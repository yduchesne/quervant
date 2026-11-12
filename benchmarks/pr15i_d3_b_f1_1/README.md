# PR 15I-D3-B-F1.1 — fail-closed verifier repair and requalification tooling

**Status: prospective measurement tooling only.** This directory is an isolated
copy of the F1 tooling carrying exactly two authorized repairs plus a synthetic
pre-freeze rehearsal harness. `benchmarks/pr15i_d3_b/`,
`benchmarks/pr15i_d3_b_f1/`, the candidate source and every historical evidence
file are preserved byte-identically.

## What changed relative to F1

The failed F1 control was not a build or performance failure: the canonical-path
compiler produced byte-identical A/A binaries. Its independent verifier could
not accept the sealed evidence because of two frozen-tooling defects. F1.1
repairs **only** those two defects and adds a full-verifier rehearsal so no
further acquisition is risked on an untested later verifier stage.

1. **Root-only `compile-source` inventory exclusion (`verify.py`).** The
   campaign-local `compile-source/` worktree mandated by the canonical-build
   design is excluded from the evidence inventory **only at the campaign root**.
   A root `compile-source` symlink or ordinary file is rejected, sealing any
   `compile-source/*` path is rejected, nested `compile-source` names are still
   detected as unlisted, and archives without the checkout remain verifiable.
2. **One campaign host-fingerprint contract (`run.py`).**
   `preflight_host_fingerprint(environment)` keeps F1's preflight inputs
   (`allowed_cpus`). `host_fingerprint(attestation)` uses only sealed
   attestation fields and takes the CPU set from
   `allowed_cpus_before_pin`, serialized under the canonical key
   `allowed_cpus`, with strict validation (sorted, unique, non-negative,
   non-boolean, pinned CPUs inside the list, exactly seven filesystem roles).
   The independent verifier keeps its own implementation and must produce the
   identical digest.

New harness:

- `replay.py` copies only the blocked F1 control's sealed members, transforms
  identity/attestation metadata into the F1.1 namespace, reseals, and invokes
  the real F1.1 verifier as an external process for one positive and fifteen
  negative/invariance cases. Its output is explicitly
  `SYNTHETIC_REHEARSAL_ONLY` and can never be published.
- `publish` refuses `rehearsal_only` fixtures and any path containing a
  `rehearsal` / `rehearsal-cases` component with
  `D3B_REHEARSAL_PUBLISH_FORBIDDEN`.

## Frozen identities and prospective namespace

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Protocol | `protocol_v1.json` (schema `pr15i-d3b-f1-1-canonical-build-v1`) |
| Comparison key | `d3bf11-base` |
| Target root | `target/pr15i-d3-b/fixup-f1-1/` |
| Evidence root | `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-1/` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Adapter lock SHA-256 | `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121` |
| 100K committed index bytes | 15,747,551 |
| 100K STORED-section bytes | 1,661,455 |

The F1.1 protocol differs from F1 in exactly six top-level keys: `schema`,
`study_type`, the renamed `comparisons` key, `tooling_directory`,
`target_subroot` and `evidence_root_relative`. Gates, A/A policy, drift, lanes,
schedule, corpus/hit counts, source policy and index sentinels are recursively
identical.

## Campaigns and gates

Official names only: `d3bf11-base-aa-01`, conditional numerical retry
`d3bf11-base-aa-02`, and paired `d3bf11-base-01` / `d3bf11-base-02`. Four blocks
× four slots (`ABBA / BAAB / BAAB / ABBA`), nine warm lanes, five warmups + 20
timed integer samples per lane/slot, one pinned adapter process per
`(arm, lane, slot)`, two clear contention probes per slot.

`D3B-P01`–`D3B-P06` numeric thresholds, `D3B-P07` structure and `D3B-P08`
two-campaign independence are **unchanged** from F1. The A/A policy is
unchanged: every lane's four-block lower-median `B/A` in `[0.85, 1.15]`, every
block in `[0.80, 1.25]`, with at most one soft outlier per 10K absent/rare lane
inside hard `[0.67, 1.50]`, and no median exception. Drift caps remain 1.25×
(100K medium/common) and 1.50× (others).

## Tooling freeze

`tooling_manifest.json` records the SHA-256 of every regular file in this
directory except itself. Controller and verifier require an exact file-set
match (no symlinks, no extra or missing members) before every official run and
during verification. After T2 no F1.1 tooling change is permitted.

## CLI

All official outputs are absolute, non-symlinked and strictly beneath
`target/pr15i-d3-b/fixup-f1-1/`; existing paths are never overwritten. Source
worktrees are identity inputs only and are never compile paths.

```sh
BASE=39dbd9f571a58bea8cc03d5a406533298e809bfe
CAND=48d9abf3eeefbccb480d89eac95f6e6911e078d5
ROOT=$(git rev-parse --show-toplevel)
F11="$ROOT/target/pr15i-d3-b/fixup-f1-1"
TOOL=benchmarks/pr15i_d3_b_f1_1

# pre-freeze synthetic full-verifier rehearsal (never evidence)
python3 "$TOOL/replay.py" \
  --historical-control "$ROOT/target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01" \
  --out "$F11/rehearsal/round-01/replay-report.json"

python3 "$TOOL/run.py" preflight \
  --base-tree "$F11/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F11/sources/candidate" --candidate-sha "$CAND" \
  --out "$F11/preflight-01.json"

python3 "$TOOL/run.py" paired \
  --base-tree "$F11/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F11/sources/control-base" --candidate-sha "$BASE" \
  --campaign d3bf11-base-aa-01 \
  --out "$F11/d3bf11-base-aa-01" --idle-confirmed

python3 "$TOOL/verify.py" --campaign-dir "$F11/d3bf11-base-aa-01"

python3 "$TOOL/run.py" paired \
  --base-tree "$F11/sources/base" --base-sha "$BASE" \
  --candidate-tree "$F11/sources/candidate" --candidate-sha "$CAND" \
  --campaign d3bf11-base-01 \
  --out "$F11/d3bf11-base-01" --idle-confirmed

python3 "$TOOL/verify.py" --campaign-dir "$F11/d3bf11-base-01"
python3 "$TOOL/verify.py" --series-root "$F11" --comparison d3bf11-base

python3 "$TOOL/run.py" publish \
  --campaign-dir "$F11/d3bf11-base-01" \
  --evidence-root "$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-1"
```

Exit codes: `0` success/verified, `2` rejected input, `3` blocked or
verification failure. A performance-rejected campaign still verifies and
publishes; `verification=PASS` never means the performance gates passed.
