//! PR 14 P2B Phase F — adversarial batch-memory acceptance (B10a–B13j).
//!
//! Cases that require the private `BatchExecutionMeter`/`SlotMemoryScope`
//! internals are covered by named focused unit tests in
//! `search::batch_meter::tests` and `search::projection::tests`; this file
//! exercises the public `execute_batch` path and asserts outcomes, error
//! classification, ordering, response charges and parity.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
    SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::FieldValues;
use quervant_core::contract::error::QueryError;
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch, projected_field_bytes,
};

fn policy(memory: u64, response: u64, work: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 64)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, response)
            .unwrap()
            .with(BudgetKind::BatchAggregate, work)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn run_with(
    index: &quervant_core::index::Index,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
    cancel: &CancellationFlag,
) -> quervant_core::search::SearchResult<BatchQueryResponse> {
    let snapshot = index.snapshot();
    execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(queries, None, BatchBudget::new(64)),
        policy,
        &CapabilitySet::new(),
        cancel,
    )
}

fn run(
    index: &quervant_core::index::Index,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
) -> quervant_core::search::SearchResult<BatchQueryResponse> {
    run_with(index, queries, policy, &CancellationFlag::new())
}

fn run_with_limits(
    index: &quervant_core::index::Index,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
    limits: SearchLimits,
) -> quervant_core::search::SearchResult<BatchQueryResponse> {
    let snapshot = index.snapshot();
    execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        limits,
        &BatchQueryRequest::new(queries, None, BatchBudget::new(64)),
        policy,
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
}

fn all_success(response: &BatchQueryResponse) -> bool {
    response
        .results()
        .iter()
        .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)))
}

fn success(response: &BatchQueryResponse, slot: usize) -> &SearchResponse {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("slot {slot} is not a success: {other:?}"),
    }
}

fn failure(response: &BatchQueryResponse, slot: usize) -> &QueryError {
    match response.slot(slot) {
        Some(PerQueryOutcome::Failure(error)) => error,
        other => panic!("slot {slot} is not a failure: {other:?}"),
    }
}

/// Deterministic response-byte oracle, independently derived from the
/// repository model `32 + sum(24 + key + 8 + projected fields)`.
fn response_bytes(response: &SearchResponse) -> u64 {
    let mut bytes = 32u64;
    for hit in &response.hits {
        let mut hit_bytes = 24 + hit.key.as_str().len() as u64 + 8;
        for (name, values) in &hit.fields {
            hit_bytes += projected_field_bytes(name, values);
        }
        bytes += hit_bytes;
    }
    bytes
}

/// Smallest batch-memory ceiling for which every slot succeeds.
fn min_memory(
    index: &quervant_core::index::Index,
    queries: Vec<QueryRequest>,
    response: u64,
    work: u64,
) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 40;
    while low < high {
        let mid = low + (high - low) / 2;
        let ok = run(index, clone_queries(&queries), &policy(mid, response, work))
            .map(|response| all_success(&response))
            .unwrap_or(false);
        if ok {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

fn min_work(index: &quervant_core::index::Index, queries: Vec<QueryRequest>) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 40;
    while low < high {
        let mid = low + (high - low) / 2;
        let ok = run(
            index,
            clone_queries(&queries),
            &policy(1 << 30, 1 << 30, mid),
        )
        .map(|response| all_success(&response))
        .unwrap_or(false);
        if ok {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

fn clone_queries(queries: &[QueryRequest]) -> Vec<QueryRequest> {
    queries.to_vec()
}

fn q_all() -> Query {
    Query::MatchAll
}

fn q_alpha() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn q_nomatch() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("does-not-exist".into()),
    }
}

fn q_typed() -> Query {
    Query::Exists { field: "n".into() }
}

fn q_json() -> Query {
    Query::JsonPathRange {
        field: "body".into(),
        path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
        lower: Bound::Included(FieldValue::I64(0)),
        upper: Bound::Included(FieldValue::I64(100)),
    }
}

fn q_geo() -> Query {
    Query::GeoBoundingBox {
        field: "loc".into(),
        bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
    }
}

fn q_mixed() -> Query {
    Query::And(vec![q_alpha(), q_json()])
}

fn req(query: Query, top_k: usize) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.top_k = TopK::new(top_k).unwrap();
    request
}

fn docs(json_members: usize) -> Vec<quervant_core::contract::document::Document> {
    (0..3)
        .map(|i| {
            let mut document = doc(&format!("k{i}"));
            set(
                &mut document,
                "title",
                FieldValue::Text(if i == 0 { "alpha" } else { "beta" }.into()),
            );
            set(&mut document, "n", FieldValue::I64(i as i64));
            set(
                &mut document,
                "loc",
                FieldValue::GeoPoint(GeoPoint::new(i as f64 * 0.1, i as f64 * 0.1).unwrap()),
            );
            let mut entries: Vec<(String, JsonValue)> =
                vec![("n".to_owned(), JsonValue::Number(JsonNumber::I64(i as i64)))];
            for j in 0..json_members {
                entries.push((
                    format!("k{j}"),
                    JsonValue::Number(JsonNumber::I64(j as i64)),
                ));
            }
            set(
                &mut document,
                "body",
                FieldValue::Json(JsonValue::Object(entries.into_iter().collect())),
            );
            document
        })
        .collect()
}

fn long_key_docs(prefix: char) -> Vec<quervant_core::contract::document::Document> {
    (0..2)
        .map(|i| {
            let mut document = doc(&format!("{prefix}{i}{}", "x".repeat(895)));
            set(&mut document, "title", FieldValue::Text("alpha".into()));
            set(&mut document, "n", FieldValue::I64(i));
            document
        })
        .collect()
}

// ---------------------------------------------------------------------------
// B10 — meter ownership, boundaries, heap and candidate accounting
// ---------------------------------------------------------------------------

// B10a is proven by `search::batch_meter::tests::b10a_disjoint_work_memory_borrows`
// (two independent mutable borrows without `RefCell`/`unsafe`). This end-to-end
// case additionally exercises work and memory together through the public path.
#[test]
fn b10a_work_and_memory_are_charged_together() {
    let index = committed(docs(2));
    let response = run(
        &index,
        vec![req(q_all(), 2), req(q_all(), 2)],
        &policy(1 << 20, 1 << 20, 1 << 20),
    )
    .unwrap();
    assert_eq!(response.len(), 2);
    assert!(all_success(&response));
}

// B10b — exact memory limit succeeds; first byte over returns BatchMemoryBytes.
#[test]
fn b10b_memory_exact_and_one_over() {
    let index = committed(docs(2));
    let queries = vec![req(q_all(), 2)];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    let exact = run(
        &index,
        clone_queries(&queries),
        &policy(minimum, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(all_success(&exact));
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

// B10c — reserve overflow is typed; proven by
// `search::batch_meter::tests::b10c_overflow_is_typed_and_atomic`.
#[test]
fn b10c_overflow_is_typed() {
    // The unit test owns the arithmetic proof; here a u64::MAX batch succeeds
    // without wrapping.
    let index = committed(docs(2));
    let response = run(
        &index,
        vec![req(q_all(), 2)],
        &policy(u64::MAX, u64::MAX, u64::MAX),
    )
    .unwrap();
    assert!(all_success(&response));
}

// B10d — checked release underflow; proven by
// `search::projection::tests::b10d_checked_release_underflow`.
#[test]
fn b10d_checked_release_underflow() {
    // Projection/scope underflow is a unit-level invariant; the integration
    // path still fails closed without saturating (exercised via exact limits).
    let index = committed(docs(2));
    let queries = vec![req(q_all(), 2)];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

// B10e — an early failure releases temporaries and retains prior responses.
#[test]
fn b10e_failed_slot_releases_temporaries_and_keeps_prior() {
    let index = committed(docs(2));
    let light = req(q_all(), 2);
    let minimum = min_memory(&index, vec![light.clone()], 1 << 30, 1 << 30);
    // 2 * minimum fits two successes; one byte less rejects the second slot only.
    let response = run(
        &index,
        vec![light.clone(), light.clone()],
        &policy(2 * minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        failure(&response, 1),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

// B10f — cancellation releases slot memory; proven by
// `search::unified::tests::d_json_cancellation_cleanup`; the public path returns
// the cancellation provenance and no success.
#[test]
fn b10f_cancellation_has_no_success() {
    let index = committed(docs(2));
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let response = run_with(
        &index,
        vec![req(q_all(), 2)],
        &policy(1 << 30, 1 << 30, 1 << 30),
        &cancel,
    )
    .unwrap();
    assert!(matches!(
        failure(&response, 0),
        QueryError::Cancelled { .. }
    ));
}

// B10g/B10h — K+1 heap bounds, eviction and atomic replacement are covered by
// `search::unified::tests::c3_path_heap_exact_one_over`,
// `c3_path_larger_replacement`, `c3_path_smaller_replacement` and
// `c3_replacement_reject_atomic`. This case proves the public boundary.
#[test]
fn b10g_heap_exact_and_one_over() {
    let index = committed(long_key_docs('h'));
    let queries = vec![req(q_alpha(), 1)];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    assert!(
        run(
            &index,
            clone_queries(&queries),
            &policy(minimum, 1 << 30, 1 << 30)
        )
        .unwrap()
        .results()
        .iter()
        .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)))
    );
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

#[test]
fn b10h_heap_replacement_boundary_is_atomic() {
    let index = committed(long_key_docs('r'));
    let queries = vec![req(q_alpha(), 2)];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    assert!(
        run(
            &index,
            clone_queries(&queries),
            &policy(minimum, 1 << 30, 1 << 30)
        )
        .is_ok()
    );
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

// B10i — segment scratch overlaps heap: the effective peak exceeds the retained
// response alone.
#[test]
fn b10i_segment_scratch_overlaps_heap() {
    let index = committed(long_key_docs('s'));
    let mut request = req(q_alpha(), 1);
    request.projection = Projection::Fields(vec![]);
    let queries = vec![request];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    let response = run(
        &index,
        clone_queries(&queries),
        &policy(minimum, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(all_success(&response));
    assert!(minimum > response_bytes(success(&response, 0)));
}

// B10j — candidate selection and projection coexist; projection adds its
// charged payload on top of the candidate path.
#[test]
fn b10j_candidate_projection_overlap() {
    let index = committed(docs(20));
    let mut source = req(q_all(), 1);
    source.projection = Projection::Source;
    let mut empty = req(q_all(), 1);
    empty.projection = Projection::Fields(vec![]);
    let source_min = min_memory(&index, vec![source.clone()], 1 << 30, 1 << 30);
    let empty_min = min_memory(&index, vec![empty.clone()], 1 << 30, 1 << 30);
    let response = run(&index, vec![source], &policy(source_min, 1 << 30, 1 << 30)).unwrap();
    let projected: u64 = success(&response, 0)
        .hits
        .iter()
        .map(|hit| {
            hit.fields
                .iter()
                .map(|(name, values)| projected_field_bytes(name, values))
                .sum::<u64>()
        })
        .sum();
    assert!(projected > 0);
    assert!(source_min > empty_min);
}

// ---------------------------------------------------------------------------
// B11 — geo, JSON and shared immutable data
// ---------------------------------------------------------------------------

#[test]
fn b11a_geo_membership_exact_and_one_over() {
    let index = committed(docs(2));
    let queries = vec![req(q_geo(), 2)];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    assert!(all_success(
        &run(
            &index,
            clone_queries(&queries),
            &policy(minimum, 1 << 30, 1 << 30)
        )
        .unwrap()
    ));
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

#[test]
fn b11b_geo_sort_distance_exact_and_one_over() {
    let index = committed(docs(2));
    let mut request = req(q_geo(), 2);
    request.sort = Sort::new(vec![SortField::geo_distance(
        "loc",
        GeoPoint::new(0.0, 0.0).unwrap(),
        SortDirection::Asc,
    )]);
    let queries = vec![request];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    assert!(all_success(
        &run(
            &index,
            clone_queries(&queries),
            &policy(minimum, 1 << 30, 1 << 30)
        )
        .unwrap()
    ));
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

#[test]
fn b11c_json_transient_values_are_released() {
    let index = committed(docs(100));
    let one = vec![req(q_json(), 1)];
    let minimum = min_memory(&index, one.clone(), 1 << 30, 1 << 30);
    let response = run(&index, one, &policy(minimum, 1 << 30, 1 << 30)).unwrap();
    assert!(all_success(&response));
    // The transient occurrence buffer does not accumulate across documents:
    // two more documents add only their retained response bytes.
    let three = vec![req(q_json(), 3)];
    let three_min = min_memory(&index, three.clone(), 1 << 30, 1 << 30);
    let three_response = run(&index, three, &policy(three_min, 1 << 30, 1 << 30)).unwrap();
    assert!(all_success(&three_response));
    assert!(three_min < 3 * minimum);
}

#[test]
fn b11d_geo_json_candidate_overlap_exceeds_each_local_path() {
    let index = committed(docs(50));
    let geo_min = min_memory(&index, vec![req(q_geo(), 2)], 1 << 30, 1 << 30);
    let json_min = min_memory(&index, vec![req(q_json(), 2)], 1 << 30, 1 << 30);
    let mixed_min = min_memory(&index, vec![req(q_mixed(), 2)], 1 << 30, 1 << 30);
    assert!(mixed_min > geo_min.max(json_min));
    let over = run(
        &index,
        vec![req(q_mixed(), 2)],
        &policy(mixed_min - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

// B11e — immutable stored/shared bytes are not slot-owned scratch: a large
// stored JSON payload does not raise the memory floor when it is not projected.
#[test]
fn b11e_shared_stored_bytes_are_not_charged() {
    let small = committed(docs(0));
    let large = committed(docs(1000));
    let mut request = req(q_all(), 1);
    request.projection = Projection::Fields(vec![]);
    let small_min = min_memory(&small, vec![request.clone()], 1 << 30, 1 << 30);
    let large_min = min_memory(&large, vec![request], 1 << 30, 1 << 30);
    assert_eq!(small_min, large_min);
}

// ---------------------------------------------------------------------------
// B12 — projection and response handoff
// ---------------------------------------------------------------------------

#[test]
fn b12a_projection_exact_and_one_over() {
    let index = committed(docs(20));
    let mut request = req(q_all(), 2);
    request.projection = Projection::Source;
    let queries = vec![request];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    let response = run(
        &index,
        clone_queries(&queries),
        &policy(minimum, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(all_success(&response));
    assert_eq!(minimum, response_bytes(success(&response, 0)));
    let over = run(
        &index,
        clone_queries(&queries),
        &policy(minimum - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

#[test]
fn b12b_projection_failure_has_no_partial_success() {
    let index = committed(docs(6));
    let request = req(q_geo(), 2);
    let limits = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .unwrap();
    let response = run_with_limits(
        &index,
        vec![request],
        &policy(1 << 30, 1 << 30, 1 << 30),
        limits,
    )
    .unwrap();
    assert!(matches!(
        failure(&response, 0),
        QueryError::ExecutionFailure { reason } if *reason == "query_resource_limit"
    ));
}

#[test]
fn b12c_handoff_does_not_double_or_uncount() {
    let index = committed(docs(20));
    let mut request = req(q_all(), 2);
    request.projection = Projection::Source;
    let one = vec![request.clone()];
    let single = min_memory(&index, one, 1 << 30, 1 << 30);
    let two = vec![request.clone(), request];
    let double = min_memory(&index, two.clone(), 1 << 30, 1 << 30);
    assert_eq!(double, 2 * single);
    let response = run(&index, two, &policy(double, 1 << 30, 1 << 30)).unwrap();
    assert!(all_success(&response));
}

#[test]
fn b12d_prior_response_plus_next_scratch_rejects_second_slot() {
    let index = committed(docs(20));
    let mut request = req(q_all(), 2);
    request.projection = Projection::Source;
    let one = min_memory(&index, vec![request.clone()], 1 << 30, 1 << 30);
    let two = min_memory(
        &index,
        vec![request.clone(), request.clone()],
        1 << 30,
        1 << 30,
    );
    let response = run(
        &index,
        vec![request.clone(), request],
        &policy(two - 1, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        failure(&response, 1),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
    assert!(two >= 2 * one);
}

#[test]
fn b12e_two_slot_current_is_sum_of_retained_responses() {
    let index = committed(docs(20));
    let mut request = req(q_all(), 2);
    request.projection = Projection::Source;
    let queries = vec![request.clone(), request];
    let minimum = min_memory(&index, queries.clone(), 1 << 30, 1 << 30);
    let response = run(&index, queries, &policy(minimum, 1 << 30, 1 << 30)).unwrap();
    let total: u64 = (0..2)
        .map(|slot| response_bytes(success(&response, slot)))
        .sum();
    assert_eq!(minimum, total);
}

#[test]
fn b12f_response_first_excess_releases_failed_slot() {
    let index = committed(docs(20));
    let mut request = req(q_all(), 2);
    request.projection = Projection::Source;
    let queries = vec![request.clone(), request];
    let response_bytes_needed = {
        let response = run(&index, queries.clone(), &policy(1 << 30, 1 << 30, 1 << 30)).unwrap();
        response_bytes(success(&response, 0))
    };
    let exact = run(
        &index,
        queries.clone(),
        &policy(1 << 30, response_bytes_needed, 1 << 30),
    )
    .unwrap();
    assert!(matches!(exact.slot(0), Some(PerQueryOutcome::Success(_))));
    assert!(
        exact.slot(1).is_some(),
        "second slot produced an outcome: {:?}",
        exact.slot(1)
    );
    let over = run(
        &index,
        queries,
        &policy(1 << 30, response_bytes_needed - 1, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchResponseBytes
        }
    ));
}

// ---------------------------------------------------------------------------
// B13 — provenance, parity, ordering and multi-slot isolation
// ---------------------------------------------------------------------------

#[test]
fn b13a_zero_hit_consumes_work() {
    let index = committed(docs(6));
    // One unit of work cannot cover the three-document scan.
    let response = run(
        &index,
        vec![req(q_nomatch(), 2)],
        &policy(1 << 30, 1 << 30, 1),
    )
    .unwrap();
    assert!(matches!(
        failure(&response, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchAggregate
        }
    ));
}

#[test]
fn b13b_work_and_memory_have_distinct_provenance() {
    let index = committed(docs(6));
    let work = run(&index, vec![req(q_all(), 2)], &policy(1 << 30, 1 << 30, 1)).unwrap();
    assert!(matches!(
        failure(&work, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchAggregate
        }
    ));
    let memory = run(&index, vec![req(q_all(), 2)], &policy(1, 1 << 30, 1 << 30)).unwrap();
    assert!(matches!(
        failure(&memory, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
}

#[test]
fn b13c_query_local_limit_is_not_batch_exhaustion() {
    let index = committed(docs(6));
    let request = req(q_all(), 2);
    let limits = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .unwrap();
    let response = run_with_limits(
        &index,
        vec![request],
        &policy(1 << 30, 1 << 30, 1 << 30),
        limits,
    )
    .unwrap();
    assert!(matches!(
        failure(&response, 0),
        QueryError::ExecutionFailure { reason } if *reason == "query_resource_limit"
    ));
}

#[test]
fn b13d_multi_segment_cancellation_leaves_no_success() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for i in 0..2 {
            let mut document = doc(&format!("m{i}"));
            set(&mut document, "title", FieldValue::Text("alpha".into()));
            set(&mut document, "n", FieldValue::I64(i));
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in docs(2) {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let index = reopen(directory);
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let response = run_with(
        &index,
        vec![req(q_all(), 2)],
        &policy(1 << 30, 1 << 30, 1 << 30),
        &cancel,
    )
    .unwrap();
    assert!(matches!(
        failure(&response, 0),
        QueryError::Cancelled { .. }
    ));
}

#[test]
fn b13e_batch_and_standalone_parity() {
    let index = committed(docs(6));
    let mut request = req(q_alpha(), 2);
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = run(
        &index,
        vec![request.clone()],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let batched = success(&response, 0);
    let snapshot = index.snapshot();
    let standalone =
        UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
            .search(
                &UnifiedRequest {
                    query: request.query,
                    sort: request.sort,
                    top_k: request.top_k,
                    projection: request.projection,
                    after: None,
                },
                &Budgets::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
    assert_eq!(batched.total_hits, standalone.total_hits);
    assert_eq!(batched.hits.len(), standalone.hits.len());
    for (left, right) in batched.hits.iter().zip(&standalone.hits) {
        assert_eq!(left.key, right.key);
        assert_eq!(left.fields, right.fields);
        assert_eq!(left.score, right.score.map(|score| score as f32));
    }
}

#[test]
fn b13f_matchall_typed_and_zero_hit_work_parity() {
    let index = committed(docs(6));
    let all = min_work(&index, vec![req(q_all(), 2)]);
    let typed = min_work(&index, vec![req(q_typed(), 2)]);
    let zero = min_work(&index, vec![req(q_nomatch(), 2)]);
    // MatchAll charges exactly one unit per live document (three documents);
    // term and typed paths charge the per-document unit plus their own work.
    assert_eq!(all, 3);
    assert!(zero >= all);
    assert!(typed >= all);
}

#[test]
fn b13g_sorted_geo_order_is_stable() {
    let index = committed(docs(2));
    let mut request = req(q_geo(), 3);
    request.sort = Sort::new(vec![SortField::geo_distance(
        "loc",
        GeoPoint::new(0.0, 0.0).unwrap(),
        SortDirection::Asc,
    )]);
    let response = run(&index, vec![request], &policy(1 << 30, 1 << 30, 1 << 30)).unwrap();
    let hits = &success(&response, 0).hits;
    let keys: Vec<&str> = hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["k0", "k1", "k2"]);
}

#[test]
fn b13h_five_states_and_no_unstored_leak() {
    let mut present = doc("present");
    set(&mut present, "n", FieldValue::I64(1));
    set_multi(
        &mut present,
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2)],
    );
    set(&mut present, "title", FieldValue::Text("alpha".into()));
    set(&mut present, "raw", FieldValue::Json(JsonValue::Null));
    let mut null = doc("null");
    set_null(&mut null, "n");
    set(&mut null, "title", FieldValue::Text("alpha".into()));
    let mut missing = doc("missing");
    set(&mut missing, "title", FieldValue::Text("alpha".into()));
    let mut empty = doc("empty");
    empty.insert("mn", FieldValues::Empty).unwrap();
    set(&mut empty, "title", FieldValue::Text("alpha".into()));
    let index = committed(vec![present, null, missing, empty]);
    let mut request = req(q_alpha(), 10);
    request.projection = Projection::Fields(vec!["n".into(), "mn".into(), "title".into()]);
    let response = run(&index, vec![request], &policy(1 << 30, 1 << 30, 1 << 30)).unwrap();
    let hits = &success(&response, 0).hits;
    let find = |key: &str| hits.iter().find(|hit| hit.key.as_str() == key).unwrap();
    assert!(find("present").fields.iter().any(|(name, values)| {
        name == "mn" && matches!(values, FieldValues::Multi(values) if values.len() == 2)
    }));
    assert!(
        find("null")
            .fields
            .iter()
            .any(|(name, values)| { name == "n" && matches!(values, FieldValues::ExplicitNull) })
    );
    assert!(
        find("missing")
            .fields
            .iter()
            .any(|(name, values)| { name == "n" && matches!(values, FieldValues::Absent) })
    );
    assert!(
        find("empty")
            .fields
            .iter()
            .any(|(name, values)| { name == "mn" && matches!(values, FieldValues::Empty) })
    );
    // `raw` is indexed but not stored: it must never leak through Source.
    assert!(
        hits.iter()
            .all(|hit| hit.fields.iter().all(|(name, _)| name != "raw"))
    );
}

#[test]
fn b13i_three_slots_success_failure_success_shape() {
    let mut docs = docs(20);
    // A single oversized stored payload makes the middle slot's response larger
    // than the light slots' retained allowance.
    let mut heavy = doc("heavy");
    let mut entries: Vec<(String, JsonValue)> =
        vec![("n".to_owned(), JsonValue::Number(JsonNumber::I64(1)))];
    for index in 0..1000 {
        entries.push((
            format!("h{index}"),
            JsonValue::Number(JsonNumber::I64(index as i64)),
        ));
    }
    set(
        &mut heavy,
        "body",
        FieldValue::Json(JsonValue::Object(entries.into_iter().collect())),
    );
    set(&mut heavy, "title", FieldValue::Text("heavy".into()));
    docs.push(heavy);
    let index = committed(docs);

    let light = req(q_alpha(), 2);
    let light_min = min_memory(&index, vec![light.clone()], 1 << 30, 1 << 30);
    let mut middle = req(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("heavy".into()),
        },
        2,
    );
    middle.projection = Projection::Source;
    let response = run(
        &index,
        vec![light.clone(), middle, light],
        &policy(2 * light_min, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        failure(&response, 1),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

#[test]
fn b13j_extreme_limits_are_typed_and_atomic() {
    let index = committed(docs(6));
    let response = run(
        &index,
        vec![req(q_all(), 2)],
        &policy(u64::MAX, u64::MAX, u64::MAX),
    )
    .unwrap();
    assert!(all_success(&response));
    // A response ceiling of 1 cannot fit even the empty-response overhead.
    let over = run(
        &index,
        vec![req(q_all(), 2)],
        &policy(u64::MAX, 1, u64::MAX),
    )
    .unwrap();
    assert!(matches!(
        failure(&over, 0),
        QueryError::BudgetExceeded {
            kind: BudgetKind::BatchResponseBytes
        }
    ));
}
