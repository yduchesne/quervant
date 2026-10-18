//! PR 14 F1 correctness-hardening acceptance tests.
//!
//! Score parity is asserted against the PR 7 `LexicalSearcher` on the same
//! snapshot with `f64::to_bits()` equality, not against another unified result.
//! Sort validation failures are asserted before any segment work.

mod pr14_common;

use std::collections::BTreeMap;
use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::{Cancellation, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::FieldValues;
use quervant_core::contract::query::JsonPathExpr;
use quervant_core::contract::result::Projection;
use quervant_core::contract::value::GeoPoint;
use quervant_core::search::{
    LexicalSearcher, SearchError, SearchLimits, UnifiedRequest, UnifiedSearcher,
};

fn search(
    index: &quervant_core::index::Index,
    query: Query,
    sort: Sort,
    top_k: usize,
) -> quervant_core::search::UnifiedResponse {
    let snapshot = index.snapshot();
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).unwrap());
    request.sort = sort;
    UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .expect("unified search")
}

fn lexical_scores(index: &quervant_core::index::Index, query: Query) -> BTreeMap<String, u64> {
    let snapshot = index.snapshot();
    let response = LexicalSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(
            &query,
            TopK::new(100).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("lexical search");
    response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score.to_bits()))
        .collect()
}

fn all_docs() -> Vec<quervant_core::contract::document::Document> {
    // Every document has a present `host`, so `Exists(host)` is nonrestrictive.
    let mut d1 = doc("d1");
    set(&mut d1, "title", FieldValue::Text("alpha beta".into()));
    set(&mut d1, "host", FieldValue::Keyword("h".into()));
    set(&mut d1, "n", FieldValue::I64(1));
    let mut d2 = doc("d2");
    set(&mut d2, "title", FieldValue::Text("alpha gamma".into()));
    set(&mut d2, "host", FieldValue::Keyword("h".into()));
    set(&mut d2, "n", FieldValue::I64(2));
    let mut d3 = doc("d3");
    set(&mut d3, "title", FieldValue::Text("beta gamma".into()));
    set(&mut d3, "host", FieldValue::Keyword("h".into()));
    set(&mut d3, "n", FieldValue::I64(3));
    let mut d4 = doc("d4");
    set(&mut d4, "title", FieldValue::Text("alpha delta".into()));
    set(&mut d4, "host", FieldValue::Keyword("h".into()));
    set(&mut d4, "n", FieldValue::I64(4));
    vec![d1, d2, d3, d4]
}

fn term(text: &str) -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text(text.into()),
    }
}

fn nonrestrictive() -> Query {
    Query::Exists {
        field: "host".into(),
    }
}

fn assert_parity(index: &quervant_core::index::Index, lexical: Query, mixed: Query) {
    let expected = lexical_scores(index, lexical);
    let response = search(index, mixed, Sort::default(), 100);
    assert_eq!(response.total_hits, expected.len() as u64);
    for hit in &response.hits {
        let expected_bits = expected
            .get(hit.key.as_str())
            .unwrap_or_else(|| panic!("unexpected hit {}", hit.key));
        assert_eq!(
            hit.score.expect("lexical score").to_bits(),
            *expected_bits,
            "score mismatch for {}",
            hit.key
        );
    }
}

// S01 — Term + nonrestrictive typed clause is bit-identical to PR 7.
#[test]
fn s01_term_parity() {
    let index = committed(all_docs());
    assert_parity(
        &index,
        term("alpha"),
        Query::And(vec![term("alpha"), nonrestrictive()]),
    );
}

// S02 — Phrase + nonrestrictive typed clause is bit-identical.
#[test]
fn s02_phrase_parity() {
    let index = committed(all_docs());
    assert_parity(
        &index,
        Query::Phrase {
            field: "title".into(),
            terms: vec!["alpha".into(), "beta".into()],
        },
        Query::And(vec![
            Query::Phrase {
                field: "title".into(),
                terms: vec!["alpha".into(), "beta".into()],
            },
            nonrestrictive(),
        ]),
    );
}

// S03 — duplicate positive leaves and nested Boolean do not double score.
#[test]
fn s03_duplicate_nested_parity() {
    let index = committed(all_docs());
    assert_parity(
        &index,
        term("alpha"),
        Query::And(vec![
            Query::Or(vec![term("alpha"), term("alpha")]),
            nonrestrictive(),
        ]),
    );
}

// S05 — two segments use snapshot-wide BM25 statistics, not segment-local.
#[test]
fn s05_two_segment_statistics_parity() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    let documents = all_docs();
    {
        let mut writer = index.writer().unwrap();
        for document in documents.iter().take(2).cloned() {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    {
        let mut writer = index.writer().unwrap();
        for document in documents.into_iter().skip(2) {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = reopen(directory);
    assert!(reopened.snapshot().segment_count() >= 2);
    assert_parity(
        &reopened,
        term("alpha"),
        Query::And(vec![term("alpha"), nonrestrictive()]),
    );
}

// V01 — unknown sort field fails with a typed contract error before I/O.
#[test]
fn v01_unknown_sort_field() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("missing", SortDirection::Asc)]);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

// V02 — a non-columnar sort field is rejected.
#[test]
fn v02_noncolumnar_sort_field() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("title", SortDirection::Asc)]);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

// V03 — a multi-value sort field requires an explicit selector.
#[test]
fn v03_multivalue_selector_required() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::new("tags", SortDirection::Asc)]);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

// V04 — a JSON path sort on a non-JSON field is rejected.
#[test]
fn v04_json_path_on_non_json_field() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![
        SortField::new("n", SortDirection::Asc).with_json_path(JsonPathExpr::parse("$.x").unwrap()),
    ]);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

// V05 — a geo-distance sort on a non-GeoPoint field is rejected.
#[test]
fn v05_invalid_geo_sort_field() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let origin = GeoPoint::new(0.0, 0.0).unwrap();
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.sort = Sort::new(vec![SortField::geo_distance(
        "title",
        origin,
        SortDirection::Asc,
    )]);
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::Query(_)));
}

fn geo_docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    for (key, lon) in [("g1", 0.0), ("g2", 1.0), ("g3", 2.0)] {
        let mut document = doc(key);
        set(
            &mut document,
            "title",
            FieldValue::Text("alpha beta".into()),
        );
        set(&mut document, "host", FieldValue::Keyword("h".into()));
        set(
            &mut document,
            "loc",
            FieldValue::GeoPoint(GeoPoint::new(lon, 0.0).unwrap()),
        );
        docs.push(document);
    }
    let mut missing = doc("g4");
    set(&mut missing, "title", FieldValue::Text("alpha beta".into()));
    set(&mut missing, "host", FieldValue::Keyword("h".into()));
    docs.push(missing);
    docs
}

fn geo_sort(direction: SortDirection, missing: MissingValuePosition) -> Sort {
    let mut field = SortField::geo_distance("loc", GeoPoint::new(0.0, 0.0).unwrap(), direction);
    field.missing = missing;
    Sort::new(vec![field])
}

// G01 — mixed ascending geo-distance sort.
#[test]
fn g01_geo_ascending() {
    let index = committed(geo_docs());
    let response = search(
        &index,
        Query::And(vec![term("alpha"), nonrestrictive()]),
        geo_sort(SortDirection::Asc, MissingValuePosition::Last),
        10,
    );
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["g1", "g2", "g3", "g4"]);
}

// G02 — mixed descending geo-distance sort.
#[test]
fn g02_geo_descending() {
    let index = committed(geo_docs());
    let response = search(
        &index,
        Query::And(vec![term("alpha"), nonrestrictive()]),
        geo_sort(SortDirection::Desc, MissingValuePosition::Last),
        10,
    );
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    // Missing values stay last regardless of direction.
    assert_eq!(keys, ["g3", "g2", "g1", "g4"]);
}

// G03 — missing geo values placed first.
#[test]
fn g03_geo_missing_first() {
    let index = committed(geo_docs());
    let response = search(
        &index,
        Query::And(vec![term("alpha"), nonrestrictive()]),
        geo_sort(SortDirection::Asc, MissingValuePosition::First),
        10,
    );
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    assert_eq!(keys, ["g4", "g1", "g2", "g3"]);
}

// M02 — K=1 still reports the exact total hit count.
#[test]
fn m02_top_k_total_hits() {
    let index = committed(all_docs());
    let response = search(
        &index,
        Query::And(vec![term("alpha"), nonrestrictive()]),
        Sort::default(),
        1,
    );
    assert_eq!(response.hits.len(), 1);
    assert_eq!(response.total_hits, 3);
}

// W04 — a zero-match scan still charges work and exhausts a tiny budget.
#[test]
fn w04_zero_match_scan_charges_work() {
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let limits = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    let request = UnifiedRequest::new(
        Query::And(vec![term("nonexistent"), nonrestrictive()]),
        TopK::new(10).unwrap(),
    );
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), limits)
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
}

// W06 — cancellation is observed in the mixed lexical/typed loop.
#[test]
fn w06_mixed_cancellation() {
    struct FlipAfter(std::sync::atomic::AtomicUsize);
    impl Cancellation for FlipAfter {
        fn is_cancelled(&self) -> bool {
            self.0.fetch_add(1, std::sync::atomic::Ordering::Relaxed) >= 1
        }
    }
    let index = committed(all_docs());
    let snapshot = index.snapshot();
    let request = UnifiedRequest::new(
        Query::And(vec![term("alpha"), nonrestrictive()]),
        TopK::new(10).unwrap(),
    );
    let error = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &FlipAfter(Default::default()))
        .unwrap_err();
    assert!(matches!(error, SearchError::Cancelled));
}

// P02 — projection uses the current physical version after an update.
#[test]
fn p02_projection_uses_current_version() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        let mut original = doc("k");
        set(&mut original, "title", FieldValue::Text("alpha".into()));
        set(&mut original, "host", FieldValue::Keyword("old".into()));
        writer.insert(original).unwrap();
        writer.commit().unwrap();
    }
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        let mut updated = doc("k");
        set(&mut updated, "title", FieldValue::Text("alpha".into()));
        set(&mut updated, "host", FieldValue::Keyword("new".into()));
        writer
            .apply(quervant_core::contract::document::MutationRequest::upsert(
                updated,
            ))
            .unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory);
    let snapshot = live.snapshot();
    let mut request = UnifiedRequest::new(
        Query::And(vec![term("alpha"), nonrestrictive()]),
        TopK::new(10).unwrap(),
    );
    request.projection = Projection::Fields(vec!["host".into()]);
    let response = UnifiedSearcher::new(&snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &NeverCancel)
        .unwrap();
    assert_eq!(response.hits.len(), 1);
    assert_eq!(
        response.hits[0].fields[0].1,
        FieldValues::Single(FieldValue::Keyword("new".into()))
    );
}
