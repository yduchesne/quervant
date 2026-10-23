//! Private complete committed-snapshot key selection for query mutations (M3).
//!
//! This module is deliberately a thin adapter around the existing unified
//! execution path. It does not compile, plan or evaluate queries itself: the
//! [`UnifiedSearcher::select_keys`] private visitor reuses the same compiled
//! predicate and membership machinery as normal unified search. Revisions are
//! derived from the committed mutation-state winner, never a physical segment
//! ordinal, so obsolete physical versions cannot become tombstones.

use crate::analysis::{AnalyzerRegistry, Cancellation};
use crate::contract::budget::Budgets;
use crate::contract::document::DocumentKey;
use crate::contract::error::QueryError;
use crate::contract::mutation::QueryMutationSelector;
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;
use crate::index::error::{IndexError, IndexResult};
use crate::index::mutation_state::MutationStateV1;
use crate::search::SearchError;
use crate::search::{CompleteKeySelection, SearchLimits, UnifiedSearcher};

/// One selected logical key with its committed revision evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SelectedKey {
    pub(crate) key: DocumentKey,
    pub(crate) revision: u64,
}

/// The outcome of resolving one query selector.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum SelectionOutcome {
    /// Complete, deduplicated, ascending selected keys.
    Complete(Vec<SelectedKey>),
    /// The first distinct matching key above the effective bound.
    LimitExceeded { limit: u64, matched: u64 },
}

/// Resolve every live logical key matching `selector.query` on `snapshot`.
///
/// The caller must hold one immutable committed snapshot for the whole
/// selection phase and must pass the already-computed effective bound
/// `min(selector.max_matches, limits.max_query_matches, limits.max_batch_keys)`.
/// Any search failure is propagated as a typed index error; a partial key set is
/// never returned.
#[allow(clippy::too_many_arguments)]
pub(crate) fn select_query_keys(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    search_limits: SearchLimits,
    budgets: &Budgets,
    committed_state: Option<&MutationStateV1>,
    selector: &QueryMutationSelector,
    effective_limit: u64,
    cancel: &dyn Cancellation,
) -> IndexResult<SelectionOutcome> {
    let keys = UnifiedSearcher::new(snapshot, schema, registry, search_limits)
        .select_keys(&selector.query, effective_limit, budgets, cancel)
        .map_err(search_error_to_index)?;
    match keys {
        CompleteKeySelection::LimitExceeded { limit, matched } => {
            Ok(SelectionOutcome::LimitExceeded { limit, matched })
        }
        CompleteKeySelection::Complete(keys) => {
            let mut selected = Vec::new();
            selected
                .try_reserve_exact(keys.len())
                .map_err(|_| IndexError::ResourceLimit {
                    limit: effective_limit,
                    requested: keys.len() as u64,
                })?;
            for key in keys {
                let row = committed_state
                    .and_then(|state| state.row(&key))
                    .ok_or_else(|| IndexError::CorruptCommittedState {
                        detail: "query selection key has no committed mutation-state row"
                            .to_owned(),
                    })?;
                if !row.is_live() {
                    return Err(IndexError::CorruptCommittedState {
                        detail: "query selection key is not live in committed mutation state"
                            .to_owned(),
                    });
                }
                selected.push(SelectedKey {
                    key,
                    revision: row.revision,
                });
            }
            // The visitor already returns ascending keys; keep the invariant
            // explicit at the mutation boundary.
            selected.sort_by(|left, right| left.key.cmp(&right.key));
            Ok(SelectionOutcome::Complete(selected))
        }
    }
}

/// Convert a search failure into an existing typed index failure.
///
/// No variant is treated as a partial or empty selection.
fn search_error_to_index(error: SearchError) -> IndexError {
    match error {
        SearchError::Query(error) => IndexError::Contract(error),
        SearchError::Analysis(error) => IndexError::Analysis(error),
        SearchError::Segment(error) => IndexError::Segment(error),
        SearchError::Index(error) => error,
        SearchError::ResourceLimit { limit, requested } => {
            IndexError::ResourceLimit { limit, requested }
        }
        SearchError::Cancelled => IndexError::Cancelled,
        SearchError::CorruptIndex { detail } => IndexError::CorruptCommittedState { detail },
        SearchError::UnsupportedOperator { operator } => {
            IndexError::Contract(QueryError::ExecutionFailure { reason: operator })
        }
        SearchError::InvalidScore { detail } => {
            IndexError::Contract(QueryError::ExecutionFailure { reason: detail })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::AnalysisError;
    use crate::contract::error::InvalidQueryReason;
    use crate::segment::SegmentError;

    #[test]
    fn every_search_failure_maps_to_an_existing_index_failure_without_partial_success() {
        let mappings = [
            SearchError::Query(QueryError::InvalidQuery(InvalidQueryReason::UnknownField {
                field: "f".to_owned(),
            })),
            SearchError::Analysis(AnalysisError::EmptyTerm),
            SearchError::Segment(SegmentError::InvalidVarint { context: "x" }),
            SearchError::Index(IndexError::WriterBusy),
            SearchError::ResourceLimit {
                limit: 3,
                requested: 4,
            },
            SearchError::Cancelled,
            SearchError::CorruptIndex {
                detail: "corrupt".to_owned(),
            },
            SearchError::UnsupportedOperator { operator: "op" },
            SearchError::InvalidScore { detail: "nan" },
        ];
        for error in mappings {
            let mapped = search_error_to_index(error);
            let _ = mapped.to_string();
        }
        assert!(matches!(
            search_error_to_index(SearchError::Cancelled),
            IndexError::Cancelled
        ));
        assert!(matches!(
            search_error_to_index(SearchError::ResourceLimit {
                limit: 3,
                requested: 4
            }),
            IndexError::ResourceLimit {
                limit: 3,
                requested: 4
            }
        ));
        assert!(matches!(
            search_error_to_index(SearchError::CorruptIndex {
                detail: "d".to_owned()
            }),
            IndexError::CorruptCommittedState { .. }
        ));
        assert!(matches!(
            search_error_to_index(SearchError::UnsupportedOperator { operator: "op" }),
            IndexError::Contract(QueryError::ExecutionFailure { .. })
        ));
        assert!(matches!(
            search_error_to_index(SearchError::InvalidScore { detail: "nan" }),
            IndexError::Contract(QueryError::ExecutionFailure { .. })
        ));
        assert!(matches!(
            search_error_to_index(SearchError::Index(IndexError::WriterBusy)),
            IndexError::WriterBusy
        ));
    }
}
