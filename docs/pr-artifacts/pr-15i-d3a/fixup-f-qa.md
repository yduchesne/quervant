# PR 15I-D3-A-F QA

Final state: branch `dev/pr15i-d3a-candidate-attribution`, BASE
`409fb0fdf370bb4d4dade5ea507c6fa4518b5220`, T0c
`0f07c29c318982afaf4ce6790ce5272e8754aa11`. Production Rust source is unchanged
from BASE.

| Command | Result |
|---|---|
| `python3 -m py_compile benchmarks/pr15i_d3a/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3a -p 'test_*.py' -v` | PASS — 85 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v` | PASS — 76 tests |
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.96% lines**, 92.68% regions, 87.48% functions |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `git diff --check` | PASS |
| Protected-path diff vs BASE (worktree and HEAD) | PASS — empty |
| `tooling_manifest_v2.json` validation | PASS — exact file set and hashes |

## External gates

- RustFS: `RUSTFS_NOT_RUN_NOT_REQUIRED_FOR_D3AF_ATTRIBUTION`. Ignored local
  RustFS tests are not a PASS.
- Hosted CI: `CI_PENDING`.
- Independent review: `REVIEW_PENDING`.
- PR: `PR_NOT_CREATED` (invalid GitHub CLI token; no fabricated URL).

## Measurement result

`D3A_MEASUREMENT_BLOCKED`: control and runs 01–03 qualified, run 04 failed the
frozen paired A/A stability gate, run 05 was not executed. The code and
documentation gates above passed; the measurement gate did not.
