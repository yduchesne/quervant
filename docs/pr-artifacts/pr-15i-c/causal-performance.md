# PR 15I-C causal experiment — measurements and classification

All numbers below are recomputed by `benchmarks/pr15i_c/verify_causal.py` from
sealed raw with the frozen PR15D nearest-rank median. `B/A` = specialization
enabled vs baseline; `C/A` = the **same candidate binary** with the
specialization **disabled** vs baseline; `B/C` = enabled vs disabled.

## 1. Unbatched (per-request; the only classification basis)

### Campaign `causal-unbatched-01` (24 slots, 4 320 samples, 1 080 warmups)

| Lane | B/A | C/A | B/C | A/A drift | blocks B/A | blocks C/A | blocks B/C |
|---|---|---|---|---|---|---|---|
| 10K absent | 1.354 | **1.685** | 0.850 | 1.067 | 1.58/1.36/1.34/1.35 | 1.88/1.82/1.55/1.35 | 0.84/0.75/0.86/1.00 |
| 10K rare | 1.254 | **1.310** | 0.957 | 1.092 | 1.36/1.23/1.28/1.18 | 1.60/1.28/1.34/1.19 | 0.85/0.96/0.96/0.99 |
| 10K medium | 0.996 | 1.051 | 0.930 | 1.034 | — | — | — |
| 10K common | 0.898 | 1.030 | 0.872 | 1.031 | — | — | — |
| 100K absent | 1.793 | **1.750** | 0.999 | 1.027 | 1.96/1.77/1.82/1.73 | 2.21/1.74/1.68/1.76 | 0.89/1.02/1.08/0.98 |
| 100K rare | 1.732 | **1.725** | 1.005 | 1.007 | 2.06/1.69/1.75/1.71 | 2.30/1.59/1.68/1.78 | 0.90/1.06/1.05/0.96 |
| 100K medium | 0.964 | 1.042 | 0.888 | 1.015 | — | — | — |
| 100K common/k100 | 0.874 | 1.019 | 0.858 | 1.014 | — | — | — |
| 100K common/k10 | 0.830 | 1.047 | 0.792 | 0.997 | — | — | — |

Per-campaign lane classes: all four low-match lanes `CAUSAL_NON_OPERATOR_DOMINANT`.

### Campaign `causal-unbatched-02` (24 slots, 4 320 samples, 1 080 warmups)

| Lane | B/A | C/A | B/C | A/A drift | blocks B/A | blocks C/A | blocks B/C |
|---|---|---|---|---|---|---|---|
| 10K absent | 1.392 | **1.418** | 0.986 | 1.125 | 1.30/1.55/1.49/**1.02** | 1.60/1.50/1.34/1.09 | 0.81/1.04/1.11/0.93 |
| 10K rare | 1.301 | **1.181** | 1.026 | 1.022 | **1.05**/1.24/1.36/1.38 | 1.21/1.67/1.15/1.05 | 0.87/0.74/1.19/1.31 |
| 10K medium | 0.994 | 1.203 | 0.836 | 1.005 | — | — | — |
| 10K common | 0.901 | 1.019 | 0.900 | 0.945 | — | — | — |
| 100K absent | 1.946 | **1.819** | 1.008 | 0.990 | 1.57/2.06/2.02/1.87 | 1.72/1.91/1.73/2.00 | 0.91/1.08/1.17/0.93 |
| 100K rare | 1.753 | **1.758** | 1.016 | 0.972 | 1.86/1.86/1.65/1.53 | 1.82/1.84/1.70/1.26 | 1.02/1.01/0.97/1.22 |
| 100K medium | 0.900 | 0.977 | 0.919 | 1.008 | — | — | — |
| 100K common/k100 | 0.835 | 1.012 | 0.827 | 1.023 | — | — | — |
| 100K common/k10 | 0.780 | 1.015 | 0.771 | 1.064 | — | — | — |

Per-campaign lane classes: 10K absent/rare `CAUSAL_HISTORICAL_PATTERN_NOT_REPRODUCED`
(one B/A block 1.018 / 1.051 below the predeclared 1.10 floor); 100K absent/rare
`CAUSAL_INCONCLUSIVE` (one B/C block 1.167 / 1.219 above the 1.15 ceiling).

## 2. Batched (observational only, never classification)

| Campaign | 10K absent B/A · C/A · B/C | 10K rare | 100K absent | 100K rare | 100K common/k100 B/A |
|---|---|---|---|---|---|
| causal-batched-01 | 1.497 · 1.565 · 0.949 | 1.365 · 1.436 · 0.972 | 1.846 · 1.794 · 1.026 | 1.837 · 1.744 · 1.072 | 0.879 |
| causal-batched-02 | 1.461 · 1.602 · 0.940 | 1.400 · 1.495 · 0.962 | 1.752 · 1.774 · 1.009 | 1.751 · 1.783 · 0.963 | 0.891 |

The batched regime reproduces the same qualitative shape as the per-request
regime, which is itself an observation: the low-match asymmetry is not an
artefact of single-request timing. It still cannot override the unbatched
classification.

## 3. Classification (frozen §9 table, applied mechanically)

* Row 0/1/2 pass campaign-by-campaign: evidence valid, A/A drift medians
  `0.990–1.125` (inside `[0.85, 1.15]` on every lane of every campaign), and the
  B/A reproduction gate holds on all four medians in both campaigns.
* Row 3 (`operator dominant`) fails everywhere: `C/A` is never ≤1.05 on a
  low-match lane.
* Row 4 (`non-operator dominant`) holds for **all four lanes in campaign 1**, but
  not in campaign 2 (block-level floors/ceilings missed on two lanes).
* Rows 5/6 therefore apply: `CAUSAL_INCONCLUSIVE`.

**Series status: `15IC_CAUSAL_DIAGNOSTIC_INCONCLUSIVE`.**

## 4. What is nevertheless established (stated as measured facts)

1. In **all 8 low-match lane × campaign cells**, C/A ≈ B/A: `B/C` medians range
   `0.850 … 1.026` (median ≈ 0.99). Disabling the specialized execution path does
   **not** remove the absent/rare regression.
2. On the common/medium lanes `C/A ≈ 1.0` (0.96–1.05) while `B/A` is 0.78–0.90:
   the specialization *is* what makes those lanes faster.
3. Therefore the low-match regression is **not** attributable to the specialized
   operator's execution; it is present in the candidate build when the generic
   algorithm runs. That is consistent with gate/dispatch/link-layout effects, but
   this experiment does **not** prove an LLVM mechanism and the frozen classifier
   does not award the decisive row because two lanes missed block-level
   thresholds in one campaign.
4. `perf` counters were unavailable, so no branch/cache/cycle claim is made.

## 5. Limitations

* One campaign per regime is not enough to make the block-level thresholds
  robust on ~50–250 µs lanes; the decisive row requires both campaigns and every
  block, which is deliberately strict.
* The 100-search batch metric is a hot-throughput observation and cannot speak to
  single-request tail latency.
* `C/A` mixes the experimental gate, an extra data-dependent branch and changed
  link layout; it is not a pure compiler attribution.
