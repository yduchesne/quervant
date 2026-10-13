//! PR 6 deterministic fault/crash matrix (F01–F16).
//!
//! Failures are injected by wrapping the **real** `Directory` methods. Segment
//! codecs, the analyzer and the manifest are never mocked, so a passing test
//! proves the real pre-CURRENT/post-CURRENT behavior — not a fake's modeled
//! behavior. A process-level kill test is not power-loss simulation; power-loss
//! durability rests on the separately verified `Directory::atomic_write` sync
//! contract.

mod common;

use std::collections::BTreeSet;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{
    CURRENT_KEY, CurrentPointer, Index, IndexError, IndexLimits, manifest_key_for,
};
use quervant_core::storage::{
    Directory, MemoryDirectory, ReadHandle, StorageError, StorageKey, StorageOp, WriteHandle,
};

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
    .expect("schema")
}

fn doc(key: &str, title: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
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

fn keys(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .unwrap()
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

fn generation(directory: &Arc<dyn Directory>) -> Option<u64> {
    let key = StorageKey::parse(CURRENT_KEY).unwrap();
    if !directory.exists(&key).unwrap() {
        return None;
    }
    let handle = directory.open_read(&key).unwrap();
    let mut buffer = vec![0u8; handle.len() as usize];
    let mut offset = 0;
    while offset < buffer.len() {
        let read = handle
            .read_at(offset as u64, &mut buffer[offset..])
            .unwrap();
        assert!(read > 0);
        offset += read;
    }
    Some(CurrentPointer::parse(&buffer).unwrap().generation())
}

#[derive(Debug, Clone, Copy, Default)]
struct Faults {
    fail_lock_create: bool,
    fail_segment_create: bool,
    fail_segment_write: bool,
    fail_segment_write_sync: bool,
    fail_segment_dir_sync: bool,
    fail_manifest_create: bool,
    fail_manifest_write_sync: bool,
    fail_manifest_dir_sync: bool,
    fail_current_before: bool,
    fail_current_after: bool,
    fail_current_readback: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CreateKind {
    Lock,
    Segment,
    Manifest,
    Current,
    Other,
}

fn classify(key: &StorageKey) -> CreateKind {
    let value = key.as_str();
    if value == quervant_core::index::WRITER_LOCK_KEY {
        CreateKind::Lock
    } else if value == CURRENT_KEY {
        CreateKind::Current
    } else if value.starts_with("index/segments/") {
        CreateKind::Segment
    } else if value.starts_with("index/manifests/") {
        CreateKind::Manifest
    } else {
        CreateKind::Other
    }
}

struct FaultShared {
    inner: Arc<dyn Directory>,
    faults: Faults,
    last_create: Mutex<CreateKind>,
    counter: AtomicU64,
    readback_active: std::sync::atomic::AtomicBool,
}

#[derive(Clone)]
struct FaultyDirectory {
    shared: Arc<FaultShared>,
}

impl FaultyDirectory {
    fn new(faults: Faults) -> Self {
        Self {
            shared: Arc::new(FaultShared {
                inner: Arc::new(MemoryDirectory::new()),
                faults,
                last_create: Mutex::new(CreateKind::Other),
                counter: AtomicU64::new(0),
                readback_active: std::sync::atomic::AtomicBool::new(false),
            }),
        }
    }

    fn injected(&self, operation: StorageOp) -> StorageError {
        let ordinal = self.shared.counter.fetch_add(1, Ordering::SeqCst);
        StorageError::io(
            operation,
            std::io::Error::other(format!("injected {ordinal}")),
        )
    }
}

impl Directory for FaultyDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.shared.inner.create_dir_all(prefix)
    }

    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        let kind = classify(key);
        *self.shared.last_create.lock().unwrap() = kind;
        let faults = self.shared.faults;
        if (kind == CreateKind::Lock && faults.fail_lock_create)
            || (kind == CreateKind::Segment && faults.fail_segment_create)
            || (kind == CreateKind::Manifest && faults.fail_manifest_create)
        {
            return Err(self.injected(StorageOp::Create));
        }
        let inner = self.shared.inner.create(key)?;
        Ok(Box::new(FaultyWrite {
            inner,
            kind,
            faults,
        }))
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        if self.shared.faults.fail_current_readback
            && key.as_str() == CURRENT_KEY
            && self.shared.readback_active.load(Ordering::SeqCst)
        {
            return Err(self.injected(StorageOp::Read));
        }
        self.shared.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        if self.shared.faults.fail_current_readback
            && key.as_str() == CURRENT_KEY
            && self.shared.readback_active.load(Ordering::SeqCst)
        {
            return Err(self.injected(StorageOp::Exists));
        }
        self.shared.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.shared.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if key.as_str() == CURRENT_KEY {
            let faults = self.shared.faults;
            if faults.fail_current_before {
                self.shared.readback_active.store(true, Ordering::SeqCst);
                return Err(self.injected(StorageOp::AtomicWrite));
            }
            if faults.fail_current_after {
                self.shared.inner.atomic_write(key, data)?;
                return Err(self.injected(StorageOp::Sync));
            }
        }
        self.shared.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        let kind = *self.shared.last_create.lock().unwrap();
        let faults = self.shared.faults;
        if (kind == CreateKind::Segment && faults.fail_segment_dir_sync)
            || (kind == CreateKind::Manifest && faults.fail_manifest_dir_sync)
        {
            return Err(self.injected(StorageOp::DirSync));
        }
        self.shared.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.shared.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.shared.inner.file_len(key)
    }
}

struct FaultyWrite {
    inner: Box<dyn WriteHandle>,
    kind: CreateKind,
    faults: Faults,
}

impl WriteHandle for FaultyWrite {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError> {
        if self.kind == CreateKind::Segment && self.faults.fail_segment_write {
            return Err(StorageError::io(
                StorageOp::Write,
                std::io::Error::other("injected segment write"),
            ));
        }
        self.inner.write_all(buf)
    }

    fn sync_all(&mut self) -> Result<(), StorageError> {
        if (self.kind == CreateKind::Segment && self.faults.fail_segment_write_sync)
            || (self.kind == CreateKind::Manifest && self.faults.fail_manifest_write_sync)
        {
            return Err(StorageError::io(
                StorageOp::Sync,
                std::io::Error::other("injected file sync"),
            ));
        }
        self.inner.sync_all()
    }
}

fn create_pre_commit_failure(
    faults: Faults,
) -> (
    Arc<dyn Directory>,
    IndexError,
    Index,
    quervant_core::index::IndexWriter,
) {
    let wrapper = FaultyDirectory::new(faults);
    let directory: Arc<dyn Directory> = Arc::new(wrapper);
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    let error = writer
        .commit()
        .expect_err("injected failure must fail the commit");
    (directory, error, index, writer)
}

fn assert_pre_current_failure(
    directory: &Arc<dyn Directory>,
    error: &IndexError,
    writer: &quervant_core::index::IndexWriter,
) {
    assert!(
        matches!(error, IndexError::Storage(_)),
        "expected a pre-CURRENT failure, got {error:?}"
    );
    assert_eq!(generation(directory), None);
    assert!(
        !directory
            .exists(&StorageKey::parse(CURRENT_KEY).unwrap())
            .unwrap()
    );
    // Pending is retained for a future attempt.
    assert_eq!(writer.pending_documents(), 1);
}

// F01
#[test]
fn f01_segment_create_failure_keeps_old_state() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_segment_create: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F02
#[test]
fn f02_segment_write_failure_leaves_no_committed_segment() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_segment_write: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
    // No committed segment object exists in the in-memory backend.
    assert!(
        directory.list("index/segments", 16).unwrap().is_empty(),
        "a failed in-memory create must not publish a partial segment"
    );
}

// F03
#[test]
fn f03_segment_file_sync_failure_is_not_acknowledged() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_segment_write_sync: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F04
#[test]
fn f04_segment_directory_sync_failure_is_not_acknowledged() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_segment_dir_sync: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F05 (manifest create)
#[test]
fn f05a_manifest_create_failure_is_not_acknowledged() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_manifest_create: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F05 (manifest file sync)
#[test]
fn f05b_manifest_file_sync_failure_is_not_acknowledged() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_manifest_write_sync: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F05 (manifest directory sync)
#[test]
fn f05c_manifest_directory_sync_failure_is_not_acknowledged() {
    let (directory, error, _index, writer) = create_pre_commit_failure(Faults {
        fail_manifest_dir_sync: true,
        ..Faults::default()
    });
    assert_pre_current_failure(&directory, &error, &writer);
}

// F06 / F14 — CURRENT failure before replacement leaves the old generation.
#[test]
fn f06_current_failure_before_replacement_keeps_old_generation() {
    let wrapper = FaultyDirectory::new(Faults::default());
    let directory: Arc<dyn Directory> = Arc::new(wrapper);
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut first = index.writer().unwrap();
    first.insert(doc("a", "hello")).unwrap();
    first.commit().unwrap();
    drop(first);

    let wrapper = FaultyDirectory::with_inner(
        &directory,
        Faults {
            fail_current_before: true,
            ..Faults::default()
        },
    );
    let faulty: Arc<dyn Directory> = Arc::new(wrapper);
    let index =
        Index::open_existing(Arc::clone(&faulty), schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "world")).unwrap();
    let error = writer.commit().expect_err("injected CURRENT failure");
    assert!(matches!(error, IndexError::Storage(_)));
    assert_eq!(generation(&faulty), Some(1));

    // Orphan segment and manifest exist but are invisible; reopening sees gen1.
    let reopened = Index::open_existing(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    assert_eq!(reopened.generation(), Some(1));
    assert_eq!(keys(&reopened.snapshot()), BTreeSet::from(["a".into()]));
}

// F07
#[test]
fn f07_current_post_replacement_failure_is_indeterminate_and_poisoned() {
    let wrapper = FaultyDirectory::new(Faults::default());
    let directory: Arc<dyn Directory> = Arc::new(wrapper);
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut first = index.writer().unwrap();
    first.insert(doc("a", "hello")).unwrap();
    first.commit().unwrap();
    drop(first);

    let wrapper = FaultyDirectory::with_inner(
        &directory,
        Faults {
            fail_current_after: true,
            ..Faults::default()
        },
    );
    let faulty: Arc<dyn Directory> = Arc::new(wrapper);
    let index =
        Index::open_existing(Arc::clone(&faulty), schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "world")).unwrap();
    let error = writer.commit().expect_err("post-replacement sync error");
    assert!(matches!(error, IndexError::RecoveryRequired { .. }));
    // The new pointer is actually visible, but durability is unproven.
    assert_eq!(generation(&faulty), Some(2));
    // The writer refuses further writes until reopen/reconciliation.
    assert!(matches!(
        writer.insert(doc("c", "again")),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.commit(),
        Err(IndexError::RecoveryRequired { .. })
    ));
}

// F16
#[test]
fn f16_reconciliation_readback_failure_is_recovery_required() {
    let wrapper = FaultyDirectory::new(Faults {
        fail_current_before: true,
        fail_current_readback: true,
        ..Faults::default()
    });
    let directory: Arc<dyn Directory> = Arc::new(wrapper);
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    let error = writer.commit().expect_err("indeterminate commit");
    assert!(matches!(error, IndexError::RecoveryRequired { .. }));
    assert!(matches!(
        writer.insert(doc("b", "world")),
        Err(IndexError::RecoveryRequired { .. })
    ));
}

// F08
#[test]
fn f08_malformed_current_fails_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.commit().unwrap();
    drop(writer);
    directory
        .atomic_write(&StorageKey::parse(CURRENT_KEY).unwrap(), b"not a pointer\n")
        .unwrap();
    assert!(matches!(
        Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()),
        Err(IndexError::InvalidCurrent { .. })
    ));
}

// F09
#[test]
fn f09_manifest_length_or_digest_mismatch_fails_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.commit().unwrap();
    drop(writer);

    let manifest_key = StorageKey::parse(manifest_key_for(1)).unwrap();
    directory
        .atomic_write(&manifest_key, b"corrupt-manifest-bytes-that-are-long")
        .unwrap();
    assert!(matches!(
        Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()),
        Err(IndexError::CorruptCommittedState { .. })
    ));
}

// F10
#[test]
fn f10_missing_referenced_segment_fails_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.commit().unwrap();
    let segment_key = writer.reader().segments()[0].meta().object_key().to_owned();
    drop(writer);

    directory
        .delete(&StorageKey::parse(segment_key).unwrap())
        .unwrap();
    let error = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())
        .expect_err("missing segment must fail closed");
    assert!(matches!(
        error,
        IndexError::Storage(_) | IndexError::CorruptCommittedState { .. }
    ));
}

// F11
#[test]
fn f11_segment_digest_mismatch_fails_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.commit().unwrap();
    let segment = writer.reader().segments()[0].clone();
    let segment_key = StorageKey::parse(segment.meta().object_key()).unwrap();
    drop(writer);

    // Same declared length, different bytes -> digest mismatch.
    let mut mutated = segment.bytes().to_vec();
    mutated[0] ^= 0xff;
    directory.atomic_write(&segment_key, &mutated).unwrap();
    assert!(matches!(
        Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()),
        Err(IndexError::CorruptCommittedState { .. })
    ));
}

// F12
#[test]
fn f12_content_key_collision_is_a_typed_conflict_without_overwrite() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.flush().unwrap();
    let view = writer.refresh().unwrap();
    let object_key = view.segments()[0].meta().object_key().to_owned();

    // Pre-populate the future content key with different bytes.
    directory
        .atomic_write(&StorageKey::parse(&object_key).unwrap(), b"different-bytes")
        .unwrap();
    let error = writer.commit().expect_err("collision must fail");
    assert!(matches!(error, IndexError::ContentConflict { .. }));
    assert_eq!(
        directory
            .open_read(&StorageKey::parse(&object_key).unwrap())
            .unwrap()
            .len(),
        b"different-bytes".len() as u64,
        "the colliding object must not be overwritten"
    );
}

// F13
#[test]
fn f13_resource_limits_never_publish_current() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let limits = IndexLimits::new().with_max_manifest_bytes(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_eq!(generation(&directory), None);
}

// F15
#[test]
fn f15_successful_commit_is_recovered_once_without_replay() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello")).unwrap();
    writer.commit().unwrap();
    drop(writer);

    // A lost response is recovered by reopening; the key is not replayed.
    let index = Index::open_existing(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "hello")),
        Err(IndexError::DuplicateDocument { .. })
    ));
    assert_eq!(writer.reader().document_count(), 1);
}

impl FaultyDirectory {
    /// Wrap a different inner directory (for a second-generation fault).
    fn with_inner(inner: &Arc<dyn Directory>, faults: Faults) -> Self {
        Self {
            shared: Arc::new(FaultShared {
                inner: Arc::clone(inner),
                faults,
                last_create: Mutex::new(CreateKind::Other),
                counter: AtomicU64::new(0),
                readback_active: std::sync::atomic::AtomicBool::new(false),
            }),
        }
    }
}
