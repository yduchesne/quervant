# PR 15I-D0 lockfix-01 — paired A/Q/P measurement

**Status: `D0_ATTRIBUTION_LOW_INTRUSION` (both campaigns, independently verified).**
**Ranking: qualified, non-causal, instrumented diagnostic only.**

Measured source is `COMPAT_BASE` (`a53ee021acbe5f30db2b3298a11fcd99e72c2945`).
`A` is the original adapter (`op=query`); `Q` is the diagnostic binary with the
recorder inactive (`op=query`); `P` is the **same** diagnostic binary with the
recorder active (`op=query_probe`). Q and P are one file with SHA-256
`aab694cd…`; A is `db27f3bf…`.

## 1. Evidence inventory

| Item | `unbatched-01` | `unbatched-02` |
|---|---:|---:|
| Slots | 24 | 24 |
| Timed `engine_ns` | 4,320 | 4,320 |
| Warmups | 1,080 | 1,080 |
| Contention probes | 48 | 48 |
| Index builds | 4 | 4 |
| P stage/counter samples | 1,440 | 1,440 |
| Sealed members | 83 | 83 |
| Independent verifier | VERIFIED | VERIFIED |
| Aggregate status | `D0_ATTRIBUTION_LOW_INTRUSION` | `D0_ATTRIBUTION_LOW_INTRUSION` |

All contention probes were `clear`. All slots follow the frozen
`AQPPQA / PQAAQP / QAPPAQ / PAQQAP` schedule. The independent verifier
recomputed the oracle, counts, all ratios, stability, intrusion, per-sample stage
partitions and counter parity from the sealed raw files.

## 2. Nine-lane ratio matrix

Medians of four block ratios; gates are per campaign.

### `unbatched-01`

| Lane | A/A drift | Q/A | P/Q | P/A |
|---|---:|---:|---:|---:|
| 10K absent K100 | 0.927024 | 1.010040 | 1.054024 | 0.997814 |
| 10K rare K100 | 1.034382 | 1.077395 | 0.985155 | 1.039372 |
| 10K medium K100 | 1.051862 | 1.009422 | 1.000491 | 1.014329 |
| 10K common K100 | 1.031975 | 0.987920 | 1.012596 | 1.001465 |
| 100K absent K100 | 1.019661 | 1.027033 | 1.025939 | 1.042715 |
| 100K rare K100 | 1.059103 | 0.979429 | 0.991597 | 0.967575 |
| 100K medium K100 | 1.004091 | 1.008328 | 0.993925 | 0.992726 |
| 100K common K100 | 1.001746 | 0.999863 | 1.003898 | 0.999345 |
| 100K common K10 | 0.988688 | 1.003489 | 0.998090 | 1.005144 |

### `unbatched-02`

| Lane | A/A drift | Q/A | P/Q | P/A |
|---|---:|---:|---:|---:|
| 10K absent K100 | 0.983157 | 1.057094 | 1.031501 | 1.078876 |
| 10K rare K100 | 1.083056 | 0.990659 | 1.007994 | 1.064146 |
| 10K medium K100 | 0.958605 | 0.963759 | 1.027451 | 0.959740 |
| 10K common K100 | 1.081460 | 0.981305 | 0.968156 | 0.956876 |
| 100K absent K100 | 1.033437 | 0.999934 | 1.003593 | 0.992016 |
| 100K rare K100 | 0.989638 | 0.982202 | 1.002926 | 0.995883 |
| 100K medium K100 | 0.987340 | 1.014886 | 0.969687 | 0.979562 |
| 100K common K100 | 0.998818 | 0.997130 | 1.000868 | 0.996937 |
| 100K common K10 | 1.003882 | 0.999449 | 1.001734 | 1.000735 |

All A/A drift values are inside `[0.85, 1.15]`; no lane has more than one block
outside `[0.80, 1.25]`. Every Q/A value is below its `1.15` (absent/rare) or
`1.10` (medium/common) ceiling and every P/Q value below `1.25`/`1.15`. Every
block ratio is positive and below the `1.50` single-block guard. The largest
observed Q/A is `1.0774` (10K rare, campaign 01); the largest P/Q is `1.0540`
(10K absent, campaign 01).

## 3. Stage attribution (P, instrumented diagnostic)

Median exclusive nanoseconds and median per-sample share. These are **not**
accepted-build latency and the category medians are **not additive** (the sum of
category medians is not the median total).

### 100K medium K100

| Category | 01 ns | 01 share | 02 ns | 02 share |
|---|---:|---:|---:|---:|
| candidate | 8,764,541 | 0.4366 | 8,596,134 | 0.4361 |
| projection | 5,131,783 | 0.2575 | 5,038,885 | 0.2573 |
| leaf_decode | 1,927,631 | 0.0959 | 1,901,731 | 0.0970 |
| other | 1,636,726 | 0.0813 | 1,566,726 | 0.0798 |
| membership | 1,234,720 | 0.0612 | 1,233,120 | 0.0625 |
| score_vector | 925,215 | 0.0459 | 910,114 | 0.0463 |
| eval_residual | 83,402 | 0.0041 | 80,501 | 0.0042 |
| reader_live | 148,803 | 0.0075 | 146,303 | 0.0075 |
| stats | 55,501 | 0.0028 | 54,801 | 0.0028 |
| expand | 1,700 | 0.0001 | 1,700 | 0.0001 |
| plan | 24,900 | 0.0012 | 23,900 | 0.0012 |

### 100K common K100

| Category | 01 ns | 01 share | 02 ns | 02 share |
|---|---:|---:|---:|---:|
| candidate | 24,941,604 | 0.5002 | 24,608,375 | 0.4982 |
| leaf_decode | 7,553,522 | 0.1524 | 7,561,418 | 0.1544 |
| membership | 5,496,989 | 0.1101 | 5,390,229 | 0.1102 |
| projection | 5,349,786 | 0.1071 | 5,290,985 | 0.1078 |
| score_vector | 3,808,961 | 0.0763 | 3,768,761 | 0.0767 |
| other | 1,755,929 | 0.0351 | 1,715,628 | 0.0348 |
| eval_residual | 463,108 | 0.0093 | 426,507 | 0.0086 |
| reader_live | 155,803 | 0.0031 | 153,902 | 0.0031 |
| stats | 57,301 | 0.0011 | 57,001 | 0.0011 |
| expand | 1,800 | 0.0000 | 1,700 | 0.0000 |
| plan | 25,400 | 0.0005 | 25,601 | 0.0005 |

### 100K common K10

| Category | 01 ns | 01 share | 02 ns | 02 share |
|---|---:|---:|---:|---:|
| candidate | 12,948,909 | 0.3447 | 12,697,204 | 0.3437 |
| leaf_decode | 7,663,723 | 0.2056 | 7,494,575 | 0.2040 |
| membership | 5,440,387 | 0.1454 | 5,380,384 | 0.1464 |
| projection | 5,167,583 | 0.1373 | 5,123,883 | 0.1397 |
| score_vector | 3,800,961 | 0.1013 | 3,761,789 | 0.1023 |
| other | 1,666,426 | 0.0439 | 1,630,339 | 0.0444 |
| eval_residual | 442,607 | 0.0117 | 441,307 | 0.0119 |
| reader_live | 153,703 | 0.0041 | 150,902 | 0.0041 |
| stats | 56,901 | 0.0015 | 56,801 | 0.0015 |
| expand | 1,700 | 0.0000 | 1,800 | 0.0000 |
| plan | 25,601 | 0.0007 | 25,400 | 0.0007 |

`eval_residual` is `evaluate − leaf_decode − membership − score_vector`;
`other` is the unclassified top-level residual. Both are non-negative for every
one of the 2,880 P samples, and each per-sample exclusive partition sums exactly
to `engine_ns`.

## 4. Closed-hypothesis ranking (non-causal)

`H-OTHER` is the sum of the `other` and `eval_residual` categories. Primary order
is by 100K common/K100 median exclusive ns descending; exact ties use the fixed
H-table order.

| Rank | Hypothesis | Common/K100 ns (01) | Possible scope |
|---:|---|---:|---|
| 1 | `H-CANDIDATE` | 24,941,604 | `WORTH_REVIEW` (≥20% share in a 100K lane) |
| 2 | `H-LEAF` | 7,553,522 | `WORTH_REVIEW` (common/K10 share 20.6%) |
| 3 | `H-MEMBERSHIP` | 5,496,989 | no |
| 4 | `H-PROJECTION` | 5,349,786 | `WORTH_REVIEW` (medium share 25.8%) |
| 5 | `H-SCORE` | 3,808,961 | no |
| 6 | `H-OTHER` | 2,219,037 | no |
| 7 | `H-LIVE` | 155,803 | no |
| 8 | `H-STATS` | 57,301 | no |
| 9 | `H-PLAN` | 25,400 | no |

`unbatched-02` produces the identical order (values within measurement spread).
Separate absent/K100 order:
`H-LIVE, H-MEMBERSHIP, H-STATS, H-PLAN, H-OTHER, H-LEAF, H-SCORE, H-PROJECTION, H-CANDIDATE`.
Separate rare/K100 order:
`H-LIVE, H-MEMBERSHIP, H-STATS, H-PLAN, H-PROJECTION, H-OTHER, H-CANDIDATE, H-LEAF, H-SCORE`.

`H-OTHER` does **not** top the ranking, so further attribution is not mandated by
the decision rule. `WORTH_REVIEW` is not `SPEEDUP_PREDICTED` and does not
authorize implementation. The dominant `H-CANDIDATE` region covers per-hit
document-key/keyword-sort ownership, bounded-heap admission and comparisons in
`collect_mixed`; that is a diagnostic region, not a proven removable cost.

## 5. Interpretation limits

- P is an **instrumented diagnostic** binary; its percentages are not
  uninstrumented latency shares.
- The workload is exact-term, exact-count, ascending `doc_id`. Quervant performs
  positive-term scoring while the Tantivy PR 15D lane uses `Basic` + `Count` +
  numeric sort; logical equivalence does not imply physical cost equivalence.
- No stage percentage is multiplied by a historical Tantivy gap.
- No optimization is selected, designed or implemented by this report.
