//! PERF-06-B2 — local vertical slices (I01–I08).
//!
//! Every expected key order, projection and rank is derived from the frozen B1
//! input table (`perf06_b1_common`), never from the production comparator, the
//! prepared map or a previous B2 result. The ineligible `Query::And` reference
//! is a second, independent execution path.

mod perf06_b1_common;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use perf06_b1_common::*;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
use quervant_core::contract::batch::{BatchQueryRequest, PerQueryOutcome, QueryRequest};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::error::{InvalidQueryReason, QueryError};
use quervant_core::contract::query::{JsonPathExpr, Query};
use quervant_core::contract::result::{
    MissingValuePosition, MultiValueSelector, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint};
use quervant_core::index::{
    Index, IndexLimits, KeywordOrdinalUnavailable, ReaderSnapshot, SnapshotKeywordOrdinals,
};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
    execute_batch_pinned,
};
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, Manifest, SectionKind, SegmentError, SegmentLimits,
    parse_container,
};

/// A unique temporary directory for this B2 file.
///
/// `perf06_b1_common::TempDir` is frozen and its name has one-second-ish
/// nanosecond granularity, which can collide when several tests in one binary
/// run in parallel. This local helper adds a process-wide counter without
/// modifying the frozen B1 fixture package.
struct B2TempDir {
    path: std::path::PathBuf,
}

impl B2TempDir {
    fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0);
        let serial = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "quervant-perf06-b2-{tag}-{}-{nanos}-{serial}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("create temp dir");
        Self { path }
    }

    fn path(&self) -> &std::path::Path {
        &self.path
    }
}

impl Drop for B2TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn body_term() -> Query {
    Query::Term {
        field: "body".to_owned(),
        value: FieldValue::Text("common".to_owned()),
    }
}

fn fallback_query() -> Query {
    Query::And(vec![body_term()])
}

fn city_sort(direction: SortDirection, missing: MissingValuePosition) -> Sort {
    let mut field = SortField::new("city", direction);
    field.missing = missing;
    Sort::new(vec![field])
}

fn request(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = sort;
    request.projection = projection();
    request
}

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &cancel())
        .expect("search")
}

fn request_city(query: Query, top_k: usize, sort: Sort) -> UnifiedRequest {
    let mut request = request(query, top_k, sort);
    request.projection = Projection::Fields(vec!["city".to_owned()]);
    request
}

/// Parity helper for synthetic-key corpora outside the frozen 18-row table.
fn assert_order_and_fallback_city(
    snapshot: &ReaderSnapshot,
    rows: &[(String, City)],
    top_k: usize,
) {
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
            let ordinal = search(
                snapshot,
                &request_city(body_term(), top_k, city_sort(direction, missing)),
            );
            let legacy = search(
                snapshot,
                &request_city(fallback_query(), top_k, city_sort(direction, missing)),
            );
            assert_eq!(ordinal.total_hits, rows.len() as u64);
            let expected: Vec<String> = order_for(rows, direction, missing)
                .into_iter()
                .take(top_k)
                .collect();
            assert_eq!(keys(&ordinal), expected, "{direction:?}/{missing:?}");
            assert_eq!(keys(&legacy), keys(&ordinal));
            assert_eq!(score_bits(&legacy), score_bits(&ordinal));
            assert_eq!(
                legacy
                    .hits
                    .iter()
                    .map(|hit| hit.fields.clone())
                    .collect::<Vec<_>>(),
                ordinal
                    .hits
                    .iter()
                    .map(|hit| hit.fields.clone())
                    .collect::<Vec<_>>()
            );
        }
    }
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
        .map(|hit| hit.score.expect("scored").to_bits())
        .collect()
}

/// Independent expected order over an arbitrary frozen-corpus row subset.
fn order_for(
    rows: &[(String, City)],
    direction: SortDirection,
    missing: MissingValuePosition,
) -> Vec<String> {
    let mut values: Vec<(Vec<u8>, String)> = rows
        .iter()
        .filter_map(|(key, city)| match city {
            City::Value(value) => Some((value.as_bytes().to_vec(), key.clone())),
            _ => None,
        })
        .collect();
    values.sort_by(|left, right| {
        let term_order = match direction {
            SortDirection::Asc => left.0.cmp(&right.0),
            SortDirection::Desc => right.0.cmp(&left.0),
        };
        term_order.then_with(|| left.1.cmp(&right.1))
    });
    let mut missing_rows: Vec<String> = rows
        .iter()
        .filter(|(_, city)| *city == City::Missing)
        .map(|(key, _)| key.clone())
        .collect();
    missing_rows.sort();
    let mut null_rows: Vec<String> = rows
        .iter()
        .filter(|(_, city)| *city == City::Null)
        .map(|(key, _)| key.clone())
        .collect();
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

fn corpus_rows() -> Vec<(String, City)> {
    ROWS.iter()
        .map(|(key, _, city)| ((*key).to_owned(), *city))
        .collect()
}

fn assert_scores_and_projection(b2: &UnifiedResponse, legacy: &UnifiedResponse) {
    assert_eq!(b2.total_hits, legacy.total_hits);
    assert_eq!(keys(b2), keys(legacy));
    assert_eq!(score_bits(b2), score_bits(legacy));
    assert_eq!(b2.generation, legacy.generation);
    assert_eq!(b2.view_ordinal, legacy.view_ordinal);
    for hit in &b2.hits {
        assert_eq!(
            hit.fields,
            expected_projected_fields(hit.key.as_str()),
            "B2 projection mismatch for {}",
            hit.key.as_str()
        );
    }
}

fn build_fs_corpus() -> (B2TempDir, Index) {
    let dir = B2TempDir::new("b2");
    {
        let directory = fs_directory(dir.path());
        let index = Index::create(directory, schema(), registry()).expect("create");
        for (batch, chunk) in ROWS.chunks(6).enumerate() {
            let mut writer = index.writer().expect("writer");
            for (key, _, city) in chunk {
                let position = ROWS.iter().position(|(row, _, _)| row == key).expect("row");
                writer.insert(document_at(position, *city)).expect("insert");
            }
            assert_eq!(
                writer.commit().expect("commit").generation,
                (batch + 1) as u64
            );
        }
    }
    let index =
        Index::open_existing(fs_directory(dir.path()), schema(), registry()).expect("reopen");
    (dir, index)
}

fn reopen(path: &std::path::Path) -> Index {
    Index::open_existing(fs_directory(path), schema(), registry()).expect("reopen")
}

fn copy_tree(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir_all(to).expect("create");
    for entry in walkdir(from) {
        let relative = entry.strip_prefix(from).expect("relative");
        let target = to.join(relative);
        if entry.is_dir() {
            std::fs::create_dir_all(&target).expect("dir");
        } else {
            std::fs::copy(&entry, &target).expect("copy");
        }
    }
}

fn walkdir(root: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(path) = stack.pop() {
        out.push(path.clone());
        if path.is_dir() {
            for entry in std::fs::read_dir(&path).expect("read_dir") {
                stack.push(entry.expect("entry").path());
            }
        }
    }
    out.sort();
    out
}

/// Immutable objects reachable from `CURRENT` (manifest, segments, state).
fn reachable_immutable(root: &std::path::Path) -> BTreeMap<String, Vec<u8>> {
    let current = std::fs::read(root.join("index/CURRENT")).expect("CURRENT");
    let pointer = quervant_core::index::CurrentPointer::parse(&current).expect("pointer");
    let manifest_key = pointer.manifest_key().as_str().to_owned();
    let manifest_bytes = std::fs::read(root.join(&manifest_key)).expect("manifest");
    let manifest =
        Manifest::decode(&manifest_bytes, &SegmentLimits::default()).expect("manifest decode");
    let mut objects = BTreeMap::new();
    objects.insert(manifest_key, manifest_bytes);
    for segment in &manifest.segments {
        objects.insert(
            segment.object_key.clone(),
            std::fs::read(root.join(&segment.object_key)).expect("segment"),
        );
    }
    if let Some(state) = &manifest.mutation_state {
        objects.insert(
            state.object_key.clone(),
            std::fs::read(root.join(&state.object_key)).expect("state"),
        );
    }
    objects
}

fn appended_document(key: &str, city: City, n: i64) -> Document {
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
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
    doc.insert("city", city.values()).expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(n)))
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

fn assert_order_and_fallback(snapshot: &ReaderSnapshot, rows: &[(String, City)], top_k: usize) {
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
            let ordinal = search(
                snapshot,
                &request(body_term(), top_k, city_sort(direction, missing)),
            );
            let legacy = search(
                snapshot,
                &request(fallback_query(), top_k, city_sort(direction, missing)),
            );
            assert_eq!(ordinal.total_hits, rows.len() as u64);
            let expected: Vec<String> = order_for(rows, direction, missing)
                .into_iter()
                .take(top_k)
                .collect();
            assert_eq!(keys(&ordinal), expected, "{direction:?}/{missing:?}");
            assert_scores_and_projection(&ordinal, &legacy);
        }
    }
}

/// Shared rank proof over the frozen three-segment corpus.
fn assert_shared_ranks(snapshot: &ReaderSnapshot) {
    let guards = guards(snapshot);
    let preparation = prepare_city(snapshot, &guards);
    let map: &Arc<SnapshotKeywordOrdinals> = ready_map(&preparation);
    assert_eq!(map.field_id(), CITY);
    assert_eq!(map.term_count(), GLOBAL_CITY_ORDER.len() as u64);
    let segments = segment_ordinals(snapshot, &guards, map);
    assert_eq!(segments.len(), 3);
    // Seattle exists in batches A and B with different local ordinals but one
    // shared rank derived from the literal input table.
    let seattle_rank = expected_rank("Seattle");
    let mut seattle_local = BTreeSet::new();
    let mut seattle_ranks = BTreeSet::new();
    for segment in &segments {
        for (local, term) in segment.terms.iter().enumerate() {
            if term.as_slice() == b"Seattle" {
                seattle_local.insert(local);
                seattle_ranks.insert(segment.ranks[local]);
            }
            assert_eq!(
                Some(segment.ranks[local]),
                GLOBAL_CITY_ORDER
                    .iter()
                    .position(|value| value.as_bytes() == term.as_slice())
                    .map(|rank| rank as u64)
            );
        }
    }
    assert_eq!(seattle_ranks, BTreeSet::from([seattle_rank]));
    assert_eq!(seattle_local.len(), 2, "two distinct local ordinals");
    for key in ["a4", "b2"] {
        assert_eq!(shared_city_rank(&guards, map, key), Some(seattle_rank));
    }
}

/// B2-I01: real FsDirectory corpus, full order/projection/score parity.
#[test]
fn b2_i01_filesystem_corpus_full_order_and_projection() {
    let (_dir, index) = build_fs_corpus();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.generation(), Some(3));
    assert_eq!(snapshot.segment_count(), 3);
    assert_shared_ranks(&snapshot);
    let rows = corpus_rows();
    for top_k in [1usize, 5, 10, 18] {
        assert_order_and_fallback(&snapshot, &rows, top_k);
    }
    // Complete 18-key order at K=18 for both directions.
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        let response = search(
            &snapshot,
            &request(
                body_term(),
                18,
                city_sort(direction, MissingValuePosition::Last),
            ),
        );
        assert_eq!(response.hits.len(), 18);
        assert_eq!(
            keys(&response),
            order_for(&rows, direction, MissingValuePosition::Last)
        );
        assert!(response.next_cursor.is_none());
    }
}

/// B2-I02: first page uses B2; continuation pages use the string-backed cursor.
#[test]
fn b2_i02_cursor_pagination_reassembles_the_complete_order() {
    let (_dir, index) = build_fs_corpus();
    let pit = index.pin().expect("pin");
    let snapshot = Arc::clone(pit.snapshot());
    let rows = corpus_rows();
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        let expected = order_for(&rows, direction, MissingValuePosition::Last);
        let mut request = request(
            body_term(),
            5,
            city_sort(direction, MissingValuePosition::Last),
        );
        let mut collected = Vec::new();
        let mut page_lengths = Vec::new();
        for page in 0..4usize {
            let response = search(&snapshot, &request);
            assert_eq!(response.total_hits, 18);
            page_lengths.push(response.hits.len());
            collected.extend(keys(&response));
            match response.next_cursor {
                Some(cursor) => {
                    // The cursor carries the canonical owned string tuple.
                    // The cursor keeps an owned string tuple, never a rank.
                    match cursor.last_sort_values().first() {
                        Some(
                            quervant_core::search::SortValue::Missing
                            | quervant_core::search::SortValue::Null
                            | quervant_core::search::SortValue::Value(FieldValue::Keyword(_)),
                        ) => {}
                        other => panic!("unexpected cursor sort atom: {other:?}"),
                    }
                    assert_eq!(cursor.snapshot_binding(), snapshot.binding_id());
                    assert_eq!(
                        cursor.last_key().as_str(),
                        collected.last().expect("last key")
                    );
                    request.after = Some(cursor);
                }
                None => {
                    assert_eq!(page, 3, "only the final page is exhausted");
                }
            }
        }
        assert_eq!(page_lengths, vec![5, 5, 5, 3]);
        assert_eq!(collected, expected, "{direction:?}");
    }

    // Wrong sort and wrong snapshot remain exact cursor errors before any map.
    let asc = city_sort(SortDirection::Asc, MissingValuePosition::Last);
    let first = search(&snapshot, &request(body_term(), 2, asc.clone()));
    let cursor = first.next_cursor.clone().expect("cursor");
    let mut wrong = request(
        body_term(),
        2,
        city_sort(SortDirection::Desc, MissingValuePosition::Last),
    );
    wrong.after = Some(cursor.clone());
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&wrong, &Budgets::new(), &cancel())
        .expect_err("sort mismatch");
    assert!(matches!(
        error,
        SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::CursorSortMismatch
        ))
    ));
    let other = index.snapshot();
    let mut foreign = request(body_term(), 2, asc);
    foreign.after = Some(cursor);
    let error = UnifiedSearcher::new(&other, &schema(), &registry(), SearchLimits::default())
        .search(&foreign, &Budgets::new(), &cancel())
        .expect_err("foreign cursor");
    assert!(matches!(
        error,
        SearchError::Query(QueryError::InvalidQuery(
            InvalidQueryReason::CursorPitMismatch
        ))
    ));
}

/// B2-I03: the genuine pre-B1 fixture falls back, then compacts to numeric v2.
#[test]
fn b2_i03_genuine_v1_fixture_falls_back_then_compacts() {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/index/perf06_b1_columns_v1");
    let dir = B2TempDir::new("b2-i03");
    copy_tree(&source.join("index"), &dir.path().join("index"));
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(3));

    // --- g3: genuine legacy COLUMNS v1 => whole-request fallback ---
    let g3_objects = reachable_immutable(dir.path());
    assert_eq!(g3_objects.len(), 5);
    let g3_pit = index.pin().expect("pin");
    let g3_snapshot = Arc::clone(g3_pit.snapshot());
    for segment_index in 0..3 {
        let guard = g3_snapshot
            .open_segment_reader(segment_index)
            .expect("guard");
        let body = parse_container(guard.reader().bytes(), &SegmentLimits::default())
            .expect("container")
            .body(SectionKind::Columns)
            .expect("columns")
            .to_vec();
        assert_eq!(&body[..2], &1u16.to_le_bytes(), "genuine COLUMNS v1");
    }
    assert_eq!(
        prepare_city(&g3_snapshot, &guards(&g3_snapshot)).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    assert_order_and_fallback(&g3_snapshot, &corpus_rows(), 18);

    // --- g4: append one v2 segment => still a whole-request fallback ---
    let mut writer = index.writer().expect("writer");
    writer
        .insert(appended_document("d0", City::Value("Chicago"), 18))
        .expect("append");
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);
    let index = reopen(dir.path());
    let g4_objects = reachable_immutable(dir.path());
    assert_eq!(g4_objects.len(), 6);
    let g4_snapshot = index.pin().expect("pin");
    let g4_snapshot = Arc::clone(g4_snapshot.snapshot());
    assert_eq!(
        prepare_city(&g4_snapshot, &guards(&g4_snapshot)).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    let mut rows_19 = corpus_rows();
    rows_19.push(("d0".to_owned(), City::Value("Chicago")));
    assert_order_and_fallback(&g4_snapshot, &rows_19, 19);

    // --- g5: real compaction to one all-v2 segment => numeric ranking ---
    let mut writer = index.writer().expect("writer");
    assert_eq!(writer.compact().expect("compact").documents, 19);
    drop(writer);
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(5));
    let g5_snapshot = index.snapshot();
    assert_eq!(g5_snapshot.segment_count(), 1);
    assert_eq!(g5_snapshot.document_count(), 19);
    assert!(
        prepare_city(&g5_snapshot, &guards(&g5_snapshot))
            .ready()
            .is_some()
    );
    assert_order_and_fallback(&g5_snapshot, &rows_19, 19);
    for (path, bytes) in g3_objects.iter().chain(g4_objects.iter()) {
        assert_eq!(
            std::fs::read(dir.path().join(path)).expect("immutable"),
            *bytes,
            "immutable object {path} changed"
        );
    }
    // The held g3 PIT still falls back and still returns its original view.
    assert_eq!(
        prepare_city(&g3_snapshot, &guards(&g3_snapshot)).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    assert_eq!(g3_snapshot.document_count(), 18);
    assert_order_and_fallback(&g3_snapshot, &corpus_rows(), 18);
}

/// B2-I04: held PITs keep their ranks while new snapshots renumber.
#[test]
fn b2_i04_held_pits_keep_old_ranks_across_append_delete_compact() {
    let (dir, index) = build_fs_corpus();
    let old_pit = index.pin().expect("pin");
    let old_snapshot = Arc::clone(old_pit.snapshot());
    let old_guards = guards(&old_snapshot);
    let old_map = Arc::clone(ready_map(&prepare_city(&old_snapshot, &old_guards)));
    assert_eq!(shared_city_rank(&old_guards, &old_map, "b0"), Some(3));
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a4"), Some(5));

    let mut writer = index.writer().expect("writer");
    writer
        .insert(appended_document("d0", City::Value("Chicago"), 18))
        .expect("append");
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);
    let index = reopen(dir.path());
    let g4 = index.snapshot();
    let g4_guards = guards(&g4);
    let g4_map = Arc::clone(ready_map(&prepare_city(&g4, &g4_guards)));
    // "Chicago" sits between "Boston" and "Dallas", shifting later ranks.
    assert_eq!(shared_city_rank(&g4_guards, &g4_map, "d0"), Some(4));
    assert_eq!(shared_city_rank(&g4_guards, &g4_map, "a4"), Some(6));
    // The held PIT keeps its own numbers.
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a4"), Some(5));

    let mut writer = index.writer().expect("writer");
    writer
        .apply(quervant_core::contract::document::MutationRequest::delete(
            DocumentKey::new("b0").expect("key"),
        ))
        .expect("delete");
    assert_eq!(writer.commit().expect("commit").generation, 5);
    assert_eq!(writer.compact().expect("compact").documents, 18);
    drop(writer);
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(6));
    let current = index.snapshot();
    assert_eq!(current.segment_count(), 1);
    let current_guards = guards(&current);
    let current_map = Arc::clone(ready_map(&prepare_city(&current, &current_guards)));
    assert_eq!(current_map.term_count(), 12);
    assert!(shared_city_rank(&current_guards, &current_map, "b0").is_none());
    let mut rows = corpus_rows();
    rows.retain(|(key, _)| key != "b0");
    rows.push(("d0".to_owned(), City::Value("Chicago")));
    assert_order_and_fallback(&current, &rows, rows.len());
    assert_order_and_fallback(&old_snapshot, &corpus_rows(), 18);
}

/// B2-I05: single segment, all-absent/null, zero-segment and MultiOne shapes.
#[test]
fn b2_i05_identity_absent_null_empty_and_multi_one() {
    let dir = B2TempDir::new("b2-i05");
    {
        let index = Index::create(fs_directory(dir.path()), schema(), registry()).expect("create");
        let mut writer = index.writer().expect("writer");
        writer
            .insert(appended_document("k0", City::Missing, 0))
            .expect("missing");
        writer
            .insert(appended_document("k1", City::Null, 1))
            .expect("null");
        writer
            .insert(appended_document("k2", City::Value(""), 2))
            .expect("empty");
        writer
            .insert(appended_document("k3", City::Value("a"), 3))
            .expect("value");
        writer
            .insert(appended_document("k4", City::Value("z"), 4))
            .expect("value");
        assert_eq!(writer.commit().expect("commit").segments_added, 1);
    }
    let index = reopen(dir.path());
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 1);
    let guards = guards(&snapshot);
    let preparation = prepare_city(&snapshot, &guards);
    let map = ready_map(&preparation);
    // One segment uses the identity mapping: local ordinal == shared rank.
    for segment in segment_ordinals(&snapshot, &guards, map) {
        for (ordinal, rank) in segment.ranks.iter().enumerate() {
            assert_eq!(ordinal as u64, *rank);
        }
    }
    let rows = vec![
        ("k0".to_owned(), City::Missing),
        ("k1".to_owned(), City::Null),
        ("k2".to_owned(), City::Value("")),
        ("k3".to_owned(), City::Value("a")),
        ("k4".to_owned(), City::Value("z")),
    ];
    assert_order_and_fallback_city(&snapshot, &rows, rows.len());

    // A real one-element `Multi` on the single-cardinality city field.
    let multi_dir = B2TempDir::new("b2-i05-multi");
    {
        let index =
            Index::create(fs_directory(multi_dir.path()), schema(), registry()).expect("create");
        let mut writer = index.writer().expect("writer");
        let mut multi = appended_document("m0", City::Value("Austin"), 0);
        multi
            .insert(
                "city",
                FieldValues::Multi(vec![FieldValue::Keyword("Austin".to_owned())]),
            )
            .expect("multi");
        writer.insert(multi).expect("insert");
        writer
            .insert(appended_document("m1", City::Value("Austin"), 1))
            .expect("single");
        writer
            .insert(appended_document("m2", City::Value("Boston"), 2))
            .expect("single");
        writer.commit().expect("commit");
    }
    let index = reopen(multi_dir.path());
    let snapshot = index.snapshot();
    let rows = vec![
        ("m0".to_owned(), City::Value("Austin")),
        ("m1".to_owned(), City::Value("Austin")),
        ("m2".to_owned(), City::Value("Boston")),
    ];
    assert_order_and_fallback_city(&snapshot, &rows, rows.len());
    let response = search(
        &snapshot,
        &request_city(
            body_term(),
            10,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    let multi_hit = response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "m0")
        .expect("multi hit");
    assert_eq!(
        multi_hit.fields[0],
        (
            "city".to_owned(),
            FieldValues::Multi(vec![FieldValue::Keyword("Austin".to_owned())])
        )
    );

    // Zero segments: the old empty result, no preparation, no error.
    let empty_dir = B2TempDir::new("b2-i05-empty");
    let empty = Index::create_with_limits(
        fs_directory(empty_dir.path()),
        schema(),
        registry(),
        IndexLimits::default(),
    )
    .expect("empty index");
    let snapshot = empty.snapshot();
    assert_eq!(snapshot.segment_count(), 0);
    let response = search(
        &snapshot,
        &request_city(
            body_term(),
            10,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    assert_eq!(response.total_hits, 0);
    assert!(response.hits.is_empty());
}

// ---------------------------------------------------------------------------
// B2-I06 — ineligible shapes on a real filesystem index.
// ---------------------------------------------------------------------------

fn mixed_schema() -> Schema {
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
                "city",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
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
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .expect("mixed schema")
}

fn mixed_document(key: &str, city: &str, n: i64, rank: i64, lat: f64, lon: f64) -> Document {
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
    doc.insert(
        "title",
        FieldValues::Single(FieldValue::Text("common".to_owned())),
    )
    .expect("title");
    doc.insert(
        "city",
        FieldValues::Single(FieldValue::Keyword(city.to_owned())),
    )
    .expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(n)))
        .expect("n");
    doc.insert(
        "body",
        FieldValues::Single(FieldValue::Json(
            quervant_core::contract::value::JsonValue::Object(
                [(
                    "rank".to_owned(),
                    quervant_core::contract::value::JsonValue::Number(
                        quervant_core::contract::value::JsonNumber::I64(rank),
                    ),
                )]
                .into_iter()
                .collect(),
            ),
        )),
    )
    .expect("body");
    doc.insert(
        "loc",
        FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(lat, lon).expect("geo"))),
    )
    .expect("loc");
    doc.insert(
        "tags",
        FieldValues::Multi(vec![
            FieldValue::Keyword(format!("tag-{city}")),
            FieldValue::Keyword("shared".to_owned()),
        ]),
    )
    .expect("tags");
    doc
}

fn mixed_search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(
        snapshot,
        &mixed_schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(request, &Budgets::new(), &cancel())
    .expect("search")
}

/// B2-I06: Boolean/typed/JSON/geo/multi-value/relevance and batch aggregation
/// keep their established behavior and outputs.
#[test]
fn b2_i06_ineligible_shapes_keep_existing_behavior() {
    let dir = B2TempDir::new("b2-i06");
    {
        let index =
            Index::create(fs_directory(dir.path()), mixed_schema(), registry()).expect("create");
        let mut writer = index.writer().expect("writer");
        writer
            .insert(mixed_document("k0", "Austin", 30, 2, 0.0, 0.0))
            .expect("k0");
        writer
            .insert(mixed_document("k1", "Boston", 10, 1, 0.0, 1.0))
            .expect("k1");
        writer
            .insert(mixed_document("k2", "Austin", 20, 3, 0.0, 2.0))
            .expect("k2");
        writer.commit().expect("commit");
    }
    let index =
        Index::open_existing(fs_directory(dir.path()), mixed_schema(), registry()).expect("reopen");
    let snapshot = index.snapshot();
    let term = Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text("common".to_owned()),
    };
    let mut city_request = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    city_request.sort = Sort::new(vec![SortField::new("city", SortDirection::Asc)]);
    let eligible = mixed_search(&snapshot, &city_request);
    assert_eq!(
        keys(&eligible),
        vec!["k0".to_owned(), "k2".to_owned(), "k1".to_owned()]
    );

    let mut shapes: Vec<(UnifiedRequest, Vec<&str>)> = Vec::new();
    let mut boolean = UnifiedRequest::new(
        Query::And(vec![
            term.clone(),
            Query::Exists {
                field: "n".to_owned(),
            },
        ]),
        TopK::new(10).expect("k"),
    );
    boolean.sort = Sort::new(vec![SortField::new("city", SortDirection::Asc)]);
    shapes.push((boolean, vec!["k0", "k2", "k1"]));

    let mut numeric = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    numeric.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    shapes.push((numeric, vec!["k1", "k2", "k0"]));

    let mut json = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    let mut json_field = SortField::new("body", SortDirection::Asc);
    json_field.json_path = Some(JsonPathExpr::parse("$.rank").expect("json path"));
    json.sort = Sort::new(vec![json_field]);
    shapes.push((json, vec!["k1", "k0", "k2"]));

    let mut geo = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    let mut geo_field = SortField::new("loc", SortDirection::Asc);
    geo_field.distance_from = Some(GeoPoint::new(0.0, 0.0).expect("origin"));
    geo.sort = Sort::new(vec![geo_field]);
    shapes.push((geo, vec!["k0", "k1", "k2"]));

    let mut tags = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    let mut tag_field = SortField::new("tags", SortDirection::Asc);
    tag_field.multi = Some(MultiValueSelector::Max);
    tags.sort = Sort::new(vec![tag_field]);
    shapes.push((tags, vec!["k0", "k2", "k1"]));

    let mut relevance = UnifiedRequest::new(term.clone(), TopK::new(10).expect("k"));
    relevance.projection = Projection::Source;
    relevance.sort = Sort::default();
    shapes.push((relevance, vec!["k0", "k1", "k2"]));

    for (shape, expected) in shapes {
        let response = mixed_search(&snapshot, &shape);
        assert_eq!(response.total_hits, 3, "{:?}", shape.sort);
        assert_eq!(keys(&response), expected, "{:?}", shape.sort);
    }

    // Public batch aggregation over the same snapshot is unchanged.
    let mut aggregate_request = QueryRequest::new(term.clone());
    aggregate_request.top_k = TopK::new(10).expect("k");
    aggregate_request.projection = Projection::Source;
    aggregate_request.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("city".into())])),
        aggregates: vec![Aggregate::count()],
        ..Aggregation::new()
    });
    let batch = BatchQueryRequest::new(vec![aggregate_request], None, batch_budget());
    let response = execute_batch(
        &snapshot,
        &mixed_schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
    )
    .expect("batch aggregate");
    let Some(PerQueryOutcome::Success(slot)) = response.slot(0) else {
        panic!("aggregate slot failed");
    };
    let aggregation = slot.aggregation.as_ref().expect("aggregation");
    let mut counts = BTreeMap::new();
    for group in &aggregation.groups {
        let AggregationGroupValue::Value(FieldValue::Keyword(city)) =
            group.components.first().expect("component")
        else {
            panic!("unexpected group");
        };
        let AggregationMetricValue::Count(count) = group.metrics[0] else {
            panic!("unexpected metric");
        };
        counts.insert(city.clone(), count);
    }
    assert_eq!(
        counts,
        BTreeMap::from([("Austin".to_owned(), 2), ("Boston".to_owned(), 1)])
    );

    // The PIT-bound public cursor envelope still pages the eligible sort.
    let pit = index.pin().expect("pin");
    let mut paginated = QueryRequest::new(term);
    paginated.top_k = TopK::new(2).expect("k");
    paginated.sort = Sort::new(vec![SortField::new("city", SortDirection::Asc)]);
    paginated.projection = Projection::Source;
    let batch = BatchQueryRequest::new(vec![paginated], Some(pit.id().clone()), batch_budget());
    let response = execute_batch_pinned(
        &pit,
        &mixed_schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
        quervant_core::contract::value::Timestamp::from_micros(1_000),
        quervant_core::contract::value::Timestamp::from_micros(10_000),
    )
    .expect("pinned envelope");
    let Some(PerQueryOutcome::Success(slot)) = response.slot(0) else {
        panic!("pinned slot failed");
    };
    assert_eq!(slot.total_hits, 3);
    assert_eq!(slot.hits.len(), 2);
    assert!(slot.next_cursor.is_some());
}

// ---------------------------------------------------------------------------
// B2-I07 — losing values and corrupt unselected v2 data.
// ---------------------------------------------------------------------------

/// B2-I07: a losing long value is fully validated, and a container-wrapped
/// corrupt v2 term is refused before any numeric selection.
#[test]
fn b2_i07_losing_long_value_and_container_wrapped_corruption() {
    // Losing 80-byte value: it is charged and validated, never truncated.
    let long: &'static str = Box::leak("z".repeat(80).into_boxed_str());
    let dir = B2TempDir::new("b2-i07");
    {
        let index = Index::create(fs_directory(dir.path()), schema(), registry()).expect("create");
        let mut writer = index.writer().expect("writer");
        writer
            .insert(appended_document("k0", City::Value("a"), 0))
            .expect("k0");
        writer
            .insert(appended_document("k1", City::Value(long), 1))
            .expect("k1");
        writer.commit().expect("commit");
    }
    let index = reopen(dir.path());
    let snapshot = index.snapshot();
    let response = search(
        &snapshot,
        &request(
            body_term(),
            1,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    assert_eq!(keys(&response), vec!["k0".to_owned()]);
    assert_eq!(response.total_hits, 2);
    let response = search(
        &snapshot,
        &request(
            body_term(),
            2,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    assert_eq!(keys(&response), vec!["k0".to_owned(), "k1".to_owned()]);

    // Corrupt unselected v2 dictionary term behind a valid outer envelope.
    let (_corpus_dir, corpus) = build_fs_corpus();
    let corpus_snapshot = corpus.snapshot();
    // `Seattle` lives in exactly one frozen segment; locate it by content.
    let mut located = None;
    for index in 0..corpus_snapshot.segment_count() {
        let guard = corpus_snapshot.open_segment_reader(index).expect("guard");
        let bytes = guard.reader().bytes().to_vec();
        if bytes.windows(7).any(|window| window == b"Seattle") {
            let features = guard.reader().required_features().to_vec();
            let doc_count = guard.reader().doc_count();
            located = Some((index, bytes, features, doc_count));
            break;
        }
    }
    let (segment, bytes, features, doc_count) = located.expect("segment with Seattle");
    let view = parse_container(&bytes, &SegmentLimits::default()).expect("container");
    let sections: Vec<(SectionKind, u16, u64, Vec<u8>)> = view
        .sections()
        .iter()
        .map(|entry| {
            (
                entry.kind,
                entry.flags,
                entry.aux,
                view.body(entry.kind).expect("body").to_vec(),
            )
        })
        .collect();
    let original = view.body(SectionKind::Columns).expect("columns").to_vec();
    let mut corrupted = original.clone();
    let at = corrupted
        .windows(7)
        .position(|window| window == b"Seattle")
        .expect("Seattle term");
    corrupted[at] = 0xFF;
    assert_ne!(corrupted, original);
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
    for (id, version) in &features {
        builder.require_feature(*id, *version);
    }
    for (kind, flags, aux, body) in &sections {
        let body = if *kind == SectionKind::Columns {
            corrupted.clone()
        } else {
            body.clone()
        };
        builder.section(*kind, *flags, *aux, body);
    }
    let rebuilt = builder.build().expect("rebuild container");
    let error = match quervant_core::segment::SegmentReader::open(rebuilt, SegmentLimits::default())
    {
        Err(error) => error,
        Ok(_) => panic!("a corrupt v2 dictionary term must be refused"),
    };
    assert!(matches!(
        error,
        SegmentError::InvalidUtf8 { context: "keyword" }
    ));
    // The original immutable segment and the prepared map are unaffected.
    let guard = corpus_snapshot.open_segment_reader(segment).expect("guard");
    assert_eq!(guard.reader().bytes(), bytes.as_slice());
    assert!(
        prepare_city(&corpus_snapshot, &guards(&corpus_snapshot))
            .ready()
            .is_some()
    );
}

// ---------------------------------------------------------------------------
// B2-I08 — adapter session source contract (untimed).
// ---------------------------------------------------------------------------

#[test]
fn b2_i08_adapter_session_keeps_one_snapshot_per_session() {
    // This test intentionally runs no benchmark: it proves only that the
    // adapter's query session retains one snapshot per process session, which is
    // the B2 reuse premise. The real assertion lives in the adapter crate test
    // named `query_session_constructs_exactly_one_snapshot_for_the_whole_session`.
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../benchmarks/pr15d/adapters/quervant/src/main.rs");
    let text = std::fs::read_to_string(&source).expect("adapter source");
    assert!(text.contains("struct QuerySession"));
    assert!(text.contains("snapshot: Arc<ReaderSnapshot>"));
    assert_eq!(
        text.matches("query_session_constructs_exactly_one_snapshot_for_the_whole_session")
            .count(),
        1,
        "the adapter contract test remains registered"
    );
}
