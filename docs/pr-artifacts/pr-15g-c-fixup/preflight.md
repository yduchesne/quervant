# PR 15G-C fixup preflight

**Status:** preflight complete.
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**Local/remote HEAD:** `850e0f3ac193d4cb359be299e235986613819600`
**Accepted pre-C Arm A:** `018fdd768d0898d6709baeb8661998ee1a82947c`
**B carryover test commit:** `97d7ce1bc82c9903304371ce8b45074c3981adf5`
**Failed C control:** `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e`
**Umbrella PR:** #86

## Ancestry and provenance

- `018fdd7`, `97d7ce1`, `5ec886f` and `850e0f3` are ancestors of the current
  shared tip.
- `97d7ce1` is test-only relative to `018fdd7` (B carryover tests).
- Failed C reports under `docs/pr-artifacts/pr-15g-c/` are preserved and must not
  be rewritten.
- Prior exact-head CI run `41858331326` at `850e0f3` passed `rust`, `msrv` and
  `rustfs`; this does not imply performance acceptance.

## Frozen runner and inputs

- `benchmarks/pr15g_c/run.py` still pins Arm A `018fdd7`, nine lanes, 3 trials
  per arm, 5 warmups + 20 samples.
- Frozen PR15D corpus/adapter/oracle hashes remain unchanged.
- The fixup must use a fresh stage root and not overwrite the failed C campaign.

## Environment

Stable Rust 1.98.1, MSRV cargo 1.85.0, Python 3.12.3, cargo-llvm-cov 0.9.1,
native ext4 on WSL2. Pinned RustFS image present locally.

## B baseline tests

`gc_br01a–e` (5) and `gc_br02a/b` (2) are present and will be rerun unchanged.
