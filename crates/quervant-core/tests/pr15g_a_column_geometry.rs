//! PR 15G-A — retained immutable column geometry, real-boundary integration.
//!
//! These tests exercise the production writer → commit → snapshot → unified
//! search path (memory and real `FsDirectory`) and compare column access with an
//! independently opened, fully validating `SegmentReader::open` over the exact
//! committed bytes. Expected query sets come from the frozen PR 15A oracle.

mod pr14_common;
mod pr15a_common;

use std::sync::Arc;

use pr14_common::{
    Bound, FieldValue, Query, Sort, SortDirection, SortField, TopK, registry, schema,
};
use pr15a_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::segment::{ColumnReader, SegmentReader};
use quervant_core::storage::Directory;

fn unified_request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"))
}

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn sorted_keys(response: &UnifiedResponse) -> Vec<String> {
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort_unstable();
    keys
}

fn alpha_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn absent_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("absent-term".into()),
    }
}

fn n_range_query() -> Query {
    Query::Range {
        field: "n".into(),
        lower: Bound::Included(FieldValue::I64(25)),
        upper: Bound::Included(FieldValue::I64(60)),
    }
}

fn n_sorted_request() -> UnifiedRequest {
    let mut request = unified_request(Query::MatchAll, 8);
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request
}

fn range_oracle() -> Vec<String> {
    BASE_ROWS
        .iter()
        .filter(|row| (25..=60).contains(&row.n))
        .map(|row| row.key.to_owned())
        .collect()
}

/// Compare every cached column value with an independently validated uncached
/// reader over the exact committed segment bytes.
fn assert_columns_match_uncached(snapshot: &ReaderSnapshot) {
    let mut compared = 0usize;
    for index in 0..snapshot.segment_count() {
        let segment = &snapshot.segments()[index];
        let doc_count = segment.doc_count();
        let guard = snapshot
            .open_segment_reader(index)
            .expect("snapshot reader");
        let cached = guard.reader();
        let uncached = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits())
            .expect("uncached reader");
        let cached_fields = cached
            .open_columns()
            .expect("cached columns")
            .map(|columns| columns.fields())
            .unwrap_or_default();
        let uncached_fields = uncached
            .open_columns()
            .expect("uncached columns")
            .map(|columns| columns.fields())
            .unwrap_or_default();
        assert_eq!(cached_fields, uncached_fields);
        let Some(columns) = uncached.open_columns().expect("uncached columns") else {
            continue;
        };
        for field_id in columns.fields() {
            for doc_id in 0..doc_count {
                assert_eq!(
                    cached.column_value(field_id, doc_id).expect("cached value"),
                    uncached
                        .column_value(field_id, doc_id)
                        .expect("uncached value"),
                    "segment {index} field {field_id} doc {doc_id}"
                );
                compared += 1;
            }
        }
    }
    assert!(compared > 0, "the fixture must expose column values");
}

// GA-I01 — memory index, writer/commit/snapshot, term/absent/range and explicit
// column sort, with column parity to a fresh uncached control.
#[test]
fn ga_i01_memory_snapshot_queries_and_column_parity() {
    let index = build_memory();
    let snapshot = index.snapshot();

    assert_eq!(
        sorted_keys(&search(&snapshot, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
    assert!(
        search(&snapshot, &unified_request(absent_query(), 16))
            .hits
            .is_empty()
    );
    assert_eq!(
        sorted_keys(&search(&snapshot, &unified_request(n_range_query(), 16))),
        range_oracle()
    );
    assert_eq!(
        search(&snapshot, &n_sorted_request())
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        N_ASCENDING_KEYS
    );
    assert_columns_match_uncached(&snapshot);
}

// GA-I02 — real `FsDirectory` commit, process-handle drop, cold reopen and the
// same query set over byte-identical committed segments.
#[test]
fn ga_i02_filesystem_commit_reopen_is_byte_identical() {
    let (path, index) = build_fs("pr15g-a-i02");
    let before = index.snapshot();
    let before_bytes: Vec<Vec<u8>> = before
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    assert_eq!(
        sorted_keys(&search(&before, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
    assert_eq!(
        sorted_keys(&search(&before, &unified_request(n_range_query(), 16))),
        range_oracle()
    );
    assert_columns_match_uncached(&before);
    drop(index);
    drop(before);

    let reopened = reopen_fs(&path);
    let after = reopened.snapshot();
    let after_bytes: Vec<Vec<u8>> = after
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    assert_eq!(before_bytes, after_bytes, "segment bytes must not change");
    assert_eq!(
        sorted_keys(&search(&after, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
    assert_eq!(
        search(&after, &n_sorted_request())
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        N_ASCENDING_KEYS
    );
    assert_columns_match_uncached(&after);
    let _ = std::fs::remove_dir_all(&path);
}

// GA-I03 — a pinned old snapshot keeps its original column values after a real
// upsert/delete/commit; the new snapshot sees the new state only.
#[test]
fn ga_i03_old_pit_is_isolated_from_new_generation() {
    let (directory, index) = build_memory_with_dir();
    let old = index.pin().expect("pin old");
    let old_snapshot = old.snapshot();
    assert_eq!(
        sorted_keys(&search(old_snapshot, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
    let b1 = DocumentKey::new("b1").expect("b1");
    let c0 = DocumentKey::new("c0").expect("c0");
    assert!(old_snapshot.contains_key(&b1).expect("old b1"));
    assert!(!old_snapshot.contains_key(&c0).expect("old c0"));

    {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(b1.clone()))
            .expect("delete b1");
        writer.insert(c0_document()).expect("insert c0");
        writer.commit().expect("commit");
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry())
        .expect("reopen after mutation");
    let new_snapshot = reopened.snapshot();
    assert_eq!(
        sorted_keys(&search(&new_snapshot, &unified_request(alpha_query(), 16))),
        NEW_ALPHA_KEYS.to_vec()
    );
    assert!(new_snapshot.contains_key(&c0).expect("new c0"));

    // The old snapshot still observes the original generation and values.
    assert_eq!(
        sorted_keys(&search(old_snapshot, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
    assert!(old_snapshot.contains_key(&b1).expect("old b1 again"));
    assert_columns_match_uncached(old_snapshot);
    assert_columns_match_uncached(&new_snapshot);
}

// GA-I04 — concurrent readers over one multi-segment snapshot keep independent
// query-local state and exact results.
#[test]
fn ga_i04_concurrent_snapshot_readers_are_exact() {
    let index = build_memory();
    let snapshot = Arc::new(index.snapshot());
    let alpha = oracle_sorted(Predicate::Alpha);
    let range = range_oracle();
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let snapshot = Arc::clone(&snapshot);
            let alpha = alpha.clone();
            let range = range.clone();
            scope.spawn(move || {
                for _ in 0..5 {
                    assert_eq!(
                        sorted_keys(&search(&snapshot, &unified_request(alpha_query(), 16))),
                        alpha
                    );
                    assert_eq!(
                        sorted_keys(&search(&snapshot, &unified_request(n_range_query(), 16))),
                        range
                    );
                    for index in 0..snapshot.segment_count() {
                        let guard = snapshot.open_segment_reader(index).expect("guarded reader");
                        let columns = guard
                            .reader()
                            .open_columns()
                            .expect("columns")
                            .expect("present");
                        assert!(!columns.fields().is_empty());
                    }
                }
            });
        }
    });
}

// GA-I05 — a small metadata cap repeatedly takes the validating fallback while
// every reader and query stays correct, and guard drop releases admission.
#[test]
fn ga_i05_small_metadata_cap_repeats_fallback_correctly() {
    let directory: Arc<dyn Directory> = Arc::new(quervant_core::storage::MemoryDirectory::new());
    // Reader admission charges the segment bytes; the candidate metadata
    // allowance is much larger, so this cap exercises the optional fallback.
    let limits = IndexLimits::default().with_max_snapshot_bytes(64 * 1024);
    let index = Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits)
        .expect("create index");
    commit_segment(&index, segment0_documents());
    commit_segment(&index, segment1_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let snapshot = reopened.snapshot();
    assert!(snapshot.resident_bytes() < 64 * 1024);
    for _ in 0..4 {
        let guard = snapshot.open_segment_reader(0).expect("fallback reader");
        assert_eq!(
            guard.reader().doc_count(),
            segment0_documents().len() as u64
        );
        let columns = guard
            .reader()
            .open_columns()
            .expect("columns")
            .expect("present");
        assert!(!columns.fields().is_empty());
        drop(guard);
    }
    assert_eq!(
        sorted_keys(&search(&snapshot, &unified_request(alpha_query(), 16))),
        oracle_sorted(Predicate::Alpha)
    );
}

// GA-I06 — corrupt committed column geometry fails closed with a typed error and
// never yields a partial reader.
#[test]
fn ga_i06_corrupt_column_geometry_fails_closed() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let original = snapshot.segments()[0].bytes().to_vec();
    SegmentReader::open(original.clone(), *snapshot.segment_limits()).expect("valid segment");

    let view = quervant_core::segment::parse_container(&original, snapshot.segment_limits())
        .expect("container");
    let body = view
        .body(quervant_core::segment::SectionKind::Columns)
        .expect("columns body")
        .to_vec();
    // Corrupt the first column's type tag (6-byte prefix + field id).
    let mut corrupt_body = body.clone();
    corrupt_body[10] ^= 0xFF;
    let mut builder = quervant_core::segment::ContainerBuilder::new(view.kind(), view.doc_count());
    for (feature, version) in view.required_features() {
        if (*feature, *version) != (1, 1) {
            builder.require_feature(*feature, *version);
        }
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        let body = if section.kind == quervant_core::segment::SectionKind::Columns {
            corrupt_body.clone()
        } else {
            let start = section.offset as usize;
            original[start..start + section.length as usize].to_vec()
        };
        builder.section(section.kind, section.flags, section.aux, body);
    }
    let corrupt = builder
        .build()
        .expect("rebuild container with valid digests");
    let error = match SegmentReader::open(corrupt, *snapshot.segment_limits()) {
        Ok(_) => panic!("corrupt columns must fail"),
        Err(error) => error,
    };
    assert!(
        matches!(
            error,
            quervant_core::segment::SegmentError::FieldTypeMismatch { .. }
        ),
        "unexpected error: {error:?}"
    );
    // The committed snapshot remains usable and its column body is unchanged.
    let guard = snapshot.open_segment_reader(0).expect("snapshot reader");
    let columns = guard
        .reader()
        .open_columns()
        .expect("columns")
        .expect("present");
    let standalone = ColumnReader::open(guard.reader().schema(), &body, snapshot.segment_limits())
        .expect("standalone");
    assert_eq!(columns.fields(), standalone.fields());
}

// GA-I07 / GA-I08 require a real RustFS service and are intentionally not
// emulated here. They are reported BLOCKED in the PR 15G-A artifact.
