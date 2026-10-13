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

mod current;
mod error;
mod limits;
mod pit;
mod snapshot;
mod support;
mod writer;

pub use current::{
    CURRENT_KEY, CURRENT_MAX_BYTES, CURRENT_VERSION, CurrentPointer, WRITER_LOCK_KEY,
    manifest_key_for, segment_key_for_hex,
};
pub use error::{IndexError, IndexResult};
pub use limits::IndexLimits;
pub use pit::PitHandle;
pub use snapshot::{ReaderSnapshot, SegmentMeta, SegmentSnapshot};
pub use writer::{CommitOutcome, FlushOutcome, IndexWriter};

use std::collections::BTreeSet;
use std::sync::Arc;

use quervant_objectstore::{ContentDescriptor, ContentDigest};

use crate::analysis::AnalyzerRegistry;
use crate::contract::document::DocumentKey;
use crate::contract::schema::Schema;
use crate::segment::{Manifest, SegmentReader};
use crate::storage::{Directory, StorageKey};

use pit::PinCounter;

/// The verified committed state of an index generation.
#[derive(Clone)]
pub(crate) struct CommittedState {
    pub(crate) generation: u64,
    pub(crate) manifest: Manifest,
    pub(crate) segments: Vec<SegmentSnapshot>,
    pub(crate) keys: BTreeSet<DocumentKey>,
}

/// A handle to a local index.
///
/// `Index` is an opener/factory: [`Index::writer`] constructs a single
/// cooperating [`IndexWriter`] from the committed state visible when it was
/// created. Commits update the writer's state; reopen the index to observe a
/// new generation from a fresh `Index`.
pub struct Index {
    directory: Arc<dyn Directory>,
    schema: Schema,
    registry: AnalyzerRegistry,
    limits: IndexLimits,
    pins: Arc<PinCounter>,
    committed: Option<CommittedState>,
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
        let pins = PinCounter::new(limits.max_pinned_pits());
        Ok(Self {
            directory,
            schema,
            registry,
            limits,
            pins,
            committed: None,
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
        let pins = PinCounter::new(limits.max_pinned_pits());
        Ok(Self {
            directory,
            schema,
            registry,
            limits,
            pins,
            committed: Some(committed),
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
    /// Fails with [`IndexError::WriterBusy`] if another writer already holds
    /// `index/WRITER_LOCK`.
    pub fn writer(&self) -> IndexResult<IndexWriter> {
        IndexWriter::open(
            Arc::clone(&self.directory),
            self.schema.clone(),
            self.registry.clone(),
            self.limits.clone(),
            Arc::clone(&self.pins),
            self.committed.clone(),
        )
    }

    /// An immutable snapshot of the currently committed generation.
    #[must_use]
    pub fn snapshot(&self) -> Arc<ReaderSnapshot> {
        let segments = self
            .committed
            .as_ref()
            .map(|state| state.segments.clone())
            .unwrap_or_default();
        let generation = self.committed.as_ref().map(|state| state.generation);
        Arc::new(ReaderSnapshot::new(
            generation,
            0,
            segments,
            *self.limits.segment_limits(),
            Arc::clone(&self.pins),
        ))
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
    let mut segments = Vec::with_capacity(manifest.segments.len());
    let mut keys = BTreeSet::new();
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
        let reader = SegmentReader::open(bytes.clone(), *limits.segment_limits())?;
        let doc_count = reader.doc_count();
        for record in reader.stored()?.iter() {
            if !keys.insert(record.key.clone()) {
                return Err(IndexError::CorruptCommittedState {
                    detail: format!("duplicate committed document key: {}", record.key),
                });
            }
        }
        let meta = SegmentMeta::new(
            reference.segment_id.clone(),
            reference.object_key.clone(),
            descriptor,
            reference.required_features.clone(),
            reference.optional_features.clone(),
            reference.time_bounds,
        );
        segments.push(SegmentSnapshot::new(meta, Arc::new(bytes), doc_count));
    }
    Ok(CommittedState {
        generation: pointer.generation(),
        manifest,
        segments,
        keys,
    })
}
