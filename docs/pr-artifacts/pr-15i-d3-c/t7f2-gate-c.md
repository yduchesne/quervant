# T7-F2 Gate C — independent policy verification PASS

- `verify_policy.py`: re-authenticates R3 via `admission.audit`, validates
  analysis/policy shape, runs frozen F1 `verify_derived.py`, independently
  derives nine decisions through the F2 oracle, compares exact decision fields,
  and writes PASS only when all checks pass.
- Real CLI positive:
  `target/pr15i-d3-c/t7f2/diagnostics/positive-01` →
  `verification=PASS`, `comparison_rows=9`, `statistical_lanes=72`.
- `test_mutations.py`: 13/13 `TestMutation` tests PASS, including actual CLI
  rejection of selected, status and CI mutations.
- Commands executed:
  `python3 -m unittest benchmarks.pr15i_d3_c_t7_f2.test_mutations -v`
  → 13 OK (406 s);
  positive `verify_policy.py` CLI → PASS.
- Original R3/F1/micro hashes unchanged; no measurement performed.

Gate D/E remain incomplete: no 60-test acceptance runner, freeze gate,
new F2 freeze/anchor, or final attestation.
