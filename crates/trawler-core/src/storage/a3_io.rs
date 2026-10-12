//! A3-IO regression tests for bounded, executor-neutral filesystem offloading.
//!
//! Blocking gates stall dedicated filesystem workers, never the single-threaded
//! `LocalPool` executor. There are no sleeps and no timing-based ordering
//! assertions: gates are released explicitly and futures are driven to
//! completion.

use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::task::{Context, Poll, Waker};

use futures::executor::LocalPool;
use futures::task::LocalSpawnExt;
use trawler_objectstore::{
    ByteRange, ContentDescriptor, ContentDigest, FakeObjectStore, ObjectKey, ObjectMetadata,
    ObjectStore, ObjectStoreCapabilities, ObjectStoreError, PutOutcome, PutPrecondition,
    TransferLimits,
};

#[cfg(unix)]
use super::fs::AtomicWriteStep;
use super::fs::FsDirectory;
use super::io::{OffloadConfig, Offloader};
use super::{
    CacheConfig, Directory, MemoryDirectory, ReadHandle, SegmentCache, SegmentDescriptor,
    StorageError, StorageKey, StorageOp, WriteHandle,
};

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct SharedStore(Arc<FakeObjectStore>);

impl SharedStore {
    fn new(fake: Arc<FakeObjectStore>) -> Self {
        Self(fake)
    }
}

impl ObjectStore for SharedStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        self.0.capabilities()
    }

    async fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> Result<PutOutcome, ObjectStoreError> {
        self.0.put(key, expected, body, precondition, limits).await
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        self.0.get(key, range, limits).await
    }

    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError> {
        self.0.head(key).await
    }

    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError> {
        self.0.delete(key).await
    }
}

/// A blocking gate usable only from dedicated worker threads.
struct BlockingGate {
    released: Mutex<bool>,
    cv: Condvar,
}

impl BlockingGate {
    fn released() -> Self {
        Self {
            released: Mutex::new(true),
            cv: Condvar::new(),
        }
    }

    fn blocked() -> Self {
        Self {
            released: Mutex::new(false),
            cv: Condvar::new(),
        }
    }

    fn block(&self) {
        *self.released.lock().unwrap() = false;
    }

    fn release(&self) {
        *self.released.lock().unwrap() = true;
        self.cv.notify_all();
    }

    fn wait(&self) {
        let mut released = self.released.lock().unwrap();
        while !*released {
            released = self.cv.wait(released).unwrap();
        }
    }
}

struct BlockingDirectory {
    inner: MemoryDirectory,
    write_gate: Arc<BlockingGate>,
    delete_gate: Arc<BlockingGate>,
    write_calls: Arc<AtomicUsize>,
    delete_calls: Arc<AtomicUsize>,
    fail_write: Arc<AtomicBool>,
    panic_write: Arc<AtomicBool>,
    fail_delete: Arc<AtomicBool>,
}

impl Directory for BlockingDirectory {
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
        self.delete_calls.fetch_add(1, Ordering::SeqCst);
        self.delete_gate.wait();
        if self.fail_delete.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::Delete,
                std::io::Error::other("injected delete failure"),
            ));
        }
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.write_calls.fetch_add(1, Ordering::SeqCst);
        self.write_gate.wait();
        if self.panic_write.load(Ordering::SeqCst) {
            panic!("injected filesystem worker panic");
        }
        if self.fail_write.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::AtomicWrite,
                std::io::Error::other("injected write failure"),
            ));
        }
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

type TestCache = SegmentCache<SharedStore, BlockingDirectory>;

struct Harness {
    cache: Arc<TestCache>,
    write_calls: Arc<AtomicUsize>,
    delete_calls: Arc<AtomicUsize>,
    fail_write: Arc<AtomicBool>,
    panic_write: Arc<AtomicBool>,
    fail_delete: Arc<AtomicBool>,
    write_gate: Arc<BlockingGate>,
    delete_gate: Arc<BlockingGate>,
}

fn config(max_cache_bytes: u64, fills: usize, max_response_bytes: u64) -> CacheConfig {
    CacheConfig::new(max_cache_bytes, fills, max_response_bytes)
}

fn offload(workers: usize, jobs: usize, bytes: u64) -> OffloadConfig {
    OffloadConfig::new(workers, jobs, bytes)
}

fn seed(fake: &FakeObjectStore, name: &str, body: &[u8]) -> SegmentDescriptor {
    let object_key = ObjectKey::parse(name).unwrap();
    let content = fake.insert_raw(&object_key, body);
    SegmentDescriptor::new(object_key, content)
}

#[allow(clippy::too_many_arguments)]
fn harness(
    fake: &Arc<FakeObjectStore>,
    cache_config: CacheConfig,
    offload_config: OffloadConfig,
    write_gate: Arc<BlockingGate>,
    delete_gate: Arc<BlockingGate>,
) -> Harness {
    let directory = BlockingDirectory {
        inner: MemoryDirectory::new(),
        write_gate: Arc::clone(&write_gate),
        delete_gate: Arc::clone(&delete_gate),
        write_calls: Arc::new(AtomicUsize::new(0)),
        delete_calls: Arc::new(AtomicUsize::new(0)),
        fail_write: Arc::new(AtomicBool::new(false)),
        panic_write: Arc::new(AtomicBool::new(false)),
        fail_delete: Arc::new(AtomicBool::new(false)),
    };
    let write_calls = Arc::clone(&directory.write_calls);
    let delete_calls = Arc::clone(&directory.delete_calls);
    let fail_write = Arc::clone(&directory.fail_write);
    let panic_write = Arc::clone(&directory.panic_write);
    let fail_delete = Arc::clone(&directory.fail_delete);
    let cache = Arc::new(SegmentCache::with_offload(
        SharedStore::new(Arc::clone(fake)),
        directory,
        cache_config,
        offload_config,
    ));
    // Reconciliation is offloaded in production; run it here so deterministic
    // manual-polling tests start from a reconciled ledger.
    cache
        .ensure_reconciled_blocking()
        .expect("reconciliation succeeds for an empty cache root");
    Harness {
        cache,
        write_calls,
        delete_calls,
        fail_write,
        panic_write,
        fail_delete,
        write_gate,
        delete_gate,
    }
}

fn read_all(reader: &dyn ReadHandle) -> Vec<u8> {
    let mut buf = vec![0u8; reader.len() as usize];
    let mut filled = 0;
    while filled < buf.len() {
        let read = reader.read_at(filled as u64, &mut buf[filled..]).unwrap();
        if read == 0 {
            break;
        }
        filled += read;
    }
    buf.truncate(filled);
    buf
}

/// Poll `future` until `condition` holds or the future completes.
///
/// Not a timing oracle: the condition observes a worker-side counter, and the
/// future advances as worker completions become visible.
fn poll_until<F, C>(
    future: &mut Pin<Box<F>>,
    cx: &mut Context<'_>,
    mut condition: C,
) -> Poll<F::Output>
where
    F: Future,
    C: FnMut() -> bool,
{
    loop {
        if let Poll::Ready(value) = future.as_mut().poll(cx) {
            return Poll::Ready(value);
        }
        if condition() {
            return Poll::Pending;
        }
        std::thread::yield_now();
    }
}

fn spin_until(mut condition: impl FnMut() -> bool) {
    while !condition() {
        std::thread::yield_now();
    }
}

// ---------------------------------------------------------------------------
// A3-IO-01..14
// ---------------------------------------------------------------------------

#[test]
fn a3_io_01_stalled_write_does_not_stall_executor() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let progress = Arc::new(AtomicBool::new(false));
    let task_cache = Arc::clone(&h.cache);
    spawner
        .spawn_local(async move {
            let _ = task_cache.prepare(&descriptor).await;
        })
        .unwrap();
    let flag = Arc::clone(&progress);
    spawner
        .spawn_local(async move {
            flag.store(true, Ordering::SeqCst);
        })
        .unwrap();
    pool.run_until_stalled();
    assert!(
        progress.load(Ordering::SeqCst),
        "independent task progressed"
    );
    assert_eq!(h.cache.stats().in_flight, 1);

    h.write_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a3_io_02_stalled_temp_cleanup_does_not_stall_executor() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::blocked()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let progress = Arc::new(AtomicBool::new(false));
    let task_cache = Arc::clone(&h.cache);
    spawner
        .spawn_local(async move {
            let _ = task_cache.prepare(&descriptor).await;
        })
        .unwrap();
    let flag = Arc::clone(&progress);
    spawner
        .spawn_local(async move {
            flag.store(true, Ordering::SeqCst);
        })
        .unwrap();
    pool.run_until_stalled();
    assert!(
        progress.load(Ordering::SeqCst),
        "independent task progressed"
    );
    spin_until(|| h.delete_calls.load(Ordering::SeqCst) >= 1);

    h.delete_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a3_io_03_stalled_eviction_delete_does_not_stall_executor() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    h.delete_gate.block();

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let progress = Arc::new(AtomicBool::new(false));
    let task_cache = Arc::clone(&h.cache);
    spawner
        .spawn_local(async move {
            let _ = task_cache.prepare(&b).await;
        })
        .unwrap();
    let flag = Arc::clone(&progress);
    spawner
        .spawn_local(async move {
            flag.store(true, Ordering::SeqCst);
        })
        .unwrap();
    pool.run_until_stalled();
    assert!(
        progress.load(Ordering::SeqCst),
        "independent task progressed"
    );
    assert_eq!(
        h.cache.stats().evictions,
        0,
        "eviction not finalized while blocked"
    );

    h.delete_gate.release();
    pool.run();
    assert!(h.cache.stats().evictions >= 1);
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a3_io_04_bounded_workers_and_queue_under_saturation() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptors = [
        seed(&fake, "objects/a", b"aaaaa"),
        seed(&fake, "objects/b", b"bbbbb"),
        seed(&fake, "objects/c", b"ccccc"),
    ];
    let h = harness(
        &fake,
        config(1024, 3, 1024),
        offload(1, 1, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    for descriptor in descriptors {
        let task_cache = Arc::clone(&h.cache);
        spawner
            .spawn_local(async move {
                let _ = task_cache.prepare(&descriptor).await;
            })
            .unwrap();
    }
    pool.run_until_stalled();
    assert!(
        h.cache.offload_queue_len() <= 1,
        "queue bounded by max_queued_jobs"
    );

    h.write_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 3);
    h.cache.shutdown();
}

#[test]
fn a3_io_05_cancel_queued_job_before_dispatch_skips_mutation() {
    let directory = Arc::new(MemoryDirectory::new());
    let gate = Arc::new(BlockingGate::blocked());
    let started = Arc::new(AtomicBool::new(false));
    let offloader = Arc::new(Offloader::new(Arc::clone(&directory), offload(1, 4, 1024)));

    let first_gate = Arc::clone(&gate);
    let first_started = Arc::clone(&started);
    let first_offloader = Arc::clone(&offloader);
    let first = std::thread::spawn(move || {
        futures::executor::block_on(first_offloader.submit(
            0,
            move |dir: &MemoryDirectory, _cancelled| {
                first_started.store(true, Ordering::SeqCst);
                first_gate.wait();
                dir.atomic_write(&StorageKey::parse("first").unwrap(), b"first")
            },
            |_directory, result| result,
        ))
    });
    spin_until(|| started.load(Ordering::SeqCst));

    // Second job is queued; drop its future so it is cancelled before dispatch.
    {
        let mut future = Box::pin(offloader.submit(
            0,
            move |dir: &MemoryDirectory, cancelled| {
                assert!(cancelled, "queued job must observe cancellation");
                dir.atomic_write(&StorageKey::parse("second").unwrap(), b"second")
            },
            |_directory, result| result,
        ));
        let mut cx = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut cx).is_pending());
    }
    gate.release();
    assert!(first.join().unwrap().is_ok());
    offloader.shutdown_and_join();
    assert!(
        directory
            .exists(&StorageKey::parse("first").unwrap())
            .unwrap()
    );
    assert!(
        !directory
            .exists(&StorageKey::parse("second").unwrap())
            .unwrap()
    );
}

#[test]
fn a3_io_06_cancel_running_write_holds_reservation_until_reconciled() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );
    let mut cx = Context::from_waker(Waker::noop());

    let mut future = Box::pin(h.cache.prepare(&descriptor));
    assert!(
        poll_until(&mut future, &mut cx, || h
            .write_calls
            .load(Ordering::SeqCst)
            >= 1)
        .is_pending()
    );
    assert_eq!(h.cache.stats().in_flight, 1);
    assert!(h.cache.stats().reserved_bytes > 0);
    drop(future);
    // Dropping the waiter must not release the reservation while running.
    assert_eq!(h.cache.stats().in_flight, 1);
    assert!(h.cache.stats().reserved_bytes > 0);

    h.write_gate.release();
    spin_until(|| h.cache.stats().in_flight == 0);
    assert_eq!(h.cache.stats().reserved_bytes, 0);
    assert_eq!(h.cache.stats().published_bytes, descriptor.content.length);

    let pin = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(h.cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
    h.cache.shutdown();
}

#[test]
fn a3_io_07_cancel_running_delete_keeps_eviction_marker() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    let delete_before = h.delete_calls.load(Ordering::SeqCst);
    h.delete_gate.block();

    let mut cx = Context::from_waker(Waker::noop());
    let mut future = Box::pin(h.cache.prepare(&b));
    assert!(future.as_mut().poll(&mut cx).is_pending());
    spin_until(|| h.delete_calls.load(Ordering::SeqCst) > delete_before);
    assert_eq!(h.cache.stats().published_bytes, 8);
    drop(future);
    assert_eq!(
        h.cache.stats().published_bytes,
        8,
        "eviction marker persists while delete runs"
    );

    h.delete_gate.release();
    spin_until(|| h.cache.stats().published_bytes == 0);
    let pin = futures::executor::block_on(h.cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(h.cache.open_read(&pin).unwrap().as_ref()),
        &[1u8; 8]
    );
    h.cache.shutdown();
}

#[test]
fn a3_io_08_concurrent_same_identity_coalesces_during_slow_write() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"coalesced");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results = Arc::new(Mutex::new(Vec::<Vec<u8>>::new()));
    for _ in 0..3 {
        let task_cache = Arc::clone(&h.cache);
        let descriptor = descriptor.clone();
        let results = Arc::clone(&results);
        spawner
            .spawn_local(async move {
                if let Ok(pin) = task_cache.prepare(&descriptor).await {
                    results
                        .lock()
                        .unwrap()
                        .push(read_all(task_cache.open_read(&pin).unwrap().as_ref()));
                }
            })
            .unwrap();
    }
    pool.run_until_stalled();
    h.write_gate.release();
    pool.run();
    let results = results.lock().unwrap();
    assert_eq!(results.len(), 3);
    assert!(results.iter().all(|bytes| bytes == b"coalesced"));
    assert_eq!(fake.get_calls(), 1);
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a3_io_09_write_error_and_worker_panic_are_typed_and_retryable() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );

    h.fail_write.store(true, Ordering::SeqCst);
    let error = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap_err();
    assert!(matches!(error, StorageError::Io { .. }));
    assert_eq!(h.cache.stats().published_entries, 0);

    h.fail_write.store(false, Ordering::SeqCst);
    h.panic_write.store(true, Ordering::SeqCst);
    let error = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap_err();
    assert!(matches!(error, StorageError::Io { .. }));
    h.panic_write.store(false, Ordering::SeqCst);

    let pin = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(h.cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
    h.cache.shutdown();
}

#[test]
fn a3_io_10_delete_failure_keeps_safe_accounting_and_remote_intact() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    h.fail_delete.store(true, Ordering::SeqCst);

    // The failed delete retains the physical charge, so the second fill cannot
    // be admitted (no overcommit, no tight retry) and `a` stays charged.
    let error = futures::executor::block_on(h.cache.prepare(&b)).unwrap_err();
    assert!(matches!(error, StorageError::LimitExceeded { .. }));
    let stats = h.cache.stats();
    assert!(
        stats.delete_failures >= 1,
        "failed delete must be observable"
    );
    assert!(
        stats.physical_bytes >= 8,
        "failed delete retains the charge"
    );
    assert_eq!(stats.evictions, 0);
    // The authoritative object is never deleted by the cache.
    assert!(fake.contains(&ObjectKey::parse("objects/a").unwrap()));
    h.cache.shutdown();
}

#[test]
fn a3_io_11_shutdown_with_queued_and_running_jobs_does_not_hang() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", b"running payload");
    let b = seed(&fake, "objects/b", b"queued payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 8, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let running_cache = Arc::clone(&h.cache);
    let running = std::thread::spawn(move || {
        futures::executor::block_on(running_cache.prepare(&a)).map(|_| ())
    });
    spin_until(|| h.write_calls.load(Ordering::SeqCst) >= 1);

    let queued_cache = Arc::clone(&h.cache);
    let queued = std::thread::spawn(move || {
        futures::executor::block_on(queued_cache.prepare(&b)).map(|_| ())
    });
    spin_until(|| h.cache.stats().in_flight >= 2);

    let shutdown_cache = Arc::clone(&h.cache);
    let shutdown = std::thread::spawn(move || shutdown_cache.shutdown());
    // Ensure shutdown is observed before the running job can free the worker.
    spin_until(|| h.cache.offload_is_shutdown());
    h.write_gate.release();
    shutdown.join().unwrap();
    let running_result = running.join().unwrap();
    let queued_result = queued.join().unwrap();
    assert!(
        running_result.is_ok(),
        "running job completes: {running_result:?}"
    );
    assert!(
        matches!(queued_result, Err(StorageError::Cancelled)),
        "queued job cancelled by shutdown, got {queued_result:?}"
    );
}

#[test]
fn a3_io_12_real_filesystem_materialize_reopen_evict_reload() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", b"filesystem a");
    let b = seed(&fake, "objects/b", &[7u8; 64]);
    let root = std::env::temp_dir().join(format!("trawler-a3-12-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).unwrap();
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(&root).unwrap(),
        config(b.content.length, 4, 1024),
        offload(2, 8, 1024),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let pin_a = futures::executor::block_on(cache.prepare(&a)).unwrap();
    let key_a = pin_a.key().clone();
    assert_eq!(
        read_all(cache.open_read(&pin_a).unwrap().as_ref()),
        b"filesystem a"
    );
    drop(pin_a);
    let pin_b = futures::executor::block_on(cache.prepare(&b)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin_b).unwrap().as_ref()),
        &[7u8; 64]
    );

    let inspector = FsDirectory::open(&root).unwrap();
    assert!(!inspector.exists(&key_a).unwrap(), "unpinned a was evicted");
    drop(pin_b);
    let reloaded = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&reloaded).unwrap().as_ref()),
        b"filesystem a"
    );
    cache.shutdown();
    let _ = std::fs::remove_dir_all(&root);
}

#[test]
fn a3_io_13_repeated_cancel_retry_stress_returns_to_baseline() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"payload");
    // Block the cleanup delete so every cancelled fill parks before the write
    // job is delegated (deterministic cancellation point).
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::blocked()),
    );
    let mut cx = Context::from_waker(Waker::noop());

    for _ in 0..5 {
        let mut future = Box::pin(h.cache.prepare(&descriptor));
        assert!(future.as_mut().poll(&mut cx).is_pending());
        drop(future);
        assert_eq!(h.cache.stats().in_flight, 0);
        assert_eq!(h.cache.stats().reserved_bytes, 0);
    }
    h.delete_gate.release();
    let pin = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(h.cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a3_io_14_queued_and_in_flight_memory_is_bounded() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", &[3u8; 128]);
    let h = harness(
        &fake,
        config(4096, 4, 4096),
        offload(1, 4, 128),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    for _ in 0..3 {
        let task_cache = Arc::clone(&h.cache);
        let descriptor = descriptor.clone();
        spawner
            .spawn_local(async move {
                let _ = task_cache.prepare(&descriptor).await;
            })
            .unwrap();
    }
    pool.run_until_stalled();
    assert!(
        h.cache.offload_queued_bytes() <= 128,
        "queued/in-flight payload bytes bounded by max_queued_bytes"
    );
    h.write_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

// ---------------------------------------------------------------------------
// A4-01..06: offloaded content verification.
// ---------------------------------------------------------------------------

#[test]
fn a4_01_offloaded_verification_does_not_block_executor() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let body = vec![0x5Au8; 2 * 1024 * 1024];
    let descriptor = seed(&fake, "objects/large", &body);
    let size = body.len() as u64;
    let h = harness(
        &fake,
        config(size, 4, size),
        offload(1, 4, size),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );

    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let progress = Arc::new(AtomicBool::new(false));
    let task_cache = Arc::clone(&h.cache);
    spawner
        .spawn_local(async move {
            let _ = task_cache.prepare(&descriptor).await;
        })
        .unwrap();
    let flag = Arc::clone(&progress);
    spawner
        .spawn_local(async move {
            flag.store(true, Ordering::SeqCst);
        })
        .unwrap();
    pool.run_until_stalled();
    assert!(progress.load(Ordering::SeqCst), "executor stays responsive");
    // Hashing + write run on the worker; the write gate holds it after hashing.
    assert_eq!(h.cache.stats().in_flight, 1);

    h.write_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 1);
    h.cache.shutdown();
}

#[test]
fn a4_02_hash_mismatch_is_typed_and_never_writes() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let object_key = ObjectKey::parse("objects/a").unwrap();
    let body = b"payload bytes";
    fake.insert_raw(&object_key, body);
    // Correct length, deliberately wrong digest.
    let descriptor = SegmentDescriptor::new(
        object_key,
        ContentDescriptor::new(body.len() as u64, ContentDigest::sha256_v1(b"different")),
    );
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    let error = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap_err();
    assert!(matches!(error, StorageError::IntegrityMismatch { .. }));
    assert_eq!(
        h.write_calls.load(Ordering::SeqCst),
        0,
        "hash mismatch must not write"
    );
    assert_eq!(h.cache.stats().published_entries, 0);
    h.cache.shutdown();
}

#[test]
fn a4_03_successful_verification_preserves_identity() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptor = seed(&fake, "objects/a", b"identity payload");
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    let pin = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap();
    assert_eq!(pin.descriptor(), descriptor.content);
    let bytes = read_all(h.cache.open_read(&pin).unwrap().as_ref());
    assert_eq!(ContentDigest::sha256_v1(&bytes), descriptor.content.digest);
    assert_eq!(h.write_calls.load(Ordering::SeqCst), 1);
    h.cache.shutdown();
}

#[test]
fn a4_04_cancel_queued_verification_skips_hash_and_write() {
    let directory = Arc::new(MemoryDirectory::new());
    let gate = Arc::new(BlockingGate::blocked());
    let started = Arc::new(AtomicBool::new(false));
    let ran = Arc::new(AtomicUsize::new(0));
    let offloader = Arc::new(Offloader::new(Arc::clone(&directory), offload(1, 4, 4096)));

    let first_gate = Arc::clone(&gate);
    let first_started = Arc::clone(&started);
    let first_offloader = Arc::clone(&offloader);
    let first = std::thread::spawn(move || {
        futures::executor::block_on(first_offloader.submit(
            0,
            move |dir: &MemoryDirectory, _cancelled| {
                first_started.store(true, Ordering::SeqCst);
                first_gate.wait();
                dir.atomic_write(&StorageKey::parse("first").unwrap(), b"first")
            },
            |_directory, result| result,
        ))
    });
    spin_until(|| started.load(Ordering::SeqCst));

    let ran_clone = Arc::clone(&ran);
    {
        let mut future = Box::pin(offloader.submit(
            0,
            move |_dir: &MemoryDirectory, _cancelled| {
                ran_clone.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
            |_directory, result| result,
        ));
        let mut cx = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut cx).is_pending());
    }
    gate.release();
    assert!(first.join().unwrap().is_ok());
    offloader.shutdown_and_join();
    assert_eq!(ran.load(Ordering::SeqCst), 0, "queued op must not run");
}

#[test]
fn a4_05_cancel_running_verification_holds_reservation() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let body = vec![0x33u8; 1024 * 1024];
    let descriptor = seed(&fake, "objects/large", &body);
    let size = body.len() as u64;
    let h = harness(
        &fake,
        config(size, 4, size),
        offload(1, 4, size),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );
    let mut cx = Context::from_waker(Waker::noop());
    let mut future = Box::pin(h.cache.prepare(&descriptor));
    assert!(
        poll_until(&mut future, &mut cx, || h
            .write_calls
            .load(Ordering::SeqCst)
            >= 1)
        .is_pending()
    );
    assert_eq!(h.cache.stats().in_flight, 1);
    assert!(h.cache.stats().reserved_bytes > 0);
    drop(future);
    assert_eq!(
        h.cache.stats().in_flight,
        1,
        "reservation held while running"
    );

    h.write_gate.release();
    spin_until(|| h.cache.stats().in_flight == 0);
    assert_eq!(h.cache.stats().reserved_bytes, 0);
    let pin = futures::executor::block_on(h.cache.prepare(&descriptor)).unwrap();
    assert_eq!(pin.descriptor(), descriptor.content);
    h.cache.shutdown();
}

#[test]
fn a4_06_many_large_fills_obey_limits() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptors = [
        seed(&fake, "objects/a", &vec![0x7Eu8; 1024 * 1024]),
        seed(&fake, "objects/b", &vec![0x7Fu8; 1024 * 1024]),
        seed(&fake, "objects/c", &vec![0x80u8; 1024 * 1024]),
    ];
    let size = 1024 * 1024u64;
    let h = harness(
        &fake,
        config(size * 4, 3, size),
        offload(1, 4, size),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    for descriptor in descriptors {
        let task_cache = Arc::clone(&h.cache);
        spawner
            .spawn_local(async move {
                let _ = task_cache.prepare(&descriptor).await;
            })
            .unwrap();
    }
    pool.run_until_stalled();
    assert!(h.cache.offload_queued_bytes() <= size);
    assert!(h.cache.stats().reserved_bytes <= size * 4);
    assert!(h.cache.stats().in_flight <= 3);

    h.write_gate.release();
    pool.run();
    assert_eq!(h.cache.stats().published_entries, 3);
    h.cache.shutdown();
}

// ---------------------------------------------------------------------------
// A4-07..16: physical-space accounting, restart reconciliation, failure safety.
// ---------------------------------------------------------------------------

static A4_COUNTER: AtomicUsize = AtomicUsize::new(0);

/// A unique temporary root removed on drop.
struct TestRoot {
    path: std::path::PathBuf,
}

impl TestRoot {
    fn new(tag: &str) -> Self {
        let counter = A4_COUNTER.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("trawler-a4-{tag}-{}-{counter}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self { path }
    }

    fn path(&self) -> &std::path::Path {
        &self.path
    }
}

impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn total_file_len(root: &std::path::Path) -> u64 {
    std::fs::read_dir(root)
        .unwrap()
        .filter_map(Result::ok)
        .filter_map(|entry| entry.metadata().ok())
        .filter(|metadata| metadata.is_file())
        .map(|metadata| metadata.len())
        .sum()
}

/// Real `FsDirectory` whose `atomic_write` can be parked at the temp-created
/// step so tests can inspect the destination/temp overlap on disk.
#[cfg(unix)]
struct GatedFsDirectory {
    inner: FsDirectory,
    write_gate: Arc<BlockingGate>,
    write_started: Arc<AtomicBool>,
    write_calls: Arc<AtomicUsize>,
}

#[cfg(unix)]
impl GatedFsDirectory {
    fn new(inner: FsDirectory, gate: Arc<BlockingGate>) -> Self {
        Self {
            inner,
            write_gate: gate,
            write_started: Arc::new(AtomicBool::new(false)),
            write_calls: Arc::new(AtomicUsize::new(0)),
        }
    }
}

#[cfg(unix)]
impl Directory for GatedFsDirectory {
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
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.write_calls.fetch_add(1, Ordering::SeqCst);
        let gate = Arc::clone(&self.write_gate);
        let started = Arc::clone(&self.write_started);
        self.inner.atomic_write_with_hook(key, data, move |step| {
            if step == AtomicWriteStep::MidTempWrite {
                started.store(true, Ordering::SeqCst);
                gate.wait();
            }
            Ok(())
        })
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

/// Wraps a directory so `list` can be made to fail (restart scan failure).
struct ListFailDirectory<D> {
    inner: D,
    fail_list: Arc<AtomicBool>,
}

impl<D: Directory> Directory for ListFailDirectory<D> {
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
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        if self.fail_list.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::Open,
                std::io::Error::other("injected list failure"),
            ));
        }
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        self.inner.file_len(key)
    }
}

#[test]
fn a4_07_failed_delete_retains_physical_charge() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    h.fail_delete.store(true, Ordering::SeqCst);
    let error = futures::executor::block_on(h.cache.prepare(&b)).unwrap_err();
    assert!(matches!(error, StorageError::LimitExceeded { .. }));
    let stats = h.cache.stats();
    assert!(
        stats.physical_bytes >= 8,
        "failed delete must retain the charge"
    );
    assert!(stats.delete_failures >= 1);
    h.cache.shutdown();
}

#[test]
fn a4_08_repeated_delete_failure_does_not_overadmit_or_spin() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    h.fail_delete.store(true, Ordering::SeqCst);
    assert!(futures::executor::block_on(h.cache.prepare(&b)).is_err());
    let deletes_after_first = h.delete_calls.load(Ordering::SeqCst);
    for _ in 0..3 {
        let error = futures::executor::block_on(h.cache.prepare(&b)).unwrap_err();
        assert!(matches!(error, StorageError::LimitExceeded { .. }));
    }
    assert!(
        h.delete_calls.load(Ordering::SeqCst) <= deletes_after_first + 3,
        "at most one bounded retry per admission"
    );
    assert!(h.cache.stats().physical_bytes <= 8);
    h.cache.shutdown();
}

#[test]
fn a4_09_successful_cleanup_releases_capacity_exactly_once() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let h = harness(
        &fake,
        config(8, 4, 64),
        offload(1, 8, 64),
        Arc::new(BlockingGate::released()),
        Arc::new(BlockingGate::released()),
    );
    drop(futures::executor::block_on(h.cache.prepare(&a)).unwrap());
    h.fail_delete.store(true, Ordering::SeqCst);
    assert!(futures::executor::block_on(h.cache.prepare(&b)).is_err());
    assert!(h.cache.stats().physical_bytes >= 8);
    h.fail_delete.store(false, Ordering::SeqCst);
    let pin_b = futures::executor::block_on(h.cache.prepare(&b)).unwrap();
    assert_eq!(h.cache.stats().physical_bytes, 8);
    assert_eq!(
        read_all(h.cache.open_read(&pin_b).unwrap().as_ref()),
        &[2u8; 8]
    );
    h.cache.shutdown();
}

#[cfg(unix)]
#[test]
fn a4_10_temp_destination_overlap_stays_within_budget() {
    let root = TestRoot::new("a4-10");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[9u8; 32]);
    let len = a.content.length;
    {
        let cache = SegmentCache::with_offload(
            SharedStore::new(Arc::clone(&fake)),
            FsDirectory::open(root.path()).unwrap(),
            config(len, 4, len),
            offload(1, 4, len),
        );
        drop(futures::executor::block_on(cache.prepare(&a)).unwrap());
        cache.shutdown();
    }

    let gate = Arc::new(BlockingGate::blocked());
    let gated = GatedFsDirectory::new(FsDirectory::open(root.path()).unwrap(), Arc::clone(&gate));
    let started = Arc::clone(&gated.write_started);
    let cache = Arc::new(SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        gated,
        config(len * 2, 4, len * 2),
        offload(1, 4, len * 2),
    ));
    cache.ensure_reconciled_blocking().unwrap();
    assert_eq!(cache.stats().orphan_bytes, len);

    let write_cache = Arc::clone(&cache);
    let write = std::thread::spawn(move || {
        futures::executor::block_on(write_cache.prepare(&a)).map(|_| ())
    });
    spin_until(|| started.load(Ordering::SeqCst));
    let on_disk = total_file_len(root.path());
    assert_eq!(on_disk, len * 2, "destination + temp must coexist");
    assert!(on_disk <= len * 2, "actual on-disk bytes exceed the budget");

    gate.release();
    assert!(write.join().unwrap().is_ok());
    assert!(total_file_len(root.path()) <= len);
    cache.shutdown();
}

#[test]
fn a4_11_restart_charges_orphans_before_admission() {
    let root = TestRoot::new("a4-11");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[3u8; 32]);
    {
        let cache = SegmentCache::with_offload(
            SharedStore::new(Arc::clone(&fake)),
            FsDirectory::open(root.path()).unwrap(),
            config(64, 4, 64),
            offload(1, 8, 64),
        );
        drop(futures::executor::block_on(cache.prepare(&a)).unwrap());
        cache.shutdown();
    }
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let stats = cache.stats();
    assert_eq!(stats.orphan_bytes, 32);
    assert_eq!(stats.physical_bytes, 32);

    let b = seed(&fake, "objects/b", &[4u8; 32]);
    let pin = futures::executor::block_on(cache.prepare(&b)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        &[4u8; 32]
    );
    assert!(cache.stats().physical_bytes <= 64);
    cache.shutdown();
}

#[test]
fn a4_12_restart_does_not_treat_orphan_as_verified_hit() {
    let root = TestRoot::new("a4-12");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[3u8; 32]);
    {
        let cache = SegmentCache::with_offload(
            SharedStore::new(Arc::clone(&fake)),
            FsDirectory::open(root.path()).unwrap(),
            config(64, 4, 64),
            offload(1, 8, 64),
        );
        drop(futures::executor::block_on(cache.prepare(&a)).unwrap());
        cache.shutdown();
    }
    let gets_before = fake.get_calls();
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let pin = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert!(
        fake.get_calls() > gets_before,
        "content-addressed orphan must be re-verified, not treated as a hit"
    );
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        &[3u8; 32]
    );
    cache.shutdown();
}

#[test]
fn a4_13_reconciliation_scan_failure_prevents_admission() {
    let root = TestRoot::new("a4-13");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[5u8; 16]);
    let directory = ListFailDirectory {
        inner: FsDirectory::open(root.path()).unwrap(),
        fail_list: Arc::new(AtomicBool::new(true)),
    };
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    assert!(cache.ensure_reconciled_blocking().is_err());
    let error = futures::executor::block_on(cache.prepare(&a)).unwrap_err();
    assert!(matches!(
        error,
        StorageError::Io { .. } | StorageError::Corrupt { .. }
    ));
    assert_eq!(cache.stats().published_entries, 0);
    cache.shutdown();
}

#[test]
fn a4_14_unrelated_file_and_symlink_safety() {
    let fake = Arc::new(FakeObjectStore::immutable());

    let root = TestRoot::new("a4-14-unrelated");
    std::fs::write(root.path().join("index.meta"), b"durable").unwrap();
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    assert!(
        cache.ensure_reconciled_blocking().is_err(),
        "unrelated files fail closed"
    );
    assert!(root.path().join("index.meta").exists());
    cache.shutdown();

    let root2 = TestRoot::new("a4-14-symlink");
    let outside = TestRoot::new("a4-14-outside");
    std::fs::write(outside.path().join("secret"), b"secret").unwrap();
    std::fs::write(root2.path().join("cache-v1-orphan"), b"orphan").unwrap();
    std::os::unix::fs::symlink(outside.path().join("secret"), root2.path().join("link")).unwrap();
    let cache2 = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root2.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache2.ensure_reconciled_blocking().unwrap();
    assert_eq!(cache2.stats().orphan_bytes, 6);
    assert!(root2.path().join("link").exists(), "symlink untouched");
    cache2.shutdown();
}

#[test]
fn a4_15_concurrent_fills_and_evictions_preserve_bound() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptors = [
        seed(&fake, "objects/a", &[1u8; 16]),
        seed(&fake, "objects/b", &[2u8; 16]),
        seed(&fake, "objects/c", &[3u8; 16]),
    ];
    let h = harness(
        &fake,
        config(32, 3, 32),
        offload(1, 4, 32),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    for descriptor in descriptors {
        let task_cache = Arc::clone(&h.cache);
        spawner
            .spawn_local(async move {
                let _ = task_cache.prepare(&descriptor).await;
            })
            .unwrap();
    }
    pool.run_until_stalled();
    assert!(
        h.cache.stats().physical_bytes <= 32,
        "bound held while writes are gated"
    );
    h.write_gate.release();
    pool.run();
    assert!(h.cache.stats().physical_bytes <= 32);
    h.cache.shutdown();
}

#[test]
fn a4_16_real_filesystem_restart_recovery_and_reopen() {
    let root = TestRoot::new("a4-16");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", b"durable payload");
    let b = seed(&fake, "objects/b", &[9u8; 24]);
    {
        let cache = SegmentCache::with_offload(
            SharedStore::new(Arc::clone(&fake)),
            FsDirectory::open(root.path()).unwrap(),
            config(64, 4, 64),
            offload(2, 8, 64),
        );
        let pin_a = futures::executor::block_on(cache.prepare(&a)).unwrap();
        assert_eq!(
            read_all(cache.open_read(&pin_a).unwrap().as_ref()),
            b"durable payload"
        );
        drop(pin_a);
        let pin_b = futures::executor::block_on(cache.prepare(&b)).unwrap();
        assert_eq!(
            read_all(cache.open_read(&pin_b).unwrap().as_ref()),
            &[9u8; 24]
        );
        cache.shutdown();
    }
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(2, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    assert!(cache.stats().orphan_bytes >= 15 + 24);
    let pin_a = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin_a).unwrap().as_ref()),
        b"durable payload"
    );
    let pin_b = futures::executor::block_on(cache.prepare(&b)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin_b).unwrap().as_ref()),
        &[9u8; 24]
    );
    assert!(total_file_len(root.path()) <= 64);
    cache.shutdown();
}

// ---------------------------------------------------------------------------
// A5-01..12: crash-temporary recovery and fail-closed write reconciliation.
// ---------------------------------------------------------------------------

/// Handles to a [`FaultDirectory`]'s injectable switches.
#[derive(Clone)]
struct FaultFlags {
    fail_write: Arc<AtomicBool>,
    fail_list: Arc<AtomicBool>,
    fail_file_len: Arc<AtomicBool>,
    file_len_not_found: Arc<AtomicBool>,
    fail_delete: Arc<AtomicBool>,
    delete_calls: Arc<AtomicUsize>,
}

/// A directory wrapper with independently injectable `atomic_write`,
/// `list`, `file_len` and `delete` failures.
struct FaultDirectory<D> {
    inner: D,
    fail_write: Arc<AtomicBool>,
    fail_list: Arc<AtomicBool>,
    fail_file_len: Arc<AtomicBool>,
    file_len_not_found: Arc<AtomicBool>,
    fail_delete: Arc<AtomicBool>,
    delete_calls: Arc<AtomicUsize>,
}

impl<D> FaultDirectory<D> {
    fn new(inner: D) -> Self {
        Self {
            inner,
            fail_write: Arc::new(AtomicBool::new(false)),
            fail_list: Arc::new(AtomicBool::new(false)),
            fail_file_len: Arc::new(AtomicBool::new(false)),
            file_len_not_found: Arc::new(AtomicBool::new(false)),
            fail_delete: Arc::new(AtomicBool::new(false)),
            delete_calls: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn flags(&self) -> FaultFlags {
        FaultFlags {
            fail_write: Arc::clone(&self.fail_write),
            fail_list: Arc::clone(&self.fail_list),
            fail_file_len: Arc::clone(&self.fail_file_len),
            file_len_not_found: Arc::clone(&self.file_len_not_found),
            fail_delete: Arc::clone(&self.fail_delete),
            delete_calls: Arc::clone(&self.delete_calls),
        }
    }
}

impl<D: Directory> Directory for FaultDirectory<D> {
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
        self.delete_calls.fetch_add(1, Ordering::SeqCst);
        if self.fail_delete.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::Delete,
                std::io::Error::other("injected delete failure"),
            ));
        }
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        if self.fail_write.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::AtomicWrite,
                std::io::Error::other("injected write failure"),
            ));
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }

    fn list(&self, prefix: &str, limit: usize) -> Result<Vec<StorageKey>, StorageError> {
        if self.fail_list.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::Open,
                std::io::Error::other("injected list failure"),
            ));
        }
        self.inner.list(prefix, limit)
    }

    fn file_len(&self, key: &StorageKey) -> Result<u64, StorageError> {
        if self.file_len_not_found.load(Ordering::SeqCst) {
            return Err(StorageError::NotFound { key: key.clone() });
        }
        if self.fail_file_len.load(Ordering::SeqCst) {
            return Err(StorageError::io(
                StorageOp::Open,
                std::io::Error::other("injected metadata failure"),
            ));
        }
        self.inner.file_len(key)
    }
}

fn temp_key(name: &str) -> StorageKey {
    StorageKey::parse(name).unwrap()
}

/// A real filesystem that succeeds the rename but fails the parent-directory
/// sync, leaving the destination present while reporting an error.
#[cfg(unix)]
struct RenameFailDirectory {
    inner: FsDirectory,
}

#[cfg(unix)]
impl Directory for RenameFailDirectory {
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
        self.inner.delete(key)
    }

    fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError> {
        self.inner.atomic_write_with_hook(key, data, |step| {
            if step == AtomicWriteStep::AfterRename {
                Err(StorageError::io(
                    StorageOp::DirSync,
                    std::io::Error::other("injected post-rename failure"),
                ))
            } else {
                Ok(())
            }
        })
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

#[test]
fn a5_01_crash_temp_recognized_and_cleaned() {
    let root = TestRoot::new("a5-01");
    std::fs::write(root.path().join(".trawler-tmp-4242-9"), [0u8; 20]).unwrap();
    let fake = Arc::new(FakeObjectStore::immutable());
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    assert!(
        !root.path().join(".trawler-tmp-4242-9").exists(),
        "recognized crash temp is cleaned"
    );
    assert_eq!(cache.stats().physical_bytes, 0);
    cache.shutdown();
}

#[test]
fn a5_02_partial_temp_charged_at_actual_size() {
    let root = TestRoot::new("a5-02");
    std::fs::write(root.path().join(".trawler-tmp-7-3"), [0u8; 7]).unwrap();
    let fake = Arc::new(FakeObjectStore::immutable());
    let directory = FaultDirectory::new(FsDirectory::open(root.path()).unwrap());
    let flags = directory.flags();
    flags.fail_delete.store(true, Ordering::SeqCst);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    assert_eq!(cache.stats().physical_bytes, 7, "charged at actual size");
    assert!(cache.stats().delete_failures >= 1);
    cache.shutdown();
}

#[test]
fn a5_03_temp_delete_failure_retains_charge_with_bounded_retry() {
    let root = TestRoot::new("a5-03");
    std::fs::write(root.path().join(".trawler-tmp-7-3"), [0u8; 7]).unwrap();
    let fake = Arc::new(FakeObjectStore::immutable());
    let directory = FaultDirectory::new(FsDirectory::open(root.path()).unwrap());
    let flags = directory.flags();
    flags.fail_delete.store(true, Ordering::SeqCst);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(8, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    // 7 charged bytes + an 8-byte object cannot fit into an 8-byte budget.
    let error = futures::executor::block_on(cache.prepare(&a)).unwrap_err();
    assert!(matches!(error, StorageError::LimitExceeded { .. }));
    let deletes = flags.delete_calls.load(Ordering::SeqCst);
    for _ in 0..3 {
        assert!(futures::executor::block_on(cache.prepare(&a)).is_err());
    }
    assert!(
        flags.delete_calls.load(Ordering::SeqCst) <= deletes + 3,
        "bounded retry"
    );
    assert_eq!(cache.stats().physical_bytes, 7);
    cache.shutdown();
}

#[test]
fn a5_04_successful_cleanup_restores_capacity_once() {
    let root = TestRoot::new("a5-04");
    std::fs::write(root.path().join(".trawler-tmp-7-3"), [0u8; 7]).unwrap();
    let fake = Arc::new(FakeObjectStore::immutable());
    let directory = FaultDirectory::new(FsDirectory::open(root.path()).unwrap());
    let flags = directory.flags();
    flags.fail_delete.store(true, Ordering::SeqCst);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(8, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    assert_eq!(cache.stats().physical_bytes, 7);
    flags.fail_delete.store(false, Ordering::SeqCst);
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let pin = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert_eq!(cache.stats().physical_bytes, 8, "capacity restored once");
    assert_eq!(read_all(cache.open_read(&pin).unwrap().as_ref()), &[1u8; 8]);
    cache.shutdown();
}

#[test]
fn a5_05_unknown_and_malformed_temp_fail_closed() {
    let fake = Arc::new(FakeObjectStore::immutable());
    for (tag, name) in [
        ("unknown", "index.meta"),
        ("malformed-pid", ".trawler-tmp-abc"),
        ("extra-dash", ".trawler-tmp-1-2-3"),
        ("empty-counter", ".trawler-tmp-1-"),
    ] {
        let root = TestRoot::new(&format!("a5-05-{tag}"));
        std::fs::write(root.path().join(name), b"x").unwrap();
        let cache = SegmentCache::with_offload(
            SharedStore::new(Arc::clone(&fake)),
            FsDirectory::open(root.path()).unwrap(),
            config(64, 4, 64),
            offload(1, 8, 64),
        );
        assert!(
            cache.ensure_reconciled_blocking().is_err(),
            "{name} must fail closed"
        );
        assert!(root.path().join(name).exists(), "unknown file untouched");
        cache.shutdown();
    }
}

#[test]
fn a5_06_symlink_not_followed_or_deleted() {
    let root = TestRoot::new("a5-06");
    let outside = TestRoot::new("a5-06-outside");
    std::fs::write(outside.path().join("secret"), b"secret").unwrap();
    std::os::unix::fs::symlink(outside.path().join("secret"), root.path().join("link")).unwrap();
    let fake = Arc::new(FakeObjectStore::immutable());
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FsDirectory::open(root.path()).unwrap(),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    assert!(root.path().join("link").exists(), "symlink untouched");
    assert!(outside.path().join("secret").exists());
    cache.shutdown();
}

#[test]
fn a5_07_indeterminate_destination_probe_retains_charge() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[4u8; 32]);
    let directory = FaultDirectory::new(MemoryDirectory::new());
    let flags = directory.flags();
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    flags.fail_write.store(true, Ordering::SeqCst);
    flags.fail_file_len.store(true, Ordering::SeqCst);
    let error = futures::executor::block_on(cache.prepare(&a)).unwrap_err();
    assert!(matches!(error, StorageError::Io { .. }));
    let stats = cache.stats();
    assert_eq!(stats.reserved_bytes, 0);
    assert!(
        stats.physical_bytes >= 32,
        "indeterminate residual retained"
    );
    assert_eq!(stats.published_entries, 0);

    // Repair the probe failure; the re-armed reconciliation clears the charge.
    flags.fail_write.store(false, Ordering::SeqCst);
    flags.fail_file_len.store(false, Ordering::SeqCst);
    cache.ensure_reconciled_blocking().unwrap();
    assert_eq!(cache.stats().physical_bytes, 0);
    cache.shutdown();
}

#[test]
fn a5_08_verified_absence_releases_after_temp_inventory() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[4u8; 32]);
    let directory = FaultDirectory::new(MemoryDirectory::new());
    let flags = directory.flags();
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    flags.fail_write.store(true, Ordering::SeqCst);
    flags.file_len_not_found.store(true, Ordering::SeqCst);
    let error = futures::executor::block_on(cache.prepare(&a)).unwrap_err();
    assert!(matches!(error, StorageError::Io { .. }));
    // Verified absence with no leftover temp: the reservation is released.
    assert_eq!(cache.stats().physical_bytes, 0);
    assert_eq!(cache.stats().published_entries, 0);
    cache.shutdown();
}

#[cfg(unix)]
#[test]
fn a5_09_post_rename_failure_charges_destination_without_publishing() {
    let root = TestRoot::new("a5-09");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[4u8; 32]);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        RenameFailDirectory {
            inner: FsDirectory::open(root.path()).unwrap(),
        },
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let error = futures::executor::block_on(cache.prepare(&a)).unwrap_err();
    assert!(matches!(error, StorageError::Io { .. }));
    assert_eq!(cache.stats().published_entries, 0);
    assert_eq!(cache.stats().physical_bytes, 32, "destination charged");
    assert_eq!(total_file_len(root.path()), 32);
    cache.shutdown();
}

#[cfg(unix)]
#[test]
fn a5_10_cancellation_during_real_write_reconciles() {
    let root = TestRoot::new("a5-10");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[5u8; 32]);
    let gate = Arc::new(BlockingGate::blocked());
    let gated = GatedFsDirectory::new(FsDirectory::open(root.path()).unwrap(), Arc::clone(&gate));
    let started = Arc::clone(&gated.write_started);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        gated,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let mut cx = Context::from_waker(Waker::noop());
    let mut future = Box::pin(cache.prepare(&a));
    assert!(poll_until(&mut future, &mut cx, || started.load(Ordering::SeqCst)).is_pending());
    assert_eq!(cache.stats().in_flight, 1);
    drop(future);
    assert_eq!(cache.stats().in_flight, 1, "reservation held while running");
    gate.release();
    spin_until(|| cache.stats().in_flight == 0);
    assert_eq!(cache.stats().reserved_bytes, 0);
    assert_eq!(cache.stats().physical_bytes, 32);
    assert_eq!(total_file_len(root.path()), 32);
    cache.shutdown();
}

#[test]
fn a5_11_concurrent_fills_and_cleanup_preserve_bound() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let descriptors = [
        seed(&fake, "objects/a", &[1u8; 16]),
        seed(&fake, "objects/b", &[2u8; 16]),
        seed(&fake, "objects/c", &[3u8; 16]),
    ];
    let inner = MemoryDirectory::new();
    inner
        .atomic_write(&temp_key(".trawler-tmp-1-2"), &[0u8; 4])
        .unwrap();
    let cache = Arc::new(SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FaultDirectory::new(inner),
        config(32, 3, 32),
        offload(1, 4, 32),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    for descriptor in descriptors {
        let task_cache = Arc::clone(&cache);
        spawner
            .spawn_local(async move {
                let _ = task_cache.prepare(&descriptor).await;
            })
            .unwrap();
    }
    pool.run();
    assert!(cache.stats().physical_bytes <= 32, "bound preserved");
    cache.shutdown();
}

#[test]
fn a5_12_scan_failure_refuses_admission_then_recovers() {
    let root = TestRoot::new("a5-12");
    let fake = Arc::new(FakeObjectStore::immutable());
    let a = seed(&fake, "objects/a", &[6u8; 16]);
    let directory = FaultDirectory::new(FsDirectory::open(root.path()).unwrap());
    let flags = directory.flags();
    flags.fail_list.store(true, Ordering::SeqCst);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        directory,
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    assert!(cache.ensure_reconciled_blocking().is_err());
    assert!(futures::executor::block_on(cache.prepare(&a)).is_err());
    cache.shutdown();

    // Repair the root and open a fresh cache instance that recovers.
    flags.fail_list.store(false, Ordering::SeqCst);
    let cache = SegmentCache::with_offload(
        SharedStore::new(Arc::clone(&fake)),
        FaultDirectory::new(FsDirectory::open(root.path()).unwrap()),
        config(64, 4, 64),
        offload(1, 8, 64),
    );
    cache.ensure_reconciled_blocking().unwrap();
    let pin = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        &[6u8; 16]
    );
    cache.shutdown();
}
