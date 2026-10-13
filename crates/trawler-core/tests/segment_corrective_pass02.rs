//! PR 5 corrective pass 02: bounded Directory reads and manifest retained-memory
//! accounting (C6-*).
//!
//! The read-path tests use a purpose-built `Directory`/`ReadHandle` double that
//! logs every `(offset, requested_len)` and rejects any request above a
//! configured threshold, so the expectation is derived from the original bytes,
//! not from a copy of the decoder.

use std::sync::{Arc, Mutex};

use trawler_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use trawler_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use trawler_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use trawler_core::contract::value::{FieldType, FieldValue};
use trawler_core::segment::manifest::{Manifest, ManifestSegmentRef};
use trawler_core::segment::{
    CodecSchema, SegmentBuilder, SegmentDocument, SegmentError, SegmentLimits, SegmentReader,
};
use trawler_core::storage::{
    CorruptionKind, Directory, ReadHandle, StorageError, StorageKey, StorageOp, WriteHandle,
};

const MIB: usize = 1024 * 1024;

/// Shared log of `(offset, requested_len)` read requests.
type ReadLog = Arc<Mutex<Vec<(u64, usize)>>>;

#[derive(Clone)]
struct InstrumentedHandle {
    bytes: Arc<Vec<u8>>,
    log: ReadLog,
    reject_over: usize,
    max_return: usize,
    zero_at: Option<usize>,
    fail_at: Option<usize>,
}

impl ReadHandle for InstrumentedHandle {
    fn len(&self) -> u64 {
        self.bytes.len() as u64
    }

    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError> {
        self.log.lock().unwrap().push((offset, buf.len()));
        if buf.len() > self.reject_over {
            return Err(StorageError::Corrupt {
                key: StorageKey::parse("instrumented").unwrap(),
                detail: CorruptionKind::UnexpectedContent,
            });
        }
        let start = offset as usize;
        if let Some(zero_at) = self.zero_at {
            if start >= zero_at {
                return Ok(0);
            }
        }
        if let Some(fail_at) = self.fail_at {
            if start >= fail_at {
                return Err(StorageError::io(
                    StorageOp::Read,
                    std::io::Error::other("instrumented read failure"),
                ));
            }
        }
        if start >= self.bytes.len() {
            return Ok(0);
        }
        let available = self.bytes.len() - start;
        let n = available.min(buf.len()).min(self.max_return);
        buf[..n].copy_from_slice(&self.bytes[start..start + n]);
        Ok(n)
    }
}

struct InstrumentedDirectory {
    handle: InstrumentedHandle,
}

impl Directory for InstrumentedDirectory {
    fn create(&self, _key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        Err(StorageError::Unsupported {
            operation: StorageOp::Create,
            platform: "instrumented",
        })
    }

    fn open_read(&self, _key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        Ok(Box::new(self.handle.clone()))
    }

    fn exists(&self, _key: &StorageKey) -> Result<bool, StorageError> {
        Ok(true)
    }

    fn delete(&self, _key: &StorageKey) -> Result<(), StorageError> {
        Ok(())
    }

    fn atomic_write(&self, _key: &StorageKey, _data: &[u8]) -> Result<(), StorageError> {
        Err(StorageError::Unsupported {
            operation: StorageOp::AtomicWrite,
            platform: "instrumented",
        })
    }

    fn sync(&self) -> Result<(), StorageError> {
        Ok(())
    }

    fn list(&self, _prefix: &str, _limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        Ok(Vec::new())
    }

    fn file_len(&self, _key: &StorageKey) -> Result<u64, StorageError> {
        Ok(self.handle.bytes.len() as u64)
    }
}

fn instrumented(
    bytes: Vec<u8>,
    reject_over: usize,
    max_return: usize,
) -> (InstrumentedDirectory, ReadLog) {
    let log = Arc::new(Mutex::new(Vec::new()));
    let handle = InstrumentedHandle {
        bytes: Arc::new(bytes),
        log: Arc::clone(&log),
        reject_over,
        max_return,
        zero_at: None,
        fail_at: None,
    };
    (InstrumentedDirectory { handle }, log)
}

fn small_segment() -> Vec<u8> {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "payload",
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::new(false, true, false),
        )],
        None,
    )
    .unwrap();
    let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin()).unwrap();
    for i in 0..3 {
        let mut doc = SegmentDocument::new(DocumentKey::new(format!("k{i}")).unwrap());
        doc.fields.insert(
            "payload".to_owned(),
            FieldValues::Single(FieldValue::Text(format!("value-{i}"))),
        );
        builder.add_document(doc).unwrap();
    }
    builder.build().unwrap().bytes
}

/// A valid segment strictly larger than 1 MiB, for the baseline reproducer.
fn large_segment() -> Vec<u8> {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "payload",
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::new(false, true, false),
        )],
        None,
    )
    .unwrap();
    let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin()).unwrap();
    let padding = "x".repeat(400);
    for i in 0..3000 {
        let mut doc = SegmentDocument::new(DocumentKey::new(format!("doc-{i:05}")).unwrap());
        doc.fields.insert(
            "payload".to_owned(),
            FieldValues::Single(FieldValue::Text(padding.clone())),
        );
        builder.add_document(doc).unwrap();
    }
    let bytes = builder.build().unwrap().bytes;
    assert!(bytes.len() > MIB, "segment must exceed 1 MiB");
    bytes
}

fn key() -> StorageKey {
    StorageKey::parse("segments/one").unwrap()
}

// --- R5-I08: bounded read requests ------------------------------------------

#[test]
fn c6_u01_requests_are_chunk_bounded() {
    let bytes = small_segment();
    let (directory, log) = instrumented(bytes.clone(), 7, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes(7);
    let reader = SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    assert_eq!(reader.bytes(), bytes.as_slice());
    let log = log.lock().unwrap();
    assert!(!log.is_empty());
    for (offset, requested) in log.iter() {
        assert!((1..=7).contains(requested), "unbounded request {requested}");
        assert!(*offset < bytes.len() as u64);
    }
}

#[test]
fn c6_u02_exact_chunk_is_one_request() {
    let bytes = small_segment();
    let len = bytes.len();
    let (directory, log) = instrumented(bytes.clone(), len, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes(len as u64);
    SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    assert_eq!(log.lock().unwrap().len(), 1);
}

#[test]
fn c6_u03_chunk_one_below_needs_two_requests() {
    let bytes = small_segment();
    let len = bytes.len();
    let (directory, log) = instrumented(bytes.clone(), len - 1, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes((len - 1) as u64);
    SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    let log = log.lock().unwrap();
    assert_eq!(log.len(), 2);
    assert_eq!(log[0], (0, len - 1));
    assert_eq!(log[1], ((len - 1) as u64, 1));
}

#[test]
fn c6_u04_empty_object_makes_no_read() {
    let (directory, log) = instrumented(Vec::new(), 7, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes(7);
    assert!(SegmentReader::open_directory(&directory, &key(), limits).is_err());
    assert!(log.lock().unwrap().is_empty());
}

#[test]
fn c6_u05_zero_chunk_fails_before_read() {
    let bytes = small_segment();
    let (directory, log) = instrumented(bytes, 7, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes(0);
    assert!(matches!(
        SegmentReader::open_directory(&directory, &key(), limits),
        Err(SegmentError::LimitExceeded { .. })
    ));
    assert!(log.lock().unwrap().is_empty(), "no read must be attempted");
}

#[test]
fn c6_u06_single_byte_short_reads() {
    let bytes = small_segment();
    let (directory, log) = instrumented(bytes.clone(), 4, 1);
    let limits = SegmentLimits::default().with_max_read_bytes(4);
    let reader = SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    assert_eq!(reader.bytes(), bytes.as_slice());
    let log = log.lock().unwrap();
    for (index, (offset, requested)) in log.iter().enumerate() {
        assert_eq!(*offset, index as u64);
        assert!((1..=4).contains(requested));
    }
}

#[test]
fn c6_u07_variable_fragments() {
    let bytes = small_segment();
    let log = Arc::new(Mutex::new(Vec::new()));
    // A handle whose returned size cycles 3/1/2 via a wrapper Directory.
    struct VariableHandle {
        bytes: Arc<Vec<u8>>,
        log: ReadLog,
    }
    impl ReadHandle for VariableHandle {
        fn len(&self) -> u64 {
            self.bytes.len() as u64
        }
        fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError> {
            let start = offset as usize;
            let size = match (start % 3, buf.len()) {
                (0, _) => 3,
                (1, _) => 1,
                _ => 2,
            };
            self.log.lock().unwrap().push((offset, buf.len()));
            if start >= self.bytes.len() {
                return Ok(0);
            }
            let available = self.bytes.len() - start;
            let n = available.min(buf.len()).min(size);
            buf[..n].copy_from_slice(&self.bytes[start..start + n]);
            Ok(n)
        }
    }
    struct VariableDirectory {
        handle: VariableHandle,
    }
    impl Directory for VariableDirectory {
        fn create(&self, _k: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
            Err(StorageError::Unsupported {
                operation: StorageOp::Create,
                platform: "instrumented",
            })
        }
        fn open_read(&self, _k: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
            Ok(Box::new(VariableHandle {
                bytes: Arc::clone(&self.handle.bytes),
                log: Arc::clone(&self.handle.log),
            }))
        }
        fn exists(&self, _k: &StorageKey) -> Result<bool, StorageError> {
            Ok(true)
        }
        fn delete(&self, _k: &StorageKey) -> Result<(), StorageError> {
            Ok(())
        }
        fn atomic_write(&self, _k: &StorageKey, _d: &[u8]) -> Result<(), StorageError> {
            Err(StorageError::Unsupported {
                operation: StorageOp::AtomicWrite,
                platform: "instrumented",
            })
        }
        fn sync(&self) -> Result<(), StorageError> {
            Ok(())
        }
        fn list(&self, _p: &str, _l: usize) -> Result<Vec<StorageKey>, StorageError> {
            Ok(Vec::new())
        }
        fn file_len(&self, _k: &StorageKey) -> Result<u64, StorageError> {
            Ok(self.handle.bytes.len() as u64)
        }
    }
    let directory = VariableDirectory {
        handle: VariableHandle {
            bytes: Arc::new(bytes.clone()),
            log: Arc::clone(&log),
        },
    };
    let limits = SegmentLimits::default().with_max_read_bytes(8);
    let reader = SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    assert_eq!(reader.bytes(), bytes.as_slice());
    let requested: Vec<(u64, usize)> = log.lock().unwrap().clone();
    let mut expected_offset = 0usize;
    for (offset, _) in &requested {
        assert_eq!(
            *offset, expected_offset as u64,
            "offset skipped or duplicated"
        );
        expected_offset = (*offset as usize)
            + match (*offset as usize) % 3 {
                0 => 3,
                1 => 1,
                _ => 2,
            };
        expected_offset = expected_offset.min(bytes.len());
    }
}

#[test]
fn c6_u08_no_redundant_read_after_completion() {
    let bytes = small_segment();
    let len = bytes.len();
    let (directory, log) = instrumented(bytes.clone(), len, usize::MAX);
    let limits = SegmentLimits::default().with_max_read_bytes(len as u64);
    SegmentReader::open_directory(&directory, &key(), limits).expect("open");
    assert_eq!(
        log.lock().unwrap().len(),
        1,
        "no EOF probe after completion"
    );
}

#[test]
fn c6_u09_short_object_is_length_mismatch() {
    let bytes = small_segment();
    let mut handle_dir = instrumented(bytes.clone(), usize::MAX, 5);
    handle_dir.0.handle.zero_at = Some(10);
    let limits = SegmentLimits::default().with_max_read_bytes(16);
    assert!(matches!(
        SegmentReader::open_directory(&handle_dir.0, &key(), limits),
        Err(SegmentError::LengthMismatch { .. })
    ));
}

#[test]
fn c6_u10_io_error_is_propagated() {
    let bytes = small_segment();
    let mut handle_dir = instrumented(bytes.clone(), usize::MAX, usize::MAX);
    handle_dir.0.handle.fail_at = Some(8);
    let limits = SegmentLimits::default().with_max_read_bytes(16);
    assert!(matches!(
        SegmentReader::open_directory(&handle_dir.0, &key(), limits),
        Err(SegmentError::Storage(_))
    ));
}

#[test]
fn c6_u11_total_size_cap_rejects_before_read() {
    let bytes = small_segment();
    let (directory, log) = instrumented(bytes.clone(), usize::MAX, usize::MAX);
    let limits = SegmentLimits::default().with_accepted_segment_bytes((bytes.len() - 1) as u64);
    assert!(matches!(
        SegmentReader::open_directory(&directory, &key(), limits),
        Err(SegmentError::LimitExceeded { .. })
    ));
    assert!(log.lock().unwrap().is_empty());
}

#[test]
fn c6_baseline_oversized_read_reproducer() {
    // Baseline-compatible: default `max_read_bytes` (1 MiB); the handle rejects
    // any request larger than 1 MiB. A valid >1 MiB segment must open on the
    // fixed chunked reader and fails on the baseline whole-remaining read.
    let bytes = large_segment();
    let (directory, log) = instrumented(bytes.clone(), MIB, usize::MAX);
    let reader = SegmentReader::open_directory(&directory, &key(), SegmentLimits::default())
        .expect("chunked read must succeed");
    assert_eq!(reader.bytes(), bytes.as_slice());
    for (_, requested) in log.lock().unwrap().iter() {
        assert!(*requested <= MIB, "request exceeded max_read_bytes");
    }
}

#[test]
fn c6_i01_memory_directory_real_reopen() {
    use trawler_core::storage::MemoryDirectory;
    let bytes = small_segment();
    let directory = MemoryDirectory::new();
    let key = key();
    {
        let mut handle = directory.create(&key).unwrap();
        handle.write_all(&bytes).unwrap();
        handle.sync_all().unwrap();
    }
    let reader =
        SegmentReader::open_directory(&directory, &key, SegmentLimits::default()).expect("open");
    assert_eq!(reader.bytes(), bytes.as_slice());
}

#[test]
fn c6_i02_fs_directory_fresh_reopen() {
    use trawler_core::storage::FsDirectory;
    let bytes = small_segment();
    let dir = std::env::temp_dir().join(format!("trawler-p2-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("segments")).unwrap();
    let key = key();
    {
        let directory = FsDirectory::open(&dir).unwrap();
        let mut handle = directory.create(&key).unwrap();
        handle.write_all(&bytes).unwrap();
        handle.sync_all().unwrap();
        directory.sync().unwrap();
    }
    let directory = FsDirectory::open(&dir).unwrap();
    let reader =
        SegmentReader::open_directory(&directory, &key, SegmentLimits::default()).expect("open");
    assert_eq!(reader.bytes(), bytes.as_slice());
    let _ = std::fs::remove_dir_all(&dir);
}

// --- R5-I09: manifest retained-memory accounting ----------------------------

fn codec_schema() -> CodecSchema {
    // Empty schema so the manifest retained-charge boundary is not conflated
    // with the schema decoder's own independent budget check.
    let schema = Schema::new(Vec::new(), None).unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn reference(id: &str, object: &str) -> ManifestSegmentRef {
    ManifestSegmentRef {
        segment_id: id.to_owned(),
        object_key: object.to_owned(),
        content_algorithm: 0,
        content_length: 10,
        content_digest: [7u8; 32],
        time_bounds: None,
        required_features: vec![(1, 1)],
        optional_features: vec![(2, 1)],
    }
}

fn manifest_with(segments: Vec<ManifestSegmentRef>) -> Manifest {
    Manifest {
        schema: codec_schema(),
        segments,
        required_features: vec![(1, 1)],
        optional_features: vec![],
    }
}

#[test]
fn c6_u14_empty_manifest_round_trip() {
    let manifest = manifest_with(vec![]);
    let required = manifest.retained_bytes().unwrap();
    let bytes = manifest.encode().unwrap();
    let limits = SegmentLimits::default().with_max_section_decode_bytes(required);
    assert_eq!(Manifest::decode(&bytes, &limits).unwrap(), manifest);
}

#[test]
fn c6_u13_three_unique_keys_decode_matches_model() {
    let manifest = manifest_with(vec![
        reference("segments/a", "objects/a"),
        reference("segments/b", "objects/b"),
        reference("segments/c", "objects/c"),
    ]);
    let required = manifest.retained_bytes().unwrap();
    let bytes = manifest.encode().unwrap();
    let limits = SegmentLimits::default().with_max_section_decode_bytes(required);
    let decoded = Manifest::decode(&bytes, &limits).unwrap();
    assert_eq!(decoded, manifest);
}

#[test]
fn c6_u12_duplicate_object_key_rejected() {
    use trawler_core::segment::format::{ByteWriter, ContainerBuilder, ContainerKind, SectionKind};
    let schema_bytes = codec_schema().encode().unwrap();
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(2);
    for id in ["segments/a", "segments/b"] {
        payload.len_prefixed_u16(id.as_bytes()).unwrap();
        payload.len_prefixed_u16(b"objects/same").unwrap();
        payload.u8(0);
        payload.u64(10);
        payload.bytes(&[7u8; 32]);
        payload.u8(0);
        payload.u32(0);
        payload.u32(0);
    }
    payload.u32(0);
    payload.u32(0);
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    builder.section(SectionKind::Manifest, 0, 0, payload.into_vec());
    let bytes = builder.build().unwrap();
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::InvalidManifest { .. })
    ));
}

#[test]
fn c6_u15_many_unique_keys_within_budget() {
    let segments = (0..50)
        .map(|i| reference(&format!("segments/{i:03}"), &format!("objects/{i:03}")))
        .collect();
    let manifest = manifest_with(segments);
    let required = manifest.retained_bytes().unwrap();
    let bytes = manifest.encode().unwrap();
    let limits = SegmentLimits::default().with_max_section_decode_bytes(required);
    assert_eq!(
        Manifest::decode(&bytes, &limits).unwrap().segments.len(),
        50
    );
}

#[test]
fn c6_u16_u19_u20_retained_budget_boundaries() {
    let manifest = manifest_with(vec![
        reference("segments/a", "objects/a"),
        reference("segments/b", "objects/b"),
    ]);
    let required = manifest.retained_bytes().unwrap();
    let bytes = manifest.encode().unwrap();

    // Exact conservative budget is accepted.
    assert!(
        Manifest::decode(
            &bytes,
            &SegmentLimits::default().with_max_section_decode_bytes(required)
        )
        .is_ok()
    );
    // One below is rejected.
    assert!(matches!(
        Manifest::decode(
            &bytes,
            &SegmentLimits::default().with_max_section_decode_bytes(required - 1)
        ),
        Err(SegmentError::LimitExceeded { .. })
    ));
    // Well below is rejected.
    assert!(matches!(
        Manifest::decode(
            &bytes,
            &SegmentLimits::default().with_max_section_decode_bytes(required / 2)
        ),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

#[test]
fn c6_u17_u18_truncated_and_malformed_manifest() {
    let manifest = manifest_with(vec![reference("segments/a", "objects/a")]);
    let bytes = manifest.encode().unwrap();
    // Truncated container.
    assert!(Manifest::decode(&bytes[..bytes.len() / 2], &SegmentLimits::default()).is_err());
    // Malformed payload (invalid manifest section body) via a rebuilt container.
    use trawler_core::segment::format::{ContainerBuilder, ContainerKind, SectionKind};
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    let mut payload = Vec::new();
    payload.extend_from_slice(&1u16.to_le_bytes()); // version
    payload.extend_from_slice(&u32::MAX.to_le_bytes()); // oversized schema length
    builder.section(SectionKind::Manifest, 0, 0, payload);
    let forged = builder.build().unwrap();
    assert!(Manifest::decode(&forged, &SegmentLimits::default()).is_err());
}

#[test]
fn c6_i03_unknown_required_feature_fails_closed() {
    let mut manifest = manifest_with(vec![reference("segments/a", "objects/a")]);
    manifest.segments[0].required_features = vec![(0xbeef, 1)];
    let bytes = manifest.encode().unwrap();
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::UnsupportedFeature { .. })
    ));
}

#[test]
fn c6_i04_public_retained_bytes_is_conservative() {
    let manifest = manifest_with(vec![
        reference("segments/a", "objects/a"),
        reference("segments/b", "objects/b"),
    ]);
    // The charge includes the vector backing, both string payloads plus the
    // duplicate-index clone payload, feature vectors, and index overhead.
    let required = manifest.retained_bytes().unwrap();
    let naive_strings: u64 = manifest
        .segments
        .iter()
        .map(|s| (s.segment_id.len() + s.object_key.len()) as u64)
        .sum();
    assert!(required > naive_strings);
}
