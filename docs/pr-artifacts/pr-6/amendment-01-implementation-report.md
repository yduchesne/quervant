# PR 6 Amendment 01 implementation report — writer freshness and bounded reader lifecycle

> **Branch:** `dev/pr06-writer-lifecycle`
> **Base:** `569f4a48f98e2f97d55686c5440588889fc66233` (original PR 6 base)
> **Amendment target inspected/implemented from:** `e1ef19541ce3a317419d372e42a8fbc54e06626a`
> **Status:** implementation complete; mandatory local gates green (see
> `amendment-01-validation-report.md`). **No merge performed.**

## 1. Scope delivered

Exactly the five corrective findings, plus tests, artifacts and active docs:

| Finding | Correction |
|---|---|
| R6-A01 | `Index` is a read-only snapshot handle; every new writer acquires the lock and reloads authoritative `CURRENT`; private `IndexOrigin` distinguishes created-empty from opened-existing. |
| R6-A02 | Aggregate declared-segment byte preflight before allocating the segment vector or opening any segment; checked cumulative re-check while loading. |
| R6-A03 | `WriterLock::release` marks released only after a successful delete; Guard Drop makes one best-effort retry. |
| R6-A04 | Process-global session sequence + per-session checked ordinal; ids `pit-<16 hex session>-<16 hex ordinal>`; typed `PitIdExhausted`; pin rollback on ordinal exhaustion. |
| R6-A05 | Snapshot-shared `ReaderByteBudget` + RAII `ReaderReservation`; public non-Clone `GuardedSegmentReader`; `ReaderSnapshot::open_segment_reader` reserves before cloning; the unmetered `SegmentSnapshot::reader` bypass was removed. |

Preserved unchanged: `Directory::create_dir_all`, `segment/*` codec bytes,
golden fixtures, CURRENT v1, commit ordering, fail-closed recovery, local-only
architecture, immutable snapshots, and the cooperative no-auto-steal lock policy.

## 2. Public API migration

- **Removed** `pub fn SegmentSnapshot::reader(&self, SegmentLimits) -> Result<SegmentReader, SegmentError>`.
  It was an unbounded, unmetered clone path. `SegmentSnapshot::{bytes, shared_bytes,
  meta, doc_count}` remain public, so raw immutable bytes are still accessible and
  user-owned clones are **not** memory-enforced.
- **Added** `pub fn ReaderSnapshot::open_segment_reader(&self, index: usize)
  -> IndexResult<GuardedSegmentReader>`.
- **Added** non-Clone `GuardedSegmentReader` with `reader(&self) -> &SegmentReader`
  (no `Deref`, no ownership transfer, no `Send`).
- **Removed** the `pub` status is also reflected in the amendment preflight; the
  method had no remaining Quervant-managed caller after migration.
- New typed errors: `IndexError::{PitIdExhausted, SegmentOutOfRange}`.
- `PinCounter::new` now returns `IndexResult<Arc<Self>>` and `try_pin` returns
  `IndexResult<Option<String>>`; `Index` constructors propagate the session
  allocation error.

This is an intentional source-compatibility change on an unmerged branch. No
semver constraint forbade removal, so no STOP was required.

## 3. Detailed changes

### 3.1 Writer freshness (A01/A02)

- `index/mod.rs`: added `pub(crate) enum IndexOrigin { CreatedEmpty,
  OpenedExisting }`; `Index` stores `origin`; `writer()` passes `origin` and no
  longer passes `self.committed.clone()`.
- `index/writer.rs::IndexWriter::open(directory, schema, registry, limits, pins,
  origin)`: `ensure_layout` → `WriterLock::acquire` → exactly one
  `support::read_current`. If `CURRENT` is absent: `CreatedEmpty` starts empty,
  `OpenedExisting` returns `NotInitialized`. If present, the parsed pointer is
  loaded via `mod::load_committed_at` (no second `CURRENT` read). A load failure
  returns the original typed error; the `WriterLock` guard's `Drop` attempts
  release.
- `load_committed` is a thin wrapper that reads `CURRENT` once and delegates to
  `pub(crate) load_committed_at`, keeping `Index::open_with_limits` behavior.

### 3.2 Aggregate committed-snapshot budget (A03/A04)

- `index/support.rs::bounded_segment_total(lengths, per_segment_limit,
  total_limit)`: checked running sum; individual overage and `u64` overflow are
  typed `ResourceLimit` failures.
- `load_committed_at`: after `Manifest::decode` and schema validation, calls the
  helper over `reference.content_length` with the codec `accepted_segment_bytes`
  and `max_snapshot_bytes` **before** `try_reserve_exact` or any
  `SegmentReader`/`open_read`. It then re-checks the checked cumulative
  verified-byte total inside the load loop. No partial `CommittedState` is
  published.

### 3.3 Retryable lock release (A05/A06)

```rust
fn release(&mut self) -> IndexResult<()> {
    if self.released { return Ok(()); }
    self.directory.delete(&self.key)?;
    self.released = true;
    Ok(())
}
```

`Drop` still calls release best-effort once. `IndexWriter::close(self)`
attempts release once and consumes the writer; the subsequent guard drop is the
single best-effort retry. No automatic stale-lock stealing was added.

### 3.4 Process-local PIT session identity (A07/A08)

- `index/pit.rs`: `static NEXT_SESSION: AtomicU64 = AtomicU64::new(1)`;
  `PinCounter { pinned, max, session, next }`. Session allocation uses
  `fetch_update(... |n| n.checked_add(1))` and maps exhaustion to
  `PitIdExhausted`. `try_pin` reserves capacity first (CAS), then allocates an
  ordinal with checked `fetch_update`; on ordinal exhaustion it releases the
  reservation exactly once and returns `PitIdExhausted`. Ids are
  `pit-<16 lowercase hex session>-<16 lowercase hex ordinal>`. `PitHandle`
  remains non-Clone with a single Drop release.
- `Index` constructors use `PinCounter::new(...)?`.

### 3.5 Bounded managed reader materialization (A09/A10/A14)

- `index/snapshot.rs`: private `ReaderByteBudget { used: AtomicU64, limit }` with
  CAS `try_reserve` (checked add; typed `ResourceLimit` on overage or overflow)
  and `release`; private RAII `ReaderReservation`.
- `ReaderSnapshot::new(..., reader_copy_limit)` constructs a fresh per-snapshot
  budget. Every construction site (`Index::snapshot`, `IndexWriter::refresh`,
  `IndexWriter::committed_snapshot`) passes `IndexLimits::max_snapshot_bytes()`.
- `open_segment_reader(index)` validates the index (`SegmentOutOfRange`),
  reserves the encoded length **before** cloning, wraps the clone in a
  `ReaderReservation`, and opens the existing `SegmentReader`; any open error
  drops the reservation. Exact-at-limit succeeds; one-over fails.
- `stored_keys`/`stored_key_set`/`contains_key` now use the guarded API and
  `try_reserve` the key vector instead of `Vec::with_capacity`.
- `resident_bytes()` continues to report only base immutable snapshot bytes; the
  reader-copy budget is a **separate** ceiling of the same configured value.

## 4. Tests

`crates/quervant-core/tests/pr06_amendment_01.rs` (T01–T07, T10–T14, T16–T18,
T20–T22, T25, plus the ignored `t02_child_commits_gen2` separate-process child).
In-crate focused tests:

- `index/writer.rs`: T09 lock-release retry and permanent-failure behavior.
- `index/pit.rs`: session distinction/format, capacity, and T15 ordinal
  exhaustion with rollback (local counter, no global mutation).
- `index/snapshot.rs`: budget exact/one-over, overflow, decoder-failure
  reservation release, out-of-range, and RAII release.
- `index/support.rs`: T08 aggregate-total overflow/overage.

Existing PR 6 suites (`pr06_lifecycle_unit`, `pr06_local_integration`,
`pr06_faults`) and all PR 3/4/5 suites remain green.

## 5. Deviations and residual risks

- No deviations from the plan's binding design decisions.
- The reader-copy reservation bounds cloned **encoded bytes**, not decoder
  allocations or process RSS.
- Snapshot base residency and active reader copies have separate ceilings of the
  same value; they are not a combined cap.
- PIT id uniqueness holds only within one process lifetime.
- A permanently failing lock delete leaves a stale lock requiring manual
  operator cleanup; this is documented and tested.
- Separate-process restart tests are not power-loss simulation.
