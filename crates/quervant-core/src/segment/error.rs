//! Typed immutable-segment codec errors (PR 5, plan step A2).
//!
//! Errors never carry raw document/term content beyond a bounded context label;
//! they describe *what* failed, not the bytes that failed.

use std::fmt;

use crate::storage::StorageError;

/// Result alias for segment codec operations.
pub type SegmentResult<T> = Result<T, SegmentError>;

/// A typed segment/manifest codec failure.
///
/// Every malformed, truncated, hostile or unsupported input maps to one of these
/// variants; codecs never panic and never allocate from an unvalidated count.
#[derive(Debug)]
#[non_exhaustive]
pub enum SegmentError {
    /// The leading magic bytes were not the expected container magic.
    InvalidMagic {
        /// Bounded context label (for example `"segment header"`).
        context: &'static str,
    },
    /// The major/minor format version is not supported.
    UnsupportedFormatVersion {
        /// Read major version.
        major: u16,
        /// Read minor version.
        minor: u16,
    },
    /// A required feature id/version is not supported by this reader.
    UnsupportedFeature {
        /// Numeric on-disk feature id.
        feature_id: u16,
        /// Required feature version.
        version: u16,
    },
    /// An unknown set flag bit was encountered.
    UnknownFlags {
        /// Bounded context label.
        context: &'static str,
        /// The offending flag bits.
        flags: u64,
    },
    /// The input ended before a declared field could be read.
    Truncated {
        /// Bounded context label.
        context: &'static str,
        /// Bytes required.
        needed: u64,
        /// Bytes available.
        available: u64,
    },
    /// A declared offset/length extent is invalid for the container.
    InvalidExtent {
        /// Bounded context label.
        context: &'static str,
        /// Declared offset.
        offset: u64,
        /// Declared length.
        length: u64,
        /// Upper bound (exclusive).
        limit: u64,
    },
    /// Section bodies are not contiguous at this offset.
    NonContiguousSections {
        /// Expected offset.
        expected: u64,
        /// Found offset.
        found: u64,
    },
    /// Two sections declared the same kind.
    DuplicateSection {
        /// Section kind.
        kind: u16,
    },
    /// A required structural section is missing.
    MissingSection {
        /// Section kind.
        kind: u16,
    },
    /// Structural corruption with a bounded description.
    Corrupt {
        /// Bounded context label.
        context: &'static str,
        /// Short human-readable detail (never document content).
        detail: String,
    },
    /// A stored digest did not match the recomputed digest.
    DigestMismatch {
        /// Bounded context label.
        context: &'static str,
    },
    /// A stored length did not match the actual length.
    LengthMismatch {
        /// Bounded context label.
        context: &'static str,
        /// Declared length.
        expected: u64,
        /// Actual length.
        actual: u64,
    },
    /// A configured resource budget was exceeded.
    LimitExceeded {
        /// The configured limit.
        limit: u64,
        /// The requested amount.
        requested: u64,
    },
    /// An unsigned varint was overlong or exceeded `u64`.
    InvalidVarint {
        /// Bounded context label.
        context: &'static str,
    },
    /// An unexpected field type tag was read.
    InvalidFieldTypeTag {
        /// The offending tag.
        tag: u8,
    },
    /// Two schema fields shared a canonical id or name.
    DuplicateField {
        /// Field name.
        name: String,
    },
    /// An invalid cardinality tag was read.
    InvalidCardinality {
        /// The offending tag.
        value: u8,
    },
    /// An invalid logical field-state tag was read.
    InvalidFieldState {
        /// The offending tag.
        value: u8,
    },
    /// A term occurred more than once within one field dictionary.
    DuplicateTerm {
        /// Field id.
        field_id: u32,
        /// Term bytes (bounded by the term limit).
        term: String,
    },
    /// Posting doc ids were not strictly increasing.
    NonMonotoneDocId {
        /// Previous doc id.
        previous: u64,
        /// Offending doc id.
        next: u64,
    },
    /// A posting frequency was zero.
    ZeroFrequency {
        /// Doc id with zero frequency.
        doc_id: u64,
    },
    /// Occurrence positions were not strictly increasing within a doc.
    NonMonotonePosition {
        /// Doc id.
        doc_id: u64,
    },
    /// The sorted doc-id permutation was not bijective.
    InvalidRemap {
        /// Bounded description.
        context: &'static str,
    },
    /// A persisted analyzer fingerprint did not match the resolved analyzer.
    AnalyzerFingerprintMismatch {
        /// Field name.
        field: String,
    },
    /// A reference used an unknown field id.
    UnknownFieldId {
        /// The unknown id.
        field_id: u32,
    },
    /// A field value did not match the schema field type.
    FieldTypeMismatch {
        /// Field name.
        field: String,
    },
    /// A GeoPoint was non-finite or out of range.
    InvalidGeo {
        /// Short detail.
        detail: &'static str,
    },
    /// An IP/CIDR value was malformed.
    InvalidIp {
        /// Short detail.
        detail: &'static str,
    },
    /// Bytes claimed to be UTF-8 were not.
    InvalidUtf8 {
        /// Bounded context label.
        context: &'static str,
    },
    /// A non-finite float was encountered where finite was required.
    NonFiniteFloat {
        /// Bounded context label.
        context: &'static str,
    },
    /// Column block geometry was inconsistent.
    InvalidColumnGeometry {
        /// Bounded description.
        detail: &'static str,
    },
    /// A manifest reference was missing, duplicated or malformed.
    InvalidManifest {
        /// Short human-readable detail.
        detail: String,
    },
    /// The operation was cooperatively cancelled.
    Cancelled,
    /// An underlying local storage operation failed.
    Storage(StorageError),
}

impl fmt::Display for SegmentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidMagic { context } => write!(f, "invalid magic in {context}"),
            Self::UnsupportedFormatVersion { major, minor } => {
                write!(f, "unsupported format version {major}.{minor}")
            }
            Self::UnsupportedFeature {
                feature_id,
                version,
            } => write!(f, "unsupported required feature {feature_id} v{version}"),
            Self::UnknownFlags { context, flags } => {
                write!(f, "unknown flag bits 0x{flags:x} in {context}")
            }
            Self::Truncated {
                context,
                needed,
                available,
            } => write!(
                f,
                "truncated {context}: needed {needed} bytes, {available} available"
            ),
            Self::InvalidExtent {
                context,
                offset,
                length,
                limit,
            } => write!(
                f,
                "invalid extent in {context}: offset {offset}, length {length}, limit {limit}"
            ),
            Self::NonContiguousSections { expected, found } => {
                write!(
                    f,
                    "non-contiguous sections: expected offset {expected}, found {found}"
                )
            }
            Self::DuplicateSection { kind } => write!(f, "duplicate section kind {kind}"),
            Self::MissingSection { kind } => write!(f, "missing required section kind {kind}"),
            Self::Corrupt { context, detail } => write!(f, "corrupt {context}: {detail}"),
            Self::DigestMismatch { context } => write!(f, "digest mismatch in {context}"),
            Self::LengthMismatch {
                context,
                expected,
                actual,
            } => write!(
                f,
                "length mismatch in {context}: expected {expected}, actual {actual}"
            ),
            Self::LimitExceeded { limit, requested } => write!(
                f,
                "resource limit exceeded: limit {limit}, requested {requested}"
            ),
            Self::InvalidVarint { context } => write!(f, "invalid varint in {context}"),
            Self::InvalidFieldTypeTag { tag } => write!(f, "invalid field type tag {tag}"),
            Self::DuplicateField { name } => write!(f, "duplicate schema field {name}"),
            Self::InvalidCardinality { value } => write!(f, "invalid cardinality tag {value}"),
            Self::InvalidFieldState { value } => write!(f, "invalid field state tag {value}"),
            Self::DuplicateTerm { field_id, term } => {
                write!(f, "duplicate term in field {field_id}: {term}")
            }
            Self::NonMonotoneDocId { previous, next } => {
                write!(f, "non-monotone posting doc id {next} after {previous}")
            }
            Self::ZeroFrequency { doc_id } => write!(f, "zero frequency for doc {doc_id}"),
            Self::NonMonotonePosition { doc_id } => {
                write!(f, "non-monotone position for doc {doc_id}")
            }
            Self::InvalidRemap { context } => write!(f, "invalid doc-id remap: {context}"),
            Self::AnalyzerFingerprintMismatch { field } => {
                write!(f, "analyzer fingerprint mismatch for field {field}")
            }
            Self::UnknownFieldId { field_id } => write!(f, "unknown field id {field_id}"),
            Self::FieldTypeMismatch { field } => write!(f, "field type mismatch for {field}"),
            Self::InvalidGeo { detail } => write!(f, "invalid geo value: {detail}"),
            Self::InvalidIp { detail } => write!(f, "invalid ip value: {detail}"),
            Self::InvalidUtf8 { context } => write!(f, "invalid utf-8 in {context}"),
            Self::NonFiniteFloat { context } => {
                write!(f, "non-finite float in {context}")
            }
            Self::InvalidColumnGeometry { detail } => {
                write!(f, "invalid column geometry: {detail}")
            }
            Self::InvalidManifest { detail } => write!(f, "invalid manifest: {detail}"),
            Self::Cancelled => f.write_str("segment operation cancelled"),
            Self::Storage(error) => write!(f, "storage error: {error}"),
        }
    }
}

impl std::error::Error for SegmentError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Storage(error) => Some(error),
            _ => None,
        }
    }
}

impl From<StorageError> for SegmentError {
    fn from(error: StorageError) -> Self {
        match error {
            StorageError::Cancelled => Self::Cancelled,
            other => Self::Storage(other),
        }
    }
}
