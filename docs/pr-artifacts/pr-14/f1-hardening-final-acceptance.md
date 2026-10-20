# PR 14 — F1 hardening final acceptance

**Status: H1/F1 correctness-hardening ACCEPTED for the code slice; PR 14 remains NOT READY.**
Real RustFS acceptance and final-SHA CI are mandatory and remain blocked/unexecuted. This is not
a PR 14 completion claim.

| Item | Status |
|---|---|
| Gate 0 preflight | DONE |
| H4 validation order | DONE |
| H3 physical projection identity | DONE |
| H2 bounded top-K + integrated candidate budget | DONE |
| H5 mixed geo-distance sort | DONE |
| H1 shared work meter | DONE |
| W01–W06 mapped to executed tests | DONE |
| Exact-limit / one-over (aggregate, typed, scanned) | DONE |
| Charge-site audit (no bypass) | DONE |
| Cancellation through both adapters and phases | DONE |
| Standalone lexical/typed budget semantics | DONE (PR 7/10 + targeted unit suites) |
| M01–M06, G01–G05 | DONE |
| S/V/P regressions | DONE |
| fmt/clippy stable+MSRV | PASS |
| workspace tests stable+MSRV | PASS |
| coverage ≥85% | PASS (91.33% lines) |
| Real RustFS topology | **BLOCKED** (no endpoint) |
| Final-SHA CI | **NOT EXECUTED** (no push) |

## Executed evidence
- `pr14_f1_hardening`: 23 tests; `pr14_unified_mixed`: 14; `pr14_projection`: 10; `pr14_batch`: 12.
- `search::work`: 7 unit tests (exact limits, aggregate exhaustion, scanned formula, adapter
  forwarding/cancellation).
- `search::execute::budget_tests`: 22; `search::typed::tests`: 4; PR 7/10 budget suites green.

## Unresolved gates (block PR 14, not F1)
- Real RustFS integration harness in the required topology.
- Push final SHA and observe CI for that exact SHA.
- Separate PR 14 phases: F2 public cursor/PIT, F4 compound aggregation, PR 15 qualification.

No undocumented accounting or cancellation semantic was discovered; no STOP decision is required.
`docs/ROADMAP_V01.md` remains IN PROGRESS.
