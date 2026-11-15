# PR 15I-D3-B — durable evidence index

Published by the controller's mandatory `publish` gate to:

```text
$HOME/.local/share/quervant/benchmark-evidence/pr15i-d3-b/
```

Each archive is created exclusively, safely extracted into a fresh scratch
directory, every member re-hashed against the sidecar inventory, and the
independent verifier re-run before the immutable `.sha256` sidecar is written.

| Archive | SHA-256 | Members | Campaign status |
|---|---|---:|---|
| `d3b-base-aa-01.tar.gz` | `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc` | 59 | `MEASUREMENT_BLOCKED` (structural A/A binary mismatch; numerical A/A and drift passed) |

The archive contains the complete sealed `raw/` evidence (16 slot records with
warmup IDs, 20 samples per lane, two contention probes per slot, setup
manifests, `seal.json`), `authorization.json`, `manifest.json`, the sanitized
summary pair and the independent `verification.json` receipt, with
relative-path-only inventories. Replaceable build directories, generated
indexes and corpus are excluded; their file inventories, digests and byte
sentinels are sealed in `raw/setup/`.

Round-trip check performed after publication: 59 members extracted, 59
re-hashed, 0 mismatches, no absolute or traversal member names.

## Not present

`d3b-base-01` and `d3b-base-02` do not exist: the mandatory A/A control was
structurally invalid, and `DBX-31` stops the series before any paired campaign.
`d3b-base-aa-02` does not exist: the retry rule (`DBX-30`) is limited to a
purely numerical A/A stability failure.

## Local scratch (not evidence)

`target/pr15i-d3-b/` holds the pinned detached worktrees
(`sources/base`, `sources/candidate`, `sources/control-base`), the preflight
record and the sealed control attempt. `target/` is disposable and outside Git;
the archive and sidecar are the durable copy (`SAME_DISK_ONLY`).

## Historical evidence

The D3-A-F2 attribution study, the D1-C1 rejection and the D1-F C2 rejection
remain unchanged in `docs/pr-artifacts/` and their own evidence roots. They are
historical context only and were not used as acceptance gates or as substitutes
for D3-B measurement.
