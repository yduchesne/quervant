# PR 14 — P2B Phase C status (not implemented)

## Verified state at HEAD `09af350`

- Phase A verified in source: `BatchExecutionMeter { work, memory, response }`,
  `MixedWorkMeter` borrows `&mut BatchWorkMeter`, `a01_disjoint_work_memory_borrows` passes.
- Phase B verified: `search/memory.rs` registered, `SlotMemoryScope`/`MemoryCharge`, `b01`–`b10`
  all pass (10/10); `search::batch_meter` 5/5.
- Existing PR14 regressions green (batch 12, governance 6, cursor 11, f1 23).

## Phase C is the next assignment and was not implemented

Reason: remaining session execution capacity was insufficient to complete and validate the
candidate/segment/K+1 binding safely. This is a **capacity stop**, not a semantic or repository
contradiction. No production edits were made in this pass and no partial accounting was shipped.

## Exact next edits (design already frozen)

1. `CandidateBudget`: split `reserve_global_bytes`/segment reserve into pure **preflight** and
   infallible-after-preflight **commit**; keep `new(&limits)` and standalone wrappers.
2. `SegmentCandidateLedger`: take an **ephemeral** `Option<&mut dyn MemoryCharge>` per
   reserve/release call (not stored as a long-lived owner); preflight local, then batch, then
   commit both; release both at segment end and on early return/Drop.
3. `evaluate_lexical_with`: accept the optional ephemeral scope and pass it to the segment
   ledger only; do not hold it across the typed callback (Phase D adds typed scratch).
4. `collect_mixed`: destructure `&mut batch.work` and `&mut batch.memory` from the same
   `BatchExecutionMeter` (disjoint fields), build `MixedWorkMeter` and `SlotMemoryScope`, and use
   the scope for `reserve_global_bytes_with`/`release_global_bytes_with`.
5. K+1 heap: reserve the incoming entry before push; for replacement, preflight only the net
   delta (`charge - evicted.charge`) while the evicted entry is still live, then pop, release the
   evicted charge, and commit the incoming charge; never expose a partial heap on rejection.
6. Tests: segment exact/one-over, local-first and batch-first atomicity, two-segment heap
   overlap, larger/smaller replacement, noncompetitive candidate zero-charge, cancellation/error
   cleanup, K+1 cursor parity, standalone lexical parity.

## Status

P2B remains **NOT ACCEPTED**. Phase C (and D–F) outstanding; PR 14 remains NOT READY pending P3,
P4 real RustFS, benchmarks and final-SHA CI.
