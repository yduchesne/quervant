//! Shared PR 12 GeoPoint integration helpers and an independent brute-force
//! oracle that never calls the production KD tree or geometry code.
#![allow(dead_code)]

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::{GeoBoundingBox, GeoPolygon, GeoRadius, Query};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint, JsonNumber, JsonValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{SearchLimits, TypedSearchRequest, TypedSearchResponse, TypedSearcher};
use quervant_core::storage::{Directory, MemoryDirectory};

pub use quervant_core::contract::result::{Sort, SortDirection, SortField, TopK};

pub const R: f64 = 6_371_008.8;

pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// PR 12 fixture schema: single and multi GeoPoint, text, JSON and timestamp.
pub fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "single_loc",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "body",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::new(true, true, false),
            ),
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
        ],
        None,
    )
    .expect("pr12 schema")
}

pub fn memory() -> Arc<dyn Directory> {
    Arc::new(MemoryDirectory::new())
}

pub fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create(directory, schema(), registry()).expect("create index")
}

pub fn reopen(directory: Arc<dyn Directory>) -> Index {
    Index::open_existing(directory, schema(), registry()).expect("reopen index")
}

pub fn point(lon: f64, lat: f64) -> GeoPoint {
    GeoPoint::new(lon, lat).expect("valid point")
}

pub fn doc(key: &str) -> Document {
    Document::new(DocumentKey::new(key).unwrap())
}

pub fn set(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("insert single");
}

pub fn set_multi(document: &mut Document, field: &str, values: Vec<FieldValue>) {
    document
        .insert(field, FieldValues::Multi(values))
        .expect("insert multi");
}

pub fn set_null(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::ExplicitNull)
        .expect("insert null");
}

pub fn set_empty(document: &mut Document, field: &str) {
    document
        .insert(field, FieldValues::Empty)
        .expect("insert empty");
}

pub fn geo_doc(key: &str, locations: &[(f64, f64)]) -> Document {
    let mut document = doc(key);
    set(
        &mut document,
        "title",
        FieldValue::Text(format!("doc {key}")),
    );
    set(&mut document, "tag", FieldValue::Keyword("all".to_owned()));
    if !locations.is_empty() {
        set_multi(
            &mut document,
            "loc",
            locations
                .iter()
                .map(|(lon, lat)| FieldValue::GeoPoint(point(*lon, *lat)))
                .collect(),
        );
    }
    document
}

pub fn single_geo_doc(key: &str, location: (f64, f64)) -> Document {
    let mut document = geo_doc(key, &[]);
    set(
        &mut document,
        "single_loc",
        FieldValue::GeoPoint(point(location.0, location.1)),
    );
    document
}

pub fn committed(docs: Vec<Document>) -> (Arc<dyn Directory>, Index) {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in docs {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let reopened = reopen(Arc::clone(&directory));
    (directory, reopened)
}

pub fn typed_search(
    snapshot: &ReaderSnapshot,
    request: &TypedSearchRequest,
) -> TypedSearchResponse {
    let schema = schema();
    let cancel = CancellationFlag::new();
    TypedSearcher::new(snapshot, &schema, SearchLimits::default())
        .search(request, &Budgets::new(), &cancel)
        .expect("typed search")
}

pub fn search(snapshot: &ReaderSnapshot, query: Query, sort: Sort) -> Vec<String> {
    request_hits(snapshot, request(query, sort, 1000))
}

pub fn request(query: Query, sort: Sort, top_k: usize) -> TypedSearchRequest {
    TypedSearchRequest {
        query,
        sort,
        top_k: TopK::new(top_k).unwrap(),
        after: None,
        primary_time_field: None,
    }
}

pub fn request_hits(snapshot: &ReaderSnapshot, req: TypedSearchRequest) -> Vec<String> {
    typed_search(snapshot, &req)
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

pub fn bbox(west: f64, south: f64, east: f64, north: f64) -> Query {
    Query::GeoBoundingBox {
        field: "loc".to_owned(),
        bbox: GeoBoundingBox::new(west, south, east, north).unwrap(),
    }
}

pub fn bbox_field(field: &str, west: f64, south: f64, east: f64, north: f64) -> Query {
    Query::GeoBoundingBox {
        field: field.to_owned(),
        bbox: GeoBoundingBox::new(west, south, east, north).unwrap(),
    }
}

pub fn radius(center: (f64, f64), meters: f64) -> Query {
    Query::GeoRadius {
        field: "loc".to_owned(),
        radius: GeoRadius::new(point(center.0, center.1), meters).unwrap(),
    }
}

pub fn polygon(outer: &[(f64, f64)], holes: &[&[(f64, f64)]]) -> Query {
    Query::GeoPolygon {
        field: "loc".to_owned(),
        polygon: GeoPolygon::new(
            outer.iter().map(|(lon, lat)| point(*lon, *lat)).collect(),
            holes
                .iter()
                .map(|ring| ring.iter().map(|(lon, lat)| point(*lon, *lat)).collect())
                .collect(),
        )
        .unwrap(),
    }
}

pub fn distance_sort(origin: (f64, f64)) -> Sort {
    Sort::new(vec![SortField::geo_distance(
        "loc",
        point(origin.0, origin.1),
        SortDirection::Asc,
    )])
}

pub fn match_all() -> Query {
    Query::MatchAll
}

// ---------------------------------------------------------------------------
// Independent brute-force oracle (no production geometry or KD code).
// ---------------------------------------------------------------------------

/// Exact independent bounding-box longitude membership via canonical closed
/// intervals. This is a separate implementation from the production predicate
/// and contains no tolerance.
pub fn oracle_lon_in_intervals(lon: f64, intervals: &[(f64, f64)]) -> bool {
    if intervals.iter().any(|(lo, hi)| lon >= *lo && lon <= *hi) {
        return true;
    }
    if lon == 180.0 {
        intervals
            .iter()
            .any(|(lo, hi)| -180.0 >= *lo && -180.0 <= *hi)
    } else if lon == -180.0 {
        intervals
            .iter()
            .any(|(lo, hi)| 180.0 >= *lo && 180.0 <= *hi)
    } else {
        false
    }
}

pub fn oracle_bbox_intervals(west: f64, east: f64) -> ([(f64, f64); 2], usize) {
    if west > east {
        ([(west, 180.0), (-180.0, east)], 2)
    } else {
        ([(west, east), (0.0, 0.0)], 1)
    }
}

pub fn oracle_bbox_contains(point: (f64, f64), bbox: (f64, f64, f64, f64)) -> bool {
    let (west, south, east, north) = bbox;
    if point.1 < south || point.1 > north {
        return false;
    }
    let (intervals, len) = oracle_bbox_intervals(west, east);
    oracle_lon_in_intervals(point.0, &intervals[..len])
}

pub fn oracle_haversine(a: (f64, f64), b: (f64, f64)) -> f64 {
    let phi1 = a.1.to_radians();
    let phi2 = b.1.to_radians();
    let d_phi = (b.1 - a.1).to_radians();
    let mut d_lon = b.0 - a.0;
    if d_lon > 180.0 {
        d_lon -= 360.0;
    } else if d_lon < -180.0 {
        d_lon += 360.0;
    }
    let d_lambda = d_lon.to_radians();
    let h = (d_phi / 2.0).sin().powi(2) + phi1.cos() * phi2.cos() * (d_lambda / 2.0).sin().powi(2);
    2.0 * R * h.clamp(0.0, 1.0).sqrt().asin()
}

// ---------------------------------------------------------------------------
// Integer-grid polygon reference (exact for dyadic coordinates).
// ---------------------------------------------------------------------------

/// Number of grid units per degree. Coordinates are represented as exact
/// integer multiples of `1 / GRID_SCALE`.
pub const GRID_SCALE: f64 = 1024.0;

/// Quantize an exactly-dyadic coordinate to grid units.
pub fn to_grid(value: f64) -> i128 {
    (value * GRID_SCALE).round() as i128
}

/// Exact `i128` orientation: positive CCW, negative CW, zero collinear.
pub fn integer_orient(a: (i128, i128), b: (i128, i128), c: (i128, i128)) -> i128 {
    (b.0 - a.0) * (c.1 - a.1) - (b.1 - a.1) * (c.0 - a.0)
}

fn integer_on_segment(p: (i128, i128), a: (i128, i128), b: (i128, i128)) -> bool {
    integer_orient(a, b, p) == 0
        && p.0 >= a.0.min(b.0)
        && p.0 <= a.0.max(b.0)
        && p.1 >= a.1.min(b.1)
        && p.1 <= a.1.max(b.1)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum IntegerRingPosition {
    Inside,
    Outside,
    Boundary,
}

fn integer_ring_position(p: (i128, i128), ring: &[(i128, i128)]) -> IntegerRingPosition {
    let mut inside = false;
    let n = ring.len();
    if n < 3 {
        return IntegerRingPosition::Outside;
    }
    for index in 0..n {
        let a = ring[index];
        let b = ring[(index + 1) % n];
        if integer_on_segment(p, a, b) {
            return IntegerRingPosition::Boundary;
        }
        if (a.1 > p.1) != (b.1 > p.1) {
            let orientation = integer_orient(a, b, p);
            let crosses_right = if a.1 < b.1 {
                orientation > 0
            } else {
                orientation < 0
            };
            if crosses_right {
                inside = !inside;
            }
        }
    }
    if inside {
        IntegerRingPosition::Inside
    } else {
        IntegerRingPosition::Outside
    }
}

/// Exact integer-grid polygon containment: outer boundary inside, hole boundary
/// and interior excluded.
pub fn integer_polygon_contains(
    point: (i128, i128),
    outer: &[(i128, i128)],
    holes: &[Vec<(i128, i128)>],
) -> bool {
    match integer_ring_position(point, outer) {
        IntegerRingPosition::Outside => false,
        IntegerRingPosition::Boundary => true,
        IntegerRingPosition::Inside => {
            for hole in holes {
                match integer_ring_position(point, hole) {
                    IntegerRingPosition::Outside => {}
                    IntegerRingPosition::Boundary | IntegerRingPosition::Inside => return false,
                }
            }
            true
        }
    }
}

pub fn to_grid_ring(ring: &[(f64, f64)]) -> Vec<(i128, i128)> {
    ring.iter()
        .map(|(x, y)| (to_grid(*x), to_grid(*y)))
        .collect()
}

/// Deterministic point set for one document.
pub type DocPoints = Vec<(String, Vec<(f64, f64)>)>;

pub fn oracle_bbox_keys(points: &DocPoints, bbox: (f64, f64, f64, f64)) -> Vec<String> {
    let mut keys: Vec<String> = points
        .iter()
        .filter(|(_, values)| values.iter().any(|p| oracle_bbox_contains(*p, bbox)))
        .map(|(key, _)| key.clone())
        .collect();
    keys.sort();
    keys
}

pub fn oracle_radius_keys(points: &DocPoints, center: (f64, f64), meters: f64) -> Vec<String> {
    let mut keys: Vec<String> = points
        .iter()
        .filter(|(_, values)| {
            values
                .iter()
                .any(|p| oracle_haversine(center, *p) <= meters)
        })
        .map(|(key, _)| key.clone())
        .collect();
    keys.sort();
    keys
}

pub fn oracle_polygon_keys(
    points: &DocPoints,
    outer: &[(f64, f64)],
    holes: &[Vec<(f64, f64)>],
) -> Vec<String> {
    let outer_grid = to_grid_ring(outer);
    let holes_grid: Vec<Vec<(i128, i128)>> = holes.iter().map(|ring| to_grid_ring(ring)).collect();
    let mut keys: Vec<String> = points
        .iter()
        .filter(|(_, values)| {
            values.iter().any(|p| {
                integer_polygon_contains((to_grid(p.0), to_grid(p.1)), &outer_grid, &holes_grid)
            })
        })
        .map(|(key, _)| key.clone())
        .collect();
    keys.sort();
    keys
}

/// A tiny deterministic SplitMix64 generator for reproducible property cases.
pub struct SplitMix64(u64);

impl SplitMix64 {
    pub fn new(seed: u64) -> Self {
        Self(seed)
    }

    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    pub fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }

    pub fn range_i64(&mut self, low: i64, high: i64) -> i64 {
        low + (self.next_u64() % ((high - low + 1).max(1) as u64)) as i64
    }
}

pub fn json_point(value: &JsonValue) -> FieldValue {
    FieldValue::Json(value.clone())
}

pub fn point_json(lon: f64, lat: f64) -> JsonValue {
    JsonValue::Object(vec![
        ("type".into(), JsonValue::String("Point".into())),
        (
            "coordinates".into(),
            JsonValue::Array(vec![
                JsonValue::Number(JsonNumber::F64(lon)),
                JsonValue::Number(JsonNumber::F64(lat)),
            ]),
        ),
    ])
}
