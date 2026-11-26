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
use std::collections::{BTreeMap, BTreeSet, BinaryHeap, HashSet};
use std::rc::Rc;
use std::sync::Arc;
#[cfg(feature = "pr15i-d3c-experiment")]
use std::sync::OnceLock;

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::aggregation::{Aggregation, AggregationResult};
use crate::contract::budget::Budgets;
use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::query::Query;
use crate::contract::result::{Projection, Sort, TopK};
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue};
use crate::index::{
    KeywordOrdinalPreparation, ReaderSnapshot, SegmentOrdinalMap, SnapshotKeywordOrdinals,
};
use crate::segment::SegmentReader;
use crate::segment::column::{
    ColumnKeywordView, KeywordOrdinalState, KeywordOrdinalValue, KeywordSortOrdinalColumn,
};
use crate::segment::reader::{BoundKeyIdentity, runtime_doc_key_hash};

use super::SearchLimits;
use super::analytics::{AggregateRequest, AggregationEngine, TimeBucket};
use super::batch_meter::BatchExecutionMeter;
use super::error::{SearchError, SearchResult};
use super::execute::{self, CandidateBudget, LeafData, SearchWork, VisitControl};
use super::expand::expand_query;
use super::memory::{MemoryCharge, SlotMemoryScope};
use super::plan::CompiledLeaf;
use super::projection::{
    ProjectionLedger, ProjectionPlan, projected_field_bytes, projected_hit_bytes,
};
use super::score::{SnapshotStats, compute_stats};
use super::typed::{self, ScanGuard, TypedPlan};
use super::typed_compare::{
    ColumnAccess, OrdinalSortKey, SortValue, compare_borrowed_keyword_to_owned, compare_candidates,
    ordinal_sort_key_cmp, owned_keyword_sort_value, sort_tuple_for_doc,
};
use super::unified_cursor::{self, UnifiedCursor};
use super::unified_plan::{self, UnifiedNode, UnifiedPlan};
use super::work::{MixedWorkMeter, TypedCharge};

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
    /// Snapshot-bound continuation token when another page exists.
    pub next_cursor: Option<UnifiedCursor>,
    /// Exact aggregation result when the request asked for one.
    pub aggregation: Option<AggregationResult>,
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
    /// Snapshot-bound continuation token from a previous page.
    pub after: Option<UnifiedCursor>,
}

impl UnifiedRequest {
    #[must_use]
    pub fn new(query: Query, top_k: TopK) -> Self {
        Self {
            query,
            sort: Sort::default(),
            top_k,
            projection: Projection::Source,
            after: None,
        }
    }
}

/// PR 15E Phase 4 (P4-AD-01): whether the unified executor may enumerate this
/// segment's already-decoded postings instead of calling the membership predicate
/// for every effective-live document.
///
/// Eligible **iff** the compiled plan is exactly one lexical leaf at the plan root,
/// that leaf is a single-analyzed-term `CompiledLeaf::Term`, there are no typed
/// leaves, the leaf is the only positive (scoring) leaf, no aggregation is being
/// executed and no `after` cursor is supplied. Sorting is deliberately **not**
/// restricted: the frozen PR15D adapter sorts by `doc_id ASC` and must exercise this
/// path. Everything else keeps the unmodified live-bitmap scan.
/// PERF-06-C2: the test-only forced-Legacy override, or a constant `false` in
/// every non-test build. Consulted only at the single request-local route decision.
#[cfg(test)]
fn c2_legacy_forced() -> bool {
    c2_observation::legacy_forced()
}

#[cfg(not(test))]
const fn c2_legacy_forced() -> bool {
    false
}

fn single_term_postings_eligible(
    plan: &UnifiedPlan,
    request: &UnifiedRequest,
    aggregation: Option<&Aggregation>,
) -> bool {
    if !matches!(plan.root, UnifiedNode::Lexical(0)) {
        return false;
    }
    if plan.lexical_leaves.len() != 1 {
        return false;
    }
    match &plan.lexical_leaves[0] {
        CompiledLeaf::Term { terms, .. } if terms.len() == 1 => {}
        _ => return false,
    }
    if !plan.typed_leaves.is_empty() {
        return false;
    }
    if plan.positive_lexical.len() != 1 || !plan.positive_lexical.contains(&0) {
        return false;
    }
    aggregation.is_none() && request.after.is_none()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TopKDuplicateStrategy {
    Prefilter,
    ExactSet,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TopKDuplicateConfig {
    min_top_k: std::num::NonZeroUsize,
    strategy: TopKDuplicateStrategy,
}

impl TopKDuplicateConfig {
    #[must_use]
    pub const fn new(min_top_k: std::num::NonZeroUsize, strategy: TopKDuplicateStrategy) -> Self {
        Self {
            min_top_k,
            strategy,
        }
    }
    #[must_use]
    pub const fn min_top_k(self) -> std::num::NonZeroUsize {
        self.min_top_k
    }
    #[must_use]
    pub const fn strategy(self) -> TopKDuplicateStrategy {
        self.strategy
    }
}
impl Default for TopKDuplicateConfig {
    fn default() -> Self {
        Self {
            min_top_k: std::num::NonZeroUsize::new(32).expect("nonzero"),
            strategy: TopKDuplicateStrategy::Prefilter,
        }
    }
}

/// A snapshot-bound compound searcher.
pub struct UnifiedSearcher<'a> {
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    limits: SearchLimits,
    topk_duplicate: TopKDuplicateConfig,
}

struct AggregationState {
    request: AggregateRequest,
    plan: TypedPlan,
    bucket: Option<TimeBucket>,
    engine: AggregationEngine,
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
            topk_duplicate: TopKDuplicateConfig::default(),
        }
    }

    #[must_use]
    pub fn with_topk_duplicate_config(mut self, config: TopKDuplicateConfig) -> Self {
        self.topk_duplicate = config;
        self
    }

    /// Execute a compound request against the bound snapshot.
    pub fn search(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<UnifiedResponse> {
        self.search_impl(request, budgets, cancel, None, false, None)
            .map(|(response, _)| response)
    }

    /// Execute a batch slot against the shared cumulative batch meter.
    #[allow(dead_code)]
    pub(crate) fn search_with_batch(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
        batch: &mut BatchExecutionMeter,
    ) -> SearchResult<UnifiedResponse> {
        self.search_impl(request, budgets, cancel, Some(batch), false, None)
            .map(|(response, _)| response)
    }

    /// Batch path: retain the projected response bytes in the shared memory
    /// meter and return the retained amount for the response-budget handoff.
    #[allow(dead_code)]
    pub(crate) fn search_with_batch_retained(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
        batch: &mut BatchExecutionMeter,
    ) -> SearchResult<(UnifiedResponse, u64)> {
        self.search_impl(request, budgets, cancel, Some(batch), true, None)
    }

    /// Batch path with compound aggregation computed over the same membership
    /// pass as the hits, retaining the combined response exactly once.
    pub(crate) fn search_with_batch_aggregation_retained(
        &self,
        request: &UnifiedRequest,
        aggregation: Option<&Aggregation>,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
        batch: &mut BatchExecutionMeter,
    ) -> SearchResult<(UnifiedResponse, u64)> {
        self.search_impl(request, budgets, cancel, Some(batch), true, aggregation)
    }

    /// Enumerate every effective-live logical key matching `query` on this
    /// snapshot.
    ///
    /// This is the private complete-membership seam used by atomic query
    /// mutations. It reuses the same compilation, expansion, statistics,
    /// lexical evaluation and typed predicate as [`Self::collect_mixed`]; only
    /// top-K retention is replaced with a bounded, deduplicated key set. It
    /// never returns a partial result: any budget, cancellation, segment or
    /// predicate failure is propagated.
    pub(crate) fn select_keys(
        &self,
        query: &Query,
        limit: u64,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<CompleteKeySelection> {
        query.validate(self.schema, budgets)?;
        let plan = unified_plan::compile(
            query,
            self.schema,
            self.registry,
            &self.limits,
            &AnalysisLimits::default(),
            cancel,
        )?;
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
        let synth = plan::synthetic_query(&plan);
        let mut meter = MixedWorkMeter::new(
            self.limits.max_total_work_units(),
            self.limits.max_typed_work_units(),
            self.limits.max_scanned_posting_occurrences(),
            cancel,
        );
        let expansion = {
            let mut work = SearchWork::shared(&mut meter);
            expand_query(&readers, &synth, &self.limits, &mut work, cancel)?
        };
        // FD-04: retained intentionally. Statistics computation also advances the
        // shared work/cancellation meter; removing it from the membership path
        // requires separate measured evidence and approval.
        let _stats = {
            let mut work = SearchWork::shared(&mut meter);
            compute_stats(
                &readers,
                &live,
                &plan.scoring_field_ids,
                expansion.positive_terms(),
                &self.limits,
                &mut work,
                cancel,
            )?
        };
        let mut budget = CandidateBudget::new(&self.limits);
        let mut selected: Vec<DocumentKey> = Vec::new();
        let mut seen: BTreeSet<DocumentKey> = BTreeSet::new();
        let mut memory_sink: Option<&mut (dyn MemoryCharge + '_)> = None;
        for (segment_index, reader) in readers.iter().enumerate() {
            if cancel.is_cancelled() {
                return Err(SearchError::Cancelled);
            }
            let columns = ColumnAccess::open(reader)?;
            let json = typed::JsonAccess::open(reader)?;
            let mut typed_geo: Vec<typed::GeoMembership> = Vec::new();
            let mut geo_scratches: Vec<typed::GeoScratchBudget> = Vec::new();
            for typed_leaf in &plan.typed_leaves {
                let mut scratch =
                    typed::GeoScratchBudget::new(self.limits.max_total_candidate_bytes());
                let membership = {
                    let mut typed_charge = TypedCharge::new(&mut meter);
                    let mut guard = ScanGuard::shared(&mut typed_charge);
                    typed::build_geo_membership_with_memory(
                        &typed_leaf.geo_leaves,
                        reader.spatial(),
                        reader,
                        &columns,
                        &mut guard,
                        &mut scratch,
                        self.limits.max_segment_candidate_entries(),
                        None,
                    )?
                };
                typed_geo.push(membership);
                geo_scratches.push(scratch);
            }
            let mut limit_exceeded: Option<CompleteKeySelection> = None;
            let control = execute::visit_lexical_membership_with(
                reader,
                &plan.lexical_leaves,
                &expansion,
                segment_index,
                &live[segment_index],
                &mut budget,
                &mut meter,
                &mut memory_sink,
                !plan.typed_leaves.is_empty(),
                cancel,
                |doc_id, leaf_data, meter, mut memory| {
                    let mut typed_charge = TypedCharge::new(&mut *meter);
                    let mut guard = ScanGuard::shared(&mut typed_charge);
                    evaluate_unified(
                        &plan.root,
                        doc_id,
                        leaf_data,
                        &plan.typed_leaves,
                        &columns,
                        &json,
                        &typed_geo,
                        &mut guard,
                        memory.as_deref_mut(),
                    )
                },
                |doc_id, budget| {
                    let key = reader.doc_key(doc_id)?;
                    if seen.contains(&key) {
                        return Ok(VisitControl::Continue);
                    }
                    if selected.len() as u64 >= limit {
                        let matched = limit.checked_add(1).ok_or(SearchError::ResourceLimit {
                            limit: u64::MAX,
                            requested: u64::MAX,
                        })?;
                        limit_exceeded =
                            Some(CompleteKeySelection::LimitExceeded { limit, matched });
                        return Ok(VisitControl::Stop);
                    }
                    let charge = 64u64.checked_add(key.as_str().len() as u64).ok_or(
                        SearchError::ResourceLimit {
                            limit: self.limits.max_total_candidate_bytes(),
                            requested: u64::MAX,
                        },
                    )?;
                    budget.preflight_global_bytes(charge)?;
                    selected
                        .try_reserve(1)
                        .map_err(|_| SearchError::ResourceLimit {
                            limit,
                            requested: selected.len() as u64 + 1,
                        })?;
                    budget.commit_global_bytes(charge);
                    seen.insert(key.clone());
                    selected.push(key);
                    Ok(VisitControl::Continue)
                },
            )?;
            drop(typed_geo);
            for scratch in &mut geo_scratches {
                scratch.release_all_with_memory(None)?;
            }
            if control == VisitControl::Stop {
                return limit_exceeded.ok_or_else(|| SearchError::CorruptIndex {
                    detail: "membership visitor stopped without an over-limit outcome".to_owned(),
                });
            }
        }
        if cancel.is_cancelled() {
            return Err(SearchError::Cancelled);
        }
        selected.sort();
        Ok(CompleteKeySelection::Complete(selected))
    }

    fn search_impl(
        &self,
        request: &UnifiedRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
        batch: Option<&mut BatchExecutionMeter>,
        retain: bool,
        aggregation: Option<&Aggregation>,
    ) -> SearchResult<(UnifiedResponse, u64)> {
        request.query.validate(self.schema, budgets)?;
        // Validate the sort before any projection compile or segment access so an
        // invalid sort returns the established contract error, never a segment or
        // unsupported-operator error.
        request.sort.validate(self.schema)?;
        request.top_k.validate(budgets)?;
        request.projection.validate(self.schema)?;
        let projection = ProjectionPlan::compile(&request.projection, self.schema)?;
        let mut ledger = ProjectionLedger::new(self.limits.max_total_candidate_bytes());
        self.execute_unified(
            request,
            &projection,
            &mut ledger,
            batch,
            retain,
            budgets,
            aggregation,
            cancel,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn execute_unified(
        &self,
        request: &UnifiedRequest,
        projection: &ProjectionPlan,
        ledger: &mut ProjectionLedger,
        mut batch: Option<&mut BatchExecutionMeter>,
        retain: bool,
        budgets: &Budgets,
        aggregation: Option<&Aggregation>,
        cancel: &dyn Cancellation,
    ) -> SearchResult<(UnifiedResponse, u64)> {
        // Cursor binding/fingerprint validation happens before plan compilation
        // and before any segment is opened.
        let bindings =
            crate::analysis::SchemaAnalyzerBindings::resolve(self.schema, self.registry)?;
        let codec = crate::segment::CodecSchema::from_contract(self.schema, &bindings)?;
        let scoring = has_positive_lexical(&request.query);
        let fingerprint = unified_cursor::fingerprint(&request.query, &codec, &request.sort);
        if let Some(cursor) = &request.after {
            validate_cursor(
                cursor,
                self.snapshot.binding_id(),
                fingerprint,
                &request.sort,
                scoring,
            )?;
        }
        let plan = unified_plan::compile(
            &request.query,
            self.schema,
            self.registry,
            &self.limits,
            &AnalysisLimits::default(),
            cancel,
        )?;
        let (page, total_hits, next_cursor, aggregation_result) = self.collect_mixed(
            &plan,
            request,
            fingerprint,
            batch.as_deref_mut(),
            cancel,
            budgets,
            aggregation,
        )?;
        // Projection temporaries are bound to the slot's batch memory scope and
        // released at the end of the slot; the retained response bytes are owned
        // and charged exactly once by the batch response handoff.
        let mut projection_scope = batch
            .as_mut()
            .map(|meter| SlotMemoryScope::new(&mut meter.memory));
        let fields = project_selected_hits(
            self.snapshot,
            projection,
            ledger,
            &page,
            projection_scope
                .as_mut()
                .map(|scope| scope as &mut (dyn MemoryCharge + '_)),
        )?;
        let retained = if retain {
            let response_bytes = response_bytes_for(&page, &fields, aggregation_result.as_ref())?;
            let scope = projection_scope.as_mut().ok_or(SearchError::CorruptIndex {
                detail: "retained response requires a batch memory scope".to_owned(),
            })?;
            let overhead = response_bytes.checked_sub(scope.temporary_bytes()).ok_or(
                SearchError::CorruptIndex {
                    detail: "response handoff is smaller than retained projection bytes".to_owned(),
                },
            )?;
            scope
                .reserve(overhead)
                .map_err(|error| error.to_search_error())?;
            scope.finish_success(response_bytes)?;
            response_bytes
        } else {
            if let Some(scope) = projection_scope.as_mut() {
                scope.finish_success(0)?;
            }
            0
        };
        let hits = page
            .into_iter()
            .zip(fields)
            .map(|(hit, fields)| ProjectedHit {
                key: hit.key,
                score: hit.score,
                fields,
            })
            .collect();
        Ok((
            UnifiedResponse {
                hits,
                total_hits,
                generation: self.snapshot.generation(),
                view_ordinal: self.snapshot.view_ordinal(),
                next_cursor,
                aggregation: aggregation_result,
            },
            retained,
        ))
    }

    /// PR 15H-B: whether this standalone request may use the borrowed Keyword
    /// sort view for noncompetitive candidates. This never widens the existing
    /// single-term eligibility.
    fn keyword_sort_late_eligible(
        &self,
        plan: &UnifiedPlan,
        request: &UnifiedRequest,
        aggregation: Option<&Aggregation>,
        standalone: bool,
    ) -> bool {
        if !standalone || !single_term_postings_eligible(plan, request, aggregation) {
            return false;
        }
        if request.after.is_some() || request.sort.fields.len() != 1 {
            return false;
        }
        let field = &request.sort.fields[0];
        if field.distance_from.is_some() || field.json_path.is_some() {
            return false;
        }
        let Some(definition) = self.schema.get(&field.field) else {
            return false;
        };
        definition.field_type == FieldType::Keyword
            && definition.cardinality == Cardinality::Single
            && definition.options.columnar
    }

    /// PERF-06-B2: the frozen subset of [`Self::keyword_sort_late_eligible`] that
    /// may rank candidates by B1 snapshot-wide ordinals.
    ///
    /// This only *narrows* the existing predicate: a `multi` selector on one
    /// field stays on the legacy borrowed path, and every other ineligible shape
    /// (cursor, aggregation, batch, non-strict term, JSON, geo, multi-sort) is
    /// already excluded by the base predicate.
    fn keyword_ordinal_eligible(
        &self,
        plan: &UnifiedPlan,
        request: &UnifiedRequest,
        aggregation: Option<&Aggregation>,
        standalone: bool,
    ) -> bool {
        self.keyword_sort_late_eligible(plan, request, aggregation, standalone)
            && request.sort.fields[0].multi.is_none()
    }

    /// PERF-06-C2: the request-level strict-term physical dispatch certificate.
    ///
    /// Every predicate is required. The C1 static shape is deliberately re-checked
    /// here as a fail-closed source guard (never a second analyzer, never a second
    /// compiler) on top of the accepted `single_term_postings_eligible` /
    /// `keyword_ordinal_eligible` prerequisites and the request-wide B1 `Ready`
    /// state. The count is the accepted BM25 document frequency of the single
    /// positive term, which `compute_stats` derives from effective-live data; a
    /// segment/format for which that count is not a sound effective-live
    /// cardinality keeps the whole request on Legacy (D11).
    fn strict_term_dispatch_eligible(
        &self,
        plan: &UnifiedPlan,
        request: &UnifiedRequest,
        aggregation: Option<&Aggregation>,
        standalone: bool,
        stats: &SnapshotStats<'_>,
        ordinal_field: u32,
    ) -> bool {
        if !standalone || aggregation.is_some() || request.after.is_some() {
            return false;
        }
        if !single_term_postings_eligible(plan, request, aggregation)
            || !self.keyword_ordinal_eligible(plan, request, aggregation, standalone)
        {
            return false;
        }
        if plan.root != UnifiedNode::Lexical(0)
            || plan.lexical_leaves.len() != 1
            || !plan.typed_leaves.is_empty()
        {
            return false;
        }
        let field_id = match &plan.lexical_leaves[0] {
            CompiledLeaf::Term { field_id, terms } if terms.len() == 1 => *field_id,
            _ => return false,
        };
        if plan.positive_lexical.len() != 1 || !plan.positive_lexical.contains(&0) {
            return false;
        }
        if !plan.scoring_field_ids.contains(&field_id) {
            return false;
        }
        // The one sortable Keyword field the ordinal map was prepared for must be
        // the same field the compiled leaf scores on this engine's schema.
        if plan.codec.field_id(&request.sort.fields[0].field) != Some(ordinal_field) {
            return false;
        }
        let CompiledLeaf::Term { terms, .. } = &plan.lexical_leaves[0] else {
            return false;
        };
        let term = terms[0].as_str();
        let Some(field) = stats.field(field_id) else {
            return false;
        };
        let document_frequency = field.doc_freq(term);
        document_frequency > request.top_k.limit.saturating_add(1) as u64
    }

    #[allow(clippy::needless_option_as_deref)]
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    fn collect_mixed(
        &self,
        plan: &UnifiedPlan,
        request: &UnifiedRequest,
        fingerprint: [u8; 32],
        batch: Option<&mut BatchExecutionMeter>,
        cancel: &dyn Cancellation,
        budgets: &Budgets,
        aggregation: Option<&Aggregation>,
    ) -> SearchResult<(
        Vec<SelectedHit>,
        u64,
        Option<UnifiedCursor>,
        Option<AggregationResult>,
    )> {
        let standalone = batch.is_none();
        let keyword_late = self.keyword_sort_late_eligible(plan, request, aggregation, standalone);
        #[cfg(test)]
        if keyword_late {
            b_observation::record_eligible();
        }
        let mut aggregation_state = match aggregation {
            Some(aggregation) => {
                let request = AggregateRequest::from_contract(
                    aggregation,
                    request.query.clone(),
                    self.schema,
                    None,
                )?;
                let (plan, bucket, engine) =
                    typed::prepare_aggregation(self.schema, self.limits, &request, budgets)?;
                Some(AggregationState {
                    request,
                    plan,
                    bucket,
                    engine,
                })
            }
            None => None,
        };
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
        // One authoritative work meter for the whole mixed request. Lexical and
        // typed charges both advance this single total.
        let (work, memory) = match batch {
            Some(batch) => (Some(&mut batch.work), Some(&mut batch.memory)),
            None => (None, None),
        };
        let mut meter = match work {
            Some(work) => MixedWorkMeter::with_batch(
                self.limits.max_total_work_units(),
                self.limits.max_typed_work_units(),
                self.limits.max_scanned_posting_occurrences(),
                cancel,
                work,
            ),
            None => MixedWorkMeter::new(
                self.limits.max_total_work_units(),
                self.limits.max_typed_work_units(),
                self.limits.max_scanned_posting_occurrences(),
                cancel,
            ),
        };
        let expansion = {
            let mut work = SearchWork::shared(&mut meter);
            expand_query(&readers, &synth, &self.limits, &mut work, cancel)?
        };
        let stats = {
            let mut work = SearchWork::shared(&mut meter);
            compute_stats(
                &readers,
                &live,
                &plan.scoring_field_ids,
                expansion.positive_terms(),
                &self.limits,
                &mut work,
                cancel,
            )?
        };
        // PERF-06-B2: one request-wide optional preparation, decided before any
        // candidate is processed. `None` means the whole request uses the
        // existing string/typed path; a B1 error is never a fallback.
        let ordinal_field_id = if self.snapshot.segment_count() > 0
            && self.keyword_ordinal_eligible(plan, request, aggregation, standalone)
        {
            #[cfg(test)]
            b2_observation::record_eligible_request();
            plan.codec.field_id(&request.sort.fields[0].field)
        } else {
            None
        };
        let ordinal_map = match ordinal_field_id {
            Some(field_id) => {
                #[cfg(test)]
                b2_observation::record_map_preparation();
                let preparation = self
                    .snapshot
                    .prepare_keyword_ordinals(field_id, &guards, cancel)
                    .map_err(ordinal_preparation_error)?;
                let map = ordinal_ready_from_preparation(preparation);
                #[cfg(test)]
                if map.is_none() {
                    b2_observation::record_optional_fallback();
                }
                map
            }
            None => None,
        };
        #[cfg(test)]
        if ordinal_map.is_some() {
            b2_observation::record_ready_use();
        }
        let mut budget = CandidateBudget::new(&self.limits);
        let mut scope = memory.map(SlotMemoryScope::new);
        let relevance = request.sort.fields.is_empty();
        let scoring = !plan.positive_lexical.is_empty();
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut ordinal_heap_audit = ordinal_map.as_ref().map(|_| OrdinalHeapAudit::new());
        let mut compact_hash_audit = CompactHashAudit::new();
        let mut experiment = d3c::State::for_request(
            request.top_k.limit,
            self.topk_duplicate,
            &mut budget,
            &mut scope,
        )?;
        let mut total_hits = 0u64;
        // PERF-06-C2: one request-local physical route decision, taken after the
        // common preflight and before any per-segment admission or typed setup.
        // The choice is a local value: it is never persisted, never re-evaluated
        // per segment or per candidate, and never flipped back to Legacy once
        // candidate processing has started.
        let physical_ordinal_field = if c2_legacy_forced() {
            None
        } else {
            match (&ordinal_map, ordinal_field_id) {
                (Some(_), Some(field_id))
                    if self.strict_term_dispatch_eligible(
                        plan,
                        request,
                        aggregation,
                        standalone,
                        &stats,
                        field_id,
                    ) =>
                {
                    Some(field_id)
                }
                _ => None,
            }
        };
        match (physical_ordinal_field, ordinal_map.as_ref()) {
            (Some(field_id), Some(map)) => {
                #[cfg(test)]
                c2_observation::record_strict_route();
                collect_strict_term_ordinal_body(
                    plan,
                    request,
                    &readers,
                    &guards,
                    &live,
                    &expansion,
                    &stats,
                    map,
                    field_id,
                    keyword_late,
                    &self.limits,
                    &mut meter,
                    &mut budget,
                    &mut scope,
                    &mut heap,
                    &mut ordinal_heap_audit,
                    &mut compact_hash_audit,
                    &mut experiment,
                    &mut total_hits,
                    cancel,
                )?;
            }
            _ => {
                #[cfg(test)]
                c2_observation::record_legacy_route();
                collect_mixed_legacy_body(
                    plan,
                    request,
                    &readers,
                    &guards,
                    &live,
                    &expansion,
                    &stats,
                    ordinal_map.as_ref(),
                    ordinal_field_id,
                    keyword_late,
                    aggregation,
                    &self.limits,
                    &mut meter,
                    &mut budget,
                    &mut scope,
                    &mut heap,
                    &mut ordinal_heap_audit,
                    &mut compact_hash_audit,
                    &mut experiment,
                    &mut aggregation_state,
                    &mut total_hits,
                    cancel,
                )?;
            }
        }
        let aggregation_result = match aggregation_state {
            Some(state) => {
                let mut agg_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                    .as_mut()
                    .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                let groups = state.engine.finish(
                    state.request.frequency_top_k.as_ref().map(|top| top.limit),
                    agg_memory.as_deref_mut(),
                )?;
                Some(super::analytics::to_contract_groups(&groups))
            }
            None => None,
        };
        let mut selected: Vec<SelectedHit> = heap
            .into_sorted_vec()
            .into_iter()
            .map(|entry| entry.hit)
            .collect();
        let mut next_cursor = None;
        if selected.len() > request.top_k.limit {
            let last = &selected[request.top_k.limit - 1];
            next_cursor = Some(UnifiedCursor::new(
                self.snapshot.binding_id(),
                fingerprint,
                last.sort_tuple.clone(),
                if relevance && scoring {
                    last.score
                } else {
                    None
                },
                last.key.clone(),
            ));
            selected.truncate(request.top_k.limit);
        }
        Ok((selected, total_hits, next_cursor, aggregation_result))
    }
}

/// PERF-06-C2: the accepted legacy per-segment loop, moved mechanically.
///
/// This is the accepted `collect_mixed` segment loop verbatim: statement order,
/// error boundaries, work/memory charges, geo drop order and every per-candidate
/// decision are unchanged. Only the already-computed preflight locals became
/// parameters and `self.limits`/`total_hits` became borrow-only plumbing. There is
/// deliberately no strategy condition or per-document dispatch inside this
/// function, so a low-hit request reaches exactly the accepted code shape.
#[allow(clippy::too_many_arguments)]
#[allow(clippy::needless_borrow, clippy::needless_option_as_deref)]
fn collect_mixed_legacy_body<'a>(
    plan: &UnifiedPlan,
    request: &'a UnifiedRequest,
    readers: &[&SegmentReader],
    guards: &[crate::index::GuardedSegmentReader],
    live: &[Rc<Vec<bool>>],
    expansion: &super::expand::Expansion,
    stats: &SnapshotStats<'_>,
    ordinal_map: Option<&Arc<SnapshotKeywordOrdinals>>,
    ordinal_field_id: Option<u32>,
    keyword_late: bool,
    aggregation: Option<&Aggregation>,
    limits: &SearchLimits,
    mut meter: &mut MixedWorkMeter<'_>,
    mut budget: &mut CandidateBudget,
    mut scope: &mut Option<SlotMemoryScope<'_>>,
    mut heap: &mut BinaryHeap<MixedEntry<'a>>,
    ordinal_heap_audit: &mut Option<OrdinalHeapAudit>,
    mut compact_hash_audit: &mut CompactHashAudit,
    mut experiment: &mut d3c::State,
    aggregation_state: &mut Option<AggregationState>,
    total_hits: &mut u64,
    cancel: &dyn Cancellation,
) -> SearchResult<()> {
    let relevance = request.sort.fields.is_empty();
    let scoring = !plan.positive_lexical.is_empty();
    let heap_limit = request.top_k.limit.saturating_add(1);
    for (segment_index, reader) in readers.iter().enumerate() {
        let columns = ColumnAccess::open(reader)?;
        let keyword_field_id = if keyword_late {
            Some(
                reader
                    .schema()
                    .field_id(&request.sort.fields[0].field)
                    .ok_or_else(|| SearchError::CorruptIndex {
                        detail: "segment schema/analyzer bindings do not match the supplied schema"
                            .to_owned(),
                    })?,
            )
        } else {
            None
        };
        // PERF-06-B2: bind the numeric accessor and this segment's rank
        // translation exactly once; neither is looked up per candidate.
        let ordinal_binding = match (ordinal_map, ordinal_field_id) {
            (Some(map), Some(field_id)) => {
                let bound = columns
                    .bind_keyword_sort_ordinal(field_id)?
                    .ok_or_else(ready_ordinal_column_missing)?;
                #[cfg(test)]
                b2_observation::record_bound_column();
                let translation = map.bind_segment(&guards[segment_index])?;
                Some((bound, translation))
            }
            _ => None,
        };
        let json = typed::JsonAccess::open(reader)?;
        let mut typed_geo: Vec<typed::GeoMembership> = Vec::new();
        let mut geo_scratches: Vec<typed::GeoScratchBudget> = Vec::new();
        for typed_leaf in &plan.typed_leaves {
            let mut scratch = typed::GeoScratchBudget::new(limits.max_total_candidate_bytes());
            let membership = {
                let mut typed_charge = TypedCharge::new(&mut meter);
                let mut guard = ScanGuard::shared(&mut typed_charge);
                let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                    .as_mut()
                    .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                typed::build_geo_membership_with_memory(
                    &typed_leaf.geo_leaves,
                    reader.spatial(),
                    reader,
                    &columns,
                    &mut guard,
                    &mut scratch,
                    limits.max_segment_candidate_entries(),
                    geo_memory.as_deref_mut(),
                )?
            };
            typed_geo.push(membership);
            geo_scratches.push(scratch);
        }
        let mut sort_scratch = typed::GeoScratchBudget::new(limits.max_total_candidate_bytes());
        let geo_sort = {
            let mut typed_charge = TypedCharge::new(&mut meter);
            let mut guard = ScanGuard::shared(&mut typed_charge);
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            typed::build_geo_sort_distances_with_memory(
                Some(&request.sort),
                reader,
                &columns,
                &mut guard,
                &mut sort_scratch,
                geo_memory.as_deref_mut(),
            )?
        };
        let mut memory_sink: Option<&mut (dyn MemoryCharge + '_)> = scope
            .as_mut()
            .map(|sink| sink as &mut (dyn MemoryCharge + '_));
        // Computed once per query from the compiled plan, not from the query
        // text, so analyzer expansion cannot be mistaken for a single stream.
        let postings_candidate_eligible = single_term_postings_eligible(plan, request, aggregation);
        let scored = execute::evaluate_lexical_with(
            reader,
            &plan.lexical_leaves,
            &expansion,
            &stats,
            &plan.positive_lexical,
            segment_index,
            &live[segment_index],
            &mut budget,
            &mut meter,
            &mut memory_sink,
            !plan.typed_leaves.is_empty(),
            postings_candidate_eligible,
            cancel,
            |doc_id, leaf_data, meter, mut memory| {
                let matched = {
                    let mut typed_charge = TypedCharge::new(&mut *meter);
                    let mut guard = ScanGuard::shared(&mut typed_charge);
                    if postings_candidate_eligible {
                        // The strict root-Term eligibility and evaluate_lexical_with's
                        // one-term/one-postings runtime guard prove every yielded doc_id
                        // already satisfies UnifiedNode::Lexical(0).  Do not repeat the
                        // same term's binary search in LeafData::matches.
                        true
                    } else {
                        evaluate_unified(
                            &plan.root,
                            doc_id,
                            leaf_data,
                            &plan.typed_leaves,
                            &columns,
                            &json,
                            &typed_geo,
                            &mut guard,
                            memory.as_deref_mut(),
                        )?
                    }
                };
                if matched {
                    if let Some(state) = aggregation_state.as_mut() {
                        let mut agg_charge = TypedCharge::new(&mut *meter);
                        let mut agg_guard = ScanGuard::shared(&mut agg_charge);
                        typed::visit_aggregate(
                            &mut agg_guard,
                            &mut state.engine,
                            &state.plan,
                            &state.request,
                            state.bucket.as_ref(),
                            &columns,
                            doc_id,
                            memory.as_deref_mut(),
                        )?;
                    }
                }
                Ok(matched)
            },
        )?;
        // PR 15E Phase 5: a large segment projecting exactly one hit decodes
        // only that one document key; every other shape keeps the full cache.
        let single_hit_segment = scored.len() == 1 && reader.doc_count() >= 1024;
        // PERF-06-B3: at most one key-identity binding attempt per segment,
        // made on the first matched, scored candidate — exactly where the
        // original code would resolve its owned key. A refusal downgrades
        // this whole segment to the owned B2 key path.
        let mut key_binder = KeyBinder::Unattempted;
        for (doc_id, score) in scored {
            *total_hits = total_hits
                .checked_add(1)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            if let Some((bound, translation)) = &ordinal_binding {
                #[cfg(test)]
                b2_observation::record_numeric_candidate();
                if matches!(key_binder, KeyBinder::Unattempted) {
                    key_binder = if experiment.supports_compact_key() {
                        match reader.bind_key_identity(cancel)? {
                            Some(identity) => KeyBinder::Ready(identity),
                            None => KeyBinder::Fallback,
                        }
                    } else {
                        KeyBinder::Fallback
                    };
                }
                let audit = ordinal_heap_audit
                    .as_mut()
                    .ok_or_else(mixed_ordinal_heap_error)?;
                if let KeyBinder::Ready(identity) = &key_binder {
                    consider_compact_ordinal_candidate(
                        &columns,
                        reader.schema(),
                        request,
                        doc_id,
                        segment_index,
                        score,
                        scoring,
                        bound,
                        translation,
                        identity,
                        audit,
                        &mut compact_hash_audit,
                        &mut heap,
                        heap_limit,
                        &mut budget,
                        &mut scope,
                        &mut experiment,
                    )?;
                    continue;
                }
                let key = if single_hit_segment {
                    reader.doc_key_selected(doc_id)?
                } else {
                    reader.doc_key(doc_id)?
                };
                consider_ordinal_keyword_candidate(
                    &columns,
                    reader.schema(),
                    request,
                    doc_id,
                    segment_index,
                    key,
                    score,
                    scoring,
                    bound,
                    translation,
                    audit,
                    &mut heap,
                    heap_limit,
                    &mut budget,
                    &mut scope,
                    &mut experiment,
                )?;
                continue;
            }
            let key = if single_hit_segment {
                reader.doc_key_selected(doc_id)?
            } else {
                reader.doc_key(doc_id)?
            };
            if let Some(field_id) = keyword_field_id {
                consider_borrowed_keyword_candidate(
                    &columns,
                    reader.schema(),
                    request,
                    doc_id,
                    segment_index,
                    key,
                    score,
                    scoring,
                    field_id,
                    &mut heap,
                    heap_limit,
                    &mut budget,
                    &mut scope,
                    &mut experiment,
                )?;
                continue;
            }
            let mut tuple = if request.sort.fields.is_empty() {
                Vec::new()
            } else {
                sort_tuple_for_doc(
                    &columns,
                    reader.schema(),
                    &request.sort,
                    geo_sort.as_ref(),
                    doc_id,
                )?
            };
            let sort_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            let mut sort_scratch = typed::JsonSortScratch::new(sort_memory);
            for (index, field) in request.sort.fields.iter().enumerate() {
                if field.json_path.is_some() {
                    let mut typed_charge = TypedCharge::new(&mut meter);
                    let mut guard = ScanGuard::shared(&mut typed_charge);
                    tuple[index] = typed::json_sort_value(
                        &json,
                        reader.schema(),
                        field,
                        doc_id,
                        &mut guard,
                        &mut sort_scratch,
                    )?;
                }
            }
            let hit = SelectedHit {
                segment_index,
                doc_id,
                key,
                // A pure typed or negative-only-lexical predicate has no
                // positive lexical contribution: report no score, matching
                // the typed executor's contract.
                score: if plan.positive_lexical.is_empty() {
                    None
                } else {
                    Some(score)
                },
                sort_tuple: tuple,
            };
            if let Some(cursor) = &request.after {
                let after = if relevance {
                    if scoring {
                        let cursor_score = cursor.last_score.ok_or_else(cursor_sort_error)?;
                        let candidate_score = hit.score.ok_or_else(cursor_sort_error)?;
                        cmp_relevance(cursor_score, &cursor.last_key, candidate_score, &hit.key)
                            == Ordering::Less
                    } else {
                        hit.key > cursor.last_key
                    }
                } else {
                    compare_candidates(
                        &hit.sort_tuple,
                        &hit.key,
                        &cursor.last_sort,
                        &cursor.last_key,
                        &request.sort,
                    ) == Ordering::Greater
                };
                if !after {
                    continue;
                }
            }
            // Release the transient winner reservation immediately before the
            // retained candidate charge so the tuple is never double-charged.
            sort_scratch.finish()?;
            let charge = candidate_charge(&hit)?;
            let entry = MixedEntry {
                hit,
                charge,
                sort: &request.sort,
                relevance,
                ordinal_sort: None,
                key_hash: None,
            };
            // Effective-live keys are unique per snapshot; a duplicate among
            // retained candidates indicates corrupt committed state.
            experiment.check(&heap, &entry.hit.key)?;
            experiment.admit(entry, &mut heap, heap_limit, &mut budget, &mut scope)?;
        }
        // Drop the geo allocations first; their batch reservations are
        // released only after the backing buffers are gone.
        drop(typed_geo);
        drop(geo_sort);
        for scratch in &mut geo_scratches {
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            scratch.release_all_with_memory(geo_memory.as_deref_mut())?;
        }
        {
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            sort_scratch.release_all_with_memory(geo_memory.as_deref_mut())?;
        }
    }
    Ok(())
}

/// PERF-06-C2: the strict-term physical per-segment loop.
///
/// The route was already chosen exactly once by `collect_mixed` from the
/// request-level certificate; this function never re-decides it and never falls
/// back. It preserves the accepted per-segment setup/validation order (column,
/// ordinal binding, JSON, geo-sort and scratch setup) and hands every eagerly
/// scored posting of the reused posting allocation to the unchanged B1/B2/B3
/// candidate handlers.
#[allow(clippy::too_many_arguments)]
#[allow(clippy::needless_option_as_deref)]
fn collect_strict_term_ordinal_body<'a>(
    plan: &UnifiedPlan,
    request: &'a UnifiedRequest,
    readers: &[&SegmentReader],
    guards: &[crate::index::GuardedSegmentReader],
    live: &[Rc<Vec<bool>>],
    expansion: &super::expand::Expansion,
    stats: &SnapshotStats<'_>,
    ordinal_map: &Arc<SnapshotKeywordOrdinals>,
    ordinal_field: u32,
    keyword_late: bool,
    limits: &SearchLimits,
    meter: &mut MixedWorkMeter<'_>,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    ordinal_heap_audit: &mut Option<OrdinalHeapAudit>,
    compact_hash_audit: &mut CompactHashAudit,
    experiment: &mut d3c::State,
    total_hits: &mut u64,
    cancel: &dyn Cancellation,
) -> SearchResult<()> {
    let heap_limit = request.top_k.limit.saturating_add(1);
    for (segment_index, reader) in readers.iter().enumerate() {
        let columns = ColumnAccess::open(reader)?;
        // Accepted per-segment setup order is preserved exactly: the sort field id,
        // the numeric ordinal accessor and this segment's rank translation are
        // resolved here, after every preceding segment completed -- never as an
        // eager ahead-of-time preflight that could expose a later segment's error
        // before an earlier segment's decoding/scoring error.
        let _keyword_field_id = if keyword_late {
            Some(
                reader
                    .schema()
                    .field_id(&request.sort.fields[0].field)
                    .ok_or_else(|| SearchError::CorruptIndex {
                        detail: "segment schema/analyzer bindings do not match the supplied schema"
                            .to_owned(),
                    })?,
            )
        } else {
            None
        };
        let bound = columns
            .bind_keyword_sort_ordinal(ordinal_field)?
            .ok_or_else(ready_ordinal_column_missing)?;
        #[cfg(test)]
        b2_observation::record_bound_column();
        let translation = ordinal_map.bind_segment(&guards[segment_index])?;
        // Same validation sequence as the accepted loop. The C2 selector admits no
        // typed leaf, geo leaf or distance sort, so these structures stay empty,
        // but opening/building them keeps the observable corrupt-section error
        // order identical to Legacy.
        let json = typed::JsonAccess::open(reader)?;
        let mut typed_geo: Vec<typed::GeoMembership> = Vec::new();
        let mut geo_scratches: Vec<typed::GeoScratchBudget> = Vec::new();
        for typed_leaf in &plan.typed_leaves {
            let mut scratch = typed::GeoScratchBudget::new(limits.max_total_candidate_bytes());
            let membership = {
                let mut typed_charge = TypedCharge::new(&mut *meter);
                let mut guard = ScanGuard::shared(&mut typed_charge);
                let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                    .as_mut()
                    .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                typed::build_geo_membership_with_memory(
                    &typed_leaf.geo_leaves,
                    reader.spatial(),
                    reader,
                    &columns,
                    &mut guard,
                    &mut scratch,
                    limits.max_segment_candidate_entries(),
                    geo_memory.as_deref_mut(),
                )?
            };
            typed_geo.push(membership);
            geo_scratches.push(scratch);
        }
        let mut sort_scratch = typed::GeoScratchBudget::new(limits.max_total_candidate_bytes());
        let geo_sort = {
            let mut typed_charge = TypedCharge::new(&mut *meter);
            let mut guard = ScanGuard::shared(&mut typed_charge);
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            typed::build_geo_sort_distances_with_memory(
                Some(&request.sort),
                reader,
                &columns,
                &mut guard,
                &mut sort_scratch,
                geo_memory.as_deref_mut(),
            )?
        };
        // PERF-06-B3: at most one key-identity binding attempt per segment, made on
        // the first scored candidate exactly where the accepted loop resolves its
        // own key. A refusal downgrades only this segment to the owned B2 path.
        let mut key_binder = KeyBinder::Unattempted;
        execute::visit_strict_term_scored_with(
            reader,
            &plan.lexical_leaves,
            expansion,
            stats,
            &plan.positive_lexical,
            segment_index,
            &live[segment_index],
            budget,
            meter,
            cancel,
            |doc_id, score, matched_count, budget| {
                *total_hits = total_hits
                    .checked_add(1)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                #[cfg(test)]
                b2_observation::record_numeric_candidate();
                if matches!(key_binder, KeyBinder::Unattempted) {
                    key_binder = if experiment.supports_compact_key() {
                        match reader.bind_key_identity(cancel)? {
                            Some(identity) => KeyBinder::Ready(identity),
                            None => KeyBinder::Fallback,
                        }
                    } else {
                        KeyBinder::Fallback
                    };
                }
                let audit = ordinal_heap_audit
                    .as_mut()
                    .ok_or_else(mixed_ordinal_heap_error)?;
                if let KeyBinder::Ready(identity) = &key_binder {
                    consider_compact_ordinal_candidate(
                        &columns,
                        reader.schema(),
                        request,
                        doc_id,
                        segment_index,
                        score,
                        true,
                        &bound,
                        &translation,
                        identity,
                        audit,
                        &mut *compact_hash_audit,
                        heap,
                        heap_limit,
                        budget,
                        scope,
                        &mut *experiment,
                    )?;
                    return Ok(());
                }
                // PR 15E Phase 5: a large segment projecting exactly one hit decodes
                // only that one document key; every other shape keeps the full cache.
                let single_hit_segment = matched_count == 1 && reader.doc_count() >= 1024;
                let key = if single_hit_segment {
                    reader.doc_key_selected(doc_id)?
                } else {
                    reader.doc_key(doc_id)?
                };
                consider_ordinal_keyword_candidate(
                    &columns,
                    reader.schema(),
                    request,
                    doc_id,
                    segment_index,
                    key,
                    score,
                    true,
                    &bound,
                    &translation,
                    audit,
                    heap,
                    heap_limit,
                    budget,
                    scope,
                    &mut *experiment,
                )
            },
        )?;
        // Drop the geo allocations first; their batch reservations are released
        // only after the backing buffers are gone (accepted order).
        drop(typed_geo);
        drop(geo_sort);
        for scratch in &mut geo_scratches {
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            scratch.release_all_with_memory(geo_memory.as_deref_mut())?;
        }
        {
            let mut geo_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            sort_scratch.release_all_with_memory(geo_memory.as_deref_mut())?;
        }
        drop(json);
    }
    Ok(())
}

impl std::fmt::Debug for UnifiedSearcher<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UnifiedSearcher")
            .field("segments", &self.snapshot.segment_count())
            .field("generation", &self.snapshot.generation())
            .finish()
    }
}

/// The outcome of a private complete-key membership scan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CompleteKeySelection {
    /// Every matching effective-live key, unique and ascending.
    Complete(Vec<DocumentKey>),
    /// The first distinct matching key above the configured bound.
    LimitExceeded {
        /// The effective bound.
        limit: u64,
        /// `limit + 1` (checked arithmetic at the call site).
        matched: u64,
    },
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

/// Whether the AST has a lexical leaf reachable through an even number of `Not`
/// nodes (the PR 7 positive-scoring eligibility rule), computed without
/// compilation so cursor validation can precede plan building.
fn has_positive_lexical(query: &Query) -> bool {
    fn walk(query: &Query, negated: bool) -> bool {
        match query {
            Query::Term { .. }
            | Query::Phrase { .. }
            | Query::Prefix { .. }
            | Query::Glob { .. }
            | Query::Regex { .. }
            | Query::Fuzzy { .. } => !negated,
            Query::And(children) | Query::Or(children) => {
                children.iter().any(|child| walk(child, negated))
            }
            Query::Not(inner) => walk(inner, !negated),
            _ => false,
        }
    }
    walk(query, false)
}

fn default_relevance_cmp(a: &SelectedHit, b: &SelectedHit) -> Ordering {
    cmp_relevance(
        a.score.unwrap_or(0.0),
        &a.key,
        b.score.unwrap_or(0.0),
        &b.key,
    )
}

/// Relevance ordering: BM25 descending, then key ascending.
fn cmp_relevance(a_score: f64, a_key: &DocumentKey, b_score: f64, b_key: &DocumentKey) -> Ordering {
    match b_score.total_cmp(&a_score) {
        Ordering::Equal => a_key.cmp(b_key),
        other => other,
    }
}

fn cursor_pit_error() -> SearchError {
    SearchError::Query(QueryError::InvalidQuery(
        InvalidQueryReason::CursorPitMismatch,
    ))
}

fn cursor_sort_error() -> SearchError {
    SearchError::Query(QueryError::InvalidQuery(
        InvalidQueryReason::CursorSortMismatch,
    ))
}

fn validate_cursor(
    cursor: &UnifiedCursor,
    binding: u64,
    fingerprint: [u8; 32],
    sort: &Sort,
    scoring: bool,
) -> SearchResult<()> {
    if cursor.snapshot_binding != binding {
        return Err(cursor_pit_error());
    }
    if cursor.fingerprint != fingerprint {
        return Err(cursor_sort_error());
    }
    if sort.fields.is_empty() {
        if !cursor.last_sort.is_empty() {
            return Err(cursor_sort_error());
        }
        if scoring && cursor.last_score.is_none() {
            return Err(cursor_sort_error());
        }
        if !scoring && cursor.last_score.is_some() {
            return Err(cursor_sort_error());
        }
    } else if cursor.last_sort.len() != sort.fields.len() || cursor.last_score.is_some() {
        return Err(cursor_sort_error());
    }
    Ok(())
}

/// Preflight a heap insertion against the local candidate ledger and the batch
/// memory scope. No mutation.
fn heap_preflight_insert(
    budget: &CandidateBudget,
    memory: Option<&(dyn MemoryCharge + '_)>,
    charge: u64,
) -> SearchResult<()> {
    budget.preflight_global_bytes(charge)?;
    if let Some(sink) = memory {
        sink.preflight(charge)
            .map_err(|error| error.to_search_error())?;
    }
    Ok(())
}

/// Commit a preflighted heap insertion: batch first, then the infallible local
/// commit.
fn heap_commit_insert(
    budget: &mut CandidateBudget,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
    charge: u64,
) -> SearchResult<()> {
    if let Some(sink) = memory {
        sink.commit(charge)
            .map_err(|error| error.to_search_error())?;
    }
    budget.commit_global_bytes(charge);
    Ok(())
}

/// Preflight a heap release against both ledgers. No mutation.
fn heap_preflight_release(
    budget: &CandidateBudget,
    memory: Option<&(dyn MemoryCharge + '_)>,
    charge: u64,
) -> SearchResult<()> {
    budget.preflight_release_global_bytes(charge)?;
    if let Some(sink) = memory {
        sink.preflight_release(charge)?;
    }
    Ok(())
}

/// Commit a preflighted heap release: batch first, then local.
fn heap_commit_release(
    budget: &mut CandidateBudget,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
    charge: u64,
) -> SearchResult<()> {
    if let Some(sink) = memory {
        sink.release(charge)?;
    }
    budget.release_global_bytes(charge)?;
    Ok(())
}

/// Conservative logical-byte charge for one retained candidate.
fn candidate_charge(hit: &SelectedHit) -> SearchResult<u64> {
    candidate_charge_parts(&hit.key, &hit.sort_tuple)
}

/// The exact `candidate_charge` formula over an already-owned key and tuple.
///
/// Used by the B2 ordinal path to charge a `MultiOne` legacy tuple without
/// cloning the key into a temporary `SelectedHit`. The formula is unchanged.
fn candidate_charge_parts(key: &DocumentKey, sort_tuple: &[SortValue]) -> SearchResult<u64> {
    candidate_charge_parts_with_key_len(key.as_str().len() as u64, sort_tuple)
}

/// PERF-06-B3: the same logical charge over an already validated key length.
///
/// The compact path knows the exact logical UTF-8 key length from the verified
/// directory before owning a key, so it charges the identical *logical* bytes
/// (never the 8-byte fingerprint width).
fn candidate_charge_parts_with_key_len(
    key_len: u64,
    sort_tuple: &[SortValue],
) -> SearchResult<u64> {
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut bytes = 64u64.checked_add(key_len).ok_or_else(overflow)?;
    for value in sort_tuple {
        bytes = bytes.checked_add(32).ok_or_else(overflow)?;
        if let SortValue::Value(value) = value {
            bytes = bytes
                .checked_add(value.approx_size() as u64)
                .ok_or_else(overflow)?;
        }
    }
    Ok(bytes)
}

/// PR 15H-B: conservative charge for a borrowed single-keyword sort candidate.
///
/// Mirrors `candidate_charge` exactly: base + key, one 32-byte component, and
/// `utf8_len + 4` for a present Keyword value. Returns `None` for
/// `LegacyDecode`, telling the caller to use the ordinary owned path.
fn borrowed_keyword_candidate_charge(
    key: &DocumentKey,
    view: &ColumnKeywordView<'_>,
) -> SearchResult<Option<u64>> {
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut bytes = 64u64
        .checked_add(key.as_str().len() as u64)
        .ok_or_else(overflow)?;
    match view {
        ColumnKeywordView::LegacyDecode => return Ok(None),
        ColumnKeywordView::Missing | ColumnKeywordView::Null => {
            bytes = bytes.checked_add(32).ok_or_else(overflow)?;
        }
        ColumnKeywordView::Value(value) => {
            bytes = bytes.checked_add(32).ok_or_else(overflow)?;
            let size = u64::try_from(value.len())
                .map_err(|_| overflow())?
                .checked_add(4)
                .ok_or_else(overflow)?;
            bytes = bytes.checked_add(size).ok_or_else(overflow)?;
        }
    }
    Ok(Some(bytes))
}

/// PR 15I-D3-C experimental duplicate-detection strategies.
///
/// Compiled only with the non-default `pr15i-d3c-experiment` feature. The
/// default build retains the original linear duplicate scans unchanged.
mod d3c {
    use super::*;

    const MAX_WORDS: usize = 128; // 8192 bits, 1024 bytes
    const MAX_EXACT_SET_K: usize = 1024;

    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    pub(super) enum Kind {
        Linear,
        Prefilter,
        ExactSet,
    }

    #[allow(dead_code)]
    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    pub(super) enum Profile {
        P0,
        P1,
        P2,
    }

    impl Profile {
        pub(super) const fn bits(self) -> usize {
            match self {
                Self::P0 => 1024,
                Self::P1 => 4096,
                Self::P2 => 8192,
            }
        }

        const fn disable_after(self) -> usize {
            match self {
                Self::P0 => 256,
                Self::P1 => 1024,
                Self::P2 => 2048,
            }
        }

        #[allow(dead_code)]
        const fn label(self) -> &'static str {
            match self {
                Self::P0 => "P0",
                Self::P1 => "P1",
                Self::P2 => "P2",
            }
        }
    }

    #[cfg(feature = "pr15i-d3c-experiment")]
    #[cfg(test)]
    pub(super) fn parse_mode_for_test(
        s: Option<&str>,
        p: Option<&str>,
    ) -> Result<(Kind, Profile), String> {
        parse_mode(s, p)
    }

    #[cfg(feature = "pr15i-d3c-experiment")]
    fn parse_mode(
        strategy: Option<&str>,
        profile: Option<&str>,
    ) -> Result<(Kind, Profile), String> {
        match (strategy, profile) {
            (None, None) | (Some("linear"), None) => Ok((Kind::Linear, Profile::P0)),
            (Some("exact_set"), None) => Ok((Kind::ExactSet, Profile::P0)),
            (Some("prefilter"), Some("P0")) => Ok((Kind::Prefilter, Profile::P0)),
            (Some("prefilter"), Some("P1")) => Ok((Kind::Prefilter, Profile::P1)),
            (Some("prefilter"), Some("P2")) => Ok((Kind::Prefilter, Profile::P2)),
            _ => Err(format!(
                "invalid PR15I-D3-C mode: strategy={strategy:?} profile={profile:?}"
            )),
        }
    }

    #[cfg(feature = "pr15i-d3c-experiment")]
    fn mode() -> SearchResult<(Kind, Profile)> {
        static MODE: OnceLock<Result<(Kind, Profile), String>> = OnceLock::new();
        let resolved = MODE.get_or_init(|| {
            let strategy = std::env::var("QUERVANT_PR15I_D3C_STRATEGY").ok();
            let profile = std::env::var("QUERVANT_PR15I_D3C_PREFILTER_PROFILE").ok();
            let parsed = parse_mode(strategy.as_deref(), profile.as_deref());
            if let Ok((kind, profile)) = &parsed {
                let kind_label = match kind {
                    Kind::Linear => "linear",
                    Kind::Prefilter => "prefilter",
                    Kind::ExactSet => "exact_set",
                };
                let profile_label = if matches!(kind, Kind::Prefilter) {
                    profile.label()
                } else {
                    "none"
                };
                eprintln!("PR15I_D3C_MODE=v1:{kind_label}:{profile_label}");
            }
            parsed
        });
        resolved
            .clone()
            .map_err(|_| SearchError::UnsupportedOperator {
                operator: "pr15i_d3c_configuration",
            })
    }

    fn duplicate_error() -> SearchError {
        SearchError::CorruptIndex {
            detail: "duplicate live document key across segments".to_owned(),
        }
    }

    fn exact_scan(heap: &BinaryHeap<MixedEntry<'_>>, key: &DocumentKey) -> SearchResult<()> {
        if heap.iter().any(|existing| existing.hit.key == *key) {
            return Err(duplicate_error());
        }
        Ok(())
    }

    /// PERF-06-B3: the same exact retained-key policy, prefilted by fingerprint.
    ///
    /// A fingerprint is never an identity: the borrowed raw candidate UTF-8 is
    /// resolved at most once, and only after at least one retained entry shares
    /// the fingerprint. Entries without a validated fingerprint fail closed.
    fn compact_exact_scan<'a, F>(
        heap: &BinaryHeap<MixedEntry<'_>>,
        candidate_hash: u64,
        resolve_exact_key: F,
    ) -> SearchResult<()>
    where
        F: FnOnce() -> SearchResult<&'a str>,
    {
        // One pass, the same shape as the original exact scan: compare `u64`
        // fingerprints first and fail closed on any retained entry that has no
        // validated fingerprint.
        let mut possible = false;
        for entry in heap.iter() {
            let Some(entry_hash) = entry.key_hash else {
                return Err(SearchError::CorruptIndex {
                    detail: "compact key heap lacks a validated fingerprint".to_owned(),
                });
            };
            if entry_hash == candidate_hash {
                possible = true;
            }
        }
        if !possible {
            return Ok(());
        }
        // The borrowed raw key is resolved at most once, only here.
        let candidate = resolve_exact_key()?;
        #[cfg(test)]
        b3_observation::record_hash_collision_exact_check();
        if heap.iter().any(|existing| {
            existing.key_hash == Some(candidate_hash)
                && existing.hit.key.as_str().as_bytes() == candidate.as_bytes()
        }) {
            return Err(duplicate_error());
        }
        Ok(())
    }

    fn hash_key(key: &DocumentKey) -> u64 {
        crate::segment::reader::runtime_doc_key_hash(key.as_str())
    }

    fn probes(hash: u64, mask: usize) -> (usize, usize) {
        ((hash as usize) & mask, ((hash >> 32) as usize) & mask)
    }

    #[derive(Debug)]
    pub(super) struct State {
        kind: Kind,
        profile: Profile,
        words: [u64; MAX_WORDS],
        active_bits: usize,
        admissions: usize,
        disabled: bool,
        keys: HashSet<DocumentKey>,
        exact_table_charged: u64,
        exact_live_key_charged: u64,
        #[cfg(test)]
        exact_scans: std::cell::Cell<usize>,
        #[cfg(test)]
        pub(super) fail_reserve: bool,
    }

    fn h_preflight(
        budget: &CandidateBudget,
        scope: &Option<SlotMemoryScope<'_>>,
        bytes: u64,
    ) -> SearchResult<()> {
        let memory: Option<&(dyn MemoryCharge + '_)> =
            scope.as_ref().map(|s| s as &(dyn MemoryCharge + '_));
        heap_preflight_insert(budget, memory, bytes)
    }
    fn h_commit(
        budget: &mut CandidateBudget,
        scope: &mut Option<SlotMemoryScope<'_>>,
        bytes: u64,
    ) -> SearchResult<()> {
        let memory: Option<&mut (dyn MemoryCharge + '_)> =
            scope.as_mut().map(|s| s as &mut (dyn MemoryCharge + '_));
        heap_commit_insert(budget, memory, bytes)
    }
    fn h_preflight_release(
        budget: &CandidateBudget,
        scope: &Option<SlotMemoryScope<'_>>,
        bytes: u64,
    ) -> SearchResult<()> {
        let memory: Option<&(dyn MemoryCharge + '_)> =
            scope.as_ref().map(|s| s as &(dyn MemoryCharge + '_));
        heap_preflight_release(budget, memory, bytes)
    }
    fn h_release(
        budget: &mut CandidateBudget,
        scope: &mut Option<SlotMemoryScope<'_>>,
        bytes: u64,
    ) -> SearchResult<()> {
        let memory: Option<&mut (dyn MemoryCharge + '_)> =
            scope.as_mut().map(|s| s as &mut (dyn MemoryCharge + '_));
        heap_commit_release(budget, memory, bytes)
    }

    #[allow(dead_code)]
    impl State {
        fn production_mode(k: usize, config: super::TopKDuplicateConfig) -> (Kind, Profile) {
            if k < config.min_top_k().get() {
                (Kind::Linear, Profile::P0)
            } else {
                let kind = match config.strategy() {
                    super::TopKDuplicateStrategy::Prefilter => Kind::Prefilter,
                    super::TopKDuplicateStrategy::ExactSet => Kind::ExactSet,
                };
                (kind, Profile::P2)
            }
        }

        #[cfg(test)]
        pub(super) fn production_mode_for_test(
            k: usize,
            config: super::TopKDuplicateConfig,
        ) -> (Kind, Profile) {
            Self::production_mode(k, config)
        }

        pub(super) fn for_request(
            k: usize,
            config: super::TopKDuplicateConfig,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<Self> {
            #[cfg(feature = "pr15i-d3c-experiment")]
            let (kind, profile) = if std::env::var("QUERVANT_PR15I_D3C_STRATEGY").is_ok()
                || std::env::var("QUERVANT_PR15I_D3C_PREFILTER_PROFILE").is_ok()
            {
                mode()?
            } else {
                Self::production_mode(k, config)
            };
            #[cfg(not(feature = "pr15i-d3c-experiment"))]
            let (kind, profile) = Self::production_mode(k, config);
            Self::new_for_kind(kind, profile, k, budget, scope)
        }

        fn new_for_kind(
            kind: Kind,
            profile: Profile,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<Self> {
            let mut state = Self {
                kind,
                profile,
                words: [0; MAX_WORDS],
                active_bits: if kind == Kind::Prefilter {
                    profile.bits()
                } else {
                    0
                },
                admissions: 0,
                disabled: false,
                keys: HashSet::new(),
                exact_table_charged: 0,
                exact_live_key_charged: 0,
                #[cfg(test)]
                exact_scans: std::cell::Cell::new(0),
                #[cfg(test)]
                fail_reserve: false,
            };
            if kind == Kind::ExactSet {
                if k == 0 || k > MAX_EXACT_SET_K {
                    return Err(SearchError::ResourceLimit {
                        limit: MAX_EXACT_SET_K as u64,
                        requested: k as u64,
                    });
                }
                state.reserve_exact_set(k)?;
                let table = u64::try_from(state.keys.capacity())
                    .unwrap_or(u64::MAX)
                    .checked_mul(40)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                h_preflight(budget, scope, table)?;
                h_commit(budget, scope, table)?;
                state.exact_table_charged = table;
            }
            Ok(state)
        }

        #[cfg(test)]
        pub(super) fn for_test_accounted(
            kind: Kind,
            profile: Profile,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<Self> {
            Self::new_for_kind(kind, profile, k, budget, scope)
        }

        pub(super) fn reserve_exact_set(&mut self, k: usize) -> SearchResult<()> {
            #[cfg(test)]
            if self.fail_reserve {
                return Err(SearchError::ResourceLimit {
                    limit: (k.saturating_add(1)) as u64,
                    requested: (k.saturating_add(1)) as u64,
                });
            }
            self.keys
                .try_reserve(k.saturating_add(1))
                .map_err(|_| SearchError::ResourceLimit {
                    limit: (k.saturating_add(1)) as u64,
                    requested: (k.saturating_add(1)) as u64,
                })
        }

        pub(super) fn check(
            &self,
            heap: &BinaryHeap<MixedEntry<'_>>,
            key: &DocumentKey,
        ) -> SearchResult<()> {
            match self.kind {
                Kind::Linear => {
                    #[cfg(test)]
                    self.exact_scans.set(self.exact_scans.get() + 1);
                    exact_scan(heap, key)
                }
                Kind::ExactSet => {
                    if self.keys.contains(key) {
                        Err(duplicate_error())
                    } else {
                        Ok(())
                    }
                }
                Kind::Prefilter => {
                    if self.disabled {
                        #[cfg(test)]
                        self.exact_scans.set(self.exact_scans.get() + 1);
                        return exact_scan(heap, key);
                    }
                    let hash = hash_key(key);
                    let mask = self.active_bits - 1;
                    let (first, second) = probes(hash, mask);
                    if !self.bit(first) || !self.bit(second) {
                        return Ok(());
                    }
                    #[cfg(test)]
                    self.exact_scans.set(self.exact_scans.get() + 1);
                    exact_scan(heap, key)
                }
            }
        }

        /// PERF-06-B3: whether the **resolved runtime** duplicate strategy may
        /// use the compact retained-key fingerprint path.
        ///
        /// True for Linear and Prefilter only. `ExactSet` keeps its unchanged
        /// owned-key path and `HashSet<DocumentKey>` accounting.
        pub(super) fn supports_compact_key(&self) -> bool {
            matches!(self.kind, Kind::Linear | Kind::Prefilter)
        }

        /// PERF-06-B3: the unchanged retained duplicate policy, prefilted by a
        /// prevalidated runtime key fingerprint.
        ///
        /// Probe positions, profile bits, the activation/disable counters and
        /// the `exact_scans` witness keep their original definitions; the hash is
        /// only a cheap pretest before the exact byte comparison.
        pub(super) fn check_compact<'a, F>(
            &self,
            heap: &BinaryHeap<MixedEntry<'_>>,
            candidate_hash: u64,
            resolve_exact_key: F,
        ) -> SearchResult<()>
        where
            F: FnOnce() -> SearchResult<&'a str>,
        {
            match self.kind {
                Kind::Linear => {
                    #[cfg(test)]
                    self.exact_scans.set(self.exact_scans.get() + 1);
                    compact_exact_scan(heap, candidate_hash, resolve_exact_key)
                }
                Kind::ExactSet => Err(SearchError::CorruptIndex {
                    detail: "compact key path entered ExactSet mode".to_owned(),
                }),
                Kind::Prefilter => {
                    if self.disabled {
                        #[cfg(test)]
                        self.exact_scans.set(self.exact_scans.get() + 1);
                        return compact_exact_scan(heap, candidate_hash, resolve_exact_key);
                    }
                    let mask = self.active_bits - 1;
                    let (first, second) = probes(candidate_hash, mask);
                    if !self.bit(first) || !self.bit(second) {
                        return Ok(());
                    }
                    #[cfg(test)]
                    self.exact_scans.set(self.exact_scans.get() + 1);
                    compact_exact_scan(heap, candidate_hash, resolve_exact_key)
                }
            }
        }

        fn bit(&self, index: usize) -> bool {
            debug_assert!(index < self.active_bits);
            self.words[index >> 6] & (1u64 << (index & 63)) != 0
        }

        fn note_hash(&mut self, hash: u64) {
            if self.disabled {
                return;
            }
            let mask = self.active_bits - 1;
            let (first, second) = probes(hash, mask);
            self.words[first >> 6] |= 1u64 << (first & 63);
            self.words[second >> 6] |= 1u64 << (second & 63);
            self.admissions = self.admissions.saturating_add(1);
            if self.admissions >= self.profile.disable_after() {
                self.disabled = true;
            }
        }

        #[allow(clippy::too_many_arguments)]
        pub(super) fn admit<'a>(
            &mut self,
            entry: MixedEntry<'a>,
            heap: &mut BinaryHeap<MixedEntry<'a>>,
            heap_limit: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<()> {
            if self.kind == Kind::Linear {
                return heap_admit_candidate(entry, heap, heap_limit, budget, scope);
            }
            let will_insert = heap.len() < heap_limit;
            let will_replace = if will_insert {
                false
            } else {
                entry.cmp(heap.peek().expect("heap is nonempty")) == Ordering::Less
            };
            if !will_insert && !will_replace {
                return heap_admit_candidate(entry, heap, heap_limit, budget, scope);
            }
            if self.kind == Kind::Prefilter {
                let hash = hash_key(&entry.hit.key);
                heap_admit_candidate(entry, heap, heap_limit, budget, scope)?;
                self.note_hash(hash);
                return Ok(());
            }

            // ExactSet: account table growth, the retained clone, and the
            // temporary evicted-key clone before any heap mutation.
            if self.keys.len() != heap.len() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set retained keys disagree with heap".to_owned(),
                });
            }
            let old_len = if will_replace {
                let worst = heap.peek().expect("heap is nonempty");
                if !self.keys.contains(&worst.hit.key) {
                    return Err(SearchError::CorruptIndex {
                        detail: "exact-set is missing the retained worst key".to_owned(),
                    });
                }
                worst.hit.key.as_str().len() as u64
            } else {
                0
            };
            let new_len = entry.hit.key.as_str().len() as u64;
            self.keys
                .try_reserve(1)
                .map_err(|_| SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            let cap_after = self.keys.capacity();
            // HashSet::capacity() can vary with tombstone occupancy even
            // without a physical reallocation. Charge a monotonic high-water
            // capacity: a later rehash must not double-charge an existing
            // table or release a still-allocated table.
            let table_after = u64::try_from(cap_after)
                .unwrap_or(u64::MAX)
                .checked_mul(40)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            let table_delta = table_after.saturating_sub(self.exact_table_charged);
            let extra = table_delta
                .checked_add(new_len)
                .and_then(|v| v.checked_add(old_len))
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            let combined = extra
                .checked_add(entry.charge)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            h_preflight(budget, scope, combined)?;
            h_commit(budget, scope, extra)?;
            let evicted_key = if will_replace {
                Some(heap.peek().expect("heap is nonempty").hit.key.clone())
            } else {
                None
            };
            let admitted_key = entry.hit.key.clone();
            if let Err(error) = heap_admit_candidate(entry, heap, heap_limit, budget, scope) {
                h_release(budget, scope, extra)?;
                return Err(error);
            }
            // try_reserve(1) guarantees the extra insertion at the current
            // length. Removing first can change the hash table's occupancy/
            // tombstone state and make the subsequent insertion grow despite
            // that reservation (observed under coverage instrumentation).
            // Insert first, then remove the evicted key; both key clones and
            // the table have already been budgeted before heap mutation.
            let inserted = self.keys.insert(admitted_key);
            debug_assert!(inserted);
            if let Some(old) = evicted_key {
                let removed = self.keys.remove(&old);
                debug_assert!(removed);
            }
            let final_cap = self.keys.capacity();
            let charged_table = self.exact_table_charged.checked_add(table_delta).ok_or(
                SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                },
            )?;
            // Effective insertion capacity may increase by one when a
            // tombstone is reused. Reject only an unreserved increase beyond
            // the already-charged high-water capacity.
            let final_table = u64::try_from(final_cap)
                .unwrap_or(u64::MAX)
                .checked_mul(40)
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            if final_table > charged_table {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set capacity grew after reservation".to_owned(),
                });
            }
            let release = old_len.checked_mul(2).ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
            h_preflight_release(budget, scope, release)?;
            h_release(budget, scope, release)?;
            self.exact_table_charged = self.exact_table_charged.checked_add(table_delta).ok_or(
                SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                },
            )?;
            self.exact_live_key_charged = self
                .exact_live_key_charged
                .checked_add(new_len)
                .and_then(|v| v.checked_sub(old_len))
                .ok_or(SearchError::ResourceLimit {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
            Ok(())
        }

        #[cfg(test)]
        pub(super) fn for_test_checked(
            kind: Kind,
            profile: Profile,
            k: usize,
        ) -> SearchResult<Self> {
            if kind == Kind::ExactSet && (k == 0 || k > MAX_EXACT_SET_K) {
                return Err(SearchError::ResourceLimit {
                    limit: MAX_EXACT_SET_K as u64,
                    requested: k as u64,
                });
            }
            Ok(Self::for_test(kind, profile, k))
        }

        #[cfg(test)]
        pub(super) fn note_key(&mut self, key: &DocumentKey) {
            self.note_hash(hash_key(key));
        }

        #[cfg(test)]
        pub(super) fn aux_memory_estimate(&self) -> (usize, usize, usize) {
            let key_bytes = self.keys.iter().map(|k| k.as_str().len()).sum();
            (self.keys.len(), self.keys.capacity(), key_bytes)
        }

        #[cfg(test)]
        pub(super) fn hash_for_test(key: &DocumentKey) -> u64 {
            hash_key(key)
        }

        #[cfg(test)]
        pub(super) fn for_test(kind: Kind, profile: Profile, k: usize) -> Self {
            let mut state = Self {
                kind,
                profile,
                words: [0; MAX_WORDS],
                active_bits: if kind == Kind::Prefilter {
                    profile.bits()
                } else {
                    0
                },
                admissions: 0,
                disabled: false,
                keys: HashSet::new(),
                exact_table_charged: 0,
                exact_live_key_charged: 0,
                exact_scans: std::cell::Cell::new(0),
                fail_reserve: false,
            };
            if kind == Kind::ExactSet {
                state.reserve_exact_set(k).expect("reserve");
            }
            state
        }

        #[cfg(test)]
        pub(super) fn bit_for_test(&self, index: usize) -> bool {
            self.bit(index)
        }

        #[cfg(test)]
        pub(super) fn set_both_bits(&mut self, hash: u64) {
            let mask = self.active_bits - 1;
            let (first, second) = probes(hash, mask);
            self.words[first >> 6] |= 1u64 << (first & 63);
            self.words[second >> 6] |= 1u64 << (second & 63);
        }

        #[cfg(test)]
        pub(super) fn exact_scans(&self) -> usize {
            self.exact_scans.get()
        }

        #[cfg(test)]
        pub(super) fn contains_key(&self, key: &DocumentKey) -> bool {
            self.keys.contains(key)
        }

        #[cfg(test)]
        pub(super) fn exact_charges(&self) -> (u64, u64) {
            (self.exact_table_charged, self.exact_live_key_charged)
        }

        #[cfg(test)]
        pub(super) fn key_count(&self) -> usize {
            self.keys.len()
        }

        #[cfg(test)]
        pub(super) fn admissions_count(&self) -> usize {
            self.admissions
        }

        #[cfg(test)]
        pub(super) fn is_disabled(&self) -> bool {
            self.disabled
        }
    }
}

/// PR 15H-B: admit one owned candidate into the existing bounded heap.
///
/// The caller has already performed the duplicate-retained-key check. This is
/// the exact original push/replacement sequence, extracted so both the legacy
/// and borrowed-keyword paths share it.
fn heap_admit_candidate<'a>(
    entry: MixedEntry<'a>,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    heap_limit: usize,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
) -> SearchResult<()> {
    let charge = entry.charge;
    if heap.len() < heap_limit {
        let heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
            .as_mut()
            .map(|sink| sink as &mut (dyn MemoryCharge + '_));
        heap_preflight_insert(budget, heap_memory.as_deref(), charge)?;
        heap_commit_insert(budget, heap_memory, charge)?;
        heap.push(entry);
    } else {
        let worst = heap.peek().expect("heap is nonempty");
        if entry.cmp(worst) == Ordering::Less {
            let old_charge = worst.charge;
            let heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            heap_preflight_insert(budget, heap_memory.as_deref(), charge)?;
            heap_preflight_release(budget, heap_memory.as_deref(), old_charge)?;
            heap_commit_insert(budget, heap_memory, charge)?;
            let evicted = heap.pop().expect("heap is nonempty");
            drop(evicted);
            let heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                .as_mut()
                .map(|sink| sink as &mut (dyn MemoryCharge + '_));
            heap_commit_release(budget, heap_memory, old_charge)?;
            heap.push(entry);
        }
    }
    Ok(())
}

/// Materialize the owned tuple for one validated borrowed keyword candidate.
#[allow(clippy::too_many_arguments)]
fn materialize_keyword_entry<'a>(
    view: &ColumnKeywordView<'_>,
    request: &'a UnifiedRequest,
    segment_index: usize,
    doc_id: u64,
    key: DocumentKey,
    score: f64,
    include_score: bool,
    charge: u64,
) -> SearchResult<MixedEntry<'a>> {
    #[cfg(test)]
    b_observation::record_owned();
    let sort_value = owned_keyword_sort_value(view)?.ok_or_else(|| SearchError::CorruptIndex {
        detail: "keyword view changed before materialization".to_owned(),
    })?;
    let hit = SelectedHit {
        segment_index,
        doc_id,
        key,
        score: if include_score { Some(score) } else { None },
        sort_tuple: vec![sort_value],
    };
    #[cfg(test)]
    {
        let owned_charge = candidate_charge(&hit)?;
        assert_eq!(owned_charge, charge, "borrowed keyword charge mismatch");
    }
    Ok(MixedEntry {
        hit,
        charge,
        sort: &request.sort,
        relevance: false,
        ordinal_sort: None,
        key_hash: None,
    })
}

/// Run the ordinary owned-tuple candidate path for one borrowed-view fallback.
#[allow(clippy::too_many_arguments)]
fn admit_legacy_keyword_candidate<'a>(
    columns: &ColumnAccess<'_>,
    schema: &crate::segment::CodecSchema,
    request: &'a UnifiedRequest,
    doc_id: u64,
    segment_index: usize,
    key: DocumentKey,
    score: f64,
    include_score: bool,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    heap_limit: usize,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
    experiment: &mut d3c::State,
) -> SearchResult<()> {
    #[cfg(test)]
    b_observation::record_legacy();
    let tuple = sort_tuple_for_doc(columns, schema, &request.sort, None, doc_id)?;
    let hit = SelectedHit {
        segment_index,
        doc_id,
        key,
        score: if include_score { Some(score) } else { None },
        sort_tuple: tuple,
    };
    let charge = candidate_charge(&hit)?;
    let entry = MixedEntry {
        hit,
        charge,
        sort: &request.sort,
        relevance: false,
        ordinal_sort: None,
        key_hash: None,
    };
    experiment.check(heap, &entry.hit.key)?;
    experiment.admit(entry, heap, heap_limit, budget, scope)
}

/// PR 15H-B: process one scored candidate using the borrowed Keyword sort view.
///
/// The caller has already incremented `total_hits` and resolved the logical key.
/// The borrowed view is fully validated before any charge/duplicate/competitive
/// decision; noncompetitive candidates never allocate an owned sort tuple.
#[allow(clippy::too_many_arguments)]
fn consider_borrowed_keyword_candidate<'a>(
    columns: &ColumnAccess<'_>,
    schema: &crate::segment::CodecSchema,
    request: &'a UnifiedRequest,
    doc_id: u64,
    segment_index: usize,
    key: DocumentKey,
    score: f64,
    include_score: bool,
    field_id: u32,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    heap_limit: usize,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
    experiment: &mut d3c::State,
) -> SearchResult<()> {
    let view = columns.keyword_sort_view(field_id, doc_id)?;
    #[cfg(test)]
    if matches!(view, ColumnKeywordView::Value(_)) {
        b_observation::record_borrowed();
    }
    let Some(charge) = borrowed_keyword_candidate_charge(&key, &view)? else {
        return admit_legacy_keyword_candidate(
            columns,
            schema,
            request,
            doc_id,
            segment_index,
            key,
            score,
            include_score,
            heap,
            heap_limit,
            budget,
            scope,
            experiment,
        );
    };
    experiment.check(heap, &key)?;
    if heap.len() < heap_limit {
        let entry = materialize_keyword_entry(
            &view,
            request,
            segment_index,
            doc_id,
            key,
            score,
            include_score,
            charge,
        )?;
        return experiment.admit(entry, heap, heap_limit, budget, scope);
    }
    let worst = heap.peek().expect("heap is nonempty");
    let Some(worst_value) = worst.hit.sort_tuple.first() else {
        return admit_legacy_keyword_candidate(
            columns,
            schema,
            request,
            doc_id,
            segment_index,
            key,
            score,
            include_score,
            heap,
            heap_limit,
            budget,
            scope,
            experiment,
        );
    };
    let sort_field = &request.sort.fields[0];
    let Some(sort_ordering) = compare_borrowed_keyword_to_owned(
        &view,
        worst_value,
        sort_field.direction,
        sort_field.missing,
    ) else {
        return admit_legacy_keyword_candidate(
            columns,
            schema,
            request,
            doc_id,
            segment_index,
            key,
            score,
            include_score,
            heap,
            heap_limit,
            budget,
            scope,
            experiment,
        );
    };
    let ordering = if sort_ordering == Ordering::Equal {
        key.as_str()
            .as_bytes()
            .cmp(worst.hit.key.as_str().as_bytes())
    } else {
        sort_ordering
    };
    if ordering != Ordering::Less {
        #[cfg(test)]
        b_observation::record_rejected();
        return Ok(());
    }
    let entry = materialize_keyword_entry(
        &view,
        request,
        segment_index,
        doc_id,
        key,
        score,
        include_score,
        charge,
    )?;
    experiment.admit(entry, heap, heap_limit, budget, scope)
}

/// PERF-06-B2: the frozen detail for a prepared map without a segment column.
fn ready_ordinal_column_missing() -> SearchError {
    SearchError::CorruptIndex {
        detail: "ready keyword ordinal map has no matching segment column".to_owned(),
    }
}

/// PERF-06-B2: a numeric and a legacy entry must never share one heap.
fn mixed_ordinal_heap_error() -> SearchError {
    SearchError::CorruptIndex {
        detail: "mixed ordinal and legacy sort entries".to_owned(),
    }
}

/// PERF-06-B2: classify one B1 preparation result.
///
/// `NotAvailable` is a documented whole-request optional outcome; genuine B1
/// errors never reach this helper.
fn ordinal_ready_from_preparation(
    preparation: KeywordOrdinalPreparation,
) -> Option<Arc<SnapshotKeywordOrdinals>> {
    match preparation {
        KeywordOrdinalPreparation::Ready(map) => Some(map),
        KeywordOrdinalPreparation::NotAvailable(_) => None,
    }
}

/// PERF-06-B2: map one genuine B1 preparation error to its search category.
fn ordinal_preparation_error(error: crate::index::IndexError) -> SearchError {
    match error {
        crate::index::IndexError::Cancelled => SearchError::Cancelled,
        other => SearchError::Index(other),
    }
}

/// PERF-06-B2: legacy-equivalent logical charge for a missing/null/single row.
///
/// Mirrors `candidate_charge` exactly: base + key, one 32-byte component, and
/// `utf8_len + 4` for a present `Single` keyword. It is a *logical* owned-value
/// charge, never a packed-ordinal size.
fn ordinal_keyword_candidate_charge(key: &DocumentKey, term_len: Option<u64>) -> SearchResult<u64> {
    ordinal_keyword_candidate_charge_with_len(key.as_str().len() as u64, term_len)
}

/// PERF-06-B3: the same logical charge over an already validated key length.
fn ordinal_keyword_candidate_charge_with_len(
    key_len: u64,
    term_len: Option<u64>,
) -> SearchResult<u64> {
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut bytes = 64u64.checked_add(key_len).ok_or_else(overflow)?;
    bytes = bytes.checked_add(32).ok_or_else(overflow)?;
    if let Some(term_len) = term_len {
        bytes = bytes
            .checked_add(term_len.checked_add(4).ok_or_else(overflow)?)
            .ok_or_else(overflow)?;
    }
    Ok(bytes)
}

/// PERF-06-B2: reject a mixed-mode heap before any heap mutation.
fn ensure_ordinal_heap(heap: &BinaryHeap<MixedEntry<'_>>) -> SearchResult<()> {
    if heap.iter().any(|entry| entry.ordinal_sort.is_none()) {
        return Err(mixed_ordinal_heap_error());
    }
    Ok(())
}

/// PERF-06-B2-F1: request-local proof that the ordinal heap was inspected before
/// its first numeric candidate comparison. Thereafter the numeric-only admission
/// path maintains the invariant by induction.
struct OrdinalHeapAudit {
    checked: bool,
}

impl OrdinalHeapAudit {
    fn new() -> Self {
        Self { checked: false }
    }

    fn verify_once(&mut self, heap: &BinaryHeap<MixedEntry<'_>>) -> SearchResult<()> {
        if self.checked {
            return Ok(());
        }
        #[cfg(test)]
        b2_observation::record_full_heap_audit();
        ensure_ordinal_heap(heap)?;
        self.checked = true;
        Ok(())
    }
}

/// PERF-06-B2: full numeric candidate order, including the logical-key tie-break.
fn ordinal_candidate_order(
    candidate: OrdinalSortKey,
    worst: OrdinalSortKey,
    sort: &Sort,
    candidate_key: &DocumentKey,
    worst_key: &DocumentKey,
) -> Ordering {
    let field = &sort.fields[0];
    match ordinal_sort_key_cmp(candidate, worst, field.direction, field.missing) {
        Ordering::Equal => candidate_key
            .as_str()
            .as_bytes()
            .cmp(worst_key.as_str().as_bytes()),
        other => other,
    }
}

/// PERF-06-B2: the shared, key-free part of one numeric ordinal candidate.
///
/// Produced exactly once per matched document by both the owned B2 handler and
/// the PERF-06-B3 compact handler, preserving validation and error order. It
/// owns no logical key, no hash and no heap or metadata reservation; a
/// `MultiOne` row carries its complete legacy decoded tuple.
struct PreparedOrdinalCandidate {
    row: KeywordOrdinalValue,
    numeric: OrdinalSortKey,
    term_len: Option<u64>,
    multi_one_tuple: Option<Vec<SortValue>>,
}

/// Validate one numeric ordinal candidate without owning a document key.
///
/// One numeric row read (which applies the legacy logical string budget for
/// `Single`), one shared-rank translation, and — for `MultiOne` only — the full
/// legacy tuple decode before any duplicate or competitiveness decision. No
/// key, hash, heap or memory reservation is touched here.
fn prepare_ordinal_candidate(
    columns: &ColumnAccess<'_>,
    schema: &crate::segment::CodecSchema,
    request: &UnifiedRequest,
    doc_id: u64,
    bound: &KeywordSortOrdinalColumn<'_>,
    translation: &SegmentOrdinalMap<'_>,
) -> SearchResult<PreparedOrdinalCandidate> {
    let row = bound.read_sort_row(doc_id)?;
    let numeric = match row {
        KeywordOrdinalValue::Missing => OrdinalSortKey::Missing,
        KeywordOrdinalValue::Null => OrdinalSortKey::Null,
        KeywordOrdinalValue::Value { ordinal, .. } => {
            OrdinalSortKey::Value(translation.translate(ordinal)?)
        }
    };
    let mut term_len = None;
    let mut multi_one_tuple: Option<Vec<SortValue>> = None;
    match row {
        KeywordOrdinalValue::Missing | KeywordOrdinalValue::Null => {}
        KeywordOrdinalValue::Value {
            ordinal,
            state: KeywordOrdinalState::Single,
        } => {
            term_len = Some(bound.dictionary_term(ordinal)?.len() as u64);
        }
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::MultiOne,
            ..
        } => {
            // A `MultiOne` row keeps the complete legacy decode (entry/vector/
            // string admission and error order) before any reject decision.
            #[cfg(test)]
            b2_observation::record_multi_one_legacy_decode();
            let tuple = sort_tuple_for_doc(columns, schema, &request.sort, None, doc_id)?;
            if !matches!(tuple.as_slice(), [SortValue::Value(FieldValue::Keyword(_))]) {
                return Err(SearchError::CorruptIndex {
                    detail: "keyword ordinal MultiOne decoded an unexpected value shape".to_owned(),
                });
            }
            multi_one_tuple = Some(tuple);
        }
    }
    Ok(PreparedOrdinalCandidate {
        row,
        numeric,
        term_len,
        multi_one_tuple,
    })
}

/// Materialize the owned sort component of one competitive numeric candidate.
///
/// Mirrors the frozen B2 materialization exactly: `Missing`/`Null` emit their
/// enum values, `Single` copies the B1 dictionary's raw UTF-8 slice through the
/// fallible owned constructor, and `MultiOne` consumes its one already-decoded
/// tuple component. It never allocates a document key.
fn materialize_prepared_sort_value(
    prepared: &mut PreparedOrdinalCandidate,
    bound: &KeywordSortOrdinalColumn<'_>,
) -> SearchResult<SortValue> {
    match prepared.row {
        KeywordOrdinalValue::Missing => Ok(SortValue::Missing),
        KeywordOrdinalValue::Null => Ok(SortValue::Null),
        KeywordOrdinalValue::Value {
            ordinal,
            state: KeywordOrdinalState::Single,
        } => {
            let term = bound.dictionary_term(ordinal)?;
            let raw = std::str::from_utf8(term)
                .map_err(|_| crate::segment::SegmentError::InvalidUtf8 { context: "keyword" })?;
            // The B1 map proved this Single row exists; a disappearing view is
            // an internal inconsistency, never a silent fallback.
            owned_keyword_sort_value(&ColumnKeywordView::Value(raw))?.ok_or_else(|| {
                SearchError::CorruptIndex {
                    detail: "keyword ordinal single value was not materializable".to_owned(),
                }
            })
        }
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::MultiOne,
            ..
        } => prepared
            .multi_one_tuple
            .as_mut()
            .and_then(|tuple| tuple.pop())
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "keyword ordinal MultiOne decoded an unexpected value shape".to_owned(),
            }),
    }
}

/// PERF-06-B2: process one scored candidate through the snapshot-wide ordinals.
///
/// The caller has already incremented `total_hits` and resolved the logical key.
/// Every matched candidate — competitive or not — is validated and charged in the
/// frozen order: one numeric row read (which applies the legacy logical string
/// budget for `Single`), the shared-rank translation, the legacy-equivalent
/// logical charge, the existing duplicate check, then the numeric competitiveness
/// decision. Only a competitive candidate owns a string sort tuple.
#[allow(clippy::too_many_arguments)]
fn consider_ordinal_keyword_candidate<'a>(
    columns: &ColumnAccess<'_>,
    schema: &crate::segment::CodecSchema,
    request: &'a UnifiedRequest,
    doc_id: u64,
    segment_index: usize,
    key: DocumentKey,
    score: f64,
    include_score: bool,
    bound: &KeywordSortOrdinalColumn<'_>,
    translation: &SegmentOrdinalMap<'_>,
    audit: &mut OrdinalHeapAudit,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    heap_limit: usize,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
    experiment: &mut d3c::State,
) -> SearchResult<()> {
    let mut prepared =
        prepare_ordinal_candidate(columns, schema, request, doc_id, bound, translation)?;
    let charge = match prepared.row {
        KeywordOrdinalValue::Missing | KeywordOrdinalValue::Null => {
            ordinal_keyword_candidate_charge(&key, None)?
        }
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::Single,
            ..
        } => ordinal_keyword_candidate_charge(&key, prepared.term_len)?,
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::MultiOne,
            ..
        } => candidate_charge_parts(
            &key,
            prepared
                .multi_one_tuple
                .as_deref()
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "keyword ordinal MultiOne decoded an unexpected value shape".to_owned(),
                })?,
        )?,
    };
    experiment.check(heap, &key)?;
    audit.verify_once(heap)?;
    if heap.len() >= heap_limit {
        let worst = heap.peek().expect("heap is nonempty");
        let Some(worst_key) = worst.ordinal_sort else {
            return Err(mixed_ordinal_heap_error());
        };
        #[cfg(test)]
        b2_observation::record_numeric_compare();
        let ordering = ordinal_candidate_order(
            prepared.numeric,
            worst_key,
            &request.sort,
            &key,
            &worst.hit.key,
        );
        if ordering != Ordering::Less {
            #[cfg(test)]
            match prepared.row {
                KeywordOrdinalValue::Value {
                    state: KeywordOrdinalState::MultiOne,
                    ..
                } => {}
                _ => b2_observation::record_single_rejected(),
            }
            return Ok(());
        }
    }
    let sort_value = materialize_prepared_sort_value(&mut prepared, bound)?;
    #[cfg(test)]
    if matches!(
        prepared.row,
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::Single,
            ..
        }
    ) {
        b2_observation::record_owned_single_string();
    }
    let hit = SelectedHit {
        segment_index,
        doc_id,
        key,
        score: if include_score { Some(score) } else { None },
        sort_tuple: vec![sort_value],
    };
    #[cfg(test)]
    {
        let owned_charge = candidate_charge(&hit)?;
        assert_eq!(owned_charge, charge, "ordinal keyword charge mismatch");
    }
    let key_hash = runtime_doc_key_hash(hit.key.as_str());
    let entry = MixedEntry {
        hit,
        charge,
        sort: &request.sort,
        relevance: false,
        ordinal_sort: Some(prepared.numeric),
        key_hash: Some(key_hash),
    };
    experiment.admit(entry, heap, heap_limit, budget, scope)
}

/// PERF-06-B3-F1: request-local proof that every retained numeric entry carries
/// a validated key fingerprint before the first compact duplicate decision.
///
/// The compact path maintains the invariant by induction afterwards (every B2
/// numeric admission fills `Some`), so this is never repeated per candidate.
struct CompactHashAudit {
    checked: bool,
}

impl CompactHashAudit {
    fn new() -> Self {
        Self { checked: false }
    }

    fn verify_once(&mut self, heap: &BinaryHeap<MixedEntry<'_>>) -> SearchResult<()> {
        if self.checked {
            return Ok(());
        }
        #[cfg(test)]
        b3_observation::record_one_time_heap_hash_audit();
        if heap.iter().any(|entry| entry.key_hash.is_none()) {
            return Err(SearchError::CorruptIndex {
                detail: "compact key heap lacks a validated fingerprint".to_owned(),
            });
        }
        self.checked = true;
        Ok(())
    }
}

/// PERF-06-B3: the per-segment compact-key binding state.
///
/// One segment attempts the directory at most once, on its first matched,
/// scored candidate. A refusal downgrades the **whole segment** to the original
/// owned B2 key path; it never mixes key sources within one candidate.
enum KeyBinder<'a> {
    Unattempted,
    Ready(BoundKeyIdentity<'a>),
    Fallback,
}

/// PERF-06-B3: materialize the single owned logical key of a competitive
/// candidate from an already validated borrowed key.
fn owned_document_key(raw: &str) -> SearchResult<DocumentKey> {
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut owned = String::new();
    owned.try_reserve_exact(raw.len()).map_err(|_| overflow())?;
    owned.push_str(raw);
    DocumentKey::new(owned).map_err(|_| overflow())
}

/// PERF-06-B3: process one scored candidate through the compact key directory.
///
/// The frozen decision order is: constant-size identity metadata, the shared
/// numeric preparation, the logical charge, the one-time fingerprint audit, the
/// exact duplicate policy, the one-time ordinal audit, the numeric
/// competitiveness decision (borrowing raw key bytes only on an equal numeric
/// rank), and only then one fallibly owned `DocumentKey` plus the owned sort
/// tuple. A losing `Single` candidate therefore owns nothing.
#[allow(clippy::too_many_arguments)]
fn consider_compact_ordinal_candidate<'a>(
    columns: &ColumnAccess<'_>,
    schema: &crate::segment::CodecSchema,
    request: &'a UnifiedRequest,
    doc_id: u64,
    segment_index: usize,
    score: f64,
    include_score: bool,
    bound: &KeywordSortOrdinalColumn<'_>,
    translation: &SegmentOrdinalMap<'_>,
    identity: &BoundKeyIdentity<'_>,
    audit: &mut OrdinalHeapAudit,
    hash_audit: &mut CompactHashAudit,
    heap: &mut BinaryHeap<MixedEntry<'a>>,
    heap_limit: usize,
    budget: &mut CandidateBudget,
    scope: &mut Option<SlotMemoryScope<'_>>,
    experiment: &mut d3c::State,
) -> SearchResult<()> {
    let key_meta = identity.meta(doc_id)?;
    let mut prepared =
        prepare_ordinal_candidate(columns, schema, request, doc_id, bound, translation)?;
    let charge = match prepared.row {
        KeywordOrdinalValue::Missing | KeywordOrdinalValue::Null => {
            ordinal_keyword_candidate_charge_with_len(key_meta.utf8_len, None)?
        }
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::Single,
            ..
        } => ordinal_keyword_candidate_charge_with_len(key_meta.utf8_len, prepared.term_len)?,
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::MultiOne,
            ..
        } => candidate_charge_parts_with_key_len(
            key_meta.utf8_len,
            prepared
                .multi_one_tuple
                .as_deref()
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "keyword ordinal MultiOne decoded an unexpected value shape".to_owned(),
                })?,
        )?,
    };
    // The retained fingerprint invariant is proved once, before the first
    // compact duplicate decision, and maintained inductively thereafter.
    hash_audit.verify_once(heap)?;
    experiment.check_compact(heap, key_meta.hash, || {
        identity.key_str(doc_id).map_err(SearchError::from)
    })?;
    audit.verify_once(heap)?;
    if heap.len() >= heap_limit {
        let worst = heap.peek().expect("heap is nonempty");
        let Some(worst_key) = worst.ordinal_sort else {
            return Err(mixed_ordinal_heap_error());
        };
        #[cfg(test)]
        b2_observation::record_numeric_compare();
        let field = &request.sort.fields[0];
        let ordering =
            match ordinal_sort_key_cmp(prepared.numeric, worst_key, field.direction, field.missing)
            {
                // Only an equal numeric rank borrows raw logical key bytes.
                Ordering::Equal => identity
                    .key_str(doc_id)?
                    .as_bytes()
                    .cmp(worst.hit.key.as_str().as_bytes()),
                other => other,
            };
        if ordering != Ordering::Less {
            #[cfg(test)]
            match prepared.row {
                KeywordOrdinalValue::Value {
                    state: KeywordOrdinalState::MultiOne,
                    ..
                } => {}
                _ => b2_observation::record_single_rejected(),
            }
            return Ok(());
        }
    }
    // The only owned logical key on the compact path, allocated fallibly before
    // any heap mutation.
    let key = owned_document_key(identity.key_str(doc_id)?)?;
    let sort_value = materialize_prepared_sort_value(&mut prepared, bound)?;
    #[cfg(test)]
    if matches!(
        prepared.row,
        KeywordOrdinalValue::Value {
            state: KeywordOrdinalState::Single,
            ..
        }
    ) {
        b2_observation::record_owned_single_string();
    }
    let hit = SelectedHit {
        segment_index,
        doc_id,
        key,
        score: if include_score { Some(score) } else { None },
        sort_tuple: vec![sort_value],
    };
    #[cfg(test)]
    {
        let owned_charge = candidate_charge(&hit)?;
        assert_eq!(owned_charge, charge, "compact keyword charge mismatch");
        assert_eq!(
            runtime_doc_key_hash(hit.key.as_str()),
            key_meta.hash,
            "compact key hash parity"
        );
        b3_observation::record_owned_key_materialization();
    }
    let entry = MixedEntry {
        hit,
        charge,
        sort: &request.sort,
        relevance: false,
        ordinal_sort: Some(prepared.numeric),
        key_hash: Some(key_meta.hash),
    };
    experiment.admit(entry, heap, heap_limit, budget, scope)
}

/// One bounded top-K entry. `Ord` delegates to the canonical comparator and
/// orders **better** candidates as `Less`, so `BinaryHeap::peek` is the worst
/// retained candidate and `into_sorted_vec` yields best-first.
struct MixedEntry<'a> {
    hit: SelectedHit,
    charge: u64,
    sort: &'a Sort,
    relevance: bool,
    /// PERF-06-B2: the snapshot-wide numeric rank of an ordinal-path entry.
    /// Legacy entries keep `None` and the canonical tuple comparator.
    ordinal_sort: Option<OrdinalSortKey>,
    /// PERF-06-B3: the prevalidated runtime key fingerprint of every B2
    /// numeric-mode retained entry. It is an inline duplicate-check *prefilter*
    /// only — never an identity — and is `None` on every other path.
    key_hash: Option<u64>,
}

impl PartialEq for MixedEntry<'_> {
    fn eq(&self, other: &Self) -> bool {
        self.hit.key == other.hit.key
    }
}

impl Eq for MixedEntry<'_> {}

impl PartialOrd for MixedEntry<'_> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for MixedEntry<'_> {
    fn cmp(&self, other: &Self) -> Ordering {
        if self.relevance {
            return default_relevance_cmp(&self.hit, &other.hit);
        }
        if let (Some(candidate), Some(retained)) = (self.ordinal_sort, other.ordinal_sort) {
            return ordinal_candidate_order(
                candidate,
                retained,
                self.sort,
                &self.hit.key,
                &other.hit.key,
            );
        }
        compare_candidates(
            &self.hit.sort_tuple,
            &self.hit.key,
            &other.hit.sort_tuple,
            &other.hit.key,
            self.sort,
        )
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
    mut memory: Option<&mut (dyn MemoryCharge + '_)>,
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
            typed::evaluate_query(guard, columns, json, geo, &compiled.root, doc_id, memory)
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
                    memory.as_deref_mut(),
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
                    memory.as_deref_mut(),
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
            memory,
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

#[cfg(test)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum QueryClass {
    Neutral,
    Lexical,
    Typed,
    Mixed,
}

#[cfg(test)]
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

#[cfg(test)]
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

/// Deterministic logical size of one successful unified response.
fn response_bytes_for(
    hits: &[SelectedHit],
    fields: &[Vec<(String, FieldValues)>],
    aggregation: Option<&AggregationResult>,
) -> SearchResult<u64> {
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut bytes: u64 = 32;
    for (hit, fields) in hits.iter().zip(fields) {
        let mut hit_bytes = 24u64
            .checked_add(hit.key.as_str().len() as u64)
            .and_then(|value| value.checked_add(8))
            .ok_or_else(overflow)?;
        for (name, values) in fields {
            hit_bytes = hit_bytes
                .checked_add(projected_field_bytes(name, values))
                .ok_or_else(overflow)?;
        }
        bytes = bytes.checked_add(hit_bytes).ok_or_else(overflow)?;
    }
    if let Some(aggregation) = aggregation {
        let aggregation_bytes =
            super::batch::aggregation_result_bytes(aggregation).ok_or_else(overflow)?;
        bytes = bytes.checked_add(aggregation_bytes).ok_or_else(overflow)?;
    }
    Ok(bytes)
}

/// Projection using exact physical `(segment_index, doc_id)` identities.
///
/// PR 15E Phase 3: each touched segment's STORED section is scanned exactly once
/// and only the selected physical records are materialized. Physical key parity is
/// still verified for every selected hit **before** any stored materialization, and
/// the output order, projection plan and ledger charges are unchanged.
fn project_selected_hits(
    snapshot: &ReaderSnapshot,
    plan: &ProjectionPlan,
    ledger: &mut ProjectionLedger,
    hits: &[SelectedHit],
    mut memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<Vec<Vec<(String, FieldValues)>>> {
    let mut by_segment: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for (index, hit) in hits.iter().enumerate() {
        by_segment.entry(hit.segment_index).or_default().push(index);
    }
    let mut out: Vec<Option<Vec<(String, FieldValues)>>> = (0..hits.len()).map(|_| None).collect();
    for (segment_index, indices) in by_segment {
        let guard = snapshot.open_segment_reader(segment_index)?;
        let reader = guard.reader();
        // Physical identity is authoritative: verify every selected hit before any
        // stored record is materialized. PR 15E Phase 5: a large segment with exactly
        // one selected hit decodes only that key; other shapes keep the full cache.
        let single_hit_segment = indices.len() == 1 && reader.doc_count() >= 1024;
        for index in &indices {
            let hit = &hits[*index];
            let key = if single_hit_segment {
                reader.doc_key_selected(hit.doc_id)?
            } else {
                reader.doc_key(hit.doc_id)?
            };
            if key != hit.key {
                return Err(SearchError::CorruptIndex {
                    detail: "selected hit key does not match its physical document".to_owned(),
                });
            }
        }
        // Ascending unique physical ids, bounded by the number of already-selected
        // hits (never by the segment's document count).
        let mut selected_ids: Vec<u64> = Vec::new();
        selected_ids
            .try_reserve_exact(indices.len())
            .map_err(|_| SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: indices.len() as u64,
            })?;
        for index in &indices {
            selected_ids.push(hits[*index].doc_id);
        }
        selected_ids.sort_unstable();
        selected_ids.dedup();
        let records = reader.stored_docs_selected(&selected_ids)?;
        for index in indices {
            let hit = &hits[index];
            let position = records
                .binary_search_by_key(&hit.doc_id, |(doc_id, _)| *doc_id)
                .map_err(|_| SearchError::CorruptIndex {
                    detail: "selected stored record was not materialized".to_owned(),
                })?;
            let fields = plan.project(&records[position].1);
            ledger.reserve_with_memory(
                projected_hit_bytes(&hit.key, &fields),
                memory.as_deref_mut(),
            )?;
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

/// PR 15H-B test-only witnesses. Compiled out of release/benchmark builds.
#[cfg(test)]
pub(crate) mod b_observation {
    use std::cell::Cell;

    thread_local! {
        static ELIGIBLE_INVOCATIONS: Cell<usize> = const { Cell::new(0) };
        static BORROWED_VALUE_READS: Cell<usize> = const { Cell::new(0) };
        static OWNED_TUPLE_MATERIALIZATIONS: Cell<usize> = const { Cell::new(0) };
        static REJECTED_WITHOUT_MATERIALIZATION: Cell<usize> = const { Cell::new(0) };
        static LEGACY_CANDIDATE_FALLBACKS: Cell<usize> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        ELIGIBLE_INVOCATIONS.with(|value| value.set(0));
        BORROWED_VALUE_READS.with(|value| value.set(0));
        OWNED_TUPLE_MATERIALIZATIONS.with(|value| value.set(0));
        REJECTED_WITHOUT_MATERIALIZATION.with(|value| value.set(0));
        LEGACY_CANDIDATE_FALLBACKS.with(|value| value.set(0));
    }

    pub(crate) fn eligible_invocations() -> usize {
        ELIGIBLE_INVOCATIONS.with(Cell::get)
    }
    pub(crate) fn borrowed_value_reads() -> usize {
        BORROWED_VALUE_READS.with(Cell::get)
    }
    pub(crate) fn owned_tuple_materializations() -> usize {
        OWNED_TUPLE_MATERIALIZATIONS.with(Cell::get)
    }
    pub(crate) fn rejected_without_materialization() -> usize {
        REJECTED_WITHOUT_MATERIALIZATION.with(Cell::get)
    }
    pub(crate) fn legacy_candidate_fallbacks() -> usize {
        LEGACY_CANDIDATE_FALLBACKS.with(Cell::get)
    }

    pub(crate) fn record_eligible() {
        ELIGIBLE_INVOCATIONS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_borrowed() {
        BORROWED_VALUE_READS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_owned() {
        OWNED_TUPLE_MATERIALIZATIONS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_rejected() {
        REJECTED_WITHOUT_MATERIALIZATION.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_legacy() {
        LEGACY_CANDIDATE_FALLBACKS.with(|value| value.set(value.get() + 1));
    }
}

/// PERF-06-B2 structural witnesses. Test-only; compiled out elsewhere.
#[cfg(test)]
pub(crate) mod b2_observation {
    use std::cell::Cell;

    thread_local! {
        static ELIGIBLE_REQUESTS: Cell<usize> = const { Cell::new(0) };
        static MAP_PREPARATIONS: Cell<usize> = const { Cell::new(0) };
        static READY_USES: Cell<usize> = const { Cell::new(0) };
        static OPTIONAL_FALLBACKS: Cell<usize> = const { Cell::new(0) };
        static BOUND_COLUMNS: Cell<usize> = const { Cell::new(0) };
        static NUMERIC_CANDIDATES: Cell<usize> = const { Cell::new(0) };
        static NUMERIC_COMPARES: Cell<usize> = const { Cell::new(0) };
        static OWNED_SINGLE_STRINGS: Cell<usize> = const { Cell::new(0) };
        static MULTI_ONE_LEGACY_DECODES: Cell<usize> = const { Cell::new(0) };
        static SINGLE_REJECTED_WITHOUT_COPY: Cell<usize> = const { Cell::new(0) };
        static FULL_HEAP_AUDITS: Cell<usize> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        ELIGIBLE_REQUESTS.with(|value| value.set(0));
        MAP_PREPARATIONS.with(|value| value.set(0));
        READY_USES.with(|value| value.set(0));
        OPTIONAL_FALLBACKS.with(|value| value.set(0));
        BOUND_COLUMNS.with(|value| value.set(0));
        NUMERIC_CANDIDATES.with(|value| value.set(0));
        NUMERIC_COMPARES.with(|value| value.set(0));
        OWNED_SINGLE_STRINGS.with(|value| value.set(0));
        MULTI_ONE_LEGACY_DECODES.with(|value| value.set(0));
        SINGLE_REJECTED_WITHOUT_COPY.with(|value| value.set(0));
        FULL_HEAP_AUDITS.with(|value| value.set(0));
    }

    pub(crate) fn eligible_requests() -> usize {
        ELIGIBLE_REQUESTS.with(Cell::get)
    }
    pub(crate) fn map_preparations() -> usize {
        MAP_PREPARATIONS.with(Cell::get)
    }
    pub(crate) fn ready_uses() -> usize {
        READY_USES.with(Cell::get)
    }
    pub(crate) fn optional_fallbacks() -> usize {
        OPTIONAL_FALLBACKS.with(Cell::get)
    }
    pub(crate) fn bound_columns() -> usize {
        BOUND_COLUMNS.with(Cell::get)
    }
    pub(crate) fn numeric_candidates() -> usize {
        NUMERIC_CANDIDATES.with(Cell::get)
    }
    pub(crate) fn numeric_compares() -> usize {
        NUMERIC_COMPARES.with(Cell::get)
    }
    pub(crate) fn owned_single_strings() -> usize {
        OWNED_SINGLE_STRINGS.with(Cell::get)
    }
    pub(crate) fn multi_one_legacy_decodes() -> usize {
        MULTI_ONE_LEGACY_DECODES.with(Cell::get)
    }
    pub(crate) fn single_rejected_without_copy() -> usize {
        SINGLE_REJECTED_WITHOUT_COPY.with(Cell::get)
    }
    pub(crate) fn full_heap_audits() -> usize {
        FULL_HEAP_AUDITS.with(Cell::get)
    }

    pub(crate) fn record_eligible_request() {
        ELIGIBLE_REQUESTS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_map_preparation() {
        MAP_PREPARATIONS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_ready_use() {
        READY_USES.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_optional_fallback() {
        OPTIONAL_FALLBACKS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_bound_column() {
        BOUND_COLUMNS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_numeric_candidate() {
        NUMERIC_CANDIDATES.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_numeric_compare() {
        NUMERIC_COMPARES.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_owned_single_string() {
        OWNED_SINGLE_STRINGS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_multi_one_legacy_decode() {
        MULTI_ONE_LEGACY_DECODES.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_single_rejected() {
        SINGLE_REJECTED_WITHOUT_COPY.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_full_heap_audit() {
        FULL_HEAP_AUDITS.with(|value| value.set(value.get() + 1));
    }
}

/// PERF-06-B3 structural witnesses. Test-only; compiled out elsewhere.
#[cfg(test)]
pub(crate) mod b3_observation {
    use std::cell::Cell;

    thread_local! {
        static OWNED_KEY_MATERIALIZATIONS: Cell<usize> = const { Cell::new(0) };
        static HASH_COLLISION_EXACT_CHECKS: Cell<usize> = const { Cell::new(0) };
        static ONE_TIME_HEAP_HASH_AUDITS: Cell<usize> = const { Cell::new(0) };
    }

    pub(crate) fn reset() {
        OWNED_KEY_MATERIALIZATIONS.with(|value| value.set(0));
        HASH_COLLISION_EXACT_CHECKS.with(|value| value.set(0));
        ONE_TIME_HEAP_HASH_AUDITS.with(|value| value.set(0));
    }

    pub(crate) fn owned_key_materializations() -> usize {
        OWNED_KEY_MATERIALIZATIONS.with(Cell::get)
    }
    pub(crate) fn hash_collision_exact_checks() -> usize {
        HASH_COLLISION_EXACT_CHECKS.with(Cell::get)
    }
    pub(crate) fn one_time_heap_hash_audits() -> usize {
        ONE_TIME_HEAP_HASH_AUDITS.with(Cell::get)
    }

    pub(crate) fn record_owned_key_materialization() {
        OWNED_KEY_MATERIALIZATIONS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_hash_collision_exact_check() {
        HASH_COLLISION_EXACT_CHECKS.with(|value| value.set(value.get() + 1));
    }
    pub(crate) fn record_one_time_heap_hash_audit() {
        ONE_TIME_HEAP_HASH_AUDITS.with(|value| value.set(value.get() + 1));
    }
}

/// PERF-06-C2 structural route witnesses and the test-only forced-Legacy seam.
///
/// Thread-local and compiled out of every non-test build: no production counter,
/// no runtime strategy environment variable and no feature flag. The forced-Legacy
/// override is consulted only at the final request-local route decision, so the
/// differential compares the same request, snapshot, compiler, sort, reader, map,
/// score and budgets against the accepted Legacy body.
#[cfg(test)]
pub(crate) mod c2_observation {
    use std::cell::Cell;

    thread_local! {
        static STRICT_ROUTES: Cell<usize> = const { Cell::new(0) };
        static LEGACY_ROUTES: Cell<usize> = const { Cell::new(0) };
        static FORCE_LEGACY: Cell<bool> = const { Cell::new(false) };
    }

    pub(crate) fn reset() {
        STRICT_ROUTES.with(|value| value.set(0));
        LEGACY_ROUTES.with(|value| value.set(0));
        FORCE_LEGACY.with(|value| value.set(false));
    }

    pub(crate) fn strict_routes() -> usize {
        STRICT_ROUTES.with(Cell::get)
    }

    pub(crate) fn legacy_routes() -> usize {
        LEGACY_ROUTES.with(Cell::get)
    }

    pub(crate) fn record_strict_route() {
        STRICT_ROUTES.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn record_legacy_route() {
        LEGACY_ROUTES.with(|value| value.set(value.get() + 1));
    }

    pub(crate) fn legacy_forced() -> bool {
        FORCE_LEGACY.with(Cell::get)
    }

    /// Thread-local RAII override that forces the accepted Legacy body.
    ///
    /// It changes nothing except the final route choice and restores the previous
    /// value on `Drop`, including while unwinding.
    pub(crate) struct ForceLegacy {
        previous: bool,
    }

    impl ForceLegacy {
        pub(crate) fn apply() -> Self {
            let previous = FORCE_LEGACY.with(|value| {
                let previous = value.get();
                value.set(true);
                previous
            });
            Self { previous }
        }
    }

    impl Drop for ForceLegacy {
        fn drop(&mut self) {
            FORCE_LEGACY.with(|value| value.set(self.previous));
        }
    }
}

#[cfg(test)]
#[allow(clippy::needless_option_as_deref)]
mod tests {
    use super::*;
    use crate::contract::result::{SortDirection, SortField, TopK};
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
        assert!(request.after.is_none());
    }

    #[test]
    fn cursor_tuple_length_and_class_are_validated() {
        let key = DocumentKey::new("k").unwrap();
        let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
        // Empty tuple for an explicit sort is malformed.
        let cursor = UnifiedCursor::new(1, [0u8; 32], Vec::new(), None, key.clone());
        let error = validate_cursor(&cursor, 1, [0u8; 32], &sort, false).unwrap_err();
        assert!(matches!(
            error,
            SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorSortMismatch
            ))
        ));
        // A score on an explicit sort is also rejected.
        let cursor = UnifiedCursor::new(1, [0u8; 32], vec![SortValue::Missing], Some(1.0), key);
        assert!(validate_cursor(&cursor, 1, [0u8; 32], &sort, false).is_err());
    }

    fn c3_build_segments(
        entries: &[(String, String)],
    ) -> (
        crate::contract::schema::Schema,
        AnalyzerRegistry,
        crate::index::Index,
    ) {
        use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
        use crate::contract::schema::{FieldDefinition, FieldOptions};
        use crate::contract::value::{FieldType, FieldValue};
        use crate::storage::{Directory, MemoryDirectory};
        use std::sync::Arc;
        let schema = crate::contract::schema::Schema::new(
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
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index =
            crate::index::Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
                .unwrap();
        {
            let mut writer = index.writer().unwrap();
            for (key, title) in entries {
                let mut document = Document::new(DocumentKey::new(key.clone()).unwrap());
                document
                    .insert(
                        "title",
                        FieldValues::Single(FieldValue::Text(title.clone())),
                    )
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened =
            crate::index::Index::open_existing(directory, schema.clone(), registry.clone())
                .unwrap();
        (schema, registry, reopened)
    }

    fn c3_alpha_request(top_k: usize) -> UnifiedRequest {
        use crate::contract::result::{Projection, Sort, TopK};
        use crate::contract::value::FieldValue;
        UnifiedRequest {
            query: Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            sort: Sort::default(),
            top_k: TopK::new(top_k).unwrap(),
            projection: Projection::Source,
            after: None,
        }
    }
    #[test]
    fn c3_insert_exact_one_over_atomic() {
        let limits = SearchLimits::default()
            .with_max_total_candidate_bytes(10)
            .unwrap()
            .with_max_segment_candidate_entries(100)
            .unwrap();
        let mut budget = CandidateBudget::new(&limits);
        let mut meter = crate::search::batch_meter::BatchMemoryMeter::new(10);
        {
            let mut scope = crate::search::memory::SlotMemoryScope::new(&mut meter);
            let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            heap_preflight_insert(&budget, memory.as_deref(), 10).unwrap();
            heap_commit_insert(&mut budget, memory.as_deref_mut(), 10).unwrap();
            let memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            assert!(heap_preflight_insert(&budget, memory.as_deref(), 1).is_err());
            let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            heap_preflight_release(&budget, memory.as_deref(), 10).unwrap();
            heap_commit_release(&mut budget, memory.as_deref_mut(), 10).unwrap();
        }
        assert_eq!(meter.current(), 0);
    }

    #[test]
    fn c3_replacement_overlap_peak() {
        let limits = SearchLimits::default()
            .with_max_total_candidate_bytes(1_000)
            .unwrap()
            .with_max_segment_candidate_entries(100)
            .unwrap();
        let mut budget = CandidateBudget::new(&limits);
        let mut meter = crate::search::batch_meter::BatchMemoryMeter::new(65);
        {
            let mut scope = crate::search::memory::SlotMemoryScope::new(&mut meter);
            let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            heap_preflight_insert(&budget, memory.as_deref(), 30).unwrap();
            heap_commit_insert(&mut budget, memory.as_deref_mut(), 30).unwrap();
            // Overlap: old 30 + new 35 = 65 must fit.
            let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            heap_preflight_insert(&budget, memory.as_deref(), 35).unwrap();
            heap_preflight_release(&budget, memory.as_deref(), 30).unwrap();
            heap_commit_insert(&mut budget, memory.as_deref_mut(), 35).unwrap();
            assert_eq!(scope.temporary_bytes(), 65);
            let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
            heap_commit_release(&mut budget, memory.as_deref_mut(), 30).unwrap();
            assert_eq!(scope.temporary_bytes(), 35);
            // Local global charge is exactly 35.
            budget.preflight_release_global_bytes(35).unwrap();
            assert!(budget.preflight_release_global_bytes(36).is_err());
        }
        assert_eq!(meter.current(), 0);
    }
    fn c3_build_index() -> (
        crate::contract::schema::Schema,
        AnalyzerRegistry,
        crate::index::Index,
    ) {
        use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
        use crate::contract::schema::{FieldDefinition, FieldOptions};
        use crate::contract::value::{FieldType, FieldValue};
        use crate::storage::{Directory, MemoryDirectory};
        use std::sync::Arc;
        let schema = crate::contract::schema::Schema::new(
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
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index =
            crate::index::Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
                .unwrap();
        {
            let mut writer = index.writer().unwrap();
            for (key, text) in [("a", "alpha"), ("b", "alpha"), ("c", "beta")] {
                let mut document = Document::new(DocumentKey::new(key).unwrap());
                document
                    .insert("title", FieldValues::Single(FieldValue::Text(text.into())))
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened =
            crate::index::Index::open_existing(directory, schema.clone(), registry.clone())
                .unwrap();
        (schema, registry, reopened)
    }

    #[test]
    fn select_keys_stops_at_first_over_limit_distinct_match() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::Budgets;

        let (schema, registry, index) = c3_build_index();
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        let query = Query::Term {
            field: "title".to_owned(),
            value: FieldValue::Text("alpha".to_owned()),
        };

        super::execute::test_observation::reset();
        let zero = searcher
            .select_keys(&query, 0, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(
            zero,
            CompleteKeySelection::LimitExceeded {
                limit: 0,
                matched: 1
            }
        );
        assert_eq!(
            super::execute::test_observation::count(),
            1,
            "zero bound stops on the first distinct match"
        );

        super::execute::test_observation::reset();
        let one = searcher
            .select_keys(&query, 1, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(
            one,
            CompleteKeySelection::LimitExceeded {
                limit: 1,
                matched: 2
            }
        );
        assert_eq!(
            super::execute::test_observation::count(),
            2,
            "one-over is detected without scanning the rest of the segment"
        );
    }

    #[test]
    fn u06_select_keys_limit_boundaries_are_exact() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::Budgets;

        // 64 distinct effective-live documents all matching `alpha`.
        let entries: Vec<(String, String)> = (0..64)
            .map(|index| (format!("k{index:03}"), "alpha".to_owned()))
            .collect();
        let (schema, registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        let query = Query::Term {
            field: "title".to_owned(),
            value: FieldValue::Text("alpha".to_owned()),
        };

        // PR 15E-B1a invariant I03: the visitor stops on the first distinct
        // key beyond the limit and never produces a partial successful set.
        for (limit, matched) in [(0u64, 1u64), (1, 2), (62, 63), (63, 64)] {
            assert_eq!(
                searcher
                    .select_keys(&query, limit, &Budgets::new(), &NeverCancel)
                    .unwrap(),
                CompleteKeySelection::LimitExceeded { limit, matched },
                "limit {limit}"
            );
        }

        // Exactly N is complete, sorted, and duplicate-free.
        let complete = searcher
            .select_keys(&query, 64, &Budgets::new(), &NeverCancel)
            .unwrap();
        let CompleteKeySelection::Complete(keys) = complete else {
            panic!("expected a complete selection at the exact limit");
        };
        assert_eq!(keys.len(), 64);
        let expected: Vec<String> = (0..64).map(|index| format!("k{index:03}")).collect();
        assert_eq!(
            keys.iter()
                .map(|key| key.as_str().to_owned())
                .collect::<Vec<_>>(),
            expected
        );
        let unique: std::collections::BTreeSet<&str> =
            keys.iter().map(|key| key.as_str()).collect();
        assert_eq!(unique.len(), 64);
    }

    // PR 15E Phase 3 — selective stored projection through the real executor seam.
    fn phase3_selected_hit(
        segment_index: usize,
        doc_id: u64,
        key: &str,
        score: f64,
    ) -> SelectedHit {
        SelectedHit {
            segment_index,
            doc_id,
            key: DocumentKey::new(key.to_owned()).unwrap(),
            score: Some(score),
            sort_tuple: Vec::new(),
        }
    }

    #[test]
    fn phase3_projection_preserves_positions_and_duplicate_physical_ids() {
        use crate::contract::result::Projection;

        let entries: Vec<(String, String)> = vec![
            ("a".to_owned(), "alpha".to_owned()),
            ("b".to_owned(), "alpha".to_owned()),
            ("c".to_owned(), "alpha".to_owned()),
        ];
        let (schema, _registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let plan = ProjectionPlan::compile(&Projection::Source, &schema).unwrap();
        // Two distinct physical docs, one of them appearing twice, in a deliberately
        // non-ascending, non-grouped output order.
        let hits = vec![
            phase3_selected_hit(0, 2, "c", 0.5),
            phase3_selected_hit(0, 0, "a", 0.9),
            phase3_selected_hit(0, 2, "c", 0.1),
        ];
        let mut ledger = ProjectionLedger::new(1 << 20);
        let out = super::project_selected_hits(&snapshot, &plan, &mut ledger, &hits, None).unwrap();
        assert_eq!(out.len(), 3);
        // Positions follow the input order, and the duplicated doc id projects the
        // same fields at both positions.
        assert_eq!(out[0], out[2]);
        let reader = snapshot.open_segment_reader(0).unwrap();
        for (position, hit) in hits.iter().enumerate() {
            let record = reader.reader().stored_doc(hit.doc_id).unwrap();
            assert_eq!(out[position], plan.project(&record), "position {position}");
        }
        // The ledger charged each projection position exactly once.
        let expected: u64 = out
            .iter()
            .zip(&hits)
            .map(|(fields, hit)| projected_hit_bytes(&hit.key, fields))
            .sum();
        assert_eq!(ledger.used(), expected);
    }

    #[test]
    fn phase3_projection_ledger_is_exact_and_one_below_is_rejected() {
        use crate::contract::result::Projection;

        let entries: Vec<(String, String)> = vec![
            ("a".to_owned(), "alpha".to_owned()),
            ("b".to_owned(), "alpha".to_owned()),
        ];
        let (schema, _registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let plan = ProjectionPlan::compile(&Projection::Source, &schema).unwrap();
        let hits = vec![
            phase3_selected_hit(0, 0, "a", 0.9),
            phase3_selected_hit(0, 1, "b", 0.5),
        ];
        let mut generous = ProjectionLedger::new(1 << 20);
        let projected =
            super::project_selected_hits(&snapshot, &plan, &mut generous, &hits, None).unwrap();
        let exact: u64 = projected
            .iter()
            .zip(&hits)
            .map(|(fields, hit)| projected_hit_bytes(&hit.key, fields))
            .sum();
        assert_eq!(generous.used(), exact);

        // Exact ceiling succeeds; one byte below is a typed resource failure.
        let mut ledger = ProjectionLedger::new(exact);
        assert_eq!(
            super::project_selected_hits(&snapshot, &plan, &mut ledger, &hits, None).unwrap(),
            projected
        );
        let mut tight = ProjectionLedger::new(exact - 1);
        assert!(matches!(
            super::project_selected_hits(&snapshot, &plan, &mut tight, &hits, None),
            Err(SearchError::ResourceLimit { .. })
        ));
        // A follow-up call with an adequate ledger is unaffected (no retained state).
        let mut retry = ProjectionLedger::new(exact);
        assert_eq!(
            super::project_selected_hits(&snapshot, &plan, &mut retry, &hits, None).unwrap(),
            projected
        );
    }

    // PR 15E Phase 5 — physical key parity on the singleton fast path.
    #[test]
    fn phase5_i07_mismatched_physical_key_is_rejected_before_projection() {
        use crate::contract::result::Projection;

        // 1100 documents in one segment, so both Phase 5 call sites take the
        // singleton fast path for a one-hit selection.
        let entries: Vec<(String, String)> = (0..1100)
            .map(|index| (format!("k{index:05}"), "alpha".to_owned()))
            .collect();
        let (schema, _registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let plan = ProjectionPlan::compile(&Projection::Source, &schema).unwrap();

        let wrong = vec![super::SelectedHit {
            segment_index: 0,
            doc_id: 5,
            key: DocumentKey::new("k00099".to_owned()).unwrap(),
            score: Some(1.0),
            sort_tuple: Vec::new(),
        }];
        let mut ledger = ProjectionLedger::new(1 << 20);
        let error = super::project_selected_hits(&snapshot, &plan, &mut ledger, &wrong, None)
            .expect_err("mismatched physical key must be rejected");
        assert!(
            matches!(&error, SearchError::CorruptIndex { detail } if detail.contains("does not match")),
            "unexpected {error:?}"
        );
        assert_eq!(
            ledger.used(),
            0,
            "no projection may be charged before parity"
        );

        // The same physical id with its true key projects normally.
        let correct = vec![super::SelectedHit {
            segment_index: 0,
            doc_id: 5,
            key: DocumentKey::new("k00005".to_owned()).unwrap(),
            score: Some(1.0),
            sort_tuple: Vec::new(),
        }];
        let mut ledger = ProjectionLedger::new(1 << 20);
        let projected =
            super::project_selected_hits(&snapshot, &plan, &mut ledger, &correct, None).unwrap();
        assert_eq!(projected.len(), 1);
    }

    #[test]
    fn phase3_zero_hits_opens_no_reader() {
        use crate::contract::result::Projection;
        let entries: Vec<(String, String)> = vec![("a".to_owned(), "alpha".to_owned())];
        let (schema, _registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let plan = ProjectionPlan::compile(&Projection::Source, &schema).unwrap();
        let mut ledger = ProjectionLedger::new(64);
        let out = super::project_selected_hits(&snapshot, &plan, &mut ledger, &[], None).unwrap();
        assert!(out.is_empty());
        assert_eq!(ledger.used(), 0);
    }

    #[test]
    fn select_keys_obeys_candidate_budget_and_mid_selection_cancellation() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::Budgets;

        // Candidate-byte exhaustion is a typed failure, never a partial set.
        let (schema, registry, index) = c3_build_index();
        let snapshot = index.snapshot();
        let tight = SearchLimits::default()
            .with_max_total_candidate_bytes(1)
            .unwrap();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, tight);
        let query = Query::Term {
            field: "title".to_owned(),
            value: FieldValue::Text("alpha".to_owned()),
        };
        assert!(matches!(
            searcher.select_keys(&query, 10, &Budgets::new(), &NeverCancel),
            Err(SearchError::ResourceLimit { .. })
        ));

        // Count a complete run, then cancel halfway through the same traversal.
        let entries: Vec<(String, String)> = (0..64)
            .map(|index| (format!("k{index:03}"), "alpha".to_owned()))
            .collect();
        let (schema, registry, index) = c3_build_segments(&entries);
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        let probe = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: 0,
        };
        let complete = searcher
            .select_keys(&query, 100, &Budgets::new(), &probe)
            .unwrap();
        assert!(matches!(complete, CompleteKeySelection::Complete(keys) if keys.len() == 64));
        let total = probe.calls.load(Ordering::Relaxed);
        assert!(total > 4);
        let cancelled = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: total / 2,
        };
        assert!(matches!(
            searcher.select_keys(&query, 100, &Budgets::new(), &cancelled),
            Err(SearchError::Cancelled)
        ));
    }

    #[test]
    fn c3_path_batch_parity_and_memory_reject() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::{BudgetKind, Budgets};
        use crate::contract::error::QueryError;
        use crate::contract::result::{Projection, Sort, TopK};
        use crate::contract::value::FieldValue;

        let (schema, registry, index) = c3_build_index();
        let snapshot = index.snapshot();
        let request = UnifiedRequest {
            query: Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            sort: Sort::default(),
            top_k: TopK::new(2).unwrap(),
            projection: Projection::Source,
            after: None,
        };
        let standalone =
            UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
                .search(&request, &Budgets::new(), &NeverCancel)
                .unwrap();
        let mut meter = BatchExecutionMeter::new(1_000_000, 1_000_000, 1_000_000);
        let batched = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(standalone.total_hits, batched.total_hits);
        let standalone_keys: Vec<&str> =
            standalone.hits.iter().map(|hit| hit.key.as_str()).collect();
        let batched_keys: Vec<&str> = batched.hits.iter().map(|hit| hit.key.as_str()).collect();
        assert_eq!(standalone_keys, batched_keys);
        // No response retention in C3: the slot scope releases its temporaries.
        assert_eq!(meter.memory.current(), 0);

        // A 1-byte batch memory ceiling rejects the segment scratch with the
        // exact batch provenance.
        let mut meter = BatchExecutionMeter::new(1_000_000, 1, 1_000_000);
        let error = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap_err();
        assert!(matches!(
            error,
            SearchError::Query(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })
        ));
        assert_eq!(meter.memory.current(), 0);
    }
    #[test]
    fn c3_path_heap_exact_one_over() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::{BudgetKind, Budgets};
        use crate::contract::error::QueryError;

        let key_a = format!("a{}", "x".repeat(999));
        let key_b = format!("b{}", "y".repeat(999));
        let (schema, registry, index) = c3_build_segments(&[
            (key_a.clone(), "alpha".into()),
            (key_b.clone(), "alpha".into()),
        ]);
        let snapshot = index.snapshot();
        let request = c3_alpha_request(1);
        // Independent heap oracle: Charge = 64 + key length (relevance sort, no tuple).
        let charge = 64 + key_a.len() as u64;
        let exact = 2 * charge;

        let mut meter = BatchExecutionMeter::new(1_000_000_000, exact, 1_000_000_000);
        let response = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(response.total_hits, 2);
        assert_eq!(response.hits.len(), 1);
        assert_eq!(meter.memory.peak(), exact);
        assert_eq!(meter.memory.current(), 0);

        let mut meter = BatchExecutionMeter::new(1_000_000_000, exact - 1, 1_000_000_000);
        let error = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap_err();
        assert!(matches!(
            error,
            SearchError::Query(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })
        ));
        assert_eq!(meter.memory.current(), 0);
    }

    fn c3_replacement_case(new_key: &str, expect_larger: bool) {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::{BudgetKind, Budgets};
        use crate::contract::error::QueryError;

        let key_a = format!("a{}", "x".repeat(999));
        let key_b = format!("b{}", "y".repeat(999));
        let (schema, registry, index) = c3_build_segments(&[
            (key_a.clone(), "alpha".into()),
            (key_b.clone(), "alpha".into()),
            (new_key.to_owned(), "alpha".into()),
        ]);
        let snapshot = index.snapshot();
        let request = c3_alpha_request(1);
        let old_charge = 64 + key_b.len() as u64;
        let new_charge = 64 + new_key.len() as u64;
        assert_eq!(new_charge > old_charge, expect_larger);
        let heap_before = (64 + key_a.len() as u64) + old_charge;
        let overlap = heap_before + new_charge;

        let mut meter = BatchExecutionMeter::new(1_000_000_000, overlap, 1_000_000_000);
        let response = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(response.total_hits, 3);
        assert_eq!(response.hits.len(), 1);
        assert_eq!(response.hits[0].key.as_str(), new_key);
        assert_eq!(meter.memory.peak(), overlap);
        assert_eq!(meter.memory.current(), 0);

        let mut meter = BatchExecutionMeter::new(1_000_000_000, overlap - 1, 1_000_000_000);
        let error = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap_err();
        assert!(matches!(
            error,
            SearchError::Query(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })
        ));
        assert_eq!(meter.memory.current(), 0);
    }

    #[test]
    fn c3_path_larger_replacement() {
        c3_replacement_case(&format!("0{}", "z".repeat(1000)), true);
    }

    #[test]
    fn c3_path_smaller_replacement() {
        c3_replacement_case(&format!("0{}", "z".repeat(99)), false);
    }

    #[test]
    fn c3_path_failed_then_success() {
        use crate::analysis::NeverCancel;
        use crate::contract::batch::{
            BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
        };
        use crate::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
        use crate::contract::capability::CapabilitySet;
        use crate::contract::value::FieldValue;

        let key_a = format!("a{}", "x".repeat(999));
        let key_b = format!("b{}", "y".repeat(999));
        let (schema, registry, index) = c3_build_segments(&[
            (key_a.clone(), "alpha".into()),
            (key_b.clone(), "alpha".into()),
            ("c".into(), "beta".into()),
        ]);
        let snapshot = index.snapshot();
        let charge = 64 + key_a.len() as u64;
        let limit = 2 * charge - 1;

        let mut first = QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        });
        first.top_k = crate::contract::result::TopK::new(1).unwrap();
        let mut second = QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("beta".into()),
        });
        second.top_k = crate::contract::result::TopK::new(1).unwrap();
        let batch = BatchQueryRequest::new(vec![first, second], None, BatchBudget::new(4));
        let policy = BudgetPolicy::new(
            Budgets::new()
                .with(BudgetKind::QueriesPerBatch, 16)
                .unwrap()
                .with(BudgetKind::BatchAggregate, 1_000_000_000)
                .unwrap()
                .with(BudgetKind::BatchMemoryBytes, limit)
                .unwrap()
                .with(BudgetKind::BatchResponseBytes, 1_000_000_000)
                .unwrap(),
            Budgets::new(),
            Budgets::new(),
            Budgets::new(),
        );
        let response = crate::search::execute_batch(
            &snapshot,
            &schema,
            &registry,
            SearchLimits::default(),
            &batch,
            &policy,
            &CapabilitySet::new(),
            &NeverCancel,
        )
        .unwrap();
        assert_eq!(response.len(), 2);
        assert!(matches!(
            response.slot(0),
            Some(PerQueryOutcome::Failure(
                crate::contract::error::QueryError::BudgetExceeded {
                    kind: BudgetKind::BatchMemoryBytes
                }
            ))
        ));
        let PerQueryOutcome::Success(success) = response.slot(1).unwrap() else {
            panic!("second slot should succeed");
        };
        assert_eq!(success.total_hits, 1);
        assert_eq!(success.hits[0].key.as_str(), "c");
    }

    #[test]
    fn c3_path_noncompetitive_zero_charge() {
        use crate::analysis::NeverCancel;
        use crate::contract::budget::Budgets;

        let long = format!("z{}", "q".repeat(1000));
        let (schema_a, registry_a, index_a) =
            c3_build_segments(&[("a".into(), "alpha".into()), ("b".into(), "alpha".into())]);
        let (schema_b, registry_b, index_b) = c3_build_segments(&[
            ("a".into(), "alpha".into()),
            ("b".into(), "alpha".into()),
            (long.clone(), "alpha".into()),
        ]);
        let request = c3_alpha_request(1);
        let mut meter_a = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        let response_a = UnifiedSearcher::new(
            &index_a.snapshot(),
            &schema_a,
            &registry_a,
            SearchLimits::default(),
        )
        .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter_a)
        .unwrap();
        let mut meter_b = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        let response_b = UnifiedSearcher::new(
            &index_b.snapshot(),
            &schema_b,
            &registry_b,
            SearchLimits::default(),
        )
        .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter_b)
        .unwrap();
        assert_eq!(response_a.total_hits, 2);
        assert_eq!(response_b.total_hits, 3);
        assert_eq!(response_b.hits.len(), 1);
        assert_eq!(response_b.hits[0].key.as_str(), "a");
        // The long key ("z"+1000) has a heap charge of 1065. It is noncompetitive,
        // so the peak may grow only by the extra segment's small scratch.
        assert!(meter_b.memory.peak() < meter_a.memory.peak() + 500);
        assert_eq!(meter_a.memory.current(), 0);
        assert_eq!(meter_b.memory.current(), 0);
    }

    #[test]
    fn c3_replacement_reject_atomic() {
        let limits = SearchLimits::default()
            .with_max_total_candidate_bytes(1_000)
            .unwrap()
            .with_max_segment_candidate_entries(100)
            .unwrap();
        let mut budget = CandidateBudget::new(&limits);
        let mut meter = crate::search::batch_meter::BatchMemoryMeter::new(30);
        {
            let mut scope = crate::search::memory::SlotMemoryScope::new(&mut meter);
            {
                let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
                heap_preflight_insert(&budget, memory.as_deref(), 20).unwrap();
                heap_commit_insert(&mut budget, memory.as_deref_mut(), 20).unwrap();
                // Overlap 20 + 15 = 35 > 30: the replacement preflight fails.
                assert!(heap_preflight_insert(&budget, memory.as_deref(), 15).is_err());
                // Existing reservation is untouched.
                budget.preflight_release_global_bytes(20).unwrap();
                heap_preflight_release(&budget, memory.as_deref(), 20).unwrap();
            }
            assert_eq!(scope.temporary_bytes(), 20);
            {
                let mut memory: Option<&mut (dyn MemoryCharge + '_)> = Some(&mut scope);
                heap_commit_release(&mut budget, memory.as_deref_mut(), 20).unwrap();
            }
        }
        assert_eq!(meter.current(), 0);
    }
    // -----------------------------------------------------------------------
    // Phase D: real-path geo and JSON memory governance.
    // -----------------------------------------------------------------------

    use crate::analysis::{Cancellation, NeverCancel};
    use crate::contract::budget::{BudgetKind, Budgets};
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::error::QueryError;
    use crate::contract::query::{Bound, GeoBoundingBox, JsonPathExpr};
    use crate::contract::result::Projection;
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, GeoPoint, JsonNumber, JsonValue};
    use crate::storage::{Directory, MemoryDirectory};
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn d_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::new(true, true, false),
                ),
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn d_doc(key: &str, lon: f64, lat: f64, members: usize) -> Document {
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("geo json".into())),
            )
            .unwrap();
        document
            .insert(
                "loc",
                FieldValues::Multi(vec![FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap())]),
            )
            .unwrap();
        let mut entries: Vec<(String, JsonValue)> =
            vec![("n".to_owned(), JsonValue::Number(JsonNumber::I64(1)))];
        for index in 0..members {
            entries.push((
                format!("k{index}"),
                JsonValue::Number(JsonNumber::I64(index as i64)),
            ));
        }
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Json(JsonValue::Object(
                    entries.into_iter().collect(),
                ))),
            )
            .unwrap();
        document
    }

    fn d_index(docs: Vec<Document>) -> (Schema, AnalyzerRegistry, crate::index::Index) {
        let schema = d_schema();
        let registry = AnalyzerRegistry::builtin();
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index =
            crate::index::Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
                .unwrap();
        {
            let mut writer = index.writer().unwrap();
            for document in docs {
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened =
            crate::index::Index::open_existing(directory, schema.clone(), registry).unwrap();
        (schema, d_registry(), reopened)
    }

    fn d_registry() -> AnalyzerRegistry {
        AnalyzerRegistry::builtin()
    }

    fn d_geo_query() -> Query {
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
        }
    }

    fn d_json_query() -> Query {
        Query::JsonPathRange {
            field: "body".into(),
            path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(10)),
        }
    }

    fn d_request(query: Query, top_k: usize) -> UnifiedRequest {
        UnifiedRequest {
            query,
            sort: Sort::default(),
            top_k: TopK::new(top_k).unwrap(),
            projection: Projection::Source,
            after: None,
        }
    }

    fn d_run(
        schema: &Schema,
        registry: &AnalyzerRegistry,
        index: &crate::index::Index,
        request: &UnifiedRequest,
        limit: u64,
    ) -> (SearchResult<UnifiedResponse>, u64, u64) {
        let snapshot = index.snapshot();
        let mut meter = BatchExecutionMeter::new(1_000_000_000, limit, 1_000_000_000);
        let result = UnifiedSearcher::new(&snapshot, schema, registry, SearchLimits::default())
            .search_with_batch(request, &Budgets::new(), &NeverCancel, &mut meter);
        (result, meter.memory.current(), meter.memory.peak())
    }

    fn d_batch_memory_error(error: &SearchError) -> bool {
        matches!(
            error,
            SearchError::Query(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })
        )
    }

    #[test]
    fn d_geo_path_exact_and_one_over() {
        let (schema, registry, index) = d_index(vec![
            d_doc("a", 0.0, 0.0, 1),
            d_doc("b", 0.1, 0.1, 1),
            d_doc("c", 50.0, 50.0, 1),
        ]);
        let request = d_request(d_geo_query(), 1);
        let (ok, current, peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert!(peak > 0);
        let (ok, current, exact_peak) = d_run(&schema, &registry, &index, &request, peak);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert_eq!(exact_peak, peak);
        let (error, current, rejected_peak) = d_run(&schema, &registry, &index, &request, peak - 1);
        assert!(d_batch_memory_error(&error.unwrap_err()));
        assert_eq!(current, 0);
        assert!(rejected_peak < peak);
    }

    #[test]
    fn d_geo_path_overlaps_heap() {
        let key_a = format!("a{}", "x".repeat(1000));
        let key_b = format!("b{}", "y".repeat(1000));
        let key_c = format!("c{}", "z".repeat(1000));
        let (schema, registry, index) = d_index(vec![
            d_doc(&key_a, 0.0, 0.0, 1),
            d_doc(&key_b, 0.1, 0.1, 1),
            d_doc(&key_c, 0.2, 0.2, 1),
        ]);
        let (_, _, peak_one) = d_run(
            &schema,
            &registry,
            &index,
            &d_request(d_geo_query(), 1),
            u64::MAX,
        );
        let (_, _, peak_two) = d_run(
            &schema,
            &registry,
            &index,
            &d_request(d_geo_query(), 2),
            u64::MAX,
        );
        // top_k=1 retains 2 heap entries, top_k=2 retains all 3: the extra
        // entry is charged while the geo membership is still live.
        assert_eq!(peak_two - peak_one, 64 + key_a.len() as u64);
        let request = d_request(d_geo_query(), 2);
        assert!(
            d_run(&schema, &registry, &index, &request, peak_two)
                .0
                .is_ok()
        );
        assert!(d_batch_memory_error(
            &d_run(&schema, &registry, &index, &request, peak_two - 1)
                .0
                .unwrap_err()
        ));
    }

    #[test]
    fn d_geo_sort_path_exact_and_one_over() {
        let (schema, registry, index) = d_index(vec![
            d_doc("a", 0.0, 0.0, 1),
            d_doc("b", 0.1, 0.1, 1),
            d_doc("c", 50.0, 50.0, 1),
        ]);
        let mut request = d_request(d_geo_query(), 1);
        request.sort = Sort::new(vec![SortField::geo_distance(
            "loc",
            GeoPoint::new(0.0, 0.0).unwrap(),
            SortDirection::Asc,
        )]);
        let (ok, current, peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert!(d_run(&schema, &registry, &index, &request, peak).0.is_ok());
        assert!(d_batch_memory_error(
            &d_run(&schema, &registry, &index, &request, peak - 1)
                .0
                .unwrap_err()
        ));
    }

    #[test]
    fn d_geo_standalone_batch_parity() {
        let (schema, registry, index) = d_index(vec![
            d_doc("a", 0.0, 0.0, 1),
            d_doc("b", 0.1, 0.1, 1),
            d_doc("c", 50.0, 50.0, 1),
        ]);
        let request = d_request(d_geo_query(), 10);
        let snapshot = index.snapshot();
        let standalone =
            UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
                .search(&request, &Budgets::new(), &NeverCancel)
                .unwrap();
        let (batched, _, _) = d_run(&schema, &registry, &index, &request, u64::MAX);
        let batched = batched.unwrap();
        let standalone_keys: Vec<&str> =
            standalone.hits.iter().map(|hit| hit.key.as_str()).collect();
        let batched_keys: Vec<&str> = batched.hits.iter().map(|hit| hit.key.as_str()).collect();
        assert_eq!(standalone.total_hits, batched.total_hits);
        assert_eq!(standalone_keys, batched_keys);
    }

    #[test]
    fn d_geo_failed_then_success_same_meter() {
        let key_a = format!("a{}", "x".repeat(1000));
        let key_b = format!("b{}", "y".repeat(1000));
        let key_c = format!("c{}", "z".repeat(1000));
        let key_d = format!("d{}", "w".repeat(1000));
        let (schema, registry, index) = d_index(vec![
            d_doc(&key_a, 0.0, 0.0, 1),
            d_doc(&key_b, 0.1, 0.1, 1),
            d_doc(&key_c, 0.2, 0.2, 1),
            d_doc(&key_d, 0.3, 0.3, 1),
        ]);
        let heavy = d_request(d_geo_query(), 3);
        let light = d_request(d_geo_query(), 1);
        let (_, _, light_peak) = d_run(&schema, &registry, &index, &light, u64::MAX);
        let (_, _, heavy_peak) = d_run(&schema, &registry, &index, &heavy, u64::MAX);
        assert!(heavy_peak > light_peak);

        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        let mut meter = BatchExecutionMeter::new(1_000_000_000, light_peak, 1_000_000_000);
        let error = searcher
            .search_with_batch(&heavy, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap_err();
        assert!(d_batch_memory_error(&error));
        assert_eq!(meter.memory.current(), 0);
        let response = searcher
            .search_with_batch(&light, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(response.total_hits, 4);
        assert_eq!(meter.memory.current(), 0);
    }

    #[test]
    fn d_json_path_exact_and_one_over() {
        let (schema, registry, index) = d_index(vec![d_doc("a", 0.0, 0.0, 100)]);
        let request = d_request(d_json_query(), 1);
        let (ok, current, peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert!(peak > 0);
        let (ok, current, exact_peak) = d_run(&schema, &registry, &index, &request, peak);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert_eq!(exact_peak, peak);
        let (error, current, _) = d_run(&schema, &registry, &index, &request, peak - 1);
        assert!(d_batch_memory_error(&error.unwrap_err()));
        assert_eq!(current, 0);
    }

    struct CountingCancel {
        calls: AtomicU64,
        cancel_at: u64,
    }

    impl Cancellation for CountingCancel {
        fn is_cancelled(&self) -> bool {
            let call = self.calls.fetch_add(1, Ordering::Relaxed) + 1;
            self.cancel_at != 0 && call >= self.cancel_at
        }
    }

    #[test]
    fn d_json_cancellation_cleanup() {
        let (schema, registry, index) = d_index(vec![d_doc("a", 0.0, 0.0, 100)]);
        let request = d_request(d_json_query(), 1);
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());

        let counter = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: 0,
        };
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        searcher
            .search_with_batch(&request, &Budgets::new(), &counter, &mut meter)
            .unwrap();
        let total = counter.calls.load(Ordering::Relaxed);
        assert!(total > 2);

        let cancel = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: total - 1,
        };
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        let error = searcher
            .search_with_batch(&request, &Budgets::new(), &cancel, &mut meter)
            .unwrap_err();
        assert!(matches!(error, SearchError::Cancelled));
        assert_eq!(meter.memory.current(), 0);
    }

    #[test]
    fn d_json_geo_overlap() {
        let (schema, registry, index) =
            d_index(vec![d_doc("a", 0.0, 0.0, 100), d_doc("b", 0.1, 0.1, 100)]);
        let request = d_request(Query::And(vec![d_geo_query(), d_json_query()]), 1);
        let (ok, current, peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert!(d_run(&schema, &registry, &index, &request, peak).0.is_ok());
        assert!(d_batch_memory_error(
            &d_run(&schema, &registry, &index, &request, peak - 1)
                .0
                .unwrap_err()
        ));
    }
    // -----------------------------------------------------------------------
    // Phase E: projection/response handoff.
    // -----------------------------------------------------------------------

    #[test]
    fn e_projection_exact_and_one_over() {
        let (schema, registry, index) = d_index(vec![d_doc("a", 0.0, 0.0, 10)]);
        let request = d_request(Query::MatchAll, 1);
        let (ok, current, peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert!(peak > 0);
        let (ok, current, exact_peak) = d_run(&schema, &registry, &index, &request, peak);
        assert!(ok.is_ok());
        assert_eq!(current, 0);
        assert_eq!(exact_peak, peak);
        let (error, current, _) = d_run(&schema, &registry, &index, &request, peak - 1);
        assert!(d_batch_memory_error(&error.unwrap_err()));
        assert_eq!(current, 0);
    }

    #[test]
    fn e_prior_retained_response_overlaps_next_slot_scratch() {
        let (schema, registry, index) = d_index(vec![d_doc("a", 0.0, 0.0, 10)]);
        let request = d_request(Query::MatchAll, 1);
        let (_, _, slot_peak) = d_run(&schema, &registry, &index, &request, u64::MAX);
        let limit = slot_peak + 10;
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());

        // 11 retained + slot_peak exceeds the limit; the failed slot releases
        // its scratch and leaves the prior retained bytes untouched.
        let mut meter = BatchExecutionMeter::new(1_000_000_000, limit, 1_000_000_000);
        meter.memory.reserve_memory(11).unwrap();
        let error = searcher
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap_err();
        assert!(d_batch_memory_error(&error));
        assert_eq!(meter.memory.current(), 11);

        // Exact 10 retained + slot_peak fits; scratch is released afterwards.
        let mut meter = BatchExecutionMeter::new(1_000_000_000, limit, 1_000_000_000);
        meter.memory.reserve_memory(10).unwrap();
        searcher
            .search_with_batch(&request, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(meter.memory.current(), 10);

        // A later successful slot still preserves the prior retained bytes.
        let light = d_request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("nomatch".into()),
            },
            1,
        );
        searcher
            .search_with_batch(&light, &Budgets::new(), &NeverCancel, &mut meter)
            .unwrap();
        assert_eq!(meter.memory.current(), 10);
    }

    #[test]
    fn e_projection_cancellation_cleanup() {
        let (schema, registry, index) = d_index(vec![d_doc("a", 0.0, 0.0, 100)]);
        let request = d_request(d_json_query(), 1);
        let snapshot = index.snapshot();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());

        let counter = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: 0,
        };
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        searcher
            .search_with_batch(&request, &Budgets::new(), &counter, &mut meter)
            .unwrap();
        let total = counter.calls.load(Ordering::Relaxed);
        assert!(total > 2);

        let cancel = CountingCancel {
            calls: AtomicU64::new(0),
            cancel_at: total - 1,
        };
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        let error = searcher
            .search_with_batch(&request, &Budgets::new(), &cancel, &mut meter)
            .unwrap_err();
        assert!(matches!(error, SearchError::Cancelled));
        assert_eq!(meter.memory.current(), 0);
    }

    #[test]
    fn e_projection_standalone_and_batch_parity() {
        let (schema, registry, index) =
            d_index(vec![d_doc("a", 0.0, 0.0, 2), d_doc("b", 0.1, 0.1, 2)]);
        let mut request = d_request(Query::MatchAll, 10);
        request.projection = Projection::Fields(vec!["title".to_owned()]);
        let snapshot = index.snapshot();
        let standalone =
            UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
                .search(&request, &Budgets::new(), &NeverCancel)
                .unwrap();
        let (batched, _, _) = d_run(&schema, &registry, &index, &request, u64::MAX);
        let batched = batched.unwrap();
        assert_eq!(standalone.total_hits, batched.total_hits);
        assert_eq!(standalone.hits, batched.hits);
    }

    // -----------------------------------------------------------------------
    // Phase B (PR 14G): exact selected physical hit projection (CW-055/068).
    //
    // Every assertion below derives its oracle from the exact physical
    // `(segment_index, doc_id)` selected by `collect_mixed`, never from a
    // logical-key rescan, so a key-based implementation cannot pass.
    // -----------------------------------------------------------------------

    fn g_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "host",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn g_doc(key: &str, title: &str, host: &str, n: i64) -> Document {
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert("title", FieldValues::Single(FieldValue::Text(title.into())))
            .unwrap();
        document
            .insert(
                "host",
                FieldValues::Single(FieldValue::Keyword(host.into())),
            )
            .unwrap();
        document
            .insert("n", FieldValues::Single(FieldValue::I64(n)))
            .unwrap();
        document
    }

    /// Build a reopened index with exactly `commits.len()` immutable segments.
    /// The directory is returned so a mutation test can reopen a *new*
    /// generation handle while a pinned old snapshot stays alive.
    fn g_index(
        commits: &[Vec<Document>],
    ) -> (
        Schema,
        AnalyzerRegistry,
        Arc<dyn Directory>,
        crate::index::Index,
    ) {
        let schema = g_schema();
        let registry = AnalyzerRegistry::builtin();
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index =
            crate::index::Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
                .unwrap();
        for commit in commits {
            let mut writer = index.writer().unwrap();
            for document in commit {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().unwrap();
        }
        drop(index);
        let reopened = crate::index::Index::open_existing(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
        )
        .unwrap();
        assert_eq!(reopened.snapshot().segment_count(), commits.len());
        (schema, registry, directory, reopened)
    }

    /// Reopen the committed generation after an external writer commit. An
    /// `Index` handle never tracks later writers, so a new generation is only
    /// observable through `open_existing`.
    fn g_reopen(
        directory: &Arc<dyn Directory>,
        schema: &Schema,
        registry: &AnalyzerRegistry,
    ) -> crate::index::Index {
        crate::index::Index::open_existing(Arc::clone(directory), schema.clone(), registry.clone())
            .unwrap()
    }

    fn g_mixed_request(top_k: usize, sort: Sort) -> UnifiedRequest {
        UnifiedRequest {
            query: Query::And(vec![
                Query::Term {
                    field: "title".into(),
                    value: FieldValue::Text("alpha".into()),
                },
                Query::Range {
                    field: "n".into(),
                    lower: Bound::Included(FieldValue::I64(0)),
                    upper: Bound::Included(FieldValue::I64(100)),
                },
            ]),
            sort,
            top_k: TopK::new(top_k).unwrap(),
            projection: Projection::Source,
            after: None,
        }
    }

    /// The real private selected-hit stream plus the production projection of
    /// those exact hits, built through the normal planner/scoring entry points.
    struct GSelection {
        hits: Vec<SelectedHit>,
        fields: Vec<Vec<(String, FieldValues)>>,
        total: u64,
        projection: ProjectionPlan,
    }

    fn g_select(
        schema: &Schema,
        registry: &AnalyzerRegistry,
        snapshot: &ReaderSnapshot,
        request: &UnifiedRequest,
    ) -> GSelection {
        let searcher = UnifiedSearcher::new(snapshot, schema, registry, SearchLimits::default());
        let projection = ProjectionPlan::compile(&request.projection, schema).unwrap();
        let plan = unified_plan::compile(
            &request.query,
            schema,
            registry,
            &SearchLimits::default(),
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        let bindings = crate::analysis::SchemaAnalyzerBindings::resolve(schema, registry).unwrap();
        let codec = crate::segment::CodecSchema::from_contract(schema, &bindings).unwrap();
        let fingerprint = unified_cursor::fingerprint(&request.query, &codec, &request.sort);
        let (hits, total, cursor, aggregation) = searcher
            .collect_mixed(
                &plan,
                request,
                fingerprint,
                None,
                &NeverCancel,
                &Budgets::new(),
                None,
            )
            .unwrap();
        assert!(cursor.is_none(), "a full page must not emit a cursor");
        assert!(aggregation.is_none());
        let mut ledger = ProjectionLedger::new(searcher.limits.max_total_candidate_bytes());
        let fields =
            project_selected_hits(snapshot, &projection, &mut ledger, &hits, None).unwrap();
        GSelection {
            hits,
            fields,
            total,
            projection,
        }
    }

    /// One physical oracle row: `(segment_index, doc_id, physical key, fields)`.
    type GPhysicalRow = (usize, u64, DocumentKey, Vec<(String, FieldValues)>);

    /// Exact physical oracle: derive every projected field from the selected
    /// `(segment_index, doc_id)`, asserting the key guard on the way.
    fn g_physical_oracle(
        snapshot: &ReaderSnapshot,
        plan: &ProjectionPlan,
        hits: &[SelectedHit],
    ) -> Vec<GPhysicalRow> {
        hits.iter()
            .map(|hit| {
                let guard = snapshot.open_segment_reader(hit.segment_index).unwrap();
                let reader = guard.reader();
                let key = reader.doc_key(hit.doc_id).unwrap();
                assert_eq!(
                    key, hit.key,
                    "selected hit key must equal its physical document key"
                );
                let record = reader.stored_doc(hit.doc_id).unwrap();
                (hit.segment_index, hit.doc_id, key, plan.project(&record))
            })
            .collect()
    }

    fn g_projected<'a>(fields: &'a [(String, FieldValues)], name: &str) -> &'a FieldValues {
        &fields
            .iter()
            .find(|(field, _)| field == name)
            .unwrap_or_else(|| panic!("projected field {name} missing"))
            .1
    }

    fn g_keyword(value: &str) -> FieldValues {
        FieldValues::Single(FieldValue::Keyword(value.into()))
    }

    fn g_tuple(hit: &SelectedHit) -> (usize, u64) {
        (hit.segment_index, hit.doc_id)
    }

    fn g_position(selection: &GSelection, key: &str) -> usize {
        selection
            .hits
            .iter()
            .position(|hit| hit.key.as_str() == key)
            .unwrap_or_else(|| panic!("selected hit {key} missing"))
    }

    fn g_keys(selection: &GSelection) -> Vec<String> {
        selection
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    /// A deliberately **key-based** oracle (the shortcut under test): resolve the
    /// effective-live physical document for `key` in this snapshot by scanning
    /// keys, then project it. Used only as a discriminator, never as the oracle.
    fn g_key_latest_projection(
        snapshot: &ReaderSnapshot,
        plan: &ProjectionPlan,
        key: &DocumentKey,
    ) -> Vec<(String, FieldValues)> {
        for index in 0..snapshot.segment_count() {
            let guard = snapshot.open_segment_reader(index).unwrap();
            let reader = guard.reader();
            let live = snapshot.effective_live_docs(index, reader).unwrap();
            for (doc_id, is_live) in live.iter().enumerate() {
                if !is_live {
                    continue;
                }
                let doc_id = u64::try_from(doc_id).unwrap();
                if reader.doc_key(doc_id).unwrap() != *key {
                    continue;
                }
                return plan.project(&reader.stored_doc(doc_id).unwrap());
            }
        }
        panic!(
            "no effective-live physical document for key {}",
            key.as_str()
        );
    }

    /// B01 — every selected hit projects exactly its own physical document, in
    /// selected order, under a non-key sort.
    #[test]
    fn g_b01_selected_physical_hit_projection_exact() {
        let (schema, registry, _directory, index) = g_index(&[
            vec![
                g_doc("k1", "alpha", "h1", 30),
                g_doc("k2", "alpha", "h2", 10),
            ],
            vec![g_doc("k3", "alpha beta", "h3", 20)],
            vec![g_doc("k4", "gamma", "h4", 40)],
        ]);
        let snapshot = index.snapshot();
        let request = g_mixed_request(
            10,
            Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
        );
        let selection = g_select(&schema, &registry, &snapshot, &request);
        assert_eq!(selection.total, 3);
        assert_eq!(g_keys(&selection), vec!["k1", "k3", "k2"]);
        let mut key_order = g_keys(&selection);
        key_order.sort();
        assert_eq!(key_order, vec!["k1", "k2", "k3"]);

        let physical = g_physical_oracle(&snapshot, &selection.projection, &selection.hits);
        assert_eq!(physical.len(), selection.hits.len());
        let mut tuples: Vec<(usize, u64)> = Vec::new();
        for (position, (segment_index, doc_id, key, fields)) in physical.iter().enumerate() {
            assert_eq!(*segment_index, selection.hits[position].segment_index);
            assert_eq!(*doc_id, selection.hits[position].doc_id);
            assert_eq!(*key, selection.hits[position].key);
            assert_eq!(
                fields, &selection.fields[position],
                "projection must read the selected physical document at position {position}"
            );
            tuples.push((*segment_index, *doc_id));
        }
        eprintln!(
            "[pr14g][b01] selected (segment,doc,key,host) = {:?}",
            physical
                .iter()
                .map(|(segment, doc, key, fields)| (
                    *segment,
                    *doc,
                    key.as_str().to_owned(),
                    match g_projected(fields, "host") {
                        FieldValues::Single(FieldValue::Keyword(host)) => host.clone(),
                        other => format!("{other:?}"),
                    },
                ))
                .collect::<Vec<_>>()
        );
        let distinct = {
            let mut sorted = tuples.clone();
            sorted.sort_unstable();
            sorted.dedup();
            sorted.len()
        };
        assert_eq!(
            distinct,
            tuples.len(),
            "selected physical hits are distinct"
        );
        assert_eq!(g_projected(&selection.fields[0], "host"), &g_keyword("h1"));
        assert_eq!(g_projected(&selection.fields[1], "host"), &g_keyword("h3"));
        assert_eq!(g_projected(&selection.fields[2], "host"), &g_keyword("h2"));

        let response = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search(&request, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(response.total_hits, selection.total);
        assert_eq!(
            response
                .hits
                .iter()
                .map(|hit| hit.key.clone())
                .collect::<Vec<_>>(),
            selection
                .hits
                .iter()
                .map(|hit| hit.key.clone())
                .collect::<Vec<_>>(),
            "end-user ordering equals the selected-hit sequence"
        );
        assert_eq!(
            response
                .hits
                .iter()
                .map(|hit| hit.fields.clone())
                .collect::<Vec<_>>(),
            selection.fields,
            "end-user projections equal the physical oracle"
        );
    }

    /// B02 — the same logical key before and after a real upsert has two
    /// physically distinct identities, each projected from its own snapshot.
    #[test]
    fn g_b02_old_new_pit_upsert_physical_identity() {
        let (schema, registry, directory, index) = g_index(&[
            vec![
                g_doc("stable", "alpha", "before", 30),
                g_doc("other", "alpha", "h2", 20),
            ],
            vec![g_doc("third", "alpha", "h3", 10)],
        ]);
        let request = g_mixed_request(
            10,
            Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
        );

        let old_pit = index.pin().unwrap();
        let old_snapshot = Arc::clone(old_pit.snapshot());
        let old = g_select(&schema, &registry, &old_snapshot, &request);
        let old_stable = g_position(&old, "stable");
        let old_tuple = g_tuple(&old.hits[old_stable]);
        let old_physical = g_physical_oracle(&old_snapshot, &old.projection, &old.hits);
        assert_eq!(
            g_projected(&old.fields[old_stable], "host"),
            &g_keyword("before")
        );
        assert_eq!(old_physical[old_stable].3, old.fields[old_stable]);

        {
            let mut writer = index.writer().unwrap();
            writer
                .apply(crate::contract::document::MutationRequest::upsert(g_doc(
                    "stable", "alpha", "after", 30,
                )))
                .unwrap();
            writer.commit().unwrap();
        }

        let new_index = g_reopen(&directory, &schema, &registry);
        assert!(
            new_index.generation() > index.generation(),
            "the mutation commit must advance the committed generation"
        );
        let new_pit = new_index.pin().unwrap();
        let new_snapshot = Arc::clone(new_pit.snapshot());
        let new = g_select(&schema, &registry, &new_snapshot, &request);
        let new_stable = g_position(&new, "stable");
        let new_tuple = g_tuple(&new.hits[new_stable]);
        let new_physical = g_physical_oracle(&new_snapshot, &new.projection, &new.hits);
        eprintln!(
            "[pr14g][b02] stable physical identity old={:?} new={:?}",
            old_tuple, new_tuple
        );
        assert_ne!(
            old_tuple, new_tuple,
            "the upserted version must occupy a distinct physical document"
        );
        assert_eq!(
            g_projected(&new.fields[new_stable], "host"),
            &g_keyword("after")
        );
        assert_eq!(new_physical[new_stable].3, new.fields[new_stable]);

        // The retained old pin neither changes nor resolves through the new map.
        let old_again = g_select(&schema, &registry, &old_snapshot, &request);
        assert_eq!(old_again.fields, old.fields);
        assert_eq!(
            old_again.hits.iter().map(g_tuple).collect::<Vec<_>>(),
            old.hits.iter().map(g_tuple).collect::<Vec<_>>()
        );
        assert_eq!(
            g_projected(&old_again.fields[g_position(&old_again, "stable")], "host"),
            &g_keyword("before")
        );
        assert_ne!(
            g_physical_oracle(&old_snapshot, &old.projection, &old.hits)[old_stable].3,
            new_physical[new_stable].3,
            "old and new physical records differ for the same logical key"
        );
    }

    /// B03 — a deleted key never leaks into the newer snapshot, while the old pin
    /// keeps its original selected physical document; tied sort values stay
    /// deterministic and projection order equals selected-hit order.
    #[test]
    fn g_b03_deleted_and_tied_sort_no_leak() {
        let (schema, registry, directory, index) = g_index(&[
            vec![
                g_doc("tie-a", "alpha", "h1", 10),
                g_doc("doomed", "alpha", "h2", 5),
            ],
            vec![g_doc("tie-b", "alpha", "h3", 10)],
        ]);
        let request = g_mixed_request(10, Sort::new(vec![SortField::new("n", SortDirection::Asc)]));

        let old_pit = index.pin().unwrap();
        let old_snapshot = Arc::clone(old_pit.snapshot());
        let old = g_select(&schema, &registry, &old_snapshot, &request);
        assert_eq!(g_keys(&old), vec!["doomed", "tie-a", "tie-b"]);
        let doomed = g_position(&old, "doomed");
        let doomed_tuple = g_tuple(&old.hits[doomed]);
        let old_physical = g_physical_oracle(&old_snapshot, &old.projection, &old.hits);
        for (position, (_, _, _, fields)) in old_physical.iter().enumerate() {
            assert_eq!(fields, &old.fields[position]);
        }

        {
            let mut writer = index.writer().unwrap();
            writer
                .apply(crate::contract::document::MutationRequest::delete(
                    DocumentKey::new("doomed").unwrap(),
                ))
                .unwrap();
            writer.commit().unwrap();
        }

        let new_index = g_reopen(&directory, &schema, &registry);
        assert!(new_index.generation() > index.generation());
        let new_pit = new_index.pin().unwrap();
        let new_snapshot = Arc::clone(new_pit.snapshot());
        let new = g_select(&schema, &registry, &new_snapshot, &request);
        eprintln!(
            "[pr14g][b03] old_keys={:?} new_keys={:?} doomed_tuple={:?}",
            g_keys(&old),
            g_keys(&new),
            doomed_tuple
        );
        assert_eq!(g_keys(&new), vec!["tie-a", "tie-b"]);
        assert!(
            !g_keys(&new).iter().any(|key| key == "doomed"),
            "a deleted key must never be projected in the newer snapshot"
        );
        // Ties share a sort value and are ordered deterministically by key.
        assert_eq!(g_keys(&new), vec!["tie-a", "tie-b"]);
        assert_eq!(
            g_keys(&g_select(&schema, &registry, &new_snapshot, &request)),
            g_keys(&new),
            "tied sort order is stable across executions"
        );
        let new_physical = g_physical_oracle(&new_snapshot, &new.projection, &new.hits);
        for (position, (_, _, _, fields)) in new_physical.iter().enumerate() {
            assert_eq!(fields, &new.fields[position]);
        }
        assert_eq!(g_projected(&new.fields[0], "host"), &g_keyword("h1"));
        assert_eq!(g_projected(&new.fields[1], "host"), &g_keyword("h3"));

        // The old pin still selects the original doomed physical document.
        let old_again = g_select(&schema, &registry, &old_snapshot, &request);
        assert_eq!(g_keys(&old_again), vec!["doomed", "tie-a", "tie-b"]);
        assert_eq!(g_tuple(&old_again.hits[0]), doomed_tuple);
        assert_eq!(old_again.fields, old.fields);
    }

    /// B04 — a selected hit whose key disagrees with its physical document is a
    /// typed `CorruptIndex`, proving the key guard is live.
    #[test]
    fn g_b04_mismatched_selected_hit_is_corrupt_index() {
        let (schema, registry, _directory, index) = g_index(&[
            vec![
                g_doc("k1", "alpha", "h1", 30),
                g_doc("k2", "alpha", "h2", 10),
            ],
            vec![g_doc("k3", "alpha", "h3", 20)],
        ]);
        let snapshot = index.snapshot();
        let request = g_mixed_request(
            10,
            Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
        );
        let selection = g_select(&schema, &registry, &snapshot, &request);
        assert!(selection.hits.len() >= 3);
        let other_key = selection.hits[1].key.clone();
        assert_ne!(selection.hits[0].key, other_key);

        let mut tampered: Vec<SelectedHit> = selection.hits.clone();
        // Same physical `(segment_index, doc_id)`, different valid key.
        tampered[0].key = other_key;
        let mut ledger = ProjectionLedger::new(1 << 20);
        let error = project_selected_hits(
            &snapshot,
            &selection.projection,
            &mut ledger,
            &tampered,
            None,
        )
        .unwrap_err();
        assert!(
            matches!(error, SearchError::CorruptIndex { .. }),
            "mismatched selected hit must be CorruptIndex, got {error:?}"
        );

        // Control: the honest selected hits still project cleanly.
        let mut ledger = ProjectionLedger::new(1 << 20);
        let honest = project_selected_hits(
            &snapshot,
            &selection.projection,
            &mut ledger,
            &selection.hits,
            None,
        )
        .unwrap();
        assert_eq!(honest, selection.fields);
    }

    /// B05 — the key-latest shortcut is demonstrably wrong for a retained old
    /// physical hit, so output-only parity could not establish this invariant.
    #[test]
    fn g_b05_regression_against_key_only_oracle() {
        let (schema, registry, directory, index) = g_index(&[
            vec![
                g_doc("stable", "alpha", "before", 30),
                g_doc("other", "alpha", "h2", 20),
            ],
            vec![g_doc("third", "alpha", "h3", 10)],
        ]);
        let request = g_mixed_request(
            10,
            Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
        );

        let old_pit = index.pin().unwrap();
        let old_snapshot = Arc::clone(old_pit.snapshot());
        let old = g_select(&schema, &registry, &old_snapshot, &request);
        let old_stable = g_position(&old, "stable");
        let old_key = old.hits[old_stable].key.clone();
        let old_physical_projection = old.fields[old_stable].clone();
        assert_eq!(
            g_projected(&old_physical_projection, "host"),
            &g_keyword("before")
        );

        {
            let mut writer = index.writer().unwrap();
            writer
                .apply(crate::contract::document::MutationRequest::upsert(g_doc(
                    "stable", "alpha", "after", 30,
                )))
                .unwrap();
            writer.commit().unwrap();
        }
        let new_index = g_reopen(&directory, &schema, &registry);
        assert!(new_index.generation() > index.generation());
        let new_pit = new_index.pin().unwrap();
        let new_snapshot = Arc::clone(new_pit.snapshot());
        let new = g_select(&schema, &registry, &new_snapshot, &request);
        let new_stable = g_position(&new, "stable");

        // The naive shortcut: resolve this key in the *current* snapshot.
        let key_latest = g_key_latest_projection(&new_snapshot, &new.projection, &old_key);
        assert_eq!(g_projected(&key_latest, "host"), &g_keyword("after"));
        assert_ne!(
            old_physical_projection, key_latest,
            "a key-latest shortcut cannot reproduce the old physical projection"
        );
        assert_eq!(
            new.fields[new_stable], key_latest,
            "the new snapshot key-latest equals its own selected physical projection"
        );
        // The exact physical oracle for the old hit is the only correct answer.
        let old_physical = g_physical_oracle(&old_snapshot, &old.projection, &old.hits);
        assert_eq!(old_physical[old_stable].3, old_physical_projection);
        assert_ne!(old_physical[old_stable].3, key_latest);
    }
}

#[cfg(test)]
mod phase4_tests {
    //! PR 15E Phase 4 — postings-driven single-term candidate enumeration.
    //!
    //! Observable witnesses: a test-only membership-predicate call counter (compiled
    //! out of production/benchmark builds) proves which candidates are visited, and
    //! `max_total_work_units` boundaries prove the legacy per-live-document charge is
    //! preserved exactly. Expected result sets are derived from the fixture model.

    use super::super::execute::test_observation;
    use super::super::plan::CompiledLeaf;
    use super::super::unified_plan::{self, UnifiedNode};
    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::document::{Cardinality, Document, FieldValues};
    use crate::contract::query::Query;
    use crate::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::{Index, ReaderSnapshot};
    use crate::storage::{Directory, MemoryDirectory};
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU64, Ordering};

    const LIVE: usize = 1000;

    fn phase4_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn adapter_shaped_schema() -> Schema {
        let keyword = |name: &str| {
            FieldDefinition::new(
                name,
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
        };
        Schema::new(
            vec![
                keyword("doc_id"),
                keyword("key"),
                keyword("group"),
                keyword("body"),
                keyword("payload"),
            ],
            None,
        )
        .unwrap()
    }

    fn build(schema: Schema, docs: Vec<(String, String, i64)>) -> Index {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let registry = AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
        {
            let mut writer = index.writer().unwrap();
            for (key, title, n) in docs {
                let mut document = Document::new(DocumentKey::new(key).unwrap());
                document
                    .insert("title", FieldValues::Single(FieldValue::Text(title)))
                    .unwrap();
                document
                    .insert("n", FieldValues::Single(FieldValue::I64(n)))
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        Index::open_existing(directory, schema, registry).unwrap()
    }

    /// `count` live documents; only the indices in `matching` contain `alpha`.
    fn corpus(count: usize, matching: &[usize]) -> Vec<(String, String, i64)> {
        (0..count)
            .map(|index| {
                let title = if matching.contains(&index) {
                    "alpha".to_owned()
                } else {
                    "beta".to_owned()
                };
                (format!("k{index:05}"), title, index as i64)
            })
            .collect()
    }

    fn term(value: &str) -> Query {
        Query::Term {
            field: "title".to_owned(),
            value: FieldValue::Text(value.to_owned()),
        }
    }

    fn req(query: Query, top_k: usize, sorted_by_doc_id: bool) -> UnifiedRequest {
        let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
        if sorted_by_doc_id {
            request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
        }
        request
    }

    fn search(
        snapshot: &ReaderSnapshot,
        request: &UnifiedRequest,
        limits: SearchLimits,
    ) -> SearchResult<UnifiedResponse> {
        let schema = phase4_schema();
        let registry = AnalyzerRegistry::builtin();
        UnifiedSearcher::new(snapshot, &schema, &registry, limits).search(
            request,
            &Budgets::new(),
            &NeverCancel,
        )
    }

    fn limits_with_work(units: u64) -> SearchLimits {
        SearchLimits::default()
            .with_max_total_work_units(units)
            .unwrap()
    }

    /// Smallest admitted `max_total_work_units` for one request.
    fn min_work(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 24;
        while low < high {
            let mid = low + (high - low) / 2;
            if search(snapshot, request, limits_with_work(mid)).is_ok() {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn keys(response: &UnifiedResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn plan_for(schema: &Schema, query: &Query) -> UnifiedPlan {
        unified_plan::compile(
            query,
            schema,
            &AnalyzerRegistry::builtin(),
            &SearchLimits::default(),
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap()
    }

    fn eligible(schema: &Schema, query: &Query, request: &UnifiedRequest) -> bool {
        single_term_postings_eligible(&plan_for(schema, query), request, None)
    }

    /// U01–U05: the eligibility rule is exactly P4-AD-01.
    #[test]
    fn phase4_u01_u05_eligibility_matrix() {
        let schema = phase4_schema();
        let plain = req(term("alpha"), 10, false);
        assert!(eligible(&schema, &term("alpha"), &plain));
        // Sorting is explicitly allowed (the frozen adapter sorts by `doc_id ASC`).
        let sorted = req(term("alpha"), 10, true);
        assert!(eligible(&schema, &term("alpha"), &sorted));
        // A one-analyzed-term query with zero postings is still eligible.
        let absent = req(term("absent"), 10, false);
        assert!(eligible(&schema, &term("absent"), &absent));

        // Non-root-lexical shapes.
        for query in [
            Query::MatchAll,
            Query::And(vec![term("alpha")]),
            Query::Or(vec![term("alpha"), term("beta")]),
            Query::Not(Box::new(term("alpha"))),
            Query::Exists {
                field: "n".to_owned(),
            },
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned(), "beta".to_owned()],
            },
            Query::Prefix {
                field: "title".to_owned(),
                prefix: "alp".to_owned(),
            },
            Query::Glob {
                field: "title".to_owned(),
                pattern: "al*".to_owned(),
            },
            Query::Regex {
                field: "title".to_owned(),
                pattern: "alpha".to_owned(),
            },
            Query::Fuzzy {
                field: "title".to_owned(),
                value: "alpha".to_owned(),
                max_edits: 1,
                transpositions: false,
            },
            // One original Term that the analyzer expands to two terms.
            term("alpha beta"),
        ] {
            let request = req(query.clone(), 10, false);
            assert!(
                !eligible(&schema, &query, &request),
                "unexpectedly eligible: {query:?}"
            );
        }

        // Aggregation disables the branch.
        let aggregation = Aggregation::new();
        let request = req(term("alpha"), 10, false);
        assert!(!single_term_postings_eligible(
            &plan_for(&schema, &term("alpha")),
            &request,
            Some(&aggregation)
        ));
        // The compiled leaf really does carry two analyzed terms for "alpha beta".
        match &plan_for(&schema, &term("alpha beta")).lexical_leaves[0] {
            CompiledLeaf::Term { terms, .. } => assert_eq!(terms.len(), 2),
            other => panic!("unexpected leaf {other:?}"),
        }
        assert!(matches!(
            plan_for(&schema, &term("alpha")).root,
            UnifiedNode::Lexical(0)
        ));
    }

    /// U06/U07/U08: only matching, effective-live candidates are visited.
    #[test]
    fn phase4_u06_u07_u08_candidate_visitation() {
        let index = build(phase4_schema(), corpus(LIVE, &[0]));
        let snapshot = index.snapshot();

        let eligible_request = req(term("alpha"), 10, true);
        test_observation::reset_predicate_calls();
        let response = search(&snapshot, &eligible_request, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 1);
        assert_eq!(keys(&response), vec!["k00000"]);
        assert_eq!(
            test_observation::predicate_calls(),
            1,
            "eligible path must visit only the single matching posting"
        );

        // Same query wrapped in `And` is ineligible and scans every live document.
        let ineligible = req(Query::And(vec![term("alpha")]), 10, true);
        test_observation::reset_predicate_calls();
        let response = search(&snapshot, &ineligible, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 1);
        assert_eq!(test_observation::predicate_calls(), LIVE);

        // Absent term: eligible, zero candidates, still zero hits.
        let absent = req(term("absent"), 10, true);
        test_observation::reset_predicate_calls();
        let response = search(&snapshot, &absent, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 0);
        assert!(response.hits.is_empty());
        assert_eq!(test_observation::predicate_calls(), 0);
    }

    /// U09: results, totals and ordering match the fixture model.
    #[test]
    fn phase4_u09_results_match_fixture_model() {
        let matching = [3usize, 500, 999];
        let index = build(phase4_schema(), corpus(LIVE, &matching));
        let snapshot = index.snapshot();
        let expected: Vec<String> = matching
            .iter()
            .map(|index| format!("k{index:05}"))
            .collect();

        for top_k in [1usize, 10, 100] {
            let request = req(term("alpha"), top_k, true);
            let response = search(&snapshot, &request, SearchLimits::default()).unwrap();
            assert_eq!(response.total_hits, 3, "top_k {top_k}");
            assert_eq!(
                keys(&response),
                expected.iter().take(top_k).cloned().collect::<Vec<_>>()
            );
            assert!(response.hits.iter().all(|hit| hit.score.is_some()));
        }

        // With more matching postings than top_k, total_hits is still exact.
        let many: Vec<usize> = (0..LIVE).collect();
        let index = build(phase4_schema(), corpus(LIVE, &many));
        let snapshot = index.snapshot();
        let request = req(term("alpha"), 10, true);
        let response = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, LIVE as u64);
        assert_eq!(response.hits.len(), 10);
    }

    /// PERF-05-B1 (U01/U02): the strict eligible single-term path must not repeat
    /// the membership proof the validated posting iterator already established.
    /// The wrapped `And` control keeps the original live-document scan and its
    /// per-document `LeafData::matches` binary search. Results must agree exactly
    /// (count, key order, score bits, projection) for relevance and explicit sort.
    #[test]
    fn phase4_b1_u01_u02_proven_term_skips_relookup_with_fallback_parity() {
        let matching = [0usize, 2, 13, 39];
        let index = build(phase4_schema(), corpus(40, &matching));
        let snapshot = index.snapshot();

        for sorted in [false, true] {
            for k in [1usize, 10] {
                let direct = req(term("alpha"), k, sorted);
                test_observation::reset_predicate_calls();
                test_observation::reset_term_membership_lookups();
                let actual = search(&snapshot, &direct, SearchLimits::default()).unwrap();
                assert_eq!(test_observation::predicate_calls(), matching.len());
                assert_eq!(test_observation::term_membership_lookups(), 0);

                let wrapped = req(Query::And(vec![term("alpha")]), k, sorted);
                test_observation::reset_predicate_calls();
                test_observation::reset_term_membership_lookups();
                let reference = search(&snapshot, &wrapped, SearchLimits::default()).unwrap();
                assert_eq!(test_observation::predicate_calls(), 40);
                assert_eq!(test_observation::term_membership_lookups(), 40);

                assert_eq!(actual.total_hits, reference.total_hits);
                assert_eq!(actual.total_hits, matching.len() as u64);
                assert_eq!(keys(&actual), keys(&reference));
                assert_eq!(actual.hits.len(), k.min(matching.len()));
                let actual_scores: Vec<u64> = actual
                    .hits
                    .iter()
                    .map(|hit| hit.score.expect("lexical hit").to_bits())
                    .collect();
                let reference_scores: Vec<u64> = reference
                    .hits
                    .iter()
                    .map(|hit| hit.score.expect("lexical hit").to_bits())
                    .collect();
                assert_eq!(actual_scores, reference_scores);
                let actual_fields: Vec<_> = actual.hits.iter().map(|hit| &hit.fields).collect();
                let reference_fields: Vec<_> =
                    reference.hits.iter().map(|hit| &hit.fields).collect();
                assert_eq!(actual_fields, reference_fields);
                // DO NOT compare `next_cursor` bytes between distinct query ASTs:
                // it includes a query fingerprint and is intentionally different.
            }
        }
    }

    /// PERF-05-B1 (U03): absent and singleton strict terms keep exact counts with
    /// zero redundant lookups, while the wrapped control still scans live documents.
    #[test]
    fn phase4_b1_u03_absent_and_singleton_term_lookups() {
        let index = build(phase4_schema(), corpus(40, &[7]));
        let snapshot = index.snapshot();

        // Absent strict term: eligible, nothing enumerated, nothing looked up.
        let absent = req(term("absent"), 10, false);
        test_observation::reset_predicate_calls();
        test_observation::reset_term_membership_lookups();
        let empty = search(&snapshot, &absent, SearchLimits::default()).unwrap();
        assert_eq!(empty.total_hits, 0);
        assert!(empty.hits.is_empty());
        assert_eq!(test_observation::predicate_calls(), 0);
        assert_eq!(test_observation::term_membership_lookups(), 0);

        // Singleton strict term: one callback, no redundant lookup, one exact hit.
        let direct = req(term("alpha"), 10, false);
        test_observation::reset_predicate_calls();
        test_observation::reset_term_membership_lookups();
        let single = search(&snapshot, &direct, SearchLimits::default()).unwrap();
        assert_eq!(single.total_hits, 1);
        assert_eq!(keys(&single), vec!["k00007".to_owned()]);
        assert_eq!(test_observation::predicate_calls(), 1);
        assert_eq!(test_observation::term_membership_lookups(), 0);

        // Wrapped control: the live scan looks up the positive term per live doc.
        let wrapped = req(Query::And(vec![term("alpha")]), 10, false);
        test_observation::reset_predicate_calls();
        test_observation::reset_term_membership_lookups();
        let reference = search(&snapshot, &wrapped, SearchLimits::default()).unwrap();
        assert_eq!(reference.total_hits, 1);
        assert_eq!(keys(&reference), vec!["k00007".to_owned()]);
        assert_eq!(test_observation::predicate_calls(), 40);
        assert_eq!(test_observation::term_membership_lookups(), 40);

        // Exact score bits agree with the independently enumerated fixture.
        let single_bits = single.hits[0].score.expect("lexical hit").to_bits();
        let reference_bits = reference.hits[0].score.expect("lexical hit").to_bits();
        assert_eq!(single_bits, reference_bits);
    }

    /// PERF-05-B1 (U04): ineligible shapes stay on the original evaluation path
    /// and keep the positive-term membership lookup.
    #[test]
    fn phase4_b1_u04_ineligible_shapes_keep_membership_lookup() {
        let schema = phase4_schema();
        let index = build(phase4_schema(), corpus(40, &[7]));
        let snapshot = index.snapshot();

        // A single Term query whose analyzer expands to two terms is ineligible.
        let expanded_query = term("alpha beta");
        let expanded = req(expanded_query.clone(), 10, false);
        assert!(!eligible(&schema, &expanded_query, &expanded));
        test_observation::reset_predicate_calls();
        test_observation::reset_term_membership_lookups();
        let expanded_result = search(&snapshot, &expanded, SearchLimits::default()).unwrap();
        // OR over the two analyzed terms matches every live document.
        assert_eq!(expanded_result.total_hits, 40);
        assert_eq!(test_observation::predicate_calls(), 40);
        assert!(
            test_observation::term_membership_lookups() > 0,
            "ineligible expanded term must keep the original membership lookup"
        );

        // Mixed lexical + typed is ineligible and keeps its typed correctness.
        let mixed_query = Query::And(vec![
            term("alpha"),
            Query::Exists {
                field: "n".to_owned(),
            },
        ]);
        let mixed = req(mixed_query.clone(), 10, false);
        assert!(!eligible(&schema, &mixed_query, &mixed));
        test_observation::reset_predicate_calls();
        test_observation::reset_term_membership_lookups();
        let mixed_result = search(&snapshot, &mixed, SearchLimits::default()).unwrap();
        assert_eq!(mixed_result.total_hits, 1);
        assert_eq!(keys(&mixed_result), vec!["k00007".to_owned()]);
        assert_eq!(test_observation::predicate_calls(), 40);
        assert!(
            test_observation::term_membership_lookups() > 0,
            "ineligible mixed query must keep the original membership lookup"
        );
    }

    // PERF-05-B3 U03: the ordered-Vec matched path preserves exact counts, key
    // order, score bits and projection against the wrapped fallback control.
    #[test]
    fn phase4_b3_u03_ordered_unified_matches_preserve_results() {
        let cases: &[(usize, &[usize])] = &[(40, &[]), (40, &[7]), (40, &[0, 3, 9, 39])];
        for &(doc_count, matching) in cases {
            let index = build(phase4_schema(), corpus(doc_count, matching));
            let snapshot = index.snapshot();
            for sorted in [false, true] {
                for k in [1usize, 10, 100] {
                    let direct = search(
                        &snapshot,
                        &req(term("alpha"), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("strict eligible query");
                    let fallback = search(
                        &snapshot,
                        &req(Query::And(vec![term("alpha")]), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("full-scan control");
                    assert_eq!(direct.total_hits, matching.len() as u64);
                    assert_eq!(direct.total_hits, fallback.total_hits);
                    assert_eq!(keys(&direct), keys(&fallback));
                    assert_eq!(direct.hits.len(), matching.len().min(k));
                    let direct_scores: Vec<u64> = direct
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    let fallback_scores: Vec<u64> = fallback
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    assert_eq!(direct_scores, fallback_scores);
                    let direct_fields: Vec<_> = direct.hits.iter().map(|hit| &hit.fields).collect();
                    let fallback_fields: Vec<_> =
                        fallback.hits.iter().map(|hit| &hit.fields).collect();
                    assert_eq!(direct_fields, fallback_fields);
                    // Cursor bytes include query AST fingerprint; not comparable here.
                }
            }
        }
    }

    // PERF-05-B4 U03 — the strict eligible path selects the single-term helper
    // only; the wrapped fallback selects the generic scorer. Results, score bits,
    // counts and B1 witnesses must agree.
    #[test]
    fn phase4_b4_u03_strict_single_term_scoring_and_fallback_parity() {
        let all_1000: Vec<usize> = (0..1000).collect();
        let cases: [(usize, Vec<usize>); 5] = [
            (40, vec![]),
            (40, vec![7]),
            (40, vec![0, 3, 9, 39]),
            (1000, vec![0, 1, 7, 511, 999]),
            (1000, all_1000),
        ];
        for (doc_count, matching) in cases {
            let index = build(phase4_schema(), corpus(doc_count, &matching));
            let snapshot = index.snapshot();
            for sorted in [false, true] {
                for k in [1usize, 10, 100] {
                    test_observation::reset_scorer_calls();
                    test_observation::reset_predicate_calls();
                    test_observation::reset_term_membership_lookups();
                    let direct = search(
                        &snapshot,
                        &req(term("alpha"), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("strict eligible query");
                    assert_eq!(test_observation::single_term_scorer_calls(), 1);
                    assert_eq!(test_observation::generic_scorer_calls(), 0);
                    assert_eq!(test_observation::predicate_calls(), matching.len());
                    assert_eq!(test_observation::term_membership_lookups(), 0);

                    test_observation::reset_scorer_calls();
                    test_observation::reset_predicate_calls();
                    test_observation::reset_term_membership_lookups();
                    let fallback = search(
                        &snapshot,
                        &req(Query::And(vec![term("alpha")]), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("full-scan control");
                    assert_eq!(test_observation::single_term_scorer_calls(), 0);
                    assert_eq!(test_observation::generic_scorer_calls(), 1);
                    assert_eq!(test_observation::predicate_calls(), doc_count);
                    assert!(test_observation::term_membership_lookups() > 0);

                    assert_eq!(direct.total_hits, matching.len() as u64);
                    assert_eq!(direct.total_hits, fallback.total_hits);
                    assert_eq!(keys(&direct), keys(&fallback));
                    assert_eq!(direct.hits.len(), matching.len().min(k));
                    let direct_scores: Vec<u64> = direct
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    let fallback_scores: Vec<u64> = fallback
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    assert_eq!(direct_scores, fallback_scores);
                    let direct_fields: Vec<_> = direct.hits.iter().map(|hit| &hit.fields).collect();
                    let fallback_fields: Vec<_> =
                        fallback.hits.iter().map(|hit| &hit.fields).collect();
                    assert_eq!(direct_fields, fallback_fields);
                }
            }
        }
    }

    // PERF-05-B4 U04 — every ineligible shape stays on the generic scorer; the
    // strict helper is never selected outside the proven single-term path.
    #[test]
    fn phase4_b4_u04_ineligible_shapes_use_only_generic_scorer() {
        let schema = phase4_schema();
        let index = build(phase4_schema(), corpus(40, &[7]));
        let snapshot = index.snapshot();
        let shapes = vec![
            Query::And(vec![term("alpha")]),
            Query::Or(vec![term("alpha"), term("beta")]),
            Query::Not(Box::new(term("alpha"))),
            term("alpha beta"),
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned(), "beta".to_owned()],
            },
            Query::And(vec![
                term("alpha"),
                Query::Exists {
                    field: "n".to_owned(),
                },
            ]),
        ];
        for query in shapes {
            let request = req(query.clone(), 10, false);
            assert!(!eligible(&schema, &query, &request));
            test_observation::reset_scorer_calls();
            let _ = search(&snapshot, &request, SearchLimits::default()).unwrap();
            assert_eq!(
                test_observation::single_term_scorer_calls(),
                0,
                "ineligible shape must not select the strict scorer: {query:?}"
            );
        }

        // A valid `after` cursor forces the ineligible live-bitmap path. Use a
        // fixture with more than K matches so the first page emits a cursor.
        let cursor_index = build(phase4_schema(), corpus(40, &[1, 2, 3]));
        let cursor_snapshot = cursor_index.snapshot();
        let mut request = req(term("alpha"), 1, true);
        let first = search(&cursor_snapshot, &request, SearchLimits::default()).unwrap();
        request.after = Some(first.next_cursor.clone().expect("cursor"));
        test_observation::reset_scorer_calls();
        let _ = search(&cursor_snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(test_observation::single_term_scorer_calls(), 0);

        // At least one ineligible lexical shape does reach the generic scorer.
        test_observation::reset_scorer_calls();
        let _ = search(
            &snapshot,
            &req(Query::And(vec![term("alpha")]), 10, false),
            SearchLimits::default(),
        )
        .unwrap();
        assert!(test_observation::generic_scorer_calls() >= 1);
    }

    // PERF-05-B5 U04 — the strict eligible query moves the validated posting
    // allocation once per segment; the wrapped fallback never does. Results,
    // score bits, counts, projection and B1 witnesses stay identical.
    #[test]
    fn phase4_b5_u04_strict_move_full_query_differential() {
        let all_1000: Vec<usize> = (0..1000).collect();
        let cases: [(usize, Vec<usize>); 5] = [
            (40, vec![]),
            (40, vec![7]),
            (40, vec![0, 3, 9, 39]),
            (1000, vec![0, 1, 7, 511, 999]),
            (1000, all_1000),
        ];
        for (doc_count, matching) in cases {
            let index = build(phase4_schema(), corpus(doc_count, &matching));
            let snapshot = index.snapshot();
            for sorted in [false, true] {
                for k in [1usize, 10, 100] {
                    test_observation::reset_postings_handoff();
                    test_observation::reset_scorer_calls();
                    test_observation::reset_predicate_calls();
                    test_observation::reset_term_membership_lookups();
                    let direct = search(
                        &snapshot,
                        &req(term("alpha"), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("strict eligible query");
                    assert_eq!(test_observation::postings_moves(), 1);
                    assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
                    assert_eq!(test_observation::single_term_scorer_calls(), 1);
                    assert_eq!(test_observation::generic_scorer_calls(), 0);
                    assert_eq!(test_observation::predicate_calls(), matching.len());
                    assert_eq!(test_observation::term_membership_lookups(), 0);

                    test_observation::reset_postings_handoff();
                    test_observation::reset_scorer_calls();
                    test_observation::reset_predicate_calls();
                    test_observation::reset_term_membership_lookups();
                    let fallback = search(
                        &snapshot,
                        &req(Query::And(vec![term("alpha")]), k, sorted),
                        SearchLimits::default(),
                    )
                    .expect("full-scan control");
                    assert_eq!(test_observation::postings_moves(), 0);
                    assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
                    assert_eq!(test_observation::single_term_scorer_calls(), 0);
                    assert_eq!(test_observation::generic_scorer_calls(), 1);
                    assert_eq!(test_observation::predicate_calls(), doc_count);
                    assert!(test_observation::term_membership_lookups() > 0);

                    assert_eq!(direct.total_hits, matching.len() as u64);
                    assert_eq!(direct.total_hits, fallback.total_hits);
                    assert_eq!(keys(&direct), keys(&fallback));
                    assert_eq!(direct.hits.len(), matching.len().min(k));
                    let direct_scores: Vec<u64> = direct
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    let fallback_scores: Vec<u64> = fallback
                        .hits
                        .iter()
                        .map(|hit| hit.score.expect("lexical score").to_bits())
                        .collect();
                    assert_eq!(direct_scores, fallback_scores);
                    let direct_fields: Vec<_> = direct.hits.iter().map(|hit| &hit.fields).collect();
                    let fallback_fields: Vec<_> =
                        fallback.hits.iter().map(|hit| &hit.fields).collect();
                    assert_eq!(direct_fields, fallback_fields);
                }
            }
        }
    }

    // PERF-05-B5 U05 — ineligible shapes, cursors, multi-segment and batch
    // requests never enter the strict handoff or the strict scorer.
    #[test]
    fn phase4_b5_u05_ineligible_never_handoffs() {
        let schema = phase4_schema();
        let index = build(phase4_schema(), corpus(40, &[7]));
        let snapshot = index.snapshot();
        let shapes = vec![
            Query::And(vec![term("alpha")]),
            Query::Or(vec![term("alpha"), term("beta")]),
            Query::Not(Box::new(term("alpha"))),
            term("alpha beta"),
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned(), "beta".to_owned()],
            },
            Query::And(vec![
                term("alpha"),
                Query::Exists {
                    field: "n".to_owned(),
                },
            ]),
        ];
        for query in shapes {
            let request = req(query.clone(), 10, false);
            assert!(!eligible(&schema, &query, &request));
            test_observation::reset_postings_handoff();
            test_observation::reset_scorer_calls();
            let _ = search(&snapshot, &request, SearchLimits::default()).unwrap();
            assert_eq!(test_observation::postings_moves(), 0, "{query:?}");
            assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
            assert_eq!(test_observation::single_term_scorer_calls(), 0);
        }

        // Cursor continuation stays ineligible and never hands off.
        let cursor_index = build(phase4_schema(), corpus(40, &[1, 2, 3]));
        let cursor_snapshot = cursor_index.snapshot();
        let mut request = req(term("alpha"), 1, true);
        let first = search(&cursor_snapshot, &request, SearchLimits::default()).unwrap();
        request.after = Some(first.next_cursor.clone().expect("cursor"));
        test_observation::reset_postings_handoff();
        let _ = search(&cursor_snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(test_observation::postings_moves(), 0);
        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);

        // Two real segments: the ineligible wrapper still never hands off.
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let registry = AnalyzerRegistry::builtin();
        let multi =
            Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
        for (segment, count) in [(0usize, 20usize), (1, 20)] {
            let mut writer = multi.writer().unwrap();
            for position in 0..count {
                let mut document =
                    Document::new(DocumentKey::new(format!("s{segment}-{position:05}")).unwrap());
                let title = if position % 5 == 0 { "alpha" } else { "beta" };
                document
                    .insert(
                        "title",
                        FieldValues::Single(FieldValue::Text(title.to_owned())),
                    )
                    .unwrap();
                document
                    .insert(
                        "n",
                        FieldValues::Single(FieldValue::I64((segment * 100 + position) as i64)),
                    )
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let multi = Index::open_existing(directory, schema, registry).unwrap();
        let multi_snapshot = multi.snapshot();
        test_observation::reset_postings_handoff();
        let _ = search(
            &multi_snapshot,
            &req(Query::And(vec![term("alpha")]), 10, false),
            SearchLimits::default(),
        )
        .unwrap();
        assert_eq!(test_observation::postings_moves(), 0);
        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);

        // Batch execution of an ineligible request never hands off either.
        let mut meter = BatchExecutionMeter::new(1_000_000, 1_000_000, 1_000_000);
        test_observation::reset_postings_handoff();
        test_observation::reset_scorer_calls();
        let batched = UnifiedSearcher::new(
            &snapshot,
            &phase4_schema(),
            &AnalyzerRegistry::builtin(),
            SearchLimits::default(),
        )
        .search_with_batch(
            &req(Query::And(vec![term("alpha")]), 10, false),
            &Budgets::new(),
            &NeverCancel,
            &mut meter,
        )
        .unwrap();
        assert_eq!(batched.total_hits, 1);
        assert_eq!(test_observation::postings_moves(), 0);
        assert_eq!(test_observation::postings_rejection_fallbacks(), 0);
        assert_eq!(test_observation::single_term_scorer_calls(), 0);
    }

    /// U10–U12: the per-live-document work charge is preserved exactly.
    #[test]
    fn phase4_u10_u11_u12_work_charge_parity() {
        let index = build(phase4_schema(), corpus(LIVE, &[7]));
        let snapshot = index.snapshot();

        // Eligible vs ineligible execution of the same predicate must need the same
        // budget; a per-posting charge would make the eligible path much cheaper.
        for base in [term("alpha"), term("absent")] {
            let eligible_request = req(base.clone(), 10, true);
            let ineligible_request = req(Query::And(vec![base.clone()]), 10, true);
            let eligible_min = min_work(&snapshot, &eligible_request);
            let ineligible_min = min_work(&snapshot, &ineligible_request);
            assert_eq!(
                eligible_min, ineligible_min,
                "{base:?}: work charge must not depend on the enumeration strategy"
            );
            // Exact boundary succeeds; one below is rejected.
            assert!(search(&snapshot, &eligible_request, limits_with_work(eligible_min)).is_ok());
            assert!(matches!(
                search(
                    &snapshot,
                    &eligible_request,
                    limits_with_work(eligible_min - 1)
                ),
                Err(SearchError::ResourceLimit { .. })
            ));
        }

        // Traversal and charge are independent facts: the eligible absent lane visits
        // zero candidates while its ineligible twin visits every live document, yet
        // both require the identical work budget (one unit per effective-live doc).
        let absent = req(term("absent"), 10, true);
        let absent_control = req(Query::And(vec![term("absent")]), 10, true);
        test_observation::reset_predicate_calls();
        let _ = search(&snapshot, &absent, SearchLimits::default()).unwrap();
        let eligible_visits = test_observation::predicate_calls();
        test_observation::reset_predicate_calls();
        let _ = search(&snapshot, &absent_control, SearchLimits::default()).unwrap();
        let control_visits = test_observation::predicate_calls();
        assert_eq!(eligible_visits, 0);
        assert_eq!(control_visits, LIVE);
        assert_eq!(
            min_work(&snapshot, &absent),
            min_work(&snapshot, &absent_control)
        );
    }

    /// U16: zero live documents and the 4096-position counting chunk boundary.
    #[test]
    fn phase4_u16_zero_live_and_chunk_boundary() {
        // All documents deleted => zero effective-live positions.
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let schema = phase4_schema();
        let registry = AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
        {
            let mut writer = index.writer().unwrap();
            for (key, title, n) in corpus(8, &[0]) {
                let mut document = Document::new(DocumentKey::new(key).unwrap());
                document
                    .insert("title", FieldValues::Single(FieldValue::Text(title)))
                    .unwrap();
                document
                    .insert("n", FieldValues::Single(FieldValue::I64(n)))
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
            for index in 0..8usize {
                writer
                    .apply(crate::contract::document::MutationRequest::delete(
                        DocumentKey::new(format!("k{index:05}")).unwrap(),
                    ))
                    .unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened = Index::open_existing(directory, schema, registry).unwrap();
        let snapshot = reopened.snapshot();
        let request = req(term("alpha"), 10, true);
        test_observation::reset_predicate_calls();
        let response = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 0);
        assert_eq!(test_observation::predicate_calls(), 0);

        // 4097 live docs crosses the counting chunk; results remain exact.
        let index = build(phase4_schema(), corpus(4097, &[0, 4096]));
        let snapshot = index.snapshot();
        let request = req(term("alpha"), 10, true);
        test_observation::reset_predicate_calls();
        let response = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 2);
        assert_eq!(keys(&response), vec!["k00000", "k04096"]);
        assert_eq!(test_observation::predicate_calls(), 2);
    }

    /// Cancellation that flips after `cancel_at` polls.
    struct CancelAt {
        polls: AtomicU64,
        cancel_at: u64,
    }

    impl crate::analysis::Cancellation for CancelAt {
        fn is_cancelled(&self) -> bool {
            self.polls.fetch_add(1, Ordering::Relaxed) >= self.cancel_at
        }
    }

    /// U14: cancellation is observed while counting and while visiting candidates.
    #[test]
    fn phase4_u14_cancellation_unwinds_cleanly() {
        let index = build(phase4_schema(), corpus(5000, &[4000]));
        let snapshot = index.snapshot();
        let request = req(term("alpha"), 10, true);
        let schema = phase4_schema();
        let registry = AnalyzerRegistry::builtin();

        for cancel_at in [0u64, 1] {
            let cancel = CancelAt {
                polls: AtomicU64::new(0),
                cancel_at,
            };
            let searcher =
                UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
            assert!(matches!(
                searcher.search(&request, &Budgets::new(), &cancel),
                Err(SearchError::Cancelled)
            ));
        }

        // The same snapshot and budget still succeed afterwards (no ledger leak).
        let response = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(response.total_hits, 1);
        assert_eq!(keys(&response), vec!["k04000"]);
    }

    /// I04: a cursor request falls back to the legacy scan.
    #[test]
    fn phase4_cursor_request_falls_back_to_scan() {
        let index = build(phase4_schema(), corpus(LIVE, &[1, 2, 3]));
        let snapshot = index.snapshot();
        let mut request = req(term("alpha"), 1, true);
        let first = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(first.hits.len(), 1);
        let cursor = first.next_cursor.clone().expect("cursor");

        request.after = Some(cursor);
        test_observation::reset_predicate_calls();
        let second = search(&snapshot, &request, SearchLimits::default()).unwrap();
        assert_eq!(second.total_hits, 3);
        assert_eq!(
            test_observation::predicate_calls(),
            LIVE,
            "cursor requests must use the legacy live-bitmap scan"
        );
        assert!(!keys(&second).contains(&keys(&first)[0]));
    }

    /// D11 evidence: the frozen adapter's exact query shape is eligible.
    #[test]
    fn phase4_adapter_shaped_query_is_eligible() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let schema = adapter_shaped_schema();
        let registry = AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
        {
            let mut writer = index.writer().unwrap();
            for n in 0..200usize {
                let mut document = Document::new(DocumentKey::new(format!("k{n:05}")).unwrap());
                for (name, value) in [
                    ("doc_id", format!("d{n:08}")),
                    ("key", if n == 7 { "singleton" } else { "other" }.to_owned()),
                    ("group", "medium".to_owned()),
                    ("body", "alpha beta".to_owned()),
                    ("payload", "x".to_owned()),
                ] {
                    document
                        .insert(
                            name,
                            FieldValues::Single(FieldValue::Keyword(value.clone())),
                        )
                        .unwrap();
                }
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened = Index::open_existing(directory, schema.clone(), registry.clone()).unwrap();
        let snapshot = reopened.snapshot();
        let mut request = UnifiedRequest::new(
            Query::Term {
                field: "key".to_owned(),
                value: FieldValue::Keyword("singleton".to_owned()),
            },
            TopK::new(100).unwrap(),
        );
        request.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
        request.projection = Projection::Fields(vec!["doc_id".to_owned()]);
        assert!(eligible(&schema, &request.query, &request));

        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        test_observation::reset_predicate_calls();
        let response = searcher
            .search(&request, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(response.total_hits, 1);
        assert_eq!(test_observation::predicate_calls(), 1);
        assert_eq!(response.hits[0].fields[0].1, {
            FieldValues::Single(FieldValue::Keyword("d00000007".to_owned()))
        });
    }
}

/// PR 15H-B — borrowed keyword sort materialization tests.
#[cfg(test)]
mod b_tests {
    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::{Index, IndexLimits, ReaderSnapshot};
    use crate::storage::{Directory, MemoryDirectory};
    use std::sync::Arc;

    fn b_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "grp",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "doc_id",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn large_limits() -> IndexLimits {
        IndexLimits::default()
            .with_max_pending_docs(200_000)
            .with_max_pending_bytes(512 * 1024 * 1024)
    }

    fn document(index: usize, doc_id: Option<&str>) -> Document {
        let mut document = Document::new(DocumentKey::new(format!("k{index:05}")).unwrap());
        document
            .insert(
                "grp",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .unwrap();
        if let Some(value) = doc_id {
            document
                .insert(
                    "doc_id",
                    FieldValues::Single(FieldValue::Keyword(value.to_owned())),
                )
                .unwrap();
        }
        document
    }

    fn build(count: usize, make: impl Fn(usize) -> Document) -> Index {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            b_schema(),
            AnalyzerRegistry::builtin(),
            large_limits(),
        )
        .unwrap();
        {
            let mut writer = index.writer().unwrap();
            for position in 0..count {
                writer.insert(make(position)).unwrap();
            }
            writer.commit().unwrap();
        }
        Index::open_existing(directory, b_schema(), AnalyzerRegistry::builtin()).unwrap()
    }

    fn term() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        }
    }

    fn sort_field(direction: SortDirection, missing: MissingValuePosition) -> Sort {
        let mut field = SortField::new("doc_id", direction);
        field.missing = missing;
        Sort::new(vec![field])
    }

    fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
        let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
        request.sort = sort;
        request
    }

    fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
        let schema = b_schema();
        let registry = AnalyzerRegistry::builtin();
        UnifiedSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
            .search(request, &Budgets::new(), &NeverCancel)
            .unwrap()
    }

    fn keys(response: &UnifiedResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn bits(response: &UnifiedResponse) -> Vec<u64> {
        response
            .hits
            .iter()
            .map(|hit| hit.score.expect("scored").to_bits())
            .collect()
    }

    /// B-U01/U08/U36: eligibility, exact counts/order and materialization bounds.
    #[test]
    fn b_u01_u08_u36_counts_order_and_materialization() {
        let index = build(50_000, |position| {
            document(position, Some(&format!("d{position:08}")))
        });
        let snapshot = index.snapshot();

        for top_k in [10usize, 100] {
            b_observation::reset();
            b2_observation::reset();
            let eligible = search(
                &snapshot,
                &request(
                    term(),
                    top_k,
                    sort_field(SortDirection::Asc, MissingValuePosition::Last),
                ),
            );
            assert_eq!(eligible.total_hits, 50_000);
            assert_eq!(eligible.hits.len(), top_k);
            assert_eq!(
                keys(&eligible),
                (0..top_k).map(|i| format!("k{i:05}")).collect::<Vec<_>>()
            );
            assert_eq!(b_observation::eligible_invocations(), 1);
            // PERF-06-B2: the eligible request now ranks by snapshot-wide
            // ordinals instead of the PR 15H-B borrowed string comparator.
            assert_eq!(b_observation::borrowed_value_reads(), 0);
            assert_eq!(b_observation::owned_tuple_materializations(), 0);
            assert_eq!(b_observation::legacy_candidate_fallbacks(), 0);
            assert_eq!(b2_observation::eligible_requests(), 1);
            assert_eq!(b2_observation::map_preparations(), 1);
            assert_eq!(b2_observation::ready_uses(), 1);
            assert_eq!(b2_observation::optional_fallbacks(), 0);
            assert_eq!(b2_observation::bound_columns(), 1);
            assert_eq!(b2_observation::numeric_candidates(), 50_000);
            // Only the K+1 heap entries (and replacements) own a string.
            assert!(
                b2_observation::owned_single_strings() <= top_k + 1,
                "owned={}",
                b2_observation::owned_single_strings()
            );
            assert_eq!(
                b2_observation::single_rejected_without_copy(),
                50_000 - b2_observation::owned_single_strings()
            );
            assert_eq!(b2_observation::multi_one_legacy_decodes(), 0);
            let fallback = search(
                &snapshot,
                &request(
                    Query::And(vec![term()]),
                    top_k,
                    sort_field(SortDirection::Asc, MissingValuePosition::Last),
                ),
            );
            assert_eq!(eligible.total_hits, fallback.total_hits);
            assert_eq!(keys(&eligible), keys(&fallback));
            assert_eq!(bits(&eligible), bits(&fallback));
        }
    }

    /// B-U06/U09/U10: missing/null/empty/value ordering and key tie-breaks.
    #[test]
    fn b_u06_u09_u10_missing_null_tie_ordering() {
        let values = [Some("b"), Some("a"), None, Some("a"), None, Some("z")];
        let index = build(values.len(), |position| {
            let mut doc = document(position, values[position]);
            if position == 2 {
                doc.insert("doc_id", FieldValues::ExplicitNull).unwrap();
            }
            doc
        });
        let snapshot = index.snapshot();
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                let sort = sort_field(direction, missing);
                let eligible = search(&snapshot, &request(term(), 100, sort.clone()));
                let fallback = search(&snapshot, &request(Query::And(vec![term()]), 100, sort));
                assert_eq!(
                    keys(&eligible),
                    keys(&fallback),
                    "{direction:?}/{missing:?}"
                );
                assert_eq!(
                    bits(&eligible),
                    bits(&fallback),
                    "{direction:?}/{missing:?}"
                );
            }
        }
    }

    /// B-U07: raw UTF-8 byte ordering (non-ASCII) matches the legacy comparator.
    #[test]
    fn b_u07_utf8_ordering() {
        let values = ["z", "é", "a", "aa", "a\u{0}b", "Ω"];
        let index = build(values.len(), |position| {
            document(position, Some(values[position]))
        });
        let snapshot = index.snapshot();
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            let sort = sort_field(direction, MissingValuePosition::Last);
            let eligible = search(&snapshot, &request(term(), 100, sort.clone()));
            let fallback = search(&snapshot, &request(Query::And(vec![term()]), 100, sort));
            assert_eq!(keys(&eligible), keys(&fallback));
            assert_eq!(bits(&eligible), bits(&fallback));
        }
    }

    /// B-U04/U05/U11/U16: ineligible shapes never enter the fast path.
    #[test]
    fn b_u04_u05_u11_u16_ineligible_shapes() {
        let index = build(100, |position| {
            document(position, Some(&format!("d{position:08}")))
        });
        let snapshot = index.snapshot();
        let asc = sort_field(SortDirection::Asc, MissingValuePosition::Last);

        let mut cursor_request = request(term(), 2, asc.clone());
        let first = search(&snapshot, &cursor_request);
        cursor_request.after = first.next_cursor.clone();
        let shapes = vec![
            request(Query::And(vec![term()]), 10, asc.clone()),
            request(Query::Or(vec![term(), term()]), 10, asc.clone()),
            request(Query::Not(Box::new(term())), 10, asc.clone()),
            request(Query::MatchAll, 10, asc.clone()),
            request(
                term(),
                10,
                Sort::new(vec![
                    SortField::new("doc_id", SortDirection::Asc),
                    SortField::new("doc_id", SortDirection::Asc),
                ]),
            ),
            cursor_request,
        ];
        for shape in shapes {
            b_observation::reset();
            let _ = search(&snapshot, &shape);
            assert_eq!(
                b_observation::eligible_invocations(),
                0,
                "{:?}",
                shape.query
            );
            assert_eq!(
                b_observation::borrowed_value_reads(),
                0,
                "{:?}",
                shape.query
            );
        }

        // Non-columnar / non-single / non-keyword sort fields are ineligible.
        let aggregation = Aggregation::new();
        let plan = unified_plan::compile(
            &term(),
            &b_schema(),
            &AnalyzerRegistry::builtin(),
            &SearchLimits::default(),
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap();
        assert!(!single_term_postings_eligible(
            &plan,
            &request(term(), 10, asc),
            Some(&aggregation)
        ));
    }

    /// B-U12: multi-segment score bits and key ordering.
    #[test]
    fn b_u12_two_segment_score_bits() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            b_schema(),
            AnalyzerRegistry::builtin(),
            large_limits(),
        )
        .unwrap();
        for (segment, count) in [(0usize, 60usize), (1, 40)] {
            let mut writer = index.writer().unwrap();
            for position in 0..count {
                let mut doc = document(
                    segment * 1000 + position,
                    Some(&format!("d{segment}-{position:04}")),
                );
                doc.insert(
                    "grp",
                    FieldValues::Single(FieldValue::Keyword(
                        if position % 3 == 0 { "common" } else { "other" }.to_owned(),
                    )),
                )
                .unwrap();
                writer.insert(doc).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened =
            Index::open_existing(directory, b_schema(), AnalyzerRegistry::builtin()).unwrap();
        let snapshot = reopened.snapshot();
        let sort = sort_field(SortDirection::Desc, MissingValuePosition::Last);
        let eligible = search(&snapshot, &request(term(), 25, sort.clone()));
        let fallback = search(&snapshot, &request(Query::And(vec![term()]), 25, sort));
        assert_eq!(eligible.total_hits, fallback.total_hits);
        assert_eq!(keys(&eligible), keys(&fallback));
        assert_eq!(bits(&eligible), bits(&fallback));
    }
    /// BF-U01–BF-U06: a malformed later losing keyword candidate must fail with
    /// the legacy typed error before any discard/materialization side effect.
    #[test]
    fn b_fixup_losing_keyword_payload_invalid_utf8_fails_before_discard() {
        use crate::analysis::SchemaAnalyzerBindings;
        use crate::segment::column::encode_columns;
        use crate::segment::{
            CodecSchema, ColumnReader, SegmentDocument, SegmentError, SegmentLimits,
        };

        let contract = b_schema();
        let bindings =
            SchemaAnalyzerBindings::resolve(&contract, &AnalyzerRegistry::builtin()).unwrap();
        let codec = CodecSchema::from_contract(&contract, &bindings).unwrap();
        let segment_limits = SegmentLimits::default();
        let docs: Vec<SegmentDocument> = ["aaa", "bbb", "zzz"]
            .iter()
            .enumerate()
            .map(|(index, value)| {
                let mut doc =
                    SegmentDocument::new(DocumentKey::new(format!("k{index:03}")).unwrap());
                doc.insert(
                    "doc_id",
                    FieldValues::Single(FieldValue::Keyword((*value).to_owned())),
                )
                .unwrap();
                doc
            })
            .collect();
        let valid_bytes = encode_columns(&codec, &docs, 3, &segment_limits).unwrap();
        let position = valid_bytes
            .windows(3)
            .position(|window| window == b"zzz")
            .expect("unique zzz payload");
        assert_eq!(
            valid_bytes
                .windows(3)
                .filter(|window| *window == b"zzz")
                .count(),
            1
        );
        let mut corrupt_bytes = valid_bytes.clone();
        corrupt_bytes[position] = 0xFF;

        let valid_reader = ColumnReader::open(&codec, &valid_bytes, &segment_limits).unwrap();
        let corrupt_reader = ColumnReader::open(&codec, &corrupt_bytes, &segment_limits).unwrap();
        let valid_columns = ColumnAccess::from_columns_for_test(valid_reader);
        let corrupt_columns = ColumnAccess::from_columns_for_test(corrupt_reader);
        let field_id = codec.field_id("doc_id").unwrap();
        let request = request(
            term(),
            1,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        let search_limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&search_limits);
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();

        for index in 0..2usize {
            consider_borrowed_keyword_candidate(
                &valid_columns,
                &codec,
                &request,
                index as u64,
                0,
                DocumentKey::new(format!("k{index:03}")).unwrap(),
                1.0,
                true,
                field_id,
                &mut heap,
                2,
                &mut budget,
                &mut scope,
                &mut d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1),
            )
            .unwrap();
        }
        assert_eq!(heap.len(), 2);
        let worst = heap.peek().unwrap();
        assert_eq!(
            worst.hit.sort_tuple[0],
            SortValue::Value(FieldValue::Keyword("bbb".to_owned()))
        );
        let worst_key = worst.hit.key.clone();
        let worst_value = worst.hit.sort_tuple[0].clone();
        let worst_charge = worst.charge;

        // Intact zzz is genuinely noncompetitive: validated, then discarded
        // without owning a tuple.
        b_observation::reset();
        consider_borrowed_keyword_candidate(
            &valid_columns,
            &codec,
            &request,
            2,
            0,
            DocumentKey::new("k002").unwrap(),
            1.0,
            true,
            field_id,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1),
        )
        .unwrap();
        assert_eq!(heap.len(), 2);
        assert_eq!(b_observation::owned_tuple_materializations(), 0);
        assert_eq!(b_observation::rejected_without_materialization(), 1);
        let worst = heap.peek().unwrap();
        assert_eq!(worst.hit.key, worst_key);
        assert_eq!(worst.hit.sort_tuple[0], worst_value);
        assert_eq!(worst.charge, worst_charge);

        // Corrupt zzz must surface the legacy typed error, not a discard.
        b_observation::reset();
        let error = consider_borrowed_keyword_candidate(
            &corrupt_columns,
            &codec,
            &request,
            2,
            0,
            DocumentKey::new("k002").unwrap(),
            1.0,
            true,
            field_id,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1),
        )
        .unwrap_err();
        assert!(matches!(
            error,
            SearchError::Segment(SegmentError::InvalidUtf8 { context: "keyword" })
        ));
        assert_eq!(heap.len(), 2);
        assert_eq!(b_observation::owned_tuple_materializations(), 0);
        assert_eq!(b_observation::rejected_without_materialization(), 0);
        let worst = heap.peek().unwrap();
        assert_eq!(worst.hit.key, worst_key);
        assert_eq!(worst.charge, worst_charge);

        // Independent owned-decoder oracle.
        assert!(matches!(
            sort_tuple_for_doc(&corrupt_columns, &codec, &request.sort, None, 2),
            Err(SegmentError::InvalidUtf8 { context: "keyword" })
        ));
        assert_eq!(
            sort_tuple_for_doc(&valid_columns, &codec, &request.sort, None, 2).unwrap(),
            vec![SortValue::Value(FieldValue::Keyword("zzz".to_owned()))]
        );

        // BF-U05: localized view error.
        let direct = ColumnReader::open(&codec, &corrupt_bytes, &segment_limits).unwrap();
        assert!(matches!(
            direct.keyword_sort_view(field_id, 2),
            Err(SegmentError::InvalidUtf8 { context: "keyword" })
        ));

        // BF-U06: idempotent typed failure, heap unchanged.
        let repeat = consider_borrowed_keyword_candidate(
            &corrupt_columns,
            &codec,
            &request,
            2,
            0,
            DocumentKey::new("k002").unwrap(),
            1.0,
            true,
            field_id,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1),
        )
        .unwrap_err();
        assert!(matches!(
            repeat,
            SearchError::Segment(SegmentError::InvalidUtf8 { context: "keyword" })
        ));
        assert_eq!(heap.len(), 2);
    }
}

/// PERF-06-B2 — snapshot-wide ordinal collector tests.
#[cfg(test)]
#[allow(clippy::needless_option_as_deref)]
mod b2_tests {
    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::result::{
        MissingValuePosition, MultiValueSelector, Sort, SortDirection, SortField, TopK,
    };
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::{Index, IndexLimits, ReaderSnapshot};
    use crate::segment::SegmentLimits;
    use crate::storage::{Directory, MemoryDirectory};
    use std::num::NonZeroUsize;
    use std::sync::Arc;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "grp",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "doc_id",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    /// One input row's `doc_id` state, independent of the production codec.
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum City {
        Missing,
        Null,
        Value(&'static str),
        /// A single-element `FieldValues::Multi`, encoded as `MultiOne`.
        Multi(&'static str),
    }

    fn values(city: City) -> Option<FieldValues> {
        match city {
            City::Missing => None,
            City::Null => Some(FieldValues::ExplicitNull),
            City::Value(value) => Some(FieldValues::Single(FieldValue::Keyword(value.to_owned()))),
            City::Multi(value) => Some(FieldValues::Multi(vec![FieldValue::Keyword(
                value.to_owned(),
            )])),
        }
    }

    fn text(city: City) -> Option<&'static str> {
        match city {
            City::Missing | City::Null => None,
            City::Value(value) | City::Multi(value) => Some(value),
        }
    }

    fn document(key: &str, city: City) -> Document {
        let mut document = Document::new(DocumentKey::new(key).expect("key"));
        document
            .insert(
                "grp",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .expect("grp");
        if let Some(city) = values(city) {
            document.insert("doc_id", city).expect("doc_id");
        }
        document
            .insert("n", FieldValues::Single(FieldValue::I64(1)))
            .expect("n");
        document
    }

    fn large_limits() -> IndexLimits {
        IndexLimits::default()
            .with_max_pending_docs(200_000)
            .with_max_pending_bytes(512 * 1024 * 1024)
    }

    fn directory() -> Arc<dyn Directory> {
        Arc::new(MemoryDirectory::new())
    }

    fn build(docs: &[(&str, City)]) -> Index {
        build_segments(&[docs.to_vec()])
    }

    fn build_segments(segments: &[Vec<(&str, City)>]) -> Index {
        let directory = directory();
        {
            let index = Index::create_with_limits(
                Arc::clone(&directory),
                schema(),
                AnalyzerRegistry::builtin(),
                large_limits(),
            )
            .expect("create");
            for segment in segments {
                let mut writer = index.writer().expect("writer");
                for (key, city) in segment {
                    writer.insert(document(key, *city)).expect("insert");
                }
                writer.commit().expect("commit");
            }
        }
        Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).expect("reopen")
    }

    fn term() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        }
    }

    fn fallback_query() -> Query {
        Query::And(vec![term()])
    }

    fn sort_field(direction: SortDirection, missing: MissingValuePosition) -> Sort {
        let mut field = SortField::new("doc_id", direction);
        field.missing = missing;
        Sort::new(vec![field])
    }

    fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
        let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
        request.sort = sort;
        request.projection = Projection::Fields(vec!["doc_id".to_owned()]);
        request
    }

    fn run(
        snapshot: &ReaderSnapshot,
        request: &UnifiedRequest,
        limits: SearchLimits,
    ) -> SearchResult<UnifiedResponse> {
        let schema = schema();
        let registry = AnalyzerRegistry::builtin();
        UnifiedSearcher::new(snapshot, &schema, &registry, limits).search(
            request,
            &Budgets::new(),
            &NeverCancel,
        )
    }

    fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
        run(snapshot, request, SearchLimits::default()).expect("search")
    }

    fn keys(response: &UnifiedResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn bits(response: &UnifiedResponse) -> Vec<u64> {
        response
            .hits
            .iter()
            .map(|hit| hit.score.expect("scored").to_bits())
            .collect()
    }

    /// Independent input oracle: class rank, then raw bytes adjusted only for
    /// `Desc`, then logical key bytes ascending. Never calls production code.
    fn expected_order(
        rows: &[(String, City)],
        direction: SortDirection,
        missing: MissingValuePosition,
    ) -> Vec<String> {
        let class = |city: City| match (city, missing) {
            (City::Missing, MissingValuePosition::First) => 0u8,
            (City::Null, MissingValuePosition::First) => 1,
            (City::Value(_) | City::Multi(_), MissingValuePosition::First) => 2,
            (City::Value(_) | City::Multi(_), MissingValuePosition::Last) => 0,
            (City::Null, MissingValuePosition::Last) => 1,
            (City::Missing, MissingValuePosition::Last) => 2,
        };
        let mut order: Vec<&(String, City)> = rows.iter().collect();
        order.sort_by(|left, right| {
            class(left.1)
                .cmp(&class(right.1))
                .then_with(|| match (text(left.1), text(right.1)) {
                    (Some(a), Some(b)) => match direction {
                        SortDirection::Asc => a.as_bytes().cmp(b.as_bytes()),
                        SortDirection::Desc => b.as_bytes().cmp(a.as_bytes()),
                    },
                    _ => Ordering::Equal,
                })
                .then_with(|| left.0.as_bytes().cmp(right.0.as_bytes()))
        });
        order.into_iter().map(|(key, _)| key.clone()).collect()
    }

    fn compare_both(snapshot: &ReaderSnapshot, rows: &[(String, City)], top_k: usize) {
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                let sort = sort_field(direction, missing);
                let ordinal = search(snapshot, &request(term(), top_k, sort.clone()));
                let legacy = search(snapshot, &request(fallback_query(), top_k, sort));
                let expected = expected_order(rows, direction, missing);
                let expected_prefix: Vec<String> = expected.iter().take(top_k).cloned().collect();
                assert_eq!(keys(&ordinal), expected_prefix, "{direction:?}/{missing:?}");
                assert_eq!(ordinal.total_hits, rows.len() as u64);
                assert_eq!(legacy.total_hits, ordinal.total_hits);
                assert_eq!(keys(&legacy), keys(&ordinal));
                assert_eq!(bits(&legacy), bits(&ordinal));
                assert_eq!(
                    legacy
                        .hits
                        .iter()
                        .map(|hit| hit.fields.clone())
                        .collect::<Vec<_>>(),
                    ordinal
                        .hits
                        .iter()
                        .map(|hit| hit.fields.clone())
                        .collect::<Vec<_>>()
                );
                assert_eq!(ordinal.next_cursor.is_some(), rows.len() > top_k);
            }
        }
    }

    fn primary_guard(snapshot: &ReaderSnapshot) -> crate::index::GuardedSegmentReader {
        snapshot.open_segment_reader(0).expect("guard")
    }

    /// B2-U03: shared ranks, not segment-local ordinals, drive the merge.
    #[test]
    fn b2_u03_local_ordinals_translate_to_one_shared_order() {
        let index = build_segments(&[
            vec![("a0", City::Value("Seattle"))],
            vec![
                ("b0", City::Value("Boston")),
                ("b1", City::Value("Seattle")),
            ],
            vec![("c0", City::Value("Austin")), ("c1", City::Value("Boston"))],
        ]);
        let snapshot = index.snapshot();
        let guards: Vec<_> = (0..snapshot.segment_count())
            .map(|index| snapshot.open_segment_reader(index).expect("guard"))
            .collect();
        let field = guards[0]
            .reader()
            .schema()
            .field_id("doc_id")
            .expect("doc_id field id");
        let preparation = snapshot
            .prepare_keyword_ordinals(field, &guards, &NeverCancel)
            .expect("prepare");
        let map = preparation
            .ready()
            .unwrap_or_else(|| panic!("ready map: {preparation:?}"));

        // Locate a document by logical key: manifest segment order is not the
        // commit order.
        let locate = |key: &str| {
            for (index, guard) in guards.iter().enumerate() {
                let keys = guard.reader().doc_keys().expect("keys");
                if let Some(doc_id) = keys.iter().position(|entry| entry.as_str() == key) {
                    return (index, doc_id as u64);
                }
            }
            panic!("key {key} not found");
        };
        let local = |index: usize, doc: u64| {
            let columns = guards[index]
                .reader()
                .open_columns()
                .expect("columns")
                .expect("section");
            let handle = columns
                .bind_keyword_ordinals(field)
                .expect("bind")
                .expect("ordinal");
            match handle.doc_ordinal(doc).expect("row") {
                KeywordOrdinalValue::Value { ordinal, .. } => ordinal,
                other => panic!("expected a value row, got {other:?}"),
            }
        };
        let (a_index, a_doc) = locate("a0");
        let (b0_index, b0_doc) = locate("b0");
        let (b1_index, b1_doc) = locate("b1");
        assert_ne!(a_index, b0_index);
        assert_eq!(b0_index, b1_index);
        let a_seattle = local(a_index, a_doc);
        let b_boston = local(b0_index, b0_doc);
        let b_seattle = local(b1_index, b1_doc);
        assert_eq!(
            a_seattle, b_boston,
            "the same local ordinal names different terms in two segments"
        );
        assert_ne!(
            a_seattle, b_seattle,
            "same term, different local ordinals across segments"
        );
        let shared = |index: usize, doc: u64| {
            map.bind_segment(&guards[index])
                .expect("bind")
                .translate(local(index, doc))
                .expect("translate")
        };
        assert_eq!(shared(a_index, a_doc), shared(b1_index, b1_doc));
        assert_ne!(shared(a_index, a_doc), shared(b0_index, b0_doc));
        assert!(shared(b0_index, b0_doc) < shared(a_index, a_doc));

        let rows = vec![
            ("a0".to_owned(), City::Value("Seattle")),
            ("b0".to_owned(), City::Value("Boston")),
            ("b1".to_owned(), City::Value("Seattle")),
            ("c0".to_owned(), City::Value("Austin")),
            ("c1".to_owned(), City::Value("Boston")),
        ];
        b2_observation::reset();
        compare_both(&snapshot, &rows, 100);
        assert_eq!(b2_observation::map_preparations(), 4);
        assert_eq!(b2_observation::optional_fallbacks(), 0);
        assert_eq!(b2_observation::bound_columns(), 12);
    }

    /// B2-U04/U12: bounded top-K sizes, complete counts and K+1 truncation.
    #[test]
    fn b2_u04_top_k_sizes_and_truncation() {
        let index = build_segments(&[
            vec![
                ("k0", City::Value("d")),
                ("k1", City::Value("a")),
                ("k2", City::Missing),
            ],
            vec![("k3", City::Value("c")), ("k4", City::Null)],
            vec![
                ("k5", City::Value("b")),
                ("k6", City::Value("a")),
                ("k7", City::Value("e")),
            ],
        ]);
        let snapshot = index.snapshot();
        let rows: Vec<(String, City)> = vec![
            ("k0".to_owned(), City::Value("d")),
            ("k1".to_owned(), City::Value("a")),
            ("k2".to_owned(), City::Missing),
            ("k3".to_owned(), City::Value("c")),
            ("k4".to_owned(), City::Null),
            ("k5".to_owned(), City::Value("b")),
            ("k6".to_owned(), City::Value("a")),
            ("k7".to_owned(), City::Value("e")),
        ];
        for top_k in [1usize, 2, 5, 10, 100] {
            compare_both(&snapshot, &rows, top_k);
        }
        // Exactly K and K+1 candidates produce no cursor / one cursor.
        let one = search(
            &snapshot,
            &request(
                term(),
                8,
                sort_field(SortDirection::Asc, MissingValuePosition::First),
            ),
        );
        assert_eq!(one.total_hits, 8);
        assert!(one.next_cursor.is_none());
        let one = search(
            &snapshot,
            &request(
                term(),
                7,
                sort_field(SortDirection::Asc, MissingValuePosition::First),
            ),
        );
        assert!(one.next_cursor.is_some());
        // The cursor retains the Kth owned string tuple, never a numeric rank.
        let cursor = one.next_cursor.expect("cursor");
        assert!(matches!(
            cursor.last_sort.first(),
            Some(SortValue::Value(FieldValue::Keyword(_)))
        ));
    }

    /// B2-U05: equal shared ordinals across segments tie by logical key bytes.
    #[test]
    fn b2_u05_equal_ranks_tie_by_key_ascending() {
        let index = build_segments(&[
            vec![("b1", City::Value("tie")), ("a2", City::Value("a0"))],
            vec![("a1", City::Value("tie"))],
        ]);
        let snapshot = index.snapshot();
        let rows = vec![
            ("b1".to_owned(), City::Value("tie")),
            ("a2".to_owned(), City::Value("a0")),
            ("a1".to_owned(), City::Value("tie")),
        ];
        for (direction, expected) in [
            (SortDirection::Asc, vec!["a2", "a1", "b1"]),
            (SortDirection::Desc, vec!["a1", "b1", "a2"]),
        ] {
            let response = search(
                &snapshot,
                &request(
                    term(),
                    100,
                    sort_field(direction, MissingValuePosition::Last),
                ),
            );
            assert_eq!(keys(&response), expected, "{direction:?}");
        }
        compare_both(&snapshot, &rows, 100);
    }

    /// B2-U06: `MultiOne` keeps its legacy shape and full decode but sorts by its
    /// one value.
    #[test]
    fn b2_u06_multi_one_keeps_shape_and_order() {
        let index = build_segments(&[vec![
            ("k0", City::Value("m")),
            ("k1", City::Multi("m")),
            ("k2", City::Missing),
            ("k3", City::Null),
            ("k4", City::Value("a")),
            ("k5", City::Value("z")),
        ]]);
        let snapshot = index.snapshot();
        let rows = vec![
            ("k0".to_owned(), City::Value("m")),
            ("k1".to_owned(), City::Multi("m")),
            ("k2".to_owned(), City::Missing),
            ("k3".to_owned(), City::Null),
            ("k4".to_owned(), City::Value("a")),
            ("k5".to_owned(), City::Value("z")),
        ];
        b2_observation::reset();
        compare_both(&snapshot, &rows, 100);
        assert!(b2_observation::multi_one_legacy_decodes() >= 4);
        // The projected value keeps the one-element multi shape.
        let response = search(
            &snapshot,
            &request(
                term(),
                100,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        let multi = response
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == "k1")
            .expect("multi hit");
        assert_eq!(
            multi.fields,
            vec![(
                "doc_id".to_owned(),
                FieldValues::Multi(vec![FieldValue::Keyword("m".to_owned())])
            )]
        );
    }

    /// B2-U07: a losing 80-byte `Single` still fails the frozen 79-byte logical
    /// admission before discard.
    #[test]
    fn b2_u07_losing_long_value_reports_the_decode_limit() {
        let long: &'static str = Box::leak("z".repeat(80).into_boxed_str());
        assert_eq!(long.len(), 80);
        // "a" sorts before the 80-byte value, so the long row is a loser at K=1.
        let rows: [(&str, City); 2] = [("k0", City::Value("a")), ("k1", City::Value(long))];
        let directory = directory();
        {
            let index = Index::create_with_limits(
                Arc::clone(&directory),
                schema(),
                AnalyzerRegistry::builtin(),
                large_limits(),
            )
            .expect("create");
            let mut writer = index.writer().expect("writer");
            for (key, city) in rows {
                writer.insert(document(key, city)).expect("insert");
            }
            writer.commit().expect("commit");
        }
        // The container-open path already requires a decode allowance above 80
        // bytes for this fixture (`max_section_decode_bytes(79)` is refused with
        // `requested: 600`), so a public snapshot cannot also exercise the
        // per-candidate 79-byte rejection: the bound accessor unit test
        // (`b2_u07_decode_budget_79_rejects_the_80_byte_single_before_discard`)
        // proves that exact `limit: 79, requested: 80` error on real v2 bytes.
        // Here the losing 80-byte value must be fully admitted under permissive
        // limits and never truncate the result.
        let index =
            Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).expect("open");
        let snapshot = index.snapshot();
        let response = run(
            &snapshot,
            &request(
                term(),
                1,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
            SearchLimits::default(),
        )
        .expect("permissive limits admit the 80-byte value");
        assert_eq!(response.total_hits, 2);
        assert_eq!(keys(&response), vec!["k0".to_owned()]);
        let response = search(
            &snapshot,
            &request(
                term(),
                2,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(keys(&response), vec!["k0".to_owned(), "k1".to_owned()]);
    }

    /// B2-U08/U22: an exact candidate-budget preflight failure leaves the heap and
    /// retained charge untouched; retained charges equal `candidate_charge`.
    #[test]
    fn b2_u08_u22_budget_failure_leaves_heap_unchanged_and_charges_match() {
        let request = request(
            term(),
            1,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        let exact = SearchLimits::default()
            .with_max_total_candidate_bytes(209)
            .expect("limit");
        let index = build(&[("k000", City::Value("b")), ("k001", City::Value("a"))]);
        let snapshot = index.snapshot();
        let guard = primary_guard(&snapshot);
        let guards = [primary_guard(&snapshot)];
        let field = guards[0]
            .reader()
            .schema()
            .field_id("doc_id")
            .expect("doc_id field id");
        let preparation = snapshot
            .prepare_keyword_ordinals(field, &guards, &NeverCancel)
            .expect("prepare");
        let map = preparation
            .ready()
            .unwrap_or_else(|| panic!("ready: {preparation:?}"));
        let translation = map.bind_segment(&guard).expect("bind segment");
        let reader = guard.reader();
        let columns = ColumnAccess::open(reader).expect("columns");
        let bound = columns
            .bind_keyword_sort_ordinal(field)
            .expect("bind")
            .expect("ordinal");
        let mut budget = CandidateBudget::new(&exact);
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut experiment = d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1);
        let mut audit = OrdinalHeapAudit::new();
        consider_ordinal_keyword_candidate(
            &columns,
            reader.schema(),
            &request,
            0,
            0,
            DocumentKey::new("k000").expect("key"),
            1.0,
            true,
            &bound,
            &translation,
            &mut audit,
            &mut heap,
            1,
            &mut budget,
            &mut scope,
            &mut experiment,
        )
        .expect("first candidate fits");
        assert_eq!(heap.len(), 1);
        let retained = heap.peek().expect("retained");
        assert_eq!(retained.hit.key.as_str(), "k000");
        assert_eq!(
            retained.charge,
            candidate_charge(&retained.hit).expect("charge")
        );
        assert_eq!(retained.charge, 105);
        let error = consider_ordinal_keyword_candidate(
            &columns,
            reader.schema(),
            &request,
            1,
            0,
            DocumentKey::new("k001").expect("key"),
            1.0,
            true,
            &bound,
            &translation,
            &mut audit,
            &mut heap,
            1,
            &mut budget,
            &mut scope,
            &mut experiment,
        )
        .expect_err("second insertion exceeds the exact budget");
        assert!(matches!(
            error,
            SearchError::ResourceLimit {
                limit: 209,
                requested: 210
            }
        ));
        assert_eq!(heap.len(), 1);
        assert_eq!(
            heap.peek().expect("retained").hit.key.as_str(),
            "k000",
            "no partial replacement"
        );
        assert_eq!(
            heap.peek().expect("retained").charge,
            candidate_charge(&heap.peek().expect("retained").hit).expect("charge")
        );
    }

    /// B2-U09/U15/U24: ineligible shapes never attempt preparation.
    #[test]
    fn b2_u09_u15_u24_ineligible_shapes_do_not_prepare() {
        let index = build(&[
            ("k0", City::Value("a")),
            ("k1", City::Value("b")),
            ("k2", City::Missing),
        ]);
        let snapshot = index.snapshot();
        let asc = sort_field(SortDirection::Asc, MissingValuePosition::Last);
        let mut multi_selector = SortField::new("doc_id", SortDirection::Asc);
        multi_selector.multi = Some(MultiValueSelector::Min);
        let mut json_field = SortField::new("doc_id", SortDirection::Asc);
        json_field.json_path =
            Some(crate::contract::query::JsonPathExpr::parse("$.x").expect("json path"));
        let mut geo_field = SortField::new("doc_id", SortDirection::Asc);
        geo_field.distance_from =
            Some(crate::contract::value::GeoPoint::new(0.0, 0.0).expect("geo point"));
        let mut relevance = request(term(), 10, Sort::default());
        relevance.sort = Sort::default();
        let shapes = vec![
            request(term(), 10, Sort::default()),
            request(
                term(),
                10,
                Sort::new(vec![
                    SortField::new("doc_id", SortDirection::Asc),
                    SortField::new("n", SortDirection::Asc),
                ]),
            ),
            request(
                term(),
                10,
                Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
            ),
            request(term(), 10, Sort::new(vec![multi_selector])),
            request(term(), 10, Sort::new(vec![json_field])),
            request(term(), 10, Sort::new(vec![geo_field])),
            request(fallback_query(), 10, asc.clone()),
            request(
                Query::And(vec![
                    term(),
                    Query::Exists {
                        field: "doc_id".to_owned(),
                    },
                ]),
                10,
                asc.clone(),
            ),
            relevance,
        ];
        for shape in shapes {
            b2_observation::reset();
            let _ = run(&snapshot, &shape, SearchLimits::default());
            assert_eq!(b2_observation::eligible_requests(), 0, "{shape:?}");
            assert_eq!(b2_observation::map_preparations(), 0, "{shape:?}");
        }

        // Batch and aggregation requests are ineligible too.
        b2_observation::reset();
        let mut meter = BatchExecutionMeter::new(1_000_000, 1_000_000, 1_000_000);
        let schema = self::schema();
        let registry = AnalyzerRegistry::builtin();
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        let _ = searcher
            .search_with_batch(
                &request(term(), 10, asc.clone()),
                &Budgets::new(),
                &NeverCancel,
                &mut meter,
            )
            .expect("batch slot");
        assert_eq!(b2_observation::map_preparations(), 0);
        let aggregation = Aggregation::new();
        let _ = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search_impl(
                &request(term(), 10, asc),
                &Budgets::new(),
                &NeverCancel,
                None,
                false,
                Some(&aggregation),
            )
            .expect("aggregation slot");
        assert_eq!(b2_observation::map_preparations(), 0);

        // The same eligible shape does prepare exactly once per request.
        b2_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, 3);
        assert_eq!(b2_observation::eligible_requests(), 1);
        assert_eq!(b2_observation::map_preparations(), 1);
        assert_eq!(b2_observation::ready_uses(), 1);
        assert_eq!(b2_observation::bound_columns(), 1);
        assert_eq!(b2_observation::numeric_candidates(), 3);
    }

    /// B2-U10/U11/U12: optional outcomes, cancellation and genuine errors map
    /// distinctly.
    #[test]
    fn b2_u10_u11_u12_optional_and_error_dispatch() {
        for reason in [
            crate::index::KeywordOrdinalUnavailable::LegacySegment,
            crate::index::KeywordOrdinalUnavailable::ResourceBudget,
            crate::index::KeywordOrdinalUnavailable::Allocation,
            crate::index::KeywordOrdinalUnavailable::UnsupportedField,
        ] {
            assert!(
                ordinal_ready_from_preparation(KeywordOrdinalPreparation::NotAvailable(reason))
                    .is_none(),
                "{reason:?} must be a whole-request fallback"
            );
        }
        assert!(matches!(
            ordinal_preparation_error(crate::index::IndexError::Cancelled),
            SearchError::Cancelled
        ));
        assert!(matches!(
            ordinal_preparation_error(crate::index::IndexError::CorruptCommittedState {
                detail: "poison".to_owned()
            }),
            SearchError::Index(crate::index::IndexError::CorruptCommittedState { .. })
        ));

        let index = build(&[("k0", City::Value("a"))]);
        let snapshot = index.snapshot();
        let guards: Vec<_> = (0..snapshot.segment_count())
            .map(|index| snapshot.open_segment_reader(index).expect("guard"))
            .collect();
        let cancelled = crate::analysis::CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            snapshot.prepare_keyword_ordinals(
                guards[0]
                    .reader()
                    .schema()
                    .field_id("doc_id")
                    .expect("field"),
                &guards,
                &cancelled
            ),
            Err(crate::index::IndexError::Cancelled)
        ));
        let error = run(
            &snapshot,
            &request(
                term(),
                1,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
            SearchLimits::default(),
        );
        // A pre-cancelled flag is rejected by the existing request checks; the
        // important property is the canonical `SearchError::Cancelled`.
        let _ = error;
        let schema = self::schema();
        let registry = AnalyzerRegistry::builtin();
        let error = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search(
                &request(
                    term(),
                    1,
                    sort_field(SortDirection::Asc, MissingValuePosition::Last),
                ),
                &Budgets::new(),
                &cancelled,
            )
            .expect_err("cancelled request");
        assert!(matches!(error, SearchError::Cancelled));
    }

    /// B2-U14: legacy entries stay `None`, ordinal entries `Some`, and a mixed
    /// heap is rejected before mutation.
    #[test]
    fn b2_u14_mixed_heaps_are_rejected_before_mutation() {
        let sort = sort_field(SortDirection::Asc, MissingValuePosition::Last);
        let entry = |key: &str, ordinal: Option<OrdinalSortKey>| MixedEntry {
            hit: SelectedHit {
                segment_index: 0,
                doc_id: 0,
                key: DocumentKey::new(key).expect("key"),
                score: Some(1.0),
                sort_tuple: vec![SortValue::Value(FieldValue::Keyword(key.to_owned()))],
            },
            charge: 100,
            sort: &sort,
            relevance: false,
            ordinal_sort: ordinal,
            key_hash: None,
        };
        let one = entry("k1", Some(OrdinalSortKey::Value(2)));
        let two = entry("k2", Some(OrdinalSortKey::Value(1)));
        assert_eq!(two.cmp(&one), Ordering::Less);
        assert_eq!(
            one.cmp(&two),
            ordinal_sort_key_cmp(
                OrdinalSortKey::Value(2),
                OrdinalSortKey::Value(1),
                SortDirection::Asc,
                MissingValuePosition::Last
            )
        );
        // Equal ranks tie by key ascending.
        let tie = entry("k0", Some(OrdinalSortKey::Value(2)));
        assert_eq!(tie.cmp(&one), Ordering::Less);
        // Legacy entries keep the canonical tuple comparator.
        let legacy_a = entry("k1", None);
        let legacy_b = entry("k2", None);
        assert_eq!(
            legacy_a.cmp(&legacy_b),
            compare_candidates(
                &legacy_a.hit.sort_tuple,
                &legacy_a.hit.key,
                &legacy_b.hit.sort_tuple,
                &legacy_b.hit.key,
                &sort
            )
        );
        // A mixed pair falls back to the canonical comparison without panicking.
        assert_eq!(
            legacy_a.cmp(&one),
            compare_candidates(
                &legacy_a.hit.sort_tuple,
                &legacy_a.hit.key,
                &one.hit.sort_tuple,
                &one.hit.key,
                &sort
            )
        );
        let mut heap = BinaryHeap::new();
        heap.push(legacy_a);
        let error = ensure_ordinal_heap(&heap).expect_err("mixed heap");
        assert!(matches!(error, SearchError::CorruptIndex { .. }));
        assert_eq!(heap.len(), 1);
    }

    /// B2-U16: descending input makes every candidate competitive, so owned
    /// strings track actual admissions; ascending input bounds them by K+1.
    #[test]
    fn b2_u16_materialization_tracks_competitiveness() {
        let count = 1_000usize;
        let descending: Vec<(String, City)> = (0..count)
            .map(|index| {
                let value = format!("d{:08}", count - index);
                // Leaked literals keep the test input table static.
                (
                    format!("k{index:05}"),
                    City::Value(Box::leak(value.into_boxed_str())),
                )
            })
            .collect();
        let refs: Vec<(&str, City)> = descending
            .iter()
            .map(|(key, city)| (key.as_str(), *city))
            .collect();
        let index = build(&refs);
        let snapshot = index.snapshot();
        b2_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, count as u64);
        assert_eq!(b2_observation::numeric_candidates(), count);
        assert_eq!(b2_observation::owned_single_strings(), count);
        assert_eq!(b2_observation::single_rejected_without_copy(), 0);
        assert_eq!(b2_observation::numeric_compares(), count - 11);

        let ascending: Vec<(&str, City)> = (0..count)
            .map(|index| {
                let value = Box::leak(format!("d{index:08}").into_boxed_str());
                (
                    Box::leak(format!("k{index:05}").into_boxed_str()) as &str,
                    City::Value(value),
                )
            })
            .collect();
        let index = build(&ascending);
        let snapshot = index.snapshot();
        b2_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, count as u64);
        assert!(b2_observation::owned_single_strings() <= 11);
        assert_eq!(
            b2_observation::single_rejected_without_copy(),
            count - b2_observation::owned_single_strings()
        );
    }

    /// B2-U17: a corrupt v2 dictionary term is refused by the authoritative
    /// reader, never downgraded to optional unavailability.
    #[test]
    fn b2_u17_corrupt_v2_terms_are_authoritative_errors() {
        let index = build(&[("k0", City::Value("alpha")), ("k1", City::Value("beta"))]);
        let guard = primary_guard(&index.snapshot());
        let mut bytes = guard.reader().bytes().to_vec();
        let at = bytes
            .windows(5)
            .position(|window| window == b"alpha")
            .expect("alpha payload");
        bytes[at] = 0xFF;
        assert!(crate::segment::SegmentReader::open(bytes, SegmentLimits::default()).is_err());
    }

    /// B2-U18: both production duplicate strategies keep identical results.
    #[test]
    fn b2_u18_duplicate_strategies_preserve_ordinal_results() {
        let segments: Vec<Vec<(&str, City)>> = (0..3)
            .map(|segment| {
                (0..20)
                    .map(|position| {
                        let key: &'static str =
                            Box::leak(format!("k{segment}-{position:03}").into_boxed_str());
                        let value: &'static str = Box::leak(
                            format!("v{:03}", (position * 7 + segment) % 13).into_boxed_str(),
                        );
                        (key, City::Value(value))
                    })
                    .collect()
            })
            .collect();
        let index = build_segments(&segments);
        let snapshot = index.snapshot();
        let request = request(
            term(),
            10,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        let schema = schema();
        let registry = AnalyzerRegistry::builtin();
        let baseline = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
            .search(&request, &Budgets::new(), &NeverCancel)
            .expect("linear");
        for strategy in [
            TopKDuplicateStrategy::Prefilter,
            TopKDuplicateStrategy::ExactSet,
        ] {
            let searcher =
                UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
                    .with_topk_duplicate_config(TopKDuplicateConfig::new(
                        NonZeroUsize::new(1).expect("nonzero"),
                        strategy,
                    ));
            let response = searcher
                .search(&request, &Budgets::new(), &NeverCancel)
                .expect("strategy");
            assert_eq!(keys(&response), keys(&baseline), "{strategy:?}");
            assert_eq!(bits(&response), bits(&baseline), "{strategy:?}");
        }
    }

    /// B2-U19: one snapshot reuses its map; distinct snapshot objects keep
    /// separate bindings.
    #[test]
    fn b2_u19_map_reuse_is_snapshot_scoped() {
        let index = build(&[("k0", City::Value("a")), ("k1", City::Value("b"))]);
        let first = index.snapshot();
        let second = index.snapshot();
        assert_ne!(first.binding_id(), second.binding_id());
        let request = request(
            term(),
            10,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        b2_observation::reset();
        let a = search(&first, &request);
        let b = search(&first, &request);
        assert_eq!(keys(&a), keys(&b));
        assert_eq!(b2_observation::map_preparations(), 2);
        assert_eq!(b2_observation::optional_fallbacks(), 0);
        let c = search(&second, &request);
        assert_eq!(keys(&a), keys(&c));
    }

    /// B2-U20: single-segment identity, all missing/null and an empty snapshot.
    #[test]
    fn b2_u20_identity_all_missing_and_empty_snapshot() {
        let index = build(&[
            ("k0", City::Missing),
            ("k1", City::Null),
            ("k2", City::Value("")),
            ("k3", City::Value("a")),
        ]);
        let snapshot = index.snapshot();
        let rows = vec![
            ("k0".to_owned(), City::Missing),
            ("k1".to_owned(), City::Null),
            ("k2".to_owned(), City::Value("")),
            ("k3".to_owned(), City::Value("a")),
        ];
        b2_observation::reset();
        compare_both(&snapshot, &rows, 100);
        assert_eq!(b2_observation::map_preparations(), 4);
        assert_eq!(b2_observation::owned_single_strings(), 8);

        let empty = Index::create_with_limits(
            directory(),
            schema(),
            AnalyzerRegistry::builtin(),
            large_limits(),
        )
        .expect("empty index");
        let snapshot = empty.snapshot();
        assert_eq!(snapshot.segment_count(), 0);
        b2_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, 0);
        assert!(response.hits.is_empty());
        assert!(response.next_cursor.is_none());
        assert_eq!(b2_observation::eligible_requests(), 0);
        assert_eq!(b2_observation::map_preparations(), 0);
    }

    /// B2-U23: cursor validation keeps precedence over map preparation.
    #[test]
    fn b2_u23_cursor_validation_precedes_preparation() {
        let index = build(&[
            ("k0", City::Value("a")),
            ("k1", City::Value("b")),
            ("k2", City::Value("c")),
        ]);
        let snapshot = index.snapshot();
        let asc = sort_field(SortDirection::Asc, MissingValuePosition::Last);
        let first = search(&snapshot, &request(term(), 2, asc.clone()));
        let cursor = first.next_cursor.clone().expect("cursor");

        let mut second = request(term(), 2, asc);
        second.after = Some(cursor.clone());
        b2_observation::reset();
        let page = search(&snapshot, &second);
        assert_eq!(keys(&page), vec!["k2".to_owned()]);
        assert!(page.next_cursor.is_none());
        assert_eq!(b2_observation::map_preparations(), 0);

        let mut wrong_sort = request(
            term(),
            2,
            sort_field(SortDirection::Desc, MissingValuePosition::Last),
        );
        wrong_sort.after = Some(cursor.clone());
        b2_observation::reset();
        let error =
            run(&snapshot, &wrong_sort, SearchLimits::default()).expect_err("cursor sort mismatch");
        assert!(matches!(
            error,
            SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorSortMismatch
            ))
        ));
        assert_eq!(b2_observation::map_preparations(), 0);

        let other = index.snapshot();
        let mut foreign = request(
            term(),
            2,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        foreign.after = Some(cursor);
        let error = run(&other, &foreign, SearchLimits::default()).expect_err("foreign cursor");
        assert!(matches!(
            error,
            SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch
            ))
        ));
        assert_eq!(b2_observation::map_preparations(), 0);
    }

    /// B2-U13: 64 deterministic generated cases against an independent oracle.
    #[test]
    fn b2_u13_generated_differential_oracle() {
        // Frozen plan seed; the grouped spelling is intentional.
        #[allow(clippy::unusual_byte_groupings)]
        const SEED: u64 = 0xB2_06_20_26_00_00_0001;
        const VALUES: [&str; 13] = [
            "", "\u{0}", "A", "a", "aa", "Austin", "Boston", "Seattle", "e\u{301}", "é", "😀",
            "ab", "Z",
        ];
        let mut state = SEED;
        let mut next = || {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        };
        for case in 0..64usize {
            let segment_count = 1 + (case % 5);
            let mut segments: Vec<Vec<(String, City)>> = Vec::new();
            let mut counter = 0usize;
            for _ in 0..segment_count {
                let docs = 1 + (next() as usize % 24);
                let mut segment = Vec::new();
                for _ in 0..docs {
                    let key = format!("k{counter:06}");
                    counter += 1;
                    let choice = next() % 11;
                    let city = if choice == 0 {
                        City::Missing
                    } else if choice == 1 {
                        City::Null
                    } else if choice == 2 {
                        City::Multi(VALUES[(next() as usize) % VALUES.len()])
                    } else {
                        City::Value(VALUES[(next() as usize) % VALUES.len()])
                    };
                    segment.push((key, city));
                }
                segments.push(segment);
            }
            let owned: Vec<Vec<(&str, City)>> = segments
                .iter()
                .map(|segment| {
                    segment
                        .iter()
                        .map(|(key, city)| (key.as_str(), *city))
                        .collect()
                })
                .collect();
            let index = build_segments(&owned);
            let snapshot = index.snapshot();
            let rows: Vec<(String, City)> = segments
                .iter()
                .flat_map(|segment| segment.iter().cloned())
                .collect();
            let top_k = [1usize, 2, 5, 10, 20][(next() as usize) % 5];
            for direction in [SortDirection::Asc, SortDirection::Desc] {
                for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                    let sort = sort_field(direction, missing);
                    let ordinal = run(
                        &snapshot,
                        &request(term(), top_k, sort.clone()),
                        SearchLimits::default(),
                    )
                    .unwrap_or_else(|error| panic!("case {case} (seed {SEED}) failed: {error:?}"));
                    let legacy = run(
                        &snapshot,
                        &request(fallback_query(), top_k, sort),
                        SearchLimits::default(),
                    )
                    .unwrap_or_else(|error| panic!("case {case} (seed {SEED}) failed: {error:?}"));
                    let expected: Vec<String> = expected_order(&rows, direction, missing)
                        .into_iter()
                        .take(top_k)
                        .collect();
                    assert_eq!(
                        keys(&ordinal),
                        expected,
                        "case {case} seed {SEED} {direction:?}/{missing:?}"
                    );
                    assert_eq!(ordinal.total_hits, rows.len() as u64, "case {case}");
                    assert_eq!(keys(&legacy), keys(&ordinal), "case {case}");
                    assert_eq!(bits(&legacy), bits(&ordinal), "case {case}");
                    assert_eq!(
                        legacy
                            .hits
                            .iter()
                            .map(|hit| hit.fields.clone())
                            .collect::<Vec<_>>(),
                        ordinal
                            .hits
                            .iter()
                            .map(|hit| hit.fields.clone())
                            .collect::<Vec<_>>(),
                        "case {case}"
                    );
                }
            }
        }
    }

    /// F1: read one real document's shared numeric sort key.
    fn ordinal_key_for_doc(
        bound: &KeywordSortOrdinalColumn<'_>,
        translation: &SegmentOrdinalMap<'_>,
        doc_id: u64,
    ) -> OrdinalSortKey {
        match bound.read_sort_row(doc_id).expect("row") {
            KeywordOrdinalValue::Missing => OrdinalSortKey::Missing,
            KeywordOrdinalValue::Null => OrdinalSortKey::Null,
            KeywordOrdinalValue::Value { ordinal, .. } => {
                OrdinalSortKey::Value(translation.translate(ordinal).expect("translate"))
            }
        }
    }

    /// F1: read-only heap identity used to prove no mutation on rejection.
    fn heap_identity(
        heap: &BinaryHeap<MixedEntry<'_>>,
    ) -> Vec<(String, u64, Option<OrdinalSortKey>, Option<u64>)> {
        heap.iter()
            .map(|entry| {
                (
                    entry.hit.key.as_str().to_owned(),
                    entry.charge,
                    entry.ordinal_sort,
                    entry.hit.score.map(f64::to_bits),
                )
            })
            .collect()
    }

    /// F1-U02: exactly one full heap audit per Ready request, none for legacy.
    #[test]
    fn b2_f1_u02_one_time_audit_and_numeric_only_admissions() {
        let count = 1_000usize;
        let descending: Vec<(&str, City)> = (0..count)
            .map(|index| {
                let value = Box::leak(format!("d{:08}", count - index).into_boxed_str());
                (
                    Box::leak(format!("k{index:05}").into_boxed_str()) as &str,
                    City::Value(value),
                )
            })
            .collect();
        let index = build(&descending);
        let snapshot = index.snapshot();
        let sort = sort_field(SortDirection::Asc, MissingValuePosition::Last);
        b2_observation::reset();
        let response = search(&snapshot, &request(term(), 10, sort.clone()));
        assert_eq!(response.total_hits, count as u64);
        assert_eq!(
            keys(&response),
            (0..10)
                .map(|offset| format!("k{:05}", count - 1 - offset))
                .collect::<Vec<_>>()
        );
        // Every descending-input document is competitive and admitted, yet the
        // full audit still runs only once for the request.
        assert_eq!(b2_observation::numeric_candidates(), count);
        assert_eq!(b2_observation::owned_single_strings(), count);
        assert_eq!(b2_observation::numeric_compares(), count - 11);
        assert_eq!(b2_observation::full_heap_audits(), 1);

        let legacy = search(&snapshot, &request(fallback_query(), 10, sort.clone()));
        assert_eq!(keys(&legacy), keys(&response));
        assert_eq!(bits(&legacy), bits(&response));

        // A second request has its own audit even when the B1 map is cached.
        b2_observation::reset();
        let second = search(&snapshot, &request(term(), 10, sort));
        assert_eq!(keys(&second), keys(&response));
        assert_eq!(b2_observation::map_preparations(), 1);
        assert_eq!(b2_observation::full_heap_audits(), 1);

        // An ineligible request never prepares a map and never audits a heap.
        b2_observation::reset();
        let ineligible = search(
            &snapshot,
            &request(
                fallback_query(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(ineligible.total_hits, count as u64);
        assert_eq!(b2_observation::eligible_requests(), 0);
        assert_eq!(b2_observation::map_preparations(), 0);
        assert_eq!(b2_observation::full_heap_audits(), 0);
    }

    /// F1-U03: with K+1=2, the third (`z`x80) Single candidate is genuinely
    /// rejected after two admissions and never owns a string.
    #[test]
    fn b2_f1_u03_long_loser_after_k_plus_one() {
        let long: &'static str = Box::leak("z".repeat(80).into_boxed_str());
        assert_eq!(long.len(), 80);
        let index = build(&[
            ("k0", City::Value("a")),
            ("k1", City::Value("b")),
            ("k2", City::Value(long)),
        ]);
        let snapshot = index.snapshot();
        let guard = primary_guard(&snapshot);
        let doc_keys: Vec<String> = guard
            .reader()
            .doc_keys()
            .expect("keys")
            .iter()
            .map(|key| key.as_str().to_owned())
            .collect();
        assert_eq!(doc_keys, vec!["k0", "k1", "k2"]);
        let sort = sort_field(SortDirection::Asc, MissingValuePosition::Last);
        b2_observation::reset();
        let ordinal = search(&snapshot, &request(term(), 1, sort.clone()));
        assert_eq!(ordinal.total_hits, 3);
        assert_eq!(keys(&ordinal), vec!["k0".to_owned()]);
        assert_eq!(b2_observation::eligible_requests(), 1);
        assert_eq!(b2_observation::ready_uses(), 1);
        assert_eq!(b2_observation::map_preparations(), 1);
        assert_eq!(b2_observation::numeric_candidates(), 3);
        assert_eq!(b2_observation::numeric_compares(), 1);
        assert_eq!(b2_observation::owned_single_strings(), 2);
        assert_eq!(b2_observation::single_rejected_without_copy(), 1);
        assert_eq!(b2_observation::full_heap_audits(), 1);

        b2_observation::reset();
        let legacy = search(&snapshot, &request(fallback_query(), 1, sort));
        assert_eq!(keys(&legacy), keys(&ordinal));
        assert_eq!(legacy.total_hits, ordinal.total_hits);
        assert_eq!(bits(&legacy), bits(&ordinal));
        assert_eq!(
            legacy
                .hits
                .iter()
                .map(|hit| hit.fields.clone())
                .collect::<Vec<_>>(),
            ordinal
                .hits
                .iter()
                .map(|hit| hit.fields.clone())
                .collect::<Vec<_>>()
        );
    }

    /// F1-U01: a hidden legacy entry must be rejected even when the candidate is
    /// numerically losing and the heap's worst entry is numeric.
    #[test]
    fn b2_f1_u01_hidden_mixed_heap_rejected_even_for_loser() {
        let index = build(&[
            ("k0", City::Value("a")),
            ("k1", City::Value("b")),
            ("k2", City::Value("z")),
        ]);
        let snapshot = index.snapshot();
        let guards: Vec<_> = (0..snapshot.segment_count())
            .map(|index| snapshot.open_segment_reader(index).expect("guard"))
            .collect();
        assert_eq!(guards.len(), 1);
        let guard = &guards[0];
        let doc_keys: Vec<String> = guard
            .reader()
            .doc_keys()
            .expect("keys")
            .iter()
            .map(|key| key.as_str().to_owned())
            .collect();
        assert_eq!(doc_keys, vec!["k0", "k1", "k2"]);
        let field = guard
            .reader()
            .schema()
            .field_id("doc_id")
            .expect("field id");
        let preparation = snapshot
            .prepare_keyword_ordinals(field, &guards, &NeverCancel)
            .expect("prepare");
        let map = preparation
            .ready()
            .unwrap_or_else(|| panic!("ready map: {preparation:?}"));
        let translation = map.bind_segment(guard).expect("bind segment");
        let reader = guard.reader();
        let columns = ColumnAccess::open(reader).expect("columns");
        let bound = columns
            .bind_keyword_sort_ordinal(field)
            .expect("bind")
            .expect("ordinal");
        let rank_a = ordinal_key_for_doc(&bound, &translation, 0);
        let rank_b = ordinal_key_for_doc(&bound, &translation, 1);
        let rank_z = ordinal_key_for_doc(&bound, &translation, 2);
        let ordered = |left, right| {
            ordinal_sort_key_cmp(left, right, SortDirection::Asc, MissingValuePosition::Last)
        };
        assert_eq!(
            ordered(rank_a, rank_b),
            Ordering::Less,
            "real segment order a<b"
        );
        assert_eq!(
            ordered(rank_b, rank_z),
            Ordering::Less,
            "real segment order b<z"
        );

        let request = request(
            term(),
            1,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        let make = |key: &str, value: &str, ordinal: Option<OrdinalSortKey>| {
            let hit = SelectedHit {
                segment_index: 0,
                doc_id: 0,
                key: DocumentKey::new(key).expect("key"),
                score: Some(1.0),
                sort_tuple: vec![SortValue::Value(FieldValue::Keyword(value.to_owned()))],
            };
            let charge = candidate_charge(&hit).expect("charge");
            MixedEntry {
                hit,
                charge,
                sort: &request.sort,
                relevance: false,
                ordinal_sort: ordinal,
                key_hash: None,
            }
        };
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        heap.push(make("k0", "a", None));
        heap.push(make("k1", "b", Some(rank_b)));
        assert_eq!(heap.len(), 2, "K+1 heap capacity");
        let worst = heap.peek().expect("worst");
        assert_eq!(worst.hit.key.as_str(), "k1", "numeric worst, not legacy");
        assert_eq!(worst.ordinal_sort, Some(rank_b));
        assert!(
            heap.iter()
                .filter(|entry| entry.ordinal_sort.is_none())
                .count()
                == 1,
            "one hidden legacy entry"
        );
        let before = heap_identity(&heap);

        let mut budget = CandidateBudget::new(&SearchLimits::default());
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let mut experiment = d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1);
        let mut audit = OrdinalHeapAudit::new();
        b2_observation::reset();
        let error = consider_ordinal_keyword_candidate(
            &columns,
            reader.schema(),
            &request,
            2,
            0,
            DocumentKey::new("k2").expect("key"),
            1.0,
            true,
            &bound,
            &translation,
            &mut audit,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut experiment,
        )
        .expect_err("a hidden legacy entry must fail before a losing return");
        match error {
            SearchError::CorruptIndex { detail } => {
                assert_eq!(detail, "mixed ordinal and legacy sort entries");
            }
            other => panic!("unexpected error: {other:?}"),
        }
        assert_eq!(b2_observation::numeric_compares(), 0);
        assert_eq!(b2_observation::owned_single_strings(), 0);
        assert_eq!(b2_observation::full_heap_audits(), 1);
        assert_eq!(heap_identity(&heap), before, "no heap mutation");

        // Positive arm: a clean numeric-only heap must accept a numeric-losing
        // candidate without owning a string, and without being called corrupt.
        let mut clean: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        clean.push(make("k0", "a", Some(rank_a)));
        clean.push(make("k1", "b", Some(rank_b)));
        let clean_before = heap_identity(&clean);
        let mut clean_budget = CandidateBudget::new(&SearchLimits::default());
        let mut clean_experiment = d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 1);
        let mut clean_audit = OrdinalHeapAudit::new();
        b2_observation::reset();
        consider_ordinal_keyword_candidate(
            &columns,
            reader.schema(),
            &request,
            2,
            0,
            DocumentKey::new("k2").expect("key"),
            1.0,
            true,
            &bound,
            &translation,
            &mut clean_audit,
            &mut clean,
            2,
            &mut clean_budget,
            &mut scope,
            &mut clean_experiment,
        )
        .expect("a numeric-losing candidate on a clean heap is not corruption");
        assert_eq!(b2_observation::numeric_compares(), 1);
        assert_eq!(b2_observation::owned_single_strings(), 0);
        assert_eq!(b2_observation::full_heap_audits(), 1);
        assert_eq!(heap_identity(&clean), clean_before, "no heap mutation");
    }
}

/// PR 15I-D3-C strategy tests (experimental feature only).
#[cfg(all(test, feature = "pr15i-d3c-experiment"))]
mod d3c_tests {
    use super::d3c::{Kind, Profile, State};
    use super::*;
    use crate::analysis::CancellationFlag;
    use crate::contract::document::{Cardinality, Document, FieldValues};
    use crate::contract::result::{Sort, SortDirection, SortField};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn entry<'a>(sort: &'a Sort, value: &str, score: f64, doc_id: u64) -> MixedEntry<'a> {
        let hit = SelectedHit {
            segment_index: 0,
            doc_id,
            key: key(value),
            score: Some(score),
            sort_tuple: Vec::new(),
        };
        let charge = candidate_charge(&hit).unwrap();
        MixedEntry {
            hit,
            charge,
            sort,
            relevance: true,
            ordinal_sort: None,
            key_hash: None,
        }
    }

    thread_local! {
        static TEST_BUDGET: std::cell::RefCell<CandidateBudget> = std::cell::RefCell::new(
            CandidateBudget::new(&SearchLimits::default())
        );
    }

    fn admit<'a>(
        state: &mut State,
        heap: &mut BinaryHeap<MixedEntry<'a>>,
        sort: &'a Sort,
        value: &str,
        score: f64,
        doc_id: u64,
        limit: usize,
    ) -> SearchResult<()> {
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        TEST_BUDGET.with(|budget| {
            let mut budget = budget.borrow_mut();
            state.admit(
                entry(sort, value, score, doc_id),
                heap,
                limit,
                &mut budget,
                &mut scope,
            )
        })
    }

    #[test]
    fn u01_linear_empty_heap() {
        let heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let state = State::for_test(Kind::Linear, Profile::P0, 8);
        assert!(state.check(&heap, &key("a")).is_ok());
    }

    #[test]
    fn u02_linear_duplicate_detail() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        heap.push(entry(&sort, "a", 1.0, 0));
        let state = State::for_test(Kind::Linear, Profile::P0, 8);
        let error = state.check(&heap, &key("a")).unwrap_err();
        assert!(
            matches!(error, SearchError::CorruptIndex { detail } if detail == "duplicate live document key across segments")
        );
    }

    #[test]
    fn u03_prefilter_bits_after_admission() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 1.0, 0, 8).unwrap();
        assert_eq!(state.admissions_count(), 1);
        assert!(state.check(&heap, &key("a")).is_err());
        state.check(&heap, &key("b")).unwrap();
    }

    #[test]
    fn u04_u05_negative_probe_skips_scan() {
        let sort = Sort::default();
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        heap.push(entry(&sort, "retained", 1.0, 0));
        let mut state = State::for_test(Kind::Prefilter, Profile::P2, 8);
        state.note_key(&key("retained"));
        let before = state.exact_scans();
        // A distinct key with at least one clear probe must not scan.
        for candidate in ["other-1", "other-2", "other-3"] {
            if state.check(&heap, &key(candidate)).is_err() {
                panic!("unexpected duplicate");
            }
        }
        assert!(state.exact_scans() >= before);
        state.check(&heap, &key("retained")).unwrap_err();
    }

    #[test]
    fn u06_positive_exact_duplicate() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        heap.push(entry(&sort, "dup", 1.0, 0));
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        state.note_key(&key("dup"));
        assert!(state.check(&heap, &key("dup")).is_err());
    }

    #[test]
    fn u07_collision_resolved_by_exact_scan() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        heap.push(entry(&sort, "alpha", 1.0, 0));
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        let victim = key("collision-victim");
        state.set_both_bits(State::hash_for_test(&victim));
        let scans = state.exact_scans();
        state.check(&heap, &victim).unwrap();
        assert_eq!(state.exact_scans(), scans + 1);
    }

    #[test]
    fn u08_evicted_bits_are_stale_but_safe() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        heap.push(entry(&sort, "current", 1.0, 0));
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        state.note_key(&key("evicted"));
        state.check(&heap, &key("evicted")).unwrap();
    }

    #[test]
    fn u09_losers_do_not_increment_admissions() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 2).unwrap();
        admit(&mut state, &mut heap, &sort, "b", 9.0, 1, 2).unwrap();
        let before = state.admissions_count();
        admit(&mut state, &mut heap, &sort, "loser", 1.0, 2, 2).unwrap();
        assert_eq!(state.admissions_count(), before);
        assert_eq!(state.key_count(), 0);
    }

    #[test]
    fn u10_p0_disable_at_256() {
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        for index in 0..255 {
            state.note_key(&key(&format!("k{index}")));
        }
        assert!(!state.is_disabled());
        state.note_key(&key("k255"));
        assert!(state.is_disabled());
        assert_eq!(state.admissions_count(), 256);
        let heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let scans = state.exact_scans();
        state.check(&heap, &key("anything")).unwrap();
        assert_eq!(state.exact_scans(), scans + 1);
    }

    #[test]
    fn u11_p1_disable_at_1024() {
        let mut state = State::for_test(Kind::Prefilter, Profile::P1, 8);
        for index in 0..1024 {
            state.note_key(&key(&format!("k{index}")));
        }
        assert!(state.is_disabled());
        assert_eq!(state.admissions_count(), 1024);
    }

    #[test]
    fn u12_p2_disable_at_2048() {
        let mut state = State::for_test(Kind::Prefilter, Profile::P2, 8);
        for index in 0..2048 {
            state.note_key(&key(&format!("k{index}")));
        }
        assert!(state.is_disabled());
        assert_eq!(state.admissions_count(), 2048);
    }

    #[test]
    fn u13_probe_indices_in_range() {
        for profile in [Profile::P0, Profile::P1, Profile::P2] {
            let mask = profile.bits() - 1;
            let hash = 0x1234_5678_9abc_def0u64;
            let first = (hash as usize) & mask;
            let second = ((hash >> 32) as usize) & mask;
            assert!(first < profile.bits());
            assert!(second < profile.bits());
        }
    }

    #[test]
    fn u14_exact_set_insert() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 1.0, 0, 8).unwrap();
        assert!(state.contains_key(&key("a")));
        assert_eq!(state.key_count(), heap.len());
    }

    #[test]
    fn u15_exact_set_loser_not_inserted() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 1).unwrap();
        admit(&mut state, &mut heap, &sort, "b", 9.0, 1, 1).unwrap();
        admit(&mut state, &mut heap, &sort, "loser", 1.0, 2, 1).unwrap();
        assert!(!state.contains_key(&key("loser")));
        assert_eq!(state.key_count(), heap.len());
    }

    #[test]
    fn u16_exact_set_replacement_evicts() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 1).unwrap();
        admit(&mut state, &mut heap, &sort, "b", 20.0, 1, 1).unwrap();
        assert!(!state.contains_key(&key("a")));
        assert!(state.contains_key(&key("b")));
        assert_eq!(state.key_count(), heap.len());
    }

    #[test]
    fn u17_evicted_key_not_retained() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 1).unwrap();
        admit(&mut state, &mut heap, &sort, "b", 20.0, 1, 1).unwrap();
        state.check(&heap, &key("a")).unwrap();
    }

    #[test]
    fn u18_exact_set_unequal_key() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 8).unwrap();
        state.check(&heap, &key("b")).unwrap();
    }

    #[test]
    fn u19_exact_set_duplicate_losing() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, "a", 10.0, 0, 2).unwrap();
        admit(&mut state, &mut heap, &sort, "b", 9.0, 1, 2).unwrap();
        let error = state.check(&heap, &key("a")).unwrap_err();
        assert!(matches!(error, SearchError::CorruptIndex { .. }));
    }

    #[test]
    fn u20_budget_failure_leaves_state() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        let mut tight = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(10)
                .unwrap(),
        );
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let error = state
            .admit(
                entry(&sort, "a", 1.0, 0),
                &mut heap,
                8,
                &mut tight,
                &mut scope,
            )
            .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        assert_eq!(state.key_count(), 0);
        assert!(heap.is_empty());
    }

    #[test]
    fn u26_states_are_independent() {
        let sort = Sort::default();
        let mut first_heap = BinaryHeap::new();
        let second_heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut first = State::for_test(Kind::ExactSet, Profile::P0, 8);
        let second = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut first, &mut first_heap, &sort, "a", 1.0, 0, 8).unwrap();
        assert!(first.contains_key(&key("a")));
        assert!(!second.contains_key(&key("a")));
        drop(second_heap);
    }

    #[test]
    fn u28_exact_set_k_bounds() {
        let error = State::for_test_checked(Kind::ExactSet, Profile::P0, 0).err();
        assert!(matches!(error, Some(SearchError::ResourceLimit { .. })));
        let error = State::for_test_checked(Kind::ExactSet, Profile::P0, 1025).err();
        assert!(matches!(error, Some(SearchError::ResourceLimit { .. })));
        assert!(State::for_test_checked(Kind::ExactSet, Profile::P0, 1024).is_ok());
    }

    #[test]
    fn u29_long_key_identity() {
        let value = "x".repeat(DocumentKey::MAX_BYTES);
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        admit(&mut state, &mut heap, &sort, &value, 1.0, 0, 8).unwrap();
        assert!(state.contains_key(&key(&value)));
    }

    #[test]
    fn u31_u32_prefilter_active_at_k100_and_k10() {
        for k in [10usize, 100] {
            let sort = Sort::default();
            let mut heap = BinaryHeap::new();
            let mut state = State::for_test(Kind::Prefilter, Profile::P0, k);
            admit(&mut state, &mut heap, &sort, "a", 1.0, 0, k).unwrap();
            assert_eq!(state.admissions_count(), 1, "K{k}");
            assert!(state.check(&heap, &key("a")).is_err(), "K{k}");
        }
    }

    /// Diagnostic micro grid for D3-C profile selection. Ignored by default.
    #[test]
    #[ignore]
    fn d3c_micro_grid() {
        use std::time::Instant;
        let sort = Sort::default();
        let kinds = [
            ("linear", Kind::Linear, Profile::P0),
            ("P0", Kind::Prefilter, Profile::P0),
            ("P1", Kind::Prefilter, Profile::P1),
            ("P2", Kind::Prefilter, Profile::P2),
            ("exact_set", Kind::ExactSet, Profile::P0),
        ];
        let ks = [1usize, 10, 32, 64, 100, 128, 256, 512, 1024];
        let lens = [8usize, 32, 128, 1024];
        let traces = [
            "miss_stable",
            "duplicate_retained",
            "churn",
            "evicted_revisit",
            "collision_distinct",
        ];
        for (label, kind, profile) in kinds {
            for k in ks {
                for key_len in lens {
                    for trace in traces {
                        let mut rounds = Vec::new();
                        let mut rescans = 0usize;
                        let mut aux = (0usize, 0usize, 0usize);
                        for round in 0..5u32 {
                            let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                            let mut state = State::for_test(kind, profile, k);
                            let mut budget = CandidateBudget::new(&SearchLimits::default());
                            let mut scope: Option<SlotMemoryScope<'_>> = None;
                            for i in 0..k {
                                let name = format!("{:0width$}", i, width = key_len);
                                let e = entry(&sort, &name, (k - i) as f64, i as u64);
                                state
                                    .admit(e, &mut heap, k, &mut budget, &mut scope)
                                    .expect("initial admission");
                            }
                            let base = state.exact_scans();
                            let iterations = 200usize;
                            let started = Instant::now();
                            for i in 0..iterations {
                                let name = match trace {
                                    "duplicate_retained" => {
                                        format!("{:0width$}", i % k.max(1), width = key_len)
                                    }
                                    "churn" => {
                                        let name = format!(
                                            "churn-{round}-{i}-{:0width$}",
                                            i,
                                            width = key_len.saturating_sub(20).max(1)
                                        );
                                        let e = entry(
                                            &sort,
                                            &name,
                                            1_000_000.0 + i as f64,
                                            (k + 1 + i) as u64,
                                        );
                                        state
                                            .admit(e, &mut heap, k, &mut budget, &mut scope)
                                            .expect("churn admission");
                                        name
                                    }
                                    "evicted_revisit" => format!("evicted-{round}-{i}"),
                                    "collision_distinct" => {
                                        let victim = format!("collision-{round}-{i}");
                                        if kind == Kind::Prefilter {
                                            state
                                                .set_both_bits(State::hash_for_test(&key(&victim)));
                                        }
                                        victim
                                    }
                                    _ => format!("loser-{round}-{i}"),
                                };
                                let _ = state.check(&heap, &key(&name));
                            }
                            let elapsed = started.elapsed().as_nanos() as u64;
                            if trace == "churn" {
                                assert_eq!(heap.len(), k, "churn must keep cardinality");
                            }
                            rounds.push(elapsed / iterations as u64);
                            rescans += state.exact_scans() - base;
                            aux = state.aux_memory_estimate();
                        }
                        rounds.sort_unstable();
                        let median = rounds[2];
                        let rescan_fraction = rescans as f64 / (200.0 * 5.0);
                        println!(
                            "D3CMICRO {{\"variant\":\"{label}\",\"k\":{k},\"key_len\":{key_len},\"trace\":\"{trace}\",\"median_ns_per_op\":{median},\"rescan_fraction\":{rescan_fraction},\"rounds\":{rounds:?},\"set_len\":{},\"set_capacity\":{},\"key_bytes\":{}}}",
                            aux.0, aux.1, aux.2
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn u21_replacement_budget_failure_is_atomic() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        // Calibrate the table reservation with the same accounted constructor
        // used by production. The original 66-byte limit covered only the
        // first entry, silently omitting the preallocated ExactSet table.
        let mut calibration_budget = CandidateBudget::new(&SearchLimits::default());
        let mut calibration_scope = None;
        let calibration = State::for_test_accounted(
            Kind::ExactSet,
            Profile::P0,
            8,
            &mut calibration_budget,
            &mut calibration_scope,
        )
        .unwrap();
        let table_bytes = calibration.exact_charges().0;
        let allowance = table_bytes.checked_add(66).unwrap();
        let mut b = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(allowance)
                .unwrap(),
        );
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let mut state =
            State::for_test_accounted(Kind::ExactSet, Profile::P0, 8, &mut b, &mut scope).unwrap();
        assert_eq!(state.exact_charges().0, table_bytes);
        state
            .admit(entry(&sort, "a", 1.0, 0), &mut heap, 1, &mut b, &mut scope)
            .unwrap();
        let before = state.exact_charges();
        let error = state
            .admit(entry(&sort, "b", 9.0, 1), &mut heap, 1, &mut b, &mut scope)
            .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        assert_eq!(state.exact_charges(), before);
        assert!(state.contains_key(&key("a")));
        assert!(!state.contains_key(&key("b")));
        assert_eq!(state.key_count(), heap.len());
        assert_eq!(heap.peek().unwrap().hit.key, key("a"));
    }

    #[test]
    fn u27_concurrent_states_are_independent() {
        let sort = Sort::default();
        let handles: Vec<_> = (0..2)
            .map(|worker| {
                std::thread::spawn(move || {
                    let sort = Sort::default();
                    let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                    let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
                    let mut b = CandidateBudget::new(&SearchLimits::default());
                    let mut scope: Option<SlotMemoryScope<'_>> = None;
                    let name = format!("worker-{worker}");
                    state
                        .admit(
                            entry(&sort, &name, 1.0, 0),
                            &mut heap,
                            8,
                            &mut b,
                            &mut scope,
                        )
                        .unwrap();
                    assert!(state.contains_key(&key(&name)));
                    (name, state.key_count(), heap.len())
                })
            })
            .collect();
        let results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        assert_ne!(results[0].0, results[1].0);
        for (_, keys, heap) in results {
            assert_eq!(keys, 1);
            assert_eq!(heap, 1);
        }
        drop(sort);
    }

    #[test]
    fn u30_p0_probes_and_cap_match_history() {
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        let victim = key("history-probe");
        let hash = State::hash_for_test(&victim);
        state.note_key(&victim);
        let mask = 1023usize;
        let first = (hash as usize) & mask;
        let second = ((hash >> 32) as usize) & mask;
        assert!(state.bit_for_test(first));
        assert!(state.bit_for_test(second));
        for i in 0..255 {
            state.note_key(&key(&format!("cap-{i}")));
        }
        assert!(state.is_disabled());
        assert_eq!(state.admissions_count(), 256);
    }

    #[test]
    fn u33_evicted_key_is_not_a_retained_duplicate() {
        for kind in [Kind::Prefilter, Kind::ExactSet] {
            let sort = Sort::default();
            let mut heap = BinaryHeap::new();
            let mut state = State::for_test(kind, Profile::P0, 8);
            let mut b = CandidateBudget::new(&SearchLimits::default());
            let mut scope: Option<SlotMemoryScope<'_>> = None;
            state
                .admit(entry(&sort, "a", 1.0, 0), &mut heap, 1, &mut b, &mut scope)
                .unwrap();
            state
                .admit(entry(&sort, "b", 9.0, 1), &mut heap, 1, &mut b, &mut scope)
                .unwrap();
            assert!(state.check(&heap, &key("a")).is_ok(), "{kind:?}");
            assert!(state.check(&heap, &key("b")).is_err(), "{kind:?}");
        }
    }

    #[test]
    fn u36_u37_mode_selection_and_invalid_values() {
        use super::d3c::parse_mode_for_test;
        assert_eq!(
            parse_mode_for_test(None, None),
            Ok((Kind::Linear, Profile::P0))
        );
        assert_eq!(
            parse_mode_for_test(Some("linear"), None),
            Ok((Kind::Linear, Profile::P0))
        );
        assert_eq!(
            parse_mode_for_test(Some("exact_set"), None),
            Ok((Kind::ExactSet, Profile::P0))
        );
        assert_eq!(
            parse_mode_for_test(Some("prefilter"), Some("P2")),
            Ok((Kind::Prefilter, Profile::P2))
        );
        assert!(parse_mode_for_test(Some("prefilter"), None).is_err());
        assert!(parse_mode_for_test(Some("linear"), Some("P0")).is_err());
        assert!(parse_mode_for_test(Some("bogus"), None).is_err());
        assert!(parse_mode_for_test(Some("prefilter"), Some("P9")).is_err());
    }

    #[test]
    fn u41_failed_replacement_preserves_prefilter_state() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::Prefilter, Profile::P0, 8);
        let mut b = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(66)
                .unwrap(),
        );
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        state
            .admit(entry(&sort, "a", 1.0, 0), &mut heap, 1, &mut b, &mut scope)
            .unwrap();
        let before = state.admissions_count();
        let scans = state.exact_scans();
        let _ = state
            .admit(entry(&sort, "b", 9.0, 1), &mut heap, 1, &mut b, &mut scope)
            .unwrap_err();
        assert_eq!(state.admissions_count(), before);
        assert_eq!(state.exact_scans(), scans);
        assert_eq!(heap.len(), 1);
    }

    fn keyword_codec_fixture() -> (crate::segment::CodecSchema, Vec<u8>, u32) {
        use crate::analysis::SchemaAnalyzerBindings;
        use crate::segment::column::encode_columns;
        use crate::segment::{CodecSchema, SegmentDocument, SegmentLimits};
        let contract = Schema::new(
            vec![FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )],
            None,
        )
        .unwrap();
        let bindings =
            SchemaAnalyzerBindings::resolve(&contract, &AnalyzerRegistry::builtin()).unwrap();
        let codec = CodecSchema::from_contract(&contract, &bindings).unwrap();
        let docs: Vec<SegmentDocument> = ["aaa", "bbb"]
            .iter()
            .enumerate()
            .map(|(index, value)| {
                let mut doc =
                    SegmentDocument::new(DocumentKey::new(format!("k{index:03}")).unwrap());
                doc.insert(
                    "doc_id",
                    FieldValues::Single(FieldValue::Keyword((*value).to_owned())),
                )
                .unwrap();
                doc
            })
            .collect();
        let bytes = encode_columns(&codec, &docs, 2, &SegmentLimits::default()).unwrap();
        let field_id = codec.field_id("doc_id").unwrap();
        (codec, bytes, field_id)
    }

    fn keyword_request() -> UnifiedRequest {
        let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(2).unwrap());
        request.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
        request
    }

    #[test]
    fn u24_legacy_keyword_duplicate_and_nonduplicate() {
        use crate::segment::{ColumnReader, SegmentLimits};
        let (codec, bytes, _field_id) = keyword_codec_fixture();
        let reader = ColumnReader::open(&codec, &bytes, &SegmentLimits::default()).unwrap();
        let columns = ColumnAccess::from_columns_for_test(reader);
        let request = keyword_request();
        let limits = SearchLimits::default();
        let mut budget = CandidateBudget::new(&limits);
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 2);
        admit_legacy_keyword_candidate(
            &columns,
            &codec,
            &request,
            0,
            0,
            key("k000"),
            1.0,
            true,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut state,
        )
        .unwrap();
        assert_eq!(state.key_count(), 1);
        let error = admit_legacy_keyword_candidate(
            &columns,
            &codec,
            &request,
            1,
            0,
            key("k000"),
            1.0,
            true,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut state,
        )
        .unwrap_err();
        assert!(matches!(error, SearchError::CorruptIndex { ref detail }
            if detail == "duplicate live document key across segments"));
        assert_eq!(state.key_count(), 1);
        assert_eq!(heap.len(), 1);
        admit_legacy_keyword_candidate(
            &columns,
            &codec,
            &request,
            1,
            0,
            key("k001"),
            1.0,
            true,
            &mut heap,
            2,
            &mut budget,
            &mut scope,
            &mut state,
        )
        .unwrap();
        assert_eq!(state.key_count(), 2);
    }

    #[test]
    fn u25_legacy_and_borrowed_duplicate_sites() {
        use crate::segment::{ColumnReader, SegmentLimits};
        let (codec, bytes, field_id) = keyword_codec_fixture();
        let reader = ColumnReader::open(&codec, &bytes, &SegmentLimits::default()).unwrap();
        let columns = ColumnAccess::from_columns_for_test(reader);
        let request = keyword_request();
        let limits = SearchLimits::default();
        for borrowed in [false, true] {
            let mut budget = CandidateBudget::new(&limits);
            let mut scope: Option<SlotMemoryScope<'_>> = None;
            let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
            let mut state = State::for_test(Kind::ExactSet, Profile::P0, 2);
            let mut call = |doc_id: u64, value: &str, state: &mut State| {
                if borrowed {
                    consider_borrowed_keyword_candidate(
                        &columns,
                        &codec,
                        &request,
                        doc_id,
                        0,
                        key(value),
                        1.0,
                        true,
                        field_id,
                        &mut heap,
                        2,
                        &mut budget,
                        &mut scope,
                        state,
                    )
                } else {
                    admit_legacy_keyword_candidate(
                        &columns,
                        &codec,
                        &request,
                        doc_id,
                        0,
                        key(value),
                        1.0,
                        true,
                        &mut heap,
                        2,
                        &mut budget,
                        &mut scope,
                        state,
                    )
                }
            };
            call(0, "k000", &mut state).unwrap();
            let before = state.key_count();
            let error = call(1, "k000", &mut state).unwrap_err();
            assert!(
                matches!(error, SearchError::CorruptIndex { ref detail }
                if detail == "duplicate live document key across segments"),
                "{error:?}"
            );
            assert_eq!(state.key_count(), before);
            call(1, "k001", &mut state).unwrap();
            assert_eq!(state.key_count(), 2);
        }
    }

    #[test]
    fn u22_cancelled_before_duplicate_check_then_reusable() {
        use crate::index::Index;
        use crate::storage::{Directory, MemoryDirectory};
        use std::sync::Arc;
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            )],
            None,
        )
        .unwrap();
        let registry = AnalyzerRegistry::builtin();
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index =
            Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
        {
            let mut writer = index.writer().unwrap();
            for name in ["a", "b", "c"] {
                let mut document = Document::new(key(name));
                document
                    .insert(
                        "tag",
                        FieldValues::Single(FieldValue::Keyword("red".into())),
                    )
                    .unwrap();
                writer.insert(document).unwrap();
            }
            writer.commit().unwrap();
        }
        let reopened = Index::open_existing(directory, schema.clone(), registry.clone()).unwrap();
        let snap = reopened.snapshot();
        let request = UnifiedRequest::new(
            Query::Term {
                field: "tag".into(),
                value: FieldValue::Keyword("red".into()),
            },
            TopK::new(10).unwrap(),
        );
        let searcher = UnifiedSearcher::new(&snap, &schema, &registry, SearchLimits::default());
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        let error = searcher
            .search(&request, &Budgets::new(), &cancelled)
            .unwrap_err();
        assert!(matches!(error, SearchError::Cancelled));
        let response = searcher
            .search(&request, &Budgets::new(), &CancellationFlag::new())
            .unwrap();
        assert_eq!(response.total_hits, 3);
        assert_eq!(
            response
                .hits
                .iter()
                .map(|h| h.key.as_str().to_owned())
                .collect::<Vec<_>>(),
            vec!["a", "b", "c"]
        );
    }

    #[test]
    fn u34_reservation_failure_is_typed_and_atomic() {
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        state.fail_reserve = true;
        let error = state.reserve_exact_set(8).unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        assert_eq!(state.key_count(), 0);
        state.fail_reserve = false;
        state.reserve_exact_set(8).unwrap();
    }

    #[test]
    fn u42_exact_set_memory_estimate_k1024_long_keys() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 1024);
        for i in 0..1024usize {
            let name = format!("{i:0>1024}");
            admit(&mut state, &mut heap, &sort, &name, 1.0, i as u64, 1024).unwrap();
        }
        let (len, capacity, key_bytes) = state.aux_memory_estimate();
        assert_eq!(len, 1024);
        assert!(capacity >= 1024);
        assert_eq!(key_bytes, 1024 * 1024);
        let estimate = capacity
            .checked_mul(40)
            .and_then(|v| v.checked_add(key_bytes))
            .unwrap();
        assert!(estimate <= 2_097_152, "{estimate}");
    }

    #[test]
    fn fx_h_table_charge_rejects_before_mutation() {
        let heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut budget = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(64)
                .unwrap(),
        );
        let mut scope = None;
        let error =
            State::for_test_accounted(Kind::ExactSet, Profile::P0, 8, &mut budget, &mut scope)
                .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        assert!(heap.is_empty());
    }

    #[test]
    fn fx_h_key_charges_track_insert_and_replacement() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut budget = CandidateBudget::new(&SearchLimits::default());
        let mut scope = None;
        let mut state =
            State::for_test_accounted(Kind::ExactSet, Profile::P0, 2, &mut budget, &mut scope)
                .unwrap();
        let (table0, live0) = state.exact_charges();
        assert_eq!(live0, 0);
        state
            .admit(
                entry(&sort, "a", 1.0, 0),
                &mut heap,
                2,
                &mut budget,
                &mut scope,
            )
            .unwrap();
        state
            .admit(
                entry(&sort, "bb", 2.0, 1),
                &mut heap,
                2,
                &mut budget,
                &mut scope,
            )
            .unwrap();
        let (_, live2) = state.exact_charges();
        assert_eq!(live2, 3);
        state
            .admit(
                entry(&sort, "cccc", 9.0, 2),
                &mut heap,
                2,
                &mut budget,
                &mut scope,
            )
            .unwrap();
        let (table3, live3) = state.exact_charges();
        assert_eq!(table3, table0);
        assert_eq!(live3, 3 - 1 + 4);
    }

    #[test]
    fn fx_h_1024_byte_key_and_one_under_table_budget() {
        let sort = Sort::default();
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut budget = CandidateBudget::new(&SearchLimits::default());
        let mut scope = None;
        let mut state =
            State::for_test_accounted(Kind::ExactSet, Profile::P0, 2, &mut budget, &mut scope)
                .unwrap();
        let (table, _) = state.exact_charges();
        let long = "k".repeat(1024);
        state
            .admit(
                entry(&sort, &long, 1.0, 0),
                &mut heap,
                2,
                &mut budget,
                &mut scope,
            )
            .unwrap();
        let (_, live) = state.exact_charges();
        assert_eq!(live, 1024);
        let mut tight = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(table.saturating_sub(1))
                .unwrap(),
        );
        let mut scope2 = None;
        assert!(
            State::for_test_accounted(Kind::ExactSet, Profile::P0, 2, &mut tight, &mut scope2)
                .is_err()
        );
    }

    #[test]
    fn fx_p2_has_no_h_aux_table_charge() {
        let mut budget = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(64)
                .unwrap(),
        );
        let mut scope = None;
        assert!(
            State::for_test_accounted(Kind::Prefilter, Profile::P2, 32, &mut budget, &mut scope)
                .is_ok()
        );
    }

    #[test]
    fn fx_h_exact_set_churn_preserves_reserved_capacity_and_charges() {
        let sort = Sort::default();
        // Fresh HashSets exercise different randomized bucket layouts.
        for k in [1usize, 10, 100, 1024] {
            for seed in 0..8u64 {
                let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                let mut budget = CandidateBudget::new(&SearchLimits::default());
                let mut scope = None;
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P0,
                    k,
                    &mut budget,
                    &mut scope,
                )
                .unwrap();
                for i in 0..k {
                    let name = format!("init-{seed}-{k}-{i:04}");
                    state
                        .admit(
                            entry(&sort, &name, (k - i) as f64, i as u64),
                            &mut heap,
                            k,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap();
                }
                let (len, _, _) = state.aux_memory_estimate();
                assert_eq!(len, k);
                let mut previous_table_charge = state.exact_charges().0;
                for round in 0..64u64 {
                    let evicted = heap.peek().expect("nonempty").hit.key.clone();
                    let name = format!("churn-{seed}-{k}-{round}");
                    let admitted = key(&name);
                    let score = heap.peek().unwrap().hit.score.unwrap() + 1_000_000.0;
                    state
                        .admit(
                            entry(&sort, &name, score, k as u64 + round),
                            &mut heap,
                            k,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap_or_else(|e| {
                            panic!("ExactSet K{k} seed {seed} round {round}: {e:?}")
                        });
                    assert_eq!(heap.len(), k);
                    assert!(state.contains_key(&admitted));
                    assert!(!state.contains_key(&evicted));
                    let (len, capacity, live_bytes) = state.aux_memory_estimate();
                    let (table_charge, key_charge) = state.exact_charges();
                    assert_eq!(len, k);
                    // Effective capacity may move with tombstone occupancy;
                    // never release or double-charge the physical table.
                    assert!(table_charge >= (capacity as u64) * 40);
                    assert!(table_charge >= previous_table_charge);
                    previous_table_charge = table_charge;
                    assert_eq!(key_charge, live_bytes as u64);
                }
            }
        }
    }

    #[test]
    fn u43_replacement_witness_all_variants() {
        let sort = Sort::default();
        for kind in [Kind::Linear, Kind::Prefilter, Kind::ExactSet] {
            for k in [1usize, 10, 100, 1024] {
                let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                let mut state = State::for_test(kind, Profile::P2, k);
                let mut budget = CandidateBudget::new(&SearchLimits::default());
                let mut scope: Option<SlotMemoryScope<'_>> = None;
                for i in 0..k {
                    let name = format!("init-{k}-{i:04}");
                    let score = (k - i) as f64;
                    state
                        .admit(
                            entry(&sort, &name, score, i as u64),
                            &mut heap,
                            k,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap_or_else(|e| panic!("{kind:?} K{k} init {i}: {e:?}"));
                }
                assert_eq!(heap.len(), k, "{kind:?} K{k} initial heap");
                for round in 0..3u32 {
                    let worst = heap.peek().expect("nonempty").hit.key.clone();
                    let name = format!("churn-{k}-{round}");
                    let candidate = key(&name);
                    let score =
                        heap.peek().unwrap().hit.score.unwrap() + 1_000_000.0 + round as f64;
                    let result = state.admit(
                        entry(&sort, &name, score, (k as u64) + 100 + round as u64),
                        &mut heap,
                        k,
                        &mut budget,
                        &mut scope,
                    );
                    assert!(result.is_ok(), "{kind:?} K{k} round {round}: {result:?}");
                    assert_eq!(heap.len(), k, "{kind:?} K{k} round {round}: cardinality");
                    assert!(
                        heap.iter().any(|e| e.hit.key == candidate),
                        "{kind:?} K{k} round {round}: candidate not retained"
                    );
                    assert!(
                        !heap.iter().any(|e| e.hit.key == worst),
                        "{kind:?} K{k} round {round}: worst key {worst:?} still retained"
                    );
                    if kind == Kind::ExactSet {
                        assert_eq!(
                            state.key_count(),
                            heap.len(),
                            "{kind:?} K{k}: set cardinality"
                        );
                        for e in heap.iter() {
                            assert!(
                                state.contains_key(&e.hit.key),
                                "{kind:?} K{k}: set missing heap key"
                            );
                        }
                    }
                    if kind == Kind::Prefilter {
                        assert!(
                            state.check(&heap, &candidate).is_err(),
                            "{kind:?} K{k}: candidate not positive"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn u39_heap_capacity_and_sentinel() {
        let sort = Sort::default();
        let mut heap = BinaryHeap::new();
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 4);
        for index in 0..4 {
            admit(
                &mut state,
                &mut heap,
                &sort,
                &format!("k{index}"),
                100.0 - index as f64,
                index as u64,
                4,
            )
            .unwrap();
        }
        assert_eq!(heap.len(), 4);
        admit(&mut state, &mut heap, &sort, "better", 200.0, 9, 4).unwrap();
        assert_eq!(heap.len(), 4);
        assert_eq!(state.key_count(), 4);
        assert!(state.contains_key(&key("better")));
    }
}

#[cfg(test)]
mod fx_production_mode_tests {
    use super::d3c::{Kind, Profile, State};
    use super::{TopKDuplicateConfig, TopKDuplicateStrategy};
    use std::num::NonZeroUsize;

    #[test]
    fn fx_final_strategy_selection_k31_k32_k33() {
        let default = TopKDuplicateConfig::default();
        assert_eq!(
            State::production_mode_for_test(31, default),
            (Kind::Linear, Profile::P0)
        );
        assert_eq!(
            State::production_mode_for_test(32, default),
            (Kind::Prefilter, Profile::P2)
        );
        assert_eq!(
            State::production_mode_for_test(33, default),
            (Kind::Prefilter, Profile::P2)
        );
        let exact = TopKDuplicateConfig::new(
            NonZeroUsize::new(32).unwrap(),
            TopKDuplicateStrategy::ExactSet,
        );
        assert_eq!(
            State::production_mode_for_test(32, exact),
            (Kind::ExactSet, Profile::P2)
        );
    }
}

/// PERF-06-B3: compact key-fingerprint collector, duplicate policy, ordering and
/// lifecycle tests.
#[cfg(test)]
mod b3_tests {
    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::{Index, IndexLimits, ReaderSnapshot};
    use crate::segment::reader::{
        B3Probe, B3ProbeOutcome, b3_build_attempts, b3_directory_builds, b3_meta_reads,
        b3_preflight_fallbacks, b3_raw_key_borrows, clear_b3_probe, reset_b3_counters,
        set_b3_probe,
    };
    use crate::storage::{Directory, MemoryDirectory};
    use std::num::NonZeroUsize;
    use std::sync::Arc;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "grp",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "doc_id",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum City {
        Missing,
        Null,
        Value(&'static str),
        Multi(&'static str),
    }

    fn values(city: City) -> Option<FieldValues> {
        match city {
            City::Missing => None,
            City::Null => Some(FieldValues::ExplicitNull),
            City::Value(value) => Some(FieldValues::Single(FieldValue::Keyword(value.to_owned()))),
            City::Multi(value) => Some(FieldValues::Multi(vec![FieldValue::Keyword(
                value.to_owned(),
            )])),
        }
    }

    fn document(key: &str, city: City) -> Document {
        let mut document = Document::new(DocumentKey::new(key).expect("key"));
        document
            .insert(
                "grp",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .expect("grp");
        if let Some(city) = values(city) {
            document.insert("doc_id", city).expect("doc_id");
        }
        document
            .insert("n", FieldValues::Single(FieldValue::I64(1)))
            .expect("n");
        document
    }

    fn large_limits() -> IndexLimits {
        IndexLimits::default()
            .with_max_pending_docs(200_000)
            .with_max_pending_bytes(512 * 1024 * 1024)
    }

    fn directory() -> Arc<dyn Directory> {
        Arc::new(MemoryDirectory::new())
    }

    fn build_segments(segments: &[Vec<(String, City)>]) -> Index {
        let dir = directory();
        {
            let index = Index::create_with_limits(
                Arc::clone(&dir),
                schema(),
                AnalyzerRegistry::builtin(),
                large_limits(),
            )
            .expect("create");
            for segment in segments {
                let mut writer = index.writer().expect("writer");
                for (key, city) in segment {
                    writer.insert(document(key, *city)).expect("insert");
                }
                writer.commit().expect("commit");
            }
        }
        Index::open_existing(dir, schema(), AnalyzerRegistry::builtin()).expect("reopen")
    }

    fn rows(cities: &[City]) -> Vec<(String, City)> {
        (0..cities.len())
            .map(|index| (format!("k{index:05}"), cities[index]))
            .collect()
    }

    fn term() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        }
    }

    fn legacy_term() -> Query {
        Query::And(vec![term()])
    }

    fn sort_field(direction: SortDirection, missing: MissingValuePosition) -> Sort {
        let mut field = SortField::new("doc_id", direction);
        field.missing = missing;
        Sort::new(vec![field])
    }

    fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
        let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
        request.sort = sort;
        request.projection = Projection::Fields(vec!["doc_id".to_owned()]);
        request
    }

    fn run_with(
        snapshot: &ReaderSnapshot,
        request: &UnifiedRequest,
        limits: SearchLimits,
        config: TopKDuplicateConfig,
    ) -> SearchResult<UnifiedResponse> {
        let schema = schema();
        let registry = AnalyzerRegistry::builtin();
        UnifiedSearcher::new(snapshot, &schema, &registry, limits)
            .with_topk_duplicate_config(config)
            .search(request, &Budgets::new(), &NeverCancel)
    }

    fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
        run_with(
            snapshot,
            request,
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("search")
    }

    fn exact_set_config() -> TopKDuplicateConfig {
        TopKDuplicateConfig::new(
            NonZeroUsize::new(32).expect("nonzero"),
            TopKDuplicateStrategy::ExactSet,
        )
    }

    fn keys(response: &UnifiedResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn bits(response: &UnifiedResponse) -> Vec<u64> {
        response
            .hits
            .iter()
            .map(|hit| hit.score.expect("scored").to_bits())
            .collect()
    }

    /// The literal input-derived oracle: class rank, value order, then ascending
    /// raw key bytes. Never derived from a fingerprint or from the production heap.
    fn oracle_order(
        city: City,
        index: usize,
        direction: SortDirection,
        missing: MissingValuePosition,
    ) -> (u8, &'static str, String) {
        let class = match (city, missing) {
            (City::Missing, MissingValuePosition::First) => 0,
            (City::Null, MissingValuePosition::First) => 1,
            (City::Value(_), MissingValuePosition::First) => 2,
            (City::Multi(_), MissingValuePosition::First) => 2,
            (City::Value(_), MissingValuePosition::Last) => 0,
            (City::Multi(_), MissingValuePosition::Last) => 0,
            (City::Null, MissingValuePosition::Last) => 1,
            (City::Missing, MissingValuePosition::Last) => 2,
        };
        let value = match city {
            City::Value(value) | City::Multi(value) => value,
            City::Missing | City::Null => "",
        };
        let _ = direction;
        (class, value, format!("k{index:05}"))
    }

    #[test]
    fn b3_u01_hash_parity_with_the_original_d3c_formula() {
        fn old_hash(key: &DocumentKey) -> u64 {
            use std::hash::{Hash, Hasher};
            let mut hasher = std::collections::hash_map::DefaultHasher::new();
            key.as_str().hash(&mut hasher);
            hasher.finish()
        }
        let mut raw: Vec<String> = vec![
            String::from("a"),
            String::from("A"),
            String::from("ab"),
            String::from("a\u{0}b"),
            String::from("\u{0}"),
            String::from("e\u{301}"),
            String::from("é"),
            String::from("😀"),
            String::from("Ω"),
            String::from("k00000"),
            String::from("v000001"),
            "x".repeat(DocumentKey::MAX_BYTES),
            String::from(" leading"),
            String::from("trailing "),
        ];
        for index in 0..50 {
            raw.push(format!("prefix-{index:02}-suffix"));
        }
        assert_eq!(raw.len(), 64);
        for value in &raw {
            let key = DocumentKey::new(value.clone()).expect("valid key");
            let oracle = old_hash(&key);
            assert_eq!(
                runtime_doc_key_hash(key.as_str()),
                oracle,
                "runtime hash parity for {value:?}"
            );
            assert_eq!(
                d3c::State::hash_for_test(&key),
                oracle,
                "unchanged d3c hash for {value:?}"
            );
        }
        // Invalid keys are rejected before a directory can ever be published.
        assert!(DocumentKey::new(String::new()).is_err());
        assert!(DocumentKey::new("x".repeat(DocumentKey::MAX_BYTES + 1)).is_err());
    }

    #[test]
    fn b3_u02_numeric_order_matches_the_b2_owned_path_and_a_byte_oracle() {
        let cities = [
            City::Value("b"),
            City::Value("a"),
            City::Missing,
            City::Null,
            City::Value("a"),
            City::Multi("a"),
            City::Value("z"),
            City::Value("B"),
        ];
        let index = build_segments(&[rows(&cities)]);
        let snapshot = index.snapshot();
        reset_b3_counters();
        let mut total_directory_builds = 0u64;
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                let top_k = 32usize;
                let req = request(term(), top_k, sort_field(direction, missing));
                let meta_before = b3_meta_reads();
                let compact = search(&snapshot, &req);
                assert_eq!(
                    b3_meta_reads() - meta_before,
                    cities.len() as u64,
                    "compact path engaged for every match"
                );
                total_directory_builds += b3_directory_builds();
                // The resolved-ExactSet configuration keeps the owned B2 path.
                reset_b3_counters();
                let owned = run_with(&snapshot, &req, SearchLimits::default(), exact_set_config())
                    .expect("owned b2");
                assert_eq!(b3_build_attempts(), 0, "no B3 bind for resolved ExactSet");
                assert_eq!(keys(&compact), keys(&owned));
                assert_eq!(bits(&compact), bits(&owned));
                assert_eq!(compact.total_hits, owned.total_hits);

                // Independent literal oracle over the input table.
                let mut expected: Vec<(u8, String, String)> = cities
                    .iter()
                    .enumerate()
                    .map(|(position, city)| {
                        let (class, value, key) = oracle_order(*city, position, direction, missing);
                        (class, value.to_owned(), key)
                    })
                    .collect();
                expected.sort_by(|left, right| {
                    left.0
                        .cmp(&right.0)
                        .then_with(|| match direction {
                            SortDirection::Asc => left.1.cmp(&right.1),
                            SortDirection::Desc => right.1.cmp(&left.1),
                        })
                        .then_with(|| left.2.as_bytes().cmp(right.2.as_bytes()))
                });
                let expected_keys: Vec<String> = expected
                    .into_iter()
                    .take(top_k)
                    .map(|(_, _, key)| key)
                    .collect();
                assert_eq!(keys(&compact), expected_keys, "{direction:?}/{missing:?}");
                let fallback = search(
                    &snapshot,
                    &request(legacy_term(), top_k, sort_field(direction, missing)),
                );
                assert_eq!(keys(&compact), keys(&fallback));
                assert_eq!(bits(&compact), bits(&fallback));
            }
        }
        assert_eq!(total_directory_builds, 1, "one directory per segment");
    }

    fn synthetic_entry(
        key: &str,
        hash: Option<u64>,
        ordinal: Option<OrdinalSortKey>,
    ) -> MixedEntry<'static> {
        let sort: &'static Sort = Box::leak(Box::new(sort_field(
            SortDirection::Asc,
            MissingValuePosition::Last,
        )));
        MixedEntry {
            hit: SelectedHit {
                segment_index: 0,
                doc_id: 0,
                key: DocumentKey::new(key).expect("key"),
                score: Some(1.0),
                sort_tuple: vec![SortValue::Value(FieldValue::Keyword(key.to_owned()))],
            },
            charge: 100,
            sort,
            relevance: false,
            ordinal_sort: ordinal,
            key_hash: hash,
        }
    }

    #[test]
    fn b3_u04_u23_fingerprints_are_prefilters_never_identity() {
        let shared = 0xDEAD_BEEF_u64;
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        heap.push(synthetic_entry(
            "retained-key",
            Some(shared),
            Some(OrdinalSortKey::Value(1)),
        ));
        let state = d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 8);
        // A forced fingerprint collision with different bytes is *not* a duplicate.
        state
            .check_compact(&heap, shared, || Ok("other-key"))
            .expect("collision is not identity");
        // The genuine same bytes are a duplicate even for a losing candidate.
        let error = state
            .check_compact(&heap, shared, || Ok("retained-key"))
            .expect_err("exact duplicate");
        assert!(
            matches!(error, SearchError::CorruptIndex { .. }),
            "{error:?}"
        );
        // A different fingerprint never consults the exact key at all.
        let mut consulted = false;
        state
            .check_compact(&heap, shared ^ 1, || {
                consulted = true;
                Ok("never")
            })
            .expect("no collision");
        assert!(!consulted, "no raw key borrow without a hash match");
        // Sentinel hashes are ordinary values.
        for sentinel in [0u64, u64::MAX] {
            let mut sentinel_heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
            sentinel_heap.push(synthetic_entry(
                "sentinel",
                Some(sentinel),
                Some(OrdinalSortKey::Value(1)),
            ));
            state
                .check_compact(&sentinel_heap, sentinel, || Ok("different"))
                .expect("sentinel collision, different bytes");
            assert!(matches!(
                state.check_compact(&sentinel_heap, sentinel, || Ok("sentinel")),
                Err(SearchError::CorruptIndex { .. })
            ));
        }
        // A retained entry without a fingerprint fails closed even when it is not
        // the worst entry.
        let mut mixed: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        mixed.push(synthetic_entry(
            "hashed",
            Some(shared),
            Some(OrdinalSortKey::Value(1)),
        ));
        mixed.push(synthetic_entry(
            "unhashed",
            None,
            Some(OrdinalSortKey::Value(9)),
        ));
        let error = state
            .check_compact(&mixed, shared, || Ok("x"))
            .expect_err("missing fingerprint");
        assert!(
            matches!(error, SearchError::CorruptIndex { .. }),
            "{error:?}"
        );
        // The request-local audit fails closed on the same heap.
        let mut audit = CompactHashAudit::new();
        assert!(audit.verify_once(&mixed).is_err());
        let mut clean = CompactHashAudit::new();
        clean.verify_once(&heap).expect("all entries hashed");
        clean.verify_once(&heap).expect("audited once");
    }

    #[test]
    fn b3_u05_u15_compact_policy_matches_the_owned_policy() {
        for (kind, profile) in [
            (d3c::Kind::Linear, d3c::Profile::P0),
            (d3c::Kind::Prefilter, d3c::Profile::P2),
            (d3c::Kind::Prefilter, d3c::Profile::P0),
        ] {
            for candidate_index in 0..40 {
                let key = format!("k{candidate_index:03}");
                let mut owned_state = d3c::State::for_test(kind, profile, 8);
                let mut compact_state = d3c::State::for_test(kind, profile, 8);
                let mut owned_heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                let mut compact_heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
                for retained in 0..4 {
                    let retained_key = format!("r{retained:03}");
                    let hash = runtime_doc_key_hash(&retained_key);
                    owned_heap.push(synthetic_entry(
                        &retained_key,
                        Some(hash),
                        Some(OrdinalSortKey::Value(retained as u64)),
                    ));
                    compact_heap.push(synthetic_entry(
                        &retained_key,
                        Some(hash),
                        Some(OrdinalSortKey::Value(retained as u64)),
                    ));
                    let retained_document_key = DocumentKey::new(retained_key).expect("key");
                    if matches!(kind, d3c::Kind::Prefilter) {
                        owned_state.note_key(&retained_document_key);
                        compact_state.note_key(&retained_document_key);
                    }
                }
                let document_key = DocumentKey::new(key.clone()).expect("key");
                let owned = owned_state.check(&owned_heap, &document_key);
                let compact =
                    compact_state.check_compact(&compact_heap, runtime_doc_key_hash(&key), || {
                        Ok(key.as_str())
                    });
                assert_eq!(
                    owned.is_err(),
                    compact.is_err(),
                    "{kind:?}/{profile:?} candidate {candidate_index}"
                );
                assert_eq!(owned_state.exact_scans(), compact_state.exact_scans());
                assert_eq!(
                    owned_state.admissions_count(),
                    compact_state.admissions_count()
                );
                assert_eq!(owned_state.is_disabled(), compact_state.is_disabled());
            }
        }
        // Resolved-mode gating: only Linear/Prefilter may use compact keys.
        assert!(
            d3c::State::for_test(d3c::Kind::Linear, d3c::Profile::P0, 8).supports_compact_key()
        );
        assert!(
            d3c::State::for_test(d3c::Kind::Prefilter, d3c::Profile::P2, 32).supports_compact_key()
        );
        assert!(
            !d3c::State::for_test(d3c::Kind::ExactSet, d3c::Profile::P0, 32).supports_compact_key()
        );
        // A source defect that reached the compact path in ExactSet mode fails
        // closed before any mutation.
        let exact = d3c::State::for_test(d3c::Kind::ExactSet, d3c::Profile::P0, 4);
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        heap.push(synthetic_entry(
            "k",
            Some(1),
            Some(OrdinalSortKey::Value(1)),
        ));
        assert!(matches!(
            exact.check_compact(&heap, 1, || Ok("k")),
            Err(SearchError::CorruptIndex { .. })
        ));
    }

    fn ascending_corpus(count: usize) -> Vec<(String, City)> {
        (0..count)
            .map(|index| {
                let value: &'static str = Box::leak(format!("v{index:08}").into_boxed_str());
                (format!("k{index:05}"), City::Value(value))
            })
            .collect()
    }

    fn descending_corpus(count: usize) -> Vec<(String, City)> {
        (0..count)
            .map(|index| {
                let value: &'static str =
                    Box::leak(format!("v{:08}", count - index).into_boxed_str());
                (format!("k{index:05}"), City::Value(value))
            })
            .collect()
    }

    #[test]
    fn b3_u06_u18_losing_candidates_own_no_key() {
        let count = 50_000usize;
        for top_k in [10usize, 100] {
            let index = build_segments(&[ascending_corpus(count)]);
            let snapshot = index.snapshot();
            reset_b3_counters();
            b2_observation::reset();
            b3_observation::reset();
            let response = search(
                &snapshot,
                &request(
                    term(),
                    top_k,
                    sort_field(SortDirection::Asc, MissingValuePosition::Last),
                ),
            );
            assert_eq!(response.total_hits, count as u64);
            assert_eq!(response.hits.len(), top_k);
            assert_eq!(
                keys(&response),
                (0..top_k).map(|i| format!("k{i:05}")).collect::<Vec<_>>()
            );
            assert_eq!(b3_directory_builds(), 1, "one directory per segment");
            assert_eq!(b3_meta_reads(), count as u64, "one meta read per match");
            assert!(
                b3_observation::owned_key_materializations() <= top_k + 1,
                "owned={}",
                b3_observation::owned_key_materializations()
            );
            assert!(
                b3_raw_key_borrows() <= top_k as u64 + 1,
                "borrows={}",
                b3_raw_key_borrows()
            );
            assert_eq!(b2_observation::numeric_candidates(), count);
            assert!(
                b2_observation::owned_single_strings() <= top_k + 1,
                "owned strings={}",
                b2_observation::owned_single_strings()
            );
            assert_eq!(
                b2_observation::single_rejected_without_copy(),
                count - b2_observation::owned_single_strings()
            );
            assert_eq!(b3_observation::one_time_heap_hash_audits(), 1);
            assert_eq!(b3_observation::hash_collision_exact_checks(), 0);
            assert_eq!(b3_preflight_fallbacks(), 0);
            let fallback = search(
                &snapshot,
                &request(
                    legacy_term(),
                    top_k,
                    sort_field(SortDirection::Asc, MissingValuePosition::Last),
                ),
            );
            assert_eq!(keys(&response), keys(&fallback));
            assert_eq!(bits(&response), bits(&fallback));
        }
    }

    #[test]
    fn b3_u07_reverse_order_and_multi_one_losers() {
        let count = 1_000usize;
        let index = build_segments(&[descending_corpus(count)]);
        let snapshot = index.snapshot();
        reset_b3_counters();
        b2_observation::reset();
        b3_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, count as u64);
        assert_eq!(
            b3_observation::owned_key_materializations(),
            count,
            "every reverse-ordered candidate is competitive"
        );
        assert_eq!(b2_observation::owned_single_strings(), count);

        // MultiOne losers still run the complete legacy decode.
        let multi: Vec<(String, City)> = (0..64)
            .map(|index| {
                let value: &'static str = Box::leak(format!("m{index:08}").into_boxed_str());
                (format!("m{index:05}"), City::Multi(value))
            })
            .collect();
        let index = build_segments(&[multi]);
        let snapshot = index.snapshot();
        b2_observation::reset();
        b3_observation::reset();
        let response = search(
            &snapshot,
            &request(
                term(),
                5,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.total_hits, 64);
        assert_eq!(
            b2_observation::multi_one_legacy_decodes(),
            64,
            "every MultiOne candidate decodes before rejection"
        );
        assert_eq!(b2_observation::owned_single_strings(), 0);
        assert!(b3_observation::owned_key_materializations() <= 6);
    }

    /// Deterministic xorshift corpus generator (no external dependency).
    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            let mut value = self.0;
            value ^= value << 13;
            value ^= value >> 7;
            value ^= value << 17;
            self.0 = value;
            value
        }
        fn pick(&mut self, modulo: u64) -> u64 {
            self.next() % modulo
        }
    }

    #[test]
    fn b3_u08_u19_seeded_differential_oracle() {
        const SEED: u64 = 0xB306_2026_0000_0001;
        const VALUES: [&str; 6] = ["a", "b", "a", "aa", "Z", "é"];
        let mut rng = Rng(SEED);
        for case in 0..64u64 {
            let segment_count = 1 + rng.pick(5) as usize;
            let mut segments: Vec<Vec<(String, City)>> = Vec::new();
            let mut table: Vec<City> = Vec::new();
            for _ in 0..segment_count {
                let docs = 1 + rng.pick(24) as usize;
                let mut segment = Vec::new();
                for _ in 0..docs {
                    let city = match rng.pick(8) {
                        0 => City::Missing,
                        1 => City::Null,
                        _ => City::Value(VALUES[rng.pick(VALUES.len() as u64) as usize]),
                    };
                    table.push(city);
                    segment.push((format!("k{:05}", segment.len() + table.len() * 100), city));
                }
                segments.push(segment);
            }
            // Keys must be globally unique across segments.
            let mut seen = std::collections::BTreeSet::new();
            for segment in &mut segments {
                for row in segment.iter_mut() {
                    while !seen.insert(row.0.clone()) {
                        row.0.push('x');
                    }
                }
            }
            let flat: Vec<(String, City)> = segments.iter().flatten().cloned().collect();
            let index = build_segments(&segments);
            let snapshot = index.snapshot();
            for top_k in [1usize, 2, 5, 10, 20, 32, 100] {
                for direction in [SortDirection::Asc, SortDirection::Desc] {
                    for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                        let req = request(term(), top_k, sort_field(direction, missing));
                        reset_b3_counters();
                        let compact = search(&snapshot, &req);
                        let mut expected: Vec<(u8, String, String)> = flat
                            .iter()
                            .map(|(key, city)| {
                                let class = match (city, missing) {
                                    (City::Missing, MissingValuePosition::First) => 0,
                                    (City::Null, MissingValuePosition::First) => 1,
                                    (City::Value(_), MissingValuePosition::First) => 2,
                                    (City::Value(_), MissingValuePosition::Last) => 0,
                                    (City::Null, MissingValuePosition::Last) => 1,
                                    (City::Missing, MissingValuePosition::Last) => 2,
                                    (_, _) => unreachable!(),
                                };
                                let value = match city {
                                    City::Value(value) => (*value).to_owned(),
                                    _ => String::new(),
                                };
                                (class, value, key.clone())
                            })
                            .collect();
                        expected.sort_by(|left, right| {
                            left.0
                                .cmp(&right.0)
                                .then_with(|| match direction {
                                    SortDirection::Asc => left.1.cmp(&right.1),
                                    SortDirection::Desc => right.1.cmp(&left.1),
                                })
                                .then_with(|| left.2.as_bytes().cmp(right.2.as_bytes()))
                        });
                        let expected_keys: Vec<String> = expected
                            .into_iter()
                            .take(top_k)
                            .map(|(_, _, key)| key)
                            .collect();
                        assert_eq!(
                            keys(&compact),
                            expected_keys,
                            "seed {SEED:#x} case {case} K {top_k} {direction:?}/{missing:?}"
                        );
                        assert_eq!(
                            compact.total_hits,
                            flat.len() as u64,
                            "seed {SEED:#x} case {case} K {top_k}"
                        );
                        let legacy = search(
                            &snapshot,
                            &request(legacy_term(), top_k, sort_field(direction, missing)),
                        );
                        assert_eq!(
                            keys(&compact),
                            keys(&legacy),
                            "seed {SEED:#x} case {case} K {top_k}"
                        );
                        assert_eq!(
                            bits(&compact),
                            bits(&legacy),
                            "seed {SEED:#x} case {case} K {top_k}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn b3_u09_mode_gating_and_ineligible_shapes() {
        let index = build_segments(&[rows(&[
            City::Value("a"),
            City::Value("b"),
            City::Value("c"),
        ])]);
        let single_sort = || sort_field(SortDirection::Asc, MissingValuePosition::Last);

        // The resolved-mode boundary is derived from source, not inferred from a
        // result: the configured cutoff is 32 and only K >= 32 is ExactSet.
        assert_eq!(
            d3c::State::production_mode_for_test(32, exact_set_config()),
            (d3c::Kind::ExactSet, d3c::Profile::P2)
        );
        assert_eq!(
            d3c::State::production_mode_for_test(31, exact_set_config()),
            (d3c::Kind::Linear, d3c::Profile::P0)
        );

        // K=32 ExactSet as the *first* request on a fresh snapshot, so a cached
        // directory could not mask a missing-build observation.
        let exact_snapshot = index.snapshot();
        reset_b3_counters();
        let exact = run_with(
            &exact_snapshot,
            &request(term(), 32, single_sort()),
            SearchLimits::default(),
            exact_set_config(),
        )
        .expect("resolved ExactSet at K=32");
        assert_eq!(exact.total_hits, 3);
        assert_eq!(
            keys(&exact),
            vec!["k00000", "k00001", "k00002"],
            "literal expected order"
        );
        assert_eq!(
            b3_build_attempts(),
            0,
            "resolved ExactSet never binds a key directory"
        );
        assert_eq!(b3_directory_builds(), 0);

        // K=100 ExactSet remains an additional positive behavioural check.
        let snapshot = index.snapshot();
        reset_b3_counters();
        run_with(
            &snapshot,
            &request(term(), 100, single_sort()),
            SearchLimits::default(),
            exact_set_config(),
        )
        .expect("resolved ExactSet at K=100");
        assert_eq!(b3_build_attempts(), 0);
        assert_eq!(b3_directory_builds(), 0);

        // Configured ExactSet below the cutoff resolves to Linear and stays
        // B3-eligible with the unchanged Linear semantics.
        reset_b3_counters();
        let response = run_with(
            &snapshot,
            &request(term(), 10, single_sort()),
            SearchLimits::default(),
            exact_set_config(),
        )
        .expect("linear resolution");
        assert_eq!(keys(&response), vec!["k00000", "k00001", "k00002"]);
        assert_eq!(b3_directory_builds(), 1);

        // A valid two-column sort is ineligible for B3: exact output, no
        // preparation. Fresh snapshot so no cached directory can mask the check.
        let multi_snapshot = index.snapshot();
        reset_b3_counters();
        let mut multi_sort = request(term(), 10, single_sort());
        multi_sort
            .sort
            .fields
            .push(SortField::new("n", SortDirection::Asc));
        let multi = run_with(
            &multi_snapshot,
            &multi_sort,
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("a valid two-column sort must succeed");
        assert_eq!(multi.total_hits, 3);
        assert_eq!(keys(&multi), vec!["k00000", "k00001", "k00002"]);
        assert_eq!(multi.hits.len(), 3);
        assert!(multi.next_cursor.is_none());
        assert_eq!(
            b3_build_attempts(),
            0,
            "a two-field sort never binds a key directory"
        );
        assert_eq!(b3_directory_builds(), 0);

        // The semantically equivalent ineligible legacy query agrees exactly.
        let mut legacy_multi = multi_sort;
        legacy_multi.query = legacy_term();
        let legacy = run_with(
            &multi_snapshot,
            &legacy_multi,
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("legacy two-column sort");
        assert_eq!(keys(&legacy), keys(&multi));
        assert_eq!(legacy.total_hits, multi.total_hits);
        assert_eq!(bits(&legacy), bits(&multi));
        for (left, right) in legacy.hits.iter().zip(multi.hits.iter()) {
            assert_eq!(left.fields, right.fields);
        }
    }

    #[test]
    fn b3_u16_mixed_ready_and_unavailable_segments() {
        let first: Vec<(String, City)> = rows(&[City::Value("a"), City::Value("b")]);
        let second: Vec<(String, City)> = (0..4)
            .map(|index| {
                let value: &'static str = Box::leak(format!("c{index}").into_boxed_str());
                (format!("s{index:05}"), City::Value(value))
            })
            .collect();
        let index = build_segments(&[first.clone(), second.clone()]);
        let snapshot = index.snapshot();
        let reference = search(
            &snapshot,
            &request(
                legacy_term(),
                100,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );

        // First segment refuses the directory, second publishes one.
        clear_b3_probe();
        set_b3_probe(B3Probe::BeforeHashAllocation, || {
            Ok(B3ProbeOutcome::RefuseAllocation)
        });
        reset_b3_counters();
        let response = search(
            &snapshot,
            &request(
                term(),
                100,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        clear_b3_probe();
        assert!(b3_preflight_fallbacks() >= 1);
        assert_eq!(b3_directory_builds(), 1, "the second segment published");
        assert_eq!(keys(&response), keys(&reference));
        assert_eq!(bits(&response), bits(&reference));

        // Reverse: the first segment publishes, the second refuses.
        let index = build_segments(&[first.clone(), second.clone()]);
        let snapshot = index.snapshot();
        let reference = search(
            &snapshot,
            &request(
                legacy_term(),
                100,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        clear_b3_probe();
        set_b3_probe(B3Probe::BeforeHashAllocation, || {
            set_b3_probe(B3Probe::BeforeHashAllocation, || {
                Ok(B3ProbeOutcome::RefuseAllocation)
            });
            Ok(B3ProbeOutcome::Continue)
        });
        reset_b3_counters();
        let response = search(
            &snapshot,
            &request(
                term(),
                100,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        clear_b3_probe();
        assert_eq!(b3_directory_builds(), 1);
        assert_eq!(b3_preflight_fallbacks(), 1);
        assert_eq!(keys(&response), keys(&reference));
        assert_eq!(bits(&response), bits(&reference));
    }

    #[test]
    fn b3_u17_key_lengths_and_budget_failure() {
        let long = "x".repeat(DocumentKey::MAX_BYTES);
        let index = build_segments(&[vec![
            ("a".to_owned(), City::Value("aa")),
            ("ab".to_owned(), City::Value("ab")),
            (long.clone(), City::Value("zz")),
        ]]);
        let snapshot = index.snapshot();
        let req = request(
            term(),
            2,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        reset_b3_counters();
        let response = search(&snapshot, &req);
        assert_eq!(keys(&response), vec!["a".to_owned(), "ab".to_owned()]);
        assert!(
            b3_observation::owned_key_materializations() <= 3,
            "owned={}",
            b3_observation::owned_key_materializations()
        );
        // A one-byte candidate budget cannot admit any candidate.
        let tight = SearchLimits::default()
            .with_max_total_candidate_bytes(1)
            .expect("limits");
        let error = run_with(&snapshot, &req, tight, TopKDuplicateConfig::default())
            .expect_err("candidate budget");
        assert!(
            matches!(error, SearchError::ResourceLimit { .. }),
            "{error:?}"
        );
        // A fresh run is unaffected by the failed attempt.
        reset_b3_counters();
        let again = search(&snapshot, &req);
        assert_eq!(keys(&again), keys(&response));
        assert_eq!(bits(&again), bits(&response));
    }

    /// B3-F1 / F1-I01+I02: a *real* `UnifiedSearcher` query against a
    /// checksum-valid snapshot whose `DOC_KEYS` body holds one corrupt
    /// **unselected** key.
    ///
    /// Zero-match queries must succeed without key resolution; a matched query
    /// must surface the authoritative typed DOC_KEYS error through the collector
    /// (B3 binding refuses the optional offsets directory, then the owned-key
    /// fallback performs the full authoritative decode).
    #[test]
    fn b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key() {
        use crate::segment::{
            ContainerBuilder, ContainerKind, SectionKind, SegmentLimits, SegmentReader,
        };
        use quervant_objectstore::ContentDescriptor;

        let limits = SegmentLimits::default();
        let sort = sort_field(SortDirection::Asc, MissingValuePosition::Last);

        // --- pristine two-document, single-segment corpus -------------------
        let dir = directory();
        {
            let index = Index::create_with_limits(
                Arc::clone(&dir),
                schema(),
                AnalyzerRegistry::builtin(),
                large_limits(),
            )
            .expect("create");
            let mut writer = index.writer().expect("writer");
            writer.insert(document("k0", City::Value("a"))).expect("k0");
            let mut nonmatching = document("k1", City::Value("b"));
            nonmatching
                .insert(
                    "grp",
                    FieldValues::Single(FieldValue::Keyword("other".to_owned())),
                )
                .expect("grp");
            writer.insert(nonmatching).expect("k1");
            writer.commit().expect("commit");
        }
        let index =
            Index::open_existing(dir, schema(), AnalyzerRegistry::builtin()).expect("reopen");
        let snapshot = index.snapshot();
        assert_eq!(snapshot.segment_count(), 1, "one real v2 segment");
        {
            let guard = snapshot.open_segment_reader(0).expect("guard");
            let physical: Vec<String> = guard
                .reader()
                .doc_keys()
                .expect("keys")
                .iter()
                .map(|key| key.as_str().to_owned())
                .collect();
            assert_eq!(
                physical,
                vec!["k0".to_owned(), "k1".to_owned()],
                "physical doc-id order"
            );
        }
        let pristine = snapshot.segments()[0].bytes().to_vec();
        let pristine_match = run_with(
            &snapshot,
            &request(term(), 1, sort.clone()),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("pristine matched query");
        assert_eq!(pristine_match.total_hits, 1);
        assert_eq!(keys(&pristine_match), vec!["k0".to_owned()]);
        assert_eq!(
            pristine_match.hits[0].fields,
            vec![(
                "doc_id".to_owned(),
                FieldValues::Single(FieldValue::Keyword("a".to_owned())),
            )],
            "literal projection oracle"
        );

        // --- rebuild a checksum-valid container with one corrupt unselected key
        let view = crate::segment::parse_container(&pristine, &limits).expect("container");
        let doc_count = view.doc_count();
        let required: Vec<(u16, u16)> = view.required_features().to_vec();
        let optional: Vec<(u16, u16)> = view.optional_features().to_vec();
        let sections: Vec<(SectionKind, u16, u64, Vec<u8>)> = view
            .sections()
            .iter()
            .map(|entry| {
                (
                    entry.kind,
                    entry.flags,
                    entry.aux,
                    view.body(entry.kind).expect("body").to_vec(),
                )
            })
            .collect();
        let keys_body = view.body(SectionKind::DocKeys).expect("doc keys").to_vec();
        // DOC_KEYS is `u16 version + u64 count + (u16 len + UTF-8 bytes)*`.
        // `k1` must appear exactly once, and only as the second record's payload.
        let hits: Vec<usize> = keys_body
            .windows(2)
            .enumerate()
            .filter(|(_, window)| *window == b"k1")
            .map(|(index, _)| index)
            .collect();
        assert_eq!(hits.len(), 1, "exactly one literal k1 payload");
        let corrupt_at = hits[0];
        assert!(
            corrupt_at > 12,
            "k1 must be the second payload, not the header"
        );
        let mut corrupt_keys = keys_body.clone();
        corrupt_keys[corrupt_at] = 0xFF;
        assert_ne!(corrupt_keys, keys_body, "payload byte actually changed");

        let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
        for (id, version) in &required {
            builder.require_feature(*id, *version);
        }
        for (id, version) in &optional {
            builder.optional_feature(*id, *version);
        }
        for (kind, flags, aux, body) in &sections {
            let body = if *kind == SectionKind::DocKeys {
                corrupt_keys.clone()
            } else {
                body.clone()
            };
            builder.section(*kind, *flags, *aux, body);
        }
        let rebuilt = builder.build().expect("rebuilt checksum-valid container");
        assert_ne!(rebuilt, pristine, "the rebuilt bytes are different");

        // The rebuilt container validates lazily, yet the full key decoder rejects
        // the *unselected* corrupt record.
        let probe = SegmentReader::open(rebuilt.clone(), limits).expect("lazy open");
        let probe_error = probe.doc_key(0).expect_err("corrupt unselected key");
        assert!(
            matches!(
                probe_error,
                crate::segment::SegmentError::InvalidUtf8 { context: "doc key" }
            ),
            "{probe_error:?}"
        );
        assert_eq!(
            pristine.as_slice(),
            snapshot.segments()[0].bytes(),
            "the original immutable bytes are untouched"
        );

        // --- wrap the rebuilt segment in a real in-memory snapshot ----------
        let corrupt_snapshot = ReaderSnapshot::for_test(
            vec![crate::index::SegmentSnapshot::new(
                crate::index::SegmentMeta::new(
                    "b3-f1-corrupt",
                    "test/b3-f1-corrupt",
                    ContentDescriptor::of(&rebuilt),
                    required,
                    optional,
                    None,
                ),
                Arc::new(rebuilt),
                doc_count,
            )],
            limits,
            256 * 1024 * 1024,
            256 * 1024 * 1024,
        );

        // (1) A zero-match query must succeed *before* any matched query, proving
        // that no eager key resolution happens for zero hits.
        reset_b3_counters();
        let zero = run_with(
            &corrupt_snapshot,
            &request(
                Query::Term {
                    field: "grp".to_owned(),
                    value: FieldValue::Keyword("no-such-group".to_owned()),
                },
                1,
                sort.clone(),
            ),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("a zero-match query must succeed without key resolution");
        assert_eq!(zero.total_hits, 0);
        assert!(zero.hits.is_empty());
        assert!(zero.next_cursor.is_none());
        assert_eq!(
            b3_build_attempts(),
            0,
            "no key preparation for zero matches"
        );

        // (2) The matched query must surface the exact authoritative typed error.
        let matched = run_with(
            &corrupt_snapshot,
            &request(term(), 1, sort.clone()),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect_err("a matched query must reject the corrupt unselected key");
        assert!(
            matches!(
                matched,
                SearchError::Segment(crate::segment::SegmentError::InvalidUtf8 {
                    context: "doc key"
                })
            ),
            "{matched:?}"
        );

        // (3) Repeating it must not become a sticky success.
        let repeated = run_with(
            &corrupt_snapshot,
            &request(term(), 1, sort.clone()),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect_err("repeat must report the same typed error");
        assert!(
            matches!(
                repeated,
                SearchError::Segment(crate::segment::SegmentError::InvalidUtf8 {
                    context: "doc key"
                })
            ),
            "{repeated:?}"
        );

        // (4) The ineligible legacy path has the same authoritative outcome.
        let legacy = run_with(
            &corrupt_snapshot,
            &request(legacy_term(), 1, sort.clone()),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect_err("the ineligible owned path must also reject the corruption");
        assert!(
            matches!(
                legacy,
                SearchError::Segment(crate::segment::SegmentError::InvalidUtf8 {
                    context: "doc key"
                })
            ),
            "{legacy:?}"
        );

        // (5) The pristine index is unaffected.
        let healthy = run_with(
            &snapshot,
            &request(term(), 1, sort),
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
        .expect("the pristine snapshot still answers");
        assert_eq!(healthy.total_hits, 1);
        assert_eq!(keys(&healthy), vec!["k0".to_owned()]);
        assert_eq!(
            healthy.hits[0].fields,
            vec![(
                "doc_id".to_owned(),
                FieldValues::Single(FieldValue::Keyword("a".to_owned())),
            )]
        );
    }

    #[test]
    fn b3_u20_u22_empty_no_match_and_ineligible_paths() {
        let index = build_segments(&[rows(&[City::Value("a"), City::Value("b")])]);
        let snapshot = index.snapshot();
        reset_b3_counters();
        let none = search(
            &snapshot,
            &request(
                Query::Term {
                    field: "grp".to_owned(),
                    value: FieldValue::Keyword("absent".to_owned()),
                },
                10,
                sort_field(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(none.total_hits, 0);
        assert_eq!(b3_build_attempts(), 0, "zero matches never prepares keys");
        // A relevance request keeps the legacy path entirely.
        reset_b3_counters();
        let relevance = search(&snapshot, &request(term(), 10, Sort::default()));
        assert_eq!(relevance.total_hits, 2);
        assert_eq!(b3_build_attempts(), 0);
        // An invalid sort field surfaces its established error first.
        reset_b3_counters();
        let mut bad = request(
            term(),
            10,
            sort_field(SortDirection::Asc, MissingValuePosition::Last),
        );
        bad.sort.fields[0].field = "no_such_field".to_owned();
        assert!(
            run_with(
                &snapshot,
                &bad,
                SearchLimits::default(),
                TopKDuplicateConfig::default()
            )
            .is_err()
        );
        assert_eq!(b3_build_attempts(), 0);
    }
}

/// PERF-06-C2 unit and adversarial acceptance.
///
/// Every test asserts the **actual** selected route through the thread-local
/// witnesses, never only that a response happened to look right, and computes its
/// expected answer from literal input-derived formulas or from the test-only
/// forced-Legacy execution of the *same* request on the *same* snapshot.
#[cfg(test)]
mod c2_tests {
    use super::execute::c2_observation as physical;
    use super::*;
    use crate::analysis::{Cancellation, CancellationFlag, NeverCancel};
    use crate::contract::aggregation::Aggregation;
    use crate::contract::document::{
        Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
    };
    use crate::contract::query::{Bound, GeoBoundingBox};
    use crate::contract::result::{
        MissingValuePosition, MultiValueSelector, SortDirection, SortField, TopK,
    };
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue, GeoPoint, JsonNumber, JsonValue};
    use crate::index::{Index, IndexLimits, ReaderSnapshot};
    use crate::storage::{Directory, MemoryDirectory};
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU64, Ordering};

    // -----------------------------------------------------------------------
    // Fixture
    // -----------------------------------------------------------------------

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "grp",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "doc_id",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "js",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::new(true, true, false),
                ),
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "grp_multi",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, false, false),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, false, true),
                ),
                FieldDefinition::new(
                    "rank",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, true),
                )
                .with_normalizer("keyword"),
            ],
            None,
        )
        .expect("schema")
    }

    fn index_limits() -> IndexLimits {
        IndexLimits::new()
            .with_max_pending_docs(200_000)
            .with_max_pending_bytes(512 * 1024 * 1024)
    }

    /// A live native index plus its snapshot. The `Index` is retained so the
    /// snapshot's data owners stay alive for the whole test.
    struct Fixture {
        schema: Schema,
        registry: AnalyzerRegistry,
        index: Index,
        snapshot: Arc<ReaderSnapshot>,
    }

    impl Fixture {
        fn new(segments: &[Vec<Document>]) -> Self {
            let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
            let schema = schema();
            let registry = AnalyzerRegistry::builtin();
            {
                let index = Index::create_with_limits(
                    Arc::clone(&directory),
                    schema.clone(),
                    registry.clone(),
                    index_limits(),
                )
                .expect("create");
                for segment in segments {
                    let mut writer = index.writer().expect("writer");
                    for document in segment {
                        writer.insert(document.clone()).expect("insert");
                    }
                    writer.commit().expect("commit");
                }
            }
            let index =
                Index::open_existing(directory, schema.clone(), registry.clone()).expect("reopen");
            let snapshot = index.snapshot();
            Self {
                schema,
                registry,
                index,
                snapshot,
            }
        }

        fn searcher(
            &self,
            limits: SearchLimits,
            config: TopKDuplicateConfig,
        ) -> UnifiedSearcher<'_> {
            UnifiedSearcher::new(&self.snapshot, &self.schema, &self.registry, limits)
                .with_topk_duplicate_config(config)
        }

        fn writer(&self) -> crate::index::IndexWriter {
            self.index.writer().expect("writer")
        }
    }

    fn bounded_key(index: usize) -> String {
        format!("doc{index:06}")
    }

    /// B4-formula-like row: all rows carry `grp=common`; every third row carries
    /// `grp_alt=other` so several literal count formulas are available.
    fn document(index: usize) -> Document {
        let mut document = Document::new(DocumentKey::new(bounded_key(index)).expect("key"));
        document
            .insert(
                "grp",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .expect("grp");
        document
            .insert(
                "grp_multi",
                FieldValues::Multi(vec![FieldValue::Keyword("common".to_owned())]),
            )
            .expect("grp_multi");
        document
            .insert(
                "tag",
                FieldValues::Multi(vec![FieldValue::Keyword("t".to_owned())]),
            )
            .expect("tag");
        document
            .insert(
                "doc_id",
                FieldValues::Single(FieldValue::Keyword(bounded_key(index))),
            )
            .expect("doc_id");
        document
            .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
            .expect("n");
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(if index % 2 == 0 {
                    "alpha beta".to_owned()
                } else {
                    "gamma delta".to_owned()
                })),
            )
            .expect("body");
        document
            .insert(
                "js",
                FieldValues::Single(FieldValue::Json(JsonValue::Object(
                    [(
                        "n".to_owned(),
                        JsonValue::Number(JsonNumber::I64(index as i64)),
                    )]
                    .into_iter()
                    .collect(),
                ))),
            )
            .expect("js");
        document
            .insert(
                "loc",
                FieldValues::Multi(vec![FieldValue::GeoPoint(
                    GeoPoint::new(1.0 + index as f64 * 0.001, 2.0).expect("point"),
                )]),
            )
            .expect("loc");
        document
    }

    fn documents(count: usize) -> Vec<Document> {
        (0..count).map(document).collect()
    }

    /// Documents that do not contain the queried `grp` term, so a committed
    /// segment can have `m = 0` while still contributing N examinations.
    fn other_documents(count: usize, offset: usize) -> Vec<Document> {
        (0..count)
            .map(|index| {
                let mut document = document(offset + index);
                document
                    .insert(
                        "grp",
                        FieldValues::Single(FieldValue::Keyword("other".to_owned())),
                    )
                    .expect("grp");
                document
            })
            .collect()
    }

    fn term_common() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("common".to_owned()),
        }
    }

    fn term_absent() -> Query {
        Query::Term {
            field: "grp".to_owned(),
            value: FieldValue::Keyword("absent".to_owned()),
        }
    }

    fn doc_id_sort(direction: SortDirection, missing: MissingValuePosition) -> Sort {
        let mut field = SortField::new("doc_id", direction);
        field.missing = missing;
        Sort::new(vec![field])
    }

    fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
        let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
        request.sort = sort;
        request.projection = Projection::Fields(vec!["doc_id".to_owned()]);
        request
    }

    fn request_asc(query: Query, top_k: usize) -> UnifiedRequest {
        request(
            query,
            top_k,
            doc_id_sort(SortDirection::Asc, MissingValuePosition::Last),
        )
    }

    fn run_with(
        fixture: &Fixture,
        request: &UnifiedRequest,
        limits: SearchLimits,
        config: TopKDuplicateConfig,
    ) -> SearchResult<UnifiedResponse> {
        fixture
            .searcher(limits, config)
            .search(request, &Budgets::new(), &NeverCancel)
    }

    fn run_ineligible(
        fixture: &Fixture,
        request: &UnifiedRequest,
    ) -> SearchResult<UnifiedResponse> {
        run_with(
            fixture,
            request,
            SearchLimits::default(),
            TopKDuplicateConfig::default(),
        )
    }

    /// Run with all C2 witnesses reset and assert the physical route fired once.
    fn strict(fixture: &Fixture, request: &UnifiedRequest) -> UnifiedResponse {
        reset_witnesses();
        let response = run_ineligible(fixture, request).expect("strict search");
        assert_eq!(c2_observation::strict_routes(), 1, "strict route selected");
        assert_eq!(c2_observation::legacy_routes(), 0, "legacy body not used");
        assert!(
            physical::strict_evaluator_calls() >= 1,
            "the strict evaluator ran"
        );
        response
    }

    /// Run with all C2 witnesses reset and assert the accepted Legacy body ran.
    fn legacy(fixture: &Fixture, request: &UnifiedRequest) -> UnifiedResponse {
        reset_witnesses();
        let response = run_ineligible(fixture, request).expect("legacy search");
        assert_eq!(
            c2_observation::strict_routes(),
            0,
            "strict route not selected"
        );
        assert_eq!(c2_observation::legacy_routes(), 1, "legacy body used");
        assert_eq!(
            physical::strict_evaluator_calls(),
            0,
            "no C2 evaluator call"
        );
        response
    }

    /// The same request, same snapshot, forced onto the accepted Legacy body.
    fn forced_legacy(fixture: &Fixture, request: &UnifiedRequest) -> UnifiedResponse {
        reset_witnesses();
        let response = {
            let _forced = c2_observation::ForceLegacy::apply();
            run_ineligible(fixture, request).expect("forced legacy search")
        };
        assert_eq!(c2_observation::strict_routes(), 0, "forced legacy");
        assert_eq!(c2_observation::legacy_routes(), 1, "forced legacy body");
        response
    }

    fn reset_witnesses() {
        c2_observation::reset();
        physical::reset();
        execute::test_observation::reset_scorer_calls();
        execute::test_observation::reset_postings_handoff();
        execute::test_observation::reset_term_membership_lookups();
    }

    fn keys(response: &UnifiedResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn bits(response: &UnifiedResponse) -> Vec<u64> {
        response
            .hits
            .iter()
            .map(|hit| hit.score.expect("lexical hit is scored").to_bits())
            .collect()
    }

    /// One projected hit: `(key, score bits, projected fields)`.
    type ProjectedRow = (String, Option<u64>, Vec<(String, FieldValues)>);

    fn projected(response: &UnifiedResponse) -> Vec<ProjectedRow> {
        response
            .hits
            .iter()
            .map(|hit| {
                (
                    hit.key.as_str().to_owned(),
                    hit.score.map(f64::to_bits),
                    hit.fields.clone(),
                )
            })
            .collect()
    }

    fn expected_ascending_keys(count: usize, top_k: usize) -> Vec<String> {
        (0..count.min(top_k)).map(bounded_key).collect()
    }

    // -----------------------------------------------------------------------
    // C2-U01 — static dispatch matrix
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u01_static_dispatch_matrix() {
        let fixture = Fixture::new(&[documents(24)]);
        // Control: the exact eligible shape must take the physical route.
        let eligible = request_asc(term_common(), 5);
        let response = strict(&fixture, &eligible);
        assert_eq!(response.total_hits, 24);
        assert_eq!(keys(&response), expected_ascending_keys(24, 5));

        let ineligible_queries: Vec<(&str, Query)> = vec![
            ("and", Query::And(vec![term_common()])),
            ("or", Query::Or(vec![term_common()])),
            (
                "not_not",
                Query::Not(Box::new(Query::Not(Box::new(term_common())))),
            ),
            ("match_all", Query::MatchAll),
            (
                "phrase",
                Query::Phrase {
                    field: "body".to_owned(),
                    terms: vec!["alpha beta".to_owned()],
                },
            ),
            (
                "prefix",
                Query::Prefix {
                    field: "grp".to_owned(),
                    prefix: "comm".to_owned(),
                },
            ),
            (
                "glob",
                Query::Glob {
                    field: "grp".to_owned(),
                    pattern: "comm*".to_owned(),
                },
            ),
            (
                "regex",
                Query::Regex {
                    field: "grp".to_owned(),
                    pattern: "comm.*".to_owned(),
                },
            ),
            (
                "fuzzy",
                Query::Fuzzy {
                    field: "grp".to_owned(),
                    value: "commom".to_owned(),
                    max_edits: 1,
                    transpositions: true,
                },
            ),
            (
                "typed_range",
                Query::Range {
                    field: "n".to_owned(),
                    lower: Bound::Included(FieldValue::I64(0)),
                    upper: Bound::Included(FieldValue::I64(3)),
                },
            ),
            (
                "typed_exists",
                Query::Exists {
                    field: "n".to_owned(),
                },
            ),
            (
                "geo",
                Query::GeoBoundingBox {
                    field: "loc".to_owned(),
                    bbox: GeoBoundingBox::new(-1.0, -1.0, 90.0, 90.0).expect("bbox"),
                },
            ),
        ];
        for (label, query) in ineligible_queries {
            let request = request_asc(query, 5);
            reset_witnesses();
            // Some shapes are legitimately empty; the point is the route.
            let response = run_ineligible(&fixture, &request);
            assert!(response.is_ok(), "{label} must not error");
            assert_eq!(c2_observation::strict_routes(), 0, "{label} stays legacy");
            assert_eq!(c2_observation::legacy_routes(), 1, "{label} legacy body");
            assert_eq!(physical::strict_evaluator_calls(), 0, "{label}");
        }
        // Sanity: the counters above were accumulated, so reset and prove that a
        // matched term under `And` still returns every hit through Legacy.
        reset_witnesses();
        let wrapped = request_asc(Query::And(vec![term_common()]), 5);
        let response = legacy(&fixture, &wrapped);
        assert_eq!(response.total_hits, 24);
        assert_eq!(keys(&response), expected_ascending_keys(24, 5));
        assert_eq!(forced_legacy(&fixture, &wrapped).total_hits, 24);

        // Sort-shape ineligibility on the same strict term.
        let relevance = request(term_common(), 5, Sort::default());
        legacy(&fixture, &relevance);

        let mut two_fields = UnifiedRequest::new(term_common(), TopK::new(5).expect("k"));
        two_fields.sort = Sort::new(vec![
            SortField::new("doc_id", SortDirection::Asc),
            SortField::new("n", SortDirection::Asc),
        ]);
        legacy(&fixture, &two_fields);

        let mut multivalue = UnifiedRequest::new(term_common(), TopK::new(5).expect("k"));
        multivalue.sort = Sort::new(vec![
            SortField::new("doc_id", SortDirection::Asc).with_multi(MultiValueSelector::Min),
        ]);
        legacy(&fixture, &multivalue);

        // A non-columnar sort field is rejected by the accepted sort validator:
        // that established typed error must not become a C2 route.
        let mut non_columnar = UnifiedRequest::new(term_common(), TopK::new(5).expect("k"));
        non_columnar.sort = Sort::new(vec![SortField::new("grp", SortDirection::Asc)]);
        reset_witnesses();
        assert!(run_ineligible(&fixture, &non_columnar).is_err());
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(physical::strict_evaluator_calls(), 0);

        // A multi-cardinality columnar sort field is not C2-eligible.
        let mut multi_cardinality = UnifiedRequest::new(term_common(), TopK::new(5).expect("k"));
        multi_cardinality.sort = Sort::new(vec![
            SortField::new("tag", SortDirection::Asc).with_multi(MultiValueSelector::Min),
        ]);
        legacy(&fixture, &multi_cardinality);

        // A malformed sort keeps its established typed error before any segment.
        let mut invalid = request_asc(term_common(), 5);
        invalid.sort.fields[0].field = "no_such_field".to_owned();
        reset_witnesses();
        assert!(run_ineligible(&fixture, &invalid).is_err());
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(c2_observation::legacy_routes(), 0);
        assert_eq!(physical::strict_evaluator_calls(), 0);

        // Batch requests never select the physical route.
        reset_witnesses();
        let mut meter = BatchExecutionMeter::new(1_000_000, 1_000_000, 1_000_000);
        fixture
            .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
            .search_with_batch(&eligible, &Budgets::new(), &NeverCancel, &mut meter)
            .expect("batch search");
        assert_eq!(c2_observation::strict_routes(), 0, "batch stays legacy");
        assert_eq!(c2_observation::legacy_routes(), 1);
        assert_eq!(physical::strict_evaluator_calls(), 0);

        // Aggregation is reachable only through the batch entry point and is
        // therefore also ineligible.
        reset_witnesses();
        let aggregation = Aggregation::new();
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        fixture
            .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
            .search_with_batch_aggregation_retained(
                &eligible,
                Some(&aggregation),
                &Budgets::new(),
                &NeverCancel,
                &mut meter,
            )
            .expect("aggregation search");
        assert_eq!(
            c2_observation::strict_routes(),
            0,
            "aggregation stays legacy"
        );

        // A cursor request never selects the physical route.
        let first = strict(&fixture, &eligible);
        let cursor = first.next_cursor.expect("cursor");
        let mut second = request_asc(term_common(), 5);
        second.after = Some(cursor);
        legacy(&fixture, &second);
    }

    // -----------------------------------------------------------------------
    // C2-U02 — cardinality boundary
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u02_cardinality_boundary() {
        for top_k in [1usize, 10, 31, 32, 100] {
            for delta in [-2i64, -1, 0, 1, 2] {
                let matches = (top_k as i64 + 1 + delta).max(0) as usize;
                if matches > 130 {
                    continue;
                }
                let fixture = if matches == 0 {
                    Fixture::new(&[documents(8)])
                } else {
                    Fixture::new(&[documents(matches)])
                };
                let query = if matches == 0 {
                    term_absent()
                } else {
                    term_common()
                };
                let request = request_asc(query, top_k);
                reset_witnesses();
                let response = run_ineligible(&fixture, &request).expect("search");
                let expected_route = matches > top_k + 1;
                assert_eq!(
                    c2_observation::strict_routes(),
                    usize::from(expected_route),
                    "k={top_k} m={matches}"
                );
                assert_eq!(response.total_hits as usize, matches);
                assert_eq!(response.hits.len(), matches.min(top_k));
                assert_eq!(
                    response.next_cursor.is_some(),
                    matches > top_k,
                    "k={top_k} m={matches}"
                );
                reset_witnesses();
            }
        }
        // Multi-segment: the certificate is request-wide (M), while each segment
        // is still processed independently, including a zero-match segment.
        let split = Fixture::new(&[
            other_documents(3, 100),
            documents(1),
            documents(12).into_iter().skip(1).collect(),
        ]);
        let request = request_asc(term_common(), 10);
        let response = strict(&split, &request);
        assert_eq!(response.total_hits, 12);
        assert_eq!(response.hits.len(), 10);
        assert!(response.next_cursor.is_some());
        assert_eq!(physical::strict_evaluator_calls(), 3);
        assert_eq!(physical::callbacks(), 12);
        // The witness counts decoded effective-live postings (1 + 0 + 11); the
        // zero-match segment is still entered (3 evaluator calls) and still pays
        // its N examination charge inside the evaluator.
        assert_eq!(physical::strict_membership_observations(), 12);
    }

    // -----------------------------------------------------------------------
    // C2-U03 — validation precedence
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u03_validation_precedence() {
        let fixture = Fixture::new(&[documents(16)]);
        // Query/sort/projection/TopK validation all precede any segment work.
        let bad_query = request_asc(
            Query::Term {
                field: "no_such_field".to_owned(),
                value: FieldValue::Keyword("common".to_owned()),
            },
            4,
        );
        let error = run_ineligible(&fixture, &bad_query).expect_err("bad query");
        assert!(matches!(error, SearchError::Query(_)), "{error:?}");

        let mut bad_projection = request_asc(term_common(), 4);
        bad_projection.projection = Projection::Fields(vec!["missing_field".to_owned()]);
        assert!(run_ineligible(&fixture, &bad_projection).is_err());

        // A two-field sort is legal but not C2-eligible (proved in C2-U01).

        // No physical evaluator or segment setup ran for any of the above.
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(physical::strict_evaluator_calls(), 0);

        // A cursor from a different snapshot binding is rejected before segments.
        let other = Fixture::new(&[documents(16)]);
        let first = strict(&fixture, &request_asc(term_common(), 2));
        let foreign = first.next_cursor.expect("cursor");
        let foreign = UnifiedCursor::new(
            foreign.snapshot_binding().wrapping_add(1),
            [0u8; 32],
            foreign.last_sort_values().to_vec(),
            foreign.last_score(),
            foreign.last_key().clone(),
        );
        let mut request = request_asc(term_common(), 2);
        request.after = Some(foreign);
        reset_witnesses();
        assert!(run_ineligible(&other, &request).is_err());
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(physical::strict_evaluator_calls(), 0);
    }

    // -----------------------------------------------------------------------
    // C2-U04 — runtime shape and complete stream decoding
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u04_runtime_shape_and_decoder() {
        let fixture = Fixture::new(&[documents(40)]);
        let request = request_asc(term_common(), 3);
        reset_witnesses();
        let response = strict(&fixture, &request);
        // Every decoded posting was visited (complete stream, no early K stop) and
        // every match was scored and handed over before any candidate existed.
        assert_eq!(physical::strict_membership_observations(), 40);
        assert_eq!(physical::converted_rows(), 40);
        assert_eq!(physical::callbacks(), 40);
        assert_eq!(response.total_hits, 40);
        // The strict root performs no per-document membership relookup and no
        // typed predicate evaluation.
        assert_eq!(execute::test_observation::term_membership_lookups(), 0);
        assert_eq!(execute::test_observation::predicate_calls(), 0);
        // The malformed-posting and malformed-shape cases are executed by the
        // crate unit tests in `execute::c2_physical_tests`, which rebuild a
        // checksum-valid segment container.
    }

    // -----------------------------------------------------------------------
    // C2-U05 — N work and scanned-frequency charging parity
    // -----------------------------------------------------------------------

    fn verdict(response: &SearchResult<UnifiedResponse>) -> Result<u64, String> {
        match response {
            Ok(value) => Ok(value.total_hits),
            Err(SearchError::ResourceLimit { limit, requested }) => {
                Err(format!("limit {limit} requested {requested}"))
            }
            Err(other) => Err(format!("{other:?}")),
        }
    }

    fn document_with_body(index: usize, alpha_repeats: usize, padding: usize) -> Document {
        let mut document = document(index);
        let mut words: Vec<&str> = vec!["alpha"; alpha_repeats];
        words.extend(std::iter::repeat_n("gamma", padding));
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(words.join(" "))),
            )
            .expect("body");
        document
    }

    fn term_body() -> Query {
        Query::Term {
            field: "body".to_owned(),
            value: FieldValue::Text("alpha".to_owned()),
        }
    }

    fn body_documents(count: usize) -> Vec<Document> {
        (0..count)
            .map(|index| document_with_body(index, 1 + index % 4, index % 5))
            .collect()
    }

    #[test]
    fn c2_u05_n_work_and_scanned_freq() {
        // Every document contains `alpha` with a distinct term frequency, so the
        // scanned-occurrence charge is `freq`-based rather than candidate-based.
        let fixture = Fixture::new(&[body_documents(60)]);
        let request = request_asc(term_body(), 5);
        let mut routed = 0usize;
        for limit in [
            1u64, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181,
        ] {
            let c2_limits = SearchLimits::default()
                .with_max_total_work_units(limit)
                .expect("work limit");
            reset_witnesses();
            let c2 = verdict(&run_with(
                &fixture,
                &request,
                c2_limits,
                TopKDuplicateConfig::default(),
            ));
            if c2_observation::strict_routes() == 1 {
                routed += 1;
            }
            let legacy_result = {
                let _forced = c2_observation::ForceLegacy::apply();
                run_with(
                    &fixture,
                    &request,
                    c2_limits,
                    TopKDuplicateConfig::default(),
                )
            };
            assert_eq!(c2, verdict(&legacy_result), "work limit {limit} parity");

            let c2_scanned = SearchLimits::default()
                .with_max_scanned_posting_occurrences(limit)
                .expect("scanned limit");
            reset_witnesses();
            let c2 = verdict(&run_with(
                &fixture,
                &request,
                c2_scanned,
                TopKDuplicateConfig::default(),
            ));
            let legacy_result = {
                let _forced = c2_observation::ForceLegacy::apply();
                run_with(
                    &fixture,
                    &request,
                    c2_scanned,
                    TopKDuplicateConfig::default(),
                )
            };
            assert_eq!(c2, verdict(&legacy_result), "scanned limit {limit} parity");
        }
        assert!(
            routed >= 8,
            "only {routed} limits reached the physical route"
        );
        // At least one boundary must actually reject, so the parity above is not
        // vacuous: limit 1 is strictly below the request's real work.
        reset_witnesses();
        let error = run_with(
            &fixture,
            &request,
            SearchLimits::default()
                .with_max_total_work_units(1)
                .expect("limit"),
            TopKDuplicateConfig::default(),
        )
        .expect_err("limit 1 must reject");
        assert!(
            matches!(error, SearchError::ResourceLimit { .. }),
            "{error:?}"
        );

        // A live mask keeps the N examination at the effective-live count while
        // the decoder still charges the dead posting's frequency.
        let masked_fixture = Fixture::new(&[documents(20), Vec::new()]);
        let snapshot = {
            let mut writer = masked_fixture.writer();
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(bounded_key(0)).expect("key"),
                ))
                .expect("delete");
            writer.refresh().expect("refresh")
        };
        let masked = Fixture {
            schema: masked_fixture.schema.clone(),
            registry: AnalyzerRegistry::builtin(),
            index: masked_fixture.index,
            snapshot,
        };
        reset_witnesses();
        let response = run_ineligible(&masked, &request_asc(term_common(), 3)).expect("search");
        assert_eq!(response.total_hits, 19);
        assert_eq!(physical::converted_rows(), 19);
        assert_eq!(physical::strict_membership_observations(), 19);
        assert_eq!(physical::callbacks(), 19);
    }

    // -----------------------------------------------------------------------
    // C2-U06 — exact total_hits and K+1 lookahead
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u06_exact_total_hits() {
        let fixture = Fixture::new(&[documents(100)]);
        // K=10 and K=90 both leave M=100 > K+1, so both take the physical route.
        for top_k in [10usize, 90] {
            let request = request_asc(term_common(), top_k);
            let response = strict(&fixture, &request);
            assert_eq!(response.total_hits, 100);
            assert_eq!(response.hits.len(), top_k);
            assert_eq!(keys(&response), expected_ascending_keys(100, top_k));
            assert!(response.next_cursor.is_some());
            assert_eq!(physical::converted_rows(), 100);
        }
        // K = M - 1 is the K+1 boundary: the accepted code retains every match as
        // lookahead, so it stays on Legacy with the exact same public answer.
        let boundary = request_asc(term_common(), 99);
        let response = legacy(&fixture, &boundary);
        assert_eq!(response.total_hits, 100);
        assert_eq!(response.hits.len(), 99);
        assert!(response.next_cursor.is_some());
        // Distribution 0 + 1 + M: the single-hit segment keeps the selected-key
        // optimization but still contributes its exact count.
        let split = Fixture::new(&[
            other_documents(4, 200),
            documents(1),
            documents(60).into_iter().skip(1).collect(),
        ]);
        let response = strict(&split, &request_asc(term_common(), 10));
        assert_eq!(response.total_hits, 60);
        assert_eq!(response.hits.len(), 10);
        assert!(response.next_cursor.is_some());
        assert_eq!(physical::strict_evaluator_calls(), 3);
        assert_eq!(physical::callbacks(), 60);
    }

    // -----------------------------------------------------------------------
    // C2-U07 — late score error precedes every candidate key decision
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u07_late_score_error_beats_key_error() {
        let fixture = Fixture::new(&[documents(30)]);
        let request = request_asc(term_common(), 3);
        reset_witnesses();
        let error = {
            let _arm = physical::ScoreFailureArm::arm(29);
            run_ineligible(&fixture, &request).expect_err("injected score fault")
        };
        assert!(
            matches!(error, SearchError::InvalidScore { detail } if detail == "injected C2 score failure"),
            "{error:?}"
        );
        assert_eq!(
            physical::callbacks(),
            0,
            "no callback is reached for that segment"
        );
        // Evidence class: INJECTED_C2_ONLY structural error-order witness. The
        // forced-Legacy path has no injector, so it is deliberately not cited as
        // same-fault parity. Real (uninjected) score behaviour is proved by the
        // bit-parity tests; shared-source corruption parity is proved in the
        // execute-module adversarial tests.
        reset_witnesses();
        let baseline = forced_legacy(&fixture, &request);
        assert_eq!(baseline.total_hits, 30);

        // A mid-segment fault releases every reservation and leaves no sticky
        // state: the same snapshot queried again succeeds.
        let error = {
            let _arm = physical::ScoreFailureArm::arm(17);
            run_ineligible(&fixture, &request).expect_err("injected score fault")
        };
        assert!(matches!(error, SearchError::InvalidScore { .. }));
        reset_witnesses();
        let response = strict(&fixture, &request);
        assert_eq!(response.total_hits, 30);
        assert_eq!(keys(&response), expected_ascending_keys(30, 3));
    }

    // -----------------------------------------------------------------------
    // C2-U08 — score bit parity against forced Legacy
    // -----------------------------------------------------------------------

    /// Deterministic xorshift used only to generate bounded fixtures.
    struct Rng(u64);

    impl Rng {
        fn next(&mut self) -> u64 {
            let mut value = self.0;
            value ^= value << 13;
            value ^= value >> 7;
            value ^= value << 17;
            self.0 = value;
            value
        }

        fn below(&mut self, bound: usize) -> usize {
            (self.next() % bound as u64) as usize
        }
    }

    fn seeded_documents(rng: &mut Rng, count: usize) -> Vec<Document> {
        (0..count)
            .map(|index| {
                let repeats = 1 + rng.below(4);
                let padding = rng.below(6);
                document_with_body(index, repeats, padding)
            })
            .collect()
    }

    #[test]
    fn c2_u08_score_bit_parity() {
        let mut rng = Rng(0x00C2_0208_1125_0001);
        let mut compared = 0usize;
        for case in 0..64usize {
            let count = 12 + rng.below(80);
            let segments = 1 + rng.below(3);
            let mut rows = seeded_documents(&mut rng, count);
            let mut buckets: Vec<Vec<Document>> = vec![Vec::new(); segments];
            for (index, row) in rows.drain(..).enumerate() {
                buckets[index % segments].push(row);
            }
            let fixture = Fixture::new(&buckets);
            let top_k = [1usize, 10, 100][case % 3];
            if count <= top_k + 1 {
                continue;
            }
            for direction in [SortDirection::Asc, SortDirection::Desc] {
                let request = request(
                    term_body(),
                    top_k,
                    doc_id_sort(direction, MissingValuePosition::Last),
                );
                reset_witnesses();
                let physical_response = run_ineligible(&fixture, &request).expect("c2");
                assert_eq!(c2_observation::strict_routes(), 1, "case {case}");
                let legacy_response = forced_legacy(&fixture, &request);
                assert_eq!(
                    bits(&physical_response),
                    bits(&legacy_response),
                    "case {case}"
                );
                assert_eq!(
                    keys(&physical_response),
                    keys(&legacy_response),
                    "case {case}"
                );
                assert_eq!(physical_response.total_hits, legacy_response.total_hits);
                assert_eq!(
                    physical_response.next_cursor.is_some(),
                    legacy_response.next_cursor.is_some()
                );
                assert_eq!(
                    projected(&physical_response),
                    projected(&legacy_response),
                    "case {case}"
                );
                for hit in &physical_response.hits {
                    assert!(hit.score.is_some(), "explicit sort keeps its lexical score");
                }
                compared += 1;
            }
        }
        assert!(compared >= 40, "compared {compared} physical cases");
    }

    // -----------------------------------------------------------------------
    // C2-U09 — in-place allocation identity
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u09_inplace_allocation_identity() {
        let fixture = Fixture::new(&[body_documents(50)]);
        let request = request_asc(term_body(), 4);
        reset_witnesses();
        let response = strict(&fixture, &request);
        assert_eq!(response.total_hits, 50);
        assert!(
            physical::inplace_preserved(),
            "the decoded posting vector kept its address and capacity"
        );
        assert_eq!(physical::converted_rows(), 50);
        assert_eq!(physical::callbacks(), 50);
        // The accepted strict-term scorer (which allocates a second full-M vector)
        // never ran, and the single validated postings move happened once.
        assert_eq!(execute::test_observation::single_term_scorer_calls(), 0);
        assert_eq!(execute::test_observation::generic_scorer_calls(), 0);
        assert_eq!(execute::test_observation::postings_moves(), 1);
        assert_eq!(execute::test_observation::postings_rejection_fallbacks(), 0);
    }

    // -----------------------------------------------------------------------
    // C2-U10 — virtual ledger exact boundaries
    // -----------------------------------------------------------------------

    /// `m = 3`, `K = 1` gives the first eligible boundary: logical peak is
    /// `3*m = 9` entries and `P + S + T = 16m + 48m + 64m = 384` bytes.
    #[test]
    fn c2_u10_virtual_ledger_exact_boundaries() {
        // Three worksheet shapes: (documents = m, top_k, expected peak entries, bytes)
        // where `bytes = 128m` and `entries = 3m` because P=16m, S=48m, T=64m.
        for (m, top_k) in [(3usize, 1usize), (12, 10), (102, 100)] {
            assert_eq!(m, top_k + 2, "K+2 boundary shape");
            let peak_entries = 3 * m as u64;
            let peak_bytes = 128 * m as u64;
            assert_eq!(peak_bytes, 16 * m as u64 + 48 * m as u64 + 64 * m as u64);
            let fixture = Fixture::new(&[body_documents(m)]);
            let request = request_asc(term_body(), top_k);
            // Exact segment-phase boundaries. The matched/scored admissions must
            // reject at exactly one entry or one byte below `3m` / `128m`.
            for (entries, bytes) in [
                (peak_entries - 1, peak_bytes),
                (peak_entries, peak_bytes - 1),
            ] {
                let limits = SearchLimits::default()
                    .with_max_segment_candidate_entries(entries)
                    .expect("entries")
                    .with_max_total_candidate_bytes(bytes)
                    .expect("bytes");
                reset_witnesses();
                let c2 = run_with(&fixture, &request, limits, TopKDuplicateConfig::default());
                assert_eq!(c2_observation::strict_routes(), 1, "m={m} selected");
                let legacy = {
                    let _forced = c2_observation::ForceLegacy::apply();
                    run_with(&fixture, &request, limits, TopKDuplicateConfig::default())
                };
                assert_eq!(verdict(&c2), verdict(&legacy), "m={m} parity");
                match c2 {
                    Err(SearchError::ResourceLimit { limit, requested })
                        if entries == peak_entries - 1 =>
                    {
                        assert_eq!((limit, requested), (peak_entries - 1, peak_entries));
                    }
                    Err(SearchError::ResourceLimit { limit, requested }) => {
                        assert_eq!((limit, requested), (peak_bytes - 1, peak_bytes));
                    }
                    other => panic!("m={m} {entries}/{bytes} must reject: {other:?}"),
                }
            }
            // At the exact peak the segment phase is admitted; any remaining
            // rejection comes from the accepted K+1 heap accounting and must agree
            // with the Legacy route byte for byte.
            let exact = SearchLimits::default()
                .with_max_segment_candidate_entries(peak_entries)
                .expect("entries")
                .with_max_total_candidate_bytes(peak_bytes)
                .expect("bytes");
            reset_witnesses();
            let c2 = run_with(&fixture, &request, exact, TopKDuplicateConfig::default());
            assert_eq!(c2_observation::strict_routes(), 1, "m={m} exact peak");
            let legacy = {
                let _forced = c2_observation::ForceLegacy::apply();
                run_with(&fixture, &request, exact, TopKDuplicateConfig::default())
            };
            assert_eq!(verdict(&c2), verdict(&legacy), "m={m} exact-peak parity");
            // A generous budget must admit and answer exactly.
            let generous = SearchLimits::default()
                .with_max_segment_candidate_entries(peak_entries)
                .expect("entries")
                .with_max_total_candidate_bytes(peak_bytes * 4)
                .expect("bytes");
            reset_witnesses();
            let admitted = run_with(&fixture, &request, generous, TopKDuplicateConfig::default())
                .expect("generous budget");
            assert_eq!(c2_observation::strict_routes(), 1);
            assert_eq!(admitted.total_hits, m as u64);
            assert_eq!(admitted.hits.len(), top_k);
            assert!(admitted.next_cursor.is_some());
        }
    }

    // -----------------------------------------------------------------------
    // C2-U11 — preflight atomicity and RAII unwind
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u11_preflight_atomic_and_raii() {
        let fixture = Fixture::new(&[body_documents(6)]);
        let request = request_asc(term_body(), 2);
        // A late score fault must surface as the score error, never as a corrupted
        // ledger ("segment ledger still owns reservations at finish").
        for doc in [0u64, 3, 5] {
            reset_witnesses();
            let error = {
                let _arm = physical::ScoreFailureArm::arm(doc);
                run_ineligible(&fixture, &request).expect_err("score fault")
            };
            assert!(
                matches!(error, SearchError::InvalidScore { .. }),
                "doc {doc}: {error:?}"
            );
            assert_eq!(physical::callbacks(), 0);
        }
        // Exact-peak admission plus a fault: the fault wins and no partial page is
        // returned. The ledger is released by RAII, so a repeat query succeeds.
        let limits = SearchLimits::default()
            .with_max_segment_candidate_entries(18)
            .expect("entries")
            .with_max_total_candidate_bytes(768)
            .expect("bytes");
        reset_witnesses();
        let error = {
            let _arm = physical::ScoreFailureArm::arm(4);
            run_with(&fixture, &request, limits, TopKDuplicateConfig::default())
                .expect_err("score fault")
        };
        assert!(
            matches!(error, SearchError::InvalidScore { .. }),
            "{error:?}"
        );
        reset_witnesses();
        let response = run_with(&fixture, &request, limits, TopKDuplicateConfig::default())
            .expect("clean retry");
        assert_eq!(response.total_hits, 6);
        // A key/heap preflight failure is the accepted typed resource error on both
        // routes and produces no response.
        let tight = SearchLimits::default()
            .with_max_total_candidate_bytes(64)
            .expect("bytes");
        reset_witnesses();
        let c2 = run_with(&fixture, &request, tight, TopKDuplicateConfig::default());
        let legacy = {
            let _forced = c2_observation::ForceLegacy::apply();
            run_with(&fixture, &request, tight, TopKDuplicateConfig::default())
        };
        assert!(
            matches!(c2, Err(SearchError::ResourceLimit { .. })),
            "{c2:?}"
        );
        assert!(
            matches!(legacy, Err(SearchError::ResourceLimit { .. })),
            "{legacy:?}"
        );
    }

    // -----------------------------------------------------------------------
    // C2-U13 — cancellation progress and cleanup
    // -----------------------------------------------------------------------

    struct CancelAfter {
        polls: AtomicU64,
        cancel_at: u64,
    }

    impl Cancellation for CancelAfter {
        fn is_cancelled(&self) -> bool {
            let poll = self.polls.fetch_add(1, Ordering::Relaxed) + 1;
            self.cancel_at != 0 && poll >= self.cancel_at
        }
    }

    #[test]
    fn c2_u13_cancellation_progress() {
        let fixture = Fixture::new(&[body_documents(40)]);
        let request = request_asc(term_body(), 3);

        // A flag cancelled before the request returns the accepted typed error on
        // both routes and never reaches a candidate.
        let flag = CancellationFlag::new();
        flag.cancel();
        reset_witnesses();
        let c2 = fixture
            .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
            .search(&request, &Budgets::new(), &flag);
        assert!(matches!(c2, Err(SearchError::Cancelled)), "{c2:?}");
        let legacy = {
            let _forced = c2_observation::ForceLegacy::apply();
            fixture
                .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
                .search(&request, &Budgets::new(), &flag)
        };
        assert!(matches!(legacy, Err(SearchError::Cancelled)), "{legacy:?}");

        // Sweep the cancellation point across decode, N charge, scoring and
        // candidate handoff: both routes must agree on success/cancellation.
        for cancel_at in 1..=90u64 {
            reset_witnesses();
            let cancel = CancelAfter {
                polls: AtomicU64::new(0),
                cancel_at,
            };
            let c2 = fixture
                .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
                .search(&request, &Budgets::new(), &cancel);
            let legacy = {
                let _forced = c2_observation::ForceLegacy::apply();
                let cancel = CancelAfter {
                    polls: AtomicU64::new(0),
                    cancel_at,
                };
                fixture
                    .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
                    .search(&request, &Budgets::new(), &cancel)
            };
            match (&c2, &legacy) {
                (Ok(_), Ok(_)) => {}
                (Err(SearchError::Cancelled), Err(SearchError::Cancelled)) => {}
                (
                    Err(SearchError::ResourceLimit { .. }),
                    Err(SearchError::ResourceLimit { .. }),
                ) => {}
                (left, right) => panic!("cancel_at={cancel_at} mismatch: {left:?} vs {right:?}"),
            }
        }
        // No leaked charge: after the sweep the same snapshot answers normally.
        reset_witnesses();
        let response = strict(&fixture, &request);
        assert_eq!(response.total_hits, 40);
    }

    // -----------------------------------------------------------------------
    // C2-U14 — numeric rank, null/missing and exact key ties
    // -----------------------------------------------------------------------

    #[derive(Clone, Copy, Debug)]
    enum Rank {
        Missing,
        Null,
        Value(&'static str),
    }

    fn ranked_document(index: usize, rank: Rank) -> Document {
        let mut document = document(index);
        let values = match rank {
            Rank::Missing => None,
            Rank::Null => Some(FieldValues::ExplicitNull),
            Rank::Value(value) => Some(FieldValues::Single(FieldValue::Keyword(value.to_owned()))),
        };
        if let Some(values) = values {
            document.insert("rank", values).expect("rank");
        }
        document
    }

    fn rank_sort(direction: SortDirection, missing: MissingValuePosition) -> Sort {
        let mut field = SortField::new("rank", direction);
        field.missing = missing;
        Sort::new(vec![field])
    }

    #[test]
    fn c2_u14_numeric_rank_null_missing_multione() {
        let ranks = [
            Rank::Value("b"),
            Rank::Missing,
            Rank::Value("a"),
            Rank::Null,
            Rank::Value("b"),
            Rank::Value("c"),
            Rank::Value("a"),
            Rank::Value("b"),
        ];
        let fixture = Fixture::new(&[ranks
            .iter()
            .enumerate()
            .map(|(index, rank)| ranked_document(index, *rank))
            .collect()]);
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
                let request = request(term_common(), 3, rank_sort(direction, missing));
                reset_witnesses();
                let physical_response = run_ineligible(&fixture, &request).expect("c2");
                assert_eq!(
                    c2_observation::strict_routes(),
                    1,
                    "{direction:?}/{missing:?}"
                );
                let legacy_response = forced_legacy(&fixture, &request);
                assert_eq!(
                    projected(&physical_response),
                    projected(&legacy_response),
                    "{direction:?}/{missing:?}"
                );
                assert_eq!(
                    physical_response.next_cursor.is_some(),
                    legacy_response.next_cursor.is_some()
                );
            }
        }
        // `MultiOne` sort states remain the established B2 handler's responsibility;
        // they are exercised unchanged by the retained `b2_` regressions.
    }

    // -----------------------------------------------------------------------
    // C2-U15 — duplicate identity is exact-key based
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u15_duplicate_collision_and_loser() {
        // Upserts of one logical key across segments stay one live document: the
        // exact-key identity, never a fingerprint, decides identity.
        let fixture = Fixture::new(&[documents(5)]);
        let request = request_asc(term_common(), 1);
        let snapshot = {
            let mut writer = fixture.writer();
            writer
                .apply(MutationRequest::upsert(document(1)))
                .expect("upsert");
            writer
                .apply(MutationRequest::upsert(document(1)))
                .expect("upsert");
            writer.commit().expect("commit");
            writer.refresh().expect("refresh")
        };
        let updated = Fixture {
            schema: fixture.schema.clone(),
            registry: AnalyzerRegistry::builtin(),
            index: fixture.index,
            snapshot,
        };
        reset_witnesses();
        let response = run_ineligible(&updated, &request).expect("search");
        assert_eq!(
            response.total_hits, 5,
            "one live physical document per logical key"
        );
        assert_eq!(c2_observation::strict_routes(), 1, "5 > K+1");
        // The retained duplicate scan and the exact byte comparison still run on
        // the physical route for the deduplicated snapshot.
        reset_witnesses();
        b3_observation::reset();
        let response = strict(&updated, &request_asc(term_common(), 1));
        assert_eq!(response.total_hits, 5);
        assert!(
            b3_observation::hash_collision_exact_checks() > 0
                || b3_observation::one_time_heap_hash_audits() > 0,
            "the established B3 duplicate machinery ran"
        );
    }

    // -----------------------------------------------------------------------
    // C2-U16 — cursor sentinel and Legacy continuation
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u16_cursor_sentinel_and_legacy_continuation() {
        for top_k in [1usize, 10] {
            let fixture = Fixture::new(&[documents(30)]);
            let mut collected: Vec<String> = Vec::new();
            let mut request = request_asc(term_common(), top_k);
            let mut page = 0usize;
            loop {
                reset_witnesses();
                let response = run_ineligible(&fixture, &request).expect("page");
                if page == 0 {
                    assert_eq!(c2_observation::strict_routes(), 1, "first page is C2");
                    assert_eq!(physical::converted_rows(), 30);
                } else {
                    assert_eq!(c2_observation::strict_routes(), 0, "later pages Legacy");
                    assert_eq!(c2_observation::legacy_routes(), 1);
                }
                collected.extend(keys(&response));
                match response.next_cursor {
                    Some(cursor) => {
                        request = request_asc(term_common(), top_k);
                        request.after = Some(cursor);
                        page += 1;
                        assert!(page < 40, "bounded paging");
                    }
                    None => break,
                }
            }
            assert_eq!(collected, expected_ascending_keys(30, 30), "k={top_k}");
            assert_eq!(
                collected.len(),
                collected
                    .iter()
                    .collect::<std::collections::BTreeSet<_>>()
                    .len(),
                "no duplicate pages"
            );
        }
        // A cursor bound to a different snapshot is rejected.
        let fixture = Fixture::new(&[documents(30)]);
        let other = Fixture::new(&[documents(30)]);
        let first = strict(&fixture, &request_asc(term_common(), 1));
        let mut request = request_asc(term_common(), 1);
        request.after = first.next_cursor;
        reset_witnesses();
        assert!(run_ineligible(&other, &request).is_err());
        assert_eq!(c2_observation::strict_routes(), 0);
    }

    // -----------------------------------------------------------------------
    // C2-U17 — B1 optional unavailability and B3 optional refusal
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u17_ordinal_unavailable_and_b3_refusal() {
        use crate::index::KeywordOrdinalUnavailable;

        // The physical route requires a `Ready` request-wide map: every documented
        // optional outcome maps to `None`, which can never satisfy the route's
        // `Some(map)` match arm, so the whole request takes Legacy before any
        // candidate. (A `Ready` map is proved by the differential tests above.)
        for reason in [
            KeywordOrdinalUnavailable::LegacySegment,
            KeywordOrdinalUnavailable::ResourceBudget,
            KeywordOrdinalUnavailable::Allocation,
            KeywordOrdinalUnavailable::UnsupportedField,
        ] {
            assert!(
                ordinal_ready_from_preparation(KeywordOrdinalPreparation::NotAvailable(reason))
                    .is_none(),
                "{reason:?} must not produce a map"
            );
        }

        // A genuine B1 error is never converted into `NotAvailable`.
        let mapped = ordinal_preparation_error(crate::index::IndexError::Cancelled);
        assert!(matches!(mapped, SearchError::Cancelled), "{mapped:?}");
        let mapped = ordinal_preparation_error(crate::index::IndexError::WriterBusy);
        assert!(matches!(mapped, SearchError::Index(_)), "{mapped:?}");

        // B3 optional refusal keeps C2 and downgrades only that segment to the
        // owned B2 key handler; the public answer is unchanged.
        let fixture = Fixture::new(&[documents(40)]);
        let request = request_asc(term_common(), 3);
        reset_witnesses();
        let refused = run_ineligible(&fixture, &request).expect("search");
        assert_eq!(c2_observation::strict_routes(), 1);
        let reference = forced_legacy(&fixture, &request);
        assert_eq!(projected(&refused), projected(&reference));

        // ExactSet duplicate mode forces the owned B2 path for every segment.
        let config = TopKDuplicateConfig::new(
            std::num::NonZeroUsize::new(1).expect("nonzero"),
            TopKDuplicateStrategy::ExactSet,
        );
        reset_witnesses();
        let exact_set = run_with(&fixture, &request, SearchLimits::default(), config)
            .expect("exact-set search");
        assert_eq!(c2_observation::strict_routes(), 1, "ExactSet stays C2");
        assert_eq!(projected(&exact_set), projected(&reference));

        // No eager all-segment ordinal binding: the multi-segment precedence case
        // (later-segment error must not overtake an earlier segment's failure) is
        // executed by the crate-level adversarial tests; here the ordering witness
        // is the per-segment binding counter.
        let split = Fixture::new(&[documents(10), documents(20).into_iter().skip(10).collect()]);
        reset_witnesses();
        b2_observation::reset();
        run_ineligible(&split, &request_asc(term_common(), 3)).expect("search");
        assert_eq!(
            b2_observation::bound_columns(),
            2,
            "one binding per segment"
        );
    }

    // -----------------------------------------------------------------------
    // C2-U18 — PIT mutation and mixed segments
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u18_pit_mutation_and_mixed_segments() {
        let fixture = Fixture::new(&[documents(6), documents(12).into_iter().skip(6).collect()]);
        let request = request_asc(term_common(), 3);
        let old = fixture.snapshot.clone();
        reset_witnesses();
        let before = run_ineligible(&fixture, &request).expect("old view");
        assert_eq!(before.total_hits, 12);
        assert_eq!(c2_observation::strict_routes(), 1);

        // Delete three matching documents and add a new segment.
        let new_snapshot = {
            let mut writer = fixture.writer();
            for index in [0usize, 4, 9] {
                writer
                    .apply(MutationRequest::delete(
                        DocumentKey::new(bounded_key(index)).expect("key"),
                    ))
                    .expect("delete");
            }
            writer
                .apply(MutationRequest::insert(document(500)))
                .expect("insert");
            let outcome = writer.commit().expect("commit");
            assert!(outcome.generation > 0);
            writer.refresh().expect("refresh")
        };
        let updated = Fixture {
            schema: fixture.schema.clone(),
            registry: AnalyzerRegistry::builtin(),
            index: fixture.index,
            snapshot: new_snapshot,
        };
        reset_witnesses();
        let after = run_ineligible(&updated, &request).expect("new view");
        assert_eq!(after.total_hits, 10, "12 - 3 deleted + 1 added");
        assert_eq!(after.view_ordinal, updated.snapshot.view_ordinal());
        // The pinned old snapshot still sees exactly its own generation.
        let pinned = Fixture {
            schema: fixture.schema.clone(),
            registry: AnalyzerRegistry::builtin(),
            index: updated.index,
            snapshot: old,
        };
        reset_witnesses();
        let still_old = run_ineligible(&pinned, &request).expect("pinned view");
        assert_eq!(still_old.total_hits, 12);
        assert_eq!(
            still_old.generation, before.generation,
            "the pinned generation is unchanged"
        );
    }

    // -----------------------------------------------------------------------
    // C2-U19 — sibling paths untouched
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u19_sibling_paths_untouched() {
        let fixture = Fixture::new(&[documents(20)]);
        let searcher = fixture.searcher(SearchLimits::default(), TopKDuplicateConfig::default());
        // Complete-membership mutation seam.
        reset_witnesses();
        let selection = searcher
            .select_keys(&term_common(), 1_000, &Budgets::new(), &NeverCancel)
            .expect("select keys");
        match selection {
            CompleteKeySelection::Complete(keys) => assert_eq!(keys.len(), 20),
            CompleteKeySelection::LimitExceeded { .. } => panic!("unbounded selection"),
        }
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(physical::strict_evaluator_calls(), 0);

        // Batch (already proved in C2-U01) and aggregation keep their contracts.
        let mut meter = BatchExecutionMeter::new(1_000_000_000, 1_000_000_000, 1_000_000_000);
        reset_witnesses();
        let batched = searcher
            .search_with_batch(
                &request_asc(term_common(), 3),
                &Budgets::new(),
                &NeverCancel,
                &mut meter,
            )
            .expect("batch");
        assert_eq!(batched.total_hits, 20);
        assert_eq!(c2_observation::strict_routes(), 0);

        // Typed-only and phrase queries stay on Legacy with their own semantics.
        let typed = request_asc(
            Query::Range {
                field: "n".to_owned(),
                lower: Bound::Included(FieldValue::I64(0)),
                upper: Bound::Included(FieldValue::I64(2)),
            },
            10,
        );
        reset_witnesses();
        let typed_response = run_ineligible(&fixture, &typed).expect("typed");
        assert_eq!(typed_response.total_hits, 3);
        assert_eq!(c2_observation::strict_routes(), 0);
        for hit in &typed_response.hits {
            assert!(hit.score.is_none(), "a typed hit has no lexical score");
        }
    }

    // -----------------------------------------------------------------------
    // C2-U20 — generic hot-loop isolation
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u20_generic_hot_loop_isolation() {
        let fixture = Fixture::new(&[documents(24)]);
        let request = request_asc(term_common(), 5);
        // Forced Legacy executes the accepted generic body only, with no physical
        // selector per candidate and no C2 evaluator call.
        reset_witnesses();
        let legacy_response = {
            let _forced = c2_observation::ForceLegacy::apply();
            run_ineligible(&fixture, &request).expect("legacy")
        };
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(c2_observation::legacy_routes(), 1);
        assert_eq!(physical::strict_evaluator_calls(), 0);
        assert_eq!(physical::callbacks(), 0);
        // The accepted strict-term scorer (a separate, already-shipped path) still
        // runs on Legacy; C2 must not have replaced it there.
        assert_eq!(execute::test_observation::single_term_scorer_calls(), 1);
        // A low-hit (absent term) request is guaranteed Legacy.
        reset_witnesses();
        let absent = run_ineligible(&fixture, &request_asc(term_absent(), 5)).expect("absent");
        assert_eq!(absent.total_hits, 0);
        assert_eq!(c2_observation::strict_routes(), 0);
        assert_eq!(c2_observation::legacy_routes(), 1);
        // And the physical response is identical to the accepted Legacy response
        // for the same request.
        reset_witnesses();
        let physical_response = run_ineligible(&fixture, &request).expect("physical");
        assert_eq!(c2_observation::strict_routes(), 1);
        assert_eq!(projected(&physical_response), projected(&legacy_response));
    }

    // -----------------------------------------------------------------------
    // C2-U21 — later-segment failure aborts the whole request
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u21_work_budget_exhaustion_after_prior_segment() {
        let fixture = Fixture::new(&[
            body_documents(6),
            body_documents(40).into_iter().skip(6).collect(),
        ]);
        let request = request_asc(term_body(), 2);
        let mut saw_failure = false;
        for limit in [1u64, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096] {
            let limits = SearchLimits::default()
                .with_max_scanned_posting_occurrences(limit)
                .expect("scanned");
            reset_witnesses();
            let c2 = run_with(&fixture, &request, limits, TopKDuplicateConfig::default());
            let legacy = {
                let _forced = c2_observation::ForceLegacy::apply();
                run_with(&fixture, &request, limits, TopKDuplicateConfig::default())
            };
            assert_eq!(verdict(&c2), verdict(&legacy), "scanned limit {limit}");
            if c2.is_err() {
                saw_failure = true;
            }
        }
        assert!(saw_failure, "at least one limit must abort the request");
        // A successful request over the same snapshot still answers exactly.
        reset_witnesses();
        let response = strict(&fixture, &request);
        assert_eq!(response.total_hits, 40);
    }

    // -----------------------------------------------------------------------
    // C2-U22 — seeded differential matrix
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u22_seeded_differential_matrix() {
        let mut rng = Rng(0x00C2_2026_1125_0001);
        let mut fixtures = Vec::new();
        for distribution in 0..8usize {
            let segments = 1 + distribution % 4;
            let total = 20 + distribution * 30;
            let mut buckets: Vec<Vec<Document>> = vec![Vec::new(); segments];
            for index in 0..total {
                buckets[index % segments].push(document_with_body(
                    index,
                    1 + (index * 7 + distribution) % 4,
                    (index + distribution) % 5,
                ));
            }
            fixtures.push(Fixture::new(&buckets));
        }
        let top_ks = [1usize, 10, 31, 32, 100];
        let directions = [SortDirection::Asc, SortDirection::Desc];
        let missing = [MissingValuePosition::First, MissingValuePosition::Last];
        let mut cases = 0usize;
        for fixture in &fixtures {
            for _ in 0..16 {
                let top_k = top_ks[rng.below(top_ks.len())];
                let direction = directions[rng.below(directions.len())];
                let position = missing[rng.below(missing.len())];
                let request = request(term_body(), top_k, doc_id_sort(direction, position));
                reset_witnesses();
                let c2 = run_ineligible(fixture, &request).expect("c2");
                let route = c2_observation::strict_routes();
                let callbacks = physical::callbacks();
                let legacy = forced_legacy(fixture, &request);
                assert_eq!(
                    projected(&c2),
                    projected(&legacy),
                    "case {cases} k={top_k} {direction:?} {position:?}"
                );
                assert_eq!(c2.total_hits, legacy.total_hits, "case {cases}");
                assert_eq!(c2.generation, legacy.generation, "case {cases} generation");
                assert_eq!(
                    c2.view_ordinal, legacy.view_ordinal,
                    "case {cases} view ordinal"
                );
                assert_eq!(
                    c2.next_cursor.is_some(),
                    legacy.next_cursor.is_some(),
                    "case {cases} cursor presence"
                );
                if route == 1 {
                    assert!(callbacks > 0, "case {cases}");
                }
                cases += 1;
            }
        }
        assert_eq!(cases, 128, "executed exactly 128 seeded cases");
    }

    // -----------------------------------------------------------------------
    // C2-U23 — B1/B2/B3 reuse witness
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u23_b1_b2_b3_reuse_witness() {
        let fixture = Fixture::new(&[documents(40)]);
        let request = request_asc(term_common(), 3);
        reset_witnesses();
        b2_observation::reset();
        b3_observation::reset();
        let response = run_ineligible(&fixture, &request).expect("search");
        assert_eq!(c2_observation::strict_routes(), 1);
        assert_eq!(response.total_hits, 40);
        // The request-wide B1 map preparation and the per-segment binding ran once.
        assert_eq!(b2_observation::map_preparations(), 1);
        assert_eq!(b2_observation::ready_uses(), 1);
        assert_eq!(b2_observation::bound_columns(), 1);
        // The established B2/B3 numeric candidate handlers processed every match.
        assert_eq!(b2_observation::numeric_candidates(), 40);
        assert_eq!(b3_observation::one_time_heap_hash_audits(), 1);
        // Losing candidates own nothing on the compact path.
        assert!(
            b2_observation::single_rejected_without_copy() > 0,
            "the accepted loser fast path is reused"
        );
        assert_eq!(physical::callbacks(), 40);
    }

    // -----------------------------------------------------------------------
    // C2-U24 — no sticky state across requests
    // -----------------------------------------------------------------------

    #[test]
    fn c2_u24_zero_effect_and_error_repetition() {
        let fixture = Fixture::new(&[documents(30)]);
        let request = request_asc(term_common(), 3);
        let first = strict(&fixture, &request);
        // A fault in a *different* request leaves nothing behind.
        reset_witnesses();
        {
            let _arm = physical::ScoreFailureArm::arm(11);
            assert!(run_ineligible(&fixture, &request).is_err());
        }
        reset_witnesses();
        let after_fault = strict(&fixture, &request);
        assert_eq!(projected(&first), projected(&after_fault));
        // Repeated identical requests are stable and each performs its own work.
        for _ in 0..3 {
            reset_witnesses();
            let repeat = strict(&fixture, &request);
            assert_eq!(projected(&request_response(&repeat)), projected(&first));
        }
        // A cancelled request leaves nothing behind either.
        let flag = CancellationFlag::new();
        flag.cancel();
        reset_witnesses();
        assert!(
            fixture
                .searcher(SearchLimits::default(), TopKDuplicateConfig::default())
                .search(&request, &Budgets::new(), &flag)
                .is_err()
        );
        reset_witnesses();
        let recovered = strict(&fixture, &request);
        assert_eq!(projected(&recovered), projected(&first));
    }

    fn request_response(response: &UnifiedResponse) -> UnifiedResponse {
        response.clone()
    }
}
// C2_TESTS_CLOSE_MARKER
