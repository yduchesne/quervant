//! PR 7 Amendment 02 — candidate reservation lifetimes and batch transfer.
//!
//! Public-path tests use real `Index`/`IndexWriter`/`ReaderSnapshot`/`LexicalSearcher`
//! over `MemoryDirectory` and `FsDirectory`. Private budget primitives are unit
//! tested inside `search/execute.rs`.

mod common;

use std::collections::BTreeSet;
use std::sync::Arc;

use common::TempDir;
use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

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
    run_with_limits(snapshot, query, limits, &CancellationFlag::new())
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

fn phrase(terms: &[&str]) -> Query {
    Query::Phrase {
        field: "title".into(),
        terms: terms.iter().map(|term| (*term).to_owned()).collect(),
    }
}

/// Smallest `max_total_candidate_bytes` for which the query succeeds (reliable
/// because segment-charge checks dominate; a binary search avoids hard-coding the
/// logical accounting constants into the assertion).
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

/// Smallest `max_segment_candidate_entries` for which the query succeeds.
fn min_segment_entries(snapshot: &ReaderSnapshot, query: &Query) -> u64 {
    let mut low = 1u64;
    let mut high = 1u64 << 20;
    while low < high {
        let mid = low + (high - low) / 2;
        let limits = SearchLimits::default()
            .with_max_segment_candidate_entries(mid)
            .unwrap();
        if run(snapshot, query, limits).is_ok() {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    low
}

fn limits_entries(entries: u64) -> SearchLimits {
    SearchLimits::default()
        .with_max_segment_candidate_entries(entries)
        .unwrap()
}

// ---------------------------------------------------------------------------
// A2-02 — sequential phrase scratch is released at its drop boundary
// ---------------------------------------------------------------------------

#[test]
fn a2_02_sequential_phrase_scratch_is_released() {
    let snapshot = build(vec![vec![title_doc("a", "x y p q")]]);
    let single = phrase(&["x", "y"]);
    let query = Query::Or(vec![phrase(&["x", "y"]), phrase(&["p", "q"])]);
    let response = run_default(&snapshot, &query);
    assert_eq!(keys(&response), vec!["a"]);

    // The second sibling leaf adds only its retained first-leaf match reservation
    // and its own live scratch, not the first leaf's historical scratch. A
    // cumulative (unreleased) scratch would need substantially more entries.
    let single_min = min_segment_entries(&snapshot, &single);
    let two_min = min_segment_entries(&snapshot, &query);
    assert!(
        two_min <= single_min + 4,
        "sequential scratch must not cumulate: single={single_min} two={two_min}"
    );
    // The boundary remains sharp.
    assert!(run(&snapshot, &query, limits_entries(two_min)).is_ok());
    assert!(matches!(
        run(&snapshot, &query, limits_entries(two_min - 1)),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// A2-03 — multi-segment batch transfer boundaries
// ---------------------------------------------------------------------------

#[test]
fn a2_03_multi_segment_batch_boundaries() {
    let snapshot = build(vec![
        vec![title_doc("a", "one")],
        vec![title_doc("bb", "two")],
        vec![title_doc("ccc", "three")],
    ]);
    let query = Query::MatchAll;
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

    let response = run_default(&snapshot, &query);
    assert_eq!(response.total_hits, 3);
    assert_eq!(keys(&response), vec!["a", "bb", "ccc"]);
}

// ---------------------------------------------------------------------------
// A2-09 — cancellation and work/scanned exhaustion during scratch and batches
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
fn a2_09_cancellation_and_work_exhaustion_recover() {
    let snapshot = build(vec![
        vec![title_doc("a", "x y p q")],
        vec![title_doc("b", "x y p q")],
    ]);
    let query = Query::Or(vec![phrase(&["x", "y"]), phrase(&["p", "q"])]);

    for budget in [0u32, 1, 2, 4, 8] {
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
    let tight = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    assert!(matches!(
        run(&snapshot, &query, tight),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A fresh request with sufficient limits succeeds on the same snapshot.
    let response = run_default(&snapshot, &query);
    assert_eq!(keys(&response), vec!["a", "b"]);
}

// ---------------------------------------------------------------------------
// A2-10 — per-segment peaks reset between segments
// ---------------------------------------------------------------------------

#[test]
fn a2_10_many_small_segments_reset_peak() {
    let batches: Vec<Vec<Document>> = (0..8)
        .map(|index| vec![title_doc(&format!("r{index:03}"), "token")])
        .collect();
    let snapshot = build(batches);
    // Peaks at two entries per segment; the cumulative lifetime count is 16.
    let response = run(
        &snapshot,
        &Query::MatchAll,
        SearchLimits::default()
            .with_max_segment_candidate_entries(2)
            .unwrap(),
    )
    .expect("per-segment peak resets");
    assert_eq!(response.total_hits, 8);

    // A single 4-document segment exceeds the same peak.
    let single = build(vec![vec![
        title_doc("s0", "token"),
        title_doc("s1", "token"),
        title_doc("s2", "token"),
        title_doc("s3", "token"),
    ]]);
    assert!(matches!(
        run(
            &single,
            &Query::MatchAll,
            SearchLimits::default()
                .with_max_segment_candidate_entries(2)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// A2-11 — semantics unchanged across memory and filesystem paths
// ---------------------------------------------------------------------------

#[test]
fn a2_11_memory_and_fs_agree() {
    let batches = || {
        vec![
            vec![title_doc("a", "quick brown fox")],
            vec![title_doc("b", "quick fox"), title_doc("c", "brown fox")],
        ]
    };
    let memory = build(batches());
    let query = phrase(&["quick", "brown", "fox"]);
    let memory_response = run_default(&memory, &query);

    let dir = TempDir::new("pr07-a2-11");
    let snapshot = {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(dir.path()).unwrap());
        build_on(directory, batches())
    };
    let fs_response = run_default(&snapshot, &query);
    assert_eq!(keys(&memory_response), vec!["a"]);
    assert_eq!(keys(&fs_response), vec!["a"]);
    assert_eq!(memory_response.total_hits, fs_response.total_hits);
}

// ---------------------------------------------------------------------------
// A2-12 — seeded bounded differential against an independent membership oracle
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
enum OracleNode {
    MatchAll,
    Term(String),
    Phrase(Vec<String>),
    And(Vec<OracleNode>),
    Or(Vec<OracleNode>),
    Not(Box<OracleNode>),
}

impl OracleNode {
    fn to_query(&self) -> Query {
        match self {
            Self::MatchAll => Query::MatchAll,
            Self::Term(term) => Query::Term {
                field: "title".into(),
                value: FieldValue::Text(term.clone()),
            },
            Self::Phrase(tokens) => Query::Phrase {
                field: "title".into(),
                terms: tokens.clone(),
            },
            Self::And(children) => Query::And(children.iter().map(Self::to_query).collect()),
            Self::Or(children) => Query::Or(children.iter().map(Self::to_query).collect()),
            Self::Not(inner) => Query::Not(Box::new(inner.to_query())),
        }
    }

    fn evaluate(&self, tokens: &[String]) -> bool {
        match self {
            Self::MatchAll => true,
            Self::Term(term) => tokens.iter().any(|token| token == term),
            Self::Phrase(phrase) => {
                phrase.len() <= tokens.len()
                    && (0..=tokens.len() - phrase.len())
                        .any(|start| &tokens[start..start + phrase.len()] == phrase.as_slice())
            }
            Self::And(children) => children.iter().all(|child| child.evaluate(tokens)),
            Self::Or(children) => children.iter().any(|child| child.evaluate(tokens)),
            Self::Not(inner) => !inner.evaluate(tokens),
        }
    }
}

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

fn generate_node(lcg: &mut Lcg, depth: usize) -> OracleNode {
    let vocab = ["a", "b", "c", "d"];
    if depth == 0 || lcg.below(4) == 0 {
        return match lcg.below(4) {
            0 => OracleNode::MatchAll,
            1 => {
                let len = lcg.below(2) + 1;
                OracleNode::Phrase(
                    (0..len)
                        .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                        .collect(),
                )
            }
            _ => OracleNode::Term(vocab[lcg.below(vocab.len())].to_owned()),
        };
    }
    match lcg.below(4) {
        0 => {
            let count = lcg.below(3) + 1;
            OracleNode::And((0..count).map(|_| generate_node(lcg, depth - 1)).collect())
        }
        1 => {
            let count = lcg.below(3) + 1;
            OracleNode::Or((0..count).map(|_| generate_node(lcg, depth - 1)).collect())
        }
        2 => OracleNode::Not(Box::new(generate_node(lcg, depth - 1))),
        _ => {
            let len = lcg.below(2) + 1;
            OracleNode::Phrase(
                (0..len)
                    .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                    .collect(),
            )
        }
    }
}

#[test]
fn a2_12_seeded_differential_membership() {
    let vocab = ["a", "b", "c", "d"];
    for seed_offset in 0..200u64 {
        let seed = 0xA202u64 ^ seed_offset;
        let mut lcg = Lcg::new(seed);
        let segment_count = lcg.below(4) + 1;
        let mut batches = Vec::new();
        let mut docs: Vec<(String, Vec<String>)> = Vec::new();
        let mut counter = 0usize;
        for _ in 0..segment_count {
            let doc_count = lcg.below(8);
            let mut batch = Vec::new();
            for _ in 0..doc_count {
                let key = format!("k{counter:03}");
                counter += 1;
                let token_count = lcg.below(4) + 1;
                let tokens: Vec<String> = (0..token_count)
                    .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                    .collect();
                batch.push(title_doc(&key, &tokens.join(" ")));
                docs.push((key, tokens));
            }
            batches.push(batch);
        }
        let snapshot = build(batches);
        let node = generate_node(&mut lcg, 4);
        let query = node.to_query();
        let response = run_default(&snapshot, &query);
        let expected: BTreeSet<String> = docs
            .iter()
            .filter(|(_, tokens)| node.evaluate(tokens))
            .map(|(key, _)| key.clone())
            .collect();
        let actual: BTreeSet<String> = keys(&response).into_iter().collect();
        assert_eq!(
            actual, expected,
            "seed {seed} query {query:?} docs {docs:?}"
        );
        assert_eq!(response.total_hits as usize, expected.len(), "seed {seed}");
    }
}
