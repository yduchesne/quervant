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
use crate::contract::budget::BudgetKind;
use crate::contract::error::{CancelReason, InvalidQueryReason, QueryError};
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;

use super::error::{SearchError, SearchResult};
use super::projection::projected_hit_bytes;
use super::{ProjectedHit, SearchLimits, UnifiedRequest, UnifiedSearcher};

/// Execute an accepted batch serially against one snapshot.
pub fn execute_batch(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: SearchLimits,
    batch: &BatchQueryRequest,
    cancel: &dyn Cancellation,
) -> SearchResult<BatchQueryResponse> {
    batch.validate_envelope()?;
    let mut ledger = BatchLedger::from_batch(batch);
    let searcher = UnifiedSearcher::new(snapshot, schema, registry, limits);
    let mut outcomes = Vec::with_capacity(batch.queries.len());
    for query in &batch.queries {
        if cancel.is_cancelled() {
            outcomes.push(PerQueryOutcome::Failure(QueryError::InvalidQuery(
                InvalidQueryReason::UnsupportedOperator {
                    field: String::new(),
                    operator: "batch_cancelled",
                },
            )));
            continue;
        }
        outcomes.push(match execute_slot(&searcher, &mut ledger, query, cancel) {
            Ok(response) => PerQueryOutcome::Success(response),
            Err(error) => PerQueryOutcome::Failure(to_query_error(error)),
        });
    }
    BatchQueryResponse::from_outcomes_for(batch, outcomes).map_err(SearchError::from)
}

fn execute_slot(
    searcher: &UnifiedSearcher<'_>,
    ledger: &mut BatchLedger,
    query: &QueryRequest,
    cancel: &dyn Cancellation,
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
    };
    let response = searcher.search(&request, &query.budgets, cancel)?;
    ledger.charge_response(&response.hits)?;
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
        SearchError::ResourceLimit { .. } => QueryError::BudgetExceeded {
            kind: BudgetKind::BatchAggregate,
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

/// A cumulative, shared batch ledger.
struct BatchLedger {
    response_budget: Option<u64>,
    response_used: u64,
    aggregate_budget: Option<u64>,
    aggregate_used: u64,
}

impl BatchLedger {
    fn from_batch(batch: &BatchQueryRequest) -> Self {
        Self {
            response_budget: batch.budget.limits.get(BudgetKind::BatchResponseBytes),
            response_used: 0,
            aggregate_budget: batch.budget.limits.get(BudgetKind::BatchAggregate),
            aggregate_used: 0,
        }
    }

    /// Charge one slot's projected response and commit the counters on success.
    /// The shared meter is never reset between slots.
    fn charge_response(&mut self, hits: &[ProjectedHit]) -> SearchResult<()> {
        let mut bytes = 0u64;
        for hit in hits {
            bytes = bytes.saturating_add(projected_hit_bytes(&hit.key, &hit.fields));
        }
        let projected = self.response_used.saturating_add(bytes);
        if let Some(budget) = self.response_budget {
            if projected > budget {
                return Err(SearchError::ResourceLimit {
                    limit: budget,
                    requested: projected,
                });
            }
        }
        let aggregate = self.aggregate_used.saturating_add(hits.len() as u64);
        if let Some(budget) = self.aggregate_budget {
            if aggregate > budget {
                return Err(SearchError::ResourceLimit {
                    limit: budget,
                    requested: aggregate,
                });
            }
        }
        self.response_used = projected;
        self.aggregate_used = aggregate;
        Ok(())
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
    use crate::contract::budget::Budgets;
    use crate::contract::document::{DocumentKey, FieldValues};
    use crate::contract::query::Query;
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
            QueryError::BudgetExceeded {
                kind: BudgetKind::BatchAggregate
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
    fn ledger_accumulates_and_bounds() {
        let batch = BatchQueryRequest::new(
            vec![QueryRequest::new(Query::MatchAll)],
            None,
            crate::contract::batch::BatchBudget::new(4).with_limits(
                Budgets::new()
                    .with(BudgetKind::BatchResponseBytes, 40)
                    .unwrap(),
            ),
        );
        let mut ledger = BatchLedger::from_batch(&batch);
        let hit = ProjectedHit {
            key: DocumentKey::new("a").unwrap(),
            score: None,
            fields: Vec::new(),
        };
        assert!(ledger.charge_response(std::slice::from_ref(&hit)).is_ok());
        // The shared meter is not reset: the second identical slot exceeds 40.
        assert!(matches!(
            ledger.charge_response(std::slice::from_ref(&hit)),
            Err(SearchError::ResourceLimit { .. })
        ));
    }
}
