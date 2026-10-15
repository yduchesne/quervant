# PR 11 Follow-up B1 — Pre-implementation correctness gate

**Status:** PRE-CODE GATE (recorded before the production fix; red gate captured first).
**Repository:** `yduchesne/quervant`.
**Baseline `main` (PR #31 merge):** `026f6e045b6cc0956210e8ea941a46d4a0906969`.
**Working branch:** `fix/pr11-json-dfs-frontier`.
**`git status --short` at branch creation:** clean.
**`git merge-base HEAD origin/main`:** `026f6e045b6cc0956210e8ea941a46d4a0906969`.
**Toolchains:** stable `rustc 1.98.1 (48a229cea 2026-09-01)`, MSRV `cargo 1.85.0 (d73d2caf9 2024-12-31)`.

## Verified call graph

`extract_field_paths` (private, `segment/json_paths.rs`) is called by:

- `segment/build.rs` — new-segment JSON-path section build;
- `index/merge.rs` — compaction rebuild from decoded occurrences (legacy stored fallback branch);
- `search/typed.rs::JsonAccess::occurrences` — legacy source fallback.

All three reuse the same DFS. Hardening `extract_value` therefore covers every surface.
`SegmentReader::decode_directory`/`DecodeBudget` are independent and untouched.

### Confirmed defect (before fix)

`extract_value` used `Vec<Frame<'_>>`; when visiting an `Array`/`Object` it pushed **every direct child**
as an independent `Frame` (`for (index, child) in values.iter().enumerate() { stack.push(...) }`,
and the same for object entries), and `charge_occurrence` ran only when a frame was popped. The
pending frontier was therefore proportional to sibling width and was **not** charged against
`max_single_allocation`. `Vec` growth was implicit (`push`), with no `try_reserve`/preflight.

## Counterexamples (reproduced before production changes)

1. Root object with 10,000 members → pending frontier high-water **10,000** (`b1_wide_object_frontier_is_bounded` FAILED with `frontier high-water 10000`).
2. Root array with 10,000 elements → pending frontier high-water **10,000** (`b1_wide_array_frontier_is_bounded` FAILED with `frontier high-water 10000`).
3. A container that is wide at several nesting levels accumulates one `Frame` per already-queued sibling at every ancestor, so the frontier grows with width × active containers, all uncharged.
4. `max_single_allocation` could not bound the frontier: the ceiling was only applied to `estimated` retained occurrences, never to the pending `Vec<Frame>` capacity.
5. The same uncharged frontier is reachable from the builder, compaction and legacy search fallback.
6. A sequence of `push`es could trigger geometric `Vec` reallocation beyond the configured single-allocation ceiling with no typed failure.

## Red-gate evidence (unmodified production)

```
cargo test -p quervant-core --lib nonfinite... (context)
cargo test -p quervant-core --lib b1_wide -- --nocapture
FAILED: frontier high-water 10000   (object)
FAILED: frontier high-water 10000   (array)
```

Test-only instrumentation (`#[cfg(test)]` thread-local `DFS_FRAME_HIGH_WATER`, updated at each push)
exposed the frontier without OOM or timing. After the fix the same tests report high-water ≤ 1.

## Invariant → test mapping

| ID | Invariant | Tests |
|---|---|---|
| B1-I01 | Frontier bounded by active depth, not sibling width | `b1_wide_object_frontier_is_bounded`, `b1_wide_array_frontier_is_bounded` |
| B1-I02 | One identical path/node occurrence per JSON node | `b1_nested_mixed_matches_manual_expected`, `b1_multi_root_prefixes_and_duplicates`, `b1_property_vs_recursive_reference` |
| B1-I03 | Existing occurrence/depth/member/array limits preserved | `b1_depth_boundary_at_and_over`, `b1_member_bytes_and_array_boundaries` |
| B1-I04 | Stack allocation preflighted; typed failure before budget overflow | `b1_stack_capacity_preflight`, `b1_wide_shallow_survives_modest_frontier_budget` |
| B1-I05 | Segment wire/golden digest unchanged | `t13_json_paths_golden_fixture` (existing byte-frozen SHA-256) |
| B1-I06 | Builder/merge/legacy fallback preserve results | `b1_wide_shallow_builder_search`, `b1_compact_wide_indexed_only_json`, `b1_legacy_source_fallback_wide_field` |
| B1-I07 | No partial results, panic, recursion, unbounded child materialization | `b1_property_vs_recursive_reference`, `b1_stack_capacity_preflight` |
| B1-I08 | Unrelated search/mutation/analytics unchanged | full workspace suite |

## Expected failure types

`SegmentError::LimitExceeded { limit, requested }` for every exhausted bound; no panic; no partially
published occurrence vector. Allocation failure is converted to the same typed error. No new error
variant, public limit, configuration, dependency, recursion or wire change.

## Deliberate deviations from the plan (recorded)

- The plan's B1-T06 asks for "configured `max_array_elements` with a small override", but main has no
  such setter and §2 forbids new public limits. A `#[cfg(test)]`-only
  `SegmentLimits::with_max_array_elements_for_test` was added in `segment/limits.rs`; it is absent from
  release builds and changes no default. This is the only change outside `json_paths.rs`/tests/artifacts.
- B1-T08's literal "budget far below `width * size_of::<DfsFrame>()`" is not simultaneously satisfiable
  through `extract_field_paths` because the **retained-occurrence** charge per node is larger than a
  frame and shares the same `max_single_allocation` ceiling, so occurrence accounting fails first.
  B1-T08 asserts a modest budget that bounds the single allocation while allowing occurrences, and the
  frame-growth preflight is isolated directly in `b1_stack_capacity_preflight` (the plan's permitted
  fallback).

## Residual risks

`SegmentLimits` is not a process-RSS limiter. Retained occurrence vectors, cloned paths, stored-source
decoding and builder staging remain governed by their existing budgets; this correction only removes
the uncharged/unbounded pending-child frontier.
