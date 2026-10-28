//! PR 15B benchmark/test-only deterministic scaling fixture and oracle.
//!
//! Everything here is **benchmark-only** code. It uses only the public
//! `quervant-core` writer/reader/search APIs and an independently derived
//! arithmetic oracle over the frozen PR15A row truth table. It never imports a
//! production evaluator to compute an expected answer.
//!
//! The eight-row `pr15a_v1` fixture remains the canonical semantic golden
//! fixture. The 2K/10K/100K corpora generated here are deterministic synthetic
//! **scaling extensions** with their own digest; they are not a replacement for
//! `benchmarks/datasets/pr15a_v1.json`.

#![allow(dead_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, NeverCancel};
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
    NumericAggregate,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
    SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Cursor, Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{
    FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue, Timestamp,
};
use quervant_core::index::{Index, IndexLimits, PitHandle, ReaderSnapshot};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch_pinned,
};
use quervant_core::storage::{Directory, MemoryDirectory};
use sha2::{Digest, Sha256};

/// Frozen scaling-extension version identifier.
pub const FIXTURE_VERSION: &str = "pr15b_v1";
/// Canonical PR15A fixture bytes, compiled into every consumer of this module.
pub const CANONICAL_JSON: &str = include_str!("../../../../benchmarks/datasets/pr15a_v1.json");
/// Frozen SHA-256 of the canonical PR15A fixture (external `sha256sum`).
pub const PR15A_V1_SHA256: &str =
    "104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087";

/// Default top-K for workloads whose specification does not override it.
pub const DEFAULT_K: usize = 100;
/// Fixed lower timestamp base for every generated record.
pub const TS_BASE: i64 = 1_000_000;
/// Fixed PIT clock used by the pinned batch benchmarks.
pub const NOW_MICROS: i64 = 1_000;
/// Fixed cursor deadline used by the pinned batch benchmarks.
pub const DEADLINE_MICROS: i64 = 10_000;
/// Opt-in environment flag for the optional 1M corpus.
pub const LARGE_ENV: &str = "QUERVANT_PR15B_LARGE";
/// Opt-in environment flag for the optional 64-segment stress lane.
pub const SEG64_ENV: &str = "QUERVANT_PR15B_SEG64";

/// One frozen PR15A source row, used as the template for `i % 8`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Template {
    pub title: &'static str,
    pub host: &'static str,
    pub ip: &'static str,
    /// `None` is an explicit JSON `null` severity.
    pub severity: Option<i64>,
    /// `None` means the `tags` key is absent; `Some(&[])` is an empty array.
    pub tags: Option<&'static [&'static str]>,
}

/// The eight canonical PR15A rows in template order.
pub const BASE_ROWS: [Template; 8] = [
    Template {
        title: "alpha beta",
        host: "h1",
        ip: "10.0.0.1",
        severity: Some(1),
        tags: Some(&["red", "blue"]),
    },
    Template {
        title: "alpha",
        host: "h2",
        ip: "10.0.0.2",
        severity: Some(2),
        tags: Some(&["blue"]),
    },
    Template {
        title: "beta",
        host: "h1",
        ip: "192.0.2.1",
        severity: Some(3),
        tags: Some(&[]),
    },
    Template {
        title: "gamma",
        host: "h3",
        ip: "2001:db8::1",
        severity: None,
        tags: None,
    },
    Template {
        title: "alpha gamma",
        host: "h1",
        ip: "10.0.1.1",
        severity: Some(2),
        tags: Some(&["red"]),
    },
    Template {
        title: "beta gamma",
        host: "h2",
        ip: "192.0.2.2",
        severity: Some(4),
        tags: None,
    },
    Template {
        title: "delta",
        host: "h3",
        ip: "2001:db8::2",
        severity: Some(0),
        tags: Some(&[]),
    },
    Template {
        title: "alpha",
        host: "h2",
        ip: "10.0.0.8",
        severity: Some(5),
        tags: Some(&["green"]),
    },
];

/// The frozen `pr15a_v1` extension schema.
#[must_use]
pub fn schema() -> Schema {
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
                "body",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "ip",
                FieldType::IpAddress,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
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
    .expect("pr15b scaling schema")
}

/// Built-in analyzer registry.
#[must_use]
pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// Stable key for generated record `i`.
#[must_use]
pub fn record_key(i: usize) -> String {
    format!("d{i:08}")
}

/// Frozen template for generated record `i`.
#[must_use]
pub fn template(i: usize) -> &'static Template {
    &BASE_ROWS[i % 8]
}

/// Canonical JSON body for one template, preserving null/absent/empty states.
#[must_use]
pub fn body(template: &Template) -> JsonValue {
    let mut entries = vec![(
        "severity".to_owned(),
        match template.severity {
            Some(value) => JsonValue::Number(JsonNumber::I64(value)),
            None => JsonValue::Null,
        },
    )];
    if let Some(tags) = template.tags {
        entries.push((
            "tags".to_owned(),
            JsonValue::Array(
                tags.iter()
                    .map(|tag| JsonValue::String((*tag).to_owned()))
                    .collect(),
            ),
        ));
    }
    JsonValue::Object(entries)
}

/// Build one generated document. All fields are derived from `i` and
/// `i % 8`; there is no random input.
#[must_use]
pub fn document(i: usize) -> Document {
    let template = template(i);
    let mut document = Document::new(DocumentKey::new(record_key(i)).expect("generated key"));
    insert(
        &mut document,
        "title",
        FieldValue::Text(template.title.to_owned()),
    );
    insert(
        &mut document,
        "host",
        FieldValue::Keyword(template.host.to_owned()),
    );
    insert(&mut document, "n", FieldValue::I64(i as i64));
    insert(
        &mut document,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(TS_BASE + i as i64)),
    );
    insert(
        &mut document,
        "ip",
        FieldValue::Ip(template.ip.parse().expect("generated ip")),
    );
    insert(&mut document, "body", FieldValue::Json(body(template)));
    document
}

fn insert(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("generated insert");
}

/// Validate the frozen synthetic shape before any index is created.
///
/// `N` must be positive and divisible by eight so every template occurs a whole
/// number of times. `S` must be at least one and no larger than `N` so every
/// contiguous range is non-empty. `N` need not be divisible by `S`; the frozen
/// split rule is `floor(j * N / S)`.
pub fn validate_shape(n: usize, s: usize) -> Result<(), String> {
    if n == 0 {
        return Err("N must be positive".to_owned());
    }
    if n % 8 != 0 {
        return Err(format!("N={n} is not divisible by 8"));
    }
    if s == 0 {
        return Err("S must be at least one".to_owned());
    }
    if s > n {
        return Err(format!("S={s} exceeds N={n}"));
    }
    Ok(())
}

/// Contiguous `(start, end)` ranges for `S` segments and `N` records.
#[must_use]
pub fn segment_bounds(n: usize, s: usize) -> Vec<(usize, usize)> {
    (0..s).map(|j| (j * n / s, (j + 1) * n / s)).collect()
}

/// Canonical row text used by every deterministic digest in this module.
#[must_use]
pub fn canonical_row_text(i: usize) -> String {
    let template = template(i);
    let severity = match template.severity {
        Some(value) => value.to_string(),
        None => "null".to_owned(),
    };
    let tags = match template.tags {
        Some([]) => "empty".to_owned(),
        Some(tags) => tags.join(","),
        None => "absent".to_owned(),
    };
    format!(
        "{i}|{}|{}|{}|{}|{}|{}|{}|{}",
        record_key(i),
        template.title,
        template.host,
        i,
        TS_BASE + i as i64,
        template.ip,
        severity,
        tags
    )
}

/// SHA-256 over the canonical generated rows for `N`.
#[must_use]
pub fn rows_sha256(n: usize) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(FIXTURE_VERSION.as_bytes());
    hasher.update((n as u64).to_be_bytes());
    for i in 0..n {
        hasher.update(canonical_row_text(i).as_bytes());
        hasher.update(b"\n");
    }
    hasher.finalize().into()
}

/// SHA-256 over the generated rows plus the exact `N`/`S` segment boundaries.
#[must_use]
pub fn corpus_sha256(n: usize, s: usize) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(FIXTURE_VERSION.as_bytes());
    hasher.update((n as u64).to_be_bytes());
    hasher.update((s as u64).to_be_bytes());
    for (start, end) in segment_bounds(n, s) {
        hasher.update((start as u64).to_be_bytes());
        hasher.update((end as u64).to_be_bytes());
    }
    hasher.update(rows_sha256(n));
    hasher.finalize().into()
}

/// Lowercase hex encoding of a digest.
#[must_use]
pub fn hex(digest: &[u8]) -> String {
    use std::fmt::Write as _;
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        write!(out, "{byte:02x}").expect("writing to String cannot fail");
    }
    out
}

/// SHA-256 of the compiled canonical PR15A fixture bytes.
#[must_use]
pub fn canonical_fixture_sha256() -> [u8; 32] {
    Sha256::digest(CANONICAL_JSON.as_bytes()).into()
}

/// Assert the compiled canonical fixture still matches the frozen digest.
pub fn assert_canonical_fixture_digest() {
    let actual = hex(&canonical_fixture_sha256());
    assert_eq!(
        actual, PR15A_V1_SHA256,
        "benchmarks/datasets/pr15a_v1.json changed; bump the fixture version and freeze record"
    );
    assert!(
        CANONICAL_JSON.contains("\"version\": \"pr15a_v1\""),
        "canonical fixture must declare pr15a_v1"
    );
}

/// A built, committed scaling fixture kept resident for every timed sample.
pub struct Corpus {
    pub n: usize,
    pub s: usize,
    pub directory: Arc<dyn Directory>,
    pub index: Index,
    pub snapshot: Arc<ReaderSnapshot>,
    pub schema: Schema,
    pub registry: AnalyzerRegistry,
    pub rows_sha256: [u8; 32],
    pub corpus_sha256: [u8; 32],
}

/// Fixture-only build limits. Search limits and production defaults are never
/// relaxed; only the immutable-fixture construction bounds are raised so the
/// prescribed `N`/`S` topology can be built exactly.
#[must_use]
pub fn fixture_limits(n: usize, s: usize) -> IndexLimits {
    let largest = segment_bounds(n, s)
        .into_iter()
        .map(|(start, end)| end - start)
        .max()
        .unwrap_or(1);
    IndexLimits::new()
        .with_max_pending_docs(largest as u64 + 16)
        .with_max_pending_bytes(1024 * 1024 * 1024)
        .with_max_segments_per_commit(s as u64 + 8)
        .with_max_manifest_bytes(64 * 1024 * 1024)
        .with_max_snapshot_bytes(4 * 1024 * 1024 * 1024)
}

/// Build exactly `S` immutable segments for a deterministic `N`-record corpus.
///
/// Panics when the requested shape is invalid or when the physical snapshot
/// does not contain exactly `S` segments and `N` live documents. Callers must
/// not silently relabel a mismatched topology.
#[must_use]
pub fn build_corpus(n: usize, s: usize) -> Corpus {
    validate_shape(n, s).unwrap_or_else(|error| panic!("invalid fixture shape: {error}"));
    let schema = schema();
    let registry = registry();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let limits = fixture_limits(n, s);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema.clone(),
        registry.clone(),
        limits.clone(),
    )
    .expect("create fixture index");
    {
        let mut writer = index.writer().expect("fixture writer");
        for (start, end) in segment_bounds(n, s) {
            for i in start..end {
                writer.insert(document(i)).expect("fixture insert");
            }
            writer.flush().expect("fixture flush");
        }
        writer.commit().expect("fixture commit");
    }
    let reopened =
        Index::open_with_limits(directory.clone(), schema.clone(), registry.clone(), limits)
            .expect("reopen fixture");
    let snapshot = reopened.snapshot();
    assert_eq!(
        snapshot.segment_count(),
        s,
        "physical segment count must equal configured S={s} for N={n}"
    );
    assert_eq!(
        snapshot.document_count(),
        n as u64,
        "physical document count must equal N={n}"
    );
    Corpus {
        n,
        s,
        directory,
        index: reopened,
        snapshot,
        schema,
        registry,
        rows_sha256: rows_sha256(n),
        corpus_sha256: corpus_sha256(n, s),
    }
}

impl Corpus {
    /// Execute one unified request against the resident snapshot.
    #[must_use]
    pub fn run(&self, request: &UnifiedRequest) -> UnifiedResponse {
        UnifiedSearcher::new(
            &self.snapshot,
            &self.schema,
            &self.registry,
            SearchLimits::default(),
        )
        .search(request, &Budgets::new(), &NeverCancel)
        .expect("unified search")
    }

    /// Execute one pinned batch against a retained PIT.
    #[must_use]
    pub fn run_batch(&self, pit: &PitHandle, batch: &BatchQueryRequest) -> BatchQueryResponse {
        execute_batch_pinned(
            pit,
            &self.schema,
            &self.registry,
            SearchLimits::default(),
            batch,
            &batch_policy(),
            &CapabilitySet::new(),
            &NeverCancel,
            Timestamp::from_micros(NOW_MICROS),
            Timestamp::from_micros(DEADLINE_MICROS),
        )
        .expect("pinned batch")
    }
}

/// Top-K constructor with a clear panic message for benchmark configuration.
#[must_use]
pub fn top_k(k: usize) -> TopK {
    TopK::new(k).expect("top-k must be positive")
}

/// `title=alpha`.
#[must_use]
pub fn query_alpha() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

/// `title=gamma`.
#[must_use]
pub fn query_gamma() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("gamma".into()),
    }
}

/// Absent lexical sentinel (`0/8` templates).
#[must_use]
pub fn query_absent() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("zzzz_absent_15b".into()),
    }
}

/// Typed identity predicate `n == 0`.
#[must_use]
pub fn query_rare() -> Query {
    Query::In {
        field: "n".into(),
        values: vec![FieldValue::I64(0)],
    }
}

/// `title=alpha AND n >= N/2`.
#[must_use]
pub fn query_common_mixed(n: usize) -> Query {
    Query::And(vec![
        query_alpha(),
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64((n / 2) as i64)),
            upper: Bound::Unbounded,
        },
    ])
}

/// IPv4 `10.0.0.0/24` plus the production half-open `TimeRange`.
///
/// The approved contract is `[start, end)`. The workload specification's prose
/// said "inclusive"; the production contract is normative, so the interval end
/// is exclusive here and the independent oracle uses the same half-open test.
#[must_use]
pub fn query_cidr_time(n: usize) -> Query {
    Query::And(vec![
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("10.0.0.0".parse().expect("cidr addr"), 24)
                .expect("cidr prefix"),
        },
        Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(TS_BASE + (n / 4) as i64),
            end: Timestamp::from_micros(TS_BASE + (n / 2) as i64),
        },
    ])
}

/// `body.severity == 2`.
#[must_use]
pub fn query_json_severity() -> Query {
    Query::JsonPathEquals {
        field: "body".into(),
        path: JsonPathExpr::parse("$.severity").expect("severity path"),
        value: FieldValue::I64(2),
    }
}

/// Match-all sorted by numeric `n` ascending.
#[must_use]
pub fn request_sort_n(k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(Query::MatchAll, top_k(k));
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request
}

/// Match-all sorted by `host` ascending (key is the final tie-break).
#[must_use]
pub fn request_sort_host(k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(Query::MatchAll, top_k(k));
    request.sort = Sort::new(vec![SortField::new("host", SortDirection::Asc)]);
    request
}

/// Match-all sorted by `n` with an explicit projection.
#[must_use]
pub fn request_projection(k: usize, projection: Projection) -> UnifiedRequest {
    let mut request = request_sort_n(k);
    request.projection = projection;
    request
}

/// U01 absent lexical request.
#[must_use]
pub fn request_absent() -> UnifiedRequest {
    UnifiedRequest::new(query_absent(), top_k(DEFAULT_K))
}

/// U02 rare typed request.
#[must_use]
pub fn request_rare() -> UnifiedRequest {
    UnifiedRequest::new(query_rare(), top_k(DEFAULT_K))
}

/// U03 medium lexical request.
#[must_use]
pub fn request_medium() -> UnifiedRequest {
    UnifiedRequest::new(query_gamma(), top_k(DEFAULT_K))
}

/// U04 lexical+typed intersection request.
#[must_use]
pub fn request_common_mixed(n: usize) -> UnifiedRequest {
    UnifiedRequest::new(query_common_mixed(n), top_k(DEFAULT_K))
}

/// U05 CIDR+time request.
#[must_use]
pub fn request_cidr_time(n: usize) -> UnifiedRequest {
    UnifiedRequest::new(query_cidr_time(n), top_k(DEFAULT_K))
}

/// U06 JSON scalar request.
#[must_use]
pub fn request_json_severity() -> UnifiedRequest {
    UnifiedRequest::new(query_json_severity(), top_k(DEFAULT_K))
}

/// Convert a unified request into an equivalent batch slot request.
#[must_use]
pub fn to_query_request(request: &UnifiedRequest) -> QueryRequest {
    let mut slot = QueryRequest::new(request.query.clone());
    slot.sort = request.sort.clone();
    slot.top_k = request.top_k;
    slot.projection = request.projection.clone();
    slot
}

/// U09 aggregation slot: `MatchAll` grouped by host with count and sum(n).
#[must_use]
pub fn query_request_aggregate_host() -> QueryRequest {
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let mut request = QueryRequest::new(Query::MatchAll);
    request.top_k = top_k(DEFAULT_K);
    request.aggregation = Some(aggregation);
    request
}

/// Batch-wide budget policy used by benchmark/test pinned batches.
#[must_use]
pub fn batch_policy() -> BudgetPolicy {
    let base = Budgets::new()
        .with(BudgetKind::QueriesPerBatch, 16)
        .expect("nonzero batch query budget")
        .with(BudgetKind::BatchMemoryBytes, 1 << 30)
        .expect("nonzero batch memory budget")
        .with(BudgetKind::BatchResponseBytes, 1 << 30)
        .expect("nonzero batch response budget")
        .with(BudgetKind::BatchAggregate, 1 << 30)
        .expect("nonzero batch aggregate budget");
    BudgetPolicy::new(base, Budgets::new(), Budgets::new(), Budgets::new())
}

/// One pinned batch with `queries` in explicit order.
#[must_use]
pub fn pinned_batch(pit: &PitHandle, queries: Vec<QueryRequest>) -> BatchQueryRequest {
    BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(16))
}

/// U09 pinned batch.
#[must_use]
pub fn batch_u09(pit: &PitHandle) -> BatchQueryRequest {
    pinned_batch(pit, vec![query_request_aggregate_host()])
}

/// U10 pinned batch: U04, U05, U09 in exactly that order.
#[must_use]
pub fn batch_u10(pit: &PitHandle, n: usize) -> BatchQueryRequest {
    pinned_batch(
        pit,
        vec![
            to_query_request(&request_common_mixed(n)),
            to_query_request(&request_cidr_time(n)),
            query_request_aggregate_host(),
        ],
    )
}

/// Extract a successful batch slot.
#[must_use]
pub fn success(response: &BatchQueryResponse, slot: usize) -> &SearchResponse {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("batch slot {slot} was not successful: {other:?}"),
    }
}

/// Hit keys in returned order.
#[must_use]
pub fn keys(response: &SearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// Hit keys in returned order for a unified response.
#[must_use]
pub fn unified_keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

// ---------------------------------------------------------------------------
// Independent arithmetic oracle (never calls the engine)
// ---------------------------------------------------------------------------

fn keys_where(n: usize, predicate: impl Fn(usize) -> bool) -> Vec<String> {
    (0..n).filter(|i| predicate(*i)).map(record_key).collect()
}

/// `alpha` templates `{0,1,4,7}`.
#[must_use]
pub fn expected_alpha(n: usize) -> Vec<String> {
    keys_where(n, |i| matches!(i % 8, 0 | 1 | 4 | 7))
}

/// `gamma` templates `{3,4,5}`.
#[must_use]
pub fn expected_medium(n: usize) -> Vec<String> {
    keys_where(n, |i| matches!(i % 8, 3..=5))
}

/// Absent lexical sentinel: empty.
#[must_use]
pub fn expected_absent(_n: usize) -> Vec<String> {
    Vec::new()
}

/// `n == 0`: exactly the first record.
#[must_use]
pub fn expected_rare(_n: usize) -> Vec<String> {
    vec![record_key(0)]
}

/// `alpha AND n >= N/2`.
#[must_use]
pub fn expected_common_mixed(n: usize) -> Vec<String> {
    keys_where(n, |i| matches!(i % 8, 0 | 1 | 4 | 7) && i >= n / 2)
}

/// IPv4 `/24` (`{0,1,7}`) intersect the half-open `[N/4, N/2)` index window.
#[must_use]
pub fn expected_cidr_time(n: usize) -> Vec<String> {
    keys_where(n, |i| matches!(i % 8, 0 | 1 | 7) && i >= n / 4 && i < n / 2)
}

/// `body.severity == 2` templates `{1,4}`.
#[must_use]
pub fn expected_json_severity(n: usize) -> Vec<String> {
    keys_where(n, |i| matches!(i % 8, 1 | 4))
}

/// Exact ascending-`n` prefix of length `min(N, K)`.
#[must_use]
pub fn expected_sorted_prefix(n: usize, k: usize) -> Vec<String> {
    (0..n.min(k)).map(record_key).collect()
}

/// Exact host-then-key ascending prefix, matching the contract tie-break.
#[must_use]
pub fn expected_host_prefix(n: usize, k: usize) -> Vec<String> {
    let mut sequence = Vec::with_capacity(n);
    for host in ["h1", "h2", "h3"] {
        for i in 0..n {
            if template(i).host == host {
                sequence.push(record_key(i));
            }
        }
    }
    sequence.truncate(k.min(sequence.len()));
    sequence
}

/// Independent host group counts and sums in canonical host order.
#[must_use]
pub fn expected_host_groups(n: usize) -> Vec<(String, u64, i128)> {
    let mut groups: BTreeMap<&'static str, (u64, i128)> = BTreeMap::new();
    for i in 0..n {
        let entry = groups.entry(template(i).host).or_insert((0, 0));
        entry.0 += 1;
        entry.1 += i as i128;
    }
    groups
        .into_iter()
        .map(|(host, (count, sum))| (host.to_owned(), count, sum))
        .collect()
}

/// Global exact-distinct host count for this template set.
#[must_use]
pub fn expected_distinct_hosts() -> u64 {
    BASE_ROWS
        .iter()
        .map(|template| template.host)
        .collect::<BTreeSet<_>>()
        .len() as u64
}

// ---------------------------------------------------------------------------
// Independent comparison helpers
// ---------------------------------------------------------------------------

/// Check an exact, ordered key sequence.
pub fn check_exact(actual: &[String], expected: &[String]) -> Result<(), String> {
    if actual == expected {
        Ok(())
    } else {
        Err(format!(
            "ordered key mismatch: actual {} keys, expected {} keys",
            actual.len(),
            expected.len()
        ))
    }
}

/// Check an exact set (order-insensitive) and exact total.
pub fn check_set(actual: &[String], total: u64, expected: &[String]) -> Result<(), String> {
    if total != expected.len() as u64 {
        return Err(format!(
            "total_hits={total} does not match independent oracle {}",
            expected.len()
        ));
    }
    let expected: BTreeSet<&str> = expected.iter().map(String::as_str).collect();
    let mut seen = BTreeSet::new();
    for key in actual {
        if !seen.insert(key) {
            return Err(format!("duplicate hit key {key}"));
        }
        if !expected.contains(key.as_str()) {
            return Err(format!(
                "hit key {key} is not in the independent oracle set"
            ));
        }
    }
    Ok(())
}

/// Check a truncated ranked lane: exact total, exact returned length, unique
/// keys and strict membership in the independent full-match set.
///
/// Independence limitation (recorded in `docs/pr-artifacts/pr-15b/oracles.md`):
/// the top-K *selection order* beyond the canonical eight-row fixture is not
/// reimplemented; only exact membership, count and uniqueness are gated.
pub fn check_ranked_prefix(
    actual: &[String],
    total: u64,
    expected: &[String],
    k: usize,
) -> Result<(), String> {
    if total != expected.len() as u64 {
        return Err(format!(
            "total_hits={total} does not match independent oracle {}",
            expected.len()
        ));
    }
    let expected_len = expected.len().min(k);
    if actual.len() != expected_len {
        return Err(format!(
            "returned {} hits, expected min(oracle={}, K={k})={expected_len}",
            actual.len(),
            expected.len()
        ));
    }
    check_set(actual, total, expected)
}

/// Compare contract aggregation groups with the independent arithmetic oracle.
pub fn check_host_groups(
    actual: &[(String, u64, i128)],
    expected: &[(String, u64, i128)],
) -> Result<(), String> {
    if actual == expected {
        Ok(())
    } else {
        Err(format!(
            "host group mismatch: actual {actual:?}, expected {expected:?}"
        ))
    }
}

/// Extract `(host, count, sum(n))` groups from a batch response slot.
#[must_use]
pub fn host_groups(response: &SearchResponse) -> Vec<(String, u64, i128)> {
    let aggregation = response
        .aggregation
        .as_ref()
        .expect("aggregation result required");
    aggregation
        .groups
        .iter()
        .map(|group| {
            let host = match &group.components[0] {
                AggregationGroupValue::Value(FieldValue::Keyword(host)) => host.clone(),
                other => panic!("unexpected group component {other:?}"),
            };
            let count = match group.metrics[0] {
                AggregationMetricValue::Count(count) => count,
                ref other => panic!("unexpected count metric {other:?}"),
            };
            let sum = match group.metrics[1] {
                AggregationMetricValue::Sum(NumericAggregate::Signed(sum)) => sum,
                ref other => panic!("unexpected sum metric {other:?}"),
            };
            (host, count, sum)
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Oracle gates executed before timing
// ---------------------------------------------------------------------------

fn assert_ok(result: Result<(), String>, context: &str) {
    if let Err(error) = result {
        panic!("PR15B oracle gate failed for {context}: {error}");
    }
}

/// Validate the exact physical topology and the documented arithmetic model.
pub fn assert_corpus_shape(corpus: &Corpus) {
    assert_canonical_fixture_digest();
    assert_eq!(corpus.snapshot.segment_count(), corpus.s, "segment count");
    assert_eq!(
        corpus.snapshot.document_count(),
        corpus.n as u64,
        "document count"
    );
    assert_eq!(corpus.rows_sha256, rows_sha256(corpus.n), "row digest");
    assert_eq!(
        corpus.corpus_sha256,
        corpus_sha256(corpus.n, corpus.s),
        "corpus digest"
    );
    assert_eq!(expected_alpha(corpus.n).len(), corpus.n / 2, "alpha share");
    assert_eq!(
        expected_medium(corpus.n).len(),
        corpus.n * 3 / 8,
        "gamma share"
    );
    assert_eq!(
        expected_json_severity(corpus.n).len(),
        corpus.n / 4,
        "severity share"
    );
    let groups = expected_host_groups(corpus.n);
    assert_eq!(
        groups.iter().map(|(_, count, _)| count).sum::<u64>(),
        corpus.n as u64,
        "host groups must cover the corpus"
    );
}

/// U01 absent lexical.
pub fn assert_absent(corpus: &Corpus) {
    let response = corpus.run(&request_absent());
    assert_ok(
        check_exact(&unified_keys(&response), &expected_absent(corpus.n)),
        "U01 absent",
    );
    assert_eq!(response.total_hits, 0, "U01 total_hits");
}

/// U02 rare typed identity.
pub fn assert_rare(corpus: &Corpus) {
    let response = corpus.run(&request_rare());
    let expected = expected_rare(corpus.n);
    assert_ok(check_exact(&unified_keys(&response), &expected), "U02 rare");
    assert_eq!(response.total_hits, 1, "U02 total_hits");
}

/// U03 medium lexical.
pub fn assert_medium(corpus: &Corpus) {
    let expected = expected_medium(corpus.n);
    assert_eq!(expected.len(), corpus.n * 3 / 8, "U03 oracle size");
    let response = corpus.run(&request_medium());
    assert_ok(
        check_ranked_prefix(
            &unified_keys(&response),
            response.total_hits,
            &expected,
            DEFAULT_K,
        ),
        "U03 medium",
    );
    assert_full_set(corpus, query_gamma(), &expected, "U03 medium full set");
}

/// U03/U04 full-set membership validation for corpora small enough to
/// materialize the complete match set without changing any production limit.
fn assert_full_set(corpus: &Corpus, query: Query, expected: &[String], context: &str) {
    if corpus.n > 100_000 || expected.len() > 100_000 {
        return;
    }
    let mut request = UnifiedRequest::new(query, top_k(expected.len().max(1)));
    request.projection = Projection::Fields(Vec::new());
    let response = corpus.run(&request);
    let mut actual = unified_keys(&response);
    actual.sort_unstable();
    let mut expected_sorted: Vec<String> = expected.to_vec();
    expected_sorted.sort_unstable();
    assert_ok(check_exact(&actual, &expected_sorted), context);
    assert_eq!(
        response.total_hits,
        expected.len() as u64,
        "{context} total"
    );
}

/// U04 lexical+typed intersection.
pub fn assert_common_mixed(corpus: &Corpus) {
    let expected = expected_common_mixed(corpus.n);
    let response = corpus.run(&request_common_mixed(corpus.n));
    assert_ok(
        check_ranked_prefix(
            &unified_keys(&response),
            response.total_hits,
            &expected,
            DEFAULT_K,
        ),
        "U04 common-mixed",
    );
    assert_full_set(
        corpus,
        query_common_mixed(corpus.n),
        &expected,
        "U04 common-mixed full set",
    );
}

/// U05 typed CIDR plus production half-open time range.
pub fn assert_cidr_time(corpus: &Corpus) {
    let expected = expected_cidr_time(corpus.n);
    let response = corpus.run(&request_cidr_time(corpus.n));
    let expected_prefix: Vec<String> = expected.iter().take(DEFAULT_K).cloned().collect();
    assert_ok(
        check_exact(&unified_keys(&response), &expected_prefix),
        "U05 cidr-time",
    );
    assert_eq!(response.total_hits, expected.len() as u64, "U05 total_hits");

    // Adversarial family boundary: `/0` must not be reinterpreted as `/24`, and
    // an IPv4 network must not match the IPv6 template rows.
    let wide = UnifiedRequest::new(
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("0.0.0.0".parse().expect("addr"), 0).expect("prefix"),
        },
        top_k(DEFAULT_K),
    );
    let wide_response = corpus.run(&wide);
    assert_ne!(
        wide_response.total_hits, response.total_hits,
        "IPv4 /0 must not be silently treated as /24"
    );
    for key in unified_keys(&wide_response) {
        let i: usize = key[1..].parse().expect("generated key index");
        let ip: std::net::IpAddr = template(i).ip.parse().expect("template ip");
        assert!(ip.is_ipv4(), "IPv4 /0 returned an IPv6 document");
    }
}

/// U06 JSON path scalar.
pub fn assert_json_severity(corpus: &Corpus) {
    let expected = expected_json_severity(corpus.n);
    let response = corpus.run(&request_json_severity());
    let expected_prefix: Vec<String> = expected.iter().take(DEFAULT_K).cloned().collect();
    assert_ok(
        check_exact(&unified_keys(&response), &expected_prefix),
        "U06 json-scalar",
    );
    assert_eq!(response.total_hits, expected.len() as u64, "U06 total_hits");
}

/// U07 explicit numeric sort with exact ascending prefix.
pub fn assert_sort_n(corpus: &Corpus, k: usize) {
    let expected = expected_sorted_prefix(corpus.n, k);
    let response = corpus.run(&request_sort_n(k));
    assert_ok(
        check_exact(&unified_keys(&response), &expected),
        "U07 sort-n",
    );
    assert_eq!(response.total_hits, corpus.n as u64, "U07 total_hits");
}

/// U07 companion: exact host tie-break ordering.
pub fn assert_sort_host(corpus: &Corpus, k: usize) {
    let expected = expected_host_prefix(corpus.n, k);
    let response = corpus.run(&request_sort_host(k));
    assert_ok(
        check_exact(&unified_keys(&response), &expected),
        "U07 host tie-break",
    );
    assert_eq!(response.total_hits, corpus.n as u64, "host sort total_hits");
}

/// U08 projection: `Source` and `Fields(host,n)` exact field states.
pub fn assert_projection(corpus: &Corpus) {
    let expected = expected_sorted_prefix(corpus.n, DEFAULT_K);

    let source = corpus.run(&request_projection(DEFAULT_K, Projection::Source));
    assert_ok(
        check_exact(&unified_keys(&source), &expected),
        "U08 source keys",
    );
    for hit in &source.hits {
        let i: usize = hit.key.as_str()[1..].parse().expect("key index");
        assert_eq!(hit.fields.len(), 6, "source must return all stored fields");
        let host = find_field(&hit.fields, "host");
        assert_eq!(
            host,
            Some(FieldValue::Keyword(template(i).host.to_owned())),
            "source host state"
        );
        let n = find_field(&hit.fields, "n");
        assert_eq!(n, Some(FieldValue::I64(i as i64)), "source n state");
        let body_field = find_field(&hit.fields, "body");
        assert_eq!(
            body_field,
            Some(FieldValue::Json(body(template(i)))),
            "source JSON null/absent/empty state"
        );
    }

    let fields = corpus.run(&request_projection(
        DEFAULT_K,
        Projection::Fields(vec!["host".into(), "n".into()]),
    ));
    assert_ok(
        check_exact(&unified_keys(&fields), &expected),
        "U08 fields keys",
    );
    for hit in &fields.hits {
        let i: usize = hit.key.as_str()[1..].parse().expect("key index");
        assert_eq!(hit.fields.len(), 2, "fields must return exactly two fields");
        assert_eq!(hit.fields[0].0, "host");
        assert_eq!(
            hit.fields[0].1,
            FieldValues::Single(FieldValue::Keyword(template(i).host.to_owned()))
        );
        assert_eq!(hit.fields[1].0, "n");
        assert_eq!(
            hit.fields[1].1,
            FieldValues::Single(FieldValue::I64(i as i64))
        );
    }
}

fn find_field(fields: &[(String, FieldValues)], name: &str) -> Option<FieldValue> {
    fields
        .iter()
        .find(|(field, _)| field == name)
        .and_then(|(_, values)| match values {
            FieldValues::Single(value) => Some(value.clone()),
            FieldValues::ExplicitNull => Some(FieldValue::Json(JsonValue::Null)),
            _ => None,
        })
}

/// U09 grouped aggregation.
pub fn assert_aggregation(corpus: &Corpus) {
    let pit = corpus.index.pin().expect("pit");
    let batch = batch_u09(&pit);
    let response = corpus.run_batch(&pit, &batch);
    let slot = success(&response, 0);
    assert_eq!(slot.total_hits, corpus.n as u64, "U09 total_hits");
    let actual = host_groups(slot);
    let expected = expected_host_groups(corpus.n);
    assert_ok(check_host_groups(&actual, &expected), "U09 groups");
    assert_eq!(
        actual.len() as u64,
        expected_distinct_hosts(),
        "U09 global exact-distinct host"
    );
}

/// U10 serial batch equals three standalone slot executions in order.
pub fn assert_batch(corpus: &Corpus) {
    let pit = corpus.index.pin().expect("pit");
    let batch = batch_u10(&pit, corpus.n);
    let response = corpus.run_batch(&pit, &batch);
    assert_eq!(response.len(), 3, "U10 slot count");

    for slot in 0..3 {
        let standalone = pinned_batch(
            &pit,
            vec![batch.queries.get(slot).expect("slot request").clone()],
        );
        let standalone = corpus.run_batch(&pit, &standalone);
        let expected = success(&standalone, 0);
        let actual = success(&response, slot);
        assert_ok(
            check_exact(&keys(actual), &keys(expected)),
            "U10 slot order",
        );
        assert_eq!(actual.total_hits, expected.total_hits, "U10 slot total");
        assert_eq!(
            actual.aggregation, expected.aggregation,
            "U10 slot aggregation"
        );
    }
}

/// Run one page with an optional cursor and return its sorted key sequence.
fn run_page(
    pit: &PitHandle,
    corpus: &Corpus,
    page_size: usize,
    cursor: Option<Cursor>,
) -> (Vec<String>, Option<Cursor>) {
    let mut slot = to_query_request(&request_sort_n(page_size));
    slot.cursor = cursor;
    let batch = pinned_batch(pit, vec![slot]);
    let response = corpus.run_batch(pit, &batch);
    let page = success(&response, 0);
    (keys(page), page.next_cursor.clone())
}

/// U12 pinned pagination: pages concatenate to the exact sorted key sequence.
pub fn assert_pinned_pages(corpus: &Corpus, page_size: usize) {
    let pit = corpus.index.pin().expect("pit");
    let mut all = Vec::new();
    let mut cursor = None;
    let mut pages = 0usize;
    loop {
        let (page, next) = run_page(&pit, corpus, page_size, cursor);
        all.extend(page);
        pages += 1;
        cursor = next;
        if cursor.is_none() {
            break;
        }
        assert!(pages < 1_000, "pagination did not terminate");
    }
    assert_ok(
        check_exact(&all, &expected_sorted_prefix(corpus.n, corpus.n)),
        "U12 pinned pages",
    );
}

// ---------------------------------------------------------------------------
// U13 separate geo provenance fixture
// ---------------------------------------------------------------------------

/// One frozen geo point record (key, lon, lat).
pub const GEO_ROWS: [(&str, f64, f64); 8] = [
    ("g0", 0.0, 0.0),
    ("g1", 1.0, 1.0),
    ("g2", -1.0, -1.0),
    ("g3", 5.0, 5.0),
    ("g4", 11.0, 0.0),
    ("g5", 0.0, -11.0),
    ("g6", 170.0, 0.0),
    ("g7", -170.0, 80.0),
];

/// PR12-style geo schema (single multi-valued GeoPoint field).
#[must_use]
pub fn geo_schema() -> Schema {
    Schema::new(
        vec![FieldDefinition::new(
            "loc",
            FieldType::GeoPoint,
            Cardinality::Multi,
            FieldOptions::new(true, true, true),
        )],
        None,
    )
    .expect("pr15b geo schema")
}

/// Fixed bounding box used by U13.
#[must_use]
pub fn geo_bbox() -> GeoBoundingBox {
    GeoBoundingBox::new(-10.0, -10.0, 10.0, 10.0).expect("fixed bbox")
}

/// U13 geo request.
#[must_use]
pub fn request_geo_bbox() -> UnifiedRequest {
    UnifiedRequest::new(
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: geo_bbox(),
        },
        top_k(DEFAULT_K),
    )
}

/// Independent inclusive bounding-box oracle over the fixed point table.
#[must_use]
pub fn expected_geo() -> Vec<String> {
    let bbox = geo_bbox();
    GEO_ROWS
        .iter()
        .filter(|(_, lon, lat)| {
            *lon >= bbox.west && *lon <= bbox.east && *lat >= bbox.south && *lat <= bbox.north
        })
        .map(|(key, _, _)| (*key).to_owned())
        .collect()
}

/// Built, resident U13 geo fixture.
pub struct GeoCorpus {
    pub index: Index,
    pub snapshot: Arc<ReaderSnapshot>,
    pub schema: Schema,
    pub registry: AnalyzerRegistry,
}

impl GeoCorpus {
    /// Execute one unified request against the resident geo snapshot.
    #[must_use]
    pub fn run(&self, request: &UnifiedRequest) -> UnifiedResponse {
        UnifiedSearcher::new(
            &self.snapshot,
            &self.schema,
            &self.registry,
            SearchLimits::default(),
        )
        .search(request, &Budgets::new(), &NeverCancel)
        .expect("geo unified search")
    }
}

/// Build the fixed U13 geo corpus (one immutable segment).
#[must_use]
pub fn build_geo_corpus() -> GeoCorpus {
    let schema = geo_schema();
    let registry = registry();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema.clone(),
        registry.clone(),
        IndexLimits::default(),
    )
    .expect("create geo index");
    {
        let mut writer = index.writer().expect("geo writer");
        for (key, lon, lat) in GEO_ROWS {
            let mut document = Document::new(DocumentKey::new(key).expect("geo key"));
            document
                .insert(
                    "loc",
                    FieldValues::Multi(vec![FieldValue::GeoPoint(
                        GeoPoint::new(lon, lat).expect("geo point"),
                    )]),
                )
                .expect("geo insert");
            writer.insert(document).expect("geo insert");
        }
        writer.commit().expect("geo commit");
    }
    let reopened = Index::open_existing(directory, schema.clone(), registry.clone())
        .expect("reopen geo index");
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.segment_count(), 1, "geo physical segment count");
    assert_eq!(snapshot.document_count(), GEO_ROWS.len() as u64);
    GeoCorpus {
        index: reopened,
        snapshot,
        schema,
        registry,
    }
}

/// SHA-256 over the fixed geo fixture rows.
#[must_use]
pub fn geo_sha256() -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(b"pr15b_geo_v1");
    for (key, lon, lat) in GEO_ROWS {
        hasher.update(key.as_bytes());
        hasher.update(lon.to_bits().to_be_bytes());
        hasher.update(lat.to_bits().to_be_bytes());
    }
    hasher.finalize().into()
}

/// U13 oracle gate. Also proves an outside-everything bbox is empty.
pub fn assert_geo(geo: &GeoCorpus) {
    let response = geo.run(&request_geo_bbox());
    let expected = expected_geo();
    assert_ok(
        check_exact(&unified_keys(&response), &expected),
        "U13 geo-bbox",
    );
    assert_eq!(response.total_hits, expected.len() as u64, "U13 total_hits");

    let empty = UnifiedRequest::new(
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(50.0, 50.0, 60.0, 60.0).expect("empty bbox"),
        },
        top_k(DEFAULT_K),
    );
    let empty_response = geo.run(&empty);
    assert_eq!(
        empty_response.total_hits, 0,
        "U13 outside bbox must be empty"
    );
}

// ---------------------------------------------------------------------------
// Fixture metadata emitted before timing
// ---------------------------------------------------------------------------

/// Accepted release-profiling workload identifiers.
pub const PROFILE_WORKLOADS: [&str; 7] = [
    "absent",
    "rare",
    "mixed",
    "json",
    "sort",
    "aggregation",
    "batch",
];

/// One accepted release-profiling workload.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProfileWorkload {
    Absent,
    Rare,
    Mixed,
    Json,
    Sort,
    Aggregation,
    Batch,
}

impl ProfileWorkload {
    /// Stable CLI identifier.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Absent => "absent",
            Self::Rare => "rare",
            Self::Mixed => "mixed",
            Self::Json => "json",
            Self::Sort => "sort",
            Self::Aggregation => "aggregation",
            Self::Batch => "batch",
        }
    }
}

/// Parse one accepted profiling workload identifier.
pub fn parse_profile_workload(value: &str) -> Result<ProfileWorkload, String> {
    match value {
        "absent" => Ok(ProfileWorkload::Absent),
        "rare" => Ok(ProfileWorkload::Rare),
        "mixed" => Ok(ProfileWorkload::Mixed),
        "json" => Ok(ProfileWorkload::Json),
        "sort" => Ok(ProfileWorkload::Sort),
        "aggregation" => Ok(ProfileWorkload::Aggregation),
        "batch" => Ok(ProfileWorkload::Batch),
        other => Err(format!(
            "unknown workload {other}; expected one of {}",
            PROFILE_WORKLOADS.join(", ")
        )),
    }
}

/// Parse a positive profiling duration bounded to at most 120 seconds.
pub fn parse_profile_seconds(value: &str) -> Result<u64, String> {
    let seconds: u64 = value
        .parse()
        .map_err(|_| format!("seconds must be a positive integer, got {value:?}"))?;
    if seconds == 0 {
        return Err("seconds must be at least 1".to_owned());
    }
    if seconds > 120 {
        return Err(format!("seconds must be at most 120, got {seconds}"));
    }
    Ok(seconds)
}

/// One corpus provenance record.
pub struct CorpusMeta {
    pub label: String,
    pub n: usize,
    pub s: usize,
    pub rows_sha256: String,
    pub corpus_sha256: String,
    pub physical_segments: usize,
    pub document_count: u64,
}

/// Collect provenance for a scaling corpus.
#[must_use]
pub fn corpus_meta(corpus: &Corpus) -> CorpusMeta {
    CorpusMeta {
        label: format!("n{}_s{}", corpus.n, corpus.s),
        n: corpus.n,
        s: corpus.s,
        rows_sha256: hex(&corpus.rows_sha256),
        corpus_sha256: hex(&corpus.corpus_sha256),
        physical_segments: corpus.snapshot.segment_count(),
        document_count: corpus.snapshot.document_count(),
    }
}

/// Collect provenance for the separate geo corpus.
#[must_use]
pub fn geo_meta(geo: &GeoCorpus) -> CorpusMeta {
    CorpusMeta {
        label: "geo_n8_s1".to_owned(),
        n: GEO_ROWS.len(),
        s: 1,
        rows_sha256: hex(&geo_sha256()),
        corpus_sha256: hex(&geo_sha256()),
        physical_segments: geo.snapshot.segment_count(),
        document_count: geo.snapshot.document_count(),
    }
}

/// Render the fixture metadata JSON. Hand-written because the benchmark target
/// must not add a serialization dependency.
#[must_use]
pub fn fixture_metadata_json(corpora: &[CorpusMeta]) -> String {
    let mut out = String::new();
    out.push_str("{\n");
    out.push_str("  \"schema\": \"quervant-pr15b-fixture-v1\",\n");
    out.push_str(&format!("  \"workload_version\": \"{FIXTURE_VERSION}\",\n"));
    out.push_str(&format!(
        "  \"canonical_sha256\": \"{}\",\n",
        PR15A_V1_SHA256
    ));
    out.push_str("  \"oracle_gate\": \"PASS\",\n");
    out.push_str("  \"corpora\": [\n");
    for (index, corpus) in corpora.iter().enumerate() {
        out.push_str(&format!(
            "    {{\"label\": \"{}\", \"n\": {}, \"s\": {}, \"rows_sha256\": \"{}\", \
             \"corpus_sha256\": \"{}\", \"physical_segments\": {}, \"document_count\": {}}}{}\n",
            corpus.label,
            corpus.n,
            corpus.s,
            corpus.rows_sha256,
            corpus.corpus_sha256,
            corpus.physical_segments,
            corpus.document_count,
            if index + 1 == corpora.len() { "" } else { "," }
        ));
    }
    out.push_str("  ]\n}\n");
    out
}

/// Write the fixture metadata file when `QUERVANT_PR15B_METADATA` is set.
pub fn emit_fixture_metadata(corpora: &[CorpusMeta]) {
    let Ok(path) = std::env::var("QUERVANT_PR15B_METADATA") else {
        return;
    };
    let json = fixture_metadata_json(corpora);
    if let Some(parent) = std::path::Path::new(&path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).expect("create metadata directory");
        }
    }
    std::fs::write(&path, json).expect("write fixture metadata");
}
