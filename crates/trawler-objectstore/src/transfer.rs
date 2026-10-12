//! Transfer requests, limits, preconditions and outcomes.

use crate::digest::ContentDigest;
use crate::key::ObjectKey;

/// An explicit half-open byte range within an object.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ByteRange {
    /// Starting byte offset.
    pub offset: u64,
    /// Number of bytes to read. Must be positive.
    pub length: u64,
}

impl ByteRange {
    /// Construct a range.
    #[must_use]
    pub const fn new(offset: u64, length: u64) -> Self {
        Self { offset, length }
    }

    /// Checked end offset, or `None` on integer overflow.
    #[must_use]
    pub const fn end(&self) -> Option<u64> {
        self.offset.checked_add(self.length)
    }
}

/// Hard bounds for a single transfer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TransferLimits {
    /// Maximum number of bytes a single response may contain.
    pub max_bytes: u64,
}

impl TransferLimits {
    /// Construct limits with an explicit maximum.
    #[must_use]
    pub const fn new(max_bytes: u64) -> Self {
        Self { max_bytes }
    }
}

/// The precondition under which a put may proceed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PutPrecondition {
    /// Atomic create-if-absent. Idempotent when the existing object is
    /// byte-identical, a conflict otherwise.
    IfAbsent,
    /// Conditional replace (compare-and-swap). Capability-gated and reserved
    /// for future manifest/fencing work, not for immutable segment objects.
    IfMatch(ContentDigest),
}

/// The result of an immutable put.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum PutOutcome {
    /// The object was created (or conditionally replaced).
    Created,
    /// An identical object already existed; the call was idempotent.
    AlreadyPresent,
}

/// Metadata describing a stored object.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectMetadata {
    /// The object key.
    pub key: ObjectKey,
    /// Exact byte length.
    pub length: u64,
    /// Content digest.
    pub digest: ContentDigest,
}

impl ObjectMetadata {
    /// Construct metadata.
    #[must_use]
    pub fn new(key: ObjectKey, length: u64, digest: ContentDigest) -> Self {
        Self {
            key,
            length,
            digest,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_range_end_is_checked() {
        assert_eq!(ByteRange::new(2, 3).end(), Some(5));
        assert_eq!(ByteRange::new(u64::MAX, 1).end(), None);
        assert_eq!(ByteRange::new(u64::MAX, 0).end(), Some(u64::MAX));
    }

    #[test]
    fn transfer_limits_and_metadata() {
        assert_eq!(TransferLimits::new(10).max_bytes, 10);
        let key = ObjectKey::parse("a/b").unwrap();
        let digest = ContentDigest::sha256_v1(b"x");
        let metadata = ObjectMetadata::new(key.clone(), 1, digest);
        assert_eq!(metadata.key, key);
        assert_eq!(metadata.length, 1);
        assert_eq!(metadata.digest, digest);
    }

    #[test]
    fn precondition_equality() {
        assert_eq!(PutPrecondition::IfAbsent, PutPrecondition::IfAbsent);
        assert_ne!(
            PutPrecondition::IfAbsent,
            PutPrecondition::IfMatch(ContentDigest::sha256_v1(b"x"))
        );
    }
}
