//! PR 15A — local regression vertical over the frozen `pr15a_v1` fixture.
//!
//! Expected values come from the static record table in `pr15a_common`; the
//! production index/search/writer is only the system under test. Cursor and
//! mutation negative cases remain in their authoritative PR 14A/M5 suites and
//! are mapped in `docs/pr-artifacts/pr-15a/test-traceability.md`.

mod pr14_common;
mod pr15a_common;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use pr14_common::registry;
use pr15a_common::*;
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, ExactDistinct, GroupBy,
    GroupKey, TopKFrequency,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{DocumentKey, FieldValues, IdempotencyKey};
use quervant_core::contract::error::{CancelReason, InvalidQueryReason, QueryError};
use quervant_core::contract::mutation::{
    MutationAction, MutationBatch, MutationCommand, MutationTarget,
};
use quervant_core::contract::query::{Bound, JsonPathExpr, Query};
use quervant_core::contract::result::{Cursor, Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, IpNetwork, JsonValue, Timestamp};
use quervant_core::index::{Index, PitHandle, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
    execute_batch_pinned,
};

use pr14_common::schema;

const NOW: i64 = 1_000;
const DEADLINE: i64 = 10_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn unified(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn unified_request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"))
}

fn sorted_keys(response: &UnifiedResponse) -> Vec<String> {
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort_unstable();
    keys
}

fn expected_set(keys: &[&str]) -> BTreeSet<String> {
    keys.iter().map(|key| (*key).to_owned()).collect()
}

fn actual_set(keys: &[String]) -> BTreeSet<String> {
    keys.iter().cloned().collect()
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

fn query_request(query: Query, sort: Sort, top_k: usize) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.sort = sort;
    request.top_k = TopK::new(top_k).expect("top-k");
    request
}

fn batch(queries: Vec<QueryRequest>, pit: &PitHandle) -> BatchQueryRequest {
    BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(16))
}

fn pinned_run(
    pit: &PitHandle,
    queries: Vec<QueryRequest>,
    cancel: &dyn Cancellation,
) -> Result<quervant_core::contract::batch::BatchQueryResponse, SearchError> {
    execute_batch_pinned(
        pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch(queries, pit),
        &policy(),
        &CapabilitySet::new(),
        cancel,
        Timestamp::from_micros(NOW),
        Timestamp::from_micros(DEADLINE),
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

fn response_keys(response: &SearchResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn paginate(pit: &PitHandle, sort: Sort, page_size: usize) -> Vec<String> {
    let mut request = query_request(Query::MatchAll, sort, page_size);
    let mut seen = Vec::new();
    let mut cursor: Option<Cursor> = None;
    let mut pages = 0usize;
    loop {
        request.cursor = cursor.clone();
        let response = pinned_run(pit, vec![request.clone()], &CancellationFlag::new()).unwrap();
        let page = success(&response, 0);
        seen.extend(response_keys(page));
        pages += 1;
        cursor = page.next_cursor.clone();
        if cursor.is_none() {
            break;
        }
        assert!(pages < 100, "pagination did not terminate");
    }
    seen
}

fn run_aggregation(
    snapshot: &ReaderSnapshot,
    query: Query,
    aggregation: Aggregation,
    top_k: usize,
) -> SearchResponse {
    let mut request = QueryRequest::new(query);
    request.top_k = TopK::new(top_k).expect("top-k");
    request.aggregation = Some(aggregation);
    let response = execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![request], None, BatchBudget::new(4)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("aggregation batch");
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.clone(),
        other => panic!("aggregation slot failed: {other:?}"),
    }
}

fn group_counts(response: &SearchResponse) -> Vec<(String, u64, i128)> {
    let result = response.aggregation.as_ref().expect("aggregation");
    result
        .groups
        .iter()
        .map(|group| {
            let host = match &group.components[0] {
                AggregationGroupValue::Value(FieldValue::Keyword(host)) => host.clone(),
                other => panic!("unexpected group component {other:?}"),
            };
            let count = match group.metrics[0] {
                AggregationMetricValue::Count(count) => count,
                ref other => panic!("unexpected count {other:?}"),
            };
            let sum = match group.metrics[1] {
                AggregationMetricValue::Sum(
                    quervant_core::contract::aggregation::NumericAggregate::Signed(value),
                ) => value,
                ref other => panic!("unexpected sum {other:?}"),
            };
            (host, count, sum)
        })
        .collect()
}

fn live_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    unified(snapshot, &unified_request(Query::MatchAll, 256))
        .hits
        .into_iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn alpha_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    sorted_keys(&unified(
        snapshot,
        &unified_request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            10,
        ),
    ))
}

fn host_keys(snapshot: &ReaderSnapshot, host: &str) -> Vec<String> {
    sorted_keys(&unified(
        snapshot,
        &unified_request(
            Query::Term {
                field: "host".into(),
                value: FieldValue::Keyword(host.into()),
            },
            10,
        ),
    ))
}

fn alpha_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn mutated_batch() -> MutationBatch {
    MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("a1").expect("a1")),
            MutationAction::Upsert(mutated_a1()),
        ),
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("b1").expect("b1")),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("c0").expect("c0")),
            MutationAction::Insert(c0_document()),
        ),
    ])
    .with_idempotency_key(IdempotencyKey::new("pr15a-v1-mutation").expect("token"))
}

fn batch_response_keys(
    response: &quervant_core::contract::mutation::MutationBatchResponse,
) -> Vec<Vec<String>> {
    response
        .outcomes
        .iter()
        .map(|outcome| {
            outcome
                .keys
                .iter()
                .map(|key| key.key.as_str().to_owned())
                .collect()
        })
        .collect()
}

// ---------------------------------------------------------------------------
// A-T00 — frozen fixture and pure oracle
// ---------------------------------------------------------------------------

#[test]
fn a15_t00_frozen_fixture_and_pure_oracle() {
    assert_frozen_digest();

    // Every documented predicate is asserted against both the helper output and
    // a literal expectation, so a bug in the helper cannot change the answer.
    assert_eq!(
        oracle_sorted(Predicate::Alpha),
        vec!["a0", "a1", "b0", "b3"]
    );
    assert_eq!(
        oracle_sorted(Predicate::NAtLeast50),
        vec!["b0", "b1", "b2", "b3"]
    );
    assert_eq!(oracle_sorted(Predicate::AlphaAndN50), vec!["b0", "b3"]);
    assert_eq!(oracle_sorted(Predicate::HostH2), vec!["a1", "b1", "b3"]);
    assert_eq!(oracle_sorted(Predicate::Ipv4Cidr10), vec!["a0", "a1", "b3"]);
    assert_eq!(
        oracle_sorted(Predicate::TimeInclusive2000To5000),
        vec!["a1", "a2", "a3", "b0"]
    );
    assert_eq!(oracle_sorted(Predicate::AlphaAndHostH2), vec!["a1", "b3"]);
    assert_eq!(
        oracle_sorted(Predicate::NotAlpha),
        vec!["a2", "a3", "b1", "b2"]
    );
    assert_eq!(oracle_sorted(Predicate::SeverityTwo), vec!["a1", "b0"]);
    assert_eq!(oracle_sorted(Predicate::Ipv6Cidr2001Db8), vec!["a3", "b2"]);
    assert_eq!(
        oracle_group_counts(),
        BTreeMap::from([("h1", 3), ("h2", 3), ("h3", 2)])
    );
    assert_eq!(oracle_distinct_hosts(), 3);

    // Segment membership, insertion order and uniqueness are literal.
    let documents = base_documents();
    assert_eq!(documents.len(), 8);
    let keys: Vec<&str> = documents.iter().map(|doc| doc.key().as_str()).collect();
    assert_eq!(keys, OLD_KEYS);
    let unique: BTreeSet<&str> = keys.iter().copied().collect();
    assert_eq!(unique.len(), 8);
    let segment0_docs = segment0_documents();
    let segment1_docs = segment1_documents();
    let segment0: Vec<&str> = segment0_docs.iter().map(|doc| doc.key().as_str()).collect();
    let segment1: Vec<&str> = segment1_docs.iter().map(|doc| doc.key().as_str()).collect();
    assert_eq!(segment0, ["a0", "a1", "a2", "a3"]);
    assert_eq!(segment1, ["b0", "b1", "b2", "b3"]);

    // Intentional wrong-set negative: the oracle helper rejects an incomplete
    // alpha set. The suite stays green because the wrong set is asserted not
    // to equal the oracle result.
    let incomplete = ["a0", "a1", "b0"];
    assert_ne!(oracle_sorted(Predicate::Alpha), incomplete);
    assert!(!oracle_sorted(Predicate::Alpha).contains(&"a2"));
    assert_eq!(FIXTURE_VERSION, "pr15a_v1");
    assert!(CANONICAL_JSON.contains("\"version\": \"pr15a_v1\""));
}

// ---------------------------------------------------------------------------
// A-T01 — lexical term and mixed Boolean projection
// ---------------------------------------------------------------------------

#[test]
fn a15_t01_lexical_and_mixed_boolean_oracle() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let alpha = unified(&snapshot, &unified_request(alpha_query(), 10));
    assert_eq!(alpha.total_hits, 4);
    let alpha_keys = sorted_keys(&alpha);
    assert_eq!(alpha_keys, vec!["a0", "a1", "b0", "b3"]);
    assert_eq!(
        actual_set(&alpha_keys),
        expected_set(&["a0", "a1", "b0", "b3"])
    );
    assert_eq!(
        alpha_keys.len(),
        actual_set(&alpha_keys).len(),
        "lexical result must not contain duplicate keys"
    );
    for hit in &alpha.hits {
        let record = row(hit.key.as_str());
        let title = hit
            .fields
            .iter()
            .find(|(name, _)| name == "title")
            .map(|(_, values)| values.clone());
        assert_eq!(
            title,
            Some(FieldValues::Single(FieldValue::Text(
                record.title.to_owned()
            ))),
            "projection for {} must equal the frozen literal title",
            record.key
        );
    }

    let mixed = unified(
        &snapshot,
        &unified_request(
            Query::And(vec![
                alpha_query(),
                Query::Range {
                    field: "n".into(),
                    lower: Bound::Included(FieldValue::I64(50)),
                    upper: Bound::Unbounded,
                },
            ]),
            10,
        ),
    );
    assert_eq!(mixed.total_hits, 2);
    assert_eq!(sorted_keys(&mixed), vec!["b0", "b3"]);
}

// ---------------------------------------------------------------------------
// A-T02 — memory vs freshly reopened FsDirectory equivalence
// ---------------------------------------------------------------------------

#[test]
fn a15_t02_memory_and_fs_reopen_equivalence() {
    let memory_index = build_memory();
    let memory_snapshot = memory_index.snapshot();
    let (path, fs_index) = build_fs("t02");
    assert_eq!(fs_index.generation(), Some(2), "both segments committed");
    let fs_snapshot = fs_index.snapshot();

    let request = unified_request(alpha_query(), 10);
    let memory = unified(&memory_snapshot, &request);
    let fs = unified(&fs_snapshot, &request);
    assert_eq!(memory.total_hits, fs.total_hits);
    assert_eq!(memory.hits, fs.hits);
    assert_eq!(sorted_keys(&memory), sorted_keys(&fs));
    assert_eq!(fs.generation, Some(2));

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// A-T03 — absent term, Boolean composition and NOT
// ---------------------------------------------------------------------------

#[test]
fn a15_t03_absent_and_boolean_negatives() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let absent = Query::Term {
        field: "title".into(),
        value: FieldValue::Text("zeta".into()),
    };

    let none = unified(&snapshot, &unified_request(absent.clone(), 10));
    assert_eq!(none.total_hits, 0);
    assert!(none.hits.is_empty());

    let and_absent = unified(
        &snapshot,
        &unified_request(Query::And(vec![alpha_query(), absent.clone()]), 10),
    );
    assert_eq!(and_absent.total_hits, 0);

    let or_absent = unified(
        &snapshot,
        &unified_request(Query::Or(vec![alpha_query(), absent]), 10),
    );
    assert_eq!(or_absent.total_hits, 4);
    assert_eq!(sorted_keys(&or_absent), vec!["a0", "a1", "b0", "b3"]);

    let not_alpha = unified(
        &snapshot,
        &unified_request(Query::Not(Box::new(alpha_query())), 10),
    );
    assert_eq!(not_alpha.total_hits, 4);
    assert_eq!(sorted_keys(&not_alpha), vec!["a2", "a3", "b1", "b2"]);
    assert_ne!(not_alpha.total_hits, 8, "NOT must not degrade to MatchAll");

    let all = unified(&snapshot, &unified_request(Query::MatchAll, 10));
    assert_eq!(all.total_hits, 8);
}

// ---------------------------------------------------------------------------
// A-T04 — CIDR and timestamp window
// ---------------------------------------------------------------------------

#[test]
fn a15_t04_cidr_and_time_range() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let cidr = unified(
        &snapshot,
        &unified_request(
            Query::IpInCidr {
                field: "ip".into(),
                network: IpNetwork::new("10.0.0.0".parse().expect("ipv4"), 24).expect("cidr"),
            },
            10,
        ),
    );
    assert_eq!(cidr.total_hits, 3);
    assert_eq!(sorted_keys(&cidr), vec!["a0", "a1", "b3"]);

    let time = unified(
        &snapshot,
        &unified_request(
            Query::TimeRange {
                field: "ts".into(),
                start: Timestamp::from_micros(2000),
                end: Timestamp::from_micros(5001),
            },
            10,
        ),
    );
    assert_eq!(time.total_hits, 4);
    assert_eq!(sorted_keys(&time), vec!["a1", "a2", "a3", "b0"]);

    // Existing half-open contract: end=5000 excludes b0.
    let half_open = unified(
        &snapshot,
        &unified_request(
            Query::TimeRange {
                field: "ts".into(),
                start: Timestamp::from_micros(2000),
                end: Timestamp::from_micros(5000),
            },
            10,
        ),
    );
    assert_eq!(sorted_keys(&half_open), vec!["a1", "a2", "a3"]);
}

// ---------------------------------------------------------------------------
// A-T05 — JSON path scalar predicate and stored source
// ---------------------------------------------------------------------------

#[test]
fn a15_t05_json_scalar_and_source_states() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let severity_two = unified(
        &snapshot,
        &unified_request(
            Query::JsonPathEquals {
                field: "body".into(),
                path: JsonPathExpr::parse("$.severity").expect("path"),
                value: FieldValue::I64(2),
            },
            10,
        ),
    );
    assert_eq!(severity_two.total_hits, 2);
    assert_eq!(sorted_keys(&severity_two), vec!["a1", "b0"]);

    let tagged = unified(
        &snapshot,
        &unified_request(
            Query::JsonPathArrayContains {
                field: "body".into(),
                path: JsonPathExpr::parse("$.tags")
                    .expect("path")
                    .to_concrete()
                    .expect("concrete"),
                value: FieldValue::Text("red".into()),
            },
            10,
        ),
    );
    assert_eq!(sorted_keys(&tagged), vec!["a0", "b0"]);

    let all = unified(&snapshot, &unified_request(Query::MatchAll, 10));
    assert_eq!(all.total_hits, 8);
    for hit in &all.hits {
        let record = row(hit.key.as_str());
        let body = hit
            .fields
            .iter()
            .find(|(name, _)| name == "body")
            .map(|(_, values)| values.clone());
        assert_eq!(
            body,
            Some(FieldValues::Single(FieldValue::Json(pr15a_common::body(
                record
            )))),
            "stored JSON for {} must preserve null/absent/empty-array states",
            record.key
        );
    }

    let a3 = row("a3");
    let JsonValue::Object(entries) = pr15a_common::body(a3) else {
        panic!("a3 body must be an object");
    };
    assert!(matches!(
        entries
            .iter()
            .find(|(name, _)| name == "severity")
            .map(|(_, value)| value),
        Some(JsonValue::Null)
    ));
    assert!(
        entries.iter().all(|(name, _)| name != "tags"),
        "a3 must not gain a tags key"
    );
    let b1 = row("b1");
    let JsonValue::Object(entries) = pr15a_common::body(b1) else {
        panic!("b1 body must be an object");
    };
    assert!(entries.iter().all(|(name, _)| name != "tags"));
    let b2 = row("b2");
    let JsonValue::Object(entries) = pr15a_common::body(b2) else {
        panic!("b2 body must be an object");
    };
    assert!(matches!(
        entries
            .iter()
            .find(|(name, _)| name == "tags")
            .map(|(_, value)| value),
        Some(JsonValue::Array(values)) if values.is_empty()
    ));
}

// ---------------------------------------------------------------------------
// A-T06 — IP family separation, JSON scalar-kind/null and typed failures
// ---------------------------------------------------------------------------

#[test]
fn a15_t06_ip_family_json_states_and_typed_failures() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let ipv6 = unified(
        &snapshot,
        &unified_request(
            Query::IpInCidr {
                field: "ip".into(),
                network: IpNetwork::new("2001:db8::".parse().expect("ipv6"), 32).expect("cidr"),
            },
            10,
        ),
    );
    assert_eq!(sorted_keys(&ipv6), vec!["a3", "b2"]);
    let ipv4 = unified(
        &snapshot,
        &unified_request(
            Query::IpInCidr {
                field: "ip".into(),
                network: IpNetwork::new("0.0.0.0".parse().expect("ipv4"), 0).expect("cidr"),
            },
            10,
        ),
    );
    // IPv4 /0 contains every IPv4 row and never an IPv6 row.
    assert_eq!(sorted_keys(&ipv4), vec!["a0", "a1", "a2", "b0", "b1", "b3"]);

    let string_two = unified(
        &snapshot,
        &unified_request(
            Query::JsonPathEquals {
                field: "body".into(),
                path: JsonPathExpr::parse("$.severity").expect("path"),
                value: FieldValue::Text("2".into()),
            },
            10,
        ),
    );
    assert_eq!(
        string_two.total_hits, 0,
        "JSON scalar kinds are distinct; the string \"2\" is not the number 2"
    );

    let missing_value = unified(
        &snapshot,
        &unified_request(
            Query::JsonPathEquals {
                field: "body".into(),
                path: JsonPathExpr::parse("$.severity").expect("path"),
                value: FieldValue::I64(99),
            },
            10,
        ),
    );
    assert_eq!(
        missing_value.total_hits, 0,
        "explicit null and absent JSON values never match a scalar equality"
    );

    let wrong_field =
        UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default()).search(
            &unified_request(
                Query::IpInCidr {
                    field: "title".into(),
                    network: IpNetwork::new("10.0.0.0".parse().expect("ipv4"), 24).expect("cidr"),
                },
                10,
            ),
            &Budgets::new(),
            &CancellationFlag::new(),
        );
    assert!(matches!(
        wrong_field,
        Err(SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::UnsupportedOperator { ref field, operator: "type" }
        ))) if field == "title"
    ));

    let inverted_time =
        UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default()).search(
            &unified_request(
                Query::TimeRange {
                    field: "ts".into(),
                    start: Timestamp::from_micros(5000),
                    end: Timestamp::from_micros(2000),
                },
                10,
            ),
            &Budgets::new(),
            &CancellationFlag::new(),
        );
    assert!(matches!(
        inverted_time,
        Err(SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::InvalidTimeRange { .. }
        )))
    ));
}

// ---------------------------------------------------------------------------
// A-T07 — grouped metrics, exact distinct and frequency top-K
// ---------------------------------------------------------------------------

#[test]
fn a15_t07_groups_metrics_and_exact_distinct() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let grouped = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let response = run_aggregation(&snapshot, Query::MatchAll, grouped, 100);
    assert_eq!(response.total_hits, 8);
    assert_eq!(
        group_counts(&response),
        vec![
            ("h1".to_owned(), 3, 90),
            ("h2".to_owned(), 3, 160),
            ("h3".to_owned(), 2, 110),
        ]
    );

    let global = Aggregation {
        group_by: None,
        aggregates: vec![Aggregate::count()],
        exact_distinct: Some(ExactDistinct {
            field: "host".into(),
        }),
        top_k: Some(TopKFrequency {
            field: "host".into(),
            k: 2,
        }),
        time_bucket: None,
    };
    let response = run_aggregation(&snapshot, Query::MatchAll, global, 10);
    let result = response.aggregation.as_ref().expect("aggregation");
    assert_eq!(result.groups.len(), 1);
    let group = &result.groups[0];
    assert!(matches!(group.metrics[0], AggregationMetricValue::Count(8)));
    assert!(matches!(
        group.metrics[1],
        AggregationMetricValue::ExactDistinct(3)
    ));
    let frequencies = group.frequencies.as_ref().expect("frequencies");
    assert_eq!(frequencies.len(), 2);
    assert_eq!(frequencies[0].value, FieldValue::Keyword("h1".into()));
    assert_eq!(frequencies[0].count, 3);
    assert_eq!(frequencies[1].value, FieldValue::Keyword("h2".into()));
    assert_eq!(frequencies[1].count, 3);
}

// ---------------------------------------------------------------------------
// A-T08 — ties, empty grouping and top-K prefix
// ---------------------------------------------------------------------------

#[test]
fn a15_t08_ties_empty_groups_and_top_k() {
    let index = build_memory();
    let snapshot = index.snapshot();

    let tie_sort = Sort::new(vec![SortField::new("host", SortDirection::Asc)]);
    let mut tie_request = unified_request(Query::MatchAll, 10);
    tie_request.sort = tie_sort.clone();
    let tied = unified(&snapshot, &tie_request);
    assert_eq!(
        tied.hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>(),
        vec!["a0", "a2", "b0", "a1", "b1", "b3", "a3", "b2"],
        "host ties break by canonical key order"
    );

    let one = Aggregation {
        group_by: None,
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: Some(TopKFrequency {
            field: "host".into(),
            k: 1,
        }),
        time_bucket: None,
    };
    let response = run_aggregation(&snapshot, Query::MatchAll, one, 10);
    let frequencies = response.aggregation.as_ref().expect("aggregation").groups[0]
        .frequencies
        .as_ref()
        .expect("frequencies");
    assert_eq!(frequencies.len(), 1);
    assert_eq!(frequencies[0].value, FieldValue::Keyword("h1".into()));
    assert_eq!(frequencies[0].count, 3);

    let empty = Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    };
    let response = run_aggregation(
        &snapshot,
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("zeta".into()),
        },
        empty,
        10,
    );
    assert!(
        response
            .aggregation
            .as_ref()
            .expect("aggregation")
            .groups
            .is_empty(),
        "grouped empty match must return zero correct groups"
    );

    let n_asc = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let mut small = unified_request(Query::MatchAll, 3);
    small.sort = n_asc.clone();
    let mut full = unified_request(Query::MatchAll, 8);
    full.sort = n_asc;
    let small_keys = unified(&snapshot, &small)
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect::<Vec<_>>();
    let full_keys = unified(&snapshot, &full)
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect::<Vec<_>>();
    assert_eq!(small_keys, full_keys[..3]);
}

// ---------------------------------------------------------------------------
// A-T09 — pinned pagination concatenation
// ---------------------------------------------------------------------------

#[test]
fn a15_t09_pinned_pages_concatenate_exactly() {
    let (_path, index) = build_fs("t09");
    let pit = index.pin().expect("pit");
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    for page_size in [1usize, 2, 3, 8] {
        let keys = paginate(&pit, sort.clone(), page_size);
        assert_eq!(
            keys, N_ASCENDING_KEYS,
            "page size {page_size} must concatenate to the full ordered result"
        );
        let unique: BTreeSet<&String> = keys.iter().collect();
        assert_eq!(
            unique.len(),
            keys.len(),
            "no duplicate keys at page size {page_size}"
        );
    }

    // The first page yields a snapshot-bound continuation token. The test never
    // reads cursor internals; resumption is the opacity witness.
    let first = pinned_run(
        &pit,
        vec![query_request(Query::MatchAll, sort, 2)],
        &CancellationFlag::new(),
    )
    .expect("first page");
    let continuation = success(&first, 0)
        .next_cursor
        .clone()
        .expect("continuation");
    let mut resume = query_request(
        Query::MatchAll,
        Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
        2,
    );
    resume.cursor = Some(continuation);
    let second = pinned_run(&pit, vec![resume], &CancellationFlag::new()).expect("second page");
    assert_eq!(response_keys(success(&second, 0)), vec!["a2", "a3"]);
}

// ---------------------------------------------------------------------------
// A-T11 — durable generation-3 mutation and replay
// ---------------------------------------------------------------------------

#[test]
fn a15_t11_generation_three_mutation_and_replay() {
    let (path, index) = build_fs("t11");
    assert_eq!(index.generation(), Some(2));
    let batch = mutated_batch();
    let mut writer = index.writer().expect("writer");
    let first = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("mutation batch");
    assert!(!first.replayed);
    assert_eq!(
        batch_response_keys(&first),
        vec![
            vec!["a1".to_owned()],
            vec!["b1".to_owned()],
            vec!["c0".to_owned()]
        ]
    );
    writer.commit().expect("commit generation 3");
    drop(writer);
    drop(index);

    let reopened = reopen_fs(&path);
    assert_eq!(reopened.generation(), Some(3));
    let snapshot = reopened.snapshot();
    assert_eq!(live_keys(&snapshot), NEW_LIVE_KEYS);
    assert_eq!(alpha_keys(&snapshot), NEW_ALPHA_KEYS);
    assert_eq!(host_keys(&snapshot, "h2"), NEW_HOST_H2);
    drop(snapshot);

    let mut writer = reopened.writer().expect("writer");
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("replay");
    assert!(replay.replayed);
    assert_eq!(batch_response_keys(&replay), batch_response_keys(&first));
    assert_eq!(writer.generation(), Some(3), "replay adds no generation");
    writer.refresh().expect("refresh");
    assert_eq!(live_keys(&writer.reader()), NEW_LIVE_KEYS);
    assert_eq!(writer.pending_mutations(), 0);
    drop(writer);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// A-T13 — retained old PIT across mutation and compaction
// ---------------------------------------------------------------------------

#[test]
fn a15_t13_retained_pit_is_immutable() {
    let (path, index) = build_fs("t13");
    let old_pit = index.pin().expect("old pit");
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let old = pinned_run(
        &old_pit,
        vec![query_request(Query::MatchAll, sort.clone(), 50)],
        &CancellationFlag::new(),
    )
    .expect("old snapshot");
    assert_eq!(response_keys(success(&old, 0)), OLD_KEYS);

    let mut writer = index.writer().expect("writer");
    writer
        .apply_batch(&mutated_batch(), &CancellationFlag::new())
        .expect("mutation");
    writer.refresh().expect("refresh");
    writer.commit().expect("commit");
    writer.compact().expect("compaction");
    drop(writer);

    let mut projected = query_request(Query::MatchAll, sort.clone(), 50);
    projected.projection = Projection::Fields(vec!["host".into(), "n".into()]);
    let old_after = pinned_run(&old_pit, vec![projected], &CancellationFlag::new())
        .expect("old snapshot after mutation");
    let page = success(&old_after, 0);
    assert_eq!(response_keys(page), OLD_KEYS);
    let a1 = page
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "a1")
        .expect("a1 in old snapshot");
    assert_eq!(
        a1.fields
            .iter()
            .find(|(name, _)| name == "host")
            .map(|(_, values)| values.clone()),
        Some(FieldValues::Single(FieldValue::Keyword("h2".into())))
    );
    assert_eq!(
        a1.fields
            .iter()
            .find(|(name, _)| name == "n")
            .map(|(_, values)| values.clone()),
        Some(FieldValues::Single(FieldValue::I64(20)))
    );

    let new = reopen_fs(&path);
    assert!(
        new.generation().expect("generation") > 2,
        "mutation commit and compaction advance beyond generation 2"
    );
    let new_pit = new.pin().expect("new pit");
    let new_page = pinned_run(
        &new_pit,
        vec![query_request(Query::MatchAll, sort, 50)],
        &CancellationFlag::new(),
    )
    .expect("new snapshot");
    assert_eq!(response_keys(success(&new_page, 0)), NEW_LIVE_KEYS);
    let snapshot = new.snapshot();
    assert_eq!(alpha_keys(&snapshot), NEW_ALPHA_KEYS);
    assert_eq!(host_keys(&snapshot, "h2"), NEW_HOST_H2);

    drop(new_pit);
    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// A-T14 — stale reader vs a newly opened handle
// ---------------------------------------------------------------------------

#[test]
fn a15_t14_stale_reader_cannot_see_new_commit() {
    let (path, index) = build_fs("t14");
    let stale = index.snapshot();
    let stale_generation = stale.generation();

    let mut writer = index.writer().expect("writer");
    writer
        .apply_batch(&mutated_batch(), &CancellationFlag::new())
        .expect("mutation");
    writer.commit().expect("commit");
    drop(writer);
    drop(index);

    assert_eq!(stale_generation, Some(2));
    assert_eq!(stale.generation(), Some(2), "old snapshot is immutable");
    assert_eq!(live_keys(&stale), OLD_KEYS);
    assert!(
        !live_keys(&stale).contains(&"c0".to_owned()),
        "stale reader must not see c0"
    );

    let fresh = reopen_fs(&path);
    assert_eq!(fresh.generation(), Some(3));
    let fresh_snapshot = fresh.snapshot();
    assert_eq!(live_keys(&fresh_snapshot), NEW_LIVE_KEYS);
    assert!(live_keys(&fresh_snapshot).contains(&"c0".to_owned()));
    assert_ne!(
        stale.generation(),
        fresh_snapshot.generation(),
        "generations must not be silently substituted"
    );

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// A-T17 — cancellation around a multi-slot pinned batch
// ---------------------------------------------------------------------------

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
fn a15_t17_cancellation_is_slot_local() {
    let (_path, index) = build_fs("t17");
    let pit = index.pin().expect("pit");
    let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);

    let polls = Arc::new(AtomicUsize::new(0));
    let response = pinned_run(
        &pit,
        vec![query_request(Query::MatchAll, sort.clone(), 2)],
        &CountPolls(Arc::clone(&polls)),
    )
    .expect("warm poll count");
    assert!(success(&response, 0).next_cursor.is_some());
    let total = polls.load(Ordering::SeqCst);
    assert!(total > 0, "a successful slot must poll cancellation");

    let cancel = TripAfter {
        skip: total,
        polls: Arc::new(AtomicUsize::new(0)),
    };
    let response = pinned_run(
        &pit,
        vec![
            query_request(Query::MatchAll, sort.clone(), 2),
            query_request(Query::MatchAll, sort, 2),
        ],
        &cancel,
    )
    .expect("batch result");
    assert_eq!(response.len(), 2);
    let first = success(&response, 0);
    assert_eq!(response_keys(first), vec!["a0", "a1"]);
    assert!(first.next_cursor.is_some());
    assert_eq!(
        response.slot(1),
        Some(&PerQueryOutcome::Failure(QueryError::Cancelled {
            reason: CancelReason::ClientCancellation
        })),
        "cancelled slot must be typed and must not report partial success"
    );
}

// Keep the `Index` and `Arc` imports meaningful for the shared helpers.
#[allow(dead_code)]
fn _type_anchors(_: &Index, _: &Arc<dyn quervant_core::storage::Directory>) {}
