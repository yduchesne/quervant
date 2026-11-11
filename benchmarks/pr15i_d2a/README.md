# PR 15I-D2-A — source-locked scoring-cost qualification

**Measurement-only.** This directory contains the frozen diagnostic tooling for
PR 15I-D2-A. It ships no production scoring change, no alternate executor, no
BM25 change and no PR15D adapter/corpus change. D2-B is not authorized here.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `9429dce99827f25766a92c1fbded8f78a0b168f1` (merged PR 15I-D1-F closeout) |
| Protocol | `protocol_v1.json`, schema `pr15i-d2a-scoring-attribution-v1` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Arms | `A` pristine BASE `op=query`; `Q`/`P` same derivative binary, `P` uses `op=query_probe` |
| Lanes | Nine frozen PR15D warm lanes (10K/100K × absent/rare/medium/common + 100K common K10) |
| Tooling freeze | `tooling_manifest.json` (T0 identity required by `verify.py`) |

The diagnostic derivative is produced only by `patch_source.py`, is insertion
only, and is independently reversed to BASE by `source_proof.py`. The
derivative is never committed. `d2a_probe` exists only in the scratch worktree.

## Commands

`BASE_ROOT` and `SCRATCH_ROOT` are detached Git worktrees at BASE; the scratch
worktree is clean before materialization. All outputs are new directories under
`<tooling-root>/target/pr15i-d2a/`; existing paths are never reused.

```sh
python3 benchmarks/pr15i_d2a/run.py preflight \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d2a/preflight/preflight.json

python3 benchmarks/pr15i_d2a/run.py build \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d2a/builds

python3 benchmarks/pr15i_d2a/run.py aa \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d2a/aa/d2a-base-aa-01 --idle-confirmed

python3 benchmarks/pr15i_d2a/verify.py \
  --base-root "$BASE_ROOT" \
  --campaign-dir target/pr15i-d2a/aa/d2a-base-aa-01

python3 benchmarks/pr15i_d2a/run.py campaign \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --campaign d2a-unbatched-01 \
  --out target/pr15i-d2a/paired/d2a-unbatched-01 --idle-confirmed

python3 benchmarks/pr15i_d2a/verify.py \
  --base-root "$BASE_ROOT" \
  --campaign-dir target/pr15i-d2a/paired/d2a-unbatched-01

# d2a-unbatched-02 is run only after campaign 01 qualifies, with no changes.
python3 benchmarks/pr15i_d2a/verify.py \
  --base-root "$BASE_ROOT" --aggregate \
  --series-root target/pr15i-d2a/paired \
  --control-dir target/pr15i-d2a/aa/d2a-base-aa-01

python3 benchmarks/pr15i_d2a/run.py archive \
  --campaign-dir target/pr15i-d2a/paired/d2a-unbatched-01 \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d2a"
```

Exit codes: `0` success/verified, `2` invalid input, `3` blocked.

## Campaign contract

- `d2a-base-aa-01`: 4 blocks × 4 slots = 16 slots, arms `A1A2A2A1 / A2A1A1A2 /
  A1A2A2A1 / A2A1A1A2`; two independent BASE builds and two shared indexes.
  Every block/lane `A1/A2` ratio must be in `[0.80, 1.25]`, and the lower
  median of four block ratios in `[0.85, 1.15]`.
- `d2a-unbatched-01` / `-02`: 4 blocks × 6 slots = 24 slots, arm orders
  `AQPPQA / PQAAQP / QAPPAQ / PAQQAP`; 9 lanes, 5 warmups + 20 timed integer
  `engine_ns` samples per lane/slot, one pinned adapter process per
  `(arm, lane, slot)`, and two clear contention probes per slot.
- Q and P are the same absolute binary and SHA-256. Q must not expose
  `stage_ns`/`counts`; P writes them only after `engine_ns` stops.
- Four index builds per paired campaign (A/10K, A/100K, QP/10K, QP/100K) with
  byte-identical A/QP digests and the frozen 100K LZ4 sentinels.

## Stage and counter contract

Ten inherited D0 stages plus three nested score stages:

`plan_ns`, `reader_live_ns`, `expand_ns`, `stats_ns`, `evaluate_ns`,
`candidate_ns`, `projection_ns`, `leaf_decode_ns`, `membership_ns`,
`score_vector_ns`, `score_map_ns`, `score_owner_ns`, `score_accumulate_ns`.

Six counters: `matched_docs`, `scored_docs`, `candidate_docs`, `bm25_calls`,
`scoring_map_entries`, `positive_term_owners`. For each frozen single-term lane
the verifier requires `bm25_calls == candidate_docs == scored_docs ==
matched_docs == expected_hits`, `scoring_map_entries == expected_hits`, and
`positive_term_owners == 0` for absent and `1` for a present term. The nested
score sum may exceed `score_vector_ns` only by the frozen per-sample overhead
tolerance `max(10,000 ns, 2%)`; more than 1% violating samples invalidates the
stage partition.

## Verification and evidence

`verify.py` does not import `run.py`. It re-derives the frozen corpus manifest,
reads every sealed slot, recomputes medians/ratios/drift/intrusion/stage
partitions/counters and the §11 priority gate, refuses unknown or extra seal
members, and writes a deterministic `sanitized/summary.{json,md}` plus
`verification.json`. It also requires the frozen tooling manifest.

`archive` refuses to run before independent verification, creates
`CAMPAIGN.tar.gz` with `O_EXCL` outside the repository, writes an immutable
`.sha256` sidecar, safely extracts the archive into a fresh directory, rejects
traversal/symlinks/extra members and re-hashes every member. Archives on
`$HOME` share the same physical disk unless the operator supplies off-host
storage; `SAME_DISK_ONLY` is recorded and is not an off-host backup.

## Non-goals and limits

No production `src/` change, no adapter/corpus/oracle/PR15D change, no
threshold tuning, no extra campaigns, no selective reruns, no per-candidate
`Instant::now()`, and no claim that an optimistic diagnostic upper bound is a
delivered speedup. `score_vector_ns` is an inclusive parent of the three score
substages; parent and children are never added together.

## Tests

```sh
python3 -m py_compile benchmarks/pr15i_d2a/*.py
python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v
```

Python `unittest` only; no third-party packages. The suite covers the BT-01…
BT-25 matrix with synthetic fixtures and mutation cases, in addition to the
real-path Rust scoring-contract suite in
`crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs`.
