# PR 15I-D3-B-F1 — QA

Executed on the final working tree at branch HEAD `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82`
(T1) with no production/test change relative to the D3-B candidate
`48d9abf3eeefbccb480d89eac95f6e6911e078d5`; F1 adds only the isolated benchmark
tooling and PR documentation.

## Commands and results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,496 passed, 0 failed |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,496 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.85% lines** (87.79% regions, 92.17% functions) |
| `cargo test -p quervant-core --lib d3b_tests` | PASS — 28/28 |
| `cargo test -p quervant-core --test pr15i_d3_b` | PASS — 10/10 (I12 ignored without RustFS) |
| `python3 -m py_compile benchmarks/pr15i_d3_b_f1/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b_f1 -p 'test_*.py'` | PASS — 95 tests |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py'` | PASS — 61 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `git diff --exit-code 155ebafa… -- benchmarks/pr15i_d3_b` | PASS (old T0 unchanged) |
| `git diff --exit-code ac45c23f… -- benchmarks/pr15i_d3_b_f1` | PASS (F1 T1 unchanged) |
| `git diff --check` | PASS |
| `cargo fmt --all -- --check`, `cargo +1.85.0 fmt` | PASS |

Full earlier variants `cargo test --workspace --all-targets` and the MSRV
equivalent were also executed and passed; the all-features counts above include
every workspace test binary.

## Real boundaries

| Boundary | State |
|---|---|
| Canonical worktree creation/switch, two real `cargo build --release --locked` executions | PASS (dry proof + control) |
| Real PR15D corpus, 10K/100K index builds, exact oracle, 100K sentinels | PASS (control) |
| Real `FsDirectory` writer→commit→reopen→query | PASS (candidate I11, unchanged) |
| Real pinned CPU affinity, `/proc` observations, contention probes | PASS (control: 32/32 clear, all lane records observed) |
| Independent verifier replay of the sealed control | **FAIL** — two post-T1 tooling defects, see `a-a-control.md` |
| RustFS/S3 production adapter | `RUSTFS_PENDING` (pinned image cannot start under podman-compose 1.0.6; no fake pass) |
| Hosted CI | `CI_PENDING` |
| Independent human review | `REVIEW_PENDING` |

## Coverage note

The measured 92.85% line coverage is unchanged from the D3-B candidate state
because F1 touches no Rust source or test file. The 85% floor was not modified
and no module is excluded.

## Failure classification

- The two verifier defects are **tooling implementation defects in the frozen
  F1 harness** (post-T1). They are not production regressions and not evidence
  defects; they block measurement acceptance (`MEASUREMENT_BLOCKED`).
- No Rust test, coverage, format or Clippy failure occurred.
- `RUSTFS_PENDING` remains an environment limitation, carried forward.
