# PR 15D comparative qualification assets

**Status: static harness complete, real three-engine qualification BLOCKED.**
See [`docs/pr-artifacts/pr-15d/preflight.md`](../../docs/pr-artifacts/pr-15d/preflight.md)
and [`qualification.md`](../../docs/pr-artifacts/pr-15d/qualification.md).

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
  harness/    run.py, validate.py, aggregate.py, test_pr15d.py
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
| Quervant | `adapters/quervant` (standalone, locked Cargo project) | `FsDirectory` | Builds; exact-term smoke passes |
| Tantivy | — | on-disk directory | **Not authored:** frozen `=0.22.0` pin is yanked (X15) |
| Lucene | `adapters/lucene` | `FSDirectory` | Source complete; unbuilt (no JDK/Gradle, X14/X16) |

All adapters speak `pr15d-adapter-v1` on stdin/stdout: one JSON request/response
per line, `stderr` for diagnostics, `engine_ns` measured internally around only
the public engine operation, typed error records and nonzero exit on terminal
failure. Index build, commit, reopen and index size are separate measurements.

## Known blockers

1. **X15 HARD STOP:** `tantivy = "=0.22.0"` is yanked and cannot resolve. A
   maintainer version-pin amendment is required; the agent did not substitute a
   version.
2. **X14 DEFER-ENVIRONMENT:** no JDK 21, `javac` or Gradle 8.14.3 on the host.
3. **X16:** no verified official `gradlew`/wrapper JAR is committed; only the
   official Gradle 8.14.3 distribution SHA-256 is pinned.
4. **X24:** operator idle attestation must come from a human; the agent cannot
   self-attest.
5. **X30:** CI has no JDK/Gradle and the frozen pin is unresolvable, so a CI
   benchmark gate was not added.

No qualified cross-engine result exists in this tree.
