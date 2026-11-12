//! PR 15I-D3-B production-path integration tests (I01–I12).
//!
//! Every expectation is derived from the frozen PR15D row formula or from a
//! deterministic enumeration of the fixture documents, never from the optimized
//! engine. The optimized implementation is only ever compared against those
//! independent oracles.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::mutation::QueryMutationSelector;
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher,
};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_path(name: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!(
        "quervant-d3b-{}-{}-{}",
        std::process::id(),
        DIRS.fetch_add(1, Ordering::SeqCst),
        name
    ));
    let _ = std::fs::remove_dir_all(&base);
    base
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "key",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            ),
            FieldDefinition::new(
                "group",
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
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "payload",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn limits() -> IndexLimits {
    IndexLimits::default()
        .with_max_pending_docs(200_000)
        .with_max_pending_bytes(512 * 1024 * 1024)
}

/// The frozen PR15D row formula, reproduced independently of the engine.
fn pr15d_document(index: usize) -> Document {
    let doc_id = format!("d{index:08}");
    let key = if index == 0 {
        "singleton"
    } else if index % 2 == 0 {
        "common"
    } else {
        "other"
    };
    let group = if index % 8 == 0 {
        "medium"
    } else {
        "different"
    };
    let body = if index % 2 == 0 {
        "alpha beta"
    } else {
        "gamma delta"
    };
    let mut document = Document::new(DocumentKey::new(doc_id.clone()).unwrap());
    for (name, value) in [
        ("key", key.to_owned()),
        ("group", group.to_owned()),
        ("doc_id", doc_id),
        ("payload", format!("payload-{index:08}")),
    ] {
        document
            .insert(name, FieldValues::Single(FieldValue::Keyword(value)))
            .unwrap();
    }
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Text(body.to_owned())),
        )
        .unwrap();
    document
}

fn uniform_document(index: usize) -> Document {
    let doc_id = format!("d{index:08}");
    let mut document = Document::new(DocumentKey::new(doc_id.clone()).unwrap());
    for (name, value) in [
        ("key", "common".to_owned()),
        ("group", "medium".to_owned()),
        ("doc_id", doc_id),
        ("payload", format!("payload-{index:08}")),
    ] {
        document
            .insert(name, FieldValues::Single(FieldValue::Keyword(value)))
            .unwrap();
    }
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Text("alpha beta".to_owned())),
        )
        .unwrap();
    document
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(directory, schema(), registry(), limits()).unwrap()
}

fn build(count: usize, make: impl Fn(usize) -> Document) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for position in 0..count {
            writer.insert(make(position)).unwrap();
        }
        writer.commit().unwrap();
    }
    Index::open_existing(directory, schema(), registry()).unwrap()
}

fn term(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    UnifiedRequest::new(query, TopK::new(top_k).unwrap())
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

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    search_with_limits(snapshot, request, SearchLimits::default()).expect("unified search")
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

/// Independent oracle: ascending PR15D document ids matching a predicate.
fn expected_ids(count: usize, predicate: impl Fn(usize) -> bool) -> Vec<String> {
    (0..count)
        .filter(|index| predicate(*index))
        .map(|index| format!("d{index:08}"))
        .collect()
}

fn prefix(ids: &[String], top_k: usize) -> Vec<String> {
    ids.iter().take(top_k).cloned().collect()
}

// I01: PR15D-shaped 10K and 100K single-term lanes with an independent oracle.
#[test]
fn i01_pr15d_shaped_lanes_match_independent_oracle() {
    for count in [10_000usize, 100_000] {
        let index = build(count, pr15d_document);
        let snapshot = index.snapshot();
        let common = expected_ids(count, |index| index != 0 && index % 2 == 0);
        let medium = expected_ids(count, |index| index % 8 == 0);
        assert_eq!(common.len(), count / 2 - 1);
        assert_eq!(medium.len(), count / 8);

        let response = search(&snapshot, &request(term("key", "common"), 100));
        assert_eq!(response.total_hits, common.len() as u64, "n={count}");
        assert_eq!(keys(&response), prefix(&common, 100), "n={count} K100");

        let response = search(&snapshot, &request(term("key", "common"), 10));
        assert_eq!(response.total_hits, common.len() as u64);
        assert_eq!(keys(&response), prefix(&common, 10), "n={count} K10");

        if count == 100_000 {
            let response = search(&snapshot, &request(term("group", "medium"), 100));
            assert_eq!(response.total_hits, medium.len() as u64);
            assert_eq!(keys(&response), prefix(&medium, 100));

            let rare = search(&snapshot, &request(term("key", "singleton"), 100));
            assert_eq!(rare.total_hits, 1);
            assert_eq!(keys(&rare), vec!["d00000000".to_owned()]);

            let absent = search(&snapshot, &request(term("key", "never"), 100));
            assert_eq!(absent.total_hits, 0);
            assert!(absent.hits.is_empty());
            assert!(absent.next_cursor.is_none());
        }
    }
}

// I02: 101/102/1000 matches with TopK=100 paginate without duplicate or omission.
#[test]
fn i02_pagination_over_one_hundred() {
    for count in [101usize, 102, 1_000] {
        let index = build(count, uniform_document);
        let snapshot = index.snapshot();
        let expected = expected_ids(count, |_| true);
        let mut request = request(term("key", "common"), 100);
        let mut collected = Vec::new();
        loop {
            let response = search(&snapshot, &request);
            assert_eq!(response.total_hits, count as u64);
            collected.extend(keys(&response));
            match response.next_cursor {
                Some(cursor) => {
                    assert!(collected.len() < count, "cursor past the last hit");
                    request.after = Some(cursor);
                }
                None => break,
            }
        }
        assert_eq!(collected, expected, "n={count}");
    }
}

// I03: equal scores with distinct keys keep the key tie-break for both sort
// directions, including Unicode keys, and preserve score bits exactly.
#[test]
fn i03_equal_score_tie_break_and_sort_directions() {
    let index = build(5, uniform_document);
    let snapshot = index.snapshot();
    let response = search(&snapshot, &request(term("key", "common"), 100));
    assert_eq!(keys(&response), expected_ids(5, |_| true));
    let bits = score_bits(&response);
    assert!(bits.iter().all(|value| *value == bits[0]));

    let mut ascending = request(term("key", "common"), 100);
    ascending.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let response = search(&snapshot, &ascending);
    assert_eq!(keys(&response), expected_ids(5, |_| true));

    let mut descending = request(term("key", "common"), 100);
    descending.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Desc)]);
    let response = search(&snapshot, &descending);
    let mut reversed = expected_ids(5, |_| true);
    reversed.reverse();
    assert_eq!(keys(&response), reversed);
}

// I04: TopK 99/100/101 with 101 hits has no off-by-one and no hidden cursor.
#[test]
fn i04_topk_boundary_with_one_hundred_one_hits() {
    let index = build(101, uniform_document);
    let snapshot = index.snapshot();
    for top_k in [99usize, 100] {
        let response = search(&snapshot, &request(term("key", "common"), top_k));
        assert_eq!(response.total_hits, 101);
        assert_eq!(response.hits.len(), top_k);
        assert!(response.next_cursor.is_some(), "K{top_k}");
    }
    let response = search(&snapshot, &request(term("key", "common"), 101));
    assert_eq!(response.total_hits, 101);
    assert_eq!(response.hits.len(), 101);
    assert!(response.next_cursor.is_none(), "K101 exhausts the matches");
}

// I05: one committed segment and multiple committed segments agree exactly.
#[test]
fn i05_single_and_multi_segment_parity() {
    let single = build(200, uniform_document);
    let multi_directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let multi = create(Arc::clone(&multi_directory));
    {
        let mut writer = multi.writer().unwrap();
        for position in 0..100 {
            writer.insert(uniform_document(position)).unwrap();
        }
        writer.commit().unwrap();
        for position in 100..200 {
            writer.insert(uniform_document(position)).unwrap();
        }
        writer.commit().unwrap();
    }
    let multi = Index::open_existing(multi_directory, schema(), registry()).unwrap();
    let single_snapshot = single.snapshot();
    let multi_snapshot = multi.snapshot();
    let request = request(term("key", "common"), 100);
    let first = search(&single_snapshot, &request);
    let second = search(&multi_snapshot, &request);
    assert_eq!(first.total_hits, second.total_hits);
    assert_eq!(keys(&first), keys(&second));
    assert_eq!(score_bits(&first), score_bits(&second));
    assert_eq!(
        keys(&first),
        expected_ids(200, |_| true)
            .into_iter()
            .take(100)
            .collect::<Vec<_>>()
    );
}

// I06: the candidate budget keeps exact-at acceptance and one-under rejection
// with the unchanged typed error. The minimal accepted ceiling is discovered by
// bisection so the boundary is measured rather than assumed.
#[test]
fn i06_candidate_budget_exact_one_over() {
    let index = build(3, uniform_document);
    let snapshot = index.snapshot();
    let request = request(term("key", "common"), 1);
    let default = search(&snapshot, &request);
    assert_eq!(default.total_hits, 3);
    assert_eq!(default.hits.len(), 1);

    let attempt = |ceiling: u64| -> Result<(), u64> {
        let limits = SearchLimits::default()
            .with_max_total_candidate_bytes(ceiling)
            .unwrap();
        match search_with_limits(&snapshot, &request, limits) {
            Ok(response) => {
                assert_eq!(response.total_hits, 3);
                assert_eq!(response.hits.len(), 1);
                Ok(())
            }
            Err(SearchError::ResourceLimit { limit, requested }) => {
                assert_eq!(limit, ceiling);
                Err(requested)
            }
            Err(other) => panic!("unexpected error: {other:?}"),
        }
    };

    let mut low = 1u64;
    let mut high = match attempt(low) {
        Err(requested) => requested.max(low + 1),
        Ok(()) => panic!("a one-byte candidate ceiling must reject this query"),
    };
    let mut guard = 0u32;
    while attempt(high).is_err() {
        guard += 1;
        assert!(guard <= 8, "budget probe did not converge");
        high = high.checked_mul(2).expect("budget probe overflow");
    }
    while high - low > 1 {
        let middle = low + (high - low) / 2;
        if attempt(middle).is_ok() {
            high = middle;
        } else {
            low = middle;
        }
    }
    assert!(attempt(high).is_ok(), "exact-at budget must be accepted");
    let requested = attempt(high - 1).unwrap_err();
    assert!(
        requested > high - 1,
        "one-under budget must request more than its ceiling"
    );
}

// I07: a pinned old snapshot is isolated from later delete/upsert commits.
#[test]
fn i07_pinned_snapshot_isolated_from_mutation() {
    let index = build(120, |position| {
        let mut document = uniform_document(position);
        if position < 20 {
            document
                .insert(
                    "key",
                    FieldValues::Single(FieldValue::Keyword("gone".to_owned())),
                )
                .unwrap();
        }
        document
    });
    let mut writer = index.writer().unwrap();
    let pinned = writer.pin().unwrap();
    let pinned_snapshot = Arc::clone(pinned.snapshot());
    assert_eq!(
        search(&pinned_snapshot, &request(term("key", "gone"), 100)).total_hits,
        20
    );
    writer
        .delete_by_query(
            QueryMutationSelector {
                query: term("key", "gone"),
                max_matches: 100,
                expected_generation: None,
            },
            &CancellationFlag::new(),
        )
        .unwrap();
    writer.insert(uniform_document(500)).unwrap();
    writer.commit().unwrap();

    let current = writer.reader();
    assert_eq!(
        search(&current, &request(term("key", "gone"), 100)).total_hits,
        0
    );
    assert_eq!(
        search(&current, &request(term("key", "common"), 100)).total_hits,
        101
    );
    assert_eq!(
        search(&pinned_snapshot, &request(term("key", "gone"), 100)).total_hits,
        20,
        "the pinned generation keeps its original view"
    );
    assert_eq!(
        search(&pinned_snapshot, &request(term("key", "common"), 100)).total_hits,
        100
    );
    drop(pinned);
}

// I08: borrowed and owned keyword-sort paths select identical pages and scores.
// A cursor request is not eligible for the borrowed view, so the second page
// exercises the owned tuple path while the first page uses the borrowed view.
#[test]
fn i08_keyword_sort_borrowed_and_owned_parity() {
    let index = build(150, uniform_document);
    let snapshot = index.snapshot();
    let request = request(term("key", "common"), 100);
    let mut borrowed = request.clone();
    borrowed.sort = Sort::new(vec![SortField::new("doc_id", SortDirection::Asc)]);
    let first = search(&snapshot, &borrowed);
    assert_eq!(first.total_hits, 150);
    assert_eq!(keys(&first), prefix(&expected_ids(150, |_| true), 100));
    let bits = score_bits(&first);
    assert!(bits.iter().all(|value| *value == bits[0]));

    let mut page = borrowed.clone();
    page.after = first.next_cursor.clone();
    let second = search(&snapshot, &page);
    assert_eq!(
        keys(&second),
        expected_ids(150, |_| true)
            .into_iter()
            .skip(100)
            .collect::<Vec<_>>()
    );
    let second_bits = score_bits(&second);
    assert!(second_bits.iter().all(|value| *value == bits[0]));

    // An invalid sort field keeps its original typed validation error.
    let mut invalid = request;
    invalid.sort = Sort::new(vec![SortField::new("body", SortDirection::Asc)]);
    let error = search_with_limits(&snapshot, &invalid, SearchLimits::default()).unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

// I10: concurrent searches with independent filters are deterministic.
#[test]
fn i10_concurrent_requests_are_independent() {
    let index = build(150, uniform_document);
    let results: Vec<Vec<String>> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..2)
            .map(|_| {
                scope.spawn(|| {
                    let snapshot = index.snapshot();
                    keys(&search(&snapshot, &request(term("key", "common"), 100)))
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect()
    });
    assert_eq!(results[0], results[1]);
    assert_eq!(results[0], prefix(&expected_ids(150, |_| true), 100));
}

// I11: a real FsDirectory commit survives close/reopen with identical results.
#[test]
fn i11_fs_directory_reopen_parity() {
    let root = temp_path("d3b-fs");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits()).unwrap();
    {
        let mut writer = index.writer().unwrap();
        for position in 0..120 {
            writer.insert(uniform_document(position)).unwrap();
        }
        writer.commit().unwrap();
    }
    let request = request(term("key", "common"), 100);
    drop(index);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let before = search(&reopened.snapshot(), &request);
    drop(reopened);
    let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
    let after = search(&reopened.snapshot(), &request);
    assert_eq!(before.total_hits, after.total_hits);
    assert_eq!(keys(&before), keys(&after));
    assert_eq!(score_bits(&before), score_bits(&after));
    let _ = std::fs::remove_dir_all(&root);
}

// I12: real RustFS/S3 cold bootstrap parity (ignored; requires the documented
// environment and the `s3` feature). A missing service is reported as
// RUSTFS_PENDING, never as a pass.
#[cfg(feature = "s3")]
mod real_rustfs {
    use super::*;
    use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix};

    fn require_env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        assert!(endpoint.starts_with("http://"));
        (endpoint, bucket, access, secret, region)
    }

    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("d3b-rustfs".to_owned())
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("tokio runtime");
                runtime.block_on(body);
            })
            .expect("spawn");
        handle.join().expect("real RustFS test panicked");
    }

    #[test]
    #[ignore = "requires a real RustFS service (see tests/rustfs/README.md)"]
    fn i12_real_rustfs_cold_bootstrap_query_parity() {
        run(async move {
            let (endpoint, bucket, access, secret, region) = require_env();
            let store = Arc::new(
                quervant_objectstore::S3ObjectStore::new(quervant_objectstore::S3Config::rustfs(
                    endpoint, region, bucket, access, secret,
                ))
                .expect("valid RustFS config"),
            );
            store.create_bucket_if_absent().await.expect("bucket");
            let run_tag = format!("d3b-i12-{}", std::process::id());
            let prefix = format!("pr15i-d3b/{run_tag}");
            let cache = temp_path("d3b-cache");
            let config = RemoteConfig::new(RemoteKeyPrefix::parse(&prefix).expect("prefix"), cache);
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                limits(),
            )
            .await
            .expect("create remote");
            {
                let mut writer = index.writer().await.expect("writer");
                for position in 0..120 {
                    writer.insert(uniform_document(position)).unwrap();
                }
                writer.commit().await.expect("commit");
            }
            let request = request(term("key", "common"), 100);
            let writer_view = search(&index.snapshot(), &request);
            let cold = RemoteIndex::open_existing(
                Arc::clone(&store),
                RemoteConfig::new(
                    RemoteKeyPrefix::parse(&prefix).expect("prefix"),
                    temp_path("d3b-cold"),
                ),
                schema(),
                registry(),
                limits(),
            )
            .await
            .expect("cold open")
            .snapshot();
            let cold_view = search(&cold, &request);
            assert_eq!(writer_view.total_hits, 120);
            assert_eq!(keys(&writer_view), keys(&cold_view));
            assert_eq!(score_bits(&writer_view), score_bits(&cold_view));
        });
    }
}
