# BM-09 archival snapshot — INCOMPLETE and UNQUALIFIED

**Disposition: `BM09_TERMINATED_INCOMPLETE`.** `BM09_ACCEPTED=NO`. `PR110_MERGE_AUTHORIZED=NO`. `PERF02_NOT_STARTED`.

This branch preserves an unfinished implementation of the BM-09 benchmark-framework
migration, captured from `dev/bm09-real-qualification` at `920ff3a22dc7d15fc8be1dd537f3ee3cbf7a0d5c`
(working tree uncommitted at termination, 13 files, +2107/−50). It is **not** a release, not
qualified, and must not be merged, cited as a result, or used to claim BM-09 completion.

## What is here
- Current-baseline-v2 retained-key build policy (`official/current_retained_build.py`): one closed
  compiler/build policy, per-build own-artifact integrity barrier, versioned premeasurement binding.
- Versioned v2 verifier/publisher (`official/current_retained_verifier.py`): frozen-helper reuse with
  exactly two documented relaxations (no A/A byte equality, no `V_AB`), explicit source basis
  (`checkout` for production, `pinned-git` for offline replay).
- Wiring into `acquisition`, `admission`, `retained_acquisition`, `retained_backend`, `transport`,
  `workflow`; cross-engine `p99` nearest-rank correction (`ordered[18] → ordered[19]`).
- Focused tests: `test_official_current_retained_build.py`, `test_official_current_v2_replay.py`,
  plus updated admission/transport/support fixtures.

## Verified at capture
- `test_official_current_v2_replay`: 15/15 PASS (766 s).
- Earlier in the same session: admission 72 tests OK; `CurrentBaselineProductionAdmissionTests` 5/5.
- Cross-engine `p99` fix proven red→green.

## Known outstanding defect (blocking)
Retained transport replay fails late (4,821 s) with
`BM_UNSAFE_INPUT: unapproved retained-key relocation` from
`transport.validate_recorded_relocations` → the relocation allowlist is narrower than the new
projection, which now rewrites the `--manifest-path` / `--target-dir` argv operands of
`raw/build-provenance.json` and `raw/official-premeasurement-binaries.json`.

## Never done
Full Python discovery, Rust stable+MSRV gates, coverage ≥85 %, real RustFS suites, push/PR/comparative
CI on the new source, fixture re-freeze, commit of a new source `C`, untimed preparation, genuine
33+33 QA assembly, any authorized acquisition, preservation, or replay of a complete baseline.
