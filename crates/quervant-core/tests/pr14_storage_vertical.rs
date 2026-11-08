//! PR 14 P4 — real RustFS compound vertical (R01–R08, R12, R15).
//!
//! Local `FsDirectory` and real RustFS snapshots are queried through the same
//! PR 14 `UnifiedSearcher`/`execute_batch` entry points and compared with an
//! independent, hand-enumerated fixture oracle. Real-provider tests are
//! `#[ignore]`d and fail closed when the documented environment is missing.

mod pr11_common;
mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
#[cfg(feature = "s3")]
use quervant_core::analysis::Cancellation;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
#[cfg(feature = "s3")]
use quervant_core::contract::batch::BatchQueryResponse;
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest, SearchResponse,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, FieldValues};
#[cfg(feature = "s3")]
use quervant_core::contract::document::{DocumentKey, MutationRequest};
#[cfg(feature = "s3")]
use quervant_core::contract::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
#[cfg(feature = "s3")]
use quervant_core::contract::result::{Cursor, PitId};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
#[cfg(feature = "s3")]
use quervant_core::index::PitHandle;
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
#[cfg(feature = "s3")]
use quervant_core::search::{SearchError, execute_batch_pinned};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
};
use quervant_core::segment::format::{FEATURE_JSON_PATHS, sha256};
use quervant_core::segment::{
    SectionKind, SegmentError, SegmentLimits, SegmentReader, parse_container,
};
use quervant_core::storage::{Directory, FsDirectory};
#[cfg(feature = "s3")]
use std::sync::atomic::{AtomicUsize, Ordering};

/// Frozen historical PR 11 JSON-path segment (see `b18_b19_*`).
const JSON_PATHS_GOLDEN: &[u8] = include_bytes!("fixtures/segment/json_paths_golden.seg");

fn p4_dir(tag: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr14-p4-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

fn json(values: &[(&str, i64)]) -> JsonValue {
    JsonValue::Object(
        values
            .iter()
            .map(|(key, value)| {
                (
                    (*key).to_owned(),
                    JsonValue::Number(JsonNumber::I64(*value)),
                )
            })
            .collect(),
    )
}

/// Deterministic `pr14-p4-v1` fixture. Each tuple is one logical document.
fn fixture() -> Vec<Document> {
    let mut out = Vec::new();
    let rows = [
        (
            "d0",
            "alpha beta",
            "h1",
            10i64,
            0i64,
            0.0f64,
            0.0,
            "192.0.2.1",
        ),
        ("d1", "alpha", "h1", 20, 60_000_000, 0.1, 0.1, "192.0.2.2"),
        ("d2", "beta", "h2", 30, -1, 50.0, 50.0, "2001:db8::1"),
        (
            "d3",
            "alpha beta",
            "h2",
            40,
            120_000_000,
            0.2,
            0.2,
            "192.0.2.1",
        ),
        (
            "d4",
            "gamma",
            "h3",
            50,
            180_000_000,
            60.0,
            60.0,
            "2001:db8::2",
        ),
        ("d5", "alpha", "h1", 60, 240_000_000, 0.3, 0.3, "192.0.2.2"),
    ];
    for (key, title, host, n, ts, lon, lat, ip) in rows {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text(title.into()));
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "ts",
            FieldValue::Timestamp(Timestamp::from_micros(ts)),
        );
        set(
            &mut document,
            "body",
            FieldValue::Json(json(&[("n", n), ("k", n * 2)])),
        );
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap()),
        );
        set(&mut document, "ip", FieldValue::Ip(ip.parse().unwrap()));
        out.push(document);
    }
    // Extra five-state / multivalue cases.
    set_null(&mut out[1], "nullable");
    set_multi(&mut out[5], "tags", vec![FieldValue::Keyword("x".into())]);
    set_multi(
        &mut out[2],
        "mn",
        vec![FieldValue::I64(1), FieldValue::I64(2)],
    );
    out[4].insert("mn", FieldValues::Empty).unwrap();
    out
}

fn build_local(tag: &str) -> (std::path::PathBuf, Index) {
    build_local_docs(tag, &fixture())
}

/// Commit `docs` into exactly two immutable segments and reopen the index.
fn build_local_docs(tag: &str, docs: &[Document]) -> (std::path::PathBuf, Index) {
    let path = p4_dir(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    let split = docs.len() / 2;
    // Two explicit immutable segments.
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().take(split) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in docs.iter().skip(split) {
            writer.insert(document.clone()).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    (path, reopened)
}

/// B02 auxiliary corpus: a mixed lexical/JSON/IP/geo Boolean filter where the
/// only two survivors rank in the opposite order from their document keys.
#[cfg(feature = "s3")]
fn aux_ranking_docs() -> Vec<Document> {
    #[allow(clippy::too_many_arguments)]
    fn row(
        key: &str,
        title: &str,
        host: &str,
        n: i64,
        json_n: i64,
        lon: f64,
        lat: f64,
        ip: &str,
    ) -> Document {
        let mut document = doc(key);
        set(&mut document, "title", FieldValue::Text(title.into()));
        set(&mut document, "host", FieldValue::Keyword(host.into()));
        set(&mut document, "n", FieldValue::I64(n));
        set(
            &mut document,
            "body",
            FieldValue::Json(json(&[("n", json_n)])),
        );
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap()),
        );
        set(&mut document, "ip", FieldValue::Ip(ip.parse().unwrap()));
        document
    }
    vec![
        row("aonce", "alpha", "h1", 1, 1, 0.0, 0.0, "192.0.2.1"),
        row("zfew", "alpha alpha", "h1", 2, 2, 0.5, 0.5, "192.0.2.2"),
        row("skip", "alpha", "h3", 3, 3, 0.0, 0.0, "198.51.100.1"),
        row("nocidr", "alpha", "h1", 4, 4, 0.0, 0.0, "198.51.100.2"),
        row("nogeo", "alpha beta", "h1", 5, 5, 50.0, 50.0, "192.0.2.3"),
        row("nojson", "alpha", "h1", 6, 99, 0.0, 0.0, "192.0.2.4"),
    ]
}

#[cfg(feature = "s3")]
fn aux_ranking_query() -> Query {
    Query::And(vec![
        Query::Or(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("beta".into()),
            },
        ]),
        Query::Not(Box::new(Query::Term {
            field: "host".into(),
            value: FieldValue::Keyword("h3".into()),
        })),
        Query::JsonPathRange {
            field: "body".into(),
            path: JsonPathExpr::parse("$.n").unwrap().to_concrete().unwrap(),
            lower: Bound::Included(FieldValue::I64(1)),
            upper: Bound::Included(FieldValue::I64(4)),
        },
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(-1.0, -1.0, 1.0, 1.0).unwrap(),
        },
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("192.0.2.0".parse().unwrap(), 24).unwrap(),
        },
    ])
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
        Query::And(vec![
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
        ]),
    ])
}

fn aggregation() -> Aggregation {
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![Aggregate::count(), Aggregate::sum("n")],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    }
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(top_k).unwrap(),
        projection: Projection::Source,
        after: None,
    }
}

fn aggregation_request(query: Query, aggregation: Aggregation, top_k: usize) -> QueryRequest {
    let mut request = QueryRequest::new(query);
    request.top_k = TopK::new(top_k).unwrap();
    request.aggregation = Some(aggregation);
    request
}

fn run_aggregation(
    snapshot: &Arc<ReaderSnapshot>,
    query: Query,
    aggregation: Aggregation,
    top_k: usize,
) -> SearchResponse {
    let response = execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(
            vec![aggregation_request(query, aggregation, top_k)],
            None,
            BatchBudget::new(4),
        ),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap();
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response.clone(),
        other => panic!("aggregation slot failed: {other:?}"),
    }
}

fn unified(snapshot: &Arc<ReaderSnapshot>, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .unwrap()
}

#[cfg(feature = "s3")]
fn assert_unified_equal(local: &UnifiedResponse, remote: &UnifiedResponse) {
    assert_eq!(local.total_hits, remote.total_hits);
    assert_eq!(local.hits.len(), remote.hits.len());
    for (left, right) in local.hits.iter().zip(&remote.hits) {
        assert_eq!(left.key, right.key);
        assert_eq!(left.fields, right.fields);
        assert_eq!(left.score, right.score);
    }
    assert_eq!(local.aggregation, remote.aggregation);
}

fn policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 8)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 30)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

#[cfg(feature = "s3")]
fn batch_requests() -> Vec<QueryRequest> {
    let mut aggregated = QueryRequest::new(mixed_query());
    aggregated.top_k = TopK::new(1).unwrap();
    aggregated.aggregation = Some(aggregation());
    let mut invalid = QueryRequest::new(Query::MatchAll);
    invalid.top_k = TopK::new(1).unwrap();
    invalid.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("nope".into())])),
        aggregates: vec![Aggregate::count()],
        exact_distinct: None,
        top_k: None,
        time_bucket: None,
    });
    let mut plain = QueryRequest::new(Query::MatchAll);
    plain.top_k = TopK::new(2).unwrap();
    plain.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    vec![aggregated, invalid, plain]
}

#[cfg(feature = "s3")]
fn run_batch(snapshot: &Arc<ReaderSnapshot>) -> BatchQueryResponse {
    execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(batch_requests(), None, BatchBudget::new(8)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .unwrap()
}

#[cfg(feature = "s3")]
fn assert_batch_equal(local: &BatchQueryResponse, remote: &BatchQueryResponse) {
    assert_eq!(local.len(), remote.len());
    for index in 0..local.len() {
        match (local.slot(index), remote.slot(index)) {
            (Some(PerQueryOutcome::Success(a)), Some(PerQueryOutcome::Success(b))) => {
                assert_eq!(a.total_hits, b.total_hits);
                assert_eq!(a.aggregation, b.aggregation);
                assert_eq!(a.hits.len(), b.hits.len());
                for (hit_a, hit_b) in a.hits.iter().zip(&b.hits) {
                    assert_eq!(hit_a.key, hit_b.key);
                    assert_eq!(hit_a.fields, hit_b.fields);
                    assert_eq!(hit_a.score, hit_b.score);
                }
            }
            (Some(PerQueryOutcome::Failure(a)), Some(PerQueryOutcome::Failure(b))) => {
                assert_eq!(a, b);
            }
            (a, b) => panic!("outcome mismatch at slot {index}: {a:?} vs {b:?}"),
        }
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

// Local-only oracle gate: must pass before any remote comparison.
#[test]
fn r02_local_mixed_oracle_and_aggregation() {
    let (path, index) = build_local("local-oracle");
    let snapshot = index.snapshot();
    let response = run_aggregation(&snapshot, mixed_query(), aggregation(), 10);
    // d0, d1, d3, d5 satisfy alpha + range + JSON + bbox.
    assert_eq!(response.total_hits, 4);
    let mut counts = group_counts(&response);
    counts.sort();
    assert_eq!(
        counts,
        vec![("h1".to_owned(), 3, 90), ("h2".to_owned(), 1, 40)]
    );
    let _ = std::fs::remove_dir_all(path);
}

// R04/R06/R07 local: nested Boolean, ranking, projection and five-state fields.
#[test]
fn r04_r06_r07_local_nested_boolean_and_states() {
    let (path, index) = build_local("local-nested");
    let snapshot = index.snapshot();
    let query = Query::And(vec![
        Query::Or(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            },
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("beta".into()),
            },
        ]),
        Query::Not(Box::new(Query::Term {
            field: "host".into(),
            value: FieldValue::Keyword("h3".into()),
        })),
    ]);
    let mut request = request(query, 10);
    request.projection = Projection::Fields(vec!["n".into(), "nullable".into()]);
    let response = unified(&snapshot, &request);
    assert_eq!(response.total_hits, 5);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert!(keys.contains(&"d1"));
    let d1 = response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "d1")
        .unwrap();
    assert!(d1
        .fields
        .iter()
        .any(|(name, values)| name == "nullable" && matches!(values, FieldValues::ExplicitNull)));
    let _ = std::fs::remove_dir_all(path);
}

// R07 local matrix: missing/null/empty/multivalue and deterministic tie order.
#[test]
fn r07_local_states_and_tie_order() {
    let (path, index) = build_local("local-r07");
    let snapshot = index.snapshot();
    let mut request = request(Query::MatchAll, 10);
    request.projection = Projection::Fields(vec![
        "n".into(),
        "nullable".into(),
        "mn".into(),
        "tags".into(),
    ]);
    request.sort = Sort::new(vec![
        SortField::geo_distance("loc", GeoPoint::new(0.0, 0.0).unwrap(), SortDirection::Asc),
        SortField::new("n", SortDirection::Asc),
    ]);
    let first = unified(&snapshot, &request);
    let second = unified(&snapshot, &request);
    assert_eq!(first.hits, second.hits);
    let find = |key: &str| {
        first
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == key)
            .unwrap()
    };
    assert!(find("d1")
        .fields
        .iter()
        .any(|(name, values)| name == "nullable" && matches!(values, FieldValues::ExplicitNull)));
    assert!(
        find("d4")
            .fields
            .iter()
            .any(|(name, values)| name == "mn" && matches!(values, FieldValues::Empty))
    );
    assert!(
        find("d2")
            .fields
            .iter()
            .any(|(name, values)| name == "mn" && matches!(values, FieldValues::Multi(_)))
    );
    assert!(
        find("d0")
            .fields
            .iter()
            .any(|(name, values)| name == "nullable" && matches!(values, FieldValues::Absent))
    );
    // Geo distance/n tie ordering is deterministic and starts at the origin.
    assert_eq!(first.hits[0].key.as_str(), "d0");
    let _ = std::fs::remove_dir_all(path);
}

// B03 local: JSON-path numeric sort plus an independent five-state projection
// table. `$.k` is `2 * n`, so descending order is the reverse of key order.
#[test]
fn b03_local_json_path_sort_and_projection_table() {
    let (path, index) = build_local("local-b03");
    let snapshot = index.snapshot();
    let mut request = request(Query::MatchAll, 10);
    request.sort = Sort::new(vec![
        SortField::new("body", SortDirection::Desc)
            .with_json_path(JsonPathExpr::parse("$.k").unwrap()),
    ]);
    request.projection = Projection::Fields(vec![
        "n".into(),
        "nullable".into(),
        "mn".into(),
        "tags".into(),
    ]);
    let first = unified(&snapshot, &request);
    let second = unified(&snapshot, &request);
    assert_eq!(first.hits, second.hits);
    let keys: Vec<&str> = first.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, vec!["d5", "d4", "d3", "d2", "d1", "d0"]);
    let state = |key: &str, field: &str| {
        first
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == key)
            .unwrap()
            .fields
            .iter()
            .find(|(name, _)| name == field)
            .map(|(_, values)| values.clone())
    };
    assert!(matches!(
        state("d1", "nullable"),
        Some(FieldValues::ExplicitNull)
    ));
    assert!(matches!(state("d2", "mn"), Some(FieldValues::Multi(_))));
    assert!(matches!(state("d4", "mn"), Some(FieldValues::Empty)));
    assert!(matches!(state("d5", "tags"), Some(FieldValues::Multi(_))));
    assert!(matches!(state("d0", "nullable"), Some(FieldValues::Absent)));
    let _ = std::fs::remove_dir_all(path);
}

/// B18/B19 — genuine historical PR 11 JSON segment golden fixture.
///
/// Provenance: `tests/fixtures/segment/json_paths_golden.seg` was checked in by
/// commit `65f7440` ("PR 11 Phase 0") and is byte-frozen at SHA-256
/// `0528a62c…a02f`. Its container is `TRWSEG01` major 1 / minor 0 carrying the
/// inline `FEATURE_JSON_PATHS` v1 section; this format has no separate JSON-path
/// sidecar. The current decoder must read the artifact unchanged and produce the
/// test-owned predicate/projection table below. A corrupt byte and an
/// unsupported format version must fail closed rather than be reinterpreted.
#[test]
fn b18_b19_historical_json_segment_compatibility() {
    const GOLDEN: &[u8] = JSON_PATHS_GOLDEN;
    let expected_digest: [u8; 32] = [
        0x05, 0x28, 0xa6, 0x2c, 0xdb, 0x02, 0xfc, 0xd0, 0x87, 0x54, 0xd5, 0x77, 0x6f, 0x23, 0xbd,
        0x16, 0xde, 0x78, 0x7f, 0x78, 0x85, 0x97, 0xad, 0xe9, 0x3d, 0x5d, 0xfb, 0xc6, 0x5c, 0x30,
        0xa0, 0x2f,
    ];
    assert_eq!(sha256(GOLDEN), expected_digest);

    let limits = SegmentLimits::default();
    let view = parse_container(GOLDEN, &limits).expect("golden container");
    assert!(view.required_features().contains(&(FEATURE_JSON_PATHS, 1)));
    assert!(view.entry(SectionKind::JsonPaths).is_some());
    let golden_reader = SegmentReader::open(GOLDEN.to_vec(), limits).expect("golden segment");
    assert_eq!(golden_reader.doc_count(), 2);

    // Rebuild the frozen logical corpus with the current writer and prove the
    // committed content-addressed segment is byte-identical to the artifact.
    let mut a = pr11_common::doc("a", 1);
    pr11_common::set_body(
        &mut a,
        pr11_common::obj(&[("v", pr11_common::i64_value(1))]),
    );
    let mut b = pr11_common::doc("b", 1);
    pr11_common::set_body(
        &mut b,
        pr11_common::obj(&[("v", pr11_common::i64_value(2))]),
    );
    let (_directory, index) = pr11_common::committed(vec![a, b]);
    let snapshot = index.snapshot();
    {
        let guard = snapshot.open_segment_reader(0).expect("current segment");
        assert_eq!(guard.reader().bytes(), GOLDEN);
    }
    assert_eq!(
        pr11_common::search(&snapshot, pr11_common::exists("body", "$.v")),
        ["a", "b"]
    );
    assert_eq!(
        pr11_common::search(
            &snapshot,
            pr11_common::equals("body", "$.v", FieldValue::I64(2))
        ),
        ["b"]
    );
    assert!(
        pr11_common::search(
            &snapshot,
            pr11_common::equals("body", "$.v", FieldValue::I64(3))
        )
        .is_empty()
    );
    // Stored projections: doc 0 -> {"v":1}, doc 1 -> {"v":2}.
    {
        let guard = snapshot.open_segment_reader(0).expect("current segment");
        let reader = guard.reader();
        let field_id = reader.schema().field_id("body").expect("body field id");
        for (doc_id, expected) in [(0u64, 1i64), (1, 2)] {
            let record = reader.stored_doc(doc_id).expect("stored doc");
            match record.get(field_id) {
                FieldValues::Single(FieldValue::Json(value)) => assert_eq!(
                    value,
                    pr11_common::obj(&[("v", pr11_common::i64_value(expected))])
                ),
                other => panic!("doc {doc_id}: unexpected stored body {other:?}"),
            }
        }
    }
    // B19: corruption and an unsupported format version are rejected.
    let mut corrupt = GOLDEN.to_vec();
    let midpoint = corrupt.len() / 2;
    corrupt[midpoint] ^= 0x01;
    assert!(SegmentReader::open(corrupt, limits).is_err());
    let mut unsupported = GOLDEN.to_vec();
    unsupported[8] = 2; // major format version 1 -> 2 (little-endian low byte)
    assert!(matches!(
        SegmentReader::open(unsupported, limits),
        Err(SegmentError::UnsupportedFormatVersion { major: 2, minor: 0 })
    ));
}

/// R01 child entrypoint: cold bootstrap from remote only. Invoked by the
/// parent with `QUERVANT_PR14_P4_CHILD=1` and no writer-local state.
#[cfg(feature = "s3")]
#[test]
#[ignore = "internal child entrypoint for the P4 cold-bootstrap harness"]
fn p4_child_bootstrap() {
    if std::env::var("QUERVANT_PR14_P4_CHILD").is_err() {
        return;
    }
    let prefix = std::env::var("QUERVANT_PR14_P4_PREFIX").expect("prefix");
    let workspace = std::env::var("QUERVANT_PR14_P4_WORKSPACE").expect("workspace");
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT").expect("endpoint");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").expect("bucket");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").expect("access");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").expect("secret");
    let handle = std::thread::Builder::new()
        .stack_size(32 * 1024 * 1024)
        .spawn(move || {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap()
                .block_on(async move {
                    let store = Arc::new(
                        quervant_objectstore::S3ObjectStore::new(
                            quervant_objectstore::S3Config::rustfs(
                                endpoint, region, bucket, access, secret,
                            ),
                        )
                        .unwrap(),
                    );
                    let config = quervant_core::remote::RemoteConfig::new(
                        quervant_core::remote::RemoteKeyPrefix::parse(prefix).unwrap(),
                        std::path::PathBuf::from(workspace),
                    );
                    let reader = quervant_core::remote::RemoteIndex::open_existing(
                        store,
                        config,
                        schema(),
                        registry(),
                        IndexLimits::default(),
                    )
                    .await
                    .expect("cold open");
                    assert_eq!(reader.generation(), Some(2));
                    let response = unified(&reader.snapshot(), &request(mixed_query(), 10));
                    assert_eq!(response.total_hits, 4);
                    let aggregated =
                        run_aggregation(&reader.snapshot(), mixed_query(), aggregation(), 10);
                    assert_eq!(aggregated.total_hits, 4);
                    assert_eq!(
                        group_counts(&aggregated),
                        vec![("h1".to_owned(), 3, 90), ("h2".to_owned(), 1, 40),]
                    );
                });
        })
        .unwrap();
    handle.join().expect("child bootstrap panicked");
}

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT required for real P4 acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET required for real P4 acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY required for real P4 acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY required for real P4 acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        for (name, value) in [
            ("endpoint", &endpoint),
            ("bucket", &bucket),
            ("access", &access),
            ("secret", &secret),
        ] {
            assert!(!value.trim().is_empty(), "{name} must not be empty");
        }
        assert!(endpoint.starts_with("http://"));
        (endpoint, bucket, access, secret, region)
    }

    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("pr14-p4-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .unwrap()
                    .block_on(body);
            })
            .unwrap();
        handle.join().expect("real P4 test panicked");
    }

    fn config(tag: &str) -> RemoteConfig {
        RemoteConfig::new(
            RemoteKeyPrefix::parse(format!(
                "pr14-p4/{tag}/{}/{}/{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or(0),
                "case"
            ))
            .unwrap(),
            p4_dir(&format!("remote-{tag}")),
        )
        .with_transfer(RemoteTransferConfig::default())
    }

    async fn remote_index(
        tag: &str,
    ) -> (Arc<S3ObjectStore>, RemoteConfig, RemoteIndex<S3ObjectStore>) {
        let (endpoint, bucket, access, secret, region) = env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret)).unwrap(),
        );
        store.create_bucket_if_absent().await.unwrap();
        let config = config(tag);
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .unwrap();
        (store, config, index)
    }

    async fn publish(index: &RemoteIndex<S3ObjectStore>) {
        publish_split(index, &fixture()).await;
    }

    async fn publish_split(index: &RemoteIndex<S3ObjectStore>, docs: &[Document]) {
        let split = docs.len() / 2;
        {
            let mut writer = index.writer().await.unwrap();
            for document in docs.iter().take(split) {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
        {
            let mut writer = index.writer().await.unwrap();
            for document in docs.iter().skip(split) {
                writer.insert(document.clone()).unwrap();
            }
            writer.commit().await.unwrap();
        }
    }

    /// B02 — mixed lexical/JSON/IP/geo nested Boolean on the real provider, with
    /// a relevance order that is deliberately the reverse of the key order.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn b02_real_mixed_boolean_and_relevance_order() {
        run(async {
            let (store, config, index) = remote_index("b02").await;
            publish_split(&index, &aux_ranking_docs()).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let remote_snapshot = reader.snapshot();
            let (local_path, local_index) = build_local_docs("b02-local", &aux_ranking_docs());
            let local_snapshot = local_index.snapshot();

            let request = request(aux_ranking_query(), 10);
            let local = unified(&local_snapshot, &request);
            let remote = unified(&remote_snapshot, &request);
            assert_unified_equal(&local, &remote);
            assert_eq!(local.total_hits, 2);
            let order: Vec<&str> = local.hits.iter().map(|hit| hit.key.as_str()).collect();
            assert_eq!(order, vec!["zfew", "aonce"]);
            let mut key_order = order.clone();
            key_order.sort();
            assert_eq!(key_order, vec!["aonce", "zfew"]);
            let scores: Vec<f64> = local
                .hits
                .iter()
                .map(|hit| hit.score.expect("lexical relevance score"))
                .collect();
            assert!(
                scores[0] > scores[1],
                "relevance order must be score-driven"
            );
            std::fs::remove_dir_all(local_path).unwrap();
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    /// B18 remote: the same frozen historical JSON segment object is the
    /// authoritative committed object fetched through the real provider, and
    /// its JSON predicates/projections agree with the test-owned table.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn b18_real_historical_json_remote() {
        run(async {
            let (endpoint, bucket, access, secret, region) = env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .unwrap(),
            );
            store.create_bucket_if_absent().await.unwrap();
            let config = config("b18");
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                super::pr11_common::pr11_schema(),
                super::pr11_common::registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let mut a = super::pr11_common::doc("a", 1);
            super::pr11_common::set_body(
                &mut a,
                super::pr11_common::obj(&[("v", super::pr11_common::i64_value(1))]),
            );
            let mut b = super::pr11_common::doc("b", 1);
            super::pr11_common::set_body(
                &mut b,
                super::pr11_common::obj(&[("v", super::pr11_common::i64_value(2))]),
            );
            {
                let mut writer = index.writer().await.unwrap();
                writer.insert(a).unwrap();
                writer.insert(b).unwrap();
                writer.commit().await.unwrap();
            }
            drop(index);
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                super::pr11_common::pr11_schema(),
                super::pr11_common::registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let snapshot = reader.snapshot();
            {
                let guard = snapshot.open_segment_reader(0).expect("remote segment");
                assert_eq!(guard.reader().bytes(), super::JSON_PATHS_GOLDEN);
            }
            assert_eq!(
                super::pr11_common::search(&snapshot, super::pr11_common::exists("body", "$.v")),
                ["a", "b"]
            );
            assert_eq!(
                super::pr11_common::search(
                    &snapshot,
                    super::pr11_common::equals("body", "$.v", FieldValue::I64(2))
                ),
                ["b"]
            );
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r02_r04_r06_real_cold_compound_equivalence() {
        run(async {
            let (store, config, index) = remote_index("r02").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(2));
            let remote_snapshot = reader.snapshot();

            let (local_path, local_index) = build_local("r02-local");
            let local_snapshot = local_index.snapshot();
            let req = request(mixed_query(), 10);
            let local = unified(&local_snapshot, &req);
            let remote = unified(&remote_snapshot, &req);
            assert_unified_equal(&local, &remote);
            assert_eq!(local.total_hits, 4);
            let local_agg = run_aggregation(&local_snapshot, mixed_query(), aggregation(), 10);
            let remote_agg = run_aggregation(&remote_snapshot, mixed_query(), aggregation(), 10);
            assert_eq!(local_agg.total_hits, remote_agg.total_hits);
            assert_eq!(local_agg.aggregation, remote_agg.aggregation);
            assert_eq!(group_counts(&local_agg), group_counts(&remote_agg));

            // B01 independent oracle: an explicit `n`-ascending key table and a
            // five-state projection table, asserted on both providers.
            let mut sorted = request(mixed_query(), 10);
            sorted.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
            sorted.projection = Projection::Fields(vec![
                "n".into(),
                "nullable".into(),
                "tags".into(),
                "mn".into(),
            ]);
            let local_sorted = unified(&local_snapshot, &sorted);
            let remote_sorted = unified(&remote_snapshot, &sorted);
            assert_unified_equal(&local_sorted, &remote_sorted);
            assert_eq!(local_sorted.total_hits, 4);
            let keys: Vec<&str> = local_sorted
                .hits
                .iter()
                .map(|hit| hit.key.as_str())
                .collect();
            assert_eq!(keys, vec!["d0", "d1", "d3", "d5"]);
            let state = |key: &str, field: &str| {
                local_sorted
                    .hits
                    .iter()
                    .find(|hit| hit.key.as_str() == key)
                    .unwrap()
                    .fields
                    .iter()
                    .find(|(name, _)| name == field)
                    .map(|(_, values)| values.clone())
            };
            assert!(matches!(
                state("d1", "nullable"),
                Some(FieldValues::ExplicitNull)
            ));
            assert!(matches!(state("d5", "tags"), Some(FieldValues::Multi(_))));
            assert!(matches!(state("d0", "nullable"), Some(FieldValues::Absent)));
            assert!(matches!(state("d3", "mn"), Some(FieldValues::Absent)));
            std::fs::remove_dir_all(local_path).unwrap();
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r08_r09_r15_real_batch_aggregation_and_cursor() {
        run(async {
            let (store, config, index) = remote_index("r08").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let remote_snapshot = reader.snapshot();
            let (local_path, local_index) = build_local("r08-local");
            let local_snapshot = local_index.snapshot();

            let local = run_batch(&local_snapshot);
            let remote = run_batch(&remote_snapshot);
            assert_batch_equal(&local, &remote);
            assert!(matches!(local.slot(0), Some(PerQueryOutcome::Success(_))));
            assert!(matches!(local.slot(1), Some(PerQueryOutcome::Failure(_))));
            assert!(matches!(local.slot(2), Some(PerQueryOutcome::Success(_))));
            let aggregated = match local.slot(0).unwrap() {
                PerQueryOutcome::Success(response) => response,
                _ => unreachable!(),
            };
            assert!(aggregated.aggregation.is_some());
            assert_eq!(aggregated.total_hits, 4);
            assert!(aggregated.hits.len() <= 1);

            // STOP S2: public cursor + aggregation remains fail-closed remotely.
            let mut cursor = QueryRequest::new(Query::MatchAll);
            cursor.top_k = TopK::new(1).unwrap();
            cursor.aggregation = Some(aggregation());
            cursor.pit = Some(PitId::new("pit").unwrap());
            cursor.cursor = Some(quervant_core::contract::result::Cursor::new(
                PitId::new("pit").unwrap(),
                Sort::default(),
                DocumentKey::new("a").unwrap(),
                Timestamp::from_micros(10),
            ));
            // PR 14A fail-closed negative regression: the naked snapshot entry
            // rejects the whole PIT/cursor-bearing envelope before any slot
            // executes. The positive pinned path is
            // `b06_b07_real_pinned_batch_search_after`.
            let error = execute_batch(
                &remote_snapshot,
                &schema(),
                &registry(),
                SearchLimits::default(),
                &BatchQueryRequest::new(vec![cursor], None, BatchBudget::new(8)),
                &policy(),
                &CapabilitySet::new(),
                &CancellationFlag::new(),
            )
            .expect_err("naked batch must reject PIT/cursor requests fail-closed");
            assert!(matches!(
                error,
                SearchError::Query(QueryError::InvalidBatch(
                    InvalidBatchReason::PinnedContextRequired
                ))
            ));
            std::fs::remove_dir_all(local_path).unwrap();
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    fn success_of(
        response: &BatchQueryResponse,
        slot: usize,
    ) -> &quervant_core::contract::batch::SearchResponse {
        match response.slot(slot) {
            Some(PerQueryOutcome::Success(response)) => response,
            other => panic!("slot {slot} was not successful: {other:?}"),
        }
    }

    fn keys_of(response: &quervant_core::contract::batch::SearchResponse) -> Vec<String> {
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect()
    }

    fn pinned_run(
        pit: &PitHandle,
        queries: Vec<QueryRequest>,
        policy: &BudgetPolicy,
        cancel: &dyn Cancellation,
        now: i64,
        deadline: i64,
    ) -> Result<BatchQueryResponse, SearchError> {
        execute_batch_pinned(
            pit,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &BatchQueryRequest::new(queries, Some(pit.id().clone()), BatchBudget::new(8)),
            policy,
            &CapabilitySet::new(),
            cancel,
            Timestamp::from_micros(now),
            Timestamp::from_micros(deadline),
        )
    }

    /// B06/B07 — real-provider public PIT-bound pagination through the same
    /// live `PitHandle`: exact key sequence, page-size metamorphism, aggregation
    /// parity, sibling isolation and typed stale/expired/wrong-handle negatives.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn b06_b07_real_pinned_batch_search_after() {
        run(async {
            let (store, config, index) = remote_index("b06").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(2));
            let pit = reader.pin().unwrap();
            let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
            let expected: Vec<String> = fixture()
                .iter()
                .map(|document| document.key().as_str().to_owned())
                .collect();
            assert_eq!(
                expected,
                vec!["d0", "d1", "d2", "d3", "d4", "d5"],
                "fixture insertion order must equal n-ascending order"
            );
            let now = 1_000i64;
            let deadline = 10_000i64;

            for page_size in [1usize, 2] {
                let mut first = QueryRequest::new(Query::MatchAll);
                first.sort = sort.clone();
                first.top_k = TopK::new(page_size).unwrap();
                first.projection = Projection::Fields(Vec::new());
                first.aggregation = Some(aggregation());
                let mut invalid = QueryRequest::new(Query::MatchAll);
                invalid.top_k = TopK::new(1).unwrap();
                invalid.aggregation = Some(Aggregation {
                    group_by: Some(GroupBy::new(vec![GroupKey::Field("nope".into())])),
                    aggregates: vec![Aggregate::count()],
                    exact_distinct: None,
                    top_k: None,
                    time_bucket: None,
                });
                let mut sibling = QueryRequest::new(Query::MatchAll);
                sibling.sort = sort.clone();
                sibling.top_k = TopK::new(page_size).unwrap();
                sibling.projection = Projection::Fields(Vec::new());

                let mut cursor0: Option<Cursor> = None;
                let mut cursor2: Option<Cursor> = None;
                let mut order = Vec::new();
                let mut pages = 0usize;
                loop {
                    first.cursor = cursor0.clone();
                    sibling.cursor = cursor2.clone();
                    let response = pinned_run(
                        &pit,
                        vec![first.clone(), invalid.clone(), sibling.clone()],
                        &policy(),
                        &CancellationFlag::new(),
                        now,
                        deadline,
                    )
                    .unwrap();
                    assert_eq!(response.len(), 3);
                    let page = success_of(&response, 0);
                    assert_eq!(page.total_hits, 6);
                    let mut counts = group_counts(page);
                    counts.sort();
                    assert_eq!(
                        counts,
                        vec![
                            ("h1".to_owned(), 3, 90),
                            ("h2".to_owned(), 2, 70),
                            ("h3".to_owned(), 1, 50),
                        ]
                    );
                    assert!(matches!(
                        response.slot(1),
                        Some(PerQueryOutcome::Failure(_))
                    ));
                    let page2 = success_of(&response, 2);
                    assert_eq!(keys_of(page), keys_of(page2));
                    order.extend(keys_of(page));
                    cursor0 = page.next_cursor.clone();
                    cursor2 = page2.next_cursor.clone();
                    assert_eq!(cursor0.is_some(), cursor2.is_some());
                    pages += 1;
                    if cursor0.is_none() {
                        break;
                    }
                    assert!(pages < 100, "continuation did not terminate");
                }
                assert_eq!(order, expected, "page_size={page_size}");
                assert_eq!(pages, expected.len().div_ceil(page_size));
            }

            // B07 negatives. First obtain a real continuation from the live pin.
            let mut probe = QueryRequest::new(Query::MatchAll);
            probe.sort = sort.clone();
            probe.top_k = TopK::new(1).unwrap();
            let issued = pinned_run(
                &pit,
                vec![probe.clone()],
                &policy(),
                &CancellationFlag::new(),
                now,
                deadline,
            )
            .unwrap();
            let cursor = success_of(&issued, 0)
                .next_cursor
                .clone()
                .expect("first page must emit a continuation");

            // Wrong handle: the request's shared PIT names `pit`, the handle is
            // a different live pin.
            let other = reader.pin().unwrap();
            let mismatched = execute_batch_pinned(
                &other,
                &schema(),
                &registry(),
                SearchLimits::default(),
                &BatchQueryRequest::new(
                    vec![{
                        let mut request = probe.clone();
                        request.cursor = Some(cursor.clone());
                        request
                    }],
                    Some(pit.id().clone()),
                    BatchBudget::new(8),
                ),
                &policy(),
                &CapabilitySet::new(),
                &CancellationFlag::new(),
                Timestamp::from_micros(now),
                Timestamp::from_micros(deadline),
            );
            assert!(matches!(
                mismatched,
                Err(SearchError::Query(QueryError::InvalidBatch(
                    InvalidBatchReason::ConflictingPit
                )))
            ));

            // Expired exactly at the issuing deadline: the slot fails typed and
            // emits no cursor. The pinned window itself stays valid.
            let expired = pinned_run(
                &pit,
                vec![{
                    let mut request = probe.clone();
                    request.cursor = Some(cursor.clone());
                    request
                }],
                &policy(),
                &CancellationFlag::new(),
                deadline,
                deadline + 1_000,
            )
            .unwrap();
            assert_eq!(
                expired.slot(0),
                Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
            );

            // Changed query and changed sort against the same cursor both fail
            // typed instead of silently resuming.
            let changed_query = pinned_run(
                &pit,
                vec![{
                    let mut request = QueryRequest::new(Query::Term {
                        field: "title".into(),
                        value: FieldValue::Text("alpha".into()),
                    });
                    request.sort = sort.clone();
                    request.top_k = TopK::new(1).unwrap();
                    request.cursor = Some(cursor.clone());
                    request
                }],
                &policy(),
                &CancellationFlag::new(),
                now,
                deadline,
            )
            .unwrap();
            assert!(matches!(
                changed_query.slot(0),
                Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
                    InvalidQueryReason::CursorSortMismatch
                )))
            ));
            let changed_sort = pinned_run(
                &pit,
                vec![{
                    let mut request = QueryRequest::new(Query::MatchAll);
                    request.sort = Sort::new(vec![SortField::new("host", SortDirection::Desc)]);
                    request.top_k = TopK::new(1).unwrap();
                    request.cursor = Some(cursor.clone());
                    request
                }],
                &policy(),
                &CancellationFlag::new(),
                now,
                deadline,
            )
            .unwrap();
            assert!(matches!(
                changed_sort.slot(0),
                Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
                    InvalidQueryReason::CursorSortMismatch
                )))
            ));
            drop(other);
            drop(pit);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r05_real_mutation_old_and_new_snapshot() {
        run(async {
            let (store, config, index) = remote_index("r05").await;
            publish(&index).await;
            // B08: pin the committed generation before any mutation.
            let old_pit = {
                let writer = index.writer().await.unwrap();
                writer.pin().unwrap()
            };
            let old_order: Vec<String> = unified(old_pit.snapshot(), &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert_eq!(old_order.len(), 6);
            let old = index.writer().await.unwrap().refresh().unwrap();
            let old_total = unified(&old, &request(Query::MatchAll, 10)).total_hits;
            assert_eq!(old_total, 6);
            let new = {
                let mut writer = index.writer().await.unwrap();
                let mut updated = fixture()[0].clone();
                set(&mut updated, "title", FieldValue::Text("delta".into()));
                writer.apply(MutationRequest::upsert(updated)).unwrap();
                writer
                    .apply(MutationRequest::delete(DocumentKey::new("d2").unwrap()))
                    .unwrap();
                writer.commit().await.unwrap();
                writer.refresh().unwrap()
            };
            // Pinned old generation is unchanged by the mutation/commit.
            assert_eq!(unified(&old, &request(Query::MatchAll, 10)).total_hits, 6);
            let retained: Vec<String> = unified(old_pit.snapshot(), &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert_eq!(retained, old_order);
            assert!(retained.contains(&"d2".to_owned()));
            assert_eq!(unified(&new, &request(Query::MatchAll, 10)).total_hits, 5);
            let new_keys: Vec<String> = unified(&new, &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert!(!new_keys.contains(&"d2".to_owned()));

            // Cold remote reopen equals the new local generation.
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let reopened = reader.snapshot();
            assert_eq!(
                unified(&reopened, &request(Query::MatchAll, 10)).total_hits,
                5
            );
            // B09: a newly pinned reader sees the new committed generation,
            // while the retained old pin still sees the pre-mutation state.
            let new_pit = reader.pin().unwrap();
            let new_keys: Vec<String> = unified(new_pit.snapshot(), &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert_eq!(new_keys.len(), 5);
            assert!(!new_keys.contains(&"d2".to_owned()));
            let still_old: Vec<String> = unified(old_pit.snapshot(), &request(Query::MatchAll, 10))
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert_eq!(still_old, old_order);
            drop(new_pit);
            drop(old_pit);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    fn run_batch_with(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        policy: &BudgetPolicy,
    ) -> BatchQueryResponse {
        execute_batch(
            snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &BatchQueryRequest::new(queries, None, BatchBudget::new(8)),
            policy,
            &CapabilitySet::new(),
            &CancellationFlag::new(),
        )
        .unwrap()
    }

    fn min_memory(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        response: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let ok = run_batch_with(snapshot, queries.clone(), &policy_with(mid, response, work))
                .results()
                .iter()
                .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)));
            if ok {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn min_response(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        memory: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let ok = run_batch_with(snapshot, queries.clone(), &policy_with(memory, mid, work))
                .results()
                .iter()
                .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)));
            if ok {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn min_work(
        snapshot: &Arc<ReaderSnapshot>,
        queries: Vec<QueryRequest>,
        memory: u64,
        response: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let ok = run_batch_with(
                snapshot,
                queries.clone(),
                &policy_with(memory, response, mid),
            )
            .results()
            .iter()
            .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)));
            if ok {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn pinned_ok(pit: &PitHandle, queries: Vec<QueryRequest>, policy: &BudgetPolicy) -> bool {
        pinned_run(
            pit,
            queries,
            policy,
            &CancellationFlag::new(),
            1_000,
            10_000,
        )
        .map(|response| {
            response
                .results()
                .iter()
                .all(|outcome| matches!(outcome, PerQueryOutcome::Success(_)))
        })
        .unwrap_or(false)
    }

    fn pinned_min_memory(
        pit: &PitHandle,
        queries: Vec<QueryRequest>,
        response: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            if pinned_ok(pit, queries.clone(), &policy_with(mid, response, work)) {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn pinned_min_response(
        pit: &PitHandle,
        queries: Vec<QueryRequest>,
        memory: u64,
        work: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            if pinned_ok(pit, queries.clone(), &policy_with(memory, mid, work)) {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    fn pinned_min_work(
        pit: &PitHandle,
        queries: Vec<QueryRequest>,
        memory: u64,
        response: u64,
    ) -> u64 {
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            if pinned_ok(pit, queries.clone(), &policy_with(memory, response, mid)) {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
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

    fn policy_with(memory: u64, response: u64, work: u64) -> BudgetPolicy {
        BudgetPolicy::new(
            Budgets::new()
                .with(BudgetKind::QueriesPerBatch, 8)
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

    fn aggregated_queries() -> Vec<QueryRequest> {
        vec![aggregation_request(mixed_query(), aggregation(), 1)]
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r10_r11_real_remote_budget_exact_and_one_over() {
        run(async {
            let (store, config, index) = remote_index("r10").await;
            publish(&index).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let snapshot = reader.snapshot();

            let queries = aggregated_queries();
            let memory_min = min_memory(&snapshot, queries.clone(), 1 << 30, 1 << 30);
            assert!(matches!(
                run_batch_with(
                    &snapshot,
                    queries.clone(),
                    &policy_with(memory_min, 1 << 30, 1 << 30)
                )
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let memory_over = run_batch_with(
                &snapshot,
                queries.clone(),
                &policy_with(memory_min - 1, 1 << 30, 1 << 30),
            );
            assert!(matches!(
                memory_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchMemoryBytes
                    }
                ))
            ));

            let response_min = min_response(&snapshot, queries.clone(), 1 << 30, 1 << 30);
            assert!(matches!(
                run_batch_with(
                    &snapshot,
                    queries.clone(),
                    &policy_with(1 << 30, response_min, 1 << 30)
                )
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let response_over = run_batch_with(
                &snapshot,
                queries.clone(),
                &policy_with(1 << 30, response_min - 1, 1 << 30),
            );
            assert!(matches!(
                response_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchResponseBytes
                    }
                ))
            ));

            // B12/B13: BatchAggregate exact / one-under on the real provider.
            let work_min = min_work(&snapshot, queries.clone(), 1 << 30, 1 << 30);
            assert!(matches!(
                run_batch_with(
                    &snapshot,
                    queries.clone(),
                    &policy_with(1 << 30, 1 << 30, work_min)
                )
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let work_over = run_batch_with(
                &snapshot,
                queries.clone(),
                &policy_with(1 << 30, 1 << 30, work_min - 1),
            );
            assert!(matches!(
                work_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchAggregate
                    }
                ))
            ));

            // Pinned cursor path: a real continuation emitted by the live handle
            // exercises all three cumulative dimensions at exact and one-under.
            let pit = reader.pin().unwrap();
            let sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
            let mut page_one = QueryRequest::new(Query::MatchAll);
            page_one.sort = sort;
            page_one.top_k = TopK::new(1).unwrap();
            page_one.projection = Projection::Fields(Vec::new());
            let issued = pinned_run(
                &pit,
                vec![page_one.clone()],
                &policy(),
                &CancellationFlag::new(),
                1_000,
                10_000,
            )
            .unwrap();
            let cursor = success_of(&issued, 0)
                .next_cursor
                .clone()
                .expect("first page must emit a continuation");
            let mut continuation = page_one.clone();
            continuation.cursor = Some(cursor);

            let cursor_memory =
                pinned_min_memory(&pit, vec![continuation.clone()], 1 << 30, 1 << 30);
            assert!(matches!(
                pinned_run(
                    &pit,
                    vec![continuation.clone()],
                    &policy_with(cursor_memory, 1 << 30, 1 << 30),
                    &CancellationFlag::new(),
                    1_000,
                    10_000,
                )
                .unwrap()
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let cursor_memory_over = pinned_run(
                &pit,
                vec![continuation.clone()],
                &policy_with(cursor_memory - 1, 1 << 30, 1 << 30),
                &CancellationFlag::new(),
                1_000,
                10_000,
            )
            .unwrap();
            assert!(matches!(
                cursor_memory_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchMemoryBytes
                    }
                ))
            ));

            let cursor_response =
                pinned_min_response(&pit, vec![continuation.clone()], 1 << 30, 1 << 30);
            assert!(matches!(
                pinned_run(
                    &pit,
                    vec![continuation.clone()],
                    &policy_with(1 << 30, cursor_response, 1 << 30),
                    &CancellationFlag::new(),
                    1_000,
                    10_000,
                )
                .unwrap()
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let cursor_response_over = pinned_run(
                &pit,
                vec![continuation.clone()],
                &policy_with(1 << 30, cursor_response - 1, 1 << 30),
                &CancellationFlag::new(),
                1_000,
                10_000,
            )
            .unwrap();
            assert!(matches!(
                cursor_response_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchResponseBytes
                    }
                ))
            ));

            let cursor_work = pinned_min_work(&pit, vec![continuation.clone()], 1 << 30, 1 << 30);
            assert!(matches!(
                pinned_run(
                    &pit,
                    vec![continuation.clone()],
                    &policy_with(1 << 30, 1 << 30, cursor_work),
                    &CancellationFlag::new(),
                    1_000,
                    10_000,
                )
                .unwrap()
                .slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            let cursor_work_over = pinned_run(
                &pit,
                vec![continuation],
                &policy_with(1 << 30, 1 << 30, cursor_work - 1),
                &CancellationFlag::new(),
                1_000,
                10_000,
            )
            .unwrap();
            assert!(matches!(
                cursor_work_over.slot(0),
                Some(PerQueryOutcome::Failure(
                    quervant_core::contract::error::QueryError::BudgetExceeded {
                        kind: BudgetKind::BatchAggregate
                    }
                ))
            ));

            // B13 cancellation: a prior slot success is preserved, the aborted
            // slot returns a typed cancellation and emits no cursor.
            let polls = Arc::new(AtomicUsize::new(0));
            let probe = pinned_run(
                &pit,
                vec![page_one.clone()],
                &policy(),
                &CountPolls(Arc::clone(&polls)),
                1_000,
                10_000,
            )
            .unwrap();
            assert!(matches!(probe.slot(0), Some(PerQueryOutcome::Success(_))));
            let total = polls.load(Ordering::SeqCst);
            assert!(total > 0, "a successful slot must poll cancellation");
            let cancel = TripAfter {
                skip: total,
                polls: Arc::new(AtomicUsize::new(0)),
            };
            let cancelled = pinned_run(
                &pit,
                vec![page_one.clone(), page_one.clone(), page_one],
                &policy(),
                &cancel,
                1_000,
                10_000,
            )
            .unwrap();
            assert_eq!(cancelled.len(), 3);
            assert!(matches!(
                cancelled.slot(0),
                Some(PerQueryOutcome::Success(_))
            ));
            assert_eq!(
                cancelled.slot(1),
                Some(&PerQueryOutcome::Failure(QueryError::Cancelled {
                    reason: quervant_core::contract::error::CancelReason::ClientCancellation
                }))
            );
            assert!(matches!(
                cancelled.slot(2),
                Some(PerQueryOutcome::Failure(QueryError::Cancelled { .. }))
            ));
            drop(pit);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r12_empty_cache_no_writer_state() {
        run(async {
            let (store, config, index) = remote_index("r12").await;
            publish(&index).await;
            drop(index);
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            assert!(!config.workspace_root().exists());
            let reader = RemoteIndex::open_existing(
                store,
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader.generation(), Some(2));
            let response = unified(&reader.snapshot(), &request(mixed_query(), 10));
            assert_eq!(response.total_hits, 4);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r01_separate_process_cold_bootstrap() {
        run(async {
            let (endpoint, bucket, access, secret, region) = env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .unwrap(),
            );
            store.create_bucket_if_absent().await.unwrap();
            let prefix = format!(
                "pr14-p4/r01/{}/{}/case",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or(0)
            );
            let config = RemoteConfig::new(
                RemoteKeyPrefix::parse(prefix.clone()).unwrap(),
                p4_dir("r01"),
            )
            .with_transfer(RemoteTransferConfig::default());
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            publish(&index).await;
            // The child receives only remote config + prefix/workspace.
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let workspace = config.workspace_root().to_path_buf();
            let env = env();
            let mut child = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--ignored",
                    "--exact",
                    "p4_child_bootstrap",
                    "--nocapture",
                    "--test-threads=1",
                ])
                .env("QUERVANT_PR14_P4_CHILD", "1")
                .env("QUERVANT_PR14_P4_PREFIX", &prefix)
                .env("QUERVANT_PR14_P4_WORKSPACE", &workspace)
                .env("QUERVANT_RUSTFS_ENDPOINT", &env.0)
                .env("QUERVANT_RUSTFS_REGION", &env.4)
                .env("QUERVANT_RUSTFS_BUCKET", &env.1)
                .env("QUERVANT_RUSTFS_ACCESS_KEY", &env.2)
                .env("QUERVANT_RUSTFS_SECRET_KEY", &env.3)
                .stdout(std::process::Stdio::inherit())
                .stderr(std::process::Stdio::inherit())
                .spawn()
                .expect("spawn child");
            let status = child.wait().expect("child wait");
            assert!(status.success(), "cold child failed: {status}");
            let _ = std::fs::remove_dir_all(config.workspace_root());
            let _ = store;
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r03_wrong_generation_is_not_substituted() {
        run(async {
            // Prefix A: generations 1 and 2.
            let (store_a, config_a, index_a) = remote_index("r03a").await;
            publish(&index_a).await;
            // Prefix B: one generation only, different documents.
            let (store_b, config_b, index_b) = remote_index("r03b").await;
            {
                let mut writer = index_b.writer().await.unwrap();
                let mut document = doc("only");
                set(&mut document, "title", FieldValue::Text("alpha".into()));
                set(&mut document, "host", FieldValue::Keyword("h1".into()));
                set(&mut document, "n", FieldValue::I64(1));
                writer.insert(document).unwrap();
                writer.commit().await.unwrap();
            }
            let reader_a = RemoteIndex::open_existing(
                Arc::clone(&store_a),
                config_a.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let reader_b = RemoteIndex::open_existing(
                Arc::clone(&store_b),
                config_b.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reader_a.generation(), Some(2));
            assert_eq!(reader_b.generation(), Some(1));
            assert_eq!(
                unified(&reader_a.snapshot(), &request(Query::MatchAll, 10)).total_hits,
                6
            );
            assert_eq!(
                unified(&reader_b.snapshot(), &request(Query::MatchAll, 10)).total_hits,
                1
            );
            let _ = std::fs::remove_dir_all(config_a.workspace_root());
            let _ = std::fs::remove_dir_all(config_b.workspace_root());
        });
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn r13_r14_warm_evict_and_pinned_reader() {
        run(async {
            let (store, config, index) = remote_index("r13").await;
            publish(&index).await;
            let _ = &index;
            let first = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let expected = unified(&first.snapshot(), &request(mixed_query(), 10));
            assert_eq!(expected.total_hits, 4);
            let cache_dir = config.workspace_root().join("cache");
            assert!(cache_dir.exists() || config.workspace_root().exists());

            // Warm reopen reuses the same workspace/cache.
            let warm = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(
                unified(&warm.snapshot(), &request(mixed_query(), 10)).hits,
                expected.hits
            );

            // Pinned reader remains consistent across a fresh open, and a
            // cache capacity that cannot hold the pinned segment fails closed
            // instead of evicting the pinned bytes.
            let pin = warm.pin().unwrap();
            let pinned = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(
                unified(&pinned.snapshot(), &request(mixed_query(), 10)).hits,
                expected.hits
            );
            let tiny = config
                .clone()
                .with_cache(quervant_core::storage::CacheConfig::new(6000, 2, 1 << 20));
            let pinned_reload = RemoteIndex::open_existing(
                Arc::clone(&store),
                tiny,
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await;
            assert!(
                pinned_reload.is_err(),
                "pinned cache bytes must not be silently evicted"
            );
            drop(pin);
            drop(first);
            drop(warm);
            drop(pinned);

            // Reload from the authoritative remote objects after releasing pins.
            let reload = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(
                unified(&reload.snapshot(), &request(mixed_query(), 10)).hits,
                expected.hits
            );
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    fn memory_policy(memory: u64) -> BudgetPolicy {
        BudgetPolicy::new(
            Budgets::new()
                .with(BudgetKind::QueriesPerBatch, 8)
                .unwrap()
                .with(BudgetKind::BatchMemoryBytes, memory)
                .unwrap()
                .with(BudgetKind::BatchResponseBytes, 1 << 30)
                .unwrap()
                .with(BudgetKind::BatchAggregate, 1 << 30)
                .unwrap(),
            Budgets::new(),
            Budgets::new(),
            Budgets::new(),
        )
    }

    fn events_body(values: impl IntoIterator<Item = i64>) -> FieldValue {
        let events: Vec<JsonValue> = values
            .into_iter()
            .map(|value| {
                JsonValue::Object(vec![(
                    "v".to_owned(),
                    JsonValue::Number(JsonNumber::I64(value)),
                )])
            })
            .collect();
        FieldValue::Json(JsonValue::Object(vec![(
            "events".to_owned(),
            JsonValue::Array(events),
        )]))
    }

    fn json_memory_docs() -> Vec<Document> {
        let mut docs = Vec::new();
        for (key, title, value) in [("a", "alpha", 5i64), ("b", "alpha", 3), ("c", "beta", 9)] {
            let mut document = doc(key);
            set(&mut document, "title", FieldValue::Text(title.into()));
            set(&mut document, "body", events_body([value]));
            docs.push(document);
        }
        let mut huge = doc("huge");
        set(&mut huge, "title", FieldValue::Text("beta".into()));
        set(&mut huge, "body", events_body(0..4096));
        docs.push(huge);
        docs
    }

    fn json_sort_request(query: Query, top_k: usize) -> QueryRequest {
        let mut request = QueryRequest::new(query);
        request.sort = Sort::new(vec![
            SortField::new("body", SortDirection::Asc)
                .with_json_path(JsonPathExpr::parse("$.events[*].v").unwrap())
                .with_multi(MultiValueSelector::Min),
        ]);
        request.top_k = TopK::new(top_k).unwrap();
        request.projection = Projection::Fields(Vec::new());
        request
    }

    struct ImmediateCancel;

    impl Cancellation for ImmediateCancel {
        fn is_cancelled(&self) -> bool {
            true
        }
    }

    fn min_pinned_memory(pit: &PitHandle, request: impl Fn() -> QueryRequest) -> u64 {
        let cancel = CancellationFlag::new();
        let mut low = 1u64;
        let mut high = 1u64 << 40;
        while low < high {
            let mid = low + (high - low) / 2;
            let response = pinned_run(
                pit,
                vec![request()],
                &memory_policy(mid),
                &cancel,
                1_000_000,
                2_000_000,
            )
            .expect("pinned batch");
            if matches!(response.slot(0), Some(PerQueryOutcome::Success(_))) {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    }

    /// D11 — real provider JSON sort exact/one-under memory admission with a
    /// hand-authored local oracle.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn d11_real_json_sort_memory_exact_and_one_under() {
        run(async {
            let (store, config, index) = remote_index("d11").await;
            let docs = json_memory_docs();
            publish_split(&index, &docs).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let pit = reader.pin().unwrap();
            let request = || json_sort_request(Query::MatchAll, 10);
            let exact = min_pinned_memory(&pit, request);
            assert!(
                exact > 1,
                "exact real-provider threshold must be measurable"
            );

            let cancel = CancellationFlag::new();
            let ok = pinned_run(
                &pit,
                vec![request()],
                &memory_policy(exact),
                &cancel,
                1_000_000,
                2_000_000,
            )
            .expect("exact pinned batch");
            assert_eq!(
                keys_of(success_of(&ok, 0)),
                vec!["huge", "b", "a", "c"],
                "hand-authored ascending Min order"
            );

            let under = pinned_run(
                &pit,
                vec![request()],
                &memory_policy(exact - 1),
                &cancel,
                1_000_000,
                2_000_000,
            )
            .expect("one-under pinned batch");
            assert_eq!(
                under.slot(0),
                Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                    kind: BudgetKind::BatchMemoryBytes
                })),
                "one-under must be a typed batch-memory failure"
            );

            // Independent local oracle for the same committed corpus.
            let (local_path, local_index) = build_local_docs("d11-local", &docs);
            let local_pit = local_index.pin().unwrap();
            let local = pinned_run(
                &local_pit,
                vec![request()],
                &memory_policy(1 << 40),
                &cancel,
                1_000_000,
                2_000_000,
            )
            .expect("local pinned batch");
            assert_eq!(keys_of(success_of(&local, 0)), keys_of(success_of(&ok, 0)));
            assert_eq!(
                success_of(&local, 0).total_hits,
                success_of(&ok, 0).total_hits
            );
            let _ = std::fs::remove_dir_all(local_path);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }

    /// D12 — real provider mixed lexical/JSON sort: typed S/F/S sibling
    /// isolation, cancellation, and old/new PIT visibility.
    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn d12_real_json_sort_mixed_sibling_cancellation_and_pit() {
        run(async {
            let (store, config, index) = remote_index("d12").await;
            let docs = json_memory_docs();
            publish_split(&index, &docs).await;
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let old_pit = reader.pin().unwrap();

            let alpha = || Query::Term {
                field: "title".into(),
                value: FieldValue::Text("alpha".into()),
            };
            let beta = || Query::Term {
                field: "title".into(),
                value: FieldValue::Text("beta".into()),
            };
            let alpha_request = || json_sort_request(alpha(), 10);
            let beta_request = || json_sort_request(beta(), 10);
            let threshold = min_pinned_memory(&old_pit, alpha_request);
            let cumulative = threshold.saturating_mul(2);
            let cancel = CancellationFlag::new();
            let response = pinned_run(
                &old_pit,
                vec![alpha_request(), beta_request(), alpha_request()],
                &memory_policy(cumulative),
                &cancel,
                1_000_000,
                2_000_000,
            )
            .expect("pinned mixed batch");
            assert_eq!(keys_of(success_of(&response, 0)), vec!["b", "a"]);
            assert_eq!(
                response.slot(1),
                Some(&PerQueryOutcome::Failure(QueryError::BudgetExceeded {
                    kind: BudgetKind::BatchMemoryBytes
                })),
                "the high-occurrence middle slot must fail typed"
            );
            assert_eq!(keys_of(success_of(&response, 2)), vec!["b", "a"]);

            let cancelled = pinned_run(
                &old_pit,
                vec![alpha_request()],
                &memory_policy(1 << 40),
                &ImmediateCancel,
                1_000_000,
                2_000_000,
            )
            .expect("cancelled pinned batch");
            assert!(
                matches!(
                    cancelled.slot(0),
                    Some(PerQueryOutcome::Failure(QueryError::Cancelled { .. }))
                ),
                "cancellation must be typed"
            );

            let old_keys = keys_of(success_of(
                &pinned_run(
                    &old_pit,
                    vec![json_sort_request(Query::MatchAll, 10)],
                    &memory_policy(1 << 40),
                    &cancel,
                    1_000_000,
                    2_000_000,
                )
                .expect("old pinned batch"),
                0,
            ));

            // Upsert `a` to a larger JSON value, then pin the new generation.
            let mut updated = doc("a");
            set(&mut updated, "title", FieldValue::Text("alpha".into()));
            set(&mut updated, "body", events_body([100]));
            {
                let mut writer = index.writer().await.unwrap();
                writer.apply(MutationRequest::upsert(updated)).unwrap();
                writer.commit().await.unwrap();
            }
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            let new_pit = reader.pin().unwrap();
            let new_keys = keys_of(success_of(
                &pinned_run(
                    &new_pit,
                    vec![json_sort_request(Query::MatchAll, 10)],
                    &memory_policy(1 << 40),
                    &cancel,
                    1_000_000,
                    2_000_000,
                )
                .expect("new pinned batch"),
                0,
            ));
            assert_eq!(old_keys, vec!["huge", "b", "a", "c"]);
            assert_eq!(new_keys, vec!["huge", "b", "c", "a"]);
            let _ = std::fs::remove_dir_all(config.workspace_root());
        });
    }
}
