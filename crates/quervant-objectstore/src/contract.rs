//! The provider-neutral asynchronous [`ObjectStore`] contract.

use std::future::Future;

use crate::capability::ObjectStoreCapabilities;
use crate::digest::ContentDescriptor;
use crate::error::ObjectStoreError;
use crate::key::ObjectKey;
use crate::transfer::{ByteRange, ObjectMetadata, PutOutcome, PutPrecondition, TransferLimits};

/// A provider-neutral store of immutable objects.
///
/// The trait uses native Rust `async fn`-style futures (RPITIT), so no runtime
/// is required by the contract itself. Implementations must not perform hidden
/// retries; retry and idempotency policy belong to the caller (S16).
pub trait ObjectStore: Send + Sync {
    /// Advertise the capabilities this adapter actually provides.
    fn capabilities(&self) -> ObjectStoreCapabilities;

    /// Store immutable bytes under `key`.
    ///
    /// `expected` is the caller-declared identity of `body`; adapters verify
    /// length and digest before acknowledging creation. A mismatch is a typed
    /// failure and must not create or overwrite an object. An existing
    /// byte-identical object is an idempotent [`PutOutcome::AlreadyPresent`]; a
    /// different object is a typed [`ObjectStoreError::Conflict`].
    fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> impl Future<Output = Result<PutOutcome, ObjectStoreError>> + Send;

    /// Read an object, or exactly one bounded byte range of it.
    ///
    /// `None` requests the whole object. `Some(range)` requires a positive
    /// length, a non-overflowing extent, and the [`ObjectStoreCapabilities::range_read`]
    /// capability; the response contains exactly `range.length` bytes at
    /// `range.offset`. A short, shifted, or full-object response is a typed
    /// error, never partial success.
    fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> impl Future<Output = Result<Vec<u8>, ObjectStoreError>> + Send;

    /// Describe an object without transferring its bytes.
    fn head(
        &self,
        key: &ObjectKey,
    ) -> impl Future<Output = Result<ObjectMetadata, ObjectStoreError>> + Send;

    /// Delete an object. Deleting an absent object succeeds (idempotent).
    fn delete(&self, key: &ObjectKey) -> impl Future<Output = Result<(), ObjectStoreError>> + Send;
}
