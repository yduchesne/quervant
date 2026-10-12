//! Stable typed error families (A24).

use std::fmt;

use super::budget::BudgetKind;
use super::capability::Capability;
use super::value::FieldType;

/// A low-level value-construction error, mapped to a contextual error by the
/// document or query layer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueError {
    NonFiniteFloat,
    InvalidLongitude,
    InvalidLatitude,
    InvalidPrefixLength,
    HostBitsSet,
    MalformedAddress,
    JsonDepthExceeded { depth: usize },
}

/// Schema definition errors (A05).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SchemaError {
    DuplicateField { field: String },
    UselessField { field: String },
    AnalyzerTypeMismatch { field: String },
    NormalizerTypeMismatch { field: String },
    InvalidPrimaryTimestamp { field: String },
    ColumnarTypeUnsupported { field: String },
}

/// Document validation errors (A01/A03/A04/A07/A13).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DocumentError {
    EmptyKey,
    KeyTooLong { len: usize },
    MissingDocument,
    UnexpectedDocument,
    UnknownField { field: String },
    TypeMismatch { field: String },
    CardinalityMismatch { field: String },
    NullArrayElement { field: String },
    MalformedIp { field: String },
    InvalidCidr { field: String },
    NonFiniteFloat { field: String },
    JsonDepthExceeded { field: String },
    ArrayTooLong { field: String, len: usize },
    TooManyFields { count: usize },
    DocumentTooLarge { bytes: usize },
}

/// Query-shape validation errors.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvalidQueryReason {
    UnknownField {
        field: String,
    },
    UnsupportedOperator {
        field: String,
        operator: &'static str,
    },
    InvalidTimeRange {
        start_us: i64,
        end_us: i64,
    },
    MultiValueSelectorRequired {
        field: String,
    },
    CursorPitMismatch,
    CursorSortMismatch,
    EmptyInValues {
        field: String,
    },
    EmptyBoolean {
        operator: &'static str,
    },
    InvalidIpRange {
        field: String,
    },
    InvalidRadius {
        field: String,
    },
    InvalidTimeBucket,
    InvalidSortField {
        field: String,
    },
    UnstoredProjection {
        field: String,
    },
    ZeroBudget {
        kind: BudgetKind,
    },
    UnconfiguredBudget {
        kind: BudgetKind,
    },
    InvalidBudget {
        kind: BudgetKind,
        requested: u64,
        ceiling: u64,
    },
}

/// Batch-envelope validation errors (A25).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvalidBatchReason {
    Empty,
    TooManyQueries { count: usize, max: usize },
    ConflictingPit,
    InvalidAggregateBudget,
    InvalidAggregateBudgetKind { kind: BudgetKind },
    CardinalityMismatch { expected: usize, actual: usize },
}

/// Terminal reason for a cancelled slot (A25.1).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CancelReason {
    ClientCancellation,
    BatchBudgetExhausted,
    Timeout,
}

/// The unified public error type (A24).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QueryError {
    InvalidSchema(SchemaError),
    InvalidDocument(DocumentError),
    InvalidQuery(InvalidQueryReason),
    InvalidBatch(InvalidBatchReason),
    TypeMismatch {
        field: String,
        expected: FieldType,
        actual: FieldType,
    },
    UnsupportedCapability {
        capability: Capability,
    },
    BudgetExceeded {
        kind: BudgetKind,
    },
    BudgetPolicyViolation {
        kind: BudgetKind,
        requested: u64,
        ceiling: u64,
    },
    Conflict {
        key: String,
    },
    IdempotencyConflict {
        key: String,
    },
    ExpiredCursor,
    NumericOverflow {
        operation: &'static str,
    },
    UnsupportedJsonPath {
        path: String,
    },
    InvalidGeoShape {
        reason: &'static str,
    },
    UnsupportedGeoShape {
        reason: &'static str,
    },
    Cancelled {
        reason: CancelReason,
    },
}

impl QueryError {
    /// Maps a low-level [`ValueError`] into a document-context error.
    #[must_use]
    pub fn document_value(field: &str, error: ValueError) -> Self {
        let field = field.to_owned();
        match error {
            ValueError::NonFiniteFloat => {
                Self::InvalidDocument(DocumentError::NonFiniteFloat { field })
            }
            ValueError::InvalidLongitude | ValueError::InvalidLatitude => {
                Self::InvalidDocument(DocumentError::TypeMismatch { field })
            }
            ValueError::InvalidPrefixLength | ValueError::MalformedAddress => {
                Self::InvalidDocument(DocumentError::InvalidCidr { field })
            }
            ValueError::HostBitsSet => Self::InvalidDocument(DocumentError::InvalidCidr { field }),
            ValueError::JsonDepthExceeded { .. } => {
                Self::InvalidDocument(DocumentError::JsonDepthExceeded { field })
            }
        }
    }

    /// Maps a low-level [`ValueError`] into a query-context error.
    #[must_use]
    pub fn query_value(field: &str, error: ValueError) -> Self {
        let field = field.to_owned();
        match error {
            ValueError::NonFiniteFloat => Self::InvalidGeoShape {
                reason: "non-finite coordinate",
            },
            ValueError::InvalidLongitude | ValueError::InvalidLatitude => Self::InvalidGeoShape {
                reason: "coordinate out of range",
            },
            ValueError::InvalidPrefixLength | ValueError::HostBitsSet => {
                Self::InvalidQuery(InvalidQueryReason::InvalidIpRange { field })
            }
            ValueError::MalformedAddress => {
                Self::InvalidQuery(InvalidQueryReason::InvalidIpRange { field })
            }
            ValueError::JsonDepthExceeded { .. } => {
                Self::InvalidQuery(InvalidQueryReason::InvalidBudget {
                    kind: BudgetKind::JsonDepth,
                    requested: 0,
                    ceiling: 0,
                })
            }
        }
    }
}

impl fmt::Display for QueryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for QueryError {}

impl From<SchemaError> for QueryError {
    fn from(value: SchemaError) -> Self {
        Self::InvalidSchema(value)
    }
}

impl From<DocumentError> for QueryError {
    fn from(value: DocumentError) -> Self {
        Self::InvalidDocument(value)
    }
}

impl From<InvalidQueryReason> for QueryError {
    fn from(value: InvalidQueryReason) -> Self {
        Self::InvalidQuery(value)
    }
}

impl From<InvalidBatchReason> for QueryError {
    fn from(value: InvalidBatchReason) -> Self {
        Self::InvalidBatch(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conversions_and_display() {
        let schema: QueryError = SchemaError::DuplicateField { field: "a".into() }.into();
        assert!(matches!(schema, QueryError::InvalidSchema(_)));
        let document: QueryError = DocumentError::EmptyKey.into();
        assert!(matches!(document, QueryError::InvalidDocument(_)));
        let query: QueryError = InvalidQueryReason::CursorPitMismatch.into();
        assert!(matches!(query, QueryError::InvalidQuery(_)));
        let batch: QueryError = InvalidBatchReason::Empty.into();
        assert!(matches!(batch, QueryError::InvalidBatch(_)));
        assert!(format!("{schema}").contains("InvalidSchema"));
        let _: &dyn std::error::Error = &schema;
    }

    #[test]
    fn value_error_mapping_is_contextual() {
        let cases = [
            (ValueError::NonFiniteFloat, FieldType::F64),
            (ValueError::InvalidLongitude, FieldType::GeoPoint),
            (ValueError::InvalidLatitude, FieldType::GeoPoint),
            (ValueError::InvalidPrefixLength, FieldType::IpNetwork),
            (ValueError::HostBitsSet, FieldType::IpNetwork),
            (ValueError::MalformedAddress, FieldType::IpAddress),
            (ValueError::JsonDepthExceeded { depth: 9 }, FieldType::Json),
        ];
        for (error, _) in cases {
            let document = QueryError::document_value("f", error);
            assert!(matches!(document, QueryError::InvalidDocument(_)));
            let query = QueryError::query_value("f", error);
            assert!(matches!(
                query,
                QueryError::InvalidGeoShape { .. } | QueryError::InvalidQuery(_)
            ));
        }
    }
}
