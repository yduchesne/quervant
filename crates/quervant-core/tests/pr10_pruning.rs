//! PR 10 T49–T53: conservative time-bound pruning without false negatives.

mod pr10_common;

use std::sync::Arc;

use pr10_common::{Query, Sort, doc, full_doc, match_all_request, set, set_multi, time_range};
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, TypedSearcher};
use quervant_core::storage::Directory;

fn segment(base: i64, batch: usize, index: &Index) {
    let mut writer = index.writer().unwrap();
    for offset in 0..5 {
        writer
            .insert(full_doc(
                &format!("k{batch}-{offset}"),
                "t",
                base + offset,
                0,
                0,
                1.0,
                true,
                "h",
                &["x"],
                "10.0.0.1",
            ))
            .unwrap();
    }
    writer.commit().unwrap();
}

fn segmented() -> (Arc<dyn Directory>, Index) {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    segment(0, 0, &index);
    segment(100, 1, &index);
    segment(200, 2, &index);
    // A fourth segment whose live docs carry no timestamp (unknown bounds).
    {
        let mut writer = index.writer().unwrap();
        let mut document = doc("n0");
        set(&mut document, "host", FieldValue::Keyword("h".into()));
        set_multi(&mut document, "tags", vec![FieldValue::Keyword("x".into())]);
        writer.insert(document).unwrap();
        writer.commit().unwrap();
    }
    let reopened = pr10_common::reopen(directory.clone());
    (directory, reopened)
}

fn search(
    snapshot: &ReaderSnapshot,
    query: Query,
    pruning_disabled: bool,
) -> quervant_core::search::TypedSearchResponse {
    let schema = pr10_common::pr10_schema();
    let cancel = quervant_core::analysis::CancellationFlag::new();
    let mut request = match_all_request(Sort::default(), 100);
    request.query = query;
    TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .with_pruning_disabled(pruning_disabled)
        .search(
            &request,
            &quervant_core::contract::budget::Budgets::new(),
            &cancel,
        )
        .unwrap()
}

// T49 — nonoverlapping segments are skipped and incremented.
#[test]
fn t49_nonoverlap_skip() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    let response = search(&snapshot, time_range("ts", 100, 110), false);
    assert_eq!(pr10_common::hit_keys(&response).len(), 5);
    assert!(response.diagnostics.segments_skipped_by_time >= 2);
}

// T50 — boundary values are not pruned when they can still match.
#[test]
fn t50_boundary_not_pruned() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    // Segment 0 spans `[0, 4]`; end at 100 excludes segment 1's minimum.
    let response = search(&snapshot, time_range("ts", 4, 100), false);
    let keys = pr10_common::hit_keys(&response);
    assert!(keys.contains(&"k0-4".to_owned()));
    assert!(!keys.contains(&"k1-0".to_owned()));
    assert!(response.diagnostics.segments_skipped_by_time >= 1);
}

// T51 — unknown bounds force a scan.
#[test]
fn t51_unknown_bounds_scan() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    let response = search(&snapshot, time_range("ts", 250, 300), false);
    // The unknown-bounds segment must be considered, never skipped as a whole.
    assert!(response.diagnostics.live_documents_examined >= 1);
    assert!(pr10_common::hit_keys(&response).is_empty());
}

// T52 — pruning is only extracted from positive top-level `And` conjuncts.
#[test]
fn t52_and_versus_or_not() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    let and = Query::And(vec![
        time_range("ts", 100, 110),
        pr10_common::i64_range("n", Some(0), Some(1000)),
    ]);
    let response = search(&snapshot, and, false);
    assert_eq!(pr10_common::hit_keys(&response).len(), 5);
    assert!(response.diagnostics.segments_skipped_by_time >= 2);

    // `Or`/`Not` must not enable pruning of the positive branch.
    let or = Query::Or(vec![time_range("ts", 100, 110), time_range("ts", 200, 210)]);
    let response = search(&snapshot, or, false);
    assert_eq!(response.diagnostics.segments_skipped_by_time, 0);
    assert_eq!(pr10_common::hit_keys(&response).len(), 10);

    let not = Query::Not(Box::new(time_range("ts", 100, 110)));
    let response = search(&snapshot, not, false);
    assert_eq!(response.diagnostics.segments_skipped_by_time, 0);
}

// T53 — pruning on/off produces identical logical results for seeded cases.
#[test]
fn t53_pruning_differential() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    for (start, end) in [
        (0i64, 10i64),
        (9, 100),
        (100, 110),
        (0, 300),
        (-50, 5),
        (250, 300),
    ] {
        let on = search(&snapshot, time_range("ts", start, end), false);
        let off = search(&snapshot, time_range("ts", start, end), true);
        assert_eq!(
            pr10_common::hit_keys(&on),
            pr10_common::hit_keys(&off),
            "range [{start},{end})"
        );
        assert_eq!(on.total_hits, off.total_hits);
    }
}

// Sanity: the segmented fixture has the expected four segments.
#[test]
fn segmented_fixture_has_four_segments() {
    let (_directory, index) = segmented();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 4);
}
