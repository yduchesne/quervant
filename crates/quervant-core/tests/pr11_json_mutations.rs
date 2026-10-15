//! PR 11 JSON path mutation, PIT, compaction and storage-policy tests.

mod pr11_common;

use std::sync::Arc;

use pr11_common::*;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::query::Query;
use quervant_core::contract::value::{FieldValue, JsonValue};
use quervant_core::index::Index;
use quervant_core::search::{SearchError, SearchLimits};

fn body_doc(key: &str, ts: i64, value: i64) -> Document {
    let mut document = doc(key, ts);
    set_body(&mut document, obj(&[("v", i64_value(value))]));
    document
}

/// J11-T18 — refresh/commit/reopen preserve hits; a PIT keeps the prior revision.
#[test]
fn t18_refresh_commit_reopen_and_pit() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer.insert(body_doc("a", 1, 1)).unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    writer
        .apply(MutationRequest::upsert(body_doc("a", 2, 2)))
        .unwrap();
    writer.commit().unwrap();
    assert_eq!(
        search(&writer.reader(), equals("body", "$.v", FieldValue::I64(2))),
        ["a"]
    );
    assert_eq!(
        search(pit.snapshot(), equals("body", "$.v", FieldValue::I64(1))),
        ["a"]
    );
    assert!(search(pit.snapshot(), equals("body", "$.v", FieldValue::I64(2))).is_empty());
    writer.close().unwrap();

    let reopened = reopen(directory);
    assert_eq!(
        search(
            &reopened.snapshot(),
            equals("body", "$.v", FieldValue::I64(2))
        ),
        ["a"]
    );
}

/// J11-T19 — delete/upsert and `Not(Exists)` never resurrect tombstoned docs.
#[test]
fn t19_delete_upsert_and_negation() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer.insert(body_doc("a", 1, 1)).unwrap();
    writer.insert(doc("b", 2)).unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();

    let negated = Query::Not(Box::new(exists("body", "$.v")));
    assert_eq!(search(&writer.reader(), negated.clone()), ["b"]);
    assert!(search(&writer.reader(), exists("body", "$.v")).is_empty());

    // Upsert "b" to carry a matching path; only "a" remains tombstoned.
    writer
        .apply(MutationRequest::upsert(body_doc("b", 3, 9)))
        .unwrap();
    writer.commit().unwrap();
    assert!(search(&writer.reader(), negated).is_empty());
    writer.close().unwrap();
    let reopened = reopen(directory);
    assert_eq!(
        search(
            &reopened.snapshot(),
            equals("body", "$.v", FieldValue::I64(9))
        ),
        ["b"]
    );
}

/// J11-T20 — compaction rebuilds the JSON index across a physical remap.
#[test]
fn t20_compact_rebuilds_json_paths() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        writer.insert(body_doc("a", 1, 1)).unwrap();
        writer.insert(body_doc("b", 2, 2)).unwrap();
        writer.insert(doc("c", 3)).unwrap();
        writer.commit().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("b").unwrap()))
            .unwrap();
        writer.commit().unwrap();
        let outcome = writer.compact().unwrap();
        assert!(!outcome.no_op);
        assert_eq!(writer.reader().document_count(), 2);
    }
    let reopened = reopen(directory);
    assert_eq!(search(&reopened.snapshot(), exists("body", "$.v")), ["a"]);
    assert_eq!(
        search(
            &reopened.snapshot(),
            equals("body", "$.v", FieldValue::I64(1))
        ),
        ["a"]
    );
    assert_eq!(
        search(
            &reopened.snapshot(),
            Query::Not(Box::new(exists("body", "$.v")))
        ),
        ["c"]
    );
}

/// J11-T21 — `indexed=false` is not silently queryable; `stored=false` hides source.
#[test]
fn t21_index_and_storage_policy() {
    let mut document = doc("d", 1);
    set_indexed_only(&mut document, obj(&[("v", i64_value(1))]));
    set_stored_only(&mut document, obj(&[("v", i64_value(2))]));
    let (_directory, index) = committed(vec![document]);
    let snapshot = index.snapshot();

    // Indexed-but-not-stored is queryable via the JSON index...
    assert_eq!(
        search(&snapshot, equals("indexed_only", "$.v", FieldValue::I64(1))),
        ["d"]
    );
    // ...but its source is not retrievable.
    let guard = snapshot.open_segment_reader(0).unwrap();
    let reader = guard.reader();
    let field_id = reader.schema().field_id("indexed_only").unwrap();
    assert_eq!(
        reader.stored_doc(0).unwrap().get(field_id),
        FieldValues::Absent
    );

    // Stored-only JSON is not silently queryable: typed unsupported operator.
    let error = try_search(
        &snapshot,
        exists("stored_only", "$.v"),
        SearchLimits::default(),
        &Budgets::new(),
    )
    .unwrap_err();
    assert!(matches!(error, SearchError::UnsupportedOperator { .. }));
}

/// J11-T10 — invalid JSON paths and wildcard equality fail before any segment read.
#[test]
fn t10_preflight_failures() {
    let (_directory, index) = committed(vec![body_doc("a", 1, 1)]);
    let snapshot = index.snapshot();
    let budgets = Budgets::new();

    // Wildcard equality (rejected already by contract validation).
    let wildcard = Query::JsonPathEquals {
        field: "body".to_owned(),
        path: quervant_core::contract::query::JsonPathExpr::parse("$.v[*]").unwrap(),
        value: FieldValue::I64(1),
    };
    assert!(try_search(&snapshot, wildcard, SearchLimits::default(), &budgets).is_err());

    // Unsupported RHS type falls back to a typed unsupported error.
    let bad_rhs = equals(
        "body",
        "$.v",
        FieldValue::Timestamp(quervant_core::contract::value::Timestamp::from_micros(1)),
    );
    let error = try_search(&snapshot, bad_rhs, SearchLimits::default(), &budgets).unwrap_err();
    assert!(matches!(error, SearchError::UnsupportedOperator { .. }));

    // Unindexed field is rejected, not silently source-scanned.
    let unindexed = exists("stored_only", "$.v");
    let error = try_search(&snapshot, unindexed, SearchLimits::default(), &budgets).unwrap_err();
    assert!(matches!(error, SearchError::UnsupportedOperator { .. }));
}

/// J11-I11 — detection of unsupported field types is deterministic and typed.
#[test]
fn t21_indexed_only_is_visible_after_reopen() {
    let mut document = doc("d", 1);
    set_indexed_only(&mut document, obj(&[("v", u64_value(5))]));
    let (directory, _index) = committed(vec![document]);
    let reopened = Index::open_existing(directory, pr11_schema(), registry()).unwrap();
    assert_eq!(
        search(
            &reopened.snapshot(),
            equals("indexed_only", "$.v", FieldValue::U64(5))
        ),
        ["d"]
    );
}

/// B1-T11 — compaction rebuilds a wide indexed-but-not-stored JSON field exactly.
#[test]
fn b1_compact_wide_indexed_only_json() {
    let mut wide = doc("wide", 2);
    let entries: Vec<(String, JsonValue)> = (0..2_000u64)
        .map(|index| (format!("k{index:05}"), u64_value(index)))
        .collect();
    set_indexed_only(&mut wide, JsonValue::Object(entries));

    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        writer.insert(body_doc("a", 1, 1)).unwrap();
        writer.insert(wide).unwrap();
        writer.insert(body_doc("b", 3, 3)).unwrap();
        writer.commit().unwrap();
        // Drop a physical doc so compaction remaps the surviving documents.
        writer
            .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
            .unwrap();
        writer.commit().unwrap();
        let outcome = writer.compact().unwrap();
        assert!(!outcome.no_op);
    }
    let reopened = reopen(directory);
    let snapshot = reopened.snapshot();
    assert_eq!(
        search(&snapshot, exists("indexed_only", "$.k00000")),
        ["wide"]
    );
    assert_eq!(
        search(
            &snapshot,
            equals("indexed_only", "$.k01999", FieldValue::U64(1_999))
        ),
        ["wide"]
    );
    assert!(
        search(
            &snapshot,
            equals("indexed_only", "$.k01999", FieldValue::U64(0))
        )
        .is_empty()
    );
}

/// A `JsonValue` helper that the compiler must see used (avoids unused warnings).
#[allow(dead_code)]
fn unused_json_marker() -> JsonValue {
    JsonValue::Null
}
