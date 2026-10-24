//! PR 14A — public PIT-bound batch search-after.
//!
//! All pagination runs through the public `execute_batch_pinned` seam against a
//! real `FsDirectory` index and a retained `PitHandle`. Expected order is a
//! test-owned table over the predeclared fixture; the production comparator is
//! never used to compute it.

mod pr14_common;

use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use pr14_common::{doc, registry, schema, set, set_multi, set_null};
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::aggregation::{Aggregate, Aggregation, GroupBy, GroupKey};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey};
use quervant_core::contract::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{
    Cursor, PitId, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexLimits, PitHandle};
use quervant_core::search::{SearchError, SearchLimits, execute_batch, execute_batch_pinned};
use quervant_core::storage::{Directory, FsDirectory};

const NOW: i64 = 1_000;
const DEADLINE: i64 = 10_000;

struct TestDir(std::path::PathBuf);

impl TestDir {
    fn new(tag: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "quervant-pr14a-{}-{tag}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Copy)]
struct Row {
    key: &'static str,
    n: Option<i64>,
    n_null: bool,
    host: &'static str,
    ts: i64,
    score: f64,
    ip: &'static str,
}

const ROWS: &[Row] = &[
    Row {
        key: "k00",
        n: Some(10),
        n_null: false,
        host: "h1",
        ts: 10,
        score: -0.0,
        ip: "192.0.2.1",
    },
    Row {
        key: "k01",
        n: Some(20),
        n_null: false,
        host: "h2",
        ts: 20,
        score: 0.0,
        ip: "192.0.2.2",
    },
    Row {
        key: "k02",
        n: Some(30),
        n_null: false,
        host: "h1",
        ts: 30,
        score: 1.0,
        ip: "192.0.2.3",
    },
    Row {
        key: "k03",
        n: Some(40),
        n_null: false,
        host: "h2",
        ts: 40,
        score: 1.0,
        ip: "2001:db8::1",
    },
    Row {
        key: "k04",
        n: Some(50),
        n_null: false,
        host: "h3",
        ts: 50,
        score: 2.0,
        ip: "2001:db8::2",
    },
    Row {
        key: "k05",
        n: Some(60),
        n_null: false,
        host: "h1",
        ts: 60,
        score: 2.0,
        ip: "192.0.2.4",
    },
    Row {
        key: "k06",
        n: Some(10),
        n_null: false,
        host: "h2",
        ts: 70,
        score: 3.0,
        ip: "192.0.2.5",
    },
    Row {
        key: "k07",
        n: Some(10),
        n_null: false,
        host: "h1",
        ts: 80,
        score: 3.0,
        ip: "192.0.2.6",
    },
    Row {
        key: "k08",
        n: None,
        n_null: false,
        host: "h4",
        ts: 90,
        score: -1.0,
        ip: "2001:db8::3",
    },
    Row {
        key: "k09",
        n: None,
        n_null: true,
        host: "h1",
        ts: 100,
        score: -2.0,
        ip: "192.0.2.7",
    },
    Row {
        key: "k10",
        n: Some(70),
        n_null: false,
        host: "h5",
        ts: 110,
        score: 0.5,
        ip: "192.0.2.8",
    },
    Row {
        key: "k11",
        n: Some(80),
        n_null: false,
        host: "h6",
        ts: 120,
        score: 0.5,
        ip: "192.0.2.9",
    },
];

fn json(n: i64) -> JsonValue {
    JsonValue::Object(vec![
        ("n".into(), JsonValue::Number(JsonNumber::I64(n))),
        ("k".into(), JsonValue::Number(JsonNumber::I64(n * 2))),
    ])
}

fn fixture() -> Vec<Document> {
    ROWS.iter()
        .map(|row| {
            let mut document = doc(row.key);
            let title = if row.n.unwrap_or(-1) % 2 == 0 {
                "alpha beta"
            } else {
                "gamma"
            };
            set(&mut document, "title", FieldValue::Text(title.into()));
            match (row.n, row.n_null) {
                (Some(n), _) => set(&mut document, "n", FieldValue::I64(n)),
                (None, true) => set_null(&mut document, "n"),
                (None, false) => {}
            }
            set(&mut document, "host", FieldValue::Keyword(row.host.into()));
            set(
                &mut document,
                "ts",
                FieldValue::Timestamp(Timestamp::from_micros(row.ts)),
            );
            set(&mut document, "score", FieldValue::F64(row.score));
            set(
                &mut document,
                "body",
                FieldValue::Json(json(row.n.unwrap_or(0))),
            );
            set(
                &mut document,
                "loc",
                FieldValue::GeoPoint(GeoPoint::new(0.1, 0.1).unwrap()),
            );
            set(&mut document, "ip", FieldValue::Ip(row.ip.parse().unwrap()));
            set_multi(
                &mut document,
                "tags",
                vec![FieldValue::Keyword(row.host.into())],
            );
            document
        })
        .collect()
}

fn build_index(tag: &str) -> (TestDir, Index) {
    let dir = TestDir::new(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&dir.0).unwrap());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    let docs = fixture();
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().take(5) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().skip(5) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    (dir, reopened)
}

fn policy_with(response: u64, memory: u64, work: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, response)
            .unwrap()
            .with(BudgetKind::BatchAggregate, work)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn policy() -> BudgetPolicy {
    policy_with(1 << 30, 1 << 30, 1 << 30)
}

fn request(query: Query, sort: Sort, top_k: usize) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.sort = sort;
    request.top_k = TopK::new(top_k).unwrap();
    request
}

fn batch(queries: Vec<QueryRequest>, pit: &PitHandle) -> BatchQueryRequest {
    BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(16))
}

fn run(
    pit: &PitHandle,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
    now: i64,
    deadline: i64,
) -> Result<quervant_core::contract::batch::BatchQueryResponse, SearchError> {
    execute_batch_pinned(
        pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch(queries, pit),
        policy,
        &CapabilitySet::new(),
        &CancellationFlag::new(),
        Timestamp::from_micros(now),
        Timestamp::from_micros(deadline),
    )
}

fn success(
    response: &quervant_core::contract::batch::BatchQueryResponse,
    slot: usize,
) -> &SearchResponse {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response,
        other => panic!("slot {slot} was not successful: {other:?}"),
    }
}

fn keys(response: &SearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn expected_n_host(n_desc: bool, host_desc: bool) -> Vec<String> {
    let mut rows: Vec<&Row> = ROWS.iter().collect();
    rows.sort_by(|a, b| {
        let rank = |row: &Row| match (row.n, row.n_null) {
            (Some(_), _) => 0,
            (None, true) => 1,
            (None, false) => 2,
        };
        let by_n = rank(a).cmp(&rank(b)).then_with(|| match (a.n, b.n) {
            (Some(a), Some(b)) => {
                if n_desc {
                    b.cmp(&a)
                } else {
                    a.cmp(&b)
                }
            }
            _ => std::cmp::Ordering::Equal,
        });
        if by_n != std::cmp::Ordering::Equal {
            return by_n;
        }
        let by_host = if host_desc {
            b.host.cmp(a.host)
        } else {
            a.host.cmp(b.host)
        };
        by_host.then_with(|| a.key.cmp(b.key))
    });
    rows.into_iter().map(|row| row.key.to_owned()).collect()
}

fn expected_n_only() -> Vec<String> {
    let mut rows: Vec<&Row> = ROWS.iter().collect();
    rows.sort_by(|a, b| {
        let rank = |row: &Row| match (row.n, row.n_null) {
            (Some(_), _) => 0,
            (None, true) => 1,
            (None, false) => 2,
        };
        rank(a)
            .cmp(&rank(b))
            .then_with(|| match (a.n, b.n) {
                (Some(a), Some(b)) => a.cmp(&b),
                _ => std::cmp::Ordering::Equal,
            })
            .then_with(|| a.key.cmp(b.key))
    });
    rows.into_iter().map(|row| row.key.to_owned()).collect()
}

fn expected_ts_ip() -> Vec<String> {
    let mut rows: Vec<&Row> = ROWS.iter().collect();
    rows.sort_by(|a, b| {
        a.ts.cmp(&b.ts).then_with(|| {
            let a_ip: std::net::IpAddr = a.ip.parse().unwrap();
            let b_ip: std::net::IpAddr = b.ip.parse().unwrap();
            b_ip.cmp(&a_ip).then_with(|| a.key.cmp(b.key))
        })
    });
    rows.into_iter().map(|row| row.key.to_owned()).collect()
}

fn expected_score() -> Vec<String> {
    let mut rows: Vec<&Row> = ROWS.iter().collect();
    rows.sort_by(|a, b| a.score.total_cmp(&b.score).then_with(|| a.key.cmp(b.key)));
    rows.into_iter().map(|row| row.key.to_owned()).collect()
}

fn paginate(
    pit: &PitHandle,
    query: Query,
    sort: Sort,
    page_size: usize,
) -> (Vec<String>, Vec<f32>, Option<u64>) {
    let mut request = request(query, sort, page_size);
    let mut seen = Vec::new();
    let mut scores = Vec::new();
    let mut cursor: Option<Cursor> = None;
    let mut pages = 0;
    loop {
        request.cursor = cursor.clone();
        let response = run(pit, vec![request.clone()], &policy(), NOW, DEADLINE).unwrap();
        let page = success(&response, 0);
        seen.extend(keys(page));
        scores.extend(page.hits.iter().map(|hit| hit.score.unwrap_or(f32::NAN)));
        pages += 1;
        cursor = page.next_cursor.clone();
        if cursor.is_none() {
            break;
        }
        assert!(pages < 100, "continuation did not terminate");
    }
    (seen, scores, Some(pages))
}

fn assert_no_duplicates(order: &[String], label: &str) {
    let unique: BTreeSet<&String> = order.iter().collect();
    assert_eq!(unique.len(), order.len(), "{label}: duplicate keys");
}

#[test]
fn t01_naked_snapshot_rejects_pit_and_cursor_before_slots() {
    let (_dir, index) = build_index("t01");
    let pit = index.pin().unwrap();
    let snapshot = index.snapshot();
    let mut plain = request(Query::MatchAll, Sort::default(), 3);
    let response = execute_batch(
        &snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![plain.clone()], None, BatchBudget::new(4)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));

    let shared = BatchQueryRequest::new(
        vec![plain.clone()],
        Some(pit.id().clone()),
        BatchBudget::new(4),
    );
    assert!(matches!(
        execute_batch(
            &snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &shared,
            &policy(),
            &CapabilitySet::new(),
            &CancellationFlag::new(),
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::PinnedContextRequired
        )))
    ));
    plain.pit = Some(pit.id().clone());
    let own = BatchQueryRequest::new(vec![plain.clone()], None, BatchBudget::new(4));
    assert!(matches!(
        execute_batch(
            &snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &own,
            &policy(),
            &CapabilitySet::new(),
            &CancellationFlag::new(),
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::PinnedContextRequired
        )))
    ));
    let legacy = Cursor::new(
        pit.id().clone(),
        Sort::default(),
        DocumentKey::new("k00").unwrap(),
        Timestamp::from_micros(DEADLINE),
    );
    let mut cursor_request = request(Query::MatchAll, Sort::default(), 2);
    cursor_request.cursor = Some(legacy);
    let cursor_batch = BatchQueryRequest::new(vec![cursor_request], None, BatchBudget::new(4));
    assert!(matches!(
        execute_batch(
            &snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &cursor_batch,
            &policy(),
            &CapabilitySet::new(),
            &CancellationFlag::new(),
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::PinnedContextRequired
        )))
    ));
}

#[test]
fn t02_two_field_pages_are_exact_and_metamorphic() {
    let (_dir, index) = build_index("t02");
    let pit = index.pin().unwrap();
    for (n_desc, host_desc) in [(false, true), (true, false)] {
        let expected = expected_n_host(n_desc, host_desc);
        for page_size in [1, 2, 3, 20] {
            let sort = Sort::new(vec![
                SortField::new(
                    "n",
                    if n_desc {
                        SortDirection::Desc
                    } else {
                        SortDirection::Asc
                    },
                ),
                SortField::new(
                    "host",
                    if host_desc {
                        SortDirection::Desc
                    } else {
                        SortDirection::Asc
                    },
                ),
            ]);
            let (order, _, _) = paginate(&pit, Query::MatchAll, sort, page_size);
            assert_eq!(order, expected, "page_size={page_size}");
            assert_no_duplicates(&order, "two-field pages");
        }
    }
}

#[test]
fn t03_typed_tuples_missing_null_keyword_time_ip_and_negative_zero() {
    let (_dir, index) = build_index("t03");
    let pit = index.pin().unwrap();
    let expected_missing = expected_n_host(false, true);
    for page_size in [1, 2, 5, 12, 20] {
        let (order, _, _) = paginate(
            &pit,
            Query::MatchAll,
            Sort::new(vec![
                SortField::new("n", SortDirection::Asc),
                SortField::new("host", SortDirection::Desc),
            ]),
            page_size,
        );
        assert_eq!(order, expected_missing);
    }
    let expected_time = expected_ts_ip();
    let (order, _, _) = paginate(
        &pit,
        Query::MatchAll,
        Sort::new(vec![
            SortField::new("ts", SortDirection::Asc),
            SortField::new("ip", SortDirection::Desc),
        ]),
        2,
    );
    assert_eq!(order, expected_time);
    let expected_scores = expected_score();
    let (order, _, _) = paginate(
        &pit,
        Query::MatchAll,
        Sort::new(vec![SortField::new("score", SortDirection::Asc)]),
        3,
    );
    assert_eq!(order, expected_scores);
    assert_eq!(order[0], "k09", "-2.0 must sort first");
}

#[test]
fn t04_relevance_pages_match_full_unpaginated_search_and_score_bits() {
    let (_dir, index) = build_index("t04");
    let pit = index.pin().unwrap();
    let relevance = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    };
    let full = run(
        &pit,
        vec![request(relevance.clone(), Sort::default(), 100)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    let full = success(&full, 0);
    let (order, scores, _) = paginate(&pit, relevance, Sort::default(), 2);
    assert_eq!(order, keys(full));
    for (actual, expected) in scores.iter().zip(full.hits.iter()) {
        assert_eq!(actual.to_bits(), expected.score.unwrap().to_bits());
    }
}

fn mixed_query() -> Query {
    Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
        Query::JsonPathRange {
            field: "body".into(),
            path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
            lower: Bound::Included(FieldValue::I64(1)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
        },
        Query::In {
            field: "ip".into(),
            values: vec![FieldValue::Ip("192.0.2.1".parse().unwrap())],
        },
    ])
}

#[test]
fn t05_mixed_filter_aggregation_and_projection_are_page_size_invariant() {
    let (_dir, index) = build_index("t05");
    let pit = index.pin().unwrap();
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let mut full_request = request(mixed_query(), Sort::default(), 100);
    full_request.aggregation = Some(aggregation.clone());
    full_request.projection = Projection::Fields(vec!["title".into(), "host".into(), "n".into()]);
    let full = run(&pit, vec![full_request.clone()], &policy(), NOW, DEADLINE).unwrap();
    let full = success(&full, 0).clone();
    assert!(full.total_hits > 0);
    for page_size in [1, 2, 5] {
        let mut request = full_request.clone();
        request.top_k = TopK::new(page_size).unwrap();
        let mut order = Vec::new();
        let mut cursor = None;
        loop {
            request.cursor = cursor.clone();
            let response = run(&pit, vec![request.clone()], &policy(), NOW, DEADLINE).unwrap();
            let page = success(&response, 0);
            assert_eq!(page.total_hits, full.total_hits);
            assert_eq!(page.aggregation, full.aggregation);
            for hit in &page.hits {
                assert_eq!(
                    hit.fields,
                    full.hits
                        .iter()
                        .find(|candidate| candidate.key == hit.key)
                        .unwrap()
                        .fields
                );
            }
            order.extend(keys(page));
            cursor = page.next_cursor.clone();
            if cursor.is_none() {
                break;
            }
        }
        assert_eq!(order, keys(&full), "page_size={page_size}");
    }
}

#[test]
fn t06_wrong_handle_and_snapshot_binding_fail_without_fallback() {
    let (dir, index) = build_index("t06");
    let pit_a = index.pin().unwrap();
    let first = run(
        &pit_a,
        vec![request(Query::MatchAll, Sort::default(), 2)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&dir.0).unwrap());
    let index_b = Index::open_existing(directory, schema(), registry()).unwrap();
    let pit_b = index_b.pin().unwrap();
    assert_eq!(pit_a.snapshot().generation(), pit_b.snapshot().generation());
    assert_ne!(pit_a.snapshot().binding_id(), pit_b.snapshot().binding_id());

    let mut wrong_cursor = request(Query::MatchAll, Sort::default(), 2);
    wrong_cursor.cursor = Some(cursor.clone());
    let response = run(&pit_b, vec![wrong_cursor], &policy(), NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorPitMismatch
        )))
    ));

    let mut wrong_shared = request(Query::MatchAll, Sort::default(), 2);
    wrong_shared.cursor = Some(cursor);
    let mismatched = BatchQueryRequest::new(
        vec![wrong_shared],
        Some(pit_a.id().clone()),
        BatchBudget::new(4),
    );
    assert!(matches!(
        execute_batch_pinned(
            &pit_b,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &mismatched,
            &policy(),
            &CapabilitySet::new(),
            &CancellationFlag::new(),
            Timestamp::from_micros(NOW),
            Timestamp::from_micros(DEADLINE),
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::ConflictingPit
        )))
    ));
}

#[test]
fn t07_query_and_sort_mismatch_fail_typed() {
    let (_dir, index) = build_index("t07");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let first = run(
        &pit,
        vec![request(Query::MatchAll, sort.clone(), 2)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();

    let mut changed_query = request(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        sort.clone(),
        2,
    );
    changed_query.cursor = Some(cursor.clone());
    let response = run(&pit, vec![changed_query], &policy(), NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorSortMismatch
        )))
    ));

    let mut changed_sort = request(
        Query::MatchAll,
        Sort::new(vec![SortField::new("host", SortDirection::Desc)]),
        2,
    );
    changed_sort.cursor = Some(cursor);
    let response = run(&pit, vec![changed_sort], &policy(), NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorSortMismatch
        )))
    ));
}

#[test]
fn t08_three_slot_batch_isolates_cursor_failure_in_input_order() {
    let (_dir, index) = build_index("t08");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let first = run(
        &pit,
        vec![request(Query::MatchAll, sort.clone(), 2)],
        &policy(),
        NOW,
        NOW + 10,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let mut expired = request(Query::MatchAll, sort.clone(), 2);
    expired.cursor = Some(cursor);
    let queries = vec![
        request(Query::MatchAll, sort.clone(), 2),
        expired,
        request(Query::MatchAll, sort, 2),
    ];
    let response = run(&pit, queries, &policy(), NOW + 10, NOW + 20).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert_eq!(
        response.slot(1),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

#[test]
fn t09_retained_pit_survives_mutation_refresh_commit_and_compaction() {
    let (_dir, index) = build_index("t09");
    let old_pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let first = run(
        &old_pit,
        vec![request(Query::MatchAll, sort.clone(), 3)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let old_prefix = keys(success(&first, 0));

    let mut writer = index.writer().unwrap();
    let mut updated = doc("k00");
    set(&mut updated, "n", FieldValue::I64(999));
    set(&mut updated, "title", FieldValue::Text("updated".into()));
    set(&mut updated, "host", FieldValue::Keyword("h9".into()));
    set(
        &mut updated,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(999)),
    );
    set(&mut updated, "score", FieldValue::F64(9.0));
    set(&mut updated, "body", FieldValue::Json(json(999)));
    set(
        &mut updated,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.1, 0.1).unwrap()),
    );
    set(
        &mut updated,
        "ip",
        FieldValue::Ip("192.0.2.1".parse().unwrap()),
    );
    set_multi(&mut updated, "tags", vec![FieldValue::Keyword("h9".into())]);
    writer
        .apply(quervant_core::contract::document::MutationRequest::upsert(
            updated,
        ))
        .unwrap();
    writer
        .apply(quervant_core::contract::document::MutationRequest::delete(
            DocumentKey::new("k01").unwrap(),
        ))
        .unwrap();
    let mut inserted = doc("k12");
    set(&mut inserted, "n", FieldValue::I64(5));
    set(&mut inserted, "title", FieldValue::Text("inserted".into()));
    set(&mut inserted, "host", FieldValue::Keyword("h0".into()));
    set(
        &mut inserted,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(5)),
    );
    set(&mut inserted, "score", FieldValue::F64(5.0));
    set(&mut inserted, "body", FieldValue::Json(json(5)));
    set(
        &mut inserted,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.1, 0.1).unwrap()),
    );
    set(
        &mut inserted,
        "ip",
        FieldValue::Ip("192.0.2.1".parse().unwrap()),
    );
    set_multi(
        &mut inserted,
        "tags",
        vec![FieldValue::Keyword("h0".into())],
    );
    writer.insert(inserted).unwrap();
    writer.refresh().unwrap();
    writer.commit().unwrap();
    writer.compact().unwrap();
    drop(writer);

    let mut cursor = Some(cursor);
    let mut old_all = old_prefix;
    while let Some(existing) = cursor {
        let mut resume_request = request(Query::MatchAll, sort.clone(), 3);
        resume_request.cursor = Some(existing);
        let response = run(&old_pit, vec![resume_request], &policy(), NOW, DEADLINE).unwrap();
        let page = success(&response, 0);
        old_all.extend(keys(page));
        cursor = page.next_cursor.clone();
    }
    assert_eq!(old_all, expected_n_only());

    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&_dir.0).unwrap());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    assert!(reopened.generation().unwrap() > old_pit.snapshot().generation().unwrap());
    let new_pit = reopened.pin().unwrap();
    let full = run(
        &new_pit,
        vec![request(Query::MatchAll, sort, 100)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    let new_keys = keys(success(&full, 0));
    assert!(new_keys.contains(&"k12".to_owned()));
    assert!(!new_keys.contains(&"k01".to_owned()));
    assert_eq!(new_keys[0], "k12");
    assert_eq!(
        new_keys[new_keys.len() - 3],
        "k00",
        "updated n=999 sorts after all present low values but before null/missing"
    );
    assert_eq!(
        &new_keys[new_keys.len() - 2..],
        ["k09".to_owned(), "k08".to_owned()]
    );
}

#[test]
fn t10_expiry_boundaries_and_no_renewal() {
    let (_dir, index) = build_index("t10");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let first = run(
        &pit,
        vec![request(Query::MatchAll, sort.clone(), 2)],
        &policy(),
        NOW,
        NOW + 10,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let mut resume = request(Query::MatchAll, sort.clone(), 2);
    resume.cursor = Some(cursor.clone());
    assert!(run(&pit, vec![resume.clone()], &policy(), NOW + 9, NOW + 10).is_ok());

    let mut at_expiry = resume.clone();
    at_expiry.cursor = Some(cursor.clone());
    let response = run(&pit, vec![at_expiry], &policy(), NOW + 10, NOW + 20).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );

    let mut renewed = resume.clone();
    renewed.cursor = Some(cursor.clone());
    let response = run(&pit, vec![renewed], &policy(), NOW + 1, NOW + 1_000).unwrap();
    let next = success(&response, 0).next_cursor.clone().unwrap();
    let mut after_original_expiry = request(Query::MatchAll, sort.clone(), 2);
    after_original_expiry.cursor = Some(next);
    let response = run(
        &pit,
        vec![after_original_expiry],
        &policy(),
        NOW + 10,
        NOW + 1_000,
    )
    .unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );

    assert!(matches!(
        run(
            &pit,
            vec![request(Query::MatchAll, sort.clone(), 2)],
            &policy(),
            NOW,
            NOW
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::InvalidCursorDeadline
        )))
    ));
    let legacy = Cursor::new(
        pit.id().clone(),
        sort.clone(),
        DocumentKey::new("k00").unwrap(),
        Timestamp::from_micros(NOW + 10),
    );
    let mut legacy_request = request(Query::MatchAll, sort, 2);
    legacy_request.cursor = Some(legacy);
    let response = run(&pit, vec![legacy_request], &policy(), NOW, NOW + 10).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorSortMismatch
        )))
    ));
}

fn cursor_logical_bytes_for_test(pit: &PitId, key: &str, sort_field: &str) -> u64 {
    let mut bytes = 8 + 8 + pit.as_str().len() as u64;
    let mut sort_bytes = 16;
    sort_bytes += 8 + sort_field.len() as u64 + 3;
    bytes += sort_bytes;
    bytes += 8 + key.len() as u64;
    bytes += 8 + 9;
    bytes += 8; // atom count
    bytes += 9; // one I64 atom
    bytes
}

fn response_charge(pit: &PitId, key: &str, sort_field: &str) -> u64 {
    32 + 24 + key.len() as u64 + 8 + cursor_logical_bytes_for_test(pit, key, sort_field)
}

#[test]
fn t11_response_and_memory_budgets_include_cursor_exactly_once() {
    let (_dir, index) = build_index("t11");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let mut probe = request(Query::MatchAll, sort.clone(), 1);
    probe.projection = Projection::Fields(Vec::new());
    let response = run(&pit, vec![probe.clone()], &policy(), NOW, DEADLINE).unwrap();
    let page = success(&response, 0);
    let key = page.hits[0].key.as_str().to_owned();
    assert!(page.next_cursor.is_some());
    let charge = response_charge(pit.id(), &key, "n");

    // Response bytes are fully documented by the test-owned formula above.
    let response_exact = policy_with(charge, 1 << 30, 1 << 30);
    let response = run(&pit, vec![probe.clone()], &response_exact, NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));

    // Memory also includes the executor's peak candidate/projection retention.
    // Find its exact boundary on the real path rather than pretending that the
    // response-byte formula is the whole memory peak.
    let mut low = 1u64;
    let mut high = 1u64 << 16;
    while low < high {
        let mid = (low + high) / 2;
        let probe_policy = policy_with(1 << 30, mid, 1 << 30);
        let response = run(&pit, vec![probe.clone()], &probe_policy, NOW, DEADLINE).unwrap();
        if matches!(response.slot(0), Some(PerQueryOutcome::Success(_))) {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    let memory_charge = low;
    let memory_exact = policy_with(1 << 30, memory_charge, 1 << 30);
    let response = run(&pit, vec![probe.clone()], &memory_exact, NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));

    let over_memory = policy_with(1 << 30, memory_charge - 1, 1 << 30);
    let response = run(&pit, vec![probe.clone()], &over_memory, NOW, DEADLINE).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }))
    );

    let over_response = policy_with(charge - 1, 1 << 30, 1 << 30);
    let response = run(&pit, vec![probe.clone()], &over_response, NOW, DEADLINE).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchResponseBytes
        }))
    );
}

struct CountPolls(Arc<AtomicUsize>);

impl Cancellation for CountPolls {
    fn is_cancelled(&self) -> bool {
        self.0.fetch_add(1, Ordering::SeqCst);
        false
    }
}

struct TripAfter {
    skip: usize,
    polls: Arc<AtomicUsize>,
}

impl Cancellation for TripAfter {
    fn is_cancelled(&self) -> bool {
        self.polls.fetch_add(1, Ordering::SeqCst) >= self.skip
    }
}

#[test]
fn t13_cancellation_after_prior_success_is_slot_local_and_emits_no_cursor() {
    let (_dir, index) = build_index("t13");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let one = vec![request(Query::MatchAll, sort.clone(), 2)];
    let polls = Arc::new(AtomicUsize::new(0));
    execute_batch_pinned(
        &pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch(one, &pit),
        &policy(),
        &CapabilitySet::new(),
        &CountPolls(Arc::clone(&polls)),
        Timestamp::from_micros(NOW),
        Timestamp::from_micros(DEADLINE),
    )
    .unwrap();
    let total = polls.load(Ordering::SeqCst);
    assert!(total > 0, "a successful slot must poll cancellation");

    let queries = vec![
        request(Query::MatchAll, sort.clone(), 2),
        request(Query::MatchAll, sort, 2),
    ];
    let cancel = TripAfter {
        skip: total,
        polls: Arc::new(AtomicUsize::new(0)),
    };
    let response = execute_batch_pinned(
        &pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch(queries, &pit),
        &policy(),
        &CapabilitySet::new(),
        &cancel,
        Timestamp::from_micros(NOW),
        Timestamp::from_micros(DEADLINE),
    )
    .unwrap();
    assert_eq!(response.len(), 2);
    let first = success(&response, 0);
    assert!(first.next_cursor.is_some());
    assert_eq!(
        response.slot(1),
        Some(&PerQueryOutcome::Failure(QueryError::Cancelled {
            reason: quervant_core::contract::error::CancelReason::ClientCancellation
        }))
    );
}

// ===========================================================================
// PR 14A Correction 01 — JSON sort-path cursor accounting
// ===========================================================================

fn long_member(member_len: usize) -> String {
    "a".repeat(member_len)
}

fn long_path(member_len: usize) -> JsonPathExpr {
    JsonPathExpr::parse(&format!("$.{}", long_member(member_len))).unwrap()
}

fn long_json_doc(key: &str, member: &str, n: i64) -> Document {
    let mut document = doc(key);
    set(
        &mut document,
        "body",
        FieldValue::Json(JsonValue::Object(vec![(
            member.to_owned(),
            JsonValue::Number(JsonNumber::I64(n)),
        )])),
    );
    document
}

fn build_long_json_index(tag: &str, member_len: usize) -> (TestDir, Index) {
    let dir = TestDir::new(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&dir.0).unwrap());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let member = long_member(member_len);
    {
        let mut writer = index.writer().unwrap();
        for (key, n) in [("k00", 30), ("k01", 10), ("k02", 20)] {
            writer.insert(long_json_doc(key, &member, n)).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    (dir, reopened)
}

fn long_path_request(member_len: usize, top_k: usize) -> QueryRequest {
    let mut request = request(
        Query::MatchAll,
        Sort::new(vec![
            SortField::new("body", SortDirection::Asc).with_json_path(long_path(member_len)),
        ]),
        top_k,
    );
    request.projection = Projection::Fields(Vec::new());
    request
}

/// Independent logical response charge for one hit with an empty projection
/// and one I64 cursor atom.
fn long_path_response_charge(pit: &PitId, key: &str, member_len: usize) -> u64 {
    let path_charge = 24 + 24 + member_len as u64;
    let sort_charge = 16 + (8 + "body".len() as u64 + 3) + path_charge;
    let cursor_charge =
        8 + 8 + pit.as_str().len() as u64 + sort_charge + 8 + key.len() as u64 + 8 + 9 + 8 + 9;
    let hit_charge = 32 + 24 + key.len() as u64 + 8;
    hit_charge + cursor_charge
}

fn min_memory_for(pit: &PitHandle, queries: Vec<QueryRequest>) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 20;
    while low < high {
        let mid = (low + high) / 2;
        let probe = policy_with(1 << 30, mid, 1 << 30);
        let response = run(pit, queries.clone(), &probe, NOW, DEADLINE).unwrap();
        let all_success = (0..queries.len())
            .all(|slot| matches!(response.slot(slot), Some(PerQueryOutcome::Success(_))));
        if all_success {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

#[test]
fn t07_json_path_long_member_response_boundary() {
    const MEMBER_LEN: usize = 256;
    let (_dir, index) = build_long_json_index("t07", MEMBER_LEN);
    let pit = index.pin().unwrap();
    let request = long_path_request(MEMBER_LEN, 1);
    let probe = run(&pit, vec![request.clone()], &policy(), NOW, DEADLINE).unwrap();
    let page = success(&probe, 0);
    assert_eq!(
        keys(page),
        ["k01".to_owned()],
        "numeric JSON values, not key order, must determine the first page"
    );
    assert!(page.next_cursor.is_some(), "one-hit page must continue");

    let charge = long_path_response_charge(pit.id(), "k01", MEMBER_LEN);
    let exact = policy_with(charge, 1 << 30, 1 << 30);
    let response = run(&pit, vec![request.clone()], &exact, NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));

    let over = policy_with(charge - 1, 1 << 30, 1 << 30);
    let response = run(&pit, vec![request.clone()], &over, NOW, DEADLINE).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchResponseBytes
        }))
    );

    let mut cursor = page.next_cursor.clone();
    let mut continuation = Vec::new();
    while let Some(existing) = cursor {
        let mut next = request.clone();
        next.cursor = Some(existing);
        let response = run(&pit, vec![next], &policy(), NOW, DEADLINE).unwrap();
        let page = success(&response, 0);
        continuation.extend(keys(page));
        cursor = page.next_cursor.clone();
    }
    assert_eq!(continuation, ["k02".to_owned(), "k00".to_owned()]);
}

#[test]
fn t08_json_path_long_member_memory_boundary_and_sibling_rollback() {
    const MEMBER_LEN: usize = 256;
    let (_dir, index) = build_long_json_index("t08", MEMBER_LEN);
    let pit = index.pin().unwrap();
    let one = long_path_request(MEMBER_LEN, 1);
    let one_charge = min_memory_for(&pit, vec![one.clone()]);

    let exact = policy_with(1 << 30, one_charge, 1 << 30);
    let response = run(&pit, vec![one.clone()], &exact, NOW, DEADLINE).unwrap();
    let page = success(&response, 0);
    assert!(page.next_cursor.is_some());
    assert_eq!(keys(page), ["k01".to_owned()]);

    let under = policy_with(1 << 30, one_charge - 1, 1 << 30);
    let response = run(&pit, vec![one.clone()], &under, NOW, DEADLINE).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }))
    );

    let two_charge = min_memory_for(&pit, vec![one.clone(), one.clone()]);
    assert!(
        two_charge > one_charge,
        "two successful cursor slots must retain more than one"
    );
    let sibling_limit = two_charge - 1;
    let sibling_policy = policy_with(1 << 30, sibling_limit, 1 << 30);
    let response = run(&pit, vec![one.clone(), one], &sibling_policy, NOW, DEADLINE).unwrap();
    assert_eq!(response.len(), 2);
    let first = success(&response, 0);
    assert_eq!(keys(first), ["k01".to_owned()]);
    assert!(first.next_cursor.is_some());
    assert_eq!(
        response.slot(1),
        Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }))
    );
}

#[test]
fn t09_non_json_cursor_regressions_remain_unchanged() {
    let (_dir, index) = build_index("t09-correction");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let (order, _, _) = paginate(&pit, Query::MatchAll, sort.clone(), 3);
    assert_eq!(order, expected_n_only());
    let first = run(
        &pit,
        vec![request(Query::MatchAll, sort.clone(), 2)],
        &policy(),
        NOW,
        NOW + 10,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let mut resume = request(Query::MatchAll, sort.clone(), 2);
    resume.cursor = Some(cursor.clone());
    assert!(run(&pit, vec![resume], &policy(), NOW + 9, NOW + 10).is_ok());
    let mut expired = request(Query::MatchAll, sort.clone(), 2);
    expired.cursor = Some(cursor);
    let response = run(&pit, vec![expired], &policy(), NOW + 10, NOW + 20).unwrap();
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );
    let mut wrong_query = request(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        sort.clone(),
        2,
    );
    let first_cursor = success(
        &run(
            &pit,
            vec![request(Query::MatchAll, sort.clone(), 2)],
            &policy(),
            NOW,
            DEADLINE,
        )
        .unwrap(),
        0,
    )
    .next_cursor
    .clone()
    .unwrap();
    wrong_query.cursor = Some(first_cursor);
    let response = run(&pit, vec![wrong_query], &policy(), NOW, DEADLINE).unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorSortMismatch
        )))
    ));
}

// ===========================================================================
// PR 14A Correction 02 — unified JSON-path sort semantics
// ===========================================================================

fn json_num(value: i64) -> JsonValue {
    JsonValue::Number(JsonNumber::I64(value))
}

fn json_row(
    key: &str,
    title: &str,
    n: Option<i64>,
    n_null: bool,
    m: i64,
    lon: f64,
    arr: [i64; 2],
) -> Document {
    let mut document = doc(key);
    set(&mut document, "title", FieldValue::Text(title.into()));
    set(&mut document, "host", FieldValue::Keyword("h1".into()));
    let mut body = vec![("m".to_owned(), json_num(m))];
    match (n, n_null) {
        (Some(value), _) => body.push(("n".to_owned(), json_num(value))),
        (None, true) => body.push(("n".to_owned(), JsonValue::Null)),
        (None, false) => {}
    }
    body.push((
        "arr".to_owned(),
        JsonValue::Array(
            arr.iter()
                .map(|value| JsonValue::Object(vec![("v".to_owned(), json_num(*value))]))
                .collect(),
        ),
    ));
    set(
        &mut document,
        "body",
        FieldValue::Json(JsonValue::Object(body)),
    );
    set(
        &mut document,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(lon, 0.0).unwrap()),
    );
    document
}

fn json_fixture() -> Vec<Document> {
    vec![
        json_row("k00", "alpha", Some(30), false, 1, 0.0, [5, 2]),
        json_row("k01", "alpha", Some(10), false, 3, 1.0, [1, 9]),
        json_row("k02", "beta", Some(20), false, 2, 2.0, [4, 3]),
        json_row("k03", "alpha", Some(10), false, 4, 3.0, [8, 7]),
        json_row("k04", "alpha", None, false, 5, 4.0, [6, 0]),
        json_row("k05", "alpha", None, true, 6, 5.0, [2, 2]),
        json_row("k06", "gamma", Some(20), false, 7, 6.0, [9, 1]),
    ]
}

fn build_json_index(tag: &str) -> (TestDir, Index) {
    let dir = TestDir::new(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&dir.0).unwrap());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let docs = json_fixture();
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().take(3) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().skip(3) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    (dir, reopened)
}

fn json_path_sort(field: &str, path: &str, direction: SortDirection) -> Sort {
    Sort::new(vec![
        SortField::new(field, direction).with_json_path(JsonPathExpr::parse(path).unwrap()),
    ])
}

fn run_limits(
    pit: &PitHandle,
    queries: Vec<QueryRequest>,
    policy: &BudgetPolicy,
    limits: SearchLimits,
    now: i64,
    deadline: i64,
) -> Result<quervant_core::contract::batch::BatchQueryResponse, SearchError> {
    execute_batch_pinned(
        pit,
        &schema(),
        &registry(),
        limits,
        &batch(queries, pit),
        policy,
        &CapabilitySet::new(),
        &CancellationFlag::new(),
        Timestamp::from_micros(now),
        Timestamp::from_micros(deadline),
    )
}

fn direct_unified(pit: &PitHandle, query: Query, sort: Sort, top_k: usize) -> Vec<String> {
    let request = quervant_core::search::UnifiedRequest {
        query,
        sort,
        top_k: TopK::new(top_k).unwrap(),
        projection: Projection::Source,
        after: None,
    };
    let response = quervant_core::search::UnifiedSearcher::new(
        pit.snapshot().as_ref(),
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &CancellationFlag::new())
    .unwrap();
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

#[test]
fn j01_unified_json_path_numeric_ascending() {
    let (_dir, index) = build_json_index("j01");
    let pit = index.pin().unwrap();
    let order = direct_unified(
        &pit,
        Query::MatchAll,
        json_path_sort("body", "$.n", SortDirection::Asc),
        20,
    );
    assert_eq!(order, ["k01", "k03", "k02", "k06", "k00", "k05", "k04"]);
}

#[test]
fn j02_json_path_descending_and_page_sizes() {
    let (_dir, index) = build_json_index("j02");
    let pit = index.pin().unwrap();
    let expected = ["k00", "k02", "k06", "k01", "k03", "k05", "k04"];
    for top_k in [1, 2, 3, 20] {
        let (order, _, _) = paginate(
            &pit,
            Query::MatchAll,
            json_path_sort("body", "$.n", SortDirection::Desc),
            top_k,
        );
        assert_eq!(order, expected, "top_k={top_k}");
    }
}

#[test]
fn j03_second_field_json_sort_and_tie_key() {
    let (_dir, index) = build_json_index("j03");
    let pit = index.pin().unwrap();
    let sort = Sort::new(vec![
        SortField::new("host", SortDirection::Asc),
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.n").unwrap()),
    ]);
    assert_eq!(
        direct_unified(&pit, Query::MatchAll, sort.clone(), 20),
        ["k01", "k03", "k02", "k06", "k00", "k05", "k04"]
    );
    let (paged, _, _) = paginate(&pit, Query::MatchAll, sort, 2);
    assert_eq!(paged, ["k01", "k03", "k02", "k06", "k00", "k05", "k04"]);
}

#[test]
fn j04_json_missing_null_ascending_and_descending() {
    let (_dir, index) = build_json_index("j04");
    let pit = index.pin().unwrap();
    assert_eq!(
        direct_unified(
            &pit,
            Query::MatchAll,
            json_path_sort("body", "$.n", SortDirection::Asc),
            20,
        ),
        ["k01", "k03", "k02", "k06", "k00", "k05", "k04"]
    );
    assert_eq!(
        direct_unified(
            &pit,
            Query::MatchAll,
            json_path_sort("body", "$.n", SortDirection::Desc),
            20,
        ),
        ["k00", "k02", "k06", "k01", "k03", "k05", "k04"]
    );
}

#[test]
fn j05_json_wildcard_min_max_and_selector_requirement() {
    let (_dir, index) = build_json_index("j05");
    let pit = index.pin().unwrap();
    let min_sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.arr[*].v").unwrap())
            .with_multi(quervant_core::contract::result::MultiValueSelector::Min),
    ]);
    assert_eq!(
        direct_unified(&pit, Query::MatchAll, min_sort, 20),
        ["k04", "k01", "k06", "k00", "k05", "k02", "k03"]
    );
    let max_sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.arr[*].v").unwrap())
            .with_multi(quervant_core::contract::result::MultiValueSelector::Max),
    ]);
    assert_eq!(
        direct_unified(&pit, Query::MatchAll, max_sort, 20),
        ["k05", "k02", "k00", "k04", "k03", "k01", "k06"]
    );
    let missing_selector = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.arr[*].v").unwrap()),
    ]);
    let request = quervant_core::search::UnifiedRequest {
        query: Query::MatchAll,
        sort: missing_selector,
        top_k: TopK::new(5).unwrap(),
        projection: Projection::Source,
        after: None,
    };
    assert!(
        quervant_core::search::UnifiedSearcher::new(
            pit.snapshot().as_ref(),
            &schema(),
            &registry(),
            SearchLimits::default(),
        )
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .is_err()
    );
}

#[test]
fn j06_mixed_lexical_json_sort_and_aggregation() {
    let (_dir, index) = build_json_index("j06");
    let pit = index.pin().unwrap();
    let query = Query::And(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::JsonPathRange {
            field: "body".into(),
            path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
    ]);
    let aggregation = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let mut full = request(
        query.clone(),
        json_path_sort("body", "$.n", SortDirection::Asc),
        100,
    );
    full.aggregation = Some(aggregation.clone());
    let full_response = run(&pit, vec![full.clone()], &policy(), NOW, DEADLINE).unwrap();
    let full = success(&full_response, 0).clone();
    assert_eq!(keys(&full), ["k01", "k03", "k00"]);

    for page_size in [1, 2] {
        let mut page_request = request(
            query.clone(),
            json_path_sort("body", "$.n", SortDirection::Asc),
            page_size,
        );
        page_request.aggregation = Some(aggregation.clone());
        let mut cursor = None;
        let mut order = Vec::new();
        loop {
            page_request.cursor = cursor;
            let response = run(&pit, vec![page_request.clone()], &policy(), NOW, DEADLINE).unwrap();
            let page = success(&response, 0);
            assert_eq!(page.aggregation, full.aggregation);
            order.extend(keys(page));
            cursor = page.next_cursor.clone();
            if cursor.is_none() {
                break;
            }
        }
        assert_eq!(order, keys(&full));
    }
}

#[test]
fn j08_json_pit_stable_across_mutation_and_compaction() {
    let (_dir, index) = build_json_index("j08");
    let old_pit = index.pin().unwrap();
    let sort = json_path_sort("body", "$.n", SortDirection::Asc);
    let (old_before, _, _) = paginate(&old_pit, Query::MatchAll, sort.clone(), 2);
    assert_eq!(
        old_before,
        ["k01", "k03", "k02", "k06", "k00", "k05", "k04"]
    );

    let mut writer = index.writer().unwrap();
    let mut updated = doc("k01");
    set(&mut updated, "title", FieldValue::Text("alpha".into()));
    set(&mut updated, "host", FieldValue::Keyword("h1".into()));
    set(
        &mut updated,
        "body",
        FieldValue::Json(JsonValue::Object(vec![
            ("n".to_owned(), json_num(99)),
            ("m".to_owned(), json_num(3)),
        ])),
    );
    set(
        &mut updated,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(1.0, 0.0).unwrap()),
    );
    writer
        .apply(quervant_core::contract::document::MutationRequest::upsert(
            updated,
        ))
        .unwrap();
    writer
        .apply(quervant_core::contract::document::MutationRequest::delete(
            DocumentKey::new("k02").unwrap(),
        ))
        .unwrap();
    let mut inserted = doc("k07");
    set(&mut inserted, "title", FieldValue::Text("alpha".into()));
    set(&mut inserted, "host", FieldValue::Keyword("h1".into()));
    set(
        &mut inserted,
        "body",
        FieldValue::Json(JsonValue::Object(vec![("n".to_owned(), json_num(15))])),
    );
    set(
        &mut inserted,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(7.0, 0.0).unwrap()),
    );
    writer.insert(inserted).unwrap();
    writer.refresh().unwrap();
    writer.commit().unwrap();
    writer.compact().unwrap();
    drop(writer);

    let (old_after, _, _) = paginate(&old_pit, Query::MatchAll, sort.clone(), 2);
    assert_eq!(old_after, old_before);

    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&_dir.0).unwrap());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let new_pit = reopened.pin().unwrap();
    assert_eq!(
        direct_unified(&new_pit, Query::MatchAll, sort, 20),
        ["k03", "k07", "k06", "k00", "k01", "k05", "k04"]
    );
}

#[test]
fn j09_bad_json_sort_fails_typed() {
    let (_dir, index) = build_json_index("j09");
    let pit = index.pin().unwrap();
    let bad = Sort::new(vec![
        SortField::new("title", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.n").unwrap()),
    ]);
    let response = run(
        &pit,
        vec![request(Query::MatchAll, bad, 4)],
        &policy(),
        NOW,
        DEADLINE,
    )
    .unwrap();
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(_)))
    ));
}

#[test]
fn j10_json_work_limit_exact_and_one_under() {
    let (_dir, index) = build_json_index("j10");
    let pit = index.pin().unwrap();
    let sort = json_path_sort("body", "$.n", SortDirection::Asc);
    let query = request(Query::MatchAll, sort, 20);
    let mut low = 1u64;
    let mut high = 1u64 << 20;
    while low < high {
        let mid = (low + high) / 2;
        let limits = SearchLimits::default()
            .with_max_total_work_units(mid)
            .unwrap();
        let response =
            run_limits(&pit, vec![query.clone()], &policy(), limits, NOW, DEADLINE).unwrap();
        if matches!(response.slot(0), Some(PerQueryOutcome::Success(_))) {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    let exact = SearchLimits::default()
        .with_max_total_work_units(low)
        .unwrap();
    assert!(matches!(
        run_limits(&pit, vec![query.clone()], &policy(), exact, NOW, DEADLINE)
            .unwrap()
            .slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    let under = SearchLimits::default()
        .with_max_total_work_units(low - 1)
        .unwrap();
    assert!(matches!(
        run_limits(&pit, vec![query], &policy(), under, NOW, DEADLINE)
            .unwrap()
            .slot(0),
        Some(PerQueryOutcome::Failure(
            QueryError::ExecutionFailure { .. }
        )) | Some(PerQueryOutcome::Failure(QueryError::BudgetExceeded { .. }))
    ));
}

#[test]
fn j11_json_three_slot_failure_isolated() {
    let (_dir, index) = build_json_index("j11");
    let pit = index.pin().unwrap();
    let sort = json_path_sort("body", "$.n", SortDirection::Asc);
    let first = run(
        &pit,
        vec![request(Query::MatchAll, sort.clone(), 2)],
        &policy(),
        NOW,
        NOW + 10,
    )
    .unwrap();
    let cursor = success(&first, 0).next_cursor.clone().unwrap();
    let mut expired = request(Query::MatchAll, sort.clone(), 2);
    expired.cursor = Some(cursor);
    let response = run(
        &pit,
        vec![
            request(Query::MatchAll, sort.clone(), 2),
            expired,
            request(Query::MatchAll, sort, 2),
        ],
        &policy(),
        NOW + 10,
        NOW + 20,
    )
    .unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert_eq!(
        response.slot(1),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

#[test]
fn j12_geo_distance_and_plain_column_sort_regression() {
    let (_dir, index) = build_json_index("j12");
    let pit = index.pin().unwrap();
    let geo_sort = Sort::new(vec![SortField::geo_distance(
        "loc",
        GeoPoint::new(0.0, 0.0).unwrap(),
        SortDirection::Asc,
    )]);
    assert_eq!(
        direct_unified(&pit, Query::MatchAll, geo_sort, 20),
        ["k00", "k01", "k02", "k03", "k04", "k05", "k06"]
    );
    assert_eq!(
        direct_unified(
            &pit,
            Query::MatchAll,
            Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
            20,
        )
        .len(),
        7
    );
}
