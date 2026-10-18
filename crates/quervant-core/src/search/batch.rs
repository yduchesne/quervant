//! Ordered serial batch execution over one resolved snapshot (PR 14).
//!
//! The envelope is validated first and rejects the whole batch on violation.
//! After acceptance, exactly one [`PerQueryOutcome`] is produced per input query
//! in positional order; a per-slot failure never erases or reorders siblings.
//! Execution is deliberately serial against one resolved snapshot until serial
//! semantics are proven.
//!
//! A single [`BatchLedger`] is shared across every slot and is never reset, so
//! cumulative response and aggregate budgets bound the whole batch.

use crate::analysis::{AnalyzerRegistry, Cancellation};
use crate::contract::batch::{
    BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest, SearchHit, SearchResponse,
};
use crate::contract::budget::{BudgetKind, BudgetPolicy};
use crate::contract::capability::CapabilitySet;
use crate::contract::error::{CancelReason, InvalidQueryReason, QueryError};
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;

use super::batch_meter::{BatchExecutionMeter, BatchMeterError};
use super::error::{SearchError, SearchResult};
use super::projection::projected_field_bytes;
use super::{ProjectedHit, SearchLimits, UnifiedRequest, UnifiedSearcher};

/// Execute an accepted batch serially against one snapshot.
///
/// The envelope (including the authoritative [`BudgetPolicy`]) is validated
/// first and rejects the whole batch on violation. Each accepted slot is then
/// validated against `supported` capabilities before execution; a per-slot
/// failure yields one typed [`PerQueryOutcome::Failure`] and never erases a
/// sibling. Execution is deliberately serial against one resolved snapshot.
#[allow(clippy::too_many_arguments)]
pub fn execute_batch(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: SearchLimits,
    batch: &BatchQueryRequest,
    policy: &BudgetPolicy,
    supported: &CapabilitySet,
    cancel: &dyn Cancellation,
) -> SearchResult<BatchQueryResponse> {
    batch.validate_envelope_with_policy(policy)?;
    // Resolve authoritative ceilings from policy for every batch-metric kind.
    // An absent policy ceiling is a typed error, never "unlimited".
    let work_limit = policy.effective(
        BudgetKind::BatchAggregate,
        batch.budget.limits.get(BudgetKind::BatchAggregate),
    )?;
    let memory_limit = policy.effective(
        BudgetKind::BatchMemoryBytes,
        batch.budget.limits.get(BudgetKind::BatchMemoryBytes),
    )?;
    let response_limit = policy.effective(
        BudgetKind::BatchResponseBytes,
        batch.budget.limits.get(BudgetKind::BatchResponseBytes),
    )?;
    let mut meter = BatchExecutionMeter::new(work_limit, memory_limit, response_limit);
    let searcher = UnifiedSearcher::new(snapshot, schema, registry, limits);
    let mut outcomes = Vec::with_capacity(batch.queries.len());
    for query in &batch.queries {
        if cancel.is_cancelled() {
            outcomes.push(PerQueryOutcome::Failure(QueryError::Cancelled {
                reason: CancelReason::ClientCancellation,
            }));
            continue;
        }
        if let Err(error) = query.validate(schema, supported) {
            outcomes.push(PerQueryOutcome::Failure(error));
            continue;
        }
        match execute_slot(&searcher, query, cancel, &mut meter) {
            Ok(response) => {
                let bytes = match response_bytes(&response) {
                    Ok(bytes) => bytes,
                    Err(error) => {
                        outcomes.push(PerQueryOutcome::Failure(to_query_error(
                            error.to_search_error(),
                        )));
                        continue;
                    }
                };
                // Retain memory for the response before committing its bytes so a
                // failure leaves neither counter advanced.
                if let Err(error) = meter.reserve_memory(bytes) {
                    outcomes.push(PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                        kind: error.kind,
                    }));
                    continue;
                }
                if let Err(error) = meter.charge_response(bytes) {
                    let _ = meter.release_memory(bytes);
                    outcomes.push(PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                        kind: error.kind,
                    }));
                    continue;
                }
                outcomes.push(PerQueryOutcome::Success(response));
            }
            Err(error) => outcomes.push(PerQueryOutcome::Failure(to_query_error(error))),
        }
    }
    BatchQueryResponse::from_outcomes_for(batch, outcomes).map_err(SearchError::from)
}

/// Deterministic logical size of one successful slot response.
///
/// Fixed per-slot/per-hit overhead, key bytes, score presence and the full
/// five-state projected field payload. Batch public cursors are fail-closed, so
/// `next_cursor` is always `None` here.
fn response_bytes(response: &SearchResponse) -> Result<u64, BatchMeterError> {
    let response_overflow = || BatchMeterError {
        kind: BudgetKind::BatchResponseBytes,
        limit: 0,
        requested: u64::MAX,
    };
    let mut bytes: u64 = 32;
    for hit in &response.hits {
        let mut hit_bytes = 24u64
            .checked_add(hit.key.as_str().len() as u64)
            .and_then(|value| value.checked_add(8))
            .ok_or_else(response_overflow)?;
        for (name, values) in &hit.fields {
            hit_bytes = hit_bytes
                .checked_add(projected_field_bytes(name, values))
                .ok_or_else(response_overflow)?;
        }
        bytes = bytes.checked_add(hit_bytes).ok_or_else(response_overflow)?;
    }
    Ok(bytes)
}

fn execute_slot(
    searcher: &UnifiedSearcher<'_>,
    query: &QueryRequest,
    cancel: &dyn Cancellation,
    meter: &mut BatchExecutionMeter,
) -> SearchResult<SearchResponse> {
    if query.aggregation.is_some() {
        return Err(SearchError::UnsupportedOperator {
            operator: "batch_aggregation_pending_stop_s1",
        });
    }
    if query.cursor.is_some() {
        // The public cursor contract cannot represent a sorted continuation
        // (STOP S2); reject rather than resume incorrectly.
        return Err(SearchError::UnsupportedOperator {
            operator: "batch_cursor_stop_s2",
        });
    }
    let request = UnifiedRequest {
        query: query.query.clone(),
        sort: query.sort.clone(),
        top_k: query.top_k,
        projection: query.projection.clone(),
        // Public PIT cursors remain fail-closed until an authoritative resolver
        // exists; `query.cursor` is rejected above.
        after: None,
    };
    let response = searcher.search_with_batch(&request, &query.budgets, cancel, meter)?;
    Ok(SearchResponse {
        hits: response.hits.iter().map(project_hit).collect(),
        total_hits: response.total_hits,
        next_cursor: None,
    })
}

/// Map an internal search failure onto the contract per-slot error, preserving
/// an already-typed contract error and wrapping execution failures.
fn to_query_error(error: SearchError) -> QueryError {
    match error {
        SearchError::Query(query) => query,
        SearchError::Cancelled => QueryError::Cancelled {
            reason: CancelReason::ClientCancellation,
        },
        SearchError::ResourceLimit { .. } => QueryError::ExecutionFailure {
            reason: "query_resource_limit",
        },
        SearchError::UnsupportedOperator { operator } => {
            QueryError::InvalidQuery(InvalidQueryReason::UnsupportedOperator {
                field: String::new(),
                operator,
            })
        }
        SearchError::Analysis(_) => QueryError::ExecutionFailure {
            reason: "analysis_failure",
        },
        SearchError::Segment(_) => QueryError::ExecutionFailure {
            reason: "segment_read_failure",
        },
        SearchError::Index(_) => QueryError::ExecutionFailure {
            reason: "index_read_failure",
        },
        SearchError::CorruptIndex { .. } => QueryError::ExecutionFailure {
            reason: "corrupt_index",
        },
        SearchError::InvalidScore { .. } => QueryError::ExecutionFailure {
            reason: "invalid_score",
        },
    }
}

/// Preserve an internal five-state projection exactly in the contract hit.
fn project_hit(hit: &ProjectedHit) -> SearchHit {
    SearchHit {
        key: hit.key.clone(),
        score: hit.score.map(|score| score as f32),
        fields: hit.fields.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::{DocumentKey, FieldValues};
    use crate::contract::value::FieldValue;

    #[test]
    fn project_hit_preserves_all_five_states() {
        let hit = ProjectedHit {
            key: DocumentKey::new("k").unwrap(),
            score: None,
            fields: vec![
                ("a".into(), FieldValues::Absent),
                ("b".into(), FieldValues::ExplicitNull),
                ("c".into(), FieldValues::Empty),
                ("d".into(), FieldValues::Single(FieldValue::I64(1))),
                (
                    "e".into(),
                    FieldValues::Multi(vec![FieldValue::I64(1), FieldValue::I64(2)]),
                ),
            ],
        };
        let projected = project_hit(&hit);
        assert_eq!(projected.fields, hit.fields);
        assert_eq!(projected.fields.len(), 5);
    }

    #[test]
    fn error_mapping_preserves_contract_errors() {
        let typed =
            QueryError::InvalidQuery(InvalidQueryReason::UnknownField { field: "x".into() });
        assert_eq!(to_query_error(SearchError::Query(typed.clone())), typed);
        assert!(matches!(
            to_query_error(SearchError::Cancelled),
            QueryError::Cancelled {
                reason: CancelReason::ClientCancellation
            }
        ));
        assert!(matches!(
            to_query_error(SearchError::ResourceLimit {
                limit: 1,
                requested: 2
            }),
            QueryError::ExecutionFailure {
                reason: "query_resource_limit"
            }
        ));
        assert!(matches!(
            to_query_error(SearchError::CorruptIndex { detail: "x".into() }),
            QueryError::ExecutionFailure {
                reason: "corrupt_index"
            }
        ));
    }

    #[test]
    fn response_bytes_are_cumulative_and_checked() {
        let mut meter = BatchExecutionMeter::new(100, 1_000, 100);
        let hit = crate::contract::batch::SearchHit {
            key: DocumentKey::new("a").unwrap(),
            score: None,
            fields: Vec::new(),
        };
        let response = SearchResponse {
            hits: vec![hit],
            total_hits: 1,
            next_cursor: None,
        };
        let bytes = response_bytes(&response).unwrap();
        assert!(meter.charge_response(bytes).is_ok());
        // The cumulative meter is not reset: a second slot exceeds 100.
        assert!(meter.charge_response(bytes).is_err());
    }
}
