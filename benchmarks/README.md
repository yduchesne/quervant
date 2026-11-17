# Quervant benchmarks

Linux/WSL2 microbenchmark and profiling infrastructure for the standalone
`quervant-core` engine (PR 7 Amendment 04). See
[`docs/BENCHMARKING.md`](../docs/BENCHMARKING.md) for the repository-wide policy.

## Contract foundation (`v0.1-bench`)

`quervant_bench/` is the **contract-only** Python foundation for the interim
`v0.1-bench` milestone: strict versioned schemas, semantic identity and canonical
JSON, a read-only `inspect` command and a read-only legacy inventory. It does not
execute benchmarks, schedule anything or publish results.

```sh
PYTHONPATH=benchmarks python -m quervant_bench inspect \
    --experiment synthetic-contract-smoke --format json
```

**No new real timed benchmark acquisition is permitted in BM-01 through BM-08.**
`quervant-bench run` fails closed with `BM_ACQUISITION_PROHIBITED` (exit 77); the
first real full-scale campaign belongs to BM-09. Historical PR 15D/D3-C
controllers, protocols, verifiers and reports remain unchanged and authoritative
for their original studies. See
[`docs/pr-artifacts/bm-01/`](../docs/pr-artifacts/bm-01/README.md).

BM-03 adds a deterministic **synthetic** execution core
(`quervant_bench/protocol/`, `quervant_bench/execution/`): a generic
`balanced-cyclic-v1` / `explicit-v1` schedule compiler, a freeze-before-acquisition
binding, one synthetic `BenchmarkAdapter` implementation driven by an injected
logical clock and readiness provider, an exclusive append-only structural evidence
store and a read-only structural replayer. It is an importable library only — there
is no new CLI verb — and it never times a real query. `quervant-bench run` remains
blocked with `BM_ACQUISITION_PROHIBITED` (exit 77) until BM-09. See
[`docs/pr-artifacts/bm-03/`](../docs/pr-artifacts/bm-03/README.md).

BM-02 adds a reusable, read-only evidence layer (`quervant_bench/evidence/`,
`quervant_bench/host/`) for safe path/archive inspection, external trust anchors,
pinned provenance, synthetic admission receipts and crash-safe publication. It is
an importable library only, not a new CLI verb. See
[`docs/pr-artifacts/bm-02/`](../docs/pr-artifacts/bm-02/README.md).

BM-04 adds an internal, deterministic primary analysis and frozen-policy engine
(`quervant_bench/analysis/`) over BM-03's read-only, replay-verified **synthetic**
evidence: paired block statistics, symmetric whole-pair exclusions, a SHA-256
rejection bootstrap, direction-aware geometric means and an exact-boundary
eligibility/selection policy. It returns two canonical in-memory documents and is
an importable library only — no CLI verb, no file writes, no real timing and no
Gate A–E receipt. See
[`docs/pr-artifacts/bm-04/`](../docs/pr-artifacts/bm-04/README.md).

BM-05 adds an importable, read-only `quervant_bench/verification/` oracle that
reopens a sealed BM-03 synthetic run and independently reconstructs the paired
statistics, symmetric exclusions, SHA-256 paired-bootstrap intervals and frozen
policy decision before accepting a BM-04 analysis/policy pair. It returns one
in-memory `VerificationAssessment` and never writes, publishes, issues a receipt,
runs an adapter or adds a CLI verb. Local reference-vector, mutation,
independence and synthetic vertical-slice gates pass; remote CI is pending. See
[`docs/pr-artifacts/bm-05/`](../docs/pr-artifacts/bm-05/README.md).

BM-06 adds an importable `quervant_bench/qualification/` coordinator that binds a
sealed BM-03 synthetic run to the existing BM-04 derivation and BM-05 independent
verification, adds pinned framework/source QA evidence and BM-01 receipt-v1 gates,
and exclusively publishes one immutable 15-file A–E bundle whose `manifest.json` is
the completion marker. Reuse is allowed only after full fresh source/run/QA/edge
revalidation; BM-04/BM-05 are never re-run on a verified committed result. It does
not add a CLI verb, acquire real timing, authenticate CI or issue an official
qualification; the checked-in QA records are explicitly simulated L2 assertions.
Local synthetic correctness gates pass; remote CI is pending. See
[`docs/pr-artifacts/bm-06/`](../docs/pr-artifacts/bm-06/README.md).

BM-07 adds the synthetic-only `synthetic-retained-key-reference` catalog and a
bounded offline read-only surface for the five reserved stage verbs. A previously
committed 15-file BM-06 bundle can be revalidated and displayed only when the
caller supplies a safe local workspace and an independent
`qualification-anchors.v1.json`; the CLI never acquires, derives, publishes or
relabels evidence. `inspect` keeps its original `outcome.v1` success contract and
`run` remains prohibited with exit 77. Historical D3-C/T7/T7-F2 sources stay
unchanged; the missing external archive is recorded as `EVIDENCE_UNAVAILABLE`
with numeric/decision parity `NOT_EXECUTED`. See
[`docs/pr-artifacts/bm-07/`](../docs/pr-artifacts/bm-07/README.md).

BM-08 adds the synthetic-only `synthetic-cross-engine-reference` catalog and the
same offline surface for it. `quervant`, `tantivy` and `lucene` are **declared
logical sample-stream labels** bound to the single BM-03 `synthetic-execution`
simulator: no Quervant, Tantivy or Lucene adapter is built, launched or queried,
and no duration is measured. A pure exact-keyword corpus oracle is recomputed from
the frozen PR15D formula, 48 untimed adapter reply **projections** are validated
against reviewed goldens, and the original adapter files are bound by raw-byte
SHA-256 only (never as binaries). Scored BM25, process-cold and
indexing-throughput classes are excluded in the semantic ledger. The five offline
verbs now read either family through one frozen two-entry literal map. Historical
numeric/decision parity remains `NOT_EXECUTED`/`BLOCKED`. See
[`docs/pr-artifacts/bm-08/`](../docs/pr-artifacts/bm-08/README.md).

```sh
# Declared synthetic contracts only (no engine is executed).
PYTHONPATH=benchmarks python -m quervant_bench inspect \
    --experiment synthetic-retained-key-reference --format json
PYTHONPATH=benchmarks python -m quervant_bench inspect \
    --experiment synthetic-cross-engine-reference --format json

# Read-only views over an operator-provisioned committed bundle.
export QUERVANT_BENCH_OFFLINE_WORKSPACE=/absolute/path/to/offline-workspace
quervant-bench validate --run <run-uuid> --offline
quervant-bench analyze  --run <run-uuid> --offline
quervant-bench verify   --run <run-uuid> --offline
quervant-bench accept   --run <run-uuid> --offline
quervant-bench report   --run <run-uuid> --offline
```

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
- `pr15e/` — PR 15E-A exact-workload `perf`/`heaptrack` profiling driver and
  fail-closed evidence verifier for the frozen PR 15D Quervant workload; see
  [`pr15e/README.md`](pr15e/README.md). Profiling evidence is never mixed with
  the uninstrumented PR 15D-B comparison.

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

## Official real-qualification facade (BM-09)

`quervant_bench/official/` is the **only** real-origin qualification path. It adds
a reviewed, independently pinned design template, a G0 run authorization, live host
readiness, real A/A controls, independent Gate C recomputation, a seven-gate
`receipt.v1` graph and exclusive immutable publication for the two required
families (`retained-key-topk-real-v1` and `cross-engine-keyword-real-v1`).

- The legacy measurement backends (`benchmarks/pr15d/harness/*`,
  `benchmarks/pr15i_d3_c/*`) are invoked **unchanged**; no timing loop is
  reimplemented and no real adapter is launched by any test.
- Design templates live in `benchmarks/official-protocols/`; an independent
  reviewer must approve their digests before any timed control.
- Synthetic (`synthetic`/`simulated`), historical (`real`/`historical_replay`) and
  official (`real`/`official`) evidence are mutually inassimilable: each domain's
  loaders reject the others, including after a coherent rehash.

**No real timed acquisition has been performed.** There is no independent G0
authorization, the historic T6 freeze receipt and the PR15D corpus/adapter
artefacts are not available on the local host, so both families are `BLOCKED` and
roadmap checkpoint C6 stays blocked. `quervant-bench run` still fails closed with
`BM_ACQUISITION_PROHIBITED`; real acquisition is only reachable through the explicit
G0-gated official orchestrator. Evidence and status:
[`docs/pr-artifacts/bm-09/`](../docs/pr-artifacts/bm-09/README.md).
