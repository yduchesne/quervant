# PR 14D — test traceability

Implementation commit: `d0e1bbb` (baseline `2cb91be`). All rows were executed
locally on stable 1.98.1 and MSRV 1.85.0, and the provider rows against the
pinned RustFS digest. Commands and counts: `validation-report.md`.

## 1. Frozen decisions AD-01…AD-12

| ID | Requirement | Evidence | Result |
|---|---|---|---|
| AD-01 | Scope limited to sort transient-memory accounting | diff: `search/typed.rs`, `search/unified.rs`, `segment/json_paths.rs`, `segment/mod.rs`, tests/docs only | PASS |
| AD-02 | Reuse `MemoryCharge`/`SlotMemoryScope`, keep `BatchMemoryBytes` failure | `OccurrenceScratchSink`, `JsonSortScratch`, `pr14d` D01/D05; no new meter | PASS |
| AD-03 | Private scratch owner with reserve/release/finish/Drop | `JsonSortScratch`; unit `t01`–`t09` | PASS |
| AD-04 | Thread memory through typed and unified; `None` only non-batch | `accept(..., memory)`, `collect_mixed` passes `scope`; typed passes `None` | PASS |
| AD-05 | Preflight capacity growth before allocation, reconcile actual | `push_occurrence`; unit `t08`; D02 threshold growth | PASS |
| AD-06 | Legacy batch sort not routed through unmetered bulk extraction | `extract_field_paths_charged` with sink; unit `t09` | PASS |
| AD-07 | Charge owned path/member/node bytes; qualify bounded decode transient | `retained_owned_bytes` + sink; `resource-characterization.md` limitation | PASS (with qualified transient) |
| AD-08 | Single-pass Min/Max winner, no second `Vec<FieldValue>` | `json_sort_value` rewrite; D03/D08 | PASS |
| AD-09 | Concurrent charging, no double charge/release, retained transfer | `t07`; `finish` before heap charge; D04/D05 | PASS |
| AD-10 | Cancellation/error releases scratch, siblings isolated | `t03`; D05/D06; provider F01–F09 | PASS |
| AD-11 | No public API/cursor/snapshot/disk contract change | `compatibility-report.md`; `git diff` path audit | PASS |
| AD-12 | Local exact/one-under, real provider, B20/B21, stable/MSRV/coverage, CI | D01–D16 + gates; final-SHA CI pending | PASS except CI (see final acceptance) |

## 2. Required deterministic cases

| ID | Assertion | Test / command | Result |
|---|---|---|---|
| D01 | Exact admission succeeds; one-under typed failure before full materialization | `pr14d_json_sort_memory::d01_d09_exact_admission_and_small_budget_rejection` | PASS |
| D02 | 1/128/4096 charged thresholds grow; not the old constant | `…::d02_charged_threshold_grows_with_occurrences` (387 / 45,726 / 1,462,302 B) | PASS |
| D03 | Min/Max over mixed scalar types, null/missing ordering | `…::d03_mixed_scalar_min_max_order` | PASS |
| D04 | Typed standalone vs unified vs pinned: same keys, totals, cursor presence | `…::d04_typed_unified_and_pinned_parity` | PASS |
| D05 | Batch S/F/S with a middle typed memory failure; later slot fresh | `…::d05_d10_sibling_isolation_and_repeat_cleanup` | PASS |
| D06 | Cancellation before/during work is typed, no partial success | `…::d06_cancellation_is_typed`; provider `real::d12` cancellation branch | PASS |
| D07 | Corrupt historical bytes rejected; unstored legacy field typed | `…::d07_historical_fixture_digest_and_corruption`; unit `t09`; `b18_b19` regression | PASS |
| D08 | Zero/one/many occurrences, non-matching path, null-only, multi Min/Max | `…::d08_multivalue_min_max_and_shape_handling` | PASS |
| D09 | Small fixed budget fails typed at first unaffordable admission, no RSS claim | `…::d01_d09_…` (`exact/4`) | PASS |
| D10 | 100 repeated runs + interleaved cancellation/one-under: no accumulation | `…::d05_d10_…` | PASS |
| D11 | Real provider JSON sort exact/one-under + local oracle | `pr14_storage_vertical::real::d11_real_json_sort_memory_exact_and_one_under` (`--ignored --exact`) | PASS |
| D12 | Real provider mixed lexical/JSON sort: S/F/S, cancellation, old/new PIT | `real::d12_real_json_sort_mixed_sibling_cancellation_and_pit` | PASS |
| D13 | Historical v1 fixture compatible; corrupt/unsupported rejected; no rewrite | `d07` (frozen SHA-256) + `b18_b19` regression + `real::b18` | PASS |
| D14 | B20/B21 recharacterization prints post-fix thresholds/peaks, no RSS claim | `pr14b_json_memory` updated assertions | PASS |
| D15 | Overflow/underflow and failed-growth cleanup leave exact prior state | unit `t02`, `t05`, `t08`, `t09` | PASS |
| D16 | Existing PR14A/B, PR13 and batch/JSON regressions remain green | workspace 2036/2040 tests; provider 13 verticals + faults + PR13 suites | PASS |

## 3. Fault matrix FS01–FS08

| ID | Scenario | Evidence | Result |
|---|---|---|---|
| FS01 | Indexed cursor malformed/truncated | `d07` corruption; `real::b18`; `pr11` corruption suites (D16) | PASS |
| FS02 | Legacy stored JSON malformed | `t09` rejection; legacy decode errors unchanged (D16) | PASS |
| FS03 | Budget one-under | `d01`, `d05`, provider `d11`, `real::r10_r11` | PASS |
| FS04 | Cancellation at initial scan | `d06`; provider `d12` | PASS |
| FS05 | Cancellation after partial traversal | `pr14_storage_faults::f06`; `pr14a_public_cursor::t13` | PASS |
| FS06 | Candidate heap admission failure after sort | `d05` (middle slot) | PASS |
| FS07 | Batch middle-slot error then successful sibling | `d05`, provider `d12` | PASS |
| FS08 | Remote transient/truncated GET and recovery | `pr14_storage_faults` F01–F09 (10 iterations each) | PASS |

## 4. Provider symbol inventory executed

- `pr14_storage_vertical::real::{d11…, d12…, b02…, b06_b07…, b18…, r01…, r02_r04_r06…, r03…, r05…, r08_r09_r15…, r10_r11…, r12…, r13_r14…}` — 13/13 PASS.
- `pr14_storage_faults` F01–F09/F10 — 9/9 PASS × 10 iterations.
- `pr13_remote_proxy` h06–h12 — 7/7; `pr13_crash_rustfs` k01–k05 — 5/5.
- `quervant-objectstore` `pr13_s3_rustfs` 8/8, `pr13_proxy_rustfs` 5/5.
- `pr13_remote` real 3/3, `pr13_oracle` real 1/1, `pr13_oracle_geo` real 1/1.

No fake substituted for a real-boundary assertion. Child entrypoints were
executed only by their parents.
