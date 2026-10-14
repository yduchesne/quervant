# PR 9 Amendment 01 — implementation report

**Base:** `950583c43ea11773e59971e3e330064bd7f67c14` (committed original PR 9),
on top of `main` at `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`.
**Branch:** `dev/stable-key-mutations` (amendment changes uncommitted at report
time). **Scope:** T06 (revision overflow), T30 (ambiguous `CURRENT`
publication), T35 (cooperative compaction cancellation).

## Production changes

### A — revision overflow

No production ordering change was required. The existing `IndexWriter::apply`
already performs replay lookup, live-state validation, `checked_add(1)` and
budget preflight before mutating the journal or replay ledger. The amendment adds
a valid near-`u64::MAX` fixture built from real production primitives
(`MutationStateV1::encode`, content digest, manifest v2, `CURRENT`) and tests
A1-T01–T04.

### B — ambiguous `CURRENT`

- Only change: `IndexWriter::poison` was removed and the shared
  `IndexWriter::reconcile_publication` helper was added so compaction uses the
  same reconciliation contract as `commit` (pre-write failure → retryable
  storage error with old authority; write-then-error → poison +
  `RecoveryRequired`). `commit` behavior is unchanged.
- Tests A1-T05–T10 use a deterministic delegating `FaultyCurrentDirectory`
  wrapper around real `MemoryDirectory` and real `FsDirectory` with
  `FailBeforeWriteOnce` / `WriteThenFailOnce` modes and an interception counter.
  Every writer mutation/publication entry point already began with
  `ensure_writable()`; A1-T07 verifies them.

### C — compaction cancellation

- `IndexError::Cancelled` added.
- `IndexWriter::compact()` now delegates to the new
  `IndexWriter::compact_with_cancel(&AtomicBool)` using a never-cancelled
  static; `compact_with_cancel` reuses the same `MergeOutcome` type.
- `merge::compact(writer, cancelled)` now threads a private
  `MergeCancellation`, which polls the caller flag at entry, on each
  `stage(...)` phase transition, and every `CANCELLATION_CHECK_INTERVAL = 256`
  logical units (checked counter arithmetic; overflow fails with
  `ResourceLimit`).
- Checkpoints were inserted at: entry; before each source segment decode; the
  live-pointer mapping loop; stored/column field remapping; legacy norm
  reconstruction; the postings/positions loop (per dictionary entry, per
  posting); revisions; time/geo bounds; before and after output encoding;
  candidate-state/snapshot construction; before state/manifest installation; and
  a final prepublication checkpoint immediately before the `CURRENT`
  `atomic_write`.
- `visibility::build_masks_from_readers_cancellable` adds a per-row check for the
  source-mask build; the existing `build_masks_from_readers` delegates with
  `NeverCancel`, so `refresh`/`commit` signatures are unchanged.
- `MergeStage`/thread-local stage and unit hooks are `#[cfg(test)]`-only
  observers. `observe_after_publish_check` can flip the flag after the final
  checkpoint but never checks it, so a published generation is never reported as
  `Cancelled`.
- Compaction builds all candidate bytes in scratch state and swaps
  writer-local `committed`/`published`/state only after successful publication
  (`install_compacted`). `CURRENT` remains the sole commit point.

## Explicit non-goals

No remote storage, cross-process GC, automatic destructive reclamation,
background merge scheduler, WAL, mutation-format redesign, new dependency, or
wire-format change. The locked `contract/*` mutation semantics are unchanged.

## Test additions

27 new in-crate tests:

- `src/index/amendment01.rs`: A1-T01–T22 (25 tests, including the FsDirectory and
  compaction-publication variants).
- `src/index/merge.rs` `#[cfg(test)] mod tests`: 2 `MergeCancellation`
  boundary/overflow tests (A1-T21).

See [`amendment-01-test-traceability.md`](amendment-01-test-traceability.md).
