# PR 7 Amendment 02 review

**Scope:** candidate reservation lifetimes and segment-to-global batch transfer.
**Branch:** `dev/lexical-postings`; starting commit `161cf5e` (Amendment 01).
**Disposition:** amend the existing PR 7 branch; not a separate roadmap PR.

## Corrections delivered

| Item | Defect | Fix | Files |
|---|---|---|---|
| Defect 1 | Phrase scratch retained until segment end | `build_phrase` releases scratch after `drop(distinct)`, before sibling leaves | `search/execute.rs` |
| Defect 2 | Result batch uncharged between segment return and global merge | `execute_segment` transfers the batch to `global_bytes` before `finish()`/return; caller drains without re-reserving | `search/execute.rs` |
| Defect 3 | Implicit bulk release inflated the per-segment peak | Explicit drop/release for `live_set`, `matches`, `leaf_data`, `scored`; `finish` verifies zero | `search/execute.rs` |

## Invariant evidence

- **INV-A2-01/05:** `budget_tests::a2_01_*`, `a2_04_*`, `a2_05_*` prove atomic
  transfer, rejection atomicity and the combined segment/global bound. The
  end-to-end A2-01 boundary is not distinguishable because segment-charge checks
  dominate; this is the plan's documented feasibility exception and is covered by
  the private unit tests.
- **INV-A2-02/06:** `a2_03`, `a2_10` (per-segment peak reset), `a2_05`.
- **INV-A2-03:** `a2_02` — two sequential phrase leaves; **fails on `161cf5e`**,
  passes after.
- **INV-A2-04:** `a2_08` (Boolean set algebra/peaks), `a2_10` (implicit bulk
  release) — **fails on `161cf5e`**, passes after.
- **INV-A2-07/08:** `a2_09`, `a2_11`, `a2_12` plus all existing U/I/F/P/S suites.

## Pre-fix regression evidence

A detached worktree at `161cf5e` running the same
`crates/quervant-core/tests/pr07_amendment02.rs` produced:

```text
test a2_02_sequential_phrase_scratch_is_released ... FAILED
test a2_10_many_small_segments_reset_peak ... FAILED
test a2_03_multi_segment_batch_boundaries ... ok
test a2_09_cancellation_and_work_exhaustion_recover ... ok
test a2_11_memory_and_fs_agree ... ok
test a2_12_seeded_differential_membership ... ok
```

After the fix, all six pass on Rust 1.98.1 and 1.85.0.

## Execution evidence

- `cargo test --workspace --all-targets`: 991 passed, 7 ignored, 0 failed on both
  toolchains.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets
  --all-features -- -D warnings`, `cargo doc --workspace --no-deps`: clean on both.
- `cargo llvm-cov --workspace --all-features --fail-under-lines 85`: 91.97% line.
- `cargo run --release -p quervant-core --example pr07_bench`: correctness oracle
  passes; latencies within noise of Amendment 01.

## Reviewer checklist status

- [x] No output batch uncharged between segment and global ownership.
- [x] No double charging of keys transferred into the global map.
- [x] Phrase scratch released only after drop, before sibling phrase processing.
- [x] `live_set`, `leaf_data`, `matches`, `scored` and output results have
      explicit ownership and release/transfer sites.
- [x] Atomic transfer and rejection tested at exact/over limits.
- [x] Scoring, phrase, top-K and snapshot semantics unchanged.
- [x] Stable/MSRV gates, coverage and benchmark executed and recorded.
- [x] Adversarial self-review and residual risks documented.
- [x] No public API, codec, format, remote/distributed or roadmap scope expansion.
- [ ] Independent review before merge (pending).

## Residual risks

Logical accounting is not exact RSS; `match_phrase` internal scratch vectors are
not individually charged; O(indexed postings) field-length work remains; no
RustFS/WAND/streaming. No new on-disk format.
