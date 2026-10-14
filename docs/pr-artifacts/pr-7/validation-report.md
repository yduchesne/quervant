# PR 7 validation report

**Amendment 04 working tree:** branch `dev/lexical-postings` on base
`4f603ce1c0dafd994918bb5291d4b0584d9f001c`, starting commit
`b7d9d5d6d5e57848149937c22472573ae8c7c5d4` (Amendment 03); implementation
commit `dad2514e16698b7a65bb607c10b97a868e7e94e8`.
**Environment:** Linux 6.18.33.2-microsoft-standard-WSL2 x86_64, Intel(R)
Core(TM) i7-10750H @ 2.60GHz, 12 logical CPUs, ext4; stable Rust 1.98.1 and MSRV
Rust 1.85.0; `cargo-llvm-cov 0.9.1`; Criterion 0.7.0 (dev-only). Date: 2026-10-14.
**Amendment 04 changes:** dev-only benchmark targets/fixtures, profiling
entrypoint and scripts, benchmark docs and PR artifacts; no production source.

## Command results (post-amendment)

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable 1.98.1 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable 1.98.1 | PASS — **1020 passed, 7 ignored, 0 failed** |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | PASS — **1020 passed, 7 ignored, 0 failed** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | stable 1.98.1 | PASS — **92.05% line, 92.25% region** |
| `cargo doc --workspace --no-deps` | stable 1.98.1 | PASS |
| `cargo +1.85.0 doc --workspace --no-deps` | 1.85.0 | PASS |
| `cargo bench -p quervant-core --no-run` | stable 1.98.1 + 1.85.0 | PASS (five targets compile) |
| `cargo run --release -p quervant-core --example pr07_bench` | stable 1.98.1 | PASS (existing oracle benchmark) |
| `bash benchmarks/scripts/run-pr07-baseline.sh` | stable 1.98.1 | PASS on clean `dad2514` |
| `bash benchmarks/scripts/test-scripts.sh` | bash + python3 | PASS — 13/13 |
| `bash benchmarks/scripts/profile-pr07.sh --mode perf …` | stable 1.98.1 | BLOCKED/UNAVAILABLE (no `perf`) |
| `bash benchmarks/scripts/profile-pr07.sh --mode heaptrack …` | stable 1.98.1 | BLOCKED/UNAVAILABLE (no `heaptrack`) |

Amendment 03 baseline on `b7d9d5d`: 1012 passed / 7 ignored / 0 failed, 92.04%
line coverage. All prior PR 2–6 suites remain green.

## Amendment 04 baseline

Clean-tree run `20261014T011531Z-dad2514`, correctness gate 9/9 PASS. Whole-search
median latencies (4 segments, warm, top-K 10): `term-rare` 7.58 ms / 34.96 ms /
327.49 ms and `term-common` 8.04 ms / 49.58 ms / 393.70 ms at 2K/10K/100K;
`match-all` 5.31 ms and `pure-negative` 5.35 ms at 2K; postings decode `ctoken`
148.7 µs / 716.2 µs / 7.35 ms; dictionary present ~6.6 ns, absent ~181–187 ns.
Full CIs and the machine-readable manifest are in
`benchmarks/reports/pr07-amendment04-baseline.{md,json}` (validator PASS). The
near-selectivity-insensitivity and the 2K `MatchAll` gap support the
`compute_stats`-dominates hypothesis; CPU symbols were not captured because
`perf`/flamegraph/heaptrack are unavailable (**BLOCKED**, not PASS). The 1M
extended lane and the 25% tombstone lane were not run (the latter is NOT
APPLICABLE for insert-only PR 7).

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

## Amendment 04 Correction 01

| Command | Result |
|---|---|
| `cargo test -p quervant-core --test pr07_amendment04` | PASS — 11 tests |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 30 checks |
| Real-artifact builder + v2 validator smoke test | PASS — 34 rows joined from `target/criterion` |
| `python3 validate-report.py --historical …baseline.json` | PASS (historical/unqualified only) |
| `bash benchmarks/scripts/run-pr07-baseline.sh --idle-confirmed` | **BLOCKED (exit 3)** — contention `suspected` (`java`, ≥0.5 core) before Criterion |
| `profile-pr07.sh --mode perf|heaptrack` | **UNAVAILABLE** |

Historical Amendment 04 timings are preserved unchanged and clearly marked
`historical_unqualified`; `actual_hits` placeholders are non-authoritative. The
qualified baseline is **not published** because no three-trial contention-free,
clean-tree run was obtainable; no fabricated artifact was produced. See
`amendment-04-correction-01-review.md` for the exact evidence and residual risks.

