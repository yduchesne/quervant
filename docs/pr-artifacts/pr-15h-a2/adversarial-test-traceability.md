# PR 15H-A2 — adversarial test traceability

All results were executed at candidate `569132d` or on the final rollback source
where noted. Test-only code that referenced the rejected helper was removed
mechanically by restoring `execute.rs`/`unified.rs`; the independent public-path
integration suite remains and passes.

## Unit matrix

| ID | Test | Candidate | Final rollback |
|---|---|---|---|
| A2-U01 | `a2_u01_u06_route_boundaries_and_counters` (0 postings) | PASS | removed with helper |
| A2-U02 | same (1 posting) | PASS | removed with helper |
| A2-U03 | same (4,999) | PASS | removed with helper |
| A2-U04 | `a2_u04_high_cardinality_linear` (12,500 / 49,999) | PASS | removed with helper |
| A2-U05 | `a2_u01_u06_route_boundaries_and_counters` (8,191) | PASS | removed with helper |
| A2-U06 | same (8,192 / 8,193) | PASS | removed with helper |
| A2-U07 | `a2_u07_work_budget_boundary` | PASS | removed with helper |
| A2-U08 | `a2_u08_cancellation_parity` | PASS | removed with helper |
| A2-U09 | `a2_u09_u12_u26_linear_differential_and_cursor` | PASS | removed with helper |
| A2-U10 | `a2_u10_u27_two_segment_routes` | PASS | removed with helper |
| A2-U11 | `a2_u11_live_filtered_dispatch` | PASS | removed with helper |
| A2-U12 | `a2_u09_u12_u26_linear_differential_and_cursor` (tf 1/3) | PASS | removed with helper |
| A2-U13 | `a2_u13_u14_linear_route_budget` (exact) | PASS | removed with helper |
| A2-U14 | same (one under) | PASS | removed with helper |
| A2-U15 | `a2_u15_u16_u28_ineligible_routes` | PASS | removed with helper |
| A2-U16 | same (cursor/aggregation) | PASS | removed with helper |
| A2-U17 | `a2_u17_dispatch_shape_guard` | PASS | removed with helper |
| A2-U18 | historical `h_a_u10_non_increasing_candidates_fail_closed` | PASS | removed with helper |
| A2-U19 | `a2_u19_callback_subset_ordering` | PASS | removed with helper |
| A2-U20 | historical `h_a_u22_batch_memory_charge_boundary` | PASS | removed with helper |
| A2-U21 | historical `h_a_u16_reserve_fault_typed_and_recovered` | PASS | removed with helper |
| A2-U22 | historical `h_a_u17_u23_score_fault_and_double_fault_precedence` | PASS | removed with helper |
| A2-U23 | `a2_u23_sparse_empty_zero_linear` (100K sparse/empty) | PASS | removed with helper |
| A2-U24 | `cargo build -p quervant-core --release` | PASS | PASS |
| A2-U25 | corruption path before dispatch: `pr15h_a2_dispatch::a2_i07` and existing segment corruption tests | PASS | PASS |
| A2-U26 | `a2_u09_u12_u26_linear_differential_and_cursor` (K/cursor) | PASS | removed with helper |
| A2-U27 | `a2_u10_u27_two_segment_routes` (seed `0x15A2`, two segments) | PASS | removed with helper |
| A2-U28 | `a2_u15_u16_u28_ineligible_routes` | PASS | removed with helper |

Historical helper/score/ledger tests reused unchanged at candidate:
`search::execute::linear_term_tests` 8 passed, `phase4_tests` 15 passed.

## Public-path integration matrix (final rollback source)

| ID | Test | Result |
|---|---|---|
| A2-I01 | `a2_i01_local_commit_reopen_boundary` | PASS |
| A2-I02 | `a2_i02_100k_mixed_cardinality` | PASS |
| A2-I03 | `a2_i03_two_segment_live_dispatch_and_pit` | PASS |
| A2-I04 | `a2_i04_candidate_budget_boundary` | PASS |
| A2-I05 | `a2_i05_cancellation_high_and_low` | PASS |
| A2-I06 | `a2_i06_sort_cursor_typed_negative` | PASS |
| A2-I07 | `a2_i07_corruption_fail_closed` | PASS |
| A2-I08 | `a2_i08_fs_reopen_and_deterministic_rebuild` | PASS |
| A2-I09 | real-RustFS cold/warm semantics covered by the executed `pr15g_a_rustfs` / `pr13_remote` suites on the final source | PASS (regression) |
| A2-I10 | `pr13_remote_proxy`, `pr13_crash_rustfs` k0/k05 | PASS |

## Controller matrix

`python3 -m unittest discover -s benchmarks/pr15h_a2 -p 'test*.py'` → 26 passed.
Covered: B01–B03 lane/idle/seal, B04–B12 source/sample/drift, B13–B16 verdict and
blocked, B17 tamper, B18 sanitizer, B19 path confinement, B20 A2 allowlist,
B21 ancestry refusal, B22 historical-artifact preservation.
