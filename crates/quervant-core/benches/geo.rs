//! PR 12 GeoPoint benchmark: immutable KD candidate pruning versus an
//! equivalent brute-force predicate over the same point set.
//!
//! Both arms evaluate the same exact inclusive bounding-box predicate over the
//! same decoded `SpatialNode` points. The only difference is candidate
//! selection: the KD arm prunes by exact subtree envelopes, the brute-force arm
//! examines every point. The benchmark records the number of exact checks in
//! each arm so latency is never compared without its work count.

use std::hint::black_box;

use criterion::{Criterion, criterion_group, criterion_main};
use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::Cardinality;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, GeoPoint};
use quervant_core::segment::{
    ABSENT_INDEX, SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader, SpatialIndex,
    SpatialNode,
};

const POINTS: usize = 50_000;
const DOCS: usize = 10_000;

fn schema() -> Schema {
    Schema::new(
        vec![FieldDefinition::new(
            "loc",
            FieldType::GeoPoint,
            Cardinality::Multi,
            FieldOptions::new(true, true, true),
        )],
        None,
    )
    .unwrap()
}

fn build() -> (SpatialIndex, Vec<SpatialNode>, [f64; 4]) {
    let mut builder = SegmentBuilder::new(schema(), AnalyzerRegistry::builtin()).unwrap();
    let mut point_cursor = 0usize;
    for doc_index in 0..DOCS {
        let mut document = SegmentDocument::new(
            quervant_core::contract::document::DocumentKey::new(format!("d{doc_index:06}"))
                .unwrap(),
        );
        let mut values = Vec::new();
        while point_cursor < POINTS && values.len() < (point_cursor % 3) + 1 {
            let lon = ((point_cursor.wrapping_mul(37) % 36_000) as f64) / 100.0 - 180.0;
            let lat = ((point_cursor.wrapping_mul(53) % 18_000) as f64) / 100.0 - 90.0;
            values.push(FieldValue::GeoPoint(GeoPoint::new(lon, lat).unwrap()));
            point_cursor += 1;
        }
        let values = if values.len() == 1 {
            quervant_core::contract::document::FieldValues::Single(values.pop().unwrap())
        } else {
            quervant_core::contract::document::FieldValues::Multi(values)
        };
        document.insert("loc", values).unwrap();
        builder.add_document(document).unwrap();
    }
    let built = builder.build().unwrap();
    let reader = SegmentReader::open(built.bytes, SegmentLimits::default()).unwrap();
    let spatial = reader.spatial().unwrap().clone();
    let field_id = reader.schema().field_id("loc").unwrap();
    let tree = spatial.field(field_id).unwrap();
    let nodes = tree.nodes.clone();
    (spatial, nodes, [-30.0, -20.0, 30.0, 20.0])
}

fn bbox_contains(bbox: [f64; 4], lon: f64, lat: f64) -> bool {
    let [west, south, east, north] = bbox;
    if lat < south || lat > north {
        return false;
    }
    let span = if east >= west {
        east - west
    } else {
        east - west + 360.0
    };
    (lon - west).rem_euclid(360.0) <= span + 1e-9
}

fn bbox_may_intersect(bbox: [f64; 4], node: &SpatialNode) -> bool {
    let [west, south, east, north] = bbox;
    if node.max_lat < south || node.min_lat > north {
        return false;
    }
    let span = if east >= west {
        east - west
    } else {
        east - west + 360.0
    };
    let arcs = |start: f64, a_span: f64, b_start: f64, b_span: f64| -> bool {
        if a_span >= 360.0 - 1e-12 || b_span >= 360.0 - 1e-12 {
            return true;
        }
        let within = |lon: f64, s: f64, sp: f64| -> bool {
            sp >= 360.0 - 1e-12 || (lon - s).rem_euclid(360.0) <= sp + 1e-12
        };
        within(start, b_start, b_span)
            || within(start + a_span, b_start, b_span)
            || within(b_start, start, a_span)
            || within(b_start + b_span, start, a_span)
    };
    arcs(
        west,
        span,
        node.min_lon,
        (node.max_lon - node.min_lon).max(0.0),
    )
}

fn kd_candidates(spatial: &SpatialIndex, field_id: u32, bbox: [f64; 4]) -> (usize, usize) {
    let Some(field) = spatial.field(field_id) else {
        return (0, 0);
    };
    let Some(root) = field.root else {
        return (0, 0);
    };
    let mut stack = vec![root];
    let mut exact_checks = 0usize;
    let mut hits = 0usize;
    while let Some(index) = stack.pop() {
        let node = &field.nodes[index as usize];
        if !bbox_may_intersect(bbox, node) {
            continue;
        }
        exact_checks += 1;
        if bbox_contains(bbox, node.lon, node.lat) {
            hits += 1;
        }
        if node.left != ABSENT_INDEX {
            stack.push(node.left);
        }
        if node.right != ABSENT_INDEX {
            stack.push(node.right);
        }
    }
    (exact_checks, hits)
}

fn brute_candidates(nodes: &[SpatialNode], bbox: [f64; 4]) -> (usize, usize) {
    let mut hits = 0usize;
    for node in nodes {
        if bbox_contains(bbox, node.lon, node.lat) {
            hits += 1;
        }
    }
    (nodes.len(), hits)
}

fn bench(c: &mut Criterion) {
    let (spatial, nodes, bbox) = build();
    let field_id = 0u32;
    let (kd_checks, kd_hits) = kd_candidates(&spatial, field_id, bbox);
    let (brute_checks, brute_hits) = brute_candidates(&nodes, bbox);
    assert_eq!(kd_hits, brute_hits);
    eprintln!(
        "geo bench points={} kd_exact_checks={} brute_checks={} hits={}",
        nodes.len(),
        kd_checks,
        brute_checks,
        kd_hits
    );

    c.bench_function("geo_kd_candidates", |b| {
        b.iter(|| black_box(kd_candidates(&spatial, field_id, bbox)))
    });
    c.bench_function("geo_bruteforce_scan", |b| {
        b.iter(|| black_box(brute_candidates(&nodes, bbox)))
    });
}

criterion_group!(benches, bench);
criterion_main!(benches);
