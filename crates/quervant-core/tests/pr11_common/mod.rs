//! Shared PR 11 integration-test helpers and independent JSON reference oracle.
#![allow(dead_code)]
#![allow(unused_imports)]

use std::collections::BTreeMap;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::result::{Sort, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, TypedSearchRequest, TypedSearcher};
use quervant_core::storage::{Directory, MemoryDirectory};

/// The PR 11 fixture schema.
pub fn pr11_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
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
                "mbody",
                FieldType::Json,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "stored_only",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "indexed_only",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
        ],
        Some("ts".into()),
    )
    .expect("pr11 schema")
}

/// The shared analyzer registry.
pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// A fresh in-memory directory.
pub fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

/// Create a fresh PR 11 index.
pub fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create(directory, pr11_schema(), registry()).expect("create index")
}

/// Reopen an existing PR 11 index.
pub fn reopen(directory: Arc<dyn Directory>) -> Index {
    Index::open_existing(directory, pr11_schema(), registry()).expect("reopen index")
}

/// An empty document with a timestamp.
pub fn doc(key: &str, ts: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "ts",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(ts))),
        )
        .unwrap();
    document
}

/// Set a single JSON value on the `body` field.
pub fn set_body(document: &mut Document, value: JsonValue) {
    document
        .insert("body", FieldValues::Single(FieldValue::Json(value)))
        .unwrap();
}

/// Set the `body` field to an absent state.
pub fn clear_body(document: &mut Document) {
    document.insert("body", FieldValues::Absent).unwrap();
}

/// Set the `body` field to an explicit null.
pub fn set_body_explicit_null(document: &mut Document) {
    document.insert("body", FieldValues::ExplicitNull).unwrap();
}

/// Set the `mbody` field to a zero-element multi-value.
pub fn set_mbody_empty(document: &mut Document) {
    document.insert("mbody", FieldValues::Empty).unwrap();
}

/// Set a single JSON value on the `mbody` multi field.
pub fn set_mbody(document: &mut Document, values: Vec<JsonValue>) {
    document
        .insert(
            "mbody",
            FieldValues::Multi(values.into_iter().map(FieldValue::Json).collect::<Vec<_>>()),
        )
        .unwrap();
}

/// Set the indexed-only JSON field.
pub fn set_indexed_only(document: &mut Document, value: JsonValue) {
    document
        .insert("indexed_only", FieldValues::Single(FieldValue::Json(value)))
        .unwrap();
}

/// Set the stored-only JSON field.
pub fn set_stored_only(document: &mut Document, value: JsonValue) {
    document
        .insert("stored_only", FieldValues::Single(FieldValue::Json(value)))
        .unwrap();
}

/// Build, insert and commit a set of documents; return a reopened index.
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

/// Insert documents into an existing index and commit.
pub fn insert_commit(index: &Index, docs: Vec<Document>) {
    let mut writer = index.writer().unwrap();
    for document in docs {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
}

/// A JSON-path existence query.
pub fn exists(field: &str, path: &str) -> Query {
    Query::JsonPathExists {
        field: field.to_owned(),
        path: JsonPathExpr::parse(path).expect("json path"),
    }
}

/// A JSON-path equality query.
pub fn equals(field: &str, path: &str, value: FieldValue) -> Query {
    Query::JsonPathEquals {
        field: field.to_owned(),
        path: JsonPathExpr::parse(path).expect("json path"),
        value,
    }
}

/// Run one typed search with default limits, expecting success.
pub fn search(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let schema = pr11_schema();
    let cancel = CancellationFlag::new();
    let request = TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(1000).unwrap(),
        after: None,
        primary_time_field: None,
    };
    let response = TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel)
        .expect("typed search");
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// Run one typed search, returning the typed result.
pub fn try_search(
    snapshot: &ReaderSnapshot,
    query: Query,
    limits: SearchLimits,
    budgets: &Budgets,
) -> quervant_core::search::SearchResult<quervant_core::search::TypedSearchResponse> {
    let schema = pr11_schema();
    let cancel = CancellationFlag::new();
    let request = TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(1000).unwrap(),
        after: None,
        primary_time_field: None,
    };
    TypedSearcher::new(snapshot, &schema, limits).search(&request, budgets, &cancel)
}

/// Run one typed search with a cancellation flag.
pub fn search_cancel(
    snapshot: &ReaderSnapshot,
    query: Query,
    cancel: &CancellationFlag,
) -> quervant_core::search::SearchResult<quervant_core::search::TypedSearchResponse> {
    let schema = pr11_schema();
    let request = TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(1000).unwrap(),
        after: None,
        primary_time_field: None,
    };
    TypedSearcher::new(snapshot, &schema, SearchLimits::default()).search(
        &request,
        &Budgets::new(),
        cancel,
    )
}

/// Convenience JSON constructors.
pub fn obj(entries: &[(&str, JsonValue)]) -> JsonValue {
    JsonValue::Object(
        entries
            .iter()
            .map(|(key, value)| ((*key).to_owned(), value.clone()))
            .collect(),
    )
}

/// A signed JSON integer.
pub fn i64_value(value: i64) -> JsonValue {
    JsonValue::Number(JsonNumber::I64(value))
}

/// An unsigned JSON integer.
pub fn u64_value(value: u64) -> JsonValue {
    JsonValue::Number(JsonNumber::U64(value))
}

/// A finite JSON float.
pub fn f64_value(value: f64) -> JsonValue {
    JsonValue::Number(JsonNumber::F64(value))
}

/// A JSON string.
pub fn str_value(value: &str) -> JsonValue {
    JsonValue::String(value.to_owned())
}

/// A JSON boolean.
pub fn bool_value(value: bool) -> JsonValue {
    JsonValue::Bool(value)
}

/// A JSON array.
pub fn array(values: Vec<JsonValue>) -> JsonValue {
    JsonValue::Array(values)
}

// ---------------------------------------------------------------------------
// Independent test-only reference evaluator
// ---------------------------------------------------------------------------

/// A wildcard-free or wildcard pattern compiled from a `JsonPathExpr`.
#[derive(Debug, Clone, PartialEq)]
pub enum RefSegment {
    /// Object member.
    Member(String),
    /// Array index.
    Index(usize),
    /// One array level.
    Wildcard,
}

/// Compile an expression into reference segments.
pub fn compile_ref(path: &JsonPathExpr) -> Vec<RefSegment> {
    path.segments()
        .iter()
        .map(|segment| match segment {
            quervant_core::contract::query::JsonPathSegment::Member(member) => {
                RefSegment::Member(member.clone())
            }
            quervant_core::contract::query::JsonPathSegment::Index(index) => {
                RefSegment::Index(*index)
            }
            quervant_core::contract::query::JsonPathSegment::Wildcard => RefSegment::Wildcard,
        })
        .collect()
}

/// Whether one reference pattern matches a concrete path of `(member/index)`.
pub fn ref_path_matches(pattern: &[RefSegment], path: &[RefComponent]) -> bool {
    if pattern.len() != path.len() {
        return false;
    }
    pattern
        .iter()
        .zip(path)
        .all(|(pattern, component)| match (pattern, component) {
            (RefSegment::Member(member), RefComponent::Member(candidate)) => member == candidate,
            (RefSegment::Index(index), RefComponent::Index(candidate)) => index == candidate,
            (RefSegment::Wildcard, RefComponent::Index(_)) => true,
            _ => false,
        })
}

/// Whether one concrete reference pattern equals a concrete path.
pub fn ref_path_equals(pattern: &[RefSegment], path: &[RefComponent]) -> bool {
    if pattern.len() != path.len() {
        return false;
    }
    pattern
        .iter()
        .zip(path)
        .all(|(pattern, component)| match (pattern, component) {
            (RefSegment::Member(member), RefComponent::Member(candidate)) => member == candidate,
            (RefSegment::Index(index), RefComponent::Index(candidate)) => index == candidate,
            _ => false,
        })
}

/// A concrete reference path component.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RefComponent {
    /// Object member.
    Member(String),
    /// Array index (including the virtual multi-root index).
    Index(usize),
}

/// A reference JSON node.
#[derive(Debug, Clone, PartialEq)]
pub enum RefNode {
    /// Null.
    Null,
    /// Boolean.
    Bool(bool),
    /// Signed integer.
    I64(i64),
    /// Unsigned integer.
    U64(u64),
    /// Float with normalized zero.
    F64(f64),
    /// String bytes.
    String(String),
    /// Array.
    Array,
    /// Object.
    Object,
}

/// A reference node occurrence.
#[derive(Debug, Clone, PartialEq)]
pub struct RefOccurrence {
    /// Concrete path from the root.
    pub path: Vec<RefComponent>,
    /// Node value.
    pub node: RefNode,
}

/// Walk one JSON value into reference occurrences, deepest-last pre-order.
pub fn reference_occurrences(value: &JsonValue) -> Vec<RefOccurrence> {
    let mut out = Vec::new();
    walk_ref(value, &mut Vec::new(), &mut out);
    out
}

fn walk_ref(value: &JsonValue, path: &mut Vec<RefComponent>, out: &mut Vec<RefOccurrence>) {
    let node = match value {
        JsonValue::Null => RefNode::Null,
        JsonValue::Bool(flag) => RefNode::Bool(*flag),
        JsonValue::Number(JsonNumber::I64(number)) => RefNode::I64(*number),
        JsonValue::Number(JsonNumber::U64(number)) => RefNode::U64(*number),
        JsonValue::Number(JsonNumber::F64(number)) => {
            RefNode::F64(if *number == 0.0 { 0.0 } else { *number })
        }
        JsonValue::String(text) => RefNode::String(text.clone()),
        JsonValue::Array(_) => RefNode::Array,
        JsonValue::Object(_) => RefNode::Object,
    };
    out.push(RefOccurrence {
        path: path.clone(),
        node,
    });
    match value {
        JsonValue::Array(values) => {
            for (index, child) in values.iter().enumerate() {
                path.push(RefComponent::Index(index));
                walk_ref(child, path, out);
                path.pop();
            }
        }
        JsonValue::Object(entries) => {
            for (key, child) in entries {
                path.push(RefComponent::Member(key.clone()));
                walk_ref(child, path, out);
                path.pop();
            }
        }
        _ => {}
    }
}

/// A compiled reference predicate.
#[derive(Debug, Clone, PartialEq)]
pub enum RefPredicate {
    /// Existential path.
    Exists {
        /// Pattern.
        pattern: Vec<RefSegment>,
    },
    /// Concrete scalar equality.
    Equals {
        /// Concrete pattern.
        pattern: Vec<RefSegment>,
        /// Scalar to compare.
        scalar: RefScalar,
    },
    /// Boolean AND.
    And(Vec<RefPredicate>),
    /// Boolean OR.
    Or(Vec<RefPredicate>),
    /// Boolean NOT.
    Not(Box<RefPredicate>),
}

/// A reference scalar.
#[derive(Debug, Clone, PartialEq)]
pub enum RefScalar {
    /// Boolean.
    Bool(bool),
    /// Signed integer.
    I64(i64),
    /// Unsigned integer.
    U64(u64),
    /// Float.
    F64(f64),
    /// String bytes.
    String(Vec<u8>),
}

impl RefScalar {
    /// Map an accepted RHS value.
    pub fn from_value(value: &FieldValue) -> Option<Self> {
        match value {
            FieldValue::Bool(flag) => Some(Self::Bool(*flag)),
            FieldValue::I64(number) => Some(Self::I64(*number)),
            FieldValue::U64(number) => Some(Self::U64(*number)),
            FieldValue::F64(number) => Some(Self::F64(if *number == 0.0 { 0.0 } else { *number })),
            FieldValue::Text(text) | FieldValue::Keyword(text) => {
                Some(Self::String(text.as_bytes().to_vec()))
            }
            _ => None,
        }
    }
}

/// Evaluate a reference predicate over one document's `body` JSON value.
pub fn reference_eval(value: Option<&JsonValue>, predicate: &RefPredicate) -> bool {
    let occurrences = value.map(reference_occurrences).unwrap_or_default();
    match predicate {
        RefPredicate::Exists { pattern } => occurrences
            .iter()
            .any(|occurrence| ref_path_matches(pattern, &occurrence.path)),
        RefPredicate::Equals { pattern, scalar } => occurrences.iter().any(|occurrence| {
            ref_path_equals(pattern, &occurrence.path)
                && ref_scalar_matches(&occurrence.node, scalar)
        }),
        RefPredicate::And(predicates) => predicates
            .iter()
            .all(|predicate| reference_eval(value, predicate)),
        RefPredicate::Or(predicates) => predicates
            .iter()
            .any(|predicate| reference_eval(value, predicate)),
        RefPredicate::Not(inner) => !reference_eval(value, inner),
    }
}

fn ref_scalar_matches(node: &RefNode, scalar: &RefScalar) -> bool {
    match (node, scalar) {
        (RefNode::Bool(a), RefScalar::Bool(b)) => a == b,
        (RefNode::I64(a), RefScalar::I64(b)) => a == b,
        (RefNode::U64(a), RefScalar::U64(b)) => a == b,
        (RefNode::F64(a), RefScalar::F64(b)) => *a == *b,
        (RefNode::String(a), RefScalar::String(b)) => a.as_bytes() == b.as_slice(),
        _ => false,
    }
}
