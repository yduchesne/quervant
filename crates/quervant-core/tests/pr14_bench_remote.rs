//! PR 14 P4 — correctness-gated local/RustFS cold/warm benchmark runner.
//!
//! Not a cross-engine comparison and not a production p99 estimate. Emits raw
//! rows under `target/pr14-p4/` and a sanitized trial JSON under
//! `benchmarks/reports/`. Qualification requires a clean tree, operator idle
//! confirmation and a `clear` contention result; diagnostic mode cannot qualify.

#![cfg(feature = "s3")]

mod pr14_common;

use std::sync::Arc;
use std::time::{Duration, Instant};

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
};
use quervant_core::storage::{CacheConfig, Directory, FsDirectory};
use quervant_objectstore::{S3Config, S3ObjectStore};
use sha2::{Digest, Sha256};

const CORPUS_DOCS: usize = 20_000;
const WARMUPS: usize = 3;
const SAMPLES: usize = 20;

fn trial_id() -> String {
    std::env::var("QUERVANT_P4_TRIAL").unwrap_or_else(|_| "diagnostic".to_owned())
}

fn diagnostic() -> bool {
    std::env::var("QUERVANT_P4_DIAGNOSTIC").is_ok()
}

fn git_dirty() -> bool {
    std::process::Command::new("git")
        .args(["status", "--porcelain", "--untracked-files=no"])
        .output()
        .map(|output| !output.stdout.is_empty())
        .unwrap_or(true)
}

fn corpus() -> (Vec<Document>, String) {
    let mut documents = Vec::with_capacity(CORPUS_DOCS);
    let mut hasher = Sha256::new();
    for i in 0..CORPUS_DOCS {
        let key = format!("d{i:05}");
        let title = if i % 2 == 0 {
            format!("alpha beta document {i}")
        } else {
            format!("beta gamma document {i}")
        };
        let host = format!("h{}", i % 4);
        let body = JsonValue::Object(
            vec![(
                "n".to_owned(),
                JsonValue::Number(JsonNumber::I64((i % 10) as i64)),
            )]
            .into_iter()
            .collect(),
        );
        for part in [
            key.as_bytes(),
            title.as_bytes(),
            host.as_bytes(),
            &(i as i64).to_le_bytes(),
            &(i as i64).to_le_bytes(),
        ] {
            hasher.update(part);
            hasher.update(b"\0");
        }
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        set(&mut document, "title", FieldValue::Text(title));
        set(&mut document, "host", FieldValue::Keyword(host));
        set(&mut document, "n", FieldValue::I64(i as i64));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(i as i64)),
        );
        set(&mut document, "body", FieldValue::Json(body));
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new((i % 10) as f64, (i % 10) as f64).unwrap()),
        );
        set(
            &mut document,
            "ip",
            FieldValue::Ip(format!("192.0.2.{}", i % 4).parse().unwrap()),
        );
        documents.push(document);
    }
    (documents, hex(&hasher.finalize()))
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(CORPUS_DOCS as u64 + 16)
        .with_max_pending_bytes(1 << 30)
}

fn w01() -> Query {
    Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64((CORPUS_DOCS - 1) as i64)),
        },
    ])
}

fn w03() -> Query {
    Query::JsonPathRange {
        field: "body".into(),
        path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
        lower: Bound::Included(FieldValue::I64(5)),
        upper: Bound::Included(FieldValue::I64(5)),
    }
}

fn w04() -> Query {
    Query::GeoBoundingBox {
        field: "loc".into(),
        bbox: GeoBoundingBox::new(-1.0, -1.0, 2.0, 2.0).unwrap(),
    }
}

fn w05() -> Query {
    Query::And(vec![
        Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        },
        Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(0),
            end: Timestamp::from_micros(10_000),
        },
    ])
}

fn w06() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn request(query: Query, top_k: usize, projection: Projection, sort: Sort) -> UnifiedRequest {
    UnifiedRequest {
        query,
        sort,
        top_k: TopK::new(top_k).unwrap(),
        projection,
        after: None,
    }
}

fn unified(snapshot: &Arc<ReaderSnapshot>, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
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

fn w07_batch(snapshot: &Arc<ReaderSnapshot>) -> quervant_core::contract::batch::BatchQueryResponse {
    let mut aggregated = QueryRequest::new(w01());
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(w06());
    let mut invalid = QueryRequest::new(Query::MatchAll);
    invalid.top_k = TopK::new(1).unwrap();
    invalid.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("missing".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    });
    let mut plain = QueryRequest::new(Query::MatchAll);
    plain.top_k = TopK::new(2).unwrap();
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![aggregated, invalid, plain], None, BatchBudget::new(8)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("batch")
}

fn check_aggregation(response: &SearchResponse, groups: usize, per_group: u64, total: u64) {
    let result = response.aggregation.as_ref().expect("aggregation");
    assert_eq!(result.groups.len(), groups);
    assert_eq!(
        result
            .groups
            .iter()
            .map(|group| match group.metrics[0] {
                AggregationMetricValue::Count(count) => count,
                _ => panic!("count"),
            })
            .sum::<u64>(),
        total
    );
    for group in &result.groups {
        assert!(matches!(
            group.components[0],
            AggregationGroupValue::Value(FieldValue::Keyword(_))
        ));
        assert!(matches!(
            group.metrics[0],
            AggregationMetricValue::Count(count) if count == per_group
        ));
    }
}

fn w06_batch(snapshot: &Arc<ReaderSnapshot>) -> quervant_core::contract::batch::BatchQueryResponse {
    let mut aggregated = QueryRequest::new(Query::MatchAll);
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(w06());
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![aggregated], None, BatchBudget::new(4)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("aggregation batch")
}

/// Independent correctness gate for every timed workload.
fn correctness(snapshot: &Arc<ReaderSnapshot>) {
    assert_eq!(
        unified(
            snapshot,
            &request(w01(), 10, Projection::Source, Sort::default())
        )
        .total_hits,
        10_000
    );
    let mut json = request(
        w03(),
        10,
        Projection::Fields(vec!["n".into()]),
        Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
    );
    json.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    assert_eq!(unified(snapshot, &json).total_hits, 2_000);
    let geo = request(
        w04(),
        10,
        Projection::Source,
        Sort::new(vec![SortField::geo_distance(
            "loc",
            GeoPoint::new(0.0, 0.0).unwrap(),
            SortDirection::Asc,
        )]),
    );
    assert_eq!(unified(snapshot, &geo).total_hits, 6_000);
    assert_eq!(
        unified(
            snapshot,
            &request(w05(), 10, Projection::Source, Sort::default())
        )
        .total_hits,
        2_500
    );
    let batch = w07_batch(snapshot);
    assert!(matches!(batch.slot(0), Some(PerQueryOutcome::Success(_))));
    assert!(matches!(batch.slot(1), Some(PerQueryOutcome::Failure(_))));
    assert!(matches!(batch.slot(2), Some(PerQueryOutcome::Success(_))));
    if let Some(PerQueryOutcome::Success(response)) = batch.slot(0) {
        // W07 aggregates only alpha-matching even docs: i%4 in {0,2}.
        check_aggregation(response, 2, 5_000, 10_000);
    }
    let aggregate = w06_batch(snapshot);
    if let Some(PerQueryOutcome::Success(response)) = aggregate.slot(0) {
        check_aggregation(response, 4, 5_000, 20_000);
    }
}

fn rss_kib() -> u64 {
    let Ok(text) = std::fs::read_to_string("/proc/self/statm") else {
        return 0;
    };
    text.split_whitespace()
        .nth(1)
        .and_then(|field| field.parse::<u64>().ok())
        .map_or(0, |pages| pages * 4)
}

fn percentile(sorted: &[Duration], pct: f64) -> Duration {
    if sorted.is_empty() {
        return Duration::ZERO;
    }
    let rank = ((sorted.len() - 1) as f64 * pct).round() as usize;
    sorted[rank.min(sorted.len() - 1)]
}

fn record(
    csv: &mut String,
    lane: &str,
    workload: &str,
    sample: usize,
    elapsed: Duration,
    hits: u64,
) {
    let micros = elapsed.as_secs_f64() * 1_000_000.0;
    csv.push_str(&format!(
        "{},{},{},{:.3},{},{}\n",
        lane,
        workload,
        sample,
        micros,
        hits,
        rss_kib()
    ));
}

fn warm_measure<F>(
    csv: &mut String,
    lane: &str,
    workload: &str,
    mut operation: F,
) -> (Duration, Duration, Duration)
where
    F: FnMut() -> u64,
{
    for _ in 0..WARMUPS {
        let _ = operation();
    }
    let mut samples = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {
        let start = Instant::now();
        let hits = operation();
        let elapsed = start.elapsed();
        samples.push(elapsed);
        record(csv, lane, workload, sample, elapsed, hits);
    }
    samples.sort();
    (
        percentile(&samples, 0.50),
        percentile(&samples, 0.95),
        percentile(&samples, 0.99),
    )
}

fn local_index() -> (std::path::PathBuf, Index) {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr14-p4-bench-local-{}-{}",
        std::process::id(),
        trial_id()
    ));
    let _ = std::fs::remove_dir_all(&path);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    let (documents, _) = corpus();
    for chunk in [0..7_000, 7_000..14_000, 14_000..CORPUS_DOCS] {
        let mut writer = index.writer().unwrap();
        for document in &documents[chunk] {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    (
        path,
        Index::open_existing(directory, schema(), registry()).unwrap(),
    )
}

fn main_body() {
    let trial = trial_id();
    let (documents, digest) = corpus();
    println!("trial={trial} corpus={CORPUS_DOCS} digest={digest}");

    let mut csv = String::from("lane,workload,sample,micros,hits,rss_kib\n");
    let mut summary = Vec::new();

    // Local lane (W09 cold, W01–W07 warm).
    let (local_path, local_index) = local_index();
    let local_snapshot = local_index.snapshot();
    correctness(&local_snapshot);
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {
        let start = Instant::now();
        let reopened = Index::open_existing(
            Arc::new(FsDirectory::open(&local_path).unwrap()),
            schema(),
            registry(),
        )
        .unwrap();
        let hits = unified(
            &reopened.snapshot(),
            &request(w01(), 10, Projection::Source, Sort::default()),
        )
        .total_hits;
        let elapsed = start.elapsed();
        assert_eq!(hits, 10_000);
        cold.push(elapsed);
        record(&mut csv, "local-cold", "W09", sample, elapsed, hits);
    }
    cold.sort();
    summary.push(format!(
        "local-cold W09 p50={:.3}ms p95={:.3}ms p99={:.3}ms",
        percentile(&cold, 0.5).as_secs_f64() * 1000.0,
        percentile(&cold, 0.95).as_secs_f64() * 1000.0,
        percentile(&cold, 0.99).as_secs_f64() * 1000.0
    ));
    let warm_query = request(w01(), 10, Projection::Source, Sort::default());
    let (p50, p95, p99) = warm_measure(&mut csv, "local-warm", "W02", || {
        unified(&local_snapshot, &warm_query).total_hits
    });
    summary.push(format!(
        "local-warm W02 p50={p50:?} p95={p95:?} p99={p99:?}"
    ));
    let json_request = request(
        w03(),
        10,
        Projection::Fields(vec!["n".into()]),
        Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
    );
    let (_, _, _) = warm_measure(&mut csv, "local-warm", "W03", || {
        unified(&local_snapshot, &json_request).total_hits
    });
    let geo_request = request(
        w04(),
        10,
        Projection::Source,
        Sort::new(vec![SortField::geo_distance(
            "loc",
            GeoPoint::new(0.0, 0.0).unwrap(),
            SortDirection::Asc,
        )]),
    );
    let (_, _, _) = warm_measure(&mut csv, "local-warm", "W04", || {
        unified(&local_snapshot, &geo_request).total_hits
    });
    let ip_request = request(w05(), 10, Projection::Source, Sort::default());
    let (_, _, _) = warm_measure(&mut csv, "local-warm", "W05", || {
        unified(&local_snapshot, &ip_request).total_hits
    });
    let (_, _, _) = warm_measure(&mut csv, "local-warm", "W06", || {
        w06_batch(&local_snapshot).len() as u64
    });
    let (_, _, _) = warm_measure(&mut csv, "local-warm", "W07", || {
        w07_batch(&local_snapshot).len() as u64
    });
    let _ = std::fs::remove_dir_all(local_path);

    // Remote lanes.
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT").expect("endpoint");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").expect("bucket");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").expect("access");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").expect("secret");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    let store = Arc::new(
        S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret)).unwrap(),
    );
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        store.create_bucket_if_absent().await.unwrap();
        let prefix = format!(
            "pr14-p4-bench/{trial}/{}/{}/case",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        );
        let config = RemoteConfig::new(
            RemoteKeyPrefix::parse(prefix).unwrap(),
            std::env::temp_dir().join(format!("quervant-pr14-p4-bench-remote-{trial}")),
        )
        .with_cache(CacheConfig::new(1 << 30, 8, 1 << 30))
        .with_transfer(RemoteTransferConfig::default());
        let workspace = config.workspace_root().to_path_buf();
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            limits(),
        )
        .await
        .unwrap();
        for chunk in [0..7_000, 7_000..14_000, 14_000..CORPUS_DOCS] {
            let mut writer = index.writer().await.unwrap();
            for document in &documents[chunk] {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
        let _ = std::fs::remove_dir_all(&workspace);

        let mut cold = Vec::with_capacity(SAMPLES);
        for sample in 0..SAMPLES {
            let _ = std::fs::remove_dir_all(&workspace);
            let start = Instant::now();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                limits(),
            )
            .await
            .unwrap();
            let hits = unified(
                &reader.snapshot(),
                &request(w01(), 10, Projection::Source, Sort::default()),
            )
            .total_hits;
            let elapsed = start.elapsed();
            assert_eq!(hits, 10_000);
            cold.push(elapsed);
            record(&mut csv, "remote-cold", "W01", sample, elapsed, hits);
        }
        cold.sort();
        summary.push(format!(
            "remote-cold W01 p50={:.3}ms p95={:.3}ms p99={:.3}ms",
            percentile(&cold, 0.5).as_secs_f64() * 1000.0,
            percentile(&cold, 0.95).as_secs_f64() * 1000.0,
            percentile(&cold, 0.99).as_secs_f64() * 1000.0
        ));
        let reader = RemoteIndex::open_existing(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            limits(),
        )
        .await
        .unwrap();
        let snapshot = reader.snapshot();
        correctness(&snapshot);
        let (p50, p95, p99) = warm_measure(&mut csv, "remote-warm", "W02", || {
            unified(
                &snapshot,
                &request(w01(), 10, Projection::Source, Sort::default()),
            )
            .total_hits
        });
        summary.push(format!(
            "remote-warm W02 p50={p50:?} p95={p95:?} p99={p99:?}"
        ));
        let mut warm_json = request(
            w03(),
            10,
            Projection::Fields(vec!["n".into()]),
            Sort::default(),
        );
        warm_json.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
        let (_, _, _) = warm_measure(&mut csv, "remote-warm", "W03", || {
            unified(&snapshot, &warm_json).total_hits
        });
        let warm_geo = request(
            w04(),
            10,
            Projection::Source,
            Sort::new(vec![SortField::geo_distance(
                "loc",
                GeoPoint::new(0.0, 0.0).unwrap(),
                SortDirection::Asc,
            )]),
        );
        let (_, _, _) = warm_measure(&mut csv, "remote-warm", "W04", || {
            unified(&snapshot, &warm_geo).total_hits
        });
        let warm_ip = request(w05(), 10, Projection::Source, Sort::default());
        let (_, _, _) = warm_measure(&mut csv, "remote-warm", "W05", || {
            unified(&snapshot, &warm_ip).total_hits
        });
        let (_, _, _) = warm_measure(&mut csv, "remote-warm", "W06", || {
            w06_batch(&snapshot).len() as u64
        });
        let (_, _, _) = warm_measure(&mut csv, "remote-warm", "W07", || {
            w07_batch(&snapshot).len() as u64
        });
        let _ = std::fs::remove_dir_all(&workspace);
    });

    let raw = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../target/pr14-p4");
    std::fs::create_dir_all(&raw).unwrap();
    let sha = std::process::Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|text| text.trim().to_owned())
        .unwrap_or_default();
    let csv_path = raw.join(format!("pr14-p4-{trial}.csv"));
    std::fs::write(&csv_path, &csv).unwrap();
    let idle = std::env::var("QUERVANT_P4_IDLE_CONFIRMED").is_ok();
    let contention =
        std::env::var("QUERVANT_P4_CONTENTION").unwrap_or_else(|_| "unknown".to_owned());
    let qualified = !diagnostic() && !git_dirty() && idle && contention == "clear";
    let json = format!(
        "{{\"workload\":\"pr14_p4_v1\",\"trial\":\"{trial}\",\"sha\":\"{sha}\",\"corpus_docs\":{CORPUS_DOCS},\"corpus_digest\":\"{digest}\",\"warmups\":{WARMUPS},\"samples\":{SAMPLES},\"qualified\":{qualified},\"idle_confirmed\":{idle},\"contention\":\"{contention}\",\"dirty\":{},\"raw_csv\":\"{}\",\"summary\":{:?}}}\n",
        git_dirty(),
        csv_path.display(),
        summary
    );
    // Qualified campaigns direct fresh reports into an ignored directory so the
    // tracked historical reports stay byte-identical. `create_new` refuses to
    // overwrite an earlier attempt; failed artifacts stay inspectable.
    let reports = match std::env::var_os("QUERVANT_P4_REPORT_DIR") {
        Some(path) if !path.is_empty() => std::path::PathBuf::from(path),
        Some(_) => panic!("QUERVANT_P4_REPORT_DIR must not be empty"),
        None => std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../benchmarks/reports"),
    };
    std::fs::create_dir_all(&reports).expect("create benchmark report directory");
    let json_path = reports.join(format!("pr14-p4-{trial}.json"));
    let mut report_file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&json_path)
        .expect("create benchmark report without overwriting an existing attempt");
    std::io::Write::write_all(&mut report_file, json.as_bytes()).expect("write benchmark report");
    println!(
        "raw={} report={} qualified={qualified}",
        csv_path.display(),
        json_path.display()
    );
    for line in summary {
        println!("{line}");
    }
    assert!(csv.lines().count() > 1, "no measurements");
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn pr14_p4_benchmark() {
    let handle = std::thread::Builder::new()
        .name("pr14-p4-bench".to_owned())
        .stack_size(64 * 1024 * 1024)
        .spawn(main_body)
        .unwrap();
    handle.join().expect("benchmark thread panicked");
}
