//! PR 14 phase 14E: ordered serial batch execution.

mod pr14_common;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::FieldValues;
use quervant_core::contract::result::{PitId, TopK};
use quervant_core::search::{SearchError, SearchLimits, execute_batch};

fn batch_docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    for (key, ip, n) in [
        ("a", "192.0.2.1", 1i64),
        ("b", "192.0.2.2", 2),
        ("c", "192.0.2.3", 3),
    ] {
        let mut document = doc(key);
        set(&mut document, "ip", FieldValue::Ip(ip.parse().unwrap()));
        set(&mut document, "n", FieldValue::I64(n));
        docs.push(document);
    }
    docs
}

fn policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 64)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 20)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn execute(
    index: &quervant_core::index::Index,
    batch: &BatchQueryRequest,
    cancel: &CancellationFlag,
) -> quervant_core::search::SearchResult<BatchQueryResponse> {
    let snapshot = index.snapshot();
    execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        batch,
        &policy(),
        &CapabilitySet::new(),
        cancel,
    )
}

fn match_all() -> QueryRequest {
    let mut request = QueryRequest::new(Query::MatchAll);
    request.top_k = TopK::new(10).unwrap();
    request
}

// B01 — a single accepted slot produces exactly one success.
#[test]
fn b01_single_slot() {
    let index = committed(batch_docs());
    let batch = BatchQueryRequest::new(vec![match_all()], None, BatchBudget::new(4));
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert_eq!(response.len(), 1);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
}

// B02 — ordered slots preserve position across mixed outcomes.
#[test]
fn b02_ordered_mixed_outcomes() {
    let index = committed(batch_docs());
    let mut bad = QueryRequest::new(Query::Term {
        field: "missing".into(),
        value: FieldValue::Text("x".into()),
    });
    bad.top_k = TopK::new(10).unwrap();
    let batch = BatchQueryRequest::new(
        vec![match_all(), bad, match_all()],
        None,
        BatchBudget::new(4),
    );
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

// B03 — an empty envelope is rejected as a whole.
#[test]
fn b03_empty_envelope() {
    let index = committed(batch_docs());
    let batch = BatchQueryRequest::new(vec![], None, BatchBudget::new(4));
    assert!(execute(&index, &batch, &CancellationFlag::new()).is_err());
}

// B04 — exceeding the envelope count is rejected as a whole.
#[test]
fn b04_too_many_queries() {
    let index = committed(batch_docs());
    let batch = BatchQueryRequest::new(
        vec![match_all(), match_all(), match_all()],
        None,
        BatchBudget::new(2),
    );
    assert!(execute(&index, &batch, &CancellationFlag::new()).is_err());
}

// B05 — a conflicting shared PIT rejects the whole envelope.
#[test]
fn b05_conflicting_pit() {
    let index = committed(batch_docs());
    let shared = PitId::new("shared").unwrap();
    let mut query = match_all();
    query.pit = Some(PitId::new("other").unwrap());
    let batch = BatchQueryRequest::new(vec![query], Some(shared), BatchBudget::new(4));
    assert!(execute(&index, &batch, &CancellationFlag::new()).is_err());
}

// B06 — BatchAggregate meters actual work, not hit count.
#[test]
fn b06_work_is_not_hit_count() {
    let index = committed(batch_docs());
    // Zero-hit query: work is still charged, so a 1-unit work ceiling fails.
    let mut zero_hit = QueryRequest::new(Query::Term {
        field: "title".into(),
        value: FieldValue::Text("nonexistent".into()),
    });
    zero_hit.top_k = TopK::new(10).unwrap();
    let limits = Budgets::new().with(BudgetKind::BatchAggregate, 1).unwrap();
    let batch = BatchQueryRequest::new(
        vec![zero_hit],
        None,
        BatchBudget::new(4).with_limits(limits),
    );
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(
            quervant_core::contract::error::QueryError::BudgetExceeded {
                kind: BudgetKind::BatchAggregate
            }
        ))
    ));
}

// B07 — cancellation preserves one failure slot per input query.
#[test]
fn b07_cancellation_preserves_cardinality() {
    let index = committed(batch_docs());
    let batch = BatchQueryRequest::new(vec![match_all(), match_all()], None, BatchBudget::new(4));
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let response = execute(&index, &batch, &cancel).unwrap();
    assert_eq!(response.len(), 2);
    assert!(
        response
            .results()
            .iter()
            .all(|outcome| matches!(outcome, PerQueryOutcome::Failure(_)))
    );
}

// B08 — an aggregation slot fails per-slot without erasing siblings.
#[test]
fn b08_aggregation_slot_isolated() {
    let index = committed(batch_docs());
    let mut aggregation = match_all();
    aggregation.aggregation = Some(quervant_core::contract::aggregation::Aggregation::new());
    let batch = BatchQueryRequest::new(
        vec![match_all(), aggregation, match_all()],
        None,
        BatchBudget::new(4),
    );
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

// B09 — a cursor slot fails closed rather than resuming incorrectly.
#[test]
fn b09_cursor_slot_fails_closed() {
    let index = committed(batch_docs());
    let mut with_cursor = match_all();
    with_cursor.pit = Some(PitId::new("pit").unwrap());
    with_cursor.cursor = Some(quervant_core::contract::result::Cursor::new(
        PitId::new("pit").unwrap(),
        Sort::default(),
        quervant_core::contract::document::DocumentKey::new("a").unwrap(),
        Timestamp::from_micros(10),
    ));
    let batch = BatchQueryRequest::new(vec![with_cursor], None, BatchBudget::new(4));
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(_))
    ));
}

// B11 — batch hits preserve explicit-null and empty-multi states.
#[test]
fn b11_lossless_field_states() {
    let mut a = doc("a");
    set(&mut a, "host", FieldValue::Keyword("h".into()));
    let mut b = doc("b");
    set_null(&mut b, "host");
    set_empty(&mut b, "nullable");
    let index = committed(vec![a, b]);
    let mut request = match_all();
    request.sort = Sort::new(vec![quervant_core::contract::result::SortField::new(
        "host",
        quervant_core::contract::result::SortDirection::Asc,
    )]);
    request.projection =
        quervant_core::contract::result::Projection::Fields(vec!["host".into(), "nullable".into()]);
    let batch = BatchQueryRequest::new(vec![request], None, BatchBudget::new(4));
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    let PerQueryOutcome::Success(search) = response.slot(0).unwrap() else {
        panic!("expected success");
    };
    let b_hit = search
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "b")
        .expect("b");
    assert_eq!(b_hit.fields[0].1, FieldValues::ExplicitNull);
    assert_eq!(b_hit.fields[1].1, FieldValues::Empty);
}

// B13 — an unsupported per-slot capability fails that slot only.
#[test]
fn b13_capability_rejection_is_isolated() {
    let index = committed(batch_docs());
    let mut requiring = match_all();
    requiring.capabilities.required = vec![quervant_core::contract::capability::Capability::new(
        "experimental",
        1,
    )];
    let batch = BatchQueryRequest::new(
        vec![match_all(), requiring, match_all()],
        None,
        BatchBudget::new(4),
    );
    let response = execute(&index, &batch, &CancellationFlag::new()).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

// B10 — over-budget envelope limits are typed errors, not silent clamps.
#[test]
fn b10_invalid_aggregate_kind() {
    let index = committed(batch_docs());
    let limits = Budgets::new().with(BudgetKind::ResultWindow, 1).unwrap();
    let batch = BatchQueryRequest::new(
        vec![match_all()],
        None,
        BatchBudget::new(4).with_limits(limits),
    );
    assert!(matches!(
        execute(&index, &batch, &CancellationFlag::new()),
        Err(SearchError::Query(_))
    ));
}
