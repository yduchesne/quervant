//! Local index lifecycle: writer, durable generations, refresh and PIT (PR 6).
//!
//! `Index` opens or creates a **local-only** single-writer index over an
//! existing [`crate::storage::Directory`]. It reuses the validated document and
//! analyzer contracts, the immutable segment/manifest codecs and the storage
//! seam. It deliberately does **not** provide query execution, mutations,
//! merges, garbage collection, remote ObjectStore publication or distributed
//! coordination.
//!
//! Central rule: **durable commit requires persisted immutable segments, a
//! persisted manifest and durable atomic publication of `CURRENT`; refresh is a
//! separate, non-durable reader-visibility boundary.**
//!
//! ```text
//! validated Document -> IndexWriter -> pending batch -> SegmentBuilder
//!                          | flush: staged immutable segment, no visibility
//!                          | refresh: volatile immutable snapshot -> PIT
//!                          | commit: synced segment -> synced manifest
//!                                    -> atomic CURRENT -> durable snapshot
//! ```
//!
//! An `Index` handle is a read-only snapshot of the generation visible when it
//! was opened. It is **not** writer authority: every new [`IndexWriter`]
//! acquires the cooperative lock and then reloads the authoritative `CURRENT`
//! while holding it, so a stale handle can never lose intervening commits.

mod current;
mod error;
mod limits;
mod merge;
mod mutation_state;
mod pit;
mod reclaim;
mod snapshot;
pub(crate) mod support;
mod visibility;
mod writer;

#[cfg(test)]
mod amendment01;

pub use current::{
    CURRENT_KEY, CURRENT_MAX_BYTES, CURRENT_VERSION, CurrentPointer, WRITER_LOCK_KEY,
    manifest_key_for, segment_key_for_hex,
};
pub use error::{IndexError, IndexResult};
pub use limits::IndexLimits;
pub use merge::MergeOutcome;
pub use pit::PitHandle;
pub use reclaim::{ObjectClass, ObjectRef, ReclamationPlan};
pub use snapshot::{GuardedSegmentReader, ReaderSnapshot, SegmentMeta, SegmentSnapshot};
pub use writer::{CommitOutcome, FlushOutcome, IndexWriter, RetentionOutcome};

use std::collections::BTreeMap;
use std::sync::Arc;

use quervant_objectstore::{ContentDescriptor, ContentDigest};

use crate::analysis::AnalyzerRegistry;
use crate::contract::document::DocumentKey;
use crate::contract::schema::Schema;
use crate::segment::{Manifest, SegmentReader};
use crate::storage::{Directory, StorageKey};

use mutation_state::{KeyRow, MutationStateV1};
use pit::PinCounter;

/// The verified committed state of an index generation.
#[derive(Clone)]
pub(crate) struct CommittedState {
    pub(crate) generation: u64,
    pub(crate) manifest: Manifest,
    pub(crate) segments: Vec<SegmentSnapshot>,
    pub(crate) state: Arc<MutationStateV1>,
    pub(crate) masks: Vec<Option<Arc<Vec<bool>>>>,
}

/// Whether an `Index` handle was created empty or opened from an existing
/// `CURRENT`. This determines whether a missing `CURRENT` is valid for a new
/// writer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum IndexOrigin {
    /// `Index::create*`: no `CURRENT` yet is the expected initial state.
    CreatedEmpty,
    /// `Index::open*`: a missing `CURRENT` is an error.
    OpenedExisting,
}

/// A handle to a local index.
///
/// `Index` is an opener/factory and a read-only snapshot handle. The committed
/// state it exposes is fixed at open time; [`Index::writer`] always reloads the
/// authoritative `CURRENT` under the writer lock rather than trusting this
/// cache.
pub struct Index {
    directory: Arc<dyn Directory>,
    schema: Schema,
    registry: AnalyzerRegistry,
    limits: IndexLimits,
    pins: Arc<PinCounter>,
    committed: Option<CommittedState>,
    origin: IndexOrigin,
}

impl Index {
    /// Create a fresh, uncommitted local index with published default limits.
    ///
    /// Fails with [`IndexError::AlreadyInitialized`] if `CURRENT` already
    /// exists. The first [`IndexWriter::commit`] creates generation 1.
    pub fn create(
        directory: Arc<dyn Directory>,
        schema: Schema,
        registry: AnalyzerRegistry,
    ) -> IndexResult<Self> {
        Self::create_with_limits(directory, schema, registry, IndexLimits::default())
    }

    /// Create a fresh, uncommitted local index with explicit limits.
    pub fn create_with_limits(
        directory: Arc<dyn Directory>,
        schema: Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
    ) -> IndexResult<Self> {
        let current = StorageKey::parse(CURRENT_KEY)?;
        if directory.exists(&current)? {
            return Err(IndexError::AlreadyInitialized);
        }
        support::ensure_layout(directory.as_ref())?;
        // Resolve analyzer bindings fail-closed before returning.
        let _ = support::expected_codec_schema(&schema, &registry)?;
        let pins = PinCounter::new(limits.max_pinned_pits())?;
        Ok(Self {
            directory,
            schema,
            registry,
            limits,
            pins,
            committed: None,
            origin: IndexOrigin::CreatedEmpty,
        })
    }

    /// Open an existing local index, resolving **only** `CURRENT`.
    ///
    /// Returns [`IndexError::NotInitialized`] when `CURRENT` is absent.
    /// Corruption or a missing referenced object is a typed error with no
    /// fallback to an older generation.
    pub fn open_existing(
        directory: Arc<dyn Directory>,
        schema: Schema,
        registry: AnalyzerRegistry,
    ) -> IndexResult<Self> {
        Self::open_with_limits(directory, schema, registry, IndexLimits::default())
    }

    /// Open an existing local index with explicit limits.
    pub fn open_with_limits(
        directory: Arc<dyn Directory>,
        schema: Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
    ) -> IndexResult<Self> {
        let committed = load_committed(directory.as_ref(), &schema, &registry, &limits)?;
        let pins = PinCounter::new(limits.max_pinned_pits())?;
        Ok(Self {
            directory,
            schema,
            registry,
            limits,
            pins,
            committed: Some(committed),
            origin: IndexOrigin::OpenedExisting,
        })
    }

    /// Alias for [`Index::open_existing`] emphasizing `CURRENT`-only resolution.
    pub fn open_committed(
        directory: Arc<dyn Directory>,
        schema: Schema,
        registry: AnalyzerRegistry,
    ) -> IndexResult<Self> {
        Self::open_existing(directory, schema, registry)
    }

    /// The committed generation, if any.
    #[must_use]
    pub fn generation(&self) -> Option<u64> {
        self.committed.as_ref().map(|state| state.generation)
    }

    /// The configured limits.
    #[must_use]
    pub const fn limits(&self) -> &IndexLimits {
        &self.limits
    }

    /// The supplied contract schema.
    #[must_use]
    pub const fn schema(&self) -> &Schema {
        &self.schema
    }

    /// The supplied analyzer registry.
    #[must_use]
    pub const fn registry(&self) -> &AnalyzerRegistry {
        &self.registry
    }

    /// Construct the single cooperating writer.
    ///
    /// Acquires `index/WRITER_LOCK` and then reloads the authoritative
    /// `CURRENT`, so the returned writer never uses this handle's cached
    /// committed state. Fails with [`IndexError::WriterBusy`] if another writer
    /// already holds the lock.
    pub fn writer(&self) -> IndexResult<IndexWriter> {
        IndexWriter::open(
            Arc::clone(&self.directory),
            self.schema.clone(),
            self.registry.clone(),
            self.limits.clone(),
            Arc::clone(&self.pins),
            self.origin,
        )
    }

    /// An immutable snapshot of the generation committed when this handle was
    /// opened. It does not track later writers; reopen to observe a new
    /// generation.
    #[must_use]
    pub fn snapshot(&self) -> Arc<ReaderSnapshot> {
        let segments = self
            .committed
            .as_ref()
            .map(|state| state.segments.clone())
            .unwrap_or_default();
        let masks = self
            .committed
            .as_ref()
            .map(|state| state.masks.clone())
            .unwrap_or_else(|| vec![None; segments.len()]);
        let generation = self.committed.as_ref().map(|state| state.generation);
        let snapshot = ReaderSnapshot::new_with_masks(
            generation,
            0,
            segments,
            masks,
            *self.limits.segment_limits(),
            Arc::clone(&self.pins),
            self.limits.max_snapshot_bytes(),
        )
        .expect("committed snapshot masks are validated before publication");
        Arc::new(snapshot)
    }

    /// Pin the committed snapshot as a point-in-time handle.
    pub fn pin(&self) -> IndexResult<PitHandle> {
        pit::pin(&self.snapshot())
    }

    /// The current number of pinned PIT handles.
    #[must_use]
    pub fn pinned_pits(&self) -> usize {
        self.pins.pinned()
    }

    /// Build a conservative dry-run reclamation plan. Never deletes anything.
    pub fn reclamation_plan(&self) -> IndexResult<ReclamationPlan> {
        reclaim::plan_reclamation(self.directory.as_ref(), &self.limits)
    }
}

impl std::fmt::Debug for Index {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Index")
            .field("generation", &self.generation())
            .field("pinned_pits", &self.pins.pinned())
            .finish()
    }
}

fn load_committed(
    directory: &dyn Directory,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: &IndexLimits,
) -> IndexResult<CommittedState> {
    let Some(pointer) = support::read_current(directory)? else {
        return Err(IndexError::NotInitialized);
    };
    load_committed_at(directory, schema, registry, limits, pointer)
}

/// Load the committed state referenced by an already-parsed `CURRENT` pointer.
///
/// `IndexWriter::open` calls this with the single pointer it read under the
/// writer lock, avoiding a second `CURRENT` read/TOCTOU window.
pub(crate) fn load_committed_at(
    directory: &dyn Directory,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    limits: &IndexLimits,
    pointer: CurrentPointer,
) -> IndexResult<CommittedState> {
    let descriptor = ContentDescriptor::new(pointer.manifest_length(), pointer.manifest_digest());
    let manifest_bytes = support::read_verified(
        directory,
        pointer.manifest_key(),
        descriptor,
        limits.max_manifest_bytes(),
    )?;
    let manifest = Manifest::decode(&manifest_bytes, limits.segment_limits())?;
    let expected = support::expected_codec_schema(schema, registry)?;
    if manifest.schema != expected {
        return Err(IndexError::SchemaMismatch {
            detail:
                "committed schema/analyzer bindings differ from the supplied schema and registry"
                    .to_owned(),
        });
    }

    // Aggregate preflight: bound every declared segment and the running total
    // BEFORE allocating the segment vector or opening any segment. This refuses
    // a committed generation whose combined resident bytes exceed the snapshot
    // budget, and refuses `u64` overflow, with no partial snapshot.
    let _declared_total = support::bounded_segment_total(
        manifest
            .segments
            .iter()
            .map(|reference| reference.content_length),
        limits.segment_limits().accepted_segment_bytes(),
        limits.max_snapshot_bytes(),
    )?;

    let mut segments: Vec<SegmentSnapshot> = Vec::new();
    segments
        .try_reserve_exact(manifest.segments.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: limits.max_snapshot_bytes(),
            requested: u64::try_from(manifest.segments.len()).unwrap_or(u64::MAX),
        })?;
    let mut readers: Vec<SegmentReader> = Vec::new();
    readers
        .try_reserve_exact(manifest.segments.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: limits.max_snapshot_bytes(),
            requested: u64::try_from(manifest.segments.len()).unwrap_or(u64::MAX),
        })?;
    let mut loaded_total: u64 = 0;
    for reference in &manifest.segments {
        let key = StorageKey::parse(&reference.object_key)?;
        let descriptor = ContentDescriptor::new(
            reference.content_length,
            ContentDigest::from_sha256_v1_bytes(reference.content_digest),
        );
        let bytes = support::read_verified(
            directory,
            &key,
            descriptor,
            limits.segment_limits().accepted_segment_bytes(),
        )?;
        // Re-check cumulative verified bytes as reads complete.
        loaded_total =
            loaded_total
                .checked_add(bytes.len() as u64)
                .ok_or(IndexError::ResourceLimit {
                    limit: limits.max_snapshot_bytes(),
                    requested: u64::MAX,
                })?;
        if loaded_total > limits.max_snapshot_bytes() {
            return Err(IndexError::ResourceLimit {
                limit: limits.max_snapshot_bytes(),
                requested: loaded_total,
            });
        }
        let reader = SegmentReader::open(bytes.clone(), *limits.segment_limits())?;
        let doc_count = reader.doc_count();
        let meta = SegmentMeta::new(
            reference.segment_id.clone(),
            reference.object_key.clone(),
            descriptor,
            reference.required_features.clone(),
            reference.optional_features.clone(),
            reference.time_bounds,
        );
        segments.push(SegmentSnapshot::new(meta, Arc::new(bytes), doc_count));
        readers.push(reader);
    }

    let state = match &manifest.mutation_state {
        Some(reference) => {
            let key = StorageKey::parse(&reference.object_key)?;
            let descriptor = ContentDescriptor::new(
                reference.content_length,
                ContentDigest::from_sha256_v1_bytes(reference.content_digest),
            );
            let state_bytes = support::read_verified(
                directory,
                &key,
                descriptor,
                limits.max_mutation_state_bytes(),
            )?;
            let decoded = MutationStateV1::decode(&state_bytes, limits.segment_limits())?;
            let total_replay = decoded
                .replay_count()
                .checked_add(decoded.batch_replay_count())
                .ok_or(IndexError::ResourceLimit {
                    limit: limits.max_replay_entries(),
                    requested: u64::MAX,
                })?;
            if total_replay as u64 > limits.max_replay_entries() {
                return Err(IndexError::ResourceLimit {
                    limit: limits.max_replay_entries(),
                    requested: total_replay as u64,
                });
            }
            if decoded.replay_bytes_total() > limits.max_replay_bytes() {
                return Err(IndexError::ResourceLimit {
                    limit: limits.max_replay_bytes(),
                    requested: decoded.replay_bytes_total(),
                });
            }
            if decoded.batch_replay_key_count() as u64 > limits.max_batch_replay_keys() {
                return Err(IndexError::ResourceLimit {
                    limit: limits.max_batch_replay_keys(),
                    requested: decoded.batch_replay_key_count() as u64,
                });
            }
            Arc::new(decoded)
        }
        None => Arc::new(synthesize_legacy_state(&segments, &readers)?),
    };
    let masks = visibility::build_masks_from_readers(&state, &segments, &readers)?;
    Ok(CommittedState {
        generation: pointer.generation(),
        manifest,
        segments,
        state,
        masks,
    })
}

/// Synthesize the initial all-live revision-1 state for a legacy v1 manifest.
///
/// Legacy generations declare no tombstones and were written under the insert
/// uniqueness invariant, so duplicate physical logical keys are corruption.
fn synthesize_legacy_state(
    segments: &[SegmentSnapshot],
    readers: &[SegmentReader],
) -> IndexResult<MutationStateV1> {
    let mut rows: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
    for (index, reader) in readers.iter().enumerate() {
        let segment_id = segments[index].meta().segment_id().to_owned();
        for (doc_id, key) in reader.doc_keys()?.iter().enumerate() {
            if rows.contains_key(key) {
                return Err(IndexError::CorruptCommittedState {
                    detail: format!("duplicate committed document key: {key}"),
                });
            }
            rows.insert(
                key.clone(),
                KeyRow::live(key.clone(), 1, segment_id.clone(), doc_id as u64),
            );
        }
    }
    Ok(MutationStateV1::from_parts(rows, BTreeMap::new()))
}
