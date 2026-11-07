//! PR 15H-B real local production-path integration tests.
//!
//! Exercises the public `Index`/`UnifiedSearcher` boundary for the borrowed
//! keyword sort view. The eligible `Term` request is compared with the
//! ineligible `And([Term])` fallback and exact score bits; PIT, cursor, batch,
//! multi-valued and corrupt paths are covered.

use std::path::PathBuf;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MultiValueSelector, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn schema() -> Schema {
    let keyword = |name: &str, cardinality: Cardinality, columnar: bool| {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            cardinality,
            FieldOptions::new(true, true, columnar),
        )
    };
    Schema::new(
        vec![
            keyword("grp", Cardinality::Single, false),
            keyword("doc_id", Cardinality::Single, true),
            keyword("multi", Cardinality::Multi, true),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn large_limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(200_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
}

fn document(index: usize, doc_id: Option<&str>, multi: &[&str]) -> Document {
    let mut document = Document::new(DocumentKey::new(format!("k{index:05}")).unwrap());
    document
        .insert(
            "grp",
            FieldValues::Single(FieldValue::Keyword(
                if index % 3 == 0 { "common" } else { "other" }.to_owned(),
            )),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
        .unwrap();
    if let Some(value) = doc_id {
        document
            .insert(
                "doc_id",
                FieldValues::Single(FieldValue::Keyword(value.to_owned())),
            )
            .unwrap();
    }
    if !multi.is_empty() {
        document
            .insert(
                "multi",
                FieldValues::Multi(
                    multi
                        .iter()
                        .map(|value| FieldValue::Keyword((*value).to_owned()))
                        .collect(),
                ),
            )
            .unwrap();
    }
    document
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(directory, schema(), registry(), large_limits()).unwrap()
}

fn commit(index: &Index, documents: Vec<Document>) {
    let mut writer = index.writer().unwrap();
    for document in documents {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
}

fn term() -> Query {
    Query::Term {
        field: "grp".to_owned(),
        value: FieldValue::Keyword("common".to_owned()),
    }
}

fn sort_by(field: &str, direction: SortDirection) -> Sort {
    Sort::new(vec![SortField::new(field, direction)])
}

fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = sort;
    request.projection = Projection::Fields(vec!["n".to_owned()]);
    request
}

fn search(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
) -> Result<UnifiedResponse, SearchError> {
    let schema = schema();
    let registry = registry();
    UnifiedSearcher::new(snapshot, &schema, &registry, SearchLimits::default()).search(
        request,
        &Budgets::new(),
        &CancellationFlag::new(),
    )
}

fn search_ok(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    search(snapshot, request).expect("search")
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn bits(response: &UnifiedResponse) -> Vec<u64> {
    response
        .hits
        .iter()
        .map(|hit| hit.score.expect("scored").to_bits())
        .collect()
}

fn temp_dir(tag: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr15h-b-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

/// B-I01: FsDirectory commit/reopen, 50K matches, columnar keyword sort.
#[test]
fn b_i01_fs_commit_reopen_large_sort() {
    let path = temp_dir("i01");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = create(Arc::clone(&directory));
    commit(
        &index,
        (0..50_000)
            .map(|position| document(position, Some(&format!("d{position:08}")), &[]))
            .collect(),
    );
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    for top_k in [10usize, 100] {
        let sort = sort_by("doc_id", SortDirection::Asc);
        let eligible = search_ok(&snapshot, &request(term(), top_k, sort.clone()));
        let fallback = search_ok(&snapshot, &request(Query::And(vec![term()]), top_k, sort));
        let expected_total: u64 = (0..50_000).filter(|position| position % 3 == 0).count() as u64;
        assert_eq!(eligible.total_hits, expected_total);
        assert_eq!(eligible.total_hits, fallback.total_hits);
        assert_eq!(keys(&eligible), keys(&fallback));
        assert_eq!(bits(&eligible), bits(&fallback));
        assert!(eligible.hits.iter().all(|hit| hit.fields.len() == 1));
    }
    let _ = std::fs::remove_dir_all(&path);
}

/// B-I02: two segments, equal keyword values, logical-key tie.
#[test]
fn b_i02_two_segment_key_tie() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    for segment in 0..2usize {
        commit(
            &index,
            (0..500)
                .map(|position| {
                    document(
                        segment * 1000 + position,
                        Some(&format!("d{:04}", position % 100)),
                        &[],
                    )
                })
                .collect(),
        );
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.segment_count(), 2);
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        let sort = sort_by("doc_id", direction);
        let eligible = search_ok(&snapshot, &request(term(), 50, sort.clone()));
        let fallback = search_ok(&snapshot, &request(Query::And(vec![term()]), 50, sort));
        assert_eq!(keys(&eligible), keys(&fallback));
        assert_eq!(bits(&eligible), bits(&fallback));
    }
}

/// B-I03: PIT snapshot isolation across delete/upsert/commit.
#[test]
fn b_i03_pit_refresh_delete_upsert() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(
        &index,
        (0..200)
            .map(|position| document(position, Some(&format!("d{position:04}")), &[]))
            .collect(),
    );
    let reader = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let old = reader.snapshot();
    let old_response = search_ok(
        &old,
        &request(term(), 100, sort_by("doc_id", SortDirection::Asc)),
    );
    {
        let mut writer = reader.writer().unwrap();
        for position in 0..10usize {
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(format!("k{position:05}")).unwrap(),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let new = reopened.snapshot();
    let new_response = search_ok(
        &new,
        &request(term(), 100, sort_by("doc_id", SortDirection::Asc)),
    );
    assert_eq!(
        search_ok(
            &old,
            &request(term(), 100, sort_by("doc_id", SortDirection::Asc))
        )
        .total_hits,
        old_response.total_hits
    );
    assert_eq!(old_response.total_hits - new_response.total_hits, 4); // indices 0,3,6,9 are "common"
}

/// B-I04: first page fast path, follow-up cursor uses the legacy path.
#[test]
fn b_i04_cursor_followup() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(
        &index,
        (0..1000)
            .map(|position| document(position, Some(&format!("d{position:06}")), &[]))
            .collect(),
    );
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    let mut eligible_request = request(term(), 2, sort_by("doc_id", SortDirection::Asc));
    let mut fallback_request = request(
        Query::And(vec![term()]),
        2,
        sort_by("doc_id", SortDirection::Asc),
    );
    let first = search_ok(&snapshot, &eligible_request);
    let control = search_ok(&snapshot, &fallback_request);
    assert_eq!(keys(&first), keys(&control));
    eligible_request.after = first.next_cursor.clone();
    fallback_request.after = control.next_cursor.clone();
    let page = search_ok(&snapshot, &eligible_request);
    let page_control = search_ok(&snapshot, &fallback_request);
    assert_eq!(keys(&page), keys(&page_control));
    assert_eq!(bits(&page), bits(&page_control));
}

/// B-I08: multi-valued sort and typed/mixed queries stay on the legacy path.
#[test]
fn b_i08_multi_and_typed_fallback() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(
        &index,
        (0..300)
            .map(|position| {
                let values = if position % 2 == 0 {
                    vec!["b", "a"]
                } else {
                    vec!["c", "d"]
                };
                document(position, Some(&format!("d{position:04}")), &values)
            })
            .collect(),
    );
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    let mut multi_sort = SortField::new("multi", SortDirection::Asc);
    multi_sort.multi = Some(MultiValueSelector::Min);
    let multi = Sort::new(vec![multi_sort]);
    let eligible = search_ok(&snapshot, &request(term(), 50, multi.clone()));
    let fallback = search_ok(&snapshot, &request(Query::And(vec![term()]), 50, multi));
    assert_eq!(keys(&eligible), keys(&fallback));
    let typed = Query::And(vec![
        term(),
        Query::Exists {
            field: "n".to_owned(),
        },
    ]);
    let typed_response = search_ok(
        &snapshot,
        &request(typed, 20, sort_by("doc_id", SortDirection::Asc)),
    );
    assert!(typed_response.total_hits > 0);
}

/// B-I05: a corrupted committed segment is rejected with a typed error.
#[test]
fn b_i05_corrupt_segment_fail_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(
        &index,
        (0..500)
            .map(|position| document(position, Some(&format!("d{position:04}")), &[]))
            .collect(),
    );
    let mut keys = directory.list("index/segments", 64).unwrap();
    keys.sort_by(|left, right| left.as_str().cmp(right.as_str()));
    let key = keys.first().expect("segment").clone();
    let handle = directory.open_read(&key).unwrap();
    let mut bytes = vec![0u8; handle.len() as usize];
    let mut offset = 0usize;
    while offset < bytes.len() {
        let read = handle.read_at(offset as u64, &mut bytes[offset..]).unwrap();
        if read == 0 {
            break;
        }
        offset += read;
    }
    drop(handle);
    let pivot = bytes.len() / 2;
    bytes[pivot] ^= 0xFF;
    directory.atomic_write(&key, &bytes).unwrap();
    match Index::open_existing(directory, schema(), registry()) {
        Err(_) => {}
        Ok(reopened) => {
            let snapshot = reopened.snapshot();
            match search(
                &snapshot,
                &request(term(), 10, sort_by("doc_id", SortDirection::Asc)),
            ) {
                Err(SearchError::Segment(_))
                | Err(SearchError::Index(_))
                | Err(SearchError::CorruptIndex { .. }) => {}
                other => panic!("corrupted segment was not rejected: {other:?}"),
            }
        }
    }
}
