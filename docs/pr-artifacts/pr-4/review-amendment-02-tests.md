# PR 4 review amendment 02 — test matrix execution

**Branch:** `dev/analyzer-contract`. Negative assertions check the specific `AnalysisError`
variant. Executed commands:

```text
cargo +1.85.0 test -p trawler-core --test analysis_review_amendment_02   # 30 passed; 0 failed
cargo +1.85.0 test --workspace --all-targets                            # see report
cargo test --workspace --all-targets                                    # see report
```

## A2-T matrix

| ID | Test function | File | Result |
|---|---|---|---|
| A2-T01 NFC run composition | `a2_t01_nfc_literal_run_composes_across_scalars` | `tests/analysis_review_amendment_02.rs` | PASS |
| A2-T02 composed NFC stable | `a2_t02_already_composed_nfc_is_stable` | same | PASS |
| A2-T03 NFD decomposition | `a2_t03_nfd_decomposes_composed_literal` | same | PASS |
| A2-T04 escaped metachar maintained | `a2_t04_escaped_metacharacter_is_preserved` | same | PASS |
| A2-T05 quantified combining mark | `a2_t05_quantified_combining_mark_is_rejected` | same | PASS |
| A2-T06 alternation boundary | `a2_t06_no_composition_across_alternation_branches` | same | PASS |
| A2-T07 group/anchor/repetition | `a2_t07_group_anchor_repetition_do_not_drift` | same | PASS |
| A2-T08 expansion policy | `a2_t08_expansion_policy_is_safe` | same | PASS |
| A2-T09 long run budget/cancel | `a2_t09_long_run_respects_work_budget_and_cancellation` | same | PASS |
| A2-T10 case range rejected | `a2_t10_case_sensitive_range_is_rejected_when_folding` | same | PASS |
| A2-T11 unsafe interior rejected | `a2_t11_stable_endpoints_unsafe_interior_is_rejected` | same | PASS |
| A2-T12 predefined case classes | `a2_t12_predefined_case_classes_are_rejected_when_folding` | same | PASS |
| A2-T13 safe predefined classes | `a2_t13_safe_predefined_classes_are_accepted_with_proof` | same | PASS |
| A2-T14 digit class under NFC | `a2_t14_digit_class_under_nfc_only_is_accepted` | same | PASS |
| A2-T15 class/quantifier/escape | `a2_t15_class_with_quantifier_and_escaped_bracket_preserved` | same | PASS |
| A2-T16 keyword checkpoint/cancel | `a2_t16_keyword_charges_incrementally` | same | PASS |
| A2-T17 keyword exact work budget | `a2_t17_keyword_exact_work_budget` | same | PASS |
| A2-T18 UAX #29 single word | `a2_t18_uax29_single_word_exact_segmentation` | same | PASS |
| A2-T19 long pre-word run | `a2_t19_long_punctuation_before_first_word_is_charged_and_bounded` | same | PASS |
| A2-T20 multibyte offsets | `a2_t20_multibyte_offsets_are_unchanged` | same | PASS |
| A2-T21 call-wide work / per-value cap | `a2_t21_call_wide_work_budget_and_per_value_token_ceiling` | same | PASS |
| A2-T22 terminal after work/token error | `a2_t22_terminal_error_is_latched` | same | PASS |
| A2-T23 terminal after cancellation | `a2_t23_cancellation_after_token_is_terminal` | same | PASS |
| A2-T24 terminal too-many-tokens | `a2_t24_too_many_tokens_is_terminal` | same | PASS |
| A2-T25 position overflow terminal | `analysis::analyzer::tests::position_overflow_is_checked` | `src/analysis/analyzer.rs` | PASS |
| A2-T26 EOF idempotent | `a2_t26_eof_is_idempotent` | same | PASS |
| A2-T27 collect never partial | `a2_t27_collect_tokens_never_returns_partial_success` | same | PASS |

## A2-I vertical slices

| ID | Test function | Result |
|---|---|---|
| A2-I01 NFC index/prepare agreement | `a2_i01_nfc_indexing_and_literal_preparation_agree` | PASS |
| A2-I02 folded unsafe class rejected | `a2_i02_folded_analyzer_rejects_unsafe_class` | PASS |
| A2-I03 schema → cursor → terminal cancellation | `a2_i03_schema_binding_cursor_and_mid_stream_cancellation` | PASS |
| A2-I04 fingerprint/domain/term seams preserved | `a2_i04_fingerprint_domain_and_term_seams_preserved` | PASS |

## Superseded/renamed pre-existing tests (authorized behavior change)

| Old | New | Reason |
|---|---|---|
| `f4_09_length_changing_literal_is_rejected` (`Straße+` rejected) | `f4_09_expansion_policy_is_safe` (`Straße`→`strasse`, `ß+` rejected) | Amendment 02/A2-T08: unquantified run expansion is safely representable; only quantified expansion changes scope. |
| `regex_literal_expansion_is_rejected` (unit) | `regex_unquantified_expansion_is_representable` + `regex_quantified_expansion_is_rejected` | Same. |

`f4_07_approved_subset_is_accepted` (`[0-9]` under `english`) is **unchanged and still passes**,
because the range check now proves the whole interior stable rather than applying a blanket class
rejection. No prior evidence was deleted; the renamed rows are recorded here.
