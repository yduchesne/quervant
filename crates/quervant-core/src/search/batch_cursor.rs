//! Private bridge between the public `Cursor` contract and the canonical
//! snapshot-bound `UnifiedCursor`.
//!
//! The conversion is exhaustive over supported typed sort scalars and preserves
//! IEEE-754 bit patterns. No comparator, query fingerprint or ranking logic is
//! reimplemented here.

use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::query::{JsonPathExpr, JsonPathSegment};
use crate::contract::result::{Cursor, CursorAtom, CursorContinuationV1, PitId, Sort};
use crate::contract::value::{FieldValue, Timestamp};

use super::error::{SearchError, SearchResult};
use super::typed_compare::SortValue;
use super::unified_cursor::UnifiedCursor;

/// Convert an internal cursor into the public contract cursor.
pub(crate) fn to_public(
    unified: &UnifiedCursor,
    pit: &PitId,
    sort: &Sort,
    expiry: Timestamp,
) -> SearchResult<Cursor> {
    let tuple = unified
        .last_sort_values()
        .iter()
        .map(atom_from_sort_value)
        .collect::<SearchResult<Vec<_>>>()?;
    let relevance_bits = match unified.last_score() {
        Some(score) if score.is_finite() => Some(score.to_bits()),
        Some(_) => return Err(cursor_sort_error()),
        None => None,
    };
    Ok(Cursor::from_continuation_v1(
        pit.clone(),
        sort.clone(),
        unified.last_key().clone(),
        expiry,
        CursorContinuationV1 {
            snapshot_binding: unified.snapshot_binding(),
            fingerprint: unified.fingerprint,
            tuple,
            relevance_bits,
        },
    ))
}

/// Reconstruct the exact internal cursor for unified validation.
///
/// A legacy position-only cursor has no complete tuple and is therefore not
/// resumable; it fails with `CursorSortMismatch` rather than pretending that
/// `last_key` alone determines order.
pub(crate) fn to_unified(public: &Cursor) -> SearchResult<UnifiedCursor> {
    let continuation = public.continuation_v1().ok_or_else(cursor_sort_error)?;
    let tuple = continuation
        .tuple
        .iter()
        .map(sort_value_from_atom)
        .collect::<SearchResult<Vec<_>>>()?;
    let score = match continuation.relevance_bits {
        Some(bits) => {
            let score = f64::from_bits(bits);
            if !score.is_finite() {
                return Err(cursor_sort_error());
            }
            Some(score)
        }
        None => None,
    };
    Ok(UnifiedCursor::new(
        continuation.snapshot_binding,
        continuation.fingerprint,
        tuple,
        score,
        public.last_key().clone(),
    ))
}

/// Deterministic logical retained size of a public cursor.
///
/// This is the single accounting formula used for both response bytes and
/// retained memory. It covers the PIT id, sort definition (including optional
/// JSON path overhead), key, expiry, V1 header and every atom's owned bytes.
pub(crate) fn cursor_logical_bytes(cursor: &Cursor) -> Option<u64> {
    let mut bytes = 8u64; // V1 header/version.
    bytes = bytes.checked_add(8 + cursor.pit().as_str().len() as u64)?;
    bytes = bytes.checked_add(sort_logical_bytes(cursor.sort())?)?;
    bytes = bytes.checked_add(8 + cursor.last_key().as_str().len() as u64)?;
    bytes = bytes.checked_add(8)?; // expiry
    bytes = bytes.checked_add(9)?; // relevance presence + bits
    let continuation = cursor.continuation_v1()?;
    bytes = bytes.checked_add(8)?; // atom count
    for atom in &continuation.tuple {
        bytes = bytes.checked_add(atom_logical_bytes(atom)?)?;
    }
    Some(bytes)
}

// Logical admission accounting for a JSON sort path. These structural
// allowances model retained cursor payload for budgeting; they are not a claim
// about native `Vec` capacity or allocator/RSS behavior.
const JSON_PATH_BASE: u64 = 24;
const JSON_SEGMENT_BASE: u64 = 24;

fn checked_path_components(segment_count: u64, member_bytes: u64) -> Option<u64> {
    JSON_PATH_BASE
        .checked_add(segment_count.checked_mul(JSON_SEGMENT_BASE)?)?
        .checked_add(member_bytes)
}

fn json_path_logical_bytes(path: &JsonPathExpr) -> Option<u64> {
    let mut member_bytes = 0u64;
    for segment in path.segments() {
        if let JsonPathSegment::Member(member) = segment {
            member_bytes = member_bytes.checked_add(u64::try_from(member.len()).ok()?)?;
        }
    }
    checked_path_components(u64::try_from(path.segments().len()).ok()?, member_bytes)
}

fn sort_logical_bytes(sort: &Sort) -> Option<u64> {
    let mut bytes = 8u64 + 8; // field count + fixed sort header
    for field in &sort.fields {
        bytes = bytes.checked_add(8 + field.field.len() as u64)?;
        bytes = bytes.checked_add(3)?; // direction + missing + multi presence
        if field.multi.is_some() {
            bytes = bytes.checked_add(1)?;
        }
        if field.distance_from.is_some() {
            bytes = bytes.checked_add(16)?;
        }
        if let Some(path) = &field.json_path {
            bytes = bytes.checked_add(json_path_logical_bytes(path)?)?;
        }
    }
    Some(bytes)
}

fn atom_logical_bytes(atom: &CursorAtom) -> Option<u64> {
    match atom {
        CursorAtom::Missing | CursorAtom::Null => Some(1),
        CursorAtom::Bool(_) => Some(2),
        CursorAtom::I64(_)
        | CursorAtom::U64(_)
        | CursorAtom::F64Bits(_)
        | CursorAtom::TimestampMicros(_) => Some(9),
        CursorAtom::Keyword(value) => (8u64).checked_add(value.len() as u64),
        CursorAtom::Ip(_) => Some(1 + 16),
    }
}

fn atom_from_sort_value(value: &SortValue) -> SearchResult<CursorAtom> {
    match value {
        SortValue::Missing => Ok(CursorAtom::Missing),
        SortValue::Null => Ok(CursorAtom::Null),
        SortValue::Value(value) => match value {
            FieldValue::Bool(value) => Ok(CursorAtom::Bool(*value)),
            FieldValue::I64(value) => Ok(CursorAtom::I64(*value)),
            FieldValue::U64(value) => Ok(CursorAtom::U64(*value)),
            FieldValue::F64(value) if value.is_finite() => Ok(CursorAtom::F64Bits(value.to_bits())),
            FieldValue::F64(_) => Err(cursor_sort_error()),
            FieldValue::Timestamp(value) => Ok(CursorAtom::TimestampMicros(value.as_micros())),
            FieldValue::Keyword(value) => Ok(CursorAtom::Keyword(value.clone())),
            FieldValue::Ip(value) => Ok(CursorAtom::Ip(*value)),
            FieldValue::Text(_)
            | FieldValue::Json(_)
            | FieldValue::GeoPoint(_)
            | FieldValue::Cidr(_) => Err(cursor_sort_error()),
        },
    }
}

fn sort_value_from_atom(atom: &CursorAtom) -> SearchResult<SortValue> {
    match atom {
        CursorAtom::Missing => Ok(SortValue::Missing),
        CursorAtom::Null => Ok(SortValue::Null),
        CursorAtom::Bool(value) => Ok(SortValue::Value(FieldValue::Bool(*value))),
        CursorAtom::I64(value) => Ok(SortValue::Value(FieldValue::I64(*value))),
        CursorAtom::U64(value) => Ok(SortValue::Value(FieldValue::U64(*value))),
        CursorAtom::F64Bits(bits) => {
            let value = f64::from_bits(*bits);
            if !value.is_finite() {
                return Err(cursor_sort_error());
            }
            Ok(SortValue::Value(FieldValue::F64(value)))
        }
        CursorAtom::TimestampMicros(value) => Ok(SortValue::Value(FieldValue::Timestamp(
            Timestamp::from_micros(*value),
        ))),
        CursorAtom::Keyword(value) => Ok(SortValue::Value(FieldValue::Keyword(value.clone()))),
        CursorAtom::Ip(value) => Ok(SortValue::Value(FieldValue::Ip(*value))),
    }
}

fn cursor_sort_error() -> SearchError {
    SearchError::Query(QueryError::InvalidQuery(
        InvalidQueryReason::CursorSortMismatch,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::DocumentKey;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn pit() -> PitId {
        PitId::new("pit-A").unwrap()
    }

    fn sort() -> Sort {
        Sort::new(vec![
            crate::contract::result::SortField::new(
                "n",
                crate::contract::result::SortDirection::Asc,
            ),
            crate::contract::result::SortField::new(
                "tag",
                crate::contract::result::SortDirection::Desc,
            ),
        ])
    }

    fn cursor(tuple: Vec<SortValue>, score: Option<f64>) -> UnifiedCursor {
        UnifiedCursor::new(7, [9u8; 32], tuple, score, key("k08"))
    }

    #[test]
    fn b01_roundtrip_preserves_every_supported_scalar_and_score_bits() {
        let tuple = vec![
            SortValue::Missing,
            SortValue::Null,
            SortValue::Value(FieldValue::Bool(true)),
            SortValue::Value(FieldValue::I64(-7)),
            SortValue::Value(FieldValue::U64(u64::MAX)),
            SortValue::Value(FieldValue::F64(-0.0)),
            SortValue::Value(FieldValue::Timestamp(Timestamp::from_micros(-11))),
            SortValue::Value(FieldValue::Keyword("tied".into())),
            SortValue::Value(FieldValue::Ip("2001:db8::1".parse().unwrap())),
        ];
        let public = to_public(
            &cursor(tuple.clone(), Some(1.25)),
            &pit(),
            &sort(),
            Timestamp::from_micros(50),
        )
        .unwrap();
        let internal = to_unified(&public).unwrap();
        assert_eq!(internal.last_sort_values(), tuple.as_slice());
        assert_eq!(internal.last_score().unwrap().to_bits(), 1.25f64.to_bits());
        assert_eq!(internal.snapshot_binding(), 7);
        assert_eq!(internal.fingerprint, [9u8; 32]);
        let roundtrip = to_public(&internal, &pit(), &sort(), Timestamp::from_micros(50)).unwrap();
        assert_eq!(roundtrip, public);
    }

    #[test]
    fn b02_negative_zero_bits_are_not_collapsed() {
        let negative = cursor(vec![SortValue::Value(FieldValue::F64(-0.0))], None);
        let positive = cursor(vec![SortValue::Value(FieldValue::F64(0.0))], None);
        let a = to_public(&negative, &pit(), &sort(), Timestamp::from_micros(9)).unwrap();
        let b = to_public(&positive, &pit(), &sort(), Timestamp::from_micros(9)).unwrap();
        assert_ne!(a, b);
        assert_eq!(
            to_unified(&a).unwrap().last_sort_values()[0],
            SortValue::Value(FieldValue::F64(-0.0))
        );
    }

    #[test]
    fn b03_legacy_cursor_and_unsupported_values_fail_typed() {
        let legacy = Cursor::new(pit(), sort(), key("k"), Timestamp::from_micros(10));
        assert!(matches!(
            to_unified(&legacy),
            Err(SearchError::Query(QueryError::InvalidQuery(
                InvalidQueryReason::CursorSortMismatch
            )))
        ));
        let unsupported = cursor(
            vec![SortValue::Value(FieldValue::GeoPoint(
                crate::contract::value::GeoPoint::new(1.0, 2.0).unwrap(),
            ))],
            None,
        );
        assert!(to_public(&unsupported, &pit(), &sort(), Timestamp::from_micros(9)).is_err());
        let nonfinite = cursor(vec![SortValue::Value(FieldValue::F64(f64::NAN))], None);
        assert!(to_public(&nonfinite, &pit(), &sort(), Timestamp::from_micros(9)).is_err());
    }

    #[test]
    fn b04_logical_size_includes_keyword_bytes_and_is_checked() {
        let public = to_public(
            &cursor(
                vec![SortValue::Value(FieldValue::Keyword(
                    "a-long-keyword".into(),
                ))],
                Some(0.5),
            ),
            &pit(),
            &sort(),
            Timestamp::from_micros(9),
        )
        .unwrap();
        let small = cursor_logical_bytes(&public).unwrap();
        let larger = cursor_logical_bytes(
            &to_public(
                &cursor(
                    vec![SortValue::Value(FieldValue::Keyword(
                        "a-much-longer-keyword".into(),
                    ))],
                    Some(0.5),
                ),
                &pit(),
                &sort(),
                Timestamp::from_micros(9),
            )
            .unwrap(),
        )
        .unwrap();
        assert!(larger > small);
    }
}

#[cfg(test)]
mod accounting_tests {
    use super::*;
    use crate::contract::document::DocumentKey;
    use crate::contract::result::{SortDirection, SortField};
    use crate::contract::value::FieldValue;

    fn path(input: &str) -> JsonPathExpr {
        JsonPathExpr::parse(input).unwrap()
    }

    fn sort_with_path(path: JsonPathExpr) -> Sort {
        Sort::new(vec![
            SortField::new("body", SortDirection::Asc).with_json_path(path),
        ])
    }

    fn public_cursor(sort: Sort) -> Cursor {
        let internal = UnifiedCursor::new(
            3,
            [1u8; 32],
            vec![SortValue::Value(FieldValue::I64(7))],
            None,
            DocumentKey::new("k").unwrap(),
        );
        to_public(
            &internal,
            &PitId::new("pit-accounting").unwrap(),
            &sort,
            Timestamp::from_micros(100),
        )
        .unwrap()
    }

    #[test]
    fn t01_path_root_charges_base() {
        assert_eq!(json_path_logical_bytes(&path("$")), Some(24));
        assert_eq!(json_path_logical_bytes(&path("$.x")), Some(49));
    }

    #[test]
    fn t02_path_long_member_is_not_fixed_64() {
        let small = format!("$[\"{}\"]", "a".repeat(256));
        let large = format!("$[\"{}\"]", "a".repeat(1024));
        assert_eq!(json_path_logical_bytes(&path(&small)), Some(304));
        assert_eq!(json_path_logical_bytes(&path(&large)), Some(1072));
        let small_charge =
            cursor_logical_bytes(&public_cursor(sort_with_path(path(&small)))).unwrap();
        let large_charge =
            cursor_logical_bytes(&public_cursor(sort_with_path(path(&large)))).unwrap();
        assert_eq!(large_charge - small_charge, 768);
    }

    #[test]
    fn t03_path_unicode_bytes() {
        assert_eq!(json_path_logical_bytes(&path("$[\"é\"]")), Some(50));
        assert_eq!(json_path_logical_bytes(&path("$[\"a\"]")), Some(49));
    }

    #[test]
    fn t04_path_segments_all_metered() {
        assert_eq!(json_path_logical_bytes(&path("$.a[1][*].b")), Some(122));
        assert_eq!(json_path_logical_bytes(&path("$.a[1].b")), Some(98));
        assert_eq!(json_path_logical_bytes(&path("$.a[*]")), Some(73));
    }

    #[test]
    fn t05_path_checked_arithmetic() {
        assert_eq!(checked_path_components(u64::MAX, 0), None);
        assert_eq!(checked_path_components(0, u64::MAX), None);
        assert_eq!(checked_path_components(2, 3), Some(24 + 48 + 3));
    }

    #[test]
    fn t06_sort_and_cursor_charge_grows_with_path() {
        let short = format!("$[\"{}\"]", "a".repeat(16));
        let long = format!("$[\"{}\"]", "a".repeat(256));
        let short_charge =
            cursor_logical_bytes(&public_cursor(sort_with_path(path(&short)))).unwrap();
        let long_charge =
            cursor_logical_bytes(&public_cursor(sort_with_path(path(&long)))).unwrap();
        assert_eq!(long_charge - short_charge, 240);

        let multi_sort = Sort::new(vec![
            SortField::new("n", SortDirection::Asc),
            SortField::new("body", SortDirection::Asc).with_json_path(path(&long)),
        ]);
        let multi_charge = cursor_logical_bytes(&public_cursor(multi_sort.clone())).unwrap();
        let multi_short = Sort::new(vec![
            SortField::new("n", SortDirection::Asc),
            SortField::new("body", SortDirection::Asc).with_json_path(path(&short)),
        ]);
        let multi_short_charge = cursor_logical_bytes(&public_cursor(multi_short)).unwrap();
        assert_eq!(multi_charge - multi_short_charge, 240);
        assert!(multi_charge > long_charge);
    }
}
