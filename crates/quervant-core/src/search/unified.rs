//! Unified snapshot-bound compound query execution (PR 14 final design).
//!
//! Pure lexical and pure typed/neutral queries delegate to the existing lexical
//! and typed executors, preserving their exact scoring, sorting, cursor and
//! aggregation behavior. Mixed lexical+typed queries are executed by one compiled
//! Boolean tree (`unified_plan`) over the effective-live universe, scoring only
//! positive lexical leaves with the existing PR 7 BM25 scorer and evaluating
//! typed leaves with the existing typed predicate evaluator.
//!
//! Every internal match carries `SelectedHit { segment_index, doc_id, key, ... }`,
//! so projection reads exactly that physical document rather than rescanning for
//! a logical key.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::budget::Budgets;
use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::query::Query;
use crate::contract::result::{Projection, Sort, TopK};
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;
use crate::segment::SegmentReader;

use super::error::{SearchError, SearchResult};
use super::execute::{self, CandidateBudget, LeafData, SearchWork};
use super::expand::expand_query;
use super::projection::{ProjectionLedger, ProjectionPlan, projected_hit_bytes};
use super::score::compute_stats;
use super::typed::{self, ScanGuard};
use super::typed_compare::{ColumnAccess, SortValue, compare_candidates, sort_tuple_for_doc};
use super::unified_plan::{self, UnifiedNode, UnifiedPlan};
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

        match classify(&request.query) {
            QueryClass::Neutral if request.sort.fields.is_empty() => {
                let (keys, scores, total_hits) = self.lexical_search(request, budgets, cancel)?;
                self.finish_delegated(keys, scores, total_hits, &projection, &mut ledger)
            }
            QueryClass::Neutral | QueryClass::Typed => {
                let (keys, scores, total_hits) = self.typed_search(request, budgets, cancel)?;
                self.finish_delegated(keys, scores, total_hits, &projection, &mut ledger)
            }
            QueryClass::Lexical => {
                if !request.sort.fields.is_empty() {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "lexical_explicit_sort",
                    });
                }
                let (keys, scores, total_hits) = self.lexical_search(request, budgets, cancel)?;
                self.finish_delegated(keys, scores, total_hits, &projection, &mut ledger)
            }
            QueryClass::Mixed => self.execute_mixed(request, &projection, &mut ledger, cancel),
        }
    }

    #[allow(clippy::type_complexity)]
    fn finish_delegated(
        &self,
        keys: Vec<DocumentKey>,
        scores: Vec<Option<f64>>,
        total_hits: u64,
        projection: &ProjectionPlan,
        ledger: &mut ProjectionLedger,
    ) -> SearchResult<UnifiedResponse> {
        let fields = project_selected(self.snapshot, projection, ledger, &keys)?;
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

    fn execute_mixed(
        &self,
        request: &UnifiedRequest,
        projection: &ProjectionPlan,
        ledger: &mut ProjectionLedger,
        cancel: &dyn Cancellation,
    ) -> SearchResult<UnifiedResponse> {
        if request
            .sort
            .fields
            .iter()
            .any(|field| field.distance_from.is_some())
        {
            return Err(SearchError::UnsupportedOperator {
                operator: "mixed_geo_distance_sort",
            });
        }
        let plan = unified_plan::compile(
            &request.query,
            self.schema,
            self.registry,
            &self.limits,
            &AnalysisLimits::default(),
            cancel,
        )?;
        let selected = self.collect_mixed(&plan, request, cancel)?;
        let total_hits = selected.len() as u64;
        let page = self.select_page(selected, request);
        let fields = project_selected_hits(self.snapshot, projection, ledger, &page)?;
        let hits = page
            .into_iter()
            .zip(fields)
            .map(|(hit, fields)| ProjectedHit {
                key: hit.key,
                score: hit.score,
                fields,
            })
            .collect();
        Ok(UnifiedResponse {
            hits,
            total_hits,
            generation: self.snapshot.generation(),
            view_ordinal: self.snapshot.view_ordinal(),
        })
    }

    fn collect_mixed(
        &self,
        plan: &UnifiedPlan,
        request: &UnifiedRequest,
        cancel: &dyn Cancellation,
    ) -> SearchResult<Vec<SelectedHit>> {
        let mut guards = Vec::new();
        guards
            .try_reserve_exact(self.snapshot.segment_count())
            .map_err(|_| SearchError::ResourceLimit {
                limit: self.limits.max_segment_candidate_entries(),
                requested: self.snapshot.segment_count() as u64,
            })?;
        for index in 0..self.snapshot.segment_count() {
            guards.push(self.snapshot.open_segment_reader(index)?);
        }
        let readers: Vec<&SegmentReader> = guards.iter().map(|guard| guard.reader()).collect();
        if plan.has_lexical() {
            for reader in &readers {
                if reader.schema() != &plan.codec {
                    return Err(SearchError::CorruptIndex {
                        detail: "segment schema/analyzer bindings do not match the supplied schema"
                            .to_owned(),
                    });
                }
            }
        }
        let mut live: Vec<Rc<Vec<bool>>> = Vec::new();
        for (index, reader) in readers.iter().enumerate() {
            live.push(self.snapshot.effective_live_docs(index, reader)?);
        }
        let synth = plan::synthetic_query(plan);
        let mut work = SearchWork::new(self.limits.max_total_work_units(), cancel)
            .with_scanned_limit(self.limits.max_scanned_posting_occurrences());
        let expansion = expand_query(&readers, &synth, &self.limits, &mut work, cancel)?;
        let stats = compute_stats(
            &readers,
            &live,
            &plan.scoring_field_ids,
            expansion.positive_terms(),
            &self.limits,
            &mut work,
            cancel,
        )?;
        let mut budget = CandidateBudget::new(&self.limits);
        let mut guard = ScanGuard::new(
            self.limits
                .max_total_work_units()
                .min(self.limits.max_typed_work_units()),
            cancel,
        );
        let mut global: BTreeMap<DocumentKey, SelectedHit> = BTreeMap::new();
        let mut global_bytes = 0u64;
        for (segment_index, reader) in readers.iter().enumerate() {
            let columns = ColumnAccess::open(reader)?;
            let json = typed::JsonAccess::open(reader)?;
            let mut typed_geo: Vec<typed::GeoMembership> = Vec::new();
            for typed_leaf in &plan.typed_leaves {
                let mut scratch =
                    typed::GeoScratchBudget::new(self.limits.max_total_candidate_bytes());
                typed_geo.push(typed::build_geo_membership(
                    &typed_leaf.geo_leaves,
                    reader.spatial(),
                    reader,
                    &columns,
                    &mut guard,
                    &mut scratch,
                    self.limits.max_segment_candidate_entries(),
                )?);
            }
            let scored = execute::evaluate_lexical_with(
                reader,
                &plan.lexical_leaves,
                &expansion,
                &stats,
                &plan.positive_lexical,
                segment_index,
                &live[segment_index],
                &mut budget,
                &mut work,
                cancel,
                |doc_id, leaf_data| {
                    evaluate_unified(
                        &plan.root,
                        doc_id,
                        leaf_data,
                        &plan.typed_leaves,
                        &columns,
                        &json,
                        &typed_geo,
                        &mut guard,
                    )
                },
            )?;
            for (doc_id, score) in scored {
                let key = reader.doc_key(doc_id)?;
                let tuple = if request.sort.fields.is_empty() {
                    Vec::new()
                } else {
                    sort_tuple_for_doc(&columns, reader.schema(), &request.sort, None, doc_id)?
                };
                let bytes = key.as_str().len() as u64 + 64;
                global_bytes =
                    global_bytes
                        .checked_add(bytes)
                        .ok_or_else(|| SearchError::ResourceLimit {
                            limit: self.limits.max_total_candidate_bytes(),
                            requested: u64::MAX,
                        })?;
                if global_bytes > self.limits.max_total_candidate_bytes() {
                    return Err(SearchError::ResourceLimit {
                        limit: self.limits.max_total_candidate_bytes(),
                        requested: global_bytes,
                    });
                }
                let hit = SelectedHit {
                    segment_index,
                    doc_id,
                    key: key.clone(),
                    score: Some(score),
                    sort_tuple: tuple,
                };
                if global.insert(key, hit).is_some() {
                    return Err(SearchError::CorruptIndex {
                        detail: "duplicate live document key across segments".to_owned(),
                    });
                }
            }
        }
        Ok(global.into_values().collect())
    }

    fn select_page(
        &self,
        mut selected: Vec<SelectedHit>,
        request: &UnifiedRequest,
    ) -> Vec<SelectedHit> {
        let relevance = request.sort.fields.is_empty();
        if relevance {
            selected.sort_by(default_relevance_cmp);
        } else {
            selected.sort_by(|a, b| {
                compare_candidates(&a.sort_tuple, &a.key, &b.sort_tuple, &b.key, &request.sort)
            });
        }
        selected.truncate(request.top_k.limit);
        selected
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

/// An internal selected match with exact physical identity.
#[derive(Debug, Clone)]
struct SelectedHit {
    segment_index: usize,
    doc_id: u64,
    key: DocumentKey,
    score: Option<f64>,
    sort_tuple: Vec<SortValue>,
}

fn default_relevance_cmp(a: &SelectedHit, b: &SelectedHit) -> Ordering {
    let a_score = a.score.unwrap_or(0.0);
    let b_score = b.score.unwrap_or(0.0);
    match b_score.total_cmp(&a_score) {
        Ordering::Equal => a.key.cmp(&b.key),
        other => other,
    }
}

#[allow(clippy::too_many_arguments)]
fn evaluate_unified(
    node: &UnifiedNode,
    doc_id: u64,
    leaf_data: &[LeafData],
    typed_leaves: &[typed::Compiled],
    columns: &ColumnAccess<'_>,
    json: &typed::JsonAccess<'_>,
    typed_geo: &[typed::GeoMembership],
    guard: &mut ScanGuard<'_>,
) -> SearchResult<bool> {
    match node {
        UnifiedNode::MatchAll => Ok(true),
        UnifiedNode::Lexical(index) => Ok(leaf_data
            .get(*index)
            .is_some_and(|leaf| leaf.matches(doc_id))),
        UnifiedNode::Typed(index) => {
            let compiled = typed_leaves
                .get(*index)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "typed leaf index out of range".to_owned(),
                })?;
            let geo = typed_geo
                .get(*index)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "typed geo membership missing".to_owned(),
                })?;
            typed::evaluate_query(guard, columns, json, geo, &compiled.root, doc_id)
        }
        UnifiedNode::And(children) => {
            for child in children {
                if !evaluate_unified(
                    child,
                    doc_id,
                    leaf_data,
                    typed_leaves,
                    columns,
                    json,
                    typed_geo,
                    guard,
                )? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        UnifiedNode::Or(children) => {
            for child in children {
                if evaluate_unified(
                    child,
                    doc_id,
                    leaf_data,
                    typed_leaves,
                    columns,
                    json,
                    typed_geo,
                    guard,
                )? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
        UnifiedNode::Not(inner) => Ok(!evaluate_unified(
            inner,
            doc_id,
            leaf_data,
            typed_leaves,
            columns,
            json,
            typed_geo,
            guard,
        )?),
    }
}

/// The synthetic lexical container used for expansion and statistics.
mod plan {
    use super::UnifiedPlan;
    use crate::search::plan::{CompiledNode, CompiledQuery};

    pub(super) fn synthetic_query(plan: &UnifiedPlan) -> CompiledQuery {
        CompiledQuery {
            root: CompiledNode::MatchAll,
            leaves: plan.lexical_leaves.clone(),
            positive_leaf_indices: plan.positive_lexical.clone(),
            scoring_field_ids: plan.scoring_field_ids.clone(),
            codec: plan.codec.clone(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum QueryClass {
    Neutral,
    Lexical,
    Typed,
    Mixed,
}

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

/// Projection for the pure delegated paths, which only expose logical keys.
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

/// Projection using exact physical `(segment_index, doc_id)` identities.
fn project_selected_hits(
    snapshot: &ReaderSnapshot,
    plan: &ProjectionPlan,
    ledger: &mut ProjectionLedger,
    hits: &[SelectedHit],
) -> SearchResult<Vec<Vec<(String, FieldValues)>>> {
    let mut by_segment: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for (index, hit) in hits.iter().enumerate() {
        by_segment.entry(hit.segment_index).or_default().push(index);
    }
    let mut out: Vec<Option<Vec<(String, FieldValues)>>> = (0..hits.len()).map(|_| None).collect();
    for (segment_index, indices) in by_segment {
        let guard = snapshot.open_segment_reader(segment_index)?;
        let reader = guard.reader();
        for index in indices {
            let hit = &hits[index];
            let key = reader.doc_key(hit.doc_id)?;
            if key != hit.key {
                return Err(SearchError::CorruptIndex {
                    detail: "selected hit key does not match its physical document".to_owned(),
                });
            }
            let record = reader.stored_doc(hit.doc_id)?;
            let fields = plan.project(&record);
            ledger.reserve(projected_hit_bytes(&hit.key, &fields))?;
            out[index] = Some(fields);
        }
    }
    out.into_iter()
        .map(|fields| {
            fields.ok_or_else(|| SearchError::CorruptIndex {
                detail: "selected hit was not projected".to_owned(),
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
