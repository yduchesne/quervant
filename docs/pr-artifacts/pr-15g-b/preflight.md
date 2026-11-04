# PR 15G-B preflight

**Status:** `GB_READY_FOR_SHARED_BRANCH_PREFLIGHT` — shared branch verified.
**Branch:** `dev/pr15g-a-retained-column-geometry` (all PR 15G phases remain on this branch).
**GB_BASE_SHA (frozen pre-B):** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`
**Local HEAD at preflight:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`
**Remote shared tip:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`
**Contextual `origin/main`:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (expected behind; not the B baseline)
**Worktree:** clean.

## Shared-branch and 15G-A verification

- Historical 15G-A implementation `9ddff6a79a7a9fa1932c5de7f37065252673397d` and documentation-only
  `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c` are ancestors of the shared tip.
- GitHub Actions run `41774735678` is `completed/success` for `head_sha=3329dd8…`
  on `dev/pr15g-a-retained-column-geometry` (verified through the public Actions API).
- Open umbrella PR: #86 `https://github.com/yduchesne/quervant/pull/86`.
- 15G-A performance qualification `P01–P04 PASS` is present at
  `docs/pr-artifacts/pr-15g-a/performance-qualification.md`.
- Shared tip contains:
  - `VerifiedSegmentState::column_geometry`;
  - `ColumnReader::from_validated_geometry` and borrowed `open_columns` dispatch;
  - metered candidate admission and `MetadataBudget`;
  - the 15G-A integrity/corruption/RustFS tests and runners.

Raw source-symbol log: `target/pr15g-b/preflight/source-symbols.log`.

## Context

The prior plan revision treated an unmerged `main` as a blocker. The revised
operator-approved plan explicitly replaces that rule: PR 15G-A is qualified on
the shared optimization branch and **does not need to merge to main** before B.
No branch creation, cherry-pick, rebase or main merge was performed.

## Source anchors revalidated on the shared tip

| Area | Symbol | Status |
|---|---|---|
| STORED encoder/decoder | `encode_stored`, `decode_stored_selected`, `decode_stored` | present, signatures match §2 |
| STORED validation | `decode_field_values_budgeted`, `skip_field_values_budgeted`, full `DecodeBudget` | present |
| DOC_KEYS | `encode_doc_keys`, `decode_doc_key_selected`, `decode_doc_keys` | present |
| Verified state | `VerifiedSegmentState`, `DecodedMetadata`, `try_build_cached`, PR 15G-A `column_geometry` | present |
| Metadata | `MetadataBudget`, `MetadataMeter`, `MetadataReservation`, `element_bytes`, `capacity_bytes` | present |
| Snapshot | `SlotState`, `acquire_reader`, `metadata_budget` witnesses | present |
| Byte reader | `position`, `len_prefixed_u16`, `bytes`, `expect_end` | present |

If a materially different signature is discovered while implementing, GB-D03
applies; no speculative adapter is authorized.

## Environment

- Stable `rustc 1.98.1` / `cargo 1.98.1`; MSRV `cargo 1.85.0`; Python 3.12.3;
  `cargo-llvm-cov 0.9.1`.
- Native `ext4` on WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`.
- Docker unavailable; Podman available. Pinned RustFS image present:
  `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`.
- Frozen PR 15F report SHA-256:
  `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096`.
- Frozen PR15D input hashes recorded in `target/pr15g-b/preflight/environment.txt`.

## Baseline focused tests (before B edits)

| Command | Result | Log |
|---|---|---|
| `cargo test -p quervant-core --lib segment::reader` | PASS — 9 passed | `target/pr15g-b/preflight/reader.log` |
| `cargo test -p quervant-core --lib segment::metadata` | PASS — 9 passed | `.../metadata.log` |
| `cargo test -p quervant-core --test pr15e_b1` | PASS — 17 passed | `.../pr15e_b1.log` |
| `cargo test -p quervant-core --test pr15g_a_column_geometry` | PASS — 6 passed | `.../pr15g_a_column_geometry.log` |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | PASS — 5 passed | `.../pr15c_a_segment_state.log` |
| `python3 -m unittest discover -s benchmarks/pr15g_a -p 'test_*.py' -v` | PASS — 16 passed | `.../pr15g_a_runner.log` |

## Counterexamples to preserve

1. A corrupted unselected STORED record must fail before any directory is
   published; fallback must return the original typed error.
2. A corrupted unselected DOC_KEYS entry must fail identically.
3. A directory built for one `VerifiedSegmentState` must never be reused for a
   refreshed generation, PIT or different bytes.
4. A budget rejection must leave zero reservation and use the full scanner,
   never publish a partial/uncharged directory.
5. A malformed/out-of-range selection must hit the legacy scanner before any
   optional directory construction so error precedence is unchanged.

The full invariant/test mapping and design verification are in
`design-verification.md`; implementation status is recorded in `execution.md`.
