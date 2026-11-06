//! PR 15G-D GD-R01 — real RustFS cold bootstrap for exact-term miss/membership specializations.

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
        "quervant-pr15g-d-r01-{}-{}",
        std::process::id(),
        run_id()
    ));
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "pr15g-d/gd-r01-{}-{}",
            std::process::id(),
            run_id()
        ))
        .expect("prefix"),
        workspace,
    )
}

fn require_env() -> (String, String, String, String, String) {
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT").expect("ENDPOINT");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET").expect("BUCKET");
    let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").expect("ACCESS_KEY");
    let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY").expect("SECRET_KEY");
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
        .name("pr15g-d-rustfs".to_owned())
        .stack_size(32 * 1024 * 1024)
        .spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("runtime");
            runtime.block_on(body);
        })
        .expect("spawn");
    handle.join().expect("real RustFS test panicked");
}

fn request(query: Query, top_k: usize) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["title".to_owned(), "n".to_owned()]);
    request
}

fn search(
    snapshot: &quervant_core::index::ReaderSnapshot,
    request: &UnifiedRequest,
) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("search")
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
fn gd_r01_real_rustfs_cold_bootstrap_miss_and_present() {
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
            for n in 0..1024i64 {
                let title = match n {
                    0..=999 => "common",
                    1000 => "rare",
                    _ => "other",
                };
                writer
                    .insert(document(&format!("k{n:05}"), title, n))
                    .expect("insert");
            }
            assert_eq!(writer.commit().await.expect("commit").generation, 1);
        }
        std::fs::remove_dir_all(&workspace).expect("remove workspace");
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

        let absent = request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("absent-term".into()),
            },
            100,
        );
        let absent_response = search(&snapshot, &absent);
        assert_eq!(absent_response.total_hits, 0);
        assert!(absent_response.hits.is_empty());

        let common = request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("common".into()),
            },
            100,
        );
        let response = search(&snapshot, &common);
        assert_eq!(response.total_hits, 1000);
        assert_eq!(response.hits.len(), 100);
        assert_eq!(keys(&response)[0], "k00000");
        assert!(response.hits.iter().all(|hit| hit.score.is_some()));
        assert_eq!(
            response.hits[0].fields,
            vec![
                (
                    "title".to_owned(),
                    FieldValues::Single(FieldValue::Text("common".into()))
                ),
                ("n".to_owned(), FieldValues::Single(FieldValue::I64(0))),
            ]
        );

        let common_k10 = request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("common".into()),
            },
            10,
        );
        assert_eq!(search(&snapshot, &common_k10).hits.len(), 10);
        let rare = request(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("rare".into()),
            },
            100,
        );
        assert_eq!(search(&snapshot, &rare).total_hits, 1);

        let before = reopened.transfer_stats().requests();
        assert_eq!(search(&snapshot, &absent).total_hits, 0);
        assert_eq!(keys(&search(&snapshot, &common)), keys(&response));
        assert_eq!(search(&snapshot, &rare).total_hits, 1);
        assert_eq!(
            reopened.transfer_stats().requests(),
            before,
            "warm D search must not add provider GETs"
        );

        drop(snapshot);
        drop(reopened);
        let _ = std::fs::remove_dir_all(&workspace);
    });
}
