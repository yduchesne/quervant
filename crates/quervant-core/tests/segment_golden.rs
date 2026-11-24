//! Checked-in golden segment fixture decoded against a hand-authored table
//! (P5-G). The expected values below are authored from the input, not derived
//! from encoder intermediates.

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, Timestamp};
use quervant_core::segment::{
    Layout, SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader,
};

const GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden.seg");

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
                "when",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
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
        Some("when".to_owned()),
    )
    .expect("schema")
}

fn doc(key: &str, when: i64, title: &str, path: &str, n: i64) -> SegmentDocument {
    let mut document = SegmentDocument::new(DocumentKey::new(key).expect("key"));
    document.fields.insert(
        "title".to_owned(),
        FieldValues::Single(FieldValue::Text(title.to_owned())),
    );
    document.fields.insert(
        "when".to_owned(),
        FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(when))),
    );
    document.fields.insert(
        "path".to_owned(),
        FieldValues::Single(FieldValue::Keyword(path.to_owned())),
    );
    document
        .fields
        .insert("n".to_owned(), FieldValues::Single(FieldValue::I64(n)));
    document
}

fn golden_segment() -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .with_layout(Layout::TimestampSorted);
    builder
        .add_document(doc("a", 2000, "Hello World", "/a", -1))
        .expect("add a");
    builder
        .add_document(doc("b", 1000, "hello there", "/b", 7))
        .expect("add b");
    builder.build().expect("build").bytes
}

#[test]
fn p5_g02_golden_decodes_expected_table() {
    let reader = SegmentReader::open(GOLDEN.to_vec(), SegmentLimits::default()).expect("open");
    assert_eq!(reader.doc_count(), 2);

    // Physical order is timestamp ascending: b(1000) then a(2000).
    let stored = reader.stored().expect("stored");
    assert_eq!(stored[0].key.as_str(), "b");
    assert_eq!(
        stored[0].get(reader.schema().field_id("title").unwrap()),
        FieldValues::Single(FieldValue::Text("hello there".to_owned()))
    );
    assert_eq!(
        stored[0].get(reader.schema().field_id("path").unwrap()),
        FieldValues::Single(FieldValue::Keyword("/b".to_owned()))
    );
    assert_eq!(
        stored[0].get(reader.schema().field_id("n").unwrap()),
        FieldValues::Single(FieldValue::I64(7))
    );
    assert_eq!(stored[1].key.as_str(), "a");
    assert_eq!(
        stored[1].get(reader.schema().field_id("title").unwrap()),
        FieldValues::Single(FieldValue::Text("Hello World".to_owned()))
    );

    // Hand-authored term dictionary for the folded title field.
    let title_id = reader.schema().field_id("title").unwrap();
    let dictionary = reader.dictionary().expect("dictionary");
    let terms: Vec<&str> = dictionary
        .field(title_id)
        .expect("title dict")
        .iter()
        .map(|entry| entry.term.as_str())
        .collect();
    assert_eq!(terms, vec!["hello", "there", "world"]);
    assert_eq!(dictionary.lookup(title_id, "hello").unwrap().doc_freq, 2);

    // Postings for "hello": docs 0 and 1 (physical), one occurrence each.
    let mut postings = reader
        .postings(title_id, "hello")
        .unwrap()
        .expect("hello postings");
    assert_eq!(postings.posting_doc_count(), 2);
    let first = postings.next().unwrap().unwrap();
    assert_eq!(first.doc_id, 0);
    let second = postings.next().unwrap().unwrap();
    assert_eq!(second.doc_id, 1);
    assert!(postings.next().unwrap().is_none());

    // Remap: physical 0 -> original 1 (b), physical 1 -> original 0 (a).
    assert_eq!(reader.remap().physical_to_original(0).unwrap(), 1);
    assert_eq!(reader.remap().physical_to_original(1).unwrap(), 0);

    // Conservative ordered time bounds.
    let bounds = reader.time_bounds().expect("time bounds");
    assert_eq!(bounds.min_micros, 1000);
    assert_eq!(bounds.max_micros, 2000);
    assert!(bounds.known && bounds.ordered);
    assert_eq!(bounds.present_count, 2);

    // Columnar keyword/i64 values are addressable by physical doc id.
    let path_id = reader.schema().field_id("path").unwrap();
    assert_eq!(
        reader.column_value(path_id, 1).unwrap(),
        Some(FieldValues::Single(FieldValue::Keyword("/a".to_owned())))
    );
}

#[test]
#[ignore = "regenerates the checked-in norms golden fixture"]
fn regenerate_golden_norms() {
    // `golden.seg` is the frozen legacy (pre-Amendment-05) fixture and must never
    // be regenerated by this builder, which now always emits field norms.
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/segment/golden_norms.seg"
    );
    std::fs::write(path, golden_segment()).expect("write norms golden");
}

/// A5-T01/T08 — the separately checked-in norms-bearing golden fixture.
#[test]
fn p5_g03_norms_golden_decodes() {
    const NORMS_GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden_norms.seg");
    // Pin the exact bytes so any accidental regeneration change is caught.
    use sha2::Digest as _;
    use std::fmt::Write as _;
    let digest_bytes = sha2::Sha256::digest(NORMS_GOLDEN);
    let mut digest = String::with_capacity(64);
    for byte in digest_bytes.iter() {
        write!(digest, "{byte:02x}").expect("string write");
    }
    assert_eq!(
        digest, "49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b",
        "regenerate with `cargo test --test segment_golden regenerate_golden_norms -- --ignored`"
    );
    let reader =
        SegmentReader::open(NORMS_GOLDEN.to_vec(), SegmentLimits::default()).expect("open norms");
    assert_eq!(reader.doc_count(), 2);
    assert!(reader.required_features().iter().any(|(id, version)| *id
        == quervant_core::segment::format::FEATURE_FIELD_NORMS
        && *version == 1));
    let norms = reader.field_norms().expect("norms present");
    let title = reader.schema().field_id("title").unwrap();
    let path = reader.schema().field_id("path").unwrap();
    // Physical order is timestamp ascending: b(1000) then a(2000).
    // title b: "hello there" -> 2 tokens; a: "Hello World" -> 2 tokens.
    assert_eq!(norms.field(title).unwrap().length(0).unwrap(), 2);
    assert_eq!(norms.field(title).unwrap().length(1).unwrap(), 2);
    assert_eq!(norms.field(path).unwrap().length(0).unwrap(), 1);
    assert_eq!(norms.field(path).unwrap().length(1).unwrap(), 1);
    assert_eq!(norms.field(title).unwrap().total_token_count(), 4);
}

/// A3-I04: the pinned legacy norms fixture and a freshly built split-postings
/// segment containing the *same two logical documents* decode identically
/// through two independent real `SegmentReader`s. This exercises the two
/// feature-dispatch branches; it does not claim a single production manifest
/// carried both formats.
#[test]
fn a3_i04_legacy_and_split_segments_share_logical_content() {
    use quervant_core::segment::format::FEATURE_SPLIT_POSTINGS;

    const NORMS_GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden_norms.seg");

    // The legacy fixture bytes and digest stay pinned.
    use sha2::Digest as _;
    use std::fmt::Write as _;
    let digest_bytes = sha2::Sha256::digest(NORMS_GOLDEN);
    let mut digest = String::with_capacity(64);
    for byte in digest_bytes.iter() {
        write!(digest, "{byte:02x}").expect("string write");
    }
    assert_eq!(
        digest, "49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b",
        "the legacy fixture must never be regenerated"
    );

    let limits = SegmentLimits::default();
    let legacy = SegmentReader::open(NORMS_GOLDEN.to_vec(), limits).expect("legacy opens");
    let fresh = SegmentReader::open(golden_segment(), limits).expect("fresh opens");

    let has_split = |reader: &SegmentReader| {
        reader
            .required_features()
            .iter()
            .any(|(id, version)| (*id, *version) == (FEATURE_SPLIT_POSTINGS, 1))
    };
    assert!(!has_split(&legacy), "pinned fixture stays legacy");
    assert!(has_split(&fresh), "new builder emits split postings");

    assert_eq!(legacy.doc_count(), fresh.doc_count());
    assert_eq!(legacy.remap(), fresh.remap());

    // Stored keys and values are identical for the same physical ordering.
    let legacy_stored = legacy.stored().expect("legacy stored");
    let fresh_stored = fresh.stored().expect("fresh stored");
    assert_eq!(legacy_stored.len(), fresh_stored.len());
    for (legacy_record, fresh_record) in legacy_stored.iter().zip(fresh_stored.iter()) {
        assert_eq!(legacy_record.key.as_str(), fresh_record.key.as_str());
        for field in ["title", "path", "when", "n"] {
            let legacy_id = legacy.schema().field_id(field).expect("legacy field");
            let fresh_id = fresh.schema().field_id(field).expect("fresh field");
            assert_eq!(legacy_id, fresh_id, "field ids must match across formats");
            assert_eq!(
                legacy_record.get(legacy_id),
                fresh_record.get(fresh_id),
                "stored field {field} differs"
            );
        }
    }

    // Field norms are identical.
    let legacy_norms = legacy.field_norms().expect("legacy norms");
    let fresh_norms = fresh.field_norms().expect("fresh norms");
    for field in ["title", "path"] {
        let legacy_id = legacy.schema().field_id(field).expect("legacy field");
        let fresh_id = fresh.schema().field_id(field).expect("fresh field");
        let legacy_field = legacy_norms.field(legacy_id).expect("legacy norms field");
        let fresh_field = fresh_norms.field(fresh_id).expect("fresh norms field");
        for physical in 0..2u64 {
            assert_eq!(
                legacy_field.length(physical).expect("length"),
                fresh_field.length(physical).expect("length"),
                "norms for {field} doc {physical}"
            );
        }
        assert_eq!(
            legacy_field.total_token_count(),
            fresh_field.total_token_count()
        );
    }

    // Every term and every posting record is logically identical.
    for field in ["title", "path"] {
        let legacy_id = legacy.schema().field_id(field).expect("legacy field");
        let fresh_id = fresh.schema().field_id(field).expect("fresh field");
        let legacy_terms = legacy
            .dictionary()
            .expect("legacy dictionary")
            .field(legacy_id)
            .expect("legacy terms");
        let fresh_terms = fresh
            .dictionary()
            .expect("fresh dictionary")
            .field(fresh_id)
            .expect("fresh terms");
        let legacy_table: Vec<(&str, u64)> = legacy_terms
            .iter()
            .map(|entry| (entry.term.as_str(), entry.doc_freq))
            .collect();
        let fresh_table: Vec<(&str, u64)> = fresh_terms
            .iter()
            .map(|entry| (entry.term.as_str(), entry.doc_freq))
            .collect();
        assert_eq!(legacy_table, fresh_table, "{field} dictionary differs");
        for (legacy_entry, fresh_entry) in legacy_terms.iter().zip(fresh_terms.iter()) {
            let mut legacy_cursor = legacy
                .postings_for_entry(legacy_entry)
                .expect("legacy postings");
            let mut fresh_cursor = fresh
                .postings_for_entry(fresh_entry)
                .expect("fresh postings");
            loop {
                match (
                    legacy_cursor.next().expect("legacy decode"),
                    fresh_cursor.next().expect("fresh decode"),
                ) {
                    (Some(left), Some(right)) => assert_eq!(
                        left, right,
                        "{field} term {:?} posting differs",
                        legacy_entry.term
                    ),
                    (None, None) => break,
                    (left, right) => panic!(
                        "{field} term {:?} posting count differs: {left:?} vs {right:?}",
                        legacy_entry.term
                    ),
                }
            }
        }
    }
}
