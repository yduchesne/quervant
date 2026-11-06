# PR 15G-C performance qualification

**Status:** `PERFORMANCE_NOT_ACCEPTED`
**Measured arm A:** `018fdd768d0898d6709baeb8661998ee1a82947c` (shared pre-C)
**Measured arm B:** `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e` (C candidate)
**Campaign stage root:** `target/pr15g-c/qualified-pair-5ec886f-20261104T1525Z/`
**Operator authorization:** assume-idle instruction; actual probes were `clear`
before, between and after trials (CPU busy fractions 0.0100 / 0.0146; zero
competing processes). This is recorded as an authorized assumption plus measured
clear probes, not a claim of impossible-to-observe Windows-host interference.

## Method

- Exact nine frozen PR15D warm lanes; 5 warmups + 20 samples; 3 trials/arm.
- Same host, corpus manifest
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`,
  identical 10K/100K index digests.
- Exact oracle hit counts matched; all six trials qualified with `clear`
  contention.
- No samples/lanes excluded and no retuning after measurement.

## Results

| Lane | A median (ns) | B median (ns) | B/A | Latency change | Paired trial ratios | Verdict |
|---|---:|---:|---:|---:|---|---|
| 10K absent/K100 | 62,500 | 76,290 | 1.221 | −22.1% | 0.840, 1.224, 1.283 | INCONCLUSIVE |
| 10K rare/K100 | 62,520 | 76,231 | 1.219 | −21.9% | 1.131, 1.145, 1.402 | A_FASTER |
| 10K medium/K100 | 2,974,088 | 3,282,890 | 1.104 | −10.4% | 0.856, 1.192, 1.107 | INCONCLUSIVE |
| 10K common/K100 | 7,709,998 | 8,279,490 | 1.074 | −7.4% | 0.811, 1.028, 1.271 | INCONCLUSIVE |
| 100K absent/K100 | 351,192 | 570,521 | 1.625 | −62.5% | 1.263, 1.675, 1.625 | A_FASTER |
| 100K rare/K100 | 343,500 | 540,554 | 1.574 | −57.4% | 1.685, 1.611, 1.574 | A_FASTER |
| 100K medium/K100 | 30,332,316 | 31,603,549 | 1.042 | −4.2% | 1.256, 1.154, 0.972 | INCONCLUSIVE |
| 100K common/K100 | 73,908,122 | 85,278,201 | 1.154 | −15.4% | 1.129, 1.315, 1.102 | A_FASTER |
| 100K common/K10 | 53,175,081 | 68,292,687 | 1.284 | −28.4% | 1.284, 1.366, 1.192 | A_FASTER |

**Supplementary aggregate:** geometric mean B/A `1.240647`, i.e. `0.806×` A/B
speedup (24.06% higher median latency). Not an acceptance substitute.

## Gate verdicts

| Gate | Status | Detail |
|---|---|---|
| GC-P01 100K common/K100 B_FASTER | **FAIL** | `A_FASTER` |
| GC-P02 100K common/K10 B_FASTER | **FAIL** | `A_FASTER` |
| GC-P03 100K medium not A_FASTER | PASS | actual verdict `INCONCLUSIVE` |
| GC-P04 other six lanes no A_FASTER | **FAIL** | 10K rare, 100K absent, 100K rare `A_FASTER` |
| GC-P05 trial/input qualification | PASS | 9 lanes, 3×20, clear probes, identical digests |
| GC-P06 sanitized report | PASS | `comparison.json`/`.md` below |
| GC-P07 semantic/error mismatch | PASS | none observed; timing failure only |
| Overall | **FAIL / PERFORMANCE_NOT_ACCEPTED** | |

No threshold or eligibility heuristic was changed after seeing the result.

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `comparison.json` | `40bfaf30b1f4d6deea38568e7f9cae68cb3136fbab7a7131c2d32b7e1b0bc1fd` |
| `comparison.md` | `d3c82a6ee7bd37e3e327f51fb062315bed64815a0d879f9a8e1a6b8b7502da84` |
| `qualification-summary.json` | `e2859dd9fd92a02e798e1bb2e0cad40ed3114bb1640aa3733e62470166c55746` |

Raw samples/contention/setup remain under the stage root in ignored `target/`.

## Interpretation

The C implementation is functionally correct in the exercised scope but is
measurably slower than the B baseline on every lane sign-consistency-wise, and
fails both mandatory high-hit gates. No causal profiling was performed and no
further optimization is authorized by this plan. Performance is **not accepted**;
human review must decide whether to revert, retain as experimental, or request a
new measured design.
