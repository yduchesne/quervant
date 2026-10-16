//! Snapshot-bound typed numeric/temporal search and exact bounded analytics
//! (PR 10).
//!
//! `TypedSearcher` validates every query, sort, metric and limit **before** any
//! segment is opened, evaluates a deliberately small typed boolean subset over
//! the PR 9 effective-live documents, and produces deterministic responses with
//! generation/view identity and scan diagnostics. It never mutates the index and
//! never returns a partial response after an error or cancellation.

use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap};
use std::net::IpAddr;

use sha2::{Digest, Sha256};

use crate::analysis::Cancellation;
use crate::contract::budget::{BudgetKind, Budgets};
use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::query::{Bound, GeoPolygon, JsonPathExpr, JsonPathSegment, Query};
use crate::contract::result::{MultiValueSelector, Sort, SortField, TopK};
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue, IpNetwork};
use crate::index::ReaderSnapshot;
use crate::segment::{
    ABSENT_INDEX, JsonOccurrence, JsonScalar, MAX_JSON_PATH_DEPTH, MAX_JSON_PATH_MEMBER_BYTES,
    SegmentReader, SpatialField, SpatialIndex, SpatialNode, extract_field_paths, node_is_array,
    node_is_null, node_matches_scalar, node_to_field_value, occurrence_is_immediate_index_child,
    occurrence_matches_range, path_equals, path_matches,
};

use super::geo;

use super::analytics::{
    AggregateLimits, AggregateMetric, AggregateRequest, AggregateResponse, AggregationEngine,
    GroupValue, MAX_GROUP_FIELDS, MetricInput, TimeBucket, bucket_start,
};
use super::error::{SearchError, SearchResult};
use super::limits::SearchLimits;
use super::typed_compare::{
    ColumnAccess, GeoSortDistances, SortValue, canonical_scalar_bytes, canonical_scalar_cmp,
    compare_candidates, is_min_max_type, is_range_type, is_sum_type, is_typed_scalar,
    matches_range, matches_time_range, sort_tuple_for_doc,
};

/// Scan diagnostics for one typed request.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct TypedScanDiagnostics {
    /// Segments visited by the scan (including time-pruned segments).
    pub segments_considered: u64,
    /// Segments skipped without reading columns using persisted time bounds.
    pub segments_skipped_by_time: u64,
    /// Effective-live documents examined.
    pub live_documents_examined: u64,
    /// Documents whose typed query matched.
    pub matching_documents: u64,
}

/// One typed result.
#[derive(Debug, Clone, PartialEq)]
pub struct TypedHit {
    /// Byte-exact logical document key.
    pub key: DocumentKey,
    /// The document's sort tuple, in request order.
    pub sort_values: Vec<SortValue>,
}

/// An opaque, snapshot- and query/sort-bound typed search-after cursor.
///
/// The cursor is intentionally not serializable and not portable across
/// processes or snapshots. Its fields are private; it is created by a search
/// response and passed back unchanged.
#[derive(Debug, Clone, PartialEq)]
pub struct TypedCursor {
    snapshot_binding: u64,
    fingerprint: [u8; 32],
    last_sort: Vec<SortValue>,
    last_key: DocumentKey,
}

impl TypedCursor {
    fn new(
        snapshot_binding: u64,
        fingerprint: [u8; 32],
        last_sort: Vec<SortValue>,
        last_key: DocumentKey,
    ) -> Self {
        Self {
            snapshot_binding,
            fingerprint,
            last_sort,
            last_key,
        }
    }

    /// The snapshot binding this cursor was created from.
    #[must_use]
    pub const fn snapshot_binding(&self) -> u64 {
        self.snapshot_binding
    }

    /// The logical key of the last returned hit.
    #[must_use]
    pub const fn last_key(&self) -> &DocumentKey {
        &self.last_key
    }

    /// The sort tuple of the last returned hit.
    #[must_use]
    pub fn last_sort_values(&self) -> &[SortValue] {
        &self.last_sort
    }
}

/// A typed search request.
#[derive(Debug, Clone, PartialEq)]
pub struct TypedSearchRequest {
    /// Typed boolean query.
    pub query: Query,
    /// Deterministic total sort order.
    pub sort: Sort,
    /// Bounded page size.
    pub top_k: TopK,
    /// Search-after cursor from a previous page.
    pub after: Option<TypedCursor>,
    /// Runtime-only primary timestamp selector.
    pub primary_time_field: Option<String>,
}

/// A complete typed search response.
#[derive(Debug, Clone, PartialEq)]
pub struct TypedSearchResponse {
    /// Best-first hits for this page.
    pub hits: Vec<TypedHit>,
    /// Exact count of matching effective-live documents before page truncation.
    pub total_hits: u64,
    /// Continuation cursor when another candidate remains.
    pub next_cursor: Option<TypedCursor>,
    /// Committed generation echoed from the snapshot.
    pub generation: Option<u64>,
    /// Process-local view ordinal echoed from the snapshot.
    pub view_ordinal: u64,
    /// Scan diagnostics.
    pub diagnostics: TypedScanDiagnostics,
}

/// Shared deterministic work meter with periodic cancellation polling.
pub(crate) struct ScanGuard<'a> {
    used: u64,
    limit: u64,
    next_check: u64,
    cancel: &'a dyn Cancellation,
}

impl<'a> ScanGuard<'a> {
    pub(crate) fn new(limit: u64, cancel: &'a dyn Cancellation) -> Self {
        Self {
            used: 0,
            limit,
            next_check: 256,
            cancel,
        }
    }

    pub(crate) fn charge(&mut self, units: u64) -> SearchResult<()> {
        self.used = self
            .used
            .checked_add(units)
            .ok_or(SearchError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })?;
        if self.used > self.limit {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: self.used,
            });
        }
        if self.used >= self.next_check {
            self.poll()?;
            self.next_check = self.used.saturating_add(256);
        }
        Ok(())
    }

    pub(crate) fn poll(&self) -> SearchResult<()> {
        if self.cancel.is_cancelled() {
            Err(SearchError::Cancelled)
        } else {
            Ok(())
        }
    }
}

struct FieldPlan {
    id: u32,
    field_type: FieldType,
    columnar: bool,
    indexed: bool,
    cardinality: Cardinality,
}

struct TypedPlan {
    fields: BTreeMap<String, FieldPlan>,
    primary_time: Option<String>,
}

impl TypedPlan {
    fn build(schema: &Schema) -> Self {
        // Contract `Schema::fields()` iterates a `BTreeMap` in ascending name
        // order, which is exactly how `CodecSchema::from_contract` assigns ids.
        let fields = schema
            .fields()
            .enumerate()
            .map(|(id, definition)| {
                (
                    definition.name.clone(),
                    FieldPlan {
                        id: u32::try_from(id).unwrap_or(u32::MAX),
                        field_type: definition.field_type,
                        columnar: definition.options.columnar,
                        indexed: definition.options.indexed,
                        cardinality: definition.cardinality,
                    },
                )
            })
            .collect();
        Self {
            fields,
            primary_time: schema.primary_timestamp().map(str::to_owned),
        }
    }

    fn field(&self, name: &str) -> Option<&FieldPlan> {
        self.fields.get(name)
    }
}

/// A concrete typed searcher bound to one immutable snapshot.
pub struct TypedSearcher<'a> {
    snapshot: &'a ReaderSnapshot,
    schema: &'a Schema,
    limits: SearchLimits,
    pruning_disabled: bool,
}

impl<'a> TypedSearcher<'a> {
    /// Bind a typed searcher to a snapshot, schema and explicit limits.
    #[must_use]
    pub fn new(snapshot: &'a ReaderSnapshot, schema: &'a Schema, limits: SearchLimits) -> Self {
        Self {
            snapshot,
            schema,
            limits,
            pruning_disabled: false,
        }
    }

    /// Test-only: disable persisted time-bound pruning for differential testing.
    #[doc(hidden)]
    #[must_use]
    pub fn with_pruning_disabled(mut self, disabled: bool) -> Self {
        self.pruning_disabled = disabled;
        self
    }

    /// The configured limits.
    #[must_use]
    pub const fn limits(&self) -> &SearchLimits {
        &self.limits
    }

    /// Execute a typed paginated search.
    pub fn search(
        &self,
        request: &TypedSearchRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<TypedSearchResponse> {
        cancel_check(cancel)?;
        let plan = TypedPlan::build(self.schema);
        let compiled = self.validate_search(request, budgets, &plan)?;
        let fingerprint = fingerprint(&compiled, &request.sort)?;
        if let Some(cursor) = &request.after {
            if cursor.snapshot_binding != self.snapshot.binding_id() {
                return Err(cursor_pit_error());
            }
            if cursor.fingerprint != fingerprint {
                return Err(cursor_sort_error());
            }
        }
        let work_limit = self
            .limits
            .max_total_work_units()
            .min(self.limits.max_typed_work_units());
        let max_heap_bytes = self
            .limits
            .max_total_candidate_bytes()
            .min(self.limits.max_topk_heap_bytes());
        let positive = collect_positive_time(&request.query);
        let prune = !self.pruning_disabled;
        let mut accumulator = SearchAccumulator {
            sort: &request.sort,
            top_k: request.top_k.limit,
            limit_entries: request.top_k.limit.saturating_add(1),
            heap: BinaryHeap::new(),
            heap_bytes: 0,
            max_heap_bytes,
            total_hits: 0,
            after: request.after.as_ref(),
            snapshot_binding: self.snapshot.binding_id(),
            fingerprint,
        };
        let mut guard = ScanGuard::new(work_limit, cancel);
        let diagnostics = {
            let mut visit = |guard: &mut ScanGuard<'_>,
                             reader: &SegmentReader,
                             columns: &ColumnAccess<'_>,
                             json: &JsonAccess<'_>,
                             geo: Option<&GeoSortDistances>,
                             doc_id: u64| {
                accumulator.accept(guard, reader, columns, json, geo, doc_id)
            };
            self.scan(
                &plan,
                &compiled,
                &positive,
                prune,
                Some(&request.sort),
                &mut guard,
                &mut visit,
            )?
        };
        let total_hits = accumulator.total_hits;
        let (hits, next_cursor) = accumulator.finish()?;
        Ok(TypedSearchResponse {
            hits,
            total_hits,
            next_cursor,
            generation: self.snapshot.generation(),
            view_ordinal: self.snapshot.view_ordinal(),
            diagnostics,
        })
    }

    /// Execute an exact bounded aggregation.
    pub fn aggregate(
        &self,
        request: &AggregateRequest,
        budgets: &Budgets,
        cancel: &dyn Cancellation,
    ) -> SearchResult<AggregateResponse> {
        cancel_check(cancel)?;
        let plan = TypedPlan::build(self.schema);
        let (resolved_bucket, compiled) = self.validate_aggregate(request, budgets, &plan)?;
        let work_limit = self
            .limits
            .max_total_work_units()
            .min(self.limits.max_typed_work_units());
        let agg_limits = aggregate_limits(self.limits, budgets);
        let mut engine = AggregationEngine::new(
            &request.metrics,
            request.frequency_top_k.as_ref(),
            resolved_bucket.as_ref(),
            self.schema,
            agg_limits,
        );
        if request.group_fields.is_empty() && resolved_bucket.is_none() {
            engine.ensure_global_group()?;
        }
        let positive = collect_positive_time(&request.query);
        let prune = !self.pruning_disabled;
        let mut guard = ScanGuard::new(work_limit, cancel);
        let diagnostics = {
            let mut visit = |guard: &mut ScanGuard<'_>,
                             _reader: &SegmentReader,
                             columns: &ColumnAccess<'_>,
                             _json: &JsonAccess<'_>,
                             _geo: Option<&GeoSortDistances>,
                             doc_id: u64| {
                visit_aggregate(
                    guard,
                    &mut engine,
                    &plan,
                    request,
                    resolved_bucket.as_ref(),
                    columns,
                    doc_id,
                )
            };
            self.scan(
                &plan, &compiled, &positive, prune, None, &mut guard, &mut visit,
            )?
        };
        let groups = engine.finish(request.frequency_top_k.as_ref().map(|f| f.limit))?;
        Ok(AggregateResponse {
            groups,
            diagnostics,
            generation: self.snapshot.generation(),
            view_ordinal: self.snapshot.view_ordinal(),
        })
    }

    fn validate_search(
        &self,
        request: &TypedSearchRequest,
        budgets: &Budgets,
        plan: &TypedPlan,
    ) -> SearchResult<Compiled> {
        request.query.validate(self.schema, budgets)?;
        request.top_k.validate(budgets)?;
        let compiled = compile_query(&request.query, plan)?;
        request.sort.validate(self.schema)?;
        for field in &request.sort.fields {
            let Some(plan) = plan.field(&field.field) else {
                return Err(unsupported("sort_field"));
            };
            if field.distance_from.is_some() {
                if plan.field_type != FieldType::GeoPoint || !plan.indexed {
                    return Err(unsupported("sort_type"));
                }
                continue;
            }
            if field.json_path.is_some() {
                if plan.field_type != FieldType::Json || !plan.indexed {
                    return Err(unsupported("sort_type"));
                }
                let needs_selector = plan.cardinality == Cardinality::Multi
                    || field
                        .json_path
                        .as_ref()
                        .is_some_and(|path| !path.is_concrete());
                if needs_selector && field.multi.is_none() {
                    return Err(SearchError::Query(QueryError::InvalidQuery(
                        InvalidQueryReason::MultiValueSelectorRequired {
                            field: field.field.clone(),
                        },
                    )));
                }
                continue;
            }
            if !plan.columnar || !is_typed_scalar(plan.field_type) {
                return Err(unsupported("sort_type"));
            }
            if plan.cardinality == Cardinality::Multi && field.multi.is_none() {
                return Err(SearchError::Query(QueryError::InvalidQuery(
                    InvalidQueryReason::MultiValueSelectorRequired {
                        field: field.field.clone(),
                    },
                )));
            }
        }
        if let Some(field) = &request.primary_time_field {
            let Some(plan) = plan.field(field) else {
                return Err(unsupported("primary_time_field"));
            };
            if !plan.columnar
                || plan.field_type != FieldType::Timestamp
                || plan.cardinality != Cardinality::Single
            {
                return Err(unsupported("primary_time_field"));
            }
        }
        Ok(compiled)
    }

    fn validate_aggregate(
        &self,
        request: &AggregateRequest,
        budgets: &Budgets,
        plan: &TypedPlan,
    ) -> SearchResult<(Option<TimeBucket>, Compiled)> {
        request.query.validate(self.schema, budgets)?;
        if request.group_fields.len() > MAX_GROUP_FIELDS {
            return Err(SearchError::Query(QueryError::BudgetExceeded {
                kind: BudgetKind::GroupKeyFields,
            }));
        }
        if let Some(max) = budgets.get(BudgetKind::GroupKeyFields) {
            if u64::try_from(request.group_fields.len()).unwrap_or(u64::MAX) > max {
                return Err(SearchError::Query(QueryError::BudgetExceeded {
                    kind: BudgetKind::GroupKeyFields,
                }));
            }
        }
        for field in &request.group_fields {
            let Some(plan) = plan.field(field) else {
                return Err(SearchError::Query(QueryError::InvalidQuery(
                    InvalidQueryReason::UnknownField {
                        field: field.clone(),
                    },
                )));
            };
            if !plan.columnar || !is_typed_scalar(plan.field_type) {
                return Err(unsupported("group_field_type"));
            }
        }
        if let Some(field) = &request.primary_time_field {
            if plan.field(field).is_none() {
                return Err(unsupported("primary_time_field"));
            }
        }
        let resolved_bucket = self.resolve_bucket(request, plan)?;
        if let Some(bucket) = &resolved_bucket {
            let Some(plan) = plan.field(&bucket.field) else {
                return Err(unsupported("time_bucket_field"));
            };
            if !plan.columnar
                || plan.field_type != FieldType::Timestamp
                || plan.cardinality != Cardinality::Single
            {
                return Err(unsupported("time_bucket_field"));
            }
        }
        for metric in &request.metrics {
            match metric {
                AggregateMetric::Count => {}
                AggregateMetric::Sum { field } | AggregateMetric::Avg { field } => {
                    let Some(plan) = plan.field(field) else {
                        return Err(unknown_field(field));
                    };
                    if !plan.columnar || !is_sum_type(plan.field_type) {
                        return Err(unsupported("metric_sum_type"));
                    }
                }
                AggregateMetric::Min { field } | AggregateMetric::Max { field } => {
                    let Some(plan) = plan.field(field) else {
                        return Err(unknown_field(field));
                    };
                    if !plan.columnar || !is_min_max_type(plan.field_type) {
                        return Err(unsupported("metric_min_max_type"));
                    }
                }
                AggregateMetric::ExactDistinct { field } => {
                    let Some(plan) = plan.field(field) else {
                        return Err(unknown_field(field));
                    };
                    if !plan.columnar || !is_typed_scalar(plan.field_type) {
                        return Err(unsupported("metric_distinct_type"));
                    }
                }
            }
        }
        if let Some(frequency) = &request.frequency_top_k {
            if frequency.limit == 0 {
                return Err(SearchError::ResourceLimit {
                    limit: self.limits.max_frequency_top_k(),
                    requested: 0,
                });
            }
            if u64::try_from(frequency.limit).unwrap_or(u64::MAX)
                > self.limits.max_frequency_top_k()
            {
                return Err(SearchError::ResourceLimit {
                    limit: self.limits.max_frequency_top_k(),
                    requested: u64::try_from(frequency.limit).unwrap_or(u64::MAX),
                });
            }
            let Some(plan) = plan.field(&frequency.field) else {
                return Err(unknown_field(&frequency.field));
            };
            if !plan.columnar || !is_typed_scalar(plan.field_type) {
                return Err(unsupported("frequency_type"));
            }
        }
        let compiled = compile_query(&request.query, plan)?;
        Ok((resolved_bucket, compiled))
    }

    fn resolve_bucket(
        &self,
        request: &AggregateRequest,
        plan: &TypedPlan,
    ) -> SearchResult<Option<TimeBucket>> {
        let Some(bucket) = &request.time_bucket else {
            return Ok(None);
        };
        if bucket.width_micros <= 0 {
            return Err(SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::InvalidTimeBucket,
            )));
        }
        let field = if bucket.field.is_empty() {
            request
                .primary_time_field
                .clone()
                .or_else(|| plan.primary_time.clone())
                .ok_or_else(|| unsupported("time_bucket_field"))?
        } else {
            bucket.field.clone()
        };
        Ok(Some(TimeBucket {
            field,
            width_micros: bucket.width_micros,
            origin_micros: bucket.origin_micros,
        }))
    }

    #[allow(clippy::too_many_arguments)]
    fn scan<'g, F>(
        &self,
        plan: &TypedPlan,
        compiled: &Compiled,
        positive: &[TimeConjunct],
        prune: bool,
        sort: Option<&Sort>,
        guard: &mut ScanGuard<'g>,
        visit: &mut F,
    ) -> SearchResult<TypedScanDiagnostics>
    where
        F: FnMut(
            &mut ScanGuard<'g>,
            &SegmentReader,
            &ColumnAccess<'_>,
            &JsonAccess<'_>,
            Option<&GeoSortDistances>,
            u64,
        ) -> SearchResult<()>,
    {
        guard.poll()?;
        let mut diagnostics = TypedScanDiagnostics::default();
        let max_docs = self.limits.max_typed_scan_docs();
        for index in 0..self.snapshot.segment_count() {
            guard.poll()?;
            diagnostics.segments_considered = diagnostics
                .segments_considered
                .checked_add(1)
                .ok_or_else(|| counter_overflow("segments_considered"))?;
            if prune && self.segment_pruned(index, positive, plan) {
                diagnostics.segments_skipped_by_time = diagnostics
                    .segments_skipped_by_time
                    .checked_add(1)
                    .ok_or_else(|| counter_overflow("segments_skipped_by_time"))?;
                continue;
            }
            let guarded = self.snapshot.open_segment_reader(index)?;
            let reader = guarded.reader();
            let columns = ColumnAccess::open(reader)?;
            let json = JsonAccess::open(reader)?;
            let mut scratch = GeoScratchBudget::new(self.limits.max_total_candidate_bytes());
            let geo = build_geo_membership(
                &compiled.geo_leaves,
                reader.spatial(),
                reader,
                &columns,
                guard,
                &mut scratch,
                self.limits.max_segment_candidate_entries(),
            )?;
            let geo_sort = build_geo_sort_distances(sort, reader, &columns, guard, &mut scratch)?;
            let live = self.snapshot.effective_live_docs(index, reader)?;
            for (doc_id, is_live) in live.iter().enumerate() {
                if !*is_live {
                    continue;
                }
                if diagnostics.live_documents_examined >= max_docs {
                    return Err(SearchError::ResourceLimit {
                        limit: max_docs,
                        requested: diagnostics.live_documents_examined.saturating_add(1),
                    });
                }
                diagnostics.live_documents_examined += 1;
                guard.charge(1)?;
                let doc_id = u64::try_from(doc_id).unwrap_or(u64::MAX);
                if evaluate_query(guard, &columns, &json, &geo, &compiled.root, doc_id)? {
                    diagnostics.matching_documents = diagnostics
                        .matching_documents
                        .checked_add(1)
                        .ok_or_else(|| counter_overflow("matching_documents"))?;
                    visit(guard, reader, &columns, &json, geo_sort.as_ref(), doc_id)?;
                }
            }
        }
        Ok(diagnostics)
    }

    fn segment_pruned(&self, index: usize, positive: &[TimeConjunct], plan: &TypedPlan) -> bool {
        let Some(bounds) = self.snapshot.segments()[index].meta().time_bounds() else {
            return false;
        };
        for conjunct in positive {
            if let Some(field) = plan.field(&conjunct.field) {
                if bounds.field_id == field.id
                    && bounds.prunes_positive_range(conjunct.start, conjunct.end)
                {
                    return true;
                }
            }
        }
        false
    }
}

impl std::fmt::Debug for TypedSearcher<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TypedSearcher")
            .field("segments", &self.snapshot.segment_count())
            .field("generation", &self.snapshot.generation())
            .finish()
    }
}

/// A positive top-level `TimeRange` conjunct used only for pruning.
struct TimeConjunct {
    field: String,
    start: i64,
    end: i64,
}

fn collect_positive_time(query: &Query) -> Vec<TimeConjunct> {
    let mut conjuncts = Vec::new();
    collect_positive_time_into(query, &mut conjuncts);
    conjuncts
}

fn collect_positive_time_into(query: &Query, out: &mut Vec<TimeConjunct>) {
    match query {
        Query::TimeRange { field, start, end } => out.push(TimeConjunct {
            field: field.clone(),
            start: start.as_micros(),
            end: end.as_micros(),
        }),
        Query::And(queries) => {
            for query in queries {
                collect_positive_time_into(query, out);
            }
        }
        _ => {}
    }
}

/// A compiled typed query with JSON path segments resolved once per request.
enum CompiledQuery {
    MatchAll,
    Range {
        id: u32,
        lower: Bound<FieldValue>,
        upper: Bound<FieldValue>,
    },
    TimeRange {
        id: u32,
        start: i64,
        end: i64,
    },
    JsonExists {
        id: u32,
        path: Vec<JsonPathSegment>,
    },
    JsonEquals {
        id: u32,
        path: Vec<JsonPathSegment>,
        scalar: JsonScalar,
    },
    JsonRange {
        id: u32,
        path: Vec<JsonPathSegment>,
        lower: Bound<JsonScalar>,
        upper: Bound<JsonScalar>,
    },
    JsonArrayContains {
        id: u32,
        path: Vec<JsonPathSegment>,
        scalar: JsonScalar,
    },
    /// Universal presence predicates over one columnar field.
    Exists {
        id: u32,
    },
    Missing {
        id: u32,
    },
    IsNull {
        id: u32,
    },
    /// Any-member scalar membership over present, non-null values.
    InSet {
        id: u32,
        values: Vec<FieldValue>,
    },
    /// Present, non-null membership negation (absent/null never match).
    NotInSet {
        id: u32,
        values: Vec<FieldValue>,
    },
    IpExact {
        id: u32,
        addr: IpAddr,
    },
    IpRange {
        id: u32,
        start: IpAddr,
        end: IpAddr,
    },
    IpInCidr {
        id: u32,
        network: IpNetwork,
    },
    IpNotInCidr {
        id: u32,
        network: IpNetwork,
    },
    /// A spatial leaf; membership is precomputed once per segment.
    Geo {
        leaf: usize,
    },
    And(Vec<CompiledQuery>),
    Or(Vec<CompiledQuery>),
    Not(Box<CompiledQuery>),
}

/// The compiled query plus its distinct spatial leaves.
struct Compiled {
    root: CompiledQuery,
    geo_leaves: Vec<CompiledGeoLeaf>,
}

/// One distinct spatial leaf with its resolved field and predicate.
struct CompiledGeoLeaf {
    field_id: u32,
    predicate: CompiledGeoPredicate,
}

/// A compiled exact spatial predicate.
enum CompiledGeoPredicate {
    BoundingBox {
        west: f64,
        south: f64,
        east: f64,
        north: f64,
    },
    Radius {
        lon: f64,
        lat: f64,
        meters: f64,
    },
    Polygon {
        outer: Vec<(f64, f64)>,
        holes: Vec<Vec<(f64, f64)>>,
        min_lon: f64,
        min_lat: f64,
        max_lon: f64,
        max_lat: f64,
    },
}

impl CompiledGeoPredicate {
    fn envelope_may_match(&self, node: &SpatialNode) -> bool {
        match self {
            Self::BoundingBox {
                west,
                south,
                east,
                north,
            } => geo::bbox_intersects_envelope(
                (*west, *south, *east, *north),
                (node.min_lon, node.min_lat, node.max_lon, node.max_lat),
            ),
            // A radius query uses a full-world candidate envelope; the exact
            // haversine predicate always decides.
            Self::Radius { .. } => true,
            Self::Polygon {
                min_lon,
                min_lat,
                max_lon,
                max_lat,
                ..
            } => geo::polygon_intersects_envelope(
                (*min_lon, *min_lat, *max_lon, *max_lat),
                (node.min_lon, node.min_lat, node.max_lon, node.max_lat),
            ),
        }
    }

    fn matches_point(&self, lon: f64, lat: f64) -> bool {
        match self {
            Self::BoundingBox {
                west,
                south,
                east,
                north,
            } => geo::bbox_contains(lon, lat, *west, *south, *east, *north),
            Self::Radius {
                lon: center_lon,
                lat: center_lat,
                meters,
            } => geo::haversine_meters(lon, lat, *center_lon, *center_lat) <= *meters,
            Self::Polygon { outer, holes, .. } => geo::polygon_contains(lon, lat, outer, holes),
        }
    }
}

/// Logical per-segment scratch budget shared by every spatial allocation.
///
/// Bounds simultaneously live **vector capacities** (not process RSS) against
/// [`SearchLimits::max_total_candidate_bytes`]. Membership candidate sets, DFS
/// stacks and distance-sort tables all draw from one instance per segment; the
/// top-K heap budget is deliberately separate.
struct GeoScratchBudget {
    limit: u64,
    used: u64,
}

impl GeoScratchBudget {
    fn new(limit: u64) -> Self {
        Self { limit, used: 0 }
    }

    fn scratch_usize(&self, value: u64) -> SearchResult<usize> {
        usize::try_from(value).map_err(|_| SearchError::ResourceLimit {
            limit: self.limit,
            requested: value,
        })
    }

    fn reserve(&mut self, bytes: u64) -> SearchResult<()> {
        let projected = self
            .used
            .checked_add(bytes)
            .ok_or(SearchError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })?;
        if projected > self.limit {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: projected,
            });
        }
        self.used = projected;
        Ok(())
    }

    fn release(&mut self, bytes: u64) {
        self.used = self.used.saturating_sub(bytes);
    }

    fn bytes_for<T>(&self, count: usize) -> SearchResult<u64> {
        (count as u64)
            .checked_mul(std::mem::size_of::<T>() as u64)
            .ok_or(SearchError::ResourceLimit {
                limit: self.limit,
                requested: u64::MAX,
            })
    }

    /// Fallibly reserve `additional` elements and charge the actual capacity
    /// delta. Rejects allocator over-allocation beyond the budget.
    fn reserve_exact<T>(&mut self, vec: &mut Vec<T>, additional: usize) -> SearchResult<()> {
        if additional == 0 {
            return Ok(());
        }
        let requested = self.bytes_for::<T>(additional)?;
        self.reserve(requested)?;
        let before = vec.capacity();
        if vec.try_reserve_exact(additional).is_err() {
            return Err(SearchError::ResourceLimit {
                limit: self.limit,
                requested: self.used.saturating_add(requested),
            });
        }
        let actual = self.bytes_for::<T>(vec.capacity().saturating_sub(before))?;
        if actual > requested {
            self.reserve(actual - requested)?;
        } else {
            self.release(requested - actual);
        }
        Ok(())
    }

    /// Push with checked doubling, charging the new capacity before use.
    fn push_u64(&mut self, vec: &mut Vec<u64>, value: u64, entries_limit: u64) -> SearchResult<()> {
        let next_len = (vec.len() as u64)
            .checked_add(1)
            .ok_or(SearchError::ResourceLimit {
                limit: entries_limit,
                requested: u64::MAX,
            })?;
        if next_len > entries_limit {
            return Err(SearchError::ResourceLimit {
                limit: entries_limit,
                requested: next_len,
            });
        }
        if vec.len() == vec.capacity() {
            let additional = if vec.capacity() == 0 {
                4
            } else {
                vec.capacity()
            };
            self.reserve_exact(vec, additional)?;
        }
        vec.push(value);
        Ok(())
    }

    fn push_u32(&mut self, stack: &mut Vec<u32>, value: u32) -> SearchResult<()> {
        if stack.len() == stack.capacity() {
            let additional = if stack.capacity() == 0 {
                8
            } else {
                stack.capacity()
            };
            self.reserve_exact(stack, additional)?;
        }
        stack.push(value);
        Ok(())
    }
}

/// Precomputed per-segment membership for every distinct spatial leaf.
#[derive(Debug)]
struct GeoMembership {
    members: Vec<Vec<u64>>,
}

impl GeoMembership {
    fn contains(&self, leaf: usize, doc_id: u64) -> bool {
        self.members
            .get(leaf)
            .is_some_and(|members| members.binary_search(&doc_id).is_ok())
    }
}

/// A reusable per-segment JSON-path accessor.
///
/// For a segment with a JSON-path section it decodes only the requested
/// document's occurrences. For a legacy segment without the section it uses a
/// bounded, exact stored-source fallback, and fails typed when the field is not
/// stored. The validated directory is opened once per segment, never per doc.
struct JsonAccess<'a> {
    reader: &'a SegmentReader,
    paths: Option<crate::segment::JsonPathsReader<'a>>,
    schema: &'a crate::segment::CodecSchema,
    limits: crate::segment::SegmentLimits,
}

impl<'a> JsonAccess<'a> {
    fn open(reader: &'a SegmentReader) -> Result<Self, crate::segment::SegmentError> {
        Ok(Self {
            reader,
            paths: reader.open_json_paths()?,
            schema: reader.schema(),
            limits: *reader.limits(),
        })
    }

    fn occurrences(
        &self,
        field_id: u32,
        doc_id: u64,
        guard: &mut ScanGuard<'_>,
    ) -> SearchResult<Vec<JsonOccurrence>> {
        let mut out = Vec::new();
        match &self.paths {
            Some(paths) => {
                if let Some(mut cursor) = paths.doc_occurrences(field_id, doc_id)? {
                    while let Some(occurrence) = cursor.next_occurrence()? {
                        guard.charge(1)?;
                        out.push(occurrence);
                    }
                }
            }
            None => {
                let field = self
                    .schema
                    .field(field_id)
                    .ok_or(SearchError::CorruptIndex {
                        detail: "unknown json field id".to_owned(),
                    })?;
                if !field.is_stored() {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "json_path_legacy_unstored",
                    });
                }
                let record = self.reader.stored_doc(doc_id)?;
                let values = record.get(field_id);
                out = extract_field_paths(doc_id, &values, &self.limits)?;
                for _ in &out {
                    guard.charge(1)?;
                }
            }
        }
        Ok(out)
    }

    fn match_exists(
        &self,
        field_id: u32,
        pattern: &[JsonPathSegment],
        doc_id: u64,
        guard: &mut ScanGuard<'_>,
    ) -> SearchResult<bool> {
        let occurrences = self.occurrences(field_id, doc_id, guard)?;
        for occurrence in &occurrences {
            guard.charge(occurrence.path.len() as u64)?;
            if path_matches(pattern, &occurrence.path) {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn match_equals(
        &self,
        field_id: u32,
        pattern: &[JsonPathSegment],
        scalar: &JsonScalar,
        doc_id: u64,
        guard: &mut ScanGuard<'_>,
    ) -> SearchResult<bool> {
        let occurrences = self.occurrences(field_id, doc_id, guard)?;
        for occurrence in &occurrences {
            guard.charge(occurrence.path.len() as u64)?;
            if path_equals(pattern, &occurrence.path)
                && node_matches_scalar(&occurrence.node, scalar)
            {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn match_range(
        &self,
        field_id: u32,
        pattern: &[JsonPathSegment],
        lower: &Bound<JsonScalar>,
        upper: &Bound<JsonScalar>,
        doc_id: u64,
        guard: &mut ScanGuard<'_>,
    ) -> SearchResult<bool> {
        let occurrences = self.occurrences(field_id, doc_id, guard)?;
        for occurrence in &occurrences {
            guard.charge(occurrence.path.len() as u64)?;
            if occurrence_matches_range(occurrence, pattern, lower, upper) {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn match_array_contains(
        &self,
        field_id: u32,
        pattern: &[JsonPathSegment],
        scalar: &JsonScalar,
        doc_id: u64,
        guard: &mut ScanGuard<'_>,
    ) -> SearchResult<bool> {
        let occurrences = self.occurrences(field_id, doc_id, guard)?;
        let mut parent_is_array = false;
        for occurrence in &occurrences {
            guard.charge(occurrence.path.len() as u64)?;
            if path_equals(pattern, &occurrence.path) && node_is_array(&occurrence.node) {
                parent_is_array = true;
            }
        }
        if !parent_is_array {
            return Ok(false);
        }
        for occurrence in &occurrences {
            guard.charge(occurrence.path.len() as u64)?;
            if occurrence_is_immediate_index_child(pattern, &occurrence.path)
                && node_matches_scalar(&occurrence.node, scalar)
            {
                return Ok(true);
            }
        }
        Ok(false)
    }
}

fn evaluate_query(
    guard: &mut ScanGuard<'_>,
    columns: &ColumnAccess<'_>,
    json: &JsonAccess<'_>,
    geo: &GeoMembership,
    query: &CompiledQuery,
    doc_id: u64,
) -> SearchResult<bool> {
    match query {
        CompiledQuery::MatchAll => Ok(true),
        CompiledQuery::Range { id, lower, upper } => {
            let values = columns.value(*id, doc_id)?;
            Ok(values
                .as_ref()
                .is_some_and(|values| matches_range(values, lower, upper)))
        }
        CompiledQuery::TimeRange { id, start, end } => {
            let values = columns.value(*id, doc_id)?;
            Ok(values
                .as_ref()
                .is_some_and(|values| matches_time_range(values, *start, *end)))
        }
        CompiledQuery::And(queries) => {
            for query in queries {
                if !evaluate_query(guard, columns, json, geo, query, doc_id)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        CompiledQuery::Or(queries) => {
            for query in queries {
                if evaluate_query(guard, columns, json, geo, query, doc_id)? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
        CompiledQuery::Not(inner) => Ok(!evaluate_query(guard, columns, json, geo, inner, doc_id)?),
        CompiledQuery::JsonExists { id, path } => json.match_exists(*id, path, doc_id, guard),
        CompiledQuery::JsonEquals { id, path, scalar } => {
            json.match_equals(*id, path, scalar, doc_id, guard)
        }
        CompiledQuery::JsonRange {
            id,
            path,
            lower,
            upper,
        } => json.match_range(*id, path, lower, upper, doc_id, guard),
        CompiledQuery::JsonArrayContains { id, path, scalar } => {
            json.match_array_contains(*id, path, scalar, doc_id, guard)
        }
        CompiledQuery::Exists { id } => match columns.value(*id, doc_id)? {
            Some(values) => Ok(!values.is_absent()),
            None => Ok(false),
        },
        CompiledQuery::Missing { id } => match columns.value(*id, doc_id)? {
            Some(values) => Ok(values.is_absent()),
            None => Ok(true),
        },
        CompiledQuery::IsNull { id } => match columns.value(*id, doc_id)? {
            Some(values) => Ok(values.is_explicit_null()),
            None => Ok(false),
        },
        CompiledQuery::InSet { id, values } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(membership_any(&state, values)),
            None => Ok(false),
        },
        CompiledQuery::NotInSet { id, values } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(membership_none(&state, values)),
            None => Ok(false),
        },
        CompiledQuery::IpExact { id, addr } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(state
                .values()
                .any(|value| matches!(value, FieldValue::Ip(candidate) if candidate == addr))),
            None => Ok(false),
        },
        CompiledQuery::IpRange { id, start, end } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(state.values().any(|value| {
                matches!(value, FieldValue::Ip(candidate) if ip_in_inclusive_range(candidate, start, end))
            })),
            None => Ok(false),
        },
        CompiledQuery::IpInCidr { id, network } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(state.values().any(|value| ip_in_cidr(value, network))),
            None => Ok(false),
        },
        CompiledQuery::IpNotInCidr { id, network } => match columns.value(*id, doc_id)? {
            Some(state) => Ok(membership_none_ip(&state, network)),
            None => Ok(false),
        },
        CompiledQuery::Geo { leaf } => Ok(geo.contains(*leaf, doc_id)),
    }
}

fn membership_any(state: &FieldValues, values: &[FieldValue]) -> bool {
    if state.is_absent() || state.is_explicit_null() {
        return false;
    }
    state.values().any(|value| values.contains(value))
}

fn membership_none(state: &FieldValues, values: &[FieldValue]) -> bool {
    if state.is_absent() || state.is_explicit_null() {
        return false;
    }
    if state.is_empty_multi() {
        return true;
    }
    !membership_any(state, values)
}

fn ip_in_cidr(value: &FieldValue, network: &IpNetwork) -> bool {
    match value {
        FieldValue::Ip(addr) => network.contains(addr),
        FieldValue::Cidr(stored) => cidr_subset(network, stored),
        _ => false,
    }
}

fn membership_none_ip(state: &FieldValues, network: &IpNetwork) -> bool {
    if state.is_absent() || state.is_explicit_null() {
        return false;
    }
    if state.is_empty_multi() {
        return true;
    }
    !state.values().any(|value| ip_in_cidr(value, network))
}

/// Whether `stored` is entirely contained in `network` (same family).
fn cidr_subset(network: &IpNetwork, stored: &IpNetwork) -> bool {
    if network.addr().is_ipv4() != stored.addr().is_ipv4() {
        return false;
    }
    stored.prefix() >= network.prefix() && network.contains(&stored.addr())
}

fn ip_rank(addr: IpAddr) -> (u8, u128) {
    match addr {
        IpAddr::V4(v4) => (0, u128::from(u32::from(v4))),
        IpAddr::V6(v6) => (1, u128::from(v6)),
    }
}

/// Inclusive, family-aware address range membership.
fn ip_in_inclusive_range(candidate: &IpAddr, start: &IpAddr, end: &IpAddr) -> bool {
    if start.is_ipv4() != end.is_ipv4() || candidate.is_ipv4() != start.is_ipv4() {
        return false;
    }
    let candidate = ip_rank(*candidate);
    candidate >= ip_rank(*start) && candidate <= ip_rank(*end)
}

/// Build the exact per-segment membership for every distinct spatial leaf.
///
/// A feature-bearing segment uses the immutable KD tree; a legacy segment falls
/// back to a bounded exact column scan, or to stored source, and fails closed
/// when neither is available.
fn build_geo_membership(
    leaves: &[CompiledGeoLeaf],
    spatial: Option<&SpatialIndex>,
    reader: &SegmentReader,
    columns: &ColumnAccess<'_>,
    guard: &mut ScanGuard<'_>,
    budget: &mut GeoScratchBudget,
    entries_limit: u64,
) -> SearchResult<GeoMembership> {
    guard.poll()?;
    let mut members: Vec<Vec<u64>> = Vec::new();
    budget.reserve_exact(&mut members, leaves.len())?;
    for leaf in leaves {
        let mut docs: Vec<u64> = Vec::new();
        match spatial {
            Some(index) => {
                if let Some(field) = index.field(leaf.field_id) {
                    collect_tree_candidates(
                        field,
                        &leaf.predicate,
                        guard,
                        budget,
                        &mut docs,
                        entries_limit,
                    )?;
                }
            }
            None => collect_legacy_candidates(
                reader,
                columns,
                leaf,
                guard,
                budget,
                &mut docs,
                entries_limit,
            )?,
        }
        docs.sort_unstable();
        docs.dedup();
        members.push(docs);
    }
    Ok(GeoMembership { members })
}

fn collect_tree_candidates(
    field: &SpatialField,
    predicate: &CompiledGeoPredicate,
    guard: &mut ScanGuard<'_>,
    budget: &mut GeoScratchBudget,
    out: &mut Vec<u64>,
    entries_limit: u64,
) -> SearchResult<()> {
    guard.poll()?;
    let Some(root) = field.root else {
        return Ok(());
    };
    let mut stack: Vec<u32> = Vec::new();
    budget.push_u32(&mut stack, root)?;
    while let Some(index) = stack.pop() {
        guard.charge(1)?;
        let node = &field.nodes[index as usize];
        if !predicate.envelope_may_match(node) {
            continue;
        }
        if predicate.matches_point(node.lon, node.lat) {
            budget.push_u64(out, node.doc_id, entries_limit)?;
        }
        if node.left != ABSENT_INDEX {
            budget.push_u32(&mut stack, node.left)?;
        }
        if node.right != ABSENT_INDEX {
            budget.push_u32(&mut stack, node.right)?;
        }
    }
    // The DFS stack is a temporary: release its capacity accounting now that
    // traversal is complete. Memberships stay charged for the segment scan.
    let stack_bytes = budget.bytes_for::<u32>(stack.capacity())?;
    budget.release(stack_bytes);
    Ok(())
}

/// Build the per-segment minimum-distance table for GeoDistance sort fields.
fn build_geo_sort_distances(
    sort: Option<&Sort>,
    reader: &SegmentReader,
    columns: &ColumnAccess<'_>,
    guard: &mut ScanGuard<'_>,
    budget: &mut GeoScratchBudget,
) -> SearchResult<Option<GeoSortDistances>> {
    guard.poll()?;
    let Some(sort) = sort else {
        return Ok(None);
    };
    if !sort
        .fields
        .iter()
        .any(|field| field.distance_from.is_some())
    {
        return Ok(None);
    }
    let doc_count = budget.scratch_usize(reader.doc_count())?;
    let mut per_field: Vec<Option<Vec<Option<f64>>>> = Vec::new();
    budget.reserve_exact(&mut per_field, sort.fields.len())?;
    for field in &sort.fields {
        let Some(origin) = field.distance_from else {
            per_field.push(None);
            continue;
        };
        let field_id = reader
            .schema()
            .field_id(&field.field)
            .ok_or_else(|| unknown_field(&field.field))?;
        let mut distances: Vec<Option<f64>> = Vec::new();
        budget.reserve_exact(&mut distances, doc_count)?;
        distances.resize(doc_count, None);
        let tree = reader.spatial().and_then(|index| index.field(field_id));
        match tree {
            Some(tree) => {
                for node in &tree.nodes {
                    guard.charge(1)?;
                    let distance =
                        geo::haversine_meters(node.lon, node.lat, origin.lon(), origin.lat());
                    let slot = &mut distances[node.doc_id as usize];
                    *slot = Some(slot.map_or(distance, |current| current.min(distance)));
                }
            }
            None => {
                let definition =
                    reader
                        .schema()
                        .field(field_id)
                        .ok_or(SearchError::CorruptIndex {
                            detail: "unknown geo sort field id".to_owned(),
                        })?;
                if !definition.is_columnar() && !definition.is_stored() {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "geo_distance_legacy_unrecoverable",
                    });
                }
                for (doc_id, slot) in distances.iter_mut().enumerate() {
                    guard.charge(1)?;
                    let values = if definition.is_columnar() {
                        columns.value(field_id, doc_id as u64)?
                    } else {
                        Some(reader.stored_doc(doc_id as u64)?.get(field_id))
                    };
                    if let Some(values) = values {
                        for value in values.values() {
                            if let FieldValue::GeoPoint(point) = value {
                                let distance = geo::haversine_meters(
                                    point.lon(),
                                    point.lat(),
                                    origin.lon(),
                                    origin.lat(),
                                );
                                *slot =
                                    Some(slot.map_or(distance, |current| current.min(distance)));
                            }
                        }
                    }
                }
            }
        }
        per_field.push(Some(distances));
    }
    Ok(Some(GeoSortDistances { per_field }))
}

fn collect_legacy_candidates(
    reader: &SegmentReader,
    columns: &ColumnAccess<'_>,
    leaf: &CompiledGeoLeaf,
    guard: &mut ScanGuard<'_>,
    budget: &mut GeoScratchBudget,
    out: &mut Vec<u64>,
    entries_limit: u64,
) -> SearchResult<()> {
    guard.poll()?;
    let field = reader
        .schema()
        .field(leaf.field_id)
        .ok_or(SearchError::CorruptIndex {
            detail: "unknown geo field id".to_owned(),
        })?;
    let doc_count = reader.doc_count();
    if field.is_columnar() {
        for doc_id in 0..doc_count {
            guard.charge(1)?;
            if let Some(values) = columns.value(leaf.field_id, doc_id)? {
                if values.values().any(|value| match value {
                    FieldValue::GeoPoint(point) => {
                        leaf.predicate.matches_point(point.lon(), point.lat())
                    }
                    _ => false,
                }) {
                    budget.push_u64(out, doc_id, entries_limit)?;
                }
            }
        }
        return Ok(());
    }
    if !field.is_stored() {
        return Err(SearchError::UnsupportedOperator {
            operator: "geo_legacy_unrecoverable",
        });
    }
    for doc_id in 0..doc_count {
        guard.charge(1)?;
        let record = reader.stored_doc(doc_id)?;
        let values = record.get(leaf.field_id);
        if values.values().any(|value| match value {
            FieldValue::GeoPoint(point) => leaf.predicate.matches_point(point.lon(), point.lat()),
            _ => false,
        }) {
            budget.push_u64(out, doc_id, entries_limit)?;
        }
    }
    Ok(())
}

fn compile_query(query: &Query, plan: &TypedPlan) -> SearchResult<Compiled> {
    let mut geo_leaves = Vec::new();
    let root = compile_query_inner(query, plan, &mut geo_leaves)?;
    Ok(Compiled { root, geo_leaves })
}

fn compile_query_inner(
    query: &Query,
    plan: &TypedPlan,
    geo_leaves: &mut Vec<CompiledGeoLeaf>,
) -> SearchResult<CompiledQuery> {
    match query {
        Query::MatchAll => Ok(CompiledQuery::MatchAll),
        Query::Range {
            field,
            lower,
            upper,
        } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || !is_range_type(plan.field_type) {
                return Err(unsupported("range_type"));
            }
            for bound in [lower, upper] {
                if let Bound::Included(value) | Bound::Excluded(value) = bound {
                    if value.field_type() != plan.field_type {
                        return Err(unsupported("range_bound_type"));
                    }
                }
            }
            Ok(CompiledQuery::Range {
                id: plan.id,
                lower: lower.clone(),
                upper: upper.clone(),
            })
        }
        Query::TimeRange { field, start, end } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || plan.field_type != FieldType::Timestamp {
                return Err(unsupported("time_range_type"));
            }
            Ok(CompiledQuery::TimeRange {
                id: plan.id,
                start: start.as_micros(),
                end: end.as_micros(),
            })
        }
        Query::JsonPathExists { field, path } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if plan.field_type != FieldType::Json || !plan.indexed {
                return Err(unsupported("json_path_field"));
            }
            validate_json_path(path)?;
            Ok(CompiledQuery::JsonExists {
                id: plan.id,
                path: path.segments().to_vec(),
            })
        }
        Query::JsonPathEquals { field, path, value } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if plan.field_type != FieldType::Json || !plan.indexed {
                return Err(unsupported("json_path_field"));
            }
            if !path.is_concrete() {
                return Err(unsupported("jsonpath_equals_wildcard"));
            }
            validate_json_path(path)?;
            let scalar = JsonScalar::from_field_value(value)
                .ok_or_else(|| unsupported("jsonpath_equals_type"))?;
            Ok(CompiledQuery::JsonEquals {
                id: plan.id,
                path: path.segments().to_vec(),
                scalar,
            })
        }
        Query::JsonPathRange {
            field,
            path,
            lower,
            upper,
        } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if plan.field_type != FieldType::Json || !plan.indexed {
                return Err(unsupported("json_path_field"));
            }
            validate_json_path_segments(path.segments())?;
            let lower = convert_json_bound(lower)?;
            let upper = convert_json_bound(upper)?;
            if let (
                Bound::Included(l) | Bound::Excluded(l),
                Bound::Included(u) | Bound::Excluded(u),
            ) = (&lower, &upper)
            {
                if json_scalar_cmp(l, u) == Ordering::Greater {
                    return Err(SearchError::Query(QueryError::InvalidQuery(
                        InvalidQueryReason::UnsupportedOperator {
                            field: field.clone(),
                            operator: "jsonpath_range_reversed",
                        },
                    )));
                }
            }
            Ok(CompiledQuery::JsonRange {
                id: plan.id,
                path: path.segments().to_vec(),
                lower,
                upper,
            })
        }
        Query::JsonPathArrayContains { field, path, value } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if plan.field_type != FieldType::Json || !plan.indexed {
                return Err(unsupported("json_path_field"));
            }
            validate_json_path_segments(path.segments())?;
            let scalar = JsonScalar::from_field_value(value)
                .ok_or_else(|| unsupported("jsonpath_array_value_type"))?;
            Ok(CompiledQuery::JsonArrayContains {
                id: plan.id,
                path: path.segments().to_vec(),
                scalar,
            })
        }
        Query::Exists { field } | Query::Missing { field } | Query::IsNull { field } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar {
                return Err(unsupported("presence_field"));
            }
            Ok(match query {
                Query::Exists { .. } => CompiledQuery::Exists { id: plan.id },
                Query::Missing { .. } => CompiledQuery::Missing { id: plan.id },
                _ => CompiledQuery::IsNull { id: plan.id },
            })
        }
        Query::In { field, values } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || !is_membership_type(plan.field_type) {
                return Err(unsupported("in_field_type"));
            }
            Ok(CompiledQuery::InSet {
                id: plan.id,
                values: values.clone(),
            })
        }
        Query::NotIn { field, values } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || !is_membership_type(plan.field_type) {
                return Err(unsupported("not_in_field_type"));
            }
            Ok(CompiledQuery::NotInSet {
                id: plan.id,
                values: values.clone(),
            })
        }
        Query::IpExact { field, addr } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || plan.field_type != FieldType::IpAddress {
                return Err(unsupported("ip_exact_field"));
            }
            Ok(CompiledQuery::IpExact {
                id: plan.id,
                addr: *addr,
            })
        }
        Query::IpRange { field, start, end } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar || plan.field_type != FieldType::IpAddress {
                return Err(unsupported("ip_range_field"));
            }
            if start.is_ipv4() != end.is_ipv4() || ip_rank(*start) > ip_rank(*end) {
                return Err(SearchError::Query(QueryError::InvalidQuery(
                    InvalidQueryReason::InvalidIpRange {
                        field: field.clone(),
                    },
                )));
            }
            Ok(CompiledQuery::IpRange {
                id: plan.id,
                start: *start,
                end: *end,
            })
        }
        Query::IpInCidr { field, network } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar
                || !matches!(plan.field_type, FieldType::IpAddress | FieldType::IpNetwork)
            {
                return Err(unsupported("ip_cidr_field"));
            }
            Ok(CompiledQuery::IpInCidr {
                id: plan.id,
                network: *network,
            })
        }
        Query::IpNotInCidr { field, network } => {
            let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
            if !plan.columnar
                || !matches!(plan.field_type, FieldType::IpAddress | FieldType::IpNetwork)
            {
                return Err(unsupported("ip_cidr_field"));
            }
            Ok(CompiledQuery::IpNotInCidr {
                id: plan.id,
                network: *network,
            })
        }
        Query::GeoBoundingBox { field, bbox } => {
            let plan = require_geo_field(plan, field)?;
            Ok(push_geo_leaf(
                geo_leaves,
                plan,
                CompiledGeoPredicate::BoundingBox {
                    west: bbox.west,
                    south: bbox.south,
                    east: bbox.east,
                    north: bbox.north,
                },
            ))
        }
        Query::GeoRadius { field, radius } => {
            let plan = require_geo_field(plan, field)?;
            Ok(push_geo_leaf(
                geo_leaves,
                plan,
                CompiledGeoPredicate::Radius {
                    lon: radius.center.lon(),
                    lat: radius.center.lat(),
                    meters: radius.meters,
                },
            ))
        }
        Query::GeoPolygon { field, polygon } => {
            let plan = require_geo_field(plan, field)?;
            let (min_lon, min_lat, max_lon, max_lat) = polygon_envelope(polygon);
            let outer = ring_pairs(polygon.outer());
            let holes = polygon
                .holes()
                .iter()
                .map(|ring| ring_pairs(ring))
                .collect();
            Ok(push_geo_leaf(
                geo_leaves,
                plan,
                CompiledGeoPredicate::Polygon {
                    outer,
                    holes,
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                },
            ))
        }
        Query::And(queries) => {
            let mut compiled = Vec::with_capacity(queries.len());
            for query in queries {
                compiled.push(compile_query_inner(query, plan, geo_leaves)?);
            }
            Ok(CompiledQuery::And(compiled))
        }
        Query::Or(queries) => {
            let mut compiled = Vec::with_capacity(queries.len());
            for query in queries {
                compiled.push(compile_query_inner(query, plan, geo_leaves)?);
            }
            Ok(CompiledQuery::Or(compiled))
        }
        Query::Not(inner) => Ok(CompiledQuery::Not(Box::new(compile_query_inner(
            inner, plan, geo_leaves,
        )?))),
        other => Err(SearchError::UnsupportedOperator {
            operator: query_label(other),
        }),
    }
}

fn is_membership_type(field_type: FieldType) -> bool {
    is_typed_scalar(field_type) || field_type == FieldType::IpNetwork
}

fn require_geo_field(plan: &TypedPlan, field: &str) -> SearchResult<u32> {
    let plan = plan.field(field).ok_or_else(|| unknown_field(field))?;
    if plan.field_type != FieldType::GeoPoint || !plan.indexed {
        return Err(unsupported("geo_field"));
    }
    Ok(plan.id)
}

fn push_geo_leaf(
    leaves: &mut Vec<CompiledGeoLeaf>,
    field_id: u32,
    predicate: CompiledGeoPredicate,
) -> CompiledQuery {
    let leaf = leaves.len();
    leaves.push(CompiledGeoLeaf {
        field_id,
        predicate,
    });
    CompiledQuery::Geo { leaf }
}

fn ring_pairs(ring: &[crate::contract::value::GeoPoint]) -> Vec<(f64, f64)> {
    ring.iter()
        .map(|point| (point.lon(), point.lat()))
        .collect()
}

fn polygon_envelope(polygon: &GeoPolygon) -> (f64, f64, f64, f64) {
    let mut min_lon = f64::INFINITY;
    let mut min_lat = f64::INFINITY;
    let mut max_lon = f64::NEG_INFINITY;
    let mut max_lat = f64::NEG_INFINITY;
    for point in polygon.outer() {
        min_lon = min_lon.min(point.lon());
        min_lat = min_lat.min(point.lat());
        max_lon = max_lon.max(point.lon());
        max_lat = max_lat.max(point.lat());
    }
    (min_lon, min_lat, max_lon, max_lat)
}

fn validate_json_path(path: &JsonPathExpr) -> SearchResult<()> {
    validate_json_path_segments(path.segments())
}

fn validate_json_path_segments(segments: &[JsonPathSegment]) -> SearchResult<()> {
    if segments.len() > MAX_JSON_PATH_DEPTH {
        return Err(SearchError::ResourceLimit {
            limit: MAX_JSON_PATH_DEPTH as u64,
            requested: segments.len() as u64,
        });
    }
    for segment in segments {
        if let JsonPathSegment::Member(member) = segment {
            if member.len() > MAX_JSON_PATH_MEMBER_BYTES {
                return Err(SearchError::ResourceLimit {
                    limit: MAX_JSON_PATH_MEMBER_BYTES as u64,
                    requested: member.len() as u64,
                });
            }
        }
    }
    Ok(())
}

/// Convert a validated contract bound into a JSON scalar bound.
fn convert_json_bound(bound: &Bound<FieldValue>) -> SearchResult<Bound<JsonScalar>> {
    match bound {
        Bound::Unbounded => Ok(Bound::Unbounded),
        Bound::Included(value) => Ok(Bound::Included(
            JsonScalar::from_field_value(value)
                .ok_or_else(|| unsupported("jsonpath_range_type"))?,
        )),
        Bound::Excluded(value) => Ok(Bound::Excluded(
            JsonScalar::from_field_value(value)
                .ok_or_else(|| unsupported("jsonpath_range_type"))?,
        )),
    }
}

/// Same-type JSON scalar comparison used only for reversed-bound validation.
fn json_scalar_cmp(a: &JsonScalar, b: &JsonScalar) -> Ordering {
    match (a, b) {
        (JsonScalar::Bool(a), JsonScalar::Bool(b)) => a.cmp(b),
        (JsonScalar::I64(a), JsonScalar::I64(b)) => a.cmp(b),
        (JsonScalar::U64(a), JsonScalar::U64(b)) => a.cmp(b),
        (JsonScalar::F64(a), JsonScalar::F64(b)) => a.total_cmp(b),
        (JsonScalar::String(a), JsonScalar::String(b)) => a.cmp(b),
        _ => Ordering::Equal,
    }
}

fn query_label(query: &Query) -> &'static str {
    match query {
        Query::MatchAll => "match_all",
        Query::Term { .. } => "term",
        Query::Phrase { .. } => "phrase",
        Query::Prefix { .. } => "prefix",
        Query::Glob { .. } => "glob",
        Query::Regex { .. } => "regex",
        Query::Fuzzy { .. } => "fuzzy",
        Query::Range { .. } => "range",
        Query::TimeRange { .. } => "time_range",
        Query::Exists { .. } => "exists",
        Query::Missing { .. } => "missing",
        Query::IsNull { .. } => "is_null",
        Query::In { .. } => "in",
        Query::NotIn { .. } => "not_in",
        Query::IpExact { .. } => "ip_exact",
        Query::IpRange { .. } => "ip_range",
        Query::IpInCidr { .. } => "ip_in_cidr",
        Query::IpNotInCidr { .. } => "ip_not_in_cidr",
        Query::JsonPathEquals { .. } => "json_path_equals",
        Query::JsonPathExists { .. } => "json_path_exists",
        Query::JsonPathRange { .. } => "json_path_range",
        Query::JsonPathArrayContains { .. } => "json_path_array_contains",
        Query::GeoBoundingBox { .. } => "geo_bounding_box",
        Query::GeoRadius { .. } => "geo_radius",
        Query::GeoPolygon { .. } => "geo_polygon",
        Query::And(_) => "and",
        Query::Or(_) => "or",
        Query::Not(_) => "not",
    }
}

fn unknown_field(field: &str) -> SearchError {
    SearchError::Query(QueryError::InvalidQuery(InvalidQueryReason::UnknownField {
        field: field.to_owned(),
    }))
}

fn unsupported(operator: &'static str) -> SearchError {
    SearchError::UnsupportedOperator { operator }
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

fn counter_overflow(operation: &'static str) -> SearchError {
    SearchError::Query(QueryError::NumericOverflow { operation })
}

fn cancel_check(cancel: &dyn Cancellation) -> SearchResult<()> {
    if cancel.is_cancelled() {
        Err(SearchError::Cancelled)
    } else {
        Ok(())
    }
}

fn aggregate_limits(limits: SearchLimits, budgets: &Budgets) -> AggregateLimits {
    let max_groups = limits
        .max_aggregate_groups()
        .min(budgets.get(BudgetKind::Groups).unwrap_or(u64::MAX));
    let max_state_bytes = limits
        .max_aggregate_state_bytes()
        .min(budgets.get(BudgetKind::MemoryBytes).unwrap_or(u64::MAX));
    let max_distinct_per_group = limits
        .max_distinct_values_per_group()
        .min(budgets.get(BudgetKind::DistinctKeys).unwrap_or(u64::MAX));
    let max_expansion_per_doc = limits
        .max_group_expansion_per_document()
        .min(budgets.get(BudgetKind::GroupExpansions).unwrap_or(u64::MAX));
    AggregateLimits {
        max_groups,
        max_state_bytes,
        max_distinct_per_group,
        max_frequency_per_group: limits.max_frequency_values_per_group(),
        max_expansion_per_doc,
    }
}

#[allow(clippy::too_many_arguments)]
fn visit_aggregate(
    guard: &mut ScanGuard<'_>,
    engine: &mut AggregationEngine,
    plan: &TypedPlan,
    request: &AggregateRequest,
    bucket: Option<&TimeBucket>,
    columns: &ColumnAccess<'_>,
    doc_id: u64,
) -> SearchResult<()> {
    let mut charge: u64 = 0;
    let result = visit_aggregate_inner(
        guard,
        engine,
        plan,
        request,
        bucket,
        columns,
        doc_id,
        &mut charge,
    );
    if charge > 0 {
        engine.release_transient(charge);
    }
    result
}

/// Build per-document staging, pre-admitting every owned decoded value and clone
/// against the shared aggregation ledger. The caller releases `charge` on all
/// exits, including errors and cancellation.
#[allow(clippy::too_many_arguments)]
fn visit_aggregate_inner(
    guard: &mut ScanGuard<'_>,
    engine: &mut AggregationEngine,
    plan: &TypedPlan,
    request: &AggregateRequest,
    bucket: Option<&TimeBucket>,
    columns: &ColumnAccess<'_>,
    doc_id: u64,
    charge: &mut u64,
) -> SearchResult<()> {
    // Decode each distinct referenced field exactly once, admitting a
    // conservative decoded-value bound before the decoder allocates.
    let mut decode_ids: Vec<u32> = Vec::new();
    for field in &request.group_fields {
        let id = require_plan_field(plan, field)?.id;
        if !decode_ids.contains(&id) {
            decode_ids.push(id);
        }
    }
    if let Some(bucket) = bucket {
        let id = require_plan_field(plan, &bucket.field)?.id;
        if !decode_ids.contains(&id) {
            decode_ids.push(id);
        }
    }
    for metric in &request.metrics {
        if let Some(field) = metric_field(metric) {
            let id = require_plan_field(plan, field)?.id;
            if !decode_ids.contains(&id) {
                decode_ids.push(id);
            }
        }
    }
    if let Some(frequency) = &request.frequency_top_k {
        let id = require_plan_field(plan, &frequency.field)?.id;
        if !decode_ids.contains(&id) {
            decode_ids.push(id);
        }
    }

    let mut cache: BTreeMap<u32, Option<FieldValues>> = BTreeMap::new();
    engine.reserve_staging(64 + 64 * decode_ids.len() as u64, charge)?;
    for id in decode_ids {
        let bound = columns.decoded_value_bound(id, doc_id)?;
        engine.reserve_staging(bound, charge)?;
        let decoded = columns.value(id, doc_id)?;
        cache.insert(id, decoded);
    }

    let mut group_lists: Vec<Vec<GroupValue>> = Vec::with_capacity(request.group_fields.len());
    engine.reserve_staging(32 + 32 * request.group_fields.len() as u64, charge)?;
    for field in &request.group_fields {
        let field_plan = require_plan_field(plan, field)?;
        let values = cache.get(&field_plan.id).and_then(|value| value.as_ref());
        let list = match values {
            Some(values) => engine.expand_group_values(values, field_plan.field_type, charge)?,
            None => {
                engine.expand_group_values(&FieldValues::Absent, field_plan.field_type, charge)?
            }
        };
        group_lists.push(list);
    }

    let bucket_value = match bucket {
        None => None,
        Some(bucket) => {
            let field_plan = require_plan_field(plan, &bucket.field)?;
            match cache.get(&field_plan.id).and_then(|value| value.as_ref()) {
                Some(FieldValues::Single(FieldValue::Timestamp(timestamp))) => {
                    let start = bucket_start(
                        timestamp.as_micros(),
                        bucket.width_micros,
                        bucket.origin_micros,
                    )?;
                    Some(FieldValue::Timestamp(
                        crate::contract::value::Timestamp::from_micros(start),
                    ))
                }
                _ => None,
            }
        }
    };

    let mut metric_inputs: Vec<MetricInput<'_>> = Vec::with_capacity(request.metrics.len());
    engine.reserve_staging(32 + 32 * request.metrics.len() as u64, charge)?;
    for metric in &request.metrics {
        match metric {
            AggregateMetric::Count => metric_inputs.push(MetricInput::Count),
            _ => {
                let field = metric_field(metric).ok_or_else(|| unsupported("metric_field"))?;
                let field_plan = require_plan_field(plan, field)?;
                let slice = cache
                    .get(&field_plan.id)
                    .and_then(|value| value.as_ref())
                    .map(field_values_slice)
                    .unwrap_or(&[]);
                metric_inputs.push(MetricInput::Values(slice));
            }
        }
    }

    let frequency_values: &[FieldValue] = match &request.frequency_top_k {
        None => &[],
        Some(frequency) => {
            let field_plan = require_plan_field(plan, &frequency.field)?;
            cache
                .get(&field_plan.id)
                .and_then(|value| value.as_ref())
                .map(field_values_slice)
                .unwrap_or(&[])
        }
    };

    engine.add_document(
        guard,
        &group_lists,
        bucket_value.as_ref(),
        &metric_inputs,
        frequency_values,
    )
}

fn require_plan_field<'a>(plan: &'a TypedPlan, name: &str) -> SearchResult<&'a FieldPlan> {
    plan.field(name).ok_or_else(|| unknown_field(name))
}

fn metric_field(metric: &AggregateMetric) -> Option<&str> {
    match metric {
        AggregateMetric::Count => None,
        AggregateMetric::Sum { field }
        | AggregateMetric::Avg { field }
        | AggregateMetric::Min { field }
        | AggregateMetric::Max { field }
        | AggregateMetric::ExactDistinct { field } => Some(field.as_str()),
    }
}

fn field_values_slice(values: &FieldValues) -> &[FieldValue] {
    match values {
        FieldValues::Single(value) => std::slice::from_ref(value),
        FieldValues::Multi(list) => list.as_slice(),
        FieldValues::Absent | FieldValues::ExplicitNull | FieldValues::Empty => &[],
    }
}

/// Compute the sort value for one indexed JSON path on one document.
fn json_sort_value(
    json: &JsonAccess<'_>,
    schema: &crate::segment::CodecSchema,
    field: &SortField,
    doc_id: u64,
    guard: &mut ScanGuard<'_>,
) -> SearchResult<SortValue> {
    let Some(path) = field.json_path.as_ref() else {
        return Ok(SortValue::Missing);
    };
    let Some(field_id) = schema.field_id(&field.field) else {
        return Ok(SortValue::Missing);
    };
    let occurrences = json.occurrences(field_id, doc_id, guard)?;
    let pattern = path.segments();
    let mut values: Vec<FieldValue> = Vec::new();
    let mut saw_null = false;
    for occurrence in &occurrences {
        if !path_matches(pattern, &occurrence.path) {
            continue;
        }
        if node_is_null(&occurrence.node) {
            saw_null = true;
            continue;
        }
        if let Some(value) = node_to_field_value(&occurrence.node) {
            values.push(value);
        }
    }
    if values.is_empty() {
        return Ok(if saw_null {
            SortValue::Null
        } else {
            SortValue::Missing
        });
    }
    let mut best = values[0].clone();
    for candidate in &values[1..] {
        let ordering = canonical_scalar_cmp(candidate, &best);
        let replace = match field.multi.unwrap_or(MultiValueSelector::Min) {
            MultiValueSelector::Min => ordering == Ordering::Less,
            MultiValueSelector::Max => ordering == Ordering::Greater,
        };
        if replace {
            best = candidate.clone();
        }
    }
    Ok(SortValue::Value(best))
}

struct CandidateEntry<'a> {
    tuple: Vec<SortValue>,
    key: DocumentKey,
    sort: &'a Sort,
}

impl PartialEq for CandidateEntry<'_> {
    fn eq(&self, other: &Self) -> bool {
        self.key == other.key
    }
}

impl Eq for CandidateEntry<'_> {}

impl PartialOrd for CandidateEntry<'_> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for CandidateEntry<'_> {
    fn cmp(&self, other: &Self) -> Ordering {
        compare_candidates(&self.tuple, &self.key, &other.tuple, &other.key, self.sort)
    }
}

struct SearchAccumulator<'a> {
    sort: &'a Sort,
    top_k: usize,
    limit_entries: usize,
    heap: BinaryHeap<CandidateEntry<'a>>,
    heap_bytes: u64,
    max_heap_bytes: u64,
    total_hits: u64,
    after: Option<&'a TypedCursor>,
    snapshot_binding: u64,
    fingerprint: [u8; 32],
}

impl SearchAccumulator<'_> {
    fn accept(
        &mut self,
        guard: &mut ScanGuard<'_>,
        reader: &SegmentReader,
        columns: &ColumnAccess<'_>,
        json: &JsonAccess<'_>,
        geo: Option<&GeoSortDistances>,
        doc_id: u64,
    ) -> SearchResult<()> {
        self.total_hits = self
            .total_hits
            .checked_add(1)
            .ok_or_else(|| counter_overflow("total_hits"))?;
        let mut tuple = sort_tuple_for_doc(columns, reader.schema(), self.sort, geo, doc_id)?;
        for (index, field) in self.sort.fields.iter().enumerate() {
            if field.json_path.is_some() {
                tuple[index] = json_sort_value(json, reader.schema(), field, doc_id, guard)?;
            }
        }
        let key = reader.doc_key(doc_id)?;
        if let Some(after) = self.after {
            let ordering =
                compare_candidates(&tuple, &key, &after.last_sort, &after.last_key, self.sort);
            if ordering != Ordering::Greater {
                return Ok(());
            }
        }
        let bytes = candidate_bytes(&key, &tuple);
        if self.heap.len() < self.limit_entries {
            self.push(guard, tuple, key, bytes)
        } else {
            let Some(worst) = self.heap.peek() else {
                return self.push(guard, tuple, key, bytes);
            };
            let ordering = compare_candidates(&tuple, &key, &worst.tuple, &worst.key, self.sort);
            if ordering != Ordering::Less {
                return Ok(());
            }
            let popped = self.heap.pop().expect("heap is nonempty");
            self.heap_bytes = self
                .heap_bytes
                .saturating_sub(candidate_bytes(&popped.key, &popped.tuple));
            self.push(guard, tuple, key, bytes)
        }
    }

    fn push(
        &mut self,
        guard: &mut ScanGuard<'_>,
        tuple: Vec<SortValue>,
        key: DocumentKey,
        bytes: u64,
    ) -> SearchResult<()> {
        let projected = self
            .heap_bytes
            .checked_add(bytes)
            .ok_or(SearchError::ResourceLimit {
                limit: self.max_heap_bytes,
                requested: u64::MAX,
            })?;
        if projected > self.max_heap_bytes {
            return Err(SearchError::ResourceLimit {
                limit: self.max_heap_bytes,
                requested: projected,
            });
        }
        guard.charge(1)?;
        self.heap_bytes = projected;
        self.heap.push(CandidateEntry {
            tuple,
            key,
            sort: self.sort,
        });
        Ok(())
    }

    fn finish(self) -> SearchResult<(Vec<TypedHit>, Option<TypedCursor>)> {
        let entries = self.heap.into_sorted_vec();
        let available = entries.len();
        let keep = self.top_k.min(available);
        let mut hits = Vec::with_capacity(keep);
        let mut next_cursor = None;
        for (index, entry) in entries.into_iter().enumerate() {
            if index >= keep {
                break;
            }
            if index + 1 == keep && available > self.top_k {
                // Another retained candidate remains after this page.
                next_cursor = Some(TypedCursor::new(
                    self.snapshot_binding,
                    self.fingerprint,
                    entry.tuple.clone(),
                    entry.key.clone(),
                ));
            }
            hits.push(TypedHit {
                key: entry.key,
                sort_values: entry.tuple,
            });
        }
        Ok((hits, next_cursor))
    }
}

fn candidate_bytes(key: &DocumentKey, tuple: &[SortValue]) -> u64 {
    let mut bytes = key.as_str().len() as u64 + 24;
    for value in tuple {
        bytes += 24 + value.canonical_bytes().map_or(0, |b| b.len() as u64);
    }
    bytes
}

fn fingerprint(compiled: &Compiled, sort: &Sort) -> SearchResult<[u8; 32]> {
    let mut buffer = Vec::new();
    encode_query(&mut buffer, &compiled.root)?;
    push_len(&mut buffer, compiled.geo_leaves.len() as u64);
    for leaf in &compiled.geo_leaves {
        buffer.extend_from_slice(&leaf.field_id.to_le_bytes());
        encode_geo_predicate(&mut buffer, &leaf.predicate);
    }
    encode_sort(&mut buffer, sort);
    let mut hasher = Sha256::new();
    hasher.update(&buffer);
    Ok(hasher.finalize().into())
}

fn encode_geo_predicate(buffer: &mut Vec<u8>, predicate: &CompiledGeoPredicate) {
    match predicate {
        CompiledGeoPredicate::BoundingBox {
            west,
            south,
            east,
            north,
        } => {
            buffer.push(0);
            for value in [west, south, east, north] {
                buffer.extend_from_slice(&value.to_le_bytes());
            }
        }
        CompiledGeoPredicate::Radius { lon, lat, meters } => {
            buffer.push(1);
            for value in [lon, lat, meters] {
                buffer.extend_from_slice(&value.to_le_bytes());
            }
        }
        CompiledGeoPredicate::Polygon { outer, holes, .. } => {
            buffer.push(2);
            push_len(buffer, outer.len() as u64);
            for (lon, lat) in outer {
                buffer.extend_from_slice(&lon.to_le_bytes());
                buffer.extend_from_slice(&lat.to_le_bytes());
            }
            push_len(buffer, holes.len() as u64);
            for hole in holes {
                push_len(buffer, hole.len() as u64);
                for (lon, lat) in hole {
                    buffer.extend_from_slice(&lon.to_le_bytes());
                    buffer.extend_from_slice(&lat.to_le_bytes());
                }
            }
        }
    }
}

fn encode_query(buffer: &mut Vec<u8>, query: &CompiledQuery) -> SearchResult<()> {
    match query {
        CompiledQuery::MatchAll => buffer.push(1),
        CompiledQuery::Range { id, lower, upper } => {
            buffer.push(2);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_bound(buffer, lower)?;
            encode_bound(buffer, upper)?;
        }
        CompiledQuery::TimeRange { id, start, end } => {
            buffer.push(3);
            buffer.extend_from_slice(&id.to_le_bytes());
            buffer.extend_from_slice(&start.to_le_bytes());
            buffer.extend_from_slice(&end.to_le_bytes());
        }
        CompiledQuery::And(queries) => encode_list(buffer, 4, queries)?,
        CompiledQuery::Or(queries) => encode_list(buffer, 5, queries)?,
        CompiledQuery::Not(inner) => {
            buffer.push(6);
            encode_query(buffer, inner)?;
        }
        CompiledQuery::JsonExists { id, path } => {
            buffer.push(8);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_json_path(buffer, path);
        }
        CompiledQuery::JsonEquals { id, path, scalar } => {
            buffer.push(9);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_json_path(buffer, path);
            encode_json_scalar(buffer, scalar);
        }
        CompiledQuery::Geo { leaf } => {
            buffer.push(10);
            push_len(buffer, *leaf as u64);
        }
        CompiledQuery::Exists { id } => {
            buffer.push(11);
            buffer.extend_from_slice(&id.to_le_bytes());
        }
        CompiledQuery::Missing { id } => {
            buffer.push(12);
            buffer.extend_from_slice(&id.to_le_bytes());
        }
        CompiledQuery::IsNull { id } => {
            buffer.push(13);
            buffer.extend_from_slice(&id.to_le_bytes());
        }
        CompiledQuery::InSet { id, values } => {
            buffer.push(14);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_values(buffer, values)?;
        }
        CompiledQuery::NotInSet { id, values } => {
            buffer.push(15);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_values(buffer, values)?;
        }
        CompiledQuery::IpExact { id, addr } => {
            buffer.push(16);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_ip(buffer, addr);
        }
        CompiledQuery::IpRange { id, start, end } => {
            buffer.push(17);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_ip(buffer, start);
            encode_ip(buffer, end);
        }
        CompiledQuery::IpInCidr { id, network } => {
            buffer.push(18);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_ip_network(buffer, network);
        }
        CompiledQuery::IpNotInCidr { id, network } => {
            buffer.push(19);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_ip_network(buffer, network);
        }
        CompiledQuery::JsonRange {
            id,
            path,
            lower,
            upper,
        } => {
            buffer.push(20);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_json_path(buffer, path);
            encode_json_bound(buffer, lower);
            encode_json_bound(buffer, upper);
        }
        CompiledQuery::JsonArrayContains { id, path, scalar } => {
            buffer.push(21);
            buffer.extend_from_slice(&id.to_le_bytes());
            encode_json_path(buffer, path);
            encode_json_scalar(buffer, scalar);
        }
    }
    Ok(())
}

fn encode_json_bound(buffer: &mut Vec<u8>, bound: &Bound<JsonScalar>) {
    match bound {
        Bound::Unbounded => buffer.push(0),
        Bound::Included(scalar) => {
            buffer.push(1);
            encode_json_scalar(buffer, scalar);
        }
        Bound::Excluded(scalar) => {
            buffer.push(2);
            encode_json_scalar(buffer, scalar);
        }
    }
}

fn encode_values(buffer: &mut Vec<u8>, values: &[FieldValue]) -> SearchResult<()> {
    push_len(buffer, values.len() as u64);
    for value in values {
        encode_value(buffer, value)?;
    }
    Ok(())
}

fn encode_ip(buffer: &mut Vec<u8>, addr: &IpAddr) {
    match addr {
        IpAddr::V4(v4) => {
            buffer.push(0);
            buffer.extend_from_slice(&v4.octets());
        }
        IpAddr::V6(v6) => {
            buffer.push(1);
            buffer.extend_from_slice(&v6.octets());
        }
    }
}

fn encode_ip_network(buffer: &mut Vec<u8>, network: &IpNetwork) {
    encode_ip(buffer, &network.addr());
    buffer.push(network.prefix());
}

fn encode_json_path(buffer: &mut Vec<u8>, path: &[JsonPathSegment]) {
    push_len(buffer, path.len() as u64);
    for segment in path {
        match segment {
            JsonPathSegment::Member(member) => {
                buffer.push(0);
                encode_str(buffer, member);
            }
            JsonPathSegment::Index(index) => {
                buffer.push(1);
                push_len(buffer, *index as u64);
            }
            JsonPathSegment::Wildcard => buffer.push(2),
        }
    }
}

fn encode_json_scalar(buffer: &mut Vec<u8>, scalar: &JsonScalar) {
    match scalar {
        JsonScalar::Bool(flag) => {
            buffer.push(0);
            buffer.push(u8::from(*flag));
        }
        JsonScalar::I64(number) => {
            buffer.push(1);
            buffer.extend_from_slice(&number.to_le_bytes());
        }
        JsonScalar::U64(number) => {
            buffer.push(2);
            buffer.extend_from_slice(&number.to_le_bytes());
        }
        JsonScalar::F64(number) => {
            buffer.push(3);
            let normalized = if *number == 0.0 { 0.0 } else { *number };
            buffer.extend_from_slice(&normalized.to_le_bytes());
        }
        JsonScalar::String(bytes) => {
            buffer.push(4);
            push_len(buffer, bytes.len() as u64);
            buffer.extend_from_slice(bytes);
        }
    }
}

fn encode_list(buffer: &mut Vec<u8>, tag: u8, queries: &[CompiledQuery]) -> SearchResult<()> {
    buffer.push(tag);
    push_len(buffer, queries.len() as u64);
    for query in queries {
        encode_query(buffer, query)?;
    }
    Ok(())
}

fn encode_bound(buffer: &mut Vec<u8>, bound: &Bound<FieldValue>) -> SearchResult<()> {
    match bound {
        Bound::Unbounded => buffer.push(0),
        Bound::Included(value) => {
            buffer.push(1);
            encode_value(buffer, value)?;
        }
        Bound::Excluded(value) => {
            buffer.push(2);
            encode_value(buffer, value)?;
        }
    }
    Ok(())
}

fn encode_value(buffer: &mut Vec<u8>, value: &FieldValue) -> SearchResult<()> {
    buffer.push(scalar_tag(value.field_type()));
    let bytes = canonical_scalar_bytes(value).map_err(SearchError::from)?;
    push_len(buffer, bytes.len() as u64);
    buffer.extend_from_slice(&bytes);
    Ok(())
}

fn encode_sort(buffer: &mut Vec<u8>, sort: &Sort) {
    buffer.push(7);
    push_len(buffer, sort.fields.len() as u64);
    for field in &sort.fields {
        encode_str(buffer, &field.field);
        buffer.push(match field.direction {
            crate::contract::result::SortDirection::Asc => 0,
            crate::contract::result::SortDirection::Desc => 1,
        });
        buffer.push(match field.missing {
            crate::contract::result::MissingValuePosition::First => 0,
            crate::contract::result::MissingValuePosition::Last => 1,
        });
        buffer.push(match field.multi {
            None => 0,
            Some(crate::contract::result::MultiValueSelector::Min) => 1,
            Some(crate::contract::result::MultiValueSelector::Max) => 2,
        });
        match field.distance_from {
            None => buffer.push(0),
            Some(origin) => {
                buffer.push(1);
                buffer.extend_from_slice(&origin.lon().to_le_bytes());
                buffer.extend_from_slice(&origin.lat().to_le_bytes());
            }
        }
        match &field.json_path {
            None => buffer.push(0),
            Some(path) => {
                buffer.push(1);
                encode_json_path(buffer, path.segments());
            }
        }
    }
}

fn encode_str(buffer: &mut Vec<u8>, value: &str) {
    push_len(buffer, value.len() as u64);
    buffer.extend_from_slice(value.as_bytes());
}

fn push_len(buffer: &mut Vec<u8>, length: u64) {
    buffer.extend_from_slice(&length.to_le_bytes());
}

fn scalar_tag(field_type: FieldType) -> u8 {
    match field_type {
        FieldType::Text => 0,
        FieldType::Keyword => 1,
        FieldType::Bool => 2,
        FieldType::I64 => 3,
        FieldType::U64 => 4,
        FieldType::F64 => 5,
        FieldType::Timestamp => 6,
        FieldType::Json => 7,
        FieldType::GeoPoint => 8,
        FieldType::IpAddress => 9,
        FieldType::IpNetwork => 10,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::analysis::NeverCancel;
    use crate::contract::result::SortField;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::index::Index;
    use crate::search::MetricValue;
    use crate::search::SearchLimits;
    use crate::storage::MemoryDirectory;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
            ],
            Some("ts".into()),
        )
        .unwrap()
    }

    #[test]
    fn empty_snapshot_returns_no_hits() {
        let schema = schema();
        let registry = crate::analysis::AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::new(MemoryDirectory::new()), schema.clone(), registry).unwrap();
        let snapshot = index.snapshot();
        let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
        let request = TypedSearchRequest {
            query: Query::MatchAll,
            sort: Sort::default(),
            top_k: TopK::new(5).unwrap(),
            after: None,
            primary_time_field: Some("ts".into()),
        };
        let response = searcher
            .search(&request, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert!(response.hits.is_empty());
        assert_eq!(response.total_hits, 0);
        assert!(response.next_cursor.is_none());
        assert_eq!(response.diagnostics.segments_considered, 0);
    }

    #[test]
    fn global_aggregate_on_empty_index_is_one_group() {
        let schema = schema();
        let registry = crate::analysis::AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::new(MemoryDirectory::new()), schema.clone(), registry).unwrap();
        let snapshot = index.snapshot();
        let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
        let request = AggregateRequest {
            query: Query::MatchAll,
            group_fields: Vec::new(),
            time_bucket: None,
            metrics: vec![AggregateMetric::Count],
            frequency_top_k: None,
            primary_time_field: Some("ts".into()),
        };
        let response = searcher
            .aggregate(&request, &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(response.groups.len(), 1);
        assert_eq!(response.groups[0].metrics, vec![MetricValue::Count(0)]);
    }

    #[test]
    fn unsupported_query_fails_closed() {
        let schema = schema();
        let registry = crate::analysis::AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::new(MemoryDirectory::new()), schema.clone(), registry).unwrap();
        let snapshot = index.snapshot();
        let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
        let request = TypedSearchRequest {
            query: Query::Term {
                field: "n".into(),
                value: FieldValue::I64(1),
            },
            sort: Sort::default(),
            top_k: TopK::new(5).unwrap(),
            after: None,
            primary_time_field: None,
        };
        assert!(matches!(
            searcher.search(&request, &Budgets::new(), &NeverCancel),
            Err(SearchError::UnsupportedOperator { .. })
        ));
    }

    #[test]
    fn sort_validation_rejects_unsupported_types() {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "point",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )],
            None,
        )
        .unwrap();
        let registry = crate::analysis::AnalyzerRegistry::builtin();
        let index =
            Index::create(Arc::new(MemoryDirectory::new()), schema.clone(), registry).unwrap();
        let snapshot = index.snapshot();
        let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
        let request = TypedSearchRequest {
            query: Query::MatchAll,
            sort: Sort::new(vec![SortField::new(
                "point",
                crate::contract::result::SortDirection::Asc,
            )]),
            top_k: TopK::new(5).unwrap(),
            after: None,
            primary_time_field: None,
        };
        assert!(matches!(
            searcher.search(&request, &Budgets::new(), &NeverCancel),
            Err(SearchError::UnsupportedOperator { .. })
        ));
    }
}

#[cfg(test)]
mod legacy_json_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, NeverCancel};
    use crate::contract::value::{JsonNumber, JsonValue};
    use crate::segment::{
        ContainerBuilder, ContainerKind, SectionKind, SegmentBuilder, SegmentDocument,
        SegmentLimits, parse_container,
    };

    fn legacy_segment(schema: &Schema, docs: Vec<SegmentDocument>) -> Vec<u8> {
        let mut builder = SegmentBuilder::new(schema.clone(), AnalyzerRegistry::builtin()).unwrap();
        for doc in docs {
            builder.add_document(doc).unwrap();
        }
        let built = builder.build().unwrap();
        let limits = SegmentLimits::default();
        let view = parse_container(&built.bytes, &limits).unwrap();
        let mut container = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
        for (id, version) in view.required_features() {
            if *id == crate::segment::format::FEATURE_JSON_PATHS {
                continue;
            }
            container.require_feature(*id, *version);
        }
        for entry in view.sections() {
            if entry.kind == SectionKind::JsonPaths {
                continue;
            }
            container.section(
                entry.kind,
                entry.flags,
                entry.aux,
                view.body(entry.kind).unwrap().to_vec(),
            );
        }
        container.build().unwrap()
    }

    fn json_field(value: i64) -> FieldValues {
        FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![(
            "v".into(),
            JsonValue::Number(JsonNumber::I64(value)),
        )])))
    }

    fn legacy_schema() -> Schema {
        Schema::new(
            vec![
                crate::contract::schema::FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    crate::contract::schema::FieldOptions::indexed_stored(),
                ),
                crate::contract::schema::FieldDefinition::new(
                    "indexed_only",
                    FieldType::Json,
                    Cardinality::Single,
                    crate::contract::schema::FieldOptions::new(true, false, false),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn legacy_source_fallback_and_unstored_error() {
        let schema = legacy_schema();
        let mut doc = SegmentDocument::new(DocumentKey::new("d").unwrap());
        doc.insert("body", json_field(1)).unwrap();
        doc.insert("indexed_only", json_field(2)).unwrap();
        let bytes = legacy_segment(&schema, vec![doc]);
        let reader = SegmentReader::open(bytes, SegmentLimits::default()).unwrap();
        let access = JsonAccess::open(&reader).unwrap();
        assert!(access.paths.is_none());

        let mut guard = ScanGuard::new(64, &NeverCancel);
        let path = JsonPathExpr::parse("$.v").unwrap();
        let body_id = reader.schema().field_id("body").unwrap();
        assert!(
            access
                .match_exists(body_id, path.segments(), 0, &mut guard)
                .unwrap()
        );
        // A source fallback that does not match is a clean negative.
        let missing = JsonPathExpr::parse("$.nope").unwrap();
        assert!(
            !access
                .match_exists(body_id, missing.segments(), 0, &mut guard)
                .unwrap()
        );

        // An indexed-but-not-stored legacy JSON field cannot be recovered.
        let indexed_only_id = reader.schema().field_id("indexed_only").unwrap();
        let error = access
            .match_exists(indexed_only_id, path.segments(), 0, &mut guard)
            .unwrap_err();
        assert!(matches!(error, SearchError::UnsupportedOperator { .. }));
    }

    #[test]
    fn b1_legacy_source_fallback_wide_field() {
        let schema = legacy_schema();
        let entries: Vec<(String, JsonValue)> = (0..2_000i64)
            .map(|index| {
                (
                    format!("w{index:05}"),
                    JsonValue::Number(JsonNumber::I64(index)),
                )
            })
            .collect();
        let mut doc = SegmentDocument::new(DocumentKey::new("d").unwrap());
        doc.insert(
            "body",
            FieldValues::Single(FieldValue::Json(JsonValue::Object(entries))),
        )
        .unwrap();
        let bytes = legacy_segment(&schema, vec![doc]);
        let reader = SegmentReader::open(bytes, SegmentLimits::default()).unwrap();
        let access = JsonAccess::open(&reader).unwrap();
        assert!(access.paths.is_none());

        let mut guard = ScanGuard::new(100_000, &NeverCancel);
        let path = JsonPathExpr::parse("$.w01999").unwrap();
        let body_id = reader.schema().field_id("body").unwrap();
        assert!(
            access
                .match_exists(body_id, path.segments(), 0, &mut guard)
                .unwrap()
        );
        let missing = JsonPathExpr::parse("$.missing").unwrap();
        assert!(
            !access
                .match_exists(body_id, missing.segments(), 0, &mut guard)
                .unwrap()
        );
    }
}

#[cfg(test)]
mod legacy_geo_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, CancellationFlag, NeverCancel};
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue, GeoPoint};
    use crate::segment::{
        ContainerBuilder, ContainerKind, SectionKind, SegmentBuilder, SegmentDocument,
        SegmentLimits, SegmentReader, parse_container,
    };

    fn legacy_geo_segment(schema: &Schema, docs: Vec<SegmentDocument>) -> Vec<u8> {
        let mut builder = SegmentBuilder::new(schema.clone(), AnalyzerRegistry::builtin()).unwrap();
        for doc in docs {
            builder.add_document(doc).unwrap();
        }
        let built = builder.build().unwrap();
        let limits = SegmentLimits::default();
        let view = parse_container(&built.bytes, &limits).unwrap();
        let mut container = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
        for (id, version) in view.required_features() {
            if *id == crate::segment::format::FEATURE_SPATIAL_POINTS {
                continue;
            }
            container.require_feature(*id, *version);
        }
        for entry in view.sections() {
            if entry.kind == SectionKind::SpatialPoints {
                continue;
            }
            container.section(
                entry.kind,
                entry.flags,
                entry.aux,
                view.body(entry.kind).unwrap().to_vec(),
            );
        }
        container.build().unwrap()
    }

    fn geo_document() -> SegmentDocument {
        let mut doc = SegmentDocument::new(DocumentKey::new("d").unwrap());
        doc.insert(
            "loc",
            FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(1.0, 1.0).unwrap())),
        )
        .unwrap();
        doc.insert(
            "indexed_only",
            FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(1.0, 1.0).unwrap())),
        )
        .unwrap();
        doc
    }

    fn legacy_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "indexed_only",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn in_box() -> CompiledGeoPredicate {
        CompiledGeoPredicate::BoundingBox {
            west: 0.0,
            south: 0.0,
            east: 2.0,
            north: 2.0,
        }
    }

    #[test]
    fn legacy_column_fallback_and_unrecoverable() {
        let schema = legacy_schema();
        let bytes = legacy_geo_segment(&schema, vec![geo_document()]);
        let reader = SegmentReader::open(bytes, SegmentLimits::default()).unwrap();
        assert!(reader.spatial().is_none());
        let columns = ColumnAccess::open(&reader).unwrap();
        let loc_id = reader.schema().field_id("loc").unwrap();
        let only_id = reader.schema().field_id("indexed_only").unwrap();

        // A columnar legacy field is recovered by an exact bounded scan.
        let leaves = vec![CompiledGeoLeaf {
            field_id: loc_id,
            predicate: in_box(),
        }];
        let mut guard = ScanGuard::new(1_000, &NeverCancel);
        let mut budget = GeoScratchBudget::new(1 << 20);
        let membership = build_geo_membership(
            &leaves,
            reader.spatial(),
            &reader,
            &columns,
            &mut guard,
            &mut budget,
            1_000,
        )
        .unwrap();
        assert!(membership.contains(0, 0));

        // An indexed-not-stored/non-columnar legacy field fails closed.
        let leaves = vec![CompiledGeoLeaf {
            field_id: only_id,
            predicate: in_box(),
        }];
        let mut guard = ScanGuard::new(1_000, &NeverCancel);
        let mut budget = GeoScratchBudget::new(1 << 20);
        let error = build_geo_membership(
            &leaves,
            reader.spatial(),
            &reader,
            &columns,
            &mut guard,
            &mut budget,
            1_000,
        )
        .unwrap_err();
        assert!(matches!(
            error,
            SearchError::UnsupportedOperator {
                operator: "geo_legacy_unrecoverable"
            }
        ));
    }

    #[test]
    fn m15_legacy_cancellation_is_observed() {
        let schema = legacy_schema();
        let bytes = legacy_geo_segment(&schema, vec![geo_document()]);
        let reader = SegmentReader::open(bytes, SegmentLimits::default()).unwrap();
        let columns = ColumnAccess::open(&reader).unwrap();
        let loc_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![CompiledGeoLeaf {
            field_id: loc_id,
            predicate: in_box(),
        }];
        let canceled = CancellationFlag::new();
        canceled.cancel();
        let mut guard = ScanGuard::new(1_000, &canceled);
        let mut budget = GeoScratchBudget::new(1 << 20);
        let error = build_geo_membership(
            &leaves,
            reader.spatial(),
            &reader,
            &columns,
            &mut guard,
            &mut budget,
            1_000,
        )
        .unwrap_err();
        assert!(matches!(error, SearchError::Cancelled));
    }
}

#[cfg(test)]
mod geo_scratch_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, CancellationFlag, NeverCancel};
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::result::{Sort, SortDirection, SortField};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue, GeoPoint};
    use crate::segment::{SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader};
    use std::mem::size_of;

    fn schema() -> Schema {
        Schema::new(
            vec![FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )],
            None,
        )
        .unwrap()
    }

    fn reader_with(docs: &[Vec<(f64, f64)>], live: &[bool]) -> SegmentReader {
        let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
        for (index, points) in docs.iter().enumerate() {
            let mut doc = SegmentDocument::new(DocumentKey::new(format!("d{index}")).unwrap());
            if !points.is_empty() {
                doc.insert(
                    "loc",
                    FieldValues::Multi(
                        points
                            .iter()
                            .map(|(lon, lat)| {
                                FieldValue::GeoPoint(GeoPoint::new(*lon, *lat).unwrap())
                            })
                            .collect(),
                    ),
                )
                .unwrap();
            }
            if !live.get(index).copied().unwrap_or(true) {
                doc = doc.with_live(false);
            }
            builder.add_document(doc).unwrap();
        }
        SegmentReader::open(builder.build().unwrap().bytes, SegmentLimits::default()).unwrap()
    }

    fn box_leaf(field_id: u32) -> CompiledGeoLeaf {
        CompiledGeoLeaf {
            field_id,
            predicate: CompiledGeoPredicate::BoundingBox {
                west: -1.0,
                south: -1.0,
                east: 1.0,
                north: 1.0,
            },
        }
    }

    fn far_leaf(field_id: u32) -> CompiledGeoLeaf {
        CompiledGeoLeaf {
            field_id,
            predicate: CompiledGeoPredicate::BoundingBox {
                west: 100.0,
                south: 100.0,
                east: 110.0,
                north: 110.0,
            },
        }
    }

    fn distance_sort_one() -> Sort {
        Sort::new(vec![SortField::geo_distance(
            "loc",
            GeoPoint::new(0.0, 0.0).unwrap(),
            SortDirection::Asc,
        )])
    }

    fn distance_sort_two() -> Sort {
        Sort::new(vec![
            SortField::geo_distance("loc", GeoPoint::new(0.0, 0.0).unwrap(), SortDirection::Asc),
            SortField::geo_distance("loc", GeoPoint::new(1.0, 1.0).unwrap(), SortDirection::Desc),
        ])
    }

    const OPTION_VEC: u64 = size_of::<Option<Vec<Option<f64>>>>() as u64;
    const OPTION_F64: u64 = size_of::<Option<f64>>() as u64;
    const INNER_VEC: u64 = size_of::<Vec<u64>>() as u64;
    const U64: u64 = size_of::<u64>() as u64;

    fn membership(
        reader: &SegmentReader,
        leaves: &[CompiledGeoLeaf],
        budget: u64,
        entries: u64,
    ) -> SearchResult<GeoMembership> {
        let columns = ColumnAccess::open(reader).unwrap();
        let mut guard = ScanGuard::new(1_000_000, &NeverCancel);
        let mut scratch = GeoScratchBudget::new(budget);
        build_geo_membership(
            leaves,
            reader.spatial(),
            reader,
            &columns,
            &mut guard,
            &mut scratch,
            entries,
        )
    }

    #[test]
    fn m01_m02_m03_candidate_entry_limit() {
        let reader = reader_with(
            &[vec![(0.0, 0.0)], vec![(0.5, 0.5)], vec![(0.9, 0.9)]],
            &[true; 3],
        );
        let field_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![box_leaf(field_id)];
        let ok = membership(&reader, &leaves, 1 << 20, 3).unwrap();
        assert_eq!(ok.members.len(), 1);
        assert_eq!(ok.members[0], vec![0, 1, 2]);
        // M02: one over the pre-dedup occurrence count fails.
        assert!(matches!(
            membership(&reader, &leaves, 1 << 20, 2),
            Err(SearchError::ResourceLimit { .. })
        ));

        // M03: duplicate occurrences consume the pre-dedup budget.
        let reader = reader_with(&[vec![(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]], &[true]);
        let field_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![box_leaf(field_id)];
        assert!(matches!(
            membership(&reader, &leaves, 1 << 20, 2),
            Err(SearchError::ResourceLimit { .. })
        ));
        let ok = membership(&reader, &leaves, 1 << 20, 3).unwrap();
        assert_eq!(ok.members[0], vec![0]);
    }

    #[test]
    fn m04_two_leaves_combined_scratch() {
        let reader = reader_with(&[vec![(0.0, 0.0)], vec![(0.5, 0.5)]], &[true; 2]);
        let field_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![box_leaf(field_id), box_leaf(field_id)];
        // outer 2 * INNER_VEC; each leaf inner cap 4; plus one live DFS stack.
        let combined = 2 * INNER_VEC + 2 * 4 * U64 + 8 * 4;
        let ok = membership(&reader, &leaves, combined, 100).unwrap();
        assert_eq!(ok.members.len(), 2);
        assert!(matches!(
            membership(&reader, &leaves, combined - 1, 100),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn m05_stack_exceeds_tiny_budget() {
        let reader = reader_with(&[vec![(0.0, 0.0)]], &[true]);
        let field_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![far_leaf(field_id)];
        // outer membership container 24 bytes; a DFS stack of 8 * u32 = 32.
        let outer = INNER_VEC;
        assert!(membership(&reader, &leaves, outer + 32, 100).is_ok());
        assert!(matches!(
            membership(&reader, &leaves, outer + 31, 100),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    fn distances(
        reader: &SegmentReader,
        sort: &Sort,
        budget: u64,
    ) -> SearchResult<Option<GeoSortDistances>> {
        let columns = ColumnAccess::open(reader).unwrap();
        let mut guard = ScanGuard::new(1_000_000, &NeverCancel);
        let mut scratch = GeoScratchBudget::new(budget);
        build_geo_sort_distances(Some(sort), reader, &columns, &mut guard, &mut scratch)
    }

    #[test]
    fn m06_m07_m08_m09_distance_sort_exact_budget() {
        let reader = reader_with(
            &[
                vec![(0.0, 0.0)],
                vec![(0.5, 0.5)],
                vec![(0.9, 0.9)],
                vec![(0.2, 0.2)],
            ],
            &[true; 4],
        );
        let sort = distance_sort_one();
        let expected = OPTION_VEC + 4 * OPTION_F64;
        assert!(distances(&reader, &sort, expected).unwrap().is_some());
        assert!(matches!(
            distances(&reader, &sort, expected - 1),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn m10_two_sort_fields_combined_scratch() {
        let reader = reader_with(
            &[
                vec![(0.0, 0.0)],
                vec![(0.5, 0.5)],
                vec![(0.9, 0.9)],
                vec![(0.2, 0.2)],
            ],
            &[true; 4],
        );
        let sort = distance_sort_two();
        let combined = 2 * OPTION_VEC + 2 * 4 * OPTION_F64;
        assert!(distances(&reader, &sort, combined).unwrap().is_some());
        // Fits the outer container and exactly one table, not both.
        let one = 2 * OPTION_VEC + 4 * OPTION_F64;
        assert!(matches!(
            distances(&reader, &sort, one),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn m11_membership_plus_sort_combined_scratch() {
        let reader = reader_with(&[vec![(0.0, 0.0)]], &[true]);
        let field_id = reader.schema().field_id("loc").unwrap();
        let leaves = vec![box_leaf(field_id)];
        let membership_bytes = INNER_VEC + 4 * U64;
        let sort_bytes = OPTION_VEC + OPTION_F64;
        let combined = membership_bytes + sort_bytes;
        let columns = ColumnAccess::open(&reader).unwrap();
        let sort = distance_sort_one();

        let mut guard = ScanGuard::new(1_000_000, &NeverCancel);
        let mut scratch = GeoScratchBudget::new(combined);
        let geo = build_geo_membership(
            &leaves,
            reader.spatial(),
            &reader,
            &columns,
            &mut guard,
            &mut scratch,
            100,
        )
        .unwrap();
        assert!(geo.contains(0, 0));
        assert!(
            build_geo_sort_distances(Some(&sort), &reader, &columns, &mut guard, &mut scratch)
                .unwrap()
                .is_some()
        );

        // One byte short: membership still fits, the sort table does not.
        let mut guard = ScanGuard::new(1_000_000, &NeverCancel);
        let mut scratch = GeoScratchBudget::new(combined - 1);
        let geo = build_geo_membership(
            &leaves,
            reader.spatial(),
            &reader,
            &columns,
            &mut guard,
            &mut scratch,
            100,
        )
        .unwrap();
        assert!(geo.contains(0, 0));
        assert!(matches!(
            build_geo_sort_distances(Some(&sort), &reader, &columns, &mut guard, &mut scratch),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn m12_physical_doc_count_bounds_table() {
        let reader = reader_with(
            &[
                vec![(0.0, 0.0)],
                vec![(1.0, 1.0)],
                vec![(2.0, 2.0)],
                vec![(3.0, 3.0)],
            ],
            &[true, false, true, false],
        );
        assert_eq!(reader.doc_count(), 4);
        let sort = distance_sort_one();
        let result = distances(&reader, &sort, 1 << 20).unwrap().unwrap();
        let table = result.per_field[0].as_ref().unwrap();
        assert_eq!(table.len(), 4);
        assert_eq!(table.capacity(), 4);
        // The last physical doc (dead) still has a reserved slot.
        assert!(table[3].is_some());
    }

    #[test]
    fn m13_overflow_and_allocator_refusal_are_typed() {
        let mut budget = GeoScratchBudget::new(u64::MAX / 2);
        assert!(matches!(
            budget.reserve(u64::MAX),
            Err(SearchError::ResourceLimit { .. })
        ));
        let mut budget = GeoScratchBudget::new(u64::MAX);
        budget.reserve(u64::MAX).unwrap();
        assert!(matches!(
            budget.reserve(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        // Checked multiplication overflow is typed, not a panic.
        let budget = GeoScratchBudget::new(0);
        assert!(matches!(
            budget.bytes_for::<u64>(usize::MAX),
            Err(SearchError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn m14_m16_cancellation_on_spatial_paths() {
        let reader = reader_with(&[vec![(0.0, 0.0)], vec![(0.5, 0.5)]], &[true; 2]);
        let field_id = reader.schema().field_id("loc").unwrap();
        let columns = ColumnAccess::open(&reader).unwrap();
        let canceled = CancellationFlag::new();
        canceled.cancel();

        let mut guard = ScanGuard::new(1_000_000, &canceled);
        let mut scratch = GeoScratchBudget::new(1 << 20);
        let leaves = vec![box_leaf(field_id)];
        assert!(matches!(
            build_geo_membership(
                &leaves,
                reader.spatial(),
                &reader,
                &columns,
                &mut guard,
                &mut scratch,
                100
            ),
            Err(SearchError::Cancelled)
        ));

        let mut guard = ScanGuard::new(1_000_000, &canceled);
        let mut scratch = GeoScratchBudget::new(1 << 20);
        assert!(matches!(
            build_geo_sort_distances(
                Some(&distance_sort_one()),
                &reader,
                &columns,
                &mut guard,
                &mut scratch
            ),
            Err(SearchError::Cancelled)
        ));
    }
}
