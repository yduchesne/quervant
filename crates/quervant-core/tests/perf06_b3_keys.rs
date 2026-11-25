//! PERF-06-B3 — real filesystem, PIT, cursor, corruption and resource slices.
//!
//! Every expected order is derived from the frozen B1 literal input table
//! (`perf06_b1_common`), never from the production comparator, a fingerprint or
//! a previous result. The ineligible `Query::And` reference is a second,
//! independent execution path.

mod perf06_b1_common;

use std::collections::BTreeMap;
use std::sync::Arc;

use perf06_b1_common::*;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, GroupBy, GroupKey,
};
use quervant_core::contract::batch::{BatchQueryRequest, PerQueryOutcome, QueryRequest};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MissingValuePosition, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::value::FieldValue;
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher, execute_batch,
    execute_batch_pinned,
};
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, Manifest, SectionKind, SegmentError, SegmentLimits,
    parse_container,
};

/// A unique temporary directory for this B3 file.
struct B3TempDir {
    path: std::path::PathBuf,
}

impl B3TempDir {
    fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0);
        let serial = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "quervant-perf06-b3-{tag}-{}-{nanos}-{serial}",
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

impl Drop for B3TempDir {
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

/// Independent expected order over the frozen literal corpus.
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

fn assert_scores_and_projection(b3: &UnifiedResponse, legacy: &UnifiedResponse) {
    assert_eq!(b3.total_hits, legacy.total_hits);
    assert_eq!(keys(b3), keys(legacy));
    assert_eq!(score_bits(b3), score_bits(legacy));
    assert_eq!(b3.generation, legacy.generation);
    assert_eq!(b3.view_ordinal, legacy.view_ordinal);
    for hit in &b3.hits {
        assert_eq!(
            hit.fields,
            expected_projected_fields(hit.key.as_str()),
            "B3 projection mismatch for {}",
            hit.key.as_str()
        );
    }
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

fn build_fs_corpus() -> (B3TempDir, Index) {
    let dir = B3TempDir::new("corpus");
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

fn sequential_rows(count: usize) -> Vec<(String, City)> {
    (0..count)
        .map(|index| {
            let value: &'static str = Box::leak(format!("c{index:06}").into_boxed_str());
            (format!("key{index:06}"), City::Value(value))
        })
        .collect()
}

// ---------------------------------------------------------------------------
// B3-I01 — real three-segment corpus parity.
// ---------------------------------------------------------------------------

/// B3-I01: the frozen 18-row/three-segment FsDirectory corpus produces the exact
/// literal order, six-field projection, score bits and total hits.
#[test]
fn b3_i01_filesystem_corpus_full_order_projection_and_scores() {
    let (_dir, index) = build_fs_corpus();
    let snapshot = index.snapshot();
    assert_eq!(snapshot.generation(), Some(3));
    assert_eq!(snapshot.segment_count(), 3);
    let rows = corpus_rows();
    for top_k in [1usize, 5, 10, 18] {
        assert_order_and_fallback(&snapshot, &rows, top_k);
    }
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
        for hit in &response.hits {
            assert_eq!(hit.fields.len(), 6, "complete six-field projection");
        }
    }
}

// ---------------------------------------------------------------------------
// B3-I02 — sequential-key corpora and repeated same-snapshot queries.
// ---------------------------------------------------------------------------

/// B3-I02: a real 1000-row sequential-key index returns the exact order at K=10
/// and K=100, and repeated queries on the same `ReaderSnapshot` are identical.
///
/// The "losing candidates own no key" evidence is structural, so it lives in the
/// crate unit test `b3_u06_u18_losing_candidates_own_no_key` (a `pub(crate)`
/// counter cannot be observed from an integration crate).
#[test]
fn b3_i02_sequential_keys_repeat_queries_are_stable() {
    let rows = sequential_rows(1_000);
    let dir = B3TempDir::new("sequential");
    {
        let index = Index::create(fs_directory(dir.path()), schema(), registry()).expect("create");
        let mut writer = index.writer().expect("writer");
        for (key, city) in &rows {
            writer
                .insert(appended_document(key, *city, 0))
                .expect("insert");
        }
        writer.commit().expect("commit");
    }
    let index = reopen(dir.path());
    let snapshot = index.snapshot();
    for top_k in [10usize, 100] {
        let req = request(
            body_term(),
            top_k,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        );
        let first = search(&snapshot, &req);
        assert_eq!(first.total_hits, rows.len() as u64);
        let expected: Vec<String> =
            order_for(&rows, SortDirection::Asc, MissingValuePosition::Last)
                .into_iter()
                .take(top_k)
                .collect();
        assert_eq!(keys(&first), expected, "K={top_k}");
        for _ in 0..3 {
            let repeated = search(&snapshot, &req);
            assert_eq!(keys(&repeated), keys(&first), "repeat K={top_k}");
            assert_eq!(score_bits(&repeated), score_bits(&first));
        }
        let legacy = search(
            &snapshot,
            &request(
                fallback_query(),
                top_k,
                city_sort(SortDirection::Asc, MissingValuePosition::Last),
            ),
        );
        assert_eq!(legacy.total_hits, first.total_hits);
        assert_eq!(keys(&legacy), keys(&first));
        assert_eq!(score_bits(&legacy), score_bits(&first));
        assert_eq!(
            legacy
                .hits
                .iter()
                .map(|hit| hit.fields.clone())
                .collect::<Vec<_>>(),
            first
                .hits
                .iter()
                .map(|hit| hit.fields.clone())
                .collect::<Vec<_>>()
        );
    }
}

// ---------------------------------------------------------------------------
// B3-I03 — held PITs across append/delete/compact.
// ---------------------------------------------------------------------------

/// B3-I03: held PIT views stay exact and every pre-existing immutable object is
/// byte-identical after append, delete and compaction.
#[test]
fn b3_i03_held_pits_and_immutable_objects_across_mutation() {
    let (dir, index) = build_fs_corpus();
    let g3_objects = reachable_immutable(dir.path());
    let old_pit = index.pin().expect("pin");
    let old_snapshot = Arc::clone(old_pit.snapshot());
    assert_order_and_fallback(&old_snapshot, &corpus_rows(), 18);

    let mut writer = index.writer().expect("writer");
    writer
        .insert(appended_document("d0", City::Value("Chicago"), 18))
        .expect("append");
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);
    let index = reopen(dir.path());
    let mut rows_19 = corpus_rows();
    rows_19.push(("d0".to_owned(), City::Value("Chicago")));
    assert_order_and_fallback(&index.snapshot(), &rows_19, 19);

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
    let mut rows_18 = corpus_rows();
    rows_18.retain(|(key, _)| key != "b0");
    rows_18.push(("d0".to_owned(), City::Value("Chicago")));
    assert_order_and_fallback(&current, &rows_18, 18);

    // The held g3 PIT still returns its original 18-row view.
    assert_eq!(old_snapshot.document_count(), 18);
    assert_order_and_fallback(&old_snapshot, &corpus_rows(), 18);
    // Every immutable object published before g4 is untouched.
    for (path, bytes) in &g3_objects {
        assert_eq!(
            std::fs::read(dir.path().join(path)).expect("immutable"),
            *bytes,
            "immutable object {path} changed"
        );
    }
}

// ---------------------------------------------------------------------------
// B3-I04 — genuine pre-B1 v1 fixture, mixed generation, compaction.
// ---------------------------------------------------------------------------

/// B3-I04: the genuine pre-B1 v1 fixture keeps the legacy path at g3/g4 (no B2
/// ordinals, therefore no B3 directory) and only g5 compaction enables numeric
/// ranking and the compact key path.
#[test]
fn b3_i04_genuine_v1_fixture_then_compaction() {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/index/perf06_b1_columns_v1");
    let dir = B3TempDir::new("v1");
    copy_tree(&source.join("index"), &dir.path().join("index"));
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(3));
    let g3_objects = reachable_immutable(dir.path());
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
    let snapshot = g3_snapshot;
    assert_order_and_fallback(&snapshot, &corpus_rows(), 18);

    let mut writer = index.writer().expect("writer");
    writer
        .insert(appended_document("d0", City::Value("Chicago"), 18))
        .expect("append");
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);
    let index = reopen(dir.path());
    let mut rows_19 = corpus_rows();
    rows_19.push(("d0".to_owned(), City::Value("Chicago")));
    assert_order_and_fallback(&index.snapshot(), &rows_19, 19);

    let mut writer = index.writer().expect("writer");
    assert_eq!(writer.compact().expect("compact").documents, 19);
    drop(writer);
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(5));
    let compacted = index.snapshot();
    assert_eq!(compacted.segment_count(), 1);
    assert_order_and_fallback(&compacted, &rows_19, 19);
    for (path, bytes) in &g3_objects {
        assert_eq!(
            std::fs::read(dir.path().join(path)).expect("immutable"),
            *bytes,
            "frozen v1 object {path} changed"
        );
    }
    // The held g3 PIT keeps the legacy 18-row view.
    assert_order_and_fallback(&snapshot, &corpus_rows(), 18);
}

// ---------------------------------------------------------------------------
// B3-I05 — cursor pages, pinned batch and ineligible shapes.
// ---------------------------------------------------------------------------

/// B3-I05: cursor pages `[5, 5, 5, 3]` reassemble the complete order with owned
/// cursor tuples, and pinned batch/aggregate/typed shapes keep their contracts.
#[test]
fn b3_i05_cursor_pages_pinned_batch_and_ineligible_shapes() {
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
                    // The cursor always carries one owned sort value plus the
                    // owned logical key, never a rank or a fingerprint.
                    assert!(matches!(
                        cursor.last_sort_values().first(),
                        Some(
                            quervant_core::search::SortValue::Missing
                                | quervant_core::search::SortValue::Null
                                | quervant_core::search::SortValue::Value(FieldValue::Keyword(_))
                        )
                    ));
                    assert_eq!(cursor.snapshot_binding(), snapshot.binding_id());
                    assert_eq!(
                        cursor.last_key().as_str(),
                        collected.last().expect("last key")
                    );
                    request.after = Some(cursor);
                }
                None => assert_eq!(page, 3, "only the final page is exhausted"),
            }
        }
        assert_eq!(page_lengths, vec![5, 5, 5, 3]);
        assert_eq!(collected, expected, "{direction:?}");
    }

    // Pinned batch execution keeps owned results and its own PIT view.
    let batch = BatchQueryRequest::new(
        vec![{
            let mut query = QueryRequest::new(body_term());
            query.top_k = TopK::new(3).expect("k");
            query.sort = city_sort(SortDirection::Asc, MissingValuePosition::Last);
            query.projection = projection();
            query
        }],
        Some(pit.id().clone()),
        batch_budget(),
    );
    let response = execute_batch_pinned(
        &pit,
        &schema(),
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
    assert_eq!(slot.total_hits, 18);
    assert_eq!(slot.hits.len(), 3);
    assert!(slot.next_cursor.is_some());

    // A grouped aggregation is an ineligible shape and keeps its own result.
    let mut aggregate_request = QueryRequest::new(body_term());
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
        &schema(),
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
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut other_groups = 0u64;
    for group in &aggregation.groups {
        let AggregationMetricValue::Count(count) = group.metrics[0] else {
            panic!("unexpected metric");
        };
        match group.components.first().expect("component") {
            AggregationGroupValue::Value(FieldValue::Keyword(city)) => {
                *counts.entry(city.clone()).or_insert(0) += count;
            }
            AggregationGroupValue::Null(_) | AggregationGroupValue::Missing(_) => {
                other_groups += count;
            }
            other => panic!("unexpected group component: {other:?}"),
        }
    }
    let mut expected_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut expected_other = 0u64;
    for (_, city) in corpus_rows() {
        match city {
            City::Value(value) => *expected_counts.entry(value.to_owned()).or_insert(0) += 1,
            _ => expected_other += 1,
        }
    }
    assert_eq!(counts, expected_counts);
    assert_eq!(other_groups, expected_other);
}

// ---------------------------------------------------------------------------
// B3-I06 — hosted real RustFS suite is unchanged and still pinned.
// ---------------------------------------------------------------------------

/// B3-I06: the real RustFS acceptance suite is unmodified and still registers the
/// pinned cold shared-ordinal test. The actual execution evidence comes from the
/// `rustfs` CI job; this test only proves the topology was not replaced locally.
#[test]
fn b3_i06_rustfs_suite_registration_is_unchanged() {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/perf06_b1_rustfs.rs");
    let text = std::fs::read_to_string(&source).expect("rustfs suite source");
    assert_eq!(
        text.matches("fn b1_r01_cold_shared_ordinals_and_pit")
            .count(),
        1,
        "the pinned real RustFS test remains registered exactly once"
    );
    assert!(
        text.contains("#[ignore"),
        "the real RustFS suite stays opt-in behind the CI job"
    );
}

// ---------------------------------------------------------------------------
// B3-I07 — corrupt DOC_KEYS behind a valid outer container.
// ---------------------------------------------------------------------------

/// B3-I07: a valid outer container carrying a corrupt `DOC_KEYS` body never
/// produces a successful partial result: opening succeeds (no eager key
/// validation) and every key access raises the original typed corruption.
///
/// A committed filesystem segment cannot be rewritten behind its recorded
/// length/digest state, so the collector-level matched-query behaviour for this
/// topology is proved by the crate unit test
/// `b3_u11_corrupt_doc_keys_stays_authoritative_and_unbound`, and the pristine
/// snapshot below proves matched and zero-match queries keep their contracts.
#[test]
fn b3_i07_corrupt_doc_keys_is_authoritative() {
    let (_dir, index) = build_fs_corpus();
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).expect("guard");
    let original = guard.reader().bytes().to_vec();
    drop(guard);
    let view = parse_container(&original, &SegmentLimits::default()).expect("container");
    let doc_count = view.doc_count();
    let features: Vec<(u16, u16)> = view.required_features().to_vec();
    let optional: Vec<(u16, u16)> = view.optional_features().to_vec();
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
    let keys = view.body(SectionKind::DocKeys).expect("doc keys").to_vec();
    // The header is a u16 version plus a u64 count; byte 12 is the first key byte.
    let mut corrupted = keys.clone();
    corrupted[12] ^= 0xFF;
    assert_ne!(corrupted, keys);
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
    for (id, version) in &features {
        builder.require_feature(*id, *version);
    }
    for (id, version) in &optional {
        builder.optional_feature(*id, *version);
    }
    for (kind, flags, aux, body) in &sections {
        let body = if *kind == SectionKind::DocKeys {
            corrupted.clone()
        } else {
            body.clone()
        };
        builder.section(*kind, *flags, *aux, body);
    }
    let rebuilt = builder.build().expect("rebuild valid container");
    let reader = quervant_core::segment::SegmentReader::open(rebuilt, SegmentLimits::default())
        .expect("a corrupt DOC_KEYS body is not validated at open");
    // Every key access is the original typed corruption, never a success.
    let error = reader.doc_keys().expect_err("corrupt DOC_KEYS");
    assert!(
        matches!(error, SegmentError::InvalidUtf8 { context: "doc key" }),
        "{error:?}"
    );
    let error = reader.doc_key(0).expect_err("corrupt DOC_KEYS");
    assert!(
        matches!(error, SegmentError::InvalidUtf8 { context: "doc key" }),
        "{error:?}"
    );

    // The pristine snapshot keeps both matched and zero-match contracts.
    let matched = search(
        &snapshot,
        &request(
            body_term(),
            5,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    assert_eq!(matched.total_hits, 18);
    assert_order_and_fallback(&snapshot, &corpus_rows(), 5);
    let none = search(
        &snapshot,
        &request(
            Query::Term {
                field: "body".to_owned(),
                value: FieldValue::Text("absent-term".to_owned()),
            },
            5,
            city_sort(SortDirection::Asc, MissingValuePosition::Last),
        ),
    );
    assert_eq!(none.total_hits, 0);
    assert!(none.hits.is_empty());
}

// ---------------------------------------------------------------------------
// B3-I08 — resource limits and the unchanged ExactSet fallback.
// ---------------------------------------------------------------------------

/// B3-I08: a candidate-budget refusal stays the original typed `ResourceLimit`
/// and leaves no partial result; the resolved ExactSet configuration keeps the
/// owned B2 path with identical output.
///
/// The metadata-capacity-only fallback (B2 ordinals still `Ready` while the B3
/// fingerprint directory is refused) cannot be isolated through public snapshot
/// knobs; it is proved by the crate unit tests
/// `b3_u12_exact_cap_one_under_and_injected_refusal` and
/// `b3_u16_mixed_ready_and_unavailable_segments` (plan rule D38).
#[test]
fn b3_i08_resource_limits_and_exact_set_fallback() {
    let (_dir, index) = build_fs_corpus();
    let snapshot = index.snapshot();
    let sort = city_sort(SortDirection::Asc, MissingValuePosition::Last);
    let tight = SearchLimits::default()
        .with_max_total_candidate_bytes(1)
        .expect("limits");
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), tight)
        .search(
            &request(body_term(), 5, sort.clone()),
            &Budgets::new(),
            &cancel(),
        )
        .expect_err("candidate budget");
    assert!(
        matches!(error, SearchError::ResourceLimit { .. }),
        "{error:?}"
    );
    // The same snapshot still answers correctly afterwards.
    let recovered = search(&snapshot, &request(body_term(), 5, sort.clone()));
    let legacy = search(&snapshot, &request(fallback_query(), 5, sort.clone()));
    assert_scores_and_projection(&recovered, &legacy);

    // A fresh snapshot so the ExactSet request cannot benefit from a directory a
    // previous request on another snapshot might have built.
    let exact_snapshot = index.snapshot();
    let rows = corpus_rows();
    // The configured threshold stays 32 and the request TopK is 32: only then does
    // `production_mode` resolve to ExactSet, which keeps the original owned-key
    // path (`b3_u09` proves the resolved mode at the unit seam).
    let exact = UnifiedSearcher::new(
        &exact_snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .with_topk_duplicate_config(quervant_core::search::TopKDuplicateConfig::new(
        std::num::NonZeroUsize::new(32).expect("nonzero"),
        quervant_core::search::TopKDuplicateStrategy::ExactSet,
    ))
    .search(
        &request(body_term(), 32, sort.clone()),
        &Budgets::new(),
        &cancel(),
    )
    .expect("K=32 with the ExactSet threshold must succeed");
    assert_eq!(exact.total_hits, 18);
    assert_eq!(
        exact.hits.len(),
        18,
        "the frozen corpus has exactly 18 rows"
    );
    assert!(exact.next_cursor.is_none());
    let expected: Vec<String> = order_for(&rows, SortDirection::Asc, MissingValuePosition::Last);
    assert_eq!(
        keys(&exact),
        expected,
        "literal input-derived 18-key oracle, not another engine response"
    );
    for hit in &exact.hits {
        assert_eq!(
            hit.fields,
            expected_projected_fields(hit.key.as_str()),
            "complete six-field projection for {}",
            hit.key.as_str()
        );
        assert!(
            hit.score.expect("scored").is_finite(),
            "every returned score is finite for {}",
            hit.key.as_str()
        );
    }
    // The independently executed *ineligible* reference at the same K.
    let fallback = UnifiedSearcher::new(
        &exact_snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(
        &request(fallback_query(), 32, sort.clone()),
        &Budgets::new(),
        &cancel(),
    )
    .expect("ineligible reference at K=32");
    assert_scores_and_projection(&exact, &fallback);
    // The default duplicate configuration at K=32 resolves to Prefilter, so this
    // is a differential contract check, not proof of the ExactSet dispatch.
    let default = search(&exact_snapshot, &request(body_term(), 32, sort));
    assert_scores_and_projection(&default, &exact);
}
