# T7-F2 Gate B — independent decision oracle PASS

- `oracle.py` completed with required APIs, accumulated eligibility, exact
  Fraction GM products, strict 3% boundary, deterministic GM bootstrap and
  nine-row derivation.
- `fixture_factory.py` and `test_oracle.py`: 32 deterministic cases
  (`test_b01`–`b16`, `test_s01`–`s16`), all PASS.
- Real R3-derived comparison:
  `target/pr15i-d3-c/t7-derived/t7f1-analysis-01/analysis.json`
  vs `t7f1-policy-01.json` → 9 rows, zero mismatches:
  `target/pr15i-d3-c/t7f2/gates/t7f2-gate-b.json`.
- Commands:
  `python3 -m unittest benchmarks.pr15i_d3_c_t7_f2.test_oracle -v` → 32 OK;
  `python3 -m benchmarks.pr15i_d3_c_t7_f2.oracle ...` → `mismatches=[]`.

Gates C–E remain incomplete: no `verify_policy.py`, 13 mutation tests,
`freeze_gate.py`, `acceptance_gate.py`, 60-test roster, 11 QA commands, new
freeze/anchor, or final attestation.
