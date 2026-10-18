# PR 14 — F1 hardening test traceability (verified)

State: `dev/pagination`, base `69d47ba` + uncommitted H1 verification edits. All rows below were
executed locally and passed.

## W-series (work meter)

| ID | Concrete test function | Executed result |
|---|---|---|
| W01 | `search::work::tests::shared_adapters_forward_charges_and_cancellation` (one meter receives lexical 3 + typed 2) | PASS |
| W02 | `search::work::tests::aggregate_exhaustion_blocks_typed_after_lexical` (6+4 = L=10, then typed 1 rejected) | PASS |
| W03 | `search::work::tests::total_exact_limit_then_one_over`; `typed_exact_limit_then_one_over`; `scanned_exact_limit_then_one_over` | PASS |
| W04 | `pr14_f1_hardening::w04_zero_match_scan_charges_work` (stats/scan path); `w04b_phrase_charges_shared_meter` (phrase path); charge-site audit in adversarial review | PASS |
| W05 | `search::execute::budget_tests` (22, owned `SearchWork`); `search::typed::tests` (4); `pr07_amendment01/02/03`; `pr10_aggregate_memory`; `pr10_cursor` | PASS |
| W06 | `search::work::tests::shared_adapters_forward_charges_and_cancellation` (alternating); `scanned_charges_add_one_plus_freq`; `pr14_f1_hardening::w06_mixed_cancellation`; `m06_multi_segment_cancellation` | PASS |

## S/V/G/M/P

| ID | Concrete test function | Result |
|---|---|---|
| S01 | `pr14_f1_hardening::s01_term_parity` (bit-exact `f64::to_bits`) | PASS |
| S02 | `s02_phrase_parity` | PASS |
| S03 | `s03_duplicate_nested_parity` | PASS |
| S04 | `pr14_unified_mixed::m07_not_cannot_resurrect_tombstones` | PASS |
| S05 | `s05_two_segment_statistics_parity` | PASS |
| V01 | `v01_unknown_sort_field` | PASS |
| V02 | `v02_noncolumnar_sort_field` | PASS |
| V03 | `v03_multivalue_selector_required` | PASS |
| V04 | `v04_json_path_on_non_json_field` | PASS |
| V05 | `v05_invalid_geo_sort_field` | PASS |
| G01 | `g01_geo_ascending` | PASS |
| G02 | `g02_geo_descending` | PASS |
| G03 | `g03_geo_missing_first` | PASS |
| G04 | `g04_multivalue_minimum_distance` (multi GeoPoint `mloc`, min distance) | PASS |
| G05 | `g05_geo_tie_break_by_key` (ascending and descending ties) | PASS |
| M01 | `m01_top_k_retention_and_total` (K=2, 5 matches, `total_hits=5`) | PASS |
| M02 | `m02_top_k_total_hits` | PASS |
| M03 | `search::execute::budget_tests::production_global_bytes_exact_then_one_over_and_release` | PASS |
| M04 | `m04_eviction_tie_break_by_key` (K=1, tie → smallest key) | PASS |
| M05 | `m05_long_keyword_sort_values` (2×4096-byte sort values) | PASS |
| M06 | `m06_multi_segment_cancellation` | PASS |
| P02 | `p02_projection_uses_current_version` | PASS |
| P01/P03–P05 | `pr14_projection` p01/p03/p06 + mixed path | PASS |

## Counts
- `pr14_f1_hardening`: **23** tests, 0 failed.
- `pr14_unified_mixed`: 14; `pr14_projection`: 10; `pr14_batch`: 12.
- `search::work` unit tests: 7.
- I01–I10 each have executed evidence above.

## Remaining unresolved (not F1 code)
- Real RustFS integration: BLOCKED (no endpoint).
- Final-SHA CI: NOT EXECUTED.
