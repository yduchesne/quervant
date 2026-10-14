//! PR 10 Amendment 02 — bounded transient aggregation memory (A2-T03..T11).
//!
//! The shared retained/transient ledger has focused unit tests in
//! `search/analytics.rs` (A2-T01, T02, T05-unit, T07, T08, T09). This suite
//! exercises the admission behavior end-to-end through the real aggregation
//! engine over real committed snapshots.

mod pr10_common;

use pr10_common::{
    AggregateGroup, AggregateMetric, AggregateRequest, FieldValue, FrequencyTopK, GroupValue,
    MetricValue, NumericAggregate, Query, Timestamp, aggregate, aggregate_with_limits, committed,
    doc, pr10_schema, set, set_multi,
};
use quervant_core::analysis::Cancellation;
use quervant_core::contract::budget::Budgets;
use quervant_core::search::{SearchError, SearchLimits, TypedSearcher};
use std::sync::atomic::{AtomicUsize, Ordering};

/// Cancel after a fixed number of `is_cancelled` polls.
struct CancelAfter {
    calls: AtomicUsize,
    cancel_at: usize,
}

impl CancelAfter {
    fn new(cancel_at: usize) -> Self {
        Self {
            calls: AtomicUsize::new(0),
            cancel_at,
        }
    }
}

impl Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        self.calls.fetch_add(1, Ordering::SeqCst) >= self.cancel_at
    }
}

fn request(
    group_fields: Vec<&str>,
    metrics: Vec<AggregateMetric>,
    frequency: Option<(&str, usize)>,
) -> AggregateRequest {
    AggregateRequest {
        query: Query::MatchAll,
        group_fields: group_fields.into_iter().map(str::to_owned).collect(),
        time_bucket: None,
        metrics,
        frequency_top_k: frequency.map(|(field, limit)| FrequencyTopK {
            field: field.to_owned(),
            limit,
        }),
        primary_time_field: Some("ts".into()),
    }
}

fn timestamp(micros: i64) -> FieldValue {
    FieldValue::Timestamp(Timestamp::from_micros(micros))
}

fn group_label(group: &AggregateGroup) -> String {
    match group.components.as_slice() {
        [GroupValue::Value(FieldValue::Keyword(host))] => host.clone(),
        [GroupValue::Missing(_)] => "<missing>".to_owned(),
        [GroupValue::Null(_)] => "<null>".to_owned(),
        other => format!("{other:?}"),
    }
}

// A2-T03 — a very large owned decoded value is rejected before it is admitted.
#[test]
fn a2_t03_large_keyword_admission_rejected() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set_multi(
        &mut a,
        "tags",
        vec![FieldValue::Keyword("x".repeat(10_000))],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let aggregate = request(
        vec!["tags"],
        vec![AggregateMetric::Count],
        Some(("tags", 10)),
    );
    let limits = SearchLimits::default()
        .with_max_aggregate_state_bytes(256)
        .unwrap();
    let result = aggregate_with_limits(&snapshot, &aggregate, limits, &Budgets::new());
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
}

// A2-T04 — repeated metrics over one field reuse one decode and stay exact.
#[test]
fn a2_t04_repeated_metrics_reuse_and_exactness() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set_multi(
        &mut a,
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2), FieldValue::I64(3)],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = aggregate(
        &snapshot,
        &request(
            vec![],
            vec![
                AggregateMetric::Sum { field: "mn".into() },
                AggregateMetric::Avg { field: "mn".into() },
                AggregateMetric::Min { field: "mn".into() },
                AggregateMetric::Max { field: "mn".into() },
                AggregateMetric::ExactDistinct { field: "mn".into() },
            ],
            None,
        ),
    );
    assert_eq!(response.groups.len(), 1);
    let metrics = &response.groups[0].metrics;
    assert_eq!(metrics[0], MetricValue::Sum(NumericAggregate::Signed(6)));
    assert_eq!(metrics[1], MetricValue::Avg(Some(2.0)));
    assert_eq!(metrics[2], MetricValue::Min(Some(FieldValue::I64(1))));
    assert_eq!(metrics[3], MetricValue::Max(Some(FieldValue::I64(3))));
    assert_eq!(metrics[4], MetricValue::ExactDistinct(3));
}

// A2-T05 — duplicate multi-values count once per document in frequency top-K.
#[test]
fn a2_t05_frequency_dedup_per_document() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set_multi(
        &mut a,
        "mn",
        vec![
            FieldValue::I64(1),
            FieldValue::I64(1),
            FieldValue::I64(2),
            FieldValue::I64(2),
            FieldValue::I64(3),
            FieldValue::I64(3),
        ],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let response = aggregate(
        &snapshot,
        &request(vec![], vec![AggregateMetric::Count], Some(("mn", 10))),
    );
    let frequencies = response.groups[0]
        .frequencies
        .as_ref()
        .expect("frequencies");
    assert_eq!(
        frequencies,
        &[
            (FieldValue::I64(1), 1),
            (FieldValue::I64(2), 1),
            (FieldValue::I64(3), 1)
        ]
    );
}

// A2-T06 — Cartesian staging is bounded by the shared memory budget.
#[test]
fn a2_t06_expansion_memory_bound() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set_multi(
        &mut a,
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2), FieldValue::I64(3)],
    );
    set_multi(
        &mut a,
        "tags",
        vec![
            FieldValue::Keyword("x".into()),
            FieldValue::Keyword("y".into()),
            FieldValue::Keyword("z".into()),
        ],
    );
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let aggregate_request = request(vec!["mn", "tags"], vec![AggregateMetric::Count], None);
    let limits = SearchLimits::default()
        .with_max_aggregate_state_bytes(512)
        .unwrap();
    let result = aggregate_with_limits(&snapshot, &aggregate_request, limits, &Budgets::new());
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));

    // The same request succeeds with a generous budget and exact counts.
    let response = aggregate(&snapshot, &aggregate_request);
    assert_eq!(response.groups.len(), 9);
    assert!(
        response
            .groups
            .iter()
            .all(|group| group.metrics == [MetricValue::Count(1)])
    );
}

// A2-T10 — exact semantics table over a real snapshot with a generous budget.
#[test]
fn a2_t10_semantics_table() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set(&mut a, "host", FieldValue::Keyword("h1".into()));
    set_multi(&mut a, "mn", vec![FieldValue::I64(1), FieldValue::I64(2)]);
    let mut b = doc("b");
    set(&mut b, "ts", timestamp(2));
    set(&mut b, "host", FieldValue::Keyword("h1".into()));
    set_multi(&mut b, "mn", vec![FieldValue::I64(2), FieldValue::I64(3)]);
    let mut c = doc("c");
    set(&mut c, "ts", timestamp(3));
    set(&mut c, "host", FieldValue::Keyword("h2".into()));
    set_multi(&mut c, "mn", vec![FieldValue::I64(3)]);
    let (_directory, index) = committed(vec![a, b, c]);
    let snapshot = index.snapshot();
    let response = aggregate(
        &snapshot,
        &request(
            vec!["host"],
            vec![
                AggregateMetric::Count,
                AggregateMetric::Sum { field: "mn".into() },
                AggregateMetric::ExactDistinct { field: "mn".into() },
                AggregateMetric::Min { field: "ts".into() },
                AggregateMetric::Max { field: "ts".into() },
            ],
            Some(("mn", 10)),
        ),
    );
    assert_eq!(response.groups.len(), 2);
    type GroupRow = (String, Vec<MetricValue>, Vec<(FieldValue, u64)>);
    let mut by_host: Vec<GroupRow> = response
        .groups
        .iter()
        .map(|group| {
            (
                group_label(group),
                group.metrics.clone(),
                group.frequencies.clone().unwrap_or_default(),
            )
        })
        .collect();
    by_host.sort_by(|a, b| a.0.cmp(&b.0));

    assert_eq!(by_host[0].0, "h1");
    assert_eq!(
        by_host[0].1,
        vec![
            MetricValue::Count(2),
            MetricValue::Sum(NumericAggregate::Signed(8)),
            MetricValue::ExactDistinct(3),
            MetricValue::Min(Some(timestamp(1))),
            MetricValue::Max(Some(timestamp(2))),
        ]
    );
    assert_eq!(
        by_host[0].2,
        vec![
            (FieldValue::I64(2), 2),
            (FieldValue::I64(1), 1),
            (FieldValue::I64(3), 1)
        ]
    );

    assert_eq!(by_host[1].0, "h2");
    assert_eq!(
        by_host[1].1,
        vec![
            MetricValue::Count(1),
            MetricValue::Sum(NumericAggregate::Signed(3)),
            MetricValue::ExactDistinct(1),
            MetricValue::Min(Some(timestamp(3))),
            MetricValue::Max(Some(timestamp(3))),
        ]
    );
    assert_eq!(by_host[1].2, vec![(FieldValue::I64(3), 1)]);
}

// A2-T11 — identical inputs yield identical success or typed error.
#[test]
fn a2_t11_deterministic_success_or_error() {
    let mut a = doc("a");
    set(&mut a, "ts", timestamp(1));
    set_multi(&mut a, "mn", vec![FieldValue::I64(1), FieldValue::I64(2)]);
    let (_directory, index) = committed(vec![a]);
    let snapshot = index.snapshot();
    let aggregate_request = request(vec!["mn"], vec![AggregateMetric::Count], Some(("mn", 5)));

    let tight = SearchLimits::default()
        .with_max_aggregate_state_bytes(64)
        .unwrap();
    let first = aggregate_with_limits(&snapshot, &aggregate_request, tight, &Budgets::new());
    let second = aggregate_with_limits(&snapshot, &aggregate_request, tight, &Budgets::new());
    assert!(matches!(first, Err(SearchError::ResourceLimit { .. })));
    assert!(matches!(second, Err(SearchError::ResourceLimit { .. })));

    let first = aggregate(&snapshot, &aggregate_request);
    let second = aggregate(&snapshot, &aggregate_request);
    assert_eq!(first.groups, second.groups);
    assert_eq!(first.diagnostics, second.diagnostics);
}

// A2-T08 (integration) — cancellation mid-scan returns `Cancelled` with no
// partial response, leaving the snapshot usable.
#[test]
fn a2_t08_cancellation_mid_scan() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(std::sync::Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        let mut a = doc("a");
        set(&mut a, "ts", timestamp(1));
        set_multi(&mut a, "tags", vec![FieldValue::Keyword("x".into())]);
        writer.insert(a).unwrap();
        writer.commit().unwrap();
        let mut b = doc("b");
        set(&mut b, "ts", timestamp(2));
        set_multi(&mut b, "tags", vec![FieldValue::Keyword("y".into())]);
        writer.insert(b).unwrap();
        writer.commit().unwrap();
    }
    let reopened = pr10_common::reopen(directory);
    let snapshot = reopened.snapshot();
    assert!(snapshot.segment_count() >= 2);

    let schema = pr10_schema();
    let aggregate_request = request(vec!["tags"], vec![AggregateMetric::Count], None);
    // Entry check is call 0; the first segment poll is call 1; cancelling on
    // call 2 stops while later segments still remain.
    let cancel = CancelAfter::new(2);
    let result = TypedSearcher::new(&snapshot, &schema, SearchLimits::default()).aggregate(
        &aggregate_request,
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));

    // The snapshot remains usable with a non-cancelling caller.
    let response = aggregate(&snapshot, &aggregate_request);
    assert_eq!(response.groups.len(), 2);
}
