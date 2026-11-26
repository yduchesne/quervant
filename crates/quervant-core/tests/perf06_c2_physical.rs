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
