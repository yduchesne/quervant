//! PR 10 T01–T05: typed integer/F64 range bounds and multi-value semantics.

mod pr10_common;

use pr10_common::{
    Bound, FieldValue, Query, committed, full_doc, hit_keys, i64_range, match_all_request,
    set_null, typed_search,
};

// T01 — inclusive/exclusive integer bounds on I64 and U64 columns.
#[test]
fn t01_integer_bounds_are_inclusive_and_exclusive() {
    let docs = vec![
        full_doc("a", "a", 1, -5, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 1, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 1, 5, 2, 1.0, true, "h", &["x"], "10.0.0.3"),
        full_doc("d", "d", 1, 10, 3, 1.0, true, "h", &["x"], "10.0.0.4"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();

    let inclusive = Query::Range {
        field: "n".into(),
        lower: Bound::Included(FieldValue::I64(-5)),
        upper: Bound::Included(FieldValue::I64(5)),
    };
    let response = typed_search(&snapshot, &match_all_request_with(inclusive));
    assert_eq!(hit_keys(&response), ["a", "b", "c"]);

    let exclusive = Query::Range {
        field: "n".into(),
        lower: Bound::Excluded(FieldValue::I64(-5)),
        upper: Bound::Excluded(FieldValue::I64(5)),
    };
    let response = typed_search(&snapshot, &match_all_request_with(exclusive));
    assert_eq!(hit_keys(&response), ["b"]);

    let u64_query = Query::Range {
        field: "u".into(),
        lower: Bound::Included(FieldValue::U64(1)),
        upper: Bound::Excluded(FieldValue::U64(3)),
    };
    let response = typed_search(&snapshot, &match_all_request_with(u64_query));
    assert_eq!(hit_keys(&response), ["b", "c"]);
}

// T02 — unbounded and half-bounded ranges.
#[test]
fn t02_open_ended_ranges() {
    let mut docs = Vec::new();
    for (index, value) in ["a", "b", "c", "d"].iter().zip([-5i64, 0, 5, 10]) {
        docs.push(full_doc(
            index,
            index,
            1,
            value,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ));
    }
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();

    let at_least = i64_range("n", Some(0), None);
    let response = typed_search(&snapshot, &match_all_request_with(at_least));
    assert_eq!(hit_keys(&response), ["b", "c", "d"]);

    let at_most = i64_range("n", None, Some(0));
    let response = typed_search(&snapshot, &match_all_request_with(at_most));
    assert_eq!(hit_keys(&response), ["a", "b"]);

    let all = i64_range("n", None, None);
    let response = typed_search(&snapshot, &match_all_request_with(all));
    assert_eq!(hit_keys(&response), ["a", "b", "c", "d"]);
}

// T03 — F64 bounds are exact and reject NaN inputs upstream.
#[test]
fn t03_f64_bounds() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.5, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 1, 0, 0, 2.5, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 1, 0, 0, 3.5, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let query = Query::Range {
        field: "score".into(),
        lower: Bound::Excluded(FieldValue::F64(1.5)),
        upper: Bound::Included(FieldValue::F64(3.5)),
    };
    let response = typed_search(&snapshot, &match_all_request_with(query));
    assert_eq!(hit_keys(&response), ["b", "c"]);
}

// T04 — a multi-value field matches a range if any member is in range.
#[test]
fn t04_multivalue_range_any_member() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    pr10_common::set_multi(&mut a, "mn", vec![FieldValue::I64(-10), FieldValue::I64(7)]);
    let mut b = full_doc("b", "b", 1, 7, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    pr10_common::set_multi(&mut b, "mn", vec![FieldValue::I64(7)]);
    let (_directory, index) = committed(vec![a, b]);
    let snapshot = index.snapshot();
    let response = typed_search(
        &snapshot,
        &match_all_request_with(i64_range("mn", Some(6), Some(8))),
    );
    assert_eq!(hit_keys(&response), ["a", "b"]);
}

// T05 — absent/null/empty never match a positive range, and `Not` matches them.
#[test]
fn t05_missing_null_empty_and_not() {
    let mut absent = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    pr10_common::without_field(&mut absent, "mn");
    let mut null = full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_null(&mut null, "mn");
    let mut empty = full_doc("c", "c", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.3");
    pr10_common::set_empty(&mut empty, "mn");
    let mut matched = full_doc("d", "d", 1, 5, 0, 1.0, true, "h", &["x"], "10.0.0.4");
    pr10_common::set_multi(&mut matched, "mn", vec![FieldValue::I64(5)]);
    let (_directory, index) = committed(vec![absent, null, empty, matched]);
    let snapshot = index.snapshot();

    let positive = i64_range("mn", Some(0), Some(10));
    let response = typed_search(&snapshot, &match_all_request_with(positive.clone()));
    assert_eq!(hit_keys(&response), ["d"]);

    let not = Query::Not(Box::new(positive));
    let response = typed_search(&snapshot, &match_all_request_with(not));
    assert_eq!(hit_keys(&response), ["a", "b", "c"]);
}

fn match_all_request_with(query: Query) -> pr10_common::TypedSearchRequest {
    let mut request = match_all_request(pr10_common::Sort::default(), 50);
    request.query = query;
    request
}
