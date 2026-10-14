//! PR 11 deterministic property tests against an independent reference oracle.

mod pr11_common;

use std::collections::BTreeMap;

use pr11_common::*;
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::value::{FieldValue, JsonValue};
use quervant_core::index::Index;

/// A small deterministic xorshift generator (fixed seed).
struct Rng(u64);

impl Rng {
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next_u64() % n
    }
}

const KEYS: [&str; 7] = ["a", "b", "c", "ab", "abc", "x0", "longer_name"];

fn gen_value(rng: &mut Rng, depth: u32) -> JsonValue {
    if depth == 0 {
        return match rng.below(5) {
            0 => JsonValue::Null,
            1 => JsonValue::Bool(rng.below(2) == 1),
            2 => i64_value(rng.below(5) as i64 - 2),
            3 => u64_value(rng.below(4)),
            _ => str_value(KEYS[rng.below(KEYS.len() as u64) as usize]),
        };
    }
    match rng.below(6) {
        0 => JsonValue::Null,
        1 => JsonValue::Bool(rng.below(2) == 1),
        2 => i64_value(rng.below(5) as i64 - 2),
        3 => str_value(KEYS[rng.below(KEYS.len() as u64) as usize]),
        4 => {
            let count = rng.below(5);
            JsonValue::Array((0..count).map(|_| gen_value(rng, depth - 1)).collect())
        }
        _ => {
            let count = rng.below(5) as usize;
            // Choose distinct keys so no duplicate members are produced.
            let mut chosen = Vec::new();
            while chosen.len() < count {
                let index = rng.below(KEYS.len() as u64) as usize;
                if !chosen.contains(&index) {
                    chosen.push(index);
                }
            }
            JsonValue::Object(
                chosen
                    .into_iter()
                    .map(|index| (KEYS[index].to_owned(), gen_value(rng, depth - 1)))
                    .collect(),
            )
        }
    }
}

fn gen_member(rng: &mut Rng) -> String {
    KEYS[rng.below(KEYS.len() as u64) as usize].to_owned()
}

fn gen_path(rng: &mut Rng, allow_wildcard: bool, max_depth: u32) -> String {
    let mut path = String::from("$");
    let depth = rng.below(u64::from(max_depth) + 1);
    for _ in 0..depth {
        match rng.below(3) {
            0 => path.push_str(&format!(".{}", gen_member(rng))),
            1 => path.push_str(&format!("[{}]", rng.below(4))),
            _ if allow_wildcard => path.push_str("[*]"),
            _ => path.push_str(&format!("[{}]", rng.below(4))),
        }
    }
    path
}

fn gen_scalar(rng: &mut Rng) -> FieldValue {
    match rng.below(5) {
        0 => FieldValue::Bool(rng.below(2) == 1),
        1 => FieldValue::I64(rng.below(5) as i64 - 2),
        2 => FieldValue::U64(rng.below(4)),
        3 => FieldValue::F64(rng.below(5) as f64 - 2.0),
        _ => FieldValue::Keyword(KEYS[rng.below(KEYS.len() as u64) as usize].to_owned()),
    }
}

fn gen_predicate(rng: &mut Rng) -> (Query, RefPredicate) {
    match rng.below(6) {
        0 | 1 => {
            let text = gen_path(rng, true, 4);
            let path = JsonPathExpr::parse(&text).expect("path");
            (
                Query::JsonPathExists {
                    field: "body".to_owned(),
                    path: path.clone(),
                },
                RefPredicate::Exists {
                    pattern: compile_ref(&path),
                },
            )
        }
        2 | 3 => {
            let text = gen_path(rng, false, 4);
            let path = JsonPathExpr::parse(&text).expect("path");
            let value = gen_scalar(rng);
            let scalar = RefScalar::from_value(&value).expect("scalar");
            (
                Query::JsonPathEquals {
                    field: "body".to_owned(),
                    path: path.clone(),
                    value,
                },
                RefPredicate::Equals {
                    pattern: compile_ref(&path),
                    scalar,
                },
            )
        }
        _ => {
            let (left_query, left_ref) = gen_predicate(rng);
            let (right_query, right_ref) = gen_predicate(rng);
            if rng.below(2) == 0 {
                (
                    Query::And(vec![left_query, right_query]),
                    RefPredicate::And(vec![left_ref, right_ref]),
                )
            } else {
                (
                    Query::Or(vec![left_query, right_query]),
                    RefPredicate::Or(vec![left_ref, right_ref]),
                )
            }
        }
    }
}

fn oracle_keys(model: &BTreeMap<String, JsonValue>, predicate: &RefPredicate) -> Vec<String> {
    let mut keys: Vec<String> = model
        .iter()
        .filter(|(_, value)| reference_eval(Some(value), predicate))
        .map(|(key, _)| key.clone())
        .collect();
    keys.sort();
    keys
}

/// J11-I04/I05/I06/I11 — random predicates match the independent oracle exactly.
#[test]
fn t_oracle_matches_exactly() {
    let mut rng = Rng(0x11_2026);
    let mut model: BTreeMap<String, JsonValue> = BTreeMap::new();
    let mut documents = Vec::new();
    for index in 0..100 {
        let key = format!("doc{index:03}");
        let value = gen_value(&mut rng, 4);
        let mut document = doc(&key, index as i64);
        set_body(&mut document, value.clone());
        model.insert(key, value);
        documents.push(document);
    }
    let (_directory, index) = committed(documents);
    let snapshot = index.snapshot();

    for iteration in 0..250 {
        let (query, predicate) = gen_predicate(&mut rng);
        let expected = oracle_keys(&model, &predicate);
        let actual = search(&snapshot, query);
        assert_eq!(
            actual, expected,
            "predicate {iteration} mismatch: expected {expected:?}, actual {actual:?}"
        );
    }
}

/// J11-I06 — document-level Boolean composition never implies array correlation.
#[test]
fn t11_document_level_boolean() {
    let events = obj(&[(
        "events",
        array(vec![
            obj(&[("ip", str_value("a")), ("t", i64_value(1))]),
            obj(&[("ip", str_value("b")), ("t", i64_value(2))]),
        ]),
    )]);
    let mut document = doc("d", 1);
    set_body(&mut document, events);
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();
    let combined = Query::And(vec![
        equals("body", "$.events[0].ip", FieldValue::Keyword("a".into())),
        equals("body", "$.events[1].t", FieldValue::I64(2)),
    ]);
    assert_eq!(search(&snapshot, combined), ["d"]);
}

/// J11-I11 — insertion order does not change logical query results.
#[test]
fn t22_order_independent_results() {
    let mut rng = Rng(0x99);
    let mut forward = Vec::new();
    for index in 0..40 {
        let key = format!("doc{index:03}");
        let value = gen_value(&mut rng, 3);
        let mut document = doc(&key, index as i64);
        set_body(&mut document, value);
        forward.push(document);
    }

    let reverse: Vec<_> = forward.iter().rev().cloned().collect();
    let (_directory_a, index_a) = committed(forward);
    let (_directory_b, index_b) = committed(reverse);
    let snapshot_a = index_a.snapshot();
    let snapshot_b = index_b.snapshot();

    let mut rng = Rng(0x1234);
    for _ in 0..50 {
        let (query, _) = gen_predicate(&mut rng);
        assert_eq!(
            search(&snapshot_a, query.clone()),
            search(&snapshot_b, query)
        );
    }
}

/// J11-T24 — the PR 5 legacy golden fixture is untouched by importing this module.
#[test]
fn t24_pr5_fixture_unaffected() {
    let fixture = include_bytes!("fixtures/segment/golden.seg");
    let limits = quervant_core::segment::SegmentLimits::default();
    let reader = quervant_core::segment::SegmentReader::open(fixture.to_vec(), limits).unwrap();
    assert!(reader.doc_count() > 0);
}

/// Marker to keep the `Index` import meaningful.
#[allow(dead_code)]
fn index_marker(index: Index) -> u64 {
    index.generation().unwrap_or(0)
}
