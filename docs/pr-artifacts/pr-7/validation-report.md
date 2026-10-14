# PR 7 validation report

**Amendment 01 working tree:** branch `dev/lexical-postings` on base
`4f603ce1c0dafd994918bb5291d4b0584d9f001c`, starting commit
`0568cce6f3505ba94158af990e4b834772d25e21`.
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs; stable Rust 1.98.1 and MSRV Rust
1.85.0; `cargo-llvm-cov 0.9.1`. Date of run: 2026-10-14.
**Amendment changes:** `crates/quervant-core/src/search/{mod,plan,execute,score,topk}.rs`,
`tests/pr07_amendment01.rs` (new), `docs/pr-artifacts/pr-7/**`.

## Command results (post-amendment)

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable 1.98.1 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable 1.98.1 | PASS — **980 passed, 7 ignored, 0 failed** |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | PASS — **980 passed, 7 ignored, 0 failed** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | stable 1.98.1 | PASS — **91.90% line, 92.07% region** |
| `cargo doc --workspace --no-deps` | stable 1.98.1 | PASS |
| `cargo run --release -p quervant-core --example pr07_bench` | stable 1.98.1 | PASS (correctness-gated) |

Pre-amendment baseline on `0568cce` (re-executed, not inferred): 948 passed /
7 ignored / 0 failed, 91.73% line coverage. All prior PR 2–6 suites remain green.

## Amendment test matrix

- Scoring polarity S01–S07 (including the 200-case seeded parity oracle at
  `0xA107`): `tests/pr07_amendment01.rs`.
- Resource accounting B01–B11 and F01/F03: `tests/pr07_amendment01.rs` plus
  `search/execute.rs::budget_tests` and `search/topk.rs::tests::{h01,h02}`.
- Field-length occupancy L01–L03: `tests/pr07_amendment01.rs` plus
  `search/score.rs::tests::l03_*`.
- Regression R01–R07: the original U01–U19 / I01–I10 / F01–F12 / P01–P05 suites
  still pass unchanged, and `pr07_bench` still validates every query against its
  naive oracle.

## Integration topology

All integration tests use the real production path: `Index::create` /
`IndexWriter::{insert, flush, refresh, commit, pin}` -> `Index::open_existing` /
`ReaderSnapshot` -> `LexicalSearcher`. `MemoryDirectory` and `FsDirectory`
(including real filesystem reopen) are exercised; no postings fakes. Remote
RustFS is out of scope (PR 13).

## Failure classification

None. No mandatory gate failed, no test was ignored for this amendment, and no
environment/harness limitation required an exception. F01 (corrupt segment) is
covered at the codec level by `pr07_faults::f03` because PR 6 verification
rejects a corrupted committed generation before search; the search-layer typed
propgation is asserted there.

## Notes

- `search/execute.rs` coverage is 88%+; the budget primitive tests directly
  exercise the reserve/release/overflow/cleanup contracts.
- `ResourceLimit` is a deterministic logical-accounting contract, not a claim
  that process OOM is prevented; see the residual risks in
  [adversarial-review.md](adversarial-review.md).
- Benchmarking is not release qualification; PR 15 owns the full harness.
