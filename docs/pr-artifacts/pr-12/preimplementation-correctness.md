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

---

# Corrective pass (changes requested)

## Baseline

- Branch: `dev/geopoint-spatial-pr12`, HEAD `1a44349` (one commit above `main`).
- Reviewed `main`: `46ee2ad44db5562c53736cfbfea0ec6ac4e3e8b8`.
- Baseline `cargo test -p quervant-core --test pr12_geo`: PASS, 21 passed / 0 failed.
- Baseline `cargo llvm-cov`: 91.75% workspace line coverage.
- `robust` v1.2.0 (MIT OR Apache-2.0, GeoRust/Spade; edition 2021) resolved as
  Rust 1.85-compatible; API is `robust::orient2d(Coord { x, y }, Coord { x, y },
  Coord { x, y }) -> f64` with sign +1/0/-1 for CCW/collinear/CW. Verified by
  reading the fetched crate source before use. No API invention.

## Invariant map (corrective)

| ID | Invariant | Tests |
|---|---|---|
| I01 | Exact inclusive bbox, no tolerance halo | B01–B10 |
| I02 | ±180 alias, crossing, zero-width, signed zero | B04, B05, B08, B09 |
| I03 | Conservative KD pruning, no false negatives | B10, seeded oracle, `longitude_arcs_intersect` unit test |
| I04 | Exact planar polygon, no epsilon | P01–P10 |
| I05 | Bounded spatial scratch allocations | M01–M16 |
| I06 | Membership + sort share one per-segment budget | M04, M07, M09, M10, M11 |
| I07 | Cancellation/work on all spatial paths | M14, M15, M16, `t11` |
| I08 | Oracle independent of production predicates | O01–O04 |
| I09 | Unrecoverable legacy compaction never publishes | L01–L04 |
| I10 | Codec/Boolean/PIT/multi-value/distance unchanged | R01–R06 |

## Explicit counterexamples driving the fixes

1. **Adjacent-ULP bbox miss (I01).** `bbox_contains(1.0000000000000002e-15, 0, 0, 1e-15, …)`
   must be `false`; the old `<= span + 1e-12` returned `true`. Also
   `bbox_contains(179.99999999999999, …, -180, 180-ulp)` must be `false` while the
   old near-full-world shortcut returned `true`.
2. **Point just outside a hole (I04).** With hole edge `y = 0`, the point
   `(0.5, -1e-16)` is outside the hole and must be *included*; the old
   epsilons treated it as on the hole boundary and excluded it.
3. **Combined scratch allocations (I05/I06).** Two Geo leaves that each fit the
   per-segment candidate-byte budget individually must fail when combined, and a
   distance-sort table plus membership must fail together when they exceed the
   shared budget.
4. **Legacy compaction (I09).** A digest-valid committed segment with an
   indexed-not-stored/non-columnar GeoPoint field and no `SpatialPoints`
   feature must fail `compact()` with `IndexError::CorruptCommittedState` and
   leave the current generation and held PIT intact.

No inspected API conflicts with these invariants. The `robust` dependency API
and MSRV are verified, so P2 proceeds.
