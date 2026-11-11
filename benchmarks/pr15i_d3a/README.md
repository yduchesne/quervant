# PR 15I-D3-A — candidate processing and intermediate-materialization attribution

**Measurement-only.** This directory contains the frozen diagnostic tooling for
PR 15I-D3-A. It ships no production search, scorer, segment-format or API change.
It adds no late scoring, alternate collector, cache or BM25 change, and it does
not authorize D3-B implementation.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `409fb0fdf370bb4d4dade5ea507c6fa4518b5220` (merged PR 15I-D2-A, `D2A_SCORE_COST_LOW_PRIORITY`) |
| Protocol | `protocol_v1.json`, schema `pr15i-d3a-candidate-attribution-v1` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Arms | `A` pristine BASE `op=query`; `Q`/`P` one derivative binary, `P` uses `op=query_probe` |
| Lanes | Nine frozen PR15D warm lanes (10K/100K × absent/rare/medium/common + 100K common K10) |
| Tooling freeze | `tooling_manifest.json` (T0 identity required by `verify.py`) |

The diagnostic derivative is produced only by `patch_source.py`, is insertion
only, touches exactly six scratch paths, and is independently reversed to BASE
by `source_proof.py`. The derivative is never committed. `d3a_probe` exists only
in the scratch worktree.

The recorder schema is fixed at **25 stages** and **15 counters**, plus up to 32
fixed segment descriptors, two fixed FIRST/STEADY timing rows (parent plus seven
children) and two stratum counts. Candidate micro-samples are deterministic per
segment and suppressed for fewer than 512 scored candidates:

```text
if n < 512:                       no candidate micro-samples
else if i < 128:                  sample, stratum=FIRST
else if (i - 128) % 64 == 0:      sample, stratum=STEADY
else:                             do not sample
```

## Commands

`BASE_ROOT` and `SCRATCH_ROOT` are detached Git worktrees at BASE; the scratch
worktree is clean before materialization. All outputs are new directories under
`<tooling-root>/target/pr15i-d3a/`; existing paths are never reused.

```sh
python3 benchmarks/pr15i_d3a/run.py preflight \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/preflight/preflight.json

python3 benchmarks/pr15i_d3a/run.py build \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/builds

python3 benchmarks/pr15i_d3a/run.py aa \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/aa/d3a-base-aa-01 --idle-confirmed

python3 benchmarks/pr15i_d3a/verify.py \
  --base-root "$BASE_ROOT" \
  --campaign-dir target/pr15i-d3a/aa/d3a-base-aa-01

python3 benchmarks/pr15i_d3a/run.py campaign \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --campaign d3a-unbatched-01 \
  --out target/pr15i-d3a/paired/d3a-unbatched-01 --idle-confirmed

python3 benchmarks/pr15i_d3a/verify.py \
  --base-root "$BASE_ROOT" \
  --campaign-dir target/pr15i-d3a/paired/d3a-unbatched-01

# d3a-unbatched-02 runs only after campaign 01 qualifies, with no changes.
python3 benchmarks/pr15i_d3a/verify.py \
  --base-root "$BASE_ROOT" --aggregate \
  --series-root target/pr15i-d3a/paired \
  --control-dir target/pr15i-d3a/aa/d3a-base-aa-01

python3 benchmarks/pr15i_d3a/run.py archive \
  --campaign-dir target/pr15i-d3a/paired/d3a-unbatched-01 \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3a"
```

Exit codes: `0` success/verified, `2` invalid input, `3` blocked.

## Campaign contract

- `d3a-base-aa-01`: 4 blocks × 4 slots = 16 slots, arms `A1A2A2A1 / A2A1A1A2 /
  A1A2A2A1 / A2A1A1A2`; two independent BASE builds from the same canonical
  pristine worktree and two shared indexes. Every block/lane `A1/A2` ratio must
  be in `[0.80, 1.25]`, and the lower median of four block ratios in `[0.85, 1.15]`.
- `d3a-unbatched-01` / `-02`: 4 blocks × 6 slots = 24 slots, arm orders
  `AQPPQA / PQAAQP / QAPPAQ / PAQQAP`; 9 lanes, 5 warmups + 20 timed integer
  `engine_ns` samples per lane/slot, one pinned adapter process per
  `(arm, lane, slot)`, and two clear contention probes per slot.
- Q and P are the same absolute binary and SHA-256. Q must not expose probe
  fields; P writes `stage_ns`, `counts`, `segments`, `sample_strata_ns`,
  `sample_strata_count` and `segments_unsupported` only after `engine_ns` stops.
- Four index builds per paired campaign (A/10K, A/100K, QP/10K, QP/100K) with
  byte-identical A/QP digests and the frozen 100K LZ4 sentinels.

## Decision

The closed decision rule in `verify.py` is applied only after both qualified
campaigns and the qualified control. It produces one of
`D3A_CANDIDATE_HOTSPOT_LOCALIZED`, `D3A_INTERMEDIATE_MATERIALIZATION_PRIORITY`,
`D3A_CANDIDATE_STAGE_UNRESOLVED`, `D3A_NO_ACTIONABLE_HOTSPOT`, or
`D3A_MEASUREMENT_BLOCKED`. Every outcome is diagnostic; none authorizes an
optimization PR. A negative result is a successful measurement PR.
