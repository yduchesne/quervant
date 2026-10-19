# PR 14 — P2B consolidated status (partial; not accepted)

Current tree: `dev/pagination` with uncommitted Phase C2–E changes (see per-phase artifacts).

## Verified from source and executed tests

| Checkpoint | Status | Evidence |
|---|---|---|
| A — disjoint `work`/`memory`/`response` sub-meters | VERIFIED-EXISTING | `search::batch_meter` 5/5, incl. `a01_disjoint_work_memory_borrows` |
| B — `MemoryCharge`/`SlotMemoryScope`, checked reserve/release/finish | VERIFIED-EXISTING | `search::memory` 10/10 (`b01`–`b10`) |
| C1 — candidate local preflight/commit primitives | VERIFIED-EXISTING | `budget_tests::c1*` 5/5 |
| C2 — segment ledger ephemeral sink | **IMPLEMENTED/VALIDATED** | `p2b-phase-c2-implementation.md`; `c2_*` 9 |
| C3 — K+1 heap batch binding | **IMPLEMENTED/VALIDATED** | `p2b-phase-c3-implementation.md`; `c3_*` 9 |
| D — typed/geo/JSON scratch | **IMPLEMENTED/ACCEPTED** | `p2b-phase-d-implementation.md`; 8 path tests |
| E — projection/response handoff | **IMPLEMENTED** | `p2b-phase-e-implementation.md`; 4 E tests, checked release |
| F — B10a–B13j acceptance | **NOT IMPLEMENTED** | `pr14_batch_memory` absent |

Phase F (`pr14_batch_memory` B10a–B13j and final evidence/review artifacts) remains open.
Real RustFS acceptance, qualified benchmarks and final-SHA CI remain PR 14 P4 blockers.

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
