# PR 4 review amendment 05 — test matrix execution

**Branch:** `dev/analyzer-contract`. Reproductions first (baseline `29636c8`): the A5 file was
**31 passed / 25 failed**; after the fix **56 passed / 0 failed**. Negative assertions check
`AnalysisError::UnsupportedPattern`.

Executed commands (final):

```text
cargo +1.85.0 check --workspace --all-targets                         # PASS
cargo +1.85.0 test --workspace --all-targets                          # 529 passed; 0 failed; 1 ignored
cargo test -p trawler-core --test analysis_review_amendment_05        # 56 passed
cargo test -p trawler-core --test analysis_review_amendment_04        # 45 passed
cargo test -p trawler-core --test analysis_review_amendment_03        # 27 passed
cargo test -p trawler-core --test analysis_review_amendment_02        # 30 passed
cargo fmt --all -- --check                                            # PASS
cargo clippy --workspace --all-targets -- -D warnings                 # PASS
cargo test --workspace --all-targets                                  # 529 passed; 0 failed; 1 ignored
cargo llvm-cov --workspace --all-targets --fail-under-lines 85        # 94.24% lines
cargo doc --workspace --no-deps                                       # PASS
```

## A5-T matrix

| ID | Test function | Baseline | Final |
|---|---|---|---|
| A5-T01 `e[^x]` NFC | `a5_t01_outer_negated_class_nfc` | RED (bypass) | PASS |
| A5-T02 `e[^x]` NFKC | `a5_t02_outer_negated_class_nfkc` | RED | PASS |
| A5-T03 `e(?:[^x])` | `a5_t03_noncapturing_wrapped_negated_class` | RED | PASS |
| A5-T04 `e([^x])` | `a5_t04_capturing_wrapped_negated_class` | RED | PASS |
| A5-T05 `e(?:x?[^x])` | `a5_t05_nullable_prefix_before_negated_class` | RED | PASS |
| A5-T06 `e(?:x*[^x])` | `a5_t06_zero_or_more_prefix_before_negated_class` | RED | PASS |
| A5-T07 `e(?:x{0,2}[^x])` | `a5_t07_bounded_prefix_before_negated_class` | RED | PASS |
| A5-T08 `e(?:x\|[^x])` | `a5_t08_negated_class_alternative` | RED | PASS |
| A5-T09 `e(?:[^x]\|x)` | `a5_t09_negated_class_first_alternative` | RED | PASS |
| A5-T10 `e(?:[^x])+` | `a5_t10_quantified_wrapped_negated_class` | RED | PASS |
| A5-T11 `e[[:^digit:]]` | `a5_t11_negated_posix_class` | RED | PASS |
| A5-T12 `e(?:[[:^alpha:]])` | `a5_t12_wrapped_negated_posix_class` | RED | PASS |
| A5-T13 `e[^\u{0301}]` | `a5_t13_negated_class_excluding_mark_still_rejected` | already safe | PASS |
| A5-T14 `e[^0-9]` | `a5_t14_negated_digit_range` | RED | PASS |
| A5-T15 `e[^a-z]` | `a5_t15_negated_ascii_range` | RED | PASS |
| A5-T16 `e(?:x?[^0-9])` | `a5_t16_nullable_prefix_negated_digit_range` | RED | PASS |
| A5-T17 `e[^x]{1,3}` | `a5_t17_bounded_repetition_negated_class` | RED | PASS |
| A5-T18 `e[^x]?` | `a5_t18_optional_negated_class` | RED | PASS |
| A5-T19 standalone `[^x]` | `a5_t19_standalone_negated_class` | PASS | PASS |
| A5-T20 standalone `(?:[^x])` | `a5_t20_standalone_wrapped_negated_class` | PASS | PASS |
| A5-T21 `[^x]e` | `a5_t21_negated_class_before_literal` | PASS | PASS |
| A5-T22 `e[0-9]` | `a5_t22_digit_class_after_literal` | PASS | PASS |
| A5-T23 `e[a-z]` | `a5_t23_ascii_range_after_literal` | PASS | PASS |
| A5-T24 `e[[:digit:]]` | `a5_t24_positive_posix_digit_class` | PASS | PASS |
| A5-T25 `e[[:alpha:]]` | `a5_t25_positive_posix_alpha_class` | PASS | PASS |
| A5-T26 `e(?:xy)` | `a5_t26_plain_group_after_literal` | PASS | PASS |
| A5-T27 `e(?:x?y)` | `a5_t27_nullable_group_required_literal` | PASS | PASS |
| A5-T28 `e(?:é)` | `a5_t28_group_with_composed_literal` | PASS | PASS |
| A5-T29 `e[^x]` NFD | `a5_t29_negated_class_nfd_preserved` | PASS | PASS |
| A5-T30 `e[^x]` NFKD | `a5_t30_negated_class_nfkd_preserved` | PASS | PASS |
| A5-T31 `e[^x]` None | `a5_t31_negated_class_no_normalization_preserved` | PASS | PASS |
| A5-T32 `e[\^x]` | `a5_t32_escaped_caret_is_literal` | PASS | PASS |
| A5-T33 `e[^^]` | `a5_t33_negated_caret_class_rejected` | RED | PASS |
| A5-T34 `e[^]` | `a5_t34_empty_negated_class_grammar` | parser error | PASS |
| A5-T35 `e[[:^digit:]a]` | `a5_t35_negated_posix_in_union` | RED | PASS |
| A5-T36 `e(?:x?[^x]\|y)` | `a5_t36_nullable_alternation_with_negated_class` | RED | PASS |
| A5-T37 `e(?:x?[^x]){0,2}` | `a5_t37_quantified_nullable_negated_group` | RED | PASS |
| A5-T38 deterministic rejection | `a5_t38_negated_class_repeated_preparation_deterministic` | RED | PASS |
| A5-T39 deterministic acceptance | `a5_t39_positive_class_repeated_preparation_deterministic` | PASS | PASS |
| A5-T40 input ceiling | `a5_t40_input_ceiling` | PASS | PASS |
| A5-T41 cancellation | `a5_t41_cancellation` | PASS | PASS |
| A5-T42 work budget | `a5_t42_work_budget` | PASS | PASS |
| A5-T43 max range bound (4096) | `a5_t43_max_range_bound_is_bounded_and_safe` | PASS | PASS |
| A5-T44 beyond range bound | `a5_t44_range_beyond_bound_is_conservatively_rejected` | PASS | PASS |
| A5-T45 deep nesting within limit | `a5_t45_deep_nesting_within_limit` | PASS | PASS |
| A5-T46 beyond nesting limit | `a5_t46_beyond_nesting_limit_is_typed` | PASS | PASS |
| A5-T47 A3 regression | `a5_t47_amendment03_group_boundary` | PASS | PASS |
| A5-T48 A4 regression | `a5_t48_amendment04_nullable_boundary` | PASS | PASS |
| A5-T49 self-contained composition | `a5_t49_self_contained_group_composes` | PASS | PASS |
| A5-T50 A4 combining class | `a5_t50_amendment04_combining_class` | PASS | PASS |

## A5-I vertical slices

| ID | Test function / suite | Result |
|---|---|---|
| A5-I01 NFC index + boundary rejection + fingerprint | `a5_i01_nfc_index_and_boundary_rejection` | PASS |
| A5-I02 NFKC composition + rejection | `a5_i02_nfkc_composition_and_rejection` | PASS |
| A5-I03 NFD preserved | `a5_i03_nfd_preserved` | PASS |
| A5-I04 positive/standalone negated + metadata | `a5_i04_positive_and_standalone_negated_classes` | PASS |
| A5-I05 nested nullable negated POSIX | `a5_i05_nested_nullable_negated_posix_rejected` | PASS |
| A5-I06 cancellation + budget, no partial | `a5_i06_cancellation_and_budget_no_partial_success` | PASS |
| A5-I07 A2/A3/A4 regression rerun | `analysis_review_amendment_02/03/04` (30/27/45) | PASS |

## Notes

- All A5 patterns are accepted by the pinned parser except `e[^]`, which is a typed parser error
  and asserted as such (no negation-bypass claim).
- No previously accepted safe pattern outside the explicitly approved conservative negation
  policy was rejected; standalone/leading negated classes and `NFD`/`NFKD`/no-normalization
  boundaries remain accepted.
- No existing test was edited; no test is assertion-free or ignored.
