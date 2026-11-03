# PR 15E — optimized Quervant three-engine qualification (PR 15D matrix)

**Status: `THREE_ENGINE_OPTIMIZED_QUALIFIED_REVIEW_READY`.** A complete, newly qualified PR 15D
three-engine campaign was run against optimized Quervant source
`40ca10bae46f2d7df7804a0a129a99a4daf35ef0`. Validator and aggregator both report `QUALIFIED`,
all 54 real contention probes were `clear`, and all 32 lanes × 3 engines × 3 trials are present
with 20 oracle-checked samples each. **No source, adapter, harness, format or CI change was
made. PR #83 was not merged; G11 remains `PENDING_REVIEW`.**

## 1. Identity and method

| Item | Value |
|---|---|
| Measured source (detached worktree) | `40ca10bae46f2d7df7804a0a129a99a4daf35ef0` |
| Historical PR 15D reference (context only) | `40a9c26a57aa23640904075e77be956ee52718bc` |
| Original pre-optimization base (context) | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| Workload / spec | frozen `pr15d_v1` (unchanged N, K, classes, sort, terms, regimes) |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Engines | Quervant (release adapter on `quervant-core@40ca10b`, `FsDirectory`), Tantivy `=0.22.1`, Lucene (JDK 21, pinned Gradle wrapper) |
| Trials / samples | 3 independent trials per engine, 20 measured requests per lane/trial, 5 untimed warmups on warm lanes |
| Lanes | 32 per engine (N∈{10K,100K} × {absent,rare,medium,common} × K∈{10,100} × {process_cold,warm}) |
| Contention | **54/54 real probes `clear`** (3 trials × 3 engines × 2 sizes × 3 probes) |
| Validation | `validate.py` exit 0, `QUALIFIED`, `errors=[]`; aggregator `QUALIFIED`; independent `verify_aggregate` re-derivation PASS |
| Host filesystem | `ext4` (native); host identity only as fingerprint hash `4f971362…` |
| Idle authorization | Maintainer's explicit assumed-idle instruction for this campaign; recorded as authorization, **not** as an observed idleness fact |

Timing boundary (verbatim from the qualified aggregate): `engine_ns` covers engine search/count,
the requested top-K sort and materialisation of every returned `doc_id`; process start, reader
open, response serialization and oracle checks are excluded. Query API shape differs by engine
(Quervant counts and selects in one public call; Tantivy/Lucene issue separate count and Top-K
operations); both totals are exact and included for every engine. The three engines return the
same ascending `doc_id` order, but physical sort representations differ (Quervant keyword column,
Tantivy numeric ordinal, Lucene `SortedDocValues`): `physical_equivalence = NOT_CLAIMED`.

## 2. Warm lanes (16) — new same-run direct comparison

Median of three trial medians, milliseconds. `Q/T` and `Q/L` are Quervant ÷ other engine; **> 1
means Quervant is slower**. `Inconclusive` lists engines the canonical aggregator flagged
(dispersion > 1.10 or overlapping trial-median ranges); those rows are descriptive only.

| Lane | Quervant | Tantivy | Lucene | Q/T | Q/L | Inconclusive |
|---|---:|---:|---:|---:|---:|---|
| `pr15d_v1/10000/absent/k10` | 0.13 | 0.01 | 0.29 | 11.45 | 0.45 | tantivy, lucene |
| `pr15d_v1/10000/absent/k100` | 0.14 | 0.01 | 0.37 | 11.29 | 0.38 | tantivy, lucene |
| `pr15d_v1/10000/rare/k10` | 2.63 | 0.01 | 0.79 | 197.94 | 3.32 | tantivy, lucene |
| `pr15d_v1/10000/rare/k100` | 2.82 | 0.02 | 0.69 | 182.92 | 4.08 | tantivy, lucene |
| `pr15d_v1/10000/medium/k10` | 4.81 | 0.04 | 1.43 | 134.42 | 3.36 | tantivy, lucene |
| `pr15d_v1/10000/medium/k100` | 4.42 | 0.10 | 4.95 | 43.22 | 0.89 | tantivy |
| `pr15d_v1/10000/common/k10` | 6.40 | 0.08 | 1.59 | 75.53 | 4.04 | tantivy, lucene |
| `pr15d_v1/10000/common/k100` | 7.58 | 0.14 | 3.78 | 54.05 | 2.00 | tantivy, lucene |
| `pr15d_v1/100000/absent/k10` | 1.22 | 0.02 | 0.34 | 76.82 | 3.55 | tantivy, lucene |
| `pr15d_v1/100000/absent/k100` | 1.20 | 0.02 | 0.37 | 74.21 | 3.28 | tantivy, lucene |
| `pr15d_v1/100000/rare/k10` | 27.45 | 0.02 | 0.73 | 1508.44 | 37.79 | tantivy, lucene |
| `pr15d_v1/100000/rare/k100` | 26.93 | 0.02 | 0.78 | 1474.41 | 34.63 | — |
| `pr15d_v1/100000/medium/k10` | 43.70 | 0.18 | 1.50 | 245.81 | 29.08 | lucene |
| `pr15d_v1/100000/medium/k100` | 46.41 | 0.24 | 4.66 | 191.77 | 9.96 | tantivy, lucene |
| `pr15d_v1/100000/common/k10` | 68.26 | 0.63 | 1.49 | 107.63 | 45.84 | lucene |
| `pr15d_v1/100000/common/k100` | 79.96 | 0.67 | 3.37 | 119.31 | 23.75 | lucene |

## 3. Process-cold lanes (16) — new same-run direct comparison

`process_cold` means a fresh adapter process with an unopened reader, **not** an OS-cold page
cache. Same columns and caveats as above.

| Lane | Quervant | Tantivy | Lucene | Q/T | Q/L | Inconclusive |
|---|---:|---:|---:|---:|---:|---|
| `pr15d_v1/10000/absent/k10` | 18.75 | 0.05 | 19.13 | 371.30 | 0.98 | tantivy, lucene |
| `pr15d_v1/10000/absent/k100` | 18.82 | 0.04 | 20.02 | 489.85 | 0.94 | tantivy, lucene |
| `pr15d_v1/10000/rare/k10` | 21.70 | 0.05 | 28.13 | 398.14 | 0.77 | tantivy, lucene |
| `pr15d_v1/10000/rare/k100` | 21.46 | 0.05 | 27.86 | 398.85 | 0.77 | tantivy, lucene |
| `pr15d_v1/10000/medium/k10` | 24.20 | 0.10 | 35.89 | 241.06 | 0.67 | tantivy, lucene |
| `pr15d_v1/10000/medium/k100` | 25.23 | 0.21 | 62.23 | 120.56 | 0.41 | tantivy |
| `pr15d_v1/10000/common/k10` | 26.49 | 0.17 | 36.16 | 160.08 | 0.73 | tantivy |
| `pr15d_v1/10000/common/k100` | 27.95 | 0.22 | 55.27 | 124.65 | 0.51 | tantivy |
| `pr15d_v1/100000/absent/k10` | 190.30 | 0.06 | 19.67 | 3064.62 | 9.67 | tantivy |
| `pr15d_v1/100000/absent/k100` | 190.98 | 0.05 | 19.69 | 3715.84 | 9.70 | — |
| `pr15d_v1/100000/rare/k10` | 219.94 | 0.06 | 27.84 | 3661.93 | 7.90 | tantivy |
| `pr15d_v1/100000/rare/k100` | 223.77 | 0.09 | 28.35 | 2448.20 | 7.89 | tantivy |
| `pr15d_v1/100000/medium/k10` | 233.20 | 0.26 | 37.19 | 894.55 | 6.27 | tantivy |
| `pr15d_v1/100000/medium/k100` | 236.97 | 0.39 | 65.72 | 609.54 | 3.61 | tantivy |
| `pr15d_v1/100000/common/k10` | 257.10 | 0.78 | 37.13 | 329.64 | 6.92 | — |
| `pr15d_v1/100000/common/k100` | 269.12 | 0.81 | 55.67 | 331.33 | 4.83 | — |

## 4. Nine previously paired warm lanes — measured vs historical vs projected

Columns: PR 15D historical qualified medians (context, different session), the previously accepted
PR 15E cumulative Quervant-only measurement (arm B of `cumulative-closeout.json`), any earlier
*projection* (none exists with a disclosed formula → `N/A`), and the new three-engine Quervant
measurement. All values in milliseconds; the new column is the authoritative current number.

| Lane | PR15D Quervant | PR15D Tantivy | PR15D Lucene | PR15E cumulative Quervant (B) | Projected Quervant | New 3-engine Quervant |
|---|---:|---:|---:|---:|---:|---:|
| `pr15d_v1/10000/absent/k100` | 0.30 | 0.01 | 0.32 | 0.14 | N/A (no disclosed formula) | 0.14 |
| `pr15d_v1/10000/rare/k100` | 7.21 | 0.01 | 0.62 | 3.03 | N/A (no disclosed formula) | 2.82 |
| `pr15d_v1/10000/medium/k100` | 12.13 | 0.09 | 4.27 | 5.11 | N/A (no disclosed formula) | 4.42 |
| `pr15d_v1/10000/common/k100` | 27.74 | 0.13 | 2.65 | 8.74 | N/A (no disclosed formula) | 7.58 |
| `pr15d_v1/100000/absent/k100` | 2.86 | 0.02 | 0.35 | 1.25 | N/A (no disclosed formula) | 1.20 |
| `pr15d_v1/100000/rare/k100` | 81.21 | 0.02 | 0.68 | 28.29 | N/A (no disclosed formula) | 26.93 |
| `pr15d_v1/100000/medium/k100` | 613.62 | 0.24 | 4.36 | 51.12 | N/A (no disclosed formula) | 46.41 |
| `pr15d_v1/100000/common/k10` | 1,877.74 | 0.60 | 1.33 | 72.22 | N/A (no disclosed formula) | 68.26 |
| `pr15d_v1/100000/common/k100` | 1,881.92 | 0.66 | 2.86 | 87.38 | N/A (no disclosed formula) | 79.96 |

Relative standing versus the other engines, historical PR 15D → new run (median ratios, > 1 =
Quervant slower):

| Lane | Q/T historical | Q/T new | Q/L historical | Q/L new |
|---|---:|---:|---:|---:|
| `pr15d_v1/10000/absent/k100` | 26.9 | 11.3 | 0.9 | 0.4 |
| `pr15d_v1/10000/rare/k100` | 526.2 | 182.9 | 11.7 | 4.1 |
| `pr15d_v1/10000/medium/k100` | 128.7 | 43.2 | 2.8 | 0.9 |
| `pr15d_v1/10000/common/k100` | 207.8 | 54.1 | 10.5 | 2.0 |
| `pr15d_v1/100000/absent/k100` | 176.3 | 74.2 | 8.2 | 3.3 |
| `pr15d_v1/100000/rare/k100` | 4296.9 | 1474.4 | 119.8 | 34.6 |
| `pr15d_v1/100000/medium/k100` | 2582.5 | 191.8 | 140.6 | 10.0 |
| `pr15d_v1/100000/common/k10` | 3104.7 | 107.6 | 1411.4 | 45.8 |
| `pr15d_v1/100000/common/k100` | 2863.1 | 119.3 | 656.9 | 23.7 |

## 5. Relative ranking on the nine paired warm lanes (no overall superiority claim)

| Comparison | Quervant faster | Quervant slower | Inconclusive |
|---|---:|---:|---:|
| Quervant vs Tantivy | 0 | 3 | 6 |
| Quervant vs Lucene | 1 | 1 | 7 |

These nine lanes are a selected subset of the 32-lane matrix; they do **not** establish general
engine superiority in either direction. On the full matrix Quervant remains substantially slower
than Tantivy on every warm lane, while its position versus Lucene is mixed (faster on some
small/absent and process-cold lanes, slower on the high-match warm lanes). This is reported
exactly as measured; no lane was excluded or reclassified.

## 6. Ingestion, index size and serial throughput (median of three trials)

`ingest_through_commit_ns = index_ns + commit_ns` (adapter insertion plus commit — **not** a
proven fsync-equivalent durability measurement). Throughput is one sustained **serial** window,
not parallel QPS.

| Engine | N | Ingest+commit | Index bytes | Serial ops/s |
|---|---|---:|---:|---:|
| quervant | 10000 | 193 ms | 3,090,037 B | 222.4 ops/s |
| quervant | 100000 | 1,837 ms | 30,965,025 B | 22.5 ops/s |
| tantivy | 10000 | 98 ms | 298,299 B | 7,974.6 ops/s |
| tantivy | 100000 | 1,367 ms | 2,907,264 B | 3,337.7 ops/s |
| lucene | 10000 | 277 ms | 186,052 B | 615.5 ops/s |
| lucene | 100000 | 832 ms | 1,858,642 B | 696.4 ops/s |

Quervant's index is larger and its serial throughput lower than Tantivy's in this exact-term
workload; Lucene sits between them. These are descriptive measurements of the frozen workload,
not general storage claims.

## 7. What changed relative to the historical PR 15D result

The optimizations improved Quervant's position without changing the workload: on the 100K warm
lanes the Quervant/Lucene ratio moved from ~120× to ~35× (rare), ~141× to ~10× (medium) and
~657× to ~24× (common/k100), and the Quervant/Tantivy ratio from ~4300× to ~1470× (rare), ~2580×
to ~192× (medium) and ~2863× to ~119× (common/k100). Process-cold high-match lanes improved even
more in absolute terms (e.g. 100K common/k100 ≈ 2082 ms → 269 ms). These comparisons are
**cross-session and cross-source**; only the new run's own numbers are directly comparable.

## 8. Determination gates

| Gate | State |
|---|---|
| A01 source (exact `40ca10b` detached tree, adapter links it, frozen inputs unchanged) | PASS |
| A02 environment (JDK 21, Tantivy 0.22.1, Gradle wrapper checksums, native FS) | PASS |
| A03 corpus (frozen digest + independent oracle) | PASS |
| A04 measurement (one complete run, 3 engines × 32 lanes × 3 trials × 20 samples, 54/54 clear) | PASS |
| A05 correctness (exact `doc_ids`, `total_hits`, protocol per response) | PASS |
| A06 validation (`validate.py` exit 0 `QUALIFIED`) | PASS |
| A07 aggregation (re-derived, 32 lanes, both regimes) | PASS |
| A08 comparison separation (new vs historical vs projected; inconclusive disclosed) | PASS |
| A09 publication (three new sanitized files; historical PR15D untouched) | PASS |
| A10 QA (documentation/test checks; no production/adapter/runner change) | PASS |
| A11 remote (evidence commit pushed; exact-head CI recorded in the delivery report) | PASS |
| A12 governance (PR unmerged; G11 pending; no optimization implemented) | PASS |

## 9. Limits

Frozen synthetic exact-term corpus on local disk only; no BM25 score parity
(`score_comparison: NOT_APPLICABLE`, `SEMANTICALLY_NONCOMPARABLE`); physical sort
representations differ and are not normalized; `process_cold` is not OS-cold; 20-sample
nearest-rank percentiles are sample distributions, not SLAs; serial throughput is not parallel
QPS; no remote ObjectStore/RustFS or distributed measurement in this campaign; historical PR 15D
numbers come from a different session and source and are context only; the nine-lane subset is
not an engine-superiority claim.
