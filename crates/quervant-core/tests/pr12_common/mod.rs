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

pub fn arc_contains(lon: f64, west: f64, span: f64) -> bool {
    if span >= 360.0 - 1e-12 {
        return true;
    }
    let delta = (lon - west).rem_euclid(360.0);
    delta <= span + 1e-9
}

pub fn oracle_bbox_contains(point: (f64, f64), bbox: (f64, f64, f64, f64)) -> bool {
    let (west, south, east, north) = bbox;
    if point.1 < south || point.1 > north {
        return false;
    }
    let span = if east >= west {
        east - west
    } else {
        east - west + 360.0
    };
    arc_contains(point.0, west, span)
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

fn on_segment(px: f64, py: f64, a: (f64, f64), b: (f64, f64)) -> bool {
    let cross = (b.0 - a.0) * (py - a.1) - (b.1 - a.1) * (px - a.0);
    let scale = 1.0 + (b.0 - a.0).abs() + (b.1 - a.1).abs() + (px - a.0).abs() + (py - a.1).abs();
    if cross.abs() > 1e-10 * scale {
        return false;
    }
    px >= a.0.min(b.0) - 1e-9
        && px <= a.0.max(b.0) + 1e-9
        && py >= a.1.min(b.1) - 1e-9
        && py <= a.1.max(b.1) + 1e-9
}

fn ring_position(px: f64, py: f64, ring: &[(f64, f64)]) -> u8 {
    let mut inside = false;
    let n = ring.len();
    for index in 0..n {
        let a = ring[index];
        let b = ring[(index + 1) % n];
        if on_segment(px, py, a, b) {
            return 1; // boundary
        }
        if (a.1 > py) != (b.1 > py) {
            let t = (py - a.1) / (b.1 - a.1);
            let x = a.0 + t * (b.0 - a.0);
            if px < x {
                inside = !inside;
            }
        }
    }
    if inside { 2 } else { 0 }
}

pub fn oracle_polygon_contains(
    point: (f64, f64),
    outer: &[(f64, f64)],
    holes: &[Vec<(f64, f64)>],
) -> bool {
    match ring_position(point.0, point.1, outer) {
        0 => false,
        1 => true,
        _ => {
            for hole in holes {
                if ring_position(point.0, point.1, hole) != 0 {
                    return false;
                }
            }
            true
        }
    }
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
    let mut keys: Vec<String> = points
        .iter()
        .filter(|(_, values)| {
            values
                .iter()
                .any(|p| oracle_polygon_contains(*p, outer, holes))
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
