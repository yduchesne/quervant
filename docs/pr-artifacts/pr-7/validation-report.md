# PR 7 validation report

**Amendment 03 working tree:** branch `dev/lexical-postings` on base
`4f603ce1c0dafd994918bb5291d4b0584d9f001c`, starting commit
`66b512bd737af5dfb25cbf258be22c999a3eb76c` (Amendment 02).
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs; stable Rust 1.98.1 and MSRV Rust
1.85.0; `cargo-llvm-cov 0.9.1`. Date of run: 2026-10-14.
**Amendment 03 changes:** `crates/quervant-core/src/search/{execute,phrase}.rs`,
`tests/pr07_amendment02.rs` (updated sibling boundary),
`tests/pr07_amendment03.rs` (new), `docs/pr-artifacts/pr-7/**`.

## Command results (post-amendment)

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable 1.98.1 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable 1.98.1 | PASS — **1012 passed, 7 ignored, 0 failed** |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | PASS — **1012 passed, 7 ignored, 0 failed** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | stable 1.98.1 | PASS — **92.04% line, 92.24% region** |
| `cargo doc --workspace --no-deps` | stable 1.98.1 | PASS |
| `cargo +1.85.0 doc --workspace --no-deps` | 1.85.0 | PASS |
| `cargo run --release -p quervant-core --example pr07_bench` | stable 1.98.1 | PASS (correctness-gated) |

Amendment 02 baseline on `66b512b`: 991 passed / 7 ignored / 0 failed, 91.97%
line coverage. All prior PR 2–6 suites remain green.

## Amendment 03 test matrix

- Transactional T01–T08 in `search/execute.rs::budget_tests`; T01–T04 (and
  T07/T08) were demonstrated failing on `66b512b` before the fix.
- Phrase scratch `p01` (`tests/pr07_amendment03.rs`) fails on `66b512b` in a
  detached worktree and passes after; P02–P12 are guards/new-contract tests.
- `phrase::tests::phrase_scratch_returns_to_zero` asserts zero residual scratch
  after success, no-match and empty-token phrases.
- `pr07_amendment02::a2_02` was updated to compare single vs sibling phrase-leaf
  minimum entry bounds (the previously hard-coded constants predated the new
  internal scratch charges).

## Integration topology

All integration tests use the real production path: `Index::create` /
`IndexWriter::{insert, flush, refresh, commit, pin}` -> `Index::open_existing` /
`ReaderSnapshot` -> `LexicalSearcher`. `MemoryDirectory` and `FsDirectory` are
exercised; no executor or postings fakes. Remote RustFS is out of scope (PR 13).

## Failure classification

None. No mandatory gate failed, and no test was ignored for this amendment.

## Notes

- `ResourceLimit` is a deterministic **logical**-accounting contract, not a claim
  that process OOM is prevented; `match_phrase` scratch is now bounded and
  charged, but the units remain logical rather than allocator-exact RSS.
- Field-length recomputation remains O(indexed postings).
- Benchmarking is not release qualification; PR 15 owns the full harness.

