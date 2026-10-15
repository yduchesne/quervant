# PR 11 Follow-up B1 — Invariant and test traceability

**Branch:** `fix/pr11-json-dfs-frontier`
**Base:** `main` `026f6e045b6cc0956210e8ea941a46d4a0906969` (PR #31 merge).
**Tested state:** branch working tree immediately before commit; `cargo test` results recorded below.
**Toolchains:** stable `rustc 1.98.1`, MSRV `1.85.0`.

| ID | Invariant | Required tests | Actual result |
|---|---|---|---|
| B1-I01 | Frontier bounded by active depth, not sibling width | B1-T01 `b1_wide_object_frontier_is_bounded`, B1-T02 `b1_wide_array_frontier_is_bounded` | PASS — high-water ≤ 1 (was 10,000 pre-fix) |
| B1-I02 | One identical concrete path/node per JSON node | B1-T03 `b1_nested_mixed_matches_manual_expected`, B1-T04 `b1_multi_root_prefixes_and_duplicates`, B1-T13 `b1_property_vs_recursive_reference` | PASS |
| B1-I03 | Pre-existing occurrence/depth/member/array limits enforced | B1-T05 `b1_depth_boundary_at_and_over`, B1-T06 `b1_member_bytes_and_array_boundaries` | PASS |
| B1-I04 | Stack allocation preflighted; typed failure before over-budget growth | B1-T07 `b1_stack_capacity_preflight`, B1-T08 `b1_wide_shallow_survives_modest_frontier_budget` | PASS |
| B1-I05 | Segment wire and golden digest unchanged | B1-T09 `pr11_json_corruption::t13_json_paths_golden_fixture` | PASS — SHA-256 `0528a62c…a02f` unchanged |
| B1-I06 | Builder/merge/legacy fallback preserve results/error propagation | B1-T10 `pr11_json_paths::b1_wide_shallow_builder_search`, B1-T11 `pr11_json_mutations::b1_compact_wide_indexed_only_json`, B1-T12 `typed::legacy_json_tests::b1_legacy_source_fallback_wide_field` | PASS |
| B1-I07 | No partial results, panic, recursion, unbounded child materialization | B1-T13 `b1_property_vs_recursive_reference`, B1-T02, B1-T07 | PASS |
| B1-I08 | Unrelated search/mutation/analytics unchanged | B1-T14 workspace suite + PR 11 suites | PASS |

## Independent oracles / controls

- **High-water observer:** `#[cfg(test)]` thread-local updated at each frame push; B1-T01/T02 assert
  `max_frames <= 1` and the old algorithm measured exactly `10,000`.
- **Manual expected vector:** B1-T03 enumerates all 9 occurrences for a fixed mixed tree, independent
  of the traversal.
- **Recursive reference walker:** B1-T13 compares 250 seeded generated trees (seed `0xB1_2026`, depth
  0–8, width 0–32, node budget 512) against a simple recursive walker; sorted `(path,node)` equality.
- **Signed-zero / finite controls:** existing A1 tests remain green.
- **Golden:** byte-frozen fixture with asserted SHA-256; not regenerated.

## Counts

| Suite | Tests |
|---|---|
| `segment::json_paths` unit (incl. 9 `b1_*`) | 21 |
| `search::typed::legacy_json_tests` unit (incl. 1 `b1_*`) | 2 |
| `pr11_json_paths` | 10 |
| `pr11_json_mutations` | 7 |
| `pr11_json_corruption` | 8 (+1 ignored fixture generator) |
| `pr11_json_properties` | 4 |
| `cargo test --workspace --all-targets` (stable) | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS |
| `cargo llvm-cov --fail-under-lines 85` | PASS — **91.78% line**, 87.97% branch, 91.39% function |

## Deliberate deviations

- Test-only `SegmentLimits::with_max_array_elements_for_test` (no release surface) to exercise the
  existing array guard cheaply.
- B1-T08 asserts a modest (not sub-`width*frame_bytes`) budget because the retained-occurrence charge
  dominates the same ceiling; frame preflight is isolated directly in B1-T07.
