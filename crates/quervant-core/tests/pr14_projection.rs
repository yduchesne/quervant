//! PR 14 phases 14A/14D: unified execution delegation and stored projections.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::{CancellationFlag, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::result::{Projection, Sort, SortDirection, SortField, TopK};
use quervant_core::contract::value::{JsonNumber, JsonValue};
use quervant_core::search::{
    ProjectionLedger, ProjectionPlan, SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher,
    projected_hit_bytes,
};

fn unified(
    index: &quervant_core::index::Index,
    request: &UnifiedRequest,
) -> quervant_core::search::UnifiedResponse {
    let snapshot = index.snapshot();
    let schema = schema();
    UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &NeverCancel)
        .expect("unified search")
}

fn docs() -> Vec<quervant_core::contract::document::Document> {
    let mut a = doc("a");
    set(&mut a, "title", FieldValue::Text("hello world".into()));
    set(&mut a, "host", FieldValue::Keyword("h1".into()));
    set(&mut a, "n", FieldValue::I64(1));
    // Indexed but not stored: must never be projected.
    set(
        &mut a,
        "raw",
        FieldValue::Json(JsonValue::Number(JsonNumber::I64(7))),
    );
    let mut b = doc("b");
    set(&mut b, "title", FieldValue::Text("hello there".into()));
    set_null(&mut b, "host");
    set_empty(&mut b, "nullable");
    set(&mut b, "n", FieldValue::I64(2));
    let mut c = doc("c");
    set(&mut c, "title", FieldValue::Text("goodbye".into()));
    set(&mut c, "host", FieldValue::Keyword("h3".into()));
    set(&mut c, "n", FieldValue::I64(3));
    vec![a, b, c]
}

fn committed_with_directory(
    docs: Vec<quervant_core::contract::document::Document>,
) -> (
    Arc<dyn quervant_core::storage::Directory>,
    quervant_core::index::Index,
) {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in docs {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    (directory, index)
}

// P01 — Projection::Source returns stored fields and never leaks unstored ones.
#[test]
fn p01_source_projection() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Source;
    let response = unified(&index, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["a", "b", "c"]);
    for hit in &response.hits {
        assert!(hit.fields.iter().all(|(name, _)| name != "raw"));
        assert!(hit.fields.iter().any(|(name, _)| name == "host"));
    }
}

// P02 — Projection::Fields preserves request order exactly.
#[test]
fn p02_field_order() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["title".into(), "host".into()]);
    let response = unified(&index, &request);
    for hit in &response.hits {
        let names: Vec<&str> = hit.fields.iter().map(|(name, _)| name.as_str()).collect();
        assert_eq!(names, ["title", "host"]);
    }
}

// P03 — five-state field vocabulary round-trips through projection.
#[test]
fn p03_five_state_preserved() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Fields(vec!["host".into(), "nullable".into()]);
    let response = unified(&index, &request);
    let by_key = |key: &str| {
        response
            .hits
            .iter()
            .find(|hit| hit.key.as_str() == key)
            .expect("hit")
    };
    assert_eq!(by_key("b").fields[0].1, FieldValues::ExplicitNull);
    assert_eq!(by_key("b").fields[1].1, FieldValues::Empty);
    assert_eq!(
        by_key("a").fields[0].1,
        FieldValues::Single(FieldValue::Keyword("h1".into()))
    );
    assert_eq!(by_key("a").fields[1].1, FieldValues::Absent);
}

// P04 — unstored/unknown/duplicate projection requests fail before scanning.
#[test]
fn p04_invalid_projections_rejected() {
    let schema = schema();
    assert!(ProjectionPlan::compile(&Projection::Fields(vec!["raw".into()]), &schema).is_err());
    assert!(ProjectionPlan::compile(&Projection::Fields(vec!["missing".into()]), &schema).is_err());
    assert!(
        ProjectionPlan::compile(
            &Projection::Fields(vec!["host".into(), "host".into()]),
            &schema
        )
        .is_err()
    );
}

// P05 — projection output is charged and an over-budget result fails closed.
#[test]
fn p05_projection_budget() {
    let plan = ProjectionPlan::compile(&Projection::Source, &schema()).unwrap();
    assert!(!plan.field_names().is_empty());
    let mut ledger = ProjectionLedger::new(1);
    assert!(matches!(
        ledger.reserve(projected_hit_bytes(&DocumentKey::new("a").unwrap(), &[])),
        Err(SearchError::ResourceLimit { .. })
    ));
    assert_eq!(ledger.used(), 0);
}

// P06 — deleted documents never appear in projected responses.
#[test]
fn p06_deleted_documents_excluded() {
    let (directory, _index) = committed_with_directory(docs());
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("b").unwrap()))
            .unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory);
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = unified(&live, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["a", "c"]);
    assert_eq!(response.total_hits, 2);
}

// P07 — pure lexical unified search delegates and scores.
#[test]
fn p07_pure_lexical_delegation() {
    let index = committed(docs());
    let request = UnifiedRequest::new(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("hello".into()),
        },
        TopK::new(10).unwrap(),
    );
    let response = unified(&index, &request);
    let mut keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    keys.sort_unstable();
    assert_eq!(keys, ["a", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_some()));
    assert_eq!(response.total_hits, 2);
}

// P08 — mixed lexical+typed predicates execute exactly over the live universe.
#[test]
fn p08_mixed_predicates_execute() {
    let index = committed(docs());
    let snapshot = index.snapshot();
    let schema = schema();
    // `title` contains "hello" AND `host` is present (present includes explicit null).
    let request = UnifiedRequest::new(
        Query::And(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("hello".into()),
            },
            Query::Exists {
                field: "host".into(),
            },
        ]),
        TopK::new(10).unwrap(),
    );
    let response = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .expect("mixed search");
    let mut keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    keys.sort_unstable();
    assert_eq!(keys, ["a", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_some()));
}

// P09 — a pure lexical query now supports an explicit canonical sort.
#[test]
fn p09_lexical_explicit_sort_supported() {
    let index = committed(docs());
    let snapshot = index.snapshot();
    let schema = schema();
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("hello".into()),
        },
        TopK::new(10).unwrap(),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    let response = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .expect("explicit lexical sort");
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["a", "b"]);
}

// P10 — pure typed queries use the typed executor and return no score.
#[test]
fn p10_pure_typed_delegation() {
    let index = committed(docs());
    let mut request = UnifiedRequest::new(
        Query::Range {
            field: "n".into(),
            lower: Bound::Included(FieldValue::I64(2)),
            upper: Bound::Unbounded,
        },
        TopK::new(10).unwrap(),
    );
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Desc)]);
    let response = unified(&index, &request);
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["c", "b"]);
    assert!(response.hits.iter().all(|hit| hit.score.is_none()));
    assert_eq!(response.total_hits, 2);
}

// ---------------------------------------------------------------------------
// PR 15E Phase 3 — selective stored-document materialization (production path)
// ---------------------------------------------------------------------------

fn phase3_document(key: &str, n: i64) -> quervant_core::contract::document::Document {
    let mut document = doc(key);
    set(
        &mut document,
        "title",
        FieldValue::Text(format!("hello {key}")),
    );
    set(&mut document, "host", FieldValue::Keyword(format!("h{n}")));
    set(&mut document, "n", FieldValue::I64(n));
    set_multi(
        &mut document,
        "mn",
        vec![FieldValue::I64(n * 2), FieldValue::I64(n * 2 + 1)],
    );
    set_multi(
        &mut document,
        "tags",
        vec![
            FieldValue::Keyword(format!("t{n}")),
            FieldValue::Keyword("shared".into()),
        ],
    );
    set(
        &mut document,
        "ip",
        FieldValue::Ip(format!("10.0.0.{}", (n % 250) + 1).parse().unwrap()),
    );
    set(
        &mut document,
        "net",
        FieldValue::Cidr(
            quervant_core::contract::value::IpNetwork::new(
                format!("10.0.{}.0", n % 250).parse().unwrap(),
                24,
            )
            .unwrap(),
        ),
    );
    set(&mut document, "score", FieldValue::F64(n as f64 / 8.0));
    set(
        &mut document,
        "ts",
        FieldValue::Timestamp(quervant_core::contract::value::Timestamp::from_micros(n)),
    );
    set(
        &mut document,
        "loc",
        FieldValue::GeoPoint(
            quervant_core::contract::value::GeoPoint::new((n as f64) / 100.0, (n as f64) / 200.0)
                .unwrap(),
        ),
    );
    set(
        &mut document,
        "body",
        FieldValue::Json(JsonValue::Object(vec![
            ("n".into(), JsonValue::Number(JsonNumber::I64(n))),
            (
                "nested".into(),
                JsonValue::Array(vec![
                    JsonValue::Null,
                    JsonValue::Bool(true),
                    JsonValue::String(format!("s{n}")),
                ]),
            ),
        ])),
    );
    document
}

/// Four committed segments of eight documents each (32 physical documents).
fn phase3_multi_segment_index() -> quervant_core::index::Index {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for chunk in 0..4i64 {
            for offset in 0..8i64 {
                let n = chunk * 8 + offset;
                writer
                    .insert(phase3_document(&format!("k{n:02}"), n))
                    .unwrap();
            }
            writer.commit().unwrap();
        }
    }
    reopen(directory)
}

// I01/I02 — every stored field type and value state round-trips through the
// selective production path, and Source/Fields projections agree with a full
// decode-derived expectation.
#[test]
fn phase3_i01_i02_projection_matches_full_decode_for_every_type() {
    let index = phase3_multi_segment_index();
    let snapshot = index.snapshot();
    let schema = schema();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(64).unwrap());
    request.sort = Sort::new(vec![SortField::new("n", SortDirection::Asc)]);
    request.projection = Projection::Source;
    let response = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("source projection");
    assert_eq!(response.total_hits, 32);
    assert_eq!(response.hits.len(), 32);

    // Independent expectation: decode the stored record directly for every hit and
    // compare field-for-field with the projected response.
    for hit in &response.hits {
        let n: i64 = hit.key.as_str()[1..].parse().unwrap();
        let expected_document = phase3_document(hit.key.as_str(), n);
        // Physical key parity already holds; compare against the contract document.
        for (name, values) in &hit.fields {
            let expected = expected_document.get(name);
            assert_eq!(*values, expected, "field {name} of {}", hit.key.as_str());
        }
        assert!(hit.fields.iter().all(|(name, _)| name != "raw"));
    }

    // Fields projection returns the requested states in request order.
    request.projection = Projection::Fields(vec![
        "host".into(),
        "nullable".into(),
        "tags".into(),
        "body".into(),
    ]);
    let fields_response =
        UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
            .search(&request, &Budgets::new(), &NeverCancel)
            .expect("fields projection");
    assert_eq!(
        fields_response
            .hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>(),
        response
            .hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>()
    );
    let source_field = |hit: &quervant_core::search::ProjectedHit, name: &str| {
        hit.fields
            .iter()
            .find(|(field, _)| field == name)
            .map(|(_, values)| values.clone())
            .unwrap_or(FieldValues::Absent)
    };
    for (source, projected) in response.hits.iter().zip(&fields_response.hits) {
        let names: Vec<&str> = projected
            .fields
            .iter()
            .map(|(name, _)| name.as_str())
            .collect();
        assert_eq!(names, ["host", "nullable", "tags", "body"]);
        assert_eq!(
            projected.fields[0].1,
            source_field(source, "host"),
            "host parity"
        );
        assert_eq!(
            projected.fields[1].1,
            FieldValues::Absent,
            "nullable absent"
        );
        assert_eq!(
            projected.fields[2].1,
            source_field(source, "tags"),
            "tags parity"
        );
        assert_eq!(
            projected.fields[3].1,
            source_field(source, "body"),
            "nested json parity"
        );
    }
}

// I04 — deletes/upserts across generations project only the live version, and a
// PIT keeps the older generation's projection.
#[test]
fn phase3_i04_generations_and_pit_project_only_live_records() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let mut writer = index.writer().unwrap();
    for n in 0..6i64 {
        writer
            .insert(phase3_document(&format!("k{n:02}"), n))
            .unwrap();
    }
    writer.commit().unwrap();
    let old_snapshot = writer.reader();
    let old_keys: Vec<String> = {
        let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(16).unwrap());
        request.projection = Projection::Source;
        UnifiedSearcher::new(
            &old_snapshot,
            &schema(),
            &registry(),
            SearchLimits::default(),
        )
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap()
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
    };
    assert_eq!(old_keys.len(), 6);

    // Delete one document and replace another with a different stored payload.
    writer
        .apply(MutationRequest::delete(DocumentKey::new("k02").unwrap()))
        .unwrap();
    let mut replaced = phase3_document("k03", 300);
    set(
        &mut replaced,
        "host",
        FieldValue::Keyword("replacement".into()),
    );
    writer.apply(MutationRequest::upsert(replaced)).unwrap();
    writer.commit().unwrap();

    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(16).unwrap());
    request.projection = Projection::Fields(vec!["host".into(), "n".into()]);
    let response = UnifiedSearcher::new(
        &writer.reader(),
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &NeverCancel)
    .unwrap();
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert!(!keys.contains(&"k02"));
    let replaced_hit = response
        .hits
        .iter()
        .find(|hit| hit.key.as_str() == "k03")
        .expect("replacement hit");
    assert_eq!(
        replaced_hit.fields[0].1,
        FieldValues::Single(FieldValue::Keyword("replacement".into()))
    );
    assert_eq!(
        replaced_hit.fields[1].1,
        FieldValues::Single(FieldValue::I64(300))
    );

    // The older pinned snapshot still projects the pre-mutation generation.
    let pinned: Vec<String> = UnifiedSearcher::new(
        &old_snapshot,
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &NeverCancel)
    .unwrap()
    .hits
    .iter()
    .map(|hit| hit.key.as_str().to_owned())
    .collect();
    assert!(pinned.contains(&"k02".to_owned()));
}

// I05/I07 — hits interleaved across segments, sort ties and a cursor keep their
// order and project the right physical records.
#[test]
fn phase3_i05_i07_interleaved_segments_sort_and_cursor() {
    let index = phase3_multi_segment_index();
    let snapshot = index.snapshot();
    let schema = schema();
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: "tags".into(),
            value: FieldValue::Keyword("shared".into()),
        },
        TopK::new(5).unwrap(),
    );
    // Descending relevance ties are broken by key, spanning four segments.
    request.projection = Projection::Fields(vec!["host".into(), "n".into()]);
    let first_page = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("first page");
    assert_eq!(first_page.hits.len(), 5);
    let mut seen: Vec<String> = first_page
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect();
    let mut cursor = first_page.next_cursor.clone();
    while let Some(current) = cursor {
        request.after = Some(current);
        let page = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
            .search(&request, &Budgets::new(), &NeverCancel)
            .expect("page");
        for hit in &page.hits {
            let n: i64 = hit.key.as_str()[1..].parse().unwrap();
            // Physical record parity: the projected fields are the document's own.
            assert_eq!(hit.fields[1].1, FieldValues::Single(FieldValue::I64(n)));
            assert_eq!(
                hit.fields[0].1,
                FieldValues::Single(FieldValue::Keyword(format!("h{n}")))
            );
            seen.push(hit.key.as_str().to_owned());
        }
        cursor = page.next_cursor;
    }
    assert_eq!(seen.len(), 32);
    let unique: std::collections::BTreeSet<&String> = seen.iter().collect();
    assert_eq!(
        unique.len(),
        32,
        "no duplicate or omitted hits across pages"
    );
}

// I03 — the same selected hits through the batch API project identically.
#[test]
fn phase3_i03_batch_and_standalone_projection_parity() {
    use quervant_core::contract::batch::{
        BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
    };
    use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets as BatchBudgets};
    use quervant_core::contract::capability::CapabilitySet;
    use quervant_core::search::execute_batch;

    let index = phase3_multi_segment_index();
    let snapshot = index.snapshot();
    let schema = schema();
    let mut request = UnifiedRequest::new(
        Query::Term {
            field: "tags".into(),
            value: FieldValue::Keyword("shared".into()),
        },
        TopK::new(8).unwrap(),
    );
    request.projection = Projection::Fields(vec!["host".into(), "n".into(), "body".into()]);
    let standalone = UnifiedSearcher::new(&snapshot, &schema, &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("standalone");

    let policy = BudgetPolicy::new(
        BatchBudgets::new()
            .with(BudgetKind::QueriesPerBatch, 4)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1 << 20)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 1 << 20)
            .unwrap(),
        BatchBudgets::new(),
        BatchBudgets::new(),
        BatchBudgets::new(),
    );
    let mut batch_request = QueryRequest::new(request.query.clone());
    batch_request.top_k = TopK::new(8).unwrap();
    batch_request.projection = request.projection.clone();
    let response = execute_batch(
        &snapshot,
        &schema,
        &registry(),
        SearchLimits::default(),
        &BatchQueryRequest::new(vec![batch_request], None, BatchBudget::new(4)),
        &policy,
        &CapabilitySet::new(),
        &NeverCancel,
    )
    .expect("batch envelope");
    let PerQueryOutcome::Success(batched) = &response.results()[0] else {
        panic!("batch slot failed: {:?}", response.results()[0]);
    };
    assert_eq!(batched.total_hits, standalone.total_hits);
    assert_eq!(batched.hits.len(), standalone.hits.len());
    for (batched_hit, standalone_hit) in batched.hits.iter().zip(&standalone.hits) {
        assert_eq!(batched_hit.key, standalone_hit.key);
        assert_eq!(
            batched_hit.score,
            standalone_hit.score.map(|value| value as f32)
        );
        assert_eq!(batched_hit.fields, standalone_hit.fields);
    }
}
