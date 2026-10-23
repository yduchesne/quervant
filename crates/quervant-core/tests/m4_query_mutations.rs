//! M4 query-targeted update, replace and restricted upsert integration tests.
//!
//! Coverage map (see `docs/pr-artifacts/m4/implementation-evidence.md`):
//! T01–T05 update/replace, T06–T14 restricted upsert and overlap/conflict rules,
//! T15–T16 match bounds and ambiguity precedence, T17–T18 reconstruction and
//! cancellation, T19–T20 durable replay (including the zero-match fallback),
//! T23–T25 PIT/filesystem, T27 remote admission, T28–T32 cap, tombstone,
//! precondition and fingerprint-conflict boundaries, T33–T35 shape/validation
//! and resource failures and T37 scored/M3 regression. T21/T22 fingerprint
//! byte-compatibility goldens live in `index::mutation_state` unit tests where
//! the crate-private fingerprint encoder is reachable.

mod pr14_common;

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use pr14_common::{doc, set, set_multi};
use quervant_core::analysis::{Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Document, DocumentKey, FieldValues, IdempotencyKey};
use quervant_core::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationBatchResponse, MutationCommand,
    MutationKeyOutcome, MutationPrecondition, MutationRejection, MutationTarget, PatchOperation,
    QueryMutationSelector, ReconstructionFailure,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::contract::value::{FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexError, IndexLimits, IndexWriter, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

/// Local M4 schema: every field is either stored or columnar, so a live
/// document is always losslessly reconstructable for patch/replace. (The shared
/// PR 14 schema intentionally contains an indexed-only `raw` field, which is
/// covered separately by the reconstruction-failure test T17.)
fn schema() -> quervant_core::contract::schema::Schema {
    use quervant_core::contract::document::Cardinality;
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use quervant_core::contract::value::FieldType;
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
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "score",
                FieldType::F64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "when",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "meta",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "point",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "nullable",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "empty_multi",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .expect("m4 schema")
}

fn registry() -> quervant_core::analysis::AnalyzerRegistry {
    quervant_core::analysis::AnalyzerRegistry::builtin()
}

// ---------------------------------------------------------------------------
// Fixtures and helpers
// ---------------------------------------------------------------------------

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).expect("key")
}

fn json_num(member: &str, value: i64) -> JsonValue {
    JsonValue::Object(vec![(
        member.to_owned(),
        JsonValue::Number(JsonNumber::I64(value)),
    )])
}

/// A fully-populated document over every `pr14_common` schema field.
fn task(id: &str, title: &str, n: i64) -> Document {
    let mut document = doc(id);
    set(&mut document, "title", FieldValue::Text(title.to_owned()));
    set(
        &mut document,
        "body",
        FieldValue::Text("original body".to_owned()),
    );
    set_multi(
        &mut document,
        "tag",
        vec![
            FieldValue::Keyword("red".to_owned()),
            FieldValue::Keyword("blue".to_owned()),
        ],
    );
    set(&mut document, "n", FieldValue::I64(n));
    set(&mut document, "score", FieldValue::F64(1.25));
    set(
        &mut document,
        "when",
        FieldValue::Timestamp(Timestamp::from_micros(1_000)),
    );
    set(&mut document, "meta", FieldValue::Json(json_num("k", 1)));
    set(
        &mut document,
        "point",
        FieldValue::GeoPoint(GeoPoint::new(0.0, 0.0).unwrap()),
    );
    set(&mut document, "nullable", FieldValue::I64(5));
    set(
        &mut document,
        "empty_multi",
        FieldValue::Keyword("present".to_owned()),
    );
    document
}

fn selector(query: Query, max_matches: u64) -> QueryMutationSelector {
    QueryMutationSelector {
        query,
        max_matches,
        expected_generation: None,
    }
}

fn title_term(text: &str) -> Query {
    Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text(text.to_owned()),
    }
}

fn setup(documents: Vec<Document>) -> (Arc<dyn Directory>, IndexWriter) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    for document in documents {
        writer.insert(document).unwrap();
    }
    writer.commit().unwrap();
    (directory, writer)
}

fn setup_with_limits(
    documents: Vec<Document>,
    limits: IndexLimits,
) -> (Arc<dyn Directory>, IndexWriter) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits).unwrap();
    let mut writer = index.writer().unwrap();
    for document in documents {
        writer.insert(document).unwrap();
        writer.flush().unwrap();
        writer.commit().unwrap();
    }
    (directory, writer)
}

fn unified(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
) -> quervant_core::search::UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn live_keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let mut keys: Vec<String> = unified(
        snapshot,
        &UnifiedRequest::new(query, TopK::new(100).unwrap()),
    )
    .hits
    .into_iter()
    .map(|hit| hit.key.as_str().to_owned())
    .collect();
    keys.sort();
    keys
}

fn all_live_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    live_keys(snapshot, Query::MatchAll)
}

type ProjectedFields = BTreeMap<String, BTreeMap<String, FieldValues>>;

/// Independent projection oracle: stored field states per key.
fn projected(snapshot: &ReaderSnapshot, fields: &[&str]) -> ProjectedFields {
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(100).unwrap());
    request.projection =
        Projection::Fields(fields.iter().map(|field| (*field).to_owned()).collect());
    let response = unified(snapshot, &request);
    response
        .hits
        .into_iter()
        .map(|hit| {
            (
                hit.key.as_str().to_owned(),
                hit.fields.into_iter().collect::<BTreeMap<_, _>>(),
            )
        })
        .collect()
}

fn field<'a>(
    projected: &'a ProjectedFields,
    document: &str,
    name: &str,
) -> Option<&'a FieldValues> {
    projected.get(document).and_then(|fields| fields.get(name))
}

fn outcome_keys(response: &MutationBatchResponse) -> Vec<Vec<String>> {
    response
        .outcomes
        .iter()
        .map(|outcome| {
            outcome
                .keys
                .iter()
                .map(|key: &MutationKeyOutcome| key.key.as_str().to_owned())
                .collect()
        })
        .collect()
}

fn outcome_revisions(response: &MutationBatchResponse) -> Vec<Vec<Option<u64>>> {
    response
        .outcomes
        .iter()
        .map(|outcome| outcome.keys.iter().map(|key| key.revision).collect())
        .collect()
}

type WriterState = (Option<u64>, usize, usize, usize, Vec<String>);

fn writer_state(writer: &IndexWriter) -> WriterState {
    (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
        writer.flushed_segments(),
        all_live_keys(&writer.reader()),
    )
}

fn assert_unchanged(writer: &mut IndexWriter, before: &WriterState) {
    assert_eq!(&writer_state(writer), before);
}

fn update_patch() -> DocumentPatch {
    DocumentPatch {
        operations: vec![PatchOperation::Set {
            field: "title".to_owned(),
            values: FieldValues::Single(FieldValue::Text("patched".to_owned())),
        }],
    }
}

fn query_update(selector: QueryMutationSelector, patch: DocumentPatch) -> MutationBatch {
    MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector),
        MutationAction::Update(patch),
    )])
}

fn query_replace(selector: QueryMutationSelector, template: Document) -> MutationBatch {
    MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector),
        MutationAction::Replace(template),
    )])
}

fn query_upsert(
    selector: QueryMutationSelector,
    replacement: Document,
    fallback: Document,
) -> MutationBatch {
    MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector),
        MutationAction::QueryUpsert {
            replacement,
            fallback,
        },
    )])
}

fn token(batch: MutationBatch, value: &str) -> MutationBatch {
    batch.with_idempotency_key(IdempotencyKey::new(value).unwrap())
}

static DIRS: AtomicU64 = AtomicU64::new(0);

fn temp_path(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-m4-{}-{name}-{n}", std::process::id()))
}

// ---------------------------------------------------------------------------
// T01–T05 — query update and replacement
// ---------------------------------------------------------------------------

#[test]
fn m4_t01_query_update_patches_every_selected_key_only() {
    let (_directory, mut writer) = setup(vec![
        task("a", "target alpha", 1),
        task("b", "target beta", 2),
        task("c", "target gamma", 3),
        task("z", "unselected", 4),
    ]);
    let cancel = CancellationFlag::new();
    // Independent expectation: only the three committed "target" documents.
    let response = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 3);
    assert_eq!(
        outcome_keys(&response),
        [vec!["a".to_owned(), "b".to_owned(), "c".to_owned()]]
    );
    assert_eq!(
        outcome_revisions(&response),
        [vec![Some(2), Some(2), Some(2)]]
    );
    for outcome in &response.outcomes[0].keys {
        assert_eq!(
            outcome.intent,
            quervant_core::contract::document::MutationIntent::Upsert
        );
        assert!(!outcome.replayed);
    }

    let view = writer.refresh().unwrap();
    assert_eq!(
        live_keys(&view, title_term("patched")),
        ["a".to_owned(), "b".to_owned(), "c".to_owned()]
    );
    assert!(live_keys(&view, title_term("target")).is_empty());
    // The unselected document keeps its original title.
    assert_eq!(live_keys(&view, title_term("unselected")), ["z".to_owned()]);
    let projected = projected(&view, &["title"]);
    assert_eq!(
        field(&projected, "z", "title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "unselected".to_owned()
        )))
    );
}

#[test]
fn m4_t02_zero_match_update_is_a_noop_without_revisions() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    let before = writer_state(&writer);
    let response = writer
        .apply_batch(
            &query_update(selector(title_term("nothing"), 10), update_patch()),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 0);
    assert!(response.outcomes[0].keys.is_empty());
    assert!(!response.replayed);
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t03_query_update_preserves_every_untouched_field_state() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let patch = DocumentPatch {
        operations: vec![
            PatchOperation::Set {
                field: "body".to_owned(),
                values: FieldValues::Single(FieldValue::Text("new body".to_owned())),
            },
            PatchOperation::Set {
                field: "tag".to_owned(),
                values: FieldValues::Multi(vec![
                    FieldValue::Keyword("green".to_owned()),
                    FieldValue::Keyword("yellow".to_owned()),
                ]),
            },
            PatchOperation::Set {
                field: "n".to_owned(),
                values: FieldValues::Single(FieldValue::I64(9)),
            },
            PatchOperation::Set {
                field: "meta".to_owned(),
                values: FieldValues::Single(FieldValue::Json(json_num("k", 2))),
            },
            PatchOperation::Set {
                field: "point".to_owned(),
                values: FieldValues::Single(FieldValue::GeoPoint(
                    GeoPoint::new(10.0, 20.0).unwrap(),
                )),
            },
            PatchOperation::Set {
                field: "nullable".to_owned(),
                values: FieldValues::ExplicitNull,
            },
            PatchOperation::Set {
                field: "empty_multi".to_owned(),
                values: FieldValues::Empty,
            },
        ],
    };
    let response = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), patch),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 1);
    let view = writer.refresh().unwrap();
    let projected = projected(
        &view,
        &[
            "title",
            "body",
            "tag",
            "n",
            "score",
            "when",
            "meta",
            "point",
            "nullable",
            "empty_multi",
        ],
    );
    // Patched states are exactly as supplied.
    assert_eq!(
        field(&projected, "a", "body"),
        Some(&FieldValues::Single(FieldValue::Text(
            "new body".to_owned()
        )))
    );
    assert_eq!(
        field(&projected, "a", "tag"),
        Some(&FieldValues::Multi(vec![
            FieldValue::Keyword("green".to_owned()),
            FieldValue::Keyword("yellow".to_owned()),
        ]))
    );
    assert_eq!(
        field(&projected, "a", "n"),
        Some(&FieldValues::Single(FieldValue::I64(9)))
    );
    assert_eq!(
        field(&projected, "a", "meta"),
        Some(&FieldValues::Single(FieldValue::Json(json_num("k", 2))))
    );
    assert_eq!(
        field(&projected, "a", "point"),
        Some(&FieldValues::Single(FieldValue::GeoPoint(
            GeoPoint::new(10.0, 20.0).unwrap()
        )))
    );
    assert_eq!(
        field(&projected, "a", "nullable"),
        Some(&FieldValues::ExplicitNull)
    );
    assert_eq!(
        field(&projected, "a", "empty_multi"),
        Some(&FieldValues::Empty)
    );
    // Untouched fields survive exactly, including typed/columnar state.
    assert_eq!(
        field(&projected, "a", "title"),
        Some(&FieldValues::Single(FieldValue::Text("target".to_owned())))
    );
    assert_eq!(
        field(&projected, "a", "score"),
        Some(&FieldValues::Single(FieldValue::F64(1.25)))
    );
    assert_eq!(
        field(&projected, "a", "when"),
        Some(&FieldValues::Single(FieldValue::Timestamp(
            Timestamp::from_micros(1_000)
        )))
    );
    assert!(live_keys(&view, title_term("original")).is_empty());
}

#[test]
fn m4_t04_query_replace_uses_template_fields_and_keeps_selected_keys() {
    let (_directory, mut writer) = setup(vec![
        task("a", "target one", 1),
        task("b", "target two", 2),
        task("c", "target three", 3),
        task("z", "unselected", 4),
    ]);
    let cancel = CancellationFlag::new();
    // The template's own key is inert and differs from every selected key.
    let mut template = doc("other");
    set(
        &mut template,
        "title",
        FieldValue::Text("template title".to_owned()),
    );
    set(&mut template, "n", FieldValue::I64(42));
    let response = writer
        .apply_batch(
            &query_replace(selector(title_term("target"), 10), template),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 3);
    assert_eq!(
        outcome_keys(&response),
        [vec!["a".to_owned(), "b".to_owned(), "c".to_owned()]]
    );

    let view = writer.refresh().unwrap();
    // Every selected identity is preserved (no "other" document appears) and
    // the template fields are installed.
    assert_eq!(
        all_live_keys(&view),
        [
            "a".to_owned(),
            "b".to_owned(),
            "c".to_owned(),
            "z".to_owned()
        ]
    );
    let projected = projected(&view, &["title", "n"]);
    for selected in ["a", "b", "c"] {
        assert_eq!(
            field(&projected, selected, "title"),
            Some(&FieldValues::Single(FieldValue::Text(
                "template title".to_owned()
            )))
        );
        assert_eq!(
            field(&projected, selected, "n"),
            Some(&FieldValues::Single(FieldValue::I64(42)))
        );
    }
    assert_eq!(
        field(&projected, "z", "title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "unselected".to_owned()
        )))
    );
}

#[test]
fn m4_t05_query_replace_removes_fields_omitted_by_the_template() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let mut template = doc("template");
    set(&mut template, "title", FieldValue::Text("kept".to_owned()));
    let response = writer
        .apply_batch(
            &query_replace(selector(title_term("target"), 10), template),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 1);
    let view = writer.refresh().unwrap();
    let projected = projected(&view, &["title", "body", "tag", "n"]);
    assert_eq!(
        field(&projected, "a", "title"),
        Some(&FieldValues::Single(FieldValue::Text("kept".to_owned())))
    );
    // Omitted template fields are absent, not stale.
    // Omitted template fields project as explicitly absent, never stale values.
    assert_eq!(field(&projected, "a", "body"), Some(&FieldValues::Absent));
    assert_eq!(field(&projected, "a", "tag"), Some(&FieldValues::Absent));
    assert_eq!(field(&projected, "a", "n"), Some(&FieldValues::Absent));
    assert!(live_keys(&view, title_term("original")).is_empty());
}

// ---------------------------------------------------------------------------
// T06–T10 — restricted query upsert
// ---------------------------------------------------------------------------

#[test]
fn m4_t06_query_upsert_one_match_replaces_selected_key_and_ignores_fallback() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("template-key");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let mut fallback = doc("fallback");
    set(
        &mut fallback,
        "title",
        FieldValue::Text("fallback".to_owned()),
    );
    let response = writer
        .apply_batch(
            &query_upsert(selector(title_term("target"), 10), replacement, fallback),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 1);
    assert_eq!(outcome_keys(&response), [vec!["a".to_owned()]]);
    assert_eq!(outcome_revisions(&response), [vec![Some(2)]]);
    assert_eq!(
        response.outcomes[0].keys[0].intent,
        quervant_core::contract::document::MutationIntent::Upsert
    );

    let view = writer.refresh().unwrap();
    let projected = projected(&view, &["title"]);
    assert_eq!(
        field(&projected, "a", "title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "replacement".to_owned()
        )))
    );
    assert!(!projected.contains_key("template-key"));
    assert!(
        !projected.contains_key("fallback"),
        "fallback is not inserted"
    );
}

#[test]
fn m4_t07_query_upsert_two_matches_is_ambiguous_and_atomic() {
    let (_directory, mut writer) =
        setup(vec![task("a", "target one", 1), task("b", "target two", 2)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let mut fallback = doc("fallback");
    set(
        &mut fallback,
        "title",
        FieldValue::Text("fallback".to_owned()),
    );
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert(selector(title_term("target"), 10), replacement, fallback),
            &cancel,
        )
        .expect_err("ambiguous upsert must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::AmbiguousQueryUpsert { matched: 2 }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t08_query_upsert_zero_matches_inserts_fallback_with_matched_zero() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let fallback = task("fallback", "fallback title", 7);
    let response = writer
        .apply_batch(
            &query_upsert(
                selector(title_term("nothing"), 10),
                replacement,
                fallback.clone(),
            ),
            &cancel,
        )
        .unwrap();
    // Selector cardinality is zero; the fallback is one explicit Insert outcome.
    assert_eq!(response.outcomes[0].matched, 0);
    assert_eq!(outcome_keys(&response), [vec!["fallback".to_owned()]]);
    assert_eq!(
        response.outcomes[0].keys[0].intent,
        quervant_core::contract::document::MutationIntent::Insert
    );
    assert_eq!(response.outcomes[0].keys[0].revision, Some(1));

    let view = writer.refresh().unwrap();
    assert_eq!(
        live_keys(&view, title_term("fallback")),
        ["fallback".to_owned()]
    );
    let projected = projected(&view, &["title", "n", "body"]);
    // The fallback document is inserted unaltered, at its own key.
    assert_eq!(
        field(&projected, "fallback", "title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "fallback title".to_owned()
        )))
    );
    assert_eq!(
        field(&projected, "fallback", "n"),
        Some(&FieldValues::Single(FieldValue::I64(7)))
    );
    assert_eq!(
        field(&projected, "fallback", "body"),
        Some(&FieldValues::Single(FieldValue::Text(
            "original body".to_owned()
        )))
    );
    assert!(!projected.contains_key("replacement"));
    assert_eq!(
        field(&projected, "a", "title"),
        Some(&FieldValues::Single(FieldValue::Text("alpha".to_owned())))
    );
}

#[test]
fn m4_t09_zero_match_fallback_live_in_committed_state_rejects() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1), task("fallback", "live", 2)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let fallback = task("fallback", "would overwrite", 9);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert(selector(title_term("nothing"), 10), replacement, fallback),
            &cancel,
        )
        .expect_err("live fallback must reject");
    assert!(
        matches!(&error, IndexError::DuplicateDocument { key } if key == "fallback"),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t10_zero_match_fallback_live_only_in_pending_state_rejects() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    // The fallback key exists only in the uncommitted writer-effective state.
    writer.insert(task("fallback", "pending live", 5)).unwrap();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let fallback = task("fallback", "would overwrite", 9);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert(selector(title_term("nothing"), 10), replacement, fallback),
            &cancel,
        )
        .expect_err("pending live fallback must reject");
    assert!(
        matches!(&error, IndexError::DuplicateDocument { key } if key == "fallback"),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

// ---------------------------------------------------------------------------
// T11–T14 — staleness, overlap and committed-snapshot selection
// ---------------------------------------------------------------------------

#[test]
fn m4_t11_selected_key_with_pending_newer_revision_rejects() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    // A pending, uncommitted update makes the committed selection stale.
    writer
        .apply_batch(
            &query_update(selector(Query::MatchAll, 10), update_patch()),
            &cancel,
        )
        .unwrap();
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &cancel,
        )
        .expect_err("stale selection must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed {
                    expected: MutationPrecondition::ExpectedRevision(1),
                    ..
                }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t12_earlier_explicit_command_overlapping_a_selected_key_rejects() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let batch = MutationBatch::new(vec![
        MutationCommand::new(MutationTarget::Key(key("a")), MutationAction::Delete),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Replace(task("other", "template", 0)),
        ),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&batch, &cancel)
        .expect_err("overlap must reject the whole batch");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t12b_convenience_delegations_build_one_typed_command_each() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1), task("b", "other", 2)]);
    let cancel = CancellationFlag::new();

    // update_by_query / replace_by_query / upsert_by_query are the same planner
    // with exactly one typed command each.
    let updated = writer
        .update_by_query(selector(title_term("target"), 10), update_patch(), &cancel)
        .unwrap();
    assert_eq!(updated.outcomes.len(), 1);
    assert_eq!(updated.outcomes[0].matched, 1);
    assert_eq!(outcome_keys(&updated), [vec!["a".to_owned()]]);
    // Query selection is committed-snapshot based, so commit before the next
    // query observes the patched title.
    writer.commit().unwrap();

    let mut template = doc("template");
    set(
        &mut template,
        "title",
        FieldValue::Text("replaced".to_owned()),
    );
    let replaced = writer
        .replace_by_query(selector(title_term("patched"), 10), template, &cancel)
        .unwrap();
    assert_eq!(replaced.outcomes.len(), 1);
    assert_eq!(replaced.outcomes[0].matched, 1);
    assert_eq!(outcome_keys(&replaced), [vec!["a".to_owned()]]);

    let inserted = writer
        .upsert_by_query(
            selector(title_term("nothing"), 10),
            {
                let mut replacement = doc("replacement");
                set(
                    &mut replacement,
                    "title",
                    FieldValue::Text("replacement".to_owned()),
                );
                replacement
            },
            task("fallback", "fallback", 1),
            &cancel,
        )
        .unwrap();
    assert_eq!(inserted.outcomes.len(), 1);
    assert_eq!(inserted.outcomes[0].matched, 0);
    assert_eq!(
        inserted.outcomes[0].keys[0].intent,
        quervant_core::contract::document::MutationIntent::Insert
    );

    let view = writer.refresh().unwrap();
    assert_eq!(live_keys(&view, title_term("replaced")), ["a".to_owned()]);
    assert_eq!(
        live_keys(&view, title_term("fallback")),
        ["fallback".to_owned()]
    );
    assert_eq!(live_keys(&view, title_term("other")), ["b".to_owned()]);
}

#[test]
fn m4_t13_two_query_commands_selecting_the_same_key_reject() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Update(update_patch()),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Delete,
        ),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&batch, &cancel)
        .expect_err("overlapping selectors must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t14_query_does_not_select_a_key_inserted_earlier_in_the_batch() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    // The staged insert matches the selector but is not in the committed
    // batch-initial snapshot.
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("b")),
            MutationAction::Insert(task("b", "target", 2)),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Update(update_patch()),
        ),
    ]);
    let response = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(response.outcomes[1].matched, 0);
    assert!(response.outcomes[1].keys.is_empty());
    let view = writer.refresh().unwrap();
    let projected = projected(&view, &["title"]);
    assert_eq!(
        field(&projected, "b", "title"),
        Some(&FieldValues::Single(FieldValue::Text("target".to_owned()))),
        "the staged insert is untouched by the query command"
    );
    assert_eq!(
        field(&projected, "a", "title"),
        Some(&FieldValues::Single(FieldValue::Text("alpha".to_owned())))
    );
}

// ---------------------------------------------------------------------------
// T15–T16 — match bounds and ambiguity precedence
// ---------------------------------------------------------------------------

#[test]
fn m4_t15_query_bounds_fail_closed_without_truncation() {
    let (_directory, mut writer) = setup(vec![
        task("a", "target one", 1),
        task("b", "target two", 2),
        task("c", "target three", 3),
    ]);
    let cancel = CancellationFlag::new();

    // Exact bound succeeds with the complete match set.
    let exact = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 3), update_patch()),
            &cancel,
        )
        .unwrap();
    assert_eq!(exact.outcomes[0].matched, 3);
    writer.refresh().unwrap();

    // One over fails with the exact typed limit outcome.
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 2), update_patch()),
            &cancel,
        )
        .expect_err("one over the bound must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::MatchLimitExceeded {
                    limit: 2,
                    matched: 3
                }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);

    // A zero selector bound is an invalid selector, not a silent default.
    assert!(matches!(
        writer.apply_batch(
            &query_update(selector(Query::MatchAll, 0), update_patch()),
            &cancel
        ),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::InvalidBatch { .. }
        })
    ));

    // A globally configured zero match bound fails closed on the first match.
    let (_zero_directory, mut zero) = setup_with_limits(
        vec![task("a", "alpha", 1)],
        IndexLimits::default().with_max_query_matches(0),
    );
    assert!(matches!(
        zero.apply_batch(
            &query_update(selector(Query::MatchAll, 10), update_patch()),
            &cancel
        ),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::MatchLimitExceeded {
                limit: 0,
                matched: 1
            }
        })
    ));
}

#[test]
fn m4_t16_query_upsert_bound_one_two_matches_is_a_limit_not_ambiguity() {
    let (_directory, mut writer) =
        setup(vec![task("a", "target one", 1), task("b", "target two", 2)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let mut fallback = doc("fallback");
    set(
        &mut fallback,
        "title",
        FieldValue::Text("fallback".to_owned()),
    );
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert(selector(title_term("target"), 1), replacement, fallback),
            &cancel,
        )
        .expect_err("bound one must keep the limit precedence");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::MatchLimitExceeded {
                    limit: 1,
                    matched: 2
                }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

// ---------------------------------------------------------------------------
// T17–T18 — reconstruction and cancellation
// ---------------------------------------------------------------------------

fn indexed_only_schema() -> quervant_core::contract::schema::Schema {
    use quervant_core::contract::document::Cardinality;
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use quervant_core::contract::value::FieldType;
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            // Indexed only: no stored or columnar source to reconstruct.
            FieldDefinition::new(
                "ghost",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .expect("schema")
}

#[test]
fn m4_t17_query_update_rejects_an_unreconstructable_source() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), indexed_only_schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    let mut document = doc("a");
    set(
        &mut document,
        "title",
        FieldValue::Text("target".to_owned()),
    );
    set(
        &mut document,
        "ghost",
        FieldValue::Text("indexed".to_owned()),
    );
    writer.insert(document).unwrap();
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();
    let before = (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
    );
    let error = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &cancel,
        )
        .expect_err("indexed-only source must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ReconstructionUnavailable {
                    field: Some(ref field),
                    reason: ReconstructionFailure::UnrecoverableField,
                    ..
                }
            } if field == "ghost"
        ),
        "unexpected error {error:?}"
    );
    assert_eq!(
        (
            writer.generation(),
            writer.pending_mutations(),
            writer.pending_documents(),
        ),
        before
    );
    assert!(writer.pin().is_ok(), "writer remains usable");
}

/// Cancellation that reports `true` from the `skip + 1`-th poll onward.
struct TripAfter {
    skip: usize,
    polls: Arc<AtomicUsize>,
}

impl Cancellation for TripAfter {
    fn is_cancelled(&self) -> bool {
        self.polls.fetch_add(1, Ordering::SeqCst) >= self.skip
    }
}

/// Cancellation that never trips and counts polls.
struct CountPolls(Arc<AtomicUsize>);

impl Cancellation for CountPolls {
    fn is_cancelled(&self) -> bool {
        self.0.fetch_add(1, Ordering::SeqCst);
        false
    }
}

#[test]
fn m4_t18_cancellation_leaves_no_partial_admission() {
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &cancel
        ),
        Err(IndexError::Cancelled)
    ));
    assert_unchanged(&mut writer, &before);

    // Calibrate the number of cancellation polls for one successful query
    // update, then trip on the final poll (the per-key simulation checkpoint)
    // on an identical writer and assert the same no-change invariant.
    let polls = Arc::new(AtomicUsize::new(0));
    {
        let (directory, mut warm) = setup(vec![task("a", "target", 1)]);
        let counter = CountPolls(Arc::clone(&polls));
        warm.apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &counter,
        )
        .unwrap();
        drop(directory);
    }
    let total = polls.load(Ordering::SeqCst);
    assert!(total > 1, "the planner must poll cancellation repeatedly");

    let (directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let polls = Arc::new(AtomicUsize::new(0));
    let trip = TripAfter {
        skip: total - 1,
        polls: Arc::clone(&polls),
    };
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &trip,
        )
        .expect_err("the final checkpoint must observe cancellation");
    assert!(
        matches!(error, IndexError::Cancelled),
        "unexpected {error:?}"
    );
    assert_unchanged(&mut writer, &before);
    drop(directory);
}

// ---------------------------------------------------------------------------
// T19–T20 — durable replay, including the zero-match fallback
// ---------------------------------------------------------------------------

#[test]
fn m4_t19_replay_does_not_rerun_selection_after_the_match_set_changes() {
    let (_directory, mut writer) =
        setup(vec![task("a", "target one", 1), task("b", "target two", 2)]);
    let cancel = CancellationFlag::new();
    let batch = token(
        query_update(selector(title_term("target"), 10), update_patch()),
        "m4-t19",
    );
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes[0].matched, 2);
    writer.commit().unwrap();

    // New committed documents change the match set.
    writer.insert(task("c", "target three", 3)).unwrap();
    writer.commit().unwrap();
    assert_eq!(
        live_keys(&writer.reader(), title_term("target")),
        ["c".to_owned()]
    );

    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, 2);
    assert_eq!(
        outcome_keys(&replay),
        [vec!["a".to_owned(), "b".to_owned()]]
    );
    assert!(
        replay.outcomes[0]
            .keys
            .iter()
            .all(|outcome| outcome.replayed)
    );
    // The newly matching document is not patched by the replayed command.
    let view = writer.refresh().unwrap();
    let projected = projected(&view, &["title"]);
    assert_eq!(
        field(&projected, "c", "title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "target three".to_owned()
        )))
    );
}

#[test]
fn m4_t20_tokenized_zero_match_fallback_commit_reopen_and_replay() {
    let (directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let fallback = task("fallback", "fallback title", 7);
    let batch = token(
        query_upsert(
            selector(title_term("nothing"), 10),
            replacement,
            fallback.clone(),
        ),
        "m4-t20",
    );
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes[0].matched, 0);
    assert_eq!(outcome_keys(&first), [vec!["fallback".to_owned()]]);
    assert_eq!(first.outcomes[0].keys[0].revision, Some(1));
    writer.commit().unwrap();

    // A later committed change must not be re-selected on replay.
    writer.insert(task("b", "nothing", 2)).unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let state_before = writer_state(&writer);
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, 0);
    assert_eq!(outcome_keys(&replay), [vec!["fallback".to_owned()]]);
    assert_eq!(replay.outcomes[0].keys[0].revision, Some(1));
    assert_eq!(
        replay.outcomes[0].keys[0].intent,
        quervant_core::contract::document::MutationIntent::Insert
    );
    assert!(replay.outcomes[0].keys[0].replayed);
    assert_unchanged(&mut writer, &state_before);
    // Exactly one fallback document exists; replay inserted nothing.
    assert_eq!(
        live_keys(&writer.reader(), title_term("fallback")),
        ["fallback".to_owned()]
    );
    let projected = projected(&writer.reader(), &["title", "n"]);
    assert_eq!(
        field(&projected, "fallback", "n"),
        Some(&FieldValues::Single(FieldValue::I64(7)))
    );
}

// ---------------------------------------------------------------------------
// T23 — PIT isolation and one refresh visibility boundary
// ---------------------------------------------------------------------------

#[test]
fn m4_t23_pit_pinned_before_query_mutation_stays_immutable() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let before = writer.pin().unwrap();
    let original = writer.reader();
    assert_eq!(live_keys(&original, title_term("target")), ["a".to_owned()]);

    writer
        .apply_batch(
            &query_update(selector(title_term("target"), 10), update_patch()),
            &cancel,
        )
        .unwrap();
    // Admitted but not visible until refresh.
    assert_eq!(live_keys(&original, title_term("target")), ["a".to_owned()]);
    assert_eq!(
        live_keys(before.snapshot(), title_term("target")),
        ["a".to_owned()]
    );

    let refreshed = writer.refresh().unwrap();
    assert!(live_keys(&refreshed, title_term("target")).is_empty());
    assert_eq!(
        live_keys(&refreshed, title_term("patched")),
        ["a".to_owned()]
    );
    assert_eq!(
        live_keys(before.snapshot(), title_term("target")),
        ["a".to_owned()],
        "old PIT is immutable across refresh"
    );

    writer.commit().unwrap();
    assert_eq!(
        live_keys(&writer.reader(), title_term("patched")),
        ["a".to_owned()]
    );
    assert_eq!(
        live_keys(before.snapshot(), title_term("target")),
        ["a".to_owned()],
        "old PIT is immutable across commit"
    );
}

// ---------------------------------------------------------------------------
// T24 — mixed batch with a late failure admits no prefix
// ---------------------------------------------------------------------------

#[test]
fn m4_t24_mixed_batch_late_failure_leaves_no_prefix() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("new")),
            MutationAction::Insert(task("new", "new doc", 2)),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Replace(task("other", "template", 0)),
        ),
        MutationCommand::new(MutationTarget::Key(key("absent")), MutationAction::Delete)
            .with_precondition(MutationPrecondition::MustExist),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&batch, &cancel)
        .expect_err("late failure must reject the batch");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

// ---------------------------------------------------------------------------
// T25 — local filesystem commit/reopen for each M4 action
// ---------------------------------------------------------------------------

#[test]
fn m4_t25_filesystem_commit_and_reopen_for_each_m4_action() {
    let root = temp_path("fs");
    std::fs::create_dir_all(&root).unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(task("a", "target one", 1)).unwrap();
    writer.insert(task("b", "target two", 2)).unwrap();
    writer.insert(task("c", "other", 3)).unwrap();
    writer.commit().unwrap();
    let cancel = CancellationFlag::new();

    // Query update.
    let updated = writer
        .apply_batch(
            &token(
                query_update(selector(title_term("target"), 10), update_patch()),
                "m4-t25-update",
            ),
            &cancel,
        )
        .unwrap();
    assert_eq!(updated.outcomes[0].matched, 2);
    writer.commit().unwrap();

    // Query replace with a template whose key is not among the targets.
    let mut template = doc("template");
    set(
        &mut template,
        "title",
        FieldValue::Text("replaced".to_owned()),
    );
    let replaced = writer
        .apply_batch(
            &token(
                query_replace(selector(title_term("patched"), 10), template),
                "m4-t25-replace",
            ),
            &cancel,
        )
        .unwrap();
    assert_eq!(replaced.outcomes[0].matched, 2);
    writer.commit().unwrap();

    // Query upsert: zero-match fallback insert.
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("upserted".to_owned()),
    );
    let fallback = task("fallback", "fallback title", 9);
    let upserted = writer
        .apply_batch(
            &token(
                query_upsert(selector(title_term("nothing"), 10), replacement, fallback),
                "m4-t25-upsert",
            ),
            &cancel,
        )
        .unwrap();
    assert_eq!(upserted.outcomes[0].matched, 0);
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    let view = writer.reader();
    assert_eq!(
        live_keys(&view, title_term("replaced")),
        ["a".to_owned(), "b".to_owned()]
    );
    assert_eq!(
        live_keys(&view, title_term("fallback")),
        ["fallback".to_owned()]
    );
    assert_eq!(live_keys(&view, title_term("other")), ["c".to_owned()]);
    // Revisions survive the commit/reopen boundary.
    let update_replay = writer
        .apply_batch(
            &token(
                query_update(selector(title_term("target"), 10), update_patch()),
                "m4-t25-update",
            ),
            &cancel,
        )
        .unwrap();
    assert!(update_replay.replayed);
    assert_eq!(outcome_revisions(&update_replay), [vec![Some(2), Some(2)]]);
    let fallback_replay = writer
        .apply_batch(
            &token(
                query_upsert(
                    selector(title_term("nothing"), 10),
                    {
                        let mut replacement = doc("replacement");
                        set(
                            &mut replacement,
                            "title",
                            FieldValue::Text("upserted".to_owned()),
                        );
                        replacement
                    },
                    task("fallback", "fallback title", 9),
                ),
                "m4-t25-upsert",
            ),
            &cancel,
        )
        .unwrap();
    assert!(fallback_replay.replayed);
    assert_eq!(fallback_replay.outcomes[0].matched, 0);
    assert_eq!(
        outcome_keys(&fallback_replay),
        [vec!["fallback".to_owned()]]
    );
    writer.close().unwrap();
    let _ = std::fs::remove_dir_all(&root);
}

// ---------------------------------------------------------------------------
// T27 — remote admission performs no remote I/O
// ---------------------------------------------------------------------------

fn remote_config(name: &str) -> quervant_core::remote::RemoteConfig {
    quervant_core::remote::RemoteConfig::new(
        quervant_core::remote::RemoteKeyPrefix::parse(format!("m4/{name}-{}", std::process::id()))
            .unwrap(),
        std::env::temp_dir().join(format!("quervant-m4-remote-{name}-{}", std::process::id())),
    )
    .with_transfer(
        quervant_core::remote::RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024)
            .with_chunk_size(32 * 1024)
            .with_max_aggregate_response_bytes(2 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16),
    )
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

#[test]
fn m4_t27_remote_admission_performs_no_remote_io_and_replays() {
    use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

    let store = Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ));
    let config = remote_config("m4-t27");
    let index = block_on(quervant_core::remote::RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("upserted".to_owned()),
    );
    let upsert = token(
        query_upsert(
            selector(title_term("nothing"), 10),
            replacement,
            task("fallback", "fallback title", 7),
        ),
        "m4-t27-upsert",
    );
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(task("a", "target", 1)).unwrap();
        block_on(writer.commit()).unwrap();
        let puts = store.put_calls();
        let gets = store.get_calls();

        let updated = writer
            .update_by_query(selector(title_term("target"), 10), update_patch(), &cancel)
            .unwrap();
        assert_eq!(updated.outcomes[0].matched, 1);
        let inserted = writer.apply_batch(&upsert, &cancel).unwrap();
        assert_eq!(inserted.outcomes[0].matched, 0);
        assert_eq!(inserted.outcomes[0].keys[0].revision, Some(1));
        assert_eq!(store.put_calls(), puts, "admission must not write remotely");
        assert_eq!(store.get_calls(), gets, "admission must not read remotely");
        block_on(writer.commit()).unwrap();
        assert!(store.put_calls() > puts);
    }

    let reopened = block_on(quervant_core::remote::RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let view = reopened.snapshot();
    assert_eq!(live_keys(&view, title_term("patched")), ["a".to_owned()]);
    assert_eq!(
        live_keys(&view, title_term("fallback")),
        ["fallback".to_owned()]
    );
    let mut writer = block_on(reopened.writer()).unwrap();
    let puts = store.put_calls();
    let replay = writer.apply_batch(&upsert, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, 0);
    assert_eq!(store.put_calls(), puts);
}

// ---------------------------------------------------------------------------
// T28–T32 — caps, tombstones, overlap and fingerprint conflicts
// ---------------------------------------------------------------------------

#[test]
fn m4_t28_upsert_with_batch_key_limit_one_reports_the_limit_not_ambiguity() {
    let (_directory, mut writer) = setup_with_limits(
        vec![task("a", "target one", 1), task("b", "target two", 2)],
        IndexLimits::default().with_max_batch_keys(1),
    );
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let mut fallback = doc("fallback");
    set(
        &mut fallback,
        "title",
        FieldValue::Text("fallback".to_owned()),
    );
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert(selector(title_term("target"), 10), replacement, fallback),
            &cancel,
        )
        .expect_err("configured bound one must fail closed");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::MatchLimitExceeded {
                    limit: 1,
                    matched: 2
                }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t29_tombstoned_fallback_inserts_at_the_next_revision() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    // Create and tombstone the fallback key: revisions 1 (insert) and 2 (delete).
    writer.insert(task("fallback", "old", 1)).unwrap();
    writer.commit().unwrap();
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("fallback")),
                MutationAction::Delete,
            )]),
            &cancel,
        )
        .unwrap();
    writer.commit().unwrap();
    assert!(live_keys(&writer.reader(), title_term("old")).is_empty());

    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let response = writer
        .apply_batch(
            &query_upsert(
                selector(title_term("nothing"), 10),
                replacement,
                task("fallback", "revived", 3),
            ),
            &cancel,
        )
        .unwrap();
    assert_eq!(response.outcomes[0].matched, 0);
    assert_eq!(response.outcomes[0].keys[0].revision, Some(3));
    assert_eq!(
        response.outcomes[0].keys[0].intent,
        quervant_core::contract::document::MutationIntent::Insert
    );
    writer.refresh().unwrap();
    assert_eq!(
        live_keys(&writer.reader(), title_term("revived")),
        ["fallback".to_owned()]
    );
}

#[test]
fn m4_t30_earlier_command_touching_the_fallback_key_rejects_the_batch() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    // The earlier delete tombstones the fallback; the zero-match upsert must not
    // silently insert over that staged state.
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("fallback")),
            MutationAction::Insert(task("fallback", "staged", 1)),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("nothing"), 10)),
            MutationAction::QueryUpsert {
                replacement: {
                    let mut replacement = doc("replacement");
                    set(
                        &mut replacement,
                        "title",
                        FieldValue::Text("replacement".to_owned()),
                    );
                    replacement
                },
                fallback: task("fallback", "fallback title", 2),
            },
        ),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&batch, &cancel)
        .expect_err("staged fallback overlap must reject");
    assert!(
        matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ),
        "unexpected error {error:?}"
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t31_preconditions_apply_to_selected_and_fallback_cases() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();

    // Selected key: MustExist succeeds, MustNotExist rejects, a wrong expected
    // revision rejects.
    let must_exist = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Update(update_patch()),
        )
        .with_precondition(MutationPrecondition::MustExist),
    ]);
    assert_eq!(
        writer.apply_batch(&must_exist, &cancel).unwrap().outcomes[0].matched,
        1
    );
    // Commit so the next query's committed selection sees the new revision.
    writer.commit().unwrap();
    writer.refresh().unwrap();

    let before = writer_state(&writer);
    let must_not_exist = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("patched"), 10)),
            MutationAction::Update(update_patch()),
        )
        .with_precondition(MutationPrecondition::MustNotExist),
    ]);
    assert!(matches!(
        writer.apply_batch(&must_not_exist, &cancel),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    let wrong_revision = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("patched"), 10)),
            MutationAction::Update(update_patch()),
        )
        .with_precondition(MutationPrecondition::ExpectedRevision(99)),
    ]);
    assert!(matches!(
        writer.apply_batch(&wrong_revision, &cancel),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    assert_unchanged(&mut writer, &before);

    // Fallback key: MustExist fails on an absent key; MustNotExist succeeds.
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let must_exist_fallback = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("nothing"), 10)),
            MutationAction::QueryUpsert {
                replacement: replacement.clone(),
                fallback: task("fallback", "fallback", 1),
            },
        )
        .with_precondition(MutationPrecondition::MustExist),
    ]);
    assert!(matches!(
        writer.apply_batch(&must_exist_fallback, &cancel),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed { .. }
        })
    ));
    let must_not_exist_fallback = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("nothing"), 10)),
            MutationAction::QueryUpsert {
                replacement,
                fallback: task("fallback", "fallback", 1),
            },
        )
        .with_precondition(MutationPrecondition::MustNotExist),
    ]);
    let inserted = writer
        .apply_batch(&must_not_exist_fallback, &cancel)
        .unwrap();
    assert_eq!(inserted.outcomes[0].matched, 0);
    assert_eq!(inserted.outcomes[0].keys[0].revision, Some(1));
}

#[test]
fn m4_t32_replacement_and_fallback_each_change_the_idempotency_fingerprint() {
    let (_directory, mut writer) = setup(vec![task("a", "alpha", 1)]);
    let cancel = CancellationFlag::new();
    let mut replacement = doc("replacement");
    set(
        &mut replacement,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let fallback = task("fallback", "fallback title", 7);
    let batch = token(
        query_upsert(
            selector(title_term("nothing"), 10),
            replacement.clone(),
            fallback.clone(),
        ),
        "m4-t32",
    );
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes[0].matched, 0);

    // Changed replacement under the same token conflicts.
    let mut changed_replacement = replacement.clone();
    set(
        &mut changed_replacement,
        "title",
        FieldValue::Text("different replacement".to_owned()),
    );
    assert!(matches!(
        writer.apply_batch(
            &token(
                query_upsert(
                    selector(title_term("nothing"), 10),
                    changed_replacement,
                    fallback.clone(),
                ),
                "m4-t32",
            ),
            &cancel,
        ),
        Err(IndexError::IdempotencyConflict { .. })
    ));

    // Changed fallback fields conflict.
    let mut changed_fallback = fallback.clone();
    set(&mut changed_fallback, "n", FieldValue::I64(99));
    assert!(matches!(
        writer.apply_batch(
            &token(
                query_upsert(
                    selector(title_term("nothing"), 10),
                    replacement.clone(),
                    changed_fallback,
                ),
                "m4-t32",
            ),
            &cancel,
        ),
        Err(IndexError::IdempotencyConflict { .. })
    ));

    // The unchanged batch replays deterministically.
    let replay = writer
        .apply_batch(
            &token(
                query_upsert(selector(title_term("nothing"), 10), replacement, fallback),
                "m4-t32",
            ),
            &cancel,
        )
        .unwrap();
    assert!(replay.replayed);
    assert_eq!(outcome_keys(&replay), [vec!["fallback".to_owned()]]);
}

// ---------------------------------------------------------------------------
// T33–T35 — unsupported shapes, validation ordering and resource caps
// ---------------------------------------------------------------------------

#[test]
fn m4_t33_unsupported_target_action_pairs_are_typed() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let before = writer_state(&writer);
    let cases = [
        // Query + Insert.
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(selector(Query::MatchAll, 10)),
            MutationAction::Insert(task("b", "target", 2)),
        )]),
        // Query + ordinary Upsert.
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(selector(Query::MatchAll, 10)),
            MutationAction::Upsert(task("b", "target", 2)),
        )]),
        // Explicit key + QueryUpsert.
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::QueryUpsert {
                replacement: task("a", "x", 2),
                fallback: task("b", "y", 3),
            },
        )]),
    ];
    for batch in cases {
        assert!(
            matches!(
                writer.apply_batch(&batch, &cancel),
                Err(IndexError::MutationRejected {
                    rejection: MutationRejection::UnsupportedTargetAction { .. }
                })
            ),
            "every unsupported pair must be typed"
        );
    }
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m4_t34_validation_precedes_replay_lookup() {
    let (_directory, mut writer) = setup(vec![task("a", "target", 1)]);
    let cancel = CancellationFlag::new();
    let valid = token(
        query_update(selector(title_term("target"), 10), update_patch()),
        "m4-t34",
    );
    assert_eq!(
        writer.apply_batch(&valid, &cancel).unwrap().outcomes[0].matched,
        1
    );
    let before = writer_state(&writer);

    // Same token, malformed patch: validation wins over replay.
    let unknown_field = token(
        query_update(
            selector(title_term("patched"), 10),
            DocumentPatch {
                operations: vec![PatchOperation::Unset {
                    field: "unknown".to_owned(),
                }],
            },
        ),
        "m4-t34",
    );
    assert!(matches!(
        writer.apply_batch(&unknown_field, &cancel),
        Err(IndexError::Contract(
            quervant_core::contract::error::QueryError::InvalidDocument { .. }
        ))
    ));

    // Same token, malformed fallback template: validation wins over replay.
    let unknown_fallback = token(
        query_upsert(
            selector(title_term("nothing"), 10),
            {
                let mut replacement = doc("replacement");
                set(
                    &mut replacement,
                    "title",
                    FieldValue::Text("replacement".to_owned()),
                );
                replacement
            },
            {
                let mut fallback = doc("fallback");
                set(
                    &mut fallback,
                    "unknown",
                    FieldValue::Keyword("x".to_owned()),
                );
                fallback
            },
        ),
        "m4-t34",
    );
    assert!(matches!(
        writer.apply_batch(&unknown_fallback, &cancel),
        Err(IndexError::Contract(
            quervant_core::contract::error::QueryError::InvalidDocument { .. }
        ))
    ));
    assert_unchanged(&mut writer, &before);
    // The original token still replays after the rejected attempts.
    assert!(writer.apply_batch(&valid, &cancel).unwrap().replayed);
}

#[test]
fn m4_t35_query_resource_caps_fail_closed_without_state_change() {
    let cancel = CancellationFlag::new();

    // Pending-document cap.
    let (_directory, mut writer) = setup_with_limits(
        vec![task("a", "target one", 1), task("b", "target two", 2)],
        IndexLimits::default().with_max_pending_docs(1),
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(
            &query_update(selector(Query::MatchAll, 10), update_patch()),
            &cancel
        ),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Response-byte cap (the zero-match fallback is one key outcome).
    let (_directory, mut writer) = setup_with_limits(
        vec![task("a", "alpha", 1)],
        IndexLimits::default().with_max_batch_response_bytes(8),
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(
            &query_upsert(
                selector(title_term("nothing"), 10),
                {
                    let mut replacement = doc("replacement");
                    set(
                        &mut replacement,
                        "title",
                        FieldValue::Text("replacement".to_owned()),
                    );
                    replacement
                },
                task("fallback", "fallback", 1),
            ),
            &cancel,
        ),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Durable batch replay-key cap (one allowed outcome, two selected keys).
    let (_directory, mut writer) = setup_with_limits(
        vec![task("a", "target one", 1), task("b", "target two", 2)],
        IndexLimits::default().with_max_batch_replay_keys(1),
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(
            &query_update(selector(Query::MatchAll, 10), update_patch()),
            &cancel
        ),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Cumulative query-key cap: two query commands that each resolve one key
    // exceed a one-key batch budget.
    let (_directory, mut writer) = setup_with_limits(
        vec![task("a", "alpha", 1), task("b", "beta", 2)],
        IndexLimits::default().with_max_batch_keys(1),
    );
    let before = writer_state(&writer);
    let cumulative = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("alpha"), 10)),
            MutationAction::Update(update_patch()),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("beta"), 10)),
            MutationAction::Update(update_patch()),
        ),
    ]);
    assert!(matches!(
        writer.apply_batch(&cumulative, &cancel),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);
}

// ---------------------------------------------------------------------------
// T37 — scored search and M3 delete-by-query remain unchanged
// ---------------------------------------------------------------------------

#[test]
fn m4_t37_scored_search_and_delete_by_query_are_unaffected() {
    let (_directory, mut writer) = setup(vec![
        task("a", "target alpha", 1),
        task("b", "target beta", 2),
        task("c", "gamma", 3),
    ]);
    let cancel = CancellationFlag::new();
    let before = live_keys(&writer.reader(), title_term("target"));
    assert_eq!(before, ["a".to_owned(), "b".to_owned()]);

    // A query update over a disjoint selector leaves scored results identical.
    writer
        .apply_batch(
            &query_update(selector(title_term("gamma"), 10), update_patch()),
            &cancel,
        )
        .unwrap();
    writer.refresh().unwrap();
    assert_eq!(live_keys(&writer.reader(), title_term("target")), before);

    // M3 delete-by-query keeps its exact semantics after M4.
    let deleted = writer
        .delete_by_query(selector(title_term("target"), 10), &cancel)
        .unwrap();
    assert_eq!(deleted.outcomes[0].matched, 2);
    assert_eq!(
        outcome_keys(&deleted),
        [vec!["a".to_owned(), "b".to_owned()]]
    );
    writer.refresh().unwrap();
    assert!(live_keys(&writer.reader(), title_term("target")).is_empty());
    assert_eq!(
        live_keys(&writer.reader(), title_term("patched")),
        ["c".to_owned()]
    );
}

// ---------------------------------------------------------------------------
// T26 — real RustFS (ignored; authoritative environment required)
// ---------------------------------------------------------------------------

#[cfg(feature = "s3")]
#[test]
#[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
fn m4_t26_real_rustfs_query_mutations_reopen_and_replay() {
    real_rustfs::run(async {
        real_rustfs::m4_scenario().await;
    });
}

#[cfg(feature = "s3")]
mod real_rustfs {
    use super::*;
    use quervant_objectstore::{S3Config, S3ObjectStore};

    fn require_env() -> (String, String, String, String, String) {
        let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
            .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
        let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
            .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
        let access = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
            .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
        let secret = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
            .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
        let region =
            std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
        assert!(
            endpoint.starts_with("http://"),
            "real RustFS acceptance requires an http:// endpoint"
        );
        (endpoint, bucket, access, secret, region)
    }

    pub fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("m4-rustfs".to_owned())
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

    pub async fn m4_scenario() {
        let (endpoint, bucket, access, secret, region) = require_env();
        let store = Arc::new(
            S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                .expect("valid RustFS config"),
        );
        store.create_bucket_if_absent().await.expect("bucket");

        let run_tag = format!(
            "m4-t26-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let config = quervant_core::remote::RemoteConfig::new(
            quervant_core::remote::RemoteKeyPrefix::parse(format!("m4/{run_tag}")).unwrap(),
            std::env::temp_dir().join(format!("quervant-m4-rustfs-{run_tag}")),
        )
        .with_transfer(
            quervant_core::remote::RemoteTransferConfig::default()
                .with_range_threshold(256 * 1024)
                .with_chunk_size(32 * 1024)
                .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16),
        );

        let index = quervant_core::remote::RemoteIndex::create(
            Arc::clone(&store) as Arc<S3ObjectStore>,
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("create remote index");
        let cancel = CancellationFlag::new();
        let update = token(
            query_update(selector(title_term("target"), 10), update_patch()),
            &format!("{run_tag}-update"),
        );
        let mut template = doc("template");
        set(
            &mut template,
            "title",
            FieldValue::Text("replaced".to_owned()),
        );
        let replace = token(
            query_replace(selector(title_term("patched"), 10), template),
            &format!("{run_tag}-replace"),
        );
        let upsert = token(
            query_upsert(
                selector(title_term("nothing"), 10),
                {
                    let mut replacement = doc("replacement");
                    set(
                        &mut replacement,
                        "title",
                        FieldValue::Text("upserted".to_owned()),
                    );
                    replacement
                },
                task("fallback", "fallback title", 7),
            ),
            &format!("{run_tag}-upsert"),
        );
        {
            let mut writer = index.writer().await.expect("writer");
            for document in [
                task("a", "target one", 1),
                task("b", "target two", 2),
                task("c", "other", 3),
            ] {
                writer.insert(document).unwrap();
            }
            writer.commit().await.unwrap();

            let updated = writer.apply_batch(&update, &cancel).unwrap();
            assert_eq!(updated.outcomes[0].matched, 2);
            writer.commit().await.unwrap();
            let replaced = writer.apply_batch(&replace, &cancel).unwrap();
            assert_eq!(replaced.outcomes[0].matched, 2);
            writer.commit().await.unwrap();
            let inserted = writer.apply_batch(&upsert, &cancel).unwrap();
            assert_eq!(inserted.outcomes[0].matched, 0);
            assert_eq!(inserted.outcomes[0].keys[0].revision, Some(1));
            writer.commit().await.unwrap();
        }

        let reopened = quervant_core::remote::RemoteIndex::open_existing(
            Arc::clone(&store) as Arc<S3ObjectStore>,
            config,
            schema(),
            registry(),
            IndexLimits::default(),
        )
        .await
        .expect("reopen");
        let view = reopened.snapshot();
        assert_eq!(
            live_keys(&view, title_term("replaced")),
            ["a".to_owned(), "b".to_owned()]
        );
        assert_eq!(
            live_keys(&view, title_term("fallback")),
            ["fallback".to_owned()]
        );
        assert_eq!(live_keys(&view, title_term("other")), ["c".to_owned()]);
        let mut writer = reopened.writer().await.expect("writer");
        let replay = writer.apply_batch(&upsert, &cancel).unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.outcomes[0].matched, 0);
        assert_eq!(outcome_keys(&replay), [vec!["fallback".to_owned()]]);
    }
}
