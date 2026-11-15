# PR 15I-D3-C — A/A timing-variability analysis (corrected)

Status: **diagnostic only**. The original A/A verdict remains
`MEASUREMENT_BLOCKED`. Evidence:
`target/pr15i-d3-c/official/d3c-base-aa-01`, 16 slots, 72 lanes, 23,040 samples.
No benchmark was rerun.

## Definitions and arithmetic reference

- `slot_median = sorted(samples_ns)[9]` over exactly 20 samples.
- `block_arm_value = (slot1_median + slot2_median) // 2`.
- **Gate ratio** = `sorted([B/A block ratios])[1]` — the frozen lower-middle
  order statistic (`median4`) used by the controller. It is not the arithmetic
  mean and not the upper-middle value.
- **Arm aggregate ratio** = `sorted(B block values)[1] / sorted(A block values)[1]`.
- `absolute gate deviation` and `absolute aggregate deviation` are
  `100 × |ratio − 1|`.
- Percentiles are nearest-rank; all counts use the 72 lane IDs.
- Reproduction: `python3 benchmarks/pr15i_d3_c/analyze_control.py
  --campaign-dir target/pr15i-d3-c/official/d3c-base-aa-01 --json`;
  A01–A06 are in `benchmarks/pr15i_d3_c/test_analysis.py`.

## 1. Aggregate A/A statistics

| Metric | Gate-ratio deviation | Arm-aggregate deviation |
|---|---:|---:|
| Median | 1.797% | 1.246% |
| Mean | 2.889% | 2.022% |
| p90 | 5.357% | 4.766% |
| p95 | 7.613% | 6.924% |
| p99 | 20.096% | 9.912% |
| Maximum | 20.096% | 9.912% |

Absolute arm-aggregate timing differences:

| Statistic | \|B−A\| (ns) |
|---|---:|
| Median | 8,996 |
| p90 | 194,637 |
| p95 | 409,683 |
| p99 | 2,178,714 |
| Maximum | 2,178,714 |
| Mean | 96,272 |

Signed arm-aggregate differences: 35 lanes faster in B, 37 in A; range
−650,685 ns to +2,178,714 ns. Percentile ordering is checked by A05.

## 2. Lanes within tolerance

Gate-ratio definition:

| Scope | ±5% | ±10% | ±15% | ±25% |
|---|---:|---:|---:|---:|
| All 72 | 61 (84.7%) | 69 (95.8%) | 70 (97.2%) | 72 (100%) |
| N=10K (36) | 27 (75.0%) | 33 (91.7%) | 34 (94.4%) | 36 (100%) |
| N=100K (36) | 34 (94.4%) | 36 (100%) | 36 (100%) | 36 (100%) |
| absent (18) | 16 (88.9%) | 17 (94.4%) | 17 (94.4%) | 18 (100%) |
| rare (18) | 11 (61.1%) | 16 (88.9%) | 17 (94.4%) | 18 (100%) |
| medium (18) | 17 (94.4%) | 18 (100%) | 18 (100%) | 18 (100%) |
| common (18) | 17 (94.4%) | 18 (100%) | 18 (100%) | 18 (100%) |
| 10K medium (9) | 8 | 9 | 9 | 9 |
| 10K common (9) | 8 | 9 | 9 | 9 |
| 100K medium (9) | 9 | 9 | 9 | 9 |
| 100K common (9) | 9 | 9 | 9 | 9 |

Arm-aggregate definition:

| Scope | ±5% | ±10% | ±15% | ±25% |
|---|---:|---:|---:|---:|
| All 72 | 65 (90.3%) | 72 (100%) | 72 (100%) | 72 (100%) |
| N=10K (36) | 30 | 36 | 36 | 36 |
| N=100K (36) | 35 | 36 | 36 | 36 |
| absent (18) | 16 | 18 | 18 | 18 |
| rare (18) | 14 | 18 | 18 | 18 |
| medium (18) | 17 | 18 | 18 | 18 |
| common (18) | 18 | 18 | 18 | 18 |

The arm aggregate is never worse than 9.91%; the gate ratio reaches 20.1%
because it selects the second-smallest of four block ratios.

## 3. Per-block behaviour

| Block | Median B/A | p90 | p95 | Max | Gate ±5% | ±10% | ±15% | ±25% |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.0000 | 1.0401 | 1.0577 | 1.2238 | 60 | 68 | 69 | 72 |
| 2 | 0.9288 | 1.0409 | 1.1001 | 1.2138 | 20 | 42 | 57 | 68 |
| 3 | 1.0228 | 1.0878 | 1.1358 | 1.1897 | 44 | 63 | 67 | 72 |
| 4 | 0.9945 | 1.0457 | 1.0873 | 1.2319 | 59 | 65 | 67 | 72 |

Within-block duplicate-slot dispersion (relative difference between the two
same-arm slot medians):

| Block | A median | A p90 | A max | B median | B p90 | B max |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.32% | 9.42% | 26.25% | 2.03% | 9.00% | 45.04% |
| 2 | **12.30%** | **40.49%** | **75.60%** | 4.92% | 17.80% | 52.05% |
| 3 | 3.46% | 11.97% | 43.63% | 7.20% | 18.17% | 35.22% |
| 4 | 3.39% | 18.66% | 38.45% | 2.60% | 9.69% | 45.24% |

Median arm latency normalized to block-1 A:

| Block | A | B |
|---:|---:|---:|
| 1 | 1.000 | 1.000 |
| 2 | **1.119** | 1.045 |
| 3 | 1.011 | 1.043 |
| 4 | 1.017 | 1.013 |

Block 2 is anomalous, especially in the A arm. The evidence is consistent with
temporal host interference, but root cause is **not established** until the CPU
topology, governor, frequency and contention audit is evaluated.

### 17 frozen drift violations (all retained)

| Arm | Block | Lane | Gate | First ns | Second ns | Δ ns | Ratio | Cap |
|---|---:|---|---|---:|---:|---:|---:|---:|
| A | 2 | 10000/absent/k1 | within | 64,300 | 42,100 | 22,200 | 1.527316 | 1.50 |
| A | 2 | 10000/rare/k100 | within | 48,301 | 75,101 | 26,800 | 1.554854 | 1.50 |
| A | 2 | 10000/medium/k256 | within | 2,591,327 | 4,550,450 | 1,959,123 | 1.756031 | 1.50 |
| A | 2 | 10000/medium/k512 | within | 3,632,438 | 5,784,464 | 2,152,026 | 1.592447 | 1.50 |
| A | 2 | 10000/medium/k1024 | within | 5,329,756 | 9,123,701 | 3,793,945 | 1.711842 | 1.50 |
| A | 2 | 100000/absent/k128 | within | 246,303 | 370,204 | 123,901 | 1.503043 | 1.50 |
| A | 2 | 100000/absent/k1024 | within | 241,602 | 378,804 | 137,202 | 1.567884 | 1.50 |
| A | all | 100000/medium/k32 | between | 15,702,981 | 20,164,225 | 4,461,244 | 1.284102 | 1.25 |
| A | 2 | 100000/medium/k64 | within | 26,176,287 | 19,642,824 | 6,533,463 | 1.332613 | 1.25 |
| A | all | 100000/medium/k64 | between | 16,673,201 | 22,909,555 | 6,236,354 | 1.374035 | 1.25 |
| A | all | 100000/medium/k100 | between | 17,590,038 | 22,333,541 | 4,743,503 | 1.269670 | 1.25 |
| A | 2 | 100000/medium/k128 | within | 26,120,383 | 20,415,021 | 5,705,362 | 1.279469 | 1.25 |
| A | all | 100000/medium/k128 | between | 18,429,603 | 23,267,702 | 4,838,099 | 1.262518 | 1.25 |
| B | 2 | 10000/absent/k1 | within | 39,000 | 59,301 | 20,301 | 1.520538 | 1.50 |
| B | 2 | 100000/absent/k512 | within | 240,203 | 363,904 | 123,701 | 1.514985 | 1.50 |
| B | 3 | 100000/medium/k1024 | within | 73,600,710 | 54,430,295 | 19,170,415 | 1.352201 | 1.25 |
| B | 3 | 100000/common/k10 | within | 44,648,990 | 33,602,473 | 11,046,517 | 1.328741 | 1.25 |

## 4. Failing lanes — gate versus aggregate

| Lane | Exempt? | A ns | B ns | B−A ns | Aggregate ratio | Gate ratio | Frozen gate that fails |
|---|---|---:|---:|---:|---:|---:|---|
| 10000/absent/k100 | yes | 45,400 | 40,900 | −4,500 | 0.9009 | **0.7990** | gate median outside 0.85–1.15; two soft-band violations |
| 10000/rare/k1024 | yes | 55,500 | 52,351 | −3,149 | 0.9433 | **0.8390** | gate median outside 0.85–1.15 |
| 10000/medium/k1 | **no** | 993,012 | 993,161 | +149 | 1.0002 | 0.9849 | block-2 ratio 0.7156 outside 0.80–1.25 |
| 10000/medium/k256 | **no** | 2,524,179 | 2,510,384 | −13,795 | 0.9945 | 0.9678 | block-2 ratio 0.7132; A block-2 within drift 1.756 |
| 10000/medium/k512 | **no** | 3,534,939 | 3,505,788 | −29,151 | 0.9918 | 0.9864 | block-2 ratio 0.7446; A block-2 within drift 1.592 |
| 10000/medium/k1024 | **no** | 5,222,156 | 5,212,607 | −9,549 | 0.9982 | 0.9914 | block-2 ratio 0.7499; A block-2 within drift 1.712 |

This corrects the earlier claim that all six failures had aggregate deviation
≤10%: `absent/k100` is 20.1% and `rare/k1024` is 16.1% on the gate ratio (and
9.9%/5.7% on the arm aggregate). The four **medium** lanes are nonexempt and
fail only because of the block-2 per-block band, not their four-block aggregate
(≤0.9% deviation).

Only 10K absent/rare receive the one-soft-block exemption; the four 10K medium
failures do **not**.

## 5. Excluding block 2 (diagnostic only)

| Metric | All four blocks | Excluding block 2 |
|---|---:|---:|
| Gate median | 1.797% | 1.173% |
| p90 | 5.357% | 4.719% |
| p95 | 7.613% | 7.103% |
| p99 | 20.096% | 20.096% |
| Maximum | 20.096% | 20.096% |
| ±5% lanes | 61 | 65 |
| ±10% lanes | 69 | 71 |
| ±15% lanes | 70 | 71 |
| ±25% lanes | 72 | 72 |

Block 2 is not silently removed; this is only a sensitivity check. It improves
the central statistics but leaves the 20.1% outlier.

## 6. Sample, slot and aggregate instability

| Level | Observed dispersion |
|---|---|
| Individual samples | CV median 8.70%, p90 26.05%, p95 31.95%, max 91.68% |
| Slot medians within a block | A block-2 duplicate median 12.30%, p90 40.49%, max 75.60% |
| Four-block gate ratio | median 1.80%, p95 7.61%, max 20.10% |
| Four-block arm aggregate | median 1.25%, p95 6.92%, max 9.91% |

Short sub-millisecond lanes dominate sample-level CV.

## 7. Detectability (qualitative — no formal CI)

| Expected gain | Assessment |
|---:|---|
| **3%** | Marginal. 100K medium/common gate maxima are 3.34%/2.73% and arm-aggregate maxima 1.32%/2.28%, so 3% is plausible there. 10K medium noise reaches ~6.5–6.9%, so 3% is not measurable on short lanes with this sample budget. |
| **10%** | Arm aggregate is entirely within ±10%, so a 10% shift is detectable in aggregate. The per-block 1.25/1.50 caps can still false-block because block-2 within-block drift reaches 28.7%. |
| **20%** | Detectable in aggregate (max 9.91%), but block-2 within drift reaches 28.7% and can confound single-block comparisons. |
| **50%** | Safely detectable; far above all observed A/A dispersion. |

These are qualitative judgments from observed A/A noise; no confidence interval
or guaranteed detection probability follows from this dataset alone.

## 8. Assessment and remediation

- The four-block arm aggregate is stable: median 1.25%, max 9.91%, 100% within
  ±10%.
- The frozen gate ratio is sensitive to one noisy block for short lanes: two
  lanes exceed ±15% and four medium lanes fail via the block-2 band despite
  aggregates within 1%.
- Block-2 temporal interference is a hypothesis consistent with the data, not a
  proven root cause. The host-topology/frequency audit must be completed before
  attributing it to CPU placement.
- The original `MEASUREMENT_BLOCKED` verdict is unchanged.

Recommended remediation, without changing thresholds in this analysis:

1. Audit CPU topology and choose distinct physical cores on the same package.
2. Stabilize frequency/governor conditions only through owner-approved,
   non-global means; record observed state.
3. If a diagnostic confirms block-2 behaviour persists, evaluate a
   statistically justified gate for exempt short lanes using aggregate
   statistics and more samples; retain the 100K 3% target and aggregate ±10%
   guard.
4. Run one bounded nonofficial diagnostic after remediation. A new official
   control requires a successor protocol and explicit authorization.
