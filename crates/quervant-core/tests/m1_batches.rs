//! M1 atomic explicit-key mutation batch integration tests (QMA-001 / M1).
//!
//! Verticals covered here:
//!
//! * `M1-V01` in-memory full slice (pre/post-refresh readers, pinned PITs,
//!   commit, reopen, exact replay).
//! * `M1-V02` real local filesystem slice (flush + restart + old generation).
//! * `M1-V03` remote fake slice (`RemoteIndexWriter::apply_batch`, remote
//!   publication only on `commit`, upload fault, CAS conflict).
//! * `M1-V04` real RustFS slice (ignored; requires the documented environment).
//!
//! `M1-V05` (baseline binary opening an upgraded v2 index) requires a compiled
//! baseline binary and is recorded as BLOCKED in
//! `docs/pr-artifacts/m1/implementation-evidence.md`; the in-repo feature-gate
//! evidence is exercised by the unit fixture tests instead.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey,
};
use quervant_core::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationBatchResponse, MutationCommand,
    MutationCommandOutcome, MutationKeyOutcome, MutationRejection, MutationTarget,
    QueryMutationSelector,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexError, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};
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

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).unwrap()
}

fn temp_path(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-m1-{}-{name}-{n}", std::process::id()))
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

fn summary(response: &MutationCommandOutcome) -> (u64, Vec<(String, Option<u64>)>) {
    (
        response.matched,
        response
            .keys
            .iter()
            .map(|outcome: &MutationKeyOutcome| (outcome.key.as_str().to_owned(), outcome.revision))
            .collect(),
    )
}

fn batch_of(commands: Vec<MutationCommand>, token: &str) -> MutationBatch {
    MutationBatch::new(commands).with_idempotency_key(IdempotencyKey::new(token).unwrap())
}

// ---------------------------------------------------------------------------
// M1-V01 — in-memory vertical slice
// ---------------------------------------------------------------------------

#[test]
fn m1_v01_memory_vertical_slice() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .insert(document("seed", "seed alpha"))
        .expect("seed insert");
    writer.commit().unwrap();

    // The pre-batch reader.
    let before = writer.reader();
    assert_eq!(query_keys(&before, "beta"), Vec::<String>::new());

    let batch = batch_of(
        vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "alpha beta")),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Insert(document("b", "beta gamma")),
            ),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("seed"), key("ghost")]),
                MutationAction::Delete,
            ),
        ],
        "v01-batch",
    );
    let cancel = CancellationFlag::new();
    let response = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(response.outcomes.len(), 3);
    assert_eq!(
        summary(&response.outcomes[0]),
        (1, vec![("a".into(), Some(1))])
    );
    assert_eq!(
        summary(&response.outcomes[1]),
        (1, vec![("b".into(), Some(1))])
    );
    assert_eq!(
        summary(&response.outcomes[2]),
        (2, vec![("ghost".into(), Some(1)), ("seed".into(), Some(2))]),
        "Keys delete processes first occurrence but reports ascending keys"
    );
    assert!(!response.replayed);

    // Before refresh, the previously published reader is unchanged.
    assert_eq!(query_keys(&before, "beta"), Vec::<String>::new());
    assert_eq!(query_keys(&before, "alpha"), vec!["seed".to_owned()]);
    // `writer.reader()` still returns the previously published snapshot.
    assert_eq!(query_keys(&writer.reader(), "beta"), Vec::<String>::new());

    let refreshed = writer.refresh().unwrap();
    assert_eq!(
        query_keys(&refreshed, "beta"),
        vec!["a".to_owned(), "b".to_owned()]
    );
    assert_eq!(query_keys(&refreshed, "alpha"), vec!["a".to_owned()]);

    // Pin before commit: the pinned PIT must not follow later generations.
    let pinned = writer.pin().unwrap();
    writer.commit().unwrap();
    assert_eq!(
        query_keys(&writer.reader(), "beta"),
        vec!["a".to_owned(), "b".to_owned()]
    );
    assert_eq!(
        query_keys(pinned.snapshot(), "beta"),
        vec!["a".to_owned(), "b".to_owned()]
    );
    writer.close().unwrap();

    // Fresh reopen sees exactly the committed batch effects.
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let snapshot = writer.reader();
    assert_eq!(
        query_keys(&snapshot, "beta"),
        vec!["a".to_owned(), "b".to_owned()]
    );
    assert_eq!(query_keys(&snapshot, "alpha"), vec!["a".to_owned()]);
    assert!(query_keys(&snapshot, "seed").is_empty());
    assert_eq!(
        query_keys(&before, "seed"),
        vec!["seed".to_owned()],
        "the pre-batch reader keeps the pre-batch generation"
    );

    // The durable idempotency token replays the exact outcome, adding nothing.
    let stored_before = (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
    );
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(summary(&replay.outcomes[0]), summary(&response.outcomes[0]));
    assert_eq!(summary(&replay.outcomes[1]), summary(&response.outcomes[1]));
    assert_eq!(summary(&replay.outcomes[2]), summary(&response.outcomes[2]));
    assert!(
        replay
            .outcomes
            .iter()
            .all(|command| command.keys.iter().all(|outcome| outcome.replayed))
    );
    assert_eq!(
        (
            writer.generation(),
            writer.pending_mutations(),
            writer.pending_documents(),
        ),
        stored_before
    );
    writer.close().unwrap();
}

// ---------------------------------------------------------------------------
// M1-V02 — local filesystem vertical slice
// ---------------------------------------------------------------------------

#[test]
fn m1_v02_filesystem_restart_and_old_generation() {
    let root = temp_path("v02");
    std::fs::create_dir_all(&root).unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(document("seed", "seed alpha")).unwrap();
    writer.commit().unwrap();
    let pre_batch_reader = writer.reader();

    // Flush before the batch, then the batch, then flush again.
    writer.flush().unwrap();
    let batch = batch_of(
        vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "beta alpha")),
            ),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("seed")]),
                MutationAction::Delete,
            ),
        ],
        "v02-batch",
    );
    let cancel = CancellationFlag::new();
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    writer.flush().unwrap();
    let generation = writer.commit().unwrap().generation;
    assert_eq!(generation, 2);
    writer.compact().unwrap();
    assert_eq!(query_keys(&writer.reader(), "alpha"), vec!["a".to_owned()]);
    writer.close().unwrap();

    // A fresh reader with no writer-local state recovers the committed batch.
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    assert_eq!(writer.generation(), Some(3));
    assert_eq!(query_keys(&writer.reader(), "beta"), vec!["a".to_owned()]);
    assert!(query_keys(&writer.reader(), "seed").is_empty());
    assert_eq!(
        query_keys(&pre_batch_reader, "seed"),
        vec!["seed".to_owned()],
        "the pre-batch snapshot is immutable"
    );

    // Durable replay after restart and compaction.
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(summary(&replay.outcomes[0]), summary(&first.outcomes[0]));
    assert_eq!(summary(&replay.outcomes[1]), summary(&first.outcomes[1]));
    writer.close().unwrap();
    let _ = std::fs::remove_dir_all(&root);
}

// ---------------------------------------------------------------------------
// M1-V03 — remote fake vertical slice
// ---------------------------------------------------------------------------

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!("m1/{name}-{}", std::process::id())).unwrap(),
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

fn remote_fake() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

#[test]
fn m1_v03_remote_fake_batch_admission_makes_no_remote_calls() {
    let store = remote_fake();
    let config = remote_config("v03");
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let batch = batch_of(
        vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "alpha beta")),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Insert(document("b", "beta gamma")),
            ),
        ],
        "v03-batch",
    );
    let cancel = CancellationFlag::new();
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("seed", "seed alpha")).unwrap();
        block_on(writer.commit()).unwrap();
        let puts = store.put_calls();
        let gets = store.get_calls();
        let response = writer.apply_batch(&batch, &cancel).unwrap();
        assert_eq!(response.outcomes.len(), 2);
        assert_eq!(store.put_calls(), puts, "admission must not write remotely");
        assert_eq!(store.get_calls(), gets, "admission must not read remotely");
        // The added objects are published exactly once, on commit.
        block_on(writer.commit()).unwrap();
        assert!(store.put_calls() > puts);
    }

    let reader_index = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let reader = reader_index.snapshot();
    assert_eq!(
        query_keys(&reader, "beta"),
        vec!["a".to_owned(), "b".to_owned()]
    );

    // Durable replay from a fresh remote writer.
    let reopened = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let mut writer = block_on(reopened.writer()).unwrap();
    let puts = store.put_calls();
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(store.put_calls(), puts);
}

#[test]
fn m1_v03_remote_upload_fault_before_current_keeps_old_generation() {
    let store = remote_fake();
    let config = remote_config("v03-fault");
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
        writer.insert(document("seed", "seed alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let mut writer = block_on(index.writer()).unwrap();
    // Fail the segment upload of the batch commit.
    store.set_put_fault(quervant_objectstore::FaultKind::BeforeWrite);
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "beta alpha")),
            )]),
            &CancellationFlag::new(),
        )
        .unwrap();
    assert!(block_on(writer.commit()).is_err());

    // The authoritative generation is still the pre-batch one.
    let reader_index = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let reader = reader_index.snapshot();
    assert_eq!(query_keys(&reader, "alpha"), vec!["seed".to_owned()]);
    assert!(query_keys(&reader, "beta").is_empty());
}

// ---------------------------------------------------------------------------
// M1-V04 — real RustFS (ignored; requires the documented environment)
// ---------------------------------------------------------------------------

#[cfg(feature = "s3")]
mod real_rustfs {
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
            endpoint.starts_with("http://"),
            "real RustFS acceptance requires an http:// endpoint"
        );
        (endpoint, bucket, access, secret, region)
    }

    /// Run a real RustFS async body on a dedicated large-stack thread with a
    /// current-thread Tokio runtime, matching the existing PR 13 harness.
    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("m1-rustfs".to_owned())
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

    fn remote_config_for(prefix: &str, name: &str) -> RemoteConfig {
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

    #[test]
    #[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
    fn m1_v04_real_rustfs_batch_replay_and_generation_consistency() {
        run(async move {
            let (endpoint, bucket, access, secret, region) = require_env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .expect("valid RustFS config"),
            );
            store.create_bucket_if_absent().await.expect("bucket");

            let run_tag = format!(
                "m1-v04-{}-{}",
                std::process::id(),
                DIRS.fetch_add(1, Ordering::SeqCst)
            );
            let prefix = format!("m1/{run_tag}");
            let config = remote_config_for(&prefix, "v04");

            // --- Generation 1: a plain single-key commit (v1 payload). ---
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("create remote");
            {
                let mut writer = index.writer().await.expect("writer");
                writer
                    .insert(document("seed", "seed alpha"))
                    .expect("insert");
                writer.commit().await.expect("commit v1 baseline");
            }

            // A reader pinned at generation 1. It must never observe batch 2.
            let pinned = RemoteIndex::open_existing(
                Arc::clone(&store),
                remote_config_for(&prefix, "v04-pinned"),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("pinned open")
            .snapshot();
            assert_eq!(query_keys(&pinned, "alpha"), vec!["seed".to_owned()]);

            let token = format!("{run_tag}-token");
            let batch = MutationBatch::new(vec![
                MutationCommand::new(
                    MutationTarget::Key(key("a")),
                    MutationAction::Insert(document("a", "beta alpha")),
                ),
                MutationCommand::new(
                    MutationTarget::Key(key("b")),
                    MutationAction::Insert(document("b", "gamma beta")),
                ),
                MutationCommand::new(
                    MutationTarget::Keys(vec![key("seed")]),
                    MutationAction::Delete,
                ),
            ])
            .with_idempotency_key(IdempotencyKey::new(token.clone()).expect("token"));
            let cancel = CancellationFlag::new();

            // --- Admission is volatile: it must publish nothing remotely. ---
            let first = {
                let mut writer = index.writer().await.expect("writer");
                let response = writer.apply_batch(&batch, &cancel).expect("admit batch");
                assert_eq!(response.outcomes.len(), 3);
                // Before commit, a fresh remote reader still sees generation 1.
                let uncommitted_view = RemoteIndex::open_existing(
                    Arc::clone(&store),
                    remote_config_for(&prefix, "v04-uncommitted"),
                    schema(),
                    registry(),
                    IndexLimits::default(),
                )
                .await
                .expect("open before commit")
                .snapshot();
                assert_eq!(
                    query_keys(&uncommitted_view, "alpha"),
                    vec!["seed".to_owned()],
                    "an uncommitted batch must never be visible remotely"
                );
                writer.commit().await.expect("commit batch generation");
                response
            };
            assert_eq!(summary(&first.outcomes[2]).0, 1);

            // --- Cold bootstrap: empty local cache, fresh bucket prefix read. ---
            let cold = RemoteIndex::open_existing(
                Arc::clone(&store),
                remote_config_for(&prefix, "v04-cold"),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("cold open")
            .snapshot();
            assert_eq!(
                query_keys(&cold, "beta"),
                vec!["a".to_owned(), "b".to_owned()]
            );
            assert_eq!(query_keys(&cold, "alpha"), vec!["a".to_owned()]);
            assert!(query_keys(&cold, "seed").is_empty());
            assert_eq!(
                query_keys(&pinned, "alpha"),
                vec!["seed".to_owned()],
                "the pinned generation-1 reader keeps its original view"
            );

            // --- Durable replay from a cold remote writer. ---
            let cold_index = RemoteIndex::open_existing(
                Arc::clone(&store),
                remote_config_for(&prefix, "v04-replay"),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("replay open");
            let mut writer = cold_index.writer().await.expect("writer");
            let replay = writer.apply_batch(&batch, &cancel).expect("replay");
            assert!(replay.replayed, "durable replay must be marked replayed");
            assert_eq!(summary(&replay.outcomes[0]), summary(&first.outcomes[0]));
            assert_eq!(summary(&replay.outcomes[1]), summary(&first.outcomes[1]));
            assert_eq!(summary(&replay.outcomes[2]), summary(&first.outcomes[2]));
            assert!(
                replay
                    .outcomes
                    .iter()
                    .all(|command| command.keys.iter().all(|outcome| outcome.replayed))
            );

            // --- Same token with a different payload is a typed conflict. ---
            let conflicting = MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "different payload")),
            )])
            .with_idempotency_key(IdempotencyKey::new(token).expect("token"));
            let error = writer
                .apply_batch(&conflicting, &cancel)
                .expect_err("conflicting token must be rejected");
            assert!(
                matches!(&error, IndexError::IdempotencyConflict { .. }),
                "expected IdempotencyConflict, got {error:?}"
            );
            // The rejected batch changed nothing: the generation is unchanged
            // and the committed replay record still answers.
            let replay_again = writer.apply_batch(&batch, &cancel).expect("replay again");
            assert!(replay_again.replayed);
            assert_eq!(
                summary(&replay_again.outcomes[0]),
                summary(&first.outcomes[0])
            );
        });
    }
}

// A compile-time guard that the conflict path is representable.
#[test]
fn m1_v03b_remote_concurrent_writer_conflict() {
    let store = remote_fake();
    let config = remote_config("v03b");
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
        writer.insert(document("seed", "seed alpha")).unwrap();
        block_on(writer.commit()).unwrap();
    }
    let cancel = CancellationFlag::new();
    let mut first = block_on(index.writer()).unwrap();
    let mut second = block_on(index.writer()).unwrap();
    first
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "beta alpha")),
            )]),
            &cancel,
        )
        .unwrap();
    second
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Insert(document("b", "beta gamma")),
            )]),
            &cancel,
        )
        .unwrap();
    block_on(first.commit()).unwrap();
    let error = block_on(second.commit()).unwrap_err();
    assert!(
        matches!(&error, IndexError::RemoteConflict { .. }),
        "the losing writer must fail closed, got {error:?}"
    );
    // The loser can never expose its partial batch as durable.
    let reader_index = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let reader = reader_index.snapshot();
    assert_eq!(
        query_keys(&reader, "alpha"),
        vec!["a".to_owned(), "seed".to_owned()]
    );
    assert!(query_keys(&reader, "gamma").is_empty());
}

// ---------------------------------------------------------------------------
// M1 raw explicit-key admission-work ceiling (PR #48 review fixup)
//
// `IndexLimits::max_batch_keys` bounds BOTH the cumulative raw explicit-key
// occurrences (duplicates included) and the cumulative resolved logical
// operations. These tests pin the raw-occurrence side, which must be enforced
// before any per-key deduplication or allocation proportional to the input.
// ---------------------------------------------------------------------------

fn delete_keys(keys: &[&str]) -> MutationCommand {
    MutationCommand::new(
        MutationTarget::Keys(
            keys.iter()
                .map(|key| DocumentKey::new(*key).unwrap())
                .collect(),
        ),
        MutationAction::Delete,
    )
}

fn delete_key(value: &str) -> MutationCommand {
    MutationCommand::new(MutationTarget::Key(key(value)), MutationAction::Delete)
}

/// A writer with a small, deterministic raw-key ceiling.
fn bounded_index(limit: u64) -> (Arc<dyn Directory>, Index) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default().with_max_batch_keys(limit),
    )
    .unwrap();
    (directory, index)
}

fn assert_resource_limit(
    result: Result<MutationBatchResponse, IndexError>,
    limit: u64,
    requested: u64,
) {
    match result {
        Err(IndexError::ResourceLimit {
            limit: got_limit,
            requested: got_requested,
        }) => {
            assert_eq!(got_limit, limit, "limit");
            assert_eq!(got_requested, requested, "requested");
        }
        other => panic!(
            "expected ResourceLimit {{ limit: {limit}, requested: {requested} }}, got {other:?}"
        ),
    }
}

#[test]
fn m1_raw_ceiling_rejects_oversized_duplicate_key_list() {
    let (_directory, index) = bounded_index(4);
    let mut writer = index.writer().unwrap();
    // Five raw occurrences of the SAME key resolve to one logical operation, so
    // the logical-operation check alone would accept this request.
    let batch = MutationBatch::new(vec![delete_keys(&["a", "a", "a", "a", "a"])]);
    assert_resource_limit(writer.apply_batch(&batch, &CancellationFlag::new()), 4, 5);
    assert_eq!(writer.pending_mutations(), 0, "no admission");
    assert_eq!(writer.pending_documents(), 0);
    assert_eq!(writer.generation(), None);
}

#[test]
fn m1_raw_ceiling_aggregates_raw_occurrences_across_commands() {
    let (_directory, index) = bounded_index(4);
    let mut writer = index.writer().unwrap();
    // Three occurrences per command; each command is individually within the
    // ceiling, but the batch total (6) exceeds it.
    let batch = MutationBatch::new(vec![
        delete_keys(&["a", "a", "a"]),
        delete_keys(&["b", "b", "b"]),
    ]);
    assert_resource_limit(writer.apply_batch(&batch, &CancellationFlag::new()), 4, 6);
    assert_eq!(writer.pending_mutations(), 0);
}

#[test]
fn m1_raw_ceiling_counts_single_key_commands() {
    let (_directory, index) = bounded_index(4);
    let mut writer = index.writer().unwrap();
    // Four `Key` commands are fine; the fifth exceeds the ceiling even though
    // every explicit `Keys` list is short.
    let in_bound = MutationBatch::new(vec![
        delete_key("a"),
        delete_key("b"),
        delete_key("c"),
        delete_key("d"),
    ]);
    assert_eq!(
        writer
            .apply_batch(&in_bound, &CancellationFlag::new())
            .unwrap()
            .outcomes
            .len(),
        4
    );

    writer.close().unwrap();

    // A fresh writer on its own index for the over-bound case.
    let (_directory, index) = bounded_index(4);
    let mut writer = index.writer().unwrap();
    let over_bound = MutationBatch::new(vec![
        delete_key("e"),
        delete_key("f"),
        delete_keys(&["g", "g"]),
        delete_key("h"),
        delete_key("i"),
    ]);
    assert_resource_limit(
        writer.apply_batch(&over_bound, &CancellationFlag::new()),
        4,
        5,
    );
    assert_eq!(writer.pending_mutations(), 0);
}

#[test]
fn m1_raw_ceiling_boundary_accepts_at_limit_and_rejects_at_limit_plus_one() {
    for (raw, ok) in [(2usize, true), (3usize, false)] {
        let (_directory, index) = bounded_index(2);
        let mut writer = index.writer().unwrap();
        let keys: Vec<&str> = (0..raw).map(|_| "a").collect();
        let batch = MutationBatch::new(vec![delete_keys(&keys)]);
        let result = writer.apply_batch(&batch, &CancellationFlag::new());
        if ok {
            let response = result.expect("exactly at the ceiling must be accepted");
            assert_eq!(
                response.outcomes[0].matched, 1,
                "one deduplicated operation"
            );
            assert_eq!(response.outcomes[0].keys.len(), 1);
            assert_eq!(writer.pending_mutations(), 1);
        } else {
            assert_resource_limit(result, 2, 3);
            assert_eq!(writer.pending_mutations(), 0);
        }
    }
}

#[test]
fn m1_raw_ceiling_preserves_first_occurrence_and_response_order() {
    let (_directory, index) = bounded_index(8);
    let mut writer = index.writer().unwrap();
    let batch = MutationBatch::new(vec![delete_keys(&["b", "a", "b", "c"])]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 3);
    assert_eq!(
        response.outcomes[0]
            .keys
            .iter()
            .map(|outcome| outcome.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        vec!["a".to_owned(), "b".to_owned(), "c".to_owned()],
        "per-key outcomes stay ascending"
    );
    assert_eq!(
        response.outcomes[0]
            .keys
            .iter()
            .filter(|outcome| outcome.key.as_str() == "b")
            .count(),
        1,
        "one operation per distinct key"
    );
}

#[test]
fn m1_raw_ceiling_rejection_is_atomic_and_does_not_publish() {
    let (directory, index) = bounded_index(4);
    let mut writer = index.writer().unwrap();
    // Pre-existing admitted state plus a committed generation.
    writer.insert(document("seed", "seed alpha")).unwrap();
    writer.commit().unwrap();
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("live")),
                MutationAction::Insert(document("live", "live beta")),
            )]),
            &CancellationFlag::new(),
        )
        .unwrap();
    let generation = writer.generation();
    let pending = writer.pending_mutations();
    let documents = writer.pending_documents();
    let reader_before = writer.reader();

    // A rejected oversized batch changes none of the live writer state.
    assert_resource_limit(
        writer.apply_batch(
            &MutationBatch::new(vec![delete_keys(&["a", "a", "a", "a", "a"])]),
            &CancellationFlag::new(),
        ),
        4,
        5,
    );
    assert_eq!(writer.generation(), generation, "generation unchanged");
    assert_eq!(writer.pending_mutations(), pending, "journal unchanged");
    assert_eq!(writer.pending_documents(), documents, "pending unchanged");
    assert_eq!(
        query_keys(&writer.reader(), "beta"),
        query_keys(&reader_before, "beta"),
        "published view unchanged"
    );
    // The still-pending admission behaves normally afterwards.
    assert_eq!(
        query_keys(&writer.reader(), "alpha"),
        query_keys(&reader_before, "alpha")
    );
    assert!(writer.close().is_ok());

    // Nothing was published: a fresh reopen sees only the committed generation.
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    assert_eq!(query_keys(&snapshot, "beta"), Vec::<String>::new());
    assert_eq!(query_keys(&snapshot, "alpha"), vec!["seed".to_owned()]);
}

#[test]
fn m1_raw_ceiling_keeps_existing_typed_rejections() {
    let (_directory, index) = bounded_index(2);
    let mut writer = index.writer().unwrap();

    // Empty key list keeps the typed invalid-batch rejection.
    let empty = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Keys(Vec::new()),
        MutationAction::Delete,
    )]);
    assert!(matches!(
        writer.apply_batch(&empty, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::InvalidBatch { .. }
        })
    ));

    // Reserved query target keeps the typed unsupported rejection, even with an
    // empty selector payload (raw count zero must not make it look valid).
    let query = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(QueryMutationSelector {
            query: Query::MatchAll,
            max_matches: 0,
            expected_generation: None,
        }),
        MutationAction::Delete,
    )]);
    assert!(matches!(
        writer.apply_batch(&query, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::UnsupportedTargetAction { .. }
        })
    ));

    // M2 admits Update for a live explicit key, but an empty patch is still a
    // typed invalid-batch rejection (phase A, before applicability).
    let update = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(DocumentPatch {
            operations: Vec::new(),
        }),
    )]);
    assert!(matches!(
        writer.apply_batch(&update, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::InvalidBatch { .. }
        })
    ));
    assert_eq!(writer.pending_mutations(), 0);
}

#[test]
fn m1_raw_ceiling_cancellation_wins_over_oversized_input() {
    let (_directory, index) = bounded_index(2);
    let mut writer = index.writer().unwrap();
    let flag = CancellationFlag::new();
    flag.cancel();
    let batch = MutationBatch::new(vec![delete_keys(&["a", "a", "a"])]);
    assert!(matches!(
        writer.apply_batch(&batch, &flag),
        Err(IndexError::Cancelled)
    ));
    assert_eq!(writer.pending_mutations(), 0);
}

#[test]
fn m1_raw_ceiling_rejects_highly_duplicated_input_cheaply() {
    // A large run of one repeated key must be rejected from the raw count, not
    // from deduplication work. The ceiling is tiny, so this is deterministic.
    let (_directory, index) = bounded_index(2);
    let mut writer = index.writer().unwrap();
    let repeated: Vec<&str> = vec!["same"; 10_000];
    let batch = MutationBatch::new(vec![delete_keys(&repeated)]);
    assert_resource_limit(
        writer.apply_batch(&batch, &CancellationFlag::new()),
        2,
        10_000,
    );
    assert_eq!(writer.pending_mutations(), 0);
}
