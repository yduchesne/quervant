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
use std::collections::{BTreeMap, BTreeSet, BinaryHeap};
use std::rc::Rc;

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::aggregation::{Aggregation, AggregationResult};
use crate::contract::budget::Budgets;
use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::query::Query;
use crate::contract::result::{Projection, Sort, TopK};
use crate::contract::schema::Schema;
use crate::index::ReaderSnapshot;
use crate::segment::SegmentReader;

use super::SearchLimits;
use super::analytics::{AggregateRequest, AggregationEngine, TimeBucket};
use super::batch_meter::BatchExecutionMeter;
use super::error::{SearchError, SearchResult};
use super::execute::{self, CandidateBudget, LeafData, SearchWork, VisitControl};
use super::expand::expand_query;
use super::memory::{MemoryCharge, SlotMemoryScope};
use super::projection::{
    ProjectionLedger, ProjectionPlan, projected_field_bytes, projected_hit_bytes,
};
use super::score::compute_stats;
use super::typed::{self, ScanGuard, TypedPlan};
use super::typed_compare::{ColumnAccess, SortValue, compare_candidates, sort_tuple_for_doc};
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

/// A snapshot-bound compound searcher.
pub struct UnifiedSearcher<'a> {
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    limits: SearchLimits,
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
        }
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
        let mut total_hits = 0u64;
        for (segment_index, reader) in readers.iter().enumerate() {
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
            for (doc_id, score) in scored {
                total_hits = total_hits
                    .checked_add(1)
                    .ok_or(SearchError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
                let key = reader.doc_key(doc_id)?;
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
                if heap
                    .iter()
                    .any(|existing| existing.hit.key == entry.hit.key)
                {
                    return Err(SearchError::CorruptIndex {
                        detail: "duplicate live document key across segments".to_owned(),
                    });
                }
                if heap.len() < heap_limit {
                    let mut heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                        .as_mut()
                        .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                    heap_preflight_insert(&budget, heap_memory.as_deref(), charge)?;
                    heap_commit_insert(&mut budget, heap_memory.as_deref_mut(), charge)?;
                    heap.push(entry);
                } else {
                    let worst = heap.peek().expect("heap is nonempty");
                    if entry.cmp(worst) == Ordering::Less {
                        let old_charge = worst.charge;
                        // Conservative overlap: the old entry remains charged
                        // while the replacement is admitted.
                        let mut heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                            .as_mut()
                            .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                        heap_preflight_insert(&budget, heap_memory.as_deref(), charge)?;
                        heap_preflight_release(&budget, heap_memory.as_deref(), old_charge)?;
                        heap_commit_insert(&mut budget, heap_memory.as_deref_mut(), charge)?;
                        let evicted = heap.pop().expect("heap is nonempty");
                        drop(evicted);
                        let mut heap_memory: Option<&mut (dyn MemoryCharge + '_)> = scope
                            .as_mut()
                            .map(|sink| sink as &mut (dyn MemoryCharge + '_));
                        heap_commit_release(&mut budget, heap_memory.as_deref_mut(), old_charge)?;
                        heap.push(entry);
                    }
                }
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
