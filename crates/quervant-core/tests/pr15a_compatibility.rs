//! PR 15A — compatibility and durability cross-combinations (C01–C03).
//!
//! These tests use the frozen `pr15a_v1` schema and the existing native
//! filesystem `FsDirectory`. Historical golden bytes are referenced unchanged;
//! no fixture is regenerated or rewritten here.

mod pr14_common;
mod pr15a_common;

use std::sync::Arc;

use pr14_common::registry;
use pr15a_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::batch::{BatchBudget, BatchQueryRequest, PerQueryOutcome};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{DocumentKey, FieldValues, IdempotencyKey};
use quervant_core::contract::mutation::{
    MutationAction, MutationBatch, MutationCommand, MutationTarget,
};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::Timestamp;
use quervant_core::contract::value::{FieldValue, JsonValue};
use quervant_core::index::{Index, PitHandle};
use quervant_core::search::{
    SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch_pinned,
};
use quervant_core::segment::format::{FEATURE_JSON_PATHS, sha256};
use quervant_core::segment::{SectionKind, SegmentLimits, parse_container};
use quervant_core::storage::{Directory, FsDirectory};

const GOLDEN: &[u8] = include_bytes!("fixtures/segment/json_paths_golden.seg");
const GOLDEN_SHA256: [u8; 32] = [
    0x05, 0x28, 0xa6, 0x2c, 0xdb, 0x02, 0xfc, 0xd0, 0x87, 0x54, 0xd5, 0x77, 0x6f, 0x23, 0xbd, 0x16,
    0xde, 0x78, 0x7f, 0x78, 0x85, 0x97, 0xad, 0xe9, 0x3d, 0x5d, 0xfb, 0xc6, 0x5c, 0x30, 0xa0, 0x2f,
];

const NOW: i64 = 1_000;
const DEADLINE: i64 = 10_000;

fn policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 30)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 30)
            .unwrap(),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

fn pinned_all(pit: &PitHandle) -> Vec<String> {
    let mut request = quervant_core::contract::batch::QueryRequest::new(
        quervant_core::contract::query::Query::MatchAll,
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.top_k = TopK::new(50).expect("top-k");
    let response = execute_batch_pinned(
        pit,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![request], Some(pit.id().clone()), BatchBudget::new(8)),
        &policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
        Timestamp::from_micros(NOW),
        Timestamp::from_micros(DEADLINE),
    )
    .expect("pinned batch");
    match response.slot(0) {
        Some(PerQueryOutcome::Success(response)) => response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect(),
        other => panic!("pinned slot failed: {other:?}"),
    }
}

fn unified(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
) -> UnifiedResponse {
    UnifiedSearcher::new(
        snapshot,
        &pr14_common::schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(request, &Budgets::new(), &CancellationFlag::new())
    .expect("unified search")
}

fn mutated_batch() -> MutationBatch {
    MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("a1").expect("a1")),
            MutationAction::Upsert(mutated_a1()),
        ),
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("b1").expect("b1")),
            MutationAction::Delete,
        ),
        MutationCommand::new(
            MutationTarget::Key(DocumentKey::new("c0").expect("c0")),
            MutationAction::Insert(c0_document()),
        ),
    ])
    .with_idempotency_key(IdempotencyKey::new("pr15a-v1-compat").expect("token"))
}

fn reopen_path(path: &std::path::Path) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(path).expect("fs directory"));
    Index::open_existing(directory, pr14_common::schema(), registry()).expect("reopen")
}

// C01 — current-format FsDirectory reopen + old retained pin + real-schema
// mutation through the new handle.
#[test]
fn a15_c01_reopened_fs_with_retained_pin_and_mutation() {
    let (path, index) = build_fs("c01");
    assert_eq!(index.generation(), Some(2));
    let old_pit = index.pin().expect("old pin");
    drop(index);

    let reopened = reopen_path(&path);
    assert_eq!(reopened.generation(), Some(2));
    let mut writer = reopened.writer().expect("writer");
    writer
        .apply_batch(&mutated_batch(), &CancellationFlag::new())
        .expect("mutation through reopened handle");
    writer.commit().expect("commit generation 3");
    drop(writer);

    assert_eq!(pinned_all(&old_pit), OLD_KEYS);
    assert_eq!(
        old_pit.snapshot().generation(),
        Some(2),
        "old pin remains bound to generation 2"
    );

    let new = reopen_path(&path);
    assert_eq!(new.generation(), Some(3));
    let snapshot = new.snapshot();
    assert_eq!(
        unified(
            &snapshot,
            &UnifiedRequest::new(
                quervant_core::contract::query::Query::MatchAll,
                TopK::new(50).expect("top-k")
            )
        )
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect::<Vec<_>>(),
        NEW_LIVE_KEYS
    );
    assert_eq!(
        unified(
            &snapshot,
            &UnifiedRequest::new(
                quervant_core::contract::query::Query::Term {
                    field: "title".into(),
                    value: FieldValue::Text("alpha".into()),
                },
                TopK::new(50).expect("top-k")
            )
        )
        .total_hits,
        5
    );

    drop(old_pit);
    let _ = std::fs::remove_dir_all(path);
}

// C02 — source projection after reopen and forced compaction.
#[test]
fn a15_c02_projection_after_reopen_and_compaction() {
    let (path, index) = build_fs("c02");
    {
        let mut writer = index.writer().expect("writer");
        writer
            .apply_batch(&mutated_batch(), &CancellationFlag::new())
            .expect("mutation");
        writer.commit().expect("commit");
        writer.compact().expect("compaction");
    }
    drop(index);

    let reopened = reopen_path(&path);
    assert!(reopened.generation().expect("generation") > 2);
    let snapshot = reopened.snapshot();
    let mut request = UnifiedRequest::new(
        quervant_core::contract::query::Query::MatchAll,
        TopK::new(50).expect("top-k"),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Source;
    let response = unified(&snapshot, &request);
    assert_eq!(
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        NEW_LIVE_KEYS
    );

    let state = |key: &str, field: &str| {
        response
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == key)
            .and_then(|hit| hit.fields.iter().find(|(name, _)| name == field))
            .map(|(_, values)| values.clone())
    };
    assert_eq!(
        state("a1", "host"),
        Some(FieldValues::Single(FieldValue::Keyword("h9".into())))
    );
    assert_eq!(
        state("a1", "n"),
        Some(FieldValues::Single(FieldValue::I64(25)))
    );
    let c0_body = state("c0", "body").expect("c0 body");
    assert_eq!(
        c0_body,
        FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![
            (
                "severity".to_owned(),
                JsonValue::Number(quervant_core::contract::value::JsonNumber::I64(6))
            ),
            ("tags".to_owned(), JsonValue::Array(Vec::new())),
        ])))
    );
    let a2_body = state("a2", "body").expect("a2 body");
    let FieldValues::Single(FieldValue::Json(JsonValue::Object(entries))) = a2_body else {
        panic!("a2 body must be a stored JSON object");
    };
    assert!(matches!(
        entries
            .iter()
            .find(|(name, _)| name == "tags")
            .map(|(_, value)| value),
        Some(JsonValue::Array(values)) if values.is_empty()
    ));

    let _ = std::fs::remove_dir_all(path);
}

// C03 — existing historical golden fixture digest, unchanged bytes.
#[test]
fn a15_c03_historical_json_segment_digest_unchanged() {
    assert_eq!(
        sha256(GOLDEN),
        GOLDEN_SHA256,
        "historical fixture bytes must not be rewritten"
    );
    let limits = SegmentLimits::default();
    let view = parse_container(GOLDEN, &limits).expect("golden container");
    assert!(view.required_features().contains(&(FEATURE_JSON_PATHS, 1)));
    assert!(view.entry(SectionKind::JsonPaths).is_some());
    assert_eq!(view.doc_count(), 2);
    // Decode/behaviour reuse: `pr14_storage_vertical::b18_b19` and
    // `pr11_json_corruption::t14` are executed in the same validation run.
}
