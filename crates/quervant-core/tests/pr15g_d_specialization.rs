//! PR 15G-D — compiled exact-term miss and direct-membership specialization.

mod pr14_common;
mod pr15a_common;

use std::sync::Arc;

use pr14_common::{FieldValue, Query, Sort, SortDirection, SortField, TopK, registry, schema};
use pr15a_common::temp_dir;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn term(value: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(value.into()),
    }
}

fn legacy(query: Query) -> Query {
    Query::And(vec![query])
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

fn assert_d_parity(snapshot: &ReaderSnapshot, query: Query, top_k: usize) {
    let direct = search(snapshot, &sorted_request(query.clone(), top_k));
    let control = search(snapshot, &sorted_request(legacy(query), top_k));
    assert_eq!(direct.total_hits, control.total_hits);
    assert_eq!(keys(&direct), keys(&control));
    for (a, b) in direct.hits.iter().zip(control.hits.iter()) {
        assert_eq!(a.fields, b.fields);
        match (a.score, b.score) {
            (Some(a), Some(b)) => assert_eq!(a.to_bits(), b.to_bits()),
            (None, None) => {}
            other => panic!("score shape mismatch: {other:?}"),
        }
    }
}

// GD-I01 — memory, absent/rare/common, K1/K10/K100 parity.
#[test]
fn gd_i01_memory_absent_present_parity() {
    let index = memory_index(1024);
    let snapshot = index.snapshot();
    for top_k in [1usize, 10, 100] {
        assert_d_parity(&snapshot, term("absent"), top_k);
        assert_d_parity(&snapshot, term("rare"), top_k);
        assert_d_parity(&snapshot, term("common"), top_k);
    }
    let absent = search(&snapshot, &sorted_request(term("absent"), 10));
    assert_eq!(absent.total_hits, 0);
    let rare = search(&snapshot, &sorted_request(term("rare"), 10));
    assert_eq!(rare.total_hits, 1);
    assert_eq!(keys(&rare), ["k00000"]);
}

// GD-I02 — two segments: a term absent from one but present in the other.
#[test]
fn gd_i02_cross_segment_miss_and_hit() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create");
    {
        let mut writer = index.writer().expect("writer");
        for n in 0..16i64 {
            writer
                .insert(document(&format!("a{n:02}"), "alpha", n))
                .expect("a");
        }
        writer.commit().expect("commit a");
        for n in 0..16i64 {
            writer
                .insert(document(&format!("b{n:02}"), "beta", n))
                .expect("b");
        }
        writer.commit().expect("commit b");
    }
    let index = Index::open_existing(directory, schema(), registry()).expect("reopen");
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 2);
    assert_d_parity(&snapshot, term("alpha"), 100);
    assert_d_parity(&snapshot, term("beta"), 100);
    assert_d_parity(&snapshot, term("absent"), 100);
}

// GD-I03 — FsDirectory commit/reopen absent and present searches.
#[test]
fn gd_i03_filesystem_reopen_parity() {
    let path = temp_dir("pr15g-d-i03");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).expect("fs"));
    let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create");
    fill(&index, 128);
    let committed =
        Index::open_existing(Arc::clone(&directory), schema(), registry()).expect("reopen");
    let before = committed.snapshot();
    let before_bytes: Vec<Vec<u8>> = before
        .segments()
        .iter()
        .map(|s| s.bytes().to_vec())
        .collect();
    assert_d_parity(&before, term("absent"), 10);
    assert_d_parity(&before, term("common"), 10);
    drop(index);
    drop(committed);
    drop(before);
    let reopened = Index::open_existing(directory, schema(), registry()).expect("reopen2");
    let after = reopened.snapshot();
    let after_bytes: Vec<Vec<u8>> = after
        .segments()
        .iter()
        .map(|s| s.bytes().to_vec())
        .collect();
    assert_eq!(before_bytes, after_bytes);
    assert_d_parity(&after, term("absent"), 10);
    assert_d_parity(&after, term("common"), 10);
    let _ = std::fs::remove_dir_all(&path);
}

// GD-I04 — PIT old/new generation with absent and present searches.
#[test]
fn gd_i04_old_pit_and_new_generation() {
    let index = memory_index(128);
    let old = index.pin().expect("pin");
    let old_snapshot = old.snapshot();
    let old_absent = search(old_snapshot.as_ref(), &sorted_request(term("absent"), 10));
    let old_common = keys(&search(
        old_snapshot.as_ref(),
        &sorted_request(term("common"), 100),
    ));
    {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new("k00001").expect("key"),
            ))
            .expect("delete");
        writer.commit().expect("commit");
    }
    assert_eq!(
        search(old_snapshot.as_ref(), &sorted_request(term("absent"), 10)).total_hits,
        old_absent.total_hits
    );
    assert_eq!(
        keys(&search(
            old_snapshot.as_ref(),
            &sorted_request(term("common"), 100)
        )),
        old_common
    );
}

// GD-I05 — eight concurrent readers, absent/present parity.
#[test]
fn gd_i05_concurrent_readers() {
    let index = memory_index(128);
    let snapshot = Arc::new(index.snapshot());
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let snapshot = Arc::clone(&snapshot);
            scope.spawn(move || {
                for _ in 0..4 {
                    assert_eq!(
                        search(&snapshot, &sorted_request(term("absent"), 10)).total_hits,
                        0
                    );
                    assert_eq!(
                        search(&snapshot, &sorted_request(term("common"), 10)).total_hits,
                        127
                    );
                }
            });
        }
    });
}
