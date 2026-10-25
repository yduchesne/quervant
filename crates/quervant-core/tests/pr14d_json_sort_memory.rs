//! PR 14D — JSON sort transient-memory governance (D01–D10, D15 local).
//!
//! These tests prove that the JSON-path sort path admits its transient scratch
//! through the existing batch memory meter **before** the buffers grow, that
//! exact/one-under admission is deterministic, that ordering is unchanged for
//! the canonical comparator, and that cancellation/error paths release every
//! reservation. Allocator-window observations (D14) live in
//! `pr14b_json_memory.rs`; real-provider cases (D11–D12) live in
//! `pr14_storage_vertical.rs`.
//!
//! Expected values are hand-authored from the fixture model; the production
//! comparator is never used to compute an oracle.

mod pr14_common;

use std::sync::Arc;

use pr14_common::{
    FieldValue, committed, doc, registry, request, schema, set, set_multi, typed_search,
};
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::error::QueryError;
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::result::{
    MultiValueSelector, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::value::{JsonNumber, JsonValue, Timestamp};
use quervant_core::index::ReaderSnapshot;
use quervant_core::search::{SearchLimits, execute_batch, execute_batch_pinned};
use sha2::{Digest, Sha256};

fn body_with(value: i64) -> FieldValue {
    FieldValue::Json(JsonValue::Object(vec![(
        "v".to_owned(),
        JsonValue::Number(JsonNumber::I64(value)),
    )]))
}

fn occurrence_doc(key: &str, count: usize) -> quervant_core::contract::document::Document {
    let events: Vec<JsonValue> = (0..count)
        .map(|index| {
            JsonValue::Object(vec![(
                "v".to_owned(),
                JsonValue::Number(JsonNumber::I64(index as i64)),
            )])
        })
        .collect();
    let body = JsonValue::Object(vec![("events".to_owned(), JsonValue::Array(events))]);
    let mut document = doc(key);
    set(&mut document, "body", FieldValue::Json(body));
    document
}

fn json_sort_request(
    query: Query,
    selector: MultiValueSelector,
    direction: SortDirection,
    top_k: usize,
) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.sort = Sort::new(vec![
        SortField::new("body", direction)
            .with_json_path(JsonPathExpr::parse("$.events[*].v").unwrap())
            .with_multi(selector),
    ]);
    request.top_k = TopK::new(top_k).unwrap();
    request.projection = Projection::Fields(Vec::new());
    request
}

fn v_sort_request(
    query: Query,
    selector: MultiValueSelector,
    direction: SortDirection,
) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.sort = Sort::new(vec![
        SortField::new("body", direction)
            .with_json_path(JsonPathExpr::parse("$.v").unwrap())
            .with_multi(selector),
    ]);
    request.top_k = TopK::new(50).unwrap();
    request.projection = Projection::Fields(Vec::new());
    request
}

fn mbody_sort_request(
    query: Query,
    selector: MultiValueSelector,
    direction: SortDirection,
) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.sort = Sort::new(vec![
        SortField::new("mbody", direction)
            .with_json_path(JsonPathExpr::parse("$.v").unwrap())
            .with_multi(selector),
    ]);
    request.top_k = TopK::new(50).unwrap();
    request.projection = Projection::Fields(Vec::new());
    request
}

fn policy_with(memory: u64) -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 4)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, memory)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 40)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 40)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn run_batch(
    snapshot: &Arc<ReaderSnapshot>,
    queries: Vec<QueryRequest>,
    memory: u64,
    cancel: &dyn Cancellation,
) -> quervant_core::contract::batch::BatchQueryResponse {
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(queries, None, BatchBudget::new(4)),
        &policy_with(memory),
        &CapabilitySet::new(),
        cancel,
    )
    .expect("batch envelope")
}

fn success(response: &quervant_core::contract::batch::BatchQueryResponse, slot: usize) -> bool {
    matches!(response.slot(slot), Some(PerQueryOutcome::Success(_)))
}

fn failure_kind(
    response: &quervant_core::contract::batch::BatchQueryResponse,
    slot: usize,
) -> Option<QueryError> {
    match response.slot(slot) {
        Some(PerQueryOutcome::Failure(error)) => Some(error.clone()),
        _ => None,
    }
}

fn keys(response: &quervant_core::contract::batch::BatchQueryResponse, slot: usize) -> Vec<String> {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect(),
        other => panic!("slot {slot} is not a success: {other:?}"),
    }
}

fn total_hits(response: &quervant_core::contract::batch::BatchQueryResponse, slot: usize) -> u64 {
    match response.slot(slot) {
        Some(PerQueryOutcome::Success(response)) => response.total_hits,
        other => panic!("slot {slot} is not a success: {other:?}"),
    }
}

fn min_memory(snapshot: &Arc<ReaderSnapshot>, query: Query, selector: MultiValueSelector) -> u64 {
    let cancel = CancellationFlag::new();
    let mut low = 1u64;
    let mut high = 1u64 << 40;
    while low < high {
        let mid = low + (high - low) / 2;
        let request = json_sort_request(query.clone(), selector, SortDirection::Asc, 1);
        if success(&run_batch(snapshot, vec![request], mid, &cancel), 0) {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

struct ImmediateCancel;

impl Cancellation for ImmediateCancel {
    fn is_cancelled(&self) -> bool {
        true
    }
}

/// D01/D09 — exact admission succeeds; one-under and a much smaller budget are
/// rejected with the typed `BatchMemoryBytes` failure before success is
/// reported. No RSS/absolute-heap assertion is made.
#[test]
fn d01_d09_exact_admission_and_small_budget_rejection() {
    let index = committed(vec![occurrence_doc("huge", 4096)]);
    let snapshot = index.snapshot();
    let exact = min_memory(&snapshot, Query::MatchAll, MultiValueSelector::Min);
    assert!(exact > 1, "the exact logical threshold must be measurable");

    let cancel = CancellationFlag::new();
    let query = || {
        json_sort_request(
            Query::MatchAll,
            MultiValueSelector::Min,
            SortDirection::Asc,
            1,
        )
    };

    let response = run_batch(&snapshot, vec![query()], exact, &cancel);
    assert!(success(&response, 0), "exact logical limit must succeed");

    let response = run_batch(&snapshot, vec![query()], exact - 1, &cancel);
    assert_eq!(
        failure_kind(&response, 0),
        Some(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }),
        "one-under must be a typed batch-memory failure"
    );

    let response = run_batch(&snapshot, vec![query()], (exact / 4).max(1), &cancel);
    assert_eq!(
        failure_kind(&response, 0),
        Some(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }),
        "a small fixed budget must fail at the first unaffordable admission"
    );
}

/// D02 — the charged threshold grows with the live occurrence demand and is
/// never the old occurrence-independent constant.
#[test]
fn d02_charged_threshold_grows_with_occurrences() {
    let cancel = CancellationFlag::new();
    let mut thresholds = Vec::new();
    for count in [1usize, 128, 4096] {
        let index = committed(vec![occurrence_doc("huge", count)]);
        let snapshot = index.snapshot();
        let threshold = min_memory(&snapshot, Query::MatchAll, MultiValueSelector::Min);
        assert!(threshold > 0);
        thresholds.push((count, threshold));
        // A successful run at the threshold returns the hand-authored minimum.
        let request = json_sort_request(
            Query::MatchAll,
            MultiValueSelector::Min,
            SortDirection::Asc,
            1,
        );
        let response = run_batch(&snapshot, vec![request], threshold, &cancel);
        assert!(success(&response, 0));
        assert_eq!(keys(&response, 0), vec!["huge".to_owned()]);
        assert_eq!(total_hits(&response, 0), 1);
    }
    assert!(
        thresholds[0].1 < thresholds[1].1 && thresholds[1].1 < thresholds[2].1,
        "charged JSON sort threshold must grow with occurrences: {thresholds:?}"
    );
}

/// D03 — mixed scalar types, null and missing keep the canonical comparator,
/// and both Min and Max select the hand-authored winner.
#[test]
fn d03_mixed_scalar_min_max_order() {
    let mut docs = Vec::new();
    let mut push = |key: &str, value: JsonValue| {
        let mut document = doc(key);
        set(
            &mut document,
            "body",
            FieldValue::Json(JsonValue::Object(vec![("v".to_owned(), value)])),
        );
        docs.push(document);
    };
    push("bool_f", JsonValue::Bool(false));
    push("bool_t", JsonValue::Bool(true));
    push("i64", JsonValue::Number(JsonNumber::I64(-1)));
    push("u64", JsonValue::Number(JsonNumber::U64(5)));
    push("f64", JsonValue::Number(JsonNumber::F64(1.5)));
    push("str_a", JsonValue::String("a".to_owned()));
    push("str_b", JsonValue::String("b".to_owned()));
    push("null_v", JsonValue::Null);
    docs.push(doc("absent_v"));

    let index = committed(docs);
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    let memory = 1u64 << 40;

    let asc = v_sort_request(Query::MatchAll, MultiValueSelector::Min, SortDirection::Asc);
    let response = run_batch(&snapshot, vec![asc], memory, &cancel);
    assert!(success(&response, 0));
    assert_eq!(
        keys(&response, 0),
        vec![
            "bool_f", "bool_t", "i64", "u64", "f64", "str_a", "str_b", "null_v", "absent_v"
        ],
        "ascending canonical order: bool < i64 < u64 < f64 < keyword, then null, then missing"
    );

    let desc = v_sort_request(
        Query::MatchAll,
        MultiValueSelector::Min,
        SortDirection::Desc,
    );
    let response = run_batch(&snapshot, vec![desc], memory, &cancel);
    assert_eq!(
        keys(&response, 0),
        vec![
            "str_b", "str_a", "f64", "u64", "i64", "bool_t", "bool_f", "null_v", "absent_v"
        ],
        "descending reverses scalar order but keeps null/missing placement"
    );
}

/// D03/D08 — multivalue Min and Max select the hand-authored scalar.
#[test]
fn d08_multivalue_min_max_and_shape_handling() {
    let mut multi = doc("multi");
    set_multi(
        &mut multi,
        "mbody",
        vec![
            FieldValue::Json(JsonValue::Object(vec![(
                "v".to_owned(),
                JsonValue::Number(JsonNumber::I64(5)),
            )])),
            FieldValue::Json(JsonValue::Object(vec![(
                "v".to_owned(),
                JsonValue::String("a".to_owned()),
            )])),
        ],
    );
    let mut null_only = doc("null_v");
    set(
        &mut null_only,
        "body",
        FieldValue::Json(JsonValue::Object(vec![("v".to_owned(), JsonValue::Null)])),
    );
    let mut empty = doc("empty");
    set(
        &mut empty,
        "body",
        FieldValue::Json(JsonValue::Object(vec![(
            "v".to_owned(),
            JsonValue::Array(Vec::new()),
        )])),
    );
    let mut nonmatch = doc("nonmatch");
    set(
        &mut nonmatch,
        "body",
        FieldValue::Json(JsonValue::Object(vec![(
            "w".to_owned(),
            JsonValue::Number(JsonNumber::I64(1)),
        )])),
    );
    let mut single = doc("single");
    set(
        &mut single,
        "body",
        FieldValue::Json(JsonValue::Object(vec![(
            "v".to_owned(),
            JsonValue::Number(JsonNumber::I64(7)),
        )])),
    );

    let index = committed(vec![multi, null_only, empty, nonmatch, single]);
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    let memory = 1u64 << 40;

    let min = mbody_sort_request(Query::MatchAll, MultiValueSelector::Min, SortDirection::Asc);
    let response = run_batch(&snapshot, vec![min], memory, &cancel);
    assert!(success(&response, 0));

    let max = mbody_sort_request(Query::MatchAll, MultiValueSelector::Max, SortDirection::Asc);
    let response_max = run_batch(&snapshot, vec![max], memory, &cancel);
    assert!(success(&response_max, 0));

    let min_sort = v_sort_request(Query::MatchAll, MultiValueSelector::Min, SortDirection::Asc);
    let response_v = run_batch(&snapshot, vec![min_sort], memory, &cancel);
    assert!(success(&response_v, 0));
    assert_eq!(
        keys(&response_v, 0),
        vec!["single", "null_v", "empty", "multi", "nonmatch"],
        "scalar value first, then explicit null, then missing (empty/non-matching paths tie by key)"
    );
}

/// D04 — typed standalone, unified batch and pinned unified batch agree on keys,
/// totals and cursor presence for the same JSON sort.
#[test]
fn d04_typed_unified_and_pinned_parity() {
    let index = committed(vec![
        occurrence_doc("a", 1),
        occurrence_doc("b", 3),
        occurrence_doc("c", 2),
    ]);
    let snapshot = index.snapshot();

    let mut typed_request = request(Query::MatchAll);
    typed_request.sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.events[*].v").unwrap())
            .with_multi(MultiValueSelector::Min),
    ]);
    typed_request.top_k = TopK::new(2).unwrap();
    let typed = typed_search(&snapshot, &typed_request);
    let typed_keys: Vec<String> = typed
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    assert_eq!(typed_keys, vec!["a".to_owned(), "b".to_owned()]);
    assert_eq!(typed.total_hits, 3);
    assert!(typed.next_cursor.is_some());

    let cancel = CancellationFlag::new();
    let batch_request = json_sort_request(
        Query::MatchAll,
        MultiValueSelector::Min,
        SortDirection::Asc,
        2,
    );
    let unified = run_batch(&snapshot, vec![batch_request.clone()], 1 << 40, &cancel);
    assert!(success(&unified, 0));
    assert_eq!(keys(&unified, 0), typed_keys);
    assert_eq!(total_hits(&unified, 0), typed.total_hits);
    let unified_cursor = match unified.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.next_cursor.is_some(),
        _ => unreachable!(),
    };
    assert!(
        !unified_cursor,
        "the naked batch entry does not emit a PIT-bound cursor"
    );

    let pit = index.pin().expect("pin snapshot");
    let pinned = execute_batch_pinned(
        &pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(
            vec![batch_request],
            Some(pit.id().clone()),
            BatchBudget::new(4),
        ),
        &policy_with(1 << 40),
        &CapabilitySet::new(),
        &cancel,
        Timestamp::from_micros(1_000_000),
        Timestamp::from_micros(2_000_000),
    )
    .expect("pinned batch");
    assert!(success(&pinned, 0));
    assert_eq!(keys(&pinned, 0), typed_keys);
    assert_eq!(total_hits(&pinned, 0), typed.total_hits);
    let pinned_cursor = match pinned.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.next_cursor.is_some(),
        _ => unreachable!(),
    };
    assert_eq!(pinned_cursor, typed.next_cursor.is_some());
}

/// D05/D10 — an unaffordable middle slot fails typed, the following sibling
/// succeeds with a fresh budget, and repeated runs do not accumulate meter
/// state.
#[test]
fn d05_d10_sibling_isolation_and_repeat_cleanup() {
    let mut small = doc("small");
    set(&mut small, "title", FieldValue::Text("small".to_owned()));
    set(&mut small, "body", body_with(1));
    let mut huge = doc("huge");
    set(&mut huge, "title", FieldValue::Text("huge".to_owned()));
    set(
        &mut huge,
        "body",
        FieldValue::Json(JsonValue::Object(vec![(
            "events".to_owned(),
            JsonValue::Array(
                (0..4096)
                    .map(|index| {
                        JsonValue::Object(vec![(
                            "v".to_owned(),
                            JsonValue::Number(JsonNumber::I64(index as i64)),
                        )])
                    })
                    .collect(),
            ),
        )])),
    );
    let index = committed(vec![small, huge]);
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();

    let small_query = || {
        json_sort_request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("small".into()),
            },
            MultiValueSelector::Min,
            SortDirection::Asc,
            1,
        )
    };
    let huge_query = || {
        json_sort_request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("huge".into()),
            },
            MultiValueSelector::Min,
            SortDirection::Asc,
            1,
        )
    };

    // Threshold for the small slot alone.
    let threshold = min_memory(
        &snapshot,
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("small".into()),
        },
        MultiValueSelector::Min,
    );
    assert!(threshold < (1 << 30));

    // Retained successful responses stay charged, so leave room for the first
    // slot's retained bytes while staying far below the huge slot's demand.
    let cumulative = threshold.saturating_mul(2);
    assert!(cumulative < (1 << 30));
    let response = run_batch(
        &snapshot,
        vec![small_query(), huge_query(), small_query()],
        cumulative,
        &cancel,
    );
    assert!(success(&response, 0), "first slot must succeed");
    assert_eq!(
        failure_kind(&response, 1),
        Some(QueryError::BudgetExceeded {
            kind: BudgetKind::BatchMemoryBytes
        }),
        "middle slot must fail typed"
    );
    assert!(
        success(&response, 2),
        "third slot must succeed with a fresh budget"
    );
    assert_eq!(keys(&response, 0), keys(&response, 2));

    // Repeated invocations at the exact threshold must not accumulate state.
    for _ in 0..100 {
        let response = run_batch(&snapshot, vec![small_query()], threshold, &cancel);
        assert!(success(&response, 0));
    }
    // Interleave cancellation and one-under failures, then succeed again.
    for _ in 0..10 {
        let cancelled = run_batch(&snapshot, vec![small_query()], threshold, &ImmediateCancel);
        assert!(matches!(
            failure_kind(&cancelled, 0),
            Some(QueryError::Cancelled { .. })
        ));
        let rejected = run_batch(&snapshot, vec![small_query()], threshold - 1, &cancel);
        assert_eq!(
            failure_kind(&rejected, 0),
            Some(QueryError::BudgetExceeded {
                kind: BudgetKind::BatchMemoryBytes
            })
        );
    }
    let response = run_batch(&snapshot, vec![small_query()], threshold, &cancel);
    assert!(success(&response, 0));
}

/// D06 — cancellation is typed and leaves no partial success.
#[test]
fn d06_cancellation_is_typed() {
    let index = committed(vec![occurrence_doc("huge", 128)]);
    let snapshot = index.snapshot();
    let request = json_sort_request(
        Query::MatchAll,
        MultiValueSelector::Min,
        SortDirection::Asc,
        1,
    );
    let response = run_batch(&snapshot, vec![request], 1 << 40, &ImmediateCancel);
    assert!(matches!(
        failure_kind(&response, 0),
        Some(QueryError::Cancelled { .. })
    ));
}

/// D07 — the frozen historical JSON v1 fixture still opens, its digest is
/// unchanged, and a corrupted byte is rejected.
#[test]
fn d07_historical_fixture_digest_and_corruption() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/segment/json_paths_golden.seg"
    );
    let bytes = std::fs::read(path).expect("read frozen fixture");
    let digest = Sha256::digest(&bytes);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write;
        write!(&mut hex, "{byte:02x}").expect("format digest byte");
    }
    assert_eq!(
        hex, "0528a62cdb02fcd08754d5776f23bd16de787f788597ade93d5dfbc65c30a02f",
        "frozen JSON v1 golden must not be regenerated"
    );
    let limits = quervant_core::segment::SegmentLimits::default();
    assert!(quervant_core::segment::SegmentReader::open(bytes.clone(), limits).is_ok());
    let mut corrupt = bytes;
    let middle = corrupt.len() / 2;
    corrupt[middle] ^= 0xFF;
    assert!(
        quervant_core::segment::SegmentReader::open(corrupt, limits).is_err(),
        "corrupted fixture bytes must fail typed at open"
    );
}
