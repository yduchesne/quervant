# PR 6 Amendment 01 preflight — writer freshness and bounded reader lifecycle

> **Branch:** `dev/pr06-writer-lifecycle`
> **Baseline (original PR 6 base):** `569f4a48f98e2f97d55686c5440588889fc66233` (`main`)
> **Inspected amendment target:** `e1ef19541ce3a317419d372e42a8fbc54e06626a`
> **Actual branch HEAD at preflight:** `e1ef19541ce3a317419d372e42a8fbc54e06626a` (clean worktree)
> **Toolchains:** stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.9`/`0.9.1` installed.
> **Status:** EXECUTED preflight. No production edits made before this record.

## 1. Reconciliation of the five findings against actual branch code

| ID | Reported defect | Actual code at `e1ef195` | Classification |
|---|---|---|---|
| R6-A01 | `Index::writer` passes `self.committed.clone()`; lock acquisition does not reload CURRENT | Confirmed: `index/mod.rs::writer` passes `self.committed.clone()`; `IndexWriter::open` accepts it and never reads CURRENT. | **OPEN** |
| R6-A02 | `load_committed` loads segments with no aggregate `max_snapshot_bytes` preflight | Confirmed: only `Vec::with_capacity(manifest.segments.len())` and per-segment `accepted_segment_bytes`; no checked sum, no `max_snapshot_bytes` use. | **OPEN** |
| R6-A03 | `WriterLock::release` sets `released = true` before fallible `delete` | Confirmed: `self.released = true; self.directory.delete(&self.key)?;`. | **OPEN** |
| R6-A04 | `PinCounter` per-index `next` starting at 1, IDs `pit-{ordinal}` | Confirmed: `next: AtomicU64::new(1)`; `format!("pit-{ordinal}")`; `fetch_add` wraparound unchecked. | **OPEN** |
| R6-A05 | `SegmentSnapshot::reader` clones entire bytes with no budget | Confirmed: public `pub fn reader(&self, limits)` doing `SegmentReader::open(self.bytes.as_ref().clone(), limits)`. | **OPEN** |

No existing correction was found, so none is overwritten. The reported 831-pass/92.30%-line/unchanged-golden baseline is treated as **reported, not independently verified** until this amendment reran it.

## 2. Verified API facts used by the amendment

- `Index { directory, schema, registry, limits, pins, committed }`, `Index::writer`, `Index::snapshot`, `Index::pin`, `Index::pinned_pits`.
- `IndexWriter::open(directory, schema, registry, limits, pins, committed)`.
- `WriterLock { directory, key, released }` with `acquire`/`release`/`Drop`.
- `PinCounter { pinned, max, next }`, `PinCounter::new(max) -> Arc<Self>`, `try_pin(&self) -> Option<String>`, `release`, `pinned`, `max`.
- `ReaderSnapshot { generation, view_ordinal, segments, document_count, resident_bytes, segment_limits, pins }`, `ReaderSnapshot::new(...)`, `stored_keys`, `stored_key_set`, `contains_key`, `try_pin`, `pin_limit`.
- `SegmentSnapshot { meta, bytes, doc_count }`, public `bytes`, `shared_bytes`, `meta`, `doc_count`, public `reader`.
- Existing fault wrapper `FaultyDirectory` in `tests/pr06_faults.rs` wraps the real `Directory`; existing integration/unit suites are the amendment's test homes.
- Golden fixture `crates/quervant-core/tests/fixtures/segment/golden.seg` SHA-256 = `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`.

## 3. Pre-code correctness gate (A01–A14)

| ID | Invariant | Planned code | Positive test | Negative counterexample | Oracle / topology |
|---|---|---|---|---|---|
| A01 | Writer state equals CURRENT under acquired lock | `IndexOrigin`, `IndexWriter::open` reload; `load_committed_at` | T01, T03 | Stale handle publishes manifest omitting gen-2 data → T02 | Read CURRENT + stored-key set; Memory + Fs (+ new process) |
| A02 | Corrupt CURRENT prevents writer admission | `IndexWriter::open` read before writer constructed | T04 | Stale cached opener admits writer | `IndexError::InvalidCurrent`/`CorruptCommittedState`; real `MemoryDirectory` |
| A03 | Aggregate declared snapshot bytes bounded before segment reads | `support::bounded_segment_total` called before vector alloc/open | T05 | Two individually legal segments over aggregate → T06 | Counting `Directory` reports **zero** segment `open_read` |
| A04 | Cumulative arithmetic checked, no partial snapshot | checked helper + load-loop recheck | T08 | overflow of `u64::MAX` inputs | Direct helper unit test |
| A05 | Failed lock delete leaves guard unreleased | `WriterLock::release` marks released after success | T09 | Released flag set on failure | Counting fault `Directory` |
| A06 | Failed release does not admit second writer | unchanged lock ownership | T10, T11 | Competing writer succeeds after injected failure | `WriterBusy` + manual cleanup documented |
| A07 | PIT IDs differ across sessions in one process | process-global `NEXT_SESSION` | T12, T13, T14 | Two indexes both issue `pit-1` | Format/regex + set uniqueness; no global mutation in tests |
| A08 | PIT counters never wrap or leak pins | `fetch_update` checked; rollback on exhaustion | T15 | `MAX` ordinal repeats an ID | Local `next` value in private unit test |
| A09 | Reader-copy reservation precedes clone | `ReaderByteBudget::try_reserve` before clone | T16, T17 | Concurrent copies exceed limit | Budget `used()` counter; real snapshot |
| A10 | Reservation released on success/error/drop | `ReaderReservation` RAII | T18, T19 | Failed decoder leaks budget | In-crate invalid-bytes snapshot |
| A11 | Snapshots/PITs immutable across commits, readers independent | existing `Arc` snapshots + guarded readers | T20, T21 | Old PIT sees new docs / dangling bytes | Threads + old PIT after commit |
| A12 | CURRENT/segment/manifest/golden unchanged | no codec edits | T22, T23 | Golden digest changes | SHA-256 + `segment_golden.rs` |
| A13 | Commit/recovery fault semantics preserved | commit/reconcile untouched | T24 | Ambiguous CURRENT acked as success | Existing F01–F16 |
| A14 | Quervant-managed reader opening cannot bypass budget | remove public `SegmentSnapshot::reader`; guarded API only | T25 | Raw unmetered managed path remains | Static source audit |

**Unspecified-decision check:** none. The plan fixes the writer-origin semantics, budget, lock retry, PIT identity, and reader-budget architecture. No STOP condition applies.

## 4. Scope confirmation

Only the five corrections, their tests and reports/docs. Protected and untouched: `segment/*` codec bytes, golden fixtures, `storage/directory.rs`/backends, `quervant-objectstore`, `quervant-distributed`, CURRENT v1, commit ordering, fail-closed recovery, existing lock policy (no auto-steal), and `Directory::create_dir_all`. No new crate, dependency, unsafe code, remote storage, query, mutation/merge/GC, or distributed work.

## 5. Expected residual risks

- Snapshot base residency and managed reader copies have **separate** ceilings of the same configured value; they are not a combined cap.
- The reservation bounds cloned encoded bytes, not decoder allocations or process RSS.
- PIT id uniqueness holds only within one process lifetime.
- A permanently failing lock delete leaves a stale lock requiring manual operator cleanup.
- Process-crash tests are not power-loss simulation.
