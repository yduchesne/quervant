//! PR 14 F1: mixed lexical+typed unified execution.
//!
//! Expected key sets are hand-enumerated from the fixture corpus; the pure
//! lexical and pure typed paths are separately compared against their existing
//! executors for parity.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::{CancellationFlag, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, MutationRequest};
use quervant_core::contract::value::{JsonNumber, JsonValue, Timestamp};
use quervant_core::search::{LexicalSearcher, SearchLimits, UnifiedRequest, UnifiedSearcher};

fn unified(
    index: &quervant_core::index::Index,
    query: Query,
) -> quervant_core::search::UnifiedResponse {
    let snapshot = index.snapshot();
    let request = UnifiedRequest::new(query, TopK::new(50).unwrap());
    UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("unified search")
}

fn keys(index: &quervant_core::index::Index, query: Query) -> Vec<String> {
    let mut out: Vec<String> = unified(index, query)
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    out.sort_unstable();
    out
}

fn corpus() -> Vec<Document> {
    let mut d1 = doc("d1");
    set(&mut d1, "title", FieldValue::Text("alpha beta".into()));
    set(&mut d1, "n", FieldValue::I64(1));
    set(&mut d1, "body", FieldValue::Json(obj_num("k", 1)));
    set(&mut d1, "ip", FieldValue::Ip("10.0.0.1".parse().unwrap()));
    set(
        &mut d1,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(100)),
    );
    let mut d2 = doc("d2");
    set(&mut d2, "title", FieldValue::Text("alpha gamma".into()));
    set(&mut d2, "n", FieldValue::I64(5));
    set(&mut d2, "body", FieldValue::Json(obj_num("k", 2)));
    set(&mut d2, "ip", FieldValue::Ip("10.0.0.2".parse().unwrap()));
    set(
        &mut d2,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(200)),
    );
    let mut d3 = doc("d3");
    set(&mut d3, "title", FieldValue::Text("beta gamma".into()));
    set(&mut d3, "n", FieldValue::I64(9));
    set(&mut d3, "body", FieldValue::Json(obj_num("k", 3)));
    set(&mut d3, "ip", FieldValue::Ip("192.0.2.1".parse().unwrap()));
    set(
        &mut d3,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(300)),
    );
    let mut d4 = doc("d4");
    set(&mut d4, "title", FieldValue::Text("delta".into()));
    set(&mut d4, "n", FieldValue::I64(12));
    set(&mut d4, "ip", FieldValue::Ip("10.0.0.4".parse().unwrap()));
    set(
        &mut d4,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(400)),
    );
    vec![d1, d2, d3, d4]
}

fn obj_num(key: &str, value: i64) -> JsonValue {
    JsonValue::Object(vec![(
        key.to_owned(),
        JsonValue::Number(JsonNumber::I64(value)),
    )])
}

fn term(text: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(text.into()),
    }
}

// M01 — term AND typed range.
#[test]
fn m01_term_and_range() {
    let index = committed(corpus());
    let query = Query::And(vec![
        term("alpha"),
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(5)),
            upper: Bound::Included(FieldValue::I64(10)),
        },
    ]);
    assert_eq!(keys(&index, query), ["d2"]);
}

// M02 — term OR IP; typed-only match has zero lexical score.
#[test]
fn m02_term_or_ip() {
    let index = committed(corpus());
    let query = Query::Or(vec![
        term("alpha"),
        Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        },
    ]);
    let response = unified(&index, query);
    let mut got: Vec<(&str, Option<f64>)> = response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str(), hit.score))
        .collect();
    got.sort_by(|a, b| a.0.cmp(b.0));
    assert_eq!(got.len(), 3);
    assert_eq!(got[0].0, "d1");
    assert!(got[0].1.unwrap() > 0.0);
    // d3 matched only the IP branch: no phantom lexical score.
    let d3 = got.iter().find(|(key, _)| *key == "d3").unwrap();
    assert_eq!(d3.1, Some(0.0));
}

// M03 — nested OR + JSON, AND NOT time range.
#[test]
fn m03_json_or_and_not_time() {
    let index = committed(corpus());
    let query = Query::And(vec![
        Query::Or(vec![
            term("alpha"),
            Query::JsonPathExists {
                field: "body".into(),
                path: quervant_core::contract::query::JsonPathExpr::parse("$.k").unwrap(),
            },
        ]),
        Query::Not(Box::new(Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(0),
            end: Timestamp::from_micros(250),
        })),
    ]);
    assert_eq!(keys(&index, query), ["d3"]);
}

// M04 — negative-only lexical leaf contributes no score but still filters.
#[test]
fn m04_negative_only_lexical() {
    let index = committed(corpus());
    let query = Query::And(vec![
        Query::Not(Box::new(term("alpha"))),
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(9)),
            upper: Bound::Included(FieldValue::I64(100)),
        },
    ]);
    let response = unified(&index, query);
    assert_eq!(response.hits.len(), 2);
    // Negative-only leaf is not scoring-eligible; D4 has n=12 which is in range.
    let mut got: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    got.sort_unstable();
    assert_eq!(got, ["d3", "d4"]);
    assert!(response.hits.iter().all(|hit| hit.score == Some(0.0)));
}

// M05 — MatchAll AND term behaves like the term.
#[test]
fn m05_match_all_and_term() {
    let index = committed(corpus());
    assert_eq!(
        keys(&index, Query::And(vec![Query::MatchAll, term("delta")])),
        ["d4"]
    );
}

// M06 — double negation.
#[test]
fn m06_double_negation() {
    let index = committed(corpus());
    let query = Query::Not(Box::new(Query::Not(Box::new(term("delta")))));
    assert_eq!(keys(&index, query), ["d4"]);
}

// M07 — deleted documents never resurrect under NOT.
#[test]
fn m07_not_cannot_resurrect_tombstones() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in corpus() {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("d4").unwrap()))
            .unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory);
    // NOT Term(delta) must not include the deleted d4.
    let query = Query::Not(Box::new(term("delta")));
    let got = keys(&live, query);
    assert!(!got.contains(&"d4".to_owned()));
    assert_eq!(got, ["d1", "d2", "d3"]);
}

// M08 — duplicate positive lexical leaves do not double score.
#[test]
fn m08_duplicate_leaves_do_not_double_score() {
    let index = committed(corpus());
    let single = Query::And(vec![term("alpha"), Query::MatchAll]);
    let duplicate = Query::And(vec![term("alpha"), term("alpha")]);
    let index_snapshot = index.snapshot();
    let single_scores: std::collections::BTreeMap<String, f64> = unified(&index, single)
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score.unwrap()))
        .collect();
    let duplicate_scores: std::collections::BTreeMap<String, f64> = UnifiedSearcher::new(
        &index_snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(
        &UnifiedRequest::new(duplicate, TopK::new(50).unwrap()),
        &Budgets::new(),
        &NeverCancel,
    )
    .unwrap()
    .hits
    .iter()
    .map(|hit| (hit.key.as_str().to_owned(), hit.score.unwrap()))
    .collect();
    assert_eq!(single_scores, duplicate_scores);
}

// M09 — mixed query across two committed segments.
#[test]
fn m09_two_segments() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in corpus().into_iter().take(2) {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in corpus().into_iter().skip(2) {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = reopen(directory);
    let query = Query::And(vec![
        Query::Exists { field: "ip".into() },
        Query::Not(Box::new(Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        })),
    ]);
    // This query is typed-only; assert mixed still works with a lexical anchor.
    let mixed = Query::And(vec![
        Query::Or(vec![term("alpha"), term("delta")]),
        Query::Not(Box::new(Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        })),
    ]);
    assert!(reopened.snapshot().segment_count() >= 2);
    assert_eq!(keys(&reopened, query), ["d1", "d2", "d4"]);
    let mut mixed_keys = keys(&reopened, mixed);
    mixed_keys.sort_unstable();
    assert_eq!(mixed_keys, ["d1", "d2", "d4"]);
}

// M10 — phrase AND typed range.
#[test]
fn m10_phrase_and_range() {
    let index = committed(corpus());
    let query = Query::And(vec![
        Query::Phrase {
            field: "title".into(),
            terms: vec!["alpha".into(), "beta".into()],
        },
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(1)),
            upper: Bound::Included(FieldValue::I64(1)),
        },
    ]);
    assert_eq!(keys(&index, query), ["d1"]);
}

// M11 — regex AND JSON equality.
#[test]
fn m11_regex_and_json() {
    let index = committed(corpus());
    let query = Query::And(vec![
        Query::Regex {
            field: "title".into(),
            pattern: "alpha".into(),
        },
        Query::JsonPathEquals {
            field: "body".into(),
            path: quervant_core::contract::query::JsonPathExpr::parse("$.k").unwrap(),
            value: FieldValue::I64(2),
        },
    ]);
    assert_eq!(keys(&index, query), ["d2"]);
}

// M12 — zero hits.
#[test]
fn m12_zero_hits() {
    let index = committed(corpus());
    let query = Query::And(vec![
        term("nonexistent"),
        Query::Exists { field: "ip".into() },
    ]);
    let response = unified(&index, query);
    assert!(response.hits.is_empty());
    assert_eq!(response.total_hits, 0);
}

// M13 — pure lexical parity with the lexical executor.
#[test]
fn m13_pure_lexical_parity() {
    let index = committed(corpus());
    let snapshot = index.snapshot();
    let lexical = LexicalSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(
            &term("alpha"),
            TopK::new(50).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
    let unified_response = unified(&index, term("alpha"));
    assert_eq!(lexical.total_hits, unified_response.total_hits);
    let mut expected: Vec<String> = lexical
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    let mut actual: Vec<String> = unified_response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    expected.sort_unstable();
    actual.sort_unstable();
    assert_eq!(expected, actual);
    // Bit-identical scores from the shared scorer.
    for hit in &lexical.hits {
        let other = unified_response
            .hits
            .iter()
            .find(|candidate| candidate.key == hit.key)
            .unwrap();
        assert_eq!(Some(hit.score), other.score);
    }
}

// M14 — mixed explicit numeric sort with key tie-break.
#[test]
fn m14_mixed_explicit_sort() {
    let index = committed(corpus());
    let snapshot = index.snapshot();
    let query = Query::And(vec![Query::Exists { field: "ip".into() }, term("gamma")]);
    let mut request = UnifiedRequest::new(query, TopK::new(50).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    let response = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .unwrap();
    let got: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    // gamma: d2(n=5), d3(n=9); descending by n => d3, d2.
    assert_eq!(got, ["d3", "d2"]);
}
