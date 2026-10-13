//! Typed value, field-state and JSON encoding (F06/F07).
//!
//! The five logical field states shared by stored source and columns are:
//! `ABSENT`, `EXPLICIT_NULL`, `EMPTY_MULTI`, `SINGLE`, `MULTI`.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use crate::contract::document::FieldValues;
use crate::contract::value::{FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue};

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
    let state = reader.u8("field state")?;
    match state {
        STATE_ABSENT => Ok(FieldValues::Absent),
        STATE_EXPLICIT_NULL => Ok(FieldValues::ExplicitNull),
        STATE_EMPTY_MULTI => Ok(FieldValues::Empty),
        STATE_SINGLE => Ok(FieldValues::Single(decode_scalar(
            reader, field_type, limits,
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
            let mut values = Vec::with_capacity(count as usize);
            for _ in 0..count {
                values.push(decode_scalar(reader, field_type, limits)?);
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
    Ok(match field_type {
        FieldType::Text => {
            let len = reader.varint("text length")?;
            check_len(len, limits)?;
            let bytes = reader.bytes(len as usize, "text bytes")?;
            FieldValue::Text(
                std::str::from_utf8(bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 { context: "text" })?
                    .to_owned(),
            )
        }
        FieldType::Keyword => {
            let bytes = reader.len_prefixed_u16("keyword")?;
            FieldValue::Keyword(
                std::str::from_utf8(bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 { context: "keyword" })?
                    .to_owned(),
            )
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
        FieldType::Json => FieldValue::Json(decode_json(reader, limits, 0)?),
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
            JsonValue::String(
                std::str::from_utf8(bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 {
                        context: "json string",
                    })?
                    .to_owned(),
            )
        }
        6 => {
            let count = reader.varint("json array count")?;
            check_count(count, limits)?;
            let mut values = Vec::with_capacity(count as usize);
            for _ in 0..count {
                values.push(decode_json(reader, limits, depth + 1)?);
            }
            JsonValue::Array(values)
        }
        7 => {
            let count = reader.varint("json object count")?;
            check_count(count, limits)?;
            let mut entries = Vec::with_capacity(count as usize);
            for _ in 0..count {
                let len = reader.varint("json key length")?;
                check_len(len, limits)?;
                let bytes = reader.bytes(len as usize, "json key")?;
                let key = std::str::from_utf8(bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 {
                        context: "json key",
                    })?
                    .to_owned();
                let value = decode_json(reader, limits, depth + 1)?;
                entries.push((key, value));
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
