//! PR 10 T06–T09: exact half-open UTC time filtering.

mod pr10_common;

use pr10_common::{
    FieldValue, Query, Sort, Timestamp, committed, full_doc, hit_keys, match_all_request,
    set_multi, time_range, typed_search,
};

fn request(query: Query) -> pr10_common::TypedSearchRequest {
    let mut request = match_all_request(Sort::default(), 50);
    request.query = query;
    request
}

// T06 — `TimeRange` is half-open `[start, end)`.
#[test]
fn t06_time_range_is_half_open() {
    let docs = vec![
        full_doc("a", "a", 9, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 10, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 19, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
        full_doc("d", "d", 20, 0, 0, 1.0, true, "h", &["x"], "10.0.0.4"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = typed_search(&snapshot, &request(time_range("ts", 10, 20)));
    assert_eq!(hit_keys(&response), ["b", "c"]);
    // Empty window matches nothing.
    let response = typed_search(&snapshot, &request(time_range("ts", 10, 10)));
    assert!(response.hits.is_empty());
}

// T07 — signed pre-epoch microseconds.
#[test]
fn t07_pre_epoch_time() {
    let docs = vec![
        full_doc("a", "a", -100, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", -1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 0, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = typed_search(&snapshot, &request(time_range("ts", -150, 0)));
    assert_eq!(hit_keys(&response), ["a", "b"]);
}

// T08 — late/out-of-order events are filtered by value, not ingestion order.
#[test]
fn t08_late_out_of_order_events() {
    let docs = vec![
        full_doc(
            "late",
            "late",
            500,
            0,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ),
        full_doc(
            "early",
            "early",
            100,
            0,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.2",
        ),
        full_doc(
            "middle",
            "middle",
            300,
            0,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.3",
        ),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let response = typed_search(&snapshot, &request(time_range("ts", 150, 450)));
    assert_eq!(hit_keys(&response), ["middle"]);
}

// T09 — multi timestamp matches ANY member; invalid `start > end` is rejected.
#[test]
fn t09_multi_value_and_invalid_range() {
    let mut a = full_doc("a", "a", 0, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(
        &mut a,
        "mts",
        vec![
            FieldValue::Timestamp(Timestamp::from_micros(-5)),
            FieldValue::Timestamp(Timestamp::from_micros(50)),
        ],
    );
    let mut b = full_doc("b", "b", 0, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_multi(
        &mut b,
        "mts",
        vec![FieldValue::Timestamp(Timestamp::from_micros(200))],
    );
    let (_directory, index) = committed(vec![a, b]);
    let snapshot = index.snapshot();
    let response = typed_search(&snapshot, &request(time_range("mts", 40, 60)));
    assert_eq!(hit_keys(&response), ["a"]);

    let invalid = Query::TimeRange {
        field: "ts".into(),
        start: Timestamp::from_micros(20),
        end: Timestamp::from_micros(10),
    };
    let mut request = match_all_request(Sort::default(), 10);
    request.query = invalid;
    let schema = pr10_common::pr10_schema();
    let cancel = quervant_core::analysis::CancellationFlag::new();
    let error = quervant_core::search::TypedSearcher::new(
        &snapshot,
        &schema,
        quervant_core::search::SearchLimits::default(),
    )
    .search(
        &request,
        &quervant_core::contract::budget::Budgets::new(),
        &cancel,
    );
    assert!(error.is_err());
}
