//! PR 10 T28–T32: exact group expansion, null/missing/empty and Cartesian bounds.

mod pr10_common;

use std::collections::BTreeMap;

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, GroupValue, MetricValue, Query, committed,
    full_doc, set_empty, set_multi, set_null, without_field,
};

fn count_request(group_fields: Vec<&str>) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: group_fields.into_iter().map(str::to_owned).collect(),
        time_bucket: None,
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    }
}

fn count_by_display(response: &quervant_core::search::AggregateResponse) -> BTreeMap<String, u64> {
    response
        .groups
        .iter()
        .map(|group| {
            let label = group
                .components
                .iter()
                .map(display)
                .collect::<Vec<_>>()
                .join("|");
            let count = match group.metrics.as_slice() {
                [MetricValue::Count(count)] => *count,
                other => panic!("expected count metric, got {other:?}"),
            };
            (label, count)
        })
        .collect()
}

fn display(value: &GroupValue) -> String {
    match value {
        GroupValue::Missing(_) => "<missing>".to_owned(),
        GroupValue::Null(_) => "<null>".to_owned(),
        GroupValue::Value(FieldValue::I64(number)) => number.to_string(),
        GroupValue::Value(FieldValue::Keyword(keyword)) => keyword.clone(),
        GroupValue::Value(FieldValue::Timestamp(timestamp)) => timestamp.as_micros().to_string(),
        other => format!("{other:?}"),
    }
}

// T28 — empty grouping returns one global group even with zero matches.
#[test]
fn t28_global_group() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &count_request(vec![]));
    assert_eq!(response.groups.len(), 1);
    assert_eq!(response.groups[0].metrics, [MetricValue::Count(2)]);

    let no_match = AggregateRequest {
        query: Query::Term {
            field: "title".into(),
            value: FieldValue::Text("nope".into()),
        },
        ..count_request(vec![])
    };
    // A lexical query is unsupported by the typed engine, so use a range that matches none.
    let none = AggregateRequest {
        query: pr10_common::i64_range("n", Some(100), Some(200)),
        ..no_match
    };
    let response = pr10_common::aggregate(&snapshot, &none);
    assert_eq!(response.groups.len(), 1);
    assert_eq!(response.groups[0].metrics, [MetricValue::Count(0)]);
}

// T29 — missing, null and empty are distinct group components.
#[test]
fn t29_missing_null_empty_groups() {
    let mut absent = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    without_field(&mut absent, "nullable");
    let mut null = full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_null(&mut null, "nullable");
    let mut zero = full_doc("c", "c", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3");
    pr10_common::set(&mut zero, "nullable", FieldValue::I64(0));
    let mut five = full_doc("d", "d", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.4");
    pr10_common::set(&mut five, "nullable", FieldValue::I64(5));
    let (_directory, index) = committed(vec![absent, null, zero, five]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &count_request(vec!["nullable"]));
    let counts = count_by_display(&response);
    assert_eq!(counts.get("<missing>"), Some(&1));
    assert_eq!(counts.get("<null>"), Some(&1));
    assert_eq!(counts.get("0"), Some(&1));
    assert_eq!(counts.get("5"), Some(&1));
    assert_eq!(counts.len(), 4);
}

// T30 — multi-value group expansion deduplicates values per document.
#[test]
fn t30_multi_group_dedup() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "tags",
        vec![
            FieldValue::Keyword("x".into()),
            FieldValue::Keyword("x".into()),
            FieldValue::Keyword("y".into()),
        ],
    );
    let mut b = full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_multi(
        &mut b,
        "tags",
        vec![
            FieldValue::Keyword("y".into()),
            FieldValue::Keyword("z".into()),
        ],
    );
    // An empty multi-value expands to zero groups and contributes nothing.
    let mut c = full_doc("c", "c", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3");
    set_empty(&mut c, "tags");
    let (_directory, index) = committed(vec![a, b, c]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &count_request(vec!["tags"]));
    let counts = count_by_display(&response);
    assert_eq!(counts.get("x"), Some(&1));
    assert_eq!(counts.get("y"), Some(&2));
    assert_eq!(counts.get("z"), Some(&1));
    assert_eq!(counts.len(), 3);
}

// T31 — per-document Cartesian expansion is bounded before materialization.
#[test]
fn t31_cartesian_limit() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "mn",
        vec![
            FieldValue::I64(1),
            FieldValue::I64(2),
            FieldValue::I64(3),
            FieldValue::I64(4),
            FieldValue::I64(5),
        ],
    );
    set_multi(
        &mut a,
        "tags",
        vec![
            FieldValue::Keyword("a".into()),
            FieldValue::Keyword("b".into()),
            FieldValue::Keyword("c".into()),
            FieldValue::Keyword("d".into()),
            FieldValue::Keyword("e".into()),
        ],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let limits = quervant_core::search::SearchLimits::default()
        .with_max_group_expansion_per_document(10)
        .unwrap();
    let result = pr10_common::aggregate_with_limits(
        &snapshot,
        &count_request(vec!["mn", "tags"]),
        limits,
        &quervant_core::contract::budget::Budgets::new(),
    );
    assert!(matches!(
        result,
        Err(quervant_core::search::SearchError::ResourceLimit { .. })
    ));
}

// T32 — grouping over two typed keys produces the Cartesian product of groups.
#[test]
fn t32_two_group_fields() {
    let a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h1", &["x"], "10.0.0.1");
    let b = full_doc("b", "b", 1, 0, 0, 1.0, true, "h1", &["y"], "10.0.0.2");
    let c = full_doc("c", "c", 1, 0, 0, 1.0, true, "h2", &["x"], "10.0.0.3");
    let (_directory, index) = committed(vec![a, b, c]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &count_request(vec!["host", "tags"]));
    let counts = count_by_display(&response);
    assert_eq!(counts.get("h1|x"), Some(&1));
    assert_eq!(counts.get("h1|y"), Some(&1));
    assert_eq!(counts.get("h2|x"), Some(&1));
    assert_eq!(counts.len(), 3);
}
