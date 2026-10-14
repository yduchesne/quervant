//! Typed local index lifecycle errors (PR 6).
//!
//! Persisted input is never trusted: malformed `CURRENT`, a missing or corrupt
//! manifest, and a missing or mismatched segment all map to a typed error.
//! Nothing in this module panics for malformed persisted state.

use std::fmt;

use crate::analysis::AnalysisError;
use crate::contract::error::QueryError;
use crate::segment::SegmentError;
use crate::storage::StorageError;

/// Result alias for index lifecycle operations.
pub type IndexResult<T> = Result<T, IndexError>;

/// A typed index writer/lifecycle failure.
#[derive(Debug)]
#[non_exhaustive]
pub enum IndexError {
    /// No committed generation exists (`CURRENT` is absent).
    NotInitialized,
    /// A fresh index was requested but `CURRENT` already exists.
    AlreadyInitialized,
    /// Another cooperating writer owns `index/WRITER_LOCK`.
    WriterBusy,
    /// A logical document key already exists in an uncommitted or committed state.
    DuplicateDocument {
        /// The duplicated logical key.
        key: String,
    },
    /// Upsert, delete or idempotency-key execution is not supported in PR 6.
    UnsupportedMutation,
    /// An idempotency token was reused with a different request payload.
    IdempotencyConflict {
        /// The conflicting opaque token.
        token: String,
    },
    /// A new mutation would overflow the 64-bit revision space.
    RevisionOverflow,
    /// A cooperative cancellation request aborted the operation before any
    /// durable publication.
    Cancelled,
    /// Compaction was requested while uncommitted mutations are outstanding.
    PendingMutations {
        /// Number of accepted-but-uncommitted operations.
        pending: u64,
    },
    /// A retention request was rejected before admission.
    InvalidRetention {
        /// Bounded human-readable detail.
        detail: String,
    },
    /// `index/CURRENT` is malformed, truncated or otherwise invalid.
    InvalidCurrent {
        /// Bounded human-readable detail (never document content).
        detail: String,
    },
    /// Committed state (manifest or segment) is corrupt or inconsistent.
    CorruptCommittedState {
        /// Bounded human-readable detail.
        detail: String,
    },
    /// The number of generations would overflow the 64-bit generation space.
    GenerationOverflow,
    /// A write cannot be safely admitted until the index is reopened.
    RecoveryRequired {
        /// Bounded human-readable detail.
        detail: String,
    },
    /// A configured resource bound would be exceeded.
    ResourceLimit {
        /// The configured limit.
        limit: u64,
        /// The requested amount.
        requested: u64,
    },
    /// An existing content-addressed file or generation manifest has different bytes.
    ContentConflict {
        /// The conflicting storage key.
        key: String,
    },
    /// The pinned PIT count would exceed its bound.
    PitLimitExceeded {
        /// The configured maximum number of pinned PITs.
        limit: u64,
    },
    /// The process-local PIT id space is exhausted.
    PitIdExhausted,
    /// The requested segment index is out of range for a snapshot.
    SegmentOutOfRange {
        /// The requested index.
        index: usize,
        /// The number of segments in the snapshot.
        count: usize,
    },
    /// The requested PIT does not exist.
    PitNotFound {
        /// The opaque PIT id.
        id: String,
    },
    /// The supplied schema/analyzer bindings do not match committed state.
    SchemaMismatch {
        /// Bounded human-readable detail.
        detail: String,
    },
    /// A document or schema contract violation.
    Contract(QueryError),
    /// An analyzer binding/configuration failure.
    Analysis(AnalysisError),
    /// An immutable segment codec failure.
    Segment(SegmentError),
    /// A local storage failure.
    Storage(StorageError),
}

impl fmt::Display for IndexError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotInitialized => f.write_str("index is not initialized (no CURRENT)"),
            Self::AlreadyInitialized => f.write_str("index already has a committed generation"),
            Self::WriterBusy => f.write_str("another cooperating writer holds the writer lock"),
            Self::DuplicateDocument { key } => write!(f, "duplicate document key: {key}"),
            Self::UnsupportedMutation => {
                f.write_str("only insert mutations are supported in this release")
            }
            Self::IdempotencyConflict { token } => {
                write!(
                    f,
                    "idempotency token reused with a different payload: {token}"
                )
            }
            Self::RevisionOverflow => f.write_str("document revision space exhausted"),
            Self::Cancelled => f.write_str("index operation cancelled"),
            Self::PendingMutations { pending } => {
                write!(f, "cannot compact with {pending} uncommitted mutations")
            }
            Self::InvalidRetention { detail } => {
                write!(f, "invalid retention request: {detail}")
            }
            Self::InvalidCurrent { detail } => write!(f, "invalid CURRENT pointer: {detail}"),
            Self::CorruptCommittedState { detail } => {
                write!(f, "corrupt committed index state: {detail}")
            }
            Self::GenerationOverflow => f.write_str("index generation space exhausted"),
            Self::RecoveryRequired { detail } => {
                write!(f, "index recovery required before further writes: {detail}")
            }
            Self::ResourceLimit { limit, requested } => write!(
                f,
                "index resource limit exceeded: limit {limit}, requested {requested}"
            ),
            Self::ContentConflict { key } => {
                write!(
                    f,
                    "content-addressed entry already exists with different bytes: {key}"
                )
            }
            Self::PitLimitExceeded { limit } => {
                write!(f, "pinned PIT limit exceeded: {limit}")
            }
            Self::PitIdExhausted => f.write_str("process-local PIT id space exhausted"),
            Self::SegmentOutOfRange { index, count } => {
                write!(f, "segment index {index} out of range for {count} segments")
            }
            Self::PitNotFound { id } => write!(f, "unknown PIT: {id}"),
            Self::SchemaMismatch { detail } => {
                write!(f, "schema/analyzer mismatch: {detail}")
            }
            Self::Contract(error) => write!(f, "document contract error: {error}"),
            Self::Analysis(error) => write!(f, "analysis error: {error}"),
            Self::Segment(error) => write!(f, "segment error: {error}"),
            Self::Storage(error) => write!(f, "storage error: {error}"),
        }
    }
}

impl std::error::Error for IndexError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Contract(error) => Some(error),
            Self::Analysis(error) => Some(error),
            Self::Segment(error) => Some(error),
            Self::Storage(error) => Some(error),
            _ => None,
        }
    }
}

impl From<QueryError> for IndexError {
    fn from(error: QueryError) -> Self {
        Self::Contract(error)
    }
}

impl From<AnalysisError> for IndexError {
    fn from(error: AnalysisError) -> Self {
        Self::Analysis(error)
    }
}

impl From<SegmentError> for IndexError {
    fn from(error: SegmentError) -> Self {
        Self::Segment(error)
    }
}

impl From<StorageError> for IndexError {
    fn from(error: StorageError) -> Self {
        Self::Storage(error)
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;

    #[test]
    fn displays_and_sources_do_not_panic() {
        let errors = vec![
            IndexError::NotInitialized,
            IndexError::AlreadyInitialized,
            IndexError::WriterBusy,
            IndexError::DuplicateDocument {
                key: "k".to_owned(),
            },
            IndexError::UnsupportedMutation,
            IndexError::IdempotencyConflict {
                token: "t".to_owned(),
            },
            IndexError::RevisionOverflow,
            IndexError::Cancelled,
            IndexError::PendingMutations { pending: 1 },
            IndexError::InvalidRetention {
                detail: "bad".to_owned(),
            },
            IndexError::InvalidCurrent {
                detail: "bad".to_owned(),
            },
            IndexError::CorruptCommittedState {
                detail: "bad".to_owned(),
            },
            IndexError::GenerationOverflow,
            IndexError::RecoveryRequired {
                detail: "bad".to_owned(),
            },
            IndexError::ResourceLimit {
                limit: 1,
                requested: 2,
            },
            IndexError::ContentConflict {
                key: "k".to_owned(),
            },
            IndexError::PitLimitExceeded { limit: 1 },
            IndexError::PitIdExhausted,
            IndexError::SegmentOutOfRange { index: 1, count: 1 },
            IndexError::PitNotFound { id: "p".to_owned() },
            IndexError::SchemaMismatch {
                detail: "bad".to_owned(),
            },
        ];
        for error in &errors {
            let _ = error.to_string();
            assert!(error.source().is_none());
        }
    }
}
