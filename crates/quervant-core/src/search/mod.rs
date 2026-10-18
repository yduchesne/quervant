//! Standalone snapshot-bound lexical search (PR 7).
//!
//! This module is a read-only executor over PR 6 [`ReaderSnapshot`]s and PR 5
//! immutable segments. It supports exact lexical `Term`s, positional `Phrase`s,
//! arbitrarily nested `And`/`Or`/`Not`, `MatchAll`, deterministic BM25 ranking and
//! bounded top-K with exact hit counts. It compiles a private query representation
//! (field ids and analyzed terms) and never mutates a snapshot, writer or segment.
//!
//! Unsupported contract operators (prefix/glob/regex, typed ranges, JSON, geo,
//! `In`/`NotIn`, etc.) fail closed with a typed [`SearchError::UnsupportedOperator`]
//! before any segment is opened.
//!
//! # Ranking policy (v1)
//!
//! BM25 with `k1 = 1.2` and `b = 0.75`. A document's score is the sum of the
//! distinct positive leaf contributions that match it: a `Term` leaf contributes
//! each of its analyzed terms once, and a `Phrase` leaf contributes its distinct
//! constituent terms once when the phrase matches. Duplicate clauses share a
//! compiled leaf, so repeated clauses do not inflate scores.
//!
//! **Scoring eligibility (Amendment 01).** Boolean membership is computed by the
//! full tree; ranking is a separate pass. A compiled leaf is scoring-eligible iff
//! it is reachable from the root through an **even** number of `Not` nodes. Such a
//! leaf contributes whenever the returned document also matches that leaf, even if
//! another `Or` branch alone was sufficient for membership. A leaf reachable only
//! through odd/negative polarity contributes exactly zero, and negation never
//! increases a score. `NOT NOT Term(x)` is positive; `NOT(AND(...))` makes every
//! descendant negative; `MatchAll` and pure-negative queries yield zero scores.

mod analytics;
mod automaton;
mod batch;
mod error;
mod execute;
mod expand;
mod geo;
mod limits;
mod phrase;
mod plan;
mod projection;
mod score;
mod term_fst;
mod topk;
mod typed;
mod typed_compare;
mod unified;
mod unified_cursor;
mod unified_plan;
mod work;

pub use analytics::{
    AggregateGroup, AggregateMetric, AggregateRequest, AggregateResponse, FrequencyTopK,
    GroupValue, MAX_GROUP_FIELDS, MetricValue, NumericAggregate, TimeBucket,
};
pub use batch::execute_batch;
pub use error::{SearchError, SearchResult};
pub use limits::SearchLimits;
pub use projection::{
    ProjectionLedger, ProjectionPlan, projected_field_bytes, projected_hit_bytes,
};
pub use typed::{
    TypedCursor, TypedHit, TypedScanDiagnostics, TypedSearchRequest, TypedSearchResponse,
    TypedSearcher,
};
pub use typed_compare::SortValue;
pub use unified::{ProjectedHit, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
pub use unified_cursor::UnifiedCursor;

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::budget::Budgets;
use crate::contract::document::DocumentKey;
use crate::contract::query::Query;
use crate::contract::result::TopK;
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;

/// One ranked result.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchHit {
    /// Byte-exact logical document key.
    pub key: DocumentKey,
    /// Finite, nonnegative BM25 score.
    pub score: f64,
}

/// A complete lexical search response.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchResponse {
    /// Ranked top-K hits, best first.
    pub hits: Vec<SearchHit>,
    /// Exact number of unique matching live documents, before top-K truncation.
    pub total_hits: u64,
    /// The committed generation echoed from the captured snapshot.
    pub generation: Option<u64>,
    /// The process-local view ordinal echoed from the captured snapshot.
    pub view_ordinal: u64,
}

/// A concrete lexical searcher bound to one immutable snapshot.
///
/// The searcher borrows the snapshot, the caller-supplied schema and the analyzer
/// registry. It is deliberately not a query planner or index lifecycle manager:
/// callers obtain a [`ReaderSnapshot`] from `Index`/`IndexWriter`/`PitHandle`.
pub struct LexicalSearcher<'a> {
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    limits: SearchLimits,
    analysis_limits: AnalysisLimits,
}

impl<'a> LexicalSearcher<'a> {
    /// Bind a searcher to a snapshot, schema, registry and explicit search limits.
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
            analysis_limits: AnalysisLimits::default(),
        }
    }

    /// Replace the analysis limits used for search-time query analysis.
    #[must_use]
    pub fn with_analysis_limits(mut self, limits: AnalysisLimits) -> Self {
        self.analysis_limits = limits;
        self
    }

    /// The configured search limits.
    #[must_use]
    pub const fn limits(&self) -> &SearchLimits {
        &self.limits
    }

    /// Execute `query` against the captured snapshot.
    ///
    /// Validation runs before any segment read; unsupported operators fail closed
    /// and no partial response is ever returned.
    pub fn search(
        &self,
        query: &Query,
        top_k: TopK,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<SearchResponse> {
        query.validate(self.schema, budgets)?;
        top_k.validate(budgets)?;
        let compiled = plan::compile(
            query,
            self.schema,
            self.registry,
            &self.limits,
            &self.analysis_limits,
            cancel,
        )?;
        execute::execute_search(self.snapshot, &compiled, &self.limits, top_k, cancel)
    }
}

impl std::fmt::Debug for LexicalSearcher<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LexicalSearcher")
            .field("segments", &self.snapshot.segment_count())
            .field("generation", &self.snapshot.generation())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;
    use crate::index::Index;
    use crate::storage::MemoryDirectory;

    #[test]
    fn searcher_accessors_and_empty_snapshot() {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap();
        let registry = AnalyzerRegistry::builtin();
        let index = Index::create(
            Arc::new(MemoryDirectory::new()),
            schema.clone(),
            registry.clone(),
        )
        .unwrap();
        let snapshot = index.snapshot();
        let searcher = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        assert_eq!(
            searcher.limits().max_compiled_nodes(),
            SearchLimits::default().max_compiled_nodes()
        );
        let searcher = searcher.with_analysis_limits(AnalysisLimits::default());
        assert!(!format!("{searcher:?}").is_empty());
        let response = searcher
            .search(
                &Query::MatchAll,
                TopK::new(1).unwrap(),
                &Budgets::new(),
                &NeverCancel,
            )
            .unwrap();
        assert_eq!(response.total_hits, 0);
        assert!(response.hits.is_empty());
        assert_eq!(response.generation, None);
        assert_eq!(response.view_ordinal, 0);
    }
}
