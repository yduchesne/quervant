# PR 6 Amendment 01 adversarial review

> Tested tree: the amendment branch tip (code commit recorded in
> `amendment-01-validation-report.md`). This review names plausible ways each
> invariant could still be violated, the evidence that distinguishes it, and any
> residual risk.

## 1. Writer freshness (A01/A02)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| A stale `Index` handle passes its cached `CommittedState` to a new writer | `Index::writer` passes `origin` only; `IndexWriter::open` reads `CURRENT` under the lock. T02 commits generation 2 from another handle and then confirms the stale handle's writer starts at generation 2, rejects the committed duplicate, and commits generation 3 retaining all keys. | None observed. |
| A created-empty handle re-commits generation 1 after another writer's first commit | T03 creates two handles before any commit; the second commits generation 1; the first handle's writer reloads generation 1 and commits generation 2 with both keys. | None observed. |
| Corrupt `CURRENT` still admits a writer | T04 corrupts `CURRENT` after opening and asserts `InvalidCurrent` on repeated `writer()` calls; the guard drops and releases the lock each time. | None observed. |
| `CURRENT` is read twice (TOCTOU) between pointer and manifest | `IndexWriter::open` reads `CURRENT` once and passes the parsed pointer to `load_committed_at`; the manifest is verified against that pointer's length/digest. | A concurrent external process mutating `CURRENT` between the pointer read and manifest read is outside the single-writer/cooperative model. |

## 2. Aggregate snapshot budget (A03/A04)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Two individually legal segments exceed the aggregate budget | T06 sets `max_snapshot_bytes = s0+s1-1` and asserts `ResourceLimit` with a counting `Directory` reporting **zero** segment `open_read` calls. | None observed. |
| A single declared length exceeds the codec acceptance bound | T07 lowers `accepted_segment_bytes` below the segment length and asserts a pre-read `ResourceLimit` with zero segment opens. | None observed. |
| `u64` overflow in the total wraps | T08 (`support.rs`) exercises `bounded_segment_total([u64::MAX, 1], ...)` as a typed limit error. | None observed. |
| Partial snapshot published when a later segment fails validation | The loop only pushes a `SegmentSnapshot` after `read_verified` + `SegmentReader::open` + stored-key checks; `CommittedState` is returned only at the end. | None observed. |

## 3. Lock release (A05/A06)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| `released` set before a failed delete, so the write handle is never removed | T09 injects one delete failure: `release` returns an error and `released == false`; a second direct release succeeds. | None observed. |
| A failed release admits a competing writer | T10 injects permanent delete failure: `close` fails, Drop retries once, and `index.writer()` still returns `WriterBusy`. | A permanently stale lock requires manual operator cleanup; documented and unchanged policy. |
| `close(self)` + Drop deletes twice on a one-time failure | T11 asserts exactly two delete calls for a one-time failure and that the lock is released (new writer admitted). | None observed; the second delete is the intended single best-effort retry. |

## 4. PIT identity and pin accounting (A07/A08)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Two indexes in one process both issue `pit-1` | T12 creates two indexes and asserts distinct, session-qualified ids with the exact `pit-<16hex>-<16hex>` length/format. | Uniqueness is process-lifetime only, not across restarts; documented. |
| Ordinal overflow repeats an id or leaks a pin | T15 sets a private counter's ordinal to `u64::MAX-1`; the next pin returns `PitIdExhausted` and the reserved pin count stays at 1 (rollback). The process-global counter is not mutated. | None observed. |
| Drop/close leaks a pin | T12–T14 assert `pinned_pits()` returns to 0; `PitHandle` remains non-Clone with one Drop release. | None observed. |

## 5. Managed reader budget (A09/A10/A14)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Budget checked after the clone | `open_segment_reader` calls `try_reserve` before `SegmentReader::open(...clone...)`; T17 shows the second simultaneous copy rejects while the first reader remains usable. | The reservation bounds cloned encoded bytes, not decoder allocations/RSS. |
| Reservation leaked on decoder failure | The in-crate `decoder_failure_releases_reservation` test opens invalid bytes and asserts `reader_copy_used() == 0`. | None observed. |
| Reservation leaked on guard drop | `ReaderReservation` Drop releases exactly once; T18 shows the budget is reusable after dropping the first guard. | None observed. |
| Unmetered managed bypass remains | The public `SegmentSnapshot::reader` was removed; T25 and the source audit confirm no Quervant-managed unmetered path. Raw `SegmentSnapshot::bytes`/`shared_bytes` clones remain user-owned and are explicitly **not** enforced. | A caller can still clone raw bytes; this is disclosed, not silently enforced. |
| Out-of-range index panics | T25 asserts typed `SegmentOutOfRange`. | None observed. |

## 6. Regression and durability honesty

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| PR 5 golden fixture changed | T22 hashes `fixtures/segment/golden.seg` and asserts `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`; the existing `segment_golden.rs` suite also passes. | None observed. |
| Commit/fault semantics regressed | All existing F01–F16, I01–I12 and U01–U17 tests pass unchanged, including ambiguous-`CURRENT` `RecoveryRequired`. | None observed. |
| Old PIT/readers lose prior segments after a commit | T20/T21 and I10 keep an old snapshot/PIT readable and confirm the old segment object is not deleted. | None observed. |
| Separate-process restart wrongly claimed as power-loss proof | The process tests are labeled as process-crash recovery; power-loss durability remains a property of the verified `FsDirectory::atomic_write` contract. | Not proven by deterministic tests; disclosed. |
