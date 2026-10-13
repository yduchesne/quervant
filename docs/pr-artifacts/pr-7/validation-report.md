# PR 7 validation report

**Tested working tree:** branch `dev/lexical-postings` on base `4f603ce1c0dafd994918bb5291d4b0584d9f001c`.
**Changes:** `crates/quervant-core/src/search/**` (new), `src/lib.rs`,
`src/segment/{reader,postings}.rs`, `tests/common/mod.rs`,
`tests/pr07_{unit,integration,faults,properties}.rs` (new), `docs/**`.

## Command results

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable 1.98.1 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable 1.98.1 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable 1.98.1 | PASS — 948 passed, 7 ignored, 0 failed |
| `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | PASS — all suites green |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable 1.98.1 | PASS — 91.73% line coverage, 92.05% region coverage |
| `cargo doc --workspace --no-deps` | stable 1.98.1 | PASS |
| `cargo +1.85.0 doc --workspace --no-deps` | 1.85.0 | PASS |

Coverage was measured with `cargo-llvm-cov 0.9.1` over the whole workspace
(all production crates, all targets). No exclusions were applied.

New `search/*` module line coverage from the same run: `limits.rs` 95.3%,
`phrase.rs` 97.4%, `topk.rs` 96.6%, `execute.rs` 88.9%, `score.rs` 81.4%,
`plan.rs` 81.4%, `error.rs` 76.2%, `mod.rs` 71.7%. The workspace line gate
(85%) is satisfied; `search/mod.rs` is thin wrapper/accessor code, and
`error.rs`/`plan.rs` untested arms are defensive display/unsupported-operator
paths exercised by the variant sweep.

## PR 7 acceptance tests

- Unit U01–U19: `tests/pr07_unit.rs` (18 tests).
- Integration I01–I10 plus cancellation and empty-index/no-op commit: `tests/pr07_integration.rs` (12 tests).
- Faults F01–F12: `tests/pr07_faults.rs` (10 tests). F03 exercises real corrupted
  immutable segment bytes through `SegmentReader`; F05 (duplicate committed keys)
  is covered by PR 6 committed-state duplicate rejection and the search-layer
  defensive `CorruptIndex` path rather than an end-to-end constructed state.
- Properties P01–P05 (200 seeds for P01/P02/P03, 60 for P05; P04 seeded):
  `tests/pr07_properties.rs` plus `search/topk.rs` unit test.

## Integration topology

All integration tests use the real production path: `Index::create` /
`IndexWriter::{insert, flush, refresh, commit, pin}` -> `Index::open_existing` /
`ReaderSnapshot` -> `LexicalSearcher`. `MemoryDirectory` and `FsDirectory`
(including a real reopen across the same filesystem) are exercised. No postings
fakes are used. The remote ObjectStore path is out of scope (PR 13).

## Failures / blockers

None. No mandatory gate is unexecuted; no exception was required.

## Microbenchmark example

The correctness-gated, dependency-free example
`cargo run --release -p quervant-core --example pr07_bench` builds a synthetic
2,000-document / 4-segment corpus through the real writer/reader path, verifies
every query against a naive oracle, and reports latency/throughput and a
concrete-vs-enum-vs-`dyn` postings-cursor comparison. Representative numbers and
their interpretation are in
[adversarial-review.md](adversarial-review.md). This is a PR 7 baseline, not
release qualification; PR 15 owns the full comparative harness.

## Notes

- F05 duplicate-key corruption and the non-finite-score `InvalidScore` path are
  asserted at unit boundaries and by construction, not by a full end-to-end
  corrupted committed generation (which PR 6 verification rejects earlier).
- Benchmarking is not claimed as release qualification; it remains owned by PR 15.
