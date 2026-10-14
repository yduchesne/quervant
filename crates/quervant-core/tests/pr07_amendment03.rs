//! PR 7 Amendment 03 — transactional ledger and bounded phrase scratch.
//!
//! Public-path tests use real `Index`/`IndexWriter`/`ReaderSnapshot`/`LexicalSearcher`
//! over `MemoryDirectory` and `FsDirectory`. Transactional budget primitives are
//! unit tested in `search/execute.rs`; bounded phrase scratch is additionally unit
//! tested in `search/phrase.rs`.

mod common;

use std::collections::BTreeMap;
use std::sync::Arc;

use common::TempDir;
use quervant_core::analysis::{AnalyzerRegistry, Cancellation, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
        ],
        None,
    )
    .expect("schema")
}

fn title_doc(key: &str, title: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .unwrap();
    document
}

fn body_doc(key: &str, values: Vec<&str>) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "body",
            FieldValues::Multi(
                values
                    .into_iter()
                    .map(|value| FieldValue::Text(value.to_owned()))
                    .collect(),
            ),
        )
        .unwrap();
    document
}

fn build_on(directory: Arc<dyn Directory>, batches: Vec<Vec<Document>>) -> Arc<ReaderSnapshot> {
    let index = Index::create(directory.clone(), schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut writer = index.writer().unwrap();
    for batch in batches {
        for document in batch {
            writer.insert(document).unwrap();
        }
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())
        .unwrap()
        .snapshot()
}

fn build(batches: Vec<Vec<Document>>) -> Arc<ReaderSnapshot> {
    build_on(Arc::new(MemoryDirectory::new()), batches)
}

fn run_with_limits(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
    cancel: &dyn Cancellation,
) -> Result<SearchResponse, SearchError> {
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    LexicalSearcher::new(snapshot, &schema, &registry, limits).search(
        query,
        TopK::new(1_000).unwrap(),
        &Budgets::new(),
        cancel,
    )
}

fn run(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
) -> Result<SearchResponse, SearchError> {
    run_with_limits(snapshot, query, limits, &NeverCancel)
}

fn run_default(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    run(snapshot, query, SearchLimits::default()).expect("search")
}

fn keys(response: &SearchResponse) -> Vec<String> {
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

fn scores(response: &SearchResponse) -> BTreeMap<String, f64> {
    response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score))
        .collect()
}

fn phrase(field: &str, terms: &[&str]) -> Query {
    Query::Phrase {
        field: field.into(),
        terms: terms.iter().map(|term| (*term).to_owned()).collect(),
    }
}

fn term(field: &str, text: &str) -> Query {
    Query::Term {
        field: field.into(),
        value: FieldValue::Text(text.into()),
    }
}

fn limits_entries(entries: u64) -> SearchLimits {
    SearchLimits::default()
        .with_max_segment_candidate_entries(entries)
        .unwrap()
}

fn min_segment_entries(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 20;
    while low < high {
        let mid = low + (high - low) / 2;
        if run(snapshot, query, limits_entries(mid)).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

fn min_total_bytes(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 20;
    while low < high {
        let mid = low + (high - low) / 2;
        let limits = SearchLimits::default()
            .with_max_total_candidate_bytes(mid)
            .unwrap();
        if run(snapshot, query, limits).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

// ---------------------------------------------------------------------------
// P01/P02 — internal phrase scratch is charged and bounded
// ---------------------------------------------------------------------------

#[test]
fn p01_chain_reference_scratch_is_charged() {
    // Eight 'a' occurrences produce eight live chain references (plus the
    // simultaneous `advanced` buffer), which the pre-Amendment-03 executor did
    // not charge. The corrected minimum entry bound is therefore far above the
    // outer posting/match charges alone.
    let snapshot = build(vec![vec![title_doc("a", "a a a a a a a a b")]]);
    let query = phrase("title", &["a", "b"]);
    let min = min_segment_entries(&snapshot, &query);
    assert!(
        min >= 30,
        "internal chain references must be charged, min={min}"
    );
    assert!(run(&snapshot, &query, limits_entries(min)).is_ok());
    assert!(matches!(
        run(&snapshot, &query, limits_entries(min - 1)),
        Err(SearchError::ResourceLimit { .. })
    ));
}

#[test]
fn p02_intersection_replacement_is_charged_atomically() {
    let snapshot = build(vec![vec![
        title_doc("a", "x y z"),
        title_doc("b", "x y"),
        title_doc("c", "y z"),
    ]]);
    // Three distinct terms force two successive intersections; old and new
    // candidate vectors are simultaneously charged at the replacement peak.
    let query = phrase("title", &["x", "y", "z"]);
    let min = min_segment_entries(&snapshot, &query);
    assert!(run(&snapshot, &query, limits_entries(min)).is_ok());
    assert!(matches!(
        run(&snapshot, &query, limits_entries(min - 1)),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert_eq!(keys(&run_default(&snapshot, &query)), vec!["a"]);
}

// ---------------------------------------------------------------------------
// P03/P04/P11 — long repeated chains, siblings, degenerate phrases
// ---------------------------------------------------------------------------

#[test]
fn p03_long_repeated_chain_membership_unchanged() {
    let snapshot = build(vec![vec![
        title_doc("a", "a a a a b"),
        title_doc("b", "a b"),
        title_doc("c", "a a b"),
    ]]);
    let query = phrase("title", &["a", "a", "b"]);
    // Contiguous "a a b" subsequences: "a a a a b" (positions 2,3,4) and "a a b".
    assert_eq!(keys(&run_default(&snapshot, &query)), vec!["a", "c"]);
}

#[test]
fn p04_sibling_phrase_scratch_not_cumulative() {
    let snapshot = build(vec![vec![title_doc("a", "x y p q")]]);
    let single = phrase("title", &["x", "y"]);
    let siblings = Query::Or(vec![
        phrase("title", &["x", "y"]),
        phrase("title", &["p", "q"]),
    ]);
    let single_min = min_segment_entries(&snapshot, &single);
    let sibling_min = min_segment_entries(&snapshot, &siblings);
    assert!(
        sibling_min <= single_min + 4,
        "sibling scratch must be released: single={single_min} siblings={sibling_min}"
    );
}

#[test]
fn p11_degenerate_phrases_are_safe() {
    let snapshot = build(vec![vec![title_doc("a", "only")]]);
    assert_eq!(
        keys(&run_default(&snapshot, &phrase("title", &["only"]))),
        vec!["a"]
    );
    assert!(
        run_default(&snapshot, &phrase("title", &["absent"]))
            .hits
            .is_empty()
    );
    assert!(
        run_default(&snapshot, &phrase("title", &["only", "absent"]))
            .hits
            .is_empty()
    );
}

// ---------------------------------------------------------------------------
// P05 — combined global + segment + phrase scratch bound
// ---------------------------------------------------------------------------

#[test]
fn p05_global_plus_phrase_scratch_combined_bound() {
    // First segment contributes a retained global hit; the second performs phrase
    // verification with scratch, so the combined byte ceiling must cover both.
    let snapshot = build(vec![
        vec![title_doc("g", "zeta")],
        vec![title_doc("p", "a a a a b")],
    ]);
    let query = Query::Or(vec![term("title", "zeta"), phrase("title", &["a", "b"])]);
    let exact = min_total_bytes(&snapshot, &query);
    assert!(
        run(
            &snapshot,
            &query,
            SearchLimits::default()
                .with_max_total_candidate_bytes(exact)
                .unwrap()
        )
        .is_ok()
    );
    assert!(matches!(
        run(
            &snapshot,
            &query,
            SearchLimits::default()
                .with_max_total_candidate_bytes(exact - 1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert_eq!(keys(&run_default(&snapshot, &query)), vec!["g", "p"]);
}

// ---------------------------------------------------------------------------
// P06/P07 — error and cancellation cleanup
// ---------------------------------------------------------------------------

struct CancelAfter {
    remaining: std::cell::Cell<u32>,
}

impl CancelAfter {
    fn new(remaining: u32) -> Self {
        Self {
            remaining: std::cell::Cell::new(remaining),
        }
    }
}

impl Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let left = self.remaining.get();
        if left == 0 {
            true
        } else {
            self.remaining.set(left - 1);
            false
        }
    }
}

#[test]
fn p06_rejection_stages_clean_up_and_retry() {
    let snapshot = build(vec![vec![title_doc("a", "a a a a b b b b")]]);
    let query = phrase("title", &["a", "b"]);
    let exact = min_segment_entries(&snapshot, &query);
    for limit in 1..exact {
        assert!(
            matches!(
                run(&snapshot, &query, limits_entries(limit)),
                Err(SearchError::ResourceLimit { .. })
            ),
            "limit {limit}"
        );
    }
    // A fresh request with sufficient limits succeeds on the same snapshot.
    assert_eq!(keys(&run_default(&snapshot, &query)), vec!["a"]);
}

#[test]
fn p07_cancellation_during_phrase_work_cleans_up() {
    let snapshot = build(vec![vec![title_doc("a", "a a a a b b b b")]]);
    let query = phrase("title", &["a", "b"]);
    for budget in [0u32, 1, 2, 3, 4, 5, 8, 10] {
        assert!(
            matches!(
                run_with_limits(
                    &snapshot,
                    &query,
                    SearchLimits::default(),
                    &CancelAfter::new(budget)
                ),
                Err(SearchError::Cancelled)
            ),
            "budget {budget}"
        );
    }
    assert_eq!(keys(&run_default(&snapshot, &query)), vec!["a"]);
}

// ---------------------------------------------------------------------------
// P08 — multi-value/stopword/repeated/position semantics oracle
// ---------------------------------------------------------------------------

#[test]
fn p08_multivalue_and_position_semantics() {
    let snapshot = build(vec![vec![
        body_doc("a", vec!["quick brown", "fox"]),
        body_doc("b", vec!["quick brown fox"]),
        body_doc("c", vec!["quick fox"]),
        body_doc("d", vec!["brown quick fox"]),
    ]]);
    // A phrase never bridges values.
    assert_eq!(
        keys(&run_default(
            &snapshot,
            &phrase("body", &["quick", "brown", "fox"])
        )),
        vec!["b"]
    );
    // Within a value, adjacency and order matter.
    assert_eq!(
        keys(&run_default(
            &snapshot,
            &phrase("body", &["quick", "brown"])
        )),
        vec!["a", "b"]
    );
    assert_eq!(
        keys(&run_default(&snapshot, &phrase("body", &["quick", "fox"]))),
        vec!["c", "d"]
    );
}

// ---------------------------------------------------------------------------
// P09 — memory/filesystem parity
// ---------------------------------------------------------------------------

#[test]
fn p09_memory_and_fs_agree() {
    let batches = || {
        vec![
            vec![title_doc("a", "a a a a b")],
            vec![title_doc("b", "a a b"), title_doc("c", "a b b")],
        ]
    };
    let memory = build(batches());
    let query = phrase("title", &["a", "b"]);
    let memory_response = run_default(&memory, &query);

    let dir = TempDir::new("pr07-a3-p09");
    let fs_snapshot = {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(dir.path()).unwrap());
        build_on(directory, batches())
    };
    let fs_response = run_default(&fs_snapshot, &query);
    assert_eq!(keys(&memory_response), keys(&fs_response));
    assert_eq!(memory_response.total_hits, fs_response.total_hits);
    let memory_scores = scores(&memory_response);
    let fs_scores = scores(&fs_response);
    for (key, score) in &memory_scores {
        assert!((score - fs_scores[key]).abs() < 1e-12, "{key}");
    }
}

// ---------------------------------------------------------------------------
// P10/P12 — seeded phrase oracle (membership + BM25 scores)
// ---------------------------------------------------------------------------

struct Lcg(u64);
impl Lcg {
    fn new(seed: u64) -> Self {
        Self(seed)
    }
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }
    fn below(&mut self, bound: usize) -> usize {
        if bound == 0 {
            0
        } else {
            (self.next() as usize) % bound
        }
    }
}

fn bm25_ref(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> f64 {
    if tf == 0 || n == 0 || avgdl <= 0.0 {
        return 0.0;
    }
    let tf = tf as f64;
    let df = df as f64;
    let n = n as f64;
    let dl = dl as f64;
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    idf * (tf * 2.2) / (tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / avgdl))
}

#[test]
fn p10_seeded_phrase_oracle_membership_and_scores() {
    let vocab = ["a", "b", "c", "d"];
    for seed_offset in 0..200u64 {
        let seed = 0xA303u64 ^ seed_offset;
        let mut lcg = Lcg::new(seed);
        let doc_count = lcg.below(7) + 1;
        let mut documents = Vec::new();
        let mut token_lists: Vec<Vec<String>> = Vec::new();
        for index in 0..doc_count {
            let key = format!("p{index:02}");
            let token_count = lcg.below(6) + 1;
            let tokens: Vec<String> = (0..token_count)
                .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                .collect();
            token_lists.push(tokens.clone());
            documents.push(title_doc(&key, &tokens.join(" ")));
        }
        let phrase_len = lcg.below(3) + 1;
        let phrase_tokens: Vec<String> = (0..phrase_len)
            .map(|_| vocab[lcg.below(vocab.len())].to_owned())
            .collect();
        let snapshot = build(vec![documents]);
        let query = Query::Phrase {
            field: "title".into(),
            terms: phrase_tokens.clone(),
        };
        let response = run_default(&snapshot, &query);

        // Independent membership and score oracle from raw token positions.
        let n = token_lists.len() as u64;
        let avgdl = token_lists
            .iter()
            .map(|tokens| tokens.len() as f64)
            .sum::<f64>()
            / n as f64;
        let distinct: Vec<&String> = {
            let mut terms: Vec<&String> = phrase_tokens.iter().collect();
            terms.sort();
            terms.dedup();
            terms
        };
        let mut expected: BTreeMap<String, f64> = BTreeMap::new();
        for (index, tokens) in token_lists.iter().enumerate() {
            let matched = phrase_tokens.len() <= tokens.len()
                && (0..=tokens.len() - phrase_tokens.len())
                    .any(|start| tokens[start..start + phrase_tokens.len()] == phrase_tokens[..]);
            if !matched {
                continue;
            }
            let dl = tokens.len() as u64;
            let mut score = 0.0;
            for term in &distinct {
                let tf = tokens.iter().filter(|token| *token == *term).count() as u64;
                let df = token_lists
                    .iter()
                    .filter(|tokens| tokens.iter().any(|token| token == *term))
                    .count() as u64;
                score += bm25_ref(tf, df, n, dl, avgdl);
            }
            expected.insert(format!("p{index:02}"), score);
        }
        assert_eq!(
            keys(&response)
                .into_iter()
                .collect::<std::collections::BTreeSet<_>>(),
            expected.keys().cloned().collect(),
            "seed {seed} phrase {phrase_tokens:?}"
        );
        for (key, score) in scores(&response) {
            assert!(
                (score - expected[&key]).abs() < 1e-10,
                "seed {seed} key {key}: {score} vs {}",
                expected[&key]
            );
        }
    }
}

#[test]
fn p12_long_terms_in_output_are_handled() {
    let long = "z".repeat(2_000);
    let snapshot = build(vec![vec![title_doc("a", &format!("{long} tail"))]]);
    // A single long term as a phrase; output term_freqs holds the long string.
    let response = run_default(&snapshot, &phrase("title", &[long.as_str()]));
    assert_eq!(keys(&response), vec!["a"]);
}
