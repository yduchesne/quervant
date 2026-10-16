//! PR 13 review-fixup oracles: O04 (JSON), O05 (GeoPoint), O06 (GeoDistance).
//!
//! Expected hit sets and orderings are enumerated by hand from literal JSON
//! values and coordinates. They are checked against local `FsDirectory`,
//! `FakeObjectStore` cold reopen, and real RustFS cold reopen.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{GeoBoundingBox, GeoPolygon, GeoRadius, JsonPathExpr, Query};
use quervant_core::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint, JsonNumber, JsonValue};
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{SearchLimits, TypedSearchRequest, TypedSearcher};
use quervant_core::storage::{Directory, FsDirectory};
use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_dir(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!(
        "quervant-geo-oracle-{name}-{}-{n}",
        std::process::id()
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
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        None,
    )
    .unwrap()
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn point(lon: f64, lat: f64) -> GeoPoint {
    GeoPoint::new(lon, lat).expect("valid point")
}

fn obj(entries: &[(&str, JsonValue)]) -> JsonValue {
    JsonValue::Object(
        entries
            .iter()
            .map(|(key, value)| ((*key).to_owned(), value.clone()))
            .collect(),
    )
}

fn num(value: i64) -> JsonValue {
    JsonValue::Number(JsonNumber::I64(value))
}

fn arr(values: &[JsonValue]) -> JsonValue {
    JsonValue::Array(values.to_vec())
}

fn document(key: &str, body: Option<JsonValue>, loc: Option<GeoPoint>, n: i64) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(key.to_owned())),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(n)))
        .unwrap();
    if let Some(body) = body {
        document
            .insert("body", FieldValues::Single(FieldValue::Json(body)))
            .unwrap();
    }
    if let Some(loc) = loc {
        document
            .insert("loc", FieldValues::Single(FieldValue::GeoPoint(loc)))
            .unwrap();
    }
    document
}

fn corpus() -> Vec<Document> {
    vec![
        document(
            "origin",
            Some(obj(&[
                ("kind", JsonValue::String("a".into())),
                ("n", num(1)),
                ("flag", JsonValue::Bool(true)),
                ("nested", obj(&[("x", JsonValue::String("y".into()))])),
                ("arr", arr(&[num(1), num(2), num(3)])),
            ])),
            Some(point(0.0, 0.0)),
            1,
        ),
        document(
            "ne",
            Some(obj(&[
                ("kind", JsonValue::String("b".into())),
                ("n", num(2)),
                ("flag", JsonValue::Bool(false)),
            ])),
            Some(point(1.0, 1.0)),
            2,
        ),
        document(
            "east",
            Some(obj(&[
                ("kind", JsonValue::String("a".into())),
                ("n", num(3)),
            ])),
            Some(point(179.0, 0.0)),
            3,
        ),
        document(
            "west",
            Some(obj(&[
                ("kind", JsonValue::String("b".into())),
                ("n", num(4)),
            ])),
            Some(point(-179.0, 0.0)),
            4,
        ),
        document(
            "north",
            Some(obj(&[
                ("kind", JsonValue::String("a".into())),
                ("n", num(5)),
                ("nested", obj(&[("x", JsonValue::String("z".into()))])),
            ])),
            Some(point(0.0, 10.0)),
            5,
        ),
        document("nullkind", Some(obj(&[("kind", JsonValue::Null)])), None, 6),
        document("nobody", None, None, 7),
    ]
}

fn json_path(input: &str) -> JsonPathExpr {
    JsonPathExpr::parse(input).expect("valid path")
}

fn exists(field: &str, path: &str) -> Query {
    Query::JsonPathExists {
        field: field.to_owned(),
        path: json_path(path),
    }
}

fn equals(field: &str, path: &str, value: FieldValue) -> Query {
    Query::JsonPathEquals {
        field: field.to_owned(),
        path: json_path(path),
        value,
    }
}

fn text(value: &str) -> FieldValue {
    FieldValue::Text(value.to_owned())
}

fn bbox(field: &str, west: f64, south: f64, east: f64, north: f64) -> Query {
    Query::GeoBoundingBox {
        field: field.to_owned(),
        bbox: GeoBoundingBox::new(west, south, east, north).unwrap(),
    }
}

fn radius(field: &str, lon: f64, lat: f64, meters: f64) -> Query {
    Query::GeoRadius {
        field: field.to_owned(),
        radius: GeoRadius::new(point(lon, lat), meters).unwrap(),
    }
}

fn n_range(lower: i64, upper: i64) -> Query {
    Query::Range {
        field: "n".to_owned(),
        lower: quervant_core::contract::query::Bound::Included(FieldValue::I64(lower)),
        upper: quervant_core::contract::query::Bound::Included(FieldValue::I64(upper)),
    }
}

fn keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
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

fn sorted(mut values: Vec<String>) -> Vec<String> {
    values.sort();
    values
}

fn search_sorted(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    sorted(keys(snapshot, query))
}

/// Assert a typed search fails (invalid path/unsupported operator).
fn search_fails(snapshot: &ReaderSnapshot, query: Query) {
    let schema = schema();
    let cancel = CancellationFlag::new();
    let request = TypedSearchRequest {
        query,
        sort: Sort::default(),
        top_k: TopK::new(10).unwrap(),
        after: None,
        primary_time_field: None,
    };
    let result = TypedSearcher::new(snapshot, &schema, SearchLimits::default()).search(
        &request,
        &Budgets::new(),
        &cancel,
    );
    assert!(result.is_err(), "expected a typed failure");
}

fn check_json(snapshot: &ReaderSnapshot, label: &str) {
    let cases: Vec<(Query, Vec<&str>)> = vec![
        (
            exists("body", "$.kind"),
            vec!["east", "ne", "north", "nullkind", "origin", "west"],
        ),
        (exists("body", "$.nested.x"), vec!["north", "origin"]),
        (exists("body", "$.arr[*]"), vec!["origin"]),
        (
            equals("body", "$.kind", text("a")),
            vec!["east", "north", "origin"],
        ),
        (equals("body", "$.n", FieldValue::I64(2)), vec!["ne"]),
        (
            equals("body", "$.flag", FieldValue::Bool(true)),
            vec!["origin"],
        ),
        // Type-sensitive mismatch: `$.kind` is a string, `$.n` an integer.
        (equals("body", "$.kind", FieldValue::I64(1)), vec![]),
        (equals("body", "$.n", text("2")), vec![]),
        // JSON null never equals a scalar.
        (equals("body", "$.kind", text("null")), vec![]),
    ];
    for (query, expected) in cases {
        assert_eq!(
            search_sorted(snapshot, query.clone()),
            expected,
            "[{label}] {query:?}"
        );
    }

    // O04D: unsupported wildcard equality and invalid path are typed failures.
    search_fails(snapshot, equals("body", "$.arr[*]", FieldValue::I64(1)));
    assert!(JsonPathExpr::parse("body.kind").is_err());
    assert!(JsonPathExpr::parse("$.arr[*]").is_ok());
}

fn check_geo(snapshot: &ReaderSnapshot, label: &str) {
    let cases: Vec<(Query, Vec<&str>)> = vec![
        (bbox("loc", -0.5, -0.5, 1.5, 1.5), vec!["ne", "origin"]),
        // Inclusive exact edges: (0,0) and (1,1) both lie on the box.
        (bbox("loc", 0.0, 0.0, 1.0, 1.0), vec!["ne", "origin"]),
        // Antimeridian crossing: west > east wraps through +/-180.
        (bbox("loc", 170.0, -1.0, -170.0, 1.0), vec!["east", "west"]),
        (radius("loc", 0.0, 0.0, 100_000.0), vec!["origin"]),
        (radius("loc", 0.0, 0.0, 1_000_000.0), vec!["ne", "origin"]),
        (
            radius("loc", 0.0, 0.0, 1_200_000.0),
            vec!["ne", "north", "origin"],
        ),
    ];
    for (query, expected) in cases {
        assert_eq!(
            search_sorted(snapshot, query.clone()),
            expected,
            "[{label}] {query:?}"
        );
    }

    // O05D: planar polygon with a hole excludes `ne` (inside the hole).
    let polygon = Query::GeoPolygon {
        field: "loc".to_owned(),
        polygon: GeoPolygon::new(
            vec![
                point(-1.0, -1.0),
                point(2.0, -1.0),
                point(2.0, 2.0),
                point(-1.0, 2.0),
            ],
            vec![vec![
                point(0.5, 0.5),
                point(1.5, 0.5),
                point(1.5, 1.5),
                point(0.5, 1.5),
            ]],
        )
        .unwrap(),
    };
    assert_eq!(
        search_sorted(snapshot, polygon.clone()),
        vec!["origin"],
        "[{label}] polygon hole"
    );

    // O05E: Boolean composition with a typed range.
    let composed = Query::And(vec![bbox("loc", -0.5, -0.5, 0.5, 0.5), n_range(1, 1)]);
    assert_eq!(search_sorted(snapshot, composed), vec!["origin"]);
    let union = Query::Or(vec![
        bbox("loc", 170.0, -1.0, -170.0, 1.0),
        bbox("loc", 0.0, 9.0, 1.0, 11.0),
    ]);
    assert_eq!(
        search_sorted(snapshot, union),
        vec!["east", "north", "west"]
    );
    // NOT geo includes documents with no `loc`.
    assert_eq!(
        search_sorted(
            snapshot,
            Query::Not(Box::new(bbox("loc", -0.5, -0.5, 1.5, 1.5)))
        ),
        vec!["east", "nobody", "north", "nullkind", "west"]
    );

    // O05F: invalid polygon rings are typed validation errors.
    assert!(GeoPolygon::new(vec![point(0.0, 0.0), point(1.0, 1.0)], vec![]).is_err());
    assert!(GeoRadius::new(point(0.0, 0.0), 0.0).is_err());
    assert!(GeoBoundingBox::new(0.0, 0.0, 0.0, 0.0).is_ok());
}

fn distance_sort(direction: SortDirection) -> Sort {
    Sort::new(vec![SortField {
        field: "loc".to_owned(),
        direction,
        missing: MissingValuePosition::Last,
        multi: None,
        distance_from: Some(point(0.0, 0.0)),
    }])
}

fn ordered_keys(snapshot: &ReaderSnapshot, sort: Sort, top_k: usize) -> Vec<String> {
    let schema = schema();
    let cancel = CancellationFlag::new();
    let request = TypedSearchRequest {
        query: Query::MatchAll,
        sort,
        top_k: TopK::new(top_k).unwrap(),
        after: None,
        primary_time_field: None,
    };
    TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel)
        .expect("typed search")
        .hits
        .into_iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn check_geo_sort(snapshot: &ReaderSnapshot, label: &str) {
    // Ascending distance: origin (0), ne (~157 km), north (~1112 km), then the
    // equal-distance east/west pair key-broken, then missing-loc docs.
    let ascending = ordered_keys(snapshot, distance_sort(SortDirection::Asc), 100);
    assert_eq!(
        ascending,
        vec![
            "origin", "ne", "north", "east", "west", "nobody", "nullkind"
        ],
        "[{label}] ascending GeoDistance"
    );

    // Descending: farthest first; the equal-distance pair remains key-broken;
    // missing-loc documents stay last.
    let descending = ordered_keys(snapshot, distance_sort(SortDirection::Desc), 100);
    assert_eq!(
        descending,
        vec![
            "east", "west", "north", "ne", "origin", "nobody", "nullkind"
        ],
        "[{label}] descending GeoDistance"
    );

    // O06C: search-after pagination yields every key exactly once.
    let schema = schema();
    let cancel = CancellationFlag::new();
    let mut request = TypedSearchRequest {
        query: Query::MatchAll,
        sort: distance_sort(SortDirection::Asc),
        top_k: TopK::new(3).unwrap(),
        after: None,
        primary_time_field: None,
    };
    let searcher = TypedSearcher::new(snapshot, &schema, SearchLimits::default());
    let mut seen: Vec<String> = Vec::new();
    loop {
        let response = searcher
            .search(&request, &Budgets::new(), &cancel)
            .expect("paged search");
        for hit in &response.hits {
            seen.push(hit.key.as_str().to_owned());
        }
        match response.next_cursor {
            Some(cursor) => request.after = Some(cursor),
            None => break,
        }
    }
    assert_eq!(
        seen,
        vec![
            "origin", "ne", "north", "east", "west", "nobody", "nullkind"
        ],
        "[{label}] search-after pages"
    );
}

fn check_all(snapshot: &ReaderSnapshot, label: &str) {
    check_json(snapshot, label);
    check_geo(snapshot, label);
    check_geo_sort(snapshot, label);
}

fn fake_store() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "geooracle/{name}-{}-{}",
            std::process::id(),
            run_id()
        ))
        .unwrap(),
        temp_dir(name),
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
fn o04_o05_o06_local_and_fake() {
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
        for document in corpus() {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
        check_all(&writer.reader(), "local");
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
        for document in corpus() {
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
    check_all(&reader.snapshot(), "fake-cold");
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
        handle.join().expect("geo oracle panicked");
    }

    #[test]
    #[ignore = "requires a running pinned RustFS instance"]
    fn o04_o05_o06_real_rustfs() {
        run(async {
            let (endpoint, bucket, access, secret, region) = require_env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .expect("config"),
            );
            store.create_bucket_if_absent().await.expect("bucket");
            let config = remote_config("real");
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
                for document in corpus() {
                    writer.insert(document).unwrap();
                }
                writer.commit().await.unwrap();
            }
            std::fs::remove_dir_all(config.workspace_root()).unwrap();
            let reader = RemoteIndex::open_existing(
                store,
                config,
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .unwrap();
            check_all(&reader.snapshot(), "rustfs-cold");
            let _ = std::fs::remove_dir_all(&workspace);
        });
    }
}
