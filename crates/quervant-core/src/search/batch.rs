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
use crate::contract::error::{CancelReason, InvalidBatchReason, InvalidQueryReason, QueryError};
use crate::contract::result::PitId;
use crate::contract::schema::Schema;
use crate::contract::value::Timestamp;
use crate::index::{PitHandle, ReaderSnapshot};

use super::batch_cursor::{cursor_logical_bytes, to_public, to_unified};
use super::batch_meter::{BatchExecutionMeter, BatchMeterError};
use super::error::{SearchError, SearchResult};
use super::projection::projected_field_bytes;
use super::{ProjectedHit, SearchLimits, UnifiedRequest, UnifiedSearcher};
use crate::contract::aggregation::{
    AggregationGroupValue, AggregationMetricValue, AggregationResult,
    NumericAggregate as ContractNumericAggregate,
};

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
    // A naked snapshot cannot authenticate a PIT id or resume a complete
    // continuation. Reject every PIT/cursor-bearing request before any slot is
    // validated or executed, and before creating the cumulative meter.
    if batch.shared_pit.is_some()
        || batch
            .queries
            .iter()
            .any(|query| query.pit.is_some() || query.cursor.is_some())
    {
        return Err(QueryError::InvalidBatch(InvalidBatchReason::PinnedContextRequired).into());
    }
    execute_batch_inner(
        snapshot, schema, registry, limits, batch, policy, supported, cancel, None,
    )
}

/// Execute an accepted batch against an explicitly pinned snapshot.
///
/// The supplied [`PitHandle`] is the only snapshot authority: the request's
/// shared PIT must equal the handle id, and the snapshot is obtained from the
/// handle itself. Public continuations are process-local, expire at the supplied
/// deadline, and are validated against the issuing snapshot/query/sort.
#[allow(clippy::too_many_arguments)]
pub fn execute_batch_pinned(
    pit: &PitHandle,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: SearchLimits,
    batch: &BatchQueryRequest,
    policy: &BudgetPolicy,
    supported: &CapabilitySet,
    cancel: &dyn Cancellation,
    now: Timestamp,
    cursor_deadline: Timestamp,
) -> SearchResult<BatchQueryResponse> {
    if cursor_deadline <= now {
        return Err(QueryError::InvalidBatch(InvalidBatchReason::InvalidCursorDeadline).into());
    }
    if batch.shared_pit.as_ref() != Some(pit.id()) {
        return Err(QueryError::InvalidBatch(InvalidBatchReason::ConflictingPit).into());
    }
    for query in &batch.queries {
        if query.pit.as_ref().is_some_and(|own| own != pit.id()) {
            return Err(QueryError::InvalidBatch(InvalidBatchReason::ConflictingPit).into());
        }
    }
    let context = PinnedBatchContext {
        pit_id: pit.id(),
        now,
        deadline: cursor_deadline,
    };
    execute_batch_inner(
        pit.snapshot().as_ref(),
        schema,
        registry,
        limits,
        batch,
        policy,
        supported,
        cancel,
        Some(context),
    )
}

struct PinnedBatchContext<'a> {
    pit_id: &'a PitId,
    now: Timestamp,
    deadline: Timestamp,
}

#[allow(clippy::too_many_arguments)]
fn execute_batch_inner(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: SearchLimits,
    batch: &BatchQueryRequest,
    policy: &BudgetPolicy,
    supported: &CapabilitySet,
    cancel: &dyn Cancellation,
    context: Option<PinnedBatchContext<'_>>,
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
        let validation = match context.as_ref() {
            Some(context) => query.validate_pinned(schema, supported, context.pit_id),
            None => query.validate(schema, supported),
        };
        if let Err(error) = validation {
            outcomes.push(PerQueryOutcome::Failure(error));
            continue;
        }
        match execute_slot(&searcher, query, cancel, &mut meter, context.as_ref()) {
            Ok((response, retained)) => {
                let cursor_bytes = match response.next_cursor.as_ref() {
                    Some(cursor) => match cursor_logical_bytes(cursor) {
                        Some(bytes) => bytes,
                        None => {
                            let _ = meter.memory.release_memory(retained);
                            outcomes.push(PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                                kind: BudgetKind::BatchMemoryBytes,
                            }));
                            continue;
                        }
                    },
                    None => 0,
                };
                let bytes = match response_bytes(&response) {
                    Ok(bytes) => bytes,
                    Err(error) => {
                        let _ = meter.memory.release_memory(retained);
                        outcomes.push(PerQueryOutcome::Failure(to_query_error(
                            error.to_search_error(),
                        )));
                        continue;
                    }
                };
                // The slot already retained the projected response bytes in the
                // shared memory meter via `finish_success`; cursor payload memory
                // is retained alongside it and charged exactly once here.
                if let Err(error) = meter.memory.commit_reserve(cursor_bytes) {
                    let _ = meter.memory.release_memory(retained);
                    outcomes.push(PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                        kind: error.kind,
                    }));
                    continue;
                }
                // Charge the cumulative response budget once, after the actual
                // public response size (including any cursor) is known.
                if let Err(error) = meter.response.charge_response(bytes) {
                    let _ = meter.memory.release_memory(cursor_bytes);
                    let _ = meter.memory.release_memory(retained);
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

/// Deterministic logical size of an aggregation payload. Returns `None` on
/// checked-arithmetic overflow; callers map that to their typed budget error.
pub(crate) fn aggregation_result_bytes(result: &AggregationResult) -> Option<u64> {
    let mut bytes: u64 = 32;
    for group in &result.groups {
        let mut group_bytes = 16u64.checked_add(group.key.len() as u64)?;
        group_bytes = group_bytes.checked_add(8)?;
        for component in &group.components {
            let component_bytes = match component {
                AggregationGroupValue::Missing(_) | AggregationGroupValue::Null(_) => 16,
                AggregationGroupValue::Value(value) => {
                    16u64.checked_add(value.approx_size() as u64)?
                }
            };
            group_bytes = group_bytes.checked_add(component_bytes)?;
        }
        group_bytes = group_bytes.checked_add(8)?;
        for metric in &group.metrics {
            let metric_bytes = match metric {
                AggregationMetricValue::Count(_) | AggregationMetricValue::ExactDistinct(_) => 16,
                AggregationMetricValue::Sum(value) => match value {
                    ContractNumericAggregate::Signed(_)
                    | ContractNumericAggregate::Unsigned(_)
                    | ContractNumericAggregate::Float(_) => 32,
                },
                AggregationMetricValue::Min(value) | AggregationMetricValue::Max(value) => 16u64
                    .checked_add(value.as_ref().map_or(0, |value| value.approx_size() as u64))?,
                AggregationMetricValue::Avg(_) => 16,
            };
            group_bytes = group_bytes.checked_add(metric_bytes)?;
        }
        group_bytes = group_bytes.checked_add(8)?;
        if let Some(frequencies) = &group.frequencies {
            for entry in frequencies {
                group_bytes = group_bytes
                    .checked_add(16)?
                    .checked_add(entry.value.approx_size() as u64)?;
            }
        }
        bytes = bytes.checked_add(group_bytes)?;
    }
    Some(bytes)
}

/// Deterministic logical size of one successful slot response.
///
/// Fixed per-slot/per-hit overhead, key bytes, score presence, the full
/// five-state projected field payload and any public continuation payload.
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
    if let Some(aggregation) = &response.aggregation {
        bytes = bytes
            .checked_add(aggregation_result_bytes(aggregation).ok_or_else(response_overflow)?)
            .ok_or_else(response_overflow)?;
    }
    if let Some(cursor) = &response.next_cursor {
        bytes = bytes
            .checked_add(cursor_logical_bytes(cursor).ok_or_else(response_overflow)?)
            .ok_or_else(response_overflow)?;
    }
    Ok(bytes)
}

fn execute_slot(
    searcher: &UnifiedSearcher<'_>,
    query: &QueryRequest,
    cancel: &dyn Cancellation,
    meter: &mut BatchExecutionMeter,
    context: Option<&PinnedBatchContext<'_>>,
) -> SearchResult<(SearchResponse, u64)> {
    let mut after = None;
    let mut expiry = None;
    if let Some(context) = context {
        expiry = Some(context.deadline);
        if let Some(cursor) = &query.cursor {
            cursor.validate(context.pit_id, &query.sort, context.now)?;
            // A renewed page deadline may never extend the incoming cursor.
            let previous = cursor.expires_at();
            if previous < context.deadline {
                expiry = Some(previous);
            }
            after = Some(to_unified(cursor)?);
        }
    }
    let request = UnifiedRequest {
        query: query.query.clone(),
        sort: query.sort.clone(),
        top_k: query.top_k,
        projection: query.projection.clone(),
        after,
    };
    let (response, retained) = searcher.search_with_batch_aggregation_retained(
        &request,
        query.aggregation.as_ref(),
        &query.budgets,
        cancel,
        meter,
    )?;
    let next_cursor = match (context, response.next_cursor.as_ref(), expiry) {
        (Some(context), Some(internal), Some(expiry)) => {
            match to_public(internal, context.pit_id, &query.sort, expiry) {
                Ok(cursor) => Some(cursor),
                Err(error) => {
                    let _ = meter.memory.release_memory(retained);
                    return Err(error);
                }
            }
        }
        _ => None,
    };
    Ok((
        SearchResponse {
            hits: response.hits.iter().map(project_hit).collect(),
            total_hits: response.total_hits,
            next_cursor,
            aggregation: response.aggregation,
        },
        retained,
    ))
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
            aggregation: None,
        };
        let bytes = response_bytes(&response).unwrap();
        assert!(meter.response.charge_response(bytes).is_ok());
        // The cumulative meter is not reset: a second slot exceeds 100.
        assert!(meter.response.charge_response(bytes).is_err());
    }
}
