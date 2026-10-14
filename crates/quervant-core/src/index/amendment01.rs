//! PR 9 Amendment 01 correctness-closure tests (in-crate).
//!
//! These tests exercise the production mutation-state codec, manifest
//! publication and writer against real `MemoryDirectory`/`FsDirectory`
//! instances. They cover:
//!
//! * A1-T01–T04: deterministic revision overflow at `u64::MAX` using a valid,
//!   production-encoded near-limit state fixture.
//! * A1-T05–T10: deterministic before-write and write-then-error `CURRENT`
//!   failures, poisoning and authoritative reopen.
//! * A1-T11–T20: bounded cooperative cancellation of compaction at real decode,
//!   remap, snapshot and prepublication checkpoints.
//! * A1-T22: wire-format/scope audit.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, AtomicUsize, Ordering};

use quervant_objectstore::ContentDigest;

use crate::analysis::AnalyzerRegistry;
use crate::contract::budget::Budgets;
use crate::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent,
    MutationRequest,
};
use crate::contract::query::Query;
use crate::contract::result::TopK;
use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
use crate::contract::value::{FieldType, FieldValue};
use crate::index::current::{CURRENT_KEY, CurrentPointer, manifest_key_for, state_key_for_hex};
use crate::index::error::IndexError;
use crate::index::merge::{MergeStage, clear_cancel_hooks, set_stage_hook, set_unit_hook};
use crate::index::mutation_state::{KeyRow, MutationStateV1, ReplayRow, mutation_fingerprint};
use crate::index::{Index, IndexLimits, IndexWriter, ReaderSnapshot, support};
use crate::search::{LexicalSearcher, SearchLimits};
use crate::segment::{Manifest, MutationStateRef, SegmentReader};
use crate::storage::{
    Directory, FsDirectory, MemoryDirectory, ReadHandle, StorageError, StorageKey, StorageOp,
    WriteHandle,
};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

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
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .expect("schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).expect("key")
}

fn doc(key_str: &str, title: &str, body: &str, tag: &str, n: i64) -> Document {
    let mut document = Document::new(key(key_str));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .unwrap();
    if !body.is_empty() {
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(body.to_owned())),
            )
            .unwrap();
    }
    document
        .insert(
            "tag",
            FieldValues::Single(FieldValue::Keyword(tag.to_owned())),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    document
}

fn read_current_bytes(directory: &Arc<dyn Directory>) -> Vec<u8> {
    let storage_key = StorageKey::parse(CURRENT_KEY).unwrap();
    let handle: Box<dyn ReadHandle> = directory.open_read(&storage_key).unwrap();
    let mut buf = vec![0u8; handle.len() as usize];
    let mut filled = 0usize;
    while filled < buf.len() {
        let read = handle.read_at(filled as u64, &mut buf[filled..]).unwrap();
        if read == 0 {
            break;
        }
        filled += read;
    }
    buf.truncate(filled);
    buf
}

fn current_generation(directory: &Arc<dyn Directory>) -> u64 {
    CurrentPointer::parse(&read_current_bytes(directory))
        .unwrap()
        .generation()
}

/// Build one committed generation and then republish its logical state with the
/// supplied transform applied to the real encoded row/replay maps.
///
/// The transform can only change real `KeyRow`/`ReplayRow` values; publication
/// reuses the production state codec, content digest, manifest v2 and
/// `CURRENT` pointer. The returned state is the published candidate.
fn publish_transformed_state<F>(transform: F) -> (Arc<dyn Directory>, Arc<MutationStateV1>, u64)
where
    F: FnOnce(
        BTreeMap<DocumentKey, KeyRow>,
        BTreeMap<IdempotencyKey, ReplayRow>,
    ) -> (
        BTreeMap<DocumentKey, KeyRow>,
        BTreeMap<IdempotencyKey, ReplayRow>,
    ),
{
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .expect("create");
    let mut writer = index.writer().expect("writer");
    writer
        .apply(MutationRequest::insert(doc(
            "overflow-key",
            "seed",
            "",
            "x",
            1,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "other-key",
            "seed",
            "",
            "x",
            2,
        )))
        .unwrap();
    writer.commit().unwrap();
    let previous = writer.generation().unwrap();
    let base_state = writer.committed_state_arc().unwrap();
    let manifest = writer.committed_manifest().unwrap().clone();
    let rows: BTreeMap<_, _> = base_state
        .rows()
        .iter()
        .map(|row| (row.key.clone(), row.clone()))
        .collect();
    let replay: BTreeMap<_, _> = base_state
        .replay_rows()
        .iter()
        .map(|row| (row.token.clone(), row.clone()))
        .collect();
    let (rows, replay) = transform(rows, replay);
    let new_state = Arc::new(MutationStateV1::from_parts(rows, replay));
    // Release the writer lock before manual publication.
    writer.close().unwrap();

    let generation = previous + 1;
    let state_bytes = new_state.encode().unwrap();
    let digest = ContentDigest::sha256_v1(&state_bytes);
    let state_ref = MutationStateRef {
        object_key: state_key_for_hex(&digest.to_hex()),
        content_length: state_bytes.len() as u64,
        content_digest: *digest.as_bytes(),
    };
    support::install_immutable(
        directory.as_ref(),
        &StorageKey::parse(&state_ref.object_key).unwrap(),
        &state_bytes,
    )
    .unwrap();
    let new_manifest = Manifest {
        schema: manifest.schema.clone(),
        segments: manifest.segments.clone(),
        required_features: manifest.required_features.clone(),
        optional_features: manifest.optional_features.clone(),
        mutation_state: Some(state_ref),
    };
    let manifest_bytes = new_manifest.encode().unwrap();
    let manifest_storage_key = StorageKey::parse(manifest_key_for(generation)).unwrap();
    support::install_immutable(directory.as_ref(), &manifest_storage_key, &manifest_bytes).unwrap();
    let pointer = CurrentPointer::new(
        generation,
        manifest_bytes.len() as u64,
        ContentDigest::sha256_v1(&manifest_bytes),
    )
    .unwrap();
    directory
        .atomic_write(
            &StorageKey::parse(CURRENT_KEY).unwrap(),
            &pointer.encode().unwrap(),
        )
        .unwrap();
    (directory, new_state, generation)
}

fn search_pairs(snapshot: &ReaderSnapshot, query: &Query) -> (Vec<String>, Vec<f64>) {
    let cancel = crate::analysis::CancellationFlag::new();
    let response = LexicalSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(query, TopK::new(100).unwrap(), &Budgets::new(), &cancel)
        .unwrap();
    (
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect(),
        response.hits.iter().map(|hit| hit.score).collect(),
    )
}

fn term(value: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(value.to_owned()),
    }
}

fn body_phrase() -> Query {
    Query::Phrase {
        field: "body".into(),
        terms: vec!["quick".into(), "brown".into(), "fox".into()],
    }
}

// ---------------------------------------------------------------------------
// A1-T01 – A1-T04: revision overflow
// ---------------------------------------------------------------------------

#[test]
fn a1_t01_at_max_minus_one_new_operation_reaches_max() {
    let (directory, _, generation) = publish_transformed_state(|mut rows, replay| {
        rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX - 1;
        (rows, replay)
    });
    assert_eq!(generation, 2);
    let index = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let response = writer
        .apply(MutationRequest::upsert(doc(
            "overflow-key",
            "next",
            "",
            "x",
            1,
        )))
        .unwrap();
    assert_eq!(response.revision, Some(u64::MAX));
    assert!(!response.replayed);
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let state = writer.committed_state_arc().unwrap();
    assert_eq!(state.row(&key("overflow-key")).unwrap().revision, u64::MAX);
    // A further new operation on the same key now overflows.
    let error = writer
        .apply(MutationRequest::delete(key("overflow-key")))
        .unwrap_err();
    assert!(matches!(error, IndexError::RevisionOverflow));
    writer.close().unwrap();
}

#[test]
fn a1_t02_new_operation_at_max_overflows_without_state_change() {
    let (directory, _, _) = publish_transformed_state(|mut rows, replay| {
        rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX;
        rows.insert(key("tomb-key"), KeyRow::deleted(key("tomb-key"), u64::MAX));
        (rows, replay)
    });
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let generation = writer.generation();
    let pending = writer.pending_mutations();
    let replay_entries = writer.replay_entry_count();
    let pit = writer.pin().unwrap();
    let before_term = search_pairs(pit.snapshot(), &term("seed"));

    for request in [
        MutationRequest::upsert(doc("overflow-key", "x", "", "x", 9)),
        MutationRequest::delete(key("overflow-key")),
        MutationRequest::insert(doc("tomb-key", "x", "", "x", 9)),
    ] {
        let error = writer.apply(request).unwrap_err();
        assert!(
            matches!(error, IndexError::RevisionOverflow),
            "expected overflow, got {error:?}"
        );
    }

    assert_eq!(writer.generation(), generation);
    assert_eq!(writer.pending_mutations(), pending);
    assert_eq!(writer.replay_entry_count(), replay_entries);
    assert_eq!(search_pairs(pit.snapshot(), &term("seed")), before_term);
    // The writer remains usable for an unrelated key.
    let response = writer
        .apply(MutationRequest::upsert(doc(
            "other-key",
            "updated",
            "",
            "x",
            5,
        )))
        .unwrap();
    assert_eq!(response.revision, Some(2));
}

#[test]
fn a1_t03_replay_at_max_succeeds_and_new_token_overflows() {
    let replay_token = IdempotencyKey::new("tok-a").unwrap();
    let insert_request = MutationRequest::insert(doc("overflow-key", "seed", "", "x", 1));
    let fingerprint = mutation_fingerprint(
        MutationIntent::Insert,
        &key("overflow-key"),
        insert_request.document.as_ref(),
    )
    .unwrap();
    let (directory, _, _) = publish_transformed_state(|mut rows, mut replay| {
        rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX;
        replay.insert(
            replay_token.clone(),
            ReplayRow {
                token: replay_token.clone(),
                fingerprint,
                key: key("overflow-key"),
                intent: MutationIntent::Insert,
                revision: u64::MAX,
            },
        );
        (rows, replay)
    });
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();

    // Exact replay returns the original revision even at MAX.
    let replay = writer
        .apply(
            insert_request
                .clone()
                .with_idempotency_key(replay_token.clone()),
        )
        .unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(u64::MAX));

    // A conflicting payload still errors as a conflict, not an overflow.
    let conflict = writer
        .apply(
            MutationRequest::insert(doc("overflow-key", "altered", "", "x", 1))
                .with_idempotency_key(replay_token),
        )
        .unwrap_err();
    assert!(matches!(conflict, IndexError::IdempotencyConflict { .. }));

    // A new token at MAX overflows and is not consumed: it remains reusable
    // for an unrelated key.
    let new_token = IdempotencyKey::new("tok-new").unwrap();
    let overflow = writer
        .apply(
            MutationRequest::upsert(doc("overflow-key", "x", "", "x", 9))
                .with_idempotency_key(new_token.clone()),
        )
        .unwrap_err();
    assert!(matches!(overflow, IndexError::RevisionOverflow));
    let accepted = writer
        .apply(
            MutationRequest::upsert(doc("other-key", "other", "", "x", 9))
                .with_idempotency_key(new_token),
        )
        .unwrap();
    assert!(!accepted.replayed);
    assert_eq!(accepted.revision, Some(2));
}

#[test]
fn a1_t04_overflow_is_inert_and_writer_remains_usable() {
    let (directory, _, _) = publish_transformed_state(|mut rows, replay| {
        rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX;
        (rows, replay)
    });
    let index = Index::open_existing(directory.clone(), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let generation = writer.generation();
    let pending = writer.pending_mutations();
    let admitted = writer.admitted_entry_count();
    let replay_entries = writer.replay_entry_count();
    let pit = writer.pin().unwrap();
    let before = search_pairs(pit.snapshot(), &term("seed"));

    assert!(matches!(
        writer.apply(MutationRequest::delete(key("overflow-key"))),
        Err(IndexError::RevisionOverflow)
    ));

    assert_eq!(writer.generation(), generation);
    assert_eq!(writer.pending_mutations(), pending);
    assert_eq!(writer.admitted_entry_count(), admitted);
    assert_eq!(writer.replay_entry_count(), replay_entries);
    assert_eq!(search_pairs(pit.snapshot(), &term("seed")), before);
    // A no-work commit is still a no-op.
    assert!(writer.commit().unwrap().no_op);
    // The published view is unchanged.
    assert_eq!(search_pairs(&writer.reader(), &term("seed")), before);
}

#[test]
fn a1_t04_negative_control_inconsistent_pointer_is_rejected() {
    let (directory, _, _) = publish_transformed_state(|mut rows, replay| {
        let row = rows.get_mut(&key("overflow-key")).unwrap();
        row.revision = u64::MAX - 1;
        row.doc_id = Some(9_999);
        (rows, replay)
    });
    let error = Index::open_existing(directory, schema(), registry()).unwrap_err();
    assert!(matches!(
        error,
        IndexError::CorruptCommittedState { .. } | IndexError::Segment(_)
    ));
}

// ---------------------------------------------------------------------------
// A1-T05 – A1-T10: ambiguous CURRENT publication
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq)]
enum InjectionMode {
    PassThrough = 0,
    FailBeforeWriteOnce = 1,
    WriteThenFailOnce = 2,
}

/// A delegating `Directory` wrapper that can deterministically fail exactly the
/// next `index/CURRENT` `atomic_write`. All other operations are unchanged.
struct FaultyCurrentDirectory {
    inner: Arc<dyn Directory>,
    mode: AtomicU8,
    intercepted: AtomicUsize,
}

impl FaultyCurrentDirectory {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            mode: AtomicU8::new(InjectionMode::PassThrough as u8),
            intercepted: AtomicUsize::new(0),
        }
    }

    fn set_mode(&self, mode: InjectionMode) {
        self.mode.store(mode as u8, Ordering::SeqCst);
    }

    fn intercepted(&self) -> usize {
        self.intercepted.load(Ordering::SeqCst)
    }

    fn injected_error() -> StorageError {
        StorageError::io(
            StorageOp::AtomicWrite,
            std::io::Error::other("injected CURRENT atomic_write failure"),
        )
    }
}

impl Directory for FaultyCurrentDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        self.inner.create(key)
    }
    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        self.inner.open_read(key)
    }
    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        self.inner.exists(key)
    }
    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.inner.delete(key)
    }
    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if key.as_str() != CURRENT_KEY {
            return self.inner.atomic_write(key, data);
        }
        self.intercepted.fetch_add(1, Ordering::SeqCst);
        match self.mode.load(Ordering::SeqCst) {
            m if m == InjectionMode::PassThrough as u8 => self.inner.atomic_write(key, data),
            m if m == InjectionMode::FailBeforeWriteOnce as u8 => {
                self.mode
                    .store(InjectionMode::PassThrough as u8, Ordering::SeqCst);
                Err(Self::injected_error())
            }
            m if m == InjectionMode::WriteThenFailOnce as u8 => {
                self.mode
                    .store(InjectionMode::PassThrough as u8, Ordering::SeqCst);
                self.inner.atomic_write(key, data)?;
                Err(Self::injected_error())
            }
            _ => self.inner.atomic_write(key, data),
        }
    }
    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }
    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.inner.list(prefix, limit)
    }
    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}

fn faulty_memory() -> (Arc<FaultyCurrentDirectory>, Arc<dyn Directory>) {
    let faulty = Arc::new(FaultyCurrentDirectory::new(
        Arc::new(MemoryDirectory::new()),
    ));
    let directory: Arc<dyn Directory> = faulty.clone();
    (faulty, directory)
}

struct TempDir(std::path::PathBuf);

impl TempDir {
    fn new(tag: &str) -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "quervant-a1-{tag}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn assert_poisoned(writer: &mut IndexWriter) {
    assert!(matches!(
        writer.insert(doc("poison", "x", "", "x", 1)),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.apply(MutationRequest::upsert(doc("poison", "x", "", "x", 1))),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.delete_keys_for_retention(&[key("poison")], "reason"),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.flush(),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.refresh(),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.compact(),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.compact_with_cancel(&AtomicBool::new(false)),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.commit(),
        Err(IndexError::RecoveryRequired { .. })
    ));
}

#[test]
fn a1_t05_write_then_fail_poisons_and_new_generation_is_authoritative() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();
    let old_pit = writer.pin().unwrap();
    let old_hits = search_pairs(old_pit.snapshot(), &term("one"));

    let before_intercepts = faulty.intercepted();
    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    writer
        .apply(MutationRequest::insert(doc("b", "two", "", "x", 2)))
        .unwrap();
    let error = writer.commit().unwrap_err();
    assert!(matches!(error, IndexError::RecoveryRequired { .. }));
    assert_eq!(faulty.intercepted(), before_intercepts + 1);
    assert_eq!(current_generation(&directory), 2);
    assert_poisoned(&mut writer);
    // The old PIT keeps its pre-publication view.
    assert_eq!(search_pairs(old_pit.snapshot(), &term("one")), old_hits);
    drop(writer);

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    let hits = search_pairs(&reopened.snapshot(), &term("two")).0;
    assert_eq!(hits, ["b"]);
}

#[test]
fn a1_t06_write_then_fail_delete_only_and_replay_are_authoritative() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();

    // Delete-only commit with a replay token.
    let delete = MutationRequest::delete(key("a"))
        .with_idempotency_key(IdempotencyKey::new("tok-del").unwrap());
    writer.apply(delete.clone()).unwrap();
    let before_intercepts = faulty.intercepted();
    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    assert!(matches!(
        writer.commit().unwrap_err(),
        IndexError::RecoveryRequired { .. }
    ));
    assert_eq!(faulty.intercepted(), before_intercepts + 1);
    assert_poisoned(&mut writer);
    drop(writer);

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert!(
        search_pairs(&reopened.snapshot(), &term("one"))
            .0
            .is_empty()
    );
    // The replay ledger survived: exact replay returns the original revision.
    let mut writer = reopened.writer().unwrap();
    let replay = writer.apply(delete).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(2));
    writer.close().unwrap();

    // A subsequent commit that adds a segment also recovers cleanly.
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("c", "three", "", "x", 3)))
        .unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();
}

#[test]
fn a1_t07_poisoned_writer_rejects_every_entry_point() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();
    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    writer
        .apply(MutationRequest::insert(doc("b", "two", "", "x", 2)))
        .unwrap();
    assert!(matches!(
        writer.commit().unwrap_err(),
        IndexError::RecoveryRequired { .. }
    ));
    // Read-only inspection methods remain callable. The poisoned writer's
    // in-memory generation is intentionally stale relative to CURRENT until a
    // reopen reconciles it.
    assert_eq!(writer.generation(), Some(1));
    let _ = writer.reader();
    assert_eq!(writer.pending_mutations(), 1);
    // Every mutation/publication entry point refuses without touching storage.
    assert_poisoned(&mut writer);
}

#[test]
fn a1_t05b_write_then_fail_against_real_fs_directory() {
    let temp = TempDir::new("fs");
    let faulty = Arc::new(FaultyCurrentDirectory::new(Arc::new(
        FsDirectory::open(&temp.0).unwrap(),
    )));
    let directory: Arc<dyn Directory> = faulty.clone();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();
    let before_intercepts = faulty.intercepted();
    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    writer
        .apply(MutationRequest::insert(doc("b", "two", "", "x", 2)))
        .unwrap();
    assert!(matches!(
        writer.commit().unwrap_err(),
        IndexError::RecoveryRequired { .. }
    ));
    assert_eq!(faulty.intercepted(), before_intercepts + 1);
    drop(writer);
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(search_pairs(&reopened.snapshot(), &term("two")).0, ["b"]);
}

#[test]
fn a1_t08_fresh_writer_sees_revision_and_token_and_lock_is_released() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let request = MutationRequest::insert(doc("a", "one", "", "x", 1))
        .with_idempotency_key(IdempotencyKey::new("tok").unwrap());
    writer.apply(request.clone()).unwrap();
    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    assert!(matches!(
        writer.commit().unwrap_err(),
        IndexError::RecoveryRequired { .. }
    ));
    // A second writer cannot start while the poisoned writer holds the lock.
    assert!(matches!(index.writer(), Err(IndexError::WriterBusy)));
    drop(writer);
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut fresh = reopened.writer().unwrap();
    let replay = fresh.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
    fresh.close().unwrap();
}

#[test]
fn a1_t09_fail_before_write_preserves_old_generation_and_retries_once() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();

    let before_intercepts = faulty.intercepted();
    faulty.set_mode(InjectionMode::FailBeforeWriteOnce);
    let request = MutationRequest::insert(doc("b", "two", "", "x", 2))
        .with_idempotency_key(IdempotencyKey::new("tok-b").unwrap());
    writer.apply(request.clone()).unwrap();
    let error = writer.commit().unwrap_err();
    assert!(matches!(error, IndexError::Storage(_)));
    assert_eq!(faulty.intercepted(), before_intercepts + 1);
    assert_eq!(current_generation(&directory), 1);
    // Old generation remains authoritative on a fresh open.
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(1));
    assert!(
        !search_pairs(&reopened.snapshot(), &term("two"))
            .0
            .contains(&"b".to_owned())
    );
    drop(reopened);

    // Retry the proven pre-publication failure exactly once.
    assert_eq!(writer.replay_entry_count(), 1);
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 2);
    assert_eq!(faulty.intercepted(), before_intercepts + 2);
    let replay = writer.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
}

#[test]
fn a1_t10_retry_after_prepublication_failure_has_one_revision_and_one_token() {
    let (faulty, directory) = faulty_memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();

    let token = IdempotencyKey::new("tok-once").unwrap();
    let request = MutationRequest::insert(doc("b", "two", "", "x", 2)).with_idempotency_key(token);
    writer.apply(request.clone()).unwrap();
    faulty.set_mode(InjectionMode::FailBeforeWriteOnce);
    assert!(writer.commit().is_err());
    assert_eq!(writer.replay_entry_count(), 1);
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 2);
    drop(writer);

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let replay = writer.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
    // Exactly one accepted operation and one replay entry are visible.
    let state = writer.committed_state_arc().unwrap();
    assert_eq!(state.replay_count(), 1);
    assert_eq!(state.row_count(), 2);
    writer.close().unwrap();
}

// ---------------------------------------------------------------------------
// A1-T11 – A1-T20: compaction cancellation
// ---------------------------------------------------------------------------

fn cancellation_fixture() -> (Arc<dyn Directory>, IndexWriter) {
    build_cancellation_fixture(Arc::new(MemoryDirectory::new()))
}

fn build_cancellation_fixture(directory: Arc<dyn Directory>) -> (Arc<dyn Directory>, IndexWriter) {
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "d0",
            "alpha",
            "quick brown fox jumps",
            "rust",
            1,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "d1",
            "beta",
            "quick brown dog",
            "cpp",
            2,
        )))
        .unwrap();
    writer.flush().unwrap();
    writer
        .apply(MutationRequest::upsert(doc(
            "d0",
            "gamma",
            "quick brown fox runs",
            "rust",
            3,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "d2",
            "delta",
            "quick brown fox",
            "rust",
            4,
        )))
        .unwrap();
    writer.flush().unwrap();
    writer.apply(MutationRequest::delete(key("d1"))).unwrap();
    writer.commit().unwrap();
    (directory, writer)
}

/// A fixture whose posting lists exceed the 256-unit cancellation poll by a wide
/// margin so a unit-hook cancellation lands inside postings remapping.
fn large_postings_fixture() -> (Arc<dyn Directory>, IndexWriter) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let body = (0..24)
        .map(|index| format!("term{index}"))
        .collect::<Vec<_>>()
        .join(" ");
    for i in 0..40 {
        writer
            .apply(MutationRequest::insert(doc(
                &format!("k{i}"),
                &format!("doc{i}"),
                &body,
                "rust",
                1,
            )))
            .unwrap();
    }
    writer.flush().unwrap();
    // Tombstone every other key to force a reclaiming merge.
    for i in (0..40).step_by(2) {
        writer
            .apply(MutationRequest::delete(key(&format!("k{i}"))))
            .unwrap();
    }
    writer.flush().unwrap();
    writer.commit().unwrap();
    (directory, writer)
}

fn assert_stage_cancellation_is_inert(stage: MergeStage, occurrence: u64) {
    let (directory, mut writer) = cancellation_fixture();
    let before_current = read_current_bytes(&directory);
    let before_generation = writer.generation();
    let before_pending = writer.pending_mutations();
    let before_replay = writer.replay_entry_count();
    let pit = writer.pin().unwrap();
    let before_phrase = search_pairs(pit.snapshot(), &body_phrase());
    let before_term = search_pairs(pit.snapshot(), &term("gamma"));

    let flag = AtomicBool::new(false);
    set_stage_hook(stage, occurrence);
    let error = writer.compact_with_cancel(&flag).unwrap_err();
    clear_cancel_hooks();
    assert!(
        matches!(error, IndexError::Cancelled),
        "stage {stage:?} expected Cancelled, got {error:?}"
    );

    assert_eq!(read_current_bytes(&directory), before_current);
    assert_eq!(writer.generation(), before_generation);
    assert_eq!(writer.pending_mutations(), before_pending);
    assert_eq!(writer.replay_entry_count(), before_replay);
    assert_eq!(search_pairs(pit.snapshot(), &body_phrase()), before_phrase);
    assert_eq!(search_pairs(pit.snapshot(), &term("gamma")), before_term);

    // Retry without cancellation succeeds and is lossless.
    let outcome = writer.compact().unwrap();
    assert!(!outcome.no_op);
    assert_eq!(outcome.documents, 2);
    assert_eq!(
        search_pairs(&writer.reader(), &body_phrase()),
        before_phrase
    );
    assert_eq!(search_pairs(&writer.reader(), &term("gamma")), before_term);
}

#[test]
fn a1_t11_pre_cancelled_compact_is_rejected_without_publication() {
    let (directory, mut writer) = cancellation_fixture();
    let before_current = read_current_bytes(&directory);
    let before_generation = writer.generation();
    let flag = AtomicBool::new(true);
    let error = writer.compact_with_cancel(&flag).unwrap_err();
    assert!(matches!(error, IndexError::Cancelled));
    assert_eq!(read_current_bytes(&directory), before_current);
    assert_eq!(writer.generation(), before_generation);
    // The writer remains usable and a follow-up compaction succeeds.
    assert!(!writer.compact().unwrap().no_op);
}

#[test]
fn a1_t12_cancel_before_second_segment_decode() {
    assert_stage_cancellation_is_inert(MergeStage::BeforeDecode, 2);
}

#[test]
fn a1_t13_cancel_within_large_postings_remap() {
    let (directory, mut writer) = large_postings_fixture();
    let before_current = read_current_bytes(&directory);
    let before_generation = writer.generation();
    let pit = writer.pin().unwrap();
    let before_phrase = search_pairs(pit.snapshot(), &body_phrase());

    let flag = AtomicBool::new(false);
    set_unit_hook(300);
    let error = writer.compact_with_cancel(&flag).unwrap_err();
    clear_cancel_hooks();
    assert!(matches!(error, IndexError::Cancelled));
    assert_eq!(read_current_bytes(&directory), before_current);
    assert_eq!(writer.generation(), before_generation);
    assert_eq!(search_pairs(pit.snapshot(), &body_phrase()), before_phrase);

    let outcome = writer.compact().unwrap();
    assert!(!outcome.no_op);
    assert_eq!(outcome.documents, 20);
    assert_eq!(
        search_pairs(&writer.reader(), &body_phrase()),
        before_phrase
    );
}

#[test]
fn a1_t14_cancel_during_columns_and_norms_remap() {
    assert_stage_cancellation_is_inert(MergeStage::DuringColumns, 1);
}

#[test]
fn a1_t15_cancel_before_and_after_output_encode() {
    assert_stage_cancellation_is_inert(MergeStage::BeforeEncode, 1);
    assert_stage_cancellation_is_inert(MergeStage::AfterEncode, 1);
}

#[test]
fn a1_t16_cancel_during_snapshot_construction() {
    assert_stage_cancellation_is_inert(MergeStage::DuringSnapshot, 1);
}

#[test]
fn a1_t17_retry_after_cancellation_preserves_replay_and_revisions() {
    let (directory, mut writer) = cancellation_fixture();
    let before_generation = writer.generation();
    let before_phrase = search_pairs(writer.reader().as_ref(), &body_phrase());
    let flag = AtomicBool::new(true);
    assert!(matches!(
        writer.compact_with_cancel(&flag).unwrap_err(),
        IndexError::Cancelled
    ));
    assert_eq!(writer.generation(), before_generation);
    let outcome = writer.compact().unwrap();
    assert_eq!(outcome.generation, before_generation.unwrap() + 1);
    assert_eq!(
        search_pairs(writer.reader().as_ref(), &body_phrase()),
        before_phrase
    );
    drop(writer);
    // Reopen and verify the compacted generation is authoritative.
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(
        search_pairs(&reopened.snapshot(), &body_phrase()),
        before_phrase
    );
}

#[test]
fn a1_t18_cancellation_after_final_check_does_not_false_cancel() {
    let (_directory, mut writer) = cancellation_fixture();
    let before_generation = writer.generation().unwrap();
    let flag = AtomicBool::new(false);
    set_stage_hook(MergeStage::AfterPublishCheck, 1);
    let outcome = writer.compact_with_cancel(&flag).unwrap();
    clear_cancel_hooks();
    assert!(!outcome.no_op);
    assert_eq!(outcome.generation, before_generation + 1);
    // The flag was set by the hook after the final check, yet publication won.
    assert!(flag.load(Ordering::Relaxed));
}

#[test]
fn a1_t19_plain_and_flag_compaction_are_equivalent() {
    let (_, mut plain) = cancellation_fixture();
    let (_, mut flagged) = cancellation_fixture();
    let plain_outcome = plain.compact().unwrap();
    let never = AtomicBool::new(false);
    let flagged_outcome = flagged.compact_with_cancel(&never).unwrap();
    assert_eq!(plain_outcome.documents, flagged_outcome.documents);
    assert!(!plain_outcome.no_op);
    assert!(!flagged_outcome.no_op);
    for query in [body_phrase(), term("gamma"), term("delta")] {
        assert_eq!(
            search_pairs(plain.reader().as_ref(), &query),
            search_pairs(flagged.reader().as_ref(), &query)
        );
    }
}

#[test]
fn a1_t20_lossless_merge_against_document_oracle() {
    let (_, mut writer) = cancellation_fixture();
    // Independent oracle: live logical keys after the fixture's operations.
    let oracle = ["d0", "d2"];
    let before_term = search_pairs(writer.reader().as_ref(), &term("gamma"));
    let before_phrase = search_pairs(writer.reader().as_ref(), &body_phrase());
    let before_not = search_pairs(
        writer.reader().as_ref(),
        &Query::Not(Box::new(term("gamma"))),
    );
    let before_bm25 = search_pairs(writer.reader().as_ref(), &term("quick"));

    writer.compact().unwrap();
    let snapshot = writer.reader();
    assert_eq!(snapshot.document_count(), oracle.len() as u64);
    assert_eq!(search_pairs(snapshot.as_ref(), &term("gamma")), before_term);
    assert_eq!(
        search_pairs(snapshot.as_ref(), &body_phrase()),
        before_phrase
    );
    assert_eq!(
        search_pairs(snapshot.as_ref(), &Query::Not(Box::new(term("gamma")))),
        before_not
    );
    assert_eq!(search_pairs(snapshot.as_ref(), &term("quick")), before_bm25);

    // Stored fields, columns and indexed-but-not-stored positions survive.
    let segment = &snapshot.segments()[0];
    let reader = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits()).unwrap();
    let tag_id = reader.schema().field_id("tag").unwrap();
    let n_id = reader.schema().field_id("n").unwrap();
    assert_eq!(reader.doc_key(0).unwrap().as_str(), "d0");
    assert_eq!(reader.doc_key(1).unwrap().as_str(), "d2");
    assert_eq!(
        reader.stored_doc(0).unwrap().get(tag_id),
        FieldValues::Single(FieldValue::Keyword("rust".into()))
    );
    assert_eq!(
        reader.column_value(n_id, 1).unwrap(),
        Some(FieldValues::Single(FieldValue::I64(4)))
    );
    // The indexed-not-stored body still resolves its phrase.
    let mut phrase_keys = search_pairs(snapshot.as_ref(), &body_phrase()).0;
    phrase_keys.sort();
    assert_eq!(phrase_keys, ["d0", "d2"]);
}

#[test]
fn a1_t15b_compaction_write_then_fail_poisons_and_reopens() {
    let faulty = Arc::new(FaultyCurrentDirectory::new(
        Arc::new(MemoryDirectory::new()),
    ));
    let directory: Arc<dyn Directory> = faulty.clone();
    let (_, mut writer) = build_cancellation_fixture(directory);
    let before_generation = writer.generation().unwrap();
    let pit = writer.pin().unwrap();
    let before_phrase = search_pairs(pit.snapshot(), &body_phrase());
    let before_intercepts = faulty.intercepted();

    faulty.set_mode(InjectionMode::WriteThenFailOnce);
    assert!(matches!(
        writer.compact().unwrap_err(),
        IndexError::RecoveryRequired { .. }
    ));
    assert_eq!(faulty.intercepted(), before_intercepts + 1);
    assert_eq!(current_generation(&faulty.inner), before_generation + 1);
    assert_poisoned(&mut writer);
    assert_eq!(search_pairs(pit.snapshot(), &body_phrase()), before_phrase);
    drop(writer);

    let reopened = Index::open_existing(Arc::clone(&faulty.inner), schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(before_generation + 1));
    assert_eq!(
        search_pairs(&reopened.snapshot(), &body_phrase()),
        before_phrase
    );
}

#[test]
fn a1_t15c_compaction_prepublication_failure_is_retryable() {
    let faulty = Arc::new(FaultyCurrentDirectory::new(
        Arc::new(MemoryDirectory::new()),
    ));
    let directory: Arc<dyn Directory> = faulty.clone();
    let (_, mut writer) = build_cancellation_fixture(directory);
    let before_generation = writer.generation().unwrap();
    let pit = writer.pin().unwrap();
    let before_phrase = search_pairs(pit.snapshot(), &body_phrase());

    faulty.set_mode(InjectionMode::FailBeforeWriteOnce);
    assert!(matches!(
        writer.compact().unwrap_err(),
        IndexError::Storage(_)
    ));
    assert_eq!(current_generation(&faulty.inner), before_generation);
    assert_eq!(search_pairs(pit.snapshot(), &body_phrase()), before_phrase);
    // The writer is retryable and the retry publishes exactly one generation.
    let outcome = writer.compact().unwrap();
    assert_eq!(outcome.generation, before_generation + 1);
    assert_eq!(
        search_pairs(&writer.reader(), &body_phrase()),
        before_phrase
    );
}

#[test]
fn a1_t22_no_wire_format_or_scope_change() {
    assert_eq!(crate::segment::format::FEATURE_MUTATION_STATE, 0x0008);
    assert_eq!(
        crate::segment::format::SectionKind::MutationState as u16,
        0x000F
    );
}
