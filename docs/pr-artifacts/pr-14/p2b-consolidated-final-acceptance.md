# PR 14 — P2B consolidated status (partial; not accepted)

Current HEAD: `7c0c2c961bfb759c5c2307ac4914a44b15d58297` (clean tree).

## Verified from source and executed tests

| Checkpoint | Status | Evidence |
|---|---|---|
| A — disjoint `work`/`memory`/`response` sub-meters | VERIFIED-EXISTING | `search::batch_meter` 5/5, incl. `a01_disjoint_work_memory_borrows` |
| B — `MemoryCharge`/`SlotMemoryScope`, checked reserve/release/finish | VERIFIED-EXISTING | `search::memory` 10/10 (`b01`–`b10`) |
| C1 — candidate local preflight/commit primitives | VERIFIED-EXISTING | `budget_tests::c1*` 5/5 |
| C2 — segment ledger ephemeral sink | **NOT IMPLEMENTED** | ledger still local-only |
| C3 — K+1 heap batch binding | **NOT IMPLEMENTED** | heap still local-only |
| D — typed/geo/JSON scratch | **NOT IMPLEMENTED** | geo scratch has saturating release |
| E — projection/response handoff | **NOT IMPLEMENTED** | retained response reserved after slot; projection release saturates |
| F — B10a–B13j acceptance | **NOT IMPLEMENTED** | `pr14_batch_memory` absent |

This session reached its executable capacity before C2–F could be compiled, tested and validated.
No partial or unvalidated accounting code was shipped.

## Exact next implementation (C2), frozen

1. Add checked `MemoryCharge::preflight_release(bytes)` in `search/memory.rs`, implemented by
   `SlotMemoryScope` using temporary and meter balances; add unit tests.
2. `SegmentCandidateLedger::reserve/release/transfer_to_global` take an **ephemeral**
   `Option<&mut dyn MemoryCharge>` argument; local preflight → batch preflight → commit both;
   release validates both before mutating. `transfer_to_global` changes no batch bytes.
3. Thread the ephemeral sink through `evaluate_lexical_with` and its ledger call sites; the typed
   callback and `SearchWork::shared` must not capture the sink.
4. Standalone callers pass `None`; the mixed caller passes `Some(&mut scope)`.
5. Add C2 tests (`c2_segment_exact`, one-over atomicity, local/batch rejection isolation,
   overflow, underflow, two-segment reuse, retained-response overlap, cancellation cleanup,
   typed-callback borrow compiles, standalone parity) and run the full gates.

Then C3, D, E, F per the consolidated plan.

## Status

**P2B NOT ACCEPTED. PR 14 NOT READY.** PR14 still requires P3 compound aggregation, P4 real
RustFS acceptance, qualified benchmarks and final-SHA CI. `docs/ROADMAP_V01.md` remains IN
PROGRESS.
