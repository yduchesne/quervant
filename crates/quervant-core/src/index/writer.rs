//! Local single cooperating writer: insert, flush, refresh and durable commit.
//!
//! Separation of concerns is deliberate:
//!
//! * [`IndexWriter::insert`] admits insert-only documents into a bounded pending
//!   batch.
//! * [`IndexWriter::flush`] builds immutable segment bytes **without** making
//!   them durable or visible to committed readers.
//! * [`IndexWriter::refresh`] publishes a new volatile immutable reader view.
//! * [`IndexWriter::commit`] durably installs segments, the generation manifest
//!   and, last, the atomic `CURRENT` pointer.
//!
//! The writer holds `index/WRITER_LOCK` for its whole lifetime. A stale lock
//! after a crash is never stolen automatically; an operator must remove it.

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_objectstore::ContentDigest;

use crate::analysis::AnalyzerRegistry;
use crate::contract::document::{Document, DocumentKey, MutationIntent, MutationRequest};
use crate::segment::{Manifest, ManifestSegmentRef, SegmentDocument};
use crate::storage::{Directory, StorageError, StorageKey};

use super::CommittedState;
use super::current::{CURRENT_KEY, CurrentPointer, WRITER_LOCK_KEY, manifest_key_for};
use super::error::{IndexError, IndexResult};
use super::limits::IndexLimits;
use super::pit::{self, PinCounter, PitHandle};
use super::snapshot::{ReaderSnapshot, SegmentMeta, SegmentSnapshot};
use super::{IndexOrigin, support};

/// Outcome of a flush.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FlushOutcome {
    /// Segments moved from the pending batch into the flushed set.
    pub segments_flushed: u64,
    /// Documents flushed.
    pub documents: u64,
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

/// A built-but-uncommitted segment.
#[derive(Clone)]
struct PendingSegment {
    meta: SegmentMeta,
    bytes: Arc<Vec<u8>>,
    keys: Vec<DocumentKey>,
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
    pending: Vec<SegmentDocument>,
    pending_bytes: u64,
    uncommitted_keys: BTreeSet<DocumentKey>,
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
            pending: Vec::new(),
            pending_bytes: 0,
            uncommitted_keys: BTreeSet::new(),
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

    /// Admit one insert-only document.
    ///
    /// The logical key is rejected if it exists in the pending, flushed,
    /// uncommitted or committed state.
    pub fn insert(&mut self, document: Document) -> IndexResult<()> {
        self.ensure_writable()?;
        let key = document.key().clone();
        if self.is_duplicate(&key) {
            return Err(IndexError::DuplicateDocument {
                key: key.as_str().to_owned(),
            });
        }
        self.schema
            .validate_document(&document, self.limits.budgets())?;
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
        self.pending.push(to_segment_document(&document));
        self.pending_bytes = new_bytes;
        self.uncommitted_keys.insert(key);
        Ok(())
    }

    /// Apply a typed mutation request.
    ///
    /// PR 6 is insert-only: upsert, delete and idempotency-key execution are
    /// rejected as unsupported with no side effects.
    pub fn apply(&mut self, request: MutationRequest) -> IndexResult<()> {
        if request.idempotency_key.is_some() {
            return Err(IndexError::UnsupportedMutation);
        }
        match request.intent {
            MutationIntent::Insert => {
                let document = request.document.ok_or(IndexError::UnsupportedMutation)?;
                self.insert(document)
            }
            MutationIntent::Upsert | MutationIntent::Delete => Err(IndexError::UnsupportedMutation),
        }
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
    /// uncommitted document (flushed segments and the pending batch). It never
    /// writes `CURRENT` and never makes data durable.
    pub fn refresh(&mut self) -> IndexResult<Arc<ReaderSnapshot>> {
        self.ensure_writable()?;
        let mut segments: Vec<SegmentSnapshot> = Vec::new();
        if let Some(committed) = &self.committed {
            segments.extend(committed.segments.iter().cloned());
        }
        for segment in &self.flushed {
            segments.push(segment.snapshot());
        }
        if !self.pending.is_empty() {
            segments.push(self.build_pending_segment()?.snapshot());
        }
        let snapshot = Arc::new(ReaderSnapshot::new(
            self.committed.as_ref().map(|state| state.generation),
            self.next_view,
            segments,
            *self.limits.segment_limits(),
            Arc::clone(&self.pins),
            self.limits.max_snapshot_bytes(),
        ));
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

    /// Durably commit all flushed and pending documents.
    ///
    /// Ordering: segments, then the generation manifest, then `CURRENT` last.
    /// Acknowledgment happens only after every durability barrier succeeds.
    pub fn commit(&mut self) -> IndexResult<CommitOutcome> {
        self.ensure_writable()?;
        let has_changes = !self.pending.is_empty() || !self.flushed.is_empty();
        if !has_changes {
            if let Some(committed) = &self.committed {
                return Ok(CommitOutcome {
                    generation: committed.generation,
                    documents: 0,
                    segments_added: 0,
                    no_op: true,
                });
            }
        }

        let mut new_segments: Vec<PendingSegment> = self.flushed.clone();
        if !self.pending.is_empty() {
            new_segments.push(self.build_pending_segment()?);
        }
        let segments_added = new_segments.len() as u64;
        if segments_added > self.limits.max_segments_per_commit() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_segments_per_commit(),
                requested: segments_added,
            });
        }
        // Pre-publication resource parity: the prospective committed generation
        // (authoritative committed manifest refs + all built new segments) must
        // satisfy exactly the same per-segment and aggregate encoded-byte bounds
        // that `load_committed_at` enforces on reopen. This runs before any
        // immutable object is installed or CURRENT is published, so a rejected
        // commit has no durable side effects and leaves the writer usable.
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
        let doc_total: u64 = new_segments.iter().map(|segment| segment.doc_count).sum();
        let previous_generation = self
            .committed
            .as_ref()
            .map(|state| state.generation)
            .unwrap_or(0);
        let generation = previous_generation
            .checked_add(1)
            .ok_or(IndexError::GenerationOverflow)?;

        // Step 3: install immutable content-addressed segments.
        for segment in &new_segments {
            let key = StorageKey::parse(segment.meta.object_key())?;
            support::install_immutable(self.directory.as_ref(), &key, segment.bytes.as_slice())?;
        }

        // Step 4: build and round-trip-validate the generation manifest.
        let mut refs: Vec<ManifestSegmentRef> = self
            .committed
            .as_ref()
            .map(|state| state.manifest.segments.clone())
            .unwrap_or_default();
        for segment in &new_segments {
            refs.push(segment.to_ref());
        }
        refs.sort_by(|left, right| left.segment_id.cmp(&right.segment_id));
        let manifest = Manifest {
            schema: support::expected_codec_schema(&self.schema, &self.registry)?,
            segments: refs,
            required_features: self
                .committed
                .as_ref()
                .map(|state| state.manifest.required_features.clone())
                .unwrap_or_default(),
            optional_features: self
                .committed
                .as_ref()
                .map(|state| state.manifest.optional_features.clone())
                .unwrap_or_default(),
        };
        let manifest_bytes = manifest.encode()?;
        if manifest_bytes.len() as u64 > self.limits.max_manifest_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: self.limits.max_manifest_bytes(),
                requested: manifest_bytes.len() as u64,
            });
        }
        let _ = Manifest::decode(&manifest_bytes, self.limits.segment_limits())?;
        let manifest_key = StorageKey::parse(manifest_key_for(generation))?;
        support::install_immutable(self.directory.as_ref(), &manifest_key, &manifest_bytes)?;

        // Step 5: publish CURRENT last, atomically.
        let pointer = CurrentPointer::new(
            generation,
            manifest_bytes.len() as u64,
            ContentDigest::sha256_v1(&manifest_bytes),
        )?;
        let current_key = StorageKey::parse(CURRENT_KEY)?;
        let current_bytes = pointer.encode()?;
        match self.directory.atomic_write(&current_key, &current_bytes) {
            // Step 6: acknowledge only after durable success.
            Ok(()) => {
                self.finish_commit(
                    generation,
                    manifest,
                    new_segments,
                    segments_added,
                    doc_total,
                );
                Ok(CommitOutcome {
                    generation,
                    documents: doc_total,
                    segments_added,
                    no_op: false,
                })
            }
            // Steps 7/8: reconcile the indeterminate outcome.
            Err(error) => self.reconcile_current_failure(error, previous_generation, generation),
        }
    }

    fn finish_commit(
        &mut self,
        generation: u64,
        manifest: Manifest,
        new_segments: Vec<PendingSegment>,
        segments_added: u64,
        doc_total: u64,
    ) {
        let mut segments = self
            .committed
            .as_ref()
            .map(|state| state.segments.clone())
            .unwrap_or_default();
        segments.extend(new_segments.iter().map(PendingSegment::snapshot));
        let mut keys = self
            .committed
            .as_ref()
            .map(|state| state.keys.clone())
            .unwrap_or_default();
        for segment in &new_segments {
            for key in &segment.keys {
                keys.insert(key.clone());
            }
        }
        self.committed = Some(CommittedState {
            generation,
            manifest,
            segments,
            keys,
        });
        self.pending.clear();
        self.pending_bytes = 0;
        self.uncommitted_keys.clear();
        self.flushed.clear();
        self.poisoned = false;
        let snapshot = self.committed_snapshot();
        self.published = Some(snapshot);
        debug_assert_eq!(
            self.committed
                .as_ref()
                .map(|state| state.keys.len())
                .unwrap_or(0),
            self.committed
                .as_ref()
                .map(|state| state.segments.iter().map(|s| s.doc_count()).sum::<u64>())
                .unwrap_or(0) as usize,
        );
        let _ = (segments_added, doc_total);
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

    fn is_duplicate(&self, key: &DocumentKey) -> bool {
        self.uncommitted_keys.contains(key)
            || self
                .committed
                .as_ref()
                .is_some_and(|state| state.keys.contains(key))
    }

    fn build_pending_segment(&self) -> IndexResult<PendingSegment> {
        let built = support::build_segment(&self.schema, &self.registry, &self.pending)?;
        let bytes = Arc::new(built.bytes);
        let (meta, doc_count) = support::meta_from_bytes(self.limits.segment_limits(), &bytes)?;
        let keys = self.pending.iter().map(|doc| doc.key.clone()).collect();
        Ok(PendingSegment {
            meta,
            bytes,
            keys,
            doc_count,
        })
    }

    fn committed_snapshot(&self) -> Arc<ReaderSnapshot> {
        let segments = self
            .committed
            .as_ref()
            .map(|state| state.segments.clone())
            .unwrap_or_default();
        let generation = self.committed.as_ref().map(|state| state.generation);
        Arc::new(ReaderSnapshot::new(
            generation,
            self.next_view,
            segments,
            *self.limits.segment_limits(),
            Arc::clone(&self.pins),
            self.limits.max_snapshot_bytes(),
        ))
    }
}

impl std::fmt::Debug for IndexWriter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IndexWriter")
            .field("generation", &self.generation())
            .field("pending", &self.pending.len())
            .field("flushed", &self.flushed.len())
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
