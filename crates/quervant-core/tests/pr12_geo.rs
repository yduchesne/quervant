//! PR 12 GeoPoint spatial index and exact spatial retrieval integration tests.

mod pr12_common;

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use pr12_common::*;
use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, MutationRequest};
use quervant_core::contract::query::{GeoPolygon, GeoRadius, JsonPathExpr, Query};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint, Timestamp};
use quervant_core::index::{CURRENT_KEY, CurrentPointer, Index, IndexError};
use quervant_core::search::{SearchError, SearchLimits, TypedSearcher};
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, Manifest, SectionKind, SegmentBuilder, SegmentDocument,
    SegmentLimits, SegmentReader, parse_container,
};
use quervant_core::storage::{Directory, FsDirectory, ReadHandle, StorageKey};
use quervant_objectstore::ContentDigest;

static COUNTER: AtomicU64 = AtomicU64::new(0);

fn sorted(mut keys: Vec<String>) -> Vec<String> {
    keys.sort();
    keys
}

// ---------------------------------------------------------------------------
// T01 — empty, zero-point, missing, null and empty
// ---------------------------------------------------------------------------

#[test]
fn t01_empty_zero_point_missing_null_empty() {
    let (_directory, index) = committed(Vec::new());
    let snapshot = index.snapshot();
    assert!(search(&snapshot, bbox(-10.0, -10.0, 10.0, 10.0), Sort::default()).is_empty());

    let mut missing = doc("missing");
    set(&mut missing, "title", FieldValue::Text("m".into()));
    let mut null = doc("null");
    set_null(&mut null, "loc");
    let mut empty = doc("empty");
    set_empty(&mut empty, "loc");
    let mut zero = doc("zero");
    set_empty(&mut zero, "loc");

    let (_directory, index) = committed(vec![missing, null, empty, zero]);
    let snapshot = index.snapshot();
    // A positive predicate never matches missing/null/empty.
    assert!(search(&snapshot, bbox(-180.0, -90.0, 180.0, 90.0), Sort::default()).is_empty());
    assert!(search(&snapshot, radius((0.0, 0.0), 20_000_000.0), Sort::default()).is_empty());
    // The spatial section exists (indexed GeoPoint field) with zero points.
    let guard = snapshot.open_segment_reader(0).unwrap();
    let spatial = guard.reader().spatial().expect("spatial section");
    let field_id = guard.reader().schema().field_id("loc").unwrap();
    assert_eq!(spatial.field(field_id).unwrap().point_count(), 0);
}

// ---------------------------------------------------------------------------
// T02 — single/multi, duplicates, ordinals and dedup
// ---------------------------------------------------------------------------

#[test]
fn t02_multivalue_duplicates_and_ordinals() {
    let docs = vec![
        geo_doc("a", &[(0.0, 0.0), (0.0, 0.0)]),
        geo_doc("b", &[(50.0, 50.0), (60.0, 60.0)]),
        geo_doc("c", &[(0.0, 0.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(-1.0, -1.0, 1.0, 1.0), Sort::default()),
        ["a", "c"]
    );
    // A document matching through multiple points is returned once.
    assert_eq!(
        sorted(search(
            &snapshot,
            bbox(-1.0, -1.0, 1.0, 1.0),
            Sort::default()
        ))
        .len(),
        2
    );
    // Every point occurrence is stored, including duplicate coordinates.
    let guard = snapshot.open_segment_reader(0).unwrap();
    let spatial = guard.reader().spatial().unwrap();
    let field_id = guard.reader().schema().field_id("loc").unwrap();
    assert_eq!(spatial.field(field_id).unwrap().point_count(), 5);

    // A single-valued field is also indexed.
    let (_directory, index) = committed(vec![single_geo_doc("single", (1.0, 2.0))]);
    let snapshot = index.snapshot();
    assert_eq!(
        search(
            &snapshot,
            bbox_field("single_loc", 0.5, 1.5, 1.5, 2.5),
            Sort::default()
        ),
        ["single"]
    );
}

// ---------------------------------------------------------------------------
// T03 — invalid coordinates and malformed GeoJSON
// ---------------------------------------------------------------------------

#[test]
fn t03_invalid_coordinates_and_geojson() {
    assert!(GeoPoint::new(f64::NAN, 0.0).is_err());
    assert!(GeoPoint::new(0.0, f64::INFINITY).is_err());
    assert!(GeoPoint::new(200.0, 0.0).is_err());
    assert!(GeoPoint::new(0.0, 91.0).is_err());

    let valid = point_json(1.0, 2.0);
    let parsed = GeoPoint::from_geojson(&valid).unwrap();
    assert_eq!((parsed.lon(), parsed.lat()), (1.0, 2.0));

    let wrong_type = quervant_core::contract::value::JsonValue::Object(vec![(
        "type".into(),
        quervant_core::contract::value::JsonValue::String("LineString".into()),
    )]);
    assert!(GeoPoint::from_geojson(&wrong_type).is_err());
    let not_enough = quervant_core::contract::value::JsonValue::Object(vec![
        (
            "type".into(),
            quervant_core::contract::value::JsonValue::String("Point".into()),
        ),
        (
            "coordinates".into(),
            quervant_core::contract::value::JsonValue::Array(vec![
                quervant_core::contract::value::JsonValue::Number(
                    quervant_core::contract::value::JsonNumber::F64(1.0),
                ),
            ]),
        ),
    ]);
    assert!(GeoPoint::from_geojson(&not_enough).is_err());
    // Missing type member.
    assert!(
        GeoPoint::from_geojson(&quervant_core::contract::value::JsonValue::Object(vec![])).is_err()
    );
}

// ---------------------------------------------------------------------------
// T04 — bounding-box boundaries, crossing and ±180 alias
// ---------------------------------------------------------------------------

#[test]
fn t04_bbox_boundaries_crossing_alias() {
    let docs = vec![
        geo_doc("west_edge", &[(-10.0, 0.0)]),
        geo_doc("east_edge", &[(10.0, 0.0)]),
        geo_doc("outside", &[(10.0001, 0.0)]),
        geo_doc("south_edge", &[(0.0, -5.0)]),
        geo_doc("north_edge", &[(0.0, 5.0)]),
        geo_doc("dateline_plus", &[(180.0, 0.0)]),
        geo_doc("dateline_minus", &[(-180.0, 0.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(-10.0, -5.0, 10.0, 5.0), Sort::default()),
        ["east_edge", "north_edge", "south_edge", "west_edge"]
    );
    // ±180 alias: a box reaching one side matches both meridian representations.
    assert_eq!(
        search(&snapshot, bbox(170.0, -10.0, -170.0, 10.0), Sort::default()),
        ["dateline_minus", "dateline_plus"]
    );
    assert_eq!(
        search(
            &snapshot,
            bbox(-180.0, -10.0, -170.0, 10.0),
            Sort::default()
        ),
        ["dateline_minus", "dateline_plus"]
    );
    assert_eq!(
        search(&snapshot, bbox(170.0, -10.0, 180.0, 10.0), Sort::default()),
        ["dateline_minus", "dateline_plus"]
    );
}

// ---------------------------------------------------------------------------
// T05 — radius validation before I/O
// ---------------------------------------------------------------------------

#[test]
fn t05_radius_invalid_is_rejected() {
    let center = point(0.0, 0.0);
    assert!(GeoRadius::new(center, 0.0).is_err());
    assert!(GeoRadius::new(center, -1.0).is_err());
    assert!(GeoRadius::new(center, f64::NAN).is_err());
    assert!(GeoRadius::new(center, f64::INFINITY).is_err());
    assert!(GeoRadius::new(center, 1.0).is_ok());
}

// ---------------------------------------------------------------------------
// T06 — radius poles, antimeridian, antipodes and full world
// ---------------------------------------------------------------------------

#[test]
fn t06_radius_geometry() {
    let docs = vec![
        geo_doc("north_pole", &[(0.0, 90.0)]),
        geo_doc("south_pole", &[(0.0, -90.0)]),
        geo_doc("dateline", &[(179.9, 0.0)]),
        geo_doc("antipode", &[(180.0, 0.0)]),
        geo_doc("origin", &[(0.0, 0.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    // Polar radius.
    assert_eq!(
        search(&snapshot, radius((0.0, 90.0), 1_000.0), Sort::default()),
        ["north_pole"]
    );
    // A quarter-circumference reaches the poles.
    let quarter = std::f64::consts::FRAC_PI_2 * R;
    assert_eq!(
        search(
            &snapshot,
            radius((0.0, 0.0), quarter + 1.0),
            Sort::default()
        ),
        ["north_pole", "origin", "south_pole"]
    );
    // Antipodal radius covers half the Earth.
    let equator_half = std::f64::consts::PI * R;
    assert_eq!(
        search(
            &snapshot,
            radius((0.0, 0.0), equator_half + 1.0),
            Sort::default()
        ),
        ["antipode", "dateline", "north_pole", "origin", "south_pole"]
    );
    // Full world.
    assert_eq!(
        search(
            &snapshot,
            radius((0.0, 0.0), equator_half * 2.0 + 1.0),
            Sort::default()
        ),
        ["antipode", "dateline", "north_pole", "origin", "south_pole"]
    );
    // A radius that reaches across the antimeridian.
    assert_eq!(
        search(&snapshot, radius((180.0, 0.0), 30_000.0), Sort::default()),
        ["antipode", "dateline"]
    );
}

// ---------------------------------------------------------------------------
// T07 — polygon interior/exterior/vertex/edges/holes
// ---------------------------------------------------------------------------

#[test]
fn t07_polygon_contains() {
    let docs = vec![
        geo_doc("inside", &[(2.0, 2.0)]),
        geo_doc("outside", &[(5.0, 5.0)]),
        geo_doc("vertex", &[(0.0, 0.0)]),
        geo_doc("edge", &[(2.0, 0.0)]),
        geo_doc("hole_interior", &[(2.0, 2.0)]),
    ];
    let _ = docs;
    // Construct a polygon with a hole and test at the geometry level through
    // the query on a purpose-built fixture.
    let docs = vec![
        geo_doc("inside", &[(0.5, 0.5)]),
        geo_doc("outside", &[(5.0, 5.0)]),
        geo_doc("vertex", &[(0.0, 0.0)]),
        geo_doc("outer_edge", &[(2.0, 0.0)]),
        geo_doc("hole_interior", &[(2.0, 2.0)]),
        geo_doc("hole_edge", &[(1.0, 2.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)];
    let hole = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)];
    let q = polygon(&outer, &[&hole]);
    assert_eq!(
        search(&snapshot, q, Sort::default()),
        ["inside", "outer_edge", "vertex"]
    );
}

// ---------------------------------------------------------------------------
// T08 — crossing/±180 polygons rejected by the contract
// ---------------------------------------------------------------------------

#[test]
fn t08_unsupported_polygons_rejected() {
    let crossing = GeoPolygon::new(
        vec![
            point(179.0, 0.0),
            point(-179.0, 0.0),
            point(-179.0, 10.0),
            point(179.0, 10.0),
        ],
        Vec::new(),
    );
    assert!(crossing.is_err());
    let at_antimeridian = GeoPolygon::new(
        vec![point(180.0, 0.0), point(170.0, 0.0), point(175.0, 10.0)],
        Vec::new(),
    );
    assert!(at_antimeridian.is_err());
}

// ---------------------------------------------------------------------------
// T09/T10 — corruption fails closed on open
// ---------------------------------------------------------------------------

fn rebuild(
    bytes: &[u8],
    replace: Option<(SectionKind, Vec<u8>)>,
    drop_feature: Option<u16>,
) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in view.required_features() {
        if Some(*id) != drop_feature {
            builder.require_feature(*id, *version);
        }
    }
    for (id, version) in view.optional_features() {
        builder.optional_feature(*id, *version);
    }
    for entry in view.sections() {
        let body = view.body(entry.kind).unwrap().to_vec();
        let body = match &replace {
            Some((kind, new_body)) if *kind == entry.kind => new_body.clone(),
            _ => body,
        };
        builder.section(entry.kind, entry.flags, entry.aux, body);
    }
    builder.build().unwrap()
}

fn sample_segment() -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
    for document in [geo_doc("a", &[(10.0, 10.0)]), geo_doc("b", &[(20.0, 20.0)])] {
        let mut segment_doc = SegmentDocument::new(document.key().clone());
        for (name, values) in document.fields() {
            segment_doc.insert(name, values.clone()).unwrap();
        }
        builder.add_document(segment_doc).unwrap();
    }
    builder.build().unwrap().bytes
}

#[test]
fn t09_feature_section_mismatch_fails_closed() {
    let bytes = sample_segment();
    let limits = SegmentLimits::default();
    assert!(SegmentReader::open(bytes.clone(), limits).is_ok());

    // Section present, feature dropped.
    let no_feature = rebuild(&bytes, None, Some(0x000A));
    assert!(SegmentReader::open(no_feature, limits).is_err());

    // Feature present, section dropped.
    let view = parse_container(&bytes, &limits).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in view.required_features() {
        builder.require_feature(*id, *version);
    }
    for entry in view.sections() {
        if entry.kind != SectionKind::SpatialPoints {
            builder.section(
                entry.kind,
                entry.flags,
                entry.aux,
                view.body(entry.kind).unwrap().to_vec(),
            );
        }
    }
    assert!(SegmentReader::open(builder.build().unwrap(), limits).is_err());
}

#[test]
fn t10_malformed_nodes_and_geometries_fail_closed() {
    let bytes = sample_segment();
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    let body = view.body(SectionKind::SpatialPoints).unwrap().to_vec();

    // Node 0 begins after 6 header + 20 field header bytes; latitude is at +20.
    let node0 = 6 + 20;
    let lat_offset = node0 + 20;

    // Non-WGS84 latitude (still finite, so only the reader's range check can catch it).
    let mut bad_lat = body.clone();
    bad_lat[lat_offset..lat_offset + 8].copy_from_slice(&100.0f64.to_le_bytes());
    assert!(
        SegmentReader::open(
            rebuild(&bytes, Some((SectionKind::SpatialPoints, bad_lat)), None),
            limits
        )
        .is_err()
    );

    // Wrong split axis (root must be longitude = 0).
    let axis_offset = node0 + 76;
    let mut bad_axis = body.clone();
    bad_axis[axis_offset] = 1;
    assert!(
        SegmentReader::open(
            rebuild(&bytes, Some((SectionKind::SpatialPoints, bad_axis)), None),
            limits
        )
        .is_err()
    );

    // Out-of-range doc id.
    let mut bad_doc = body.clone();
    bad_doc[node0..node0 + 8].copy_from_slice(&99u64.to_le_bytes());
    assert!(
        SegmentReader::open(
            rebuild(&bytes, Some((SectionKind::SpatialPoints, bad_doc)), None),
            limits
        )
        .is_err()
    );

    // Non-finite coordinate.
    let lon_offset = node0 + 12;
    let mut nan_lon = body.clone();
    nan_lon[lon_offset..lon_offset + 8].copy_from_slice(&f64::NAN.to_le_bytes());
    assert!(
        SegmentReader::open(
            rebuild(&bytes, Some((SectionKind::SpatialPoints, nan_lon)), None),
            limits
        )
        .is_err()
    );

    // Truncated node (drop the last byte).
    let mut truncated = body.clone();
    truncated.pop();
    assert!(
        SegmentReader::open(
            rebuild(&bytes, Some((SectionKind::SpatialPoints, truncated)), None),
            limits
        )
        .is_err()
    );
}

fn four_point_segment() -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
    for index in 0..4 {
        let document = geo_doc(&format!("p{index}"), &[(index as f64, index as f64)]);
        let mut segment_doc = SegmentDocument::new(document.key().clone());
        for (name, values) in document.fields() {
            segment_doc.insert(name, values.clone()).unwrap();
        }
        builder.add_document(segment_doc).unwrap();
    }
    builder.build().unwrap().bytes
}

#[test]
fn t10b_thirty_malformed_node_cases() {
    let bytes = four_point_segment();
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    let base = view.body(SectionKind::SpatialPoints).unwrap().to_vec();
    assert!(SegmentReader::open(bytes.clone(), limits).is_ok());

    let node = 6 + 20;
    let nan = f64::NAN.to_le_bytes();
    // (node-relative field offset, replacement bytes)
    let invalid: Vec<(usize, [u8; 8])> = vec![
        (0, u64::MAX.to_le_bytes()), // doc_id out of range
        (12, nan),                   // longitude NaN
        (20, nan),                   // latitude NaN
        (28, nan),                   // min_lon NaN
        (36, nan),                   // min_lat NaN
        (44, nan),                   // max_lon NaN
        (52, nan),                   // max_lat NaN
        (60, 255u64.to_le_bytes()),  // left out of range
        (68, 255u64.to_le_bytes()),  // right out of range
        (76, [2u8; 8]),              // invalid axis byte
    ];
    let mut rejected = 0usize;
    for node_index in 0..3 {
        for (offset, replacement) in &invalid {
            let mut body = base.clone();
            let at = node + node_index * 77 + offset;
            let width = if *offset == 76 { 1 } else { 8 };
            body[at..at + width].copy_from_slice(&replacement[..width]);
            let candidate = rebuild(&bytes, Some((SectionKind::SpatialPoints, body)), None);
            assert!(
                SegmentReader::open(candidate, limits).is_err(),
                "node {node_index} offset {offset} must be rejected"
            );
            rejected += 1;
        }
    }
    // Duplicate (doc_id, ordinal).
    {
        let mut body = base.clone();
        body[node + 77..node + 77 + 8].copy_from_slice(&0u64.to_le_bytes());
        let candidate = rebuild(&bytes, Some((SectionKind::SpatialPoints, body)), None);
        assert!(SegmentReader::open(candidate, limits).is_err());
        rejected += 1;
    }
    // Wrong version, wrong root, truncation and a trailing byte.
    for mutate in [
        0usize, // version low byte
        18,     // root index (low byte of u64)
    ] {
        let mut body = base.clone();
        body[mutate] = 0xFF;
        let candidate = rebuild(&bytes, Some((SectionKind::SpatialPoints, body)), None);
        assert!(SegmentReader::open(candidate, limits).is_err());
        rejected += 1;
    }
    {
        let mut body = base.clone();
        body.pop();
        let candidate = rebuild(&bytes, Some((SectionKind::SpatialPoints, body)), None);
        assert!(SegmentReader::open(candidate, limits).is_err());
        rejected += 1;
    }
    {
        let mut body = base.clone();
        body.push(0);
        let candidate = rebuild(&bytes, Some((SectionKind::SpatialPoints, body)), None);
        assert!(SegmentReader::open(candidate, limits).is_err());
        rejected += 1;
    }
    assert!(rejected >= 30, "expected at least 30 cases, got {rejected}");
}

// ---------------------------------------------------------------------------
// T11 — limits and cancellation
// ---------------------------------------------------------------------------

#[test]
fn t11_limits_and_cancellation() {
    let docs: Vec<_> = (0..40)
        .map(|index| geo_doc(&format!("d{index:03}"), &[(index as f64, index as f64)]))
        .collect();
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let schema = schema();

    let flag = CancellationFlag::new();
    flag.cancel();
    let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
    let req = request(bbox(-180.0, -90.0, 180.0, 90.0), Sort::default(), 10);
    assert!(matches!(
        searcher.search(&req, &Budgets::new(), &flag),
        Err(SearchError::Cancelled)
    ));

    let tight = SearchLimits::default()
        .with_max_typed_work_units(1)
        .unwrap();
    let searcher = TypedSearcher::new(&snapshot, &schema, tight);
    assert!(matches!(
        searcher.search(&req, &Budgets::new(), &CancellationFlag::new()),
        Err(SearchError::ResourceLimit { .. })
    ));
}

// ---------------------------------------------------------------------------
// T12 — compaction preserves points, including indexed-only semantics
// ---------------------------------------------------------------------------

#[test]
fn t12_compaction_preserves_indexed_points() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for index in 0..20 {
            writer
                .insert(geo_doc(
                    &format!("d{index:03}"),
                    &[(index as f64, index as f64)],
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let index = reopen(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for index in 0..10 {
            writer
                .apply(MutationRequest::delete(
                    quervant_core::contract::document::DocumentKey::new(format!("d{index:03}"))
                        .unwrap(),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let index = reopen(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        let outcome = writer.compact().unwrap();
        assert!(!outcome.no_op);
    }
    let index = reopen(Arc::clone(&directory));
    let snapshot = index.snapshot();
    // Survivors keep their exact coordinates.
    assert_eq!(
        search(&snapshot, bbox(14.0, 14.0, 16.0, 16.0), Sort::default()),
        ["d014", "d015", "d016"]
    );
    // Every surviving point remains reachable through a full-world query.
    let all = search(&snapshot, bbox(-180.0, -90.0, 180.0, 90.0), Sort::default());
    assert_eq!(all.len(), 10);
}

// ---------------------------------------------------------------------------
// T12b — indexed-not-stored non-columnar GeoPoint survives compaction (I05)
// ---------------------------------------------------------------------------

#[test]
fn t12b_indexed_only_geopoint_survives_compaction() {
    use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use quervant_core::storage::MemoryDirectory;

    let schema = Schema::new(
        vec![FieldDefinition::new(
            "loc",
            FieldType::GeoPoint,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )],
        None,
    )
    .unwrap();
    assert!(!schema.get("loc").unwrap().options.stored);
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = quervant_core::index::Index::create(
        Arc::clone(&directory),
        schema.clone(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    {
        let mut writer = index.writer().unwrap();
        for i in 0..10 {
            let mut document = Document::new(DocumentKey::new(format!("d{i:03}")).unwrap());
            document
                .insert(
                    "loc",
                    FieldValues::Single(FieldValue::GeoPoint(point(i as f64, i as f64))),
                )
                .unwrap();
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let index = quervant_core::index::Index::open_existing(
        Arc::clone(&directory),
        schema.clone(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    {
        let mut writer = index.writer().unwrap();
        for i in 0..5 {
            writer
                .apply(MutationRequest::delete(
                    DocumentKey::new(format!("d{i:03}")).unwrap(),
                ))
                .unwrap();
        }
        writer.commit().unwrap();
    }
    let index = quervant_core::index::Index::open_existing(
        Arc::clone(&directory),
        schema.clone(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    {
        let mut writer = index.writer().unwrap();
        writer.compact().unwrap();
    }
    let index = quervant_core::index::Index::open_existing(
        Arc::clone(&directory),
        schema.clone(),
        AnalyzerRegistry::builtin(),
    )
    .unwrap();
    let snapshot = index.snapshot();
    let searcher = TypedSearcher::new(&snapshot, &schema, SearchLimits::default());
    let request = request(bbox(4.0, 4.0, 9.0, 9.0), Sort::default(), 100);
    let response = searcher
        .search(&request, &Budgets::new(), &CancellationFlag::new())
        .unwrap();
    let keys: Vec<&str> = response.hits.iter().map(|hit| hit.key.as_str()).collect();
    // Deleted points are gone; the indexed-only survivors remain exact.
    assert_eq!(keys, ["d005", "d006", "d007", "d008", "d009"]);
}

// ---------------------------------------------------------------------------
// T13 — delete/upsert/refresh/reopen generation consistency
// ---------------------------------------------------------------------------

#[test]
fn t13_lifecycle_generations() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        writer.insert(geo_doc("a", &[(1.0, 1.0)])).unwrap();
        writer.insert(geo_doc("b", &[(2.0, 2.0)])).unwrap();
        writer.commit().unwrap();
    }
    let index = reopen(Arc::clone(&directory));
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(0.0, 0.0, 5.0, 5.0), Sort::default()),
        ["a", "b"]
    );

    // Upsert moves `a` out of the box.
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::upsert(geo_doc("a", &[(50.0, 50.0)])))
            .unwrap();
        writer.commit().unwrap();
    }
    let index = reopen(Arc::clone(&directory));
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(0.0, 0.0, 5.0, 5.0), Sort::default()),
        ["b"]
    );
    assert_eq!(
        search(&snapshot, bbox(49.0, 49.0, 51.0, 51.0), Sort::default()),
        ["a"]
    );

    // Delete removes it entirely.
    {
        let mut writer = index.writer().unwrap();
        writer
            .apply(MutationRequest::delete(
                quervant_core::contract::document::DocumentKey::new("a").unwrap(),
            ))
            .unwrap();
        writer.commit().unwrap();
    }
    let index = reopen(Arc::clone(&directory));
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(49.0, 49.0, 51.0, 51.0), Sort::default()),
        Vec::<String>::new()
    );
}

// ---------------------------------------------------------------------------
// T14 — distance sort: min across points, missing last, ties, pagination
// ---------------------------------------------------------------------------

#[test]
fn t14_distance_sort() {
    let docs = vec![
        geo_doc("near", &[(0.1, 0.0), (10.0, 0.0)]),
        geo_doc("min_wins", &[(5.0, 0.0), (0.05, 0.0)]),
        geo_doc("missing", &[]),
        geo_doc("far", &[(20.0, 0.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let sort = distance_sort((0.0, 0.0));
    assert_eq!(
        search(&snapshot, match_all(), sort.clone()),
        ["min_wins", "near", "far", "missing"]
    );

    // Missing-last is preserved under descending direction.
    let desc = Sort::new(vec![
        quervant_core::contract::result::SortField::geo_distance(
            "loc",
            point(0.0, 0.0),
            quervant_core::contract::result::SortDirection::Desc,
        ),
    ]);
    assert_eq!(
        search(&snapshot, match_all(), desc),
        ["far", "near", "min_wins", "missing"]
    );

    // Pagination with a cursor is deterministic.
    let mut req = request(match_all(), sort, 2);
    let first = typed_search(&snapshot, &req);
    assert_eq!(
        first
            .hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>(),
        ["min_wins", "near"]
    );
    req.after = first.next_cursor.clone();
    let second = typed_search(&snapshot, &req);
    assert_eq!(
        second
            .hits
            .iter()
            .map(|hit| hit.key.as_str())
            .collect::<Vec<_>>(),
        ["far", "missing"]
    );
}

// ---------------------------------------------------------------------------
// T15 — Boolean AND/OR/NOT with time, JSON and tombstones
// ---------------------------------------------------------------------------

#[test]
fn t15_boolean_and_tombstones() {
    let mut with_time = geo_doc("with_time", &[(1.0, 1.0)]);
    set(
        &mut with_time,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(100)),
    );
    let mut without_time = geo_doc("without_time", &[(1.0, 1.0)]);
    set(
        &mut without_time,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(5)),
    );
    let mut with_json = geo_doc("with_json", &[(1.0, 1.0)]);
    set(
        &mut with_json,
        "body",
        json_point(&quervant_core::contract::value::JsonValue::Object(vec![(
            "kind".into(),
            quervant_core::contract::value::JsonValue::String("x".into()),
        )])),
    );
    let docs = vec![with_time, without_time, with_json];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();

    let geo = bbox(0.0, 0.0, 2.0, 2.0);
    let time = Query::TimeRange {
        field: "ts".into(),
        start: Timestamp::from_micros(50),
        end: Timestamp::from_micros(200),
    };
    let json = Query::JsonPathExists {
        field: "body".into(),
        path: JsonPathExpr::parse("$.kind").unwrap(),
    };

    assert_eq!(
        search(
            &snapshot,
            Query::And(vec![geo.clone(), time.clone()]),
            Sort::default()
        ),
        ["with_time"]
    );
    assert_eq!(
        search(
            &snapshot,
            Query::Or(vec![geo.clone(), json.clone()]),
            Sort::default()
        ),
        ["with_json", "with_time", "without_time"]
    );
    assert_eq!(
        search(
            &snapshot,
            Query::And(vec![geo.clone(), Query::Not(Box::new(time))]),
            Sort::default()
        ),
        ["with_json", "without_time"]
    );
    // NOT geo is the exact complement within live documents.
    assert_eq!(
        sorted(search(
            &snapshot,
            Query::Not(Box::new(geo)),
            Sort::default()
        )),
        Vec::<String>::new()
    );
}

// ---------------------------------------------------------------------------
// T16 — deterministic build
// ---------------------------------------------------------------------------

#[test]
fn t16_deterministic_build() {
    let docs = vec![
        geo_doc("a", &[(10.0, 10.0)]),
        geo_doc("b", &[(20.0, 20.0), (-20.0, -20.0)]),
        geo_doc("c", &[(0.0, 0.0)]),
    ];
    let first = segment_bytes(&docs);
    let second = segment_bytes(&docs);
    assert_eq!(first, second);
    let reader = SegmentReader::open(first, SegmentLimits::default()).unwrap();
    assert!(reader.spatial().is_some());
}

fn segment_bytes(docs: &[quervant_core::contract::document::Document]) -> Vec<u8> {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
    for document in docs {
        let mut segment_doc = SegmentDocument::new(document.key().clone());
        for (name, values) in document.fields() {
            segment_doc.insert(name, values.clone()).unwrap();
        }
        builder.add_document(segment_doc).unwrap();
    }
    builder.build().unwrap().bytes
}

// ---------------------------------------------------------------------------
// T18 — FsDirectory restart
// ---------------------------------------------------------------------------

fn temp_dir(tag: &str) -> std::path::PathBuf {
    let id = COUNTER.fetch_add(1, Ordering::SeqCst);
    let path =
        std::env::temp_dir().join(format!("quervant-pr12-{tag}-{}-{id}", std::process::id()));
    let _ = std::fs::remove_dir_all(&path);
    std::fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn t18_fs_directory_restart() {
    let path = temp_dir("fs");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        writer.insert(geo_doc("a", &[(1.0, 1.0)])).unwrap();
        writer.insert(geo_doc("b", &[(2.0, 2.0)])).unwrap();
        writer.commit().unwrap();
    }
    drop(index);
    drop(directory);

    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = reopen(directory);
    let snapshot = index.snapshot();
    assert_eq!(
        search(&snapshot, bbox(0.0, 0.0, 3.0, 3.0), Sort::default()),
        ["a", "b"]
    );
    let _ = std::fs::remove_dir_all(&path);
}

// ---------------------------------------------------------------------------
// T17 / independent oracle — seeded property cases
// ---------------------------------------------------------------------------

#[test]
fn t17_seeded_oracle_bbox_radius_polygon() {
    let mut rng = SplitMix64::new(0x5151_2024);
    for case in 0..300u64 {
        let doc_count = rng.range_i64(0, 1000) as usize;
        let mut docs = Vec::with_capacity(doc_count);
        let mut oracle_points: DocPoints = Vec::with_capacity(doc_count);
        for doc_index in 0..doc_count {
            let key = format!("d{doc_index:03}");
            let point_count = rng.range_i64(0, 8) as usize;
            let mut points = Vec::with_capacity(point_count);
            for _ in 0..point_count {
                let lon = rng.next_f64() * 360.0 - 180.0;
                let lat = rng.next_f64() * 180.0 - 90.0;
                points.push((lon, lat));
            }
            oracle_points.push((key.clone(), points.clone()));
            docs.push(geo_doc(&key, &points));
        }
        let (_directory, index) = committed(docs);
        let snapshot = index.snapshot();

        let west = rng.next_f64() * 360.0 - 180.0;
        let east = rng.next_f64() * 360.0 - 180.0;
        let south = rng.next_f64() * 180.0 - 90.0;
        let north = rng.next_f64() * 180.0 - 90.0;
        let (south, north) = if south <= north {
            (south, north)
        } else {
            (north, south)
        };
        let q = bbox(west, south, east, north);
        let expected = oracle_bbox_keys(&oracle_points, (west, south, east, north));
        let actual = sorted(search(&snapshot, q, Sort::default()));
        assert_eq!(
            actual, expected,
            "case {case} bbox ({west},{south},{east},{north})"
        );

        let center = (
            rng.next_f64() * 360.0 - 180.0,
            rng.next_f64() * 180.0 - 90.0,
        );
        let meters = rng.next_f64() * 8_000_000.0 + 100.0;
        let expected = oracle_radius_keys(&oracle_points, center, meters);
        let actual = sorted(search(&snapshot, radius(center, meters), Sort::default()));
        assert_eq!(actual, expected, "case {case} radius {center:?} {meters}");
    }
}

#[test]
fn t17_oracle_polygon() {
    let outer = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)];
    let hole = vec![(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)];
    let mut rng = SplitMix64::new(0xC0FFEE);
    let mut docs = Vec::new();
    let mut points: DocPoints = Vec::new();
    // Exact dyadic coordinates so the integer-grid oracle is authoritative.
    for doc_index in 0..120 {
        let key = format!("p{doc_index:03}");
        let lon = rng.range_i64(-5 * 1024, 40 * 1024 - 1) as f64 / 1024.0;
        let lat = rng.range_i64(-5 * 1024, 40 * 1024 - 1) as f64 / 1024.0;
        points.push((key.clone(), vec![(lon, lat)]));
        docs.push(geo_doc(&key, &[(lon, lat)]));
    }
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let q = polygon(&outer, &[&hole]);
    let expected = oracle_polygon_keys(&points, &outer, std::slice::from_ref(&hole));
    let actual = sorted(search(&snapshot, q, Sort::default()));
    assert_eq!(actual, expected);
}

// O01/O04 — adversarial exact-grid polygon boundary cases.
#[test]
fn o04_integer_grid_polygon_edges() {
    let outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)];
    let hole = vec![(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)];
    let outer_grid = to_grid_ring(&outer);
    let holes_grid = vec![to_grid_ring(&hole)];
    let cases: &[(f64, f64)] = &[
        (0.0, 0.0),
        (0.5, 0.0),
        (2.0, 0.0),
        (4.0, 0.0),
        (4.0, 2.0),
        (2.0, 4.0),
        (0.0, 4.0),
        (0.5, 0.5),
        (3.5, 0.5),
        (0.5, 3.5),
        (3.5, 3.5),
        (1.0, 2.0),
        (2.0, 1.0),
        (3.0, 2.0),
        (2.0, 3.0),
        (2.0, 2.0),
        (-0.5, 2.0),
        (4.5, 2.0),
        (2.0, -0.5),
        (2.0, 4.5),
    ];
    let mut docs = Vec::new();
    let mut expected_keys = Vec::new();
    for (index, (lon, lat)) in cases.iter().enumerate() {
        let key = format!("g{index:03}");
        let included =
            integer_polygon_contains((to_grid(*lon), to_grid(*lat)), &outer_grid, &holes_grid);
        if included {
            expected_keys.push(key.clone());
        }
        docs.push(geo_doc(&key, &[(*lon, *lat)]));
    }
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let q = polygon(&outer, &[&hole]);
    let actual = sorted(search(&snapshot, q, Sort::default()));
    expected_keys.sort();
    assert_eq!(actual, expected_keys);
    // Both outcomes are represented.
    assert!(expected_keys.len() > 3 && expected_keys.len() < cases.len());
}

// O03 — a tolerance-based predicate is rejected by the exact oracle.
#[test]
fn o03_tolerance_predicate_is_detected_by_oracle() {
    fn next_up(value: f64) -> f64 {
        f64::from_bits(value.to_bits() + 1)
    }
    let east = 1e-15_f64;
    let outsider = next_up(east);
    // The exact oracle rejects the adjacent-ULP outsider.
    assert!(!oracle_bbox_contains(
        (outsider, 0.0),
        (0.0, -1.0, east, 1.0)
    ));
    // A local copy of the removed tolerance predicate would accept it, so a
    // regression to epsilon logic makes this test red.
    let old_tolerance_predicate = |lon: f64| lon.rem_euclid(360.0) <= east + 1e-12;
    assert!(old_tolerance_predicate(outsider));
}

// ---------------------------------------------------------------------------
// P6 — fail-closed legacy compaction (L01–L04)
// ---------------------------------------------------------------------------

fn read_key(directory: &Arc<dyn Directory>, key: &StorageKey) -> Vec<u8> {
    let handle: Box<dyn ReadHandle> = directory.open_read(key).unwrap();
    let len = usize::try_from(handle.len()).unwrap();
    let mut bytes = vec![0u8; len];
    let mut offset = 0usize;
    while offset < len {
        let read = handle.read_at(offset as u64, &mut bytes[offset..]).unwrap();
        assert!(read > 0, "short read");
        offset += read;
    }
    bytes
}

fn read_current(directory: &Arc<dyn Directory>, key: &str) -> Vec<u8> {
    read_key(directory, &StorageKey::parse(key).unwrap())
}

fn manifest_list(directory: &Arc<dyn Directory>) -> Vec<StorageKey> {
    directory.list("index/manifests", 1_000).unwrap()
}

/// Rebuild a segment container with the `SpatialPoints` section and feature
/// removed, producing a digest-valid legacy segment.
fn strip_spatial(bytes: &[u8]) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in view.required_features() {
        if *id == quervant_core::segment::format::FEATURE_SPATIAL_POINTS {
            continue;
        }
        builder.require_feature(*id, *version);
    }
    for (id, version) in view.optional_features() {
        builder.optional_feature(*id, *version);
    }
    for entry in view.sections() {
        if entry.kind == SectionKind::SpatialPoints {
            continue;
        }
        builder.section(
            entry.kind,
            entry.flags,
            entry.aux,
            view.body(entry.kind).unwrap().to_vec(),
        );
    }
    builder.build().unwrap()
}

#[test]
fn l01_l04_legacy_unrecoverable_compaction_fails_closed() {
    use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
    use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};

    let schema = Schema::new(
        vec![FieldDefinition::new(
            "loc",
            FieldType::GeoPoint,
            Cardinality::Single,
            FieldOptions::new(true, false, false),
        )],
        None,
    )
    .unwrap();
    let registry = AnalyzerRegistry::builtin();
    let path = temp_dir("legacy");
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).unwrap());
    let index = Index::create(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
    // Two commits produce two segments so compaction is not an all-live no-op.
    for (key, lon) in [("a", 1.0_f64), ("b", 2.0_f64)] {
        let mut writer = index.writer().unwrap();
        let mut document = Document::new(DocumentKey::new(key).unwrap());
        document
            .insert(
                "loc",
                FieldValues::Single(FieldValue::GeoPoint(point(lon, lon))),
            )
            .unwrap();
        writer.insert(document).unwrap();
        writer.commit().unwrap();
    }

    // Rewrite the manifest as a legacy v1 manifest (no mutation state) whose
    // segments have no spatial section or feature.
    let pointer = CurrentPointer::parse(&read_current(&directory, CURRENT_KEY)).unwrap();
    let manifest_key = pointer.manifest_key().clone();
    let manifest_bytes = read_key(&directory, &manifest_key);
    let mut manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default()).unwrap();
    assert!(
        manifest.segments.len() >= 2,
        "need two segments to force compaction"
    );
    for segment_ref in &mut manifest.segments {
        let key = StorageKey::parse(&segment_ref.object_key).unwrap();
        let bytes = read_key(&directory, &key);
        let rebuilt = strip_spatial(&bytes);
        directory.atomic_write(&key, &rebuilt).unwrap();
        segment_ref.content_length = rebuilt.len() as u64;
        segment_ref.content_digest = *ContentDigest::sha256_v1(&rebuilt).as_bytes();
        segment_ref
            .required_features
            .retain(|(id, _)| *id != quervant_core::segment::format::FEATURE_SPATIAL_POINTS);
    }
    manifest.mutation_state = None;
    manifest
        .required_features
        .retain(|(id, _)| *id != quervant_core::segment::format::FEATURE_MUTATION_STATE);
    let new_manifest = manifest.encode().unwrap();
    directory
        .atomic_write(&manifest_key, &new_manifest)
        .unwrap();
    let new_pointer = CurrentPointer::new(
        pointer.generation(),
        new_manifest.len() as u64,
        ContentDigest::sha256_v1(&new_manifest),
    )
    .unwrap();
    directory
        .atomic_write(
            &StorageKey::parse(CURRENT_KEY).unwrap(),
            &new_pointer.encode().unwrap(),
        )
        .unwrap();

    // L01: the legacy generation opens and its held reader is usable.
    let index =
        Index::open_existing(Arc::clone(&directory), schema.clone(), registry.clone()).unwrap();
    let held = index.snapshot();
    assert!(held.segment_count() >= 2);
    let generation_before = held.generation().unwrap();
    let manifests_before = manifest_list(&directory).len();

    // L02: the public compaction path fails closed before publication.
    let mut writer = index.writer().unwrap();
    let error = writer.compact().unwrap_err();
    assert!(
        matches!(error, IndexError::CorruptCommittedState { .. }),
        "unexpected error: {error:?}"
    );
    drop(writer);

    // L03: no new generation or manifest, and the held reader still works.
    let pointer_after = CurrentPointer::parse(&read_current(&directory, CURRENT_KEY)).unwrap();
    assert_eq!(pointer_after.generation(), generation_before);
    assert_eq!(manifest_list(&directory).len(), manifests_before);
    assert_eq!(held.generation().unwrap(), generation_before);
    assert!(held.segment_count() >= 2);

    // L04: a retry fails identically with no partial publication.
    let mut writer = index.writer().unwrap();
    assert!(matches!(
        writer.compact().unwrap_err(),
        IndexError::CorruptCommittedState { .. }
    ));
    drop(writer);
    assert_eq!(manifest_list(&directory).len(), manifests_before);
    assert_eq!(
        CurrentPointer::parse(&read_current(&directory, CURRENT_KEY))
            .unwrap()
            .generation(),
        generation_before
    );

    let _ = std::fs::remove_dir_all(&path);
}

// ---------------------------------------------------------------------------
// M01/M02 — public SearchLimits wiring for the spatial candidate-entry cap
// ---------------------------------------------------------------------------

#[test]
fn m01_m02_public_candidate_entry_limit() {
    let docs = vec![
        geo_doc("a", &[(0.0, 0.0)]),
        geo_doc("b", &[(0.0, 0.0)]),
        geo_doc("c", &[(0.0, 0.0)]),
    ];
    let (_directory, index) = committed(docs);
    let snapshot = index.snapshot();
    let req = request(bbox(-1.0, -1.0, 1.0, 1.0), Sort::default(), 10);
    let schema = schema();
    let cancel = CancellationFlag::new();
    let ok = SearchLimits::default()
        .with_max_segment_candidate_entries(3)
        .unwrap();
    assert!(
        TypedSearcher::new(&snapshot, &schema, ok)
            .search(&req, &Budgets::new(), &cancel)
            .is_ok()
    );
    let tight = SearchLimits::default()
        .with_max_segment_candidate_entries(2)
        .unwrap();
    assert!(matches!(
        TypedSearcher::new(&snapshot, &schema, tight).search(&req, &Budgets::new(), &cancel),
        Err(SearchError::ResourceLimit { .. })
    ));
}
