# PR 12 — Pre-implementation correctness record

Base commit: `46ee2ad44db5562c53736cfbfea0ec6ac4e3e8b8` (fresh `main` after PR #33).
Branch: `dev/geopoint-spatial-pr12`.

## 1. Verified current-main contracts

| Surface | Verified fact |
|---|---|
| `contract/value.rs` | `GeoPoint::new(lon, lat)` rejects non-finite, `lon ∉ [-180, 180]`, `lat ∉ [-90, 90]`. `FieldValue::GeoPoint` and `FieldType::GeoPoint` exist. |
| `contract/query.rs` | `GeoBoundingBox` allows `west > east` (antimeridian); `GeoRadius` rejects `!finite || <= 0`; `GeoPolygon` rejects edges with `|Δlon| >= 180` or a vertex at `|lon| == 180`, and rejects self-intersecting/zero-area rings. |
| `segment/column.rs` | GeoPoint columns are supported, single (`LAYOUT_FIXED_SINGLE`, 16 bytes) and multi. |
| `segment/bounds.rs` | `GeoBounds` is conservative pruning metadata only; `prunes_positive_box` is used for pruning. |
| `segment/format.rs` | Last section is `JsonPaths = 0x0010`; last feature is `FEATURE_JSON_PATHS = 0x0009`. |
| `search/typed.rs` | Geo query variants are rejected with `SearchError::UnsupportedOperator` in `validate_query`. |
| `index/merge.rs` | Compaction remaps decoded structures and already preserves indexed-but-not-stored JSON via a source section or a stored fallback. |
| `search/typed_compare.rs` | Sort tuples are built from columnar values only; `SortField` has `field/direction/missing/multi`. |

No verified fact contradicts the PR 12 design.

## 2. Semantics fixed before coding

- Bounding-box edges are inclusive. A crossing box (`west > east`) is `[west, 180] ∪ [-180, east]`. `±180` are the same meridian. Longitude membership is evaluated on the circle: `span = east >= west ? east - west : east - west + 360`, `delta = (lon - west).rem_euclid(360)`, match iff `delta <= span`.
- Radius uses spherical haversine with `R = 6_371_008.8 m` (not ellipsoidal), inclusive (`distance <= meters`).
- Polygon is planar and non-crossing. Outer boundary is *inside*; hole boundary is *excluded*; holes subtract their interior. Ray casting with explicit boundary detection.
- Missing/`ExplicitNull`/`Empty`/absent GeoPoint contributes no point. A multi-valued document matches if any point matches, and is returned once.
- Geo distance sort uses the minimum point distance, ascending by default, missing last, tied by the existing logical-key tie-break, and is part of the PIT/search-after fingerprint.
- GeoJSON ingestion accepts exactly `{"type":"Point","coordinates":[lon,lat]}` with finite numeric coordinates; every other shape is a typed rejection.

## 3. KD tree / codec invariants

- Immutable field-local median-split 2D KD tree over every GeoPoint occurrence; split axis alternates longitude (depth even) / latitude (depth odd).
- Deterministic pre-order serialization: order by `(axis.total_cmp, other.total_cmp, doc_id, ordinal)` after signed-zero normalization, `mid = len / 2`, node `i`'s left child is always `i + 1` when present.
- Each node carries exact subtree extrema; the reader recomputes them bottom-up and requires equality.
- Reader fails closed on: feature/section mismatch, non-increasing field ids, unknown/wrong/non-indexed field, count overflow, `count * 77` overflow, out-of-range doc id, duplicate `(doc_id, ordinal)`, non-finite/out-of-range coordinates, child index `<= parent`, cycles, orphans, wrong split axis, split-order violation, wrong envelope, and trailing bytes.
- Section `0x0011`, feature `0x000A`, version 1; both co-occur. The section is emitted whenever any indexed GeoPoint field exists, even with zero points.

## 4. Boundary / failure matrix

| Case | Expected |
|---|---|
| `lon` exactly `±180` in a box endpoint | equivalent meridian match |
| pole latitude the box edge | inclusive match |
| `meters == 0`, negative, NaN, infinite | `QueryError::InvalidQuery(InvalidRadius)` before I/O |
| crossing polygon edge / ±180 vertex | `QueryError::UnsupportedGeoShape` |
| corrupt spatial section with a valid container digest | typed segment-open error, never a fallback |
| missing spatial section, columnar field | bounded exact column scan |
| missing spatial section, stored-only field | bounded stored-source extraction |
| missing spatial section, indexed-not-stored/non-columnar | typed failure, never zero hits |
| cancellation during traversal/build/final scan | `Cancelled`, no partial hits |
| budget exhaustion | `ResourceLimit`, no partial hits |
| write/merge failure | previously committed generation remains usable |

## 5. STOP findings

None at Phase 0. The existing `SortField` public struct is extended with an optional
GeoPoint distance origin (additive, with a manual `Eq`), which is a compatible
extension rather than an incompatible redesign. No planner redesign is required:
geo leaves are compiled and membership is precomputed per segment.
