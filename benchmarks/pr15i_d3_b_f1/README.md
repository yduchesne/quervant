# PR 15I-D3-B-F1 — canonical-path requalification controller (frozen tooling)

**Status: prospective measurement tooling only.** This directory is an isolated
copy of the D3-B tooling with the canonical-build, provenance, host-attestation
and verifier-hardening changes of the approved F1 plan. `benchmarks/pr15i_d3_b/`
and all historical evidence are preserved byte-identically.

## What changed relative to D3-B v1

The candidate implementation is **not** modified. F1 repairs the A/A
build-identity contradiction: each campaign owns exactly one detached
`compile-source` worktree at one absolute path, and both arms are compiled from
that same path into independent target directories (`build/A`, `build/B`). For
A/B the same path switches from BASE to the immutable candidate commit only
after arm A is built. No cross-worktree compilation, binary copying, build flag,
`RUSTFLAGS`, `--remap-path-prefix`, toolchain change or source edit is allowed.

New sealed evidence:

- `raw/build-provenance.json`: both build events (ids, argv, cwd, manifest and
  target paths, pre/post checkout and source hashes, toolchain, environment
  fingerprint, exit status, binary hashes/sizes) plus the source transition and
  pre/post-timing binary snapshots.
- `raw/host-attestation.json`: kernel/CPU facts, allowed CPUs, controller
  affinity immediately after pinning, per-path `findmnt` and harness filesystem
  classifications, and the recomputable host fingerprint.
- Every lane record carries the observed adapter PID and settled
  `/proc/<pid>/status` CPU lists before warmup and after timed sample 20; every
  slot carries controller affinity before and after the slot.

The independent verifier (`verify.py`, which never imports the controller)
rehashes the frozen PR15D inputs and adapter lock from immutable Git blobs for
each declared revision, validates the provenance and host/affinity evidence,
recomputes every median, block, drift, A/A and gate decision, and enforces the
control-succession history.

## Frozen identities

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` (`MAIN_PR97_BASE`) |
| Candidate | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Protocol | `protocol_v1.json` (`pr15i-d3b-f1-canonical-build-v1`) |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Adapter lock SHA-256 | `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121` |
| 100K committed index bytes | 15,747,551 |
| 100K STORED-section bytes | 1,661,455 |

## Campaigns and schedules

- `d3bf1-base-aa-01` — mandatory same-source A/A control: two real builds of
  BASE from one canonical path, byte-identical binaries required.
- `d3bf1-base-aa-02` — permitted only once, only after a structurally valid
  `aa-01` failed a numerical A/A or drift threshold. A structural failure in
  `aa-01` forbids any retry.
- `d3bf1-base-01`, `d3bf1-base-02` — paired campaigns against one immutable
  candidate commit. Campaign 02 runs only if campaign 01 is structurally
  qualified and passes every frozen gate.

Four blocks × four slots (`ABBA / BAAB / BAAB / ABBA`), nine warm lanes per
slot, five warmups + twenty timed integer `engine_ns` samples per lane, one
fresh pinned adapter process per `(arm, lane, slot)`, two clear contention
probes per slot. Controller on the second allowed CPU, adapters on the first,
with sealed `/proc` observations.

## Frozen D3B gates

| Gate | Requirement |
|---|---|
| `D3B-P00` | All structural/provenance/host/affinity/oracle/index/contention/drift/seal/verifier checks qualify, exact 16×9×20 shape |
| `D3B-P01` | 100K common/K100: lower-median `d >= +2,000,000 ns` and ≥3/4 blocks `d >= 0` |
| `D3B-P02` | 100K medium/K100: lower-median `d >= +1,000,000 ns` and ≥3/4 blocks `d >= 0` |
| `D3B-P03` | 100K common/K10: median `d >= −500,000 ns`; every block `d >= −1,500,000 ns`; median `B/A <= 1.05` |
| `D3B-P04` | 10K/100K absent and rare: each median `B/A <= 1.15`, every block `B/A <= 1.50` |
| `D3B-P05` | 10K common/K100 and medium/K100: median `d > −2,000,000 ns`; every block `d >= −3,000,000 ns` |
| `D3B-P06` | Both 100K K100: median `d > −500,000 ns`; every block `d >= −1,500,000 ns` |
| `D3B-P07` | Distinct A/B source and binary identity, exact oracle, byte-identical index digests/sentinels, complete sealed evidence and provenance |
| `D3B-P08` | Both paired campaigns independently meet P00–P07; no pooling |

A/A: every lane's four-block lower-median `B/A` in `[0.85, 1.15]`, every block in
`[0.80, 1.25]`; exactly the two 10K absent/rare lanes may tolerate one soft
outlier each inside hard `[0.67, 1.50]`; no median exception. Drift caps 1.25×
(100K medium/common) and 1.50× (others) for both arms.

## Tooling freeze

`tooling_manifest.json` records the SHA-256 of every regular file in this
directory except itself. Both the controller and the independent verifier
require an exact file-set match (no symlinks, no extra, missing or changed
members) before any official run and during verification. After the first
official timed slot, no F1 tooling change is permitted.

## CLI

All official outputs must be absolute, non-symlinked and strictly beneath
`<repo>/target/pr15i-d3-b/fixup-f1/`. Existing paths are never overwritten.
Required SHA values are full 40-hex; source trees must be detached, clean Git
worktrees. They are **identity inputs only** — never compile paths.

```sh
BASE=39dbd9f571a58bea8cc03d5a406533298e809bfe
CAND=48d9abf3eeefbccb480d89eac95f6e6911e078d5
ROOT=$(git rev-parse --show-toplevel)
F1="$ROOT/target/pr15i-d3-b/fixup-f1"

# non-timed reproducibility proof (never an A/A control)
python3 benchmarks/pr15i_d3_b_f1/run.py dry-proof \
  --candidate-sha "$CAND" --out "$F1/dry-proof-01"

python3 benchmarks/pr15i_d3_b_f1/run.py preflight \
  --base-tree "$F1/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F1/sources/candidate" --candidate-sha "$CAND" \
  --out "$F1/preflight-01.json"

python3 benchmarks/pr15i_d3_b_f1/run.py paired \
  --base-tree "$F1/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F1/sources/control-base" --candidate-sha "$BASE" \
  --campaign d3bf1-base-aa-01 \
  --out "$F1/d3bf1-base-aa-01" --idle-confirmed

python3 benchmarks/pr15i_d3_b_f1/verify.py --campaign-dir "$F1/d3bf1-base-aa-01"

python3 benchmarks/pr15i_d3_b_f1/run.py paired \
  --base-tree "$F1/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F1/sources/candidate" --candidate-sha "$CAND" \
  --campaign d3bf1-base-01 \
  --out "$F1/d3bf1-base-01" --idle-confirmed

python3 benchmarks/pr15i_d3_b_f1/verify.py --campaign-dir "$F1/d3bf1-base-01"
python3 benchmarks/pr15i_d3_b_f1/verify.py --series-root "$F1" --comparison d3bf1-base

python3 benchmarks/pr15i_d3_b_f1/run.py publish \
  --campaign-dir "$F1/d3bf1-base-01" \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1"
```

Exit codes: `0` success/verified, `2` rejected input, `3` blocked or
verification failure. A qualified performance rejection still verifies and
publishes; `verification=PASS` never means the performance gates passed.
