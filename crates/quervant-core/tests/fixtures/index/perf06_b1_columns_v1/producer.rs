//! Frozen PERF-06-B1 fixture producer: compile only against the pinned pre-B1 source.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{CURRENT_KEY, CurrentPointer, Index, WRITER_LOCK_KEY};
use quervant_core::segment::{Manifest, SectionKind, SegmentLimits, parse_container};
use quervant_core::storage::{Directory, FsDirectory};
use sha2::Digest as _;

const SOURCE_REVISION: &str = "480a77e78c6897e05cb7ceb76b01434974b82ec6";

#[derive(Clone, Copy)]
enum City {
    Missing,
    Null,
    Value(&'static str),
}

const ROWS: [(&str, City); 18] = [
    ("a0", City::Missing),
    ("a1", City::Null),
    ("a2", City::Value("")),
    ("a3", City::Value("Austin")),
    ("a4", City::Value("Seattle")),
    ("a5", City::Value("\u{e9}")),
    ("b0", City::Value("Boston")),
    ("b1", City::Value("Dallas")),
    ("b2", City::Value("Seattle")),
    ("b3", City::Value("e\u{301}")),
    ("b4", City::Value("\0")),
    ("b5", City::Value("\u{1f600}")),
    ("c0", City::Value("Austin")),
    ("c1", City::Value("a")),
    ("c2", City::Value("aa")),
    ("c3", City::Value("Z")),
    ("c4", City::Missing),
    ("c5", City::Null),
];

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "body", FieldType::Text, Cardinality::Single, FieldOptions::indexed_stored(),
            ).with_analyzer("standard_folded"),
            FieldDefinition::new(
                "category", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
            FieldDefinition::new(
                "city", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
            FieldDefinition::new(
                "n", FieldType::I64, Cardinality::Single, FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "stored_tag", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "tags", FieldType::Keyword, Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
        ],
        None,
    ).expect("frozen schema")
}

fn city_values(city: City) -> FieldValues {
    match city {
        City::Missing => FieldValues::Absent,
        City::Null => FieldValues::ExplicitNull,
        City::Value(value) => FieldValues::Single(FieldValue::Keyword(value.to_owned())),
    }
}

fn document(position: usize) -> Document {
    let (key, city) = ROWS[position];
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
    doc.insert("body", FieldValues::Single(FieldValue::Text("common".to_owned())))
        .expect("body");
    doc.insert("category", FieldValues::Single(FieldValue::Keyword(
        ["type-a", "type-b", "type-c"][position / 6].to_owned(),
    ))).expect("category");
    doc.insert("city", city_values(city)).expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(position as i64)))
        .expect("n");
    doc.insert("stored_tag", FieldValues::Single(FieldValue::Keyword("stored".to_owned())))
        .expect("stored_tag");
    doc.insert("tags", FieldValues::Multi(vec![
        FieldValue::Keyword("one".to_owned()),
        FieldValue::Keyword("two".to_owned()),
    ])).expect("tags");
    doc
}

fn sha256(bytes: &[u8]) -> String {
    let digest = sha2::Sha256::digest(bytes);
    let mut text = String::with_capacity(64);
    for byte in digest.iter() {
        write!(text, "{byte:02x}").expect("write to String");
    }
    text
}

fn verify_fixture(root: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(root)?);
    let index = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())?;
    assert_eq!(index.generation(), Some(3));
    let snapshot = index.snapshot();
    assert_eq!(snapshot.document_count(), 18);
    assert_eq!(snapshot.segment_count(), 3);
    let expected: BTreeMap<String, FieldValues> = ROWS.iter()
        .map(|(key, city)| ((*key).to_owned(), city_values(*city)))
        .collect();
    let mut actual = BTreeMap::new();
    for segment in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(segment)?;
        let reader = guard.reader();
        assert_eq!(reader.doc_count(), 6);
        assert_eq!(reader.schema().field_id("city"), Some(2));
        assert!(!reader.required_features().iter().any(|(id, _)| *id == 0x0010));
        let container = parse_container(reader.bytes(), &SegmentLimits::default())?;
        let columns = container.body(SectionKind::Columns).expect("COLUMNS");
        assert_eq!(&columns[..2], &1u16.to_le_bytes(), "genuine baseline COLUMNS v1");
        let keys = reader.doc_keys()?;
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let value = reader.column_value(2, doc_id)?.expect("city column exists");
            assert!(actual.insert(key, value).is_none(), "unique logical key");
        }
    }
    assert_eq!(actual, expected, "complete input-derived city state/value oracle");
    assert!(!root.join(WRITER_LOCK_KEY).exists(), "no active writer lock");
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: perf06_b1_make_legacy_fixture WORK_ROOT FIXTURE_ROOT (both absent)".into());
    }
    let work_root = PathBuf::from(&args[1]);
    let fixture_root = PathBuf::from(&args[2]);
    if work_root.exists() || fixture_root.exists() {
        return Err("both destination roots must be absent; refusing overwrite".into());
    }
    std::fs::create_dir_all(&work_root)?;
    {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&work_root)?);
        let index = Index::create(directory, schema(), AnalyzerRegistry::builtin())?;
        for batch in 0..3usize {
            let mut writer = index.writer()?;
            for position in batch * 6..(batch + 1) * 6 {
                writer.insert(document(position))?;
            }
            let outcome = writer.commit()?;
            assert_eq!(outcome.generation, (batch + 1) as u64);
            assert_eq!(outcome.segments_added, 1);
        }
    }
    verify_fixture(&work_root)?;

    // Package the complete CURRENT-reachable closure, not stale generations or locks.
    let current_bytes = std::fs::read(work_root.join(CURRENT_KEY))?;
    let current = CurrentPointer::parse(&current_bytes)?;
    assert_eq!(current.generation(), 3);
    let manifest_key = current.manifest_key().as_str().to_owned();
    let manifest_bytes = std::fs::read(work_root.join(&manifest_key))?;
    assert_eq!(manifest_bytes.len() as u64, current.manifest_length());
    assert_eq!(sha256(&manifest_bytes), current.manifest_digest().to_hex());
    let manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default())?;
    assert_eq!(manifest.segments.len(), 3);
    let mut objects = BTreeSet::from([CURRENT_KEY.to_owned(), manifest_key]);
    for segment in &manifest.segments {
        objects.insert(segment.object_key.clone());
    }
    objects.insert(manifest.mutation_state.as_ref().expect("baseline mutation state").object_key.clone());
    assert_eq!(objects.len(), 6);
    std::fs::create_dir_all(&fixture_root)?;
    let mut inventory = String::from("# sha256\tbytes\trelative_path\n");
    for key in &objects {
        let bytes = std::fs::read(work_root.join(key))?;
        let destination = fixture_root.join(key);
        std::fs::create_dir_all(destination.parent().expect("object parent"))?;
        std::fs::write(&destination, &bytes)?;
        writeln!(inventory, "{}\t{}\t{}", sha256(&bytes), bytes.len(), key)?;
    }
    std::fs::write(fixture_root.join("objects.tsv"), inventory.as_bytes())?;
    verify_fixture(&fixture_root)?;
    println!("SOURCE_REVISION\t{SOURCE_REVISION}");
    println!("FIXTURE_GENERATION\t3");
    println!("FIXTURE_DOCUMENTS\t18");
    println!("FIXTURE_SEGMENTS\t3");
    println!("FIXTURE_OBJECTS\t6");
    println!("INVENTORY_SHA256\t{}", sha256(inventory.as_bytes()));
    print!("{inventory}");
    println!("PERF06_B1_LEGACY_FIXTURE_PASS");
    Ok(())
}
