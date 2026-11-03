# PR 15E Phase 3 — targeted performance qualification

**Status: `PHASE3_PERF_MEASURED` — independent phase review pending.**

The operator explicitly confirmed the benchmark host was idle and authorized the Phase 3
measurements against commits `5553c3b` (arm A, accepted B1) and `df9b856` (arm B, Phase 3
head). Both invocations completed under the approved methodology: fresh operator
attestation, three independent trials per source, 5 warmups + 20 measured samples per
lane, oracle-checked samples, and `clear` contention before **and** after every trial.
Verdicts are sign-consistency only; no speedup threshold is asserted.

Sanitized machine-readable summary:
`benchmarks/reports/pr15e-b1/phase3-targeted-comparison.json`. Raw samples, build logs,
index digests, host details and the operator attestation stay private under
`target/pr15e-b1/p3/` (gitignored).

## 1. Identity and parity

| Item | Value |
|---|---|
| Arm A — accepted B1 | `5553c3bba268b9b268b51117e54eb256772ec19c` |
| Arm B — Phase 3 head | `df9b8565a4e47c5c66a7edeb566333643672e3fa` (strict descendant of arm A) |
| Tooling revision | `df9b8565a4e47c5c66a7edeb566333643672e3fa` |
| Release adapter SHA-256 | A `49b9ac105944516b5d56fefca96c40b78e299f39bfff5c01d84ca37cdc92e152` · B `f9fc44a14324401744f2a0475b4c34b3ba6770433bcd0e9e7b2764b2ea3cc2f0` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` (identical both arms) |
| Index bytes (10K / 100K) | byte-identical both arms (`4fbca86e5e3beffc…` / `d65fae4069f1c17a…`) |
| Host fingerprint | identical both arms (`4f971362f029…`) |
| Trials / samples | 3 / 20 per lane, 7 lanes, both arms |
| Contention probes | 42/42 `clear` (before and after every trial) |
| Oracle | untimed per lane + `validate_query_response` on every sample: PASS |

## 2. Fixed design (pre-registered)

Seven warm lanes: `n100000/rare/k100` (**primary**, one selected stored record),
`n100000/rare/k10` (top-K control), `n10000/rare/k100` (10K scaling), `n100000/medium/k100`
(12,500 hits), `n100000/common/k100` (high-match), `n100000/absent/k100` (no-projection
regression sentinel), `n10000/common/k100` (smaller high-match).

Ratio = Phase 3 median / B1 median. `B_FASTER` iff all three paired trial ratios `< 1`,
`A_FASTER` iff all `> 1`, otherwise `INCONCLUSIVE`. Arms are pinned: arm A must be exactly
`5553c3b`, arm B a descendant; reversed/unrelated arms are refused by the runner.

## 3. Results

| Lane | Arm A median | Arm B median | ratio | paired trial ratios | verdict |
|---|---:|---:|---:|---|---|
| `n100000/rare/k100` (**primary**) | 78 652 322 ns | 32 165 176 ns | **0.409** | 0.405, 0.411, 0.407 | **B_FASTER** |
| `n100000/rare/k10` | 80 394 221 ns | 32 329 869 ns | 0.402 | 0.415, 0.397, 0.408 | B_FASTER |
| `n10000/rare/k100` | 7 277 045 ns | 3 152 323 ns | 0.433 | 0.428, 0.433, 0.443 | B_FASTER |
| `n100000/medium/k100` | 92 180 037 ns | 45 128 505 ns | 0.490 | 0.483, 0.496, 0.487 | B_FASTER |
| `n100000/common/k100` | 122 316 890 ns | 74 682 876 ns | 0.611 | 0.611, 0.611, 0.608 | B_FASTER |
| `n100000/absent/k100` | 1 672 045 ns | 1 703 245 ns | 1.019 | 1.065, 1.019, 0.974 | INCONCLUSIVE |
| `n10000/common/k100` | 11 366 795 ns | 7 179 589 ns | 0.632 | 0.612, 0.625, 0.634 | B_FASTER |

Per-trial medians (dispersion evidence):

| Lane | A trial medians (ns) | B trial medians (ns) |
|---|---|---|
| `n100000/rare/k100` | 79 341 267 · 78 652 322 · 78 232 416 | 32 165 176 · 32 312 231 · 31 849 133 |
| `n100000/rare/k10` | 77 903 524 · 80 931 665 · 80 394 221 | 32 329 869 · 32 160 627 · 32 763 605 |
| `n10000/rare/k100` | 7 304 606 · 7 277 045 · 7 110 003 | 3 125 823 · 3 152 475 · 3 152 323 |
| `n100000/medium/k100` | 94 032 716 · 91 009 896 · 92 180 037 | 45 439 852 · 45 128 505 · 44 932 543 |
| `n100000/common/k100` | 123 744 045 · 122 316 890 · 121 339 788 | 75 658 898 · 74 682 876 · 73 767 560 |
| `n100000/absent/k100` | 1 665 432 · 1 672 045 · 1 716 211 | 1 774 439 · 1 703 245 · 1 671 529 |
| `n10000/common/k100` | 11 726 892 · 11 121 037 · 11 366 795 | 7 179 589 · 6 949 039 · 7 206 676 |

Percentiles (median of the three per-trial percentiles):

| Lane | A p95 | A p99 | B p95 | B p99 |
|---|---:|---:|---:|---:|
| `n100000/rare/k100` | 81 731 542 | 82 066 629 | 33 610 402 | 34 087 662 |
| `n100000/rare/k10` | 82 064 720 | 82 751 544 | 33 208 485 | 34 472 656 |
| `n10000/rare/k100` | 7 745 003 | 8 046 811 | 3 348 989 | 3 698 851 |
| `n100000/medium/k100` | 95 578 819 | 96 792 037 | 47 011 287 | 47 972 298 |
| `n100000/common/k100` | 124 961 817 | 125 761 936 | 75 740 452 | 77 132 089 |
| `n100000/absent/k100` | 1 937 214 | 2 038 628 | 1 928 016 | 2 027 989 |
| `n10000/common/k100` | 12 107 375 | 12 138 990 | 7 565 010 | 7 729 125 |

**7 lanes: 6 `B_FASTER`, 1 `INCONCLUSIVE`, 0 `A_FASTER`.** The primary lane is a
sign-consistent improvement (every paired trial ratio ≤ 0.411), so this phase is **not**
`PHASE3_PERF_REVIEW_REQUIRED`.

## 4. Reading the result

* The primary single-record lane improves from ~78.7 ms to ~32.2 ms in this workload.
  The remaining cost is the per-live-document traversal and full matched-set scoring
  (B2 territory), not stored projection.
* The top-K control moves with the primary lane (0.402), so the effect is not a K artifact.
* High-match lanes improve less (medium 0.490, common 0.611) because more records must be
  projected; the selective path is bounded by selected hits, not segment size.
* The `absent` lane performs **no stored projection at all**; its paired ratios straddle
  1.0 (1.065, 1.019, 0.974) and it is `INCONCLUSIVE`, i.e. no systematic regression in the
  untouched path.
* Byte-identical index bytes on both arms confirm the writer/format are untouched; only the
  read path changed.

## 5. Operator attestation

The operator confirmed host idleness and authorized these two commits. The runner recorded
`operator_idle_confirmed: true` in each run's `idle-confirmation.json` (private, not
committed) and re-probed contention before and after every trial (42/42 `clear`). The
agent did not generate or infer the attestation.

## 6. Untimed preflight (executed before the timed run)

| Item | Arm A (B1 accepted) | Arm B (Phase 3) |
|---|---|---|
| Worktree | `/home/yduchesne/pr15e-p3-work/b1-accepted` | `/home/yduchesne/pr15e-p3-work/phase3` |
| Clean tracked tree / frozen hashes | yes / ok | yes / ok |
| Codec analyzer / backend | `keyword-exact` / `FsDirectory` | `keyword-exact` / `FsDirectory` |
| Untimed oracle, all 7 lanes | PASS (1, 1, 1, 12500, 49999, 0, 4999 hits) | PASS (same) |

## 7. Limits (must travel with these numbers)

* Synthetic exact-term `FsDirectory` workload; says nothing about BM25-scored ranking,
  remote-latency projection, or distributed search.
* In-process adapter samples include JSON transport but exclude build and index creation.
* Wall-clock `engine_ns` only; no CPU counters or allocation measurement was performed.
* Modeled decode budgets are deliberately unchanged (full-decode parity), so the effect is
  allocation/CPU work, not decode admissibility.
* Single host, single session, trial-paired; not a cross-host or production-p99 claim.
* Historical reference only: original `main`/PR 15D and the B1 campaign figures come from
  different sessions and were not re-measured here; they are not part of this comparison.

## 8. Reproduction

```sh
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p3-work/b1-accepted \
  --stage p3 --out "$PWD/target/pr15e-b1/p3" --idle-confirmed
python3 benchmarks/pr15e_b1/run_targeted.py \
  --source-tree /home/yduchesne/pr15e-p3-work/phase3 \
  --stage p3 --out "$PWD/target/pr15e-b1/p3" --idle-confirmed
```

The runner refuses a missing attestation, a non-`clear` probe, mismatched corpus or host,
fewer than three trials, and any arm set that is not exactly {`5553c3b`, descendant}.

## 9. Status history

Before the operator's Phase 3 attestation this phase was `PERF_BLOCKED_OPERATOR`; the
pre-registered design and the untimed preflight were recorded at that time and are
reproduced in §2 and §6 above.
