# PR 14 — Final design test traceability

| ID | Test symbol | Status |
|---|---|---|
| I1 mixed Boolean membership | `pr14_unified_mixed` m01–m06, m10, m11 | PASS |
| I2 effective-live only / delete | `m07_not_cannot_resurrect_tombstones` | PASS |
| I3 BM25 unchanged / positive only | `m13_pure_lexical_parity` (bit-exact), `m04_negative_only_lexical`, `m08_duplicate_leaves_do_not_double_score` | PASS |
| I4 exact total before top-K | `m12_zero_hits`; existing `pr14_*` totals | PASS |
| I5 total sort / gap-free cursor | `m14_mixed_explicit_sort`; cursor NOT IMPLEMENTED | PARTIAL |
| I6 cursor binding/expiry | NOT IMPLEMENTED (no PIT resolver) | OPEN |
| I7 five field states | `pr14_batch::b11_lossless_field_states`, `pr14_projection::p03` | PASS |
| I8 exact physical hit identity | `project_selected_hits`; mixed path only | PARTIAL |
| I9 work charged at scan sites | NOT IMPLEMENTED | OPEN |
| I10 shared budgets never reset | `pr14_batch::b06_shared_budget_not_reset` (response/hit meter) | PARTIAL |
| I11 policy/capability admission | `pr14_batch::b13_capability_rejection_is_isolated`, `b10_invalid_aggregate_kind` | PASS (admission); work meter OPEN |
| I12 aggregate sees every match once | NOT IMPLEMENTED | OPEN |
| I13 no query-time remote GET | NOT EXECUTED | OPEN |
| I14 no persisted format change | golden/PR13 regression suites remain green | PASS |

## New/updated suites
- `tests/pr14_unified_mixed.rs`: 14.
- `tests/pr14_batch.rs`: 12 (adds b13; `execute_batch` policy/capability args).
- `tests/pr14_projection.rs`: 10 (`p08` now asserts mixed execution).
