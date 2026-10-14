//! Shared PR 10 integration-test helpers and independent oracle utilities.
#![allow(dead_code)]
#![allow(unused_imports)]

use std::collections::BTreeMap;
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
pub use quervant_core::contract::value::{FieldValue, Timestamp};
pub use quervant_core::search::{
    AggregateGroup, AggregateMetric, AggregateRequest, AggregateResponse, FrequencyTopK,
    GroupValue, MetricValue, NumericAggregate, TimeBucket, TypedCursor, TypedHit,
    TypedSearchRequest,
};

/// The PR 10 fixture schema.
pub fn pr10_schema() -> Schema {
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
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "mts",
                FieldType::Timestamp,
                Cardinality::Multi,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "mn",
                FieldType::I64,
                Cardinality::Multi,
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
                "mfl",
                FieldType::F64,
                Cardinality::Multi,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "flag",
                FieldType::Bool,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "ip",
                FieldType::IpAddress,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "point",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "nullable",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        Some("ts".into()),
    )
    .expect("pr10 schema")
}

/// The shared analyzer registry.
pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// A new in-memory directory.
pub fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

/// Create a fresh PR 10 index.
pub fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create(directory, pr10_schema(), registry()).expect("create index")
}

/// Reopen an existing PR 10 index.
pub fn reopen(directory: Arc<dyn Directory>) -> Index {
    Index::open_existing(directory, pr10_schema(), registry()).expect("reopen index")
}

/// A fresh document with only its key.
pub fn doc(key: &str) -> Document {
    Document::new(DocumentKey::new(key).unwrap())
}

/// Set a single typed value.
pub fn set(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("insert single");
}

/// Set a multi-value.
pub fn set_multi(document: &mut Document, field: &str, values: Vec<FieldValue>) {
    document
        .insert(field, FieldValues::Multi(values))
        .expect("insert multi");
}

/// Set an explicit null.
pub fn set_null(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::ExplicitNull)
        .expect("insert null");
}

/// Set an empty multi-value.
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

/// Build a fully-typed document.
#[allow(clippy::too_many_arguments)]
pub fn full_doc(
    key: &str,
    title: &str,
    ts_micros: i64,
    n: i64,
    u: u64,
    score: f64,
    flag: bool,
    host: &str,
    tags: &[&str],
    ip: &str,
) -> Document {
    let mut document = doc(key);
    if !title.is_empty() {
        set(&mut document, "title", FieldValue::Text(title.to_owned()));
    }
    set(
        &mut document,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(ts_micros)),
    );
    set(&mut document, "n", FieldValue::I64(n));
    set(&mut document, "u", FieldValue::U64(u));
    set(&mut document, "score", FieldValue::F64(score));
    set(&mut document, "flag", FieldValue::Bool(flag));
    set(&mut document, "host", FieldValue::Keyword(host.to_owned()));
    set_multi(
        &mut document,
        "tags",
        tags.iter()
            .map(|tag| FieldValue::Keyword((*tag).to_owned()))
            .collect(),
    );
    set(&mut document, "ip", FieldValue::Ip(ip.parse().expect("ip")));
    document
}

/// Commit a set of documents to a fresh index and return the directory.
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
    let reopened = reopen(Arc::clone(&directory));
    (directory, reopened)
}

/// Run a typed search with default limits.
pub fn typed_search(
    snapshot: &ReaderSnapshot,
    request: &TypedSearchRequest,
) -> TypedSearchResponse {
    let schema = pr10_schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .search(request, &Budgets::new(), &cancel)
        .expect("typed search")
}

/// Run a typed search with explicit limits.
pub fn typed_search_with_limits(
    snapshot: &ReaderSnapshot,
    request: &TypedSearchRequest,
    limits: SearchLimits,
    budgets: &Budgets,
) -> quervant_core::search::SearchResult<TypedSearchResponse> {
    let schema = pr10_schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, limits).search(request, budgets, &cancel)
}

/// Run an aggregation with default limits.
pub fn aggregate(
    snapshot: &ReaderSnapshot,
    request: &AggregateRequest,
) -> quervant_core::search::AggregateResponse {
    let schema = pr10_schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .aggregate(request, &Budgets::new(), &cancel)
        .expect("aggregate")
}

/// Run an aggregation with explicit limits.
pub fn aggregate_with_limits(
    snapshot: &ReaderSnapshot,
    request: &AggregateRequest,
    limits: SearchLimits,
    budgets: &Budgets,
) -> quervant_core::search::SearchResult<quervant_core::search::AggregateResponse> {
    let schema = pr10_schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, limits).aggregate(request, budgets, &cancel)
}

/// Hit keys in returned order.
pub fn hit_keys(response: &TypedSearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// A range query over an `I64` field.
pub fn i64_range(field: &str, lower: Option<i64>, upper: Option<i64>) -> Query {
    Query::Range {
        field: field.to_owned(),
        lower: lower.map_or(Bound::Unbounded, |value| {
            Bound::Included(FieldValue::I64(value))
        }),
        upper: upper.map_or(Bound::Unbounded, |value| {
            Bound::Included(FieldValue::I64(value))
        }),
    }
}

/// A half-open time range.
pub fn time_range(field: &str, start: i64, end: i64) -> Query {
    Query::TimeRange {
        field: field.to_owned(),
        start: Timestamp::from_micros(start),
        end: Timestamp::from_micros(end),
    }
}

/// Sort ascending on one field with default missing-last placement.
pub fn sort_asc(field: &str) -> Sort {
    Sort::new(vec![quervant_core::contract::result::SortField::new(
        field,
        quervant_core::contract::result::SortDirection::Asc,
    )])
}

/// Sort descending on one field with default missing-last placement.
pub fn sort_desc(field: &str) -> Sort {
    Sort::new(vec![quervant_core::contract::result::SortField::new(
        field,
        quervant_core::contract::result::SortDirection::Desc,
    )])
}

/// A simple MatchAll request with the given sort and page size.
pub fn match_all_request(sort: Sort, top_k: usize) -> TypedSearchRequest {
    TypedSearchRequest {
        query: Query::MatchAll,
        sort,
        top_k: TopK::new(top_k).unwrap(),
        after: None,
        primary_time_field: Some("ts".into()),
    }
}

/// One independent model document.
#[derive(Debug, Clone, PartialEq)]
pub struct ModelDocument {
    /// Logical key.
    pub key: String,
    /// Current revision (higher wins).
    pub revision: u64,
    /// Live or deleted.
    pub live: bool,
    /// Typed scalar values by field name (last write per revision).
    pub values: BTreeMap<String, FieldValue>,
}

/// An independent model index for differential oracle checks.
#[derive(Debug, Default, Clone)]
pub struct ModelIndex {
    /// key -> winning document.
    pub docs: BTreeMap<String, ModelDocument>,
}

impl ModelIndex {
    /// Insert or replace a document at `revision`.
    pub fn put(&mut self, revision: u64, key: &str, values: BTreeMap<String, FieldValue>) {
        let entry = self.docs.entry(key.to_owned()).or_insert(ModelDocument {
            key: key.to_owned(),
            revision: 0,
            live: false,
            values: BTreeMap::new(),
        });
        if revision >= entry.revision {
            entry.revision = revision;
            entry.live = true;
            entry.values = values;
        }
    }

    /// Delete a key at `revision`.
    pub fn delete(&mut self, revision: u64, key: &str) {
        let entry = self.docs.entry(key.to_owned()).or_insert(ModelDocument {
            key: key.to_owned(),
            revision: 0,
            live: false,
            values: BTreeMap::new(),
        });
        if revision >= entry.revision {
            entry.revision = revision;
            entry.live = false;
            entry.values.clear();
        }
    }

    /// Live document keys matching a simple I64 inclusive range.
    pub fn live_with_i64_range(
        &self,
        field: &str,
        lower: Option<i64>,
        upper: Option<i64>,
    ) -> Vec<String> {
        let mut keys: Vec<String> = self
            .docs
            .values()
            .filter(|document| document.live)
            .filter(|document| {
                let Some(FieldValue::I64(value)) = document.values.get(field) else {
                    return false;
                };
                lower.is_none_or(|bound| *value >= bound)
                    && upper.is_none_or(|bound| *value <= bound)
            })
            .map(|document| document.key.clone())
            .collect();
        keys.sort();
        keys
    }
}
