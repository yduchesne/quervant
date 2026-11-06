# PR 15H-A — adversarial test traceability

The matrix below was executed against candidate
`dce8f02405e6541d478c2072a0332af192ed2945`. All listed tests passed. After the
qualified performance rejection, `execute.rs` and `unified.rs` were restored to
the baseline blobs, which mechanically removed the `#[cfg(test)]` witnesses and
the tests that referenced the rejected helper. The integration suite does not
reference crate-private helpers and remains on the final source.

## Unit matrix (candidate SHA)

`cargo test -p quervant-core --lib search::execute::linear_term_tests` → 8 passed.

`cargo test -p quervant-core --lib search::unified::phase4_tests` → 15 passed
(8 pre-existing + 7 PR 15H-A additions).

| ID | Test | Result |
|---|---|---|
| U01 | `h_a_u01_u02_linear_counters_and_fallback_bypass` | PASS |
| U02 | `h_a_u01_u02_linear_counters_and_fallback_bypass` | PASS |
| U03 | `h_a_u03_u04_noneligible_shapes_use_fallback` | PASS |
| U04 | `h_a_u03_u04_noneligible_shapes_use_fallback` | PASS |
| U05 | `h_a_u05_u09_u21_differential_scores_and_cursor` | PASS |
| U06 | `h_a_u06_live_filtering` | PASS |
| U07 | `h_a_u01_u02_linear_counters_and_fallback_bypass`, `h_a_u07_predicate_and_work_parity` | PASS |
| U08 | `h_a_u08_runtime_shape_guard` | PASS |
| U09 | `h_a_u05_u09_u21_differential_scores_and_cursor` (tf 1 and 3, varied norms) | PASS |
| U10 | `h_a_u10_non_increasing_candidates_fail_closed` | PASS |
| U11 | `h_a_u11_u12_matched_ledger_boundary` | PASS |
| U12 | `h_a_u11_u12_matched_ledger_boundary` | PASS |
| U13 | `h_a_u13_u14_scored_ledger_boundary` | PASS |
| U14 | `h_a_u13_u14_scored_ledger_boundary` | PASS |
| U15 | `h_a_u15_global_budget_shared` | PASS |
| U16 | `h_a_u16_reserve_fault_typed_and_recovered` | PASS |
| U17 | `h_a_u17_u23_score_fault_and_double_fault_precedence` | PASS |
| U18 | `h_a_u10_non_increasing_candidates_fail_closed` (repeated postings) | PASS |
| U19 | `h_a_u19_cancellation_parity` | PASS |
| U20 | `h_a_u20_and_term_fallback_ineligible` | PASS |
| U21 | `h_a_u05_u09_u21_differential_scores_and_cursor` | PASS |
| U22 | `h_a_u22_batch_memory_charge_boundary` | PASS |
| U23 | `h_a_u17_u23_score_fault_and_double_fault_precedence` | PASS |
| U24 | `cargo build -p quervant-core --release` with witnesses `#[cfg(test)]`-only | PASS |

Additional pre-existing score validation relied on by U17:
`score::tests::bm25_golden_values` and `bm25_boundaries_and_invalid` (PASS in the
workspace suite).

## Differential oracle

For the eligible `Term` shape the ineligible `And([Term])` request was verified to
be genuinely ineligible (`h_a_u20_and_term_fallback_ineligible`) and produced
identical `total_hits`, key order and exact `f64::to_bits()` scores across
top_k = 1/10/100, top_k = matched, top_k = matched − 1 and cursor follow-ups.
