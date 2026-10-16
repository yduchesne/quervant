//! PR 14 phases 14A/14D: unified execution delegation and stored projections.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::{CancellationFlag, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{JsonNumber, JsonValue};
use quervant_core::search::{
    ProjectionLedger, ProjectionPlan, SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher,
    projected_hit_bytes,
};

fn unified(
    index: &quervant_core::index::Index,
    request: &UnifiedRequest,
) -> quervant_core::search::UnifiedResponse {
    let snapshot = index.snapshot();
    let schema = schema();
    UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &NeverCancel)
        .expect("unified search")
}

fn docs() -> Vec<quervant_core::contract::document::Document> {
    let mut a = doc("a");
    set(&mut a, "title", FieldValue::Text("hello world".into()));
    set(&mut a, "host", FieldValue::Keyword("h1".into()));
    set(&mut a, "n", FieldValue::I64(1));
    // Indexed but not stored: must never be projected.
    set(
        &mut a,
        "raw",
        FieldValue::Json(JsonValue::Number(JsonNumber::I64(7))),
    );
    let mut b = doc("b");
    set(&mut b, "title", FieldValue::Text("hello there".into()));
    set_null(&mut b, "host");
    set_empty(&mut b, "nullable");
    set(&mut b, "n", FieldValue::I64(2));
    let mut c = doc("c");
    set(&mut c, "title", FieldValue::Text("goodbye".into()));
    set(&mut c, "host", FieldValue::Keyword("h3".into()));
    set(&mut c, "n", FieldValue::I64(3));
    vec![a, b, c]
}

fn committed_with_directory(
    docs: Vec<quervant_core::contract::document::Document>,
) -> (
    Arc<dyn quervant_core::storage::Directory>,
    quervant_core::index::Index,
) {
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

// P01 — Projection::Source returns stored fields and never leaks unstored ones.
#[test]
fn p01_source_projection() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Source;
    let response = unified(&index, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["a", "b", "c"]);
    for hit in &response.hits {
        assert!(hit.fields.iter().all(|(name, _)| name != "raw"));
        assert!(hit.fields.iter().any(|(name, _)| name == "host"));
    }
}

// P02 — Projection::Fields preserves request order exactly.
#[test]
fn p02_field_order() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["title".into(), "host".into()]);
    let response = unified(&index, &request);
    for hit in &response.hits {
        let names: Vec<&str> = hit.fields.iter().map(|(name, _)| name.as_str()).collect();
        assert_eq!(names, ["title", "host"]);
    }
}

// P03 — five-state field vocabulary round-trips through projection.
#[test]
fn p03_five_state_preserved() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["host".into(), "nullable".into()]);
    let response = unified(&index, &request);
    let by_key = |key: &str| {
        response
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == key)
            .expect("hit")
    };
    assert_eq!(by_key("b").fields[0].1, FieldValues::ExplicitNull);
    assert_eq!(by_key("b").fields[1].1, FieldValues::Empty);
    assert_eq!(
        by_key("a").fields[0].1,
        FieldValues::Single(FieldValue::Keyword("h1".into()))
    );
    assert_eq!(by_key("a").fields[1].1, FieldValues::Absent);
}

// P04 — unstored/unknown/duplicate projection requests fail before scanning.
#[test]
fn p04_invalid_projections_rejected() {
    let schema = schema();
    assert!(ProjectionPlan::compile(&Projection::Fields(vec!["raw".into()]), &schema).is_err());
    assert!(ProjectionPlan::compile(&Projection::Fields(vec!["missing".into()]), &schema).is_err());
    assert!(
        ProjectionPlan::compile(
            &Projection::Fields(vec!["host".into(), "host".into()]),
            &schema
        )
        .is_err()
    );
}

// P05 — projection output is charged and an over-budget result fails closed.
#[test]
fn p05_projection_budget() {
    let plan = ProjectionPlan::compile(&Projection::Source, &schema()).unwrap();
    assert!(!plan.field_names().is_empty());
    let mut ledger = ProjectionLedger::new(1);
    assert!(matches!(
        ledger.reserve(projected_hit_bytes(&DocumentKey::new("a").unwrap(), &[])),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert_eq!(ledger.used(), 0);
}

// P06 — deleted documents never appear in projected responses.
#[test]
fn p06_deleted_documents_excluded() {
    let (directory, _index) = committed_with_directory(docs());
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("b").unwrap()))
            .unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory);
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = unified(&live, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["a", "c"]);
    assert_eq!(response.total_hits, 2);
}

// P07 — pure lexical unified search delegates and scores.
#[test]
fn p07_pure_lexical_delegation() {
    let index = committed(docs());
    let request = UnifiedRequest::new(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("hello".into()),
        },
        TopK::new(10).unwrap(),
    );
    let response = unified(&index, &request);
    let mut keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    keys.sort_unstable();
    assert_eq!(keys, ["a", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_some()));
    assert_eq!(response.total_hits, 2);
}

// P08 — mixed lexical+typed predicates execute exactly over the live universe.
#[test]
fn p08_mixed_predicates_execute() {
    let index = committed(docs());
    let snapshot = index.snapshot();
    let schema = schema();
    // `title` contains "hello" AND `host` is present (present includes explicit null).
    let request = UnifiedRequest::new(
        Query::And(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("hello".into()),
            },
            Query::Exists {
                field: "host".into(),
            },
        ]),
        TopK::new(10).unwrap(),
    );
    let response = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .expect("mixed search");
    let mut keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    keys.sort_unstable();
    assert_eq!(keys, ["a", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_some()));
}

// P09 — an explicit sort on a pure lexical query fails closed.
#[test]
fn p09_lexical_explicit_sort_fails_closed() {
    let index = committed(docs());
    let snapshot = index.snapshot();
    let schema = schema();
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("hello".into()),
        },
        TopK::new(10).unwrap(),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let result = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new());
    assert!(matches!(
        result,
        Err(SearchError::UnsupportedOperator {
            operator: "lexical_explicit_sort"
        })
    ));
}

// P10 — pure typed queries use the typed executor and return no score.
#[test]
fn p10_pure_typed_delegation() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(2)),
            upper: Bound::Unbounded,
        },
        TopK::new(10).unwrap(),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    let response = unified(&index, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["c", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_none()));
    assert_eq!(response.total_hits, 2);
}
