//! PR 9 recovery, durability barriers and stale handling (T12, T13, T34, T36, T40).

mod pr09_common;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use pr09_common::{create, doc, hit_keys, memory, pr09_registry, pr09_schema, term};

use quervant_core::contract::document::{DocumentKey, IdempotencyKey, MutationRequest};
use quervant_core::index::{Index, IndexError, IndexLimits};
use quervant_core::storage::{
    Directory, MemoryDirectory, ReadHandle, StorageError, StorageKey, WriteHandle,
};

/// A real `MemoryDirectory` wrapper that can fail `CURRENT` publication only
/// after the immutable objects have been written.
struct FailCurrentDirectory {
    inner: MemoryDirectory,
    fail_current: AtomicBool,
}

impl FailCurrentDirectory {
    fn new() -> Self {
        Self {
            inner: MemoryDirectory::new(),
            fail_current: AtomicBool::new(false),
        }
    }

    fn set_fail(&self, value: bool) {
        self.fail_current.store(value, Ordering::SeqCst);
    }
}

impl Directory for FailCurrentDirectory {
    fn create_dir_all(&self, prefix: &str) -> Result<(), StorageError> {
        self.inner.create_dir_all(prefix)
    }
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
        if key.as_str() == "index/CURRENT" && self.fail_current.load(Ordering::SeqCst) {
            return Err(StorageError::Unsupported {
                operation: quervant_core::storage::StorageOp::AtomicWrite,
                platform: "injected fault",
            });
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

// T12/T36 — a pre-CURRENT failure leaves the old generation authoritative and
// the writer retryable; the orphaned immutable objects are retained.
#[test]
fn t12_pre_current_failure_is_recoverable() {
    let fault = Arc::new(FailCurrentDirectory::new());
    let directory: Arc<dyn Directory> = fault.clone();
    let index = create(directory.clone());
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    writer.commit().unwrap();

    fault.set_fail(true);
    writer
        .apply(MutationRequest::insert(doc("b", "two", "", "x", 2)))
        .unwrap();
    let error = writer.commit().unwrap_err();
    assert!(matches!(error, IndexError::Storage(_)));
    // The old generation is still authoritative for a reopen.
    {
        let reopened =
            Index::open_existing(directory.clone(), pr09_schema(), pr09_registry()).unwrap();
        assert_eq!(hit_keys(&reopened.snapshot(), &term("one")), ["a"]);
        assert!(!hit_keys(&reopened.snapshot(), &term("two")).contains(&"b".to_owned()));
    }
    // Safe retry after reconciliation.
    fault.set_fail(false);
    let outcome = writer.commit().unwrap();
    assert_eq!(outcome.generation, 2);
    assert_eq!(hit_keys(&writer.reader(), &term("two")), ["b"]);
}

// T13 — a failed refresh leaves the previously published view unchanged.
#[test]
fn t13_failed_refresh_retains_last_view() {
    let directory = memory();
    let limits = IndexLimits::new().with_max_snapshot_bytes(0);
    let index =
        Index::create_with_limits(directory, pr09_schema(), pr09_registry(), limits).unwrap();
    let mut writer = index.writer().unwrap();
    let first = writer.refresh().unwrap();
    assert_eq!(first.document_count(), 0);
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    let error = writer.refresh().unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    // The previously published empty view is still returned.
    assert_eq!(writer.reader().document_count(), 0);
}

// T34 — exact and one-over resource bounds are enforced before publication.
#[test]
fn t34_resource_bounds_exact_and_one_over() {
    // A state-byte bound of 1 always rejects a real sidecar before publication.
    let directory = memory();
    let limits = IndexLimits::new().with_max_mutation_state_bytes(1);
    let index =
        Index::create_with_limits(directory.clone(), pr09_schema(), pr09_registry(), limits)
            .unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
        .unwrap();
    let error = writer.commit().unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert!(Index::open_existing(directory, pr09_schema(), pr09_registry()).is_err());

    // Replay-ledger capacity: exactly one entry fits.
    let directory = memory();
    let limits = IndexLimits::new().with_max_replay_entries(1);
    let index =
        Index::create_with_limits(directory, pr09_schema(), pr09_registry(), limits).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .apply(
            MutationRequest::insert(doc("a", "one", "", "x", 1))
                .with_idempotency_key(IdempotencyKey::new("t1").unwrap()),
        )
        .unwrap();
    let error = writer
        .apply(
            MutationRequest::insert(doc("b", "two", "", "x", 2))
                .with_idempotency_key(IdempotencyKey::new("t2").unwrap()),
        )
        .unwrap_err();
    assert!(matches!(error, IndexError::ResourceLimit { .. }));
    assert_eq!(writer.pending_documents(), 1);
}

// T40 — a stale `Index` handle's writer reloads the authoritative `CURRENT`.
#[test]
fn t40_stale_handle_writer_reloads_current() {
    let directory = memory();
    let index = create(directory.clone());
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("a", "one", "", "x", 1)))
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();
    }
    // The `index` handle was created before the first commit and is stale.
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::insert(doc("b", "two", "", "x", 2)))
            .unwrap();
        writer.commit().unwrap();
        writer.close().unwrap();
    }
    let reopened = Index::open_existing(directory, pr09_schema(), pr09_registry()).unwrap();
    assert_eq!(hit_keys(&reopened.snapshot(), &term("one")), ["a"]);
    assert_eq!(hit_keys(&reopened.snapshot(), &term("two")), ["b"]);
    let _ = DocumentKey::new("unused");
}
