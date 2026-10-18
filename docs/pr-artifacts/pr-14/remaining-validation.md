# PR 14 — Remaining validation report

State: `dev/pagination`, base `551f7f9` + uncommitted edits. Stable `1.98.1`, MSRV `1.85.0`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --test pr14_unified_cursor` | PASS — 11 |
| `cargo test -p quervant-core --lib search::unified` | PASS — 3 |
| `cargo test -p quervant-core --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **90.86% lines** (regions 91.14%, functions 87.35%) |

## Not executed / blocked
- Batch meter B01–B12, compound aggregation A01–A12: not implemented.
- Real RustFS R01–R04: BLOCKED (no endpoint).
- Final-SHA CI Q01–Q06: NOT EXECUTED (no push).
- Benchmarks: NOT EXECUTED.
