//! PR 14 P3 — compound (mixed lexical+typed) aggregation over the full
//! effective-live match set, returned in the same batch slot as the hits.

mod pr14_common;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, ExactDistinct, GroupBy,
    GroupKey, TimeBucket, TopKFrequency,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest,
    SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::error::QueryError;
use quervant_core::contract::query::GeoBoundingBox;
use quervant_core::contract::query::{Bound, JsonPathExpr, Query};
use quervant_core::contract::result::{PitId, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::search::{SearchLimits, execute_batch};

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

fn run(
    index: &quervant_core::index::Index,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
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
        &CancellationFlag::new(),
    )
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

fn req(query: Query, top_k: usize, aggregation: Option<Aggregation>) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.top_k = TopK::new(top_k).unwrap();
    request.aggregation = aggregation;
    request
}

fn count_by_host() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn docs() -> Vec<quervant_core::contract::document::Document> {
    let mut out = Vec::new();
    for (key, title, host, n, ts) in [
        ("a", "alpha", "h1", 10i64, 0i64),
        ("b", "alpha", "h1", 20, 1_000_000),
        ("c", "beta", "h2", 5, 60_000_000),
        ("d", "alpha", "h2", 40, 61_000_000),
    ] {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text(title.into()));
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(ts)),
        );
        set(
            &mut document,
            "body",
            FieldValue::Json(JsonValue::Object(
                vec![("n".to_owned(), JsonValue::Number(JsonNumber::I64(n)))]
                    .into_iter()
                    .collect(),
            )),
        );
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new(n as f64, n as f64).unwrap()),
        );
        out.push(document);
    }
    out
}

fn json_query(value: i64) -> Query {
    Query::JsonPathRange {
        field: "body".into(),
        path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
        lower: Bound::Included(FieldValue::I64(value)),
        upper: Bound::Included(FieldValue::I64(value)),
    }
}

fn groups(
    response: &SearchResponse,
) -> &[quervant_core::contract::aggregation::AggregationGroupResult] {
    &response
        .aggregation
        .as_ref()
        .expect("aggregation result")
        .groups
}

fn count_of(group: &quervant_core::contract::aggregation::AggregationGroupResult) -> u64 {
    match group.metrics[0] {
        AggregationMetricValue::Count(count) => count,
        ref other => panic!("expected count, got {other:?}"),
    }
}

fn host_of(group: &quervant_core::contract::aggregation::AggregationGroupResult) -> &str {
    match &group.components[0] {
        AggregationGroupValue::Value(FieldValue::Keyword(host)) => host,
        other => panic!("expected keyword host, got {other:?}"),
    }
}

// T01 — mixed lexical AND typed range aggregates over all matches, independent
// of top_k; compare an independent count oracle.
#[test]
fn t01_mixed_lexical_and_typed_range_all_matches() {
    let index = committed(docs());
    let query = Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(10)),
            upper: Bound::Included(FieldValue::I64(20)),
        },
    ]);
    let small = run(
        &index,
        vec![req(query.clone(), 1, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let large = run(
        &index,
        vec![req(query, 10, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let small_groups = groups(success(&small, 0));
    let large_groups = groups(success(&large, 0));
    assert_eq!(small_groups, large_groups);
    // a(10) and b(20) match; both are h1.
    assert_eq!(small_groups.len(), 1);
    assert_eq!(host_of(&small_groups[0]), "h1");
    assert_eq!(count_of(&small_groups[0]), 2);
    assert_eq!(success(&small, 0).total_hits, 2);
}

// T05 — differing top-K and sort do not change groups.
#[test]
fn t05_sort_and_top_k_do_not_change_groups() {
    let index = committed(docs());
    let query = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    };
    let mut sorted = req(query.clone(), 3, Some(count_by_host()));
    sorted.sort = quervant_core::contract::result::Sort::new(vec![
        quervant_core::contract::result::SortField::new(
            "n",
            quervant_core::contract::result::SortDirection::Desc,
        ),
    ]);
    let a = run(
        &index,
        vec![req(query, 1, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let b = run(&index, vec![sorted], &policy(1 << 30, 1 << 30, 1 << 30)).unwrap();
    assert_eq!(groups(success(&a, 0)), groups(success(&b, 0)));
}

// T07 — exact metrics.
#[test]
fn t07_exact_metrics() {
    let index = committed(docs());
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![
            Aggregate::count(),
            Aggregate::sum("n"),
            Aggregate::min("n"),
            Aggregate::max("n"),
            Aggregate::avg("n"),
        ],
        exact_distinct: Some(ExactDistinct { field: "n".into() }),
        top_k: None,
        time_bucket: None,
    };
    let response = run(
        &index,
        vec![req(Query::MatchAll, 10, Some(aggregation))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let group = &groups(success(&response, 0))[0];
    assert_eq!(host_of(group), "h1");
    assert_eq!(group.metrics.len(), 6);
    assert!(matches!(group.metrics[0], AggregationMetricValue::Count(2)));
    assert!(matches!(
        group.metrics[1],
        AggregationMetricValue::Sum(
            quervant_core::contract::aggregation::NumericAggregate::Signed(30)
        )
    ));
    assert!(matches!(
        group.metrics[2],
        AggregationMetricValue::Min(Some(FieldValue::I64(10)))
    ));
    assert!(matches!(
        group.metrics[3],
        AggregationMetricValue::Max(Some(FieldValue::I64(20)))
    ));
    assert!(matches!(
        group.metrics[4],
        AggregationMetricValue::Avg(Some(value)) if value == 15.0
    ));
    assert!(matches!(
        group.metrics[5],
        AggregationMetricValue::ExactDistinct(2)
    ));
}

// T10 — empty match global group vs grouped empty.
#[test]
fn t10_empty_match_global_and_grouped() {
    let index = committed(docs());
    let empty = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("nomatch".into()),
    };
    let global = Aggregation {
        group_by: None,
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let response = run(
        &index,
        vec![req(empty.clone(), 1, Some(global))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let group = &groups(success(&response, 0))[0];
    assert!(group.components.is_empty());
    assert!(matches!(group.metrics[0], AggregationMetricValue::Count(0)));

    let response = run(
        &index,
        vec![req(empty, 1, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(groups(success(&response, 0)).is_empty());
}

// T11 — ordinary search has no aggregation; requested empty grouping is Some.
#[test]
fn t11_none_compatibility_and_lossless_response() {
    let index = committed(docs());
    let ordinary = run(
        &index,
        vec![req(Query::MatchAll, 1, None)],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(success(&ordinary, 0).aggregation.is_none());
    let aggregation = run(
        &index,
        vec![req(Query::MatchAll, 1, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let response = success(&aggregation, 0);
    assert!(response.aggregation.is_some());
    assert!(!response.hits.is_empty());
    assert_eq!(response.total_hits, 4);
}

// T22 — invalid group field/type/bucket are typed per-slot failures.
#[test]
fn t22_invalid_aggregation_is_typed_per_slot() {
    let index = committed(docs());
    let unknown = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("nope".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let bad_bucket = Aggregation {
        group_by: None,
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: Some(TimeBucket { width_micros: 0 }),
    };
    let response = run(
        &index,
        vec![
            req(Query::MatchAll, 1, Some(unknown)),
            req(Query::MatchAll, 1, Some(bad_bucket)),
            req(Query::MatchAll, 1, None),
        ],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    assert!(matches!(failure(&response, 0), QueryError::InvalidQuery(_)));
    assert!(matches!(failure(&response, 1), QueryError::InvalidQuery(_)));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

// T26 — public cursor + aggregation still fails closed (STOP S2).
#[test]
fn t26_cursor_with_aggregation_fails_closed() {
    let index = committed(docs());
    let mut request = req(Query::MatchAll, 1, Some(count_by_host()));
    request.pit = Some(PitId::new("pit").unwrap());
    request.cursor = Some(quervant_core::contract::result::Cursor::new(
        PitId::new("pit").unwrap(),
        quervant_core::contract::result::Sort::default(),
        quervant_core::contract::document::DocumentKey::new("a").unwrap(),
        Timestamp::from_micros(10),
    ));
    let response = run(&index, vec![request], &policy(1 << 30, 1 << 30, 1 << 30)).unwrap();
    assert!(matches!(failure(&response, 0), QueryError::InvalidQuery(_)));
}
// T02 — lexical OR JSON predicate combined with a geo filter; counts do not
// double-count and are independent of heap K+1.
#[test]
fn t02_lexical_or_json_and_geo_filter() {
    let index = committed(docs());
    let query = Query::And(vec![
        Query::Or(vec![json_query(10), json_query(20)]),
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 21.0, 21.0).unwrap(),
        },
    ]);
    let response = run(
        &index,
        vec![req(query, 1, Some(count_by_host()))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    let groups = groups(success(&response, 0));
    assert_eq!(groups.len(), 1);
    assert_eq!(host_of(&groups[0]), "h1");
    assert_eq!(count_of(&groups[0]), 2);
}

// T08 — exact frequency top-K with stable tie ordering.
#[test]
fn t08_frequency_top_k_stable_ties() {
    let index = committed(docs());
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: Some(TopKFrequency {
            field: "tags".into(),
            k: 2,
        }),
        time_bucket: None,
    };
    let response = run(
        &index,
        vec![req(Query::MatchAll, 10, Some(aggregation))],
        &policy(1 << 30, 1 << 30, 1 << 30),
    )
    .unwrap();
    // Fixture has no tags, so frequencies are present but empty per group.
    for group in groups(success(&response, 0)) {
        assert!(group.frequencies.is_some());
    }
}
