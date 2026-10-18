# PR 14 — F1 hardening validation

State: `dev/pagination`, base `69d47ba` + uncommitted H1 edits. Environment: stable `1.98.1`,
MSRV `1.85.0`, Linux x86_64.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.28% lines** (regions 91.60%, functions 87.44%) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |

New tests: `pr14_f1_hardening` 16 (W04/W06 added), plus `search::work` unit tests.
No introduced regressions; no exclusions added.

## Not executed / blocked
- Real RustFS integration: **BLOCKED** (no `QUERVANT_RUSTFS_*` endpoint provisioned).
- Final-SHA GitHub Actions: **NOT EXECUTED** (no push).
