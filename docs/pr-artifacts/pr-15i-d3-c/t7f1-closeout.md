# PR 15I-D3-C — T7-F1 closeout

Status: **R3 acquisition complete; T7-F1 analysis independently checked;
policy decisions derived but not fully independently recomputed.**

- R3 protocol: `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`
- T6-R3: `44ccd9e027071cf12777610abae5e6ab5f03177f`
- T7-F1 commit: `38a937fdf0b09f1330f26423dabb311399c8a4cf`
- T7-F1 receipt SHA-256: `80f21e8fb7c9a76d466d749b0253f50bf8955112db0214386abbfcb9a9532ee1`
- Inputs: three verified R3 archives, 345,600 samples, `full_series=true`.
- Fresh derivation: `target/pr15i-d3-c/t7-derived/t7f1-analysis-01/analysis.json`
- Policy: `target/pr15i-d3-c/t7-derived/t7f1-policy-01.json`
- Independent check: `t7f1-verify-01/verification.json`, PASS, 72 lanes / 9 rows.

## Nine-K result

| K | Selected | Decision | P | H |
|---:|---|---|---|---|
| 1 | LINEAR_BASE | LINEAR_BASE | INELIGIBLE | INELIGIBLE |
| 10 | LINEAR_BASE | LINEAR_BASE | INELIGIBLE | INELIGIBLE |
| 32 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 64 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 100 | INCONCLUSIVE | K_INCONCLUSIVE | ELIGIBLE | INCONCLUSIVE |
| 128 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 256 | P | P_TIEBREAKER_NOT_PROVEN_FASTER | ELIGIBLE | ELIGIBLE |
| 512 | INCONCLUSIVE | K_INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| 1024 | INCONCLUSIVE | K_INCONCLUSIVE | ELIGIBLE | INCONCLUSIVE |

All 72 lanes retained at least four blocks. H auxiliary memory is within the
2,097,152-byte gate at every K. K=1/10 fail the 3% target; K=256 is the only
fully eligible P/H pair and selects P by the within-3% tie rule, not as a
proven faster arm. Large K>=64 point gains remain statistically inconclusive
because of guardrail/target CI uncertainty and filter sensitivity.

## Verified scope

The independent verifier recomputed every lane's retained/excluded blocks,
arm medians, P/A H/A L/A P/L H/L H/P point ratios, and all paired 10,000-draw
CIs from the sealed slots, and checked the nine policy rows' input and memory
consistency. It did not independently recompute every policy eligibility and
selection decision from scratch. The comprehensive T7-F1 test matrix and
decision-level verifier are therefore **not** complete.

No benchmark, micro, or acquisition command was run. R3 archives and raw
evidence remain unchanged. This remains an experiment-only recommendation.
