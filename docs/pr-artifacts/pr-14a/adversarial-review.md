# PR 14A — adversarial review

| Risk challenged | Evidence / disposition |
|---|---|
| Key-only resume could accept a different sort tuple | Legacy `Cursor::new` has no continuation and is rejected with `CursorSortMismatch`; only complete V1 tuples resume (T10, T12). |
| Same key with changed query/sort could pass | Fingerprint and public sort are checked before execution; T07 asserts typed `CursorSortMismatch`. |
| Cursor from another snapshot could read current data | The pinned API uses only `pit.snapshot()`; wrong handle/PIT fails typed and never falls back (T06). |
| Expiry could be renewed with a later requested deadline | Returned expiry is `min(incoming expiry, requested deadline)`; T10 resumes only before the original deadline. |
| Cursor bytes bypass response/memory budgets | Response bytes include the cursor formula and T11 exercises exact/one-over response and memory boundaries. |
| Cursor failure erases sibling slots | T08 has exactly three ordered outcomes with only the middle expired slot failing. |
| Cancellation emits a partial cursor | T13 cancels at a later slot boundary; prior success remains, cancelled slot emits no cursor. |
| Pinned mutation view could drift | T09 retains the old PIT across upsert/delete/insert/refresh/commit/compact and compares the full old order; a new PIT sees the new generation. |
| Cursor is secretly a wire format | No serde/base64/wire parsing; continuations are private Rust values and are explicitly process-local. |

Residual risks are recorded in `implementation-evidence.md`. Real-RustFS and
broader fault qualification remain 14B work.

## Correction 01 adversarial review

- **256-byte member:** old fixed 64 charge is falsified; new charge is
  `24 + 24 + 256 = 304`, and a 1024-byte member is 1072.
- **Unicode:** `é` contributes 2 UTF-8 bytes, giving 50 rather than 49.
- **Many segments:** dot/index/wildcard segments each add 24; no free
  structural segments.
- **Overflow:** synthetic `u64::MAX` inputs return `None` through the same
  production helper; callers retain typed budget failure.
- **Exact/one-under:** long-path response and full-peak memory boundaries are
  tested through the real pinned executor; sibling rollback is asserted.
- **Physical vs logical:** the model is an admission charge, not a claim about
  allocator capacity, `Vec` capacity, or RSS.

**Blocked finding:** `UnifiedSearcher` returns `Missing` for JSON-path sort
values. The accounting correction does not change that executor, and numeric
JSON-path ordering is explicitly BLOCKED pending a separately approved fix.

## Correction 02 adversarial review

- **Keys contradict JSON values:** J01 uses `k00=30,k01=10,k02=20`; old code
  returned key order, corrected code returns `k01,k02,k00`.
- **Descending/tie/page boundaries:** J02 covers top_k 1/2/3; J03 covers a
  second JSON field and key tie-break.
- **Missing versus null:** J04 asserts the existing missing-last ordering in
  both directions.
- **Wildcard/Min/Max:** J05 independently enumerates both selectors and verifies
  a wildcard path without a selector fails.
- **Mixed query:** J06 asserts JSON ordering is retained alongside a positive
  lexical term, typed JSON range and aggregation.
- **PIT mutation/compaction:** J08 retains an old pin across update/delete/
  insert/refresh/commit/compact; old order is unchanged and a new pin sees the
  new generation.
- **Failure isolation:** J09 invalid sort and J11 expired middle cursor are
  typed per-slot failures; sibling slots remain successful.
- **Resource boundary:** J10 finds the real total-work exact/one-under boundary;
  occurrence traversal is work-charged through the shared meter.
- **Geo regression:** J12 proves geo-distance order remains intact.

### Residual risk R-14A-JSON-MEM — unmetered temporary JSON sort occurrences

**Status:** OPEN; pre-existing in `TypedSearcher`, reused by `UnifiedSearcher` in Correction 02. **Disposition:** disclose for explicit human acceptance at PR 14A review; do not claim `BatchMemoryBytes` caps all transient JSON-sort allocations. This risk is not resolved by the passing cursor-budget tests.

`typed::json_sort_value` calls `JsonAccess::occurrences(field_id, doc_id, guard, None)`. The occurrence vector is subject to existing JSON path occurrence/depth/member and scan/work bounds, and traversal work is charged through `ScanGuard`/`MixedWorkMeter`. However, passing `None` for the memory sink means the temporary `Vec<JsonOccurrence>` and its owned contents are **not charged to `SlotMemoryScope` / cumulative batch retained-memory accounting**. Thus a workload can consume additional transient heap memory within those logical limits despite satisfying the batch memory budget. This is a **resource-governance coverage gap**, not evidence of a confirmed out-of-bounds allocation or a demonstrated correctness failure.

**Required follow-up:** during 14B resource/fault qualification, explicitly evaluate high-occurrence JSON-path sorting under constrained budgets and record peak RSS/allocations separately from logical memory metering. If measured impact or the intended `BatchMemoryBytes` contract requires strict accounting, authorize a **separate, design-reviewed implementation fix** shared by both typed and unified sort paths; do not silently expand PR 14A or treat a real-provider test alone as remediation. 14C release acceptance must explicitly decide whether this documented residual risk is acceptable or blocking. **Owner:** Quervant maintainer / human architecture reviewer. **Closure evidence:** an approved scoped fix with exact/one-over memory and cancellation/failure tests, or a recorded human risk-acceptance decision with justified bounds and limitations.
