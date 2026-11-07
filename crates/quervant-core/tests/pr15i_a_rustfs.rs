//! PR 15I-A real RustFS acceptance for the compact mutation-state payload V3.
//!
//! These tests are `#[ignore]`d by default and require the documented pinned
//! RustFS service. A skipped run is **not** provider acceptance evidence.
//!
//! ```sh
//! QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
//! QUERVANT_RUSTFS_BUCKET=quervant-pr15ia-core \
//! QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
//! QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
//! cargo test -p quervant-core --all-features --test pr15i_a_rustfs -- --ignored --test-threads=1
//! ```

#![cfg(feature = "s3")]

#[path = "../../quervant-objectstore/tests/support/mod.rs"]
mod support;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey,
};
use quervant_core::contract::mutation::{
    MutationAction, MutationBatch, MutationCommand, MutationTarget,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::segment::format::{SectionKind, parse_container};
use quervant_core::segment::{Manifest, SegmentLimits};
use quervant_core::storage::{Directory, FsDirectory, StorageKey};
use quervant_objectstore::{S3Config, S3ObjectStore};
use support::{Fault, Proxy, Rule};

static DIRS: AtomicU64 = AtomicU64::new(0);

const V3_VERSION: u16 = 3;

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
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn temp_path(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-pr15ia-{}-{name}-{n}", std::process::id()))
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
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
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
        .insert("n", FieldValues::Single(FieldValue::I64(1)))
        .unwrap();
    document
}

fn remote_config(prefix: &str, name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(prefix).expect("prefix"),
        temp_path(name),
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

fn direct_store(env: &Env) -> Arc<S3ObjectStore> {
    Arc::new(
        S3ObjectStore::new(S3Config::rustfs(
            env.endpoint.clone(),
            env.region.clone(),
            env.bucket.clone(),
            env.access_key.clone(),
            env.secret_key.clone(),
        ))
        .expect("valid RustFS config"),
    )
}

fn proxied_store(env: &Env, endpoint: &str) -> Arc<S3ObjectStore> {
    Arc::new(
        S3ObjectStore::new(
            S3Config::rustfs(
                endpoint.to_owned(),
                env.region.clone(),
                env.bucket.clone(),
                env.access_key.clone(),
                env.secret_key.clone(),
            )
            .with_timeouts(
                std::time::Duration::from_secs(5),
                std::time::Duration::from_secs(5),
            ),
        )
        .expect("valid proxy config"),
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

fn read_bytes(directory: &dyn Directory, key: &StorageKey) -> Vec<u8> {
    let handle = directory.open_read(key).expect("open read");
    let len = handle.len() as usize;
    let mut buffer = vec![0u8; len];
    let mut offset = 0;
    while offset < len {
        let read = handle
            .read_at(offset as u64, &mut buffer[offset..])
            .unwrap();
        assert!(read > 0);
        offset += read;
    }
    buffer
}

/// Read the committed payload version from the reader's materialized cache.
fn cached_payload_version(config: &RemoteConfig) -> u16 {
    let directory = FsDirectory::open(config.reader_dir()).expect("reader cache");
    let current = read_bytes(
        &directory,
        &StorageKey::parse(quervant_core::index::CURRENT_KEY).unwrap(),
    );
    let pointer = quervant_core::index::CurrentPointer::parse(&current).expect("CURRENT");
    let manifest_bytes = read_bytes(&directory, pointer.manifest_key());
    let manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default()).expect("manifest");
    let reference = manifest.mutation_state.expect("sidecar");
    let sidecar = read_bytes(
        &directory,
        &StorageKey::parse(&reference.object_key).unwrap(),
    );
    let view = parse_container(&sidecar, &SegmentLimits::default()).expect("container");
    let body = view
        .body(SectionKind::MutationState)
        .expect("mutation-state section");
    u16::from_le_bytes([body[0], body[1]])
}

/// Run a real-provider async body on a dedicated large-stack thread with a
/// current-thread runtime, matching the existing PR 13 harness.
macro_rules! real_async_test {
    ($name:ident, $body:block) => {
        #[test]
        #[ignore = "requires a running pinned RustFS instance"]
        fn $name() {
            let handle = std::thread::Builder::new()
                .name(stringify!($name).to_owned())
                .stack_size(32 * 1024 * 1024)
                .spawn(|| {
                    let runtime = tokio::runtime::Builder::new_current_thread()
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

// R01: a V3 generation cold-bootstraps from RustFS with an empty workspace.
real_async_test!(r01_v3_cold_bootstrap_after_workspace_delete, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ia/r01-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r01");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).expect("insert");
        writer.insert(document("b", "beta")).expect("insert");
        writer.flush().expect("flush");
        writer
            .apply(quervant_core::contract::document::MutationRequest::upsert(
                document("a", "alpha two"),
            ))
            .expect("upsert");
        writer.commit().await.expect("commit");
    }
    // Discard every disposable local cache/workspace object.
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");

    let fresh = remote_config(&prefix, "r01-fresh");
    assert!(!fresh.reader_dir().exists(), "fresh cache must be empty");
    let reader = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("cold bootstrap");
    assert_eq!(
        query_keys(&reader.snapshot(), "alpha"),
        vec!["a".to_owned()]
    );
    assert_eq!(query_keys(&reader.snapshot(), "beta"), vec!["b".to_owned()]);
    assert_eq!(cached_payload_version(&fresh), V3_VERSION);
});

// R02: a tokened V3 batch replays exactly after a remote restart.
real_async_test!(r02_v3_batch_replay_after_restart, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ia/r02-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r02");
    let token = IdempotencyKey::new("pr15ia-remote-batch").expect("token");
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(DocumentKey::new("a").expect("key")),
        MutationAction::Insert(document("a", "alpha")),
    )])
    .with_idempotency_key(token.clone());
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        let applied = writer
            .apply_batch(&batch, &CancellationFlag::new())
            .expect("batch");
        assert!(!applied.replayed);
        writer.commit().await.expect("commit");
    }
    drop(index);
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");

    let fresh = remote_config(&prefix, "r02-fresh");
    let reopened = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("reopen");
    assert_eq!(
        query_keys(&reopened.snapshot(), "alpha"),
        vec!["a".to_owned()]
    );
    assert_eq!(cached_payload_version(&fresh), V3_VERSION);
    let mut writer = reopened.writer().await.expect("writer");
    let replayed = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("replay");
    assert!(replayed.replayed);
    assert!(
        replayed
            .outcomes
            .iter()
            .flat_map(|command| command.keys.iter())
            .all(|outcome| outcome.replayed)
    );
    assert_eq!(replayed.outcomes[0].keys[0].key.as_str(), "a");
});

// R03: remote compaction rewrites V3 and leaves a pinned generation untouched.
real_async_test!(r03_v3_compaction_and_pit, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ia/r03-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r03");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    let mut writer = index.writer().await.expect("writer");
    writer.insert(document("a", "old")).expect("insert");
    writer.insert(document("b", "keep")).expect("insert");
    writer.flush().expect("flush");
    writer
        .apply(quervant_core::contract::document::MutationRequest::upsert(
            document("a", "new"),
        ))
        .expect("upsert");
    writer.flush().expect("flush");
    writer.commit().await.expect("commit");
    // Pin the writer's committed generation, not the stale opener handle.
    let pinned = writer.pin().expect("pin");
    let pinned_generation = pinned.snapshot().generation();
    assert!(
        pinned_generation.is_some(),
        "pinned generation must be committed"
    );
    let outcome = writer.compact().expect("compact");
    assert!(!outcome.no_op);
    writer.close().expect("close");

    // The pinned reader still sees its generation and the superseded document.
    assert_eq!(pinned.snapshot().generation(), pinned_generation);
    assert_eq!(
        query_keys(pinned.snapshot().as_ref(), "new"),
        vec!["a".to_owned()]
    );
    assert!(query_keys(pinned.snapshot().as_ref(), "old").is_empty());

    let fresh = remote_config(&prefix, "r03-fresh");
    let reopened = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("reopen");
    assert_eq!(
        query_keys(&reopened.snapshot(), "new"),
        vec!["a".to_owned()]
    );
    assert_eq!(
        query_keys(&reopened.snapshot(), "keep"),
        vec!["b".to_owned()]
    );
    assert!(query_keys(&reopened.snapshot(), "old").is_empty());
    assert_eq!(cached_payload_version(&fresh), V3_VERSION);
});

// R04: withholding the authoritative sidecar fails closed with no fallback.
real_async_test!(r04_v3_missing_sidecar_fails_closed, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let store = proxied_store(&env, &proxy.endpoint);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ia/r04-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r04");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).expect("insert");
        writer.commit().await.expect("commit");
    }
    drop(index);
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");

    // Withhold the state object only; the authoritative object is not deleted.
    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "/index/state/".to_owned(),
        nth: 0,
        fault: Fault::ReturnStatus(404),
    });
    let fresh = remote_config(&prefix, "r04-fresh");
    let message = match RemoteIndex::open_existing(
        store,
        fresh,
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .await
    {
        Ok(_) => panic!("missing sidecar must fail closed"),
        Err(error) => format!("{error:?}"),
    };
    assert!(
        message.contains("NotFound")
            || message.contains("Storage")
            || message.contains("Integrity")
            || message.contains("Corrupt"),
        "unexpected error: {message}"
    );
    proxy.stop().await;
});
