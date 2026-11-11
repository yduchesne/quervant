# PR 15I-D3-A QA

Final state: normal tooling branch `dev/pr15i-d3a-candidate-attribution`, BASE
`409fb0fdf370bb4d4dade5ea507c6fa4518b5220`, T0b
`fd216580374cc0f30a9ca84b44f7b8a7cd760a08`. Production Rust source is unchanged
from BASE.

## Command results

| Command | Result | Evidence |
|---|---|---|
| `python3 -m py_compile benchmarks/pr15i_d3a/*.py` | PASS | all scripts compile |
| `python3 -m unittest discover -s benchmarks/pr15i_d3a -p 'test_*.py' -v` | PASS | 56 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS | 83 tests, 3 skipped |
| `python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v` | PASS | 76 tests |
| `cargo fmt --all -- --check` | PASS | |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS | no warnings |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS | no warnings |
| `cargo test --workspace --all-targets` | PASS | |
| `cargo test --workspace --all-targets --all-features` | PASS | 2,458 passed / 0 failed / 92 ignored across 136 targets (coverage run) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS | **91.96% lines**, 92.68% regions, 87.48% functions |
| `cargo doc --workspace --no-deps` | PASS | |
| `cargo +1.85.0 fmt --all -- --check` | PASS | |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS | |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS | |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS | |
| `git diff --check` | PASS | |
| `git diff --exit-code BASE HEAD -- crates/ Cargo.toml Cargo.lock .github/ AGENTS.md benchmarks/pr15d/ benchmarks/pr15i_d2a/` | PASS | empty |

## External gates

- RustFS: `RUSTFS_NOT_RUN_NOT_REQUIRED_FOR_D3A_ATTRIBUTION`. The local S3/RustFS
  integration targets are ignored without a pinned instance; no local RustFS
  result is reported as PASS.
- Hosted CI: `CI_PENDING`.
- Independent review: `REVIEW_PENDING`.
- PR: `PR_NOT_CREATED`.

## Coverage note

The 85% floor is measured on the entire Rust workspace production code, not a
selected crate. The tooling scripts are Python and are exercised by the 56
targeted tests; they do not contribute to the Rust coverage denominator.

## Measurement gate

`D3A_MEASUREMENT_BLOCKED` due to the T0b A/A control failure. This is a QA
outcome, not a code defect; the repository code gates above pass.
