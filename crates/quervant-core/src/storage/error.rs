//! Typed local storage errors.

use std::fmt;

use quervant_objectstore::{ContentDigest, KeyError, ObjectStoreError};

use super::StorageKey;

/// The operation an error originated from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum StorageOp {
    /// Opening a file or directory.
    Open,
    /// Creating a file.
    Create,
    /// Creating a directory prefix.
    CreateDir,
    /// Reading bytes.
    Read,
    /// Writing bytes.
    Write,
    /// Synchronizing file data.
    Sync,
    /// Renaming/replacing a file.
    Rename,
    /// Synchronizing a directory entry.
    DirSync,
    /// Deleting a file.
    Delete,
    /// Checking existence.
    Exists,
    /// Durable atomic replacement.
    AtomicWrite,
    /// Filling a cache entry from a remote store.
    CacheFill,
}

impl fmt::Display for StorageOp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Open => "open",
            Self::Create => "create",
            Self::CreateDir => "create directory",
            Self::Read => "read",
            Self::Write => "write",
            Self::Sync => "sync",
            Self::Rename => "rename",
            Self::DirSync => "directory sync",
            Self::Delete => "delete",
            Self::Exists => "exists",
            Self::AtomicWrite => "atomic write",
            Self::CacheFill => "cache fill",
        };
        f.write_str(name)
    }
}

/// The kind of content corruption detected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum CorruptionKind {
    /// Stored length differed from the expected length.
    LengthMismatch,
    /// Stored digest differed from the expected digest.
    DigestMismatch,
    /// The content was otherwise unexpected.
    UnexpectedContent,
}

impl fmt::Display for CorruptionKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::LengthMismatch => "length mismatch",
            Self::DigestMismatch => "digest mismatch",
            Self::UnexpectedContent => "unexpected content",
        };
        f.write_str(name)
    }
}

/// A local storage failure.
#[derive(Debug)]
#[non_exhaustive]
pub enum StorageError {
    /// The key grammar was invalid.
    InvalidKey {
        /// Why the key was rejected.
        reason: KeyError,
    },
    /// The entry does not exist.
    NotFound {
        /// The requested key.
        key: StorageKey,
    },
    /// A create found an existing entry.
    AlreadyExists {
        /// The conflicting key.
        key: StorageKey,
    },
    /// Stored bytes were corrupt.
    Corrupt {
        /// The affected key.
        key: StorageKey,
        /// The kind of corruption.
        detail: CorruptionKind,
    },
    /// Stored bytes did not match the expected digest.
    IntegrityMismatch {
        /// The affected key.
        key: StorageKey,
        /// Expected digest.
        expected: ContentDigest,
        /// Actual digest.
        actual: ContentDigest,
    },
    /// Stored bytes did not match the expected length.
    LengthMismatch {
        /// The affected key.
        key: StorageKey,
        /// Expected length.
        expected: u64,
        /// Actual length.
        actual: u64,
    },
    /// A configured bound was exceeded.
    LimitExceeded {
        /// The configured limit.
        limit: u64,
        /// The requested amount.
        requested: u64,
    },
    /// An immutable identity conflict.
    Conflict {
        /// The conflicting key.
        key: StorageKey,
    },
    /// The operation is not supported on this platform.
    Unsupported {
        /// The attempted operation.
        operation: StorageOp,
        /// The platform descriptor.
        platform: &'static str,
    },
    /// An underlying I/O failure.
    Io {
        /// The attempted operation.
        operation: StorageOp,
        /// The underlying error.
        source: std::io::Error,
    },
    /// The operation was cancelled.
    Cancelled,
}

impl StorageError {
    /// Wrap an [`std::io::Error`] with operation context.
    #[must_use]
    pub fn io(operation: StorageOp, source: std::io::Error) -> Self {
        Self::Io { operation, source }
    }

    /// Map a remote object-store failure into a local, keyed storage failure.
    pub(crate) fn from_object_store(error: ObjectStoreError, key: &StorageKey) -> Self {
        match error {
            ObjectStoreError::InvalidKey { reason } => Self::InvalidKey { reason },
            ObjectStoreError::NotFound { .. } => Self::NotFound { key: key.clone() },
            ObjectStoreError::Conflict { .. } | ObjectStoreError::PreconditionFailed { .. } => {
                Self::Conflict { key: key.clone() }
            }
            ObjectStoreError::UnsupportedCapability { .. } => Self::Unsupported {
                operation: StorageOp::CacheFill,
                platform: "object-store",
            },
            ObjectStoreError::LimitExceeded { limit, requested } => {
                Self::LimitExceeded { limit, requested }
            }
            ObjectStoreError::IntegrityMismatch { expected, actual } => Self::IntegrityMismatch {
                key: key.clone(),
                expected,
                actual,
            },
            ObjectStoreError::LengthMismatch { expected, actual } => Self::LengthMismatch {
                key: key.clone(),
                expected,
                actual,
            },
            ObjectStoreError::InvalidRange { .. }
            | ObjectStoreError::RangeLengthMismatch { .. } => Self::Corrupt {
                key: key.clone(),
                detail: CorruptionKind::UnexpectedContent,
            },
            ObjectStoreError::Timeout => Self::Io {
                operation: StorageOp::CacheFill,
                source: std::io::Error::new(std::io::ErrorKind::TimedOut, "object store timeout"),
            },
            ObjectStoreError::Cancelled => Self::Cancelled,
            ObjectStoreError::Backend { detail } => Self::Io {
                operation: StorageOp::CacheFill,
                source: std::io::Error::other(detail),
            },
            ObjectStoreError::Transient { detail } => Self::Io {
                operation: StorageOp::CacheFill,
                source: std::io::Error::new(std::io::ErrorKind::TimedOut, detail),
            },
            _ => Self::Io {
                operation: StorageOp::CacheFill,
                source: std::io::Error::other("unrecognized object store failure"),
            },
        }
    }
}

impl fmt::Display for StorageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidKey { reason } => write!(f, "invalid storage key: {reason}"),
            Self::NotFound { key } => write!(f, "storage entry not found: {key}"),
            Self::AlreadyExists { key } => write!(f, "storage entry already exists: {key}"),
            Self::Corrupt { key, detail } => write!(f, "corrupt storage entry {key}: {detail}"),
            Self::IntegrityMismatch {
                key,
                expected,
                actual,
            } => {
                write!(
                    f,
                    "integrity mismatch for {key}: expected {expected}, actual {actual}"
                )
            }
            Self::LengthMismatch {
                key,
                expected,
                actual,
            } => {
                write!(
                    f,
                    "length mismatch for {key}: expected {expected}, actual {actual}"
                )
            }
            Self::LimitExceeded { limit, requested } => {
                write!(
                    f,
                    "storage limit exceeded: limit {limit}, requested {requested}"
                )
            }
            Self::Conflict { key } => write!(f, "storage conflict for {key}"),
            Self::Unsupported {
                operation,
                platform,
            } => {
                write!(f, "unsupported storage operation {operation} on {platform}")
            }
            Self::Io { operation, source } => write!(f, "io error during {operation}: {source}"),
            Self::Cancelled => f.write_str("storage operation cancelled"),
        }
    }
}

impl std::error::Error for StorageError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io { source, .. } => Some(source),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;

    fn key() -> StorageKey {
        StorageKey::parse("a/b").unwrap()
    }

    #[test]
    fn displays_without_panicking() {
        let errors = vec![
            StorageError::InvalidKey {
                reason: KeyError::Empty,
            },
            StorageError::NotFound { key: key() },
            StorageError::AlreadyExists { key: key() },
            StorageError::Corrupt {
                key: key(),
                detail: CorruptionKind::DigestMismatch,
            },
            StorageError::IntegrityMismatch {
                key: key(),
                expected: ContentDigest::sha256_v1(b"a"),
                actual: ContentDigest::sha256_v1(b"b"),
            },
            StorageError::LengthMismatch {
                key: key(),
                expected: 1,
                actual: 2,
            },
            StorageError::LimitExceeded {
                limit: 1,
                requested: 2,
            },
            StorageError::Conflict { key: key() },
            StorageError::Unsupported {
                operation: StorageOp::AtomicWrite,
                platform: "windows",
            },
            StorageError::io(StorageOp::Read, std::io::Error::other("boom")),
            StorageError::Cancelled,
        ];
        for error in &errors {
            assert!(!error.to_string().is_empty());
        }
        assert!(errors[9].source().is_some());
        assert!(errors[0].source().is_none());
        assert!(!StorageOp::CacheFill.to_string().is_empty());
        assert!(!CorruptionKind::LengthMismatch.to_string().is_empty());
    }

    #[test]
    fn maps_object_store_errors() {
        use quervant_objectstore::ObjectKey;
        let object_key = ObjectKey::parse("a/b").unwrap();
        let mapped = StorageError::from_object_store(
            ObjectStoreError::NotFound {
                key: object_key.clone(),
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::NotFound { .. }));
        let mapped =
            StorageError::from_object_store(ObjectStoreError::Conflict { key: object_key }, &key());
        assert!(matches!(mapped, StorageError::Conflict { .. }));
        let mapped = StorageError::from_object_store(ObjectStoreError::Timeout, &key());
        assert!(matches!(mapped, StorageError::Io { .. }));
        let mapped = StorageError::from_object_store(ObjectStoreError::Cancelled, &key());
        assert!(matches!(mapped, StorageError::Cancelled));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::UnsupportedCapability {
                capability: "range_read",
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::Unsupported { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::InvalidRange {
                offset: 0,
                length: 0,
                object_length: None,
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::Corrupt { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::PreconditionFailed {
                key: ObjectKey::parse("a/b").unwrap(),
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::Conflict { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::LengthMismatch {
                expected: 1,
                actual: 2,
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::LengthMismatch { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::IntegrityMismatch {
                expected: ContentDigest::sha256_v1(b"a"),
                actual: ContentDigest::sha256_v1(b"b"),
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::IntegrityMismatch { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::LimitExceeded {
                limit: 1,
                requested: 2,
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::LimitExceeded { .. }));
        let mapped = StorageError::from_object_store(
            ObjectStoreError::Backend {
                detail: "boom".to_string(),
            },
            &key(),
        );
        assert!(matches!(mapped, StorageError::Io { .. }));
    }
}
