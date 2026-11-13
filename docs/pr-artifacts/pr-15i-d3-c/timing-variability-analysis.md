# PR 15I-D3-C — A/A timing-variability analysis

Status: **diagnostic only**; the original A/A verdict remains `MEASUREMENT_BLOCKED`.
Evidence: `target/pr15i-d3-c/official/d3c-base-aa-01` (16 slots, 72 lanes,
23,040 samples). No benchmark was rerun.

Definitions used below:

- **Slot median**: the adapter's 20-sample median for one slot/lane.
- **Block arm value**: average of the two slot medians for that arm in a block,
  matching the controller.
- **Aggregate ratio**: `median(B block values) / median(A block values)`.
- **Gate ratio**: `median(B/A block ratios)` — the value the current verifier
  uses for lane pass/fail.
- Percentile convention: nearest rank on the 72 lane values.

## 1. Aggregate A/A stability

| Metric | Gate-ratio deviation | Aggregate-ratio deviation |
|---|---:|---:|
| Median | 1.45% | 2.54% |
| p90 | 5.08% | 6.81% |
| p95 | 7.58% | 9.70% |
| p99 | 10.01% | 20.10% |
| Maximum | 10.01% | 20.10% |
| Mean | 2.01% | 3.46% |

Absolute aggregate timing deviation across all 72 lanes:

| Statistic | \|B−A\| (ns) |
|---|---:|
| Median | 17,600 |
| p90 | 734,235 |
| p95 | 1,488,718 |
| p99 | 3,524,825 |
| Maximum | 3,524,825 |
| Mean | 220,348 |

Signed deviations: 36 lanes faster in B, 36 faster in A; range
−199,247 ns to +3,524,825 ns. There is no systematic whole-grid offset.

### Lanes within tolerance (gate-ratio deviation)

| Scope | ±5% | ±10% | ±15% | ±25% |
|---|---:|---:|---:|---:|
| All 72 lanes | 63 (87.5%) | 71 (98.6%) | 72 (100%) | 72 (100%) |
| N=10K (36) | 30 (83.3%) | 35 (97.2%) | 36 (100%) | 36 (100%) |
| N=100K (36) | 33 (91.7%) | 36 (100%) | 36 (100%) | 36 (100%) |
| absent (18) | 14 (77.8%) | 18 (100%) | 18 (100%) | 18 (100%) |
| rare (18) | 14 (77.8%) | 17 (94.4%) | 18 (100%) | 18 (100%) |
| medium (18) | 17 (94.4%) | 18 (100%) | 18 (100%) | 18 (100%) |
| common (18) | 18 (100%) | 18 (100%) | 18 (100%) | 18 (100%) |
| 10K medium (9) | 8 (88.9%) | 9 (100%) | 9 (100%) | 9 (100%) |
| 10K common (9) | 9 (100%) | 9 (100%) | 9 (100%) | 9 (100%) |
| 100K medium (9) | 9 (100%) | 9 (100%) | 9 (100%) | 9 (100%) |
| 100K common (9) | 9 (100%) | 9 (100%) | 9 (100%) | 9 (100%) |

The target decision lanes — 100K medium/common — are the most stable group
(maximum gate deviation 1.87% and 1.46% respectively).

## 2. Per-block behaviour and temporal drift

| Block | Median B/A | p90 | p95 | Max | ±5% lanes | ±10% | ±15% | ±25% |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.0000 | 1.0401 | 1.0577 | 1.2238 | 60 | 68 | 69 | 72 |
| 2 | 0.9288 | 1.0409 | 1.1001 | 1.2138 | 20 | 42 | 57 | 68 |
| 3 | 1.0228 | 1.0878 | 1.1358 | 1.1897 | 44 | 63 | 67 | 72 |
| 4 | 0.9945 | 1.0457 | 1.0873 | 1.2319 | 59 | 65 | 67 | 72 |

Block 2 is a clear outlier: median B/A 0.929 versus approximately 1.00 in the
other blocks, only 20/72 lanes within ±5%, and 4/72 outside ±25%.

Within-block duplicate-slot dispersion (difference between the two A or two B
slot medians for the same lane), relative to the smaller value:

| Block | A median | A p90 | A max | B median | B p90 | B max |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.32% | 9.42% | 26.25% | 2.03% | 9.00% | 45.04% |
| 2 | **12.30%** | **40.49%** | **75.60%** | 4.92% | 17.80% | 52.05% |
| 3 | 3.46% | 11.97% | 43.63% | 7.20% | 18.17% | 35.22% |
| 4 | 3.39% | 18.66% | 38.45% | 2.60% | 9.69% | 45.24% |

Block 2's A-arm duplicate slots disagree by a median 12.3% and a maximum 75.6%.
Median arm latency normalized to the lane's block-1 A value:

| Block | A | B |
|---:|---:|---:|
| 1 | 1.000 | 1.000 |
| 2 | **1.119** | 1.045 |
| 3 | 1.011 | 1.043 |
| 4 | 1.017 | 1.013 |

Block 2's A arm was elevated while B was not, producing the apparent B/A < 1
offset. This is temporal interference or CPU-frequency/topology behaviour, not
a stable A/B difference.

## 3. Sample-level instability versus final aggregates

Per-slot within-lane coefficient of variation across the 20 samples:

| Statistic | Sample CV |
|---|---:|
| Median | 8.70% |
| p90 | 26.05% |
| p95 | 31.95% |
| p99 | 44.24% |
| Maximum | 91.68% |

Short/empty-result lanes (sub-millisecond, 10K absent/rare) dominate the high
CVs. The instability hierarchy is:

1. **Individual samples**: median CV 8.7%, p95 32%, worst 92%.
2. **Slot medians**: block-2 A duplicate slots differ by 12.3% median, 40.5% p90.
3. **Aggregate ratios**: median 1.45%, p95 7.58%, maximum 10.01% (gate ratio).

Averaging 20 samples plus four blocks removes most sample noise; the residual
block-2 temporal offset and the short-lane sample variance are what the
per-block equality caps currently detect.

## 4. Sensitivity excluding block 2 (diagnostic only)

| Metric | Full four blocks | Excluding block 2 |
|---|---:|---:|
| Median deviation | 1.45% | 1.17% |
| p90 | 5.08% | 4.72% |
| p95 | 7.58% | 7.10% |
| p99 | 10.01% | 20.10% |
| Maximum | 10.01% | 20.10% |
| ±5% lanes | 63 | 65 |
| ±10% lanes | 71 | 71 |
| ±15% lanes | 72 | 71 |
| ±25% lanes | 72 | 72 |

Removing block 2 improves the central statistics but does not fix the single
20% outlier (`10000/absent/k100`, three-block median ratio 0.799). It would be a
diagnostic comparison only; the frozen A/A verdict is unchanged.

## 5. Failing lanes and absolute differences

Six lanes fail the current gate despite final deviations ≤10%:

| Lane | A aggregate ns | B aggregate ns | B−A ns | Aggregate ratio | Gate ratio | Block ratios (1–4) |
|---|---:|---:|---:|---:|---:|---|
| 10000/absent/k100 | 52,250 | 41,750 | −10,500 | 0.799 | 0.901 | 1.224, 0.901, 0.757, 0.799 |
| 10000/rare/k1024 | 63,350 | 53,150 | −10,200 | 0.839 | 0.986 | 0.839, 0.782, 1.008, 0.986 |
| 10000/medium/k1 | 1,005,761 | 1,000,013 | −5,748 | 0.994 | 1.007 | 0.985, 0.716, 1.070, 1.007 |
| 10000/medium/k256 | 2,584,278 | 2,546,827 | −37,451 | 0.986 | 0.995 | 0.968, 0.713, 1.023, 0.995 |
| 10000/medium/k512 | 3,535,141 | 3,505,797 | −29,344 | 0.992 | 0.992 | 0.986, 0.745, 1.068, 0.992 |
| 10000/medium/k1024 | 5,257,911 | 5,419,409 | +161,498 | 1.031 | 0.996 | 0.996, 0.750, 1.059, 0.991 |

All six are 10K lanes. Five fail because block 2's ratio is far outside the
exempt-lane soft band, not because their four-block aggregate moved materially.
The medium/k1024 lane even has opposite signs for its aggregate ratio (+3.1%)
and gate ratio (−0.4%), a direct symptom of block-2 weighting.

The largest aggregate deviations are 100K common lanes but they remain inside
the 1.25 cap: 100K common/k1024 +3.52 ms (+1.83%), 100K common/k512 +1.49 ms
(+1.46%), 100K common/k1 +1.63 ms (+1.99%).

## 6. Impact on detecting real improvements

Observed noise relevant to the frozen decision lanes:

- 100K medium: p95 ≈ 1.87%, maximum 1.87%.
- 100K common: p95 ≈ 2.00%, maximum 1.46%.

| Expected gain | Assessment against this A/A run |
|---:|---|
| **3%** | Marginal for aggregate 100K medium/common (noise max ~1.9%), but not robust for short 10K lanes (p95 ~7.6%, max 10.0%). The 3% policy threshold is defensible only on the stable target lanes with multiple blocks; per-block equality caps can still false-block. |
| **10%** | Detectable in aggregate: 71/72 lanes within ±10%. However block-2 per-block drift exceeds 10%, so a 10% result could be rejected by the within-block gate even when the four-block aggregate is correct. |
| **20%** | Detectable overall (100% within ±15% aggregate), but block-2 within-block dispersion reaches 28.7% and could confound a single-block comparison. Requires aggregate/median-of-block evaluation, not one block. |
| **50%** | Safely detectable; far above all observed A/A dispersion (worst block ratio 28.7%, worst aggregate 20.1%). |

The 3% threshold is not uniformly measurable on 10K absent/rare lanes with this
sample budget. It is more credible for 100K medium/common, which are stable to
about 2%.

## 7. Assessment

- The final four-block aggregate is not materially biased: median A/A deviation
  1.45%, 100% of lanes within ±15%.
- The current gate is **overly sensitive to per-block point estimates for short,
  exempt lanes**. Five of six failures are driven by one noisy block, not by a
  persistent A/B difference.
- There is **systematic temporal interference in block 2**, strongest in the A
  arm: A median latency +11.9% versus block 1, duplicate A slots differ by 12.3%
  median, and block-2 B/A median is 0.929.
- Individual samples are noisy (CV 8.7% median, 32% p95), especially on
  sub-millisecond lanes; slot medians and four-block aggregates are progressively
  more stable.
- The original `MEASUREMENT_BLOCKED` verdict is unchanged.

## 8. Remediation recommendation

1. **Host/measurement stabilization first**: pin adapter and controller to
   distinct physical cores (avoid SMT siblings), disable frequency scaling/turbo
   for the run, keep the host otherwise idle, and increase settle/warmup before
   block 1. Re-run the host topology investigation before measuring.
2. **Do not relax the 1.25/1.50 caps globally.** For exempt 10K absent/rare
   lanes, evaluate whether the per-block pair-consistency requirement should be
   replaced by a statistically justified rule based on the aggregate median and
   a confidence interval derived from more samples. Any change must preserve the
   aggregate ±10% guard and the 100K medium/common 3% criterion.
3. **Increase samples on short lanes** if the protocol is revised: with sample
   CV up to 30–90%, 20 samples leave large standard errors; at least 3–5× more
   samples (or a trimmed estimator) would be needed to support 3% detection.
4. **Run one narrowly scoped nonofficial diagnostic control** after host
   remediation to estimate the new A/A distribution. Do not change the official
   verdict or retry the official control without explicit protocol authorization;
   the frozen retry count remains 0.

No threshold or acceptance criterion was changed by this analysis.
