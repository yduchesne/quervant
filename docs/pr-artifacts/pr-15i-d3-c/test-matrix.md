# PR 15I-D3-C — test matrix (executed subset)

All commands were run on the implementation tree. D3-C tooling exists; the
source integration matrix is closed except for the explicitly listed U/PM
residuals, and the official V/M/P/RH/T4 gates remain **NOT RUN**.

| Suite | State |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,478 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,514 passed, 0 failed |
| `cargo test -p quervant-core --features pr15i-d3c-experiment d3c_tests` | PASS — 37 passed, 1 ignored (`d3c_micro_grid`) |
| D3-C V01–V60 / M01–M16 / P01–P22 / RH-01–RH-16 | PARTIAL: preflight, dry-proof and 8 rehearsal cases pass; full matrices NOT RUN (T4 not frozen) |
| D3-C I01–I12 real `FsDirectory` integration | PASS — 12 tests: I01, I02 (72 real adapter lanes), I03, I04 (pinned + upsert/delete/compaction), I05, I06, I07 (2 tests), I08, I09, I10, I12 (2 no-feature subprocess tests). I11 is the separate real RustFS gate below. |
| D3-C I11 real RustFS | PASS — `m1_v04_real_rustfs_batch_replay_and_generation_consistency` and `m2_v04_real_rustfs_patch_reopen_replay` each 1 passed, 0 ignored against pinned RustFS 1.0.1 via podman. |
| Python D3-C suites | PASS — 14 tests (`test_harness.py` + `test_policy.py` PM01–PM10) |
| Coverage, docs, bench, MSRV, RustFS, CI, review | NOT RUN for D3-C final state |

Implemented U-IDs: U01–U34, U36, U37, U39, U41, U42, U43.
U23 is exercised by the existing `b_fixup_losing_keyword_payload_invalid_utf8_fails_before_discard`
codec test plus I08; U35 is satisfied by the executed no-feature I12 child/parent
pair; U38 is exercised by `run.py adapter-compare` single-marker checks.
U24/U25 exercise legacy and borrowed keyword duplicate sites; U40 runs
linear/P2/exact_set in separate feature-mode processes and compares exact score
bits and two-page cursor keys. The owned-general inline duplicate guard has no
separate standalone U witness; its shared `experiment.check` guard is exercised
by the strategy states and `g_b04` corruption control.
