//! Sorting, projection, top-K and opaque PIT/cursor shapes (A15, A21, A23).

use std::fmt;

use super::budget::{BudgetKind, Budgets};
use super::document::DocumentKey;
use super::error::{InvalidQueryReason, QueryError};
use super::query::JsonPathExpr;
use super::schema::Schema;
use super::value::{GeoPoint, Timestamp};

/// Sort direction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SortDirection {
    Asc,
    Desc,
}

/// Where missing/null values sort.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MissingValuePosition {
    First,
    Last,
}

/// Required selector for multi-value sort fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MultiValueSelector {
    Min,
    Max,
}

/// One sort key.
///
/// `PartialEq` is derived (over the validated `GeoPoint`); `Eq` is implemented
/// manually because `GeoPoint` is not `Eq`.
#[derive(Debug, Clone, PartialEq)]
pub struct SortField {
    pub field: String,
    pub direction: SortDirection,
    pub missing: MissingValuePosition,
    pub multi: Option<MultiValueSelector>,
    /// When set, order by the minimum spherical distance from this point to the
    /// field's indexed GeoPoint values (ascending unless `direction` is `Desc`).
    pub distance_from: Option<GeoPoint>,
    /// When set, order by the value at this concrete indexed JSON path.
    pub json_path: Option<JsonPathExpr>,
}

impl Eq for SortField {}

impl SortField {
    #[must_use]
    pub fn new(field: impl Into<String>, direction: SortDirection) -> Self {
        Self {
            field: field.into(),
            direction,
            missing: MissingValuePosition::Last,
            multi: None,
            distance_from: None,
            json_path: None,
        }
    }

    #[must_use]
    pub fn with_multi(mut self, selector: MultiValueSelector) -> Self {
        self.multi = Some(selector);
        self
    }

    /// Order by the value at a concrete indexed JSON path.
    #[must_use]
    pub fn with_json_path(mut self, path: JsonPathExpr) -> Self {
        self.json_path = Some(path);
        self
    }

    /// Order by the minimum distance from `origin` to an indexed GeoPoint field.
    #[must_use]
    pub fn geo_distance(
        field: impl Into<String>,
        origin: GeoPoint,
        direction: SortDirection,
    ) -> Self {
        Self {
            field: field.into(),
            direction,
            missing: MissingValuePosition::Last,
            multi: None,
            distance_from: Some(origin),
            json_path: None,
        }
    }
}

/// A total, deterministic sort order. The engine always appends the logical
/// document key as the final tie-break (A15).
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Sort {
    pub fields: Vec<SortField>,
}

impl Sort {
    #[must_use]
    pub fn new(fields: Vec<SortField>) -> Self {
        Self { fields }
    }

    pub fn validate(&self, schema: &Schema) -> Result<(), QueryError> {
        for field in &self.fields {
            let definition =
                schema
                    .get(&field.field)
                    .ok_or_else(|| InvalidQueryReason::InvalidSortField {
                        field: field.field.clone(),
                    })?;
            if field.distance_from.is_some() {
                if definition.field_type != super::value::FieldType::GeoPoint
                    || !definition.options.indexed
                {
                    return Err(InvalidQueryReason::InvalidSortField {
                        field: field.field.clone(),
                    }
                    .into());
                }
                continue;
            }
            if field.json_path.is_some() {
                if definition.field_type != super::value::FieldType::Json
                    || !definition.options.indexed
                {
                    return Err(InvalidQueryReason::InvalidSortField {
                        field: field.field.clone(),
                    }
                    .into());
                }
                if definition.cardinality == super::document::Cardinality::Multi
                    && field.multi.is_none()
                {
                    return Err(InvalidQueryReason::MultiValueSelectorRequired {
                        field: field.field.clone(),
                    }
                    .into());
                }
                if field
                    .json_path
                    .as_ref()
                    .is_some_and(|path| !path.is_concrete())
                    && field.multi.is_none()
                {
                    return Err(InvalidQueryReason::MultiValueSelectorRequired {
                        field: field.field.clone(),
                    }
                    .into());
                }
                continue;
            }
            if !definition.options.columnar {
                return Err(InvalidQueryReason::InvalidSortField {
                    field: field.field.clone(),
                }
                .into());
            }
            if definition.cardinality == super::document::Cardinality::Multi
                && field.multi.is_none()
            {
                return Err(InvalidQueryReason::MultiValueSelectorRequired {
                    field: field.field.clone(),
                }
                .into());
            }
        }
        Ok(())
    }
}

/// Stored-field selection (A23). Computed expressions are not supported.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Projection {
    Source,
    Fields(Vec<String>),
}

impl Projection {
    pub fn validate(&self, schema: &Schema) -> Result<(), QueryError> {
        if let Self::Fields(fields) = self {
            for field in fields {
                let definition =
                    schema
                        .get(field)
                        .ok_or_else(|| InvalidQueryReason::UnknownField {
                            field: field.clone(),
                        })?;
                if !definition.options.stored {
                    return Err(InvalidQueryReason::UnstoredProjection {
                        field: field.clone(),
                    }
                    .into());
                }
            }
        }
        Ok(())
    }
}

/// A bounded top-K request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TopK {
    pub limit: usize,
}

impl TopK {
    pub fn new(limit: usize) -> Result<Self, QueryError> {
        if limit == 0 {
            return Err(InvalidQueryReason::ZeroBudget {
                kind: BudgetKind::ResultWindow,
            }
            .into());
        }
        Ok(Self { limit })
    }

    pub fn validate(&self, budgets: &Budgets) -> Result<(), QueryError> {
        if let Some(max) = budgets.get(BudgetKind::ResultWindow) {
            if u64::try_from(self.limit).unwrap_or(u64::MAX) > max {
                return Err(QueryError::BudgetExceeded {
                    kind: BudgetKind::ResultWindow,
                });
            }
        }
        Ok(())
    }
}

/// An opaque PIT snapshot token (A21).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PitId(String);

impl PitId {
    pub fn new(value: impl Into<String>) -> Result<Self, QueryError> {
        let value = value.into();
        if value.is_empty() {
            return Err(InvalidQueryReason::CursorPitMismatch.into());
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for PitId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// One scalar component of a complete cursor sort tuple.
///
/// This is a contract-local, Eq-safe representation. It deliberately does not
/// expose `search::SortValue` at the public contract layer, and all floating
/// point members are stored as IEEE-754 bit patterns.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CursorAtom {
    Missing,
    Null,
    Bool(bool),
    I64(i64),
    U64(u64),
    F64Bits(u64),
    TimestampMicros(i64),
    Keyword(String),
    Ip(std::net::IpAddr),
}

/// Private, immutable continuation payload for a PIT-bound public cursor.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CursorContinuationV1 {
    pub(crate) snapshot_binding: u64,
    pub(crate) fingerprint: [u8; 32],
    pub(crate) tuple: Vec<CursorAtom>,
    pub(crate) relevance_bits: Option<u64>,
}

/// An opaque PIT-bound search-after cursor (A21).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cursor {
    pit: PitId,
    sort: Sort,
    last_key: DocumentKey,
    expires_at: Timestamp,
    continuation: Option<CursorContinuationV1>,
}

impl Cursor {
    /// Construct a legacy position-only cursor.
    ///
    /// Source-compatible with previous releases. Such a cursor is intentionally
    /// not resumable by the pinned batch API because `last_key` alone cannot
    /// encode the full sort tuple or query/snapshot binding.
    #[must_use]
    pub fn new(pit: PitId, sort: Sort, last_key: DocumentKey, expires_at: Timestamp) -> Self {
        Self {
            pit,
            sort,
            last_key,
            expires_at,
            continuation: None,
        }
    }

    /// Construct a cursor carrying the complete private continuation payload.
    pub(crate) fn from_continuation_v1(
        pit: PitId,
        sort: Sort,
        last_key: DocumentKey,
        expires_at: Timestamp,
        continuation: CursorContinuationV1,
    ) -> Self {
        Self {
            pit,
            sort,
            last_key,
            expires_at,
            continuation: Some(continuation),
        }
    }

    #[must_use]
    pub fn pit(&self) -> &PitId {
        &self.pit
    }

    #[must_use]
    pub fn last_key(&self) -> &DocumentKey {
        &self.last_key
    }

    /// The private complete continuation payload, if this cursor was issued by
    /// the pinned batch API.
    pub(crate) fn continuation_v1(&self) -> Option<&CursorContinuationV1> {
        self.continuation.as_ref()
    }

    /// The cursor expiry timestamp.
    pub(crate) fn expires_at(&self) -> Timestamp {
        self.expires_at
    }

    /// The sort definition this cursor is bound to.
    pub(crate) fn sort(&self) -> &Sort {
        &self.sort
    }

    /// Validates the cursor against the request's PIT and sort order.
    pub fn validate(&self, pit: &PitId, sort: &Sort, now: Timestamp) -> Result<(), QueryError> {
        if now >= self.expires_at {
            return Err(QueryError::ExpiredCursor);
        }
        self.matches(pit, sort)
    }

    /// Validates only the PIT and sort binding, without expiry.
    pub fn matches(&self, pit: &PitId, sort: &Sort) -> Result<(), QueryError> {
        if &self.pit != pit {
            return Err(InvalidQueryReason::CursorPitMismatch.into());
        }
        if &self.sort != sort {
            return Err(InvalidQueryReason::CursorSortMismatch.into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "score",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "hidden",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn sort_requires_multi_selector_and_columnar() {
        let schema = schema();
        assert!(
            Sort::new(vec![SortField::new("score", SortDirection::Asc)])
                .validate(&schema)
                .is_ok()
        );
        assert!(
            Sort::new(vec![SortField::new("tags", SortDirection::Asc)])
                .validate(&schema)
                .is_err()
        );
        assert!(
            Sort::new(vec![
                SortField::new("tags", SortDirection::Asc).with_multi(MultiValueSelector::Max)
            ])
            .validate(&schema)
            .is_ok()
        );
        assert!(
            Sort::new(vec![SortField::new("hidden", SortDirection::Asc)])
                .validate(&schema)
                .is_err()
        );
        assert!(
            Sort::new(vec![SortField::new("missing", SortDirection::Asc)])
                .validate(&schema)
                .is_err()
        );
    }

    #[test]
    fn projection_requires_stored_fields() {
        let schema = schema();
        assert!(Projection::Source.validate(&schema).is_ok());
        assert!(
            Projection::Fields(vec!["score".into()])
                .validate(&schema)
                .is_ok()
        );
        assert!(
            Projection::Fields(vec!["hidden".into()])
                .validate(&schema)
                .is_err()
        );
        assert!(
            Projection::Fields(vec!["missing".into()])
                .validate(&schema)
                .is_err()
        );
    }

    #[test]
    fn topk_and_cursor_validation() {
        assert!(TopK::new(0).is_err());
        let budgets = Budgets::new().with(BudgetKind::ResultWindow, 10).unwrap();
        assert!(TopK::new(10).unwrap().validate(&budgets).is_ok());
        assert!(TopK::new(11).unwrap().validate(&budgets).is_err());

        let pit = PitId::new("pit-A").unwrap();
        let sort = Sort::new(vec![SortField::new("score", SortDirection::Desc)]);
        let cursor = Cursor::new(
            pit.clone(),
            sort.clone(),
            DocumentKey::new("doc").unwrap(),
            Timestamp::from_micros(100),
        );
        assert!(
            cursor
                .validate(&pit, &sort, Timestamp::from_micros(50))
                .is_ok()
        );
        assert_eq!(
            cursor.validate(&pit, &sort, Timestamp::from_micros(100)),
            Err(QueryError::ExpiredCursor)
        );
        let other = PitId::new("pit-B").unwrap();
        assert!(
            cursor
                .validate(&other, &sort, Timestamp::from_micros(1))
                .is_err()
        );
        let other_sort = Sort::default();
        assert!(
            cursor
                .validate(&pit, &other_sort, Timestamp::from_micros(1))
                .is_err()
        );
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    #[test]
    fn sort_field_defaults_and_selector() {
        let field = SortField::new("score", SortDirection::Desc);
        assert_eq!(field.missing, MissingValuePosition::Last);
        assert_eq!(field.multi, None);
        let with_multi = field.with_multi(MultiValueSelector::Min);
        assert_eq!(with_multi.multi, Some(MultiValueSelector::Min));
        assert_eq!(MissingValuePosition::First, MissingValuePosition::First);
    }

    #[test]
    fn pit_and_cursor_helpers() {
        assert!(PitId::new("").is_err());
        assert_eq!(PitId::new("pit").unwrap().as_str(), "pit");
        assert!(format!("{}", PitId::new("pit").unwrap()).contains("pit"));
        let pit = PitId::new("pit").unwrap();
        let sort = Sort::new(vec![SortField::new("score", SortDirection::Asc)]);
        let cursor = Cursor::new(
            pit.clone(),
            sort.clone(),
            DocumentKey::new("k").unwrap(),
            Timestamp::from_micros(100),
        );
        assert_eq!(cursor.pit(), &pit);
        assert_eq!(cursor.last_key().as_str(), "k");
        assert!(cursor.matches(&pit, &sort).is_ok());
        let other = PitId::new("other").unwrap();
        assert!(matches!(
            cursor.matches(&other, &sort),
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch
            ))
        ));
        assert!(matches!(
            cursor.matches(&pit, &Sort::default()),
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::CursorSortMismatch
            ))
        ));
    }

    #[test]
    fn projection_default_variants_and_topk_zero() {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "k",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )],
            None,
        )
        .unwrap();
        assert!(
            Projection::Fields(vec!["k".into()])
                .validate(&schema)
                .is_err()
        );
        assert!(TopK::new(0).is_err());
    }
}
