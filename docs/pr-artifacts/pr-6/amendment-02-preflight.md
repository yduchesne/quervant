# PR 6 Amendment 02 preflight — commit/recovery snapshot-budget parity

> **Branch:** `dev/pr06-writer-lifecycle`
> **Actual branch HEAD at preflight:** `321147feb2c242a566de0b7de82e936584f3347b`
> (clean worktree; Amendment 01 code `f7a1715`; original PR 6 `e1ef195`; base `569f4a4`)
> **Toolchains:** stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov` installed.
> **Status:** EXECUTED preflight. No production edit made before this record.

## 1. Finding reconciliation (R6-F01)

`index/writer.rs::IndexWriter::commit` currently checks:

- `segments_added > max_segments_per_commit`,
- encoded manifest size `> max_manifest_bytes`,
- then installs each immutable segment, installs the manifest, and publishes
  `CURRENT`.

It does **not** sum the encoded byte lengths of the previous committed manifest
references plus the new segments. `index/mod.rs::load_committed_at` **does**
enforce `bounded_segment_total(lengths, accepted_segment_bytes,
max_snapshot_bytes)` on reopen. Therefore a writer configured with a small
`max_snapshot_bytes` can publish a generation that the same handle's
`Index::open_with_limits` later rejects. **R6-F01 = OPEN.**

Verified code facts:
- `support::bounded_segment_total(lengths, per_segment_limit, total_limit)`
  checks each length, uses `checked_add`, and returns
  `IndexError::ResourceLimit` on per-segment overage or overflow.
- `SegmentMeta::descriptor()` returns `ContentDescriptor` with a `u64 length`.
- First durable write in `commit` is `support::install_immutable` for the first
  new segment. The preflight must precede it.
- The no-change branch returns `no_op = true` before any segment construction.
- `build_pending_segment()` already allocates transient bytes before the
  preflight; the contract is **no durable side effects**, not zero CPU/RSS.

## 2. Binding design (from the plan)

One aggregate preflight immediately after the `max_segments_per_commit` check and
before `doc_total`/generation/any `install_immutable`:

```rust
let committed_lengths = self.committed.iter().flat_map(|state| {
    state.manifest.segments.iter().map(|reference| reference.content_length)
});
let new_lengths = new_segments
    .iter()
    .map(|segment| segment.meta.descriptor().length);
support::bounded_segment_total(
    committed_lengths.chain(new_lengths),
    self.limits.segment_limits().accepted_segment_bytes(),
    self.limits.max_snapshot_bytes(),
)?;
```

Semantics: `self.committed.manifest.segments` is the authoritative committed
list; `new_segments` already includes flushed segments plus the built pending
segment, so nothing is double-counted or omitted. Error is
`IndexError::ResourceLimit`; the writer is **not** poisoned and `pending`,
`flushed`, `uncommitted_keys`, `committed`, `published` and `CURRENT` are
untouched. No new API, limit field, codec, storage or publication-ordering change.

## 3. Correctness gate (B01–B12) and planned tests

| ID | Invariant | Counterexample | Planned test |
|---|---|---|---|
| B01 | Commit and reopen enforce the same aggregate ceiling | old 70 + new 40, budget 100: commit succeeds but reopen fails | C01, C02 |
| B02 | Exact-at-limit succeeds; one over fails | `>=` instead of `>` | C03, C04 |
| B03 | Every individual segment meets the codec accepted-byte bound | total under budget but new segment over per-segment bound | C05 |
| B04 | Budget check precedes any immutable write / `CURRENT` | over-limit attempt leaves an orphan segment | C06 |
| B05 | Rejected commit preserves `CURRENT` and reopened key set | generation incremented despite error | C01, C07 |
| B06 | Rejected commit preserves pending/flushed and does not poison | pending discarded or `RecoveryRequired` | C08, C09 |
| B07 | No-change and empty-initial commits unchanged | preflight blocks the empty generation | C10 |
| B08 | Multi-generation accumulation is checked | three commits each individually under limit but total over | C02, C11 |
| B09 | Aggregate sum cannot wrap | `u64::MAX + 1` wraps | C12 (existing helper) |
| B10 | Existing fault/recovery semantics unchanged | `atomic_write` failure misclassified | C13 (F01–F16, U01–U17) |
| B11 | No codec/manifest/`CURRENT` wire change | PR 5 golden bytes altered | C14 |
| B12 | Memory and Fs storage agree | memory-only test hides filesystem ordering | C01, C07, C15 |

**Unspecified decisions:** none. The plan fixes placement, inputs, helper and
error semantics. No STOP condition applies.

## 4. Transition analysis

`pending -> built segment -> aggregate preflight -> immutable installs ->
manifest -> CURRENT -> reopened state`.

- Empty: `new_segments` empty; total `0`; passes.
- Singleton: one committed + one new; boundary handled by `>`.
- Multi-segment / multi-generation: summed across the committed manifest chain.
- Flushed + pending: both live in `new_segments`; counted once.
- Exact bound: success; one-over: `ResourceLimit { limit, requested = exact sum }`.
- Failure: no Directory write; writer remains usable.
- Later failures (manifest encode/size, storage write/sync, ambiguous
  `CURRENT`): unchanged existing semantics.

## 5. Test oracle strategy

- Expected key sets are hand-authored `BTreeSet`s.
- Expected segment totals are computed in the test from independently measured
  real encoded segment lengths (isolated fixture with identical
  schema/documents), never by calling `bounded_segment_total` as the oracle.
- Rejected commits compare raw `CURRENT` bytes, generation, manifest/segment
  listings and a counting `Directory`.
- Storage parity is exercised on both real `MemoryDirectory` and real
  `FsDirectory`, with a separate-process reopen where the harness supports it.

## 6. Scope and protected behavior

Only `index/writer.rs::commit` changes in production. Reuse-only:
`support::bounded_segment_total`, `load_committed_at`. No production change to
`limits.rs`, `snapshot.rs`, `pit.rs`, `Directory`/backends, `segment/*`, PR 5
fixtures, `CURRENT` v1, commit ordering, `refresh` or lock policy. No new
dependency, unsafe code, remote/distributed/query/mutation scope.

## 7. Expected residual risks

- The preflight bounds encoded segment bytes of one prospective generation, not
  decoder allocations, process RSS, cross-snapshot residency or raw user clones.
- `build_pending_segment()` still performs transient work before rejection.
- Process-crash reopen is not a power-loss simulation.
