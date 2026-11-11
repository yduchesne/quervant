# PR 15I-D1-F — durable evidence index

Published by the controller's mandatory `publish` gate to:

```text
$HOME/.local/share/quervant/benchmark-evidence/pr15i-d1-f/
```

Each archive was created exclusively, safely extracted into a fresh scratch
directory, every member re-hashed, and the independent verifier re-run before
the immutable `.sha256` sidecar was written.

| Archive | SHA-256 | Members | Campaign status |
|---|---|---:|---|
| `c2-base-aa-01.tar.gz` | `56f7b240d8e45ad5435a33572ed027ee0f87db21baa1961e775c2f2e1ee598fe` | 59 | `CONTROL_QUALIFIED` |
| `c2-base-01.tar.gz` | `a20269c4596b9655866838871e90857cfd68774345d00b4e8047c8c94699f140` | 61 | `CAMPAIGN_REJECTED` |

Archives contain the complete sealed `raw/` evidence (16 slot records with
warmup IDs, 20 samples per lane, two contention probes per slot, setup
manifests, `seal.json`), `authorization.json`, `manifest.json`, the sanitized
summary pair and the independent `verification.json` receipt, with
relative-path-only inventories. Replaceable build directories, generated
indexes and corpus are excluded; their file inventories, digests and byte
sentinels are sealed in `raw/setup/`.

## Not archived

`c2-base-aa-01.attempt-01-drift-noise` was a scientifically blocked A/A attempt
(one 10K rare within-block drift ratio 1.5104 > 1.50 and one 10K absent block
ratio 1.4385 > 1.25; it also recorded a binary SHA discrepancy between the two
different-worktree BASE builds). It is preserved only under
`target/pr15i-d1-f/` and is not evidence. The one authorized transient retry
used two independent builds of the same BASE tree (identical binaries) and is
the archived control.

`c2-base-02` does not exist: the first valid paired campaign failed the frozen
primary gate, and FDX-23 stops later campaigns.

## Historical C1 evidence

The original `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d1/` archives
and sidecars were not modified. Their integrity and the frozen D1 verifier
results are recorded in `c1-postmortem.md`.

## Retention risk

All archives live under the same WSL2 ext4 virtual disk as the repository.
This is **not** an off-host backup; a single disk loss could remove source and
evidence together. `.sha256` sidecars are immutable. Cleaning
`target/pr15i-d1-f/` must never touch the evidence root, and no historical D0/D1
evidence was deleted.
