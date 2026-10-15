//! Pure exact geometry for GeoPoint predicates (PR 12).
//!
//! No KD tree, segment or index type is referenced here so the predicates can be
//! tested independently and reused by the independent test oracle. Distances are
//! spherical (haversine) with the fixed mean Earth radius `6_371_008.8 m`, never
//! ellipsoidal. Polygons are planar and non-crossing, matching the existing
//! `GeoPolygon` contract.
//!
//! Exact membership predicates contain **no tolerance**: bounding-box edges and
//! polygon boundaries are classified by exact comparisons and the adaptive
//! `robust::orient2d` predicate. Pruning helpers are deliberately conservative
//! (they may return `true` for a non-match but must never return `false` for a
//! match).

use robust::{Coord, orient2d};

/// Mean Earth radius in meters used by the spherical distance model.
pub(crate) const EARTH_RADIUS_METERS: f64 = 6_371_008.8;

/// Next representable `f64` strictly above `value` (conservative direction).
fn next_up(value: f64) -> f64 {
    if value.is_nan() || value == f64::INFINITY {
        return value;
    }
    if value == 0.0 {
        return f64::from_bits(1);
    }
    let bits = value.to_bits();
    if value > 0.0 {
        f64::from_bits(bits + 1)
    } else {
        f64::from_bits(bits - 1)
    }
}

/// Next representable `f64` strictly below `value` (conservative direction).
fn next_down(value: f64) -> f64 {
    if value.is_nan() || value == f64::NEG_INFINITY {
        return value;
    }
    if value == 0.0 {
        return -f64::from_bits(1);
    }
    let bits = value.to_bits();
    if value > 0.0 {
        f64::from_bits(bits - 1)
    } else {
        f64::from_bits(bits + 1)
    }
}

/// Eastward angular span of a longitude interval, including the crossing case.
#[must_use]
pub(crate) fn longitude_span(west: f64, east: f64) -> f64 {
    if east >= west {
        east - west
    } else {
        east - west + 360.0
    }
}

/// Canonical closed longitude intervals for a bounding box.
///
/// The circle is split at the antimeridian: a non-crossing box is one closed
/// interval and a `west > east` box is `[west, 180] ∪ [-180, east]`. No span or
/// modulo arithmetic is used, so the exact `west`/`east` values are preserved.
fn bbox_intervals(west: f64, east: f64) -> ([(f64, f64); 2], usize) {
    if west > east {
        ([(west, 180.0), (-180.0, east)], 2)
    } else {
        ([(west, east), (0.0, 0.0)], 1)
    }
}

fn intervals_contain(lon: f64, intervals: &[(f64, f64)]) -> bool {
    intervals
        .iter()
        .any(|(low, high)| lon >= *low && lon <= *high)
}

/// Exact inclusive longitude membership with `±180` treated as one meridian.
#[must_use]
pub(crate) fn longitude_in_bbox(lon: f64, west: f64, east: f64) -> bool {
    let (intervals, len) = bbox_intervals(west, east);
    let intervals = &intervals[..len];
    if intervals_contain(lon, intervals) {
        return true;
    }
    // `+180` and `-180` are the same physical meridian: test the alias too.
    if lon == 180.0 {
        intervals_contain(-180.0, intervals)
    } else if lon == -180.0 {
        intervals_contain(180.0, intervals)
    } else {
        false
    }
}

/// Whether a point is inside an inclusive bounding box.
#[must_use]
pub(crate) fn bbox_contains(
    lon: f64,
    lat: f64,
    west: f64,
    south: f64,
    east: f64,
    north: f64,
) -> bool {
    if lat < south || lat > north {
        return false;
    }
    longitude_in_bbox(lon, west, east)
}

/// Exact membership on the closed eastward arc `[west, west + span]`.
///
/// No tolerance: the arc is split into canonical closed intervals and `±180`
/// aliases are tested explicitly. Retained for the conservative arc-intersection
/// endpoint tests.
#[must_use]
pub(crate) fn longitude_on_arc(lon: f64, west: f64, span: f64) -> bool {
    if span >= 360.0 {
        return true;
    }
    let end = west + span;
    let (intervals, len) = if end <= 180.0 {
        ([(west, end), (0.0, 0.0)], 1)
    } else {
        ([(west, 180.0), (-180.0, end - 360.0)], 2)
    };
    let intervals = &intervals[..len];
    if intervals_contain(lon, intervals) {
        return true;
    }
    if lon == 180.0 {
        intervals_contain(-180.0, intervals)
    } else if lon == -180.0 {
        intervals_contain(180.0, intervals)
    } else {
        false
    }
}

/// Split a (possibly widened) arc `[lo, hi]` into canonical intervals.
fn split_arc(lo: f64, hi: f64) -> ([(f64, f64); 2], usize) {
    if hi - lo >= 360.0 {
        return ([(f64::NEG_INFINITY, f64::INFINITY), (0.0, 0.0)], 1);
    }
    if hi <= 180.0 {
        ([(lo, hi), (0.0, 0.0)], 1)
    } else {
        ([(lo, 180.0), (-180.0, hi - 360.0)], 2)
    }
}

fn interval_sets_overlap(a: &[(f64, f64)], b: &[(f64, f64)]) -> bool {
    for (a_lo, a_hi) in a {
        for (b_lo, b_hi) in b {
            if a_lo <= b_hi && b_lo <= a_hi {
                return true;
            }
        }
    }
    false
}

/// Whether two connected circular longitude arcs may intersect.
///
/// Conservative for pruning: returning `true` merely means "may intersect".
/// Both arcs are widened by one ULP before comparison so a rounded endpoint can
/// never hide a genuine intersection, and the `±180` seam is treated as one
/// physical longitude.
#[must_use]
pub(crate) fn longitude_arcs_intersect(
    a_start: f64,
    a_span: f64,
    b_start: f64,
    b_span: f64,
) -> bool {
    if a_span >= 360.0 || b_span >= 360.0 || a_span < 0.0 || b_span < 0.0 {
        return true;
    }
    let a_lo = next_down(a_start);
    let a_hi = next_up(a_start + a_span);
    let b_lo = next_down(b_start);
    let b_hi = next_up(b_start + b_span);
    let a_seam = a_lo <= -180.0 || a_hi >= 180.0;
    let b_seam = b_lo <= -180.0 || b_hi >= 180.0;
    if a_seam && b_seam {
        return true;
    }
    let (a_intervals, a_len) = split_arc(a_lo, a_hi);
    let (b_intervals, b_len) = split_arc(b_lo, b_hi);
    if interval_sets_overlap(&a_intervals[..a_len], &b_intervals[..b_len]) {
        return true;
    }
    // Endpoint membership is an additional conservative check for any rounding
    // hidden in the widened endpoints.
    longitude_on_arc(a_lo, b_start, b_span)
        || longitude_on_arc(a_hi, b_start, b_span)
        || longitude_on_arc(b_lo, a_start, a_span)
        || longitude_on_arc(b_hi, a_start, a_span)
}

/// Whether a bounding box may intersect a node envelope.
///
/// The node envelope is exact `[min_lon, max_lon] × [min_lat, max_lat]`; a node
/// touching the antimeridian is treated conservatively.
#[must_use]
pub(crate) fn bbox_intersects_envelope(
    bbox: (f64, f64, f64, f64),
    envelope: (f64, f64, f64, f64),
) -> bool {
    let (west, south, east, north) = bbox;
    let (min_lon, min_lat, max_lon, max_lat) = envelope;
    if max_lat < south || min_lat > north {
        return false;
    }
    longitude_arcs_intersect(
        west,
        longitude_span(west, east),
        min_lon,
        (max_lon - min_lon).max(0.0),
    )
}

/// Spherical haversine distance in meters.
///
/// Always finite and nonnegative; identical points return exactly `0.0`.
#[must_use]
pub(crate) fn haversine_meters(lon1: f64, lat1: f64, lon2: f64, lat2: f64) -> f64 {
    if lon1 == lon2 && lat1 == lat2 {
        return 0.0;
    }
    let phi1 = lat1.to_radians();
    let phi2 = lat2.to_radians();
    let d_phi = (lat2 - lat1).to_radians();
    // Use the shortest longitude difference so ±180 are the same meridian.
    let mut lon_delta = lon2 - lon1;
    if lon_delta > 180.0 {
        lon_delta -= 360.0;
    } else if lon_delta < -180.0 {
        lon_delta += 360.0;
    }
    let d_lambda = lon_delta.to_radians();
    let sin_d_phi = (d_phi / 2.0).sin();
    let sin_d_lambda = (d_lambda / 2.0).sin();
    let a = (sin_d_phi * sin_d_phi + phi1.cos() * phi2.cos() * sin_d_lambda * sin_d_lambda)
        .clamp(0.0, 1.0);
    2.0 * EARTH_RADIUS_METERS * a.sqrt().asin()
}

/// Whether `(px, py)` lies on the closed segment `(ax, ay)..(bx, by)`.
///
/// Uses the adaptive exact `orient2d` predicate for collinearity and exact
/// inclusive bounding-box comparisons for the on-segment range. No tolerance.
#[must_use]
pub(crate) fn point_on_segment(px: f64, py: f64, ax: f64, ay: f64, bx: f64, by: f64) -> bool {
    let orientation = orient2d(
        Coord { x: ax, y: ay },
        Coord { x: bx, y: by },
        Coord { x: px, y: py },
    );
    if orientation != 0.0 {
        return false;
    }
    px >= ax.min(bx) && px <= ax.max(bx) && py >= ay.min(by) && py <= ay.max(by)
}

/// Position of a point relative to a single ring.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RingPosition {
    Inside,
    Outside,
    Boundary,
}

fn point_in_ring(px: f64, py: f64, ring: &[(f64, f64)]) -> RingPosition {
    let mut inside = false;
    let n = ring.len();
    if n < 3 {
        return RingPosition::Outside;
    }
    for index in 0..n {
        let (ax, ay) = ring[index];
        let (bx, by) = ring[(index + 1) % n];
        // Boundary classification wins over parity and is exact.
        if point_on_segment(px, py, ax, ay, bx, by) {
            return RingPosition::Boundary;
        }
        // Half-open y-straddle; a shared vertex is counted exactly once.
        if (ay > py) != (by > py) {
            // Crossing strictly to the right of `px` iff the point lies to the
            // left of an upward edge or to the right of a downward edge.
            let orientation = orient2d(
                Coord { x: ax, y: ay },
                Coord { x: bx, y: by },
                Coord { x: px, y: py },
            );
            let crosses_right = if ay < by {
                orientation > 0.0
            } else {
                orientation < 0.0
            };
            if crosses_right {
                inside = !inside;
            }
        }
    }
    if inside {
        RingPosition::Inside
    } else {
        RingPosition::Outside
    }
}

/// Whether a point is inside a planar polygon with holes.
///
/// The outer boundary is inside; every hole boundary is excluded, as is every
/// hole interior.
#[must_use]
pub(crate) fn polygon_contains(
    px: f64,
    py: f64,
    outer: &[(f64, f64)],
    holes: &[Vec<(f64, f64)>],
) -> bool {
    match point_in_ring(px, py, outer) {
        RingPosition::Outside => return false,
        RingPosition::Boundary => return true,
        RingPosition::Inside => {}
    }
    for hole in holes {
        match point_in_ring(px, py, hole) {
            RingPosition::Outside => {}
            RingPosition::Boundary | RingPosition::Inside => return false,
        }
    }
    true
}

/// Whether a polygon outer envelope may intersect a node envelope.
#[must_use]
pub(crate) fn polygon_intersects_envelope(
    polygon: (f64, f64, f64, f64),
    envelope: (f64, f64, f64, f64),
) -> bool {
    let (poly_min_lon, poly_min_lat, poly_max_lon, poly_max_lat) = polygon;
    let (min_lon, min_lat, max_lon, max_lat) = envelope;
    max_lat >= poly_min_lat
        && min_lat <= poly_max_lat
        && max_lon >= poly_min_lon
        && min_lon <= poly_max_lon
}

#[cfg(test)]
mod tests {
    use super::*;

    const EPS: f64 = 1e-6;

    // ------------------------------------------------------------------
    // B01–B10 — exact bounding boxes
    // ------------------------------------------------------------------

    #[test]
    fn b01_four_exact_edges_included() {
        let (west, south, east, north) = (-10.0, -5.0, 10.0, 5.0);
        assert!(bbox_contains(west, 0.0, west, south, east, north));
        assert!(bbox_contains(east, 0.0, west, south, east, north));
        assert!(bbox_contains(0.0, south, west, south, east, north));
        assert!(bbox_contains(0.0, north, west, south, east, north));
        assert!(bbox_contains(west, south, west, south, east, north));
    }

    #[test]
    fn b02_adjacent_ulp_longitude_outsiders_excluded() {
        // Tiny non-degenerate box: the old `+ 1e-12` halo accepted both outsiders.
        let east = 1e-15_f64;
        assert!(bbox_contains(0.0, 0.0, 0.0, -1.0, east, 1.0));
        assert!(bbox_contains(east, 0.0, 0.0, -1.0, east, 1.0));
        assert!(!bbox_contains(next_up(east), 0.0, 0.0, -1.0, east, 1.0));
        assert!(!bbox_contains(next_down(0.0), 0.0, 0.0, -1.0, east, 1.0));
    }

    #[test]
    fn b03_adjacent_ulp_latitude_outsiders_excluded() {
        let north = 1e-15_f64;
        assert!(bbox_contains(0.0, north, -1.0, 0.0, 1.0, north));
        assert!(!bbox_contains(0.0, next_up(north), -1.0, 0.0, 1.0, north));
        assert!(!bbox_contains(0.0, next_down(0.0), -1.0, 0.0, 1.0, north));
    }

    #[test]
    fn b04_degenerate_box_matches_exactly() {
        assert!(bbox_contains(0.0, 0.0, 0.0, 0.0, 0.0, 0.0));
        assert!(!bbox_contains(next_up(0.0), 0.0, 0.0, 0.0, 0.0, 0.0));
        assert!(!bbox_contains(next_down(0.0), 0.0, 0.0, 0.0, 0.0, 0.0));
        assert!(!bbox_contains(0.0, next_up(0.0), 0.0, 0.0, 0.0, 0.0));
    }

    #[test]
    fn b05_antimeridian_aliases() {
        // Crossing box.
        assert!(bbox_contains(180.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-180.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        // Non-crossing box that reaches one side of the seam.
        assert!(bbox_contains(-180.0, 0.0, 170.0, -5.0, 180.0, 5.0));
        assert!(bbox_contains(180.0, 0.0, -180.0, -5.0, -170.0, 5.0));
        // Degenerate seam box matches both representations only.
        assert!(bbox_contains(180.0, 0.0, 180.0, -1.0, 180.0, 1.0));
        assert!(bbox_contains(-180.0, 0.0, 180.0, -1.0, 180.0, 1.0));
        assert!(!bbox_contains(179.999, 0.0, 180.0, -1.0, 180.0, 1.0));
    }

    #[test]
    fn b06_crossing_170_to_minus_170() {
        assert!(bbox_contains(175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(!bbox_contains(0.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(!bbox_contains(169.999, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(!bbox_contains(-169.999, 0.0, 170.0, -5.0, -170.0, 5.0));
    }

    #[test]
    fn b07_near_full_world_gap_excluded() {
        // A span just under 360 degrees used to be treated as full-world by the
        // old `span >= 360 - 1e-12` shortcut.
        let east = 180.0 - 1e-13;
        let outsider = 180.0 - 5e-14;
        assert!(longitude_span(-180.0, east) < 360.0);
        assert!(outsider > east && outsider < 180.0);
        assert!(bbox_contains(east, 0.0, -180.0, -90.0, east, 90.0));
        assert!(!bbox_contains(outsider, 0.0, -180.0, -90.0, east, 90.0));
        // The seam alias is genuinely inside `[-180, east]`.
        assert!(bbox_contains(180.0, 0.0, -180.0, -90.0, east, 90.0));
    }

    #[test]
    fn b08_signed_zero() {
        assert!(bbox_contains(0.0, 0.0, -0.0, -0.0, 0.0, 0.0));
        assert!(bbox_contains(-0.0, 0.0, 0.0, -1.0, 0.0, 1.0));
        assert!(!bbox_contains(next_up(0.0), 0.0, 0.0, -1.0, 0.0, 1.0));
        assert!(!bbox_contains(next_down(0.0), 0.0, 0.0, -1.0, 0.0, 1.0));
    }

    #[test]
    fn b09_seam_boundary_inclusion() {
        assert!(bbox_contains(180.0, 0.0, 179.5, -1.0, -179.5, 1.0));
        assert!(bbox_contains(-180.0, 0.0, 179.5, -1.0, -179.5, 1.0));
        assert!(!bbox_contains(179.0, 0.0, 179.5, -1.0, -179.5, 1.0));
    }

    #[test]
    fn b10_pruning_never_false_prunes_seams() {
        // A node exactly at +180 is reachable by a box reaching -180.
        assert!(bbox_intersects_envelope(
            (-180.0, -5.0, -170.0, 5.0),
            (180.0, 0.0, 180.0, 0.0)
        ));
        assert!(bbox_intersects_envelope(
            (170.0, -5.0, -170.0, 5.0),
            (-180.0, 0.0, -180.0, 0.0)
        ));
        // Genuinely disjoint boxes still prune.
        assert!(!bbox_intersects_envelope(
            (0.0, 0.0, 10.0, 10.0),
            (100.0, 20.0, 110.0, 30.0)
        ));
    }

    #[test]
    fn longitude_arcs_intersect_is_conservative() {
        // Overlapping ordinary arcs.
        assert!(longitude_arcs_intersect(0.0, 10.0, 5.0, 10.0));
        // Disjoint ordinary arcs.
        assert!(!longitude_arcs_intersect(0.0, 10.0, 20.0, 10.0));
        // Full-world arc intersects everything.
        assert!(longitude_arcs_intersect(0.0, 360.0, 100.0, 1.0));
        // Seam-aliased arcs genuinely intersect.
        assert!(longitude_arcs_intersect(170.0, 10.0, -180.0, 10.0));
    }

    #[test]
    fn bbox_inclusive_and_crossing_legacy() {
        assert!(bbox_contains(0.0, 0.0, -1.0, -1.0, 1.0, 1.0));
        assert!(bbox_contains(1.0, 1.0, -1.0, -1.0, 1.0, 1.0));
        assert!(!bbox_contains(1.0001, 0.0, -1.0, -1.0, 1.0, 1.0));
        assert!(bbox_contains(175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(!bbox_contains(0.0, 0.0, 170.0, -5.0, -170.0, 5.0));
    }

    #[test]
    fn frame_next_up_and_down() {
        assert!(next_up(0.0) > 0.0);
        assert!(next_down(0.0) < 0.0);
        assert!(next_up(-1.0) > -1.0);
        assert!(next_down(-1.0) < -1.0);
        assert_eq!(next_up(f64::INFINITY), f64::INFINITY);
    }

    // ------------------------------------------------------------------
    // P01–P10 — exact polygon boundaries
    // ------------------------------------------------------------------

    #[test]
    fn p01_outer_edge_included() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        assert!(polygon_contains(0.0, 512.0, &outer, &[]));
        assert!(polygon_contains(512.0, 0.0, &outer, &[]));
        assert!(polygon_contains(1024.0, 512.0, &outer, &[]));
        assert!(polygon_contains(512.0, 1024.0, &outer, &[]));
    }

    #[test]
    fn p02_just_outside_outer_excluded() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        assert!(!polygon_contains(next_down(0.0), 512.0, &outer, &[]));
        assert!(!polygon_contains(next_up(1024.0), 512.0, &outer, &[]));
    }

    #[test]
    fn p03_just_inside_outer_included() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        assert!(polygon_contains(next_up(0.0), 512.0, &outer, &[]));
        assert!(polygon_contains(next_down(1024.0), 512.0, &outer, &[]));
    }

    #[test]
    fn p04_hole_edge_excluded() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        let hole = vec![
            (256.0, 256.0),
            (768.0, 256.0),
            (768.0, 768.0),
            (256.0, 768.0),
        ];
        assert!(!polygon_contains(
            512.0,
            256.0,
            &outer,
            std::slice::from_ref(&hole)
        ));
        assert!(!polygon_contains(
            256.0,
            512.0,
            &outer,
            std::slice::from_ref(&hole)
        ));
        assert!(!polygon_contains(768.0, 512.0, &outer, &[hole]));
    }

    #[test]
    fn p05_hole_interior_excluded() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        let hole = vec![
            (256.0, 256.0),
            (768.0, 256.0),
            (768.0, 768.0),
            (256.0, 768.0),
        ];
        assert!(!polygon_contains(512.0, 512.0, &outer, &[hole]));
    }

    #[test]
    fn p06_just_outside_hole_included_and_ulp_not_boundary() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        let hole = vec![
            (256.0, 256.0),
            (768.0, 256.0),
            (768.0, 768.0),
            (256.0, 768.0),
        ];
        // A point one ULP below the hole's south edge is outside the hole and
        // must be included. The old epsilons classified it as a hole boundary.
        assert!(polygon_contains(
            512.0,
            next_down(256.0),
            &outer,
            std::slice::from_ref(&hole)
        ));
        assert!(polygon_contains(next_down(256.0), 512.0, &outer, &[hole]));
    }

    #[test]
    fn p07_horizontal_vertical_slanted() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        // Horizontal edge at y = 512 from (0,512) to (1024,512).
        assert!(point_on_segment(300.0, 512.0, 0.0, 512.0, 1024.0, 512.0));
        // Vertical edge.
        assert!(point_on_segment(512.0, 300.0, 512.0, 0.0, 512.0, 1024.0));
        // Slanted edge through the origin.
        assert!(point_on_segment(256.0, 256.0, 0.0, 0.0, 1024.0, 1024.0));
        assert!(!point_on_segment(
            300.0,
            next_up(300.0),
            0.0,
            0.0,
            1024.0,
            1024.0
        ));
        assert!(polygon_contains(512.0, 512.0, &outer, &[]));
    }

    #[test]
    fn p08_vertex_ray_height_parity() {
        let diamond = [(512.0, 0.0), (1024.0, 512.0), (512.0, 1024.0), (0.0, 512.0)];
        // A ray through the shared vertex height must not double count.
        assert!(polygon_contains(512.0, 512.0, &diamond, &[]));
        // The extreme vertices are boundary and therefore inside.
        assert!(polygon_contains(512.0, 0.0, &diamond, &[]));
        assert!(polygon_contains(1024.0, 512.0, &diamond, &[]));
        assert!(polygon_contains(512.0, 1024.0, &diamond, &[]));
        assert!(polygon_contains(0.0, 512.0, &diamond, &[]));
    }

    #[test]
    fn p09_reversed_ring_order_equivalent() {
        let outer = [(0.0, 0.0), (1024.0, 0.0), (1024.0, 1024.0), (0.0, 1024.0)];
        let reversed: Vec<(f64, f64)> = outer.iter().rev().copied().collect();
        let hole = vec![
            (256.0, 256.0),
            (768.0, 256.0),
            (768.0, 768.0),
            (256.0, 768.0),
        ];
        let hole_reversed: Vec<(f64, f64)> = hole.iter().rev().copied().collect();
        for (px, py) in [(512.0, 512.0), (next_down(256.0), 512.0), (128.0, 128.0)] {
            assert_eq!(
                polygon_contains(px, py, &outer, std::slice::from_ref(&hole)),
                polygon_contains(px, py, &reversed, std::slice::from_ref(&hole_reversed)),
            );
        }
    }

    #[test]
    fn p10_adjacent_ulp_outsiders_never_boundary() {
        // The midpoint of the diagonal raised by one ULP has nonzero robust
        // orientation, so it is never treated as on the edge.
        let (ax, ay) = (0.0, 0.0);
        let (bx, by) = (1.0, 1.0);
        let px = 0.5;
        let py = next_up(0.5);
        assert!(!point_on_segment(px, py, ax, ay, bx, by));
    }

    // ------------------------------------------------------------------
    // Reference values and envelope intersection
    // ------------------------------------------------------------------

    #[test]
    fn bbox_envelope_pruning_never_false_prunes_alias() {
        assert!(bbox_intersects_envelope(
            (-180.0, -5.0, -170.0, 5.0),
            (180.0, 0.0, 180.0, 0.0)
        ));
        assert!(!bbox_intersects_envelope(
            (0.0, 0.0, 10.0, 10.0),
            (-180.0, -180.0, -179.0, -179.0)
        ));
    }

    #[test]
    fn haversine_reference_values() {
        assert_eq!(haversine_meters(0.0, 0.0, 0.0, 0.0), 0.0);
        let quarter = haversine_meters(0.0, 0.0, 90.0, 0.0);
        assert!((quarter - EARTH_RADIUS_METERS * std::f64::consts::FRAC_PI_2).abs() < EPS);
        let antipodal = haversine_meters(0.0, 0.0, 180.0, 0.0);
        assert!((antipodal - EARTH_RADIUS_METERS * std::f64::consts::PI).abs() < 1e-3);
        assert_eq!(haversine_meters(180.0, 0.0, -180.0, 0.0), 0.0);
    }

    #[test]
    fn segment_boundaries() {
        assert!(point_on_segment(0.5, 0.5, 0.0, 0.0, 1.0, 1.0));
        assert!(point_on_segment(0.0, 0.0, 0.0, 0.0, 1.0, 1.0));
        assert!(!point_on_segment(0.6, 0.5, 0.0, 0.0, 1.0, 1.0));
        assert!(point_on_segment(0.5, 0.0, 0.0, 0.0, 1.0, 0.0));
        assert!(!point_on_segment(1.5, 0.0, 0.0, 0.0, 1.0, 0.0));
    }

    #[test]
    fn polygon_interior_boundary_and_holes() {
        let outer = vec![(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)];
        let holes = vec![vec![(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]];
        assert!(polygon_contains(2.0, 0.5, &outer, &holes));
        assert!(polygon_contains(0.0, 0.0, &outer, &holes));
        assert!(polygon_contains(4.0, 2.0, &outer, &holes));
        assert!(!polygon_contains(2.0, 2.0, &outer, &holes));
        assert!(!polygon_contains(1.0, 2.0, &outer, &holes));
        assert!(!polygon_contains(5.0, 5.0, &outer, &holes));
        assert!(!polygon_contains(-0.001, 2.0, &outer, &holes));
    }

    #[test]
    fn polygon_envelope_intersection() {
        assert!(polygon_intersects_envelope(
            (0.0, 0.0, 4.0, 4.0),
            (2.0, 2.0, 3.0, 3.0)
        ));
        assert!(!polygon_intersects_envelope(
            (0.0, 0.0, 4.0, 4.0),
            (5.0, 5.0, 6.0, 6.0)
        ));
    }
}
