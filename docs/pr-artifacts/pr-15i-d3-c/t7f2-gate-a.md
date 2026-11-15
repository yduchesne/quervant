# T7-F2 Gate A — evidence admission PASS

- HEAD at execution: `f6a4a360f1033f839d6ba5f8cb330c6afc712b8c`
- Inputs: R3 series `target/pr15i-d3-c/official-v3r3`;
  archives `~/.local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3`;
  micro `target/pr15i-d3-c/micro-05/micro.json`;
  F1 receipt `target/pr15i-d3-c/t7f1-freeze/freeze-receipt.json`.
- Protocol SHA verified: `c6193830…`.
- Frozen verifier: PASS, full_series=true, provenance_consistent=true, all
  three campaigns ACQUIRED_VERIFIED.
- Three archive literal SHA-256 values, sidecars, safe member inventories,
  per-member hashes and loose-file equality verified.
- F1 receipt SHA, commit, four Git blobs and current worktree bytes verified.
- Micro: 900 unique Cartesian records, P2/source `3ad6c51…`, five rounds,
  nine memory estimates; K1024 = 1,120,256 bytes.
- Gate A artifact:
  `target/pr15i-d3-c/t7f2/gates/t7f2-gate-a.json`.
- Tests: `python3 -m unittest benchmarks.pr15i_d3_c_t7_f2.test_admission -v`
  → 8 passed, 0 failed.

Gate B remains: complete `oracle.py` API/GM branches, `fixture_factory.py`,
and the 27 `test_b*`/`test_s*` cases. No Gate B-E acceptance is claimed.
