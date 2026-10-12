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
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CacheStats {
    /// Number of published entries.
    pub published_entries: usize,
    /// Bytes held by published entries.
    pub published_bytes: u64,
    /// Bytes reserved for in-flight fills.
    pub reserved_bytes: u64,
    /// Number of in-flight fills.
    pub in_flight: usize,
    /// Successful published hits.
    pub hits: u64,
    /// Lookups that did not find a published entry.
    pub misses: u64,
    /// Entries evicted by the LRU policy.
    pub evictions: u64,
    /// Waiters that coalesced onto an existing fill.
    pub coalesced_waiters: u64,
}

#[derive(Debug)]
struct Entry {
    bytes: u64,
    pinned: usize,
    last_used: u64,
    /// Marked while a leader is deleting this entry's local bytes. An evicting
    /// entry can neither be pinned nor selected again.
    evicting: bool,
}

#[derive(Debug, Default)]
struct State {
    entries: HashMap<StorageKey, Entry>,
    published_bytes: u64,
    reserved_bytes: u64,
    next_tick: u64,
    in_flight: usize,
    fills: HashMap<StorageKey, Arc<FillSlot>>,
    admission_wakers: Vec<Waker>,
    eviction_wakers: HashMap<StorageKey, Vec<Waker>>,
    hits: u64,
    misses: u64,
    evictions: u64,
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
        CacheStats {
            published_entries: state.entries.len(),
            published_bytes: state.published_bytes,
            reserved_bytes: state.reserved_bytes,
            in_flight: state.in_flight,
            hits: state.hits,
            misses: state.misses,
            evictions: state.evictions,
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
        let actual = ContentDigest::sha256_v1(&body);
        if actual != content.digest {
            return self.abort_fill(
                &mut guard,
                StorageError::IntegrityMismatch {
                    key: key.clone(),
                    expected: content.digest,
                    actual,
                },
            );
        }

        // Do not overwrite a local file while it is being evicted.
        self.wait_for_key_eviction(key).await;
        self.offload_write(guard, body).await
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
                |_| (),
            )
            .await;
    }

    /// Offload the verified atomic promotion, transferring fill ownership.
    async fn offload_write(
        &self,
        mut guard: FillLeaderGuard,
        body: Vec<u8>,
    ) -> Result<PinnedSegment, StorageError> {
        let bytes = body.len() as u64;
        let key = guard.key().clone();
        let op = move |directory: &D, cancelled: bool| -> Result<(), StorageError> {
            if cancelled {
                return Err(StorageError::Cancelled);
            }
            directory.atomic_write(&key, &body)
        };
        let reconcile =
            move |result: Result<(), StorageError>| -> Result<PinnedSegment, StorageError> {
                let ownership = guard.delegate();
                match result {
                    Ok(()) => Ok(ownership.publish()),
                    Err(error) => {
                        ownership.fail(FailureKind::from_error(&error));
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
        loop {
            let admission = poll_fn(|cx| {
                let mut state = self.inner.accounting.lock();

                // A fill slot is required first; bytes may already fit.
                if state.in_flight >= max_fills {
                    state.admission_wakers.push(cx.waker().clone());
                    return Poll::Pending;
                }
                if state
                    .published_bytes
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
                if state.in_flight > 0 || state.entries.values().any(|entry| entry.evicting) {
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
                move |result| finalize_eviction(&accounting, &reconcile_key, result),
            )
            .await;
    }

    /// Wait until no eviction is in progress for `key`.
    async fn wait_for_key_eviction(&self, key: &StorageKey) {
        poll_fn(|cx| {
            let mut state = self.inner.accounting.lock();
            let evicting = state
                .entries
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
}

fn pin_existing(state: &mut State, key: &StorageKey) -> bool {
    let Some(entry) = state.entries.get(key) else {
        return false;
    };
    if entry.evicting {
        return false;
    }
    state.next_tick += 1;
    let tick = state.next_tick;
    if let Some(entry) = state.entries.get_mut(key) {
        entry.pinned += 1;
        entry.last_used = tick;
        true
    } else {
        false
    }
}

fn select_eviction_candidate(state: &mut State) -> Option<StorageKey> {
    let key = state
        .entries
        .iter()
        .filter(|(_, entry)| entry.pinned == 0 && !entry.evicting)
        .min_by_key(|(_, entry)| entry.last_used)
        .map(|(key, _)| key.clone())?;
    if let Some(entry) = state.entries.get_mut(&key) {
        entry.evicting = true;
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
    fn publish(self) -> PinnedSegment {
        let admission_wakers = self.release_reservation_and_fill_slot(true);
        for waker in admission_wakers {
            waker.wake();
        }
        self.set_status(FillStatus::Published);
        PinnedSegment::new(Arc::clone(&self.accounting), self.key.clone(), self.content)
    }

    fn fail(self, kind: FailureKind) {
        let admission_wakers = self.release_reservation_and_fill_slot(false);
        for waker in admission_wakers {
            waker.wake();
        }
        self.set_status(FillStatus::Failed(kind));
    }

    /// Release the reservation and remove the fill slot.
    ///
    /// When `published`, reserve bytes transfer to published bytes and the
    /// verified entry is inserted with the leader's pin.
    fn release_reservation_and_fill_slot(&self, published: bool) -> Vec<Waker> {
        let mut state = self.accounting.lock();
        if self.reserved {
            state.reserved_bytes = state.reserved_bytes.saturating_sub(self.bytes);
            state.in_flight = state.in_flight.saturating_sub(1);
        }
        if published {
            state.published_bytes = state.published_bytes.saturating_add(self.bytes);
            state.next_tick += 1;
            let tick = state.next_tick;
            state.entries.insert(
                self.key.clone(),
                Entry {
                    bytes: self.bytes,
                    pinned: 1,
                    last_used: tick,
                    evicting: false,
                },
            );
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
fn finalize_eviction(
    accounting: &Arc<Accounting>,
    key: &StorageKey,
    _result: Result<(), StorageError>,
) {
    let (eviction_wakers, admission_wakers) = {
        let mut state = accounting.lock();
        let evicting = state
            .entries
            .get(key)
            .map(|entry| entry.evicting)
            .unwrap_or(false);
        if evicting {
            let bytes = state.entries.get(key).map(|entry| entry.bytes).unwrap_or(0);
            state.entries.remove(key);
            state.published_bytes = state.published_bytes.saturating_sub(bytes);
            state.evictions += 1;
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
        if let Some(entry) = state.entries.get_mut(&self.key) {
            entry.pinned = entry.pinned.saturating_sub(1);
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
        assert!(state.entries.is_empty());
        assert_eq!(state.published_bytes, 0);
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
            assert_eq!(accounting.lock().entries.get(&key).unwrap().pinned, 1);
            drop(pin);
        }
        let state = accounting.lock();
        assert_eq!(state.in_flight, 0);
        assert_eq!(state.reserved_bytes, 0);
        assert_eq!(state.published_bytes, content.length);
        assert!(state.fills.is_empty());
        assert_eq!(state.entries.get(&key).unwrap().pinned, 0);
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
