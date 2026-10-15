//! Typed scalar/structured values, IP/CIDR, timestamps and geo points (A03–A08, A13, A14).

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use super::error::ValueError;

/// The closed set of typed field kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FieldType {
    Text,
    Keyword,
    Bool,
    I64,
    U64,
    F64,
    Timestamp,
    Json,
    GeoPoint,
    IpAddress,
    IpNetwork,
}

impl FieldType {
    #[must_use]
    pub const fn is_numeric(self) -> bool {
        matches!(self, Self::I64 | Self::U64 | Self::F64)
    }

    #[must_use]
    pub const fn is_lexical(self) -> bool {
        matches!(self, Self::Text | Self::Keyword)
    }
}

/// A signed microsecond UTC timestamp (A13).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Timestamp(i64);

impl Timestamp {
    #[must_use]
    pub const fn from_micros(micros: i64) -> Self {
        Self(micros)
    }

    /// Converts milliseconds to microseconds exactly.
    #[must_use]
    pub const fn from_millis(millis: i64) -> Self {
        Self(millis.saturating_mul(1_000))
    }

    /// Converts nanoseconds to microseconds, flooring toward negative infinity
    /// so an event can never be rounded forward across a half-open boundary.
    #[must_use]
    pub const fn from_nanos_floor(nanos: i64) -> Self {
        Self(nanos.div_euclid(1_000))
    }

    #[must_use]
    pub const fn as_micros(self) -> i64 {
        self.0
    }
}

/// A WGS84 `(longitude, latitude)` point (A14).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GeoPoint {
    lon: f64,
    lat: f64,
}

impl GeoPoint {
    pub fn new(lon: f64, lat: f64) -> Result<Self, ValueError> {
        if !lon.is_finite() || !lat.is_finite() {
            return Err(ValueError::NonFiniteFloat);
        }
        if !(-180.0..=180.0).contains(&lon) {
            return Err(ValueError::InvalidLongitude);
        }
        if !(-90.0..=90.0).contains(&lat) {
            return Err(ValueError::InvalidLatitude);
        }
        Ok(Self { lon, lat })
    }

    #[must_use]
    pub const fn lon(self) -> f64 {
        self.lon
    }

    #[must_use]
    pub const fn lat(self) -> f64 {
        self.lat
    }

    /// Convert a strict GeoJSON `Point` into a validated WGS84 point.
    ///
    /// Accepts exactly `{"type":"Point","coordinates":[lon,lat]}` with numeric
    /// finite coordinates. Every other shape is rejected; no other geometry type
    /// is supported and no HTTP/JSON text parsing is performed here.
    pub fn from_geojson(value: &JsonValue) -> Result<Self, ValueError> {
        let JsonValue::Object(entries) = value else {
            return Err(ValueError::MalformedGeoJson);
        };
        let mut kind: Option<&JsonValue> = None;
        let mut coordinates: Option<&JsonValue> = None;
        for (key, member) in entries {
            match key.as_str() {
                "type" => {
                    if kind.replace(member).is_some() {
                        return Err(ValueError::MalformedGeoJson);
                    }
                }
                "coordinates" => {
                    if coordinates.replace(member).is_some() {
                        return Err(ValueError::MalformedGeoJson);
                    }
                }
                _ => return Err(ValueError::MalformedGeoJson),
            }
        }
        if kind != Some(&JsonValue::String("Point".to_owned())) {
            return Err(ValueError::MalformedGeoJson);
        }
        let Some(JsonValue::Array(pair)) = coordinates else {
            return Err(ValueError::MalformedGeoJson);
        };
        if pair.len() != 2 {
            return Err(ValueError::MalformedGeoJson);
        }
        let lon = geojson_number(&pair[0])?;
        let lat = geojson_number(&pair[1])?;
        Self::new(lon, lat)
    }
}

fn geojson_number(value: &JsonValue) -> Result<f64, ValueError> {
    match value {
        JsonValue::Number(JsonNumber::I64(number)) => Ok(*number as f64),
        JsonValue::Number(JsonNumber::U64(number)) => Ok(*number as f64),
        JsonValue::Number(JsonNumber::F64(number)) if number.is_finite() => Ok(*number),
        _ => Err(ValueError::MalformedGeoJson),
    }
}

/// A CIDR network with a validated prefix length (A08).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IpNetwork {
    addr: IpAddr,
    prefix: u8,
}

impl IpNetwork {
    /// Validates a canonical network. Host bits set are rejected.
    pub fn new(addr: IpAddr, prefix: u8) -> Result<Self, ValueError> {
        let masked = mask_addr(addr, prefix)?;
        if masked != addr {
            return Err(ValueError::HostBitsSet);
        }
        Ok(Self { addr, prefix })
    }

    /// Masks any host bits to produce a canonical network.
    pub fn new_masked(addr: IpAddr, prefix: u8) -> Result<Self, ValueError> {
        Ok(Self {
            addr: mask_addr(addr, prefix)?,
            prefix,
        })
    }

    #[must_use]
    pub const fn addr(self) -> IpAddr {
        self.addr
    }

    #[must_use]
    pub const fn prefix(self) -> u8 {
        self.prefix
    }

    /// Family-aware prefix membership. A family mismatch is `false`, never an
    /// error and never a textual prefix comparison.
    #[must_use]
    pub fn contains(&self, addr: &IpAddr) -> bool {
        match (self.addr, addr) {
            (IpAddr::V4(_), IpAddr::V4(candidate)) => mask_v4(*candidate, self.prefix) == self.addr,
            (IpAddr::V6(_), IpAddr::V6(candidate)) => mask_v6(*candidate, self.prefix) == self.addr,
            _ => false,
        }
    }
}

fn mask_addr(addr: IpAddr, prefix: u8) -> Result<IpAddr, ValueError> {
    match addr {
        IpAddr::V4(v4) => {
            if prefix > 32 {
                return Err(ValueError::InvalidPrefixLength);
            }
            Ok(IpAddr::V4(mask_v4(v4, prefix)))
        }
        IpAddr::V6(v6) => {
            if prefix > 128 {
                return Err(ValueError::InvalidPrefixLength);
            }
            Ok(IpAddr::V6(mask_v6(v6, prefix)))
        }
    }
}

fn mask_v4(addr: Ipv4Addr, prefix: u8) -> Ipv4Addr {
    let bits = u32::from(addr);
    let mask = if prefix == 0 {
        0
    } else {
        u32::MAX << (32 - u32::from(prefix))
    };
    Ipv4Addr::from(bits & mask)
}

fn mask_v6(addr: Ipv6Addr, prefix: u8) -> Ipv6Addr {
    let bits = u128::from(addr);
    let mask = if prefix == 0 {
        0
    } else {
        u128::MAX << (128 - u32::from(prefix))
    };
    Ipv6Addr::from(bits & mask)
}

/// A JSON number preserving integer/unsigned/float distinctions.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum JsonNumber {
    I64(i64),
    U64(u64),
    F64(f64),
}

/// An ordered JSON value (A12).
#[derive(Debug, Clone, PartialEq)]
pub enum JsonValue {
    Null,
    Bool(bool),
    Number(JsonNumber),
    String(String),
    Array(Vec<JsonValue>),
    Object(Vec<(String, JsonValue)>),
}

impl JsonValue {
    #[must_use]
    pub fn max_depth(&self) -> usize {
        match self {
            Self::Array(values) => 1 + values.iter().map(Self::max_depth).max().unwrap_or(0),
            Self::Object(entries) => {
                1 + entries
                    .iter()
                    .map(|(_, v)| v.max_depth())
                    .max()
                    .unwrap_or(0)
            }
            _ => 0,
        }
    }

    #[must_use]
    pub fn approx_size(&self) -> usize {
        match self {
            Self::Null => 1,
            Self::Bool(_) => 1,
            Self::Number(_) => 8,
            Self::String(value) => value.len() + 4,
            Self::Array(values) => 2 + values.iter().map(Self::approx_size).sum::<usize>(),
            Self::Object(entries) => {
                2 + entries
                    .iter()
                    .map(|(k, v)| k.len() + 4 + v.approx_size())
                    .sum::<usize>()
            }
        }
    }
}

/// A typed field value (A03).
#[derive(Debug, Clone, PartialEq)]
pub enum FieldValue {
    Text(String),
    Keyword(String),
    Bool(bool),
    I64(i64),
    U64(u64),
    F64(f64),
    Timestamp(Timestamp),
    Json(JsonValue),
    GeoPoint(GeoPoint),
    Ip(IpAddr),
    Cidr(IpNetwork),
}

impl FieldValue {
    #[must_use]
    pub const fn field_type(&self) -> FieldType {
        match self {
            Self::Text(_) => FieldType::Text,
            Self::Keyword(_) => FieldType::Keyword,
            Self::Bool(_) => FieldType::Bool,
            Self::I64(_) => FieldType::I64,
            Self::U64(_) => FieldType::U64,
            Self::F64(_) => FieldType::F64,
            Self::Timestamp(_) => FieldType::Timestamp,
            Self::Json(_) => FieldType::Json,
            Self::GeoPoint(_) => FieldType::GeoPoint,
            Self::Ip(_) => FieldType::IpAddress,
            Self::Cidr(_) => FieldType::IpNetwork,
        }
    }

    /// Validates invariants that a public struct literal could otherwise bypass
    /// (currently non-finite floats and JSON value validity).
    pub fn validate(&self) -> Result<(), ValueError> {
        match self {
            Self::F64(value) if !value.is_finite() => Err(ValueError::NonFiniteFloat),
            Self::Json(value) => {
                if json_has_non_finite(value) {
                    Err(ValueError::NonFiniteFloat)
                } else {
                    Ok(())
                }
            }
            _ => Ok(()),
        }
    }

    #[must_use]
    pub fn approx_size(&self) -> usize {
        match self {
            Self::Text(value) | Self::Keyword(value) => value.len() + 4,
            Self::Bool(_) => 1,
            Self::I64(_) | Self::U64(_) | Self::F64(_) | Self::Timestamp(_) => 8,
            Self::Json(value) => value.approx_size(),
            Self::GeoPoint(_) => 16,
            Self::Ip(_) => 16,
            Self::Cidr(_) => 17,
        }
    }
}

fn json_has_non_finite(value: &JsonValue) -> bool {
    let mut stack = vec![value];
    while let Some(current) = stack.pop() {
        match current {
            JsonValue::Number(JsonNumber::F64(number)) if !number.is_finite() => return true,
            JsonValue::Array(values) => stack.extend(values),
            JsonValue::Object(entries) => stack.extend(entries.iter().map(|(_, v)| v)),
            _ => {}
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ipv4_cidr_boundaries() {
        let all = IpNetwork::new(IpAddr::V4(Ipv4Addr::new(0, 0, 0, 0)), 0).unwrap();
        assert!(all.contains(&IpAddr::V4(Ipv4Addr::new(203, 0, 113, 7))));
        assert!(!all.contains(&"2001:db8::1".parse().unwrap()));
        let host = IpNetwork::new(IpAddr::V4(Ipv4Addr::new(192, 0, 2, 7)), 32).unwrap();
        assert!(host.contains(&IpAddr::V4(Ipv4Addr::new(192, 0, 2, 7))));
        assert!(!host.contains(&IpAddr::V4(Ipv4Addr::new(192, 0, 2, 8))));
    }

    #[test]
    fn ipv6_cidr_boundaries_and_host_bits() {
        let all = IpNetwork::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), 0).unwrap();
        assert!(all.contains(&"2001:db8::1".parse().unwrap()));
        assert!(!all.contains(&IpAddr::V4(Ipv4Addr::LOCALHOST)));
        let host = IpNetwork::new("2001:db8::1".parse().unwrap(), 128).unwrap();
        assert!(host.contains(&"2001:db8::1".parse().unwrap()));
        assert!(IpNetwork::new("192.0.2.1".parse().unwrap(), 24).is_err());
        let masked = IpNetwork::new_masked("192.0.2.1".parse().unwrap(), 24).unwrap();
        assert_eq!(masked.addr(), "192.0.2.0".parse::<IpAddr>().unwrap());
        assert!(IpNetwork::new("192.0.2.1".parse().unwrap(), 33).is_err());
    }

    #[test]
    fn ipv4_mapped_ipv6_is_not_normalized() {
        let mapped: IpAddr = "::ffff:192.0.2.1".parse().unwrap();
        assert!(matches!(mapped, IpAddr::V6(_)));
        assert_eq!(FieldValue::Ip(mapped).field_type(), FieldType::IpAddress);
    }

    #[test]
    fn timestamp_floor_and_millis() {
        assert_eq!(Timestamp::from_nanos_floor(-1).as_micros(), -1);
        assert_eq!(Timestamp::from_nanos_floor(1_999).as_micros(), 1);
        assert_eq!(Timestamp::from_millis(2).as_micros(), 2_000);
    }

    #[test]
    fn geo_point_validation() {
        assert!(GeoPoint::new(-122.4, 37.8).is_ok());
        assert_eq!(GeoPoint::new(200.0, 0.0), Err(ValueError::InvalidLongitude));
        assert_eq!(GeoPoint::new(0.0, 91.0), Err(ValueError::InvalidLatitude));
        assert_eq!(
            GeoPoint::new(f64::NAN, 0.0),
            Err(ValueError::NonFiniteFloat)
        );
    }

    #[test]
    fn json_depth_and_size() {
        let value = JsonValue::Array(vec![JsonValue::Object(vec![(
            "a".into(),
            JsonValue::Array(vec![JsonValue::Null]),
        )])]);
        assert_eq!(value.max_depth(), 3);
        assert!(value.approx_size() > 0);
    }

    #[test]
    fn field_value_validation_rejects_non_finite() {
        assert!(FieldValue::F64(f64::NAN).validate().is_err());
        assert!(FieldValue::F64(1.5).validate().is_ok());
        assert!(
            FieldValue::Json(JsonValue::Array(vec![JsonValue::Number(JsonNumber::F64(
                f64::INFINITY
            ))]))
            .validate()
            .is_err()
        );
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;

    #[test]
    fn approx_sizes_and_types() {
        let values = vec![
            FieldValue::Text("abcd".into()),
            FieldValue::Keyword("abcd".into()),
            FieldValue::Bool(true),
            FieldValue::I64(-1),
            FieldValue::U64(1),
            FieldValue::F64(1.0),
            FieldValue::Timestamp(Timestamp::from_micros(1)),
            FieldValue::Json(JsonValue::Object(vec![(
                "k".into(),
                JsonValue::Bool(false),
            )])),
            FieldValue::GeoPoint(GeoPoint::new(0.0, 0.0).unwrap()),
            FieldValue::Ip("10.0.0.1".parse().unwrap()),
            FieldValue::Cidr(IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap()),
        ];
        let types: Vec<FieldType> = values.iter().map(FieldValue::field_type).collect();
        assert_eq!(
            types,
            vec![
                FieldType::Text,
                FieldType::Keyword,
                FieldType::Bool,
                FieldType::I64,
                FieldType::U64,
                FieldType::F64,
                FieldType::Timestamp,
                FieldType::Json,
                FieldType::GeoPoint,
                FieldType::IpAddress,
                FieldType::IpNetwork,
            ]
        );
        assert!(values.iter().all(|value| value.approx_size() > 0));
        assert!(FieldType::I64.is_numeric());
        assert!(FieldType::Text.is_lexical());
    }

    #[test]
    fn json_depth_variants() {
        assert_eq!(JsonValue::Null.max_depth(), 0);
        assert_eq!(JsonValue::Bool(true).max_depth(), 0);
        assert_eq!(JsonValue::Number(JsonNumber::U64(1)).max_depth(), 0);
        assert_eq!(JsonValue::String("x".into()).max_depth(), 0);
        assert_eq!(JsonValue::Array(vec![]).max_depth(), 1);
        assert_eq!(JsonValue::Object(vec![]).max_depth(), 1);
        assert_eq!(JsonValue::Array(vec![JsonValue::Null]).approx_size(), 3);
    }

    #[test]
    fn network_masked_mismatch_and_errors() {
        assert!(IpNetwork::new_masked("2001:db8::1".parse().unwrap(), 200).is_err());
        assert!(IpNetwork::new("10.0.0.1".parse().unwrap(), 8).is_err());
        let net = IpNetwork::new_masked("2001:db8::1".parse().unwrap(), 32).unwrap();
        assert_eq!(net.prefix(), 32);
        assert_eq!(net.addr(), "2001:db8::".parse::<IpAddr>().unwrap());
    }

    #[test]
    fn field_value_validation_paths() {
        assert!(FieldValue::Text("x".into()).validate().is_ok());
        assert!(FieldValue::Json(JsonValue::Null).validate().is_ok());
        assert!(
            FieldValue::Json(JsonValue::Object(vec![(
                "k".into(),
                JsonValue::Number(JsonNumber::F64(f64::NAN))
            )]))
            .validate()
            .is_err()
        );
        assert_eq!(FieldValue::Json(JsonValue::Null).validate(), Ok(()));
    }

    #[test]
    fn timestamp_conversions() {
        assert_eq!(Timestamp::from_nanos_floor(2_500).as_micros(), 2);
        assert_eq!(Timestamp::from_millis(-2).as_micros(), -2_000);
        assert_eq!(Timestamp::from_micros(7).as_micros(), 7);
        assert_eq!(GeoPoint::new(0.0, 0.0).unwrap().lat(), 0.0);
        assert_eq!(GeoPoint::new(1.5, 2.5).unwrap().lon(), 1.5);
    }
}
