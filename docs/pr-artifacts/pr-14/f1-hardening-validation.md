# PR 14 — F1 hardening validation (verification pass)

State: `dev/pagination`, base `69d47ba` + uncommitted H1 verification edits. Environment: stable
`1.98.1`, MSRV `1.85.0`, Linux x86_64.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.33% lines** (regions 91.65%, functions 87.49%) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |

## Targeted verification runs
| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib search::work` | PASS — 7 tests |
| `cargo test -p quervant-core --lib search::execute::budget_tests` | PASS — 22 tests |
| `cargo test -p quervant-core --lib search::typed::tests` | PASS — 4 tests |
| `cargo test -p quervant-core --test pr07_amendment01 --test pr07_amendment02 --test pr07_amendment03 --test pr10_aggregate_memory --test pr10_cursor` | PASS — 20/6/12/7/4 |
| `cargo test -p quervant-core --test pr14_f1_hardening` | PASS — 23 tests |
| `cargo test -p quervant-core --test pr14_unified_mixed --test pr14_projection --test pr14_batch` | PASS — 14/10/12 |

New tests added in this verification pass: exact-limit/one-over for aggregate, typed and scanned
limits; shared-adapter charge/cancellation forwarding; candidate global-bytes exact/one-over;
M01, M04, M05, M06, G04, G05; `w04b` phrase metering.

## Not executed / blocked
- Real RustFS integration: **BLOCKED** (no `QUERVANT_RUSTFS_*` endpoint).
- Final-SHA GitHub Actions: **NOT EXECUTED** (no push).
