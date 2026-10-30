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

## Qualification (Correction 01)

A run that completes is not automatically a comparison baseline. The corrected
runner distinguishes four questions:

1. **Correctness** — the independent oracle passed before timing.
2. **Measurement completion** — all five Criterion targets produced estimates.
3. **Environment qualification** — contention checks were `clear`, the tree was
   clean, and the operator attested with `--idle-confirmed` that competing
   benchmark workloads (for example MTMF) are stopped.
4. **Publication eligibility** — at least three independently qualified trials
   were aggregated.

```sh
# Always use live /proc in production; --snapshot-* is test-only.
python3 benchmarks/scripts/check-pr07-contention.py --out target/contention.json

# Correctness gate, per-target contention checks, isolated Criterion output,
# automated v2 report assembly and validation. Fails closed on contention.
bash benchmarks/scripts/run-pr07-baseline.sh --idle-confirmed

# Three-trial qualified aggregate (only when every trial is qualified).
bash benchmarks/scripts/run-pr07-baseline.sh --idle-confirmed --trials 3

# Manual validation.
python3 benchmarks/scripts/validate-report.py --fixture-metadata <meta.json> <report-v2.json>
python3 benchmarks/scripts/validate-report.py --historical benchmarks/reports/pr07-amendment04-baseline.json
```

`--allow-contended` permits a diagnostic run but never marks it qualified. The
detector cannot see Windows-host processes or other WSL guests; `clear` is not a
proof of physical isolation. No external processes are terminated and no
privileges are escalated.

## PR 15B unified-search diagnostics

PR 15B adds one release Criterion target, `unified_diagnostics`, over the frozen
`pr15b_v1` scaling extension of the canonical PR15A row table. The canonical
fixture and its digest remain the semantic oracle; the generated 2K/10K/100K
corpora are synthetic performance extensions.

- `crates/quervant-core/benches/unified_diagnostics.rs` — U01–U13 whole-query
  lanes (selectivity, typed/JSON/IP/time, sort, projection, aggregation,
  serial batch, segment fan-out, pinned pages, separate geo provenance).
- `crates/quervant-core/benches/unified_diag_common/mod.rs` — deterministic
  generator, independent arithmetic oracle and fixture metadata emitter.
- `crates/quervant-core/tests/pr15b_diagnostics.rs` — B-T01–B-T16 positive and
  adversarial oracle/validator tests.
- `crates/quervant-core/examples/pr15b_profile.rs` — release profiling driver
  using the same fixture and request constructors.
- `scripts/run-pr15b.sh` — clean/idle/contention-gated three-trial runner.
- `scripts/profile-pr15b.sh` — `perf`, `cargo flamegraph` and `heaptrack`
  wrapper with nonzero `UNAVAILABLE` behaviour.
- `scripts/validate-pr15b.py` — strict trial validator, negative self-tests and
  source-identical aggregate.
- `workloads/pr15b_v1.md` — frozen lane matrix and exclusions.

```sh
# Compile only (routine CI).
cargo bench -p quervant-core --bench unified_diagnostics --no-run

# One diagnostic run (not a published baseline).
bash benchmarks/scripts/run-pr15b.sh --allow-contended --trials 1

# Three qualified source-locked trials (clean tree + operator idle attestation).
bash benchmarks/scripts/run-pr15b.sh --idle-confirmed --trials 3

# Strict validator self-tests.
python3 benchmarks/scripts/validate-pr15b.py self-test
```

The 1M corpus and 64-segment stress topology are opt-in only
(`QUERVANT_PR15B_LARGE=1`, `QUERVANT_PR15B_SEG64=1`) and never run in routine CI.

## PR 15D cross-engine comparative qualification

PR 15D adds a standalone, local-only comparative harness under
`benchmarks/pr15d/`. It is **not** a production optimization and it asserts no
competitive threshold. The mandatory lane is exact, unanalyzed `Keyword`
membership with `doc_id` ascending ordering, an independent TSV oracle and
explicit `process_cold`/`warm` labels. A BM25 scored lane is
`SEMANTICALLY_NONCOMPARABLE` and contributes zero ratios.

```sh
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/test_pr15d.py
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/<unique-id>
python3 benchmarks/pr15d/harness/validate.py --run target/pr15d/runs/<unique-id> \
  --out target/pr15d/runs/<unique-id>/validation.json
python3 benchmarks/pr15d/harness/aggregate.py --run target/pr15d/runs/<unique-id> \
  --out benchmarks/reports/pr15d/pr15d-qualified.json \
  --md docs/pr-artifacts/pr-15d/qualification.md
```

The real three-engine series is currently **BLOCKED**: the prescribed Tantivy
pin `=0.22.0` is yanked (X15) and the host has no JDK 21/Gradle 8.14.3 (X14).
Static S1–S4 work, the Quervant adapter and the deterministic T01–T22 suite are
complete; see `docs/pr-artifacts/pr-15d/` and `benchmarks/pr15d/README.md`.
