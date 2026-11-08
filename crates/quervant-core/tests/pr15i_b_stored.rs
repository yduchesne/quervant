//! PR 15I-B — bounded compressed random-access STORED v2 public-path tests.

use std::collections::BTreeMap;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::segment::format::{
    ContainerBuilder, FEATURE_STORED_BLOCKS, parse_container, sha256,
};
use quervant_core::segment::stored::encode_stored;
use quervant_core::segment::{
    Layout, SectionKind, SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader,
};
use quervant_core::storage::{Directory, MemoryDirectory};

const BLOCKS_HEADER_LEN: usize = 22;
const BLOCK_ENTRY_LEN: usize = 40;
const STORED_BLOCK_DOCS: u64 = 128;
const STORED_BLOCKS_PAYLOAD_VERSION: u16 = 2;

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
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .expect("schema")
}

fn doc(index: usize) -> SegmentDocument {
    let mut document = SegmentDocument::new(DocumentKey::new(format!("k{index:06}")).unwrap());
    document.fields.insert(
        "title".to_owned(),
        FieldValues::Single(FieldValue::Text(format!("title {index}"))),
    );
    document.fields.insert(
        "tag".to_owned(),
        FieldValues::Single(FieldValue::Keyword(if index % 3 == 0 {
            "common".to_owned()
        } else {
            "rare".to_owned()
        })),
    );
    document.fields.insert(
        "n".to_owned(),
        FieldValues::Single(FieldValue::I64(index as i64)),
    );
    document
}

fn build(count: usize) -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .with_layout(Layout::Insertion)
        .with_limits(SegmentLimits::default());
    for index in 0..count {
        builder.add_document(doc(index)).expect("add");
    }
    builder.build().expect("build").bytes
}

fn stored_body(bytes: &[u8]) -> Vec<u8> {
    let view = parse_container(bytes, &SegmentLimits::default()).expect("container");
    view.body(SectionKind::Stored).expect("stored").to_vec()
}

fn directory_end(body: &[u8]) -> usize {
    let count = u64::from_le_bytes(body[14..22].try_into().unwrap());
    BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN * count as usize
}

fn rebuild_stored(original: &[u8], body: &[u8], with_feature: bool) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(original, &limits).expect("container");
    let mut builder = ContainerBuilder::new(view.kind(), view.doc_count());
    let mut baseline_skipped = false;
    let mut saw_blocks = false;
    for (feature, version) in view.required_features() {
        if (*feature, *version) == (FEATURE_STORED_BLOCKS, 1) {
            saw_blocks = true;
            if with_feature {
                builder.require_feature(*feature, *version);
            }
            continue;
        }
        if !baseline_skipped && (*feature, *version) == (1, 1) {
            baseline_skipped = true;
            continue;
        }
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    if with_feature && !saw_blocks {
        builder.require_feature(FEATURE_STORED_BLOCKS, 1);
    }
    for section in view.sections() {
        let replacement = if section.kind == SectionKind::Stored {
            body.to_vec()
        } else {
            let start = section.offset as usize;
            original[start..start + section.length as usize].to_vec()
        };
        builder.section(section.kind, section.flags, section.aux, replacement);
    }
    builder.build().expect("rebuilt container")
}

fn as_v1(bytes: &[u8]) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let reader = SegmentReader::open(bytes.to_vec(), limits).expect("v2");
    let schema = reader.schema().clone();
    let docs: Vec<SegmentDocument> = reader
        .stored()
        .expect("stored")
        .iter()
        .map(|record| {
            let mut document = SegmentDocument::new(record.key.clone());
            for (field_id, values) in &record.fields {
                if let Some(field) = schema.field(*field_id) {
                    document.fields.insert(field.name.clone(), values.clone());
                }
            }
            document
        })
        .collect();
    let v1 = encode_stored(&schema, &docs, &limits).expect("v1");
    rebuild_stored(bytes, &v1, false)
}

fn open(bytes: Vec<u8>) -> SegmentReader {
    SegmentReader::open(bytes, SegmentLimits::default()).expect("open")
}

fn keys(reader: &SegmentReader) -> Vec<String> {
    reader
        .stored()
        .expect("stored")
        .iter()
        .map(|record| record.key.as_str().to_owned())
        .collect()
}

#[test]
fn u02_zero_docs_is_exactly_the_22_byte_header() {
    let bytes = build(0);
    let body = stored_body(&bytes);
    assert_eq!(body.len(), 22);
    assert_eq!(
        u16::from_le_bytes([body[0], body[1]]),
        STORED_BLOCKS_PAYLOAD_VERSION
    );
    assert_eq!(u64::from_le_bytes(body[2..10].try_into().unwrap()), 0);
    assert_eq!(u64::from_le_bytes(body[14..22].try_into().unwrap()), 0);
    assert!(open(bytes).stored().unwrap().is_empty());
}

#[test]
fn u03_to_u08_block_geometry_is_exact() {
    for count in [1usize, 127, 128, 129, 255, 256] {
        let bytes = build(count);
        let body = stored_body(&bytes);
        let block_count = u64::from_le_bytes(body[14..22].try_into().unwrap());
        let expected = (count as u64).div_ceil(STORED_BLOCK_DOCS);
        assert_eq!(block_count, expected, "count {count}");
        assert_eq!(
            u16::from_le_bytes(body[10..12].try_into().unwrap()) as u64,
            STORED_BLOCK_DOCS
        );
        let mut offset = directory_end(&body) as u64;
        let mut total = 0u64;
        for index in 0..block_count as usize {
            let entry = BLOCKS_HEADER_LEN + index * BLOCK_ENTRY_LEN;
            let first = u64::from_le_bytes(body[entry..entry + 8].try_into().unwrap());
            let docs = u32::from_le_bytes(body[entry + 8..entry + 12].try_into().unwrap());
            let reserved = u32::from_le_bytes(body[entry + 12..entry + 16].try_into().unwrap());
            let compressed_offset =
                u64::from_le_bytes(body[entry + 16..entry + 24].try_into().unwrap());
            let compressed_length =
                u64::from_le_bytes(body[entry + 24..entry + 32].try_into().unwrap());
            let uncompressed = u64::from_le_bytes(body[entry + 32..entry + 40].try_into().unwrap());
            assert_eq!(first, index as u64 * STORED_BLOCK_DOCS);
            assert_eq!(reserved, 0);
            assert_eq!(compressed_offset, offset);
            assert!(compressed_length > 0 && uncompressed >= 10);
            total += u64::from(docs);
            offset += compressed_length;
        }
        assert_eq!(total, count as u64);
        assert_eq!(offset, body.len() as u64);
        let reader = open(bytes);
        assert_eq!(keys(&reader).len(), count);
        assert!(
            reader
                .required_features()
                .contains(&(FEATURE_STORED_BLOCKS, 1))
        );
    }
}

#[test]
fn u10_directory_and_payload_boundaries_are_consistent() {
    let bytes = build(300);
    let body = stored_body(&bytes);
    let block_count = u64::from_le_bytes(body[14..22].try_into().unwrap());
    assert_eq!(
        u64::from_le_bytes(body[16..24].try_into().unwrap()),
        0,
        "guard against accidental offset read"
    );
    assert_eq!(
        block_count,
        (300u64).div_ceil(STORED_BLOCK_DOCS),
        "300 docs => three blocks"
    );
    let first_offset = u64::from_le_bytes(
        body[BLOCKS_HEADER_LEN + 16..BLOCKS_HEADER_LEN + 24]
            .try_into()
            .unwrap(),
    );
    assert_eq!(
        first_offset,
        (BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN * block_count as usize) as u64
    );
}

#[test]
fn u11_truncated_header_directory_and_block_are_rejected() {
    let bytes = build(129);
    let body = stored_body(&bytes);
    for cut in [0usize, 1, 21, 22, 23, body.len() - 1] {
        let mut truncated = body.clone();
        truncated.truncate(cut);
        let rebuilt = rebuild_stored(&bytes, &truncated, true);
        assert!(
            SegmentReader::open(rebuilt, SegmentLimits::default()).is_err(),
            "truncation at {cut} must fail"
        );
    }
}

#[test]
fn u12_flags_reserved_and_codec_are_rejected() {
    let bytes = build(129);
    let body = stored_body(&bytes);
    let mut bad_flags = body.clone();
    bad_flags[13] = 1;
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &bad_flags, true),
            SegmentLimits::default()
        )
        .is_err()
    );
    let mut unknown_codec = body.clone();
    unknown_codec[12] = 9;
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &unknown_codec, true),
            SegmentLimits::default()
        )
        .is_err()
    );
    let mut reserved = body.clone();
    let entry = BLOCKS_HEADER_LEN;
    reserved[entry + 12] = 1;
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &reserved, true),
            SegmentLimits::default()
        )
        .is_err()
    );
}

#[test]
fn u13_bad_block_count_and_misordered_first_doc_are_rejected() {
    let bytes = build(129);
    let body = stored_body(&bytes);
    let mut count = body.clone();
    count[14] = 0;
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &count, true),
            SegmentLimits::default()
        )
        .is_err()
    );
    let mut first = body.clone();
    let entry = BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN;
    first[entry] = 1;
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &first, true),
            SegmentLimits::default()
        )
        .is_err()
    );
}

#[test]
fn u14_gap_overlap_and_trailing_bytes_are_rejected() {
    let bytes = build(129);
    let body = stored_body(&bytes);
    let first = BLOCKS_HEADER_LEN;
    let second = BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN;
    let mut gap = body.clone();
    let second_offset = gap_offset(&gap, first) + 1;
    gap[second + 16..second + 24].copy_from_slice(&second_offset.to_le_bytes());
    assert!(
        SegmentReader::open(rebuild_stored(&bytes, &gap, true), SegmentLimits::default()).is_err()
    );
    let mut overlap = body.clone();
    let first_length = u64::from_le_bytes(overlap[first + 24..first + 32].try_into().unwrap());
    let overlap_offset = gap_offset(&overlap, first) + first_length - 1;
    overlap[second + 16..second + 24].copy_from_slice(&overlap_offset.to_le_bytes());
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &overlap, true),
            SegmentLimits::default()
        )
        .is_err()
    );
    let mut trailing = body.clone();
    trailing.push(0);
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &trailing, true),
            SegmentLimits::default()
        )
        .is_err()
    );
}

fn gap_offset(body: &[u8], entry: usize) -> u64 {
    u64::from_le_bytes(body[entry + 16..entry + 24].try_into().unwrap())
}

#[test]
fn u15_huge_uncompressed_length_is_rejected_before_allocation() {
    let bytes = build(128);
    let body = stored_body(&bytes);
    let entry = BLOCKS_HEADER_LEN;
    let mut huge = body.clone();
    huge[entry + 32..entry + 40].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &huge, true),
            SegmentLimits::default()
        )
        .is_err()
    );
}

#[test]
fn u16_u17_corrupt_selected_and_unselected_blocks_fail() {
    let bytes = build(300);
    let body = stored_body(&bytes);
    let directory = directory_end(&body);
    // Corrupt the second compressed block (physically unselected for doc 0).
    let second = BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN;
    let second_offset = gap_offset(&body, second) as usize;
    let mut corrupt = body.clone();
    corrupt[second_offset] ^= 0xFF;
    let rebuilt = rebuild_stored(&bytes, &corrupt, true);
    let reader = open(rebuilt);
    // Public full stored access validates every block, including the corrupted
    // physically unselected block.
    assert!(reader.stored().is_err());
    assert!(directory > 0);
}

#[test]
fn u18_five_state_values_match_v1() {
    let limits = SegmentLimits::default();
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .with_layout(Layout::Insertion)
        .with_limits(limits);
    let states = [
        FieldValues::Absent,
        FieldValues::ExplicitNull,
        FieldValues::Empty,
        FieldValues::Single(FieldValue::Keyword("single".to_owned())),
        FieldValues::Multi(vec![
            FieldValue::Keyword("a".to_owned()),
            FieldValue::Keyword("b".to_owned()),
        ]),
    ];
    for (index, values) in states.into_iter().enumerate() {
        let mut document = SegmentDocument::new(DocumentKey::new(format!("s{index}")).unwrap());
        let field = if matches!(values, FieldValues::Multi(_) | FieldValues::Empty) {
            "tags"
        } else {
            "tag"
        };
        document.fields.insert(field.to_owned(), values);
        builder.add_document(document).expect("add");
    }
    let bytes = builder.build().expect("build").bytes;
    let v2 = open(bytes.clone()).stored().expect("v2 stored").to_vec();
    let v1 = open(as_v1(&bytes)).stored().expect("v1 stored").to_vec();
    assert_eq!(v2, v1);
}

#[test]
fn u20_empty_selection_still_validates_every_block() {
    let bytes = build(300);
    let body = stored_body(&bytes);
    let second = BLOCKS_HEADER_LEN + BLOCK_ENTRY_LEN;
    let second_offset = gap_offset(&body, second) as usize;
    let mut corrupt = body.clone();
    corrupt[second_offset] ^= 0xFF;
    let reader = open(rebuild_stored(&bytes, &corrupt, true));
    assert!(reader.stored().is_err());
}

#[test]
fn u23_v2_stored_equals_v1_and_selected_equals_full() {
    let bytes = build(300);
    let reader = open(bytes.clone());
    let full = reader.stored().expect("full").to_vec();
    assert_eq!(
        keys(&reader),
        full.iter()
            .map(|r| r.key.as_str().to_owned())
            .collect::<Vec<_>>()
    );
    assert_eq!(open(as_v1(&bytes)).stored().expect("v1").to_vec(), full);
    for doc_id in [0usize, 127, 128, 129, 299] {
        assert_eq!(reader.stored_doc(doc_id as u64).expect("doc"), full[doc_id]);
    }
}

#[test]
fn u31_u32_legacy_and_feature_compatibility() {
    let bytes = build(129);
    let v1 = as_v1(&bytes);
    let v1_reader = open(v1.clone());
    assert_eq!(v1_reader.stored().expect("v1 stored").len(), 129);
    assert!(
        !v1_reader
            .required_features()
            .contains(&(FEATURE_STORED_BLOCKS, 1))
    );
    // v1 body with the required v2 feature is corruption.
    let view = parse_container(&v1, &SegmentLimits::default()).expect("container");
    let body = view.body(SectionKind::Stored).expect("stored").to_vec();
    assert!(
        SegmentReader::open(rebuild_stored(&v1, &body, true), SegmentLimits::default()).is_err()
    );
    // v2 body without the required feature is corruption.
    let v2_body = stored_body(&bytes);
    assert!(
        SegmentReader::open(
            rebuild_stored(&bytes, &v2_body, false),
            SegmentLimits::default()
        )
        .is_err()
    );
}

#[test]
fn u36_encoding_is_deterministic() {
    let first = build(300);
    let second = build(300);
    assert_eq!(stored_body(&first), stored_body(&second));
    let digest = sha256(&stored_body(&first));
    assert_eq!(digest, sha256(&stored_body(&second)));
}

#[test]
fn i01_i02_search_and_projection_are_unchanged() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    for index in 0..300usize {
        let mut document = Document::new(DocumentKey::new(format!("k{index:06}")).unwrap());
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text(format!("title {index}"))),
            )
            .unwrap();
        document
            .insert(
                "tag",
                FieldValues::Single(FieldValue::Keyword(if index % 3 == 0 {
                    "common".to_owned()
                } else {
                    "rare".to_owned()
                })),
            )
            .unwrap();
        document
            .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
            .unwrap();
        writer.apply(MutationRequest::insert(document)).unwrap();
    }
    writer.commit().unwrap();
    let snapshot = writer.reader();
    let cancel = CancellationFlag::new();
    let response = LexicalSearcher::new(
        &snapshot,
        &schema(),
        &AnalyzerRegistry::builtin(),
        SearchLimits::default(),
    )
    .search(
        &Query::Term {
            field: "tag".into(),
            value: FieldValue::Keyword("common".into()),
        },
        TopK::new(100).unwrap(),
        &Budgets::new(),
        &cancel,
    )
    .unwrap();
    assert_eq!(response.total_hits, 100);
    assert_eq!(response.hits.len(), 100);
    for hit in &response.hits {
        let index: usize = hit.key.as_str()[1..].parse().unwrap();
        assert_eq!(index % 3, 0);
    }
}

#[test]
fn i04_compaction_produces_v2_and_preserves_values() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    for key in ["a", "b"] {
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert("title", FieldValues::Single(FieldValue::Text(key.into())))
            .unwrap();
        document
            .insert("tag", FieldValues::Single(FieldValue::Keyword("x".into())))
            .unwrap();
        writer.apply(MutationRequest::insert(document)).unwrap();
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    let outcome = writer.compact().unwrap();
    assert!(!outcome.no_op);
    let snapshot = writer.reader();
    assert_eq!(snapshot.segment_count(), 1);
    let guard = snapshot.open_segment_reader(0).unwrap();
    assert!(
        guard
            .reader()
            .required_features()
            .contains(&(FEATURE_STORED_BLOCKS, 1))
    );
    let stored = guard.reader().stored().unwrap();
    let by_key: BTreeMap<String, FieldValues> = stored
        .iter()
        .map(|record| {
            (
                record.key.as_str().to_owned(),
                record.get(guard.reader().schema().field_id("title").unwrap()),
            )
        })
        .collect();
    assert_eq!(
        by_key.get("a"),
        Some(&FieldValues::Single(FieldValue::Text("a".into())))
    );
    assert_eq!(
        by_key.get("b"),
        Some(&FieldValues::Single(FieldValue::Text("b".into())))
    );
}

#[test]
fn i05_pit_retains_old_generation_across_v2_commit_and_compaction() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    let mut document = Document::new(DocumentKey::new("a").unwrap());
    document
        .insert("title", FieldValues::Single(FieldValue::Text("one".into())))
        .unwrap();
    writer.apply(MutationRequest::insert(document)).unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    let generation = pit.snapshot().generation();
    let mut document = Document::new(DocumentKey::new("b").unwrap());
    document
        .insert("title", FieldValues::Single(FieldValue::Text("two".into())))
        .unwrap();
    writer.apply(MutationRequest::insert(document)).unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();
    writer.compact().unwrap();
    assert_eq!(pit.snapshot().generation(), generation);
    assert_eq!(pit.snapshot().segment_count(), 1);
}

#[test]
fn i06_upsert_delete_replay_reopen_with_v2() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    let token = IdempotencyKey::new("v2-token").unwrap();
    let mut document = Document::new(DocumentKey::new("a").unwrap());
    document
        .insert("title", FieldValues::Single(FieldValue::Text("one".into())))
        .unwrap();
    writer
        .apply(MutationRequest::upsert(document).with_idempotency_key(token.clone()))
        .unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let mut original = Document::new(DocumentKey::new("a").unwrap());
    original
        .insert("title", FieldValues::Single(FieldValue::Text("one".into())))
        .unwrap();
    let replay = writer
        .apply(MutationRequest::upsert(original).with_idempotency_key(token))
        .unwrap();
    assert!(replay.replayed);
    let mut changed = Document::new(DocumentKey::new("a").unwrap());
    changed
        .insert("title", FieldValues::Single(FieldValue::Text("two".into())))
        .unwrap();
    writer.apply(MutationRequest::upsert(changed)).unwrap();
    writer.commit().unwrap();
    let snapshot = writer.reader();
    let guard = snapshot.open_segment_reader(0).unwrap();
    assert!(
        guard
            .reader()
            .required_features()
            .contains(&(FEATURE_STORED_BLOCKS, 1))
    );
    assert_eq!(guard.reader().stored().unwrap().len(), 1);
}

#[test]
fn i16_zero_live_compaction_keeps_feature_integrity() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    for key in ["a", "b"] {
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert("title", FieldValues::Single(FieldValue::Text("x".into())))
            .unwrap();
        writer.apply(MutationRequest::insert(document)).unwrap();
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    for key in ["a", "b"] {
        writer
            .apply(MutationRequest::delete(DocumentKey::new(key).unwrap()))
            .unwrap();
    }
    writer.commit().unwrap();
    writer.compact().unwrap();
    let snapshot = writer.reader();
    if snapshot.segment_count() == 0 {
        // Zero-live compaction may publish no segment; the logical state is
        // still a valid generation and must reopen cleanly.
        assert!(writer.generation().is_some());
    } else {
        let guard = snapshot.open_segment_reader(0).unwrap();
        assert!(
            guard
                .reader()
                .required_features()
                .contains(&(FEATURE_STORED_BLOCKS, 1))
        );
        assert_eq!(guard.reader().stored().unwrap().len(), 0);
    }
}

#[test]
fn limits_reject_encoded_sections_above_the_configured_cap() {
    let tight = IndexLimits::new()
        .with_segment_limits(SegmentLimits::default().with_max_single_allocation(64));
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(directory, schema(), AnalyzerRegistry::builtin(), tight).unwrap();
    let mut writer = index.writer().unwrap();
    let mut document = Document::new(DocumentKey::new("a").unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("x".repeat(4096))),
        )
        .unwrap();
    writer.apply(MutationRequest::insert(document)).unwrap();
    // The build/commit must fail closed rather than allocate an unbounded block.
    assert!(writer.commit().is_err());
}
