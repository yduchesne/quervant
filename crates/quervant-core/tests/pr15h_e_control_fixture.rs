//! PR 15H-E low-vocabulary size control fixture (ignored; invoked by the
//! benchmark controller through `cargo test --test pr15h_e_control_fixture`).
//!
//! Builds exactly one indexed `Keyword` field with 2,048 documents all carrying
//! the same term, then writes the single immutable segment bytes to the path in
//! `QUERVANT_E_CONTROL_OUT`. No index directory, manifest or other section is
//! included beyond what `SegmentBuilder` emits for that schema.

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{
    Cardinality, DocumentKey, FieldValues,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::segment::{SegmentBuilder, SegmentDocument};

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
    .expect("control schema")
}

#[test]
#[ignore = "benchmark fixture helper; run explicitly from the E controller"]
fn build_low_vocabulary_control_segment() {
    let out = std::env::var("QUERVANT_E_CONTROL_OUT")
        .expect("QUERVANT_E_CONTROL_OUT must name the output segment file");
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin())
        .expect("segment builder");
    for index in 0..2_048usize {
        let mut document =
            SegmentDocument::new(DocumentKey::new(format!("e-low-{index:08}")).unwrap());
        document
            .insert(
                "term",
                FieldValues::Single(FieldValue::Keyword("common".to_owned())),
            )
            .expect("term value");
        builder.add_document(document).expect("add document");
    }
    let built = builder.build().expect("build control segment");
    std::fs::write(&out, &built.bytes).expect("write control segment");
}
