//! PR 9 lossless compaction (T20–T24, T26).

mod pr09_common;

use std::collections::BTreeMap;
use std::sync::Arc;

use pr09_common::{create, doc, hit_keys, memory, pr09_registry, pr09_schema, search, term};

use quervant_core::contract::document::{
    DocumentKey, FieldValues, IdempotencyKey, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::index::Index;
use quervant_core::segment::SegmentReader;
use quervant_core::storage::Directory;

/// Build a two-segment committed index with one dead document and a replay entry.
fn fixture() -> (Arc<dyn Directory>, Index) {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .apply(
            MutationRequest::insert(doc("a", "alpha one", "quick brown fox jumps", "rust", 1))
                .with_idempotency_key(IdempotencyKey::new("retention-token").unwrap()),
        )
        .unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "b",
            "beta two",
            "quick brown dog sleeps",
            "cpp",
            2,
        )))
        .unwrap();
    writer.flush().unwrap();
    writer
        .apply(MutationRequest::insert(doc(
            "c",
            "gamma three",
            "quick brown fox runs",
            "rust",
            3,
        )))
        .unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("b").unwrap()))
        .unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();
    (directory, index)
}

fn body_phrase() -> Query {
    Query::Phrase {
        field: "body".into(),
        terms: vec!["quick".into(), "brown".into(), "fox".into()],
    }
}

fn physical_docs(snapshot: &quervant_core::index::ReaderSnapshot) -> u64 {
    snapshot.segments().iter().map(|s| s.doc_count()).sum()
}

// T20 — indexed-but-not-stored phrase/positions survive compaction.
#[test]
fn t20_indexed_not_stored_phrase_survives_merge() {
    let (_, index) = fixture();
    let mut writer = index.writer().unwrap();
    let before = hit_keys(&writer.reader(), &body_phrase());
    assert_eq!(before, ["a", "c"]);
    let outcome = writer.compact().unwrap();
    assert!(!outcome.no_op);
    assert_eq!(outcome.documents, 2);
    assert_eq!(hit_keys(&writer.reader(), &body_phrase()), ["a", "c"]);
    // Fuzzy on the indexed-not-stored field still works after the merge.
    let fuzzy = Query::Fuzzy {
        field: "body".into(),
        value: "jumps".into(),
        max_edits: 1,
        transpositions: true,
    };
    assert_eq!(hit_keys(&writer.reader(), &fuzzy), ["a"]);
}

// T21 — typed columns, stored values and null/missing states survive compaction.
#[test]
fn t21_columns_and_stored_values_survive_merge() {
    let (_, index) = fixture();
    let mut writer = index.writer().unwrap();
    writer.compact().unwrap();
    let snapshot = writer.reader();
    assert_eq!(snapshot.segment_count(), 1);
    let segment = &snapshot.segments()[0];
    let reader = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits()).unwrap();
    let tag_id = reader.schema().field_id("tag").unwrap();
    let n_id = reader.schema().field_id("n").unwrap();
    assert_eq!(reader.stored_doc(0).unwrap().key.as_str(), "a");
    assert_eq!(reader.stored_doc(1).unwrap().key.as_str(), "c");
    assert_eq!(
        reader.stored_doc(0).unwrap().get(tag_id),
        FieldValues::Single(quervant_core::contract::value::FieldValue::Keyword(
            "rust".into()
        ))
    );
    assert_eq!(
        reader.column_value(n_id, 1).unwrap(),
        Some(FieldValues::Single(
            quervant_core::contract::value::FieldValue::I64(3)
        ))
    );
}

// T22 — logical keys, revisions, tombstones and the replay ledger survive.
#[test]
fn t22_revisions_tombstones_and_replay_survive_merge() {
    let (_, index) = fixture();
    let mut writer = index.writer().unwrap();
    writer.compact().unwrap();
    let request =
        MutationRequest::insert(doc("a", "alpha one", "quick brown fox jumps", "rust", 1))
            .with_idempotency_key(IdempotencyKey::new("retention-token").unwrap());
    let replay = writer.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
    // The tombstoned key can be reinserted with the next revision.
    let inserted = writer
        .apply(MutationRequest::insert(doc(
            "b",
            "beta again",
            "",
            "cpp",
            9,
        )))
        .unwrap();
    assert_eq!(inserted.revision, Some(3));
}

// T23 — compaction removes dead physical documents and remaps pointers.
#[test]
fn t23_merge_removes_dead_docs() {
    let (_, index) = fixture();
    let mut writer = index.writer().unwrap();
    let before = physical_docs(&writer.reader());
    assert_eq!(before, 3);
    writer.compact().unwrap();
    let after = physical_docs(&writer.reader());
    assert_eq!(after, 2);
    assert!(!hit_keys(&writer.reader(), &term("beta")).contains(&"b".to_owned()));
}

// T24 — before/after merge hit sets and BM25 scores are equivalent.
#[test]
fn t24_merge_scores_equivalent() {
    let (_, index) = fixture();
    let mut writer = index.writer().unwrap();
    let score_map = |writer: &quervant_core::index::IndexWriter| -> BTreeMap<String, f64> {
        search(&writer.reader(), &term("quick"))
            .hits
            .into_iter()
            .map(|hit| (hit.key.as_str().to_owned(), hit.score))
            .collect()
    };
    let before = score_map(&writer);
    writer.compact().unwrap();
    let after = score_map(&writer);
    assert_eq!(
        before.keys().collect::<Vec<_>>(),
        after.keys().collect::<Vec<_>>()
    );
    for (key, score) in &before {
        assert!((score - after[key]).abs() < 1e-9, "score drift for {key}");
    }
}

// T26 — an old PIT remains valid across compact and writer close.
#[test]
fn t26_old_pit_survives_compact_and_close() {
    let (directory, index) = fixture();
    let mut writer = index.writer().unwrap();
    let pit = writer.pin().unwrap();
    writer.compact().unwrap();
    assert_eq!(hit_keys(pit.snapshot(), &body_phrase()), ["a", "c"]);
    drop(pit);
    writer.close().unwrap();
    let reopened = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&reopened.snapshot(), &body_phrase()), ["a", "c"]);
}
