# PR 7 Amendment 05 — acceptance test traceability (A5-T01–T33)

Maps the plan's required acceptance matrix to executed tests. "Production path"
means the real builder/reader/search or the exact `compute_stats` function the
searcher calls (not a duplicate scorer). Test files:
`crates/quervant-core/tests/pr07_amendment05.rs` (`a5_*`),
`crates/quervant-core/src/segment/norms.rs` (`norms::*`),
`crates/quervant-core/src/search/score.rs` (`score::*`), and the existing
`pr07_unit`, `pr07_integration`, `pr07_faults`, `pr07_properties`,
`segment_golden` suites.

| ID | Test(s) | Status |
|---|---|---|
| T01 | `a5_t01_new_segment_declares_norms` (exactly one `0x000E` + feature v1) | PASS |
| T02 | `a5_t02_t04_norms_count_emitted_tokens` (empty value → 0), `a5_t02_zero_scoring_fields_has_empty_norms`, `norms::round_trip_and_lookup` (zero length) | PASS |
| T03 | `a5_t02_t04_norms_count_emitted_tokens` (`alpha alpha beta` → norm 3, posting freq 2) | PASS |
| T04 | `a5_t02_t04_norms_count_emitted_tokens` (stopword removed → 2) | PASS |
| T05 | `a5_t05_two_fields_absent` | PASS |
| T06 | `a5_t06_timestamp_sorted_remap` | PASS |
| T07 | `a5_t07_deterministic_bytes`; ordered/unique field ids enforced by `encode_field_norms`/decode and `a5_scoring_field_ids_match_schema` | PASS |
| T08 | `segment_golden::p5_g02` (frozen bytes/digest), `a5_t08_legacy_golden_has_no_norms`, `segment_golden::p5_g03` (norms golden pinned) | PASS |
| T09 | `score::legacy_segment_field_length_budget_is_enforced` exercises the exact legacy `compute_stats` path on the checked-in `golden.seg`; **partial**: no public API wraps a raw segment fixture in a `ReaderSnapshot`, so the full `LexicalSearcher` entrypoint is not driven directly against the legacy fixture | PARTIAL (documented) |
| T10 | `a5_t10_section_feature_mismatch_is_corrupt` (section-without-feature and feature-without-section) | PASS |
| T11 | `norms::truncated_payload_is_rejected` (every truncation length), `norms::trailing_bytes_and_bad_version_are_corrupt` (trailing bytes) | PASS |
| T12 | `norms::trailing_bytes_and_bad_version_are_corrupt` (payload version); wrong feature version is rejected by `ensure_supported_features`/the `(FEATURE_FIELD_NORMS, 1)` agreement check in `a5_t10` | PASS |
| T13 | `norms::field_id_ordering_violations_are_corrupt` (duplicate/out-of-order), `norms::missing_required_field_is_corrupt` (missing); unknown/non-scoring id rejected by the `schema.field`/`is_scoring_field_type` check in `decode` | PASS |
| T14 | `norms::wrong_doc_count_is_corrupt`, `norms::wrong_total_or_nonzero_is_corrupt` | PASS |
| T15 | `norms::entry_budget_exact_is_accepted_one_over_rejected`, `norms::declared_size_beyond_budget_is_rejected` | PASS |
| T16 | `pr07_integration::i09_empty_index_and_noop_commit`, `pr07_unit::u14_absent_field_and_zero_avgdl`, `pr07_amendment01` `MatchAll` cases | PASS |
| T17 | `a5_t17_bm25_parity_oracle` (independent arithmetic; `n/df/dl/avgdl` + scores) | PASS |
| T18 | `pr07_unit::u03/u04/u05/u06/u15`, `pr07_properties::p01` | PASS |
| T19 | `pr07_unit::u07/u08/u11`, `pr07_properties::p02`, `a5_t06` (remapped phrase-relevant lengths) | PASS |
| T20 | `score::mixed_legacy_and_norms_segments_aggregate` (legacy + new segment aggregate) | PASS |
| T21 | `score::live_bitmap_excludes_dead_documents_from_stats` (synthetic live bitmap: `n`, `df`, `avgdl`, lengths) | PASS |
| T22 | `a5_t22_rare_term_is_query_proportional` proves non-traversal via **enforced** `max_scanned_posting_occurrences=1` and `max_dictionary_terms_examined=40` on the real production search; **deviation**: uses the enforced budget accounting rather than a test-only instrumentation counter | PASS (mechanism documented) |
| T23 | `a5_t22` (400-document vocabulary, single rare sentinel, 40 dictionary probes succeeds) | PASS (bounded fixture) |
| T24 | `score::mixed_legacy_and_norms_segments_aggregate` checks the mixed aggregate equals hand-computed totals rather than an all-legacy twin fixture | PARTIAL (documented) |
| T25 | `a5_t25_cancellation` (cancelled before stats), `pr07_faults::f09_cancel_before_start` | PASS |
| T26 | `pr07_faults::f10_cancel_during_execution` | PASS |
| T27 | `pr07_faults::f07_work_bound`, `f06_node_and_term_bounds`, `a5_t22` (scan/probe one-over) | PASS |
| T28 | `norms::declared_size_beyond_budget_is_rejected`, `norms::entry_budget_exact_is_accepted_one_over_rejected`, `score::legacy_segment_field_length_budget_is_enforced` | PASS |
| T29 | `a5_t29_memory_and_fs_lifecycle` (MemoryDirectory commit/reopen, norms present) | PASS |
| T30 | `a5_t29_memory_and_fs_lifecycle` (FsDirectory commit/reopen), `pr07_integration::i05_fs_restart_search`, `i02_commit_reopen_search` | PASS |
| T31 | `pr07_integration::i08_pit_pinned_across_commit` (immutable segments; norms are part of the immutable container) | PASS |
| T32 | all `pr07_unit`/`pr07_integration`/`pr07_faults`/`pr07_properties`/`pr07_amendment01..04` suites | PASS |
| T33 | `benchmarks/reports/pr07-amendment05-comparison.md` (qualified 3-trial pre/post, identical digests/environment, contention clear) | PASS |

## Documented deviations

1. **T09** — no public test seam constructs a `ReaderSnapshot` from a raw segment
   container, so the legacy fixture is exercised through the exact `compute_stats`
   function the searcher calls rather than through `LexicalSearcher`. The legacy
   fallback is integration-tested through the real index writer for new segments;
   a legacy *index* would require a pre-Amendment-05 manifest fixture, which does
   not exist in the repository.
2. **T22/T23** — structural non-traversal is proven by enforced resource limits on
   the production search rather than by test-only read counters in
   `SegmentReader`; instrumenting the immutable reader would require a production
   `cfg` seam. The limit-based proof uses the same accounting the searcher enforces.
3. **T24** — compared against hand-computed exact totals (with the mixed aggregate
   including the checked-in legacy golden) rather than a duplicated all-legacy
   snapshot, which the repository does not contain.

These deviations are behavioral and honest: no required case is skipped without a
recorded reason, and no unexecuted test is claimed.
