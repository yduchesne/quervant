# PR 7 Amendment 04 preflight — Linux microbenchmarking, profiling and baselines

**Branch:** `dev/lexical-postings`
**Inspected/starting commit:** `b7d9d5d6d5e57848149937c22472573ae8c7c5d4` (Amendment 03)
**Base `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (unchanged)
**Working tree at preflight:** clean.

The branch HEAD matches the plan's inspected `b7d9d5d`. No material drift; no STOP
condition triggered. This amendment adds only dev-only benchmark/doc/lockfile
changes and does **not** touch production search, segment, writer, reader or
storage behavior.

## Environment

| Item | Value |
|---|---|
| OS | Linux 6.18.33.2-microsoft-standard-WSL2 x86_64 |
| CPU | Intel(R) Core(TM) i7-10750H @ 2.60GHz (12 logical CPUs) |
| Filesystem | `ext4` (native Linux filesystem, not `/mnt/c`/drvfs) |
| Rust stable | 1.98.1 |
| Rust MSRV | 1.85.0 |
| Criterion | `=0.7.0` (builds on Rust 1.85; `cargo +1.85.0 bench --no-run` verified) |
| `perf` | UNAVAILABLE |
| `cargo-flamegraph` | UNAVAILABLE |
| `heaptrack` | UNAVAILABLE |
| `hyperfine` | UNAVAILABLE |
| `python3` | available (schema validator) |

Criterion 0.8.2 declares `rust-version = 1.86` (too new for MSRV 1.85); 0.7.0 and
0.6.0 declare 1.80. 0.7.0 was selected as the newest release that demonstrably
builds on 1.85 (`cargo +1.85.0 bench -p quervant-core --no-run` succeeded).
`default-features = false, features = ["cargo_bench_support"]` avoids the
plotting stack while keeping the `cargo bench` harness.

## Baseline gates on `b7d9d5d` (re-executed)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | 1012 passed, 7 ignored, 0 failed |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | 92.04% line |

## Inspected interfaces

- `crates/quervant-core/examples/pr07_bench.rs` — existing oracle-gated 2K query
  example; preserved unchanged.
- `crates/quervant-core/src/search/score.rs` — crate-private `bm25` and
  `compute_stats`; `compute_stats` scans all dictionary entries/postings for
  scoring fields every search. **Not** exposed; attributed only via CPU samples and
  the whole-search scaling curve.
- Public seams used by the benchmarks: `Index::{create_with_limits, open_existing}`,
  `IndexWriter::{insert, flush, commit}`, `ReaderSnapshot::open_segment_reader`,
  `SegmentReader::{schema, dictionary, postings, live_docs}`, `LexicalSearcher`.
- No `[[bench]]` targets or Criterion dependency existed before this amendment.

## Invariant → test mapping

| Invariant | Tests / evidence |
|---|---|
| I01 semantics unchanged | git diff; `pr07_amendment04` + existing suites |
| I02 oracle precedes timing | `assert_all_cases`; A4-T01/T03–T06/T08 |
| I03 build outside `b.iter` | `common::build` before groups; A4-T13 (`cargo test --bench` smoke) |
| I04 controlled variables | `workloads/pr07_amendment04_v1.md`; A4-T02 |
| I05 statistical honesty | `configure_group` warmup/measurement/samples; report schema |
| I06 stable baseline | `dataset_sha256`, `capture-pr07-env.sh`, SHA-scoped untracked run dir |
| I07 Linux-first profiling | `profile-pr07.sh` UNAVAILABLE paths; A4-T10/T11 |
| I08 relative comparison policy | `benchmarks/README.md`, `docs/BENCHMARKING.md` |
| I09 no production dependency | Criterion is `[dev-dependencies]` only; `benches/`/`examples/` are dev targets |
| I10 profiling fidelity | `examples/pr07_profile.rs` reuses the same fixture; profiler timings never mixed |

## Scope reconciliation / STOP checks

- No occurrence changes; public APIs unchanged.
- No production visibility seam added for `bm25`/`compute_stats`; `bm25.rs` is an
  explicitly labeled reference-arithmetic control.
- Real postings/dictionary/phrase paths are used; no synthetic stand-in.
- 1M extended lane is optional and not run by default.
- 25% tombstone lane is NOT APPLICABLE for insert-only PR 7 (documented in the
  workload spec and A4-T07); it requires PR 9 mutation support.
- `perf`/`flamegraph`/`heaptrack` are unavailable; profiling is classified
  BLOCKED/UNAVAILABLE, not PASS, and the Criterion baseline still runs.
