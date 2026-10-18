# PR 14 — F1 hardening validation

Tested state: `dev/pagination`, HEAD `83e1dcf` + uncommitted hardening edits. Environment:
stable `1.98.1`, MSRV `1.85.0`, Linux x86_64.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo +1.85.0 test --workspace --all-features --no-fail-fast` | PASS, 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.25% lines** (regions 91.59%, functions 87.40%) |
| `cargo doc --workspace --no-deps` | PASS (unchanged modules) |
| `cargo bench --workspace --no-run` | PASS (unchanged) |

New tests: `pr14_f1_hardening` 14. Existing `pr14_unified_mixed` 14, `pr14_projection` 10,
`pr14_batch` 12 all green. No introduced regressions; no exclusions added.

## Failure classification
- One transient local fix during implementation (clippy `unnecessary_lazy_evaluations`); not a
  test failure.
- No pre-existing failures observed.

## Not executed / blocked
- W01–W06 work-meter tests: blocked by STOP H1 (shared meter not implemented).
- Real RustFS / final-SHA CI: **BLOCKED** (no provider; no push). This F1 slice adds no
  storage/remote behavior.
