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

## Amendment 02 invariant mapping

Tests live in `crates/quervant-core/tests/pr07_amendment02.rs` plus private
`search/execute.rs::budget_tests`.

| ID | Invariant | Tests |
|---|---|---|
| INV-A2-01 | No result batch exists without a live global charge; transfer is atomic | `budget_tests::a2_01_transfer_is_atomic_and_preserves_total`, `a2_05_global_plus_segment_boundary_is_atomic` |
| INV-A2-02 | Global + segment logical bytes never exceed the limit at a reservation/transfer | `a2_03_multi_segment_batch_boundaries`, `budget_tests::a2_05`, `a2_10_many_small_segments_reset_peak` |
| INV-A2-03 | Phrase scratch ends when scratch storage dies | `a2_02_sequential_phrase_scratch_is_released` (fails on `161cf5e`) |
| INV-A2-04 | Each retained collection has one charge and one release/transfer | `a2_08_boolean_set_algebra_and_peak`, `a2_10` (fails on `161cf5e`) |
| INV-A2-05 | Rejected operations are atomic and return no partial result | `budget_tests::a2_04_transfer_rejections_are_atomic`, `a2_09_cancellation_and_work_exhaustion_recover` |
| INV-A2-06 | Per-segment entries reset only after temporaries die | `a2_10` |
| INV-A2-07 | Membership/BM25/top-K/snapshots unchanged | `a2_11_memory_and_fs_agree`, `a2_12_seeded_differential_membership`, all existing suites |
| INV-A2-08 | Work/scanned limits and cancellation stay independent | `a2_09` |

Pre-fix evidence: on `161cf5e` the same `pr07_amendment02.rs` fails
`a2_02_sequential_phrase_scratch_is_released` and
`a2_10_many_small_segments_reset_peak`, and passes the other four. The A2-01
transfer-gap boundary is not observable end-to-end (segment-charge checks
dominate) and is covered by the private atomic-transfer unit tests.

## Amendment 03 invariant mapping

Tests live in `search/execute.rs::budget_tests` (T), `search/phrase.rs::tests`,
and `tests/pr07_amendment03.rs` (P).

| ID | Invariant | Tests |
|---|---|---|
| T01 | A failed `release_segment` (valid entries, excessive bytes) mutates nothing | `t01_direct_release_is_atomic_on_mixed_underflow` (red on `66b512b`) |
| T02 | Ledger `release` preflights ledger state before the budget | `t02_ledger_release_preflights_before_budget_mutation` (red) |
| T03 | `transfer_to_global` preflights both owners | `t03_transfer_preflights_ledger_state` (red) |
| T04 | `reserve` rejects inconsistent ledger without budget mutation | `t04_reserve_preflights_ledger_state` (red) |
| T05 | Near-`u64::MAX` overflow is typed and atomic | `t05_near_max_overflow_is_typed_and_atomic` |
| T06 | Valid reserve/release/transfer/finish reaches consistent zero | `t06_valid_sequence_reaches_consistent_zero` |
| T07 | Seeded 300-op sequence matches an independent tuple model | `t07_seeded_transactions_match_tuple_model` (red) |
| T08 | Drop cleans consistent state; injected inconsistency never touches global | `t08_drop_cleanup_and_injected_inconsistency` (red) |
| P01 | `phrase.rs` internal chain references are charged before allocation | `p01_chain_reference_scratch_is_charged` (red on `66b512b`) |
| P02 | Simultaneous old/new candidate vectors are charged | `p02_intersection_replacement_is_charged_atomically` |
| P03 | Long repeated-token chains are bounded; membership unchanged | `p03_long_repeated_chain_membership_unchanged` |
| P04 | Sibling phrase scratch is released, not cumulative | `p04_sibling_phrase_scratch_not_cumulative`, `pr07_amendment02::a2_02` |
| P05 | Phrase scratch participates in the combined global+segment byte bound | `p05_global_plus_phrase_scratch_combined_bound` |
| P06 | Mid-stage rejection cleans up and a fresh request succeeds | `p06_rejection_stages_clean_up_and_retry` |
| P07 | Cancellation during phrase work cleans up | `p07_cancellation_during_phrase_work_cleans_up` |
| P08 | Multi-value/stopword/repeated/position semantics unchanged | `p08_multivalue_and_position_semantics` |
| P09 | Memory and filesystem directories agree | `p09_memory_and_fs_agree` |
| P10 | Seeded 200-case phrase membership and BM25 scores match an oracle | `p10_seeded_phrase_oracle_membership_and_scores` |
| P11 | Empty/one-token/no-candidate phrases are safe | `p11_degenerate_phrases_are_safe`, `phrase::tests::phrase_scratch_returns_to_zero` |
| P12 | Long output terms are handled once by the caller's reservation | `p12_long_terms_in_output_are_handled` |
| R01 | Existing PR 7/Amendment 01–02 suites remain green | full workspace suite |

## Amendment 04 measurement matrix

Benchmark infrastructure only. Tests live in `crates/quervant-core/tests/pr07_amendment04.rs`
and `benchmarks/scripts/test-scripts.sh`.

| ID | Invariant / acceptance | Evidence |
|---|---|---|
| A4-T01 | Identical seed/axes → identical digest and oracle hits | `a4_t01_deterministic_fixture_and_digest` |
| A4-T02 | Seed/doc-count/segment change changes the digest | `a4_t02_digest_is_axis_sensitive` |
| A4-T03 | Rare=1, absent=0, medium/common match the ledger at 2K/10K/100K | `a4_t03_selectivity_counts` |
| A4-T04 | Phrase present/absent/repeated oracle agreement | `a4_t04_phrase_oracle` |
| A4-T05 | Term/AND/OR/MatchAll/pure-negative set oracle | `a4_t05_boolean_oracle` |
| A4-T06 | Top-K truncation preserves total hits and ranking; stable repeats | `a4_t06_topk_truncation_and_stability` |
| A4-T07 | 0% tombstones; 25% NOT APPLICABLE (insert-only) | `a4_t07_deletions` |
| A4-T08 | Single- vs four-segment logical/score equivalence | `a4_t08_segment_partition_equivalence` |
| A4-T09 | Benchmarks compile on stable + MSRV; dev-only dependency | `cargo bench --no-run` ×2; `Cargo.toml` |
| A4-T10 | Missing profiler → UNAVAILABLE, never fake PASS | `test-scripts.sh` (perf/heaptrack) + fake-perf success |
| A4-T11 | Invalid mode/workload/args → nonzero diagnostics | `test-scripts.sh` |
| A4-T12 | Corrupted oracle expectation aborts before timing | `a4_t12_oracle_gate_rejects_wrong_expectation` (`#[should_panic]`) |
| A4-T13 | Fixtures built outside `b.iter`; benches smoke under `cargo test` | source structure; `cargo test --bench ...` "Success" |
| A4-T14 | Provenance runs preserved, not overwritten | `test-scripts.sh`; unique run dirs in runner |
| A4-T15 | Manifest validator rejects missing/contradictory/malformed/dirty | `validate-report.py` + `test-scripts.sh` |
| A4-T16 | Ratio gating policy | `benchmarks/README.md`, `docs/BENCHMARKING.md` (no competitor run) |
| A4-T17 | Existing PR 7 suites green | full workspace suite (1020 passed) |
| A4-T18 | Profiling produces samples or BLOCKED evidence | **BLOCKED/UNAVAILABLE** (no profiler); diagnostics in review |

## Amendment 04 Correction 01 matrix

Evidence: `tests/pr07_amendment04.rs` (`c01_*`), `benchmarks/scripts/test-scripts.sh`
(30 checks), and the real-artifact assembly smoke test.

| ID | Acceptance | Evidence |
|---|---|---|
| C-T01 | 2K metadata: phrase present 8, repeated 16, absent 0, rare 1, common 1000 | `c01_workload_metadata_counts`; script metadata check |
| C-T02 | 10K/100K counts (40, 5000, 50000) and digests | `c01_*`; script |
| C-T03 | Validator rejects false-zero phrase-present in v2 | script (`false-zero`) |
| C-T04 | Rejects wrong corpus/query/top-K/segments | script (`wrong-corpus`) |
| C-T05 | Non-query rows null + N/A; invented zero rejected | script (`nonquery-zero`); `c01_*` |
| C-T06 | Missing/duplicate/extra workload rows fail closed | script (`duplicate`, `extra`, missing-estimate) |
| C-T07 | Bad numeric (CI, samples, ratio) rejected | script (`bad-ci`, `zero-samples`, `wrong-ratio`) |
| C-T08 | Dictionary throughput `Elements(1)`, unit lookups | source assertion in script |
| C-T09 | Idle snapshot → `clear`, sanitized | script (synthetic snapshots) |
| C-T10 | Unrelated sustained CPU → `suspected` | script |
| C-T11 | Runner ancestry excluded; unrelated worker counted | script (`--self-pid`) |
| C-T12 | Missing/zero-tick `/proc` → `unknown`, not clear | script (zero elapsed ticks) |
| C-T13 | Preflight suspected/unknown stops runner | runner exits 3 before Criterion (see baseline disposition) |
| C-T14 | Mid-run contention marks whole run unqualified | runner logic; scripts |
| C-T15 | Historical report timing unchanged; v1 only via `--historical` | script; `--historical` validator |
| C-T16 | Qualification prerequisites enforced | validator (`false-qualified`, `dirty-qualified`) |
| C-T17 | Missing idle confirmation/dirty tree cannot qualify | script (`false-qualified`, `dirty-qualified`) |
| C-T18 | Three-trial aggregate only when all qualified | `aggregate-pr07-baseline.py` (requires ≥3 qualified) |
| C-T19 | Assembly failure/interrupt: no partial qualified artifact | atomic `os.replace`; builder fails closed on missing/extra |
| C-T20 | Relative-comparison policy documented | `benchmarks/README.md`, `docs/BENCHMARKING.md` |
| C-T21 | Profiler unavailable → `UNAVAILABLE`, not PASS | script |
| C-T22 | Existing Amendment 04 correctness unchanged | `pr07_amendment04` 11 tests; full workspace suite |
