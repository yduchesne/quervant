//! Opaque, snapshot-bound unified search-after cursor (PR 14 F2).
//!
//! The cursor is process-local, non-serializable and crate-constructed only. It
//! carries the snapshot binding id, a deterministic query+sort fingerprint and
//! the complete last sort tuple (plus score for relevance ordering). A cursor is
//! valid only for the exact immutable snapshot and query/sort that produced it.
//!
//! The fingerprint canonical-encodes the validated AST and sort definition with
//! length-prefixed strings, explicit variant tags and IEEE bit patterns. It never
//! hashes `Debug` output, randomized hashes, addresses or lexical expansions.

use sha2::{Digest, Sha256};

use crate::contract::document::DocumentKey;
use crate::contract::query::{Bound, ConcreteJsonPath, JsonPathExpr, JsonPathSegment, Query};
use crate::contract::result::{MultiValueSelector, Sort};
use crate::contract::value::{FieldValue, JsonNumber, JsonValue, Timestamp};
use crate::segment::CodecSchema;

use super::typed_compare::SortValue;

const CURSOR_VERSION: &[u8] = b"quervant-unified-cursor-v1";

/// A snapshot-bound unified continuation token.
#[derive(Debug, Clone, PartialEq)]
pub struct UnifiedCursor {
    pub(crate) snapshot_binding: u64,
    pub(crate) fingerprint: [u8; 32],
    pub(crate) last_sort: Vec<SortValue>,
    pub(crate) last_score: Option<f64>,
    pub(crate) last_key: DocumentKey,
}

impl UnifiedCursor {
    pub(crate) fn new(
        snapshot_binding: u64,
        fingerprint: [u8; 32],
        last_sort: Vec<SortValue>,
        last_score: Option<f64>,
        last_key: DocumentKey,
    ) -> Self {
        Self {
            snapshot_binding,
            fingerprint,
            last_sort,
            last_score,
            last_key,
        }
    }

    #[must_use]
    pub fn snapshot_binding(&self) -> u64 {
        self.snapshot_binding
    }

    #[must_use]
    pub fn last_key(&self) -> &DocumentKey {
        &self.last_key
    }

    #[must_use]
    pub fn last_sort_values(&self) -> &[SortValue] {
        &self.last_sort
    }

    #[must_use]
    pub fn last_score(&self) -> Option<f64> {
        self.last_score
    }
}

/// Deterministic query+sort+schema fingerprint for a unified request.
pub(crate) fn fingerprint(query: &Query, schema: &CodecSchema, sort: &Sort) -> [u8; 32] {
    let mut buffer = Vec::new();
    buffer.extend_from_slice(CURSOR_VERSION);
    encode_query(&mut buffer, query);
    encode_schema(&mut buffer, schema);
    encode_sort(&mut buffer, sort);
    let mut hasher = Sha256::new();
    hasher.update(&buffer);
    hasher.finalize().into()
}

fn put_tag(buffer: &mut Vec<u8>, tag: u8) {
    buffer.push(tag);
}

fn put_u64(buffer: &mut Vec<u8>, value: u64) {
    buffer.extend_from_slice(&value.to_le_bytes());
}

fn put_i64(buffer: &mut Vec<u8>, value: i64) {
    buffer.extend_from_slice(&value.to_le_bytes());
}

fn put_f64(buffer: &mut Vec<u8>, value: f64) {
    // Canonical IEEE bits; non-finite values are rejected during validation.
    buffer.extend_from_slice(&value.to_bits().to_le_bytes());
}

fn put_bytes(buffer: &mut Vec<u8>, bytes: &[u8]) {
    put_u64(buffer, bytes.len() as u64);
    buffer.extend_from_slice(bytes);
}

fn put_str(buffer: &mut Vec<u8>, value: &str) {
    put_bytes(buffer, value.as_bytes());
}

fn encode_schema(buffer: &mut Vec<u8>, schema: &CodecSchema) {
    put_u64(buffer, schema.fields().len() as u64);
    for field in schema.fields() {
        put_u64(buffer, u64::from(field.id));
        put_str(buffer, &field.name);
        put_tag(buffer, field.field_type as u8);
        put_tag(buffer, field.cardinality as u8);
        put_tag(buffer, u8::from(field.options.indexed));
        put_tag(buffer, u8::from(field.options.stored));
        put_tag(buffer, u8::from(field.options.columnar));
        encode_binding(buffer, field.analyzer.as_ref());
        encode_binding(buffer, field.normalizer.as_ref());
    }
}

fn encode_binding(buffer: &mut Vec<u8>, binding: Option<&crate::segment::FieldBinding>) {
    match binding {
        None => put_tag(buffer, 0),
        Some(binding) => {
            put_tag(buffer, 1);
            put_str(buffer, &binding.id);
            put_str(buffer, &binding.version);
            buffer.extend_from_slice(&binding.fingerprint);
        }
    }
}

fn encode_query(buffer: &mut Vec<u8>, query: &Query) {
    match query {
        Query::MatchAll => put_tag(buffer, 1),
        Query::Term { field, value } => {
            put_tag(buffer, 2);
            put_str(buffer, field);
            encode_value(buffer, value);
        }
        Query::Phrase { field, terms } => {
            put_tag(buffer, 3);
            put_str(buffer, field);
            put_u64(buffer, terms.len() as u64);
            for term in terms {
                put_str(buffer, term);
            }
        }
        Query::Prefix { field, prefix } => {
            put_tag(buffer, 4);
            put_str(buffer, field);
            put_str(buffer, prefix);
        }
        Query::Glob { field, pattern } => {
            put_tag(buffer, 5);
            put_str(buffer, field);
            put_str(buffer, pattern);
        }
        Query::Regex { field, pattern } => {
            put_tag(buffer, 6);
            put_str(buffer, field);
            put_str(buffer, pattern);
        }
        Query::Fuzzy {
            field,
            value,
            max_edits,
            transpositions,
        } => {
            put_tag(buffer, 7);
            put_str(buffer, field);
            put_str(buffer, value);
            put_tag(buffer, *max_edits);
            put_tag(buffer, u8::from(*transpositions));
        }
        Query::Range {
            field,
            lower,
            upper,
        } => {
            put_tag(buffer, 8);
            put_str(buffer, field);
            encode_bound(buffer, lower);
            encode_bound(buffer, upper);
        }
        Query::TimeRange { field, start, end } => {
            put_tag(buffer, 9);
            put_str(buffer, field);
            put_i64(buffer, start.as_micros());
            put_i64(buffer, end.as_micros());
        }
        Query::Exists { field } => {
            put_tag(buffer, 10);
            put_str(buffer, field);
        }
        Query::Missing { field } => {
            put_tag(buffer, 11);
            put_str(buffer, field);
        }
        Query::IsNull { field } => {
            put_tag(buffer, 12);
            put_str(buffer, field);
        }
        Query::In { field, values } => {
            put_tag(buffer, 13);
            put_str(buffer, field);
            put_u64(buffer, values.len() as u64);
            for value in values {
                encode_value(buffer, value);
            }
        }
        Query::NotIn { field, values } => {
            put_tag(buffer, 14);
            put_str(buffer, field);
            put_u64(buffer, values.len() as u64);
            for value in values {
                encode_value(buffer, value);
            }
        }
        Query::IpExact { field, addr } => {
            put_tag(buffer, 15);
            put_str(buffer, field);
            encode_ip(buffer, *addr);
        }
        Query::IpRange { field, start, end } => {
            put_tag(buffer, 16);
            put_str(buffer, field);
            encode_ip(buffer, *start);
            encode_ip(buffer, *end);
        }
        Query::IpInCidr { field, network } => {
            put_tag(buffer, 17);
            put_str(buffer, field);
            encode_network(buffer, *network);
        }
        Query::IpNotInCidr { field, network } => {
            put_tag(buffer, 18);
            put_str(buffer, field);
            encode_network(buffer, *network);
        }
        Query::JsonPathEquals { field, path, value } => {
            put_tag(buffer, 19);
            put_str(buffer, field);
            encode_json_path_expr(buffer, path);
            encode_value(buffer, value);
        }
        Query::JsonPathExists { field, path } => {
            put_tag(buffer, 20);
            put_str(buffer, field);
            encode_json_path_expr(buffer, path);
        }
        Query::JsonPathRange {
            field,
            path,
            lower,
            upper,
        } => {
            put_tag(buffer, 21);
            put_str(buffer, field);
            encode_concrete_path(buffer, path);
            encode_bound(buffer, lower);
            encode_bound(buffer, upper);
        }
        Query::JsonPathArrayContains { field, path, value } => {
            put_tag(buffer, 22);
            put_str(buffer, field);
            encode_concrete_path(buffer, path);
            encode_value(buffer, value);
        }
        Query::GeoBoundingBox { field, bbox } => {
            put_tag(buffer, 23);
            put_str(buffer, field);
            for value in [bbox.west, bbox.south, bbox.east, bbox.north] {
                put_f64(buffer, value);
            }
        }
        Query::GeoRadius { field, radius } => {
            put_tag(buffer, 24);
            put_str(buffer, field);
            put_f64(buffer, radius.center.lon());
            put_f64(buffer, radius.center.lat());
            put_f64(buffer, radius.meters);
        }
        Query::GeoPolygon { field, polygon } => {
            put_tag(buffer, 25);
            put_str(buffer, field);
            encode_ring(buffer, polygon.outer());
            put_u64(buffer, polygon.holes().len() as u64);
            for hole in polygon.holes() {
                encode_ring(buffer, hole);
            }
        }
        Query::And(children) => {
            put_tag(buffer, 26);
            put_u64(buffer, children.len() as u64);
            for child in children {
                encode_query(buffer, child);
            }
        }
        Query::Or(children) => {
            put_tag(buffer, 27);
            put_u64(buffer, children.len() as u64);
            for child in children {
                encode_query(buffer, child);
            }
        }
        Query::Not(inner) => {
            put_tag(buffer, 28);
            encode_query(buffer, inner);
        }
    }
}

fn encode_ring(buffer: &mut Vec<u8>, ring: &[crate::contract::value::GeoPoint]) {
    put_u64(buffer, ring.len() as u64);
    for point in ring {
        put_f64(buffer, point.lon());
        put_f64(buffer, point.lat());
    }
}

fn encode_bound(buffer: &mut Vec<u8>, bound: &Bound<FieldValue>) {
    match bound {
        Bound::Unbounded => put_tag(buffer, 0),
        Bound::Included(value) => {
            put_tag(buffer, 1);
            encode_value(buffer, value);
        }
        Bound::Excluded(value) => {
            put_tag(buffer, 2);
            encode_value(buffer, value);
        }
    }
}

fn encode_value(buffer: &mut Vec<u8>, value: &FieldValue) {
    match value {
        FieldValue::Text(text) => {
            put_tag(buffer, 1);
            put_str(buffer, text);
        }
        FieldValue::Keyword(text) => {
            put_tag(buffer, 2);
            put_str(buffer, text);
        }
        FieldValue::Bool(flag) => {
            put_tag(buffer, 3);
            put_tag(buffer, u8::from(*flag));
        }
        FieldValue::I64(number) => {
            put_tag(buffer, 4);
            put_i64(buffer, *number);
        }
        FieldValue::U64(number) => {
            put_tag(buffer, 5);
            put_u64(buffer, *number);
        }
        FieldValue::F64(number) => {
            put_tag(buffer, 6);
            put_f64(buffer, *number);
        }
        FieldValue::Timestamp(timestamp) => {
            put_tag(buffer, 7);
            put_i64(buffer, timestamp.as_micros());
        }
        FieldValue::Json(json) => {
            put_tag(buffer, 8);
            encode_json(buffer, json);
        }
        FieldValue::GeoPoint(point) => {
            put_tag(buffer, 9);
            put_f64(buffer, point.lon());
            put_f64(buffer, point.lat());
        }
        FieldValue::Ip(addr) => {
            put_tag(buffer, 10);
            encode_ip(buffer, *addr);
        }
        FieldValue::Cidr(network) => {
            put_tag(buffer, 11);
            encode_network(buffer, *network);
        }
    }
}

fn encode_json(buffer: &mut Vec<u8>, value: &JsonValue) {
    match value {
        JsonValue::Null => put_tag(buffer, 0),
        JsonValue::Bool(flag) => {
            put_tag(buffer, 1);
            put_tag(buffer, u8::from(*flag));
        }
        JsonValue::Number(number) => {
            put_tag(buffer, 2);
            match number {
                JsonNumber::I64(value) => {
                    put_tag(buffer, 0);
                    put_i64(buffer, *value);
                }
                JsonNumber::U64(value) => {
                    put_tag(buffer, 1);
                    put_u64(buffer, *value);
                }
                JsonNumber::F64(value) => {
                    put_tag(buffer, 2);
                    put_f64(buffer, *value);
                }
            }
        }
        JsonValue::String(text) => {
            put_tag(buffer, 3);
            put_str(buffer, text);
        }
        JsonValue::Array(values) => {
            put_tag(buffer, 4);
            put_u64(buffer, values.len() as u64);
            for value in values {
                encode_json(buffer, value);
            }
        }
        JsonValue::Object(entries) => {
            put_tag(buffer, 5);
            put_u64(buffer, entries.len() as u64);
            for (key, value) in entries {
                put_str(buffer, key);
                encode_json(buffer, value);
            }
        }
    }
}

fn encode_ip(buffer: &mut Vec<u8>, addr: std::net::IpAddr) {
    match addr {
        std::net::IpAddr::V4(v4) => {
            put_tag(buffer, 4);
            buffer.extend_from_slice(&v4.octets());
        }
        std::net::IpAddr::V6(v6) => {
            put_tag(buffer, 6);
            buffer.extend_from_slice(&v6.octets());
        }
    }
}

fn encode_network(buffer: &mut Vec<u8>, network: crate::contract::value::IpNetwork) {
    encode_ip(buffer, network.addr());
    put_tag(buffer, network.prefix());
}

fn encode_json_path_expr(buffer: &mut Vec<u8>, path: &JsonPathExpr) {
    encode_segments(buffer, path.segments());
}

fn encode_concrete_path(buffer: &mut Vec<u8>, path: &ConcreteJsonPath) {
    encode_segments(buffer, path.segments());
}

fn encode_segments(buffer: &mut Vec<u8>, segments: &[JsonPathSegment]) {
    put_u64(buffer, segments.len() as u64);
    for segment in segments {
        match segment {
            JsonPathSegment::Member(member) => {
                put_tag(buffer, 0);
                put_str(buffer, member);
            }
            JsonPathSegment::Index(index) => {
                put_tag(buffer, 1);
                put_u64(buffer, *index as u64);
            }
            JsonPathSegment::Wildcard => put_tag(buffer, 2),
        }
    }
}

fn encode_sort(buffer: &mut Vec<u8>, sort: &Sort) {
    put_u64(buffer, sort.fields.len() as u64);
    for field in &sort.fields {
        put_str(buffer, &field.field);
        put_tag(
            buffer,
            match field.direction {
                crate::contract::result::SortDirection::Asc => 0,
                crate::contract::result::SortDirection::Desc => 1,
            },
        );
        put_tag(
            buffer,
            match field.missing {
                crate::contract::result::MissingValuePosition::First => 0,
                crate::contract::result::MissingValuePosition::Last => 1,
            },
        );
        put_tag(
            buffer,
            match field.multi {
                None => 0,
                Some(MultiValueSelector::Min) => 1,
                Some(MultiValueSelector::Max) => 2,
            },
        );
        match field.distance_from {
            None => put_tag(buffer, 0),
            Some(origin) => {
                put_tag(buffer, 1);
                put_f64(buffer, origin.lon());
                put_f64(buffer, origin.lat());
            }
        }
        match &field.json_path {
            None => put_tag(buffer, 0),
            Some(path) => {
                put_tag(buffer, 1);
                encode_json_path_expr(buffer, path);
            }
        }
    }
}

/// Timestamp helper retained for symmetry with the contract encoding.
#[allow(dead_code)]
fn encode_timestamp(buffer: &mut Vec<u8>, timestamp: Timestamp) {
    put_i64(buffer, timestamp.as_micros());
}
