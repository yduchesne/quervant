# PR 15I-D3-B-F1.1 — QA

Executed after the final F1.1 tooling change (T2 = T_PRE3
`63b30a0be451357a5edaf8399ad2e4d336e6c45b`). No Rust source/test/Cargo file
changed in F1.1; the workspace is byte-identical to the D3-B candidate
`48d9abf3…`.

## Commands and results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo test --workspace --all-targets` | PASS — 2,492 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,496 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.85% lines** (87.79% regions, 92.17% functions) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compilation only) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2,492 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,496 passed, 0 failed |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `python3 -m py_compile benchmarks/pr15i_d3_b_f1_1/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b_f1_1 -p 'test_*.py'` | PASS — **143 tests** (95 inherited F1 + 48 F1.1) |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b_f1 -p 'test_*.py'` | PASS — 95 tests |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py'` | PASS — 61 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `git diff --check` | PASS |
| `git diff --exit-code 155ebafa… -- benchmarks/pr15i_d3_b` | PASS (empty) |
| `git diff --exit-code ac45c23f… -- benchmarks/pr15i_d3_b_f1` | PASS (empty) |
| `git diff --exit-code 63b30a0b… -- benchmarks/pr15i_d3_b_f1_1` | PASS (empty) |

The targeted F1.1 rehearsal matrix (`replay.py` round-03) executed one positive
and fifteen negative/invariance cases through the **external** verifier: 16/16
expected results, original files unchanged, no archive written.

## Real boundaries

| Boundary | State |
|---|---|
| Canonical one-path builds, two target dirs, byte-identical A/A binaries | PASS (control) |
| Same-path BASE→candidate switch, distinct A/B binaries | PASS (campaign 01) |
| Real PR15D corpus/index/oracle and 100K sentinels | PASS (control and campaign) |
| Real `FsDirectory` writer→commit→reopen→query | PASS (candidate `i11`) |
| Pinned CPU affinity and `/proc` observations | PASS (all 144 lane records per campaign) |
| Contention probes | PASS (32/32 clear per campaign) |
| Independent verifier | PASS for control and campaign 01 (campaign 01 status blocked by drift) |
| RustFS/S3 | **RUSTFS_PENDING** — `QUERVANT_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh` cannot start the pinned image under podman-compose 1.0.6 (`short-name ... did not resolve to an alias`); no fake pass |
| Hosted CI | `CI_PENDING` |
| Independent review | `REVIEW_PENDING` |

## Coverage

92.85% workspace line coverage on all production Rust crates; the 85% floor and
exclusions were not modified. F1.1 adds no Rust production code.

## Incidental tree state

A pre-existing user modification to `disk-cleanup.sh` was present in the working
tree before the F1.1 tooling commit and was **not** touched, staged or reverted.
It is unrelated to the measurement tooling and evidence.
