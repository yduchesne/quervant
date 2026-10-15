//! Pure exact geometry for GeoPoint predicates (PR 12).
//!
//! No KD tree, segment or index type is referenced here so the predicates can be
//! tested independently and reused by the independent test oracle. Distances are
//! spherical (haversine) with the fixed mean Earth radius `6_371_008.8 m`, never
//! ellipsoidal. Polygons are planar and non-crossing, matching the existing
//! `GeoPolygon` contract.

/// Mean Earth radius in meters used by the spherical distance model.
pub(crate) const EARTH_RADIUS_METERS: f64 = 6_371_008.8;

/// Eastward angular span of a longitude interval, including the crossing case.
#[must_use]
pub(crate) fn longitude_span(west: f64, east: f64) -> f64 {
    if east >= west {
        east - west
    } else {
        east - west + 360.0
    }
}

/// Whether `lon` lies on the eastward arc `[west, west + span]`.
///
/// `west` and `span` may be outside `[-180, 180]` / `[0, 360]`; the circular
/// distance is computed with `rem_euclid`.
#[must_use]
pub(crate) fn longitude_on_arc(lon: f64, west: f64, span: f64) -> bool {
    if span >= 360.0 - 1e-12 {
        return true;
    }
    let delta = (lon - west).rem_euclid(360.0);
    delta <= span + 1e-12
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
    longitude_on_arc(lon, west, longitude_span(west, east))
}

/// Whether two connected circular longitude arcs intersect.
///
/// Conservative for pruning: returning `true` merely means "may intersect".
#[must_use]
pub(crate) fn longitude_arcs_intersect(
    a_start: f64,
    a_span: f64,
    b_start: f64,
    b_span: f64,
) -> bool {
    if a_span >= 360.0 - 1e-12 || b_span >= 360.0 - 1e-12 {
        return true;
    }
    if a_span <= 1e-12 {
        return longitude_on_arc(a_start, b_start, b_span);
    }
    if b_span <= 1e-12 {
        return longitude_on_arc(b_start, a_start, a_span);
    }
    longitude_on_arc(a_start, b_start, b_span)
        || longitude_on_arc(a_start + a_span, b_start, b_span)
        || longitude_on_arc(b_start, a_start, a_span)
        || longitude_on_arc(b_start + b_span, a_start, a_span)
}

/// Whether a bounding box may intersect a node envelope.
///
/// The node envelope is exact `[min_lon, max_lon] × [min_lat, max_lat]`; the
/// query longitude span is interpreted on the circle.
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
#[must_use]
pub(crate) fn point_on_segment(px: f64, py: f64, ax: f64, ay: f64, bx: f64, by: f64) -> bool {
    let cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
    let scale = 1.0 + (bx - ax).abs() + (by - ay).abs() + (px - ax).abs() + (py - ay).abs();
    if cross.abs() > 1e-12 * scale {
        return false;
    }
    px >= ax.min(bx) - 1e-12
        && px <= ax.max(bx) + 1e-12
        && py >= ay.min(by) - 1e-12
        && py <= ay.max(by) + 1e-12
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
        if point_on_segment(px, py, ax, ay, bx, by) {
            return RingPosition::Boundary;
        }
        if (ay > py) != (by > py) {
            let t = (py - ay) / (by - ay);
            let x = ax + t * (bx - ax);
            if px < x {
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

    #[test]
    fn bbox_inclusive_and_crossing() {
        assert!(bbox_contains(0.0, 0.0, -1.0, -1.0, 1.0, 1.0));
        assert!(bbox_contains(1.0, 1.0, -1.0, -1.0, 1.0, 1.0));
        assert!(!bbox_contains(1.0001, 0.0, -1.0, -1.0, 1.0, 1.0));
        // Crossing box [170, 180] U [-180, -170].
        assert!(bbox_contains(175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-175.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(!bbox_contains(0.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        // ±180 alias.
        assert!(bbox_contains(180.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-180.0, 0.0, 170.0, -5.0, -170.0, 5.0));
        assert!(bbox_contains(-180.0, 0.0, -170.0, -5.0, 180.0, 5.0));
        assert!(bbox_contains(180.0, 0.0, -180.0, -5.0, -170.0, 5.0));
    }

    #[test]
    fn bbox_envelope_pruning_never_false_prunes_alias() {
        // A node whose only point is at +180 must not be pruned for a box that
        // reaches down to -180 via the alias.
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
        // ±180 alias is zero apart along the equator.
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
