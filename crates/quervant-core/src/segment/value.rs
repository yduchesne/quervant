//! Typed value, field-state and JSON encoding (F06/F07).
//!
//! The five logical field states shared by stored source and columns are:
//! `ABSENT`, `EXPLICIT_NULL`, `EMPTY_MULTI`, `SINGLE`, `MULTI`.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use crate::contract::document::FieldValues;
use crate::contract::value::{FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue};

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;

/// Logical state: field is not present.
pub const STATE_ABSENT: u8 = 0x00;
/// Logical state: field is present with explicit null.
pub const STATE_EXPLICIT_NULL: u8 = 0x01;
/// Logical state: field is a zero-element multi-value.
pub const STATE_EMPTY_MULTI: u8 = 0x02;
/// Logical state: exactly one value.
pub const STATE_SINGLE: u8 = 0x03;
/// Logical state: one or more values.
pub const STATE_MULTI: u8 = 0x04;

/// Classify a contract `FieldValues` into its logical state tag.
#[must_use]
pub const fn state_of(values: &FieldValues) -> u8 {
    match values {
        FieldValues::Absent => STATE_ABSENT,
        FieldValues::ExplicitNull => STATE_EXPLICIT_NULL,
        FieldValues::Empty => STATE_EMPTY_MULTI,
        FieldValues::Single(_) => STATE_SINGLE,
        FieldValues::Multi(_) => STATE_MULTI,
    }
}

/// Encode a field state plus any values.
pub fn encode_field_values(
    writer: &mut ByteWriter,
    field_type: FieldType,
    values: &FieldValues,
    limits: &SegmentLimits,
) -> SegmentResult<()> {
    writer.u8(state_of(values));
    match values {
        FieldValues::Absent | FieldValues::ExplicitNull | FieldValues::Empty => Ok(()),
        FieldValues::Single(value) => encode_scalar(writer, field_type, value),
        FieldValues::Multi(values) => {
            let count = u64::try_from(values.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_array_elements(),
                requested: values.len() as u64,
            })?;
            if count > limits.max_array_elements() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_array_elements(),
                    requested: count,
                });
            }
            writer.varint(count);
            for value in values {
                encode_scalar(writer, field_type, value)?;
            }
            Ok(())
        }
    }
}

/// Decode a field state plus any values.
pub fn decode_field_values(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
) -> SegmentResult<FieldValues> {
    let mut budget = DecodeBudget::new(limits);
    decode_field_values_budgeted(reader, field_type, limits, &mut budget)
}

/// Decode a field state plus any values using a shared budget.
pub(crate) fn decode_field_values_budgeted(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<FieldValues> {
    let state = reader.u8("field state")?;
    match state {
        STATE_ABSENT => Ok(FieldValues::Absent),
        STATE_EXPLICIT_NULL => Ok(FieldValues::ExplicitNull),
        STATE_EMPTY_MULTI => Ok(FieldValues::Empty),
        STATE_SINGLE => Ok(FieldValues::Single(decode_scalar_budgeted(
            reader, field_type, limits, budget,
        )?)),
        STATE_MULTI => {
            let count = reader.varint("multi count")?;
            if count == 0 {
                return Err(SegmentError::Corrupt {
                    context: "multi count",
                    detail: "zero count; use EMPTY_MULTI".to_owned(),
                });
            }
            if count > limits.max_array_elements() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_array_elements(),
                    requested: count,
                });
            }
            limits.check_entries(count)?;
            budget.reserve_vec::<FieldValue>(count)?;
            let mut values = Vec::with_capacity(count as usize);
            for _ in 0..count {
                values.push(decode_scalar_budgeted(reader, field_type, limits, budget)?);
            }
            Ok(FieldValues::Multi(values))
        }
        value => Err(SegmentError::InvalidFieldState { value }),
    }
}

/// Encode one scalar typed value.
pub fn encode_scalar(
    writer: &mut ByteWriter,
    field_type: FieldType,
    value: &FieldValue,
) -> SegmentResult<()> {
    if value.field_type() != field_type {
        return Err(SegmentError::FieldTypeMismatch {
            field: "value".to_owned(),
        });
    }
    match value {
        FieldValue::Text(text) => {
            writer.varint(text.len() as u64);
            writer.bytes(text.as_bytes());
        }
        FieldValue::Keyword(keyword) => {
            writer.len_prefixed_u16(keyword.as_bytes())?;
        }
        FieldValue::Bool(flag) => writer.u8(u8::from(*flag)),
        FieldValue::I64(number) => writer.i64(*number),
        FieldValue::U64(number) => writer.u64(*number),
        FieldValue::F64(number) => {
            if !number.is_finite() {
                return Err(SegmentError::NonFiniteFloat { context: "f64" });
            }
            writer.f64(*number);
        }
        FieldValue::Timestamp(timestamp) => writer.i64(timestamp.as_micros()),
        FieldValue::GeoPoint(point) => {
            writer.f64(point.lon());
            writer.f64(point.lat());
        }
        FieldValue::Ip(addr) => encode_ip(writer, *addr),
        FieldValue::Cidr(network) => {
            encode_ip(writer, network.addr());
            writer.u8(network.prefix());
        }
        FieldValue::Json(json) => encode_json(writer, json)?,
    }
    Ok(())
}

/// Decode one scalar typed value.
pub fn decode_scalar(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
) -> SegmentResult<FieldValue> {
    let mut budget = DecodeBudget::new(limits);
    decode_scalar_budgeted(reader, field_type, limits, &mut budget)
}

/// Decode one scalar typed value using a shared budget.
fn decode_scalar_budgeted(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<FieldValue> {
    Ok(match field_type {
        FieldType::Text => {
            let len = reader.varint("text length")?;
            check_len(len, limits)?;
            let bytes = reader.bytes(len as usize, "text bytes")?;
            let text = std::str::from_utf8(bytes)
                .map_err(|_| SegmentError::InvalidUtf8 { context: "text" })?;
            budget.reserve_string(text.len() as u64)?;
            FieldValue::Text(text.to_owned())
        }
        FieldType::Keyword => {
            let bytes = reader.len_prefixed_u16("keyword")?;
            let keyword = std::str::from_utf8(bytes)
                .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
            budget.reserve_string(keyword.len() as u64)?;
            FieldValue::Keyword(keyword.to_owned())
        }
        FieldType::Bool => match reader.u8("bool")? {
            0 => FieldValue::Bool(false),
            1 => FieldValue::Bool(true),
            value => {
                return Err(SegmentError::Corrupt {
                    context: "bool",
                    detail: format!("invalid {value}"),
                });
            }
        },
        FieldType::I64 => FieldValue::I64(reader.i64("i64")?),
        FieldType::U64 => FieldValue::U64(reader.u64("u64")?),
        FieldType::F64 => FieldValue::F64(reader.f64("f64")?),
        FieldType::Timestamp => FieldValue::Timestamp(
            crate::contract::value::Timestamp::from_micros(reader.i64("timestamp")?),
        ),
        FieldType::GeoPoint => {
            let lon = reader.f64("geo lon")?;
            let lat = reader.f64("geo lat")?;
            FieldValue::GeoPoint(
                GeoPoint::new(lon, lat).map_err(|_| SegmentError::InvalidGeo {
                    detail: "coordinate out of range or non-finite",
                })?,
            )
        }
        FieldType::IpAddress => FieldValue::Ip(decode_ip(reader)?),
        FieldType::IpNetwork => {
            let addr = decode_ip(reader)?;
            let prefix = reader.u8("cidr prefix")?;
            FieldValue::Cidr(
                IpNetwork::new(addr, prefix).map_err(|_| SegmentError::InvalidIp {
                    detail: "invalid cidr network",
                })?,
            )
        }
        FieldType::Json => FieldValue::Json(decode_json_budgeted(reader, limits, 0, budget)?),
    })
}

/// Encode an IP address with an explicit family tag.
pub fn encode_ip(writer: &mut ByteWriter, addr: IpAddr) {
    match addr {
        IpAddr::V4(v4) => {
            writer.u8(0);
            writer.bytes(&v4.octets());
        }
        IpAddr::V6(v6) => {
            writer.u8(1);
            writer.bytes(&v6.octets());
        }
    }
}

/// Decode an IP address with an explicit family tag.
pub fn decode_ip(reader: &mut ByteReader<'_>) -> SegmentResult<IpAddr> {
    match reader.u8("ip family")? {
        0 => {
            let octets = reader.bytes(4, "ipv4 octets")?;
            let mut array = [0u8; 4];
            array.copy_from_slice(octets);
            Ok(IpAddr::V4(Ipv4Addr::from(array)))
        }
        1 => {
            let octets = reader.bytes(16, "ipv6 octets")?;
            let mut array = [0u8; 16];
            array.copy_from_slice(octets);
            Ok(IpAddr::V6(Ipv6Addr::from(array)))
        }
        _ => Err(SegmentError::InvalidIp {
            detail: "invalid ip family tag",
        }),
    }
}

/// Encode a JSON value recursively.
pub fn encode_json(writer: &mut ByteWriter, value: &JsonValue) -> SegmentResult<()> {
    match value {
        JsonValue::Null => writer.u8(0),
        JsonValue::Bool(flag) => {
            writer.u8(1);
            writer.u8(u8::from(*flag));
        }
        JsonValue::Number(JsonNumber::I64(number)) => {
            writer.u8(2);
            writer.i64(*number);
        }
        JsonValue::Number(JsonNumber::U64(number)) => {
            writer.u8(3);
            writer.u64(*number);
        }
        JsonValue::Number(JsonNumber::F64(number)) => {
            if !number.is_finite() {
                return Err(SegmentError::NonFiniteFloat {
                    context: "json number",
                });
            }
            writer.u8(4);
            writer.f64(*number);
        }
        JsonValue::String(text) => {
            writer.u8(5);
            writer.varint(text.len() as u64);
            writer.bytes(text.as_bytes());
        }
        JsonValue::Array(values) => {
            writer.u8(6);
            writer.varint(values.len() as u64);
            for value in values {
                encode_json(writer, value)?;
            }
        }
        JsonValue::Object(entries) => {
            writer.u8(7);
            writer.varint(entries.len() as u64);
            for (key, value) in entries {
                writer.varint(key.len() as u64);
                writer.bytes(key.as_bytes());
                encode_json(writer, value)?;
            }
        }
    }
    Ok(())
}

/// Decode a JSON value with depth and element bounds.
pub fn decode_json(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
    depth: u64,
) -> SegmentResult<JsonValue> {
    let mut budget = DecodeBudget::new(limits);
    decode_json_budgeted(reader, limits, depth, &mut budget)
}

/// Decode a JSON value using a shared budget.
fn decode_json_budgeted(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
    depth: u64,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<JsonValue> {
    if depth > limits.max_json_depth() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_json_depth(),
            requested: depth,
        });
    }
    let tag = reader.u8("json tag")?;
    Ok(match tag {
        0 => JsonValue::Null,
        1 => match reader.u8("json bool")? {
            0 => JsonValue::Bool(false),
            1 => JsonValue::Bool(true),
            value => {
                return Err(SegmentError::Corrupt {
                    context: "json bool",
                    detail: format!("invalid {value}"),
                });
            }
        },
        2 => JsonValue::Number(JsonNumber::I64(reader.i64("json i64")?)),
        3 => JsonValue::Number(JsonNumber::U64(reader.u64("json u64")?)),
        4 => JsonValue::Number(JsonNumber::F64(reader.f64("json f64")?)),
        5 => {
            let len = reader.varint("json string length")?;
            check_len(len, limits)?;
            let bytes = reader.bytes(len as usize, "json string")?;
            let text = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "json string",
            })?;
            budget.reserve_string(text.len() as u64)?;
            JsonValue::String(text.to_owned())
        }
        6 => {
            let count = reader.varint("json array count")?;
            check_count(count, limits)?;
            budget.reserve_vec::<JsonValue>(count)?;
            let mut values = Vec::with_capacity(count as usize);
            for _ in 0..count {
                values.push(decode_json_budgeted(reader, limits, depth + 1, budget)?);
            }
            JsonValue::Array(values)
        }
        7 => {
            let count = reader.varint("json object count")?;
            check_count(count, limits)?;
            budget.reserve_vec::<(String, JsonValue)>(count)?;
            let mut entries = Vec::with_capacity(count as usize);
            for _ in 0..count {
                let len = reader.varint("json key length")?;
                check_len(len, limits)?;
                let bytes = reader.bytes(len as usize, "json key")?;
                let key = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "json key",
                })?;
                budget.reserve_string(key.len() as u64)?;
                let value = decode_json_budgeted(reader, limits, depth + 1, budget)?;
                entries.push((key.to_owned(), value));
            }
            JsonValue::Object(entries)
        }
        _ => {
            return Err(SegmentError::Corrupt {
                context: "json tag",
                detail: format!("unknown {tag}"),
            });
        }
    })
}

/// PR 15E Phase 3: consume and validate one field state without materializing it.
///
/// This is the allocation-free sibling of [`decode_field_values_budgeted`]. It
/// consumes exactly the same bytes, applies the same validity checks in the same
/// order, returns the same typed errors, and issues the same modeled
/// [`DecodeBudget`] reservations — but never constructs a `FieldValues`,
/// `FieldValue`, `JsonValue`, `String`, `Vec` or `BTreeMap` for the skipped value.
///
/// Selected records continue to use the normal decoder; this helper exists only so
/// the selective STORED scanner can validate every *unselected* record fully.
pub(crate) fn skip_field_values_budgeted(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<()> {
    let state = reader.u8("field state")?;
    match state {
        STATE_ABSENT | STATE_EXPLICIT_NULL | STATE_EMPTY_MULTI => Ok(()),
        STATE_SINGLE => skip_scalar_budgeted(reader, field_type, limits, budget),
        STATE_MULTI => {
            let count = reader.varint("multi count")?;
            if count == 0 {
                return Err(SegmentError::Corrupt {
                    context: "multi count",
                    detail: "zero count; use EMPTY_MULTI".to_owned(),
                });
            }
            if count > limits.max_array_elements() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_array_elements(),
                    requested: count,
                });
            }
            limits.check_entries(count)?;
            budget.reserve_vec::<FieldValue>(count)?;
            for _ in 0..count {
                skip_scalar_budgeted(reader, field_type, limits, budget)?;
            }
            Ok(())
        }
        value => Err(SegmentError::InvalidFieldState { value }),
    }
}

/// Consume and validate one typed scalar without materializing it.
///
/// Byte consumption, validation order, typed errors and modeled budget charges
/// mirror [`decode_scalar_budgeted`] exactly. In particular the raw `F64` field
/// value is **not** rejected for non-finite payloads on read, because the existing
/// decoder does not reject it either; parity with the accepted decoder governs.
fn skip_scalar_budgeted(
    reader: &mut ByteReader<'_>,
    field_type: FieldType,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<()> {
    match field_type {
        FieldType::Text => {
            let len = reader.varint("text length")?;
            check_len(len, limits)?;
            let bytes = reader.bytes(len as usize, "text bytes")?;
            let text = std::str::from_utf8(bytes)
                .map_err(|_| SegmentError::InvalidUtf8 { context: "text" })?;
            budget.reserve_string(text.len() as u64)
        }
        FieldType::Keyword => {
            let bytes = reader.len_prefixed_u16("keyword")?;
            let keyword = std::str::from_utf8(bytes)
                .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?;
            budget.reserve_string(keyword.len() as u64)
        }
        FieldType::Bool => match reader.u8("bool")? {
            0 | 1 => Ok(()),
            value => Err(SegmentError::Corrupt {
                context: "bool",
                detail: format!("invalid {value}"),
            }),
        },
        FieldType::I64 => {
            reader.i64("i64")?;
            Ok(())
        }
        FieldType::U64 => {
            reader.u64("u64")?;
            Ok(())
        }
        FieldType::F64 => {
            reader.f64("f64")?;
            Ok(())
        }
        FieldType::Timestamp => {
            reader.i64("timestamp")?;
            Ok(())
        }
        FieldType::GeoPoint => {
            let lon = reader.f64("geo lon")?;
            let lat = reader.f64("geo lat")?;
            GeoPoint::new(lon, lat).map_err(|_| SegmentError::InvalidGeo {
                detail: "coordinate out of range or non-finite",
            })?;
            Ok(())
        }
        FieldType::IpAddress => {
            decode_ip(reader)?;
            Ok(())
        }
        FieldType::IpNetwork => {
            let addr = decode_ip(reader)?;
            let prefix = reader.u8("cidr prefix")?;
            IpNetwork::new(addr, prefix).map_err(|_| SegmentError::InvalidIp {
                detail: "invalid cidr network",
            })?;
            Ok(())
        }
        FieldType::Json => skip_json_budgeted(reader, limits, 0, budget),
    }
}

/// Consume and validate one JSON value recursively without materializing it.
///
/// Mirrors [`decode_json_budgeted`] exactly: same depth/size/entry/UTF-8 checks,
/// same modeled budget charges, same typed errors.
fn skip_json_budgeted(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
    depth: u64,
    budget: &mut DecodeBudget<'_>,
) -> SegmentResult<()> {
    if depth > limits.max_json_depth() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_json_depth(),
            requested: depth,
        });
    }
    let tag = reader.u8("json tag")?;
    match tag {
        0 => Ok(()),
        1 => match reader.u8("json bool")? {
            0 | 1 => Ok(()),
            value => Err(SegmentError::Corrupt {
                context: "json bool",
                detail: format!("invalid {value}"),
            }),
        },
        2 => {
            reader.i64("json i64")?;
            Ok(())
        }
        3 => {
            reader.u64("json u64")?;
            Ok(())
        }
        4 => {
            reader.f64("json f64")?;
            Ok(())
        }
        5 => {
            let len = reader.varint("json string length")?;
            check_len(len, limits)?;
            let bytes = reader.bytes(len as usize, "json string")?;
            let text = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "json string",
            })?;
            budget.reserve_string(text.len() as u64)
        }
        6 => {
            let count = reader.varint("json array count")?;
            check_count(count, limits)?;
            budget.reserve_vec::<JsonValue>(count)?;
            for _ in 0..count {
                skip_json_budgeted(reader, limits, depth + 1, budget)?;
            }
            Ok(())
        }
        7 => {
            let count = reader.varint("json object count")?;
            check_count(count, limits)?;
            budget.reserve_vec::<(String, JsonValue)>(count)?;
            for _ in 0..count {
                let len = reader.varint("json key length")?;
                check_len(len, limits)?;
                let bytes = reader.bytes(len as usize, "json key")?;
                let key = std::str::from_utf8(bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "json key",
                })?;
                budget.reserve_string(key.len() as u64)?;
                skip_json_budgeted(reader, limits, depth + 1, budget)?;
            }
            Ok(())
        }
        _ => Err(SegmentError::Corrupt {
            context: "json tag",
            detail: format!("unknown {tag}"),
        }),
    }
}

fn check_len(len: u64, limits: &SegmentLimits) -> SegmentResult<()> {
    if len > limits.max_single_allocation() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: len,
        });
    }
    Ok(())
}

fn check_count(count: u64, limits: &SegmentLimits) -> SegmentResult<()> {
    if count > limits.max_array_elements() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_array_elements(),
            requested: count,
        });
    }
    limits.check_entries(count)
}

#[cfg(test)]
mod phase3_tests {
    //! PR 15E Phase 3 — differential proof that the allocation-free skip path is
    //! byte-, check-, error- and modeled-budget-identical to the accepted decoder.

    use super::*;
    use crate::contract::value::Timestamp;

    fn limits() -> SegmentLimits {
        SegmentLimits::default()
    }

    fn encode_state(
        field_type: FieldType,
        values: &FieldValues,
        limits: &SegmentLimits,
    ) -> Vec<u8> {
        let mut writer = ByteWriter::new();
        encode_field_values(&mut writer, field_type, values, limits).expect("encode");
        writer.into_vec()
    }

    /// Run the accepted decoder and the skip path over identical bytes and require
    /// identical cursor position, identical modeled budget and identical outcome.
    fn differential(field_type: FieldType, bytes: &[u8], limits: &SegmentLimits, label: &str) {
        let mut decode_reader = ByteReader::new(bytes);
        let mut decode_budget = DecodeBudget::new(limits);
        let decoded = decode_field_values_budgeted(
            &mut decode_reader,
            field_type,
            limits,
            &mut decode_budget,
        );
        let mut skip_reader = ByteReader::new(bytes);
        let mut skip_budget = DecodeBudget::new(limits);
        let skipped =
            skip_field_values_budgeted(&mut skip_reader, field_type, limits, &mut skip_budget);
        match (decoded, skipped) {
            (Ok(_), Ok(())) => {
                assert_eq!(
                    decode_reader.position(),
                    skip_reader.position(),
                    "{label}: cursor divergence"
                );
                assert_eq!(
                    decode_budget.retained(),
                    skip_budget.retained(),
                    "{label}: modeled budget divergence"
                );
            }
            (Err(expected), Err(actual)) => {
                assert_eq!(
                    format!("{expected:?}"),
                    format!("{actual:?}"),
                    "{label}: typed error divergence"
                );
                assert_eq!(
                    decode_reader.position(),
                    skip_reader.position(),
                    "{label}: cursor divergence on rejection"
                );
            }
            (Ok(_), Err(actual)) => panic!("{label}: skip rejected a valid value: {actual:?}"),
            (Err(expected), Ok(())) => {
                panic!("{label}: skip accepted a value the decoder rejects: {expected:?}")
            }
        }
    }

    fn scalar_cases() -> Vec<(FieldType, Vec<FieldValue>)> {
        vec![
            (
                FieldType::Text,
                vec![
                    FieldValue::Text("hello".to_owned()),
                    FieldValue::Text("wörld ünïcode".to_owned()),
                ],
            ),
            (
                FieldType::Keyword,
                vec![
                    FieldValue::Keyword("k1".to_owned()),
                    FieldValue::Keyword("k2-løng".to_owned()),
                ],
            ),
            (
                FieldType::Bool,
                vec![FieldValue::Bool(true), FieldValue::Bool(false)],
            ),
            (
                FieldType::I64,
                vec![FieldValue::I64(-5), FieldValue::I64(7)],
            ),
            (
                FieldType::U64,
                vec![FieldValue::U64(5), FieldValue::U64(u64::MAX)],
            ),
            (
                FieldType::F64,
                vec![FieldValue::F64(1.5), FieldValue::F64(-2.25)],
            ),
            (
                FieldType::Timestamp,
                vec![
                    FieldValue::Timestamp(Timestamp::from_micros(123)),
                    FieldValue::Timestamp(Timestamp::from_micros(-456)),
                ],
            ),
            (
                FieldType::GeoPoint,
                vec![
                    FieldValue::GeoPoint(GeoPoint::new(1.0, 2.0).unwrap()),
                    FieldValue::GeoPoint(GeoPoint::new(-179.5, 89.0).unwrap()),
                ],
            ),
            (
                FieldType::IpAddress,
                vec![
                    FieldValue::Ip("10.0.0.1".parse().unwrap()),
                    FieldValue::Ip("2001:db8::1".parse().unwrap()),
                ],
            ),
            (
                FieldType::IpNetwork,
                vec![
                    FieldValue::Cidr(IpNetwork::new("10.0.0.0".parse().unwrap(), 24).unwrap()),
                    FieldValue::Cidr(IpNetwork::new("2001:db8::".parse().unwrap(), 32).unwrap()),
                ],
            ),
            (
                FieldType::Json,
                vec![
                    FieldValue::Json(JsonValue::Null),
                    FieldValue::Json(JsonValue::Array(vec![
                        JsonValue::Bool(true),
                        JsonValue::Number(JsonNumber::I64(-9)),
                        JsonValue::Number(JsonNumber::U64(9)),
                        JsonValue::Number(JsonNumber::F64(2.5)),
                        JsonValue::String("nested ünïcode".to_owned()),
                        JsonValue::Object(vec![
                            ("a".to_owned(), JsonValue::Array(vec![JsonValue::Null])),
                            ("b".to_owned(), JsonValue::Object(vec![])),
                        ]),
                    ])),
                ],
            ),
        ]
    }

    /// U03/U09: every type and every five-state variant is byte/budget identical.
    #[test]
    fn phase3_skip_matches_decode_for_every_state_and_type() {
        let limits = limits();
        for (field_type, scalars) in scalar_cases() {
            let states = [
                FieldValues::Absent,
                FieldValues::ExplicitNull,
                FieldValues::Empty,
                FieldValues::Single(scalars[0].clone()),
                FieldValues::Multi(scalars.clone()),
            ];
            for state in states {
                let bytes = encode_state(field_type, &state, &limits);
                differential(
                    field_type,
                    &bytes,
                    &limits,
                    &format!("{field_type:?} {state:?}"),
                );
            }
        }
    }

    /// U05/U06/U07: malformed payloads are rejected identically, with the same
    /// typed error, by both paths.
    #[test]
    fn phase3_skip_matches_decode_on_malformed_inputs() {
        let limits = limits();
        let mut cases: Vec<(FieldType, Vec<u8>, &str)> = Vec::new();

        // Invalid bool payload.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(2);
        cases.push((FieldType::Bool, writer.into_vec(), "invalid bool"));

        // Invalid UTF-8 text payload.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.varint(2);
        writer.bytes(&[0xff, 0xfe]);
        cases.push((FieldType::Text, writer.into_vec(), "invalid utf8 text"));

        // Invalid UTF-8 keyword payload.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.len_prefixed_u16(&[0xff]).unwrap();
        cases.push((
            FieldType::Keyword,
            writer.into_vec(),
            "invalid utf8 keyword",
        ));

        // Unknown JSON tag.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(9);
        cases.push((FieldType::Json, writer.into_vec(), "unknown json tag"));

        // Invalid JSON bool.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(1);
        writer.u8(7);
        cases.push((FieldType::Json, writer.into_vec(), "invalid json bool"));

        // Invalid UTF-8 JSON string.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(5);
        writer.varint(1);
        writer.bytes(&[0xff]);
        cases.push((
            FieldType::Json,
            writer.into_vec(),
            "invalid utf8 json string",
        ));

        // Invalid UTF-8 JSON object key.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(7);
        writer.varint(1);
        writer.varint(1);
        writer.bytes(&[0xff]);
        writer.u8(0);
        cases.push((FieldType::Json, writer.into_vec(), "invalid utf8 json key"));

        // Out-of-range geo coordinate.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.f64(200.0);
        writer.f64(0.0);
        cases.push((FieldType::GeoPoint, writer.into_vec(), "invalid geo"));

        // Non-finite geo coordinate.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.f64(f64::NAN);
        writer.f64(0.0);
        cases.push((FieldType::GeoPoint, writer.into_vec(), "non-finite geo"));

        // Invalid CIDR prefix for the address family.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        encode_ip(&mut writer, "10.0.0.0".parse().unwrap());
        writer.u8(33);
        cases.push((FieldType::IpNetwork, writer.into_vec(), "invalid cidr"));

        // Invalid IP family tag.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(2);
        cases.push((FieldType::IpAddress, writer.into_vec(), "invalid ip family"));

        // Zero multi count.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_MULTI);
        writer.varint(0);
        cases.push((FieldType::I64, writer.into_vec(), "zero multi count"));

        // Unknown field state.
        let mut writer = ByteWriter::new();
        writer.u8(9);
        cases.push((FieldType::I64, writer.into_vec(), "invalid field state"));

        // Text length above the single-allocation ceiling.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.varint(limits.max_single_allocation() + 1);
        cases.push((FieldType::Text, writer.into_vec(), "oversized text"));

        // JSON array count above the element ceiling.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.u8(6);
        writer.varint(limits.max_array_elements() + 1);
        cases.push((FieldType::Json, writer.into_vec(), "oversized json array"));

        // JSON nesting deeper than the maximum.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        for _ in 0..=(limits.max_json_depth() + 1) {
            writer.u8(6);
            writer.varint(1);
        }
        writer.u8(0);
        cases.push((FieldType::Json, writer.into_vec(), "json depth overflow"));

        // Overlong varint text length.
        let mut writer = ByteWriter::new();
        writer.u8(STATE_SINGLE);
        writer.bytes(&[0xff; 10]);
        cases.push((FieldType::Text, writer.into_vec(), "overlong varint"));

        // Truncated payloads for every type.
        for (field_type, _) in scalar_cases() {
            let bytes = encode_state(
                field_type,
                &FieldValues::Single(scalar_cases_value(field_type)),
                &limits,
            );
            cases.push((
                field_type,
                bytes[..bytes.len() - 1].to_vec(),
                "truncated payload",
            ));
        }

        for (field_type, bytes, label) in cases {
            differential(field_type, &bytes, &limits, label);
        }
    }

    fn scalar_cases_value(field_type: FieldType) -> FieldValue {
        scalar_cases()
            .into_iter()
            .find(|(kind, _)| *kind == field_type)
            .expect("scalar case")
            .1
            .remove(0)
    }

    /// U10/U07: modeled budget ceilings reject at exactly the same byte.
    #[test]
    fn phase3_skip_matches_decode_under_tight_budgets() {
        let base = limits();
        let field_type = FieldType::Json;
        let values = FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![(
            "k".to_owned(),
            JsonValue::String("value".to_owned()),
        )])));
        let bytes = encode_state(field_type, &values, &base);

        // Minimum cumulative ceiling that admits the accepted decoder.
        let mut low = 0u64;
        let mut high = 1 << 20;
        while low < high {
            let mid = low + (high - low) / 2;
            let candidate = base.with_max_section_decode_bytes(mid);
            let mut reader = ByteReader::new(&bytes);
            let mut budget = DecodeBudget::new(&candidate);
            if decode_field_values_budgeted(&mut reader, field_type, &candidate, &mut budget)
                .is_ok()
            {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        let exact = low;
        let at = base.with_max_section_decode_bytes(exact);
        differential(field_type, &bytes, &at, "exact decode budget");
        let below = base.with_max_section_decode_bytes(exact.saturating_sub(1));
        differential(field_type, &bytes, &below, "one-below decode budget");
        // The one-below case really is a rejection for both paths.
        let mut reader = ByteReader::new(&bytes);
        let mut budget = DecodeBudget::new(&below);
        assert!(matches!(
            skip_field_values_budgeted(&mut reader, field_type, &below, &mut budget),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }
}
