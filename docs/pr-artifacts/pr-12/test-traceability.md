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

---

# Corrective pass traceability

## P1 — exact bounding boxes (`crates/quervant-core/src/search/geo.rs`)

| ID | Test | Result |
|---|---|---|
| B01 | `search::geo::tests::b01_four_exact_edges_included` | PASS |
| B02 | `search::geo::tests::b02_adjacent_ulp_longitude_outsiders_excluded` | PASS |
| B03 | `search::geo::tests::b03_adjacent_ulp_latitude_outsiders_excluded` | PASS |
| B04 | `search::geo::tests::b04_degenerate_box_matches_exactly` | PASS |
| B05 | `search::geo::tests::b05_antimeridian_aliases` | PASS |
| B06 | `search::geo::tests::b06_crossing_170_to_minus_170` | PASS |
| B07 | `search::geo::tests::b07_near_full_world_gap_excluded` | PASS |
| B08 | `search::geo::tests::b08_signed_zero` | PASS |
| B09 | `search::geo::tests::b09_seam_boundary_inclusion` | PASS |
| B10 | `search::geo::tests::b10_pruning_never_false_prunes_seams` + `longitude_arcs_intersect_is_conservative` + seeded oracle | PASS |

## P2 — exact robust polygons (`crates/quervant-core/src/search/geo.rs`)

| ID | Test | Result |
|---|---|---|
| P01 | `p01_outer_edge_included` | PASS |
| P02 | `p02_just_outside_outer_excluded` | PASS |
| P03 | `p03_just_inside_outer_included` | PASS |
| P04 | `p04_hole_edge_excluded` | PASS |
| P05 | `p05_hole_interior_excluded` | PASS |
| P06 | `p06_just_outside_hole_included_and_ulp_not_boundary` | PASS |
| P07 | `p07_horizontal_vertical_slanted` | PASS |
| P08 | `p08_vertex_ray_height_parity` | PASS |
| P09 | `p09_reversed_ring_order_equivalent` | PASS |
| P10 | `p10_adjacent_ulp_outsiders_never_boundary` | PASS |

## P5 — independent oracle (`tests/pr12_common/mod.rs`, `tests/pr12_geo.rs`)

| ID | Test / evidence | Result |
|---|---|---|
| O01 | `t17_seeded_oracle_bbox_radius_polygon` (300 seeded cases, 0–1000 docs, 0–8 points/doc) and `t17_oracle_polygon` (dyadic integer-grid) | PASS |
| O02 | Oracle uses its own `oracle_bbox_intervals`/`integer_orient`/`integer_ring_position`; no `search::geo`, KD or codec call (source inspection) | PASS |
| O03 | `o03_tolerance_predicate_is_detected_by_oracle` — a local `+ 1e-12` predicate accepts an adjacent-ULP outsider while the exact oracle rejects it, so an epsilon regression is red | PASS |
| O04 | `o04_integer_grid_polygon_edges` — outer/hole/edge/vertex/exterior dyadic cases compared to the `i128` grid reference | PASS |

## P3/P4 — scratch budgets (`search/typed.rs`)

| ID | Test | Result |
|---|---|---|
| M01 | `m01_m02_m03_candidate_entry_limit` (exact pre-dedup limit) + `m01_m02_public_candidate_entry_limit` (public `SearchLimits`) | PASS |
| M02 | `m01_m02_m03_candidate_entry_limit` (one over) + public wiring test | PASS |
| M03 | `m01_m02_m03_candidate_entry_limit` (duplicates consume the pre-dedup budget) | PASS |
| M04 | `m04_two_leaves_combined_scratch` | PASS |
| M05 | `m05_stack_exceeds_tiny_budget` | PASS |
| M06/M07 | `m06_m07_m08_m09_distance_sort_exact_budget` (exact / one byte short) | PASS |
| M08/M09 | `m06_m07_m08_m09_distance_sort_exact_budget` | PASS |
| M10 | `m10_two_sort_fields_combined_scratch` | PASS |
| M11 | `m11_membership_plus_sort_combined_scratch` | PASS |
| M12 | `m12_physical_doc_count_bounds_table` | PASS |
| M13 | `m13_overflow_and_allocator_refusal_are_typed` | PASS |
| M14/M16 | `m14_m16_cancellation_on_spatial_paths` | PASS |
| M15 | `search::typed::legacy_geo_tests::m15_legacy_cancellation_is_observed` | PASS |

## P6 — fail-closed legacy compaction (`tests/pr12_geo.rs`)

| ID | Evidence | Result |
|---|---|---|
| L01 | `l01_l04_legacy_unrecoverable_compaction_fails_closed`: real `FsDirectory` legacy v1 manifest with two spatial-stripped segments opens and a held snapshot is usable | PASS |
| L02 | Same test: public `IndexWriter::compact` returns `IndexError::CorruptCommittedState` | PASS |
| L03 | Same test: `CURRENT` generation, manifest count and held snapshot unchanged | PASS |
| L04 | Same test: retry fails identically with no partial publication | PASS |

## R — regressions

| ID | Existing coverage | Result |
|---|---|---|
| R01 | `segment::spatial` golden bytes / malformed nodes; `t09`, `t10`, `t10b` | PASS |
| R02 | `t14_distance_sort`; PR 10 sort suite | PASS |
| R03 | `t15_boolean_and_tombstones`; PR 10 aggregate suite | PASS |
| R04 | `t14_distance_sort` cursor continuation; PR 10 cursor suite | PASS |
| R05 | `t12b_indexed_only_geopoint_survives_compaction` | PASS |
| R06 | `t12`, `t18_fs_directory_restart`, `l01_l04_legacy_unrecoverable_compaction_fails_closed` | PASS |
