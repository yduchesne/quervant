//! PERF-06-B1 — B1-R01 real RustFS cold bootstrap and snapshot-scoped ordinals.
//!
//! Ignored by default; the hosted pinned RustFS job must execute it.

#![cfg(feature = "s3")]

mod perf06_b1_common;

use std::sync::Arc;
use std::sync::OnceLock;

use perf06_b1_common as corpus;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
use quervant_core::index::{
    GuardedSegmentReader, IndexLimits, ReaderSnapshot, SnapshotKeywordOrdinals,
};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_objectstore::{S3Config, S3ObjectStore};

fn run_id() -> u128 {
    static RUN: OnceLock<u128> = OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn remote_config(tag: &str) -> RemoteConfig {
    let workspace = std::env::temp_dir().join(format!(
        "quervant-perf06-b1-r01-{tag}-{}-{}",
        std::process::id(),
        run_id()
    ));
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!(
            "perf06-b1/r01-{}-{}-{tag}",
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
        .name("perf06-b1-rustfs".to_owned())
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

fn acquire_guards(snapshot: &ReaderSnapshot) -> Vec<GuardedSegmentReader> {
    (0..snapshot.segment_count())
        .map(|index| snapshot.open_segment_reader(index).expect("guard"))
        .collect()
}

fn city_rank(
    guards: &[GuardedSegmentReader],
    map: &SnapshotKeywordOrdinals,
    key: &str,
) -> Option<u64> {
    for guard in guards {
        let reader = guard.reader();
        let keys = reader.doc_keys().expect("keys");
        let Some(doc_id) = keys
            .iter()
            .position(|candidate| candidate.as_str() == key)
            .map(|index| index as u64)
        else {
            continue;
        };
        let columns = reader.open_columns().expect("columns").expect("section");
        let handle = columns
            .bind_keyword_ordinals(corpus::CITY)
            .expect("bind")
            .expect("ordinal");
        return match handle.doc_ordinal(doc_id).expect("row") {
            quervant_core::segment::column::KeywordOrdinalValue::Value { ordinal, .. } => Some(
                map.bind_segment(guard)
                    .expect("segment")
                    .translate(ordinal)
                    .expect("translate"),
            ),
            _ => None,
        };
    }
    None
}

fn sorted_keys(snapshot: &ReaderSnapshot, direction: SortDirection) -> Vec<String> {
    let mut field = SortField::new("city", direction);
    field.missing = MissingValuePosition::Last;
    let mut request = UnifiedRequest::new(
        quervant_core::contract::query::Query::MatchAll,
        TopK::new(100).expect("top-k"),
    );
    request.sort = Sort::new(vec![field]);
    request.projection = corpus::projection();
    let response = UnifiedSearcher::new(
        snapshot,
        &corpus::schema(),
        &corpus::registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &CancellationFlag::new())
    .expect("search");
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

#[test]
#[ignore = "requires a running pinned RustFS instance"]
fn b1_r01_cold_shared_ordinals_and_pit() {
    run(async {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");
        let config = remote_config("main");
        let workspace = config.workspace_root().to_path_buf();
        let cold_workspace = std::env::temp_dir().join(format!(
            "quervant-perf06-b1-r01-cold-{}-{}",
            std::process::id(),
            run_id()
        ));
        let cold_config = RemoteConfig::new(config.prefix().clone(), cold_workspace.clone());
        let third_workspace = std::env::temp_dir().join(format!(
            "quervant-perf06-b1-r01-third-{}-{}",
            std::process::id(),
            run_id()
        ));
        let third_config = RemoteConfig::new(config.prefix().clone(), third_workspace.clone());

        // ---- generation 3: three remote commits ----
        {
            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                corpus::schema(),
                corpus::registry(),
                IndexLimits::default(),
            )
            .await
            .expect("create");
            for batch in 0..3usize {
                let mut writer = index.writer().await.expect("writer");
                for position in batch * 6..(batch + 1) * 6 {
                    let (_, _, city) = corpus::ROWS[position];
                    writer
                        .insert(corpus::document_at(position, city))
                        .expect("insert");
                }
                assert_eq!(
                    writer.commit().await.expect("commit").generation,
                    (batch + 1) as u64
                );
            }
        }
        let _ = std::fs::remove_dir_all(&workspace);

        // ---- cold bootstrap in a brand-new empty workspace ----
        let reopened = RemoteIndex::open_existing(
            Arc::clone(&store),
            cold_config.clone(),
            corpus::schema(),
            corpus::registry(),
            IndexLimits::default(),
        )
        .await
        .expect("cold reopen");
        assert_eq!(reopened.generation(), Some(3));

        // Pin first: a prepared map belongs to one exact snapshot instance, so
        // every later check on the held view must use this same `Arc`.
        let pit = reopened.pin().expect("pin");
        let held_snapshot = Arc::clone(pit.snapshot());
        assert_eq!(held_snapshot.generation(), Some(3));

        // All non-`Send` reader state is scoped to this synchronous block.
        let (map, requests_after_warm) = {
            let snapshot = Arc::clone(&held_snapshot);
            assert_eq!(snapshot.document_count(), 18);
            assert_eq!(snapshot.segment_count(), 3);
            let guards = acquire_guards(&snapshot);
            let preparation = snapshot
                .prepare_keyword_ordinals(corpus::CITY, &guards, &CancellationFlag::new())
                .expect("prepare");
            let map = match &preparation {
                quervant_core::index::KeywordOrdinalPreparation::Ready(map) => Arc::clone(map),
                other => panic!("cold bootstrap must prepare a map, got {other:?}"),
            };
            assert_eq!(map.term_count(), 12);
            assert_eq!(city_rank(&guards, &map, "a2"), Some(0));
            assert_eq!(city_rank(&guards, &map, "a3"), Some(2));
            assert_eq!(city_rank(&guards, &map, "b4"), Some(1));
            assert_eq!(city_rank(&guards, &map, "a5"), Some(10));
            assert_eq!(city_rank(&guards, &map, "a0"), None);
            assert_eq!(city_rank(&guards, &map, "a1"), None);

            let mut expected_asc: Vec<String> = corpus::CITY_ASC
                .iter()
                .map(|key| (*key).to_owned())
                .collect();
            expected_asc.extend(["a1", "c5", "a0", "c4"].iter().map(|key| (*key).to_owned()));
            assert_eq!(sorted_keys(&snapshot, SortDirection::Asc), expected_asc);
            let mut expected_desc: Vec<String> = corpus::CITY_DESC
                .iter()
                .map(|key| (*key).to_owned())
                .collect();
            expected_desc.extend(["a1", "c5", "a0", "c4"].iter().map(|key| (*key).to_owned()));
            assert_eq!(sorted_keys(&snapshot, SortDirection::Desc), expected_desc);

            // Warm reuse must not add provider GETs.
            let before = reopened.transfer_stats().requests();
            let reuse = snapshot
                .prepare_keyword_ordinals(corpus::CITY, &guards, &CancellationFlag::new())
                .expect("prepare");
            assert!(matches!(
                reuse,
                quervant_core::index::KeywordOrdinalPreparation::Ready(ref again)
                    if Arc::ptr_eq(again, &map)
            ));
            let _ = sorted_keys(&snapshot, SortDirection::Asc);
            let _ = sorted_keys(&snapshot, SortDirection::Desc);
            (map, (before, reopened.transfer_stats().requests()))
        };
        assert_eq!(
            requests_after_warm.0, requests_after_warm.1,
            "warm reuse must not add provider requests"
        );

        // ---- append a fourth remote segment while the generation-3 view is held ----
        let held_chicago_before = {
            let held_guards = acquire_guards(&held_snapshot);
            city_rank(&held_guards, &map, "d0")
        };
        assert_eq!(held_chicago_before, None);
        {
            let mut writer = reopened.writer().await.expect("writer");
            writer
                .insert(corpus::document_with(
                    "d0",
                    corpus::Batch::A,
                    corpus::City::Value("Chicago"),
                    18,
                ))
                .expect("insert");
            assert_eq!(writer.commit().await.expect("commit").generation, 4);
        }

        // ---- cold reopen generation 4 in another empty workspace ----
        let third = RemoteIndex::open_existing(
            Arc::clone(&store),
            third_config,
            corpus::schema(),
            corpus::registry(),
            IndexLimits::default(),
        )
        .await
        .expect("cold reopen generation 4");
        assert_eq!(third.generation(), Some(4));
        {
            let snapshot = third.snapshot();
            assert_eq!(snapshot.document_count(), 19);
            assert_eq!(snapshot.segment_count(), 4);
            let guards = acquire_guards(&snapshot);
            let preparation = snapshot
                .prepare_keyword_ordinals(corpus::CITY, &guards, &CancellationFlag::new())
                .expect("prepare");
            let third_map = match &preparation {
                quervant_core::index::KeywordOrdinalPreparation::Ready(map) => Arc::clone(map),
                other => panic!("generation 4 must prepare a map, got {other:?}"),
            };
            assert_eq!(third_map.term_count(), 13);
            assert_eq!(city_rank(&guards, &third_map, "d0"), Some(4));
            assert_eq!(city_rank(&guards, &third_map, "a4"), Some(6));
            let mut third_asc: Vec<String> = corpus::CITY_ASC
                .iter()
                .map(|key| (*key).to_owned())
                .collect();
            // `d0` (Chicago) sorts between Boston and Dallas.
            third_asc.insert(5, "d0".to_owned());
            third_asc.extend(["a1", "c5", "a0", "c4"].iter().map(|key| (*key).to_owned()));
            assert_eq!(sorted_keys(&snapshot, SortDirection::Asc), third_asc);

            // The held generation-3 view is unchanged and never sees `d0`.
            let held_guards = acquire_guards(&held_snapshot);
            assert_eq!(city_rank(&held_guards, &map, "d0"), None);
            assert_eq!(city_rank(&held_guards, &map, "a4"), Some(5));
            assert_eq!(held_snapshot.generation(), Some(3));
        }

        drop(held_snapshot);
        drop(pit);
        drop(reopened);
        drop(third);
        let _ = std::fs::remove_dir_all(&workspace);
        let _ = std::fs::remove_dir_all(&cold_workspace);
        let _ = std::fs::remove_dir_all(&third_workspace);
        println!("PERF06_B1_R01_PASS");
    });
}
