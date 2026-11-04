//! PR 15G-B GB-R01 — real RustFS cold bootstrap with selective stored/key access.
//!
//! Ignored by default; the hosted pinned RustFS job must execute it.

#![cfg(feature = "s3")]

use std::sync::Arc;
use std::sync::OnceLock;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
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
        .insert(
            "tag",
            FieldValues::Single(FieldValue::Keyword(format!("t{n}"))),
        )
        .expect("tag");
    document
}

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
        "quervant-pr15g-b-r01-{}-{}",
        std::process::id(),
        run_id()
    ));
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "pr15g-b/gb-r01-{}-{}",
            std::process::id(),
            run_id()
        ))
        .expect("prefix"),
        workspace,
    )
}

fn require_env() -> (String, String, String, String, String) {
    let endpoint =
        std::env::var("QUERVANT_RUSTFS_ENDPOINT").expect("QUERVANT_RUSTFS_ENDPOINT must be set");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").expect("QUERVANT_RUSTFS_BUCKET");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").expect("QUERVANT_RUSTFS_ACCESS_KEY");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").expect("QUERVANT_RUSTFS_SECRET_KEY");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    assert!(!endpoint.trim().is_empty());
    assert!(!bucket.trim().is_empty());
    assert!(!access.trim().is_empty());
    assert!(!secret.trim().is_empty());
    assert!(endpoint.starts_with("http://"));
    (endpoint, bucket, access, secret, region)
}

fn run(body: impl std::future::Future<Output = ()> + Send + 'static) {
    let handle = std::thread::Builder::new()
        .name("pr15g-b-rustfs".to_owned())
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

fn request(query: Query, sort: Sort, top_k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = sort;
    request.projection =
        Projection::Fields(vec!["title".to_owned(), "n".to_owned(), "tag".to_owned()]);
    request
}

fn search(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn gb_r01_real_rustfs_cold_bootstrap_selected_access() {
    run(async {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("config"),
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
        .expect("create");
        {
            let mut writer = index.writer().await.expect("writer");
            for i in 0..20i64 {
                let title = if i == 0 { "rare" } else { "common" };
                writer
                    .insert(document(&format!("d{i:02}"), title, i))
                    .expect("insert");
            }
            assert_eq!(writer.commit().await.expect("commit").generation, 1);
        }
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

        let rare_request = request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("rare".into()),
            },
            Sort::default(),
            10,
        );
        let rare = search(&snapshot, &rare_request);
        assert_eq!(rare.total_hits, 1);
        assert_eq!(keys(&rare), vec!["d00"]);
        assert_eq!(
            rare.hits[0].fields,
            vec![
                (
                    "title".to_owned(),
                    FieldValues::Single(FieldValue::Text("rare".into()))
                ),
                ("n".to_owned(), FieldValues::Single(FieldValue::I64(0))),
                (
                    "tag".to_owned(),
                    FieldValues::Single(FieldValue::Keyword("t0".into()))
                ),
            ]
        );

        let sorted_request = request(
            Query::MatchAll,
            Sort::new(vec![SortField::new("n", SortDirection::Asc)]),
            20,
        );
        let sorted = search(&snapshot, &sorted_request);
        assert_eq!(sorted.total_hits, 20);
        assert_eq!(
            keys(&sorted),
            (0..20).map(|i| format!("d{i:02}")).collect::<Vec<_>>()
        );
        assert_eq!(
            sorted.hits[3].fields,
            vec![
                (
                    "title".to_owned(),
                    FieldValues::Single(FieldValue::Text("common".into()))
                ),
                ("n".to_owned(), FieldValues::Single(FieldValue::I64(3))),
                (
                    "tag".to_owned(),
                    FieldValues::Single(FieldValue::Keyword("t3".into()))
                ),
            ]
        );

        let before = reopened.transfer_stats().requests();
        let rare_again = search(&snapshot, &rare_request);
        let sorted_again = search(&snapshot, &sorted_request);
        assert_eq!(keys(&rare_again), vec!["d00"]);
        assert_eq!(keys(&sorted_again), keys(&sorted));
        assert_eq!(
            reopened.transfer_stats().requests(),
            before,
            "warm selective reread must not add provider GETs"
        );

        drop(snapshot);
        drop(reopened);
        let _ = std::fs::remove_dir_all(&workspace);
    });
}
