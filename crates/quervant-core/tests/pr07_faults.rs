//! PR 7 fault and resource-bound tests (F01–F12).

mod common;

use std::cell::Cell;
use std::sync::Arc;

use common::{Pr07Doc, pr07_commit_batches, pr07_registry, pr07_schema};
use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits};
use quervant_core::segment::{
    SectionKind, SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader, parse_container,
};
use quervant_core::storage::{Directory, MemoryDirectory};

fn snapshot() -> Arc<ReaderSnapshot> {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    pr07_commit_batches(
        directory.clone(),
        vec![vec![
            Pr07Doc::new("a")
                .title("alpha beta")
                .body(vec!["gamma"])
                .build(),
            Pr07Doc::new("b").title("alpha").build(),
            Pr07Doc::new("c").title("beta").build(),
        ]],
    );
    Index::open_existing(directory, pr07_schema(), pr07_registry())
        .unwrap()
        .snapshot()
}

fn search_with(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: SearchLimits,
    query: &Query,
    cancel: &dyn Cancellation,
) -> Result<quervant_core::search::SearchResponse, SearchError> {
    LexicalSearcher::new(snapshot, schema, registry, limits).search(
        query,
        TopK::new(10).unwrap(),
        &Budgets::new(),
        cancel,
    )
}

fn default_search(
    snapshot: &ReaderSnapshot,
    query: &Query,
) -> Result<quervant_core::search::SearchResponse, SearchError> {
    search_with(
        snapshot,
        &pr07_schema(),
        &pr07_registry(),
        SearchLimits::default(),
        query,
        &CancellationFlag::new(),
    )
}

/// A cancellation source that trips after a fixed number of polls.
struct CancelAfter {
    remaining: Cell<u32>,
}

impl CancelAfter {
    fn new(remaining: u32) -> Self {
        Self {
            remaining: Cell::new(remaining),
        }
    }
}

impl Cancellation for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let left = self.remaining.get();
        if left == 0 {
            true
        } else {
            self.remaining.set(left - 1);
            false
        }
    }
}

// F01 — unsupported nested operator fails closed.
#[test]
fn f01_unsupported_nested_operator() {
    let snapshot = snapshot();
    let result = default_search(
        &snapshot,
        &Query::And(vec![
            Query::MatchAll,
            Query::Exists {
                field: "title".into(),
            },
        ]),
    );
    assert!(matches!(
        result,
        Err(SearchError::UnsupportedOperator { .. })
    ));
}

// F02 — wrong field type / unindexed field.
#[test]
fn f02_wrong_field_type() {
    let snapshot = snapshot();
    let result = default_search(
        &snapshot,
        &Query::Term {
            field: "n".into(),
            value: FieldValue::I64(1),
        },
    );
    assert!(matches!(
        result,
        Err(SearchError::UnsupportedOperator { .. })
    ));
    // Unknown fields fail contract validation before any I/O.
    let result = default_search(&snapshot, &term("missing", "x"));
    assert!(matches!(result, Err(SearchError::Query(_))));
}

// F03 — corrupt segment bytes fail with a typed codec error.
#[test]
fn f03_corrupt_postings() {
    let mut builder = SegmentBuilder::new(pr07_schema(), pr07_registry()).unwrap();
    let mut document = SegmentDocument::new(DocumentKey::new("a").unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha".into())),
        )
        .unwrap();
    builder.add_document(document).unwrap();
    let built = builder.build().unwrap();
    let mut bytes = built.bytes.clone();
    let view = parse_container(&bytes, &SegmentLimits::default()).unwrap();
    let postings = view
        .sections()
        .iter()
        .find(|entry| entry.kind == SectionKind::Postings)
        .expect("postings section");
    let offset = postings.offset as usize + 1;
    bytes[offset] ^= 0xFF;
    let error = match SegmentReader::open(bytes, SegmentLimits::default()) {
        Ok(_) => panic!("corrupt segment must not open"),
        Err(error) => error,
    };
    // The typed codec error is preserved through the search error conversion.
    let converted: SearchError = error.into();
    assert!(matches!(converted, SearchError::Segment(_)));
}

// F04 — analyzer/schema mismatch fails closed without silent reinterpretation.
#[test]
fn f04_analyzer_mismatch() {
    let snapshot = snapshot();
    let mismatched = Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard"),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "raw",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .unwrap();
    let result = search_with(
        &snapshot,
        &mismatched,
        &pr07_registry(),
        SearchLimits::default(),
        &term("title", "alpha"),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::CorruptIndex { .. })));
}

// F06 — compiled-node and distinct-term bounds.
#[test]
fn f06_node_and_term_bounds() {
    let snapshot = snapshot();
    let limits = SearchLimits::default().with_max_compiled_nodes(1).unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &Query::And(vec![Query::MatchAll, Query::MatchAll]),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));

    let limits = SearchLimits::default()
        .with_max_unique_query_terms(1)
        .unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &Query::Or(vec![term("title", "alpha"), term("title", "beta")]),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
}

// F07 — work bound fails typed; a generous bound succeeds.
#[test]
fn f07_work_bound() {
    let snapshot = snapshot();
    let limits = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &term("title", "alpha"),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
    assert!(default_search(&snapshot, &term("title", "alpha")).is_ok());
}

// F08 — candidate-byte, field-length and heap byte bounds.
#[test]
fn f08_allocation_bounds() {
    let snapshot = snapshot();
    let limits = SearchLimits::default()
        .with_max_total_candidate_bytes(8)
        .unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &term("title", "alpha"),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));

    let limits = SearchLimits::default()
        .with_max_field_length_entries(1)
        .unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &term("title", "alpha"),
        &CancellationFlag::new(),
    );
    // Amendment 05: persisted norms do not build a per-query document-length map,
    // so this legacy-only bound no longer rejects new-format segments. The legacy
    // fallback budget is covered by the `search::score` unit test.
    assert!(result.is_ok());

    let limits = SearchLimits::default().with_max_topk_heap_bytes(1).unwrap();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        limits,
        &term("title", "alpha"),
        &CancellationFlag::new(),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
}

// F09 — cancellation before start.
#[test]
fn f09_cancel_before_start() {
    let snapshot = snapshot();
    let result = search_with(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        SearchLimits::default(),
        &Query::MatchAll,
        &CancelAfter::new(0),
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));
}

// F10/F11 — cancellation during traversal and the MatchAll/NOT universe.
#[test]
fn f10_cancel_during_execution() {
    let snapshot = snapshot();
    let combined = Query::Or(vec![
        term("title", "alpha"),
        term("title", "beta"),
        Query::Not(Box::new(term("body", "gamma"))),
    ]);
    for budget in [1u32, 2, 5, 10] {
        let result = search_with(
            &snapshot,
            &pr07_schema(),
            &pr07_registry(),
            SearchLimits::default(),
            &combined,
            &CancelAfter::new(budget),
        );
        assert!(
            matches!(result, Err(SearchError::Cancelled)),
            "budget {budget} should cancel"
        );
    }
}

// F12 — a bound failure releases resources and a subsequent query succeeds.
#[test]
fn f12_failure_releases_resources() {
    let snapshot = snapshot();
    let tight = SearchLimits::default()
        .with_max_total_work_units(1)
        .unwrap();
    assert!(matches!(
        search_with(
            &snapshot,
            &pr07_schema(),
            &pr07_registry(),
            tight,
            &term("title", "alpha"),
            &CancellationFlag::new(),
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
    // The snapshot remains usable and the reader-copy reservation was released.
    let response = default_search(&snapshot, &term("title", "alpha")).unwrap();
    assert_eq!(response.total_hits, 2);
    let response = default_search(&snapshot, &Query::MatchAll).unwrap();
    assert_eq!(response.total_hits, 3);
}

fn term(field: &str, text: &str) -> Query {
    Query::Term {
        field: field.into(),
        value: FieldValue::Text(text.into()),
    }
}
