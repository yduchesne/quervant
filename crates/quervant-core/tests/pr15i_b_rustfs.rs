//! PR 15I-B real RustFS acceptance for bounded compressed STORED v2 blocks.
//!
//! `#[ignore]`d by default; requires the pinned RustFS image documented in CI.

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
use quervant_core::index::IndexLimits;
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::segment::format::{FEATURE_STORED_BLOCKS, SectionKind, parse_container};
use quervant_core::segment::{SegmentLimits, SegmentReader};
use quervant_core::storage::{Directory, FsDirectory, StorageKey};
use quervant_objectstore::{S3Config, S3ObjectStore};
use support::{Fault, Proxy, Rule};

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
    assert!(endpoint.starts_with("http://"));
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
        .unwrap_or(endpoint)
        .trim_end_matches('/');
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
    std::env::temp_dir().join(format!("quervant-pr15ib-{}-{name}-{n}", std::process::id()))
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

fn query_keys(snapshot: &quervant_core::index::ReaderSnapshot, value: &str) -> Vec<String> {
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
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
    let mut buffer = vec![0u8; handle.len() as usize];
    let mut offset = 0;
    while offset < buffer.len() {
        let read = handle
            .read_at(offset as u64, &mut buffer[offset..])
            .unwrap();
        assert!(read > 0);
        offset += read;
    }
    buffer
}

fn assert_cached_v2(config: &RemoteConfig) {
    use quervant_core::index::{CURRENT_KEY, CurrentPointer};
    use quervant_core::segment::Manifest;
    let directory = FsDirectory::open(config.reader_dir()).expect("cache");
    let current = read_bytes(&directory, &StorageKey::parse(CURRENT_KEY).unwrap());
    let pointer = CurrentPointer::parse(&current).expect("CURRENT");
    let manifest_bytes = read_bytes(&directory, pointer.manifest_key());
    let manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default()).expect("manifest");
    assert!(!manifest.segments.is_empty());
    for reference in &manifest.segments {
        let bytes = read_bytes(
            &directory,
            &StorageKey::parse(&reference.object_key).expect("segment key"),
        );
        let view = parse_container(&bytes, &SegmentLimits::default()).expect("container");
        assert!(
            view.required_features()
                .contains(&(FEATURE_STORED_BLOCKS, 1))
        );
        assert!(view.body(SectionKind::Stored).is_some());
        let reader = SegmentReader::open(bytes, SegmentLimits::default()).expect("reader");
        assert!(!reader.stored().expect("stored").is_empty());
    }
}

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

real_async_test!(r01_v2_cold_bootstrap_after_workspace_delete, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r01-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r01");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).expect("insert");
        writer.insert(document("b", "beta")).expect("insert");
        writer.commit().await.expect("commit");
    }
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");
    let fresh = remote_config(&prefix, "r01-fresh");
    let reader = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("cold bootstrap");
    assert_eq!(
        query_keys(&reader.snapshot(), "alpha"),
        vec!["a".to_owned()]
    );
    assert_eq!(query_keys(&reader.snapshot(), "beta"), vec!["b".to_owned()]);
    assert_cached_v2(&fresh);
});

real_async_test!(r02_v2_pit_and_compaction_across_generations, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r02-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r02");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    let mut writer = index.writer().await.expect("writer");
    writer.insert(document("a", "one")).expect("insert");
    writer.insert(document("b", "keep")).expect("insert");
    writer.flush().expect("flush");
    writer
        .apply(quervant_core::contract::document::MutationRequest::upsert(
            document("a", "two"),
        ))
        .expect("upsert");
    writer.flush().expect("flush");
    writer.commit().await.expect("commit");
    let pinned = writer.pin().expect("pin");
    let generation = pinned.snapshot().generation();
    assert!(!writer.compact().expect("compact").no_op);
    writer.close().expect("close");
    assert_eq!(pinned.snapshot().generation(), generation);
    assert_eq!(
        query_keys(pinned.snapshot().as_ref(), "two"),
        vec!["a".to_owned()]
    );
    let fresh = remote_config(&prefix, "r02-fresh");
    let reopened = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("reopen");
    assert_eq!(
        query_keys(&reopened.snapshot(), "two"),
        vec!["a".to_owned()]
    );
    assert_eq!(
        query_keys(&reopened.snapshot(), "keep"),
        vec!["b".to_owned()]
    );
    assert_cached_v2(&fresh);
});

real_async_test!(r03_withheld_segment_fails_closed, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let store = proxied_store(&env, &proxy.endpoint);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r03-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r03");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).expect("insert");
        writer.commit().await.expect("commit");
    }
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");
    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "/index/segments/".to_owned(),
        nth: 0,
        fault: Fault::ReturnStatus(404),
    });
    let fresh = remote_config(&prefix, "r03-fresh");
    let error = RemoteIndex::open_existing(
        store,
        fresh,
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await;
    assert!(error.is_err(), "withheld segment must fail closed");
    proxy.stop().await;
});

real_async_test!(r04_failure_before_current_keeps_previous_generation, {
    let env = require_env();
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let store = proxied_store(&env, &proxy.endpoint);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r04-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r04");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    let mut writer = index.writer().await.expect("writer");
    writer.insert(document("a", "one")).expect("insert");
    writer.commit().await.expect("commit");
    proxy.add_rule(Rule {
        method: "PUT".to_owned(),
        key_contains: "/index/CURRENT".to_owned(),
        nth: 0,
        fault: Fault::ReturnStatus(503),
    });
    writer.insert(document("b", "two")).expect("insert");
    assert!(
        writer.commit().await.is_err(),
        "CURRENT failure must be reported"
    );
    writer.close().expect("close");
    let direct = direct_store(&env);
    let fresh = remote_config(&prefix, "r04-fresh");
    let reopened = RemoteIndex::open_existing(
        direct,
        fresh,
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("previous generation remains authoritative");
    assert_eq!(
        query_keys(&reopened.snapshot(), "one"),
        vec!["a".to_owned()]
    );
    assert!(query_keys(&reopened.snapshot(), "two").is_empty());
    proxy.stop().await;
});

real_async_test!(r05_uncached_reader_validates_remote_v2_segment, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r05-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r05");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        for i in 0..300 {
            writer
                .insert(document(&format!("k{i:04}"), &format!("term{i}")))
                .expect("insert");
        }
        writer.commit().await.expect("commit");
    }
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");
    let fresh = remote_config(&prefix, "r05-fresh");
    let _reader = RemoteIndex::open_existing(
        Arc::clone(&store),
        fresh.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("bootstrap");
    // Plain public reader (no metadata budget) uses the fully validating
    // uncached v2 path; the exact cap-0 retained-certificate case is unit-tested.
    let directory = FsDirectory::open(fresh.reader_dir()).expect("cache");
    let keys = directory.list("index/segments", 64).expect("list");
    assert_eq!(keys.len(), 1);
    let bytes = read_bytes(&directory, &keys[0]);
    let reader = SegmentReader::open(bytes, SegmentLimits::default()).expect("reader");
    assert_eq!(reader.stored().expect("stored").len(), 300);
});

real_async_test!(r06_repeated_cold_bootstrap_has_no_stale_certificate, {
    let env = require_env();
    let store = direct_store(&env);
    store.create_bucket_if_absent().await.expect("bucket");
    let prefix = format!("pr15ib/r06-{}-{}", std::process::id(), run_id());
    let config = remote_config(&prefix, "r06");
    let index = RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        AnalyzerRegistry::builtin(),
        IndexLimits::default(),
    )
    .await
    .expect("create");
    {
        let mut writer = index.writer().await.expect("writer");
        writer.insert(document("a", "alpha")).expect("insert");
        writer.commit().await.expect("commit");
    }
    std::fs::remove_dir_all(config.workspace_root()).expect("drop workspace");
    for attempt in 0..10 {
        let fresh = remote_config(&prefix, &format!("r06-fresh-{attempt}"));
        let reader = RemoteIndex::open_existing(
            Arc::clone(&store),
            fresh.clone(),
            schema(),
            AnalyzerRegistry::builtin(),
            IndexLimits::default(),
        )
        .await
        .unwrap_or_else(|error| panic!("bootstrap {attempt}: {error:?}"));
        assert_eq!(
            query_keys(&reader.snapshot(), "alpha"),
            vec!["a".to_owned()]
        );
        assert_cached_v2(&fresh);
    }
});
