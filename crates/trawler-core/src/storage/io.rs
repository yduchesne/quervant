//! Bounded, executor-neutral offloading of blocking filesystem operations.
//!
//! `Directory` is synchronous by contract. Asynchronous cache preparation must
//! not run blocking filesystem calls on the polling/executor thread, so this
//! module provides a small bounded worker pool with waker-based completion. It
//! uses no async runtime and does not require Tokio; the workers are ordinary
//! OS threads that are allowed to block, while the async side only ever parks on
//! wakers.
//!
//! Design and ownership rules are documented in
//! `docs/decisions/PR03_FS_OFFLOAD_DESIGN.md`.

use std::collections::VecDeque;
use std::future::Future;
use std::future::poll_fn;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::task::{Context, Poll, Waker};
use std::thread::JoinHandle;

use super::{Directory, StorageError, StorageOp};

/// Bounds for the filesystem offloader.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct OffloadConfig {
    /// Number of worker threads.
    pub(crate) workers: usize,
    /// Maximum number of queued (not running) jobs.
    pub(crate) max_queued_jobs: usize,
    /// Maximum total payload bytes permitted, queued or running.
    pub(crate) max_queued_bytes: u64,
}

impl OffloadConfig {
    pub(crate) fn new(workers: usize, max_queued_jobs: usize, max_queued_bytes: u64) -> Self {
        assert!(workers > 0, "at least one filesystem worker is required");
        assert!(max_queued_jobs > 0, "queue capacity must be positive");
        Self {
            workers,
            max_queued_jobs,
            max_queued_bytes,
        }
    }

    /// Derive offloader bounds from the cache limits.
    pub(crate) fn from_cache(max_concurrent_fills: usize, max_cache_bytes: u64) -> Self {
        let max_queued_jobs = max_concurrent_fills.saturating_mul(2).max(1);
        Self::new(2, max_queued_jobs, max_cache_bytes.max(1))
    }
}

/// Deferred filesystem work: given the worker directory and whether the job was
/// cancelled before dispatch, perform (or skip) the operation and reconcile.
type Work<D> = Box<dyn FnOnce(&D, bool) + Send>;

struct QueuedJob<D> {
    bytes: u64,
    work: Work<D>,
}

struct OffloadState<D> {
    queue: VecDeque<QueuedJob<D>>,
    queued_bytes: u64,
    admission_wakers: Vec<Waker>,
    shutdown: bool,
}

impl<D> Default for OffloadState<D> {
    fn default() -> Self {
        Self {
            queue: VecDeque::new(),
            queued_bytes: 0,
            admission_wakers: Vec::new(),
            shutdown: false,
        }
    }
}

struct OffloadShared<D> {
    directory: Arc<D>,
    state: Mutex<OffloadState<D>>,
    work_cv: Condvar,
    config: OffloadConfig,
}

impl<D> OffloadShared<D> {
    fn lock_state(&self) -> MutexGuard<'_, OffloadState<D>> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

/// A bounded dispatcher for synchronous `Directory` operations.
pub(crate) struct Offloader<D> {
    shared: Arc<OffloadShared<D>>,
    workers: Mutex<Vec<JoinHandle<()>>>,
}

impl<D: Directory + 'static> Offloader<D> {
    /// Start `config.workers` worker threads bound to `directory`.
    pub(crate) fn new(directory: Arc<D>, config: OffloadConfig) -> Self {
        let shared = Arc::new(OffloadShared {
            directory,
            state: Mutex::new(OffloadState::default()),
            work_cv: Condvar::new(),
            config,
        });
        let mut workers = Vec::with_capacity(config.workers);
        for _ in 0..config.workers {
            let shared = Arc::clone(&shared);
            let handle = std::thread::Builder::new()
                .name("trawler-fs-offload".to_string())
                .spawn(move || worker_loop(&shared))
                .expect("spawn filesystem offload worker");
            workers.push(handle);
        }
        Self {
            shared,
            workers: Mutex::new(workers),
        }
    }

    /// Run `op` on a worker and return its reconciled result.
    ///
    /// `op` receives the worker-visible `Directory` and whether the job was
    /// cancelled before dispatch (in which case it must not mutate files).
    /// `reconcile` runs on the worker after `op` and produces the value the
    /// waiter receives; it must not panic.
    pub(crate) async fn submit<T, F, R>(&self, bytes: u64, op: F, reconcile: R) -> T
    where
        F: FnOnce(&D, bool) -> Result<(), StorageError> + Send + 'static,
        R: FnOnce(Result<(), StorageError>) -> T + Send + 'static,
        T: Send + 'static,
    {
        let permit = match self.acquire_capacity(bytes).await {
            Some(permit) => permit,
            // The offloader has shut down; reconcile on the caller without
            // dispatching a job (no filesystem mutation).
            None => return reconcile(Err(StorageError::Cancelled)),
        };
        let (completer, completion) = Completion::channel();
        let work: Work<D> = Box::new(move |directory: &D, force_cancel: bool| {
            let cancelled = force_cancel || completer.is_cancelled();
            let result = if cancelled {
                Err(StorageError::Cancelled)
            } else {
                match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    op(directory, false)
                })) {
                    Ok(result) => result,
                    Err(_) => Err(StorageError::io(
                        StorageOp::CacheFill,
                        std::io::Error::other("filesystem worker panicked"),
                    )),
                }
            };
            let value = reconcile(result);
            completer.complete(value);
        });
        self.enqueue(permit, work);
        completion.await
    }

    /// Stop accepting work, drain/cancel queued jobs, and join the workers.
    ///
    /// Blocks the calling thread and must not be called from an async poll.
    pub(crate) fn shutdown_and_join(&self) {
        {
            let mut state = self.shared.lock_state();
            state.shutdown = true;
            self.shared.work_cv.notify_all();
        }
        let mut workers = self
            .workers
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        for handle in workers.drain(..) {
            let _ = handle.join();
        }
    }

    async fn acquire_capacity(&self, bytes: u64) -> Option<CapacityPermit<D>> {
        poll_fn(|cx| self.poll_capacity(cx, bytes)).await
    }

    fn poll_capacity(&self, cx: &mut Context<'_>, bytes: u64) -> Poll<Option<CapacityPermit<D>>> {
        let mut state = self.shared.lock_state();
        if state.shutdown {
            return Poll::Ready(None);
        }
        if state.queued_bytes.saturating_add(bytes) <= self.shared.config.max_queued_bytes
            && state.queue.len() < self.shared.config.max_queued_jobs
        {
            state.queued_bytes = state.queued_bytes.saturating_add(bytes);
            return Poll::Ready(Some(CapacityPermit {
                shared: Arc::clone(&self.shared),
                bytes,
                consumed: false,
            }));
        }
        state.admission_wakers.push(cx.waker().clone());
        Poll::Pending
    }

    fn enqueue(&self, mut permit: CapacityPermit<D>, work: Work<D>) {
        let mut state = self.shared.lock_state();
        permit.consumed = true;
        state.queue.push_back(QueuedJob {
            bytes: permit.bytes,
            work,
        });
        self.shared.work_cv.notify_one();
    }
}

#[cfg(test)]
impl<D> Offloader<D> {
    pub(crate) fn is_shutdown(&self) -> bool {
        self.shared.lock_state().shutdown
    }

    pub(crate) fn queued_bytes(&self) -> u64 {
        self.shared.lock_state().queued_bytes
    }

    pub(crate) fn queue_len(&self) -> usize {
        self.shared.lock_state().queue.len()
    }
}

impl<D> Drop for Offloader<D> {
    fn drop(&mut self) {
        // Signal shutdown but never join here: drop may run on an executor
        // thread. Workers finish the current job, drain-cancel the queue and
        // exit on their own. Dropping the handles detaches them.
        if let Ok(mut state) = self.shared.state.lock() {
            state.shutdown = true;
            self.shared.work_cv.notify_all();
        }
        if let Ok(mut workers) = self.workers.lock() {
            workers.clear();
        }
    }
}

struct CapacityPermit<D> {
    shared: Arc<OffloadShared<D>>,
    bytes: u64,
    consumed: bool,
}

impl<D> Drop for CapacityPermit<D> {
    fn drop(&mut self) {
        if self.consumed {
            return;
        }
        let wakers = {
            let mut state = self.shared.lock_state();
            state.queued_bytes = state.queued_bytes.saturating_sub(self.bytes);
            std::mem::take(&mut state.admission_wakers)
        };
        for waker in wakers {
            waker.wake();
        }
    }
}

fn worker_loop<D: Directory + 'static>(shared: &Arc<OffloadShared<D>>) {
    loop {
        let job = {
            let mut state = shared.lock_state();
            loop {
                if let Some(job) = state.queue.pop_front() {
                    break Some(job);
                }
                if state.shutdown {
                    break None;
                }
                state = shared
                    .work_cv
                    .wait(state)
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
            }
        };
        let Some(job) = job else {
            return;
        };

        let shutting_down = shared.lock_state().shutdown;
        let directory = Arc::clone(&shared.directory);
        (job.work)(&directory, shutting_down);

        let wakers = {
            let mut state = shared.lock_state();
            state.queued_bytes = state.queued_bytes.saturating_sub(job.bytes);
            std::mem::take(&mut state.admission_wakers)
        };
        for waker in wakers {
            waker.wake();
        }
    }
}

// ---------------------------------------------------------------------------
// One-shot, race-free completion.
// ---------------------------------------------------------------------------

struct CompletionState<T> {
    result: Option<T>,
    waker: Option<Waker>,
}

struct CompletionInner<T> {
    state: Mutex<CompletionState<T>>,
    cancelled: AtomicBool,
}

impl<T> CompletionInner<T> {
    fn lock(&self) -> MutexGuard<'_, CompletionState<T>> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

struct Completer<T> {
    inner: Arc<CompletionInner<T>>,
}

impl<T> Completer<T> {
    fn is_cancelled(&self) -> bool {
        self.inner.cancelled.load(Ordering::SeqCst)
    }

    fn complete(&self, value: T) {
        let waker = {
            let mut state = self.inner.lock();
            state.result = Some(value);
            state.waker.take()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
    }
}

/// The waiter half of a completion. Dropping it marks the job cancelled, which
/// lets a queued job be skipped before it dispatches its syscall.
struct Completion<T> {
    inner: Arc<CompletionInner<T>>,
}

impl<T> Completion<T> {
    fn channel() -> (Completer<T>, Self) {
        let inner = Arc::new(CompletionInner {
            state: Mutex::new(CompletionState {
                result: None,
                waker: None,
            }),
            cancelled: AtomicBool::new(false),
        });
        (
            Completer {
                inner: Arc::clone(&inner),
            },
            Self { inner },
        )
    }
}

impl<T> Future for Completion<T> {
    type Output = T;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<T> {
        let mut state = self.inner.lock();
        if let Some(result) = state.result.take() {
            return Poll::Ready(result);
        }
        state.waker = Some(cx.waker().clone());
        Poll::Pending
    }
}

impl<T> Drop for Completion<T> {
    fn drop(&mut self) {
        self.inner.cancelled.store(true, Ordering::SeqCst);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::MemoryDirectory;
    use crate::storage::StorageKey;

    fn key(name: &str) -> StorageKey {
        StorageKey::parse(name).unwrap()
    }

    #[test]
    fn offloader_runs_work_and_completes() {
        let directory = Arc::new(MemoryDirectory::new());
        let offloader = Offloader::new(Arc::clone(&directory), OffloadConfig::new(1, 4, 1024));
        let target = key("offloaded");
        let result = futures::executor::block_on(offloader.submit(
            0,
            move |dir, cancelled| {
                assert!(!cancelled);
                dir.atomic_write(&target, b"value")
            },
            |result| result,
        ));
        assert!(result.is_ok());
        assert!(directory.exists(&key("offloaded")).unwrap());
        offloader.shutdown_and_join();
    }
}
