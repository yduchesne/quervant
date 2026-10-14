# PR 9 Amendment 01 — preflight and reconciliation

**Base commit (plan reference):** `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`.
**Amended branch:** `dev/stable-key-mutations`.
**HEAD before amendment:** `950583c43ea11773e59971e3e330064bd7f67c14` ("PR 9 Phase 0"),
a clean committed working tree containing the original PR 9 implementation.
The amendment is applied as further uncommitted changes on top of `950583c`.
No original PR 9 work was reset or discarded.

## Working tree at amendment start

`git status --short` was empty; `git merge-base HEAD main` =
`17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`. The original PR 9 implementation
and all seven `docs/pr-artifacts/pr-9/*` reports were already committed in
`950583c`, so the amendment edits only the implementation and adds the new
amendment artifacts.

## API reconciliation (exact symbols)

| Concern | Symbol | Location |
|---|---|---|
| Revision allocation | `previous_revision.checked_add(1).ok_or(IndexError::RevisionOverflow)?` | `src/index/writer.rs` `IndexWriter::apply` |
| Idempotency replay before allocation | `lookup_replay` then exact-fingerprint early return | `src/index/writer.rs` `IndexWriter::apply` |
| Commit reconciliation | `IndexWriter::reconcile_current_failure` | `src/index/writer.rs` |
| Shared reconciliation for compaction | `IndexWriter::reconcile_publication` (new) | `src/index/writer.rs` |
| `CURRENT` atomic write | `directory.atomic_write(current_key, …)` | `commit` and `merge::compact` |
| Compaction engine | `merge::compact(writer, cancelled)` (now takes a flag) | `src/index/merge.rs` |
| Public cancellation entry | `IndexWriter::compact_with_cancel(&AtomicBool)` (new) | `src/index/writer.rs` |
| Live-mask construction | `visibility::build_masks_from_readers[_cancellable]` | `src/index/visibility.rs` |
| Typed cancellation error | `IndexError::Cancelled` (new — previously absent) | `src/index/error.rs` |
| Typed overflow error | `IndexError::RevisionOverflow` (reused) | `src/index/error.rs` |
| Fault-injection wrapper | `FaultyCurrentDirectory` (test-only) | `src/index/amendment01.rs` |

The revision-allocation ordering already matched the required sequence: replay
lookup first, then live-state check, then `checked_add`, then budget preflight,
then journal/token insertion. No production ordering correction was required.
`IndexError::RevisionOverflow` already existed and was reused. `commit` already
poisoned on an ambiguous replacement and remained retryable on a pre-write
failure.

## Invariant ↔ amendment-test mapping

| Invariant | Amendment tests |
|---|---|
| A1-I01 | A1-T01, A1-T02 |
| A1-I02 | A1-T03, A1-T04 |
| A1-I03 | A1-T05, A1-T06 |
| A1-I04 | A1-T07, A1-T08 |
| A1-I05 | A1-T09, A1-T10 |
| A1-I06 | A1-T11, A1-T12, A1-T13, A1-T14, A1-T15, A1-T16 |
| A1-I07 | A1-T13, A1-T15, A1-T17 |
| A1-I08 | A1-T18 |
| A1-I09 | A1-T19, A1-T20 |
| A1-I10 | A1-T21, A1-T22 |

## Targeted counterexamples

1. **Overflow/replay ordering:** computing the next revision before the replay
   lookup would make an exact replay at `u64::MAX` overflow. A1-T03 detects this
   by replaying an identical token at `u64::MAX` and asserting
   `replayed == true, revision == u64::MAX`.
2. **Ambiguous publication:** treating a write-then-error `CURRENT` as ordinary
   retryable I/O would leave two writers able to publish the same generation.
   A1-T05/T06 detect this by asserting `RecoveryRequired`, one intercepted
   `CURRENT` write, and that a fresh writer observes the new generation.
3. **False cancellation after publication:** checking the flag after
   `CURRENT` publication would report `Cancelled` for a durable generation.
   A1-T18 detects this by flipping the flag after the final prepublication
   checkpoint and asserting a successful `MergeOutcome`.

## Baseline results

| Command | Baseline result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo test -p quervant-core --test pr09_mutations --test pr09_visibility --test pr09_recovery --test pr09_merge --test pr09_reclamation --test pr09_properties` | PASS (13/6/4/6/5/1) |
| Full stable/MSRV workspace gates | PASS (recorded in `validation-report.md` before the amendment) |

The amendment's final validation is recorded in
[`amendment-01-validation-report.md`](amendment-01-validation-report.md).
