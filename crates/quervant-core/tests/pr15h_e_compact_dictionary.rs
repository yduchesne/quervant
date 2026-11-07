//! PR 15H-E producer/reader feature-gate integration tests.

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::segment::dictionary::{DictionaryEntry, encode_dictionary};
use quervant_core::segment::format::{
    ContainerBuilder, ContainerKind, FEATURE_BASELINE, FEATURE_COMPACT_DICTIONARY, SectionKind,
    parse_container,
};
use quervant_core::segment::{SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader};

const COMPACT: (u16, u16) = (FEATURE_COMPACT_DICTIONARY, 1);

fn schema() -> Schema {
    Schema::new(
        vec![FieldDefinition::new(
            "term",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )],
        None,
    )
    .unwrap()
}

fn segment() -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
    for (index, term) in ["alpha", "beta", "gamma"].iter().enumerate() {
        let mut document = SegmentDocument::new(DocumentKey::new(format!("k{index}")).unwrap());
        document
            .insert(
                "term",
                FieldValues::Single(FieldValue::Keyword((*term).to_owned())),
            )
            .unwrap();
        builder.add_document(document).unwrap();
    }
    builder.build().unwrap().bytes
}

fn rebuild(bytes: &[u8], dictionary: Option<Vec<u8>>, features: &[(u16, u16)]) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in features {
        if (*id, *version) != (FEATURE_BASELINE, 1) {
            builder.require_feature(*id, *version);
        }
    }
    for section in view.sections() {
        if section.kind == SectionKind::Dictionary {
            if let Some(body) = &dictionary {
                builder.section(
                    SectionKind::Dictionary,
                    section.flags,
                    section.aux,
                    body.clone(),
                );
            }
        } else {
            builder.section(
                section.kind,
                section.flags,
                section.aux,
                view.body(section.kind).unwrap().to_vec(),
            );
        }
    }
    builder.build().unwrap()
}

fn entries(bytes: &[u8]) -> Vec<DictionaryEntry> {
    let reader = SegmentReader::open(bytes.to_vec(), SegmentLimits::default()).unwrap();
    reader
        .dictionary()
        .unwrap()
        .fields()
        .iter()
        .flat_map(|(_, entries)| entries.iter().cloned())
        .collect()
}

/// E-U23/E-U07: SegmentBuilder emits v2 + required feature, minor 0.
#[test]
fn e_u23_producer_emits_v2_feature() {
    let bytes = segment();
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    assert!(view.required_features().contains(&COMPACT));
    assert_eq!(&bytes[10..12], &[0, 0]);
    let dictionary = view.body(SectionKind::Dictionary).unwrap();
    assert_eq!(u16::from_le_bytes([dictionary[0], dictionary[1]]), 2);
    let reader = SegmentReader::open(bytes.clone(), limits).unwrap();
    assert!(reader.dictionary().is_some());
    assert_eq!(entries(&bytes).len(), 3);
}

/// E-U06/E-U09: valid v1 without feature passes; mismatches are corruption.
#[test]
fn e_u06_u09_feature_payload_matrix() {
    let bytes = segment();
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    let v2_body = view.body(SectionKind::Dictionary).unwrap().to_vec();
    let v1_body = encode_dictionary(
        &[(
            view.required_features()
                .iter()
                .find(|(id, _)| *id == FEATURE_BASELINE)
                .map(|_| 0u32)
                .unwrap(),
            entries(&bytes),
        )],
        &limits,
    )
    .unwrap();
    let mut features: Vec<(u16, u16)> = view
        .required_features()
        .iter()
        .copied()
        .filter(|pair| *pair != COMPACT)
        .collect();

    // v1 without feature is valid and decodes the same entries.
    let v1 = rebuild(&bytes, Some(v1_body), &features);
    assert!(SegmentReader::open(v1.clone(), limits).is_ok());
    assert_eq!(entries(&v1), entries(&bytes));

    // v2 without the compact feature is corruption.
    assert!(SegmentReader::open(rebuild(&bytes, Some(v2_body), &features), limits).is_err());

    // v1 with the compact feature is corruption.
    features.push(COMPACT);
    assert!(SegmentReader::open(rebuild(&bytes, Some(v1.clone()), &features), limits).is_err());

    // feature without a dictionary is corruption.
    assert!(SegmentReader::open(rebuild(&bytes, None, &features), limits).is_err());

    // Unknown required feature is rejected.
    let mut unknown = features.clone();
    unknown.push((0xFFF0, 1));
    assert!(SegmentReader::open(rebuild(&bytes, Some(v1), &unknown), limits).is_err());
}

/// E-U26: an empty segment has neither Dictionary nor the compact feature.
#[test]
fn e_u26_empty_segment_has_no_compact_feature() {
    let bytes = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
        .unwrap()
        .build()
        .unwrap()
        .bytes;
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    assert!(view.body(SectionKind::Dictionary).is_none());
    assert!(!view.required_features().contains(&COMPACT));
    assert!(SegmentReader::open(bytes, limits).is_ok());
}
