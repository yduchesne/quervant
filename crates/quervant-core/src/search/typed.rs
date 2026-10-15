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

use sha2::{Digest, Sha256};

use crate::analysis::Cancellation;
use crate::contract::budget::{BudgetKind, Budgets};
use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::query::{Bound, JsonPathExpr, JsonPathSegment, Query};
use crate::contract::result::{Sort, TopK};
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue};
use crate::index::ReaderSnapshot;
use crate::segment::{
    JsonOccurrence, JsonScalar, MAX_JSON_PATH_DEPTH, MAX_JSON_PATH_MEMBER_BYTES, SegmentReader,
    extract_field_paths, node_matches_scalar, path_equals, path_matches,
};

use super::analytics::{
    AggregateLimits, AggregateMetric, AggregateRequest, AggregateResponse, AggregationEngine,
    GroupValue, MAX_GROUP_FIELDS, MetricInput, TimeBucket, bucket_start,
};
use super::error::{SearchError, SearchResult};
use super::limits::SearchLimits;
use super::typed_compare::{
    ColumnAccess, SortValue, canonical_scalar_bytes, compare_candidates, is_min_max_type,
    is_range_type, is_sum_type, is_typed_scalar, matches_range, matches_time_range,
    sort_tuple_for_doc,
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
                             doc_id: u64| {
                accumulator.accept(guard, reader, columns, doc_id)
            };
            self.scan(&plan, &compiled, &positive, prune, &mut guard, &mut visit)?
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
            self.scan(&plan, &compiled, &positive, prune, &mut guard, &mut visit)?
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
    ) -> SearchResult<CompiledQuery> {
        request.query.validate(self.schema, budgets)?;
        request.top_k.validate(budgets)?;
        let compiled = validate_query(&request.query, plan)?;
        request.sort.validate(self.schema)?;
        for field in &request.sort.fields {
            let Some(plan) = plan.field(&field.field) else {
                return Err(unsupported("sort_field"));
            };
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
    ) -> SearchResult<(Option<TimeBucket>, CompiledQuery)> {
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
        let compiled = validate_query(&request.query, plan)?;
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

    fn scan<'g, F>(
        &self,
        plan: &TypedPlan,
        query: &CompiledQuery,
        positive: &[TimeConjunct],
        prune: bool,
        guard: &mut ScanGuard<'g>,
        visit: &mut F,
    ) -> SearchResult<TypedScanDiagnostics>
    where
        F: FnMut(&mut ScanGuard<'g>, &SegmentReader, &ColumnAccess<'_>, u64) -> SearchResult<()>,
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
                if evaluate_query(guard, &columns, &json, query, doc_id)? {
                    diagnostics.matching_documents = diagnostics
                        .matching_documents
                        .checked_add(1)
                        .ok_or_else(|| counter_overflow("matching_documents"))?;
                    visit(guard, reader, &columns, doc_id)?;
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
    And(Vec<CompiledQuery>),
    Or(Vec<CompiledQuery>),
    Not(Box<CompiledQuery>),
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
}

fn evaluate_query(
    guard: &mut ScanGuard<'_>,
    columns: &ColumnAccess<'_>,
    json: &JsonAccess<'_>,
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
                if !evaluate_query(guard, columns, json, query, doc_id)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        CompiledQuery::Or(queries) => {
            for query in queries {
                if evaluate_query(guard, columns, json, query, doc_id)? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
        CompiledQuery::Not(inner) => Ok(!evaluate_query(guard, columns, json, inner, doc_id)?),
        CompiledQuery::JsonExists { id, path } => json.match_exists(*id, path, doc_id, guard),
        CompiledQuery::JsonEquals { id, path, scalar } => {
            json.match_equals(*id, path, scalar, doc_id, guard)
        }
    }
}

fn validate_query(query: &Query, plan: &TypedPlan) -> SearchResult<CompiledQuery> {
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
        Query::And(queries) => {
            let mut compiled = Vec::with_capacity(queries.len());
            for query in queries {
                compiled.push(validate_query(query, plan)?);
            }
            Ok(CompiledQuery::And(compiled))
        }
        Query::Or(queries) => {
            let mut compiled = Vec::with_capacity(queries.len());
            for query in queries {
                compiled.push(validate_query(query, plan)?);
            }
            Ok(CompiledQuery::Or(compiled))
        }
        Query::Not(inner) => Ok(CompiledQuery::Not(Box::new(validate_query(inner, plan)?))),
        other => Err(SearchError::UnsupportedOperator {
            operator: query_label(other),
        }),
    }
}

fn validate_json_path(path: &JsonPathExpr) -> SearchResult<()> {
    let segments = path.segments();
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
        doc_id: u64,
    ) -> SearchResult<()> {
        self.total_hits = self
            .total_hits
            .checked_add(1)
            .ok_or_else(|| counter_overflow("total_hits"))?;
        let tuple = sort_tuple_for_doc(columns, reader.schema(), self.sort, doc_id)?;
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

fn fingerprint(query: &CompiledQuery, sort: &Sort) -> SearchResult<[u8; 32]> {
    let mut buffer = Vec::new();
    encode_query(&mut buffer, query)?;
    encode_sort(&mut buffer, sort);
    let mut hasher = Sha256::new();
    hasher.update(&buffer);
    Ok(hasher.finalize().into())
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
    }
    Ok(())
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
