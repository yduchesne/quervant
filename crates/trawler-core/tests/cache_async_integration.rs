//! Amendment #2 A2-ASYNC-01..12: executor-neutral, nonblocking cache
//! synchronization on a deterministic single-thread executor.
//!
//! No test uses sleeps or blocking waits as an ordering oracle. The remote
//! boundary is a controllable fake whose `get` parks on waker-based gates; the
//! local boundary is the real `MemoryDirectory` (and `FsDirectory` for A2-12).

mod common;

use std::cell::RefCell;
use std::future::poll_fn;
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};

use common::{TempDir, read_all};
use futures::executor::LocalPool;
use futures::task::LocalSpawnExt;
use trawler_core::storage::{
    CacheConfig, Directory, FsDirectory, MemoryDirectory, ReadHandle, SegmentCache,
    SegmentDescriptor, StorageError, StorageKey, StorageOp, WriteHandle,
};
use trawler_objectstore::{
    ByteRange, ContentDescriptor, FakeObjectStore, FaultKind, ObjectKey, ObjectMetadata,
    ObjectStore, ObjectStoreCapabilities, ObjectStoreError, PutOutcome, PutPrecondition,
    TransferLimits,
};

type Results = Rc<RefCell<Vec<Result<Vec<u8>, StorageError>>>>;

// ---------------------------------------------------------------------------
// Controllable, executor-neutral remote boundary.
// ---------------------------------------------------------------------------

#[derive(Default)]
struct GateState {
    released: bool,
    wakers: Vec<Waker>,
}

#[derive(Default)]
struct Gate {
    state: Mutex<GateState>,
}

impl Gate {
    fn wait(&self) -> impl std::future::Future<Output = ()> + '_ {
        poll_fn(|cx| {
            let mut state = self.state.lock().unwrap();
            if state.released {
                Poll::Ready(())
            } else {
                state.wakers.push(cx.waker().clone());
                Poll::Pending
            }
        })
    }

    fn release(&self) {
        let wakers = {
            let mut state = self.state.lock().unwrap();
            state.released = true;
            std::mem::take(&mut state.wakers)
        };
        for waker in wakers {
            waker.wake();
        }
    }

    fn reset(&self) {
        self.state.lock().unwrap().released = false;
    }
}

/// Wraps the deterministic fake and parks every `get` until released.
struct GateStore {
    fake: Arc<FakeObjectStore>,
    gate: Arc<Gate>,
    fault_after_gate: Mutex<Option<FaultKind>>,
}

impl GateStore {
    fn new(fake: Arc<FakeObjectStore>, gate: Arc<Gate>) -> Self {
        Self {
            fake,
            gate,
            fault_after_gate: Mutex::new(None),
        }
    }

    fn fail_next_get(&self, fault: FaultKind) {
        *self.fault_after_gate.lock().unwrap() = Some(fault);
    }
}

impl ObjectStore for GateStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        self.fake.capabilities()
    }

    async fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> Result<PutOutcome, ObjectStoreError> {
        self.fake
            .put(key, expected, body, precondition, limits)
            .await
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        self.gate.wait().await;
        if let Some(fault) = self.fault_after_gate.lock().unwrap().take() {
            self.fake.set_get_fault(fault);
        }
        self.fake.get(key, range, limits).await
    }

    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError> {
        self.fake.head(key).await
    }

    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError> {
        self.fake.delete(key).await
    }
}

/// A local directory whose first N `atomic_write` calls fail.
struct FailOnceDirectory {
    inner: MemoryDirectory,
    remaining: AtomicUsize,
}

impl FailOnceDirectory {
    fn new(inner: MemoryDirectory, failures: usize) -> Self {
        Self {
            inner,
            remaining: AtomicUsize::new(failures),
        }
    }
}

impl Directory for FailOnceDirectory {
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
        let remaining = self.remaining.load(Ordering::SeqCst);
        if remaining > 0 {
            self.remaining.store(remaining - 1, Ordering::SeqCst);
            return Err(StorageError::io(
                StorageOp::AtomicWrite,
                std::io::Error::other("injected promotion failure"),
            ));
        }
        self.inner.atomic_write(key, data)
    }

    fn sync(&self) -> Result<(), StorageError> {
        self.inner.sync()
    }
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

fn seed(fake: &FakeObjectStore, name: &str, body: &[u8]) -> SegmentDescriptor {
    let object_key = ObjectKey::parse(name).unwrap();
    let content = fake.insert_raw(&object_key, body);
    SegmentDescriptor::new(object_key, content)
}

fn config(max_cache_bytes: u64, fills: usize, max_response_bytes: u64) -> CacheConfig {
    CacheConfig::new(max_cache_bytes, fills, max_response_bytes)
}

fn spawn_prepare<S, D>(
    spawner: &futures::executor::LocalSpawner,
    cache: Arc<SegmentCache<S, D>>,
    descriptor: SegmentDescriptor,
    results: Results,
) where
    S: ObjectStore + 'static,
    D: Directory + 'static,
{
    spawner
        .spawn_local(async move {
            let result = match cache.prepare(&descriptor).await {
                Ok(pin) => match cache.open_read(&pin) {
                    Ok(reader) => Ok(read_all(reader.as_ref())),
                    Err(error) => Err(error),
                },
                Err(error) => Err(error),
            };
            results.borrow_mut().push(result);
        })
        .unwrap();
}

fn completed(results: &Results) -> usize {
    results.borrow().len()
}

// ---------------------------------------------------------------------------

// A2-ASYNC-01
#[test]
fn a2_async_01_same_identity_coalesces_on_single_thread() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"shared bytes");
    let cache = Arc::new(SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 4, 1024),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results: Results = Rc::new(RefCell::new(Vec::new()));

    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run_until_stalled();
    assert_eq!(
        completed(&results),
        0,
        "leader should be parked in remote GET"
    );

    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run_until_stalled();
    assert_eq!(
        completed(&results),
        0,
        "follower should be parked on the fill"
    );

    gate.release();
    pool.run();

    let results = results.borrow();
    assert_eq!(results.len(), 2);
    for result in results.iter() {
        assert_eq!(result.as_ref().unwrap(), b"shared bytes");
    }
    assert_eq!(fake.get_calls(), 1, "exactly one remote GET");
}

// A2-ASYNC-02
#[test]
fn a2_async_02_second_identity_yields_for_fill_slot() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let first = seed(&fake, "objects/a", b"first");
    let second = seed(&fake, "objects/b", b"second");
    let cache = Arc::new(SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 1, 1024),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results: Results = Rc::new(RefCell::new(Vec::new()));

    spawn_prepare(&spawner, Arc::clone(&cache), first, Rc::clone(&results));
    pool.run_until_stalled();
    spawn_prepare(&spawner, Arc::clone(&cache), second, Rc::clone(&results));
    pool.run_until_stalled();
    assert_eq!(
        completed(&results),
        0,
        "second fill must await the slot, not deadlock"
    );

    gate.release();
    pool.run();
    assert_eq!(results.borrow().len(), 2);
    assert_eq!(fake.get_calls(), 2);
}

// A2-ASYNC-03
#[test]
fn a2_async_03_many_followers_no_lost_wakeup() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"many");
    let cache = Arc::new(SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 8, 1024),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results: Results = Rc::new(RefCell::new(Vec::new()));

    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run_until_stalled();
    for _ in 0..5 {
        spawn_prepare(
            &spawner,
            Arc::clone(&cache),
            descriptor.clone(),
            Rc::clone(&results),
        );
    }
    pool.run_until_stalled();
    assert_eq!(completed(&results), 0);
    gate.release();
    pool.run();
    assert_eq!(results.borrow().len(), 6);
    assert_eq!(fake.get_calls(), 1);

    // Followers arriving after completion hit the warm published entry.
    gate.reset();
    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run();
    assert_eq!(results.borrow().len(), 7);
    assert_eq!(fake.get_calls(), 1);
    assert!(cache.stats().hits >= 1);
}

// A2-ASYNC-04
#[test]
fn a2_async_04_drop_leader_wakes_followers_without_stale_fill() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 4, 1024),
    );
    let mut leader = Box::pin(cache.prepare(&descriptor));
    let mut follower = Box::pin(cache.prepare(&descriptor));
    let mut cx = Context::from_waker(Waker::noop());

    assert!(leader.as_mut().poll(&mut cx).is_pending());
    assert!(follower.as_mut().poll(&mut cx).is_pending());
    drop(leader);

    let outcome = follower.as_mut().poll(&mut cx);
    assert!(matches!(outcome, Poll::Ready(Err(StorageError::Cancelled))));
    let stats = cache.stats();
    assert_eq!(stats.in_flight, 0);
    assert_eq!(stats.reserved_bytes, 0);
    assert_eq!(stats.published_entries, 0);

    // A later retry succeeds and fills the removed slot.
    gate.release();
    let pin = futures::executor::block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
    assert_eq!(cache.stats().published_entries, 1);
}

// A2-ASYNC-05
#[test]
fn a2_async_05_dropping_a_follower_does_not_disturb_others() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 4, 1024),
    );
    let mut leader = Box::pin(cache.prepare(&descriptor));
    let mut follower_one = Box::pin(cache.prepare(&descriptor));
    let mut follower_two = Box::pin(cache.prepare(&descriptor));
    let mut cx = Context::from_waker(Waker::noop());

    assert!(leader.as_mut().poll(&mut cx).is_pending());
    assert!(follower_one.as_mut().poll(&mut cx).is_pending());
    assert!(follower_two.as_mut().poll(&mut cx).is_pending());
    drop(follower_one);

    gate.release();
    let leader_pin = match leader.as_mut().poll(&mut cx) {
        Poll::Ready(Ok(pin)) => pin,
        other => panic!("leader did not complete: {other:?}"),
    };
    let follower_pin = match follower_two.as_mut().poll(&mut cx) {
        Poll::Ready(Ok(pin)) => pin,
        other => panic!("follower did not complete: {other:?}"),
    };
    assert_eq!(
        read_all(cache.open_read(&leader_pin).unwrap().as_ref()),
        b"payload"
    );
    assert_eq!(
        read_all(cache.open_read(&follower_pin).unwrap().as_ref()),
        b"payload"
    );
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);
}

// A2-ASYNC-06
#[test]
fn a2_async_06_cancellation_around_reservation_and_publication_is_consistent() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 4, 1024),
    );
    let mut cx = Context::from_waker(Waker::noop());

    // Cancellation while a reservation is held.
    let mut future = Box::pin(cache.prepare(&descriptor));
    assert!(future.as_mut().poll(&mut cx).is_pending());
    assert_eq!(cache.stats().in_flight, 1);
    assert!(cache.stats().reserved_bytes > 0);
    drop(future);
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);

    // Cancellation after publication is covered by the pin-ownership unit
    // tests; here we confirm a successful claim leaves no leak.
    gate.release();
    let pin = futures::executor::block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(cache.stats().published_entries, 1);
    drop(pin);
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);
}

// A2-ASYNC-07
#[test]
fn a2_async_07_terminal_failure_reaches_all_followers() {
    struct Case {
        name: &'static str,
        fault: Option<FaultKind>,
        body: &'static [u8],
        wrong_length: bool,
        expected: fn(&StorageError) -> bool,
    }
    let cases = [
        Case {
            name: "not-found",
            fault: None,
            body: b"missing",
            wrong_length: false,
            expected: |error| matches!(error, StorageError::NotFound { .. }),
        },
        Case {
            name: "backend",
            fault: Some(FaultKind::ReadInterrupt),
            body: b"payload",
            wrong_length: false,
            expected: |error| matches!(error, StorageError::Io { .. }),
        },
        Case {
            name: "digest",
            fault: Some(FaultKind::CorruptRead),
            body: b"payload",
            wrong_length: false,
            expected: |error| matches!(error, StorageError::IntegrityMismatch { .. }),
        },
        Case {
            name: "length",
            fault: None,
            body: b"payload",
            wrong_length: true,
            expected: |error| matches!(error, StorageError::LengthMismatch { .. }),
        },
    ];

    for case in cases {
        let fake = Arc::new(FakeObjectStore::immutable());
        let gate = Arc::new(Gate::default());
        let object_key = ObjectKey::parse(format!("objects/{}", case.name)).unwrap();
        let descriptor = if case.name == "not-found" {
            SegmentDescriptor::new(object_key, ContentDescriptor::of(case.body))
        } else {
            let real = fake.insert_raw(&object_key, case.body);
            if case.wrong_length {
                SegmentDescriptor::new(
                    object_key,
                    ContentDescriptor::new(real.length + 1, real.digest),
                )
            } else {
                SegmentDescriptor::new(object_key, real)
            }
        };
        let store = GateStore::new(Arc::clone(&fake), Arc::clone(&gate));
        if let Some(fault) = case.fault {
            store.fail_next_get(fault);
        }
        let cache = Arc::new(SegmentCache::new(
            store,
            MemoryDirectory::new(),
            config(1024, 4, 1024),
        ));
        let mut pool = LocalPool::new();
        let spawner = pool.spawner();
        let results: Results = Rc::new(RefCell::new(Vec::new()));
        spawn_prepare(
            &spawner,
            Arc::clone(&cache),
            descriptor.clone(),
            Rc::clone(&results),
        );
        pool.run_until_stalled();
        for _ in 0..2 {
            spawn_prepare(
                &spawner,
                Arc::clone(&cache),
                descriptor.clone(),
                Rc::clone(&results),
            );
        }
        pool.run_until_stalled();
        gate.release();
        pool.run();

        let results = results.borrow();
        assert_eq!(results.len(), 3, "case {}", case.name);
        for result in results.iter() {
            let error = result.as_ref().expect_err(case.name);
            assert!((case.expected)(error), "case {}: {error:?}", case.name);
        }
        drop(results);
        assert_eq!(cache.stats().published_entries, 0, "case {}", case.name);
        assert_eq!(cache.stats().in_flight, 0, "case {}", case.name);
        assert_eq!(cache.stats().reserved_bytes, 0, "case {}", case.name);

        // Retrying after the failure succeeds when the object is present.
        if case.name != "not-found" {
            gate.reset();
            fake.insert_raw(
                &ObjectKey::parse(format!("objects/{}", case.name)).unwrap(),
                case.body,
            );
            let correct = SegmentDescriptor::new(
                ObjectKey::parse(format!("objects/{}", case.name)).unwrap(),
                ContentDescriptor::of(case.body),
            );
            gate.release();
            let pin = futures::executor::block_on(cache.prepare(&correct)).unwrap();
            assert_eq!(read_all(cache.open_read(&pin).unwrap().as_ref()), case.body);
        }
    }
}

// A2-ASYNC-08
#[test]
fn a2_async_08_pinned_capacity_exhaustion_is_typed() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(8, 4, 64),
    );
    gate.release();
    let pin_a = futures::executor::block_on(cache.prepare(&a)).unwrap();
    assert!(matches!(
        futures::executor::block_on(cache.prepare(&b)),
        Err(StorageError::LimitExceeded { .. })
    ));
    assert_eq!(
        read_all(cache.open_read(&pin_a).unwrap().as_ref()),
        &[1u8; 8]
    );
    assert_eq!(cache.stats().evictions, 0);
}

// A2-ASYNC-09
#[test]
fn a2_async_09_eviction_under_pressure_is_bounded_and_ordered() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let a = seed(&fake, "objects/a", &[1u8; 8]);
    let b = seed(&fake, "objects/b", &[2u8; 8]);
    let c = seed(&fake, "objects/c", &[3u8; 8]);
    let directory = MemoryDirectory::new();
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        directory.clone(),
        config(16, 4, 64),
    );
    gate.release();
    let pin_a = futures::executor::block_on(cache.prepare(&a)).unwrap();
    let key_a = pin_a.key().clone();
    drop(pin_a);
    let pin_b = futures::executor::block_on(cache.prepare(&b)).unwrap();
    let key_b = pin_b.key().clone();
    drop(pin_b);
    assert_eq!(cache.stats().published_bytes, 16);

    let pin_c = futures::executor::block_on(cache.prepare(&c)).unwrap();
    assert!(cache.stats().published_bytes <= 16);
    assert!(cache.stats().evictions >= 1);
    assert_eq!(
        read_all(cache.open_read(&pin_c).unwrap().as_ref()),
        &[3u8; 8]
    );

    // Deterministic LRU: the oldest unpinned entry (a) is evicted first.
    assert!(!directory.exists(&key_a).unwrap());
    assert!(directory.exists(&key_b).unwrap());
    assert!(directory.exists(pin_c.key()).unwrap());
    assert!(fake.contains(&ObjectKey::parse("objects/c").unwrap()));
}

// A2-ASYNC-10
#[test]
fn a2_async_10_failed_promotion_leaks_nothing_and_retries() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"payload");
    let directory = FailOnceDirectory::new(MemoryDirectory::new(), 1);
    let cache = Arc::new(SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        directory,
        config(1024, 4, 1024),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results: Results = Rc::new(RefCell::new(Vec::new()));
    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run_until_stalled();
    spawn_prepare(
        &spawner,
        Arc::clone(&cache),
        descriptor.clone(),
        Rc::clone(&results),
    );
    pool.run_until_stalled();
    gate.release();
    pool.run();

    {
        let results = results.borrow();
        assert_eq!(results.len(), 2);
        for result in results.iter() {
            assert!(matches!(result, Err(StorageError::Io { .. })));
        }
    }
    assert_eq!(cache.stats().published_entries, 0);
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);

    gate.reset();
    gate.release();
    let pin = futures::executor::block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
}

// A2-ASYNC-11
#[test]
fn a2_async_11_wakeup_race_stress_is_deterministic() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let first = seed(&fake, "objects/a", b"first payload");
    let second = seed(&fake, "objects/b", b"second payload");
    let cache = Arc::new(SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        MemoryDirectory::new(),
        config(1024, 2, 1024),
    ));
    let mut pool = LocalPool::new();
    let spawner = pool.spawner();
    let results: Results = Rc::new(RefCell::new(Vec::new()));

    for index in 0..6 {
        let descriptor = if index % 2 == 0 {
            first.clone()
        } else {
            second.clone()
        };
        spawn_prepare(
            &spawner,
            Arc::clone(&cache),
            descriptor,
            Rc::clone(&results),
        );
    }
    pool.run_until_stalled();
    assert_eq!(completed(&results), 0);
    gate.release();
    pool.run();

    assert_eq!(results.borrow().len(), 6);
    assert_eq!(fake.get_calls(), 2, "one fill per identity");
    assert_eq!(cache.stats().published_entries, 2);
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);
}

// A2-ASYNC-12
#[test]
fn a2_async_12_repeated_cancellation_cleans_real_filesystem() {
    let fake = Arc::new(FakeObjectStore::immutable());
    let gate = Arc::new(Gate::default());
    let descriptor = seed(&fake, "objects/a", b"durable payload");
    let dir = TempDir::new("a2-async-12");
    let cache = SegmentCache::new(
        GateStore::new(Arc::clone(&fake), Arc::clone(&gate)),
        FsDirectory::open(dir.path()).unwrap(),
        config(1024, 4, 1024),
    );
    let mut cx = Context::from_waker(Waker::noop());
    for _ in 0..3 {
        let mut future = Box::pin(cache.prepare(&descriptor));
        assert!(future.as_mut().poll(&mut cx).is_pending());
        drop(future);
        assert_eq!(cache.stats().in_flight, 0);
        assert_eq!(cache.stats().reserved_bytes, 0);
    }

    gate.release();
    let pin = futures::executor::block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        b"durable payload"
    );
    assert_eq!(cache.stats().published_entries, 1);

    let leftovers: Vec<String> = std::fs::read_dir(dir.path())
        .unwrap()
        .filter_map(Result::ok)
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .filter(|name| name.starts_with(".trawler-tmp-") || name.starts_with("tmp-v1-"))
        .collect();
    assert!(leftovers.is_empty(), "temporary artifacts: {leftovers:?}");
}
