# PR 7 Amendment 04 review — Linux microbenchmarking, profiling and baselines

**Scope:** measurement infrastructure only. No production behavior changes.
**Branch:** `dev/lexical-postings`; starting commit `b7d9d5d` (Amendment 03);
implementation commit `dad2514`.
**Disposition:** amend the existing PR 7 branch; not a new roadmap PR.

## Files

- `crates/quervant-core/Cargo.toml` — `autobenches = false`; five explicit
  `[[bench]]` targets; dev-only `criterion = "=0.7.0"` (`default-features = false`,
  `cargo_bench_support`).
- `crates/quervant-core/benches/{common/mod,bm25,search,postings,phrase,dictionary}.rs`.
- `crates/quervant-core/examples/pr07_profile.rs` — benchmark-only profiling entrypoint.
- `crates/quervant-core/tests/pr07_amendment04.rs` — fixture/oracle/determinism tests.
- `benchmarks/{README.md,workloads/pr07_amendment04_v1.md,reports/…}` and
  `benchmarks/scripts/{capture-pr07-env,profile-pr07,run-pr07-baseline,test-scripts}.sh`,
  `benchmarks/scripts/validate-report.py`.
- `docs/BENCHMARKING.md` permanent Linux/WSL2 policy; PR 7 artifacts.

No production source (`search/*`, `segment/*`, `index/*`, `storage/*`) changed.

## Invariant → evidence

| ID | Evidence |
|---|---|
| I01 semantics unchanged | git diff touches only `Cargo.toml`/`Cargo.lock`/`benches`/`examples`/`tests`/docs; all existing suites pass |
| I02 correctness precedes timing | `assert_all_cases` in every fixture; A4-T01/T03–T06/T08; A4-T12 oracle-negative `should_panic` |
| I03 build outside `b.iter` | `common::build` and `assert_all_cases` run before `benchmark_group`; A4-T13 via `cargo test --bench` smoke |
| I04 controlled variables | `pr07_amendment04_v1.md`; A4-T02 digest sensitivity |
| I05 statistical honesty | `configure_group` warmup/measurement/sample-size; JSON manifest with CIs |
| I06 stable baseline | SHA-scoped untracked run dir; `capture-pr07-env.sh`; dataset digests; A4-T14; validator A4-T15 |
| I07 Linux-first profiling | `profile-pr07.sh` UNAVAILABLE exit 2; A4-T10/T11 |
| I08 relative comparison policy | `benchmarks/README.md`, `docs/BENCHMARKING.md`; no competitor run |
| I09 no production dependency | Criterion is `[dev-dependencies]` only; `cargo bench --no-run` on stable + 1.85 |
| I10 profiling fidelity | `pr07_profile` reuses the same fixture; profiler timings never mixed with Criterion |

## Test matrix

| ID | Result |
|---|---|
| A4-T01 deterministic digest/hits | PASS (`a4_t01`) |
| A4-T02 digest axis sensitivity | PASS (`a4_t02`) |
| A4-T03 selectivity counts (2K/10K/100K) | PASS (`a4_t03`) |
| A4-T04 phrase present/absent/repeated | PASS (`a4_t04`) |
| A4-T05 Boolean set oracle | PASS (`a4_t05`) |
| A4-T06 top-K truncation/ranking/stability | PASS (`a4_t06`) |
| A4-T07 deletions | PASS for 0%; 25% **NOT APPLICABLE** (insert-only; PR 9) |
| A4-T08 single- vs four-segment equivalence | PASS (`a4_t08`) |
| A4-T09 stable + MSRV bench compile | PASS (`cargo bench --no-run`, both toolchains) |
| A4-T10 missing/blocked profilers | PASS (`test-scripts.sh`: perf/heaptrack UNAVAILABLE exit 2; fake perf captures a report) |
| A4-T11 invalid mode/workload/output | PASS (`test-scripts.sh`: exit 64) |
| A4-T12 corrupted oracle aborts | PASS (`a4_t12` `#[should_panic]`) |
| A4-T13 setup outside timing | PASS (source structure + `cargo test --bench` smoke "Success") |
| A4-T14 provenance runs preserved | PASS (`test-scripts.sh`) |
| A4-T15 manifest schema validator | PASS (valid accepted; missing digest / false correctness / negative latency / dirty rejected) |
| A4-T16 ratio gating | Policy only (no competitor adapters in Amendment 04); documented |
| A4-T17 existing suites green | PASS (1020 passed, 7 ignored, 0 failed) |
| A4-T18 profile produces samples or BLOCKED | **BLOCKED/UNAVAILABLE** — no profiler installed; diagnostics retained |

## Gates

| Command | stable 1.98.1 | MSRV 1.85.0 |
|---|---|---|
| `cargo fmt --all -- --check` | PASS | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS | PASS |
| `cargo test --workspace --all-targets` | PASS — 1020 passed, 7 ignored, 0 failed | PASS — 1020 passed, 7 ignored, 0 failed |
| `cargo doc --workspace --no-deps` | PASS | PASS |
| `cargo bench -p quervant-core --no-run` | PASS | PASS |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | PASS — 92.05% line | n/a |
| `cargo run --release --example pr07_bench` | PASS (existing oracle benchmark) | — |
| `bash benchmarks/scripts/run-pr07-baseline.sh` | PASS on clean `dad2514` | — |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 13/13 | — |

## Baseline

See `benchmarks/reports/pr07-amendment04-baseline.md` and
`benchmarks/reports/pr07-amendment04-baseline.json` (validated). Mandatory
2K/10K/100K rare/common whole-search latencies measured; postings/dictionary/
phrase/bm25 measured; 1M extended lane not run; 25% tombstone lane NOT APPLICABLE.

## Residual risks / limitations

1. Profilers unavailable on this WSL2 host; `compute_stats` attribution is a
   data-supported hypothesis (isolation of `MatchAll`, selectivity insensitivity),
   not a symbol-level CPU profile.
2. Absolute latencies are host-specific; no cross-environment extrapolation.
3. No allocation counts (`heaptrack` unavailable).
4. No competitor adapters or ratios (PR 15).
5. `dictionary_lookup` present-term timings reflect a term ordered near the start
   of the sorted dictionary; the absent term measures the full sequential scan.
6. 1M extended lane is optional and unmeasured.
