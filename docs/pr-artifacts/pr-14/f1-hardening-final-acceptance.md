# PR 14 — F1 hardening final acceptance

**Status: NOT COMPLETE — STOP H1 open.** PR 14 overall remains IN PROGRESS.

| Item | Status |
|---|---|
| Gate 0 preflight | DONE |
| H4 validation order | DONE |
| H3 physical projection identity | DONE |
| H2 bounded top-K + integrated candidate budget | DONE |
| H5 mixed geo-distance sort | DONE |
| H1 shared work meter | **STOP H1 — NOT IMPLEMENTED** |
| H6 tests | PARTIAL (S/V/G/M/P added; W blocked) |
| fmt/clippy stable+MSRV | PASS |
| workspace tests stable+MSRV | PASS |
| coverage ≥85% | PASS (91.25% lines) |
| RustFS / final-SHA CI | BLOCKED / NOT EXECUTED |

## STOP H1 — exact blocking fact

`SearchWork` (`search/execute.rs`) and `ScanGuard` (`search/typed.rs`) each own independent
counters and are simultaneously live for one mixed segment: `evaluate_lexical_with` holds
`&mut SearchWork` while invoking the typed callback, which holds `&mut ScanGuard`. Making them
share one `MixedWorkMeter` requires threading a new `WorkCharge` seam through
`build_leaf_data` → `build_phrase` → `phrase.rs::match_phrase` and `expand_query`/`compute_stats`,
plus a mixed `ScanGuard` adapter. Attempting this without the full seam would either double-count
or require unsafe/shared interior mutability, both prohibited.

**Minimum decision required:** approve the `WorkCharge` seam (or an equivalent shared-meter
signature) across `execute.rs`, `expand.rs`, `score.rs`, `phrase.rs`, and `typed.rs`, so
`MixedWorkMeter` can own the single total counter while preserving PR 7/PR 10 charging units.

## Remaining after H1
- W01–W06 tests and I01/I02 evidence.
- M01/M03/M04/M05/M06, G04/G05 full coverage.
- Push and final-SHA CI; real RustFS remains a separate PR 14 gate.
