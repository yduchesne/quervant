# PR 6 adversarial review

> Baseline `569f4a48f98e2f97d55686c5440588889fc66233`. This review names plausible
> broken implementations and the concrete test that distinguishes each. Tests
> were executed (see `validation-report.md`).

## 1. Durable-commit and recovery

| Broken implementation | Why it is plausible | Distinguishing test |
|---|---|---|
| Publish `CURRENT` before segments/manifest are synced | "Readers can discover the generation first." | F01–F05: segment/manifest failures must leave no `CURRENT`; reopen sees `NotInitialized`. |
| Acknowledge a commit after `atomic_write` returns an error | Cache the error but proceed | F03/F04/F05b/F05c assert the old generation/no generation remains and the pending batch is retained. |
| Treat a successful read-back after a post-rename sync error as durable | "If we can read it, it is committed." | F07 returns `RecoveryRequired` even though the new pointer is visible; F16 returns `RecoveryRequired` when read-back itself fails. |
| Retry a new generation after an indeterminate outcome | Hide the ambiguity | F07 and F16 then reject further writes with `RecoveryRequired` until reopen. |
| Select the highest manifest found by `list` | "Robust fallback." | I04 writes an orphan generation-3 manifest; reopen stays at generation 1 and only doc `a`. |
| Fall back to an older valid generation when `CURRENT`/manifest is corrupt | "Availability over strictness." | U06, F08–F11 return typed errors and never silently serve stale data. |
| Overwrite an existing content-addressed object on retry | "The bytes should be identical anyway." | F12 returns `ContentConflict` and preserves the original bytes; U08 shows the only reuse path is byte-identical. |

## 2. Visibility, refresh and PIT

| Broken implementation | Why it is plausible | Distinguishing test |
|---|---|---|
| Make `flush` publish a committed generation | "Flush is a small commit." | U03/I12 assert `CURRENT` is absent after flush; I01 confirms committed visibility only after commit. |
| Let later inserts mutate an already returned snapshot | Share one growing structure | U04 compares two refresh views; the earlier view is unchanged. |
| Make `refresh` durable | "Refresh can reuse the commit path." | I03 (separate process) shows a refresh-only document is not recovered. |
| Drop the writer and let snapshots dangle | Snapshot borrows writer state | U12 and I09 keep an `Arc<ReaderSnapshot>` alive after writer drop and read from it. |
| Let a PIT see documents added after it was created | PIT aliases the live view | U07/I02/I10 pin before later inserts and assert the old key set. |
| Leak or never release a pin | Count only on close | U13 asserts the pinned count returns to 0 on drop and that ids are not reused. |

## 3. Admission and identity

| Broken implementation | Why it is plausible | Distinguishing test |
|---|---|---|
| Allow a second writer | Rely on a process-local flag | U01 and I06 show `WriterBusy`, including after a manually injected stale marker. |
| Auto-steal a stale lock | "The old writer is gone." | I06 shows the stale marker must be explicitly removed by an operator. |
| Accept a duplicate key after reopen | Rebuild the key index lazily/incorrectly | U02 and I07 reject duplicates across pending, flushed, committed and reopened state. |
| Execute upsert/delete/idempotency silently | Reuse `MutationRequest` | U15 returns `UnsupportedMutation` with zero side effects. |
| Accept a mismatched schema/analyzer fingerprint | Compare only field names | U10 and I08 fail closed with `SchemaMismatch` on a changed analyzer binding. |

## 4. Resources, threading and format

| Broken implementation | Why it is plausible | Distinguishing test |
|---|---|---|
| Publish `CURRENT` despite a budget failure | Check limits last | U11 and F13 reject with `ResourceLimit` and leave `CURRENT` absent. |
| Share a non-`Send` `SegmentReader` across threads | Reuse one cached reader | I09 constructs independent readers inside each thread from `Arc<Vec<u8>>` bytes. |
| Re-encode/alter PR 5 segment or manifest bytes to add generation | "Generations belong in the manifest." | Generation lives only in the filename/`CURRENT`; the golden fixture hash is unchanged and all PR 5 suites pass. |
| Delete old segments on a new commit | "Keep the index tidy." | I10 asserts the old segment object still exists and the pinned snapshot still reads. |
| Panic on malformed persisted input | `unwrap` a decoded field | F08–F11 return typed `IndexError`s; `forbid(unsafe_code)` and no `panic!` path is exercised. |

## 5. Honesty limits

- The fault suite injects failures into the real `Directory` methods; it does
  **not** prove hardware power-loss durability. That remains a property of the
  separately verified `FsDirectory::atomic_write` fsync/rename contract.
- The separate-process tests prove recovery from an orderly process exit, not
  from a mid-syscall kill.
- The RustFS/S3 production path is out of scope and is not evidenced here.
