# PR 14 — P2B Phase A implementation (batch meter split)

Phase A only: split the meter and prove independent borrowing. No candidate/projection/
typed/geo/JSON accounting was added (Phases B–F remain).

## Changed files

- `search/batch_meter.rs`: replaced monolithic `BatchExecutionMeter` fields with three disjoint
  sub-meters:
  - `BatchWorkMeter { limit, used }` — `preflight_work`, `commit_work` (checked, exact
    `BatchAggregate` errors; rejected preflight leaves `used` unchanged).
  - `BatchMemoryMeter { limit, current, peak }` — `preflight_reserve`, `commit_reserve`,
    `reserve_memory`, checked `release_memory` (underflow → `CorruptIndex`, never saturating).
  - `BatchResponseMeter { limit, used }` — `preflight_response`, `commit_response`,
    `charge_response`.
  - `BatchExecutionMeter { work, memory, response }` and `new(work, memory, response)`.
  - `BatchMeterError`/`to_search_error` preserved.
- `search/work.rs`: `MixedWorkMeter.batch` and `with_batch` now borrow `&mut BatchWorkMeter`;
  charge ordering (local preflight → batch preflight → commit both) unchanged.
- `search/unified.rs`: `collect_mixed` passes `&mut batch.work` when constructing the mixed
  meter.
- `search/batch.rs`: retained response calls use `meter.memory.*` / `meter.response.*`.

## Borrow proof

`BatchExecutionMeter` fields are independently borrowable. `a01_disjoint_work_memory_borrows`
holds `&mut meter.work` and `&mut meter.memory` simultaneously, mutates both, and asserts
independent counters. No `RefCell`, `unsafe`, globals or duplicate meters.

## Semantics preserved

Work units, `1 + freq` scanned accounting, response byte formula, error kinds, local-vs-batch
provenance, and all query results are unchanged. Assertion: `pr14_batch`,
`pr14_batch_governance`, `pr14_unified_cursor`, `pr14_f1_hardening` all green.
