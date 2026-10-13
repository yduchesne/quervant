//! Typed provider-neutral object-store errors.

use std::fmt;

use crate::digest::ContentDigest;
use crate::key::{KeyError, ObjectKey};

/// A provider-neutral object-store failure.
///
/// The variants mirror the local `StorageError` taxonomy but are deliberately
/// separate so remote semantics never masquerade as local filesystem semantics.
#[derive(Debug)]
#[non_exhaustive]
pub enum ObjectStoreError {
    /// The key grammar was invalid.
    InvalidKey {
        /// Why the key was rejected.
        reason: KeyError,
    },
    /// The object does not exist.
    NotFound {
        /// The requested key.
        key: ObjectKey,
    },
    /// An immutable create found a different object under the same key.
    Conflict {
        /// The conflicting key.
        key: ObjectKey,
    },
    /// A conditional replace precondition did not hold.
    PreconditionFailed {
        /// The key whose precondition failed.
        key: ObjectKey,
    },
    /// The adapter does not provide the required capability.
    UnsupportedCapability {
        /// Capability name, for diagnostics.
        capability: &'static str,
    },
    /// A configured transfer bound was exceeded.
    LimitExceeded {
        /// The configured limit.
        limit: u64,
        /// The requested amount.
        requested: u64,
    },
    /// The bytes did not match the expected digest.
    IntegrityMismatch {
        /// Expected digest.
        expected: ContentDigest,
        /// Actual digest.
        actual: ContentDigest,
    },
    /// The bytes did not match the expected length.
    LengthMismatch {
        /// Expected length.
        expected: u64,
        /// Actual length.
        actual: u64,
    },
    /// A byte range was zero-length, overflowed, or fell outside the object.
    InvalidRange {
        /// Requested offset.
        offset: u64,
        /// Requested length.
        length: u64,
        /// Object length when known.
        object_length: Option<u64>,
    },
    /// A range response did not contain exactly the requested number of bytes.
    RangeLengthMismatch {
        /// Requested length.
        expected: u64,
        /// Received length.
        actual: u64,
    },
    /// The operation timed out.
    Timeout,
    /// The operation was cancelled.
    Cancelled,
    /// A backend failure with a non-sensitive detail string.
    Backend {
        /// Human-readable, non-sensitive detail.
        detail: String,
    },
}

impl fmt::Display for ObjectStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidKey { reason } => write!(f, "invalid object key: {reason}"),
            Self::NotFound { key } => write!(f, "object not found: {key}"),
            Self::Conflict { key } => write!(f, "object conflict: {key}"),
            Self::PreconditionFailed { key } => write!(f, "precondition failed: {key}"),
            Self::UnsupportedCapability { capability } => {
                write!(f, "unsupported capability: {capability}")
            }
            Self::LimitExceeded { limit, requested } => {
                write!(
                    f,
                    "transfer limit exceeded: limit {limit}, requested {requested}"
                )
            }
            Self::IntegrityMismatch { expected, actual } => {
                write!(
                    f,
                    "integrity mismatch: expected {expected}, actual {actual}"
                )
            }
            Self::LengthMismatch { expected, actual } => {
                write!(f, "length mismatch: expected {expected}, actual {actual}")
            }
            Self::InvalidRange {
                offset,
                length,
                object_length,
            } => write!(
                f,
                "invalid byte range offset {offset} length {length} object_length {}",
                object_length.map_or_else(|| "unknown".to_string(), |len| len.to_string())
            ),
            Self::RangeLengthMismatch { expected, actual } => {
                write!(
                    f,
                    "range response length mismatch: expected {expected}, actual {actual}"
                )
            }
            Self::Timeout => f.write_str("object store operation timed out"),
            Self::Cancelled => f.write_str("object store operation cancelled"),
            Self::Backend { detail } => write!(f, "object store backend failure: {detail}"),
        }
    }
}

impl std::error::Error for ObjectStoreError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn key() -> ObjectKey {
        ObjectKey::parse("a/b").unwrap()
    }

    #[test]
    fn errors_display_without_panicking() {
        let digest = ContentDigest::sha256_v1(b"x");
        let other = ContentDigest::sha256_v1(b"y");
        let cases = vec![
            ObjectStoreError::InvalidKey {
                reason: KeyError::Empty,
            },
            ObjectStoreError::NotFound { key: key() },
            ObjectStoreError::Conflict { key: key() },
            ObjectStoreError::PreconditionFailed { key: key() },
            ObjectStoreError::UnsupportedCapability {
                capability: "range_read",
            },
            ObjectStoreError::LimitExceeded {
                limit: 1,
                requested: 2,
            },
            ObjectStoreError::IntegrityMismatch {
                expected: digest,
                actual: other,
            },
            ObjectStoreError::LengthMismatch {
                expected: 1,
                actual: 2,
            },
            ObjectStoreError::InvalidRange {
                offset: 1,
                length: 0,
                object_length: None,
            },
            ObjectStoreError::InvalidRange {
                offset: 1,
                length: 2,
                object_length: Some(1),
            },
            ObjectStoreError::RangeLengthMismatch {
                expected: 2,
                actual: 1,
            },
            ObjectStoreError::Timeout,
            ObjectStoreError::Cancelled,
            ObjectStoreError::Backend {
                detail: "boom".to_string(),
            },
        ];
        for case in cases {
            assert!(!case.to_string().is_empty());
        }
    }
}
