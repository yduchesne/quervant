//! PERF-06-C2 — real filesystem vertical slices for the strict-term physical
//! executor.
//!
//! Every test in this file drives the genuine public path: a real
//! `FsDirectory`, the real writer, a real commit, a fresh `Index` reopen (or a
//! writer-refreshed snapshot for point-in-time tests), the real analyzer
//! registry and the public `UnifiedSearcher`. No fake executor, no fake
//! directory and no crate-private route counter is used here: the observable
//! oracle is a literal input-derived formula plus the independent
//! `Query::And([Term])` legacy path on the *same* snapshot.
//!
//! The B4/BM10 exact-term lane corpus (`doc_id`, `key`, `group`, `body`,
//! `payload`) is reproduced from the checked-in reviewed formula
//! `benchmarks/quervant_bench/lean/runtime.py::row_values`; this file never runs
//! a benchmark or acquires a timing sample.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag, NeverCancel};
use quervant_core::contract::aggregation::{Aggregate, Aggregation, AggregationMetricValue};
use quervant_core::contract::batch::BatchBudget;
use quervant_core::contract::batch::{BatchQueryRequest, QueryRequest};
use quervant_core::contract::budget::{BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MissingValuePosition, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::segment::{SegmentLimits, parse_container};
use quervant_core::storage::{Directory, FsDirectory};

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

/// A unique temporary directory owned by one test.
struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0);
        let serial = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "quervant-perf06-c2-{tag}-{}-{nanos}-{serial}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("create temp dir");
        Self { path }
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn directory(&self) -> Arc<dyn Directory> {
        Arc::new(FsDirectory::open(&self.path).expect("fs directory"))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

/// The accepted B4 adapter's five-field schema.
fn b4_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "key",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "group",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "payload",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .expect("schema")
}

/// The reviewed PR15D/BM10 row formula. Returns
/// `(doc_id, key, group, body, payload)`.
fn row_values(index: usize) -> (String, &'static str, &'static str, &'static str, String) {
    let key = if index == 0 {
        "singleton"
    } else if index % 2 == 0 {
        "common"
    } else {
        "other"
    };
    let group = if index % 8 == 0 {
        "medium"
    } else {
        "different"
    };
    let body = if index % 2 == 0 {
        "alpha beta"
    } else {
        "gamma delta"
    };
    (
        format!("d{index:08}"),
        key,
        group,
        body,
        format!("payload-{index:08}"),
    )
}

fn b4_document(index: usize) -> Document {
    let (doc_id, key, group, body, payload) = row_values(index);
    let mut document = Document::new(DocumentKey::new(doc_id.clone()).expect("key"));
    document
        .insert("doc_id", FieldValues::Single(FieldValue::Keyword(doc_id)))
        .expect("doc_id");
    document
        .insert(
            "key",
            FieldValues::Single(FieldValue::Keyword(key.to_owned())),
        )
        .expect("key");
    document
        .insert(
            "group",
            FieldValues::Single(FieldValue::Keyword(group.to_owned())),
        )
        .expect("group");
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Keyword(body.to_owned())),
        )
        .expect("body");
    document
        .insert("payload", FieldValues::Single(FieldValue::Keyword(payload)))
        .expect("payload");
    document
}

/// The bounded writer limits required for a single-commit 100K corpus. The
/// published `IndexLimits::default()` caps pending documents at 10,000, so a
/// 100K single commit must use explicit limits; global defaults are untouched.
fn large_index_limits() -> IndexLimits {
    IndexLimits::new()
        .with_max_pending_docs(1_000_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
        .with_max_replay_entries(1_000_000)
        .with_max_replay_bytes(256 * 1024 * 1024)
}

/// A committed on-disk corpus and its reopened index/snapshot.
struct Corpus {
    _temp: TempDir,
    schema: Schema,
    registry: AnalyzerRegistry,
    /// Retained so the opened index handle stays alive for the whole test.
    _index: Index,
    snapshot: Arc<ReaderSnapshot>,
}

impl Corpus {
    /// Build `segments.len()` commits, each carrying one slice of the B4 corpus.
    fn build(tag: &str, segments: &[Vec<usize>]) -> Self {
        let temp = TempDir::new(tag);
        let directory = temp.directory();
        let schema = b4_schema();
        let registry = AnalyzerRegistry::builtin();
        let limits = large_index_limits();
        {
            let index = Index::create_with_limits(
                Arc::clone(&directory),
                schema.clone(),
                registry.clone(),
                limits.clone(),
            )
            .expect("create");
            for segment in segments {
                let mut writer = index.writer().expect("writer");
                for index in segment {
                    writer.insert(b4_document(*index)).expect("insert");
                }
                writer.commit().expect("commit");
            }
        }
        let index =
            Index::open_with_limits(directory, schema.clone(), registry.clone(), limits.clone())
                .expect("reopen");
        let snapshot = index.snapshot();
        Self {
            _temp: temp,
            schema,
            registry,
            _index: index,
            snapshot,
        }
    }

    fn single(tag: &str, count: usize) -> Self {
        Self::build(tag, &[(0..count).collect()])
    }

    fn searcher(&self) -> UnifiedSearcher<'_> {
        UnifiedSearcher::new(
            &self.snapshot,
            &self.schema,
            &self.registry,
            SearchLimits::default(),
        )
    }

    fn searcher_with(&self, limits: SearchLimits) -> UnifiedSearcher<'_> {
        UnifiedSearcher::new(&self.snapshot, &self.schema, &self.registry, limits)
    }
}

/// The four exact-term lanes: `(field, term, literal expected count)`.
fn class_expectation(class: &str, count: usize) -> (&'static str, &'static str, u64) {
    match class {
        "absent" => ("key", "never", 0),
        "rare" => ("key", "singleton", 1),
        "medium" => ("group", "medium", (count / 8) as u64),
        "common" => ("key", "common", (count / 2 - 1) as u64),
        other => panic!("unknown class {other}"),
    }
}

/// An exact-term query on an indexed `Keyword` field.
fn term_query(field: &str, term: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(term.to_owned()),
    }
}

/// An exact-term query on an analyzed `Text` field.
fn text_term(field: &str, term: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Text(term.to_owned()),
    }
}

/// The independent, semantically equivalent legacy route for the same term.
fn legacy_query(field: &str, term: &str) -> Query {
    Query::And(vec![term_query(field, term)])
}

/// The same ineligible Legacy comparison for an analyzed `Text` field.
fn legacy_text_query(field: &str, term: &str) -> Query {
    Query::And(vec![text_term(field, term)])
}

fn doc_id_sort(direction: SortDirection) -> Sort {
    let mut field = SortField::new("doc_id", direction);
    field.missing = MissingValuePosition::Last;
    Sort::new(vec![field])
}

fn full_projection() -> Projection {
    Projection::Fields(vec![
        "doc_id".to_owned(),
        "key".to_owned(),
        "group".to_owned(),
        "body".to_owned(),
        "payload".to_owned(),
    ])
}

/// Full projection for the scoring fixture (it has no `key`/`group`/`payload`).
fn scoring_projection() -> Projection {
    Projection::Fields(vec!["doc_id".to_owned(), "body".to_owned()])
}

fn request(query: Query, top_k: usize, sort: Sort, projection: Projection) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = sort;
    request.projection = projection;
    request
}

fn search(corpus: &Corpus, request: &UnifiedRequest) -> Result<UnifiedResponse, SearchError> {
    corpus
        .searcher()
        .search(request, &Budgets::new(), &NeverCancel)
}

fn search_with(
    corpus: &Corpus,
    request: &UnifiedRequest,
    limits: SearchLimits,
    cancel: &dyn Cancellation,
) -> Result<UnifiedResponse, SearchError> {
    corpus
        .searcher_with(limits)
        .search(request, &Budgets::new(), cancel)
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn scores(response: &UnifiedResponse) -> Vec<Option<u64>> {
    response
        .hits
        .iter()
        .map(|hit| hit.score.map(f64::to_bits))
        .collect()
}

/// The literal ascending first `min(k, count)` document ids of the corpus,
/// filtered by the lane predicate.
fn expected_lane_keys(class: &str, count: usize, top_k: usize, ascending: bool) -> Vec<String> {
    let mut ids: Vec<String> = (0..count)
        .filter(|index| match class {
            "absent" => false,
            "rare" => *index == 0,
            "medium" => index % 8 == 0,
            "common" => *index != 0 && index % 2 == 0,
            other => panic!("unknown class {other}"),
        })
        .map(|index| row_values(index).0)
        .collect();
    if !ascending {
        ids.reverse();
    }
    ids.truncate(top_k);
    ids
}

// ---------------------------------------------------------------------------
// C2-I01 / C2-I10 — real writer/commit/reopen, 10K and 100K, exact-term lanes
// ---------------------------------------------------------------------------

/// C2-I01 plus C2-I10: the accepted B4 logical exact-keyword workload, executed
/// on genuine `FsDirectory` segments. Sixteen lanes = 4 classes x {10K, 100K} x
/// K in {10, 100}. Each lane asserts the literal expected count, the ascending
/// first `min(K, M)` keys, the full projected fields, cursor presence and
/// bit-identical scores against the ineligible `And([Term])` reference.
#[test]
fn c2_i01_i10_b4_formula_exact_term_lanes() {
    let corpus_10k = Corpus::single("b4-10k", 10_000);
    let corpus_100k = Corpus::single("b4-100k", 100_000);
    for (corpus, count) in [(&corpus_10k, 10_000usize), (&corpus_100k, 100_000)] {
        for class in ["absent", "rare", "medium", "common"] {
            let (field, term, expected) = class_expectation(class, count);
            for top_k in [10usize, 100] {
                let page = request(
                    term_query(field, term),
                    top_k,
                    doc_id_sort(SortDirection::Asc),
                    full_projection(),
                );
                let response = search(corpus, &page).expect("search");
                assert_eq!(response.total_hits, expected, "{class} {count} k={top_k}");
                let want = expected_lane_keys(class, count, top_k, true);
                assert_eq!(keys(&response), want, "{class} {count} k={top_k}");
                assert_eq!(
                    response.next_cursor.is_some(),
                    expected > top_k as u64,
                    "{class} {count} k={top_k} cursor"
                );
                for hit in &response.hits {
                    let projected: Vec<&str> =
                        hit.fields.iter().map(|(name, _)| name.as_str()).collect();
                    assert_eq!(
                        projected,
                        ["doc_id", "key", "group", "body", "payload"],
                        "{class} {count} k={top_k} projection order"
                    );
                }
                // Independent legacy route on the same snapshot: same hits, same
                // score bits, same count. (The wrapper query legitimately has a
                // different cursor fingerprint, so only presence is compared.)
                let reference = search(
                    corpus,
                    &request(
                        legacy_query(field, term),
                        top_k,
                        doc_id_sort(SortDirection::Asc),
                        full_projection(),
                    ),
                )
                .expect("legacy reference");
                assert_eq!(reference.total_hits, response.total_hits);
                assert_eq!(keys(&reference), keys(&response));
                assert_eq!(scores(&reference), scores(&response));
                assert_eq!(
                    reference.next_cursor.is_some(),
                    response.next_cursor.is_some()
                );
            }
        }
    }
}

// ---------------------------------------------------------------------------
// C2-I02 — scores, full projection and reverse sort
// ---------------------------------------------------------------------------

/// A corpus whose term frequencies and document lengths differ, so BM25 scores
/// are genuinely distinct, with a sortable Keyword column plus missing/null/
/// multivalue-one variants.
fn scoring_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "grp",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
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
    .expect("schema")
}

fn scoring_document(index: usize) -> Document {
    let mut document = Document::new(DocumentKey::new(format!("s{index:04}")).expect("key"));
    document
        .insert(
            "grp",
            FieldValues::Single(FieldValue::Keyword("common".to_owned())),
        )
        .expect("grp");
    document
        .insert(
            "doc_id",
            FieldValues::Single(FieldValue::Keyword(format!("s{index:04}"))),
        )
        .expect("doc_id");
    let mut words: Vec<&str> = vec!["alpha"; 1 + index % 4];
    words.extend(std::iter::repeat_n("gamma", index % 5));
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Text(words.join(" "))),
        )
        .expect("body");
    document
}

#[test]
fn c2_i02_scores_full_projection_and_reverse_sort() {
    let temp = TempDir::new("i02");
    let directory = temp.directory();
    let schema = scoring_schema();
    let registry = AnalyzerRegistry::builtin();
    {
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            large_index_limits(),
        )
        .expect("create");
        let mut writer = index.writer().expect("writer");
        for position in 0..40usize {
            writer.insert(scoring_document(position)).expect("insert");
        }
        writer.commit().expect("commit");
    }
    let index = Index::open_with_limits(
        directory,
        schema.clone(),
        registry.clone(),
        large_index_limits(),
    )
    .expect("reopen");
    let snapshot = index.snapshot();
    let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
    let query = text_term("body", "alpha");
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        let page = request(
            query.clone(),
            10,
            doc_id_sort(direction),
            scoring_projection(),
        );
        let response = searcher
            .search(&page, &Budgets::new(), &NeverCancel)
            .expect("physical");
        let reference = searcher
            .search(
                &request(
                    legacy_text_query("body", "alpha"),
                    10,
                    doc_id_sort(direction),
                    scoring_projection(),
                ),
                &Budgets::new(),
                &NeverCancel,
            )
            .expect("legacy");
        assert_eq!(keys(&response), keys(&reference), "{direction:?}");
        assert_eq!(scores(&response), scores(&reference), "{direction:?}");
        assert_eq!(response.total_hits, 40);
        // Independent literal order oracle over zero-padded ids.
        let mut wanted: Vec<String> = (0..40).map(|index| format!("s{index:04}")).collect();
        if direction == SortDirection::Desc {
            wanted.reverse();
        }
        wanted.truncate(10);
        assert_eq!(keys(&response), wanted, "{direction:?} literal order");
        // Scores are distinct enough that the two directions disagree on order.
        for hit in &response.hits {
            let score = hit.score.expect("lexical score");
            assert!(score.is_finite() && score >= 0.0);
        }
    }
    // The ascending and descending pages must not be identical.
    let ascending = searcher
        .search(
            &request(
                query.clone(),
                10,
                doc_id_sort(SortDirection::Asc),
                scoring_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("asc");
    let descending = searcher
        .search(
            &request(
                query,
                10,
                doc_id_sort(SortDirection::Desc),
                scoring_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("desc");
    assert_ne!(keys(&ascending), keys(&descending));
    assert_eq!(scores(&ascending).len(), scores(&descending).len());
}

// ---------------------------------------------------------------------------
// C2-I03 — PIT, update, delete, merge and reopen
// ---------------------------------------------------------------------------

#[test]
fn c2_i03_pit_update_delete_merge_reopen() {
    let temp = TempDir::new("i03");
    let directory = temp.directory();
    let schema = b4_schema();
    let registry = AnalyzerRegistry::builtin();
    let limits = large_index_limits();
    {
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            limits.clone(),
        )
        .expect("create");
        for segment in [0usize..40, 40..80, 80..120] {
            let mut writer = index.writer().expect("writer");
            for position in segment {
                writer.insert(b4_document(position)).expect("insert");
            }
            writer.commit().expect("commit");
        }
    }
    let mut index =
        Index::open_with_limits(directory, schema.clone(), registry.clone(), limits.clone())
            .expect("reopen");
    let old = index.snapshot();
    let common = |top_k: usize| {
        request(
            term_query("key", "common"),
            top_k,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        )
    };
    let old_searcher = UnifiedSearcher::new(&old, &schema, &registry, SearchLimits::default());
    let before = old_searcher
        .search(&common(10), &Budgets::new(), &NeverCancel)
        .expect("old view");
    assert_eq!(before.total_hits, 59, "0..120 even minus the singleton");

    // Delete two matching documents, update another, add one new match.
    let new_snapshot = {
        let mut writer = index.writer().expect("writer");
        for key in ["d00000002", "d00000004"] {
            writer
                .apply(quervant_core::contract::document::MutationRequest::delete(
                    DocumentKey::new(key).expect("key"),
                ))
                .expect("delete");
        }
        let mut updated = b4_document(6);
        updated
            .insert(
                "key",
                FieldValues::Single(FieldValue::Keyword("other".to_owned())),
            )
            .expect("key");
        writer
            .apply(quervant_core::contract::document::MutationRequest::upsert(
                updated,
            ))
            .expect("upsert");
        writer.insert(b4_document(9999)).expect("insert");
        writer.commit().expect("commit");
        writer.refresh().expect("refresh")
    };
    let new_searcher =
        UnifiedSearcher::new(&new_snapshot, &schema, &registry, SearchLimits::default());
    let after = new_searcher
        .search(&common(10), &Budgets::new(), &NeverCancel)
        .expect("new view");
    assert_eq!(
        after.total_hits, 56,
        "59 - 2 deleted - 1 updated (doc 6 leaves the class); doc 9999 is odd"
    );
    assert!(keys(&after).iter().all(|key| key != "d00000002"));
    assert!(keys(&before).iter().all(|key| key != "d00009999"));

    // The pinned old snapshot is unaffected by the newer generation.
    let pinned = old_searcher
        .search(&common(10), &Budgets::new(), &NeverCancel)
        .expect("pinned view");
    assert_eq!(pinned.total_hits, 59);
    assert_eq!(pinned.generation, before.generation);
    assert_ne!(after.generation, before.generation);

    // Merge/compact then reopen from disk: the surviving generation must answer
    // exactly like the merged snapshot.
    {
        let mut writer = index.writer().expect("writer");
        writer.compact().expect("compact");
        writer.commit().expect("commit compact");
    }
    index = Index::open_with_limits(
        Arc::new(FsDirectory::open(temp.path()).expect("fs")),
        schema.clone(),
        registry.clone(),
        limits,
    )
    .expect("reopen after compaction");
    let reopened = index.snapshot();
    let reopened_searcher =
        UnifiedSearcher::new(&reopened, &schema, &registry, SearchLimits::default());
    let merged = reopened_searcher
        .search(&common(10), &Budgets::new(), &NeverCancel)
        .expect("merged view");
    assert_eq!(merged.total_hits, 56);
    assert_eq!(keys(&merged), keys(&after));
}

// ---------------------------------------------------------------------------
// C2-I04 — real keys and the duplicate policy
// ---------------------------------------------------------------------------

#[test]
fn c2_i04_duplicates_and_optional_fallback() {
    // Repeated upserts of one logical key never produce two live hits: identity is
    // the exact logical key, and the physical route agrees with the legacy route.
    let temp = TempDir::new("i04");
    let directory = temp.directory();
    let schema = b4_schema();
    let registry = AnalyzerRegistry::builtin();
    let limits = large_index_limits();
    {
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            limits.clone(),
        )
        .expect("create");
        let mut writer = index.writer().expect("writer");
        for position in 0..30usize {
            writer.insert(b4_document(position)).expect("insert");
        }
        writer.commit().expect("commit");
        for _ in 0..3 {
            writer
                .apply(quervant_core::contract::document::MutationRequest::upsert(
                    b4_document(2),
                ))
                .expect("upsert");
        }
        writer.commit().expect("commit");
    }
    let index = Index::open_with_limits(directory, schema.clone(), registry.clone(), limits)
        .expect("reopen");
    let snapshot = index.snapshot();
    let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
    let physical = searcher
        .search(
            &request(
                term_query("key", "common"),
                5,
                doc_id_sort(SortDirection::Asc),
                full_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("physical");
    let reference = searcher
        .search(
            &request(
                legacy_query("key", "common"),
                5,
                doc_id_sort(SortDirection::Asc),
                full_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("legacy");
    assert_eq!(physical.total_hits, 14, "even non-zero ids in 0..30");
    assert_eq!(keys(&physical), keys(&reference));
    assert_eq!(scores(&physical), scores(&reference));
    // Every returned key is a real, projection-backed document key.
    for hit in &physical.hits {
        let projected = hit
            .fields
            .iter()
            .find(|(name, _)| name == "doc_id")
            .expect("doc_id projected");
        assert_eq!(
            projected.1,
            FieldValues::Single(FieldValue::Keyword(hit.key.as_str().to_owned()))
        );
    }
    // Forced-ExactSet duplicate mode (unit-seam only) and segment-level B3 refusal
    // are proved by `search::unified::c2_tests::c2_u17_ordinal_unavailable_and_b3_refusal`;
    // this test proves the public duplicate outcome.
}

// ---------------------------------------------------------------------------
// C2-I05 — real multi-page cursor
// ---------------------------------------------------------------------------

#[test]
fn c2_i05_real_cursor_multi_page() {
    let corpus = Corpus::single("i05", 60);
    let mut collected: Vec<String> = Vec::new();
    let mut cursor = None;
    let mut pages = 0usize;
    loop {
        let mut request = request(
            term_query("key", "common"),
            7,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        );
        request.after = cursor;
        let response = search(&corpus, &request).expect("page");
        collected.extend(keys(&response));
        pages += 1;
        assert!(pages < 20, "bounded paging");
        match response.next_cursor {
            Some(next) => cursor = Some(next),
            None => break,
        }
    }
    let expected = expected_lane_keys("common", 60, usize::MAX, true);
    assert_eq!(collected, expected);
    assert_eq!(
        collected.len(),
        collected
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
    );
    assert!(pages > 1);
}

// ---------------------------------------------------------------------------
// C2-I06 — authenticated committed segment bytes
// ---------------------------------------------------------------------------

#[test]
fn c2_i06_corrupt_container_and_legacy_errors() {
    let corpus = Corpus::single("i06", 32);
    let guard = corpus
        .snapshot
        .open_segment_reader(0)
        .expect("guarded segment reader");
    let bytes = guard.reader().bytes().to_vec();
    drop(guard);
    // The committed bytes are a self-describing, checksummed container.
    let view = parse_container(&bytes, &SegmentLimits::default()).expect("container");
    assert!(view.doc_count() >= 32);
    // A single flipped byte in the payload region must be rejected by the codec:
    // there is no path that silently serves tampered committed data.
    let mut tampered = bytes.clone();
    let midpoint = tampered.len() / 2;
    tampered[midpoint] ^= 0xFF;
    assert!(
        quervant_core::segment::SegmentReader::open(tampered, SegmentLimits::default()).is_err(),
        "a checksum mismatch must be rejected at open"
    );
    // The pristine committed segment still answers through the public path.
    let response = search(
        &corpus,
        &request(
            term_query("key", "common"),
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("pristine search");
    assert_eq!(response.total_hits, 15);
    // Structural corruption fixtures for the selected/unselected posting and key
    // bodies are executed by the crate unit tests
    // `search::execute::c2_physical_tests::{c2_p03_corrupt_postings_precede_every_callback,
    // c2_p04_late_score_fault_precedes_corrupt_doc_keys}`; a committed filesystem
    // segment cannot be rewritten behind its recorded digest.
}

// ---------------------------------------------------------------------------
// C2-I07 — batch, aggregation and unsupported shapes
// ---------------------------------------------------------------------------

#[test]
fn c2_i07_batch_aggregate_and_unsupported_shapes() {
    let corpus = Corpus::single("i07", 40);
    // Batch slot with a real aggregation over the same index. Batch execution
    // creates its own cumulative meter, so the physical route can never be used.
    let mut query = QueryRequest::new(term_query("key", "common"));
    query.sort = doc_id_sort(SortDirection::Asc);
    query.top_k = TopK::new(5).expect("top-k");
    query.projection = full_projection();
    let mut aggregation = Aggregation::new();
    aggregation.aggregates.push(Aggregate::count());
    query.aggregation = Some(aggregation);
    let batch_request = BatchQueryRequest::new(vec![query], None, BatchBudget::new(2));
    // An explicit, generous test-only batch policy; the checked-in default policy
    // intentionally leaves the batch budgets unconfigured.
    let policy = BudgetPolicy::new(
        Budgets::new()
            .with(
                quervant_core::contract::budget::BudgetKind::QueriesPerBatch,
                16,
            )
            .expect("queries")
            .with(
                quervant_core::contract::budget::BudgetKind::BatchMemoryBytes,
                1 << 30,
            )
            .expect("memory")
            .with(
                quervant_core::contract::budget::BudgetKind::BatchResponseBytes,
                1 << 30,
            )
            .expect("response")
            .with(
                quervant_core::contract::budget::BudgetKind::BatchAggregate,
                1 << 30,
            )
            .expect("work"),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    );
    let response = quervant_core::search::execute_batch(
        &corpus.snapshot,
        &corpus.schema,
        &corpus.registry,
        SearchLimits::default(),
        &batch_request,
        &policy,
        &CapabilitySet::new(),
        &NeverCancel,
    )
    .expect("batch aggregation");
    let slots = response.results();
    assert_eq!(slots.len(), 1);
    let aggregated = match &slots[0] {
        quervant_core::contract::batch::PerQueryOutcome::Success(hit) => hit,
        other => panic!("unexpected batch outcome: {other:?}"),
    };
    assert_eq!(aggregated.total_hits, 19);
    let aggregation = aggregated.aggregation.as_ref().expect("aggregation result");
    assert_eq!(aggregation.groups.len(), 1);
    assert!(matches!(
        aggregation.groups[0].metrics.as_slice(),
        [AggregationMetricValue::Count(19)]
    ));
    // Multi-term expansion, typed and Boolean shapes keep their own results.
    let prefix = search(
        &corpus,
        &request(
            Query::Prefix {
                field: "key".to_owned(),
                prefix: "comm".to_owned(),
            },
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("prefix");
    assert_eq!(prefix.total_hits, 19);
    let boolean = search(
        &corpus,
        &request(
            Query::Or(vec![
                term_query("key", "singleton"),
                term_query("key", "common"),
            ]),
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("boolean");
    assert_eq!(boolean.total_hits, 20);
    let typed = search(
        &corpus,
        &request(
            Query::Exists {
                field: "doc_id".to_owned(),
            },
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("typed");
    assert_eq!(typed.total_hits, 40);
    for hit in &typed.hits {
        assert!(hit.score.is_none(), "a filter-only hit has no score");
    }
}

// ---------------------------------------------------------------------------
// C2-I08 — resource and cancellation atomicity
// ---------------------------------------------------------------------------

#[test]
fn c2_i08_resource_cancellation_atomicity() {
    let corpus = Corpus::single("i08", 48);
    let page = request(
        term_query("key", "common"),
        3,
        doc_id_sort(SortDirection::Asc),
        full_projection(),
    );
    // `m = 23` per-segment effective-live matches: the virtual peak is
    // `3m = 69` entries and `128m = 2944` bytes. Every document is live with
    // persisted native norms, so statistics preparation is scan-free and the
    // evaluator scans exactly 23 posting occurrences.
    let expected_keys = expected_lane_keys("common", 48, 3, true);
    assert_eq!(
        expected_keys,
        vec![
            "d00000002".to_owned(),
            "d00000004".to_owned(),
            "d00000006".to_owned()
        ],
        "literal ascending common lane"
    );

    /// Assert that `observed` is the exact admitted response: hit count, total,
    /// generation, view ordinal, ordered keys and projected fields, explicit score
    /// bits, the **complete cursor** and the aggregation payload.
    fn assert_same_response(left: &UnifiedResponse, right: &UnifiedResponse, label: &str) {
        assert_eq!(left.hits.len(), right.hits.len(), "{label}: hit count");
        assert_eq!(left.total_hits, right.total_hits, "{label}: total hits");
        assert_eq!(left.generation, right.generation, "{label}: generation");
        assert_eq!(
            left.view_ordinal, right.view_ordinal,
            "{label}: view ordinal"
        );
        assert_eq!(
            left.next_cursor, right.next_cursor,
            "{label}: complete cursor"
        );
        assert_eq!(left.aggregation, right.aggregation, "{label}: aggregation");
        assert_eq!(scores(left), scores(right), "{label}: score bits");
        for (a, b) in left.hits.iter().zip(right.hits.iter()) {
            assert_eq!(a.key, b.key, "{label}: key");
            assert_eq!(a.fields, b.fields, "{label}: projected fields");
        }
    }

    let exact = SearchLimits::default()
        .with_max_segment_candidate_entries(69)
        .expect("entries")
        .with_max_total_candidate_bytes(2944)
        .expect("bytes");
    let admitted = search_with(&corpus, &page, exact, &NeverCancel).expect("exact peak");
    assert_eq!(admitted.total_hits, 23);
    assert_eq!(keys(&admitted), expected_keys);
    assert!(admitted.next_cursor.is_some());

    // One-under entry budget: the exact typed error, then an independent retry
    // with the admitted limits on the *same* immutable snapshot.
    let under_entries = SearchLimits::default()
        .with_max_segment_candidate_entries(68)
        .expect("entries")
        .with_max_total_candidate_bytes(2944)
        .expect("bytes");
    let rejected =
        search_with(&corpus, &page, under_entries, &NeverCancel).expect_err("one-under entries");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 68,
                requested: 69
            }
        ),
        "{rejected:?}"
    );
    let recovered = search_with(&corpus, &page, exact, &NeverCancel).expect("retry after entries");
    assert_same_response(&recovered, &admitted, "post-entries retry");

    // One-under byte budget.
    let under_bytes = SearchLimits::default()
        .with_max_segment_candidate_entries(69)
        .expect("entries")
        .with_max_total_candidate_bytes(2943)
        .expect("bytes");
    let rejected =
        search_with(&corpus, &page, under_bytes, &NeverCancel).expect_err("one-under bytes");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 2943,
                requested: 2944
            }
        ),
        "{rejected:?}"
    );
    let recovered = search_with(&corpus, &page, exact, &NeverCancel).expect("retry after bytes");
    assert_same_response(&recovered, &admitted, "post-bytes retry");

    // Scanned-occurrence boundary on the two-segment corpus: 11 + 12 = 23
    // matching postings, one occurrence each.
    let split = Corpus::build("i08-split", &[(0..24).collect(), (24..48).collect()]);
    let scanned_23 = SearchLimits::default()
        .with_max_scanned_posting_occurrences(23)
        .expect("scanned");
    let split_admitted =
        search_with(&split, &page, scanned_23, &NeverCancel).expect("exact scanned limit");
    assert_eq!(split_admitted.total_hits, 23);
    assert_eq!(keys(&split_admitted), expected_keys);
    assert!(split_admitted.next_cursor.is_some());
    let scanned_22 = SearchLimits::default()
        .with_max_scanned_posting_occurrences(22)
        .expect("scanned");
    let rejected =
        search_with(&split, &page, scanned_22, &NeverCancel).expect_err("one-under scanned");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 22,
                requested: 23
            }
        ),
        "{rejected:?}"
    );
    let recovered =
        search_with(&split, &page, scanned_23, &NeverCancel).expect("retry after scanned");
    assert_same_response(&recovered, &split_admitted, "post-scanned retry");

    // Cancellation returns the typed error and leaves the index usable.
    let flag = CancellationFlag::new();
    flag.cancel();
    let cancelled =
        search_with(&corpus, &page, SearchLimits::default(), &flag).expect_err("cancelled");
    assert!(matches!(cancelled, SearchError::Cancelled), "{cancelled:?}");
    let retried = search(&corpus, &page).expect("retry after cancellation");
    assert_same_response(&retried, &admitted, "post-cancellation retry");
    // A failed or cancelled request returns no partial page: every rejection above
    // produced `Err`, and each retry produced the exact admitted response.
}

// ---------------------------------------------------------------------------
// C2-I09 — empty and sparse physical segments
// ---------------------------------------------------------------------------

#[test]
fn c2_i09_empty_and_sparse_physical_segments() {
    // Request-wide M > K+1 while the per-segment distribution is 0 / 1 / M.
    // Segment 0 has eight documents but no matching "common" document, segment 1
    // holds only the rare singleton, and segment 2 holds the remaining matches.
    let corpus = Corpus::build(
        "i09",
        &[
            (1..9).collect::<Vec<usize>>(),
            vec![0usize],
            (9..40).collect::<Vec<usize>>(),
        ],
    );
    let page = request(
        term_query("key", "common"),
        5,
        doc_id_sort(SortDirection::Asc),
        full_projection(),
    );
    let response = search(&corpus, &page).expect("search");
    assert_eq!(response.total_hits, 19, "even non-zero ids below 40");
    assert_eq!(keys(&response), expected_lane_keys("common", 40, 5, true));
    assert!(response.next_cursor.is_some());
    let reference = search(
        &corpus,
        &request(
            legacy_query("key", "common"),
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("legacy");
    assert_eq!(keys(&reference), keys(&response));
    assert_eq!(scores(&reference), scores(&response));
    // Only the singleton is in the sparse segments: a query that matches nothing
    // there still returns the exact global count.
    let rare = search(
        &corpus,
        &request(
            term_query("key", "singleton"),
            5,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("rare");
    assert_eq!(rare.total_hits, 1);
    assert!(rare.next_cursor.is_none());
}

// ---------------------------------------------------------------------------
// PERF-06-C3 — certified deferred BM25 on real persistent indexes
// ---------------------------------------------------------------------------

/// The input-derived `body` term frequency and field length of `scoring_document`.
fn scoring_tf(index: usize) -> u64 {
    (1 + index % 4) as u64
}

fn scoring_dl(index: usize) -> u64 {
    (1 + index % 4 + index % 5) as u64
}

fn scoring_body(index: usize) -> String {
    let mut words: Vec<&str> = vec!["alpha"; 1 + index % 4];
    words.extend(std::iter::repeat_n("gamma", index % 5));
    words.join(" ")
}

fn scoring_doc_key(index: usize) -> String {
    format!("s{index:04}")
}

/// The frozen scalar BM25 oracle for the scoring corpus.
fn scoring_oracle(tf: u64, dl: u64, df: u64, n: u64, total_length: u64) -> f64 {
    let avgdl = total_length as f64 / n as f64;
    let idf = (1.0_f64 + (n as f64 - df as f64 + 0.5) / (df as f64 + 0.5)).ln();
    let tf = tf as f64;
    let dl = dl as f64;
    0.0_f64 + (idf * (tf * (1.2 + 1.0)) / (tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / avgdl)))
}

/// Build two committed segments (slices `0..split` and `split..count`) with the
/// scoring schema, close, and reopen from a real `FsDirectory`.
fn reopen_scoring_corpus(tag: &str, count: usize, split: usize) -> (TempDir, Schema, Index) {
    let temp = TempDir::new(tag);
    let directory = temp.directory();
    let schema = scoring_schema();
    let registry = AnalyzerRegistry::builtin();
    {
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            large_index_limits(),
        )
        .expect("create");
        for slice in [0..split, split..count] {
            let mut writer = index.writer().expect("writer");
            for position in slice {
                writer.insert(scoring_document(position)).expect("insert");
            }
            writer.commit().expect("commit");
        }
    }
    let index = Index::open_with_limits(directory, schema.clone(), registry, large_index_limits())
        .expect("reopen");
    (temp, schema, index)
}

#[test]
fn c3_i01_real_scores_and_explicit_cursor() {
    let (_temp, schema, index) = reopen_scoring_corpus("c3-i01", 40, 6);
    let snapshot = index.snapshot();
    let registry = AnalyzerRegistry::builtin();
    let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
    let total_length: u64 = (0..40).map(scoring_dl).sum();
    assert_eq!(total_length, 180, "input-derived total field length");
    let query = text_term("body", "alpha");

    let mut combinations = 0usize;
    for top_k in [1usize, 3, 10] {
        for direction in [SortDirection::Asc, SortDirection::Desc] {
            let page = request(
                query.clone(),
                top_k,
                doc_id_sort(direction),
                scoring_projection(),
            );
            let response = searcher
                .search(&page, &Budgets::new(), &NeverCancel)
                .expect("certified response");
            assert_eq!(response.total_hits, 40, "{direction:?} k={top_k}");

            let mut indices: Vec<usize> = (0..40).collect();
            if direction == SortDirection::Desc {
                indices.reverse();
            }
            indices.truncate(top_k);
            let expected_keys: Vec<String> = indices.iter().map(|i| scoring_doc_key(*i)).collect();
            assert_eq!(keys(&response), expected_keys, "{direction:?} k={top_k}");

            for (rank, hit) in response.hits.iter().enumerate() {
                let index = indices[rank];
                assert_eq!(
                    hit.fields,
                    vec![
                        (
                            "doc_id".to_owned(),
                            FieldValues::Single(FieldValue::Keyword(scoring_doc_key(index)))
                        ),
                        (
                            "body".to_owned(),
                            FieldValues::Single(FieldValue::Text(scoring_body(index)))
                        ),
                    ],
                    "{direction:?} k={top_k} rank={rank}: full projection"
                );
                let score = hit.score.expect("lexical score");
                assert!(score.is_finite() && score >= 0.0);
                assert_eq!(
                    score.to_bits(),
                    scoring_oracle(scoring_tf(index), scoring_dl(index), 40, 40, total_length)
                        .to_bits(),
                    "{direction:?} k={top_k} rank={rank}: independent score bits"
                );
            }

            // Independent wrapper query (a different AST, hence a different
            // fingerprint) on the same snapshot.
            let wrapper = request(
                legacy_text_query("body", "alpha"),
                top_k,
                doc_id_sort(direction),
                scoring_projection(),
            );
            let reference = searcher
                .search(&wrapper, &Budgets::new(), &NeverCancel)
                .expect("legacy wrapper");
            assert_eq!(keys(&response), keys(&reference));
            assert_eq!(scores(&response), scores(&reference));
            assert_eq!(response.total_hits, reference.total_hits);
            assert_eq!(response.generation, reference.generation);
            assert_eq!(response.view_ordinal, reference.view_ordinal);
            assert_eq!(response.aggregation, reference.aggregation);
            for (left, right) in response.hits.iter().zip(reference.hits.iter()) {
                assert_eq!(left.fields, right.fields);
            }
            // The wrapper differs only in the cursor fingerprint.
            let actual_cursor = response.next_cursor.as_ref().expect("cursor");
            let reference_cursor = reference.next_cursor.as_ref().expect("cursor");
            assert_eq!(
                actual_cursor.snapshot_binding(),
                reference_cursor.snapshot_binding()
            );
            assert_eq!(actual_cursor.last_key(), reference_cursor.last_key());
            assert_eq!(
                actual_cursor.last_sort_values(),
                reference_cursor.last_sort_values()
            );
            assert_eq!(actual_cursor.last_score(), None, "explicit sort");
            assert_eq!(reference_cursor.last_score(), None, "explicit sort");

            // The identical query re-run is a complete response equality.
            let repeated = searcher
                .search(&page, &Budgets::new(), &NeverCancel)
                .expect("repeated response");
            assert_eq!(response, repeated, "{direction:?} k={top_k}: repeat");
            assert_eq!(
                scores(&repeated),
                scores(&response),
                "{direction:?} k={top_k}: repeat score bits"
            );

            // Continue the original cursor: literal next page, no gaps/duplicates.
            let mut continuation = request(
                query.clone(),
                top_k,
                doc_id_sort(direction),
                scoring_projection(),
            );
            continuation.after = Some(actual_cursor.clone());
            let second = searcher
                .search(&continuation, &Budgets::new(), &NeverCancel)
                .expect("continuation");
            let mut next_indices: Vec<usize> = (0..40).collect();
            if direction == SortDirection::Desc {
                next_indices.reverse();
            }
            next_indices.drain(..top_k);
            next_indices.truncate(top_k);
            let expected_next: Vec<String> =
                next_indices.iter().map(|i| scoring_doc_key(*i)).collect();
            assert_eq!(
                keys(&second),
                expected_next,
                "{direction:?} k={top_k}: page 2"
            );
            for (rank, hit) in second.hits.iter().enumerate() {
                let index = next_indices[rank];
                assert_eq!(
                    hit.score.expect("score").to_bits(),
                    scoring_oracle(scoring_tf(index), scoring_dl(index), 40, 40, total_length)
                        .to_bits(),
                    "{direction:?} k={top_k} page2 rank={rank}: score bits"
                );
            }
            let first_keys: std::collections::BTreeSet<String> =
                keys(&response).into_iter().collect();
            let second_keys: std::collections::BTreeSet<String> =
                keys(&second).into_iter().collect();
            assert!(
                first_keys.is_disjoint(&second_keys),
                "no duplicates across pages"
            );
            combinations += 1;
            eprintln!(
                "C3 I01 {direction:?} k={top_k}: total=40 page1={:?} page2={:?}",
                keys(&response),
                keys(&second)
            );
        }
    }
    assert_eq!(combinations, 6, "six score/cursor combinations");
    eprintln!("C3 I01 combinations={combinations}");
}

/// Collect every page of one request, returning the concatenated keys.
fn collect_pages(
    searcher: &UnifiedSearcher<'_>,
    base: &UnifiedRequest,
    expected_indices: &[usize],
    stats: (u64, u64, u64), // df, n, total field length
    label: &str,
) -> Vec<String> {
    // Every returned hit is verified against the immutable input-derived identity,
    // full projection and scalar score oracle for its own snapshot. The returned
    // length equals the verified-hit count because each key is appended only after
    // every per-hit assertion.
    let (df, n, total_length) = stats;
    assert_eq!(
        expected_indices.len() as u64,
        df,
        "{label}: expected index count equals df"
    );
    let expected_keys: Vec<String> = expected_indices
        .iter()
        .copied()
        .map(scoring_doc_key)
        .collect();
    let mut collected: Vec<String> = Vec::new();
    let mut cursor = None;
    let mut pages = 0usize;
    let mut checked_hits = 0usize;
    loop {
        assert!(pages < 20, "{label}: at most twenty page queries");
        let mut page = base.clone();
        page.after = cursor;
        let response = searcher
            .search(&page, &Budgets::new(), &NeverCancel)
            .unwrap_or_else(|error| panic!("{label}: page {} failed: {error:?}", pages + 1));
        assert_eq!(
            response.total_hits, df,
            "{label}: every page keeps the exact total"
        );
        let offset = collected.len();
        assert!(
            offset <= expected_indices.len(),
            "{label}: offset inside the expected sequence"
        );
        let remaining = expected_indices.len() - offset;
        assert!(remaining > 0, "{label}: no query after the final page");
        let expected_len = remaining.min(3);
        assert_eq!(
            response.hits.len(),
            expected_len,
            "{label}: page {} hit count",
            pages + 1
        );
        for (rank, hit) in response.hits.iter().enumerate() {
            let index = expected_indices[offset + rank];
            assert_eq!(
                hit.key.as_str(),
                scoring_doc_key(index),
                "{label}: page {} rank {rank} input identity",
                pages + 1
            );
            assert_eq!(
                hit.fields,
                vec![
                    (
                        "doc_id".to_owned(),
                        FieldValues::Single(FieldValue::Keyword(scoring_doc_key(index)))
                    ),
                    (
                        "body".to_owned(),
                        FieldValues::Single(FieldValue::Text(scoring_body(index)))
                    ),
                ],
                "{label}: page {} rank {rank} complete projection",
                pages + 1
            );
            let score = hit
                .score
                .unwrap_or_else(|| panic!("{label}: page {} rank {rank} unscored", pages + 1));
            assert!(
                score.is_finite() && score >= 0.0,
                "{label}: page {} rank {rank} finite nonnegative score",
                pages + 1
            );
            assert_eq!(
                score.to_bits(),
                scoring_oracle(scoring_tf(index), scoring_dl(index), df, n, total_length).to_bits(),
                "{label}: page {} rank {rank} input-derived scalar bits",
                pages + 1
            );
            checked_hits += 1;
        }
        collected.extend(response.hits.iter().map(|hit| hit.key.as_str().to_owned()));
        pages += 1;
        assert!(pages <= 20, "{label}: page bound");
        let more = collected.len() < expected_indices.len();
        match response.next_cursor {
            Some(next) => {
                assert!(more, "{label}: unexpected cursor after the last page");
                cursor = Some(next);
            }
            None => {
                assert!(!more, "{label}: missing cursor before the last page");
                break;
            }
        }
    }
    assert_eq!(collected, expected_keys, "{label}: literal sequence");
    assert_eq!(
        collected.len(),
        collected
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len(),
        "{label}: no duplicate keys"
    );
    assert_eq!(checked_hits as u64, df, "{label}: checked hits equals df");
    let expected_pages = match df {
        40 => 14usize,
        39 => 13,
        other => panic!("{label}: unexpected df {other}"),
    };
    assert_eq!(pages, expected_pages, "{label}: page count");
    eprintln!(
        "C3 I02 phase={label} df={df} n={n} total_length={total_length} pages={pages} checked_hits={checked_hits}"
    );
    collected
}

#[test]
fn c3_i02_real_pit_update_merge_and_paging() {
    use quervant_core::contract::document::MutationRequest;
    use quervant_core::contract::error::{InvalidQueryReason, QueryError};

    let (temp, schema, mut index) = reopen_scoring_corpus("c3-i02", 40, 6);
    let registry = AnalyzerRegistry::builtin();
    let old = index.snapshot();
    let old_searcher = UnifiedSearcher::new(&old, &schema, &registry, SearchLimits::default());
    let page = request(
        text_term("body", "alpha"),
        3,
        doc_id_sort(SortDirection::Asc),
        scoring_projection(),
    );

    // Immutable input-derived statistics for the pinned old view.
    let old_total_length: u64 = (0..40).map(scoring_dl).sum();
    assert_eq!(old_total_length, 180, "input-derived old total length");
    let old_indices: Vec<usize> = (0..40).collect();
    let old_stats = (40u64, 40u64, old_total_length);

    let old_response = old_searcher
        .search(&page, &Budgets::new(), &NeverCancel)
        .expect("old view");
    assert_eq!(old_response.total_hits, 40);
    let old_cursor = old_response.next_cursor.clone().expect("old cursor");

    // I02-OLD-BEFORE: every page of the pinned pre-mutation view.
    let mut checked_hits = 0usize;
    let old_sequence = collect_pages(
        &old_searcher,
        &page,
        &old_indices,
        old_stats,
        "I02-OLD-BEFORE",
    );
    checked_hits += old_sequence.len();
    // First-page direct scalar checks from the input sequence.
    for (rank, hit) in old_response.hits.iter().enumerate() {
        let expect = old_indices[rank];
        assert_eq!(hit.key.as_str(), scoring_doc_key(expect));
        assert_eq!(
            hit.score.expect("score").to_bits(),
            scoring_oracle(
                scoring_tf(expect),
                scoring_dl(expect),
                old_stats.0,
                old_stats.1,
                old_stats.2
            )
            .to_bits(),
            "old first page rank {rank} scalar bits"
        );
    }
    // Old-view wrapper Legacy parity (different AST fingerprint, same snapshot).
    let old_legacy = old_searcher
        .search(
            &request(
                legacy_text_query("body", "alpha"),
                3,
                doc_id_sort(SortDirection::Asc),
                scoring_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("old legacy wrapper");
    assert_response_except_cursor_fingerprint(&old_response, &old_legacy, "I02 old wrapper");

    // Delete one match, remove alpha from another, add one new match.
    let new_snapshot = {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new("s0002").expect("key"),
            ))
            .expect("delete");
        let mut updated = scoring_document(6);
        updated
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text("gamma".to_owned())),
            )
            .expect("body");
        writer
            .apply(MutationRequest::upsert(updated))
            .expect("upsert");
        writer.insert(scoring_document(40)).expect("insert");
        writer.commit().expect("commit");
        writer.refresh().expect("refresh")
    };
    let new_searcher =
        UnifiedSearcher::new(&new_snapshot, &schema, &registry, SearchLimits::default());
    let new_response = new_searcher
        .search(&page, &Budgets::new(), &NeverCancel)
        .expect("new view");
    assert_eq!(new_response.total_hits, 39, "39 live alpha matches");

    // Input-derived new statistics: delete s0002 (dl 5), rewrite s0006 (dl 4 -> 1),
    // insert s0040 (dl 1). The updated document is not an alpha match but still
    // contributes one length unit.
    let new_total_length: u64 =
        old_total_length - scoring_dl(2) - scoring_dl(6) + 1 + scoring_dl(40);
    assert_eq!(new_total_length, 173, "input-derived new total length");
    assert_eq!(scoring_dl(2), 5);
    assert_eq!(scoring_dl(6), 4);
    assert_eq!(scoring_dl(40), 1);
    let new_indices: Vec<usize> = (0..=40)
        .filter(|index| *index != 2 && *index != 6)
        .collect();
    assert_eq!(new_indices.len(), 39);
    let new_stats = (39u64, 40u64, new_total_length);

    // I02-NEW: every page of the post-mutation view.
    let new_sequence = collect_pages(&new_searcher, &page, &new_indices, new_stats, "I02-NEW");
    checked_hits += new_sequence.len();
    for (rank, hit) in new_response.hits.iter().enumerate() {
        let expect = new_indices[rank];
        assert_eq!(hit.key.as_str(), scoring_doc_key(expect));
        assert_eq!(
            hit.score.expect("score").to_bits(),
            scoring_oracle(
                scoring_tf(expect),
                scoring_dl(expect),
                new_stats.0,
                new_stats.1,
                new_stats.2
            )
            .to_bits(),
            "new first page rank {rank} scalar bits"
        );
    }
    let new_legacy = new_searcher
        .search(
            &request(
                legacy_text_query("body", "alpha"),
                3,
                doc_id_sort(SortDirection::Asc),
                scoring_projection(),
            ),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("new legacy wrapper");
    assert_response_except_cursor_fingerprint(&new_response, &new_legacy, "I02 new wrapper");

    // The pinned old snapshot is unchanged by the newer publication, including
    // every page of its full sequence.
    let pinned = old_searcher
        .search(&page, &Budgets::new(), &NeverCancel)
        .expect("pinned old view");
    assert_eq!(pinned, old_response, "pinned old response is unchanged");
    // I02-OLD-AFTER-MUTATION: the pinned view is still complete after publication.
    let old_after_mutation = collect_pages(
        &old_searcher,
        &page,
        &old_indices,
        old_stats,
        "I02-OLD-AFTER-MUTATION",
    );
    checked_hits += old_after_mutation.len();
    assert_eq!(
        old_after_mutation, old_sequence,
        "pinned sequence unchanged"
    );

    // An old cursor must never be accepted on the new snapshot.
    let mut stale = page.clone();
    stale.after = Some(old_cursor);
    let error = new_searcher
        .search(&stale, &Budgets::new(), &NeverCancel)
        .expect_err("stale cursor");
    assert!(
        matches!(
            error,
            SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch
            ))
        ),
        "{error:?}"
    );

    // Compact and reopen: the old pinned generation and the new logical results
    // must both survive unchanged.
    {
        let mut writer = index.writer().expect("writer");
        writer.compact().expect("compact");
        writer.commit().expect("commit compact");
    }
    index = Index::open_with_limits(
        Arc::new(FsDirectory::open(temp.path()).expect("fs")),
        schema.clone(),
        AnalyzerRegistry::builtin(),
        large_index_limits(),
    )
    .expect("reopen after compaction");
    let reopened = index.snapshot();
    let reopened_registry = AnalyzerRegistry::builtin();
    let reopened_searcher = UnifiedSearcher::new(
        &reopened,
        &schema,
        &reopened_registry,
        SearchLimits::default(),
    );
    let merged = reopened_searcher
        .search(&page, &Budgets::new(), &NeverCancel)
        .expect("merged view");
    assert_eq!(merged.total_hits, 39);
    assert_eq!(keys(&merged), keys(&new_response));
    assert_eq!(
        scores(&merged),
        scores(&new_response),
        "post-merge score bits"
    );
    // I02-COMPACTED: every page of the freshly reopened post-compaction view.
    let compacted_sequence = collect_pages(
        &reopened_searcher,
        &page,
        &new_indices,
        new_stats,
        "I02-COMPACTED",
    );
    checked_hits += compacted_sequence.len();
    assert_eq!(
        compacted_sequence, new_sequence,
        "post-compaction logical sequence"
    );

    // The pinned old snapshot still sees its own generation exactly, across every
    // page of the range.
    let pinned_after = old_searcher
        .search(&page, &Budgets::new(), &NeverCancel)
        .expect("pinned after compaction");
    assert_eq!(
        pinned_after, old_response,
        "pinned old response after compaction"
    );
    // I02-OLD-AFTER-COMPACTION.
    let old_after_compaction = collect_pages(
        &old_searcher,
        &page,
        &old_indices,
        old_stats,
        "I02-OLD-AFTER-COMPACTION",
    );
    checked_hits += old_after_compaction.len();
    assert_eq!(old_after_compaction, old_sequence);

    assert_eq!(checked_hits, 198, "five phases x per-hit oracles");
    eprintln!(
        "C3 I02 old=40 new=39 new-total-length=173 merged-keys={:?}",
        keys(&merged)
    );
    eprintln!("C3 F1 I02 phases=5 checked-hits=198 old-pages=14 new-pages=13");
}

/// Assert two responses are equal except for the cursor query fingerprint.
fn assert_response_except_cursor_fingerprint(
    left: &UnifiedResponse,
    right: &UnifiedResponse,
    label: &str,
) {
    assert_eq!(left.hits.len(), right.hits.len(), "{label}: hit count");
    assert_eq!(left.total_hits, right.total_hits, "{label}: total hits");
    assert_eq!(left.generation, right.generation, "{label}: generation");
    assert_eq!(
        left.view_ordinal, right.view_ordinal,
        "{label}: view ordinal"
    );
    assert_eq!(left.aggregation, right.aggregation, "{label}: aggregation");
    assert_eq!(scores(left), scores(right), "{label}: score bits");
    for (a, b) in left.hits.iter().zip(right.hits.iter()) {
        assert_eq!(a.key, b.key, "{label}: key");
        assert_eq!(a.fields, b.fields, "{label}: projected fields");
    }
    match (&left.next_cursor, &right.next_cursor) {
        (Some(a), Some(b)) => {
            assert_eq!(
                a.snapshot_binding(),
                b.snapshot_binding(),
                "{label}: cursor binding"
            );
            assert_eq!(a.last_key(), b.last_key(), "{label}: cursor key");
            assert_eq!(
                a.last_sort_values(),
                b.last_sort_values(),
                "{label}: cursor sort values"
            );
            assert_eq!(a.last_score(), b.last_score(), "{label}: cursor score");
        }
        (None, None) => {}
        (a, b) => panic!("{label}: cursor presence differs: {a:?} vs {b:?}"),
    }
}

#[test]
fn c3_i03_real_resource_and_cancellation_edges() {
    let corpus = Corpus::single("c3-i03", 48);
    let page = request(
        term_query("key", "common"),
        3,
        doc_id_sort(SortDirection::Asc),
        full_projection(),
    );
    let expected_keys = expected_lane_keys("common", 48, 3, true);
    assert_eq!(
        expected_keys,
        vec![
            "d00000002".to_owned(),
            "d00000004".to_owned(),
            "d00000006".to_owned()
        ],
        "literal ascending common lane"
    );

    let exact = SearchLimits::default()
        .with_max_segment_candidate_entries(69)
        .expect("entries")
        .with_max_total_candidate_bytes(2944)
        .expect("bytes");
    let admitted = search_with(&corpus, &page, exact, &NeverCancel).expect("exact peak");
    assert_eq!(admitted.total_hits, 23);
    assert_eq!(keys(&admitted), expected_keys);
    assert!(admitted.next_cursor.is_some());
    // The same public failure-path response matches the default-limit Legacy route
    // apart from the cursor query fingerprint.
    let legacy = search(
        &corpus,
        &request(
            legacy_query("key", "common"),
            3,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("legacy default limits");
    assert_eq!(legacy.total_hits, 23);
    assert_response_except_cursor_fingerprint(&admitted, &legacy, "I03 admitted vs legacy");

    // One-under entry budget, then an independent same-snapshot retry.
    let under_entries = SearchLimits::default()
        .with_max_segment_candidate_entries(68)
        .expect("entries")
        .with_max_total_candidate_bytes(2944)
        .expect("bytes");
    let rejected =
        search_with(&corpus, &page, under_entries, &NeverCancel).expect_err("one-under entries");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 68,
                requested: 69
            }
        ),
        "{rejected:?}"
    );
    let recovered = search_with(&corpus, &page, exact, &NeverCancel).expect("retry after entries");
    assert_eq!(
        recovered, admitted,
        "post-entries retry is the exact same-query response"
    );

    // One-under byte budget.
    let under_bytes = SearchLimits::default()
        .with_max_segment_candidate_entries(69)
        .expect("entries")
        .with_max_total_candidate_bytes(2943)
        .expect("bytes");
    let rejected =
        search_with(&corpus, &page, under_bytes, &NeverCancel).expect_err("one-under bytes");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 2943,
                requested: 2944
            }
        ),
        "{rejected:?}"
    );
    let recovered = search_with(&corpus, &page, exact, &NeverCancel).expect("retry after bytes");
    assert_eq!(recovered, admitted, "post-bytes retry");

    // Scanned-occurrence boundary on the two-segment corpus.
    let split = Corpus::build("c3-i03-split", &[(0..24).collect(), (24..48).collect()]);
    let scanned_23 = SearchLimits::default()
        .with_max_scanned_posting_occurrences(23)
        .expect("scanned");
    let split_admitted =
        search_with(&split, &page, scanned_23, &NeverCancel).expect("exact scanned limit");
    assert_eq!(split_admitted.total_hits, 23);
    assert_eq!(keys(&split_admitted), expected_keys);
    assert!(split_admitted.next_cursor.is_some());
    let split_legacy = search(
        &split,
        &request(
            legacy_query("key", "common"),
            3,
            doc_id_sort(SortDirection::Asc),
            full_projection(),
        ),
    )
    .expect("legacy on the split snapshot");
    assert_response_except_cursor_fingerprint(
        &split_admitted,
        &split_legacy,
        "I03 split vs legacy",
    );
    let scanned_22 = SearchLimits::default()
        .with_max_scanned_posting_occurrences(22)
        .expect("scanned");
    let rejected =
        search_with(&split, &page, scanned_22, &NeverCancel).expect_err("one-under scanned");
    assert!(
        matches!(
            rejected,
            SearchError::ResourceLimit {
                limit: 22,
                requested: 23
            }
        ),
        "{rejected:?}"
    );
    let recovered =
        search_with(&split, &page, scanned_23, &NeverCancel).expect("retry after scanned");
    assert_eq!(recovered, split_admitted, "post-scanned retry");

    // Cancellation returns the typed error and leaves the index usable.
    let flag = CancellationFlag::new();
    flag.cancel();
    let cancelled =
        search_with(&corpus, &page, SearchLimits::default(), &flag).expect_err("cancelled");
    assert!(matches!(cancelled, SearchError::Cancelled), "{cancelled:?}");
    let retried = search(&corpus, &page).expect("retry after cancellation");
    assert_eq!(retried, admitted, "post-cancellation retry");
    eprintln!(
        "C3 I03 caps=69/2944 failure={{68,69}}/{{2943,2944}} scanned=23 failure={{22,23}} total=23"
    );
}

// ---------------------------------------------------------------------------
// PERF-07-A — integration acceptance on real committed local indexes.
// ---------------------------------------------------------------------------

/// Assert one scored first/continuation page against literal input-derived facts.
fn p07a_i01_assert_page(
    response: &UnifiedResponse,
    expected: &[usize],
    stats: (u64, u64, u64),
    label: &str,
) {
    let (df, n, total_length) = stats;
    assert_eq!(response.total_hits, df, "{label}: exact total");
    assert_eq!(response.hits.len(), expected.len(), "{label}: page length");
    assert!(response.aggregation.is_none(), "{label}: no aggregation");
    for (rank, index) in expected.iter().enumerate() {
        let hit = &response.hits[rank];
        assert_eq!(
            hit.key.as_str(),
            scoring_doc_key(*index),
            "{label}: rank {rank} literal key"
        );
        assert_eq!(
            hit.fields,
            vec![
                (
                    "doc_id".to_owned(),
                    FieldValues::Single(FieldValue::Keyword(scoring_doc_key(*index)))
                ),
                (
                    "body".to_owned(),
                    FieldValues::Single(FieldValue::Text(scoring_body(*index)))
                ),
            ],
            "{label}: rank {rank} complete projection"
        );
        let score = hit
            .score
            .unwrap_or_else(|| panic!("{label}: rank {rank} must be scored"));
        assert_eq!(
            score.to_bits(),
            scoring_oracle(scoring_tf(*index), scoring_dl(*index), df, n, total_length).to_bits(),
            "{label}: rank {rank} literal score bits"
        );
    }
    assert!(response.next_cursor.is_some(), "{label}: next cursor");
}

#[test]
fn perf07a_i01_real_fs_multi_hit_scores_and_projection() {
    let (_temp, schema, index) = reopen_scoring_corpus("perf07a-i01", 1100, 1000);
    let mut counts: Vec<u64> = index
        .snapshot()
        .segments()
        .iter()
        .map(|segment| segment.doc_count())
        .collect();
    counts.sort_unstable();
    assert_eq!(counts, vec![100, 1000], "two real committed segments");

    let total: u64 = (0..1100)
        .map(|index| 1 + (index % 4) as u64 + (index % 5) as u64)
        .sum();
    assert_eq!(total, 4950, "input-derived total field length");
    let stats = (1100u64, 1100u64, 4950u64);

    let snapshot = index.snapshot();
    let registry = AnalyzerRegistry::builtin();
    let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());

    let cases = [
        (1usize, SortDirection::Asc),
        (10, SortDirection::Asc),
        (100, SortDirection::Asc),
        (1, SortDirection::Desc),
        (10, SortDirection::Desc),
        (100, SortDirection::Desc),
    ];
    let mut executions = 0usize;
    for (k, direction) in cases {
        let base = request(
            text_term("body", "alpha"),
            k,
            doc_id_sort(direction),
            scoring_projection(),
        );
        let expected: Vec<usize> = match direction {
            SortDirection::Asc => (0..k).collect(),
            SortDirection::Desc => (1100 - k..1100).rev().collect(),
        };
        let label = format!("I01 {direction:?} K={k}");
        let first = searcher
            .search(&base, &Budgets::new(), &NeverCancel)
            .expect("first page");
        p07a_i01_assert_page(&first, &expected, stats, &format!("{label} first"));
        let repeat = searcher
            .search(&base, &Budgets::new(), &NeverCancel)
            .expect("repeat page");
        assert_eq!(repeat, first, "{label}: repeated response is identical");
        p07a_i01_assert_page(&repeat, &expected, stats, &format!("{label} repeat"));
        executions += 2;

        if k >= 10 {
            let cursor = first.next_cursor.clone().expect("continuation cursor");
            let mut page = base.clone();
            page.after = Some(cursor);
            let continuation = searcher
                .search(&page, &Budgets::new(), &NeverCancel)
                .expect("continuation");
            let expected_next: Vec<usize> = match direction {
                SortDirection::Asc => (k..2 * k).collect(),
                SortDirection::Desc => (1100 - 2 * k..1100 - k).rev().collect(),
            };
            p07a_i01_assert_page(
                &continuation,
                &expected_next,
                stats,
                &format!("{label} continuation"),
            );
            executions += 1;
        }
    }
    assert_eq!(executions, 16, "twelve first pages plus four continuations");
    eprintln!("PERF07-A I01 page-executions={executions} total={total}");
}

const P07A_I02_UPDATED_BODY: &str = "alpha alpha alpha alpha gamma gamma";

fn p07a_i02_body(index: usize, updated: bool) -> String {
    if updated && index == 6 {
        P07A_I02_UPDATED_BODY.to_owned()
    } else {
        scoring_body(index)
    }
}

fn p07a_i02_tf(index: usize, updated: bool) -> u64 {
    if updated && index == 6 {
        4
    } else {
        scoring_tf(index)
    }
}

fn p07a_i02_dl(index: usize, updated: bool) -> u64 {
    if updated && index == 6 {
        6
    } else {
        scoring_dl(index)
    }
}

/// Traverse the four fixed pages of one logical phase and verify every hit.
fn p07a_i02_pages(
    searcher: &UnifiedSearcher<'_>,
    snapshot: &ReaderSnapshot,
    base: &UnifiedRequest,
    updated: bool,
) -> Vec<UnifiedResponse> {
    let expected: Vec<usize> = if updated {
        (0..=40).filter(|index| *index != 2).collect()
    } else {
        (0..40).collect()
    };
    assert_eq!(expected.len(), 40);
    let (df, n, total_length) = if updated {
        (40u64, 40u64, 178u64)
    } else {
        (40u64, 40u64, 180u64)
    };
    let mut responses: Vec<UnifiedResponse> = Vec::new();
    let mut cursor = None;
    let mut seen = std::collections::BTreeSet::new();
    let mut checked = 0usize;
    for page_index in 0..4usize {
        let mut page = base.clone();
        page.after = cursor;
        let response = searcher
            .search(&page, &Budgets::new(), &NeverCancel)
            .unwrap_or_else(|error| panic!("page {page_index} failed: {error:?}"));
        assert_eq!(response.total_hits, df, "page {page_index}: total");
        assert_eq!(response.hits.len(), 10, "page {page_index}: length");
        assert!(response.aggregation.is_none());
        assert_eq!(response.generation, snapshot.generation());
        assert_eq!(response.view_ordinal, snapshot.view_ordinal());
        for (rank, hit) in response.hits.iter().enumerate() {
            let index = expected[10 * page_index + rank];
            assert_eq!(
                hit.key.as_str(),
                scoring_doc_key(index),
                "page {page_index} rank {rank}: literal key"
            );
            assert_eq!(
                hit.fields,
                vec![
                    (
                        "doc_id".to_owned(),
                        FieldValues::Single(FieldValue::Keyword(scoring_doc_key(index)))
                    ),
                    (
                        "body".to_owned(),
                        FieldValues::Single(FieldValue::Text(p07a_i02_body(index, updated)))
                    ),
                ],
                "page {page_index} rank {rank}: complete projection"
            );
            let score = hit
                .score
                .unwrap_or_else(|| panic!("page {page_index} rank {rank}: scored"));
            assert_eq!(
                score.to_bits(),
                scoring_oracle(
                    p07a_i02_tf(index, updated),
                    p07a_i02_dl(index, updated),
                    df,
                    n,
                    total_length
                )
                .to_bits(),
                "page {page_index} rank {rank}: literal score bits"
            );
            assert!(
                seen.insert(hit.key.as_str().to_owned()),
                "page {page_index} rank {rank}: duplicate key"
            );
            checked += 1;
        }
        let more = page_index < 3;
        match &response.next_cursor {
            Some(_) => assert!(more, "page {page_index}: unexpected trailing cursor"),
            None => assert!(!more, "page {page_index}: missing continuation cursor"),
        }
        cursor = response.next_cursor.clone();
        responses.push(response);
    }
    assert_eq!(checked, 40, "forty per-hit checks per phase");
    responses
}

fn p07a_i02_assert_logical_parity(left: &[UnifiedResponse], right: &[UnifiedResponse]) {
    assert_eq!(left.len(), right.len());
    for (page, (a, b)) in left.iter().zip(right).enumerate() {
        assert_eq!(a.total_hits, b.total_hits, "page {page}: total");
        assert_eq!(a.hits.len(), b.hits.len(), "page {page}: length");
        assert_eq!(a.aggregation, b.aggregation, "page {page}: aggregation");
        assert_eq!(
            a.next_cursor.is_some(),
            b.next_cursor.is_some(),
            "page {page}: cursor presence"
        );
        for (rank, (x, y)) in a.hits.iter().zip(&b.hits).enumerate() {
            assert_eq!(x.key, y.key, "page {page} rank {rank}: key");
            assert_eq!(x.fields, y.fields, "page {page} rank {rank}: fields");
            assert_eq!(
                x.score.map(f64::to_bits),
                y.score.map(f64::to_bits),
                "page {page} rank {rank}: score bits"
            );
        }
    }
}

#[test]
fn perf07a_i02_real_fs_pit_upsert_delete_compact_projection() {
    use quervant_core::contract::document::MutationRequest;
    use quervant_core::contract::error::{InvalidQueryReason, QueryError};

    let (temp, schema, mut index) = reopen_scoring_corpus("perf07a-i02", 40, 6);
    let registry = AnalyzerRegistry::builtin();
    let old = index.snapshot();
    let old_searcher = UnifiedSearcher::new(&old, &schema, &registry, SearchLimits::default());
    let base = request(
        text_term("body", "alpha"),
        10,
        doc_id_sort(SortDirection::Asc),
        scoring_projection(),
    );
    let old_total_length: u64 = (0..40).map(scoring_dl).sum();
    assert_eq!(old_total_length, 180, "input-derived old total length");

    // Phase 1: the pinned pre-mutation view.
    let old_pages = p07a_i02_pages(&old_searcher, &old, &base, false);
    let old_cursor = old_pages[0].next_cursor.clone().expect("old cursor");
    let old_s0006 = old_pages[0]
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == scoring_doc_key(6))
        .expect("old s0006");
    assert_eq!(
        old_s0006.fields[1].1,
        FieldValues::Single(FieldValue::Text(scoring_body(6))),
        "old body"
    );

    // Phase 2: real mutation keeps the key a match but changes body and score.
    let new_snapshot = {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new("s0002").expect("key"),
            ))
            .expect("delete");
        let mut updated = scoring_document(6);
        updated
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(P07A_I02_UPDATED_BODY.to_owned())),
            )
            .expect("body");
        writer
            .apply(MutationRequest::upsert(updated))
            .expect("upsert");
        writer.insert(scoring_document(40)).expect("insert");
        writer.commit().expect("commit");
        writer.refresh().expect("refresh")
    };
    let new_searcher =
        UnifiedSearcher::new(&new_snapshot, &schema, &registry, SearchLimits::default());
    let new_total_length: u64 =
        old_total_length - scoring_dl(2) - scoring_dl(6) + 6 + scoring_dl(40);
    assert_eq!(new_total_length, 178, "input-derived new total length");

    let new_pages = p07a_i02_pages(&new_searcher, &new_snapshot, &base, true);
    let new_s0006 = new_pages[0]
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == scoring_doc_key(6))
        .expect("new s0006");
    assert_eq!(
        new_s0006.fields[1].1,
        FieldValues::Single(FieldValue::Text(P07A_I02_UPDATED_BODY.to_owned())),
        "updated body"
    );
    assert_ne!(
        new_s0006.score.map(f64::to_bits),
        old_s0006.score.map(f64::to_bits),
        "updated score bits differ"
    );

    // An old cursor is rejected on the new snapshot.
    let mut stale = base.clone();
    stale.after = Some(old_cursor);
    let error = new_searcher
        .search(&stale, &Budgets::new(), &NeverCancel)
        .expect_err("stale cursor");
    assert!(
        matches!(
            error,
            SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch
            ))
        ),
        "{error:?}"
    );

    // Phase 3: the original pinned view is unchanged.
    let pinned = p07a_i02_pages(&old_searcher, &old, &base, false);
    assert_eq!(pinned, old_pages, "pinned responses are exactly unchanged");
    for (page, (a, b)) in pinned.iter().zip(&old_pages).enumerate() {
        for (rank, (x, y)) in a.hits.iter().zip(&b.hits).enumerate() {
            assert_eq!(
                x.score.map(f64::to_bits),
                y.score.map(f64::to_bits),
                "pinned page {page} rank {rank}: explicit score bits"
            );
        }
    }

    // Phase 4: compact and reopen from the real filesystem.
    {
        let mut writer = index.writer().expect("writer");
        writer.compact().expect("compact");
        writer.commit().expect("commit compact");
    }
    index = Index::open_with_limits(
        Arc::new(FsDirectory::open(temp.path()).expect("fs")),
        schema.clone(),
        AnalyzerRegistry::builtin(),
        large_index_limits(),
    )
    .expect("reopen after compaction");
    let reopened = index.snapshot();
    assert_eq!(reopened.segment_count(), 1, "compaction merges segments");
    let reopened_registry = AnalyzerRegistry::builtin();
    let reopened_searcher = UnifiedSearcher::new(
        &reopened,
        &schema,
        &reopened_registry,
        SearchLimits::default(),
    );
    let compacted_pages = p07a_i02_pages(&reopened_searcher, &reopened, &base, true);
    p07a_i02_assert_logical_parity(&compacted_pages, &new_pages);

    // Phase 5: the pinned pre-mutation view survives compaction exactly.
    let pinned_after = p07a_i02_pages(&old_searcher, &old, &base, false);
    assert_eq!(
        pinned_after, old_pages,
        "pinned pre-mutation responses survive compaction"
    );

    let page_calls = old_pages.len()
        + new_pages.len()
        + pinned.len()
        + compacted_pages.len()
        + pinned_after.len();
    assert_eq!(page_calls, 20, "five phases x four pages");
    assert_eq!(page_calls * 10, 200, "per-hit checks");
    eprintln!(
        "PERF07-A I02 phases=5 page-calls={page_calls} per-hit-checks={}",
        page_calls * 10
    );
}
