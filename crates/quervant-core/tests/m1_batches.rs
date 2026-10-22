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
    MutationAction, MutationBatch, MutationCommand, MutationCommandOutcome, MutationKeyOutcome,
    MutationTarget,
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

    fn env(name: &str) -> Option<String> {
        std::env::var(name).ok().filter(|value| !value.is_empty())
    }

    fn config() -> Option<S3Config> {
        Some(S3Config::new(
            env("QUERVANT_RUSTFS_ENDPOINT")?,
            env("QUERVANT_RUSTFS_REGION").unwrap_or_else(|| "us-east-1".to_owned()),
            env("QUERVANT_RUSTFS_BUCKET")?,
            env("QUERVANT_RUSTFS_ACCESS_KEY")?,
            env("QUERVANT_RUSTFS_SECRET_KEY")?,
        ))
    }

    #[test]
    #[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
    fn m1_v04_real_rustfs_batch_replay_and_generation_consistency() {
        let Some(s3) = config() else {
            panic!("M1-V04 requires the documented QUERVANT_RUSTFS_* environment");
        };
        let store = Arc::new(S3ObjectStore::new(s3).expect("s3 store"));
        let suffix = format!(
            "m1-v04-{}-{}",
            std::process::id(),
            DIRS.fetch_add(1, Ordering::SeqCst)
        );
        let config = RemoteConfig::new(
            RemoteKeyPrefix::parse(format!("m1/{suffix}")).unwrap(),
            temp_path("v04"),
        )
        .with_transfer(
            RemoteTransferConfig::default()
                .with_range_threshold(256 * 1024)
                .with_chunk_size(32 * 1024)
                .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16),
        );

        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        // Commit a v1 baseline generation.
        {
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("seed", "seed alpha")).unwrap();
            block_on(writer.commit()).unwrap();
        }
        let batch = MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(document("a", "beta alpha")),
            ),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("seed")]),
                MutationAction::Delete,
            ),
        ])
        .with_idempotency_key(IdempotencyKey::new(format!("{suffix}-token")).unwrap());
        let cancel = CancellationFlag::new();
        let first = {
            let mut writer = block_on(index.writer()).unwrap();
            let response = writer.apply_batch(&batch, &cancel).unwrap();
            block_on(writer.commit()).unwrap();
            response
        };

        // Cold bootstrap with an empty local cache (new workspace root).
        let cold_config = RemoteConfig::new(
            RemoteKeyPrefix::parse(format!("m1/{suffix}")).unwrap(),
            temp_path("v04-cold"),
        )
        .with_transfer(
            RemoteTransferConfig::default()
                .with_range_threshold(256 * 1024)
                .with_chunk_size(32 * 1024)
                .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16),
        );
        let cold = block_on(RemoteIndex::open_existing(
            Arc::clone(&store),
            cold_config,
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let reader = cold.snapshot();
        assert_eq!(query_keys(&reader, "beta"), vec!["a".to_owned()]);
        assert!(query_keys(&reader, "seed").is_empty());
        // Durable replay from the cold reader.
        let mut writer = block_on(cold.writer()).unwrap();
        let replay = writer.apply_batch(&batch, &cancel).unwrap();
        assert!(replay.replayed);
        assert_eq!(summary(&replay.outcomes[0]), summary(&first.outcomes[0]));
        assert_eq!(summary(&replay.outcomes[1]), summary(&first.outcomes[1]));
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
