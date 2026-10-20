# PR 14 — Corrective validation report

Tested state: `dev/pagination`, base `main` @ `7ca1b2e`, corrective edits on top of `e0e1dcb`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.22% lines** (regions 91.61%, functions 87.50%) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compiles) |
| `cargo test --workspace` (default features) | PASS (previous pass) |
| New real-RustFS PR14 targets | NOT EXECUTED — BLOCKED (no `QUERVANT_RUSTFS_*`) |
| PR13 real-RustFS regressions | NOT EXECUTED — BLOCKED |
| Final-SHA GitHub Actions | NOT EXECUTED |

New/updated test counts: `pr14_batch` 11, plus the `project_hit`/`to_query_error` unit tests.
All prior PR14 suites remain green.

## Regression classification
- No introduced regressions.

## Coverage of changed modules (from `cargo llvm-cov report`)
`search/batch.rs`, `contract/batch.rs`, and `contract/error.rs` are covered by the new unit and
integration tests; the aggregate workspace line floor is satisfied without exclusions.
