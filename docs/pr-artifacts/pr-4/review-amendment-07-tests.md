# PR 4 review amendment 07 — test matrix execution

**Branch:** `dev/analyzer-contract`. Baseline (production file reverted via `git stash`):
**25 passed / 30 failed**; final: **55 passed / 0 failed**. Negative assertions check the
specific typed variant.

Executed commands (final):

```text
cargo +1.85.0 check --workspace --all-targets                         # PASS
cargo +1.85.0 test --workspace --all-targets                          # 639 passed; 0 failed; 1 ignored
cargo test -p trawler-core --test analysis_review_amendment_07        # 55 passed
cargo test -p trawler-core --test analysis_review_amendment_06        # 55 passed
cargo test -p trawler-core --test analysis_review_amendment_05        # 56 passed
cargo test -p trawler-core --test analysis_review_amendment_04        # 45 passed
cargo test -p trawler-core --test analysis_review_amendment_03        # 27 passed
cargo test -p trawler-core --test analysis_review_amendment_02        # 30 passed
cargo fmt --all -- --check                                            # PASS
cargo clippy --workspace --all-targets -- -D warnings                 # PASS
cargo test --workspace --all-targets                                  # 639 passed; 0 failed; 1 ignored
cargo llvm-cov --workspace --all-targets --fail-under-lines 85        # 94.52% lines
cargo doc --workspace --no-deps                                       # PASS
```

## A7-T matrix

| ID | Test function | Baseline | Final |
|---|---|---|---|
| A7-T01 prefix one over input ceiling | `a7_t01_prefix_one_over_input_ceiling` | RED | PASS |
| A7-T02 prefix exactly at ceiling | `a7_t02_prefix_exactly_at_input_ceiling` | PASS | PASS |
| A7-T03 glob one over input ceiling | `a7_t03_glob_one_over_input_ceiling` | RED | PASS |
| A7-T04 glob exactly at ceiling | `a7_t04_glob_exactly_at_input_ceiling` | PASS | PASS |
| A7-T05 multibyte counted in bytes | `a7_t05_multibyte_counted_in_bytes` | RED | PASS |
| A7-T06 no-transform prefix work | `a7_t06_no_transform_prefix_work_budget` | RED | PASS |
| A7-T07 wildcard-only glob work | `a7_t07_wildcard_only_glob_work_budget` | RED | PASS |
| A7-T08 escape-heavy glob work | `a7_t08_escape_heavy_glob_work_budget` | RED | PASS |
| A7-T09 exact work boundary | `a7_t09_exact_work_budget_boundary` | RED | PASS |
| A7-T10 pre-cancelled prefix | `a7_t10_pre_cancelled_prefix` | RED | PASS |
| A7-T11 pre-cancelled glob | `a7_t11_pre_cancelled_glob` | RED | PASS |
| A7-T12 prefix term-byte expansion | `a7_t12_normalized_prefix_exceeds_term_bytes` | RED | PASS |
| A7-T13 prefix exactly term bytes | `a7_t13_normalized_prefix_exactly_at_term_bytes` | PASS | PASS |
| A7-T14 glob segment term bytes | `a7_t14_glob_segment_exceeds_term_bytes` | RED | PASS |
| A7-T15 multiple segments within term bound | `a7_t15_multiple_segments_each_within_term_bound` | PASS | PASS |
| A7-T16 total glob output bound | `a7_t16_total_glob_output_exceeds_bound` | RED | PASS |
| A7-T17 wildcard-only long bounded | `a7_t17_wildcard_only_long_pattern_is_bounded` | RED | PASS |
| A7-T18 empty/dangling forms | `a7_t18_empty_and_dangling_forms` | PASS | PASS |
| A7-T19 escaped operators literal | `a7_t19_escaped_operators_stay_literal` | PASS | PASS |
| A7-T20 consecutive operators collapse | `a7_t20_consecutive_operators_collapse` | PASS | PASS |
| A7-T21 `e*\u0301` rejected | `a7_t21_glob_composition_across_star_rejected` | RED | PASS |
| A7-T22 `e**\u0301` rejected | `a7_t22_repeated_zero_width_operators_rejected` | RED | PASS |
| A7-T23 `*\u0301` rejected | `a7_t23_leading_star_then_mark_rejected` | RED | PASS |
| A7-T24 literal-only composes | `a7_t24_literal_only_run_composes` | PASS | PASS |
| A7-T25 ASCII `*` accepted | `a7_t25_simple_ascii_star_accepted` | PASS | PASS |
| A7-T26 ASCII `?` accepted | `a7_t26_simple_ascii_question_accepted` | PASS | PASS |
| A7-T27 `e?\u0301` rejected | `a7_t27_question_then_mark_rejected` | RED | PASS |
| A7-T28 `?` + case-fold expansion | `a7_t28_question_with_casefold_expansion_documented_semantics` | PASS | PASS |
| A7-T29 AsciiFold removal rejected | `a7_t29_asciifold_removed_literal_rejected` | RED | PASS |
| A7-T30 leading/trailing/mixed operators | `a7_t30_leading_trailing_and_mixed_operators` | PASS | PASS |
| A7-T31 escaped mark after wildcard | `a7_t31_escaped_mark_after_wildcard_rejected` | RED | PASS |
| A7-T32 escaped wildcard next to mark | `a7_t32_escaped_wildcard_next_to_mark_is_literal` | PASS | PASS |
| A7-T33 NFKC boundary fails closed | `a7_t33_nfkc_boundary_fails_closed` | RED | PASS |
| A7-T34 NFD/NFKD/noop preserved | `a7_t34_decomposition_and_noop_pipelines_preserved` | PASS | PASS |
| A7-T35 filter order evaluated | `a7_t35_filter_order_evaluated` | PASS | PASS |
| A7-T36 casefold literal no stemming | `a7_t36_literal_only_casefold_without_stemming` | PASS | PASS |
| A7-T37 metadata fingerprint | `a7_t37_metadata_fingerprint_matches_analyzer` | PASS | PASS |
| A7-T38 deterministic | `a7_t38_repeated_preparation_is_deterministic` | PASS | PASS |
| A7-T39 large input small budget | `a7_t39_large_input_small_budget_fails_cleanly` | RED | PASS |
| A7-T40 tiny term limit no panic | `a7_t40_tiny_term_limit_does_not_panic` | RED | PASS |
| A7-T41 term stems, prefix/glob do not | `a7_t41_term_stems_but_prefix_and_glob_do_not` | PASS | PASS |
| A7-T42 prepare_regex unchanged | `a7_t42_prepare_regex_unchanged` | PASS | PASS |
| A7-T43 limits ceilings immutable | `a7_t43_limits_ceilings_cannot_be_raised` | PASS | PASS |
| A7-T44 empty literal segments | `a7_t44_empty_literal_segments_do_not_bypass` | PASS | PASS |
| A7-T45 multibyte accounting | `a7_t45_multibyte_escaped_scalar_accounting` | RED | PASS |
| A7-T46 zero-filter work accounting | `a7_t46_zero_filter_work_accounting_is_filter_independent` | RED | PASS |
| A7-T47 input preflight before work | `a7_t47_input_preflight_before_work` | RED | PASS |
| A7-T48 existing glob contract | `a7_t48_existing_glob_contract_remains_valid` | PASS | PASS |

## A7-I integration slices

| ID | Test function / suite | Result |
|---|---|---|
| A7-I01 index composition + glob rejection | `a7_i01_index_composition_and_glob_rejection` | PASS |
| A7-I02 casefold index + literal glob | `a7_i02_casefold_index_and_literal_glob` | PASS |
| A7-I03 no-filter analyzer budgets | `a7_i03_no_filter_analyzer_budgets` | PASS |
| A7-I04 safe operators shape/serialization | `a7_i04_safe_operators_shape_and_serialization` | PASS |
| A7-I05 filter orders + fingerprint | `a7_i05_filter_orders_and_fingerprint` | PASS |
| A7-I06 exact/one-over limits | `a7_i06_exact_and_one_over_limits` | PASS |
| A7-I07 failure leaves no object, then recovers | `a7_i07_failures_leave_no_prepared_object_then_recover` | PASS |
| A7-I08 A2–A6 regression rerun | `analysis_review_amendment_02..06` (30/27/45/56/55) | PASS |

## Notes

- Genuine red-before evidence: reverting `term.rs` to `HEAD` (`git stash push -- term.rs`) and
  running the A7 target produced 25 passed / 30 failed; the 25 baseline passes are the
  grammar/regression cases retained unchanged.
- Decision-dependent cases per the approved conservative policy: T28 (`?` indexed-scalar
  semantics), T29 (reject transform-removed literal), T33–T35 (composing vs decomposition
  pipelines).
- The single ignored test is pre-existing and unrelated; no test is assertion-free.
