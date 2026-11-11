# PR 15I-D0 canonical three-engine benchmark report

**Status: `D0_COMPARATIVE_BLOCKED_SOURCE_LOCK`.**
**Current three-engine ratio: `NO_CURRENT_3_ENGINE_RATIO`.**

No current Quervant/Tantivy/Lucene ratio is published. The official, unmodified
PR 15D harness could not build the frozen Quervant adapter at BASE because the
adapter's locked dependency set is stale. Publishing a historical number as a
current result would violate D0-I03/D0-I11 and is not done.

## 1. Exact commands and outcomes

Run from a detached, pristine BASE worktree
(`target/pr15i-d0/worktrees/canonical`):

| Step | Command | Outcome |
|---|---|---|
| corpus | `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus` | exit 0 |
| oracle | `python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus` | exit 0 |
| harness tests | `python3 benchmarks/pr15d/harness/test_pr15d.py` | 83/83 PASS |
| campaign | `python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed --out target/pr15i-d0/canonical-three-engine-01` | **exit 5** (`X15_BUILD_FAILED`) |
| validation | `python3 benchmarks/pr15d/harness/validate.py --run …` | exit 2, `INVALID` (13 errors; incomplete run) |
| aggregation | `python3 benchmarks/pr15d/harness/aggregate.py --run …` | exit 3, `AGGREGATION REFUSED (INVALID)` |

Exact blocker:

```text
X15_BUILD_FAILED: quervant adapter build failed:
error: cannot update the lock file .../benchmarks/pr15d/adapters/quervant/Cargo.lock
because --locked was passed to prevent this
```

The adapter's frozen `Cargo.lock` at BASE lacks `lz4_flex` and `twox-hash`,
which `quervant-core`'s default `stored-lz4` feature requires. The harness builds
with `--locked`, so it fails before any trial. No trial was started and no
sample was collected; the partial `run.json` says `"status": "running"` with zero
trials.

The plan authorizes exactly one full fresh repeat only for a verified transient
contention failure (`D0-X17`). This is not a contention failure, so no repeat was
attempted. `D0-X12` and `D0-X33` govern: record the blocker, do not change the
trial count, workload, lockfile or baseline.

## 2. Physical-comparability contract (must accompany any future ratio)

The canonical PR 15D lane is:

- exact `Keyword` membership on `key`/`group`;
- exact `total_hits`;
- ascending `doc_id` order;
- `score_comparison = NOT_APPLICABLE`.

The physical operators are **not** equivalent:

| Engine | Sort representation | Scoring in the timed lane |
|---|---|---|
| Quervant | `Keyword` column | unified executor still performs positive-term scoring |
| Tantivy 0.22.1 | numeric `ordinal` fast field | `TermQuery(..., IndexRecordOption::Basic)` + `Count`, numeric-sort `TopDocs` |
| Lucene 9.12.3 | sorted doc values | exact count + sorted-doc-values collection |

The oracle only proves logical equivalence of count and ordered IDs. It does not
prove equal physical work, equal BM25 cost, or equal memory behavior.

`process_cold` in PR 15D means a fresh adapter process with an unopened reader,
**not** an OS page-cache-cold start.

## 3. Historical PR 15I-0 numbers (not current)

The following values were **read from the committed historical source**
`docs/pr-artifacts/pr-15i-0/final-report.md` and asserted before reporting. They
describe an older source, harness run, index format and host; they are
`NOT_CONTROLLED` against BASE and must never be labelled current.

Historical warm medians (ns):

| Lane | Quervant | Tantivy | Lucene | Q/T |
|---|---:|---:|---:|---:|
| 100K absent K100 | 251,305 | 15,500 | 329,405 | 16.213 |
| 100K rare K100 | 254,804 | 18,600 | 665,310 | 13.699 |
| 100K medium K100 | 19,021,490 | 239,504 | 4,891,975 | 79.420 |
| 100K common K100 | 47,918,853 | 662,910 | 3,043,451 | 72.286 |
| 100K common K10 | 35,689,628 | 647,911 | 1,579,425 | 55.084 |

Historical reopen ratio Q/T: 98.641× (10K) and 897.505× (100K).

These are **not** D0 results. D0 measured zero comparative observations.

## 4. What a future qualified campaign must report

Only after the frozen adapter lock is resolved by an authorized source decision
may a fresh, unmodified PR 15D campaign be run. It must report:

- validator `QUALIFIED` with zero errors;
- three physical engines, three trials each, 32 lanes per trial, complete
  contention probes and the frozen rotation;
- absolute ns and Q/T, Q/L medians for every lane, index bytes and
  build/commit/reopen durations;
- `serial_ops_per_second` for throughput (never multi-thread QPS);
- source SHA, corpus digest, host fingerprint, toolchain and filesystem;
- the sort/scoring caveat next to every Q/T table.

No such report exists for BASE. The truthful current result is
`NO_CURRENT_3_ENGINE_RATIO`.
