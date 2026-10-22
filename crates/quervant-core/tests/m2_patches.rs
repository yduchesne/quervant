//! M2 lossless explicit-key partial-update integration tests (QMA-001 / M2).
//!
//! Verticals covered here:
//!
//! * `M2-V01` local in-memory full slice: staged update, refresh, pinned PIT,
//!   commit, reopen, untouched/updated lexical/typed/JSON/geo queries and
//!   five-state stored projections.
//! * `M2-V02` local error/atomicity slice: shape, applicability, source
//!   reconstruction, cancellation and budget failures leave no state.
//! * `M2-V03` remote fake slice: admission performs no remote I/O, commit
//!   publishes the updated generation, cold reopen and durable replay work.
//! * `M2-V04` real RustFS slice (ignored; requires the documented environment).
//!
//! The real local filesystem restart path is exercised by
//! [`m2_v02_filesystem_restart_preserves_untouched_fields`] in addition to the
//! in-memory vertical.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::{BudgetKind, Budgets};
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey,
};
use quervant_core::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationCommand, MutationRejection,
    MutationTarget, PatchOperation, QueryMutationSelector, ReconstructionFailure,
};
use quervant_core::contract::query::{Bound, GeoBoundingBox, JsonPathExpr, Query};
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexError, IndexLimits, ReaderSnapshot};
use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};
use quervant_objectstore::{FakeObjectStore, ObjectStoreCapabilities};

static DIRS: AtomicU64 = AtomicU64::new(0);

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
                FieldOptions::new(false, false, true),
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
    .expect("schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).expect("key")
}

fn json(kind: &str) -> JsonValue {
    JsonValue::Object(vec![(
        "kind".to_owned(),
        JsonValue::String(kind.to_owned()),
    )])
}

fn document(key_value: &str) -> Document {
    let mut document = Document::new(key(key_value));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha beta".to_owned())),
        )
        .unwrap();
    document
        .insert(
            "body",
            FieldValues::Single(FieldValue::Text("original body".to_owned())),
        )
        .unwrap();
    document
        .insert(
            "tag",
            FieldValues::Multi(vec![
                FieldValue::Keyword("red".to_owned()),
                FieldValue::Keyword("blue".to_owned()),
            ]),
        )
        .unwrap();
    document
        .insert("n", FieldValues::Single(FieldValue::I64(7)))
        .unwrap();
    document
        .insert("score", FieldValues::Single(FieldValue::F64(1.25)))
        .unwrap();
    document
        .insert(
            "when",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1_000))),
        )
        .unwrap();
    document
        .insert("meta", FieldValues::Single(FieldValue::Json(json("a"))))
        .unwrap();
    document
        .insert(
            "point",
            FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(0.0, 0.0).unwrap())),
        )
        .unwrap();
    document
        .insert("nullable", FieldValues::Single(FieldValue::I64(5)))
        .unwrap();
    document
        .insert(
            "empty_multi",
            FieldValues::Single(FieldValue::Keyword("present".to_owned())),
        )
        .unwrap();
    document
}

fn update_patch() -> DocumentPatch {
    DocumentPatch {
        operations: vec![
            PatchOperation::Set {
                field: "title".to_owned(),
                values: FieldValues::Single(FieldValue::Text("gamma delta".to_owned())),
            },
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
                values: FieldValues::Single(FieldValue::Json(json("b"))),
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
    }
}

fn update_command() -> MutationCommand {
    MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(update_patch()),
    )
}

fn unified(
    snapshot: &ReaderSnapshot,
    request: &UnifiedRequest,
) -> quervant_core::search::UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn keys(snapshot: &ReaderSnapshot, query: Query) -> Vec<String> {
    let mut out: Vec<String> = unified(
        snapshot,
        &UnifiedRequest::new(query, TopK::new(50).unwrap()),
    )
    .hits
    .into_iter()
    .map(|hit| hit.key.as_str().to_owned())
    .collect();
    out.sort();
    out
}

fn projected(snapshot: &ReaderSnapshot, fields: Vec<String>) -> UnifiedResponse {
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(10).unwrap());
    request.projection = Projection::Fields(fields);
    unified(snapshot, &request)
}

fn lexical(value: &str) -> Query {
    Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text(value.to_owned()),
    }
}

fn body_term(value: &str) -> Query {
    Query::Term {
        field: "body".to_owned(),
        value: FieldValue::Text(value.to_owned()),
    }
}

fn range() -> Query {
    Query::Range {
        field: "n".to_owned(),
        lower: Bound::Included(FieldValue::I64(8)),
        upper: Bound::Included(FieldValue::I64(10)),
    }
}

fn json_kind(value: &str) -> Query {
    Query::JsonPathEquals {
        field: "meta".to_owned(),
        path: JsonPathExpr::parse("$.kind").expect("path"),
        value: FieldValue::Keyword(value.to_owned()),
    }
}

fn geo_around(lon: f64, lat: f64) -> Query {
    Query::GeoBoundingBox {
        field: "point".to_owned(),
        bbox: GeoBoundingBox::new(lon - 1.0, lat - 1.0, lon + 1.0, lat + 1.0).unwrap(),
    }
}

fn temp_path(name: &str) -> std::path::PathBuf {
    let n = DIRS.fetch_add(1, Ordering::SeqCst);
    std::env::temp_dir().join(format!("quervant-m2-{}-{name}-{n}", std::process::id()))
}

fn assert_updated_queries(snapshot: &ReaderSnapshot) {
    assert!(keys(snapshot, lexical("alpha")).is_empty());
    assert!(keys(snapshot, body_term("original")).is_empty());
    assert_eq!(keys(snapshot, lexical("gamma")), vec!["a".to_owned()]);
    assert_eq!(keys(snapshot, body_term("new")), vec!["a".to_owned()]);
    assert_eq!(keys(snapshot, range()), vec!["a".to_owned()]);
    assert_eq!(keys(snapshot, json_kind("b")), vec!["a".to_owned()]);
    assert!(keys(snapshot, json_kind("a")).is_empty());
    assert_eq!(keys(snapshot, geo_around(10.0, 20.0)), vec!["a".to_owned()]);
    assert!(keys(snapshot, geo_around(0.0, 0.0)).is_empty());
}

fn assert_original_queries(snapshot: &ReaderSnapshot) {
    assert_eq!(keys(snapshot, lexical("alpha")), vec!["a".to_owned()]);
    assert_eq!(keys(snapshot, body_term("original")), vec!["a".to_owned()]);
    assert!(keys(snapshot, lexical("gamma")).is_empty());
    assert!(keys(snapshot, range()).is_empty());
    assert_eq!(keys(snapshot, json_kind("a")), vec!["a".to_owned()]);
    assert_eq!(keys(snapshot, geo_around(0.0, 0.0)), vec!["a".to_owned()]);
}

// ---------------------------------------------------------------------------
// M2-V01 — local in-memory lossless update, refresh, commit and reopen
// ---------------------------------------------------------------------------

#[test]
fn m2_v01_local_lossless_update_refresh_pit_commit_reopen() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(document("a")).unwrap();
    writer.commit().unwrap();
    let pinned_before = writer.pin().unwrap();
    let before = writer.reader();
    assert_original_queries(&before);

    let batch = MutationBatch::new(vec![update_command()])
        .with_idempotency_key(IdempotencyKey::new("m2-v01").unwrap());
    let cancel = CancellationFlag::new();
    let first = writer.apply_batch(&batch, &cancel).unwrap();
    assert_eq!(first.outcomes.len(), 1);
    assert_eq!(first.outcomes[0].matched, 1);
    assert_eq!(first.outcomes[0].keys[0].key, key("a"));
    assert_eq!(first.outcomes[0].keys[0].revision, Some(2));
    assert!(!first.outcomes[0].keys[0].replayed);

    // The update is admitted but not visible to an old reader until refresh.
    assert_original_queries(&before);
    assert_original_queries(pinned_before.snapshot());
    assert_original_queries(&writer.reader());

    let refreshed = writer.refresh().unwrap();
    assert_updated_queries(&refreshed);
    assert_original_queries(pinned_before.snapshot());

    // Untouched stored fields survive, and patched null/empty/multi states are
    // visible as exact field states.
    let projected_fields = projected(
        &refreshed,
        vec![
            "title".to_owned(),
            "body".to_owned(),
            "tag".to_owned(),
            "score".to_owned(),
            "when".to_owned(),
            "meta".to_owned(),
            "point".to_owned(),
            "nullable".to_owned(),
            "empty_multi".to_owned(),
        ],
    );
    let hit = projected_fields
        .hits
        .iter()
        .find(|hit| hit.key == key("a"))
        .expect("projected hit");
    let field = |name: &str| {
        hit.fields
            .iter()
            .find(|(field, _)| field == name)
            .map(|(_, values)| values)
            .expect("field")
    };
    assert_eq!(
        field("title"),
        &FieldValues::Single(FieldValue::Text("gamma delta".to_owned()))
    );
    assert_eq!(
        field("body"),
        &FieldValues::Single(FieldValue::Text("new body".to_owned()))
    );
    assert_eq!(
        field("tag"),
        &FieldValues::Multi(vec![
            FieldValue::Keyword("green".to_owned()),
            FieldValue::Keyword("yellow".to_owned()),
        ])
    );
    assert_eq!(
        field("score"),
        &FieldValues::Single(FieldValue::F64(1.25)),
        "untouched stored+columnar field"
    );
    assert_eq!(
        field("when"),
        &FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1_000))),
        "untouched stored+columnar timestamp"
    );
    assert_eq!(field("nullable"), &FieldValues::ExplicitNull);
    assert_eq!(field("empty_multi"), &FieldValues::Empty);

    writer.commit().unwrap();
    assert_updated_queries(&writer.reader());
    assert_original_queries(pinned_before.snapshot());
    writer.close().unwrap();

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = reopened.writer().unwrap();
    assert_updated_queries(&writer.reader());
    assert_original_queries(pinned_before.snapshot());

    // Durable replay after commit/reopen returns the exact original result and
    // does not add a revision, even though the original source is superseded.
    let before_replay = (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
    );
    let replay = writer.apply_batch(&batch, &cancel).unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].keys[0].revision, Some(2));
    assert!(replay.outcomes[0].keys[0].replayed);
    assert_eq!(
        (
            writer.generation(),
            writer.pending_mutations(),
            writer.pending_documents(),
        ),
        before_replay
    );
}

#[test]
fn m2_v02_filesystem_restart_preserves_untouched_fields() {
    let root = temp_path("restart");
    std::fs::create_dir_all(&root).unwrap();
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&root).unwrap());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(document("a")).unwrap();
    writer.flush().unwrap();
    writer.commit().unwrap();

    let batch = MutationBatch::new(vec![update_command()]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
    writer.flush().unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry()).unwrap();
    let writer = reopened.writer().unwrap();
    assert_updated_queries(&writer.reader());
    let projected_fields = projected(
        &writer.reader(),
        vec!["score".to_owned(), "when".to_owned()],
    );
    let hit = projected_fields
        .hits
        .iter()
        .find(|hit| hit.key == key("a"))
        .expect("projected hit");
    assert_eq!(hit.fields[0].1, FieldValues::Single(FieldValue::F64(1.25)));
    assert_eq!(
        hit.fields[1].1,
        FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1_000)))
    );
    writer.close().unwrap();
    let _ = std::fs::remove_dir_all(&root);
}

// ---------------------------------------------------------------------------
// M2-V02 — typed failures and atomicity through the public API
// ---------------------------------------------------------------------------

type WriterState = (usize, usize, u64, Option<u64>);

fn assert_no_state(writer: &mut quervant_core::index::IndexWriter, before: WriterState) {
    assert_eq!(state(writer), before);
}

fn state(writer: &mut quervant_core::index::IndexWriter) -> WriterState {
    (
        writer.pending_mutations(),
        writer.pending_documents(),
        writer.reader().stored_key_set().expect("stored keys").len() as u64,
        writer.generation(),
    )
}

#[test]
fn m2_v02_public_errors_are_typed_and_atomic() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(document("a")).unwrap();
    writer.commit().unwrap();
    let before = state(&mut writer);

    let malformed = [
        (
            DocumentPatch {
                operations: Vec::new(),
            },
            "empty",
        ),
        (
            DocumentPatch {
                operations: vec![PatchOperation::Set {
                    field: "title".to_owned(),
                    values: FieldValues::Absent,
                }],
            },
            "set-absent",
        ),
        (
            DocumentPatch {
                operations: vec![PatchOperation::Unset {
                    field: "missing".to_owned(),
                }],
            },
            "unknown-field",
        ),
    ];
    for (patch, label) in malformed {
        let batch = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(patch),
        )]);
        let error = writer
            .apply_batch(&batch, &CancellationFlag::new())
            .expect_err(label);
        match label {
            "unknown-field" => assert!(matches!(
                error,
                IndexError::Contract(quervant_core::contract::QueryError::InvalidDocument(
                    quervant_core::contract::DocumentError::UnknownField { .. }
                ))
            )),
            _ => assert!(matches!(
                error,
                IndexError::MutationRejected {
                    rejection: MutationRejection::InvalidBatch { .. }
                }
            )),
        }
        assert_no_state(&mut writer, before);
    }

    // Absent key.
    let absent = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("absent")),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "title".to_owned(),
            }],
        }),
    )]);
    assert!(matches!(
        writer.apply_batch(&absent, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::ActionNotApplicable { .. }
        })
    ));
    assert_no_state(&mut writer, before);

    // Multi-unique-key Update.
    let multi = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Keys(vec![key("a"), key("b")]),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "title".to_owned(),
            }],
        }),
    )]);
    assert!(matches!(
        writer.apply_batch(&multi, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::UnsupportedTargetAction { .. }
        })
    ));
    assert_no_state(&mut writer, before);

    // Query target remains reserved.
    let query = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(QueryMutationSelector {
            query: Query::MatchAll,
            max_matches: 1,
            expected_generation: None,
        }),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "title".to_owned(),
            }],
        }),
    )]);
    assert!(matches!(
        writer.apply_batch(&query, &CancellationFlag::new()),
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::UnsupportedTargetAction { .. }
        })
    ));
    assert_no_state(&mut writer, before);

    // A late failure after an earlier valid update leaves no state.
    let late = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Set {
                    field: "title".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("first".to_owned())),
                }],
            }),
        ),
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Set {
                    field: "n".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("wrong".to_owned())),
                }],
            }),
        ),
    ]);
    assert!(matches!(
        writer.apply_batch(&late, &CancellationFlag::new()),
        Err(IndexError::Contract(
            quervant_core::contract::QueryError::InvalidDocument(
                quervant_core::contract::DocumentError::TypeMismatch { .. }
            )
        ))
    ));
    assert_no_state(&mut writer, before);

    // Cancellation.
    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    assert!(matches!(
        writer.apply_batch(&MutationBatch::new(vec![update_command()]), &cancelled),
        Err(IndexError::Cancelled)
    ));
    assert_no_state(&mut writer, before);
}

#[test]
fn m2_v02_indexed_only_physical_source_is_rejected_schema_wide() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let indexed_only_schema = Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "lost",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .unwrap();
    let index = Index::create(
        Arc::clone(&directory),
        indexed_only_schema.clone(),
        registry(),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    let mut source = Document::new(key("a"));
    source
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha".to_owned())),
        )
        .unwrap();
    writer.insert(source).unwrap();
    writer.commit().unwrap();
    let before = state(&mut writer);
    let patch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Set {
                field: "title".to_owned(),
                values: FieldValues::Single(FieldValue::Text("beta".to_owned())),
            }],
        }),
    )]);
    let error = writer
        .apply_batch(&patch, &CancellationFlag::new())
        .unwrap_err();
    assert!(matches!(
        error,
        IndexError::MutationRejected {
            rejection: MutationRejection::ReconstructionUnavailable {
                field: Some(field),
                reason: ReconstructionFailure::UnrecoverableField,
                ..
            }
        } if field == "lost"
    ));
    assert_no_state(&mut writer, before);
}

#[test]
fn m2_v02_source_byte_budget_rejects_before_decode() {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(
        Arc::clone(&directory),
        schema(),
        registry(),
        IndexLimits::new().with_max_snapshot_bytes(1),
    )
    .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(document("a")).unwrap();
    writer.flush().unwrap();
    let before = state(&mut writer);
    let error = writer
        .apply_batch(
            &MutationBatch::new(vec![update_command()]),
            &CancellationFlag::new(),
        )
        .unwrap_err();
    assert!(matches!(
        error,
        IndexError::ResourceLimit {
            limit: 1,
            requested
        } if requested > 1
    ));
    assert_no_state(&mut writer, before);
}

// ---------------------------------------------------------------------------
// M2-F01 — projected patch-result budgeting
// ---------------------------------------------------------------------------

fn exact_document_budget(bytes: usize) -> Budgets {
    Budgets::new()
        .with(
            BudgetKind::DocumentBytes,
            u64::try_from(bytes).expect("document size fits u64"),
        )
        .expect("budget")
}

fn projected_fields(snapshot: &ReaderSnapshot) -> Vec<(String, FieldValues)> {
    projected(
        snapshot,
        vec![
            "title".to_owned(),
            "body".to_owned(),
            "tag".to_owned(),
            "score".to_owned(),
            "when".to_owned(),
            "meta".to_owned(),
            "point".to_owned(),
            "nullable".to_owned(),
            "empty_multi".to_owned(),
        ],
    )
    .hits
    .into_iter()
    .find(|hit| hit.key == key("a"))
    .expect("projected hit")
    .fields
}

fn shrink_patch() -> DocumentPatch {
    DocumentPatch {
        operations: vec![PatchOperation::Set {
            field: "title".to_owned(),
            values: FieldValues::Single(FieldValue::Text("gamma".to_owned())),
        }],
    }
}

#[test]
fn m2_f01_t11_late_over_limit_update_rejects_whole_batch_and_retries() {
    let seed = document("a");
    let limits = IndexLimits::new().with_budgets(exact_document_budget(seed.approx_size()));
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(seed).unwrap();
    writer.commit().unwrap();
    let before = state(&mut writer);

    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(shrink_patch()),
        ),
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Set {
                    field: "title".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("x".repeat(4_096))),
                }],
            }),
        ),
    ]);
    let error = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert_no_state(&mut writer, before);

    let retry = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(shrink_patch()),
    )]);
    let response = writer
        .apply_batch(&retry, &CancellationFlag::new())
        .unwrap();
    assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
    let refreshed = writer.refresh().unwrap();
    assert_eq!(keys(&refreshed, lexical("gamma")), vec!["a".to_owned()]);
    assert!(keys(&refreshed, lexical("alpha")).is_empty());
}

#[test]
fn m2_f01_t12_exact_limit_shrink_commits_and_reopens_with_queries() {
    let seed = document("a");
    let limits = IndexLimits::new().with_budgets(exact_document_budget(seed.approx_size()));
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(seed).unwrap();
    writer.commit().unwrap();

    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(shrink_patch()),
    )]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_with_limits(directory, schema(), registry(), limits).unwrap();
    let writer = reopened.writer().unwrap();
    assert_eq!(
        keys(&writer.reader(), lexical("gamma")),
        vec!["a".to_owned()]
    );
    assert!(keys(&writer.reader(), lexical("alpha")).is_empty());
    assert_eq!(
        keys(&writer.reader(), body_term("original")),
        vec!["a".to_owned()]
    );
    let fields = projected_fields(&writer.reader());
    assert_eq!(
        fields
            .iter()
            .find(|(name, _)| name == "title")
            .map(|(_, values)| values),
        Some(&FieldValues::Single(FieldValue::Text("gamma".to_owned())))
    );
}

#[test]
fn m2_f01_t13_exact_limit_update_replays_after_reopen() {
    let seed = document("a");
    let limits = IndexLimits::new().with_budgets(exact_document_budget(seed.approx_size()));
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer.insert(seed).unwrap();
    writer.commit().unwrap();

    let token = IdempotencyKey::new("m2-f01-replay").unwrap();
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(shrink_patch()),
    )])
    .with_idempotency_key(token.clone());
    let first = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    writer.commit().unwrap();
    writer.close().unwrap();

    let reopened = Index::open_with_limits(directory, schema(), registry(), limits).unwrap();
    let mut writer = reopened.writer().unwrap();
    let before = state(&mut writer);
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, first.outcomes[0].matched);
    assert_eq!(
        replay.outcomes[0].keys[0].revision,
        first.outcomes[0].keys[0].revision
    );
    assert!(replay.outcomes[0].keys[0].replayed);
    assert_no_state(&mut writer, before);

    let conflicting = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(DocumentPatch {
            operations: vec![PatchOperation::Unset {
                field: "title".to_owned(),
            }],
        }),
    )])
    .with_idempotency_key(token);
    assert!(matches!(
        writer.apply_batch(&conflicting, &CancellationFlag::new()),
        Err(IndexError::IdempotencyConflict { .. })
    ));
    assert_no_state(&mut writer, before);
}

#[test]
fn m2_f01_t14_pending_flushed_committed_sources_produce_equivalent_patch_results() {
    let seed = document("a");
    let limits = IndexLimits::new().with_budgets(exact_document_budget(seed.approx_size()));
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Update(shrink_patch()),
    )]);

    fn run(limits: IndexLimits, batch: &MutationBatch, stage: &str) -> Vec<(String, FieldValues)> {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create_with_limits(directory, schema(), registry(), limits).unwrap();
        let mut writer = index.writer().unwrap();
        writer.insert(document("a")).unwrap();
        match stage {
            "pending" => {}
            "flushed" => {
                writer.flush().unwrap();
            }
            "committed" => {
                writer.commit().unwrap();
            }
            _ => panic!("unknown stage"),
        }
        let response = writer.apply_batch(batch, &CancellationFlag::new()).unwrap();
        assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
        let snapshot = writer.refresh().unwrap();
        assert_eq!(keys(&snapshot, lexical("gamma")), vec!["a".to_owned()]);
        assert!(keys(&snapshot, lexical("alpha")).is_empty());
        projected_fields(&snapshot)
    }

    let pending = run(limits.clone(), &batch, "pending");
    let flushed = run(limits.clone(), &batch, "flushed");
    let committed = run(limits, &batch, "committed");
    assert_eq!(pending, flushed);
    assert_eq!(pending, committed);
}

// ---------------------------------------------------------------------------
// M2-V03 — remote fake admission and publication
// ---------------------------------------------------------------------------

fn remote_config(name: &str) -> RemoteConfig {
    RemoteConfig::new(
        RemoteKeyPrefix::parse(format!("m2/{name}-{}", std::process::id())).unwrap(),
        temp_path(name),
    )
    .with_transfer(
        RemoteTransferConfig::default()
            .with_range_threshold(256 * 1024)
            .with_chunk_size(32 * 1024)
            .with_max_aggregate_response_bytes(2 * 1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16),
    )
}

fn remote_fake() -> Arc<FakeObjectStore> {
    Arc::new(FakeObjectStore::new(
        ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
    ))
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    futures::executor::block_on(future)
}

#[test]
fn m2_v03_remote_fake_update_makes_no_admission_io_and_reopens() {
    let store = remote_fake();
    let config = remote_config("v03");
    let index = block_on(RemoteIndex::create(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let batch = MutationBatch::new(vec![update_command()])
        .with_idempotency_key(IdempotencyKey::new("m2-v03").unwrap());
    {
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a")).unwrap();
        block_on(writer.commit()).unwrap();
        let puts = store.put_calls();
        let gets = store.get_calls();
        let response = writer
            .apply_batch(&batch, &CancellationFlag::new())
            .unwrap();
        assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
        assert_eq!(store.put_calls(), puts, "admission must not write remotely");
        assert_eq!(store.get_calls(), gets, "admission must not read remotely");
        block_on(writer.commit()).unwrap();
        assert!(store.put_calls() > puts);
    }

    let reader_index = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config.clone(),
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    assert_updated_queries(&reader_index.snapshot());

    let reopened = block_on(RemoteIndex::open_existing(
        Arc::clone(&store),
        config,
        schema(),
        registry(),
        IndexLimits::default(),
    ))
    .unwrap();
    let mut writer = block_on(reopened.writer()).unwrap();
    let puts = store.put_calls();
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].keys[0].revision, Some(2));
    assert_eq!(store.put_calls(), puts);
}

// ---------------------------------------------------------------------------
// M2-V04 — real RustFS (ignored; requires the documented environment)
// ---------------------------------------------------------------------------

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

    fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("m2-rustfs".to_owned())
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

    fn remote_config_for(prefix: &str, name: &str) -> RemoteConfig {
        RemoteConfig::new(
            RemoteKeyPrefix::parse(prefix).expect("prefix"),
            temp_path(name),
        )
        .with_transfer(
            RemoteTransferConfig::default()
                .with_range_threshold(256 * 1024)
                .with_chunk_size(32 * 1024)
                .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16),
        )
    }

    #[test]
    #[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
    fn m2_v04_real_rustfs_patch_reopen_replay() {
        run(async move {
            let (endpoint, bucket, access, secret, region) = require_env();
            let store = Arc::new(
                S3ObjectStore::new(S3Config::rustfs(endpoint, region, bucket, access, secret))
                    .expect("valid RustFS config"),
            );
            store.create_bucket_if_absent().await.expect("bucket");

            let run_tag = format!(
                "m2-v04-{}-{}",
                std::process::id(),
                DIRS.fetch_add(1, Ordering::SeqCst)
            );
            let prefix = format!("m2/{run_tag}");
            let config = remote_config_for(&prefix, "v04");

            let index = RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("create remote");
            {
                let mut writer = index.writer().await.expect("writer");
                writer.insert(document("a")).expect("insert");
                writer.commit().await.expect("commit baseline");
            }

            let batch = MutationBatch::new(vec![update_command()])
                .with_idempotency_key(IdempotencyKey::new(format!("{run_tag}-token")).unwrap());
            let cancel = CancellationFlag::new();
            let first = {
                let mut writer = index.writer().await.expect("writer");
                let response = writer.apply_batch(&batch, &cancel).expect("admit update");
                assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
                writer.commit().await.expect("commit update");
                response
            };

            // Cold bootstrap must recover the full updated document from RustFS,
            // including untouched stored fields.
            let cold = RemoteIndex::open_existing(
                Arc::clone(&store),
                remote_config_for(&prefix, "v04-cold"),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("cold open");
            let snapshot = cold.snapshot();
            assert_updated_queries(&snapshot);
            let projected_fields = projected(
                &snapshot,
                vec!["score".to_owned(), "when".to_owned(), "nullable".to_owned()],
            );
            let hit = projected_fields
                .hits
                .iter()
                .find(|hit| hit.key == key("a"))
                .expect("projected hit");
            assert_eq!(hit.fields[0].1, FieldValues::Single(FieldValue::F64(1.25)));
            assert_eq!(
                hit.fields[1].1,
                FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1_000)))
            );
            assert_eq!(hit.fields[2].1, FieldValues::ExplicitNull);

            // Durable replay after a cold reopen, then delete the source and
            // replay again: the original response must still be returned.
            let reopened = RemoteIndex::open_existing(
                Arc::clone(&store),
                remote_config_for(&prefix, "v04-replay"),
                schema(),
                registry(),
                IndexLimits::default(),
            )
            .await
            .expect("replay open");
            let mut writer = reopened.writer().await.expect("writer");
            let replay = writer.apply_batch(&batch, &cancel).expect("replay");
            assert!(replay.replayed);
            assert_eq!(
                replay.outcomes[0].keys[0].revision,
                first.outcomes[0].keys[0].revision
            );
            writer
                .apply_batch(
                    &MutationBatch::new(vec![MutationCommand::new(
                        MutationTarget::Key(key("a")),
                        MutationAction::Delete,
                    )]),
                    &cancel,
                )
                .expect("delete");
            writer.commit().await.expect("commit delete");
            let replay_after_delete = writer.apply_batch(&batch, &cancel).expect("replay");
            assert!(replay_after_delete.replayed);
            assert_eq!(
                replay_after_delete.outcomes[0].keys[0].revision,
                first.outcomes[0].keys[0].revision
            );

            let conflicting = MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(DocumentPatch {
                    operations: vec![PatchOperation::Unset {
                        field: "title".to_owned(),
                    }],
                }),
            )])
            .with_idempotency_key(IdempotencyKey::new(format!("{run_tag}-token")).unwrap());
            assert!(matches!(
                writer.apply_batch(&conflicting, &cancel),
                Err(IndexError::IdempotencyConflict { .. })
            ));
        });
    }
}
