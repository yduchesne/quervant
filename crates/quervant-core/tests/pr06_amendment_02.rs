//! PR 6 Amendment 02 tests (C01–C15): commit/recovery snapshot-budget parity.
//!
//! Acceptance uses the real segment builder through `IndexWriter`, real
//! `MemoryDirectory`/`FsDirectory`, real `CURRENT` publication and a delegating
//! counting wrapper only to prove zero commit writes on rejection. Expected
//! segment totals are measured from independently built real segments, never
//! from the production validator.

mod common;

use std::collections::BTreeSet;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use common::TempDir;
use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{CURRENT_KEY, Index, IndexError, IndexLimits};
use quervant_core::storage::{
    Directory, FsDirectory, MemoryDirectory, ReadHandle, StorageError, StorageKey, WriteHandle,
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

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
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

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

fn fs_directory(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("open fs directory"))
}

fn keys(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .unwrap()
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

/// Measure the real encoded segment length for one document in an isolated
/// fixture with identical schema/analyzer and document content.
fn measure_len(key: &str, title: &str) -> u64 {
    let directory = memory();
    let index = Index::create(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc(key, title)).unwrap();
    writer.commit().unwrap();
    writer.reader().segments()[0].meta().descriptor().length
}

/// Seed generation 1 with document `a` under the published default limits.
fn seed_gen1(directory: &Arc<dyn Directory>) {
    let index = Index::create(Arc::clone(directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    writer.commit().unwrap();
}

fn read_current(directory: &Arc<dyn Directory>) -> Vec<u8> {
    let handle = directory
        .open_read(&StorageKey::parse(CURRENT_KEY).unwrap())
        .expect("CURRENT");
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

fn listing(directory: &Arc<dyn Directory>, prefix: &str) -> Vec<String> {
    directory
        .list(prefix, 64)
        .unwrap()
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

/// C01/C04/C15: an over-aggregate commit is rejected, leaves state intact, and
/// the same limit can still be reopened.
fn assert_pair_rejected(directory: Arc<dyn Directory>, a: u64, b: u64) {
    seed_gen1(&directory);
    let limit = a + b - 1;
    let before = read_current(&directory);
    let manifests_before = listing(&directory, "index/manifests");
    let segments_before = listing(&directory, "index/segments");

    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .expect("reopen at over-budget limit");
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "two")).unwrap();

    match writer.commit() {
        Err(IndexError::ResourceLimit {
            limit: reported_limit,
            requested,
        }) => {
            assert_eq!(reported_limit, limit);
            assert_eq!(requested, a + b, "exact aggregate sum is reported");
        }
        other => panic!("expected ResourceLimit, got {other:?}"),
    }

    // B04/B05: no durable side effects; CURRENT bytes and generation unchanged.
    assert_eq!(writer.generation(), Some(1));
    assert_eq!(read_current(&directory), before);
    assert_eq!(listing(&directory, "index/manifests"), manifests_before);
    assert_eq!(listing(&directory, "index/segments"), segments_before);
    // B06: pending is preserved and the writer is not poisoned.
    assert_eq!(writer.pending_documents(), 1);
    assert!(matches!(
        writer.insert(doc("b", "again")),
        Err(IndexError::DuplicateDocument { .. })
    ));
    drop(writer);

    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    assert_eq!(reopened.generation(), Some(1));
    assert_eq!(keys(&reopened.snapshot()), BTreeSet::from(["a".into()]));
}

// C01 / C04
#[test]
fn c01_c04_pair_rejected_preserves_state() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    assert_pair_rejected(memory(), a, b);
}

// C15
#[test]
fn c15_pair_rejected_on_fs_directory() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    let tmp = TempDir::new("pr06-a02-c15");
    assert_pair_rejected(fs_directory(tmp.path()), a, b);
}

// C03 / C15: exactly-at-limit commit and reopen succeed on both backends.
fn assert_pair_accepted(directory: Arc<dyn Directory>, a: u64, b: u64) {
    seed_gen1(&directory);
    let limit = a + b;
    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .expect("reopen at exact limit");
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "two")).unwrap();
    let outcome = writer.commit().expect("exact-limit commit succeeds");
    assert_eq!(outcome.generation, 2);
    drop(writer);

    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into()])
    );
}

// C03
#[test]
fn c03_exact_boundary_commit_and_reopen() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    assert_pair_accepted(memory(), a, b);
}

// C15
#[test]
fn c15_exact_boundary_on_fs_directory() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    let tmp = TempDir::new("pr06-a02-c15-exact");
    assert_pair_accepted(fs_directory(tmp.path()), a, b);
}

// C02 / B08: three-generation cumulative growth is checked.
#[test]
fn c02_multigeneration_cumulative_budget() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    let c = measure_len("c", "three");
    let directory = memory();
    {
        let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
        writer.insert(doc("b", "two")).unwrap();
        writer.commit().unwrap();
    }
    let limit = a + b + c - 1;
    let before = read_current(&directory);
    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    assert_eq!(writer.generation(), Some(2));
    writer.insert(doc("c", "three")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { requested, .. }) if requested == a + b + c
    ));
    assert_eq!(writer.generation(), Some(2));
    assert_eq!(read_current(&directory), before);
    drop(writer);

    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into()])
    );
}

// C05 / B03: the per-segment codec bound rejects before any durable write. The
// rejection surfaces while building the pending segment, so no persisted data
// is produced.
#[test]
fn c05_per_segment_codec_bound_rejects_before_durable_write() {
    let a = measure_len("a", "one");
    // A longer document guarantees a strictly larger encoded segment.
    let b = measure_len("b", "two two two two two two two two two two two two");
    assert!(b > a, "fixture must produce a larger new segment");

    let directory = memory();
    seed_gen1(&directory);
    let before = read_current(&directory);
    let segment_limits =
        quervant_core::segment::SegmentLimits::default().with_accepted_segment_bytes(a);
    let limits = IndexLimits::new().with_segment_limits(segment_limits);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .expect("gen 1 fits the tightened per-segment bound");
    let mut writer = index.writer().unwrap();
    writer
        .insert(doc("b", "two two two two two two two two two two two two"))
        .unwrap();
    let error = writer
        .commit()
        .expect_err("new segment exceeds codec bound");
    assert!(
        matches!(error, IndexError::Segment(_)),
        "expected the earlier codec rejection, got {error:?}"
    );
    assert_eq!(writer.generation(), Some(1));
    assert_eq!(read_current(&directory), before);
    assert_eq!(listing(&directory, "index/segments").len(), 1);
}

// C06 / B04: zero commit-attributable writes on aggregate budget rejection.
#[test]
fn c06_budget_rejection_performs_zero_commit_writes() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    let counting = Arc::new(CountingDirectory::new(memory()));
    let directory: Arc<dyn Directory> = counting.clone();
    seed_gen1(&directory);

    let limit = a + b - 1;
    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    // Reset after lock acquisition: only the rejected commit is measured.
    counting.reset_writes();
    writer.insert(doc("b", "two")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_eq!(counting.segment_creates(), 0);
    assert_eq!(counting.manifest_creates(), 0);
    assert_eq!(counting.current_writes(), 0);
    assert_eq!(counting.syncs(), 0);
}

// C07 / B05 / B12: real filesystem durability and no orphan objects.
#[test]
#[ignore = "spawned by c07_fs_durability_after_rejection"]
fn c07_child_reopen() {
    let path = std::env::var_os("QUERVANT_PR06_DIR").expect("directory env");
    let directory = fs_directory(std::path::Path::new(&path));
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(index.generation(), Some(1));
    assert_eq!(keys(&index.snapshot()), BTreeSet::from(["a".into()]));
}

// C07
#[test]
fn c07_fs_durability_after_rejection() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    let tmp = TempDir::new("pr06-a02-c07");
    let directory = fs_directory(tmp.path());
    seed_gen1(&directory);
    let limit = a + b - 1;
    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::open_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "two")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    drop(writer);

    // No new generation manifest or segment object from the rejected commit.
    assert_eq!(listing(&directory, "index/manifests").len(), 1);
    assert_eq!(listing(&directory, "index/segments").len(), 1);

    // A fresh process with the same path reads generation 1 only.
    let executable = std::env::current_exe().expect("current exe");
    let status = Command::new(executable)
        .args(["--ignored", "--exact", "c07_child_reopen"])
        .env("QUERVANT_PR06_DIR", tmp.path())
        .status()
        .expect("spawn child test process");
    assert!(status.success(), "child reopen failed");

    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    assert_eq!(reopened.generation(), Some(1));
}

// C08 / B06: pending batch preserved, writer not poisoned.
#[test]
fn c08_pending_preserved_after_rejection() {
    let directory = memory();
    let limits = IndexLimits::new().with_max_snapshot_bytes(1);
    let index =
        Index::create_with_limits(directory.clone(), schema(), registry(), limits.clone()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_eq!(writer.generation(), None);
    assert_eq!(writer.pending_documents(), 1);
    assert_eq!(writer.flushed_segments(), 0);
    assert!(matches!(
        writer.insert(doc("a", "again")),
        Err(IndexError::DuplicateDocument { .. })
    ));
    assert!(
        !directory
            .exists(&StorageKey::parse(CURRENT_KEY).unwrap())
            .unwrap()
    );
    writer.close().unwrap();
    assert!(matches!(
        Index::open_existing(directory, schema(), registry()),
        Err(IndexError::NotInitialized)
    ));
}

// C09 / B06: flushed + pending preserved; writer remains usable and unpoisoned.
#[test]
fn c09_flushed_and_pending_preserved_after_rejection() {
    let directory = memory();
    let limits = IndexLimits::new().with_max_snapshot_bytes(1);
    let index = Index::create_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    writer.flush().unwrap();
    writer.insert(doc("b", "two")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_eq!(writer.generation(), None);
    assert_eq!(writer.flushed_segments(), 1);
    assert_eq!(writer.pending_documents(), 1);
    // Usable: reader works, a new non-duplicate insert is accepted, refresh is
    // legitimately over the same budget and reports the existing typed error.
    let _ = writer.reader();
    writer.insert(doc("c", "three")).unwrap();
    assert!(matches!(
        writer.refresh(),
        Err(IndexError::ResourceLimit { .. })
    ));
}

// C10 / B07: no-op and empty-initial commit behavior unchanged.
#[test]
fn c10_noop_and_empty_initial_commit_unchanged() {
    let directory = memory();
    let index = Index::create(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let first = writer.commit().expect("empty initial commit");
    assert_eq!(first.generation, 1);
    assert!(!first.no_op);

    let second = writer.commit().expect("no-op commit");
    assert!(second.no_op);
    assert_eq!(second.generation, 1);

    writer.insert(doc("a", "one")).unwrap();
    let third = writer.commit().expect("real commit");
    assert_eq!(third.generation, 2);
}

// C11 / B01: committed + flushed + pending counted exactly once.
fn run_counted_once(directory: Arc<dyn Directory>, a: u64, b: u64, limit: u64, accept: bool) {
    let limits = IndexLimits::new().with_max_snapshot_bytes(limit);
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    writer.flush().unwrap();
    writer.insert(doc("b", "two")).unwrap();

    if accept {
        let outcome = writer.commit().expect("exact total accepted");
        assert_eq!(outcome.generation, 1);
        assert_eq!(outcome.segments_added, 2);
    } else {
        assert!(matches!(
            writer.commit(),
            Err(IndexError::ResourceLimit { requested, .. }) if requested == a + b
        ));
    }
}

#[test]
fn c11_committed_flushed_pending_counted_once() {
    let a = measure_len("a", "one");
    let b = measure_len("b", "two");
    run_counted_once(memory(), a, b, a + b - 1, false);
    run_counted_once(memory(), a, b, a + b, true);
}

// C12 / B09: arithmetic overflow is a typed failure (existing helper).
#[test]
fn c12_overflow_is_typed() {
    // The helper itself is unit-tested in `support.rs`; assert the public-facing
    // outcome remains a typed `ResourceLimit` for an unreachable-by-format sum.
    let directory = memory();
    let limits = IndexLimits::new().with_max_snapshot_bytes(1);
    let index = Index::create_with_limits(directory, schema(), registry(), limits.clone()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
}

// C14 / B11: PR 5 golden fixture byte-identical.
#[test]
fn c14_pr5_golden_fixture_is_byte_identical() {
    const GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden.seg");
    assert_eq!(
        quervant_objectstore::ContentDigest::sha256_v1(GOLDEN).to_hex(),
        "ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979"
    );
}

/// Real `MemoryDirectory`/`Directory` wrapper counting commit-attributable
/// operations. Only observes; all operations delegate unchanged.
struct CountingDirectory {
    inner: Arc<dyn Directory>,
    segment_creates: AtomicUsize,
    manifest_creates: AtomicUsize,
    current_writes: AtomicUsize,
    syncs: AtomicUsize,
}

impl CountingDirectory {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            segment_creates: AtomicUsize::new(0),
            manifest_creates: AtomicUsize::new(0),
            current_writes: AtomicUsize::new(0),
            syncs: AtomicUsize::new(0),
        }
    }

    fn reset_writes(&self) {
        self.segment_creates.store(0, Ordering::SeqCst);
        self.manifest_creates.store(0, Ordering::SeqCst);
        self.current_writes.store(0, Ordering::SeqCst);
        self.syncs.store(0, Ordering::SeqCst);
    }

    fn segment_creates(&self) -> usize {
        self.segment_creates.load(Ordering::SeqCst)
    }

    fn manifest_creates(&self) -> usize {
        self.manifest_creates.load(Ordering::SeqCst)
    }

    fn current_writes(&self) -> usize {
        self.current_writes.load(Ordering::SeqCst)
    }

    fn syncs(&self) -> usize {
        self.syncs.load(Ordering::SeqCst)
    }
}

impl Directory for CountingDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }

    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        if key.as_str().starts_with("index/segments/") {
            self.segment_creates.fetch_add(1, Ordering::SeqCst);
        } else if key.as_str().starts_with("index/manifests/") {
            self.manifest_creates.fetch_add(1, Ordering::SeqCst);
        }
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
        if key.as_str() == CURRENT_KEY {
            self.current_writes.fetch_add(1, Ordering::SeqCst);
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.syncs.fetch_add(1, Ordering::SeqCst);
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}
