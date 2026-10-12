# PR 4 review fixup — deterministic test matrix execution

**Branch:** `dev/analyzer-contract`. Every negative assertion checks the **specific** error
variant. Executed commands:

```text
cargo +1.85.0 test -p trawler-core --lib analysis          # 62 passed; 0 failed
cargo +1.85.0 test -p trawler-core --test analysis_review_fixup   # 19 passed; 0 failed
cargo test --workspace --all-targets                       # 370 passed; 0 failed; 1 ignored
cargo +1.85.0 test --workspace --all-targets               # 370 passed; 0 failed; 1 ignored
```

## F4 matrix

| ID | Test function | File | Result |
|---|---|---|---|
| F4-01 `a{3,2}` rejected | `f4_01_to_f4_06_regex_grammar_is_validated_fail_closed` | `tests/analysis_review_fixup.rs` | PASS |
| F4-02 `*abc` rejected | same | same | PASS |
| F4-03 `a\|` documented supported | `f4_03_empty_alternation_has_documented_supported_semantics` | same | PASS |
| F4-04 `[z-a]` rejected | `f4_01_to_f4_06_...` | same | PASS |
| F4-05 `(ab`, `a\`, `[a` rejected | same | same | PASS |
| F4-06 `(a)\1`, `a(?=b)` rejected | same | same | PASS |
| F4-07 approved subset accepted | `f4_07_approved_subset_is_accepted` | same | PASS |
| F4-08 folded literal equals indexed term | `f4_08_folded_literal_matches_indexed_term` | same | PASS |
| F4-09 expansion policy | `f4_09_expansion_policy_is_safe`; `a2_t08_expansion_policy_is_safe` | same; `tests/analysis_review_amendment_02.rs` | PASS (amendment 02: unquantified run expansion re-escaped; quantified expansion rejected) |
| F4-10 syntax / case classes preserved or rejected | `f4_10_syntax_and_case_sensitive_classes_are_preserved_or_rejected` | same | PASS |
| F4-11 same id/version, changed filter order | `f4_11_f4_12_f4_13_fingerprint_aware_compatibility`; `registry::tests::fingerprint_mismatch_is_typed_even_with_equal_id_and_version` | same; `src/analysis/registry.rs` | PASS |
| F4-12 exact id/version/fingerprint | same | same | PASS |
| F4-13 wrong version / unknown name | same | same | PASS |
| F4-14 malformed PSL bytes | `domain_data::tests::corrupt_psl_bytes_are_rejected_typed` (crate-private helper) | `src/analysis/domain_data.rs` | PASS |
| F4-15 pinned PSL private/ICANN policy | `f4_15_f4_22_domain_policy_identity_and_bounds`; `a4_15_...` | `tests/analysis_review_fixup.rs`; `tests/domain_analysis.rs` | PASS |
| F4-16 two values each at cap | `f4_16_f4_17_token_cap_is_per_value` | `tests/analysis_review_fixup.rs` | PASS |
| F4-17 one value cap+1 | same | same | PASS |
| F4-18 empty values / stopwords / gap | `f4_18_empty_values_stopwords_and_gap_are_preserved` | same | PASS |
| F4-19 no eager full-value scan | `f4_19_first_token_does_not_eagerly_scan_the_whole_value` | same | PASS |
| F4-20 cancellation start/mid/after | `f4_20_cancellation_checkpoints_are_typed` | same | PASS |
| F4-21 work exact capacity / one-over | `f4_21_exact_work_capacity_succeeds_and_one_over_fails` | same | PASS |
| F4-22 domain cancellation / long input | `f4_15_f4_22_...` | same | PASS |
| F4-23 NFC/case-fold offset preservation | `f4_23_normalization_offsets_reference_original_input` | same | PASS |
| F4-24 existing A4/I4 regression | `f4_24_stopwords_and_prefix_contract_remain_stable` + full `tests/analysis_contract.rs` / `tests/domain_analysis.rs` suites | same | PASS |

Additional unit coverage: `tokenizer::tests::cursor_is_pull_based_and_terminates`,
`analyzer::tests::position_overflow_is_checked`, `analyzer::tests::collect_tokens_matches_cursor`,
`registry::tests::fingerprint_mismatch_is_typed_even_with_equal_id_and_version`,
`domain_data::tests::corrupt_psl_bytes_are_rejected_typed`.

## IF4 production-boundary integration

| ID | Test function | Result |
|---|---|---|
| IF4-01 Schema → registry → bindings → term/pattern prep | `if4_01_real_schema_to_term_and_pattern_preparation` | PASS |
| IF4-02 cursor/collect agreement + cancellation | `if4_02_cursor_and_collect_agree_with_deterministic_cancellation` | PASS |
| IF4-03 real `analyze_domain` + pinned dataset identity | `if4_03_real_domain_analysis_with_pinned_dataset` | PASS |
| IF4-04 fingerprint-aware registry resolution | `if4_04_registry_fingerprint_seam_fails_closed` | PASS |

No filesystem, RustFS, writer/reader or query-executor harness applies to PR 4; none was invented.
