# PR 15H-C — QA and CI

## Final source

- Branch: `dev/pr15h-a-linear-term-candidates`
- Baseline A / final production source: `e8744d3fe16ee858c7d587aaf3b10d393059b809`
- Measured candidate: `fee4edba7600b405d417928a9da768d6315483b8`
- Safe rollback: `dd68fcbf4e6f33f214dd2cf9d0a5ed4811980909`
- `git diff --quiet e8744d3 HEAD -- crates/quervant-core/src/search/unified.rs` exit 0.
- Working tree clean; C tooling and evidence retained.

## C/B controller and Rust tests (final source)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15h_c -p 'test_*.py'` | PASS — 50 tests |
| `python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py'` | PASS — 33 tests |
| `cargo test -p quervant-core --lib search::unified::b_tests` | PASS — 6 |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | PASS — 6 |

At the candidate, `search::unified::c_tests` ran 6 tests (HC-U01–U18) and passed;
those C-only tests were removed by the exact source restore.

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
| `cargo bench --workspace --no-run` | PASS |
| `cargo build -p quervant-core --release` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,343 passed |

## Real RustFS (pinned image, local podman)

PASS: s3 8, proxy 5, remote 3, oracle 1, oracle_geo 1,
pr15g_a/b/c/d 1 each, m1 1, m2 1, m3 3/3, m5 3/3, remote_proxy 7,
crash k0 5, crash k05 **10/10**.

## Hosted CI

**`CI_PENDING`.** No push/PR/merge was performed; exact-final-HEAD hosted
`rust`/`msrv`/`rustfs` jobs remain the external gate.
