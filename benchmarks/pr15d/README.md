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
| `comparative-smoke` | `pull_request` (opened/synchronize/reopened) touching `benchmarks/pr15d/**` or the workflow; manual dispatch with `full_correctness=false` | builds all three adapters, then the existing 10K exact-hit smoke |
| `comparative-full-correctness` | **opt-in only:** a `pr15d-full-correctness` label on the PR, or manual dispatch with `full_correctness=true` | builds all three adapters, verifies the independent oracle, then exact-hit checks at both 10K and 100K |

Both jobs verify the Gradle wrapper checksums before any Java invocation, are
read-only, never invoke the timed harness and never attest idleness. Hosted CI
proves correctness only; it is never a performance data source.

### Why the full gate is label-gated, not dispatch-only

GitHub only makes `workflow_dispatch` available once the workflow file exists on
the **default branch**. This workflow is introduced by the PR that needs the
gate, so manual dispatch cannot validate that same PR before merge — the job was
observed as `skipped` on PR #81. Adding the `pr15d-full-correctness` label to a
PR is therefore the pre-merge opt-in; `workflow_dispatch` is retained for use
after merge. The full gate is deliberately **not** unconditional: ordinary PR
activity only runs the 10K smoke, and label events never duplicate the smoke job.

## Known blockers

1. **X14 no longer applies locally:** JDK 21 (`openjdk 21.0.12.1`) is present on
   this host, so the Lucene adapter was built with the verified Gradle 8.14.3
   wrapper and the full 10K/100K three-engine correctness gate ran locally. The
   hosted job remains the CI execution path for that same gate.
2. **First campaign (superseded, preserved as evidence):** run
   `20261030T220025Z-c9e982f…` was measured with the original timing definition
   (`engine_ns` stopped before stored-`doc_id` materialisation) and is retained
   byte-identically under `benchmarks/reports/pr15d/diagnostic-v1/` and
   `docs/pr-artifacts/pr-15d/qualification-v1-superseded.md`. Do not quote it as
   a corrected comparison.
3. **Corrected campaign (current result):** run
   `20261031T005545Z-40a9c26…` on measured source `40a9c26`, executed in the
   operator-attested MSI window (2026-10-31 00:50Z–02:50Z). `run.py` exit 0, 3/3
   trials per engine, 54/54 contention `clear`; `validate.py` → `QUALIFIED`
   (0 errors); the aggregator produced `pr15d-qualified.json`
   (`c9e8ed72…`) and `qualification.md` (`fc7ff7b4…`) with byte-identical
   re-derivation and 108 independently recomputed statistics matching.
4. **CPU/RSS measured separately:** 18/18 probes `MEASURED` (cpu_target,
   `SC_CLK_TCK=100`, contention clear). These are process-level diagnostics and
   never enter `engine_ns` or the latency ratios; allocations stay
   `NOT_MEASURED`. See `docs/pr-artifacts/pr-15d/b-resource-report.md`.
5. **Evidence package built, not published:** 68 members, 502 566 bytes,
   SHA-256 `426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab`,
   disposition `BLOCKED_SENSITIVE_CONTENT` (archived `run.json` carries absolute
   host paths). Raw bytes were deliberately not rewritten; the archive stays
   local (`target/pr15d/evidence/`, gitignored) for an approved private handoff.
6. **Pending gates:** exact-head CI on the final commit (run IDs recorded in
   `b-acceptance.md`) and independent reviewer acceptance. `gh` credentials are
   invalid locally, so dispatch/push actions are performed through the
   maintainer's session.

The current comparison is `LATENCY-QUALIFIED / ACCEPTANCE-BLOCKED`: qualified
latency/throughput/ingestion results for Quervant, Tantivy 0.22.1 and Lucene
9.12.3, measured once on an attested WSL2/ext4 host (Quervant is reported as
substantially slower, published unaltered), with no parity or significance claim
and scored BM25 still `SEMANTICALLY_NONCOMPARABLE`.
