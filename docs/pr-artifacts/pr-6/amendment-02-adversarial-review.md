# PR 6 Amendment 02 adversarial review — commit/recovery budget parity

> Tested tree: the Amendment 02 code commit recorded in
> `amendment-02-validation-report.md`. This review names plausible ways the
> parity invariant could still be violated and the evidence distinguishing each.

## 1. Parity of commit and reopen (B01/B02)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Commit checks only new segment bytes, not committed + new | C01/C04 seed a committed `a`, stage `b`, and commit with `max_snapshot_bytes = a+b-1`; the commit returns `ResourceLimit { requested = a+b }`, whereas the unpatched code published generation 2 and failed only on reopen. | None observed. |
| Off-by-one uses `>=` so exact-at-limit fails | C03 commits `a+b` and reopens containing both keys; C04 rejects `a+b-1` with the exact requested sum. | None observed. |
| Multi-generation accumulation is missed | C02 commits generation 2 under the bound and rejects generation 3 whose total exceeds it; generation 2 remains authoritative. | None observed. |
| Per-segment codec bound ignored when the total is small | C05 tightens `accepted_segment_bytes` to the old segment's length; a larger new segment is rejected by the existing codec check while building, before any install. | The rejection surfaces in `build_pending_segment`, which is the documented earlier typed failure. |
| Arithmetic wraps past the ceiling | C12 and the existing `support.rs::bounded_total_detects_overflow` unit test cover `u64::MAX + 1`. | None observed. |

## 2. No durable side effects on rejection (B04/B05)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Segment or manifest object written before rejection | C06 wraps a real `MemoryDirectory` in a counting `Directory`, resets after lock acquisition, and asserts zero segment creates, manifest creates, `CURRENT` writes and syncs. | None observed. |
| `CURRENT` replaced despite rejection | C01/C02/C07 compare raw `CURRENT` bytes before/after and assert the generation is unchanged. | None observed. |
| Orphan objects left by the rejected commit | C07 lists `index/manifests` and `index/segments` on a real `FsDirectory` and asserts exactly one object each; a separate process reopens and sees generation 1. | None observed. |

## 3. Writer state preserved (B06)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Pending batch silently dropped | C08 asserts `pending_documents() == 1` after rejection and that a duplicate insert is still rejected. | None observed. |
| Flushed segment lost | C09 stages one flushed and one pending segment, asserts both counts unchanged, and that the writer remains usable (`reader`, new insert, refresh). | None observed; `refresh()` legitimately reports the same budget error. |
| Writer poisoned or returns `RecoveryRequired` | C08/C09 exercise `close`/`reader`/`insert`/`refresh` after rejection without a poison transition. | None observed. |

## 4. Counting exactly once (B01/B08)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Flushed and pending double-counted or omitted | C11 runs the same flushed+pending staging with `limit = a+b-1` (rejected with requested `a+b`) and `limit = a+b` (accepted, `segments_added == 2`). | None observed. |
| Old segment data counted twice (manifest + `committed.segments`) | The preflight uses only `self.committed.manifest.segments`, the authoritative committed list; the plan and code deliberately avoid `committed.segments`. | None observed. |
| Empty initial commit blocked | C10 asserts the first empty commit still creates generation 1 and a later no-op returns the same generation. | None observed. |

## 5. Regression and format safety (B10/B11)

| Plausible violation | Evidence | Residual risk |
|---|---|---|
| Fault/recovery semantics changed | The full `pr06_faults` F01–F16, `pr06_lifecycle_unit` U01–U17, `pr06_local_integration` I01–I12 and `pr06_amendment_01` suites pass unchanged. | None observed. |
| PR 5 golden bytes altered | C14 asserts `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`; `segment_golden.rs` and all codec suites pass. | None observed. |
| Memory-only test hides filesystem behavior | C01/C03 and C15 repeat the rejection/acceptance cases on both `MemoryDirectory` and real `FsDirectory`, plus a separate-process reopen for C07. | None observed. |

## 6. Honesty limits

- The preflight bounds encoded segment bytes of one prospective generation; it
  does not cap decoder allocations, process RSS, cross-snapshot residency or raw
  user clones of immutable bytes.
- `build_pending_segment()` performs transient work before the preflight; the
  guaranteed property is no durable side effects.
- Process-crash reopen is not power-loss simulation.
