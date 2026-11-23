//! PR 15I-D2-A real production-path scoring contract tests (test source only).
//!
//! Every scenario builds a real `FsDirectory` index through the public
//! `Index`/writer/commit/reopen path and queries it through `UnifiedSearcher`.
//! No scorer is mocked and no test-only production hook is used. Scores are
//! compared per logical document key with exact `f64::to_bits()` equality.
//!
//! Mapping to the frozen plan:
//!
//! * SC-01 `sc01_zero_matches_have_no_scores`
//! * SC-02 `sc02_single_hit_explicit_sort_score_bits`
//! * SC-03 `sc03_frequency_and_length_score_bits`
//! * SC-04 `sc04_hundred_and_one_matches_k10_k100`
//! * SC-05 `sc05_reversed_sort_and_tie_break_scores`
//! * SC-06 `sc06_two_segments_reopen_score_parity`
//! * SC-07 `sc07_delete_upsert_pit_immutability`
//! * SC-08 `sc08_cursor_pages_match_full_result_scores`
//! * SC-09 `sc09_ineligible_and_and_single_term_parity`
//! * SC-10 `sc10_typed_only_predicates_have_no_score`
//! * SC-11 `sc11_negative_only_and_mixed_score_presence`
//! * SC-12 `sc12_cancellation_and_invalid_cursor_sort_are_typed`
//! * SC-13 `sc13_candidate_limit_stays_resource_limit`
//! * SC-14 `sc14_repeated_queries_are_bitwise_stable`
//! * SC-15 `sc15_native_fs_process_scope_reopen`
//!
//! SC-16 (`bm25` `tf=0`, `n=0`, `df>n`, non-finite) is covered by the existing
//! private scorer unit tests in `crates/quervant-core/src/search/score.rs`
//! (`bm25_boundaries_and_invalid`); this suite deliberately does not widen the
//! private scorer's visibility.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::error::{InvalidQueryReason, QueryError};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::storage::{Directory, FsDirectory};

/// A unique native temporary directory with RAII cleanup.
struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn new(tag: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "quervant-pr15i-d2a-{}-{tag}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::remove_dir_all(&path);
        Self { path }
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn keyword(name: &str, columnar: bool) -> FieldDefinition {
    FieldDefinition::new(
        name,
        FieldType::Keyword,
        Cardinality::Single,
        FieldOptions::new(true, true, columnar),
    )
}

fn schema() -> Schema {
    Schema::new(
        vec![
            keyword("grp", false),
            keyword("doc_id", true),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// Deterministic document description: literal fixtures only.
struct DocSpec {
    ordinal: usize,
    grp: &'static str,
    n: i64,
    alpha: usize,
    filler: usize,
}

fn spec(ordinal: usize, alpha: usize, filler: usize, grp: &'static str) -> DocSpec {
    DocSpec {
        ordinal,
        grp,
        n: (ordinal % 7) as i64,
        alpha,
        filler,
    }
}

fn body(alpha: usize, filler: usize) -> String {
    std::iter::repeat_n("alpha", alpha)
        .chain(std::iter::repeat_n("zeta", filler))
        .collect::<Vec<_>>()
        .join(" ")
}

fn document(spec: &DocSpec) -> Document {
    let mut document =
        Document::new(DocumentKey::new(format!("k{:05}", spec.ordinal)).expect("valid key"));
    document
        .insert(
            "grp",
            FieldValues::Single(FieldValue::Keyword(spec.grp.to_owned())),
        )
        .unwrap();
    document
        .insert(
            "doc_id",
            FieldValues::Single(FieldValue::Keyword(format!("d{:05}", spec.ordinal))),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(spec.n)))
        .unwrap();
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Text(body(spec.alpha, spec.filler))),
        )
        .unwrap();
    document
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(directory, schema(), registry(), IndexLimits::default())
        .expect("create index")
}

fn commit(index: &Index, specs: &[DocSpec]) {
    let mut writer = index.writer().expect("writer");
    for spec in specs {
        writer.insert(document(spec)).expect("insert");
    }
    writer.commit().expect("commit");
}

fn build(tag: &str, specs: &[DocSpec]) -> (TempDir, Arc<dyn Directory>, Index) {
    let temp = TempDir::new(tag);
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(&temp.path).expect("fs directory"));
    let writer_index = create(Arc::clone(&directory));
    if specs.is_empty() {
        // An unwritten index has no committed manifest to reopen; SC-01 only
        // needs the empty live snapshot.
        return (temp, directory, writer_index);
    }
    commit(&writer_index, specs);
    drop(writer_index);
    let index = Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    (temp, directory, index)
}

fn batch(count: usize, alpha: impl Fn(usize) -> usize) -> Vec<DocSpec> {
    (0..count)
        .map(|ordinal| spec(ordinal, alpha(ordinal), ordinal % 5, "common"))
        .collect()
}

fn term() -> Query {
    Query::Term {
        field: "body".to_owned(),
        value: FieldValue::Text("alpha".to_owned()),
    }
}

fn sort_by(field: &str, direction: SortDirection) -> Sort {
    Sort::new(vec![SortField::new(field, direction)])
}

fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top k"));
    request.sort = sort;
    request.projection = Projection::Fields(vec!["doc_id".to_owned(), "n".to_owned()]);
    request
}

fn ascend() -> Sort {
    sort_by("doc_id", SortDirection::Asc)
}

fn search_with_limits(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
    limits: SearchLimits,
    cancellation: &CancellationFlag,
) -> Result<UnifiedResponse, SearchError> {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), limits).search(
        request,
        &Budgets::new(),
        cancellation,
    )
}

fn search(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
) -> Result<UnifiedResponse, SearchError> {
    search_with_limits(
        snapshot,
        request,
        SearchLimits::default(),
        &CancellationFlag::new(),
    )
}

fn search_ok(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    search(snapshot, request).expect("search")
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// Exact score bits per logical key; fails when any selected hit is unscored.
fn bits_by_key(response: &UnifiedResponse) -> BTreeMap<String, u64> {
    response
        .hits
        .iter()
        .map(|hit| {
            (
                hit.key.as_str().to_owned(),
                hit.score.expect("lexical hit must be scored").to_bits(),
            )
        })
        .collect()
}

fn assert_same_scores(left: &UnifiedResponse, right: &UnifiedResponse) {
    assert_eq!(
        bits_by_key(left),
        bits_by_key(right),
        "score bits must be identical per logical key"
    );
}

fn assert_projection(response: &UnifiedResponse) {
    assert!(
        response.hits.iter().all(|hit| hit.fields.len() == 2
            && hit.fields[0].0 == "doc_id"
            && hit.fields[1].0 == "n"),
        "projected fields must be present and ordered"
    );
}

/// SC-01: zero matches produce zero hits, an exact zero total and no score.
#[test]
fn sc01_zero_matches_have_no_scores() {
    let (_temp, _directory, index) = build("sc01", &[]);
    let snapshot = index.snapshot();
    let response = search_ok(&snapshot, &request(term(), 10, ascend()));
    assert_eq!(response.total_hits, 0);
    assert!(response.hits.is_empty());
    assert_eq!(response.next_cursor, None);
}

/// SC-02: the single hit carries `Some(f64)` whose bits match relevance order.
#[test]
fn sc02_single_hit_explicit_sort_score_bits() {
    let (_temp, _directory, index) = build("sc02", &[spec(0, 2, 3, "common")]);
    let snapshot = index.snapshot();
    let sorted = search_ok(&snapshot, &request(term(), 10, ascend()));
    let relevance = search_ok(&snapshot, &request(term(), 10, Sort::default()));
    assert_eq!(sorted.total_hits, 1);
    assert_eq!(keys(&sorted), vec!["k00000".to_owned()]);
    assert!(sorted.hits[0].score.is_some());
    assert_eq!(bits_by_key(&sorted), bits_by_key(&relevance));
    assert_projection(&sorted);
}

/// SC-03: different term frequencies and field lengths, explicit versus
/// relevance order, exact per-key score bits.
#[test]
fn sc03_frequency_and_length_score_bits() {
    let specs: Vec<DocSpec> = (0..9)
        .map(|ordinal| spec(ordinal, ordinal % 5 + 1, ordinal * 2, "common"))
        .collect();
    let (_temp, _directory, index) = build("sc03", &specs);
    let snapshot = index.snapshot();
    let sorted = search_ok(&snapshot, &request(term(), 20, ascend()));
    let relevance = search_ok(&snapshot, &request(term(), 20, Sort::default()));
    assert_eq!(sorted.total_hits, 9);
    assert_eq!(
        keys(&sorted),
        (0..9).map(|i| format!("k{i:05}")).collect::<Vec<_>>()
    );
    assert_same_scores(&sorted, &relevance);
    assert_projection(&sorted);
}

/// SC-04: 101 matches, exact totals and page sizes for K10 and K100, with each
/// returned score bit equal to the full-result reference.
#[test]
fn sc04_hundred_and_one_matches_k10_k100() {
    let (_temp, _directory, index) = build("sc04", &batch(101, |ordinal| ordinal % 4 + 1));
    let snapshot = index.snapshot();
    let reference = search_ok(&snapshot, &request(term(), 101, ascend()));
    assert_eq!(reference.total_hits, 101);
    for top_k in [10usize, 100] {
        let page = search_ok(&snapshot, &request(term(), top_k, ascend()));
        assert_eq!(page.total_hits, 101);
        assert_eq!(page.hits.len(), top_k);
        assert_eq!(keys(&page), keys(&reference)[..top_k].to_vec());
        assert_scores_match_reference(&page, &reference);
        assert_projection(&page);
    }
}

/// Every selected hit in `page` must carry exactly the reference score bits.
fn assert_scores_match_reference(page: &UnifiedResponse, reference: &UnifiedResponse) {
    let reference_bits = bits_by_key(reference);
    for hit in &page.hits {
        let key = hit.key.as_str().to_owned();
        let expected = reference_bits
            .get(&key)
            .unwrap_or_else(|| panic!("missing reference score for {key}"));
        assert_eq!(
            hit.score.expect("page hit must be scored").to_bits(),
            *expected,
            "score bits differ for {key}"
        );
    }
}

/// SC-05: reversed direction and repeated tie-break values do not change the
/// score per key; the order is deterministic.
#[test]
fn sc05_reversed_sort_and_tie_break_scores() {
    let specs: Vec<DocSpec> = (0..12)
        .map(|ordinal| spec(ordinal, ordinal % 3 + 1, ordinal % 4, "common"))
        .collect();
    let (_temp, _directory, index) = build("sc05", &specs);
    let snapshot = index.snapshot();
    let reference = search_ok(&snapshot, &request(term(), 20, Sort::default()));
    let descending = search_ok(
        &snapshot,
        &request(term(), 6, sort_by("n", SortDirection::Desc)),
    );
    assert_scores_match_reference(&descending, &reference);
    let repeated = search_ok(
        &snapshot,
        &request(term(), 6, sort_by("n", SortDirection::Desc)),
    );
    assert_eq!(keys(&descending), keys(&repeated));
}

/// SC-06: two committed segments and a reopened reader produce the same keyed
/// scores as one segment containing the same documents.
#[test]
fn sc06_two_segments_reopen_score_parity() {
    let specs = batch(24, |ordinal| ordinal % 5 + 1);
    let (_single_temp, _single_dir, single) = build("sc06-single", &specs);
    let single_snapshot = single.snapshot();
    let single_response = search_ok(&single_snapshot, &request(term(), 30, ascend()));

    let (temp, directory, split) = build("sc06-split", &[]);
    commit(&split, &specs[..12]);
    commit(&split, &specs[12..]);
    drop(split);
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let before = search_ok(&reopened.snapshot(), &request(term(), 30, ascend()));
    assert_eq!(before.total_hits, single_response.total_hits);
    assert_same_scores(&before, &single_response);

    let after = search_ok(&reopened.snapshot(), &request(term(), 30, ascend()));
    assert_eq!(keys(&after), keys(&before));
    assert_same_scores(&after, &before);
    drop(temp);
}

/// SC-07: delete and upsert before a new snapshot leave the old PIT immutable
/// and the current snapshot internally consistent.
#[test]
fn sc07_delete_upsert_pit_immutability() {
    let (temp, directory, index) = build("sc07", &batch(500, |ordinal| ordinal % 4 + 1));
    let old = index.snapshot();
    let old_response = search_ok(&old, &request(term(), 500, ascend()));
    assert_eq!(old_response.total_hits, 500);

    {
        let mut writer = index.writer().expect("writer");
        for ordinal in 0..10usize {
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(format!("k{ordinal:05}")).expect("key"),
                ))
                .expect("delete");
        }
        for ordinal in 10..20usize {
            let mut document = document(&spec(ordinal, 5, ordinal % 3, "common"));
            document
                .insert(
                    "body",
                    FieldValues::Single(FieldValue::Text(body(5, ordinal % 3))),
                )
                .unwrap();
            writer
                .apply(MutationRequest::upsert(document))
                .expect("upsert");
        }
        writer.commit().expect("commit");
    }

    // The old PIT must not observe the mutation.
    let old_after = search_ok(&old, &request(term(), 500, ascend()));
    assert_eq!(keys(&old_after), keys(&old_response));
    assert_same_scores(&old_after, &old_response);

    let current_index =
        Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    let current = current_index.snapshot();
    let current_response = search_ok(&current, &request(term(), 500, ascend()));
    assert_eq!(current_response.total_hits, 490);
    // A fresh process-scope reopen must agree with the current snapshot.
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let reopened_response = search_ok(&reopened.snapshot(), &request(term(), 500, ascend()));
    assert_eq!(keys(&reopened_response), keys(&current_response));
    assert_same_scores(&reopened_response, &current_response);
    drop(temp);
}

/// SC-08: explicit-sort cursor pages select every document exactly once and
/// each selected score matches the full-result reference.
#[test]
fn sc08_cursor_pages_match_full_result_scores() {
    let (_temp, _directory, index) = build("sc08", &batch(101, |ordinal| ordinal % 6 + 1));
    let snapshot = index.snapshot();
    let reference = search_ok(&snapshot, &request(term(), 101, ascend()));
    let mut page_request = request(term(), 10, ascend());
    let first = search_ok(&snapshot, &page_request);
    assert!(first.next_cursor.is_some());
    page_request.after = first.next_cursor.clone();
    let second = search_ok(&snapshot, &page_request);

    let mut observed = keys(&first);
    observed.extend(keys(&second));
    let expected: Vec<String> = keys(&reference)[..20].to_vec();
    assert_eq!(observed, expected, "no repeated or omitted keys");
    for page in [&first, &second] {
        assert_scores_match_reference(page, &reference);
    }
}

/// SC-09: the ineligible `And([Term])` shape agrees with the single term on
/// keys, totals and exact score bits.
#[test]
fn sc09_ineligible_and_and_single_term_parity() {
    let (_temp, _directory, index) = build("sc09", &batch(40, |ordinal| ordinal % 4 + 1));
    let snapshot = index.snapshot();
    let single = search_ok(&snapshot, &request(term(), 50, ascend()));
    let conjunction = search_ok(&snapshot, &request(Query::And(vec![term()]), 50, ascend()));
    assert_eq!(single.total_hits, conjunction.total_hits);
    assert_eq!(keys(&single), keys(&conjunction));
    assert_same_scores(&single, &conjunction);
}

/// SC-10: filter-only typed predicates carry no BM25 score.
#[test]
fn sc10_typed_only_predicates_have_no_score() {
    let (_temp, _directory, index) = build("sc10", &batch(2, |_| 1));
    let snapshot = index.snapshot();
    for query in [
        Query::MatchAll,
        Query::Exists {
            field: "n".to_owned(),
        },
    ] {
        let response = search_ok(&snapshot, &request(query, 10, ascend()));
        assert_eq!(response.total_hits, 2);
        assert!(
            response.hits.iter().all(|hit| hit.score.is_none()),
            "typed-only hits must not carry a score"
        );
    }
}

/// SC-11: negative-only lexical and mixed typed/lexical shapes stay on the
/// general path with their established score presence.
#[test]
fn sc11_negative_only_and_mixed_score_presence() {
    let mut specs = batch(10, |_| 1);
    for ordinal in 10..14usize {
        specs.push(spec(ordinal, 0, 1, "other"));
    }
    let (_temp, _directory, index) = build("sc11", &specs);
    let snapshot = index.snapshot();
    let negative = search_ok(
        &snapshot,
        &request(Query::Not(Box::new(term())), 20, ascend()),
    );
    assert_eq!(negative.total_hits, 4);
    assert!(
        negative.hits.iter().all(|hit| hit.score.is_none()),
        "a pure negative lexical predicate has no positive contribution"
    );

    let mixed_query = Query::And(vec![
        term(),
        Query::Exists {
            field: "n".to_owned(),
        },
    ]);
    let mixed = search_ok(&snapshot, &request(mixed_query, 20, ascend()));
    let single = search_ok(&snapshot, &request(term(), 20, ascend()));
    assert_eq!(mixed.total_hits, single.total_hits);
    assert_same_scores(&mixed, &single);
}

/// SC-12: cancellation, an invalid sort and a stale PIT cursor keep their
/// existing typed categories.
#[test]
fn sc12_cancellation_and_invalid_cursor_sort_are_typed() {
    let (_temp, directory, index) = build("sc12", &batch(20, |_| 1));
    let old = index.snapshot();
    let old_page = search_ok(&old, &request(term(), 5, ascend()));
    let stale_cursor = old_page.next_cursor.clone().expect("cursor");

    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    let error = search_with_limits(
        &old,
        &request(term(), 5, ascend()),
        SearchLimits::default(),
        &cancelled,
    )
    .expect_err("cancelled search");
    assert!(matches!(error, SearchError::Cancelled));

    let error = search(
        &old,
        &request(term(), 5, sort_by("missing", SortDirection::Asc)),
    )
    .expect_err("invalid sort");
    assert!(matches!(
        error,
        SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::InvalidSortField { .. }
        ))
    ));

    commit(&index, &[spec(100, 1, 1, "common")]);
    let current_index =
        Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    let current = current_index.snapshot();
    let mut stale_request = request(term(), 5, ascend());
    stale_request.after = Some(stale_cursor);
    let error = search(&current, &stale_request).expect_err("stale cursor");
    assert!(matches!(
        error,
        SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::CursorPitMismatch
        ))
    ));
}

/// SC-13: a constrained candidate bound still fails with `ResourceLimit`.
#[test]
fn sc13_candidate_limit_stays_resource_limit() {
    let (_temp, _directory, index) = build("sc13", &batch(101, |_| 1));
    let snapshot = index.snapshot();
    let limits = SearchLimits::default()
        .with_max_segment_candidate_entries(1)
        .expect("limits");
    let error = search_with_limits(
        &snapshot,
        &request(term(), 10, ascend()),
        limits,
        &CancellationFlag::new(),
    )
    .expect_err("resource limit");
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
}

/// SC-14: repeated queries on the same and a reopened snapshot are bit stable.
#[test]
fn sc14_repeated_queries_are_bitwise_stable() {
    let (temp, directory, index) = build("sc14", &batch(37, |ordinal| ordinal % 5 + 1));
    let snapshot = index.snapshot();
    let first = search_ok(&snapshot, &request(term(), 20, ascend()));
    let second = search_ok(&snapshot, &request(term(), 20, ascend()));
    assert_eq!(keys(&first), keys(&second));
    assert_same_scores(&first, &second);

    drop(index);
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let after = search_ok(&reopened.snapshot(), &request(term(), 20, ascend()));
    assert_eq!(keys(&after), keys(&first));
    assert_same_scores(&after, &first);
    drop(temp);
}

/// SC-15: a real native filesystem commit survives a process-scope reopen and
/// serves the same scores through a freshly opened directory.
#[test]
fn sc15_native_fs_process_scope_reopen() {
    let (temp, directory, index) = build("sc15", &batch(500, |ordinal| ordinal % 7 + 1));
    let original = search_ok(&index.snapshot(), &request(term(), 50, ascend()));
    assert_eq!(original.total_hits, 500);
    drop(index);
    drop(directory);

    let reopened_directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(&temp.path).expect("fresh fs directory"));
    let reopened = Index::open_existing(reopened_directory, schema(), registry())
        .expect("process-scope reopen");
    let response = search_ok(&reopened.snapshot(), &request(term(), 50, ascend()));
    assert_eq!(keys(&response), keys(&original));
    assert_same_scores(&response, &original);
    assert_projection(&response);
}

/// Frozen pre-PERF-06-A1 BM25 formula, restated here so the A1 acceptance test
/// never derives "expected" bits from the code under test. The constants and
/// operation order are the pre-A1 ones.
fn frozen_scalar_bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> f64 {
    let tf = tf as f64;
    let df = df as f64;
    let n = n as f64;
    let dl = dl as f64;
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    let denominator = tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / avgdl);
    idf * (tf * (1.2 + 1.0)) / denominator
}

/// A1-I01: prepared query-local IDF must reproduce the pre-A1 scalar formula
/// bit-for-bit on a real committed `FsDirectory` index, both through the
/// eligible single-term path and through the generic `And([Term])` fallback.
#[test]
fn a1_i01_prepared_scoring_matches_formula_and_generic() {
    let specs: Vec<DocSpec> = (0..9)
        .map(|ordinal| spec(ordinal, ordinal % 5 + 1, ordinal * 2, "common"))
        .collect();
    let (_temp, _directory, index) = build("a1i01", &specs);
    let snapshot = index.snapshot();

    // Statistics derived independently from the fixture documents only.
    let n = specs.len() as u64;
    let df = specs.iter().filter(|spec| spec.alpha > 0).count() as u64;
    let total_tokens: u64 = specs
        .iter()
        .map(|spec| (spec.alpha + spec.filler) as u64)
        .sum();
    let avgdl = total_tokens as f64 / n as f64;
    assert_eq!(df, n, "every fixture document contains the query term");
    let expected: BTreeMap<String, u64> = specs
        .iter()
        .map(|spec| {
            let tf = spec.alpha as u64;
            let dl = (spec.alpha + spec.filler) as u64;
            (
                format!("k{:05}", spec.ordinal),
                frozen_scalar_bm25(tf, df, n, dl, avgdl).to_bits(),
            )
        })
        .collect();

    let sorts = [("explicit", ascend()), ("relevance", Sort::default())];
    for (label, sort) in sorts {
        for top_k in [10usize, 100] {
            let response = search_ok(&snapshot, &request(term(), top_k, sort.clone()));
            assert_eq!(response.total_hits, n, "{label} k{top_k} totals");
            assert_eq!(
                bits_by_key(&response),
                expected,
                "{label} k{top_k} score bits"
            );
            assert_eq!(keys(&response).len(), specs.len(), "{label} k{top_k} hits");
        }
        let conjunction = search_ok(
            &snapshot,
            &request(Query::And(vec![term()]), 100, sort.clone()),
        );
        assert_eq!(conjunction.total_hits, n, "{label} generic fallback totals");
        assert_eq!(
            bits_by_key(&conjunction),
            expected,
            "{label} generic fallback score bits"
        );
    }

    // Explicit ascending order over the full result set, K10 then K100.
    let ascending = search_ok(&snapshot, &request(term(), 100, ascend()));
    assert_eq!(
        keys(&ascending),
        (0..9)
            .map(|ordinal| format!("k{ordinal:05}"))
            .collect::<Vec<_>>()
    );
    let first_ten = search_ok(&snapshot, &request(term(), 10, ascend()));
    assert_eq!(keys(&first_ten), keys(&ascending)[..specs.len()].to_vec());
    assert_eq!(first_ten.total_hits, n);
    assert_projection(&ascending);
}

/// PERF-06-A2 I02: real `FsDirectory` writer→commit→reopen→`UnifiedSearcher`
/// parity for term, prefix, generic Boolean, phrase and absent-term queries.
///
/// Term/prefix/generic share the doc/freq-only postings view; phrase still uses
/// full positional postings. Expected membership is derived independently from
/// the `batch(12, |i| i % 3 + 1)` fixture, never from the production query.
#[test]
fn a2_i02_fs_term_prefix_phrase_and_generic_parity() {
    let document_count = 12usize;
    let alpha_frequencies: Vec<usize> = (0..document_count).map(|index| index % 3 + 1).collect();
    let expected_keys: Vec<String> = (0..document_count)
        .map(|index| format!("k{index:05}"))
        .collect();
    let specs = batch(document_count, |ordinal| ordinal % 3 + 1);
    let (_temp, directory, index) = build("a2-i02", &specs);
    let snapshot = index.snapshot();

    let term_response = search_ok(&snapshot, &request(term(), document_count, ascend()));
    assert_eq!(term_response.total_hits, document_count as u64);
    assert_eq!(keys(&term_response), expected_keys);
    assert_projection(&term_response);

    let prefix = Query::Prefix {
        field: "body".to_owned(),
        prefix: "alp".to_owned(),
    };
    let prefix_response = search_ok(&snapshot, &request(prefix, document_count, ascend()));
    assert_eq!(prefix_response.total_hits, document_count as u64);
    assert_eq!(keys(&prefix_response), expected_keys);
    assert_same_scores(&prefix_response, &term_response);

    let generic = Query::And(vec![term()]);
    let generic_response = search_ok(&snapshot, &request(generic, document_count, ascend()));
    assert_eq!(generic_response.total_hits, document_count as u64);
    assert_eq!(keys(&generic_response), expected_keys);
    assert_same_scores(&generic_response, &term_response);

    // Phrase: only documents with two adjacent `alpha` tokens (frequency >= 2).
    let expected_phrase_keys: Vec<String> = (0..document_count)
        .filter(|index| alpha_frequencies[*index] >= 2)
        .map(|index| format!("k{index:05}"))
        .collect();
    assert_eq!(expected_phrase_keys.len(), 8);
    let phrase = Query::Phrase {
        field: "body".to_owned(),
        terms: vec!["alpha".to_owned(), "alpha".to_owned()],
    };
    let phrase_response = search_ok(&snapshot, &request(phrase, document_count, ascend()));
    assert_eq!(phrase_response.total_hits, 8);
    assert_eq!(keys(&phrase_response), expected_phrase_keys);
    assert!(
        phrase_response.hits.iter().all(|hit| hit.score.is_some()),
        "phrase hits remain scored through the full positional reader"
    );

    let absent = Query::Term {
        field: "body".to_owned(),
        value: FieldValue::Text("never_present_a2".to_owned()),
    };
    let absent_response = search_ok(&snapshot, &request(absent, 10, ascend()));
    assert_eq!(absent_response.total_hits, 0);
    assert!(absent_response.hits.is_empty());

    // K10 is exactly the scored prefix of K100 under the same explicit sort.
    let reference = search_ok(&snapshot, &request(term(), 100, ascend()));
    assert_eq!(reference.total_hits, document_count as u64);
    let page = search_ok(&snapshot, &request(term(), 10, ascend()));
    assert_eq!(page.total_hits, document_count as u64);
    assert_eq!(page.hits.len(), 10);
    assert_eq!(keys(&page), keys(&reference)[..10].to_vec());
    assert_scores_match_reference(&page, &reference);
    drop(snapshot);

    // A fresh reopen of the same committed index is bitwise identical.
    let reopened =
        Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    let reopened_snapshot = reopened.snapshot();
    let reopened_response = search_ok(&reopened_snapshot, &request(term(), 100, ascend()));
    assert_eq!(keys(&reopened_response), keys(&reference));
    assert_same_scores(&reopened_response, &reference);
}
