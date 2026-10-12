//! A bounded, verified, pinning local cache over an authoritative ObjectStore.
//!
//! Lifecycle: `Absent -> Filling(temp) -> Verified -> Published -> Leased`.
//! Entries become visible only after full length + SHA-256 verification and
//! atomic local promotion. The cache never deletes authoritative remote
//! objects, and all accounting is hard: `max_cache_bytes` bounds published,
//! reserved in-flight, and temporary bytes together without double counting.

use std::collections::HashMap;
use std::sync::{Arc, Condvar, Mutex};

use trawler_objectstore::{ContentDescriptor, ContentDigest, ObjectStore, TransferLimits};

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
}

#[derive(Debug, Default)]
struct State {
    entries: HashMap<StorageKey, Entry>,
    published_bytes: u64,
    reserved_bytes: u64,
    next_tick: u64,
    in_flight: usize,
    fills: HashMap<StorageKey, Arc<FillSlot>>,
    hits: u64,
    misses: u64,
    evictions: u64,
    coalesced_waiters: u64,
}

#[derive(Debug, Default)]
struct Accounting {
    state: Mutex<State>,
    cv: Condvar,
}

#[derive(Debug)]
struct FillSlot {
    status: Mutex<FillStatus>,
    cv: Condvar,
}

impl FillSlot {
    fn new() -> Self {
        Self {
            status: Mutex::new(FillStatus::InProgress),
            cv: Condvar::new(),
        }
    }
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
    Integrity,
    Length,
    Limit { limit: u64, requested: u64 },
    Unsupported,
    Cancelled,
    Backend,
}

impl FailureKind {
    fn from_error(error: &StorageError) -> Self {
        match error {
            StorageError::NotFound { .. } => Self::NotFound,
            StorageError::Conflict { .. } => Self::Conflict,
            StorageError::IntegrityMismatch { .. } => Self::Integrity,
            StorageError::LengthMismatch { .. } => Self::Length,
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
            Self::Integrity => StorageError::Corrupt {
                key: key.clone(),
                detail: CorruptionKind::DigestMismatch,
            },
            Self::Length => StorageError::Corrupt {
                key: key.clone(),
                detail: CorruptionKind::LengthMismatch,
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
    directory: D,
    config: CacheConfig,
    accounting: Arc<Accounting>,
}

/// A bounded, verified, pinning cache over a [`Directory`] and an
/// [`ObjectStore`].
pub struct SegmentCache<S, D> {
    inner: Arc<Inner<S, D>>,
}

impl<S: ObjectStore, D: Directory> SegmentCache<S, D> {
    /// Construct a cache.
    ///
    /// # Panics
    ///
    /// Panics if `config.max_concurrent_fills` is zero.
    #[must_use]
    pub fn new(store: S, directory: D, config: CacheConfig) -> Self {
        assert!(
            config.max_concurrent_fills > 0,
            "max_concurrent_fills must be positive"
        );
        Self {
            inner: Arc::new(Inner {
                store,
                directory,
                config,
                accounting: Arc::new(Accounting::default()),
            }),
        }
    }

    /// The configured limits.
    #[must_use]
    pub fn config(&self) -> CacheConfig {
        self.inner.config
    }

    /// A snapshot of cache accounting.
    #[must_use]
    pub fn stats(&self) -> CacheStats {
        let state = self.inner.accounting.state.lock().expect("cache lock");
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
    /// A failed fill wakes all waiters with a typed error.
    pub async fn prepare(
        &self,
        descriptor: &SegmentDescriptor,
    ) -> Result<PinnedSegment, StorageError> {
        let content = descriptor.content;
        let key = cache_key(&content);
        loop {
            {
                let mut state = self.inner.accounting.state.lock().expect("cache lock");
                if pin_existing(&mut state, &key) {
                    state.hits += 1;
                    drop(state);
                    return Ok(PinnedSegment::new(
                        Arc::clone(&self.inner.accounting),
                        key,
                        content,
                    ));
                }
                state.misses += 1;
            }

            let (slot, is_leader) = {
                let mut state = self.inner.accounting.state.lock().expect("cache lock");
                if let Some(existing) = state.fills.get(&key) {
                    let slot = Arc::clone(existing);
                    state.coalesced_waiters += 1;
                    (slot, false)
                } else {
                    let slot = Arc::new(FillSlot::new());
                    state.fills.insert(key.clone(), Arc::clone(&slot));
                    (slot, true)
                }
            };

            if !is_leader {
                let mut status = slot.status.lock().expect("fill lock");
                while matches!(*status, FillStatus::InProgress) {
                    status = slot.cv.wait(status).expect("fill wait");
                }
                match &*status {
                    FillStatus::Published => {
                        drop(status);
                        continue;
                    }
                    FillStatus::Failed(kind) => {
                        let error = kind.into_error(&key);
                        drop(status);
                        return Err(error);
                    }
                    FillStatus::InProgress => unreachable!("loop exits only when not in progress"),
                }
            }

            let outcome = self.fill(descriptor, &key).await;
            {
                let mut status = slot.status.lock().expect("fill lock");
                *status = match &outcome {
                    Ok(()) => FillStatus::Published,
                    Err(error) => FillStatus::Failed(FailureKind::from_error(error)),
                };
                slot.cv.notify_all();
            }
            {
                let mut state = self.inner.accounting.state.lock().expect("cache lock");
                state.fills.remove(&key);
                self.inner.accounting.cv.notify_all();
            }

            match outcome {
                Ok(()) => {
                    return Ok(PinnedSegment::new(
                        Arc::clone(&self.inner.accounting),
                        key,
                        content,
                    ));
                }
                Err(error) => return Err(error),
            }
        }
    }

    async fn fill(
        &self,
        descriptor: &SegmentDescriptor,
        key: &StorageKey,
    ) -> Result<(), StorageError> {
        let content = descriptor.content;
        if content.length > self.inner.config.max_response_bytes {
            return Err(StorageError::LimitExceeded {
                limit: self.inner.config.max_response_bytes,
                requested: content.length,
            });
        }
        if content.length > self.inner.config.max_cache_bytes {
            return Err(StorageError::LimitExceeded {
                limit: self.inner.config.max_cache_bytes,
                requested: content.length,
            });
        }

        self.acquire(content.length)?;
        let guard = ReservationGuard {
            accounting: Arc::clone(&self.inner.accounting),
            bytes: content.length,
            published: false,
        };

        // Best-effort removal of a stale temporary entry for this identity.
        let _ = self.inner.directory.delete(&temp_key(&content));

        let limits = TransferLimits::new(
            self.inner
                .config
                .max_response_bytes
                .min(self.inner.config.max_cache_bytes),
        );
        let body = self
            .inner
            .store
            .get(&descriptor.object_key, None, &limits)
            .await
            .map_err(|error| StorageError::from_object_store(error, key))?;

        if body.len() as u64 != content.length {
            return Err(StorageError::LengthMismatch {
                key: key.clone(),
                expected: content.length,
                actual: body.len() as u64,
            });
        }
        let actual = ContentDigest::sha256_v1(&body);
        if actual != content.digest {
            return Err(StorageError::IntegrityMismatch {
                key: key.clone(),
                expected: content.digest,
                actual,
            });
        }

        self.inner.directory.atomic_write(key, &body)?;

        let mut guard = guard;
        {
            let mut state = self.inner.accounting.state.lock().expect("cache lock");
            state.reserved_bytes = state.reserved_bytes.saturating_sub(content.length);
            state.in_flight = state.in_flight.saturating_sub(1);
            state.published_bytes = state.published_bytes.saturating_add(content.length);
            state.next_tick += 1;
            let tick = state.next_tick;
            state.entries.insert(
                key.clone(),
                Entry {
                    bytes: content.length,
                    pinned: 1,
                    last_used: tick,
                },
            );
            self.inner.accounting.cv.notify_all();
        }
        guard.published = true;
        Ok(())
    }

    /// Reserve capacity and a fill slot, evicting LRU unpinned entries.
    fn acquire(&self, bytes: u64) -> Result<(), StorageError> {
        let mut state = self.inner.accounting.state.lock().expect("cache lock");
        while state.in_flight >= self.inner.config.max_concurrent_fills {
            state = self.inner.accounting.cv.wait(state).expect("cache wait");
        }
        while state
            .published_bytes
            .saturating_add(state.reserved_bytes)
            .saturating_add(bytes)
            > self.inner.config.max_cache_bytes
        {
            if !evict_one(&self.inner.directory, &mut state) {
                return Err(StorageError::LimitExceeded {
                    limit: self.inner.config.max_cache_bytes,
                    requested: bytes,
                });
            }
        }
        state.in_flight += 1;
        state.reserved_bytes = state.reserved_bytes.saturating_add(bytes);
        Ok(())
    }
}

fn pin_existing(state: &mut State, key: &StorageKey) -> bool {
    if !state.entries.contains_key(key) {
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

fn evict_one<D: Directory>(directory: &D, state: &mut State) -> bool {
    let candidate = state
        .entries
        .iter()
        .filter(|(_, entry)| entry.pinned == 0)
        .min_by_key(|(_, entry)| entry.last_used)
        .map(|(key, _)| key.clone());
    match candidate {
        Some(key) => {
            if let Some(entry) = state.entries.remove(&key) {
                state.published_bytes = state.published_bytes.saturating_sub(entry.bytes);
                state.evictions += 1;
                let _ = directory.delete(&key);
            }
            true
        }
        None => false,
    }
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

struct ReservationGuard {
    accounting: Arc<Accounting>,
    bytes: u64,
    published: bool,
}

impl Drop for ReservationGuard {
    fn drop(&mut self) {
        if self.published {
            return;
        }
        let mut state = self.accounting.state.lock().expect("cache lock");
        state.reserved_bytes = state.reserved_bytes.saturating_sub(self.bytes);
        state.in_flight = state.in_flight.saturating_sub(1);
        self.accounting.cv.notify_all();
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
        let mut state = self.accounting.state.lock().expect("cache lock");
        if let Some(entry) = state.entries.get_mut(&self.key) {
            entry.pinned = entry.pinned.saturating_sub(1);
        }
        self.accounting.cv.notify_all();
    }
}
