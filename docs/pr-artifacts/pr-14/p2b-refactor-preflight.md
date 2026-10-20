# PR 14 — P2B ownership refactor preflight (STOP report)

- Branch: `dev/pagination`
- `main`: `7ca1b2ec59fec648602e0e4a52e8f903a596f106` (recorded at last verified preflight)
- Branch HEAD: `dd27c9a0f862b00ae7bd4942f1a07ecc311bfeaf`; working tree contains only prior `p2b-memory-*` artifact files.
- Baseline suites (executed at this HEAD): `pr14_batch` 12, `pr14_batch_governance` 6,
  `pr14_f1_hardening` 23, `pr14_unified_cursor` 11 — all pass. Full gates previously passed at
  90.84% lines.

## Verified signatures

- `batch_meter.rs`: monolithic `BatchExecutionMeter { work_limit/work_used, memory_limit/current/peak, response_limit/used }`; `reserve_memory`/`release_memory`/`charge_response`.
- `work.rs`: `MixedWorkMeter { ..., batch: Option<&mut BatchExecutionMeter> }`, `with_batch`.
- `unified.rs`: `search_with_batch(..., &mut BatchExecutionMeter)` → `collect_mixed` → `MixedWorkMeter::with_batch`.
- `execute.rs`: `CandidateBudget` (plain counters, no lifetime param), `SegmentCandidateLedger<'a>` borrows it.
- `projection.rs`: `ProjectionLedger` (saturating `release`), separate from the batch meter.
- `batch.rs`: retained response memory charged only after `execute_slot`.

## Ownership/borrow analysis (confirms the plan's premise)

Work and memory must be charged concurrently during a slot, but `MixedWorkMeter` already holds
`&mut BatchExecutionMeter`. Binding `CandidateBudget`/`ProjectionLedger` to the same object would
be two live `&mut` aliases. The frozen design resolves this by splitting the meter into disjoint
fields:

```text
BatchExecutionMeter { work: BatchWorkMeter, memory: BatchMemoryMeter, response: BatchResponseMeter }
```

so a slot lends `&mut work` to `MixedWorkMeter` and `&mut memory` to `SlotMemoryScope`; distinct
field borrows are legal (no `RefCell`/unsafe/globals).

## Ripple (not executed)

- `CandidateBudget` → `CandidateBudget<'m>` + `Option<&'m mut dyn MemoryCharge>`, `SegmentCandidateLedger` lifetime; all `execute_search`/mixed call sites.
- `ProjectionLedger` checked release + optional memory adapter.
- `MixedWorkMeter`/`with_batch` → `BatchWorkMeter`.
- `unified.rs` split borrows, `CandidateSelection` ownership wrapper, projection/response handoff.
- `typed.rs` geo/JSON scratch wiring; `batch.rs` atomic retained-memory+response admission.
- New `search/memory.rs` `SlotMemoryScope`; `pr14_batch_memory` B10a–B13j.

## STOP decision

This is an execution-scope STOP, not a semantic contradiction: the design above is safe and
matches the frozen contract, but completing it requires a validated cross-module lifetime refactor
that cannot be finished in the remaining session. No production edits were made; no partial or
degraded accounting was shipped.
