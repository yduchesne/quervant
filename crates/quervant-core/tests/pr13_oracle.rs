//! PR 13 independent query-equivalence oracle (O01–O10).
//!
//! Expected hit sets are enumerated by hand from the corpus/query semantics in
//! `expected_queries`; they are **not** derived from any Quervant run. The same
//! corpus and expectations are checked against a local `FsDirectory`, a fake
//! object store and real RustFS after a cold reopen.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::MutationRequest;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{Bound, Query};
use quervant_core::contract::result::{Sort, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, Timestamp};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{LexicalSearcher, SearchLimits, TypedSearchRequest, TypedSearcher};
use quervant_core::storage::{Directory, FsDirectory};
use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_dir(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-oracle-{}-{name}-{n}", std::process::id()))
}

fn temp_workspace(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!(
        "quervant-oracle-ws-{}-{name}-{n}",
        std::process::id()
    ))
}

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
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// The fixed corpus: key, title, n, ts(micros), tag.
const CORPUS: &[(&str, &str, i64, i64, &str)] = &[
    ("a", "alpha beta", 10, 1_000, "x"),
    ("b", "beta gamma", 20, 2_000, "y"),
    ("c", "alpha gamma", 30, 3_000, "x"),
];

fn document(key: &str, title: &str, n: i64, ts: i64, tag: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(title.to_owned())),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    document
        .insert(
            "ts",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(ts))),
        )
        .unwrap();
    document
        .insert(
            "tag",
            FieldValues::Single(FieldValue::Keyword(tag.to_owned())),
        )
        .unwrap();
    document
}

fn corpus_documents() -> Vec<Document> {
    CORPUS
        .iter()
        .map(|(key, title, n, ts, tag)| document(key, title, *n, *ts, tag))
        .collect()
}

fn term(field: &str, value: &str) -> Query {
    Query::Term {
        field: field.to_owned(),
        value: FieldValue::Text(value.to_owned()),
    }
}

fn n_range(lower: Bound<i64>, upper: Bound<i64>) -> Query {
    fn map(bound: Bound<i64>) -> Bound<FieldValue> {
        match bound {
            Bound::Unbounded => Bound::Unbounded,
            Bound::Included(value) => Bound::Included(FieldValue::I64(value)),
            Bound::Excluded(value) => Bound::Excluded(FieldValue::I64(value)),
        }
    }
    Query::Range {
        field: "n".to_owned(),
        lower: map(lower),
        upper: map(upper),
    }
}

/// Independently enumerated lexical `(query, expected-sorted-keys)` pairs.
fn lexical_queries() -> Vec<(Query, Vec<&'static str>)> {
    vec![
        (term("title", "alpha"), vec!["a", "c"]),
        (
            Query::Phrase {
                field: "title".to_owned(),
                terms: vec!["alpha".to_owned(), "beta".to_owned()],
            },
            vec!["a"],
        ),
        (
            Query::And(vec![term("title", "alpha"), term("title", "gamma")]),
            vec!["c"],
        ),
        (
            Query::Or(vec![term("title", "alpha"), term("title", "beta")]),
            vec!["a", "b", "c"],
        ),
        (Query::Not(Box::new(term("title", "alpha"))), vec!["b"]),
    ]
}

/// Independently enumerated typed `(query, expected-sorted-keys)` pairs.
fn typed_queries() -> Vec<(Query, Vec<&'static str>)> {
    vec![
        (
            n_range(Bound::Included(20), Bound::Included(30)),
            vec!["b", "c"],
        ),
        (n_range(Bound::Excluded(20), Bound::Included(30)), vec!["c"]),
        (
            Query::TimeRange {
                field: "ts".to_owned(),
                start: Timestamp::from_micros(2_000),
                end: Timestamp::from_micros(3_000),
            },
            // `TimeRange` is half-open `[start, end)`, so `c` at 3000 is excluded.
            vec!["b"],
        ),
        (
            Query::TimeRange {
                field: "ts".to_owned(),
                start: Timestamp::from_micros(1_000),
                end: Timestamp::from_micros(2_000),
            },
            vec!["a"],
        ),
    ]
}

fn lexical_keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let schema = schema();
    let registry = registry();
    let cancel = CancellationFlag::new();
    let mut keys: Vec<String> =
        LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
            .search(&query, TopK::new(100).unwrap(), &Budgets::new(), &cancel)
            .expect("lexical search")
            .hits
            .into_iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
    keys.sort();
    keys
}

fn typed_keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let schema = schema();
    let cancel = CancellationFlag::new();
    let request = TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(100).unwrap(),
        after: None,
        primary_time_field: None,
    };
    let mut keys: Vec<String> = TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel)
        .expect("typed search")
        .hits
        .into_iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

/// Assert every independently enumerated expectation against one snapshot.
fn check_expectations(snapshot: &ReaderSnapshot, label: &str) {
    for (query, expected) in lexical_queries() {
        let actual = lexical_keys(snapshot, query.clone());
        let expected: Vec<String> = expected.into_iter().map(str::to_owned).collect();
        assert_eq!(actual, expected, "[{label}] lexical {query:?}");
    }
    for (query, expected) in typed_queries() {
        let actual = typed_keys(snapshot, query.clone());
        let expected: Vec<String> = expected.into_iter().map(str::to_owned).collect();
        assert_eq!(actual, expected, "[{label}] typed {query:?}");
    }
}

fn fake_store() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn run_id() -> u128 {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    })
}

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!("oracle/{name}-{}-{}", std::process::id(), run_id()))
            .unwrap(),
        temp_workspace(name),
    )
    .with_transfer(
        RemoteTransferConfig::default()
            .with_range_threshold(64 * 1024)
            .with_chunk_size(16 * 1024)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(8),
    )
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

#[test]
fn o01_o02_o03_local_and_fake_match_independent_expectations() {
    // Local FsDirectory.
    let directory: Arc<dyn Directory> =
        Arc::new(FsDirectory::open(temp_dir("local")).expect("fs dir"));
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .unwrap();
    {
        let mut writer = index.writer().unwrap();
        for document in corpus_documents() {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
        check_expectations(&writer.reader(), "local");
    }

    // Fake remote cold reopen.
    let store = fake_store();
    let config = remote_config("fake");
    let workspace = config.workspace_root().to_path_buf();
    {
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        for document in corpus_documents() {
            writer.insert(document).unwrap();
        }
        block_on(writer.commit()).unwrap();
    }
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let reader = block_on(RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    check_expectations(&reader.snapshot(), "fake-cold");
    let _ = std::fs::remove_dir_all(&workspace);
}

#[test]
fn o07_pit_and_o08_mutations_and_o10_explicit_commit() {
    let store = fake_store();
    let config = remote_config("lifecycle");
    let workspace = config.workspace_root().to_path_buf();
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    {
        let mut writer = block_on(index.writer()).unwrap();
        for document in corpus_documents() {
            writer.insert(document).unwrap();
        }
        block_on(writer.commit()).unwrap();
    }

    // O10: an uncommitted mutation is not remotely visible.
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer
            .insert(document("d", "delta", 40, 4_000, "z"))
            .unwrap();
        // No commit: a fresh reader still sees generation 1 only.
    }
    let before = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(before.generation(), Some(1));

    // Commit generation 2 and pin generation 1.
    let reader_v1 = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let pit = reader_v1.pin().unwrap();
    {
        let mut writer = block_on(reader_v1.writer()).unwrap();
        writer
            .insert(document("d", "delta", 40, 4_000, "z"))
            .unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
            .unwrap();
        block_on(writer.commit()).unwrap();
    }

    // O07: the old PIT still observes generation 1 (a and c match alpha); the
    // new reader observes generation 2 where `a` was deleted.
    assert_eq!(
        lexical_keys(pit.snapshot(), term("title", "alpha")),
        vec!["a", "c"]
    );
    let reader_v2 = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(reader_v2.generation(), Some(2));
    assert_eq!(
        lexical_keys(&reader_v2.snapshot(), term("title", "alpha")),
        vec!["c"]
    );
    assert_eq!(
        lexical_keys(&reader_v2.snapshot(), term("title", "delta")),
        vec!["d"]
    );

    // O08: upsert + delete survive a cold reopen with no resurrection.
    std::fs::remove_dir_all(config.workspace_root()).unwrap();
    let recovered = block_on(RemoteIndex::open_existing(
        store,
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_eq!(
        lexical_keys(&recovered.snapshot(), term("title", "alpha")),
        vec!["c"]
    );
    assert_eq!(
        lexical_keys(&recovered.snapshot(), term("title", "delta")),
        vec!["d"]
    );
    let _ = std::fs::remove_dir_all(&workspace);
}

#[cfg(feature = "s3")]
mod real {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

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
        assert!(
            !endpoint.trim().is_empty(),
            "QUERVANT_RUSTFS_ENDPOINT must not be empty"
        );
        assert!(
            !bucket.trim().is_empty(),
            "QUERVANT_RUSTFS_BUCKET must not be empty"
        );
        assert!(
            !access.trim().is_empty(),
            "QUERVANT_RUSTFS_ACCESS_KEY must not be empty"
        );
        assert!(
            !secret.trim().is_empty(),
            "QUERVANT_RUSTFS_SECRET_KEY must not be empty"
        );
        assert!(
            endpoint.starts_with("http://"),
            "real RustFS acceptance requires an http:// endpoint"
        );
        (endpoint, bucket, access, secret, region)
    }

    fn run(body: impl std::future::Future<Output = ()> + Send + 'static) {
        let handle = std::thread::Builder::new()
            .stack_size(32 * 1024 * 1024)
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("runtime");
                runtime.block_on(body);
            })
            .expect("spawn");
        handle.join().expect("real oracle panicked");
    }

    async fn store(name: &str) -> (Arc<S3ObjectStore>, RemoteConfig) {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");
        (store, remote_config(&format!("real-{name}")))
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn o01_o02_o03_o09_o10_real_rustfs() {
        run(async {
            let (store, config) = store("equivalence").await;
            let workspace = config.workspace_root().to_path_buf();
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            {
                let mut writer = index.writer().await.unwrap();
                for document in corpus_documents() {
                    writer.insert(document).unwrap();
                }
                writer.commit().await.unwrap();
            }
            // Cold reopen from RustFS with an empty workspace.
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            check_expectations(&reader.snapshot(), "rustfs-cold");

            // O09: scoring performs zero remote GETs after hydration.
            let stats = reader.transfer_stats();
            let before = stats.requests();
            check_expectations(&reader.snapshot(), "rustfs-warm");
            assert_eq!(
                stats.requests(),
                before,
                "scoring must not perform remote GET"
            );

            // O10: an uncommitted mutation is not remotely visible.
            {
                let mut writer = reader.writer().await.unwrap();
                writer
                    .insert(document("d", "delta", 40, 4_000, "z"))
                    .unwrap();
            }
            let reopened = RemoteIndex::open_existing(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            assert_eq!(reopened.generation(), Some(1));
            let _ = std::fs::remove_dir_all(&workspace);
        });
    }
}
