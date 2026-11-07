# PR 15I-A — source preflight

Recorded for the `dev/pr15i-a-mutation` implementation branch.

## Verified identities

| Item | Value |
|---|---|
| Post-PR15I-0 `main` / A arm | `888e819d85f0cde62a5040919ac5c96feca52f1f` |
| PR 15I-0 merge source (ancestry requirement) | `8e769e692e9eb39e8fd56addb67c3b9ca3862b56` |
| `origin/main` at preflight | `888e819d85f0cde62a5040919ac5c96feca52f1f` |
| Preflight working tree | clean (`git status --porcelain` empty) |
| Feature `0x000C` | free in `SUPPORTED_FEATURES`; `SectionKind::SegmentMeta` uses the same numeric value in a separate namespace and is unchanged |
| Baseline branch | created from the verified post-15I-0 `main`; the PR 15I-0 branch is not reused |

Commands executed:

```sh
git fetch origin main
BASE="$(git rev-parse origin/main)"                     # 888e819d85f0...
git merge-base --is-ancestor 8e769e692e9eb39e8fd56addb67c3b9ca3862b56 "$BASE"
git status --porcelain=v1
git grep -n 'FEATURE_MUTATION_STATE_V2\|SUPPORTED_FEATURES' -- crates/quervant-core/src/segment/format.rs
git grep -n 'encode_with_mode\|version_2_active' -- crates/quervant-core/src/index
```

Results: PR 15I-0 is an ancestor of `main`; tree clean; `FEATURE_MUTATION_STATE_V2 = 0x000B`;
`0x000C` absent from `SUPPORTED_FEATURES`; the two production write sites are
`writer.rs` (prospective admission and commit) plus `merge.rs` (compaction).
There is no post-PR15I-0 production diff relative to `8e769e6` outside
unrelated documentation, so `A-01`/`A-02` apply.

## Historical acceptance sentinels reproduced on this host

A fresh 100K index built from `888e819` with the frozen PR15D corpus and the
unchanged PR15D adapter produced exactly:

| Component | Bytes |
|---|---:|
| Mutation-state sidecar | **9,600,180** |
| Segment | 21,364,026 |
| Manifest | 636 |
| `CURRENT` | 183 |
| **Total committed index** | **30,965,025** |

These match the PR 15I-0 measured sentinels exactly, so `A-24`
(`BASELINE_MISMATCH`) does not apply. The historical latency numbers remain
historical; acceptance uses fresh paired A/B samples only.

## Frozen inputs

- PR15D corpus generator/oracle and adapter hashes are enforced by the frozen
  PR15E-B1 `FROZEN_FILES` map at campaign start.
- PR 15I-0 probe, protocol and reports are read-only and not imported.

## Environment

- Linux (WSL2), native ext4 root filesystem, 12 CPUs, 31 GiB RAM.
- Toolchains: stable `1.98.1` and MSRV `1.85.0`; Python 3.12.
- Pinned RustFS image `rustfs/rustfs@sha256:1803faef...6a3c` available locally
  through `podman`.
