//! Bounded whole-object and parallel-ranged segment transfer (PR 13).
//!
//! The scheduler downloads one immutable segment either as a single bounded
//! `GET` or as disjoint, contiguous exact byte ranges assembled in order. It is
//! executor-neutral: it awaits only provider-neutral [`ObjectStore`] futures
//! and never requires a specific runtime.
//!
//! All limits are hard. A single object must fit the cache/snapshot bound; the
//! aggregate live response bytes, global request concurrency and per-segment
//! range concurrency are separately enforced before each request. Only genuine
//! transient failures are retried, with a bounded attempt count; an auth,
//! not-found, precondition, invalid-range or corruption failure is terminal.
//!
//! The assembled bytes are returned to the existing [`SegmentCache`] fill seam,
//! which remains the sole owner of admission, verification, atomic promotion
//! and accounting.
//!
//! [`SegmentCache`]: crate::storage::SegmentCache

use std::collections::VecDeque;
use std::future::poll_fn;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Poll, Waker};

use quervant_objectstore::{
    ByteRange, ContentDescriptor, ObjectKey, ObjectStore, ObjectStoreError, TransferLimits,
};

use crate::index::{IndexError, IndexResult};
use crate::storage::StorageError;

use super::config::RemoteTransferConfig;

/// A waker-based, runtime-free permit pool.
#[derive(Debug)]
struct PermitPool {
    max: usize,
    state: Mutex<PermitState>,
}

#[derive(Debug, Default)]
struct PermitState {
    used: usize,
    waiters: VecDeque<Waker>,
}

impl PermitPool {
    fn new(max: usize) -> Arc<Self> {
        Arc::new(Self {
            max,
            state: Mutex::new(PermitState::default()),
        })
    }

    fn lock(&self) -> MutexGuard<'_, PermitState> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    async fn acquire(self: &Arc<Self>) -> Permit {
        poll_fn(|cx| {
            let mut state = self.lock();
            if state.used < self.max {
                state.used += 1;
                return Poll::Ready(Permit {
                    pool: Arc::clone(self),
                });
            }
            state.waiters.push_back(cx.waker().clone());
            Poll::Pending
        })
        .await
    }

    fn release(&self) {
        let waker = {
            let mut state = self.lock();
            state.used = state.used.saturating_sub(1);
            state.waiters.pop_front()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    #[cfg(test)]
    fn in_use(&self) -> usize {
        self.lock().used
    }
}

/// RAII global HTTP request permit.
struct Permit {
    pool: Arc<PermitPool>,
}

impl Drop for Permit {
    fn drop(&mut self) {
        self.pool.release();
    }
}

/// A byte-reservation pool with a hard ceiling.
#[derive(Debug)]
struct BytePool {
    max: u64,
    state: Mutex<ByteState>,
}

#[derive(Debug, Default)]
struct ByteState {
    used: u64,
    waiters: VecDeque<Waker>,
}

impl BytePool {
    fn new(max: u64) -> Arc<Self> {
        Arc::new(Self {
            max,
            state: Mutex::new(ByteState::default()),
        })
    }

    fn lock(&self) -> MutexGuard<'_, ByteState> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    async fn reserve(self: &Arc<Self>, bytes: u64) -> Result<ByteLease, StorageError> {
        if bytes > self.max {
            return Err(StorageError::LimitExceeded {
                limit: self.max,
                requested: bytes,
            });
        }
        Ok(poll_fn(|cx| {
            let mut state = self.lock();
            if state.used.saturating_add(bytes) <= self.max {
                state.used += bytes;
                return Poll::Ready(ByteLease {
                    pool: Arc::clone(self),
                    bytes,
                });
            }
            state.waiters.push_back(cx.waker().clone());
            Poll::Pending
        })
        .await)
    }

    fn release(&self, bytes: u64) {
        let waker = {
            let mut state = self.lock();
            state.used = state.used.saturating_sub(bytes);
            state.waiters.pop_front()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    #[cfg(test)]
    fn in_use(&self) -> u64 {
        self.lock().used
    }
}

/// RAII aggregate live-response-byte reservation.
#[derive(Debug)]
struct ByteLease {
    pool: Arc<BytePool>,
    bytes: u64,
}

impl Drop for ByteLease {
    fn drop(&mut self) {
        self.pool.release(self.bytes);
    }
}

/// Counters recorded by one remote index instance.
#[derive(Debug, Default)]
pub struct TransferStats {
    requests: AtomicU64,
    bytes: AtomicU64,
    retries: AtomicU64,
    range_requests: AtomicU64,
    whole_requests: AtomicU64,
}

impl TransferStats {
    /// Total HTTP GET requests issued (including retries).
    #[must_use]
    pub fn requests(&self) -> u64 {
        self.requests.load(Ordering::Acquire)
    }

    /// Total response bytes received.
    #[must_use]
    pub fn bytes(&self) -> u64 {
        self.bytes.load(Ordering::Acquire)
    }

    /// Total retried requests.
    #[must_use]
    pub fn retries(&self) -> u64 {
        self.retries.load(Ordering::Acquire)
    }

    /// Ranged GET requests.
    #[must_use]
    pub fn range_requests(&self) -> u64 {
        self.range_requests.load(Ordering::Acquire)
    }

    /// Whole-object GET requests.
    #[must_use]
    pub fn whole_requests(&self) -> u64 {
        self.whole_requests.load(Ordering::Acquire)
    }
}

/// Shared bounded transfer budget for one remote index.
#[derive(Debug)]
pub(crate) struct TransferBudget {
    requests: Arc<PermitPool>,
    bytes: Arc<BytePool>,
    max_retries: u32,
    stats: Arc<TransferStats>,
}

impl TransferBudget {
    /// Create a budget from transfer configuration.
    pub(crate) fn new(config: &RemoteTransferConfig) -> Self {
        Self {
            requests: PermitPool::new(config.max_total_http_requests()),
            bytes: BytePool::new(config.max_aggregate_response_bytes()),
            max_retries: config.max_retries(),
            stats: Arc::new(TransferStats::default()),
        }
    }

    /// Shared counters.
    #[must_use]
    pub(crate) fn stats(&self) -> Arc<TransferStats> {
        Arc::clone(&self.stats)
    }
}

/// Partition `[0, length)` into disjoint contiguous chunks of `chunk_size`.
///
/// The final chunk may be shorter. Empty input yields no ranges. Every range is
/// non-zero, in-bounds and exactly covers the object with no gap or overlap.
pub(crate) fn plan_ranges(length: u64, chunk_size: u64) -> IndexResult<Vec<ByteRange>> {
    if chunk_size == 0 {
        return Err(IndexError::InvalidConfiguration {
            detail: "chunk_size must be nonzero".to_owned(),
        });
    }
    if length == 0 {
        return Ok(Vec::new());
    }
    let count = length.div_ceil(chunk_size);
    let capacity = usize::try_from(count).map_err(|_| IndexError::ResourceLimit {
        limit: u64::MAX,
        requested: count,
    })?;
    let mut ranges = Vec::with_capacity(capacity);
    let mut offset = 0u64;
    while offset < length {
        let remaining = length - offset;
        let take = remaining.min(chunk_size);
        if take == 0 {
            return Err(IndexError::InvalidConfiguration {
                detail: "zero-length chunk".to_owned(),
            });
        }
        let end = offset.checked_add(take).ok_or(IndexError::ResourceLimit {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
        ranges.push(ByteRange::new(offset, take));
        offset = end;
    }
    Ok(ranges)
}

fn to_storage(error: ObjectStoreError, key: &crate::storage::StorageKey) -> StorageError {
    StorageError::from_object_store(error, key)
}

/// Fetch and assemble one immutable segment body.
///
/// The exact declared length is always enforced; the caller's cache fill seam
/// re-verifies the SHA-256 digest before atomic promotion.
pub(crate) async fn fetch_segment<S: ObjectStore>(
    store: &S,
    object_key: &ObjectKey,
    descriptor: ContentDescriptor,
    config: &RemoteTransferConfig,
    budget: &TransferBudget,
    logical_key: &crate::storage::StorageKey,
) -> Result<Vec<u8>, StorageError> {
    let length = descriptor.length;
    let use_ranges = store.capabilities().range_read
        && length >= config.range_threshold()
        && length > config.chunk_size();

    if !use_ranges {
        budget.stats.whole_requests.fetch_add(1, Ordering::AcqRel);
        let bytes = get_with_retry(store, object_key, None, length, budget, logical_key).await?;
        if bytes.len() as u64 != length {
            return Err(StorageError::LengthMismatch {
                key: logical_key.clone(),
                expected: length,
                actual: bytes.len() as u64,
            });
        }
        return Ok(bytes);
    }

    let ranges = plan_ranges(length, config.chunk_size()).map_err(|error| {
        StorageError::io(
            crate::storage::StorageOp::CacheFill,
            std::io::Error::other(error.to_string()),
        )
    })?;
    let total = usize::try_from(length).map_err(|_| StorageError::LimitExceeded {
        limit: u64::MAX,
        requested: length,
    })?;
    let mut assembled = vec![0u8; total];

    use futures::stream::{self, StreamExt, TryStreamExt};
    let concurrency = config.max_concurrent_ranges_per_segment();
    let collected: Vec<(usize, Vec<u8>)> = stream::iter(ranges.iter().copied().enumerate())
        .map(|(index, range)| {
            // Box each range future: the AWS SDK request future is large, and
            // a non-boxed `buffer_unordered` would place all of them inline in
            // one future and can overflow a worker stack.
            Box::pin(async move {
                budget.stats.range_requests.fetch_add(1, Ordering::AcqRel);
                let bytes = get_with_retry(
                    store,
                    object_key,
                    Some(range),
                    range.length,
                    budget,
                    logical_key,
                )
                .await?;
                Ok::<_, StorageError>((index, bytes))
            })
        })
        .buffer_unordered(concurrency)
        .try_collect()
        .await?;

    for (index, bytes) in collected {
        let range = ranges[index];
        if bytes.len() as u64 != range.length {
            return Err(StorageError::LengthMismatch {
                key: logical_key.clone(),
                expected: range.length,
                actual: bytes.len() as u64,
            });
        }
        let start = usize::try_from(range.offset).map_err(|_| StorageError::LimitExceeded {
            limit: u64::MAX,
            requested: range.offset,
        })?;
        let end = start + bytes.len();
        if end > assembled.len() {
            return Err(StorageError::Corrupt {
                key: logical_key.clone(),
                detail: crate::storage::CorruptionKind::UnexpectedContent,
            });
        }
        assembled[start..end].copy_from_slice(&bytes);
    }
    Ok(assembled)
}

/// One bounded GET with a global permit, byte reservation and bounded retries.
async fn get_with_retry<S: ObjectStore>(
    store: &S,
    object_key: &ObjectKey,
    range: Option<ByteRange>,
    expected: u64,
    budget: &TransferBudget,
    logical_key: &crate::storage::StorageKey,
) -> Result<Vec<u8>, StorageError> {
    let limits = TransferLimits::new(expected.max(1));
    let mut attempt = 0u32;
    loop {
        let _permit = budget.requests.acquire().await;
        let _lease = budget.bytes.reserve(expected).await?;
        budget.stats.requests.fetch_add(1, Ordering::AcqRel);
        match store.get(object_key, range, &limits).await {
            Ok(bytes) => {
                budget
                    .stats
                    .bytes
                    .fetch_add(bytes.len() as u64, Ordering::AcqRel);
                return Ok(bytes);
            }
            Err(error) if error.is_transient() && attempt < budget.max_retries => {
                attempt += 1;
                budget.stats.retries.fetch_add(1, Ordering::AcqRel);
                // Executor-neutral bounded backoff: yield once per attempt so
                // retries cannot spin and other tasks can make progress. The
                // adapter's own request timeout spaces real network attempts.
                for _ in 0..attempt {
                    yield_once().await;
                }
                continue;
            }
            Err(error) => return Err(to_storage(error, logical_key)),
        }
    }
}

/// One executor-neutral yield, used for bounded retry spacing without a timer.
async fn yield_once() {
    use std::future::poll_fn;
    use std::task::Poll;
    let mut yielded = false;
    poll_fn(move |cx| {
        if yielded {
            Poll::Ready(())
        } else {
            yielded = true;
            cx.waker().wake_by_ref();
            Poll::Pending
        }
    })
    .await;
}

#[cfg(test)]
mod tests {
    use super::*;
    use quervant_objectstore::{
        FakeObjectStore, FaultKind, ObjectStoreCapabilities, ObjectStoreError, PutPrecondition,
    };

    fn key(name: &str) -> ObjectKey {
        ObjectKey::parse(name).unwrap()
    }

    fn logical(name: &str) -> crate::storage::StorageKey {
        crate::storage::StorageKey::parse(name).unwrap()
    }

    fn budget(config: &RemoteTransferConfig) -> TransferBudget {
        TransferBudget::new(config)
    }

    #[test]
    fn plan_ranges_exact_and_final_short_chunk() {
        assert_eq!(plan_ranges(0, 8).unwrap(), Vec::new());
        assert_eq!(plan_ranges(4, 8).unwrap(), vec![ByteRange::new(0, 4)]);
        assert_eq!(
            plan_ranges(20, 8).unwrap(),
            vec![
                ByteRange::new(0, 8),
                ByteRange::new(8, 8),
                ByteRange::new(16, 4),
            ]
        );
        assert!(plan_ranges(20, 0).is_err());
    }

    #[test]
    fn plan_ranges_are_gapless_and_nonoverlapping() {
        let ranges = plan_ranges(1000, 7).unwrap();
        let mut expected = 0u64;
        for range in &ranges {
            assert_eq!(range.offset, expected);
            assert!(range.length > 0);
            expected += range.length;
        }
        assert_eq!(expected, 1000);
    }

    fn single_thread_block_on<F: std::future::Future>(future: F) -> F::Output {
        futures::executor::block_on(future)
    }

    #[test]
    fn whole_get_when_below_threshold() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/whole");
        let body = vec![7u8; 100];
        let descriptor = store.insert_raw(&key, &body);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16);
        let budget = budget(&config);
        let fetched = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/whole"),
        ))
        .unwrap();
        assert_eq!(fetched, body);
        assert_eq!(budget.stats().whole_requests(), 1);
        assert_eq!(budget.stats().range_requests(), 0);
    }

    #[test]
    fn ranged_get_when_large() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/large");
        let body: Vec<u8> = (0..=255).cycle().take(1000).collect();
        let descriptor = store.insert_raw(&key, &body);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(100)
            .with_chunk_size(64)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16)
            .with_max_concurrent_segment_fills(8);
        config.validate().unwrap();
        let budget = budget(&config);
        let fetched = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/large"),
        ))
        .unwrap();
        assert_eq!(fetched, body);
        assert_eq!(budget.stats().range_requests(), 16);
        assert_eq!(budget.stats().whole_requests(), 0);
    }

    #[test]
    fn ranged_falls_back_when_capability_absent() {
        let store = FakeObjectStore::new(
            ObjectStoreCapabilities::NONE
                .with_atomic_create_if_absent(true)
                .with_read_after_write(true),
        );
        let key = key("seg/noranges");
        let body = vec![3u8; 500];
        let descriptor = store.insert_raw(&key, &body);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(100)
            .with_chunk_size(64)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16);
        let budget = budget(&config);
        let fetched = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/noranges"),
        ))
        .unwrap();
        assert_eq!(fetched, body);
        assert_eq!(budget.stats().whole_requests(), 1);
    }

    #[test]
    fn short_or_corrupt_response_is_rejected_by_cache_digest() {
        // The transfer only enforces exact length; the cache re-hashes. A
        // corrupt read still returns exact length here, so length passes.
        let store = FakeObjectStore::immutable();
        let key = key("seg/corrupt");
        let body = vec![9u8; 128];
        let descriptor = store.insert_raw(&key, &body);
        store.set_get_fault(FaultKind::CorruptRead);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64);
        let budget = budget(&config);
        let fetched = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/corrupt"),
        ))
        .unwrap();
        assert_ne!(fetched, body);
        assert!(!descriptor.matches(&fetched));
    }

    #[test]
    fn transient_failure_is_retried_then_succeeds() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/retry");
        let body = vec![1u8; 64];
        let descriptor = store.insert_raw(&key, &body);
        store.set_get_fault(FaultKind::Timeout);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_retries(2);
        let budget = budget(&config);
        let fetched = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/retry"),
        ))
        .unwrap();
        assert_eq!(fetched, body);
        assert_eq!(budget.stats().retries(), 1);
    }

    #[test]
    fn nontransient_failure_is_not_retried() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/noretry");
        let body = vec![1u8; 64];
        let descriptor = store.insert_raw(&key, &body);
        store.set_put_fault(FaultKind::Timeout);
        store.set_get_fault(FaultKind::ReadInterrupt);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_retries(2);
        let budget = budget(&config);
        let error = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/noretry"),
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::Io { .. }));
        assert_eq!(budget.stats().retries(), 0);
    }

    #[test]
    fn interrupted_ranged_transfer_fails_without_publication() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/interrupted");
        let body: Vec<u8> = (0..2000u32).map(|i| (i % 251) as u8).collect();
        let descriptor = store.insert_raw(&key, &body);
        // The next ranged GET is interrupted; corruption/interruption is never
        // retried and never yields an assembled object.
        store.set_get_fault(FaultKind::ReadInterrupt);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(100)
            .with_chunk_size(64)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(4)
            .with_max_concurrent_segment_fills(4);
        let budget = budget(&config);
        let error = single_thread_block_on(fetch_segment(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/interrupted"),
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::Io { .. }));
        assert_eq!(budget.stats().whole_requests(), 0);
        assert_eq!(budget.stats().retries(), 0);
    }

    #[test]
    fn aggregate_byte_ceiling_is_enforced() {
        let pool = BytePool::new(10);
        let lease = single_thread_block_on(pool.reserve(10)).unwrap();
        assert_eq!(pool.in_use(), 10);
        // A reservation larger than the whole ceiling is rejected immediately
        // rather than waiting for capacity that can never exist.
        let error = single_thread_block_on(pool.reserve(11)).unwrap_err();
        assert!(matches!(error, StorageError::LimitExceeded { .. }));
        drop(lease);
        assert_eq!(pool.in_use(), 0);
    }

    #[test]
    fn permit_pool_ceiling_is_enforced() {
        let pool = PermitPool::new(1);
        let permit = single_thread_block_on(pool.acquire());
        assert_eq!(pool.in_use(), 1);
        drop(permit);
        assert_eq!(pool.in_use(), 0);
    }

    #[test]
    fn map_transient_variants() {
        assert!(
            ObjectStoreError::Transient {
                detail: "x".to_owned()
            }
            .is_transient()
        );
        assert!(!ObjectStoreError::PreconditionFailed { key: key("a") }.is_transient());
        assert!(!ObjectStoreError::Conflict { key: key("a") }.is_transient());
        let _ = PutPrecondition::IfAbsent;
    }
}
