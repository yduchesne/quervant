//! M3 atomic delete-by-query integration tests (QMA-001 / M3).
//!
//! Expected key sets are hand-enumerated from the shared PR 14 fixture corpus;
//! production selection is never used to derive its own expectation.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, IdempotencyKey};
use quervant_core::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationBatchResponse, MutationCommand,
    MutationKeyOutcome, MutationPrecondition, MutationRejection, MutationTarget, PatchOperation,
    QueryMutationSelector,
};
use quervant_core::contract::query::{Bound, GeoBoundingBox, GeoRadius, JsonPathExpr, Query};
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue};
use quervant_core::index::{Index, IndexLimits, IndexWriter, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).unwrap()
}

fn selector(
    query: Query,
    max_matches: u64,
    expected_generation: Option<u64>,
) -> QueryMutationSelector {
    QueryMutationSelector {
        query,
        max_matches,
        expected_generation,
    }
}

fn query_delete(selector: QueryMutationSelector) -> MutationBatch {
    MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector),
        MutationAction::Delete,
    )])
}

fn tokens(selector: QueryMutationSelector, token: &str) -> MutationBatch {
    query_delete(selector).with_idempotency_key(IdempotencyKey::new(token).unwrap())
}

fn setup(
    docs: Vec<quervant_core::contract::document::Document>,
) -> (Arc<dyn Directory>, IndexWriter) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    for document in docs {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    (directory, writer)
}

fn live_keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let request = UnifiedRequest::new(query, TopK::new(1_000).unwrap());
    let response = UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search");
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

fn outcome_keys(response: &MutationBatchResponse) -> Vec<Vec<String>> {
    response
        .outcomes
        .iter()
        .map(|outcome| {
            outcome
                .keys
                .iter()
                .map(|key: &MutationKeyOutcome| key.key.as_str().to_owned())
                .collect()
        })
        .collect()
}

fn term(text: &str) -> Query {
    Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text(text.into()),
    }
}

fn n_range(lower: i64, upper: i64) -> Query {
    Query::Range {
        field: "n".to_owned(),
        lower: Bound::Included(FieldValue::I64(lower)),
        upper: Bound::Included(FieldValue::I64(upper)),
    }
}

fn geo_radius() -> Query {
    Query::GeoRadius {
        field: "loc".to_owned(),
        radius: GeoRadius::new(GeoPoint::new(0.0, 0.0).unwrap(), 10_000.0).unwrap(),
    }
}

fn corpus() -> Vec<quervant_core::contract::document::Document> {
    let mut d1 = doc("d1");
    set(&mut d1, "title", FieldValue::Text("alpha beta".to_owned()));
    set(&mut d1, "n", FieldValue::I64(1));
    set(&mut d1, "body", FieldValue::Json(obj_num("k", 1)));
    set(
        &mut d1,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.0, 0.0).unwrap()),
    );
    let mut d2 = doc("d2");
    set(&mut d2, "title", FieldValue::Text("alpha gamma".to_owned()));
    set(&mut d2, "n", FieldValue::I64(5));
    set(&mut d2, "body", FieldValue::Json(obj_num("k", 2)));
    set(
        &mut d2,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.01, 0.01).unwrap()),
    );
    let mut d3 = doc("d3");
    set(&mut d3, "title", FieldValue::Text("beta gamma".to_owned()));
    set(&mut d3, "n", FieldValue::I64(9));
    set(&mut d3, "body", FieldValue::Json(obj_num("k", 3)));
    set(
        &mut d3,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.02, 0.02).unwrap()),
    );
    let mut d4 = doc("d4");
    set(&mut d4, "title", FieldValue::Text("delta".to_owned()));
    set(&mut d4, "n", FieldValue::I64(12));
    set(&mut d4, "body", FieldValue::Json(obj_num("k", 4)));
    set(
        &mut d4,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(10.0, 10.0).unwrap()),
    );
    vec![d1, d2, d3, d4]
}

fn obj_num(member: &str, value: i64) -> JsonValue {
    JsonValue::Object(vec![(
        member.to_owned(),
        JsonValue::Number(JsonNumber::I64(value)),
    )])
}

// ---------------------------------------------------------------------------
// Target/action matrix and selector shape
// ---------------------------------------------------------------------------

#[test]
fn m3_t01_query_delete_only() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    let unsupported = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector(term("alpha"), 10, None)),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "title".to_owned(),
            }],
        }),
    )]);
    assert!(matches!(
        writer.apply_batch(&unsupported, &cancel).unwrap_err(),
        quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::UnsupportedTargetAction { .. }
        }
    ));

    let zero_bound = query_delete(selector(term("alpha"), 0, None));
    assert!(matches!(
        writer.apply_batch(&zero_bound, &cancel).unwrap_err(),
        quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::InvalidBatch { .. }
        }
    ));

    let response = writer
        .apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel)
        .unwrap();
    assert_eq!(
        outcome_keys(&response),
        [vec!["d1".to_owned(), "d2".to_owned()]]
    );
    assert_eq!(response.outcomes[0].matched, 2);
}

#[test]
fn m3_t02_committed_selection_excludes_pending_and_volatile_changes() {
    let (_directory, mut writer) = setup(vec![corpus()[0].clone()]);
    let cancel = CancellationFlag::new();

    // A pending, uncommitted matching insert is not in the committed selection.
    let pending = corpus()[1].clone();
    writer.insert(pending.clone()).unwrap();
    writer.refresh().unwrap();
    let response = writer
        .apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel)
        .unwrap();
    assert_eq!(outcome_keys(&response), [vec!["d1".to_owned()]]);
    let view = writer.refresh().unwrap();
    assert_eq!(
        live_keys(&view, term("alpha")),
        ["d2".to_owned()],
        "the pending insert remains live"
    );

    // Once committed, the same selector includes both keys.
    writer.commit().unwrap();
    let response = writer
        .apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel)
        .unwrap();
    assert_eq!(outcome_keys(&response), [vec!["d2".to_owned()]]);
    let view = writer.refresh().unwrap();
    assert!(live_keys(&view, term("alpha")).is_empty());
}

#[test]
fn m3_t03_complete_membership_for_mixed_predicates() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    let mixed = Query::And(vec![
        Query::Or(vec![
            term("alpha"),
            Query::JsonPathExists {
                field: "body".to_owned(),
                path: JsonPathExpr::parse("$.k").unwrap(),
            },
        ]),
        n_range(5, 10),
        Query::Not(Box::new(term("delta"))),
        geo_radius(),
    ]);
    let response = writer
        .apply_batch(&query_delete(selector(mixed, 10, None)), &cancel)
        .unwrap();
    // Independent hand enumeration: d2 matches alpha, n=5 and the radius; d3
    // matches the JSON-exists branch, n=9 and the radius but not delta.
    assert_eq!(
        outcome_keys(&response),
        [vec!["d2".to_owned(), "d3".to_owned()]]
    );
}

#[test]
fn m3_t04_bbox_and_json_predicates_are_exact() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    let bbox = Query::GeoBoundingBox {
        field: "loc".to_owned(),
        bbox: GeoBoundingBox::new(-0.1, -0.1, 0.1, 0.1).unwrap(),
    };
    let response = writer
        .apply_batch(&query_delete(selector(bbox, 10, None)), &cancel)
        .unwrap();
    assert_eq!(
        outcome_keys(&response),
        [vec!["d1".to_owned(), "d2".to_owned(), "d3".to_owned()]]
    );

    let json = Query::JsonPathEquals {
        field: "body".to_owned(),
        path: JsonPathExpr::parse("$.k").unwrap(),
        value: FieldValue::I64(4),
    };
    let response = writer
        .apply_batch(&query_delete(selector(json, 10, None)), &cancel)
        .unwrap();
    assert_eq!(outcome_keys(&response), [vec!["d4".to_owned()]]);
}

#[test]
fn m3_t05_multiple_segments_and_versions_dedupe_by_logical_key() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    // Create a newer physical version for d1 and commit it.
    let mut replacement = doc("d1");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("alpha beta".to_owned()),
    );
    set(&mut replacement, "n", FieldValue::I64(2));
    set(&mut replacement, "body", FieldValue::Json(obj_num("k", 1)));
    set(
        &mut replacement,
        "loc",
        FieldValue::GeoPoint(GeoPoint::new(0.0, 0.0).unwrap()),
    );
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("d1")),
                MutationAction::Upsert(replacement),
            )]),
            &cancel,
        )
        .unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();

    let response = writer
        .apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel)
        .unwrap();
    assert_eq!(
        outcome_keys(&response),
        [vec![
            "d1".to_owned(),
            "d2".to_owned(),
            "d3".to_owned(),
            "d4".to_owned()
        ]]
    );
    let revisions: Vec<Option<u64>> = response.outcomes[0]
        .keys
        .iter()
        .map(|outcome| outcome.revision)
        .collect();
    assert_eq!(revisions, [Some(3), Some(2), Some(2), Some(2)]);
    let view = writer.refresh().unwrap();
    assert!(live_keys(&view, Query::MatchAll).is_empty());
}

#[test]
fn m3_t06_more_than_page_size_is_not_truncated() {
    let mut docs = Vec::new();
    for index in 0..25 {
        let mut document = doc(&format!("p{index:02}"));
        set(
            &mut document,
            "title",
            FieldValue::Text("page alpha".to_owned()),
        );
        set(&mut document, "n", FieldValue::I64(index));
        docs.push(document);
    }
    let (_directory, mut writer) = setup(docs);
    let cancel = CancellationFlag::new();
    let response = writer
        .apply_batch(&query_delete(selector(term("alpha"), 100, None)), &cancel)
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 25);
    assert_eq!(response.outcomes[0].keys.len(), 25);
    let view = writer.refresh().unwrap();
    assert!(live_keys(&view, term("alpha")).is_empty());
}

#[test]
fn m3_t07_selector_and_writer_bounds_fail_closed() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    let exact = writer
        .apply_batch(&query_delete(selector(term("alpha"), 2, None)), &cancel)
        .unwrap();
    assert_eq!(exact.outcomes[0].matched, 2);
    let after_exact = writer.refresh().unwrap();

    let one_over = writer.apply_batch(&query_delete(selector(Query::MatchAll, 3, None)), &cancel);
    assert!(matches!(
        one_over,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 3,
                matched: 4
            }
        })
    ));
    assert_eq!(
        live_keys(&after_exact, Query::MatchAll),
        ["d3".to_owned(), "d4".to_owned()],
        "the failed one-over selector installed nothing"
    );
}

#[test]
fn m3_t08_zero_writer_bound_and_cumulative_batch_bound() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default()
            .with_max_query_matches(0)
            .with_max_batch_keys(4),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();

    let zero = writer.apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel);
    assert!(matches!(
        zero,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 0,
                matched: 1
            }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 4);
}

// ---------------------------------------------------------------------------
// Generation, revision, overlap and atomicity
// ---------------------------------------------------------------------------

#[test]
fn m3_t09_generation_precondition() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let generation = writer.generation().unwrap();

    let stale = writer.apply_batch(
        &query_delete(selector(term("alpha"), 10, Some(generation - 1))),
        &cancel,
    );
    assert!(matches!(
        stale,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::StaleSelection
        })
    ));

    let response = writer
        .apply_batch(
            &query_delete(selector(term("alpha"), 10, Some(generation))),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 2);

    // Empty committed view: `None` is a valid no-op, `Some(1)` is stale.
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut empty = index.writer().unwrap();
    let zero = empty
        .apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel)
        .unwrap();
    assert_eq!(zero.outcomes[0].matched, 0);
    assert!(matches!(
        empty.apply_batch(
            &query_delete(selector(Query::MatchAll, 10, Some(1))),
            &cancel
        ),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::StaleSelection
        })
    ));
}

#[test]
fn m3_t10_pending_and_flushed_newer_revision_conflict() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let before = live_keys(&writer.reader(), Query::MatchAll);

    let mut newer = doc("d1");
    set(
        &mut newer,
        "title",
        FieldValue::Text("alpha beta".to_owned()),
    );
    set(&mut newer, "n", FieldValue::I64(2));
    let update = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("d1")),
        MutationAction::Upsert(newer),
    )]);
    writer.apply_batch(&update, &cancel).unwrap();

    let pending_conflict =
        writer.apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel);
    assert!(matches!(
        pending_conflict,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);

    writer.flush().unwrap();
    let flushed_conflict =
        writer.apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel);
    assert!(matches!(
        flushed_conflict,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
}

#[test]
fn m3_t11_earlier_explicit_command_and_overlapping_selectors_conflict() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let before = live_keys(&writer.reader(), Query::MatchAll);

    let mut replacement = doc("d1");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("alpha beta".to_owned()),
    );
    set(&mut replacement, "n", FieldValue::I64(2));
    let staged = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("d1")),
            MutationAction::Upsert(replacement),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
    ]);
    assert!(matches!(
        writer.apply_batch(&staged, &cancel),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);

    let overlap = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
    ]);
    assert!(matches!(
        writer.apply_batch(&overlap, &cancel),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);

    let disjoint = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(term("delta"), 10, None)),
            MutationAction::Delete,
        ),
    ]);
    let response = writer.apply_batch(&disjoint, &cancel).unwrap();
    assert_eq!(
        outcome_keys(&response),
        [
            vec!["d1".to_owned(), "d2".to_owned()],
            vec!["d4".to_owned()]
        ]
    );
    let view = writer.refresh().unwrap();
    assert_eq!(
        live_keys(&view, Query::MatchAll),
        ["d3".to_owned()],
        "both disjoint query commands were admitted atomically"
    );
}

#[test]
fn m3_t12_late_failure_rolls_back_and_retry_succeeds() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let before = live_keys(&writer.reader(), Query::MatchAll);

    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Key(key("d3")),
            MutationAction::Insert(doc("d3")),
        ),
    ]);
    assert!(writer.apply_batch(&batch, &cancel).is_err());
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);

    let retry = writer
        .apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel)
        .unwrap();
    assert_eq!(retry.outcomes[0].matched, 2);
}

#[test]
fn m3_t13_zero_match_is_a_replayable_noop() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let batch = tokens(selector(term("absent"), 10, None), "m3-zero");
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes[0].matched, 0);
    assert!(first.outcomes[0].keys.is_empty());
    assert!(!first.replayed);
    writer.commit().unwrap();

    // Change the committed generation so the same selector would now match.
    let mut added = doc("later");
    set(&mut added, "title", FieldValue::Text("absent".to_owned()));
    writer.insert(added).unwrap();
    writer.commit().unwrap();
    assert_eq!(
        live_keys(&writer.reader(), term("absent")),
        ["later".to_owned()]
    );

    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, 0);
    assert!(replay.outcomes[0].keys.is_empty());
    assert_eq!(
        live_keys(&writer.reader(), term("absent")),
        ["later".to_owned()],
        "replay never re-runs the selector"
    );
}

#[test]
fn m3_t14_same_token_with_different_query_conflicts_before_selection() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let first = tokens(selector(term("alpha"), 10, None), "m3-token");
    writer.apply_batch(&first, &cancel).unwrap();
    writer.commit().unwrap();

    let changed_query = tokens(selector(term("delta"), 10, None), "m3-token");
    assert!(matches!(
        writer.apply_batch(&changed_query, &cancel),
        Err(quervant_core::index::IndexError::IdempotencyConflict { .. })
    ));
    let changed_bound = tokens(selector(term("alpha"), 9, None), "m3-token");
    assert!(matches!(
        writer.apply_batch(&changed_bound, &cancel),
        Err(quervant_core::index::IndexError::IdempotencyConflict { .. })
    ));
    let changed_generation = tokens(selector(term("alpha"), 10, Some(1)), "m3-token");
    assert!(matches!(
        writer.apply_batch(&changed_generation, &cancel),
        Err(quervant_core::index::IndexError::IdempotencyConflict { .. })
    ));
}

#[test]
fn m3_t15_pit_and_previous_generation_are_immutable() {
    let (directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let before = writer.reader();
    let pinned = writer.pin().unwrap();

    writer
        .apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancel)
        .unwrap();
    let volatile = writer.refresh().unwrap();
    assert!(live_keys(&volatile, term("alpha")).is_empty());
    writer.commit().unwrap();
    writer.close().unwrap();

    assert_eq!(
        live_keys(&before, term("alpha")),
        ["d1".to_owned(), "d2".to_owned()],
        "pre-delete reader is immutable"
    );
    assert_eq!(live_keys(pinned.snapshot(), term("alpha")).len(), 2);
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    assert!(live_keys(&reopened.snapshot(), term("alpha")).is_empty());
}

#[test]
fn m3_t16_filesystem_commit_reopen_and_replay() {
    let root = std::env::temp_dir().join(format!("quervant-m3-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    let batch = tokens(selector(term("alpha"), 10, None), "m3-fs");
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    assert!(live_keys(&writer.reader(), term("alpha")).is_empty());
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(outcome_keys(&replay), outcome_keys(&first));
    writer.close().unwrap();
    let _ = std::fs::remove_dir_all(&root);
}

#[test]
fn m3_t17_preconditions_are_evaluated_per_selected_key() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();

    let must_exist = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        )
        .with_precondition(MutationPrecondition::MustExist),
    ]);
    let response = writer.apply_batch(&must_exist, &cancel).unwrap();
    assert_eq!(response.outcomes[0].matched, 2);
    let after_success = writer.refresh().unwrap();

    let must_not_exist = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("gamma"), 10, None)),
            MutationAction::Delete,
        )
        .with_precondition(MutationPrecondition::MustNotExist),
    ]);
    assert!(matches!(
        writer.apply_batch(&must_not_exist, &cancel),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));

    let wrong_revision = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("delta"), 10, None)),
            MutationAction::Delete,
        )
        .with_precondition(MutationPrecondition::ExpectedRevision(99)),
    ]);
    assert!(matches!(
        writer.apply_batch(&wrong_revision, &cancel),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    assert_eq!(
        live_keys(&after_success, Query::MatchAll),
        ["d3".to_owned(), "d4".to_owned()]
    );
}

#[test]
fn m3_t18_cancellation_and_query_validation_are_atomic() {
    let (_directory, mut writer) = setup(corpus());
    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    let before = live_keys(&writer.reader(), Query::MatchAll);
    assert!(matches!(
        writer.apply_batch(&query_delete(selector(term("alpha"), 10, None)), &cancelled),
        Err(quervant_core::index::IndexError::Cancelled)
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);

    let cancel = CancellationFlag::new();
    let invalid = Query::And(vec![]);
    assert!(matches!(
        writer.apply_batch(&query_delete(selector(invalid, 10, None)), &cancel),
        Err(quervant_core::index::IndexError::Contract(_))
    ));
}

#[test]
fn m3_t19_response_and_replay_limits_reject_whole_batch() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default().with_max_batch_response_bytes(1),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    let result = writer.apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel);
    assert!(matches!(
        result,
        Err(quervant_core::index::IndexError::ResourceLimit { .. })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 4);
}

#[test]
fn m3_t20_cumulative_query_keys_bound_fails_before_installation() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default().with_max_batch_keys(3),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(term("alpha"), 10, None)),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(term("gamma"), 10, None)),
            MutationAction::Delete,
        ),
    ]);
    // alpha selects 2 keys and gamma selects 2 distinct keys: each passes the
    // selector bound, but the cumulative 4 exceeds max_batch_keys=3.
    assert!(matches!(
        writer.apply_batch(&batch, &cancel),
        Err(quervant_core::index::IndexError::ResourceLimit {
            limit: 3,
            requested: 4
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 4);
}

#[test]
fn m3_t21_convenience_api_and_durable_replay() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let response = writer
        .delete_by_query(selector(term("alpha"), 10, None), &cancel)
        .unwrap();
    assert_eq!(
        outcome_keys(&response),
        [vec!["d1".to_owned(), "d2".to_owned()]]
    );
    let view = writer.refresh().unwrap();
    assert!(live_keys(&view, term("alpha")).is_empty());

    let batch = tokens(selector(term("delta"), 10, None), "m3-convenience");
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    writer.commit().unwrap();
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(outcome_keys(&replay), outcome_keys(&first));
}

/// Deterministic seeded model sequence mixing explicit updates, refresh,
/// commit, delete-by-query and replay against a small independent state machine.
#[test]
fn m3_t22_seeded_reference_model_sequence() {
    const SEED: u64 = 0x5EED_0003;

    #[derive(Clone, Copy)]
    struct Lcg(u64);
    impl Lcg {
        fn next(&mut self) -> u64 {
            self.0 = self
                .0
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            self.0
        }
    }

    fn group_for(key: &str) -> &'static str {
        match key {
            "a" | "c" => "even",
            _ => "odd",
        }
    }

    fn document_for(key: &str) -> quervant_core::contract::document::Document {
        let mut document = doc(key);
        set(
            &mut document,
            "title",
            FieldValue::Text(format!("group {}", group_for(key))),
        );
        document
    }

    fn model_live(model: &std::collections::BTreeMap<String, (u64, bool)>) -> Vec<String> {
        model
            .iter()
            .filter(|(_, (_, live))| *live)
            .map(|(key, _)| key.clone())
            .collect()
    }

    fn model_group(
        model: &std::collections::BTreeMap<String, (u64, bool)>,
        group: &str,
    ) -> Vec<String> {
        model
            .iter()
            .filter(|(key, (_, live))| *live && group_for(key) == group)
            .map(|(key, _)| key.clone())
            .collect()
    }

    let (_directory, mut writer) = setup(vec![
        document_for("a"),
        document_for("b"),
        document_for("c"),
        document_for("d"),
    ]);
    let cancel = CancellationFlag::new();
    let mut model: std::collections::BTreeMap<String, (u64, bool)> = ["a", "b", "c", "d"]
        .into_iter()
        .map(|key| (key.to_owned(), (1, true)))
        .collect();
    let mut replays: Vec<(MutationBatch, MutationBatchResponse)> = Vec::new();
    let mut rng = Lcg(SEED);

    for step in 0..24u64 {
        let keys = ["a", "b", "c", "d"];
        let selected_key = keys[(rng.next() % keys.len() as u64) as usize];
        let choice = rng.next() % 4;
        match choice {
            0 => {
                let document = document_for(selected_key);
                writer
                    .apply_batch(
                        &MutationBatch::new(vec![MutationCommand::new(
                            MutationTarget::Key(key(selected_key)),
                            MutationAction::Upsert(document),
                        )]),
                        &cancel,
                    )
                    .unwrap();
                let entry = model.get_mut(selected_key).unwrap();
                entry.0 += 1;
                entry.1 = true;
                writer.commit().unwrap();
            }
            1 => {
                writer
                    .apply_batch(
                        &MutationBatch::new(vec![MutationCommand::new(
                            MutationTarget::Key(key(selected_key)),
                            MutationAction::Delete,
                        )]),
                        &cancel,
                    )
                    .unwrap();
                let entry = model.get_mut(selected_key).unwrap();
                entry.0 += 1;
                entry.1 = false;
                writer.commit().unwrap();
            }
            2 => {
                let group = if rng.next() % 2 == 0 { "even" } else { "odd" };
                let expected = model_group(&model, group);
                let batch = tokens(selector(term(group), 100, None), &format!("m3-seed-{step}"));
                let response = writer.apply_batch(&batch, &cancel).unwrap();
                assert_eq!(outcome_keys(&response), vec![expected.clone()]);
                for selected in &expected {
                    let entry = model.get_mut(selected).unwrap();
                    entry.0 += 1;
                    entry.1 = false;
                }
                writer.commit().unwrap();
                replays.push((batch, response));
            }
            _ => {
                if let Some((batch, original)) = replays.last() {
                    let replay = writer.apply_batch(batch, &cancel).unwrap();
                    assert!(replay.replayed);
                    assert_eq!(outcome_keys(&replay), outcome_keys(original));
                    assert_eq!(replay.outcomes[0].matched, original.outcomes[0].matched);
                } else {
                    writer.commit().unwrap();
                }
            }
        }

        let view = writer.refresh().unwrap();
        assert_eq!(
            live_keys(&view, Query::MatchAll),
            model_live(&model),
            "step {step}"
        );
        assert_eq!(
            live_keys(&view, term("even")),
            model_group(&model, "even"),
            "step {step}"
        );
        assert_eq!(
            live_keys(&view, term("odd")),
            model_group(&model, "odd"),
            "step {step}"
        );
    }
}

// ---------------------------------------------------------------------------
// Remote boundary
// ---------------------------------------------------------------------------

fn remote_config(name: &str) -> quervant_core::remote::RemoteConfig {
    quervant_core::remote::RemoteConfig::new(
        quervant_core::remote::RemoteKeyPrefix::parse(format!("m3/{name}-{}", std::process::id()))
            .unwrap(),
        std::env::temp_dir().join(format!("quervant-m3-remote-{name}-{}", std::process::id())),
    )
    .with_transfer(
        quervant_core::remote::RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024)
            .with_chunk_size(32 * 1024)
            .with_max_aggregate_response_bytes(2 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16),
    )
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

#[test]
fn m3_t23_remote_admission_makes_no_remote_calls_and_replays_after_reopen() {
    use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

    let store = Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ));
    let config = remote_config("m3-t23");
    let index = block_on(quervant_core::remote::RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let cancel = CancellationFlag::new();
    let batch = tokens(selector(term("delta"), 10, None), "m3-remote");
    {
        let mut writer = block_on(index.writer()).unwrap();
        for document in corpus() {
            writer.insert(document).unwrap();
        }
        block_on(writer.commit()).unwrap();
        let puts = store.put_calls();
        let gets = store.get_calls();
        let response = writer
            .delete_by_query(selector(term("alpha"), 10, None), &cancel)
            .unwrap();
        assert_eq!(response.outcomes[0].matched, 2);
        let first = writer.apply_batch(&batch, &cancel).unwrap();
        assert_eq!(first.outcomes[0].matched, 1);
        assert_eq!(store.put_calls(), puts, "admission must not write remotely");
        assert_eq!(store.get_calls(), gets, "admission must not read remotely");
        block_on(writer.commit()).unwrap();
        assert!(store.put_calls() > puts);
    }

    let reopened = block_on(quervant_core::remote::RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert!(live_keys(&reopened.snapshot(), term("alpha")).is_empty());
    let mut writer = block_on(reopened.writer()).unwrap();
    let puts = store.put_calls();
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(store.put_calls(), puts);
}

#[cfg(feature = "s3")]
mod real_rustfs {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn require_env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        assert!(
            endpoint.starts_with("http://"),
            "real RustFS acceptance requires an http:// endpoint"
        );
        (endpoint, bucket, access, secret, region)
    }

    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("m3-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("tokio runtime");
                runtime.block_on(body);
            })
            .expect("spawn");
        handle.join().expect("real RustFS test panicked");
    }

    #[test]
    #[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
    fn m3_t24_real_rustfs_delete_by_query_reopen_and_replay() {
        run(async move {
            let (endpoint, bucket, access, secret, region) = require_env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .expect("valid RustFS config"),
            );
            store.create_bucket_if_absent().await.expect("bucket");

            let run_tag = format!(
                "m3-t24-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            );
            let config = quervant_core::remote::RemoteConfig::new(
                quervant_core::remote::RemoteKeyPrefix::parse(format!("m3/{run_tag}")).unwrap(),
                std::env::temp_dir().join(format!("quervant-m3-rustfs-{run_tag}")),
            )
            .with_transfer(
                quervant_core::remote::RemoteTransferConfig::default()
                    .with_range_threshold(256 * 1024)
                    .with_chunk_size(32 * 1024)
                    .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                    .with_max_total_http_requests(64)
                    .with_max_concurrent_ranges(16),
            );

            let index = quervant_core::remote::RemoteIndex::create(
                Arc::clone(&store) as Arc<S3ObjectStore>,
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("create remote index");
            let cancel = CancellationFlag::new();
            let batch = tokens(
                selector(term("delta"), 10, None),
                &format!("{run_tag}-token"),
            );
            {
                let mut writer = index.writer().await.expect("writer");
                for document in corpus() {
                    writer.insert(document).unwrap();
                }
                writer.commit().await.unwrap();
                let response = writer
                    .delete_by_query(selector(term("alpha"), 10, None), &cancel)
                    .unwrap();
                assert_eq!(response.outcomes[0].matched, 2);
                let response = writer.apply_batch(&batch, &cancel).unwrap();
                assert_eq!(response.outcomes[0].matched, 1);
                writer.commit().await.unwrap();
            }
            let reopened = quervant_core::remote::RemoteIndex::open_existing(
                Arc::clone(&store) as Arc<S3ObjectStore>,
                config,
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("reopen");
            assert!(live_keys(&reopened.snapshot(), term("alpha")).is_empty());
            assert!(live_keys(&reopened.snapshot(), term("delta")).is_empty());
            let mut writer = reopened.writer().await.expect("writer");
            let replay = writer.apply_batch(&batch, &cancel).unwrap();
            assert!(replay.replayed);
        });
    }
}

#[test]
fn m3_t25_replay_does_not_rerun_selector_after_query_changes() {
    let (_directory, mut writer) = setup(corpus());
    let cancel = CancellationFlag::new();
    let batch = tokens(selector(term("alpha"), 10, None), "m3-query-change");
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes[0].matched, 2);
    writer.commit().unwrap();

    let mut later = doc("later");
    set(&mut later, "title", FieldValue::Text("alpha".to_owned()));
    set(&mut later, "n", FieldValue::I64(1));
    writer.insert(later).unwrap();
    writer.commit().unwrap();
    assert_eq!(
        live_keys(&writer.reader(), term("alpha")),
        ["later".to_owned()]
    );

    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(
        outcome_keys(&replay),
        [vec!["d1".to_owned(), "d2".to_owned()]]
    );
    assert_eq!(
        live_keys(&writer.reader(), term("alpha")),
        ["later".to_owned()],
        "durable replay must not delete newly matching documents"
    );
}

#[test]
fn m3_t26_writer_query_bound_exact_and_one_over() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default()
            .with_max_query_matches(2)
            .with_max_batch_keys(10),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();

    assert!(matches!(
        writer.apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel),
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 2,
                matched: 3
            }
        })
    ));

    let exact = writer
        .apply_batch(&query_delete(selector(term("gamma"), 2, None)), &cancel)
        .unwrap();
    assert_eq!(
        outcome_keys(&exact),
        [vec!["d2".to_owned(), "d3".to_owned()]]
    );
}

#[test]
fn m3_t27_replay_key_bound_fails_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default().with_max_batch_replay_keys(1),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    assert!(matches!(
        writer.apply_batch(&query_delete(selector(Query::MatchAll, 10, None)), &cancel),
        Err(quervant_core::index::IndexError::ResourceLimit {
            limit: 1,
            requested: 4
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 4);
}

#[test]
fn m3_t28_query_depth_budget_is_not_bypassed() {
    use quervant_core::contract::budget::{BudgetKind, Budgets};

    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default().with_budgets(
            Budgets::new()
                .with(BudgetKind::QueryDepth, 1)
                .expect("nonzero budget"),
        ),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    for document in corpus() {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    let nested = Query::And(vec![Query::MatchAll, term("alpha")]);
    assert!(matches!(
        writer.apply_batch(&query_delete(selector(nested, 10, None)), &cancel),
        Err(quervant_core::index::IndexError::Contract(_))
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 4);
}

// ---------------------------------------------------------------------------
// M3 R-01 fixup acceptance: one large segment and cross-segment over-limit
// ---------------------------------------------------------------------------

#[test]
fn m3_fixup_t03_one_segment_limit_plus_one() {
    let mut docs = Vec::new();
    for index in 0..12 {
        let mut document = doc(&format!("r{index:02}"));
        set(
            &mut document,
            "title",
            FieldValue::Text("stream alpha".to_owned()),
        );
        set(&mut document, "n", FieldValue::I64(index));
        docs.push(document);
    }
    let (_directory, mut writer) = setup(docs);
    let cancel = CancellationFlag::new();
    let before = live_keys(&writer.reader(), Query::MatchAll);

    let result = writer.apply_batch(&query_delete(selector(term("alpha"), 5, None)), &cancel);
    assert!(matches!(
        result,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 5,
                matched: 6
            }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll), before);
}

#[test]
fn m3_fixup_t05_over_limit_in_later_segment() {
    let mut first = Vec::new();
    for index in 0..4 {
        let mut document = doc(&format!("a{index:02}"));
        set(
            &mut document,
            "title",
            FieldValue::Text("stream alpha".to_owned()),
        );
        first.push(document);
    }
    let (_directory, mut writer) = setup(first);
    let cancel = CancellationFlag::new();
    writer.commit().unwrap();

    let mut second = Vec::new();
    for index in 0..4 {
        let mut document = doc(&format!("b{index:02}"));
        set(
            &mut document,
            "title",
            FieldValue::Text("stream alpha".to_owned()),
        );
        second.push(document);
    }
    for document in second {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();

    let result = writer.apply_batch(&query_delete(selector(term("alpha"), 6, None)), &cancel);
    assert!(matches!(
        result,
        Err(quervant_core::index::IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 6,
                matched: 7
            }
        })
    ));
    assert_eq!(live_keys(&writer.reader(), Query::MatchAll).len(), 8);
}
