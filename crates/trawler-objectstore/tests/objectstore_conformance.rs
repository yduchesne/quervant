//! PR 3 O-01..O-12 object-store conformance (provider-neutral contract + fake).
//!
//! These tests exercise the production `ObjectStore` trait and the stateful
//! deterministic `FakeObjectStore`. They do **not** claim any S3/RustFS
//! compatibility.

use std::future::Future;
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll};

use trawler_objectstore::{
    ByteRange, ContentDescriptor, ContentDigest, FakeObjectStore, FaultKind, ObjectKey,
    ObjectStore, ObjectStoreCapabilities, ObjectStoreError, PutOutcome, PutPrecondition,
    TransferLimits,
};

fn block_on<F: Future>(future: F) -> F::Output {
    let mut context = Context::from_waker(std::task::Waker::noop());
    let mut future = Box::pin(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}

fn key(name: &str) -> ObjectKey {
    ObjectKey::parse(name).unwrap()
}

fn limits() -> TransferLimits {
    TransferLimits::new(4096)
}

// O-01
#[test]
fn o01_immutable_put_read_head() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let body = b"immutable bytes";
    let descriptor = ContentDescriptor::of(body);
    assert_eq!(
        block_on(store.put(
            &key,
            &descriptor,
            body,
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap(),
        PutOutcome::Created
    );
    assert_eq!(block_on(store.get(&key, None, &limits())).unwrap(), body);
    let metadata = block_on(store.head(&key)).unwrap();
    assert_eq!(metadata.length, body.len() as u64);
    assert_eq!(metadata.digest, descriptor.digest);
}

// O-02
#[test]
fn o02_same_key_same_digest_replay_is_idempotent() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"data");
    assert_eq!(
        block_on(store.put(
            &key,
            &descriptor,
            b"data",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap(),
        PutOutcome::Created
    );
    assert_eq!(
        block_on(store.put(
            &key,
            &descriptor,
            b"data",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap(),
        PutOutcome::AlreadyPresent
    );
}

// O-03
#[test]
fn o03_same_key_different_bytes_conflicts_and_preserves_original() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let original = ContentDescriptor::of(b"original");
    let other = ContentDescriptor::of(b"other");
    block_on(store.put(
        &key,
        &original,
        b"original",
        PutPrecondition::IfAbsent,
        &limits(),
    ))
    .unwrap();
    assert!(matches!(
        block_on(store.put(&key, &other, b"other", PutPrecondition::IfAbsent, &limits()))
            .unwrap_err(),
        ObjectStoreError::Conflict { .. }
    ));
    assert_eq!(
        block_on(store.get(&key, None, &limits())).unwrap(),
        b"original"
    );
}

// O-04
#[test]
fn o04_partial_upload_exposes_no_complete_object() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"payload");
    store.set_put_fault(FaultKind::MidWrite);
    assert!(
        block_on(store.put(
            &key,
            &descriptor,
            b"payload",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .is_err()
    );
    assert!(!store.contains(&key));
    assert!(matches!(
        block_on(store.head(&key)).unwrap_err(),
        ObjectStoreError::NotFound { .. }
    ));
}

// O-05
#[test]
fn o05_timeout_before_acknowledgement_is_retryable() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"payload");
    store.set_put_fault(FaultKind::BeforeWrite);
    assert!(
        block_on(store.put(
            &key,
            &descriptor,
            b"payload",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .is_err()
    );
    assert!(!store.contains(&key));
    assert_eq!(
        block_on(store.put(
            &key,
            &descriptor,
            b"payload",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap(),
        PutOutcome::Created
    );
}

// O-06
#[test]
fn o06_timeout_after_commit_replay_detects_identity() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"payload");
    store.set_put_fault(FaultKind::AfterCommitBeforeAck);
    assert!(matches!(
        block_on(store.put(
            &key,
            &descriptor,
            b"payload",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap_err(),
        ObjectStoreError::Timeout
    ));
    assert!(store.contains(&key));
    assert_eq!(
        block_on(store.put(
            &key,
            &descriptor,
            b"payload",
            PutPrecondition::IfAbsent,
            &limits()
        ))
        .unwrap(),
        PutOutcome::AlreadyPresent
    );
}

// O-07
#[test]
fn o07_corrupt_read_is_detected_by_digest_verification() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"payload");
    store.insert_raw(&key, b"payload");
    store.set_get_fault(FaultKind::CorruptRead);
    let bytes = block_on(store.get(&key, None, &limits())).unwrap();
    assert_ne!(ContentDigest::sha256_v1(&bytes), descriptor.digest);
    assert!(!descriptor.matches(&bytes));
}

// O-08
#[test]
fn o08_missing_object_is_not_found() {
    let store = FakeObjectStore::immutable();
    let missing = key("segments/missing");
    assert!(matches!(
        block_on(store.get(&missing, None, &limits())).unwrap_err(),
        ObjectStoreError::NotFound { .. }
    ));
    assert!(matches!(
        block_on(store.head(&missing)).unwrap_err(),
        ObjectStoreError::NotFound { .. }
    ));
}

// O-09
#[test]
fn o09_unsupported_conditional_operation_is_typed() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    let descriptor = ContentDescriptor::of(b"x");
    assert!(matches!(
        block_on(store.put(
            &key,
            &descriptor,
            b"x",
            PutPrecondition::IfMatch(ContentDigest::sha256_v1(b"prev")),
            &limits()
        ))
        .unwrap_err(),
        ObjectStoreError::UnsupportedCapability {
            capability: "conditional_replace"
        }
    ));
}

// O-10
#[test]
fn o10_malformed_keys_are_rejected() {
    for candidate in ["", "/abs", "a/../b", "a//b", "a:b", "a\\b"] {
        assert!(
            ObjectKey::parse(candidate).is_err(),
            "{candidate} should be rejected"
        );
    }
}

// O-11
#[test]
fn o11_bounded_transfer_over_limit_fails() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/1");
    store.insert_raw(&key, b"0123456789");
    assert!(matches!(
        block_on(store.get(&key, None, &TransferLimits::new(4))).unwrap_err(),
        ObjectStoreError::LimitExceeded { .. }
    ));
    assert!(matches!(
        block_on(store.put(
            &key,
            &ContentDescriptor::of(b"0123456789"),
            b"0123456789",
            PutPrecondition::IfAbsent,
            &TransferLimits::new(4)
        ))
        .unwrap_err(),
        ObjectStoreError::LimitExceeded { .. }
    ));
}

// O-12
#[test]
fn o12_concurrent_reads_never_see_torn_objects() {
    let store = Arc::new(FakeObjectStore::immutable());
    let key = key("segments/torn");
    let body = vec![7u8; 256];
    let descriptor = store.insert_raw(&key, &body);
    let barrier = Arc::new(Barrier::new(4));
    let mut handles = Vec::new();
    for _ in 0..4 {
        let store = Arc::clone(&store);
        let barrier = Arc::clone(&barrier);
        let key = key.clone();
        handles.push(std::thread::spawn(move || {
            barrier.wait();
            let bytes = block_on(store.get(&key, None, &limits())).unwrap();
            assert!(descriptor.matches(&bytes));
            bytes
        }));
    }
    for handle in handles {
        assert_eq!(handle.join().unwrap(), body);
    }
}

#[test]
fn concurrent_same_key_creates_exactly_one_object() {
    for _ in 0..8 {
        let store = Arc::new(FakeObjectStore::immutable());
        let barrier = Arc::new(Barrier::new(2));
        let key = key("segments/race");
        let descriptor = ContentDescriptor::of(b"payload");
        let mut handles = Vec::new();
        for _ in 0..2 {
            let store = Arc::clone(&store);
            let barrier = Arc::clone(&barrier);
            let key = key.clone();
            handles.push(std::thread::spawn(move || {
                barrier.wait();
                block_on(store.put(
                    &key,
                    &descriptor,
                    b"payload",
                    PutPrecondition::IfAbsent,
                    &limits(),
                ))
            }));
        }
        let outcomes: Vec<PutOutcome> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap().unwrap())
            .collect();
        assert_eq!(
            outcomes
                .iter()
                .filter(|outcome| **outcome == PutOutcome::Created)
                .count(),
            1
        );
        assert_eq!(store.get_calls(), 0);
    }
}

#[test]
fn exact_range_boundaries_and_overflow() {
    let store = FakeObjectStore::immutable();
    let key = key("segments/range");
    store.insert_raw(&key, b"abcdef");
    assert_eq!(
        block_on(store.get(&key, Some(ByteRange::new(0, 6)), &limits())).unwrap(),
        b"abcdef"
    );
    assert_eq!(
        block_on(store.get(&key, Some(ByteRange::new(5, 1)), &limits())).unwrap(),
        b"f"
    );
    assert!(matches!(
        block_on(store.get(&key, Some(ByteRange::new(6, 1)), &limits())).unwrap_err(),
        ObjectStoreError::InvalidRange { .. }
    ));
    assert!(matches!(
        block_on(store.get(&key, Some(ByteRange::new(u64::MAX, 2)), &limits())).unwrap_err(),
        ObjectStoreError::InvalidRange { .. }
    ));
    assert!(matches!(
        block_on(store.get(&key, Some(ByteRange::new(0, 0)), &limits())).unwrap_err(),
        ObjectStoreError::InvalidRange { .. }
    ));
}

#[test]
fn range_read_false_refuses_without_full_fallback() {
    let store =
        FakeObjectStore::new(ObjectStoreCapabilities::NONE.with_atomic_create_if_absent(true));
    let key = key("segments/range");
    store.insert_raw(&key, b"abcdef");
    assert!(matches!(
        block_on(store.get(&key, Some(ByteRange::new(1, 2)), &limits())).unwrap_err(),
        ObjectStoreError::UnsupportedCapability {
            capability: "range_read"
        }
    ));
}

#[test]
fn objectstore_crate_has_no_reverse_dependency() {
    let manifest =
        std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml")).unwrap();
    assert!(!manifest.contains("trawler-core"));
    assert!(!manifest.contains("trawler-distributed"));
}
