//! P01–P04: real remote benchmark lane (whole vs ranged cold open, warm query).
//!
//! This is a measurement runner, not a pass/fail microbenchmark. It is
//! `#[ignore]`d by default and requires the documented `QUERVANT_RUSTFS_*`
//! environment. It emits a raw CSV under `benchmarks/reports/` plus a summary.
//! It performs 3 warm-ups and at least 20 measured trials per configuration and
//! reports p50/p95/p99, GET count/bytes, retries, peak retained bytes and RSS.

#![cfg(feature = "s3")]

use std::sync::Arc;
use std::time::{Duration, Instant};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::IndexLimits;
use quervant_core::remote::{
    RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig, TransferStats,
};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_objectstore::{S3Config, S3ObjectStore};
use sha2::{Digest, Sha256};

const CORPUS_DOCS: usize = 20_000;
const WARMUPS: usize = 3;
const TRIALS: usize = 20;

struct Env {
    endpoint: String,
    region: String,
    bucket: String,
    access_key: String,
    secret_key: String,
}

fn env() -> Option<Env> {
    Some(Env {
        endpoint: std::env::var("QUERVANT_RUSTFS_ENDPOINT").ok()?,
        region: std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned()),
        bucket: std::env::var("QUERVANT_RUSTFS_BUCKET").ok()?,
        access_key: std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").ok()?,
        secret_key: std::env::var("QUERVANT_RUSTFS_SECRET_KEY").ok()?,
    })
}

fn run_id() -> u128 {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    })
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn corpus() -> (Vec<Document>, String) {
    let mut documents = Vec::with_capacity(CORPUS_DOCS);
    let mut hasher = Sha256::new();
    for i in 0..CORPUS_DOCS {
        let key = format!("d{i:06}");
        let title = format!("alpha beta gamma document number {i}");
        hasher.update(key.as_bytes());
        hasher.update(b"\0");
        hasher.update(title.as_bytes());
        hasher.update(b"\0");
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert("title", FieldValues::Single(FieldValue::Text(title)))
            .unwrap();
        documents.push(document);
    }
    let digest = hasher.finalize();
    (documents, hex(&digest))
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn temp_workspace(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "quervant-bench-{}-{name}-{}",
        std::process::id(),
        run_id()
    ))
}

fn remote_config(name: &str, ranged: bool) -> RemoteConfig {
    let transfer = if ranged {
        RemoteTransferConfig::default()
            .with_range_threshold(1)
            .with_chunk_size(256 * 1024)
            .with_max_aggregate_response_bytes(16 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(8)
    } else {
        RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024 * 1024)
            .with_chunk_size(8 * 1024 * 1024)
            .with_max_aggregate_response_bytes(256 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(1)
    };
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!("bench/{name}-{}-{}", std::process::id(), run_id()))
            .unwrap(),
        temp_workspace(name),
    )
    .with_cache(quervant_core::storage::CacheConfig::new(
        1024 * 1024 * 1024,
        8,
        1024 * 1024 * 1024,
    ))
    .with_transfer(transfer)
}

fn limits() -> IndexLimits {
    IndexLimits::default().with_max_pending_docs(CORPUS_DOCS as u64 + 16)
}

fn rss_kib() -> u64 {
    // Linux-only: resident set size in KiB from /proc/self/statm.
    let Ok(text) = std::fs::read_to_string("/proc/self/statm") else {
        return 0;
    };
    let pages: u64 = text
        .split_whitespace()
        .nth(1)
        .and_then(|field| field.parse().ok())
        .unwrap_or(0);
    pages.saturating_mul(4)
}

fn percentile(sorted: &[Duration], pct: f64) -> Duration {
    if sorted.is_empty() {
        return Duration::ZERO;
    }
    let rank = ((sorted.len() - 1) as f64 * pct).round() as usize;
    sorted[rank.min(sorted.len() - 1)]
}

fn query(title: &str, snapshot: &quervant_core::index::ReaderSnapshot) -> usize {
    let schema = schema();
    let registry = registry();
    let cancel = CancellationFlag::new();
    LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
        .search(
            &Query::Term {
                field: "title".to_owned(),
                value: FieldValue::Text(title.to_owned()),
            },
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &cancel,
        )
        .expect("search")
        .total_hits as usize
}

struct Sample {
    cold_open_ms: f64,
    query_ms: f64,
    requests: u64,
    bytes: u64,
    range_requests: u64,
    whole_requests: u64,
    peak_retained_bytes: u64,
    rss_kib: u64,
}

fn summarize(mode: &str, samples: &[Sample], csv: &mut String) {
    let mut cold: Vec<Duration> = samples
        .iter()
        .map(|s| Duration::from_secs_f64(s.cold_open_ms / 1000.0))
        .collect();
    cold.sort();
    let mut warm: Vec<Duration> = samples
        .iter()
        .map(|s| Duration::from_secs_f64(s.query_ms / 1000.0))
        .collect();
    warm.sort();
    println!(
        "[{mode}] cold p50/p95/p99 = {:.1}/{:.1}/{:.1} ms | query p50/p95/p99 = {:.2}/{:.2}/{:.2} ms | GETs mean {:.1} bytes mean {:.0} peak_retained {} rss {} KiB",
        percentile(&cold, 0.50).as_secs_f64() * 1000.0,
        percentile(&cold, 0.95).as_secs_f64() * 1000.0,
        percentile(&cold, 0.99).as_secs_f64() * 1000.0,
        percentile(&warm, 0.50).as_secs_f64() * 1000.0,
        percentile(&warm, 0.95).as_secs_f64() * 1000.0,
        percentile(&warm, 0.99).as_secs_f64() * 1000.0,
        samples.iter().map(|s| s.requests as f64).sum::<f64>() / samples.len() as f64,
        samples.iter().map(|s| s.bytes as f64).sum::<f64>() / samples.len() as f64,
        samples
            .iter()
            .map(|s| s.peak_retained_bytes)
            .max()
            .unwrap_or(0),
        samples.iter().map(|s| s.rss_kib).max().unwrap_or(0),
    );
    for (trial, sample) in samples.iter().enumerate() {
        csv.push_str(&format!(
            "{mode},{trial},{:.3},{:.3},{},{},{},{},{},{}\n",
            sample.cold_open_ms,
            sample.query_ms,
            sample.requests,
            sample.bytes,
            sample.range_requests,
            sample.whole_requests,
            sample.peak_retained_bytes,
            sample.rss_kib,
        ));
    }
}

fn run(body: impl std::future::Future<Output = ()> + Send + 'static) {
    let handle = std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(move || {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(4)
                .enable_all()
                .build()
                .expect("runtime");
            runtime.block_on(body);
        })
        .expect("spawn");
    handle.join().expect("benchmark panicked");
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn p01_p04_remote_benchmark_lane() {
    run(async {
        let Some(env) = env() else {
            return;
        };
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(
                env.endpoint.clone(),
                env.region.clone(),
                env.bucket.clone(),
                env.access_key.clone(),
                env.secret_key.clone(),
            ))
            .expect("config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");
        let (documents, corpus_digest) = corpus();
        println!(
            "corpus: {CORPUS_DOCS} docs digest={corpus_digest} warmups={WARMUPS} trials={TRIALS}"
        );

        let mut csv = String::from(
            "mode,trial,cold_open_ms,query_ms,requests,bytes,range_requests,whole_requests,peak_retained_bytes,rss_kib\n",
        );

        for (mode, ranged) in [("whole", false), ("ranged", true)] {
            let config = remote_config(mode, ranged);
            let workspace = config.workspace_root().to_path_buf();
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                limits(),
            )
            .await
            .expect("create");
            {
                let mut writer = index.writer().await.expect("writer");
                for document in &documents {
                    writer.insert(document.clone()).expect("insert");
                }
                writer.commit().await.expect("commit");
            }

            let mut samples = Vec::with_capacity(TRIALS);
            for trial in 0..(WARMUPS + TRIALS) {
                // Cold: empty application cache/workspace.
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
                .expect("cold open");
                let cold_open = start.elapsed();
                assert_eq!(query("alpha", &reader.snapshot()), CORPUS_DOCS);

                let stats: Arc<TransferStats> = reader.transfer_stats();
                let requests_before = stats.requests();
                let start = Instant::now();
                let hits = query("alpha", &reader.snapshot());
                let query_time = start.elapsed();
                assert_eq!(hits, CORPUS_DOCS);
                // Warm scoring must not issue remote GETs.
                assert_eq!(stats.requests(), requests_before, "scoring GET");

                if trial >= WARMUPS {
                    samples.push(Sample {
                        cold_open_ms: cold_open.as_secs_f64() * 1000.0,
                        query_ms: query_time.as_secs_f64() * 1000.0,
                        requests: stats.requests(),
                        bytes: stats.bytes(),
                        range_requests: stats.range_requests(),
                        whole_requests: stats.whole_requests(),
                        peak_retained_bytes: stats.peak_retained_bytes(),
                        rss_kib: rss_kib(),
                    });
                }
            }
            summarize(mode, &samples, &mut csv);
            let _ = std::fs::remove_dir_all(&workspace);
        }

        let reports =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../benchmarks/reports");
        std::fs::create_dir_all(&reports).ok();
        let path = reports.join(format!("pr13-remote-{}.csv", run_id()));
        std::fs::write(&path, csv).expect("write csv");
        println!(
            "raw CSV: {} (corpus digest {corpus_digest})",
            path.display()
        );
    });
}
