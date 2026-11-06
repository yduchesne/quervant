# PR 15G-C preflight

**Status:** preflight complete; B carryover tests next.
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**GC_BASE_SHA:** `018fdd768d0898d6709baeb8661998ee1a82947c`
**Local/remote HEAD:** equal at preflight
**B measured code:** `4e7949ad12236a0feeee671c6221119b8a998cc7`
**Contextual `origin/main`:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc` (not the C baseline)
**Umbrella PR:** #86

## Prior-phase proof

- B measured implementation `4e7949a` is an ancestor of `018fdd7`.
- B closure diff is documentation-only.
- Exact-head Rust CI run `41790864564` at `018fdd7` completed successfully
  (`rust`, `msrv`, `rustfs`; Core remote and fault/crash steps success).
- B performance campaign is recorded in
  `docs/pr-artifacts/pr-15g-b/performance-qualification.md`.

## Environment

- Stable Rust 1.98.1; MSRV cargo 1.85.0; Python 3.12.3; cargo-llvm-cov 0.9.1.
- Native `ext4`, WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`.
- Pinned RustFS image present locally:
  `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`.
- Frozen PR15F report SHA unchanged:
  `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096`.

## C eligibility source anchors

- `search/unified.rs::single_term_postings_eligible` and `collect_mixed`.
- `search/execute.rs::evaluate_lexical_with`, `build_leaf_data`,
  `effective_live_examination_count`, `score_segment`.
- `search/score.rs::bm25` and `SnapshotStats`/`FieldStats`.
- `segment/postings.rs::PostingsReader::next_with`.
- Shared B offset directories are preserved.

## Planned adversarial cases

Large M vs K; invalid score for a nonwinner; tight candidate bytes/work/
scanned limits at exact/one-under; tied sort keys; two segments with duplicate
live keys; stale PIT; cancellation between passes; zero-live/empty postings;
batch retained slots; cursor first page plus legacy continuation.
