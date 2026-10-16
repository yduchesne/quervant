//! H06/H07/H10/H11/H12: production remote publication and transfer exercised
//! through the deterministic HTTP fault proxy in front of real RustFS.
//!
//! The proxy tunnels exact signed requests; the production `S3ObjectStore` and
//! `RemoteIndexWriter`/`RemoteIndex` are used unchanged. `#[ignore]`d by default.

#![cfg(feature = "s3")]

#[path = "../../quervant-objectstore/tests/support/mod.rs"]
mod support;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{IndexError, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_objectstore::{S3Config, S3ObjectStore};
use support::{Fault, Proxy, Rule};
use tokio::sync::Notify;

static DIRS: AtomicU64 = AtomicU64::new(0);

struct Env {
    endpoint: String,
    region: String,
    bucket: String,
    access_key: String,
    secret_key: String,
}

fn require_env() -> Env {
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
        .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
        .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
    let access_key = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
        .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
    let secret_key = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
        .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    assert!(
        !endpoint.trim().is_empty(),
        "QUERVANT_RUSTFS_ENDPOINT must not be empty"
    );
    assert!(
        !bucket.trim().is_empty(),
        "QUERVANT_RUSTFS_BUCKET must not be empty"
    );
    assert!(
        !access_key.trim().is_empty(),
        "QUERVANT_RUSTFS_ACCESS_KEY must not be empty"
    );
    assert!(
        !secret_key.trim().is_empty(),
        "QUERVANT_RUSTFS_SECRET_KEY must not be empty"
    );
    assert!(
        endpoint.starts_with("http://"),
        "real RustFS acceptance requires an http:// endpoint"
    );
    Env {
        endpoint,
        region,
        bucket,
        access_key,
        secret_key,
    }
}

fn parse_host_port(endpoint: &str) -> (String, u16) {
    let rest = endpoint
        .strip_prefix("http://")
        .or_else(|| endpoint.strip_prefix("https://"))
        .unwrap_or(endpoint);
    let rest = rest.trim_end_matches('/');
    match rest.rsplit_once(':') {
        Some((host, port)) => (host.to_owned(), port.parse().expect("port")),
        None => (rest.to_owned(), 80),
    }
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

fn temp_workspace(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!(
        "quervant-pr13-proxy-{}-{name}-{n}",
        std::process::id()
    ))
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

fn document(key: &str, title: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .unwrap();
    document
}

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "pr13proxy/{name}-{}-{}",
            std::process::id(),
            run_id()
        ))
        .unwrap(),
        temp_workspace(name),
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

fn store_through(
    env: &Env,
    endpoint: &str,
    request_timeout: std::time::Duration,
) -> Arc<S3ObjectStore> {
    Arc::new(
        S3ObjectStore::new(
            S3Config::rustfs(
                endpoint.to_owned(),
                env.region.clone(),
                env.bucket.clone(),
                env.access_key.clone(),
                env.secret_key.clone(),
            )
            .with_timeouts(std::time::Duration::from_secs(5), request_timeout),
        )
        .expect("valid config"),
    )
}

fn query_keys(snapshot: &ReaderSnapshot, value: &str) -> Vec<String> {
    let schema = schema();
    let registry = registry();
    let cancel = CancellationFlag::new();
    let mut keys: Vec<String> =
        LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
            .search(
                &Query::Term {
                    field: "title".to_owned(),
                    value: FieldValue::Text(value.to_owned()),
                },
                TopK::new(20).unwrap(),
                &Budgets::new(),
                &cancel,
            )
            .expect("search")
            .hits
            .into_iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
    keys.sort();
    keys
}

async fn create_index(
    env: &Env,
    proxy: &Proxy,
    config: RemoteConfig,
) -> (Arc<S3ObjectStore>, RemoteIndex<S3ObjectStore>) {
    let store = store_through(env, &proxy.endpoint, std::time::Duration::from_secs(10));
    store.create_bucket_if_absent().await.expect("bucket");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    (store, index)
}

/// Run a real-provider async body on a dedicated large-stack thread. The
/// production futures (AWS SDK + staging) are large, so a default test-thread
/// stack must not be assumed.
macro_rules! real_async_test {
    ($name:ident, $body:block) => {
        #[test]
        #[ignore = "requires a running pinned RustFS instance"]
        fn $name() {
            let handle = std::thread::Builder::new()
                .name(stringify!($name).to_owned())
                .stack_size(32 * 1024 * 1024)
                .spawn(|| {
                    let runtime = tokio::runtime::Builder::new_multi_thread()
                        .worker_threads(4)
                        .enable_all()
                        .build()
                        .expect("runtime");
                    runtime.block_on(async $body);
                })
                .expect("spawn");
            handle.join().expect("real test panicked");
        }
    };
}

// H06: one transient 503 on a segment GET is retried by the transfer layer.
real_async_test!(h06_segment_transient_503_is_retried, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h06");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        writer.commit().await.unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "index/segments".to_owned(),
        nth: 1,
        fault: Fault::Return503,
    });
    // Count only requests after the rule is installed (the commit's reference
    // verification uses `head`, which the adapter implements as HEAD + full GET).
    let before = proxy.observed("GET", "index/segments");
    let reader =
        RemoteIndex::open_existing(store, config, schema(), registry(), IndexLimits::default())
            .await
            .expect("retry succeeds");
    assert_eq!(
        query_keys(&reader.snapshot(), "alpha"),
        vec!["a".to_owned()]
    );
    assert_eq!(
        proxy.observed("GET", "index/segments") - before,
        2,
        "one transient then one success"
    );
    proxy.stop().await;
});

// H07: persistent 503 exhausts exactly `max_retries + 1` attempts.
real_async_test!(h07_persistent_503_exhausts_attempts, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h07");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        writer.commit().await.unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "index/segments".to_owned(),
        nth: 0,
        fault: Fault::Return503,
    });
    let before = proxy.observed("GET", "index/segments");
    let started = std::time::Instant::now();
    let error = match RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    {
        Ok(_) => panic!("expected exhausted retries to fail"),
        Err(error) => error,
    };
    let elapsed = started.elapsed();
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected {error:?}"
    );
    assert_eq!(
        proxy.observed("GET", "index/segments") - before,
        3,
        "1 initial + 2 retries"
    );
    // T08: the real timer waits ~100ms + ~200ms (conservative lower bound).
    assert!(
        elapsed >= std::time::Duration::from_millis(250),
        "expected real elapsed backoff >= 250ms, got {elapsed:?}"
    );
    proxy.stop().await;
});

// H10: the CAS applied at RustFS but the response was lost; reconcile succeeds.
real_async_test!(h10_cas_applied_response_dropped_reconciles, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h10");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;

    proxy.add_rule(Rule {
        method: "PUT".to_owned(),
        key_contains: "index/CURRENT".to_owned(),
        nth: 1,
        fault: Fault::ForwardThenDrop,
    });
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        let outcome = writer.commit().await.expect("reconciled publish");
        assert_eq!(outcome.generation, 1);
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let reader =
        RemoteIndex::open_existing(store, config, schema(), registry(), IndexLimits::default())
            .await
            .expect("candidate is authoritative");
    assert_eq!(reader.generation(), Some(1));
    assert_eq!(
        query_keys(&reader.snapshot(), "alpha"),
        vec!["a".to_owned()]
    );
    proxy.stop().await;
});

// H11: the CAS never reaches RustFS and the client times out -> RecoveryRequired.
real_async_test!(h11_cas_blocked_then_timeout_requires_recovery, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h11");
    let store = store_through(&env, &proxy.endpoint, std::time::Duration::from_secs(2));
    store.create_bucket_if_absent().await.expect("bucket");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .unwrap();
    let release = Arc::new(Notify::new());
    proxy.add_rule(Rule {
        method: "PUT".to_owned(),
        key_contains: "index/CURRENT".to_owned(),
        nth: 1,
        fault: Fault::DelayUntil(Arc::clone(&release)),
    });
    let mut writer = index.writer().await.unwrap();
    writer.insert(document("a", "alpha")).unwrap();
    let error = writer.commit().await.unwrap_err();
    assert!(
        matches!(error, IndexError::RecoveryRequired { .. }),
        "unexpected {error:?}"
    );
    // Terminal: further mutations and commits are rejected.
    assert!(writer.insert(document("b", "beta")).is_err());
    assert!(writer.commit().await.is_err());
    release.notify_waiters();
    proxy.stop().await;
    let _ = std::fs::remove_dir_all(config.workspace_root());
});

// H12: two competing writers from the same base through the proxy.
real_async_test!(h12_concurrent_stale_writers_one_winner, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h12");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("base", "base")).unwrap();
        writer.commit().await.unwrap();
    }
    let mut left = index.writer().await.unwrap();
    let mut right = index.writer().await.unwrap();
    left.insert(document("l", "left")).unwrap();
    right.insert(document("r", "right")).unwrap();
    assert_eq!(left.commit().await.unwrap().generation, 2);
    let error = right.commit().await.unwrap_err();
    assert!(
        matches!(error, IndexError::RemoteConflict { .. })
            || matches!(error, IndexError::RecoveryRequired { .. }),
        "unexpected {error:?}"
    );
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let reader =
        RemoteIndex::open_existing(store, config, schema(), registry(), IndexLimits::default())
            .await
            .unwrap();
    assert_eq!(reader.generation(), Some(2));
    proxy.stop().await;
});

// H08: a nontransient 403 is not retried.
real_async_test!(h08_nontransient_403_is_not_retried, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h08");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        writer.commit().await.unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "index/segments".to_owned(),
        nth: 0,
        fault: Fault::ReturnStatus(403),
    });
    let before = proxy.observed("GET", "index/segments");
    let error = match RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    {
        Ok(_) => panic!("expected 403 to fail"),
        Err(error) => error,
    };
    assert!(
        matches!(error, IndexError::Storage(_)),
        "unexpected {error:?}"
    );
    assert_eq!(
        proxy.observed("GET", "index/segments") - before,
        1,
        "nontransient failure must not retry"
    );
    proxy.stop().await;
});

// H09: cancelling a delayed segment GET publishes no final segment.
real_async_test!(h09_cancel_during_delayed_get_publishes_nothing, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let config = remote_config("h09");
    let (store, index) = create_index(&env, &proxy, config.clone()).await;
    {
        let mut writer = index.writer().await.unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        writer.commit().await.unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let release = Arc::new(Notify::new());
    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "index/segments".to_owned(),
        nth: 1,
        fault: Fault::DelayUntil(Arc::clone(&release)),
    });
    let reader_dir = config.reader_dir();
    let timed = tokio::time::timeout(
        std::time::Duration::from_millis(500),
        RemoteIndex::open_existing(store, config, schema(), registry(), IndexLimits::default()),
    )
    .await;
    assert!(timed.is_err(), "hydration must be cancelled by the timeout");
    // The final segment key must never become visible; only a staged temp (if
    // any) may remain under the cache reconciliation grammar.
    let segments = reader_dir.join("index/segments");
    let published = std::fs::read_dir(&segments)
        .map(|entries| entries.count())
        .unwrap_or(0);
    assert_eq!(published, 0, "no final segment after cancellation");
    release.notify_waiters();
    proxy.stop().await;
    let _ = std::fs::remove_dir_all(&reader_dir);
});
