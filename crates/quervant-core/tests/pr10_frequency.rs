//! PR 10 frequency top-K: exact per-group counts, stable ties and bounds.

mod pr10_common;

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, FrequencyTopK, Query, committed, full_doc,
    set_multi,
};

fn frequency_request(field: &str, limit: usize, group_fields: Vec<&str>) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: group_fields.into_iter().map(str::to_owned).collect(),
        time_bucket: None,
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: Some(FrequencyTopK {
            field: field.to_owned(),
            limit,
        }),
        primary_time_field: Some("ts".into()),
    }
}

fn frequencies(
    response: &quervant_core::search::AggregateResponse,
    index: usize,
) -> Vec<(String, u64)> {
    response.groups[index]
        .frequencies
        .as_ref()
        .expect("frequencies")
        .iter()
        .map(|(value, count)| match value {
            FieldValue::Keyword(keyword) => (keyword.clone(), *count),
            other => panic!("unexpected frequency value {other:?}"),
        })
        .collect()
}

// Exact descending counts, with ascending canonical value on ties.
#[test]
fn frequency_orders_by_count_then_value() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["b"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["a", "b"], "10.0.0.2"),
        full_doc("c", "c", 1, 0, 0, 1.0, true, "h", &["a", "b"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &frequency_request("tags", 10, vec![]));
    assert_eq!(
        frequencies(&response, 0),
        [("b".to_owned(), 3), ("a".to_owned(), 2)]
    );
}

// Each distinct scalar counts at most once per document.
#[test]
fn frequency_counts_once_per_document() {
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
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &frequency_request("tags", 10, vec![]));
    assert_eq!(
        frequencies(&response, 0),
        [("x".to_owned(), 1), ("y".to_owned(), 1)]
    );
}

// Top-K truncates only after all exact counts are computed.
#[test]
fn frequency_top_k_is_exact() {
    let docs = (0..5)
        .map(|index| {
            full_doc(
                &format!("k{index}"),
                "t",
                1,
                0,
                0,
                1.0,
                true,
                "h",
                &[&format!("v{index}")],
                "10.0.0.1",
            )
        })
        .collect();
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &frequency_request("tags", 2, vec![]));
    let values = frequencies(&response, 0);
    assert_eq!(values.len(), 2);
    assert!(values.iter().all(|(_, count)| *count == 1));
    // Canonical value tie-break selects the two smallest keywords.
    assert_eq!(values[0].0, "v0");
    assert_eq!(values[1].0, "v1");
}

// Exceeding the frequency cardinality budget is typed, never silent truncation.
#[test]
fn frequency_cardinality_bound() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "tags",
        (0..50)
            .map(|index| FieldValue::Keyword(format!("v{index:03}")))
            .collect(),
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let limits = quervant_core::search::SearchLimits::default()
        .with_max_frequency_values_per_group(10)
        .unwrap();
    let result = pr10_common::aggregate_with_limits(
        &snapshot,
        &frequency_request("tags", 10, vec![]),
        limits,
        &quervant_core::contract::budget::Budgets::new(),
    );
    assert!(matches!(
        result,
        Err(quervant_core::search::SearchError::ResourceLimit { .. })
    ));
}

// The requested top-K limit is itself bounded.
#[test]
fn frequency_top_k_limit_is_bounded() {
    let (_directory, index) = committed(vec![full_doc(
        "a",
        "a",
        1,
        0,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.1",
    )]);
    let snapshot = index.snapshot();
    let limits = quervant_core::search::SearchLimits::default()
        .with_max_frequency_top_k(3)
        .unwrap();
    let result = pr10_common::aggregate_with_limits(
        &snapshot,
        &frequency_request("tags", 4, vec![]),
        limits,
        &quervant_core::contract::budget::Budgets::new(),
    );
    assert!(matches!(
        result,
        Err(quervant_core::search::SearchError::ResourceLimit { .. })
    ));
}

// Frequencies are computed independently for each group.
#[test]
fn frequency_per_group() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.0, true, "g1", &["x", "y"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 0, 1.0, true, "g1", &["x"], "10.0.0.2"),
        full_doc("c", "c", 1, 0, 0, 1.0, true, "g2", &["y"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = pr10_common::aggregate(&snapshot, &frequency_request("tags", 10, vec!["host"]));
    assert_eq!(response.groups.len(), 2);
    let mut all: Vec<Vec<(String, u64)>> = response
        .groups
        .iter()
        .enumerate()
        .map(|(index, _)| frequencies(&response, index))
        .collect();
    all.sort();
    assert_eq!(
        all,
        vec![
            vec![("x".to_owned(), 2), ("y".to_owned(), 1)],
            vec![("y".to_owned(), 1)],
        ]
    );
}

// Silence an unused import when the file is compiled alone.
#[allow(dead_code)]
fn _q() -> Query {
    Query::MatchAll
}
