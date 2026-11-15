# PR 15I-D3-C — T7 read-only final analysis and nine-K result

Status: **ANALYSIS COMPLETE; POLICY DERIVED BUT NOT INDEPENDENTLY VERIFIED/FROZEN.**
No benchmark or micro measurement was rerun. R3 acquisition remains intact.

- R3 protocol: `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`
- T6-R3: `44ccd9e027071cf12777610abae5e6ab5f03177f`
- Inputs: 3 verified archives, 345,600 timed samples, `full_series=true`
- Analysis: `target/pr15i-d3-c/t7-derived/official-analysis-01/analysis.json`
- Policy: `target/pr15i-d3-c/t7-derived/policy-02.json`
- Micro: `target/pr15i-d3-c/micro-05/micro.json`, P2, source `3ad6c51…`

## Nine-K decision rows

| K | Selected | Status | P | H |
|---:|---|---|---|---|
| 1 | LINEAR_BASE | LINEAR_BASE | INELIGIBLE | INELIGIBLE |
| 10 | LINEAR_BASE | LINEAR_BASE | INELIGIBLE | INELIGIBLE |
| 32 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 64 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 100 | INCONCLUSIVE | K_INCONCLUSIVE | ELIGIBLE | INCONCLUSIVE |
| 128 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 256 | **P** | P_TIEBREAKER_NOT_PROVEN_FASTER | ELIGIBLE | ELIGIBLE |
| 512 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 1024 | INCONCLUSIVE | K_INCONCLUSIVE | ELIGIBLE | INCONCLUSIVE |

K=1/10 miss the 3% primary target. K=32/64/100/128/512/1024 have at least one
inconclusive guardrail or target result despite large point gains; no forced
winner. K=256 is the only fully eligible P/H pair; P is selected by the
within-3% tie preference, explicitly **not proven faster** than H.

### 100K target-lane point ratios (P/A, H/A)

| K | C01 medium | C01 common | C02 medium | C02 common |
|---:|---|---|---|---|
| 1 | 1.0022 / 1.0040 | 1.0247 / 1.0265 | 1.0169 / 1.0153 | 1.0222 / 1.0280 |
| 10 | 0.9990 / 1.0030 | 0.9932 / 1.0009 | 1.0048 / 1.0052 | 0.9945 / 1.0019 |
| 32 | 0.9687 / 0.9724 | 0.9245 / 0.9283 | 0.9691 / 0.9702 | 0.9265 / 0.9227 |
| 64 | 0.9153 / 0.9103 | 0.8407 / 0.8440 | 0.9190 / 0.9059 | 0.8420 / 0.8447 |
| 100 | 0.8629 / 0.8590 | 0.7645 / 0.7648 | 0.8605 / 0.8570 | 0.7664 / 0.7725 |
| 128 | 0.8166 / 0.8239 | 0.7089 / 0.7095 | 0.8159 / 0.8391 | 0.7122 / 0.7143 |
| 256 | 0.6560 / 0.6658 | 0.5163 / 0.5115 | 0.6683 / 0.6688 | 0.5158 / 0.5140 |
| 512 | 0.4967 / 0.4960 | 0.3544 / 0.3456 | 0.5016 / 0.4991 | 0.3536 / 0.3425 |
| 1024 | 0.3427 / 0.3111 | 0.2314 / 0.1884 | 0.3440 / 0.3128 | 0.2327 / 0.1873 |

## Interpretation

- K=1/10: no measurable gain; linear/base retained.
- K≥32: large point-estimate gains, increasing with K; P and H are close, with P
  usually slightly ahead.
- Formal eligibility is limited by guardrail/target CI uncertainty and
  filter-sensitivity checks, not by missing blocks. All 72 lanes retained at
  least four blocks.
- H memory is eligible at every K under the 2,097,152-byte auxiliary estimate
  (K1024 = 1,120,256 bytes).

## Missing gates

`verify_derived.py`, the T7 analysis-only freeze receipt, and the full T7
test matrix were not completed. The policy JSON is therefore labeled
`T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION`, not
`T7_POLICY_COMPLETE`. No production change or merge is proposed.
