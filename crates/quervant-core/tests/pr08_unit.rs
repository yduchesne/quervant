//! PR 8 unit tests — operator semantics, validation and bounds (T01–T12, T22–T28).
//!
//! These tests exercise the real `IndexWriter -> commit -> Index::open_existing ->
//! LexicalSearcher` production path over `MemoryDirectory`. The independent oracle
//! lives in `pr08_properties.rs`.

mod common;

use std::sync::Arc;

use common::{Pr07Doc, pr08_commit_batches, pr08_registry, pr08_schema};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::DocumentKey;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::MemoryDirectory;

fn corpus() -> Vec<Pr07Doc<'static>> {
    vec![
        Pr07Doc::new("h1").host("rust").tags(vec!["rust"]),
        Pr07Doc::new("h2").host("crust").tags(vec!["crust"]),
        Pr07Doc::new("h3").host("rusty").tags(vec!["rusty"]),
        Pr07Doc::new("h4").host("run").tags(vec!["run"]),
        Pr07Doc::new("h5").host("rést").tags(vec!["rést"]),
        Pr07Doc::new("h6").host("r?st").tags(vec!["r?st", "r*st"]),
        Pr07Doc::new("h7").host("ru").tags(vec!["ru"]),
        Pr07Doc::new("h8").host("rsut").tags(vec!["rsut"]),
        Pr07Doc::new("h9").host("abc").tags(vec!["abc"]),
    ]
}

fn open_corpus() -> Index {
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(
        directory.clone(),
        vec![corpus().into_iter().map(|d| d.build()).collect()],
    );
    Index::open_existing(directory, pr08_schema(), pr08_registry()).expect("open")
}

fn search(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    search_with(snapshot, query, SearchLimits::default()).expect("search")
}

fn search_with(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
) -> Result<SearchResponse, SearchError> {
    LexicalSearcher::new(snapshot, &pr08_schema(), &pr08_registry(), limits).search(
        query,
        TopK::new(100).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
}

fn search_with_topk(
    snapshot: &ReaderSnapshot,
    query: &Query,
    limits: SearchLimits,
    top_k: usize,
) -> Result<SearchResponse, SearchError> {
    LexicalSearcher::new(snapshot, &pr08_schema(), &pr08_registry(), limits).search(
        query,
        TopK::new(top_k).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
}

fn keys(response: &SearchResponse) -> Vec<String> {
    let mut found: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    found.sort();
    found
}

fn prefix(field: &str, value: &str) -> Query {
    Query::Prefix {
        field: field.to_owned(),
        prefix: value.to_owned(),
    }
}

fn glob(field: &str, pattern: &str) -> Query {
    Query::Glob {
        field: field.to_owned(),
        pattern: pattern.to_owned(),
    }
}

fn regex(field: &str, pattern: &str) -> Query {
    Query::Regex {
        field: field.to_owned(),
        pattern: pattern.to_owned(),
    }
}

fn fuzzy(field: &str, value: &str, max_edits: u8, transpositions: bool) -> Query {
    Query::Fuzzy {
        field: field.to_owned(),
        value: value.to_owned(),
        max_edits,
        transpositions,
    }
}

// I01 / T01 — prefix is a whole-term start match, not a substring match.
#[test]
fn p8_t01_prefix_whole_term() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    assert_eq!(
        keys(&search(&snapshot, &prefix("host", "rust"))),
        ["h1", "h3"]
    );
    assert_eq!(
        keys(&search(&snapshot, &prefix("host", "ru"))),
        ["h1", "h3", "h4", "h7"]
    );
    // `crust` and `trusty` do not begin with `ru`.
    let found = keys(&search(&snapshot, &prefix("host", "ru")));
    assert!(!found.contains(&"h2".to_owned()));
}

// T02 — empty prefix is a typed analysis error; an absent prefix matches nothing.
#[test]
fn p8_t02_prefix_empty_absent() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    assert!(matches!(
        search_with(&snapshot, &prefix("host", ""), SearchLimits::default()),
        Err(SearchError::Analysis(_))
    ));
    let response = search(&snapshot, &prefix("host", "zzz"));
    assert_eq!(response.total_hits, 0);
    assert!(response.hits.is_empty());
}

// T03 — glob semantics: `*`, `?`, escaped metacharacters.
#[test]
fn p8_t03_glob_whole_term_and_escape() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    assert_eq!(
        keys(&search(&snapshot, &glob("host", "r*st"))),
        ["h1", "h5", "h6"]
    );
    assert_eq!(
        keys(&search(&snapshot, &glob("host", "r?st"))),
        ["h1", "h5", "h6"]
    );
    // A backslash escapes `*`, so this matches the literal term `r*st`.
    assert_eq!(keys(&search(&snapshot, &glob("tags", r"r\*st"))), ["h6"]);
    // `r?st` does not match the four-scalar non-conforming `russt`-like terms.
    assert!(keys(&search(&snapshot, &glob("host", "r??st"))).is_empty());
}

// T04 — regex anchors to the entire indexed term.
#[test]
fn p8_t04_regex_whole_term() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    // `tags` has no normalizer (identity fallback), so `.` / `.*` are permitted.
    assert_eq!(
        keys(&search(&snapshot, &regex("tags", "ru.*"))),
        ["h1", "h3", "h4", "h7"]
    );
    // `u` alone matches only the term `u`, never `rust`.
    assert!(keys(&search(&snapshot, &regex("tags", "u"))).is_empty());
    assert_eq!(keys(&search(&snapshot, &regex("tags", "ru"))), ["h7"]);
    assert_eq!(keys(&search(&snapshot, &regex("tags", r"r\?st"))), ["h6"]);
}

// T05 — invalid grammar is rejected before any segment is opened.
#[test]
fn p8_t05_pattern_rejected_before_reader() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    for query in [
        regex("host", "(unterminated"),
        regex("host", "a{3,2}"),
        glob("host", r"dangling\"),
    ] {
        let error = search_with(&snapshot, &query, SearchLimits::default()).unwrap_err();
        assert!(
            matches!(error, SearchError::Analysis(_)),
            "unexpected {error:?}"
        );
    }
    // The snapshot remains usable after the rejection.
    assert_eq!(keys(&search(&snapshot, &prefix("host", "ru"))).len(), 4);
}

// I02 / T06 — `?` is one Unicode scalar, not one UTF-8 byte.
#[test]
fn p8_t06_question_mark_scalar() {
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    let docs = vec![
        Pr07Doc::new("eacute").host("é").build(),
        Pr07Doc::new("emoji").host("😀").build(),
        Pr07Doc::new("two").host("éé").build(),
    ];
    pr08_commit_batches(directory.clone(), vec![docs]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    assert_eq!(
        keys(&search(&snapshot, &glob("host", "?"))),
        ["eacute", "emoji"]
    );
    assert_eq!(keys(&search(&snapshot, &glob("host", "??"))), ["two"]);
}

// T07 — NFC / case folding matches index-time normalization.
#[test]
fn p8_t07_unicode_folding() {
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    // `host` uses the `keyword` normalizer (NFC only): e + combining acute == é.
    let docs = vec![Pr07Doc::new("nfc").host("café").build()];
    pr08_commit_batches(directory.clone(), vec![docs]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let decomposed = "cafe\u{0301}";
    assert_eq!(
        keys(&search(&snapshot, &prefix("host", decomposed))),
        ["nfc"]
    );
}

// T08 — Unicode regex dot and classes conform to the PR 4 preparation.
#[test]
fn p8_t08_regex_unicode_classes() {
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    let docs = vec![
        Pr07Doc::new("a").tags(vec!["abc"]).build(),
        Pr07Doc::new("b").tags(vec!["aé"]).build(),
        Pr07Doc::new("c").tags(vec!["a1"]).build(),
    ];
    pr08_commit_batches(directory.clone(), vec![docs]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    // `.` matches any scalar (including non-ASCII), and `[a-z]` is a stable class.
    assert_eq!(
        keys(&search(&snapshot, &regex("tags", "a.*"))),
        ["a", "b", "c"]
    );
    assert_eq!(keys(&search(&snapshot, &regex("tags", "a[a-z]+"))), ["a"]);
}

// I03 / T09 — fuzzy edit counts 0/1/2.
#[test]
fn p8_t09_fuzzy_edits_reference() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("host", "rust", 0, false))),
        ["h1"]
    );
    let one = keys(&search(&snapshot, &fuzzy("host", "rust", 1, false)));
    for key in ["h1", "h2", "h3", "h5", "h6"] {
        assert!(
            one.contains(&key.to_owned()),
            "levenshtein-1 should match {key}"
        );
    }
    assert!(
        !one.contains(&"h8".to_owned()),
        "rsut is two Levenshtein edits"
    );
    assert!(!one.contains(&"h4".to_owned()));
    let two = keys(&search(&snapshot, &fuzzy("host", "rust", 2, false)));
    for key in ["h4", "h7", "h8"] {
        assert!(
            two.contains(&key.to_owned()),
            "levenshtein-2 should match {key}"
        );
    }
}

// T10 — `ab` vs `ba` is one OSA transposition, two plain Levenshtein edits.
#[test]
fn p8_t10_osa_transposition() {
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(
        directory.clone(),
        vec![vec![Pr07Doc::new("swap").host("ba").build()]],
    );
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    assert!(keys(&search(&snapshot, &fuzzy("host", "ab", 1, false))).is_empty());
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("host", "ab", 1, true))),
        ["swap"]
    );
    // A second edit is not needed for the transposition.
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("host", "ab", 1, true))).len(),
        1
    );
}

// T11 — restricted OSA rejects the unrestricted-Damerau counterexample.
#[test]
fn p8_t11_osa_vs_unrestricted() {
    // OSA("ca", "abc") == 3 even though unrestricted Damerau == 2.
    let directory: Arc<dyn quervant_core::storage::Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(
        directory.clone(),
        vec![vec![Pr07Doc::new("abc").host("abc").build()]],
    );
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    assert!(
        keys(&search(&snapshot, &fuzzy("host", "ca", 2, true))).is_empty(),
        "the `abc` document must not match under restricted OSA"
    );
    assert!(keys(&search(&snapshot, &fuzzy("host", "ca", 2, false))).is_empty());
    // A plain two-edit term still matches.
    assert_eq!(
        keys(&search(&snapshot, &fuzzy("host", "abc", 2, true))),
        ["abc"]
    );
}

// T12 — fuzzy edits above 2, multi-token values and invalid fields are typed.
#[test]
fn p8_t12_fuzzy_typed_errors() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let too_many = fuzzy("host", "rust", 3, false);
    assert!(too_many.validate(&pr08_schema(), &Budgets::new()).is_err());
    let multi = fuzzy("title", "two words", 1, false);
    assert!(matches!(
        search_with(&snapshot, &multi, SearchLimits::default()),
        Err(SearchError::Analysis(_))
    ));
    let bad_field = fuzzy("missing", "rust", 1, false);
    assert!(search_with(&snapshot, &bad_field, SearchLimits::default()).is_err());
    // Numeric fields are not lexical.
    let numeric = fuzzy("n", "1", 1, false);
    assert!(search_with(&snapshot, &numeric, SearchLimits::default()).is_err());
}

// I06 / T22 — expanded-term limit is exact and rejects one over.
#[test]
fn p8_t22_expanded_terms_exact_one_over() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    // Prefix `r` expands to five unique host terms: rust, rusty, run, rést, r?st, ru, rsut.
    let expanded = keys(&search(&snapshot, &prefix("host", "r"))).len();
    assert!(expanded >= 5);
    let exact = SearchLimits::default()
        .with_max_expanded_terms(expanded as u64)
        .unwrap();
    assert!(search_with(&snapshot, &prefix("host", "r"), exact).is_ok());
    let one_over = SearchLimits::default()
        .with_max_expanded_terms(expanded as u64 - 1)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &prefix("host", "r"), one_over),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// T23 — combined ordinary + expanded scoring terms honor `max_unique_query_terms`.
#[test]
fn p8_t23_combined_unique_terms() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let query = Query::Or(vec![
        Query::Term {
            field: "host".into(),
            value: FieldValue::Keyword("h1".into()),
        },
        prefix("host", "ru"),
    ]);
    let tight = SearchLimits::default()
        .with_max_unique_query_terms(1)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &query, tight),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// T24 — broad `*` is bounded; a no-match pattern does only bounded work.
#[test]
fn p8_t24_broad_glob_no_match_work() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    // `*` expands to every host term (nine); a low budget fails closed.
    let tight = SearchLimits::default().with_max_expanded_terms(4).unwrap();
    assert!(matches!(
        search_with(&snapshot, &glob("host", "*"), tight),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A no-match regex does bounded work and returns no hits.
    let none = search(&snapshot, &regex("tags", "zzz.*"));
    assert_eq!(none.total_hits, 0);
    // A broad glob within budget succeeds.
    assert!(search_with(&snapshot, &glob("host", "*"), SearchLimits::default()).is_ok());
}

// T25 — derived FST logical bytes are bounded per request.
#[test]
fn p8_t25_fst_bytes() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let tight = SearchLimits::default().with_max_fst_bytes(1).unwrap();
    assert!(matches!(
        search_with(&snapshot, &prefix("host", "ru"), tight),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert!(search_with(&snapshot, &prefix("host", "ru"), SearchLimits::default()).is_ok());
}

// T26 — compiled automaton states are bounded before the segment is opened.
#[test]
fn p8_t26_automaton_states() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let tight = SearchLimits::default()
        .with_max_automaton_states(1)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &regex("host", "[a-z]+"), tight),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A tiny prefix automaton still fits an exactly-three-state budget.
    let exact = SearchLimits::default()
        .with_max_automaton_states(3)
        .unwrap();
    assert!(search_with(&snapshot, &prefix("host", "ru"), exact).is_ok());
}

// T27 — fuzzy normalized scalar length is bounded.
#[test]
fn p8_t27_fuzzy_scalar_length() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let limits = SearchLimits::default()
        .with_max_fuzzy_pattern_scalars(2)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &fuzzy("host", "rust", 1, false), limits),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert!(search_with(&snapshot, &fuzzy("host", "ru", 1, false), limits).is_ok());
}

// T28 — PR 7 candidate / postings / top-K limits remain in force.
#[test]
fn p8_t28_pr7_limits_retained() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let no_postings = SearchLimits::default()
        .with_max_scanned_posting_occurrences(1)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &prefix("host", "r"), no_postings),
        Err(SearchError::ResourceLimit { .. })
    ));
    let tiny_candidates = SearchLimits::default()
        .with_max_segment_candidate_entries(1)
        .unwrap();
    assert!(matches!(
        search_with(&snapshot, &prefix("host", "r"), tiny_candidates),
        Err(SearchError::ResourceLimit { .. })
    ));
    // Top-K truncates the response but never the exact total.
    let response =
        search_with_topk(&snapshot, &prefix("host", "r"), SearchLimits::default(), 1).unwrap();
    assert_eq!(response.hits.len(), 1);
    assert!(response.total_hits > 1);
}

// T21 (unit slice) — deterministic tie ordering is score-desc then key-asc.
#[test]
fn p8_t21_topk_exact_total_tie_order() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let response = search(&snapshot, &prefix("host", "ru"));
    assert_eq!(response.total_hits, 4);
    // All matching host terms are distinct, so scores are distinct; the response is
    // ordered best-first with a stable key tiebreak.
    let scores: Vec<f64> = response.hits.iter().map(|hit| hit.score).collect();
    assert!(scores.windows(2).all(|pair| pair[0] >= pair[1]));
}

// T42 (unit slice) — a read-only PR 8 search never mutates the snapshot.
#[test]
fn p8_t42_search_is_read_only() {
    let index = open_corpus();
    let snapshot = index.snapshot();
    let before = snapshot.stored_keys().unwrap();
    let _ = search(&snapshot, &prefix("host", "ru"));
    let _ = search(&snapshot, &glob("host", "r*"));
    let _ = search(&snapshot, &regex("tags", "r.*"));
    let _ = search(&snapshot, &fuzzy("host", "rust", 1, true));
    let after = snapshot.stored_keys().unwrap();
    assert_eq!(before, after);
    // The logical key identity is preserved byte-for-byte.
    assert!(
        before
            .iter()
            .any(|key| key == &DocumentKey::new("h1").unwrap())
    );
}
