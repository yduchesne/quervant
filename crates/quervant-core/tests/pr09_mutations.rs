//! PR 9 mutation admission, revisions, idempotency and durability (T01–T15).

mod pr09_common;

use pr09_common::{create, doc, hit_keys, memory, pr09_registry, pr09_schema, term};

use quervant_core::contract::document::{DocumentKey, IdempotencyKey, MutationRequest};
use quervant_core::index::{Index, IndexError};

fn upsert(
    writer: &mut quervant_core::index::IndexWriter,
    document: quervant_core::contract::document::Document,
) -> u64 {
    writer
        .apply(MutationRequest::upsert(document))
        .expect("upsert")
        .revision
        .expect("revision")
}

fn delete(writer: &mut quervant_core::index::IndexWriter, key: &str) -> u64 {
    writer
        .apply(MutationRequest::delete(DocumentKey::new(key).unwrap()))
        .expect("delete")
        .revision
        .expect("revision")
}

// T01 — insert -> upsert -> delete -> insert, one visible winner.
#[test]
fn t01_insert_upsert_delete_insert_one_winner() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();

    writer
        .apply(MutationRequest::insert(doc("a", "first", "", "x", 1)))
        .unwrap();
    assert_eq!(hit_keys(&writer.refresh().unwrap(), &term("first")), ["a"]);

    upsert(&mut writer, doc("a", "second", "", "x", 2));
    assert_eq!(hit_keys(&writer.refresh().unwrap(), &term("second")), ["a"]);
    assert!(hit_keys(&writer.refresh().unwrap(), &term("first")).is_empty());

    delete(&mut writer, "a");
    assert!(search_all_is_empty(&mut writer));

    writer
        .apply(MutationRequest::insert(doc("a", "third", "", "x", 3)))
        .unwrap();
    assert_eq!(hit_keys(&writer.refresh().unwrap(), &term("third")), ["a"]);
}

fn search_all_is_empty(writer: &mut quervant_core::index::IndexWriter) -> bool {
    use quervant_core::contract::query::Query;
    hit_keys(&writer.refresh().unwrap(), &Query::MatchAll).is_empty()
}

// T02 — revisions strictly increase and are never reused.
#[test]
fn t02_revisions_increase_no_reuse() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    assert_eq!(
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap()
            .revision,
        Some(1)
    );
    assert_eq!(upsert(&mut writer, doc("a", "two", "", "x", 1)), 2);
    assert_eq!(delete(&mut writer, "a"), 3);
    assert_eq!(
        writer
            .apply(MutationRequest::insert(doc("a", "four", "", "x", 1)))
            .unwrap()
            .revision,
        Some(4)
    );
}

// T03 — deleting an absent key allocates a tombstone revision; reinsert advances.
#[test]
fn t03_absent_delete_tombstone_then_reinsert() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    assert_eq!(delete(&mut writer, "ghost"), 1);
    assert_eq!(
        writer
            .apply(MutationRequest::insert(doc("ghost", "back", "", "x", 1)))
            .unwrap()
            .revision,
        Some(2)
    );
}

// T04 — the same key in multiple immutable segments keeps one live pointer.
#[test]
fn t04_same_key_multiple_segments_one_live_pointer() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "old", "", "x", 1)))
        .unwrap();
    writer.flush().unwrap();
    upsert(&mut writer, doc("a", "new", "", "x", 2));
    writer.flush().unwrap();
    writer.commit().unwrap();

    let snapshot = writer.reader();
    assert_eq!(hit_keys(&snapshot, &term("new")), ["a"]);
    assert!(hit_keys(&snapshot, &term("old")).is_empty());
}

// T05 — duplicate live insert is a typed error with no revision advance.
#[test]
fn t05_duplicate_live_insert_error() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    let error = writer
        .apply(MutationRequest::insert(doc("a", "two", "", "x", 2)))
        .unwrap_err();
    assert!(matches!(error, IndexError::DuplicateDocument { .. }));
    assert_eq!(
        writer
            .apply(MutationRequest::upsert(doc("a", "three", "", "x", 3)))
            .unwrap()
            .revision,
        Some(2)
    );
}

// T07 — exact token replay before and after commit returns the original revision.
#[test]
fn t07_idempotent_replay_before_and_after_commit() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    let request = MutationRequest::upsert(doc("a", "one", "", "x", 1))
        .with_idempotency_key(IdempotencyKey::new("token-1").unwrap());
    let first = writer.apply(request.clone()).unwrap();
    assert_eq!(first.revision, Some(1));
    assert!(!first.replayed);
    // Replay within the same writer, before commit.
    let replay = writer.apply(request.clone()).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
    writer.commit().unwrap();
    // Replay against the committed ledger.
    let replay = writer.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
    // No extra physical document was created: the ledger was cleared by commit
    // and the replay did not enqueue a new pending document.
    assert_eq!(writer.pending_documents(), 0);
    assert!(writer.commit().unwrap().no_op);
}

// T08 — token reuse with a different payload is a typed conflict.
#[test]
fn t08_idempotency_conflict() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    let token = || IdempotencyKey::new("token-1").unwrap();
    writer
        .apply(MutationRequest::upsert(doc("a", "one", "", "x", 1)).with_idempotency_key(token()))
        .unwrap();
    let error = writer
        .apply(
            MutationRequest::upsert(doc("a", "different", "", "x", 9))
                .with_idempotency_key(token()),
        )
        .unwrap_err();
    assert!(matches!(error, IndexError::IdempotencyConflict { .. }));
    // Original state is intact and no new revision was allocated.
    assert_eq!(hit_keys(&writer.refresh().unwrap(), &term("one")), ["a"]);
}

// T09 — exact replay survives a restart.
#[test]
fn t09_restart_replay() {
    let directory = memory();
    let request = MutationRequest::upsert(doc("a", "one", "", "x", 1))
        .with_idempotency_key(IdempotencyKey::new("token-1").unwrap());
    {
        let index = create(directory.clone());
        let mut writer = index.writer().unwrap();
        writer.apply(request.clone()).unwrap();
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let replay = writer.apply(request).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.revision, Some(1));
}

// T10 — refresh is volatile; reopening before commit sees the old generation.
#[test]
fn t10_refresh_visibility_vs_commit_durability() {
    let directory = memory();
    {
        let index = create(directory.clone());
        let mut writer = index.writer().unwrap();
        writer.commit().unwrap(); // generation 1, empty
        writer
            .apply(MutationRequest::upsert(doc("a", "uncommitted", "", "x", 1)))
            .unwrap();
        assert_eq!(
            hit_keys(&writer.refresh().unwrap(), &term("uncommitted")),
            ["a"]
        );
    }
    let reopened = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    assert!(hit_keys(&reopened.snapshot(), &term("uncommitted")).is_empty());
}

// T11 — a delete-only commit advances the generation without a new segment.
#[test]
fn t11_delete_only_commit_advances_generation_without_segment() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    let first = writer.commit().unwrap();
    assert_eq!(first.generation, 1);
    assert_eq!(first.segments_added, 1);
    delete(&mut writer, "a");
    let second = writer.commit().unwrap();
    assert_eq!(second.generation, 2);
    assert_eq!(second.segments_added, 0);
    assert!(!second.no_op);
    assert!(hit_keys(&writer.reader(), &term("one")).is_empty());
}

// T14 — an old PIT still sees the previous version after mutation.
#[test]
fn t14_old_pit_sees_previous_version() {
    let directory = memory();
    let index = create(directory);
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "before", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    upsert(&mut writer, doc("a", "after", "", "x", 2));
    writer.commit().unwrap();
    assert_eq!(hit_keys(pit.snapshot(), &term("before")), ["a"]);
    assert!(hit_keys(pit.snapshot(), &term("after")).is_empty());
    assert_eq!(hit_keys(&writer.reader(), &term("after")), ["a"]);
}

// T15 — an old committed Index handle stays fixed; a reopened one sees latest.
#[test]
fn t15_old_handle_stays_fixed_reopen_sees_latest() {
    let directory = memory();
    {
        let index = create(directory.clone());
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "before", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
    }
    let old = Index::open_existing(directory.clone(), pr09_schema(), pr09_registry()).unwrap();
    {
        let mut writer = old.writer().unwrap();
        upsert(&mut writer, doc("a", "after", "", "x", 2));
        writer.commit().unwrap();
    }
    assert_eq!(hit_keys(&old.snapshot(), &term("before")), ["a"]);
    let reopened = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&reopened.snapshot(), &term("after")), ["a"]);
}

// T41 — a second writer is rejected while the first holds the lock.
#[test]
fn t41_competing_writer_is_busy() {
    let directory = memory();
    let index = create(directory);
    let _first = index.writer().unwrap();
    let error = index.writer().unwrap_err();
    assert!(matches!(error, IndexError::WriterBusy));
}
