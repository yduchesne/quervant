# PR 14 — F1 hardening adversarial review (verification pass)

## Charge-site audit (no bypass of the authoritative meter)

Lexical paths, all taking `&mut SearchWork` (mixed supplies `SearchWork::shared`):
- `expand.rs::expand_query` → `TermFst::preflight_build` (`charge`, `remaining`, `check_cancelled`).
- `score.rs::compute_stats` → `lookup_term` (`charge(1)`), `charge_scanned`, `check_cancelled`.
- `execute.rs::build_leaf_data` (`charge_scanned`, `check_cancelled`).
- `execute.rs::build_phrase` → `phrase.rs::match_phrase` (`charge(1)`, `check_cancelled`).

Typed paths, all taking `&mut ScanGuard` (mixed supplies `ScanGuard::shared`):
- `typed.rs::evaluate_query` and `JsonAccess::match_*`/`occurrences` (`guard.charge`, `guard.poll`).
- `typed.rs::build_geo_membership` → `collect_tree_candidates`/`collect_legacy_candidates` (`guard.charge`, `guard.poll`).
- `typed.rs::build_geo_sort_distances` (`guard.poll`, `guard.charge`).

`SearchWork::new` appears only in the standalone `execute_search` path and tests;
`ScanGuard::new` only in `TypedSearcher::{search,aggregate}` and tests. The mixed path uses only
`SearchWork::shared`, `ScanGuard::shared`, `TypedCharge`, and `MixedWorkMeter`. No direct counter
mutation exists outside `work.rs`. Scoring (`score_segment`) and sort-tuple reads are not work
charge sites in the original design, so their absence is preserved, not a bypass.

## Exact-limit / first-excess evidence

| Limit | At limit | First excess | Counter after rejection |
|---|---|---|---|
| aggregate total | `total_exact_limit_then_one_over` (10 ok) | `charge_lexical(1)` → `ResourceLimit { limit:10, requested:11 }` | unchanged (10) |
| typed | `typed_exact_limit_then_one_over` (5 ok) | `charge_typed(1)` → `{ limit:5, requested:6 }` | unchanged (5) |
| scanned | `scanned_exact_limit_then_one_over` (10 ok, total 11) | `charge_scanned_postings(1)` → `{ limit:10, requested:11 }` | unchanged (11) |
| candidate bytes | `production_global_bytes_exact_then_one_over_and_release` (100 ok) | `reserve_global_bytes(1)` → `{ limit:100, requested:101 }` | unchanged (100) |

## Cancellation propagation

`SearchWork::shared::check_cancelled` and `ScanGuard::shared::poll` both forward to
`MixedWorkMeter::check_cancelled`. `charge` polls at the 256-unit interval. Coverage:
`shared_adapters_forward_charges_and_cancellation` (both adapters, before and after cancel),
`w06_mixed_cancellation` (per-document mixed loop), `m06_multi_segment_cancellation` (2 segments),
plus existing PR 10 typed cancellation tests. No hidden reconciliation charges.

## Standalone semantics

Owned `SearchWork`/`ScanGuard` behavior is unchanged; `search::execute::budget_tests` (22),
`search::typed::tests` (4), `pr07_amendment01/02/03`, `pr10_aggregate_memory`, `pr10_cursor` all
pass. The only observable difference is that `MixedWorkMeter` validates before committing a charge
(stricter atomicity), which does not change success-path behavior or the returned error.

## Residual risks
1. `M03` is evidenced at the `CandidateBudget` primitive (and via the bounded heap implementation),
   not by a full end-to-end one-byte-over search; the search path uses the same primitive.
2. Real RustFS and final-SHA CI remain blocked.
3. The 256-unit cancellation polling cadence is inherited from PR 7; the mixed loop additionally
   checks cancellation once per effective-live document.
