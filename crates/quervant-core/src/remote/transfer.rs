//! Bounded whole-object and parallel-ranged segment transfer (PR 13).
//!
//! The scheduler streams one immutable segment either as a single bounded
//! `GET` or as disjoint, contiguous exact byte ranges. Bytes are written
//! directly into a cache-owned staged file; this module never assembles a
//! full-segment `Vec` and never collects all chunks before writing.
//!
//! Limits are hard and layered:
//!
//! * global HTTP request permits (`max_total_http_requests`),
//! * per-segment range concurrency (`max_concurrent_ranges_per_segment`),
//! * aggregate retained response bytes (`max_aggregate_response_bytes`),
//!   held by an RAII lease from before the GET until the chunk is written and
//!   its buffer dropped.
//!
//! Only typed transient failures are retried, with a bounded attempt count and
//! a deterministic capped exponential backoff (`100ms, 200ms, …`) obtained from
//! an injected [`Sleeper`] so virtual-time tests are deterministic and the core
//! stays free of an unconditional runtime.

use std::collections::VecDeque;
use std::future::poll_fn;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Poll, Waker};
use std::time::Duration;

use quervant_objectstore::{
    ByteRange, ContentDescriptor, ObjectKey, ObjectStore, ObjectStoreError, TransferLimits,
};

use crate::index::{IndexError, IndexResult};
use crate::storage::cache::StagedWriter;
use crate::storage::{StorageError, StorageKey};

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

/// A byte-reservation pool with a hard ceiling and a peak high-water mark.
#[derive(Debug)]
struct BytePool {
    max: u64,
    state: Mutex<ByteState>,
}

#[derive(Debug, Default)]
struct ByteState {
    used: u64,
    peak: u64,
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
                if state.used > state.peak {
                    state.peak = state.used;
                }
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

/// RAII aggregate retained-response-byte reservation.
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

/// A cancellable delay seam for bounded retry backoff.
///
/// Implementations must complete without blocking a runtime worker; dropping
/// the returned future must cancel the pending sleep.
pub(crate) trait Sleeper: Send + Sync + std::fmt::Debug {
    /// Sleep for `duration`.
    fn sleep(
        &self,
        duration: Duration,
    ) -> Pin<Box<dyn std::future::Future<Output = ()> + Send + '_>>;
}

/// The production sleeper used by the default local build: yields once instead
/// of blocking, so retries cannot spin and no runtime is required.
#[cfg(not(feature = "s3"))]
#[derive(Debug, Default)]
pub(crate) struct ImmediateSleeper;

#[cfg(not(feature = "s3"))]
impl Sleeper for ImmediateSleeper {
    fn sleep(
        &self,
        _duration: Duration,
    ) -> Pin<Box<dyn std::future::Future<Output = ()> + Send + '_>> {
        Box::pin(async {
            yield_once().await;
        })
    }
}

/// A deterministic virtual sleeper that records requested delays and completes
/// immediately. Used by retry tests; contains no clock.
#[cfg(test)]
#[derive(Debug, Default)]
pub(crate) struct VirtualSleeper {
    recorded: Mutex<Vec<Duration>>,
}

#[cfg(test)]
impl VirtualSleeper {
    /// Create an empty virtual sleeper.
    #[must_use]
    pub(crate) fn new() -> Self {
        Self::default()
    }

    /// The delays requested so far, in order.
    pub(crate) fn recorded(&self) -> Vec<Duration> {
        self.recorded
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }
}

#[cfg(test)]
impl Sleeper for VirtualSleeper {
    fn sleep(
        &self,
        duration: Duration,
    ) -> Pin<Box<dyn std::future::Future<Output = ()> + Send + '_>> {
        self.recorded
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .push(duration);
        Box::pin(std::future::ready(()))
    }
}

/// A Tokio-timer sleeper, available only with the S3 remote feature. The
/// default local-only build never compiles or requires it.
#[cfg(feature = "s3")]
#[derive(Debug, Default)]
pub(crate) struct TokioSleeper;

#[cfg(feature = "s3")]
impl Sleeper for TokioSleeper {
    fn sleep(
        &self,
        duration: Duration,
    ) -> Pin<Box<dyn std::future::Future<Output = ()> + Send + '_>> {
        Box::pin(tokio::time::sleep(duration))
    }
}

/// The sleeper used by the remote module: a real timer under the `s3` feature,
/// an executor-neutral yield otherwise.
pub(crate) fn default_sleeper() -> Arc<dyn Sleeper> {
    #[cfg(feature = "s3")]
    {
        Arc::new(TokioSleeper)
    }
    #[cfg(not(feature = "s3"))]
    {
        Arc::new(ImmediateSleeper)
    }
}

/// Shared bounded transfer budget for one remote index.
#[derive(Debug)]
pub(crate) struct TransferBudget {
    requests: Arc<PermitPool>,
    bytes: Arc<BytePool>,
    max_retries: u32,
    sleeper: Arc<dyn Sleeper>,
    stats: Arc<TransferStats>,
}

impl TransferBudget {
    /// Create a budget from transfer configuration and a delay seam.
    pub(crate) fn new(config: &RemoteTransferConfig, sleeper: Arc<dyn Sleeper>) -> Self {
        Self {
            requests: PermitPool::new(config.max_total_http_requests()),
            bytes: BytePool::new(config.max_aggregate_response_bytes()),
            max_retries: config.max_retries(),
            sleeper,
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

/// Deterministic capped exponential backoff: `100ms * 2^(r-1)`, capped at 2s.
fn backoff_delay(attempt: u32) -> Duration {
    let shift = attempt.saturating_sub(1).min(20);
    let millis = 100u64.saturating_mul(1u64 << shift).min(2_000);
    Duration::from_millis(millis)
}

fn to_storage(error: ObjectStoreError, key: &StorageKey) -> StorageError {
    StorageError::from_object_store(error, key)
}

/// One bounded GET response together with the byte lease that owns its
/// accounted memory until the chunk is written and dropped.
struct FetchedChunk {
    bytes: Vec<u8>,
    lease: ByteLease,
}

/// Stream and stage one immutable segment.
///
/// The exact declared length is enforced per chunk; the cache fill seam
/// re-verifies the complete SHA-256 before atomic promotion.
pub(crate) async fn fetch_to_stage<S, W>(
    store: &S,
    object_key: &ObjectKey,
    descriptor: ContentDescriptor,
    config: &RemoteTransferConfig,
    budget: &TransferBudget,
    logical_key: &StorageKey,
    sink: &W,
) -> Result<(), StorageError>
where
    S: ObjectStore,
    W: StagedWriter,
{
    let length = descriptor.length;
    let ranges_supported = store.capabilities().range_read;
    let use_ranges =
        ranges_supported && length >= config.range_threshold() && length > config.chunk_size();

    if !use_ranges {
        // Without range support a whole GET must fit the aggregate ceiling, and
        // that is rejected before any network request.
        if !ranges_supported && length > config.max_aggregate_response_bytes() {
            return Err(StorageError::LimitExceeded {
                limit: config.max_aggregate_response_bytes(),
                requested: length,
            });
        }
        budget.stats.whole_requests.fetch_add(1, Ordering::AcqRel);
        let chunk = get_with_retry(store, object_key, None, length, budget, logical_key).await?;
        if chunk.bytes.len() as u64 != length {
            return Err(StorageError::LengthMismatch {
                key: logical_key.clone(),
                expected: length,
                actual: chunk.bytes.len() as u64,
            });
        }
        let FetchedChunk { bytes, lease } = chunk;
        sink.write_at(0, bytes).await?;
        drop(lease);
        return Ok(());
    }

    let ranges = plan_ranges(length, config.chunk_size()).map_err(|error| {
        StorageError::io(
            crate::storage::StorageOp::CacheFill,
            std::io::Error::other(error.to_string()),
        )
    })?;
    let concurrency = config.max_concurrent_ranges_per_segment();

    use futures::stream::{self, StreamExt};
    let mut stream = stream::iter(ranges)
        .map(|range| {
            // Box each range future: the SDK request future is large.
            Box::pin(async move {
                budget.stats.range_requests.fetch_add(1, Ordering::AcqRel);
                let chunk = get_with_retry(
                    store,
                    object_key,
                    Some(range),
                    range.length,
                    budget,
                    logical_key,
                )
                .await?;
                Ok::<_, StorageError>((range, chunk))
            })
        })
        .buffer_unordered(concurrency);

    // Consume chunks incrementally as they complete; never collect all of them.
    while let Some(item) = stream.next().await {
        let (range, chunk) = item?;
        if chunk.bytes.len() as u64 != range.length {
            return Err(StorageError::LengthMismatch {
                key: logical_key.clone(),
                expected: range.length,
                actual: chunk.bytes.len() as u64,
            });
        }
        let FetchedChunk { bytes, lease } = chunk;
        sink.write_at(range.offset, bytes).await?;
        // The byte lease survives until the staged write completed.
        drop(lease);
    }
    Ok(())
}

/// One bounded GET with a global permit, byte reservation and bounded timed
/// retries. The returned lease remains held by the returned chunk.
async fn get_with_retry<S: ObjectStore>(
    store: &S,
    object_key: &ObjectKey,
    range: Option<ByteRange>,
    expected: u64,
    budget: &TransferBudget,
    logical_key: &StorageKey,
) -> Result<FetchedChunk, StorageError> {
    let limits = TransferLimits::new(expected.max(1));
    let mut attempt = 0u32;
    loop {
        let permit = budget.requests.acquire().await;
        let lease = budget.bytes.reserve(expected).await?;
        budget.stats.requests.fetch_add(1, Ordering::AcqRel);
        match store.get(object_key, range, &limits).await {
            Ok(bytes) => {
                budget
                    .stats
                    .bytes
                    .fetch_add(bytes.len() as u64, Ordering::AcqRel);
                // Release the HTTP permit before the staged write; retain the
                // byte lease with the bytes.
                drop(permit);
                return Ok(FetchedChunk { bytes, lease });
            }
            Err(error) if error.is_transient() && attempt < budget.max_retries => {
                attempt += 1;
                budget.stats.retries.fetch_add(1, Ordering::AcqRel);
                // Release both permits before sleeping.
                drop(permit);
                drop(lease);
                budget.sleeper.sleep(backoff_delay(attempt)).await;
                continue;
            }
            Err(error) => return Err(to_storage(error, logical_key)),
        }
    }
}

/// One executor-neutral yield, used by the immediate sleeper.
#[cfg(not(feature = "s3"))]
async fn yield_once() {
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
        FakeObjectStore, FaultKind, ObjectStoreCapabilities, PutPrecondition,
    };

    fn key(name: &str) -> ObjectKey {
        ObjectKey::parse(name).unwrap()
    }

    fn logical(name: &str) -> StorageKey {
        StorageKey::parse(name).unwrap()
    }

    fn budget(config: &RemoteTransferConfig) -> TransferBudget {
        TransferBudget::new(config, Arc::new(VirtualSleeper::new()))
    }

    fn block_on<F: std::future::Future>(future: F) -> F::Output {
        futures::executor::block_on(future)
    }

    /// In-memory staging writer used to observe the bytes the transfer stages.
    #[derive(Default)]
    struct MemoryStage {
        bytes: Mutex<Vec<u8>>,
    }

    impl MemoryStage {
        fn snapshot(&self) -> Vec<u8> {
            self.bytes
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .clone()
        }
    }

    impl StagedWriter for MemoryStage {
        fn write_at(
            &self,
            offset: u64,
            bytes: Vec<u8>,
        ) -> impl std::future::Future<Output = Result<(), StorageError>> + Send {
            let mut guard = self
                .bytes
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            let end = offset as usize + bytes.len();
            if guard.len() < end {
                guard.resize(end, 0);
            }
            guard[offset as usize..end].copy_from_slice(&bytes);
            drop(guard);
            std::future::ready(Ok(()))
        }
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

    fn config_for_ranges() -> RemoteTransferConfig {
        RemoteTransferConfig::default()
            .with_range_threshold(100)
            .with_chunk_size(64)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(16)
            .with_max_concurrent_segment_fills(8)
    }

    #[test]
    fn whole_get_when_below_threshold_stages_bytes() {
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
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/whole"),
            &stage,
        ))
        .unwrap();
        assert_eq!(stage.snapshot(), body);
        assert_eq!(budget.stats().whole_requests(), 1);
        assert_eq!(budget.stats().range_requests(), 0);
    }

    #[test]
    fn ranged_get_stages_all_chunks_in_order() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/large");
        let body: Vec<u8> = (0..=255).cycle().take(1000).collect();
        let descriptor = store.insert_raw(&key, &body);
        let config = config_for_ranges();
        config.validate().unwrap();
        let budget = budget(&config);
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/large"),
            &stage,
        ))
        .unwrap();
        assert_eq!(stage.snapshot(), body);
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
        let config = config_for_ranges();
        let budget = budget(&config);
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/noranges"),
            &stage,
        ))
        .unwrap();
        assert_eq!(stage.snapshot(), body);
        assert_eq!(budget.stats().whole_requests(), 1);
    }

    #[test]
    fn no_range_support_and_oversize_rejects_before_network() {
        let store = FakeObjectStore::new(
            ObjectStoreCapabilities::NONE
                .with_atomic_create_if_absent(true)
                .with_read_after_write(true),
        );
        let key = key("seg/oversize");
        let body = vec![1u8; 4096];
        let descriptor = store.insert_raw(&key, &body);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(64)
            .with_chunk_size(32)
            .with_max_aggregate_response_bytes(1024)
            .with_max_total_http_requests(64);
        let budget = budget(&config);
        let stage = MemoryStage::default();
        let error = block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/oversize"),
            &stage,
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::LimitExceeded { .. }));
        assert_eq!(store.get_calls(), 0);
    }

    #[test]
    fn interrupted_ranged_transfer_fails_without_publication() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/interrupted");
        let body: Vec<u8> = (0..2000u32).map(|i| (i % 251) as u8).collect();
        let descriptor = store.insert_raw(&key, &body);
        store.set_get_fault(FaultKind::ReadInterrupt);
        let config = config_for_ranges();
        let budget = budget(&config);
        let stage = MemoryStage::default();
        let error = block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/interrupted"),
            &stage,
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::Io { .. }));
        assert_eq!(budget.stats().whole_requests(), 0);
        assert_eq!(budget.stats().retries(), 0);
    }

    #[test]
    fn transient_failure_is_retried_with_backoff_then_succeeds() {
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
        let sleeper = Arc::new(VirtualSleeper::new());
        let budget = TransferBudget::new(&config, Arc::clone(&sleeper) as Arc<dyn Sleeper>);
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/retry"),
            &stage,
        ))
        .unwrap();
        assert_eq!(stage.snapshot(), body);
        assert_eq!(budget.stats().retries(), 1);
        assert_eq!(sleeper.recorded(), vec![Duration::from_millis(100)]);
    }

    #[test]
    fn two_transients_use_100_then_200ms() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/retry2");
        let body = vec![2u8; 64];
        let descriptor = store.insert_raw(&key, &body);
        store.set_get_fault(FaultKind::Timeout);
        store.set_get_fault(FaultKind::Timeout);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_retries(2);
        let sleeper = Arc::new(VirtualSleeper::new());
        let budget = TransferBudget::new(&config, Arc::clone(&sleeper) as Arc<dyn Sleeper>);
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/retry2"),
            &stage,
        ))
        .unwrap();
        assert_eq!(budget.stats().retries(), 2);
        assert_eq!(
            sleeper.recorded(),
            vec![Duration::from_millis(100), Duration::from_millis(200)]
        );
    }

    #[test]
    fn retry_exhaustion_uses_exactly_max_retries_plus_one_attempts() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/exhaust");
        let body = vec![3u8; 64];
        let descriptor = store.insert_raw(&key, &body);
        for _ in 0..5 {
            store.set_get_fault(FaultKind::Timeout);
        }
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_retries(2);
        let sleeper = Arc::new(VirtualSleeper::new());
        let budget = TransferBudget::new(&config, Arc::clone(&sleeper) as Arc<dyn Sleeper>);
        let stage = MemoryStage::default();
        let error = block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/exhaust"),
            &stage,
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::Io { .. }));
        assert_eq!(budget.stats().requests(), 3);
        assert_eq!(budget.stats().retries(), 2);
        assert_eq!(
            sleeper.recorded(),
            vec![Duration::from_millis(100), Duration::from_millis(200)]
        );
    }

    #[test]
    fn nontransient_failure_is_not_retried() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/noretry");
        let body = vec![1u8; 64];
        let descriptor = store.insert_raw(&key, &body);
        store.set_get_fault(FaultKind::ReadInterrupt);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(1024)
            .with_chunk_size(256)
            .with_max_aggregate_response_bytes(1024 * 1024)
            .with_max_total_http_requests(64)
            .with_max_retries(2);
        let sleeper = Arc::new(VirtualSleeper::new());
        let budget = TransferBudget::new(&config, Arc::clone(&sleeper) as Arc<dyn Sleeper>);
        let stage = MemoryStage::default();
        let error = block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/noretry"),
            &stage,
        ))
        .unwrap_err();
        assert!(matches!(error, StorageError::Io { .. }));
        assert_eq!(budget.stats().retries(), 0);
        assert!(sleeper.recorded().is_empty());
    }

    #[test]
    fn aggregate_byte_ceiling_is_enforced() {
        let pool = BytePool::new(10);
        let lease = block_on(pool.reserve(10)).unwrap();
        assert_eq!(pool.in_use(), 10);
        let error = block_on(pool.reserve(11)).unwrap_err();
        assert!(matches!(error, StorageError::LimitExceeded { .. }));
        drop(lease);
        assert_eq!(pool.in_use(), 0);
    }

    #[test]
    fn permit_pool_ceiling_is_enforced() {
        let pool = PermitPool::new(1);
        let permit = block_on(pool.acquire());
        assert_eq!(pool.in_use(), 1);
        drop(permit);
        assert_eq!(pool.in_use(), 0);
    }

    #[test]
    fn retained_response_bytes_peak_stays_within_ceiling() {
        let store = FakeObjectStore::immutable();
        let key = key("seg/peak");
        let body: Vec<u8> = (0..=255).cycle().take(2000).collect();
        let descriptor = store.insert_raw(&key, &body);
        let config = RemoteTransferConfig::default()
            .with_range_threshold(64)
            .with_chunk_size(128)
            .with_max_aggregate_response_bytes(256)
            .with_max_total_http_requests(64)
            .with_max_concurrent_ranges(4)
            .with_max_concurrent_segment_fills(4);
        config.validate().unwrap();
        let budget = budget(&config);
        let stage = MemoryStage::default();
        block_on(fetch_to_stage(
            &store,
            &key,
            descriptor,
            &config,
            &budget,
            &logical("seg/peak"),
            &stage,
        ))
        .unwrap();
        assert_eq!(stage.snapshot(), body);
        // The pool high-water mark never exceeds the aggregate ceiling.
        let pool_peak = budget.bytes.lock().peak;
        assert!(
            pool_peak <= 256,
            "peak retained bytes {pool_peak} exceeded 256"
        );
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
