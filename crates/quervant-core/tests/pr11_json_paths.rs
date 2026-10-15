//! PR 11 native JSON path indexing and exact predicate tests (behavioral).

mod pr11_common;

use pr11_common::*;
use quervant_core::contract::document::FieldValues;
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::value::{FieldValue, JsonNumber, JsonValue};

/// J11-T01 — stored JSON structure round-trips exactly.
#[test]
fn t01_stored_json_round_trip() {
    let value = obj(&[
        ("z", i64_value(-1)),
        ("a", u64_value(7)),
        ("unicode", str_value("naïve")),
        ("arr", array(vec![f64_value(-0.0), JsonValue::Null])),
        ("nested", obj(&[("b", bool_value(true))])),
    ]);
    let mut document = doc("d1", 1);
    set_body(&mut document, value.clone());
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).unwrap();
    let reader = guard.reader();
    let field_id = reader.schema().field_id("body").unwrap();
    let record = reader.stored_doc(0).unwrap();
    match record.get(field_id) {
        FieldValues::Single(FieldValue::Json(stored)) => assert_eq!(stored, value),
        other => panic!("unexpected stored state {other:?}"),
    }
}

/// J11-T02 — stored-only JSON may keep duplicate members; indexed JSON rejects them.
#[test]
fn t02_duplicate_members() {
    let duplicate = obj(&[("a", i64_value(1)), ("a", i64_value(2))]);
    let mut stored_only = doc("stored", 1);
    set_stored_only(&mut stored_only, duplicate.clone());
    let (_directory, index) = committed(vec![stored_only]);
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).unwrap();
    let reader = guard.reader();
    let field_id = reader.schema().field_id("stored_only").unwrap();
    match reader.stored_doc(0).unwrap().get(field_id) {
        FieldValues::Single(FieldValue::Json(stored)) => assert_eq!(stored, duplicate),
        other => panic!("unexpected stored state {other:?}"),
    }

    // Indexed duplicate member is rejected at admission.
    let directory = memory();
    let index = create(directory);
    let mut indexed = doc("indexed", 1);
    set_body(&mut indexed, duplicate);
    let mut writer = index.writer().unwrap();
    assert!(writer.insert(indexed).is_err());
}

/// J11-T03 — array elements retain concrete ancestry.
#[test]
fn t03_array_ancestry() {
    let events = array(vec![
        obj(&[("ip", str_value("a"))]),
        obj(&[("ip", str_value("b"))]),
    ]);
    let mut document = doc("d1", 1);
    set_body(&mut document, obj(&[("events", events)]));
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();
    assert_eq!(search(&snapshot, exists("body", "$.events[*].ip")), ["d1"]);
    assert_eq!(search(&snapshot, exists("body", "$.events[0].ip")), ["d1"]);
    assert_eq!(search(&snapshot, exists("body", "$.events[1].ip")), ["d1"]);
    assert!(search(&snapshot, exists("body", "$.events[2].ip")).is_empty());
    assert_eq!(
        search(
            &snapshot,
            equals("body", "$.events[1].ip", str_value_field("b"))
        ),
        ["d1"]
    );
    assert!(
        search(
            &snapshot,
            equals("body", "$.events[0].ip", str_value_field("b"))
        )
        .is_empty()
    );
}

/// J11-T04 — empty containers, root null and nesting are distinct.
#[test]
fn t04_empty_and_nested() {
    let mut empty = doc("empty", 1);
    set_body(&mut empty, obj(&[("a", array(vec![])), ("o", obj(&[]))]));
    let mut root_null = doc("root_null", 2);
    set_body(&mut root_null, JsonValue::Null);
    let mut nested = doc("nested", 3);
    set_body(
        &mut nested,
        obj(&[("a", obj(&[("b", obj(&[("c", i64_value(1))]))]))]),
    );
    let (_directory, index) = committed(vec![empty, root_null, nested]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, exists("body", "$.a")),
        ["empty", "nested"]
    );
    assert_eq!(search(&snapshot, exists("body", "$.o")), ["empty"]);
    assert!(search(&snapshot, exists("body", "$.a[*]")).is_empty());
    assert_eq!(
        search(&snapshot, exists("body", "$")),
        ["empty", "nested", "root_null"]
    );
    assert_eq!(search(&snapshot, exists("body", "$.a.b.c")), ["nested"]);
    assert_eq!(
        search(&snapshot, equals("body", "$.a.b.c", FieldValue::I64(1))),
        ["nested"]
    );
}

/// J11-T05 — a multi-root JSON field uses virtual outer indices.
#[test]
fn t05_multi_root_virtual_index() {
    let mut document = doc("m1", 1);
    set_mbody(
        &mut document,
        vec![obj(&[("x", i64_value(1))]), obj(&[("x", i64_value(2))])],
    );
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();
    assert_eq!(search(&snapshot, exists("mbody", "$[0].x")), ["m1"]);
    assert_eq!(search(&snapshot, exists("mbody", "$[1].x")), ["m1"]);
    assert!(search(&snapshot, exists("mbody", "$[2].x")).is_empty());
    assert_eq!(
        search(&snapshot, equals("mbody", "$[1].x", FieldValue::I64(2))),
        ["m1"]
    );
    assert!(search(&snapshot, equals("mbody", "$[1].x", FieldValue::I64(1))).is_empty());
}

/// J11-T06 — missing, explicit null, JSON null and empty states differ.
#[test]
fn t06_field_state_truth_table() {
    let mut absent = doc("absent", 1);
    clear_body(&mut absent);
    let mut explicit_null = doc("explicit_null", 2);
    set_body_explicit_null(&mut explicit_null);
    let mut json_null = doc("json_null", 3);
    set_body(&mut json_null, JsonValue::Null);
    let mut empty_multi = doc("empty_multi", 4);
    set_mbody_empty(&mut empty_multi);
    let (_directory, index) = committed(vec![absent, explicit_null, json_null, empty_multi]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, exists("body", "$")),
        ["explicit_null", "json_null"]
    );
    assert!(search(&snapshot, exists("body", "$.x")).is_empty());
    assert!(search(&snapshot, exists("mbody", "$")).is_empty());
    assert!(search(&snapshot, exists("mbody", "$[0]")).is_empty());
}

/// J11-T07 — wildcard existence over empty, scalar and null arrays.
#[test]
fn t07_wildcard_existence() {
    let mut empty = doc("empty", 1);
    set_body(&mut empty, obj(&[("a", array(vec![]))]));
    let mut scalar = doc("scalar", 2);
    set_body(&mut scalar, obj(&[("a", i64_value(1))]));
    let mut nulls = doc("nulls", 3);
    set_body(&mut nulls, obj(&[("a", array(vec![JsonValue::Null]))]));
    let mut unicode = doc("unicode", 4);
    set_body(&mut unicode, obj(&[("é", i64_value(1))]));
    let (_directory, index) = committed(vec![empty, scalar, nulls, unicode]);
    let snapshot = index.snapshot();
    assert_eq!(search(&snapshot, exists("body", "$.a[*]")), ["nulls"]);
    assert_eq!(
        search(&snapshot, exists("body", "$.a")),
        ["empty", "nulls", "scalar"]
    );
    assert!(search(&snapshot, exists("body", "$.a[*].missing")).is_empty());
    assert_eq!(search(&snapshot, exists("body", "$[\"é\"]")), ["unicode"]);
}

/// J11-T08 — equality is type-exact and non-coercing; signed zero is neutral.
#[test]
fn t08_equality_type_exact() {
    let mut i_doc = doc("i", 1);
    set_body(&mut i_doc, obj(&[("v", i64_value(1))]));
    let mut u_doc = doc("u", 2);
    set_body(&mut u_doc, obj(&[("v", u64_value(1))]));
    let mut f_doc = doc("f", 3);
    set_body(&mut f_doc, obj(&[("v", f64_value(1.0))]));
    let mut zero = doc("zero", 4);
    set_body(&mut zero, obj(&[("v", f64_value(-0.0))]));
    let mut flag = doc("flag", 5);
    set_body(&mut flag, obj(&[("v", bool_value(true))]));
    let mut null_doc = doc("null", 6);
    set_body(&mut null_doc, obj(&[("v", JsonValue::Null)]));
    let (_directory, index) = committed(vec![i_doc, u_doc, f_doc, zero, flag, null_doc]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::I64(1))),
        ["i"]
    );
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::U64(1))),
        ["u"]
    );
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::F64(1.0))),
        ["f"]
    );
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::F64(-0.0))),
        ["zero"]
    );
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::F64(0.0))),
        ["zero"]
    );
    assert_eq!(
        search(&snapshot, equals("body", "$.v", FieldValue::Bool(true))),
        ["flag"]
    );
    assert!(search(&snapshot, equals("body", "$.v", FieldValue::I64(0))).is_empty());
}

/// J11-T09 — string equality is byte-exact (NFC vs NFD) and path aliases agree.
#[test]
fn t09_string_bytes_and_path_aliases() {
    let nfc = "\u{00e9}";
    let nfd = "e\u{0301}";
    let mut nfc_doc = doc("nfc", 1);
    set_body(&mut nfc_doc, obj(&[("v", str_value(nfc))]));
    let mut nfd_doc = doc("nfd", 2);
    set_body(&mut nfd_doc, obj(&[("v", str_value(nfd))]));
    let (_directory, index) = committed(vec![nfc_doc, nfd_doc]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            equals("body", "$.v", FieldValue::Keyword(nfc.to_owned()))
        ),
        ["nfc"]
    );
    assert_eq!(
        search(
            &snapshot,
            equals("body", "$.v", FieldValue::Text(nfd.to_owned()))
        ),
        ["nfd"]
    );
    // Dotted and quoted ASCII members are the same concrete identity.
    assert_eq!(
        search(&snapshot, exists("body", "$[\"v\"]")),
        ["nfc", "nfd"]
    );
    assert_eq!(
        search(
            &snapshot,
            equals("body", "$[\"v\"]", FieldValue::Keyword(nfc.to_owned()))
        ),
        ["nfc"]
    );
}

/// Helper: a `Keyword` RHS field value from a JSON string.
fn str_value_field(value: &str) -> FieldValue {
    FieldValue::Keyword(value.to_owned())
}

/// `JsonNumber` is re-exported for callers that construct JSON values directly.
#[allow(dead_code)]
fn number_variants() -> (JsonNumber, JsonPathExpr) {
    (
        JsonNumber::I64(1),
        JsonPathExpr::parse("$.v").expect("path"),
    )
}

/// B1-T10 — a wide-but-shallow field survives the real writer→reader→search path.
#[test]
fn b1_wide_shallow_builder_search() {
    let mut document = doc("wide", 1);
    let entries: Vec<(String, JsonValue)> = (0..5_000i64)
        .map(|index| (format!("f{index:05}"), i64_value(index)))
        .collect();
    set_body(&mut document, JsonValue::Object(entries));
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();
    assert_eq!(search(&snapshot, exists("body", "$.f00000")), ["wide"]);
    assert_eq!(
        search(
            &snapshot,
            equals("body", "$.f04999", FieldValue::I64(4_999))
        ),
        ["wide"]
    );
    assert!(search(&snapshot, equals("body", "$.f04999", FieldValue::I64(0))).is_empty());
    assert!(search(&snapshot, exists("body", "$.missing")).is_empty());

    // No inferred cross-array correlation for independently flattened filters.
    let mut events = doc("events", 2);
    set_body(
        &mut events,
        obj(&[(
            "events",
            array(vec![
                obj(&[("ip", str_value("a")), ("t", i64_value(1))]),
                obj(&[("ip", str_value("b")), ("t", i64_value(2))]),
            ]),
        )]),
    );
    let (_directory, index) = committed(vec![events]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            Query::And(vec![
                equals("body", "$.events[1].ip", FieldValue::Keyword("b".into())),
                equals("body", "$.events[0].t", FieldValue::I64(1)),
            ])
        ),
        ["events"]
    );
    assert!(
        search(
            &snapshot,
            Query::And(vec![
                equals("body", "$.events[1].ip", FieldValue::Keyword("b".into())),
                equals("body", "$.events[0].t", FieldValue::I64(2)),
            ])
        )
        .is_empty()
    );
}
