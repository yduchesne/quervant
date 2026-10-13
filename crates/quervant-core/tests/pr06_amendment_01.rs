//! PR 6 Amendment 01 integration tests (T01–T25).
//!
//! Exercise writer freshness, aggregate committed-snapshot budgets, retryable
//! lock release, process-local session PIT ids, and bounded managed reader
//! materialization on the real `MemoryDirectory`/`FsDirectory`, the real
//! analyzer/segment/manifest codecs and the existing deterministic I/O fault
//! wrappers.

mod common;

use std::collections::BTreeSet;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use common::TempDir;
use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{CURRENT_KEY, Index, IndexError, IndexLimits};
use quervant_core::segment::SegmentLimits;
use quervant_core::storage::{
    Directory, FsDirectory, MemoryDirectory, ReadHandle, StorageError, StorageKey, StorageOp,
    WriteHandle,
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

fn keys(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .unwrap()
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

fn fs_directory(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("open fs directory"))
}

fn run_child(test_name: &str, directory: &std::path::Path) -> bool {
    let executable = std::env::current_exe().expect("current exe");
    Command::new(executable)
        .args(["--ignored", "--exact", test_name])
        .env("QUERVANT_PR06_DIR", directory)
        .status()
        .expect("spawn child test process")
        .success()
}

// A01 / T01
#[test]
fn t01_sequential_writers_reload_committed_generation() {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        assert_eq!(writer.commit().unwrap().generation, 1);
    }
    {
        let mut writer = index.writer().unwrap();
        // A fresh writer must reload CURRENT, not trust the create handle's
        // empty cached state.
        assert_eq!(writer.generation(), Some(1));
        writer.insert(doc("b", "two")).unwrap();
        assert_eq!(writer.commit().unwrap().generation, 2);
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into()])
    );
}

// A01 / T02
#[test]
fn t02_stale_opened_handle_reloads_current() {
    let directory = memory();
    let bootstrap = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = bootstrap.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
    }
    let stale = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(stale.generation(), Some(1));

    // A different handle commits generation 2.
    let other = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = other.writer().unwrap();
        writer.insert(doc("b", "two")).unwrap();
        assert_eq!(writer.commit().unwrap().generation, 2);
    }

    // The stale handle's writer must reload generation 2 and reject the
    // already-committed key rather than losing it.
    let mut writer = stale.writer().unwrap();
    assert_eq!(writer.generation(), Some(2));
    assert!(matches!(
        writer.insert(doc("a", "again")),
        Err(IndexError::DuplicateDocument { .. })
    ));
    writer.insert(doc("c", "three")).unwrap();
    assert_eq!(writer.commit().unwrap().generation, 3);

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into(), "c".into()])
    );
}

// A01 / T02 (separate process)
#[test]
#[ignore = "spawned by t02_stale_handle_reloads_current_across_process"]
fn t02_child_commits_gen2() {
    let path = std::env::var_os("QUERVANT_PR06_DIR").expect("directory env");
    let directory = fs_directory(std::path::Path::new(&path));
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "two")).unwrap();
    assert_eq!(writer.commit().unwrap().generation, 2);
}

// A01 / T02 (separate process)
#[test]
fn t02_stale_handle_reloads_current_across_process() {
    let tmp = TempDir::new("pr06-a01-t02");
    let directory = fs_directory(tmp.path());
    let create = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = create.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
    }
    let stale = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(stale.generation(), Some(1));

    // A separate process commits generation 2.
    assert!(run_child("t02_child_commits_gen2", tmp.path()));

    let mut writer = stale.writer().unwrap();
    assert_eq!(writer.generation(), Some(2));
    writer.insert(doc("c", "three")).unwrap();
    assert_eq!(writer.commit().unwrap().generation, 3);

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into(), "c".into()])
    );
}

// A01 / T03
#[test]
fn t03_created_handle_reloads_first_commit() {
    let directory = memory();
    let created = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    assert_eq!(created.generation(), None);

    let other = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = other.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        assert_eq!(writer.commit().unwrap().generation, 1);
    }

    let mut writer = created.writer().unwrap();
    assert_eq!(writer.generation(), Some(1));
    writer.insert(doc("b", "two")).unwrap();
    assert_eq!(writer.commit().unwrap().generation, 2);

    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(
        keys(&reopened.snapshot()),
        BTreeSet::from(["a".into(), "b".into()])
    );
}

// A02 / T04
#[test]
fn t04_corrupt_current_prevents_writer_admission() {
    let directory = memory();
    let bootstrap = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = bootstrap.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
    }
    let handle = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    directory
        .atomic_write(&StorageKey::parse(CURRENT_KEY).unwrap(), b"garbage")
        .unwrap();

    assert!(matches!(
        handle.writer(),
        Err(IndexError::InvalidCurrent { .. })
    ));
    // The failed attempt released the lock; a retry fails the same way.
    assert!(matches!(
        handle.writer(),
        Err(IndexError::InvalidCurrent { .. })
    ));
}

fn two_segment_committed(index: &Index) {
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    assert_eq!(writer.commit().unwrap().segments_added, 1);
    writer.insert(doc("b", "two")).unwrap();
    assert_eq!(writer.commit().unwrap().segments_added, 1);
}

// A03 / T05
#[test]
fn t05_exact_aggregate_snapshot_limit_succeeds() {
    let directory = memory();
    two_segment_committed(&Index::create(Arc::clone(&directory), schema(), registry()).unwrap());
    let probe = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let total: u64 = probe
        .snapshot()
        .segments()
        .iter()
        .map(|segment| segment.bytes().len() as u64)
        .sum();
    assert_eq!(probe.snapshot().segment_count(), 2);

    let limits = IndexLimits::new().with_max_snapshot_bytes(total);
    let reopened = Index::open_with_limits(directory, schema(), registry(), limits).unwrap();
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(reopened.snapshot().document_count(), 2);
}

// A03 / T06
#[test]
fn t06_aggregate_over_limit_rejects_before_segment_reads() {
    let directory = memory();
    two_segment_committed(&Index::create(Arc::clone(&directory), schema(), registry()).unwrap());
    let probe = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let sizes: Vec<u64> = probe
        .snapshot()
        .segments()
        .iter()
        .map(|segment| segment.bytes().len() as u64)
        .collect();
    let limits = IndexLimits::new().with_max_snapshot_bytes(sizes[0] + sizes[1] - 1);

    let counting = CountingDirectory::new(Arc::clone(&directory));
    let counting_dir: Arc<dyn Directory> = Arc::new(counting.clone());
    let error = Index::open_with_limits(counting_dir, schema(), registry(), limits).unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert_eq!(
        counting.segment_opens(),
        0,
        "no segment may be opened before the aggregate preflight"
    );
}

// A03 / T07
#[test]
fn t07_individual_oversize_rejects_before_segment_reads() {
    let directory = memory();
    let bootstrap = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = bootstrap.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
    }
    let probe = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let size = probe.snapshot().segments()[0].bytes().len() as u64;
    let segment_limits = SegmentLimits::default().with_accepted_segment_bytes(size - 1);
    let limits = IndexLimits::new()
        .with_segment_limits(segment_limits)
        .with_max_snapshot_bytes(u64::MAX);

    let counting = CountingDirectory::new(Arc::clone(&directory));
    let counting_dir: Arc<dyn Directory> = Arc::new(counting.clone());
    let error = Index::open_with_limits(counting_dir, schema(), registry(), limits).unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert_eq!(counting.segment_opens(), 0);
}

// A06 / T10 — a failing release never admits a competing writer.
#[test]
fn t10_failed_release_does_not_admit_second_writer() {
    let flaky = Arc::new(DeleteFailingDirectory::new(Arc::clone(&memory())));
    flaky.fail_always();
    let directory: Arc<dyn Directory> = flaky.clone();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let writer = index.writer().unwrap();
    let error = writer.close().expect_err("delete is permanently failing");
    assert!(matches!(error, IndexError::Storage(_)));
    assert!(matches!(index.writer(), Err(IndexError::WriterBusy)));
    // close attempt plus the Drop best-effort retry.
    assert_eq!(flaky.deletes(), 2);
}

// A06 / T11 — a one-time failure is retried by Drop and releases the lock.
#[test]
fn t11_close_failure_drop_retry_releases_one_time_failure() {
    let flaky = Arc::new(DeleteFailingDirectory::new(Arc::clone(&memory())));
    flaky.fail_next(1);
    let directory: Arc<dyn Directory> = flaky.clone();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let writer = index.writer().unwrap();
    let error = writer.close().expect_err("first delete fails");
    assert!(matches!(error, IndexError::Storage(_)));
    assert_eq!(
        flaky.deletes(),
        2,
        "Drop made exactly one best-effort retry"
    );
    // The Drop retry succeeded, so a new writer is admitted.
    assert!(index.writer().is_ok());
}

// A04 / T12–T14
#[test]
fn t12_pit_ids_are_session_qualified_and_distinct() {
    let first_index = Index::create(memory(), schema(), registry()).unwrap();
    let second_index = Index::create(memory(), schema(), registry()).unwrap();
    let mut first = first_index.writer().unwrap();
    let mut second = second_index.writer().unwrap();
    first.insert(doc("a", "one")).unwrap();
    first.refresh().unwrap();
    second.insert(doc("b", "two")).unwrap();
    second.refresh().unwrap();

    let first_pit = first.pin().unwrap();
    let second_pit = second.pin().unwrap();
    assert_ne!(first_pit.id(), second_pit.id());
    assert!(first_pit.id().as_str().starts_with("pit-"));
    assert_eq!(first_pit.id().as_str().len(), 4 + 16 + 1 + 16);

    // Same session/ordinal formatting and no pin leak on drop.
    let same_session = first.pin().unwrap();
    assert_eq!(
        &first_pit.id().as_str()[4..20],
        &same_session.id().as_str()[4..20]
    );
    assert_ne!(first_pit.id(), same_session.id());
    assert_eq!(first_index.pinned_pits(), 2);
    drop(same_session);
    assert_eq!(first_index.pinned_pits(), 1);
    drop(first_pit);
    drop(second_pit);
    assert_eq!(first_index.pinned_pits(), 0);
}

// A09 / T16–T18
#[test]
fn t16_t17_t18_managed_reader_copy_budget() {
    let directory = memory();
    let bootstrap = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    {
        let mut writer = bootstrap.writer().unwrap();
        writer.insert(doc("a", "one")).unwrap();
        writer.commit().unwrap();
    }
    let probe = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let size = probe.snapshot().segments()[0].bytes().len() as u64;

    let limits = IndexLimits::new().with_max_snapshot_bytes(size);
    let index = Index::open_with_limits(directory, schema(), registry(), limits).unwrap();
    let snapshot = index.snapshot();

    // T16: exactly at the budget succeeds.
    let first = snapshot.open_segment_reader(0).unwrap();
    assert_eq!(first.reader().doc_count(), 1);
    // T17: a second simultaneous copy rejects before cloning.
    assert!(matches!(
        snapshot.open_segment_reader(0),
        Err(IndexError::ResourceLimit { .. })
    ));
    // The existing reader is unaffected.
    assert_eq!(first.reader().doc_count(), 1);
    // T18: releasing the first copy admits another.
    drop(first);
    let third = snapshot.open_segment_reader(0).unwrap();
    assert_eq!(third.reader().doc_count(), 1);
}

// A14 / T25 — out-of-range guarded read is typed.
#[test]
fn t25_out_of_range_guarded_read_is_typed() {
    let directory = memory();
    let index = Index::create(directory, schema(), registry()).unwrap();
    let snapshot = index.snapshot();
    assert!(matches!(
        snapshot.open_segment_reader(0),
        Err(IndexError::SegmentOutOfRange { index: 0, count: 0 })
    ));
}

// A11 / T20
#[test]
fn t20_independent_guarded_readers_survive_concurrent_commit() {
    let directory = memory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    writer.commit().unwrap();
    let snapshot = writer.reader();

    let mut handles = Vec::new();
    for _ in 0..4 {
        let snapshot = Arc::clone(&snapshot);
        handles.push(std::thread::spawn(move || {
            let guard = snapshot.open_segment_reader(0).unwrap();
            assert_eq!(guard.reader().doc_count(), 1);
        }));
    }
    writer.insert(doc("b", "two")).unwrap();
    writer.commit().unwrap();
    for handle in handles {
        handle.join().unwrap();
    }
    assert_eq!(snapshot.document_count(), 1);
    assert_eq!(writer.reader().document_count(), 2);
}

// A11 / T21
#[test]
fn t21_old_pit_guarded_reader_survives_commit() {
    let directory = memory();
    let index = Index::create(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one")).unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    writer.insert(doc("b", "two")).unwrap();
    writer.commit().unwrap();

    let guard = pit.snapshot().open_segment_reader(0).unwrap();
    assert_eq!(guard.reader().doc_count(), 1);
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
}

// A12 / T22
#[test]
fn t22_pr5_golden_fixture_is_byte_identical() {
    const GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden.seg");
    let digest = quervant_objectstore::ContentDigest::sha256_v1(GOLDEN);
    assert_eq!(
        digest.to_hex(),
        "ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979"
    );
}

/// Real `MemoryDirectory` wrapper counting opens of segment keys only.
#[derive(Clone)]
struct CountingDirectory {
    inner: Arc<dyn Directory>,
    segment_opens: Arc<AtomicUsize>,
}

impl CountingDirectory {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            segment_opens: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn segment_opens(&self) -> usize {
        self.segment_opens.load(Ordering::SeqCst)
    }
}

impl Directory for CountingDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }

    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        self.inner.create(key)
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        if key.as_str().starts_with("index/segments/") {
            self.segment_opens.fetch_add(1, Ordering::SeqCst);
        }
        self.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        self.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.inner.atomic_write(key, data)
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

/// Real `MemoryDirectory` wrapper failing a configured number of deletes.
#[derive(Clone)]
struct DeleteFailingDirectory {
    inner: Arc<dyn Directory>,
    fail_always: Arc<AtomicBool>,
    remaining_failures: Arc<AtomicUsize>,
    deletes: Arc<AtomicUsize>,
}

impl DeleteFailingDirectory {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            fail_always: Arc::new(AtomicBool::new(false)),
            remaining_failures: Arc::new(AtomicUsize::new(0)),
            deletes: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn fail_always(&self) {
        self.fail_always.store(true, Ordering::SeqCst);
    }

    fn fail_next(&self, count: usize) {
        self.remaining_failures.store(count, Ordering::SeqCst);
    }

    fn deletes(&self) -> usize {
        self.deletes.load(Ordering::SeqCst)
    }
}

impl Directory for DeleteFailingDirectory {
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

    // MSRV compatibility: retain fetch_update until the minimum supported Rust version supports its replacement.
    #[allow(deprecated)]
    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.deletes.fetch_add(1, Ordering::SeqCst);
        let injected = self.fail_always.load(Ordering::SeqCst)
            || self
                .remaining_failures
                .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |remaining| {
                    remaining.checked_sub(1)
                })
                .is_ok();
        if injected {
            return Err(StorageError::io(
                StorageOp::Delete,
                std::io::Error::other("injected delete failure"),
            ));
        }
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.inner.atomic_write(key, data)
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
