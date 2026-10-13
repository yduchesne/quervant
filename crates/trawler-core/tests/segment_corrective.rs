//! PR 5 corrective adversarial tests (C5-U/C5-I/C5-P) for decoder hardening.

use std::rc::Rc;

use trawler_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use trawler_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use trawler_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use trawler_core::contract::value::{FieldType, FieldValue};
use trawler_core::segment::column::{ColumnReader, encode_columns};
use trawler_core::segment::dictionary::DictionaryReader;
use trawler_core::segment::format::{
    ByteWriter, ContainerBuilder, ContainerKind, SectionKind, parse_container,
};
use trawler_core::segment::manifest::Manifest;
use trawler_core::segment::postings::PostingsReader;
use trawler_core::segment::remap::DocRemap;
use trawler_core::segment::{
    CodecSchema, Layout, SegmentBuilder, SegmentDocument, SegmentError, SegmentLimits,
    SegmentReader,
};

const HEADER_END: usize = 6 + 46;

fn small_schema() -> CodecSchema {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "a",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, true, false),
        )],
        None,
    )
    .unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn columnar_schema() -> CodecSchema {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "tags",
            FieldType::Keyword,
            Cardinality::Multi,
            FieldOptions::new(true, true, true),
        )],
        None,
    )
    .unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn docs(n: usize) -> Vec<SegmentDocument> {
    (0..n)
        .map(|i| {
            let mut doc = SegmentDocument::new(DocumentKey::new(format!("d{i}")).unwrap());
            doc.fields.insert(
                "tags".to_owned(),
                FieldValues::Multi(vec![
                    FieldValue::Keyword(format!("t{i}")),
                    FieldValue::Keyword("shared".to_owned()),
                ]),
            );
            doc
        })
        .collect()
}

fn stored_only_segment(n: usize) -> Vec<u8> {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "a",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(false, true, false),
        )],
        None,
    )
    .unwrap();
    let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin())
        .unwrap()
        .with_layout(Layout::Insertion);
    for i in 0..n {
        let mut doc = SegmentDocument::new(DocumentKey::new(format!("k{i}")).unwrap());
        doc.fields.insert(
            "a".to_owned(),
            FieldValues::Single(FieldValue::Keyword(format!("v{i}"))),
        );
        builder.add_document(doc).unwrap();
    }
    builder.build().unwrap().bytes
}

fn sample_segment() -> Vec<u8> {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .unwrap();
    let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin()).unwrap();
    for i in 0..4 {
        let mut doc = SegmentDocument::new(DocumentKey::new(format!("s{i}")).unwrap());
        doc.fields.insert(
            "body".to_owned(),
            FieldValues::Single(FieldValue::Text(format!("hello world {i}"))),
        );
        doc.fields.insert(
            "tags".to_owned(),
            FieldValues::Multi(vec![FieldValue::Keyword("x".to_owned())]),
        );
        builder.add_document(doc).unwrap();
    }
    builder.build().unwrap().bytes
}

// --- R5-I01: dictionary allocation/work -------------------------------------

#[test]
fn c5_u02_dictionary_field_count_is_preflighted() {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(1_000_000);
    let bytes = writer.into_vec();
    let limits = SegmentLimits::default().with_max_single_allocation(1024);
    assert!(matches!(
        DictionaryReader::new(&bytes, &limits),
        Err(SegmentError::LimitExceeded { .. }) | Err(SegmentError::Truncated { .. })
    ));
}

#[test]
fn c5_u03_dictionary_term_count_is_preflighted() {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(1);
    writer.u32(0);
    writer.u64(1_000_000);
    let bytes = writer.into_vec();
    let limits = SegmentLimits::default().with_max_single_allocation(1024);
    assert!(matches!(
        DictionaryReader::new(&bytes, &limits),
        Err(SegmentError::LimitExceeded { .. }) | Err(SegmentError::Truncated { .. })
    ));
}

#[test]
fn c5_u01_dictionary_valid_at_limit_still_decodes() {
    // Four short terms fit within a small allocation budget.
    let mut body = ByteWriter::new();
    body.u16(1);
    body.u32(1); // one field
    body.u32(0); // field id
    body.u64(2); // two terms
    for term in ["a", "b"] {
        body.len_prefixed_u16(term.as_bytes()).unwrap();
        body.u64(1); // doc_freq
        body.u64(0); // offset
        body.u64(1); // length
    }
    let bytes = body.into_vec();
    let limits = SegmentLimits::default().with_max_single_allocation(4096);
    let reader = DictionaryReader::new(&bytes, &limits).expect("valid dictionary");
    assert_eq!(reader.field(0).unwrap().len(), 2);
    assert!(reader.lookup(0, "a").is_some());
}

// --- R5-I02: column geometry ------------------------------------------------

#[test]
fn c5_u06_column_doc_count_mismatch_rejected() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    assert!(
        ColumnReader::open_with_doc_count(&schema, &body, &SegmentLimits::default(), Some(5))
            .is_err()
    );
    // Correct count passes.
    assert!(
        ColumnReader::open_with_doc_count(&schema, &body, &SegmentLimits::default(), Some(4))
            .is_ok()
    );
}

#[test]
fn c5_u07_forged_directory_length_rejected() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    let mut forged = body.clone();
    for byte in &mut forged[44..52] {
        *byte = 0;
    }
    assert!(ColumnReader::open(&schema, &forged, &SegmentLimits::default()).is_err());
}

#[test]
fn c5_u09_forged_first_doc_rejected() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    let mut forged = body.clone();
    forged[HEADER_END..HEADER_END + 8].copy_from_slice(&7u64.to_le_bytes());
    assert!(ColumnReader::open(&schema, &forged, &SegmentLimits::default()).is_err());
}

#[test]
fn c5_u11_forged_values_length_rejected() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    let mut forged = body.clone();
    let values_length = HEADER_END + 8 + 4 + 8 + 8;
    forged[values_length..values_length + 8].copy_from_slice(&0u64.to_le_bytes());
    assert!(ColumnReader::open(&schema, &forged, &SegmentLimits::default()).is_err());
}

#[test]
fn c5_u10_forged_state_offset_rejected() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    let mut forged = body.clone();
    let state_offset = HEADER_END + 8 + 4;
    forged[state_offset..state_offset + 8].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(ColumnReader::open(&schema, &forged, &SegmentLimits::default()).is_err());
}

#[test]
fn c5_i01_valid_columns_still_read_all_docs() {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(5), 3, &SegmentLimits::default()).unwrap();
    let reader = ColumnReader::open(&schema, &body, &SegmentLimits::default()).unwrap();
    for doc_id in 0..5u64 {
        assert!(reader.value(0, doc_id).unwrap().is_some());
    }
}

// --- R5-I03/I04: manifest count and features --------------------------------

fn manifest_payload_with_required_feature(schema_bytes: &[u8], feature: (u16, u16)) -> Vec<u8> {
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(schema_bytes);
    payload.u32(1); // one segment
    payload.len_prefixed_u16(b"segments/a").unwrap();
    payload.len_prefixed_u16(b"objects/a").unwrap();
    payload.u8(0);
    payload.u64(1);
    payload.bytes(&[0u8; 32]);
    payload.u8(0); // no time bounds
    payload.u32(1); // one required feature
    payload.u16(feature.0);
    payload.u16(feature.1);
    payload.u32(0); // no optional features
    payload.u32(0); // no manifest-level required features
    payload.u32(0);
    payload.into_vec()
}

fn manifest_container(payload: Vec<u8>) -> Vec<u8> {
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    builder.section(SectionKind::Manifest, 0, 0, payload);
    builder.build().unwrap()
}

#[test]
fn c5_u16_manifest_segment_count_is_preflighted() {
    let schema_bytes = small_schema().encode().unwrap();
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(u32::MAX);
    let limits = SegmentLimits::default();
    assert!(matches!(
        Manifest::decode(&manifest_container(payload.into_vec()), &limits),
        Err(SegmentError::LimitExceeded { .. }) | Err(SegmentError::Truncated { .. })
    ));
}

#[test]
fn c5_u20_manifest_unknown_required_segment_feature_fails_closed() {
    let schema_bytes = small_schema().encode().unwrap();
    let payload = manifest_payload_with_required_feature(&schema_bytes, (0xbeef, 1));
    assert!(matches!(
        Manifest::decode(&manifest_container(payload), &SegmentLimits::default()),
        Err(SegmentError::UnsupportedFeature { .. })
    ));
}

#[test]
fn c5_u19_manifest_unknown_required_container_feature_fails_closed() {
    let schema_bytes = small_schema().encode().unwrap();
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(0); // no segments
    payload.u32(0);
    payload.u32(0);
    payload.u32(0);
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    builder.require_feature(0xdead, 1);
    builder.section(SectionKind::Manifest, 0, 0, payload.into_vec());
    let bytes = builder.build().unwrap();
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::UnsupportedFeature { .. })
    ));
}

#[test]
fn c5_u22_manifest_unknown_optional_feature_accepted() {
    let schema_bytes = small_schema().encode().unwrap();
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(0); // segment_count
    payload.u32(0); // required features
    payload.u32(1); // one optional feature
    payload.u16(0xbeef);
    payload.u16(1);
    let decoded = Manifest::decode(
        &manifest_container(payload.into_vec()),
        &SegmentLimits::default(),
    )
    .expect("optional feature ignored");
    assert_eq!(decoded.optional_features, vec![(0xbeef, 1)]);
}

// --- R5-I07: sibling budget audit -------------------------------------------

#[test]
fn c5_u39_schema_field_count_is_preflighted() {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(u32::MAX);
    assert!(matches!(
        CodecSchema::decode(&writer.into_vec(), &SegmentLimits::default()),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

#[test]
fn c5_u37_posting_frequency_bomb_is_rejected() {
    let mut writer = ByteWriter::new();
    writer.u8(1); // positional
    writer.u64(1); // posting_doc_count
    writer.u64(1); // freq_total
    writer.varint(0); // doc delta
    writer.varint(u64::MAX); // frequency
    let bytes = writer.into_vec();
    let limits = SegmentLimits::default().with_max_decoded_entries(4);
    let mut reader = PostingsReader::new(&bytes, 1, &limits).expect("header");
    assert!(matches!(
        reader.next(),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

#[test]
fn c5_u38_remap_count_is_preflighted() {
    assert!(matches!(
        DocRemap::decode(&[1], 1_000_000, &SegmentLimits::default()),
        Err(SegmentError::Truncated { .. }) | Err(SegmentError::LimitExceeded { .. })
    ));
}

#[test]
fn c5_u41_geo_bounds_count_is_preflighted() {
    let schema_bytes = small_schema().encode().unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
    builder.section(SectionKind::Schema, 0, 0, schema_bytes);
    let mut geo = ByteWriter::new();
    geo.u32(u32::MAX);
    builder.section(SectionKind::GeoBounds, 0, 0, geo.into_vec());
    let bytes = builder.build().unwrap();
    assert!(matches!(
        SegmentReader::open(bytes, SegmentLimits::default()),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

// --- R5-I06: stored reader bounds -------------------------------------------

#[test]
fn c5_u31_stored_cache_reuse_and_out_of_range() {
    let bytes = stored_only_segment(5);
    let reader = SegmentReader::open(bytes, SegmentLimits::default()).expect("open");
    let first: Rc<Vec<_>> = reader.stored().expect("stored");
    let second = reader.stored().expect("stored");
    assert!(Rc::ptr_eq(&first, &second), "stored records are cached");
    assert_eq!(first.len(), 5);
    assert!(reader.stored_doc(9).is_err());
}

#[test]
fn c5_u32_stored_budget_exceeded_is_typed() {
    let bytes = stored_only_segment(5);
    let limits = SegmentLimits::default().with_max_decoded_entries(1);
    let reader = SegmentReader::open(bytes, limits).expect("open");
    assert!(matches!(
        reader.stored(),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

// --- C5-P03: truncation and no-panic ----------------------------------------

#[test]
fn c5_p03_truncation_never_panics_and_fails_typed() {
    let valid = sample_segment();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        for length in 0..valid.len() {
            let prefix = valid[..length].to_vec();
            let outcome = SegmentReader::open(prefix, SegmentLimits::default());
            assert!(outcome.is_err(), "prefix {length} unexpectedly decoded");
        }
    }));
    assert!(result.is_ok(), "decoder panicked on a truncated prefix");
}

// --- Additional column-geometry coverage ------------------------------------

fn valid_column_body() -> (CodecSchema, Vec<u8>) {
    let schema = columnar_schema();
    let body = encode_columns(&schema, &docs(4), 2, &SegmentLimits::default()).unwrap();
    (schema, body)
}

#[test]
fn c5_column_geometry_branch_coverage() {
    let limits = SegmentLimits::default();
    let (schema, body) = valid_column_body();

    // Unknown field id.
    let mut m = body.clone();
    m[6..10].copy_from_slice(&999u32.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Type tag mismatch.
    let mut m = body.clone();
    m[10] = 99;
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Layout mismatch.
    let mut m = body.clone();
    m[11] = 1;
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Block row count mismatch.
    let mut m = body.clone();
    m[HEADER_END + 8..HEADER_END + 12].copy_from_slice(&9u32.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Directory overlaps the header (dir_offset below previous_end).
    let mut m = body.clone();
    m[36..44].copy_from_slice(&0u64.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Directory offset overflow.
    let mut m = body.clone();
    m[36..44].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Invalid state tag.
    let mut m = body.clone();
    let dir_offset = u64::from_le_bytes(body[36..44].try_into().unwrap()) as usize;
    let dir_len = u64::from_le_bytes(body[44..52].try_into().unwrap()) as usize;
    let data_base = dir_offset + dir_len;
    m[data_base] = 9;
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Offset beyond the value area.
    let mut m = body.clone();
    let values_offset = u64::from_le_bytes(
        m[HEADER_END + 8 + 4 + 8..HEADER_END + 8 + 4 + 8 + 8]
            .try_into()
            .unwrap(),
    ) as usize;
    let table = data_base + values_offset;
    m[table + 8..table + 16].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Terminal offset mismatch.
    let mut m = body.clone();
    let terminal = table + 2 * 8;
    m[terminal..terminal + 8].copy_from_slice(&123u64.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());

    // Values extent overflow.
    let mut m = body.clone();
    let values_length = HEADER_END + 8 + 4 + 8 + 8;
    m[values_length..values_length + 8].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(ColumnReader::open(&schema, &m, &limits).is_err());
}

// --- Reader cross-section coherence -----------------------------------------

fn replace_section(original: &[u8], kind: SectionKind, new_body: Vec<u8>) -> Vec<u8> {
    let view = parse_container(original, &SegmentLimits::default()).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in view.required_features() {
        if *id != trawler_core::segment::format::FEATURE_BASELINE {
            builder.require_feature(*id, *version);
        }
    }
    for (id, version) in view.optional_features() {
        builder.optional_feature(*id, *version);
    }
    for entry in view.sections() {
        let body = if entry.kind == kind {
            new_body.clone()
        } else {
            view.body(entry.kind).unwrap().to_vec()
        };
        builder.section(entry.kind, entry.flags, entry.aux, body);
    }
    builder.build().unwrap()
}

#[test]
fn c5_reader_rejects_forged_columns_and_coherence() {
    let valid = sample_segment();
    let limits = SegmentLimits::default();
    let view = parse_container(&valid, &limits).unwrap();
    let columns_kind = SectionKind::Columns;
    if let Some(body) = view.body(columns_kind) {
        let mut forged = body.to_vec();
        let values_length = HEADER_END + 8 + 4 + 8 + 8;
        forged[values_length..values_length + 8].copy_from_slice(&0u64.to_le_bytes());
        let rebuilt = replace_section(&valid, columns_kind, forged);
        assert!(
            SegmentReader::open(rebuilt, limits).is_err(),
            "eager column validation must reject forged geometry"
        );
    }

    // Dictionary present but POSTINGS removed -> MissingSection.
    let view = parse_container(&valid, &limits).unwrap();
    if view.body(SectionKind::Dictionary).is_some() {
        let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
        for (id, version) in view.required_features() {
            if *id != trawler_core::segment::format::FEATURE_BASELINE {
                builder.require_feature(*id, *version);
            }
        }
        for entry in view.sections() {
            if entry.kind == SectionKind::Postings {
                continue;
            }
            builder.section(
                entry.kind,
                entry.flags,
                entry.aux,
                view.body(entry.kind).unwrap().to_vec(),
            );
        }
        let rebuilt = builder.build().unwrap();
        assert!(matches!(
            SegmentReader::open(rebuilt, limits),
            Err(SegmentError::MissingSection { .. })
        ));
    }

    // Stored count mismatch (forged header) is rejected at open.
    let view = parse_container(&valid, &limits).unwrap();
    if let Some(body) = view.body(SectionKind::Stored) {
        let mut forged = body.to_vec();
        forged[2..10].copy_from_slice(&999u64.to_le_bytes());
        let rebuilt = replace_section(&valid, SectionKind::Stored, forged);
        assert!(SegmentReader::open(rebuilt, limits).is_err());
    }
}

// --- Dictionary / stored error paths ----------------------------------------

#[test]
fn c5_dictionary_retained_budget_and_errors() {
    let limits = SegmentLimits::default().with_max_single_allocation(64);

    // Field count overflow.
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u32(u32::MAX);
    assert!(matches!(
        DictionaryReader::new(&w.into_vec(), &limits),
        Err(SegmentError::LimitExceeded { .. })
    ));

    // Invalid term UTF-8.
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u32(1);
    w.u32(0);
    w.u64(1);
    w.u16(1);
    w.u8(0xff);
    w.u64(1);
    w.u64(0);
    w.u64(1);
    assert!(DictionaryReader::new(&w.into_vec(), &limits).is_err());

    // Zero doc_freq.
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u32(1);
    w.u32(0);
    w.u64(1);
    w.u16(1);
    w.u8(b'a');
    w.u64(0);
    w.u64(0);
    w.u64(1);
    assert!(DictionaryReader::new(&w.into_vec(), &limits).is_err());
}

#[test]
fn c5_stored_truncation_and_count_mismatch() {
    // Truncated stored body.
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u64(5);
    assert!(matches!(
        trawler_core::segment::stored::decode_stored(
            &small_schema(),
            &w.into_vec(),
            &SegmentLimits::default()
        ),
        Err(SegmentError::Truncated { .. })
    ));
}
