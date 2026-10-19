# PR 14 — P2B Phase D handoff (partial)

## Completed and validated

`search/typed.rs::GeoScratchBudget`
- `release` is now **checked**: `used.checked_sub(bytes)`; underflow returns
  `SearchError::CorruptIndex` instead of saturating. `reserve_exact` and the geo membership
  stack release propagate the checked result.
- Tests (executed, PASS): `search::typed::phase_d_tests::{d_geo_checked_release_underflow,
  d_geo_exact_limit_and_one_over, d_geo_reserve_exact_charges_capacity}`.

## Remaining D implementation (exact next edits)

The batch sink must be threaded **ephemerally** (not stored across `evaluate_lexical_with`):

1. Add `memory: Option<&mut (dyn MemoryCharge + '_)>` parameters to
   `GeoScratchBudget::{reserve, release, reserve_exact, push_u64, push_u32}`; `reserve` does local
   preflight → batch `preflight` → batch `commit` → local commit; `release` validates
   `used >= bytes` and batch `preflight_release` before mutating either, then batch release then
   local subtraction.
2. Thread the parameter through `build_geo_membership`, `collect_tree_candidates`,
   `collect_legacy_candidates`, and `build_geo_sort_distances` (all `GeoScratchBudget` call
   sites). Standalone typed search passes `None`.
3. In `unified.rs::collect_mixed`, pass the live `scope.as_mut()` reborrow into the builders and
   keep the `GeoMembership`/`GeoSortDistances` batch charges live through
   `evaluate_lexical_with`; after evaluation and sort-tuple construction, explicitly release the
   scratch reservations via the same sink, then drop the structures. Do not hold the sink across
   the typed callback.
4. JSON: inventory `JsonAccess` decoded occurrences/filters; add checked reserves only for owned,
   retained temporary buffers, releasing after their last use. Zero-copy paths are documented as
   zero-charge, not fabricated.
5. Tests: geo membership exact/one-over, batch reject with local unchanged, local reject with batch
   unchanged, multiple memberships, geo+heap overlap, JSON scratch exact/reject, cancellation,
   failed-then-success slot, standalone/batch parity, overflow/underflow.

## Status

Phase D is **partial**: checked release + unit tests done; batch geo/JSON sink binding and the
Phase D acceptance matrix are not implemented. **P2B NOT ACCEPTED. PR 14 NOT READY.**
