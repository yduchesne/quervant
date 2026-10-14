# PR 7 validation report

**Amendment 02 working tree:** branch `dev/lexical-postings` on base
`4f603ce1c0dafd994918bb5291d4b0584d9f001c`, starting commit
`161cf5ebce28c6425ae1b803384e876ac9254d78` (Amendment 01).
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs; stable Rust 1.98.1 and MSRV Rust
1.85.0; `cargo-llvm-cov 0.9.1`. Date of run: 2026-10-14.
**Amendment 02 changes:** `crates/quervant-core/src/search/execute.rs`,
`tests/pr07_amendment01.rs` (updated lifetime boundaries),
`tests/pr07_amendment02.rs` (new), `docs/pr-artifacts/pr-7/**`.

## Command results (post-amendment)

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable 1.98.1 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable 1.98.1 | PASS — **991 passed, 7 ignored, 0 failed** |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | PASS — **991 passed, 7 ignored, 0 failed** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | stable 1.98.1 | PASS — **91.97% line, 92.12% region** |
| `cargo doc --workspace --no-deps` | stable 1.98.1 | PASS |
| `cargo run --release -p quervant-core --example pr07_bench` | stable 1.98.1 | PASS (correctness-gated) |

Amendment 01 baseline on `161cf5e`: 980 passed / 7 ignored / 0 failed, 91.90%
line coverage. All prior PR 2–6 suites remain green.

## Amendment 01 regression-note

The Amendment 01 per-segment/byte boundary tests (`b01`–`b03`, `b07`) were
updated to the corrected (lower) peaks produced by the Amendment 02 lifetime
releases: `MatchAll` on a 4-doc segment peaks at 8 entries (was 12), and the
2-key/1-segment byte peak is 322 (was 418). This is the corrected semantics, not
weakened assertions: pre-Amendment-02 peaks are strictly higher due to implicit
bulk release and retained phrase scratch.

## Amendment 02 test matrix

- A2-02/A2-10 fail on `161cf5e` and pass after the fix (re-verified in a
  detached worktree at the starting commit): sequential phrase scratch release
  and per-segment peak reset / implicit bulk release.
- A2-01/A2-04/A2-05/A2-07 are private unit tests of atomic transfer, rejection
  atomicity, the combined segment/global bound and checked charge arithmetic.
  The A2-01 end-to-end boundary cannot distinguish before/after because
  segment-charge checks dominate; this is recorded in the preflight and review.
- A2-03/A2-08/A2-09/A2-10/A2-11/A2-12 are public-path tests: multi-segment batch
  boundaries, Boolean set algebra vs a std-set oracle, cancellation/work
  recovery, per-segment reset, memory/Fs agreement and a 200-case seeded
  membership oracle (`0xA202`).

## Integration topology

All integration tests use the real production path: `Index::create` /
`IndexWriter::{insert, flush, refresh, commit, pin}` -> `Index::open_existing` /
`ReaderSnapshot` -> `LexicalSearcher`. `MemoryDirectory` and `FsDirectory` are
exercised; no executor or postings fakes. Remote RustFS is out of scope (PR 13).

## Failure classification

None. No mandatory gate failed, and no test was ignored for this amendment.

## Notes

- `ResourceLimit` is a deterministic logical-accounting contract, not a claim
  that process OOM is prevented; `match_phrase` internal scratch vectors remain
  not individually byte-charged (bounded work, disclosed residual risk).
- Benchmarking is not release qualification; PR 15 owns the full harness.
