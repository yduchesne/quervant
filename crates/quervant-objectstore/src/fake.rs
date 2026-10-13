//! A deterministic, stateful in-memory [`ObjectStore`] with fault injection.
//!
//! The fake models only the capabilities it advertises. Mutating operations are
//! serialized by a mutex and contain no `await`, so same-key concurrent calls
//! observe a genuinely atomic operation. Faults are one-shot and injected at
//! real operation boundaries, never via timing races.

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

use crate::capability::ObjectStoreCapabilities;
use crate::contract::ObjectStore;
use crate::digest::{ContentDescriptor, ContentDigest};
use crate::error::ObjectStoreError;
use crate::key::ObjectKey;
use crate::transfer::{ByteRange, ObjectMetadata, PutOutcome, PutPrecondition, TransferLimits};

/// A deterministic failure injected at a real fake-store boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum FaultKind {
    /// Fail before storing anything.
    BeforeWrite,
    /// Fail partway through a write, storing nothing (models an incomplete
    /// transfer that must not expose a complete object).
    MidWrite,
    /// Store the object, then fail before acknowledging (uncertain outcome).
    AfterCommitBeforeAck,
    /// Interrupt a read.
    ReadInterrupt,
    /// Return bytes that do not match their stored digest.
    CorruptRead,
    /// Time out.
    Timeout,
    /// Fail a delete.
    DeleteFailure,
    /// Reject a conditional operation as unsupported.
    UnsupportedConditional,
}

#[derive(Debug)]
struct StoredObject {
    bytes: Vec<u8>,
    digest: ContentDigest,
}

#[derive(Debug, Default)]
struct State {
    objects: HashMap<ObjectKey, StoredObject>,
    put_faults: VecDeque<FaultKind>,
    get_faults: VecDeque<FaultKind>,
    head_faults: VecDeque<FaultKind>,
    delete_faults: VecDeque<FaultKind>,
    put_calls: u64,
    get_calls: u64,
    delete_calls: u64,
}

/// A deterministic stateful fake object store.
#[derive(Debug)]
pub struct FakeObjectStore {
    capabilities: ObjectStoreCapabilities,
    state: Mutex<State>,
}

impl FakeObjectStore {
    /// Create a fake advertising `capabilities`.
    #[must_use]
    pub fn new(capabilities: ObjectStoreCapabilities) -> Self {
        Self {
            capabilities,
            state: Mutex::new(State::default()),
        }
    }

    /// Create a fake with the immutable-object baseline capabilities.
    #[must_use]
    pub fn immutable() -> Self {
        Self::new(ObjectStoreCapabilities::IMMUTABLE_BASELINE)
    }

    /// Queue a one-shot fault for the next [`ObjectStore::put`].
    pub fn set_put_fault(&self, fault: FaultKind) {
        self.state
            .lock()
            .expect("fake lock")
            .put_faults
            .push_back(fault);
    }

    /// Queue a one-shot fault for the next [`ObjectStore::get`].
    pub fn set_get_fault(&self, fault: FaultKind) {
        self.state
            .lock()
            .expect("fake lock")
            .get_faults
            .push_back(fault);
    }

    /// Queue a one-shot fault for the next [`ObjectStore::head`].
    pub fn set_head_fault(&self, fault: FaultKind) {
        self.state
            .lock()
            .expect("fake lock")
            .head_faults
            .push_back(fault);
    }

    /// Queue a one-shot fault for the next [`ObjectStore::delete`].
    pub fn set_delete_fault(&self, fault: FaultKind) {
        self.state
            .lock()
            .expect("fake lock")
            .delete_faults
            .push_back(fault);
    }

    /// Insert bytes directly, bypassing fault injection (test fixture helper).
    pub fn insert_raw(&self, key: &ObjectKey, bytes: &[u8]) -> ContentDescriptor {
        let descriptor = ContentDescriptor::of(bytes);
        self.state.lock().expect("fake lock").objects.insert(
            key.clone(),
            StoredObject {
                bytes: bytes.to_vec(),
                digest: descriptor.digest,
            },
        );
        descriptor
    }

    /// Return a copy of an object's bytes, if present.
    #[must_use]
    pub fn object(&self, key: &ObjectKey) -> Option<Vec<u8>> {
        self.state
            .lock()
            .expect("fake lock")
            .objects
            .get(key)
            .map(|object| object.bytes.clone())
    }

    /// Whether an object exists.
    #[must_use]
    pub fn contains(&self, key: &ObjectKey) -> bool {
        self.state
            .lock()
            .expect("fake lock")
            .objects
            .contains_key(key)
    }

    /// Number of completed `get` calls so far.
    #[must_use]
    pub fn get_calls(&self) -> u64 {
        self.state.lock().expect("fake lock").get_calls
    }

    /// Number of completed `put` calls so far.
    #[must_use]
    pub fn put_calls(&self) -> u64 {
        self.state.lock().expect("fake lock").put_calls
    }

    /// Number of completed `delete` calls so far.
    #[must_use]
    pub fn delete_calls(&self) -> u64 {
        self.state.lock().expect("fake lock").delete_calls
    }

    /// Reset the operation counters (test helper).
    pub fn reset_counters(&self) {
        let mut state = self.state.lock().expect("fake lock");
        state.put_calls = 0;
        state.get_calls = 0;
        state.delete_calls = 0;
    }
}

fn apply_put(
    state: &mut State,
    key: &ObjectKey,
    expected: &ContentDescriptor,
    body: &[u8],
    precondition: PutPrecondition,
) -> Result<PutOutcome, ObjectStoreError> {
    let actual_length = body.len() as u64;
    if actual_length != expected.length {
        return Err(ObjectStoreError::LengthMismatch {
            expected: expected.length,
            actual: actual_length,
        });
    }
    let actual_digest = ContentDigest::sha256_v1(body);
    if actual_digest != expected.digest {
        return Err(ObjectStoreError::IntegrityMismatch {
            expected: expected.digest,
            actual: actual_digest,
        });
    }

    match precondition {
        PutPrecondition::IfAbsent => {
            if let Some(existing) = state.objects.get(key) {
                if existing.digest == expected.digest
                    && existing.bytes.len() as u64 == expected.length
                {
                    Ok(PutOutcome::AlreadyPresent)
                } else {
                    Err(ObjectStoreError::Conflict { key: key.clone() })
                }
            } else {
                state.objects.insert(
                    key.clone(),
                    StoredObject {
                        bytes: body.to_vec(),
                        digest: expected.digest,
                    },
                );
                Ok(PutOutcome::Created)
            }
        }
        PutPrecondition::IfMatch(digest) => match state.objects.get(key) {
            Some(existing) if existing.digest == digest => {
                state.objects.insert(
                    key.clone(),
                    StoredObject {
                        bytes: body.to_vec(),
                        digest: expected.digest,
                    },
                );
                Ok(PutOutcome::Created)
            }
            _ => Err(ObjectStoreError::PreconditionFailed { key: key.clone() }),
        },
    }
}

impl ObjectStore for FakeObjectStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        self.capabilities
    }

    async fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> Result<PutOutcome, ObjectStoreError> {
        let limits = *limits;
        {
            if body.len() as u64 > limits.max_bytes {
                return Err(ObjectStoreError::LimitExceeded {
                    limit: limits.max_bytes,
                    requested: body.len() as u64,
                });
            }

            match precondition {
                PutPrecondition::IfAbsent if !self.capabilities.atomic_create_if_absent => {
                    return Err(ObjectStoreError::UnsupportedCapability {
                        capability: "atomic_create_if_absent",
                    });
                }
                PutPrecondition::IfMatch(_) if !self.capabilities.conditional_replace => {
                    return Err(ObjectStoreError::UnsupportedCapability {
                        capability: "conditional_replace",
                    });
                }
                _ => {}
            }

            let mut state = self.state.lock().expect("fake lock");
            state.put_calls += 1;
            match state.put_faults.pop_front() {
                Some(FaultKind::BeforeWrite | FaultKind::MidWrite) => {
                    return Err(ObjectStoreError::Backend {
                        detail: "injected put failure".to_string(),
                    });
                }
                Some(FaultKind::Timeout) => return Err(ObjectStoreError::Timeout),
                Some(FaultKind::UnsupportedConditional) => {
                    return Err(ObjectStoreError::UnsupportedCapability {
                        capability: "conditional_replace",
                    });
                }
                Some(FaultKind::AfterCommitBeforeAck) => {
                    apply_put(&mut state, key, expected, body, precondition)?;
                    return Err(ObjectStoreError::Timeout);
                }
                _ => {}
            }

            apply_put(&mut state, key, expected, body, precondition)
        }
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        let limits = *limits;
        {
            let mut state = self.state.lock().expect("fake lock");
            state.get_calls += 1;

            if let Some(fault) = state.get_faults.pop_front() {
                match fault {
                    FaultKind::ReadInterrupt => {
                        return Err(ObjectStoreError::Backend {
                            detail: "injected read interrupt".to_string(),
                        });
                    }
                    FaultKind::Timeout => return Err(ObjectStoreError::Timeout),
                    FaultKind::CorruptRead => {
                        let mut bytes =
                            state
                                .objects
                                .get(key)
                                .map(|object| object.bytes.clone())
                                .ok_or_else(|| ObjectStoreError::NotFound { key: key.clone() })?;
                        if let Some(byte) = bytes.first_mut() {
                            *byte ^= 0xff;
                        }
                        return Ok(bytes);
                    }
                    _ => {}
                }
            }

            let object = state
                .objects
                .get(key)
                .ok_or_else(|| ObjectStoreError::NotFound { key: key.clone() })?;

            match range {
                Some(range) => {
                    if range.length == 0 {
                        return Err(ObjectStoreError::InvalidRange {
                            offset: range.offset,
                            length: range.length,
                            object_length: Some(object.bytes.len() as u64),
                        });
                    }
                    let end = range.end().ok_or(ObjectStoreError::InvalidRange {
                        offset: range.offset,
                        length: range.length,
                        object_length: Some(object.bytes.len() as u64),
                    })?;
                    if range.length > limits.max_bytes {
                        return Err(ObjectStoreError::LimitExceeded {
                            limit: limits.max_bytes,
                            requested: range.length,
                        });
                    }
                    if !self.capabilities.range_read {
                        return Err(ObjectStoreError::UnsupportedCapability {
                            capability: "range_read",
                        });
                    }
                    if end > object.bytes.len() as u64 {
                        return Err(ObjectStoreError::InvalidRange {
                            offset: range.offset,
                            length: range.length,
                            object_length: Some(object.bytes.len() as u64),
                        });
                    }
                    Ok(object.bytes[range.offset as usize..end as usize].to_vec())
                }
                None => {
                    if object.bytes.len() as u64 > limits.max_bytes {
                        return Err(ObjectStoreError::LimitExceeded {
                            limit: limits.max_bytes,
                            requested: object.bytes.len() as u64,
                        });
                    }
                    Ok(object.bytes.clone())
                }
            }
        }
    }

    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError> {
        {
            let mut state = self.state.lock().expect("fake lock");
            if let Some(FaultKind::Timeout) = state.head_faults.pop_front() {
                return Err(ObjectStoreError::Timeout);
            }
            state
                .objects
                .get(key)
                .map(|object| {
                    ObjectMetadata::new(key.clone(), object.bytes.len() as u64, object.digest)
                })
                .ok_or_else(|| ObjectStoreError::NotFound { key: key.clone() })
        }
    }

    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError> {
        {
            let mut state = self.state.lock().expect("fake lock");
            state.delete_calls += 1;
            if let Some(FaultKind::DeleteFailure) = state.delete_faults.pop_front() {
                return Err(ObjectStoreError::Backend {
                    detail: "injected delete failure".to_string(),
                });
            }
            state.objects.remove(key);
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::block_on;

    fn key(name: &str) -> ObjectKey {
        ObjectKey::parse(name).unwrap()
    }

    fn limits() -> TransferLimits {
        TransferLimits::new(1024)
    }

    #[test]
    fn put_get_head_delete_round_trip() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let body = b"hello";
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
        assert_eq!(metadata.length, 5);
        assert_eq!(metadata.digest, descriptor.digest);
        assert!(store.contains(&key));
        block_on(store.delete(&key)).unwrap();
        assert!(!store.contains(&key));
        assert!(matches!(
            block_on(store.head(&key)).unwrap_err(),
            ObjectStoreError::NotFound { .. }
        ));
    }

    #[test]
    fn idempotent_and_conflicting_puts() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let first = ContentDescriptor::of(b"one");
        let second = ContentDescriptor::of(b"two");
        assert_eq!(
            block_on(store.put(&key, &first, b"one", PutPrecondition::IfAbsent, &limits()))
                .unwrap(),
            PutOutcome::Created
        );
        assert_eq!(
            block_on(store.put(&key, &first, b"one", PutPrecondition::IfAbsent, &limits()))
                .unwrap(),
            PutOutcome::AlreadyPresent
        );
        assert!(matches!(
            block_on(store.put(&key, &second, b"two", PutPrecondition::IfAbsent, &limits()))
                .unwrap_err(),
            ObjectStoreError::Conflict { .. }
        ));
        assert_eq!(store.object(&key).unwrap(), b"one");
    }

    #[test]
    fn put_rejects_identity_mismatch() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let wrong_length = ContentDescriptor::new(99, ContentDigest::sha256_v1(b"hello"));
        assert!(matches!(
            block_on(store.put(
                &key,
                &wrong_length,
                b"hello",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::LengthMismatch { .. }
        ));
        let wrong_digest = ContentDescriptor::new(5, ContentDigest::sha256_v1(b"other"));
        assert!(matches!(
            block_on(store.put(
                &key,
                &wrong_digest,
                b"hello",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::IntegrityMismatch { .. }
        ));
        assert!(!store.contains(&key));
    }

    #[test]
    fn capability_gating_fails_closed() {
        let store = FakeObjectStore::new(ObjectStoreCapabilities::NONE);
        let key = key("a/1");
        let descriptor = ContentDescriptor::of(b"x");
        assert!(matches!(
            block_on(store.put(
                &key,
                &descriptor,
                b"x",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::UnsupportedCapability { .. }
        ));
    }

    #[test]
    fn conditional_replace_is_separate_capability() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let descriptor = ContentDescriptor::of(b"x");
        assert!(matches!(
            block_on(store.put(
                &key,
                &descriptor,
                b"x",
                PutPrecondition::IfMatch(ContentDigest::sha256_v1(b"old")),
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::UnsupportedCapability {
                capability: "conditional_replace"
            }
        ));
    }

    #[test]
    fn ranged_get_returns_exact_bytes() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        store.insert_raw(&key, b"0123456789");
        assert_eq!(
            block_on(store.get(&key, Some(ByteRange::new(2, 3)), &limits())).unwrap(),
            b"234"
        );
        assert!(
            block_on(store.get(&key, Some(ByteRange::new(10, 0)), &limits()))
                .unwrap_err()
                .to_string()
                .contains("invalid byte range")
        );
        assert!(matches!(
            block_on(store.get(&key, Some(ByteRange::new(8, 5)), &limits())).unwrap_err(),
            ObjectStoreError::InvalidRange { .. }
        ));
        assert!(matches!(
            block_on(store.get(&key, Some(ByteRange::new(u64::MAX, 1)), &limits())).unwrap_err(),
            ObjectStoreError::InvalidRange { .. }
        ));
    }

    #[test]
    fn range_requires_capability_and_budget() {
        let store = FakeObjectStore::new(ObjectStoreCapabilities {
            atomic_create_if_absent: true,
            range_read: false,
            ..ObjectStoreCapabilities::NONE
        });
        let key = key("a/1");
        store.insert_raw(&key, b"0123456789");
        assert!(matches!(
            block_on(store.get(&key, Some(ByteRange::new(0, 2)), &limits())).unwrap_err(),
            ObjectStoreError::UnsupportedCapability {
                capability: "range_read"
            }
        ));
        let tiny = TransferLimits::new(2);
        assert!(matches!(
            block_on(store.get(&key, Some(ByteRange::new(0, 3)), &tiny)).unwrap_err(),
            ObjectStoreError::LimitExceeded { .. }
        ));
    }

    #[test]
    fn whole_get_respects_limit() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        store.insert_raw(&key, b"0123456789");
        assert!(matches!(
            block_on(store.get(&key, None, &TransferLimits::new(3))).unwrap_err(),
            ObjectStoreError::LimitExceeded { .. }
        ));
    }

    #[test]
    fn fault_stages() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let descriptor = ContentDescriptor::of(b"x");

        store.set_put_fault(FaultKind::BeforeWrite);
        assert!(matches!(
            block_on(store.put(
                &key,
                &descriptor,
                b"x",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::Backend { .. }
        ));
        assert!(!store.contains(&key));

        store.set_put_fault(FaultKind::MidWrite);
        assert!(
            block_on(store.put(
                &key,
                &descriptor,
                b"x",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .is_err()
        );
        assert!(!store.contains(&key));

        store.set_put_fault(FaultKind::AfterCommitBeforeAck);
        assert!(matches!(
            block_on(store.put(
                &key,
                &descriptor,
                b"x",
                PutPrecondition::IfAbsent,
                &limits()
            ))
            .unwrap_err(),
            ObjectStoreError::Timeout
        ));
        assert!(store.contains(&key));

        store.set_get_fault(FaultKind::CorruptRead);
        let corrupted = block_on(store.get(&key, None, &limits())).unwrap();
        assert_ne!(corrupted, b"x");

        store.set_get_fault(FaultKind::ReadInterrupt);
        assert!(block_on(store.get(&key, None, &limits())).is_err());

        store.set_delete_fault(FaultKind::DeleteFailure);
        assert!(block_on(store.delete(&key)).is_err());
    }

    #[test]
    fn counters_and_insert_raw() {
        let store = FakeObjectStore::immutable();
        let key = key("a/1");
        let descriptor = store.insert_raw(&key, b"x");
        assert_eq!(descriptor.length, 1);
        assert_eq!(store.put_calls(), 0);
        assert_eq!(store.get_calls(), 0);
        block_on(store.get(&key, None, &limits())).unwrap();
        assert_eq!(store.get_calls(), 1);
    }
}
