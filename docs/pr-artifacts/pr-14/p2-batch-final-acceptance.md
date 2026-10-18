# PR 14 — P2 batch governance final acceptance

**Status: P2 PARTIAL — NOT FULLY ACCEPTED. PR 14 remains NOT READY / IN PROGRESS.**

| Item | Status |
|---|---|
| `BatchExecutionMeter` work/response/memory counters | DONE |
| Policy-resolved effective ceilings (all four batch kinds) | DONE |
| Shared `MixedWorkMeter` → batch work sink (atomic) | DONE |
| Per-class work accounting (lexical/typed/mixed/MatchAll/zero-hit) | DONE (per-document charge) |
| Typed error provenance (`BatchAggregate` vs query-local) | DONE |
| Cumulative response-byte accounting | DONE |
| Response memory retention | DONE (retained until meter drop) |
| Temporary query memory in batch peak | **PARTIAL** |
| B01–B23 | PARTIAL — see traceability |
| B24 real RustFS | BLOCKED |
| Stable + MSRV fmt/clippy/tests | PASS |
| Coverage ≥85% | PASS — 90.84% lines |
| Final-SHA CI / benchmarks | NOT EXECUTED |

## Required to complete P2
- Wire candidate/heap/projection temporary allocations to `BatchExecutionMeter` memory
  reservations (RAII/scoped) so B10–B13 prove peak retention and release.
- Add the remaining dedicated tests (B02, B05 reverse-order, B07 dedicated, B15, B18, B20).
- B24 real RustFS evidence and final-SHA CI.

## Unchanged / out of scope
P3 compound aggregation, P4 real-provider acceptance/benchmarks, public PIT cursors and all
persisted/segment formats remain unchanged. `docs/ROADMAP_V01.md` stays IN PROGRESS.
