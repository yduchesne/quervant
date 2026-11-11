# PR 15I-D3-A-F2 QA

Final state: branch `dev/pr15i-d3a-candidate-attribution`, BASE
`409fb0fdf370bb4d4dade5ea507c6fa4518b5220`, T0d
`2c74e40d87f319c548c1f485d9b0267208311743`. Production Rust source is unchanged.

| Command | Result |
|---|---|
| `python3 -m py_compile benchmarks/pr15i_d3a/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3a -p 'test_*.py' -v` | PASS — 92 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v` | PASS — 76 tests |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **91.96% lines**, 92.67% regions, 87.48% functions |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `git diff --check` | PASS |
| Protected-path diff vs BASE (worktree and HEAD) | PASS — empty |
| `tooling_manifest_v3.json` validation | PASS — exact file set/hashes |
| Tooling unchanged since T0d | PASS |

## External gates

- RustFS: `RUSTFS_NOT_RUN_NOT_REQUIRED_FOR_D3AF2_LOCAL_ATTRIBUTION`.
- Hosted CI: `CI_PENDING`.
- Independent review: `REVIEW_PENDING`.
- PR: `PR_NOT_CREATED` (GitHub CLI token invalid; branch pushed by SSH).

## Measurement result

`D3AF2_ATTRIBUTION_QUALIFIED`; priority verdict
`D3A_CANDIDATE_HOTSPOT_LOCALIZED` for the sampled `candidate_duplicate` child on
100K medium/K100 and 100K common/K100 across the same five run IDs. Run 03 was
lane-scoped for 10K rare (Q/A median 1.1838 > 1.15); all other lanes were
eligible. The verdict is diagnostic only and authorizes no optimization.
