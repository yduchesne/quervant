//! Typed query AST, JSON path expressions and geo query shapes (A10–A14, A22).

use std::net::IpAddr;

use super::budget::{BudgetKind, Budgets};
use super::document::DocumentKey;
use super::error::{InvalidQueryReason, QueryError};
use super::schema::Schema;
use super::value::{FieldType, FieldValue, GeoPoint, IpNetwork, Timestamp};

/// One decoded JSON path segment (A11).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum JsonPathSegment {
    Member(String),
    Index(usize),
    Wildcard,
}

/// A validated JSON path *expression*. It may contain wildcards and identifies
/// a set of possible matches, never a single value occurrence (A11/A12).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct JsonPathExpr {
    segments: Vec<JsonPathSegment>,
}

impl JsonPathExpr {
    pub fn parse(input: &str) -> Result<Self, QueryError> {
        let mut chars = input.char_indices().peekable();
        match chars.next() {
            Some((_, '$')) => {}
            _ => {
                return Err(QueryError::UnsupportedJsonPath {
                    path: input.to_owned(),
                });
            }
        }
        let mut segments = Vec::new();
        while let Some((offset, ch)) = chars.next() {
            match ch {
                '.' => {
                    let start = offset + 1;
                    let mut end = start;
                    while let Some((index, next)) = chars.peek() {
                        if next.is_ascii_alphanumeric() || *next == '_' {
                            end = index + next.len_utf8();
                            chars.next();
                        } else {
                            break;
                        }
                    }
                    let member = &input[start..end];
                    if member.is_empty() || !is_member_start(member.chars().next().unwrap_or(' ')) {
                        return Err(QueryError::UnsupportedJsonPath {
                            path: input.to_owned(),
                        });
                    }
                    segments.push(JsonPathSegment::Member(member.to_owned()));
                }
                '[' => match chars.peek().copied() {
                    Some((_, '*')) => {
                        chars.next();
                        expect_close(&mut chars, input)?;
                        segments.push(JsonPathSegment::Wildcard);
                    }
                    Some((_, '"')) => {
                        chars.next();
                        let member = parse_json_string(&mut chars, input)?;
                        expect_close(&mut chars, input)?;
                        segments.push(JsonPathSegment::Member(member));
                    }
                    Some((_, digit)) if digit.is_ascii_digit() => {
                        let mut index = 0usize;
                        while let Some((_, next)) = chars.peek().copied() {
                            if next.is_ascii_digit() {
                                chars.next();
                                index = index
                                    .checked_mul(10)
                                    .and_then(|value| {
                                        value.checked_add((next as u8 - b'0') as usize)
                                    })
                                    .ok_or_else(|| QueryError::UnsupportedJsonPath {
                                        path: input.to_owned(),
                                    })?;
                            } else {
                                break;
                            }
                        }
                        expect_close(&mut chars, input)?;
                        segments.push(JsonPathSegment::Index(index));
                    }
                    _ => {
                        return Err(QueryError::UnsupportedJsonPath {
                            path: input.to_owned(),
                        });
                    }
                },
                _ => {
                    return Err(QueryError::UnsupportedJsonPath {
                        path: input.to_owned(),
                    });
                }
            }
        }
        Ok(Self { segments })
    }

    #[must_use]
    pub fn segments(&self) -> &[JsonPathSegment] {
        &self.segments
    }

    #[must_use]
    pub fn is_concrete(&self) -> bool {
        !self
            .segments
            .iter()
            .any(|segment| matches!(segment, JsonPathSegment::Wildcard))
    }

    pub fn to_concrete(&self) -> Result<ConcreteJsonPath, QueryError> {
        if self.is_concrete() {
            Ok(ConcreteJsonPath {
                segments: self.segments.clone(),
            })
        } else {
            Err(QueryError::UnsupportedJsonPath {
                path: "$<wildcard>".into(),
            })
        }
    }
}

fn is_member_start(ch: char) -> bool {
    ch.is_ascii_alphabetic() || ch == '_'
}

fn expect_close(
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
    input: &str,
) -> Result<(), QueryError> {
    match chars.next() {
        Some((_, ']')) => Ok(()),
        _ => Err(QueryError::UnsupportedJsonPath {
            path: input.to_owned(),
        }),
    }
}

fn parse_json_string(
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
    input: &str,
) -> Result<String, QueryError> {
    let mut out = String::new();
    loop {
        let Some((_, ch)) = chars.next() else {
            return Err(QueryError::UnsupportedJsonPath {
                path: input.to_owned(),
            });
        };
        match ch {
            '"' => return Ok(out),
            '\\' => {
                let Some((_, escape)) = chars.next() else {
                    return Err(QueryError::UnsupportedJsonPath {
                        path: input.to_owned(),
                    });
                };
                match escape {
                    '"' => out.push('"'),
                    '\\' => out.push('\\'),
                    '/' => out.push('/'),
                    'b' => out.push('\u{0008}'),
                    'f' => out.push('\u{000C}'),
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    'u' => {
                        let first = parse_hex4(chars, input)?;
                        if (0xD800..=0xDBFF).contains(&first) {
                            // High surrogate: require a following low surrogate.
                            match chars.next() {
                                Some((_, '\\')) => {}
                                _ => {
                                    return Err(QueryError::UnsupportedJsonPath {
                                        path: input.to_owned(),
                                    });
                                }
                            }
                            match chars.next() {
                                Some((_, 'u')) => {}
                                _ => {
                                    return Err(QueryError::UnsupportedJsonPath {
                                        path: input.to_owned(),
                                    });
                                }
                            }
                            let second = parse_hex4(chars, input)?;
                            if !(0xDC00..=0xDFFF).contains(&second) {
                                return Err(QueryError::UnsupportedJsonPath {
                                    path: input.to_owned(),
                                });
                            }
                            let combined = 0x1_0000
                                + ((u32::from(first) - 0xD800) << 10)
                                + (u32::from(second) - 0xDC00);
                            let Some(ch) = char::from_u32(combined) else {
                                return Err(QueryError::UnsupportedJsonPath {
                                    path: input.to_owned(),
                                });
                            };
                            out.push(ch);
                        } else if (0xDC00..=0xDFFF).contains(&first) {
                            return Err(QueryError::UnsupportedJsonPath {
                                path: input.to_owned(),
                            });
                        } else {
                            let Some(ch) = char::from_u32(u32::from(first)) else {
                                return Err(QueryError::UnsupportedJsonPath {
                                    path: input.to_owned(),
                                });
                            };
                            out.push(ch);
                        }
                    }
                    _ => {
                        return Err(QueryError::UnsupportedJsonPath {
                            path: input.to_owned(),
                        });
                    }
                }
            }
            ch if (ch as u32) < 0x20 => {
                return Err(QueryError::UnsupportedJsonPath {
                    path: input.to_owned(),
                });
            }
            ch => out.push(ch),
        }
    }
}

fn parse_hex4(
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
    input: &str,
) -> Result<u16, QueryError> {
    let mut value: u16 = 0;
    for _ in 0..4 {
        let Some((_, ch)) = chars.next() else {
            return Err(QueryError::UnsupportedJsonPath {
                path: input.to_owned(),
            });
        };
        let digit = ch
            .to_digit(16)
            .ok_or_else(|| QueryError::UnsupportedJsonPath {
                path: input.to_owned(),
            })?;
        value = value * 16 + digit as u16;
    }
    Ok(value)
}

/// A resolved, wildcard-free path to one node in one document (A12).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ConcreteJsonPath {
    segments: Vec<JsonPathSegment>,
}

impl ConcreteJsonPath {
    pub fn new(segments: Vec<JsonPathSegment>) -> Result<Self, QueryError> {
        if segments
            .iter()
            .any(|segment| matches!(segment, JsonPathSegment::Wildcard))
        {
            return Err(QueryError::UnsupportedJsonPath {
                path: "$<wildcard>".into(),
            });
        }
        Ok(Self { segments })
    }

    #[must_use]
    pub fn segments(&self) -> &[JsonPathSegment] {
        &self.segments
    }
}

/// A concrete node identity: document key, document revision and concrete path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JsonNodeRef {
    pub key: DocumentKey,
    pub revision: u64,
    pub path: ConcreteJsonPath,
}

/// One side of a range bound.
#[derive(Debug, Clone, PartialEq)]
pub enum Bound<T> {
    Unbounded,
    Included(T),
    Excluded(T),
}

/// A validated geospatial bounding box. `west > east` crosses the antimeridian.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GeoBoundingBox {
    pub west: f64,
    pub south: f64,
    pub east: f64,
    pub north: f64,
}

impl GeoBoundingBox {
    pub fn new(west: f64, south: f64, east: f64, north: f64) -> Result<Self, QueryError> {
        for (value, limit) in [(west, 180.0), (east, 180.0)] {
            if !value.is_finite() {
                return Err(QueryError::InvalidGeoShape {
                    reason: "non-finite longitude",
                });
            }
            if value.abs() > limit {
                return Err(QueryError::InvalidGeoShape {
                    reason: "longitude out of range",
                });
            }
        }
        for (value, limit) in [(south, 90.0), (north, 90.0)] {
            if !value.is_finite() {
                return Err(QueryError::InvalidGeoShape {
                    reason: "non-finite latitude",
                });
            }
            if value.abs() > limit {
                return Err(QueryError::InvalidGeoShape {
                    reason: "latitude out of range",
                });
            }
        }
        if south > north {
            return Err(QueryError::InvalidGeoShape {
                reason: "south greater than north",
            });
        }
        Ok(Self {
            west,
            south,
            east,
            north,
        })
    }
}

/// A radius query in meters.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GeoRadius {
    pub center: GeoPoint,
    pub meters: f64,
}

impl GeoRadius {
    pub fn new(center: GeoPoint, meters: f64) -> Result<Self, QueryError> {
        if !meters.is_finite() || meters <= 0.0 {
            return Err(QueryError::InvalidQuery(
                InvalidQueryReason::InvalidRadius {
                    field: String::new(),
                },
            ));
        }
        Ok(Self { center, meters })
    }
}

/// A polygon with an outer ring and optional holes (A14).
#[derive(Debug, Clone, PartialEq)]
pub struct GeoPolygon {
    outer: Vec<GeoPoint>,
    holes: Vec<Vec<GeoPoint>>,
}

impl GeoPolygon {
    pub fn new(outer: Vec<GeoPoint>, holes: Vec<Vec<GeoPoint>>) -> Result<Self, QueryError> {
        validate_ring(&outer, "outer")?;
        for hole in &holes {
            validate_ring(hole, "hole")?;
        }
        Ok(Self { outer, holes })
    }

    #[must_use]
    pub fn outer(&self) -> &[GeoPoint] {
        &self.outer
    }

    #[must_use]
    pub fn holes(&self) -> &[Vec<GeoPoint>] {
        &self.holes
    }
}

fn normalize_ring(ring: &[GeoPoint]) -> Vec<GeoPoint> {
    if ring.len() >= 2 && ring[0] == ring[ring.len() - 1] {
        ring[..ring.len() - 1].to_vec()
    } else {
        ring.to_vec()
    }
}

fn validate_ring(ring: &[GeoPoint], kind: &'static str) -> Result<(), QueryError> {
    let vertices = normalize_ring(ring);
    if vertices.len() < 3 {
        return Err(QueryError::InvalidGeoShape {
            reason: "ring needs at least three vertices",
        });
    }
    let mut distinct: Vec<&GeoPoint> = Vec::new();
    for vertex in &vertices {
        if !distinct.contains(&vertex) {
            distinct.push(vertex);
        }
    }
    if distinct.len() < 3 {
        return Err(QueryError::InvalidGeoShape {
            reason: "ring needs three distinct vertices",
        });
    }
    for index in 0..vertices.len() {
        let a = vertices[index];
        let b = vertices[(index + 1) % vertices.len()];
        if a.lon().abs() == 180.0 || b.lon().abs() == 180.0 {
            return Err(QueryError::UnsupportedGeoShape {
                reason: "ambiguous longitude endpoint at the antimeridian",
            });
        }
        let delta = (b.lon() - a.lon()).abs();
        if delta >= 180.0 {
            return Err(QueryError::UnsupportedGeoShape {
                reason: "antimeridian-crossing polygon edge",
            });
        }
        if a == b {
            return Err(QueryError::InvalidGeoShape {
                reason: "degenerate edge",
            });
        }
    }
    if shoelace_area(&vertices).abs() < 1e-12 {
        let _ = kind;
        return Err(QueryError::InvalidGeoShape {
            reason: "zero-area ring",
        });
    }
    if ring_self_intersects(&vertices) {
        return Err(QueryError::InvalidGeoShape {
            reason: "self-intersecting ring",
        });
    }
    Ok(())
}

fn shoelace_area(vertices: &[GeoPoint]) -> f64 {
    let mut sum = 0.0;
    for index in 0..vertices.len() {
        let a = vertices[index];
        let b = vertices[(index + 1) % vertices.len()];
        sum += a.lon() * b.lat() - b.lon() * a.lat();
    }
    sum / 2.0
}

fn ring_self_intersects(vertices: &[GeoPoint]) -> bool {
    let count = vertices.len();
    for i in 0..count {
        let a1 = vertices[i];
        let a2 = vertices[(i + 1) % count];
        for j in (i + 1)..count {
            if j == i || (j + 1) % count == i || j == (i + 1) % count {
                continue;
            }
            let b1 = vertices[j];
            let b2 = vertices[(j + 1) % count];
            if segments_intersect(a1, a2, b1, b2) {
                return true;
            }
        }
    }
    false
}

fn segments_intersect(a1: GeoPoint, a2: GeoPoint, b1: GeoPoint, b2: GeoPoint) -> bool {
    let d1 = orientation(b1, b2, a1);
    let d2 = orientation(b1, b2, a2);
    let d3 = orientation(a1, a2, b1);
    let d4 = orientation(a1, a2, b2);
    (d1 * d2 < 0.0) && (d3 * d4 < 0.0)
}

fn orientation(a: GeoPoint, b: GeoPoint, c: GeoPoint) -> f64 {
    (b.lon() - a.lon()) * (c.lat() - a.lat()) - (b.lat() - a.lat()) * (c.lon() - a.lon())
}

/// The typed query AST. Representations are validated; nothing executes here.
#[derive(Debug, Clone, PartialEq)]
pub enum Query {
    MatchAll,
    Term {
        field: String,
        value: FieldValue,
    },
    Phrase {
        field: String,
        terms: Vec<String>,
    },
    Prefix {
        field: String,
        prefix: String,
    },
    Glob {
        field: String,
        pattern: String,
    },
    Regex {
        field: String,
        pattern: String,
    },
    /// Bounded fuzzy term match on an indexed Text/Keyword field.
    ///
    /// `value` is prepared through the field's search analyzer as a **single**
    /// token; zero or multiple tokens are typed analysis errors. `max_edits` is
    /// the maximum edit distance and is limited to `0`, `1` or `2` at validation
    /// time. `transpositions` selects restricted Damerau / optimal-string-alignment
    /// (one adjacent transposition, no substring edited twice) instead of plain
    /// Levenshtein. Distance is measured over normalized Unicode scalar values,
    /// never UTF-8 bytes.
    Fuzzy {
        field: String,
        value: String,
        max_edits: u8,
        transpositions: bool,
    },
    Range {
        field: String,
        lower: Bound<FieldValue>,
        upper: Bound<FieldValue>,
    },
    TimeRange {
        field: String,
        start: Timestamp,
        end: Timestamp,
    },
    Exists {
        field: String,
    },
    Missing {
        field: String,
    },
    IsNull {
        field: String,
    },
    In {
        field: String,
        values: Vec<FieldValue>,
    },
    NotIn {
        field: String,
        values: Vec<FieldValue>,
    },
    IpExact {
        field: String,
        addr: IpAddr,
    },
    IpRange {
        field: String,
        start: IpAddr,
        end: IpAddr,
    },
    IpInCidr {
        field: String,
        network: IpNetwork,
    },
    IpNotInCidr {
        field: String,
        network: IpNetwork,
    },
    JsonPathEquals {
        field: String,
        path: JsonPathExpr,
        value: FieldValue,
    },
    JsonPathExists {
        field: String,
        path: JsonPathExpr,
    },
    GeoBoundingBox {
        field: String,
        bbox: GeoBoundingBox,
    },
    GeoRadius {
        field: String,
        radius: GeoRadius,
    },
    GeoPolygon {
        field: String,
        polygon: GeoPolygon,
    },
    And(Vec<Query>),
    Or(Vec<Query>),
    Not(Box<Query>),
}

impl Query {
    pub fn validate(&self, schema: &Schema, budgets: &Budgets) -> Result<(), QueryError> {
        if let Some(max) = budgets.get(BudgetKind::QueryDepth) {
            if u64::try_from(self.depth()).unwrap_or(u64::MAX) > max {
                return Err(QueryError::BudgetExceeded {
                    kind: BudgetKind::QueryDepth,
                });
            }
        }
        self.validate_inner(schema)
    }

    #[must_use]
    pub fn depth(&self) -> usize {
        match self {
            Self::And(queries) | Self::Or(queries) => {
                1 + queries.iter().map(Self::depth).max().unwrap_or(0)
            }
            Self::Not(inner) => 1 + inner.depth(),
            _ => 1,
        }
    }

    fn validate_inner(&self, schema: &Schema) -> Result<(), QueryError> {
        match self {
            Self::MatchAll => Ok(()),
            Self::Term { field, value } => {
                let definition = require_field(schema, field)?;
                expect_type(field, definition.field_type, value.field_type())
            }
            Self::Phrase { field, terms } => {
                require_lexical(schema, field)?;
                if terms.is_empty() {
                    return Err(InvalidQueryReason::EmptyInValues {
                        field: field.clone(),
                    }
                    .into());
                }
                Ok(())
            }
            Self::Prefix { field, .. } | Self::Glob { field, .. } | Self::Regex { field, .. } => {
                require_lexical(schema, field)
            }
            Self::Fuzzy {
                field, max_edits, ..
            } => {
                require_lexical(schema, field)?;
                if *max_edits > 2 {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "fuzzy_max_edits_above_2",
                    }
                    .into());
                }
                Ok(())
            }
            Self::Range {
                field,
                lower,
                upper,
            } => {
                let definition = require_field(schema, field)?;
                if !(definition.field_type.is_numeric()
                    || definition.field_type == FieldType::Timestamp)
                {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "range",
                    }
                    .into());
                }
                for bound in [lower, upper] {
                    match bound {
                        Bound::Unbounded => {}
                        Bound::Included(value) | Bound::Excluded(value) => {
                            expect_type(field, definition.field_type, value.field_type())?;
                        }
                    }
                }
                Ok(())
            }
            Self::TimeRange { field, start, end } => {
                let definition = require_field(schema, field)?;
                if definition.field_type != FieldType::Timestamp {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "time_range",
                    }
                    .into());
                }
                if start > end {
                    return Err(InvalidQueryReason::InvalidTimeRange {
                        start_us: start.as_micros(),
                        end_us: end.as_micros(),
                    }
                    .into());
                }
                Ok(())
            }
            Self::Exists { field } | Self::Missing { field } | Self::IsNull { field } => {
                require_field(schema, field).map(|_| ())
            }
            Self::In { field, values } | Self::NotIn { field, values } => {
                let definition = require_field(schema, field)?;
                if values.is_empty() {
                    return Err(InvalidQueryReason::EmptyInValues {
                        field: field.clone(),
                    }
                    .into());
                }
                for value in values {
                    expect_type(field, definition.field_type, value.field_type())?;
                }
                Ok(())
            }
            Self::IpExact { field, .. } => require_type(schema, field, &[FieldType::IpAddress]),
            Self::IpRange { field, start, end } => {
                require_type(schema, field, &[FieldType::IpAddress])?;
                if start.is_ipv4() != end.is_ipv4() || address_cmp(*start) > address_cmp(*end) {
                    return Err(InvalidQueryReason::InvalidIpRange {
                        field: field.clone(),
                    }
                    .into());
                }
                Ok(())
            }
            Self::IpInCidr { field, .. } | Self::IpNotInCidr { field, .. } => {
                require_type(schema, field, &[FieldType::IpAddress, FieldType::IpNetwork])
            }
            Self::JsonPathEquals { field, path, value } => {
                require_type(schema, field, &[FieldType::Json])?;
                if value.field_type() == FieldType::Json {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "jsonpath_equals_json",
                    }
                    .into());
                }
                if !path.is_concrete() {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "jsonpath_equals_wildcard",
                    }
                    .into());
                }
                Ok(())
            }
            Self::JsonPathExists { field, .. } => require_type(schema, field, &[FieldType::Json]),
            Self::GeoBoundingBox { field, .. }
            | Self::GeoRadius { field, .. }
            | Self::GeoPolygon { field, .. } => require_type(schema, field, &[FieldType::GeoPoint]),
            Self::And(queries) | Self::Or(queries) => {
                if queries.is_empty() {
                    return Err(InvalidQueryReason::EmptyBoolean {
                        operator: if matches!(self, Self::And(_)) {
                            "and"
                        } else {
                            "or"
                        },
                    }
                    .into());
                }
                for query in queries {
                    query.validate_inner(schema)?;
                }
                Ok(())
            }
            Self::Not(inner) => inner.validate_inner(schema),
        }
    }
}

fn require_field<'a>(
    schema: &'a Schema,
    field: &str,
) -> Result<&'a super::schema::FieldDefinition, QueryError> {
    schema.get(field).ok_or_else(|| {
        InvalidQueryReason::UnknownField {
            field: field.to_owned(),
        }
        .into()
    })
}

fn require_lexical(schema: &Schema, field: &str) -> Result<(), QueryError> {
    require_type(schema, field, &[FieldType::Text, FieldType::Keyword])
}

fn require_type(schema: &Schema, field: &str, allowed: &[FieldType]) -> Result<(), QueryError> {
    let definition = require_field(schema, field)?;
    if allowed.is_empty() || allowed.contains(&definition.field_type) {
        Ok(())
    } else {
        Err(InvalidQueryReason::UnsupportedOperator {
            field: field.to_owned(),
            operator: "type",
        }
        .into())
    }
}

fn expect_type(field: &str, expected: FieldType, actual: FieldType) -> Result<(), QueryError> {
    if expected == actual {
        Ok(())
    } else {
        Err(QueryError::TypeMismatch {
            field: field.to_owned(),
            expected,
            actual,
        })
    }
}

fn address_cmp(addr: IpAddr) -> (u8, u128) {
    match addr {
        IpAddr::V4(v4) => (0, u128::from(u32::from(v4))),
        IpAddr::V6(v6) => (1, u128::from(v6)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "src",
                    FieldType::IpAddress,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "net",
                    FieldType::IpNetwork,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn jsonpath_accepts_subset() {
        assert_eq!(JsonPathExpr::parse("$").unwrap().segments().len(), 0);
        assert_eq!(JsonPathExpr::parse("$.a.b").unwrap().segments().len(), 2);
        assert_eq!(
            JsonPathExpr::parse("$[\"a b\"]").unwrap().segments().len(),
            1
        );
        assert_eq!(JsonPathExpr::parse("$.a[0]").unwrap().segments().len(), 2);
        assert!(!JsonPathExpr::parse("$.a[*]").unwrap().is_concrete());
        assert_eq!(
            JsonPathExpr::parse("$[\"naïve\"]")
                .unwrap()
                .segments()
                .len(),
            1
        );
        assert_eq!(
            JsonPathExpr::parse("$[\"a\\\"b\"]")
                .unwrap()
                .segments()
                .len(),
            1
        );
        assert_eq!(
            JsonPathExpr::parse("$[\"\\u00e9\"]")
                .unwrap()
                .segments()
                .len(),
            1
        );
    }

    #[test]
    fn jsonpath_rejects_unsupported_and_malformed() {
        for input in [
            "a.b",
            "$..a",
            "$[?(@.x==1)]",
            "$[1:3]",
            "$[-1]",
            "$['a b']",
            "$[\"unterminated",
            "$[\"\\uD800\"]",
            "$[\"\\x\"]",
        ] {
            assert!(JsonPathExpr::parse(input).is_err(), "should reject {input}");
        }
    }

    #[test]
    fn jsonpath_concrete_equivalence() {
        let dotted = JsonPathExpr::parse("$.a").unwrap().to_concrete().unwrap();
        let bracket = JsonPathExpr::parse("$[\"a\"]")
            .unwrap()
            .to_concrete()
            .unwrap();
        assert_eq!(dotted, bracket);
        assert!(JsonPathExpr::parse("$[*]").unwrap().to_concrete().is_err());
        assert!(ConcreteJsonPath::new(vec![JsonPathSegment::Wildcard]).is_err());
    }

    #[test]
    fn polygon_validation_rules() {
        let outer = vec![
            GeoPoint::new(0.0, 0.0).unwrap(),
            GeoPoint::new(2.0, 0.0).unwrap(),
            GeoPoint::new(2.0, 2.0).unwrap(),
            GeoPoint::new(0.0, 2.0).unwrap(),
        ];
        assert!(GeoPolygon::new(outer.clone(), vec![]).is_ok());
        assert!(GeoPolygon::new(vec![outer[0], outer[1]], vec![]).is_err());
        assert!(GeoPolygon::new(vec![outer[0], outer[1], outer[0]], vec![]).is_err());
        // zero-area ring
        assert!(
            GeoPolygon::new(
                vec![
                    GeoPoint::new(0.0, 0.0).unwrap(),
                    GeoPoint::new(1.0, 0.0).unwrap(),
                    GeoPoint::new(2.0, 0.0).unwrap()
                ],
                vec![]
            )
            .is_err()
        );
        // self-intersecting bow-tie
        assert!(
            GeoPolygon::new(
                vec![
                    GeoPoint::new(0.0, 0.0).unwrap(),
                    GeoPoint::new(2.0, 2.0).unwrap(),
                    GeoPoint::new(2.0, 0.0).unwrap(),
                    GeoPoint::new(0.0, 2.0).unwrap(),
                ],
                vec![]
            )
            .is_err()
        );
        // antimeridian crossing
        let crossing = GeoPolygon::new(
            vec![
                GeoPoint::new(170.0, 0.0).unwrap(),
                GeoPoint::new(-170.0, 0.0).unwrap(),
                GeoPoint::new(-170.0, 10.0).unwrap(),
            ],
            vec![],
        );
        assert!(matches!(
            crossing,
            Err(QueryError::UnsupportedGeoShape { .. })
        ));
        // exactly 180 separation
        assert!(matches!(
            GeoPolygon::new(
                vec![
                    GeoPoint::new(-90.0, 0.0).unwrap(),
                    GeoPoint::new(90.0, 0.0).unwrap(),
                    GeoPoint::new(90.0, 10.0).unwrap(),
                ],
                vec![]
            ),
            Err(QueryError::UnsupportedGeoShape { .. })
        ));
    }

    #[test]
    fn bbox_allows_antimeridian_crossing() {
        assert!(GeoBoundingBox::new(170.0, -10.0, -170.0, 10.0).is_ok());
        assert!(GeoBoundingBox::new(0.0, 10.0, 10.0, -10.0).is_err());
        assert!(GeoBoundingBox::new(200.0, 0.0, 10.0, 10.0).is_err());
    }

    #[test]
    fn query_validation_cross_domain() {
        let schema = schema();
        let budgets = Budgets::new().with(BudgetKind::QueryDepth, 8).unwrap();
        assert!(
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text("x".into())
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Term {
                field: "n".into(),
                value: FieldValue::I64(1)
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Term {
                field: "n".into(),
                value: FieldValue::F64(1.0)
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::TimeRange {
                field: "ts".into(),
                start: Timestamp::from_micros(2),
                end: Timestamp::from_micros(1)
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::In {
                field: "src".into(),
                values: vec![FieldValue::Ip("192.0.2.1".parse().unwrap())]
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::In {
                field: "src".into(),
                values: vec![FieldValue::Keyword("x".into())]
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::IpRange {
                field: "src".into(),
                start: "192.0.2.9".parse().unwrap(),
                end: "192.0.2.1".parse().unwrap()
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(Query::And(vec![]).validate(&schema, &budgets).is_err());
        assert!(
            Query::Not(Box::new(Query::MatchAll))
                .validate(&schema, &budgets)
                .is_ok()
        );
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "src",
                    FieldType::IpAddress,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "net",
                    FieldType::IpNetwork,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "loc",
                    FieldType::GeoPoint,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn with_depth(limit: u64) -> Budgets {
        Budgets::new().with(BudgetKind::QueryDepth, limit).unwrap()
    }

    #[test]
    fn lexical_operator_validation() {
        let schema = schema();
        let budgets = with_depth(8);
        assert!(
            Query::Phrase {
                field: "title".into(),
                terms: vec!["a".into()]
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Phrase {
                field: "title".into(),
                terms: vec![]
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::Prefix {
                field: "tag".into(),
                prefix: "a".into()
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Glob {
                field: "tag".into(),
                pattern: "*".into()
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Regex {
                field: "title".into(),
                pattern: "a.*".into()
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Prefix {
                field: "n".into(),
                prefix: "a".into()
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::Prefix {
                field: "missing".into(),
                prefix: "a".into()
            }
            .validate(&schema, &budgets)
            .is_err()
        );
    }

    #[test]
    fn range_and_bound_validation() {
        let schema = schema();
        let budgets = with_depth(8);
        assert!(
            Query::Range {
                field: "n".into(),
                lower: Bound::Included(FieldValue::I64(0)),
                upper: Bound::Excluded(FieldValue::I64(10)),
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Range {
                field: "n".into(),
                lower: Bound::Unbounded,
                upper: Bound::Included(FieldValue::I64(0)),
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::Range {
                field: "title".into(),
                lower: Bound::Unbounded,
                upper: Bound::Unbounded,
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::Range {
                field: "n".into(),
                lower: Bound::Included(FieldValue::F64(1.0)),
                upper: Bound::Unbounded,
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::TimeRange {
                field: "n".into(),
                start: Timestamp::from_micros(0),
                end: Timestamp::from_micros(1)
            }
            .validate(&schema, &budgets)
            .is_err()
        );
    }

    #[test]
    fn ip_and_json_operator_validation() {
        let schema = schema();
        let budgets = with_depth(8);
        assert!(
            Query::IpExact {
                field: "src".into(),
                addr: "10.0.0.1".parse().unwrap()
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::IpExact {
                field: "net".into(),
                addr: "10.0.0.1".parse().unwrap()
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::IpNotInCidr {
                field: "net".into(),
                network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::IpInCidr {
                field: "title".into(),
                network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        let concrete = JsonPathExpr::parse("$.a.b").unwrap();
        let wildcard = JsonPathExpr::parse("$.a[*]").unwrap();
        assert!(
            Query::JsonPathEquals {
                field: "body".into(),
                path: concrete.clone(),
                value: FieldValue::Keyword("x".into()),
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::JsonPathEquals {
                field: "body".into(),
                path: wildcard.clone(),
                value: FieldValue::Keyword("x".into()),
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::JsonPathEquals {
                field: "body".into(),
                path: concrete,
                value: FieldValue::Json(crate::contract::value::JsonValue::Null),
            }
            .validate(&schema, &budgets)
            .is_err()
        );
        assert!(
            Query::JsonPathExists {
                field: "body".into(),
                path: wildcard
            }
            .validate(&schema, &budgets)
            .is_ok()
        );
        assert!(
            Query::JsonPathExists {
                field: "title".into(),
                path: JsonPathExpr::parse("$.a").unwrap()
            }
            .validate(&schema, &budgets)
            .is_err()
        );
    }

    #[test]
    fn geo_and_boolean_and_depth() {
        let schema = schema();
        let budgets = with_depth(2);
        let polygon = GeoPolygon::new(
            vec![
                GeoPoint::new(0.0, 0.0).unwrap(),
                GeoPoint::new(1.0, 0.0).unwrap(),
                GeoPoint::new(1.0, 1.0).unwrap(),
            ],
            vec![],
        )
        .unwrap();
        assert!(
            Query::GeoPolygon {
                field: "loc".into(),
                polygon
            }
            .validate(&schema, &with_depth(8))
            .is_ok()
        );
        assert!(
            Query::GeoBoundingBox {
                field: "loc".into(),
                bbox: GeoBoundingBox::new(0.0, 0.0, 1.0, 1.0).unwrap(),
            }
            .validate(&schema, &with_depth(8))
            .is_ok()
        );
        assert!(
            Query::GeoBoundingBox {
                field: "title".into(),
                bbox: GeoBoundingBox::new(0.0, 0.0, 1.0, 1.0).unwrap(),
            }
            .validate(&schema, &with_depth(8))
            .is_err()
        );
        assert!(
            Query::Or(vec![Query::MatchAll])
                .validate(&schema, &with_depth(8))
                .is_ok()
        );
        assert!(Query::Or(vec![]).validate(&schema, &with_depth(8)).is_err());
        let deeply_nested = Query::Not(Box::new(Query::Not(Box::new(Query::Not(Box::new(
            Query::MatchAll,
        ))))));
        assert!(deeply_nested.depth() >= 4);
        assert!(matches!(
            deeply_nested.validate(&schema, &budgets),
            Err(QueryError::BudgetExceeded {
                kind: BudgetKind::QueryDepth
            })
        ));
    }

    #[test]
    fn jsonpath_edge_cases() {
        assert_eq!(JsonPathExpr::parse("$.a_1").unwrap().segments().len(), 1);
        assert_eq!(JsonPathExpr::parse("$.a[10]").unwrap().segments().len(), 2);
        assert!(JsonPathExpr::parse("$.9bad").is_err());
        assert!(JsonPathExpr::parse("$\"x\"").is_err());
        assert!(JsonPathExpr::parse("$[").is_err());
        assert!(JsonPathExpr::parse("$[1").is_err());
        assert!(JsonPathExpr::parse("$[abc]").is_err());
        assert!(matches!(
            ConcreteJsonPath::new(vec![JsonPathSegment::Wildcard]),
            Err(QueryError::UnsupportedJsonPath { .. })
        ));
        // Surrogate pair decodes to a single scalar value.
        assert_eq!(
            JsonPathExpr::parse("$[\"\\uD83D\\uDE00\"]")
                .unwrap()
                .segments()
                .len(),
            1
        );
    }
}
