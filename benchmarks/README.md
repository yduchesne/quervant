# Quervant benchmarks

Linux/WSL2 microbenchmark and profiling infrastructure for the standalone
`quervant-core` engine (PR 7 Amendment 04). See
[`docs/BENCHMARKING.md`](../docs/BENCHMARKING.md) for the repository-wide policy.

## What lives here

- `crates/quervant-core/benches/` — Criterion targets: `bm25` (reference-arithmetic
  control), `search` (whole-search, including the per-search statistics scan),
  `postings`, `phrase`, `dictionary`. Shared deterministic fixtures, the
  independent oracle and the dataset digest live in `benches/common/mod.rs`.
- `scripts/capture-pr07-env.sh` — provenance/feature metadata.
- `scripts/profile-pr07.sh` — `perf`, `cargo flamegraph` and `heaptrack` wrappers.
- `scripts/run-pr07-baseline.sh` — correctness gate then sequential Criterion run.
- `workloads/pr07_amendment04_v1.md` — the versioned workload contract.
- `reports/` — concise, checked-in baseline manifests (raw Criterion output stays
  in `target/` and is **not** committed).

## Requirements

- Linux or WSL2, ideally on a native Linux filesystem (not `/mnt/c` or `drvfs`).
- Rust stable (1.98.1 measured) and the MSRV toolchain (1.85.0) for compile gates.
- `criterion` 0.7.0 is pinned in `Cargo.lock` and builds on Rust 1.85.
- Optional profiling: `perf` (Linux tools / `linux-tools-generic`), `cargo install
  flamegraph`, `heaptrack`. If they are missing the profile script exits nonzero
  with `UNAVAILABLE`; it never fabricates a report and never escalates privileges.

## Running

```sh
# Correctness gate + all five Criterion targets, raw logs under target/pr07-baseline/.
bash benchmarks/scripts/run-pr07-baseline.sh

# Compile-only check of the benchmark targets.
cargo bench -p quervant-core --no-run

# A single target.
cargo bench -p quervant-core --bench search

# Profiling (requires the tool to be installed).
bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-100k --out target/pr07-profiles/perf
bash benchmarks/scripts/profile-pr07.sh --mode heaptrack --workload rare-100k --out target/pr07-profiles/heaptrack
```

Profiling-instrumented runs are **never** mixed with uninstrumented Criterion
numbers. `cargo bench --no-run` proves compilation only, not measurement.

## Interpretation policy

- Same machine, same WSL2/Linux environment, same filesystem, same workload, same
  cache regime and correctness gate for any comparison.
- Cross-engine conclusions are **ratios** computed on matching query IDs; raw
  absolute latencies are retained as the underlying evidence. No competitive claim
  is made from Quervant-only runs.
- Criterion iteration statistics are not production p99 latency.
- Do not treat sub-1% differences on a noisy WSL2 host as significant; report
  effect size and variability.
