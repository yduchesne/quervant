# PR 14 — F1 hardening final acceptance

**Status: NOT READY (F1 hardening slice otherwise complete; PR 14 overall blocked).**

| Item | Status |
|---|---|
| Gate 0 preflight | DONE |
| H4 validation order | DONE |
| H3 physical projection identity | DONE |
| H2 bounded top-K + integrated candidate budget | DONE |
| H5 mixed geo-distance sort | DONE |
| H1 shared work meter | **DONE** |
| H6 tests | DONE for S/V/G/M02/P02/W04/W06; M/G boundaries PARTIAL |
| fmt/clippy stable+MSRV | PASS |
| workspace tests stable+MSRV | PASS |
| coverage ≥85% | PASS (91.28% lines) |
| RustFS real topology | **BLOCKED** (no endpoint) |
| Final-SHA CI | **NOT EXECUTED** (no push) |

## Remaining before PR 14 READY
- Remaining M01/M03–M06 and G04/G05 boundary tests.
- Real RustFS integration harness in required topology.
- Push final SHA and observe CI for that exact SHA.
- Separate PR 14 phases F2 (public cursor/PIT), F4 (compound aggregation), F5 acceptance.

No DONE/merge-ready claim. `docs/ROADMAP_V01.md` remains IN PROGRESS.
