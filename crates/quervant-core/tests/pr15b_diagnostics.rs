//! PR 15B — deterministic scaling fixture, independent oracle and diagnostic
//! acceptance tests (B-T01–B-T16).
//!
//! The expected values are derived from `i` and `i % 8` over the frozen PR15A
//! row truth table. The production index/search path is only the system under
//! test; no expected result is read back from a production evaluator.

#[path = "../benches/unified_diag_common/mod.rs"]
mod unified_diag_common;

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, NeverCancel};
use quervant_core::contract::batch::{PerQueryOutcome, QueryRequest};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, Timestamp};
use quervant_core::index::Index;
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch_pinned,
};
use quervant_core::storage::{Directory, MemoryDirectory};
use sha2::{Digest, Sha256};
use unified_diag_common as common;

const N: usize = 10_000;

fn corpus() -> common::Corpus {
    common::build_corpus(N, 4)
}

// ---------------------------------------------------------------------------
// B-T01 — frozen canonical provenance
// ---------------------------------------------------------------------------

#[test]
fn b_t01_canonical_fixture_digest_and_rows() {
    common::assert_canonical_fixture_digest();
    assert_eq!(common::BASE_ROWS.len(), 8);
    assert_eq!(common::BASE_ROWS[0].title, "alpha beta");
    assert_eq!(common::BASE_ROWS[0].host, "h1");
    assert_eq!(common::BASE_ROWS[1].severity, Some(2));
    assert_eq!(common::BASE_ROWS[3].severity, None);
    assert_eq!(common::BASE_ROWS[3].tags, None);
    assert_eq!(common::BASE_ROWS[2].tags, Some(&[][..]));
    assert_eq!(common::BASE_ROWS[7].host, "h2");

    let mut flipped = common::CANONICAL_JSON.as_bytes().to_vec();
    flipped[0] ^= 0x01;
    let flipped = common::hex(&Sha256::digest(&flipped));
    assert_ne!(
        flipped,
        common::PR15A_V1_SHA256,
        "a changed canonical byte must change the digest"
    );
}

// ---------------------------------------------------------------------------
// B-T02 — deterministic generator digests
// ---------------------------------------------------------------------------

#[test]
fn b_t02_generator_digests_are_deterministic_and_sensitive() {
    for n in [2_000usize, N, 100_000] {
        let first = common::rows_sha256(n);
        let second = common::rows_sha256(n);
        assert_eq!(first, second, "row digest must be deterministic");
        assert_eq!(
            common::corpus_sha256(n, 4),
            common::corpus_sha256(n, 4),
            "corpus digest must be deterministic"
        );
    }
    assert_ne!(
        common::rows_sha256(2_000),
        common::rows_sha256(2_008),
        "a different N must change the row digest"
    );
    assert_ne!(
        common::corpus_sha256(2_000, 4),
        common::corpus_sha256(2_000, 1),
        "a different S must change the corpus digest"
    );
}

// ---------------------------------------------------------------------------
// B-T03 — exact physical topology
// ---------------------------------------------------------------------------

#[test]
fn b_t03_exact_snapshot_shape_and_invalid_inputs() {
    assert!(common::validate_shape(0, 4).is_err());
    assert!(common::validate_shape(1, 1).is_err());
    assert!(common::validate_shape(2_001, 4).is_err());
    assert!(common::validate_shape(2_000, 0).is_err());
    assert!(common::validate_shape(2_000, 2_001).is_err());

    for s in [1usize, 4, 16] {
        let corpus = common::build_corpus(2_000, s);
        assert_eq!(corpus.snapshot.segment_count(), s);
        assert_eq!(corpus.snapshot.document_count(), 2_000);
        common::assert_corpus_shape(&corpus);
    }
}

// ---------------------------------------------------------------------------
// B-T04 — selectivity lanes and wrong-oracle rejection
// ---------------------------------------------------------------------------

#[test]
fn b_t04_selectivity_lanes_match_formula_and_wrong_set_is_rejected() {
    let corpus = corpus();
    common::assert_corpus_shape(&corpus);
    common::assert_absent(&corpus);
    common::assert_rare(&corpus);
    common::assert_medium(&corpus);
    common::assert_common_mixed(&corpus);

    assert_eq!(common::expected_medium(N).len(), N * 3 / 8);
    assert_eq!(common::expected_common_mixed(N).len(), N / 4);
    assert_eq!(common::expected_rare(N), vec![common::record_key(0)]);

    let response = corpus.run(&common::request_medium());
    let mut wrong = common::expected_medium(N);
    wrong.pop();
    assert!(
        common::check_ranked_prefix(
            &common::unified_keys(&response),
            response.total_hits,
            &wrong,
            100,
        )
        .is_err(),
        "the qualification gate must reject an incomplete expected set"
    );
}

// ---------------------------------------------------------------------------
// B-T05 — CIDR/time/JSON typed composition
// ---------------------------------------------------------------------------

#[test]
fn b_t05_cidr_time_and_json_match_row_truth_table() {
    let corpus = corpus();
    common::assert_cidr_time(&corpus);
    common::assert_json_severity(&corpus);

    let cidr = corpus.run(&common::request_cidr_time(N));
    assert_eq!(cidr.total_hits, common::expected_cidr_time(N).len() as u64);
    let json = corpus.run(&common::request_json_severity());
    assert_eq!(
        json.total_hits,
        common::expected_json_severity(N).len() as u64
    );
}

// ---------------------------------------------------------------------------
// B-T06 — sort and top-K prefix invariance
// ---------------------------------------------------------------------------

#[test]
fn b_t06_sort_prefix_invariance_and_host_ties() {
    let corpus = corpus();
    for k in [10usize, 100, 1_000] {
        common::assert_sort_n(&corpus, k);
        let response = corpus.run(&common::request_sort_n(k));
        let keys = common::unified_keys(&response);
        for pair in keys.windows(2) {
            let left: usize = pair[0][1..].parse().expect("key index");
            let right: usize = pair[1][1..].parse().expect("key index");
            assert!(left < right, "n ascending order must be strict");
        }
    }
    common::assert_sort_host(&corpus, 100);

    let response = corpus.run(&common::request_sort_n(10));
    let mut shuffled = common::expected_sorted_prefix(N, 10);
    shuffled.swap(0, 1);
    assert!(
        common::check_exact(&common::unified_keys(&response), &shuffled).is_err(),
        "a shuffled top-K expectation must fail the oracle"
    );
}

// ---------------------------------------------------------------------------
// B-T07 — projection states and unstored rejection
// ---------------------------------------------------------------------------

#[test]
fn b_t07_projection_states_and_unstored_error() {
    let corpus = corpus();
    common::assert_projection(&corpus);

    let schema = Schema::new(
        vec![FieldDefinition::new(
            "raw",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )],
        None,
    )
    .expect("indexed-not-stored schema");
    let registry = AnalyzerRegistry::builtin();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
        .expect("create unstored index");
    {
        let mut document = Document::new(DocumentKey::new("u0").expect("key"));
        document
            .insert(
                "raw",
                FieldValues::Single(FieldValue::Keyword("value".into())),
            )
            .expect("insert raw");
        let mut writer = index.writer().expect("writer");
        writer.insert(document).expect("insert");
        writer.commit().expect("commit");
    }
    let reopened =
        Index::open_existing(directory, schema.clone(), registry.clone()).expect("reopen");
    let snapshot = reopened.snapshot();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).expect("k"));
    request.projection = Projection::Fields(vec!["raw".into()]);
    let result = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel);
    match result {
        Err(SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::UnstoredProjection { field },
        ))) => assert_eq!(field, "raw"),
        other => panic!("unexpected unstored projection result: {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// B-T08 — grouping and zero-match grouped query
// ---------------------------------------------------------------------------

#[test]
fn b_t08_group_metrics_and_zero_match_groups() {
    let corpus = corpus();
    common::assert_aggregation(&corpus);

    let pit = corpus.index.pin().expect("pit");
    let mut request = common::query_request_aggregate_host();
    request.query = common::query_absent();
    let batch = common::pinned_batch(&pit, vec![request]);
    let response = corpus.run_batch(&pit, &batch);
    let slot = common::success(&response, 0);
    assert_eq!(slot.total_hits, 0);
    assert!(
        slot.aggregation
            .as_ref()
            .expect("aggregation")
            .groups
            .is_empty(),
        "zero-match grouped query must return no groups"
    );
}

// ---------------------------------------------------------------------------
// B-T09 — ordered serial batch and isolated invalid middle slot
// ---------------------------------------------------------------------------

#[test]
fn b_t09_serial_batch_matches_standalone_and_isolates_failure() {
    let corpus = corpus();
    common::assert_batch(&corpus);

    let pit = corpus.index.pin().expect("pit");
    let mut batch = common::batch_u10(&pit, N);
    batch.queries[1] = QueryRequest::new(Query::Term {
        field: "missing_field".into(),
        value: FieldValue::I64(1),
    });
    let response = corpus.run_batch(&pit, &batch);
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

// ---------------------------------------------------------------------------
// B-T10 — pinned pagination, wrong PIT and expired deadline
// ---------------------------------------------------------------------------

#[test]
fn b_t10_pinned_pages_and_wrong_pit_or_deadline() {
    let corpus = corpus();
    common::assert_pinned_pages(&corpus, 100);

    let pit = corpus.index.pin().expect("pit");
    let page = common::pinned_batch(
        &pit,
        vec![common::to_query_request(&common::request_sort_n(100))],
    );
    let first = corpus.run_batch(&pit, &page);
    let cursor = common::success(&first, 0)
        .next_cursor
        .clone()
        .expect("page 2 cursor");

    let reopened = Index::open_existing(
        Arc::clone(&corpus.directory),
        corpus.schema.clone(),
        corpus.registry.clone(),
    )
    .expect("second index handle");
    let other_pit = reopened.pin().expect("other pit");
    let mut slot = common::to_query_request(&common::request_sort_n(100));
    slot.cursor = Some(cursor.clone());
    let wrong_pit_batch = common::pinned_batch(&other_pit, vec![slot]);
    let result = execute_batch_pinned(
        &other_pit,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
        &wrong_pit_batch,
        &common::batch_policy(),
        &CapabilitySet::new(),
        &NeverCancel,
        Timestamp::from_micros(common::NOW_MICROS),
        Timestamp::from_micros(common::DEADLINE_MICROS),
    );
    match result {
        Ok(response) => match response.slot(0) {
            Some(PerQueryOutcome::Failure(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch,
            ))) => {}
            other => panic!("a cursor from another PIT must be rejected: {other:?}"),
        },
        Err(error) => panic!("a cursor from another PIT must be rejected: {error:?}"),
    }

    let expired = execute_batch_pinned(
        &pit,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
        &page,
        &common::batch_policy(),
        &CapabilitySet::new(),
        &NeverCancel,
        Timestamp::from_micros(common::DEADLINE_MICROS),
        Timestamp::from_micros(common::DEADLINE_MICROS),
    );
    assert!(
        matches!(
            expired,
            Err(SearchError::Query(QueryError::InvalidBatch(
                InvalidBatchReason::InvalidCursorDeadline
            )))
        ),
        "an expired cursor deadline must be rejected: {expired:?}"
    );
}

// ---------------------------------------------------------------------------
// B-T11 — separate geo provenance
// ---------------------------------------------------------------------------

#[test]
fn b_t11_geo_oracle_and_empty_outside_bbox() {
    let geo = common::build_geo_corpus();
    common::assert_geo(&geo);
    assert_eq!(common::expected_geo(), vec!["g0", "g1", "g2", "g3"]);
}

// ---------------------------------------------------------------------------
// B-T12 — compile-time test-only diagnostics
// ---------------------------------------------------------------------------

#[test]
fn b_t12_diagnostics_are_test_only() {
    const SOURCE: &str = include_str!("../src/search/diagnostics.rs");
    assert!(
        !SOURCE.contains("pub struct WorkCounters"),
        "work counters must not be a public production symbol"
    );

    const SEARCH_MOD: &str = include_str!("../src/search/mod.rs");
    assert!(
        SEARCH_MOD.contains("#[cfg(test)]\nmod diagnostics;"),
        "the diagnostics module must be cfg(test)-gated at its declaration"
    );
}

// ---------------------------------------------------------------------------
// B-T13 — external validator self-test
// ---------------------------------------------------------------------------

#[test]
fn b_t13_validator_self_test() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates")
        .parent()
        .expect("workspace root");
    let script = root.join("benchmarks/scripts/validate-pr15b.py");
    let output = std::process::Command::new("python3")
        .arg(&script)
        .arg("self-test")
        .current_dir(root)
        .output()
        .expect("run validate-pr15b.py self-test");
    assert!(
        output.status.success(),
        "validator self-test failed (stdout={}, stderr={})",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

// ---------------------------------------------------------------------------
// B-T14 — profiling CLI contract
// ---------------------------------------------------------------------------

#[test]
fn b_t14_profile_cli_contract() {
    assert_eq!(common::PROFILE_WORKLOADS.len(), 7);
    for name in common::PROFILE_WORKLOADS {
        let workload = common::parse_profile_workload(name).expect("accepted workload");
        assert_eq!(workload.as_str(), name);
    }
    assert!(common::parse_profile_workload("unknown").is_err());
    assert!(common::parse_profile_workload("").is_err());
    for invalid in ["0", "121", "-1", "abc", ""] {
        assert!(
            common::parse_profile_seconds(invalid).is_err(),
            "seconds {invalid:?} must be rejected"
        );
    }
    assert_eq!(common::parse_profile_seconds("1").expect("min"), 1);
    assert_eq!(common::parse_profile_seconds("120").expect("max"), 120);
}

// ---------------------------------------------------------------------------
// B-T15 — historical targets and suites remain registered
// ---------------------------------------------------------------------------

#[test]
fn b_t15_historical_bench_targets_remain_registered() {
    const CARGO: &str = include_str!("../Cargo.toml");
    for name in [
        "bm25",
        "search",
        "postings",
        "phrase",
        "dictionary",
        "merge",
        "typed_analytics",
        "geo",
        "writer_mutation",
        "unified_diagnostics",
    ] {
        assert!(
            CARGO.contains(&format!("name = \"{name}\"")),
            "benchmark target {name} must remain registered"
        );
    }
}

// ---------------------------------------------------------------------------
// B-T16 — oracle gate precedes metadata/timing
// ---------------------------------------------------------------------------

#[test]
fn b_t16_metadata_is_only_emitted_after_oracle_gate() {
    let corpus = common::build_corpus(2_000, 4);
    common::assert_corpus_shape(&corpus);
    let metas = vec![common::corpus_meta(&corpus)];
    let json = common::fixture_metadata_json(&metas);
    assert!(json.contains("\"oracle_gate\": \"PASS\""));
    assert!(json.contains("\"workload_version\": \"pr15b_v1\""));
    assert!(json.contains(common::PR15A_V1_SHA256));
    assert!(json.contains("\"physical_segments\": 4"));
    assert!(json.contains("\"document_count\": 2000"));

    // A deliberately broken expectation must be rejected by the same gate the
    // benchmark uses before any timed region.
    let response = corpus.run(&common::request_medium());
    let mut wrong = common::expected_medium(2_000);
    wrong.retain(|key| key != &common::record_key(3));
    assert!(
        common::check_ranked_prefix(
            &common::unified_keys(&response),
            response.total_hits,
            &wrong,
            100,
        )
        .is_err()
    );
}
