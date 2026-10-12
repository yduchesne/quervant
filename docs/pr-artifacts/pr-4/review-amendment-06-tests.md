# PR 4 review amendment 06 — test matrix execution

**Branch:** `dev/analyzer-contract`. Reproductions first (baseline `c8f3e8f`): the A6 file was
**28 passed / 27 failed**; after the fix **55 passed / 0 failed**. Negative assertions check
`AnalysisError::UnsupportedPattern`.

Executed commands (final):

```text
cargo +1.85.0 check --workspace --all-targets                         # PASS
cargo +1.85.0 test --workspace --all-targets                          # 584 passed; 0 failed; 1 ignored
cargo test -p trawler-core --test analysis_review_amendment_06        # 55 passed
cargo test -p trawler-core --test analysis_review_amendment_05        # 56 passed
cargo test -p trawler-core --test analysis_review_amendment_04        # 45 passed
cargo test -p trawler-core --test analysis_review_amendment_03        # 27 passed
cargo test -p trawler-core --test analysis_review_amendment_02        # 30 passed
cargo fmt --all -- --check                                            # PASS
cargo clippy --workspace --all-targets -- -D warnings                 # PASS
cargo test --workspace --all-targets                                  # 584 passed; 0 failed; 1 ignored
cargo llvm-cov --workspace --all-targets --fail-under-lines 85        # 94.27% lines
cargo doc --workspace --no-deps                                       # PASS
```

## A6-T matrix

| ID | Test function | Baseline | Final |
|---|---|---|---|
| A6-T01 `[^a]` CaseFold only | `a6_t01_negated_class_casefold_only` | RED (bypass) | PASS |
| A6-T02 NFC+CaseFold | `a6_t02_negated_class_nfc_then_casefold` | RED | PASS |
| A6-T03 CaseFold+NFC | `a6_t03_negated_class_casefold_then_nfc` | RED | PASS |
| A6-T04 `[^A]` | `a6_t04_negated_uppercase_literal` | already safe (member unstable) | PASS |
| A6-T05 `[^ß]` | `a6_t05_negated_sharp_s` | already safe | PASS |
| A6-T06 `[^Σ]` | `a6_t06_negated_greek_sigma` | already safe | PASS |
| A6-T07 capture group | `a6_t07_negated_class_in_capture_group` | RED | PASS |
| A6-T08 non-capturing group | `a6_t08_negated_class_in_noncapture_group` | RED | PASS |
| A6-T09 alternation | `a6_t09_negated_class_alternation` | RED | PASS |
| A6-T10 nullable prefix | `a6_t10_nullable_prefix_then_negated_class` | RED | PASS |
| A6-T11 `?` | `a6_t11_optional_negated_class` | RED | PASS |
| A6-T12 `*` | `a6_t12_star_negated_class` | RED | PASS |
| A6-T13 `{1,3}` | `a6_t13_bounded_negated_class` | RED | PASS |
| A6-T14 `[[:^lower:]]` | `a6_t14_negated_posix_lower` | RED | PASS |
| A6-T15 `[[:^digit:]]` | `a6_t15_negated_posix_digit` | RED | PASS |
| A6-T16 `[[:^alpha:]]` | `a6_t16_negated_posix_alpha` | RED | PASS |
| A6-T17 negated POSIX union | `a6_t17_negated_posix_union` | RED | PASS |
| A6-T18 nested `[[^a]x]` | `a6_t18_nested_negated_bracket` | RED | PASS |
| A6-T19 doubly nested | `a6_t19_doubly_nested_negated_bracket` | RED | PASS |
| A6-T20 `[0-9]` CaseFold | `a6_t20_digit_range_casefold` | PASS | PASS |
| A6-T21 `[a-z]` CaseFold | `a6_t21_ascii_range_casefold` | PASS | PASS |
| A6-T22 `[[:digit:]]` | `a6_t22_positive_posix_digit_casefold` | PASS | PASS |
| A6-T23 `[[:lower:]]` | `a6_t23_positive_posix_lower_casefold` | PASS | PASS |
| A6-T24 `e[0-9]` NFC+CaseFold | `a6_t24_digit_class_after_literal_nfc_casefold` | PASS | PASS |
| A6-T25 `(?:abc)` | `a6_t25_plain_group_casefold` | PASS | PASS |
| A6-T26 `Straße` | `a6_t26_case_expansion_accepted` | PASS | PASS |
| A6-T27 `[^a]` NFC no CaseFold | `a6_t27_negated_class_nfc_without_casefold` | PASS | PASS |
| A6-T28 `[^a]` no transforms | `a6_t28_negated_class_no_transform` | PASS | PASS |
| A6-T29 `[^a]` NFD no CaseFold | `a6_t29_negated_class_nfd_without_casefold` | PASS | PASS |
| A6-T30 `[^a]` NFKD no CaseFold | `a6_t30_negated_class_nfkd_without_casefold` | PASS | PASS |
| A6-T31 NFD+CaseFold | `a6_t31_negated_class_nfd_casefold` | RED | PASS |
| A6-T32 NFKD+CaseFold | `a6_t32_negated_class_nfkd_casefold` | RED | PASS |
| A6-T33 `e[^a]` NFC no CaseFold | `a6_t33_negated_class_boundary_nfc_without_casefold` | PASS | PASS |
| A6-T34 `e[[:^digit:]]` NFC no CaseFold | `a6_t34_negated_posix_boundary_nfc_without_casefold` | PASS | PASS |
| A6-T35 `e[0-9]` | `a6_t35_positive_class_boundary_nfc_without_casefold` | PASS | PASS |
| A6-T36 `e[\^x]` | `a6_t36_escaped_caret_literal` | PASS | PASS |
| A6-T37 `[^]` | `a6_t37_malformed_empty_negated_class` | parser error | PASS |
| A6-T38 cancellation | `a6_t38_cancellation` | PASS | PASS |
| A6-T39 work budget | `a6_t39_work_budget` | PASS | PASS |
| A6-T40 input ceiling | `a6_t40_input_ceiling` | RED (test sizing) → fixed | PASS |
| A6-T41 4096-scalar range | `a6_t41_exact_max_safe_range_under_casefold` | PASS | PASS |
| A6-T42 4097-scalar range | `a6_t42_range_beyond_bound_rejected` | PASS | PASS |

Additional edge tests: `a6_t43` (empty alternative + nullable), `a6_t44` (deterministic
rejection/acceptance), `a6_t45` (nesting within/above bound), `a6_t46` (negated bracket inside a
set intersection).

## A6-I vertical slices

| ID | Test function | Result |
|---|---|---|
| A6-I01 CaseFold index `A` + `[^a]` reject | `a6_i01_casefold_index_and_negated_class_rejection` | PASS |
| A6-I02 NFC+CaseFold index + reject + fingerprint | `a6_i02_nfc_casefold_index_and_rejection_with_fingerprint` | PASS |
| A6-I03 `Straße` index + prepared literal | `a6_i03_casefold_expansion_index_and_prepared_literal` | PASS |
| A6-I04 NFC no CaseFold standalone preserved | `a6_i04_nfc_without_casefold_standalone_negated_class_preserved` | PASS |
| A6-I05 NFC boundary negated reject | `a6_i05_nfc_boundary_negated_class_rejected` | PASS |
| A6-I06 nested POSIX negation under CaseFold | `a6_i06_casefold_nested_posix_negation_rejected` | PASS |
| A6-I07 cancellation/budget, no partial | `a6_i07_cancellation_and_budget_no_partial_result` | PASS |
| A6-I08 distinct analyzer fingerprints | `a6_i08_distinct_analyzers_have_distinct_fingerprints` | PASS |

Semantic witness (independent of preparation): `a6_i_semantic_witness_casefold_membership_changes`
asserts `collect_tokens(CaseFold, "A") == "a"`, i.e. `[^a]`'s excluded `a` is exactly the folded
form of a source `A` it would otherwise match.

## Notes

- `[^A]`/`[^ß]`/`[^Σ]` were already rejected at baseline because the excluded member is
  case-unstable; they are retained as regressions, not red-bypass evidence.
- All patterns are accepted by the pinned parser except `[^]`, asserted as a typed error.
- No existing test was edited; no assertion-free or ignored test added. The single ignored test
  is pre-existing and unrelated.
