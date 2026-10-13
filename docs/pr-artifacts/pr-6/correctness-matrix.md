# PR 6 correctness matrix — invariant traceability

> Baseline `569f4a48f98e2f97d55686c5440588889fc66233`. Every row records the
> production code location, the executing test IDs and the validation command.
> Status legend: **EXECUTED** = test ran and passed on the working tree.

## 1. Invariant traceability (L01–L18)

| ID | Invariant | Production code | Tests | Status |
|---|---|---|---|---|
| L01 | One cooperating writer | `index/writer.rs` `WriterLock::acquire`, `IndexWriter::open` | U01, I06 | EXECUTED |
| L02 | Duplicate insert rejected across pending/flushed/committed/reopened | `index/writer.rs` `insert`/`is_duplicate`; `index/mod.rs` `load_committed` builds committed keys | U02, I07, F15 | EXECUTED |
| L03 | Flush never publishes the committed view | `index/writer.rs` `flush` (in-memory only) | U03, I12 | EXECUTED |
| L04 | Refresh views are immutable and complete | `index/writer.rs` `refresh`; `index/snapshot.rs` `ReaderSnapshot` | U04 | EXECUTED |
| L05 | Refresh is never durable | `index/writer.rs` `refresh` (no `atomic_write`) | I03 (separate process) | EXECUTED |
| L06 | Commit ack only after all durability barriers | `index/writer.rs` `commit` (segments → manifest → CURRENT) | F01–F07 | EXECUTED |
| L07 | `CURRENT` is the sole durable selector | `index/mod.rs` `load_committed`; `index/current.rs` strict codec | U05, I04 (orphan) | EXECUTED |
| L08 | Corruption fails closed with no fallback | `index/support.rs` `read_verified`; `index/mod.rs` `load_committed` | U06, F08–F11 | EXECUTED |
| L09 | PIT stable across refresh/commit/close | `index/pit.rs`; `index/snapshot.rs` | U07, I02, I10 | EXECUTED |
| L10 | Immutable segment/manifest bytes | `index/support.rs` `install_immutable`/`verify_existing` | U08, F12 | EXECUTED |
| L11 | Generation monotonic and checked | `index/writer.rs` `checked_add`; `GenerationOverflow` | U05 (overflow), U09, F07 | EXECUTED |
| L12 | Schema/analyzer compatibility enforced | `index/support.rs` `expected_codec_schema`; `index/mod.rs` compare | U10, I08 | EXECUTED |
| L13 | Limits reject without partial publication | `index/limits.rs`; `index/writer.rs` bound checks | U11, F13 | EXECUTED |
| L14 | Snapshot ownership independent of writer | `index/snapshot.rs` `Arc<Vec<u8>>` segments | U12, I09 | EXECUTED |
| L15 | PR 5 golden unchanged | unchanged fixture + codec | `segment_golden.rs`; fixture SHA check | EXECUTED |
| L16 | Core local-only independence | no new dependency; `quervant-core` has no runtime/Tokio/etcd | workspace clippy/test; crate manifest review | EXECUTED |
| L17 | PIT close/drop releases its pin | `index/pit.rs` `PinCounter`/`Drop` | U13 | EXECUTED |
| L18 | No referenced files deleted | `index/writer.rs` never deletes committed objects | I10 | EXECUTED |

## 2. Test ID inventory

- Unit (`tests/pr06_lifecycle_unit.rs`): **U01–U17** (18 test functions; U05 and
  U11 have focused variants).
- Integration (`tests/pr06_local_integration.rs`): **I01–I12** plus 3 ignored
  child-process entry points spawned by their parents (I03, I04, I05).
- Faults (`tests/pr06_faults.rs`): **F01–F16** (F05 split into create/file-sync/
  directory-sync variants; F06/F14 share the pre-`CURRENT` failure; F16 added).
- Golden regression: existing `segment_golden.rs` and all PR 3/4/5 suites remain
  green.

## 3. Adversarial counterexamples actually distinguished

| Plausible wrong implementation | Test that fails it |
|---|---|
| Second writer admitted after a stale lock | I06 (`WriterBusy` before and after a manually injected stale marker) |
| Duplicate after reopen accepted | U02, I07, F15 |
| Flush writes `CURRENT` | U03, I12 (`CURRENT` absent) |
| Old refresh view mutated by later inserts | U04 |
| Refresh data recovered as committed | I03 (separate process) |
| Acknowledgment after a sync error | F03, F04, F05b, F05c |
| `CURRENT` replaced but error reported as "not committed" | F07 (`RecoveryRequired`) |
| Highest listed manifest selected | I04 (orphan generation 3 ignored) |
| Fallback to an older manifest on corruption | U06, F08, F09, F10, F11 |
| `CURRENT` bytes not canonical | U05, `current.rs` unit cases |
| Digest collision overwrites existing bytes | F12 (`ContentConflict`, original preserved) |
| Generation silently reused after ambiguity | F07, F16 |
| Mismatched analyzer fingerprint accepted | U10, I08 |
| Limit failure still publishes `CURRENT` | F13, U11 |
| Snapshot dangles after writer close | U12, I09 |
| PR 5 golden regenerated | fixture SHA `ebb07800…` unchanged |
| PIT pin leaked after drop | U13 (`pinned_pits()` returns to 0) |
| Referenced segment deleted by a later commit | I10 |

## 4. Amendment 01 traceability (A01–A14)

| ID | Invariant | Production code | Amendment tests |
|---|---|---|---|
| A01 | Writer state equals `CURRENT` under the acquired lock | `index/mod.rs` `IndexOrigin`, `IndexWriter::open`, `load_committed_at` | T01, T02 (incl. separate process), T03 |
| A02 | Corrupt/missing `CURRENT` prevents writer admission | `IndexWriter::open` | T04 |
| A03 | Aggregate declared snapshot bytes bounded before segment reads | `support::bounded_segment_total`; `load_committed_at` | T05, T06, T07 |
| A04 | Cumulative arithmetic checked; no partial snapshot | `bounded_segment_total`; load-loop recheck | T08 |
| A05 | Failed lock delete leaves the guard unreleased | `WriterLock::release` | T09 |
| A06 | Failed release does not admit a second writer | `WriterLock` ownership | T10, T11 |
| A07 | PIT ids differ across sessions in one process | `pit.rs` `NEXT_SESSION`, `PinCounter` | T12, T13, T14 |
| A08 | PIT counters never wrap or leak pins | checked `fetch_update`, rollback | T15 |
| A09 | Reader-copy reservation precedes clone | `ReaderByteBudget::try_reserve`, `open_segment_reader` | T16, T17 |
| A10 | Reservation released on success/error/drop | `ReaderReservation` RAII | T18, T19 |
| A11 | Snapshots/PITs immutable; readers independent | `Arc` snapshots, guarded readers | T20, T21 |
| A12 | CURRENT/segment/manifest/golden unchanged | no codec edits | T22, T23 (existing codec suite) |
| A13 | Commit/recovery fault semantics preserved | unchanged commit/reconcile | T24 (existing F01–F16) |
| A14 | Managed reader opening cannot bypass budget | removed `SegmentSnapshot::reader`; guarded API | T25 |

## 5. Amendment 02 traceability (B01–B12)

| ID | Invariant | Production code | Amendment tests |
|---|---|---|---|
| B01 | Commit and reopen enforce the same aggregate ceiling | `writer.rs::commit` preflight (reuses `support::bounded_segment_total`) | C01, C02 |
| B02 | Exact-at-limit succeeds; one over fails | same | C03, C04 |
| B03 | Every segment meets the codec accepted-byte bound | `support::bounded_segment_total` + existing builder/reader bound | C05 |
| B04 | Check precedes any immutable write / `CURRENT` | preflight placement before `install_immutable` | C06 |
| B05 | Rejected commit preserves `CURRENT` and key set | unchanged commit body | C01, C07 |
| B06 | Rejected commit preserves pending/flushed, no poison | unchanged state mutation | C08, C09 |
| B07 | No-change / empty-initial commit unchanged | existing no-op branch | C10 |
| B08 | Multi-generation accumulation checked | manifest chain in the preflight | C02, C11 |
| B09 | Aggregate sum cannot wrap | `bounded_segment_total` `checked_add` | C12 + `support.rs` unit test |
| B10 | Existing fault/recovery semantics unchanged | commit/reconcile untouched | C13 (`pr06_faults`, `pr06_lifecycle_unit`) |
| B11 | No codec/manifest/`CURRENT` wire change | no codec edits | C14 |
| B12 | Memory and Fs storage agree | real Directory paths | C01, C03, C07, C15 |
