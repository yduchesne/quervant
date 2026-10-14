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

use quervant_objectstore::ContentDigest;

use crate::analysis::AnalyzerRegistry;
use crate::contract::document::{
    Document, DocumentKey, IdempotencyKey, MutationIntent, MutationRequest, MutationResponse,
};
use crate::segment::format::FEATURE_MUTATION_STATE;
use crate::segment::{Manifest, ManifestSegmentRef, MutationStateRef, SegmentDocument};
use crate::storage::{Directory, StorageError, StorageKey};

use super::CommittedState;
use super::current::{
    CURRENT_KEY, CurrentPointer, WRITER_LOCK_KEY, manifest_key_for, state_key_for_hex,
};
use super::error::{IndexError, IndexResult};
use super::limits::IndexLimits;
use super::mutation_state::{KeyRow, KeyStatus, MutationStateV1, ReplayRow, mutation_fingerprint};
use super::pit::{self, PinCounter, PitHandle};
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
    pending: Vec<SegmentDocument>,
    pending_bytes: u64,
    flushed: Vec<PendingSegment>,
    published: Option<Arc<ReaderSnapshot>>,
    next_view: u64,
    poisoned: bool,
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
            pending: Vec::new(),
            pending_bytes: 0,
            flushed: Vec::new(),
            published: None,
            next_view: 0,
            poisoned: false,
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
        let state = MutationStateV1::from_parts(rows, self.replay_combined());
        let state_bytes = state.encode()?;
        if state_bytes.len() as u64 > self.limits.max_mutation_state_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_mutation_state_bytes(),
                requested: state_bytes.len() as u64,
            });
        }
        if state.replay_count() as u64 > self.limits.max_replay_entries() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_entries(),
                requested: state.replay_count() as u64,
            });
        }
        if state.replay_bytes() > self.limits.max_replay_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_replay_bytes(),
                requested: state.replay_bytes(),
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
        self.pending.clear();
        self.pending_bytes = 0;
        self.flushed.clear();
        self.poisoned = false;
        let snapshot = self.committed_snapshot();
        self.published = Some(snapshot);
        let _ = (segments_added, doc_total);
        Ok(())
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

    /// Resolve the winning row for every committed key plus every accepted op.
    fn candidate_rows(
        &self,
        pending_segment_id: Option<&str>,
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
        for op in &self.journal {
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
        ))
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

    /// Mark the writer poisoned after an indeterminate publication.
    pub(crate) fn poison(&mut self) {
        self.poisoned = true;
    }

    /// Explicit compaction entry point.
    pub fn compact(&mut self) -> IndexResult<super::merge::MergeOutcome> {
        self.ensure_writable()?;
        super::merge::compact(self)
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
