//! PR 6 unit matrix (U01–U17) over the real `MemoryDirectory`, real analyzer,
//! real `SegmentBuilder`/`SegmentReader`, real manifest codec and the real
//! `Index`/`IndexWriter` lifecycle. No fake codecs or fake segments.

mod common;

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationRequest,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{
    CURRENT_KEY, CurrentPointer, Index, IndexError, IndexLimits, manifest_key_for,
};
use quervant_core::segment::{CodecSchema, Manifest, ManifestSegmentRef};
use quervant_core::storage::{Directory, MemoryDirectory, StorageKey, WriteHandle};
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
                "path",
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

fn schema_with_analyzer(analyzer: &str) -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer(analyzer),
            FieldDefinition::new(
                "path",
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

fn doc(key: &str, title: &str, path: &str, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .expect("title");
    document
        .insert(
            "path",
            FieldValues::Single(FieldValue::Keyword(path.to_owned())),
        )
        .expect("path");
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .expect("n");
    document
}

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

fn create_index(directory: &Arc<dyn Directory>) -> Index {
    Index::create(Arc::clone(directory), schema(), AnalyzerRegistry::builtin()).expect("create")
}

fn open_index(directory: &Arc<dyn Directory>) -> Index {
    Index::open_existing(Arc::clone(directory), schema(), AnalyzerRegistry::builtin())
        .expect("open")
}

fn keys(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeSet<String> {
    snapshot
        .stored_keys()
        .expect("keys")
        .into_iter()
        .map(|key| key.as_str().to_owned())
        .collect()
}

fn current_exists(directory: &Arc<dyn Directory>) -> bool {
    directory
        .exists(&StorageKey::parse(CURRENT_KEY).unwrap())
        .unwrap()
}

fn write_file(directory: &Arc<dyn Directory>, key: &str, bytes: &[u8]) {
    let key = StorageKey::parse(key).unwrap();
    if directory.exists(&key).unwrap() {
        directory.atomic_write(&key, bytes).unwrap();
    } else {
        let mut handle: Box<dyn WriteHandle> = directory.create(&key).unwrap();
        handle.write_all(bytes).unwrap();
        handle.sync_all().unwrap();
        directory.sync().unwrap();
    }
}

fn publish_manual_manifest(directory: &Arc<dyn Directory>, schema: &Schema, generation: u64) {
    for prefix in ["index", "index/manifests", "index/segments"] {
        directory.create_dir_all(prefix).unwrap();
    }
    let bindings = SchemaAnalyzerBindings::resolve(schema, &AnalyzerRegistry::builtin()).unwrap();
    let codec = CodecSchema::from_contract(schema, &bindings).unwrap();
    let manifest = Manifest {
        schema: codec,
        segments: vec![],
        required_features: vec![],
        optional_features: vec![],
        mutation_state: None,
    };
    let bytes = manifest.encode().unwrap();
    write_file(directory, &manifest_key_for(generation), &bytes);
    let pointer = CurrentPointer::new(
        generation,
        bytes.len() as u64,
        ContentDigest::sha256_v1(&bytes),
    )
    .unwrap();
    directory
        .atomic_write(
            &StorageKey::parse(CURRENT_KEY).unwrap(),
            &pointer.encode().unwrap(),
        )
        .unwrap();
}

// U01
#[test]
fn u01_single_writer_is_exclusive_and_released_on_close() {
    let directory = memory();
    let index = create_index(&directory);
    let first = index.writer().expect("first writer admitted");
    assert!(matches!(index.writer(), Err(IndexError::WriterBusy)));
    drop(first);
    let second = index.writer().expect("close releases the lock");
    second.close().expect("explicit close");
    assert!(index.writer().is_ok());
}

// U02
#[test]
fn u02_duplicate_insert_rejected_across_states() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(matches!(
        writer.insert(doc("a", "two", "/a", 2)),
        Err(IndexError::DuplicateDocument { .. })
    ));
    writer.flush().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "three", "/a", 3)),
        Err(IndexError::DuplicateDocument { .. })
    ));
    writer.commit().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "four", "/a", 4)),
        Err(IndexError::DuplicateDocument { .. })
    ));
    drop(writer);

    // Reopen and confirm the committed key is still rejected.
    let reopened = open_index(&directory);
    let mut writer = reopened.writer().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "five", "/a", 5)),
        Err(IndexError::DuplicateDocument { .. })
    ));
    // No partial mutation: the rejected key is not present twice.
    assert_eq!(writer.reader().document_count(), 1);
}

// U03
#[test]
fn u03_flush_never_publishes_or_becomes_durable() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();

    writer.flush().expect("empty flush is a no-op");
    assert!(!current_exists(&directory));
    assert!(writer.refresh().unwrap().stored_keys().unwrap().is_empty());

    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    let flushed = writer.flush().unwrap();
    assert_eq!(flushed.documents, 1);
    assert_eq!(flushed.segments_flushed, 1);
    assert!(!current_exists(&directory), "flush must not write CURRENT");

    // Committed reader still sees nothing; the volatile refresh sees the doc.
    assert!(open_index_optional(&directory).is_none());
    assert_eq!(
        keys(&writer.refresh().unwrap()),
        BTreeSet::from(["a".into()])
    );
}

fn open_index_optional(directory: &Arc<dyn Directory>) -> Option<Index> {
    Index::open_existing(Arc::clone(directory), schema(), AnalyzerRegistry::builtin()).ok()
}

// U04
#[test]
fn u04_refresh_views_are_immutable_and_complete() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();

    let empty = writer.refresh().unwrap();
    assert!(keys(&empty).is_empty());

    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    let first = writer.refresh().unwrap();
    assert_eq!(keys(&first), BTreeSet::from(["a".into()]));

    writer.insert(doc("b", "two", "/b", 2)).unwrap();
    let second = writer.refresh().unwrap();
    assert_eq!(keys(&second), BTreeSet::from(["a".into(), "b".into()]));
    // The earlier fully built view is unchanged.
    assert_eq!(keys(&first), BTreeSet::from(["a".into()]));
    assert_eq!(keys(&empty), BTreeSet::new());
    assert_ne!(first.view_ordinal(), second.view_ordinal());
}

// U05
#[test]
fn u05_current_roundtrip_and_generation_boundaries() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.commit().unwrap();
    drop(writer);

    let bytes = {
        let handle = directory
            .open_read(&StorageKey::parse(CURRENT_KEY).unwrap())
            .unwrap();
        let mut buffer = vec![0u8; handle.len() as usize];
        handle.read_at(0, &mut buffer).unwrap();
        buffer
    };
    assert!(bytes.len() <= 512);
    let pointer = CurrentPointer::parse(&bytes).unwrap();
    assert_eq!(pointer.generation(), 1);
    assert_eq!(pointer.manifest_key().as_str(), manifest_key_for(1));
    assert_eq!(
        CurrentPointer::parse(&pointer.encode().unwrap()).unwrap(),
        pointer
    );

    // Generation u64::MAX parses but cannot be incremented further.
    let max = CurrentPointer::new(u64::MAX, 1, ContentDigest::sha256_v1(b"x")).unwrap();
    assert_eq!(CurrentPointer::parse(&max.encode().unwrap()).unwrap(), max);
}

// U05 (overflow) — recovered u64::MAX generation cannot be advanced.
#[test]
fn u05_generation_overflow_is_typed() {
    let directory = memory();
    publish_manual_manifest(&directory, &schema(), u64::MAX);
    let index = open_index(&directory);
    assert_eq!(index.generation(), Some(u64::MAX));
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::GenerationOverflow)
    ));
}

// U06
#[test]
fn u06_corrupt_current_fails_closed_without_fallback() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.commit().unwrap();
    drop(writer);

    for bad in [
        b"".as_slice(),
        b"QUERVANT-CURRENT 1\n".as_slice(),
        b"garbage".as_slice(),
        b"QUERVANT-CURRENT 1\ngeneration=0000000000000001\nmanifest=index/manifests/g-0000000000000001.manifest\nlength=0\nsha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n".as_slice(),
    ] {
        write_file(&directory, CURRENT_KEY, bad);
        let error = Index::open_existing(Arc::clone(&directory), schema(), AnalyzerRegistry::builtin())
            .expect_err("must fail closed");
        assert!(
            matches!(
                error,
                IndexError::InvalidCurrent { .. } | IndexError::CorruptCommittedState { .. }
            ),
            "unexpected {error:?}"
        );
    }
}

// U07
#[test]
fn u07_pit_is_stable_across_refresh_commit_and_close() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();

    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.refresh().unwrap();
    let pit = writer.pin().unwrap();
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));

    writer.insert(doc("b", "two", "/b", 2)).unwrap();
    writer.refresh().unwrap();
    writer.commit().unwrap();
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
    drop(writer);
    // The pinned snapshot remains valid after the writer is gone.
    assert_eq!(keys(pit.snapshot()), BTreeSet::from(["a".into()]));
}

// U08 — identical content is reused after a pre-CURRENT failure.
#[test]
fn u08_identical_content_is_reused_after_retry() {
    let wrapper = Arc::new(FailNextAtomicWrite::new(memory()));
    let directory: Arc<dyn Directory> = wrapper.clone();
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(writer.commit().is_err(), "injected CURRENT failure");
    assert_eq!(writer.generation(), None);
    assert!(!current_exists(&directory));

    // Retry finds the already-installed segment and manifest byte-identical.
    wrapper.arm(false);
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 1);
    assert_eq!(writer.reader().document_count(), 1);
}

// U09 — a no-op commit does not rewrite CURRENT.
#[test]
fn u09_noop_commit_returns_existing_generation() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    let first = writer.commit().unwrap();
    assert_eq!(first.generation, 1);

    let before = read_current_bytes(&directory);
    let second = writer.commit().unwrap();
    assert!(second.no_op);
    assert_eq!(second.generation, 1);
    assert_eq!(read_current_bytes(&directory), before);
}

fn read_current_bytes(directory: &Arc<dyn Directory>) -> Vec<u8> {
    let handle = directory
        .open_read(&StorageKey::parse(CURRENT_KEY).unwrap())
        .unwrap();
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

// U10
#[test]
fn u10_schema_and_analyzer_mismatch_is_rejected() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.commit().unwrap();
    drop(writer);

    // Same fields but a different analyzer binding.
    let mismatched = Index::open_existing(
        Arc::clone(&directory),
        schema_with_analyzer("standard"),
        AnalyzerRegistry::builtin(),
    );
    assert!(matches!(mismatched, Err(IndexError::SchemaMismatch { .. })));
}

// U11
#[test]
fn u11_limits_reject_at_and_above_the_bound() {
    // Pending count.
    let directory = memory();
    let limits = IndexLimits::new().with_max_pending_docs(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(matches!(
        writer.insert(doc("b", "two", "/b", 2)),
        Err(IndexError::ResourceLimit { .. })
    ));
    drop(writer);

    // Pending bytes.
    let directory = memory();
    let limits = IndexLimits::new().with_max_pending_bytes(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    assert!(matches!(
        writer.insert(doc("a", "one", "/a", 1)),
        Err(IndexError::ResourceLimit { .. })
    ));

    // Segments per commit.
    let directory = memory();
    let limits = IndexLimits::new().with_max_segments_per_commit(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.flush().unwrap();
    writer.insert(doc("b", "two", "/b", 2)).unwrap();
    assert!(matches!(
        writer.flush(),
        Err(IndexError::ResourceLimit { .. })
    ));

    // Manifest bytes.
    let directory = memory();
    let limits = IndexLimits::new().with_max_manifest_bytes(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(matches!(
        writer.commit(),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert!(!current_exists(&directory));

    // Resident snapshot bytes.
    let directory = memory();
    let limits = IndexLimits::new().with_max_snapshot_bytes(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    assert!(matches!(
        writer.refresh(),
        Err(IndexError::ResourceLimit { .. })
    ));

    // Pinned PITs.
    let directory = memory();
    let limits = IndexLimits::new().with_max_pinned_pits(1);
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits,
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.refresh().unwrap();
    let first = writer.pin().unwrap();
    assert!(matches!(
        writer.pin(),
        Err(IndexError::PitLimitExceeded { .. })
    ));
    drop(first);
    assert!(writer.pin().is_ok());
}

// U12
#[test]
fn u12_snapshot_outlives_writer() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    let snapshot = writer.refresh().unwrap();
    drop(writer);
    assert_eq!(keys(&snapshot), BTreeSet::from(["a".into()]));
    assert!(
        snapshot
            .contains_key(&DocumentKey::new("a").unwrap())
            .unwrap()
    );
    assert!(
        !snapshot
            .contains_key(&DocumentKey::new("z").unwrap())
            .unwrap()
    );
}

// U13
#[test]
fn u13_pit_drop_releases_pin_without_reuse() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    writer.refresh().unwrap();
    let first_id = {
        let pit = writer.pin().unwrap();
        pit.id().clone()
    };
    let second = writer.pin().unwrap();
    assert_ne!(first_id, *second.id());
    assert_eq!(index.pinned_pits(), 1);
    drop(second);
    assert_eq!(index.pinned_pits(), 0);
}

// U14
#[test]
fn u14_first_empty_commit_is_generation_one() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    let first = writer.commit().unwrap();
    assert_eq!(first.generation, 1);
    assert_eq!(first.documents, 0);
    assert!(!first.no_op);

    let second = writer.commit().unwrap();
    assert!(second.no_op);
    assert_eq!(second.generation, 1);

    writer.insert(doc("a", "one", "/a", 1)).unwrap();
    let third = writer.commit().unwrap();
    assert_eq!(third.generation, 2);
    assert_eq!(third.documents, 1);
}

// U15 (PR 9): mutations are admitted with no durable side effects until commit.
#[test]
fn u15_mutations_are_admitted_without_durable_side_effects() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();

    let upsert = writer
        .apply(MutationRequest::upsert(doc("a", "one", "/a", 1)))
        .unwrap();
    assert_eq!(upsert.revision, Some(1));
    assert!(!upsert.replayed);

    let delete = writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    assert_eq!(delete.revision, Some(2));

    let insert_with_idempotency = MutationRequest::insert(doc("b", "one", "/b", 1))
        .with_idempotency_key(IdempotencyKey::new("K").unwrap());
    let response = writer.apply(insert_with_idempotency.clone()).unwrap();
    assert_eq!(response.revision, Some(1));
    // Exact replay returns the original revision without a new document.
    let replay = writer.apply(insert_with_idempotency).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));

    assert_eq!(writer.pending_documents(), 2);
    assert!(!current_exists(&directory));
}

// U16
#[test]
fn u16_manifest_requires_canonical_ordering_and_unique_keys() {
    let schema = schema();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    let codec = CodecSchema::from_contract(&schema, &bindings).unwrap();
    let reference = |id: &str, key: &str| ManifestSegmentRef {
        segment_id: id.to_owned(),
        object_key: key.to_owned(),
        content_algorithm: 0,
        content_length: 1,
        content_digest: [0u8; 32],
        time_bounds: None,
        required_features: vec![],
        optional_features: vec![],
    };
    let unsorted = Manifest {
        schema: codec.clone(),
        segments: vec![
            reference("s-b", "index/segments/b.seg"),
            reference("s-a", "index/segments/a.seg"),
        ],
        required_features: vec![],
        optional_features: vec![],
        mutation_state: None,
    };
    assert!(unsorted.encode().is_err());

    let duplicate_key = Manifest {
        schema: codec.clone(),
        segments: vec![
            reference("s-a", "index/segments/a.seg"),
            reference("s-b", "index/segments/a.seg"),
        ],
        required_features: vec![],
        optional_features: vec![],
        mutation_state: None,
    };
    assert!(duplicate_key.encode().is_err());

    let duplicate_id = Manifest {
        schema: codec,
        segments: vec![
            reference("s-a", "index/segments/a.seg"),
            reference("s-a", "index/segments/b.seg"),
        ],
        required_features: vec![],
        optional_features: vec![],
        mutation_state: None,
    };
    assert!(duplicate_id.encode().is_err());
}

// U17
#[test]
fn u17_multiple_flushes_then_commit_keeps_every_key_once() {
    let directory = memory();
    let index = create_index(&directory);
    let mut writer = index.writer().unwrap();
    for key in ["a", "b", "c"] {
        writer.insert(doc(key, key, "/x", 1)).unwrap();
        writer.flush().unwrap();
    }
    writer.insert(doc("d", "d", "/x", 2)).unwrap();
    let view = writer.refresh().unwrap();
    assert_eq!(
        keys(&view),
        BTreeSet::from(["a".into(), "b".into(), "c".into(), "d".into()])
    );
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 1);
    assert_eq!(outcome.documents, 4);
    assert_eq!(outcome.segments_added, 4);

    // Every key appears exactly once across the committed segments.
    let stored = writer.reader().stored_keys().unwrap();
    assert_eq!(stored.len(), 4);
    let distinct: BTreeSet<_> = stored.iter().map(|key| key.as_str().to_owned()).collect();
    assert_eq!(distinct.len(), 4);
}

/// Test wrapper that fails the next `atomic_write` once.
struct FailNextAtomicWrite {
    inner: Arc<dyn Directory>,
    fail: std::sync::Arc<std::sync::atomic::AtomicBool>,
}

impl FailNextAtomicWrite {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            fail: std::sync::Arc::new(std::sync::atomic::AtomicBool::new(true)),
        }
    }

    fn arm(&self, value: bool) {
        self.fail.store(value, std::sync::atomic::Ordering::SeqCst);
    }
}

impl Directory for FailNextAtomicWrite {
    fn create_dir_all(&self, prefix: &str) -> Result<(), quervant_core::storage::StorageError> {
        self.inner.create_dir_all(prefix)
    }

    fn create(
        &self,
        key: &StorageKey,
    ) -> Result<Box<dyn quervant_core::storage::WriteHandle>, quervant_core::storage::StorageError>
    {
        self.inner.create(key)
    }

    fn open_read(
        &self,
        key: &StorageKey,
    ) -> Result<Box<dyn quervant_core::storage::ReadHandle>, quervant_core::storage::StorageError>
    {
        self.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, quervant_core::storage::StorageError> {
        self.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), quervant_core::storage::StorageError> {
        self.inner.delete(key)
    }

    fn atomic_write(
        &self,
        key: &StorageKey,
        data: &[u8],
    ) -> Result<(), quervant_core::storage::StorageError> {
        if self.fail.swap(false, std::sync::atomic::Ordering::SeqCst) {
            return Err(quervant_core::storage::StorageError::io(
                quervant_core::storage::StorageOp::AtomicWrite,
                std::io::Error::other("injected atomic write failure"),
            ));
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), quervant_core::storage::StorageError> {
        self.inner.sync()
    }

    fn list(
        &self,
        prefix: &str,
        limit: usize,
    ) -> Result<Vec<StorageKey>, quervant_core::storage::StorageError> {
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, quervant_core::storage::StorageError> {
        self.inner.file_len(key)
    }
}
