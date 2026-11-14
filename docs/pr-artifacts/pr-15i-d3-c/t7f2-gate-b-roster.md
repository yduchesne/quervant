# T7-F2 Gate A/B acceptance-roster reconciliation

- Exact Gate A roster: `TestAdmission.test_a01`–`a08` — 8 passed.
- Exact Gate B roster: `TestCandidate.test_b01`–`b16` (16) and
  `TestSelection.test_s01`–`s11` (11) — 27 passed.
- Combined: `python3 -m unittest benchmarks.pr15i_d3_c_t7_f2.test_admission benchmarks.pr15i_d3_c_t7_f2.test_oracle`
  → **35 passed, 0 failed, 0 skipped**.
- `fixture_factory.eight_lanes()` added as the approved alias.
- Real R3 oracle comparison: 9 rows, zero mismatches.
- `test_s11` verifies deterministic bootstrap seed and paired output equality.

Gate C–E remain incomplete: no `verify_policy.py`, mutation suite, freeze or
acceptance runner.
