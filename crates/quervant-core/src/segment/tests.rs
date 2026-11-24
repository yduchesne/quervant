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

/// PR 15E-B1b ordering proof: the decoder rejects a non-increasing doc-id delta on
/// the read path. `search::execute::LeafData::matches` binary-searches decoded
/// postings, so this rejection is the invariant that makes the search valid; a
/// malformed block must never decode into an unsorted (or duplicated) vector.
#[test]
fn decoder_rejects_nonmonotone_doc_id_deltas() {
    use super::postings::{Posting, PostingsReader, encode_postings_block};
    let limits = SegmentLimits::default();
    let doc_only = |doc_id: u64| Posting {
        doc_id,
        freq: 1,
        occurrences: Vec::new(),
    };
    let bytes = encode_postings_block(5, &[doc_only(1), doc_only(2)], &limits).unwrap();
    // Layout: u8 occurrence kind, u64 posting count, u64 frequency total, then
    // `(doc-id delta, frequency)` varints. The second delta is the last-but-one
    // byte of this two-posting, doc-only block.
    assert_eq!(bytes.len(), 1 + 8 + 8 + 4);
    let mut corrupt = bytes.clone();
    corrupt[bytes.len() - 2] = 0;
    let mut reader = PostingsReader::new(&corrupt, 5, &limits).unwrap();
    assert_eq!(reader.next().unwrap().unwrap().doc_id, 1);
    assert!(matches!(
        reader.next(),
        Err(SegmentError::NonMonotoneDocId {
            previous: 1,
            next: 1
        })
    ));
}

// ---------------------------------------------------------------------------
// PERF-06-A2: validated document/frequency-only postings view.
// ---------------------------------------------------------------------------

fn a2_occurrence(position: u64) -> super::postings::Occurrence {
    super::postings::Occurrence {
        position,
        position_length: 1,
        value_index: 0,
        start_offset: position,
        end_offset: position + 1,
    }
}

/// Three positional postings used by the A2 document/frequency parity tests.
fn a2_three_posting_block(limits: &SegmentLimits) -> Vec<u8> {
    use super::postings::{Posting, encode_postings_block};
    let postings = vec![
        Posting {
            doc_id: 1,
            freq: 2,
            occurrences: vec![a2_occurrence(1), a2_occurrence(3)],
        },
        Posting {
            doc_id: 4,
            freq: 1,
            occurrences: vec![a2_occurrence(2)],
        },
        Posting {
            doc_id: 7,
            freq: 3,
            occurrences: vec![a2_occurrence(5), a2_occurrence(6), a2_occurrence(9)],
        },
    ];
    encode_postings_block(8, &postings, limits).unwrap()
}

const A2_THREE_DOC_FREQ: [(u64, u64); 3] = [(1, 2), (4, 1), (7, 3)];
const A2_THREE_OCCURRENCES: [usize; 3] = [2, 1, 3];

#[test]
fn a2_u01_docfreq_positional_parity_and_zero_materialization() {
    use super::postings::{PostingsReader, decode_observation};
    let limits = SegmentLimits::default();
    let bytes = a2_three_posting_block(&limits);

    decode_observation::reset();
    let mut full = PostingsReader::new(&bytes, 8, &limits).unwrap();
    for (index, (doc_id, freq)) in A2_THREE_DOC_FREQ.iter().enumerate() {
        let posting = full.next().unwrap().unwrap();
        assert_eq!(posting.doc_id, *doc_id);
        assert_eq!(posting.freq, *freq);
        assert_eq!(posting.occurrences.len(), A2_THREE_OCCURRENCES[index]);
    }
    assert!(full.next().unwrap().is_none());
    assert!(full.next().unwrap().is_none());
    let (full_reserves, full_clones) = decode_observation::counts();
    assert!(
        full_reserves > 0,
        "full mode must reserve positional vectors"
    );
    assert!(full_clones > 0, "full mode must clone the cached posting");

    decode_observation::reset();
    let mut lean = PostingsReader::new(&bytes, 8, &limits)
        .unwrap()
        .into_doc_freq();
    let mut seen = Vec::new();
    while let Some(posting) = lean.next().unwrap() {
        seen.push((posting.doc_id, posting.freq));
    }
    assert_eq!(seen, A2_THREE_DOC_FREQ);
    assert!(lean.next().unwrap().is_none());
    let (lean_reserves, lean_clones) = decode_observation::counts();
    assert_eq!(
        lean_reserves, 0,
        "lean mode must not reserve positional vectors"
    );
    assert_eq!(lean_clones, 0, "lean mode must not clone full postings");
}

#[test]
fn a2_u05_positional_hypothetical_budget() {
    use super::postings::{Occurrence, Posting, PostingsReader, encode_postings_block};
    let postings = vec![Posting {
        doc_id: 1,
        freq: 2,
        occurrences: vec![a2_occurrence(1), a2_occurrence(2)],
    }];
    let bytes = encode_postings_block(4, &postings, &SegmentLimits::default()).unwrap();
    let exact = (2 * std::mem::size_of::<Occurrence>()) as u64;

    // The historical `check_alloc::<Occurrence>(freq)` bound applies in both modes
    // even though the lean mode never physically allocates the vector.
    let limits = SegmentLimits::default().with_max_single_allocation(exact);
    let mut full = PostingsReader::new(&bytes, 4, &limits).unwrap();
    assert_eq!(full.next().unwrap().unwrap().freq, 2);
    let mut lean = PostingsReader::new(&bytes, 4, &limits)
        .unwrap()
        .into_doc_freq();
    assert_eq!(lean.next().unwrap().unwrap().freq, 2);

    let limits = SegmentLimits::default().with_max_single_allocation(exact - 1);
    let mut full = PostingsReader::new(&bytes, 4, &limits).unwrap();
    let full_error = full.next().unwrap_err();
    let mut lean = PostingsReader::new(&bytes, 4, &limits)
        .unwrap()
        .into_doc_freq();
    let lean_error = lean.next().unwrap_err();
    for error in [&full_error, &lean_error] {
        match error {
            SegmentError::LimitExceeded { limit, requested } => {
                assert_eq!(*limit, exact - 1);
                assert_eq!(*requested, exact);
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }
    assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));

    // The decoded-entry ceiling is still evaluated before the positional
    // allocation preflight.
    let limits = SegmentLimits::default()
        .with_max_decoded_entries(1)
        .with_max_single_allocation(2);
    let mut full = PostingsReader::new(&bytes, 4, &limits).unwrap();
    let full_error = full.next().unwrap_err();
    let mut lean = PostingsReader::new(&bytes, 4, &limits)
        .unwrap()
        .into_doc_freq();
    let lean_error = lean.next().unwrap_err();
    for error in [&full_error, &lean_error] {
        match error {
            SegmentError::LimitExceeded { limit, requested } => {
                assert_eq!(*limit, 1);
                assert_eq!(*requested, 2);
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }
    assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
}

#[test]
fn a2_u07_lean_mixed_conversion_and_no_clones() {
    use super::postings::{PostingsReader, decode_observation};
    let limits = SegmentLimits::default();
    let bytes = a2_three_posting_block(&limits);

    decode_observation::reset();
    let mut lean = PostingsReader::new(&bytes, 8, &limits)
        .unwrap()
        .into_doc_freq();
    let mut seen = Vec::new();
    while let Some(posting) = lean.next().unwrap() {
        seen.push((posting.doc_id, posting.freq));
    }
    assert_eq!(seen, A2_THREE_DOC_FREQ);
    assert_eq!(decode_observation::counts(), (0, 0));

    // Conversion after a full read continues at the NEXT unread posting and
    // releases the cached positional clone.
    decode_observation::reset();
    let mut cursor = PostingsReader::new(&bytes, 8, &limits).unwrap();
    let first = cursor.next().unwrap().unwrap();
    assert_eq!((first.doc_id, first.freq), (1, 2));
    assert_eq!(decode_observation::counts(), (1, 1));
    let mut lean = cursor.into_doc_freq();
    let mut rest = Vec::new();
    while let Some(posting) = lean.next().unwrap() {
        rest.push((posting.doc_id, posting.freq));
    }
    assert_eq!(rest, vec![(4, 1), (7, 3)]);
    assert_eq!(
        decode_observation::counts(),
        (1, 1),
        "no reserve or clone may happen after conversion"
    );

    // Dropping a partially read cursor has no durable side effect: the borrowed
    // block is unchanged and a fresh reader still decodes every posting.
    let before = bytes.clone();
    drop(lean);
    assert_eq!(bytes, before);
    let mut full = PostingsReader::new(&bytes, 8, &limits).unwrap();
    let mut reread = Vec::new();
    while let Some(posting) = full.next().unwrap() {
        reread.push((posting.doc_id, posting.freq));
    }
    assert_eq!(reread, A2_THREE_DOC_FREQ);
}

fn a2_raw_block(kind: u8, posting_doc_count: u64, freq_total: u64, body: &[u8]) -> Vec<u8> {
    use super::format::ByteWriter;
    let mut writer = ByteWriter::new();
    writer.u8(kind);
    writer.u64(posting_doc_count);
    writer.u64(freq_total);
    writer.bytes(body);
    writer.into_vec()
}

fn a2_varint_bytes(values: &[u64]) -> Vec<u8> {
    use super::format::ByteWriter;
    let mut writer = ByteWriter::new();
    for value in values {
        writer.varint(*value);
    }
    writer.into_vec()
}

/// Drive a block through the full reader, stopping at the first error.
fn a2_drive_full(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, Option<SegmentError>) {
    use super::postings::PostingsReader;
    let mut reader = PostingsReader::new(bytes, segment_doc_count, limits).unwrap();
    let mut records = Vec::new();
    loop {
        match reader.next() {
            Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
            Ok(None) => return (records, None),
            Err(error) => return (records, Some(error)),
        }
    }
}

/// Drive a block through the doc/freq-only reader, stopping at the first error.
fn a2_drive_lean(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, Option<SegmentError>) {
    use super::postings::PostingsReader;
    let mut reader = PostingsReader::new(bytes, segment_doc_count, limits)
        .unwrap()
        .into_doc_freq();
    let mut records = Vec::new();
    loop {
        match reader.next() {
            Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
            Ok(None) => return (records, None),
            Err(error) => return (records, Some(error)),
        }
    }
}

/// Assert both modes emit exactly the same records and the same typed error.
fn a2_assert_parity(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, SegmentError) {
    let (full_records, full_error) = a2_drive_full(bytes, segment_doc_count, limits);
    let (lean_records, lean_error) = a2_drive_lean(bytes, segment_doc_count, limits);
    assert_eq!(full_records, lean_records, "record sequences must match");
    let full_error = full_error.expect("expected the full reader to fail");
    let lean_error = lean_error.expect("expected the doc/freq reader to fail");
    assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
    (lean_records, lean_error)
}

/// Cancellation double that counts boundary polls and cancels on poll
/// `cancel_after + 1`.
#[derive(Debug, Default)]
struct A2CountingCancel {
    polls: std::cell::Cell<u64>,
    cancel_after: u64,
}

impl crate::analysis::Cancellation for A2CountingCancel {
    fn is_cancelled(&self) -> bool {
        let polled = self.polls.get() + 1;
        self.polls.set(polled);
        polled > self.cancel_after
    }
}

#[test]
fn a2_u02_doc_only_and_empty_lookup() {
    use super::build::{Layout, SegmentBuilder};
    use super::model::SegmentDocument;
    use super::postings::{OCCURRENCE_DOC_ONLY, Posting, PostingsReader, encode_postings_block};
    let limits = SegmentLimits::default();
    let postings = vec![
        Posting {
            doc_id: 0,
            freq: 1,
            occurrences: vec![],
        },
        Posting {
            doc_id: 2,
            freq: 2,
            occurrences: vec![],
        },
    ];
    let bytes = encode_postings_block(4, &postings, &limits).unwrap();
    assert_eq!(bytes[0], OCCURRENCE_DOC_ONLY);

    let mut full = PostingsReader::new(&bytes, 4, &limits).unwrap();
    let mut full_records = Vec::new();
    while let Some(posting) = full.next().unwrap() {
        assert!(posting.occurrences.is_empty());
        full_records.push((posting.doc_id, posting.freq));
    }
    let mut lean = PostingsReader::new(&bytes, 4, &limits)
        .unwrap()
        .into_doc_freq();
    let mut lean_records = Vec::new();
    while let Some(posting) = lean.next().unwrap() {
        lean_records.push((posting.doc_id, posting.freq));
    }
    assert_eq!(full_records, vec![(0, 1), (2, 2)]);
    assert_eq!(lean_records, full_records);
    assert!(full.next().unwrap().is_none());
    assert!(lean.next().unwrap().is_none());

    // A zero-entry raw postings header is rejected at construction, as before.
    let zero = a2_raw_block(OCCURRENCE_DOC_ONLY, 0, 0, &[]);
    assert!(matches!(
        PostingsReader::new(&zero, 4, &limits),
        Err(SegmentError::Corrupt {
            context: "postings",
            detail,
        }) if detail == "zero posting count"
    ));

    // Real segment integration: an absent term still resolves to `None`, and a
    // present term decodes through the doc/freq view.
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
    assert!(reader.postings(0, "absent_a2").unwrap().is_none());
    let mut present = reader.postings(0, "term").unwrap().unwrap().into_doc_freq();
    assert_eq!(present.next().unwrap().unwrap().doc_id, 0);
    assert!(present.next().unwrap().is_none());
}

#[test]
fn a2_u03_doc_id_and_frequency_errors_match_full() {
    use super::postings::OCCURRENCE_DOC_ONLY;
    let limits = SegmentLimits::default();

    // Duplicate second doc-id delta: the valid first posting is still emitted.
    let bytes = a2_raw_block(OCCURRENCE_DOC_ONLY, 2, 2, &a2_varint_bytes(&[1, 1, 0, 1]));
    let (records, error) = a2_assert_parity(&bytes, 8, &limits);
    assert_eq!(records, vec![(1, 1)]);
    assert!(matches!(
        error,
        SegmentError::NonMonotoneDocId {
            previous: 1,
            next: 1
        }
    ));

    // Second doc-id delta overflows u64.
    let bytes = a2_raw_block(
        OCCURRENCE_DOC_ONLY,
        2,
        2,
        &a2_varint_bytes(&[1, 1, u64::MAX, 1]),
    );
    let (records, error) = a2_assert_parity(&bytes, u64::MAX, &limits);
    assert_eq!(records, vec![(1, 1)]);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "doc id overflow"
    ));

    // First doc id out of range.
    let bytes = a2_raw_block(OCCURRENCE_DOC_ONLY, 1, 1, &a2_varint_bytes(&[9, 1]));
    let (records, error) = a2_assert_parity(&bytes, 5, &limits);
    assert!(records.is_empty());
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "doc id out of range"
    ));

    // Zero frequency.
    let bytes = a2_raw_block(OCCURRENCE_DOC_ONLY, 1, 0, &a2_varint_bytes(&[0, 0]));
    let (records, error) = a2_assert_parity(&bytes, 5, &limits);
    assert!(records.is_empty());
    assert!(matches!(error, SegmentError::ZeroFrequency { doc_id: 0 }));

    // Frequency above the decoded-entry ceiling.
    let tight = SegmentLimits::default().with_max_decoded_entries(1);
    let bytes = a2_raw_block(OCCURRENCE_DOC_ONLY, 1, 2, &a2_varint_bytes(&[0, 2]));
    let (records, error) = a2_assert_parity(&bytes, 5, &tight);
    assert!(records.is_empty());
    assert!(matches!(
        error,
        SegmentError::LimitExceeded {
            limit: 1,
            requested: 2
        }
    ));
}

#[test]
fn a2_u04_all_positional_corruptions_match_full() {
    use super::format::ByteWriter;
    use super::postings::OCCURRENCE_POSITIONAL;
    let limits = SegmentLimits::default();
    let block = |body: &[u8]| a2_raw_block(OCCURRENCE_POSITIONAL, 1, 2, body);
    // Base layout: doc delta 0, freq 2, then (1,1,0,0,1) and (2,1,0,2,3).
    let base = [0u64, 2, 1, 1, 0, 0, 1, 2, 1, 0, 2, 3];
    // The pristine block decodes in both modes.
    let pristine = block(&a2_varint_bytes(&base));
    assert_eq!(a2_drive_full(&pristine, 4, &limits).0, vec![(0, 2)]);
    assert_eq!(a2_drive_lean(&pristine, 4, &limits).0, vec![(0, 2)]);

    // Second position delta is zero.
    let body = a2_varint_bytes(&[0, 2, 1, 1, 0, 0, 1, 0, 1, 0, 2, 3]);
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::NonMonotonePosition { doc_id: 0 }
    ));

    // Zero position length, first then second occurrence.
    for body in [
        a2_varint_bytes(&[0, 2, 1, 0, 0, 0, 1, 2, 1, 0, 2, 3]),
        a2_varint_bytes(&[0, 2, 1, 1, 0, 0, 1, 2, 0, 0, 2, 3]),
    ] {
        let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
        assert!(matches!(
            error,
            SegmentError::Corrupt {
                context: "postings",
                detail,
            } if detail == "zero position length"
        ));
    }

    // Value index decreases on the second occurrence.
    let body = a2_varint_bytes(&[0, 2, 1, 1, 1, 0, 1, 2, 1, 0, 2, 3]);
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "value index decreased"
    ));

    // Start offset exceeds end offset.
    let body = a2_varint_bytes(&[0, 2, 1, 1, 0, 2, 1, 2, 1, 0, 2, 3]);
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "start offset exceeds end offset"
    ));

    // Second position overflows u64.
    let body = a2_varint_bytes(&[0, 2, 1, 1, 0, 0, 1, u64::MAX, 1, 0, 2, 3]);
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "position overflow"
    ));

    // Truncated final field.
    let mut body = a2_varint_bytes(&base);
    body.pop();
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::Truncated {
            context: "end offset",
            needed: 1,
            available: 0
        }
    ));

    // Non-canonical two-byte varint for the second start offset.
    let mut body = ByteWriter::new();
    for value in [0u64, 2, 1, 1, 0, 0, 1, 2, 1, 0] {
        body.varint(value);
    }
    body.u8(0x82);
    body.u8(0x00);
    body.varint(3);
    let body = body.into_vec();
    let (_, error) = a2_assert_parity(&block(&body), 4, &limits);
    assert!(matches!(
        error,
        SegmentError::InvalidVarint {
            context: "start offset"
        }
    ));
}

#[test]
fn a2_u06_full_reader_advance_and_phrase_unmodified() {
    use super::postings::PostingsReader;
    let limits = SegmentLimits::default();
    let bytes = a2_three_posting_block(&limits);
    let mut reader = PostingsReader::new(&bytes, 8, &limits).unwrap();
    assert!(reader.is_positional());

    let first = reader.next().unwrap().unwrap();
    assert_eq!((first.doc_id, first.freq), (1, 2));
    assert_eq!(first.occurrences.len(), 2);
    // Cached-current behaviour: a non-forward target returns the cached clone.
    assert_eq!(reader.advance(1).unwrap().unwrap(), first);
    assert_eq!(reader.advance(0).unwrap().unwrap(), first);

    let second = reader.advance(4).unwrap().unwrap();
    assert_eq!((second.doc_id, second.freq), (4, 1));
    assert_eq!(second.occurrences.len(), 1);
    let flag = crate::analysis::CancellationFlag::new();
    assert_eq!(reader.advance_with(4, &flag).unwrap().unwrap(), second);

    let third = reader.advance_with(7, &flag).unwrap().unwrap();
    assert_eq!((third.doc_id, third.freq), (7, 3));
    assert_eq!(third.occurrences.len(), 3);
    assert_eq!(third.occurrences[2].position, 9);
    assert!(reader.advance(99).unwrap().is_none());
    assert!(reader.next().unwrap().is_none());
    assert!(reader.next().unwrap().is_none());

    // Doc-only blocks are not positional, and the full reader keeps empty vectors.
    let doc_only = a2_raw_block(
        super::postings::OCCURRENCE_DOC_ONLY,
        1,
        1,
        &a2_varint_bytes(&[0, 1]),
    );
    let mut reader = PostingsReader::new(&doc_only, 4, &limits).unwrap();
    assert!(!reader.is_positional());
    assert!(reader.next().unwrap().unwrap().occurrences.is_empty());
}

#[test]
fn a2_u08_cancel_and_corrupt_unselected() {
    use super::postings::{OCCURRENCE_POSITIONAL, PostingsReader};
    let limits = SegmentLimits::default();

    // First posting valid, second posting's occurrence has zero position length.
    // The second document is treated as a dead/nonwinning candidate by an
    // imaginary caller: the decoder must still reject the malformed record.
    let body = a2_varint_bytes(&[
        0, 2, 1, 1, 0, 0, 1, 2, 1, 0, 2, 3, // doc 0, freq 2, valid occurrences
        3, 1, 1, 0, 0, 0, 1, // doc 3, freq 1, zero position length
    ]);
    let bytes = a2_raw_block(OCCURRENCE_POSITIONAL, 2, 3, &body);
    let (records, error) = a2_assert_parity(&bytes, 8, &limits);
    assert_eq!(records, vec![(0, 2)]);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail == "zero position length"
    ));

    // Boundary cancellation: exactly one poll per attempted posting, and nothing
    // inside the per-occurrence loop.
    let valid = a2_varint_bytes(&[
        0, 2, 1, 1, 0, 0, 1, 2, 1, 0, 2, 3, // doc 0, freq 2
        3, 1, 1, 1, 0, 4, 5, // doc 3, freq 1
    ]);
    let valid = a2_raw_block(OCCURRENCE_POSITIONAL, 2, 3, &valid);
    let full_cancel = A2CountingCancel {
        polls: Default::default(),
        cancel_after: u64::MAX,
    };
    let mut full = PostingsReader::new(&valid, 8, &limits).unwrap();
    while full.next_with(&full_cancel).unwrap().is_some() {}
    let lean_cancel = A2CountingCancel {
        polls: Default::default(),
        cancel_after: u64::MAX,
    };
    let mut lean = PostingsReader::new(&valid, 8, &limits)
        .unwrap()
        .into_doc_freq();
    while lean.next_with(&lean_cancel).unwrap().is_some() {}
    assert_eq!(full_cancel.polls.get(), 3, "one poll per attempted posting");
    assert_eq!(lean_cancel.polls.get(), full_cancel.polls.get());

    // Cancel before the first posting, after one posting, and instead of EOF.
    for cancel_after in [0u64, 1, 2] {
        let full_cancel = A2CountingCancel {
            polls: Default::default(),
            cancel_after,
        };
        let mut full = PostingsReader::new(&valid, 8, &limits).unwrap();
        let mut full_records = Vec::new();
        let mut full_error = None;
        loop {
            match full.next_with(&full_cancel) {
                Ok(Some(posting)) => full_records.push((posting.doc_id, posting.freq)),
                Ok(None) => break,
                Err(error) => {
                    full_error = Some(error);
                    break;
                }
            }
        }
        let lean_cancel = A2CountingCancel {
            polls: Default::default(),
            cancel_after,
        };
        let mut lean = PostingsReader::new(&valid, 8, &limits)
            .unwrap()
            .into_doc_freq();
        let mut lean_records = Vec::new();
        let mut lean_error = None;
        loop {
            match lean.next_with(&lean_cancel) {
                Ok(Some(posting)) => lean_records.push((posting.doc_id, posting.freq)),
                Ok(None) => break,
                Err(error) => {
                    lean_error = Some(error);
                    break;
                }
            }
        }
        assert_eq!(full_records, lean_records);
        let full_error = full_error.expect("cancellation must win");
        let lean_error = lean_error.expect("cancellation must win");
        assert!(matches!(full_error, SegmentError::Cancelled));
        assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
        assert_eq!(full_cancel.polls.get(), cancel_after + 1);
        assert_eq!(lean_cancel.polls.get(), full_cancel.polls.get());
    }
}

#[test]
fn a2_u09_trailing_and_repeated_eof() {
    use super::postings::PostingsReader;
    let limits = SegmentLimits::default();
    let bytes = a2_three_posting_block(&limits);

    let mut trailing = bytes.clone();
    trailing.push(0);
    let (records, error) = a2_assert_parity(&trailing, 8, &limits);
    assert_eq!(records, A2_THREE_DOC_FREQ);
    assert!(matches!(
        error,
        SegmentError::Corrupt {
            context: "postings",
            detail,
        } if detail.ends_with("trailing bytes")
    ));

    // A pristine block reports EOF repeatedly in both modes.
    let mut full = PostingsReader::new(&bytes, 8, &limits).unwrap();
    while full.next().unwrap().is_some() {}
    assert!(full.next().unwrap().is_none());
    assert!(full.next().unwrap().is_none());
    let mut lean = PostingsReader::new(&bytes, 8, &limits)
        .unwrap()
        .into_doc_freq();
    while lean.next().unwrap().is_some() {}
    assert!(lean.next().unwrap().is_none());
    assert!(lean.next().unwrap().is_none());

    // Cancellation before a repeated EOF still takes precedence.
    let flag = crate::analysis::CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        full.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));
    assert!(matches!(
        lean.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));
}

#[test]
fn a2_u10_frequency_transport_for_work_charges() {
    use super::postings::{Posting, PostingsReader, encode_postings_block};
    let limits = SegmentLimits::default();
    // Document 5 is a designated dead/nonwinning candidate: the decoder must still
    // emit it so the caller can apply its existing live filter and scan charge.
    let postings = vec![
        Posting {
            doc_id: 1,
            freq: 2,
            occurrences: vec![a2_occurrence(1), a2_occurrence(4)],
        },
        Posting {
            doc_id: 5,
            freq: 3,
            occurrences: vec![a2_occurrence(2), a2_occurrence(3), a2_occurrence(5)],
        },
    ];
    let bytes = encode_postings_block(8, &postings, &limits).unwrap();
    let header_total = PostingsReader::new(&bytes, 8, &limits)
        .unwrap()
        .freq_total();
    assert_eq!(header_total, 5);

    let (full_records, full_error) = a2_drive_full(&bytes, 8, &limits);
    assert!(full_error.is_none());
    let (lean_records, lean_error) = a2_drive_lean(&bytes, 8, &limits);
    assert!(lean_error.is_none());
    assert_eq!(full_records, vec![(1, 2), (5, 3)]);
    assert_eq!(lean_records, full_records);
    assert_eq!(
        full_records.iter().map(|(_, freq)| *freq).sum::<u64>(),
        header_total
    );
    assert_eq!(
        lean_records.iter().map(|(_, freq)| *freq).sum::<u64>(),
        header_total
    );
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
        mutation_state: None,
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

// ---------------------------------------------------------------------------
// PR 15E Phase 3 — selective stored-document materialization
// ---------------------------------------------------------------------------

mod phase3 {
    use super::super::model::SegmentDocument;
    use super::super::stored::{decode_stored, decode_stored_selected, encode_stored};
    use super::*;

    fn phase3_contract_schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "kw",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "text",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "flag",
                    FieldType::Bool,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "u",
                    FieldType::U64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "score",
                    FieldType::F64,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::new(false, true, true),
                ),
                FieldDefinition::new(
                    "ip",
                    FieldType::IpAddress,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "net",
                    FieldType::IpNetwork,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                ),
                // Indexed but NOT stored: a presence bit for this field is corrupt.
                FieldDefinition::new(
                    "raw",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn codec_schema() -> super::super::schema::CodecSchema {
        use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
        let schema = phase3_contract_schema();
        let registry = AnalyzerRegistry::builtin();
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).unwrap();
        super::super::schema::CodecSchema::from_contract(&schema, &bindings).unwrap()
    }

    fn limits() -> SegmentLimits {
        SegmentLimits::default()
    }

    /// A document exercising every value state and every stored field type.
    fn rich_document(key: &str, variant: u64) -> SegmentDocument {
        let mut doc = SegmentDocument::new(DocumentKey::new(key).unwrap());
        let insert = |doc: &mut SegmentDocument, name: &str, values: FieldValues| {
            doc.fields.insert(name.to_owned(), values);
        };
        insert(
            &mut doc,
            "kw",
            FieldValues::Single(FieldValue::Keyword(format!("k{key}"))),
        );
        insert(
            &mut doc,
            "text",
            FieldValues::Single(FieldValue::Text(format!("text {key} ünïcode"))),
        );
        insert(
            &mut doc,
            "flag",
            FieldValues::Single(FieldValue::Bool(variant % 2 == 0)),
        );
        insert(
            &mut doc,
            "n",
            FieldValues::Single(FieldValue::I64(-(variant as i64))),
        );
        insert(&mut doc, "u", FieldValues::Single(FieldValue::U64(variant)));
        insert(
            &mut doc,
            "score",
            FieldValues::Single(FieldValue::F64(0.5 * variant as f64)),
        );
        insert(
            &mut doc,
            "ts",
            FieldValues::Single(FieldValue::Timestamp(
                crate::contract::value::Timestamp::from_micros(variant as i64),
            )),
        );
        insert(
            &mut doc,
            "loc",
            FieldValues::Single(FieldValue::GeoPoint(
                GeoPoint::new(1.0 + variant as f64 / 100.0, 2.0).unwrap(),
            )),
        );
        insert(
            &mut doc,
            "ip",
            FieldValues::Single(FieldValue::Ip("10.0.0.1".parse().unwrap())),
        );
        insert(
            &mut doc,
            "net",
            FieldValues::Single(FieldValue::Cidr(
                IpNetwork::new("10.0.0.0".parse().unwrap(), 24).unwrap(),
            )),
        );
        insert(
            &mut doc,
            "body",
            FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![
                (
                    "n".to_owned(),
                    JsonValue::Number(JsonNumber::I64(variant as i64)),
                ),
                (
                    "list".to_owned(),
                    JsonValue::Array(vec![
                        JsonValue::Null,
                        JsonValue::Bool(true),
                        JsonValue::String(format!("s{variant}")),
                    ]),
                ),
            ]))),
        );
        insert(
            &mut doc,
            "tags",
            FieldValues::Multi(vec![
                FieldValue::Keyword("a".to_owned()),
                FieldValue::Keyword("b".to_owned()),
            ]),
        );
        doc
    }

    fn simple_documents(count: u64) -> Vec<SegmentDocument> {
        (0..count)
            .map(|index| rich_document(&format!("k{index:03}"), index))
            .collect()
    }

    fn encoded(docs: &[SegmentDocument]) -> Vec<u8> {
        encode_stored(&codec_schema(), docs, &limits()).unwrap()
    }

    fn assert_selection_matches_full(docs: &[SegmentDocument], selection: &[u64]) {
        let schema = codec_schema();
        let limits = limits();
        let bytes = encoded(docs);
        let full = decode_stored(&schema, &bytes, &limits).unwrap();
        let selected = decode_stored_selected(&schema, &bytes, &limits, selection).unwrap();
        assert_eq!(selected.len(), selection.len());
        for (position, doc_id) in selection.iter().enumerate() {
            assert_eq!(selected[position].0, *doc_id);
            assert_eq!(
                selected[position].1, full[*doc_id as usize],
                "record {doc_id} differs from the full decoder"
            );
        }
    }

    // U01/U02 — selection sizes, boundaries and the documented failure modes.
    #[test]
    fn phase3_u01_u02_selection_boundaries() {
        let docs = simple_documents(6);
        assert_selection_matches_full(&docs, &[]);
        assert_selection_matches_full(&docs, &[0]);
        assert_selection_matches_full(&docs, &[5]);
        assert_selection_matches_full(&docs, &[0, 1]);
        assert_selection_matches_full(&docs, &[0, 2, 3, 5]);
        assert_selection_matches_full(&docs, &[0, 1, 2, 3, 4, 5]);
        assert_selection_matches_full(&docs, &[2, 3]);

        let schema = codec_schema();
        let limits = limits();
        let bytes = encoded(&docs);
        // Unsorted, duplicate and out-of-range selections are typed failures.
        for (selection, context) in [
            (vec![2, 1], "stored selection"),
            (vec![1, 1], "stored selection"),
            (vec![6], "stored"),
        ] {
            let error = decode_stored_selected(&schema, &bytes, &limits, &selection).unwrap_err();
            assert!(
                matches!(&error, SegmentError::Corrupt { context: actual, .. } if *actual == context),
                "{selection:?}: unexpected {error:?}"
            );
        }
    }

    /// A document carrying exactly one stored field, so the encoded record layout
    /// is fully predictable for byte-level corruption tests.
    fn single_field_document(key: &str, field: &str, values: FieldValues) -> SegmentDocument {
        let mut doc = SegmentDocument::new(DocumentKey::new(key).unwrap());
        doc.fields.insert(field.to_owned(), values);
        doc
    }

    /// Byte offset of the first payload byte of record `index`'s single field.
    fn single_field_payload_offset(
        docs: &[SegmentDocument],
        index: usize,
        schema: &super::super::schema::CodecSchema,
        key_bytes: usize,
        prefix_bytes: usize,
    ) -> usize {
        let record_start = encoded(&docs[..index]).len();
        let bitmap_len = schema.field_count().div_ceil(8);
        // u16 key length + key + bitmap + u32 field id + u8 state + payload prefix.
        record_start + 2 + key_bytes + bitmap_len + 4 + 1 + prefix_bytes
    }

    // U04/U05/U06/U14 — corruption in an UNSELECTED record is still detected.
    #[test]
    fn phase3_u04_u05_u06_u14_unselected_corruption_is_rejected() {
        let schema = codec_schema();
        let limits = limits();
        let bitmap_len = schema.field_count().div_ceil(8);
        // Selected prefix record; the corruption always lands in record 1 or later.
        let clean_prefix = single_field_document(
            "k0",
            "kw",
            FieldValues::Single(FieldValue::Keyword("v".into())),
        );

        let mut cases: Vec<(&str, Vec<SegmentDocument>, Vec<u8>)> = Vec::new();

        // Invalid bool payload in an unselected record.
        let bad_doc =
            single_field_document("k1", "flag", FieldValues::Single(FieldValue::Bool(true)));
        let docs = vec![clean_prefix.clone(), bad_doc];
        let mut bytes = encoded(&docs);
        let offset = single_field_payload_offset(&docs, 1, &schema, 2, 0);
        bytes[offset] = 2;
        cases.push(("invalid bool in unselected record", docs, bytes));

        // Invalid UTF-8 keyword payload in an unselected record.
        let bad_doc = single_field_document(
            "k1",
            "kw",
            FieldValues::Single(FieldValue::Keyword("value".into())),
        );
        let docs = vec![clean_prefix.clone(), bad_doc];
        let mut bytes = encoded(&docs);
        let offset = single_field_payload_offset(&docs, 1, &schema, 2, 2);
        bytes[offset] = 0xff;
        cases.push(("invalid utf8 keyword in unselected record", docs, bytes));

        // Unknown JSON tag in an unselected record.
        let bad_doc = single_field_document(
            "k1",
            "body",
            FieldValues::Single(FieldValue::Json(JsonValue::Null)),
        );
        let docs = vec![clean_prefix.clone(), bad_doc];
        let mut bytes = encoded(&docs);
        let offset = single_field_payload_offset(&docs, 1, &schema, 2, 0);
        bytes[offset] = 9;
        cases.push(("unknown json tag in unselected record", docs, bytes));

        // Out-of-range geo coordinate in an unselected record.
        let bad_doc = single_field_document(
            "k1",
            "loc",
            FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(1.0, 2.0).unwrap())),
        );
        let docs = vec![clean_prefix.clone(), bad_doc];
        let mut bytes = encoded(&docs);
        let offset = single_field_payload_offset(&docs, 1, &schema, 2, 0);
        bytes[offset..offset + 8].copy_from_slice(&200.0f64.to_le_bytes());
        cases.push(("invalid geo in unselected record", docs, bytes));

        // Invalid CIDR prefix in an unselected record (family tag + 4 octets).
        let bad_doc = single_field_document(
            "k1",
            "net",
            FieldValues::Single(FieldValue::Cidr(
                IpNetwork::new("10.0.0.0".parse().unwrap(), 24).unwrap(),
            )),
        );
        let docs = vec![clean_prefix.clone(), bad_doc];
        let mut bytes = encoded(&docs);
        let offset = single_field_payload_offset(&docs, 1, &schema, 2, 0);
        bytes[offset + 5] = 33;
        cases.push(("invalid cidr in unselected record", docs, bytes));

        // Truncated final record.
        let posts = vec![
            clean_prefix.clone(),
            single_field_document(
                "k1",
                "kw",
                FieldValues::Single(FieldValue::Keyword("v".into())),
            ),
        ];
        let bytes = encoded(&posts);
        let truncated = bytes[..bytes.len() - 2].to_vec();
        cases.push(("truncated stored section", posts, truncated));

        // Trailing bytes after the declared records.
        let posts = vec![clean_prefix.clone()];
        let mut bytes = encoded(&posts);
        bytes.push(0);
        cases.push(("trailing bytes", posts, bytes));

        // Bad version.
        let posts = vec![clean_prefix.clone()];
        let mut bytes = encoded(&posts);
        bytes[0] = 9;
        cases.push(("bad stored version", posts, bytes));

        // Field id that does not match the presence bitmap.
        let posts = vec![clean_prefix.clone()];
        let mut bytes = encoded(&posts);
        // Start of record 0 is the section header length.
        let record_start = encoded(&[]).len();
        let field_id_offset = record_start + 2 + 2 + bitmap_len;
        bytes[field_id_offset..field_id_offset + 4].copy_from_slice(&99u32.to_le_bytes());
        let mut docs_bad = vec![clean_prefix.clone()];
        docs_bad[0] = single_field_document(
            "k0",
            "kw",
            FieldValues::Single(FieldValue::Keyword("v".into())),
        );
        cases.push(("misaligned field id", docs_bad, bytes));

        // Non-stored field marked present: set the `raw` bit (last field id).
        let posts = vec![clean_prefix.clone()];
        let mut bytes = encoded(&posts);
        let record_start = encoded(&[]).len();
        let raw_field_id = schema.field_count() - 1;
        let bitmap_offset = record_start + 2 + 2;
        bytes[bitmap_offset + raw_field_id / 8] |= 1 << (raw_field_id % 8);
        cases.push(("non-stored field present", posts, bytes));

        for (label, docs, bytes) in cases {
            // Independent oracle: the accepted full decoder rejects it too.
            assert!(
                decode_stored(&schema, &bytes, &limits).is_err(),
                "{label}: full decoder accepted corrupt bytes"
            );
            let selection: Vec<u64> = if docs.is_empty() { vec![] } else { vec![0] };
            let error = decode_stored_selected(&schema, &bytes, &limits, &selection).unwrap_err();
            assert!(
                matches!(
                    &error,
                    SegmentError::Corrupt { .. }
                        | SegmentError::InvalidUtf8 { .. }
                        | SegmentError::InvalidGeo { .. }
                        | SegmentError::InvalidIp { .. }
                        | SegmentError::Truncated { .. }
                        | SegmentError::LimitExceeded { .. }
                ),
                "{label}: unexpected {error:?}"
            );
        }

        // Sanity: a clean two-record section still decodes with a selection.
        let clean = vec![
            clean_prefix,
            single_field_document(
                "k1",
                "kw",
                FieldValues::Single(FieldValue::Keyword("v".into())),
            ),
        ];
        assert_selection_matches_full(&clean, &[0]);
    }

    // U08 — invalid keys are rejected even when their records are unselected.
    #[test]
    fn phase3_u08_invalid_keys_are_rejected() {
        let schema = codec_schema();
        let limits = limits();
        let docs = vec![
            single_field_document(
                "k0",
                "kw",
                FieldValues::Single(FieldValue::Keyword("v".into())),
            ),
            single_field_document(
                "k1",
                "kw",
                FieldValues::Single(FieldValue::Keyword("v".into())),
            ),
        ];
        let clean = encoded(&docs);
        let record_one = encoded(&docs[..1]).len();

        // Empty key in the unselected record 1.
        let mut bad = clean.clone();
        bad.drain(record_one..record_one + 2 + 2);
        bad[record_one..record_one + 2].copy_from_slice(&0u16.to_le_bytes());
        assert!(decode_stored(&schema, &bad, &limits).is_err());
        assert!(decode_stored_selected(&schema, &bad, &limits, &[0]).is_err());

        // Oversized key (> DocumentKey::MAX_BYTES) in the unselected record 1.
        let long_key = "k".repeat(DocumentKey::MAX_BYTES + 1);
        let mut patched = clean.clone();
        patched.splice(
            record_one..record_one + 4,
            [
                &(long_key.len() as u16).to_le_bytes()[..],
                long_key.as_bytes(),
            ]
            .concat(),
        );
        assert!(decode_stored(&schema, &patched, &limits).is_err());
        assert!(decode_stored_selected(&schema, &patched, &limits, &[0]).is_err());
    }

    // U07/U10 — modeled full-decode budget parity, exact limit and one below.
    #[test]
    fn phase3_u07_u10_budget_parity_exact_and_one_below() {
        let schema = codec_schema();
        let base = limits();
        let docs = simple_documents(4);
        let bytes = encoded(&docs);

        // Minimum cumulative decode ceiling that admits the accepted decoder.
        let mut low = 0u64;
        let mut high = 1 << 22;
        while low < high {
            let mid = low + (high - low) / 2;
            let candidate = base.with_max_section_decode_bytes(mid);
            if decode_stored(&schema, &bytes, &candidate).is_ok() {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        let exact = low;
        let at = base.with_max_section_decode_bytes(exact);
        assert!(decode_stored(&schema, &bytes, &at).is_ok());
        let selected = decode_stored_selected(&schema, &bytes, &at, &[1]).unwrap();
        assert_eq!(selected.len(), 1);
        assert_eq!(
            selected[0].1,
            decode_stored(&schema, &bytes, &at).unwrap()[1]
        );

        let below = base.with_max_section_decode_bytes(exact - 1);
        assert!(decode_stored(&schema, &bytes, &below).is_err());
        assert!(matches!(
            decode_stored_selected(&schema, &bytes, &below, &[1]),
            Err(SegmentError::LimitExceeded { .. })
        ));

        // The entry ceiling (applied to the declared record count) and the
        // per-allocation ceiling are enforced identically.
        let entry_capped = base.with_max_decoded_entries(3);
        assert!(decode_stored(&schema, &bytes, &entry_capped).is_err());
        assert!(decode_stored_selected(&schema, &bytes, &entry_capped, &[0]).is_err());

        let allocation_capped = base.with_max_single_allocation(4);
        assert!(decode_stored(&schema, &bytes, &allocation_capped).is_err());
        assert!(decode_stored_selected(&schema, &bytes, &allocation_capped, &[0]).is_err());
    }

    // U13 — 200 deterministic generated fixture/selection pairs.
    #[test]
    fn phase3_u13_generated_fixtures_match_full_decode() {
        let schema = codec_schema();
        let limits = limits();
        let stored_fields = [
            "kw", "text", "flag", "n", "u", "score", "ts", "loc", "ip", "net", "body", "tags",
        ];
        let mut state: u64 = 0x9E37_79B9_7F4A_7C15;
        let mut next = || {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            state >> 11
        };
        for seed in 0..200u64 {
            let doc_count = 1 + next() % 64;
            let field_count = next() % 9;
            let mut docs = Vec::new();
            for doc_index in 0..doc_count {
                let mut doc = SegmentDocument::new(
                    DocumentKey::new(format!("s{seed}d{doc_index:03}")).unwrap(),
                );
                let full = rich_document("x", doc_index);
                for field in stored_fields.iter().take(field_count as usize) {
                    if let Some(values) = full.fields.get(*field) {
                        doc.fields.insert((*field).to_owned(), values.clone());
                    }
                }
                docs.push(doc);
            }
            let bytes = encode_stored(&schema, &docs, &limits).unwrap();
            let full = decode_stored(&schema, &bytes, &limits).unwrap();
            let mut selection: Vec<u64> = (0..doc_count).filter(|_| next() % 3 == 0).collect();
            if selection.is_empty() && doc_count > 0 {
                selection.push(next() % doc_count);
            }
            let selected = decode_stored_selected(&schema, &bytes, &limits, &selection).unwrap();
            assert_eq!(selected.len(), selection.len(), "seed {seed}");
            for (position, doc_id) in selection.iter().enumerate() {
                assert_eq!(
                    selected[position].1, full[*doc_id as usize],
                    "seed {seed} doc {doc_id}"
                );
            }
        }
    }

    // U11/U12 — reader accessor: cache interaction in both orders.
    #[test]
    fn phase3_u11_u12_reader_selected_accessor_and_cache_order() {
        use super::super::build::{Layout, SegmentBuilder};
        use super::super::reader::SegmentReader;
        use crate::analysis::AnalyzerRegistry;

        let mut builder =
            SegmentBuilder::new(phase3_contract_schema(), AnalyzerRegistry::builtin())
                .unwrap()
                .with_layout(Layout::Insertion);
        for doc in simple_documents(3) {
            builder.add_document(doc).unwrap();
        }
        let built = builder.build().unwrap();
        let limits = limits();
        let expected = SegmentReader::open(built.bytes.clone(), limits)
            .unwrap()
            .stored()
            .unwrap();

        // Selective first: no full cache installed, values still exact.
        let reader = SegmentReader::open(built.bytes.clone(), limits).unwrap();
        assert!(!reader.stored_cache_is_populated());
        let selected = reader.stored_docs_selected(&[2]).unwrap();
        assert!(!reader.stored_cache_is_populated());
        assert_eq!(selected, vec![(2u64, expected[2].clone())]);
        // Legacy accessor still performs a full decode and caches it.
        let all = reader.stored().unwrap();
        assert!(reader.stored_cache_is_populated());
        assert_eq!(*all, *expected);
        // Selective reads now serve from the cache, including repeats.
        assert_eq!(
            reader.stored_docs_selected(&[0, 2]).unwrap(),
            vec![(0u64, expected[0].clone()), (2u64, expected[2].clone())]
        );
        assert!(reader.stored_docs_selected(&[3]).is_err());

        // Full first, then selective: cache reuse with identical values.
        let reader = SegmentReader::open(built.bytes.clone(), limits).unwrap();
        let all = reader.stored().unwrap();
        assert!(reader.stored_cache_is_populated());
        assert_eq!(
            reader.stored_docs_selected(&[1]).unwrap(),
            vec![(1u64, all[1].clone())]
        );
        assert_eq!(
            reader.stored_doc(1).unwrap(),
            reader.stored_docs_selected(&[1]).unwrap()[0].1
        );
    }
}

// ---------------------------------------------------------------------------
// PR 15E Phase 5 — selective DOC_KEYS decoding for single-hit queries
// ---------------------------------------------------------------------------

mod phase5 {
    use super::super::build::{Layout, SegmentBuilder};
    use super::super::format::FEATURE_BASELINE;
    use super::super::model::SegmentDocument;
    use super::super::reader::SegmentReader;
    use super::*;
    use crate::analysis::AnalyzerRegistry;

    fn p5_schema() -> Schema {
        Schema::new(
            vec![FieldDefinition::new(
                "k",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap()
    }

    fn p5_document(key: &str) -> SegmentDocument {
        let mut doc = SegmentDocument::new(DocumentKey::new(key).unwrap());
        doc.fields.insert(
            "k".to_owned(),
            FieldValues::Single(FieldValue::Keyword("v".to_owned())),
        );
        doc
    }

    /// Build a real, checksum-valid segment with one key per physical doc.
    fn build_segment(keys: &[String]) -> Vec<u8> {
        let mut builder = SegmentBuilder::new(p5_schema(), AnalyzerRegistry::builtin())
            .unwrap()
            .with_layout(Layout::Insertion);
        for key in keys {
            builder.add_document(p5_document(key)).unwrap();
        }
        builder.build().unwrap().bytes
    }

    fn doc_keys_body(bytes: &[u8]) -> Vec<u8> {
        let limits = SegmentLimits::default();
        let view = parse_container(bytes, &limits).unwrap();
        view.body(super::super::format::SectionKind::DocKeys)
            .unwrap()
            .to_vec()
    }

    /// Rebuild a checksum-valid segment with a patched DOC_KEYS body so the codec
    /// (not the container digest) is what rejects the corruption.
    fn rebuild_doc_keys(bytes: &[u8], mut patch: impl FnMut(&mut Vec<u8>)) -> Vec<u8> {
        let limits = SegmentLimits::default();
        let view = parse_container(bytes, &limits).unwrap();
        let mut builder = ContainerBuilder::new(view.kind(), view.doc_count());
        for (id, version) in view.required_features() {
            if *id != FEATURE_BASELINE {
                builder.require_feature(*id, *version);
            }
        }
        for (id, version) in view.optional_features() {
            builder.optional_feature(*id, *version);
        }
        for entry in view.sections() {
            let mut body = view.body(entry.kind).unwrap().to_vec();
            if entry.kind == super::super::format::SectionKind::DocKeys {
                patch(&mut body);
            }
            builder.section(entry.kind, entry.flags, entry.aux, body);
        }
        builder.build().unwrap()
    }

    fn open(bytes: Vec<u8>) -> SegmentReader {
        SegmentReader::open(bytes, SegmentLimits::default()).unwrap()
    }

    /// Independent expected key for physical position `index`.
    fn expected_key(keys: &[String], index: usize) -> String {
        keys[index].clone()
    }

    /// Open a segment whose DOC_KEYS body was patched; the container stays valid, so
    /// a codec-level corruption must surface through the accessors.
    fn open_patched(bytes: &[u8], patch: impl FnMut(&mut Vec<u8>)) -> Option<SegmentReader> {
        let patched = rebuild_doc_keys(bytes, patch);
        SegmentReader::open(patched, SegmentLimits::default()).ok()
    }

    const SIZES: [usize; 5] = [1, 2, 1023, 1024, 1025];

    fn keys_for(count: usize) -> Vec<String> {
        (0..count).map(|index| format!("key-{index:05}")).collect()
    }

    // U01 — sizes around the threshold, first/middle/last selection.
    #[test]
    fn phase5_u01_sizes_and_boundaries() {
        for count in SIZES {
            let keys = keys_for(count);
            let bytes = build_segment(&keys);
            let reader = open(bytes);
            for index in [0usize, count / 2, count - 1] {
                let selected = reader.doc_key_selected(index as u64).unwrap();
                assert_eq!(selected.as_str(), expected_key(&keys, index));
                assert_eq!(selected, reader.doc_key(index as u64).unwrap());
            }
        }
    }

    // U02 — 200 seeded fixtures with varied key lengths around the 1024-byte edge.
    #[test]
    fn phase5_u02_seeded_fixtures_match_full_decode() {
        let mut state: u64 = 0x5EED_0F1F_0000_0005;
        let mut next = || {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            state >> 11
        };
        for seed in 0..200u64 {
            let count = 1 + (next() % 24) as usize;
            let mut keys = Vec::with_capacity(count);
            for index in 0..count {
                let len = match next() % 4 {
                    0 => 1,
                    1 => 1024,
                    _ => 1 + (next() % 32) as usize,
                };
                // Compose a key with a multi-byte character and pad to the desired
                // byte length, clamping to DocumentKey::MAX_BYTES (1024) bytes.
                let mut key = format!("s{seed}-{index}-ü");
                while key.len() < len {
                    key.push('x');
                }
                while key.len() > 1024 {
                    key.pop();
                }
                keys.push(key);
            }
            let bytes = build_segment(&keys);
            let reader = open(bytes);
            let full = reader.doc_keys().unwrap();
            assert_eq!(full.len(), count);
            for index in 0..count {
                let selected = reader.doc_key_selected(index as u64).unwrap();
                assert_eq!(selected.as_str(), keys[index], "seed {seed} doc {index}");
                assert_eq!(selected, full[index]);
            }
        }
    }

    // U03/U04 — corruption in an unselected record after/before the selected one.
    #[test]
    fn phase5_u03_u04_unselected_corruption_is_rejected() {
        let keys = keys_for(4);
        let bytes = build_segment(&keys);
        // Body layout: u16 version, u64 count, then per key: u16 len + bytes.
        let later_corrupt = open_patched(&bytes, |body| {
            // Corrupt the last key's last payload byte.
            let last = body.len() - 1;
            body[last] = 0xff;
        });
        let later_reached = later_corrupt.is_some();
        if let Some(reader) = later_corrupt {
            assert!(
                reader.doc_key_selected(0).is_err(),
                "early exit on later corruption"
            );
            assert!(reader.doc_key(0).is_err());
        }
        let earlier_corrupt = open_patched(&bytes, |body| {
            // Corrupt the first key's first payload byte (after the 10-byte header).
            body[10 + 2] = 0xff;
        });
        let earlier_reached = earlier_corrupt.is_some();
        if let Some(reader) = earlier_corrupt {
            assert!(
                reader.doc_key_selected(3).is_err(),
                "skipped earlier corruption"
            );
        }
        assert!(
            later_reached || earlier_reached,
            "container rebuild must reach the DOC_KEYS codec"
        );
    }

    // U05 — out-of-range ids fail typed and never install the cache.
    #[test]
    fn phase5_u05_out_of_range() {
        let keys = keys_for(3);
        let reader = open(build_segment(&keys));
        for doc_id in [3u64, 4, u64::MAX] {
            let error = reader.doc_key_selected(doc_id).unwrap_err();
            assert!(
                matches!(&error, SegmentError::Corrupt { context, .. } if *context == "doc keys"),
                "unexpected {error:?}"
            );
        }
        assert!(!reader.doc_keys_cache_is_populated());
    }

    // U06 — version and count mismatches stay typed errors.
    #[test]
    fn phase5_u06_version_and_count_mismatch() {
        let bytes = build_segment(&keys_for(3));
        // Bad version fails at segment validation (metadata) or at the codec.
        let bad_version = rebuild_doc_keys(&bytes, |body| body[0] = 9);
        let outcome = SegmentReader::open(bad_version, SegmentLimits::default());
        match outcome {
            Ok(reader) => assert!(reader.doc_key_selected(0).is_err()),
            Err(error) => assert!(matches!(
                error,
                SegmentError::Corrupt { .. } | SegmentError::UnsupportedFormatVersion { .. }
            )),
        }
        // Count mismatch: declare one more entry than the segment holds.
        let bad_count = rebuild_doc_keys(&bytes, |body| {
            body[2..10].copy_from_slice(&4u64.to_le_bytes());
        });
        let outcome = SegmentReader::open(bad_count, SegmentLimits::default());
        match outcome {
            Ok(reader) => assert!(reader.doc_key_selected(0).is_err()),
            Err(error) => assert!(matches!(error, SegmentError::Corrupt { .. })),
        }
    }

    // U07 — truncation and trailing bytes.
    #[test]
    fn phase5_u07_truncation_and_trailing() {
        let bytes = build_segment(&keys_for(3));
        let truncated = rebuild_doc_keys(&bytes, |body| {
            body.truncate(body.len() - 2);
        });
        let trailing = rebuild_doc_keys(&bytes, |body| body.push(0));
        for patched in [truncated, trailing] {
            if let Ok(reader) = SegmentReader::open(patched, SegmentLimits::default()) {
                assert!(reader.doc_key_selected(1).is_err());
            }
        }
    }

    // U08/U09 — invalid UTF-8, empty and oversized keys in selected and unselected slots.
    #[test]
    fn phase5_u08_u09_key_validity_parity() {
        let bytes = build_segment(&keys_for(3));
        let mut checks = 0;
        for index in 0..3usize {
            // Replace one key payload with invalid UTF-8 while keeping the framing.
            let mut offset = 10usize;
            for prior in 0..index {
                let len = u16::from_le_bytes([
                    bytes_doc_keys_byte(&bytes, offset),
                    bytes_doc_keys_byte(&bytes, offset + 1),
                ]) as usize;
                offset += 2 + len;
                let _ = prior;
            }
            let len = u16::from_le_bytes([
                bytes_doc_keys_byte(&bytes, offset),
                bytes_doc_keys_byte(&bytes, offset + 1),
            ]) as usize;
            let payload = offset + 2;
            // Invalid UTF-8 byte.
            let invalid = rebuild_doc_keys(&bytes, |body| body[payload] = 0xff);
            if let Ok(reader) = SegmentReader::open(invalid, SegmentLimits::default()) {
                let error = reader.doc_key_selected(index as u64).unwrap_err();
                assert!(
                    matches!(error, SegmentError::InvalidUtf8 { context } if context == "doc key")
                );
                assert!(reader.doc_key(index as u64).is_err());
                checks += 1;
            }
            // Empty key: shrink the length prefix to zero and drop the payload.
            let empty = rebuild_doc_keys(&bytes, |body| {
                body[offset..offset + 2].copy_from_slice(&0u16.to_le_bytes());
                body.drain(payload..payload + len);
            });
            if let Ok(reader) = SegmentReader::open(empty, SegmentLimits::default()) {
                let error = reader.doc_key_selected(index as u64).unwrap_err();
                assert!(
                    matches!(&error, SegmentError::Corrupt { context, .. } if *context == "doc key")
                );
                checks += 1;
            }
        }
        assert!(
            checks > 0,
            "at least one key-validity corruption must reach the codec"
        );
    }

    fn bytes_doc_keys_byte(bytes: &[u8], body_offset: usize) -> u8 {
        doc_keys_body(bytes)[body_offset]
    }

    // U10 — trailing payload after the last declared key is rejected even when the
    // selected key was already found.
    #[test]
    fn phase5_u10_trailing_bytes_after_selected() {
        let bytes = build_segment(&keys_for(2));
        let trailing = rebuild_doc_keys(&bytes, |body| body.push(0xAB));
        if let Ok(reader) = SegmentReader::open(trailing, SegmentLimits::default()) {
            assert!(reader.doc_key_selected(0).is_err());
        }
    }

    // U11/U12/U16 — cache ownership in both orders; exactly one owned key.
    #[test]
    fn phase5_u11_u12_u16_cache_ownership() {
        use super::super::reader::test_observation;

        // Cold selective: one owned key, cache stays empty.
        let keys = keys_for(4);
        let bytes = build_segment(&keys);
        let reader = open(bytes.clone());
        test_observation::reset();
        assert!(!reader.doc_keys_cache_is_populated());
        let selected = reader.doc_key_selected(2).unwrap();
        assert_eq!(selected.as_str(), keys[2]);
        assert_eq!(test_observation::selected_keys_owned(), 1);
        assert!(!reader.doc_keys_cache_is_populated());

        // Legacy accessor still decodes the full vector and caches it.
        let full = reader.doc_keys().unwrap();
        assert!(reader.doc_keys_cache_is_populated());
        assert_eq!(full.len(), 4);

        // Cached reader: selective accessor clones without a second decode.
        test_observation::reset();
        assert_eq!(reader.doc_key_selected(1).unwrap(), full[1]);
        assert_eq!(test_observation::selected_keys_owned(), 0);

        // Full-first order on a fresh reader.
        let reader = open(bytes);
        let full = reader.doc_keys().unwrap();
        assert_eq!(reader.doc_key_selected(3).unwrap(), full[3]);
        assert!(reader.doc_keys_cache_is_populated());
    }

    // U17 — duplicate logical keys do not remap physical identity.
    #[test]
    fn phase5_u17_duplicate_logical_keys_keep_physical_identity() {
        let keys = vec![
            "dup".to_owned(),
            "other".to_owned(),
            "dup".to_owned(),
            "dup".to_owned(),
        ];
        let reader = open(build_segment(&keys));
        for (index, key) in keys.iter().enumerate() {
            assert_eq!(reader.doc_key_selected(index as u64).unwrap().as_str(), key);
        }
    }
}

// ---------------------------------------------------------------------------
// PERF-06-A3: versioned split postings streams and block directory.
// ---------------------------------------------------------------------------

const A3_SPLIT_HEADER_BYTES: usize = 56;
const A3_SPLIT_BLOCK_DOCS: u32 = 128;
const A3_SPLIT_DIRECTORY_ENTRY_BYTES: usize = 40;
const A3_SPLIT_MARKER_DOC_ONLY: u8 = 2;
const A3_SPLIT_MARKER_POSITIONAL: u8 = 3;
const A3_SPLIT_CONTEXT: &str = "split postings";

fn a3_occurrence(index: u64) -> super::postings::Occurrence {
    super::postings::Occurrence {
        position: index,
        position_length: 1,
        value_index: 0,
        start_offset: index * 2,
        end_offset: index * 2 + 1,
    }
}

fn a3_posting(doc_id: u64, freq: u64, positional: bool) -> super::postings::Posting {
    super::postings::Posting {
        doc_id,
        freq,
        occurrences: if positional {
            (0..freq).map(a3_occurrence).collect()
        } else {
            Vec::new()
        },
    }
}

fn a3_postings(docs: &[u64], freqs: &[u64], positional: bool) -> Vec<super::postings::Posting> {
    docs.iter()
        .zip(freqs)
        .map(|(doc_id, freq)| a3_posting(*doc_id, *freq, positional))
        .collect()
}

fn a3_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().expect("u32 field"))
}

fn a3_u64(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().expect("u64 field"))
}

/// Wire-level split payload builder used only for malformed/geometry fixtures.
///
/// Valid payloads in these tests are produced by the real encoder; this type
/// exists so malformed cases are authored as explicit byte fields rather than
/// derived from encoder output.
struct A3RawSplit {
    marker: u8,
    payload_version: u8,
    flags: u16,
    block_docs: u32,
    block_count: u32,
    reserved: u32,
    posting_doc_count: u64,
    freq_total: u64,
    doc_stream_len: u64,
    freq_stream_len: u64,
    pos_stream_len: u64,
    docs: Vec<u8>,
    freqs: Vec<u8>,
    positions: Vec<u8>,
    directory: Vec<[u64; 5]>,
}

impl A3RawSplit {
    fn valid(docs: &[u64], freqs: &[u64], positional: bool) -> Self {
        assert_eq!(docs.len(), freqs.len(), "one frequency per document");
        let mut doc_stream = ByteWriter::new();
        let mut freq_stream = ByteWriter::new();
        let mut pos_stream = ByteWriter::new();
        let mut directory: Vec<[u64; 5]> = Vec::new();
        for (index, (doc, freq)) in docs.iter().zip(freqs).enumerate() {
            if index % A3_SPLIT_BLOCK_DOCS as usize == 0 {
                directory.push([
                    *doc,
                    index as u64,
                    doc_stream.len() as u64,
                    freq_stream.len() as u64,
                    pos_stream.len() as u64,
                ]);
                doc_stream.varint(*doc);
            } else {
                doc_stream.varint(doc - docs[index - 1]);
            }
            freq_stream.varint(*freq);
            if positional {
                for slot in 0..*freq {
                    pos_stream.varint(if slot == 0 { 0 } else { 1 });
                    pos_stream.varint(1);
                    pos_stream.varint(0);
                    pos_stream.varint(slot * 2);
                    pos_stream.varint(slot * 2 + 1);
                }
            }
        }
        Self {
            marker: if positional {
                A3_SPLIT_MARKER_POSITIONAL
            } else {
                A3_SPLIT_MARKER_DOC_ONLY
            },
            payload_version: 1,
            flags: 0,
            block_docs: A3_SPLIT_BLOCK_DOCS,
            block_count: directory.len() as u32,
            reserved: 0,
            posting_doc_count: docs.len() as u64,
            freq_total: freqs
                .iter()
                .fold(0u64, |acc, freq| acc.saturating_add(*freq)),
            doc_stream_len: doc_stream.len() as u64,
            freq_stream_len: freq_stream.len() as u64,
            pos_stream_len: pos_stream.len() as u64,
            docs: doc_stream.into_vec(),
            freqs: freq_stream.into_vec(),
            positions: pos_stream.into_vec(),
            directory,
        }
    }

    fn encode(&self) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.u8(self.marker);
        writer.u8(self.payload_version);
        writer.u16(self.flags);
        writer.u32(self.block_docs);
        writer.u32(self.block_count);
        writer.u32(self.reserved);
        writer.u64(self.posting_doc_count);
        writer.u64(self.freq_total);
        writer.u64(self.doc_stream_len);
        writer.u64(self.freq_stream_len);
        writer.u64(self.pos_stream_len);
        writer.bytes(&self.docs);
        writer.bytes(&self.freqs);
        writer.bytes(&self.positions);
        for entry in &self.directory {
            for value in entry {
                writer.u64(*value);
            }
        }
        writer.into_vec()
    }
}

/// Drive a split payload through the real full or doc/freq-only cursor.
fn a3_drive(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
    lean: bool,
) -> (Vec<(u64, u64)>, Option<SegmentError>) {
    use super::postings::PostingsReader;
    let mut reader = match PostingsReader::new_split(bytes, segment_doc_count, limits) {
        Ok(reader) => reader,
        Err(error) => return (Vec::new(), Some(error)),
    };
    let mut records = Vec::new();
    if lean {
        let mut lean = reader.into_doc_freq();
        loop {
            match lean.next() {
                Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
                Ok(None) => return (records, None),
                Err(error) => return (records, Some(error)),
            }
        }
    }
    loop {
        match reader.next() {
            Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
            Ok(None) => return (records, None),
            Err(error) => return (records, Some(error)),
        }
    }
}

fn a3_assert_corrupt(error: &SegmentError, detail: &str) {
    a3_assert_corrupt_with(error, A3_SPLIT_CONTEXT, detail);
}

/// Split-semantic corruptions shared with the legacy decoder keep the
/// historical `"postings"` context; only new structural failures use
/// `"split postings"`.
fn a3_assert_corrupt_with(error: &SegmentError, context: &str, detail: &str) {
    match error {
        SegmentError::Corrupt {
            context: actual_context,
            detail: actual_detail,
        } => {
            assert_eq!(*actual_context, context, "corruption context");
            assert_eq!(actual_detail, detail, "corruption detail");
        }
        other => panic!("expected {context} Corrupt, got {other:?}"),
    }
}

/// Build a small real text segment from `(key, title)` pairs.
fn a3_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .expect("schema")
}

fn a5_build_current_segment(titles: &[(&str, &str)]) -> Vec<u8> {
    use super::build::{Layout, SegmentBuilder};
    use super::model::SegmentDocument;
    let mut builder =
        SegmentBuilder::new(a3_schema(), crate::analysis::AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
    for (key, title) in titles {
        let mut document = SegmentDocument::new(DocumentKey::new(*key).expect("key"));
        document.fields.insert(
            "title".to_owned(),
            FieldValues::Single(FieldValue::Text((*title).to_owned())),
        );
        builder.add_document(document).expect("add document");
    }
    builder.build().expect("build").bytes
}

/// Re-encode every term of an existing valid segment with the retained A3 split
/// encoder, rebuilding Dictionary offsets/lengths and replacing the adaptive
/// postings feature with the split feature.
///
/// This keeps A3-specific byte/error assertions running against explicitly
/// constructed A3 payloads now that the ordinary builder emits the adaptive
/// family. Every other section body, flag, aux value and optional feature is
/// preserved. `ContainerBuilder::new` supplies one baseline tuple, so exactly
/// one matching tuple from the source feature list is skipped to keep the
/// feature multiplicity (and therefore byte accounting) honest.
fn a3_reconstruct_current(original: &[u8]) -> Vec<u8> {
    use super::dictionary::encode_dictionary;
    use super::format::{
        ByteWriter, FEATURE_ADAPTIVE_POSTINGS, FEATURE_BASELINE, FEATURE_SPLIT_POSTINGS,
    };
    use super::postings::encode_split_postings_block;

    let limits = SegmentLimits::default();
    let view = parse_container(original, &limits).expect("container");
    let reader = super::reader::SegmentReader::open(original.to_vec(), limits).expect("open");
    let doc_count = view.doc_count();

    let mut postings_body = ByteWriter::new();
    let mut fields: Vec<(u32, Vec<super::dictionary::DictionaryEntry>)> = Vec::new();
    if let Some(dictionary) = reader.dictionary() {
        for (field_id, entries) in dictionary.fields() {
            let mut rebuilt: Vec<super::dictionary::DictionaryEntry> = Vec::new();
            for entry in entries {
                let mut cursor = reader.postings_for_entry(entry).expect("postings");
                let mut postings = Vec::new();
                while let Some(posting) = cursor.next().expect("posting") {
                    postings.push(posting);
                }
                let offset = postings_body.len() as u64;
                let block = encode_split_postings_block(doc_count, &postings, &limits)
                    .expect("split encode");
                let length = block.len() as u64;
                postings_body.bytes(&block);
                rebuilt.push(super::dictionary::DictionaryEntry {
                    term: entry.term.clone(),
                    doc_freq: postings.len() as u64,
                    postings_offset: offset,
                    postings_length: length,
                });
            }
            fields.push((*field_id, rebuilt));
        }
    }
    let postings_bytes = postings_body.into_vec();

    let mut builder = ContainerBuilder::new(view.kind(), doc_count);
    let mut baseline_skipped = false;
    for (feature, version) in view.required_features() {
        if (*feature, *version) == (FEATURE_BASELINE, 1) && !baseline_skipped {
            baseline_skipped = true;
            continue;
        }
        if (*feature, *version) == (FEATURE_ADAPTIVE_POSTINGS, 1) {
            builder.require_feature(FEATURE_SPLIT_POSTINGS, 1);
            continue;
        }
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        let body = match section.kind {
            SectionKind::Dictionary if !fields.is_empty() => {
                encode_dictionary(&fields, &limits).expect("dictionary")
            }
            SectionKind::Postings if !fields.is_empty() => postings_bytes.clone(),
            _ => {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            }
        };
        builder.section(section.kind, section.flags, section.aux, body);
    }
    builder.build().expect("rebuilt A3 container")
}

/// Build a small real text segment, then re-encode its postings as explicit A3
/// split payloads for historical A3 assertions.
fn a3_build_segment(titles: &[(&str, &str)]) -> Vec<u8> {
    a3_reconstruct_current(&a5_build_current_segment(titles))
}

/// Rebuild a container with recomputed section digests, changing only the
/// requested features/sections. Used to prove that failures are not merely a
/// whole-container checksum mismatch.
struct A3Rebuild {
    add_features: Vec<(u16, u16)>,
    drop_features: Vec<(u16, u16)>,
    drop_sections: Vec<SectionKind>,
    replace_section: Option<(SectionKind, Vec<u8>)>,
}

impl A3Rebuild {
    fn new() -> Self {
        Self {
            add_features: Vec::new(),
            drop_features: Vec::new(),
            drop_sections: Vec::new(),
            replace_section: None,
        }
    }
}

fn a3_rebuild(original: &[u8], spec: &A3Rebuild) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(original, &limits).expect("container");
    let mut builder = ContainerBuilder::new(view.kind(), view.doc_count());
    let mut retained: Vec<(u16, u16)> = Vec::new();
    for (feature, version) in view.required_features() {
        if spec.drop_features.contains(&(*feature, *version)) {
            continue;
        }
        retained.push((*feature, *version));
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in &spec.add_features {
        if !retained.contains(&(*feature, *version)) {
            builder.require_feature(*feature, *version);
        }
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        if spec.drop_sections.contains(&section.kind) {
            continue;
        }
        let body = match &spec.replace_section {
            Some((kind, body)) if *kind == section.kind => body.clone(),
            _ => {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            }
        };
        builder.section(section.kind, section.flags, section.aux, body);
    }
    builder.build().expect("rebuilt container")
}

fn a3_postings_body(bytes: &[u8]) -> Vec<u8> {
    let view = parse_container(bytes, &SegmentLimits::default()).expect("container");
    view.body(SectionKind::Postings)
        .expect("postings body")
        .to_vec()
}

#[test]
fn a3_u01_feature_and_empty_segment_contract() {
    use super::build::{Layout, SegmentBuilder};
    use super::format::{FEATURE_POSITIONAL, FEATURE_SPLIT_POSTINGS, FEATURE_STORED_BLOCKS};
    use super::model::SegmentDocument;

    // Exactly the next free feature id, version 1, and supported.
    assert_eq!(FEATURE_SPLIT_POSTINGS, 0x000E);
    assert!(
        super::format::SUPPORTED_FEATURES.contains(&(FEATURE_SPLIT_POSTINGS, 1)),
        "split postings feature must be supported"
    );
    // Existing ids and section kinds must not be renumbered.
    assert_eq!(FEATURE_STORED_BLOCKS, 0x000D);
    assert_eq!(SectionKind::Postings as u16, 0x0003);
    assert_eq!(SectionKind::Dictionary as u16, 0x0002);

    // Non-empty lexical segment: required feature + split markers.
    let bytes = a3_build_segment(&[("a", "alpha beta"), ("b", "alpha")]);
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).expect("container");
    let required = view.required_features();
    assert!(required.contains(&(FEATURE_SPLIT_POSTINGS, 1)));
    assert!(required.contains(&(FEATURE_POSITIONAL, 1)));
    let postings_body = view.body(SectionKind::Postings).expect("postings body");
    let reader = super::reader::SegmentReader::open(bytes.clone(), limits).expect("open");
    let title = reader.schema().field_id("title").expect("title field");
    let mut terms = 0usize;
    for entry in reader
        .dictionary()
        .expect("dictionary")
        .field(title)
        .expect("field terms")
    {
        terms += 1;
        let start = entry.postings_offset as usize;
        let marker = postings_body[start];
        assert!(
            marker == A3_SPLIT_MARKER_DOC_ONLY || marker == A3_SPLIT_MARKER_POSITIONAL,
            "term {:?} must use a split marker, saw {marker}",
            entry.term
        );
        assert_eq!(a3_u64(postings_body, start + 16), entry.doc_freq);
    }
    assert!(terms > 0, "expected indexed terms");

    // No lexical postings: neither the feature nor the section pair appears.
    let mut builder =
        SegmentBuilder::new(a3_schema(), crate::analysis::AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
    let document = SegmentDocument::new(DocumentKey::new("empty").expect("key"));
    builder.add_document(document).expect("add document");
    let empty = builder.build().expect("build").bytes;
    let view = parse_container(&empty, &limits).expect("container");
    let required = view.required_features();
    assert!(!required.contains(&(FEATURE_SPLIT_POSTINGS, 1)));
    assert!(!required.contains(&(FEATURE_POSITIONAL, 1)));
    assert!(view.body(SectionKind::Dictionary).is_none());
    assert!(view.body(SectionKind::Postings).is_none());

    // A declared split feature without the section pair fails closed.
    let mut spec = A3Rebuild::new();
    spec.drop_features.push((FEATURE_SPLIT_POSTINGS, 1));
    let legacy_marked = a3_rebuild(&bytes, &spec);
    let reader =
        super::reader::SegmentReader::open(legacy_marked, limits).expect("feature removed opens");
    assert!(matches!(
        reader.postings(title, "alpha"),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));

    let mut spec = A3Rebuild::new();
    spec.add_features.push((FEATURE_SPLIT_POSTINGS, 1));
    let empty_with_feature = a3_rebuild(&empty, &spec);
    match super::reader::SegmentReader::open(empty_with_feature, limits) {
        Err(error) => a3_assert_corrupt(
            &error,
            "split postings feature requires dictionary and postings",
        ),
        Ok(_) => panic!("feature without dictionary/postings must be rejected"),
    }
}

#[test]
fn a3_u02_exact_split_header_one_posting_bytes() {
    use super::postings::{PostingsReader, encode_split_postings_block};

    let limits = SegmentLimits::default();
    let doc_only = encode_split_postings_block(
        2,
        &[super::postings::Posting {
            doc_id: 0,
            freq: 1,
            occurrences: Vec::new(),
        }],
        &limits,
    )
    .expect("encode doc-only");

    // 56-byte header + 1 doc byte + 1 frequency byte + 0 positions + 40-byte entry.
    assert_eq!(doc_only.len(), 98);
    assert_eq!(doc_only[0], A3_SPLIT_MARKER_DOC_ONLY);
    assert_eq!(doc_only[1], 1, "payload version");
    assert_eq!(u16::from_le_bytes([doc_only[2], doc_only[3]]), 0, "flags");
    assert_eq!(a3_u32(&doc_only, 4), A3_SPLIT_BLOCK_DOCS);
    assert_eq!(a3_u32(&doc_only, 8), 1, "block count");
    assert_eq!(a3_u32(&doc_only, 12), 0, "reserved");
    assert_eq!(a3_u64(&doc_only, 16), 1, "posting doc count");
    assert_eq!(a3_u64(&doc_only, 24), 1, "frequency total");
    assert_eq!(a3_u64(&doc_only, 32), 1, "doc stream length");
    assert_eq!(a3_u64(&doc_only, 40), 1, "frequency stream length");
    assert_eq!(a3_u64(&doc_only, 48), 0, "position stream length");
    assert_eq!(&doc_only[56..58], &[0u8, 1u8], "doc id 0, frequency 1");
    assert_eq!(
        &doc_only[58..98],
        &[0u8; 40],
        "single zeroed directory entry"
    );

    let mut reader = PostingsReader::new_split(&doc_only, 2, &limits).expect("split header");
    assert!(!reader.is_positional());
    assert_eq!(reader.posting_doc_count(), 1);
    assert_eq!(reader.freq_total(), 1);
    let posting = reader.next().expect("decode").expect("one posting");
    assert_eq!(posting.doc_id, 0);
    assert_eq!(posting.freq, 1);
    assert!(posting.occurrences.is_empty());
    assert!(reader.next().expect("eof").is_none());

    let occurrence = super::postings::Occurrence {
        position: 0,
        position_length: 1,
        value_index: 0,
        start_offset: 0,
        end_offset: 1,
    };
    let positional = encode_split_postings_block(
        2,
        &[super::postings::Posting {
            doc_id: 0,
            freq: 1,
            occurrences: vec![occurrence],
        }],
        &limits,
    )
    .expect("encode positional");
    assert_eq!(positional.len(), 103);
    assert_eq!(positional[0], A3_SPLIT_MARKER_POSITIONAL);
    assert_eq!(a3_u64(&positional, 48), 5, "position stream length");
    assert_eq!(
        &positional[56..63],
        &[0u8, 1u8, 0, 1, 0, 0, 1],
        "doc 0, frequency 1, one five-varint occurrence"
    );
    assert_eq!(&positional[63..103], &[0u8; 40]);

    let mut reader = PostingsReader::new_split(&positional, 2, &limits).expect("split header");
    assert!(reader.is_positional());
    let posting = reader.next().expect("decode").expect("one posting");
    assert_eq!(posting.occurrences, vec![occurrence]);
    assert!(reader.next().expect("eof").is_none());
}

#[test]
fn a3_u05_split_directory_geometry_errors() {
    let limits = SegmentLimits::default();
    let docs = [0u64, 3];
    let freqs = [1u64, 1];

    // Sanity: the raw builder's valid payload decodes.
    let valid = A3RawSplit::valid(&docs, &freqs, false).encode();
    let (records, error) = a3_drive(&valid, 4, &limits, false);
    assert!(error.is_none());
    assert_eq!(records, vec![(0, 1), (3, 1)]);

    let assert_rejected = |raw: &A3RawSplit, segment_doc_count: u64, expected: &str| {
        let bytes = raw.encode();
        let (_, full_error) = a3_drive(&bytes, segment_doc_count, &limits, false);
        let (_, lean_error) = a3_drive(&bytes, segment_doc_count, &limits, true);
        let full_error = full_error.expect("full reader must reject malformed directory");
        let lean_error = lean_error.expect("lean reader must reject malformed directory");
        assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
        a3_assert_corrupt(&full_error, expected);
    };

    // block_count off by one versus ceil(posting_doc_count / 128).
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.block_count = 2;
    assert_rejected(&raw, 4, "block count mismatch");

    // Fixed block size is part of the format.
    for block_docs in [0u32, 127, 129] {
        let mut raw = A3RawSplit::valid(&docs, &freqs, false);
        raw.block_docs = block_docs;
        assert_rejected(&raw, 4, "invalid block_docs");
    }

    // Directory must describe exactly the declared posting count.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.posting_doc_count = A3_SPLIT_BLOCK_DOCS as u64 + 1;
    assert_rejected(&raw, 200, "block count mismatch");

    // Entry 0 must be canonical.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[0][1] = 1;
    assert_rejected(&raw, 4, "block ordinal mismatch");
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[0][2] = 1;
    assert_rejected(&raw, 4, "block doc offset not canonical");
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[0][3] = 1;
    assert_rejected(&raw, 4, "block frequency offset not canonical");
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[0][4] = 1;
    assert_rejected(&raw, 4, "block position offset not canonical");

    // Two-block payloads: forged ordinals/offsets/first docs.
    let count = A3_SPLIT_BLOCK_DOCS as usize + 1;
    let block_docs: Vec<u64> = (0..count as u64).collect();
    let block_freqs: Vec<u64> = vec![1; count];

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][1] = 127;
    assert_rejected(&raw, count as u64, "block ordinal mismatch");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][0] = raw.directory[0][0];
    assert_rejected(&raw, count as u64, "block first doc id not ascending");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][0] = u64::from(u32::MAX);
    assert_rejected(&raw, count as u64, "block first doc id out of range");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][2] = raw.directory[0][2];
    assert_rejected(&raw, count as u64, "block doc offset not ascending");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][2] = raw.doc_stream_len;
    assert_rejected(&raw, count as u64, "block doc offset out of range");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][3] = raw.directory[0][3];
    assert_rejected(&raw, count as u64, "block frequency offset not ascending");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][3] = raw.freq_stream_len;
    assert_rejected(&raw, count as u64, "block frequency offset out of range");

    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, true);
    raw.directory[1][4] = raw.positions.len() as u64;
    let bytes = raw.encode();
    let (_, error) = a3_drive(&bytes, count as u64, &limits, false);
    a3_assert_corrupt(
        &error.expect("position offset"),
        "block position offset out of range",
    );

    // Positional block offsets must strictly ascend.
    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, true);
    raw.directory[1][4] = raw.directory[0][4];
    assert_rejected(&raw, count as u64, "block position offset not ascending");

    // A doc-only payload cannot carry a non-zero position offset on any entry.
    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][4] = 1;
    assert_rejected(&raw, count as u64, "block position offset not canonical");

    // Doc-only payloads carry no positional stream/offsets.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.pos_stream_len = 1;
    raw.positions.push(0);
    assert_rejected(&raw, 4, "position stream present for doc-only payload");

    // Forged/truncated declared stream lengths.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.doc_stream_len = u64::MAX;
    assert_rejected(&raw, 4, "length overflow");

    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.doc_stream_len = 0;
    assert_rejected(&raw, 4, "doc stream too short");

    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.freq_stream_len = 0;
    assert_rejected(&raw, 4, "frequency stream too short");

    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.doc_stream_len += 1;
    assert_rejected(&raw, 4, "extent length mismatch");

    // Trailing byte after the directory.
    let mut trailing = valid.clone();
    trailing.push(0);
    let (_, error) = a3_drive(&trailing, 4, &limits, false);
    a3_assert_corrupt(&error.expect("trailing byte"), "extent length mismatch");

    // An in-range but wrong offset passes the bounded-geometry constructor and
    // is rejected at the block boundary, before that block's first posting.
    let mut raw = A3RawSplit::valid(&block_docs, &block_freqs, false);
    raw.directory[1][2] = 1;
    assert_rejected(&raw, count as u64, "block doc offset mismatch");

    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.posting_doc_count = 1 << 40;
    raw.block_count = 1 << 20;
    let bytes = raw.encode();
    for lean in [false, true] {
        let (records, error) = a3_drive(&bytes, u64::MAX, &limits, lean);
        assert!(records.is_empty());
        match error.expect("forged posting count must be rejected") {
            SegmentError::LimitExceeded { limit, requested } => {
                assert_eq!(limit, limits.max_postings_per_term());
                assert_eq!(requested, 1 << 40);
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }
}

#[test]
fn a3_u03_block_boundaries_and_monotone_docs() {
    use super::postings::{PostingsReader, encode_split_postings_block};
    let limits = SegmentLimits::default();

    for (count, expected_blocks) in [
        (1usize, 1u32),
        (127, 1),
        (128, 1),
        (129, 2),
        (256, 2),
        (257, 3),
    ] {
        let docs: Vec<u64> = (0..count as u64).collect();
        let freqs = vec![1u64; count];
        let positional = a3_postings(&docs, &freqs, true);
        let bytes = encode_split_postings_block(count as u64, &positional, &limits)
            .unwrap_or_else(|error| panic!("encode {count}: {error:?}"));
        assert_eq!(a3_u32(&bytes, 4), A3_SPLIT_BLOCK_DOCS);
        assert_eq!(a3_u32(&bytes, 8), expected_blocks, "block count {count}");
        assert_eq!(a3_u64(&bytes, 16), count as u64);
        assert_eq!(a3_u64(&bytes, 24), count as u64, "frequency total");

        let doc_len = a3_u64(&bytes, 32);
        let freq_len = a3_u64(&bytes, 40);
        let pos_len = a3_u64(&bytes, 48);
        assert_eq!(freq_len, count as u64);
        assert_eq!(pos_len, count as u64 * 5);
        // Absolute doc id at every block start is a reset, not a delta chain.
        let expected_doc_len = if count <= 128 {
            count as u64
        } else if count <= 256 {
            count as u64 + 1
        } else {
            count as u64 + 2
        };
        assert_eq!(doc_len, expected_doc_len);

        let directory =
            A3_SPLIT_HEADER_BYTES + doc_len as usize + freq_len as usize + pos_len as usize;
        assert_eq!(bytes.len(), directory + expected_blocks as usize * 40);
        let mut expected_doc_offset = 0u64;
        for block in 0..expected_blocks as usize {
            let entry = directory + block * A3_SPLIT_DIRECTORY_ENTRY_BYTES;
            let ordinal = block as u64 * 128;
            assert_eq!(a3_u64(&bytes, entry), ordinal, "entry {block} first doc id");
            assert_eq!(a3_u64(&bytes, entry + 8), ordinal, "entry {block} ordinal");
            assert_eq!(
                a3_u64(&bytes, entry + 16),
                expected_doc_offset,
                "entry {block} doc offset"
            );
            assert_eq!(
                a3_u64(&bytes, entry + 24),
                ordinal,
                "entry {block} freq offset"
            );
            assert_eq!(
                a3_u64(&bytes, entry + 32),
                ordinal * 5,
                "entry {block} pos offset"
            );
            // Advance the model doc offset by this block's encoded width.
            let block_len = if block + 1 == expected_blocks as usize {
                doc_len - expected_doc_offset
            } else {
                let posts_in_block = 128u64;
                let first_width = if block == 0 { 1 } else { 2 };
                first_width + posts_in_block - 1
            };
            expected_doc_offset += block_len;
        }

        // Full and lean cursors return the exact ordered doc/freq sequence.
        let (full_records, full_error) = a3_drive(&bytes, count as u64, &limits, false);
        assert!(full_error.is_none(), "full {count}: {full_error:?}");
        let (lean_records, lean_error) = a3_drive(&bytes, count as u64, &limits, true);
        assert!(lean_error.is_none(), "lean {count}: {lean_error:?}");
        let expected: Vec<(u64, u64)> = docs.iter().map(|doc| (*doc, 1)).collect();
        assert_eq!(full_records, expected);
        assert_eq!(lean_records, expected);

        // Full mode reports every occurrence; lean returns first-class values.
        let mut full = PostingsReader::new_split(&bytes, count as u64, &limits).unwrap();
        let first = full.next().unwrap().unwrap();
        assert_eq!(first.occurrences, vec![a3_occurrence(0)]);
    }

    // 128 -> 129 must write an absolute 128 at the second block start.
    let docs: Vec<u64> = (0..129).collect();
    let freqs = vec![1u64; 129];
    let bytes =
        encode_split_postings_block(129, &a3_postings(&docs, &freqs, false), &limits).unwrap();
    let doc_len = a3_u64(&bytes, 32) as usize;
    assert_eq!(doc_len, 130);
    assert_eq!(
        &bytes[56 + 128..56 + 130],
        &[0x80u8, 0x01],
        "absolute 128 varint"
    );

    // Rejections: duplicate inside a block and a decreasing block start.
    let mut duplicate = docs.clone();
    duplicate[5] = duplicate[4];
    let raw = A3RawSplit::valid(&duplicate, &freqs, false).encode();
    let (records, error) = a3_drive(&raw, 129, &limits, false);
    assert_eq!(records.len(), 5);
    assert!(matches!(
        error,
        Some(SegmentError::NonMonotoneDocId {
            previous: 4,
            next: 4
        })
    ));

    let mut regressed = docs.clone();
    regressed[128] = regressed[127];
    let raw = A3RawSplit::valid(&regressed, &freqs, false).encode();
    let (records, error) = a3_drive(&raw, 129, &limits, false);
    assert_eq!(records.len(), 128);
    assert!(matches!(
        error,
        Some(SegmentError::NonMonotoneDocId {
            previous: 127,
            next: 127
        })
    ));
    let (lean_records, lean_error) = a3_drive(&raw, 129, &limits, true);
    assert_eq!(lean_records.len(), 128);
    assert_eq!(
        format!("{error:?}"),
        format!("{lean_error:?}"),
        "both modes must reject the same 128->129 regression"
    );
}

#[test]
fn a3_u04_full_lean_and_advance_parity() {
    use super::postings::{PostingsReader, decode_observation, encode_split_postings_block};
    let limits = SegmentLimits::default();

    // Hand-authored three-posting positional payload.
    let docs = [1u64, 4, 7];
    let freqs = [2u64, 1, 3];
    let postings = a3_postings(&docs, &freqs, true);
    let bytes = encode_split_postings_block(8, &postings, &limits).expect("encode positional");

    decode_observation::reset();
    let mut full = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    assert!(full.is_positional());
    for (index, posting) in postings.iter().enumerate() {
        let decoded = full.next().expect("decode").expect("posting");
        assert_eq!(decoded.doc_id, posting.doc_id);
        assert_eq!(decoded.freq, posting.freq);
        assert_eq!(
            decoded.occurrences, posting.occurrences,
            "posting {index} occurrences"
        );
        for (slot, occurrence) in decoded.occurrences.iter().enumerate() {
            assert_eq!(occurrence.position, slot as u64);
            assert_eq!(occurrence.position_length, 1);
            assert_eq!(occurrence.value_index, 0);
            assert_eq!(occurrence.start_offset, slot as u64 * 2);
            assert_eq!(occurrence.end_offset, slot as u64 * 2 + 1);
        }
    }
    assert!(full.next().expect("eof").is_none());
    let (full_reserves, full_clones) = decode_observation::counts();
    assert!(full_reserves > 0, "full mode reserves positional vectors");
    assert!(full_clones > 0, "full mode clones the cached posting");

    decode_observation::reset();
    let mut lean = PostingsReader::new_split(&bytes, 8, &limits)
        .expect("header")
        .into_doc_freq();
    let mut seen = Vec::new();
    while let Some(posting) = lean.next().expect("decode") {
        seen.push((posting.doc_id, posting.freq));
    }
    assert_eq!(seen, vec![(1, 2), (4, 1), (7, 3)]);
    assert!(lean.next().expect("eof").is_none());
    assert_eq!(
        decode_observation::counts(),
        (0, 0),
        "lean mode never reserves positions or clones postings"
    );

    // advance()/advance_with() keep the original sequential, cached-current walk.
    let mut cursor = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    let first = cursor.next().expect("decode").expect("posting");
    assert_eq!(cursor.advance(1).expect("advance").expect("cached"), first);
    assert_eq!(cursor.advance(0).expect("advance").expect("cached"), first);
    let second = cursor.advance(4).expect("advance").expect("posting");
    assert_eq!((second.doc_id, second.freq), (4, 1));
    let flag = crate::analysis::CancellationFlag::new();
    assert_eq!(
        cursor
            .advance_with(4, &flag)
            .expect("advance")
            .expect("cached"),
        second
    );
    let third = cursor
        .advance_with(7, &flag)
        .expect("advance")
        .expect("posting");
    assert_eq!((third.doc_id, third.freq), (7, 3));
    assert_eq!(third.occurrences[2].position, 2);
    assert!(cursor.advance(99).expect("advance").is_none());
    assert!(cursor.next().expect("eof").is_none());

    // Conversion after a full read continues at the next unread posting.
    decode_observation::reset();
    let mut cursor = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    assert_eq!(cursor.next().expect("decode").expect("posting").doc_id, 1);
    let after_full_read = decode_observation::counts();
    assert!(after_full_read.0 > 0 && after_full_read.1 > 0);
    let mut lean = cursor.into_doc_freq();
    let mut rest = Vec::new();
    while let Some(posting) = lean.next().expect("decode") {
        rest.push((posting.doc_id, posting.freq));
    }
    assert_eq!(rest, vec![(4, 1), (7, 3)]);
    assert_eq!(
        decode_observation::counts(),
        after_full_read,
        "no reserve or clone may happen after conversion"
    );

    // Doc-only payloads carry empty occurrence vectors in full mode.
    let doc_only = encode_split_postings_block(8, &a3_postings(&[2, 5], &[1, 2], false), &limits)
        .expect("encode doc-only");
    let mut full = PostingsReader::new_split(&doc_only, 8, &limits).expect("header");
    assert!(!full.is_positional());
    assert!(
        full.next()
            .expect("decode")
            .expect("posting")
            .occurrences
            .is_empty()
    );
}

#[test]
fn a3_u06_split_header_and_positional_corruption() {
    use super::postings::PostingsReader;
    let limits = SegmentLimits::default();

    let assert_parity = |raw: &A3RawSplit, segment_doc_count: u64| -> SegmentError {
        let bytes = raw.encode();
        let (full_records, full_error) = a3_drive(&bytes, segment_doc_count, &limits, false);
        let (lean_records, lean_error) = a3_drive(&bytes, segment_doc_count, &limits, true);
        assert_eq!(full_records, lean_records);
        let full_error = full_error.expect("full reader must reject");
        let lean_error = lean_error.expect("lean reader must reject");
        assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
        full_error
    };

    // Markers: legacy 0/1 and unknown 9 are invalid under the new constructor.
    for marker in [0u8, 1, 9] {
        let mut raw = A3RawSplit::valid(&[0], &[1], false);
        raw.marker = marker;
        a3_assert_corrupt(&assert_parity(&raw, 1), "invalid occurrence marker");
        let bytes = raw.encode();
        assert!(PostingsReader::new_split(&bytes, 1, &limits).is_err());
    }

    for payload_version in [0u8, 2] {
        let mut raw = A3RawSplit::valid(&[0], &[1], false);
        raw.payload_version = payload_version;
        a3_assert_corrupt(&assert_parity(&raw, 1), "unsupported payload version");
    }

    let mut raw = A3RawSplit::valid(&[0], &[1], false);
    raw.flags = 1;
    match assert_parity(&raw, 1) {
        SegmentError::UnknownFlags { context, flags } => {
            assert_eq!(context, A3_SPLIT_CONTEXT);
            assert_eq!(flags, 1);
        }
        other => panic!("unexpected error: {other:?}"),
    }

    let mut raw = A3RawSplit::valid(&[0], &[1], false);
    raw.reserved = 7;
    a3_assert_corrupt(&assert_parity(&raw, 1), "reserved field nonzero");

    // Noncanonical doc-stream varint (overlong zero).
    let mut raw = A3RawSplit::valid(&[0], &[1], false);
    raw.docs = vec![0x80, 0x00];
    raw.doc_stream_len = 2;
    match assert_parity(&raw, 1) {
        SegmentError::InvalidVarint { context } => assert_eq!(context, "doc id delta"),
        other => panic!("unexpected error: {other:?}"),
    }

    let positional_with = |positions: Vec<u8>, freq: u64| {
        let mut raw = A3RawSplit::valid(&[0], &[freq], true);
        raw.pos_stream_len = positions.len() as u64;
        raw.positions = positions;
        raw
    };

    // Truncated fifth component of the final occurrence.
    let raw = positional_with(vec![0, 1, 0, 0, 0x80], 1);
    match assert_parity(&raw, 1) {
        SegmentError::Truncated { context, .. } => assert_eq!(context, "end offset"),
        other => panic!("unexpected error: {other:?}"),
    }

    a3_assert_corrupt_with(
        &assert_parity(&positional_with(vec![0, 0, 0, 0, 1], 1), 1),
        "postings",
        "zero position length",
    );
    a3_assert_corrupt_with(
        &assert_parity(&positional_with(vec![0, 1, 1, 0, 1, 1, 1, 0, 0, 1], 2), 1),
        "postings",
        "value index decreased",
    );
    a3_assert_corrupt_with(
        &assert_parity(&positional_with(vec![0, 1, 0, 2, 1], 1), 1),
        "postings",
        "start offset exceeds end offset",
    );
    // A duplicate absolute position inside one posting is non-monotone.
    let mut duplicate = A3RawSplit::valid(&[0], &[2], true);
    let mut positions = Vec::new();
    let mut writer = ByteWriter::new();
    for _ in 0..2 {
        writer.varint(0); // first absolute 7, then a zero delta
        writer.varint(1);
        writer.varint(0);
        writer.varint(0);
        writer.varint(1);
    }
    positions.extend_from_slice(writer.as_slice());
    duplicate.positions = positions;
    duplicate.pos_stream_len = duplicate.positions.len() as u64;
    match assert_parity(&duplicate, 1) {
        SegmentError::NonMonotonePosition { doc_id } => assert_eq!(doc_id, 0),
        other => panic!("unexpected error: {other:?}"),
    }

    // Position addition overflow: u64::MAX then +1.
    let mut overflow = ByteWriter::new();
    overflow.varint(u64::MAX);
    overflow.varint(1);
    overflow.varint(0);
    overflow.varint(0);
    overflow.varint(1);
    overflow.varint(1);
    overflow.varint(1);
    overflow.varint(0);
    overflow.varint(0);
    overflow.varint(1);
    let mut raw = A3RawSplit::valid(&[0], &[2], true);
    raw.pos_stream_len = overflow.len() as u64;
    raw.positions = overflow.into_vec();
    a3_assert_corrupt_with(&assert_parity(&raw, 1), "postings", "position overflow");

    // Corruption on the second posting is surfaced only when it is consumed.
    let mut raw = A3RawSplit::valid(&[0, 5], &[1, 1], true);
    // Second posting begins after the first posting's five position bytes.
    raw.positions[6] = 0; // second posting's position-length field
    let bytes = raw.encode();
    for lean in [false, true] {
        let (records, error) = a3_drive(&bytes, 8, &limits, lean);
        assert_eq!(records, vec![(0, 1)]);
        a3_assert_corrupt_with(
            &error.expect("second posting must fail"),
            "postings",
            "zero position length",
        );
    }
}

#[test]
fn a3_u07_directory_offset_and_first_doc_must_match_streams() {
    use super::postings::PostingsReader;
    let limits = SegmentLimits::default();
    let count = A3_SPLIT_BLOCK_DOCS as usize + 1;
    let docs: Vec<u64> = (0..count as u64).collect();
    let freqs = vec![1u64; count];

    // Forged in-range first doc id for block 1: accepted by the bounded-geometry
    // constructor, rejected at the block boundary.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[1][0] = 100;
    let bytes = raw.encode();
    let mut reader = PostingsReader::new_split(&bytes, count as u64, &limits).expect("header");
    for expected in 0..128u64 {
        assert_eq!(
            reader.next().expect("decode").expect("posting").doc_id,
            expected
        );
    }
    a3_assert_corrupt(
        &reader.next().expect_err("block 1 mismatch"),
        "block first doc id mismatch",
    );

    // advance(target_in_block_2) must traverse (and reject) block 1 first.
    let mut reader = PostingsReader::new_split(&bytes, count as u64, &limits).expect("header");
    match reader.advance(129) {
        Err(error) => a3_assert_corrupt(&error, "block first doc id mismatch"),
        Ok(_) => panic!("advance must not skip the inconsistent block"),
    }

    // Forged in-range but misaligned doc-stream offset for block 1.
    let mut raw = A3RawSplit::valid(&docs, &freqs, false);
    raw.directory[1][2] = 127;
    let bytes = raw.encode();
    let mut reader = PostingsReader::new_split(&bytes, count as u64, &limits).expect("header");
    for _ in 0..128 {
        reader.next().expect("decode").expect("posting");
    }
    a3_assert_corrupt(
        &reader.next().expect_err("offset mismatch"),
        "block doc offset mismatch",
    );

    // A malformed earlier positional record cannot be skipped by advance().
    let mut raw = A3RawSplit::valid(&docs, &freqs, true);
    raw.positions[0] = 0;
    raw.positions[1] = 0; // zero position length in the very first posting
    let bytes = raw.encode();
    let mut reader = PostingsReader::new_split(&bytes, count as u64, &limits).expect("header");
    match reader.advance(200) {
        Err(error) => a3_assert_corrupt_with(&error, "postings", "zero position length"),
        Ok(_) => panic!("advance must not skip a malformed earlier posting"),
    }
}

#[test]
fn a3_u08_cancellation_eof_and_unselected_corruption() {
    use super::postings::{PostingsReader, encode_split_postings_block};
    let limits = SegmentLimits::default();
    let bytes = encode_split_postings_block(8, &a3_postings(&[1, 4, 7], &[2, 1, 3], true), &limits)
        .expect("encode");

    // One poll per attempted posting; cancellation wins over EOF.
    let canceller = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: 0,
    };
    let mut reader = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    assert!(matches!(
        reader.next_with(&canceller),
        Err(SegmentError::Cancelled)
    ));
    assert_eq!(canceller.polls.get(), 1);

    let canceller = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: 1,
    };
    let mut reader = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    assert_eq!(
        reader
            .next_with(&canceller)
            .expect("decode")
            .expect("posting")
            .doc_id,
        1
    );
    assert!(matches!(
        reader.next_with(&canceller),
        Err(SegmentError::Cancelled)
    ));
    assert_eq!(canceller.polls.get(), 2);

    let canceller = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: 3,
    };
    let mut reader = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    for _ in 0..3 {
        reader
            .next_with(&canceller)
            .expect("decode")
            .expect("posting");
    }
    assert!(matches!(
        reader.next_with(&canceller),
        Err(SegmentError::Cancelled)
    ));
    assert_eq!(canceller.polls.get(), 4);

    let canceller = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: u64::MAX,
    };
    let mut reader = PostingsReader::new_split(&bytes, 8, &limits).expect("header");
    while reader.next_with(&canceller).expect("decode").is_some() {}
    assert!(
        reader
            .next_with(&canceller)
            .expect("repeated eof")
            .is_none()
    );
    assert!(
        reader
            .next_with(&canceller)
            .expect("repeated eof")
            .is_none()
    );
    let flag = crate::analysis::CancellationFlag::new();
    flag.cancel();
    assert!(matches!(
        reader.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));

    // Corruption in a later, unselected/dead positional posting is still fatal.
    let mut raw = A3RawSplit::valid(&[0, 5], &[1, 2], true);
    // Second posting begins after the first posting's five position bytes; its
    // first occurrence has a zero position length.
    raw.positions[6] = 0;
    let bytes = raw.encode();
    for lean in [false, true] {
        let (records, error) = a3_drive(&bytes, 8, &limits, lean);
        assert_eq!(records, vec![(0, 1)]);
        assert!(
            error.is_some(),
            "a dead/nonwinning posting must still be validated"
        );
    }
}

#[test]
fn a3_u09_frequency_and_resource_limits() {
    use super::postings::{Occurrence, PostingsReader, encode_split_postings_block};
    let limits = SegmentLimits::default();

    // Forged posting count above the configured per-term ceiling.
    let mut raw = A3RawSplit::valid(&[0], &[1], false);
    raw.posting_doc_count = 1 << 40;
    let bytes = raw.encode();
    match PostingsReader::new_split(&bytes, u64::MAX, &limits) {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!(limit, limits.max_postings_per_term());
            assert_eq!(requested, 1 << 40);
        }
        other => panic!("unexpected result: {other:?}"),
    }

    // Posting count above the segment doc count.
    let mut raw = A3RawSplit::valid(&[0, 1, 2], &[1, 1, 1], false);
    raw.posting_doc_count = 3;
    let bytes = raw.encode();
    match PostingsReader::new_split(&bytes, 2, &limits) {
        Err(error) => a3_assert_corrupt(&error, "posting count exceeds segment doc count"),
        Ok(_) => panic!("posting count over segment doc count must be rejected"),
    }

    // Zero and over-limit frequencies.
    let zero = A3RawSplit::valid(&[0, 1], &[0, 2], false).encode();
    let (records, error) = a3_drive(&zero, 2, &limits, false);
    assert!(records.is_empty());
    assert!(matches!(
        error,
        Some(SegmentError::ZeroFrequency { doc_id: 0 })
    ));

    let mut raw = A3RawSplit::valid(&[0], &[3], false);
    raw.freq_total = 3;
    let bytes = raw.encode();
    let tight = SegmentLimits::default().with_max_decoded_entries(2);
    for lean in [false, true] {
        let (_, error) = a3_drive(&bytes, 1, &tight, lean);
        match error {
            Some(SegmentError::LimitExceeded { limit, requested }) => {
                assert_eq!(limit, 2);
                assert_eq!(requested, 3);
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }

    // The historical hypothetical occurrence allocation preflight applies in
    // both split modes, even though the lean mode never allocates.
    let bytes = encode_split_postings_block(
        4,
        &[super::postings::Posting {
            doc_id: 1,
            freq: 2,
            occurrences: vec![a3_occurrence(0), a3_occurrence(1)],
        }],
        &limits,
    )
    .expect("encode");
    let exact = (2 * std::mem::size_of::<Occurrence>()) as u64;
    let exact_limits = SegmentLimits::default().with_max_single_allocation(exact);
    let (records, error) = a3_drive(&bytes, 4, &exact_limits, false);
    assert!(error.is_none());
    assert_eq!(records, vec![(1, 2)]);
    let (_, error) = a3_drive(&bytes, 4, &exact_limits, true);
    assert!(error.is_none());
    let under = SegmentLimits::default().with_max_single_allocation(exact - 1);
    let (_, full_error) = a3_drive(&bytes, 4, &under, false);
    let (_, lean_error) = a3_drive(&bytes, 4, &under, true);
    for error in [full_error, lean_error] {
        match error {
            Some(SegmentError::LimitExceeded { limit, requested }) => {
                assert_eq!(limit, exact - 1);
                assert_eq!(requested, exact);
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }

    // A wrong frequency total is only detectable at EOF.
    let mut raw = A3RawSplit::valid(&[0, 1], &[1, 1], false);
    raw.freq_total = 3;
    let bytes = raw.encode();
    for lean in [false, true] {
        let (records, error) = a3_drive(&bytes, 2, &limits, lean);
        assert_eq!(records, vec![(0, 1), (1, 1)]);
        a3_assert_corrupt(
            &error.expect("EOF must reject the wrong total"),
            "frequency total mismatch",
        );
    }

    // Checked frequency-sum overflow while decoding.
    let mut raw = A3RawSplit::valid(&[0, 1], &[u64::MAX, u64::MAX], false);
    raw.freq_total = u64::MAX;
    let bytes = raw.encode();
    let wide = SegmentLimits::default().with_max_decoded_entries(u64::MAX);
    let (records, error) = a3_drive(&bytes, 2, &wide, false);
    assert_eq!(records.len(), 1);
    a3_assert_corrupt(
        &error.expect("overflowed frequency sum must be rejected"),
        "frequency total overflow",
    );

    // A forged block count is rejected before any directory allocation.
    let mut raw = A3RawSplit::valid(&[0, 1], &[1, 1], false);
    raw.block_count = 1 << 20;
    let bytes = raw.encode();
    match PostingsReader::new_split(&bytes, 2, &limits) {
        Err(error) => a3_assert_corrupt(&error, "block count mismatch"),
        Ok(_) => panic!("forged block count must be rejected"),
    }
}

#[test]
fn a3_u10_legacy_encoder_and_reader_unchanged() {
    use super::postings::{
        OCCURRENCE_DOC_ONLY, OCCURRENCE_POSITIONAL, Occurrence, Posting, PostingsReader,
        encode_postings_block,
    };
    let limits = SegmentLimits::default();

    // Byte-exact legacy specimens (frozen by hand, not derived from the codec).
    let doc_only = vec![
        OCCURRENCE_DOC_ONLY,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0, // posting doc count
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0, // frequency total
        0, // absolute doc id
        1, // frequency
    ];
    let encoded = encode_postings_block(
        2,
        &[Posting {
            doc_id: 0,
            freq: 1,
            occurrences: Vec::new(),
        }],
        &limits,
    )
    .expect("legacy doc-only");
    assert_eq!(encoded, doc_only);

    let positional = vec![
        OCCURRENCE_POSITIONAL,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0, // absolute doc id
        1, // frequency
        0, // position delta (absolute 0)
        1, // position length
        0, // value index
        0, // start offset
        1, // end offset
    ];
    let encoded = encode_postings_block(
        2,
        &[Posting {
            doc_id: 0,
            freq: 1,
            occurrences: vec![Occurrence {
                position: 0,
                position_length: 1,
                value_index: 0,
                start_offset: 0,
                end_offset: 1,
            }],
        }],
        &limits,
    )
    .expect("legacy positional");
    assert_eq!(encoded, positional);

    // Each constructor rejects the other version's markers without fallback.
    assert!(matches!(
        PostingsReader::new(&[2u8], 1, &limits),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));
    assert!(matches!(
        PostingsReader::new(&[3u8], 1, &limits),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));
    for marker in [OCCURRENCE_DOC_ONLY, OCCURRENCE_POSITIONAL] {
        let mut raw = A3RawSplit::valid(&[0], &[1], false);
        raw.marker = marker;
        let bytes = raw.encode();
        match PostingsReader::new_split(&bytes, 1, &limits) {
            Err(error) => a3_assert_corrupt(&error, "invalid occurrence marker"),
            Ok(_) => panic!("split constructor must reject legacy markers"),
        }
    }

    // Historical legacy error categories and strings are preserved.
    let mut trailing = doc_only.clone();
    trailing.push(0);
    let mut reader = PostingsReader::new(&trailing, 2, &limits).expect("legacy header");
    assert!(reader.next().expect("decode").is_some());
    match reader.next() {
        Err(SegmentError::Corrupt { context, detail }) => {
            assert_eq!(context, "postings");
            assert_eq!(detail, "1 trailing bytes");
        }
        other => panic!("unexpected result: {other:?}"),
    }

    let mut noncanonical = doc_only.clone();
    noncanonical[17] = 0x80;
    noncanonical[18] = 0x00;
    let mut reader = PostingsReader::new(&noncanonical, 2, &limits).expect("legacy header");
    match reader.next() {
        Err(SegmentError::InvalidVarint { context }) => assert_eq!(context, "doc id delta"),
        other => panic!("unexpected result: {other:?}"),
    }

    let tight = SegmentLimits::default().with_max_decoded_entries(1);
    let two = encode_postings_block(
        4,
        &[Posting {
            doc_id: 0,
            freq: 2,
            occurrences: vec![a3_occurrence(0), a3_occurrence(1)],
        }],
        &tight,
    )
    .expect("legacy encode");
    let mut reader = PostingsReader::new(&two, 4, &tight).expect("legacy header");
    match reader.next() {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!(limit, 1);
            assert_eq!(requested, 2);
        }
        other => panic!("unexpected result: {other:?}"),
    }

    // The checked-in legacy fixtures keep their pinned bytes.
    use sha2::Digest as _;
    let path = format!(
        "{}/tests/fixtures/segment/golden_norms.seg",
        env!("CARGO_MANIFEST_DIR")
    );
    let fixture = std::fs::read(path).expect("golden norms fixture");
    let digest = sha2::Sha256::digest(&fixture);
    let mut rendered = String::with_capacity(64);
    for byte in digest {
        rendered.push_str(&format!("{byte:02x}"));
    }
    assert_eq!(
        rendered, "49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b",
        "legacy golden fixture must never be regenerated"
    );
}

/// Locate a term in a v1 dictionary body and patch its stored fields.
fn a3_patch_dictionary(
    body: &mut [u8],
    term: &str,
    doc_freq: Option<u64>,
    offset: Option<u64>,
    length: Option<u64>,
) -> bool {
    let mut cursor = 0usize;
    cursor += 2; // version
    let fields = a3_u32(body, cursor) as usize;
    cursor += 4;
    for _ in 0..fields {
        cursor += 4; // field id
        let entries = a3_u64(body, cursor) as usize;
        cursor += 8;
        for _ in 0..entries {
            let term_len = u16::from_le_bytes([body[cursor], body[cursor + 1]]) as usize;
            cursor += 2;
            let name = &body[cursor..cursor + term_len];
            let matches = name == term.as_bytes();
            cursor += term_len;
            if matches {
                if let Some(value) = doc_freq {
                    body[cursor..cursor + 8].copy_from_slice(&value.to_le_bytes());
                }
                if let Some(value) = offset {
                    body[cursor + 8..cursor + 16].copy_from_slice(&value.to_le_bytes());
                }
                if let Some(value) = length {
                    body[cursor + 16..cursor + 24].copy_from_slice(&value.to_le_bytes());
                }
                return true;
            }
            cursor += 24;
        }
    }
    false
}

#[test]
fn a3_u11_feature_section_pair_and_dictionary_extents() {
    use super::format::FEATURE_SPLIT_POSTINGS;
    use super::reader::SegmentReader;

    let limits = SegmentLimits::default();
    let bytes = a3_build_segment(&[("a", "alpha beta"), ("b", "alpha"), ("c", "beta gamma")]);
    let reader = SegmentReader::open(bytes.clone(), limits).expect("open");
    let title = reader.schema().field_id("title").expect("title field");
    let dictionary_body = {
        let view = parse_container(&bytes, &limits).expect("container");
        view.body(SectionKind::Dictionary)
            .expect("dictionary")
            .to_vec()
    };
    let postings_body = a3_postings_body(&bytes);
    let mut cursor = 0u64;
    let mut terms = 0usize;
    for entry in reader
        .dictionary()
        .expect("dictionary")
        .field(title)
        .expect("field terms")
    {
        terms += 1;
        assert_eq!(entry.postings_offset, cursor, "contiguous term extents");
        assert_eq!(
            a3_u64(&postings_body, entry.postings_offset as usize + 16),
            entry.doc_freq
        );
        let marker = postings_body[entry.postings_offset as usize];
        assert!(marker == A3_SPLIT_MARKER_DOC_ONLY || marker == A3_SPLIT_MARKER_POSITIONAL);
        cursor += entry.postings_length;
    }
    assert!(terms >= 3);
    assert_eq!(cursor, postings_body.len() as u64, "exact extent coverage");

    // Feature removed but split bytes kept: legacy dispatch fails closed.
    let mut spec = A3Rebuild::new();
    spec.drop_features.push((FEATURE_SPLIT_POSTINGS, 1));
    let rebuilt = a3_rebuild(&bytes, &spec);
    let reader = SegmentReader::open(rebuilt, limits).expect("legacy dispatch opens");
    assert!(matches!(
        reader.postings(title, "alpha"),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));

    // Feature declared without the dictionary/postings pair. The pre-existing
    // single-section pair validation keeps its typed `MissingSection`; the whole
    // pair being absent is the new split-feature corruption.
    for (drop_sections, expected_kind) in [
        (vec![SectionKind::Dictionary], Some(SectionKind::Dictionary)),
        (vec![SectionKind::Postings], Some(SectionKind::Postings)),
        (vec![SectionKind::Dictionary, SectionKind::Postings], None),
    ] {
        let mut spec = A3Rebuild::new();
        spec.drop_sections = drop_sections;
        let rebuilt = a3_rebuild(&bytes, &spec);
        match SegmentReader::open(rebuilt, limits) {
            Err(SegmentError::MissingSection { kind }) => {
                let expected = expected_kind.expect("pair-absent case uses the split error");
                assert_eq!(kind, expected as u16);
            }
            Err(error) if expected_kind.is_none() => a3_assert_corrupt(
                &error,
                "split postings feature requires dictionary and postings",
            ),
            Err(other) => panic!("unexpected error: {other:?}"),
            Ok(_) => panic!("split feature without the section pair must be rejected"),
        }
    }

    // Incorrect dictionary doc_freq for a term.
    let mut patched = dictionary_body.clone();
    assert!(a3_patch_dictionary(
        &mut patched,
        "alpha",
        Some(1),
        None,
        None
    ));
    let mut spec = A3Rebuild::new();
    spec.replace_section = Some((SectionKind::Dictionary, patched));
    let rebuilt = a3_rebuild(&bytes, &spec);
    let reader = SegmentReader::open(rebuilt, limits).expect("patched dictionary opens");
    match reader.postings(title, "alpha") {
        Err(error) => a3_assert_corrupt_with(
            &error,
            "postings",
            "dictionary doc_freq does not match posting count",
        ),
        Ok(_) => panic!("doc_freq mismatch must be rejected"),
    }

    // Per-term offset/length outside the POSTINGS body.
    for (offset, length) in [
        (Some(u64::MAX), None),
        (None, Some(u64::MAX)),
        (Some(1 << 20), None),
    ] {
        let mut patched = dictionary_body.clone();
        assert!(a3_patch_dictionary(
            &mut patched,
            "alpha",
            None,
            offset,
            length
        ));
        let mut spec = A3Rebuild::new();
        spec.replace_section = Some((SectionKind::Dictionary, patched));
        let rebuilt = a3_rebuild(&bytes, &spec);
        match SegmentReader::open(rebuilt, limits) {
            Err(SegmentError::Corrupt { context, .. }) => assert_eq!(context, "dictionary"),
            Err(other) => panic!("unexpected error: {other:?}"),
            Ok(_) => panic!("invalid dictionary extent must be rejected"),
        }
    }
}

#[test]
fn a3_u12_determinism_and_structural_size_report() {
    use super::postings::{encode_postings_block, encode_split_postings_block};

    let limits = SegmentLimits::default();
    let titles = [("a", "alpha beta"), ("b", "beta gamma alpha")];
    let first = a3_build_segment(&titles);
    let second = a3_build_segment(&titles);
    assert_eq!(
        first, second,
        "layout and schema must produce identical bytes"
    );

    println!("PERF-06-A3 structural sizes (bytes; not query latency):");
    for count in [1usize, 127, 128, 129, 257] {
        let docs: Vec<u64> = (0..count as u64).collect();
        let freqs = vec![1u64; count];
        let legacy_doc =
            encode_postings_block(count as u64, &a3_postings(&docs, &freqs, false), &limits)
                .expect("legacy doc-only");
        let split_doc =
            encode_split_postings_block(count as u64, &a3_postings(&docs, &freqs, false), &limits)
                .expect("split doc-only");
        let legacy_pos =
            encode_postings_block(count as u64, &a3_postings(&docs, &freqs, true), &limits)
                .expect("legacy positional");
        let split_pos =
            encode_split_postings_block(count as u64, &a3_postings(&docs, &freqs, true), &limits)
                .expect("split positional");
        println!(
            "  postings={count:>3} legacy_doc_only={} split_doc_only={} legacy_positional={} split_positional={}",
            legacy_doc.len(),
            split_doc.len(),
            legacy_pos.len(),
            split_pos.len()
        );
        // Structural identity only: no performance threshold is asserted.
        let block_count = count.div_ceil(128);
        let doc_stream_len = count + block_count - 1;
        assert_eq!(
            split_doc.len(),
            56 + doc_stream_len + count + block_count * 40
        );
        assert_eq!(
            split_pos.len(),
            56 + doc_stream_len + count + count * 5 + block_count * 40
        );
    }
    println!(
        "  complete segment (2 documents, 1 text field) = {} bytes",
        first.len()
    );
    assert!(!first.is_empty());
}

// ---------------------------------------------------------------------------
// PERF-06-A5: adaptive postings (compact singleton/short lists, split longs).
// ---------------------------------------------------------------------------

const A5_COMPACT_SINGLETON_DOC_ONLY: u8 = 4;
const A5_COMPACT_SINGLETON_POSITIONAL: u8 = 5;
const A5_COMPACT_SHORT_DOC_ONLY: u8 = 6;
const A5_COMPACT_SHORT_POSITIONAL: u8 = 7;
const A5_ADAPTIVE_CONTEXT: &str = "adaptive postings";

fn a5_encode_with(
    segment_doc_count: u64,
    postings: &[super::postings::Posting],
    limits: &SegmentLimits,
) -> Vec<u8> {
    super::postings::encode_adaptive_postings_block(segment_doc_count, postings, limits)
        .expect("adaptive encode")
}

fn a5_encode(docs: &[u64], freqs: &[u64], positional: bool) -> Vec<u8> {
    let segment_doc_count = docs.iter().copied().max().expect("at least one document") + 1;
    a5_encode_with(
        segment_doc_count,
        &a3_postings(docs, freqs, positional),
        &SegmentLimits::default(),
    )
}

fn a5_reader<'a>(
    bytes: &'a [u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> super::postings::PostingsReader<'a> {
    super::postings::PostingsReader::new_adaptive(bytes, segment_doc_count, limits)
        .expect("adaptive reader")
}

fn a5_decode_full(bytes: &[u8], segment_doc_count: u64) -> Vec<super::postings::Posting> {
    let mut reader = a5_reader(bytes, segment_doc_count, &SegmentLimits::default());
    let mut records = Vec::new();
    while let Some(posting) = reader.next().expect("full decode") {
        records.push(posting);
    }
    records
}

fn a5_decode_lean(bytes: &[u8], segment_doc_count: u64) -> Vec<(u64, u64)> {
    let mut reader = a5_reader(bytes, segment_doc_count, &SegmentLimits::default()).into_doc_freq();
    let mut records = Vec::new();
    while let Some(posting) = reader.next().expect("lean decode") {
        records.push((posting.doc_id, posting.freq));
    }
    records
}

/// Drive a compact/split payload through the adaptive full reader.
fn a5_drive_full(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, Option<SegmentError>) {
    use super::postings::PostingsReader;
    let mut reader = match PostingsReader::new_adaptive(bytes, segment_doc_count, limits) {
        Ok(reader) => reader,
        Err(error) => return (Vec::new(), Some(error)),
    };
    let mut records = Vec::new();
    loop {
        match reader.next() {
            Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
            Ok(None) => return (records, None),
            Err(error) => return (records, Some(error)),
        }
    }
}

/// Drive a compact/split payload through the adaptive doc/freq-only reader.
fn a5_drive_lean(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, Option<SegmentError>) {
    use super::postings::PostingsReader;
    let mut reader = match PostingsReader::new_adaptive(bytes, segment_doc_count, limits) {
        Ok(reader) => reader.into_doc_freq(),
        Err(error) => return (Vec::new(), Some(error)),
    };
    let mut records = Vec::new();
    loop {
        match reader.next() {
            Ok(Some(posting)) => records.push((posting.doc_id, posting.freq)),
            Ok(None) => return (records, None),
            Err(error) => return (records, Some(error)),
        }
    }
}

/// Assert both decode modes emit the same records and the same typed error.
fn a5_assert_parity(
    bytes: &[u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> (Vec<(u64, u64)>, SegmentError) {
    let (full_records, full_error) = a5_drive_full(bytes, segment_doc_count, limits);
    let (lean_records, lean_error) = a5_drive_lean(bytes, segment_doc_count, limits);
    assert_eq!(full_records, lean_records, "record sequences must match");
    let full_error = full_error.expect("expected the full reader to fail");
    let lean_error = lean_error.expect("expected the doc/freq reader to fail");
    assert_eq!(
        format!("{full_error:?}"),
        format!("{lean_error:?}"),
        "both modes must report the identical typed error"
    );
    (lean_records, lean_error)
}

/// Parse a compact header directly from the wire (independent of the encoder).
fn a5_header(bytes: &[u8]) -> (u8, u8, Option<u64>, u64, u64, u64, u64) {
    let mut reader = ByteReader::new(bytes);
    let marker = reader.u8("marker").expect("marker");
    let version = reader.u8("version").expect("version");
    let df = match marker {
        A5_COMPACT_SINGLETON_DOC_ONLY | A5_COMPACT_SINGLETON_POSITIONAL => None,
        _ => Some(reader.varint("df").expect("df")),
    };
    let freq_total = reader.varint("freq total").expect("freq total");
    let docs = reader.varint("doc stream length").expect("D");
    let freqs = reader.varint("frequency stream length").expect("F");
    let positions = reader.varint("position stream length").expect("P");
    (marker, version, df, freq_total, docs, freqs, positions)
}

/// Explicit compact wire fixture, authored independently of the encoder.
struct A5RawCompact {
    marker: u8,
    version: u8,
    df: Option<u64>,
    freq_total: u64,
    docs: Vec<u8>,
    freqs: Vec<u8>,
    positions: Vec<u8>,
    doc_len: Option<u64>,
    freq_len: Option<u64>,
    pos_len: Option<u64>,
    tail: Vec<u8>,
}

impl A5RawCompact {
    fn new(marker: u8, freq_total: u64) -> Self {
        Self {
            marker,
            version: 1,
            df: None,
            freq_total,
            docs: Vec::new(),
            freqs: Vec::new(),
            positions: Vec::new(),
            doc_len: None,
            freq_len: None,
            pos_len: None,
            tail: Vec::new(),
        }
    }

    fn df(mut self, df: u64) -> Self {
        self.df = Some(df);
        self
    }

    fn streams(mut self, docs: &[u8], freqs: &[u8], positions: &[u8]) -> Self {
        self.docs = docs.to_vec();
        self.freqs = freqs.to_vec();
        self.positions = positions.to_vec();
        self
    }

    fn declared(mut self, docs: u64, freqs: u64, positions: u64) -> Self {
        self.doc_len = Some(docs);
        self.freq_len = Some(freqs);
        self.pos_len = Some(positions);
        self
    }

    fn encode(&self) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        writer.u8(self.marker);
        writer.u8(self.version);
        if let Some(df) = self.df {
            writer.varint(df);
        }
        writer.varint(self.freq_total);
        writer.varint(self.doc_len.unwrap_or(self.docs.len() as u64));
        writer.varint(self.freq_len.unwrap_or(self.freqs.len() as u64));
        writer.varint(self.pos_len.unwrap_or(self.positions.len() as u64));
        writer.bytes(&self.docs);
        writer.bytes(&self.freqs);
        writer.bytes(&self.positions);
        writer.bytes(&self.tail);
        writer.into_vec()
    }
}

/// Rebuild a container with recomputed digests and the requested feature/section
/// changes. Exactly one constructor-supplied baseline tuple is skipped so the
/// remaining feature multiplicity is preserved.
#[derive(Default)]
struct A5Rebuild {
    add_required: Vec<(u16, u16)>,
    drop_required: Vec<(u16, u16)>,
    add_optional: Vec<(u16, u16)>,
    drop_optional: Vec<(u16, u16)>,
    drop_sections: Vec<SectionKind>,
    replace_section: Option<(SectionKind, Vec<u8>)>,
}

fn a5_rebuild(original: &[u8], spec: &A5Rebuild) -> Vec<u8> {
    use super::format::FEATURE_BASELINE;
    let limits = SegmentLimits::default();
    let view = parse_container(original, &limits).expect("container");
    let mut builder = ContainerBuilder::new(view.kind(), view.doc_count());
    let mut baseline_skipped = false;
    for (feature, version) in view.required_features() {
        if (*feature, *version) == (FEATURE_BASELINE, 1) && !baseline_skipped {
            baseline_skipped = true;
            continue;
        }
        if spec.drop_required.contains(&(*feature, *version)) {
            continue;
        }
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in &spec.add_required {
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in view.optional_features() {
        if spec.drop_optional.contains(&(*feature, *version)) {
            continue;
        }
        builder.optional_feature(*feature, *version);
    }
    for (feature, version) in &spec.add_optional {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        if spec.drop_sections.contains(&section.kind) {
            continue;
        }
        let body = match &spec.replace_section {
            Some((kind, body)) if *kind == section.kind => body.clone(),
            _ => {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            }
        };
        builder.section(section.kind, section.flags, section.aux, body);
    }
    builder.build().expect("rebuilt container")
}

#[test]
fn a5_u01_feature_and_empty_segment_contract() {
    use super::build::{Layout, SegmentBuilder};
    use super::format::{FEATURE_ADAPTIVE_POSTINGS, FEATURE_POSITIONAL, FEATURE_SPLIT_POSTINGS};
    use super::model::SegmentDocument;

    // Exactly the next free feature id, version 1, and supported.
    assert_eq!(FEATURE_ADAPTIVE_POSTINGS, 0x000F);
    assert!(
        super::format::SUPPORTED_FEATURES.contains(&(FEATURE_ADAPTIVE_POSTINGS, 1)),
        "adaptive postings feature must be supported"
    );
    assert!(
        super::format::SUPPORTED_FEATURES.contains(&(FEATURE_SPLIT_POSTINGS, 1)),
        "the retained split postings feature stays supported"
    );
    // The mutation-state section kind reuses numeric 0x000F in a *different*
    // namespace and must not be renumbered.
    assert_eq!(SectionKind::MutationState as u16, 0x000F);
    assert_eq!(SectionKind::Postings as u16, 0x0003);
    assert_eq!(SectionKind::Dictionary as u16, 0x0002);

    // The ordinary builder emits the adaptive family and never split.
    let bytes = a5_build_current_segment(&[("a", "alpha beta"), ("b", "alpha")]);
    let reader =
        super::reader::SegmentReader::open(bytes.clone(), SegmentLimits::default()).expect("open");
    let required = reader.required_features();
    assert!(required.contains(&(FEATURE_ADAPTIVE_POSTINGS, 1)));
    assert!(!required.contains(&(FEATURE_SPLIT_POSTINGS, 1)));
    assert!(required.contains(&(FEATURE_POSITIONAL, 1)));
    let title = reader.schema().field_id("title").expect("title field");
    let body = a3_postings_body(&bytes);
    let mut terms = 0usize;
    for entry in reader
        .dictionary()
        .expect("dictionary")
        .field(title)
        .expect("field terms")
    {
        terms += 1;
        let marker = body[entry.postings_offset as usize];
        let expected = if entry.doc_freq == 1 {
            A5_COMPACT_SINGLETON_POSITIONAL
        } else {
            A5_COMPACT_SHORT_POSITIONAL
        };
        assert_eq!(
            marker, expected,
            "term {:?} (df {}) must select its marker from the live count and positional data",
            entry.term, entry.doc_freq
        );
    }
    assert!(terms > 0, "expected indexed terms");

    // Completely empty segment: neither feature nor section pair.
    let builder = SegmentBuilder::new(a3_schema(), crate::analysis::AnalyzerRegistry::builtin())
        .expect("builder")
        .with_layout(Layout::Insertion);
    let empty = builder.build().expect("build").bytes;
    let view = parse_container(&empty, &SegmentLimits::default()).expect("container");
    assert!(
        !view
            .required_features()
            .contains(&(FEATURE_ADAPTIVE_POSTINGS, 1))
    );
    assert!(
        !view
            .required_features()
            .contains(&(FEATURE_SPLIT_POSTINGS, 1))
    );
    assert!(view.body(SectionKind::Dictionary).is_none());
    assert!(view.body(SectionKind::Postings).is_none());

    // Non-empty stored-only schema: stored values, no indexed terms, no pair.
    let stored_schema = Schema::new(
        vec![FieldDefinition::new(
            "raw",
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::new(false, true, false),
        )],
        None,
    )
    .expect("schema");
    let mut builder =
        SegmentBuilder::new(stored_schema, crate::analysis::AnalyzerRegistry::builtin())
            .expect("builder")
            .with_layout(Layout::Insertion);
    let mut document = SegmentDocument::new(DocumentKey::new("s").expect("key"));
    document.fields.insert(
        "raw".to_owned(),
        FieldValues::Single(FieldValue::Text("alpha".to_owned())),
    );
    builder.add_document(document).expect("add document");
    let stored_only = builder.build().expect("build").bytes;
    let view = parse_container(&stored_only, &SegmentLimits::default()).expect("container");
    assert!(
        !view
            .required_features()
            .contains(&(FEATURE_ADAPTIVE_POSTINGS, 1))
    );
    assert!(
        !view
            .required_features()
            .contains(&(FEATURE_SPLIT_POSTINGS, 1))
    );
    assert!(view.body(SectionKind::Dictionary).is_none());
    assert!(view.body(SectionKind::Postings).is_none());

    // An unknown adaptive feature version is rejected by feature negotiation.
    let mut spec = A5Rebuild::default();
    spec.drop_required.push((FEATURE_ADAPTIVE_POSTINGS, 1));
    spec.add_required.push((FEATURE_ADAPTIVE_POSTINGS, 2));
    let unknown = a5_rebuild(&bytes, &spec);
    match super::reader::SegmentReader::open(unknown, SegmentLimits::default()) {
        Err(SegmentError::UnsupportedFeature {
            feature_id,
            version,
        }) => {
            assert_eq!((feature_id, version), (FEATURE_ADAPTIVE_POSTINGS, 2));
        }
        Err(other) => panic!("unexpected error: {other:?}"),
        Ok(_) => panic!("unknown adaptive feature version must be rejected"),
    }
}

#[test]
fn a5_u02_literal_wire_fixtures_and_absolute_ids() {
    use super::postings::{Posting, encode_adaptive_postings_block};

    let limits = SegmentLimits::default();

    // Singleton doc-only: marker 4, version 1, freq total 1, D/F/P = 1/1/0.
    let singleton_doc = vec![Posting {
        doc_id: 0,
        freq: 1,
        occurrences: Vec::new(),
    }];
    let bytes = encode_adaptive_postings_block(1, &singleton_doc, &limits).expect("encode");
    assert_eq!(
        bytes,
        vec![0x04, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x01],
        "singleton doc-only literal bytes"
    );
    assert_eq!(a5_decode_full(&bytes, 1), singleton_doc);
    assert_eq!(a5_decode_lean(&bytes, 1), vec![(0, 1)]);

    // Singleton positional: one occurrence (0,1,0,0,1).
    let singleton_pos = a3_postings(&[0], &[1], true);
    let bytes = encode_adaptive_postings_block(1, &singleton_pos, &limits).expect("encode");
    assert_eq!(
        bytes,
        vec![
            0x05, 0x01, 0x01, 0x01, 0x01, 0x05, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x01
        ],
        "singleton positional literal bytes"
    );
    assert_eq!(a5_decode_full(&bytes, 1), singleton_pos);
    assert_eq!(a5_decode_lean(&bytes, 1), vec![(0, 1)]);

    // Two-document doc-only.
    let two_doc = a3_postings(&[0, 1], &[1, 1], false);
    let bytes = encode_adaptive_postings_block(2, &two_doc, &limits).expect("encode");
    assert_eq!(
        bytes,
        vec![
            0x06, 0x01, 0x02, 0x02, 0x02, 0x02, 0x00, 0x00, 0x01, 0x01, 0x01
        ],
        "two-document doc-only literal bytes"
    );
    assert_eq!(a5_decode_full(&bytes, 2), two_doc);
    assert_eq!(a5_decode_lean(&bytes, 2), vec![(0, 1), (1, 1)]);

    // Two-document positional.
    let two_pos = a3_postings(&[0, 1], &[1, 1], true);
    let bytes = encode_adaptive_postings_block(2, &two_pos, &limits).expect("encode");
    assert_eq!(
        bytes,
        vec![
            0x07, 0x01, 0x02, 0x02, 0x02, 0x02, 0x0a, 0x00, 0x01, 0x01, 0x01, 0x00, 0x01, 0x00,
            0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x01
        ],
        "two-document positional literal bytes"
    );
    assert_eq!(a5_decode_full(&bytes, 2), two_pos);
    assert_eq!(a5_decode_lean(&bytes, 2), vec![(0, 1), (1, 1)]);

    // Singleton frequency > 1: the header carries the real sum and the body the
    // real per-posting frequency.
    let frequent = vec![Posting {
        doc_id: 5,
        freq: 3,
        occurrences: Vec::new(),
    }];
    let bytes = encode_adaptive_postings_block(6, &frequent, &limits).expect("encode");
    let (marker, version, df, freq_total, _, _, _) = a5_header(&bytes);
    assert_eq!(marker, A5_COMPACT_SINGLETON_DOC_ONLY);
    assert_eq!(version, 1);
    assert_eq!(df, None, "singleton count is implicit");
    assert_eq!(freq_total, 3);
    assert_eq!(a5_decode_full(&bytes, 6), frequent);

    // Absolute first document ids at each varint width boundary.
    for (doc_id, width) in [(0u64, 1u64), (127, 1), (128, 2), (16383, 2), (16384, 3)] {
        let postings = vec![Posting {
            doc_id,
            freq: 1,
            occurrences: Vec::new(),
        }];
        let bytes = encode_adaptive_postings_block(doc_id + 1, &postings, &limits).expect("encode");
        let (marker, _, _, _, doc_len, _, _) = a5_header(&bytes);
        assert_eq!(marker, A5_COMPACT_SINGLETON_DOC_ONLY);
        assert_eq!(doc_len, width, "doc id {doc_id} width");
        assert_eq!(a5_decode_full(&bytes, doc_id + 1), postings);
        assert_eq!(a5_decode_lean(&bytes, doc_id + 1), vec![(doc_id, 1)]);
    }
}

#[test]
fn a5_u03_short_forms_and_stream_length_boundaries() {
    use super::postings::{Occurrence, Posting};

    let limits = SegmentLimits::default();

    // df 2/127/128 with sparse ids, varied frequencies and reset value indices.
    let cases: Vec<(Vec<u64>, Vec<u64>)> = vec![
        (vec![3, 200], vec![2, 1]),
        (
            (0..127u64).map(|index| index * 2).collect(),
            (0..127u64).map(|index| 1 + index % 3).collect(),
        ),
        (
            (0..128u64).map(|index| index * 2).collect(),
            (0..128u64).map(|index| 1 + index % 4).collect(),
        ),
    ];
    for (docs, freqs) in &cases {
        let segment_doc_count = docs.last().expect("docs") + 1;
        for positional in [false, true] {
            let mut postings = a3_postings(docs, freqs, positional);
            if positional {
                // Repeated field values: value index increases per occurrence but
                // resets for every posting.
                for posting in &mut postings {
                    posting.occurrences = (0..posting.freq)
                        .map(|index| Occurrence {
                            position: index * 2,
                            position_length: 1 + index % 2,
                            value_index: index / 2,
                            start_offset: index * 3,
                            end_offset: index * 3 + 1,
                        })
                        .collect();
                }
            }
            let bytes = a5_encode_with(segment_doc_count, &postings, &limits);
            let (marker, version, df, freq_total, doc_len, freq_len, pos_len) = a5_header(&bytes);
            assert_eq!(version, 1);
            assert_eq!(df, Some(docs.len() as u64));
            assert_eq!(freq_total, freqs.iter().sum::<u64>());
            assert_eq!(
                marker,
                if positional {
                    A5_COMPACT_SHORT_POSITIONAL
                } else {
                    A5_COMPACT_SHORT_DOC_ONLY
                },
                "marker is selected by count and positional data only"
            );
            assert!(doc_len >= docs.len() as u64);
            assert!(freq_len >= docs.len() as u64);
            if positional {
                assert!(pos_len >= 5 * freq_total);
            } else {
                assert_eq!(pos_len, 0);
            }
            assert_eq!(a5_decode_full(&bytes, segment_doc_count), postings);
            let lean: Vec<(u64, u64)> = postings
                .iter()
                .map(|posting| (posting.doc_id, posting.freq))
                .collect();
            assert_eq!(a5_decode_lean(&bytes, segment_doc_count), lean);
        }
    }

    // df=127/128 exercise the 127/128 stream-length varint boundary.
    let boundary = a5_header(&a5_encode(
        &(0..128u64).collect::<Vec<_>>(),
        &vec![1u64; 128],
        false,
    ));
    assert_eq!(boundary.4, 128, "doc stream length 128 needs two bytes");
    assert_eq!(boundary.5, 128, "frequency stream length 128");

    // Wider document/frequency/header values separately.
    let wide = vec![
        Posting {
            doc_id: 16_384,
            freq: 16_384,
            occurrences: Vec::new(),
        },
        Posting {
            doc_id: 40_000,
            freq: 1,
            occurrences: Vec::new(),
        },
    ];
    let bytes = a5_encode_with(40_001, &wide, &limits);
    let (_, _, _, freq_total, _, _, _) = a5_header(&bytes);
    assert_eq!(freq_total, 16_385);
    assert_eq!(a5_decode_full(&bytes, 40_001), wide);

    // Position-stream length exactly 16_383 and exactly 16_384 bytes.
    let base_occurrences: Vec<Occurrence> = (0..1_638u64)
        .map(|index| Occurrence {
            position: index,
            position_length: 1,
            value_index: 0,
            start_offset: 0,
            end_offset: 1,
        })
        .collect();
    let build = |changed: usize| {
        let mut first = base_occurrences.clone();
        for occurrence in first.iter_mut().take(changed) {
            occurrence.position_length = 128;
        }
        vec![
            Posting {
                doc_id: 0,
                freq: 1_638,
                occurrences: first,
            },
            Posting {
                doc_id: 1,
                freq: 1_638,
                occurrences: base_occurrences.clone(),
            },
        ]
    };
    for (changed, expected) in [(0usize, 16_380u64), (3, 16_383), (4, 16_384)] {
        let postings = build(changed);
        let bytes = a5_encode_with(2, &postings, &limits);
        let (_, _, _, _, _, _, pos_len) = a5_header(&bytes);
        assert_eq!(
            pos_len, expected,
            "position stream length with {changed} change(s)"
        );
        assert_eq!(a5_decode_full(&bytes, 2), postings);
    }
}

#[test]
fn a5_u04_long_delegation_and_old_parser_compatibility() {
    use super::postings::{
        PostingsReader, encode_adaptive_postings_block, encode_split_postings_block,
    };

    let limits = SegmentLimits::default();
    for count in [129usize, 256, 257] {
        let docs: Vec<u64> = (0..count as u64).collect();
        let freqs = vec![1u64; count];
        for positional in [false, true] {
            let postings = a3_postings(&docs, &freqs, positional);
            let adaptive =
                encode_adaptive_postings_block(count as u64, &postings, &limits).expect("adaptive");
            let split =
                encode_split_postings_block(count as u64, &postings, &limits).expect("split");
            assert_eq!(
                adaptive, split,
                "documents={count} positional={positional}: long lists stay byte-identical"
            );
            assert_eq!(a5_decode_full(&adaptive, count as u64), postings);
        }
    }

    // The split parser accepts small A3 payloads; the adaptive parser rejects
    // them only after the old parser has fully validated them.
    for count in [1usize, 2, 128] {
        let docs: Vec<u64> = (0..count as u64).collect();
        let postings = a3_postings(&docs, &vec![1u64; count], true);
        let split = encode_split_postings_block(count as u64, &postings, &limits).expect("split");
        let mut legacy_split = PostingsReader::new_split(&split, count as u64, &limits)
            .expect("split parser accepts A3");
        assert_eq!(legacy_split.posting_doc_count(), count as u64);
        while legacy_split.next().expect("decode").is_some() {}
        match PostingsReader::new_adaptive(&split, count as u64, &limits) {
            Err(error) => a3_assert_corrupt_with(
                &error,
                A5_ADAPTIVE_CONTEXT,
                "noncanonical split posting count",
            ),
            Ok(_) => panic!("adaptive must reject canonical split at df<=128"),
        }
    }

    // Malformed A3 keeps its original error precedence: the old parser error wins
    // ahead of the canonical-count selector check.
    let docs: Vec<u64> = (0..129).collect();
    let split =
        encode_split_postings_block(129, &a3_postings(&docs, &vec![1u64; 129], false), &limits)
            .expect("split");
    let truncated = &split[..split.len() - 1];
    match PostingsReader::new_adaptive(truncated, 129, &limits) {
        Err(error) => a3_assert_corrupt(&error, "extent length mismatch"),
        Ok(_) => panic!("truncated A3 payload must be rejected"),
    }
}

#[test]
fn a5_u05_source_validation_order_is_preserved() {
    use super::postings::{
        Posting, encode_adaptive_postings_block, encode_postings_block, encode_split_postings_block,
    };

    let limits = SegmentLimits::default();
    let occurrence = |index: u64| super::postings::Occurrence {
        position: index,
        position_length: 1,
        value_index: 0,
        start_offset: 0,
        end_offset: 1,
    };
    let posting = |doc_id: u64, freq: u64, occurrences: Vec<super::postings::Occurrence>| Posting {
        doc_id,
        freq,
        occurrences,
    };

    let cases: Vec<(Vec<Posting>, u64)> = vec![
        (Vec::new(), 4),
        // Count greater than segment document count.
        (a3_postings(&[0, 1], &[1, 1], false), 1),
        // Out-of-range id.
        (vec![posting(9, 1, Vec::new())], 4),
        // Duplicate id.
        (
            vec![posting(1, 1, Vec::new()), posting(1, 1, Vec::new())],
            4,
        ),
        // Decreasing id.
        (
            vec![posting(2, 1, Vec::new()), posting(1, 1, Vec::new())],
            4,
        ),
        // Zero frequency (doubly invalid with an out-of-range id: range wins).
        (vec![posting(9, 0, Vec::new())], 4),
        // Frequency/occurrence mismatch.
        (vec![posting(0, 2, vec![occurrence(0)])], 4),
        // Frequency total overflow.
        (
            vec![posting(0, u64::MAX, Vec::new()), posting(1, 1, Vec::new())],
            4,
        ),
        // Zero position length.
        (
            vec![posting(
                0,
                1,
                vec![super::postings::Occurrence {
                    position: 0,
                    position_length: 0,
                    value_index: 0,
                    start_offset: 0,
                    end_offset: 1,
                }],
            )],
            4,
        ),
        // Decreasing position.
        (vec![posting(0, 2, vec![occurrence(1), occurrence(1)])], 4),
        // Decreasing value index.
        (
            vec![posting(
                0,
                2,
                vec![
                    super::postings::Occurrence {
                        position: 0,
                        position_length: 1,
                        value_index: 3,
                        start_offset: 0,
                        end_offset: 1,
                    },
                    super::postings::Occurrence {
                        position: 1,
                        position_length: 1,
                        value_index: 2,
                        start_offset: 2,
                        end_offset: 3,
                    },
                ],
            )],
            4,
        ),
        // Reversed offsets.
        (
            vec![posting(
                0,
                1,
                vec![super::postings::Occurrence {
                    position: 0,
                    position_length: 1,
                    value_index: 0,
                    start_offset: 5,
                    end_offset: 4,
                }],
            )],
            4,
        ),
    ];

    for (index, (postings, segment_doc_count)) in cases.iter().enumerate() {
        let adaptive = encode_adaptive_postings_block(*segment_doc_count, postings, &limits).err();
        let legacy = encode_postings_block(*segment_doc_count, postings, &limits).err();
        let split = encode_split_postings_block(*segment_doc_count, postings, &limits).err();
        let adaptive = adaptive.unwrap_or_else(|| panic!("case {index}: adaptive must fail"));
        let legacy = legacy.unwrap_or_else(|| panic!("case {index}: legacy must fail"));
        let split = split.unwrap_or_else(|| panic!("case {index}: split must fail"));
        assert_eq!(
            format!("{adaptive:?}"),
            format!("{legacy:?}"),
            "case {index}: adaptive matches the legacy source error"
        );
        assert_eq!(
            format!("{adaptive:?}"),
            format!("{split:?}"),
            "case {index}: adaptive matches the split source error"
        );
    }

    // The first failing rule wins, not a later more specific one.
    let order = vec![posting(9, 0, Vec::new())];
    let error = encode_adaptive_postings_block(4, &order, &limits).expect_err("must fail");
    a3_assert_corrupt_with(&error, "postings", "doc id out of range");
}

#[test]
fn a5_u06_compact_framing_is_canonical_and_bounded() {
    use super::postings::PostingsReader;

    let limits = SegmentLimits::default();
    let reject = |bytes: &[u8], segment_doc_count: u64, context: &str, detail: &str| {
        match PostingsReader::new_adaptive(bytes, segment_doc_count, &limits) {
            Err(error) => a3_assert_corrupt_with(&error, context, detail),
            Ok(_) => panic!("expected {context} rejection of {detail}"),
        }
    };

    // Marker/version.
    match PostingsReader::new_adaptive(&[], 1, &limits) {
        Err(SegmentError::Truncated { context, .. }) => {
            assert_eq!(context, "adaptive occurrence marker");
        }
        other => panic!("unexpected: {other:?}"),
    }
    reject(&[0x00], 1, A5_ADAPTIVE_CONTEXT, "invalid occurrence marker");
    reject(
        &A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
            .streams(&[0], &[1], &[])
            .encode()
            .iter()
            .enumerate()
            .map(|(index, byte)| if index == 1 { 2 } else { *byte })
            .collect::<Vec<_>>(),
        1,
        A5_ADAPTIVE_CONTEXT,
        "unsupported payload version",
    );

    // Every header field truncated keeps the adaptive varint context.
    let valid = A5RawCompact::new(A5_COMPACT_SHORT_POSITIONAL, 2)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[0, 1, 0, 0, 1, 0, 1, 0, 0, 1])
        .encode();
    for cut in 1..7usize {
        match PostingsReader::new_adaptive(&valid[..cut], 2, &limits) {
            Err(SegmentError::Truncated { context, .. }) => {
                assert!(
                    context.starts_with("adaptive "),
                    "truncated header context: {context}"
                );
            }
            other => panic!("cut {cut}: unexpected {other:?}"),
        }
    }

    // Overlong/non-canonical and >u64 varints.
    let mut overlong = vec![A5_COMPACT_SHORT_DOC_ONLY, 1];
    overlong.extend_from_slice(&[0x82, 0x00]);
    match PostingsReader::new_adaptive(&overlong, 4, &limits) {
        Err(SegmentError::InvalidVarint { context }) => {
            assert_eq!(context, "adaptive posting doc count");
        }
        other => panic!("unexpected: {other:?}"),
    }
    let mut too_long = vec![A5_COMPACT_SHORT_DOC_ONLY, 1];
    too_long.extend_from_slice(&[0xff; 11]);
    match PostingsReader::new_adaptive(&too_long, 4, &limits) {
        Err(SegmentError::InvalidVarint { context }) => {
            assert_eq!(context, "adaptive posting doc count");
        }
        other => panic!("unexpected: {other:?}"),
    }

    // Canonical counts only.
    for df in [0u64, 1, 129] {
        let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
            .df(df)
            .streams(&[0, 1], &[1, 1], &[])
            .encode();
        reject(
            &bytes,
            4,
            A5_ADAPTIVE_CONTEXT,
            "noncanonical compact posting count",
        );
    }
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[])
        .encode();
    reject(
        &bytes,
        1,
        A5_ADAPTIVE_CONTEXT,
        "posting count exceeds segment doc count",
    );

    // Frequency total below the posting count.
    for freq_total in [0u64, 1] {
        let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, freq_total)
            .df(2)
            .streams(&[0, 1], &[1, 1], &[])
            .encode();
        reject(
            &bytes,
            4,
            A5_ADAPTIVE_CONTEXT,
            "frequency total below posting count",
        );
    }

    // Declared stream lengths below the document/posting count.
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[])
        .declared(1, 2, 0)
        .encode();
    reject(&bytes, 4, A5_ADAPTIVE_CONTEXT, "doc stream too short");
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[])
        .declared(2, 1, 0)
        .encode();
    reject(&bytes, 4, A5_ADAPTIVE_CONTEXT, "frequency stream too short");

    // Doc-only payloads carry no positional bytes.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[1], &[0])
        .encode();
    reject(&bytes, 1, A5_ADAPTIVE_CONTEXT, "doc-only positional bytes");

    // Positional payloads need five bytes per occurrence, multiplicatively.
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_POSITIONAL, 2)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[0, 1, 0, 0, 1, 0, 1, 0, 0])
        .encode();
    reject(&bytes, 4, A5_ADAPTIVE_CONTEXT, "position stream too short");
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_POSITIONAL, u64::MAX)
        .df(2)
        .streams(&[0, 1], &[1, 1], &[])
        .encode();
    reject(&bytes, 4, A5_ADAPTIVE_CONTEXT, "length overflow");

    // Checked total/extent arithmetic and exact extents.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[1], &[])
        .declared(u64::MAX, 1, 0)
        .encode();
    reject(&bytes, 1, A5_ADAPTIVE_CONTEXT, "length overflow");
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[1], &[])
        .declared(2, 1, 0)
        .encode();
    reject(&bytes, 1, A5_ADAPTIVE_CONTEXT, "extent length mismatch");
    let valid = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[1], &[])
        .encode();
    reject(
        &valid[..valid.len() - 1],
        1,
        A5_ADAPTIVE_CONTEXT,
        "extent length mismatch",
    );
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_POSITIONAL, 1)
        .streams(&[0], &[1], &[0, 1, 0, 0, 1])
        .declared(2, 1, 5)
        .encode();
    reject(&bytes, 1, A5_ADAPTIVE_CONTEXT, "extent length mismatch");
}

#[test]
fn a5_u07_lazy_full_and_lean_parity() {
    let limits = SegmentLimits::default();
    let occurrence = |position: u64, length: u64, value_index: u64, start: u64, end: u64| {
        let mut writer = ByteWriter::new();
        writer.varint(position);
        writer.varint(length);
        writer.varint(value_index);
        writer.varint(start);
        writer.varint(end);
        writer.into_vec()
    };

    // Zero doc delta between postings.
    let mut docs = ByteWriter::new();
    docs.varint(0);
    docs.varint(0);
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
        .df(2)
        .streams(docs.as_slice(), &[1, 1], &[])
        .encode();
    let (_, error) = a5_assert_parity(&bytes, 4, &limits);
    assert!(matches!(error, SegmentError::NonMonotoneDocId { .. }));

    // Document-id addition overflow.
    let mut docs = ByteWriter::new();
    docs.varint(1);
    docs.varint(u64::MAX);
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, u64::MAX)
        .df(2)
        .streams(docs.as_slice(), &[1, 1], &[])
        .encode();
    let (records, error) = a5_assert_parity(&bytes, 4, &limits);
    assert_eq!(records, vec![(1, 1)]);
    a3_assert_corrupt_with(&error, "postings", "doc id overflow");

    // Document id out of range.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[7], &[1], &[])
        .encode();
    let (_, error) = a5_assert_parity(&bytes, 4, &limits);
    a3_assert_corrupt_with(&error, "postings", "doc id out of range");

    // Zero frequency.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[0], &[])
        .encode();
    let (_, error) = a5_assert_parity(&bytes, 1, &limits);
    assert!(matches!(error, SegmentError::ZeroFrequency { doc_id: 0 }));

    // Invalid frequency varint.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
        .streams(&[0], &[0x80, 0x00], &[])
        .encode();
    let (_, error) = a5_assert_parity(&bytes, 1, &limits);
    assert!(matches!(error, SegmentError::InvalidVarint { .. }));

    // Position corruption reaches the same semantic error in both modes.
    // Each fixture is an explicit one-posting compact payload.
    let build_positional =
        |freq_total: u64, docs: &[u8], freqs: &[u8], positions: &[u8], df: Option<u64>| {
            let marker = if df.is_none() {
                A5_COMPACT_SINGLETON_POSITIONAL
            } else {
                A5_COMPACT_SHORT_POSITIONAL
            };
            let mut raw = A5RawCompact::new(marker, freq_total).streams(docs, freqs, positions);
            if let Some(df) = df {
                raw = raw.df(df);
            }
            raw.encode()
        };
    let cases: Vec<(Vec<u8>, u64, &str)> = vec![
        // Repeated position (df 1, freq 2).
        (
            build_positional(
                2,
                &[0],
                &[2],
                &[occurrence(0, 1, 0, 0, 1), occurrence(0, 1, 0, 0, 1)].concat(),
                None,
            ),
            4,
            "NonMonotonePosition",
        ),
        // Position addition overflow.
        (
            build_positional(
                2,
                &[0],
                &[2],
                &[occurrence(1, 1, 0, 0, 1), occurrence(u64::MAX, 1, 0, 0, 1)].concat(),
                None,
            ),
            4,
            "position overflow",
        ),
        // Zero position length.
        (
            build_positional(1, &[0], &[1], &occurrence(0, 0, 0, 0, 1), None),
            1,
            "zero position length",
        ),
        // Decreasing value index.
        (
            build_positional(
                2,
                &[0],
                &[2],
                &[occurrence(0, 1, 2, 0, 1), occurrence(1, 1, 1, 2, 3)].concat(),
                None,
            ),
            4,
            "value index decreased",
        ),
        // Reversed offsets.
        (
            build_positional(1, &[0], &[1], &occurrence(0, 1, 0, 9, 3), None),
            1,
            "start offset exceeds end offset",
        ),
    ];
    for (index, (bytes, segment_doc_count, expected)) in cases.iter().enumerate() {
        let (_, error) = a5_assert_parity(bytes, *segment_doc_count, &limits);
        let rendered = format!("{error:?}");
        assert!(
            rendered.contains(expected),
            "case {index}: expected {expected:?}, saw {rendered}"
        );
    }

    // Truncated/non-canonical occurrence fields.
    let truncated = A5RawCompact::new(A5_COMPACT_SINGLETON_POSITIONAL, 1)
        .streams(&[0], &[1], &[0, 1, 0, 0, 0x80])
        .encode();
    let (_, error) = a5_assert_parity(&truncated, 1, &limits);
    assert!(matches!(error, SegmentError::Truncated { .. }));
    let noncanonical = A5RawCompact::new(A5_COMPACT_SINGLETON_POSITIONAL, 1)
        .streams(&[0], &[1], &[0, 1, 0, 0, 0x80, 0x00])
        .encode();
    let (_, error) = a5_assert_parity(&noncanonical, 1, &limits);
    assert!(matches!(error, SegmentError::InvalidVarint { .. }));

    // A clean first posting followed by a corrupt second one: construction and
    // the first read succeed in both APIs, then both fail identically.
    let mut docs = ByteWriter::new();
    docs.varint(0);
    docs.varint(1);
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, 2)
        .df(2)
        .streams(docs.as_slice(), &[1, 0], &[])
        .encode();
    let mut full = super::postings::PostingsReader::new_adaptive(&bytes, 2, &limits)
        .expect("construction is lazy");
    let mut lean = super::postings::PostingsReader::new_adaptive(&bytes, 2, &limits)
        .expect("construction is lazy")
        .into_doc_freq();
    assert_eq!(
        full.next().expect("first").map(|posting| posting.doc_id),
        Some(0)
    );
    assert_eq!(
        lean.next().expect("first").map(|posting| posting.doc_id),
        Some(0)
    );
    let full_error = full.next().expect_err("second posting is corrupt");
    let lean_error = lean.next().expect_err("second posting is corrupt");
    assert!(matches!(
        full_error,
        SegmentError::ZeroFrequency { doc_id: 1 }
    ));
    assert_eq!(format!("{full_error:?}"), format!("{lean_error:?}"));
}

#[test]
fn a5_u08_cancellation_advance_and_conversion() {
    use crate::analysis::CancellationFlag;

    let limits = SegmentLimits::default();
    let docs: Vec<u64> = (0..3).collect();
    let postings = a3_postings(&docs, &[1, 1, 1], true);
    let bytes = a5_encode_with(3, &postings, &limits);

    // Cancellation before the first, subsequent, final and post-EOF attempts.
    let flag = CancellationFlag::new();
    flag.cancel();
    let mut reader = super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    assert!(matches!(
        reader.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));

    let counting = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: 1,
    };
    let mut reader = super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    assert_eq!(
        reader.next_with(&counting).expect("first"),
        Some(super::postings::DocFreqPosting { doc_id: 0, freq: 1 })
    );
    assert!(matches!(
        reader.next_with(&counting),
        Err(SegmentError::Cancelled)
    ));

    // Cancellation before the final exhaustion check.
    let final_flag = A2CountingCancel {
        polls: std::cell::Cell::new(0),
        cancel_after: 3,
    };
    let mut reader = super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    for _ in 0..3 {
        assert!(reader.next_with(&final_flag).expect("posting").is_some());
    }
    assert!(matches!(
        reader.next_with(&final_flag),
        Err(SegmentError::Cancelled)
    ));

    // Repeated uncancelled EOF is a stable `None`.
    let mut reader = super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    while reader.next().expect("decode").is_some() {}
    assert!(reader.next().expect("repeat EOF").is_none());
    assert!(reader.next().expect("repeat EOF").is_none());

    // Cancelled next after EOF still reports cancellation.
    let flag = CancellationFlag::new();
    let mut reader = super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    while reader.next().expect("decode").is_some() {}
    flag.cancel();
    assert!(matches!(
        reader.next_with(&flag),
        Err(SegmentError::Cancelled)
    ));

    // Full advance across clean intervening postings and the cached-target case.
    let mut reader =
        super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits).expect("reader");
    let advanced = reader.advance(2).expect("advance").expect("posting");
    assert_eq!(advanced.doc_id, 2);
    // Cached target: no cancellation poll on this no-read path.
    let flag = CancellationFlag::new();
    flag.cancel();
    assert_eq!(
        reader
            .advance_with(2, &flag)
            .expect("cached advance")
            .expect("posting")
            .doc_id,
        2
    );
    assert!(matches!(
        reader.advance_with(3, &flag),
        Err(SegmentError::Cancelled)
    ));

    // Conversion then lean next continues at the next unread posting.
    let mut full =
        super::postings::PostingsReader::new_adaptive(&bytes, 3, &limits).expect("reader");
    assert_eq!(full.next().expect("first").expect("posting").doc_id, 0);
    let mut lean = full.into_doc_freq();
    assert_eq!(lean.next().expect("second").expect("posting").doc_id, 1);
}

#[test]
fn a5_u09_resource_limits_and_incremental_charging() {
    use super::postings::{DocFreqPosting, PostingsReader};

    let postings = a3_postings(&[0, 1], &[1, 1], true);
    let bytes = a5_encode_with(2, &postings, &SegmentLimits::default());
    let total = bytes.len() as u64;

    // Encoded output admitted at exactly the limit and rejected one byte under.
    let exact = SegmentLimits::default().with_max_single_allocation(total);
    assert_eq!(a5_encode_with(2, &postings, &exact).len(), bytes.len());
    let short = SegmentLimits::default().with_max_single_allocation(total - 1);
    match super::postings::encode_adaptive_postings_block(2, &postings, &short) {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!((limit, requested), (total - 1, total));
        }
        other => panic!("unexpected: {other:?}"),
    }

    // Construction does not charge decoded entries; the budget is incremental.
    let one_entry = SegmentLimits::default().with_max_decoded_entries(1);
    let mut reader = PostingsReader::new_adaptive(&bytes, 2, &one_entry).expect("constructs");
    assert!(reader.next().expect("first posting").is_some());
    match reader.next() {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!((limit, requested), (1, 2));
        }
        other => panic!("unexpected: {other:?}"),
    }

    // Posting frequency equal to and one over the decoded-entry limit.
    let doc_only = a5_encode(&[0], &[5], false);
    let mut at_limit = PostingsReader::new_adaptive(
        &doc_only,
        1,
        &SegmentLimits::default().with_max_decoded_entries(5),
    )
    .expect("constructs");
    assert_eq!(
        at_limit.next().expect("posting"),
        Some(super::postings::Posting {
            doc_id: 0,
            freq: 5,
            occurrences: Vec::new()
        })
    );
    let mut over = PostingsReader::new_adaptive(
        &doc_only,
        1,
        &SegmentLimits::default().with_max_decoded_entries(4),
    )
    .expect("constructs");
    match over.next() {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!((limit, requested), (4, 5))
        }
        other => panic!("unexpected: {other:?}"),
    }

    // The hypothetical positional occurrence allocation is charged identically in
    // both modes, at the exact bound and one byte below.
    let occurrence_bytes = std::mem::size_of::<super::postings::Occurrence>() as u64;
    let positional = a5_encode(&[0], &[1], true);
    for (limit, allowed) in [(occurrence_bytes, true), (occurrence_bytes - 1, false)] {
        let limits = SegmentLimits::default().with_max_single_allocation(limit);
        for lean in [false, true] {
            let mut reader = PostingsReader::new_adaptive(&positional, 1, &limits)
                .expect("borrowed construction");
            if lean {
                let mut lean = reader.into_doc_freq();
                let result = lean.next();
                if allowed {
                    assert_eq!(
                        result.expect("within bound"),
                        Some(DocFreqPosting { doc_id: 0, freq: 1 })
                    );
                } else {
                    assert!(matches!(result, Err(SegmentError::LimitExceeded { .. })));
                }
            } else if allowed {
                assert!(reader.next().expect("within bound").is_some());
            } else {
                assert!(matches!(
                    reader.next(),
                    Err(SegmentError::LimitExceeded { .. })
                ));
            }
        }
    }

    // A forged A3 header at the existing parser seam still enforces
    // max_postings_per_term (compact's canonical df<=128 cannot reach it).
    let mut forged = A3RawSplit::valid(&[0, 1], &[1, 1], false);
    forged.posting_doc_count = u64::MAX;
    let forged = forged.encode();
    match PostingsReader::new_adaptive(&forged, 2, &SegmentLimits::default()) {
        Err(SegmentError::LimitExceeded { limit, requested }) => {
            assert_eq!(limit, SegmentLimits::default().max_postings_per_term());
            assert_eq!(requested, u64::MAX);
        }
        other => panic!("unexpected: {other:?}"),
    }
}

#[test]
fn a5_u10_decode_and_conversion_witnesses() {
    use super::postings::{PostingsReader, decode_observation};

    let limits = SegmentLimits::default();
    let postings = a3_postings(&[0, 2], &[2, 1], true);
    let bytes = a5_encode_with(3, &postings, &limits);

    decode_observation::reset();
    let mut full = PostingsReader::new_adaptive(&bytes, 3, &limits).expect("reader");
    while full.next().expect("decode").is_some() {}
    let (reserves, clones) = decode_observation::counts();
    assert_eq!(reserves, 2, "one positional vector per posting");
    assert_eq!(clones, 2, "one cached full posting clone per posting");

    decode_observation::reset();
    let mut lean = PostingsReader::new_adaptive(&bytes, 3, &limits)
        .expect("reader")
        .into_doc_freq();
    while lean.next().expect("decode").is_some() {}
    assert_eq!(
        decode_observation::counts(),
        (0, 0),
        "the lean view neither reserves occurrence vectors nor clones postings"
    );

    // Full read, then consuming conversion: the next record continues after the
    // cached posting and the final verification still runs.
    let mut reader = PostingsReader::new_adaptive(&bytes, 3, &limits).expect("reader");
    assert_eq!(reader.next().expect("first").expect("posting").doc_id, 0);
    let mut lean = reader.into_doc_freq();
    assert_eq!(
        lean.next().expect("second"),
        Some(super::postings::DocFreqPosting { doc_id: 2, freq: 1 })
    );
    assert!(lean.next().expect("EOF").is_none());
}

#[test]
fn a5_u11_frequency_totals_and_stream_tails() {
    let limits = SegmentLimits::default();

    // Header frequency total vs body frequency: the returned record keeps the
    // real body frequency and the mismatch fails at EOF.
    let bytes = A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 5)
        .streams(&[0], &[1], &[])
        .encode();
    let mut reader =
        super::postings::PostingsReader::new_adaptive(&bytes, 1, &limits).expect("constructs");
    let posting = reader.next().expect("first").expect("posting");
    assert_eq!(posting.freq, 1, "the body frequency is never substituted");
    let error = reader.next().expect_err("mismatch at EOF");
    a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, "frequency total mismatch");

    // Each stream's trailing bytes reach its own ordered finish error.
    let trailing = [
        (
            A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
                .streams(&[0, 0], &[1], &[])
                .encode(),
            "doc stream trailing bytes",
        ),
        (
            A5RawCompact::new(A5_COMPACT_SINGLETON_DOC_ONLY, 1)
                .streams(&[0], &[1, 1], &[])
                .encode(),
            "frequency stream trailing bytes",
        ),
        (
            A5RawCompact::new(A5_COMPACT_SINGLETON_POSITIONAL, 1)
                .streams(&[0], &[1], &[0, 1, 0, 0, 1, 0])
                .encode(),
            "position stream trailing bytes",
        ),
    ];
    for (bytes, detail) in trailing {
        let mut reader =
            super::postings::PostingsReader::new_adaptive(&bytes, 1, &limits).expect("constructs");
        assert!(reader.next().expect("first").is_some());
        let error = reader.next().expect_err("finish error");
        a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, detail);
    }

    // Checked observed-sum overflow uses bounded doc-only raw bytes.
    let mut freqs = ByteWriter::new();
    freqs.varint(u64::MAX - 1);
    freqs.varint(2);
    let bytes = A5RawCompact::new(A5_COMPACT_SHORT_DOC_ONLY, u64::MAX)
        .df(2)
        .streams(&[0, 1], freqs.as_slice(), &[])
        .encode();
    let limits = SegmentLimits::default().with_max_decoded_entries(u64::MAX);
    let mut reader =
        super::postings::PostingsReader::new_adaptive(&bytes, 2, &limits).expect("constructs");
    assert!(reader.next().expect("first").is_some());
    let error = reader.next().expect_err("sum overflow");
    a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, "frequency total overflow");

    // Legacy EOF behavior is unchanged: no trailing/sum verification is added.
    let legacy = super::postings::encode_postings_block(
        1,
        &[super::postings::Posting {
            doc_id: 0,
            freq: 1,
            occurrences: Vec::new(),
        }],
        &SegmentLimits::default(),
    )
    .expect("legacy encode");
    let mut reader = super::postings::PostingsReader::new(&legacy, 1, &SegmentLimits::default())
        .expect("legacy reader");
    assert!(reader.next().expect("posting").is_some());
    assert!(reader.next().expect("EOF").is_none());
}

#[test]
fn a5_u12_required_feature_matrix_and_extent_errors() {
    use super::format::{FEATURE_ADAPTIVE_POSTINGS, FEATURE_SPLIT_POSTINGS};
    use super::reader::SegmentReader;

    let limits = SegmentLimits::default();
    let adaptive = a5_build_current_segment(&[("a", "alpha beta"), ("b", "alpha")]);
    let title = SegmentReader::open(adaptive.clone(), limits)
        .expect("open")
        .schema()
        .field_id("title")
        .expect("title");

    // Required F opens; the postings body is compact.
    let reader = SegmentReader::open(adaptive.clone(), limits).expect("adaptive opens");
    assert!(
        reader
            .required_features()
            .contains(&(FEATURE_ADAPTIVE_POSTINGS, 1))
    );
    assert!(reader.postings(title, "alpha").expect("lookup").is_some());

    // Required F removed: compact bytes read by the legacy dispatch fail closed.
    let mut spec = A5Rebuild::default();
    spec.drop_required.push((FEATURE_ADAPTIVE_POSTINGS, 1));
    let rebuilt = a5_rebuild(&adaptive, &spec);
    let reader = SegmentReader::open(rebuilt, limits).expect("legacy dispatch opens");
    assert!(matches!(
        reader.postings(title, "alpha"),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));

    // Both families required in one segment is a conflict (never index-wide).
    let mut spec = A5Rebuild::default();
    spec.add_required.push((FEATURE_SPLIT_POSTINGS, 1));
    let rebuilt = a5_rebuild(&adaptive, &spec);
    match SegmentReader::open(rebuilt, limits) {
        Err(error) => {
            a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, "conflicting postings features")
        }
        Ok(_) => panic!("conflicting postings families must be rejected"),
    }

    // An optional F feature does not activate adaptive parsing.
    let mut spec = A5Rebuild::default();
    spec.drop_required.push((FEATURE_ADAPTIVE_POSTINGS, 1));
    spec.add_optional.push((FEATURE_ADAPTIVE_POSTINGS, 1));
    let rebuilt = a5_rebuild(&adaptive, &spec);
    let reader = SegmentReader::open(rebuilt, limits).expect("optional feature opens");
    assert!(
        !reader
            .required_features()
            .contains(&(FEATURE_ADAPTIVE_POSTINGS, 1))
    );
    assert!(
        reader
            .optional_features()
            .contains(&(FEATURE_ADAPTIVE_POSTINGS, 1))
    );
    assert!(matches!(
        reader.postings(title, "alpha"),
        Err(SegmentError::Corrupt {
            context: "occurrence kind",
            ..
        })
    ));

    // Per-segment families: an explicit A3 segment stays readable next to F.
    let a3_bytes = a3_build_segment(&[("a", "alpha beta")]);
    let a3_reader = SegmentReader::open(a3_bytes, limits).expect("A3 segment opens");
    assert!(
        a3_reader
            .required_features()
            .contains(&(FEATURE_SPLIT_POSTINGS, 1))
    );
    let a3_title = a3_reader.schema().field_id("title").expect("title");
    assert!(
        a3_reader
            .postings(a3_title, "alpha")
            .expect("lookup")
            .is_some()
    );

    // Pair absence: single missing section keeps `MissingSection`; the whole pair
    // missing uses the adaptive-specific corruption.
    for (drop, expected) in [
        (vec![SectionKind::Dictionary], Some(SectionKind::Dictionary)),
        (vec![SectionKind::Postings], Some(SectionKind::Postings)),
        (vec![SectionKind::Dictionary, SectionKind::Postings], None),
    ] {
        let spec = A5Rebuild {
            drop_sections: drop,
            ..Default::default()
        };
        let rebuilt = a5_rebuild(&adaptive, &spec);
        match SegmentReader::open(rebuilt, limits) {
            Err(SegmentError::MissingSection { kind }) => {
                assert_eq!(kind, expected.expect("single-section case") as u16);
            }
            Err(error) if expected.is_none() => a3_assert_corrupt_with(
                &error,
                A5_ADAPTIVE_CONTEXT,
                "adaptive postings feature requires dictionary and postings",
            ),
            Err(other) => panic!("unexpected error: {other:?}"),
            Ok(_) => panic!("missing pair must be rejected"),
        }
    }

    // Conflicting features with the whole pair absent reports the conflict first.
    let mut spec = A5Rebuild::default();
    spec.add_required.push((FEATURE_SPLIT_POSTINGS, 1));
    spec.drop_sections = vec![SectionKind::Dictionary, SectionKind::Postings];
    let rebuilt = a5_rebuild(&adaptive, &spec);
    match SegmentReader::open(rebuilt, limits) {
        Err(error) => {
            a3_assert_corrupt_with(&error, A5_ADAPTIVE_CONTEXT, "conflicting postings features")
        }
        Ok(_) => panic!("conflicting features must win over pair absence"),
    }

    // Dictionary doc_freq mismatch is unchanged.
    let dictionary_body = {
        let view = parse_container(&adaptive, &limits).expect("container");
        view.body(SectionKind::Dictionary)
            .expect("dictionary")
            .to_vec()
    };
    let mut patched = dictionary_body.clone();
    assert!(a3_patch_dictionary(
        &mut patched,
        "alpha",
        Some(9),
        None,
        None
    ));
    let spec = A5Rebuild {
        replace_section: Some((SectionKind::Dictionary, patched)),
        ..Default::default()
    };
    let rebuilt = a5_rebuild(&adaptive, &spec);
    let reader = SegmentReader::open(rebuilt, limits).expect("patched dictionary opens");
    match reader.postings(title, "alpha") {
        Err(error) => a3_assert_corrupt_with(
            &error,
            "postings",
            "dictionary doc_freq does not match posting count",
        ),
        Ok(_) => panic!("doc_freq mismatch must be rejected"),
    }

    // Checked extent addition and slice lookup keep their typed errors.
    for offset in [Some(u64::MAX), Some(1u64 << 40)] {
        let mut patched = dictionary_body.clone();
        assert!(a3_patch_dictionary(
            &mut patched,
            "alpha",
            None,
            offset,
            None
        ));
        let spec = A5Rebuild {
            replace_section: Some((SectionKind::Dictionary, patched)),
            ..Default::default()
        };
        let rebuilt = a5_rebuild(&adaptive, &spec);
        match SegmentReader::open(rebuilt, limits) {
            Err(SegmentError::Corrupt { context, .. }) => assert_eq!(context, "dictionary"),
            Err(other) => panic!("unexpected error: {other:?}"),
            Ok(_) => panic!("invalid extent must be rejected"),
        }
    }
    let mut patched = dictionary_body.clone();
    assert!(a3_patch_dictionary(
        &mut patched,
        "alpha",
        None,
        Some(u64::MAX),
        Some(2)
    ));
    let spec = A5Rebuild {
        replace_section: Some((SectionKind::Dictionary, patched)),
        ..Default::default()
    };
    let rebuilt = a5_rebuild(&adaptive, &spec);
    match SegmentReader::open(rebuilt, limits) {
        Err(SegmentError::Corrupt { context, .. }) => assert_eq!(context, "dictionary"),
        Err(other) => panic!("unexpected error: {other:?}"),
        Ok(_) => panic!("overflowing extent must be rejected"),
    }
}

#[test]
fn a5_u13_structural_size_table_and_determinism() {
    use super::postings::{encode_postings_block, encode_split_postings_block};

    let limits = SegmentLimits::default();
    let table = [
        (1usize, 19usize, 98usize, 8usize, 24usize, 103usize, 13usize),
        (2, 21, 100, 11, 31, 110, 21),
        (127, 271, 350, 261, 906, 985, 897),
        (128, 273, 352, 267, 913, 992, 908),
        (129, 275, 395, 395, 920, 1040, 1040),
        (257, 531, 692, 692, 1816, 1977, 1977),
    ];
    for (count, legacy_doc, a3_doc, a5_doc, legacy_pos, a3_pos, a5_pos) in table {
        let docs: Vec<u64> = (0..count as u64).collect();
        let freqs = vec![1u64; count];
        for positional in [false, true] {
            let postings = a3_postings(&docs, &freqs, positional);
            let legacy = encode_postings_block(count as u64, &postings, &limits).expect("legacy");
            let split =
                encode_split_postings_block(count as u64, &postings, &limits).expect("split");
            let adaptive = a5_encode_with(count as u64, &postings, &limits);
            let again = a5_encode_with(count as u64, &postings, &limits);
            assert_eq!(adaptive, again, "encoding is deterministic for exact input");
            let (expected_legacy, expected_a3, expected_a5) = if positional {
                (legacy_pos, a3_pos, a5_pos)
            } else {
                (legacy_doc, a3_doc, a5_doc)
            };
            assert_eq!(
                legacy.len(),
                expected_legacy,
                "count={count} positional={positional}"
            );
            assert_eq!(
                split.len(),
                expected_a3,
                "count={count} positional={positional}"
            );
            assert_eq!(
                adaptive.len(),
                expected_a5,
                "count={count} positional={positional}"
            );
            assert_eq!(a5_decode_full(&adaptive, count as u64), postings);
            if count <= 128 {
                assert!(
                    adaptive.len() < split.len(),
                    "compact must be strictly smaller at df<=128 (count={count})"
                );
            } else {
                assert_eq!(adaptive, split, "long lists are byte-identical to A3");
            }
        }
    }
}

/// Which postings family a differential case decodes through.
#[derive(Clone, Copy)]
enum A5Family {
    Legacy,
    Split,
    Adaptive,
}

fn a5_open<'a>(
    family: A5Family,
    bytes: &'a [u8],
    segment_doc_count: u64,
    limits: &SegmentLimits,
) -> Result<super::postings::PostingsReader<'a>, SegmentError> {
    match family {
        A5Family::Legacy => super::postings::PostingsReader::new(bytes, segment_doc_count, limits),
        A5Family::Split => {
            super::postings::PostingsReader::new_split(bytes, segment_doc_count, limits)
        }
        A5Family::Adaptive => {
            super::postings::PostingsReader::new_adaptive(bytes, segment_doc_count, limits)
        }
    }
}

/// Deterministic fixture generator for the differential test.
///
/// A test-local linear-congruential sequence: not a cryptographic primitive, not
/// production randomness and not a dependency.
struct A5Lcg(u64);

impl A5Lcg {
    const fn new() -> Self {
        Self(0x5045_5246_0006_A505)
    }

    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0
    }
}

#[test]
fn a5_u14_generated_differential_across_all_families() {
    use super::postings::{
        Occurrence, Posting, encode_postings_block, encode_split_postings_block,
    };

    let limits = SegmentLimits::default();
    let mut rng = A5Lcg::new();
    let counts = [1usize, 2, 3, 127, 128, 129, 256, 257];
    let bases = [0u64, 127, 128, 16_384];
    let mut ordinal = 0usize;
    for count in counts {
        for positional in [false, true] {
            for base in bases {
                ordinal += 1;
                let context = format!(
                    "seed=0x{:016X} ordinal={ordinal} count={count} positional={positional} base={base}",
                    A5Lcg::new().0
                );
                let mut postings = Vec::new();
                let mut doc_id = base;
                for _ in 0..count {
                    let freq = 1 + rng.next() % 4;
                    let occurrences = if positional {
                        let mut occurrences = Vec::new();
                        let mut position = 0u64;
                        for index in 0..freq {
                            if index > 0 {
                                position += 1 + rng.next() % 3;
                            }
                            occurrences.push(Occurrence {
                                position,
                                position_length: 1 + rng.next() % 2,
                                value_index: index / 2,
                                start_offset: 3 * index,
                                end_offset: 3 * index + 1,
                            });
                        }
                        occurrences
                    } else {
                        Vec::new()
                    };
                    postings.push(Posting {
                        doc_id,
                        freq,
                        occurrences,
                    });
                    doc_id += 1 + rng.next() % 17;
                }
                let segment_doc_count = postings.last().expect("postings").doc_id + 1;
                let lean: Vec<(u64, u64)> = postings
                    .iter()
                    .map(|posting| (posting.doc_id, posting.freq))
                    .collect();

                let legacy = encode_postings_block(segment_doc_count, &postings, &limits)
                    .unwrap_or_else(|error| panic!("{context}: legacy encode {error:?}"));
                let split = encode_split_postings_block(segment_doc_count, &postings, &limits)
                    .unwrap_or_else(|error| panic!("{context}: split encode {error:?}"));
                let adaptive = a5_encode_with(segment_doc_count, &postings, &limits);

                for (family, name, bytes) in [
                    (A5Family::Legacy, "legacy", &legacy),
                    (A5Family::Split, "split", &split),
                    (A5Family::Adaptive, "adaptive", &adaptive),
                ] {
                    let mut reader = a5_open(family, bytes, segment_doc_count, &limits)
                        .unwrap_or_else(|error| panic!("{context}: {name} open {error:?}"));
                    let mut records = Vec::new();
                    while let Some(posting) = reader
                        .next()
                        .unwrap_or_else(|error| panic!("{context}: {name} decode {error:?}"))
                    {
                        records.push(posting);
                    }
                    assert_eq!(records, postings, "{context}: {name} full records");
                    let mut lean_reader = a5_open(family, bytes, segment_doc_count, &limits)
                        .unwrap_or_else(|error| panic!("{context}: {name} open {error:?}"))
                        .into_doc_freq();
                    let mut lean_records = Vec::new();
                    while let Some(posting) = lean_reader
                        .next()
                        .unwrap_or_else(|error| panic!("{context}: {name} lean decode {error:?}"))
                    {
                        lean_records.push((posting.doc_id, posting.freq));
                    }
                    assert_eq!(lean_records, lean, "{context}: {name} lean projection");
                }
            }
        }
    }
}

#[test]
fn a5_u15_encoder_cost_witnesses() {
    use super::postings::{encode_adaptive_postings_block, encode_observation};

    let limits = SegmentLimits::default();

    // Singleton doc-only: 2*n doc/frequency widths + 4 header widths.
    encode_observation::reset();
    let postings = a3_postings(&[3], &[2], false);
    let bytes = encode_adaptive_postings_block(4, &postings, &limits).expect("encode");
    let counts = encode_observation::counts();
    assert_eq!(counts.validation_calls, 1);
    assert_eq!(counts.compact_validation_calls, 1);
    // 2 document/frequency widths + 4 header widths.
    assert_eq!(counts.width_calls, 2 + 4);
    assert_eq!(counts.compact_output_buffers, 1);
    assert!(counts.initial_capacity >= bytes.len());
    assert_eq!(
        counts.initial_capacity, counts.final_capacity,
        "the admitted output buffer never grows"
    );

    // Short positional: 2*n + 5*m widths + 5 header widths (the df field).
    encode_observation::reset();
    let postings = a3_postings(&[1, 4, 9], &[2, 1, 3], true);
    let occurrences: u64 = postings.iter().map(|posting| posting.freq).sum();
    let bytes = encode_adaptive_postings_block(10, &postings, &limits).expect("encode");
    let counts = encode_observation::counts();
    assert_eq!(counts.validation_calls, 1);
    assert_eq!(counts.compact_validation_calls, 1);
    assert_eq!(counts.width_calls, 2 * 3 + 5 * occurrences + 5);
    assert_eq!(counts.compact_output_buffers, 1);
    assert!(counts.initial_capacity >= bytes.len());
    assert_eq!(counts.initial_capacity, counts.final_capacity);

    // Long lists do zero compact work: one validation, no measurement, no buffer.
    encode_observation::reset();
    let docs: Vec<u64> = (0..129).collect();
    let postings = a3_postings(&docs, &vec![1u64; 129], true);
    let _ = encode_adaptive_postings_block(129, &postings, &limits).expect("encode");
    let counts = encode_observation::counts();
    assert_eq!(counts.validation_calls, 1);
    assert_eq!(counts.compact_validation_calls, 0);
    assert_eq!(counts.width_calls, 0);
    assert_eq!(counts.compact_output_buffers, 0);

    // A rejected admission allocates nothing.
    encode_observation::reset();
    let postings = a3_postings(&[0], &[1], false);
    let tiny = SegmentLimits::default().with_max_single_allocation(1);
    assert!(encode_adaptive_postings_block(1, &postings, &tiny).is_err());
    let counts = encode_observation::counts();
    assert_eq!(counts.compact_output_buffers, 0);
    assert_eq!(counts.initial_capacity, 0);
    assert_eq!(counts.final_capacity, 0);
}

#[test]
fn a5_u16_varint_width_and_checked_arithmetic() {
    use super::postings::encode_observation::{test_total_len, test_varint_len};

    for (value, expected) in [
        (0u64, 1u64),
        (1, 1),
        (127, 1),
        (128, 2),
        (16_383, 2),
        (16_384, 3),
        (u64::MAX, 10),
    ] {
        assert_eq!(test_varint_len(value), expected, "width of {value}");
    }

    assert_eq!(
        test_total_len(1, u64::MAX - 1, 0, 0).expect("fits"),
        u64::MAX
    );
    assert_eq!(test_total_len(0, u64::MAX, 0, 0).expect("fits"), u64::MAX);
    assert!(
        test_total_len(1, u64::MAX, 0, 0).is_err(),
        "checked sum overflow"
    );
    assert!(test_total_len(0, u64::MAX, 1, 0).is_err());
    assert!(test_total_len(0, 0, u64::MAX, 1).is_err());

    // Header width accounting on a real payload.
    let limits = SegmentLimits::default();
    let postings = a3_postings(&[0, 200], &[1, 2], true);
    let bytes =
        super::postings::encode_adaptive_postings_block(201, &postings, &limits).expect("encode");
    let (marker, version, df, freq_total, doc_len, freq_len, pos_len) = a5_header(&bytes);
    assert_eq!(
        (marker, version, df, freq_total),
        (A5_COMPACT_SHORT_POSITIONAL, 1, Some(2), 3)
    );
    let expected_header = 2
        + test_varint_len(2)
        + test_varint_len(freq_total)
        + test_varint_len(doc_len)
        + test_varint_len(freq_len)
        + test_varint_len(pos_len);
    assert_eq!(
        bytes.len() as u64,
        expected_header + doc_len + freq_len + pos_len
    );
}
