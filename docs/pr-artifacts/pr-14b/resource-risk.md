# PR 14B — resource risk `R-14A-JSON-MEM` (B20/B21)

> **Disposition (2026-10-24, PR 14C):** the human decision is
> **`REQUIRE SEPARATE CORRECTION`**. The risk is **NOT** accepted, PR 14 is
> **BLOCKED / NOT ACCEPTED**, and a separately designed/approved correction is
> required. Details: [../pr-14c/resource-risk-disposition.md](../pr-14c/resource-risk-disposition.md).
> The historical 14B text below is preserved unchanged.

**Status:** OPEN. PR 14B measures and characterizes this residual risk. It does
**not** change memory-accounting architecture and does **not** mark the risk
resolved. A human 14C disposition (accept with bounds, or authorize a separate
design-reviewed fix) is required.

## The risk, restated

`search::typed::json_sort_value` calls
`JsonAccess::occurrences(field_id, doc_id, guard, None)`. Traversal work is
charged through `ScanGuard`/`MixedWorkMeter`, and occurrence count/depth/member
sizes are bounded by the JSON limits. However, the `None` memory sink means the
temporary `Vec<JsonOccurrence>` and its owned contents are **not** charged to
`SlotMemoryScope` / cumulative `BatchMemoryBytes`.

The existing JSON limits are:

| Limit | Value |
|---|---|
| `MAX_JSON_PATH_DEPTH` | 128 |
| `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` | 65,536 |
| `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT` | 8,000,000 |
| `MAX_JSON_PATH_MEMBER_BYTES` | 65,535 |
| `MAX_JSON_PATH_SECTION_BYTES` | 256 MiB |

## Method

Test suite: `crates/quervant-core/tests/pr14b_json_memory.rs`.

- One indexed document with a JSON array of `N` objects `{"v": i}` under
  `body.events`.
- Sort by the concrete wildcard path `$.events[*].v` with
  `MultiValueSelector::Min`, `top_k = 1`.
- `Projection::Fields([])` so the logical meter isolates the sort/budget path
  instead of charging per-document source bytes.
- The logical `BatchMemoryBytes` boundary is found by binary search on the real
  cumulative meter.
- Heap is measured by a test-only tracking `#[global_allocator]` inside an
  explicitly spawned **child process**, so concurrent tests cannot pollute the
  measurement. Windows are opened only around the measured batch.
- This is an allocator/process-heap metric, not RSS equivalence, and it is
  reported separately from the contract meters.

Run:

```sh
cargo test -p quervant-core --all-features --test pr14b_json_memory -- --nocapture --test-threads=1
```

## Measured results (Ubuntu 24.04, Rust 1.98.1, debug profile, 2026-10-24)

| Occurrences | Logical `BatchMemoryBytes` boundary | Tracked peak, exact limit | Tracked peak, one-under (typed failure) | Tracked peak, cancellation |
|---:|---:|---:|---:|---:|
| 1 | 112 B | 33,675 B | 33,104 B | 7,397 B |
| 128 | 112 B | 110,392 B | 41,233 B | 7,397 B |
| 4,096 | 112 B | **2,518,968 B** (≈2.4 MiB) | 303,121 B | 7,397 B |

Observations:

- The **logical meter is constant at 112 bytes** across a 4,096× occurrence
  increase, because the temporary occurrence vector is not charged.
- The **tracked heap grows with occurrence count** and, at 4,096 occurrences,
  reaches ≈22,500× the logical boundary.
- The **one-under budget failure still incurs a large transient allocation**
  before/while the typed `BudgetExceeded{BatchMemoryBytes}` is produced. Raising
  or lowering the logical budget therefore does not bound the temporary
  allocation.
- Cancellation is typed and avoids the occurrence walk in the measured path
  (7,397 B), i.e. it does not leak a partial success.

These observations are consistent with the reviewed PR 14A residual risk. They
do **not** demonstrate an unbounded allocation: occurrence count is bounded by
the JSON limits above, and the observed growth is linear in occurrences.

## Interpretation and limits

- `BatchMemoryBytes` is a **retained/cumulative logical** meter. It was never a
  physical-RSS cap, and this evidence does not claim otherwise.
- The measurement is on one machine and the debug profile. Absolute bytes are
  indicative; the scaling relationship and the logical/heap divergence are the
  material findings.
- JSON occurrence limits bound the worst case, but a workload near
  `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT` can still allocate materially more
  transient heap than the configured `BatchMemoryBytes` suggests.
- No production code was changed. No new meter or memory adapter was added.

## Required 14C disposition

PR 14B must not silently accept this risk. 14C (or a human architecture
reviewer) must choose and record one of:

1. **Accept** the residual risk with explicit bounds (for example, document that
   transient occurrence memory is bounded by the JSON limits and is not covered
   by `BatchMemoryBytes`, with operational caveats).
2. **Authorize a separate, design-reviewed fix** shared by the typed and unified
   sort paths (for example, pass a real memory sink to
   `JsonAccess::occurrences` and add exact/one-over/cancellation tests).
3. **Reject** and block release qualification until fixed.

Until such a decision exists, `R-14A-JSON-MEM` remains OPEN and PR 14B is not
`HUMAN ACCEPTED`.

## Independent source-review qualifications (PR #61)

**Q1 — Measurement scope, not a hard heap bound.** The test-only tracking allocator records allocation activity within explicit child-process measurement windows. It is not a measurement of process RSS, allocator capacity, a global maximum allocation, or a hard upper bound. The observed scaling and disparity with the 112-byte logical budget constitute evidence of a missing transient-allocation charge, not a proof that memory is unbounded. Do not infer a strict physical memory cap from these results.

**Q2 — Release disposition remains OPEN.** `R-14A-JSON-MEM` has **not** been accepted merely because the 14B tests and real-RustFS fault tests passed. PR 14B may be accepted strictly as test/evidence qualification, subject to its own gates. PR 14C must record an explicit human decision to (a) accept the documented bounded-but-unmetered transient allocation with operational limitations, (b) require a separately designed correction and its new resource tests, or (c) block the release. Until then, do not mark the risk RESOLVED or PR 14 acceptance DONE.
