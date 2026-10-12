//! A bounded, verified, pinning local cache over an authoritative ObjectStore.
//!
//! Lifecycle: `Absent -> Filling(temp) -> Verified -> Published -> Leased`.
//! Entries become visible only after full length + SHA-256 verification and
//! atomic local promotion. The cache never deletes authoritative remote
//! objects, and all accounting is hard: `max_cache_bytes` bounds published,
//! reserved in-flight, and temporary bytes together without double counting.
//!
//! # Executor neutrality
//!
//! `prepare` performs remote I/O through the provider-neutral `ObjectStore`
//! contract but never requires a runtime. Coordination between concurrent
//! callers uses waker-based notifications guarded by short, uncontended
//! `std::sync::Mutex` critical sections; it never blocks a worker thread and
//! never holds a lock across `.await` or during filesystem/network I/O.

use std::collections::HashMap;
use std::future::poll_fn;
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Poll, Waker};

use trawler_objectstore::{ContentDescriptor, ContentDigest, ObjectStore, TransferLimits};

use super::io::{OffloadConfig, Offloader};
use super::{
    CorruptionKind, Directory, ReadHandle, SegmentDescriptor, StorageError, StorageKey, StorageOp,
};

/// Cache limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CacheConfig {
    /// Hard upper bound on published + reserved + temporary bytes.
    pub max_cache_bytes: u64,
    /// Maximum number of simultaneous remote fills.
    pub max_concurrent_fills: usize,
    /// Maximum bytes for a single remote response.
    pub max_response_bytes: u64,
}

impl CacheConfig {
    /// Construct a cache configuration.
    ///
    /// # Panics
    ///
    /// Panics if `max_concurrent_fills` is zero.
    #[must_use]
    pub fn new(max_cache_bytes: u64, max_concurrent_fills: usize, max_response_bytes: u64) -> Self {
        assert!(
            max_concurrent_fills > 0,
            "max_concurrent_fills must be positive"
        );
        Self {
            max_cache_bytes,
            max_concurrent_fills,
            max_response_bytes,
        }
    }
}

/// A snapshot of cache accounting.
///
/// `physical_bytes` is a hard bound on the aggregate logical content length of
/// cache-owned regular files plus reserved future growth; it is **not** a bound
/// on filesystem allocation, metadata, unrelated writers or device free space.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CacheStats {
    /// Number of verified, published entries.
    pub published_entries: usize,
    /// Logical bytes held by published entries.
    pub published_bytes: u64,
    /// Bytes reserved for in-flight write growth (temporary files).
    pub reserved_bytes: u64,
    /// Published + orphaned + reserved logical bytes.
    pub physical_bytes: u64,
    /// Logical bytes of cache-owned files with no live published entry.
    pub orphan_bytes: u64,
    /// Number of in-flight fills.
    pub in_flight: usize,
    /// Successful published hits.
    pub hits: u64,
    /// Lookups that did not find a published entry.
    pub misses: u64,
    /// Files evicted by the orphan/LRU policy.
    pub evictions: u64,
    /// Deletes that failed and left a charged file behind.
    pub delete_failures: u64,
    /// Waiters that coalesced onto an existing fill or reconciliation.
    pub coalesced_waiters: u64,
}

/// A cache-owned regular file, whether verified/published or an orphan.
#[derive(Debug)]
struct FileEntry {
    bytes: u64,
    pinned: usize,
    last_used: u64,
    /// Marked while a delete is running; cannot be pinned or reselected.
    evicting: bool,
    /// A delete failed and the file remains charged; not retried automatically.
    delete_failed: bool,
    /// Verified and pinnable when true; charged-but-unverified orphan otherwise.
    published: bool,
}

/// Startup reconciliation state.
#[derive(Debug, Clone, Copy, Default)]
enum Reconciliation {
    #[default]
    Pending,
    InProgress,
    Done(Result<(), FailureKind>),
}

/// Result of the startup scan: `(key, length)` pairs.
type ScanResult = Vec<(StorageKey, u64)>;
type ScanSlot = Arc<Mutex<Option<Result<ScanResult, FailureKind>>>>;

#[derive(Debug, Default)]
struct State {
    files: HashMap<StorageKey, FileEntry>,
    /// Aggregate logical length of every charged cache-owned file.
    known_bytes: u64,
    /// Admitted write growth (temporary bytes) not yet on disk.
    reserved_bytes: u64,
    next_tick: u64,
    in_flight: usize,
    fills: HashMap<StorageKey, Arc<FillSlot>>,
    admission_wakers: Vec<Waker>,
    eviction_wakers: HashMap<StorageKey, Vec<Waker>>,
    reconciliation: Reconciliation,
    reconciliation_wakers: Vec<Waker>,
    hits: u64,
    misses: u64,
    evictions: u64,
    delete_failures: u64,
    coalesced_waiters: u64,
}

#[derive(Debug, Default)]
struct Accounting {
    state: Mutex<State>,
}

impl Accounting {
    fn lock(&self) -> MutexGuard<'_, State> {
        // Tolerate poisoning so no destructor can abort the process.
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

#[derive(Debug)]
struct FillSlot {
    state: Mutex<FillSlotState>,
}

impl FillSlot {
    fn new() -> Self {
        Self {
            state: Mutex::new(FillSlotState {
                status: FillStatus::InProgress,
                wakers: Vec::new(),
            }),
        }
    }

    fn lock(&self) -> MutexGuard<'_, FillSlotState> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

#[derive(Debug)]
struct FillSlotState {
    status: FillStatus,
    wakers: Vec<Waker>,
}

#[derive(Debug, Clone, Copy)]
enum FillStatus {
    InProgress,
    Published,
    Failed(FailureKind),
}

#[derive(Debug, Clone, Copy)]
enum FailureKind {
    NotFound,
    Conflict,
    Integrity {
        expected: ContentDigest,
        actual: ContentDigest,
    },
    Length {
        expected: u64,
        actual: u64,
    },
    Corrupt {
        detail: CorruptionKind,
    },
    Limit {
        limit: u64,
        requested: u64,
    },
    Unsupported,
    Cancelled,
    Backend,
}

impl FailureKind {
    fn from_error(error: &StorageError) -> Self {
        match error {
            StorageError::NotFound { .. } => Self::NotFound,
            StorageError::Conflict { .. } => Self::Conflict,
            StorageError::IntegrityMismatch {
                expected, actual, ..
            } => Self::Integrity {
                expected: *expected,
                actual: *actual,
            },
            StorageError::LengthMismatch {
                expected, actual, ..
            } => Self::Length {
                expected: *expected,
                actual: *actual,
            },
            StorageError::Corrupt { detail, .. } => Self::Corrupt { detail: *detail },
            StorageError::LimitExceeded { limit, requested } => Self::Limit {
                limit: *limit,
                requested: *requested,
            },
            StorageError::Unsupported { .. } => Self::Unsupported,
            StorageError::Cancelled => Self::Cancelled,
            _ => Self::Backend,
        }
    }

    fn into_error(self, key: &StorageKey) -> StorageError {
        match self {
            Self::NotFound => StorageError::NotFound { key: key.clone() },
            Self::Conflict => StorageError::Conflict { key: key.clone() },
            Self::Integrity { expected, actual } => StorageError::IntegrityMismatch {
                key: key.clone(),
                expected,
                actual,
            },
            Self::Length { expected, actual } => StorageError::LengthMismatch {
                key: key.clone(),
                expected,
                actual,
            },
            Self::Corrupt { detail } => StorageError::Corrupt {
                key: key.clone(),
                detail,
            },
            Self::Limit { limit, requested } => StorageError::LimitExceeded { limit, requested },
            Self::Unsupported => StorageError::Unsupported {
                operation: StorageOp::CacheFill,
                platform: "object-store",
            },
            Self::Cancelled => StorageError::Cancelled,
            Self::Backend => StorageError::io(
                StorageOp::CacheFill,
                std::io::Error::other("cache fill failed"),
            ),
        }
    }
}

struct Inner<S, D> {
    store: S,
    directory: Arc<D>,
    offloader: Offloader<D>,
    config: CacheConfig,
    accounting: Arc<Accounting>,
}

/// A bounded, verified, pinning cache over a [`Directory`] and an
/// [`ObjectStore`].
pub struct SegmentCache<S, D> {
    inner: Arc<Inner<S, D>>,
}

enum Admission {
    Ready,
    Evict(StorageKey),
    Limit,
}

enum Decision {
    Hit(PinnedSegment),
    Follow(Arc<FillSlot>),
    Lead(Arc<FillSlot>),
}

impl<S: ObjectStore, D: Directory + 'static> SegmentCache<S, D> {
    /// Construct a cache with the default bounded filesystem offloader.
    ///
    /// # Panics
    ///
    /// Panics if `config.max_concurrent_fills` is zero.
    #[must_use]
    pub fn new(store: S, directory: D, config: CacheConfig) -> Self {
        let offload =
            OffloadConfig::from_cache(config.max_concurrent_fills, config.max_cache_bytes);
        Self::with_offload(store, directory, config, offload)
    }

    /// Construct a cache with an explicit offloader configuration.
    pub(crate) fn with_offload(
        store: S,
        directory: D,
        config: CacheConfig,
        offload: OffloadConfig,
    ) -> Self {
        assert!(
            config.max_concurrent_fills > 0,
            "max_concurrent_fills must be positive"
        );
        let directory = Arc::new(directory);
        let offloader = Offloader::new(Arc::clone(&directory), offload);
        Self {
            inner: Arc::new(Inner {
                store,
                directory,
                offloader,
                config,
                accounting: Arc::new(Accounting::default()),
            }),
        }
    }

    /// Stop the filesystem offloader and join its workers.
    ///
    /// This is terminal: subsequent `prepare` calls return a typed
    /// [`StorageError::Cancelled`] without mutating files. It blocks the calling
    /// thread and must not be called from an async poll or a worker callback.
    pub fn shutdown(&self) {
        self.inner.offloader.shutdown_and_join();
    }

    /// Test-only: run startup reconciliation to completion on the calling
    /// thread so tests can inspect deterministic post-reconciliation state.
    #[cfg(test)]
    pub(crate) fn ensure_reconciled_blocking(&self) -> Result<(), StorageError> {
        futures::executor::block_on(self.ensure_reconciled())
    }

    #[cfg(test)]
    pub(crate) fn offload_is_shutdown(&self) -> bool {
        self.inner.offloader.is_shutdown()
    }

    #[cfg(test)]
    pub(crate) fn offload_queued_bytes(&self) -> u64 {
        self.inner.offloader.queued_bytes()
    }

    #[cfg(test)]
    pub(crate) fn offload_queue_len(&self) -> usize {
        self.inner.offloader.queue_len()
    }

    /// The configured limits.
    #[must_use]
    pub fn config(&self) -> CacheConfig {
        self.inner.config
    }

    /// A snapshot of cache accounting.
    #[must_use]
    pub fn stats(&self) -> CacheStats {
        let state = self.inner.accounting.lock();
        let published_bytes: u64 = state
            .files
            .values()
            .filter(|file| file.published)
            .map(|file| file.bytes)
            .sum();
        let published_entries = state.files.values().filter(|file| file.published).count();
        CacheStats {
            published_entries,
            published_bytes,
            reserved_bytes: state.reserved_bytes,
            physical_bytes: state.known_bytes.saturating_add(state.reserved_bytes),
            orphan_bytes: state.known_bytes.saturating_sub(published_bytes),
            in_flight: state.in_flight,
            hits: state.hits,
            misses: state.misses,
            evictions: state.evictions,
            delete_failures: state.delete_failures,
            coalesced_waiters: state.coalesced_waiters,
        }
    }

    /// Open a pinned, published entry for synchronous local reads.
    pub fn open_read(&self, pin: &PinnedSegment) -> Result<Box<dyn ReadHandle>, StorageError> {
        self.inner.directory.open_read(&pin.key)
    }

    /// Materialize, verify, publish and pin the described segment.
    ///
    /// Concurrent calls for the same immutable identity coalesce onto one fill.
    /// A failed or cancelled fill wakes all followers with a typed error.
    ///
    /// The returned future is executor-neutral: callers drive it with any
    /// runtime, and no worker thread is ever blocked.
    pub async fn prepare(
        &self,
        descriptor: &SegmentDescriptor,
    ) -> Result<PinnedSegment, StorageError> {
        // Charge any files left by a previous process before admitting fills.
        self.ensure_reconciled().await?;
        let content = descriptor.content;
        let key = cache_key(&content);
        loop {
            let decision = {
                let mut state = self.inner.accounting.lock();
                if pin_existing(&mut state, &key) {
                    state.hits += 1;
                    Decision::Hit(PinnedSegment::new(
                        Arc::clone(&self.inner.accounting),
                        key.clone(),
                        content,
                    ))
                } else {
                    state.misses += 1;
                    if let Some(existing) = state.fills.get(&key) {
                        let slot = Arc::clone(existing);
                        state.coalesced_waiters += 1;
                        Decision::Follow(slot)
                    } else {
                        let slot = Arc::new(FillSlot::new());
                        state.fills.insert(key.clone(), Arc::clone(&slot));
                        Decision::Lead(slot)
                    }
                }
            };

            match decision {
                Decision::Hit(pin) => return Ok(pin),
                Decision::Follow(slot) => {
                    let outcome = poll_fn(|cx| {
                        let mut slot_state = slot.lock();
                        match &slot_state.status {
                            FillStatus::InProgress => {
                                slot_state.wakers.push(cx.waker().clone());
                                Poll::Pending
                            }
                            FillStatus::Published => Poll::Ready(Ok(())),
                            FillStatus::Failed(kind) => Poll::Ready(Err(kind.into_error(&key))),
                        }
                    })
                    .await;
                    match outcome {
                        Ok(()) => continue,
                        Err(error) => return Err(error),
                    }
                }
                Decision::Lead(slot) => return self.fill(descriptor, &key, &slot).await,
            }
        }
    }

    async fn fill(
        &self,
        descriptor: &SegmentDescriptor,
        key: &StorageKey,
        slot: &Arc<FillSlot>,
    ) -> Result<PinnedSegment, StorageError> {
        let content = descriptor.content;
        let mut guard = FillLeaderGuard::new(
            Arc::clone(&self.inner.accounting),
            Arc::clone(slot),
            key.clone(),
            content,
        );

        if content.length > self.inner.config.max_response_bytes {
            return self.abort_fill(
                &mut guard,
                StorageError::LimitExceeded {
                    limit: self.inner.config.max_response_bytes,
                    requested: content.length,
                },
            );
        }
        if content.length > self.inner.config.max_cache_bytes {
            return self.abort_fill(
                &mut guard,
                StorageError::LimitExceeded {
                    limit: self.inner.config.max_cache_bytes,
                    requested: content.length,
                },
            );
        }

        if let Err(error) = self.reserve(&mut guard, content.length).await {
            return self.abort_fill(&mut guard, error);
        }

        // Best-effort removal of a stale temporary entry for this identity.
        self.cleanup_temp(&content).await;

        let limits = TransferLimits::new(
            self.inner
                .config
                .max_response_bytes
                .min(self.inner.config.max_cache_bytes),
        );
        let body = match self
            .inner
            .store
            .get(&descriptor.object_key, None, &limits)
            .await
        {
            Ok(body) => body,
            Err(error) => {
                let error = StorageError::from_object_store(error, key);
                guard.fail(FailureKind::from_error(&error));
                return Err(error);
            }
        };

        if body.len() as u64 != content.length {
            return self.abort_fill(
                &mut guard,
                StorageError::LengthMismatch {
                    key: key.clone(),
                    expected: content.length,
                    actual: body.len() as u64,
                },
            );
        }
        // Full-length SHA-256 verification is offloaded to the filesystem
        // worker together with the atomic write so it never runs on the async
        // polling thread and never copies the payload a second time.

        // Do not overwrite a local file while it is being evicted.
        self.wait_for_key_eviction(key).await;
        self.offload_write(guard, content.digest, body).await
    }

    fn abort_fill(
        &self,
        guard: &mut FillLeaderGuard,
        error: StorageError,
    ) -> Result<PinnedSegment, StorageError> {
        guard.fail(FailureKind::from_error(&error));
        Err(error)
    }

    /// Offload the best-effort stale temporary cleanup.
    async fn cleanup_temp(&self, content: &ContentDescriptor) {
        let temp = temp_key(content);
        let _ = self
            .inner
            .offloader
            .submit(
                0,
                move |directory: &D, cancelled| {
                    if cancelled {
                        return Err(StorageError::Cancelled);
                    }
                    directory.delete(&temp)
                },
                |_directory, _result| (),
            )
            .await;
    }

    /// Offload verification and atomic promotion, transferring fill ownership.
    async fn offload_write(
        &self,
        mut guard: FillLeaderGuard,
        expected: ContentDigest,
        body: Vec<u8>,
    ) -> Result<PinnedSegment, StorageError> {
        let bytes = body.len() as u64;
        let key = guard.key().clone();
        let op = move |directory: &D, cancelled: bool| -> Result<(), StorageError> {
            if cancelled {
                return Err(StorageError::Cancelled);
            }
            let actual = ContentDigest::sha256_v1(&body);
            if actual != expected {
                return Err(StorageError::IntegrityMismatch {
                    key: key.clone(),
                    expected,
                    actual,
                });
            }
            directory.atomic_write(&key, &body)
        };
        let reconcile = move |directory: &D,
                              result: Result<(), StorageError>|
              -> Result<PinnedSegment, StorageError> {
            let ownership = guard.delegate();
            match result {
                Ok(()) => Ok(ownership.publish()),
                Err(error) => {
                    // A failed atomic_write may still have renamed the
                    // destination (for example a failing parent sync). Probe
                    // and charge any residual file so no bytes go unaccounted.
                    let residual = directory.file_len(ownership.key()).ok();
                    ownership.fail_residual(FailureKind::from_error(&error), residual);
                    Err(error)
                }
            }
        };
        self.inner.offloader.submit(bytes, op, reconcile).await
    }

    /// Reserve capacity and a fill slot without blocking a worker thread.
    async fn reserve(&self, guard: &mut FillLeaderGuard, bytes: u64) -> Result<(), StorageError> {
        let max_cache = self.inner.config.max_cache_bytes;
        let max_fills = self.inner.config.max_concurrent_fills;
        // Allow one bounded retry of previously failed deletes per admission,
        // without retrying inside the same admission loop.
        {
            let mut state = self.inner.accounting.lock();
            for file in state.files.values_mut() {
                if !file.evicting {
                    file.delete_failed = false;
                }
            }
        }
        loop {
            let admission = poll_fn(|cx| {
                let mut state = self.inner.accounting.lock();

                // A fill slot is required first; bytes may already fit.
                if state.in_flight >= max_fills {
                    state.admission_wakers.push(cx.waker().clone());
                    return Poll::Pending;
                }
                if state
                    .known_bytes
                    .saturating_add(state.reserved_bytes)
                    .saturating_add(bytes)
                    <= max_cache
                {
                    state.in_flight += 1;
                    state.reserved_bytes = state.reserved_bytes.saturating_add(bytes);
                    return Poll::Ready(Admission::Ready);
                }
                if let Some(candidate) = select_eviction_candidate(&mut state) {
                    return Poll::Ready(Admission::Evict(candidate));
                }
                if state.in_flight > 0 || state.files.values().any(|file| file.evicting) {
                    state.admission_wakers.push(cx.waker().clone());
                    return Poll::Pending;
                }
                Poll::Ready(Admission::Limit)
            })
            .await;

            match admission {
                Admission::Ready => {
                    guard.mark_reserved();
                    return Ok(());
                }
                Admission::Evict(key) => self.evict_and_finalize(&key).await,
                Admission::Limit => {
                    return Err(StorageError::LimitExceeded {
                        limit: max_cache,
                        requested: bytes,
                    });
                }
            }
        }
    }

    /// Offload an evicted entry's local delete to a filesystem worker.
    ///
    /// The entry stays marked `evicting` until the job reconciles. Accounting is
    /// freed even if the delete fails so admission can make progress; a failed
    /// delete may leave a stale local file that a future fill overwrites.
    /// Authoritative objects are never touched.
    async fn evict_and_finalize(&self, key: &StorageKey) {
        let accounting = Arc::clone(&self.inner.accounting);
        let op_key = key.clone();
        let reconcile_key = key.clone();
        let _ = self
            .inner
            .offloader
            .submit(
                0,
                move |directory: &D, cancelled| {
                    if cancelled {
                        return Err(StorageError::Cancelled);
                    }
                    directory.delete(&op_key)
                },
                move |_directory, result| finalize_eviction(&accounting, &reconcile_key, result),
            )
            .await;
    }

    /// Wait until no eviction is in progress for `key`.
    async fn wait_for_key_eviction(&self, key: &StorageKey) {
        poll_fn(|cx| {
            let mut state = self.inner.accounting.lock();
            let evicting = state
                .files
                .get(key)
                .map(|entry| entry.evicting)
                .unwrap_or(false);
            if !evicting {
                return Poll::Ready(());
            }
            state
                .eviction_wakers
                .entry(key.clone())
                .or_default()
                .push(cx.waker().clone());
            Poll::Pending
        })
        .await
    }

    /// Ensure startup reconciliation has charged all pre-existing cache files.
    async fn ensure_reconciled(&self) -> Result<(), StorageError> {
        let is_leader = {
            let mut state = self.inner.accounting.lock();
            if matches!(state.reconciliation, Reconciliation::Pending) {
                state.reconciliation = Reconciliation::InProgress;
                true
            } else {
                if matches!(state.reconciliation, Reconciliation::InProgress) {
                    state.coalesced_waiters += 1;
                }
                false
            }
        };
        if is_leader {
            self.run_reconciliation().await;
        }
        let result = poll_fn(|cx| {
            let mut state = self.inner.accounting.lock();
            match state.reconciliation {
                Reconciliation::Done(result) => Poll::Ready(result),
                _ => {
                    state.reconciliation_wakers.push(cx.waker().clone());
                    Poll::Pending
                }
            }
        })
        .await;
        result.map_err(|kind| kind.into_error(&reconciliation_key()))
    }

    async fn run_reconciliation(&self) {
        let accounting = Arc::clone(&self.inner.accounting);
        let limit = reconcile_entry_limit(self.inner.config.max_cache_bytes);
        let scan: ScanSlot = Arc::new(Mutex::new(None));
        let scan_op = Arc::clone(&scan);
        let op = move |directory: &D, cancelled: bool| -> Result<(), StorageError> {
            let outcome = if cancelled {
                Err(FailureKind::Cancelled)
            } else {
                scan_directory(directory, limit)
            };
            *scan_op
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(outcome);
            Ok(())
        };
        let scan_reconcile = Arc::clone(&scan);
        let accounting_reconcile = Arc::clone(&accounting);
        let reconcile = move |_directory: &D, result: Result<(), StorageError>| {
            let outcome = match result {
                Ok(()) => match scan_reconcile
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                    .take()
                {
                    Some(Ok(entries)) => {
                        apply_reconciliation(&accounting_reconcile, entries);
                        Ok(())
                    }
                    Some(Err(kind)) => Err(kind),
                    None => Err(FailureKind::Backend),
                },
                Err(error) => Err(FailureKind::from_error(&error)),
            };
            set_reconciliation_done(&accounting_reconcile, outcome);
            outcome
        };
        let _ = self.inner.offloader.submit(0, op, reconcile).await;
    }
}

const MAX_RECONCILE_ENTRIES: usize = 262_144;

fn reconcile_entry_limit(max_cache_bytes: u64) -> usize {
    usize::try_from(max_cache_bytes)
        .unwrap_or(MAX_RECONCILE_ENTRIES)
        .clamp(1024, MAX_RECONCILE_ENTRIES)
}

/// Cache-owned key prefixes. A dedicated cache root must contain only these.
fn is_cache_owned(key: &str) -> bool {
    key.starts_with("cache-v1-") || key.starts_with("tmp-v1-") || key.starts_with(".trawler-tmp-")
}

fn reconciliation_key() -> StorageKey {
    StorageKey::parse("cache-reconcile").expect("synthetic reconciliation key is valid")
}

fn scan_directory<D: Directory>(
    directory: &D,
    limit: usize,
) -> Result<Vec<(StorageKey, u64)>, FailureKind> {
    let keys = directory
        .list("", limit)
        .map_err(|error| FailureKind::from_error(&error))?;
    let mut entries = Vec::with_capacity(keys.len());
    for key in keys {
        if !is_cache_owned(key.as_str()) {
            // A dedicated cache root must contain only cache-owned files.
            return Err(FailureKind::Corrupt {
                detail: CorruptionKind::UnexpectedContent,
            });
        }
        let len = directory
            .file_len(&key)
            .map_err(|error| FailureKind::from_error(&error))?;
        entries.push((key, len));
    }
    Ok(entries)
}

fn apply_reconciliation(accounting: &Arc<Accounting>, entries: Vec<(StorageKey, u64)>) {
    let mut state = accounting.lock();
    for (key, len) in entries {
        if state.files.contains_key(&key) {
            continue;
        }
        state.files.insert(
            key,
            FileEntry {
                bytes: len,
                pinned: 0,
                last_used: 0,
                evicting: false,
                delete_failed: false,
                published: false,
            },
        );
        state.known_bytes = state.known_bytes.saturating_add(len);
    }
}

fn set_reconciliation_done(accounting: &Arc<Accounting>, result: Result<(), FailureKind>) {
    let wakers = {
        let mut state = accounting.lock();
        state.reconciliation = Reconciliation::Done(result);
        std::mem::take(&mut state.reconciliation_wakers)
    };
    for waker in wakers {
        waker.wake();
    }
}

fn pin_existing(state: &mut State, key: &StorageKey) -> bool {
    let Some(entry) = state.files.get(key) else {
        return false;
    };
    // Orphans are charged but never verified or pinnable.
    if !entry.published || entry.evicting {
        return false;
    }
    state.next_tick += 1;
    let tick = state.next_tick;
    if let Some(entry) = state.files.get_mut(key) {
        entry.pinned += 1;
        entry.last_used = tick;
        true
    } else {
        false
    }
}

fn select_eviction_candidate(state: &mut State) -> Option<StorageKey> {
    // Prefer charged orphans (unverified, never pinned), then LRU unpinned
    // published entries. Delete-failed files stay charged but are not retried.
    let key = state
        .files
        .iter()
        .filter(|(_, file)| !file.evicting && !file.delete_failed)
        .filter(|(_, file)| !file.published || file.pinned == 0)
        .min_by_key(|(_, file)| (file.published, file.last_used))
        .map(|(key, _)| key.clone())?;
    if let Some(file) = state.files.get_mut(&key) {
        file.evicting = true;
    }
    Some(key)
}

fn cache_key(content: &ContentDescriptor) -> StorageKey {
    StorageKey::parse(format!(
        "cache-v1-{}-{}-{}",
        content.digest.algorithm().id(),
        content.digest.to_hex(),
        content.length
    ))
    .expect("generated cache key is valid")
}

fn temp_key(content: &ContentDescriptor) -> StorageKey {
    StorageKey::parse(format!(
        "tmp-v1-{}-{}-{}",
        content.digest.algorithm().id(),
        content.digest.to_hex(),
        content.length
    ))
    .expect("generated temp key is valid")
}

/// Ownership of a fill's reservation, fill slot and terminal status.
///
/// Moved out of [`FillLeaderGuard`] and into the offloaded write job so a
/// dropped `prepare` future can never release the reservation while a worker is
/// still mutating the filesystem.
struct FillOwnership {
    accounting: Arc<Accounting>,
    slot: Arc<FillSlot>,
    key: StorageKey,
    content: ContentDescriptor,
    bytes: u64,
    reserved: bool,
}

impl FillOwnership {
    fn key(&self) -> &StorageKey {
        &self.key
    }

    fn publish(self) -> PinnedSegment {
        let admission_wakers = self.release_reservation_and_fill_slot(true, None);
        for waker in admission_wakers {
            waker.wake();
        }
        self.set_status(FillStatus::Published);
        PinnedSegment::new(Arc::clone(&self.accounting), self.key.clone(), self.content)
    }

    fn fail(self, kind: FailureKind) {
        self.fail_residual(kind, None);
    }

    /// Fail the fill, optionally charging a residual file left on disk by a
    /// failed but partially-applied atomic write.
    fn fail_residual(self, kind: FailureKind, residual: Option<u64>) {
        let admission_wakers = self.release_reservation_and_fill_slot(false, residual);
        for waker in admission_wakers {
            waker.wake();
        }
        self.set_status(FillStatus::Failed(kind));
    }

    /// Release the reservation and remove the fill slot.
    ///
    /// When `published`, the verified file replaces any charged orphan for the
    /// same key and the leader's pin is installed. `residual` charges an
    /// unverified leftover on a failed write.
    fn release_reservation_and_fill_slot(
        &self,
        published: bool,
        residual: Option<u64>,
    ) -> Vec<Waker> {
        let mut state = self.accounting.lock();
        if self.reserved {
            state.reserved_bytes = state.reserved_bytes.saturating_sub(self.bytes);
            state.in_flight = state.in_flight.saturating_sub(1);
        }
        if published {
            state.next_tick += 1;
            let tick = state.next_tick;
            let old_bytes = state
                .files
                .insert(
                    self.key.clone(),
                    FileEntry {
                        bytes: self.bytes,
                        pinned: 1,
                        last_used: tick,
                        evicting: false,
                        delete_failed: false,
                        published: true,
                    },
                )
                .map(|file| file.bytes)
                .unwrap_or(0);
            state.known_bytes = state
                .known_bytes
                .saturating_sub(old_bytes)
                .saturating_add(self.bytes);
        } else if let Some(len) = residual {
            if !state.files.contains_key(&self.key) {
                state.files.insert(
                    self.key.clone(),
                    FileEntry {
                        bytes: len,
                        pinned: 0,
                        last_used: 0,
                        evicting: false,
                        delete_failed: false,
                        published: false,
                    },
                );
                state.known_bytes = state.known_bytes.saturating_add(len);
            }
        }
        state.fills.remove(&self.key);
        std::mem::take(&mut state.admission_wakers)
    }

    fn set_status(&self, status: FillStatus) {
        let wakers = {
            let mut slot = self.slot.lock();
            slot.status = status;
            std::mem::take(&mut slot.wakers)
        };
        for waker in wakers {
            waker.wake();
        }
    }
}

/// Leader guard that owns [`FillOwnership`] until it is delegated to a job.
///
/// Dropping the guard before delegation (for example because the leader future
/// was cancelled) marks the fill failed and wakes every follower. Once the
/// ownership is delegated the job owns reconciliation, so a later drop is a
/// no-op.
struct FillLeaderGuard {
    ownership: Option<FillOwnership>,
    terminal: bool,
}

impl FillLeaderGuard {
    fn new(
        accounting: Arc<Accounting>,
        slot: Arc<FillSlot>,
        key: StorageKey,
        content: ContentDescriptor,
    ) -> Self {
        Self {
            ownership: Some(FillOwnership {
                accounting,
                slot,
                key,
                content,
                bytes: content.length,
                reserved: false,
            }),
            terminal: false,
        }
    }

    fn key(&self) -> &StorageKey {
        &self
            .ownership
            .as_ref()
            .expect("fill ownership is held before delegation")
            .key
    }

    fn mark_reserved(&mut self) {
        if let Some(ownership) = self.ownership.as_mut() {
            ownership.reserved = true;
        }
    }

    fn fail(&mut self, kind: FailureKind) {
        if self.terminal {
            return;
        }
        self.terminal = true;
        if let Some(ownership) = self.ownership.take() {
            ownership.fail(kind);
        }
    }

    fn delegate(&mut self) -> FillOwnership {
        self.terminal = true;
        self.ownership
            .take()
            .expect("fill ownership is held before delegation")
    }
}

impl Drop for FillLeaderGuard {
    fn drop(&mut self) {
        if self.terminal {
            return;
        }
        self.terminal = true;
        if let Some(ownership) = self.ownership.take() {
            ownership.fail(FailureKind::Cancelled);
        }
    }
}

/// Finalize an eviction when its offloaded delete completes or is cancelled.
///
/// Only a successful delete frees the physical charge. A failed delete keeps
/// the file charged and marks it `delete_failed` so it is not retried in a tight
/// loop and cannot be treated as free capacity.
fn finalize_eviction(
    accounting: &Arc<Accounting>,
    key: &StorageKey,
    result: Result<(), StorageError>,
) {
    let (eviction_wakers, admission_wakers) = {
        let mut state = accounting.lock();
        let mut removed_bytes = None;
        let mut failed = false;
        if let Some(file) = state.files.get_mut(key) {
            if file.evicting {
                match result {
                    Ok(()) => removed_bytes = Some(file.bytes),
                    Err(_) => {
                        file.evicting = false;
                        file.delete_failed = true;
                        failed = true;
                    }
                }
            }
        }
        if let Some(bytes) = removed_bytes {
            state.files.remove(key);
            state.known_bytes = state.known_bytes.saturating_sub(bytes);
            state.evictions += 1;
        }
        if failed {
            state.delete_failures += 1;
        }
        (
            state.eviction_wakers.remove(key),
            std::mem::take(&mut state.admission_wakers),
        )
    };
    if let Some(wakers) = eviction_wakers {
        for waker in wakers {
            waker.wake();
        }
    }
    for waker in admission_wakers {
        waker.wake();
    }
}

/// An RAII lease on a verified, published cache entry.
pub struct PinnedSegment {
    accounting: Arc<Accounting>,
    key: StorageKey,
    descriptor: ContentDescriptor,
}

impl PinnedSegment {
    fn new(accounting: Arc<Accounting>, key: StorageKey, descriptor: ContentDescriptor) -> Self {
        Self {
            accounting,
            key,
            descriptor,
        }
    }

    /// The local cache key holding the verified bytes.
    #[must_use]
    pub fn key(&self) -> &StorageKey {
        &self.key
    }

    /// The immutable identity of the pinned bytes.
    #[must_use]
    pub fn descriptor(&self) -> ContentDescriptor {
        self.descriptor
    }
}

impl std::fmt::Debug for PinnedSegment {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PinnedSegment")
            .field("key", &self.key)
            .field("descriptor", &self.descriptor)
            .finish_non_exhaustive()
    }
}

impl Drop for PinnedSegment {
    fn drop(&mut self) {
        let mut state = self.accounting.lock();
        if let Some(file) = state.files.get_mut(&self.key) {
            file.pinned = file.pinned.saturating_sub(1);
        }
    }
}

#[cfg(test)]
mod pin_ownership_tests {
    use super::*;

    fn fixture() -> (
        Arc<Accounting>,
        Arc<FillSlot>,
        StorageKey,
        ContentDescriptor,
    ) {
        (
            Arc::new(Accounting::default()),
            Arc::new(FillSlot::new()),
            StorageKey::parse("owned").unwrap(),
            ContentDescriptor::of(b"payload"),
        )
    }

    #[test]
    fn pre_publish_drop_marks_cancelled_and_releases_reservation() {
        let (accounting, slot, key, content) = fixture();
        {
            let mut guard = FillLeaderGuard::new(
                Arc::clone(&accounting),
                Arc::clone(&slot),
                key.clone(),
                content,
            );
            {
                let mut state = accounting.lock();
                state.in_flight = 1;
                state.reserved_bytes = content.length;
                state.fills.insert(key.clone(), Arc::clone(&slot));
            }
            guard.mark_reserved();
            // Dropped without publishing.
        }
        let state = accounting.lock();
        assert_eq!(state.in_flight, 0);
        assert_eq!(state.reserved_bytes, 0);
        assert!(state.fills.is_empty());
        assert!(state.files.is_empty());
        assert_eq!(state.known_bytes, 0);
        drop(state);
        assert!(matches!(
            slot.lock().status,
            FillStatus::Failed(FailureKind::Cancelled)
        ));
    }

    #[test]
    fn post_publish_drop_releases_pin_and_keeps_verified_entry() {
        let (accounting, slot, key, content) = fixture();
        {
            let mut guard = FillLeaderGuard::new(
                Arc::clone(&accounting),
                Arc::clone(&slot),
                key.clone(),
                content,
            );
            {
                let mut state = accounting.lock();
                state.in_flight = 1;
                state.reserved_bytes = content.length;
                state.fills.insert(key.clone(), Arc::clone(&slot));
            }
            guard.mark_reserved();
            // Delegation transfers ownership to the (simulated) job, which
            // publishes. Dropping the returned pin releases it without leaking
            // and leaves the verified entry published.
            let pin = guard.delegate().publish();
            assert_eq!(accounting.lock().files.get(&key).unwrap().pinned, 1);
            drop(pin);
        }
        let state = accounting.lock();
        assert_eq!(state.in_flight, 0);
        assert_eq!(state.reserved_bytes, 0);
        assert_eq!(state.known_bytes, content.length);
        assert!(state.fills.is_empty());
        assert_eq!(state.files.get(&key).unwrap().pinned, 0);
        drop(state);
        assert!(matches!(slot.lock().status, FillStatus::Published));
    }

    #[test]
    fn failed_fill_wakes_all_followers() {
        let (accounting, slot, key, content) = fixture();
        let mut follower = Box::pin(poll_fn(|cx| {
            let mut slot_state = slot.lock();
            match slot_state.status {
                FillStatus::InProgress => {
                    slot_state.wakers.push(cx.waker().clone());
                    Poll::Pending
                }
                FillStatus::Published => Poll::Ready(Ok(())),
                FillStatus::Failed(_) => Poll::Ready(Err(())),
            }
        }));
        let mut context = std::task::Context::from_waker(std::task::Waker::noop());
        assert!(follower.as_mut().poll(&mut context).is_pending());

        let mut guard = FillLeaderGuard::new(
            Arc::clone(&accounting),
            Arc::clone(&slot),
            key.clone(),
            content,
        );
        guard.fail(FailureKind::NotFound);
        assert!(matches!(
            follower.as_mut().poll(&mut context),
            Poll::Ready(Err(()))
        ));
    }
}
