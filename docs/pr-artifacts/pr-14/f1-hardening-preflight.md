# PR 14 — F1 hardening preflight

- Branch: `dev/pagination`
- `main` SHA: `7ca1b2ec59fec648602e0e4a52e8f903a596f106`
- Amendment base HEAD: `69d47babd4232eba78325ba061fe33228f8dad9f`; H1 edits uncommitted at report time.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`.

## H1 call graph and charge sites (verified from source)

| Path | Function | Charge |
|---|---|---|
| mixed scope | `UnifiedSearcher::collect_internal` | owns one `MixedWorkMeter` |
| expansion | `expand.rs::expand_query` → `TermFst::preflight_build` | `charge(1+term_bytes)`, `remaining()` |
| statistics | `score.rs::compute_stats`/`lookup_term` | `charge(1)`, `charge_scanned(freq)`, `check_cancelled` |
| leaf build | `execute.rs::build_leaf_data` | `charge_scanned(posting.freq)` |
| phrase | `execute.rs::build_phrase` → `phrase.rs::match_phrase` | `charge(1)`, `check_cancelled` |
| typed | `typed.rs::evaluate_query` / geo builders via `ScanGuard` | `guard.charge(1)`, `guard.poll()` |

Work units: `charge(n)` = n total units; `charge_scanned(freq)` = freq scanned units **and** `1+freq` total units (PR 7 formula). Typed units additionally count against `max_typed_work_units`; scanned against `max_scanned_posting_occurrences`. Limit inclusivity and `SearchError::ResourceLimit` semantics are unchanged.

## Borrowing plan (implemented)

- `SearchWork` and `ScanGuard` gained a `Shared` variant that owns **no** counter and forwards to a `&mut dyn WorkBudget` / `&mut dyn WorkCharge`.
- The mixed executor owns `MixedWorkMeter`; short-lived `SearchWork::shared(&mut meter)` scopes wrap expansion, stats and leaf building; the typed callback receives the meter directly and wraps it in a scoped `TypedCharge` + `ScanGuard::shared`.
- No `Rc<RefCell>`, unsafe, global state, or post-hoc reconciliation. `SearchWork`/`ScanGuard` `Owned` modes are unchanged for standalone lexical/typed searches.

## Contract conflict check

Units, limit scopes and error variants are compatible: both rely on the same `max_total_work_units` and `ResourceLimit`; no policy redesign was required. No STOP condition remains.

## I01–I10 → tests

| ID | Tests |
|---|---|
| I01/I02 | `work::tests::aggregate_exhaustion_blocks_typed_after_lexical`, W04/W06 |
| I03 | `work::tests::rejected_typed_charge_does_not_mutate_counters`, differential S/V |
| I04 | W05 (pure suites), PR 7/10 regressions |
| I05/I06 | ownership review + `work::tests` |
| I07 | S01–S05, M02, G01–G03, P02 |
| I08 | M01–M06 / M02 |
| I09 | W01/W06 |
| I10 | W04, call-site inventory above |
