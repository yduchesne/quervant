//! PR 7 focused unit/behavior tests (U01–U19) over the real writer/reader path.

mod common;

use std::sync::Arc;

use common::{Pr07Doc, pr07_commit_batches, pr07_registry, pr07_schema};
use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

fn snapshot(batches: Vec<Vec<quervant_core::contract::document::Document>>) -> Arc<ReaderSnapshot> {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    pr07_commit_batches(directory.clone(), batches);
    Index::open_existing(directory, pr07_schema(), pr07_registry())
        .unwrap()
        .snapshot()
}

fn snapshot_one(
    documents: Vec<quervant_core::contract::document::Document>,
) -> Arc<ReaderSnapshot> {
    snapshot(vec![documents])
}

fn run(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    run_k(snapshot, query, 50)
}

fn run_k(snapshot: &ReaderSnapshot, query: &Query, k: usize) -> SearchResponse {
    let schema = pr07_schema();
    let registry = pr07_registry();
    let cancel = CancellationFlag::new();
    LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
        .search(query, TopK::new(k).unwrap(), &Budgets::new(), &cancel)
        .expect("search")
}

fn keys_sorted(response: &SearchResponse) -> Vec<String> {
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

fn term(field: &str, text: &str) -> Query {
    Query::Term {
        field: field.into(),
        value: FieldValue::Text(text.into()),
    }
}

fn keyword_term(field: &str, text: &str) -> Query {
    Query::Term {
        field: field.into(),
        value: FieldValue::Keyword(text.into()),
    }
}

fn phrase(field: &str, terms: &[&str]) -> Query {
    Query::Phrase {
        field: field.into(),
        terms: terms.iter().map(|term| (*term).to_owned()).collect(),
    }
}

// U01 — term field isolation and missing terms.
#[test]
fn u01_term_field_isolation_and_missing() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("rust").body(vec!["python"]).build(),
        Pr07Doc::new("b").title("python").build(),
    ]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &term("title", "rust"))),
        vec!["a"]
    );
    assert!(run(&snapshot, &term("body", "rust")).hits.is_empty());
    assert!(run(&snapshot, &term("title", "java")).hits.is_empty());
}

// U02 — keyword normalization and analyzer mismatch.
#[test]
fn u02_keyword_normalization_and_mismatch() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").host("café.example").build(),
        Pr07Doc::new("b").host("cafe.example").build(),
    ]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &keyword_term("host", "café.example"))),
        vec!["a"]
    );
    assert_eq!(
        keys_sorted(&run(&snapshot, &keyword_term("host", "cafe.example"))),
        vec!["b"]
    );
    // A registry lacking the schema's analyzer fails closed.
    let empty = AnalyzerRegistry::default();
    let schema = pr07_schema();
    let cancel = CancellationFlag::new();
    let result = LexicalSearcher::new(&snapshot, &schema, &empty, SearchLimits::default()).search(
        &term("title", "rust"),
        TopK::new(1).unwrap(),
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Analysis(_))));
}

// U03 — AND intersection.
#[test]
fn u03_and_intersection() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("alpha beta").build(),
        Pr07Doc::new("b").title("alpha").build(),
        Pr07Doc::new("c").title("beta").build(),
    ]);
    let query = Query::And(vec![term("title", "alpha"), term("title", "beta")]);
    assert_eq!(keys_sorted(&run(&snapshot, &query)), vec!["a"]);
    assert_eq!(run(&snapshot, &query).total_hits, 1);
}

// U04 — OR union and dedup.
#[test]
fn u04_or_union() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("alpha beta").build(),
        Pr07Doc::new("b").title("alpha").build(),
        Pr07Doc::new("c").title("beta").build(),
    ]);
    let query = Query::Or(vec![term("title", "alpha"), term("title", "beta")]);
    assert_eq!(keys_sorted(&run(&snapshot, &query)), vec!["a", "b", "c"]);
    assert_eq!(run(&snapshot, &query).total_hits, 3);
}

// U05 — NOT complement and pure negative.
#[test]
fn u05_not_complement() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("alpha beta").build(),
        Pr07Doc::new("b").title("alpha").build(),
        Pr07Doc::new("c").title("beta").build(),
    ]);
    let query = Query::Not(Box::new(term("title", "alpha")));
    let response = run(&snapshot, &query);
    assert_eq!(keys_sorted(&response), vec!["c"]);
    // Pure-negative documents are zero-score hits.
    assert!(response.hits.iter().all(|hit| hit.score == 0.0));
    assert!(
        run(&snapshot, &Query::Not(Box::new(Query::MatchAll)))
            .hits
            .is_empty()
    );
}

// U06 — nested De Morgan and double negation.
#[test]
fn u06_nested_boolean() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("alpha beta").build(),
        Pr07Doc::new("b").title("alpha").build(),
        Pr07Doc::new("c").title("beta").build(),
        Pr07Doc::new("d").title("gamma").build(),
    ]);
    let double_negation = Query::Not(Box::new(Query::Not(Box::new(term("title", "alpha")))));
    assert_eq!(
        keys_sorted(&run(&snapshot, &double_negation)),
        vec!["a", "b"]
    );

    let de_morgan = Query::Not(Box::new(Query::Or(vec![
        term("title", "alpha"),
        term("title", "beta"),
    ])));
    let expected = Query::And(vec![
        Query::Not(Box::new(term("title", "alpha"))),
        Query::Not(Box::new(term("title", "beta"))),
    ]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &de_morgan)),
        keys_sorted(&run(&snapshot, &expected))
    );
    assert_eq!(keys_sorted(&run(&snapshot, &de_morgan)), vec!["d"]);
}

// U07 — adjacent phrase.
#[test]
fn u07_adjacent_phrase() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("quick brown fox").build(),
        Pr07Doc::new("b").title("quick fox").build(),
    ]);
    assert_eq!(
        keys_sorted(&run(
            &snapshot,
            &phrase("title", &["quick", "brown", "fox"])
        )),
        vec!["a"]
    );
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("title", &["quick", "fox"]))),
        vec!["b"]
    );
}

// U08 — stopword position hole.
#[test]
fn u08_stopword_gap() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("quick the fox").build(),
        Pr07Doc::new("b").title("quick fox").build(),
    ]);
    // The stopword is part of the query, so the analyzed positions are 0 and 2.
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("title", &["quick", "the", "fox"]))),
        vec!["a"]
    );
    // Without the stopword the query is adjacent and matches only the adjacent doc.
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("title", &["quick", "fox"]))),
        vec!["b"]
    );
}

// U09 — repeated term requires distinct successive positions.
#[test]
fn u09_repeated_term() {
    let snapshot = snapshot_one(vec![Pr07Doc::new("a").title("alpha alpha beta").build()]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("title", &["alpha", "alpha"]))),
        vec!["a"]
    );
    assert!(
        run(&snapshot, &phrase("title", &["alpha", "alpha", "alpha"]))
            .hits
            .is_empty()
    );
}

// U10 — multi-value field boundaries are never bridged.
#[test]
fn u10_multi_value_boundary() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").body(vec!["quick brown", "fox"]).build(),
        Pr07Doc::new("b").body(vec!["quick brown fox"]).build(),
    ]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("body", &["quick", "brown", "fox"]))),
        vec!["b"]
    );
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("body", &["quick", "brown"]))),
        vec!["a", "b"]
    );
}

// U11 — phrase on a non-Text field is unsupported; single-token phrase equals term.
#[test]
fn u11_phrase_capability() {
    let snapshot = snapshot_one(vec![Pr07Doc::new("a").title("singleton").build()]);
    assert_eq!(
        keys_sorted(&run(&snapshot, &phrase("title", &["singleton"]))),
        vec!["a"]
    );
    let schema = pr07_schema();
    let registry = pr07_registry();
    let cancel = CancellationFlag::new();
    let result = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
        .search(
            &phrase("tags", &["a"]),
            TopK::new(1).unwrap(),
            &Budgets::new(),
            &cancel,
        );
    assert!(matches!(
        result,
        Err(SearchError::UnsupportedOperator { .. })
    ));
}

// U12 — BM25 golden score against the documented formula.
#[test]
fn u12_bm25_golden() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("alpha").build(),
        Pr07Doc::new("b").title("alpha alpha").build(),
    ]);
    let response = run(&snapshot, &term("title", "alpha"));
    // Independently tabulated: N=2, df=2, dl(a)=1, dl(b)=2, avgdl=1.5.
    let idf = (1.0_f64 + (2.0_f64 - 2.0 + 0.5) / (2.0 + 0.5)).ln();
    let expected = |tf: f64, dl: f64| {
        let denominator = tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / 1.5);
        idf * (tf * 2.2) / denominator
    };
    let scores: std::collections::BTreeMap<_, _> = response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score))
        .collect();
    assert!((scores["a"] - expected(1.0, 1.0)).abs() < 1e-10);
    assert!((scores["b"] - expected(2.0, 2.0)).abs() < 1e-10);
}

// U13 — document frequency spans segments.
#[test]
fn u13_global_df_across_segments() {
    let snapshot = snapshot(vec![
        vec![Pr07Doc::new("a").title("shared token").build()],
        vec![Pr07Doc::new("b").title("shared").build()],
    ]);
    let response = run(&snapshot, &term("title", "shared"));
    assert_eq!(response.total_hits, 2);
    assert_eq!(keys_sorted(&response), vec!["a", "b"]);
}

// U14 — absent field and zero average length.
#[test]
fn u14_absent_field_and_zero_avgdl() {
    let snapshot = snapshot_one(vec![Pr07Doc::new("a").n(1).build()]);
    assert!(run(&snapshot, &term("title", "missing")).hits.is_empty());
    let match_all = run(&snapshot, &Query::MatchAll);
    assert_eq!(match_all.total_hits, 1);
    assert_eq!(match_all.hits[0].score, 0.0);
}

// U15 — duplicate clauses and same term in distinct fields.
#[test]
fn u15_duplicate_clauses_and_fields() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("rust").body(vec!["rust"]).build(),
    ]);
    let single = run(&snapshot, &term("title", "rust"));
    let duplicated = run(
        &snapshot,
        &Query::And(vec![term("title", "rust"), term("title", "rust")]),
    );
    assert!((single.hits[0].score - duplicated.hits[0].score).abs() < 1e-12);

    let two_fields = run(
        &snapshot,
        &Query::Or(vec![term("title", "rust"), term("body", "rust")]),
    );
    assert!(two_fields.hits[0].score > single.hits[0].score);
}

// U16 — all scores are finite and nonnegative.
#[test]
fn u16_scores_are_finite() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a")
            .title("rust rust rust")
            .body(vec!["rust"])
            .build(),
        Pr07Doc::new("b").title("rust").build(),
    ]);
    for query in [term("title", "rust"), Query::MatchAll, term("body", "rust")] {
        let response = run(&snapshot, &query);
        assert!(
            response
                .hits
                .iter()
                .all(|hit| hit.score.is_finite() && hit.score >= 0.0)
        );
    }
}

// U17 — heap comparator ties order by key ascending.
#[test]
fn u17_heap_ties() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("c").title("tied").build(),
        Pr07Doc::new("a").title("tied").build(),
        Pr07Doc::new("b").title("tied").build(),
    ]);
    let response = run(&snapshot, &term("title", "tied"));
    assert_eq!(
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        vec!["a", "b", "c"]
    );
}

// U18/U19 — top-K prefix and exact total count unaffected by K.
#[test]
fn u18_topk_prefix_and_exact_count() {
    let snapshot = snapshot_one(vec![
        Pr07Doc::new("a").title("token token token").build(),
        Pr07Doc::new("b").title("token token").build(),
        Pr07Doc::new("c").title("token").build(),
    ]);
    let query = term("title", "token");
    let full = run_k(&snapshot, &query, 10);
    assert_eq!(full.total_hits, 3);
    for k in 1..=3 {
        let response = run_k(&snapshot, &query, k);
        assert_eq!(response.total_hits, 3, "count must not depend on K");
        assert_eq!(response.hits.len(), k);
        assert_eq!(
            response
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect::<Vec<_>>(),
            full.hits
                .iter()
                .take(k)
                .map(|hit| hit.key.as_str().to_owned())
                .collect::<Vec<_>>()
        );
    }
}
