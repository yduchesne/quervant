//! PERF-06-B1 — local vertical slices (I01–I08).
//!
//! Every expectation is derived from the frozen input table in
//! `perf06_b1_common`; the production codec, merge and comparator are never used
//! to compute an expected rank or ordering.

mod perf06_b1_common;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use perf06_b1_common::*;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue, ExactDistinct, GroupBy,
    GroupKey, NumericAggregate,
};
use quervant_core::contract::batch::{BatchQueryRequest, PerQueryOutcome, QueryRequest};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use quervant_core::contract::query::{Bound, Query};
use quervant_core::contract::result::{MissingValuePosition, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{FieldValue, Timestamp};
use quervant_core::index::{
    GuardedSegmentReader, Index, IndexLimits, KeywordOrdinalUnavailable, ReaderSnapshot,
    SnapshotKeywordOrdinals,
};
use quervant_core::search::{
    SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher, execute_batch, execute_batch_pinned,
};
use quervant_core::segment::column::{KeywordOrdinalState, KeywordOrdinalValue};
use quervant_core::segment::format::FEATURE_KEYWORD_ORDINALS;
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, SectionKind, SegmentError, SegmentLimits, parse_container,
};
use quervant_core::storage::{Directory, MemoryDirectory};

fn memory_directory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

/// Build the frozen three-commit corpus, then return a freshly reopened handle so
/// the committed generation is the one actually observed.
fn build_corpus(directory: Arc<dyn Directory>) -> Index {
    {
        let index = Index::create(Arc::clone(&directory), schema(), registry()).expect("create");
        for (batch, chunk) in ROWS.chunks(6).enumerate() {
            let mut writer = index.writer().expect("writer");
            for (key, _, city) in chunk {
                let position = ROWS.iter().position(|(row, _, _)| row == key).expect("row");
                let _ = key;
                writer.insert(document_at(position, *city)).expect("insert");
            }
            let outcome = writer.commit().expect("commit");
            assert_eq!(outcome.generation, (batch + 1) as u64);
            assert_eq!(outcome.segments_added, 1);
        }
    }
    Index::open_existing(directory, schema(), registry()).expect("reopen committed corpus")
}

/// Reopen a committed index so every lifecycle step observes the new generation.
fn reopen(dir: &std::path::Path) -> Index {
    Index::open_existing(fs_directory(dir), schema(), registry()).expect("reopen")
}

fn sorted_hits(
    snapshot: &ReaderSnapshot,
    direction: SortDirection,
    missing: MissingValuePosition,
    limit: usize,
) -> Vec<String> {
    let mut field = SortField::new("city", direction);
    field.missing = missing;
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(limit).expect("top-k"));
    request.sort = Sort::new(vec![field]);
    request.projection = projection();
    let response = UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel())
        .expect("search");
    assert_eq!(response.total_hits, 18);
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// Independent expected ordering: missing rows first or last, never reversed.
fn expected_order(direction: SortDirection, missing: MissingValuePosition) -> Vec<String> {
    let values: &[&str] = match direction {
        SortDirection::Asc => &CITY_ASC,
        SortDirection::Desc => &CITY_DESC,
    };
    let mut order: Vec<String> = Vec::new();
    // Missing rows first, then null rows; the reverse when missing rows go last.
    let missing_first = ["a0", "c4", "a1", "c5"];
    let missing_last = ["a1", "c5", "a0", "c4"];
    let missing_rows: &[&str] = match missing {
        MissingValuePosition::First => &missing_first,
        MissingValuePosition::Last => &missing_last,
    };
    if missing == MissingValuePosition::First {
        order.extend(missing_rows.iter().map(|key| (*key).to_owned()));
    }
    order.extend(values.iter().map(|key| (*key).to_owned()));
    if missing == MissingValuePosition::Last {
        order.extend(missing_rows.iter().map(|key| (*key).to_owned()));
    }
    order
}

fn expected_projection(key: &str) -> Vec<(String, FieldValues)> {
    let position = ROWS
        .iter()
        .position(|(row, _, _)| *row == key)
        .expect("row");
    let (_, batch, city) = ROWS[position];
    vec![
        (
            "body".to_owned(),
            FieldValues::Single(FieldValue::Text("common".to_owned())),
        ),
        (
            "category".to_owned(),
            FieldValues::Single(FieldValue::Keyword(batch.category().to_owned())),
        ),
        ("city".to_owned(), city.values()),
        (
            "n".to_owned(),
            FieldValues::Single(FieldValue::I64(position as i64)),
        ),
        (
            "stored_tag".to_owned(),
            FieldValues::Single(FieldValue::Keyword("stored".to_owned())),
        ),
        (
            "tags".to_owned(),
            FieldValues::Multi(vec![
                FieldValue::Keyword("one".to_owned()),
                FieldValue::Keyword("two".to_owned()),
            ]),
        ),
    ]
}

fn batch_of(key: &str) -> Batch {
    ROWS.iter()
        .find(|(row, _, _)| *row == key)
        .map(|(_, batch, _)| *batch)
        .expect("row")
}

fn assert_segment_dictionaries(
    snapshot: &ReaderSnapshot,
    guards: &[GuardedSegmentReader],
    map: &SnapshotKeywordOrdinals,
) {
    let segments = segment_ordinals(snapshot, guards, map);
    assert_eq!(segments.len(), 3);
    for segment in &segments {
        let first = segment.keys.first().cloned().unwrap_or_default();
        let batch = batch_of(&first);
        let terms: Vec<Vec<u8>> = batch
            .dictionary()
            .iter()
            .map(|term| term.as_bytes().to_vec())
            .collect();
        assert_eq!(segment.terms, terms, "dictionary for segment {first}");
        assert_eq!(
            segment.ranks,
            batch.ranks().to_vec(),
            "local→shared ranks for segment {first}"
        );
        // Integer comparison of translated ranks equals independent byte order.
        for (left, left_rank) in segment.terms.iter().zip(&segment.ranks) {
            for (right, right_rank) in segment.terms.iter().zip(&segment.ranks) {
                assert_eq!(
                    left.as_slice().cmp(right.as_slice()),
                    left_rank.cmp(right_rank),
                    "byte order vs rank order"
                );
            }
        }
    }
}

fn assert_full_view(index: &Index) {
    let snapshot = index.snapshot();
    assert_eq!(snapshot.document_count(), 18);
    assert_eq!(snapshot.segment_count(), 3);

    let guards = guards(&snapshot);
    let preparation = prepare_city(&snapshot, &guards);
    let map = ready_map(&preparation);
    assert_eq!(map.field_id(), CITY);
    assert_eq!(map.term_count(), 12);
    assert_segment_dictionaries(&snapshot, &guards, map);

    // Complete input-derived values, every row state, and every shared rank.
    let mut actual: BTreeMap<String, FieldValues> = BTreeMap::new();
    for guard in &guards {
        let reader = guard.reader();
        let columns = reader.open_columns().expect("columns").expect("section");
        let handle = columns
            .bind_keyword_ordinals(CITY)
            .expect("bind")
            .expect("ordinal column");
        let translation = map.bind_segment(guard).expect("segment map");
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let values = reader
                .column_value(CITY, doc_id)
                .expect("column value")
                .expect("city column");
            assert!(actual.insert(key.clone(), values).is_none());
            let (_, _, city) = ROWS.iter().find(|(row, _, _)| *row == key).expect("row");
            match (
                handle.doc_ordinal(doc_id).expect("ordinal"),
                city.expected_ordinal(),
            ) {
                (KeywordOrdinalValue::Value { ordinal, state }, Some(rank)) => {
                    assert_eq!(translation.translate(ordinal).expect("translate"), rank);
                    let expected_state = match city {
                        City::Value(_) => KeywordOrdinalState::Single,
                        _ => unreachable!(),
                    };
                    assert_eq!(state, expected_state);
                }
                (KeywordOrdinalValue::Missing, None) => assert_eq!(*city, City::Missing),
                (KeywordOrdinalValue::Null, None) => assert_eq!(*city, City::Null),
                (other, expected) => panic!("state mismatch for {key}: {other:?} vs {expected:?}"),
            }
        }
    }
    assert_eq!(actual, expected_city_values());

    // Exact ordinary sorted orders, K prefixes and complete projections.
    for (direction, missing) in [
        (SortDirection::Asc, MissingValuePosition::First),
        (SortDirection::Asc, MissingValuePosition::Last),
        (SortDirection::Desc, MissingValuePosition::First),
        (SortDirection::Desc, MissingValuePosition::Last),
    ] {
        let expected = expected_order(direction, missing);
        assert_eq!(sorted_hits(&snapshot, direction, missing, 100), expected);
        for limit in [1usize, 10, 18] {
            assert_eq!(
                sorted_hits(&snapshot, direction, missing, limit),
                expected[..limit].to_vec(),
                "K{limit} {direction:?} {missing:?}"
            );
        }
    }

    // Full projections on each hit.
    let mut field = SortField::new("city", SortDirection::Asc);
    field.missing = MissingValuePosition::First;
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(18).expect("top-k"));
    request.sort = Sort::new(vec![field]);
    request.projection = projection();
    let response = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel())
        .expect("search");
    for hit in &response.hits {
        assert_eq!(hit.fields, expected_projection(hit.key.as_str()));
        assert!(hit.score.unwrap_or(0.0).is_finite());
    }

    // Generic Boolean path matches the same exact ordering.
    let boolean = Query::And(vec![
        Query::Term {
            field: "body".to_owned(),
            value: FieldValue::Text("common".to_owned()),
        },
        Query::Range {
            field: "n".to_owned(),
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(17)),
        },
    ]);
    let mut request = UnifiedRequest::new(boolean, TopK::new(100).expect("top-k"));
    let mut field = SortField::new("city", SortDirection::Asc);
    field.missing = MissingValuePosition::First;
    request.sort = Sort::new(vec![field]);
    request.projection = projection();
    let response = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel())
        .expect("search");
    assert_eq!(
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect::<Vec<_>>(),
        expected_order(SortDirection::Asc, MissingValuePosition::First)
    );

    // Typed predicate membership from the frozen input table.
    let (missing, null, exists) = typed_membership();
    for (query, expected) in [
        (
            Query::Missing {
                field: "city".to_owned(),
            },
            missing,
        ),
        (
            Query::IsNull {
                field: "city".to_owned(),
            },
            null,
        ),
        (
            Query::Exists {
                field: "city".to_owned(),
            },
            exists,
        ),
    ] {
        let request = UnifiedRequest::new(query, TopK::new(100).expect("top-k"));
        let response =
            UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
                .search(&request, &Budgets::new(), &cancel())
                .expect("search");
        let actual: BTreeSet<String> = response
            .hits
            .iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
        assert_eq!(actual, expected);
        assert_eq!(response.total_hits, expected.len() as u64);
    }
}

// B1-I01 — frozen corpus in both real directory substrates.
#[test]
fn b1_i01_corpus_values_ordinals_and_exact_query_order() {
    let memory = build_corpus(memory_directory());
    assert_eq!(memory.generation(), Some(3));
    assert_full_view(&memory);

    let dir = TempDir::new("i01");
    let fs = build_corpus(fs_directory(dir.path()));
    assert_eq!(fs.generation(), Some(3));
    assert_full_view(&fs);
}

// B1-I02 — a genuinely fresh process reopens the committed generation.
#[test]
fn b1_i02_child_process_reopen_sees_the_same_view() {
    let dir = TempDir::new("i02");
    let index = build_corpus(fs_directory(dir.path()));
    assert_eq!(index.generation(), Some(3));
    drop(index);
    let status = std::process::Command::new(std::env::current_exe().expect("current exe"))
        .args(["--ignored", "--exact", "b1_i02_child_body"])
        .env("PERF06_B1_I02_DIR", dir.path())
        .status()
        .expect("spawn child");
    assert!(status.success(), "child process failed: {status:?}");
}

#[test]
#[ignore = "invoked only by b1_i02_child_process_reopen_sees_the_same_view"]
fn b1_i02_child_body() {
    let Ok(dir) = std::env::var("PERF06_B1_I02_DIR") else {
        return;
    };
    let index = Index::open_existing(
        fs_directory(std::path::Path::new(&dir)),
        schema(),
        registry(),
    )
    .expect("open existing");
    assert_eq!(index.generation(), Some(3));
    assert_full_view(&index);
    println!("PERF06_B1_I02_CHILD_PASS");
}

// B1-I03 — append, delete and compaction renumber only new snapshots.
#[test]
fn b1_i03_append_delete_compact_and_held_pits() {
    let dir = TempDir::new("i03");
    let index = build_corpus(fs_directory(dir.path()));
    // The frozen three-batch corpus produces three segments at generation 3.
    let g3_objects = reachable_immutable(dir.path());
    assert_eq!(g3_objects.len(), 5, "g3 manifest + 3 segments + state");
    let old_pit = index.pin().expect("pin");
    let old_snapshot = Arc::clone(old_pit.snapshot());
    assert_eq!(old_snapshot.generation(), Some(3));
    assert_eq!(old_snapshot.document_count(), 18);
    assert_eq!(old_snapshot.segment_count(), 3);
    let old_guards = guards(&old_snapshot);
    let old_preparation = prepare_city(&old_snapshot, &old_guards);
    let old_map = Arc::clone(ready_map(&old_preparation));
    assert_eq!(shared_city_rank(&old_guards, &old_map, "b0"), Some(3));
    let g3_live = live_keys(&old_snapshot);
    assert_eq!(g3_live.len(), 18);

    let mut writer = index.writer().expect("writer");
    writer
        .insert(document_with("d0", Batch::A, City::Value("Chicago"), 18))
        .expect("insert");
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);

    let g4_objects = {
        let after_append = reopen(dir.path());
        assert_eq!(after_append.generation(), Some(4));
        reachable_immutable(dir.path())
    };
    assert_eq!(g4_objects.len(), 6, "g4 manifest + 4 segments + state");
    for (path, bytes) in &g3_objects {
        assert_eq!(
            std::fs::read(dir.path().join(path)).expect("g3 object"),
            *bytes,
            "g3 immutable object {path} changed after the append"
        );
    }
    let appended = reopen(dir.path()).pin().expect("pin");
    let appended_snapshot = Arc::clone(appended.snapshot());
    assert_eq!(appended_snapshot.generation(), Some(4));
    assert_eq!(appended_snapshot.document_count(), 19);
    assert_eq!(appended_snapshot.segment_count(), 4);
    let appended_guards = guards(&appended_snapshot);
    let appended_preparation = prepare_city(&appended_snapshot, &appended_guards);
    let appended_map = ready_map(&appended_preparation);
    assert_eq!(appended_map.term_count(), 13);
    // "Chicago" sorts between "Boston" and "Dallas", so later ranks shift.
    assert_eq!(
        shared_city_rank(&appended_guards, appended_map, "d0"),
        Some(4)
    );
    assert_eq!(
        shared_city_rank(&appended_guards, appended_map, "a4"),
        Some(6)
    );
    // The held snapshot keeps its own numbers.
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a4"), Some(5));

    // Delete `b0` (Boston) and compact.
    let index = reopen(dir.path());
    let mut writer = index.writer().expect("writer");
    writer
        .apply(MutationRequest::delete(
            DocumentKey::new("b0").expect("key"),
        ))
        .expect("delete");
    assert_eq!(writer.commit().expect("commit").generation, 5);
    drop(writer);
    // G08: before compaction the physical dictionary still contains the
    // deleted-only term, while live results exclude the deleted document.
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(5));
    assert_eq!(index.snapshot().document_count(), 18);
    assert_eq!(index.snapshot().segment_count(), 4, "no compaction yet");
    {
        let snapshot = index.snapshot();
        assert_eq!(snapshot.document_count(), 18);
        let guards = guards(&snapshot);
        let preparation = prepare_city(&snapshot, &guards);
        let map = ready_map(&preparation);
        assert_eq!(
            map.term_count(),
            13,
            "the deleted-only Boston term is still physical"
        );
        assert_eq!(shared_city_rank(&guards, map, "b0"), Some(3));
        let live = live_keys(&snapshot);
        assert!(!live.contains(&"b0".to_owned()), "b0 is not live");
        assert!(live.contains(&"b1".to_owned()));
        // Physical dictionaries are visible for every retained segment.
        let segments = segment_ordinals(&snapshot, &guards, map);
        assert!(segments.iter().any(|segment| {
            segment
                .terms
                .iter()
                .any(|term| term.as_slice() == b"Boston")
        }));
    }
    let mut writer = index.writer().expect("writer");
    let outcome = writer.compact().expect("compact");
    assert_eq!(outcome.documents, 18);
    assert!(!outcome.no_op);
    drop(writer);

    let index = reopen(dir.path());
    for (path, bytes) in g3_objects.iter().chain(g4_objects.iter()) {
        assert_eq!(
            std::fs::read(dir.path().join(path))
                .unwrap_or_else(|error| panic!("immutable {path} disappeared: {error}")),
            *bytes,
            "immutable object {path} changed after compaction"
        );
    }
    let current = index.pin().expect("pin");
    let current_snapshot = Arc::clone(current.snapshot());
    assert_eq!(current_snapshot.generation(), Some(6));
    assert_eq!(current_snapshot.segment_count(), 1);
    assert_eq!(current_snapshot.document_count(), 18);
    let current_guards = guards(&current_snapshot);
    let current_preparation = prepare_city(&current_snapshot, &current_guards);
    let current_map = ready_map(&current_preparation);
    // Boston is a deleted-only term before compaction; it is gone afterwards.
    assert_eq!(current_map.term_count(), 12);
    assert!(shared_city_rank(&current_guards, current_map, "b0").is_none());
    assert_eq!(
        shared_city_rank(&current_guards, current_map, "a4"),
        Some(5)
    );

    // Held views remain exactly what they were, including complete key sets.
    assert_eq!(shared_city_rank(&old_guards, &old_map, "b0"), Some(3));
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a4"), Some(5));
    assert_eq!(live_keys(&old_snapshot), g3_live);
    assert_eq!(live_keys(&appended_snapshot).len(), 19);
    assert_eq!(live_keys(&current_snapshot), {
        let mut keys = g3_live.clone();
        keys.retain(|key| key != "b0");
        keys.push("d0".to_owned());
        keys.sort();
        keys
    });
}

// B1-U14 — a real commit rejects a noncanonical zero-element multi before any
// durable publication.
#[test]
fn b1_u14_real_writer_rejects_zero_multi_count() {
    use quervant_core::contract::document::{Cardinality, Document};
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use quervant_core::contract::value::FieldType;
    use quervant_core::index::IndexError;
    use quervant_core::segment::SegmentError;

    let schema = Schema::new(
        vec![FieldDefinition::new(
            "city",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(false, false, true),
        )],
        None,
    )
    .expect("schema");
    let dir = TempDir::new("u14");
    let index =
        Index::create(fs_directory(dir.path()), schema.clone(), registry()).expect("create");
    {
        let mut writer = index.writer().expect("writer");
        let mut doc = Document::new(DocumentKey::new("k0").expect("key"));
        doc.insert(
            "city",
            FieldValues::Single(FieldValue::Keyword("alpha".to_owned())),
        )
        .expect("city");
        writer.insert(doc).expect("insert");
        assert_eq!(writer.commit().expect("commit").generation, 1);
    }
    let before = directory_inventory(dir.path());

    let index =
        Index::open_existing(fs_directory(dir.path()), schema.clone(), registry()).expect("reopen");
    let mut writer = index.writer().expect("writer");
    let mut document = Document::new(DocumentKey::new("k1").expect("key"));
    // The public schema still admits the noncanonical zero-element multi.
    document
        .insert("city", FieldValues::Multi(Vec::new()))
        .expect("city");
    writer.insert(document).expect("pending insert is accepted");
    let error = writer.commit().expect_err("commit must reject Multi0");
    match error {
        IndexError::Segment(SegmentError::InvalidColumnGeometry { detail }) => {
            assert_eq!(detail, "zero multi count");
        }
        other => panic!("unexpected error: {other:?}"),
    }
    drop(writer);

    // Nothing durable changed, and a fresh reader still opens generation 1.
    let after = directory_inventory(dir.path());
    assert_eq!(before, after, "a rejected commit must not publish anything");
    let reopened =
        Index::open_existing(fs_directory(dir.path()), schema, registry()).expect("reopen");
    assert_eq!(reopened.generation(), Some(1));
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.segment_count(), 1);
    let guard = snapshot.open_segment_reader(0).expect("guard");
    assert_eq!(
        guard.reader().column_value(0, 0).expect("value"),
        Some(FieldValues::Single(FieldValue::Keyword("alpha".to_owned())))
    );
}

// B1-I06 — the exact large-dictionary compaction allocation boundary.
#[test]
fn b1_i06_exact_large_dictionary_allocation_boundary() {
    use quervant_core::contract::document::{Cardinality, Document};
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use quervant_core::contract::value::FieldType;

    let schema = Schema::new(
        vec![FieldDefinition::new(
            "city",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::new(false, false, true),
        )],
        None,
    )
    .expect("schema");
    let dir = TempDir::new("i06");
    let index =
        Index::create(fs_directory(dir.path()), schema.clone(), registry()).expect("create");
    for batch in 0..2usize {
        let mut writer = index.writer().expect("writer");
        for position in batch * 8..(batch + 1) * 8 {
            let value = format!("{position:02}{}", "x".repeat(5998));
            assert_eq!(value.len(), 6_000);
            let mut doc = Document::new(DocumentKey::new(format!("p{position:02}")).expect("key"));
            doc.insert("city", FieldValues::Single(FieldValue::Keyword(value)))
                .expect("city");
            writer.insert(doc).expect("insert");
        }
        assert_eq!(
            writer.commit().expect("commit").generation,
            (batch + 1) as u64
        );
    }
    drop(index);

    // Independent size formula: 6+46+36+16+17*3+96000+16+16 = 96187.
    const EXPECTED_COLUMNS: u64 = 96_187;
    let failure_dir = TempDir::new("i06-fail");
    copy_tree(dir.path(), failure_dir.path());
    let limits = IndexLimits::default()
        .with_segment_limits(SegmentLimits::default().with_max_single_allocation(65_536));
    let index = Index::open_with_limits(
        fs_directory(failure_dir.path()),
        schema.clone(),
        registry(),
        limits,
    )
    .expect("open with limits");
    let mut writer = index.writer().expect("writer");
    match writer.compact().expect_err("allocation must fail") {
        quervant_core::index::IndexError::Segment(SegmentError::LimitExceeded {
            limit,
            requested,
        }) => {
            assert_eq!(limit, 65_536);
            assert_eq!(requested, EXPECTED_COLUMNS);
        }
        other => panic!("unexpected error: {other:?}"),
    }
    drop(writer);
    let reopened =
        Index::open_existing(fs_directory(failure_dir.path()), schema.clone(), registry())
            .expect("reopen");
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(reopened.snapshot().segments().len(), 2);

    let success_dir = TempDir::new("i06-ok");
    copy_tree(dir.path(), success_dir.path());
    let limits = IndexLimits::default()
        .with_segment_limits(SegmentLimits::default().with_max_single_allocation(EXPECTED_COLUMNS));
    let index = Index::open_with_limits(
        fs_directory(success_dir.path()),
        schema.clone(),
        registry(),
        limits,
    )
    .expect("open with limits");
    let mut writer = index.writer().expect("writer");
    assert_eq!(writer.compact().expect("exact boundary").generation, 3);
    drop(writer);
    let index = Index::open_existing(fs_directory(success_dir.path()), schema.clone(), registry())
        .expect("reopen");
    let snapshot = index.snapshot();
    assert_eq!(snapshot.segment_count(), 1);
    let guard = snapshot.open_segment_reader(0).expect("guard");
    let columns_body = parse_container(guard.reader().bytes(), &SegmentLimits::default())
        .expect("container")
        .body(SectionKind::Columns)
        .expect("columns body")
        .to_vec();
    assert_eq!(columns_body.len() as u64, EXPECTED_COLUMNS);
    let columns = guard
        .reader()
        .open_columns()
        .expect("columns")
        .expect("section");
    // The fixture schema has exactly one field, so its canonical id is 0.
    let handle = columns
        .bind_keyword_ordinals(0)
        .expect("bind")
        .expect("ordinal");
    assert_eq!(handle.dictionary_len(), 16);
    let guards = guards(&snapshot);
    let preparation = snapshot
        .prepare_keyword_ordinals(0, &guards, &cancel())
        .expect("prepare");
    let map = match &preparation {
        quervant_core::index::KeywordOrdinalPreparation::Ready(map) => map,
        other => panic!("expected a ready map, got {other:?}"),
    };
    assert_eq!(map.term_count(), 16);
}

/// Byte-exact inventory of every file under an index root, keyed by relative path.
fn directory_inventory(root: &std::path::Path) -> BTreeMap<String, Vec<u8>> {
    let mut inventory = BTreeMap::new();
    for path in walkdir(root) {
        if path.is_dir() {
            continue;
        }
        let relative = path
            .strip_prefix(root)
            .expect("relative")
            .to_string_lossy()
            .into_owned();
        inventory.insert(relative, std::fs::read(&path).expect("read object"));
    }
    inventory
}

/// Live document keys from an ordinary `MatchAll` search.
fn live_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    let request = UnifiedRequest::new(Query::MatchAll, TopK::new(1_000).expect("top-k"));
    let response = UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &cancel())
        .expect("search");
    let mut keys: Vec<String> = response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    keys.sort();
    keys
}

fn copy_tree(from: &std::path::Path, to: &std::path::Path) {
    for entry in walkdir(from) {
        let relative = entry.strip_prefix(from).expect("relative");
        let target = to.join(relative);
        if entry.is_dir() {
            std::fs::create_dir_all(&target).expect("dir");
        } else {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent).expect("parent");
            }
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
            for entry in std::fs::read_dir(&path).expect("read dir") {
                stack.push(entry.expect("entry").path());
            }
        }
    }
    out
}

// B1-I05 — aggregation over the public batch executor plus nonstored reconstruction.
#[test]
fn b1_i05_public_aggregation_and_nonstored_reconstruction() {
    let index = build_corpus(memory_directory());
    let snapshot = index.snapshot();
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
        Aggregation {
            group_by: Some(GroupBy::new(vec![GroupKey::Field("tags".into())])),
            aggregates: vec![Aggregate::count()],
            ..Aggregation::new()
        },
    ];
    let queries: Vec<QueryRequest> = definitions
        .into_iter()
        .map(|aggregation| {
            let mut request = QueryRequest::new(Query::MatchAll);
            request.top_k = TopK::new(100).expect("top-k");
            request.projection = projection();
            request.aggregation = Some(aggregation);
            request
        })
        .collect();
    let batch = BatchQueryRequest::new(queries, None, batch_budget());
    let response = execute_batch(
        snapshot.as_ref(),
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
    )
    .expect("aggregate batch envelope");

    for slot_index in 0..3usize {
        match response.slot(slot_index) {
            Some(PerQueryOutcome::Success(slot)) => {
                assert_eq!(slot.total_hits, 18);
                assert_eq!(slot.hits.len(), 18);
                for hit in &slot.hits {
                    assert_eq!(hit.fields, expected_projection(hit.key.as_str()));
                }
            }
            other => panic!("slot {slot_index} failed: {other:?}"),
        }
    }

    let Some(PerQueryOutcome::Success(slot0)) = response.slot(0) else {
        panic!("slot0 not success");
    };
    let aggregation = slot0.aggregation.as_ref().expect("aggregation");
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for group in &aggregation.groups {
        let AggregationGroupValue::Value(FieldValue::Keyword(category)) =
            group.components.first().expect("component")
        else {
            panic!("unexpected group");
        };
        assert_eq!(group.metrics, vec![AggregationMetricValue::Count(6)]);
        counts.insert(category.clone(), 6);
    }
    assert_eq!(
        counts.keys().cloned().collect::<BTreeSet<_>>(),
        BTreeSet::from([
            "type-a".to_owned(),
            "type-b".to_owned(),
            "type-c".to_owned()
        ])
    );

    let Some(PerQueryOutcome::Success(slot1)) = response.slot(1) else {
        panic!("slot1 not success");
    };
    let aggregation = slot1.aggregation.as_ref().expect("aggregation");
    assert_eq!(aggregation.groups.len(), 1);
    assert!(aggregation.groups[0].components.is_empty());
    assert_eq!(
        aggregation.groups[0].metrics,
        vec![
            AggregationMetricValue::Sum(NumericAggregate::Signed(153)),
            AggregationMetricValue::ExactDistinct(18),
        ]
    );

    let Some(PerQueryOutcome::Success(slot2)) = response.slot(2) else {
        panic!("slot2 not success");
    };
    let aggregation = slot2.aggregation.as_ref().expect("aggregation");
    let mut tag_counts: BTreeMap<String, u64> = BTreeMap::new();
    for group in &aggregation.groups {
        let AggregationGroupValue::Value(FieldValue::Keyword(tag)) =
            group.components.first().expect("component")
        else {
            panic!("unexpected group");
        };
        assert_eq!(group.metrics, vec![AggregationMetricValue::Count(18)]);
        tag_counts.insert(tag.clone(), 18);
    }
    assert_eq!(
        tag_counts.keys().cloned().collect::<BTreeSet<_>>(),
        BTreeSet::from(["one".to_owned(), "two".to_owned()])
    );

    // --- Nonstored-city reconstruction workload (separate schema/index) ---
    let dir = TempDir::new("i05-nonstored");
    let index = Index::create(
        fs_directory(dir.path()),
        schema_nonstored_city(),
        registry(),
    )
    .expect("create");
    for batch in 0..3usize {
        let mut writer = index.writer().expect("writer");
        for (key, _, city) in &ROWS[batch * 6..(batch + 1) * 6] {
            let position = ROWS.iter().position(|(row, _, _)| row == key).expect("row");
            writer.insert(document_at(position, *city)).expect("insert");
        }
        writer.commit().expect("commit");
    }
    let index = Index::open_existing(
        fs_directory(dir.path()),
        schema_nonstored_city(),
        registry(),
    )
    .expect("reopen nonstored corpus");
    let old_pit = index.pin().expect("pin");
    let old_snapshot = Arc::clone(old_pit.snapshot());
    let old_guards = guards(&old_snapshot);
    let old_preparation = prepare_city(&old_snapshot, &old_guards);
    let old_map = Arc::clone(ready_map(&old_preparation));
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a3"), Some(2));

    // Upsert a3 with only `city` replaced.
    let mut writer = index.writer().expect("writer");
    writer
        .apply(MutationRequest::upsert(document_with(
            "a3",
            Batch::A,
            City::Value("Athens"),
            3,
        )))
        .expect("upsert");
    writer.commit().expect("commit");
    drop(writer);
    let mut writer = index.writer().expect("writer");
    assert_eq!(writer.compact().expect("compact").documents, 18);
    drop(writer);

    let index = Index::open_existing(
        fs_directory(dir.path()),
        schema_nonstored_city(),
        registry(),
    )
    .expect("reopen");
    let snapshot = index.snapshot();
    let guards = guards(&snapshot);
    let preparation = prepare_city(&snapshot, &guards);
    let map = ready_map(&preparation);
    let expected_terms: Vec<String> = vec![
        "", "\0", "Athens", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}",
        "é", "😀",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    let segments = segment_ordinals(&snapshot, &guards, map);
    let terms: Vec<String> = segments[0]
        .terms
        .iter()
        .map(|term| String::from_utf8(term.clone()).expect("utf8"))
        .collect();
    assert_eq!(terms, expected_terms);
    assert_eq!(map.term_count(), 13);
    assert_eq!(shared_city_rank(&guards, map, "a3"), Some(2));
    assert_eq!(shared_city_rank(&guards, map, "a4"), Some(6));
    // The held pre-mutation view still sees the old physical dictionary.
    assert_eq!(shared_city_rank(&old_guards, &old_map, "a3"), Some(2));

    // Nonstored city values survive through the real column accessors.
    let mut cities = BTreeMap::new();
    for guard in &guards {
        let reader = guard.reader();
        let columns = reader.open_columns().expect("columns").expect("section");
        let handle = columns
            .bind_keyword_ordinals(CITY)
            .expect("bind")
            .expect("ordinal");
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let values = reader
                .column_value(CITY, doc_id)
                .expect("column value")
                .expect("city column");
            let term = match handle.doc_ordinal(doc_id).expect("ordinal") {
                KeywordOrdinalValue::Value { ordinal, .. } => {
                    String::from_utf8(handle.dictionary_term(ordinal).expect("term").to_vec())
                        .expect("utf8")
                }
                KeywordOrdinalValue::Missing => "missing".to_owned(),
                KeywordOrdinalValue::Null => "null".to_owned(),
            };
            cities.insert(key, (values, term));
        }
    }
    assert_eq!(cities.len(), 18);
    assert_eq!(
        cities.get("a3").map(|(_, term)| term.clone()),
        Some("Athens".to_owned())
    );
    assert_eq!(
        cities.get("a0").map(|(values, _)| values.clone()),
        Some(FieldValues::Absent)
    );
    assert_eq!(
        cities.get("a1").map(|(values, _)| values.clone()),
        Some(FieldValues::ExplicitNull)
    );
}

// B1-I08 — public PIT-bound cursor pagination over repeated cross-segment values.
#[test]
fn b1_i08_pinned_cursor_pagination_and_negative_outcomes() {
    let index = build_corpus(memory_directory());
    let pit = index.pin().expect("pin");
    let snapshot = Arc::clone(pit.snapshot());
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        let expected = expected_order(direction, MissingValuePosition::Last);
        let mut field = SortField::new("city", direction);
        field.missing = MissingValuePosition::Last;
        let sort = Sort::new(vec![field]);
        let mut request = QueryRequest::new(Query::MatchAll);
        request.sort = sort.clone();
        request.top_k = TopK::new(5).expect("page size");
        request.projection = projection();
        let mut collected: Vec<String> = Vec::new();
        let mut page_lengths = Vec::new();
        let mut cursors = Vec::new();
        for page in 0..4usize {
            let batch = BatchQueryRequest::new(
                vec![request.clone()],
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
                Timestamp::from_micros(1_000),
                Timestamp::from_micros(10_000),
            )
            .expect("pinned envelope");
            let Some(PerQueryOutcome::Success(slot)) = response.slot(0) else {
                panic!("page {page} failed: {:?}", response.slot(0));
            };
            assert_eq!(slot.total_hits, 18);
            page_lengths.push(slot.hits.len());
            let keys: Vec<String> = slot
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            for hit in &slot.hits {
                assert_eq!(hit.fields, expected_projection(hit.key.as_str()));
            }
            match &slot.next_cursor {
                Some(cursor) => {
                    assert_eq!(cursor.pit(), pit.id());
                    assert_eq!(cursor.last_key().as_str(), keys.last().expect("last key"));
                    assert!(
                        cursor
                            .validate(pit.id(), &sort, Timestamp::from_micros(1_000))
                            .is_ok()
                    );
                    cursors.push(cursor.clone());
                    collected.extend(keys);
                    request.cursor = Some(cursor.clone());
                }
                None => {
                    assert_eq!(page, 3, "only the final page is exhausted");
                    collected.extend(keys);
                }
            }
        }
        assert_eq!(page_lengths, vec![5, 5, 5, 3]);
        assert_eq!(collected, expected);
        assert_eq!(cursors.len(), 3);
        assert_eq!(snapshot.binding_id(), pit.snapshot().binding_id());
    }

    // Negative: a cursor is bound to its snapshot instance.
    let mut field = SortField::new("city", SortDirection::Asc);
    field.missing = MissingValuePosition::Last;
    let sort = Sort::new(vec![field]);
    let mut request = QueryRequest::new(Query::MatchAll);
    request.sort = sort.clone();
    request.top_k = TopK::new(5).expect("page size");
    request.projection = projection();
    let batch = BatchQueryRequest::new(
        vec![request.clone()],
        Some(pit.id().clone()),
        batch_budget(),
    );
    let first = execute_batch_pinned(
        &pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
        Timestamp::from_micros(1_000),
        Timestamp::from_micros(10_000),
    )
    .expect("first page");
    let Some(PerQueryOutcome::Success(slot)) = first.slot(0) else {
        panic!("first page failed");
    };
    let cursor = slot.next_cursor.clone().expect("cursor");

    let other_pit = index.pin().expect("second pin");
    assert_eq!(
        other_pit.snapshot().generation(),
        pit.snapshot().generation()
    );
    assert_ne!(other_pit.snapshot().binding_id(), snapshot.binding_id());

    let mut mismatched = request.clone();
    mismatched.cursor = Some(cursor.clone());
    let batch = BatchQueryRequest::new(
        vec![mismatched],
        Some(other_pit.id().clone()),
        batch_budget(),
    );
    let response = execute_batch_pinned(
        &other_pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
        Timestamp::from_micros(1_000),
        Timestamp::from_micros(10_000),
    )
    .expect("envelope");
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::InvalidQuery(
            InvalidQueryReason::CursorPitMismatch
        )))
    );

    let batch = BatchQueryRequest::new(
        vec![request.clone()],
        Some(pit.id().clone()),
        batch_budget(),
    );
    assert!(matches!(
        execute_batch_pinned(
            &other_pit,
            &schema(),
            &registry(),
            SearchLimits::default(),
            &batch,
            &batch_policy(),
            &CapabilitySet::new(),
            &cancel(),
            Timestamp::from_micros(1_000),
            Timestamp::from_micros(10_000),
        ),
        Err(SearchError::Query(QueryError::InvalidBatch(
            InvalidBatchReason::ConflictingPit
        )))
    ));

    let mut expired = request.clone();
    expired.cursor = Some(cursor);
    let batch = BatchQueryRequest::new(vec![expired], Some(pit.id().clone()), batch_budget());
    let response = execute_batch_pinned(
        &pit,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
        Timestamp::from_micros(10_000),
        Timestamp::from_micros(20_000),
    )
    .expect("envelope");
    assert_eq!(
        response.slot(0),
        Some(&PerQueryOutcome::Failure(QueryError::ExpiredCursor))
    );
}

// ---------------------------------------------------------------------------
// F1-07 / B1-I04 — genuine historical fixture: g3 -> g4 -> g5 with full proof.
// ---------------------------------------------------------------------------

/// Appended `type-d` corpus rows (never part of the frozen first 18).
const APPENDED: [(&str, City, i64); 2] = [
    ("d0", City::Value("Chicago"), 18),
    ("d1", City::Value("Seattle"), 19),
];

/// Build an appended `type-d` document.
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

/// Independent expected `city` ordering over an arbitrary row set.
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
    let mut order: Vec<String> = Vec::new();
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

fn corpus_rows(extra: &[(&str, City, i64)]) -> Vec<(String, City)> {
    let mut rows: Vec<(String, City)> = ROWS
        .iter()
        .map(|(key, _, city)| ((*key).to_owned(), *city))
        .collect();
    rows.extend(
        extra
            .iter()
            .map(|(key, city, _)| ((*key).to_owned(), *city)),
    );
    rows
}

fn corpus_values(extra: &[(&str, City, i64)]) -> BTreeMap<String, FieldValues> {
    let mut values: BTreeMap<String, FieldValues> = ROWS
        .iter()
        .map(|(key, _, city)| ((*key).to_owned(), city.values()))
        .collect();
    values.extend(
        extra
            .iter()
            .map(|(key, city, _)| ((*key).to_owned(), city.values())),
    );
    values
}

/// Immutable objects reachable from `CURRENT` (manifest, segments, state).
fn reachable_immutable(root: &std::path::Path) -> BTreeMap<String, Vec<u8>> {
    let current = std::fs::read(root.join("index/CURRENT")).expect("CURRENT");
    let pointer = quervant_core::index::CurrentPointer::parse(&current).expect("pointer");
    let manifest_key = pointer.manifest_key().as_str().to_owned();
    let manifest_bytes = std::fs::read(root.join(&manifest_key)).expect("manifest");
    let manifest =
        quervant_core::segment::Manifest::decode(&manifest_bytes, &SegmentLimits::default())
            .expect("manifest decode");
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

/// Full ordered/state/rank assertions for one exact snapshot view.
fn assert_city_view(
    snapshot: &ReaderSnapshot,
    rows: &[(String, City)],
    expected_terms: &[&str],
) -> BTreeMap<String, FieldValues> {
    let guards = guards(snapshot);
    let preparation = prepare_city(snapshot, &guards);
    let map = ready_map(&preparation);
    assert_eq!(map.term_count(), expected_terms.len() as u64);
    let segments = segment_ordinals(snapshot, &guards, map);
    assert_eq!(segments.len(), snapshot.segment_count());
    let all_terms: BTreeSet<Vec<u8>> = segments
        .iter()
        .flat_map(|segment| segment.terms.iter().cloned())
        .collect();
    let expected: BTreeSet<Vec<u8>> = expected_terms
        .iter()
        .map(|term| term.as_bytes().to_vec())
        .collect();
    assert_eq!(all_terms, expected);

    let mut values: BTreeMap<String, FieldValues> = BTreeMap::new();
    for guard in &guards {
        let reader = guard.reader();
        let columns = reader.open_columns().expect("columns").expect("section");
        let handle = columns
            .bind_keyword_ordinals(CITY)
            .expect("bind")
            .expect("ordinal");
        let translation = map.bind_segment(guard).expect("segment map");
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let value = reader
                .column_value(CITY, doc_id)
                .expect("value")
                .expect("city column");
            values.insert(key.clone(), value);
            let city = rows
                .iter()
                .find(|(row, _)| *row == key)
                .map(|(_, city)| *city)
                .expect("row");
            // Expected ranks come from the literal term table for *this* view,
            // not from a fixed 18-row ranking.
            let expected_rank = match city {
                City::Value(value) => Some(
                    expected_terms
                        .iter()
                        .position(|term| term.as_bytes() == value.as_bytes())
                        .expect("term in the expected table") as u64,
                ),
                City::Missing | City::Null => None,
            };
            match (handle.doc_ordinal(doc_id).expect("ordinal"), expected_rank) {
                (KeywordOrdinalValue::Value { ordinal, state }, Some(rank)) => {
                    assert_eq!(translation.translate(ordinal).expect("translate"), rank);
                    assert_eq!(state, KeywordOrdinalState::Single);
                }
                (KeywordOrdinalValue::Missing, None) => assert_eq!(city, City::Missing),
                (KeywordOrdinalValue::Null, None) => assert_eq!(city, City::Null),
                (other, wanted) => panic!("{key}: {other:?} vs {wanted:?}"),
            }
        }
    }
    let expected_values: BTreeMap<String, FieldValues> = rows
        .iter()
        .map(|(key, city)| (key.clone(), city.values()))
        .collect();
    assert_eq!(values, expected_values);

    for direction in [SortDirection::Asc, SortDirection::Desc] {
        for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
            let expected = order_for(rows, direction, missing);
            let mut field = SortField::new("city", direction);
            field.missing = missing;
            let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(1_000).expect("k"));
            request.sort = Sort::new(vec![field]);
            request.projection = projection();
            let response =
                UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
                    .search(&request, &Budgets::new(), &cancel())
                    .expect("search");
            assert_eq!(response.total_hits, rows.len() as u64);
            let actual: Vec<String> = response
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect();
            assert_eq!(actual, expected, "{direction:?} {missing:?}");
            for hit in &response.hits {
                assert_eq!(hit.fields.len(), 6, "complete projection");
            }
            for limit in [1usize, 5, rows.len()] {
                let mut request =
                    UnifiedRequest::new(Query::MatchAll, TopK::new(limit).expect("k"));
                let mut field = SortField::new("city", direction);
                field.missing = missing;
                request.sort = Sort::new(vec![field]);
                request.projection = projection();
                let response =
                    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
                        .search(&request, &Budgets::new(), &cancel())
                        .expect("search");
                assert_eq!(
                    response
                        .hits
                        .iter()
                        .map(|hit| hit.key.as_str().to_owned())
                        .collect::<Vec<_>>(),
                    expected[..limit].to_vec()
                );
            }
        }
    }
    values
}

/// Values, complete orders and the sticky legacy outcome for a v1-only view.
fn assert_legacy_city_view(snapshot: &ReaderSnapshot, rows: &[(String, City)]) {
    let guards = guards(snapshot);
    assert_eq!(
        prepare_city(snapshot, &guards).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    let mut values: BTreeMap<String, FieldValues> = BTreeMap::new();
    for guard in &guards {
        let reader = guard.reader();
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            values.insert(
                keys[doc_id as usize].as_str().to_owned(),
                reader
                    .column_value(CITY, doc_id)
                    .expect("value")
                    .expect("city column"),
            );
        }
    }
    let expected_values: BTreeMap<String, FieldValues> = rows
        .iter()
        .map(|(key, city)| (key.clone(), city.values()))
        .collect();
    assert_eq!(values, expected_values);
    for direction in [SortDirection::Asc, SortDirection::Desc] {
        for missing in [MissingValuePosition::First, MissingValuePosition::Last] {
            let expected = order_for(rows, direction, missing);
            let mut field = SortField::new("city", direction);
            field.missing = missing;
            let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(1_000).expect("k"));
            request.sort = Sort::new(vec![field]);
            request.projection = projection();
            let response =
                UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
                    .search(&request, &Budgets::new(), &cancel())
                    .expect("search");
            assert_eq!(response.total_hits, rows.len() as u64);
            assert_eq!(
                response
                    .hits
                    .iter()
                    .map(|hit| hit.key.as_str().to_owned())
                    .collect::<Vec<_>>(),
                expected
            );
            for hit in &response.hits {
                assert_eq!(hit.fields.len(), 6, "complete projection");
            }
        }
    }
}

/// Aggregate expectations for one row set.
fn assert_aggregates(
    snapshot: &ReaderSnapshot,
    category_counts: &[(&str, u64)],
    n_sum: i128,
    n_distinct: u64,
    tag_count: u64,
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
        Aggregation {
            group_by: Some(GroupBy::new(vec![GroupKey::Field("tags".into())])),
            aggregates: vec![Aggregate::count()],
            ..Aggregation::new()
        },
    ];
    let queries: Vec<QueryRequest> = definitions
        .into_iter()
        .map(|aggregation| {
            let mut request = QueryRequest::new(Query::MatchAll);
            request.top_k = TopK::new(1_000).expect("top-k");
            request.projection = projection();
            request.aggregation = Some(aggregation);
            request
        })
        .collect();
    let batch = BatchQueryRequest::new(queries, None, batch_budget());
    let response = execute_batch(
        snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
        &batch,
        &batch_policy(),
        &CapabilitySet::new(),
        &cancel(),
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
    assert_eq!(aggregation.groups.len(), 1);
    assert_eq!(
        aggregation.groups[0].metrics,
        vec![
            AggregationMetricValue::Sum(NumericAggregate::Signed(n_sum)),
            AggregationMetricValue::ExactDistinct(n_distinct),
        ]
    );

    let Some(PerQueryOutcome::Success(slot2)) = response.slot(2) else {
        panic!("slot2 failed");
    };
    let aggregation = slot2.aggregation.as_ref().expect("aggregation");
    let mut tags: BTreeMap<String, u64> = BTreeMap::new();
    for group in &aggregation.groups {
        let AggregationGroupValue::Value(FieldValue::Keyword(tag)) =
            group.components.first().expect("component")
        else {
            panic!("unexpected group");
        };
        let AggregationMetricValue::Count(count) = group.metrics[0] else {
            panic!("unexpected metric");
        };
        tags.insert(tag.clone(), count);
    }
    assert_eq!(
        tags,
        BTreeMap::from([("one".to_owned(), tag_count), ("two".to_owned(), tag_count)])
    );
}

const HISTORICAL_TERMS_20: [&str; 13] = [
    "", "\0", "Austin", "Boston", "Chicago", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é",
    "😀",
];

// B1-I04 — the genuine historical pre-B1 fixture lifecycle.
#[test]
fn b1_i04_historical_fixture_append_compact_and_reopen() {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/index/perf06_b1_columns_v1");
    verify_fixture_package(&source);

    let dir = TempDir::new("i04");
    copy_tree(&source.join("index"), &dir.path().join("index"));
    let index = Index::open_existing(fs_directory(dir.path()), schema(), registry())
        .expect("open generation 3");
    assert_eq!(index.generation(), Some(3));

    // --- g3: genuine legacy COLUMNS v1 ---
    let g3_objects = reachable_immutable(dir.path());
    assert_eq!(
        g3_objects.len(),
        5,
        "manifest + 3 segments + state, got {:?}",
        g3_objects.keys().collect::<Vec<_>>()
    );
    let g3_pit = index.pin().expect("pin");
    let g3_snapshot = Arc::clone(g3_pit.snapshot());
    assert_eq!(g3_snapshot.document_count(), 18);
    assert_eq!(g3_snapshot.segment_count(), 3);
    for segment_index in 0..3 {
        let guard = g3_snapshot
            .open_segment_reader(segment_index)
            .expect("guard");
        let reader = guard.reader();
        assert!(
            !reader
                .required_features()
                .iter()
                .any(|(id, _)| *id == FEATURE_KEYWORD_ORDINALS),
            "historical segments must not require keyword ordinals"
        );
        let body = parse_container(reader.bytes(), &SegmentLimits::default())
            .expect("container")
            .body(SectionKind::Columns)
            .expect("columns section");
        assert_eq!(&body[..2], &1u16.to_le_bytes(), "genuine COLUMNS v1");
    }
    assert_eq!(
        prepare_city(&g3_snapshot, &guards(&g3_snapshot)).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    assert_legacy_city_view(&g3_snapshot, &corpus_rows(&[]));
    assert_aggregates(
        &g3_snapshot,
        &[("type-a", 6), ("type-b", 6), ("type-c", 6)],
        153,
        18,
        18,
    );

    // --- g4: append two `type-d` documents in one real commit ---
    let mut writer = index.writer().expect("writer");
    for (key, city, n) in APPENDED {
        writer
            .insert(appended_document(key, city, n))
            .expect("append");
    }
    assert_eq!(writer.commit().expect("commit").generation, 4);
    drop(writer);

    let index = reopen(dir.path());
    let g4_objects = reachable_immutable(dir.path());
    assert_eq!(g4_objects.len(), 6, "manifest + 4 segments + state");
    let g4_pit = index.pin().expect("pin");
    let g4_snapshot = Arc::clone(g4_pit.snapshot());
    assert_eq!(g4_snapshot.generation(), Some(4));
    assert_eq!(g4_snapshot.document_count(), 20);
    assert_eq!(g4_snapshot.segment_count(), 4);
    let mut v1 = 0;
    let mut v2 = 0;
    for guard in &guards(&g4_snapshot) {
        let reader = guard.reader();
        let body = parse_container(reader.bytes(), &SegmentLimits::default())
            .expect("container")
            .body(SectionKind::Columns)
            .expect("columns");
        if body[..2] == 1u16.to_le_bytes() {
            v1 += 1;
            assert!(
                !reader
                    .required_features()
                    .iter()
                    .any(|(id, _)| *id == FEATURE_KEYWORD_ORDINALS)
            );
        } else {
            v2 += 1;
            assert!(
                reader
                    .required_features()
                    .iter()
                    .any(|(id, _)| *id == FEATURE_KEYWORD_ORDINALS)
            );
        }
    }
    assert_eq!((v1, v2), (3, 1), "three genuine v1 and one v2 segment");
    assert_eq!(
        prepare_city(&g4_snapshot, &guards(&g4_snapshot)).unavailable(),
        Some(KeywordOrdinalUnavailable::LegacySegment)
    );
    assert_legacy_city_view(&g4_snapshot, &corpus_rows(&APPENDED));
    assert_aggregates(
        &g4_snapshot,
        &[("type-a", 6), ("type-b", 6), ("type-c", 6), ("type-d", 2)],
        190,
        20,
        20,
    );

    // --- g5: real compaction to one all-v2 segment ---
    let mut writer = index.writer().expect("writer");
    assert_eq!(writer.compact().expect("compact").documents, 20);
    drop(writer);
    let index = reopen(dir.path());
    assert_eq!(index.generation(), Some(5));
    let g5_snapshot = index.snapshot();
    assert_eq!(g5_snapshot.segment_count(), 1);
    assert_eq!(g5_snapshot.document_count(), 20);
    let g5_values = assert_city_view(&g5_snapshot, &corpus_rows(&APPENDED), &HISTORICAL_TERMS_20);
    assert_eq!(g5_values, corpus_values(&APPENDED));
    assert_aggregates(
        &g5_snapshot,
        &[("type-a", 6), ("type-b", 6), ("type-c", 6), ("type-d", 2)],
        190,
        20,
        20,
    );
    {
        let guard = g5_snapshot.open_segment_reader(0).expect("guard");
        let columns = guard
            .reader()
            .open_columns()
            .expect("columns")
            .expect("section");
        let handle = columns
            .bind_keyword_ordinals(CATEGORY)
            .expect("bind")
            .expect("ordinal");
        assert_eq!(handle.dictionary_len(), 4);
    }

    // Every recorded g3/g4 immutable object still exists byte-identically on
    // disk after compaction (content-addressed files are never rewritten).
    for (path, bytes) in g3_objects.iter().chain(g4_objects.iter()) {
        let on_disk = std::fs::read(dir.path().join(path))
            .unwrap_or_else(|error| panic!("immutable object {path} disappeared: {error}"));
        assert_eq!(
            on_disk.as_slice(),
            bytes.as_slice(),
            "immutable object {path} changed"
        );
    }
    // The compacted generation publishes its own smaller closure.
    let g5_objects = reachable_immutable(dir.path());
    assert_eq!(g5_objects.len(), 3, "manifest + 1 segment + state");

    // Both held PITs keep complete original views (values, orders, projections
    // and their sticky legacy map outcome).
    assert_legacy_city_view(&g3_snapshot, &corpus_rows(&[]));
    assert_legacy_city_view(&g4_snapshot, &corpus_rows(&APPENDED));
    assert_eq!(g3_snapshot.document_count(), 18);
    assert_eq!(g4_snapshot.document_count(), 20);
    assert_eq!(g3_snapshot.generation(), Some(3));
    assert_eq!(g4_snapshot.generation(), Some(4));
    drop(g3_pit);
    drop(g4_pit);
    drop(g3_snapshot);
    drop(g4_snapshot);
    drop(index);

    // --- child process: complete g5 validation after a fresh cold local open ---
    let status = std::process::Command::new(std::env::current_exe().expect("current exe"))
        .args(["--ignored", "--exact", "b1_i04_child_body"])
        .env("PERF06_B1_I04_DIR", dir.path())
        .env("PERF06_B1_I04_MODE", "g5")
        .status()
        .expect("spawn child");
    assert!(status.success(), "child process failed: {status:?}");
}

#[test]
#[ignore = "invoked only by b1_i04_historical_fixture_append_compact_and_reopen"]
fn b1_i04_child_body() {
    let dir =
        std::env::var("PERF06_B1_I04_DIR").expect("PERF06_B1_I04_DIR must be set by the parent");
    let mode =
        std::env::var("PERF06_B1_I04_MODE").expect("PERF06_B1_I04_MODE must be set by the parent");
    assert_eq!(mode, "g5", "unsupported child mode");
    let index = Index::open_existing(
        fs_directory(std::path::Path::new(&dir)),
        schema(),
        registry(),
    )
    .expect("child open");
    assert_eq!(index.generation(), Some(5));
    let snapshot = index.snapshot();
    assert_eq!(snapshot.document_count(), 20);
    assert_eq!(snapshot.segment_count(), 1);
    let values = assert_city_view(&snapshot, &corpus_rows(&APPENDED), &HISTORICAL_TERMS_20);
    assert_eq!(values.len(), 20);
    assert_aggregates(
        &snapshot,
        &[("type-a", 6), ("type-b", 6), ("type-c", 6), ("type-d", 2)],
        190,
        20,
        20,
    );
    println!("PERF06_B1_I04_CHILD_PASS");
}

fn verify_fixture_package(source: &std::path::Path) {
    use quervant_objectstore::ContentDigest;

    let inventory = std::fs::read_to_string(source.join("objects.tsv")).expect("inventory");
    let mut lines = inventory.lines();
    assert_eq!(
        lines.next(),
        Some("# sha256\tbytes\trelative_path"),
        "inventory header"
    );
    let mut rows = Vec::new();
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let mut parts = line.split('\t');
        let digest = parts.next().expect("digest").to_owned();
        let bytes: u64 = parts.next().expect("bytes").parse().expect("bytes");
        let relative = parts.next().expect("path").to_owned();
        assert!(!relative.contains(".."), "no traversal");
        rows.push((digest, bytes, relative));
    }
    assert_eq!(rows.len(), 6, "six reachable objects");
    let mut paths = BTreeSet::new();
    for (digest, bytes, relative) in &rows {
        assert!(paths.insert(relative.clone()), "unique path");
        let content = std::fs::read(source.join(relative)).expect("object");
        assert_eq!(content.len() as u64, *bytes, "{relative} length");
        assert_eq!(
            ContentDigest::sha256_v1(&content).to_hex(),
            *digest,
            "{relative} digest"
        );
    }

    // Reachability: the CURRENT pointer and manifest must name exactly these
    // objects, never "the newest manifest by directory listing".
    let current_bytes = std::fs::read(source.join("index/CURRENT")).expect("CURRENT");
    let current = quervant_core::index::CurrentPointer::parse(&current_bytes).expect("parse");
    assert_eq!(current.generation(), 3);
    let manifest_bytes =
        std::fs::read(source.join(current.manifest_key().as_str())).expect("manifest");
    let manifest =
        quervant_core::segment::Manifest::decode(&manifest_bytes, &SegmentLimits::default())
            .expect("manifest decode");
    assert_eq!(manifest.segments.len(), 3);
    let mut reachable: BTreeSet<String> = BTreeSet::from([
        "index/CURRENT".to_owned(),
        current.manifest_key().as_str().to_owned(),
    ]);
    for segment in &manifest.segments {
        reachable.insert(segment.object_key.clone());
    }
    if let Some(state) = &manifest.mutation_state {
        reachable.insert(state.object_key.clone());
    }
    let inventoried: BTreeSet<String> = rows.iter().map(|(_, _, path)| path.clone()).collect();
    assert_eq!(reachable, inventoried);
}

// B1-I07 — a corrupt COLUMNS body inside valid container checksums is rejected.
#[test]
fn b1_i07_container_wrapped_column_corruption_is_rejected() {
    let index = build_corpus(memory_directory());
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).expect("guard");
    let bytes = guard.reader().bytes().to_vec();
    let features = guard.reader().required_features().to_vec();
    let doc_count = guard.reader().doc_count();
    drop(guard);

    let view = parse_container(&bytes, &SegmentLimits::default()).expect("parse container");
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
    assert!(
        features
            .iter()
            .any(|(id, _)| *id == FEATURE_KEYWORD_ORDINALS)
    );

    let rebuild = |columns: Vec<u8>| -> Vec<u8> {
        let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
        for (id, version) in &features {
            builder.require_feature(*id, *version);
        }
        for (kind, flags, aux, body) in &sections {
            let body = if *kind == SectionKind::Columns {
                columns.clone()
            } else {
                body.clone()
            };
            builder.section(*kind, *flags, *aux, body);
        }
        builder.build().expect("rebuild container")
    };

    // A trailing byte that is not consumed by any column extent.
    let mut trailing = parse_container(&bytes, &SegmentLimits::default())
        .expect("container")
        .body(SectionKind::Columns)
        .expect("columns")
        .to_vec();
    trailing.push(0);
    let corrupt = rebuild(trailing);
    let error = match quervant_core::segment::SegmentReader::open(corrupt, SegmentLimits::default())
    {
        Err(error) => error,
        Ok(_) => panic!("trailing v2 bytes must be rejected"),
    };
    assert!(
        matches!(
            error,
            SegmentError::InvalidColumnGeometry {
                detail: "trailing v2 columns bytes"
            }
        ),
        "unexpected error: {error:?}"
    );

    // A corrupted layout-3 dictionary term count, behind valid outer checksums.
    let original = parse_container(&bytes, &SegmentLimits::default())
        .expect("container")
        .body(SectionKind::Columns)
        .expect("columns")
        .to_vec();
    let mut mutated = original.clone();
    let data_base = city_data_base(&mutated);
    let count = quervant_core::segment::value::STATE_SINGLE;
    let _ = count;
    mutated[data_base..data_base + 8].copy_from_slice(&(doc_count + 1).to_le_bytes());
    let corrupt = rebuild(mutated);
    let error = match quervant_core::segment::SegmentReader::open(corrupt, SegmentLimits::default())
    {
        Err(error) => error,
        Ok(_) => panic!("a corrupt dictionary count must be rejected"),
    };
    assert!(
        matches!(
            error,
            SegmentError::InvalidColumnGeometry {
                detail: "keyword dictionary count exceeds document count"
            }
        ),
        "unexpected error: {error:?}"
    );

    // A hostile dictionary count behind a valid outer envelope is rejected by the
    // real `SegmentReader` without unwinding (F1-03 regression).
    let mut hostile = original.clone();
    hostile[data_base..data_base + 8].copy_from_slice(&u64::MAX.to_le_bytes());
    let corrupt = rebuild(hostile);
    let error = match quervant_core::segment::SegmentReader::open(corrupt, SegmentLimits::default())
    {
        Err(error) => error,
        Ok(_) => panic!("a hostile dictionary count must be rejected"),
    };
    assert!(
        matches!(
            error,
            SegmentError::InvalidColumnGeometry {
                detail: "keyword dictionary count exceeds document count"
            }
        ),
        "unexpected error: {error:?}"
    );

    // The same corruption is rejected by the standalone column parser.
    let codec = codec_schema(&bytes);
    let mut mutated = original.clone();
    mutated[data_base..data_base + 8].copy_from_slice(&(doc_count + 1).to_le_bytes());
    assert!(
        quervant_core::segment::column::ColumnReader::open(
            &codec,
            &mutated,
            &SegmentLimits::default(),
        )
        .is_err(),
        "standalone parser must reject the same bytes"
    );
}

/// Locate the `city` column's `data_base` from the raw COLUMNS v2 headers.
fn city_data_base(body: &[u8]) -> usize {
    let count = u32::from_le_bytes(body[2..6].try_into().expect("count")) as usize;
    for index in 0..count {
        let at = 6 + index * 46;
        let field_id = u32::from_le_bytes(body[at..at + 4].try_into().expect("field id"));
        if field_id != CITY {
            continue;
        }
        let dir_offset =
            u64::from_le_bytes(body[at + 30..at + 38].try_into().expect("dir offset")) as usize;
        let dir_len =
            u64::from_le_bytes(body[at + 38..at + 46].try_into().expect("dir len")) as usize;
        return dir_offset + dir_len;
    }
    panic!("city column header not found");
}

fn codec_schema(bytes: &[u8]) -> quervant_core::segment::CodecSchema {
    let view = parse_container(bytes, &SegmentLimits::default()).expect("container");
    quervant_core::segment::CodecSchema::decode(
        view.body(SectionKind::Schema).expect("schema body"),
        &SegmentLimits::default(),
    )
    .expect("codec schema")
}
