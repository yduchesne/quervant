# T7-F2 final attestation

**T7_POLICY_COMPLETE — EXPERIMENT ONLY.**
Production adoption=false, merge_authorized=false.

- Accepted source commit: `a59fdfc0230aa15b71aaf11566960bc47f7c7723`
- Freeze receipt: `target/pr15i-d3-c/t7f2/freeze/freeze-receipt.json`
- Receipt SHA-256: `cc7f5af8a680a88dc5414f9a3d9ba27b292d0f53478afc57b7f94d7d71cc0136`
- Acceptance: 60/60 exact tests, 11/11 QA commands.
- R3 protocol: `c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c`
- T6-R3: `44ccd9e027071cf12777610abae5e6ab5f03177f`
- Two fresh derivations byte-identical:
  - analysis `2c3854e4ff02f5acc9d7837d0267ae40101180df01c7db088705451bc8df3065`
  - policy `e68ce9298e3be05540f732d51408085fc0f742e5fed45db52a2e48454576be21`
- Independent verification: PASS for both, 9/9 rows, 72 lanes.

## Nine-K result

| K | Selected | Decision |
|---:|---|---|
| 1 | LINEAR_BASE | LINEAR_BASE |
| 10 | LINEAR_BASE | LINEAR_BASE |
| 32 | INCONCLUSIVE | K_INCONCLUSIVE |
| 64 | INCONCLUSIVE | K_INCONCLUSIVE |
| 100 | INCONCLUSIVE | K_INCONCLUSIVE |
| 128 | INCONCLUSIVE | K_INCONCLUSIVE |
| 256 | P | P_TIEBREAKER_NOT_PROVEN_FASTER |
| 512 | INCONCLUSIVE | K_INCONCLUSIVE |
| 1024 | INCONCLUSIVE | K_INCONCLUSIVE |

Large point gains appear from K>=64 but remain statistically inconclusive for
most K due to target/guardrail CI and filter-sensitivity rules. K=256 is the
only fully eligible P/H pair and P is selected by the within-3% tie preference,
not as a proven faster arm.

No benchmark, microbenchmark, or acquisition measurement was performed. R3,
T6 and T7-F1 historical evidence is unchanged. No merge or production
recommendation is authorized.
