# PR 6 Amendment 02 implementation report — commit/recovery snapshot-budget parity

> **Branch:** `dev/pr06-writer-lifecycle`
> **Base:** `569f4a48f98e2f97d55686c5440588889fc66233`; Amendment 01 code `f7a1715`
> **Target inspected:** `321147feb2c242a566de0b7de82e936584f3347b`
> **Status:** implementation complete; mandatory local gates green (see
> `amendment-02-validation-report.md`). **No merge performed.**

## 1. Finding and correction (R6-F01)

`IndexWriter::commit` validated the new segment count and the encoded manifest
size, but not the combined encoded segment bytes of the prospective committed
generation. A writer configured with a small `max_snapshot_bytes` could publish a
generation that the same configuration's `Index::open_with_limits` later
rejected. The correction applies the **existing**
`support::bounded_segment_total` validator to the authoritative committed
manifest references chained with all built new segments, immediately after the
`max_segments_per_commit` check and **before** `doc_total`/generation computation
or any `support::install_immutable`.

```rust
let committed_lengths = self.committed.iter().flat_map(|state| {
    state
        .manifest
        .segments
        .iter()
        .map(|reference| reference.content_length)
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

`self.committed.manifest.segments` is the authoritative committed list;
`new_segments` already contains flushed segments plus the built pending segment,
so every encoded segment is counted exactly once. The error is the existing
`IndexError::ResourceLimit`; the writer is not poisoned and no state or durable
object changes.

## 2. Files changed

- `crates/quervant-core/src/index/writer.rs` — one preflight insertion in
  `IndexWriter::commit`; no other production change.
- `crates/quervant-core/tests/pr06_amendment_02.rs` — C01–C15 acceptance and
  regression tests, including `CountingDirectory` and the ignored
  `c07_child_reopen` separate-process child.
- `docs/pr-artifacts/pr-6/amendment-02-*.md`, `correctness-matrix.md`,
  `ARCHITECTURE.md`, `TESTING.md`.

No production change to `support.rs`, `limits.rs`, `mod.rs`, `snapshot.rs`,
`pit.rs`, `Directory`/backends, `segment/*`, PR 5 fixtures, `CURRENT` v1, commit
ordering, `refresh`, or lock policy.

## 3. Error and state semantics

On rejection:

- `CURRENT` raw bytes, generation, manifest and segment listings are unchanged.
- `pending_documents()`, `flushed_segments()`, `uncommitted_keys`, `committed`
  and `published` are untouched; duplicate-key rejection still works.
- The writer remains usable for `reader`, `insert`, `flush`, `refresh` (subject
  to its own limit) and `close`; no `RecoveryRequired` is raised because
  `CURRENT` publication was never attempted.
- No new API, limit field, no-op change, or clear/delete API was introduced.

The no-review optional nuance is retained: `build_pending_segment()` may perform
transient allocation before the preflight; the contract is **no durable side
effects**, not zero CPU/RSS. The budget bounds encoded segment bytes of one
prospective generation, not decoder allocations, process RSS, cross-snapshot
residency or raw user clones.

## 4. Tests

`tests/pr06_amendment_02.rs`: C01–C12, C14, C15 plus the ignored separate-process
child for C07. C13 is the existing `pr06_faults`/`pr06_lifecycle_unit`
regression, executed in the final QA run. C12 additionally references the
existing `support.rs::bounded_total_detects_overflow` unit test.

Independent oracle choices: expected key sets are hand-authored `BTreeSet`s;
expected segment totals are measured from independently built real segments with
identical schema/documents in isolated fixtures; rejected commits are checked
against raw `CURRENT` bytes and a counting `Directory` with **zero**
commit-attributable creates/writes/syncs; C05 exercises the earlier per-segment
codec rejection while building the pending segment.

## 5. Residual risks

- Aggregate budget is per-generation encoded segment bytes; it is not an RSS or
  decoder-allocation cap.
- `build_pending_segment()` still does transient work before rejection.
- Process-crash reopen tests are not a power-loss simulation.
