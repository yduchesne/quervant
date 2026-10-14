# PR 7 correctness matrix

Maps every observable invariant Q7-01..Q7-10 to the tests that exercise it.
Test files live under `crates/quervant-core/tests/` and unit tests under
`crates/quervant-core/src/search/`.

| ID | Invariant | Tests |
|---|---|---|
| Q7-01 | Results belong to the captured immutable snapshot | `pr07_integration::i07_refresh_snapshot_isolated`, `i08_pit_pinned_across_commit`, `i01_writer_refresh_term` |
| Q7-02 | Term retrieval uses indexed postings + correct field/analyzer binding | `pr07_unit::u01_term_field_isolation_and_missing`, `u02_keyword_normalization_and_mismatch`, `pr07_integration::i01_writer_refresh_term`, `i02_commit_reopen_search`, `pr07_faults::f04_analyzer_mismatch` |
| Q7-03 | AND/OR/NOT set algebra, nesting, live-universe complement | `pr07_unit::u03_and_intersection`, `u04_or_union`, `u05_not_complement`, `u06_nested_boolean`, `pr07_properties::p01_random_boolean_ast_matches_set_oracle` |
| Q7-04 | Phrase matches ordered positions within one value; no cross-value false positives | `pr07_unit::u07_adjacent_phrase`, `u08_stopword_gap`, `u09_repeated_term`, `u10_multi_value_boundary`, `u11_phrase_capability`, `pr07_properties::p02_random_phrases_match_exhaustive_reference`, `search::phrase::tests::*` |
| Q7-05 | BM25 matches an independent oracle and is finite/deterministic | `pr07_unit::u12_bm25_golden`, `u16_scores_are_finite`, `pr07_properties::p03_random_bm25_statistics_match_formula`, `search::score::tests::bm25_golden_values`, `bm25_boundaries_and_invalid` |
| Q7-06 | Top-K equals the full-order prefix; exact count unaffected by K | `pr07_unit::u17_heap_ties`, `u18_topk_prefix_and_exact_count`, `search::topk::tests::*`, `p04_heap_matches_full_sort_for_seeded_cases` |
| Q7-07 | Corrupt/missing/incompatible segment or unsupported operator fails closed | `pr07_faults::f01_unsupported_nested_operator`, `f02_wrong_field_type`, `f03_corrupt_postings`, `f04_analyzer_mismatch`, `search::plan::tests::every_unsupported_operator_fails_closed`, `query_error_maps_to_search_error` |
| Q7-08 | Allocation/work budgets and cancellation apply to every path | `pr07_faults::f06_node_and_term_bounds`, `f07_work_bound`, `f08_allocation_bounds`, `f09_cancel_before_start`, `f10_cancel_during_execution`, `f12_failure_releases_resources`, `pr07_integration::cancellation_before_search_yields_typed_error`, `search::limits::tests::*` |
| Q7-09 | Search is read-only; commit/reopen/PIT semantics unchanged | `pr07_integration::i04_search_is_read_only`, `i08_pit_pinned_across_commit`, `i09_empty_index_and_noop_commit`, `i05_fs_restart_search` |
| Q7-10 | Results and scores invariant under segment partitioning | `pr07_integration::i10_single_vs_multi_segment_equivalence`, `pr07_properties::p05_partitioning_preserves_hits_and_scores`, `i03_multiple_segments` |

## Coverage of the failure matrix

| Failure / boundary | Tests |
|---|---|
| Invalid query / unsupported subtree | `f01`, `plan::every_unsupported_operator_fails_closed`, `f02` |
| Analyzer mismatch / schema incompatibility | `f04`, `u02` |
| Missing term | `u01`, `u14` |
| Corrupt postings/segment | `f03` (codec-level; snapshot verifies content descriptors first) |
| Reader-copy/query-work exhaustion | `f06`–`f08`, `f12` |
| Cancellation at any stage | `f09`, `f10`, integration cancellation test |
| Concurrent refresh/commit | `i07`, `i08` |
| Multi-segment statistics and key merge | `u13`, `i10`, `p05` |
| Duplicate logical keys | Defensive `SearchError::CorruptIndex` path; PR 6 writer prevents the state. See adversarial review for the residual gap. |

## Amendment 01 invariant mapping

Tests live in `crates/quervant-core/tests/pr07_amendment01.rs` unless noted.

| ID | Invariant | Tests |
|---|---|---|
| INV-01 | A leaf only under odd `Not` polarity contributes zero BM25. | `s01_odd_not_leaf_scores_zero`, `s02_or_negative_subtree_does_not_inflate`, `s06_pure_negative_and_matchall_score_zero_without_negative_field_scan` |
| INV-02 | An even-`Not` leaf scores only when it positively matches the returned document. | `s03_double_not_scores`, `s04_same_leaf_mixed_polarity_scores_once` |
| INV-03 | Repeating an identical eligible leaf does not multiply its contribution; scores finite/deterministic. | `s05_duplicate_positive_leaves_do_not_multiply`, `s07_random_boolean_parity_matches_independent_oracle` |
| INV-04 | `max_segment_candidate_entries` bounds the peak per-segment entries, not a lifetime sum. | `b01`, `b02`, `b03`, `b04`, `b05`, `execute::budget_tests::*` |
| INV-05 | Work/scanned limits stay cumulative; failures typed with no partial response. | `b06`, `f01`, `f03`, `execute::budget_tests::overflow_is_typed_and_atomic` |
| INV-06 | Global result bytes, field-length and top-K bytes are independent and checked before growth. | `b07`, `execute::budget_tests::global_plus_segment_byte_sum_is_enforced`, `global_byte_boundary_is_exact`, `topk::tests::h01`, `h02` |
| INV-07 | Each distinct `(field, segment, doc)` length entry counted once. | `l01`, `l02`, `score::tests::l03_*` |
| INV-08 | Membership, phrase semantics, ordering, snapshots and encoding unchanged. | All pre-existing U/I/F/P suites plus `b05`, `l01`–`l02` |

All amendment tests execute and pass; see `validation-report.md` for the exact
command and result.
