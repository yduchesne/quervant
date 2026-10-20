//! PR 14 F2 — snapshot-bound unified search-after cursor (P01–P12).

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::{CancellationFlag, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::result::Projection;
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedCursor, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};

fn run(
    _index: &quervant_core::index::Index,
    snapshot: &quervant_core::index::ReaderSnapshot,
    query: Query,
    sort: Sort,
    top_k: usize,
    after: Option<UnifiedCursor>,
) -> UnifiedResponse {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = sort;
    request.after = after;
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_or_else(|error| panic!("cursor search failed: {error}"))
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn paginate(
    index: &quervant_core::index::Index,
    snapshot: &quervant_core::index::ReaderSnapshot,
    query: Query,
    sort: Sort,
    page: usize,
) -> Vec<String> {
    let mut out = Vec::new();
    let mut after = None;
    for _ in 0..1000 {
        let response = run(index, snapshot, query.clone(), sort.clone(), page, after);
        out.extend(keys(&response));
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
    }
    out
}

fn sort_two_fields() -> Sort {
    Sort::new(vec![
        SortField::new("host", SortDirection::Asc),
        SortField::new("n", SortDirection::Asc),
    ])
}

fn tie_docs() -> Vec<Document> {
    let mut a = doc("a");
    set(&mut a, "host", FieldValue::Keyword("h1".into()));
    set(&mut a, "n", FieldValue::I64(1));
    let mut b = doc("b");
    set(&mut b, "host", FieldValue::Keyword("h1".into()));
    set(&mut b, "n", FieldValue::I64(1));
    let mut c = doc("c");
    set(&mut c, "host", FieldValue::Keyword("h1".into()));
    set(&mut c, "n", FieldValue::I64(2));
    let mut d = doc("d");
    set(&mut d, "host", FieldValue::Keyword("h2".into()));
    set(&mut d, "n", FieldValue::I64(1));
    let mut null_host = doc("f");
    set_null(&mut null_host, "host");
    set(&mut null_host, "n", FieldValue::I64(0));
    let mut missing_host = doc("e");
    set(&mut missing_host, "n", FieldValue::I64(0));
    vec![a, b, c, d, null_host, missing_host]
}

// P01 — two-field sort with null/missing/ties, all page sizes match one page.
#[test]
fn p01_multi_field_sort_pages_match_full_order() {
    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let full = paginate(&index, &snapshot, Query::MatchAll, sort_two_fields(), 100);
    assert_eq!(full, ["a", "b", "c", "d", "f", "e"]);
    for page in [1usize, 2, 3] {
        assert_eq!(
            paginate(&index, &snapshot, Query::MatchAll, sort_two_fields(), page),
            full,
            "page size {page}"
        );
    }
}

// P02 — K divides N => no cursor; N=K+1 => cursor on first page.
#[test]
fn p02_cursor_presence() {
    let mut docs = Vec::new();
    for (key, n) in [("a", 1), ("b", 2), ("c", 3), ("d", 4)] {
        let mut document = doc(key);
        set(&mut document, "n", FieldValue::I64(n));
        docs.push(document);
    }
    let index = committed(docs);
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let page1 = run(&index, &snapshot, Query::MatchAll, sort.clone(), 2, None);
    assert_eq!(page1.hits.len(), 2);
    let cursor = page1.next_cursor.expect("continuation");
    let page2 = run(&index, &snapshot, Query::MatchAll, sort, 2, Some(cursor));
    assert_eq!(page2.hits.len(), 2);
    assert!(page2.next_cursor.is_none());
}

// P03 — total_hits is constant across pages.
#[test]
fn p03_total_hits_constant() {
    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let sort = sort_two_fields();
    let mut after = None;
    let mut seen = 0;
    for _ in 0..10 {
        let response = run(&index, &snapshot, Query::MatchAll, sort.clone(), 2, after);
        assert_eq!(response.total_hits, 6);
        seen += response.hits.len();
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
    }
    assert_eq!(seen, 6);
}

// P04 — empty index, zero hits, singleton, K>N.
#[test]
fn p04_boundary_empties() {
    let empty = committed(Vec::new());
    let snapshot = empty.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = run(&empty, &snapshot, Query::MatchAll, sort.clone(), 1, None);
    assert_eq!(response.total_hits, 0);
    assert!(response.hits.is_empty());
    assert!(response.next_cursor.is_none());

    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let none = run(
        &index,
        &snapshot,
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("nonexistent".into()),
        },
        sort.clone(),
        1,
        None,
    );
    assert_eq!(none.total_hits, 0);
    assert!(none.next_cursor.is_none());
    let all = run(&index, &snapshot, Query::MatchAll, sort, 100, None);
    assert_eq!(all.hits.len(), 6);
    assert!(all.next_cursor.is_none());
}

// P05 — relevance pagination preserves bit-exact scores and order.
#[test]
fn p05_relevance_pagination() {
    let mut docs = Vec::new();
    for key in ["a", "b", "c", "d"] {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text("alpha".into()));
        set(&mut document, "host", FieldValue::Keyword("h".into()));
        docs.push(document);
    }
    let index = committed(docs);
    let snapshot = index.snapshot();
    let query = Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Exists {
            field: "host".into(),
        },
    ]);
    let full = run(&index, &snapshot, query.clone(), Sort::default(), 100, None);
    let mut after = None;
    let mut paged = Vec::new();
    for _ in 0..10 {
        let response = run(&index, &snapshot, query.clone(), Sort::default(), 1, after);
        paged.extend(response.hits.iter().map(|hit| (hit.key.clone(), hit.score)));
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
    }
    assert_eq!(paged.len(), full.hits.len());
    for (paged, full) in paged.iter().zip(&full.hits) {
        assert_eq!(paged.0, full.key);
        assert_eq!(
            paged.1.expect("score").to_bits(),
            full.score.expect("score").to_bits()
        );
    }
}

// P06 — a cursor from a different snapshot is rejected before scanning.
#[test]
fn p06_different_snapshot_rejected() {
    let index = committed(tie_docs());
    let first = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let page = run(&index, &first, Query::MatchAll, sort.clone(), 1, None);
    let cursor = page.next_cursor.expect("continuation");
    let second = index.snapshot();
    let request = {
        let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(1).unwrap());
        request.sort = sort;
        request.after = Some(cursor);
        request
    };
    let error = UnifiedSearcher::new(&second, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(
        error,
        SearchError::Query(quervant_core::contract::error::QueryError::InvalidQuery(
            quervant_core::contract::error::InvalidQueryReason::CursorPitMismatch
        ))
    ));
}

// P07 — changed query or sort fingerprint is rejected.
#[test]
fn p07_changed_query_or_sort_rejected() {
    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let page = run(&index, &snapshot, Query::MatchAll, sort.clone(), 1, None);
    let cursor = page.next_cursor.expect("continuation");
    let assert_rejected = |query: Query, sort: Sort| {
        let mut request = UnifiedRequest::new(query, TopK::new(1).unwrap());
        request.sort = sort;
        request.after = Some(cursor.clone());
        let error =
            UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
                .search(&request, &Budgets::new(), &NeverCancel)
                .unwrap_err();
        assert!(matches!(
            error,
            SearchError::Query(quervant_core::contract::error::QueryError::InvalidQuery(
                quervant_core::contract::error::InvalidQueryReason::CursorSortMismatch
            ))
        ));
    };
    // Changed sort direction.
    assert_rejected(
        Query::MatchAll,
        Sort::new(vec![SortField::new("n", SortDirection::Desc)]),
    );
    // Changed sort field.
    assert_rejected(
        Query::MatchAll,
        Sort::new(vec![SortField::new("score", SortDirection::Asc)]),
    );
    // Changed query.
    assert_rejected(
        Query::Term {
            field: "n".into(),
            value: FieldValue::I64(1),
        },
        sort,
    );
}

// P08 — changing top_k and projection does not invalidate continuation.
#[test]
fn p08_top_k_and_projection_change_allowed() {
    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let page = run(&index, &snapshot, Query::MatchAll, sort.clone(), 2, None);
    let cursor = page.next_cursor.expect("continuation");
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(1).unwrap());
    request.sort = sort;
    request.projection = Projection::Fields(vec!["host".into()]);
    request.after = Some(cursor);
    UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("page size/projection change");
}

// P10 — delete/reinsert across segments returns one current version per key.
#[test]
fn p10_delete_reinsert_single_version() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        let mut original = doc("k");
        set(&mut original, "host", FieldValue::Keyword("old".into()));
        writer.insert(original).unwrap();
        writer.commit().unwrap();
    }
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("k").unwrap()))
            .unwrap();
        let mut replacement = doc("k");
        set(&mut replacement, "host", FieldValue::Keyword("new".into()));
        writer.insert(replacement).unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory);
    let snapshot = live.snapshot();
    let sort = Sort::new(vec![SortField::new("host", SortDirection::Asc)]);
    let response = run(&live, &snapshot, Query::MatchAll, sort, 1, None);
    assert_eq!(response.total_hits, 1);
    assert_eq!(response.hits.len(), 1);
    assert_eq!(
        response.hits[0].fields[0].1,
        FieldValues::Single(FieldValue::Keyword("new".into()))
    );
}

// P11 — cancellation during continuation returns no partial response.
#[test]
fn p11_continuation_cancellation() {
    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let page = run(&index, &snapshot, Query::MatchAll, sort.clone(), 1, None);
    let cursor = page.next_cursor.expect("continuation");
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(1).unwrap());
    request.sort = sort;
    request.after = Some(cursor);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Cancelled));
}

// P12 — batch public PIT cursors remain fail-closed (no resolver).
#[test]
fn p12_public_pit_cursor_still_rejected() {
    use quervant_core::contract::batch::{
        BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
    };
    use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};

    let index = committed(tie_docs());
    let snapshot = index.snapshot();
    let mut query = QueryRequest::new(Query::MatchAll);
    query.pit = Some(quervant_core::contract::result::PitId::new("pit").unwrap());
    query.cursor = Some(quervant_core::contract::result::Cursor::new(
        quervant_core::contract::result::PitId::new("pit").unwrap(),
        Sort::default(),
        DocumentKey::new("a").unwrap(),
        Timestamp::from_micros(10),
    ));
    let batch = BatchQueryRequest::new(vec![query], None, BatchBudget::new(4));
    let policy = BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 64)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 20)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    );
    let response = quervant_core::search::execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &policy,
        &quervant_core::contract::capability::CapabilitySet::new(),
        &NeverCancel,
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(_))
    ));
}
