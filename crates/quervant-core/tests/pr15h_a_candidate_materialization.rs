//! PR 15H-A real local production-path integration tests.
//!
//! These exercise the public index/writer/reader/search boundary for the linear
//! single-term candidate branch. The optimized `Term` request is compared with
//! its ineligible but logically equivalent `And([Term])` fallback, and with an
//! independent document-set oracle. No crate-private helper is reached.

use std::path::PathBuf;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, MutationRequest,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

const TOTAL: usize = 2048;

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
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

/// Deterministic title for one document index.
fn title_for(index: usize) -> &'static str {
    if index == 7 {
        "zeta alpha"
    } else if index % 5 == 0 {
        "alpha beta common"
    } else if index % 3 == 0 {
        "alpha"
    } else {
        "beta"
    }
}

/// Deterministic corpus: `alpha` on about two thirds, `zeta` once at index 7,
/// `common` on every fifth document and a few adjacent `alpha beta` phrases.
fn documents(count: usize) -> Vec<Document> {
    (0..count)
        .map(|index| {
            let mut document = Document::new(DocumentKey::new(format!("k{index:05}")).unwrap());
            document
                .insert(
                    "title",
                    FieldValues::Single(FieldValue::Text(title_for(index).to_owned())),
                )
                .unwrap();
            document
                .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
                .unwrap();
            document
        })
        .collect()
}

fn count_any(count: usize, needles: &[&str]) -> u64 {
    (0..count)
        .filter(|index| {
            needles
                .iter()
                .any(|needle| title_for(*index).contains(needle))
        })
        .count() as u64
}

fn count_all(count: usize, needles: &[&str]) -> u64 {
    (0..count)
        .filter(|index| {
            needles
                .iter()
                .all(|needle| title_for(*index).contains(needle))
        })
        .count() as u64
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(directory, schema(), registry(), IndexLimits::default()).unwrap()
}

fn commit_documents(index: &Index, documents: Vec<Document>) {
    let mut writer = index.writer().unwrap();
    for document in documents {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
}

fn term(value: &str) -> Query {
    Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text(value.to_owned()),
    }
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["n".to_owned()]);
    request
}

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn search_with_limits(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
    limits: SearchLimits,
) -> Result<UnifiedResponse, SearchError> {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), limits).search(
        request,
        &Budgets::new(),
        &CancellationFlag::new(),
    )
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn score_bits(response: &UnifiedResponse) -> Vec<u64> {
    response
        .hits
        .iter()
        .map(|hit| hit.score.expect("scored hit").to_bits())
        .collect()
}

fn alpha_oracle(count: usize) -> usize {
    count_any(count, &["alpha"]) as usize
}

fn temp_dir(tag: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr15h-a-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

/// HA-I01: real `FsDirectory` write → commit → fresh reopen → term query.
#[test]
fn h_a_i01_local_commit_reopen_term_query() {
    let path = temp_dir("i01");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = create(Arc::clone(&directory));
    commit_documents(&index, documents(TOTAL));
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();

    let expected_total = alpha_oracle(TOTAL) as u64;
    for top_k in [10usize, 100] {
        let eligible = search(&snapshot, &request(term("alpha"), top_k));
        let fallback = search(&snapshot, &request(Query::And(vec![term("alpha")]), top_k));
        assert_eq!(eligible.total_hits, expected_total);
        assert_eq!(eligible.total_hits, fallback.total_hits);
        assert_eq!(keys(&eligible), keys(&fallback));
        assert_eq!(score_bits(&eligible), score_bits(&fallback));
        assert!(eligible.hits.iter().all(|hit| hit.fields.len() == 1));
    }
    let _ = std::fs::remove_dir_all(&path);
}

/// HA-I02: two committed segments with sparse, medium and common terms match the
/// fallback for doc ids and exact scores.
#[test]
fn h_a_i02_two_segment_differential() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    let mut all = documents(TOTAL);
    let second = all.split_off(TOTAL / 2);
    commit_documents(&index, all);
    commit_documents(&index, second);
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.segment_count(), 2);

    for value in ["zeta", "alpha", "common"] {
        let eligible = search(&snapshot, &request(term(value), 100));
        let fallback = search(&snapshot, &request(Query::And(vec![term(value)]), 100));
        assert_eq!(eligible.total_hits, fallback.total_hits, "{value}");
        assert_eq!(keys(&eligible), keys(&fallback), "{value}");
        assert_eq!(score_bits(&eligible), score_bits(&fallback), "{value}");
    }
}

/// HA-I03: mixed compound and negative shapes stay on the unchanged fallback.
#[test]
fn h_a_i03_mixed_fallback_shapes() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit_documents(&index, documents(TOTAL));
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();

    let alpha = count_any(TOTAL, &["alpha"]);
    let cases: Vec<(Query, u64)> = vec![
        (Query::MatchAll, TOTAL as u64),
        (
            Query::Or(vec![term("alpha"), term("zeta")]),
            count_any(TOTAL, &["alpha", "zeta"]),
        ),
        (Query::Not(Box::new(term("alpha"))), TOTAL as u64 - alpha),
        (
            Query::And(vec![term("alpha"), term("common")]),
            count_all(TOTAL, &["alpha", "common"]),
        ),
        (
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned(), "beta".to_owned()],
            },
            count_all(TOTAL, &["alpha beta"]),
        ),
    ];
    for (query, expected) in cases {
        let response = search(&snapshot, &request(query.clone(), 100));
        assert_eq!(response.total_hits, expected, "{query:?}");
    }
}

/// HA-I04: a point-in-time snapshot is unchanged by later delete/upsert/commit.
#[test]
fn h_a_i04_pit_refresh_delete_upsert() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit_documents(&index, documents(64));
    // `Index::snapshot` is bound to the generation observed at open, so reopen
    // to observe the newly committed generation.
    let reader = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let old = reader.snapshot();
    let old_alpha = search(&old, &request(term("alpha"), 100));

    {
        let mut writer = reader.writer().unwrap();
        writer
            .apply(MutationRequest::delete(
                DocumentKey::new("k00000".to_owned()).unwrap(),
            ))
            .unwrap();
        let mut replacement = Document::new(DocumentKey::new("k00001".to_owned()).unwrap());
        replacement
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("alpha".to_owned())),
            )
            .unwrap();
        replacement
            .insert("n", FieldValues::Single(FieldValue::I64(1)))
            .unwrap();
        writer.apply(MutationRequest::upsert(replacement)).unwrap();
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let new = reopened.snapshot();
    let new_alpha = search(&new, &request(term("alpha"), 100));

    // The old snapshot still sees the original generation.
    assert_eq!(
        search(&old, &request(term("alpha"), 100)).total_hits,
        old_alpha.total_hits
    );
    // k00000 was alpha, k00001 becomes alpha: the total is unchanged but the
    // membership identity changes on the new snapshot.
    assert_eq!(old_alpha.total_hits, new_alpha.total_hits);
    assert!(keys(&old_alpha).contains(&"k00000".to_owned()));
    assert!(!keys(&new_alpha).contains(&"k00000".to_owned()));
    assert!(keys(&new_alpha).contains(&"k00001".to_owned()));
}

/// HA-I05: tight candidate byte limits and cancellation are typed and clean up.
#[test]
fn h_a_i05_limits_and_cancellation() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit_documents(&index, documents(TOTAL));
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    let eligible = request(term("alpha"), 100);
    let fallback = request(Query::And(vec![term("alpha")]), 100);

    let tight = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .unwrap();
    for request in [&eligible, &fallback] {
        assert!(matches!(
            search_with_limits(&snapshot, request, tight),
            Err(SearchError::ResourceLimit { .. })
        ));
        // The same snapshot still succeeds after the rejection (no leak).
        assert!(search_with_limits(&snapshot, request, SearchLimits::default()).is_ok());
    }

    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    let schema = schema();
    let registry = registry();
    for request in [&eligible, &fallback] {
        let searcher = UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
        assert!(matches!(
            searcher.search(request, &Budgets::new(), &cancelled),
            Err(SearchError::Cancelled)
        ));
    }
}

/// HA-I06: a corrupted committed segment is rejected with a typed error.
#[test]
fn h_a_i06_corruption_injection() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit_documents(&index, documents(256));

    let mut segment_keys = directory.list("index/segments", 64).unwrap();
    segment_keys.sort_by(|left, right| left.as_str().cmp(right.as_str()));
    let key = segment_keys.first().expect("committed segment").clone();
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
    assert!(!bytes.is_empty());
    let pivot = bytes.len() / 2;
    bytes[pivot] ^= 0xFF;
    directory.atomic_write(&key, &bytes).unwrap();

    match Index::open_existing(directory, schema(), registry()) {
        Err(_) => {}
        Ok(reopened) => {
            let snapshot = reopened.snapshot();
            match search_with_limits(
                &snapshot,
                &request(term("alpha"), 10),
                SearchLimits::default(),
            ) {
                Err(SearchError::Segment(_))
                | Err(SearchError::Index(_))
                | Err(SearchError::CorruptIndex { .. }) => {}
                other => panic!("corrupted segment was not rejected: {other:?}"),
            }
        }
    }
}
