# PR 15I-D3-B-F1.2 — synthetic full-verifier rehearsal

**Final result: `SYNTHETIC_REHEARSAL_ONLY` PASS (round-08).** Synthetic data for
verifier execution coverage only; not a measurement and not publishable.

## Sources and integrity

Copied only sealed members from the local F1.1 fixtures:
`target/pr15i-d3-b/fixup-f1-1/d3bf11-base-aa-01` (59 sealed members, archive
`f58ef556…`) and `d3bf11-base-01` (61 sealed members, archive `69c45bc4…`).
Originals were hashed before/after and were byte-identical; the F1.1 T2 tooling
diff (`63b30a0b… -- benchmarks/pr15i_d3_b_f1_1`) is empty. No `verification.json`
was written into the originals.

## Deterministic transformation

Only identity/attestation/namespace fields were rewritten: campaign and
comparison names (`d3bf12-base`), F1.2 protocol/tooling/schema identities,
build-provenance and host-attestation paths, a synthetic READY readiness record
(seven observations, six 1,000 ms intervals, 50‰ busy), and paired
`raw/attempt-succession.json` predecessor chains. Timed samples were edited only
inside synthetic fixtures:

- the higher BASE 10K-rare block-2 slot vector was replaced by the lower slot's
  original median (drift counterexample removal);
- the eight candidate-arm 100K K10 vectors were reduced by exactly 100,000 ns
  (P03 counterexample removal);
- a separate drift fixture and a separate P03-reject fixture were left without
  one or both edits so the state machine could be exercised.

No synthetic fixture can publish; the guard returns
`D3B_REHEARSAL_PUBLISH_FORBIDDEN` and writes no receipt or archive.

## Results (round-08)

| Fixture | Result |
|---|---|
| RH-01 synthetic control | external verifier PASS, `CONTROL_QUALIFIED`, 60 sealed members |
| RH-02 paired positive | external verifier PASS, `attempt_class=QUALIFIED_PASSED` |
| RH-03 positive series 01+02 | `COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY`, P08 PASS, `FULL_SERIES` |
| RH-04 drift-only 01 | `DRIFT_ONLY_INVALID` |
| RH-05/RH-06 replacement series (D,P,P) | ACCEPTED with `excluded_attempts=['d3bf12-base-01']`, `FULL_SERIES` |
| RH-07 missing readiness | `V_MISSING` |
| RH-08 tampered readiness metrics | `V_READINESS` |
| RH-09 wrong CPU pair | `V_READINESS` |
| RH-10 tampered predecessor hash | series `V_SUCCESSION` |
| RH-11 two drift-only attempts | series `MEASUREMENT_BLOCKED` |
| RH-12 qualified P03 rejection | series `COMPARISON_PERFORMANCE_REJECTED` |
| RH-13 extra attempt after acceptance | series `V_SERIES` |
| RH-14 hidden extra file | `V_INVENTORY` |
| RH-15 original F1.1 files | unchanged (inventory and T2 diff) |
| RH-16 synthetic publication | refused, no artifact |

## Pre-T3 harness corrections (preserved rounds)

Rounds 01–07 were preserved as failed harness attempts and are **not** evidence:
missing `raw/seal.json` copy, arm source SHA hardcoding, unsealed paired
readiness/succession, unmapped source-transition argv, missing attempt-01
succession record, a full-series predecessor-name comparison bug, a
missing-readiness fixture write, and a report variable reuse. Each was corrected
within the new F1.2 tooling only; the full 193-test suite and the entire
rehearsal were rerun after each change. T3 is the last candidate commit whose
rehearsal passed without any tooling byte changing.
