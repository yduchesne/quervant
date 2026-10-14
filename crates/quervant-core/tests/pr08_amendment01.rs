//! PR 8 Amendment 01 — resource-accounting integration tests (A1-T01–T27).
//!
//! Public-path tests exercise the real `IndexWriter -> commit ->
//! Index::open_existing -> ReaderSnapshot/PIT -> LexicalSearcher` path over
//! `MemoryDirectory` and `FsDirectory`. The exact/one-over byte and work
//! thresholds are found by monotonic binary search over the public
//! `SearchLimits` setters; module-level tests cover the private intern/FST/budget
//! internals and the test-only "no build on failure" counter.

mod common;

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

use common::{Pr07Doc, TempDir, pr08_commit_batches, pr08_registry, pr08_schema};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};
use sha2::Digest as _;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

fn search(
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

/// Smallest monotonic `limit` for which `ok(limit)` is true (1..=hi).
fn min_threshold(hi: u64, mut ok: impl FnMut(u64) -> bool) -> u64 {
    assert!(ok(hi), "the generous upper bound must succeed");
    let mut lo = 1u64;
    let mut high = hi;
    while lo < high {
        let mid = lo + (high - lo) / 2;
        if ok(mid) {
            high = mid;
        } else {
            lo = mid + 1;
        }
    }
    lo
}

fn corpus() -> Vec<quervant_core::contract::document::Document> {
    vec![
        Pr07Doc::new("h1").tags(vec!["rust"]).host("rust").build(),
        Pr07Doc::new("h2").tags(vec!["rusty"]).host("crust").build(),
        Pr07Doc::new("h3").tags(vec!["run"]).host("run").build(),
        Pr07Doc::new("h4")
            .tags(vec!["python"])
            .host("python")
            .build(),
    ]
}

// ---------------------------------------------------------------------------
// A1-T01/T02 — FST construction work is charged before build
// ---------------------------------------------------------------------------

#[test]
fn a1_t01_t02_work_limit_is_charged_and_prevents_partial_success() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let query = prefix("tags", "rust");

    // A generous budget succeeds.
    let ok = search(&snapshot, &query, SearchLimits::default()).unwrap();
    assert_eq!(keys(&ok), ["h1", "h2"]);

    // The minimum work budget that succeeds is the deterministic charged amount.
    let threshold = min_threshold(50_000_000, |value| {
        SearchLimits::default()
            .with_max_total_work_units(value)
            .ok()
            .and_then(|limits| search(&snapshot, &query, limits).ok())
            .is_some()
    });
    assert!(threshold > 1);
    let below = SearchLimits::default()
        .with_max_total_work_units(threshold - 1)
        .unwrap();
    assert!(matches!(
        search(&snapshot, &query, below),
        Err(SearchError::ResourceLimit { .. })
    ));
    // No partial response is produced on the failure path.
    let above = SearchLimits::default()
        .with_max_total_work_units(threshold)
        .unwrap();
    assert_eq!(
        keys(&search(&snapshot, &query, above).unwrap()),
        ["h1", "h2"]
    );
}

// ---------------------------------------------------------------------------
// A1-T03 — cumulative work across multiple fields
// ---------------------------------------------------------------------------

#[test]
fn a1_t03_cumulative_work_across_fields() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let both = Query::Or(vec![prefix("tags", "r"), prefix("host", "r")]);
    let threshold = min_threshold(50_000_000, |value| {
        SearchLimits::default()
            .with_max_total_work_units(value)
            .ok()
            .and_then(|limits| search(&snapshot, &both, limits).ok())
            .is_some()
    });
    assert!(matches!(
        search(
            &snapshot,
            &both,
            SearchLimits::default()
                .with_max_total_work_units(threshold - 1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert!(
        search(
            &snapshot,
            &both,
            SearchLimits::default()
                .with_max_total_work_units(threshold)
                .unwrap()
        )
        .is_ok()
    );
}

// ---------------------------------------------------------------------------
// A1-T05/T06/T07 — FST retained-memory reservation is cumulative and conservative
// ---------------------------------------------------------------------------

#[test]
fn a1_t05_t06_fst_budget_exact_and_one_over() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let query = prefix("tags", "r");
    let threshold = min_threshold(512 * 1024 * 1024, |value| {
        SearchLimits::default()
            .with_max_fst_bytes(value)
            .ok()
            .and_then(|limits| search(&snapshot, &query, limits).ok())
            .is_some()
    });
    assert!(threshold > 1);
    assert!(matches!(
        search(
            &snapshot,
            &query,
            SearchLimits::default()
                .with_max_fst_bytes(threshold - 1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert!(
        search(
            &snapshot,
            &query,
            SearchLimits::default()
                .with_max_fst_bytes(threshold)
                .unwrap()
        )
        .is_ok()
    );
}

#[test]
fn a1_t07_two_fsts_share_the_cumulative_budget() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let one_field = prefix("tags", "r");
    let two_fields = Query::Or(vec![prefix("tags", "r"), prefix("host", "r")]);
    let one = min_threshold(512 * 1024 * 1024, |value| {
        SearchLimits::default()
            .with_max_fst_bytes(value)
            .ok()
            .and_then(|limits| search(&snapshot, &one_field, limits).ok())
            .is_some()
    });
    // A single FST fits at `one`; two distinct field FSTs do not.
    assert!(matches!(
        search(
            &snapshot,
            &two_fields,
            SearchLimits::default().with_max_fst_bytes(one).unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// A1-T12/T13 — retained expansion bytes are exact and fail closed
// ---------------------------------------------------------------------------

#[test]
fn a1_t12_t13_expansion_bytes_exact_and_one_over() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let query = prefix("tags", "ru");
    let threshold = min_threshold(512 * 1024 * 1024, |value| {
        SearchLimits::default()
            .with_max_expansion_bytes(value)
            .ok()
            .and_then(|limits| search(&snapshot, &query, limits).ok())
            .is_some()
    });
    assert!(threshold > 1);
    let below = SearchLimits::default()
        .with_max_expansion_bytes(threshold - 1)
        .unwrap();
    assert!(matches!(
        search(&snapshot, &query, below),
        Err(SearchError::ResourceLimit { .. })
    ));
    // Exactly at the threshold the result is complete and identical.
    let at = SearchLimits::default()
        .with_max_expansion_bytes(threshold)
        .unwrap();
    assert_eq!(
        keys(&search(&snapshot, &query, at).unwrap()),
        keys(&search(&snapshot, &query, SearchLimits::default()).unwrap())
    );
}

// ---------------------------------------------------------------------------
// A1-T14/T15 — occurrence amplification fails by bytes, not by unique terms
// ---------------------------------------------------------------------------

/// 20 distinct multi-term leaves that all match the same 30 `tags` terms.
fn amplifying_query() -> Query {
    let mut leaves = Vec::new();
    for value in ["p", "pr", "pre", "pref", "prefi", "prefix"] {
        leaves.push(prefix("tags", value));
    }
    for pattern in ["p*", "pr*", "pre*", "pref*", "prefi*", "prefix*"] {
        leaves.push(Query::Glob {
            field: "tags".into(),
            pattern: pattern.to_owned(),
        });
    }
    for pattern in ["p.*", "pr.*", "pre.*", "pref.*", "prefi.*", "prefix.*"] {
        leaves.push(Query::Regex {
            field: "tags".into(),
            pattern: pattern.to_owned(),
        });
    }
    leaves.push(Query::Regex {
        field: "tags".into(),
        pattern: "p.+".into(),
    });
    leaves.push(Query::Regex {
        field: "tags".into(),
        pattern: "p.{1,}.*".into(),
    });
    assert_eq!(leaves.len(), 20);
    Query::Or(leaves)
}

fn amplification_index() -> Index {
    let directory = memory();
    let mut batches = Vec::new();
    for segment in 0..20 {
        let mut batch = Vec::new();
        for i in 0..30 {
            let key = format!("s{segment:02}_{i:02}");
            let term = format!("prefix{i:02}");
            batch.push(
                Pr07Doc::new(Box::leak(key.into_boxed_str()))
                    .tags(vec![Box::leak(term.into_boxed_str())])
                    .build(),
            );
        }
        batches.push(batch);
    }
    pr08_commit_batches(Arc::clone(&directory), batches);
    Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap()
}

#[test]
fn a1_t14_occurrence_amplification_fails_by_bytes() {
    let index = amplification_index();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 20);
    let query = amplifying_query();
    // 30 unique expanded terms produce 12,000 final-step computations across
    // 20 segments x 20 leaves; the byte budget fails even though the unique-term
    // limit is exactly satisfied.
    let constrained = SearchLimits::default()
        .with_max_expanded_terms(30)
        .unwrap()
        .with_max_expansion_bytes(5_000)
        .unwrap();
    assert!(matches!(
        search(&snapshot, &query, constrained),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A sufficient byte budget returns the complete result.
    let generous = SearchLimits::default()
        .with_max_expanded_terms(30)
        .unwrap()
        .with_max_expansion_bytes(512 * 1024 * 1024)
        .unwrap();
    let response = search(&snapshot, &query, generous).unwrap();
    // `total_hits` is exact even though the response window is 100.
    assert_eq!(response.total_hits, 600);
}

// ---------------------------------------------------------------------------
// A1-T17/T18 — failure is typed, then the same snapshot recovers
// ---------------------------------------------------------------------------

#[test]
fn a1_t17_t18_no_partial_results_and_recovery() {
    let index = amplification_index();
    let snapshot = index.snapshot();
    let query = amplifying_query();
    let constrained = SearchLimits::default()
        .with_max_expansion_bytes(5_000)
        .unwrap();
    assert!(matches!(
        search(&snapshot, &query, constrained),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A subsequent query on the same immutable snapshot succeeds.
    let recovery = search(
        &snapshot,
        &prefix("tags", "prefix00"),
        SearchLimits::default(),
    )
    .unwrap();
    assert_eq!(recovery.total_hits, 20);
}

// ---------------------------------------------------------------------------
// A1-T19 — cancellation mid-expansion then recovery
// ---------------------------------------------------------------------------

struct CancelAfter(std::cell::Cell<u32>);

impl quervant_core::analysis::Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let left = self.0.get();
        if left == 0 {
            true
        } else {
            self.0.set(left - 1);
            false
        }
    }
}

#[test]
fn a1_t19_cancellation_mid_expansion_then_recovery() {
    let index = amplification_index();
    let snapshot = index.snapshot();
    let query = amplifying_query();
    let cancel = CancelAfter(std::cell::Cell::new(3));
    let result = LexicalSearcher::new(
        &snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(&query, TopK::new(100).unwrap(), &Budgets::new(), &cancel);
    assert!(matches!(result, Err(SearchError::Cancelled)));
    let recovery = LexicalSearcher::new(
        &snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        &prefix("tags", "prefix00"),
        TopK::new(100).unwrap(),
        &Budgets::new(),
        &NeverCancel,
    )
    .unwrap();
    assert_eq!(recovery.total_hits, 20);
}

// ---------------------------------------------------------------------------
// A1-T20 — FsDirectory is never written by a failing expansion; PIT is immutable
// ---------------------------------------------------------------------------

fn hash_tree(root: &Path) -> BTreeMap<String, String> {
    fn walk(root: &Path, dir: &Path, out: &mut BTreeMap<String, String>) {
        for entry in std::fs::read_dir(dir).expect("read_dir") {
            let entry = entry.expect("entry");
            let path = entry.path();
            if entry.file_type().expect("type").is_dir() {
                walk(root, &path, out);
            } else {
                let relative = path
                    .strip_prefix(root)
                    .expect("relative")
                    .to_string_lossy()
                    .into_owned();
                let digest = sha2::Sha256::digest(std::fs::read(&path).expect("read"));
                use std::fmt::Write as _;
                let mut hex = String::new();
                for byte in digest {
                    write!(hex, "{byte:02x}").expect("write");
                }
                out.insert(relative, hex);
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    out
}

#[test]
fn a1_t20_fs_failing_expansion_is_read_only() {
    let temp = TempDir::new("a1-t20");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(temp.path()).unwrap());
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    drop(directory);
    let before = hash_tree(temp.path());

    let index =
        Index::open_existing(fs_directory(temp.path()), pr08_schema(), pr08_registry()).unwrap();
    let pinned = index.pin().expect("pin");
    let snapshot = Arc::clone(pinned.snapshot());
    let constrained = SearchLimits::default().with_max_expansion_bytes(1).unwrap();
    assert!(matches!(
        search(&snapshot, &prefix("tags", "ru"), constrained),
        Err(SearchError::ResourceLimit { .. })
    ));
    // The pinned snapshot still serves a normal query.
    assert_eq!(
        search(&snapshot, &prefix("tags", "ru"), SearchLimits::default())
            .unwrap()
            .total_hits,
        3
    );
    drop(snapshot);
    drop(index);
    let after = hash_tree(temp.path());
    assert_eq!(
        before, after,
        "failing search must not rewrite committed files"
    );
}

fn fs_directory(path: &Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("fs directory"))
}

// ---------------------------------------------------------------------------
// A1-T21 — operator membership/BMI unchanged against an independent oracle
// ---------------------------------------------------------------------------

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

fn ref_glob(pattern: &[char], term: &[char]) -> bool {
    fn go(
        p: &[char],
        t: &[char],
        i: usize,
        j: usize,
        memo: &mut BTreeMap<(usize, usize), bool>,
    ) -> bool {
        if let Some(value) = memo.get(&(i, j)) {
            return *value;
        }
        let result = if i == p.len() {
            j == t.len()
        } else {
            match p[i] {
                '*' => go(p, t, i + 1, j, memo) || (j < t.len() && go(p, t, i, j + 1, memo)),
                '?' => j < t.len() && go(p, t, i + 1, j + 1, memo),
                ch => j < t.len() && t[j] == ch && go(p, t, i + 1, j + 1, memo),
            }
        };
        memo.insert((i, j), result);
        result
    }
    go(pattern, term, 0, 0, &mut BTreeMap::new())
}

#[test]
fn a1_t21_operator_membership_matches_oracle() {
    let directory = memory();
    let docs = vec![
        Pr07Doc::new("a").tags(vec!["rust"]).build(),
        Pr07Doc::new("b").tags(vec!["crust"]).build(),
        Pr07Doc::new("c").tags(vec!["rusty"]).build(),
        Pr07Doc::new("d").tags(vec!["run"]).build(),
    ];
    let terms = ["rust", "crust", "rusty", "run"];
    pr08_commit_batches(Arc::clone(&directory), vec![docs]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();

    // Prefix.
    let response = search(&snapshot, &prefix("tags", "rust"), SearchLimits::default()).unwrap();
    let expected: Vec<String> = terms
        .iter()
        .enumerate()
        .filter(|(_, term)| term.starts_with("rust"))
        .map(|(i, _)| ["a", "b", "c", "d"][i].to_owned())
        .collect();
    assert_eq!(keys(&response), expected);

    // Glob.
    let pattern: Vec<char> = "r?st".chars().collect();
    let response = search(
        &snapshot,
        &Query::Glob {
            field: "tags".into(),
            pattern: "r?st".into(),
        },
        SearchLimits::default(),
    )
    .unwrap();
    let expected: Vec<String> = terms
        .iter()
        .enumerate()
        .filter(|(_, term)| ref_glob(&pattern, &term.chars().collect::<Vec<_>>()))
        .map(|(i, _)| ["a", "b", "c", "d"][i].to_owned())
        .collect();
    assert_eq!(keys(&response), expected);

    // Regex (whole term).
    let regex = regex::Regex::new(r"^r.*t$").unwrap();
    let response = search(
        &snapshot,
        &Query::Regex {
            field: "tags".into(),
            pattern: "r.*t".into(),
        },
        SearchLimits::default(),
    )
    .unwrap();
    let expected: Vec<String> = terms
        .iter()
        .enumerate()
        .filter(|(_, term)| regex.is_match(term))
        .map(|(i, _)| ["a", "b", "c", "d"][i].to_owned())
        .collect();
    assert_eq!(keys(&response), expected);

    // Fuzzy.
    let query = "rust".chars().collect::<Vec<_>>();
    let response = search(
        &snapshot,
        &Query::Fuzzy {
            field: "tags".into(),
            value: "rust".into(),
            max_edits: 1,
            transpositions: true,
        },
        SearchLimits::default(),
    )
    .unwrap();
    let expected: Vec<String> = terms
        .iter()
        .enumerate()
        .filter(|(_, term)| ref_levenshtein(&query, &term.chars().collect::<Vec<_>>()) <= 1)
        .map(|(i, _)| ["a", "b", "c", "d"][i].to_owned())
        .collect();
    assert_eq!(keys(&response), expected);
}

// ---------------------------------------------------------------------------
// A1-T24/T25 — Boolean, negative-only and top-K semantics unchanged
// ---------------------------------------------------------------------------

#[test]
fn a1_t24_boolean_and_negative_only_unchanged() {
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let negative = Query::Not(Box::new(prefix("tags", "rust")));
    let response = search(&snapshot, &negative, SearchLimits::default()).unwrap();
    assert_eq!(keys(&response), ["h3", "h4"]);
    assert!(response.hits.iter().all(|hit| hit.score == 0.0));

    let intersection = Query::And(vec![prefix("tags", "ru"), prefix("host", "r")]);
    let response = search(&snapshot, &intersection, SearchLimits::default()).unwrap();
    assert_eq!(keys(&response), ["h1", "h3"]);

    let one = LexicalSearcher::new(
        &snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(
        &prefix("tags", "r"),
        TopK::new(1).unwrap(),
        &Budgets::new(),
        &NeverCancel,
    )
    .unwrap();
    assert!(one.hits.len() == 1);
    assert_eq!(one.total_hits, 3);
}

// ---------------------------------------------------------------------------
// A1-T25/T26 — ten-arg constructor and additive expansion limit
// ---------------------------------------------------------------------------

#[test]
fn a1_t25_ten_arg_constructor_preserves_defaults() {
    let limits = SearchLimits::new(10, 10, 10, 10, 10, 10, 10, 10, 10, 10).unwrap();
    assert_eq!(limits.max_expansion_bytes(), 33_554_432);
    assert_eq!(limits.max_fst_bytes(), 33_554_432);
    assert_eq!(limits.max_expanded_terms(), 1_024);
}

#[test]
fn a1_t26_expansion_bytes_setter_exact_zero_one_over() {
    let limits = SearchLimits::default();
    let exact = limits.with_max_expansion_bytes(1).unwrap();
    assert_eq!(exact.max_expansion_bytes(), 1);
    assert!(limits.with_max_expansion_bytes(0).is_err());
    assert!(limits.with_max_expansion_bytes(536_870_913).is_err());
    assert_eq!(
        limits
            .with_max_expansion_bytes(536_870_912)
            .unwrap()
            .max_expansion_bytes(),
        536_870_912
    );
}

// ---------------------------------------------------------------------------
// A1-T27 — golden fixture bytes are unchanged
// ---------------------------------------------------------------------------

#[test]
fn a1_t27_frozen_fixture_bytes_unchanged() {
    use std::path::PathBuf;
    let root =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/index/pr07_pre_norms_v1");
    let objects = [
        (
            "index/CURRENT",
            "56067c79491360ac0db145387aa15dc6156bac3217c5261507e34954bcebea88",
        ),
        (
            "index/manifests/g-0000000000000001.manifest",
            "276d8025485f0e2ce9fe02a4f9eb7536a433cd28b2ae911a0b5a382b160f91d1",
        ),
        (
            "index/segments/da391e76a490450b371d3ea963dd06e4a58d269974d52d1460b26c0083faf558.seg",
            "da391e76a490450b371d3ea963dd06e4a58d269974d52d1460b26c0083faf558",
        ),
        (
            "index/segments/0508682861380e974057c33f1f702713f0d38643ebd55eee12edeeedb3b94b4e.seg",
            "0508682861380e974057c33f1f702713f0d38643ebd55eee12edeeedb3b94b4e",
        ),
    ];
    for (relative, expected) in objects {
        let bytes = std::fs::read(root.join(relative)).expect("fixture object");
        let digest = sha2::Sha256::digest(&bytes);
        use std::fmt::Write as _;
        let mut hex = String::new();
        for byte in digest {
            write!(hex, "{byte:02x}").expect("write");
        }
        assert_eq!(hex, expected, "fixture {relative} changed");
    }
}

// ---------------------------------------------------------------------------
// A1-T28 — schema surface unchanged
// ---------------------------------------------------------------------------

#[test]
fn a1_t28_published_schema_and_semantics_unchanged() {
    // The additive limit is the only new public search field; the query AST and
    // segment schema are untouched. A term/prefix search still returns identical
    // membership over an existing committed index.
    let directory = memory();
    pr08_commit_batches(Arc::clone(&directory), vec![corpus()]);
    let index = Index::open_existing(directory, pr08_schema(), pr08_registry()).unwrap();
    let snapshot = index.snapshot();
    let term = Query::Term {
        field: "tags".into(),
        value: FieldValue::Keyword("rust".into()),
    };
    assert_eq!(
        keys(&search(&snapshot, &term, SearchLimits::default()).unwrap()),
        ["h1"]
    );
    assert_eq!(
        keys(&search(&snapshot, &prefix("tags", "rust"), SearchLimits::default()).unwrap()),
        ["h1", "h2"]
    );
    // The new field is a lexical keyword field, not a new storage type.
    assert_eq!(
        pr08_schema().get("tags").unwrap().field_type,
        FieldType::Keyword
    );
}
