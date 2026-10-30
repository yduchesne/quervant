# PR 15D qualification

**Status: BLOCKED. No cross-engine comparative qualification was executed.**
This artifact must not be read as a performance result, a parity claim or a
qualified three-engine comparison.

## Why the qualified series did not run

| Gate | State | Evidence |
|---|---|---|
| Frozen Tantivy pin `=0.22.0` | **HARD STOP (X15)** | `0.22.0` is yanked; `cargo build` in an isolated project fails with `version 0.22.0 is yanked`. No adapter was authored against a substituted version. |
| JDK 21 / `javac` / Gradle 8.14.3 | **DEFER-ENVIRONMENT (X14)** | No Java toolchain exists anywhere on the host. |
| Verified Gradle wrapper | **HARD STOP (X16)** | No `gradlew`/wrapper JAR committed; only the official distribution SHA-256 is pinned. |
| Three engines available | **DEFER-ENVIRONMENT (X22)** | One adapter (Quervant) is runnable; Tantivy has no authorized pin; Lucene has no JDK. |
| Operator idle attestation | **DEFER-ATTESTATION (X24)** | The agent cannot self-attest; `run.py` records `IDLE_ATTESTATION_MISSING`. |
| CI benchmark gate | **DEFER-CI (X30)** | CI has no JDK/Gradle and the pin is unresolvable; global CI untouched. |

`run.py` on the current host writes a `status: "blocked"` run record and exits
`4`; `validate.py` classifies it `BLOCKED` and exits `3`.

## Workload identity (frozen and reproduced)

`pr15d_v1` was generated twice into independent directories; every file was
byte-identical (T01) and the manifest re-derived from the TSV bytes.

| Artifact | SHA-256 |
|---|---|
| `pr15d_v1_N10000.tsv` (10,000 rows, 546,283 bytes) | `5cdc9341d20bdc525af7e11d3b64bcabf66af9a6eaf27c7dfaddc87280be9a8b` |
| `pr15d_v1_N100000.tsv` (100,000 rows, 5,462,533 bytes) | `6ea867fe10679d12fa569822b27e58a8898d866938cf524870c84b0d80d5da4a` |
| `pr15d_v1_manifest.json` (canonical, sorted keys) | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

Exact oracle truth table (recomputed from the TSV bytes, independent of every
adapter):

| Lane | Exact `total_hits` (N=10,000) | Exact `total_hits` (N=100,000) |
|---|---:|---:|
| `pr15d_v1/<N>/absent/k10|k100` | 0 | 0 |
| `pr15d_v1/<N>/rare/k10|k100` | 1 | 1 |
| `pr15d_v1/<N>/medium/k10|k100` | 1,250 | 12,500 |
| `pr15d_v1/<N>/common/k10|k100` | 4,999 | 49,999 |

Top-K `doc_id` lists are oracle-derived and lexically ascending. `K` is 10 and
100; `N` is 10,000 and 100,000; the matrix is 16 lanes × 2 regimes = 32 measured
lanes per engine per trial, with 20 samples per lane.

## Supported and non-comparable lanes

| Lane | Classification | Published ratios |
|---|---|---|
| Exact unanalyzed `Keyword` membership over `key`/`group`, `doc_id` ascending, exact count | **Supported by the frozen contract** | None — the series did not run |
| BM25 scored lexical over `body` (`k1=1.2`, `b=0.75`) | `SEMANTICALLY_NONCOMPARABLE` | **Zero** |
| RustFS/remote or distributed measurements | Out of scope for PR 15D | None |
| Prefix/glob/regex/phrase/fuzzy/geo/JSON/typed queries | Not in this workload | None |

`score_comparison` is explicitly `NOT_APPLICABLE`; every mandatory query is a
constant-score exact-membership query.

## Per-engine evidence

| Engine | Build | Index/commit/reopen | Query latency | Index size | RSS | CPU | Allocations |
|---|---|---|---|---|---|---|---|
| Quervant | Adapter builds in release mode; sanity smoke only | `NOT_MEASURED` (qualified series) | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` |
| Tantivy | `BLOCKED` (X15) | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` |
| Lucene | `BLOCKED` (X14/X16) | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` |

No p50/p95/p99, QPS, ratio, RSS or CPU value from this PR is a qualified result.

### Non-qualified adapter sanity evidence (Quervant only)

The Quervant adapter was built and exercised to prove the public API boundary,
not to compare engines:

- 16-row canonical fixture: `documents_indexed=16`, `documents_verified=16`,
  all four classes matched the oracle exactly.
- 10,000-row corpus: `documents_indexed=10000`, `documents_verified=10000`,
  `index_bytes=3,090,037`, one segment; `medium` = 1,250 and `common` = 4,999
  exact hits, matching the oracle.

These figures are single-host adapter smoke values. They are **not** qualified
trial samples, are not compared with Tantivy/Lucene, and must not be cited as
Quervant performance.

## Host and toolchain

| Item | Value |
|---|---|
| Source | `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e` (`main`, clean) |
| Kernel / machine | recorded live by `run.py` into `run.json` |
| Filesystem | native Linux filesystem (ext4/xfs/btrfs only; `run.py` refuses others) |
| Rust | `rustc 1.98.1`, `cargo 1.98.1`; MSRV `1.85.0` available |
| Python | 3.12.3 |
| JDK / Gradle | absent |
| Lucene artifacts | 9.12.3 reachable on Maven Central (HTTP 200) |
| Gradle distribution SHA-256 | `bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531` |

## Reproduction commands

```sh
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/corpus
python3 benchmarks/pr15d/harness/test_pr15d.py
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --out target/pr15d/runs/<unique-id>            # currently BLOCKED, exit 4
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15d/runs/<unique-id> \
  --out target/pr15d/runs/<unique-id>/validation.json
python3 benchmarks/pr15d/harness/aggregate.py \
  --run target/pr15d/runs/<unique-id> \
  --out benchmarks/reports/pr15d/pr15d-qualified.json \
  --md docs/pr-artifacts/pr-15d/qualification.md
```

## Required unblocking actions

1. **Maintainer version-pin amendment** for Tantivy (`0.22.0` is yanked), or an
   approved reproducible vendoring policy.
2. **Provision JDK 21 and Gradle 8.14.3**, and approve a verified official
   Gradle wrapper (X16) or a checksum-pinned distribution.
3. **Operator-attested, contention-checked, clean-source 3-trial run** on a
   native filesystem with no competing workloads.
4. Regenerate the validated aggregate and replace this artifact only after the
   validator returns `QUALIFIED` with 3 × 20 observations for all three engines.
