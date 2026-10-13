//! Provider-neutral object storage contracts for Quervant.
//!
//! This crate defines immutable-object identity, a provider-neutral
//! asynchronous [`ObjectStore`] contract with explicit capabilities, typed
//! errors, and a deterministic stateful [`FakeObjectStore`]. It has no
//! dependency on `quervant-core`, no distributed dependency, and no production
//! S3/RustFS adapter (that belongs to PR 13).
//!
//! Local-only users of `quervant-core` never need a running object-storage
//! service; the trait and fake are pure Rust with no runtime requirement.

#![forbid(unsafe_code)]

mod capability;
mod contract;
mod digest;
mod error;
mod fake;
mod key;
#[cfg(test)]
mod test_support;
mod transfer;

pub use capability::ObjectStoreCapabilities;
pub use contract::ObjectStore;
pub use digest::{ContentDescriptor, ContentDigest, DigestAlgorithm};
pub use error::ObjectStoreError;
pub use fake::{FakeObjectStore, FaultKind};
pub use key::{KeyError, MAX_KEY_BYTES, ObjectKey, validate_key};
pub use transfer::{ByteRange, ObjectMetadata, PutOutcome, PutPrecondition, TransferLimits};

/// Returns the crate's public project identifier.
#[must_use]
pub const fn project_name() -> &'static str {
    "quervant-objectstore"
}

#[cfg(test)]
mod tests {
    #[test]
    fn crate_identity() {
        assert_eq!(super::project_name(), "quervant-objectstore");
    }
}
