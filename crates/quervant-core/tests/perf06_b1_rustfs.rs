//! PERF-06-B1 — B1-R01 real RustFS cold bootstrap, immutable-object and PIT proof.
//!
//! Ignored by default; the hosted pinned RustFS job must execute it.

#![cfg(feature = "s3")]

mod perf06_b1_common;

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::OnceLock;

use perf06_b1_common as corpus;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, ExactDistinct, GroupBy,
    GroupKey, NumericAggregate,
};
use quervant_core::contract::batch::{BatchQueryRequest, PerQueryOutcome, QueryRequest};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{
    GuardedSegmentReader, IndexLimits, KeywordOrdinalPreparation, ReaderSnapshot,
    SnapshotKeywordOrdinals,
};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch};
use quervant_core::segment::column::{KeywordOrdinalState, KeywordOrdinalValue};
use quervant_core::segment::{Manifest, SectionKind, SegmentLimits, parse_container};
use quervant_objectstore::{ContentDigest, ObjectStore, S3Config, S3ObjectStore, TransferLimits};

fn run_id() -> u128 {
    static RUN: OnceLock<u128> = OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

fn workspace(tag: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "quervant-perf06-b1-r01-{tag}-{}-{}",
        std::process::id(),
        run_id()
    ))
}

fn prefix() -> RemoteKeyPrefix {
    RemoteKeyPrefix::parse(format!("perf06-b1/r01-{}-{}", std::process::id(), run_id()))
        .expect("prefix")
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

fn prepare(
    snapshot: &ReaderSnapshot,
    guards: &[GuardedSegmentReader],
) -> KeywordOrdinalPreparation {
    snapshot
        .prepare_keyword_ordinals(corpus::CITY, guards, &CancellationFlag::new())
        .expect("prepare")
}

/// One appended `type-d` row (never part of the frozen first 18).
const APPENDED_KEY: &str = "d0";
const APPENDED_CITY: &str = "Chicago";
const APPENDED_N: i64 = 18;

fn appended_document() -> Document {
    let mut doc = Document::new(DocumentKey::new(APPENDED_KEY).expect("key"));
    doc.insert(
        "body",
        FieldValues::Single(FieldValue::Text("common".to_owned())),
    )
    .expect("body");
    doc.insert(
        "category",
        FieldValues::Single(FieldValue::Keyword("type-d".to_owned())),
    )
    .expect("category");
    doc.insert(
        "city",
        FieldValues::Single(FieldValue::Keyword(APPENDED_CITY.to_owned())),
    )
    .expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(APPENDED_N)))
        .expect("n");
    doc.insert(
        "stored_tag",
        FieldValues::Single(FieldValue::Keyword("stored".to_owned())),
    )
    .expect("stored_tag");
    doc.insert(
        "tags",
        FieldValues::Multi(vec![
            FieldValue::Keyword("one".to_owned()),
            FieldValue::Keyword("two".to_owned()),
        ]),
    )
    .expect("tags");
    doc
}

/// Frozen 18-row raw-term order.
const TERMS_18: [&str; 12] = [
    "", "\0", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀",
];

/// Frozen 18-row term order plus the appended Chicago term.
const TERMS_19: [&str; 13] = [
    "", "\0", "Austin", "Boston", "Chicago", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é",
    "😀",
];

/// Independent row set: frozen 18 plus the appended row.
fn rows(appended: bool) -> Vec<(String, Option<&'static str>)> {
    let mut rows: Vec<(String, Option<&'static str>)> = corpus::ROWS
        .iter()
        .map(|(key, _, city)| {
            let term = match city {
                corpus::City::Value(value) => Some(*value),
                _ => None,
            };
            let missing = matches!(city, corpus::City::Missing);
            let _ = missing;
            ((*key).to_owned(), term)
        })
        .collect();
    if appended {
        rows.push((APPENDED_KEY.to_owned(), Some(APPENDED_CITY)));
    }
    rows
}

/// Independent expected ordering: value rows by raw bytes (ties by key), then
/// null and missing rows in the requested placement.
fn expected_order(
    rows: &[(String, Option<&'static str>)],
    direction: SortDirection,
    missing: MissingValuePosition,
) -> Vec<String> {
    let mut values: Vec<(Vec<u8>, String)> = rows
        .iter()
        .filter_map(|(key, term)| term.map(|term| (term.as_bytes().to_vec(), key.clone())))
        .collect();
    values.sort_by(|left, right| {
        let order = match direction {
            SortDirection::Asc => left.0.cmp(&right.0),
            SortDirection::Desc => right.0.cmp(&left.0),
        };
        order.then_with(|| left.1.cmp(&right.1))
    });
    let mut missing_rows = vec!["a0".to_owned(), "c4".to_owned()];
    let mut null_rows = vec!["a1".to_owned(), "c5".to_owned()];
    missing_rows.sort();
    null_rows.sort();
    let mut order = Vec::new();
    if missing == MissingValuePosition::First {
        order.extend(missing_rows.iter().cloned());
        order.extend(null_rows.iter().cloned());
    }
    order.extend(values.into_iter().map(|(_, key)| key));
    if missing == MissingValuePosition::Last {
        order.extend(null_rows);
        order.extend(missing_rows);
    }
    order
}

fn sorted_keys(
    snapshot: &ReaderSnapshot,
    direction: SortDirection,
    missing: MissingValuePosition,
    limit: usize,
) -> (Vec<String>, u64) {
    let mut field = SortField::new("city", direction);
    field.missing = missing;
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(limit).expect("top-k"));
    request.sort = Sort::new(vec![field]);
    request.projection = corpus::projection();
    let response = UnifiedSearcher::new(
        snapshot,
        &corpus::schema(),
        &corpus::registry(),
        SearchLimits::default(),
    )
    .search(
        &request,
        &quervant_core::contract::budget::Budgets::new(),
        &CancellationFlag::new(),
    )
    .expect("search");
    // Every returned hit must carry the full six-field projected values from the
    // literal corpus oracle, not merely a field count.
    for hit in &response.hits {
        assert_eq!(
            hit.fields,
            corpus::expected_projected_fields(hit.key.as_str()),
            "full projection mismatch for {}",
            hit.key.as_str()
        );
    }
    (
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect(),
        response.total_hits,
    )
}

fn assert_full_view(
    snapshot: &ReaderSnapshot,
    appended: bool,
    expected_terms: &[&str],
) -> Arc<SnapshotKeywordOrdinals> {
    let rows = rows(appended);
    let guards = acquire_guards(snapshot);
    let preparation = prepare(snapshot, &guards);
    let map = match &preparation {
        KeywordOrdinalPreparation::Ready(map) => Arc::clone(map),
        other => panic!("expected a ready map, got {other:?}"),
    };
    assert_eq!(map.term_count(), expected_terms.len() as u64);
    let segments = corpus::segment_ordinals(snapshot, &guards, &map);
    let terms: Vec<Vec<u8>> = segments
        .iter()
        .flat_map(|segment| segment.terms.iter().cloned())
        .collect();
    for term in expected_terms {
        assert!(
            terms
                .iter()
                .any(|candidate| candidate.as_slice() == term.as_bytes()),
            "missing expected term {term:?}"
        );
    }

    // Every document's value and shared rank against the frozen table.
    for guard in &guards {
        let reader = guard.reader();
        let columns = reader.open_columns().expect("columns").expect("section");
        let handle = columns
            .bind_keyword_ordinals(corpus::CITY)
            .expect("bind")
            .expect("ordinal");
        let translation = map.bind_segment(guard).expect("segment map");
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let value = reader
                .column_value(corpus::CITY, doc_id)
                .expect("value")
                .expect("city column");
            let expected_value = if key == APPENDED_KEY {
                FieldValues::Single(FieldValue::Keyword(APPENDED_CITY.to_owned()))
            } else {
                let (_, _, city) = corpus::ROWS
                    .iter()
                    .find(|(row, _, _)| *row == key)
                    .expect("row");
                city.values()
            };
            assert_eq!(value, expected_value, "{key}");
            let expected_rank = match &expected_value {
                FieldValues::Single(FieldValue::Keyword(text)) => Some(
                    expected_terms
                        .iter()
                        .position(|term| term.as_bytes() == text.as_bytes())
                        .expect("term in table") as u64,
                ),
                _ => None,
            };
            match (handle.doc_ordinal(doc_id).expect("row"), expected_rank) {
                (KeywordOrdinalValue::Value { ordinal, state }, Some(rank)) => {
                    assert_eq!(translation.translate(ordinal).expect("translate"), rank);
                    assert_eq!(state, KeywordOrdinalState::Single);
                }
                (KeywordOrdinalValue::Missing, None) => {
                    assert_eq!(value, FieldValues::Absent, "{key}")
                }
                (KeywordOrdinalValue::Null, None) => {
                    assert_eq!(value, FieldValues::ExplicitNull, "{key}")
                }
                (other, wanted) => panic!("{key}: {other:?} vs {wanted:?}"),
            }
        }
    }

    // Both sort directions, both missing placements and K prefixes.
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
            let expected = expected_order(&rows, direction, missing);
            let (actual, total) = sorted_keys(snapshot, direction, missing, 1_000);
            assert_eq!(total, rows.len() as u64);
            assert_eq!(actual, expected, "{direction:?} {missing:?}");
            for limit in [1usize, 5, rows.len()] {
                let (actual, _) = sorted_keys(snapshot, direction, missing, limit);
                assert_eq!(actual, expected[..limit].to_vec());
            }
        }
    }
    map
}

fn assert_aggregates(
    snapshot: &ReaderSnapshot,
    category_counts: &[(&str, u64)],
    n_sum: i128,
    n_distinct: u64,
) {
    let definitions = [
        Aggregation {
            group_by: Some(GroupBy::new(vec![GroupKey::Field("category".into())])),
            aggregates: vec![Aggregate::count()],
            ..Aggregation::new()
        },
        Aggregation {
            aggregates: vec![Aggregate::sum("n")],
            exact_distinct: Some(ExactDistinct { field: "n".into() }),
            ..Aggregation::new()
        },
    ];
    let queries: Vec<QueryRequest> = definitions
        .into_iter()
        .map(|aggregation| {
            let mut request = QueryRequest::new(Query::MatchAll);
            request.top_k = TopK::new(1_000).expect("top-k");
            request.projection = corpus::projection();
            request.aggregation = Some(aggregation);
            request
        })
        .collect();
    let batch = BatchQueryRequest::new(queries, None, corpus::batch_budget());
    let response = execute_batch(
        snapshot,
        &corpus::schema(),
        &corpus::registry(),
        SearchLimits::default(),
        &batch,
        &corpus::batch_policy(),
        &CapabilitySet::new(),
        &CancellationFlag::new(),
    )
    .expect("aggregate batch");
    let Some(PerQueryOutcome::Success(slot0)) = response.slot(0) else {
        panic!("slot0 failed");
    };
    let aggregation = slot0.aggregation.as_ref().expect("aggregation");
    let mut actual: BTreeMap<String, u64> = BTreeMap::new();
    for group in &aggregation.groups {
        let AggregationGroupValue::Value(FieldValue::Keyword(category)) =
            group.components.first().expect("component")
        else {
            panic!("unexpected group");
        };
        let AggregationMetricValue::Count(count) = group.metrics[0] else {
            panic!("unexpected metric");
        };
        actual.insert(category.clone(), count);
    }
    let expected: BTreeMap<String, u64> = category_counts
        .iter()
        .map(|(name, count)| ((*name).to_owned(), *count))
        .collect();
    assert_eq!(actual, expected);

    let Some(PerQueryOutcome::Success(slot1)) = response.slot(1) else {
        panic!("slot1 failed");
    };
    let aggregation = slot1.aggregation.as_ref().expect("aggregation");
    assert_eq!(
        aggregation.groups[0].metrics,
        vec![
            AggregationMetricValue::Sum(NumericAggregate::Signed(n_sum)),
            AggregationMetricValue::ExactDistinct(n_distinct),
        ]
    );
}

/// The five immutable generation-3 objects reached from `CURRENT` and the
/// manifest, fetched entirely through the real provider (no local mirror).
async fn immutable_closure(
    store: &S3ObjectStore,
    prefix: &RemoteKeyPrefix,
) -> BTreeMap<String, Vec<u8>> {
    let limits = TransferLimits::new(1 << 24);
    let current_key = prefix.object_key("index/CURRENT").expect("physical key");
    let current = store
        .get(&current_key, None, &limits)
        .await
        .expect("provider CURRENT");
    let pointer = quervant_core::index::CurrentPointer::parse(&current).expect("pointer");
    let manifest_key = pointer.manifest_key().as_str().to_owned();
    let manifest_bytes = store
        .get(
            &prefix.object_key(&manifest_key).expect("physical key"),
            None,
            &limits,
        )
        .await
        .expect("provider manifest");
    assert_eq!(manifest_bytes.len() as u64, pointer.manifest_length());
    assert_eq!(
        ContentDigest::sha256_v1(&manifest_bytes).to_hex(),
        pointer.manifest_digest().to_hex()
    );
    let manifest =
        Manifest::decode(&manifest_bytes, &SegmentLimits::default()).expect("manifest decode");
    let mut closure = BTreeMap::new();
    closure.insert(manifest_key, manifest_bytes);
    for segment in &manifest.segments {
        let bytes = store
            .get(
                &prefix
                    .object_key(&segment.object_key)
                    .expect("physical key"),
                None,
                &limits,
            )
            .await
            .expect("provider segment");
        assert_eq!(bytes.len() as u64, segment.content_length);
        assert_eq!(
            ContentDigest::sha256_v1(&bytes).as_bytes(),
            &segment.content_digest
        );
        closure.insert(segment.object_key.clone(), bytes);
    }
    if let Some(state) = &manifest.mutation_state {
        let bytes = store
            .get(
                &prefix.object_key(&state.object_key).expect("physical key"),
                None,
                &limits,
            )
            .await
            .expect("provider state");
        assert_eq!(bytes.len() as u64, state.content_length);
        assert_eq!(
            ContentDigest::sha256_v1(&bytes).as_bytes(),
            &state.content_digest
        );
        closure.insert(state.object_key.clone(), bytes);
    }
    closure
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
        let prefix = prefix();
        let writer_workspace = workspace("writer");
        let g3_workspace = workspace("g3");
        let g4a_workspace = workspace("g4a");
        let g4b_workspace = workspace("g4b");
        let config = |root: &std::path::Path| RemoteConfig::new(prefix.clone(), root.to_path_buf());

        // ---- three real remote commits of the frozen first 18 rows ----
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config(&writer_workspace),
            corpus::schema(),
            corpus::registry(),
            IndexLimits::default(),
        )
        .await
        .expect("create");
        for batch in 0..3usize {
            let mut writer = index.writer().await.expect("writer");
            for (key, _, city) in &corpus::ROWS[batch * 6..(batch + 1) * 6] {
                let position = corpus::ROWS
                    .iter()
                    .position(|(row, _, _)| row == key)
                    .expect("row");
                writer
                    .insert(corpus::document_at(position, *city))
                    .expect("insert");
            }
            assert_eq!(
                writer.commit().await.expect("commit").generation,
                (batch + 1) as u64
            );
        }
        let g3_closure = immutable_closure(store.as_ref(), &prefix).await;
        assert_eq!(g3_closure.len(), 5, "manifest + 3 segments + state");

        // ---- g3 cold open in a brand-new empty workspace ----
        let g3 = RemoteIndex::open_existing(
            Arc::clone(&store),
            config(&g3_workspace),
            corpus::schema(),
            corpus::registry(),
            IndexLimits::default(),
        )
        .await
        .expect("cold g3");
        assert_eq!(g3.generation(), Some(3));
        let pit = g3.pin().expect("pin");
        let held_snapshot = Arc::clone(pit.snapshot());
        assert_eq!(held_snapshot.document_count(), 18);
        assert_eq!(held_snapshot.segment_count(), 3);
        let held_map = {
            let snapshot = Arc::clone(&held_snapshot);
            assert_full_view(&snapshot, false, &TERMS_18)
        };
        assert_aggregates(
            &held_snapshot,
            &[("type-a", 6), ("type-b", 6), ("type-c", 6)],
            153,
            18,
        );
        {
            let guards = acquire_guards(&held_snapshot);
            let before = g3.transfer_stats().requests();
            let again = prepare(&held_snapshot, &guards);
            assert!(matches!(
                again,
                KeywordOrdinalPreparation::Ready(ref map)
                    if Arc::ptr_eq(map, &held_map)
            ));
            let _ = sorted_keys(
                &held_snapshot,
                SortDirection::Asc,
                MissingValuePosition::Last,
                100,
            );
            let _ = sorted_keys(
                &held_snapshot,
                SortDirection::Desc,
                MissingValuePosition::Last,
                100,
            );
            assert_eq!(
                g3.transfer_stats().requests(),
                before,
                "warm reuse must not add provider requests"
            );
        }

        // ---- generation 4: one appended `type-d` row through the remote writer ----
        {
            let mut writer = g3.writer().await.expect("writer");
            writer.insert(appended_document()).expect("insert");
            assert_eq!(writer.commit().await.expect("commit").generation, 4);
        }

        // ---- two independent generation-4 cold opens ----
        for workspace_root in [&g4a_workspace, &g4b_workspace] {
            let g4 = RemoteIndex::open_existing(
                Arc::clone(&store),
                config(workspace_root),
                corpus::schema(),
                corpus::registry(),
                IndexLimits::default(),
            )
            .await
            .expect("cold g4");
            assert_eq!(g4.generation(), Some(4));
            let snapshot = g4.snapshot();
            assert_eq!(snapshot.document_count(), 19);
            assert_eq!(snapshot.segment_count(), 4);
            let map = assert_full_view(&snapshot, true, &TERMS_19);
            assert_eq!(map.term_count(), 13);
            assert_aggregates(
                &snapshot,
                &[("type-a", 6), ("type-b", 6), ("type-c", 6), ("type-d", 1)],
                171,
                19,
            );
            // The v2 segment really carries the ordinal feature.
            let mut v2 = 0;
            for guard in &acquire_guards(&snapshot) {
                let reader = guard.reader();
                let body = parse_container(reader.bytes(), &SegmentLimits::default())
                    .expect("container")
                    .body(SectionKind::Columns)
                    .expect("columns");
                if body[..2] != 1u16.to_le_bytes() {
                    v2 += 1;
                }
            }
            assert_eq!(
                v2, 4,
                "every B1-built remote segment carries COLUMNS v2 ordinals"
            );
            drop(snapshot);
            drop(g4);
        }

        // ---- the five recorded generation-3 immutable objects are unchanged ----
        for (key, bytes) in &g3_closure {
            let object_key = prefix.object_key(key).expect("physical key");
            let current = store
                .get(&object_key, None, &TransferLimits::new(1 << 24))
                .await
                .unwrap_or_else(|error| panic!("immutable {key} disappeared: {error}"));
            assert_eq!(&current, bytes, "immutable object {key} changed after g4");
            assert_eq!(
                ContentDigest::sha256_v1(&current).to_hex(),
                ContentDigest::sha256_v1(bytes).to_hex()
            );
        }

        // The held generation-3 view is unchanged and never sees the appended row.
        {
            let guards = acquire_guards(&held_snapshot);
            assert_eq!(held_snapshot.generation(), Some(3));
            let translation = held_map.bind_segment(&guards[0]).expect("bind");
            let _ = translation;
            let (keys, total) = sorted_keys(
                &held_snapshot,
                SortDirection::Asc,
                MissingValuePosition::Last,
                100,
            );
            assert_eq!(total, 18);
            assert!(!keys.contains(&APPENDED_KEY.to_owned()));
            assert_eq!(
                expected_order(&rows(false), SortDirection::Asc, MissingValuePosition::Last),
                keys
            );
        }

        drop(held_snapshot);
        drop(pit);
        drop(g3);
        drop(index);
        for root in [
            &writer_workspace,
            &g3_workspace,
            &g4a_workspace,
            &g4b_workspace,
        ] {
            if root.starts_with(std::env::temp_dir()) && root.exists() {
                std::fs::remove_dir_all(root).expect("remove disposable workspace");
            }
        }
        println!("PERF06_B1_R01_PASS");
    });
}
