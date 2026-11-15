# PR 15I-D3-B-F1.2 — QA

Executed on the **final rollback tree** (HEAD after the rollback commit
`5d3bf1f7…`; F1.2 tooling unchanged since T3 `c86c3b15…`).

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo test --workspace --all-targets` | PASS — 2,464 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,468 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.68% lines** (87.48% regions, 91.96% functions) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2,464 passed, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,468 passed, 0 failed |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `python3 -m py_compile benchmarks/pr15i_d3_b_f1_2/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b_f1_2` | PASS — 193 tests |
| F1.1 / F1 / D3-B Python suites | PASS — 143 / 95 / 61 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `git diff --check` | PASS |
| T0 / T1 / T2 / T3 tooling diffs | all empty |
| `QUERVANT_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh` | **RUSTFS_HARNESS_PASS** (pinned image started, `/health` reachable) |
| `cargo test -p quervant-core --features s3 --test m1_batches -- --ignored` | PASS — real production S3 adapter batch replay |
| `cargo test -p quervant-core --features s3 --test m2_patches -- --ignored` | PASS — real production S3 adapter patch/reopen/replay |
| D3-B-specific `i12` cold-bootstrap query test | **NOT COUNTED**: test-side assertion at `pr15i_d3_b.rs:647` compares a stale `index.snapshot()` writer view with the cold reader (the production adapter itself is exercised by m1/m2); test file left unmodified per the plan |

## Real boundaries

Canonical same-path release builds; real PR15D corpus and exact oracle; 10K/100K
index byte sentinels; scheduled `engine_ns` samples; `taskset`/`/proc` affinity;
32 genuine contention probes; native ext4; external independent verifier; sealed
archive/sidecar/extraction round trip; real RustFS harness and production adapter
tests.

## Coverage

92.68% workspace line coverage across all production Rust crates; the 85% floor
and exclusions were not modified. The D3-B candidate production delta was rolled
back, so coverage reflects the BASE source plus the retained integration tests.

## Incidental tree state

The pre-existing user modification to `disk-cleanup.sh` was preserved untouched.
