//! PR 15A — provider-neutral and real-RustFS vertical for `pr15a_v1`.
//!
//! The non-ignored fake-provider test proves the complete query/sort/projection/
//! aggregation/batch/PIT surface against the static oracle and the exact
//! GET-only counter after warmup. The ignored real-RustFS test runs the same
//! semantic comparison through the production S3 adapter and uses
//! `TransferStats` for the warmed zero-GET boundary.

mod pr14_common;
mod pr15a_common;

use std::sync::Arc;

use pr14_common::registry;
use pr15a_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::query::{Bound, JsonPathExpr, Query};
use quervant_core::contract::result::{Cursor, Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, IpNetwork, Timestamp};
use quervant_core::index::{IndexLimits, PitHandle, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
    execute_batch_pinned,
};
use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

const NOW: i64 = 1_000;
const DEADLINE: i64 = 10_000;

fn policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16)
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

fn remote_fake() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

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
            "pr15a/{tag}/{}/{}/{}",
            std::process::id(),
            run_id(),
            "case"
        ))
        .expect("prefix"),
        std::env::temp_dir().join(format!(
            "quervant-pr15a-provider-{}-{tag}-{}",
            std::process::id(),
            run_id()
        )),
    )
    .with_transfer(RemoteTransferConfig::default())
}

fn backend_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

fn unified(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(
        snapshot,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(request, &Budgets::new(), &CancellationFlag::new())
    .expect("unified search")
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"))
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort_unstable();
    keys
}

fn alpha_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn cidr_query() -> Query {
    Query::IpInCidr {
        field: "ip".into(),
        network: IpNetwork::new("10.0.0.0".parse().expect("ipv4"), 24).expect("cidr"),
    }
}

fn time_query() -> Query {
    Query::TimeRange {
        field: "ts".into(),
        start: Timestamp::from_micros(2000),
        end: Timestamp::from_micros(5001),
    }
}

fn aggregation() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn aggregation_request() -> QueryRequest {
    let mut request = QueryRequest::new(Query::MatchAll);
    request.top_k = TopK::new(50).expect("top-k");
    request.aggregation = Some(aggregation());
    request
}

fn run_aggregation(snapshot: &ReaderSnapshot) -> SearchResponse {
    let response = execute_batch(
        snapshot,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![aggregation_request()], None, BatchBudget::new(4)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("aggregation batch");
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.clone(),
        other => panic!("aggregation slot failed: {other:?}"),
    }
}

fn group_counts(response: &SearchResponse) -> Vec<(String, u64, i128)> {
    response
        .aggregation
        .as_ref()
        .expect("aggregation")
        .groups
        .iter()
        .map(|group| {
            let host = match &group.components[0] {
                AggregationGroupValue::Value(FieldValue::Keyword(host)) => host.clone(),
                other => panic!("unexpected component {other:?}"),
            };
            let count = match group.metrics[0] {
                AggregationMetricValue::Count(count) => count,
                ref other => panic!("unexpected count {other:?}"),
            };
            let sum = match group.metrics[1] {
                AggregationMetricValue::Sum(
                    quervant_core::contract::aggregation::NumericAggregate::Signed(value),
                ) => value,
                ref other => panic!("unexpected sum {other:?}"),
            };
            (host, count, sum)
        })
        .collect()
}

fn pinned_batch(queries: Vec<QueryRequest>, pit: &PitHandle) -> BatchQueryRequest {
    BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(16))
}

fn pinned_page(
    pit: &PitHandle,
    cursor: Option<Cursor>,
    page_size: usize,
) -> (Vec<String>, Option<Cursor>) {
    let mut request = QueryRequest::new(Query::MatchAll);
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.top_k = TopK::new(page_size).expect("top-k");
    request.cursor = cursor;
    let response = execute_batch_pinned(
        pit,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
        &pinned_batch(vec![request], pit),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
        Timestamp::from_micros(NOW),
        Timestamp::from_micros(DEADLINE),
    )
    .expect("pinned batch");
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => (
            response
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect(),
            response.next_cursor.clone(),
        ),
        other => panic!("pinned slot failed: {other:?}"),
    }
}

fn pinned_pages(pit: &PitHandle, page_size: usize) -> Vec<String> {
    let mut cursor = None;
    let mut out = Vec::new();
    for _ in 0..100 {
        let (page, next) = pinned_page(pit, cursor, page_size);
        out.extend(page);
        cursor = next;
        if cursor.is_none() {
            return out;
        }
    }
    panic!("pagination did not terminate");
}

fn serial_batch(snapshot: &ReaderSnapshot) -> quervant_core::contract::batch::BatchQueryResponse {
    let mut alpha = QueryRequest::new(alpha_query());
    alpha.top_k = TopK::new(10).expect("top-k");
    let mut time = QueryRequest::new(time_query());
    time.top_k = TopK::new(10).expect("top-k");
    time.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    execute_batch(
        snapshot,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![alpha, time], None, BatchBudget::new(8)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("serial batch")
}

fn oracle_checks(snapshot: &ReaderSnapshot, label: &str) {
    let alpha = unified(snapshot, &request(alpha_query(), 10));
    assert_eq!(alpha.total_hits, 4, "{label}: alpha total");
    assert_eq!(keys(&alpha), vec!["a0", "a1", "b0", "b3"], "{label}: alpha");

    let mixed = unified(
        snapshot,
        &request(
            Query::And(vec![
                alpha_query(),
                Query::Range {
                    field: "n".into(),
                    lower: Bound::Included(FieldValue::I64(50)),
                    upper: Bound::Unbounded,
                },
            ]),
            10,
        ),
    );
    assert_eq!(keys(&mixed), vec!["b0", "b3"], "{label}: mixed");

    let cidr = unified(snapshot, &request(cidr_query(), 10));
    assert_eq!(keys(&cidr), vec!["a0", "a1", "b3"], "{label}: cidr");

    let time = unified(snapshot, &request(time_query(), 10));
    assert_eq!(keys(&time), vec!["a1", "a2", "a3", "b0"], "{label}: time");

    let json = unified(
        snapshot,
        &request(
            Query::JsonPathEquals {
                field: "body".into(),
                path: JsonPathExpr::parse("$.severity").expect("path"),
                value: FieldValue::I64(2),
            },
            10,
        ),
    );
    assert_eq!(keys(&json), vec!["a1", "b0"], "{label}: json");

    let mut projected = request(Query::MatchAll, 10);
    projected.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    projected.projection = Projection::Fields(vec!["host".into(), "n".into()]);
    let projected = unified(snapshot, &projected);
    assert_eq!(projected.hits.len(), 8, "{label}: projection count");
    let first = projected.hits.first().expect("first hit");
    assert_eq!(first.key.as_str(), "a0");
    assert_eq!(
        first
            .fields
            .iter()
            .find(|(name, _)| name == "host")
            .map(|(_, values)| values.clone()),
        Some(quervant_core::contract::document::FieldValues::Single(
            FieldValue::Keyword("h1".into())
        )),
        "{label}: projected host"
    );

    let aggregated = run_aggregation(snapshot);
    assert_eq!(aggregated.total_hits, 8, "{label}: aggregation total");
    assert_eq!(
        group_counts(&aggregated),
        vec![
            ("h1".to_owned(), 3, 90),
            ("h2".to_owned(), 3, 160),
            ("h3".to_owned(), 2, 110),
        ],
        "{label}: group counts"
    );

    let batch = serial_batch(snapshot);
    let alpha = match batch.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("{label}: serial alpha slot {other:?}"),
    };
    assert_eq!(alpha.total_hits, 4);
    let time = match batch.slot(1) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("{label}: serial time slot {other:?}"),
    };
    assert_eq!(
        time.hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>(),
        vec!["a1", "a2", "a3", "b0"]
    );
}

fn assert_projection_body(snapshot: &ReaderSnapshot, label: &str) {
    let response = unified(snapshot, &request(Query::MatchAll, 10));
    for hit in &response.hits {
        let record = row(hit.key.as_str());
        let body = hit
            .fields
            .iter()
            .find(|(name, _)| name == "body")
            .map(|(_, values)| values.clone());
        assert_eq!(
            body,
            Some(quervant_core::contract::document::FieldValues::Single(
                FieldValue::Json(pr15a_common::body(record))
            )),
            "{label}: stored JSON for {}",
            record.key
        );
    }
}

fn check_no_get(store: &FakeObjectStore, baseline: u64, family: &str) {
    let current = store.get_calls();
    assert_eq!(
        current, baseline,
        "{family}: warmed query advanced the GET-only counter"
    );
}

// ---------------------------------------------------------------------------
// A-R01/A-R02/A-R03 — deterministic fake provider, cold reopen, zero GET
// ---------------------------------------------------------------------------

#[test]
fn a15_r01_r02_r03_fake_provider_vertical_and_zero_get() {
    backend_on(async {
        let store = remote_fake();
        let config = remote_config("fake");
        let workspace = config.workspace_root().to_path_buf();
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            pr14_common::schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("remote create");
        for documents in [segment0_documents(), segment1_documents()] {
            let mut writer = index.writer().await.expect("writer");
            for document in documents {
                writer.insert(document).expect("insert");
            }
            writer.commit().await.expect("commit");
        }
        drop(index);
        let _ = std::fs::remove_dir_all(&workspace);

        let reader = RemoteIndex::open_existing(
            Arc::clone(&store),
            config.clone(),
            pr14_common::schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("cold reopen");
        assert_eq!(reader.generation(), Some(2));
        let snapshot = reader.snapshot();
        assert_eq!(snapshot.segment_count(), 2);

        let after_open = store.get_calls();
        assert!(
            after_open > 0,
            "positive control: cold hydration must issue GETs, observed {after_open}"
        );

        // Unwarmed first execution defines the semantic result and the warm
        // baseline. All families are compared with the static oracle.
        oracle_checks(&snapshot, "fake");
        assert_projection_body(&snapshot, "fake");
        let baseline = store.get_calls();

        // Warmed re-execution: identical results and zero additional GETs.
        oracle_checks(&snapshot, "fake-warm");
        assert_projection_body(&snapshot, "fake-warm");
        check_no_get(&store, baseline, "unified/aggregation/batch/projection");

        let pit = reader.pin().expect("remote pit");
        let pages = pinned_pages(&pit, 3);
        assert_eq!(pages, N_ASCENDING_KEYS);
        check_no_get(&store, baseline, "pinned pages");
        drop(pit);

        let _ = std::fs::remove_dir_all(&workspace);
    });
}

// ---------------------------------------------------------------------------
// A-R02 — real pinned RustFS provider vertical
// ---------------------------------------------------------------------------

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT required for real PR 15A");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET required for real PR 15A");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY required for real PR 15A");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY required for real PR 15A");
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
            .name("pr15a-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("runtime")
                    .block_on(body);
            })
            .expect("thread");
        handle.join().expect("real PR 15A test panicked");
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn a15_r02_real_rustfs_pr15a_vertical() {
        run(async {
            let (endpoint, bucket, access, secret, region) = env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .expect("S3 store"),
            );
            store.create_bucket_if_absent().await.expect("bucket");
            let config = remote_config("real");
            let workspace = config.workspace_root().to_path_buf();
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                pr14_common::schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("remote create");
            for documents in [segment0_documents(), segment1_documents()] {
                let mut writer = index.writer().await.expect("writer");
                for document in documents {
                    writer.insert(document).expect("insert");
                }
                writer.commit().await.expect("commit");
            }
            drop(index);
            let _ = std::fs::remove_dir_all(&workspace);

            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                pr14_common::schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("cold reopen");
            assert_eq!(reader.generation(), Some(2));
            let snapshot = reader.snapshot();
            assert_eq!(snapshot.segment_count(), 2);

            let stats = reader.transfer_stats();
            let after_open = stats.requests();
            assert!(
                after_open > 0,
                "real cold hydration must issue counted GETs, observed {after_open}"
            );
            assert_eq!(
                stats.whole_requests() + stats.range_requests(),
                2,
                "two committed immutable segments must be materialized once"
            );

            oracle_checks(&snapshot, "real");
            assert_projection_body(&snapshot, "real");
            let baseline = stats.requests();

            oracle_checks(&snapshot, "real-warm");
            assert_projection_body(&snapshot, "real-warm");
            assert_eq!(
                stats.requests(),
                baseline,
                "warmed unified/aggregation/batch/projection must issue zero counted GETs"
            );

            let pit = reader.pin().expect("remote pit");
            assert_eq!(pinned_pages(&pit, 2), N_ASCENDING_KEYS);
            assert_eq!(
                stats.requests(),
                baseline,
                "warmed pinned pages must issue zero counted GETs"
            );
            drop(pit);

            let _ = std::fs::remove_dir_all(&workspace);
        });
    }
}
