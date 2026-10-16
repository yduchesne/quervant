//! PR 10 T13–T18: deterministic typed sort, ties, missing/null and unsupported types.

mod pr10_common;

use pr10_common::{
    FieldValue, MissingValuePosition, MultiValueSelector, Sort, SortDirection, SortField,
    committed, full_doc, hit_keys, match_all_request, set_multi, set_null, typed_search,
    without_field,
};

fn search(
    snapshot: &quervant_core::index::ReaderSnapshot,
    sort: Sort,
    top_k: usize,
) -> Vec<String> {
    let request = match_all_request(sort, top_k);
    hit_keys(&typed_search(snapshot, &request))
}

fn sort_field(
    field: &str,
    direction: SortDirection,
    missing: MissingValuePosition,
    multi: Option<MultiValueSelector>,
) -> SortField {
    SortField {
        field: field.to_owned(),
        direction,
        missing,
        multi,
        distance_from: None,
        json_path: None,
    }
}

// T13 — ascending and descending numeric order.
#[test]
fn t13_directions() {
    let docs = vec![
        full_doc("a", "a", 1, 3, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 1, 1, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 1, 2, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            Sort::new(vec![sort_field(
                "n",
                SortDirection::Asc,
                MissingValuePosition::Last,
                None
            )]),
            10
        ),
        ["b", "c", "a"]
    );
    assert_eq!(
        search(
            &snapshot,
            Sort::new(vec![sort_field(
                "n",
                SortDirection::Desc,
                MissingValuePosition::Last,
                None
            )]),
            10
        ),
        ["a", "c", "b"]
    );
}

// T14 — ties break by ascending logical key regardless of direction.
#[test]
fn t14_ties_break_by_key() {
    let docs = vec![
        full_doc("z", "z", 1, 7, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("a", "a", 1, 7, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("m", "m", 1, 7, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            Sort::new(vec![sort_field(
                "n",
                SortDirection::Desc,
                MissingValuePosition::Last,
                None
            )]),
            10
        ),
        ["a", "m", "z"]
    );
}

// T15 — missing placement First vs Last does not reverse under Desc.
#[test]
fn t15_missing_placement() {
    let mut absent = full_doc(
        "absent",
        "absent",
        1,
        1,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.1",
    );
    without_field(&mut absent, "nullable");
    let mut present = full_doc(
        "present",
        "present",
        1,
        1,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.2",
    );
    set_null(&mut present, "nullable");
    // present is explicit null; set a real value on value doc.
    let mut value = full_doc(
        "value",
        "value",
        1,
        1,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.3",
    );
    pr10_common::set(&mut value, "nullable", FieldValue::I64(5));
    let (_directory, index) = committed(vec![absent, present, value]);
    let snapshot = index.snapshot();

    let first = Sort::new(vec![sort_field(
        "nullable",
        SortDirection::Asc,
        MissingValuePosition::First,
        None,
    )]);
    assert_eq!(search(&snapshot, first, 10), ["absent", "present", "value"]);

    let last = Sort::new(vec![sort_field(
        "nullable",
        SortDirection::Desc,
        MissingValuePosition::Last,
        None,
    )]);
    // Desc reverses values only: value, then null, then missing.
    assert_eq!(search(&snapshot, last, 10), ["value", "present", "absent"]);
}

// T16 — explicit null and missing are distinct and never collapse.
#[test]
fn t16_null_and_missing_are_distinct() {
    let mut missing = full_doc(
        "missing",
        "missing",
        1,
        1,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.1",
    );
    without_field(&mut missing, "nullable");
    let mut null = full_doc("null", "null", 1, 1, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_null(&mut null, "nullable");
    let (_directory, index) = committed(vec![missing, null]);
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![sort_field(
        "nullable",
        SortDirection::Asc,
        MissingValuePosition::First,
        None,
    )]);
    assert_eq!(search(&snapshot, sort, 10), ["missing", "null"]);
}

// T17 — multi-value selector is applied before sort direction.
#[test]
fn t17_multi_selector_before_direction() {
    let mut a = full_doc("a", "a", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.1");
    set_multi(&mut a, "mn", vec![FieldValue::I64(1), FieldValue::I64(9)]);
    let mut b = full_doc("b", "b", 1, 0, 0, 1.0, true, "h", &["x"], "10.0.0.2");
    set_multi(&mut b, "mn", vec![FieldValue::I64(5)]);
    let (_directory, index) = committed(vec![a, b]);
    let snapshot = index.snapshot();

    let asc_min = Sort::new(vec![sort_field(
        "mn",
        SortDirection::Asc,
        MissingValuePosition::Last,
        Some(MultiValueSelector::Min),
    )]);
    assert_eq!(search(&snapshot, asc_min, 10), ["a", "b"]);

    // Max-selector: a = 9, b = 5, so b first ascending.
    let asc_max = Sort::new(vec![sort_field(
        "mn",
        SortDirection::Asc,
        MissingValuePosition::Last,
        Some(MultiValueSelector::Max),
    )]);
    assert_eq!(search(&snapshot, asc_max, 10), ["b", "a"]);
}

// T18 — keyword and IP order canonically; unsupported types fail closed.
#[test]
fn t18_keyword_ip_and_unsupported() {
    let docs = vec![
        full_doc("a", "a", 1, 0, 0, 1.0, true, "zebra", &["x"], "2001:db8::1"),
        full_doc("b", "b", 1, 0, 0, 1.0, true, "alpha", &["x"], "10.0.0.1"),
        full_doc("c", "c", 1, 0, 0, 1.0, true, "mango", &["x"], "10.0.0.2"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            Sort::new(vec![sort_field(
                "host",
                SortDirection::Asc,
                MissingValuePosition::Last,
                None
            )]),
            10
        ),
        ["b", "c", "a"]
    );
    // IPv4 before IPv6.
    assert_eq!(
        search(
            &snapshot,
            Sort::new(vec![sort_field(
                "ip",
                SortDirection::Asc,
                MissingValuePosition::Last,
                None
            )]),
            10
        ),
        ["b", "c", "a"]
    );

    // GeoPoint columns are not typed sort scalars.
    let request = match_all_request(
        Sort::new(vec![sort_field(
            "point",
            SortDirection::Asc,
            MissingValuePosition::Last,
            None,
        )]),
        10,
    );
    let schema = pr10_common::pr10_schema();
    let cancel = quervant_core::analysis::CancellationFlag::new();
    let result = quervant_core::search::TypedSearcher::new(
        &snapshot,
        &schema,
        quervant_core::search::SearchLimits::default(),
    )
    .search(
        &request,
        &quervant_core::contract::budget::Budgets::new(),
        &cancel,
    );
    assert!(matches!(
        result,
        Err(quervant_core::search::SearchError::UnsupportedOperator { .. })
    ));
}
