//! PR 7 Amendment 01 regression and boundary tests.
//!
//! Covers Boolean scoring polarity (S), per-segment/global resource accounting
//! (B), field-length entry occupancy (L), top-K replacement (unit tests in
//! `search/topk.rs`), and independent scanned-occurrence/cancellation behavior
//! (F). Oracles are test-local and never call production `score_segment`,
//! `eval_node` or `collect_positive_leaves`.

mod common;

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

/// Whitespace-analyzed title schema so the oracle can reason about raw tokens.
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

fn build(batches: Vec<Vec<Document>>) -> Arc<ReaderSnapshot> {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
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

fn run(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
) -> Result<SearchResponse, SearchError> {
    run_with(snapshot, query, limits, &CancellationFlag::new())
}

fn run_with(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
    cancel: &dyn Cancellation,
) -> Result<SearchResponse, SearchError> {
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    LexicalSearcher::new(snapshot, &schema, &registry, limits).search(
        query,
        TopK::new(100).unwrap(),
        &Budgets::new(),
        cancel,
    )
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

fn score_of(response: &SearchResponse, key: &str) -> Option<f64> {
    response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == key)
        .map(|hit| hit.score)
}

fn term(text: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(text.into()),
    }
}

/// Four-document polarity corpus: {alpha}, {beta}, {alpha,beta}, {gamma}.
fn polarity_corpus() -> Arc<ReaderSnapshot> {
    build(vec![vec![
        title_doc("da", "alpha"),
        title_doc("db", "beta"),
        title_doc("dab", "alpha beta"),
        title_doc("dnone", "gamma"),
    ]])
}

// ---------------------------------------------------------------------------
// S — Boolean scoring polarity
// ---------------------------------------------------------------------------

#[test]
fn s01_odd_not_leaf_scores_zero() {
    let snapshot = polarity_corpus();
    let query = Query::Not(Box::new(Query::And(vec![term("alpha"), term("beta")])));
    let response = run_default(&snapshot, &query);
    assert_eq!(response.total_hits, 3);
    assert_eq!(keys(&response), vec!["da", "db", "dnone"]);
    for hit in &response.hits {
        assert_eq!(hit.score, 0.0, "negative-only leaf must not score");
    }
}

#[test]
fn s02_or_negative_subtree_does_not_inflate() {
    let snapshot = polarity_corpus();
    let query = Query::Or(vec![
        term("gamma"),
        Query::Not(Box::new(Query::And(vec![term("alpha"), term("beta")]))),
    ]);
    let response = run_default(&snapshot, &query);
    assert_eq!(keys(&response), vec!["da", "db", "dnone"]);
    assert_eq!(score_of(&response, "da"), Some(0.0));
    assert_eq!(score_of(&response, "db"), Some(0.0));
    assert!(score_of(&response, "dnone").unwrap() > 0.0);
}

#[test]
fn s03_double_not_scores() {
    let snapshot = polarity_corpus();
    let query = Query::Not(Box::new(Query::Not(Box::new(term("alpha")))));
    let response = run_default(&snapshot, &query);
    assert_eq!(keys(&response), vec!["da", "dab"]);
    assert!(response.hits.iter().all(|hit| hit.score > 0.0));
    assert_eq!(response.total_hits, 2);
}

#[test]
fn s04_same_leaf_mixed_polarity_scores_once() {
    let snapshot = polarity_corpus();
    let query = Query::Or(vec![
        term("alpha"),
        Query::Not(Box::new(Query::And(vec![term("alpha"), term("beta")]))),
    ]);
    let response = run_default(&snapshot, &query);
    assert_eq!(keys(&response), vec!["da", "dab", "db", "dnone"]);
    let alpha_only = run_default(&snapshot, &term("alpha"));
    assert_eq!(score_of(&response, "da"), score_of(&alpha_only, "da"));
    assert_eq!(score_of(&response, "dab"), score_of(&alpha_only, "dab"));
    // beta is negative-only here and must not contribute.
    assert_eq!(score_of(&response, "db"), Some(0.0));
    assert_eq!(score_of(&response, "dnone"), Some(0.0));
}

#[test]
fn s05_duplicate_positive_leaves_do_not_multiply() {
    let snapshot = polarity_corpus();
    let single = run_default(&snapshot, &term("alpha"));
    let triplicated = run_default(
        &snapshot,
        &Query::Or(vec![term("alpha"), term("alpha"), term("alpha")]),
    );
    assert_eq!(triplicated.total_hits, single.total_hits);
    assert_eq!(keys(&triplicated), keys(&single));
    for (left, right) in triplicated.hits.iter().zip(&single.hits) {
        assert_eq!(left.key, right.key);
        assert!((left.score - right.score).abs() < 1e-12);
    }
}

#[test]
fn s06_pure_negative_and_matchall_score_zero_without_negative_field_scan() {
    // A second, large-vocabulary field must not be scanned for a negative-only leaf.
    let schema = Schema::new(
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
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
        ],
        None,
    )
    .unwrap();
    let mut docs = Vec::new();
    for index in 0..8 {
        let mut document = Document::new(DocumentKey::new(format!("n{index}")).unwrap());
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("shared".into())),
            )
            .unwrap();
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(format!("w{index} w{}", index + 100))),
            )
            .unwrap();
        docs.push(document);
    }
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(
        directory.clone(),
        schema.clone(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in docs {
        writer.insert(document).unwrap();
    }
    writer.flush().unwrap();
    writer.commit().unwrap();
    drop(writer);
    let snapshot = Index::open_existing(directory, schema.clone(), AnalyzerRegistry::builtin())
        .unwrap()
        .snapshot();
    let registry = AnalyzerRegistry::builtin();

    // A negative-only `body` term with a one-term dictionary budget: the body field
    // must not be scanned for BM25 statistics.
    let limits = SearchLimits::default()
        .with_max_dictionary_terms_examined(1)
        .unwrap();
    let query = Query::Not(Box::new(Query::Term {
        field: "body".into(),
        value: FieldValue::Text("w0".into()),
    }));
    let response = LexicalSearcher::new(&snapshot, &schema, &registry, limits)
        .search(
            &query,
            TopK::new(100).unwrap(),
            &Budgets::new(),
            &CancellationFlag::new(),
        )
        .unwrap();
    assert_eq!(response.total_hits, 7);
    assert!(response.hits.iter().all(|hit| hit.score == 0.0));

    let match_all = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
        .search(
            &Query::MatchAll,
            TopK::new(100).unwrap(),
            &Budgets::new(),
            &CancellationFlag::new(),
        )
        .unwrap();
    assert_eq!(match_all.total_hits, 8);
    assert!(match_all.hits.iter().all(|hit| hit.score == 0.0));
}

// ---------------------------------------------------------------------------
// S07 — randomized parity oracle
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
enum OracleNode {
    MatchAll,
    Term(String),
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
            Self::And(children) => Query::And(children.iter().map(Self::to_query).collect()),
            Self::Or(children) => Query::Or(children.iter().map(Self::to_query).collect()),
            Self::Not(inner) => Query::Not(Box::new(inner.to_query())),
        }
    }

    fn evaluate(&self, tokens: &BTreeSet<String>) -> bool {
        match self {
            Self::MatchAll => true,
            Self::Term(term) => tokens.contains(term),
            Self::And(children) => children.iter().all(|child| child.evaluate(tokens)),
            Self::Or(children) => children.iter().any(|child| child.evaluate(tokens)),
            Self::Not(inner) => !inner.evaluate(tokens),
        }
    }

    /// Collect canonical positive leaf identities, deduplicated.
    fn positive_leaves(&self, negated: bool, positive: &mut BTreeSet<String>) {
        match self {
            Self::MatchAll => {}
            Self::Term(term) => {
                if !negated {
                    positive.insert(term.clone());
                }
            }
            Self::And(children) | Self::Or(children) => {
                for child in children {
                    child.positive_leaves(negated, positive);
                }
            }
            Self::Not(inner) => inner.positive_leaves(!negated, positive),
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

fn generate_oracle(lcg: &mut Lcg, depth: usize) -> OracleNode {
    if depth == 0 || lcg.below(3) == 0 {
        if lcg.below(4) == 0 {
            return OracleNode::MatchAll;
        }
        let vocab = ["a", "b", "c"];
        return OracleNode::Term(vocab[lcg.below(vocab.len())].to_owned());
    }
    match lcg.below(4) {
        0 => {
            let count = lcg.below(3) + 1;
            OracleNode::And(
                (0..count)
                    .map(|_| generate_oracle(lcg, depth - 1))
                    .collect(),
            )
        }
        1 => {
            let count = lcg.below(3) + 1;
            OracleNode::Or(
                (0..count)
                    .map(|_| generate_oracle(lcg, depth - 1))
                    .collect(),
            )
        }
        2 => OracleNode::Not(Box::new(generate_oracle(lcg, depth - 1))),
        _ => {
            let vocab = ["a", "b", "c"];
            OracleNode::Term(vocab[lcg.below(vocab.len())].to_owned())
        }
    }
}

#[test]
fn s07_random_boolean_parity_matches_independent_oracle() {
    let vocab = ["a", "b", "c"];
    for seed_offset in 0..200u64 {
        let seed = 0xA107u64 ^ seed_offset;
        let mut lcg = Lcg::new(seed);
        let doc_count = lcg.below(7) + 2;
        let mut documents = Vec::new();
        let mut doc_tokens: Vec<(String, BTreeSet<String>)> = Vec::new();
        for index in 0..doc_count {
            let key = format!("x{index:02}");
            let token_count = lcg.below(4) + 1;
            let mut tokens = BTreeSet::new();
            for _ in 0..token_count {
                tokens.insert(vocab[lcg.below(vocab.len())].to_owned());
            }
            let title: Vec<String> = tokens.iter().cloned().collect();
            documents.push(title_doc(&key, &title.join(" ")));
            doc_tokens.push((key, tokens));
        }
        let snapshot = build(vec![documents]);
        let oracle = generate_oracle(&mut lcg, 5);
        let query = oracle.to_query();
        let response = run_default(&snapshot, &query);

        let mut positive = BTreeSet::new();
        oracle.positive_leaves(false, &mut positive);

        let mut expected_hits = BTreeSet::new();
        for (key, tokens) in &doc_tokens {
            if !oracle.evaluate(tokens) {
                continue;
            }
            expected_hits.insert(key.clone());
        }
        assert_eq!(
            keys(&response).into_iter().collect::<BTreeSet<_>>(),
            expected_hits,
            "seed {seed} query {query:?}"
        );
        // Nonzero score iff some positive leaf matches the document.
        for hit in &response.hits {
            let tokens = &doc_tokens
                .iter()
                .find(|(key, _)| key == hit.key.as_str())
                .unwrap()
                .1;
            let positive_match = positive.iter().any(|term| tokens.contains(term));
            assert_eq!(
                hit.score > 0.0,
                positive_match,
                "seed {seed} key {} query {query:?}",
                hit.key
            );
        }
    }
}

// ---------------------------------------------------------------------------
// B — resource accounting
// ---------------------------------------------------------------------------

fn repeated_corpus(segments: usize, per_segment: usize) -> Arc<ReaderSnapshot> {
    let mut batches = Vec::new();
    for segment in 0..segments {
        let mut batch = Vec::new();
        for offset in 0..per_segment {
            let index = segment * per_segment + offset;
            batch.push(title_doc(&format!("r{index:03}"), "token"));
        }
        batches.push(batch);
    }
    build(batches)
}

#[test]
fn b01_per_segment_entry_budget_resets_between_segments() {
    // Each 4-doc segment peaks at 8 logical entries under the Amendment 02
    // lifetime-accurate release order (live set + MatchAll clone, then match +
    // scored map); the pre-amendment lifetime counter reached 16 across two.
    let snapshot = repeated_corpus(2, 4);
    let limits = SearchLimits::default()
        .with_max_segment_candidate_entries(8)
        .unwrap();
    let response = run(&snapshot, &Query::MatchAll, limits).expect("within per-segment bound");
    assert_eq!(response.total_hits, 8);
}

#[test]
fn b02_per_segment_entry_budget_one_over_fails() {
    let snapshot = repeated_corpus(2, 4);
    let limits = SearchLimits::default()
        .with_max_segment_candidate_entries(7)
        .unwrap();
    let error = run(&snapshot, &Query::MatchAll, limits).unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
}

#[test]
fn b03_per_segment_entry_boundary_is_exact() {
    let snapshot = repeated_corpus(1, 4);
    assert!(
        run(
            &snapshot,
            &Query::MatchAll,
            SearchLimits::default()
                .with_max_segment_candidate_entries(8)
                .unwrap()
        )
        .is_ok()
    );
    assert!(matches!(
        run(
            &snapshot,
            &Query::MatchAll,
            SearchLimits::default()
                .with_max_segment_candidate_entries(7)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
}

#[test]
fn b04_boolean_intermediates_are_charged_concurrently() {
    let snapshot = build(vec![vec![
        title_doc("a", "x y"),
        title_doc("b", "x"),
        title_doc("c", "y"),
        title_doc("d", "z"),
    ]]);
    // AND materializes two leaf sets plus the intersection simultaneously.
    let query = Query::And(vec![term("x"), term("y")]);
    let generous = run(&snapshot, &query, SearchLimits::default()).unwrap();
    assert_eq!(keys(&generous), vec!["a"]);
    // A one-entry per-segment bound cannot hold the overlapping intermediates.
    assert!(matches!(
        run(
            &snapshot,
            &query,
            SearchLimits::default()
                .with_max_segment_candidate_entries(1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
}

#[test]
fn b05_multi_segment_repeat_is_stable() {
    let documents = || {
        vec![
            title_doc("a", "alpha beta"),
            title_doc("b", "alpha"),
            title_doc("c", "beta"),
        ]
    };
    // One segment.
    let single = build(vec![documents()]);
    // Four segments, with duplicate-free docs spread across them.
    let four = build(vec![
        vec![title_doc("a", "alpha beta")],
        vec![title_doc("b", "alpha")],
        vec![title_doc("c", "beta")],
        vec![],
    ]);
    let query = Query::Or(vec![term("alpha"), term("beta")]);
    let single_response = run_default(&single, &query);
    let four_response = run_default(&four, &query);
    assert_eq!(single_response.total_hits, four_response.total_hits);
    assert_eq!(keys(&single_response), keys(&four_response));
}

#[test]
fn b06_cumulative_work_and_cancellation() {
    let snapshot = repeated_corpus(2, 4);
    // Total work is cumulative across segments.
    let limits = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    let error = run(&snapshot, &term("token"), limits).unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));

    // Cancellation at start and during work both return `Cancelled`.
    assert!(matches!(
        run_with(
            &snapshot,
            &Query::MatchAll,
            SearchLimits::default(),
            &CancelAfter::new(0)
        ),
        Err(SearchError::Cancelled)
    ));
    for budget in [1u32, 3, 7] {
        assert!(
            matches!(
                run_with(
                    &snapshot,
                    &Query::Not(Box::new(term("token"))),
                    SearchLimits::default(),
                    &CancelAfter::new(budget)
                ),
                Err(SearchError::Cancelled)
            ),
            "budget {budget}"
        );
    }
}

#[test]
fn b07_total_byte_budget_peak_is_exact() {
    // Two one-byte keys, MatchAll over a single segment. Under the Amendment 02
    // release order the peak is the scored map (2*64 = 128) plus the resolved-key
    // move buffer (2*97 = 194) while both are live: 322 bytes.
    let snapshot = build(vec![vec![title_doc("a", "one"), title_doc("b", "two")]]);
    let exact = 322;
    assert!(
        run(
            &snapshot,
            &Query::MatchAll,
            SearchLimits::default()
                .with_max_total_candidate_bytes(exact)
                .unwrap()
        )
        .is_ok()
    );
    let error = run(
        &snapshot,
        &Query::MatchAll,
        SearchLimits::default()
            .with_max_total_candidate_bytes(exact - 1)
            .unwrap(),
    )
    .unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
}

#[test]
fn b10_failure_releases_and_next_search_succeeds() {
    let snapshot = repeated_corpus(2, 4);
    let tight = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    assert!(matches!(
        run(&snapshot, &term("token"), tight),
        Err(SearchError::ResourceLimit { .. })
    ));
    let response = run_default(&snapshot, &term("token"));
    assert_eq!(response.total_hits, 8);
    let response = run_default(&snapshot, &Query::MatchAll);
    assert_eq!(response.total_hits, 8);
}

#[test]
fn b11_phrase_and_boolean_temporaries_are_charged() {
    let snapshot = build(vec![vec![
        title_doc("a", "quick brown fox"),
        title_doc("b", "quick brown"),
    ]]);
    let phrase = Query::Phrase {
        field: "title".into(),
        terms: vec!["quick".into(), "brown".into()],
    };
    assert!(run(&snapshot, &phrase, SearchLimits::default()).is_ok());
    assert!(matches!(
        run(
            &snapshot,
            &phrase,
            SearchLimits::default()
                .with_max_segment_candidate_entries(1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// F — scanned occurrences and cancellation
// ---------------------------------------------------------------------------

#[test]
fn f01_scanned_occurrence_budget_is_independent() {
    let snapshot = build(vec![vec![title_doc("a", "alpha alpha alpha")]]);
    let query = term("alpha");
    // Generous work but a one-occurrence scan budget must fail.
    let limits = SearchLimits::default()
        .with_max_scanned_posting_occurrences(1)
        .unwrap();
    let error = run(&snapshot, &query, limits).unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
    assert!(run(&snapshot, &query, SearchLimits::default()).is_ok());
}

#[test]
fn f03_cancellation_on_pure_negative_terminates() {
    let snapshot = repeated_corpus(2, 4);
    let query = Query::Not(Box::new(term("missing")));
    assert!(matches!(
        run_with(
            &snapshot,
            &query,
            SearchLimits::default(),
            &CancelAfter::new(2)
        ),
        Err(SearchError::Cancelled)
    ));
}

// ---------------------------------------------------------------------------
// L — field-length entry occupancy
// ---------------------------------------------------------------------------

#[test]
fn l01_single_doc_multiple_terms_is_one_entry() {
    let snapshot = build(vec![vec![title_doc("a", "alpha beta gamma")]]);
    // One document contributes exactly one length-map entry per field.
    let limits = SearchLimits::default()
        .with_max_field_length_entries(1)
        .unwrap();
    let response = run(&snapshot, &term("alpha"), limits).unwrap();
    assert_eq!(response.total_hits, 1);
}

#[test]
fn l02_field_length_entry_boundary_is_exact() {
    // Amendment 05: new-format segments persist immutable field norms and never
    // build a per-query document-length map, so `max_field_length_entries` no
    // longer applies to them. The legacy fallback budget is exercised directly by
    // `search::score::tests::legacy_segment_field_length_budget_is_enforced`
    // against the checked-in legacy golden fixture.
    let snapshot = build(vec![vec![title_doc("a", "alpha"), title_doc("b", "alpha")]]);
    for entries in [1u64, 2, 1024] {
        assert!(
            run(
                &snapshot,
                &term("alpha"),
                SearchLimits::default()
                    .with_max_field_length_entries(entries)
                    .unwrap()
            )
            .is_ok(),
            "persisted norms must not charge field-length entries (limit {entries})"
        );
    }
}

// ---------------------------------------------------------------------------
// Shared cancellation helper
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
