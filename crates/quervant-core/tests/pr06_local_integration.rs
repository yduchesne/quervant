//! PR 6 real production-path integration (I01–I12).
//!
//! These tests use the real analyzer registry, `SegmentBuilder`, `SegmentReader`,
//! manifest codec and the real `MemoryDirectory`/`FsDirectory` storage seam.
//! Restart tests spawn a separate OS process; they do **not** simulate power
//! loss and do not by themselves prove hardware durability.

mod common;

use std::collections::BTreeSet;
use std::process::Command;
use std::sync::Arc;

use common::TempDir;
use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{CURRENT_KEY, Index, IndexError};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory, StorageKey};
use quervant_objectstore::ContentDigest;

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

fn doc(key: &str, title: &str, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .expect("title");
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .expect("n");
    document
}

fn keys(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .expect("keys")
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

fn fs_directory(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("open fs directory"))
}

fn memory_directory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

// I01
#[test]
fn i01_insert_flush_commit_visibility_on_memory_directory() {
    let directory = memory_directory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();

    writer.insert(doc("a", "hello world", 1)).unwrap();
    writer.flush().unwrap();
    // Not visible to a committed opener yet.
    assert!(Index::open_existing(Arc::clone(&directory), schema(), registry()).is_err());
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 1);

    let committed = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let snapshot = committed.snapshot();
    assert_eq!(keys(&snapshot), BTreeSet::from(["a".into()]));
    let guard = snapshot.open_segment_reader(0).unwrap();
    let reader = guard.reader();
    let title = reader.schema().field_id("title").unwrap();
    let postings = reader.postings(title, "hello").unwrap().expect("postings");
    assert_eq!(postings.posting_doc_count(), 1);
}

// I02
#[test]
fn i02_pit_stable_across_refresh_commit_on_memory_directory() {
    let directory = memory_directory();
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();

    writer.insert(doc("a", "hello", 1)).unwrap();
    let view_one = writer.refresh().unwrap();
    let pit = writer.pin().unwrap();

    writer.insert(doc("b", "world", 2)).unwrap();
    let view_two = writer.refresh().unwrap();
    writer.commit().unwrap();

    assert_eq!(keys(&view_one), BTreeSet::from(["a".into()]));
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
    assert_eq!(keys(&view_two), BTreeSet::from(["a".into(), "b".into()]));
    drop(writer);
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
}

// I03 child: refresh-only state must not be durable.
#[test]
#[ignore = "spawned by i03_refresh_only_not_durable"]
fn i03_child_writer() {
    let path = std::env::var_os("QUERVANT_PR06_DIR").expect("directory env");
    let directory = fs_directory(std::path::Path::new(&path));
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("volatile", "volatile", 9)).unwrap();
    writer.refresh().unwrap();
    // Exit without committing: the refresh-only document must not survive.
}

// I03
#[test]
fn i03_refresh_only_not_durable_prior_commit_intact() {
    let dir = TempDir::new("pr06-i03");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("committed", "committed", 1)).unwrap();
        writer.commit().unwrap();
    }
    let status = run_child("i03_child_writer", dir.path());
    assert!(status, "child writer failed");

    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(index.generation(), Some(1));
    assert_eq!(
        keys(&index.snapshot()),
        BTreeSet::from(["committed".into()])
    );
}

// I04 child: write an orphan higher-generation manifest without publishing.
#[test]
#[ignore = "spawned by i04_orphan_manifest_ignored"]
fn i04_child_writes_orphan() {
    let path = std::env::var_os("QUERVANT_PR06_DIR").expect("directory env");
    let directory = FsDirectory::open(std::path::Path::new(&path)).unwrap();
    directory.create_dir_all("index/manifests").unwrap();
    let key = StorageKey::parse(quervant_core::index::manifest_key_for(3)).unwrap();
    let mut handle = directory.create(&key).unwrap();
    handle
        .write_all(b"orphan-manifest-not-referenced-by-current")
        .unwrap();
    handle.sync_all().unwrap();
    directory.sync().unwrap();
}

// I04
#[test]
fn i04_orphan_manifest_ignored_current_is_authoritative() {
    let dir = TempDir::new("pr06-i04");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "hello", 1)).unwrap();
        writer.commit().unwrap();
    }
    assert!(run_child("i04_child_writes_orphan", dir.path()));

    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(index.generation(), Some(1));
    assert_eq!(keys(&index.snapshot()), BTreeSet::from(["a".into()]));
}

// I05 child: reopen in a new process, verify committed postings, commit again.
#[test]
#[ignore = "spawned by i05_restart_preserves_documents_and_postings"]
fn i05_child_reopens_and_commits() {
    let path = std::env::var_os("QUERVANT_PR06_DIR").expect("directory env");
    let directory = fs_directory(std::path::Path::new(&path));
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.document_count(), 1);
    let guard = snapshot.open_segment_reader(0).unwrap();
    let reader = guard.reader();
    let title = reader.schema().field_id("title").unwrap();
    assert!(
        reader.postings(title, "hello").unwrap().is_some(),
        "committed postings must survive restart"
    );
    drop(guard);
    drop(snapshot);
    drop(index);

    let directory = fs_directory(std::path::Path::new(&path));
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("b", "world", 2)).unwrap();
    writer.commit().unwrap();
}

// I05
#[test]
fn i05_restart_preserves_documents_and_postings() {
    let dir = TempDir::new("pr06-i05");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "hello", 1)).unwrap();
        writer.commit().unwrap();
    }
    assert!(run_child("i05_child_reopens_and_commits", dir.path()));

    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(index.generation(), Some(2));
    assert_eq!(
        keys(&index.snapshot()),
        BTreeSet::from(["a".into(), "b".into()])
    );
}

// I06
#[test]
fn i06_second_writer_rejected_and_stale_marker_manually_recoverable() {
    let dir = TempDir::new("pr06-i06");
    let directory = fs_directory(dir.path());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let first = index.writer().unwrap();
    assert!(matches!(index.writer(), Err(IndexError::WriterBusy)));
    drop(first);

    // Simulate a crash leaving a stale marker: no automatic takeover.
    let lock = StorageKey::parse(quervant_core::index::WRITER_LOCK_KEY).unwrap();
    let mut handle = directory.create(&lock).unwrap();
    handle.write_all(b"stale").unwrap();
    handle.sync_all().unwrap();
    directory.sync().unwrap();
    drop(handle);
    assert!(matches!(index.writer(), Err(IndexError::WriterBusy)));

    // An operator removes the marker, then reopening succeeds.
    directory.delete(&lock).unwrap();
    assert!(index.writer().is_ok());
}

// I07
#[test]
fn i07_committed_duplicate_key_rejected_after_reopen() {
    let dir = TempDir::new("pr06-i07");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "hello", 1)).unwrap();
        writer.commit().unwrap();
    }
    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "again", 2)),
        Err(IndexError::DuplicateDocument { .. })
    ));
}

// I08
#[test]
fn i08_schema_analyzer_mismatch_fails_closed_on_fs() {
    let dir = TempDir::new("pr06-i08");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "hello", 1)).unwrap();
        writer.commit().unwrap();
    }
    let mismatched = Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .unwrap();
    let directory = fs_directory(dir.path());
    let error = Index::open_existing(directory, mismatched, registry()).expect_err("must reject");
    assert!(matches!(error, IndexError::SchemaMismatch { .. }));
}

// I09
#[test]
fn i09_threads_read_independent_immutable_snapshots_during_commit() {
    let directory = memory_directory();
    let index = Index::create(directory, schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello", 1)).unwrap();
    writer.commit().unwrap();
    let snapshot = writer.reader();
    assert_eq!(snapshot.document_count(), 1);

    let mut handles = Vec::new();
    for _ in 0..4 {
        let snapshot = Arc::clone(&snapshot);
        handles.push(std::thread::spawn(move || {
            let guard = snapshot.open_segment_reader(0).unwrap();
            let reader = guard.reader();
            let stored = reader.stored().unwrap();
            assert_eq!(stored.len(), 1);
            let title = reader.schema().field_id("title").unwrap();
            assert!(reader.postings(title, "hello").unwrap().is_some());
        }));
    }

    // Commit a second generation while the threads read the first.
    writer.insert(doc("b", "world", 2)).unwrap();
    writer.commit().unwrap();
    for handle in handles {
        handle.join().unwrap();
    }
    assert_eq!(snapshot.document_count(), 1);
    assert_eq!(writer.reader().document_count(), 2);
}

// I10
#[test]
fn i10_old_pit_and_reader_retain_prior_segments() {
    let dir = TempDir::new("pr06-i10");
    let directory = fs_directory(dir.path());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "hello", 1)).unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    let old_segment_key = pit.snapshot().segments()[0].meta().object_key().to_owned();

    writer.insert(doc("b", "world", 2)).unwrap();
    writer.commit().unwrap();

    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
    assert!(
        directory
            .exists(&StorageKey::parse(old_segment_key).unwrap())
            .unwrap(),
        "no referenced segment may be deleted"
    );
}

// I11
#[test]
fn i11_empty_initial_commit_and_generation_increment_on_fs() {
    let dir = TempDir::new("pr06-i11");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let first = writer.commit().unwrap();
        assert_eq!(first.generation, 1);
        writer.insert(doc("a", "hello", 1)).unwrap();
        let second = writer.commit().unwrap();
        assert_eq!(second.generation, 2);
    }
    let directory = fs_directory(dir.path());
    let index = Index::open_existing(directory, schema(), registry()).unwrap();
    assert_eq!(index.generation(), Some(2));
    assert_eq!(keys(&index.snapshot()), BTreeSet::from(["a".into()]));
}

// I12
#[test]
fn i12_flush_only_state_not_durable_or_visible() {
    let dir = TempDir::new("pr06-i12");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(doc("a", "hello", 1)).unwrap();
        writer.flush().unwrap();
        assert!(
            !directory
                .exists(&StorageKey::parse(CURRENT_KEY).unwrap())
                .unwrap()
        );
    }
    let directory = fs_directory(dir.path());
    assert!(matches!(
        Index::open_existing(directory, schema(), registry()),
        Err(IndexError::NotInitialized)
    ));
}

fn run_child(test_name: &str, directory: &std::path::Path) -> bool {
    let executable = std::env::current_exe().expect("current exe");
    let status = Command::new(executable)
        .args(["--ignored", "--exact", test_name])
        .env("QUERVANT_PR06_DIR", directory)
        .status()
        .expect("spawn child test process");
    status.success()
}

// Keep a reference to the digest helper so the dependency is exercised.
#[test]
fn content_digest_is_available() {
    assert_eq!(ContentDigest::sha256_v1(b"").to_hex().len(), 64);
}
