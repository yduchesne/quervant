# PR 14 — Corrective test traceability

| ID | Test symbol | Status |
|---|---|---|
| P-lossless (I06) | `tests/pr14_batch.rs::b11_lossless_field_states` | PASS |
| E-cancel/resource/corrupt mapping (I10) | `search/batch.rs::tests::error_mapping_preserves_contract_errors` | PASS |
| B ordered slots (I08) | `b01`–`b10` | PASS |
| Batch shared ledger (I09 partial) | `b06_shared_budget_not_reset` | PASS |
| Typed/JSON/IP correctness (I15) | `pr14_typed_predicates` (12), `pr14_json` (13) | PASS |
| Projection five-state (I06/I07 partial) | `pr14_projection` (10) | PASS |
| Aggregation adapter (I11 partial) | `pr14_aggregation` (5) | PASS |

## Not implemented / not evidenced

| ID | Required | Status |
|---|---|---|
| I01 mixed Boolean equivalence | M01–M07, X01 | NOT IMPLEMENTED (F1) |
| I03 BM25 under extraction | L01–L06 | NOT IMPLEMENTED |
| I05 full-tuple cursor | C01–C12 | NOT IMPLEMENTED (C1) |
| I07 exact `HitRef` projection | P03–P06 | NOT IMPLEMENTED (rescan still key-based) |
| I09 cumulative work/memory | G01–G12 | NOT IMPLEMENTED (C3) |
| I11 mixed aggregation | A01–A08 | NOT IMPLEMENTED (C4/C8) |
| I12 zero-GET instrumentation | R01–R04 | NOT EXECUTED |
| I14 RustFS oracle equivalence | X01–X10 | NOT EXECUTED (C10) |
| I16 final SHA CI | Q01–Q09 | NOT EXECUTED |
