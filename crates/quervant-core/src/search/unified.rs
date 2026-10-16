//! Unified snapshot-bound compound query execution (PR 14).
//!
//! This module composes the existing lexical and typed executors behind one
//! request/response shape and one validated projection. It deliberately does not
//! reimplement lexical scoring or typed predicate evaluation: pure lexical
//! predicates delegate to [`crate::search::LexicalSearcher`] and pure typed
//! predicates delegate to [`crate::search::TypedSearcher`].
//!
//! # Mixed predicates (STOP S1)
//!
//! A query that mixes lexical and typed leaves requires a reusable per-segment
//! lexical membership seam that does not currently exist without changing
//! lexical execution semantics. Per the PR 14 execution contract (STOP S1) this
//! module fails closed with a typed [`SearchError::UnsupportedOperator`] rather
//! than silently reimplementing BM25/postings traversal. Pure lexical `And`/
//! `Or`/`Not` trees, pure typed trees, and `MatchAll` intentionally remain
//! fully supported.
//!
//! # Cursor (STOP S2)
//!
//! The public `contract::result::Cursor` does not carry the complete sort tuple
//! required to resume a non-key sort. No unified cursor is exposed until the
//! compatibility amendment is approved; `after` is therefore rejected.

use std::collections::{BTreeMap, BTreeSet};

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::budget::Budgets;
use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::query::Query;
use crate::contract::result::{Projection, Sort, TopK};
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;

use super::error::{SearchError, SearchResult};
use super::projection::{ProjectionLedger, ProjectionPlan, projected_hit_bytes};
use super::{LexicalSearcher, SearchLimits, TypedSearchRequest, TypedSearcher};

/// One projected result.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectedHit {
    /// Byte-exact logical document key.
    pub key: DocumentKey,
    /// BM25 score for a lexical hit; `None` for a filter-only typed hit.
    pub score: Option<f64>,
    /// Projected stored fields in plan order, preserving the five-state vocabulary.
    pub fields: Vec<(String, FieldValues)>,
}

/// A complete unified response.
#[derive(Debug, Clone, PartialEq)]
pub struct UnifiedResponse {
    /// Projected hits for this page.
    pub hits: Vec<ProjectedHit>,
    /// Exact number of matching effective-live documents before truncation.
    pub total_hits: u64,
    /// Committed generation echoed from the snapshot.
    pub generation: Option<u64>,
    /// Process-local view ordinal echoed from the snapshot.
    pub view_ordinal: u64,
}

/// A unified compound request.
#[derive(Debug, Clone, PartialEq)]
pub struct UnifiedRequest {
    /// The validated compound query.
    pub query: Query,
    /// Explicit sort; empty means relevance (lexical) or key ascending (typed).
    pub sort: Sort,
    /// Bounded page size.
    pub top_k: TopK,
    /// Stored-field projection.
    pub projection: Projection,
}

impl UnifiedRequest {
    #[must_use]
    pub fn new(query: Query, top_k: TopK) -> Self {
        Self {
            query,
            sort: Sort::default(),
            top_k,
            projection: Projection::Source,
        }
    }
}

/// A snapshot-bound compound searcher.
pub struct UnifiedSearcher<'a> {
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    limits: SearchLimits,
}

impl<'a> UnifiedSearcher<'a> {
    #[must_use]
    pub fn new(
        snapshot: &'a ReaderSnapshot,
        schema: &'a Schema,
        registry: &'a AnalyzerRegistry,
        limits: SearchLimits,
    ) -> Self {
        Self {
            snapshot,
            schema,
            registry,
            limits,
        }
    }

    /// Execute a compound request against the bound snapshot.
    pub fn search(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<UnifiedResponse> {
        request.query.validate(self.schema, budgets)?;
        request.top_k.validate(budgets)?;
        let projection = ProjectionPlan::compile(&request.projection, self.schema)?;
        let mut ledger = ProjectionLedger::new(self.limits.max_total_candidate_bytes());

        let (keys, scores, total_hits) = match classify(&request.query) {
            // A neutral `MatchAll` with an explicit sort is a pure typed scan;
            // without a sort it uses the lexical engine's deterministic key order.
            QueryClass::Neutral if request.sort.fields.is_empty() => {
                self.lexical_search(request, budgets, cancel)?
            }
            QueryClass::Neutral | QueryClass::Typed => {
                self.typed_search(request, budgets, cancel)?
            }
            QueryClass::Lexical => {
                if !request.sort.fields.is_empty() {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "lexical_explicit_sort",
                    });
                }
                self.lexical_search(request, budgets, cancel)?
            }
            QueryClass::Mixed => {
                return Err(SearchError::UnsupportedOperator {
                    operator: "mixed_predicate_stop_s1",
                });
            }
        };

        let fields = project_selected(self.snapshot, &projection, &mut ledger, &keys)?;
        let hits = keys
            .into_iter()
            .zip(scores)
            .zip(fields)
            .map(|((key, score), fields)| ProjectedHit { key, score, fields })
            .collect();
        Ok(UnifiedResponse {
            hits,
            total_hits,
            generation: self.snapshot.generation(),
            view_ordinal: self.snapshot.view_ordinal(),
        })
    }

    #[allow(clippy::type_complexity)]
    fn lexical_search(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<(Vec<DocumentKey>, Vec<Option<f64>>, u64)> {
        let response = LexicalSearcher::new(self.snapshot, self.schema, self.registry, self.limits)
            .with_analysis_limits(AnalysisLimits::default())
            .search(&request.query, request.top_k, budgets, cancel)?;
        let keys = response.hits.iter().map(|hit| hit.key.clone()).collect();
        let scores = response.hits.iter().map(|hit| Some(hit.score)).collect();
        Ok((keys, scores, response.total_hits))
    }

    #[allow(clippy::type_complexity)]
    fn typed_search(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<(Vec<DocumentKey>, Vec<Option<f64>>, u64)> {
        let typed = TypedSearchRequest {
            query: request.query.clone(),
            sort: request.sort.clone(),
            top_k: request.top_k,
            after: None,
            primary_time_field: None,
        };
        let response = TypedSearcher::new(self.snapshot, self.schema, self.limits)
            .search(&typed, budgets, cancel)?;
        let keys = response.hits.iter().map(|hit| hit.key.clone()).collect();
        let scores = vec![None; response.hits.len()];
        Ok((keys, scores, response.total_hits))
    }
}

impl std::fmt::Debug for UnifiedSearcher<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UnifiedSearcher")
            .field("segments", &self.snapshot.segment_count())
            .field("generation", &self.snapshot.generation())
            .finish()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum QueryClass {
    Neutral,
    Lexical,
    Typed,
    Mixed,
}

/// Classify a query tree as neutral (`MatchAll` only), pure lexical, pure typed
/// or mixed.
fn classify(query: &Query) -> QueryClass {
    let mut lexical = false;
    let mut typed = false;
    collect_leaves(query, &mut lexical, &mut typed);
    match (lexical, typed) {
        (true, true) => QueryClass::Mixed,
        (true, false) => QueryClass::Lexical,
        (false, true) => QueryClass::Typed,
        (false, false) => QueryClass::Neutral,
    }
}

fn collect_leaves(query: &Query, lexical: &mut bool, typed: &mut bool) {
    match query {
        Query::MatchAll => {}
        Query::Term { .. }
        | Query::Phrase { .. }
        | Query::Prefix { .. }
        | Query::Glob { .. }
        | Query::Regex { .. }
        | Query::Fuzzy { .. } => *lexical = true,
        Query::And(children) | Query::Or(children) => {
            for child in children {
                collect_leaves(child, lexical, typed);
            }
        }
        Query::Not(inner) => collect_leaves(inner, lexical, typed),
        _ => *typed = true,
    }
}

/// Decode, project and charge only the stored records for the selected keys.
fn project_selected(
    snapshot: &ReaderSnapshot,
    plan: &ProjectionPlan,
    ledger: &mut ProjectionLedger,
    keys: &[DocumentKey],
) -> SearchResult<Vec<Vec<(String, FieldValues)>>> {
    if keys.is_empty() {
        return Ok(Vec::new());
    }
    let wanted: BTreeSet<&DocumentKey> = keys.iter().collect();
    let mut by_key: BTreeMap<DocumentKey, Vec<(String, FieldValues)>> = BTreeMap::new();
    for index in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(index)?;
        let reader = guard.reader();
        let doc_keys = reader.doc_keys()?;
        if !doc_keys.iter().any(|key| wanted.contains(key)) {
            continue;
        }
        let stored = reader.stored()?;
        for (doc_id, key) in doc_keys.iter().enumerate() {
            if !wanted.contains(key) {
                continue;
            }
            let record = stored
                .get(doc_id)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "stored record missing for selected key".to_owned(),
                })?;
            let fields = plan.project(record);
            ledger.reserve(projected_hit_bytes(key, &fields))?;
            by_key.insert(key.clone(), fields);
        }
    }
    keys.iter()
        .map(|key| {
            by_key
                .get(key)
                .cloned()
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "selected hit has no stored record".to_owned(),
                })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::result::TopK;
    use crate::contract::value::FieldValue;

    fn lexical(field: &str) -> Query {
        Query::Term {
            field: field.to_owned(),
            value: FieldValue::Text("x".to_owned()),
        }
    }

    fn typed(field: &str) -> Query {
        Query::Exists {
            field: field.to_owned(),
        }
    }

    #[test]
    fn classification_pure_and_mixed() {
        assert_eq!(classify(&Query::MatchAll), QueryClass::Neutral);
        assert_eq!(classify(&lexical("title")), QueryClass::Lexical);
        assert_eq!(classify(&typed("n")), QueryClass::Typed);
        assert_eq!(
            classify(&Query::And(vec![typed("n"), typed("m")])),
            QueryClass::Typed
        );
        assert_eq!(
            classify(&Query::Not(Box::new(typed("n")))),
            QueryClass::Typed
        );
        assert_eq!(
            classify(&Query::And(vec![lexical("title"), typed("n")])),
            QueryClass::Mixed
        );
        assert_eq!(
            classify(&Query::Or(vec![
                Query::MatchAll,
                lexical("title"),
                typed("n")
            ])),
            QueryClass::Mixed
        );
    }

    #[test]
    fn request_constructor_defaults() {
        let request = UnifiedRequest::new(Query::MatchAll, TopK::new(1).unwrap());
        assert_eq!(request.projection, Projection::Source);
        assert!(request.sort.fields.is_empty());
    }
}
