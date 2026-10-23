//! Local single cooperating writer: mutations, flush, refresh and durable commit.
//!
//! Separation of concerns is deliberate:
//!
//! * [`IndexWriter::apply`] admits one typed [`MutationRequest`] into an ordered
//!   journal with deterministic revision allocation and idempotency replay.
//! * [`IndexWriter::flush`] builds immutable segment bytes **without** making
//!   them durable or visible to committed readers.
//! * [`IndexWriter::refresh`] publishes a new volatile immutable reader view
//!   whose generation-specific live mask reflects every accepted operation.
//! * [`IndexWriter::commit`] durably installs segments, the mutation-state
//!   sidecar, the generation manifest and, last, the atomic `CURRENT` pointer.
//!
//! The writer holds `index/WRITER_LOCK` for its whole lifetime. A stale lock
//! after a crash is never stolen automatically; an operator must remove it.
//!
//! Acknowledgment of [`IndexWriter::apply`] means admitted to volatile writer
//! state, **not** durable. Only a successful [`IndexWriter::commit`] is durable.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use quervant_objectstore::ContentDigest;

use crate::analysis::AnalyzerRegistry;
use crate::analysis::Cancellation;
use crate::contract::document::{
    Document, DocumentKey, IdempotencyKey, MutationIntent, MutationRequest, MutationResponse,
};
use crate::contract::error::{DocumentError, InvalidBatchReason, QueryError};
use crate::contract::mutation::{
    MutationAction, MutationBatch, MutationBatchResponse, MutationCommand, MutationCommandOutcome,
    MutationKeyOutcome, MutationPrecondition, MutationRejection, MutationTarget,
    QueryMutationSelector, ReconstructionFailure,
};
use crate::search::SearchLimits;
use crate::segment::format::{FEATURE_MUTATION_STATE, FEATURE_MUTATION_STATE_V2};
use crate::segment::{Manifest, ManifestSegmentRef, MutationStateRef, SegmentDocument};
use crate::storage::{Directory, StorageError, StorageKey};

use super::CommittedState;
use super::current::{
    CURRENT_KEY, CurrentPointer, WRITER_LOCK_KEY, manifest_key_for, state_key_for_hex,
};
use super::error::{IndexError, IndexResult};
use super::limits::IndexLimits;
use super::mutation_state::{
    BatchReplayRow, KeyRow, KeyStatus, MutationStateV1, ReplayRow, batch_fingerprint,
    mutation_fingerprint,
};
use super::pit::{self, PinCounter, PitHandle};
use super::query_selection::{SelectionOutcome, select_query_keys};
use super::reconstruct::{
    SourceMeter, apply_document_patch, reconstruct_from_document, reconstruct_from_segment,
    validate_patch_shape,
};
use super::snapshot::{ReaderSnapshot, SegmentMeta, SegmentSnapshot};
use super::visibility;
use super::{IndexOrigin, support};

/// Outcome of a flush.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FlushOutcome {
    /// Segments moved from the pending batch into the flushed set.
    pub segments_flushed: u64,
    /// Documents flushed.
    pub documents: u64,
}

/// Outcome of an explicit retention request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetentionOutcome {
    /// The caller-supplied operational policy reason.
    pub reason: String,
    /// The deduplicated keys admitted as delete mutations, in request order.
    pub deleted: Vec<DocumentKey>,
}

/// Outcome of a durable commit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommitOutcome {
    /// The durable generation now authoritative.
    pub generation: u64,
    /// Documents added by this commit.
    pub documents: u64,
    /// Immutable segments added by this commit.
    pub segments_added: u64,
    /// Whether the commit was a no-op returning an existing generation.
    pub no_op: bool,
}

/// Where one accepted live mutation's winning document currently resides.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MutationLocation {
    /// Index into the unflushed pending batch (physical doc id in the next
    /// segment built from that batch).
    Pending(usize),
    /// Flushed segment index and physical doc id within it.
    Flushed { segment: usize, doc_id: u64 },
}

/// One accepted mutation in admission order.
struct AcceptedOp {
    key: DocumentKey,
    revision: u64,
    location: Option<MutationLocation>,
}

/// A fully validated, not-yet-installed atomic mutation batch.
///
/// It owns only *new* state plus copies of affected key/replay metadata; reads
/// borrow the immutable committed and writer state. Nothing here is installed
/// until every fallible check and allocation has succeeded.
struct BatchDelta {
    appended_journal: Vec<AcceptedOp>,
    appended_pending: Vec<SegmentDocument>,
    /// Planning-only full documents for live keys touched by this batch.
    ///
    /// This map is never installed into the writer or persisted; it lets later
    /// commands in the same batch use an earlier command's complete document as
    /// their source without decoding a stale refresh view.
    prospective_documents: BTreeMap<DocumentKey, Document>,
    admitted_overrides: BTreeMap<DocumentKey, (u64, KeyStatus)>,
    batch_replay_entry: Option<BatchReplayRow>,
    pending_bytes_delta: u64,
    response: MutationBatchResponse,
}

/// The result of planning a batch: either an exact replay or a delta to install.
enum PlannedBatch {
    Replay(MutationBatchResponse),
    Admit(Box<BatchDelta>),
}

/// Fixed-width placeholder standing in for the not-yet-built pending segment id
/// during mutation-state size preflight. Real ids are `s-` plus a SHA-256 hex
/// string, so this yields an exact encoded-size bound.
const PENDING_SEGMENT_ID_PLACEHOLDER: &str =
    "s-0000000000000000000000000000000000000000000000000000000000000000";

/// A built-but-uncommitted segment.
#[derive(Clone)]
struct PendingSegment {
    meta: SegmentMeta,
    bytes: Arc<Vec<u8>>,
    doc_count: u64,
}

impl PendingSegment {
    fn snapshot(&self) -> SegmentSnapshot {
        SegmentSnapshot::new(self.meta.clone(), Arc::clone(&self.bytes), self.doc_count)
    }

    fn to_ref(&self) -> ManifestSegmentRef {
        let descriptor = self.meta.descriptor();
        ManifestSegmentRef {
            segment_id: self.meta.segment_id().to_owned(),
            object_key: self.meta.object_key().to_owned(),
            content_algorithm: 0,
            content_length: descriptor.length,
            content_digest: *descriptor.digest.as_bytes(),
            time_bounds: self.meta.time_bounds().cloned(),
            required_features: self.meta.required_features().to_vec(),
            optional_features: self.meta.optional_features().to_vec(),
        }
    }
}

/// The exclusive cooperating-writer lock guard.
struct WriterLock {
    directory: Arc<dyn Directory>,
    key: StorageKey,
    released: bool,
}

impl WriterLock {
    fn acquire(directory: &Arc<dyn Directory>) -> IndexResult<Self> {
        let key = StorageKey::parse(WRITER_LOCK_KEY)?;
        match directory.create(&key) {
            Ok(mut handle) => {
                let write = handle
                    .write_all(b"quervant-writer-lock-v1\n")
                    .and_then(|()| handle.sync_all())
                    .and_then(|()| directory.sync());
                if let Err(error) = write {
                    drop(handle);
                    let _ = directory.delete(&key);
                    return Err(error.into());
                }
                Ok(Self {
                    directory: Arc::clone(directory),
                    key,
                    released: false,
                })
            }
            Err(StorageError::AlreadyExists { .. }) => Err(IndexError::WriterBusy),
            Err(error) => Err(error.into()),
        }
    }

    fn release(&mut self) -> IndexResult<()> {
        if self.released {
            return Ok(());
        }
        self.directory.delete(&self.key)?;
        self.released = true;
        Ok(())
    }
}

impl Drop for WriterLock {
    fn drop(&mut self) {
        let _ = self.release();
    }
}

/// A single cooperating index writer.
pub struct IndexWriter {
    directory: Arc<dyn Directory>,
    schema: crate::contract::schema::Schema,
    registry: AnalyzerRegistry,
    limits: IndexLimits,
    pins: Arc<PinCounter>,
    lock: WriterLock,
    committed: Option<CommittedState>,
    journal: Vec<AcceptedOp>,
    admitted: BTreeMap<DocumentKey, (u64, KeyStatus)>,
    replay: BTreeMap<IdempotencyKey, ReplayRow>,
    batch_replay: BTreeMap<IdempotencyKey, BatchReplayRow>,
    pending: Vec<SegmentDocument>,
    pending_bytes: u64,
    flushed: Vec<PendingSegment>,
    published: Option<Arc<ReaderSnapshot>>,
    next_view: u64,
    poisoned: bool,
    /// Test-only count of committed admission installations.
    #[cfg(test)]
    install_transitions: usize,
}

impl IndexWriter {
    pub(crate) fn open(
        directory: Arc<dyn Directory>,
        schema: crate::contract::schema::Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
        pins: Arc<PinCounter>,
        origin: IndexOrigin,
    ) -> IndexResult<Self> {
        support::ensure_layout(directory.as_ref())?;
        let lock = WriterLock::acquire(&directory)?;
        // One authoritative CURRENT resolution *while holding the lock*. The
        // cached state on the originating `Index` handle is never writer
        // authority, so intervening commits cannot be lost.
        let committed = match support::read_current(directory.as_ref())? {
            Some(pointer) => Some(super::load_committed_at(
                directory.as_ref(),
                &schema,
                &registry,
                &limits,
                pointer,
            )?),
            None => match origin {
                IndexOrigin::CreatedEmpty => None,
                IndexOrigin::OpenedExisting => return Err(IndexError::NotInitialized),
            },
        };
        Ok(Self {
            directory,
            schema,
            registry,
            limits,
            pins,
            lock,
            committed,
            journal: Vec::new(),
            admitted: BTreeMap::new(),
            replay: BTreeMap::new(),
            batch_replay: BTreeMap::new(),
            pending: Vec::new(),
            pending_bytes: 0,
            flushed: Vec::new(),
            published: None,
            next_view: 0,
            poisoned: false,
            #[cfg(test)]
            install_transitions: 0,
        })
    }

    /// Explicitly release the cooperating-writer lock.
    pub fn close(mut self) -> IndexResult<()> {
        self.lock.release()
    }

    /// The current committed generation, if any.
    #[must_use]
    pub fn generation(&self) -> Option<u64> {
        self.committed.as_ref().map(|state| state.generation)
    }

    /// Number of documents in the pending batch.
    #[must_use]
    pub fn pending_documents(&self) -> usize {
        self.pending.len()
    }

    /// Number of built-but-uncommitted segments.
    #[must_use]
    pub fn flushed_segments(&self) -> usize {
        self.flushed.len()
    }

    /// Number of accepted-but-uncommitted operations.
    #[must_use]
    pub fn pending_mutations(&self) -> usize {
        self.journal.len()
    }

    /// Admit one insert-only document.
    ///
    /// The logical key is rejected if it is currently live in the committed or
    /// accepted state. A key with a committed tombstone may be reinserted.
    pub fn insert(&mut self, document: Document) -> IndexResult<()> {
        self.apply(MutationRequest::insert(document)).map(|_| ())
    }

    /// Apply a typed mutation request.
    ///
    /// Validates the request and schema, then admits one accepted operation with
    /// a deterministic next revision. Idempotency replay returns the original
    /// response without allocating a revision or a new physical document.
    pub fn apply(&mut self, request: MutationRequest) -> IndexResult<MutationResponse> {
        self.ensure_writable()?;
        request.validate()?;
        if let Some(document) = &request.document {
            self.schema
                .validate_document(document, self.limits.budgets())?;
        }
        let fingerprint =
            mutation_fingerprint(request.intent, &request.key, request.document.as_ref())?;

        if let Some(token) = &request.idempotency_key {
            // Single-key and batch replay tokens share one namespace.
            if self.lookup_batch_replay(token).is_some() {
                return Err(IndexError::IdempotencyConflict {
                    token: token.as_str().to_owned(),
                });
            }
            if let Some(existing) = self.lookup_replay(token) {
                if existing.fingerprint == fingerprint {
                    return Ok(MutationResponse {
                        key: request.key,
                        intent: request.intent,
                        revision: Some(existing.revision),
                        replayed: true,
                    });
                }
                return Err(IndexError::IdempotencyConflict {
                    token: token.as_str().to_owned(),
                });
            }
            self.check_replay_capacity()?;
        }

        let (previous_revision, current_status) = self.candidate_state_for(&request.key);
        if request.intent == MutationIntent::Insert && current_status == Some(KeyStatus::Live) {
            return Err(IndexError::DuplicateDocument {
                key: request.key.as_str().to_owned(),
            });
        }
        let revision = previous_revision
            .checked_add(1)
            .ok_or(IndexError::RevisionOverflow)?;

        // Preflight the physical pending batch before any state mutation.
        let location = match request.intent {
            MutationIntent::Delete => None,
            MutationIntent::Insert | MutationIntent::Upsert => {
                let document = request
                    .document
                    .as_ref()
                    .ok_or(IndexError::UnsupportedMutation)?;
                let size = u64::try_from(document.approx_size()).unwrap_or(u64::MAX);
                let new_count = self.pending.len() as u64 + 1;
                if new_count > self.limits.max_pending_docs() {
                    return Err(IndexError::ResourceLimit {
                        limit: self.limits.max_pending_docs(),
                        requested: new_count,
                    });
                }
                let new_bytes = self.pending_bytes.saturating_add(size);
                if new_bytes > self.limits.max_pending_bytes() {
                    return Err(IndexError::ResourceLimit {
                        limit: self.limits.max_pending_bytes(),
                        requested: new_bytes,
                    });
                }
                let doc_id = self.pending.len();
                self.pending.push(to_segment_document(document));
                self.pending_bytes = new_bytes;
                Some(MutationLocation::Pending(doc_id))
            }
        };

        let status = if location.is_some() {
            KeyStatus::Live
        } else {
            KeyStatus::Deleted
        };
        self.admitted
            .insert(request.key.clone(), (revision, status));
        self.journal.push(AcceptedOp {
            key: request.key.clone(),
            revision,
            location,
        });
        if let Some(token) = request.idempotency_key.clone() {
            self.replay.insert(
                token.clone(),
                ReplayRow {
                    token,
                    fingerprint,
                    key: request.key.clone(),
                    intent: request.intent,
                    revision,
                },
            );
        }
        Ok(MutationResponse {
            key: request.key,
            intent: request.intent,
            revision: Some(revision),
            replayed: false,
        })
    }

    /// Apply an ordered, atomic mutation batch over explicit logical keys.
    ///
    /// The whole batch is validated, simulated against a prospective overlay,
    /// resource-checked and fully allocated **before** a single non-fallible
    /// installation step. A failure on any command - including the last - has
    /// exactly the same state effect as a failure on the first: none.
    ///
    /// The batch remains volatile until [`Self::refresh`] (visibility) or
    /// [`Self::commit`] (durability), exactly like [`Self::apply`].
    pub fn apply_batch(
        &mut self,
        batch: &MutationBatch,
        cancel: &dyn Cancellation,
    ) -> IndexResult<MutationBatchResponse> {
        self.ensure_writable()?;
        match self.plan_batch(batch, cancel)? {
            PlannedBatch::Replay(response) => Ok(response),
            PlannedBatch::Admit(delta) => self.install_batch(*delta),
        }
    }

    /// Atomically tombstone every live key selected by `selector`.
    ///
    /// This is a thin convenience delegation to [`Self::apply_batch`]: it
    /// constructs exactly one `Query` + `Delete` command, so selection,
    /// revision checks, limits, replay and the single non-fallible
    /// installation are the same code path. It performs no remote I/O.
    pub fn delete_by_query(
        &mut self,
        selector: QueryMutationSelector,
        cancel: &dyn Cancellation,
    ) -> IndexResult<MutationBatchResponse> {
        let batch = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(selector),
            MutationAction::Delete,
        )]);
        self.apply_batch(&batch, cancel)
    }

    /// Phases A-C: validate, simulate and size a batch without touching state.
    fn plan_batch(
        &self,
        batch: &MutationBatch,
        cancel: &dyn Cancellation,
    ) -> IndexResult<PlannedBatch> {
        // ---------------- Phase A: immutable preflight ----------------
        if cancel.is_cancelled() {
            return Err(IndexError::Cancelled);
        }
        if batch.commands.is_empty() {
            return Err(IndexError::Contract(QueryError::InvalidBatch(
                InvalidBatchReason::Empty,
            )));
        }
        let command_count = batch.commands.len() as u64;
        if command_count > self.limits.max_batch_commands() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_batch_commands(),
                requested: command_count,
            });
        }

        // Admission-work ceiling: count the caller's raw explicit-key
        // occurrences before any per-key expansion, deduplication or
        // allocation proportional to the input length.
        batch_raw_key_preflight(batch, cancel, self.limits.max_batch_keys())?;

        // Target/action matrix plus first-occurrence key dedupe. Query targets
        // are resolved only after replay lookup, against one committed
        // batch-initial snapshot.
        let mut resolved: Vec<Vec<DocumentKey>> = Vec::new();
        resolved
            .try_reserve_exact(batch.commands.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_batch_commands(),
                requested: command_count,
            })?;
        let mut logical_ops: u64 = 0;
        let mut contains_query = false;
        for command in &batch.commands {
            if cancel.is_cancelled() {
                return Err(IndexError::Cancelled);
            }
            if matches!(command.target, MutationTarget::Query(_)) {
                contains_query = true;
                resolved.push(Vec::new());
                continue;
            }
            let keys = resolve_batch_target(command)?;
            logical_ops =
                logical_ops
                    .checked_add(keys.len() as u64)
                    .ok_or(IndexError::ResourceLimit {
                        limit: self.limits.max_batch_keys(),
                        requested: u64::MAX,
                    })?;
            resolved.push(keys);
        }
        if logical_ops > self.limits.max_batch_keys() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_batch_keys(),
                requested: logical_ops,
            });
        }

        // Full schema validation, patch shape validation and key/document
        // agreement. Patch structure is checked here, before the whole-batch
        // fingerprint and replay lookup, so malformed requests are rejected
        // consistently even when a matching idempotency token exists.
        for (command, keys) in batch.commands.iter().zip(&resolved) {
            if let MutationTarget::Query(selector) = &command.target {
                // Shape/action and zero-bound checks already ran in the raw
                // preflight. Validate the AST through the authoritative query
                // validator before fingerprint/replay lookup.
                selector
                    .query
                    .validate(&self.schema, self.limits.budgets())?;
            } else if let MutationAction::Update(patch) = &command.action {
                validate_patch_shape(patch, &self.schema)?;
            } else if let Some(document) = action_document(&command.action) {
                self.schema
                    .validate_document(document, self.limits.budgets())?;
                if keys.len() != 1 || document.key() != &keys[0] {
                    return Err(IndexError::Contract(QueryError::InvalidDocument(
                        DocumentError::TypeMismatch {
                            field: "document.key".to_owned(),
                        },
                    )));
                }
            }
        }

        // Domain-separated whole-batch fingerprint, then replay lookup.
        let fingerprint = batch_fingerprint(batch)?;
        if let Some(token) = &batch.idempotency_key {
            if self.lookup_replay(token).is_some() {
                return Err(IndexError::IdempotencyConflict {
                    token: token.as_str().to_owned(),
                });
            }
            if let Some(existing) = self.lookup_batch_replay(token) {
                if existing.fingerprint == fingerprint {
                    return Ok(PlannedBatch::Replay(existing.replay_response()));
                }
                return Err(IndexError::IdempotencyConflict {
                    token: token.as_str().to_owned(),
                });
            }
        }

        // ---------------- Phase A2: committed query selection ----------------
        //
        // Replay lookup above always wins: a matching durable token returns the
        // original result without running this generation check or selector.
        let mut selected_revisions: BTreeMap<DocumentKey, u64> = BTreeMap::new();
        if contains_query {
            let committed_generation = self.generation();
            for command in &batch.commands {
                let MutationTarget::Query(selector) = &command.target else {
                    continue;
                };
                if let Some(expected) = selector.expected_generation {
                    if committed_generation != Some(expected) {
                        return Err(IndexError::MutationRejected {
                            rejection: MutationRejection::StaleSelection,
                        });
                    }
                }
            }
            let snapshot = self.committed_snapshot();
            let committed_state = self.committed_state_arc();
            let search_limits = SearchLimits::default();
            for (index, command) in batch.commands.iter().enumerate() {
                let MutationTarget::Query(selector) = &command.target else {
                    continue;
                };
                if cancel.is_cancelled() {
                    return Err(IndexError::Cancelled);
                }
                let effective_limit = selector
                    .max_matches
                    .min(self.limits.max_query_matches())
                    .min(self.limits.max_batch_keys());
                let outcome = select_query_keys(
                    &snapshot,
                    &self.schema,
                    &self.registry,
                    search_limits,
                    self.limits.budgets(),
                    committed_state.as_deref(),
                    selector,
                    effective_limit,
                    cancel,
                )?;
                match outcome {
                    SelectionOutcome::LimitExceeded { limit, matched } => {
                        return Err(IndexError::MutationRejected {
                            rejection: MutationRejection::MatchLimitExceeded { limit, matched },
                        });
                    }
                    SelectionOutcome::Complete(selected) => {
                        let mut keys: Vec<DocumentKey> = Vec::new();
                        keys.try_reserve_exact(selected.len()).map_err(|_| {
                            IndexError::ResourceLimit {
                                limit: self.limits.max_batch_keys(),
                                requested: selected.len() as u64,
                            }
                        })?;
                        for selected_key in selected {
                            selected_revisions
                                .insert(selected_key.key.clone(), selected_key.revision);
                            keys.push(selected_key.key);
                        }
                        logical_ops = logical_ops.checked_add(keys.len() as u64).ok_or(
                            IndexError::ResourceLimit {
                                limit: self.limits.max_batch_keys(),
                                requested: u64::MAX,
                            },
                        )?;
                        if logical_ops > self.limits.max_batch_keys() {
                            return Err(IndexError::ResourceLimit {
                                limit: self.limits.max_batch_keys(),
                                requested: logical_ops,
                            });
                        }
                        resolved[index] = keys;
                    }
                }
            }
        }

        // ---------------- Phase B: prospective simulation ----------------
        let old_pending_len = self.pending.len();
        let mut delta = BatchDelta {
            appended_journal: Vec::new(),
            appended_pending: Vec::new(),
            prospective_documents: BTreeMap::new(),
            admitted_overrides: BTreeMap::new(),
            batch_replay_entry: None,
            pending_bytes_delta: 0,
            response: MutationBatchResponse {
                outcomes: Vec::new(),
                replayed: false,
            },
        };
        delta
            .appended_journal
            .try_reserve_exact(logical_ops as usize)
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_batch_keys(),
                requested: logical_ops,
            })?;
        delta
            .appended_pending
            .try_reserve_exact(logical_ops as usize)
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_batch_keys(),
                requested: logical_ops,
            })?;
        delta
            .response
            .outcomes
            .try_reserve_exact(batch.commands.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_batch_commands(),
                requested: command_count,
            })?;
        let mut source_meter = SourceMeter::new(self.limits.max_snapshot_bytes());

        for (index, command) in batch.commands.iter().enumerate() {
            if cancel.is_cancelled() {
                return Err(IndexError::Cancelled);
            }
            let intent = action_intent(&command.action);
            let keys = &resolved[index];
            let mut key_outcomes: Vec<MutationKeyOutcome> = Vec::new();
            key_outcomes
                .try_reserve_exact(keys.len())
                .map_err(|_| IndexError::ResourceLimit {
                    limit: self.limits.max_batch_keys(),
                    requested: keys.len() as u64,
                })?;
            for key in keys {
                if cancel.is_cancelled() {
                    return Err(IndexError::Cancelled);
                }
                if matches!(command.target, MutationTarget::Query(_)) {
                    let selected_revision =
                        selected_revisions.get(key).copied().ok_or_else(|| {
                            IndexError::CorruptCommittedState {
                                detail: "query-selected key has no committed revision evidence"
                                    .to_owned(),
                            }
                        })?;
                    // Selection evidence is compared with the writer's
                    // batch-initial effective state, including preexisting
                    // pending/flushed journal entries.
                    let (writer_revision, writer_status) = self.candidate_state_for(key);
                    if writer_status != Some(KeyStatus::Live)
                        || writer_revision != selected_revision
                    {
                        return Err(IndexError::MutationRejected {
                            rejection: MutationRejection::PreconditionFailed {
                                key: key.clone(),
                                expected: MutationPrecondition::ExpectedRevision(selected_revision),
                            },
                        });
                    }
                    // A key already touched by an earlier command in this same
                    // batch is an overlap, not a silent second revision.
                    if delta.admitted_overrides.contains_key(key) {
                        return Err(IndexError::MutationRejected {
                            rejection: MutationRejection::PreconditionFailed {
                                key: key.clone(),
                                expected: MutationPrecondition::ExpectedRevision(selected_revision),
                            },
                        });
                    }
                }
                let (previous_revision, status) = self.prospective_state_for(key, &delta);
                check_precondition(command.precondition, key, previous_revision, status)?;
                let revision = previous_revision
                    .checked_add(1)
                    .ok_or(IndexError::RevisionOverflow)?;
                let location = match &command.action {
                    MutationAction::Insert(document) => {
                        if status == Some(KeyStatus::Live) {
                            return Err(IndexError::DuplicateDocument {
                                key: key.as_str().to_owned(),
                            });
                        }
                        let location = self.stage_pending(document, &mut delta, old_pending_len)?;
                        delta
                            .prospective_documents
                            .insert(key.clone(), document.clone());
                        Some(location)
                    }
                    MutationAction::Upsert(document) => {
                        let location = self.stage_pending(document, &mut delta, old_pending_len)?;
                        delta
                            .prospective_documents
                            .insert(key.clone(), document.clone());
                        Some(location)
                    }
                    MutationAction::Replace(document) => {
                        if status != Some(KeyStatus::Live) {
                            return Err(IndexError::MutationRejected {
                                rejection: MutationRejection::action_not_applicable(
                                    key.clone(),
                                    command.action.clone(),
                                ),
                            });
                        }
                        let location = self.stage_pending(document, &mut delta, old_pending_len)?;
                        delta
                            .prospective_documents
                            .insert(key.clone(), document.clone());
                        Some(location)
                    }
                    MutationAction::Update(patch) => {
                        if status != Some(KeyStatus::Live) {
                            return Err(IndexError::MutationRejected {
                                rejection: MutationRejection::action_not_applicable(
                                    key.clone(),
                                    command.action.clone(),
                                ),
                            });
                        }
                        let source = self.resolve_live_document(
                            key,
                            &command.action,
                            &delta,
                            &mut source_meter,
                        )?;
                        let patched = apply_document_patch(
                            &source,
                            patch,
                            &self.schema,
                            self.limits.budgets(),
                        )?;
                        let location = self.stage_pending(&patched, &mut delta, old_pending_len)?;
                        delta.prospective_documents.insert(key.clone(), patched);
                        Some(location)
                    }
                    MutationAction::Delete => {
                        delta.prospective_documents.remove(key);
                        None
                    }
                };
                let next_status = if location.is_some() {
                    KeyStatus::Live
                } else {
                    KeyStatus::Deleted
                };
                delta
                    .admitted_overrides
                    .insert(key.clone(), (revision, next_status));
                delta.appended_journal.push(AcceptedOp {
                    key: key.clone(),
                    revision,
                    location,
                });
                key_outcomes.push(MutationKeyOutcome {
                    key: key.clone(),
                    intent,
                    revision: Some(revision),
                    replayed: false,
                });
            }
            key_outcomes.sort_by(|left, right| left.key.cmp(&right.key));
            let matched = key_outcomes.len() as u64;
            delta.response.outcomes.push(MutationCommandOutcome {
                command_index: u32::try_from(index).map_err(|_| IndexError::ResourceLimit {
                    limit: self.limits.max_batch_commands(),
                    requested: index as u64,
                })?,
                matched,
                keys: key_outcomes,
            });
        }

        // ---------------- Phase C: aggregate resource preflight ----------------
        let total_pending = (self.pending.len() as u64)
            .checked_add(delta.appended_pending.len() as u64)
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_pending_docs(),
                requested: u64::MAX,
            })?;
        if total_pending > self.limits.max_pending_docs() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_pending_docs(),
                requested: total_pending,
            });
        }
        let total_pending_bytes = self
            .pending_bytes
            .checked_add(delta.pending_bytes_delta)
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_pending_bytes(),
                requested: u64::MAX,
            })?;
        if total_pending_bytes > self.limits.max_pending_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_pending_bytes(),
                requested: total_pending_bytes,
            });
        }
        let response_bytes = delta
            .response
            .encoded_len()
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_batch_response_bytes(),
                requested: u64::MAX,
            })?;
        if response_bytes > self.limits.max_batch_response_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_batch_response_bytes(),
                requested: response_bytes,
            });
        }
        let persisted_key_outcomes = delta.response.key_outcome_count() as u64;
        if persisted_key_outcomes > self.limits.max_batch_replay_keys() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_batch_replay_keys(),
                requested: persisted_key_outcomes,
            });
        }

        // Prospective durable replay state, including the new batch record.
        let mut batch_replay = self.batch_replay_combined();
        if let Some(token) = &batch.idempotency_key {
            let row = BatchReplayRow {
                token: token.clone(),
                fingerprint,
                response: delta.response.clone(),
            };
            batch_replay.insert(token.clone(), row.clone());
            delta.batch_replay_entry = Some(row);
        }
        let total_replay_entries = self
            .replay_combined()
            .len()
            .checked_add(batch_replay.len())
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: u64::MAX,
            })?;
        if total_replay_entries as u64 > self.limits.max_replay_entries() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: total_replay_entries as u64,
            });
        }
        let prospective_state = MutationStateV1::from_parts(
            self.rows_from_ops(
                Some(PENDING_SEGMENT_ID_PLACEHOLDER),
                self.journal.iter().chain(delta.appended_journal.iter()),
            )?,
            self.replay_combined(),
        )
        .with_batch_replay(batch_replay);
        if prospective_state.replay_bytes_total() > self.limits.max_replay_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_bytes(),
                requested: prospective_state.replay_bytes_total(),
            });
        }
        let version_2 = self.version_2_active() || prospective_state.has_batch_replay();
        let encoded = prospective_state.encode_with_mode(version_2)?;
        let encoded_len = encoded.len() as u64;
        if encoded_len > self.limits.max_mutation_state_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_mutation_state_bytes(),
                requested: encoded_len,
            });
        }

        Ok(PlannedBatch::Admit(Box::new(delta)))
    }

    /// Resolve a key's candidate state through delta override, writer admission
    /// and finally the committed key row.
    fn prospective_state_for(
        &self,
        key: &DocumentKey,
        delta: &BatchDelta,
    ) -> (u64, Option<KeyStatus>) {
        if let Some((revision, status)) = delta.admitted_overrides.get(key) {
            return (*revision, Some(*status));
        }
        self.candidate_state_for(key)
    }

    /// Resolve the complete live source document for one update.
    ///
    /// Precedence is: the batch's planning-only document map, earlier accepted
    /// writer operations (latest matching operation wins, including pending and
    /// flushed locations), then the committed mutation-state winner. The refresh
    /// snapshot is deliberately never used because it can lag the journal.
    fn resolve_live_document(
        &self,
        key: &DocumentKey,
        action: &MutationAction,
        delta: &BatchDelta,
        meter: &mut SourceMeter,
    ) -> IndexResult<Document> {
        if let Some(document) = delta.prospective_documents.get(key) {
            return Ok(document.clone());
        }
        if let Some((_revision, status)) = delta.admitted_overrides.get(key) {
            if *status != KeyStatus::Live {
                return Err(self.action_not_applicable(key, action));
            }
            // A live in-batch operation must always have staged its complete
            // document. Falling through to older state here would silently lose
            // the earlier command in this batch.
            return Err(self.reconstruction_unavailable(
                key,
                None,
                ReconstructionFailure::MissingSource,
            ));
        }
        for op in self.journal.iter().rev() {
            if &op.key != key {
                continue;
            }
            return match op.location {
                None => Err(self.action_not_applicable(key, action)),
                Some(MutationLocation::Pending(index)) => {
                    let source = self.pending.get(index).ok_or_else(|| {
                        IndexError::CorruptCommittedState {
                            detail: "pending mutation points to an absent document".to_owned(),
                        }
                    })?;
                    reconstruct_from_document(source, &self.schema, key, self.limits.budgets())
                }
                Some(MutationLocation::Flushed { segment, doc_id }) => {
                    self.reconstruct_flushed(segment, doc_id, key, meter)
                }
            };
        }
        let row = self
            .committed
            .as_ref()
            .and_then(|state| state.state.row(key))
            .ok_or_else(|| self.action_not_applicable(key, action))?;
        if !row.is_live() {
            return Err(self.action_not_applicable(key, action));
        }
        let segment_id =
            row.segment_id
                .as_deref()
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "live mutation row has no segment id".to_owned(),
                })?;
        let doc_id = row
            .doc_id
            .ok_or_else(|| IndexError::CorruptCommittedState {
                detail: "live mutation row has no physical doc id".to_owned(),
            })?;
        self.reconstruct_committed(segment_id, doc_id, key, meter)
    }

    fn reconstruct_flushed(
        &self,
        segment_index: usize,
        doc_id: u64,
        key: &DocumentKey,
        meter: &mut SourceMeter,
    ) -> IndexResult<Document> {
        let built =
            self.flushed
                .get(segment_index)
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "flushed mutation points to an absent segment".to_owned(),
                })?;
        let segment_id = built.meta.segment_id();
        meter.charge(segment_id, built.bytes.len() as u64)?;
        let reader = built
            .snapshot()
            .open_reader(*self.limits.segment_limits())?;
        reconstruct_from_segment(&reader, &self.schema, doc_id, key, self.limits.budgets())
    }

    fn reconstruct_committed(
        &self,
        segment_id: &str,
        doc_id: u64,
        key: &DocumentKey,
        meter: &mut SourceMeter,
    ) -> IndexResult<Document> {
        let committed =
            self.committed
                .as_ref()
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "mutation-state winner exists without committed state".to_owned(),
                })?;
        let mut matching = committed
            .segments
            .iter()
            .filter(|segment| segment.meta().segment_id() == segment_id);
        let segment = matching
            .next()
            .ok_or_else(|| IndexError::CorruptCommittedState {
                detail: "mutation-state winner points to an absent segment".to_owned(),
            })?;
        if matching.next().is_some() {
            return Err(IndexError::CorruptCommittedState {
                detail: "mutation-state winner segment id is ambiguous".to_owned(),
            });
        }
        meter.charge(segment_id, segment.bytes().len() as u64)?;
        let reader = segment.open_reader(*self.limits.segment_limits())?;
        reconstruct_from_segment(&reader, &self.schema, doc_id, key, self.limits.budgets())
    }

    fn action_not_applicable(&self, key: &DocumentKey, action: &MutationAction) -> IndexError {
        IndexError::MutationRejected {
            rejection: MutationRejection::action_not_applicable(key.clone(), action.clone()),
        }
    }

    fn reconstruction_unavailable(
        &self,
        key: &DocumentKey,
        field: Option<String>,
        reason: ReconstructionFailure,
    ) -> IndexError {
        IndexError::MutationRejected {
            rejection: MutationRejection::reconstruction_unavailable(key.clone(), field, reason),
        }
    }

    /// Stage one document into the prospective pending batch.
    ///
    /// The staged pending index is absolute: `old_pending_len + staged_offset`.
    fn stage_pending(
        &self,
        document: &Document,
        delta: &mut BatchDelta,
        old_pending_len: usize,
    ) -> IndexResult<MutationLocation> {
        let size =
            u64::try_from(document.approx_size()).map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_pending_bytes(),
                requested: u64::MAX,
            })?;
        delta.pending_bytes_delta =
            delta
                .pending_bytes_delta
                .checked_add(size)
                .ok_or(IndexError::ResourceLimit {
                    limit: self.limits.max_pending_bytes(),
                    requested: u64::MAX,
                })?;
        let pending_index = old_pending_len
            .checked_add(delta.appended_pending.len())
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_pending_docs(),
                requested: u64::MAX,
            })?;
        delta.appended_pending.push(to_segment_document(document));
        Ok(MutationLocation::Pending(pending_index))
    }

    /// Phase D: a single non-fallible installation of a fully prepared delta.
    ///
    /// Everything fallible - including the replacement maps and the exact vector
    /// reservations - happens before this function's first mutation. No `?`,
    /// cancellation poll, I/O, validation or allocation follows it.
    fn install_batch(&mut self, mut delta: BatchDelta) -> IndexResult<MutationBatchResponse> {
        // Replacement maps are built over checked bounded sizes.
        let mut new_admitted = self.admitted.clone();
        for (key, value) in &delta.admitted_overrides {
            new_admitted.insert(key.clone(), *value);
        }
        let mut new_batch_replay = self.batch_replay.clone();
        if let Some(row) = delta.batch_replay_entry.take() {
            new_batch_replay.insert(row.token.clone(), row);
        }
        self.pending
            .try_reserve(delta.appended_pending.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_pending_docs(),
                requested: self.pending.len() as u64 + delta.appended_pending.len() as u64,
            })?;
        self.journal
            .try_reserve(delta.appended_journal.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: self.limits.max_batch_keys(),
                requested: self.journal.len() as u64 + delta.appended_journal.len() as u64,
            })?;

        // ---- installation boundary: no fallible work from here on ----
        self.pending.append(&mut delta.appended_pending);
        self.journal.append(&mut delta.appended_journal);
        self.pending_bytes += delta.pending_bytes_delta;
        let _ = std::mem::replace(&mut self.admitted, new_admitted);
        let _ = std::mem::replace(&mut self.batch_replay, new_batch_replay);
        #[cfg(test)]
        {
            self.install_transitions += 1;
        }
        // ---- end of installation boundary ----

        Ok(delta.response)
    }

    /// Build the pending batch into one immutable segment without publishing it.
    pub fn flush(&mut self) -> IndexResult<FlushOutcome> {
        self.ensure_writable()?;
        if self.pending.is_empty() {
            return Ok(FlushOutcome {
                segments_flushed: 0,
                documents: 0,
            });
        }
        let requested = self.flushed.len() as u64 + 1;
        if requested > self.limits.max_segments_per_commit() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_segments_per_commit(),
                requested,
            });
        }
        let documents = self.pending.len() as u64;
        let segment = self.build_pending_segment()?;
        let segment_index = self.flushed.len();
        for op in &mut self.journal {
            if let Some(MutationLocation::Pending(pending_doc)) = op.location {
                op.location = Some(MutationLocation::Flushed {
                    segment: segment_index,
                    doc_id: pending_doc as u64,
                });
            }
        }
        self.flushed.push(segment);
        self.pending.clear();
        self.pending_bytes = 0;
        Ok(FlushOutcome {
            segments_flushed: 1,
            documents,
        })
    }

    /// Publish a new volatile immutable reader view.
    ///
    /// The view contains the last committed segments plus every accepted
    /// uncommitted mutation, with generation-specific live masks. It never
    /// writes `CURRENT` and never makes data durable. A failure leaves the
    /// previously published view unchanged.
    pub fn refresh(&mut self) -> IndexResult<Arc<ReaderSnapshot>> {
        self.ensure_writable()?;
        let pending_built = self.build_optional_pending()?;
        let pending_id = pending_built
            .as_ref()
            .map(|segment| segment.meta.segment_id().to_owned());
        let state = self.candidate_state(pending_id.as_deref())?;
        let mut segments: Vec<SegmentSnapshot> = self.committed_segments();
        for segment in &self.flushed {
            segments.push(segment.snapshot());
        }
        if let Some(segment) = &pending_built {
            segments.push(segment.snapshot());
        }
        let masks = visibility::build_masks(&state, &segments, *self.limits.segment_limits())?;
        let snapshot = Arc::new(ReaderSnapshot::new_with_masks(
            self.committed.as_ref().map(|state| state.generation),
            self.next_view,
            segments,
            masks,
            *self.limits.segment_limits(),
            Arc::clone(&self.pins),
            self.limits.max_snapshot_bytes(),
        )?);
        if snapshot.resident_bytes() > self.limits.max_snapshot_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_snapshot_bytes(),
                requested: snapshot.resident_bytes(),
            });
        }
        self.next_view = self.next_view.saturating_add(1);
        self.published = Some(Arc::clone(&snapshot));
        Ok(snapshot)
    }

    /// The latest published refresh view, falling back to committed state.
    #[must_use]
    pub fn reader(&self) -> Arc<ReaderSnapshot> {
        if let Some(published) = &self.published {
            return Arc::clone(published);
        }
        self.committed_snapshot()
    }

    /// Pin the latest reader view as a point-in-time handle.
    pub fn pin(&self) -> IndexResult<PitHandle> {
        pit::pin(&self.reader())
    }

    /// Durably commit all accepted mutations.
    ///
    /// Ordering: segments, then the immutable mutation-state sidecar (verified
    /// by SHA-256 and exact length), then the manifest that references it, then
    /// `CURRENT` last. Acknowledgment happens only after every barrier succeeds.
    pub fn commit(&mut self) -> IndexResult<CommitOutcome> {
        self.ensure_writable()?;
        if self.journal.is_empty() && self.pending.is_empty() && self.flushed.is_empty() {
            if let Some(committed) = &self.committed {
                return Ok(CommitOutcome {
                    generation: committed.generation,
                    documents: 0,
                    segments_added: 0,
                    no_op: true,
                });
            }
        }

        let pending_built = self.build_optional_pending()?;
        let pending_id = pending_built
            .as_ref()
            .map(|segment| segment.meta.segment_id().to_owned());
        let mut new_segments: Vec<PendingSegment> = self.flushed.clone();
        if let Some(segment) = &pending_built {
            new_segments.push(segment.clone());
        }
        let segments_added = new_segments.len() as u64;
        if segments_added > self.limits.max_segments_per_commit() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_segments_per_commit(),
                requested: segments_added,
            });
        }
        // Pre-publication resource parity with reopen.
        let committed_lengths = self.committed.iter().flat_map(|state| {
            state
                .manifest
                .segments
                .iter()
                .map(|reference| reference.content_length)
        });
        let new_lengths = new_segments
            .iter()
            .map(|segment| segment.meta.descriptor().length);
        support::bounded_segment_total(
            committed_lengths.chain(new_lengths),
            self.limits.segment_limits().accepted_segment_bytes(),
            self.limits.max_snapshot_bytes(),
        )?;

        let rows = self.candidate_rows(pending_id.as_deref())?;
        let state = MutationStateV1::from_parts(rows, self.replay_combined())
            .with_batch_replay(self.batch_replay_combined());
        let version_2_active = self.version_2_active() || state.has_batch_replay();
        let state_bytes = state.encode_with_mode(version_2_active)?;
        if state_bytes.len() as u64 > self.limits.max_mutation_state_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_mutation_state_bytes(),
                requested: state_bytes.len() as u64,
            });
        }
        let total_replay_entries = state
            .replay_count()
            .checked_add(state.batch_replay_count())
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: u64::MAX,
            })?;
        if total_replay_entries as u64 > self.limits.max_replay_entries() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: total_replay_entries as u64,
            });
        }
        if state.replay_bytes_total() > self.limits.max_replay_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_bytes(),
                requested: state.replay_bytes_total(),
            });
        }
        let state_digest = ContentDigest::sha256_v1(&state_bytes);
        let state_ref = MutationStateRef {
            object_key: state_key_for_hex(&state_digest.to_hex()),
            content_length: state_bytes.len() as u64,
            content_digest: *state_digest.as_bytes(),
        };

        let doc_total: u64 = new_segments.iter().map(|segment| segment.doc_count).sum();
        let previous_generation = self
            .committed
            .as_ref()
            .map(|state| state.generation)
            .unwrap_or(0);
        let generation = previous_generation
            .checked_add(1)
            .ok_or(IndexError::GenerationOverflow)?;

        // Build and round-trip-validate the generation manifest.
        let mut refs: Vec<ManifestSegmentRef> = self
            .committed
            .as_ref()
            .map(|state| state.manifest.segments.clone())
            .unwrap_or_default();
        for segment in &new_segments {
            refs.push(segment.to_ref());
        }
        refs.sort_by(|left, right| left.segment_id.cmp(&right.segment_id));
        let mut required_features = self
            .committed
            .as_ref()
            .map(|state| state.manifest.required_features.clone())
            .unwrap_or_default();
        required_features.push((FEATURE_MUTATION_STATE, 1));
        if version_2_active {
            required_features.push((FEATURE_MUTATION_STATE_V2, 1));
        }
        required_features.sort_unstable();
        required_features.dedup();
        let manifest = Manifest {
            schema: support::expected_codec_schema(&self.schema, &self.registry)?,
            segments: refs,
            required_features,
            optional_features: self
                .committed
                .as_ref()
                .map(|state| state.manifest.optional_features.clone())
                .unwrap_or_default(),
            mutation_state: Some(state_ref.clone()),
        };
        let manifest_bytes = manifest.encode()?;
        if manifest_bytes.len() as u64 > self.limits.max_manifest_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_manifest_bytes(),
                requested: manifest_bytes.len() as u64,
            });
        }
        let _ = Manifest::decode(&manifest_bytes, self.limits.segment_limits())?;

        // Step 3: install immutable content-addressed segments.
        for segment in &new_segments {
            let key = StorageKey::parse(segment.meta.object_key())?;
            support::install_immutable(self.directory.as_ref(), &key, segment.bytes.as_slice())?;
        }
        // Step 4: install and verify the mutation-state sidecar.
        let state_key = StorageKey::parse(&state_ref.object_key)?;
        support::install_immutable(self.directory.as_ref(), &state_key, &state_bytes)?;
        // Step 5: install the manifest.
        let manifest_key = StorageKey::parse(manifest_key_for(generation))?;
        support::install_immutable(self.directory.as_ref(), &manifest_key, &manifest_bytes)?;

        // Step 6: publish CURRENT last, atomically.
        let pointer = CurrentPointer::new(
            generation,
            manifest_bytes.len() as u64,
            ContentDigest::sha256_v1(&manifest_bytes),
        )?;
        let current_key = StorageKey::parse(CURRENT_KEY)?;
        let current_bytes = pointer.encode()?;
        match self.directory.atomic_write(&current_key, &current_bytes) {
            Ok(()) => {
                self.finish_commit(
                    generation,
                    manifest,
                    new_segments,
                    state,
                    segments_added,
                    doc_total,
                )?;
                Ok(CommitOutcome {
                    generation,
                    documents: doc_total,
                    segments_added,
                    no_op: false,
                })
            }
            Err(error) => self.reconcile_current_failure(error, previous_generation, generation),
        }
    }

    fn finish_commit(
        &mut self,
        generation: u64,
        manifest: Manifest,
        new_segments: Vec<PendingSegment>,
        state: MutationStateV1,
        segments_added: u64,
        doc_total: u64,
    ) -> IndexResult<()> {
        let mut segments = self.committed_segments();
        segments.extend(new_segments.iter().map(PendingSegment::snapshot));
        let masks = visibility::build_masks(&state, &segments, *self.limits.segment_limits())?;
        let state = Arc::new(state);
        self.committed = Some(CommittedState {
            generation,
            manifest,
            segments,
            state,
            masks,
        });
        self.journal.clear();
        self.admitted.clear();
        self.replay.clear();
        self.batch_replay.clear();
        self.pending.clear();
        self.pending_bytes = 0;
        self.flushed.clear();
        self.poisoned = false;
        let snapshot = self.committed_snapshot();
        self.published = Some(snapshot);
        let _ = (segments_added, doc_total);
        Ok(())
    }

    /// Apply the shared `CURRENT` reconciliation contract and return the typed
    /// error. Pre-publication failures leave the writer retryable (old
    /// generation authoritative); an ambiguous replacement poisons it.
    pub(crate) fn reconcile_publication(
        &mut self,
        error: StorageError,
        previous_generation: u64,
        attempted_generation: u64,
    ) -> IndexError {
        match self.reconcile_current_failure(error, previous_generation, attempted_generation) {
            Ok(_) => unreachable!("reconciliation always returns an error"),
            Err(error) => error,
        }
    }

    fn reconcile_current_failure(
        &mut self,
        error: StorageError,
        previous_generation: u64,
        attempted_generation: u64,
    ) -> IndexResult<CommitOutcome> {
        match support::read_current(self.directory.as_ref()) {
            // Pre-CURRENT failure: the old state is authoritative.
            Ok(None) if previous_generation == 0 => Err(IndexError::Storage(error)),
            Ok(Some(pointer)) if pointer.generation() == previous_generation => {
                Err(IndexError::Storage(error))
            }
            // The new pointer is visible but durability was not acknowledged.
            Ok(Some(pointer)) if pointer.generation() == attempted_generation => {
                self.poisoned = true;
                Err(IndexError::RecoveryRequired {
                    detail: "CURRENT was replaced but durability was not acknowledged".to_owned(),
                })
            }
            _ => {
                self.poisoned = true;
                Err(IndexError::RecoveryRequired {
                    detail: "CURRENT state is indeterminate after a failed commit".to_owned(),
                })
            }
        }
    }

    fn ensure_writable(&self) -> IndexResult<()> {
        if self.poisoned {
            return Err(IndexError::RecoveryRequired {
                detail: "writer is poisoned after an indeterminate commit; reopen the index"
                    .to_owned(),
            });
        }
        Ok(())
    }

    /// The current candidate revision and status for a key (committed + accepted).
    fn candidate_state_for(&self, key: &DocumentKey) -> (u64, Option<KeyStatus>) {
        if let Some((revision, status)) = self.admitted.get(key) {
            return (*revision, Some(*status));
        }
        match self
            .committed
            .as_ref()
            .and_then(|state| state.state.row(key))
        {
            Some(row) => (row.revision, Some(row.status)),
            None => (0, None),
        }
    }

    /// Look up a replay entry in the uncommitted or committed ledger.
    fn lookup_replay(&self, token: &IdempotencyKey) -> Option<ReplayRow> {
        if let Some(row) = self.replay.get(token) {
            return Some(row.clone());
        }
        self.committed
            .as_ref()
            .and_then(|state| state.state.replay_entry(token))
            .cloned()
    }

    fn check_replay_capacity(&self) -> IndexResult<()> {
        let base = self
            .committed
            .as_ref()
            .map(|state| state.state.replay_count())
            .unwrap_or(0) as u64;
        let requested = base
            .checked_add(self.replay.len() as u64)
            .and_then(|value| value.checked_add(1))
            .ok_or(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: u64::MAX,
            })?;
        if requested > self.limits.max_replay_entries() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested,
            });
        }
        Ok(())
    }

    fn committed_segments(&self) -> Vec<SegmentSnapshot> {
        self.committed
            .as_ref()
            .map(|state| state.segments.clone())
            .unwrap_or_default()
    }

    fn replay_combined(&self) -> BTreeMap<IdempotencyKey, ReplayRow> {
        let mut replay: BTreeMap<IdempotencyKey, ReplayRow> = self
            .committed
            .as_ref()
            .map(|state| {
                state
                    .state
                    .replay_rows()
                    .iter()
                    .map(|row| (row.token.clone(), row.clone()))
                    .collect()
            })
            .unwrap_or_default();
        for (token, row) in &self.replay {
            replay.insert(token.clone(), row.clone());
        }
        replay
    }

    /// Look up a durable or uncommitted atomic-batch replay record.
    fn lookup_batch_replay(&self, token: &IdempotencyKey) -> Option<BatchReplayRow> {
        if let Some(row) = self.batch_replay.get(token) {
            return Some(row.clone());
        }
        self.committed
            .as_ref()
            .and_then(|state| state.state.batch_replay_entry(token))
            .cloned()
    }

    /// Whether the committed generation already requires the v2 payload.
    fn version_2_active(&self) -> bool {
        self.committed.as_ref().is_some_and(|state| {
            state
                .manifest
                .required_features
                .contains(&(FEATURE_MUTATION_STATE_V2, 1))
        })
    }

    /// Merge committed and uncommitted batch replay records by token.
    fn batch_replay_combined(&self) -> BTreeMap<IdempotencyKey, BatchReplayRow> {
        let mut replay: BTreeMap<IdempotencyKey, BatchReplayRow> = self
            .committed
            .as_ref()
            .map(|state| {
                state
                    .state
                    .batch_replay_rows()
                    .iter()
                    .map(|row| (row.token.clone(), row.clone()))
                    .collect()
            })
            .unwrap_or_default();
        for (token, row) in &self.batch_replay {
            replay.insert(token.clone(), row.clone());
        }
        replay
    }

    /// Resolve the winning row for every committed key plus every accepted op.
    fn candidate_rows(
        &self,
        pending_segment_id: Option<&str>,
    ) -> IndexResult<BTreeMap<DocumentKey, KeyRow>> {
        self.rows_from_ops(pending_segment_id, self.journal.iter())
    }

    /// Resolve winning rows from committed state plus an ordered op stream.
    fn rows_from_ops<'a>(
        &self,
        pending_segment_id: Option<&str>,
        ops: impl Iterator<Item = &'a AcceptedOp>,
    ) -> IndexResult<BTreeMap<DocumentKey, KeyRow>> {
        let mut rows: BTreeMap<DocumentKey, KeyRow> = self
            .committed
            .as_ref()
            .map(|state| {
                state
                    .state
                    .rows()
                    .iter()
                    .map(|row| (row.key.clone(), row.clone()))
                    .collect()
            })
            .unwrap_or_default();
        for op in ops {
            let row = match op.location {
                None => KeyRow::deleted(op.key.clone(), op.revision),
                Some(MutationLocation::Pending(doc_id)) => {
                    let segment_id =
                        pending_segment_id.ok_or(IndexError::CorruptCommittedState {
                            detail: "pending mutation has no pending segment".to_owned(),
                        })?;
                    KeyRow::live(op.key.clone(), op.revision, segment_id, doc_id as u64)
                }
                Some(MutationLocation::Flushed { segment, doc_id }) => {
                    let segment_id = self
                        .flushed
                        .get(segment)
                        .map(|built| built.meta.segment_id().to_owned())
                        .ok_or(IndexError::CorruptCommittedState {
                            detail: "flushed mutation points to an absent segment".to_owned(),
                        })?;
                    KeyRow::live(op.key.clone(), op.revision, segment_id, doc_id)
                }
            };
            rows.insert(op.key.clone(), row);
        }
        Ok(rows)
    }

    fn candidate_state(&self, pending_segment_id: Option<&str>) -> IndexResult<MutationStateV1> {
        Ok(MutationStateV1::from_parts(
            self.candidate_rows(pending_segment_id)?,
            self.replay_combined(),
        )
        .with_batch_replay(self.batch_replay_combined()))
    }

    fn build_optional_pending(&self) -> IndexResult<Option<PendingSegment>> {
        if self.pending.is_empty() {
            Ok(None)
        } else {
            Ok(Some(self.build_pending_segment()?))
        }
    }

    fn build_pending_segment(&self) -> IndexResult<PendingSegment> {
        let built = support::build_segment(&self.schema, &self.registry, &self.pending)?;
        let bytes = Arc::new(built.bytes);
        let (meta, doc_count) = support::meta_from_bytes(self.limits.segment_limits(), &bytes)?;
        Ok(PendingSegment {
            meta,
            bytes,
            doc_count,
        })
    }

    fn committed_snapshot(&self) -> Arc<ReaderSnapshot> {
        let segments = self.committed_segments();
        let masks = self
            .committed
            .as_ref()
            .map(|state| state.masks.clone())
            .unwrap_or_else(|| vec![None; segments.len()]);
        let generation = self.committed.as_ref().map(|state| state.generation);
        Arc::new(
            ReaderSnapshot::new_with_masks(
                generation,
                self.next_view,
                segments,
                masks,
                *self.limits.segment_limits(),
                Arc::clone(&self.pins),
                self.limits.max_snapshot_bytes(),
            )
            .expect("committed masks are validated"),
        )
    }

    /// The committed generation's manifest, if any.
    #[must_use]
    pub(crate) fn committed_manifest(&self) -> Option<&Manifest> {
        self.committed.as_ref().map(|state| &state.manifest)
    }

    /// The committed segment snapshots in manifest order.
    #[must_use]
    pub(crate) fn committed_segment_snapshots(&self) -> Vec<SegmentSnapshot> {
        self.committed_segments()
    }

    /// The committed logical state, if any.
    #[must_use]
    pub(crate) fn committed_state_arc(&self) -> Option<Arc<MutationStateV1>> {
        self.committed
            .as_ref()
            .map(|state| Arc::clone(&state.state))
    }

    /// The shared directory.
    #[must_use]
    pub(crate) fn directory(&self) -> &Arc<dyn Directory> {
        &self.directory
    }

    /// The configured limits.
    #[must_use]
    pub(crate) fn limits_ref(&self) -> &IndexLimits {
        &self.limits
    }

    /// Fail closed when compaction is requested with outstanding mutations.
    pub(crate) fn ensure_compactable(&self) -> IndexResult<()> {
        if !self.journal.is_empty() {
            return Err(IndexError::PendingMutations {
                pending: self.journal.len() as u64,
            });
        }
        Ok(())
    }

    /// Number of uncommitted replay entries (test-only introspection).
    #[cfg(test)]
    #[must_use]
    pub(crate) fn replay_entry_count(&self) -> usize {
        self.replay.len()
    }

    /// A complete, comparable snapshot of every mutable writer field.
    ///
    /// Used by rollback tests to prove that a rejected batch left the writer in
    /// exactly the pre-call state - not merely that one counter is unchanged.
    #[cfg(test)]
    #[must_use]
    fn state_snapshot(&self) -> WriterStateSnapshot {
        WriterStateSnapshot {
            generation: self.generation(),
            journal: self
                .journal
                .iter()
                .map(|op| (op.key.clone(), op.revision, op.location))
                .collect(),
            admitted: self.admitted.clone(),
            replay: self.replay.clone(),
            batch_replay_len: self.batch_replay.len(),
            pending_len: self.pending.len(),
            pending_bytes: self.pending_bytes,
            flushed_len: self.flushed.len(),
            published_view: self
                .published
                .as_ref()
                .map(|snapshot| snapshot.view_ordinal()),
            next_view: self.next_view,
            poisoned: self.poisoned,
            install_transitions: self.install_transitions,
        }
    }

    /// Number of accepted operations whose winning pointer is still unflushed.
    #[cfg(test)]
    #[must_use]
    pub(crate) fn admitted_entry_count(&self) -> usize {
        self.admitted.len()
    }

    /// Explicit compaction entry point that never observes a cancellation
    /// request.
    pub fn compact(&mut self) -> IndexResult<super::merge::MergeOutcome> {
        static NEVER_CANCEL: AtomicBool = AtomicBool::new(false);
        self.compact_with_cancel(&NEVER_CANCEL)
    }

    /// Explicit compaction entry point with a caller-supplied cooperative
    /// cancellation flag (`true` = cancel requested).
    ///
    /// Cancellation is checked at bounded intervals while compaction decodes,
    /// remaps and encodes. A cancellation request observed before the final
    /// pre-publication checkpoint aborts with [`IndexError::Cancelled`] and
    /// leaves the committed generation, revisions, replay ledger and published
    /// views unchanged. Once `CURRENT` publication has been attempted the
    /// ordinary publication reconciliation decides the outcome; a later flag
    /// change never turns a published generation into a false `Cancelled`.
    pub fn compact_with_cancel(
        &mut self,
        cancelled: &AtomicBool,
    ) -> IndexResult<super::merge::MergeOutcome> {
        self.ensure_writable()?;
        super::merge::compact(self, cancelled)
    }

    /// Admit a bounded, explicitly selected set of logical keys as normal
    /// revisioned deletes.
    ///
    /// This is the only retention hook in PR 9: it reads no clock, runs no
    /// background task and infers nothing from ingest time or file age. The
    /// caller selects keys externally (for example with a timestamp predicate
    /// owned by PR 10) and supplies a nonempty operational reason. Duplicate
    /// keys are normalized deterministically by first occurrence. The whole
    /// batch is validated before any admission.
    pub fn delete_keys_for_retention(
        &mut self,
        keys: &[DocumentKey],
        reason: &str,
    ) -> IndexResult<RetentionOutcome> {
        self.ensure_writable()?;
        if reason.trim().is_empty() {
            return Err(IndexError::InvalidRetention {
                detail: "a nonempty policy reason is required".to_owned(),
            });
        }
        let mut seen: BTreeSet<&DocumentKey> = BTreeSet::new();
        let mut unique: Vec<DocumentKey> = Vec::new();
        for key in keys {
            if seen.insert(key) {
                unique.push(key.clone());
            }
        }
        if unique.len() as u64 > self.limits.max_pending_docs() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_pending_docs(),
                requested: unique.len() as u64,
            });
        }
        // Preflight revision overflow for the entire batch before any admission.
        for key in &unique {
            let (revision, _) = self.candidate_state_for(key);
            if revision == u64::MAX {
                return Err(IndexError::RevisionOverflow);
            }
        }
        for key in &unique {
            let _ = self.apply(MutationRequest::delete(key.clone()))?;
        }
        Ok(RetentionOutcome {
            reason: reason.to_owned(),
            deleted: unique,
        })
    }

    /// Replace the in-memory committed state after a successful compaction.
    pub(crate) fn install_compacted(
        &mut self,
        generation: u64,
        manifest: Manifest,
        segments: Vec<SegmentSnapshot>,
        state: Arc<MutationStateV1>,
    ) -> IndexResult<()> {
        let masks =
            visibility::build_masks(&state, segments.as_slice(), *self.limits.segment_limits())?;
        self.committed = Some(CommittedState {
            generation,
            manifest,
            segments,
            state,
            masks,
        });
        self.batch_replay.clear();
        self.poisoned = false;
        let snapshot = self.committed_snapshot();
        self.published = Some(snapshot);
        Ok(())
    }

    /// The next generation number.
    pub(crate) fn next_generation(&self) -> IndexResult<u64> {
        self.committed
            .as_ref()
            .map(|state| state.generation)
            .unwrap_or(0)
            .checked_add(1)
            .ok_or(IndexError::GenerationOverflow)
    }
}

impl std::fmt::Debug for IndexWriter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IndexWriter")
            .field("generation", &self.generation())
            .field("pending", &self.pending.len())
            .field("flushed", &self.flushed.len())
            .field("journal", &self.journal.len())
            .field("poisoned", &self.poisoned)
            .finish()
    }
}

/// A complete snapshot of every mutable writer field (test-only).
#[cfg(test)]
#[derive(Debug, Clone, PartialEq)]
struct WriterStateSnapshot {
    generation: Option<u64>,
    journal: Vec<(DocumentKey, u64, Option<MutationLocation>)>,
    admitted: BTreeMap<DocumentKey, (u64, KeyStatus)>,
    replay: BTreeMap<IdempotencyKey, ReplayRow>,
    batch_replay_len: usize,
    pending_len: usize,
    pending_bytes: u64,
    flushed_len: usize,
    published_view: Option<u64>,
    next_view: u64,
    poisoned: bool,
    install_transitions: usize,
}

/// The typed unsupported target/action rejection for one command.
fn unsupported_target_action_error(command: &MutationCommand) -> IndexError {
    IndexError::MutationRejected {
        rejection: MutationRejection::unsupported_target_action(
            command.target.clone(),
            command.action.clone(),
        ),
    }
}

/// The typed invalid-batch rejection for an empty explicit key list.
fn empty_key_list_error() -> IndexError {
    IndexError::MutationRejected {
        rejection: MutationRejection::InvalidBatch {
            detail: "an explicit key list must not be empty".to_owned(),
        },
    }
}

/// Admission-work preflight over the caller's **raw** explicit-key occurrences.
///
/// This is a bounded, allocation-free scan of target shapes only. It never
/// clones a key, builds a set, or deduplicates, so a request containing a very
/// large list of repeated keys is rejected from the cheap `Vec::len()` values
/// instead of forcing work proportional to the input length.
///
/// Counts `MutationTarget::Key` as one occurrence and `MutationTarget::Keys` as
/// its raw length, including duplicates, accumulated across the whole batch with
/// checked arithmetic. `MutationTarget::Query` is never expanded: M1 rejects it
/// with the existing typed unsupported-target error, which is also checked here
/// so that error precedence for shapes needing no expansion is unchanged.
///
/// Returns the checked raw occurrence total on success.
fn batch_raw_key_preflight(
    batch: &MutationBatch,
    cancel: &dyn Cancellation,
    limit: u64,
) -> IndexResult<u64> {
    let mut raw_key_occurrences: u64 = 0;
    for command in &batch.commands {
        if cancel.is_cancelled() {
            return Err(IndexError::Cancelled);
        }
        // M3 activates exactly Query + Delete. A query target contributes zero
        // raw explicit-key occurrences; its own match bound is enforced against
        // the committed snapshot after replay lookup. Every other query action
        // remains the existing typed unsupported rejection, and a zero selector
        // bound is an invalid selector rather than a silent default.
        if let MutationTarget::Query(selector) = &command.target {
            if !matches!(command.action, MutationAction::Delete) {
                return Err(unsupported_target_action_error(command));
            }
            if selector.max_matches == 0 {
                return Err(IndexError::MutationRejected {
                    rejection: MutationRejection::InvalidBatch {
                        detail: "a query selector max_matches must be greater than zero".to_owned(),
                    },
                });
            }
            continue;
        }
        let count = match &command.target {
            MutationTarget::Key(_) => 1,
            MutationTarget::Keys(keys) => {
                if keys.is_empty() {
                    return Err(empty_key_list_error());
                }
                u64::try_from(keys.len()).map_err(|_| IndexError::ResourceLimit {
                    limit,
                    requested: u64::MAX,
                })?
            }
            // Handled above; defensive zero so this helper stays panic-free.
            MutationTarget::Query(_) => 0,
        };
        raw_key_occurrences =
            raw_key_occurrences
                .checked_add(count)
                .ok_or(IndexError::ResourceLimit {
                    limit,
                    requested: u64::MAX,
                })?;
        if raw_key_occurrences > limit {
            return Err(IndexError::ResourceLimit {
                limit,
                requested: raw_key_occurrences,
            });
        }
    }
    Ok(raw_key_occurrences)
}

/// Resolve an explicit command target into first-occurrence-unique keys.
///
/// Enforces the explicit target/action matrix. Query targets are rejected here
/// defensively; [`IndexWriter::plan_batch`] routes valid `Query + Delete`
/// commands through committed-snapshot selection instead of calling this
/// helper. `Update` is accepted only when the target resolves to exactly one
/// unique explicit key. Callers must run [`batch_raw_key_preflight`] first so
/// the input length is already bounded.
fn resolve_batch_target(command: &MutationCommand) -> IndexResult<Vec<DocumentKey>> {
    let unsupported = || unsupported_target_action_error(command);
    if matches!(command.target, MutationTarget::Query(_)) {
        return Err(unsupported());
    }
    match &command.target {
        MutationTarget::Key(key) => Ok(vec![key.clone()]),
        MutationTarget::Keys(keys) => {
            if keys.is_empty() {
                return Err(empty_key_list_error());
            }
            let mut unique: Vec<DocumentKey> = Vec::new();
            unique
                .try_reserve(keys.len())
                .map_err(|_| IndexError::ResourceLimit {
                    limit: keys.len() as u64,
                    requested: keys.len() as u64,
                })?;
            let mut seen: BTreeSet<&DocumentKey> = BTreeSet::new();
            for key in keys {
                if seen.insert(key) {
                    unique.push(key.clone());
                }
            }
            // More than one unique key is only valid for a delete.
            if unique.len() > 1 && !matches!(command.action, MutationAction::Delete) {
                return Err(unsupported());
            }
            Ok(unique)
        }
        MutationTarget::Query(_) => Err(unsupported()),
    }
}

/// The document carried by an action, if any.
fn action_document(action: &MutationAction) -> Option<&Document> {
    match action {
        MutationAction::Insert(document)
        | MutationAction::Upsert(document)
        | MutationAction::Replace(document) => Some(document),
        MutationAction::Update(_) | MutationAction::Delete => None,
    }
}

/// The revisioned intent an action maps onto.
fn action_intent(action: &MutationAction) -> MutationIntent {
    match action {
        MutationAction::Insert(_) => MutationIntent::Insert,
        MutationAction::Upsert(_) | MutationAction::Update(_) | MutationAction::Replace(_) => {
            MutationIntent::Upsert
        }
        MutationAction::Delete => MutationIntent::Delete,
    }
}

/// Evaluate a precondition against the prospective key state.
fn check_precondition(
    precondition: MutationPrecondition,
    key: &DocumentKey,
    revision: u64,
    status: Option<KeyStatus>,
) -> IndexResult<()> {
    let live = status == Some(KeyStatus::Live);
    let satisfied = match precondition {
        MutationPrecondition::None => true,
        MutationPrecondition::MustExist => live,
        MutationPrecondition::MustNotExist => !live,
        MutationPrecondition::ExpectedRevision(expected) => {
            status.is_some() && revision == expected
        }
    };
    if satisfied {
        Ok(())
    } else {
        Err(IndexError::MutationRejected {
            rejection: MutationRejection::PreconditionFailed {
                key: key.clone(),
                expected: precondition,
            },
        })
    }
}

/// Convert a validated contract document to a builder input document.
fn to_segment_document(document: &Document) -> SegmentDocument {
    let mut segment = SegmentDocument::new(document.key().clone());
    for (name, values) in document.fields() {
        segment.fields.insert(name.to_owned(), values.clone());
    }
    segment
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;
    use crate::storage::{MemoryDirectory, ReadHandle, StorageOp, WriteHandle};

    /// Real `MemoryDirectory` wrapper that fails the first `remaining` deletes.
    struct FlakyDeleteDirectory {
        inner: MemoryDirectory,
        remaining_failures: AtomicUsize,
        deletes: AtomicUsize,
    }

    impl FlakyDeleteDirectory {
        fn new(remaining_failures: usize) -> Self {
            Self {
                inner: MemoryDirectory::new(),
                remaining_failures: AtomicUsize::new(remaining_failures),
                deletes: AtomicUsize::new(0),
            }
        }

        fn deletes(&self) -> usize {
            self.deletes.load(Ordering::SeqCst)
        }
    }

    impl Directory for FlakyDeleteDirectory {
        fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
            self.inner.create_dir_all(prefix)
        }

        fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError> {
            self.inner.create(key)
        }

        fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError> {
            self.inner.open_read(key)
        }

        fn exists(&self, key: &StorageKey) -> Result<bool, StorageError> {
            self.inner.exists(key)
        }

        // MSRV compatibility: retain fetch_update until the minimum supported Rust version supports its replacement.
        #[allow(deprecated)]
        fn delete(&self, key: &StorageKey) -> Result<(), StorageError> {
            self.deletes.fetch_add(1, Ordering::SeqCst);
            if self
                .remaining_failures
                .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |remaining| {
                    remaining.checked_sub(1)
                })
                .is_ok()
            {
                return Err(StorageError::io(
                    StorageOp::Delete,
                    std::io::Error::other("injected delete failure"),
                ));
            }
            self.inner.delete(key)
        }

        fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
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

    // T09: a failed delete leaves the guard unreleased; a second release retries.
    #[test]
    fn t09_failed_delete_keeps_guard_unreleased_and_retry_succeeds() {
        let flaky = Arc::new(FlakyDeleteDirectory::new(1));
        let directory: Arc<dyn Directory> = flaky.clone();
        let mut lock = WriterLock::acquire(&directory).expect("lock acquisition");
        let error = lock.release().expect_err("first delete must fail");
        assert!(matches!(error, IndexError::Storage(_)));
        assert!(!lock.released, "guard must remain unreleased");
        assert_eq!(flaky.deletes(), 1);

        lock.release().expect("retry must succeed");
        assert!(lock.released);
        assert_eq!(flaky.deletes(), 2);
    }

    // Permanent delete failure leaves the guard unreleased.
    #[test]
    fn release_failure_is_idempotent_and_never_marks_released() {
        let flaky = Arc::new(FlakyDeleteDirectory::new(usize::MAX));
        let directory: Arc<dyn Directory> = flaky.clone();
        let mut lock = WriterLock::acquire(&directory).expect("lock acquisition");
        assert!(lock.release().is_err());
        assert!(!lock.released);
        assert!(lock.release().is_err());
        assert_eq!(flaky.deletes(), 2);
    }
}

#[cfg(test)]
mod batch_tests {
    use super::*;
    use crate::analysis::CancellationFlag;
    use crate::contract::budget::{BudgetKind, Budgets};
    use crate::contract::document::FieldValues;
    use crate::contract::mutation::{DocumentPatch, PatchOperation, QueryMutationSelector};
    use crate::contract::value::FieldValue;
    use crate::index::Index;
    use crate::segment::format::SectionKind;
    use crate::storage::MemoryDirectory;

    use crate::index::amendment01::{doc, key, publish_transformed_state, registry, schema};

    fn memory_writer(limits: IndexLimits) -> IndexWriter {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create_with_limits(directory, schema(), registry(), limits)
            .expect("create index");
        index.writer().expect("writer")
    }

    /// All-stored M2 schema: no indexed-only field, so committed/flushed
    /// documents are losslessly reconstructable.
    fn m2_schema() -> crate::contract::schema::Schema {
        use crate::contract::document::Cardinality;
        use crate::contract::schema::{FieldDefinition, FieldOptions};
        use crate::contract::value::FieldType;
        crate::contract::schema::Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("standard_folded"),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
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
        .expect("m2 schema")
    }

    fn m2_writer(limits: IndexLimits) -> IndexWriter {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create_with_limits(directory, m2_schema(), registry(), limits)
            .expect("create index");
        index.writer().expect("writer")
    }

    fn cmd(target: MutationTarget, action: MutationAction) -> MutationCommand {
        MutationCommand::new(target, action)
    }

    fn insert(document: Document) -> MutationAction {
        MutationAction::Insert(document)
    }

    fn upsert(document: Document) -> MutationAction {
        MutationAction::Upsert(document)
    }

    fn replace(document: Document) -> MutationAction {
        MutationAction::Replace(document)
    }

    fn no_cancel() -> CancellationFlag {
        CancellationFlag::new()
    }

    fn revisions(response: &MutationBatchResponse) -> Vec<Option<u64>> {
        response
            .outcomes
            .iter()
            .flat_map(|command| command.keys.iter().map(|outcome| outcome.revision))
            .collect()
    }

    fn outcome_keys(response: &MutationBatchResponse) -> Vec<Vec<String>> {
        response
            .outcomes
            .iter()
            .map(|command| {
                command
                    .keys
                    .iter()
                    .map(|outcome| outcome.key.as_str().to_owned())
                    .collect()
            })
            .collect()
    }

    fn state_payload_version(writer: &IndexWriter) -> u16 {
        let manifest = writer.committed_manifest().expect("committed manifest");
        let reference = manifest
            .mutation_state
            .as_ref()
            .expect("mutation state reference");
        let storage_key = StorageKey::parse(&reference.object_key).expect("state key");
        let bytes = support::read_bounded(
            writer.directory().as_ref(),
            &storage_key,
            reference.content_length,
        )
        .expect("state bytes");
        let view =
            crate::segment::format::parse_container(&bytes, writer.limits_ref().segment_limits())
                .expect("container");
        let body = view
            .body(SectionKind::MutationState)
            .expect("mutation state section");
        u16::from_le_bytes([body[0], body[1]])
    }

    // ---------------- raw explicit-key admission-work ceiling ----------------

    /// Structural proof that the admission-work preflight runs **before**
    /// target resolution and charges raw occurrences, not resolved keys.
    #[test]
    fn raw_key_preflight_counts_raw_occurrences_before_dedup() {
        let flag = CancellationFlag::new();
        let repeated = MutationCommand::new(
            MutationTarget::Keys(vec![key("same"); 7]),
            MutationAction::Delete,
        );
        // Raw count is 7 even though the resolved (deduplicated) count is 1.
        assert_eq!(
            batch_raw_key_preflight(&MutationBatch::new(vec![repeated.clone()]), &flag, 10)
                .unwrap(),
            7
        );
        // The helper is a pure length scan: no key is cloned or expanded, so the
        // same command is rejected from `Vec::len()` alone at a smaller ceiling.
        assert!(matches!(
            batch_raw_key_preflight(&MutationBatch::new(vec![repeated]), &flag, 6),
            Err(IndexError::ResourceLimit {
                limit: 6,
                requested: 7
            })
        ));
    }

    #[test]
    fn raw_key_preflight_aggregates_mixed_targets_with_checked_arithmetic() {
        let flag = CancellationFlag::new();
        let batch = MutationBatch::new(vec![
            MutationCommand::new(MutationTarget::Key(key("a")), MutationAction::Delete),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("b"), key("b"), key("c")]),
                MutationAction::Delete,
            ),
            MutationCommand::new(MutationTarget::Key(key("d")), MutationAction::Delete),
        ]);
        assert_eq!(batch_raw_key_preflight(&batch, &flag, 5).unwrap(), 5);
        assert!(matches!(
            batch_raw_key_preflight(&batch, &flag, 4),
            Err(IndexError::ResourceLimit {
                limit: 4,
                requested: 5
            })
        ));
    }

    #[test]
    fn raw_key_preflight_preserves_typed_error_precedence() {
        let flag = CancellationFlag::new();
        // Query+Delete is admitted from M3 onwards and contributes zero raw
        // explicit-key occurrences.
        let query = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(crate::contract::mutation::QueryMutationSelector {
                query: crate::contract::query::Query::MatchAll,
                max_matches: 1,
                expected_generation: None,
            }),
            MutationAction::Delete,
        )]);
        assert_eq!(batch_raw_key_preflight(&query, &flag, 1).unwrap(), 0);

        // Every other query action keeps the typed unsupported rejection.
        let query_update = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(crate::contract::mutation::QueryMutationSelector {
                query: crate::contract::query::Query::MatchAll,
                max_matches: 1,
                expected_generation: None,
            }),
            MutationAction::Update(DocumentPatch {
                operations: Vec::new(),
            }),
        )]);
        assert!(matches!(
            batch_raw_key_preflight(&query_update, &flag, 1),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::UnsupportedTargetAction { .. }
            })
        ));

        let oversized_update = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(vec![key("a"); 9]),
            MutationAction::Update(DocumentPatch {
                operations: Vec::new(),
            }),
        )]);
        // Update is now an admitted action. Its raw key list is still charged
        // before deduplication, so an oversized duplicated list is a resource
        // rejection, not a target/action rejection.
        assert!(matches!(
            batch_raw_key_preflight(&oversized_update, &flag, 1),
            Err(IndexError::ResourceLimit {
                limit: 1,
                requested: 9
            })
        ));

        // Empty key lists keep the typed invalid-batch rejection.
        let empty = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(Vec::new()),
            MutationAction::Delete,
        )]);
        assert!(matches!(
            batch_raw_key_preflight(&empty, &flag, 1),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::InvalidBatch { .. }
            })
        ));

        // Cancellation is observed first.
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            batch_raw_key_preflight(
                &MutationBatch::new(vec![MutationCommand::new(
                    MutationTarget::Key(key("a")),
                    MutationAction::Delete
                )]),
                &cancelled,
                1
            ),
            Err(IndexError::Cancelled)
        ));
    }

    // ---------------- M1-U01 ----------------

    #[test]
    fn u01_empty_batch_is_rejected_before_any_state_change() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(&MutationBatch::new(Vec::new()), &no_cancel())
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::Contract(QueryError::InvalidBatch(InvalidBatchReason::Empty))
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn u01_empty_key_list_is_rejected() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Keys(Vec::new()),
            MutationAction::Delete,
        )]);
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::InvalidBatch { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn u01_too_many_commands_is_rejected() {
        let limits = IndexLimits::new().with_max_batch_commands(3);
        let mut writer = memory_writer(limits);
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(
            (0..4)
                .map(|index| {
                    cmd(
                        MutationTarget::Key(key(&format!("k{index}"))),
                        MutationAction::Delete,
                    )
                })
                .collect(),
        );
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::ResourceLimit {
                limit: 3,
                requested: 4
            }
        ));
        assert_eq!(writer.state_snapshot(), before);

        // Exactly at the limit is accepted.
        let batch = MutationBatch::new(
            (0..3)
                .map(|index| {
                    cmd(
                        MutationTarget::Key(key(&format!("k{index}"))),
                        MutationAction::Delete,
                    )
                })
                .collect(),
        );
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(response.outcomes.len(), 3);
    }

    // ---------------- M1-U02 ----------------

    #[test]
    fn u02_single_key_action_matrix() {
        let mut writer = memory_writer(IndexLimits::default());
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    insert(doc("a", "one", "", "x", 1)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(response.outcomes.len(), 1);
        assert_eq!(response.outcomes[0].command_index, 0);
        assert_eq!(response.outcomes[0].matched, 1);
        assert_eq!(response.outcomes[0].keys[0].intent, MutationIntent::Insert);
        assert_eq!(response.outcomes[0].keys[0].revision, Some(1));
        assert_eq!(writer.state_snapshot().pending_len, 1);

        // Insert on a live key is rejected.
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    insert(doc("a", "two", "", "x", 2)),
                )]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(error, IndexError::DuplicateDocument { .. }));

        // Replace on a live key replaces without changing the intent contract.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    replace(doc("a", "three", "", "x", 3)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(response.outcomes[0].keys[0].revision, Some(2));
        assert_eq!(response.outcomes[0].keys[0].intent, MutationIntent::Upsert);

        // Upsert replaces again.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    upsert(doc("a", "four", "", "x", 4)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(3)]);

        // Delete tombstones.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    MutationAction::Delete,
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(4)]);
        assert!(
            !writer
                .committed_state_arc()
                .map(|state| state.is_live(&key("a")))
                .unwrap_or(false)
        );
    }

    #[test]
    fn u02_single_element_key_list_behaves_like_key() {
        let mut writer = memory_writer(IndexLimits::default());
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Keys(vec![key("a")]),
                    insert(doc("a", "one", "", "x", 1)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(1)]);
    }

    #[test]
    fn u02_delete_on_absent_key_matches_single_apply() {
        // Independent oracle: single-key `apply(Delete)` on a fresh writer.
        let mut single = memory_writer(IndexLimits::default());
        let expected = single
            .apply(MutationRequest::delete(key("ghost")))
            .expect("single delete");

        let mut batched = memory_writer(IndexLimits::default());
        let response = batched
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("ghost")),
                    MutationAction::Delete,
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(response.outcomes[0].keys[0].revision, expected.revision);
        assert_eq!(response.outcomes[0].keys[0].intent, expected.intent);
        assert_eq!(
            batched.state_snapshot().admitted,
            single.state_snapshot().admitted
        );
    }

    // ---------------- M1-U03 ----------------

    #[test]
    fn u03_duplicate_keys_dedupe_by_first_occurrence_but_sort_response() {
        let mut writer = memory_writer(IndexLimits::default());
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Keys(vec![key("c"), key("a"), key("c"), key("b")]),
            MutationAction::Delete,
        )]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(response.outcomes[0].matched, 3);
        assert_eq!(
            outcome_keys(&response),
            vec![vec!["a".to_owned(), "b".to_owned(), "c".to_owned()]]
        );
        assert_eq!(revisions(&response), vec![Some(1), Some(1), Some(1)]);
        // One accepted op per unique key, in first-occurrence order c, a, b.
        let journal: Vec<String> = writer
            .state_snapshot()
            .journal
            .iter()
            .map(|(k, _, _)| k.as_str().to_owned())
            .collect();
        assert_eq!(journal, vec!["c", "a", "b"]);
    }

    // ---------------- M1-U04 ----------------

    #[test]
    fn u04_repeated_key_commands_consume_successive_revisions() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("k", "seed", "", "x", 0)))
            .unwrap();
        writer.commit().unwrap();
        writer.apply(MutationRequest::delete(key("k"))).unwrap();
        writer.commit().unwrap();

        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("k")),
                insert(doc("k", "one", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("k")),
                upsert(doc("k", "two", "", "x", 2)),
            ),
            cmd(MutationTarget::Key(key("k")), MutationAction::Delete),
        ]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(
            revisions(&response),
            vec![Some(3), Some(4), Some(5)],
            "each repeated command consumes exactly one revision"
        );
        writer.commit().unwrap();

        let state = writer.committed_state_arc().unwrap();
        let row = state.row(&key("k")).expect("row");
        assert_eq!(row.revision, 5);
        assert_eq!(row.status, KeyStatus::Deleted);
        // The winning committed row is a tombstone.
        assert!(!state.is_live(&key("k")));
    }

    // ---------------- M1-U05 ----------------

    #[test]
    fn u05_precondition_truth_table() {
        // Build a fresh writer per (precondition, state) cell.
        for (label, revision, live) in [
            ("absent", None, false),
            ("tombstone", Some(4u64), false),
            ("live", Some(4u64), true),
        ] {
            for precondition in [
                MutationPrecondition::None,
                MutationPrecondition::MustExist,
                MutationPrecondition::MustNotExist,
                MutationPrecondition::ExpectedRevision(4),
                MutationPrecondition::ExpectedRevision(3),
            ] {
                let mut writer = memory_writer(IndexLimits::default());
                match revision {
                    Some(rev) if live => {
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        assert_eq!(rev, 4);
                    }
                    Some(_) => {
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer
                            .apply(MutationRequest::upsert(doc("k", "t", "", "x", 1)))
                            .unwrap();
                        writer.apply(MutationRequest::delete(key("k"))).unwrap();
                    }
                    None => {}
                }
                let batch = MutationBatch::new(vec![
                    cmd(MutationTarget::Key(key("k")), MutationAction::Delete)
                        .with_precondition(precondition),
                ]);
                let result = writer.apply_batch(&batch, &no_cancel());
                let expected_ok = match precondition {
                    MutationPrecondition::None => true,
                    MutationPrecondition::MustExist => live,
                    MutationPrecondition::MustNotExist => !live,
                    MutationPrecondition::ExpectedRevision(expected) => {
                        revision.is_some() && expected == 4
                    }
                };
                match (expected_ok, result) {
                    (true, Ok(response)) => {
                        let expected_revision = revision.unwrap_or(0) + 1;
                        assert_eq!(
                            revisions(&response),
                            vec![Some(expected_revision)],
                            "{label}"
                        );
                    }
                    (
                        false,
                        Err(IndexError::MutationRejected {
                            rejection: MutationRejection::PreconditionFailed { .. },
                        }),
                    ) => {}
                    (expected_ok, other) => {
                        panic!("{label} {precondition:?}: expected ok={expected_ok}, got {other:?}")
                    }
                }
            }
        }
    }

    // ---------------- M1-U06 ----------------

    #[test]
    fn u06_batch_key_limit_boundaries() {
        for (limit, keys, ok) in [(3u64, 2usize, true), (3, 3, true), (3, 4, false)] {
            let mut writer = memory_writer(IndexLimits::new().with_max_batch_keys(limit));
            let before = writer.state_snapshot();
            let batch = MutationBatch::new(vec![cmd(
                MutationTarget::Keys((0..keys).map(|i| key(&format!("k{i}"))).collect()),
                MutationAction::Delete,
            )]);
            let result = writer.apply_batch(&batch, &no_cancel());
            if ok {
                assert_eq!(result.unwrap().outcomes[0].matched, keys as u64);
            } else {
                assert!(matches!(
                    result.unwrap_err(),
                    IndexError::ResourceLimit { requested, .. } if requested > limit
                ));
                assert_eq!(writer.state_snapshot(), before);
            }
        }
    }

    #[test]
    fn u06_response_byte_limit_boundaries() {
        let probe = {
            let mut writer = memory_writer(IndexLimits::default());
            let batch = MutationBatch::new(vec![cmd(
                MutationTarget::Keys(vec![key("aaaa"), key("bbbb")]),
                MutationAction::Delete,
            )]);
            writer
                .apply_batch(&batch, &no_cancel())
                .unwrap()
                .encoded_len()
                .unwrap()
        };
        for (limit, ok) in [(probe - 1, false), (probe, true), (probe + 1, true)] {
            let mut writer = memory_writer(IndexLimits::new().with_max_batch_response_bytes(limit));
            let batch = MutationBatch::new(vec![cmd(
                MutationTarget::Keys(vec![key("aaaa"), key("bbbb")]),
                MutationAction::Delete,
            )]);
            let result = writer.apply_batch(&batch, &no_cancel());
            assert_eq!(result.is_ok(), ok, "limit={limit}");
        }
    }

    #[test]
    fn u06_batch_replay_key_limit_boundaries() {
        for (limit, keys, ok) in [(2u64, 2usize, true), (2, 3, false)] {
            let mut writer = memory_writer(IndexLimits::new().with_max_batch_replay_keys(limit));
            let batch = MutationBatch::new(vec![cmd(
                MutationTarget::Keys((0..keys).map(|i| key(&format!("k{i}"))).collect()),
                MutationAction::Delete,
            )]);
            let before = writer.state_snapshot();
            let result = writer.apply_batch(&batch, &no_cancel());
            assert_eq!(result.is_ok(), ok);
            if !ok {
                assert!(matches!(
                    result.unwrap_err(),
                    IndexError::ResourceLimit { .. }
                ));
                assert_eq!(writer.state_snapshot(), before);
            }
        }
    }

    // ---------------- M1-U07 ----------------

    #[test]
    fn u07_idempotent_replay_returns_the_exact_original_outcome() {
        let mut writer = memory_writer(IndexLimits::default());
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            insert(doc("a", "one", "", "x", 1)),
        )])
        .with_idempotency_key(IdempotencyKey::new("batch-token").unwrap());
        let first = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert!(!first.replayed);
        let after_first = writer.state_snapshot();

        let replay = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert!(replay.replayed);
        assert!(
            replay.outcomes[0]
                .keys
                .iter()
                .all(|outcome| outcome.replayed)
        );
        assert_eq!(
            replay.outcomes[0].keys[0].revision,
            first.outcomes[0].keys[0].revision
        );
        // No new admission: identical journal/pending, no new transition.
        assert_eq!(writer.state_snapshot(), after_first);

        // Same token, different request conflicts and changes nothing.
        let other = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            insert(doc("a", "different", "", "x", 2)),
        )])
        .with_idempotency_key(IdempotencyKey::new("batch-token").unwrap());
        let error = writer.apply_batch(&other, &no_cancel()).unwrap_err();
        assert!(matches!(error, IndexError::IdempotencyConflict { .. }));
        assert_eq!(writer.state_snapshot(), after_first);
    }

    #[test]
    fn u07_replay_survives_commit_and_reopen() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(directory.clone(), schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            insert(doc("a", "one", "", "x", 1)),
        )])
        .with_idempotency_key(IdempotencyKey::new("durable-token").unwrap());
        let first = writer.apply_batch(&batch, &no_cancel()).unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();

        let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
        let mut writer = reopened.writer().unwrap();
        let snapshot = writer.reader();
        let before = writer.state_snapshot();
        let replay = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert!(replay.replayed);
        assert!(
            replay
                .outcomes
                .iter()
                .all(|command| { command.keys.iter().all(|outcome| outcome.replayed) })
        );
        assert_eq!(
            revisions(&replay),
            revisions(&first),
            "durable replay returns the original revisions"
        );
        assert_eq!(outcome_keys(&replay), outcome_keys(&first));
        assert_eq!(writer.state_snapshot(), before);
        // Reader is unchanged by a replay.
        assert_eq!(
            snapshot.stored_key_set().unwrap(),
            writer.reader().stored_key_set().unwrap()
        );
    }

    // ---------------- M1-U08 ----------------

    #[test]
    fn u08_query_delete_is_admitted_and_update_on_absent_key_is_not_applicable() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();

        let query_batch = MutationBatch::new(vec![cmd(
            MutationTarget::Query(QueryMutationSelector {
                query: crate::contract::query::Query::MatchAll,
                max_matches: 10,
                expected_generation: None,
            }),
            MutationAction::Delete,
        )]);
        let zero = writer.apply_batch(&query_batch, &no_cancel()).unwrap();
        assert_eq!(zero.outcomes[0].matched, 0);
        assert!(zero.outcomes[0].keys.is_empty());
        assert_eq!(writer.pending_mutations(), 0);
        assert_eq!(writer.pending_documents(), 0);
        assert_eq!(writer.generation(), before.generation);
        let after_zero = writer.state_snapshot();

        let update_batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Unset {
                    field: "tag".to_owned(),
                }],
            }),
        )]);
        // M2 admits Update only for a live key; an absent key is a typed
        // applicability rejection, not a target/action rejection.
        assert!(matches!(
            writer.apply_batch(&update_batch, &no_cancel()).unwrap_err(),
            IndexError::MutationRejected {
                rejection: MutationRejection::ActionNotApplicable { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), after_zero);
    }

    // ---------------- M1-U09 ----------------

    #[test]
    fn u09_mismatched_document_key_and_invalid_schema_are_rejected() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();
        let mismatch = MutationBatch::new(vec![
            cmd(MutationTarget::Key(key("a")), MutationAction::Delete),
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("other", "one", "", "x", 1)),
            ),
        ]);
        assert!(matches!(
            writer.apply_batch(&mismatch, &no_cancel()).unwrap_err(),
            IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::TypeMismatch { .. }
            ))
        ));
        assert_eq!(writer.state_snapshot(), before);

        // Wrong value type for a typed field.
        let mut bad = Document::new(key("a"));
        bad.insert("n", FieldValues::Single(FieldValue::Text("nope".into())))
            .unwrap();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(MutationTarget::Key(key("a")), insert(bad))]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(error, IndexError::Contract(_)));
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-U11 ----------------

    #[test]
    fn u11_action_applicability_is_rejected_before_admission() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();

        // Replace on an absent key.
        let replace_absent = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            replace(doc("a", "one", "", "x", 1)),
        )]);
        assert!(matches!(
            writer
                .apply_batch(&replace_absent, &no_cancel())
                .unwrap_err(),
            IndexError::MutationRejected {
                rejection: MutationRejection::ActionNotApplicable { .. }
            }
        ));

        // Multi-key full-document action.
        let multi = MutationBatch::new(vec![cmd(
            MutationTarget::Keys(vec![key("a"), key("b")]),
            upsert(doc("a", "one", "", "x", 1)),
        )]);
        assert!(matches!(
            writer.apply_batch(&multi, &no_cancel()).unwrap_err(),
            IndexError::MutationRejected {
                rejection: MutationRejection::UnsupportedTargetAction { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-U12 ----------------

    #[test]
    fn u12_batch_and_single_key_tokens_share_one_namespace() {
        let mut writer = memory_writer(IndexLimits::default());
        let token = IdempotencyKey::new("shared").unwrap();
        writer
            .apply(
                MutationRequest::insert(doc("a", "one", "", "x", 1))
                    .with_idempotency_key(token.clone()),
            )
            .unwrap();
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("b")),
            MutationAction::Delete,
        )])
        .with_idempotency_key(token.clone());
        assert!(matches!(
            writer.apply_batch(&batch, &no_cancel()).unwrap_err(),
            IndexError::IdempotencyConflict { .. }
        ));
        assert_eq!(writer.state_snapshot(), before);

        // Reverse direction across a durable commit.
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(directory.clone(), schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let batch_token = IdempotencyKey::new("batch-shared").unwrap();
        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("c")),
                    MutationAction::Delete,
                )])
                .with_idempotency_key(batch_token.clone()),
                &no_cancel(),
            )
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();

        let reopened = Index::open_existing(directory, schema(), registry()).unwrap();
        let mut writer = reopened.writer().unwrap();
        let before = writer.state_snapshot();
        assert!(matches!(
            writer
                .apply(
                    MutationRequest::insert(doc("d", "one", "", "x", 1))
                        .with_idempotency_key(batch_token)
                )
                .unwrap_err(),
            IndexError::IdempotencyConflict { .. }
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-U13 ----------------

    #[test]
    fn u13_v1_is_retained_when_eligible_and_upgraded_for_batch_replay() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let v2 = (FEATURE_MUTATION_STATE_V2, 1);

        // Untokened batch: still v1.
        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    insert(doc("a", "one", "", "x", 1)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        writer.commit().unwrap();
        assert_eq!(state_payload_version(&writer), 1);
        assert!(
            !writer
                .committed_manifest()
                .unwrap()
                .required_features
                .contains(&v2)
        );

        // Tokened batch: upgrades to v2 with the feature marker.
        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("b")),
                    MutationAction::Delete,
                )])
                .with_idempotency_key(IdempotencyKey::new("t").unwrap()),
                &no_cancel(),
            )
            .unwrap();
        writer.commit().unwrap();
        assert_eq!(state_payload_version(&writer), 2);
        assert!(
            writer
                .committed_manifest()
                .unwrap()
                .required_features
                .contains(&v2)
        );

        // A later untokened commit never downgrades.
        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("c")),
                    MutationAction::Delete,
                )]),
                &no_cancel(),
            )
            .unwrap();
        writer.commit().unwrap();
        assert_eq!(state_payload_version(&writer), 2);
        assert!(
            writer
                .committed_manifest()
                .unwrap()
                .required_features
                .contains(&v2)
        );
        assert!(writer.committed_state_arc().unwrap().has_batch_replay());
    }

    // ---------------- M1-A01 ----------------

    #[test]
    fn a01_last_command_failure_leaves_state_identical() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("seed", "seed", "", "x", 0)))
            .unwrap();
        writer.commit().unwrap();
        let pit = writer.pin().unwrap();
        let before = writer.state_snapshot();

        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("a", "one", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("b")),
                insert(doc("b", "two", "", "x", 2)),
            ),
            cmd(MutationTarget::Key(key("c")), MutationAction::Delete)
                .with_precondition(MutationPrecondition::MustExist),
        ]);
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), before);
        // No revision or token consumed for the successful prefix.
        assert_eq!(writer.pending_mutations(), before.journal.len());
        assert_eq!(writer.state_snapshot().install_transitions, 0);
        // The pinned reader is unchanged.
        assert_eq!(pit.snapshot().stored_key_set().unwrap().len(), 1);
    }

    // ---------------- M1-A02 ----------------

    #[test]
    fn a02_last_document_exceeding_pending_bytes_rolls_back_whole_batch() {
        let probe_bytes = {
            let mut writer = memory_writer(IndexLimits::default());
            writer
                .apply_batch(
                    &MutationBatch::new(vec![
                        cmd(
                            MutationTarget::Key(key("a")),
                            insert(doc("a", "one", "", "x", 1)),
                        ),
                        cmd(
                            MutationTarget::Key(key("b")),
                            insert(doc("b", "two", "", "x", 2)),
                        ),
                    ]),
                    &no_cancel(),
                )
                .unwrap();
            writer.pending_bytes
        };
        let mut writer = memory_writer(IndexLimits::new().with_max_pending_bytes(probe_bytes - 1));
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![
                    cmd(
                        MutationTarget::Key(key("a")),
                        insert(doc("a", "one", "", "x", 1)),
                    ),
                    cmd(
                        MutationTarget::Key(key("b")),
                        insert(doc("b", "two", "", "x", 2)),
                    ),
                ]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(error, IndexError::ResourceLimit { .. }));
        assert_eq!(writer.state_snapshot(), before);
        assert_eq!(writer.pending_documents(), 0);
    }

    // ---------------- M1-A03 ----------------

    #[test]
    fn a03_revision_overflow_rejects_the_whole_batch() {
        let (directory, _, _) = publish_transformed_state(|mut rows, replay| {
            rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX;
            (rows, replay)
        });
        let index = Index::open_existing(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("other-key")),
                upsert(doc("other-key", "fresh", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("overflow-key")),
                MutationAction::Delete,
            ),
        ]);
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(
            matches!(error, IndexError::RevisionOverflow),
            "expected RevisionOverflow, got {error:?}"
        );
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-A04 ----------------

    #[test]
    fn a04_single_over_limit_rejects_without_truncation() {
        let mut writer = memory_writer(IndexLimits::new().with_max_batch_keys(2));
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Keys(vec![key("a"), key("b"), key("c")]),
            MutationAction::Delete,
        )]);
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::ResourceLimit {
                limit: 2,
                requested: 3
            }
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-A05 ----------------

    #[test]
    fn a05_cancellation_at_every_position_leaves_no_state() {
        for position in 0..4 {
            let mut writer = memory_writer(IndexLimits::default());
            let before = writer.state_snapshot();
            let batch = MutationBatch::new(vec![
                cmd(
                    MutationTarget::Key(key("a")),
                    insert(doc("a", "one", "", "x", 1)),
                ),
                cmd(
                    MutationTarget::Key(key("b")),
                    insert(doc("b", "two", "", "x", 2)),
                ),
                cmd(MutationTarget::Key(key("c")), MutationAction::Delete),
                cmd(MutationTarget::Key(key("d")), MutationAction::Delete),
            ]);
            // A canceller that trips after `position` polls.
            struct AfterPolls {
                remaining: std::cell::Cell<usize>,
            }
            impl Cancellation for AfterPolls {
                fn is_cancelled(&self) -> bool {
                    let remaining = self.remaining.get();
                    if remaining == 0 {
                        true
                    } else {
                        self.remaining.set(remaining - 1);
                        false
                    }
                }
            }
            let cancel = AfterPolls {
                remaining: std::cell::Cell::new(position),
            };
            let result = writer.apply_batch(&batch, &cancel);
            assert!(
                matches!(result, Err(IndexError::Cancelled)),
                "pos={position}"
            );
            assert_eq!(writer.state_snapshot(), before, "pos={position}");
        }
    }

    #[test]
    fn a05_presignalled_cancellation_is_reported_first() {
        let mut writer = memory_writer(IndexLimits::default());
        let before = writer.state_snapshot();
        let flag = CancellationFlag::new();
        flag.cancel();
        assert!(matches!(
            writer
                .apply_batch(
                    &MutationBatch::new(vec![cmd(
                        MutationTarget::Key(key("a")),
                        MutationAction::Delete
                    )]),
                    &flag
                )
                .unwrap_err(),
            IndexError::Cancelled
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    // ---------------- M1-A06 ----------------

    #[test]
    fn a06_planner_failure_leaves_writer_retryable() {
        let mut writer = memory_writer(IndexLimits::new().with_max_batch_response_bytes(80));
        let before = writer.state_snapshot();
        let too_large = MutationBatch::new(vec![cmd(
            MutationTarget::Keys((0..20).map(|i| key(&format!("k{i}"))).collect()),
            MutationAction::Delete,
        )]);
        assert!(matches!(
            writer.apply_batch(&too_large, &no_cancel()).unwrap_err(),
            IndexError::ResourceLimit { .. }
        ));
        assert_eq!(writer.state_snapshot(), before);
        assert!(!writer.poisoned);

        // A smaller batch on the same writer still succeeds.
        let small = MutationBatch::new(vec![cmd(
            MutationTarget::Keys(vec![key("k0"), key("k1")]),
            MutationAction::Delete,
        )]);
        assert_eq!(
            writer.apply_batch(&small, &no_cancel()).unwrap().outcomes[0].matched,
            2
        );
    }

    // ---------------- M1-A07 ----------------

    #[test]
    fn a07_refresh_after_batch_keeps_pinned_reader_stable() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "seed", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        writer.refresh().unwrap();
        let pinned = writer.pin().unwrap();
        let old_keys = pinned.snapshot().stored_key_set().unwrap();

        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("b")),
                    insert(doc("b", "added", "", "x", 2)),
                )]),
                &no_cancel(),
            )
            .unwrap();
        let refreshed = writer.refresh().unwrap();
        assert_eq!(refreshed.stored_key_set().unwrap().len(), 2);
        assert_eq!(pinned.snapshot().stored_key_set().unwrap(), old_keys);
        assert_eq!(old_keys.len(), 1);
    }

    // ---------------- M1-A12 ----------------

    #[test]
    fn a12_batch_and_single_key_mutations_stay_coherent() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            upsert(doc("a", "two", "", "x", 2)),
        )]);
        assert_eq!(
            revisions(&writer.apply_batch(&batch, &no_cancel()).unwrap()),
            vec![Some(2)]
        );
        assert_eq!(
            writer
                .apply(MutationRequest::upsert(doc("a", "three", "", "x", 3)))
                .unwrap()
                .revision,
            Some(3)
        );
        writer.commit().unwrap();
        assert_eq!(
            writer
                .committed_state_arc()
                .unwrap()
                .row(&key("a"))
                .unwrap()
                .revision,
            3
        );
    }

    // ---------------- flush / refresh / commit integration ----------------

    #[test]
    fn batch_rows_flush_through_the_existing_remap() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply_batch(
                &MutationBatch::new(vec![
                    cmd(
                        MutationTarget::Key(key("a")),
                        insert(doc("a", "one", "", "x", 1)),
                    ),
                    cmd(
                        MutationTarget::Key(key("b")),
                        insert(doc("b", "two", "", "x", 2)),
                    ),
                ]),
                &no_cancel(),
            )
            .unwrap();
        let outcome = writer.flush().unwrap();
        assert_eq!(outcome.documents, 2);
        assert_eq!(writer.pending_documents(), 0);
        // Every journal location is now a flushed pointer.
        assert!(
            writer
                .state_snapshot()
                .journal
                .iter()
                .all(|(_, _, location)| matches!(location, Some(MutationLocation::Flushed { .. })))
        );

        let snapshot = writer.refresh().unwrap();
        assert_eq!(snapshot.stored_key_set().unwrap().len(), 2);
        writer.commit().unwrap();
        assert_eq!(writer.generation(), Some(1));
    }

    #[test]
    fn batch_install_happens_exactly_once() {
        let mut writer = memory_writer(IndexLimits::default());
        assert_eq!(writer.state_snapshot().install_transitions, 0);
        writer
            .apply_batch(
                &MutationBatch::new(vec![
                    cmd(
                        MutationTarget::Key(key("a")),
                        insert(doc("a", "one", "", "x", 1)),
                    ),
                    cmd(MutationTarget::Key(key("b")), MutationAction::Delete),
                ]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(writer.state_snapshot().install_transitions, 1);
    }

    #[test]
    fn compaction_preserves_batch_replay_records() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(directory.clone(), schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("a", "one", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("b")),
                insert(doc("b", "two", "", "x", 2)),
            ),
        ])
        .with_idempotency_key(IdempotencyKey::new("compact-token").unwrap());
        let first = writer.apply_batch(&batch, &no_cancel()).unwrap();
        writer.commit().unwrap();
        writer.compact().unwrap();
        let state = writer.committed_state_arc().unwrap();
        assert_eq!(state.batch_replay_count(), 1);
        // Replay still returns the exact original outcome after compaction.
        let replay = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert!(replay.replayed);
        assert_eq!(revisions(&replay), revisions(&first));
        assert_eq!(outcome_keys(&replay), outcome_keys(&first));
        assert!(
            replay
                .outcomes
                .iter()
                .all(|command| command.keys.iter().all(|outcome| outcome.replayed))
        );
    }

    // ---------------- M2 ----------------

    fn update(operations: Vec<PatchOperation>) -> MutationAction {
        MutationAction::Update(DocumentPatch { operations })
    }

    fn set_text(field: &str, value: &str) -> PatchOperation {
        PatchOperation::Set {
            field: field.to_owned(),
            values: FieldValues::Single(FieldValue::Text(value.to_owned())),
        }
    }

    fn set_i64(field: &str, value: i64) -> PatchOperation {
        PatchOperation::Set {
            field: field.to_owned(),
            values: FieldValues::Single(FieldValue::I64(value)),
        }
    }

    fn pending_document(writer: &IndexWriter) -> &SegmentDocument {
        writer.pending.last().expect("pending document")
    }

    #[test]
    fn m2_same_batch_updates_use_staged_documents_and_successive_revisions() {
        let mut writer = memory_writer(IndexLimits::default());
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("a", "original", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![set_text("title", "patched")]),
            ),
            cmd(MutationTarget::Key(key("a")), update(vec![set_i64("n", 9)])),
        ]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(revisions(&response), vec![Some(1), Some(2), Some(3)]);
        assert_eq!(response.outcomes[1].keys[0].intent, MutationIntent::Upsert);
        assert_eq!(response.outcomes[2].keys[0].intent, MutationIntent::Upsert);

        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("title"),
            Some(&FieldValues::Single(FieldValue::Text("patched".to_owned())))
        );
        assert_eq!(
            latest.fields.get("n"),
            Some(&FieldValues::Single(FieldValue::I64(9)))
        );
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("x".to_owned())))
        );
        assert_eq!(writer.pending_documents(), 3);
    }

    #[test]
    fn m2_delete_insert_update_and_replace_update_sequencing() {
        let mut writer = memory_writer(IndexLimits::default());
        let batch = MutationBatch::new(vec![
            cmd(MutationTarget::Key(key("a")), MutationAction::Delete),
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("a", "inserted", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![set_text("title", "updated")]),
            ),
        ]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(revisions(&response), vec![Some(1), Some(2), Some(3)]);
        assert_eq!(
            pending_document(&writer).fields.get("title"),
            Some(&FieldValues::Single(FieldValue::Text("updated".to_owned())))
        );

        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                replace(doc("a", "replaced", "", "y", 2)),
            ),
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![set_text("title", "after replace")]),
            ),
        ]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(revisions(&response), vec![Some(2), Some(3)]);
        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("title"),
            Some(&FieldValues::Single(FieldValue::Text(
                "after replace".to_owned()
            )))
        );
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("y".to_owned())))
        );
        assert_eq!(
            latest.fields.get("n"),
            Some(&FieldValues::Single(FieldValue::I64(2)))
        );
    }

    #[test]
    fn m2_update_reads_pending_flushed_and_committed_sources() {
        // Pending source.
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "pending", "", "x", 1)))
            .unwrap();
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "pending patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);
        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("x".to_owned())))
        );
        assert_eq!(
            latest.fields.get("n"),
            Some(&FieldValues::Single(FieldValue::I64(1)))
        );

        // Flushed physical source.
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "flushed", "", "x", 1)))
            .unwrap();
        writer.flush().unwrap();
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "flushed patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);
        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("x".to_owned())))
        );
        assert_eq!(
            latest.fields.get("n"),
            Some(&FieldValues::Single(FieldValue::I64(1)))
        );

        // Committed physical source.
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "committed", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "committed patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);
        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("title"),
            Some(&FieldValues::Single(FieldValue::Text(
                "committed patched".to_owned()
            )))
        );
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("x".to_owned())))
        );
        assert_eq!(
            latest.fields.get("n"),
            Some(&FieldValues::Single(FieldValue::I64(1)))
        );
    }

    #[test]
    fn m2_indexed_only_physical_source_is_reconstructed_only_while_in_memory() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc(
                "a",
                "body",
                "body text",
                "x",
                1,
            )))
            .unwrap();
        // Pending/in-memory source retains the indexed-only field.
        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "memory patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        writer.flush().unwrap();
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "physical patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ReconstructionUnavailable {
                    field: Some(field),
                    reason: ReconstructionFailure::UnrecoverableField,
                    ..
                }
            } if field == "body"
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn m2_late_failure_leaves_every_writer_field_unchanged() {
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![set_text("title", "first")]),
            ),
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![PatchOperation::Set {
                    field: "n".to_owned(),
                    values: FieldValues::Single(FieldValue::Text("wrong".to_owned())),
                }]),
            ),
        ]);
        let error = writer.apply_batch(&batch, &no_cancel()).unwrap_err();
        assert!(matches!(
            error,
            IndexError::Contract(QueryError::InvalidDocument(
                DocumentError::TypeMismatch { .. }
            ))
        ));
        assert_eq!(writer.state_snapshot(), before);
        assert_eq!(writer.pending_documents(), 0);
    }

    #[test]
    fn m2_replay_after_delete_and_reopen_does_not_reconstruct() {
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(Arc::clone(&directory), m2_schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();

        let token = IdempotencyKey::new("m2-replay-after-delete").unwrap();
        let update_batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            update(vec![set_text("title", "patched")]),
        )])
        .with_idempotency_key(token.clone());
        let first = writer.apply_batch(&update_batch, &no_cancel()).unwrap();
        writer.commit().unwrap();

        writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    MutationAction::Delete,
                )]),
                &no_cancel(),
            )
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();

        let reopened = Index::open_existing(directory, m2_schema(), registry()).unwrap();
        let mut writer = reopened.writer().unwrap();
        let before = writer.state_snapshot();
        let replay = writer.apply_batch(&update_batch, &no_cancel()).unwrap();
        assert!(replay.replayed);
        assert_eq!(revisions(&replay), revisions(&first));
        assert_eq!(outcome_keys(&replay), outcome_keys(&first));
        assert!(
            replay
                .outcomes
                .iter()
                .all(|command| command.keys.iter().all(|outcome| outcome.replayed))
        );
        assert_eq!(writer.state_snapshot(), before);

        let conflict = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("a")),
            update(vec![set_text("title", "different")]),
        )])
        .with_idempotency_key(token);
        assert!(matches!(
            writer.apply_batch(&conflict, &no_cancel()),
            Err(IndexError::IdempotencyConflict { .. })
        ));
    }

    #[test]
    fn m2_source_byte_meter_rejects_flushed_segment_before_decode() {
        let mut writer = m2_writer(IndexLimits::new().with_max_snapshot_bytes(1));
        writer
            .apply(MutationRequest::insert(doc("a", "source", "", "x", 1)))
            .unwrap();
        writer.flush().unwrap();
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::ResourceLimit {
                limit: 1,
                requested
            } if requested > 1
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn m2_revision_overflow_and_cancellation_precede_reconstruction() {
        let (directory, _, _) = publish_transformed_state(|mut rows, replay| {
            rows.get_mut(&key("overflow-key")).unwrap().revision = u64::MAX;
            (rows, replay)
        });
        let index = Index::open_existing(directory, schema(), registry()).unwrap();
        let mut writer = index.writer().unwrap();
        let before = writer.state_snapshot();
        let batch = MutationBatch::new(vec![cmd(
            MutationTarget::Key(key("overflow-key")),
            update(vec![set_text("title", "would patch")]),
        )]);
        assert!(matches!(
            writer.apply_batch(&batch, &no_cancel()),
            Err(IndexError::RevisionOverflow)
        ));
        assert_eq!(writer.state_snapshot(), before);

        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();
        let before = writer.state_snapshot();
        let cancelled = CancellationFlag::new();
        cancelled.cancel();
        assert!(matches!(
            writer.apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "patched")]),
                )]),
                &cancelled,
            ),
            Err(IndexError::Cancelled)
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn m2_update_target_matrix_and_precondition_order() {
        let mut writer = memory_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();

        // A duplicated single-key list still resolves to one update.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Keys(vec![key("a"), key("a")]),
                    update(vec![set_text("title", "list patched")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(response.outcomes[0].matched, 1);
        assert_eq!(revisions(&response), vec![Some(2)]);

        // More than one unique key is unsupported for Update.
        assert!(matches!(
            writer.apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Keys(vec![key("a"), key("b")]),
                    update(vec![set_text("title", "multi")]),
                )]),
                &no_cancel(),
            ),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::UnsupportedTargetAction { .. }
            })
        ));

        // A failing precondition wins over applicability/reconstruction.
        assert!(matches!(
            writer.apply_batch(
                &MutationBatch::new(vec![
                    cmd(
                        MutationTarget::Key(key("a")),
                        update(vec![set_text("title", "never")]),
                    )
                    .with_precondition(MutationPrecondition::MustNotExist),
                ]),
                &no_cancel(),
            ),
            Err(IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            })
        ));
    }

    #[test]
    fn m2_update_delete_sequence_and_tombstone_applicability() {
        let mut writer = m2_writer(IndexLimits::default());
        let batch = MutationBatch::new(vec![
            cmd(
                MutationTarget::Key(key("a")),
                insert(doc("a", "original", "", "x", 1)),
            ),
            cmd(
                MutationTarget::Key(key("a")),
                update(vec![set_text("title", "patched")]),
            ),
            cmd(MutationTarget::Key(key("a")), MutationAction::Delete),
        ]);
        let response = writer.apply_batch(&batch, &no_cancel()).unwrap();
        assert_eq!(revisions(&response), vec![Some(1), Some(2), Some(3)]);
        assert_eq!(
            writer.candidate_state_for(&key("a")).1,
            Some(KeyStatus::Deleted)
        );

        let tombstoned = m2_writer(IndexLimits::default());
        let mut writer = tombstoned;
        writer
            .apply(MutationRequest::insert(doc("a", "original", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        writer.apply(MutationRequest::delete(key("a"))).unwrap();
        writer.commit().unwrap();
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "never")]),
                )]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::ActionNotApplicable { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), before);

        // MustExist fails before applicability/reconstruction on a tombstone.
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![
                    cmd(
                        MutationTarget::Key(key("a")),
                        update(vec![set_text("title", "never")]),
                    )
                    .with_precondition(MutationPrecondition::MustExist),
                ]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::MutationRejected {
                rejection: MutationRejection::PreconditionFailed { .. }
            }
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn m2_unset_of_absent_field_is_an_accepted_new_revision() {
        let mut writer = m2_writer(IndexLimits::default());
        let mut source = Document::new(key("a"));
        source
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("stable".to_owned())),
            )
            .unwrap();
        writer.apply(MutationRequest::insert(source)).unwrap();
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![PatchOperation::Unset {
                        field: "tag".to_owned(),
                    }]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);
        let latest = pending_document(&writer);
        assert_eq!(latest.fields.len(), 1);
        assert!(latest.fields.contains_key("title"));
        assert!(!latest.fields.contains_key("tag"));
    }

    #[test]
    fn m2_source_byte_meter_accepts_exact_and_rejects_one_over() {
        // Exact boundary: a source segment equal to the configured ceiling is
        // accepted.
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "source", "", "x", 1)))
            .unwrap();
        writer.flush().unwrap();
        let segment_bytes = writer.flushed[0].bytes.len() as u64;
        assert!(segment_bytes > 0);
        writer.limits = IndexLimits::new().with_max_snapshot_bytes(segment_bytes);
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "exact")]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);

        // One byte over: rejected before opening the segment.
        let mut writer = m2_writer(IndexLimits::default());
        writer
            .apply(MutationRequest::insert(doc("a", "source", "", "x", 1)))
            .unwrap();
        writer.flush().unwrap();
        let segment_bytes = writer.flushed[0].bytes.len() as u64;
        writer.limits = IndexLimits::new().with_max_snapshot_bytes(segment_bytes - 1);
        let before = writer.state_snapshot();
        let error = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![set_text("title", "one over")]),
                )]),
                &no_cancel(),
            )
            .unwrap_err();
        assert!(matches!(
            error,
            IndexError::ResourceLimit {
                limit,
                requested
            } if limit == segment_bytes - 1 && requested == segment_bytes
        ));
        assert_eq!(writer.state_snapshot(), before);
    }

    #[test]
    fn m2_f01_writer_set_absent_and_unset_absent_at_exact_budget() {
        let mut source = Document::new(key("a"));
        source
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("stable".to_owned())),
            )
            .unwrap();
        let mut final_document = source.clone();
        final_document
            .insert(
                "tag",
                FieldValues::Single(FieldValue::Keyword("x".to_owned())),
            )
            .unwrap();
        let limit = u64::try_from(final_document.approx_size()).unwrap();
        let limits = IndexLimits::new().with_budgets(
            Budgets::new()
                .with(BudgetKind::DocumentBytes, limit)
                .expect("budget"),
        );
        let mut writer = m2_writer(limits);
        writer.apply(MutationRequest::insert(source)).unwrap();

        // Set a previously absent field exactly to the document-byte limit.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![PatchOperation::Set {
                        field: "tag".to_owned(),
                        values: FieldValues::Single(FieldValue::Keyword("x".to_owned())),
                    }]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(2)]);
        let latest = pending_document(&writer);
        assert_eq!(
            latest.fields.get("tag"),
            Some(&FieldValues::Single(FieldValue::Keyword("x".to_owned())))
        );
        let mut candidate = Document::new(key("a"));
        for (name, values) in &latest.fields {
            candidate.insert(name.clone(), values.clone()).unwrap();
        }
        assert_eq!(u64::try_from(candidate.approx_size()).unwrap(), limit);

        // Unset the present field.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![PatchOperation::Unset {
                        field: "tag".to_owned(),
                    }]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(3)]);
        assert!(!pending_document(&writer).fields.contains_key("tag"));

        // Unset an absent field still creates an accepted revision.
        let response = writer
            .apply_batch(
                &MutationBatch::new(vec![cmd(
                    MutationTarget::Key(key("a")),
                    update(vec![PatchOperation::Unset {
                        field: "n".to_owned(),
                    }]),
                )]),
                &no_cancel(),
            )
            .unwrap();
        assert_eq!(revisions(&response), vec![Some(4)]);
        assert!(!pending_document(&writer).fields.contains_key("n"));
    }
}
