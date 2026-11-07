# PR 15H-D — QA and CI

## Final source

- Branch: `dev/pr15h-a-linear-term-candidates`
- D tooling / A: `c802f965a57d5038e98006bba581c4356654baaf`
- Candidate: `0f97779191ad1969d00dd15988601ade0ab59522`
- Rollback: `2ac85c7a936fe4e57fea78c54700d0a58a544acf`
- `git diff --quiet c802f96 HEAD -- search/unified.rs search/unified_plan.rs` exit 0.
- Worktree clean; D tooling/tests/evidence retained.

## Controller tests

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15h_d -p 'test_*.py'` | PASS — 49 tests |
| `python3 -m unittest discover -s benchmarks/pr15h_c -p 'test_*.py'` | PASS — 51 tests |
| `python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py'` | PASS — 33 tests |
| `cargo test -p quervant-core --lib search::unified::b_tests` | PASS — 6 |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | PASS — 6 |

At the candidate, `search::unified::d_tests` ran 3 test functions covering
D-U01–U10/U14 and passed; they were removed by the exact source restore.

## Stable (`1.98.1`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,339 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,343 passed, 0 failed, 79 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.70 % lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench -p quervant-core --no-run` | PASS |
| `cargo build --workspace --release` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

PASS: fmt, all-feature Clippy, all-feature workspace tests (2,343 passed).

## Real RustFS (pinned image, local podman)

PASS: s3 8, proxy 5, remote 3, oracle 1, oracle_geo 1,
pr15g_a/b/c/d 1 each, m1 1, m2 1, m3 3/3, m5 3/3, remote_proxy 7,
crash k0 5, crash k05 **10/10**.

## Hosted CI

**`CI_PENDING`.** No push/PR/merge was performed; exact-final-HEAD hosted
`rust`/`msrv`/`rustfs` jobs remain the external gate.
