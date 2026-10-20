# PR 14 — P2B batch peak-memory adversarial review

**P2B not implemented, so B10–B13 invariants remain unproven.**

| Risk | Current state | Disposition |
|---|---|---|
| Retained slot-1 response not counted against slot-2 candidate peak | `memory_current` includes only retained responses; slot temporaries use query-local ledgers | **OPEN** |
| Candidate heap/segment scratch not in batch peak | same | **OPEN** |
| Geo/JSON scratch not in batch peak | same | **OPEN** |
| Projection ledger not in batch peak; saturating release | same | **OPEN** |
| Failed slot leaves temporary reservations | query-local Drop releases them; batch memory has no temporary reservations to leak | **PARTIAL** |
| Work/response semantics | implemented and tested | PASS |
| Local-vs-batch error confusion | local `ResourceLimit` → `ExecutionFailure`; batch → exact kind | PASS |

The prescribed safe design (disjoint work/memory sub-meters + slot-scoped reservations) is
recorded in `p2b-memory-preflight.md`. Implementing it requires the cross-module lifetime
refactor documented there; it was not attempted to avoid an unvalidated partial meter.
