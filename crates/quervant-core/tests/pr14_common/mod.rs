//! Shared PR 14 integration-test helpers, fixture schema and independent oracle.
#![allow(dead_code)]
#![allow(unused_imports)]

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::FieldType;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, TypedSearchResponse, TypedSearcher};
use quervant_core::storage::{Directory, MemoryDirectory};

pub use quervant_core::contract::query::{Bound, Query};
pub use quervant_core::contract::result::{
    MissingValuePosition, MultiValueSelector, Sort, SortDirection, SortField, TopK,
};
pub use quervant_core::contract::value::{FieldValue, IpNetwork, Timestamp};
pub use quervant_core::search::{TypedHit, TypedSearchRequest};

/// The shared PR 14 fixture schema: lexical, typed, JSON, IP and geo fields.
pub fn schema() -> Schema {
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
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "raw",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "mbody",
                FieldType::Json,
                Cardinality::Multi,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "mn",
                FieldType::I64,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
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
                "nullable",
                FieldType::I64,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "mloc",
                FieldType::GeoPoint,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "score",
                FieldType::F64,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        Some("ts".into()),
    )
    .expect("pr14 schema")
}

pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

pub fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

pub fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create(directory, schema(), registry()).expect("create index")
}

pub fn reopen(directory: Arc<dyn Directory>) -> Index {
    Index::open_existing(directory, schema(), registry()).expect("reopen index")
}

pub fn doc(key: &str) -> Document {
    Document::new(DocumentKey::new(key).unwrap())
}

pub fn set(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("insert single");
}

pub fn set_multi(document: &mut Document, field: &str, values: Vec<FieldValue>) {
    document
        .insert(field, FieldValues::Multi(values))
        .expect("insert multi");
}

pub fn set_null(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::ExplicitNull)
        .expect("insert null");
}

pub fn set_empty(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::Empty)
        .expect("insert empty");
}

/// Rebuild a document without one field, for absent-field cases.
pub fn without_field(document: &mut Document, field: &str) {
    let mut replacement = Document::new(document.key().clone());
    for (name, values) in document.fields() {
        if name != field {
            replacement.insert(name, values.clone()).unwrap();
        }
    }
    *document = replacement;
}

/// Commit a set of documents to a fresh index and return the reopened index.
pub fn committed(docs: Vec<Document>) -> Index {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in docs {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    reopen(directory)
}

/// Run a typed search with default limits and panic on error.
pub fn typed_search(
    snapshot: &ReaderSnapshot,
    request: &TypedSearchRequest,
) -> TypedSearchResponse {
    typed_search_result(snapshot, request).expect("typed search")
}

/// Run a typed search with default limits, returning the result.
pub fn typed_search_result(
    snapshot: &ReaderSnapshot,
    request: &TypedSearchRequest,
) -> quervant_core::search::SearchResult<TypedSearchResponse> {
    let schema = schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, SearchLimits::default()).search(
        request,
        &Budgets::new(),
        &cancel,
    )
}

/// Hit keys in returned order.
pub fn hit_keys(response: &TypedSearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// A top-level request over `query` with an empty sort and a wide page.
pub fn request(query: Query) -> TypedSearchRequest {
    TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(50).unwrap(),
        after: None,
        primary_time_field: None,
    }
}

/// Present, non-null scalar values for one field of an independent document.
#[derive(Debug, Clone, PartialEq)]
pub enum State {
    Absent,
    Null,
    Empty,
    Single(FieldValue),
    Multi(Vec<FieldValue>),
}

impl State {
    pub fn values(&self) -> Vec<FieldValue> {
        match self {
            Self::Single(value) => vec![value.clone()],
            Self::Multi(values) => values.clone(),
            Self::Absent | Self::Null | Self::Empty => Vec::new(),
        }
    }

    pub fn exists(&self) -> bool {
        !matches!(self, Self::Absent)
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Self::Null)
    }
}
