# PR 9 Amendment 01 — adversarial review

For each invariant this names a plausible incorrect implementation and the
assertion that detects it.

## A1-I01 — exact-at-limit and one-over-limit revisions

- **Incorrect:** `revision = previous_revision.wrapping_add(1)` or resetting to 1
  at the limit. **Detected by:** A1-T01 asserts `MAX-1 → MAX`; A1-T02 asserts a
  new operation at `MAX` returns `IndexError::RevisionOverflow` for
  upsert, delete and insert-after-tombstone.
- **Incorrect:** the overflow path partially mutates the pending batch. **Detected
  by:** A1-T02 asserts `pending_mutations()` is unchanged after each failure.

## A1-I02 — overflow is inert and replay still works

- **Incorrect:** the token is inserted into the replay map before the checked
  addition, consuming it on overflow. **Detected by:** A1-T03 asserts a rejected
  new token at `MAX` is still usable for an unrelated key, and A1-T04 asserts the
  replay-entry count is unchanged.
- **Incorrect:** the idempotency lookup runs after revision allocation.
  **Detected by:** A1-T03 replays an exact token at `MAX` and expects the
  original revision, not overflow.

## A1-I03 — ambiguous `CURRENT` is not success

- **Incorrect:** `atomic_write` errors are mapped to success because the pointer
  now matches. **Detected by:** A1-T05/T06 assert `RecoveryRequired` and exactly
  one intercepted `CURRENT` publication.
- **Incorrect:** the writer clears its journal as if the commit succeeded.
  **Detected by:** A1-T07 asserts `pending_mutations()` still reflects the
  uncommitted operation after poisoning.

## A1-I04 — poisoned writer rejects every entry point

- **Incorrect:** only `commit` checks `poisoned`; `insert`/`refresh`/`compact`
  proceed. **Detected by:** A1-T07 calls every mutation/publication entry point
  and asserts `RecoveryRequired` without touching storage.
- **Incorrect:** the lock is released before the poisoned writer is dropped.
  **Detected by:** A1-T08 asserts a second `index.writer()` returns `WriterBusy`
  while the poisoned writer is alive.

## A1-I05 — pre-write failure preserves old authority

- **Incorrect:** a pre-write failure also poisons or advances the generation.
  **Detected by:** A1-T09 asserts the old generation is still `CURRENT` and a
  fresh open sees it; A1-T10 asserts exactly one revision and one replay entry
  after a single retry.
- **Incorrect:** a retry double-publishes the accepted operation. **Detected by:**
  A1-T10 asserts `state.replay_count() == 1` and a replay returns the original
  revision.

## A1-I06 — cancellation is bounded and inert

- **Incorrect:** cancellation is only checked once at entry. **Detected by:**
  A1-T12 (second segment), A1-T13 (unit hook inside postings), A1-T14 (columns),
  A1-T15 (before/after encode), A1-T16 (snapshot).
- **Incorrect:** cancellation publishes before returning `Cancelled`.
  **Detected by:** every stage test asserts `CURRENT` bytes and generation are
  byte-for-byte unchanged.

## A1-I07 — cancelled compaction leaves logical state untouched

- **Incorrect:** cancellation mutates the committed/replay state in place.
  **Detected by:** A1-T17 asserts generation, replay/revision semantics and the
  pinned-PIT results are unchanged, and that a retry is lossless.

## A1-I08 — no false `Cancelled` after publication begins

- **Incorrect:** a final `check()` after `atomic_write`. **Detected by:** A1-T18
  sets the flag from the `AfterPublishCheck` hook and asserts a successful
  `MergeOutcome` (the flag is observably set).

## A1-I09 — noncancelled compaction stays lossless

- **Incorrect:** the cancellation refactor drops the lossless merge path.
  **Detected by:** A1-T19 (plain vs flag equivalence) and A1-T20 (independent
  document-level oracle, indexed-not-stored phrase positions, stored fields,
  columns, `NOT` and BM25 equivalence).

## A1-I10 — no scope/wire-format leakage

- **Incorrect:** new feature/section ids or a remote dependency. **Detected by:**
  A1-T22 asserts `FEATURE_MUTATION_STATE == 0x0008` and
  `SectionKind::MutationState == 0x000F`; the diff audit confirms no
  `Cargo.toml`, `contract/*`, `objectstore`, or distributed changes.

## Residual risks

- Cancellation is cooperative, not a wall-clock deadline. A single codec call
  (`encode_stored`, `encode_columns`, `encode_postings_block`,
  `encode_field_norms`, `build_merged_segment`) is not interruptible. Those calls
  are bounded by `SegmentLimits`; no hard latency bound is claimed.
- The `MergeStage::AfterPublishCheck` observer is test-only and never checks the
  flag; production code has no post-publication cancellation check.
- A cancelled compaction may leave unreferenced content-addressed immutable
  objects installed before the final checkpoint. They are safe orphans retained
  for offline maintenance and are never referenced by `CURRENT`.
