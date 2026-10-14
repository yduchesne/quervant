//! PR 10 T24–T27: fixed-width signed time buckets.

mod pr10_common;

use pr10_common::{
    AggregateGroup, AggregateMetric, AggregateRequest, FieldValue, GroupValue, MetricValue, Query,
    TimeBucket, aggregate, committed, full_doc,
};

fn bucket_request(width: i64, origin: i64) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: Vec::new(),
        time_bucket: Some(TimeBucket {
            field: "ts".into(),
            width_micros: width,
            origin_micros: origin,
        }),
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

fn bucket_starts(groups: &[AggregateGroup]) -> Vec<i64> {
    groups
        .iter()
        .map(|group| match group.components.as_slice() {
            [GroupValue::Value(FieldValue::Timestamp(timestamp))] => timestamp.as_micros(),
            other => panic!("expected one bucket component, got {other:?}"),
        })
        .collect()
}

fn aggregate_with(
    snapshot: &quervant_core::index::ReaderSnapshot,
    width: i64,
    origin: i64,
) -> quervant_core::search::SearchResult<quervant_core::search::AggregateResponse> {
    pr10_common::aggregate_with_limits(
        snapshot,
        &bucket_request(width, origin),
        quervant_core::search::SearchLimits::default(),
        &quervant_core::contract::budget::Budgets::new(),
    )
}

// T24 — signed floor division for pre-epoch buckets.
#[test]
fn t24_negative_floor_buckets() {
    let docs = vec![
        full_doc("a", "a", -1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", -10, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", -11, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = aggregate(&snapshot, &bucket_request(10, 0));
    assert_eq!(bucket_starts(&response.groups), [-20, -10]);
    assert_eq!(response.groups[0].metrics, [MetricValue::Count(1)]);
    assert_eq!(response.groups[1].metrics, [MetricValue::Count(2)]);
}

// T25 — shifted origin changes the grid.
#[test]
fn t25_shifted_origin() {
    let docs = vec![
        full_doc("a", "a", 14, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 15, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = aggregate(&snapshot, &bucket_request(10, 5));
    assert_eq!(bucket_starts(&response.groups), [5, 15]);
}

// T26 — exact half-open bucket boundary.
#[test]
fn t26_bucket_boundary() {
    let docs = vec![
        full_doc("a", "a", 9, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 10, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 19, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = aggregate(&snapshot, &bucket_request(10, 0));
    assert_eq!(bucket_starts(&response.groups), [0, 10]);
    assert_eq!(response.groups[0].metrics, [MetricValue::Count(1)]);
    assert_eq!(response.groups[1].metrics, [MetricValue::Count(2)]);
}

// T27 — zero/negative width rejected and extreme grids do not wrap.
#[test]
fn t27_zero_and_overflow_width() {
    let (_directory, index) = committed(vec![full_doc(
        "a",
        "a",
        0,
        0,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.1",
    )]);
    let snapshot = index.snapshot();
    assert!(aggregate_with(&snapshot, 0, 0).is_err());
    assert!(aggregate_with(&snapshot, -5, 0).is_err());
    // A huge width plus a pre-epoch timestamp still produces a valid i64 start.
    let response = aggregate(&snapshot, &bucket_request(i64::MAX, i64::MIN));
    assert_eq!(response.groups.len(), 1);
    let start = bucket_starts(&response.groups)[0];
    // offset = 2^63, width = 2^63-1 => floor bucket 1 => origin + width = -1.
    assert_eq!(start, -1);
}
