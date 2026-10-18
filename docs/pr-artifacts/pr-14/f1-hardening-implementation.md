# PR 14 — F1 hardening implementation report

Base `69d47ba` + uncommitted H1 edits.

## H1 — Shared mixed-query work meter (DONE)

New `search/work.rs`:
- `WorkCharge { check_cancelled, charge, charge_scanned }` and `WorkBudget: WorkCharge { remaining }`.
- `MixedWorkMeter` with `total_used`, `typed_used`, `scanned_used` and independent total/typed/scanned limits. Charges are checked **before** commit; a rejected charge leaves counters unchanged. `charge_scanned_postings(freq)` reproduces the PR 7 `1+freq` total formula.
- `TypedCharge` adapts typed `charge` to `charge_typed` (increments typed and total once).
- Unit tests: aggregate exhaustion after lexical, scanned formula, rejected-charge atomicity.

`search/execute.rs`:
- `SearchWork` is now `Owned` or `Shared(&mut dyn WorkBudget)`. Owned behavior is unchanged. `Shared` forwards every charge/remaining/cancellation check to the mixed meter and owns no counter.
- `evaluate_lexical_with` now takes `&mut MixedWorkMeter` and its callback receives the meter; `build_leaf_data` uses a scoped `SearchWork::shared` so no two mutable borrows overlap.

`search/typed.rs`:
- `ScanGuard` is now `Owned` or `Shared(&mut dyn WorkCharge)`; `ScanGuard::shared` forwards typed charges to `TypedCharge` → `MixedWorkMeter`. Non-work guard responsibilities are unchanged.

`search/unified.rs`:
- `collect_internal` creates exactly one `MixedWorkMeter`; expansion/stats use scoped `SearchWork::shared`, geo preparation and typed evaluation use scoped `TypedCharge` + `ScanGuard::shared`.

Standalone lexical (`SearchWork::new`) and typed (`ScanGuard::new`) paths keep their independent counters and exact prior behavior.

## H2–H5 (preserved from prior pass)
H4 validation order, H2 bounded `BinaryHeap` top-K + `CandidateBudget` global bytes, H3 physical `SelectedHit` projection, H5 geo-distance sort via `build_geo_sort_distances`.

## H6 (extended)
`tests/pr14_f1_hardening.rs` now 16 tests (adds W04 zero-match work charging and W06 mixed cancellation). Existing `pr14_unified_mixed` (14) and `pr14_projection` (10) remain green.

## Not done
Real RustFS and final-SHA CI (no provider/push). No storage/codec/public-contract changes.
