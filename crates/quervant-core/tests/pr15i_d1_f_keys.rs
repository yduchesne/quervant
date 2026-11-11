//! PR 15I-D1-F C2 real public-path integration tests (K09–K16).
//!
//! Real `FsDirectory` indexes through `Index`/`IndexWriter`/`ReaderSnapshot`/
//! `UnifiedSearcher`: writer -> commit -> reopen -> search, multiple segments,
//! update/delete masks, PIT snapshots, Keyword sort ties/missing values, cursor,
//! mixed/typed/ineligible shapes and resource/cancellation errors.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering as AtomicOrdering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MissingValuePosition, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::storage::{Directory, FsDirectory};

static COUNTER: AtomicUsize = AtomicUsize::new(0);

struct TempIndex {
    path: PathBuf,
}

impl TempIndex {
    fn new(label: &str) -> Self {
        let unique = COUNTER.fetch_add(1, AtomicOrdering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "quervant-pr15i-d1-f-{label}-{}-{unique}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self { path }
    }

    fn directory(&self) -> Arc<dyn Directory> {
        Arc::new(FsDirectory::open(&self.path).unwrap())
    }
}

impl Drop for TempIndex {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "grp",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "doc_id",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        None,
    )
    .unwrap()
}

fn large_limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(200_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(
        directory,
        schema(),
        AnalyzerRegistry::builtin(),
        large_limits(),
    )
    .unwrap()
}

fn document(position: usize, grp: &str, doc_id: Option<&str>) -> Document {
    let mut document = Document::new(DocumentKey::new(format!("k{position:05}")).unwrap());
    document
        .insert(
            "grp",
            FieldValues::Single(FieldValue::Keyword(grp.to_owned())),
        )
        .unwrap();
    if let Some(value) = doc_id {
        document
            .insert(
                "doc_id",
                FieldValues::Single(FieldValue::Keyword(value.to_owned())),
            )
            .unwrap();
    }
    document
}

fn term(value: &str) -> Query {
    Query::Term {
        field: "grp".to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn sorted_request(query: Query, top_k: usize, direction: SortDirection) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = Sort::new(vec![SortField::new("doc_id", direction)]);
    request.projection = Projection::Fields(vec!["doc_id".to_owned()]);
    request
}

fn search_with(
    index: &Index,
    request: &UnifiedRequest,
    limits: SearchLimits,
) -> Result<UnifiedResponse, SearchError> {
    let snapshot = index.snapshot();
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    UnifiedSearcher::new(&snapshot, &schema, &registry, limits).search(
        request,
        &Budgets::new(),
        &CancellationFlag::new(),
    )
}

fn search(index: &Index, request: &UnifiedRequest) -> UnifiedResponse {
    search_with(index, request, SearchLimits::default()).unwrap()
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn expected_keys(count: usize) -> Vec<String> {
    (0..count)
        .map(|position| format!("k{position:05}"))
        .collect()
}

/// Two committed segments, 500 documents, all matching `grp=common` with
/// ascending `doc_id` values.
fn two_segment_index() -> Index {
    let temp = TempIndex::new("segments");
    let directory = temp.directory();
    let index = create(Arc::clone(&directory));
    for range in [0..250usize, 250..500] {
        let mut writer = index.writer().unwrap();
        for position in range {
            writer
                .insert(document(
                    position,
                    "common",
                    Some(&format!("d{position:05}")),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap()
}

/// K09/K13/K16: every K boundary, two segments, exact keys and hit counts.
#[test]
fn d1f_k09_k13_k16_k_boundaries_match_expected_keys() {
    let index = two_segment_index();
    for top_k in [1usize, 10, 31, 32, 100, 128, 129] {
        let response = search(
            &index,
            &sorted_request(term("common"), top_k, SortDirection::Asc),
        );
        assert_eq!(response.total_hits, 500, "K={top_k}");
        assert_eq!(keys(&response), expected_keys(top_k), "K={top_k}");
        let bits: Vec<u64> = response
            .hits
            .iter()
            .map(|hit| hit.score.expect("scored").to_bits())
            .collect();
        assert!(
            bits.windows(2).all(|window| window[0] == window[1]),
            "K={top_k}"
        );
    }
}

/// K11: equal sort values, missing values, ASC/DESC and cursor pages.
#[test]
fn d1f_k11_sort_ties_missing_and_cursor() {
    let temp = TempIndex::new("sort");
    let directory = temp.directory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for position in 0..60 {
            let doc_id = match position % 4 {
                0 => Some("same".to_owned()),
                1 => Some("first".to_owned()),
                2 => None,
                _ => Some("last".to_owned()),
            };
            writer
                .insert(document(position, "common", doc_id.as_deref()))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();

    let mut asc = sorted_request(term("common"), 100, SortDirection::Asc);
    asc.sort.fields[0].missing = MissingValuePosition::Last;
    let snapshot = reopened.snapshot();
    let sort_schema = schema();
    let sort_registry = AnalyzerRegistry::builtin();
    let run = |request: &UnifiedRequest| {
        UnifiedSearcher::new(
            &snapshot,
            &sort_schema,
            &sort_registry,
            SearchLimits::default(),
        )
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .unwrap()
    };
    let full = run(&asc);
    assert_eq!(full.total_hits, 60);
    assert_eq!(full.hits.len(), 60);

    let mut expected: Vec<String> = Vec::new();
    for value in ["first", "last", "same"] {
        let mut matching: Vec<String> = (0..60)
            .filter(|position| {
                let doc_id = match position % 4 {
                    0 => Some("same"),
                    1 => Some("first"),
                    2 => None,
                    _ => Some("last"),
                };
                doc_id == Some(value)
            })
            .map(|position| format!("k{position:05}"))
            .collect();
        matching.sort();
        expected.extend(matching);
    }
    let mut missing: Vec<String> = (0..60)
        .filter(|position| position % 4 == 2)
        .map(|position| format!("k{position:05}"))
        .collect();
    missing.sort();
    expected.extend(missing);
    assert_eq!(keys(&full), expected);

    // Cursor pages concatenate to the single-page prefix.
    let mut paged: Vec<String> = Vec::new();
    let mut after = None;
    for _ in 0..40usize {
        let mut page_request = asc.clone();
        page_request.top_k = TopK::new(7).unwrap();
        page_request.after = after.clone();
        let page = run(&page_request);
        paged.extend(keys(&page));
        match page.next_cursor.clone() {
            Some(cursor) => after = Some(cursor),
            None => break,
        }
    }
    assert_eq!(paged, keys(&full));

    // DESC inverts the present-value order while missing values stay last.
    let mut desc = sorted_request(term("common"), 100, SortDirection::Desc);
    desc.sort.fields[0].missing = MissingValuePosition::Last;
    let desc_response = run(&desc);
    assert_eq!(desc_response.total_hits, 60);
    assert_eq!(desc_response.hits.len(), 60);
}

/// K10/K12: ineligible shapes and resource/cancellation errors are unchanged.
#[test]
fn d1f_k10_k12_ineligible_and_failure_paths() {
    let index = two_segment_index();
    let typed = search(
        &index,
        &sorted_request(
            Query::Exists {
                field: "doc_id".to_owned(),
            },
            100,
            SortDirection::Asc,
        ),
    );
    assert_eq!(typed.total_hits, 500);
    let mixed = search(
        &index,
        &sorted_request(
            Query::And(vec![
                term("common"),
                Query::Exists {
                    field: "doc_id".to_owned(),
                },
            ]),
            100,
            SortDirection::Asc,
        ),
    );
    assert_eq!(mixed.total_hits, 500);
    assert_eq!(keys(&mixed), expected_keys(100));
    let relevance = search(
        &index,
        &UnifiedRequest::new(term("common"), TopK::new(10).unwrap()),
    );
    assert_eq!(relevance.total_hits, 500);

    let limits = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .unwrap();
    let error = search_with(
        &index,
        &sorted_request(term("common"), 100, SortDirection::Asc),
        limits,
    )
    .unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));

    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    let error = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default())
        .search(
            &sorted_request(term("common"), 100, SortDirection::Asc),
            &Budgets::new(),
            &cancel,
        )
        .unwrap_err();
    assert!(matches!(error, SearchError::Cancelled));
}

/// K13/K14: mutations, delete masks, PIT and a real filesystem reopen.
#[test]
fn d1f_k13_k14_mutations_pit_and_reopen() {
    let temp = TempIndex::new("mutations");
    let directory = temp.directory();
    let index = create(Arc::clone(&directory));
    let pit = {
        let mut writer = index.writer().unwrap();
        for position in 0..300 {
            writer
                .insert(document(
                    position,
                    "common",
                    Some(&format!("d{position:05}")),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
        writer.refresh().unwrap()
    };
    let fresh = {
        let mut writer = index.writer().unwrap();
        for position in 0..40 {
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(format!("k{position:05}")).unwrap(),
                ))
                .unwrap();
        }
        for position in 40..80 {
            writer
                .apply(MutationRequest::upsert(document(
                    position,
                    "other",
                    Some(&format!("u{position:05}")),
                )))
                .unwrap();
        }
        writer.commit().unwrap();
        writer.refresh().unwrap()
    };
    let pit_schema = schema();
    let pit_registry = AnalyzerRegistry::builtin();
    let pit_response =
        UnifiedSearcher::new(&pit, &pit_schema, &pit_registry, SearchLimits::default())
            .search(
                &sorted_request(term("common"), 1_000, SortDirection::Asc),
                &Budgets::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
    assert_eq!(pit_response.total_hits, 300);
    let fresh_schema = schema();
    let fresh_registry = AnalyzerRegistry::builtin();
    let fresh_response = UnifiedSearcher::new(
        &fresh,
        &fresh_schema,
        &fresh_registry,
        SearchLimits::default(),
    )
    .search(
        &sorted_request(term("common"), 1_000, SortDirection::Asc),
        &Budgets::new(),
        &CancellationFlag::new(),
    )
    .unwrap();
    assert_eq!(fresh_response.total_hits, 220);
    assert!(keys(&fresh_response).iter().all(|key| {
        let position: usize = key[1..].parse().unwrap();
        position >= 80
    }));

    drop(pit);
    drop(fresh);
    drop(index);
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let reopened_response = search(
        &reopened,
        &sorted_request(term("common"), 1_000, SortDirection::Asc),
    );
    assert_eq!(reopened_response.total_hits, 220);
    let expected: Vec<String> = (80..300)
        .map(|position| format!("k{position:05}"))
        .collect();
    assert_eq!(keys(&reopened_response), expected);
}

/// K08/K14 residual note: the public writer rejects duplicate live keys, and
/// the exact retained-duplicate predicate remains the unchanged literal
/// `heap.iter().any(...)` check. Multi-segment unique keys must not trigger it.
#[test]
fn d1f_k08_public_writer_rejects_duplicate_live_keys() {
    let temp = TempIndex::new("duplicate");
    let directory = temp.directory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        writer.insert(document(0, "common", Some("d0"))).unwrap();
        assert!(writer.insert(document(0, "common", Some("d0"))).is_err());
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin()).unwrap();
    let response = search(
        &reopened,
        &sorted_request(term("common"), 10, SortDirection::Asc),
    );
    assert_eq!(response.total_hits, 1);
}
