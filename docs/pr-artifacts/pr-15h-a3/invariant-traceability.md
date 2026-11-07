# PR 15H-A3 — invariant traceability

| ID | Invariant | Evidence | Status |
|---|---|---|---|
| I01 | Final production Rust equals accepted A | `git diff --quiet 7a136f7 HEAD -- crates/quervant-core/src/search` exit 0 | PASS |
| I02 | Frozen inputs/historic evidence unmodified | path audit; A2 verify-only; no edits under `benchmarks/pr15d`, `pr15e_b1`, `pr15h_a`, `pr15h_a2`, `docs/pr-artifacts/pr-15h-a*` | PASS |
| I03 | A2 B resolves and descends from A | `git cat-file`, `merge-base --is-ancestor` | PASS |
| I04 | A2 helper/dispatch inspected from source | region hashes `966554bc…`, `9b811a60…`; source control-flow table | PASS |
| I05 | Sparse route has zero helper calls; common uses it | candidate `phase15h_a2_tests` (10), `linear_term_a2_tests` (2), `pr15h_a2_dispatch` (8) | PASS |
| I06 | A/A uses two independent builds of the same source | two build dirs, identical binary SHA `3370083e…` | PASS |
| I07 | Pinned clean detached worktrees | tooling/base/candidate worktree status empty at exact SHAs | PASS |
| I08 | Only the four fixed warm lanes | controller canonical tuple; tests B01–B03 | PASS |
| I09 | Oracle hit-count/doc-ID agreement | controller expected-hit/doc-ID checks; A/A 16 oracle checks | PASS |
| I10 | Native FS and environment fingerprint recorded | ext4; fingerprint `4f971362…` | PASS |
| I11 | Frozen nearest-rank summaries | raw 20-sample recomputation in controller; tests B10–B12 | PASS |
| I12 | Raw/manifest sealed before reporting | `raw/seal.json` `b1579ba1…`; `verify` pass | PASS |
| I13 | A/A qualified before attribution | A/A **blocked**; A/B not run | BLOCKED (recorded) |
| I14 | Fixed mirrored schedule, no selective rerun | AA schedule enforced; no retry performed | PASS |
| I15 | Drift distinguished from regression | AA caps and drift helpers tested; no fabricated verdict | PASS |
| I16 | Profiles are observations only | `PROFILE_UNAVAILABLE`; disassembly marked observation | PASS |
| I17 | V2/V3 exact edits | not created; prereq-blocked | N/A (recorded) |
| I18 | Original semantics untouched | production equality; A2/H-A integration suites pass | PASS |
| I19 | No codegen causality without intervention | `MEASUREMENT_BLOCKED`; no causal label | PASS |
| I20 | No acceptance/retention claim | controller rejects `PERFORMANCE_ACCEPTED`/`OPTIMIZATION_RETAINED`; tests B28 | PASS |
| I21 | `UNRESOLVED`/blocked can conclude | terminal `MEASUREMENT_BLOCKED` recorded | PASS |
| I22 | No push/PR/merge | branch local only; no remote operation | PASS |

Controller matrix B01–B28 executes as 28 `unittest` tests (some functions assert
multiple rows): `python3 -m unittest discover -s benchmarks/pr15h_a3 -p 'test_*.py'`
→ 28 passed.
