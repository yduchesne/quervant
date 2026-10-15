# PR 12 — Test traceability

All tests run against real production paths (`IndexWriter`/`ReaderSnapshot`/
`TypedSearcher`, real `SegmentReader`, `MemoryDirectory` and `FsDirectory`) plus
a test-only brute-force oracle that never calls the production KD tree, codec or
geometry predicates.

## Invariants

| ID | Invariant | Represented by |
|---|---|---|
| I01 | Exact predicate: no false positives/negatives | `t04`, `t06`, `t07`, `t17_seeded_oracle_bbox_radius_polygon`, `t17_oracle_polygon`, `search::geo` unit tests |
| I02 | All multivalue points retained, doc deduplicated | `t02`, `t12`, `segment::spatial::round_trip_and_determinism` |
| I03 | Boundaries, poles, ±180 and polygon holes correct | `t04`, `t06`, `t07`, `search::geo::bbox_inclusive_and_crossing`, `search::geo::polygon_interior_boundary_and_holes` |
| I04 | Deterministic, bounded, corruption-fail-closed codec | `t09`, `t10`, `t10b`, `t11`, `t16`, `segment::spatial::golden_single_node_bytes`, `golden_three_node_tree_bytes`, `encode_rejects_over_limit`, `malformed_node_is_rejected` |
| I05 | No silent point loss in legacy/compaction | `t12`, `t12b`, `search::typed::legacy_geo_tests::legacy_column_fallback_and_unrecoverable` |
| I06 | Live mask, PIT, Boolean/NOT preserved | `t13`, `t15` |
| I07 | Distance sort and cursor deterministic | `t14` |
| I08 | Existing JSON/lexical/typed/wire unchanged | full workspace suite; `t15`; `contract::query` and `contract::value` suites |

## Mandatory test matrix

| Test | Case | Location |
|---|---|---|
| T01 | Empty index, zero-point field, missing/null/empty | `t01_empty_zero_point_missing_null_empty` |
| T02 | Single/multivalue, duplicate coordinates, ordinals | `t02_multivalue_duplicates_and_ordinals` |
| T03 | Invalid/nonfinite coordinates and malformed GeoJSON | `t03_invalid_coordinates_and_geojson` |
| T04 | Inclusive bbox boundaries, crossing bbox, ±180 equivalence | `t04_bbox_boundaries_crossing_alias` |
| T05 | Zero/negative/NaN/infinite radius rejected pre-I/O | `t05_radius_invalid_is_rejected` |
| T06 | Radius poles, antimeridian, antipodes and full-world | `t06_radius_geometry` |
| T07 | Polygon interior/exterior/vertex/outer edge/hole edge | `t07_polygon_contains` |
| T08 | Existing unsupported crossing polygon rejected | `t08_unsupported_polygons_rejected` |
| T09 | Feature/section mismatch, truncated/valid-digest corruption | `t09_feature_section_mismatch_fails_closed` |
| T10 | Cycles, unreachable nodes, false bbox, invalid doc/ordinal, NaN | `t10_malformed_nodes_and_geometries_fail_closed`, `t10b_thirty_malformed_node_cases` (35 digest-valid malformed bodies) |
| T11 | Exact-limit/over-limit and cancellation build/search/merge | `t11_limits_and_cancellation`, `segment::spatial::encode_rejects_over_limit`; merge cancellation is covered by the existing PR 9 merge suite (unchanged contract) |
| T12 | Indexed-not-stored compaction and recoverable/unrecoverable legacy | `t12_compaction_preserves_indexed_points`, `t12b_indexed_only_geopoint_survives_compaction`, `legacy_column_fallback_and_unrecoverable` |
| T13 | Delete/upsert/refresh/PIT/reopen generation consistency | `t13_lifecycle_generations` |
| T14 | Distance ties/missing/multivalue/PIT pagination | `t14_distance_sort` |
| T15 | AND/OR/NOT with time/JSON/lexical, tombstones | `t15_boolean_and_tombstones` |
| T16 | Deterministic build/golden SHA and remap | `t16_deterministic_build`, golden byte tests |
| T17 | Large dataset, narrow/broad shapes, bounded work | `t17_seeded_oracle_bbox_radius_polygon`, `t17_oracle_polygon` (300 seeded cases + 120 polygon points), benchmark |
| T18 | Concurrent snapshots, FsDirectory restart, write failure | `t18_fs_directory_restart`; concurrent immutable snapshot semantics are inherited from PR 6 and exercised by the unchanged full suite |

## Independent oracle

The oracle in `tests/pr12_common/mod.rs` is a separate implementation of the
circular bounding-box test, haversine and ray-casting polygon containment, with
explicit inclusive/alias/hole rules. It operates on the original
`(key, points)` list, not on the production KD tree, column reader or `GeoAccess`.
`t17_seeded_oracle_bbox_radius_polygon` runs 300 deterministic seeded cases
(SplitMix64 seed `0x5151_2024`, 0–1000 docs, 0–8 points/doc) and compares sorted
hit keys against the oracle for both bounding boxes and radius predicates.
Hand-verified reference values (zero distance, equatorial quarter-circumference,
±180 alias) are asserted in `search::geo::haversine_reference_values`.

## Counterexamples explicitly covered

- first-point-only: `t02` (multi-point matches), `t12`
- exclusive edges: `t04`, `t07`
- wrong meridian alias: `t04`, `search::geo::bbox_envelope_pruning_never_false_prunes_alias`
- false pruning: `t04`, seeded oracle
- stale doc id: `t09`, `t10` (out-of-range doc id), `t12` (remap)
- NOT-complement errors: `t15`
