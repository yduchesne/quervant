# PR 15I-C dispatch-isolation — measurements and classification

Four campaigns, all independently verified (receipts under
`target/pr15i-c/reviews/dispatch-*`). Unbatched campaigns are the only
classification basis; batched campaigns are observational corroboration.

## Protocol executed

* 4 blocks × 8 slots = 32 slots per campaign, schedule
  `ACDEEDCA / EDCAACDE / DCAEACED / CEADDAEC` (two of each arm per block).
* 5 warmups + 20 single-request `engine_ns` samples (unbatched) or 10 `batch_ns`
  observations (batched; 100 repeats on the four absent/rare lanes, 1 on the five
  medium/common lanes).
* Per unbatched campaign: 5 760 timed samples, 1 440 warmups, 24 fresh index
  rebuilds, 64 clear contention probes. Per batched campaign: 2 880 whole batches
  (129 600 query invocations), 1 440 warmups.
* All four campaigns: one host fingerprint, one `rustc 1.98.1`, `ext4`, affinity
  `PINNED_ADAPTER_CPU0_CONTROLLER_CPU1`, four distinct arm binaries, byte/digest
  identical index layouts and the 100K PR15I-B LZ4 STORED v2 sentinel
  (15 747 551 committed / 1 661 455 STORED bytes) in every rebuild.

## Unbatched low-match lanes (the classification input)

### `unbatched-01`

| Lane | C/A | D/A | E/A | A/A drift | D/A blocks |
|---|---|---|---|---|---|
| 10K absent | **1.4287** | 0.9893 | 0.9627 | 0.8837 | 1.245 / 0.949 / 1.030 / 0.925 |
| 10K rare | **1.3136** | **1.0807** | 0.9307 | 1.0332 | 1.077 / 1.151 / 1.085 / 0.845 |
| 100K absent | **1.7399** | 0.9897 | 1.0408 | 0.9645 | 1.003 / 1.023 / 0.967 / 0.976 |
| 100K rare | **1.6642** | 0.9659 | 0.9779 | 1.0133 | 0.964 / 0.968 / 0.923 / 0.998 |

### `unbatched-02`

| Lane | C/A | D/A | E/A | A/A drift | D/A blocks |
|---|---|---|---|---|---|
| 10K absent | **1.4078** | **1.0863** | 1.0065 | 1.0275 | 0.914 / 1.169 / 1.299 / 1.004 |
| 10K rare | **1.2976** | 1.0016 | 0.9842 | 0.9983 | 0.974 / 0.954 / 1.037 / 1.029 |
| 100K absent | **1.7879** | 1.0264 | 0.9759 | 1.0639 | 0.948 / 1.054 / 1.028 / 1.025 |
| 100K rare | **1.8024** | 1.0165 | 0.9890 | 0.9796 | 0.984 / 1.023 / 1.060 / 1.010 |

Common/medium control lanes (both campaigns): `C/A` 0.96–1.01, `D/A` 0.92–0.98,
`E/A` 0.95–1.02 — i.e. all three candidate-style paths are at or slightly below
baseline when the physical operator is not executing, exactly as expected.

## Batched corroboration (observational only)

| Campaign | 10K absent C/D/E | 10K rare | 100K absent | 100K rare |
|---|---|---|---|---|
| batched-01 | 1.485 / 1.051 / 0.991 | 1.431 / 0.986 / 1.004 | 1.805 / 1.003 / 0.994 | 1.790 / 1.009 / 1.005 |
| batched-02 | 1.355 / 1.059 / 0.970 | 1.381 / 1.026 / 1.043 | 1.770 / 1.040 / 0.971 | 1.742 / 1.004 / 0.954 |

Same shape as per-request: C regressed, D and E neutral. Batched data cannot
change the verdict and is not used to claim tail-latency equivalence.

## Classification (frozen §8 table, applied mechanically by the verifier)

1. Evidence validity, source/binary/index/oracle/score and codegen structural
   controls: PASS in all four campaigns (`e_trampoline_present`, `c_physical_present`,
   `d_physical_present = false`, `e_physical_absent`).
2. A/A within-campaign stability: PASS on every lane of every campaign
   (drift medians 0.884–1.064, at most zero blocks outside `[0.8, 1.25]`).
3. C/A reproduction: **PASS** — C/A is `REGRESSED` (≥1.15 for 10K, ≥1.40 for 100K)
   on all four lanes in both unbatched campaigns (1.30–1.80).
4. D/E classes: `C = {REGRESSED}`, `E = {NEUTRAL}` (all eight E cells within
   `[0.85, 1.08]`), `D = {NEUTRAL, INTERMEDIATE}` — D is neutral in six of eight
   cells and just above the 1.08 ceiling twice: `unbatched-01` 10K rare **1.0807**
   and `unbatched-02` 10K absent **1.0863**.
5. Because D is not uniformly `NEUTRAL`, the exact-row lookup is not applicable and
   the table's third branch applies: **MIXED**.

**Disposition: `15IC_DISPATCH_DIAG_MIXED_SAFE_ROLLBACK_VERIFIED`.**

## Supported and unsupported statements

Supported (measured):
* The historical low-match regression reproduces with the unchanged causal
  candidate at 1.30–1.80× on all four low-match lanes in both unbatched campaigns.
* Compile-time-disabling the physical dispatch in that same source (D) removes
  essentially all of the regression (0.97–1.09×, with two cells marginally above
  the neutral ceiling); the physical operator symbol is verifiably absent in D.
* A minimal eligibility/gate/trampoline scaffold built on the merged baseline (E)
  does **not** reproduce the regression (0.93–1.04× on every low-match lane).
* Common/medium lanes are unaffected by disabling the operator in either
  candidate-style arm.

Not supported (explicitly not claimed):
* That the runtime gate branch alone causes the regression (E, which has a runtime
  gate and an out-of-line trampoline, is neutral).
* That any specific compiler transformation, cache effect or branch behaviour is
  the mechanism (no counters; `perf` unavailable).
* That PR 15I-C is qualified in any sense; the frozen nine-lane acceptance gates
  were not run and remain failed for every candidate measured so far.
