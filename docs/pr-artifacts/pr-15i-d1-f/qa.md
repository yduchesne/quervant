# PR 15I-D1-F — local QA

Final source tree: production restored to exact BASE bytes by the additive
rollback `051c319…`; the only remaining changes are the F0 tooling and F1/F3
documentation. Working tree clean at the final commit.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable) | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,439 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,443 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.68% lines** (97,024 lines, 7,106 missed); functions 87.48%, regions 91.96% |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,443 passed, 0 failed |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `python3 -m py_compile benchmarks/pr15i_d1_f/{run,verify,test_run}.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d1_f -p 'test_*.py'` | PASS — 25 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `git diff --check` | PASS |

Targeted C2 tests (executed at F2 before rollback): 4 reader tests, 5 search
unit tests and 5 real public-path integration tests, all PASS. `cargo test -p
quervant-core --all-features` passed entirely.

## RustFS / CI / review

Real RustFS is unavailable on this host (no service or container). The required
core suites are **`RUSTFS_PENDING`**; no fake backend was substituted. Hosted CI
was not run (`CI_PENDING`), no PR was created (`PR_NOT_CREATED`) and independent
review is pending (`REVIEW_PENDING`).

## Host/timers

WSL2 `6.18.33.2-microsoft-standard-WSL2`, ext4, 12 CPUs; benchmark processes
pinned with `taskset -c 4,5`. Both Quervant user timers were active+enabled,
were stopped only for measurement, and were restored to the exact original
active state (`target/pr15i-d1-f/timer-state-*.txt`). No destructive cleanup,
Podman reset or repository-wide `cargo clean` was performed.
