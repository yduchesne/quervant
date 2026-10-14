//! PR 10 T19–T23: snapshot-bound typed cursors and gap-free pagination.

mod pr10_common;

use pr10_common::{
    FieldValue, Query, Sort, SortDirection, SortField, committed, full_doc, match_all_request,
    typed_search,
};

fn docs(count: i64) -> Vec<quervant_core::contract::document::Document> {
    (0..count)
        .map(|index| {
            full_doc(
                &format!("k{index:03}"),
                "t",
                index,
                index,
                index as u64,
                1.0,
                true,
                "h",
                &["x"],
                "10.0.0.1",
            )
        })
        .collect()
}

// T19 — paginating with a cursor has no gaps and no duplicates.
#[test]
fn t19_full_pagination_no_gaps() {
    let (_directory, index) = committed(docs(10));
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let expected: Vec<String> = (0..10).map(|index| format!("k{index:03}")).collect();

    let mut collected = Vec::new();
    let mut after = None;
    loop {
        let mut request = match_all_request(sort.clone(), 3);
        request.after = after.clone();
        let response = typed_search(&snapshot, &request);
        collected.extend(pr10_common::hit_keys(&response));
        match response.next_cursor {
            Some(cursor) => after = Some(cursor),
            None => break,
        }
    }
    assert_eq!(collected, expected);
}

// T20 — continuation may change the page size; fingerprint excludes top_k.
#[test]
fn t20_page_size_can_change() {
    let (_directory, index) = committed(docs(7));
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);

    let first = typed_search(&snapshot, &match_all_request(sort.clone(), 2));
    let cursor = first.next_cursor.expect("cursor after partial page");
    let mut request = match_all_request(sort, 5);
    request.after = Some(cursor);
    let second = typed_search(&snapshot, &request);
    assert_eq!(
        pr10_common::hit_keys(&second),
        ["k002", "k003", "k004", "k005", "k006"]
    );
    assert!(second.next_cursor.is_none());
}

// T21/T22 — a changed query or sort is rejected before scanning.
#[test]
fn t21_changed_query_or_sort_rejected() {
    let (_directory, index) = committed(docs(5));
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = typed_search(&snapshot, &match_all_request(sort.clone(), 2));
    let cursor = response.next_cursor.expect("cursor");

    let mut changed_query = match_all_request(sort, 2);
    changed_query.query = Query::Range {
        field: "n".into(),
        lower: quervant_core::contract::query::Bound::Included(FieldValue::I64(0)),
        upper: quervant_core::contract::query::Bound::Unbounded,
    };
    changed_query.after = Some(cursor.clone());
    let error = typed_search_err(&snapshot, &changed_query);
    assert!(matches!(
        error,
        quervant_core::search::SearchError::Query(
            quervant_core::contract::error::QueryError::InvalidQuery(
                quervant_core::contract::error::InvalidQueryReason::CursorSortMismatch
            )
        )
    ));

    let mut changed_sort =
        match_all_request(Sort::new(vec![SortField::new("n", SortDirection::Desc)]), 2);
    changed_sort.after = Some(cursor);
    let error = typed_search_err(&snapshot, &changed_sort);
    assert!(matches!(
        error,
        quervant_core::search::SearchError::Query(
            quervant_core::contract::error::QueryError::InvalidQuery(
                quervant_core::contract::error::InvalidQueryReason::CursorSortMismatch
            )
        )
    ));
}

// T23 — two snapshots at the same generation have distinct identities.
#[test]
fn t23_distinct_snapshot_same_generation_rejected() {
    let (_directory, index) = committed(docs(5));
    let first = index.snapshot();
    let second = index.snapshot();
    assert_eq!(first.generation(), second.generation());
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = typed_search(&first, &match_all_request(sort.clone(), 2));
    let cursor = response.next_cursor.expect("cursor");
    let mut request = match_all_request(sort, 2);
    request.after = Some(cursor);
    let error = typed_search_err(&second, &request);
    assert!(matches!(
        error,
        quervant_core::search::SearchError::Query(
            quervant_core::contract::error::QueryError::InvalidQuery(
                quervant_core::contract::error::InvalidQueryReason::CursorPitMismatch
            )
        )
    ));
}

fn typed_search_err(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &pr10_common::TypedSearchRequest,
) -> quervant_core::search::SearchError {
    let schema = pr10_common::pr10_schema();
    let cancel = quervant_core::analysis::CancellationFlag::new();
    quervant_core::search::TypedSearcher::new(
        snapshot,
        &schema,
        quervant_core::search::SearchLimits::default(),
    )
    .search(
        request,
        &quervant_core::contract::budget::Budgets::new(),
        &cancel,
    )
    .expect_err("expected rejection")
}
