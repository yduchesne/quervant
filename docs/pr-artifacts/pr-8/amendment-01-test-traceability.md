# PR 8 Amendment 01 test traceability — A1-T01–T28

Public-path tests live in `crates/quervant-core/tests/pr08_amendment01.rs`.
Private intern/FST/budget tests live in the `#[cfg(test)]` modules of
`crates/quervant-core/src/search/{expand,term_fst}.rs`.

| ID | Invariant / scenario | Test(s) |
|---|---|---|
| A1-T01 | Every inspected entry charges request work before build | `preflight_charges_work_and_reserves_conservatively` (term_fst); `a1_t01_t02_work_limit_is_charged_and_prevents_partial_success` (integration) |
| A1-T02 | One-over work prevents build | `preflight_work_limit_prevents_build` (asserts `build_invocations()==0`); `a1_t01_t02_...` (public-path ResourceLimit) |
| A1-T03 | Cumulative work across segments/fields | `a1_t03_cumulative_work_across_fields`; `preflight_is_cumulative_across_fields` |
| A1-T04 | Cancellation during preflight | `preflight_cancellation_during_walk`, `preflight_empty_dictionary_checks_cancellation` |
| A1-T05 | Exact cumulative FST byte budget | `a1_t05_t06_fst_budget_exact_and_one_over`; `preflight_fst_budget_one_over_prevents_build` |
| A1-T06 | One-over FST budget rejected before build | `preflight_fst_budget_one_over_prevents_build` (`build_invocations()==0`); `a1_t05_t06_...` |
| A1-T07 | Two small FSTs exceed the combined budget | `a1_t07_two_fsts_share_the_cumulative_budget`; `preflight_is_cumulative_across_fields` |
| A1-T08 | Encoded size greater than reservation fails closed | `reservation_rejects_encoded_oversize` (test-only injected `logical_bytes`) |
| A1-T09 | One canonical text per `(field, term)` across segments/leaves | `intern_deduplicates_and_charges_once`; `duplicate_term_amplification_is_bounded_by_occurrences_not_strings` |
| A1-T10 | Unicode/long-term UTF-8 byte charging | `intern_unicode_and_long_terms_charge_utf8_bytes` |
| A1-T11 | `max_expanded_terms` unchanged semantics | `expanded_unique_limit_is_enforced`; `a1_t14_occurrence_amplification_fails_by_bytes` |
| A1-T12 | Exact expansion byte limit | `a1_t12_t13_expansion_bytes_exact_and_one_over`; `occurrence_capacity_is_charged_in_chunks` |
| A1-T13 | One-over expansion byte limit fails closed | `a1_t12_t13_...`; `budget_reserve_is_exact_and_typed`; `occurrence_bytes_one_over_fails_closed` |
| A1-T14 | Many leaves/segments, same term, fail by occurrence bytes | `a1_t14_occurrence_amplification_fails_by_bytes`; `occurrence_amplification_fails_even_when_unique_terms_fit` |
| A1-T15 | Vector-capacity overshoot charged | `occurrence_capacity_is_charged_in_chunks` |
| A1-T16 | Positive scoring-union copy charged once | `positive_copy_is_not_charged_twice`; `positive_unique_limit_is_enforced` |
| A1-T17 | Failure mid-stream returns ResourceLimit, no partial state | `a1_t17_t18_no_partial_results_and_recovery`; `budget_reserve_is_exact_and_typed` |
| A1-T18 | Subsequent query succeeds after failure | `a1_t17_t18_no_partial_results_and_recovery` |
| A1-T19 | Cancellation mid-stream then recovery | `a1_t19_cancellation_mid_expansion_then_recovery` |
| A1-T20 | FsDirectory/PIT untouched by failing expansion | `a1_t20_fs_failing_expansion_is_read_only` |
| A1-T21 | Prefix/Glob/Regex/Fuzzy membership via independent oracle | `a1_t21_operator_membership_matches_oracle` (+ full oracle in `pr08_properties`) |
| A1-T22 | Overlapping leaves never double-score | `p8_t15_t16_overlap_dedup` (unchanged PR 8) |
| A1-T23 | Legacy/mixed norms BM25 unchanged | `p8_t14_mixed_legacy_new_bm25`, `p8_t36_frozen_legacy_all_operators` (unchanged) |
| A1-T24 | Top-K/Boolean/negative-only unchanged | `a1_t24_boolean_and_negative_only_unchanged` |
| A1-T25 | Ten-arg constructor preserved | `a1_t25_ten_arg_constructor_preserves_defaults`; `pr8_new_bounds_defaults_exact_and_one_over` |
| A1-T26 | Additive expansion limit: zero/ceiling/exact/one-over | `a1_t26_expansion_bytes_setter_exact_zero_one_over`; `pr8_new_bounds_defaults_exact_and_one_over` |
| A1-T27 | Golden segment/fixture SHA unchanged | `a1_t27_frozen_fixture_bytes_unchanged`; existing `segment_golden`/`segment_codec` suites |
| A1-T28 | Stable/MSRV/coverage gates | stable/MSRV `clippy`+`test`, `cargo llvm-cov`, `cargo doc`, `cargo bench --no-run`, `test-scripts.sh` |

## Notes

- "No build on failure" is proven by the test-only `build_invocations()`
  counter, never by wall-clock timing.
- A1-T05/T06/T12/T13 public-path thresholds are found by monotonic binary search
  over the public `SearchLimits` setters, so the exact and one-over values are
  derived from the implementation rather than asserted from a stale constant.
- The `max_expansion_bytes` budget is the only new public limit; no query AST,
  segment, manifest or HTTP/JSON surface changed.
