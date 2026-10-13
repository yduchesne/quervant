//! Unit tests for the segment codecs (error paths, primitives, bounds, values).

use std::error::Error;

use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
use crate::contract::value::{FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue};
use crate::storage::StorageError;

use super::bounds::{
    GeoBounds, PRESENCE_ALL, PRESENCE_NONE, PRESENCE_SOME, PRESENCE_UNKNOWN, TimeBounds,
};
use super::error::SegmentError;
use super::format::{
    ByteReader, ByteWriter, ContainerBuilder, ContainerKind, SectionKind, parse_container, sha256,
};
use super::limits::SegmentLimits;
use super::value::{
    STATE_ABSENT, STATE_EMPTY_MULTI, STATE_EXPLICIT_NULL, STATE_MULTI, STATE_SINGLE,
    decode_field_values, decode_json, encode_field_values, encode_json, state_of,
};

fn encoding_error() -> SegmentError {
    SegmentError::Corrupt {
        context: "unit",
        detail: "boom".to_owned(),
    }
}

#[test]
fn error_display_and_source_cover_variants() {
    let storage = SegmentError::Storage(StorageError::NotFound {
        key: crate::storage::StorageKey::parse("k").unwrap(),
    });
    assert!(storage.source().is_some());
    let errors = vec![
        SegmentError::InvalidMagic { context: "h" },
        SegmentError::UnsupportedFormatVersion { major: 2, minor: 0 },
        SegmentError::UnsupportedFeature {
            feature_id: 9,
            version: 1,
        },
        SegmentError::UnknownFlags {
            context: "h",
            flags: 1,
        },
        SegmentError::Truncated {
            context: "h",
            needed: 1,
            available: 0,
        },
        SegmentError::InvalidExtent {
            context: "h",
            offset: 1,
            length: 1,
            limit: 1,
        },
        SegmentError::NonContiguousSections {
            expected: 1,
            found: 2,
        },
        SegmentError::DuplicateSection { kind: 1 },
        SegmentError::MissingSection { kind: 1 },
        encoding_error(),
        SegmentError::DigestMismatch { context: "h" },
        SegmentError::LengthMismatch {
            context: "h",
            expected: 1,
            actual: 2,
        },
        SegmentError::LimitExceeded {
            limit: 1,
            requested: 2,
        },
        SegmentError::InvalidVarint { context: "h" },
        SegmentError::InvalidFieldTypeTag { tag: 200 },
        SegmentError::DuplicateField {
            name: "f".to_owned(),
        },
        SegmentError::InvalidCardinality { value: 9 },
        SegmentError::InvalidFieldState { value: 9 },
        SegmentError::DuplicateTerm {
            field_id: 1,
            term: "t".to_owned(),
        },
        SegmentError::NonMonotoneDocId {
            previous: 1,
            next: 1,
        },
        SegmentError::ZeroFrequency { doc_id: 1 },
        SegmentError::NonMonotonePosition { doc_id: 1 },
        SegmentError::InvalidRemap { context: "c" },
        SegmentError::AnalyzerFingerprintMismatch {
            field: "f".to_owned(),
        },
        SegmentError::UnknownFieldId { field_id: 1 },
        SegmentError::FieldTypeMismatch {
            field: "f".to_owned(),
        },
        SegmentError::InvalidGeo { detail: "d" },
        SegmentError::InvalidIp { detail: "d" },
        SegmentError::InvalidUtf8 { context: "h" },
        SegmentError::NonFiniteFloat { context: "h" },
        SegmentError::InvalidColumnGeometry { detail: "d" },
        SegmentError::InvalidManifest {
            detail: "d".to_owned(),
        },
        SegmentError::Cancelled,
        storage,
    ];
    for error in errors {
        assert!(!error.to_string().is_empty());
    }
    assert!(matches!(
        SegmentError::from(StorageError::Cancelled),
        SegmentError::Cancelled
    ));
}

#[test]
fn limits_getters_and_errors() {
    let limits = SegmentLimits::default()
        .with_max_single_allocation(10)
        .with_max_decoded_entries(2)
        .with_block_docs_default(7)
        .with_accepted_segment_bytes(99);
    assert_eq!(limits.max_single_allocation(), 10);
    assert_eq!(limits.max_decoded_entries(), 2);
    assert_eq!(limits.block_docs_default(), 7);
    assert_eq!(limits.accepted_segment_bytes(), 99);
    assert_eq!(limits.max_section_decode_bytes(), 256 * 1024 * 1024);
    assert_eq!(limits.max_read_bytes(), 1024 * 1024);
    assert_eq!(limits.max_footer_bytes(), 1024 * 1024);
    assert_eq!(limits.max_sections(), 4_096);
    assert_eq!(limits.max_features(), 1_024);
    assert_eq!(limits.max_docs(), u64::from(u32::MAX));
    assert_eq!(limits.max_terms_total(), 1 << 32);
    assert_eq!(limits.max_postings_per_term(), 1 << 32);
    assert_eq!(limits.max_array_elements(), 1 << 20);
    assert_eq!(limits.max_json_depth(), 128);
    assert!(matches!(
        limits.check_entries(3),
        Err(SegmentError::LimitExceeded { .. })
    ));
    assert!(limits.check_entries(1).is_ok());
}

#[test]
fn writer_reader_primitives() {
    let mut writer = ByteWriter::with_capacity(8);
    assert!(writer.is_empty());
    writer.u8(1);
    writer.u16(2);
    writer.u32(3);
    writer.u64(4);
    writer.i64(-5);
    writer.f64(1.5);
    writer.bytes(b"ab");
    writer.varint(0);
    writer.varint(127);
    writer.varint(128);
    writer.varint(u64::MAX);
    assert!(!writer.is_empty());
    assert!(!writer.is_empty());

    let bytes = writer.into_vec();
    let mut reader = ByteReader::new(&bytes);
    assert_eq!(reader.u8("c").unwrap(), 1);
    assert_eq!(reader.u16("c").unwrap(), 2);
    assert_eq!(reader.u32("c").unwrap(), 3);
    assert_eq!(reader.u64("c").unwrap(), 4);
    assert_eq!(reader.i64("c").unwrap(), -5);
    assert_eq!(reader.f64("c").unwrap(), 1.5);
    assert_eq!(reader.bytes(2, "c").unwrap(), b"ab");
    assert_eq!(reader.varint("c").unwrap(), 0);
    assert_eq!(reader.varint("c").unwrap(), 127);
    assert_eq!(reader.varint("c").unwrap(), 128);
    assert_eq!(reader.varint("c").unwrap(), u64::MAX);
    assert!(reader.is_empty());
    reader.expect_end("c").unwrap();
    assert_eq!(reader.position(), bytes.len());
    assert_eq!(reader.remaining(), 0);
}

#[test]
fn reader_error_paths() {
    let mut reader = ByteReader::new(&[0x80, 0x00]);
    assert!(matches!(
        reader.varint("v"),
        Err(SegmentError::InvalidVarint { .. })
    ));
    let mut reader = ByteReader::new(&[
        0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80,
    ]);
    assert!(matches!(
        reader.varint("v"),
        Err(SegmentError::InvalidVarint { .. })
    ));
    let mut reader = ByteReader::new(&[0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x02]);
    assert!(matches!(
        reader.varint("v"),
        Err(SegmentError::InvalidVarint { .. })
    ));

    let mut reader = ByteReader::new(&[]);
    assert!(matches!(
        reader.u8("c"),
        Err(SegmentError::Truncated { .. })
    ));

    let mut writer = ByteWriter::new();
    writer.f64(f64::NAN);
    let mut reader = ByteReader::new(writer.as_slice());
    assert!(matches!(
        reader.f64("f"),
        Err(SegmentError::NonFiniteFloat { .. })
    ));

    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u8(0);
    let reader = ByteReader::new(writer.as_slice());
    assert!(reader.expect_end("c").is_err());
}

#[test]
fn byte_writer_length_prefix_and_sha() {
    let mut writer = ByteWriter::new();
    writer.len_prefixed_u16(b"abc").unwrap();
    assert_eq!(writer.as_slice(), &[3, 0, b'a', b'b', b'c']);
    let mut reader = ByteReader::new(writer.as_slice());
    assert_eq!(reader.len_prefixed_u16("c").unwrap(), b"abc");

    let digest = sha256(b"abc");
    assert_eq!(digest.len(), 32);
    assert_ne!(digest, sha256(b"abd"));
}

#[test]
fn container_builder_and_parse_errors() {
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, 1);
    builder.section(SectionKind::Schema, 0, 0, vec![1, 2, 3]);
    builder.optional_feature(7, 1);
    let bytes = builder.build().unwrap();
    let view = parse_container(&bytes, &SegmentLimits::default()).unwrap();
    assert_eq!(view.doc_count(), 1);
    assert_eq!(view.kind(), ContainerKind::Segment);
    assert!(view.body(SectionKind::Schema).is_some());
    assert!(view.entry(SectionKind::Schema).is_some());
    assert!(view.body(SectionKind::Postings).is_none());
    view.ensure_supported_features().unwrap();

    let mut duplicate = ContainerBuilder::new(ContainerKind::Segment, 0);
    duplicate.section(SectionKind::Schema, 0, 0, vec![]);
    duplicate.section(SectionKind::Schema, 0, 0, vec![]);
    assert!(matches!(
        duplicate.build(),
        Err(SegmentError::DuplicateSection { .. })
    ));

    let mut bad_magic = bytes.clone();
    bad_magic[0] = 0;
    assert!(matches!(
        parse_container(&bad_magic, &SegmentLimits::default()),
        Err(SegmentError::InvalidMagic { .. })
    ));

    let mut bad_version = bytes.clone();
    bad_version[8] = 9;
    assert!(matches!(
        parse_container(&bad_version, &SegmentLimits::default()),
        Err(SegmentError::UnsupportedFormatVersion { .. })
    ));

    let mut bad_endian = bytes.clone();
    bad_endian[12] = 9;
    assert!(parse_container(&bad_endian, &SegmentLimits::default()).is_err());

    let mut bad_header_flags = bytes.clone();
    bad_header_flags[14] = 1;
    assert!(matches!(
        parse_container(&bad_header_flags, &SegmentLimits::default()),
        Err(SegmentError::UnknownFlags { .. })
    ));

    // Truncated container.
    assert!(matches!(
        parse_container(&bytes[..10], &SegmentLimits::default()),
        Err(SegmentError::Truncated { .. })
    ));

    // Tampered trailer section count is inconsistent with the footer.
    let mut bad_trailer = bytes.clone();
    let len = bad_trailer.len();
    bad_trailer[len - 40] ^= 0xff;
    assert!(parse_container(&bad_trailer, &SegmentLimits::default()).is_err());
}

#[test]
fn value_states_and_json() {
    assert_eq!(state_of(&FieldValues::Absent), STATE_ABSENT);
    assert_eq!(state_of(&FieldValues::ExplicitNull), STATE_EXPLICIT_NULL);
    assert_eq!(state_of(&FieldValues::Empty), STATE_EMPTY_MULTI);
    assert_eq!(
        state_of(&FieldValues::Single(FieldValue::Bool(true))),
        STATE_SINGLE
    );
    assert_eq!(
        state_of(&FieldValues::Multi(vec![FieldValue::Bool(true)])),
        STATE_MULTI
    );

    let limits = SegmentLimits::default();
    let cases = vec![
        (FieldType::Bool, FieldValue::Bool(false)),
        (FieldType::I64, FieldValue::I64(i64::MIN)),
        (FieldType::U64, FieldValue::U64(u64::MAX)),
        (FieldType::F64, FieldValue::F64(-0.0)),
        (
            FieldType::Timestamp,
            FieldValue::Timestamp(crate::contract::value::Timestamp::from_micros(-1)),
        ),
        (FieldType::Text, FieldValue::Text("hi".to_owned())),
        (FieldType::Keyword, FieldValue::Keyword("hi".to_owned())),
        (
            FieldType::GeoPoint,
            FieldValue::GeoPoint(GeoPoint::new(-122.4, 37.8).unwrap()),
        ),
        (
            FieldType::IpAddress,
            FieldValue::Ip("::ffff:192.0.2.1".parse().unwrap()),
        ),
        (
            FieldType::IpNetwork,
            FieldValue::Cidr(IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap()),
        ),
        (
            FieldType::Json,
            FieldValue::Json(JsonValue::Object(vec![
                ("n".to_owned(), JsonValue::Number(JsonNumber::I64(-1))),
                ("u".to_owned(), JsonValue::Number(JsonNumber::U64(1))),
                ("f".to_owned(), JsonValue::Number(JsonNumber::F64(1.25))),
                ("s".to_owned(), JsonValue::String("x".to_owned())),
                ("b".to_owned(), JsonValue::Bool(true)),
                ("z".to_owned(), JsonValue::Null),
                (
                    "a".to_owned(),
                    JsonValue::Array(vec![JsonValue::Number(JsonNumber::U64(2))]),
                ),
            ])),
        ),
    ];
    for (field_type, value) in cases {
        let mut writer = ByteWriter::new();
        encode_scalar_for_test(&mut writer, field_type, &value);
        let mut reader = ByteReader::new(writer.as_slice());
        let decoded = super::value::decode_scalar(&mut reader, field_type, &limits).unwrap();
        assert_eq!(decoded, value);
        reader.expect_end("value").unwrap();
    }

    // Field-state round trips including absent/null/empty/multi.
    for state in [
        FieldValues::Absent,
        FieldValues::ExplicitNull,
        FieldValues::Empty,
        FieldValues::Single(FieldValue::I64(7)),
        FieldValues::Multi(vec![FieldValue::I64(1), FieldValue::I64(2)]),
    ] {
        let mut writer = ByteWriter::new();
        encode_field_values(&mut writer, FieldType::I64, &state, &limits).unwrap();
        let mut reader = ByteReader::new(writer.as_slice());
        assert_eq!(
            decode_field_values(&mut reader, FieldType::I64, &limits).unwrap(),
            state
        );
    }

    // Invalid state tag.
    let mut reader = ByteReader::new(&[9]);
    assert!(matches!(
        decode_field_values(&mut reader, FieldType::I64, &limits),
        Err(SegmentError::InvalidFieldState { .. })
    ));

    // MULTI with zero count is rejected.
    let mut reader = ByteReader::new(&[STATE_MULTI, 0]);
    assert!(decode_field_values(&mut reader, FieldType::I64, &limits).is_err());

    // Type mismatch.
    let mut writer = ByteWriter::new();
    assert!(matches!(
        super::value::encode_scalar(&mut writer, FieldType::I64, &FieldValue::Bool(true)),
        Err(SegmentError::FieldTypeMismatch { .. })
    ));

    // Non-finite f64 rejected.
    let mut writer = ByteWriter::new();
    assert!(matches!(
        super::value::encode_scalar(&mut writer, FieldType::F64, &FieldValue::F64(f64::NAN)),
        Err(SegmentError::NonFiniteFloat { .. })
    ));
}

fn encode_scalar_for_test(writer: &mut ByteWriter, field_type: FieldType, value: &FieldValue) {
    super::value::encode_scalar(writer, field_type, value).unwrap();
}

#[test]
fn json_error_paths() {
    let limits = SegmentLimits::default();
    // Unknown tag.
    let mut reader = ByteReader::new(&[99]);
    assert!(decode_json(&mut reader, &limits, 0).is_err());
    // Invalid bool.
    let mut reader = ByteReader::new(&[1, 9]);
    assert!(decode_json(&mut reader, &limits, 0).is_err());
    // Depth limit.
    let mut writer = ByteWriter::new();
    let deep = JsonValue::Array(vec![JsonValue::Array(vec![JsonValue::Array(vec![
        JsonValue::Null,
    ])])]);
    encode_json(&mut writer, &deep).unwrap();
    let mut reader = ByteReader::new(writer.as_slice());
    let shallow = limits;
    assert!(decode_json(&mut reader, &shallow, 0).is_ok());

    // depth beyond limit
    let tiny = SegmentLimits::default();
    let mut reader = ByteReader::new(writer.as_slice());
    assert!(decode_json(&mut reader, &tiny, 129).is_err());

    // Non-finite JSON number.
    let mut writer = ByteWriter::new();
    assert!(matches!(
        encode_json(
            &mut writer,
            &JsonValue::Number(JsonNumber::F64(f64::INFINITY))
        ),
        Err(SegmentError::NonFiniteFloat { .. })
    ));
}

#[test]
fn bounds_round_trip_and_errors() {
    let time = TimeBounds {
        field_id: 1,
        known: true,
        presence: PRESENCE_ALL,
        live_count: 3,
        present_count: 3,
        min_micros: -10,
        max_micros: 10,
        ordered: true,
    };
    let decoded = TimeBounds::decode(&time.encode()).unwrap();
    assert_eq!(decoded, time);
    let unknown = TimeBounds::unknown(1, 3);
    assert_eq!(TimeBounds::decode(&unknown.encode()).unwrap(), unknown);

    assert_eq!(super::bounds::presence_of(0, 0), PRESENCE_NONE);
    assert_eq!(super::bounds::presence_of(2, 1), PRESENCE_SOME);
    assert_eq!(super::bounds::presence_of(2, 2), PRESENCE_ALL);

    // Invalid known tag.
    let mut bytes = time.encode();
    bytes[4] = 9;
    assert!(TimeBounds::decode(&bytes).is_err());
    // Present count exceeds live.
    let mut bytes = time.encode();
    bytes[6 + 8..6 + 16].copy_from_slice(&100u64.to_le_bytes());
    assert!(TimeBounds::decode(&bytes).is_err());
    // Presence mismatch.
    let mut bytes = time.encode();
    bytes[5] = PRESENCE_NONE;
    assert!(TimeBounds::decode(&bytes).is_err());
    // Unknown presence accepted.
    let mut bytes = time.encode();
    bytes[5] = PRESENCE_UNKNOWN;
    assert!(TimeBounds::decode(&bytes).is_ok());

    let geo = GeoBounds {
        field_id: 2,
        known: true,
        presence: PRESENCE_SOME,
        live_count: 4,
        present_count: 2,
        west: 170.0,
        south: -5.0,
        east: -170.0,
        north: 5.0,
        crosses_antimeridian: true,
    };
    assert_eq!(GeoBounds::decode(&geo.encode()).unwrap(), geo);
    assert_eq!(
        GeoBounds::decode(&GeoBounds::unknown(2, 0).encode()).unwrap(),
        GeoBounds::unknown(2, 0)
    );
    // Unknown and zero-present never prune.
    assert!(!GeoBounds::unknown(2, 4).prunes_positive_box(0.0, 0.0, 1.0, 1.0));
    assert_eq!(GeoBounds::unknown(2, 0).present_count, 0);
    let none = GeoBounds {
        present_count: 0,
        presence: PRESENCE_NONE,
        ..geo
    };
    assert!(none.prunes_positive_box(0.0, 0.0, 1.0, 1.0));
    // Latitude disjoint.
    assert!(geo.prunes_positive_box(0.0, 50.0, 10.0, 60.0));
}

#[test]
fn schema_tag_mapping_and_errors() {
    for field_type in [
        FieldType::Text,
        FieldType::Keyword,
        FieldType::Bool,
        FieldType::I64,
        FieldType::U64,
        FieldType::F64,
        FieldType::Timestamp,
        FieldType::Json,
        FieldType::GeoPoint,
        FieldType::IpAddress,
        FieldType::IpNetwork,
    ] {
        let tag = super::schema::field_type_tag(field_type);
        assert_eq!(super::schema::field_type_from_tag(tag).unwrap(), field_type);
    }
    assert!(matches!(
        super::schema::field_type_from_tag(200),
        Err(SegmentError::InvalidFieldTypeTag { .. })
    ));
}

#[test]
fn schema_build_and_round_trip() {
    use crate::analysis::AnalyzerRegistry;
    use crate::analysis::SchemaAnalyzerBindings;
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard"),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .unwrap();
    let registry = AnalyzerRegistry::builtin();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).unwrap();
    let codec = super::schema::CodecSchema::from_contract(&schema, &bindings).unwrap();
    assert_eq!(codec.field_count(), 3);
    assert!(codec.field_id("body").is_some());
    assert!(codec.field(0).is_some());
    assert!(codec.field(99).is_none());
    assert!(
        !codec
            .field(codec.field_id("body").unwrap())
            .unwrap()
            .is_columnar()
    );
    assert!(
        codec
            .field(codec.field_id("tag").unwrap())
            .unwrap()
            .is_columnar()
    );
    assert!(
        !codec
            .field(codec.field_id("n").unwrap())
            .unwrap()
            .is_indexed()
    );
    let bytes = codec.encode().unwrap();
    let decoded = super::schema::CodecSchema::decode(&bytes, &SegmentLimits::default()).unwrap();
    assert_eq!(decoded, codec);

    // Bad version.
    let mut bad = bytes.clone();
    bad[0] = 9;
    assert!(super::schema::CodecSchema::decode(&bad, &SegmentLimits::default()).is_err());
    // Truncated.
    assert!(super::schema::CodecSchema::decode(&bytes[..2], &SegmentLimits::default()).is_err());
}

#[test]
fn model_builders() {
    let mut doc = super::model::SegmentDocument::new(DocumentKey::new("k").unwrap())
        .with_revision(5)
        .with_live(false);
    assert_eq!(doc.revision, 5);
    assert!(!doc.live);
    doc.insert("a", FieldValues::Single(FieldValue::I64(1)))
        .unwrap();
    assert_eq!(doc.fields.len(), 1);
    doc.insert("a", FieldValues::Absent).unwrap();
    assert!(doc.fields.is_empty());
}

#[test]
fn remap_error_paths() {
    use super::remap::DocRemap;
    let identity = DocRemap::identity(3);
    assert!(identity.is_identity());
    assert_eq!(identity.doc_count(), 3);
    assert_eq!(identity.physical_to_original(2).unwrap(), 2);
    assert_eq!(identity.original_to_physical(2).unwrap(), 2);
    assert!(identity.physical_to_original(9).is_err());
    assert!(identity.original_to_physical(9).is_err());
    assert_eq!(
        DocRemap::decode(&identity.encode(), 3, &SegmentLimits::default()).unwrap(),
        identity
    );

    let permuted = DocRemap::from_order(vec![2, 0, 1]).unwrap();
    let decoded = DocRemap::decode(&permuted.encode(), 3, &SegmentLimits::default()).unwrap();
    assert_eq!(decoded, permuted);

    // Corrupt state tag.
    assert!(DocRemap::decode(&[9], 3, &SegmentLimits::default()).is_err());
    // Extra trailing bytes.
    let mut bytes = identity.encode();
    bytes.push(0);
    assert!(DocRemap::decode(&bytes, 3, &SegmentLimits::default()).is_err());
    // Inverse disagreement.
    let mut bytes = Vec::new();
    bytes.push(1);
    for value in [2u64, 0, 1] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    for value in [0u64, 1, 2] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    assert!(DocRemap::decode(&bytes, 3, &SegmentLimits::default()).is_err());
}

#[test]
fn dictionary_round_trip_and_errors() {
    use super::dictionary::{DictionaryEntry, DictionaryReader, encode_dictionary};
    let limits = SegmentLimits::default();
    let entry = |term: &str, freq: u64| DictionaryEntry {
        term: term.to_owned(),
        doc_freq: freq,
        postings_offset: 0,
        postings_length: 1,
    };
    let fields = vec![(0u32, vec![entry("a", 1), entry("b", 2)])];
    let bytes = encode_dictionary(&fields, &limits).unwrap();
    let reader = DictionaryReader::new(&bytes, &limits).unwrap();
    assert_eq!(reader.fields().len(), 1);
    assert_eq!(reader.field(0).unwrap().len(), 2);
    assert!(reader.lookup(0, "a").is_some());
    assert!(reader.lookup(0, "z").is_none());
    assert!(reader.lookup(7, "a").is_none());
    assert_eq!(DictionaryReader::default().fields().len(), 0);

    assert!(matches!(
        encode_dictionary(&[(0u32, vec![entry("a", 1), entry("a", 1)])], &limits),
        Err(SegmentError::DuplicateTerm { .. })
    ));
    assert!(matches!(
        encode_dictionary(&[(0u32, vec![entry("a", 0)])], &limits),
        Err(SegmentError::Corrupt { .. })
    ));
    assert!(matches!(
        encode_dictionary(&[(0u32, vec![entry("", 1)])], &limits),
        Err(SegmentError::Corrupt { .. })
    ));

    // Decode: bad version.
    let mut bad = bytes.clone();
    bad[0] = 9;
    assert!(DictionaryReader::new(&bad, &limits).is_err());
    // Decode: non-ascending field ids.
    // Craft two fields out of order.
    let two = encode_dictionary(
        &[(1u32, vec![entry("a", 1)]), (0u32, vec![entry("b", 1)])],
        &limits,
    )
    .unwrap();
    assert!(DictionaryReader::new(&two, &limits).is_err());
    // Decode: term order violation within a field.
    let unordered = encode_dictionary(&[(0u32, vec![entry("b", 1), entry("a", 1)])], &limits);
    assert!(unordered.is_err());
}

#[test]
fn postings_round_trip_and_errors() {
    use super::postings::{
        OCCURRENCE_DOC_ONLY, Occurrence, Posting, PostingsReader, encode_postings_block,
    };
    let limits = SegmentLimits::default();
    let occurrence = |position: u64| Occurrence {
        position,
        position_length: 1,
        value_index: 0,
        start_offset: 0,
        end_offset: 3,
    };
    let postings = vec![
        Posting {
            doc_id: 1,
            freq: 2,
            occurrences: vec![occurrence(5), occurrence(9)],
        },
        Posting {
            doc_id: 4,
            freq: 1,
            occurrences: vec![occurrence(2)],
        },
    ];
    let bytes = encode_postings_block(5, &postings, &limits).unwrap();
    let mut reader = PostingsReader::new(&bytes, 5, &limits).unwrap();
    assert_eq!(reader.posting_doc_count(), 2);
    assert_eq!(reader.freq_total(), 3);
    let first = reader.next().unwrap().unwrap();
    assert_eq!(first.doc_id, 1);
    assert_eq!(first.occurrences.len(), 2);
    assert_eq!(reader.next().unwrap().unwrap().doc_id, 4);
    assert!(reader.next().unwrap().is_none());
    // Cancellation is observed.
    let mut reader = PostingsReader::new(&bytes, 5, &limits).unwrap();
    let flag = crate::analysis::CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        reader.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));
    // Doc-only blocks decode.
    let doc_only = encode_postings_block(
        5,
        &[Posting {
            doc_id: 0,
            freq: 1,
            occurrences: vec![],
        }],
        &limits,
    )
    .unwrap();
    let mut reader = PostingsReader::new(&doc_only, 5, &limits).unwrap();
    assert!(matches!(
        reader.next().unwrap().unwrap().occurrences.len(),
        0
    ));
    let _ = OCCURRENCE_DOC_ONLY;

    // Encode errors.
    assert!(encode_postings_block(5, &[], &limits).is_err());
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 9,
                freq: 1,
                occurrences: vec![occurrence(0)]
            }],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 0,
                freq: 0,
                occurrences: vec![]
            }],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[
                Posting {
                    doc_id: 2,
                    freq: 1,
                    occurrences: vec![occurrence(0)]
                },
                Posting {
                    doc_id: 2,
                    freq: 1,
                    occurrences: vec![occurrence(0)]
                }
            ],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 0,
                freq: 2,
                occurrences: vec![occurrence(0)]
            }],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 0,
                freq: 1,
                occurrences: vec![Occurrence {
                    position: 0,
                    position_length: 0,
                    value_index: 0,
                    start_offset: 0,
                    end_offset: 0
                }]
            }],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 0,
                freq: 1,
                occurrences: vec![Occurrence {
                    position: 0,
                    position_length: 1,
                    value_index: 0,
                    start_offset: 2,
                    end_offset: 1
                }]
            }],
            &limits
        )
        .is_err()
    );
    assert!(
        encode_postings_block(
            5,
            &[Posting {
                doc_id: 0,
                freq: 2,
                occurrences: vec![occurrence(5), occurrence(5)]
            }],
            &limits
        )
        .is_err()
    );

    // Decode errors: bad occurrence kind.
    assert!(PostingsReader::new(&[9u8], 5, &limits).is_err());
    // Decode: trailing bytes after the declared postings.
    let mut trailing = bytes.clone();
    trailing.push(0);
    let mut reader = PostingsReader::new(&trailing, 5, &limits).unwrap();
    assert!(reader.next().unwrap().is_some());
    assert!(reader.next().unwrap().is_some());
    assert!(reader.next().is_err());
}

fn small_codec_schema() -> super::schema::CodecSchema {
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "a",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, true, true),
        )],
        None,
    )
    .unwrap();
    let registry = AnalyzerRegistry::builtin();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).unwrap();
    super::schema::CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn manifest_container(payload: Vec<u8>) -> Vec<u8> {
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    builder.section(SectionKind::Manifest, 0, 0, payload);
    builder.build().unwrap()
}

#[test]
fn manifest_error_paths() {
    use super::manifest::Manifest;
    let limits = SegmentLimits::default();

    // Not a manifest container.
    let mut segment = ContainerBuilder::new(ContainerKind::Segment, 0);
    segment.section(SectionKind::Schema, 0, 0, vec![]);
    assert!(matches!(
        Manifest::decode(&segment.build().unwrap(), &limits),
        Err(SegmentError::InvalidManifest { .. })
    ));

    // Missing manifest section.
    let mut no_section = ContainerBuilder::new(ContainerKind::Manifest, 0);
    no_section.section(SectionKind::Schema, 0, 0, vec![]);
    assert!(matches!(
        Manifest::decode(&no_section.build().unwrap(), &limits),
        Err(SegmentError::MissingSection { .. })
    ));

    // Bad manifest version.
    let mut payload = ByteWriter::new();
    payload.u16(9);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());

    // Missing schema bytes.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(4);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());

    // Truncated after schema.
    let schema_bytes = small_codec_schema().encode().unwrap();
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());

    // A valid prefix then a malformed segment reference.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(1); // one segment
    payload.len_prefixed_u16(b"../bad").unwrap(); // invalid segment id
    payload.len_prefixed_u16(b"objects/one").unwrap();
    payload.u8(0);
    payload.u64(1);
    payload.bytes(&[0u8; 32]);
    payload.u8(0);
    payload.u32(0);
    payload.u32(0);
    payload.u32(0);
    payload.u32(0);
    assert!(matches!(
        Manifest::decode(&manifest_container(payload.into_vec()), &limits),
        Err(SegmentError::InvalidManifest { .. })
    ));

    // Feature count beyond the limit.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(0); // no segments
    payload.u32(0);
    payload.u32(u32::MAX);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());
}

#[test]
fn column_encode_and_value_errors() {
    use super::column::{ColumnReader, encode_columns};
    use super::model::SegmentDocument;
    let schema = small_codec_schema();
    let limits = SegmentLimits::default();
    assert!(matches!(
        encode_columns(&schema, &[], 0, &limits),
        Err(SegmentError::InvalidColumnGeometry { .. })
    ));
    let doc = SegmentDocument::new(DocumentKey::new("k").unwrap());
    let body = encode_columns(&schema, std::slice::from_ref(&doc), 1, &limits).unwrap();
    let reader = ColumnReader::open(&schema, &body, &limits).unwrap();
    assert_eq!(reader.fields(), vec![0]);
    // No column for an unknown field.
    assert!(reader.value(9, 0).unwrap().is_none());
    // Doc out of range.
    assert!(reader.value(0, 5).is_err());
    // The known field decodes as absent.
    assert_eq!(reader.value(0, 0).unwrap(), Some(FieldValues::Absent));
}

#[test]
fn build_error_paths() {
    use super::build::{Layout, SegmentBuilder};
    use super::model::SegmentDocument;
    use crate::analysis::AnalyzerRegistry;

    // Timestamp-sorted requires a primary timestamp.
    let schema = Schema::new(
        vec![FieldDefinition::new(
            "a",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        )],
        None,
    )
    .unwrap();
    let builder = SegmentBuilder::new(schema, AnalyzerRegistry::builtin())
        .unwrap()
        .with_layout(Layout::TimestampSorted);
    assert!(builder.build().is_err());

    // Unknown field in a document is rejected.
    let mut builder = SegmentBuilder::new(small_contract_schema(), AnalyzerRegistry::builtin())
        .unwrap()
        .with_limits(SegmentLimits::default().with_block_docs_default(2));
    let mut doc = SegmentDocument::new(DocumentKey::new("k").unwrap());
    doc.insert("nope", FieldValues::Single(FieldValue::Bool(true)))
        .unwrap();
    assert!(builder.add_document(doc).is_err());
    assert!(builder.is_empty());

    // Oversized exact keyword term is rejected at build.
    let mut builder =
        SegmentBuilder::new(small_contract_schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut doc = SegmentDocument::new(DocumentKey::new("big").unwrap());
    doc.fields.insert(
        "a".to_owned(),
        FieldValues::Single(FieldValue::Keyword("x".repeat(5000))),
    );
    builder.add_document(doc).unwrap();
    assert!(builder.build().is_err());
}

fn small_contract_schema() -> Schema {
    Schema::new(
        vec![FieldDefinition::new(
            "a",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        )],
        None,
    )
    .unwrap()
}

#[test]
fn reader_accessor_errors() {
    use super::build::{Layout, SegmentBuilder};
    use super::model::SegmentDocument;
    let mut builder = SegmentBuilder::new(
        small_contract_schema(),
        crate::analysis::AnalyzerRegistry::builtin(),
    )
    .unwrap()
    .with_layout(Layout::Insertion);
    let mut doc = SegmentDocument::new(DocumentKey::new("k").unwrap());
    doc.fields.insert(
        "a".to_owned(),
        FieldValues::Single(FieldValue::Keyword("term".to_owned())),
    );
    builder.add_document(doc).unwrap();
    let built = builder.build().unwrap();
    let reader =
        super::reader::SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).unwrap();
    assert!(reader.dictionary().is_some());
    assert!(reader.time_bounds().is_none());
    assert!(reader.geo_bounds().is_empty());
    assert!(reader.required_features().iter().any(|(id, _)| *id == 1));
    assert!(reader.optional_features().is_empty());
    assert!(
        reader
            .sections()
            .iter()
            .any(|entry| entry.kind == SectionKind::Stored)
    );
    // Unknown term.
    assert!(reader.postings(0, "missing").unwrap().is_none());
    // Unknown field.
    assert!(reader.postings(9, "term").unwrap().is_none());
    // Stored doc out of range.
    assert!(reader.stored_doc(9).is_err());
    // No columns in this segment.
    assert!(reader.column_value(0, 0).unwrap().is_none());

    // Content descriptor length mismatch.
    let descriptor = quervant_objectstore::ContentDescriptor::new(
        0,
        quervant_objectstore::ContentDigest::sha256_v1(&built.bytes),
    );
    assert!(matches!(
        reader.verify_content_descriptor(&descriptor),
        Err(SegmentError::LengthMismatch { .. })
    ));
}

#[test]
fn stored_decode_error_paths() {
    use super::model::SegmentDocument;
    use super::stored::{decode_stored, encode_stored};
    let schema = small_codec_schema();
    let limits = SegmentLimits::default();
    let mut doc = SegmentDocument::new(DocumentKey::new("k").unwrap());
    doc.fields.insert(
        "a".to_owned(),
        FieldValues::Single(FieldValue::Keyword("v".to_owned())),
    );
    let bytes = encode_stored(&schema, &[doc], &limits).unwrap();
    assert_eq!(decode_stored(&schema, &bytes, &limits).unwrap().len(), 1);
    // Bad version.
    let mut bad = bytes.clone();
    bad[0] = 9;
    assert!(decode_stored(&schema, &bad, &limits).is_err());
    // Truncated key.
    assert!(decode_stored(&schema, &bytes[..3], &limits).is_err());
}

#[test]
fn format_footer_and_feature_errors() {
    // Too many required features.
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
    for id in 0..2000u16 {
        builder.require_feature(id, 1);
    }
    builder.section(SectionKind::Schema, 0, 0, vec![]);
    let bytes = builder.build().unwrap();
    let limits = SegmentLimits::default();
    assert!(matches!(
        parse_container(&bytes, &limits),
        Err(SegmentError::LimitExceeded { .. })
    ));

    // Footer offset beyond the trailer.
    let mut good = ContainerBuilder::new(ContainerKind::Segment, 0);
    good.section(SectionKind::Schema, 0, 0, vec![]);
    let bytes = good.build().unwrap();
    let len = bytes.len();
    let mut bad = bytes.clone();
    // footer_offset is at trailer start + 8.
    bad[len - 56..len - 48].copy_from_slice(&0u64.to_le_bytes());
    assert!(parse_container(&bad, &limits).is_err());
}

#[test]
fn value_additional_errors() {
    let limits = SegmentLimits::default();
    // Keyword too long for its u16 length prefix.
    let mut writer = ByteWriter::new();
    assert!(
        super::value::encode_scalar(
            &mut writer,
            FieldType::Keyword,
            &FieldValue::Keyword("x".repeat(70_000))
        )
        .is_err()
    );
    // Invalid IP family tag.
    let mut reader = ByteReader::new(&[9, 0, 0, 0, 0]);
    assert!(super::value::decode_ip(&mut reader).is_err());
    // Invalid CIDR (host bits set).
    let mut writer = ByteWriter::new();
    super::value::encode_ip(&mut writer, "10.0.0.1".parse().unwrap());
    writer.u8(8);
    let mut reader = ByteReader::new(writer.as_slice());
    assert!(super::value::decode_scalar(&mut reader, FieldType::IpNetwork, &limits).is_err());
    // Invalid UTF-8 keyword.
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u8(0xff);
    let mut reader = ByteReader::new(writer.as_slice());
    assert!(super::value::decode_scalar(&mut reader, FieldType::Keyword, &limits).is_err());
    // Invalid bool tag.
    let mut reader = ByteReader::new(&[9]);
    assert!(super::value::decode_scalar(&mut reader, FieldType::Bool, &limits).is_err());
    // Geo out of range.
    let mut writer = ByteWriter::new();
    writer.f64(200.0);
    writer.f64(0.0);
    let mut reader = ByteReader::new(writer.as_slice());
    assert!(super::value::decode_scalar(&mut reader, FieldType::GeoPoint, &limits).is_err());
}

#[test]
fn manifest_round_trip_full() {
    use super::manifest::{Manifest, ManifestSegmentRef};
    let schema = small_codec_schema();
    let limits = SegmentLimits::default();
    let bounds = TimeBounds {
        field_id: 0,
        known: true,
        presence: PRESENCE_ALL,
        live_count: 1,
        present_count: 1,
        min_micros: 0,
        max_micros: 1,
        ordered: true,
    };
    let manifest = Manifest {
        schema,
        segments: vec![
            ManifestSegmentRef {
                segment_id: "segments/a".to_owned(),
                object_key: "objects/a".to_owned(),
                content_algorithm: 0,
                content_length: 10,
                content_digest: [7u8; 32],
                time_bounds: Some(bounds),
                required_features: vec![(1, 1)],
                optional_features: vec![(2, 1)],
            },
            ManifestSegmentRef {
                segment_id: "segments/b".to_owned(),
                object_key: "objects/b".to_owned(),
                content_algorithm: 0,
                content_length: 20,
                content_digest: [8u8; 32],
                time_bounds: None,
                required_features: vec![],
                optional_features: vec![],
            },
        ],
        required_features: vec![(1, 1)],
        optional_features: vec![],
    };
    let bytes = manifest.encode().unwrap();
    let decoded = Manifest::decode(&bytes, &limits).unwrap();
    assert_eq!(decoded, manifest);
}

fn schema_body(field: &[u8], primary: u8) -> Vec<u8> {
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(1);
    payload.bytes(field);
    payload.u8(primary);
    payload.into_vec()
}

#[test]
fn schema_decode_error_paths() {
    let limits = SegmentLimits::default();
    let field = |type_tag: u8, cardinality: u8, flags: u8, reserved: u16, binding: u8| {
        let mut w = ByteWriter::new();
        w.u32(0);
        w.len_prefixed_u16(b"a").unwrap();
        w.u8(type_tag);
        w.u8(cardinality);
        w.u8(flags);
        w.u8(binding);
        w.u8(0); // normalizer presence
        w.u16(reserved);
        w.into_vec()
    };
    // Invalid field type tag.
    assert!(matches!(
        super::schema::CodecSchema::decode(&schema_body(&field(200, 0, 0b001, 0, 0), 0), &limits),
        Err(SegmentError::InvalidFieldTypeTag { .. })
    ));
    // Invalid cardinality.
    assert!(matches!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 9, 0b001, 0, 0), 0), &limits),
        Err(SegmentError::InvalidCardinality { .. })
    ));
    // Unknown option flag bits.
    assert!(matches!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0b1000, 0, 0), 0), &limits),
        Err(SegmentError::UnknownFlags { .. })
    ));
    // Useless options (all false) fail schema validation.
    assert!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0, 0, 0), 0), &limits)
            .is_err()
    );
    // Reserved bits set.
    assert!(matches!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0b001, 1, 0), 0), &limits),
        Err(SegmentError::UnknownFlags { .. })
    ));
    // Invalid binding presence tag.
    assert!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0b001, 0, 9), 0), &limits)
            .is_err()
    );
    // Invalid primary timestamp presence tag.
    assert!(matches!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0b001, 0, 0), 9), &limits),
        Err(SegmentError::Corrupt { .. })
    ));
    // Primary timestamp referencing a non-timestamp field fails validation.
    assert!(
        super::schema::CodecSchema::decode(&schema_body(&field(2, 0, 0b001, 0, 0), 1), &limits)
            .is_err()
    );
    // Analyzer on a non-text field fails.
    let mut binding = ByteWriter::new();
    binding.u8(1);
    binding.len_prefixed_u16(b"standard").unwrap();
    binding.len_prefixed_u16(b"1.0.0").unwrap();
    binding.bytes(&[0u8; 32]);
    let binding = binding.into_vec();
    let mut with_binding = ByteWriter::new();
    with_binding.u32(0);
    with_binding.len_prefixed_u16(b"a").unwrap();
    with_binding.u8(2); // Keyword
    with_binding.u8(0);
    with_binding.u8(0b001);
    with_binding.bytes(&binding);
    with_binding.u8(0); // no normalizer
    with_binding.u16(0);
    assert!(
        super::schema::CodecSchema::decode(&schema_body(with_binding.as_slice(), 0), &limits)
            .is_err()
    );
}

#[test]
fn column_multi_value_round_trip() {
    use super::column::{ColumnReader, encode_columns};
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
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
    let codec = super::schema::CodecSchema::from_contract(&schema, &bindings).unwrap();
    let mut a = super::model::SegmentDocument::new(DocumentKey::new("a").unwrap());
    a.fields.insert(
        "tags".to_owned(),
        FieldValues::Multi(vec![
            FieldValue::Keyword("x".to_owned()),
            FieldValue::Keyword("y".to_owned()),
        ]),
    );
    let mut b = super::model::SegmentDocument::new(DocumentKey::new("b").unwrap());
    b.fields.insert("tags".to_owned(), FieldValues::Empty);
    let mut c = super::model::SegmentDocument::new(DocumentKey::new("c").unwrap());
    c.fields
        .insert("tags".to_owned(), FieldValues::ExplicitNull);
    let limits = SegmentLimits::default();
    let body = encode_columns(&codec, &[a, b, c], 2, &limits).unwrap();
    let reader = ColumnReader::open(&codec, &body, &limits).unwrap();
    assert_eq!(
        reader.value(0, 0).unwrap(),
        Some(FieldValues::Multi(vec![
            FieldValue::Keyword("x".to_owned()),
            FieldValue::Keyword("y".to_owned())
        ]))
    );
    assert_eq!(reader.value(0, 1).unwrap(), Some(FieldValues::Empty));
    assert_eq!(reader.value(0, 2).unwrap(), Some(FieldValues::ExplicitNull));
}

#[test]
fn manifest_payload_validation_errors() {
    use super::manifest::Manifest;
    let limits = SegmentLimits::default();
    let schema_bytes = small_codec_schema().encode().unwrap();
    let base = |mut prefix: ByteWriter| -> Vec<u8> {
        prefix.u16(1);
        prefix.u32(schema_bytes.len() as u32);
        prefix.bytes(&schema_bytes);
        prefix.u32(1); // one segment
        prefix.into_vec()
    };
    let segment_tail = |w: &mut ByteWriter| {
        w.u8(0); // algorithm
        w.u64(1); // length
        w.bytes(&[0u8; 32]);
        w.u8(0); // no time bounds
        w.u32(0);
        w.u32(0);
    };

    // Invalid object key grammar.
    let mut w = ByteWriter::new();
    w.len_prefixed_u16(b"segments/a").unwrap();
    w.len_prefixed_u16(b"../bad").unwrap();
    segment_tail(&mut w);
    assert!(Manifest::decode(&manifest_container(base(w)), &limits).is_err());

    // Unsupported algorithm.
    let mut w = ByteWriter::new();
    w.len_prefixed_u16(b"segments/a").unwrap();
    w.len_prefixed_u16(b"objects/a").unwrap();
    w.u8(9);
    w.u64(1);
    w.bytes(&[0u8; 32]);
    w.u8(0);
    w.u32(0);
    w.u32(0);
    assert!(Manifest::decode(&manifest_container(base(w)), &limits).is_err());

    // Zero content length.
    let mut w = ByteWriter::new();
    w.len_prefixed_u16(b"segments/a").unwrap();
    w.len_prefixed_u16(b"objects/a").unwrap();
    w.u8(0);
    w.u64(0);
    w.bytes(&[0u8; 32]);
    w.u8(0);
    w.u32(0);
    w.u32(0);
    assert!(Manifest::decode(&manifest_container(base(w)), &limits).is_err());

    // Invalid time-bounds presence tag.
    let mut w = ByteWriter::new();
    w.len_prefixed_u16(b"segments/a").unwrap();
    w.len_prefixed_u16(b"objects/a").unwrap();
    w.u8(0);
    w.u64(1);
    w.bytes(&[0u8; 32]);
    w.u8(9);
    assert!(Manifest::decode(&manifest_container(base(w)), &limits).is_err());

    // Per-segment feature count beyond the limit.
    let mut w = ByteWriter::new();
    w.len_prefixed_u16(b"segments/a").unwrap();
    w.len_prefixed_u16(b"objects/a").unwrap();
    segment_tail(&mut w);
    // Replace the final two feature counts with one oversized count.
    let mut payload = base(ByteWriter::new());
    payload.extend_from_slice(w.as_slice());
    // The last 8 bytes are the two u32 feature counts; overwrite the first.
    let len = payload.len();
    payload[len - 8..len - 4].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(Manifest::decode(&manifest_container(payload), &limits).is_err());

    // Duplicate object key within a payload (two segments, same key).
    let mut w = ByteWriter::new();
    w.u16(1);
    w.u32(schema_bytes.len() as u32);
    w.bytes(&schema_bytes);
    w.u32(2);
    for id in ["segments/a", "segments/b"] {
        w.len_prefixed_u16(id.as_bytes()).unwrap();
        w.len_prefixed_u16(b"objects/same").unwrap();
        segment_tail(&mut w);
    }
    w.u32(0);
    w.u32(0);
    assert!(Manifest::decode(&manifest_container(w.into_vec()), &limits).is_err());
}

#[test]
fn bounds_pruning_branch_coverage() {
    let unknown = TimeBounds::unknown(1, 4);
    assert!(!unknown.prunes_positive_range(0, 1));
    assert!(!unknown.prunes_negated_range(0, 1));
    assert!(!unknown.prunes_value_less());
    assert!(!unknown.prunes_exists());

    let none = TimeBounds {
        field_id: 1,
        known: true,
        presence: PRESENCE_NONE,
        live_count: 4,
        present_count: 0,
        min_micros: 0,
        max_micros: 0,
        ordered: false,
    };
    assert!(none.prunes_positive_range(0, 1));
    assert!(none.prunes_exists());
    assert!(!none.prunes_value_less());

    let some = TimeBounds {
        presence: PRESENCE_SOME,
        live_count: 4,
        present_count: 2,
        min_micros: 10,
        max_micros: 20,
        ..none
    };
    assert!(!some.prunes_negated_range(-100, 100));
    assert!(!some.prunes_value_less());

    let all = TimeBounds {
        presence: PRESENCE_ALL,
        present_count: 4,
        ..some
    };
    assert!(all.prunes_negated_range(0, 100));
    assert!(all.prunes_value_less());
    assert!(!all.prunes_positive_range(0, 100));

    // Geo pruning branches.
    let unknown_geo = GeoBounds::unknown(2, 3);
    assert!(!unknown_geo.prunes_positive_box(0.0, 0.0, 1.0, 1.0));
    let empty = GeoBounds {
        known: true,
        presence: PRESENCE_NONE,
        live_count: 3,
        present_count: 0,
        ..unknown_geo
    };
    assert!(empty.prunes_positive_box(0.0, 0.0, 1.0, 1.0));
    let normal = GeoBounds {
        known: true,
        presence: PRESENCE_ALL,
        live_count: 3,
        present_count: 3,
        west: 10.0,
        south: 10.0,
        east: 20.0,
        north: 20.0,
        crosses_antimeridian: false,
        ..unknown_geo
    };
    assert!(!normal.prunes_positive_box(12.0, 12.0, 18.0, 18.0));
    assert!(normal.prunes_positive_box(0.0, 0.0, 5.0, 5.0));
    assert!(normal.prunes_positive_box(30.0, 0.0, 40.0, 40.0));
    // Crossing envelope vs crossing box.
    let crossing = GeoBounds {
        west: 170.0,
        east: -170.0,
        crosses_antimeridian: true,
        ..normal
    };
    assert!(!crossing.prunes_positive_box(175.0, 0.0, -175.0, 30.0));
    assert!(crossing.prunes_positive_box(0.0, 0.0, 5.0, 5.0));
}

#[test]
fn manifest_feature_order_and_schema_length_errors() {
    use super::manifest::Manifest;
    let limits = SegmentLimits::default();
    let schema_bytes = small_codec_schema().encode().unwrap();

    // Oversized schema length.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(u32::MAX);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());

    // Non-ascending feature set.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(0); // no segments
    payload.u32(2);
    payload.u16(2);
    payload.u16(1);
    payload.u16(1); // out of order
    payload.u16(1);
    payload.u32(0);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());

    // Duplicate segment ids rejected.
    let mut payload = ByteWriter::new();
    payload.u16(1);
    payload.u32(schema_bytes.len() as u32);
    payload.bytes(&schema_bytes);
    payload.u32(2);
    for _ in 0..2 {
        payload.len_prefixed_u16(b"segments/a").unwrap();
        payload.len_prefixed_u16(b"objects/a").unwrap();
        payload.u8(0);
        payload.u64(1);
        payload.bytes(&[0u8; 32]);
        payload.u8(0);
        payload.u32(0);
        payload.u32(0);
    }
    payload.u32(0);
    payload.u32(0);
    assert!(Manifest::decode(&manifest_container(payload.into_vec()), &limits).is_err());
}
