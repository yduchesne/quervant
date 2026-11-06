# PR 15G-D finalization qualification

**Status:** `D_NEGATIVE_CLOSED_HX_PARTIAL_REVIEW_PENDING`

## Disposition history

| Stage | Result |
|---|---|
| D1 isolated campaign | Qualified; initial positive evidence |
| D1+D2 three-arm confirmation | `NOT_RECONFIRMED`; D1 absent inconclusive, 10K guardrails regressed |
| First D2-only campaign | `MEASUREMENT_BLOCKED`; A 100K rare drift 1.2994 > 1.25 |
| Corrected D2-only campaign | Qualified, then `D2_ONLY_PERFORMANCE_REJECTED` |
| D2 rejection reason | DX-P01 failed (100K common/K10 inconclusive); DX-P02 failed (10K rare `A_FASTER`) |
| Final search source | Byte-identical to accepted A `ca065a2`; D1/D2 absent |

Earlier D1/D2/confirmation/blocked reports and raw evidence remain unchanged.

## Harness closeout

The controller now contains tracked exact-edit source proof, frozen
nearest-rank sample-summary validation, manifest/lane/warmup identity checks,
a v2 18-file seal written before drift classification, blocked-report output,
and byte-exact verify-only for both qualified and blocked reports.

Python suite: **24 isolated-D2 tests plus 26 historical D tests = 50 passed**
at the time of closeout. The suite includes a real-Git synthetic 15/0 + 43/1
source fixture with negative mutations, sealed blocked/qualified campaigns,
tamper rejection, legacy-unsealed refusal and report-pair coexistence.

## HX-A07

**PARTIAL.** The source/report adversarial areas are now exercised, but this
closeout does not claim every one of the 47 historical rows has a one-to-one
deterministic assertion. Per-row status is in `hx-test-traceability.md`.
HX-A07 is therefore not marked PASS.

## Other gates

| Gate | Status |
|---|---|
| Historical evidence immutable | PASS |
| Exact A search blobs restored | PASS |
| Exact CI at `7627cd6` | PASS — run `42070580673` |
| Final docs-head CI | PENDING at closeout |
| Real RustFS | PASS on the source state before E; E was rejected and source rolled back |
| Independent review | PENDING |
