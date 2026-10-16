//! K01–K04: separate-process crash-at-checkpoint recovery against real RustFS.
//!
//! The parent starts the deterministic fault proxy, which blocks the child's
//! publication at a named checkpoint. The parent then `SIGKILL`s the child and
//! reopens the index from RustFS in a fresh workspace. `K05` (mid-ranged-download
//! crash) is exercised in-process by H02/H09; `K06` (cancelled commit) by H11.
//!
//! `#[ignore]`d by default. The child is this same test binary re-invoked with
//! `QUERVANT_PR13_CHILD=1`.

#![cfg(feature = "s3")]

#[path = "../../quervant-objectstore/tests/support/mod.rs"]
mod support;

use std::sync::Arc;
use std::time::{Duration, Instant};

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{IndexError, IndexLimits};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_objectstore::{S3Config, S3ObjectStore};
use support::{Fault, Proxy, Rule};

#[derive(Clone)]
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
    std::env::temp_dir().join(format!(
        "quervant-crash-{}-{name}-{}",
        std::process::id(),
        run_id()
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

fn limits() -> IndexLimits {
    IndexLimits::default()
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

fn store(env: &Env, endpoint: &str, request_timeout: Duration) -> Arc<S3ObjectStore> {
    Arc::new(
        S3ObjectStore::new(
            S3Config::rustfs(
                endpoint.to_owned(),
                env.region.clone(),
                env.bucket.clone(),
                env.access_key.clone(),
                env.secret_key.clone(),
            )
            .with_timeouts(Duration::from_secs(5), request_timeout),
        )
        .expect("config"),
    )
}

fn transfer() -> RemoteTransferConfig {
    RemoteTransferConfig::default()
        .with_range_threshold(256 * 1024)
        .with_chunk_size(32 * 1024)
        .with_max_aggregate_response_bytes(2 * 1024 * 1024)
        .with_max_total_http_requests(64)
        .with_max_concurrent_ranges(16)
}

fn run(body: impl std::future::Future<Output = ()> + Send + 'static) {
    let handle = std::thread::Builder::new()
        .stack_size(32 * 1024 * 1024)
        .spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("runtime");
            runtime.block_on(body);
        })
        .expect("spawn");
    handle.join().expect("crash test panicked");
}

/// Child-process entrypoint: perform one real remote commit that the proxy
/// blocks at a checkpoint. Invoked only via `--ignored --exact child_entrypoint`.
#[test]
#[ignore = "internal child entrypoint for the crash harness"]
fn child_entrypoint() {
    if std::env::var("QUERVANT_PR13_CHILD").is_err() {
        return;
    }
    let proxy_endpoint = std::env::var("QUERVANT_PR13_PROXY_ENDPOINT").expect("proxy endpoint");
    let prefix = std::env::var("QUERVANT_PR13_PREFIX").expect("prefix");
    let workspace = std::env::var("QUERVANT_PR13_WORKSPACE").expect("workspace");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").expect("bucket");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").expect("access");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").expect("secret");
    run(async move {
        let store = Arc::new(
            S3ObjectStore::new(
                S3Config::rustfs(proxy_endpoint, region, bucket, access, secret)
                    .with_timeouts(Duration::from_secs(5), Duration::from_secs(60)),
            )
            .expect("config"),
        );
        let config = RemoteConfig::new(
            RemoteKeyPrefix::parse(prefix).unwrap(),
            std::path::PathBuf::from(workspace),
        )
        .with_transfer(transfer());
        let index = RemoteIndex::create(store, config, schema(), registry(), limits())
            .await
            .expect("create");
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).unwrap();
        // Blocks at the proxy checkpoint; the parent kills this process.
        let _ = writer.commit().await;
        eprintln!("child unexpectedly completed commit");
    });
}

async fn checkpoint_scenario(
    env: &Env,
    name: &str,
    rule_key: &str,
    fault: Fault,
    expect_generation: Option<u64>,
) {
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let prefix = format!("crash/{name}-{}-{}", std::process::id(), run_id());
    let child_workspace = temp_workspace(&format!("{name}-child"));

    // Ensure the bucket exists before the child starts.
    store(env, &proxy.endpoint, Duration::from_secs(10))
        .create_bucket_if_absent()
        .await
        .expect("bucket");

    proxy.add_rule(Rule {
        method: "PUT".to_owned(),
        key_contains: rule_key.to_owned(),
        nth: 1,
        fault,
    });

    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--ignored",
            "--exact",
            "child_entrypoint",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("QUERVANT_PR13_CHILD", "1")
        .env("QUERVANT_PR13_PROXY_ENDPOINT", &proxy.endpoint)
        .env("QUERVANT_PR13_PREFIX", &prefix)
        .env("QUERVANT_PR13_WORKSPACE", &child_workspace)
        .env("QUERVANT_RUSTFS_BUCKET", &env.bucket)
        .env("QUERVANT_RUSTFS_ACCESS_KEY", &env.access_key)
        .env("QUERVANT_RUSTFS_SECRET_KEY", &env.secret_key)
        .env("QUERVANT_RUSTFS_REGION", &env.region)
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .spawn()
        .expect("spawn child");

    let deadline = Instant::now() + Duration::from_secs(30);
    while !proxy.checkpoint_hit(name) {
        if Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("checkpoint {name} was not reached");
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    // Forced OS termination at the checkpoint.
    child.kill().expect("kill child");
    let status = child.wait().expect("wait child");
    assert!(!status.success(), "child must be force-terminated");

    // Reopen from RustFS in a fresh workspace (the parent is a new process
    // relative to the killed child).
    let store = store(env, &proxy.endpoint, Duration::from_secs(30));
    let config = RemoteConfig::new(
        RemoteKeyPrefix::parse(prefix).unwrap(),
        temp_workspace(&format!("{name}-parent")),
    )
    .with_transfer(transfer());
    let result = RemoteIndex::open_existing(store, config, schema(), registry(), limits()).await;
    match expect_generation {
        Some(generation) => {
            let reader = result.expect("new generation must open");
            assert_eq!(reader.generation(), Some(generation), "K={name}");
        }
        None => assert!(
            matches!(result, Err(IndexError::NotInitialized)),
            "K={name} expected no committed CURRENT"
        ),
    }
    proxy.stop().await;
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn k01_crash_after_segment_before_state() {
    run(async {
        let Some(env) = env() else {
            return;
        };
        checkpoint_scenario(
            &env,
            "k01",
            "index/state",
            Fault::BlockBeforeCheckpoint("k01".to_owned()),
            None,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn k02_crash_after_state_before_manifest() {
    run(async {
        let Some(env) = env() else {
            return;
        };
        checkpoint_scenario(
            &env,
            "k02",
            "index/manifests",
            Fault::BlockBeforeCheckpoint("k02".to_owned()),
            None,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn k03_crash_after_manifest_before_current() {
    run(async {
        let Some(env) = env() else {
            return;
        };
        checkpoint_scenario(
            &env,
            "k03",
            "index/CURRENT",
            Fault::BlockBeforeCheckpoint("k03".to_owned()),
            None,
        )
        .await;
    });
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn k04_crash_after_cas_before_ack() {
    run(async {
        let Some(env) = env() else {
            return;
        };
        checkpoint_scenario(
            &env,
            "k04",
            "index/CURRENT",
            Fault::ForwardThenCheckpoint("k04".to_owned()),
            Some(1),
        )
        .await;
    });
}
