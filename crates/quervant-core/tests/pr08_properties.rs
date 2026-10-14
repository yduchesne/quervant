//! PR 8 property and oracle tests (T09–T11, T13–T21).
//!
//! The independent oracle scans fixture analyzer tokens and computes
//! `n`/`df`/`dl`/`avgdl`, BM25 arithmetic and pattern membership itself. It never
//! calls the production `automaton`, `expand`, `compute_stats` or `bm25`.

mod common;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use common::{Pr07Doc, pr08_commit_batches, pr08_registry, pr08_schema};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

// ---------------------------------------------------------------------------
// Independent oracle
// ---------------------------------------------------------------------------

fn ref_bm25(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> f64 {
    if tf == 0 || n == 0 || avgdl <= 0.0 {
        return 0.0;
    }
    let (k1, b) = (1.2_f64, 0.75_f64);
    let idf = (1.0 + (n as f64 - df as f64 + 0.5) / (df as f64 + 0.5)).ln();
    let tf = tf as f64;
    let dl = dl as f64;
    idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))
}

fn ref_levenshtein(a: &[char], b: &[char]) -> usize {
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let mut cur = vec![0usize; b.len() + 1];
        cur[0] = i;
        for j in 1..=b.len() {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            cur[j] = (prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + cost);
        }
        prev = cur;
    }
    prev[b.len()]
}

fn ref_osa(a: &[char], b: &[char]) -> usize {
    let mut d = vec![vec![0usize; b.len() + 1]; a.len() + 1];
    for (i, row) in d.iter_mut().enumerate() {
        row[0] = i;
    }
    for (j, cell) in d[0].iter_mut().enumerate() {
        *cell = j;
    }
    for i in 1..=a.len() {
        for j in 1..=b.len() {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            let mut best = (d[i - 1][j] + 1)
                .min(d[i][j - 1] + 1)
                .min(d[i - 1][j - 1] + cost);
            if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                best = best.min(d[i - 2][j - 2] + 1);
            }
            d[i][j] = best;
        }
    }
    d[a.len()][b.len()]
}

/// Memoized reference glob matcher over Unicode scalars.
fn ref_glob(pattern: &[char], term: &[char]) -> bool {
    let mut memo: BTreeMap<(usize, usize), bool> = BTreeMap::new();
    fn go(
        pattern: &[char],
        term: &[char],
        p: usize,
        t: usize,
        memo: &mut BTreeMap<(usize, usize), bool>,
    ) -> bool {
        if let Some(value) = memo.get(&(p, t)) {
            return *value;
        }
        let result = if p == pattern.len() {
            t == term.len()
        } else {
            match pattern[p] {
                '*' => {
                    go(pattern, term, p + 1, t, memo)
                        || (t < term.len() && go(pattern, term, p, t + 1, memo))
                }
                '?' => t < term.len() && go(pattern, term, p + 1, t + 1, memo),
                ch => t < term.len() && term[t] == ch && go(pattern, term, p + 1, t + 1, memo),
            }
        };
        memo.insert((p, t), result);
        result
    }
    go(pattern, term, 0, 0, &mut memo)
}

/// The oracle's per-field postings and lengths for one corpus.
struct FieldOracle {
    n: u64,
    dictionary: Vec<String>,
    df: BTreeMap<String, u64>,
    tf: Vec<BTreeMap<String, u64>>,
    dl: Vec<u64>,
}

impl FieldOracle {
    fn build(n: u64, docs: &[Vec<String>]) -> Self {
        let mut df: BTreeMap<String, u64> = BTreeMap::new();
        let mut tf: Vec<BTreeMap<String, u64>> = Vec::new();
        let mut dl: Vec<u64> = Vec::new();
        let mut dictionary: BTreeSet<String> = BTreeSet::new();
        for values in docs {
            let mut per_doc: BTreeMap<String, u64> = BTreeMap::new();
            for value in values {
                dictionary.insert(value.clone());
                *per_doc.entry(value.clone()).or_insert(0) += 1;
            }
            for term in per_doc.keys() {
                *df.entry(term.clone()).or_insert(0) += 1;
            }
            dl.push(values.len() as u64);
            tf.push(per_doc);
        }
        Self {
            n,
            dictionary: dictionary.into_iter().collect(),
            df,
            tf,
            dl,
        }
    }

    fn avgdl(&self) -> f64 {
        if self.n == 0 {
            0.0
        } else {
            self.dl.iter().sum::<u64>() as f64 / self.n as f64
        }
    }

    /// Expected ordered `(key, score)` for a single positive expanded term set.
    fn expected_scores(&self, keys: &[String], matched: &BTreeSet<String>) -> Vec<(String, f64)> {
        let avgdl = self.avgdl();
        let n = self.n;
        let mut rows: Vec<(String, f64)> = Vec::new();
        for (doc, key) in keys.iter().enumerate() {
            let mut score = 0.0;
            for term in matched {
                let Some(tf) = self.tf[doc].get(term).copied() else {
                    continue;
                };
                let df = self.df.get(term).copied().unwrap_or(0);
                score += ref_bm25(tf, df, n, self.dl[doc], avgdl);
            }
            if score > 0.0 {
                rows.push((key.clone(), score));
            }
        }
        rows.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        rows
    }
}

fn engine_search(snapshot: &ReaderSnapshot, query: &Query) -> SearchResponse {
    LexicalSearcher::new(
        snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        query,
        TopK::new(1_000).expect("topk"),
        &Budgets::new(),
        &NeverCancel,
    )
    .expect("search")
}

fn engine_rows(response: &SearchResponse) -> Vec<(String, f64)> {
    response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score))
        .collect()
}

// ---------------------------------------------------------------------------
// Seeded corpus generator
// ---------------------------------------------------------------------------

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }

    fn range(&mut self, max: usize) -> usize {
        if max == 0 {
            0
        } else {
            (self.next() as usize) % max
        }
    }
}

fn random_term(rng: &mut Rng, alphabet: &[char]) -> String {
    let len = 1 + rng.range(4);
    (0..len)
        .map(|_| alphabet[rng.range(alphabet.len())])
        .collect()
}

fn commit_segmented(docs: Vec<(String, Vec<String>)>) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let segment_count = 1 + docs.len().min(3) % 4;
    let mut batches: Vec<Vec<quervant_core::contract::document::Document>> =
        (0..segment_count).map(|_| Vec::new()).collect();
    for (index, (key, tags)) in docs.iter().enumerate() {
        let mut doc = Pr07Doc::new(Box::leak(key.clone().into_boxed_str()));
        let leak: &'static [&'static str] = Box::leak(
            tags.iter()
                .map(|tag| -> &'static str { Box::leak(tag.clone().into_boxed_str()) })
                .collect::<Vec<_>>()
                .into_boxed_slice(),
        );
        if !leak.is_empty() {
            doc = doc.tags(leak.to_vec());
        }
        batches[index % segment_count].push(doc.build());
    }
    pr08_commit_batches(directory.clone(), batches);
    Index::open_existing(directory, pr08_schema(), pr08_registry()).expect("reopen")
}

/// T09–T11 / T13–T17 — seeded operator parity against the independent oracle.
#[test]
fn p8_properties_seeded_operator_parity() {
    let seed: u64 = 0x0800_0000_0000_0042;
    let mut rng = Rng(seed);
    let alphabet = ['a', 'b', 'c', 'd', 'é'];
    for iteration in 0..24 {
        let doc_count = rng.range(60);
        let mut docs: Vec<(String, Vec<String>)> = Vec::new();
        for doc in 0..doc_count {
            let values = rng.range(4);
            let tags: Vec<String> = (0..values)
                .map(|_| random_term(&mut rng, &alphabet))
                .collect();
            docs.push((format!("d{doc:03}"), tags));
        }
        let keys: Vec<String> = docs.iter().map(|(key, _)| key.clone()).collect();
        let values: Vec<Vec<String>> = docs.iter().map(|(_, tags)| tags.clone()).collect();
        let oracle = FieldOracle::build(docs.len() as u64, &values);
        if oracle.dictionary.is_empty() {
            continue;
        }
        let index = commit_segmented(docs);
        let snapshot = index.snapshot();

        // Prefix, glob, regex and fuzzy over randomly selected dictionary terms.
        let pick = &oracle.dictionary[rng.range(oracle.dictionary.len())];
        let prefix_chars: Vec<char> = pick
            .chars()
            .take(1 + rng.range(pick.chars().count()))
            .collect();
        let prefix: String = prefix_chars.iter().collect();
        let matched: BTreeSet<String> = oracle
            .dictionary
            .iter()
            .filter(|term| term.starts_with(&prefix))
            .cloned()
            .collect();
        let query = Query::Prefix {
            field: "tags".into(),
            prefix: prefix.clone(),
        };
        assert_parity(
            &snapshot,
            &query,
            &oracle.expected_scores(&keys, &matched),
            seed,
            iteration,
            &format!("prefix {prefix:?}"),
        );

        // Glob: replace up to two scalars with `*`/`?`.
        let mut glob: Vec<char> = pick.chars().collect();
        let mutations = rng.range(3);
        for _ in 0..mutations {
            if glob.is_empty() {
                break;
            }
            let position = rng.range(glob.len());
            glob[position] = if rng.range(2) == 0 { '*' } else { '?' };
        }
        let glob_string: String = glob.iter().collect();
        let matched: BTreeSet<String> = oracle
            .dictionary
            .iter()
            .filter(|term| ref_glob(&glob, &term.chars().collect::<Vec<_>>()))
            .cloned()
            .collect();
        let query = Query::Glob {
            field: "tags".into(),
            pattern: glob_string.clone(),
        };
        assert_parity(
            &snapshot,
            &query,
            &oracle.expected_scores(&keys, &matched),
            seed,
            iteration,
            &format!("glob {glob_string:?}"),
        );

        // Regex: literal, prefix-`.*`, or a stable class, anchored to the whole term.
        let patterns = [
            regex::escape(pick),
            format!("{}.*", regex::escape(&prefix)),
            "[abcd]+".to_owned(),
        ];
        let pattern = &patterns[rng.range(patterns.len())];
        let compiled = regex::Regex::new(&format!("^(?:{pattern})$")).expect("oracle regex");
        let matched: BTreeSet<String> = oracle
            .dictionary
            .iter()
            .filter(|term| compiled.is_match(term))
            .cloned()
            .collect();
        let query = Query::Regex {
            field: "tags".into(),
            pattern: pattern.clone(),
        };
        assert_parity(
            &snapshot,
            &query,
            &oracle.expected_scores(&keys, &matched),
            seed,
            iteration,
            &format!("regex {pattern:?}"),
        );

        // Fuzzy over scalar values.
        let fuzzy_value: String = pick.clone();
        let max_edits = rng.range(3) as u8;
        let transpositions = rng.range(2) == 0;
        let query_chars: Vec<char> = fuzzy_value.chars().collect();
        let matched: BTreeSet<String> = oracle
            .dictionary
            .iter()
            .filter(|term| {
                let term_chars: Vec<char> = term.chars().collect();
                let distance = if transpositions {
                    ref_osa(&query_chars, &term_chars)
                } else {
                    ref_levenshtein(&query_chars, &term_chars)
                };
                distance <= usize::from(max_edits)
            })
            .cloned()
            .collect();
        let query = Query::Fuzzy {
            field: "tags".into(),
            value: fuzzy_value.clone(),
            max_edits,
            transpositions,
        };
        assert_parity(
            &snapshot,
            &query,
            &oracle.expected_scores(&keys, &matched),
            seed,
            iteration,
            &format!("fuzzy {fuzzy_value:?} e{max_edits} t{transpositions}"),
        );
    }
}

fn assert_parity(
    snapshot: &ReaderSnapshot,
    query: &Query,
    expected: &[(String, f64)],
    seed: u64,
    iteration: usize,
    label: &str,
) {
    let response = engine_search(snapshot, query);
    let actual = engine_rows(&response);
    let context = || format!("seed={seed:#x} iteration={iteration} {label} query={query:?}");
    assert_eq!(
        response.total_hits as usize,
        expected.len(),
        "total hits mismatch: {}",
        context()
    );
    assert_eq!(
        actual.len(),
        expected.len(),
        "hit count mismatch: {}",
        context()
    );
    for ((actual_key, actual_score), (expected_key, expected_score)) in actual.iter().zip(expected)
    {
        assert_eq!(actual_key, expected_key, "key mismatch: {}", context());
        assert!(
            (actual_score - expected_score).abs() < 1e-9,
            "score mismatch for {actual_key}: {actual_score} vs {expected_score}: {}",
            context()
        );
    }
}

// ---------------------------------------------------------------------------
// Targeted multi-leaf invariants
// ---------------------------------------------------------------------------

fn committed(docs: Vec<Pr07Doc<'static>>) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(
        directory.clone(),
        vec![docs.into_iter().map(|d| d.build()).collect()],
    );
    Index::open_existing(directory, pr08_schema(), pr08_registry()).expect("reopen")
}

fn term(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn prefix(field: &str, value: &str) -> Query {
    Query::Prefix {
        field: field.to_owned(),
        prefix: value.to_owned(),
    }
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

fn score_of(response: &SearchResponse, key: &str) -> f64 {
    response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == key)
        .map_or(f64::NAN, |hit| hit.score)
}

// T13 — a term present in two segments uses the snapshot-wide df/n.
#[test]
fn p8_t13_global_df_segments() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    pr08_commit_batches(
        directory.clone(),
        vec![
            vec![
                Pr07Doc::new("a").tags(vec!["rust", "rust"]).build(),
                Pr07Doc::new("b").tags(vec!["rust"]).build(),
            ],
            vec![
                Pr07Doc::new("c").tags(vec!["rust", "other"]).build(),
                Pr07Doc::new("d").tags(vec!["python"]).build(),
            ],
        ],
    );
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let response = engine_search(&snapshot, &term("tags", "rust"));
    assert_eq!(response.total_hits, 3);
    // `n` and `df` are global (4 and 3), so scores match a single-segment oracle.
    let oracle = FieldOracle::build(
        4,
        &[
            vec!["rust".into(), "rust".into()],
            vec!["rust".into()],
            vec!["rust".into(), "other".into()],
            vec!["python".into()],
        ],
    );
    let expected = oracle.expected_scores(
        &["a".into(), "b".into(), "c".into(), "d".into()],
        &["rust".to_owned()].into_iter().collect(),
    );
    for (key, score) in expected {
        assert!((score_of(&response, &key) - score).abs() < 1e-9, "{key}");
    }
}

// T15/T16 — overlapping positive leaves never double count a (field, term).
#[test]
fn p8_t15_t16_overlap_dedup() {
    let index = committed(vec![
        Pr07Doc::new("a").tags(vec!["rust", "other"]),
        Pr07Doc::new("b").tags(vec!["rusty"]),
    ]);
    let snapshot = index.snapshot();
    let single = engine_search(&snapshot, &term("tags", "rust"));
    let prefix_only = engine_search(&snapshot, &prefix("tags", "rus"));
    let overlap = engine_search(
        &snapshot,
        &Query::Or(vec![
            term("tags", "rust"),
            prefix("tags", "rus"),
            Query::Glob {
                field: "tags".into(),
                pattern: "ru*".into(),
            },
        ]),
    );
    // Membership is the union: `a` matches all three, `b` only the patterns.
    assert_eq!(overlap.total_hits, 2);
    // `a`'s `rust` contribution is counted exactly once despite three leaves.
    assert!((score_of(&overlap, "a") - score_of(&single, "a")).abs() < 1e-9);
    // `b` is scored from the expanded `rusty` term supplied by the pattern leaf.
    assert!((score_of(&overlap, "b") - score_of(&prefix_only, "b")).abs() < 1e-9);
}

// T17 — a zero-expansion leaf behaves as an empty branch, never MatchAll.
#[test]
fn p8_t17_zero_expansion_or_semantics() {
    let index = committed(vec![Pr07Doc::new("a").tags(vec!["rust"])]);
    let snapshot = index.snapshot();
    let plain = engine_search(&snapshot, &term("tags", "rust"));
    let with_empty = engine_search(
        &snapshot,
        &Query::Or(vec![prefix("tags", "zzz"), term("tags", "rust")]),
    );
    assert_eq!(keys(&plain), keys(&with_empty));
    assert_eq!(plain.total_hits, with_empty.total_hits);
    // A conjunction with a zero-expansion leaf matches nothing.
    let conjunction = engine_search(
        &snapshot,
        &Query::And(vec![prefix("tags", "zzz"), term("tags", "rust")]),
    );
    assert_eq!(conjunction.total_hits, 0);
}

// T18 — AND/OR/NOT/NOT NOT membership and scoring eligibility.
#[test]
fn p8_t18_boolean_combinations() {
    let index = committed(vec![
        Pr07Doc::new("a").tags(vec!["rust", "fast"]),
        Pr07Doc::new("b").tags(vec!["rust"]),
        Pr07Doc::new("c").tags(vec!["python"]),
    ]);
    let snapshot = index.snapshot();
    assert_eq!(
        keys(&engine_search(
            &snapshot,
            &Query::And(vec![term("tags", "rust"), term("tags", "fast")])
        )),
        ["a"]
    );
    assert_eq!(
        keys(&engine_search(
            &snapshot,
            &Query::Or(vec![term("tags", "fast"), term("tags", "python")])
        )),
        ["a", "c"]
    );
    assert_eq!(
        keys(&engine_search(
            &snapshot,
            &Query::Not(Box::new(term("tags", "rust")))
        )),
        ["c"]
    );
    // NOT NOT restores positive scoring eligibility.
    let doubled = engine_search(
        &snapshot,
        &Query::Not(Box::new(Query::Not(Box::new(prefix("tags", "ru"))))),
    );
    assert_eq!(keys(&doubled), ["a", "b"]);
    assert!(doubled.hits.iter().all(|hit| hit.score > 0.0));
}

// T19 — a pure-negative query returns zero scores.
#[test]
fn p8_t19_negative_only_zero() {
    let index = committed(vec![
        Pr07Doc::new("a").tags(vec!["rust"]),
        Pr07Doc::new("b").tags(vec!["python"]),
    ]);
    let snapshot = index.snapshot();
    let response = engine_search(&snapshot, &Query::Not(Box::new(prefix("tags", "rust"))));
    assert_eq!(keys(&response), ["b"]);
    assert!(response.hits.iter().all(|hit| hit.score == 0.0));
}

// T20 — phrase AND prefix combine across fields.
#[test]
fn p8_t20_phrase_and_prefix() {
    let index = committed(vec![
        Pr07Doc::new("a")
            .title("quick brown fox")
            .host("rust.example"),
        Pr07Doc::new("b").title("quick fox").host("rust.example"),
        Pr07Doc::new("c")
            .title("quick brown fox")
            .host("python.example"),
    ]);
    let snapshot = index.snapshot();
    let response = engine_search(
        &snapshot,
        &Query::And(vec![
            Query::Phrase {
                field: "title".into(),
                terms: vec!["quick".into(), "brown".into()],
            },
            prefix("host", "rust"),
        ]),
    );
    assert_eq!(keys(&response), ["a"]);
    assert!(score_of(&response, "a") > 0.0);
}

// T21 — TopK truncation preserves exact totals and deterministic ties.
#[test]
fn p8_t21_topk_exact_total_tie_order() {
    let index = committed(vec![
        Pr07Doc::new("a").tags(vec!["rust"]),
        Pr07Doc::new("b").tags(vec!["rust"]),
        Pr07Doc::new("c").tags(vec!["rust"]),
    ]);
    let snapshot = index.snapshot();
    let all = engine_search(&snapshot, &term("tags", "rust"));
    assert_eq!(all.total_hits, 3);
    // All documents have identical tf/dl, hence equal scores; ties order by key.
    assert_eq!(keys(&all), ["a", "b", "c"]);
    let one = LexicalSearcher::new(
        &snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        &term("tags", "rust"),
        TopK::new(1).unwrap(),
        &Budgets::new(),
        &NeverCancel,
    )
    .unwrap();
    assert_eq!(one.total_hits, 3, "total is exact, not truncated");
    assert_eq!(one.hits.len(), 1);
    assert_eq!(one.hits[0].key.as_str(), "a");
}
