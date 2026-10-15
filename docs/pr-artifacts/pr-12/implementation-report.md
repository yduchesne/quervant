# PR 12 — Implementation report

## Scope delivered

Immutable, bounded GeoPoint indexing and exact bounding-box, radius and polygon
queries; GeoJSON Point ingestion; geodesic-distance ordering; and safe
mutation/compaction/PIT integration. Distributed, vector, RustFS and rich
geometry work is out of scope.

## Format

| Item | Value |
|---|---|
| Section | `SectionKind::SpatialPoints = 0x0011` |
| Feature | `FEATURE_SPATIAL_POINTS = 0x000A` v1 (required when present) |
| Version | `SPATIAL_POINTS_VERSION = 1` |
| Node width | 77 bytes |
| Body | `u16 version`, `u32 field_count`, then per field (strictly increasing id) `u32 field_id`, `u64 point_count`, `u64 root_index` (0 or `MAX`), then `point_count` preorder nodes |
| Node | `u64 doc_id`, `u32 ordinal`, `f64 lon`, `f64 lat`, `f64 min_lon`, `f64 min_lat`, `f64 max_lon`, `f64 max_lat`, `u64 left`, `u64 right`, `u8 split_axis` |

No existing section/feature id changed; the format major/minor is unchanged. The
section is emitted whenever any indexed GeoPoint field exists, even with zero
points. Old segments remain readable.

## Files

New:

- `crates/quervant-core/src/search/geo.rs` — pure exact geometry (circular
  longitude membership, inclusive bbox, haversine with `R = 6_371_008.8 m`,
  segment boundary test, ray-casting polygon with holes, conservative envelope
  intersection).
- `crates/quervant-core/src/segment/spatial.rs` — deterministic encoder,
  validated reader, bounded KD build/traverse; golden-byte and malformed-node
  tests.
- `crates/quervant-core/benches/geo.rs` — KD candidate pruning vs brute-force
  scan.
- `crates/quervant-core/tests/pr12_geo.rs` and
  `crates/quervant-core/tests/pr12_common/mod.rs` — integration tests and
  independent oracle.

Modified:

- `segment/format.rs` — new section/feature id and supported-feature entry.
- `segment/mod.rs`, `segment/reader.rs` — export and eager validation of the
  spatial index; `SegmentReader::spatial()` accessor.
- `segment/build.rs` — collect every indexed GeoPoint occurrence in physical
  order with ordinals, emit the section and feature.
- `search/typed.rs` — compile the three geo variants into distinct leaves,
  precompute exact per-segment candidate-doc membership once (KD traversal with
  exact verification, legacy column/stored fallback), evaluate Boolean
  membership from that set, and build per-segment distance-sort tables.
- `search/geo.rs` rename-free addition; `search/mod.rs` module wiring.
- `search/typed_compare.rs` — `GeoSortDistances` and distance-aware
  `sort_tuple_for_doc`.
- `contract/result.rs` — additive `SortField::distance_from` and
  `SortField::geo_distance`, with a manual `Eq`.
- `contract/value.rs` — strict `GeoPoint::from_geojson` Point ingestion.
- `contract/error.rs` — `ValueError::MalformedGeoJson` mapping.
- `index/merge.rs` — rebuild the spatial trees from persisted occurrences and
  remap doc ids; bounded legacy fallback; fail closed for unrecoverable legacy
  state.
- `docs/ARCHITECTURE.md` — documented design.

## Semantics

- Bounding box: edges inclusive; `west > east` is `[west, 180] ∪ [-180, east]`;
  `±180` are the same meridian. Longitude membership is computed on the circle.
- Radius: inclusive spherical haversine at the fixed mean radius; near poles and
  the antimeridian the candidate envelope is the full world and the exact
  predicate decides.
- Polygon: planar, non-crossing, non-geodesic; outer boundary inside, hole
  boundary and interior excluded.
- Missing/null/empty contributes no point; a multi-valued document matches if any
  point matches and is returned once.
- Distance sort: minimum point distance, missing last, logical-key tie-break,
  included in the PIT/search-after fingerprint.

## Dispatch and performance

Candidate traversal is synchronous and allocation-conscious. Per-segment
member sets are computed once per leaf and Boolean evaluation is O(1) membership
lookups, so the tree is never traversed per document. The benchmark compares the
public KD candidate traversal against a brute-force exact scan over the same
`SpatialNode` point set (50,000-point build, 30,000 points used; seed-free
deterministic coordinates), and asserts equal hit counts before reporting:

| Arm | Exact predicate checks | Latency (p50, criterion default) |
|---|---|---|
| `geo_kd_candidates` | 1,265 (30,000 nodes pruned) | ≈ 27–29 µs |
| `geo_bruteforce_scan` | 30,000 | ≈ 67–71 µs |

The benchmark intentionally does not claim a speedup for broad shapes where the
generated bounding box covers most of the world; broad queries may still scan all
points, and the typed scan still visits every effective-live document.

## Residual risks

- Spherical, not ellipsoidal, distances.
- Planar, non-geodesic polygons; antimeridian-crossing polygons remain rejected.
- Broad predicates may scan all points; the KD tree trades build/storage for
  narrowing on selective queries.
- Logical decode budgets bound allocations, not process RSS.

---

# Corrective pass (changes requested)

## Files changed

- `crates/quervant-core/src/search/geo.rs` — removed every tolerance from the
  exact predicates. Bounding-box longitude membership splits the circle into
  canonical closed intervals (`[west, east]`, or `[west, 180] ∪ [-180, east]`)
  compared directly with `±180` aliasing; no modulo epsilon and no
  near-full-world shortcut. `longitude_arcs_intersect`/`bbox_intersects_envelope`
  remain conservative: arcs are widened by one ULP and the `±180` seam is
  aliased so a rounded endpoint can never hide a match. `point_on_segment` uses
  the adaptive exact `robust::orient2d` predicate plus exact inclusive bounds;
  ray casting uses the half-open y-straddle and an orientation sign corrected for
  edge direction, testing boundary before parity.
- `crates/quervant-core/src/search/typed.rs` — added the private
  `GeoScratchBudget`, created once per segment in `TypedSearcher::scan` and
  shared by `build_geo_membership`, KD traversal, the legacy fallback and
  `build_geo_sort_distances`. Membership: outer/inner candidate vectors, the DFS
  `Vec<u32>` stack (released after traversal) and all distance-sort tables are
  reserved fallibly with checked arithmetic and charged by actual capacity.
  `max_segment_candidate_entries` is enforced before deduplication; the shared
  limit is `max_total_candidate_bytes`. Cancellation is polled at the start of
  every spatial path and per node/document as before.
- `crates/quervant-core/Cargo.toml`, `Cargo.lock` — added `robust = "1.2.0"`.
- `crates/quervant-core/tests/pr12_common/mod.rs` — replaced the tolerance
  oracle with an exact interval bbox reference and an independent `i128`
  integer-grid polygon reference (checked orientation and integer parity).
- `crates/quervant-core/tests/pr12_geo.rs` — added B/P/O/M/L acceptance tests,
  dyadic integer-grid polygon differential coverage, and a public-wiring
  candidate-limit test.
- `docs/ARCHITECTURE.md` — documented the exact predicates and scratch budget.

## Deviations

- The private helper `longitude_on_arc` is retained (exact, no epsilon) and used
  for the conservative endpoint tests in `longitude_arcs_intersect`; the public
  crate API and the named helpers `longitude_arcs_intersect` and
  `bbox_intersects_envelope` are unchanged.
- `index/merge.rs` was **not** modified: the fail-closed legacy compaction path
  was reproduced through the public lifecycle with a real legacy generation, and
  the existing `CorruptCommittedState` behavior was correct.

## Gate status

All required gates pass; see `validation-report.md`. No unresolved failure and
no scope expansion.
