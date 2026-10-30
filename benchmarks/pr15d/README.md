# PR 15D comparative qualification assets

**Status: A1 dependency/toolchain correction applied; real three-engine
performance qualification remains BLOCKED-ATTESTATION.**
See [`docs/pr-artifacts/pr-15d/preflight.md`](../../docs/pr-artifacts/pr-15d/preflight.md),
[`a1-preflight.md`](../../docs/pr-artifacts/pr-15d/a1-preflight.md) and
[`qualification.md`](../../docs/pr-artifacts/pr-15d/qualification.md).

This tree is engine-neutral and local-only. It compares Quervant, Tantivy and
Apache Lucene on one frozen, deterministic exact-term workload. It does not
optimize production search/storage code and does not assert a performance
threshold.

## Layout

```text
benchmarks/pr15d/
  spec/       frozen pr15d_v1 workload contract (machine + human readable)
  corpus/     deterministic TSV generator and independent oracle
  protocol/   pr15d-adapter-v1 JSON Lines schema
  adapters/   one independently built local disk adapter per engine
  harness/    run.py, validate.py, aggregate.py, smoke.py, test_pr15d.py
```

## Workflow

```sh
# 1. Freeze the neutral corpus and verify it twice.
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus

# 2. Deterministic tests (no Tantivy/Lucene required).
python3 benchmarks/pr15d/harness/test_pr15d.py

# 3. Operator-attested, clean-source, contention-checked trials.
#    Requires all three pinned adapters and toolchains; otherwise exits 4.
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/<unique-id>

# 4. Strict validation (exit 0 QUALIFIED, 2 INVALID, 3 UNQUALIFIED/BLOCKED).
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15d/runs/<unique-id> \
  --out target/pr15d/runs/<unique-id>/validation.json

# 5. Aggregate only from validated raw manifests.
python3 benchmarks/pr15d/harness/aggregate.py \
  --run target/pr15d/runs/<unique-id> \
  --out benchmarks/reports/pr15d/pr15d-qualified.json \
  --md docs/pr-artifacts/pr-15d/qualification.md
```

Raw corpora, indexes, logs and contention probes stay under untracked
`target/pr15d/`. Only sanitized manifest-only summaries are checked in.

## Comparability contract

- **Mandatory lane:** exact, unanalyzed `Keyword` membership over `key`/`group`,
  ordered by `doc_id` ascending, with exact `total_hits`. No scoring, no
  stemming, no normalization, no boosts. `score_comparison = NOT_APPLICABLE`.
- **Scored BM25 lane:** `SEMANTICALLY_NONCOMPARABLE`; zero cross-engine ratios.
- **Regimes:** `process_cold` means a fresh adapter process and unopened index
  reader per sample — **not** OS page-cache-cold. `warm` uses one process and
  one reader with five untimed warmups and 20 measured samples.
- **Throughput:** a separate 100-request serial window, labelled
  `serial_ops_per_second`; never multi-thread QPS.
- **Resources:** RSS/CPU/allocation are `NOT_MEASURED` when no common valid
  method exists, never zero.
- **Statistics:** nearest-rank p95 (`ceil(.95*n)-1`) and p99
  (`ceil(.99*n)-1`) over 20 samples; a sample distribution, not a production SLA.

## Adapters

| Engine | Source | Backend | State |
|---|---|---|---|
| Quervant | `adapters/quervant` (standalone, locked Cargo project) | `FsDirectory` | Builds; exact-term smoke passes (stable and MSRV) |
| Tantivy | `adapters/tantivy` (standalone, locked `=0.22.1`) | on-disk `MmapDirectory` | Builds; exact-term smoke passes at 16/10K/100K (stable and MSRV) |
| Lucene | `adapters/lucene` (verified Gradle 8.14.3 wrapper) | `FSDirectory` | Source complete; local build **BLOCKED-ENVIRONMENT** (no JDK 21), CI job added |

All adapters speak `pr15d-adapter-v1` on stdin/stdout: one JSON request/response
per line, `stderr` for diagnostics, `engine_ns` measured internally around only
the public engine operation, typed error records and nonzero exit on terminal
failure. Index build, commit, reopen and index size are separate measurements.

## A1 dependency/toolchain correction

- Tantivy is pinned exactly at `=0.22.1` with a standalone `Cargo.lock`
  (`resolver = "3"`, `rust-version = "1.85"`); `0.22.0` is not used.
- The Lucene adapter carries the standard verified Gradle 8.14.3 wrapper
  (`gradlew`, `gradlew.bat`, `gradle-wrapper.jar`), with checksums recorded in
  `adapters/lucene/A1-CHECKSUMS.sha256` and provenance in
  `adapters/lucene/A1-GRADLE-PROVENANCE.json`.
- `harness/smoke.py` is a bounded, non-timed three-adapter exact-hit check used
  by the isolated `pr15d-adapters` CI job. It never runs qualified trials and
  never reports performance.

## Known blockers

1. **X14 DEFER-ENVIRONMENT locally:** no JDK 21/`javac` on this host, so the
   Lucene adapter cannot be compiled or smoke-tested locally. The isolated CI
   job provisions Temurin 21 and is the execution path for that gate.
2. **X24 WAIT-HUMAN:** operator idle attestation must come from a human; the
   agent cannot self-attest. No `run.py --trials 3 --idle-confirmed` was run.
3. **A1 CI status pending:** the new `pr15d-adapters` job cannot be executed
   without push/PR credentials.

No qualified cross-engine performance result exists in this tree.
