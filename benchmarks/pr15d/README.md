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
- `harness/smoke.py` is a bounded, non-timed three-adapter exact-hit check. The
  automatic gate runs it on the 10K corpus only; the on-demand
  full-correctness gate adds `--sizes 10000,100000`, which is a strict subset of
  the frozen corpus sizes and leaves the default unchanged. It never runs
  qualified trials and never reports performance.

## Comparative CI (PR15D-B)

Correctness for the three standalone adapters no longer lives in `ci.yml`. It
runs in `.github/workflows/comparative-adapters.yml`, so the required `rust`,
`msrv` and `rustfs` checks keep their exact previous design:

| Job | Trigger | Scope |
|---|---|---|
| `comparative-smoke` | `pull_request` touching `benchmarks/pr15d/**` or the workflow; manual dispatch with `full_correctness=false` | builds all three adapters, then the existing 10K exact-hit smoke |
| `comparative-full-correctness` | manual dispatch with `full_correctness=true` only | builds all three adapters, verifies the independent oracle, then exact-hit checks at both 10K and 100K |

Both jobs verify the Gradle wrapper checksums before any Java invocation, are
read-only, never invoke the timed harness and never attest idleness. Hosted CI
proves correctness only; it is never a performance data source.

## Known blockers

1. **X14 no longer applies locally:** JDK 21 (`openjdk 21.0.12.1`) is present on
   this host, so the Lucene adapter was built with the verified Gradle 8.14.3
   wrapper and the full 10K/100K three-engine correctness gate ran locally. The
   hosted job remains the CI execution path for that same gate.
2. **X25 resolved, campaign blocked by validation:** the operator attested an
   idle window and the three-engine campaign ran on the clean commit (run
   `20261030T220025Z-c9e982f…`). `validate.py` then rejected the run with two
   Tantivy `index_bytes_inconsistent` errors, so under X32/X37 no aggregate was
   produced and **no qualified performance result is published**. See
   `docs/pr-artifacts/pr-15d/b-trials.md`.
3. **PR15D-B CI observation pending:** the comparative adapter job moved out of
   `ci.yml` into `.github/workflows/comparative-adapters.yml`. Trigger guards,
   job set and absence of any timing/self-attestation path are asserted by
   deterministic tests locally, but the actual GitHub Actions runs and both
   manual dispatch modes still require push/PR credentials (X43).

No qualified cross-engine performance result exists in this tree.
