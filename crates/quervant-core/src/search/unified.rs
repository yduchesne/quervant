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
use crate::contract::value::FieldType;
use crate::index::ReaderSnapshot;
use crate::segment::SegmentReader;
use crate::segment::column::ColumnKeywordView;

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
use super::score::compute_stats;
use super::typed::{self, ScanGuard, TypedPlan};
use super::typed_compare::{
    ColumnAccess, SortValue, compare_borrowed_keyword_to_owned, compare_candidates,
    owned_keyword_sort_value, sort_tuple_for_doc,
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
        let mut budget = CandidateBudget::new(&self.limits);
        let mut scope = memory.map(SlotMemoryScope::new);
        let relevance = request.sort.fields.is_empty();
        let scoring = !plan.positive_lexical.is_empty();
        let heap_limit = request.top_k.limit.saturating_add(1);
        let mut heap: BinaryHeap<MixedEntry<'_>> = BinaryHeap::new();
        let mut experiment = d3c::State::for_request(
            request.top_k.limit,
            self.topk_duplicate,
            &mut budget,
            &mut scope,
        )?;
        let mut total_hits = 0u64;
        for (segment_index, reader) in readers.iter().enumerate() {
            let columns = ColumnAccess::open(reader)?;
            let keyword_field_id = if keyword_late {
                Some(
                    reader
                        .schema()
                        .field_id(&request.sort.fields[0].field)
                        .ok_or_else(|| SearchError::CorruptIndex {
                            detail:
                                "segment schema/analyzer bindings do not match the supplied schema"
                                    .to_owned(),
                        })?,
                )
            } else {
                None
            };
            let json = typed::JsonAccess::open(reader)?;
            let mut typed_geo: Vec<typed::GeoMembership> = Vec::new();
            let mut geo_scratches: Vec<typed::GeoScratchBudget> = Vec::new();
            for typed_leaf in &plan.typed_leaves {
                let mut scratch =
                    typed::GeoScratchBudget::new(self.limits.max_total_candidate_bytes());
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
                        self.limits.max_segment_candidate_entries(),
                        geo_memory.as_deref_mut(),
                    )?
                };
                typed_geo.push(membership);
                geo_scratches.push(scratch);
            }
            let mut sort_scratch =
                typed::GeoScratchBudget::new(self.limits.max_total_candidate_bytes());
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
            let postings_candidate_eligible =
                single_term_postings_eligible(plan, request, aggregation);
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
            for (doc_id, score) in scored {
                total_hits = total_hits
                    .checked_add(1)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
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
    let overflow = || SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    };
    let mut bytes = 64u64
        .checked_add(hit.key.as_str().len() as u64)
        .ok_or_else(overflow)?;
    for value in &hit.sort_tuple {
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

    /// Test-only injection point for the two owned reservation failures.
    #[cfg(test)]
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) enum ReserveFault {
        Set,
        Scratch,
    }
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

    fn hash_key(key: &DocumentKey) -> u64 {
        use std::hash::{Hash, Hasher};
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        key.as_str().hash(&mut hasher);
        hasher.finish()
    }

    fn probes(hash: u64, mask: usize) -> (usize, usize) {
        ((hash as usize) & mask, ((hash >> 32) as usize) & mask)
    }

    #[derive(Debug)]
    pub(super) struct State<S = std::collections::hash_map::RandomState> {
        kind: Kind,
        profile: Profile,
        words: [u64; MAX_WORDS],
        active_bits: usize,
        admissions: usize,
        disabled: bool,
        keys: HashSet<DocumentKey, S>,
        /// Fixed structural charge for the whole query: the actual set bucket
        /// capacity plus the actual scratch vector capacity. Never adjusted for a
        /// later effective-capacity change; released by query/scope cleanup.
        exact_table_charged: u64,
        exact_live_key_charged: u64,
        exact_scratch: Vec<DocumentKey>,
        exact_retained_limit: usize,
        exact_initial_capacity: usize,
        #[cfg(test)]
        exact_scans: std::cell::Cell<usize>,
        #[cfg(test)]
        exact_rebuilds: std::cell::Cell<usize>,
        #[cfg(test)]
        force_rebuild_next_admit: bool,
        #[cfg(test)]
        pub(super) fail_reserve: bool,
        #[cfg(test)]
        pub(super) fail_scratch_reserve: bool,
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
    impl State<std::collections::hash_map::RandomState> {
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
            Self::new_with_builder(
                kind,
                profile,
                k,
                budget,
                scope,
                std::collections::hash_map::RandomState::default(),
            )
        }

        #[cfg(test)]
        pub(super) fn hash_for_test(key: &DocumentKey) -> u64 {
            hash_key(key)
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

        /// Historical unaccounted test constructor: reserves storage without
        /// charging a constructor budget.
        #[cfg(test)]
        pub(super) fn for_test(kind: Kind, profile: Profile, k: usize) -> Self {
            let mut state = Self::empty(kind, profile);
            if kind == Kind::ExactSet {
                state.reserve_exact_set(k).expect("reserve");
                state.exact_initial_capacity = state.keys.capacity();
                state.exact_retained_limit = k.saturating_add(1);
            }
            state
        }
    }

    #[allow(dead_code)]
    impl<S: std::hash::BuildHasher + Default> State<S> {
        fn empty(kind: Kind, profile: Profile) -> Self {
            Self {
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
                keys: HashSet::default(),
                exact_table_charged: 0,
                exact_live_key_charged: 0,
                exact_scratch: Vec::new(),
                exact_retained_limit: 0,
                exact_initial_capacity: 0,
                #[cfg(test)]
                exact_scans: std::cell::Cell::new(0),
                #[cfg(test)]
                exact_rebuilds: std::cell::Cell::new(0),
                #[cfg(test)]
                force_rebuild_next_admit: false,
                #[cfg(test)]
                fail_reserve: false,
                #[cfg(test)]
                fail_scratch_reserve: false,
            }
        }

        fn new_with_builder(
            kind: Kind,
            profile: Profile,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
            builder: S,
        ) -> SearchResult<Self> {
            let mut state = Self::empty(kind, profile);
            state.keys = HashSet::with_hasher(builder);
            Self::finish_construction(state, k, budget, scope)
        }

        /// Single owned construction path shared by production and test entrypoints.
        fn finish_construction(
            mut state: Self,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<Self> {
            if state.kind == Kind::ExactSet {
                if k == 0 || k > MAX_EXACT_SET_K {
                    return Err(SearchError::ResourceLimit {
                        limit: MAX_EXACT_SET_K as u64,
                        requested: k as u64,
                    });
                }
                state.reserve_exact_set(k)?;
                let set_capacity = state.keys.capacity();
                let scratch_capacity = state.exact_scratch.capacity();
                let table = u64::try_from(set_capacity)
                    .unwrap_or(u64::MAX)
                    .checked_mul(40)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                let scratch = u64::try_from(scratch_capacity)
                    .unwrap_or(u64::MAX)
                    .checked_mul(std::mem::size_of::<DocumentKey>() as u64)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                let total = table
                    .checked_add(scratch)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                h_preflight(budget, scope, total)?;
                h_commit(budget, scope, total)?;
                state.exact_table_charged = total;
                state.exact_initial_capacity = set_capacity;
                state.exact_retained_limit = k.saturating_add(1);
            }
            Ok(state)
        }

        #[cfg(test)]
        pub(super) fn for_test_accounted_with_builder_and_fault(
            builder: S,
            kind: Kind,
            profile: Profile,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
            fault: ReserveFault,
        ) -> SearchResult<Self> {
            let mut state = Self::empty(kind, profile);
            state.keys = HashSet::with_hasher(builder);
            match fault {
                ReserveFault::Set => state.fail_reserve = true,
                ReserveFault::Scratch => state.fail_scratch_reserve = true,
            }
            Self::finish_construction(state, k, budget, scope)
        }

        #[cfg(test)]
        pub(super) fn for_test_accounted_with_builder(
            builder: S,
            kind: Kind,
            profile: Profile,
            k: usize,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> SearchResult<Self> {
            Self::new_with_builder(kind, profile, k, budget, scope, builder)
        }
    }

    #[allow(dead_code)]
    impl<S: std::hash::BuildHasher> State<S> {
        /// Reserve the fixed ExactSet storage on an empty, uncharged state.
        ///
        /// The set is reserved for the retained limit plus one transient insertion
        /// slot; the scratch vector is reserved for the retained limit (which
        /// includes the pagination sentinel).
        pub(super) fn reserve_exact_set(&mut self, k: usize) -> SearchResult<()> {
            if !self.keys.is_empty()
                || !self.exact_scratch.is_empty()
                || self.exact_table_charged != 0
                || self.exact_live_key_charged != 0
            {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set reservation requires an empty, uncharged state".to_owned(),
                });
            }
            #[cfg(test)]
            if self.fail_reserve {
                return Err(SearchError::ResourceLimit {
                    limit: (k.saturating_add(2)) as u64,
                    requested: (k.saturating_add(2)) as u64,
                });
            }
            let transient = k.checked_add(2).ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
            self.keys
                .try_reserve(transient)
                .map_err(|_| SearchError::ResourceLimit {
                    limit: transient as u64,
                    requested: transient as u64,
                })?;
            #[cfg(test)]
            if self.fail_scratch_reserve {
                return Err(SearchError::ResourceLimit {
                    limit: (k.saturating_add(1)) as u64,
                    requested: (k.saturating_add(1)) as u64,
                });
            }
            let retained = k.checked_add(1).ok_or(SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
            self.exact_scratch
                .try_reserve_exact(retained)
                .map_err(|_| SearchError::ResourceLimit {
                    limit: retained as u64,
                    requested: retained as u64,
                })?;
            Ok(())
        }

        /// Restore insertion allowance by moving the retained keys through the
        /// preallocated scratch vector. Both collections keep their allocations.
        fn rebuild_exact_set(&mut self) -> SearchResult<()> {
            if self.kind != Kind::ExactSet {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set rebuild requested for another strategy".to_owned(),
                });
            }
            if !self.exact_scratch.is_empty() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set scratch was not empty before rebuild".to_owned(),
                });
            }
            if self.keys.len() > self.exact_retained_limit
                || self.keys.len() > self.exact_scratch.capacity()
            {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set rebuild exceeded the reserved bound".to_owned(),
                });
            }
            for key in self.keys.drain() {
                self.exact_scratch.push(key);
            }
            for key in self.exact_scratch.drain(..) {
                self.keys.insert(key);
            }
            if !self.exact_scratch.is_empty() || self.keys.capacity() <= self.keys.len() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set rebuild left the state without an insertion slot".to_owned(),
                });
            }
            #[cfg(test)]
            {
                self.exact_rebuilds
                    .set(self.exact_rebuilds.get().saturating_add(1));
                self.force_rebuild_next_admit = false;
            }
            Ok(())
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
            if self.kind == Kind::ExactSet
                && (heap_limit == 0 || heap_limit > self.exact_retained_limit)
            {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set retained limit is invalid".to_owned(),
                });
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

            // ExactSet: storage is reserved and charged once at construction, so a
            // replacement only needs the transient clone/live-byte overlap.
            if self.keys.len() != heap.len() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set retained keys disagree with heap".to_owned(),
                });
            }
            if !self.exact_scratch.is_empty() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set scratch was not empty at admission".to_owned(),
                });
            }
            if self.keys.len() > self.exact_retained_limit {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set retained keys exceed the reserved bound".to_owned(),
                });
            }
            if self.keys.capacity() < self.keys.len() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set capacity is below the retained key count".to_owned(),
                });
            }
            let mut old_charge = 0u64;
            let old_len = if will_replace {
                let worst = heap.peek().expect("heap is nonempty");
                if !self.keys.contains(&worst.hit.key) {
                    return Err(SearchError::CorruptIndex {
                        detail: "exact-set is missing the retained worst key".to_owned(),
                    });
                }
                old_charge = worst.charge;
                worst.hit.key.as_str().len() as u64
            } else {
                0
            };
            let overflow = || SearchError::ResourceLimit {
                limit: u64::MAX,
                requested: u64::MAX,
            };
            let new_len = entry.hit.key.as_str().len() as u64;
            let extra = new_len.checked_add(old_len).ok_or_else(overflow)?;
            let peak_addition = extra.checked_add(entry.charge).ok_or_else(overflow)?;
            let release_after_replacement = old_len.checked_mul(2).ok_or_else(overflow)?;
            let old_total = old_charge.checked_add(old_len).ok_or_else(overflow)?;
            let next_live = self
                .exact_live_key_charged
                .checked_sub(old_len)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "exact-set live key charge underflow".to_owned(),
                })?
                .checked_add(new_len)
                .ok_or_else(overflow)?;

            h_preflight(budget, scope, peak_addition)?;
            if will_replace {
                h_preflight_release(budget, scope, old_total)?;
            }

            let needs_rebuild = self.keys.capacity() == self.keys.len();
            #[cfg(test)]
            let forced_rebuild = self.force_rebuild_next_admit;
            #[cfg(not(test))]
            let forced_rebuild = false;
            if needs_rebuild || forced_rebuild {
                self.rebuild_exact_set()?;
            }
            if self.keys.capacity() <= self.keys.len() {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set has no reserved insertion slot".to_owned(),
                });
            }

            h_commit(budget, scope, extra)?;
            let evicted_key = if will_replace {
                Some(heap.peek().expect("heap is nonempty").hit.key.clone())
            } else {
                None
            };
            let admitted_key = entry.hit.key.clone();
            if let Err(error) = heap_admit_candidate(entry, heap, heap_limit, budget, scope) {
                drop(evicted_key);
                drop(admitted_key);
                h_release(budget, scope, extra)?;
                return Err(error);
            }
            if !self.keys.insert(admitted_key) {
                return Err(SearchError::CorruptIndex {
                    detail: "exact-set insertion found a duplicate key".to_owned(),
                });
            }
            if let Some(old) = evicted_key {
                if !self.keys.remove(&old) {
                    return Err(SearchError::CorruptIndex {
                        detail: "exact-set eviction removed an absent key".to_owned(),
                    });
                }
                drop(old);
                h_preflight_release(budget, scope, release_after_replacement)?;
                h_release(budget, scope, release_after_replacement)?;
            }
            self.exact_live_key_charged = next_live;
            Ok(())
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
        pub(super) fn structure_charge_for_test(&self) -> u64 {
            self.exact_table_charged
        }

        #[cfg(test)]
        pub(super) fn scratch_capacity_for_test(&self) -> usize {
            self.exact_scratch.capacity()
        }

        #[cfg(test)]
        pub(super) fn retained_limit_for_test(&self) -> usize {
            self.exact_retained_limit
        }

        #[cfg(test)]
        pub(super) fn force_rebuild_pending(&self) -> bool {
            self.force_rebuild_next_admit
        }

        #[cfg(test)]
        pub(super) fn force_rebuild_next_admit(&mut self) {
            self.force_rebuild_next_admit = true;
        }

        #[cfg(test)]
        pub(super) fn rebuild_count(&self) -> usize {
            self.exact_rebuilds.get()
        }

        #[cfg(test)]
        pub(super) fn rebuilt_keys(&self) -> Vec<String> {
            let mut keys: Vec<String> = self.keys.iter().map(|k| k.as_str().to_owned()).collect();
            keys.sort();
            keys
        }

        #[cfg(test)]
        pub(super) fn scratch_is_empty(&self) -> bool {
            self.exact_scratch.is_empty()
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

    /// RF09-14 / RF09-17: deterministic ExactSet capacity/accounting regressions.
    #[cfg(test)]
    mod rf09_14_tests {
        use super::*;
        use crate::contract::result::Sort;
        use crate::search::batch_meter::BatchMemoryMeter;
        use std::collections::BinaryHeap;
        use std::hash::{BuildHasher, Hasher};

        const DENSE: usize = 20;
        const SPARSE: usize = 12;
        const FIXTURE_K: usize = 31;
        const FIXTURE_RETAINED: usize = FIXTURE_K + 1;
        const GENEROUS: u64 = 16 * 1024 * 1024;
        const LONG_KEY: usize = 1024;

        #[derive(Default)]
        struct FixtureHasher {
            state: u64,
        }

        impl Hasher for FixtureHasher {
            fn finish(&self) -> u64 {
                self.state
            }

            fn write(&mut self, bytes: &[u8]) {
                if bytes.starts_with(b"dense-") {
                    self.state = 0;
                } else if bytes.starts_with(b"sparse-") {
                    self.state = 40;
                } else if bytes != [0u8] && bytes != [0xffu8] {
                    panic!("unexpected RF09-14 fixture input");
                }
            }
        }

        #[derive(Debug, Default, Clone, Copy)]
        struct FixtureBuilder;

        impl BuildHasher for FixtureBuilder {
            type Hasher = FixtureHasher;

            fn build_hasher(&self) -> FixtureHasher {
                FixtureHasher::default()
            }
        }

        fn assert_corrupt(error: SearchError, detail: &str) {
            match error {
                SearchError::CorruptIndex { detail: actual } => assert_eq!(actual, detail),
                other => panic!("expected CorruptIndex({detail:?}), got {other:?}"),
            }
        }

        fn assert_limit(error: SearchError, limit: u64, requested: u64) {
            match error {
                SearchError::ResourceLimit {
                    limit: actual_limit,
                    requested: actual_requested,
                } => {
                    assert_eq!(actual_limit, limit);
                    assert_eq!(actual_requested, requested);
                }
                other => panic!("expected ResourceLimit({limit}/{requested}), got {other:?}"),
            }
        }

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
            }
        }

        /// One immutable input record. The expected charge is computed from the
        /// UTF-8 key length only, never from production bookkeeping.
        #[derive(Debug)]
        struct InputRecord {
            key: String,
            score: f64,
            charge: u64,
        }

        fn input_record(key: String, score: f64) -> InputRecord {
            assert!(key.is_ascii());
            assert!(!key.is_empty());
            assert!(key.len() <= LONG_KEY);
            assert!(score.is_finite());
            let charge = 64 + key.len() as u64;
            InputRecord { key, score, charge }
        }

        fn input_entry<'s>(sort: &'s Sort, input: &InputRecord, doc_id: u64) -> MixedEntry<'s> {
            let candidate = entry(sort, &input.key, input.score, doc_id);
            assert_eq!(candidate.charge, input.charge, "real entry charge");
            candidate
        }

        /// Maintain the independent model best-first: score descending, key ascending.
        fn model_insert<'i>(
            model: &mut Vec<&'i InputRecord>,
            input: &'i InputRecord,
            retained: usize,
        ) {
            model.push(input);
            model.sort_by(|left, right| {
                right
                    .score
                    .partial_cmp(&left.score)
                    .unwrap()
                    .then_with(|| left.key.as_str().cmp(right.key.as_str()))
            });
            model.truncate(retained);
        }

        fn model_key_bytes(model: &[&InputRecord]) -> u64 {
            model.iter().map(|input| input.key.len() as u64).sum()
        }

        fn model_charges(model: &[&InputRecord]) -> u64 {
            model.iter().map(|input| input.charge).sum()
        }

        fn model_current(structural: u64, model: &[&InputRecord]) -> u64 {
            structural + model_charges(model) + model_key_bytes(model)
        }

        /// Expected transient peak for one operation, derived only from immutable
        /// input records and the pre-operation model.
        fn model_next_peak(
            structural: u64,
            model: &[&InputRecord],
            input: &InputRecord,
            retained: usize,
        ) -> u64 {
            assert!(retained > 0);
            assert!(model.len() <= retained);
            let before = model_current(structural, model);
            let old_len = if model.len() < retained {
                0
            } else {
                let worst = model.last().unwrap();
                let competitive = input.score > worst.score
                    || (input.score == worst.score && input.key.as_str() < worst.key.as_str());
                if !competitive {
                    return before;
                }
                worst.key.len() as u64
            };
            before + input.key.len() as u64 + old_len + input.charge
        }

        /// Exact local balance, probed through the non-mutating release preflight.
        fn local_balance(budget: &CandidateBudget) -> u64 {
            let (mut low, mut high) = (0u64, u64::MAX);
            while low < high {
                let mid = low + (high - low) / 2 + 1;
                if budget.preflight_release_global_bytes(mid).is_ok() {
                    low = mid;
                } else {
                    high = mid - 1;
                }
            }
            low
        }

        /// Fixed structural charge from the physical capacities of an empty state.
        fn initial_structural_charge<S: BuildHasher>(state: &State<S>) -> u64 {
            assert!(state.keys.is_empty(), "capture T before admitting any key");
            assert!(
                state.exact_scratch.is_empty(),
                "capture T with empty scratch"
            );
            let table = u64::try_from(state.keys.capacity())
                .expect("set capacity fits u64")
                .checked_mul(40)
                .expect("fixture table charge fits u64");
            let scratch = u64::try_from(state.exact_scratch.capacity())
                .expect("scratch capacity fits u64")
                .checked_mul(u64::try_from(std::mem::size_of::<DocumentKey>()).unwrap())
                .expect("fixture scratch charge fits u64");
            table.checked_add(scratch).expect("fixture T fits u64")
        }

        /// Complete pre/post observation for allocation identity and rejection atomicity.
        #[derive(Debug, PartialEq, Eq)]
        struct Snapshot {
            set_keys: Vec<(String, usize)>,
            heap_entries: Vec<(String, u64, u64)>,
            set_len: usize,
            set_capacity: usize,
            scratch_keys: Vec<String>,
            scratch_ptr: usize,
            scratch_len: usize,
            scratch_capacity: usize,
            table_charged: u64,
            live_key_charged: u64,
            retained_limit: usize,
            initial_capacity: usize,
            force_rebuild_pending: bool,
            rebuild_count: usize,
            local_bytes: u64,
            scope_bytes: Option<u64>,
        }

        fn snapshot<S: BuildHasher>(
            state: &State<S>,
            heap: &BinaryHeap<MixedEntry<'_>>,
            budget: &CandidateBudget,
            scope: Option<&SlotMemoryScope<'_>>,
        ) -> Snapshot {
            let mut set_keys: Vec<(String, usize)> = state
                .keys
                .iter()
                .map(|key| (key.as_str().to_owned(), key.as_str().as_ptr() as usize))
                .collect();
            set_keys.sort();
            let mut heap_entries: Vec<(String, u64, u64)> = heap
                .iter()
                .map(|candidate| {
                    (
                        candidate.hit.key.as_str().to_owned(),
                        candidate
                            .hit
                            .score
                            .expect("relevance fixture score")
                            .to_bits(),
                        candidate.charge,
                    )
                })
                .collect();
            heap_entries.sort();
            Snapshot {
                set_keys,
                heap_entries,
                set_len: state.keys.len(),
                set_capacity: state.keys.capacity(),
                scratch_keys: state
                    .exact_scratch
                    .iter()
                    .map(|key| key.as_str().to_owned())
                    .collect(),
                scratch_ptr: state.exact_scratch.as_ptr() as usize,
                scratch_len: state.exact_scratch.len(),
                scratch_capacity: state.exact_scratch.capacity(),
                table_charged: state.exact_table_charged,
                live_key_charged: state.exact_live_key_charged,
                retained_limit: state.exact_retained_limit,
                initial_capacity: state.exact_initial_capacity,
                force_rebuild_pending: state.force_rebuild_pending(),
                rebuild_count: state.rebuild_count(),
                local_bytes: local_balance(budget),
                scope_bytes: scope.map(|scope_ref| scope_ref.temporary_bytes()),
            }
        }

        /// Compare the real state/heap/sinks with the independent borrowed model.
        fn assert_valid_state<S: BuildHasher>(
            state: &State<S>,
            heap: &BinaryHeap<MixedEntry<'_>>,
            model: &[&InputRecord],
            structural: u64,
            initial_scratch: usize,
            budget: &CandidateBudget,
            scope: Option<&SlotMemoryScope<'_>>,
        ) -> u64 {
            let mut expected_keys: Vec<&str> =
                model.iter().map(|input| input.key.as_str()).collect();
            expected_keys.sort_unstable();
            let mut set_keys: Vec<&str> = state.keys.iter().map(|key| key.as_str()).collect();
            set_keys.sort_unstable();
            let mut heap_keys: Vec<&str> = heap
                .iter()
                .map(|candidate| candidate.hit.key.as_str())
                .collect();
            heap_keys.sort_unstable();
            assert_eq!(set_keys, expected_keys, "set membership");
            assert_eq!(heap_keys, expected_keys, "heap membership");
            assert_eq!(state.keys.len(), model.len());
            assert_eq!(heap.len(), model.len());

            let mut expected_entries: Vec<(&str, u64, u64)> = model
                .iter()
                .map(|input| (input.key.as_str(), input.score.to_bits(), input.charge))
                .collect();
            expected_entries.sort_unstable();
            let mut actual_entries: Vec<(&str, u64, u64)> = heap
                .iter()
                .map(|candidate| {
                    (
                        candidate.hit.key.as_str(),
                        candidate.hit.score.unwrap().to_bits(),
                        candidate.charge,
                    )
                })
                .collect();
            actual_entries.sort_unstable();
            assert_eq!(actual_entries, expected_entries, "entry values and charges");
            assert_eq!(
                heap.peek().map(|candidate| candidate.hit.key.as_str()),
                model.last().map(|input| input.key.as_str()),
                "independent worst retained key",
            );
            assert!(state.exact_scratch.is_empty());
            assert_eq!(state.exact_scratch.capacity(), initial_scratch);
            assert_eq!(state.exact_table_charged, structural);
            assert_eq!(state.exact_live_key_charged, model_key_bytes(model));

            let expected = model_current(structural, model);
            assert!(budget.preflight_release_global_bytes(expected).is_ok());
            assert!(budget.preflight_release_global_bytes(expected + 1).is_err());
            if let Some(scope_ref) = scope {
                assert_eq!(scope_ref.temporary_bytes(), expected);
            }
            expected
        }

        /// Observe the real heap ordering without building the expected order from it.
        fn assert_best_first(
            heap: &BinaryHeap<MixedEntry<'_>>,
            model: &[&InputRecord],
            expected: &[&str],
        ) {
            let model_keys: Vec<&str> = model.iter().map(|input| input.key.as_str()).collect();
            assert_eq!(model_keys, expected, "model best-first order");
            let actual_order = heap.iter().collect::<BinaryHeap<_>>().into_sorted_vec();
            let actual_keys: Vec<&str> = actual_order
                .iter()
                .map(|candidate| candidate.hit.key.as_str())
                .collect();
            assert_eq!(actual_keys, expected, "heap best-first order");
        }

        fn fixture_keys() -> Vec<InputRecord> {
            let mut keys: Vec<InputRecord> = (0..DENSE)
                .map(|index| {
                    input_record(
                        format!("dense-{index:02}"),
                        if index == 0 { 0.0 } else { 10.0 + index as f64 },
                    )
                })
                .collect();
            keys.extend((0..SPARSE).map(|index| {
                input_record(
                    format!("sparse-{index:02}"),
                    if index == 0 { 1.0 } else { 40.0 + index as f64 },
                )
            }));
            keys
        }

        fn churn_key(prefix: &str, target_len: Option<usize>) -> String {
            match target_len {
                None => prefix.to_owned(),
                Some(length) => {
                    let mut value = prefix.to_owned();
                    while value.len() < length {
                        value.push('x');
                    }
                    assert_eq!(value.len(), length);
                    value
                }
            }
        }

        /// Unaccounted probe state with the deterministic collision fixture hasher.
        fn unaccounted_fixture(k: usize) -> State<FixtureBuilder> {
            let mut state = State::empty(Kind::ExactSet, Profile::P2);
            state.keys = HashSet::with_hasher(FixtureBuilder);
            state.reserve_exact_set(k).expect("reserve");
            state.exact_initial_capacity = state.keys.capacity();
            state.exact_retained_limit = k + 1;
            state
        }

        fn unaccounted_plain(k: usize) -> State {
            let mut state = State::empty(Kind::ExactSet, Profile::P2);
            state.reserve_exact_set(k).expect("reserve");
            state.exact_initial_capacity = state.keys.capacity();
            state.exact_retained_limit = k + 1;
            state
        }

        fn fixture_state(
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
        ) -> State<FixtureBuilder> {
            State::for_test_accounted_with_builder(
                FixtureBuilder,
                Kind::ExactSet,
                Profile::P2,
                FIXTURE_K,
                budget,
                scope,
            )
            .expect("fixture constructor")
        }

        fn fill<'s, 'i, S: BuildHasher>(
            state: &mut State<S>,
            heap: &mut BinaryHeap<MixedEntry<'s>>,
            sort: &'s Sort,
            budget: &mut CandidateBudget,
            scope: &mut Option<SlotMemoryScope<'_>>,
            inputs: &'i [InputRecord],
            retained: usize,
        ) -> Vec<&'i InputRecord> {
            assert!(heap.is_empty(), "fill starts with an empty heap");
            let structural = initial_structural_charge(state);
            let initial_scratch = state.exact_scratch.capacity();
            let mut model = Vec::new();
            assert_valid_state(
                state,
                heap,
                &model,
                structural,
                initial_scratch,
                budget,
                scope.as_ref(),
            );
            for (doc_id, input) in inputs.iter().enumerate() {
                state
                    .admit(
                        input_entry(sort, input, doc_id as u64),
                        heap,
                        retained,
                        budget,
                        scope,
                    )
                    .unwrap_or_else(|error| panic!("fill {}: {error:?}", input.key));
                model_insert(&mut model, input, retained);
                assert_valid_state(
                    state,
                    heap,
                    &model,
                    structural,
                    initial_scratch,
                    budget,
                    scope.as_ref(),
                );
            }
            model
        }

        // ------------------------------------------------------------------
        // A-U01: fixed first replacement, local and real batch sinks.
        // ------------------------------------------------------------------
        fn a_u01_case(batch: bool) {
            let sort = Sort::default();
            let mut inputs = fixture_keys();
            inputs.push(input_record("sparse-new".to_owned(), 1000.0));
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            {
                let mut scope = if batch {
                    Some(SlotMemoryScope::new(&mut meter))
                } else {
                    None
                };
                let mut heap = BinaryHeap::new();
                let mut state = fixture_state(&mut budget, &mut scope);
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                assert_eq!(state.exact_table_charged, structural);
                assert_eq!(state.exact_initial_capacity, state.keys.capacity());
                let mut model = fill(
                    &mut state,
                    &mut heap,
                    &sort,
                    &mut budget,
                    &mut scope,
                    &inputs[..FIXTURE_RETAINED],
                    FIXTURE_RETAINED,
                );
                let filled = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(filled, structural + 2584, "filled current");
                assert_eq!(model_key_bytes(&model), 268);
                assert_eq!(model_charges(&model), 2316);
                assert_eq!(
                    heap.peek().map(|candidate| candidate.hit.key.as_str()),
                    Some("dense-00")
                );

                let expected_peak = structural + 2584 + 10 + 8 + 74;
                assert_eq!(expected_peak, structural + 2676, "replacement peak");
                state
                    .admit(
                        input_entry(&sort, &inputs[FIXTURE_RETAINED], 100),
                        &mut heap,
                        FIXTURE_RETAINED,
                        &mut budget,
                        &mut scope,
                    )
                    .expect("first replacement");
                model_insert(&mut model, &inputs[FIXTURE_RETAINED], FIXTURE_RETAINED);
                let current = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(current, structural + 2588, "current after replacement");
                assert_eq!(model_key_bytes(&model), 270);
                assert_eq!(model_charges(&model), 2318);
                let mut expected: Vec<&str> = inputs[..FIXTURE_RETAINED]
                    .iter()
                    .map(|input| input.key.as_str())
                    .filter(|value| *value != "dense-00")
                    .collect();
                expected.push(inputs[FIXTURE_RETAINED].key.as_str());
                expected.sort_unstable();
                let mut actual: Vec<&str> = state.keys.iter().map(|key| key.as_str()).collect();
                actual.sort_unstable();
                assert_eq!(actual, expected, "replacement membership");

                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                drop(scope);
                assert_eq!(meter.current(), 0);
                if batch {
                    assert_eq!(meter.peak(), expected_peak, "batch peak");
                }
            }
        }

        #[test]
        fn a_u01_replacement_conserves_the_structural_ledger() {
            a_u01_case(false);
        }

        #[test]
        fn a_u01b_batch_replacement_conserves_the_structural_ledger() {
            a_u01_case(true);
        }

        // ------------------------------------------------------------------
        // A-U02: explicit second-replacement membership.
        // ------------------------------------------------------------------
        #[test]
        fn a_u02_second_replacement_matches_the_model() {
            let sort = Sort::default();
            let mut inputs = fixture_keys();
            inputs.push(input_record("sparse-new".to_owned(), 1000.0));
            inputs.push(input_record("dense-new".to_owned(), 1001.0));
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut scope: Option<SlotMemoryScope<'_>> = None;
            let mut heap = BinaryHeap::new();
            let mut state = fixture_state(&mut budget, &mut scope);
            let structural = initial_structural_charge(&state);
            let initial_scratch = state.exact_scratch.capacity();
            let mut model = fill(
                &mut state,
                &mut heap,
                &sort,
                &mut budget,
                &mut scope,
                &inputs[..FIXTURE_RETAINED],
                FIXTURE_RETAINED,
            );
            for (offset, doc_id) in [(0usize, 100u64), (1, 101)] {
                let index = FIXTURE_RETAINED + offset;
                state
                    .admit(
                        input_entry(&sort, &inputs[index], doc_id),
                        &mut heap,
                        FIXTURE_RETAINED,
                        &mut budget,
                        &mut scope,
                    )
                    .expect("replacement");
                model_insert(&mut model, &inputs[index], FIXTURE_RETAINED);
                let current = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(current, structural + 2588, "equal-length exchange");
            }
            let mut expected: Vec<&str> = inputs[..FIXTURE_RETAINED]
                .iter()
                .map(|input| input.key.as_str())
                .filter(|value| *value != "dense-00" && *value != "sparse-00")
                .collect();
            expected.push(inputs[FIXTURE_RETAINED].key.as_str());
            expected.push(inputs[FIXTURE_RETAINED + 1].key.as_str());
            expected.sort_unstable();
            let mut actual: Vec<&str> = state.keys.iter().map(|key| key.as_str()).collect();
            actual.sort_unstable();
            assert_eq!(actual, expected, "explicit final membership");
            let mut model_keys: Vec<&str> = model.iter().map(|input| input.key.as_str()).collect();
            model_keys.sort_unstable();
            assert_eq!(model_keys, expected, "model final membership");
        }

        // ------------------------------------------------------------------
        // A-U03: rebuild observations include heap score bits.
        // ------------------------------------------------------------------
        #[test]
        fn a_u03_rebuild_moves_the_same_allocations() {
            let sort = Sort::default();
            let inputs = fixture_keys();
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            {
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let mut heap = BinaryHeap::new();
                let mut state = fixture_state(&mut budget, &mut scope);
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                let model = fill(
                    &mut state,
                    &mut heap,
                    &sort,
                    &mut budget,
                    &mut scope,
                    &inputs,
                    FIXTURE_RETAINED,
                );
                let filled = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(filled, structural + 2584);
                let before = snapshot(&state, &heap, &budget, scope.as_ref());
                assert_eq!(before.rebuild_count, 0);
                state.rebuild_exact_set().expect("rebuild");
                let after = snapshot(&state, &heap, &budget, scope.as_ref());
                assert_eq!(after.set_keys, before.set_keys, "key pointers");
                assert_eq!(after.heap_entries, before.heap_entries, "heap tuples");
                assert_eq!(after.set_len, before.set_len);
                assert_eq!(after.scratch_keys, before.scratch_keys);
                assert_eq!(after.scratch_ptr, before.scratch_ptr);
                assert_eq!(after.scratch_len, before.scratch_len);
                assert_eq!(after.scratch_capacity, before.scratch_capacity);
                assert_eq!(after.table_charged, before.table_charged);
                assert_eq!(after.live_key_charged, before.live_key_charged);
                assert_eq!(after.retained_limit, before.retained_limit);
                assert_eq!(after.initial_capacity, before.initial_capacity);
                assert_eq!(after.force_rebuild_pending, before.force_rebuild_pending);
                assert_eq!(before.rebuild_count, 0);
                assert_eq!(after.rebuild_count, 1);
                assert_eq!(after.local_bytes, before.local_bytes);
                assert_eq!(after.scope_bytes, before.scope_bytes);
                assert!(after.set_capacity > after.set_len, "insertion slot");
                assert!(state.scratch_is_empty());
                assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                drop(scope);
                assert_eq!(meter.current(), 0);
                assert_eq!(meter.peak(), structural + 2584, "fill peak");
            }
        }

        // ------------------------------------------------------------------
        // A-U04 / A-U05: constructor matrix with actual meter observations.
        // ------------------------------------------------------------------
        fn constructor_boundaries(batch: bool) {
            for k in [1usize, 31, 32, 100, 1024] {
                let probe_t = {
                    let probe = unaccounted_fixture(k);
                    initial_structural_charge(&probe)
                };
                if batch {
                    let mut meter = BatchMemoryMeter::new(probe_t);
                    {
                        let mut scope = Some(SlotMemoryScope::new(&mut meter));
                        let mut budget = CandidateBudget::new(
                            &SearchLimits::default()
                                .with_max_total_candidate_bytes(GENEROUS)
                                .unwrap(),
                        );
                        let state = State::for_test_accounted_with_builder(
                            FixtureBuilder,
                            Kind::ExactSet,
                            Profile::P2,
                            k,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap_or_else(|error| panic!("K{k} exact batch budget: {error:?}"));
                        let structural = initial_structural_charge(&state);
                        assert_eq!(structural, probe_t, "K{k} probe T");
                        assert_eq!(state.exact_table_charged, structural);
                        assert_eq!(state.exact_live_key_charged, 0);
                        assert_eq!(state.exact_initial_capacity, state.keys.capacity());
                        assert_eq!(state.retained_limit_for_test(), k + 1);
                        assert_eq!(local_balance(&budget), structural);
                        assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural);
                        drop(state);
                        scope.as_mut().unwrap().finish_failure().unwrap();
                        assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                    }
                    assert_eq!(meter.current(), 0);
                    assert_eq!(meter.peak(), probe_t, "K{k} batch exact peak");

                    let mut meter = BatchMemoryMeter::new(probe_t - 1);
                    {
                        let mut scope = Some(SlotMemoryScope::new(&mut meter));
                        let mut budget = CandidateBudget::new(
                            &SearchLimits::default()
                                .with_max_total_candidate_bytes(GENEROUS)
                                .unwrap(),
                        );
                        let error = State::for_test_accounted_with_builder(
                            FixtureBuilder,
                            Kind::ExactSet,
                            Profile::P2,
                            k,
                            &mut budget,
                            &mut scope,
                        )
                        .expect_err("one-under batch constructor must fail");
                        assert!(
                            matches!(
                                error,
                                SearchError::Query(QueryError::BudgetExceeded {
                                    kind: crate::contract::budget::BudgetKind::BatchMemoryBytes,
                                })
                            ),
                            "K{k} unexpected error {error:?}"
                        );
                        assert_eq!(local_balance(&budget), 0);
                        assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                    }
                    assert_eq!(meter.current(), 0);
                    assert_eq!(meter.peak(), 0, "K{k} one-under batch peak");
                } else {
                    let mut budget = CandidateBudget::new(
                        &SearchLimits::default()
                            .with_max_total_candidate_bytes(probe_t)
                            .unwrap(),
                    );
                    let mut scope: Option<SlotMemoryScope<'_>> = None;
                    let state = State::for_test_accounted_with_builder(
                        FixtureBuilder,
                        Kind::ExactSet,
                        Profile::P2,
                        k,
                        &mut budget,
                        &mut scope,
                    )
                    .unwrap_or_else(|error| panic!("K{k} exact local budget: {error:?}"));
                    let structural = initial_structural_charge(&state);
                    assert_eq!(structural, probe_t);
                    assert_eq!(state.exact_table_charged, structural);
                    assert_eq!(state.exact_live_key_charged, 0);
                    assert_eq!(state.exact_initial_capacity, state.keys.capacity());
                    assert_eq!(state.retained_limit_for_test(), k + 1);
                    assert_eq!(local_balance(&budget), structural);
                    drop(state);

                    let mut tight = CandidateBudget::new(
                        &SearchLimits::default()
                            .with_max_total_candidate_bytes(probe_t - 1)
                            .unwrap(),
                    );
                    let mut scope: Option<SlotMemoryScope<'_>> = None;
                    let error = State::for_test_accounted_with_builder(
                        FixtureBuilder,
                        Kind::ExactSet,
                        Profile::P2,
                        k,
                        &mut tight,
                        &mut scope,
                    )
                    .expect_err("one-under local constructor must fail");
                    assert_limit(error, probe_t - 1, probe_t);
                    assert_eq!(local_balance(&tight), 0);
                }
            }
            for k in [0usize, MAX_EXACT_SET_K + 1] {
                let mut budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                let mut scope: Option<SlotMemoryScope<'_>> = None;
                let error = State::for_test_accounted_with_builder(
                    FixtureBuilder,
                    Kind::ExactSet,
                    Profile::P2,
                    k,
                    &mut budget,
                    &mut scope,
                )
                .expect_err("invalid K local constructor must fail");
                assert_limit(error, MAX_EXACT_SET_K as u64, k as u64);
                assert_eq!(local_balance(&budget), 0);

                let mut meter = BatchMemoryMeter::new(GENEROUS);
                {
                    let mut scope = Some(SlotMemoryScope::new(&mut meter));
                    let mut budget = CandidateBudget::new(
                        &SearchLimits::default()
                            .with_max_total_candidate_bytes(GENEROUS)
                            .unwrap(),
                    );
                    let error = State::for_test_accounted_with_builder(
                        FixtureBuilder,
                        Kind::ExactSet,
                        Profile::P2,
                        k,
                        &mut budget,
                        &mut scope,
                    )
                    .expect_err("invalid K batch constructor must fail");
                    assert_limit(error, MAX_EXACT_SET_K as u64, k as u64);
                    assert_eq!(local_balance(&budget), 0);
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                }
                assert_eq!(meter.current(), 0);
                assert_eq!(meter.peak(), 0);
            }
        }

        #[test]
        fn a_u04_constructor_local_boundaries_are_exact() {
            constructor_boundaries(false);
        }

        #[test]
        fn a_u05_constructor_batch_boundaries_are_exact() {
            constructor_boundaries(true);
        }

        // ------------------------------------------------------------------
        // A-U06: fixed outcomes, exact error fields, complete rejection snapshots.
        // ------------------------------------------------------------------
        #[derive(Clone, Copy, Debug)]
        enum ReplacementCase {
            RejectOnly,
            RejectThenReuse,
            ExactSuccess,
        }

        fn a_u06_case(batch: bool, case: ReplacementCase) {
            let sort = Sort::default();
            let inputs = [
                input_record("a".to_owned(), 1.0),
                input_record("bb".to_owned(), 2.0),
                input_record("cccc".to_owned(), 9.0),
                input_record("ccc".to_owned(), 9.0),
            ];
            let probe_t = {
                let probe = unaccounted_plain(1);
                initial_structural_charge(&probe)
            };
            let ceiling = match case {
                ReplacementCase::ExactSuccess => probe_t + 207,
                _ => probe_t + 206,
            };
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(if batch { GENEROUS } else { ceiling })
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(if batch { ceiling } else { GENEROUS });
            let structural = {
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let mut heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    1,
                    &mut budget,
                    &mut scope,
                )
                .expect("K=1 constructor");
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                assert_eq!(structural, probe_t);
                assert_eq!(state.exact_table_charged, structural);
                let mut model = fill(
                    &mut state,
                    &mut heap,
                    &sort,
                    &mut budget,
                    &mut scope,
                    &inputs[..2],
                    2,
                );
                let filled = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(filled, structural + 134);
                assert_eq!(local_balance(&budget), structural + 134);
                assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 134);
                assert_eq!(state.exact_live_key_charged, 3);
                assert_eq!(state.rebuild_count(), 0);
                state.force_rebuild_next_admit();
                let before = snapshot(&state, &heap, &budget, scope.as_ref());
                assert!(before.force_rebuild_pending);

                match case {
                    ReplacementCase::RejectOnly | ReplacementCase::RejectThenReuse => {
                        let error = state
                            .admit(
                                input_entry(&sort, &inputs[2], 2),
                                &mut heap,
                                2,
                                &mut budget,
                                &mut scope,
                            )
                            .expect_err("cccc must be rejected at the one-under peak");
                        if batch {
                            assert!(
                                matches!(
                                    error,
                                    SearchError::Query(QueryError::BudgetExceeded {
                                        kind: crate::contract::budget::BudgetKind::BatchMemoryBytes,
                                    })
                                ),
                                "unexpected error {error:?}"
                            );
                        } else {
                            assert_limit(error, structural + 206, structural + 207);
                        }
                        let after = snapshot(&state, &heap, &budget, scope.as_ref());
                        assert_eq!(after, before, "rejection must not mutate the state");
                        assert_eq!(model.len(), 2, "rejected record stays out of the model");
                        assert_eq!(local_balance(&budget), structural + 134);
                        assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 134);
                        assert!(state.force_rebuild_pending());
                        assert_eq!(state.rebuild_count(), 0);
                    }
                    ReplacementCase::ExactSuccess => {
                        state
                            .admit(
                                input_entry(&sort, &inputs[2], 2),
                                &mut heap,
                                2,
                                &mut budget,
                                &mut scope,
                            )
                            .expect("cccc admitted at the exact peak");
                        model_insert(&mut model, &inputs[2], 2);
                        assert!(!state.force_rebuild_pending());
                        assert_eq!(state.rebuild_count(), 1);
                        let current = assert_valid_state(
                            &state,
                            &heap,
                            &model,
                            structural,
                            initial_scratch,
                            &budget,
                            scope.as_ref(),
                        );
                        assert_eq!(current, structural + 140);
                        assert_eq!(
                            state.rebuilt_keys(),
                            vec!["bb".to_owned(), "cccc".to_owned()]
                        );
                    }
                }

                if matches!(case, ReplacementCase::RejectThenReuse) {
                    state
                        .admit(
                            input_entry(&sort, &inputs[3], 3),
                            &mut heap,
                            2,
                            &mut budget,
                            &mut scope,
                        )
                        .expect("ccc reuse on the same state");
                    model_insert(&mut model, &inputs[3], 2);
                    assert!(!state.force_rebuild_pending());
                    assert_eq!(state.rebuild_count(), 1);
                    let current = assert_valid_state(
                        &state,
                        &heap,
                        &model,
                        structural,
                        initial_scratch,
                        &budget,
                        scope.as_ref(),
                    );
                    assert_eq!(current, structural + 138);
                    assert_eq!(
                        state.rebuilt_keys(),
                        vec!["bb".to_owned(), "ccc".to_owned()]
                    );
                }

                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                drop(scope);
                structural
            };
            assert_eq!(meter.current(), 0);
            let expected_peak = match case {
                ReplacementCase::RejectOnly => structural + 134,
                ReplacementCase::RejectThenReuse => structural + 205,
                ReplacementCase::ExactSuccess => structural + 207,
            };
            assert_eq!(meter.peak(), expected_peak, "{case:?} peak");
        }

        #[test]
        fn a_u06a_local_peak_rejection_only() {
            a_u06_case(false, ReplacementCase::RejectOnly);
        }

        #[test]
        fn a_u06b_local_peak_rejection_then_reuse() {
            a_u06_case(false, ReplacementCase::RejectThenReuse);
        }

        #[test]
        fn a_u06c_local_peak_exact_success() {
            a_u06_case(false, ReplacementCase::ExactSuccess);
        }

        #[test]
        fn a_u06d_batch_peak_rejection_only() {
            a_u06_case(true, ReplacementCase::RejectOnly);
        }

        #[test]
        fn a_u06e_batch_peak_rejection_then_reuse() {
            a_u06_case(true, ReplacementCase::RejectThenReuse);
        }

        #[test]
        fn a_u06f_batch_peak_exact_success() {
            a_u06_case(true, ReplacementCase::ExactSuccess);
        }

        // ------------------------------------------------------------------
        // A-U07: fixed 20-cell churn matrix.
        // ------------------------------------------------------------------
        fn a_u07_case(k: usize, long: bool, batch: bool) {
            let sort = Sort::default();
            let retained = k + 1;
            let length = if long { Some(LONG_KEY) } else { None };
            let mut inputs = Vec::with_capacity(5 * retained);
            for index in 0..retained {
                inputs.push(input_record(
                    churn_key(&format!("init-{k:04}-{index:06}-"), length),
                    (retained - index) as f64,
                ));
            }
            for round in 0..4 * retained {
                inputs.push(input_record(
                    churn_key(&format!("churn-{k:04}-{round:06}-"), length),
                    1_000_000.0 + round as f64,
                ));
            }
            assert_eq!(inputs.len(), 5 * retained);
            if long {
                assert!(inputs.iter().all(|input| input.key.len() == LONG_KEY));
            }

            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            {
                let mut scope = if batch {
                    Some(SlotMemoryScope::new(&mut meter))
                } else {
                    None
                };
                let mut heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    k,
                    &mut budget,
                    &mut scope,
                )
                .expect("accounted churn state");
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                assert_eq!(state.exact_table_charged, structural);
                assert_eq!(state.exact_initial_capacity, state.keys.capacity());
                let mut model: Vec<&InputRecord> = Vec::new();
                let mut expected_peak = structural;
                assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );

                for (index, input) in inputs.iter().enumerate() {
                    if index == retained {
                        assert_eq!(state.rebuild_count(), 0);
                        state.force_rebuild_next_admit();
                        assert!(state.force_rebuild_pending());
                    }
                    let operation_peak = model_next_peak(structural, &model, input, retained);
                    expected_peak = expected_peak.max(operation_peak);
                    let doc_id = if index < retained {
                        index as u64
                    } else {
                        10_000 + (index - retained) as u64
                    };
                    state
                        .admit(
                            input_entry(&sort, input, doc_id),
                            &mut heap,
                            retained,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap_or_else(|error| {
                            panic!("K{k} long={long} batch={batch} input={index}: {error:?}")
                        });
                    model_insert(&mut model, input, retained);
                    assert_valid_state(
                        &state,
                        &heap,
                        &model,
                        structural,
                        initial_scratch,
                        &budget,
                        scope.as_ref(),
                    );
                    match index.cmp(&retained) {
                        std::cmp::Ordering::Equal => {
                            assert_eq!(state.rebuild_count(), 1);
                            assert!(!state.force_rebuild_pending());
                        }
                        std::cmp::Ordering::Greater => {
                            assert!(state.rebuild_count() >= 1);
                            assert!(!state.force_rebuild_pending());
                        }
                        std::cmp::Ordering::Less => {}
                    }
                }

                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                drop(scope);
                assert_eq!(meter.current(), 0);
                if batch {
                    assert_eq!(meter.peak(), expected_peak, "K{k} long={long} peak");
                }
            }
        }

        #[test]
        fn a_u07_model_churn_preserves_membership_and_ledger() {
            for k in [1usize, 31, 32, 100, 1024] {
                for long in [false, true] {
                    for batch in [false, true] {
                        a_u07_case(k, long, batch);
                    }
                }
            }
        }

        // ------------------------------------------------------------------
        // A-U08: the original R=3 chain and the R=2 tie chain.
        // ------------------------------------------------------------------
        #[test]
        fn a_u08_duplicates_ordering_and_losers_are_preserved() {
            let sort = Sort::default();
            let inputs = [
                input_record("a".to_owned(), 1.0),
                input_record("bb".to_owned(), 2.0),
                input_record("ddd".to_owned(), 5.0),
                input_record("zz".to_owned(), -1.0),
                input_record("cccc".to_owned(), 9.0),
                input_record("a".to_owned(), 50.0),
            ];
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut scope: Option<SlotMemoryScope<'_>> = None;
            let mut heap = BinaryHeap::new();
            let mut state =
                State::for_test_accounted(Kind::ExactSet, Profile::P2, 2, &mut budget, &mut scope)
                    .expect("K=2");
            let structural = initial_structural_charge(&state);
            let initial_scratch = state.exact_scratch.capacity();
            let mut model: Vec<&InputRecord> = Vec::new();

            state
                .admit(
                    input_entry(&sort, &inputs[0], 0),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("admit a");
            model_insert(&mut model, &inputs[0], 3);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["a"]);

            state
                .admit(
                    input_entry(&sort, &inputs[1], 1),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("admit bb");
            model_insert(&mut model, &inputs[1], 3);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["bb", "a"]);

            let before = snapshot(&state, &heap, &budget, scope.as_ref());
            let error = state
                .check(&heap, &key("a"))
                .expect_err("retained duplicate must fail");
            assert_corrupt(error, "duplicate live document key across segments");
            assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);

            state
                .admit(
                    input_entry(&sort, &inputs[2], 2),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("admit ddd");
            model_insert(&mut model, &inputs[2], 3);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["ddd", "bb", "a"]);

            state.force_rebuild_next_admit();
            let before = snapshot(&state, &heap, &budget, scope.as_ref());
            state
                .admit(
                    input_entry(&sort, &inputs[3], 99),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("loser admission is a no-op");
            assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);
            assert!(state.force_rebuild_pending());
            assert_eq!(state.rebuild_count(), 0);
            assert_eq!(model.len(), 3);

            state
                .admit(
                    input_entry(&sort, &inputs[4], 100),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("admit cccc");
            model_insert(&mut model, &inputs[4], 3);
            assert!(!state.force_rebuild_pending());
            assert_eq!(state.rebuild_count(), 1);
            assert!(!state.contains_key(&key("a")), "a was evicted");
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["cccc", "ddd", "bb"]);

            state
                .admit(
                    input_entry(&sort, &inputs[5], 101),
                    &mut heap,
                    3,
                    &mut budget,
                    &mut scope,
                )
                .expect("reappearance of a");
            model_insert(&mut model, &inputs[5], 3);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["a", "cccc", "ddd"]);
            drop(heap);
            drop(state);
        }

        #[test]
        fn a_u08_ordering_duplicates_and_losers_are_preserved() {
            let sort = Sort::default();
            let inputs = [
                input_record("b".to_owned(), 7.0),
                input_record("a".to_owned(), 7.0),
                input_record("aa".to_owned(), 7.0),
                input_record("z".to_owned(), 7.0),
                input_record("0".to_owned(), 7.0),
                input_record("aa".to_owned(), 8.0),
            ];
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut scope: Option<SlotMemoryScope<'_>> = None;
            let mut heap = BinaryHeap::new();
            let mut state =
                State::for_test_accounted(Kind::ExactSet, Profile::P2, 1, &mut budget, &mut scope)
                    .expect("K=1");
            let structural = initial_structural_charge(&state);
            let initial_scratch = state.exact_scratch.capacity();
            let mut model: Vec<&InputRecord> = Vec::new();
            assert!(state.check(&heap, &key("a")).is_ok(), "absent key passes");

            for (index, doc_id) in [(0usize, 0u64), (1, 1)] {
                state
                    .admit(
                        input_entry(&sort, &inputs[index], doc_id),
                        &mut heap,
                        2,
                        &mut budget,
                        &mut scope,
                    )
                    .expect("initial admission");
                model_insert(&mut model, &inputs[index], 2);
                assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
            }
            assert_best_first(&heap, &model, &["a", "b"]);

            let before = snapshot(&state, &heap, &budget, scope.as_ref());
            let error = state
                .check(&heap, &key("a"))
                .expect_err("retained duplicate must fail");
            assert_corrupt(error, "duplicate live document key across segments");
            assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);

            state
                .admit(
                    input_entry(&sort, &inputs[2], 3),
                    &mut heap,
                    2,
                    &mut budget,
                    &mut scope,
                )
                .expect("tie admission aa");
            model_insert(&mut model, &inputs[2], 2);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["a", "aa"]);

            state.force_rebuild_next_admit();
            let before = snapshot(&state, &heap, &budget, scope.as_ref());
            state
                .admit(
                    input_entry(&sort, &inputs[3], 4),
                    &mut heap,
                    2,
                    &mut budget,
                    &mut scope,
                )
                .expect("loser admission is a no-op");
            assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);
            assert!(state.force_rebuild_pending());
            assert_eq!(state.rebuild_count(), 0);

            state
                .admit(
                    input_entry(&sort, &inputs[4], 5),
                    &mut heap,
                    2,
                    &mut budget,
                    &mut scope,
                )
                .expect("tie admission 0");
            model_insert(&mut model, &inputs[4], 2);
            assert!(!state.force_rebuild_pending());
            assert_eq!(state.rebuild_count(), 1);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["0", "a"]);

            state
                .admit(
                    input_entry(&sort, &inputs[5], 6),
                    &mut heap,
                    2,
                    &mut budget,
                    &mut scope,
                )
                .expect("reappearance aa");
            model_insert(&mut model, &inputs[5], 2);
            assert_valid_state(
                &state,
                &heap,
                &model,
                structural,
                initial_scratch,
                &budget,
                scope.as_ref(),
            );
            assert_best_first(&heap, &model, &["aa", "0"]);
            drop(heap);
            drop(state);
        }

        // ------------------------------------------------------------------
        // A-U09: nine independent corrupt states with a real scope.
        // ------------------------------------------------------------------
        #[derive(Clone, Copy, Debug)]
        enum Corrupt {
            CountMismatch,
            MissingWorst,
            ScratchNonempty,
            ZeroBound,
            AboveBound,
            BoundExceeded,
            LiveUnderflow,
            LiveOverflow,
            OverlapOverflow,
        }

        #[test]
        fn a_u09_corrupt_state_is_rejected_before_mutation() {
            for case in [
                Corrupt::CountMismatch,
                Corrupt::MissingWorst,
                Corrupt::ScratchNonempty,
                Corrupt::ZeroBound,
                Corrupt::AboveBound,
                Corrupt::BoundExceeded,
                Corrupt::LiveUnderflow,
                Corrupt::LiveOverflow,
                Corrupt::OverlapOverflow,
            ] {
                let sort = Sort::default();
                let inputs = [
                    input_record("a".to_owned(), 1.0),
                    input_record("bb".to_owned(), 2.0),
                    input_record("cccc".to_owned(), 9.0),
                ];
                let mut budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                let mut meter = BatchMemoryMeter::new(GENEROUS);
                {
                    let mut scope = Some(SlotMemoryScope::new(&mut meter));
                    let mut heap = BinaryHeap::new();
                    let mut state = State::for_test_accounted(
                        Kind::ExactSet,
                        Profile::P2,
                        1,
                        &mut budget,
                        &mut scope,
                    )
                    .expect("K=1");
                    let structural = initial_structural_charge(&state);
                    let initial_scratch = state.exact_scratch.capacity();
                    let mut model: Vec<&InputRecord> = Vec::new();
                    for (doc_id, input) in inputs[..2].iter().enumerate() {
                        state
                            .admit(
                                input_entry(&sort, input, doc_id as u64),
                                &mut heap,
                                2,
                                &mut budget,
                                &mut scope,
                            )
                            .expect("fill admission");
                        model_insert(&mut model, input, 2);
                        assert_valid_state(
                            &state,
                            &heap,
                            &model,
                            structural,
                            initial_scratch,
                            &budget,
                            scope.as_ref(),
                        );
                    }
                    assert_eq!(local_balance(&budget), structural + 134);
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 134);
                    assert_eq!(state.rebuild_count(), 0);

                    let mut offered = input_entry(&sort, &inputs[2], 9);
                    let heap_limit = match case {
                        Corrupt::ZeroBound => 0,
                        Corrupt::AboveBound => 3,
                        Corrupt::BoundExceeded => 1,
                        _ => 2,
                    };
                    match case {
                        Corrupt::CountMismatch => {
                            state.keys.remove(&key("a"));
                        }
                        Corrupt::MissingWorst => {
                            state.keys.remove(&key("a"));
                            state.keys.insert(key("z"));
                        }
                        Corrupt::ScratchNonempty => state.exact_scratch.push(key("stray")),
                        Corrupt::BoundExceeded => state.exact_retained_limit = 1,
                        Corrupt::LiveUnderflow => state.exact_live_key_charged = 0,
                        Corrupt::LiveOverflow => state.exact_live_key_charged = u64::MAX,
                        Corrupt::OverlapOverflow => offered.charge = u64::MAX,
                        Corrupt::ZeroBound | Corrupt::AboveBound => {}
                    }
                    state.force_rebuild_next_admit();
                    let before = snapshot(&state, &heap, &budget, scope.as_ref());
                    let error = state
                        .admit(offered, &mut heap, heap_limit, &mut budget, &mut scope)
                        .expect_err("corrupt state must be rejected");
                    match case {
                        Corrupt::CountMismatch => {
                            assert_corrupt(error, "exact-set retained keys disagree with heap")
                        }
                        Corrupt::MissingWorst => {
                            assert_corrupt(error, "exact-set is missing the retained worst key")
                        }
                        Corrupt::ScratchNonempty => {
                            assert_corrupt(error, "exact-set scratch was not empty at admission")
                        }
                        Corrupt::ZeroBound | Corrupt::AboveBound => {
                            assert_corrupt(error, "exact-set retained limit is invalid")
                        }
                        Corrupt::BoundExceeded => assert_corrupt(
                            error,
                            "exact-set retained keys exceed the reserved bound",
                        ),
                        Corrupt::LiveUnderflow => {
                            assert_corrupt(error, "exact-set live key charge underflow")
                        }
                        Corrupt::LiveOverflow | Corrupt::OverlapOverflow => {
                            assert_limit(error, u64::MAX, u64::MAX)
                        }
                    }
                    assert_eq!(state.rebuild_count(), 0, "{case:?} must not rebuild");
                    assert!(state.force_rebuild_pending(), "{case:?} keeps the flag");
                    assert_eq!(
                        snapshot(&state, &heap, &budget, scope.as_ref()),
                        before,
                        "{case:?} must not mutate the state"
                    );
                    assert_eq!(local_balance(&budget), structural + 134);
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 134);
                    drop(heap);
                    drop(state);
                    if let Some(scope_ref) = scope.as_mut() {
                        scope_ref.finish_failure().unwrap();
                        assert_eq!(scope_ref.temporary_bytes(), 0);
                    }
                    drop(scope);
                    assert_eq!(meter.current(), 0);
                    assert_eq!(meter.peak(), structural + 134, "{case:?} scope peak");
                }
            }
        }

        // ------------------------------------------------------------------
        // A-U10: constructor faults and four complete reserve-guard snapshots.
        // ------------------------------------------------------------------
        #[test]
        fn a_u10_constructor_faults_and_reserve_guard() {
            for (fault, limit) in [(ReserveFault::Set, 10u64), (ReserveFault::Scratch, 9u64)] {
                let mut budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                budget.reserve_global_bytes(11).unwrap();
                let mut meter = BatchMemoryMeter::new(GENEROUS);
                meter.reserve_memory(7).unwrap();
                {
                    let mut scope = Some(SlotMemoryScope::new(&mut meter));
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                    let error = State::for_test_accounted_with_builder_and_fault(
                        std::collections::hash_map::RandomState::default(),
                        Kind::ExactSet,
                        Profile::P2,
                        8,
                        &mut budget,
                        &mut scope,
                        fault,
                    )
                    .expect_err("constructor fault must fail");
                    assert_limit(error, limit, limit);
                    assert_eq!(local_balance(&budget), 11);
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                }
                assert_eq!(meter.current(), 7, "{fault:?} prior meter balance");
                assert_eq!(meter.peak(), 7, "{fault:?} prior meter peak");
                meter.release_memory(7).unwrap();
                assert_eq!(meter.current(), 0);
            }

            // Row a: a genuine accounted empty state with a real structural charge.
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            let structural = {
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    4,
                    &mut budget,
                    &mut scope,
                )
                .expect("K=4 accounted");
                let structural = initial_structural_charge(&state);
                assert!(structural > 0, "genuine structural charge");
                assert_eq!(state.exact_table_charged, structural);
                assert_eq!(state.exact_live_key_charged, 0);
                let before = snapshot(&state, &heap, &budget, scope.as_ref());
                let error = state
                    .reserve_exact_set(4)
                    .expect_err("a charged state must reject a second reservation");
                assert_corrupt(
                    error,
                    "exact-set reservation requires an empty, uncharged state",
                );
                assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);
                assert_eq!(local_balance(&budget), structural);
                assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural);
                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                structural
            };
            assert_eq!(meter.current(), 0);
            assert_eq!(meter.peak(), structural, "guard row a peak");

            // Rows b, c, d: unaccounted logical faults on fresh, genuinely empty states.
            for row in 0..3u8 {
                let budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                let mut meter = BatchMemoryMeter::new(GENEROUS);
                {
                    let mut scope = Some(SlotMemoryScope::new(&mut meter));
                    let heap = BinaryHeap::new();
                    let mut state = unaccounted_plain(4);
                    assert_eq!(state.exact_table_charged, 0);
                    assert_eq!(state.exact_live_key_charged, 0);
                    match row {
                        0 => state.exact_live_key_charged = 1,
                        1 => {
                            assert!(state.keys.insert(key("x")));
                        }
                        _ => state.exact_scratch.push(key("y")),
                    }
                    let before = snapshot(&state, &heap, &budget, scope.as_ref());
                    let error = state
                        .reserve_exact_set(4)
                        .expect_err("a non-empty state must reject a reservation");
                    assert_corrupt(
                        error,
                        "exact-set reservation requires an empty, uncharged state",
                    );
                    assert_eq!(snapshot(&state, &heap, &budget, scope.as_ref()), before);
                    assert_eq!(local_balance(&budget), 0, "row {row} local balance");
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                    drop(heap);
                    drop(state);
                    if let Some(scope_ref) = scope.as_mut() {
                        scope_ref.finish_failure().unwrap();
                        assert_eq!(scope_ref.temporary_bytes(), 0);
                    }
                }
                assert_eq!(meter.current(), 0);
                assert_eq!(meter.peak(), 0, "guard row {row} peak");
            }
        }

        // ------------------------------------------------------------------
        // A-U11: three cleanup modes and a fully checked follow-up query.
        // ------------------------------------------------------------------
        fn a_u11_case(mode: u8) {
            let sort = Sort::default();
            let inputs = [
                input_record("a".to_owned(), 1.0),
                input_record("bb".to_owned(), 2.0),
                input_record("cccc".to_owned(), 9.0),
            ];
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            meter.reserve_memory(7).unwrap();
            let structural = {
                let mut budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let mut heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    1,
                    &mut budget,
                    &mut scope,
                )
                .expect("K=1");
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                let model = fill(
                    &mut state,
                    &mut heap,
                    &sort,
                    &mut budget,
                    &mut scope,
                    &inputs,
                    2,
                );
                let current = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(current, structural + 140);
                assert_eq!(local_balance(&budget), structural + 140);
                assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 140);
                drop(heap);
                drop(state);
                match mode {
                    0 => scope.as_mut().unwrap().finish_success(0).unwrap(),
                    1 => scope.as_mut().unwrap().finish_failure().unwrap(),
                    _ => {}
                }
                if mode != 2 {
                    assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
                }
                structural
            };
            assert_eq!(meter.current(), 7);
            assert_eq!(meter.peak(), 7 + structural + 207, "first query peak");

            {
                let mut budget = CandidateBudget::new(
                    &SearchLimits::default()
                        .with_max_total_candidate_bytes(GENEROUS)
                        .unwrap(),
                );
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let mut heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    1,
                    &mut budget,
                    &mut scope,
                )
                .expect("follow-up K=1");
                assert_eq!(state.key_count(), 0);
                assert!(state.scratch_is_empty());
                assert!(!state.force_rebuild_pending());
                assert_eq!(state.rebuild_count(), 0);
                let structural = initial_structural_charge(&state);
                let initial_scratch = state.exact_scratch.capacity();
                let model = fill(
                    &mut state,
                    &mut heap,
                    &sort,
                    &mut budget,
                    &mut scope,
                    &inputs[..1],
                    2,
                );
                let current = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                assert_eq!(current, structural + 66);
                assert_eq!(local_balance(&budget), structural + 66);
                assert_eq!(scope.as_ref().unwrap().temporary_bytes(), structural + 66);
                drop(heap);
                drop(state);
                scope.as_mut().unwrap().finish_success(0).unwrap();
                assert_eq!(scope.as_ref().unwrap().temporary_bytes(), 0);
            }
            assert_eq!(meter.current(), 7);
            assert_eq!(
                meter.peak(),
                7 + structural + 207,
                "follow-up keeps the peak"
            );
            meter.release_memory(7).unwrap();
            assert_eq!(meter.current(), 0);
        }

        #[test]
        fn a_u11_cleanup_paths_and_follow_up_query() {
            for mode in [0u8, 1, 2] {
                a_u11_case(mode);
            }
        }

        // ------------------------------------------------------------------
        // A-U12: actual 1,025 x 1,024 population and the final sentinel.
        // ------------------------------------------------------------------
        #[test]
        fn a_u12_populated_maximum_includes_scratch_and_sentinel() {
            let sort = Sort::default();
            let retained = 1025usize;
            let inputs: Vec<InputRecord> = (0..retained)
                .map(|index| {
                    input_record(
                        churn_key(&format!("init-{:04}-{index:06}-", 1024), Some(LONG_KEY)),
                        (retained - index) as f64,
                    )
                })
                .collect();
            assert!(inputs.iter().all(|input| input.key.len() == LONG_KEY));
            let mut budget = CandidateBudget::new(
                &SearchLimits::default()
                    .with_max_total_candidate_bytes(GENEROUS)
                    .unwrap(),
            );
            let mut meter = BatchMemoryMeter::new(GENEROUS);
            let structural = {
                let mut scope = Some(SlotMemoryScope::new(&mut meter));
                let mut heap = BinaryHeap::new();
                let mut state = State::for_test_accounted(
                    Kind::ExactSet,
                    Profile::P2,
                    1024,
                    &mut budget,
                    &mut scope,
                )
                .expect("K=1024");
                let structural = initial_structural_charge(&state);
                let initial_set_capacity = state.keys.capacity();
                let initial_scratch = state.exact_scratch.capacity();
                assert_eq!(
                    structural,
                    initial_set_capacity as u64 * 40
                        + initial_scratch as u64 * std::mem::size_of::<DocumentKey>() as u64
                );
                assert_eq!(state.retained_limit_for_test(), retained);
                assert!(initial_scratch >= retained);
                let mut model: Vec<&InputRecord> = Vec::new();
                for (doc_id, input) in inputs.iter().enumerate() {
                    state
                        .admit(
                            input_entry(&sort, input, doc_id as u64),
                            &mut heap,
                            retained,
                            &mut budget,
                            &mut scope,
                        )
                        .unwrap_or_else(|error| panic!("fill {doc_id}: {error:?}"));
                    model_insert(&mut model, input, retained);
                    assert_valid_state(
                        &state,
                        &heap,
                        &model,
                        structural,
                        initial_scratch,
                        &budget,
                        scope.as_ref(),
                    );
                }
                assert_eq!(state.keys.len(), retained);
                assert_eq!(heap.len(), retained);
                assert_eq!(state.retained_limit_for_test(), retained);
                assert!(state.scratch_is_empty());
                assert_eq!(state.exact_scratch.capacity(), initial_scratch);
                let sentinel = &inputs[retained - 1];
                assert!(
                    state.contains_key(&key(&sentinel.key)),
                    "final sentinel present"
                );
                assert!(
                    heap.iter()
                        .any(|candidate| candidate.hit.key.as_str() == sentinel.key.as_str()),
                    "final sentinel retained in the heap"
                );
                let current = assert_valid_state(
                    &state,
                    &heap,
                    &model,
                    structural,
                    initial_scratch,
                    &budget,
                    scope.as_ref(),
                );
                let model_bytes = model_key_bytes(&model);
                assert_eq!(model_bytes, 1_049_600);
                let set_bytes: u64 = state.keys.iter().map(|key| key.as_str().len() as u64).sum();
                assert_eq!(set_bytes, 1_049_600);
                assert_eq!(set_bytes, model_bytes);
                assert_eq!(current, structural + 1025 * 1088 + 1_049_600);
                assert_eq!(current, structural + 2_164_800);
                let auxiliary = structural + set_bytes;
                assert!(auxiliary <= 2_097_152, "auxiliary estimate {auxiliary}");
                drop(heap);
                drop(state);
                if let Some(scope_ref) = scope.as_mut() {
                    scope_ref.finish_failure().unwrap();
                    assert_eq!(scope_ref.temporary_bytes(), 0);
                }
                structural
            };
            assert_eq!(meter.current(), 0);
            assert_eq!(meter.peak(), structural + 2_164_800, "populated peak");
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

/// One bounded top-K entry. `Ord` delegates to the canonical comparator and
/// orders **better** candidates as `Less`, so `BinaryHeap::peek` is the worst
/// retained candidate and `into_sorted_vec` yields best-first.
struct MixedEntry<'a> {
    hit: SelectedHit,
    charge: u64,
    sort: &'a Sort,
    relevance: bool,
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
            default_relevance_cmp(&self.hit, &other.hit)
        } else {
            compare_candidates(
                &self.hit.sort_tuple,
                &self.hit.key,
                &other.hit.sort_tuple,
                &other.hit.key,
                self.sort,
            )
        }
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
            assert_eq!(b_observation::borrowed_value_reads(), 50_000);
            // Only the K+1 heap entries (and replacements) own a tuple.
            assert!(
                b_observation::owned_tuple_materializations() <= top_k + 1,
                "owned={}",
                b_observation::owned_tuple_materializations()
            );
            assert_eq!(
                b_observation::rejected_without_materialization(),
                50_000 - b_observation::owned_tuple_materializations()
            );
            assert_eq!(b_observation::legacy_candidate_fallbacks(), 0);
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
        let mut state = State::for_test(Kind::ExactSet, Profile::P0, 8);
        let mut b = CandidateBudget::new(
            &SearchLimits::default()
                .with_max_total_candidate_bytes(66)
                .unwrap(),
        );
        let mut scope: Option<SlotMemoryScope<'_>> = None;
        state
            .admit(entry(&sort, "a", 1.0, 0), &mut heap, 1, &mut b, &mut scope)
            .unwrap();
        let error = state
            .admit(entry(&sort, "b", 9.0, 1), &mut heap, 1, &mut b, &mut scope)
            .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
        assert!(state.contains_key(&key("a")));
        assert!(!state.contains_key(&key("b")));
        assert_eq!(state.key_count(), heap.len());
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
        // RF09-14: the fixed structural reservation also covers the scratch vector.
        let estimate = capacity
            .checked_mul(40)
            .and_then(|v| {
                v.checked_add(
                    state.scratch_capacity_for_test() * std::mem::size_of::<DocumentKey>(),
                )
            })
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
