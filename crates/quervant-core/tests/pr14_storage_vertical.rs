//! PR 14 P4 — real RustFS compound vertical (R01–R08, R12, R15).
//!
//! Local `FsDirectory` and real RustFS snapshots are queried through the same
//! PR 14 `UnifiedSearcher`/`execute_batch` entry points and compared with an
//! independent, hand-enumerated fixture oracle. Real-provider tests are
//! `#[ignore]`d and fail closed when the documented environment is missing.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
    SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{PitId, Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
};
use quervant_core::storage::{Directory, FsDirectory};

fn p4_dir(tag: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr14-p4-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
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

/// Deterministic `pr14-p4-v1` fixture. Each tuple is one logical document.
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
    // Extra five-state / multivalue cases.
    set_null(&mut out[1], "nullable");
    set_multi(&mut out[5], "tags", vec![FieldValue::Keyword("x".into())]);
    set_multi(
        &mut out[2],
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2)],
    );
    out
}

fn build_local(tag: &str) -> (std::path::PathBuf, Index) {
    let path = p4_dir(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    let docs = fixture();
    // Two explicit immutable segments.
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().take(3) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().skip(3) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    (path, reopened)
}

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

fn aggregation() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(top_k).unwrap(),
        projection: Projection::Source,
        after: None,
    }
}

fn aggregation_request(query: Query, aggregation: Aggregation, top_k: usize) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.top_k = TopK::new(top_k).unwrap();
    request.aggregation = Some(aggregation);
    request
}

fn run_aggregation(
    snapshot: &Arc<ReaderSnapshot>,
    query: Query,
    aggregation: Aggregation,
    top_k: usize,
) -> SearchResponse {
    let response = execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(
            vec![aggregation_request(query, aggregation, top_k)],
            None,
            BatchBudget::new(4),
        ),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap();
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.clone(),
        other => panic!("aggregation slot failed: {other:?}"),
    }
}

fn unified(snapshot: &Arc<ReaderSnapshot>, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .unwrap()
}

fn assert_unified_equal(local: &UnifiedResponse, remote: &UnifiedResponse) {
    assert_eq!(local.total_hits, remote.total_hits);
    assert_eq!(local.hits.len(), remote.hits.len());
    for (left, right) in local.hits.iter().zip(&remote.hits) {
        assert_eq!(left.key, right.key);
        assert_eq!(left.fields, right.fields);
        assert_eq!(left.score, right.score);
    }
    assert_eq!(local.aggregation, remote.aggregation);
}

fn policy() -> BudgetPolicy {
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

fn batch_requests() -> Vec<QueryRequest> {
    let mut aggregated = QueryRequest::new(mixed_query());
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(aggregation());
    let mut invalid = QueryRequest::new(Query::MatchAll);
    invalid.top_k = TopK::new(1).unwrap();
    invalid.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("nope".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    });
    let mut plain = QueryRequest::new(Query::MatchAll);
    plain.top_k = TopK::new(2).unwrap();
    plain.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    vec![aggregated, invalid, plain]
}

fn run_batch(snapshot: &Arc<ReaderSnapshot>) -> BatchQueryResponse {
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(batch_requests(), None, BatchBudget::new(8)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap()
}

fn assert_batch_equal(local: &BatchQueryResponse, remote: &BatchQueryResponse) {
    assert_eq!(local.len(), remote.len());
    for index in 0..local.len() {
        match (local.slot(index), remote.slot(index)) {
            (Some(PerQueryOutcome::Success(a)), Some(PerQueryOutcome::Success(b))) => {
                assert_eq!(a.total_hits, b.total_hits);
                assert_eq!(a.aggregation, b.aggregation);
                assert_eq!(a.hits.len(), b.hits.len());
                for (hit_a, hit_b) in a.hits.iter().zip(&b.hits) {
                    assert_eq!(hit_a.key, hit_b.key);
                    assert_eq!(hit_a.fields, hit_b.fields);
                    assert_eq!(hit_a.score, hit_b.score);
                }
            }
            (Some(PerQueryOutcome::Failure(a)), Some(PerQueryOutcome::Failure(b))) => {
                assert_eq!(a, b);
            }
            (a, b) => panic!("outcome mismatch at slot {index}: {a:?} vs {b:?}"),
        }
    }
}

fn group_counts(response: &SearchResponse) -> Vec<(String, u64, i128)> {
    let result = response.aggregation.as_ref().expect("aggregation");
    result
        .groups
        .iter()
        .map(|group| {
            let host = match &group.components[0] {
                AggregationGroupValue::Value(FieldValue::Keyword(host)) => host.clone(),
                other => panic!("unexpected group component {other:?}"),
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

// Local-only oracle gate: must pass before any remote comparison.
#[test]
fn r02_local_mixed_oracle_and_aggregation() {
    let (path, index) = build_local("local-oracle");
    let snapshot = index.snapshot();
    let response = run_aggregation(&snapshot, mixed_query(), aggregation(), 10);
    // d0, d1, d3, d5 satisfy alpha + range + JSON + bbox.
    assert_eq!(response.total_hits, 4);
    let mut counts = group_counts(&response);
    counts.sort();
    assert_eq!(
        counts,
        vec![("h1".to_owned(), 3, 90), ("h2".to_owned(), 1, 40)]
    );
    let _ = std::fs::remove_dir_all(path);
}

// R04/R06/R07 local: nested Boolean, ranking, projection and five-state fields.
#[test]
fn r04_r06_r07_local_nested_boolean_and_states() {
    let (path, index) = build_local("local-nested");
    let snapshot = index.snapshot();
    let query = Query::And(vec![
        Query::Or(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("beta".into()),
            },
        ]),
        Query::Not(Box::new(Query::Term {
            field: "host".into(),
            value: FieldValue::Keyword("h3".into()),
        })),
    ]);
    let mut request = request(query, 10);
    request.projection = Projection::Fields(vec!["n".into(), "nullable".into()]);
    let response = unified(&snapshot, &request);
    assert_eq!(response.total_hits, 5);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert!(keys.contains(&"d1"));
    let d1 = response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "d1")
        .unwrap();
    assert!(d1
        .fields
        .iter()
        .any(|(name, values)| name == "nullable" && matches!(values, FieldValues::ExplicitNull)));
    let _ = std::fs::remove_dir_all(path);
}

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT required for real P4 acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET required for real P4 acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY required for real P4 acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY required for real P4 acceptance");
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
            .name("pr14-p4-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .unwrap()
                    .block_on(body);
            })
            .unwrap();
        handle.join().expect("real P4 test panicked");
    }

    fn config(tag: &str) -> RemoteConfig {
        RemoteConfig::new(
            RemoteKeyPrefix::parse(format!(
                "pr14-p4/{tag}/{}/{}/{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or(0),
                "case"
            ))
            .unwrap(),
            p4_dir(&format!("remote-{tag}")),
        )
        .with_transfer(RemoteTransferConfig::default())
    }

    async fn remote_index(
        tag: &str,
    ) -> (Arc<S3ObjectStore>, RemoteConfig, RemoteIndex<S3ObjectStore>) {
        let (endpoint, bucket, access, secret, region) = env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret)).unwrap(),
        );
        store.create_bucket_if_absent().await.unwrap();
        let config = config(tag);
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

    async fn publish(index: &RemoteIndex<S3ObjectStore>) {
        let docs = fixture();
        {
            let mut writer = index.writer().await.unwrap();
            for document in docs.iter().take(3) {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
        {
            let mut writer = index.writer().await.unwrap();
            for document in docs.iter().skip(3) {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r02_r04_r06_real_cold_compound_equivalence() {
        run(async {
            let (store, config, index) = remote_index("r02").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(2));
            let remote_snapshot = reader.snapshot();

            let (local_path, local_index) = build_local("r02-local");
            let local_snapshot = local_index.snapshot();
            let req = request(mixed_query(), 10);
            let local = unified(&local_snapshot, &req);
            let remote = unified(&remote_snapshot, &req);
            assert_unified_equal(&local, &remote);
            assert_eq!(local.total_hits, 4);
            let local_agg = run_aggregation(&local_snapshot, mixed_query(), aggregation(), 10);
            let remote_agg = run_aggregation(&remote_snapshot, mixed_query(), aggregation(), 10);
            assert_eq!(local_agg.total_hits, remote_agg.total_hits);
            assert_eq!(local_agg.aggregation, remote_agg.aggregation);
            assert_eq!(group_counts(&local_agg), group_counts(&remote_agg));
            std::fs::remove_dir_all(local_path).unwrap();
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r08_r09_r15_real_batch_aggregation_and_cursor() {
        run(async {
            let (store, config, index) = remote_index("r08").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let remote_snapshot = reader.snapshot();
            let (local_path, local_index) = build_local("r08-local");
            let local_snapshot = local_index.snapshot();

            let local = run_batch(&local_snapshot);
            let remote = run_batch(&remote_snapshot);
            assert_batch_equal(&local, &remote);
            assert!(matches!(local.slot(0), Some(PerQueryOutcome::Success(_))));
            assert!(matches!(local.slot(1), Some(PerQueryOutcome::Failure(_))));
            assert!(matches!(local.slot(2), Some(PerQueryOutcome::Success(_))));
            let aggregated = match local.slot(0).unwrap() {
                PerQueryOutcome::Success(response) => response,
                _ => unreachable!(),
            };
            assert!(aggregated.aggregation.is_some());
            assert_eq!(aggregated.total_hits, 4);
            assert!(aggregated.hits.len() <= 1);

            // STOP S2: public cursor + aggregation remains fail-closed remotely.
            let mut cursor = QueryRequest::new(Query::MatchAll);
            cursor.top_k = TopK::new(1).unwrap();
            cursor.aggregation = Some(aggregation());
            cursor.pit = Some(PitId::new("pit").unwrap());
            cursor.cursor = Some(quervant_core::contract::result::Cursor::new(
                PitId::new("pit").unwrap(),
                Sort::default(),
                DocumentKey::new("a").unwrap(),
                Timestamp::from_micros(10),
            ));
            let response = execute_batch(
                &remote_snapshot,
                &schema(),
                &registry(),
                SearchLimits::default(),
                &BatchQueryRequest::new(vec![cursor], None, BatchBudget::new(8)),
                &policy(),
                &CapabilitySet::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
            assert!(matches!(
                response.slot(0),
                Some(PerQueryOutcome::Failure(_))
            ));
            std::fs::remove_dir_all(local_path).unwrap();
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r05_real_mutation_old_and_new_snapshot() {
        run(async {
            let (store, config, index) = remote_index("r05").await;
            publish(&index).await;
            let old = index.writer().await.unwrap().refresh().unwrap();
            let old_total = unified(&old, &request(Query::MatchAll, 10)).total_hits;
            assert_eq!(old_total, 6);
            let new = {
                let mut writer = index.writer().await.unwrap();
                let mut updated = fixture()[0].clone();
                set(&mut updated, "title", FieldValue::Text("delta".into()));
                writer.apply(MutationRequest::upsert(updated)).unwrap();
                writer
                    .apply(MutationRequest::delete(DocumentKey::new("d2").unwrap()))
                    .unwrap();
                writer.commit().await.unwrap();
                writer.refresh().unwrap()
            };
            // Pinned old snapshot is unchanged.
            assert_eq!(unified(&old, &request(Query::MatchAll, 10)).total_hits, 6);
            assert_eq!(unified(&new, &request(Query::MatchAll, 10)).total_hits, 5);
            let new_keys: Vec<String> = unified(&new, &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert!(!new_keys.contains(&"d2".to_owned()));

            // Cold remote reopen equals the new local generation.
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let reopened = reader.snapshot();
            assert_eq!(
                unified(&reopened, &request(Query::MatchAll, 10)).total_hits,
                5
            );
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    fn run_batch_with(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        policy: &BudgetPolicy,
    ) -> BatchQueryResponse {
        execute_batch(
            snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &BatchQueryRequest::new(queries, None, BatchBudget::new(8)),
            policy,
            &CapabilitySet::new(),
            &CancellationFlag::new(),
        )
        .unwrap()
    }

    fn min_memory(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        response: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let ok = run_batch_with(snapshot, queries.clone(), &policy_with(mid, response, work))
                .results()
                .iter()
                .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)));
            if ok {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn min_response(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        memory: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let ok = run_batch_with(snapshot, queries.clone(), &policy_with(memory, mid, work))
                .results()
                .iter()
                .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)));
            if ok {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn policy_with(memory: u64, response: u64, work: u64) -> BudgetPolicy {
        BudgetPolicy::new(
            Budgets::new()
                .with(BudgetKind::QueriesPerBatch, 8)
                .unwrap()
                .with(BudgetKind::BatchMemoryBytes, memory)
                .unwrap()
                .with(BudgetKind::BatchResponseBytes, response)
                .unwrap()
                .with(BudgetKind::BatchAggregate, work)
                .unwrap(),
            Budgets::new(),
            Budgets::new(),
            Budgets::new(),
        )
    }

    fn aggregated_queries() -> Vec<QueryRequest> {
        vec![aggregation_request(mixed_query(), aggregation(), 1)]
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r10_r11_real_remote_budget_exact_and_one_over() {
        run(async {
            let (store, config, index) = remote_index("r10").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let snapshot = reader.snapshot();

            let queries = aggregated_queries();
            let memory_min = min_memory(&snapshot, queries.clone(), 1 << 30, 1 << 30);
            assert!(matches!(
                run_batch_with(
                    &snapshot,
                    queries.clone(),
                    &policy_with(memory_min, 1 << 30, 1 << 30)
                )
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let memory_over = run_batch_with(
                &snapshot,
                queries.clone(),
                &policy_with(memory_min - 1, 1 << 30, 1 << 30),
            );
            assert!(matches!(
                memory_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchMemoryBytes
                    }
                ))
            ));

            let response_min = min_response(&snapshot, queries.clone(), 1 << 30, 1 << 30);
            assert!(matches!(
                run_batch_with(
                    &snapshot,
                    queries.clone(),
                    &policy_with(1 << 30, response_min, 1 << 30)
                )
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let response_over = run_batch_with(
                &snapshot,
                queries,
                &policy_with(1 << 30, response_min - 1, 1 << 30),
            );
            assert!(matches!(
                response_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchResponseBytes
                    }
                ))
            ));
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r12_empty_cache_no_writer_state() {
        run(async {
            let (store, config, index) = remote_index("r12").await;
            publish(&index).await;
            drop(index);
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            assert!(!config.workspace_root().exists());
            let reader = RemoteIndex::open_existing(
                store,
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(2));
            let response = unified(&reader.snapshot(), &request(mixed_query(), 10));
            assert_eq!(response.total_hits, 4);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }
}
