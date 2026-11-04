# PR 15G-C fixup performance qualification

**Status:** `PERFORMANCE_REJECTED_SAFE_ROLLBACK`
**Arm A:** `018fdd768d0898d6709baeb8661998ee1a82947c` (accepted pre-C)
**Arm B:** `0a55119b1d47ab4bbd7d9205ad1d84a636d96c2f` (two-pass fixup)
**Stage root:** `target/pr15g-c/qualified-fixup-pair-0a55119-20261104T1713Z/`
**Authorization:** operator assumed-idle instruction; actual probes were `clear`
before (CPU busy 0.0092) and between arms (0.0083), with zero competing processes.
All six trials reported `clear`.

## Method

Nine frozen PR15D warm lanes; 3 trials/arm; 5 warmups + 20 samples; identical
corpus/index digests and exact oracle hits; no lane/sample exclusion or retiming.

## Results

| Lane | A median (ns) | B median (ns) | B/A | Latency | Paired ratios | Verdict |
|---|---:|---:|---:|---:|---|---|
| 10K absent/K100 | 44,703 | 61,670 | 1.380 | −38.0% | 1.297, 1.429, 1.205 | A_FASTER |
| 10K rare/K100 | 49,204 | 66,395 | 1.349 | −34.9% | 1.367, 1.361, 1.094 | A_FASTER |
| 10K medium/K100 | 2,128,909 | 2,177,902 | 1.023 | −2.3% | 1.083, 1.029, 0.941 | INCONCLUSIVE |
| 10K common/K100 | 5,158,384 | 5,412,900 | 1.049 | −4.9% | 1.055, 1.015, 0.950 | INCONCLUSIVE |
| 100K absent/K100 | 264,392 | 441,977 | 1.672 | −67.2% | 1.528, 1.769, 1.780 | A_FASTER |
| 100K rare/K100 | 273,602 | 440,883 | 1.611 | −61.1% | 1.611, 1.604, 1.632 | A_FASTER |
| 100K medium/K100 | 22,916,362 | 22,464,411 | 0.980 | +2.0% | 1.068, 0.976, 0.922 | INCONCLUSIVE |
| 100K common/K100 | 59,364,844 | 56,883,241 | 0.958 | +4.2% | 1.018, 0.958, 0.919 | INCONCLUSIVE |
| 100K common/K10 | 45,886,107 | 44,179,942 | 0.963 | +3.7% | 0.979, 0.969, 0.945 | B_FASTER |

Supplementary geomean B/A: `1.192271` → `0.839×` A/B speedup (19.23% higher
median latency). Supplemental only.

## Gate verdicts

| Gate | Status | Detail |
|---|---|---|
| GF-P01 100K common/K100 B_FASTER | **FAIL** | INCONCLUSIVE |
| GF-P02 100K common/K10 B_FASTER | PASS | B_FASTER |
| GF-P03 100K medium not A_FASTER | PASS | INCONCLUSIVE |
| GF-P04 other six no A_FASTER | **FAIL** | 10K absent/rare, 100K absent/rare A_FASTER |
| GF-P05 qualification | PASS | 9 lanes, 3×20, clear probes, matching digests |
| GF-P06 report/sanitization | PASS | artifacts below |
| GF-P07 semantic mismatch | PASS | no semantic failure observed |
| GF-P08 honest scope | PASS | warm Quervant-only, one host/campaign |
| Overall | **FAIL** | **PERFORMANCE_REJECTED_SAFE_ROLLBACK** |

No tuning or second design was attempted after this qualified failure. The
predetermined rollback restored B production search source.

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `comparison.json` | `80858b20438111917c65b4dc65a8f837028a40a3aaae2ec3154440d0ffc24302` |
| `comparison.md` | `27b33401ff700b4536bde6d6f6551498c12acca769a6f7663098962cfb5412d8` |
| `qualification-summary.json` | `c5b7ab02718d432bba61833fe5a49df348945aaf014093b16f43d5ffefd73967` |

Historical failed-C report under `docs/pr-artifacts/pr-15g-c/` remains untouched.
