//! PR 14 P4 — real RustFS deterministic fault/recovery (F01–F10 subset).
//!
//! Faults are injected at the HTTP boundary by the PR 13 proxy in front of the
//! real RustFS service. Each case proves the fault was observed, that no
//! partial/corrupt generation becomes readable, and that a clean reopen equals
//! the committed oracle. Stateful cases run 10 independent iterations with
//! unique prefixes and cache workspaces.

#![cfg(feature = "s3")]

mod pr14_common;
#[path = "../../quervant-objectstore/tests/support/mod.rs"]
mod support;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::Document;
use quervant_core::contract::query::{Bound, Query};
use quervant_core::contract::result::{Sort, TopK};
use quervant_core::contract::value::{FieldValue, Timestamp};
use quervant_core::index::{IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
};
use quervant_objectstore::{S3Config, S3ObjectStore};
use support::{Fault, Proxy, Rule};

const ITERATIONS: usize = 10;

struct Env {
    endpoint: String,
    region: String,
    bucket: String,
    access_key: String,
    secret_key: String,
}

fn env() -> Env {
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
        .expect("QUERVANT_RUSTFS_ENDPOINT required for real P4 faults");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
        .expect("QUERVANT_RUSTFS_BUCKET required for real P4 faults");
    let access_key = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
        .expect("QUERVANT_RUSTFS_ACCESS_KEY required for real P4 faults");
    let secret_key = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
        .expect("QUERVANT_RUSTFS_SECRET_KEY required for real P4 faults");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    for (name, value) in [
        ("endpoint", &endpoint),
        ("bucket", &bucket),
        ("access", &access_key),
        ("secret", &secret_key),
    ] {
        assert!(!value.trim().is_empty(), "{name} must not be empty");
    }
    assert!(endpoint.starts_with("http://"));
    Env {
        endpoint,
        region,
        bucket,
        access_key,
        secret_key,
    }
}

fn run<F>(body: F)
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let handle = std::thread::Builder::new()
        .name("pr14-p4-faults".to_owned())
        .stack_size(32 * 1024 * 1024)
        .spawn(move || {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap()
                .block_on(body);
        })
        .unwrap();
    handle.join().expect("fault test panicked");
}

fn dir(tag: &str, iteration: usize) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr14-p4-fault-{}-{tag}-{iteration}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

fn prefix(tag: &str, iteration: usize) -> String {
    format!(
        "pr14-p4-faults/{tag}/{}/{}/{iteration}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    )
}

fn config(prefix: String, workspace: std::path::PathBuf) -> RemoteConfig {
    RemoteConfig::new(RemoteKeyPrefix::parse(prefix).unwrap(), workspace)
        .with_transfer(RemoteTransferConfig::default())
}

fn store(endpoint: &str, env: &Env) -> Arc<S3ObjectStore> {
    Arc::new(
        S3ObjectStore::new(S3Config::rustfs(
            endpoint,
            env.region.clone(),
            env.bucket.clone(),
            env.access_key.clone(),
            env.secret_key.clone(),
        ))
        .unwrap(),
    )
}

fn documents() -> Vec<Document> {
    let mut out = Vec::new();
    for (key, title, host, n) in [
        ("a", "alpha beta", "h1", 10i64),
        ("b", "alpha", "h1", 20),
        ("c", "beta", "h2", 30),
    ] {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text(title.into()));
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(n)),
        );
        out.push(document);
    }
    out
}

async fn publish(store: Arc<S3ObjectStore>, config: RemoteConfig) {
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .unwrap();
    let mut writer = index.writer().await.unwrap();
    for document in documents() {
        writer.insert(document).unwrap();
    }
    writer.commit().await.unwrap();
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
    ])
}

fn unified(snapshot: &Arc<ReaderSnapshot>) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(
            &UnifiedRequest {
                query: mixed_query(),
                sort: Sort::default(),
                top_k: TopK::new(10).unwrap(),
                projection: quervant_core::contract::result::Projection::Source,
                after: None,
            },
            &Budgets::new(),
            &CancellationFlag::new(),
        )
        .unwrap()
}

fn batch(snapshot: &Arc<ReaderSnapshot>) -> quervant_core::contract::batch::BatchQueryResponse {
    let mut aggregated = QueryRequest::new(mixed_query());
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(quervant_core::contract::aggregation::Aggregation {
        group_by: Some(quervant_core::contract::aggregation::GroupBy::new(vec![
            quervant_core::contract::aggregation::GroupKey::Field("host".into()),
        ])),
        aggregates: vec![quervant_core::contract::aggregation::Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    });
    let mut plain = QueryRequest::new(Query::MatchAll);
    plain.top_k = TopK::new(2).unwrap();
    let policy = BudgetPolicy::new(
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
    );
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![aggregated, plain], None, BatchBudget::new(8)),
        &policy,
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap()
}

async fn healthy_reopen(env: &Env, prefix: String, workspace: std::path::PathBuf) {
    let store = store(&env.endpoint, env);
    let reader = RemoteIndex::open_existing(
        store,
        config(prefix, workspace.clone()),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("healthy reopen");
    assert_eq!(reader.generation(), Some(1));
    let response = unified(&reader.snapshot());
    assert_eq!(response.total_hits, 2);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert!(keys.contains(&"a") && keys.contains(&"b") && !keys.contains(&"c"));
    let batched = batch(&reader.snapshot());
    assert!(matches!(batched.slot(0), Some(PerQueryOutcome::Success(_))));
    assert!(matches!(batched.slot(1), Some(PerQueryOutcome::Success(_))));
    let aggregated = match batched.slot(0).unwrap() {
        PerQueryOutcome::Success(response) => response,
        _ => unreachable!(),
    };
    assert!(aggregated.aggregation.is_some());
    let _ = std::fs::remove_dir_all(workspace);
}

/// One proxy-fault case, 10 independent iterations.
#[allow(clippy::too_many_arguments)]
async fn proxy_case(
    env: &Env,
    tag: &str,
    method: &str,
    key: &str,
    fault: Fault,
    nth: usize,
    allow_retry_success: bool,
    ranged: bool,
) {
    for iteration in 0..ITERATIONS {
        let prefix = prefix(tag, iteration);
        let workspace = dir(tag, iteration);
        publish(
            store(&env.endpoint, env),
            config(prefix.clone(), dir(&format!("{tag}-seed"), iteration)),
        )
        .await;

        let (host, port) = {
            let rest = env
                .endpoint
                .strip_prefix("http://")
                .or_else(|| env.endpoint.strip_prefix("https://"))
                .unwrap_or(&env.endpoint)
                .trim_end_matches('/');
            match rest.rsplit_once(':') {
                Some((host, port)) => (host.to_owned(), port.parse().expect("port")),
                None => (rest.to_owned(), 80),
            }
        };
        let proxy = Proxy::start(&host, port).await;
        proxy.add_rule(Rule {
            method: method.to_owned(),
            key_contains: key.to_owned(),
            nth,
            fault: fault.clone(),
        });
        let mut proxy_config = config(prefix.clone(), workspace.clone());
        if ranged {
            proxy_config = proxy_config.with_transfer(
                RemoteTransferConfig::default()
                    .with_range_threshold(1)
                    .with_chunk_size(1024),
            );
        }
        let faulted = RemoteIndex::open_existing(
            store(&proxy.endpoint, env),
            proxy_config,
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await;
        if let Ok(reader) = faulted {
            assert!(
                allow_retry_success,
                "iteration {iteration}: injected fault unexpectedly recovered"
            );
            assert_eq!(unified(&reader.snapshot()).total_hits, 2);
        }
        assert!(
            proxy.observed(method, key) > 0,
            "iteration {iteration}: fault was not triggered"
        );
        drop(proxy);
        std::fs::remove_dir_all(&workspace).unwrap();
        healthy_reopen(env, prefix, workspace).await;
    }
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f01_segment_get_transient_failure() {
    run(async {
        let env = env();
        proxy_case(
            &env,
            "f01",
            "GET",
            "index/segments",
            Fault::Return503,
            1,
            true,
            false,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f02_truncated_segment_transfer() {
    run(async {
        let env = env();
        proxy_case(
            &env,
            "f02",
            "GET",
            "index/segments",
            Fault::TruncateBodyAfter(16),
            1,
            false,
            false,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f03_corrupt_content_range_rejected() {
    run(async {
        let env = env();
        proxy_case(
            &env,
            "f03",
            "GET",
            "index/segments",
            Fault::ReplaceStatus200,
            1,
            false,
            true,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f04_manifest_read_interrupted() {
    run(async {
        let env = env();
        proxy_case(
            &env,
            "f04",
            "GET",
            "index/CURRENT",
            Fault::Return503,
            1,
            false,
            false,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f07_retry_exhaustion_is_bounded_and_recoverable() {
    run(async {
        let env = env();
        proxy_case(
            &env,
            "f07",
            "GET",
            "index/segments",
            Fault::Return503,
            0,
            false,
            false,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f05_concurrent_old_reader_and_new_commit() {
    run(async {
        let env = env();
        for iteration in 0..ITERATIONS {
            let prefix = prefix("f05", iteration);
            let workspace = dir("f05", iteration);
            let store = store(&env.endpoint, &env);
            publish(
                Arc::clone(&store),
                config(prefix.clone(), workspace.clone()),
            )
            .await;
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config(prefix.clone(), dir("f05-reader", iteration)),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let old = reader.snapshot();
            assert_eq!(unified(&old).total_hits, 2);
            let index = RemoteIndex::open_existing(
                Arc::clone(&store),
                config(prefix.clone(), workspace.clone()),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            {
                let mut writer = index.writer().await.unwrap();
                let mut added = doc("d");
                set(&mut added, "title", FieldValue::Text("alpha".into()));
                set(&mut added, "host", FieldValue::Keyword("h1".into()));
                set(&mut added, "n", FieldValue::I64(40));
                writer
                    .insert(added)
                    .map_err(|error| panic!("insert: {error:?}"))
                    .unwrap();
                writer.commit().await.unwrap();
            }
            // Old pinned snapshot is unchanged; a fresh reader sees the new one.
            assert_eq!(unified(&old).total_hits, 2);
            let fresh = index.writer().await.unwrap().refresh().unwrap();
            assert_eq!(unified(&fresh).total_hits, 3);
            let _ = std::fs::remove_dir_all(workspace);
        }
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f06_cancellation_during_transfer_is_bounded() {
    run(async {
        let env = env();
        for iteration in 0..ITERATIONS {
            let prefix = prefix("f06", iteration);
            let workspace = dir("f06", iteration);
            publish(
                store(&env.endpoint, &env),
                config(prefix.clone(), dir("f06-seed", iteration)),
            )
            .await;
            let rest = env
                .endpoint
                .strip_prefix("http://")
                .unwrap_or(&env.endpoint)
                .trim_end_matches('/');
            let (host, port) = rest.rsplit_once(':').unwrap();
            let proxy = Proxy::start(host, port.parse().unwrap()).await;
            let release = Arc::new(tokio::sync::Notify::new());
            proxy.add_rule(Rule {
                method: "GET".to_owned(),
                key_contains: "index/segments".to_owned(),
                nth: 1,
                fault: Fault::DelayUntil(Arc::clone(&release)),
            });
            let open = RemoteIndex::open_existing(
                store(&proxy.endpoint, &env),
                config(prefix.clone(), workspace.clone()),
                schema(),
                registry(),
                IndexLimits::default(),
            );
            let outcome = tokio::time::timeout(std::time::Duration::from_millis(250), open).await;
            assert!(
                outcome.is_err(),
                "iteration {iteration}: cancellation/timeout did not bound the transfer"
            );
            assert!(
                proxy.observed("GET", "index/segments") > 0,
                "iteration {iteration}: delayed GET was not observed"
            );
            drop(proxy);
            std::fs::remove_dir_all(&workspace).unwrap();
            healthy_reopen(&env, prefix, workspace).await;
        }
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn f09_f10_batch_after_fault_and_s_f_s() {
    run(async {
        let env = env();
        for iteration in 0..ITERATIONS {
            let prefix = prefix("f09", iteration);
            let workspace = dir("f09", iteration);
            publish(
                store(&env.endpoint, &env),
                config(prefix.clone(), dir("f09-seed", iteration)),
            )
            .await;
            // F09: fault the initial segment GET; either bounded retry succeeds
            // or the open fails, but the healthy path must still work.
            let rest = env
                .endpoint
                .strip_prefix("http://")
                .unwrap_or(&env.endpoint)
                .trim_end_matches('/');
            let (host, port) = rest.rsplit_once(':').unwrap();
            let proxy = Proxy::start(host, port.parse().unwrap()).await;
            proxy.add_rule(Rule {
                method: "GET".to_owned(),
                key_contains: "index/segments".to_owned(),
                nth: 1,
                fault: Fault::Return503,
            });
            let _ = RemoteIndex::open_existing(
                store(&proxy.endpoint, &env),
                config(prefix.clone(), workspace.clone()),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await;
            assert!(proxy.observed("GET", "index/segments") > 0);
            drop(proxy);
            std::fs::remove_dir_all(&workspace).unwrap();

            // F10: healthy reopen, then S→F→S with aggregation + retained prior.
            let store = store(&env.endpoint, &env);
            let reader = RemoteIndex::open_existing(
                store,
                config(prefix.clone(), workspace.clone()),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let mut aggregated = QueryRequest::new(mixed_query());
            aggregated.top_k = TopK::new(1).unwrap();
            aggregated.aggregation = Some(quervant_core::contract::aggregation::Aggregation {
                group_by: Some(quervant_core::contract::aggregation::GroupBy::new(vec![
                    quervant_core::contract::aggregation::GroupKey::Field("host".into()),
                ])),
                aggregates: vec![quervant_core::contract::aggregation::Aggregate::count()],
                exact_distinct: None,
                top_k: None,
                time_bucket: None,
            });
            let mut invalid = QueryRequest::new(Query::MatchAll);
            invalid.top_k = TopK::new(1).unwrap();
            invalid.aggregation = Some(quervant_core::contract::aggregation::Aggregation {
                group_by: Some(quervant_core::contract::aggregation::GroupBy::new(vec![
                    quervant_core::contract::aggregation::GroupKey::Field("missing".into()),
                ])),
                aggregates: vec![quervant_core::contract::aggregation::Aggregate::count()],
                exact_distinct: None,
                top_k: None,
                time_bucket: None,
            });
            let mut plain = QueryRequest::new(Query::MatchAll);
            plain.top_k = TopK::new(2).unwrap();
            let policy = BudgetPolicy::new(
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
            );
            let batch = execute_batch(
                &reader.snapshot(),
                &schema(),
                &registry(),
                SearchLimits::default(),
                &BatchQueryRequest::new(
                    vec![aggregated, invalid, plain],
                    None,
                    BatchBudget::new(8),
                ),
                &policy,
                &CapabilitySet::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
            assert!(matches!(batch.slot(0), Some(PerQueryOutcome::Success(_))));
            assert!(matches!(batch.slot(1), Some(PerQueryOutcome::Failure(_))));
            assert!(matches!(batch.slot(2), Some(PerQueryOutcome::Success(_))));
            let agg = match batch.slot(0).unwrap() {
                PerQueryOutcome::Success(response) => response,
                _ => unreachable!(),
            };
            assert!(agg.aggregation.is_some());
            let _ = std::fs::remove_dir_all(workspace);
        }
    });
}
