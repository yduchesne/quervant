# PR 15I-D0 — source-locked baseline and search hot-path attribution

**Status: `15ID0_BLOCKED`.** The diagnostic tooling in this directory is
implemented, source-proven and unit/adversarially tested, but the prescribed
paired campaigns and the canonical three-engine PR 15D campaign cannot be built
from the frozen baseline because the PR 15D Quervant adapter lockfile at
`7237bce` is stale (it lacks `lz4_flex` and `twox-hash`, which the
`quervant-core` default `stored-lz4` feature now requires). The official PR 15D
harness builds with `--locked` and fails closed. See
[`docs/pr-artifacts/pr-15i-d0/preflight.md`](../../docs/pr-artifacts/pr-15i-d0/preflight.md)
and [`execution-status.md`](../../docs/pr-artifacts/pr-15i-d0/execution-status.md).

This directory contains measurement/diagnostics tooling only. It does not ship,
select or implement any production search optimization, and it does not
authorize PR 15I-D1.

## Frozen source

| Item | Value |
|---|---|
| Pinned BASE | `7237bce325834d6cc1c73735697be29bc60ef16b` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Protocol | `protocol_v1.json` (`pr15i-d0-attribution-v1`) |
| Frozen workload | PR 15D `pr15d_v1`, 10K/100K, `absent`/`rare`/`medium`/`common` |

`origin/main` advanced after BASE only through the PR #92 docs-only closeout
(`docs/BENCHMARKING.md`, `docs/ROADMAP.md`,
`docs/pr-artifacts/pr-15i-0/architecture-15i-c.md`,
`docs/pr-artifacts/pr-15i-c/closeout.md`). D0 continues to measure the pinned
BASE and never imports the rejected PR 15I-C physical executor.

## Three measurement arms

| Arm | Source | Operation | Timers |
|---|---|---|---|
| `A` | pristine BASE | `op=query` | none |
| `Q` | BASE + diagnostic insertions | `op=query` | inactive |
| `P` | **the same executable as Q** | `op=query_probe` | active |

`Q` and `P` are one release binary at one absolute path and SHA-256. `P` writes
exactly ten stage pairs and three counter pairs outside `engine_ns`; `A` and `Q`
must not carry those fields. The ten stages are `plan_ns`, `reader_live_ns`,
`expand_ns`, `stats_ns`, `evaluate_ns`, `candidate_ns`, `projection_ns`,
`leaf_decode_ns`, `membership_ns`, `score_vector_ns`; the counters are
`matched_docs`, `scored_docs`, `candidate_docs`.

The diagnostic source derivative is **never committed**. It is materialized in a
disposable scratch worktree by `patch_instrumented_source.py` and proven
byte-reversible to BASE by `source_proof.py`.

## Commands

All commands run from the tooling commit. `--checkout-root` is a detached,
pristine BASE worktree; `--instrumented-root` is a disposable BASE worktree that
receives the insertions.

```sh
# 1. Source/environment/corpus preflight
python3 benchmarks/pr15i_d0/run.py preflight \
  --checkout-root <pristine-base-worktree> \
  --out target/pr15i-d0/preflight-01.json

# 2. Materialize the diagnostic derivative and prove it independently
python3 benchmarks/pr15i_d0/run.py build \
  --checkout-root <pristine-base-worktree> \
  --instrumented-root <scratch-worktree> \
  --out target/pr15i-d0/build-01

# 3. Two frozen 24-slot campaigns (run only after the build gate passes)
python3 benchmarks/pr15i_d0/run.py campaign \
  --checkout-root <pristine-base-worktree> \
  --instrumented-root <scratch-worktree> \
  --campaign unbatched-01 --idle-confirmed \
  --out target/pr15i-d0/paired/unbatched-01

python3 benchmarks/pr15i_d0/run.py campaign \
  --checkout-root <pristine-base-worktree> \
  --instrumented-root <scratch-worktree> \
  --campaign unbatched-02 --idle-confirmed \
  --out target/pr15i-d0/paired/unbatched-02

# 4. Independent verification
python3 benchmarks/pr15i_d0/verify.py \
  --checkout-root <pristine-base-worktree> \
  --campaign-dir target/pr15i-d0/paired/unbatched-01
python3 benchmarks/pr15i_d0/verify.py \
  --checkout-root <pristine-base-worktree> \
  --series-root target/pr15i-d0/paired --aggregate

# 5. Tests
python3 -m unittest discover -s benchmarks/pr15i_d0 -p 'test_*.py' -v
```

`build` writes the A and Q/P release binaries and their `build.json` metadata
under each root's `target/pr15i-d0/build/{A,QP}/`. `campaign` finds those
deterministic paths, re-hashes the binaries and re-runs the source proof before
sampling. A sealed campaign cannot be overwritten.

## Campaign contract

- Schedule: 4 blocks × 6 slots = 24 slots, arms `AQPPQA / PQAAQP / QAPPAQ / PAQQAP`.
- Exact nine warm lanes per slot, in protocol order, including
  `pr15d_v1/100000/common/k10`.
- Five warmups and 20 timed `engine_ns` observations per lane per slot.
- One fresh adapter process per `(arm, lane, slot)`; the controller runs on the
  second allowed CPU and every adapter on the first allowed CPU.
- Two `clear` contention probes per slot (48 per campaign).
- Four fresh index builds per campaign (A/10K, A/100K, QP/10K, QP/100K), with
  byte-identical A/QP committed index digests and the frozen 100K LZ4 sentinels
  (15,747,551 committed bytes; 1,661,455 stored-section bytes).
- Full independent oracle per lane, including the absent zero-hit lane.

## Evidence and limitations

Raw evidence lives only under ignored `target/pr15i-d0/`. A campaign directory
contains `raw/`, `raw/slots/` and `setup/contention/`; `seal.json` maps every
required relative member to its SHA-256 and excludes itself. The independent
verifier re-hashes every member, recomputes the oracle from the frozen corpus
generator, recomputes all ratios/drift/stage partitions and rejects any
unlisted file, missing probe or path traversal.

Comparability limits that must never be dropped from a report:

- The canonical PR 15D lane is exact keyword membership, exact hit count and
  ascending `doc_id`. Quervant uses a `Keyword` column, Tantivy a numeric
  `ordinal` fast field and Lucene sorted doc values. The result is logically
  equivalent for the oracle; the physical operator, sort representation and
  scoring work are **not** equivalent.
- Quervant currently performs positive-term scoring in the unified executor;
  the PR 15D Tantivy adapter uses `TermQuery(..., Basic)` with `Count` and a
  numeric-sort `TopDocs`. No BM25 cost parity is claimed.
- `process_cold` in PR 15D means a fresh adapter process, not an OS page-cache
  cold start.
- Stage percentages are **instrumented diagnostic** observations from P. They are
  not accepted-build latency and do not imply a removable percentage.
- A `RANKING_NOT_QUALIFIED` result is a valid negative measurement, not an
  invitation to relax a threshold.

## Why this is not an optimization

The committed PR touches only `benchmarks/pr15i_d0/` and documentation. There is
no `crates/` change, no adapter change in `benchmarks/pr15d/`, no locked
dependency change and no format change. The only measurement artifact is a
source-locked, independently verified diagnosis — or, for this execution, a
truthful blocked report naming the smallest missing source decision.
