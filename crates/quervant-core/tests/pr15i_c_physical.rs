//! PR 15I-C — full public-path tests for the postings-driven exact-count/top-K
//! physical operator.
//!
//! The fast operator is private, so these tests use the public `Index` /
//! `UnifiedSearcher` path and compare the `C-EXACT-ONE` shape against a
//! semantically identical but deliberately ineligible shape (`And([term])`), which
//! always executes the untouched generic executor on the same committed bytes.

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MissingValuePosition, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

mod common;

use common::TempDir;

fn schema() -> Schema {
    let keyword = |name: &str| {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, true, true),
        )
    };
    Schema::new(
        vec![
            keyword("grp"),
            keyword("doc_id"),
            keyword("label"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .unwrap()
}

fn limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(200_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
}

fn document(position: usize, keyword: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(format!("k{position:06}")).unwrap());
    document
        .insert(
            "grp",
            FieldValues::Single(FieldValue::Keyword("common".to_owned())),
        )
        .unwrap();
    document
        .insert(
            "doc_id",
            FieldValues::Single(FieldValue::Keyword(keyword.to_owned())),
        )
        .unwrap();
    document
        .insert(
            "label",
            FieldValues::Single(FieldValue::Keyword(keyword.to_owned())),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(position as i64)))
        .unwrap();
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha".to_owned())),
        )
        .unwrap();
    document
}

fn grp() -> Query {
    Query::Term {
        field: "grp".to_owned(),
        value: FieldValue::Keyword("common".to_owned()),
    }
}

fn generic(term: Query) -> Query {
    Query::And(vec![term])
}

fn sorted(field: &str) -> Sort {
    Sort::new(vec![SortField::new(field, SortDirection::Asc)])
}

fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = sort;
    request
}

fn search(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
) -> UnifiedResponse {
    UnifiedSearcher::new(
        snapshot,
        &schema(),
        &AnalyzerRegistry::builtin(),
        SearchLimits::default(),
    )
    .search(request, &Budgets::new(), &NeverCancel)
    .unwrap()
}

fn search_with(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
    search_limits: SearchLimits,
) -> quervant_core::search::SearchResult<UnifiedResponse> {
    UnifiedSearcher::new(
        snapshot,
        &schema(),
        &AnalyzerRegistry::builtin(),
        search_limits,
    )
    .search(request, &Budgets::new(), &NeverCancel)
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn bits(response: &UnifiedResponse) -> Vec<Option<u64>> {
    response
        .hits
        .iter()
        .map(|hit| hit.score.map(f64::to_bits))
        .collect()
}

/// Assert the fast shape and the forced-generic shape agree exactly.
fn assert_parity(snapshot: &quervant_core::index::ReaderSnapshot, top_k: usize, sort: &Sort) {
    let fast = search(snapshot, &request(grp(), top_k, sort.clone()));
    let slow = search(snapshot, &request(generic(grp()), top_k, sort.clone()));
    assert_eq!(fast.total_hits, slow.total_hits, "total_hits drift");
    assert_eq!(keys(&fast), keys(&slow), "key order drift");
    assert_eq!(bits(&fast), bits(&slow), "score bit drift");
    assert_eq!(
        fast.hits
            .iter()
            .map(|hit| hit.fields.clone())
            .collect::<Vec<_>>(),
        slow.hits
            .iter()
            .map(|hit| hit.fields.clone())
            .collect::<Vec<_>>(),
        "projection drift",
    );
    assert_eq!(fast.next_cursor.is_some(), slow.next_cursor.is_some());
    assert_eq!(fast.generation, slow.generation);
}

fn build_fs(root: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(root).unwrap())
}

fn insert_corpus(index: &Index, start: usize, count: usize, keyword: impl Fn(usize) -> String) {
    let mut writer = index.writer().unwrap();
    for position in start..start + count {
        writer
            .insert(document(position, &keyword(position)))
            .unwrap();
    }
    writer.commit().unwrap();
}

/// C-I01/C-I02/C-I03: local `FsDirectory` commit and exact counts/scores at
/// 10K and 100K for K=10 and K=100.
#[test]
fn c_i01_i02_i03_local_fs_counts_and_scores() {
    for count in [10_000usize, 100_000] {
        let temp = TempDir::new("c15i-i01");
        let directory = build_fs(temp.path());
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema(),
            AnalyzerRegistry::builtin(),
            limits(),
        )
        .unwrap();
        insert_corpus(&index, 0, count, |position| format!("d{position:08}"));
        let reopened =
            Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
        let snapshot = reopened.snapshot();
        assert_eq!(snapshot.segment_count(), 1, "one committed segment");
        for top_k in [10usize, 100] {
            let fast = search(&snapshot, &request(grp(), top_k, sorted("doc_id")));
            assert_eq!(fast.total_hits, count as u64);
            assert_eq!(fast.hits.len(), top_k);
            assert_parity(&snapshot, top_k, &sorted("doc_id"));
        }
    }
}

/// C-I04: a sort column that differs from the logical key is authoritative.
#[test]
fn c_i04_column_differs_from_logical_key() {
    let temp = TempDir::new("c15i-i04");
    let directory = build_fs(temp.path());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 256, |position| format!("v{:05}", 255 - position));
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    let fast = search(&snapshot, &request(grp(), 256, sorted("doc_id")));
    let mut expected: Vec<String> = (0..256).map(|position| format!("k{position:06}")).collect();
    expected.reverse();
    assert_eq!(keys(&fast), expected);
    assert!(fast.hits[0].fields.iter().any(|(name, values)| {
        name == "title" && *values == FieldValues::Single(FieldValue::Text("alpha".to_owned()))
    }));
    assert_parity(&snapshot, 256, &sorted("doc_id"));
    // A second sortable Keyword field behaves identically.
    assert_parity(&snapshot, 50, &sorted("label"));
    // Missing values keep their configured ranking.
    for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
        let mut field = SortField::new("doc_id", SortDirection::Asc);
        field.missing = missing;
        assert_parity(&snapshot, 50, &Sort::new(vec![field]));
    }
}

/// C-I05: a pinned PIT keeps the old snapshot while a new generation lands.
#[test]
fn c_i05_pit_snapshot_is_immutable() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 100, |position| format!("d{position:05}"));
    let mut writer = index.writer().unwrap();
    let pinned = writer.pin().unwrap();
    let before = pinned.snapshot().clone();
    let before_total = search(&before, &request(grp(), 10, sorted("doc_id"))).total_hits;

    for position in 100..150usize {
        writer
            .insert(document(position, &format!("d{position:05}")))
            .unwrap();
    }
    writer.commit().unwrap();
    let after_index = Index::open_existing(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let after = after_index.snapshot();

    assert_eq!(before_total, 100);
    assert_eq!(
        search(&before, &request(grp(), 10, sorted("doc_id"))).total_hits,
        100
    );
    assert_eq!(
        search(&after, &request(grp(), 10, sorted("doc_id"))).total_hits,
        150
    );
    assert_eq!(
        search(&before, &request(grp(), 10, sorted("doc_id"))).total_hits,
        before_total
    );
    pinned.close();
}

/// C-I06/C-I07: multi-segment indexes stay on the generic path and agree.
#[test]
fn c_i06_i07_two_segments_fall_back_consistently() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 40, |position| format!("d{position:05}"));
    insert_corpus(&index, 40, 40, |position| format!("d{position:05}"));
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.segment_count(), 2);
    let fast = search(&snapshot, &request(grp(), 10, sorted("doc_id")));
    assert_eq!(fast.total_hits, 80);
    assert_parity(&snapshot, 10, &sorted("doc_id"));
}

/// C-I08: compaction collapses to one segment and the operator still agrees.
#[test]
fn c_i08_compaction_to_single_segment() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 30, |position| format!("d{position:05}"));
    insert_corpus(&index, 30, 30, |position| format!("d{position:05}"));
    {
        let mut writer = index.writer().unwrap();
        let keys: Vec<DocumentKey> = (0..10usize)
            .map(|position| DocumentKey::new(format!("k{position:06}")).unwrap())
            .collect();
        writer.delete_keys_for_retention(&keys, "c15i i08").unwrap();
        writer.commit().unwrap();
        writer.compact().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    let fast = search(&snapshot, &request(grp(), 10, sorted("doc_id")));
    assert_eq!(fast.total_hits, 50);
    assert!(fast.hits.iter().all(|hit| hit.key.as_str() >= "k000010"));
    assert_parity(&snapshot, 10, &sorted("doc_id"));
}

/// C-I09: reopening the real local index from disk changes nothing.
#[test]
fn c_i09_restart_reopen() {
    let temp = TempDir::new("c15i-i09");
    let root = temp.path().join("index");
    std::fs::create_dir_all(&root).unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    {
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema(),
            AnalyzerRegistry::builtin(),
            limits(),
        )
        .unwrap();
        insert_corpus(&index, 0, 500, |position| format!("d{position:05}"));
    }
    let reopened = Index::open_existing(
        Arc::new(FsDirectory::open(&root).unwrap()),
        schema(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let snapshot = reopened.snapshot();
    let first = search(&snapshot, &request(grp(), 20, sorted("doc_id")));
    assert_eq!(first.total_hits, 500);
    assert_parity(&snapshot, 20, &sorted("doc_id"));
}

/// C-I14: contract validation still fails before any segment access.
#[test]
fn c_i14_contract_validation_first() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 10, |position| format!("d{position:05}"));
    let snapshot = index.snapshot();
    let unknown_sort = request(
        grp(),
        10,
        Sort::new(vec![SortField::new("nope", SortDirection::Asc)]),
    );
    assert!(search_with(&snapshot, &unknown_sort, SearchLimits::default()).is_err());
    let mut unstored = request(grp(), 10, sorted("doc_id"));
    unstored.projection = Projection::Fields(vec!["nope".to_owned()]);
    assert!(search_with(&snapshot, &unstored, SearchLimits::default()).is_err());
}

/// C-I17/C-I22: concurrent and repeated readers observe identical results.
#[test]
fn c_i17_i22_concurrent_and_repeated_readers() {
    let temp = TempDir::new("c15i-i17");
    let directory = build_fs(temp.path());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 2_000, |position| format!("d{position:05}"));
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    let expected = search(&snapshot, &request(grp(), 50, sorted("doc_id")));
    assert_eq!(expected.total_hits, 2_000);

    for _ in 0..3 {
        let repeat = search(&snapshot, &request(grp(), 50, sorted("doc_id")));
        assert_eq!(keys(&repeat), keys(&expected));
        assert_eq!(bits(&repeat), bits(&expected));
    }

    let handles: Vec<_> = (0..4)
        .map(|_| {
            let snapshot = Arc::clone(&snapshot);
            std::thread::spawn(move || {
                let response = search(&snapshot, &request(grp(), 50, sorted("doc_id")));
                (keys(&response), bits(&response), response.total_hits)
            })
        })
        .collect();
    let baseline = (keys(&expected), bits(&expected), expected.total_hits);
    for handle in handles {
        assert_eq!(handle.join().unwrap(), baseline);
    }
}

/// C-I21: custom work/scanned ceilings keep their exact boundary on the fast path.
#[test]
fn c_i21_custom_limits_exact_and_one_below() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 400, |position| format!("d{position:05}"));
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    let fast_request = request(grp(), 5, sorted("doc_id"));
    let slow_request = request(generic(grp()), 5, sorted("doc_id"));

    let work = |value: u64| {
        SearchLimits::default()
            .with_max_total_work_units(value)
            .unwrap()
    };
    let min = |request: &UnifiedRequest| {
        let mut low = 1u64;
        let mut high = 1_000_000u64;
        while low < high {
            let mid = low + (high - low) / 2;
            if search_with(&snapshot, request, work(mid)).is_ok() {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        low
    };
    let fast_min = min(&fast_request);
    let slow_min = min(&slow_request);
    assert!(fast_min > 1, "work boundary must be non-trivial");
    assert_eq!(fast_min, slow_min, "work boundary drift");
    assert!(search_with(&snapshot, &fast_request, work(fast_min)).is_ok());
    assert!(search_with(&snapshot, &fast_request, work(fast_min - 1)).is_err());
}

/// C-I23: the operator needs no remote service or object-store feature.
#[test]
fn c_i23_local_only_path() {
    let temp = TempDir::new("c15i-i23");
    let directory = build_fs(temp.path());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 64, |position| format!("d{position:05}"));
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let snapshot = reopened.snapshot();
    let response = search(&snapshot, &request(grp(), 10, sorted("doc_id")));
    assert_eq!(response.total_hits, 64);
    assert_parity(&snapshot, 10, &sorted("doc_id"));
}

/// C-I24: a non-lexical/unsupported sort still uses the generic path.
#[test]
fn c_i24_unsupported_sort_uses_generic_path() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 60, |position| format!("d{position:05}"));
    let snapshot = index.snapshot();
    let numeric = search(&snapshot, &request(grp(), 10, sorted("n")));
    let numeric_generic = search(&snapshot, &request(generic(grp()), 10, sorted("n")));
    assert_eq!(keys(&numeric), keys(&numeric_generic));
    assert_eq!(bits(&numeric), bits(&numeric_generic));
    // Relevance ordering (no sort) also stays generic and unchanged.
    let relevance = search(&snapshot, &request(grp(), 10, Sort::default()));
    let relevance_generic = search(&snapshot, &request(generic(grp()), 10, Sort::default()));
    assert_eq!(keys(&relevance), keys(&relevance_generic));
    assert_eq!(bits(&relevance), bits(&relevance_generic));
}

/// A cancelled request never returns a partial page.
#[test]
fn c_i_cancel_returns_no_partial_page() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        AnalyzerRegistry::builtin(),
        limits(),
    )
    .unwrap();
    insert_corpus(&index, 0, 100, |position| format!("d{position:05}"));
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let error = UnifiedSearcher::new(
        &snapshot,
        &schema(),
        &AnalyzerRegistry::builtin(),
        SearchLimits::default(),
    )
    .search(
        &request(grp(), 10, sorted("doc_id")),
        &Budgets::new(),
        &cancel,
    )
    .unwrap_err();
    assert!(matches!(
        error,
        quervant_core::search::SearchError::Cancelled
    ));
}
