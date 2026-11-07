# PR 15H-A2 — preflight and frozen experiment definition

**Plan:** `QUERVANT_PR15H_A2_DETAILED_IMPLEMENTATION_PLAN.md` v1.0 (`H_A2_PLAN`)
**Branch:** `dev/pr15h-a2-cardinality-gated-linear`
**Branch base:** `7a136f7f299c2f460401b9d92dcef37d219ea98c` (PR 15H-A rollback head)

## 1. Source provenance

| Identity | SHA |
|---|---|
| `origin/main` / `main` | `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078` |
| PR 15H-A final branch HEAD | `7a136f7f299c2f460401b9d92dcef37d219ea98c` |
| PR 15H-A rejected candidate | `dce8f02405e6541d478c2072a0332af192ed2945` |
| A2 harness-only commit (`H_A2_TOOLING_SHA`) | `9aff92b6b1a12ee323ed7994a177f88949c736fd` |

- `git fetch origin main` left `main` unchanged (A2-D01, not D02/D03).
- `git diff --quiet ddcbe778… 7a136f7… -- crates/quervant-core/src/search`
  exits 0: the accepted production search is byte-identical to `main` (A2-D04).
- Rejected candidate diff vs accepted baseline is exactly two source files:

```
654  31  crates/quervant-core/src/search/execute.rs
311   0  crates/quervant-core/src/search/unified.rs
```

  Matching the plan's `+654/−31` and `+311/−0` expectation (A2-D06/D09).
- `score.rs` is unchanged by the candidate.
- `evaluate_single_term_linear` + historical helper region at `dce8f02`:
  `sha256 = 966554bccc5d5d5a852c53713ec566122981de480a40157e92b7e6be100f1592`
  (recorded before any A2 edit; A2-D12).
- Candidate test-only witnesses and `linear_term_tests` are present at `dce8f02`.

## 2. Accepted-baseline source hashes (`7a136f7`)

| File | SHA-256 |
|---|---|
| `search/execute.rs` | `b49d49f7d8104f10e98bea82e7a30b80652dd87b5b78c083bf9f1384ea8edb55` |
| `search/unified.rs` | `b810fe68e23f0efb0bdb09a074dd4fdc90d0f9358a7b5668443175b1afeb1e2d` |
| `search/score.rs` | `f03712ec16822a343002346a1bf596f292ed7884411fc1a4b0dbe7ba911caf16` |

## 3. Harness transformation review (A2-B00 / A2-D16)

`benchmarks/pr15h_a2/{run.py,test_run.py}` were produced from
`benchmarks/pr15h_a/*` at `7a136f7` by the prescribed ordered replacements:

1. `pr15h-a` → `pr15h-a2` (schemas, confinement, prose, report markers).
2. `pr15h_a` → `pr15h_a2` (module/path literals).
3. `PR15H_A` → `PR15H_A2` (printed stage marker).
4. Whole line `STAGE = "15h-a"` → `STAGE = "15h-a2"`.
5. Whole line `PHASE = "linear-single-term-candidates"` →
   `PHASE = "cardinality-gated-linear-single-term-candidates"`.
6. `HA-P` → `HA2-P` (gate tokens only).
7. `ALLOWED_CHANGED_PREFIXES` exactly
   `("benchmarks/pr15h_a2/", "docs/pr-artifacts/pr-15h-a2/")`.
8. `ALLOWED_CHANGED_EXACT` exactly `execute.rs`, `unified.rs`,
   `tests/pr15h_a2_dispatch.rs`, `docs/BENCHMARKING.md`,
   `docs/PERF_OPTIMIZATION_PLAN.md`; the historical
   `pr15h_a_candidate_materialization.rs` is removed from the allowlist.
9. Frozen lanes, schedule, statistics, oracle, sealing, sanitizer, path
   confinement and verdict Boolean formulas unchanged.

Review results:

- `run.py` diff vs historical: 68 changed lines, all identity/allowlist.
- `test_run.py` diff: 109 changed lines (identity/gate tokens plus five new
  A2 source-scope/sanitization/path/ancestry tests).
- No `pr15h-a22`, `15h-a22` or `pr15h_a22` token exists.
- `python3 -m unittest discover -s benchmarks/pr15h_a2 -p 'test*.py'` → 26 passed.
- `python3 -m py_compile` → OK.
- The historical `benchmarks/pr15h_a/` and `docs/pr-artifacts/pr-15h-a/` are
  untouched and are **not** newly modifiable.

## 4. Frozen experiment (fixed before any candidate exists)

| Item | Frozen value |
|---|---|
| Dispatch threshold | `H_A2_MIN_POSTINGS: usize = 8_192` |
| Lanes | P1 `100000/medium/k100`, P2 `100000/common/k100`, P3 `100000/common/k10`, G1 `10000/common/k100`, G2 `10000/rare/k100`, G3 `100000/rare/k100`, G4 `100000/absent/k100` |
| Schedule | 4 mirrored blocks `A,B / B,A / B,A / A,B` |
| Baseline | 3 trials x 7 lanes x (5 warmups + 20 samples) |
| Paired | 8 slots, 56 lane records, 1,120 samples, 280 warmups, 16 probes, 56 oracles |
| Drift caps | 1.25 for 100K, 1.50 for 10K, inclusive at the cap |
| Verdict | sign of all four B/A ratios; equality is `INCONCLUSIVE` |
| Gates | HA2-P00–P06 exactly as the plan |

## 5. Counterexample checklist (mapped to §8 tests)

| Case | Test |
|---|---|
| 0 postings | A2-U01 (`a2_u01_zero_postings_legacy`) |
| 1 posting | A2-U02 (`a2_u02_single_posting_legacy`) |
| 4,999 postings | A2-U03 (`a2_u03_below_threshold_legacy`) |
| 8,191 / 8,192 / 8,193 | A2-U05/U06 (`a2_u05_u06_threshold_boundary`) |
| 12,500 / 49,999 | A2-U04 (`a2_u04_high_cardinality_linear`) |
| 8,192 decoded but subset matches | A2-U19 (`a2_u19_callback_subset_ordering`) |
| high-count then low-count segment | A2-U10 (`a2_u10_two_segment_routes`) |
| cancellation early/late | A2-U08 (`a2_u08_cancellation_parity`) |
| ledger cap one over | A2-U13/U14 (historical `h_a_u11_u12` / `h_a_u13_u14` + route test) |
| missing field stats | A2-U12 (`a2_u12_score_parity_linear`) and historical helper test |
| PIT key mismatch | A2-U11 (`a2_u11_live_filtered_dispatch`) and I07 |

Any newly discovered semantic ambiguity is a HARD STOP under A2-D75.
