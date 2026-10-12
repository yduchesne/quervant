//! PR 3 cache materialization conformance (C-01..C-14) against the production
//! cache seam, the deterministic fake ObjectStore, and the real filesystem
//! `Directory`.

mod common;

use std::future::Future;
use std::sync::{Arc, Condvar, Mutex};
use std::task::Poll;

use common::{TempDir, block_on, poll_once, read_all};
use trawler_core::storage::{
    CacheConfig, Directory, FsDirectory, MemoryDirectory, SegmentCache, SegmentDescriptor,
    StorageError, StorageKey,
};
use trawler_objectstore::{
    ByteRange, ContentDescriptor, FakeObjectStore, FaultKind, ObjectKey, ObjectMetadata,
    ObjectStore, ObjectStoreCapabilities, ObjectStoreError, PutOutcome, PutPrecondition,
    TransferLimits,
};

#[derive(Clone)]
struct SharedStore(Arc<FakeObjectStore>);

impl SharedStore {
    fn new() -> Self {
        Self(Arc::new(FakeObjectStore::immutable()))
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
        let inner = Arc::clone(&self.0);
        let key = key.clone();
        let expected = *expected;
        let body = body.to_vec();
        let limits = *limits;
        inner
            .put(&key, &expected, &body, precondition, &limits)
            .await
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        let inner = Arc::clone(&self.0);
        let key = key.clone();
        let limits = *limits;
        inner.get(&key, range, &limits).await
    }

    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError> {
        let inner = Arc::clone(&self.0);
        let key = key.clone();
        inner.head(&key).await
    }

    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError> {
        let inner = Arc::clone(&self.0);
        let key = key.clone();
        inner.delete(&key).await
    }
}

fn seed(store: &SharedStore, name: &str, body: &[u8]) -> SegmentDescriptor {
    let object_key = ObjectKey::parse(name).unwrap();
    let content = store.0.insert_raw(&object_key, body);
    SegmentDescriptor::new(object_key, content)
}

fn config(max_cache_bytes: u64, max_response_bytes: u64) -> CacheConfig {
    CacheConfig::new(max_cache_bytes, 4, max_response_bytes)
}

// C-01
#[test]
fn c01_empty_cache_materializes_verified_bytes() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"alpha");
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    let pin = block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(pin.descriptor(), descriptor.content);
    assert_eq!(read_all(cache.open_read(&pin).unwrap().as_ref()), b"alpha");
    assert_eq!(cache.stats().published_entries, 1);
    assert_eq!(store.0.get_calls(), 1);
}

// C-02
#[test]
fn c02_warm_cache_does_not_refetch() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"alpha");
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    drop(block_on(cache.prepare(&descriptor)).unwrap());
    let pin = block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(store.0.get_calls(), 1);
    assert!(cache.stats().hits >= 1);
    assert_eq!(read_all(cache.open_read(&pin).unwrap().as_ref()), b"alpha");
}

// C-03
#[test]
fn c03_eviction_removes_local_only() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", &[1u8; 4]);
    let b = seed(&store, "objects/b", &[2u8; 6]);
    let directory = MemoryDirectory::new();
    let cache = SegmentCache::new(store.clone(), directory.clone(), config(6, 64));
    let pin_a = block_on(cache.prepare(&a)).unwrap();
    let key_a = pin_a.key().clone();
    drop(pin_a);
    let _pin_b = block_on(cache.prepare(&b)).unwrap();
    assert!(!directory.exists(&key_a).unwrap());
    assert!(store.0.contains(&ObjectKey::parse("objects/a").unwrap()));
    assert!(store.0.delete_calls() == 0);
    assert!(cache.stats().evictions >= 1);
}

// C-04
#[test]
fn c04_reload_after_eviction_is_identical() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", b"reloadable");
    let b = seed(&store, "objects/b", &[9u8; 32]);
    let directory = MemoryDirectory::new();
    let cache = SegmentCache::new(
        store.clone(),
        directory.clone(),
        config(b.content.length, 64),
    );
    drop(block_on(cache.prepare(&a)).unwrap());
    drop(block_on(cache.prepare(&b)).unwrap());
    let reloaded = block_on(cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&reloaded).unwrap().as_ref()),
        b"reloadable"
    );
    assert_eq!(store.0.get_calls(), 3);
}

// C-05
#[test]
fn c05_pinned_entry_is_not_evicted() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", &[1u8; 8]);
    let b = seed(&store, "objects/b", &[2u8; 8]);
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(8, 64));
    let pin_a = block_on(cache.prepare(&a)).unwrap();
    assert!(matches!(
        block_on(cache.prepare(&b)).unwrap_err(),
        StorageError::LimitExceeded { .. }
    ));
    assert_eq!(
        read_all(cache.open_read(&pin_a).unwrap().as_ref()),
        &[1u8; 8]
    );
}

// C-06
#[test]
fn c06_interrupted_download_leaves_no_entry_and_retries() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"payload");
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    store.0.set_get_fault(FaultKind::ReadInterrupt);
    assert!(block_on(cache.prepare(&descriptor)).is_err());
    assert_eq!(cache.stats().published_entries, 0);
    assert_eq!(cache.stats().in_flight, 0);
    let pin = block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
}

// C-07
#[test]
fn c07_corrupt_payload_is_rejected_before_publication() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"payload");
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    store.0.set_get_fault(FaultKind::CorruptRead);
    assert!(matches!(
        block_on(cache.prepare(&descriptor)).unwrap_err(),
        StorageError::IntegrityMismatch { .. }
    ));
    assert_eq!(cache.stats().published_entries, 0);
}

// C-08
#[test]
fn c08_declared_length_mismatch_is_rejected() {
    let store = SharedStore::new();
    let object_key = ObjectKey::parse("objects/a").unwrap();
    let real = store.0.insert_raw(&object_key, b"12345");
    let descriptor = SegmentDescriptor::new(
        object_key,
        ContentDescriptor::new(real.length + 1, real.digest),
    );
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    assert!(matches!(
        block_on(cache.prepare(&descriptor)).unwrap_err(),
        StorageError::LengthMismatch { .. }
    ));
    assert_eq!(cache.stats().published_entries, 0);
}

// C-09
#[test]
fn c09_concurrent_same_identity_coalesces_to_one_fill() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"coalesced payload");
    let gate = Arc::new(Gate::new());
    let gated = GatedStore {
        inner: store.clone(),
        gate: Arc::clone(&gate),
    };
    let cache = Arc::new(SegmentCache::new(
        gated,
        MemoryDirectory::new(),
        config(1024, 1024),
    ));

    let leader_cache = Arc::clone(&cache);
    let leader_descriptor = descriptor.clone();
    let leader = std::thread::spawn(move || {
        let pin = block_on(leader_cache.prepare(&leader_descriptor)).unwrap();
        read_all(leader_cache.open_read(&pin).unwrap().as_ref())
    });
    gate.wait_entered();

    let waiter_cache = Arc::clone(&cache);
    let waiter = std::thread::spawn(move || {
        let pin = block_on(waiter_cache.prepare(&descriptor)).unwrap();
        read_all(waiter_cache.open_read(&pin).unwrap().as_ref())
    });
    while cache.stats().coalesced_waiters == 0 {
        std::thread::yield_now();
    }
    gate.release();

    let leader_bytes = leader.join().unwrap();
    let waiter_bytes = waiter.join().unwrap();
    assert_eq!(leader_bytes, b"coalesced payload");
    assert_eq!(waiter_bytes, b"coalesced payload");
    assert_eq!(store.0.get_calls(), 1);
    assert_eq!(cache.stats().published_entries, 1);
}

// C-10
#[test]
fn c10_oversized_object_is_rejected_deterministically() {
    let store = SharedStore::new();
    let object_key = ObjectKey::parse("objects/huge").unwrap();
    let descriptor =
        SegmentDescriptor::new(object_key, ContentDescriptor::of(b"tiny not tiny enough"));
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(4, 1024));
    assert!(matches!(
        block_on(cache.prepare(&descriptor)).unwrap_err(),
        StorageError::LimitExceeded { .. }
    ));
    assert_eq!(store.0.get_calls(), 0);
}

// C-11
#[test]
fn c11_cancellation_releases_reservation_without_publication() {
    let object_key = ObjectKey::parse("objects/pending").unwrap();
    let descriptor = SegmentDescriptor::new(object_key, ContentDescriptor::of(b"payload"));
    let cache = SegmentCache::new(PendingStore, MemoryDirectory::new(), config(1024, 1024));
    let mut future = Box::pin(cache.prepare(&descriptor));
    assert!(matches!(poll_once(&mut future), Poll::Pending));
    assert_eq!(cache.stats().in_flight, 1);
    assert!(cache.stats().reserved_bytes > 0);
    drop(future);
    assert_eq!(cache.stats().in_flight, 0);
    assert_eq!(cache.stats().reserved_bytes, 0);
    assert_eq!(cache.stats().published_entries, 0);
}

// C-12
#[test]
fn c12_eviction_never_deletes_remote_objects() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", &[1u8; 8]);
    let b = seed(&store, "objects/b", &[2u8; 8]);
    store.0.set_delete_fault(FaultKind::DeleteFailure);
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(8, 64));
    drop(block_on(cache.prepare(&a)).unwrap());
    let _pin_b = block_on(cache.prepare(&b)).unwrap();
    assert!(cache.stats().evictions >= 1);
    assert_eq!(store.0.delete_calls(), 0);
    assert!(store.0.contains(&ObjectKey::parse("objects/a").unwrap()));
}

// C-13
#[test]
fn c13_accounting_at_exact_limit_and_over() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", &[1u8; 10]);
    let b = seed(&store, "objects/b", &[2u8; 10]);
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(10, 64));
    drop(block_on(cache.prepare(&a)).unwrap());
    assert_eq!(cache.stats().published_bytes, 10);
    let _pin_b = block_on(cache.prepare(&b)).unwrap();
    assert_eq!(cache.stats().published_bytes, 10);
    assert!(cache.stats().evictions >= 1);

    let oversized_key = ObjectKey::parse("objects/c").unwrap();
    let oversized = SegmentDescriptor::new(oversized_key, ContentDescriptor::of(&[3u8; 11]));
    assert!(matches!(
        block_on(cache.prepare(&oversized)).unwrap_err(),
        StorageError::LimitExceeded { .. }
    ));
}

// C-14
#[test]
fn c14_restart_with_empty_cache_rematerializes() {
    let store = SharedStore::new();
    let descriptor = seed(&store, "objects/a", b"payload");
    {
        let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
        drop(block_on(cache.prepare(&descriptor)).unwrap());
    }
    let cache = SegmentCache::new(store.clone(), MemoryDirectory::new(), config(1024, 1024));
    let pin = block_on(cache.prepare(&descriptor)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&pin).unwrap().as_ref()),
        b"payload"
    );
    assert_eq!(store.0.get_calls(), 2);
}

// C-01/C-03 on the real filesystem Directory.
#[test]
fn cache_materializes_and_evicts_on_real_filesystem() {
    let store = SharedStore::new();
    let a = seed(&store, "objects/a", b"filesystem a");
    let b = seed(&store, "objects/b", &[7u8; 64]);
    let dir = TempDir::new("cache-fs");
    let cache = SegmentCache::new(
        store.clone(),
        FsDirectory::open(dir.path()).unwrap(),
        config(b.content.length, 1024),
    );
    let pin_a = block_on(cache.prepare(&a)).unwrap();
    let key_a = pin_a.key().clone();
    assert_eq!(
        read_all(cache.open_read(&pin_a).unwrap().as_ref()),
        b"filesystem a"
    );
    drop(pin_a);
    let pin_b = block_on(cache.prepare(&b)).unwrap();

    let inspector = FsDirectory::open(dir.path()).unwrap();
    assert!(!inspector.exists(&key_a).unwrap());
    assert!(store.0.contains(&ObjectKey::parse("objects/a").unwrap()));

    // Reload from the authoritative store after eviction (b is now unpinned).
    drop(pin_b);
    let reloaded = block_on(cache.prepare(&a)).unwrap();
    assert_eq!(
        read_all(cache.open_read(&reloaded).unwrap().as_ref()),
        b"filesystem a"
    );
}

// A store whose `get` blocks until released, to make C-09 deterministic.
struct Gate {
    entered: Mutex<bool>,
    release: Mutex<bool>,
    entered_cv: Condvar,
    release_cv: Condvar,
}

impl Gate {
    fn new() -> Self {
        Self {
            entered: Mutex::new(false),
            release: Mutex::new(false),
            entered_cv: Condvar::new(),
            release_cv: Condvar::new(),
        }
    }

    fn enter(&self) {
        let mut entered = self.entered.lock().unwrap();
        *entered = true;
        self.entered_cv.notify_all();
    }

    fn wait_entered(&self) {
        let mut entered = self.entered.lock().unwrap();
        while !*entered {
            entered = self.entered_cv.wait(entered).unwrap();
        }
    }

    fn wait_release(&self) {
        let mut release = self.release.lock().unwrap();
        while !*release {
            release = self.release_cv.wait(release).unwrap();
        }
    }

    fn release(&self) {
        *self.release.lock().unwrap() = true;
        self.release_cv.notify_all();
    }
}

struct GatedStore {
    inner: SharedStore,
    gate: Arc<Gate>,
}

impl ObjectStore for GatedStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        self.inner.capabilities()
    }

    fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> impl Future<Output = Result<PutOutcome, ObjectStoreError>> + Send {
        self.inner.put(key, expected, body, precondition, limits)
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        let inner = self.inner.clone();
        let gate = Arc::clone(&self.gate);
        let key = key.clone();
        let limits = *limits;
        gate.enter();
        gate.wait_release();
        inner.get(&key, range, &limits).await
    }

    fn head(
        &self,
        key: &ObjectKey,
    ) -> impl Future<Output = Result<ObjectMetadata, ObjectStoreError>> + Send {
        self.inner.head(key)
    }

    fn delete(&self, key: &ObjectKey) -> impl Future<Output = Result<(), ObjectStoreError>> + Send {
        self.inner.delete(key)
    }
}

// A store whose `get` never resolves, for the cancellation test.
struct PendingStore;

impl ObjectStore for PendingStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        ObjectStoreCapabilities::IMMUTABLE_BASELINE
    }

    fn put(
        &self,
        _key: &ObjectKey,
        _expected: &ContentDescriptor,
        _body: &[u8],
        _precondition: PutPrecondition,
        _limits: &TransferLimits,
    ) -> impl Future<Output = Result<PutOutcome, ObjectStoreError>> + Send {
        std::future::pending()
    }

    fn get(
        &self,
        _key: &ObjectKey,
        _range: Option<ByteRange>,
        _limits: &TransferLimits,
    ) -> impl Future<Output = Result<Vec<u8>, ObjectStoreError>> + Send {
        std::future::pending()
    }

    fn head(
        &self,
        _key: &ObjectKey,
    ) -> impl Future<Output = Result<ObjectMetadata, ObjectStoreError>> + Send {
        std::future::pending()
    }

    fn delete(
        &self,
        _key: &ObjectKey,
    ) -> impl Future<Output = Result<(), ObjectStoreError>> + Send {
        std::future::pending()
    }
}

// Local-only usage needs no object store service at all.
#[test]
fn local_only_directory_operations_need_no_remote_service() {
    let directory = MemoryDirectory::new();
    let key = StorageKey::parse("local/only").unwrap();
    directory.atomic_write(&key, b"no service").unwrap();
    assert_eq!(
        read_all(directory.open_read(&key).unwrap().as_ref()),
        b"no service"
    );
}
