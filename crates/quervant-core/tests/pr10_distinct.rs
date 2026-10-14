//! PR 10 T38–T42: exact distinct counts, per-document uniqueness and bounds.

mod pr10_common;

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, MetricValue, Query, committed, doc, full_doc,
    set, set_multi,
};

fn distinct_request(field: &str, group_fields: Vec<&str>) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: group_fields.into_iter().map(str::to_owned).collect(),
        time_bucket: None,
        metrics: vec![AggregateMetric::ExactDistinct {
            field: field.to_owned(),
        }],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

fn distinct_metric(response: &quervant_core::search::AggregateResponse, index: usize) -> u64 {
    match response.groups[index].metrics.as_slice() {
        [MetricValue::ExactDistinct(count)] => *count,
        other => panic!("expected distinct metric, got {other:?}"),
    }
}

// T38 — distinct counts span every segment in the snapshot.
#[test]
fn t38_distinct_across_segments() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(std::sync::Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    // Batch 1 -> segment A.
    writer
        .insert(full_doc(
            "a",
            "a",
            1,
            0,
            0,
            1.0,
            true,
            "h1",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer.commit().unwrap();
    // Batch 2 -> segment B.
    writer
        .insert(full_doc(
            "b",
            "b",
            2,
            0,
            0,
            1.0,
            true,
            "h2",
            &["x"],
            "10.0.0.2",
        ))
        .unwrap();
    writer
        .insert(full_doc(
            "c",
            "c",
            3,
            0,
            0,
            1.0,
            true,
            "h1",
            &["x"],
            "10.0.0.3",
        ))
        .unwrap();
    writer.commit().unwrap();
    drop(writer);
    let reopened = pr10_common::reopen(directory);
    let snapshot = reopened.snapshot();
    assert!(snapshot.segment_count() >= 2);
    let response = pr10_common::aggregate(&snapshot, &distinct_request("host", vec![]));
    assert_eq!(distinct_metric(&response, 0), 2);
}

// T39 — duplicate values within one multi-value count once.
#[test]
fn t39_duplicate_multi_counts_once() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "mn",
        vec![
            FieldValue::I64(1),
            FieldValue::I64(1),
            FieldValue::I64(2),
            FieldValue::I64(2),
        ],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &distinct_request("mn", vec![]));
    assert_eq!(distinct_metric(&response, 0), 2);
}

// T40 — exceeding the per-group distinct budget is a typed error, not truncation.
#[test]
fn t40_distinct_cardinality_bound() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(&mut a, "mn", (0..50).map(FieldValue::I64).collect());
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let limits = quervant_core::search::SearchLimits::default()
        .with_max_distinct_values_per_group(10)
        .unwrap();
    let result = pr10_common::aggregate_with_limits(
        &snapshot,
        &distinct_request("mn", vec![]),
        limits,
        &quervant_core::contract::budget::Budgets::new(),
    );
    assert!(matches!(
        result,
        Err(quervant_core::search::SearchError::ResourceLimit { .. })
    ));
}

// T41 — groups are emitted in canonical key order.
#[test]
fn t41_stable_group_order() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.0, true, "z", &["x"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 0, 1.0, true, "a", &["x"], "10.0.0.2"),
        full_doc("c", "c", 1, 0, 0, 1.0, true, "m", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &distinct_request("host", vec!["host"]));
    let hosts: Vec<String> = response
        .groups
        .iter()
        .map(|group| match group.components.as_slice() {
            [pr10_common::GroupValue::Value(FieldValue::Keyword(host))] => host.clone(),
            other => panic!("unexpected components {other:?}"),
        })
        .collect();
    assert_eq!(hosts, ["a", "m", "z"]);
}

// T42 — a document contributes distinct values once per group it belongs to.
#[test]
fn t42_per_document_uniqueness_across_groups() {
    let mut a = doc("a");
    set(
        &mut a,
        "ts",
        FieldValue::Timestamp(pr10_common::Timestamp::from_micros(1)),
    );
    set(&mut a, "host", FieldValue::Keyword("h".into()));
    set_multi(
        &mut a,
        "tags",
        vec![
            FieldValue::Keyword("x".into()),
            FieldValue::Keyword("y".into()),
        ],
    );
    set_multi(
        &mut a,
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(1), FieldValue::I64(2)],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &distinct_request("mn", vec!["tags"]));
    assert_eq!(response.groups.len(), 2);
    for index in 0..2 {
        assert_eq!(distinct_metric(&response, index), 2);
    }
}
