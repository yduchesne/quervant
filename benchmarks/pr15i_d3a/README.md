# PR 15I-D3-A-F — five-run candidate-attribution qualification fixup

**Measurement-only fixup.** This directory contains the frozen diagnostic
tooling for PR 15I-D3-A-F. It ships no production search, scorer, segment-format,
API, BM25, PR15D or dependency change. It does not authorize an optimization PR.

## History and scope

The original PR 15I-D3-A ended `D3A_MEASUREMENT_BLOCKED`: two T0b A/A controls
each had one soft-range outlier in a short 10K absent/rare lane. The historical
T0 `2576bba` and T0b `fd21658` tooling, evidence and reports are preserved
unchanged and are never used for v2 qualification.

This forward-only fixup introduces:

- a **prospectively frozen** v2 control policy allowing at most one soft
  outlier (`[0.80, 1.25]`) per exactly these two lanes:
  `pr15d_v1/10000/absent/k100` and `pr15d_v1/10000/rare/k100`; hard
  `[0.67, 1.50]` and the `[0.85, 1.15]` median gate always apply;
- isolated build namespaces for control attempts (`fixup-f-control-01`,
  `fixup-f-control-02`) and one shared paired-series namespace
  (`fixup-f-series`);
- a sealed `raw/host-quiescence.json` precheck per run;
- **five** independently executed 24-slot A/Q/P campaigns, each with four fresh
  index builds, 4,320 timed queries and 1,080 warmups;
- five run-level observations per lane/area (not 800 pooled queries), with
  median/MAD/min/max and a 4-of-5 persistence rule;
- a seven-area diagnostic mapping that keeps sampled proxies separate from
  directly timed disjoint intervals.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `409fb0fdf370bb4d4dade5ea507c6fa4518b5220` |
| Historical T0 | `2576bbad088a7a16d1b84c4dc4a4b450e80b06e1` (superseded) |
| Historical T0b | `fd216580374cc0f30a9ca84b44f7b8a7cd760a08` (superseded) |
| Current v2 freeze | T0c (assigned only after the final tooling commit) |
| Protocol | `protocol_v2.json`, schema `pr15i-d3a-candidate-attribution-fixup-v2` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Arms | `A` pristine BASE `op=query`; `Q`/`P` one derivative binary, `P` uses `op=query_probe` |
| Lanes | Nine frozen PR15D warm lanes |
| Tooling freeze | `tooling_manifest_v2.json` |

The recorder, derivative, six-path insertion inventory, 25 stages, 15 counters,
sampling formulas and executable fingerprint
`62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60`
are unchanged from D3-A. `protocol_v1.json` and `tooling_manifest.json` remain
bit-identical historical artifacts.

## Campaigns

| Run | Name | Slots | Timed | Warmups | Probes | Index builds |
|---|---|---:|---:|---:|---:|---:|
| Control 01 | `d3af-base-aa-01` | 16 | 2,880 | 720 | 32 | 2 |
| Control 02 (only if 01 rejected/archived) | `d3af-base-aa-02` | 16 | 2,880 | 720 | 32 | 2 |
| Paired 01–05 | `d3af-unbatched-0N` | 24 each | 4,320 each | 1,080 each | 48 each | 4 each |

All five paired runs use the same measured A/QP binaries built once under
`fixup-f-series`. Each run contains all nine lanes in the frozen order and the
original `AQPPQA / PQAAQP / QAPPAQ / PAQQAP` arm schedule. No sixth run, no
selective slot retry and no pooled-query inference.

## Commands

`BASE_ROOT` and `SCRATCH_ROOT` are fresh detached worktrees at BASE under
`target/pr15i-d3a/fixup-f/sources/`. All v2 outputs live under
`target/pr15i-d3a/fixup-f/`.

```sh
python3 benchmarks/pr15i_d3a/run.py preflight \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/fixup-f/preflight/preflight.json

python3 benchmarks/pr15i_d3a/run.py build \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/fixup-f/builds

python3 benchmarks/pr15i_d3a/run.py aa --attempt 01 \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/fixup-f/aa/d3af-base-aa-01 --idle-confirmed

python3 benchmarks/pr15i_d3a/verify.py --base-root "$BASE_ROOT" \
  --campaign-dir target/pr15i-d3a/fixup-f/aa/d3af-base-aa-01

# Only after control 01 is independently NOT_QUALIFIED and archived:
python3 benchmarks/pr15i_d3a/run.py aa --attempt 02 \
  --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
  --out target/pr15i-d3a/fixup-f/aa/d3af-base-aa-02 --idle-confirmed

for n in 01 02 03 04 05; do
  python3 benchmarks/pr15i_d3a/run.py campaign \
    --base-root "$BASE_ROOT" --scratch-root "$SCRATCH_ROOT" \
    --campaign "d3af-unbatched-$n" \
    --out "target/pr15i-d3a/fixup-f/paired/d3af-unbatched-$n" \
    --idle-confirmed
  python3 benchmarks/pr15i_d3a/verify.py --base-root "$BASE_ROOT" \
    --campaign-dir "target/pr15i-d3a/fixup-f/paired/d3af-unbatched-$n"
done

python3 benchmarks/pr15i_d3a/verify.py --aggregate \
  --base-root "$BASE_ROOT" \
  --series-root target/pr15i-d3a/fixup-f/paired \
  --control-dir target/pr15i-d3a/fixup-f/aa/<qualified-v2-control>

python3 benchmarks/pr15i_d3a/run.py archive \
  --campaign-dir target/pr15i-d3a/fixup-f/paired/d3af-unbatched-01 \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3a/fixup-f"
```

Exit codes: `0` success/verified, `2` invalid input, `3` blocked.

## Control policy (v2 only)

For every lane, compute the four block A1/A2 ratios exactly as before.

1. Any ratio outside `[0.67, 1.50]` fails `CONTROL_HARD_OUTLIER`.
2. A lane median outside `[0.85, 1.15]` fails `CONTROL_LOWER_MEDIAN`.
3. Only `pr15d_v1/10000/absent/k100` and `pr15d_v1/10000/rare/k100` may
   tolerate exactly **one** ratio outside `[0.80, 1.25]`; it is recorded as
   `CONTROL_SOFT_OUTLIER` in separate metadata and remains visible in raw
   blocks.
4. Every other lane tolerates zero soft outliers. Two soft outliers in one
   exempt lane fail.

The independent verifier recomputes the policy from sealed slots and rejects
tampered tolerated-outlier metadata.

## Decision

The five-run rule keeps the original absolute/share/dominance thresholds and
adds a predeclared 4-of-5 persistence gate. The independent verifier writes
`independent-aggregate-v2.json`, `independent-aggregate-v2.md` and
`five-run-areas-v2.json` under the series root. It returns one of
`D3A_CANDIDATE_HOTSPOT_LOCALIZED`, `D3A_INTERMEDIATE_MATERIALIZATION_PRIORITY`,
`D3A_CANDIDATE_STAGE_UNRESOLVED`, `D3A_NO_ACTIONABLE_HOTSPOT` or
`D3A_MEASUREMENT_BLOCKED`. No outcome authorizes implementation.
