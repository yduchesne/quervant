//! PR 15G-A GA-I07 — real RustFS cold bootstrap, typed range, explicit column
//! sort and warm reread.
//!
//! This test is ignored by default and requires the pinned RustFS service and
//! the documented environment. Compilation is not execution and the hosted
//! `rustfs` job must run it before GA-I07 can be called PASS.
//!
//! ```sh
//! QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
//! QUERVANT_RUSTFS_BUCKET=quervant-pr15g-a \
//! QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
//! QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
//! cargo test -p quervant-core --all-features --test pr15g_a_rustfs \
//!   -- --ignored --test-threads=1
//! ```

#![cfg(feature = "s3")]

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::OnceLock;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{Bound, Query};
use quervant_core::contract::result::{Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::IndexLimits;
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_objectstore::{S3Config, S3ObjectStore};

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
    .expect("schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
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

/// A per-process run identifier so repeated runs against a persistent RustFS
/// instance never reuse a prefix.
fn run_id() -> u128 {
    static RUN: OnceLock<u128> = OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn remote_config() -> RemoteConfig {
    let workspace = std::env::temp_dir().join(format!(
        "quervant-pr15g-a-i07-{}-{}",
        std::process::id(),
        run_id()
    ));
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "pr15g-a/ga-i07-{}-{}",
            std::process::id(),
            run_id()
        ))
        .expect("prefix"),
        workspace,
    )
}

fn require_env() -> (String, String, String, String, String) {
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
        .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
        .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
        .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
        .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
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

/// Run the real RustFS async body on a dedicated large-stack thread with a
/// current-thread Tokio runtime, matching the existing PR 13 acceptance tests.
fn run(body: impl std::future::Future<Output = ()> + Send + 'static) {
    let handle = std::thread::Builder::new()
        .name("pr15g-a-rustfs".to_owned())
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

fn sorted_request() -> UnifiedRequest {
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(3).expect("top-k"));
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request
}

fn range_request() -> UnifiedRequest {
    let mut request = UnifiedRequest::new(
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(15)),
            upper: Bound::Included(FieldValue::I64(30)),
        },
        TopK::new(3).expect("top-k"),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request
}

fn search_on(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn ordered_keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn read_columns(snapshot: &quervant_core::index::ReaderSnapshot) -> BTreeMap<String, i64> {
    let mut values = BTreeMap::new();
    for index in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(index).expect("guarded reader");
        let field = guard.reader().schema().field_id("n").expect("n field");
        let doc_count = guard.reader().doc_count();
        for doc_id in 0..doc_count {
            let Some(FieldValues::Single(FieldValue::I64(value))) = guard
                .reader()
                .column_value(field, doc_id)
                .expect("column value")
            else {
                panic!("fixture n value must be a single I64");
            };
            let key = guard
                .reader()
                .doc_key(doc_id)
                .expect("doc key")
                .as_str()
                .to_owned();
            values.insert(key, value);
        }
    }
    values
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn ga_i07_real_rustfs_cold_bootstrap_typed_sort_and_warm_reread() {
    run(async {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("valid config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");
        let config = remote_config();
        let workspace = config.workspace_root().to_path_buf();

        let index = RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("create remote index");
        {
            let mut writer = index.writer().await.expect("writer");
            writer.insert(document("a", "alpha", 30)).expect("a");
            writer.insert(document("b", "beta", 10)).expect("b");
            writer.insert(document("c", "alpha", 20)).expect("c");
            let outcome = writer.commit().await.expect("commit");
            assert_eq!(outcome.generation, 1);
        }

        // Genuine cold bootstrap: remove every disposable local byte, reopen
        // from the authoritative remote pointer.
        std::fs::remove_dir_all(&workspace).expect("remove disposable workspace");
        let reopened = RemoteIndex::open_existing(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("cold reopen");
        assert_eq!(reopened.generation(), Some(1));
        let snapshot = reopened.snapshot();
        assert!(snapshot.generation().is_some());

        let sorted = search_on(&snapshot, &sorted_request());
        assert_eq!(sorted.total_hits, 3);
        assert_eq!(ordered_keys(&sorted), vec!["b", "c", "a"]);
        let range = search_on(&snapshot, &range_request());
        assert_eq!(range.total_hits, 2);
        assert_eq!(ordered_keys(&range), vec!["c", "a"]);

        let columns = read_columns(&snapshot);
        assert_eq!(
            columns,
            BTreeMap::from([
                ("a".to_owned(), 30),
                ("b".to_owned(), 10),
                ("c".to_owned(), 20),
            ])
        );

        // Warm reread on the same snapshot must not perform new provider GETs.
        let before = reopened.transfer_stats().requests();
        let sorted_again = search_on(&snapshot, &sorted_request());
        let range_again = search_on(&snapshot, &range_request());
        assert_eq!(ordered_keys(&sorted_again), vec!["b", "c", "a"]);
        assert_eq!(ordered_keys(&range_again), vec!["c", "a"]);
        assert_eq!(read_columns(&snapshot), columns);
        assert_eq!(
            reopened.transfer_stats().requests(),
            before,
            "warm reread must not perform new provider requests"
        );

        drop(snapshot);
        drop(reopened);
        let _ = std::fs::remove_dir_all(&workspace);
    });
}
