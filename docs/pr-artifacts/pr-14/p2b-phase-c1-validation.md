# PR 14 — P2B Phase C1 validation

Base HEAD `09af350` + uncommitted C1 changes. Stable `1.98.1`, MSRV `1.85.0`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --lib search::execute` | PASS — 27 (includes 5 C1 tests) |
| `cargo test -p quervant-core --test pr14_batch` | PASS — 12 |
| `cargo test -p quervant-core --test pr14_batch_governance` | PASS — 6 |
| `cargo test -p quervant-core --test pr14_unified_cursor` | PASS — 11 |
| `cargo test -p quervant-core --test pr14_f1_hardening` | PASS — 23 |
| `cargo test --workspace --all-features` | PASS — 0 failed |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-features` | PASS — 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — 90.91% lines (regions 91.19%, functions 87.42%) |

## Failure classification
One C1 test initially failed due to an incorrect fixture (segment entry ceiling not reached);
the test was corrected (reserve 100 entries at a 100-entry limit). Two clippy findings
(`dead_code` for C2-staged prisms, `unused_mut` in a test) were fixed. No unresolved failures.

## Checkpoint acceptance
Local transactional primitives exist and are tested; standalone lexical behavior is unchanged;
no batch/segment/heap integration was added. **Phase C is NOT complete**; C2 (segment ledger
ephemeral sink) and C3 (K+1 heap binding) remain. **P2B NOT ACCEPTED; PR 14 NOT READY.**
