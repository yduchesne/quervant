# PR 14 — P2B Phase B validation

Base HEAD `1041798` (Phase A committed) + uncommitted Phase B changes. Stable `1.98.1`, MSRV
`1.85.0`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test -p quervant-core --lib search::memory` | PASS — 10 (`b01`–`b10`) |
| `cargo test -p quervant-core --lib search::batch_meter` | PASS — 5 (Phase A) |
| `cargo test -p quervant-core --test pr14_batch` | PASS — 12 |
| `cargo test -p quervant-core --test pr14_batch_governance` | PASS — 6 |
| `cargo test -p quervant-core --test pr14_unified_cursor` | PASS — 11 |
| `cargo test --workspace --all-features` | PASS — 0 failed |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-features` | PASS — 0 failed |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — 90.88% lines (regions 91.16%, functions 87.35%) |

No failures observed this phase. Phase B acceptance: safe scoped memory lifecycle exists and is
tested; no candidate/projection accounting claim. **P2B remains NOT ACCEPTED.** Next: Phase C
(`CandidateBudget`, segment scratch, K+1 heap), then D–F.
