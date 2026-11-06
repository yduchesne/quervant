# PR 15G-E preflight and design verification

**Starting HEAD:** `7627cd63a74b9e0eb7aad0a75967c7c3c2baa569`
**A+B source:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**E implementation commit:** `62d35c262fa667673ee6d8701ca9ef75daf17a53`
**E rollback commit:** `e2bdf48cd88f6780e6c833001fec537ba218c3d4`
**Main:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (ancestor)

The implementation followed the locked E-AD decisions: segment-only minor 1,
feature `0x000C`, sections `0x0012`/`0x0013`, canonical 50+8*(N+1) directories,
source SHA binding, and scan-backed in-process certification before selected
access. Manifests and mutation-state remain minor 0.

Counterexamples were exercised in codec, format and reader tests: truncated or
trailing directories, bad counts/lengths/digests, non-monotone boundaries,
wrong interior boundary with valid outer digests, allocation/entry limits,
missing/feature mismatches, and legacy 1.0 containers containing E sections.
The reader does not treat the persisted directory as a semantic receipt.

No remote range-read path was added. All existing local/RustFS object
materialization remains whole-object and digest-verified.
