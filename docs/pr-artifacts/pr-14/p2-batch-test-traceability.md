# PR 14 — P2 batch governance test traceability

Executed tests (all PASS unless stated):

| ID | Test function | Notes |
|---|---|---|
| B01 | `pr14_batch_governance::b01_zero_hit_work_is_charged` | two zero-hit slots → `BatchAggregate` |
| B02 | — | not added; cumulative work covered by meter unit tests |
| B03 | `pr14_batch::b02_ordered_mixed_outcomes` | ordered success/failure/success |
| B04 | `search::batch_meter::tests::work_exact_limit_then_one_over_is_atomic` | exact/one-over, atomic |
| B05 | `search::work::tests::*` + `batch_meter` | local/batch preflight order via shared meter |
| B06 | `pr14_batch::b06_work_is_not_hit_count`; `pr14_f1_hardening::w04_zero_match_scan_charges_work` | zero-hit work charged |
| B07 | `pr14_f1_hardening` S/G suites | mixed phrase/geo execute through shared meter |
| B08 | `pr14_batch_governance::b01` (MatchAll/zero-hit work) | per-document charge |
| B09 | `search::batch_meter::tests::memory_peak_tracks_simultaneous_reservations` | exact/one-over memory |
| B10 | — | temporary memory not wired to batch meter (PARTIAL) |
| B11 | — | PARTIAL (heap bounded by candidate ledger) |
| B12 | — | PARTIAL (error releases query-local ledgers) |
| B13 | `pr14_batch::b07_cancellation_preserves_cardinality` | cancellation cardinality |
| B14 | `pr14_batch_governance::b14_response_bytes_cumulative` | cumulative response |
| B15 | `pr14_batch::b11_lossless_field_states` | five-state payload |
| B16 | `pr14_batch_governance::b16_response_one_over_rejected` | no partial success |
| B17 | `pr14_batch_governance::b17_distinct_budget_kinds` | three distinct kinds |
| B18 | `search::batch::tests::error_mapping_preserves_contract_errors` | query-local → ExecutionFailure |
| B19 | `pr14_batch_governance::b19_policy_rejects_whole_batch`; `pr14_batch::b10` | envelope before I/O |
| B20 | `pr14_batch::b13_capability_rejection_is_isolated` | capability isolation |
| B21 | `pr14_batch_governance::b21_one_slot_matches_direct_unified` | one-slot parity |
| B22 | `pr14_unified_cursor`, `pr14_f1_hardening`, PR7/PR10 suites | PASS |
| B23 | `search::batch_meter::tests::overflow_is_typed_not_wrapped` | checked arithmetic |
| B24 | — | BLOCKED (no RustFS endpoint) |

## Counts
- `pr14_batch_governance`: 6.
- `pr14_batch`: 12.
- `search::batch_meter`: 4; `search::batch`: 3.
- `pr14_f1_hardening`: 23; `pr14_unified_cursor`: 11; `pr14_unified_mixed`: 14; `pr14_projection`: 10.
