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
#[ignore = "regenerates the checked-in golden fixture"]
fn regenerate_golden() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/segment/golden.seg"
    );
    std::fs::write(path, golden_segment()).expect("write golden");
}
