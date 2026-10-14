//! Shared PR 9 integration-test helpers.
#![allow(dead_code)]

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory, ReadHandle, StorageKey};

/// The PR 9 fixture schema: a stored text field, an indexed-but-not-stored
/// text field, a columnar keyword field and a columnar integer field.
pub fn pr09_schema() -> Schema {
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
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tag",
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
        None,
    )
    .expect("pr09 schema")
}

/// The shared PR 9 analyzer registry.
pub fn pr09_registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// A new in-memory directory.
pub fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

/// Create a fresh PR 9 index.
pub fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create(directory, pr09_schema(), pr09_registry()).expect("create index")
}

/// Build one fixture document.
pub fn doc(key: &str, title: &str, body: &str, tag: &str, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    if !title.is_empty() {
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text(title.to_owned())),
            )
            .unwrap();
    }
    if !body.is_empty() {
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(body.to_owned())),
            )
            .unwrap();
    }
    document
        .insert(
            "tag",
            FieldValues::Single(FieldValue::Keyword(tag.to_owned())),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    document
}

/// Search a snapshot with default limits and top-K 20.
pub fn search(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    let schema = pr09_schema();
    let registry = pr09_registry();
    let cancel = CancellationFlag::new();
    LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
        .search(query, TopK::new(20).unwrap(), &Budgets::new(), &cancel)
        .expect("search")
}

/// Sorted hit keys for a query.
pub fn hit_keys(snapshot: &ReaderSnapshot, query: &Query) -> Vec<String> {
    let mut keys: Vec<String> = search(snapshot, query)
        .hits
        .into_iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

/// The `title:value` term query used throughout.
pub fn term(value: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(value.to_owned()),
    }
}

/// Read a whole file through the read-only handle seam.
pub fn read_file(directory: &Arc<dyn Directory>, key: &str) -> Vec<u8> {
    let key = StorageKey::parse(key).expect("storage key");
    let handle: Box<dyn ReadHandle> = directory.open_read(&key).expect("open read");
    let mut buf = vec![0u8; handle.len() as usize];
    let mut filled = 0usize;
    while filled < buf.len() {
        let read = handle.read_at(filled as u64, &mut buf[filled..]).unwrap();
        if read == 0 {
            break;
        }
        filled += read;
    }
    buf.truncate(filled);
    buf
}

/// Commit one order of documents to a fresh index and return the directory.
pub fn committed(docs: Vec<Document>) -> (Arc<dyn Directory>, Index) {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in docs {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    (directory, index)
}
