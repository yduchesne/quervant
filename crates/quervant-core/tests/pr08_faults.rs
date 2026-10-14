//! PR 8 fault, cancellation and recovery tests (T29–T32).

mod common;

use std::cell::Cell;
use std::sync::Arc;

use common::{Pr07Doc, pr08_commit_batches, pr08_registry, pr08_schema};
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits, SearchResponse};
use quervant_core::storage::{Directory, MemoryDirectory};

/// A cancellation source that trips after a fixed number of polls.
struct CancelAfter {
    remaining: Cell<u32>,
}

impl CancelAfter {
    fn new(remaining: u32) -> Self {
        Self {
            remaining: Cell::new(remaining),
        }
    }
}

impl Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let left = self.remaining.get();
        if left == 0 {
            true
        } else {
            self.remaining.set(left - 1);
            false
        }
    }
}

fn wide_snapshot(doc_count: usize) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let docs: Vec<quervant_core::contract::document::Document> = (0..doc_count)
        .map(|index| {
            // Leaked for the test process only; the corpus must outlive the index.
            let key: &'static str = Box::leak(format!("doc{index:04}").into_boxed_str());
            let term: &'static str = Box::leak(format!("term{index:04}").into_boxed_str());
            let common: &'static str = "common";
            Pr07Doc::new(key).host(term).tags(vec![common]).build()
        })
        .collect();
    pr08_commit_batches(directory.clone(), vec![docs]);
    Index::open_existing(directory, pr08_schema(), pr08_registry()).expect("reopen")
}

fn search(
    snapshot: &ReaderSnapshot,
    query: &Query,
    cancel: &dyn Cancellation,
) -> Result<SearchResponse, SearchError> {
    LexicalSearcher::new(
        snapshot,
        &pr08_schema(),
        &pr08_registry(),
        SearchLimits::default(),
    )
    .search(query, TopK::new(50).unwrap(), &Budgets::new(), cancel)
}

fn glob(field: &str, pattern: &str) -> Query {
    Query::Glob {
        field: field.to_owned(),
        pattern: pattern.to_owned(),
    }
}

fn term(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

// T29 — a pre-cancelled request returns `Cancelled` before opening any segment.
#[test]
fn p8_t29_precancel() {
    let index = wide_snapshot(16);
    let snapshot = index.snapshot();
    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    assert!(matches!(
        search(&snapshot, &term("tags", "common"), &cancelled),
        Err(SearchError::Cancelled)
    ));
    // The snapshot remains reusable.
    let flag = CancellationFlag::new();
    assert!(search(&snapshot, &term("tags", "common"), &flag).is_ok());
}

// T30 — cancellation is observed during bounded FST/automaton traversal.
#[test]
fn p8_t30_cancel_during_traversal() {
    let index = wide_snapshot(400);
    let snapshot = index.snapshot();
    let cancel = CancelAfter::new(3);
    let result = search(&snapshot, &glob("host", "*"), &cancel);
    assert!(
        matches!(result, Err(SearchError::Cancelled)),
        "expected cancellation during traversal, got {result:?}"
    );
    // No partial response is returned and the snapshot stays usable.
    let flag = CancellationFlag::new();
    assert!(search(&snapshot, &glob("host", "term000*"), &flag).is_ok());
}

// T31 — cancellation is observed while scanning postings.
#[test]
fn p8_t31_cancel_during_postings() {
    let index = wide_snapshot(400);
    let snapshot = index.snapshot();
    // `common` has 400 postings; polling every 256 work units trips mid-scan.
    let cancel = CancelAfter::new(2);
    let result = search(&snapshot, &term("tags", "common"), &cancel);
    assert!(
        matches!(result, Err(SearchError::Cancelled)),
        "expected cancellation during postings, got {result:?}"
    );
    let flag = CancellationFlag::new();
    let response = search(&snapshot, &term("tags", "common"), &flag).unwrap();
    assert_eq!(response.total_hits, 400);
}

// T32 — a resource failure leaves the snapshot reusable for a later query.
#[test]
fn p8_t32_failure_then_recovery() {
    let index = wide_snapshot(64);
    let snapshot = index.snapshot();
    let tight = SearchLimits::default().with_max_expanded_terms(4).unwrap();
    let result = LexicalSearcher::new(&snapshot, &pr08_schema(), &pr08_registry(), tight).search(
        &glob("host", "*"),
        TopK::new(10).unwrap(),
        &Budgets::new(),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
    // A subsequent query on the same snapshot succeeds.
    let response = search(
        &snapshot,
        &glob("host", "term000*"),
        &CancellationFlag::new(),
    )
    .unwrap();
    assert_eq!(response.total_hits, 10);
}

// T32 (corrupt segment slice) — a corrupted committed object fails closed and a
// later independent index/search is unaffected.
#[test]
fn p8_t32_corrupt_segment_fails_closed() {
    use common::TempDir;
    use quervant_core::index::IndexError;
    use quervant_core::storage::FsDirectory;

    let temp = TempDir::new("pr08-corrupt");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(temp.path()).unwrap());
    pr08_commit_batches(
        directory.clone(),
        vec![vec![Pr07Doc::new("a").host("rust").build()]],
    );
    // Corrupt the only segment object.
    let segments = temp.path().join("index/segments");
    let entry = std::fs::read_dir(&segments)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let mut bytes = std::fs::read(&entry).unwrap();
    let last = bytes.len() - 1;
    bytes[last] ^= 0xFF;
    std::fs::write(&entry, &bytes).unwrap();
    let reopened = Index::open_existing(
        Arc::new(FsDirectory::open(temp.path()).unwrap()),
        pr08_schema(),
        pr08_registry(),
    );
    assert!(matches!(
        reopened,
        Err(IndexError::CorruptCommittedState { .. }) | Err(IndexError::Storage(_))
    ));

    // An independent memory index is unaffected.
    let index = wide_snapshot(4);
    let snapshot = index.snapshot();
    assert!(
        search(
            &snapshot,
            &term("host", "term0000"),
            &CancellationFlag::new()
        )
        .is_ok()
    );
}
