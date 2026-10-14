//! PR 7 Amendment 04 — benchmark fixture/oracle/determinism validation (A4-T01..T08).
//!
//! Reuses the benchmark fixture module directly so the oracle and dataset used by
//! Criterion are the same ones validated here. No production behavior is changed.

#[path = "../benches/common/mod.rs"]
mod common;

use std::collections::BTreeSet;

use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;

// A4-T01 — identical seed/axes produce identical digest and oracle hit sets.
#[test]
fn a4_t01_deterministic_fixture_and_digest() {
    let a = common::build(2_000, 4);
    let b = common::build(2_000, 4);
    assert_eq!(a.dataset_sha256(), b.dataset_sha256());
    for (left, right) in common::cases(&a).iter().zip(common::cases(&b).iter()) {
        assert_eq!(left.id, right.id);
        assert_eq!(left.expected, right.expected);
    }
    // Production agrees with the oracle for every case.
    common::assert_all_cases(&a);
}

// A4-T02 — changing seed or axes changes the expected digest.
#[test]
fn a4_t02_digest_is_axis_sensitive() {
    let baseline = common::build(2_000, 4);
    let other_seed = common::build_with_seed(2_000, 4, common::SEED ^ 0xFFFF);
    let other_docs = common::build(1_000, 4);
    let other_segments = common::build(2_000, 1);
    let digest = baseline.dataset_sha256();
    assert_ne!(digest, other_seed.dataset_sha256());
    assert_ne!(digest, other_docs.dataset_sha256());
    assert_ne!(digest, other_segments.dataset_sha256());
}

// A4-T03 — selectivity counts match the independent ledger.
#[test]
fn a4_t03_selectivity_counts() {
    for (doc_count, expected_medium) in [(2_000usize, 20usize), (10_000, 100), (100_000, 1_000)] {
        let fixture = common::build(doc_count, 4);
        let cases = common::cases(&fixture);
        let case = |id: &str| cases.iter().find(|case| case.id == id).expect("case");
        assert_eq!(case("term-rare").expected.len(), 1, "rare at {doc_count}");
        assert!(
            case("term-rare")
                .expected
                .iter()
                .all(|key| key == "d00000000")
        );
        assert_eq!(
            case("term-absent").expected.len(),
            0,
            "absent at {doc_count}"
        );
        assert_eq!(
            case("term-medium").expected.len(),
            expected_medium,
            "medium at {doc_count}"
        );
        assert_eq!(
            case("term-common").expected.len(),
            doc_count.div_ceil(2),
            "common at {doc_count}"
        );
        common::assert_all_cases(&fixture);
    }
}

// A4-T04 — phrase present/absent/repeated oracle agreement, no cross-value matches.
#[test]
fn a4_t04_phrase_oracle() {
    let fixture = common::build(2_000, 4);
    let cases = common::cases(&fixture);
    let present = cases
        .iter()
        .find(|case| case.id == "phrase-present")
        .unwrap();
    let absent = cases
        .iter()
        .find(|case| case.id == "phrase-absent")
        .unwrap();
    let repeated = cases
        .iter()
        .find(|case| case.id == "phrase-repeated")
        .unwrap();
    assert!(!present.expected.is_empty());
    assert!(absent.expected.is_empty());
    assert!(!repeated.expected.is_empty());
    for case in [present, absent, repeated] {
        common::assert_case(&fixture, case);
    }
}

// A4-T05 — term/AND/OR/MatchAll/pure-negative match independent sets.
#[test]
fn a4_t05_boolean_oracle() {
    let fixture = common::build(2_000, 4);
    let cases = common::cases(&fixture);
    let expected = |id: &str| {
        cases
            .iter()
            .find(|case| case.id == id)
            .unwrap()
            .expected
            .clone()
    };
    let common_set = expected("term-common");
    let medium = expected("term-medium");
    let rare = expected("term-rare");
    let all: BTreeSet<String> = fixture.docs.iter().map(|doc| doc.key.clone()).collect();

    assert_eq!(
        expected("and-common-medium"),
        common_set
            .intersection(&medium)
            .cloned()
            .collect::<BTreeSet<_>>()
    );
    let mut union = common_set.clone();
    union.extend(rare.iter().cloned());
    assert_eq!(expected("or-common-rare"), union);
    assert_eq!(expected("match-all"), all);
    assert_eq!(
        expected("pure-negative"),
        all.difference(&rare).cloned().collect::<BTreeSet<_>>()
    );
    common::assert_all_cases(&fixture);
}

// A4-T06 — top-K truncation preserves exact total hits and stable ranking.
#[test]
fn a4_t06_topk_truncation_and_stability() {
    let fixture = common::build(2_000, 4);
    let searcher = fixture.searcher();
    let query = Query::Term {
        field: "title".into(),
        value: FieldValue::Text(common::COMMON_TERM.into()),
    };
    let full = searcher
        .search(
            &query,
            TopK::new(fixture.doc_count).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
    assert_eq!(full.total_hits as usize, fixture.doc_count.div_ceil(2));
    for k in [1usize, 10, 100] {
        let truncated = searcher
            .search(&query, TopK::new(k).unwrap(), &Budgets::new(), &NeverCancel)
            .unwrap();
        assert_eq!(truncated.total_hits, full.total_hits, "k={k}");
        assert_eq!(truncated.hits.len(), k);
        for (index, hit) in truncated.hits.iter().enumerate() {
            assert_eq!(hit.key, full.hits[index].key, "k={k} index={index}");
            assert!((hit.score - full.hits[index].score).abs() < 1e-12);
        }
    }
    // Repeated runs are identical (no hidden nondeterminism).
    let repeat = searcher
        .search(
            &query,
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
    let first = searcher
        .search(
            &query,
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
    assert_eq!(
        repeat
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        first
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>()
    );
}

// A4-T07 — 0% tombstones (all live); 25% is NOT APPLICABLE for insert-only PR 7.
#[test]
fn a4_t07_deletions() {
    let fixture = common::build(2_000, 4);
    // PR 6/7 is insert-only: every indexed document is live. A 25% tombstone
    // fixture cannot be constructed through the public writer/reader API without
    // PR 9 mutation support (and `ReaderSnapshot::new` is crate-private), so it is
    // explicitly NOT measured here rather than simulated with a divergent oracle.
    for segment in 0..fixture.snapshot.segment_count() {
        let guard = fixture.snapshot.open_segment_reader(segment).unwrap();
        assert!(
            guard.reader().live_docs().unwrap().iter().all(|live| *live),
            "insert-only segments must have no tombstones"
        );
    }
    let response = fixture
        .searcher()
        .search(
            &Query::MatchAll,
            TopK::new(fixture.doc_count).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
    assert_eq!(response.total_hits as usize, fixture.doc_count);
}

// A4-T08 — single- vs four-segment equivalent corpus matches logical results.
#[test]
fn a4_t08_segment_partition_equivalence() {
    let single = common::build(2_000, 1);
    let four = common::build(2_000, 4);
    // Segment partitioning is part of the dataset digest, but the logical query
    // results and scores must be invariant.
    for (left, right) in common::cases(&single)
        .iter()
        .zip(common::cases(&four).iter())
    {
        assert_eq!(left.expected, right.expected, "{}", left.id);
        let left_response = single
            .searcher()
            .search(
                &left.query,
                TopK::new(single.doc_count).unwrap(),
                &Budgets::new(),
                &NeverCancel,
            )
            .unwrap();
        let right_response = four
            .searcher()
            .search(
                &right.query,
                TopK::new(single.doc_count).unwrap(),
                &Budgets::new(),
                &NeverCancel,
            )
            .unwrap();
        assert_eq!(left_response.total_hits, right_response.total_hits);
        let left_scores: std::collections::BTreeMap<_, _> = left_response
            .hits
            .iter()
            .map(|hit| (hit.key.as_str().to_owned(), hit.score))
            .collect();
        let right_scores: std::collections::BTreeMap<_, _> = right_response
            .hits
            .iter()
            .map(|hit| (hit.key.as_str().to_owned(), hit.score))
            .collect();
        assert_eq!(left_scores.len(), right_scores.len());
        for key in left_scores.keys() {
            assert!(right_scores.contains_key(key), "{} {key}", left.id);
        }
        for (key, score) in &left_scores {
            assert!(
                (score - right_scores[key]).abs() < 1e-10,
                "{} {key}",
                left.id
            );
        }
    }
}
