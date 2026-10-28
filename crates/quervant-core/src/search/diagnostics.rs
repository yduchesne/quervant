//! PR 15B opt-in work counters (test-only, compiled out of normal builds).
//!
//! The production executor exposes no diagnostics threading point that can be
//! incremented without changing private call signatures or introducing a
//! thread-local/global hook. The approved action is therefore a test-only module
//! that observes the authoritative production response:
//!
//! - `selected_hits` is the exact number of final selected hits returned by the
//!   real unified executor.
//! - `projection_fields` is the exact number of projected field entries emitted
//!   into those hits (each `(name, FieldValues)` pair counts once).
//!
//! Every other requested stage counter has no existing authoritative seam and is
//! recorded as `NOT INSTRUMENTED` (`None`), never as zero. See
//! `docs/pr-artifacts/pr-15b/instrumentation.md`.
//!
//! The module is declared behind `#[cfg(test)]` in `search/mod.rs`, so normal
//! builds contain no runtime branch, no public symbol and no TLS/global state.

use crate::analysis::{AnalyzerRegistry, Cancellation};
use crate::contract::budget::Budgets;
use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use crate::contract::query::Query;
use crate::contract::result::{Projection, TopK};
use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
use crate::contract::value::{FieldType, FieldValue, JsonNumber, JsonValue, Timestamp};
use crate::index::{Index, ReaderSnapshot};
use crate::search::{SearchError, SearchLimits, SearchResult, UnifiedRequest, UnifiedSearcher};
use crate::storage::{Directory, MemoryDirectory};
use std::sync::Arc;

/// Deterministic work counters for one query.
///
/// `None` means **NOT INSTRUMENTED**; it never means zero. Only fields with an
/// existing authoritative event are `Some`.
#[derive(Default, Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct WorkCounters {
    pub(crate) segments_visited: Option<u64>,
    pub(crate) candidates_examined: Option<u64>,
    pub(crate) documents_decoded: Option<u64>,
    pub(crate) selected_hits: Option<u64>,
    pub(crate) projection_fields: Option<u64>,
    pub(crate) sort_comparisons: Option<u64>,
    pub(crate) group_updates: Option<u64>,
    pub(crate) logical_memory_peak_bytes: Option<u64>,
}

/// Execute the real public unified entrypoint once and record the counters that
/// have an existing authoritative response-level event.
///
/// A failed or cancelled query returns `Err`; it never reports a completed
/// selection.
pub(crate) fn measure(
    snapshot: &ReaderSnapshot,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    request: &UnifiedRequest,
    cancel: &dyn Cancellation,
) -> SearchResult<WorkCounters> {
    let response = UnifiedSearcher::new(snapshot, schema, registry, SearchLimits::default())
        .search(request, &Budgets::new(), cancel)?;
    let selected_hits = u64::try_from(response.hits.len()).unwrap_or(u64::MAX);
    let projection_fields = response.hits.iter().fold(0u64, |total, hit| {
        let fields = u64::try_from(hit.fields.len()).unwrap_or(u64::MAX);
        total.saturating_add(fields)
    });
    Ok(WorkCounters {
        segments_visited: None,
        candidates_examined: None,
        documents_decoded: None,
        selected_hits: Some(selected_hits),
        projection_fields: Some(projection_fields),
        sort_comparisons: None,
        group_updates: None,
        logical_memory_peak_bytes: None,
    })
}

// ---------------------------------------------------------------------------
// Eight-row golden fixture (a test-local copy of the canonical PR15A rows)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct Row {
    key: &'static str,
    title: &'static str,
    host: &'static str,
    n: i64,
    ts: i64,
    ip: &'static str,
    severity: Option<i64>,
    tags: Option<&'static [&'static str]>,
}

const ROWS: [Row; 8] = [
    Row {
        key: "a0",
        title: "alpha beta",
        host: "h1",
        n: 10,
        ts: 1000,
        ip: "10.0.0.1",
        severity: Some(1),
        tags: Some(&["red", "blue"]),
    },
    Row {
        key: "a1",
        title: "alpha",
        host: "h2",
        n: 20,
        ts: 2000,
        ip: "10.0.0.2",
        severity: Some(2),
        tags: Some(&["blue"]),
    },
    Row {
        key: "a2",
        title: "beta",
        host: "h1",
        n: 30,
        ts: 3000,
        ip: "192.0.2.1",
        severity: Some(3),
        tags: Some(&[]),
    },
    Row {
        key: "a3",
        title: "gamma",
        host: "h3",
        n: 40,
        ts: 4000,
        ip: "2001:db8::1",
        severity: None,
        tags: None,
    },
    Row {
        key: "b0",
        title: "alpha gamma",
        host: "h1",
        n: 50,
        ts: 5000,
        ip: "10.0.1.1",
        severity: Some(2),
        tags: Some(&["red"]),
    },
    Row {
        key: "b1",
        title: "beta gamma",
        host: "h2",
        n: 60,
        ts: 6000,
        ip: "192.0.2.2",
        severity: Some(4),
        tags: None,
    },
    Row {
        key: "b2",
        title: "delta",
        host: "h3",
        n: 70,
        ts: 7000,
        ip: "2001:db8::2",
        severity: Some(0),
        tags: Some(&[]),
    },
    Row {
        key: "b3",
        title: "alpha",
        host: "h2",
        n: 80,
        ts: 8000,
        ip: "10.0.0.8",
        severity: Some(5),
        tags: Some(&["green"]),
    },
];

fn body(row: &Row) -> JsonValue {
    let mut entries = vec![(
        "severity".to_owned(),
        match row.severity {
            Some(value) => JsonValue::Number(JsonNumber::I64(value)),
            None => JsonValue::Null,
        },
    )];
    if let Some(tags) = row.tags {
        entries.push((
            "tags".to_owned(),
            JsonValue::Array(
                tags.iter()
                    .map(|tag| JsonValue::String((*tag).to_owned()))
                    .collect(),
            ),
        ));
    }
    JsonValue::Object(entries)
}

fn document(row: &Row) -> Document {
    let mut document = Document::new(DocumentKey::new(row.key).expect("row key"));
    for (field, value) in [
        ("title", FieldValue::Text(row.title.to_owned())),
        ("host", FieldValue::Keyword(row.host.to_owned())),
        ("n", FieldValue::I64(row.n)),
        ("ts", FieldValue::Timestamp(Timestamp::from_micros(row.ts))),
        ("ip", FieldValue::Ip(row.ip.parse().expect("row ip"))),
        ("body", FieldValue::Json(body(row))),
    ] {
        document
            .insert(field, FieldValues::Single(value))
            .expect("row insert");
    }
    document
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
                "body",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "ip",
                FieldType::IpAddress,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        Some("ts".into()),
    )
    .expect("diagnostic schema")
}

fn fixture() -> (Arc<dyn Directory>, Index, Schema, AnalyzerRegistry) {
    let schema = schema();
    let registry = AnalyzerRegistry::builtin();
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema.clone(), registry.clone())
        .expect("create diagnostic index");
    {
        let mut writer = index.writer().expect("diagnostic writer");
        for row in &ROWS[..4] {
            writer.insert(document(row)).expect("diagnostic insert");
        }
        writer.flush().expect("diagnostic flush");
        for row in &ROWS[4..] {
            writer.insert(document(row)).expect("diagnostic insert");
        }
        writer.flush().expect("diagnostic flush");
        writer.commit().expect("diagnostic commit");
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema.clone(), registry.clone())
        .expect("reopen diagnostic index");
    (directory, reopened, schema, registry)
}

fn request(query: Query, k: usize) -> UnifiedRequest {
    UnifiedRequest::new(query, TopK::new(k).expect("top-k"))
}

// ---------------------------------------------------------------------------
// Adversarial counter tests
// ---------------------------------------------------------------------------

#[test]
fn counter_absent_query_selects_zero() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let request = request(
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("zzzz_absent_15b".into()),
        },
        100,
    );
    let counters = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request,
        &crate::analysis::NeverCancel,
    )
    .expect("absent search");
    assert_eq!(counters.selected_hits, Some(0));
    assert_eq!(counters.projection_fields, Some(0));
}

#[test]
fn counter_match_all_top_k_three_selects_exactly_three() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let request = request(Query::MatchAll, 3);
    let counters = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request,
        &crate::analysis::NeverCancel,
    )
    .expect("match-all search");
    assert_eq!(counters.selected_hits, Some(3));
    // Three hits x six stored fields (title, body, n, host, ip, ts).
    assert_eq!(counters.projection_fields, Some(18));

    let response = UnifiedSearcher::new(
        snapshot.as_ref(),
        &schema,
        &registry,
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &crate::analysis::NeverCancel)
    .expect("repeat search");
    assert_eq!(response.total_hits, 8, "truncation must not change total");
    assert_eq!(response.hits.len(), 3);
}

#[test]
fn counter_fields_projection_emits_exactly_four_events() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let mut request = request(Query::MatchAll, 2);
    request.projection = Projection::Fields(vec!["host".into(), "n".into()]);
    let counters = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request,
        &crate::analysis::NeverCancel,
    )
    .expect("projection search");
    assert_eq!(counters.selected_hits, Some(2));
    assert_eq!(
        counters.projection_fields,
        Some(4),
        "two hits times two requested stored fields"
    );
}

#[test]
fn counter_repeated_query_is_deterministic() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let request = request(Query::MatchAll, 5);
    let first = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request,
        &crate::analysis::NeverCancel,
    )
    .expect("first search");
    let second = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request,
        &crate::analysis::NeverCancel,
    )
    .expect("second search");
    assert_eq!(first, second);
}

#[test]
fn counter_cancelled_query_is_not_a_completed_selection() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let cancel = crate::analysis::CancellationFlag::new();
    cancel.cancel();
    let result = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request(Query::MatchAll, 3),
        &cancel,
    );
    assert!(
        matches!(result, Err(SearchError::Cancelled)),
        "cancelled query must not report a completed selection: {result:?}"
    );
}

#[test]
fn counter_invalid_query_is_not_a_completed_selection() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let result = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request(
            Query::Term {
                field: "missing_field".into(),
                value: FieldValue::I64(1),
            },
            3,
        ),
        &crate::analysis::NeverCancel,
    );
    assert!(
        matches!(result, Err(SearchError::Query(_))),
        "invalid query must not report a completed selection: {result:?}"
    );
}

#[test]
fn unavailable_counters_are_not_instrumented() {
    let (_directory, index, schema, registry) = fixture();
    let snapshot = index.snapshot();
    let counters = measure(
        snapshot.as_ref(),
        &schema,
        &registry,
        &request(Query::MatchAll, 1),
        &crate::analysis::NeverCancel,
    )
    .expect("match-all search");
    assert_eq!(counters.segments_visited, None);
    assert_eq!(counters.candidates_examined, None);
    assert_eq!(counters.documents_decoded, None);
    assert_eq!(counters.sort_comparisons, None);
    assert_eq!(counters.group_updates, None);
    assert_eq!(counters.logical_memory_peak_bytes, None);
    assert!(counters.selected_hits.is_some());
    assert!(counters.projection_fields.is_some());
}
