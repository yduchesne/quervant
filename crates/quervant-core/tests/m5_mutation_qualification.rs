//! M5 mutation qualification: independent model, adversarial transitions and
//! durable replay across memory, real local filesystem and (ignored) RustFS.
//!
//! The expected state in this file is produced by the small `Oracle` state
//! machine below, never by the production writer planner or query selector.
//! Query targets in scripts are explicitly enumerated by the fixture, so the
//! production search engine is only the system under test.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};

use quervant_core::analysis::{AnalyzerRegistry, Cancellation, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent,
};
use quervant_core::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationBatchResponse, MutationCommand,
    MutationKeyOutcome, MutationPrecondition, MutationRejection, MutationTarget, PatchOperation,
    QueryMutationSelector,
};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{Projection, TopK};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{
    FieldType, FieldValue, GeoPoint, JsonNumber, JsonValue, Timestamp,
};
use quervant_core::index::{
    CURRENT_KEY, Index, IndexError, IndexLimits, IndexWriter, ReaderSnapshot,
};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedSearcher};
use quervant_core::storage::{
    Directory, FsDirectory, MemoryDirectory, ReadHandle, StorageError, StorageKey, StorageOp,
    WriteHandle,
};

// ---------------------------------------------------------------------------
// Fixtures and schema
// ---------------------------------------------------------------------------

const ALL_FIELDS: &[&str] = &[
    "title",
    "body",
    "n",
    "tag",
    "score",
    "when",
    "meta",
    "point",
    "nullable",
    "empty_multi",
];

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
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
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
    .expect("m5 schema")
}

fn indexed_only_schema() -> Schema {
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
                "raw",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
        ],
        None,
    )
    .expect("indexed-only schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn key(value: &str) -> DocumentKey {
    DocumentKey::new(value).expect("valid test key")
}

fn set(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("single value");
}

fn set_multi(document: &mut Document, field: &str, values: Vec<FieldValue>) {
    document
        .insert(field, FieldValues::Multi(values))
        .expect("multi value");
}

fn set_null(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::ExplicitNull)
        .expect("null value");
}

fn set_empty(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::Empty)
        .expect("empty value");
}

fn base_doc(id: &str, title: &str, n: i64) -> Document {
    let mut document = Document::new(key(id));
    set(&mut document, "title", FieldValue::Text(title.to_owned()));
    set(
        &mut document,
        "body",
        FieldValue::Text("original body".to_owned()),
    );
    set(&mut document, "n", FieldValue::I64(n));
    set_multi(
        &mut document,
        "tag",
        vec![
            FieldValue::Keyword("red".to_owned()),
            FieldValue::Keyword("blue".to_owned()),
        ],
    );
    set(&mut document, "score", FieldValue::F64(1.5));
    set(
        &mut document,
        "when",
        FieldValue::Timestamp(Timestamp::from_micros(1_000 + n)),
    );
    set(&mut document, "meta", FieldValue::Json(json_object("k", n)));
    set(
        &mut document,
        "point",
        FieldValue::GeoPoint(GeoPoint::new(0.5, 1.5).expect("geo point")),
    );
    set(&mut document, "nullable", FieldValue::I64(n));
    set(
        &mut document,
        "empty_multi",
        FieldValue::Keyword("present".to_owned()),
    );
    document
}

fn json_object(name: &str, value: i64) -> JsonValue {
    JsonValue::Object(vec![(
        name.to_owned(),
        JsonValue::Number(JsonNumber::I64(value)),
    )])
}

fn title_term(text: &str) -> Query {
    Query::Term {
        field: "title".to_owned(),
        value: FieldValue::Text(text.to_owned()),
    }
}

fn selector(query: Query, max_matches: u64) -> QueryMutationSelector {
    QueryMutationSelector {
        query,
        max_matches,
        expected_generation: None,
    }
}

fn patch(field: &str, value: FieldValue) -> DocumentPatch {
    DocumentPatch {
        operations: vec![PatchOperation::Set {
            field: field.to_owned(),
            values: FieldValues::Single(value),
        }],
    }
}

fn token(batch: MutationBatch, value: &str) -> MutationBatch {
    batch.with_idempotency_key(IdempotencyKey::new(value).expect("token"))
}

fn setup(docs: Vec<Document>) -> (Arc<dyn Directory>, IndexWriter) {
    setup_with(Arc::new(MemoryDirectory::new()), docs, IndexLimits::new())
}

fn setup_with(
    directory: Arc<dyn Directory>,
    docs: Vec<Document>,
    limits: IndexLimits,
) -> (Arc<dyn Directory>, IndexWriter) {
    let index = Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits)
        .expect("create index");
    let mut writer = index.writer().expect("writer");
    for document in docs {
        writer.insert(document).expect("seed insert");
    }
    writer.commit().expect("seed commit");
    (directory, writer)
}

fn reopen(directory: Arc<dyn Directory>, limits: IndexLimits) -> IndexWriter {
    let index =
        Index::open_with_limits(directory, schema(), registry(), limits).expect("reopen index");
    index.writer().expect("writer")
}

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn new(tag: &str) -> Self {
        let unique = format!(
            "quervant-m5-{tag}-{}-{}",
            std::process::id(),
            TEMP_COUNTER.fetch_add(1, Ordering::SeqCst)
        );
        let path = std::env::temp_dir().join(unique);
        std::fs::create_dir_all(&path).expect("temp directory");
        Self { path }
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn fs_directory(path: &Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("filesystem directory"))
}

// ---------------------------------------------------------------------------
// Observation helpers (production search is the system under test)
// ---------------------------------------------------------------------------

type Projected = BTreeMap<String, BTreeMap<String, FieldValues>>;

fn projected(snapshot: &ReaderSnapshot, fields: &[&str]) -> Projected {
    let mut request = UnifiedRequest::new(Query::MatchAll, TopK::new(256).expect("top-k"));
    request.projection =
        Projection::Fields(fields.iter().map(|field| (*field).to_owned()).collect());
    let response = UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search");
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

fn live_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    let request = UnifiedRequest::new(Query::MatchAll, TopK::new(256).expect("top-k"));
    let mut keys: Vec<String> =
        UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
            .search(&request, &Budgets::new(), &CancellationFlag::new())
            .expect("match-all search")
            .hits
            .into_iter()
            .map(|hit| hit.key.as_str().to_owned())
            .collect();
    keys.sort();
    keys
}

fn writer_state(writer: &IndexWriter) -> (Option<u64>, usize, usize, usize, Vec<String>) {
    (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
        writer.flushed_segments(),
        live_keys(&writer.reader()),
    )
}

fn assert_unchanged(
    writer: &mut IndexWriter,
    before: &(Option<u64>, usize, usize, usize, Vec<String>),
) {
    assert_eq!(&writer_state(writer), before);
}

fn response_keys(response: &MutationBatchResponse) -> Vec<Vec<String>> {
    response
        .outcomes
        .iter()
        .map(|outcome| {
            outcome
                .keys
                .iter()
                .map(|outcome: &MutationKeyOutcome| outcome.key.as_str().to_owned())
                .collect()
        })
        .collect()
}

fn response_revisions(response: &MutationBatchResponse) -> Vec<Vec<Option<u64>>> {
    response
        .outcomes
        .iter()
        .map(|outcome| outcome.keys.iter().map(|key| key.revision).collect())
        .collect()
}

fn rejection(error: IndexError) -> MutationRejection {
    match error {
        IndexError::MutationRejected { rejection } => rejection,
        other => panic!("expected a typed mutation rejection, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Independent reference model
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq)]
struct OracleDoc {
    revision: u64,
    live: bool,
    fields: BTreeMap<String, FieldValues>,
}

impl OracleDoc {
    fn field(&self, name: &str) -> FieldValues {
        self.fields
            .get(name)
            .cloned()
            .unwrap_or(FieldValues::Absent)
    }
}

/// A deliberately small, independent mutation state machine.
///
/// It knows only ordered key transitions and the five field states. It does not
/// use the writer planner, the query selector or the durable response codec.
#[derive(Default)]
struct Oracle {
    docs: BTreeMap<String, OracleDoc>,
}

impl Oracle {
    fn seeded(docs: &[Document]) -> Self {
        let mut oracle = Self::default();
        for document in docs {
            oracle.docs.insert(
                document.key().as_str().to_owned(),
                OracleDoc {
                    revision: 1,
                    live: true,
                    fields: document
                        .fields()
                        .map(|(k, v)| (k.to_owned(), v.clone()))
                        .collect(),
                },
            );
        }
        oracle
    }

    fn revision(&self, id: &str) -> u64 {
        self.docs.get(id).map_or(0, |doc| doc.revision)
    }

    fn live_keys(&self) -> Vec<String> {
        self.docs
            .iter()
            .filter(|(_, doc)| doc.live)
            .map(|(id, _)| id.clone())
            .collect()
    }

    fn next_revision(&self, id: &str) -> u64 {
        self.revision(id).checked_add(1).expect("oracle revision")
    }

    fn apply_insert(&mut self, document: &Document) -> u64 {
        let id = document.key().as_str().to_owned();
        let revision = self.next_revision(&id);
        let fields = document
            .fields()
            .map(|(k, v)| (k.to_owned(), v.clone()))
            .collect();
        self.docs.insert(
            id,
            OracleDoc {
                revision,
                live: true,
                fields,
            },
        );
        revision
    }

    fn apply_upsert(&mut self, document: &Document) -> u64 {
        self.apply_insert(document)
    }

    fn apply_delete(&mut self, id: &str) -> u64 {
        let revision = self.next_revision(id);
        let entry = self.docs.entry(id.to_owned()).or_insert_with(|| OracleDoc {
            revision,
            live: false,
            fields: BTreeMap::new(),
        });
        entry.revision = revision;
        entry.live = false;
        revision
    }

    fn apply_replace(&mut self, id: &str, template: &Document) -> u64 {
        let revision = self.next_revision(id);
        let entry = self.docs.get_mut(id).expect("replace target");
        entry.revision = revision;
        entry.live = true;
        entry.fields = template
            .fields()
            .map(|(k, v)| (k.to_owned(), v.clone()))
            .collect();
        revision
    }

    fn apply_patch(&mut self, id: &str, patch: &DocumentPatch) -> u64 {
        let revision = self.next_revision(id);
        let entry = self.docs.get_mut(id).expect("patch target");
        entry.revision = revision;
        entry.live = true;
        for operation in &patch.operations {
            match operation {
                PatchOperation::Set { field, values } => {
                    if values.is_absent() {
                        entry.fields.remove(field);
                    } else {
                        entry.fields.insert(field.clone(), values.clone());
                    }
                }
                PatchOperation::Unset { field } => {
                    entry.fields.remove(field);
                }
            }
        }
        revision
    }

    fn assert_matches(&self, snapshot: &ReaderSnapshot) {
        assert_eq!(live_keys(snapshot), self.live_keys(), "live key set");
        let observed = projected(snapshot, ALL_FIELDS);
        for (id, doc) in &self.docs {
            if !doc.live {
                assert!(
                    !observed.contains_key(id),
                    "tombstone {id} must not be visible"
                );
                continue;
            }
            let fields = observed
                .get(id)
                .unwrap_or_else(|| panic!("missing live {id}"));
            for name in ALL_FIELDS {
                assert_eq!(
                    fields.get(*name).cloned().unwrap_or(FieldValues::Absent),
                    doc.field(name),
                    "field {name} of {id}"
                );
            }
        }
    }
}

/// One committed generation observed through existing snapshot APIs.
#[derive(Clone, Debug, PartialEq)]
struct GenerationView {
    generation: Option<u64>,
    keys: Vec<String>,
    fields: Projected,
}

/// Assert one committed generation against the independent oracle, then capture
/// an owned copy for cross-topology comparison. Snapshot objects expose
/// generation, keys and projected field states; per-key revisions are asserted
/// separately from mutation responses.
fn checkpoint(
    oracle: &Oracle,
    snapshot: &ReaderSnapshot,
    expected_generation: Option<u64>,
    label: &str,
) -> GenerationView {
    assert_eq!(
        snapshot.generation(),
        expected_generation,
        "{label}: committed generation"
    );
    oracle.assert_matches(snapshot);
    let keys = live_keys(snapshot);
    let fields = projected(snapshot, ALL_FIELDS);
    assert_eq!(keys, oracle.live_keys(), "{label}: live keys");
    GenerationView {
        generation: snapshot.generation(),
        keys,
        fields,
    }
}

fn title_field(fields: &Projected, key: &str) -> Option<FieldValues> {
    fields
        .get(key)
        .and_then(|values| values.get("title"))
        .cloned()
}

fn assert_pinned_view(
    pinned: &ReaderSnapshot,
    pinned_keys: &[String],
    pinned_fields: &Projected,
    boundary: &str,
) {
    assert_eq!(live_keys(pinned), pinned_keys, "{boundary}: pinned keys");
    assert_eq!(
        projected(pinned, ALL_FIELDS),
        *pinned_fields,
        "{boundary}: pinned full field projection"
    );
}

fn assert_fresh_updated(fresh: &ReaderSnapshot, boundary: &str) {
    let fields = projected(fresh, ALL_FIELDS);
    assert_eq!(
        title_field(&fields, "a"),
        Some(FieldValues::Single(FieldValue::Text("changed".to_owned()))),
        "{boundary}: fresh reader must see a.title=changed"
    );
    assert!(
        !fields.contains_key("b"),
        "{boundary}: fresh reader must not see deleted b"
    );
}

// ---------------------------------------------------------------------------
// Deterministic directory fault injection
// ---------------------------------------------------------------------------

struct FaultState {
    fail_manifest_create: AtomicBool,
    fail_current_before: AtomicBool,
    fail_current_after: AtomicBool,
    current_reached: Option<Arc<Barrier>>,
    current_release: Option<Arc<Barrier>>,
}

impl Default for FaultState {
    fn default() -> Self {
        Self {
            fail_manifest_create: AtomicBool::new(false),
            fail_current_before: AtomicBool::new(false),
            fail_current_after: AtomicBool::new(false),
            current_reached: None,
            current_release: None,
        }
    }
}

#[derive(Clone)]
struct FaultDirectory {
    inner: Arc<dyn Directory>,
    state: Arc<FaultState>,
}

impl FaultDirectory {
    fn new(inner: Arc<dyn Directory>) -> Self {
        Self {
            inner,
            state: Arc::new(FaultState::default()),
        }
    }

    fn inject(operation: StorageOp) -> StorageError {
        StorageError::io(operation, std::io::Error::other("m5 injected fault"))
    }
}

impl Directory for FaultDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }

    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
        if self.state.fail_manifest_create.load(Ordering::SeqCst)
            && key.as_str().starts_with("index/manifests/")
        {
            return Err(Self::inject(StorageOp::Create));
        }
        self.inner.create(key)
    }

    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
        self.inner.open_read(key)
    }

    fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
        self.inner.exists(key)
    }

    fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if key.as_str() == CURRENT_KEY {
            if let (Some(reached), Some(release)) =
                (&self.state.current_reached, &self.state.current_release)
            {
                reached.wait();
                release.wait();
            }
            if self.state.fail_current_before.load(Ordering::SeqCst) {
                return Err(Self::inject(StorageOp::AtomicWrite));
            }
            if self.state.fail_current_after.load(Ordering::SeqCst) {
                self.inner.atomic_write(key, data)?;
                return Err(Self::inject(StorageOp::Sync));
            }
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}

// ---------------------------------------------------------------------------
// Cancellation probes
// ---------------------------------------------------------------------------

struct TripAfter {
    skip: usize,
    polls: Arc<AtomicUsize>,
}

impl Cancellation for TripAfter {
    fn is_cancelled(&self) -> bool {
        self.polls.fetch_add(1, Ordering::SeqCst) >= self.skip
    }
}

struct CountPolls(Arc<AtomicUsize>);

impl Cancellation for CountPolls {
    fn is_cancelled(&self) -> bool {
        self.0.fetch_add(1, Ordering::SeqCst);
        false
    }
}

// ===========================================================================
// T01–T06 — admission atomicity, revisions and preconditions
// ===========================================================================

#[test]
fn m5_t01_mixed_batch_is_atomic_and_visible_after_refresh_memory_and_fs() {
    // Expected by hand: a@1,b@1 -> insert c@1, update a@2, delete b@2.
    run_mixed_batch(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t01");
    run_mixed_batch(fs_directory(temp.path()));
}

fn run_mixed_batch(directory: Arc<dyn Directory>) {
    let docs = vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)];
    let (directory, mut writer) = setup_with(directory, docs.clone(), IndexLimits::new());
    let mut oracle = Oracle::seeded(&docs);
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("c")),
            MutationAction::Insert(base_doc("c", "gamma", 3)),
        ),
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(patch("title", FieldValue::Text("alpha patched".to_owned()))),
        ),
        MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
    ]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("mixed batch");
    assert!(!response.replayed);
    assert_eq!(
        response_keys(&response),
        [
            vec!["c".to_owned()],
            vec!["a".to_owned()],
            vec!["b".to_owned()]
        ]
    );
    assert_eq!(
        response_revisions(&response),
        [vec![Some(1)], vec![Some(2)], vec![Some(2)]]
    );

    oracle.apply_insert(&base_doc("c", "gamma", 3));
    // Apply only the patched field to the oracle's complete original document.
    oracle.docs.get_mut("a").unwrap().fields.insert(
        "title".to_owned(),
        FieldValues::Single(FieldValue::Text("alpha patched".to_owned())),
    );
    oracle.docs.get_mut("a").unwrap().revision = 2;
    oracle.apply_delete("b");

    writer.refresh().expect("refresh");
    oracle.assert_matches(&writer.reader());
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t02_late_invalid_patch_rejects_whole_batch_without_token_consumption_memory_and_fs() {
    run_late_invalid_patch(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t02");
    run_late_invalid_patch(fs_directory(temp.path()));
}

fn run_late_invalid_patch(directory: Arc<dyn Directory>) {
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)],
        IndexLimits::new(),
    );
    let mut bad_patch = patch("title", FieldValue::Text("ignored".to_owned()));
    if let PatchOperation::Set { values, .. } = &mut bad_patch.operations[0] {
        *values = FieldValues::Absent;
    }
    let invalid = token(
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(patch("title", FieldValue::Text("valid first".to_owned()))),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Update(bad_patch),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("c")),
                MutationAction::Insert(base_doc("c", "gamma", 3)),
            ),
        ]),
        "m5-t02-token",
    );
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&invalid, &CancellationFlag::new())
        .expect_err("late invalid patch must reject");
    assert!(matches!(
        error,
        IndexError::MutationRejected {
            rejection: MutationRejection::InvalidBatch { .. }
        }
    ));
    assert_unchanged(&mut writer, &before);

    // The rejected batch consumed no token. A different, valid payload under
    // the same token is admitted rather than reported as a conflict.
    let valid = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("c")),
            MutationAction::Insert(base_doc("c", "gamma", 3)),
        )]),
        "m5-t02-token",
    );
    let response = writer
        .apply_batch(&valid, &CancellationFlag::new())
        .expect("token was not consumed");
    assert!(!response.replayed);
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t03_late_conflict_after_query_mutation_rejects_entire_batch_memory_and_fs() {
    run_late_conflict(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t03");
    run_late_conflict(fs_directory(temp.path()));
}

fn run_late_conflict(directory: Arc<dyn Directory>) {
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "target", 1), base_doc("b", "other", 2)],
        IndexLimits::new(),
    );
    let batch = token(
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Query(selector(title_term("target"), 10)),
                MutationAction::Update(patch("title", FieldValue::Text("first".to_owned()))),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(base_doc("a", "duplicate", 9)),
            ),
        ]),
        "m5-t03-token",
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&batch, &CancellationFlag::new()),
        Err(IndexError::DuplicateDocument { .. })
    ));
    assert_unchanged(&mut writer, &before);

    let valid = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("c")),
            MutationAction::Insert(base_doc("c", "new", 3)),
        )]),
        "m5-t03-token",
    );
    assert!(
        !writer
            .apply_batch(&valid, &CancellationFlag::new())
            .expect("token not consumed")
            .replayed
    );
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t04_ordered_explicit_commands_allocate_exact_revisions() {
    let (_directory, mut writer) = setup(vec![base_doc("a", "alpha", 1)]);
    let mut oracle = Oracle::seeded(&[base_doc("a", "alpha", 1)]);
    let replaced = base_doc("a", "replaced", 2);
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("c")),
            MutationAction::Insert(base_doc("c", "gamma", 3)),
        ),
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(patch("title", FieldValue::Text("patched".to_owned()))),
        )
        .with_precondition(MutationPrecondition::ExpectedRevision(1)),
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Upsert(replaced.clone()),
        ),
        MutationCommand::new(MutationTarget::Key(key("a")), MutationAction::Delete)
            .with_precondition(MutationPrecondition::ExpectedRevision(3)),
    ]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("ordered batch");
    assert_eq!(
        response_revisions(&response),
        [vec![Some(1)], vec![Some(2)], vec![Some(3)], vec![Some(4)]]
    );
    oracle.apply_insert(&base_doc("c", "gamma", 3));
    oracle.apply_patch("a", &patch("title", FieldValue::Text("patched".to_owned())));
    oracle.apply_upsert(&replaced);
    oracle.apply_delete("a");
    writer.refresh().unwrap();
    oracle.assert_matches(&writer.reader());
}

#[test]
fn m5_t05_stale_expected_revision_fails_without_mutation_memory_and_fs() {
    run_stale_revision(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t05");
    run_stale_revision(fs_directory(temp.path()));
}

fn run_stale_revision(directory: Arc<dyn Directory>) {
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "alpha", 1)],
        IndexLimits::new(),
    );
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(patch("title", FieldValue::Text("stale".to_owned()))),
        )
        .with_precondition(MutationPrecondition::ExpectedRevision(99)),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect_err("stale revision");
    assert_eq!(
        rejection(error),
        MutationRejection::PreconditionFailed {
            key: key("a"),
            expected: MutationPrecondition::ExpectedRevision(99),
        }
    );
    assert_unchanged(&mut writer, &before);
    drop(writer);
    drop(directory);
}

// ===========================================================================
// T07–T11 — committed-snapshot query selection and bounds
// ===========================================================================

#[test]
fn m5_t07_query_selection_is_fixed_to_the_batch_initial_committed_snapshot() {
    run_fixed_selection(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t07");
    run_fixed_selection(fs_directory(temp.path()));
}

fn run_fixed_selection(directory: Arc<dyn Directory>) {
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)],
        IndexLimits::new(),
    );
    let mut oracle = Oracle::seeded(&[base_doc("a", "alpha", 1), base_doc("b", "beta", 2)]);
    // Command 0 makes `a` match the second query. The second selector must
    // still see only committed `b`, never the batch's new state.
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("alpha"), 10)),
            MutationAction::Update(patch("title", FieldValue::Text("beta".to_owned()))),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("beta"), 10)),
            MutationAction::Delete,
        ),
    ]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("fixed selection batch");
    assert_eq!(
        response_keys(&response),
        [vec!["a".to_owned()], vec!["b".to_owned()]]
    );
    oracle.apply_patch("a", &patch("title", FieldValue::Text("beta".to_owned())));
    oracle.apply_delete("b");
    writer.refresh().unwrap();
    oracle.assert_matches(&writer.reader());
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t08_earlier_staged_insert_is_not_selected_by_a_query() {
    let (_directory, mut writer) = setup(vec![base_doc("a", "target", 1)]);
    let batch = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("b")),
            MutationAction::Insert(base_doc("b", "target", 2)),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Delete,
        ),
    ]);
    let response = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("staged insert");
    assert_eq!(
        response_keys(&response),
        [vec!["b".to_owned()], vec!["a".to_owned()]]
    );
    writer.refresh().unwrap();
    assert_eq!(live_keys(&writer.reader()), ["b".to_owned()]);
}

#[test]
fn m5_t09_selected_key_with_a_newer_pending_revision_fails_closed() {
    let (_directory, mut writer) = setup(vec![base_doc("a", "target", 1)]);
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(patch("title", FieldValue::Text("pending".to_owned()))),
            )]),
            &CancellationFlag::new(),
        )
        .expect("pending update");
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("target"), 10)),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new(),
        )
        .expect_err("newer pending revision must fail closed");
    assert_eq!(
        rejection(error),
        MutationRejection::PreconditionFailed {
            key: key("a"),
            expected: MutationPrecondition::ExpectedRevision(1),
        }
    );
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m5_t10_exactly_at_the_query_match_limit_mutates_every_match() {
    let (_directory, mut writer) = setup(vec![
        base_doc("a", "target", 1),
        base_doc("b", "target", 2),
        base_doc("c", "other", 3),
    ]);
    let response = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("target"), 2)),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new(),
        )
        .expect("exact query limit");
    assert_eq!(response.outcomes[0].matched, 2);
    assert_eq!(
        response_keys(&response),
        [vec!["a".to_owned(), "b".to_owned()]]
    );
    writer.refresh().unwrap();
    assert_eq!(live_keys(&writer.reader()), ["c".to_owned()]);
}

#[test]
fn m5_t11_one_over_the_query_match_limit_is_a_typed_failure_without_truncation() {
    let (_directory, mut writer) = setup(vec![
        base_doc("a", "target", 1),
        base_doc("b", "target", 2),
        base_doc("c", "target", 3),
    ]);
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("target"), 2)),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new(),
        )
        .expect_err("one-over query limit");
    assert_eq!(
        rejection(error),
        MutationRejection::MatchLimitExceeded {
            limit: 2,
            matched: 3,
        }
    );
    assert_unchanged(&mut writer, &before);
}

// ===========================================================================
// T12–T17 — patch/replace/upsert state fidelity
// ===========================================================================

fn five_state_doc() -> Document {
    let mut document = Document::new(key("five"));
    set(
        &mut document,
        "title",
        FieldValue::Text("five states".to_owned()),
    );
    // body is absent
    set(&mut document, "n", FieldValue::I64(7));
    set_multi(
        &mut document,
        "tag",
        vec![
            FieldValue::Keyword("red".to_owned()),
            FieldValue::Keyword("blue".to_owned()),
        ],
    );
    set_null(&mut document, "score");
    set(
        &mut document,
        "when",
        FieldValue::Timestamp(Timestamp::from_micros(42)),
    );
    set(
        &mut document,
        "meta",
        FieldValue::Json(JsonValue::Object(vec![
            (
                "nested".to_owned(),
                JsonValue::Array(vec![JsonValue::Number(JsonNumber::I64(1))]),
            ),
            ("flag".to_owned(), JsonValue::Bool(true)),
        ])),
    );
    set(
        &mut document,
        "point",
        FieldValue::GeoPoint(GeoPoint::new(-1.25, 2.5).expect("geo")),
    );
    // nullable is absent
    set_empty(&mut document, "empty_multi");
    document
}

#[test]
fn m5_t12_patch_preserves_all_five_states_and_typed_json_geo_memory_and_fs() {
    run_patch_fidelity(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t12");
    run_patch_fidelity(fs_directory(temp.path()));
}

fn run_patch_fidelity(directory: Arc<dyn Directory>) {
    let original = five_state_doc();
    let (directory, mut writer) = setup_with(directory, vec![original.clone()], IndexLimits::new());
    let mut oracle = Oracle::seeded(&[original]);
    let update = patch("title", FieldValue::Text("patched title".to_owned()));
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("five")),
                MutationAction::Update(update.clone()),
            )]),
            &CancellationFlag::new(),
        )
        .expect("five-state patch");
    oracle.apply_patch("five", &update);
    writer.refresh().unwrap();
    oracle.assert_matches(&writer.reader());

    let observed = projected(&writer.reader(), ALL_FIELDS);
    let fields = observed.get("five").expect("five live");
    assert_eq!(fields.get("body"), Some(&FieldValues::Absent));
    assert_eq!(fields.get("nullable"), Some(&FieldValues::Absent));
    assert_eq!(fields.get("empty_multi"), Some(&FieldValues::Empty));
    assert_eq!(fields.get("score"), Some(&FieldValues::ExplicitNull));
    assert_eq!(
        fields.get("tag"),
        Some(&FieldValues::Multi(vec![
            FieldValue::Keyword("red".to_owned()),
            FieldValue::Keyword("blue".to_owned())
        ]))
    );
    assert!(matches!(
        fields.get("when"),
        Some(FieldValues::Single(FieldValue::Timestamp(_)))
    ));
    assert!(matches!(
        fields.get("meta"),
        Some(FieldValues::Single(FieldValue::Json(_)))
    ));
    assert!(matches!(
        fields.get("point"),
        Some(FieldValues::Single(FieldValue::GeoPoint(_)))
    ));
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t13_indexed_only_source_is_rejected_on_real_filesystem() {
    let temp = TempDir::new("t13");
    let directory = fs_directory(temp.path());
    let index =
        Index::create(Arc::clone(&directory), indexed_only_schema(), registry()).expect("create");
    let mut writer = index.writer().expect("writer");
    let mut document = Document::new(key("a"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("target".to_owned())),
        )
        .unwrap();
    document
        .insert(
            "raw",
            FieldValues::Single(FieldValue::Text("unrecoverable".to_owned())),
        )
        .unwrap();
    writer.insert(document).unwrap();
    writer.commit().unwrap();

    let before = (
        writer.generation(),
        writer.pending_mutations(),
        writer.pending_documents(),
    );
    let error = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(DocumentPatch {
                    operations: vec![PatchOperation::Unset {
                        field: "title".to_owned(),
                    }],
                }),
            )]),
            &CancellationFlag::new(),
        )
        .expect_err("indexed-only source must fail closed");
    assert!(matches!(
        rejection(error),
        MutationRejection::ReconstructionUnavailable { .. }
    ));
    assert_eq!(
        (
            writer.generation(),
            writer.pending_mutations(),
            writer.pending_documents(),
        ),
        before
    );
}

#[test]
fn m5_t14_query_replace_retains_keys_and_drops_omitted_fields() {
    let (_directory, mut writer) = setup(vec![base_doc("a", "target", 1)]);
    let mut oracle = Oracle::seeded(&[base_doc("a", "target", 1)]);
    let mut template = Document::new(key("template"));
    set(
        &mut template,
        "title",
        FieldValue::Text("replacement".to_owned()),
    );
    let response = writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("target"), 10)),
                MutationAction::Replace(template.clone()),
            )]),
            &CancellationFlag::new(),
        )
        .expect("query replace");
    assert_eq!(response_keys(&response), [vec!["a".to_owned()]]);
    oracle.apply_replace("a", &template);
    writer.refresh().unwrap();
    oracle.assert_matches(&writer.reader());
    let observed = projected(&writer.reader(), ALL_FIELDS);
    let fields = observed.get("a").expect("a live");
    assert_eq!(fields.get("n"), Some(&FieldValues::Absent));
    assert_eq!(fields.get("tag"), Some(&FieldValues::Absent));
    assert_eq!(fields.get("point"), Some(&FieldValues::Absent));
}

#[test]
fn m5_t15_query_upsert_zero_one_and_two_matches_memory_and_fs() {
    run_query_upsert(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t15");
    run_query_upsert(fs_directory(temp.path()));
}

fn query_upsert_batch(query: Query, replacement: Document, fallback: Document) -> MutationBatch {
    MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector(query, 10)),
        MutationAction::QueryUpsert {
            replacement,
            fallback,
        },
    )])
}

fn replacement_template() -> Document {
    let mut replacement = Document::new(key("replacement"));
    set(
        &mut replacement,
        "title",
        FieldValue::Text("upserted".to_owned()),
    );
    replacement
}

fn gamma_replacement_template() -> Document {
    let mut template = Document::new(key("template"));
    set(
        &mut template,
        "title",
        FieldValue::Text("gamma replaced".to_owned()),
    );
    template
}

fn run_query_upsert(directory: Arc<dyn Directory>) {
    // 0 matches: fallback inserted unaltered at its own key.
    let (directory, mut writer) = setup_with(
        Arc::clone(&directory),
        vec![base_doc("a", "other", 1)],
        IndexLimits::new(),
    );
    let fallback = base_doc("fallback", "fallback title", 8);
    let response = writer
        .apply_batch(
            &query_upsert_batch(
                title_term("missing"),
                replacement_template(),
                fallback.clone(),
            ),
            &CancellationFlag::new(),
        )
        .expect("zero-match upsert");
    assert_eq!(response.outcomes[0].matched, 0);
    assert_eq!(response_keys(&response), [vec!["fallback".to_owned()]]);
    assert_eq!(response.outcomes[0].keys[0].intent, MutationIntent::Insert);
    assert_eq!(response.outcomes[0].keys[0].revision, Some(1));
    writer.refresh().unwrap();
    let observed = projected(&writer.reader(), ALL_FIELDS);
    assert_eq!(
        observed
            .get("fallback")
            .and_then(|fields| fields.get("title")),
        Some(&FieldValues::Single(FieldValue::Text(
            "fallback title".to_owned()
        )))
    );

    // 1 match: selected key is replaced; fallback is not inserted.
    let response = writer
        .apply_batch(
            &query_upsert_batch(
                title_term("other"),
                replacement_template(),
                base_doc("never", "never", 9),
            ),
            &CancellationFlag::new(),
        )
        .expect("one-match upsert");
    assert_eq!(response.outcomes[0].matched, 1);
    assert_eq!(response_keys(&response), [vec!["a".to_owned()]]);
    assert_eq!(response.outcomes[0].keys[0].intent, MutationIntent::Upsert);
    writer.refresh().unwrap();
    assert!(!live_keys(&writer.reader()).contains(&"never".to_owned()));

    // 2 matches: ambiguous, no change.
    writer.insert(base_doc("b", "ambiguous one", 2)).unwrap();
    writer.insert(base_doc("c", "ambiguous two", 3)).unwrap();
    writer.commit().unwrap();
    let before = writer_state(&writer);
    let error = writer
        .apply_batch(
            &query_upsert_batch(
                title_term("ambiguous"),
                replacement_template(),
                base_doc("fallback2", "fallback2", 10),
            ),
            &CancellationFlag::new(),
        )
        .expect_err("two-match upsert");
    assert_eq!(
        rejection(error),
        MutationRejection::AmbiguousQueryUpsert { matched: 2 }
    );
    assert_unchanged(&mut writer, &before);
    drop(writer);
    drop(directory);
}

#[test]
fn m5_t16_live_pending_fallback_collisions_and_staged_overlap_reject() {
    let (_directory, mut writer) =
        setup(vec![base_doc("live", "live", 1), base_doc("a", "other", 2)]);
    let live_fallback = query_upsert_batch(
        title_term("missing"),
        replacement_template(),
        base_doc("live", "collision", 3),
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&live_fallback, &CancellationFlag::new()),
        Err(IndexError::DuplicateDocument { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Pending, not yet committed fallback collision.
    writer.insert(base_doc("pending", "pending", 4)).unwrap();
    let pending_fallback = query_upsert_batch(
        title_term("missing-pending"),
        replacement_template(),
        base_doc("pending", "collision", 5),
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&pending_fallback, &CancellationFlag::new()),
        Err(IndexError::DuplicateDocument { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Earlier command in the same batch already touches the fallback key.
    let overlap = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("staged")),
            MutationAction::Insert(base_doc("staged", "staged", 6)),
        ),
        MutationCommand::new(
            MutationTarget::Query(selector(title_term("missing-overlap"), 10)),
            MutationAction::QueryUpsert {
                replacement: replacement_template(),
                fallback: base_doc("staged", "fallback", 7),
            },
        ),
    ]);
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&overlap, &CancellationFlag::new()),
        Err(IndexError::MutationRejected { .. })
    ));
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m5_t17_zero_match_fallback_is_durable_and_replays_after_reopen_memory_and_fs() {
    run_zero_match_replay(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t17");
    run_zero_match_replay(fs_directory(temp.path()));
}

fn run_zero_match_replay(directory: Arc<dyn Directory>) {
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "other", 1)],
        IndexLimits::new(),
    );
    let batch = token(
        query_upsert_batch(
            title_term("missing"),
            replacement_template(),
            base_doc("fallback", "fallback durable", 11),
        ),
        "m5-t17-token",
    );
    let first = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("zero-match upsert");
    writer.commit().expect("commit");
    drop(writer);

    let mut writer = reopen(Arc::clone(&directory), IndexLimits::new());
    let fallback = projected(&writer.reader(), ALL_FIELDS)
        .remove("fallback")
        .expect("fallback is durable");
    assert_eq!(
        fallback.get("title"),
        Some(&FieldValues::Single(FieldValue::Text(
            "fallback durable".to_owned()
        )))
    );
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("durable replay");
    assert!(replay.replayed);
    assert_eq!(replay.outcomes[0].matched, 0);
    assert_eq!(response_keys(&replay), [vec!["fallback".to_owned()]]);
    assert_eq!(replay.outcomes[0].keys[0].intent, MutationIntent::Insert);
    assert_eq!(
        replay.outcomes[0].keys[0].revision,
        first.outcomes[0].keys[0].revision
    );
    drop(writer);
    drop(directory);
}

// ===========================================================================
// T19–T23 — replay, compaction, cold reopen, publication failure
// ===========================================================================

#[test]
fn m5_t19_replay_after_reopen_never_reselects_changed_query_matches_fs() {
    let temp = TempDir::new("t19");
    let directory = fs_directory(temp.path());
    let (directory, mut writer) = setup_with(
        Arc::clone(&directory),
        vec![base_doc("a", "target", 1), base_doc("b", "target", 2)],
        IndexLimits::new(),
    );
    let batch = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Delete,
        )]),
        "m5-t19-token",
    );
    let first = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("query delete");
    writer.commit().unwrap();
    drop(writer);

    let mut writer = reopen(Arc::clone(&directory), IndexLimits::new());
    writer.insert(base_doc("c", "target", 3)).unwrap();
    writer.commit().unwrap();
    drop(writer);

    let mut writer = reopen(Arc::clone(&directory), IndexLimits::new());
    let before = writer_state(&writer);
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("replay");
    assert!(replay.replayed);
    assert_eq!(response_keys(&replay), response_keys(&first));
    assert_eq!(
        response_keys(&replay),
        [vec!["a".to_owned(), "b".to_owned()]]
    );
    writer.refresh().unwrap();
    assert_eq!(live_keys(&writer.reader()), ["c".to_owned()]);
    assert_eq!(writer.pending_mutations(), before.1);
    drop(directory);
}

#[test]
fn m5_t20_changed_token_payloads_conflict_without_admission_fs() {
    let temp = TempDir::new("t20");
    let directory = fs_directory(temp.path());
    let (directory, mut writer) = setup_with(
        directory,
        vec![base_doc("a", "target", 1), base_doc("b", "other", 2)],
        IndexLimits::new(),
    );
    let original = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(selector(title_term("target"), 10)),
            MutationAction::Delete,
        )]),
        "m5-t20-token",
    );
    writer
        .apply_batch(&original, &CancellationFlag::new())
        .expect("original");
    writer.commit().unwrap();
    drop(writer);

    let mut writer = reopen(Arc::clone(&directory), IndexLimits::new());
    let variants = [
        token(
            MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("other"), 10)),
                MutationAction::Delete,
            )]),
            "m5-t20-token",
        ),
        token(
            MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("other"), 10)),
                MutationAction::Update(patch("title", FieldValue::Text("changed".to_owned()))),
            )]),
            "m5-t20-token",
        ),
        token(
            MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(selector(title_term("other"), 10)),
                MutationAction::Replace(replacement_template()),
            )]),
            "m5-t20-token",
        ),
        token(
            query_upsert_batch(
                title_term("other"),
                replacement_template(),
                base_doc("fallback", "changed fallback", 4),
            ),
            "m5-t20-token",
        ),
    ];
    for variant in variants {
        let before = writer_state(&writer);
        assert!(matches!(
            writer.apply_batch(&variant, &CancellationFlag::new()),
            Err(IndexError::IdempotencyConflict { .. })
        ));
        assert_unchanged(&mut writer, &before);
    }
    let replay = writer
        .apply_batch(&original, &CancellationFlag::new())
        .expect("same payload replays");
    assert!(replay.replayed);
    drop(directory);
}

#[test]
fn m5_t21_replay_survives_compaction_and_respects_replay_bounds_fs() {
    let temp = TempDir::new("t21");
    let directory = fs_directory(temp.path());
    let (directory, mut writer) = setup_with(
        Arc::clone(&directory),
        vec![base_doc("a", "alpha", 1)],
        IndexLimits::new(),
    );
    let batch = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("b")),
            MutationAction::Insert(base_doc("b", "beta", 2)),
        )]),
        "m5-t21-token",
    );
    let first = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("batch");
    writer.commit().unwrap();
    writer.compact().expect("compaction");
    let replay = writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("replay after compaction");
    assert!(replay.replayed);
    assert_eq!(response_keys(&replay), response_keys(&first));
    drop(writer);

    // Replay-key budget: exact one key succeeds, two keys are rejected.
    let limits = IndexLimits::new().with_max_batch_replay_keys(1);
    let mut writer = reopen(Arc::clone(&directory), limits);
    let two_keys = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(vec![key("c"), key("d")]),
            MutationAction::Delete,
        )]),
        "m5-t21-two-keys",
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&two_keys, &CancellationFlag::new()),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);
    drop(directory);
}

#[test]
fn m5_t22_successful_mixed_batch_cold_reopens_completely_fs() {
    let temp = TempDir::new("t22");
    let directory = fs_directory(temp.path());
    let docs = vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)];
    let (directory, mut writer) =
        setup_with(Arc::clone(&directory), docs.clone(), IndexLimits::new());
    let mut oracle = Oracle::seeded(&docs);
    let batch = token(
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("c")),
                MutationAction::Insert(base_doc("c", "gamma", 3)),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(patch("title", FieldValue::Text("alpha2".to_owned()))),
            ),
            MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
        ]),
        "m5-t22-token",
    );
    writer
        .apply_batch(&batch, &CancellationFlag::new())
        .expect("mixed batch");
    writer.commit().unwrap();
    drop(writer);
    oracle.apply_insert(&base_doc("c", "gamma", 3));
    oracle.apply_patch("a", &patch("title", FieldValue::Text("alpha2".to_owned())));
    oracle.apply_delete("b");

    let writer = reopen(directory, IndexLimits::new());
    assert_eq!(writer.generation(), Some(2));
    oracle.assert_matches(&writer.reader());
}

#[test]
fn m5_t23_pre_current_failure_preserves_the_old_generation_fs() {
    for fail_manifest in [true, false] {
        let temp = TempDir::new("t23");
        let fs = fs_directory(temp.path());
        let fault = FaultDirectory::new(fs);
        let directory: Arc<dyn Directory> = Arc::new(fault.clone());
        let (_, mut writer) = setup_with(
            Arc::clone(&directory),
            vec![base_doc("a", "alpha", 1)],
            IndexLimits::new(),
        );
        if fail_manifest {
            fault
                .state
                .fail_manifest_create
                .store(true, Ordering::SeqCst);
        } else {
            fault
                .state
                .fail_current_before
                .store(true, Ordering::SeqCst);
        }
        writer
            .apply_batch(
                &MutationBatch::new(vec![MutationCommand::new(
                    MutationTarget::Key(key("b")),
                    MutationAction::Insert(base_doc("b", "beta", 2)),
                )]),
                &CancellationFlag::new(),
            )
            .expect("admit");
        assert!(writer.commit().is_err(), "publication must fail");
        drop(writer);

        let reopened = reopen(fs_directory(temp.path()), IndexLimits::new());
        assert_eq!(reopened.generation(), Some(1));
        assert_eq!(live_keys(&reopened.reader()), ["a".to_owned()]);
    }
}

#[test]
fn m5_t26_ambiguous_current_poisoning_and_reopen_follow_the_protocol_fs() {
    let temp = TempDir::new("t26");
    let fs = fs_directory(temp.path());
    let fault = FaultDirectory::new(fs);
    let directory: Arc<dyn Directory> = Arc::new(fault.clone());
    let (_, mut writer) = setup_with(
        Arc::clone(&directory),
        vec![base_doc("a", "alpha", 1)],
        IndexLimits::new(),
    );
    fault.state.fail_current_after.store(true, Ordering::SeqCst);
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Insert(base_doc("b", "beta", 2)),
            )]),
            &CancellationFlag::new(),
        )
        .expect("admit");
    assert!(matches!(
        writer.commit(),
        Err(IndexError::RecoveryRequired { .. })
    ));
    assert!(matches!(
        writer.insert(base_doc("c", "gamma", 3)),
        Err(IndexError::RecoveryRequired { .. })
    ));
    drop(writer);

    let reopened = reopen(fs_directory(temp.path()), IndexLimits::new());
    assert_eq!(reopened.generation(), Some(2));
    assert_eq!(
        live_keys(&reopened.reader()),
        ["a".to_owned(), "b".to_owned()]
    );
}

// ===========================================================================
// T27–T28 — historical isolation and barrier-controlled concurrent readers
// ===========================================================================

#[test]
fn m5_t27_pinned_reader_and_pit_remain_immutable_across_refresh_commit_and_merge() {
    run_pit_isolation(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t27");
    run_pit_isolation(fs_directory(temp.path()));
}

fn run_pit_isolation(directory: Arc<dyn Directory>) {
    let docs = vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)];
    let (directory, mut writer) = setup_with(directory, docs.clone(), IndexLimits::new());
    let pinned = writer.pin().expect("pit");
    let pinned_keys = live_keys(pinned.snapshot());
    let pinned_fields = projected(pinned.snapshot(), ALL_FIELDS);
    assert_eq!(pinned_keys, ["a".to_owned(), "b".to_owned()]);
    assert_eq!(
        title_field(&pinned_fields, "a"),
        Some(FieldValues::Single(FieldValue::Text("alpha".to_owned())))
    );
    assert_eq!(
        title_field(&pinned_fields, "b"),
        Some(FieldValues::Single(FieldValue::Text("beta".to_owned())))
    );
    assert_pinned_view(pinned.snapshot(), &pinned_keys, &pinned_fields, "initial");

    writer
        .apply_batch(
            &MutationBatch::new(vec![
                MutationCommand::new(
                    MutationTarget::Key(key("a")),
                    MutationAction::Update(patch("title", FieldValue::Text("changed".to_owned()))),
                ),
                MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
            ]),
            &CancellationFlag::new(),
        )
        .expect("mutate");
    assert_pinned_view(
        pinned.snapshot(),
        &pinned_keys,
        &pinned_fields,
        "after apply (before refresh)",
    );

    writer.refresh().unwrap();
    assert_pinned_view(
        pinned.snapshot(),
        &pinned_keys,
        &pinned_fields,
        "after refresh",
    );
    assert_fresh_updated(&writer.reader(), "after refresh");

    writer.commit().unwrap();
    assert_pinned_view(
        pinned.snapshot(),
        &pinned_keys,
        &pinned_fields,
        "after commit",
    );
    assert_fresh_updated(&writer.reader(), "after commit");

    writer.compact().expect("merge");
    assert_pinned_view(
        pinned.snapshot(),
        &pinned_keys,
        &pinned_fields,
        "after compact",
    );
    assert_fresh_updated(&writer.reader(), "after compact");

    assert_eq!(live_keys(&writer.reader()), ["a".to_owned()]);
    drop(pinned);
    drop(writer);
    drop(directory);
}
#[test]
fn m5_t28_barrier_controlled_readers_never_observe_a_prefix_fs() {
    let temp = TempDir::new("t28");
    // Seed generation 1 through the plain real filesystem so the publication
    // barrier is armed only for the generation-2 commit under test.
    {
        let (_, seed) = setup_with(
            fs_directory(temp.path()),
            vec![base_doc("a", "alpha", 1), base_doc("b", "beta", 2)],
            IndexLimits::new(),
        );
        seed.close().expect("release seed writer");
    }
    let reached = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let published = Arc::new(Barrier::new(2));
    let state = Arc::new(FaultState {
        fail_manifest_create: AtomicBool::new(false),
        fail_current_before: AtomicBool::new(false),
        fail_current_after: AtomicBool::new(false),
        current_reached: Some(Arc::clone(&reached)),
        current_release: Some(Arc::clone(&release)),
    });
    let directory: Arc<dyn Directory> = Arc::new(FaultDirectory {
        inner: fs_directory(temp.path()),
        state,
    });
    let mut writer = reopen(Arc::clone(&directory), IndexLimits::new());
    writer
        .apply_batch(
            &MutationBatch::new(vec![
                MutationCommand::new(
                    MutationTarget::Key(key("c")),
                    MutationAction::Insert(base_doc("c", "gamma", 3)),
                ),
                MutationCommand::new(
                    MutationTarget::Key(key("d")),
                    MutationAction::Insert(base_doc("d", "delta", 4)),
                ),
            ]),
            &CancellationFlag::new(),
        )
        .expect("admit");

    let reader_path = temp.path().to_path_buf();
    let reader_published = Arc::clone(&published);
    let handle = std::thread::spawn(move || {
        // The writer is blocked immediately before replacing CURRENT.
        reached.wait();
        let reader = Index::open_existing(fs_directory(&reader_path), schema(), registry())
            .expect("reader open while CURRENT is blocked");
        assert_eq!(
            live_keys(&reader.snapshot()),
            ["a".to_owned(), "b".to_owned()],
            "pre-publication reader must see exactly the old generation"
        );
        // Allow CURRENT publication and wait until the writer acknowledged it
        // before opening the new generation.
        release.wait();
        reader_published.wait();
        let after = Index::open_existing(fs_directory(&reader_path), schema(), registry())
            .expect("post-publication reader open");
        assert_eq!(
            live_keys(&after.snapshot()),
            [
                "a".to_owned(),
                "b".to_owned(),
                "c".to_owned(),
                "d".to_owned()
            ],
            "post-publication reader must see the complete new generation"
        );
    });
    writer.commit().expect("commit after release");
    published.wait();
    handle.join().expect("reader thread");
} // ===========================================================================
// T29 — one logical script across memory and filesystem
// ===========================================================================

fn run_full_script(
    directory: Arc<dyn Directory>,
) -> (Oracle, IndexWriter, Arc<dyn Directory>, Vec<GenerationView>) {
    let docs = vec![
        base_doc("a", "alpha", 1),
        base_doc("b", "beta", 2),
        base_doc("c", "gamma", 3),
    ];
    let (directory, mut writer) = setup_with(directory, docs.clone(), IndexLimits::new());
    let mut oracle = Oracle::seeded(&docs);
    let mut generations = vec![checkpoint(
        &oracle,
        &writer.reader(),
        Some(1),
        "local G1 seed",
    )];

    let mixed = token(
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("d")),
                MutationAction::Insert(base_doc("d", "delta", 4)),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Update(patch("title", FieldValue::Text("alpha2".to_owned()))),
            ),
            MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
        ]),
        "m5-t29-mixed",
    );
    let mixed_response = writer
        .apply_batch(&mixed, &CancellationFlag::new())
        .expect("mixed");
    assert_eq!(
        response_keys(&mixed_response),
        [
            vec!["d".to_owned()],
            vec!["a".to_owned()],
            vec!["b".to_owned()]
        ],
        "local G2 mixed keys"
    );
    assert_eq!(
        response_revisions(&mixed_response),
        [vec![Some(1)], vec![Some(2)], vec![Some(2)]],
        "local G2 mixed revisions"
    );
    oracle.apply_insert(&base_doc("d", "delta", 4));
    oracle.apply_patch("a", &patch("title", FieldValue::Text("alpha2".to_owned())));
    oracle.apply_delete("b");
    writer.commit().expect("commit mixed");
    generations.push(checkpoint(
        &oracle,
        &writer.reader(),
        Some(2),
        "local G2 mixed",
    ));

    let query_delete = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector(title_term("alpha2"), 10)),
        MutationAction::Delete,
    )]);
    let delete_response = writer
        .apply_batch(&query_delete, &CancellationFlag::new())
        .expect("query delete");
    assert_eq!(
        response_keys(&delete_response),
        [vec!["a".to_owned()]],
        "local G3 query-delete keys"
    );
    assert_eq!(
        response_revisions(&delete_response),
        [vec![Some(3)]],
        "local G3 query-delete revision"
    );
    oracle.apply_delete("a");
    writer.commit().expect("commit query delete");
    generations.push(checkpoint(
        &oracle,
        &writer.reader(),
        Some(3),
        "local G3 query delete",
    ));

    let upsert = token(
        query_upsert_batch(
            title_term("missing"),
            replacement_template(),
            base_doc("e", "fallback", 5),
        ),
        "m5-t29-upsert",
    );
    let upsert_response = writer
        .apply_batch(&upsert, &CancellationFlag::new())
        .expect("query upsert");
    assert_eq!(
        upsert_response.outcomes[0].matched, 0,
        "local G4 upsert matched"
    );
    assert_eq!(
        response_keys(&upsert_response),
        [vec!["e".to_owned()]],
        "local G4 fallback key"
    );
    assert_eq!(
        upsert_response.outcomes[0].keys[0].intent,
        MutationIntent::Insert,
        "local G4 fallback intent"
    );
    assert_eq!(
        response_revisions(&upsert_response),
        [vec![Some(1)]],
        "local G4 fallback revision"
    );
    oracle.apply_insert(&base_doc("e", "fallback", 5));
    writer.commit().expect("commit query upsert");
    let g4 = checkpoint(&oracle, &writer.reader(), Some(4), "local G4 upsert");
    assert_eq!(
        title_field(&g4.fields, "c"),
        Some(FieldValues::Single(FieldValue::Text("gamma".to_owned()))),
        "local G4 c.title must remain gamma"
    );
    generations.push(g4.clone());

    let replace = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector(title_term("gamma"), 10)),
        MutationAction::Replace(gamma_replacement_template()),
    )]);
    let replace_response = writer
        .apply_batch(&replace, &CancellationFlag::new())
        .expect("query replace");
    assert_eq!(
        response_keys(&replace_response),
        [vec!["c".to_owned()]],
        "local G5 replace key"
    );
    assert_eq!(
        response_revisions(&replace_response),
        [vec![Some(2)]],
        "local G5 replace revision"
    );
    oracle.apply_replace("c", &gamma_replacement_template());
    writer.commit().expect("commit query replace");
    let g5 = checkpoint(&oracle, &writer.reader(), Some(5), "local G5 replace");
    assert_eq!(
        title_field(&g5.fields, "c"),
        Some(FieldValues::Single(FieldValue::Text(
            "gamma replaced".to_owned()
        ))),
        "local G5 c.title must be replaced"
    );
    assert_eq!(
        g5.fields
            .get("c")
            .and_then(|values| values.get("body"))
            .cloned(),
        Some(FieldValues::Absent),
        "local G5 c.body must be absent after template replacement"
    );
    assert_eq!(g4.keys, g5.keys, "G4 and G5 must share keys");
    generations.push(g5);

    writer.refresh().expect("refresh");
    (oracle, writer, directory, generations)
}
#[test]
fn m5_t29_same_logical_script_is_equivalent_on_memory_and_filesystem() {
    let (memory_oracle, memory_writer, _, memory_generations) =
        run_full_script(Arc::new(MemoryDirectory::new()));
    memory_oracle.assert_matches(&memory_writer.reader());
    drop(memory_writer);

    let temp = TempDir::new("t29");
    let (fs_oracle, fs_writer, fs_directory_handle, fs_generations) =
        run_full_script(fs_directory(temp.path()));
    fs_oracle.assert_matches(&fs_writer.reader());
    assert_eq!(
        fs_generations, memory_generations,
        "T29: memory and filesystem must agree at every committed G1-G5 generation"
    );
    assert_eq!(
        fs_generations
            .iter()
            .map(|view| view.keys.clone())
            .collect::<Vec<_>>(),
        vec![
            vec!["a".to_owned(), "b".to_owned(), "c".to_owned()],
            vec!["a".to_owned(), "c".to_owned(), "d".to_owned()],
            vec!["c".to_owned(), "d".to_owned()],
            vec!["c".to_owned(), "d".to_owned(), "e".to_owned()],
            vec!["c".to_owned(), "d".to_owned(), "e".to_owned()],
        ],
        "T29: canonical G1-G5 live-key sequence"
    );
    assert_eq!(
        fs_generations
            .iter()
            .map(|view| view.generation)
            .collect::<Vec<_>>(),
        vec![Some(1), Some(2), Some(3), Some(4), Some(5)],
        "T29: canonical committed generation sequence"
    );
    assert_eq!(
        title_field(&fs_generations[3].fields, "c"),
        Some(FieldValues::Single(FieldValue::Text("gamma".to_owned()))),
        "T29: G4 c.title must be gamma"
    );
    assert_eq!(
        title_field(&fs_generations[4].fields, "c"),
        Some(FieldValues::Single(FieldValue::Text(
            "gamma replaced".to_owned()
        ))),
        "T29: G5 c.title must distinguish it from G4"
    );
    drop(fs_writer);
    drop(fs_directory_handle);
}
// ===========================================================================
// T33–T35 — cancellation, limits and token non-consumption
// ===========================================================================

#[test]
fn m5_t33_cancellation_before_and_within_selection_admits_nothing() {
    let (_directory, mut writer) = setup(vec![base_doc("a", "target", 1)]);
    let cancelled = CancellationFlag::new();
    cancelled.cancel();
    let batch = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Query(selector(title_term("target"), 10)),
        MutationAction::Delete,
    )]);
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&batch, &cancelled),
        Err(IndexError::Cancelled)
    ));
    assert_unchanged(&mut writer, &before);

    let polls = Arc::new(AtomicUsize::new(0));
    {
        let (directory, mut warm) = setup(vec![base_doc("a", "target", 1)]);
        let counter = CountPolls(Arc::clone(&polls));
        warm.apply_batch(&batch, &counter).expect("warm");
        drop(warm);
        drop(directory);
    }
    let total = polls.load(Ordering::SeqCst);
    assert!(total > 1, "planner must poll cancellation repeatedly");
    let before = writer_state(&writer);
    let trip = TripAfter {
        skip: total - 1,
        polls: Arc::new(AtomicUsize::new(0)),
    };
    assert!(matches!(
        writer.apply_batch(&batch, &trip),
        Err(IndexError::Cancelled)
    ));
    assert_unchanged(&mut writer, &before);
}

#[test]
fn m5_t34_exact_and_one_over_batch_and_query_limits_fail_closed() {
    // Query match exact / one-over is covered by T10/T11; this test covers the
    // command/key/response/replay ceilings at their exact boundary.
    let two_commands = MutationBatch::new(vec![
        MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Insert(base_doc("a", "alpha", 1)),
        ),
        MutationCommand::new(
            MutationTarget::Key(key("b")),
            MutationAction::Insert(base_doc("b", "beta", 2)),
        ),
    ]);
    let (_directory, mut exact) = setup_with(
        Arc::new(MemoryDirectory::new()),
        Vec::new(),
        IndexLimits::new().with_max_batch_commands(2),
    );
    exact
        .apply_batch(&two_commands, &CancellationFlag::new())
        .expect("exact command limit");
    let (_directory, mut over) = setup_with(
        Arc::new(MemoryDirectory::new()),
        Vec::new(),
        IndexLimits::new().with_max_batch_commands(1),
    );
    let before = writer_state(&over);
    assert!(matches!(
        over.apply_batch(&two_commands, &CancellationFlag::new()),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut over, &before);

    // Exact key ceiling: two keys, limit two; one-over with three keys.
    let (_directory, mut exact) = setup_with(
        Arc::new(MemoryDirectory::new()),
        vec![base_doc("a", "a", 1), base_doc("b", "b", 2)],
        IndexLimits::new().with_max_batch_keys(2),
    );
    exact
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Keys(vec![key("a"), key("b")]),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new(),
        )
        .expect("exact key limit");
    let (_directory, mut over) = setup_with(
        Arc::new(MemoryDirectory::new()),
        vec![
            base_doc("a", "a", 1),
            base_doc("b", "b", 2),
            base_doc("c", "c", 3),
        ],
        IndexLimits::new().with_max_batch_keys(2),
    );
    let before = writer_state(&over);
    assert!(matches!(
        over.apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Keys(vec![key("a"), key("b"), key("c")]),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new()
        ),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut over, &before);

    // Response bytes: 5 header + 16 command + 13 key + 1 key byte = 35.
    let one = MutationBatch::new(vec![MutationCommand::new(
        MutationTarget::Key(key("a")),
        MutationAction::Insert(base_doc("a", "alpha", 1)),
    )]);
    let (_directory, mut exact) = setup_with(
        Arc::new(MemoryDirectory::new()),
        Vec::new(),
        IndexLimits::new().with_max_batch_response_bytes(35),
    );
    exact
        .apply_batch(&one, &CancellationFlag::new())
        .expect("exact response bytes");
    let (_directory, mut over) = setup_with(
        Arc::new(MemoryDirectory::new()),
        Vec::new(),
        IndexLimits::new().with_max_batch_response_bytes(34),
    );
    let before = writer_state(&over);
    assert!(matches!(
        over.apply_batch(&one, &CancellationFlag::new()),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut over, &before);
}

#[test]
fn m5_t35_budget_and_cancellation_failures_consume_no_revision_or_token_memory_and_fs() {
    run_budget_token(Arc::new(MemoryDirectory::new()));
    let temp = TempDir::new("t35");
    run_budget_token(fs_directory(temp.path()));
}

fn run_budget_token(directory: Arc<dyn Directory>) {
    let (_directory, mut writer) = setup_with(
        directory,
        Vec::new(),
        IndexLimits::new().with_max_pending_docs(1),
    );
    let rejected = token(
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("a")),
                MutationAction::Insert(base_doc("a", "alpha", 1)),
            ),
            MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Insert(base_doc("b", "beta", 2)),
            ),
        ]),
        "m5-t35-token",
    );
    let before = writer_state(&writer);
    assert!(matches!(
        writer.apply_batch(&rejected, &CancellationFlag::new()),
        Err(IndexError::ResourceLimit { .. })
    ));
    assert_unchanged(&mut writer, &before);

    // Same token, now a one-document payload: no revision/token was consumed.
    let accepted = token(
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Insert(base_doc("a", "alpha", 1)),
        )]),
        "m5-t35-token",
    );
    let response = writer
        .apply_batch(&accepted, &CancellationFlag::new())
        .expect("token available");
    assert!(!response.replayed);
    assert_eq!(response.outcomes[0].keys[0].revision, Some(1));
}

// ===========================================================================
// T42 — scored search remains unchanged by qualification-only work
// ===========================================================================

#[test]
fn m5_t42_scored_search_still_observes_only_live_documents() {
    let (_directory, mut writer) = setup(vec![
        base_doc("a", "target alpha", 1),
        base_doc("b", "target beta", 2),
    ]);
    let request = UnifiedRequest::new(title_term("target"), TopK::new(10).expect("top-k"));
    let before = UnifiedSearcher::new(
        &writer.reader(),
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &CancellationFlag::new())
    .expect("search before");
    assert_eq!(before.total_hits, 2);
    writer
        .apply_batch(
            &MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Key(key("b")),
                MutationAction::Delete,
            )]),
            &CancellationFlag::new(),
        )
        .expect("delete");
    writer.refresh().unwrap();
    let after = UnifiedSearcher::new(
        &writer.reader(),
        &schema(),
        &registry(),
        SearchLimits::default(),
    )
    .search(&request, &Budgets::new(), &CancellationFlag::new())
    .expect("search after");
    assert_eq!(after.total_hits, 1);
    assert_eq!(after.hits[0].key.as_str(), "a");
    assert!(before.hits.iter().any(|hit| hit.key.as_str() == "b"));
}

// ===========================================================================
// T24/T29–T32/T43 — real RustFS acceptance (ignored; authoritative topology)
// ===========================================================================

#[cfg(feature = "s3")]
#[path = "../../quervant-objectstore/tests/support/mod.rs"]
mod support;

#[cfg(feature = "s3")]
#[test]
#[ignore = "requires a real RustFS service (see .github/workflows/ci.yml)"]
fn m5_t43_real_rustfs_mutation_qualification() {
    real_rustfs::run(async {
        let env = real_rustfs::require_env();
        real_rustfs::full_script(&env).await;
        real_rustfs::admission_without_remote_io(&env).await;
        real_rustfs::interrupted_upload_preserves_generation(&env).await;
    });
}

#[cfg(feature = "s3")]
mod real_rustfs {
    use super::*;
    use quervant_core::remote::{RemoteConfig, RemoteIndex, RemoteKeyPrefix, RemoteTransferConfig};
    use quervant_objectstore::{S3Config, S3ObjectStore};
    use support::{Fault, Proxy, Rule};

    #[derive(Clone)]
    pub struct Env {
        endpoint: String,
        region: String,
        bucket: String,
        access: String,
        secret: String,
    }

    pub fn require_env() -> Env {
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
        Env {
            endpoint,
            region,
            bucket,
            access,
            secret,
        }
    }

    pub fn run<F>(body: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let handle = std::thread::Builder::new()
            .name("m5-rustfs".to_owned())
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

    fn run_tag(label: &str) -> String {
        format!(
            "{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        )
    }

    fn store(env: &Env, endpoint: &str) -> Arc<S3ObjectStore> {
        Arc::new(
            S3ObjectStore::new(S3Config::rustfs(
                endpoint.to_owned(),
                env.region.clone(),
                env.bucket.clone(),
                env.access.clone(),
                env.secret.clone(),
            ))
            .expect("valid RustFS configuration"),
        )
    }

    fn config(prefix: String, cache: PathBuf) -> RemoteConfig {
        RemoteConfig::new(RemoteKeyPrefix::parse(prefix).expect("prefix"), cache).with_transfer(
            RemoteTransferConfig::default()
                .with_range_threshold(256 * 1024)
                .with_chunk_size(32 * 1024)
                .with_max_aggregate_response_bytes(2 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16),
        )
    }

    fn cache_path(name: &str) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("quervant-m5-rustfs-{name}-{}", run_tag("cache")));
        std::fs::create_dir_all(&path).expect("cache directory");
        path
    }

    fn parse_host_port(endpoint: &str) -> (String, u16) {
        let rest = endpoint
            .strip_prefix("http://")
            .or_else(|| endpoint.strip_prefix("https://"))
            .unwrap_or(endpoint)
            .trim_end_matches('/');
        match rest.rsplit_once(':') {
            Some((host, port)) => (host.to_owned(), port.parse().expect("port")),
            None => (rest.to_owned(), 80),
        }
    }

    fn expected_live() -> Vec<String> {
        ["c", "d", "e"].map(str::to_owned).to_vec()
    }

    async fn open_checkpoint(
        store: &Arc<S3ObjectStore>,
        prefix: &str,
        tag: &str,
    ) -> RemoteIndex<S3ObjectStore> {
        RemoteIndex::open_existing(
            Arc::clone(store),
            config(prefix.to_owned(), cache_path(tag)),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .unwrap_or_else(|error| panic!("{tag}: remote committed checkpoint open failed: {error}"))
    }

    pub async fn full_script(env: &Env) {
        let store = store(env, &env.endpoint);
        store.create_bucket_if_absent().await.expect("bucket");
        let tag = run_tag("full");
        let prefix = format!("m5/full/{tag}");
        let cache = cache_path("full");
        let cancel = CancellationFlag::new();
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config(prefix.clone(), cache.clone()),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .expect("create remote index");
        {
            let mut writer = index.writer().await.expect("remote writer");
            for document in [
                base_doc("a", "alpha", 1),
                base_doc("b", "beta", 2),
                base_doc("c", "gamma", 3),
            ] {
                writer.insert(document).expect("insert");
            }
            writer.commit().await.expect("seed commit");
        }
        drop(index);

        let docs = vec![
            base_doc("a", "alpha", 1),
            base_doc("b", "beta", 2),
            base_doc("c", "gamma", 3),
        ];
        let mut oracle = Oracle::seeded(&docs);
        let mut generations = Vec::new();

        // G1: seed.
        let index = open_checkpoint(&store, &prefix, "full-g1").await;
        generations.push(checkpoint(
            &oracle,
            &index.snapshot(),
            Some(1),
            "rustfs G1 seed",
        ));
        drop(index);

        // G2: mixed explicit insert/patch/delete.
        let mixed = token(
            MutationBatch::new(vec![
                MutationCommand::new(
                    MutationTarget::Key(key("d")),
                    MutationAction::Insert(base_doc("d", "delta", 4)),
                ),
                MutationCommand::new(
                    MutationTarget::Key(key("a")),
                    MutationAction::Update(patch("title", FieldValue::Text("alpha2".to_owned()))),
                ),
                MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
            ]),
            &format!("{tag}-mixed"),
        );
        let index = open_checkpoint(&store, &prefix, "full-g2-writer").await;
        {
            let mut writer = index.writer().await.expect("remote G2 writer");
            let response = writer.apply_batch(&mixed, &cancel).expect("mixed");
            assert_eq!(
                response_keys(&response),
                [
                    vec!["d".to_owned()],
                    vec!["a".to_owned()],
                    vec!["b".to_owned()]
                ],
                "rustfs G2 mixed keys"
            );
            assert_eq!(
                response_revisions(&response),
                [vec![Some(1)], vec![Some(2)], vec![Some(2)]],
                "rustfs G2 mixed revisions"
            );
            writer.commit().await.expect("mixed commit");
        }
        drop(index);
        oracle.apply_insert(&base_doc("d", "delta", 4));
        oracle.apply_patch("a", &patch("title", FieldValue::Text("alpha2".to_owned())));
        oracle.apply_delete("b");
        let index = open_checkpoint(&store, &prefix, "full-g2").await;
        generations.push(checkpoint(
            &oracle,
            &index.snapshot(),
            Some(2),
            "rustfs G2 mixed",
        ));
        drop(index);

        // G3: query delete selected from committed G2.
        let index = open_checkpoint(&store, &prefix, "full-g3-writer").await;
        {
            let mut writer = index.writer().await.expect("remote G3 writer");
            let response = writer
                .apply_batch(
                    &MutationBatch::new(vec![MutationCommand::new(
                        MutationTarget::Query(selector(title_term("alpha2"), 10)),
                        MutationAction::Delete,
                    )]),
                    &cancel,
                )
                .expect("query delete");
            assert_eq!(
                response_keys(&response),
                [vec!["a".to_owned()]],
                "rustfs G3 query-delete keys"
            );
            assert_eq!(
                response_revisions(&response),
                [vec![Some(3)]],
                "rustfs G3 query-delete revision"
            );
            writer.commit().await.expect("delete commit");
        }
        drop(index);
        oracle.apply_delete("a");
        let index = open_checkpoint(&store, &prefix, "full-g3").await;
        generations.push(checkpoint(
            &oracle,
            &index.snapshot(),
            Some(3),
            "rustfs G3 query delete",
        ));
        drop(index);

        // G4: zero-match query upsert with explicit fallback.
        let upsert = token(
            query_upsert_batch(
                title_term("missing"),
                replacement_template(),
                base_doc("e", "fallback", 5),
            ),
            &format!("{tag}-upsert"),
        );
        let index = open_checkpoint(&store, &prefix, "full-g4-writer").await;
        {
            let mut writer = index.writer().await.expect("remote G4 writer");
            let response = writer.apply_batch(&upsert, &cancel).expect("query upsert");
            assert_eq!(response.outcomes[0].matched, 0, "rustfs G4 upsert matched");
            assert_eq!(
                response_keys(&response),
                [vec!["e".to_owned()]],
                "rustfs G4 fallback key"
            );
            assert_eq!(
                response.outcomes[0].keys[0].intent,
                MutationIntent::Insert,
                "rustfs G4 fallback intent"
            );
            assert_eq!(
                response_revisions(&response),
                [vec![Some(1)]],
                "rustfs G4 fallback revision"
            );
            writer.commit().await.expect("upsert commit");
        }
        drop(index);
        oracle.apply_insert(&base_doc("e", "fallback", 5));
        let index = open_checkpoint(&store, &prefix, "full-g4").await;
        let g4 = checkpoint(&oracle, &index.snapshot(), Some(4), "rustfs G4 upsert");
        assert_eq!(
            title_field(&g4.fields, "c"),
            Some(FieldValues::Single(FieldValue::Text("gamma".to_owned()))),
            "rustfs G4 c.title must remain gamma"
        );
        generations.push(g4.clone());
        drop(index);

        // G5: query replace selected from committed G4. Same keys as G4 but
        // c's fields and revision must differ.
        let index = open_checkpoint(&store, &prefix, "full-g5-writer").await;
        {
            let mut writer = index.writer().await.expect("remote G5 writer");
            let response = writer
                .apply_batch(
                    &MutationBatch::new(vec![MutationCommand::new(
                        MutationTarget::Query(selector(title_term("gamma"), 10)),
                        MutationAction::Replace(gamma_replacement_template()),
                    )]),
                    &cancel,
                )
                .expect("query replace");
            assert_eq!(
                response_keys(&response),
                [vec!["c".to_owned()]],
                "rustfs G5 replace key"
            );
            assert_eq!(
                response_revisions(&response),
                [vec![Some(2)]],
                "rustfs G5 replace revision"
            );
            writer.commit().await.expect("replace commit");
        }
        drop(index);
        oracle.apply_replace("c", &gamma_replacement_template());
        let index = open_checkpoint(&store, &prefix, "full-g5").await;
        let g5 = checkpoint(&oracle, &index.snapshot(), Some(5), "rustfs G5 replace");
        assert_eq!(
            title_field(&g5.fields, "c"),
            Some(FieldValues::Single(FieldValue::Text(
                "gamma replaced".to_owned()
            ))),
            "rustfs G5 c.title must be replaced"
        );
        assert_eq!(
            g5.fields
                .get("c")
                .and_then(|values| values.get("body"))
                .cloned(),
            Some(FieldValues::Absent),
            "rustfs G5 c.body must be absent after template replacement"
        );
        assert_eq!(g4.keys, g5.keys, "rustfs G4 and G5 must share keys");
        generations.push(g5);
        drop(index);

        // T30/T31: remove the disposable local cache and cold-bootstrap G5 from
        // authoritative remote objects in a fresh empty cache.
        std::fs::remove_dir_all(&cache).expect("remove cache");
        let reopened = open_checkpoint(&store, &prefix, "full-cold-g5").await;
        let final_view = checkpoint(
            &oracle,
            &reopened.snapshot(),
            Some(5),
            "rustfs cold G5 bootstrap",
        );
        assert_eq!(final_view.keys, expected_live());
        assert_eq!(final_view, generations[4]);

        // T19: replay the original mixed batch after cold reopen. It must return
        // the original response without reselecting or mutating committed state.
        let mut writer = reopened.writer().await.expect("reopened writer");
        let replay = writer.apply_batch(&mixed, &cancel).expect("remote replay");
        assert!(replay.replayed, "rustfs replay must be marked replayed");
        assert_eq!(
            response_keys(&replay),
            [
                vec!["d".to_owned()],
                vec!["a".to_owned()],
                vec!["b".to_owned()]
            ],
            "rustfs replay must return the original mixed keys"
        );
        assert_eq!(
            response_revisions(&replay),
            [vec![Some(1)], vec![Some(2)], vec![Some(2)]],
            "rustfs replay must return the original mixed revisions"
        );
        writer.commit().await.expect("no-op replay commit");
        drop(writer);
        let after_replay = open_checkpoint(&store, &prefix, "full-after-replay").await;
        assert_eq!(
            checkpoint(
                &oracle,
                &after_replay.snapshot(),
                Some(5),
                "rustfs after replay"
            ),
            final_view,
            "rustfs replay must not mutate committed logical state"
        );
    }

    pub async fn admission_without_remote_io(env: &Env) {
        let (host, port) = parse_host_port(&env.endpoint);
        let proxy = Proxy::start(&host, port).await;
        let direct = store(env, &env.endpoint);
        direct.create_bucket_if_absent().await.expect("bucket");
        let store = store(env, &proxy.endpoint);
        let tag = run_tag("admission");
        let prefix = format!("m5/admission/{tag}");
        let cache = cache_path("admission");
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config(prefix.clone(), cache.clone()),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .expect("create through proxy");
        let cancel = CancellationFlag::new();
        {
            let mut writer = index.writer().await.expect("writer");
            writer.insert(base_doc("a", "alpha", 1)).expect("insert");
            writer.commit().await.expect("seed commit");

            let before: usize = proxy.observed_all().iter().map(|(_, count)| *count).sum();
            writer
                .apply_batch(
                    &MutationBatch::new(vec![MutationCommand::new(
                        MutationTarget::Key(key("b")),
                        MutationAction::Insert(base_doc("b", "beta", 2)),
                    )]),
                    &cancel,
                )
                .expect("admission");
            let after_admission: usize = proxy.observed_all().iter().map(|(_, count)| *count).sum();
            assert_eq!(
                after_admission, before,
                "remote admission must perform zero remote I/O"
            );
            writer.commit().await.expect("commit");
            let after_commit: usize = proxy.observed_all().iter().map(|(_, count)| *count).sum();
            assert!(
                after_commit > after_admission,
                "commit must publish through the remote adapter"
            );
        }
        drop(index);
        std::fs::remove_dir_all(&cache).expect("remove cache");
        let reopened = RemoteIndex::open_existing(
            Arc::clone(&store),
            config(prefix, cache_path("admission-fresh")),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .expect("reopen through proxy");
        assert_eq!(reopened.generation(), Some(2));
        assert_eq!(
            live_keys(&reopened.snapshot()),
            ["a".to_owned(), "b".to_owned()]
        );
        proxy.stop().await;
    }

    pub async fn interrupted_upload_preserves_generation(env: &Env) {
        let (host, port) = parse_host_port(&env.endpoint);
        let proxy = Proxy::start(&host, port).await;
        let direct = store(env, &env.endpoint);
        direct.create_bucket_if_absent().await.expect("bucket");
        let store = store(env, &proxy.endpoint);
        let tag = run_tag("interrupt");
        let prefix = format!("m5/interrupt/{tag}");
        let cache = cache_path("interrupt");
        let index = RemoteIndex::create(
            Arc::clone(&store),
            config(prefix.clone(), cache.clone()),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .expect("create through proxy");
        let cancel = CancellationFlag::new();
        {
            let mut writer = index.writer().await.expect("writer");
            writer.insert(base_doc("a", "alpha", 1)).expect("insert");
            writer.commit().await.expect("seed commit");
            proxy.add_rule(Rule {
                method: "PUT".to_owned(),
                key_contains: "index/state".to_owned(),
                nth: 0,
                fault: Fault::Return503,
            });
            writer
                .apply_batch(
                    &MutationBatch::new(vec![MutationCommand::new(
                        MutationTarget::Key(key("b")),
                        MutationAction::Insert(base_doc("b", "beta", 2)),
                    )]),
                    &cancel,
                )
                .expect("admission");
            assert!(
                writer.commit().await.is_err(),
                "interrupted state upload must fail publication"
            );
        }
        drop(index);
        std::fs::remove_dir_all(&cache).expect("remove cache");
        let reopened = RemoteIndex::open_existing(
            Arc::clone(&store),
            config(prefix, cache_path("interrupt-fresh")),
            schema(),
            registry(),
            IndexLimits::new(),
        )
        .await
        .expect("reopen old generation");
        assert_eq!(reopened.generation(), Some(1));
        assert_eq!(live_keys(&reopened.snapshot()), ["a".to_owned()]);
        proxy.stop().await;
    }
}
