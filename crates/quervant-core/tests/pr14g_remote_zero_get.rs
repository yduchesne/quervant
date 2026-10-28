//! PR 14G Phase A — remote query-time zero-GET boundary (CW-018/058/073).
//!
//! Architectural invariant A-01: `RemoteIndex::open_existing` and segment
//! materialization may issue object GETs, but every query executed afterwards —
//! typed-only, mixed lexical+typed, serial batch (typed, mixed, aggregation) and
//! pinned batch page 2 — must issue **zero additional remote GETs**.
//!
//! Every measured assertion is preceded by a positive control proving the
//! instrumented counter observes remote GETs at all (X08/X09), and every family
//! is compared against an equivalent local `Index` oracle so "no GET" can never
//! be established by doing no work (A-04).
//!
//! The shared PR 14 schema fixtures come from `pr14_common`; `fixture()`,
//! `typed_query()`, `mixed_query()`, `aggregation()`, `policy()` and
//! `batch_requests()` are the minimum fixture declarations copied from
//! `crates/quervant-core/tests/pr14_storage_vertical.rs` (the authoritative PR 14
//! compound vertical) with identical semantics. No search algorithm is ported.
//!
//! ```sh
//! cargo test -p quervant-core --test pr14g_remote_zero_get
//! QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
//! QUERVANT_RUSTFS_BUCKET=quervant-pr14g \
//! QUERVANT_RUSTFS_ACCESS_KEY=... QUERVANT_RUSTFS_SECRET_KEY=... \
//! cargo test -p quervant-core --all-features --test pr14g_remote_zero_get \
//!   a02_real_rustfs_zero_get_after_warmup -- --ignored --exact --nocapture
//! ```

mod pr14_common;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{Aggregate, Aggregation, GroupBy, GroupKey};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, FieldValues, MutationRequest};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexLimits, PitHandle, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
    execute_batch_pinned,
};
use quervant_core::storage::{Directory, MemoryDirectory};
use quervant_objectstore::{
    FakeObjectStore, ObjectStore, ObjectStoreCapabilities, ObjectStoreError, TransferLimits,
};

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_workspace(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-pr14g-{}-{name}-{n}", std::process::id()))
}

/// A per-process run identifier so repeated runs against a persistent RustFS
/// instance never reuse prefixes.
fn run_id() -> u128 {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn remote_config(tag: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "pr14g/{tag}/{}/{}/{}",
            std::process::id(),
            run_id(),
            "case"
        ))
        .unwrap(),
        temp_workspace(tag),
    )
    .with_transfer(
        RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024)
            .with_chunk_size(32 * 1024)
            .with_max_aggregate_response_bytes(2 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16),
    )
}

/// The same deterministic immutable/conditional fake used by
/// `pr13_remote::remote_fake`, whose `get_calls` is an exact GET-only counter.
fn remote_fake() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

fn json(values: &[(&str, i64)]) -> JsonValue {
    JsonValue::Object(
        values
            .iter()
            .map(|(key, value)| {
                (
                    (*key).to_owned(),
                    JsonValue::Number(JsonNumber::I64(*value)),
                )
            })
            .collect(),
    )
}

/// Deterministic six-document corpus, copied verbatim from
/// `pr14_storage_vertical::fixture()` so the local and remote oracles share the
/// authoritative PR 14 fixture.
fn fixture() -> Vec<Document> {
    let mut out = Vec::new();
    let rows = [
        (
            "d0",
            "alpha beta",
            "h1",
            10i64,
            0i64,
            0.0f64,
            0.0,
            "192.0.2.1",
        ),
        ("d1", "alpha", "h1", 20, 60_000_000, 0.1, 0.1, "192.0.2.2"),
        ("d2", "beta", "h2", 30, -1, 50.0, 50.0, "2001:db8::1"),
        (
            "d3",
            "alpha beta",
            "h2",
            40,
            120_000_000,
            0.2,
            0.2,
            "192.0.2.1",
        ),
        (
            "d4",
            "gamma",
            "h3",
            50,
            180_000_000,
            60.0,
            60.0,
            "2001:db8::2",
        ),
        ("d5", "alpha", "h1", 60, 240_000_000, 0.3, 0.3, "192.0.2.2"),
    ];
    for (key, title, host, n, ts, lon, lat, ip) in rows {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text(title.into()));
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(ts)),
        );
        set(
            &mut document,
            "body",
            FieldValue::Json(json(&[("n", n), ("k", n * 2)])),
        );
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap()),
        );
        set(&mut document, "ip", FieldValue::Ip(ip.parse().unwrap()));
        out.push(document);
    }
    set_null(&mut out[1], "nullable");
    set_multi(&mut out[5], "tags", vec![FieldValue::Keyword("x".into())]);
    set_multi(
        &mut out[2],
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2)],
    );
    out[4].insert("mn", FieldValues::Empty).unwrap();
    out
}

/// Typed-only family: JSON, IP, geo and range predicates with no lexical leaf.
fn typed_query() -> Query {
    Query::And(vec![
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("192.0.2.0".parse().unwrap(), 24).unwrap(),
        },
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
        },
        Query::JsonPathRange {
            field: "body".into(),
            path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
    ])
}

/// Mixed lexical+typed family, copied from `pr14_storage_vertical::mixed_query`.
fn mixed_query() -> Query {
    Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
        Query::And(vec![
            Query::JsonPathRange {
                field: "body".into(),
                path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
                lower: Bound::Included(FieldValue::I64(1)),
                upper: Bound::Included(FieldValue::I64(100)),
            },
            Query::GeoBoundingBox {
                field: "loc".into(),
                bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
            },
        ]),
    ])
}

/// Aggregation fixture, copied from `pr14_storage_vertical::aggregation`.
fn aggregation() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn batch_policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 8)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 30)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

/// Three-slot serial batch: typed-only, mixed, and mixed plus aggregation.
fn batch_requests() -> Vec<QueryRequest> {
    let mut typed = QueryRequest::new(typed_query());
    typed.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    typed.top_k = TopK::new(2).unwrap();
    let mut mixed = QueryRequest::new(mixed_query());
    mixed.top_k = TopK::new(10).unwrap();
    let mut aggregated = QueryRequest::new(mixed_query());
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(aggregation());
    vec![typed, mixed, aggregated]
}

fn run_batch(snapshot: &ReaderSnapshot) -> quervant_core::contract::batch::BatchQueryResponse {
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(batch_requests(), None, BatchBudget::new(8)),
        &batch_policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap()
}

fn unified_run(
    snapshot: &ReaderSnapshot,
    query: Query,
    top_k: usize,
    sort: Sort,
) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(
            &UnifiedRequest {
                query,
                sort,
                top_k: TopK::new(top_k).unwrap(),
                projection: Projection::Source,
                after: None,
            },
            &Budgets::new(),
            &CancellationFlag::new(),
        )
        .unwrap()
}

fn run_typed(snapshot: &ReaderSnapshot) -> UnifiedResponse {
    unified_run(
        snapshot,
        typed_query(),
        10,
        Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
    )
}

fn run_mixed(snapshot: &ReaderSnapshot) -> UnifiedResponse {
    unified_run(snapshot, mixed_query(), 10, Sort::default())
}

fn success_of(
    response: &quervant_core::contract::batch::BatchQueryResponse,
    slot: usize,
) -> &SearchResponse {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("slot {slot} was not successful: {other:?}"),
    }
}

fn keys_of(response: &SearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn pinned_run(
    pit: &PitHandle,
    queries: Vec<QueryRequest>,
    now: i64,
    deadline: i64,
) -> Result<quervant_core::contract::batch::BatchQueryResponse, SearchError> {
    execute_batch_pinned(
        pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(8)),
        &batch_policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
        Timestamp::from_micros(now),
        Timestamp::from_micros(deadline),
    )
}

/// The complete pinned page chain observed on one immutable generation, kept
/// explicit so the local and remote oracles are compared field by field.
#[derive(Debug, Clone, PartialEq)]
struct PinnedChain {
    pages: Vec<Vec<String>>,
    totals: Vec<u64>,
    aggregations: Vec<Option<quervant_core::contract::aggregation::AggregationResult>>,
}

/// Execute every page of one pinned query, following `next_cursor` on the same
/// frozen generation until the continuation is exhausted.
fn pinned_page_chain(pit: &PitHandle, page_size: usize) -> PinnedChain {
    let mut request = QueryRequest::new(mixed_query());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.top_k = TopK::new(page_size).unwrap();
    request.projection = Projection::Source;
    request.aggregation = Some(aggregation());
    let mut chain = PinnedChain {
        pages: Vec::new(),
        totals: Vec::new(),
        aggregations: Vec::new(),
    };
    let mut cursor = None;
    for _ in 0..32 {
        let mut page_request = request.clone();
        page_request.cursor = cursor;
        let response = pinned_run(pit, vec![page_request], 1_000, 10_000).unwrap();
        let page = success_of(&response, 0);
        chain.pages.push(keys_of(page));
        chain.totals.push(page.total_hits);
        chain.aggregations.push(page.aggregation.clone());
        cursor = page.next_cursor.clone();
        if cursor.is_none() {
            break;
        }
    }
    assert!(cursor.is_none(), "pinned pagination must terminate");
    chain
}

/// The `page_size = 2` chain; page-2 execution on the same immutable pin.
fn pinned_pages(pit: &PitHandle, page_size: usize) -> PinnedChain {
    let chain = pinned_page_chain(pit, page_size);
    assert_eq!(
        chain.pages.len(),
        4usize.div_ceil(page_size),
        "page count for page_size={page_size}"
    );
    chain
}

fn assert_unified_equal(local: &UnifiedResponse, remote: &UnifiedResponse, family: &str) {
    assert_eq!(local.total_hits, remote.total_hits, "{family}: total hits");
    assert_eq!(local.hits.len(), remote.hits.len(), "{family}: page length");
    for (left, right) in local.hits.iter().zip(&remote.hits) {
        assert_eq!(left.key, right.key, "{family}: key");
        assert_eq!(left.fields, right.fields, "{family}: projected fields");
        assert_eq!(left.score, right.score, "{family}: score");
    }
    assert_eq!(
        local.aggregation, remote.aggregation,
        "{family}: aggregation"
    );
}

fn assert_batch_equal(
    local: &quervant_core::contract::batch::BatchQueryResponse,
    remote: &quervant_core::contract::batch::BatchQueryResponse,
) {
    assert_eq!(local.len(), remote.len());
    for index in 0..local.len() {
        match (local.slot(index), remote.slot(index)) {
            (Some(PerQueryOutcome::Success(a)), Some(PerQueryOutcome::Success(b))) => {
                assert_eq!(a.total_hits, b.total_hits, "slot {index}: total hits");
                assert_eq!(a.aggregation, b.aggregation, "slot {index}: aggregation");
                assert_eq!(a.hits.len(), b.hits.len(), "slot {index}: page length");
                for (hit_a, hit_b) in a.hits.iter().zip(&b.hits) {
                    assert_eq!(hit_a.key, hit_b.key, "slot {index}: key");
                    assert_eq!(hit_a.fields, hit_b.fields, "slot {index}: fields");
                    assert_eq!(hit_a.score, hit_b.score, "slot {index}: score");
                }
            }
            (Some(PerQueryOutcome::Failure(a)), Some(PerQueryOutcome::Failure(b))) => {
                assert_eq!(a, b, "slot {index}: failure");
            }
            (a, b) => panic!("outcome mismatch at slot {index}: {a:?} vs {b:?}"),
        }
    }
}

/// A commit-split local `Index` oracle: `segments` explicit immutable commits
/// followed by a reopen, matching the remote writer's commit stream.
fn local_index(docs: &[Document], segments: usize) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = pr14_common::create(Arc::clone(&directory));
    for chunk in docs.chunks(docs.len().div_ceil(segments)) {
        let mut writer = index.writer().unwrap();
        for document in chunk {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    drop(index);
    let reopened = pr14_common::reopen(directory);
    assert_eq!(
        reopened.snapshot().segment_count(),
        segments,
        "local oracle must have exactly {segments} immutable segments"
    );
    reopened
}

/// Publish `docs` in `segments` explicit remote commits.
fn publish_segments(index: &RemoteIndex<FakeObjectStore>, docs: &[Document], segments: usize) {
    for chunk in docs.chunks(docs.len().div_ceil(segments)) {
        let mut writer = block_on(index.writer()).unwrap();
        for document in chunk {
            writer.insert(document.clone()).unwrap();
        }
        block_on(writer.commit()).unwrap();
    }
}

fn load_remote(
    store: &Arc<FakeObjectStore>,
    config: &RemoteConfig,
) -> RemoteIndex<FakeObjectStore> {
    block_on(RemoteIndex::open_existing(
        Arc::clone(store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap()
}

/// GET-only invariant checker. A warmed query must not advance the fake store's
/// exact `get_calls` counter past the recorded baseline.
fn check_no_get(store: &FakeObjectStore, baseline: u64, family: &str) -> Result<u64, String> {
    let current = store.get_calls();
    if current == baseline {
        Ok(current)
    } else {
        Err(format!(
            "{family}: remote GET counter advanced from {baseline} to {current} after a warmed query"
        ))
    }
}

fn require_no_get(store: &FakeObjectStore, baseline: u64, family: &str) {
    if let Err(detail) = check_no_get(store, baseline, family) {
        panic!("{detail}");
    }
}

fn trace(family: &str, before: u64, after: u64) {
    eprintln!("[pr14g][zero-get] family={family} get_before={before} get_after={after}");
}

/// A01/A02/A03/A04/A05/A07 — the mandatory non-ignored FakeObjectStore test.
///
/// Cold-opens a real committed remote generation with an empty local workspace,
/// proves the GET counter observes hydration (positive control), compares every
/// workload family against an equivalent local `Index`, then asserts exactly
/// zero additional GETs for one warmed re-execution of each family.
#[test]
fn a01_fake_remote_zero_get_after_warmup() {
    let store = remote_fake();
    let config = remote_config("a01");
    let workspace = config.workspace_root().to_path_buf();
    let create = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    publish_segments(&create, &fixture(), 3);
    // Drop every create-time reader/writer handle and all disposable local state.
    drop(create);
    std::fs::remove_dir_all(&workspace).unwrap();

    let before_open = store.get_calls();
    let reader = load_remote(&store, &config);
    let after_open = store.get_calls();
    assert!(
        after_open > before_open,
        "positive control: cold open must issue remote GETs (before {before_open}, after {after_open})"
    );
    assert_eq!(reader.generation(), Some(3));
    let remote = reader.snapshot();
    assert_eq!(remote.segment_count(), 3);

    let local = local_index(&fixture(), 3);
    let local_snapshot = local.snapshot();

    // A-04 family (i): typed-only JSON/IP/geo/range predicate.
    let local_typed = run_typed(&local_snapshot);
    let remote_typed = run_typed(&remote);
    assert_unified_equal(&local_typed, &remote_typed, "typed-only");
    assert_eq!(local_typed.total_hits, 4);
    let typed_order: Vec<&str> = local_typed
        .hits
        .iter()
        .map(|hit| hit.key.as_str())
        .collect();
    assert_eq!(
        typed_order,
        vec!["d5", "d3", "d1", "d0"],
        "typed-only results must follow the explicit n-descending sort"
    );

    // A-04 family (ii): mixed lexical+typed predicate.
    let local_mixed = run_mixed(&local_snapshot);
    let remote_mixed = run_mixed(&remote);
    assert_unified_equal(&local_mixed, &remote_mixed, "mixed");
    assert_eq!(local_mixed.total_hits, 4);
    let mixed_keys: Vec<&str> = local_mixed
        .hits
        .iter()
        .map(|hit| hit.key.as_str())
        .collect();
    let mut sorted = mixed_keys.clone();
    sorted.sort_unstable();
    assert_eq!(sorted, vec!["d0", "d1", "d3", "d5"]);

    // A-04 family (iii): three-slot serial batch over typed, mixed, aggregation.
    let local_batch = run_batch(&local_snapshot);
    let remote_batch = run_batch(&remote);
    assert_batch_equal(&local_batch, &remote_batch);
    assert_eq!(success_of(&local_batch, 0).total_hits, 4);
    assert_eq!(keys_of(success_of(&local_batch, 0)), vec!["d5", "d3"]);
    assert_eq!(success_of(&local_batch, 1).total_hits, 4);
    let aggregated = success_of(&local_batch, 2);
    assert_eq!(aggregated.total_hits, 4);
    let groups = aggregated.aggregation.as_ref().expect("aggregation result");
    assert_eq!(groups.groups.len(), 2, "h1 and h2 only");

    // A-04 family (iv): pinned batch page 1 → page 2 on one immutable pin.
    let local_pin = local.pin().unwrap();
    let remote_pin = reader.pin().unwrap();
    let local_pages = pinned_pages(&local_pin, 2);
    let remote_pages = pinned_pages(&remote_pin, 2);
    assert_eq!(
        local_pages, remote_pages,
        "pinned page 1/2 must match the local oracle"
    );
    assert_eq!(
        local_pages.pages,
        vec![
            vec!["d0".to_owned(), "d1".to_owned()],
            vec!["d3".to_owned(), "d5".to_owned()]
        ]
    );
    assert_eq!(local_pages.totals, vec![4, 4]);
    assert_eq!(
        local_pages.aggregations[0], local_pages.aggregations[1],
        "the pinned aggregation is identical on both pages"
    );
    drop(remote_pin);

    // One full warmup of every family, then the measured baseline.
    let baseline = store.get_calls();
    trace("baseline", before_open, baseline);

    let typed_again = run_typed(&remote);
    assert_eq!(typed_again, remote_typed, "warm typed rerun is identical");
    assert_eq!(check_no_get(&store, baseline, "typed-only"), Ok(baseline));
    trace("typed-only", baseline, store.get_calls());

    let mixed_again = run_mixed(&remote);
    assert_eq!(mixed_again, remote_mixed, "warm mixed rerun is identical");
    require_no_get(&store, baseline, "mixed");
    trace("mixed", baseline, store.get_calls());

    let batch_again = run_batch(&remote);
    assert_batch_equal(&batch_again, &remote_batch);
    require_no_get(&store, baseline, "serial-batch");
    trace("serial-batch", baseline, store.get_calls());

    let pinned_again = pinned_pages(&reader.pin().unwrap(), 2);
    assert_eq!(pinned_again, remote_pages, "warm pinned rerun is identical");
    require_no_get(&store, baseline, "pinned-page-2");
    trace("pinned-page-2", baseline, store.get_calls());

    assert_eq!(
        store.get_calls(),
        baseline,
        "warmed typed/mixed/batch/pinned execution must issue zero additional GETs"
    );
    let _ = std::fs::remove_dir_all(&workspace);
}

/// A03 — the counter positive control must fail a stuck-at-zero instrumentation.
///
/// A fresh cold open of committed remote state with an empty local workspace
/// must strictly increase the exact GET counter.
#[test]
fn a03_positive_control_detects_remote_get() {
    let store = remote_fake();
    let config = remote_config("a03");
    let workspace = config.workspace_root().to_path_buf();
    let create = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    publish_segments(&create, &fixture(), 3);
    drop(create);
    std::fs::remove_dir_all(&workspace).unwrap();

    let before = store.get_calls();
    let reader = load_remote(&store, &config);
    let after = store.get_calls();
    assert!(
        after > before,
        "instrumentation must count remote GETs during cold materialization (before {before}, after {after})"
    );
    assert!(
        after - before >= 3,
        "three committed segments plus committed metadata must be fetched from the provider (delta {})",
        after - before
    );
    // Reads of already-resident committed state remain zero-GET.
    let baseline = store.get_calls();
    let _ = run_mixed(&reader.snapshot());
    require_no_get(&store, baseline, "a03-warm-mixed");
    let _ = std::fs::remove_dir_all(&workspace);
}

/// A06 — a test-only injected GET between the baseline and the assertion must be
/// rejected by the invariant checker. No production search path is touched.
#[test]
fn a04_counter_boundary_rejects_query_get() {
    let store = remote_fake();
    let config = remote_config("a04");
    let workspace = config.workspace_root().to_path_buf();
    let create = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    publish_segments(&create, &fixture(), 3);
    drop(create);
    std::fs::remove_dir_all(&workspace).unwrap();

    let before_open = store.get_calls();
    let reader = load_remote(&store, &config);
    assert!(store.get_calls() > before_open, "positive control");

    let _ = run_mixed(&reader.snapshot());
    let baseline = store.get_calls();
    assert_eq!(check_no_get(&store, baseline, "clean"), Ok(baseline));

    // A deliberate, test-only provider GET outside any production search path.
    let injected = config
        .prefix()
        .object_key("pr14g-injected-get")
        .expect("physical key");
    let limits = TransferLimits::new(64);
    let error = block_on(store.get(&injected, None, &limits)).unwrap_err();
    assert!(matches!(error, ObjectStoreError::NotFound { .. }));
    assert_eq!(store.get_calls(), baseline + 1, "injected GET is counted");

    let rejected = check_no_get(&store, baseline, "injected");
    assert!(
        rejected.is_err(),
        "a nonzero GET delta must be rejected, got {rejected:?}"
    );
    assert!(
        rejected
            .expect_err("injected GET must fail the invariant")
            .contains("advanced")
    );
    let _ = std::fs::remove_dir_all(&workspace);
}

/// A05 — independent local-vs-remote parity and pinned cursor page separation on
/// the same immutable generation, across page sizes.
#[test]
fn a05_batch_and_cursor_oracle() {
    let store = remote_fake();
    let config = remote_config("a05");
    let workspace = config.workspace_root().to_path_buf();
    let create = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    publish_segments(&create, &fixture(), 3);
    drop(create);
    std::fs::remove_dir_all(&workspace).unwrap();

    let before_open = store.get_calls();
    let reader = load_remote(&store, &config);
    assert!(
        store.get_calls() > before_open,
        "positive control before parity assertions"
    );
    let remote = reader.snapshot();
    let local = local_index(&fixture(), 3);
    let local_snapshot = local.snapshot();

    // Batch parity: every slot matches the local oracle exactly.
    let local_batch = run_batch(&local_snapshot);
    let remote_batch = run_batch(&remote);
    assert_batch_equal(&local_batch, &remote_batch);

    let local_pin = local.pin().unwrap();
    let remote_pin = reader.pin().unwrap();
    for page_size in [1usize, 2, 3, 4] {
        let local_pages = pinned_pages(&local_pin, page_size);
        let remote_pages = pinned_pages(&remote_pin, page_size);
        assert_eq!(local_pages, remote_pages, "page_size={page_size}");
        assert!(
            local_pages.totals.iter().all(|total| *total == 4),
            "page_size={page_size}: every page reports the exact match total"
        );
        let observed = local_pages.pages.concat();
        let mut union = observed.clone();
        union.sort_unstable();
        union.dedup();
        assert_eq!(
            union,
            vec!["d0", "d1", "d3", "d5"],
            "page_size={page_size}: pages must cover the mixed match set"
        );
        assert_eq!(
            observed.len(),
            union.len(),
            "page_size={page_size}: pages must not overlap"
        );
        assert_eq!(
            local_pages.pages[0].len(),
            page_size.min(4),
            "page_size={page_size}: page 1 size"
        );
        let final_page = local_pages.aggregations.len() - 1;
        assert_eq!(
            local_pages.aggregations[0], local_pages.aggregations[final_page],
            "page_size={page_size}: aggregation is page-invariant"
        );

        // Repeated page execution on the same immutable pin is zero-GET.
        let baseline = store.get_calls();
        let _ = pinned_pages(&remote_pin, page_size);
        require_no_get(&store, baseline, "a05-pinned-pages");
    }
    drop(remote_pin);
    let _ = std::fs::remove_dir_all(&workspace);
}

/// A07 — an old pinned generation and a newly opened committed generation must
/// never be confused, and neither may lazily re-fetch from the provider once
/// warmed.
#[test]
fn a06_wrong_generation_guard() {
    let store = remote_fake();
    let old_config = remote_config("a06-old");
    let old_workspace = old_config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        old_config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    publish_segments(&index, &fixture(), 3);

    // A new reader of the committed generation, with its own disposable cache.
    std::fs::remove_dir_all(&old_workspace).unwrap();
    let before_open = store.get_calls();
    let old_reader = load_remote(&store, &old_config);
    assert!(store.get_calls() > before_open, "positive control");
    assert_eq!(old_reader.generation(), Some(3));
    let old_pit = old_reader.pin().unwrap();
    let old_snapshot = old_pit.snapshot();
    let old_delta = unified_run(
        old_snapshot,
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("delta".into()),
        },
        10,
        Sort::default(),
    );
    assert_eq!(old_delta.total_hits, 0, "old generation has no delta");
    let old_pages = pinned_pages(&old_pit, 2);

    // Real upsert of a stable key plus a commit, through the cooperating writer.
    {
        let mut writer = block_on(index.writer()).unwrap();
        let mut updated = fixture()[0].clone();
        set(&mut updated, "host", FieldValue::Keyword("h9".into()));
        set(&mut updated, "title", FieldValue::Text("delta".into()));
        writer
            .apply(MutationRequest::upsert(updated))
            .expect("upsert");
        block_on(writer.commit()).unwrap();
    }

    let new_config = RemoteConfig::new(old_config.prefix().clone(), temp_workspace("a06-new"))
        .with_transfer(*old_config.transfer());
    let new_workspace = new_config.workspace_root().to_path_buf();
    let before_new = store.get_calls();
    let new_reader = load_remote(&store, &new_config);
    assert!(
        store.get_calls() > before_new,
        "new generation open is a real remote materialization"
    );
    assert!(
        new_reader.generation() > old_reader.generation(),
        "new reader must observe the newer committed generation"
    );

    // The old pin is unchanged; the new reader sees the mutation.
    let old_after = unified_run(
        old_snapshot,
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("delta".into()),
        },
        10,
        Sort::default(),
    );
    assert_eq!(old_after.total_hits, 0, "old pin still excludes delta");
    assert_eq!(
        pinned_pages(&old_pit, 2),
        old_pages,
        "old pinned generation is stable across the mutation"
    );
    let new_delta = unified_run(
        new_reader.snapshot().as_ref(),
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("delta".into()),
        },
        10,
        Sort::default(),
    );
    assert_eq!(new_delta.total_hits, 1);
    assert_eq!(new_delta.hits[0].key.as_str(), "d0");
    let host_field = new_delta.hits[0]
        .fields
        .iter()
        .find(|(name, _)| name == "host")
        .expect("host is stored");
    assert_eq!(
        host_field.1,
        FieldValues::Single(FieldValue::Keyword("h9".into())),
        "new reader projects the mutated stored value"
    );
    let new_pin = new_reader.pin().unwrap();
    assert_ne!(
        pinned_pages(&new_pin, 2),
        old_pages,
        "the new pinned generation must not reuse the old snapshot"
    );

    // Warmed old-pin and new-reader execution stays zero-GET.
    let baseline = store.get_calls();
    let _ = unified_run(old_snapshot, mixed_query(), 10, Sort::default());
    let _ = pinned_pages(&old_pit, 2);
    let _ = run_batch(new_reader.snapshot().as_ref());
    let _ = unified_run(
        new_reader.snapshot().as_ref(),
        mixed_query(),
        10,
        Sort::default(),
    );
    require_no_get(&store, baseline, "a06-old-and-new-generations");

    drop(new_pin);
    drop(old_pit);
    let _ = std::fs::remove_dir_all(&old_workspace);
    let _ = std::fs::remove_dir_all(&new_workspace);
}

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT required for real PR 14G acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET required for real PR 14G acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY required for real PR 14G acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY required for real PR 14G acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        for (name, value) in [
            ("endpoint", &endpoint),
            ("bucket", &bucket),
            ("access", &access),
            ("secret", &secret),
        ] {
            assert!(!value.trim().is_empty(), "{name} must not be empty");
        }
        assert!(endpoint.starts_with("http://"));
        (endpoint, bucket, access, secret, region)
    }

    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("pr14g-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .unwrap()
                    .block_on(body);
            })
            .unwrap();
        handle.join().expect("real PR 14G test panicked");
    }

    async fn remote_index(
        tag: &str,
    ) -> (Arc<S3ObjectStore>, RemoteConfig, RemoteIndex<S3ObjectStore>) {
        let (endpoint, bucket, access, secret, region) = env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret)).unwrap(),
        );
        store.create_bucket_if_absent().await.unwrap();
        let config = remote_config(tag);
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .unwrap();
        (store, config, index)
    }

    async fn publish_remote_segments(
        index: &RemoteIndex<S3ObjectStore>,
        docs: &[Document],
        segments: usize,
    ) {
        for chunk in docs.chunks(docs.len().div_ceil(segments)) {
            let mut writer = index.writer().await.unwrap();
            for document in chunk {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
    }

    /// A02 — real pinned RustFS GET-only zero-GET boundary.
    ///
    /// `TransferStats::requests()` is source-verified as a GET-only counter: it
    /// is incremented exactly once per `ObjectStore::get` attempt in
    /// `remote/transfer.rs::get_with_retry`, and HEAD/PUT/LIST never touch it.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn a02_real_rustfs_zero_get_after_warmup() {
        run(async {
            let (store, config, index) = remote_index("a02").await;
            let workspace = config.workspace_root().to_path_buf();
            publish_remote_segments(&index, &fixture(), 3).await;
            drop(index);
            std::fs::remove_dir_all(&workspace).unwrap();

            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let stats = reader.transfer_stats();
            // The stats instance is created inside `open_existing` (initialized to
            // zero), so a positive value here is the cold segment-materialization
            // GET count. `requests()` is incremented exactly once per budgeted
            // `ObjectStore::get` attempt in `remote/transfer.rs::get_with_retry`, so
            // it is a GET-only counter (never HEAD/PUT/LIST); the direct metadata
            // GETs in `fetch_verified` bypass the transfer budget and are not
            // counted, which is documented in the Phase A evidence.
            let after_open = stats.requests();
            assert!(
                after_open > 0,
                "positive control: real cold hydration must issue GETs, observed {after_open}"
            );
            assert_eq!(
                stats.whole_requests() + stats.range_requests(),
                3,
                "three committed immutable segments must be materialized exactly once"
            );
            assert!(
                after_open >= 3,
                "retries may only increase the total beyond the classified fetch attempts, observed {after_open}"
            );
            assert_eq!(reader.generation(), Some(3));
            let remote = reader.snapshot();
            assert_eq!(remote.segment_count(), 3);

            let local = local_index(&fixture(), 3);
            let local_snapshot = local.snapshot();

            let local_typed = run_typed(&local_snapshot);
            let remote_typed = run_typed(&remote);
            assert_unified_equal(&local_typed, &remote_typed, "real typed-only");
            let local_mixed = run_mixed(&local_snapshot);
            let remote_mixed = run_mixed(&remote);
            assert_unified_equal(&local_mixed, &remote_mixed, "real mixed");
            let local_batch = run_batch(&local_snapshot);
            let remote_batch = run_batch(&remote);
            assert_batch_equal(&local_batch, &remote_batch);
            let local_pin = local.pin().unwrap();
            let remote_pin = reader.pin().unwrap();
            let local_pages = pinned_pages(&local_pin, 2);
            let remote_pages = pinned_pages(&remote_pin, 2);
            assert_eq!(local_pages, remote_pages, "real pinned pages");
            assert_eq!(
                local_pages.pages,
                vec![
                    vec!["d0".to_owned(), "d1".to_owned()],
                    vec!["d3".to_owned(), "d5".to_owned()]
                ]
            );
            drop(remote_pin);

            let baseline = stats.requests();
            eprintln!(
                "[pr14g][a02] baseline GETs after hydration+warmup={baseline} (cold open {after_open})"
            );

            let typed_again = run_typed(&remote);
            assert_eq!(typed_again, remote_typed);
            assert_eq!(
                stats.requests(),
                baseline,
                "typed-only query must issue zero GETs"
            );
            eprintln!("[pr14g][a02] typed-only after={}", stats.requests());

            let mixed_again = run_mixed(&remote);
            assert_eq!(mixed_again, remote_mixed);
            assert_eq!(
                stats.requests(),
                baseline,
                "mixed query must issue zero GETs"
            );
            eprintln!("[pr14g][a02] mixed after={}", stats.requests());

            let batch_again = run_batch(&remote);
            assert_batch_equal(&batch_again, &remote_batch);
            assert_eq!(
                stats.requests(),
                baseline,
                "serial batch must issue zero GETs"
            );
            eprintln!("[pr14g][a02] serial-batch after={}", stats.requests());

            let pinned_again = pinned_pages(&reader.pin().unwrap(), 2);
            assert_eq!(pinned_again, remote_pages);
            assert_eq!(
                stats.requests(),
                baseline,
                "pinned page 1->2 must issue zero GETs"
            );
            eprintln!("[pr14g][a02] pinned-page-2 after={}", stats.requests());

            let _ = std::fs::remove_dir_all(&workspace);
        });
    }
}
