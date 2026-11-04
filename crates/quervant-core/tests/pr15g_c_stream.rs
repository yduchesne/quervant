//! PR 15G-C — real local fused single-term streaming acceptance.

mod pr14_common;
mod pr15a_common;

use std::sync::Arc;

use pr14_common::{FieldValue, Query, Sort, SortDirection, SortField, TopK, registry, schema};
use pr15a_common::temp_dir;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn term(value: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(value.into()),
    }
}

fn sql_term(value: &str) -> Query {
    Query::And(vec![term(value)])
}

fn sorted_request(query: Query, top_k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request
}

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("search")
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn document(key: &str, title: &str, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .expect("title");
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .expect("n");
    document
}

fn fill(index: &Index, count: usize) {
    let mut writer = index.writer().expect("writer");
    for n in 0..count {
        let title = if n == 0 { "rare" } else { "common" };
        writer
            .insert(document(&format!("k{n:05}"), title, n as i64))
            .expect("insert");
    }
    writer.commit().expect("commit");
}

fn memory_index(count: usize) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create");
    fill(&index, count);
    Index::open_existing(directory, schema(), registry()).expect("reopen")
}

fn assert_stream_matches_legacy(snapshot: &ReaderSnapshot, top_k: usize) {
    let streamed = search(snapshot, &sorted_request(term("common"), top_k));
    let legacy = search(snapshot, &sorted_request(sql_term("common"), top_k));
    assert_eq!(streamed.total_hits, legacy.total_hits);
    assert_eq!(keys(&streamed), keys(&legacy));
    for (a, b) in streamed.hits.iter().zip(legacy.hits.iter()) {
        assert_eq!(a.fields, b.fields);
        match (a.score, b.score) {
            (Some(a), Some(b)) => assert_eq!(a.to_bits(), b.to_bits()),
            (None, None) => {}
            other => panic!("score shape mismatch: {other:?}"),
        }
    }
}

// GC-I01 — memory index, high-hit stream, exact totals/order/scores vs legacy.
#[test]
fn gc_i01_memory_high_hit_stream_matches_legacy() {
    let index = memory_index(1024);
    let snapshot = index.snapshot();
    for top_k in [1usize, 10, 100] {
        let streamed = search(&snapshot, &sorted_request(term("common"), top_k));
        assert_eq!(streamed.total_hits, 1023);
        assert_eq!(streamed.hits.len(), top_k);
        assert_stream_matches_legacy(&snapshot, top_k);
    }
}

// GC-I02 — real FsDirectory commit, drop, reopen; exact stream and bytes.
#[test]
fn gc_i02_filesystem_reopen_stream() {
    let path = temp_dir("pr15g-c-i02");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).expect("fs"));
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create");
    fill(&index, 256);
    let committed =
        Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    let before = committed.snapshot();
    let before_bytes: Vec<Vec<u8>> = before
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    assert_stream_matches_legacy(&before, 10);
    drop(index);
    drop(committed);
    drop(before);
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let after = reopened.snapshot();
    let after_bytes: Vec<Vec<u8>> = after
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    assert_eq!(before_bytes, after_bytes);
    assert_stream_matches_legacy(&after, 10);
    let _ = std::fs::remove_dir_all(&path);
}

// GC-I03/GC-I04 — ineligible sort shapes and cursor continuation remain exact.
#[test]
fn gc_i03_i04_fallback_and_cursor_pages() {
    let index = memory_index(64);
    let snapshot = index.snapshot();
    let relevance = search(
        &snapshot,
        &UnifiedRequest::new(term("common"), TopK::new(10).unwrap()),
    );
    assert_eq!(relevance.total_hits, 63);
    assert_eq!(relevance.hits.len(), 10);

    let mut descending = sorted_request(term("common"), 10);
    descending.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    let desc = search(&snapshot, &descending);
    assert_eq!(keys(&desc)[0], "k00063");

    let mut after = None;
    let mut seen = Vec::new();
    let mut pages = 0;
    loop {
        let mut request = sorted_request(term("common"), 10);
        request.after = after;
        let response = search(&snapshot, &request);
        seen.extend(keys(&response));
        pages += 1;
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
        assert!(pages < 100);
    }
    assert_eq!(seen.len(), 63);
    assert_eq!(pages, 7);
    let unique: std::collections::BTreeSet<_> = seen.iter().collect();
    assert_eq!(unique.len(), seen.len());
}

// GC-I07 — old PIT remains isolated from a new generation.
#[test]
fn gc_i07_old_pit_isolated_from_new_generation() {
    let index = memory_index(128);
    let old = index.pin().expect("pin");
    let old_snapshot = old.snapshot();
    let old_keys = keys(&search(
        old_snapshot.as_ref(),
        &sorted_request(term("common"), 100),
    ));
    let old_hits = search(old_snapshot.as_ref(), &sorted_request(term("common"), 100)).total_hits;
    {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new("k00001").expect("key"),
            ))
            .expect("delete");
        writer
            .insert(document("z00001", "common", 9999))
            .expect("insert");
        writer.commit().expect("commit");
    }
    // The pinned old view must not change after the new generation commits.
    let old_after = search(old_snapshot.as_ref(), &sorted_request(term("common"), 100));
    assert_eq!(old_after.total_hits, old_hits);
    assert_eq!(keys(&old_after), old_keys);
}

// GC-I09 — concurrent readers over one snapshot remain exact.
#[test]
fn gc_i09_concurrent_readers() {
    let index = memory_index(128);
    let snapshot = Arc::new(index.snapshot());
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let snapshot = Arc::clone(&snapshot);
            scope.spawn(move || {
                for _ in 0..4 {
                    let response = search(&snapshot, &sorted_request(term("common"), 10));
                    assert_eq!(response.total_hits, 127);
                    assert_eq!(response.hits.len(), 10);
                }
            });
        }
    });
}

// GC-I10 — deterministic index bytes for the same corpus.
#[test]
fn gc_i10_deterministic_index_bytes() {
    let first = memory_index(128);
    let second = memory_index(128);
    let a = first.snapshot();
    let b = second.snapshot();
    let a_bytes: Vec<Vec<u8>> = a.segments().iter().map(|s| s.bytes().to_vec()).collect();
    let b_bytes: Vec<Vec<u8>> = b.segments().iter().map(|s| s.bytes().to_vec()).collect();
    assert_eq!(a_bytes, b_bytes);
}

// GC-I08 — reduced metadata cap still returns exact stream results.
#[test]
fn gc_i08_reduced_metadata_cap_fallback() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let limits = IndexLimits::default().with_max_snapshot_bytes(64 * 1024);
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .expect("create");
    fill(&index, 64);
    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits).expect("reopen");
    let snapshot = reopened.snapshot();
    assert!(snapshot.resident_bytes() < 64 * 1024);
    let response = search(&snapshot, &sorted_request(term("common"), 10));
    assert_eq!(response.total_hits, 63);
    assert_eq!(response.hits.len(), 10);
}
