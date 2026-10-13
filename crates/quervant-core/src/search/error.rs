//! Typed lexical-search failures (PR 7).
//!
//! Every failure mode is explicit: validation errors wrap the existing typed
//! contract/analysis errors, while execution-only failures (unsupported operator,
//! resource bounds, cancellation, corruption and non-finite scores) are distinct
//! variants. No path panics on untrusted input.

use std::fmt;

use crate::analysis::AnalysisError;
use crate::contract::error::QueryError;
use crate::index::IndexError;
use crate::segment::SegmentError;

/// Result alias for lexical search operations.
pub type SearchResult<T> = Result<T, SearchError>;

/// A typed lexical-search failure.
#[derive(Debug)]
#[non_exhaustive]
pub enum SearchError {
    /// Query/TopK/budget shape validation failed.
    Query(QueryError),
    /// Analyzer resolution or query analysis failed.
    Analysis(AnalysisError),
    /// A segment codec read failed or reported corruption.
    Segment(SegmentError),
    /// Snapshot segment opening failed.
    Index(IndexError),
    /// The query references an operator this executor does not implement.
    UnsupportedOperator {
        /// A bounded operator label.
        operator: &'static str,
    },
    /// A configured query resource bound was exceeded.
    ResourceLimit {
        /// The configured limit.
        limit: u64,
        /// The requested amount.
        requested: u64,
    },
    /// Cancellation was requested before the response was produced.
    Cancelled,
    /// The snapshot contains inconsistent or duplicate committed state.
    CorruptIndex {
        /// Bounded human-readable detail (never document content).
        detail: String,
    },
    /// A computed BM25 score was not a finite nonnegative number.
    InvalidScore {
        /// A bounded detail label.
        detail: &'static str,
    },
}

impl fmt::Display for SearchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Query(error) => write!(f, "query error: {error}"),
            Self::Analysis(error) => write!(f, "analysis error: {error}"),
            Self::Segment(error) => write!(f, "segment error: {error}"),
            Self::Index(error) => write!(f, "index error: {error}"),
            Self::UnsupportedOperator { operator } => {
                write!(f, "unsupported query operator: {operator}")
            }
            Self::ResourceLimit { limit, requested } => write!(
                f,
                "search resource limit exceeded: limit {limit}, requested {requested}"
            ),
            Self::Cancelled => f.write_str("search cancelled"),
            Self::CorruptIndex { detail } => write!(f, "corrupt index state: {detail}"),
            Self::InvalidScore { detail } => write!(f, "invalid score: {detail}"),
        }
    }
}

impl std::error::Error for SearchError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Query(error) => Some(error),
            Self::Analysis(error) => Some(error),
            Self::Segment(error) => Some(error),
            Self::Index(error) => Some(error),
            _ => None,
        }
    }
}

impl From<QueryError> for SearchError {
    fn from(error: QueryError) -> Self {
        Self::Query(error)
    }
}

impl From<AnalysisError> for SearchError {
    fn from(error: AnalysisError) -> Self {
        match error {
            AnalysisError::Cancelled => Self::Cancelled,
            other => Self::Analysis(other),
        }
    }
}

impl From<SegmentError> for SearchError {
    fn from(error: SegmentError) -> Self {
        match error {
            SegmentError::Cancelled => Self::Cancelled,
            other => Self::Segment(other),
        }
    }
}

impl From<IndexError> for SearchError {
    fn from(error: IndexError) -> Self {
        Self::Index(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conversions_and_display() {
        let search: SearchError = QueryError::ExpiredCursor.into();
        assert!(matches!(search, SearchError::Query(_)));
        let search: SearchError = AnalysisError::EmptyTerm.into();
        assert!(matches!(search, SearchError::Analysis(_)));
        let search: SearchError = AnalysisError::Cancelled.into();
        assert!(matches!(search, SearchError::Cancelled));
        let search: SearchError = SegmentError::Cancelled.into();
        assert!(matches!(search, SearchError::Cancelled));
        let search: SearchError = SegmentError::InvalidVarint { context: "x" }.into();
        assert!(matches!(search, SearchError::Segment(_)));
        let errors = [
            SearchError::UnsupportedOperator { operator: "prefix" },
            SearchError::ResourceLimit {
                limit: 1,
                requested: 2,
            },
            SearchError::Cancelled,
            SearchError::CorruptIndex {
                detail: "d".to_owned(),
            },
            SearchError::InvalidScore { detail: "nan" },
        ];
        for error in &errors {
            assert!(!error.to_string().is_empty());
            let _: &dyn std::error::Error = error;
        }
    }

    #[test]
    fn every_variant_displays_and_exposes_sources() {
        use crate::index::IndexError;
        use std::error::Error;
        let variants = [
            SearchError::Query(QueryError::ExpiredCursor),
            SearchError::Analysis(AnalysisError::EmptyTerm),
            SearchError::Segment(SegmentError::InvalidVarint { context: "x" }),
            SearchError::Index(IndexError::NotInitialized),
            SearchError::UnsupportedOperator { operator: "glob" },
            SearchError::ResourceLimit {
                limit: 5,
                requested: 6,
            },
            SearchError::Cancelled,
            SearchError::CorruptIndex {
                detail: "detail".to_owned(),
            },
            SearchError::InvalidScore { detail: "score" },
        ];
        for (index, error) in variants.iter().enumerate() {
            assert!(!error.to_string().is_empty());
            let has_source = error.source().is_some();
            // The first four wrap typed sources; the rest are leaves.
            assert_eq!(has_source, index < 4, "variant {index}");
        }
        let indexed: SearchError = IndexError::WriterBusy.into();
        assert!(matches!(indexed, SearchError::Index(_)));
    }
}
