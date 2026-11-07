# PR 15H-D — invariant traceability

The D candidate was implemented and tested at `0f97779`, then performance-
rejected and rolled back to `c802f96`. Production source is byte-identical to A.

| D-K | Invariant | Evidence | Candidate | Final |
|---|---|---|---|---|
| D-K01 | Validation ordering unchanged | `d_u01_u02_u06_u14...`; existing phase4 | PASS | restored |
| D-K02 | Cursor/fingerprint before compile | source order unchanged; existing cursor tests | PASS | restored |
| D-K03 | Identical compiled plan | `d_u03_u04_u05_plan_equivalence` | PASS | restored |
| D-K04 | One resolve/build per normal request | call graph + `compile_with_resolved` delegation | PASS | restored |
| D-K05 | Sibling callers unchanged | `select_keys` still calls `compile`; test | PASS | restored |
| D-K06 | Score/order/count/projection/cursor | `d_u07_u09_u10...`; full suites | PASS | restored |
| D-K07 | Error/resource semantics | unchanged compiler body; U/phase4/corruption suites | PASS | restored |
| D-K08 | PIT/commit/mutation | B integration + full suites | PASS | restored |
| D-K09 | No format/cache/API change | source diff; equal index digests | PASS | PASS |
| D-K10 | Exact rollback | `git diff --quiet c802f96 HEAD -- unified.rs unified_plan.rs` | n/a | PASS |
| D-K11 | Batch/aggregation | existing batch/aggregation suites | PASS | restored |
| D-K12 | Measurement integrity | D controller tests + seals | PASS | PASS |

## D-U tests executed at candidate

| ID | Test | Result |
|---|---|---|
| D-U01/U02/U06/U14 | `d_u01_u02_u06_u14_validation_and_empty_index` | PASS |
| D-U03/U04/U05 | `d_u03_u04_u05_plan_equivalence` (MatchAll/Term/And/Or/Not/Phrase/Prefix/Glob/Regex/Fuzzy/Exists) | PASS |
| D-U07/U09/U10 | `d_u07_u09_u10_search_and_cursor_parity` | PASS |
| D-U08/U11–U13/U15/U16 | Existing two-segment/corruption/cancellation/budget/legacy-norm suites | PASS |
| D-U05 witness | Single resolution proved by the `compile` → `compile_with_resolved` delegation and the source call graph; no release counter added | PASS (source) |

## D-T controller tests

`benchmarks/pr15h_d/test_run.py` — 49 tests, covering D-T01–D-T20: lanes/order,
mirrored schedule, samples/warmups, tooling identity (including pre-output
blocking), corpus/index/host/oracle/probe, D conventional/lower median boundaries,
source-scope allowlist, seal/report tamper and read-only `--verify-only`.

## D-I integration

Existing real-boundary suites were executed at candidate and rollback:
`pr15h_b_sort_materialization` (FsDirectory 50K, two segments, PIT, cursor,
multi/typed, corruption), `pr15h_a_candidate_materialization`,
`pr15h_a2_dispatch`, and the full real RustFS matrix. No new production-boundary
behavior was introduced; D changes only duplicate resolution.
