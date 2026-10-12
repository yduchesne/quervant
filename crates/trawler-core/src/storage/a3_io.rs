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
    ByteRange, ContentDescriptor, FakeObjectStore, ObjectKey, ObjectMetadata, ObjectStore,
    ObjectStoreCapabilities, ObjectStoreError, PutOutcome, PutPrecondition, TransferLimits,
};

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
            |result| result,
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
            |result| result,
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

    let pin_b = futures::executor::block_on(h.cache.prepare(&b)).unwrap();
    assert!(
        h.cache.stats().evictions >= 1,
        "accounting freed despite delete failure"
    );
    assert!(h.cache.stats().published_bytes <= 8);
    assert_eq!(
        read_all(h.cache.open_read(&pin_b).unwrap().as_ref()),
        &[2u8; 8]
    );
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
    let h = harness(
        &fake,
        config(1024, 4, 1024),
        offload(1, 4, 1024),
        Arc::new(BlockingGate::blocked()),
        Arc::new(BlockingGate::released()),
    );
    let mut cx = Context::from_waker(Waker::noop());

    for _ in 0..5 {
        let mut future = Box::pin(h.cache.prepare(&descriptor));
        assert!(future.as_mut().poll(&mut cx).is_pending());
        drop(future);
        assert_eq!(h.cache.stats().in_flight, 0);
        assert_eq!(h.cache.stats().reserved_bytes, 0);
    }
    h.write_gate.release();
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
