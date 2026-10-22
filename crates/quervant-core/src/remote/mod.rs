//! Opt-in remote-backed single-shard index mode (PR 13).
//!
//! Authoritative durable committed objects live in a provider-neutral
//! [`ObjectStore`] (for example RustFS via the S3 adapter). A private local
//! [`FsDirectory`] workspace holds only disposable, verified materializations;
//! the remote `CURRENT` alone selects the committed generation.
//!
//! This module reuses the **existing** immutable codecs, the existing local
//! single-writer lifecycle and the existing verified [`SegmentCache`]. It adds
//! no persisted format, no distributed dependency and no query evaluator.
//!
//! ```text
//! RemoteIndexWriter -> existing IndexWriter in a private workspace
//!                    -> immutable segments/state/manifest -> ObjectStore
//!                    -> CAS remote index/CURRENT  (last)
//! RemoteIndex        -> remote CURRENT -> verified manifest/state
//!                    -> SegmentCache + bounded transfer
//!                    -> verified local FsDirectory -> existing Index
//! ```

pub mod config;
mod publication;
mod transfer;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use quervant_objectstore::{
    ContentDescriptor, ContentDigest, ObjectKey, ObjectStore, ObjectStoreError, TransferLimits,
};

use crate::analysis::AnalyzerRegistry;
use crate::analysis::Cancellation;
use crate::contract::document::{Document, MutationRequest, MutationResponse};
use crate::contract::mutation::{MutationBatch, MutationBatchResponse};
use crate::contract::schema::Schema;
use crate::index::{
    CURRENT_KEY, CURRENT_MAX_BYTES, CommitOutcome, CurrentPointer, FlushOutcome, Index, IndexError,
    IndexLimits, IndexResult, IndexWriter, PitHandle, ReaderSnapshot,
};
use crate::segment::Manifest;
use crate::storage::{
    CacheConfig, Directory, FsDirectory, PinnedSegment, SegmentCache, SegmentDescriptor,
    StorageError, StorageKey,
};

pub use config::{
    HARD_CHUNK_SIZE, HARD_MAX_AGGREGATE_RESPONSE_BYTES, HARD_MAX_CONCURRENT_RANGES,
    HARD_MAX_CONCURRENT_SEGMENT_FILLS, HARD_MAX_RETRIES, HARD_MAX_TEMP_DISK_BYTES,
    HARD_MAX_TOTAL_HTTP_REQUESTS, HARD_RANGE_THRESHOLD, HARD_REQUEST_TIMEOUT, RemoteConfig,
    RemoteKeyPrefix, RemoteTransferConfig,
};
use transfer::TransferBudget;
pub use transfer::TransferStats;

/// Monotonic id assigning each writer a distinct private workspace.
static WRITER_SEQ: AtomicU64 = AtomicU64::new(0);

use publication::{RemoteBase, collect_candidate};

/// The result of hydrating authoritative remote committed state into a
/// disposable local workspace.
struct Hydrated {
    generation: Option<u64>,
    base: RemoteBase,
    pins: Vec<PinnedSegment>,
}

/// A remote-backed index handle: an opener plus a read-only committed snapshot.
pub struct RemoteIndex<S: ObjectStore + 'static> {
    store: Arc<S>,
    config: RemoteConfig,
    schema: Schema,
    registry: AnalyzerRegistry,
    limits: IndexLimits,
    index: Index,
    _pins: Vec<PinnedSegment>,
    _cache: SegmentCache<Arc<S>, FsDirectory>,
    stats: Arc<TransferStats>,
}

impl<S: ObjectStore + 'static> RemoteIndex<S> {
    /// Create a fresh, uncommitted remote index.
    ///
    /// Fails with [`IndexError::AlreadyInitialized`] if remote `CURRENT`
    /// already exists. The index becomes durable only after the first
    /// successful [`RemoteIndexWriter::commit`].
    pub async fn create(
        store: Arc<S>,
        config: RemoteConfig,
        schema: Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
    ) -> IndexResult<Self> {
        config.validate()?;
        prepare_workspace(config.reader_dir())?;
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(config.reader_dir())?);
        let current_logical = StorageKey::parse(CURRENT_KEY)?;
        let current_physical = config.prefix().key_for(&current_logical)?;
        match store
            .get(
                &current_physical,
                None,
                &TransferLimits::new(CURRENT_MAX_BYTES as u64),
            )
            .await
        {
            Err(ObjectStoreError::NotFound { .. }) => {}
            Ok(_) => return Err(IndexError::AlreadyInitialized),
            Err(error) => {
                return Err(IndexError::Storage(StorageError::from_object_store(
                    error,
                    &current_logical,
                )));
            }
        }
        let index = Index::create_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            limits.clone(),
        )?;
        let cache = SegmentCache::new(
            Arc::clone(&store),
            FsDirectory::open(config.reader_dir())?,
            cache_config(&config),
        );
        let stats = TransferStats::default();
        Ok(Self {
            store,
            config,
            schema,
            registry,
            limits,
            index,
            _pins: Vec::new(),
            _cache: cache,
            stats: Arc::new(stats),
        })
    }

    /// Open an existing committed remote index.
    ///
    /// Returns [`IndexError::NotInitialized`] when remote `CURRENT` is absent.
    /// A malformed `CURRENT`, a corrupt manifest or a missing referenced object
    /// is a typed failure with no fallback to an older generation.
    pub async fn open_existing(
        store: Arc<S>,
        config: RemoteConfig,
        schema: Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
    ) -> IndexResult<Self> {
        config.validate()?;
        prepare_workspace(config.reader_dir())?;
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(config.reader_dir())?);
        let cache = SegmentCache::new(
            Arc::clone(&store),
            FsDirectory::open(config.reader_dir())?,
            cache_config(&config),
        );
        let budget = TransferBudget::new(config.transfer(), transfer::default_sleeper());
        let stats = budget.stats();
        let hydrated = hydrate(
            &store,
            config.prefix(),
            directory.as_ref(),
            &cache,
            &config,
            &limits,
            &schema,
            &registry,
            &budget,
        )
        .await?
        .ok_or(IndexError::NotInitialized)?;
        let index = Index::open_with_limits(
            Arc::clone(&directory),
            schema.clone(),
            registry.clone(),
            limits.clone(),
        )?;
        Ok(Self {
            store,
            config,
            schema,
            registry,
            limits,
            index,
            _pins: hydrated.pins,
            _cache: cache,
            stats,
        })
    }

    /// An immutable snapshot of the committed generation observed at open time.
    #[must_use]
    pub fn snapshot(&self) -> Arc<ReaderSnapshot> {
        self.index.snapshot()
    }

    /// Pin the observed committed snapshot as a point-in-time handle.
    pub fn pin(&self) -> IndexResult<PitHandle> {
        self.index.pin()
    }

    /// The committed generation observed at open time.
    #[must_use]
    pub fn generation(&self) -> Option<u64> {
        self.index.generation()
    }

    /// The transfer counters for this instance.
    #[must_use]
    pub fn transfer_stats(&self) -> Arc<TransferStats> {
        Arc::clone(&self.stats)
    }

    /// Open the single cooperating remote writer.
    ///
    /// The writer hydrates the authoritative base into a **separate** private
    /// workspace, verifies it with the existing local lifecycle and publishes
    /// only via provider-enforced CAS of remote `CURRENT`.
    pub async fn writer(&self) -> IndexResult<RemoteIndexWriter<S>> {
        RemoteIndexWriter::open(
            Arc::clone(&self.store),
            self.config.clone(),
            self.schema.clone(),
            self.registry.clone(),
            self.limits.clone(),
        )
        .await
    }

    /// The configured remote prefix.
    #[must_use]
    pub const fn prefix(&self) -> &RemoteKeyPrefix {
        self.config.prefix()
    }

    /// The private reader workspace directory.
    #[must_use]
    pub fn workspace_root(&self) -> &std::path::Path {
        self.config.workspace_root()
    }
}

/// A remote-backed single writer whose durability boundary is remote CAS.
///
/// The local writer's `CURRENT` advances before remote publication; this type
/// tracks the remote base separately and becomes terminal on any ambiguous
/// publication, requiring a fresh authoritative reopen.
pub struct RemoteIndexWriter<S: ObjectStore + 'static> {
    store: Arc<S>,
    config: RemoteConfig,
    limits: IndexLimits,
    writer: IndexWriter,
    base: RemoteBase,
    budget: TransferBudget,
    terminal: Option<TerminalState>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TerminalState {
    Conflict,
    Recovery,
}

fn terminal_error(state: TerminalState) -> IndexError {
    match state {
        TerminalState::Conflict => IndexError::RemoteConflict {
            detail: "remote writer is terminal after a publication conflict; reopen the index"
                .to_owned(),
        },
        TerminalState::Recovery => IndexError::RecoveryRequired {
            detail: "remote writer is terminal after an ambiguous publication; reopen the index"
                .to_owned(),
        },
    }
}

fn classify_terminal(error: &IndexError) -> TerminalState {
    match error {
        IndexError::RemoteConflict { .. } | IndexError::ContentConflict { .. } => {
            TerminalState::Conflict
        }
        _ => TerminalState::Recovery,
    }
}

impl<S: ObjectStore + 'static> RemoteIndexWriter<S> {
    /// Open the writer, hydrating the authoritative remote base.
    pub async fn open(
        store: Arc<S>,
        config: RemoteConfig,
        schema: Schema,
        registry: AnalyzerRegistry,
        limits: IndexLimits,
    ) -> IndexResult<Self> {
        config.validate()?;
        let writer_id = WRITER_SEQ.fetch_add(1, Ordering::Relaxed);
        let writer_dir = config.writer_dir_for(writer_id);
        prepare_workspace(writer_dir.clone())?;
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&writer_dir)?);
        let cache = SegmentCache::new(
            Arc::clone(&store),
            FsDirectory::open(&writer_dir)?,
            cache_config(&config),
        );
        let budget = TransferBudget::new(config.transfer(), transfer::default_sleeper());
        let hydrated = hydrate(
            &store,
            config.prefix(),
            directory.as_ref(),
            &cache,
            &config,
            &limits,
            &schema,
            &registry,
            &budget,
        )
        .await?;
        let base = hydrated
            .as_ref()
            .map(|state| state.base.clone())
            .unwrap_or(RemoteBase {
                current_bytes: None,
            });
        let index = match hydrated.as_ref().and_then(|state| state.generation) {
            Some(_) => Index::open_with_limits(
                Arc::clone(&directory),
                schema.clone(),
                registry.clone(),
                limits.clone(),
            )?,
            None => Index::create_with_limits(
                Arc::clone(&directory),
                schema.clone(),
                registry.clone(),
                limits.clone(),
            )?,
        };
        let writer = index.writer()?;
        // The hydration pins are dropped here: the local reader has already
        // copied and verified the bytes, and the writer owns the workspace.
        drop(hydrated);
        Ok(Self {
            store,
            config,
            limits,
            writer,
            base,
            budget,
            terminal: None,
        })
    }

    /// Admit one insert-only document.
    pub fn insert(&mut self, document: Document) -> IndexResult<()> {
        self.ensure_usable()?;
        self.writer.insert(document)
    }

    /// Apply a typed mutation request.
    pub fn apply(&mut self, request: MutationRequest) -> IndexResult<MutationResponse> {
        self.ensure_usable()?;
        self.writer.apply(request)
    }

    /// Apply an ordered, atomic mutation batch.
    ///
    /// This is synchronous delegation to the local workspace planner: it issues
    /// **no** remote I/O and creates no remote-side transaction. Only
    /// [`Self::commit`] publishes remotely.
    pub fn apply_batch(
        &mut self,
        batch: &MutationBatch,
        cancel: &dyn Cancellation,
    ) -> IndexResult<MutationBatchResponse> {
        self.ensure_usable()?;
        self.writer.apply_batch(batch, cancel)
    }

    /// Build the pending batch into one immutable segment without publishing it.
    pub fn flush(&mut self) -> IndexResult<FlushOutcome> {
        self.ensure_usable()?;
        self.writer.flush()
    }

    /// Publish a new volatile immutable reader view.
    pub fn refresh(&mut self) -> IndexResult<Arc<ReaderSnapshot>> {
        self.ensure_usable()?;
        self.writer.refresh()
    }

    /// The latest reader view.
    #[must_use]
    pub fn reader(&self) -> Arc<ReaderSnapshot> {
        self.writer.reader()
    }

    /// Pin the latest reader view.
    pub fn pin(&self) -> IndexResult<PitHandle> {
        self.writer.pin()
    }

    /// Explicit lossless compaction.
    pub fn compact(&mut self) -> IndexResult<crate::index::MergeOutcome> {
        self.ensure_usable()?;
        self.writer.compact()
    }

    /// Fail closed once a remote publication outcome is unresolved.
    fn ensure_usable(&self) -> IndexResult<()> {
        match self.terminal {
            Some(state) => Err(terminal_error(state)),
            None => Ok(()),
        }
    }

    /// The current committed generation, if any.
    #[must_use]
    pub fn generation(&self) -> Option<u64> {
        self.writer.generation()
    }

    /// The transfer counters for this writer's hydration and verification.
    #[must_use]
    pub fn transfer_stats(&self) -> Arc<TransferStats> {
        self.budget.stats()
    }

    /// Durably publish all committed mutations to the remote store.
    ///
    /// Remote durability is acknowledged only after the candidate `CURRENT` is
    /// published by provider-enforced CAS. A local commit that cannot be
    /// published makes the writer terminal; reopen from the authoritative
    /// remote pointer before further writes.
    pub async fn commit(&mut self) -> IndexResult<CommitOutcome> {
        if let Some(state) = self.terminal {
            return Err(terminal_error(state));
        }
        let outcome = match self.writer.commit() {
            Ok(outcome) => outcome,
            Err(error) => {
                self.terminal = Some(classify_terminal(&error));
                return Err(error);
            }
        };
        if outcome.no_op {
            return Ok(outcome);
        }
        // Cancellation-safe window: the local CURRENT has advanced but remote
        // publication has not been confirmed. Poison the writer synchronously,
        // before the first await, so a dropped commit future can never leave a
        // reusable advanced local writer.
        self.terminal = Some(TerminalState::Recovery);
        let candidate = {
            let directory = self.writer.directory();
            let current_key = StorageKey::parse(CURRENT_KEY)?;
            let bytes = crate::index::support::read_bounded(
                directory.as_ref(),
                &current_key,
                CURRENT_MAX_BYTES as u64,
            )?;
            let pointer = CurrentPointer::parse(&bytes)?;
            collect_candidate(directory.as_ref(), &pointer, &self.limits)?
        };
        match publication::publish(
            self.store.as_ref(),
            self.config.prefix(),
            &self.base,
            &candidate,
            CURRENT_MAX_BYTES as u64,
        )
        .await
        {
            Ok(generation) => {
                self.base = RemoteBase {
                    current_bytes: Some(candidate.current_bytes.clone()),
                };
                // Confirmed durable remote publication clears the terminal
                // state.
                self.terminal = None;
                Ok(CommitOutcome {
                    generation,
                    ..outcome
                })
            }
            Err(error) => {
                self.terminal = Some(classify_terminal(&error));
                Err(error)
            }
        }
    }

    /// Explicitly release the cooperating-writer lock.
    pub fn close(self) -> IndexResult<()> {
        self.writer.close()
    }
}

fn cache_config(config: &RemoteConfig) -> CacheConfig {
    CacheConfig::new(
        config.cache().max_cache_bytes,
        config.effective_max_concurrent_fills(),
        config.effective_max_response_bytes(),
    )
}

fn prepare_workspace(path: std::path::PathBuf) -> IndexResult<()> {
    if path.exists() {
        std::fs::remove_dir_all(&path).map_err(|error| {
            IndexError::Storage(StorageError::io(crate::storage::StorageOp::Delete, error))
        })?;
    }
    std::fs::create_dir_all(&path).map_err(|error| {
        IndexError::Storage(StorageError::io(
            crate::storage::StorageOp::CreateDir,
            error,
        ))
    })
}

/// Fetch and verify one small metadata object.
async fn fetch_verified<S: ObjectStore>(
    store: &S,
    physical: &ObjectKey,
    logical: &StorageKey,
    descriptor: ContentDescriptor,
    max: u64,
) -> Result<Vec<u8>, StorageError> {
    if descriptor.length > max {
        return Err(StorageError::LimitExceeded {
            limit: max,
            requested: descriptor.length,
        });
    }
    let limits = TransferLimits::new(descriptor.length.max(1));
    let bytes = store
        .get(physical, None, &limits)
        .await
        .map_err(|error| StorageError::from_object_store(error, logical))?;
    if bytes.len() as u64 != descriptor.length {
        return Err(StorageError::LengthMismatch {
            key: logical.clone(),
            expected: descriptor.length,
            actual: bytes.len() as u64,
        });
    }
    let actual = ContentDigest::sha256_v1(&bytes);
    if actual != descriptor.digest {
        return Err(StorageError::IntegrityMismatch {
            key: logical.clone(),
            expected: descriptor.digest,
            actual,
        });
    }
    Ok(bytes)
}

/// Hydrate authoritative remote committed state into a bounded local workspace.
#[allow(clippy::too_many_arguments)]
async fn hydrate<S: ObjectStore + 'static>(
    store: &Arc<S>,
    prefix: &RemoteKeyPrefix,
    directory: &dyn Directory,
    cache: &SegmentCache<Arc<S>, FsDirectory>,
    config: &RemoteConfig,
    limits: &IndexLimits,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    budget: &TransferBudget,
) -> IndexResult<Option<Hydrated>> {
    crate::index::support::ensure_layout(directory)?;
    let current_logical = StorageKey::parse(CURRENT_KEY)?;
    let current_physical = prefix.key_for(&current_logical)?;
    let current_bytes = match store
        .get(
            &current_physical,
            None,
            &TransferLimits::new(CURRENT_MAX_BYTES as u64),
        )
        .await
    {
        Ok(bytes) => bytes,
        Err(ObjectStoreError::NotFound { .. }) => return Ok(None),
        Err(error) => {
            return Err(IndexError::Storage(StorageError::from_object_store(
                error,
                &current_logical,
            )));
        }
    };
    let pointer = CurrentPointer::parse(&current_bytes)?;

    // Manifest first: schema/analyzer bindings and aggregate bounds are checked
    // before any segment download.
    let manifest_logical = pointer.manifest_key().clone();
    let manifest_physical = prefix.key_for(&manifest_logical)?;
    let manifest_descriptor =
        ContentDescriptor::new(pointer.manifest_length(), pointer.manifest_digest());
    let manifest_bytes = fetch_verified(
        store.as_ref(),
        &manifest_physical,
        &manifest_logical,
        manifest_descriptor,
        limits.max_manifest_bytes(),
    )
    .await?;
    let manifest = Manifest::decode(&manifest_bytes, limits.segment_limits())?;
    let expected = crate::index::support::expected_codec_schema(schema, registry)?;
    if manifest.schema != expected {
        return Err(IndexError::SchemaMismatch {
            detail: "remote committed schema/analyzer bindings differ".to_owned(),
        });
    }
    let declared_total = crate::index::support::bounded_segment_total(
        manifest
            .segments
            .iter()
            .map(|reference| reference.content_length),
        limits.segment_limits().accepted_segment_bytes(),
        limits.max_snapshot_bytes(),
    )?;
    if declared_total > config.transfer().max_temp_disk_bytes() {
        return Err(IndexError::ResourceLimit {
            limit: config.transfer().max_temp_disk_bytes(),
            requested: declared_total,
        });
    }

    // Fetch the optional mutation-state sidecar (bounded).
    let mut state_bytes = None;
    if let Some(state_ref) = &manifest.mutation_state {
        let logical = StorageKey::parse(&state_ref.object_key)?;
        let physical = prefix.key_for(&logical)?;
        let descriptor = ContentDescriptor::new(
            state_ref.content_length,
            ContentDigest::from_sha256_v1_bytes(state_ref.content_digest),
        );
        let bytes = fetch_verified(
            store.as_ref(),
            &physical,
            &logical,
            descriptor,
            limits.max_mutation_state_bytes(),
        )
        .await?;
        state_bytes = Some((logical, bytes));
    }

    // Materialize every segment through the shared bounded transfer and the
    // existing cache admission/promotion path.
    let mut pins = Vec::with_capacity(manifest.segments.len());
    for reference in &manifest.segments {
        let logical = StorageKey::parse(&reference.object_key)?;
        let physical = prefix.key_for(&logical)?;
        let object_key = ObjectKey::parse(reference.object_key.clone())
            .map_err(|reason| StorageError::InvalidKey { reason })?;
        let descriptor = ContentDescriptor::new(
            reference.content_length,
            ContentDigest::from_sha256_v1_bytes(reference.content_digest),
        );
        let segment = SegmentDescriptor::new(object_key, descriptor);
        let destination = logical.clone();
        let fetch_physical = physical.clone();
        let fetch_logical = logical.clone();
        let pin = Box::pin(cache.prepare_remote(&segment, destination, move |sink| {
            let physical = fetch_physical.clone();
            let logical = fetch_logical.clone();
            async move {
                transfer::fetch_to_stage(
                    store.as_ref(),
                    &physical,
                    descriptor,
                    config.transfer(),
                    budget,
                    &logical,
                    &sink,
                )
                .await
            }
        }))
        .await?;
        pins.push(pin);
    }

    // Publish metadata into the workspace with CURRENT last.
    if let Some((logical, bytes)) = state_bytes {
        directory.atomic_write(&logical, &bytes)?;
    }
    directory.atomic_write(pointer.manifest_key(), &manifest_bytes)?;
    directory.atomic_write(&current_logical, &current_bytes)?;

    Ok(Some(Hydrated {
        generation: Some(pointer.generation()),
        base: RemoteBase {
            current_bytes: Some(current_bytes),
        },
        pins,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use quervant_objectstore::{FakeObjectStore, FaultKind, ObjectStoreCapabilities};
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    use crate::analysis::AnalyzerRegistry;
    use crate::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::storage::cache::StagedWriter;

    static DIRS: AtomicU64 = AtomicU64::new(0);

    fn temp_workspace(name: &str) -> PathBuf {
        let n = DIRS.fetch_add(1, Ordering::SeqCst);
        std::env::temp_dir().join(format!("quervant-remote-{}-{name}-{n}", std::process::id()))
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
            ],
            None,
        )
        .unwrap()
    }

    fn registry() -> AnalyzerRegistry {
        AnalyzerRegistry::builtin()
    }

    fn document(key: &str, title: &str) -> Document {
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text(title.to_owned())),
            )
            .unwrap();
        document
    }

    fn config(name: &str) -> RemoteConfig {
        RemoteConfig::new(
            RemoteKeyPrefix::parse(format!("remote/{name}")).unwrap(),
            temp_workspace(name),
        )
        .with_transfer(
            RemoteTransferConfig::default()
                .with_range_threshold(1024 * 1024)
                .with_chunk_size(64 * 1024)
                .with_max_aggregate_response_bytes(4 * 1024 * 1024)
                .with_max_total_http_requests(64)
                .with_max_concurrent_ranges(16)
                .with_max_concurrent_segment_fills(4),
        )
    }

    fn block_on<F: std::future::Future>(future: F) -> F::Output {
        futures::executor::block_on(future)
    }

    /// A fake advertising the qualified remote capability set (atomic
    /// create-if-absent plus conditional replace).
    fn remote_fake() -> Arc<FakeObjectStore> {
        Arc::new(FakeObjectStore::new(
            ObjectStoreCapabilities::IMMUTABLE_BASELINE.with_conditional_replace(true),
        ))
    }

    #[test]
    fn first_commit_publishes_current_last() {
        let store = remote_fake();
        let config = config("first");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "first")).unwrap();
        let outcome = block_on(writer.commit()).unwrap();
        assert_eq!(outcome.generation, 1);

        // Remote CURRENT exists and points at generation 1.
        let prefix = RemoteKeyPrefix::parse("remote/first").unwrap();
        let current = store
            .object(&prefix.object_key("index/CURRENT").unwrap())
            .unwrap();
        let pointer = CurrentPointer::parse(&current).unwrap();
        assert_eq!(pointer.generation(), 1);

        // A fresh reader with an empty workspace recovers the document.
        let reader = block_on(RemoteIndex::open_existing(
            Arc::clone(&store),
            config,
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        assert_eq!(reader.generation(), Some(1));
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn second_commit_replaces_current_via_cas() {
        let store = remote_fake();
        let config = config("second");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        {
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("a", "one")).unwrap();
            assert_eq!(block_on(writer.commit()).unwrap().generation, 1);
        }
        {
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("b", "two")).unwrap();
            assert_eq!(block_on(writer.commit()).unwrap().generation, 2);
        }
        let prefix = RemoteKeyPrefix::parse("remote/second").unwrap();
        let current = store
            .object(&prefix.object_key("index/CURRENT").unwrap())
            .unwrap();
        assert_eq!(CurrentPointer::parse(&current).unwrap().generation(), 2);
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn missing_current_is_not_initialized() {
        let store = remote_fake();
        let config = config("missing");
        let workspace = config.workspace_root().to_path_buf();
        let result = block_on(RemoteIndex::open_existing(
            store,
            config,
            schema(),
            registry(),
            IndexLimits::default(),
        ));
        assert!(matches!(result, Err(IndexError::NotInitialized)));
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn create_rejects_existing_remote_current() {
        let store = remote_fake();
        let config = config("already");
        let workspace = config.workspace_root().to_path_buf();
        {
            let index = block_on(RemoteIndex::create(
                Arc::clone(&store),
                config.clone(),
                schema(),
                registry(),
                IndexLimits::default(),
            ))
            .unwrap();
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("a", "one")).unwrap();
            block_on(writer.commit()).unwrap();
        }
        let again = block_on(RemoteIndex::create(
            store,
            config,
            schema(),
            registry(),
            IndexLimits::default(),
        ));
        assert!(matches!(again, Err(IndexError::AlreadyInitialized)));
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn two_writers_same_base_one_wins_one_conflicts() {
        let store = remote_fake();
        let config = config("cas-race");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        {
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("base", "base")).unwrap();
            block_on(writer.commit()).unwrap();
        }
        // Two writers both hydrate generation 1.
        let mut left = block_on(index.writer()).unwrap();
        let mut right = block_on(index.writer()).unwrap();
        left.insert(document("l", "left")).unwrap();
        right.insert(document("r", "right")).unwrap();
        assert_eq!(block_on(left.commit()).unwrap().generation, 2);
        let error = block_on(right.commit()).unwrap_err();
        assert!(matches!(error, IndexError::RemoteConflict { .. }));
        // The loser published nothing: CURRENT still points at the winner's
        // generation-2 candidate (C08: same-generation manifest collision).
        let prefix = RemoteKeyPrefix::parse("remote/cas-race").unwrap();
        let current = store
            .object(&prefix.object_key("index/CURRENT").unwrap())
            .unwrap();
        assert_eq!(CurrentPointer::parse(&current).unwrap().generation(), 2);
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn segment_upload_failure_leaves_current_unchanged() {
        let store = remote_fake();
        let config = config("upload-fail");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "one")).unwrap();
        // The next put (a segment) fails before anything is published.
        store.set_put_fault(FaultKind::BeforeWrite);
        let error = block_on(writer.commit()).unwrap_err();
        assert!(matches!(error, IndexError::Storage(_)));
        // A terminal writer rejects every further mutation and commit until a
        // fresh authoritative reopen.
        assert!(writer.insert(document("b", "two")).is_err());
        assert!(writer.flush().is_err());
        assert!(writer.refresh().is_err());
        assert!(block_on(writer.commit()).is_err());
        let prefix = RemoteKeyPrefix::parse("remote/upload-fail").unwrap();
        assert!(
            store
                .object(&prefix.object_key("index/CURRENT").unwrap())
                .is_none()
        );
        let _ = std::fs::remove_dir_all(&workspace);
    }

    // C06: the CAS applied but its response was lost, and CURRENT is readable.
    #[test]
    fn ambiguous_current_publication_reconciles_exact_candidate() {
        let store = remote_fake();
        let config = config("ambiguous-ok");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "one")).unwrap();
        // Puts before CURRENT: one segment, the state sidecar and the manifest.
        // Fail the fourth put (CURRENT) after it has been applied.
        store.set_put_fault_at(4, FaultKind::AfterCommitBeforeAck);
        let outcome = block_on(writer.commit()).unwrap();
        assert_eq!(outcome.generation, 1);
        // The writer is not poisoned: a no-op commit still succeeds.
        assert!(block_on(writer.commit()).unwrap().no_op);
        let _ = std::fs::remove_dir_all(&workspace);
    }

    // C07: the CAS applied, the response was lost, and CURRENT is unreadable.
    #[test]
    fn ambiguous_unreadable_current_requires_recovery() {
        let store = remote_fake();
        let config = config("ambiguous-fail");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "one")).unwrap();
        store.set_put_fault_at(4, FaultKind::AfterCommitBeforeAck);
        // The reconcile GET is the next store read and fails.
        store.set_get_fault(FaultKind::ReadInterrupt);
        let error = block_on(writer.commit()).unwrap_err();
        assert!(matches!(error, IndexError::RecoveryRequired { .. }));
        let second = block_on(writer.commit()).unwrap_err();
        assert!(matches!(second, IndexError::RecoveryRequired { .. }));
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn delete_and_reload_from_remote() {
        let store = remote_fake();
        let config = config("reload");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        {
            let mut writer = block_on(index.writer()).unwrap();
            writer.insert(document("a", "one")).unwrap();
            block_on(writer.commit()).unwrap();
        }
        // Delete the entire workspace and reopen from the fake remote store.
        std::fs::remove_dir_all(config.workspace_root()).unwrap();
        let reader = block_on(RemoteIndex::open_existing(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        assert_eq!(reader.generation(), Some(1));
        // The remote store never received a DELETE.
        assert_eq!(store.delete_calls(), 0);
        let _ = std::fs::remove_dir_all(&workspace);
    }

    #[test]
    fn remote_put_uses_prefixed_keys() {
        let store = remote_fake();
        let config = config("prefix");
        let workspace = config.workspace_root().to_path_buf();
        let index = block_on(RemoteIndex::create(
            Arc::clone(&store),
            config.clone(),
            schema(),
            registry(),
            IndexLimits::default(),
        ))
        .unwrap();
        let mut writer = block_on(index.writer()).unwrap();
        writer.insert(document("a", "one")).unwrap();
        block_on(writer.commit()).unwrap();
        let prefix = RemoteKeyPrefix::parse("remote/prefix").unwrap();
        assert!(
            store
                .object(&prefix.object_key("index/CURRENT").unwrap())
                .is_some()
        );
        assert!(
            store
                .object(&ObjectKey::parse("index/CURRENT").unwrap())
                .is_none()
        );
        let _ = std::fs::remove_dir_all(&workspace);
    }

    fn staging_cache(
        name: &str,
        store: Arc<FakeObjectStore>,
    ) -> (SegmentCache<Arc<FakeObjectStore>, FsDirectory>, PathBuf) {
        let dir = temp_workspace(name);
        std::fs::create_dir_all(dir.join("index/segments")).unwrap();
        let cache = SegmentCache::new(
            store,
            FsDirectory::open(&dir).unwrap(),
            CacheConfig::new(1024 * 1024, 4, 1024 * 1024),
        );
        (cache, dir)
    }

    fn staging_segment(body: &[u8]) -> (SegmentDescriptor, StorageKey) {
        let key = ObjectKey::parse("index/segments/aa.seg").unwrap();
        let descriptor = SegmentDescriptor::new(key, ContentDescriptor::of(body));
        let destination = StorageKey::parse("index/segments/aa.seg").unwrap();
        (descriptor, destination)
    }

    // M06: a warm cache hit performs no redundant remote GET.
    #[test]
    fn m06_warm_cache_hit_performs_no_remote_get() {
        let store = remote_fake();
        let (cache, dir) = staging_cache("m06", Arc::clone(&store));
        let body = vec![9u8; 4096];
        let (segment, destination) = staging_segment(&body);
        let fetches = Arc::new(AtomicU64::new(0));

        let first = {
            let fetches = Arc::clone(&fetches);
            let body = body.clone();
            block_on(
                cache.prepare_remote(&segment, destination.clone(), move |sink| {
                    let body = body.clone();
                    async move {
                        fetches.fetch_add(1, Ordering::SeqCst);
                        sink.write_at(0, body).await
                    }
                }),
            )
            .unwrap()
        };
        assert_eq!(fetches.load(Ordering::SeqCst), 1);
        drop(first);

        let second = {
            let fetches = Arc::clone(&fetches);
            let body = body.clone();
            block_on(cache.prepare_remote(&segment, destination, move |sink| {
                let body = body.clone();
                async move {
                    fetches.fetch_add(1, Ordering::SeqCst);
                    sink.write_at(0, body).await
                }
            }))
            .unwrap()
        };
        assert_eq!(
            fetches.load(Ordering::SeqCst),
            1,
            "warm cache hit must not refetch"
        );
        drop(second);
        cache.shutdown();
        let _ = std::fs::remove_dir_all(&dir);
    }

    // M07: eight simultaneous same-key fills coalesce onto one leader transfer.
    #[test]
    fn m07_concurrent_same_key_fills_run_one_leader_transfer() {
        let store = remote_fake();
        let (cache, dir) = staging_cache("m07", Arc::clone(&store));
        let body = vec![4u8; 8192];
        let (segment, destination) = staging_segment(&body);
        let fetches = Arc::new(AtomicU64::new(0));
        let cache_ref = &cache;
        let futures = (0..8).map(|_| {
            let fetches = Arc::clone(&fetches);
            let body = body.clone();
            let segment = segment.clone();
            let destination = destination.clone();
            async move {
                cache_ref
                    .prepare_remote(&segment, destination, move |sink| {
                        let fetches = Arc::clone(&fetches);
                        let body = body.clone();
                        async move {
                            fetches.fetch_add(1, Ordering::SeqCst);
                            sink.write_at(0, body).await
                        }
                    })
                    .await
            }
        });
        let pins = block_on(futures::future::join_all(futures));
        let pins: Vec<_> = pins.into_iter().map(|pin| pin.unwrap()).collect();
        assert_eq!(pins.len(), 8);
        assert_eq!(
            fetches.load(Ordering::SeqCst),
            1,
            "all same-key fills must coalesce onto one transfer"
        );
        drop(pins);
        cache.shutdown();
        let _ = std::fs::remove_dir_all(&dir);
    }

    // M13: correct length but wrong digest is rejected before publication.
    #[test]
    fn m13_wrong_digest_rejects_before_promotion() {
        let store = remote_fake();
        let (cache, dir) = staging_cache("m13", Arc::clone(&store));
        let body = vec![7u8; 4096];
        let (segment, destination) = staging_segment(&body);
        let wrong = vec![0u8; body.len()];
        let error = block_on(
            cache.prepare_remote(&segment, destination, move |sink| async move {
                sink.write_at(0, wrong).await
            }),
        )
        .unwrap_err();
        assert!(matches!(error, StorageError::IntegrityMismatch { .. }));
        assert_eq!(cache.stats().published_entries, 0);
        assert!(!dir.join("index/segments/aa.seg").exists());
        cache.shutdown();
        let _ = std::fs::remove_dir_all(&dir);
    }
}
