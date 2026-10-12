//! Typed analyzer failures.
//!
//! Every analyzer entry point is fallible. User-supplied text, configuration and pinned
//! datasets can all fail; none of those paths may panic, wrap, saturate or silently truncate.

use std::fmt;

/// A typed analysis failure.
///
/// Variants are intentionally granular so callers can distinguish configuration errors,
/// budget exhaustion, cancellation and dataset incompatibility without string matching.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum AnalysisError {
    /// The analyzer/tokenizer/filter configuration is internally inconsistent.
    InvalidConfiguration { reason: String },
    /// The requested analyzer/normalizer name is not registered.
    UnknownAnalyzer { name: String },
    /// A registered analyzer's version/fingerprint does not match what the caller pinned.
    AnalyzerVersionMismatch { expected: String, found: String },
    /// A registered analyzer's canonical fingerprint does not match what the caller pinned.
    AnalyzerFingerprintMismatch { expected: String, found: String },
    /// A configured character filter is not implemented (length-changing filters are deferred).
    UnsupportedCharacterFilter { name: String },
    /// A produced token violates the token contract (bad increment/length/empty term).
    InvalidToken { reason: String },
    /// A byte offset is not a valid UTF-8 boundary or lies outside the source value.
    InvalidOffset { reason: String },
    /// A position could not be represented or incremented without overflowing `u32`.
    PositionOverflow,
    /// An offset could not be represented without overflowing `u32`.
    OffsetOverflow,
    /// The source value exceeds the configured input-byte budget.
    InputTooLarge { limit: u64, actual: u64 },
    /// The call would emit more tokens than the configured budget allows.
    TooManyTokens { limit: u64 },
    /// A single emitted term exceeds the configured term-byte budget.
    TermTooLarge { limit: u64, actual: u64 },
    /// The deterministic work budget was exhausted.
    WorkBudgetExceeded { limit: u64 },
    /// Cancellation was requested; no further tokens are produced.
    Cancelled,
    /// A domain string is not a valid domain under the configured policy.
    MalformedDomain { reason: String },
    /// A pinned dataset version does not match the embedded dataset identity.
    DatasetVersionMismatch { expected: String, found: String },
    /// A pinned embedded dataset could not be parsed into a usable representation.
    InvalidDataset { name: String, reason: String },
    /// A glob/regex pattern uses syntax outside the approved bounded subset.
    UnsupportedPattern { reason: String },
    /// A term-query preparation produced no term (e.g. all tokens were stopwords).
    EmptyTerm,
    /// A term-query preparation produced more than one term where exactly one was required.
    TooManyTerms { count: usize },
}

impl fmt::Display for AnalysisError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidConfiguration { reason } => {
                write!(f, "invalid analyzer configuration: {reason}")
            }
            Self::UnknownAnalyzer { name } => write!(f, "unknown analyzer: {name}"),
            Self::AnalyzerVersionMismatch { expected, found } => write!(
                f,
                "analyzer version mismatch: expected {expected}, found {found}"
            ),
            Self::AnalyzerFingerprintMismatch { expected, found } => write!(
                f,
                "analyzer fingerprint mismatch: expected {expected}, found {found}"
            ),
            Self::UnsupportedCharacterFilter { name } => {
                write!(f, "unsupported character filter: {name}")
            }
            Self::InvalidToken { reason } => write!(f, "invalid token: {reason}"),
            Self::InvalidOffset { reason } => write!(f, "invalid offset: {reason}"),
            Self::PositionOverflow => f.write_str("token position overflow"),
            Self::OffsetOverflow => f.write_str("token offset overflow"),
            Self::InputTooLarge { limit, actual } => {
                write!(f, "input of {actual} bytes exceeds limit {limit}")
            }
            Self::TooManyTokens { limit } => write!(f, "token count exceeds limit {limit}"),
            Self::TermTooLarge { limit, actual } => {
                write!(f, "term of {actual} bytes exceeds limit {limit}")
            }
            Self::WorkBudgetExceeded { limit } => {
                write!(f, "analysis work budget {limit} exhausted")
            }
            Self::Cancelled => f.write_str("analysis cancelled"),
            Self::MalformedDomain { reason } => write!(f, "malformed domain: {reason}"),
            Self::DatasetVersionMismatch { expected, found } => write!(
                f,
                "dataset version mismatch: expected {expected}, found {found}"
            ),
            Self::InvalidDataset { name, reason } => {
                write!(f, "invalid embedded dataset {name}: {reason}")
            }
            Self::UnsupportedPattern { reason } => {
                write!(f, "unsupported pattern: {reason}")
            }
            Self::EmptyTerm => f.write_str("term query prepared no term"),
            Self::TooManyTerms { count } => {
                write!(f, "term query prepared {count} terms, expected exactly one")
            }
        }
    }
}

impl std::error::Error for AnalysisError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_variant_has_a_message() {
        let errors = [
            AnalysisError::InvalidConfiguration {
                reason: "x".to_owned(),
            },
            AnalysisError::UnknownAnalyzer {
                name: "x".to_owned(),
            },
            AnalysisError::AnalyzerVersionMismatch {
                expected: "1".to_owned(),
                found: "2".to_owned(),
            },
            AnalysisError::AnalyzerFingerprintMismatch {
                expected: "1".to_owned(),
                found: "2".to_owned(),
            },
            AnalysisError::UnsupportedCharacterFilter {
                name: "x".to_owned(),
            },
            AnalysisError::InvalidToken {
                reason: "x".to_owned(),
            },
            AnalysisError::InvalidOffset {
                reason: "x".to_owned(),
            },
            AnalysisError::PositionOverflow,
            AnalysisError::OffsetOverflow,
            AnalysisError::InputTooLarge {
                limit: 1,
                actual: 2,
            },
            AnalysisError::TooManyTokens { limit: 1 },
            AnalysisError::TermTooLarge {
                limit: 1,
                actual: 2,
            },
            AnalysisError::WorkBudgetExceeded { limit: 1 },
            AnalysisError::Cancelled,
            AnalysisError::MalformedDomain {
                reason: "x".to_owned(),
            },
            AnalysisError::DatasetVersionMismatch {
                expected: "1".to_owned(),
                found: "2".to_owned(),
            },
            AnalysisError::InvalidDataset {
                name: "psl".to_owned(),
                reason: "x".to_owned(),
            },
            AnalysisError::UnsupportedPattern {
                reason: "x".to_owned(),
            },
            AnalysisError::EmptyTerm,
            AnalysisError::TooManyTerms { count: 3 },
        ];
        for error in errors {
            let message = error.to_string();
            assert!(!message.is_empty(), "empty message for {error:?}");
            let _: &dyn std::error::Error = &error;
        }
    }
}
