//! PR 5 Amendment 04: decoder budget consistency (A4-* / U*).
//!
//! Expected charges are computed from fixture lengths and `size_of::<T>()`,
//! independently of the production budget code. Boundary tests assert the typed
//! `LimitExceeded` at exact and one-below cumulative budgets, and shared
//! budgets across sibling records/children.

use quervant_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, JsonNumber, JsonValue};
use quervant_core::segment::dictionary::{DictionaryEntry, DictionaryReader};
use quervant_core::segment::format::ByteWriter;
use quervant_core::segment::remap::DocRemap;
use quervant_core::segment::stored::{decode_stored, encode_stored};
use quervant_core::segment::value::{decode_field_values, decode_json, decode_scalar};
use quervant_core::segment::{
    CodecSchema, Layout, SegmentBuilder, SegmentDocument, SegmentError, SegmentLimits,
    SegmentReader,
};

fn limits_with_budget(budget: u64) -> SegmentLimits {
    SegmentLimits::default().with_max_section_decode_bytes(budget)
}

fn expect_limit(result: Result<impl std::fmt::Debug, SegmentError>, requested: u64) {
    match result {
        Err(SegmentError::LimitExceeded {
            requested: actual, ..
        }) => assert_eq!(actual, requested),
        other => panic!("expected LimitExceeded({requested}), got {other:?}"),
    }
}

// --- Dictionary (A4-04) -----------------------------------------------------

fn dictionary_body(fields: &[(u32, &[(&str, u64)])]) -> Vec<u8> {
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u32(u32::try_from(fields.len()).unwrap());
    for (field_id, terms) in fields {
        w.u32(*field_id);
        w.u64(u64::try_from(terms.len()).unwrap());
        for (term, doc_freq) in *terms {
            w.len_prefixed_u16(term.as_bytes()).unwrap();
            w.u64(*doc_freq);
            w.u64(0);
            w.u64(1);
        }
    }
    w.into_vec()
}

#[test]
fn a4_u04_u05_dictionary_outer_vector_boundary() {
    let bytes = dictionary_body(&[(0, &[])]); // one empty field
    let outer = std::mem::size_of::<(u32, Vec<DictionaryEntry>)>() as u64;
    let reader = DictionaryReader::new(&bytes, &limits_with_budget(outer)).unwrap();
    assert_eq!(reader.fields().len(), 1);
    expect_limit(
        DictionaryReader::new(&bytes, &limits_with_budget(outer - 1)),
        outer,
    );
    // Empty dictionary decodes with zero charge.
    let empty = dictionary_body(&[]);
    let reader = DictionaryReader::new(&empty, &limits_with_budget(0)).unwrap();
    assert!(reader.fields().is_empty());
}

#[test]
fn a4_u04_u06_dictionary_inner_entry_boundary() {
    let bytes = dictionary_body(&[(0, &[("a", 1), ("b", 2)])]);
    let outer = std::mem::size_of::<(u32, Vec<DictionaryEntry>)>() as u64;
    let entries = 2 * std::mem::size_of::<DictionaryEntry>() as u64;
    let full = outer + entries + 1 + 1;
    let reader = DictionaryReader::new(&bytes, &limits_with_budget(full)).unwrap();
    assert_eq!(reader.field(0).unwrap().len(), 2);
    assert_eq!(reader.lookup(0, "a").unwrap().doc_freq, 1);
    assert_eq!(reader.lookup(0, "b").unwrap().doc_freq, 2);
    expect_limit(
        DictionaryReader::new(&bytes, &limits_with_budget(full - 1)),
        full,
    );
}

#[test]
fn a4_u07_dictionary_order_utf8_duplicate_truncation() {
    // Nonascending terms.
    let bad = dictionary_body(&[(0, &[("b", 1), ("a", 1)])]);
    assert!(matches!(
        DictionaryReader::new(&bad, &SegmentLimits::default()),
        Err(SegmentError::DuplicateTerm { .. })
    ));
    // Invalid UTF-8.
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
    assert!(DictionaryReader::new(&w.into_vec(), &SegmentLimits::default()).is_err());
    // Truncated.
    assert!(DictionaryReader::new(&[1, 0, 1, 0, 0, 0], &SegmentLimits::default()).is_err());
}

// --- Schema (A4-05) ---------------------------------------------------------

fn codec_schema(analyzer: bool) -> CodecSchema {
    let mut field = FieldDefinition::new(
        "abc",
        FieldType::Text,
        Cardinality::Single,
        FieldOptions::indexed_stored(),
    );
    if analyzer {
        field = field.with_analyzer("standard");
    }
    let schema = Schema::new(vec![field], None).unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

#[test]
fn a4_u08_u09_schema_vector_and_name_boundary() {
    // No binding: charge = struct + name bytes.
    let schema = codec_schema(false);
    let bytes = schema.encode().unwrap();
    let full = std::mem::size_of::<quervant_core::segment::CodecField>() as u64 + 3;
    assert_eq!(
        CodecSchema::decode(&bytes, &limits_with_budget(full)).unwrap(),
        schema
    );
    expect_limit(
        CodecSchema::decode(&bytes, &limits_with_budget(full - 1)),
        full,
    );

    // With a binding: name + analyzer id + analyzer version payloads.
    let schema = codec_schema(true);
    let bytes = schema.encode().unwrap();
    let binding = schema.fields()[0].analyzer.as_ref().unwrap();
    let full = std::mem::size_of::<quervant_core::segment::CodecField>() as u64
        + 3
        + binding.id.len() as u64
        + binding.version.len() as u64;
    assert_eq!(
        CodecSchema::decode(&bytes, &limits_with_budget(full)).unwrap(),
        schema
    );
    expect_limit(
        CodecSchema::decode(&bytes, &limits_with_budget(full - 1)),
        full,
    );
}

#[test]
fn a4_u10_schema_invalid_and_truncated() {
    let schema = codec_schema(false);
    let bytes = schema.encode().unwrap();
    // First field layout: version u16(0..2), field_count u32(2..6), field_id
    // u32(6..10), name_len u16(10..12), name bytes(12..). Forge a 1-byte
    // invalid-UTF-8 name to exercise borrowed UTF-8 validation.
    let mut forged = schema.encode().unwrap();
    forged[10..12].copy_from_slice(&1u16.to_le_bytes());
    forged[12] = 0xff;
    assert!(CodecSchema::decode(&forged, &SegmentLimits::default()).is_err());
    // Truncated.
    assert!(CodecSchema::decode(&bytes[..bytes.len() / 2], &SegmentLimits::default()).is_err());
}

// --- Stored (A4-06) ---------------------------------------------------------

fn keyword_doc_schema() -> CodecSchema {
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "k",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(false, true, false),
        )],
        None,
    )
    .unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn stored_docs(n: usize) -> Vec<SegmentDocument> {
    (0..n)
        .map(|i| {
            let mut doc = SegmentDocument::new(DocumentKey::new(format!("k{i}")).unwrap());
            doc.fields.insert(
                "k".to_owned(),
                FieldValues::Single(FieldValue::Keyword("v".to_owned())),
            );
            doc
        })
        .collect()
}

#[test]
fn a4_u11_u12_stored_shared_budget() {
    let schema = keyword_doc_schema();
    let limits = SegmentLimits::default();
    let bytes = encode_stored(&schema, &stored_docs(2), &limits).unwrap();
    // Each record individually: key(2) + btree entry + keyword value string(1),
    // plus the record struct read from a two-call encode bound.
    let record = std::mem::size_of::<quervant_core::segment::StoredRecord>() as u64;
    let per_record = 2
        + (std::mem::size_of::<(u32, FieldValues)>() as u64
            + 3 * std::mem::size_of::<usize>() as u64)
        + 1;
    let full = 2 * record + 2 * per_record;
    assert_eq!(
        decode_stored(&schema, &bytes, &limits_with_budget(full))
            .unwrap()
            .len(),
        2
    );
    // One byte below the shared full budget fails, proving records share it.
    expect_limit(
        decode_stored(&schema, &bytes, &limits_with_budget(full - 1)),
        full,
    );
    // Empty stored section decodes with zero charge (version + count only).
    let empty = encode_stored(&schema, &[], &limits).unwrap();
    assert!(
        decode_stored(&schema, &empty, &limits_with_budget(0))
            .unwrap()
            .is_empty()
    );
}

#[test]
fn a4_u14_stored_key_and_invalid() {
    let schema = keyword_doc_schema();
    let limits = SegmentLimits::default();
    let mut doc = SegmentDocument::new(DocumentKey::new("longkey").unwrap());
    doc.fields.insert(
        "k".to_owned(),
        FieldValues::Single(FieldValue::Keyword("v".to_owned())),
    );
    let bytes = encode_stored(&schema, &[doc], &limits).unwrap();
    // Truncated key.
    assert!(decode_stored(&schema, &bytes[..4], &limits).is_err());
}

#[test]
fn a4_u15_stored_multi_value_and_nested_string() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    let codec = CodecSchema::from_contract(&schema, &bindings).unwrap();
    let mut doc = SegmentDocument::new(DocumentKey::new("k").unwrap());
    doc.fields.insert(
        "tags".to_owned(),
        FieldValues::Multi(vec![
            FieldValue::Keyword("x".to_owned()),
            FieldValue::Keyword("y".to_owned()),
        ]),
    );
    doc.fields.insert(
        "body".to_owned(),
        FieldValues::Single(FieldValue::Text("hello".to_owned())),
    );
    let limits = SegmentLimits::default();
    let bytes = encode_stored(&codec, &[doc], &limits).unwrap();
    // Large budget decodes; a tiny one fails typed.
    let decoded = decode_stored(&codec, &bytes, &SegmentLimits::default()).unwrap();
    assert_eq!(decoded.len(), 1);
    assert!(matches!(
        decode_stored(&codec, &bytes, &limits_with_budget(1)),
        Err(SegmentError::LimitExceeded { .. })
    ));
}

// --- Value / JSON (A4-07, A4-08) --------------------------------------------

#[test]
fn a4_u16_u17_nested_json_array_shared_budget() {
    // JSON array of two arrays, each with one string.
    let value = JsonValue::Array(vec![
        JsonValue::Array(vec![JsonValue::String("aaa".to_owned())]),
        JsonValue::Array(vec![JsonValue::String("bbb".to_owned())]),
    ]);
    let mut w = ByteWriter::new();
    quervant_core::segment::value::encode_json(&mut w, &value).unwrap();
    let bytes = w.into_vec();

    let array = std::mem::size_of::<JsonValue>() as u64;
    let string_header = std::mem::size_of::<String>() as u64;
    // Outer array(2 elements) + two inner arrays(1 each) vectors + two strings.
    let full = 4 * array + 6;
    let mut reader = quervant_core::segment::format::ByteReader::new(&bytes);
    assert_eq!(
        decode_json(&mut reader, &limits_with_budget(full), 0).unwrap(),
        value
    );
    let mut reader = quervant_core::segment::format::ByteReader::new(&bytes);
    expect_limit(
        decode_json(&mut reader, &limits_with_budget(full - 1), 0),
        full,
    );
    let _ = string_header;
}

#[test]
fn a4_u18_json_depth_count_and_truncation() {
    let deep = JsonValue::Array(vec![JsonValue::Array(vec![JsonValue::Null])]);
    let mut w = ByteWriter::new();
    quervant_core::segment::value::encode_json(&mut w, &deep).unwrap();
    let bytes = w.into_vec();
    assert!(
        decode_json(
            &mut quervant_core::segment::format::ByteReader::new(&bytes),
            &SegmentLimits::default(),
            129
        )
        .is_err()
    );
    assert!(
        decode_json(
            &mut quervant_core::segment::format::ByteReader::new(&[9]),
            &SegmentLimits::default(),
            0
        )
        .is_err()
    );
}

#[test]
fn a4_u19_u20_public_wrappers_and_ordering() {
    // Public wrappers create fresh budgets and preserve semantics.
    let value = JsonValue::Object(vec![
        ("b".to_owned(), JsonValue::Number(JsonNumber::U64(1))),
        ("a".to_owned(), JsonValue::Null),
    ]);
    let mut w = ByteWriter::new();
    quervant_core::segment::value::encode_json(&mut w, &value).unwrap();
    let bytes = w.into_vec();
    let mut reader = quervant_core::segment::format::ByteReader::new(&bytes);
    let decoded = decode_json(&mut reader, &SegmentLimits::default(), 0).unwrap();
    assert_eq!(decoded, value, "object member order preserved");

    // Scalar wrapper and field-values wrapper.
    let mut w = ByteWriter::new();
    quervant_core::segment::value::encode_scalar(
        &mut w,
        FieldType::Keyword,
        &FieldValue::Keyword("z".to_owned()),
    )
    .unwrap();
    let mut reader = quervant_core::segment::format::ByteReader::new(w.as_slice());
    assert_eq!(
        decode_scalar(&mut reader, FieldType::Keyword, &SegmentLimits::default()).unwrap(),
        FieldValue::Keyword("z".to_owned())
    );
    let mut w = ByteWriter::new();
    quervant_core::segment::value::encode_field_values(
        &mut w,
        FieldType::Keyword,
        &FieldValues::Multi(vec![
            FieldValue::Keyword("a".to_owned()),
            FieldValue::Keyword("b".to_owned()),
        ]),
        &SegmentLimits::default(),
    )
    .unwrap();
    let mut reader = quervant_core::segment::format::ByteReader::new(w.as_slice());
    assert_eq!(
        decode_field_values(&mut reader, FieldType::Keyword, &SegmentLimits::default()).unwrap(),
        FieldValues::Multi(vec![
            FieldValue::Keyword("a".to_owned()),
            FieldValue::Keyword("b".to_owned())
        ])
    );
}

// --- Remap (A4-09) ----------------------------------------------------------

fn remap_body(order: &[u64]) -> Vec<u8> {
    let remap = DocRemap::from_order(order.to_vec()).unwrap();
    remap.encode()
}

#[test]
fn a4_u22_identity_both_vector_boundary() {
    let identity = DocRemap::identity(4).encode();
    let full = 4 * 8 * 2;
    assert_eq!(
        DocRemap::decode(&identity, 4, &limits_with_budget(full)).unwrap(),
        DocRemap::identity(4)
    );
    expect_limit(
        DocRemap::decode(&identity, 4, &limits_with_budget(full - 1)),
        full,
    );
    // Empty identity has zero charge.
    assert!(DocRemap::decode(&[0], 0, &limits_with_budget(0)).is_ok());
}

#[test]
fn a4_u23_explicit_two_vector_boundary() {
    let bytes = remap_body(&[2, 0, 1]);
    let full = 3 * 8 * 2;
    let decoded = DocRemap::decode(&bytes, 3, &limits_with_budget(full)).unwrap();
    assert!(!decoded.is_identity());
    assert_eq!(decoded.physical_to_original(0).unwrap(), 2);
    expect_limit(
        DocRemap::decode(&bytes, 3, &limits_with_budget(full - 1)),
        full,
    );
}

#[test]
fn a4_u24_u25_remap_validation() {
    // Singleton identity.
    assert!(DocRemap::decode(&[0], 1, &SegmentLimits::default()).is_ok());
    // Out-of-range forward id.
    let mut w = ByteWriter::new();
    w.u8(1);
    w.u64(9); // physical 0 -> original 9 (out of range)
    w.u64(0);
    assert!(DocRemap::decode(&w.into_vec(), 1, &SegmentLimits::default()).is_err());
    // Incorrect inverse.
    let mut w = ByteWriter::new();
    w.u8(1);
    w.u64(1);
    w.u64(0);
    w.u64(0);
    w.u64(0);
    assert!(DocRemap::decode(&w.into_vec(), 2, &SegmentLimits::default()).is_err());
}

#[test]
fn a4_u26_remap_truncation_and_trailing() {
    let bytes = remap_body(&[1, 0]);
    assert!(DocRemap::decode(&bytes[..bytes.len() - 1], 2, &SegmentLimits::default()).is_err());
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert!(DocRemap::decode(&trailing, 2, &SegmentLimits::default()).is_err());
    // Huge doc_count with a tiny body is rejected before allocation.
    assert!(DocRemap::decode(&[1], 1_000_000, &SegmentLimits::default()).is_err());
}

#[test]
fn a4_u27_error_then_valid_no_partial_state() {
    // A failed dictionary decode does not poison a subsequent valid decode.
    let bad = dictionary_body(&[(0, &[("b", 1), ("a", 1)])]);
    assert!(DictionaryReader::new(&bad, &SegmentLimits::default()).is_err());
    let good = dictionary_body(&[(0, &[("a", 1)])]);
    let reader = DictionaryReader::new(&good, &SegmentLimits::default()).unwrap();
    assert!(reader.lookup(0, "a").is_some());
}

#[test]
fn a4_i03_tight_budget_failure_then_valid_open() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard"),
        ],
        None,
    )
    .unwrap();
    let mut builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin())
        .unwrap()
        .with_layout(Layout::Insertion);
    let mut doc = SegmentDocument::new(DocumentKey::new("k0").unwrap());
    doc.fields.insert(
        "body".to_owned(),
        FieldValues::Single(FieldValue::Text("hello world".to_owned())),
    );
    builder.add_document(doc).unwrap();
    let bytes = builder.build().unwrap().bytes;

    let tight = SegmentLimits::default().with_max_section_decode_bytes(1);
    assert!(SegmentReader::open(bytes.clone(), tight).is_err());
    // No partial state: a subsequent valid open succeeds.
    let reader = SegmentReader::open(bytes, SegmentLimits::default()).unwrap();
    assert_eq!(reader.doc_count(), 1);
    assert_eq!(reader.stored().unwrap().len(), 1);
}
