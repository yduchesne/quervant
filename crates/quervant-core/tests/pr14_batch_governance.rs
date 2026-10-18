//! PR 14 P2 — cumulative batch governance (focused acceptance).

mod pr14_common;

use pr14_common::*;
use quervant_core::analysis::{CancellationFlag, NeverCancel};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::error::QueryError;
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch};

fn docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    for (key, n) in [("a", 1i64), ("b", 2), ("c", 3)] {
        let mut document = doc(key);
        set(&mut document, "n", FieldValue::I64(n));
        set(&mut document, "host", FieldValue::Keyword("h".into()));
        docs.push(document);
    }
    docs
}

fn policy_with(work: u64, memory: u64, response: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16)
            .unwrap()
            .with(BudgetKind::BatchAggregate, work)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, response)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn execute(
    index: &quervant_core::index::Index,
    batch: &BatchQueryRequest,
    policy: &BudgetPolicy,
) -> quervant_core::search::SearchResult<BatchQueryResponse> {
    let snapshot = index.snapshot();
    execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        batch,
        policy,
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
}

fn zero_hit() -> QueryRequest {
    let mut query = QueryRequest::new(Query::Term {
        field: "title".into(),
        value: FieldValue::Text("nonexistent".into()),
    });
    query.top_k = TopK::new(10).unwrap();
    query
}

fn empty_projection_match_all() -> QueryRequest {
    let mut query = QueryRequest::new(Query::MatchAll);
    query.top_k = TopK::new(10).unwrap();
    query.projection = Projection::Fields(Vec::new());
    query
}

fn budget_kind(outcome: &PerQueryOutcome) -> Option<BudgetKind> {
    match outcome {
        PerQueryOutcome::Failure(QueryError::BudgetExceeded { kind }) => Some(*kind),
        _ => None,
    }
}

// B01 — zero-hit slots still charge work; both report BatchAggregate.
#[test]
fn b01_zero_hit_work_is_charged() {
    let index = committed(docs());
    let batch = BatchQueryRequest::new(vec![zero_hit(), zero_hit()], None, BatchBudget::new(4));
    let response = execute(&index, &batch, &policy_with(1, 1 << 20, 1 << 20)).unwrap();
    assert_eq!(response.len(), 2);
    assert_eq!(
        budget_kind(response.slot(0).unwrap()),
        Some(BudgetKind::BatchAggregate)
    );
    assert_eq!(
        budget_kind(response.slot(1).unwrap()),
        Some(BudgetKind::BatchAggregate)
    );
}

// B14 — response bytes are cumulative; the second slot exceeds the shared cap.
#[test]
fn b14_response_bytes_cumulative() {
    let index = committed(docs());
    let batch = BatchQueryRequest::new(
        vec![empty_projection_match_all(), empty_projection_match_all()],
        None,
        BatchBudget::new(4),
    );
    let response = execute(&index, &batch, &policy_with(1 << 20, 1 << 20, 200)).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert_eq!(
        budget_kind(response.slot(1).unwrap()),
        Some(BudgetKind::BatchResponseBytes)
    );
}

// B16 — one-over response cap rejects without emitting a partial success.
#[test]
fn b16_response_one_over_rejected() {
    let index = committed(docs());
    let batch = BatchQueryRequest::new(
        vec![empty_projection_match_all()],
        None,
        BatchBudget::new(4),
    );
    let response = execute(&index, &batch, &policy_with(1 << 20, 1 << 20, 1)).unwrap();
    assert_eq!(
        budget_kind(response.slot(0).unwrap()),
        Some(BudgetKind::BatchResponseBytes)
    );
}

// B17 — work, memory and response failures report distinct kinds.
#[test]
fn b17_distinct_budget_kinds() {
    let index = committed(docs());
    let work = execute(
        &index,
        &BatchQueryRequest::new(vec![zero_hit()], None, BatchBudget::new(4)),
        &policy_with(1, 1 << 20, 1 << 20),
    )
    .unwrap();
    assert_eq!(
        budget_kind(work.slot(0).unwrap()),
        Some(BudgetKind::BatchAggregate)
    );

    let mut source = QueryRequest::new(Query::MatchAll);
    source.top_k = TopK::new(10).unwrap();
    let memory = execute(
        &index,
        &BatchQueryRequest::new(vec![source], None, BatchBudget::new(4)),
        &policy_with(1 << 20, 1, 1 << 20),
    )
    .unwrap();
    assert_eq!(
        budget_kind(memory.slot(0).unwrap()),
        Some(BudgetKind::BatchMemoryBytes)
    );

    let response = execute(
        &index,
        &BatchQueryRequest::new(
            vec![empty_projection_match_all()],
            None,
            BatchBudget::new(4),
        ),
        &policy_with(1 << 20, 1 << 20, 1),
    )
    .unwrap();
    assert_eq!(
        budget_kind(response.slot(0).unwrap()),
        Some(BudgetKind::BatchResponseBytes)
    );
}

// B21 — a one-slot batch matches the direct unified executor.
#[test]
fn b21_one_slot_matches_direct_unified() {
    let index = committed(docs());
    let query = Query::And(vec![
        Query::Exists {
            field: "host".into(),
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(2)),
            upper: Bound::Unbounded,
        },
    ]);
    let mut request = UnifiedRequest::new(query.clone(), TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    let snapshot = index.snapshot();
    let direct = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap();

    let mut slot = QueryRequest::new(query);
    slot.top_k = TopK::new(10).unwrap();
    slot.sort = request.sort.clone();
    let batch = BatchQueryRequest::new(vec![slot], None, BatchBudget::new(4));
    let response = execute(&index, &batch, &policy_with(1 << 20, 1 << 20, 1 << 20)).unwrap();
    let PerQueryOutcome::Success(batch_response) = response.slot(0).unwrap() else {
        panic!("expected success");
    };
    assert_eq!(batch_response.total_hits, direct.total_hits);
    let direct_keys: Vec<&str> = direct.hits.iter().map(|hit| hit.key.as_str()).collect();
    let batch_keys: Vec<&str> = batch_response
        .hits
        .iter()
        .map(|hit| hit.key.as_str())
        .collect();
    assert_eq!(direct_keys, batch_keys);
}

// B19 — an above-policy ceiling rejects the envelope before any slot runs.
#[test]
fn b19_policy_rejects_whole_batch() {
    let index = committed(docs());
    let batch = BatchQueryRequest::new(
        vec![empty_projection_match_all()],
        None,
        BatchBudget::new(4).with_limits(
            Budgets::new()
                .with(BudgetKind::BatchAggregate, 100)
                .unwrap(),
        ),
    );
    // Server ceiling is lower than the requested limit.
    let error = execute(&index, &batch, &policy_with(10, 1 << 20, 1 << 20)).unwrap_err();
    assert!(matches!(
        error,
        quervant_core::search::SearchError::Query(_)
    ));
}
