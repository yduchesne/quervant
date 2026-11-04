# PR 15G-D targeted confirmation qualification

**Status:** `NOT_RECONFIRMED`
**A / D_BASE:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**B / D1:** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**C / D1+D2:** `dae598758a433ecdc0d9af37e15194e948bbc788`
**Campaign:** `target/pr15g-d-confirm/campaign-20261105T0000Z` (opaque ID only in report)
**Harness commit:** current shared branch commit containing `benchmarks/pr15g_d/confirm.py`.

## Qualification

| Item | Result |
|---|---|
| Exact A/B/C ancestry | PASS |
| Frozen input hashes | PASS |
| Native filesystem / same host fingerprint | PASS |
| 18-slot fixed mirrored schedule | PASS |
| 162 lane records, 5 warmups + 20 samples | PASS |
| Independent oracle per slot/lane | PASS |
| All 36 contention probes `clear` | PASS |
| Index/binary/source immutability | PASS |
| Drift checks (1.25 100K / 1.50 10K) | PASS |
| Sanitizer / verify-only byte identity | PASS |
| CF-P07 measurement qualification | PASS |
| CF-P08 report structure | PASS |

## Performance gates

| Gate | Status |
|---|---|
| CF-P01 D1 100K absent/K100 `B_FASTER` | **FAIL** — `INCONCLUSIVE` |
| CF-P02 D1 other eight no `A_FASTER` | **FAIL** — 10K absent and 10K common `A_FASTER` |
| CF-P03 D2 incremental target `B_FASTER` | PASS — both 100K medium and common K100 |
| CF-P04 D2 no lane `A_FASTER` | **FAIL** — 10K rare `A_FASTER` |
| CF-P05 cumulative target `B_FASTER` | PASS — both 100K medium and common K100 |
| CF-P06 cumulative no lane `A_FASTER` | **FAIL** — 10K absent `A_FASTER` |

Overall classification: **`NOT_RECONFIRMED`**. This is a valid, qualified
measurement outcome, not a harness failure. No production rollback, tuning or
sample exclusion was performed. The original D1/D2 reports remain intact.

## Interpretation

D2’s high-hit incremental and cumulative gains reproduce in all three blocks on
100K medium/K100 and common/K100, plus 100K common/K10. However D1’s 100K absent
gain does **not** reproduce (`INCONCLUSIVE`), and both D1 and D2 show 10K
guardrail regressions. The confirmation therefore does not support the previous
full D1+D2 performance-qualified claim.

## Residual notes

- One host and one frozen warm workload matrix; strict three-block signs are not
  a broad statistical guarantee.
- No CPU/allocation attribution was measured.
- Independent review remains pending; this report does not self-approve or merge.
