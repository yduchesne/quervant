# PR 14 — P2B ownership refactor adversarial review

P2B is not implemented, so the batch peak-memory invariants remain unproven:

| Risk | State |
|---|---|
| Retained previous responses overlap later slot scratch | OPEN |
| Candidate heap/segment scratch in batch peak | OPEN |
| Geo/JSON scratch in batch peak | OPEN |
| Projection handoff double-count/uncount | OPEN |
| Heap replacement atomicity | OPEN |
| Work/response accounting | PASS (existing P2A) |
| Local-vs-batch error provenance | PASS (existing P2A) |

Safe design is specified in `p2b-refactor-preflight.md`; no degraded substitute was shipped.
