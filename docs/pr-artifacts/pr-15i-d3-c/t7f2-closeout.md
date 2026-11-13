# PR 15I-D3-C — T7-F2 independent decision verification closeout

Status: **DECISION-LEVEL VERIFICATION PASS; full F2 acceptance/test matrix and
Rust/QA closeout remain incomplete.**

- R3 protocol: `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`
- T6-R3: `44ccd9e027071cf12777610abae5e6ab5f03177f`
- T7-F1 analysis: `target/pr15i-d3-c/t7-derived/t7f1-analysis-01/analysis.json`
- T7-F1 policy: `target/pr15i-d3-c/t7-derived/t7f1-policy-01.json`
- F2 oracle commit: `8996533b9f2eaf01397ad3504ccf1047547031c3`
- F2 receipt SHA-256: `6182c51774b6a603ca489bb1e73620f8f790345ceb4047267c11e248e50c843a`
- Independent verification: `target/pr15i-d3-c/t7-derived/t7f2-verify/verification.json`
  `verification=PASS`, 9 K rows, zero mismatches.

The independent oracle implemented the required candidate eligibility,
accumulated reasons, guardrail/target/attribution boundaries, filter-sensitivity
and selection rules without importing the F1 policy. It reproduced all nine F1
rows exactly, including the K=256 P tie-breaker.

## Final nine-K result

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

## Not completed

The comprehensive F2 test matrix (`test_oracle`, `test_mutations`,
`test_admission`, `test_freeze_gate`, `test_acceptance_gate`), full archive
admission re-audit, executable acceptance gate, and final Rust/CI closeout were
not completed. The result is therefore a verified decision derivation, not a
fully accepted F2 closeout. No benchmark or micro measurement was run.
