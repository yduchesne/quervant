//! PR 10 T33–T37: exact count/sum/min/max/avg arithmetic policy.

mod pr10_common;

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, MetricValue, NumericAggregate, Query, Timestamp,
    committed, full_doc, set_multi, set_null, without_field,
};

fn metric_request(metrics: Vec<AggregateMetric>) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: Vec::new(),
        time_bucket: None,
        metrics,
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

fn metric(response: &quervant_core::search::AggregateResponse, index: usize) -> MetricValue {
    response.groups[0].metrics[index].clone()
}

// T33 — Count is per document while Sum counts every contributing value.
#[test]
fn t33_count_documents_vs_sum_values() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2), FieldValue::I64(3)],
    );
    let mut b = full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_multi(&mut b, "mn", vec![FieldValue::I64(4)]);
    let (_directory, index) = committed(vec![a, b]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(
        &snapshot,
        &metric_request(vec![
            AggregateMetric::Count,
            AggregateMetric::Sum { field: "mn".into() },
        ]),
    );
    assert_eq!(metric(&response, 0), MetricValue::Count(2));
    assert_eq!(
        metric(&response, 1),
        MetricValue::Sum(NumericAggregate::Signed(10))
    );
}

// T34 — integer sums widen to i128/u128 instead of wrapping at i64/u64.
#[test]
fn t34_integer_sums_widen() {
    let docs = vec![
        full_doc(
            "a",
            "a",
            1,
            i64::MAX,
            u64::MAX,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ),
        full_doc(
            "b",
            "b",
            1,
            i64::MAX,
            u64::MAX,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.2",
        ),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(
        &snapshot,
        &metric_request(vec![
            AggregateMetric::Sum { field: "n".into() },
            AggregateMetric::Sum { field: "u".into() },
        ]),
    );
    assert_eq!(
        metric(&response, 0),
        MetricValue::Sum(NumericAggregate::Signed(i128::from(i64::MAX) * 2))
    );
    assert_eq!(
        metric(&response, 1),
        MetricValue::Sum(NumericAggregate::Unsigned(u128::from(u64::MAX) * 2))
    );
}

// T35 — float sums use Neumaier compensation and reject non-finite results.
#[test]
fn t35_float_compensation() {
    let mut a = full_doc("a", "a", 1, 0, 0, 0.0, true, "h", &["x"], "10.0.0.1");
    let values: Vec<FieldValue> = (0..10_000).map(|_| FieldValue::F64(0.1)).collect();
    set_multi(&mut a, "mfl", values);
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(
        &snapshot,
        &metric_request(vec![AggregateMetric::Sum {
            field: "mfl".into(),
        }]),
    );
    let MetricValue::Sum(NumericAggregate::Float(total)) = metric(&response, 0) else {
        panic!("expected float sum");
    };
    assert!((total - 1_000.0).abs() < 1e-9, "compensated total {total}");
}

// T36 — Min/Max over timestamps.
#[test]
fn t36_timestamp_min_max() {
    let docs = vec![
        full_doc("a", "a", 50, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 10, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 90, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(
        &snapshot,
        &metric_request(vec![
            AggregateMetric::Min { field: "ts".into() },
            AggregateMetric::Max { field: "ts".into() },
        ]),
    );
    assert_eq!(
        metric(&response, 0),
        MetricValue::Min(Some(FieldValue::Timestamp(Timestamp::from_micros(10))))
    );
    assert_eq!(
        metric(&response, 1),
        MetricValue::Max(Some(FieldValue::Timestamp(Timestamp::from_micros(90))))
    );
}

// T37 — empty averages are `None`; null and missing do not contribute.
#[test]
fn t37_empty_average() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    without_field(&mut a, "score");
    let mut b = full_doc("b", "b", 1, 0, 0, 2.0, true, "h", &["x"], "10.0.0.2");
    set_null(&mut b, "score");
    let (_directory, index) = committed(vec![a, b]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(
        &snapshot,
        &metric_request(vec![AggregateMetric::Avg {
            field: "score".into(),
        }]),
    );
    assert_eq!(metric(&response, 0), MetricValue::Avg(None));
}
