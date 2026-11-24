//! PR 13 remote-backed index integration tests.
//!
//! Fake-object-store tests run by default and exercise the full remote
//! publication/read lifecycle with a deterministic provider. Real RustFS tests
//! are `#[ignore]`d and require the documented environment; a skipped run is
//! not provider acceptance evidence.
//!
//! ```sh
//! QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
//! QUERVANT_RUSTFS_BUCKET=quervant-pr13-core \
//! QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
//! QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
//! cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1
//! ```

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::{Directory, MemoryDirectory};
use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

static DIRS: AtomicU64 = AtomicU64::new(0);

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

fn temp_workspace(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-pr13-{}-{name}-{n}", std::process::id()))
}

/// A per-process run identifier so repeated runs against a persistent RustFS
/// instance never reuse prefixes.
fn run_id() -> u128 {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!("pr13/{name}-{}-{}", std::process::id(), run_id())).unwrap(),
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

fn remote_fake() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

fn query(snapshot: &ReaderSnapshot, value: &str) -> Vec<String> {
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

#[cfg(feature = "s3")]
fn phrase_query(snapshot: &ReaderSnapshot, terms: &[&str]) -> Vec<String> {
    let schema = schema();
    let registry = registry();
    let cancel = CancellationFlag::new();
    let mut keys: Vec<String> =
        LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
            .search(
                &Query::Phrase {
                    field: "title".to_owned(),
                    terms: terms.iter().map(|term| (*term).to_owned()).collect(),
                },
                TopK::new(20).unwrap(),
                &Budgets::new(),
                &cancel,
            )
            .expect("phrase search")
            .hits
            .into_iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
    keys.sort();
    keys
}

#[cfg(feature = "s3")]
fn query_total(snapshot: &ReaderSnapshot, value: &str) -> u64 {
    let schema = schema();
    let registry = registry();
    let cancel = CancellationFlag::new();
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
        .total_hits
}

fn local_snapshot(docs: &[(&str, &str)]) -> Arc<ReaderSnapshot> {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(directory, schema(), registry(), IndexLimits::default()).unwrap();
    let mut writer = index.writer().unwrap();
    for (key, title) in docs {
        writer.insert(document(key, title)).unwrap();
    }
    writer.commit().unwrap();
    writer.reader()
}

#[test]
fn v01_lexical_results_match_local_oracle() {
    let store = remote_fake();
    let config = remote_config("v01");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "alpha beta")).unwrap();
        writer.insert(document("b", "beta gamma")).unwrap();
        writer.insert(document("c", "alpha gamma")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let remote = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let oracle = local_snapshot(&[
        ("a", "alpha beta"),
        ("b", "beta gamma"),
        ("c", "alpha gamma"),
    ]);
    // I08/R03: scoring performs no remote GET once the generation is open.
    store.reset_counters();
    for term in ["alpha", "beta", "gamma", "missing"] {
        assert_eq!(
            query(&remote.snapshot(), term),
            query(&oracle, term),
            "term {term}"
        );
    }
    assert_eq!(store.get_calls(), 0, "no remote GET during scoring");
    let _ = std::fs::remove_dir_all(&workspace);
}

#[test]
fn r01_cold_open_from_remote_after_workspace_delete() {
    let store = remote_fake();
    let config = remote_config("r01");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    // Delete all disposable local state, then recover only from the provider.
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let reader = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(reader.generation(), Some(1));
    assert_eq!(query(&reader.snapshot(), "alpha"), vec!["a".to_owned()]);
    assert_eq!(
        store.delete_calls(),
        0,
        "cache eviction never deletes remote"
    );
    let _ = std::fs::remove_dir_all(&workspace);
}

#[test]
fn r04_old_pit_observes_its_generation() {
    let store = remote_fake();
    let config = remote_config("r04");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let reader_v1 = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let pit = reader_v1.pin().unwrap();
    {
        let mut writer = block_on(reader_v1.writer()).unwrap();
        writer.insert(document("b", "alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let reader_v2 = block_on(RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(query(pit.snapshot(), "alpha"), vec!["a".to_owned()]);
    assert_eq!(
        query(&reader_v2.snapshot(), "alpha"),
        vec!["a".to_owned(), "b".to_owned()]
    );
    let _ = std::fs::remove_dir_all(&workspace);
}

#[test]
fn v06_upsert_delete_reopen_has_no_resurrection() {
    let store = remote_fake();
    let config = remote_config("v06");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer
            .apply(quervant_core::contract::document::MutationRequest::upsert(
                document("a", "beta"),
            ))
            .unwrap();
        block_on(writer.commit()).unwrap();
    }
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer
            .apply(quervant_core::contract::document::MutationRequest::delete(
                DocumentKey::new("a").unwrap(),
            ))
            .unwrap();
        block_on(writer.commit()).unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let reader = block_on(RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert!(query(&reader.snapshot(), "alpha").is_empty());
    assert!(query(&reader.snapshot(), "beta").is_empty());
    let _ = std::fs::remove_dir_all(&workspace);
}

#[test]
fn r07_concurrent_readers_observe_one_complete_generation() {
    let store = remote_fake();
    let config = remote_config("r07");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let first = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let second = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(first.generation(), Some(1));
    assert_eq!(second.generation(), Some(1));
    assert_eq!(query(&first.snapshot(), "alpha"), vec!["a".to_owned()]);
    assert_eq!(query(&second.snapshot(), "alpha"), vec!["a".to_owned()]);
    let _ = std::fs::remove_dir_all(&workspace);
}

// ---------------------------------------------------------------------------
// Real RustFS acceptance (ignored by default).
// ---------------------------------------------------------------------------

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn require_env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        assert!(
            !endpoint.trim().is_empty(),
            "QUERVANT_RUSTFS_ENDPOINT must not be empty"
        );
        assert!(
            !bucket.trim().is_empty(),
            "QUERVANT_RUSTFS_BUCKET must not be empty"
        );
        assert!(
            !access.trim().is_empty(),
            "QUERVANT_RUSTFS_ACCESS_KEY must not be empty"
        );
        assert!(
            !secret.trim().is_empty(),
            "QUERVANT_RUSTFS_SECRET_KEY must not be empty"
        );
        assert!(
            endpoint.starts_with("http://"),
            "real RustFS acceptance requires an http:// endpoint"
        );
        (endpoint, bucket, access, secret, region)
    }

    /// Run a real RustFS async body on a dedicated large-stack thread with a
    /// current-thread Tokio runtime. The AWS SDK request futures are large, so
    /// a default test-thread stack must not be assumed.
    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("pr13-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("tokio runtime");
                runtime.block_on(body);
            })
            .expect("spawn");
        handle.join().expect("real RustFS test panicked");
    }

    async fn real_index(
        name: &str,
    ) -> (Arc<S3ObjectStore>, RemoteConfig, RemoteIndex<S3ObjectStore>) {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("valid config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");
        let config = remote_config(name);
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("create");
        (store, config, index)
    }

    /// PERF-06-A3 requires the *persisted* format to survive the real remote
    /// path: a split-postings segment is written, committed, materialized from an
    /// empty local cache, and queried again after every disposable local byte is
    /// removed. Logical results only; no timing claim.
    ///
    /// The `RemoteIndex` handle returned by `real_index` snapshots the generation
    /// observed at *open* time (before this commit), so every query below uses a
    /// reader opened after the commit. The pre-delete state is the committed
    /// generation itself; the assertions derive expectations from the fixture
    /// input, not from engine output.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn a3_r01_split_postings_rustfs_cold_reopen() {
        run(async {
            let (store, config, index) = real_index("perf06-a3-split").await;
            {
                let mut writer = index.writer().await.unwrap();
                writer.insert(document("a", "alpha beta")).unwrap();
                writer.insert(document("b", "alpha gamma")).unwrap();
                writer.insert(document("c", "beta")).unwrap();
                let outcome = writer.commit().await.unwrap();
                assert_eq!(outcome.generation, 1);
            }
            drop(index);

            // Cold reader: remove only the disposable local workspace, keep the
            // durable remote objects authoritative.
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
            assert_eq!(reader.generation(), Some(1));
            let cold = reader.snapshot();
            assert_eq!(query(&cold, "alpha"), vec!["a".to_owned(), "b".to_owned()]);
            assert_eq!(query(&cold, "beta"), vec!["a".to_owned(), "c".to_owned()]);
            assert_eq!(
                phrase_query(&cold, &["alpha", "beta"]),
                vec!["a".to_owned()]
            );
            drop(cold);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn rustfs_write_cold_open_query_and_restart() {
        run(async {
            let (store, config, index) = real_index("rustfs-slice").await;
            {
                let mut writer = index.writer().await.unwrap();
                writer.insert(document("a", "alpha beta")).unwrap();
                writer.insert(document("b", "gamma")).unwrap();
                let outcome = writer.commit().await.unwrap();
                assert_eq!(outcome.generation, 1);
            }
            // Cold restart: remove every disposable local byte, recover from RustFS.
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
            assert_eq!(reader.generation(), Some(1));
            assert_eq!(query(&reader.snapshot(), "alpha"), vec!["a".to_owned()]);
            assert_eq!(query(&reader.snapshot(), "gamma"), vec!["b".to_owned()]);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn rustfs_ranged_segment_transfer_matches_whole() {
        run(async {
            let (store, config, index) = real_index("rustfs-ranged").await;
            {
                let mut writer = index.writer().await.unwrap();
                for i in 0..200 {
                    writer
                        .insert(document(&format!("d{i:03}"), "range payload alpha"))
                        .unwrap();
                }
                writer.commit().await.unwrap();
            }
            // Force ranged transfer by lowering the threshold below the segment size.
            let ranged = config.clone().with_transfer(
                RemoteTransferConfig::default()
                    .with_range_threshold(1)
                    .with_chunk_size(1024)
                    .with_max_aggregate_response_bytes(1024 * 1024)
                    .with_max_total_http_requests(64)
                    .with_max_concurrent_ranges(8),
            );
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                store,
                ranged,
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(1));
            assert_eq!(query_total(&reader.snapshot(), "alpha"), 200);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn rustfs_stale_writer_cannot_overwrite_current() {
        run(async {
            let (store, config, index) = real_index("rustfs-cas").await;
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
                matches!(
                    error,
                    quervant_core::index::IndexError::RemoteConflict { .. }
                ) || matches!(
                    error,
                    quervant_core::index::IndexError::RecoveryRequired { .. }
                )
            );
            let _ = std::fs::remove_dir_all(config.workspace_root());
            let _ = &store;
        });
    }

    /// Adaptive postings feature id (PERF-06-A5).
    const A5_FEATURE_ADAPTIVE: u16 = 0x000F;
    /// Retained A3 split postings feature id.
    const A5_FEATURE_SPLIT: u16 = 0x000E;

    /// `(marker, doc_freq)` of the first posting payload for `(field, term)`.
    fn a5_marker(
        reader: &quervant_core::segment::SegmentReader,
        field: &str,
        term: &str,
    ) -> (u8, u64) {
        use quervant_core::segment::{SectionKind, SegmentLimits, parse_container};
        let field_id = reader.schema().field_id(field).expect("field");
        let entry = reader
            .dictionary()
            .expect("dictionary")
            .lookup(field_id, term)
            .expect("term");
        let view = parse_container(reader.bytes(), &SegmentLimits::default()).expect("container");
        let body = view.body(SectionKind::Postings).expect("postings body");
        (body[entry.postings_offset as usize], entry.doc_freq)
    }

    /// Full (untruncated) total and sorted keys for one query.
    fn a5_search(snapshot: &ReaderSnapshot, query: Query) -> (u64, Vec<String>) {
        let schema = schema();
        let registry = registry();
        let cancel = CancellationFlag::new();
        let response = LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
            .search(&query, TopK::new(300).unwrap(), &Budgets::new(), &cancel)
            .expect("search");
        let mut keys: Vec<String> = response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
        keys.sort();
        (response.total_hits, keys)
    }

    fn a5_term(value: &str) -> Query {
        Query::Term {
            field: "title".to_owned(),
            value: FieldValue::Text(value.to_owned()),
        }
    }

    fn a5_group_of(ordinal: usize) -> &'static str {
        match ordinal {
            0 => "singleton",
            1..=128 => "short",
            _ => "long",
        }
    }

    fn a5_title(ordinal: usize) -> String {
        let group = a5_group_of(ordinal);
        if ordinal % 4 != 0 {
            format!("{group} alpha beta")
        } else {
            format!("{group} alpha gamma")
        }
    }

    fn a5_expected_keys(
        range: std::ops::RangeInclusive<usize>,
        keep: impl Fn(usize) -> bool,
    ) -> Vec<String> {
        let mut keys: Vec<String> = range
            .filter(|ordinal| keep(*ordinal))
            .map(|ordinal| format!("a5-{ordinal:03}"))
            .collect();
        keys.sort();
        keys
    }

    /// Inspect the single committed adaptive segment outside the async body so no
    /// non-`Send` guarded reader is held across an await.
    fn a5_assert_single_adaptive_segment(snapshot: &ReaderSnapshot) {
        assert_eq!(snapshot.segment_count(), 1);
        let guard = snapshot.open_segment_reader(0).expect("segment reader");
        let required: Vec<u16> = guard
            .reader()
            .required_features()
            .iter()
            .map(|(id, _)| *id)
            .collect();
        assert!(required.contains(&A5_FEATURE_ADAPTIVE));
        assert!(!required.contains(&A5_FEATURE_SPLIT));
        assert_eq!(a5_marker(guard.reader(), "title", "singleton"), (5, 1));
        assert_eq!(a5_marker(guard.reader(), "title", "short"), (7, 128));
        assert_eq!(a5_marker(guard.reader(), "title", "long"), (3, 130));
    }

    /// PERF-06-A5 real remote acceptance: adaptive postings survive commit, a
    /// fresh remote open and a fully cold reader with no writer-local state.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn a5_r01_adaptive_postings_rustfs_cold_reopen() {
        run(async {
            let (store, config, index) = real_index("perf06-a5-adaptive").await;
            {
                let mut writer = index.writer().await.unwrap();
                for ordinal in 0..259usize {
                    writer
                        .insert(document(&format!("a5-{ordinal:03}"), &a5_title(ordinal)))
                        .unwrap();
                }
                let outcome = writer.commit().await.unwrap();
                assert_eq!(outcome.generation, 1);
            }
            // The pre-commit handle observed the generation at creation; drop it
            // without inspecting it as if the commit had refreshed it.
            drop(index);

            let reopened = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reopened.generation(), Some(1));
            {
                let warm = reopened.snapshot();
                a5_assert_single_adaptive_segment(&warm);
            }
            drop(reopened);

            // Remove only this disposable configuration's local workspace, then
            // rebuild every reader from the authoritative remote store.
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let cold_index = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(cold_index.generation(), Some(1));
            let snapshot = cold_index.snapshot();
            a5_assert_single_adaptive_segment(&snapshot);

            assert_eq!(
                a5_search(&snapshot, a5_term("singleton")),
                (1, vec!["a5-000".to_owned()])
            );
            assert_eq!(
                a5_search(&snapshot, a5_term("short")),
                (128, a5_expected_keys(1..=128, |_| true))
            );
            assert_eq!(
                a5_search(&snapshot, a5_term("long")),
                (130, a5_expected_keys(129..=258, |_| true))
            );
            assert_eq!(
                a5_search(&snapshot, a5_term("alpha")),
                (259, a5_expected_keys(0..=258, |_| true))
            );
            assert_eq!(
                a5_search(&snapshot, a5_term("beta")),
                (194, a5_expected_keys(0..=258, |ordinal| ordinal % 4 != 0))
            );
            assert_eq!(
                a5_search(&snapshot, a5_term("gamma")),
                (65, a5_expected_keys(0..=258, |ordinal| ordinal % 4 == 0))
            );
            assert_eq!(a5_search(&snapshot, a5_term("absent_a5")), (0, Vec::new()));
            assert_eq!(
                a5_search(
                    &snapshot,
                    Query::Phrase {
                        field: "title".to_owned(),
                        terms: vec!["alpha".to_owned(), "beta".to_owned()],
                    }
                ),
                (194, a5_expected_keys(0..=258, |ordinal| ordinal % 4 != 0))
            );

            drop(snapshot);
            drop(cold_index);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }
}
