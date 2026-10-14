//! PR 10 T62–T64: real-boundary parity, corruption handling and a seeded oracle.

mod pr10_common;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, GroupValue, MetricValue, ModelIndex, Query,
    Sort, committed, full_doc, i64_range, match_all_request,
};
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::value::Timestamp;
use quervant_core::index::Index;
use quervant_core::search::SearchLimits;
use quervant_core::storage::{Directory, FsDirectory};

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn new(tag: &str) -> Self {
        let mut path = std::env::temp_dir();
        path.push(format!(
            "quervant-pr10-{tag}-{}-{}",
            std::process::id(),
            TEMP_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&path).expect("create temp dir");
        Self { path }
    }

    fn directory(&self) -> Arc<dyn Directory> {
        Arc::new(FsDirectory::open(&self.path).expect("open fs directory"))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn request(query: Query) -> pr10_common::TypedSearchRequest {
    let mut request = match_all_request(Sort::default(), 100);
    request.query = query;
    request
}

// T62 — MemoryDirectory and FsDirectory produce identical typed results.
#[test]
fn t62_memory_and_fs_parity() {
    let docs: Vec<Document> = (0..12)
        .map(|index| {
            full_doc(
                &format!("k{index:02}"),
                "t",
                index,
                index % 5,
                index as u64,
                1.0,
                true,
                ["a", "b", "c"][(index % 3) as usize],
                &["x", "y"],
                "10.0.0.1",
            )
        })
        .collect();
    let (_memory_dir, memory_index) = committed(docs.clone());

    let temp = TempDir::new("parity");
    let fs_directory = temp.directory();
    {
        let fs_index = pr10_common::create(Arc::clone(&fs_directory));
        let mut writer = fs_index.writer().unwrap();
        for document in docs {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let fs_index = pr10_common::reopen(fs_directory);

    let query = request(i64_range("n", Some(1), Some(3)));
    assert_eq!(
        pr10_common::hit_keys(&pr10_common::typed_search(&memory_index.snapshot(), &query)),
        pr10_common::hit_keys(&pr10_common::typed_search(&fs_index.snapshot(), &query))
    );

    let aggregate = AggregateRequest {
        query: Query::MatchAll,
        group_fields: vec!["host".into()],
        time_bucket: None,
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    };
    let memory_groups = pr10_common::aggregate(&memory_index.snapshot(), &aggregate);
    let fs_groups = pr10_common::aggregate(&fs_index.snapshot(), &aggregate);
    assert_eq!(memory_groups.groups, fs_groups.groups);
}

// T63 — a corrupt committed segment fails closed rather than returning partial data.
#[test]
fn t63_corruption_fails_closed() {
    let temp = TempDir::new("corrupt");
    let directory = temp.directory();
    {
        let index = pr10_common::create(Arc::clone(&directory));
        let mut writer = index.writer().unwrap();
        for offset in 0..8 {
            writer
                .insert(full_doc(
                    &format!("k{offset}"),
                    "t",
                    offset,
                    offset,
                    0,
                    1.0,
                    true,
                    "h",
                    &["x"],
                    "10.0.0.1",
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let segment = find_extension(&temp.path, "seg").expect("segment file");
    let mut bytes = std::fs::read(&segment).unwrap();
    let index = bytes.len() / 2;
    bytes[index] ^= 0xFF;
    std::fs::write(&segment, bytes).unwrap();

    let result = Index::open_existing(
        directory,
        pr10_common::pr10_schema(),
        pr10_common::registry(),
    );
    assert!(result.is_err(), "corrupt segment must not open");
}

fn find_extension(root: &Path, extension: &str) -> Option<PathBuf> {
    let entries = std::fs::read_dir(root).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            if let Some(found) = find_extension(&path, extension) {
                return Some(found);
            }
        } else if path.extension().and_then(|value| value.to_str()) == Some(extension) {
            return Some(path);
        }
    }
    None
}

struct Rng {
    state: u64,
}

impl Rng {
    fn new(seed: u64) -> Self {
        Self {
            // Avoid a zero state degenerating.
            state: seed ^ 0x9E37_79B9_7F4A_7C15,
        }
    }

    fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut x = self.state;
        x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        x ^ (x >> 31)
    }

    fn range(&mut self, low: i64, high: i64) -> i64 {
        let span = u64::try_from(high - low + 1).unwrap_or(1);
        low + (self.next() % span) as i64
    }
}

fn generated_document(key: &str, n: i64, ts: i64, host: &str) -> Document {
    let mut document = full_doc(key, "t", ts, n, 0, 1.0, true, host, &["x"], "10.0.0.1");
    document
        .insert(
            "nullable",
            if n % 3 == 0 {
                FieldValues::ExplicitNull
            } else {
                FieldValues::Single(FieldValue::I64(n * 2))
            },
        )
        .unwrap();
    document
}

// T64 — seeded randomized oracle over ranges, deletes and grouped counts.
#[test]
fn t64_seeded_oracle() {
    for seed in [0u64, 1, 0x5EED, 0xC0FFEE] {
        let mut rng = Rng::new(seed);
        let directory = pr10_common::memory();
        let index = pr10_common::create(Arc::clone(&directory));
        let mut writer = index.writer().unwrap();
        let mut model = ModelIndex::default();
        let mut revision = 0u64;

        for op in 0..250u64 {
            let key = format!("r{:02}", op % 30);
            revision += 1;
            let delete = rng.next() % 10 == 0;
            if delete {
                writer
                    .apply(MutationRequest::delete(DocumentKey::new(&key).unwrap()))
                    .unwrap();
                model.delete(revision, &key);
            } else {
                let n = rng.range(-20, 20);
                let ts = rng.range(-1000, 1000);
                let host = ["a", "b", "c", "d"][(rng.next() % 4) as usize];
                let document = generated_document(&key, n, ts, host);
                writer.apply(MutationRequest::upsert(document)).unwrap();
                model.put(
                    revision,
                    &key,
                    BTreeMap::from([
                        ("n".to_owned(), FieldValue::I64(n)),
                        (
                            "ts".to_owned(),
                            FieldValue::Timestamp(Timestamp::from_micros(ts)),
                        ),
                        ("host".to_owned(), FieldValue::Keyword(host.to_owned())),
                    ]),
                );
            }
        }
        writer.commit().unwrap();
        let reopened = pr10_common::reopen(directory);
        let snapshot = reopened.snapshot();

        // Range oracle.
        let lower = rng.range(-25, 25);
        let upper = lower + rng.range(0, 10);
        let query = i64_range("n", Some(lower), Some(upper));
        let response = pr10_common::typed_search(&snapshot, &request(query));
        let mut expected = model.live_with_i64_range("n", Some(lower), Some(upper));
        expected.sort();
        let mut actual = pr10_common::hit_keys(&response);
        actual.sort();
        assert_eq!(actual, expected, "seed {seed} range [{lower},{upper}]");

        // Pruning on/off must agree.
        let schema = pr10_common::pr10_schema();
        let cancel = quervant_core::analysis::CancellationFlag::new();
        let mut time_request = match_all_request(Sort::default(), 100);
        time_request.query = Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(-500),
            end: Timestamp::from_micros(500),
        };
        let searcher =
            quervant_core::search::TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
        let on = searcher
            .search(
                &time_request,
                &quervant_core::contract::budget::Budgets::new(),
                &cancel,
            )
            .unwrap();
        let off = searcher
            .with_pruning_disabled(true)
            .search(
                &time_request,
                &quervant_core::contract::budget::Budgets::new(),
                &cancel,
            )
            .unwrap();
        assert_eq!(
            pr10_common::hit_keys(&on),
            pr10_common::hit_keys(&off),
            "seed {seed} pruning differential"
        );

        // Grouped count oracle.
        let aggregate = AggregateRequest {
            query: Query::MatchAll,
            group_fields: vec!["host".into()],
            time_bucket: None,
            metrics: vec![AggregateMetric::Count],
            frequency_top_k: None,
            primary_time_field: Some("ts".into()),
        };
        let response = pr10_common::aggregate(&snapshot, &aggregate);
        let mut expected_counts: BTreeMap<String, u64> = BTreeMap::new();
        for document in model.docs.values().filter(|document| document.live) {
            if let Some(FieldValue::Keyword(host)) = document.values.get("host") {
                *expected_counts.entry(host.clone()).or_default() += 1;
            }
        }
        let mut actual_counts: BTreeMap<String, u64> = BTreeMap::new();
        for group in &response.groups {
            let host = match group.components.as_slice() {
                [GroupValue::Value(FieldValue::Keyword(host))] => host.clone(),
                other => panic!("unexpected group {other:?}"),
            };
            let count = match group.metrics.as_slice() {
                [MetricValue::Count(count)] => *count,
                other => panic!("unexpected metrics {other:?}"),
            };
            actual_counts.insert(host, count);
        }
        assert_eq!(actual_counts, expected_counts, "seed {seed} group counts");
    }
}

// ---- T43–T48: explicit resource limits and cancellation fail atomically. ----

use std::sync::atomic::AtomicUsize;

use quervant_core::contract::budget::{BudgetKind, Budgets};
use quervant_core::search::SearchError;

/// A canceller that reports cancellation after a fixed number of polls.
struct CancelAfter {
    calls: AtomicUsize,
    cancel_at: usize,
}

impl CancelAfter {
    fn new(cancel_at: usize) -> Self {
        Self {
            calls: AtomicUsize::new(0),
            cancel_at,
        }
    }
}

impl quervant_core::analysis::Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        call >= self.cancel_at
    }
}

fn five_docs() -> Vec<Document> {
    (0..5)
        .map(|index| {
            full_doc(
                &format!("d{index}"),
                "t",
                index,
                index,
                0,
                1.0,
                true,
                ["a", "b", "c", "d", "e"][index as usize],
                &["x"],
                "10.0.0.1",
            )
        })
        .collect()
}

fn run_search(
    snapshot: &quervant_core::index::ReaderSnapshot,
    limits: SearchLimits,
    cancel: &dyn quervant_core::analysis::Cancellation,
) -> Result<quervant_core::search::TypedSearchResponse, SearchError> {
    let schema = pr10_common::pr10_schema();
    let request = request(i64_range("n", Some(0), Some(100)));
    quervant_core::search::TypedSearcher::new(snapshot, &schema, limits).search(
        &request,
        &Budgets::new(),
        cancel,
    )
}

// T43 — the typed scan-document bound is exact and one-over fails.
#[test]
fn t43_scan_doc_bound() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let cancel = quervant_core::analysis::NeverCancel;

    let exact = SearchLimits::default().with_max_typed_scan_docs(5).unwrap();
    assert_eq!(run_search(&snapshot, exact, &cancel).unwrap().total_hits, 5);

    let one_over = SearchLimits::default().with_max_typed_scan_docs(4).unwrap();
    assert!(matches!(
        run_search(&snapshot, one_over, &cancel),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// T44 — the typed work-unit bound fails closed (no partial response).
#[test]
fn t44_work_unit_bound() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let cancel = quervant_core::analysis::NeverCancel;
    let limits = SearchLimits::default()
        .with_max_typed_work_units(2)
        .unwrap();
    assert!(matches!(
        run_search(&snapshot, limits, &cancel),
        Err(SearchError::ResourceLimit { .. })
    ));
}

fn count_by_host() -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: vec!["host".into()],
        time_bucket: None,
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

// T45 — the aggregate-group bound is exact and one-over fails.
#[test]
fn t45_aggregate_group_bound() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let request = count_by_host();

    let exact = SearchLimits::default()
        .with_max_aggregate_groups(5)
        .unwrap();
    assert_eq!(
        pr10_common::aggregate_with_limits(&snapshot, &request, exact, &Budgets::new())
            .unwrap()
            .groups
            .len(),
        5
    );

    let one_over = SearchLimits::default()
        .with_max_aggregate_groups(4)
        .unwrap();
    assert!(matches!(
        pr10_common::aggregate_with_limits(&snapshot, &request, one_over, &Budgets::new()),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// T46 — aggregate state bytes can also be lowered through `Budgets::MemoryBytes`.
#[test]
fn t46_aggregate_state_bytes() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let request = count_by_host();
    let budgets = Budgets::new().with(BudgetKind::MemoryBytes, 1).unwrap();
    assert!(matches!(
        pr10_common::aggregate_with_limits(&snapshot, &request, SearchLimits::default(), &budgets),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// T47 — cancellation is observed at entry, mid-scan and during aggregation.
#[test]
fn t47_cancellation() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let schema = pr10_common::pr10_schema();

    // Entry cancellation.
    let flag = quervant_core::analysis::CancellationFlag::new();
    flag.cancel();
    let searcher =
        quervant_core::search::TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
    let request = request(i64_range("n", Some(0), Some(100)));
    assert!(matches!(
        searcher.search(&request, &Budgets::new(), &flag),
        Err(SearchError::Cancelled)
    ));

    // Mid-scan cancellation.
    let cancel = CancelAfter::new(2);
    assert!(matches!(
        run_search(&snapshot, SearchLimits::default(), &cancel),
        Err(SearchError::Cancelled)
    ));

    // Aggregation cancellation.
    let flag = quervant_core::analysis::CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        searcher.aggregate(&count_by_host(), &Budgets::new(), &flag),
        Err(SearchError::Cancelled)
    ));
}

// T48 — an over-budget request returns no partial response.
#[test]
fn t48_no_partial_response() {
    let (_directory, index) = committed(five_docs());
    let snapshot = index.snapshot();
    let result = run_search(
        &snapshot,
        SearchLimits::default().with_max_typed_scan_docs(1).unwrap(),
        &quervant_core::analysis::NeverCancel,
    );
    assert!(result.is_err());
}
