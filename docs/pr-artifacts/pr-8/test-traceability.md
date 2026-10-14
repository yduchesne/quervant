# PR 8 test traceability — T01–T44

Every acceptance invariant from the PR 8 plan §6 maps to at least one executed
test. Test files are `crates/quervant-core/tests/pr08_*.rs`; unit-level automaton
tests live in `crates/quervant-core/src/search/automaton.rs`.

| ID | Invariant | Test(s) | File |
|---|---|---|---|
| T01 | prefix `ru` matches `rust` not `crust` | `p8_t01_prefix_whole_term` | pr08_unit |
| T02 | empty/absent prefix | `p8_t02_prefix_empty_absent` | pr08_unit |
| T03 | glob `r*st`, `r?st`, escaped `r\*st` | `p8_t03_glob_whole_term_and_escape` | pr08_unit |
| T04 | regex `ru.*` whole-term, `u` ≠ `rust` | `p8_t04_regex_whole_term` | pr08_unit |
| T05 | invalid grammar rejected before reader | `p8_t05_pattern_rejected_before_reader` | pr08_unit |
| T06 | `?` is one Unicode scalar | `p8_t06_question_mark_scalar` | pr08_unit |
| T07 | NFC/case/ASCII fold | `p8_t07_unicode_folding` | pr08_unit |
| T08 | Unicode regex dot/classes | `p8_t08_regex_unicode_classes` | pr08_unit |
| T09 | fuzzy edits 0/1/2 parity | `p8_t09_fuzzy_edits_reference`, `p8_properties_seeded_operator_parity`, `fuzzy_levenshtein_matches_reference` | pr08_unit, pr08_properties, automaton |
| T10 | `ab` vs `ba` OSA 1 vs Levenshtein 2 | `p8_t10_osa_transposition`, `fuzzy_osa_matches_reference_and_differs_from_unrestricted` | pr08_unit, automaton |
| T11 | restricted vs unrestricted Damerau | `p8_t11_osa_vs_unrestricted`, `fuzzy_osa_is_exhaustively_correct_for_short_strings`, `fuzzy_osa_matches_reference_and_differs_from_unrestricted` | pr08_unit, automaton |
| T12 | edits 3 / multi-token / invalid field typed | `p8_t12_fuzzy_typed_errors`, `fuzzy_edits_above_two_are_rejected_by_contract`, `fuzzy_requires_a_single_token` | pr08_unit, plan |
| T13 | term in two segments global df | `p8_t13_global_df_segments` | pr08_properties |
| T14 | mixed legacy/new equals all-new BM25 | `p8_t14_mixed_legacy_new_bm25`, `mixed_legacy_and_norms_segments_aggregate` | pr08_integration, score |
| T15 | two matching expanded terms sum once each | `p8_t15_t16_overlap_dedup` | pr08_properties |
| T16 | overlapping Term/Prefix/Glob never double score | `p8_t15_t16_overlap_dedup` | pr08_properties |
| T17 | zero-expansion leaf / OR semantics | `p8_t17_zero_expansion_or_semantics` | pr08_properties |
| T18 | AND/OR/NOT/NOT NOT | `p8_t18_boolean_combinations` | pr08_properties |
| T19 | pure-negative zero score | `p8_t19_negative_only_zero` | pr08_properties |
| T20 | phrase AND prefix | `p8_t20_phrase_and_prefix` | pr08_properties |
| T21 | TopK=1 vs 10 exact total and ties | `p8_t21_topk_exact_total_tie_order`, `p8_t28_pr7_limits_retained` | pr08_properties, pr08_unit |
| T22 | expanded terms exact / one-over | `p8_t22_expanded_terms_exact_one_over`, `fst_expansion_limit_is_typed` | pr08_unit, term_fst |
| T23 | combined unique term limit | `p8_t23_combined_unique_terms` | pr08_unit |
| T24 | broad `*` / no-match work | `p8_t24_broad_glob_no_match_work`, `fst_no_match_does_bounded_work` | pr08_unit, term_fst |
| T25 | FST bytes | `p8_t25_fst_bytes` | pr08_unit |
| T26 | automaton states | `p8_t26_automaton_states`, `oversized_regex_is_rejected_before_large_allocation`, `fuzzy_scalar_and_state_limits_are_enforced` | pr08_unit, automaton |
| T27 | fuzzy scalar length | `p8_t27_fuzzy_scalar_length` | pr08_unit |
| T28 | PR7 candidate/postings/topK limits | `p8_t28_pr7_limits_retained` | pr08_unit |
| T29 | pre-cancel | `p8_t29_precancel` | pr08_faults |
| T30 | cancel during FST/automaton traversal | `p8_t30_cancel_during_traversal` | pr08_faults |
| T31 | cancel during postings | `p8_t31_cancel_during_postings` | pr08_faults |
| T32 | failure then successful query | `p8_t32_failure_then_recovery`, `p8_t32_corrupt_segment_fails_closed` | pr08_faults |
| T33 | MemoryDirectory commit/reopen | `p8_t33_memory_commit_reopen` | pr08_integration |
| T34 | FsDirectory commit/reopen, no writes | `p8_t34_fs_commit_reopen_no_writes` | pr08_integration |
| T35 | PIT vs fresh generation | `p8_t35_pit_vs_fresh` | pr08_integration |
| T36 | frozen pre-norms fixture all operators | `p8_t36_frozen_legacy_all_operators` | pr08_integration |
| T37 | single vs multi-segment sorted-remap | `p8_t37_single_vs_multisegment_remap` | pr08_integration |
| T38 | canonical IDNA/case | `p8_t38_domain_canonical` | pr08_domain |
| T39 | domain typo/transposition | `p8_t39_domain_typo_transposition` | pr08_domain |
| T40 | TLD raw distance | `p8_t40_domain_tld_raw_distance` | pr08_domain |
| T41 | no implicit skeleton/weighting, original keys | `p8_t41_domain_identity_preserved` | pr08_domain |
| T42 | golden bytes/features unchanged | `p8_t42_golden_bytes_features_unchanged`, `p8_t42_search_is_read_only`, all `segment_golden`/`segment_codec` suites | pr08_integration, pr08_unit, segment |
| T43 | all PR7 regressions | `pr07_unit`, `pr07_properties`, `pr07_integration`, `pr07_compatibility`, `pr07_faults`, `pr07_amendment0*`, `pr07_amendment05` | PR 7 suites |
| T44 | core independent of remote/distributed | `p8_t44_core_is_standalone` | pr08_integration |

## Oracle independence

`pr08_properties.rs` implements `ref_bm25`, `ref_levenshtein`, `ref_osa`,
`ref_glob` and a `regex::Regex` oracle. It computes `n`/`df`/`dl`/`avgdl` from
fixture analyzer tokens and never calls the production `automaton`, `expand`,
`compute_stats` or `bm25`. `automaton.rs` unit tests likewise use a full-matrix
Levenshtein/OSA DP and compare exhaustively over all strings of length ≤4 over
`{a,b,c}`.

## Notes

- T09/T10/T11 also have hand-calculated automaton assertions.
- T22/T23/T25/T26/T27 are boundedness tests that assert the exact limit passes and
  one-over fails, with typed `SearchError::ResourceLimit` and no partial result.
- The frozen `pr07_pre_norms_v1` fixture is copied to a temporary root and never
  regenerated; its hashes are asserted by the PR 7 compatibility suite.
