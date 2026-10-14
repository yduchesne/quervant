//! Canonical typed scalar comparison, range matching and sort tuples (PR 10).
//!
//! One comparator is shared by the bounded top-K heap, final response ordering
//! and search-after cursor validation so that those three paths cannot disagree.
//! All ordering is total and deterministic; unsupported scalar types fail
//! closed during request validation and never reach this module.

use std::cmp::Ordering;
use std::net::IpAddr;

use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::query::Bound;
use crate::contract::result::{
    MissingValuePosition, MultiValueSelector, Sort, SortDirection, SortField,
};
use crate::contract::value::{FieldType, FieldValue};
use crate::segment::value::encode_scalar;
use crate::segment::{CodecField, CodecSchema, ColumnReader, SegmentError, SegmentReader};

/// One value in a typed sort tuple.
///
/// `Missing` (the field is absent) and `Null` (an explicit null) are distinct
/// and never collapse into one another.
#[derive(Debug, Clone, PartialEq)]
pub enum SortValue {
    /// The field is absent from the document.
    Missing,
    /// The field is an explicit null.
    Null,
    /// A non-null typed scalar value.
    Value(FieldValue),
}

impl SortValue {
    /// The scalar value, if this entry is neither missing nor null.
    #[must_use]
    pub const fn as_value(&self) -> Option<&FieldValue> {
        match self {
            Self::Value(value) => Some(value),
            Self::Missing | Self::Null => None,
        }
    }

    /// The canonical encoding of the value, if any.
    pub fn canonical_bytes(&self) -> Option<Vec<u8>> {
        match self {
            Self::Value(value) => canonical_scalar_bytes(value).ok(),
            Self::Missing | Self::Null => None,
        }
    }
}

/// Whether a field type participates in typed range/time predicates.
#[must_use]
pub const fn is_range_type(field_type: FieldType) -> bool {
    matches!(
        field_type,
        FieldType::I64 | FieldType::U64 | FieldType::F64 | FieldType::Timestamp
    )
}

/// Whether a field type is a supported typed sort/group/frequency scalar.
#[must_use]
pub const fn is_typed_scalar(field_type: FieldType) -> bool {
    matches!(
        field_type,
        FieldType::Bool
            | FieldType::I64
            | FieldType::U64
            | FieldType::F64
            | FieldType::Timestamp
            | FieldType::Keyword
            | FieldType::IpAddress
    )
}

/// Whether a field type is a supported `SUM`/`AVG` metric.
#[must_use]
pub const fn is_sum_type(field_type: FieldType) -> bool {
    matches!(field_type, FieldType::I64 | FieldType::U64 | FieldType::F64)
}

/// Whether a field type is a supported `MIN`/`MAX` metric.
#[must_use]
pub const fn is_min_max_type(field_type: FieldType) -> bool {
    matches!(
        field_type,
        FieldType::I64 | FieldType::U64 | FieldType::F64 | FieldType::Timestamp
    )
}

/// Deterministic total order over typed scalars of the same declared type.
///
/// Values of different types are ordered by a stable type rank; callers only
/// ever compare values of one field, but a total order keeps the comparator
/// panic-free on corrupt input.
#[must_use]
pub fn canonical_scalar_cmp(a: &FieldValue, b: &FieldValue) -> Ordering {
    if a.field_type() != b.field_type() {
        return type_rank(a.field_type()).cmp(&type_rank(b.field_type()));
    }
    match (a, b) {
        (FieldValue::Bool(a), FieldValue::Bool(b)) => a.cmp(b),
        (FieldValue::I64(a), FieldValue::I64(b)) => a.cmp(b),
        (FieldValue::U64(a), FieldValue::U64(b)) => a.cmp(b),
        (FieldValue::F64(a), FieldValue::F64(b)) => a.total_cmp(b),
        (FieldValue::Timestamp(a), FieldValue::Timestamp(b)) => a.cmp(b),
        (FieldValue::Keyword(a), FieldValue::Keyword(b)) => a.as_bytes().cmp(b.as_bytes()),
        (FieldValue::Ip(a), FieldValue::Ip(b)) => ip_rank(*a).cmp(&ip_rank(*b)),
        // Unsupported types never reach this path; keep a deterministic fallback.
        _ => Ordering::Equal,
    }
}

/// Canonical, deterministic bytes for a typed scalar.
pub fn canonical_scalar_bytes(value: &FieldValue) -> Result<Vec<u8>, SegmentError> {
    let mut writer = crate::segment::format::ByteWriter::new();
    encode_scalar(&mut writer, value.field_type(), value)?;
    Ok(writer.into_vec())
}

const fn type_rank(field_type: FieldType) -> u8 {
    match field_type {
        FieldType::Bool => 0,
        FieldType::I64 => 1,
        FieldType::U64 => 2,
        FieldType::F64 => 3,
        FieldType::Timestamp => 4,
        FieldType::Keyword => 5,
        FieldType::IpAddress => 6,
        FieldType::Text => 7,
        FieldType::Json => 8,
        FieldType::GeoPoint => 9,
        FieldType::IpNetwork => 10,
    }
}

fn ip_rank(addr: IpAddr) -> (u8, u128) {
    match addr {
        IpAddr::V4(v4) => (0, u128::from(u32::from(v4))),
        IpAddr::V6(v6) => (1, u128::from(v6)),
    }
}

fn rank_of(value: &SortValue, position: MissingValuePosition) -> u8 {
    match (value, position) {
        (SortValue::Missing, MissingValuePosition::First) => 0,
        (SortValue::Null, MissingValuePosition::First) => 1,
        (SortValue::Value(_), MissingValuePosition::First) => 2,
        (SortValue::Value(_), MissingValuePosition::Last) => 0,
        (SortValue::Null, MissingValuePosition::Last) => 1,
        (SortValue::Missing, MissingValuePosition::Last) => 2,
    }
}

/// Compare two entries of one sort column.
///
/// Missing/null placement never reverses under `Desc`; only scalar value order
/// reverses.
#[must_use]
pub fn sort_value_cmp(
    a: &SortValue,
    b: &SortValue,
    direction: SortDirection,
    position: MissingValuePosition,
) -> Ordering {
    let a_rank = rank_of(a, position);
    let b_rank = rank_of(b, position);
    if a_rank != b_rank {
        return a_rank.cmp(&b_rank);
    }
    match (a, b) {
        (SortValue::Value(a), SortValue::Value(b)) => {
            let ordering = canonical_scalar_cmp(a, b);
            match direction {
                SortDirection::Asc => ordering,
                SortDirection::Desc => ordering.reverse(),
            }
        }
        _ => Ordering::Equal,
    }
}

/// Select one scalar from a multi-valued field using the declared selector.
///
/// The selector is applied **before** sort direction. An empty multi-value
/// sorts as missing.
#[must_use]
pub fn select_sort_value(values: &FieldValues, selector: Option<MultiValueSelector>) -> SortValue {
    match values {
        FieldValues::Absent | FieldValues::Empty => SortValue::Missing,
        FieldValues::ExplicitNull => SortValue::Null,
        FieldValues::Single(value) => SortValue::Value(value.clone()),
        FieldValues::Multi(list) => {
            if list.is_empty() {
                return SortValue::Missing;
            }
            let mut best = list[0].clone();
            for candidate in &list[1..] {
                let ordering = canonical_scalar_cmp(candidate, &best);
                let replace = match selector.unwrap_or(MultiValueSelector::Min) {
                    MultiValueSelector::Min => ordering == Ordering::Less,
                    MultiValueSelector::Max => ordering == Ordering::Greater,
                };
                if replace {
                    best = candidate.clone();
                }
            }
            SortValue::Value(best)
        }
    }
}

/// A reusable per-segment typed-column accessor.
///
/// Opening a `ColumnReader` re-parses the column geometry, so typed scan calls
/// that read many values open this once per segment and reuse it. It is a
/// read-only view over already-validated column bytes.
pub(crate) struct ColumnAccess<'a> {
    columns: Option<ColumnReader<'a>>,
}

impl<'a> ColumnAccess<'a> {
    pub(crate) fn open(reader: &'a SegmentReader) -> Result<Self, SegmentError> {
        Ok(Self {
            columns: reader.open_columns()?,
        })
    }

    pub(crate) fn value(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> Result<Option<FieldValues>, SegmentError> {
        match &self.columns {
            Some(columns) => columns.value(field_id, doc_id),
            None => Ok(None),
        }
    }
}

/// Build the sort tuple for one physical document.
pub fn sort_tuple_for_doc(
    columns: &ColumnAccess<'_>,
    schema: &CodecSchema,
    sort: &Sort,
    doc_id: u64,
) -> Result<Vec<SortValue>, SegmentError> {
    let mut tuple = Vec::with_capacity(sort.fields.len());
    for field in &sort.fields {
        tuple.push(sort_value_for_field(columns, schema, field, doc_id)?);
    }
    Ok(tuple)
}

fn sort_value_for_field(
    columns: &ColumnAccess<'_>,
    schema: &CodecSchema,
    field: &SortField,
    doc_id: u64,
) -> Result<SortValue, SegmentError> {
    let Some(field_id) = schema.field_id(&field.field) else {
        return Ok(SortValue::Missing);
    };
    let Some(values) = columns.value(field_id, doc_id)? else {
        return Ok(SortValue::Missing);
    };
    let cardinality = schema
        .field(field_id)
        .map(|definition: &CodecField| definition.cardinality);
    if cardinality == Some(crate::contract::document::Cardinality::Multi) && field.multi.is_none() {
        return Ok(select_sort_value(&values, None));
    }
    Ok(select_sort_value(&values, field.multi))
}

/// Compare two complete candidates: sort tuple first, then logical key
/// ascending.
#[must_use]
pub fn compare_candidates(
    a_values: &[SortValue],
    a_key: &DocumentKey,
    b_values: &[SortValue],
    b_key: &DocumentKey,
    sort: &Sort,
) -> Ordering {
    for (index, field) in sort.fields.iter().enumerate() {
        let a = a_values.get(index).unwrap_or(&SortValue::Missing);
        let b = b_values.get(index).unwrap_or(&SortValue::Missing);
        let ordering = sort_value_cmp(a, b, field.direction, field.missing);
        if ordering != Ordering::Equal {
            return ordering;
        }
    }
    a_key.as_str().as_bytes().cmp(b_key.as_str().as_bytes())
}

/// Whether any member of `values` satisfies a typed range.
#[must_use]
pub fn matches_range(
    values: &FieldValues,
    lower: &Bound<FieldValue>,
    upper: &Bound<FieldValue>,
) -> bool {
    values
        .values()
        .any(|value| satisfies_lower(value, lower) && satisfies_upper(value, upper))
}

fn satisfies_lower(value: &FieldValue, lower: &Bound<FieldValue>) -> bool {
    match lower {
        Bound::Unbounded => true,
        Bound::Included(bound) => canonical_scalar_cmp(value, bound) != Ordering::Less,
        Bound::Excluded(bound) => canonical_scalar_cmp(value, bound) == Ordering::Greater,
    }
}

fn satisfies_upper(value: &FieldValue, upper: &Bound<FieldValue>) -> bool {
    match upper {
        Bound::Unbounded => true,
        Bound::Included(bound) => canonical_scalar_cmp(value, bound) != Ordering::Greater,
        Bound::Excluded(bound) => canonical_scalar_cmp(value, bound) == Ordering::Less,
    }
}

/// Whether any member of `values` falls in the half-open window `[start, end)`.
#[must_use]
pub fn matches_time_range(values: &FieldValues, start: i64, end: i64) -> bool {
    if start >= end {
        return false;
    }
    values.values().any(|value| match value {
        FieldValue::Timestamp(timestamp) => {
            let micros = timestamp.as_micros();
            micros >= start && micros < end
        }
        _ => false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::value::Timestamp;

    fn kw(value: &str) -> FieldValue {
        FieldValue::Keyword(value.to_owned())
    }

    #[test]
    fn canonical_order_is_type_native() {
        assert_eq!(
            canonical_scalar_cmp(&FieldValue::Bool(false), &FieldValue::Bool(true)),
            Ordering::Less
        );
        assert_eq!(
            canonical_scalar_cmp(&FieldValue::I64(-1), &FieldValue::I64(1)),
            Ordering::Less
        );
        assert_eq!(
            canonical_scalar_cmp(&FieldValue::U64(1), &FieldValue::U64(u64::MAX)),
            Ordering::Less
        );
        assert_eq!(
            canonical_scalar_cmp(&FieldValue::F64(1.5), &FieldValue::F64(2.5)),
            Ordering::Less
        );
        assert_eq!(
            canonical_scalar_cmp(
                &FieldValue::Timestamp(Timestamp::from_micros(-5)),
                &FieldValue::Timestamp(Timestamp::from_micros(5))
            ),
            Ordering::Less
        );
        // Keyword compares unsigned UTF-8 bytes.
        assert_eq!(canonical_scalar_cmp(&kw("a"), &kw("b")), Ordering::Less);
        assert_eq!(canonical_scalar_cmp(&kw("é"), &kw("z")), Ordering::Greater);
        // IPv4 sorts before IPv6.
        let v4 = FieldValue::Ip("255.255.255.255".parse().unwrap());
        let v6 = FieldValue::Ip("::".parse().unwrap());
        assert_eq!(canonical_scalar_cmp(&v4, &v6), Ordering::Less);
    }

    #[test]
    fn sort_values_distinguish_missing_null_and_value() {
        assert_eq!(
            select_sort_value(&FieldValues::Absent, None),
            SortValue::Missing
        );
        assert_eq!(
            select_sort_value(&FieldValues::Empty, None),
            SortValue::Missing
        );
    }

    #[test]
    fn select_sort_value_handles_null_and_multi() {
        assert_eq!(
            select_sort_value(&FieldValues::ExplicitNull, None),
            SortValue::Null
        );
        assert_eq!(
            select_sort_value(&FieldValues::Empty, None),
            SortValue::Missing
        );
        let multi = FieldValues::Multi(vec![
            FieldValue::I64(5),
            FieldValue::I64(1),
            FieldValue::I64(3),
        ]);
        assert_eq!(
            select_sort_value(&multi, Some(MultiValueSelector::Min)),
            SortValue::Value(FieldValue::I64(1))
        );
        assert_eq!(
            select_sort_value(&multi, Some(MultiValueSelector::Max)),
            SortValue::Value(FieldValue::I64(5))
        );
        assert_eq!(
            select_sort_value(&FieldValues::Single(FieldValue::Bool(true)), None),
            SortValue::Value(FieldValue::Bool(true))
        );
    }

    #[test]
    fn category_placement_does_not_reverse_and_values_do() {
        let missing = SortValue::Missing;
        let null = SortValue::Null;
        let one = SortValue::Value(FieldValue::I64(1));
        let two = SortValue::Value(FieldValue::I64(2));
        // First: Missing < Null < Value regardless of direction.
        assert_eq!(
            sort_value_cmp(
                &missing,
                &one,
                SortDirection::Desc,
                MissingValuePosition::First
            ),
            Ordering::Less
        );
        assert_eq!(
            sort_value_cmp(
                &null,
                &one,
                SortDirection::Desc,
                MissingValuePosition::First
            ),
            Ordering::Less
        );
        // Last: Value < Null < Missing regardless of direction.
        assert_eq!(
            sort_value_cmp(
                &one,
                &missing,
                SortDirection::Asc,
                MissingValuePosition::Last
            ),
            Ordering::Less
        );
        // Values reverse under Desc.
        assert_eq!(
            sort_value_cmp(&one, &two, SortDirection::Asc, MissingValuePosition::First),
            Ordering::Less
        );
        assert_eq!(
            sort_value_cmp(&one, &two, SortDirection::Desc, MissingValuePosition::First),
            Ordering::Greater
        );
    }

    #[test]
    fn range_bounds_are_inclusive_exclusive() {
        let values = FieldValues::Single(FieldValue::I64(5));
        assert!(matches_range(
            &values,
            &Bound::Included(FieldValue::I64(5)),
            &Bound::Included(FieldValue::I64(5))
        ));
        assert!(!matches_range(
            &values,
            &Bound::Excluded(FieldValue::I64(5)),
            &Bound::Included(FieldValue::I64(6))
        ));
        assert!(!matches_range(
            &values,
            &Bound::Included(FieldValue::I64(6)),
            &Bound::Unbounded
        ));
        // Absent/null/empty never match a positive range.
        assert!(!matches_range(
            &FieldValues::Absent,
            &Bound::Unbounded,
            &Bound::Unbounded
        ));
        assert!(!matches_range(
            &FieldValues::ExplicitNull,
            &Bound::Unbounded,
            &Bound::Unbounded
        ));
        assert!(!matches_range(
            &FieldValues::Empty,
            &Bound::Unbounded,
            &Bound::Unbounded
        ));
    }

    #[test]
    fn time_range_is_half_open_and_any_member() {
        let values = FieldValues::Multi(vec![
            FieldValue::Timestamp(Timestamp::from_micros(9)),
            FieldValue::Timestamp(Timestamp::from_micros(10)),
        ]);
        assert!(matches_time_range(&values, 10, 11));
        assert!(!matches_time_range(&values, 10, 10));
        assert!(!matches_time_range(&values, 11, 12));
        assert!(matches_time_range(&values, 9, 10));
        // Pre-epoch works with signed micros.
        let pre = FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(-5)));
        assert!(matches_time_range(&pre, -10, 0));
    }

    #[test]
    fn canonical_bytes_round_trip_and_reject_non_finite() {
        assert_eq!(
            canonical_scalar_bytes(&FieldValue::I64(-1)).unwrap(),
            canonical_scalar_bytes(&FieldValue::I64(-1)).unwrap()
        );
        assert!(canonical_scalar_bytes(&FieldValue::F64(f64::NAN)).is_err());
    }
}
