//! PR 10 T10–T12 and T54–T61: lifecycle, PIT, merge, lexical coexistence and codec stability.

mod pr10_common;

use std::sync::Arc;

use pr10_common::{
    AggregateMetric, AggregateRequest, FieldValue, Query, Sort, committed, full_doc, hit_keys,
    i64_range, match_all_request, time_range, typed_search,
};
use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::contract::result::TopK;
use quervant_core::index::Index;
use quervant_core::search::{LexicalSearcher, SearchLimits, TypedSearcher};

fn request(query: Query) -> pr10_common::TypedSearchRequest {
    let mut request = match_all_request(Sort::default(), 50);
    request.query = query;
    request
}

// T10 — deleted logical keys disappear from typed scans.
#[test]
fn t10_delete_excludes_typed_docs() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .insert(full_doc(
            "a",
            "a",
            1,
            5,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer
        .insert(full_doc(
            "b",
            "b",
            2,
            6,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.2",
        ))
        .unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();
    let reopened = pr10_common::reopen(directory);
    let snapshot = reopened.snapshot();
    let response = typed_search(&snapshot, &request(i64_range("n", Some(0), Some(10))));
    assert_eq!(hit_keys(&response), ["b"]);
}

// T11 — upsert replaces the typed values of a logical key.
#[test]
fn t11_upsert_replaces_typed_values() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .insert(full_doc(
            "a",
            "a",
            1,
            5,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::upsert(full_doc(
            "a",
            "a",
            2,
            50,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        )))
        .unwrap();
    writer.commit().unwrap();
    let reopened = pr10_common::reopen(directory);
    let snapshot = reopened.snapshot();
    assert_eq!(
        hit_keys(&typed_search(
            &snapshot,
            &request(i64_range("n", Some(0), Some(10)))
        )),
        Vec::<String>::new()
    );
    assert_eq!(
        hit_keys(&typed_search(
            &snapshot,
            &request(i64_range("n", Some(40), Some(60)))
        )),
        ["a"]
    );
}

// T12 — an old PIT keeps its generation-specific typed view across a delete.
#[test]
fn t12_old_pit_isolation() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .insert(full_doc(
            "a",
            "a",
            1,
            5,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer.commit().unwrap();
    let pit = writer.pin().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();

    let query = request(i64_range("n", Some(0), Some(10)));
    assert_eq!(hit_keys(&typed_search(pit.snapshot(), &query)), ["a"]);
    assert!(typed_search(&writer.reader(), &query).hits.is_empty());
}

// T54 — lossless compaction preserves typed query and aggregate results.
#[test]
fn t54_compaction_preserves_typed_results() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .insert(full_doc(
            "a",
            "a",
            1,
            5,
            0,
            1.0,
            true,
            "h1",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer.commit().unwrap();
    writer
        .insert(full_doc(
            "b",
            "b",
            2,
            6,
            0,
            1.0,
            true,
            "h2",
            &["x"],
            "10.0.0.2",
        ))
        .unwrap();
    writer.commit().unwrap();
    writer
        .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
        .unwrap();
    writer.commit().unwrap();
    let before = hit_keys(&typed_search(
        &writer.reader(),
        &request(i64_range("n", Some(0), Some(10))),
    ));
    writer.compact().unwrap();
    let after = hit_keys(&typed_search(
        &writer.reader(),
        &request(i64_range("n", Some(0), Some(10))),
    ));
    assert_eq!(before, after);
    assert_eq!(after, ["b"]);

    let aggregate = AggregateRequest {
        query: Query::MatchAll,
        group_fields: vec!["host".into()],
        time_bucket: None,
        metrics: vec![AggregateMetric::Count],
        frequency_top_k: None,
        primary_time_field: Some("ts".into()),
    };
    let response = pr10_common::aggregate(&writer.reader(), &aggregate);
    assert_eq!(response.groups.len(), 1);
}

// T55 — a committed generation survives close and reopen.
#[test]
fn t55_reopen_preserves_typed_results() {
    let (directory, index) = committed(vec![
        full_doc("a", "a", 1, 5, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 2, 6, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
    ]);
    let generation = index.generation();
    let reopened = Index::open_existing(
        directory,
        pr10_common::pr10_schema(),
        pr10_common::registry(),
    )
    .unwrap();
    assert_eq!(reopened.generation(), generation);
    let response = typed_search(
        &reopened.snapshot(),
        &request(i64_range("n", Some(0), Some(10))),
    );
    assert_eq!(hit_keys(&response), ["a", "b"]);
}

// T56 — late arrivals beyond the current maximum remain queryable.
#[test]
fn t56_late_arrivals() {
    let directory = pr10_common::memory();
    let index = pr10_common::create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    writer
        .insert(full_doc(
            "a",
            "a",
            100,
            1,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ))
        .unwrap();
    writer.commit().unwrap();
    // A late event with an earlier timestamp arrives in a later generation.
    writer
        .insert(full_doc(
            "b",
            "b",
            50,
            2,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.2",
        ))
        .unwrap();
    writer.commit().unwrap();
    let reopened = pr10_common::reopen(directory);
    let response = typed_search(&reopened.snapshot(), &request(time_range("ts", 0, 60)));
    assert_eq!(hit_keys(&response), ["b"]);
}

// T57 — seeded insertion order does not affect results.
#[test]
fn t57_seeded_order_independence() {
    let mut docs: Vec<_> = (0..20)
        .map(|index| {
            full_doc(
                &format!("k{index:02}"),
                "t",
                index,
                index,
                0,
                1.0,
                true,
                "h",
                &["x"],
                "10.0.0.1",
            )
        })
        .collect();
    let (_d1, forward) = committed(docs.clone());
    docs.reverse();
    let (_d2, reversed) = committed(docs);
    let query = request(i64_range("n", Some(5), Some(15)));
    assert_eq!(
        hit_keys(&typed_search(&forward.snapshot(), &query)),
        hit_keys(&typed_search(&reversed.snapshot(), &query))
    );
}

// T58 — compound And/Or/Not over typed predicates.
#[test]
fn t58_compound_predicates() {
    let docs = vec![
        full_doc("a", "a", 1, 1, 0, 1.0, true, "h", &["x"], "10.0.0.1"),
        full_doc("b", "b", 2, 2, 0, 1.0, true, "h", &["x"], "10.0.0.2"),
        full_doc("c", "c", 3, 3, 0, 1.0, true, "h", &["x"], "10.0.0.3"),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let and = Query::And(vec![
        i64_range("n", Some(2), Some(3)),
        time_range("ts", 2, 4),
    ]);
    assert_eq!(
        hit_keys(&typed_search(&snapshot, &request(and))),
        ["b", "c"]
    );
    let or = Query::Or(vec![
        i64_range("n", Some(1), Some(1)),
        i64_range("n", Some(3), Some(3)),
    ]);
    assert_eq!(hit_keys(&typed_search(&snapshot, &request(or))), ["a", "c"]);
    let not = Query::Not(Box::new(time_range("ts", 2, 3)));
    assert_eq!(
        hit_keys(&typed_search(&snapshot, &request(not))),
        ["a", "c"]
    );
}

// T59 — unsupported operators fail closed with no partial response.
#[test]
fn t59_unsupported_fails_closed() {
    let (_directory, index) = committed(vec![full_doc(
        "a",
        "a",
        1,
        1,
        0,
        1.0,
        true,
        "h",
        &["x"],
        "10.0.0.1",
    )]);
    let snapshot = index.snapshot();
    let schema = pr10_common::pr10_schema();
    let cancel = CancellationFlag::new();
    let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
    for query in [
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("a".into()),
        },
        Query::Prefix {
            field: "title".into(),
            prefix: "a".into(),
        },
    ] {
        let mut request = match_all_request(Sort::default(), 5);
        request.query = query;
        assert!(matches!(
            searcher.search(&request, &Budgets::new(), &cancel),
            Err(quervant_core::search::SearchError::UnsupportedOperator { .. })
        ));
    }
}

// T60 — lexical BM25 execution is unchanged alongside typed search.
#[test]
fn t60_lexical_bm25_unchanged() {
    let (_directory, index) = committed(vec![
        full_doc(
            "a",
            "quick brown fox",
            1,
            1,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.1",
        ),
        full_doc(
            "b",
            "quick red fox",
            2,
            2,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.2",
        ),
        full_doc(
            "c",
            "slow turtle",
            3,
            3,
            0,
            1.0,
            true,
            "h",
            &["x"],
            "10.0.0.3",
        ),
    ]);
    let snapshot = index.snapshot();
    let schema = pr10_common::pr10_schema();
    let registry = AnalyzerRegistry::builtin();
    let cancel = CancellationFlag::new();
    let lexical = LexicalSearcher::new(&snapshot, &schema, &registry, SearchLimits::default());
    let response = lexical
        .search(
            &Query::Term {
                field: "title".into(),
                value: FieldValue::Text("fox".into()),
            },
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.total_hits, 2);
    assert!(response.hits[0].score > 0.0);
}

// T61 — segment bytes are deterministic for identical logical data.
#[test]
fn t61_deterministic_segments() {
    let docs: Vec<_> = (0..10)
        .map(|index| {
            full_doc(
                &format!("k{index}"),
                "t",
                index,
                index,
                0,
                1.0,
                true,
                "h",
                &["x"],
                "10.0.0.1",
            )
        })
        .collect();
    let (_d1, first) = committed(docs.clone());
    let (_d2, second) = committed(docs);
    assert_eq!(
        first.snapshot().segments()[0].bytes(),
        second.snapshot().segments()[0].bytes()
    );
}
