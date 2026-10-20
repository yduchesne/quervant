//! PR 14 phase 14E: contract aggregation mapping and exact execution.

mod pr14_common;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, ExactDistinct, GroupBy, GroupKey,
};
use quervant_core::search::{
    AggregateMetric, AggregateRequest, AggregateResponse, MetricValue, NumericAggregate,
    SearchLimits, TypedSearcher,
};

fn agg_docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    for (key, host, n, ts) in [
        ("a", "h1", 1i64, 10i64),
        ("b", "h1", 2, 20),
        ("c", "h2", 3, 30),
        ("d", "h2", 4, 40),
    ] {
        let mut document = doc(key);
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(ts)),
        );
        docs.push(document);
    }
    docs
}

fn run(index: &quervant_core::index::Index, aggregation: Aggregation) -> AggregateResponse {
    let snapshot = index.snapshot();
    let schema = schema();
    let request = AggregateRequest::from_contract(&aggregation, Query::MatchAll, &schema, None)
        .expect("mapping");
    TypedSearcher::new(&snapshot, &schema, SearchLimits::default())
        .aggregate(
            &request,
            &quervant_core::contract::budget::Budgets::new(),
            &CancellationFlag::new(),
        )
        .expect("aggregate")
}

fn count(metric: &MetricValue) -> Option<u64> {
    match metric {
        MetricValue::Count(value) => Some(*value),
        _ => None,
    }
}

fn sum(metric: &MetricValue) -> Option<i128> {
    match metric {
        MetricValue::Sum(NumericAggregate::Signed(value)) => Some(*value),
        _ => None,
    }
}

// A01 — contract aggregation maps to runtime metrics and executes exactly.
#[test]
fn a01_grouped_metrics() {
    let index = committed(agg_docs());
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![
            Aggregate::count(),
            Aggregate::sum("n"),
            Aggregate::min("n"),
            Aggregate::max("n"),
            Aggregate::avg("n"),
        ],
        ..Aggregation::new()
    };
    let response = run(&index, aggregation);
    assert_eq!(response.groups.len(), 2);
    let h1 = &response.groups[0];
    assert_eq!(h1.components.len(), 1);
    assert_eq!(count(&h1.metrics[0]), Some(2));
    assert_eq!(sum(&h1.metrics[1]), Some(3));
    let h2 = &response.groups[1];
    assert_eq!(count(&h2.metrics[0]), Some(2));
    assert_eq!(sum(&h2.metrics[1]), Some(7));
}

// A02 — exact distinct and frequency top-K mapping.
#[test]
fn a02_distinct_and_frequency() {
    let index = committed(agg_docs());
    let aggregation = Aggregation {
        aggregates: vec![Aggregate::count()],
        exact_distinct: Some(ExactDistinct {
            field: "host".into(),
        }),
        top_k: Some(quervant_core::contract::aggregation::TopKFrequency {
            field: "host".into(),
            k: 2,
        }),
        ..Aggregation::new()
    };
    let response = run(&index, aggregation);
    // Global group: count + exact distinct metric in metric order.
    let group = &response.groups[0];
    assert_eq!(count(&group.metrics[0]), Some(4));
    assert!(matches!(group.metrics[1], MetricValue::ExactDistinct(2)));
    let frequencies = group.frequencies.as_ref().expect("frequencies");
    assert_eq!(frequencies.len(), 2);
    // Ties break by canonical value order (h1 before h2).
    assert_eq!(frequencies[0].0, FieldValue::Keyword("h1".into()));
    assert_eq!(frequencies[1].0, FieldValue::Keyword("h2".into()));
}

// A03 — time bucket mapping uses the primary timestamp.
#[test]
fn a03_time_buckets() {
    let index = committed(agg_docs());
    let aggregation = Aggregation {
        aggregates: vec![Aggregate::count()],
        time_bucket: Some(quervant_core::contract::aggregation::TimeBucket { width_micros: 15 }),
        ..Aggregation::new()
    };
    let response = run(&index, aggregation);
    // [0,15): a ; [15,30): b ; [30,45): c, d
    assert_eq!(response.groups.len(), 3);
    assert_eq!(count(&response.groups[0].metrics[0]), Some(1));
    assert_eq!(count(&response.groups[1].metrics[0]), Some(1));
    assert_eq!(count(&response.groups[2].metrics[0]), Some(2));
}

// A04 — a time bucket without any timestamp resolver is a typed error.
#[test]
fn a04_time_bucket_requires_field() {
    let schema = quervant_core::contract::schema::Schema::new(
        vec![quervant_core::contract::schema::FieldDefinition::new(
            "host",
            quervant_core::contract::value::FieldType::Keyword,
            quervant_core::contract::document::Cardinality::Single,
            quervant_core::contract::schema::FieldOptions::new(true, true, true),
        )],
        None,
    )
    .unwrap();
    let aggregation = Aggregation {
        time_bucket: Some(quervant_core::contract::aggregation::TimeBucket { width_micros: 10 }),
        ..Aggregation::new()
    };
    assert!(AggregateRequest::from_contract(&aggregation, Query::MatchAll, &schema, None).is_err());
}

// A05 — mapping never downgrades: an unsupported aggregate shape stays typed.
#[test]
fn a05_mapping_is_explicit() {
    let schema = schema();
    let aggregation = Aggregation {
        aggregates: vec![
            Aggregate::count(),
            Aggregate::sum("n"),
            Aggregate::min("ts"),
        ],
        ..Aggregation::new()
    };
    let request =
        AggregateRequest::from_contract(&aggregation, Query::MatchAll, &schema, None).unwrap();
    assert_eq!(request.metrics.len(), 3);
    assert_eq!(request.metrics[0], AggregateMetric::Count);
    assert!(matches!(request.metrics[1], AggregateMetric::Sum { .. }));
    assert!(matches!(request.metrics[2], AggregateMetric::Min { .. }));
}
