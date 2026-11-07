//! PR 15H-A2 real local production-path integration tests.
//!
//! These exercise the public `Index`/`IndexWriter`/`UnifiedSearcher` boundary for
//! the cardinality-gated single-term route. The below- and above-threshold paths
//! are compared with the ineligible `And([Term])` oracle and with an independent
//! document-set count. No crate-private helper is reached.

use std::path::PathBuf;
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag};
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
use sha2::{Digest, Sha256};

const BOUNDARY_TOTAL: usize = 8_193;

fn schema() -> Schema {
    let keyword = |name: &str| {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )
    };
    Schema::new(
        vec![
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            keyword("tag1"),
            keyword("tag4999"),
            keyword("tag8191"),
            keyword("tag8192"),
            keyword("tag8193"),
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

fn boundary_documents() -> Vec<Document> {
    (0..BOUNDARY_TOTAL)
        .map(|index| {
            let mut document = Document::new(DocumentKey::new(format!("k{index:05}")).unwrap());
            document
                .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
                .unwrap();
            for (field, limit) in [
                ("tag1", 1usize),
                ("tag4999", 4_999),
                ("tag8191", 8_191),
                ("tag8192", 8_192),
                ("tag8193", 8_193),
            ] {
                if index < limit {
                    document
                        .insert(
                            field,
                            FieldValues::Single(FieldValue::Keyword("mark".to_owned())),
                        )
                        .unwrap();
                }
            }
            document
        })
        .collect()
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

fn keyword(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn request(query: Query, top_k: usize, sort: Option<&str>) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    if let Some(field) = sort {
        request.sort = Sort::new(vec![SortField::new(field, SortDirection::Asc)]);
    }
    request.projection = Projection::Fields(vec!["n".to_owned()]);
    request
}

fn search(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
    limits: SearchLimits,
) -> Result<UnifiedResponse, SearchError> {
    let schema = schema();
    let registry = registry();
    UnifiedSearcher::new(snapshot, &schema, &registry, limits).search(
        request,
        &Budgets::new(),
        &CancellationFlag::new(),
    )
}

fn search_default(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    search(snapshot, request, SearchLimits::default()).expect("unified search")
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

fn temp_dir(tag: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr15h-a2-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

fn read_all(directory: &dyn Directory, key: &quervant_core::storage::StorageKey) -> Vec<u8> {
    let handle = directory.open_read(key).unwrap();
    let mut bytes = vec![0u8; handle.len() as usize];
    let mut offset = 0usize;
    while offset < bytes.len() {
        let read = handle.read_at(offset as u64, &mut bytes[offset..]).unwrap();
        if read == 0 {
            break;
        }
        offset += read;
    }
    bytes
}

fn segment_digests(directory: &dyn Directory) -> Vec<(String, Vec<u8>)> {
    let mut keys = directory.list("index/segments", 256).unwrap();
    keys.sort_by(|left, right| left.as_str().cmp(right.as_str()));
    keys.into_iter()
        .map(|key| {
            let bytes = read_all(directory, &key);
            let mut digest = Sha256::new();
            digest.update(&bytes);
            (key.as_str().to_owned(), digest.finalize().to_vec())
        })
        .collect()
}

/// A2-I01: local commit/reopen with 0/1/4,999/8,191/8,192/8,193 matches, exact
/// totals, key order, score parity and projection.
#[test]
fn a2_i01_local_commit_reopen_boundary() {
    let path = temp_dir("i01");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = create(Arc::clone(&directory));
    commit(&index, boundary_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();

    for (field, value, expected) in [
        ("tag1", "absent", 0u64),
        ("tag1", "mark", 1),
        ("tag4999", "mark", 4_999),
        ("tag8191", "mark", 8_191),
        ("tag8192", "mark", 8_192),
        ("tag8193", "mark", 8_193),
    ] {
        let eligible = search_default(&snapshot, &request(keyword(field, value), 100, Some("n")));
        let fallback = search_default(
            &snapshot,
            &request(Query::And(vec![keyword(field, value)]), 100, Some("n")),
        );
        assert_eq!(eligible.total_hits, expected, "{field}/{value}");
        assert_eq!(eligible.total_hits, fallback.total_hits, "{field}/{value}");
        assert_eq!(keys(&eligible), keys(&fallback), "{field}/{value}");
        assert_eq!(
            score_bits(&eligible),
            score_bits(&fallback),
            "{field}/{value}"
        );
        assert!(eligible.hits.iter().all(|hit| hit.fields.len() == 1));
    }
    let _ = std::fs::remove_dir_all(&path);
}

/// A2-I02: 100K deterministic common/medium/rare terms with explicit sort K10/K100.
#[test]
fn a2_i02_100k_mixed_cardinality() {
    let keyword_field = |name: &str| {
        FieldDefinition::new(
            name,
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )
    };
    let schema_100k = Schema::new(
        vec![
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            keyword_field("common"),
            keyword_field("medium"),
            keyword_field("rare"),
        ],
        None,
    )
    .unwrap();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema_100k.clone(),
        registry(),
        large_limits(),
    )
    .unwrap();
    {
        let mut writer = index.writer().unwrap();
        for position in 0..100_000usize {
            let mut document = Document::new(DocumentKey::new(format!("k{position:06}")).unwrap());
            document
                .insert("n", FieldValues::Single(FieldValue::I64(position as i64)))
                .unwrap();
            document
                .insert(
                    "common",
                    FieldValues::Single(FieldValue::Keyword("hit".to_owned())),
                )
                .unwrap();
            if position % 8 == 0 {
                document
                    .insert(
                        "medium",
                        FieldValues::Single(FieldValue::Keyword("hit".to_owned())),
                    )
                    .unwrap();
            }
            if position == 0 {
                document
                    .insert(
                        "rare",
                        FieldValues::Single(FieldValue::Keyword("hit".to_owned())),
                    )
                    .unwrap();
            }
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = Index::open_existing(directory, schema_100k.clone(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    for (field, expected) in [("common", 100_000u64), ("medium", 12_500), ("rare", 1)] {
        for top_k in [10usize, 100] {
            let eligible = UnifiedSearcher::new(
                &snapshot,
                &schema_100k,
                &registry(),
                SearchLimits::default(),
            )
            .search(
                &request(keyword(field, "hit"), top_k, Some("n")),
                &Budgets::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
            let fallback = UnifiedSearcher::new(
                &snapshot,
                &schema_100k,
                &registry(),
                SearchLimits::default(),
            )
            .search(
                &request(Query::And(vec![keyword(field, "hit")]), top_k, Some("n")),
                &Budgets::new(),
                &CancellationFlag::new(),
            )
            .unwrap();
            assert_eq!(eligible.total_hits, expected, "{field}/{top_k}");
            assert_eq!(eligible.total_hits, fallback.total_hits, "{field}/{top_k}");
            assert_eq!(keys(&eligible), keys(&fallback), "{field}/{top_k}");
            assert_eq!(
                score_bits(&eligible),
                score_bits(&fallback),
                "{field}/{top_k}"
            );
        }
    }
}

/// A2-I03: two segments, one falling below the gate after deletion, plus PIT.
#[test]
fn a2_i03_two_segment_live_dispatch_and_pit() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    for (segment, count) in [(0usize, 8_192usize), (1, 8_192)] {
        let mut writer = index.writer().unwrap();
        for position in 0..count {
            let mut document =
                Document::new(DocumentKey::new(format!("s{segment}-{position:05}")).unwrap());
            document
                .insert("n", FieldValues::Single(FieldValue::I64(position as i64)))
                .unwrap();
            document
                .insert(
                    "tag8192",
                    FieldValues::Single(FieldValue::Keyword("mark".to_owned())),
                )
                .unwrap();
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let reader_before = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let before = reader_before.snapshot();
    let before_response =
        search_default(&before, &request(keyword("tag8192", "mark"), 10, Some("n")));
    assert_eq!(before_response.total_hits, 16_384);

    {
        let mut writer = reader_before.writer().unwrap();
        for position in 0..10usize {
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(format!("s0-{position:05}")).unwrap(),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let reader_after = Index::open_existing(directory, schema(), registry()).unwrap();
    let after = reader_after.snapshot();
    let after_response =
        search_default(&after, &request(keyword("tag8192", "mark"), 10, Some("n")));
    assert_eq!(after_response.total_hits, 16_384 - 10);
    // The pinned PIT still observes the original committed generation.
    assert_eq!(
        search_default(&before, &request(keyword("tag8192", "mark"), 10, Some("n"))).total_hits,
        16_384
    );
}

/// A2-I04: the linear route preserves the 48+64 virtual peak and typed failure.
#[test]
fn a2_i04_candidate_budget_boundary() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(&index, boundary_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    let request = request(keyword("tag8192", "mark"), 10, Some("n"));
    let peak = 8_192u64 * (16 + 48 + 64);
    let exact = SearchLimits::default()
        .with_max_segment_candidate_entries(30_000)
        .unwrap()
        .with_max_total_candidate_bytes(peak)
        .unwrap();
    let one_under = SearchLimits::default()
        .with_max_segment_candidate_entries(30_000)
        .unwrap()
        .with_max_total_candidate_bytes(peak - 1)
        .unwrap();
    assert!(search(&snapshot, &request, exact).is_ok());
    assert!(matches!(
        search(&snapshot, &request, one_under),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert!(search(&snapshot, &request, SearchLimits::default()).is_ok());
}

/// A2-I05: cancellation on high and low cardinality paths is typed and clean.
#[test]
fn a2_i05_cancellation_high_and_low() {
    struct CancelAt {
        polls: std::sync::atomic::AtomicU64,
        cancel_at: u64,
    }
    impl Cancellation for CancelAt {
        fn is_cancelled(&self) -> bool {
            self.polls
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
                >= self.cancel_at
        }
    }
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(&index, boundary_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();
    let schema = schema();
    let registry = registry();
    for field in ["tag1", "tag8192"] {
        let request = request(keyword(field, "mark"), 10, Some("n"));
        for cancel_at in [0u64, 1] {
            let cancel = CancelAt {
                polls: std::sync::atomic::AtomicU64::new(0),
                cancel_at,
            };
            let searcher =
                UnifiedSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
            assert!(matches!(
                searcher.search(&request, &Budgets::new(), &cancel),
                Err(SearchError::Cancelled)
            ));
        }
        assert!(search(&snapshot, &request, SearchLimits::default()).is_ok());
    }
}

/// A2-I06: explicit sort, relevance sort, cursor, typed+lexical and negation.
#[test]
fn a2_i06_sort_cursor_typed_negative() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(&index, boundary_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let snapshot = reopened.snapshot();

    // Explicit numeric sort and relevance sort produce identical linear/fallback
    // ordering because the score bits are identical.
    for sort in [Some("n"), None] {
        let eligible = search_default(&snapshot, &request(keyword("tag8192", "mark"), 10, sort));
        let fallback = search_default(
            &snapshot,
            &request(Query::And(vec![keyword("tag8192", "mark")]), 10, sort),
        );
        assert_eq!(keys(&eligible), keys(&fallback));
        assert_eq!(score_bits(&eligible), score_bits(&fallback));
    }

    // Cursor: the first page is linear, the cursor follow-up is ineligible.
    let eligible_request = request(keyword("tag8192", "mark"), 2, Some("n"));
    let fallback_request = request(Query::And(vec![keyword("tag8192", "mark")]), 2, Some("n"));
    let first = search_default(&snapshot, &eligible_request);
    let control = search_default(&snapshot, &fallback_request);
    assert_eq!(keys(&first), keys(&control));
    let mut next = eligible_request;
    next.after = first.next_cursor.clone();
    let mut next_control = fallback_request;
    next_control.after = control.next_cursor.clone();
    let page = search_default(&snapshot, &next);
    let page_control = search_default(&snapshot, &next_control);
    assert_eq!(keys(&page), keys(&page_control));

    // Typed+lexical and negative-only shapes stay on the fallback.
    let typed = Query::And(vec![
        keyword("tag8192", "mark"),
        Query::Exists {
            field: "n".to_owned(),
        },
    ]);
    let typed_response = search_default(&snapshot, &request(typed, 10, Some("n")));
    assert_eq!(typed_response.total_hits, 8_192);
    let negative = search_default(
        &snapshot,
        &request(
            Query::Not(Box::new(keyword("tag8192", "mark"))),
            10,
            Some("n"),
        ),
    );
    assert_eq!(negative.total_hits, (BOUNDARY_TOTAL - 8_192) as u64);
}

/// A2-I07: a corrupted committed segment is rejected with a typed error.
#[test]
fn a2_i07_corruption_fail_closed() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit(&index, boundary_documents());
    let mut keys = directory.list("index/segments", 64).unwrap();
    keys.sort_by(|left, right| left.as_str().cmp(right.as_str()));
    let key = keys.first().expect("segment").clone();
    let mut bytes = read_all(directory.as_ref(), &key);
    assert!(!bytes.is_empty());
    let pivot = bytes.len() / 2;
    bytes[pivot] ^= 0xFF;
    directory.atomic_write(&key, &bytes).unwrap();
    match Index::open_existing(directory, schema(), registry()) {
        Err(_) => {}
        Ok(reopened) => {
            let snapshot = reopened.snapshot();
            match search(
                &snapshot,
                &request(keyword("tag8192", "mark"), 10, Some("n")),
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

/// A2-I08: fresh `FsDirectory` reopen and deterministic rebuild bytes.
#[test]
fn a2_i08_fs_reopen_and_deterministic_rebuild() {
    let first = temp_dir("i08a");
    let second = temp_dir("i08b");
    let mut digests = Vec::new();
    for path in [&first, &second] {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(path).unwrap());
        let index = create(Arc::clone(&directory));
        commit(&index, boundary_documents());
        digests.push(segment_digests(directory.as_ref()));
    }
    assert_eq!(digests[0], digests[1]);
    let reopened = {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&first).unwrap());
        Index::open_existing(directory, schema(), registry()).unwrap()
    };
    let snapshot = reopened.snapshot();
    assert_eq!(
        search_default(
            &snapshot,
            &request(keyword("tag8192", "mark"), 10, Some("n"))
        )
        .total_hits,
        8_192
    );
    let _ = std::fs::remove_dir_all(&first);
    let _ = std::fs::remove_dir_all(&second);
}
