# PR 15I-D3-C — stability remediation execution ledger

- Starting HEAD: `07fded225306c4e2cddb06e20068541dbc4899b7`
- Source: `3ad6c5184fbe9c011abb731415a007e3f19d21de`
- v1 protocol SHA: `c7a062f85ffc2b356612ea0b47e062cb7f59c23444164c438fd2a3d9f0404002`
- v2 protocol SHA: `55255c687ccfa65f8cffe3169cca6f01880584f30e3c7f29843489bedc42a5c5`
- T5 tooling commit: `1bdbef8984461de7ddc6c8fd30a1960e6accf140`

## Stage 0

- Branch/HEAD verified; `main` `39dbd9f...`; user `disk-cleanup.sh` untouched.
- Failed v1 evidence inventoried in `failed-aa-sha256.txt` (55 files).
- Verifier: structural PASS, `MEASUREMENT_BLOCKED`, 16 slots, 72 lanes,
  23,040 samples, 17 drift violations. Evidence not modified.

## Stage 1

- Corrected gate arithmetic to frozen `median4` lower-middle semantics.
- Gate deviation: median 1.797%, p95 7.613%, max 20.096%.
- Arm aggregate: median 1.246%, p95 6.924%, max 9.912%.
- Named outliers: `10000/absent/k100` gate 0.799/aggregate 0.901;
  `10000/rare/k1024` gate 0.839/aggregate 0.943.
- Four nonexempt 10K medium lanes fail block-2 bands despite ≤0.9% aggregate.
- Read-only analyzer and A01–A06 tests PASS.

## Stage 2

- Topology audit chose adapter CPU 0 / controller CPU 2, same package, distinct
  physical cores; v1 had used SMT siblings 0/1.
- Governor/frequency files unavailable: `NOT_OBSERVED`; no OS tuning performed.
- H01–H06 tests PASS.

## Stage 3

- 13 fixed lanes, 16 slots, 4,160 real samples, 1,040 warmups.
- `DIAGNOSTIC_STABLE`; original subset A/A `CONTROL_QUALIFIED`; drift PASS with
  zero violations.
- Evidence: `target/pr15i-d3-c/stability-diagnostics/d3c-stability-diag-01`.
- D01–D05 tests PASS.

## Stage 4

- Protocol v2 diff is exactly the three authorized identity fields.
- v2 preflight and dry-proof PASS; rehearsal 3 positives/16 negatives PASS.
- Micro: `PROTOCOL_IDENTITY_REWRAP_ONLY`, original 900 records unchanged,
  source/P2/map preserved, v2 protocol identity validated.
- T5 frozen at `1bdbef8`; manifest `b5237729...`.
