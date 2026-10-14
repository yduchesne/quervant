# PR 8 adversarial review — advanced lexical multi-term operators

This document enumerates the high-risk semantic invariants, the plausible ways an
implementation can be wrong, and the exact test that discharges each risk. It is
the Phase 0 adversarial gate from the PR 8 plan §6 and is updated as evidence is
produced. A semantic mismatch is never an accepted residual risk.

## High-risk failure modes and their discharge

### I01 — whole-term normalized matching
- **Risk:** prefix is treated as substring; glob is treated as regex over source
  text; `^`/`$` anchoring forgotten so `u` matches `rust`; patterns are reparsed
  from raw input instead of the PR 4 prepared form.
- **Discharge:** T01 (`p8_t01_prefix_whole_term`), T02 (`p8_t02_prefix_empty_absent`),
  T03 (`p8_t03_glob_whole_term_and_escape`), T04 (`p8_t04_regex_whole_term`),
  T05 (`p8_t05_pattern_rejected_before_reader`). All patterns are compiled from
  `PreparedPrefix`/`PreparedGlob`/`PreparedRegex`, never reparsed.

### I02 — Unicode scalar semantics
- **Risk:** `?` consumes one UTF-8 byte rather than one scalar; case/NFC/ASCII
  folding differs between index and pattern; regex `.`/classes operate on bytes.
- **Discharge:** T06 (`p8_t06_question_mark_scalar`), T07 (`p8_t07_unicode_folding`),
  T08 (`p8_t08_regex_unicode_classes`). The trie and automata transition on
  decoded Unicode scalar values.

### I03 — fuzzy distance exactness
- **Risk:** byte-wise edit distance; unrestricted Damerau instead of restricted
  OSA; `max_edits` accepted above 2; multi-token or non-lexical values accepted.
- **Discharge:** T09 (`p8_t09_fuzzy_edits_reference`), T10 (`p8_t10_osa_transposition`),
  T11 (`p8_t11_osa_vs_unrestricted`), T12 (`p8_t12_fuzzy_typed_errors`). The
  independent oracle is a full-matrix Levenshtein and OSA DP over scalars.

### I04 — global stats and per-document dedup
- **Risk:** per-segment IDF; overlapping positive leaves double count a
  `(field, term)`; zero-expansion leaf becomes MatchAll; legacy vs new-format
  BM25 diverges.
- **Discharge:** T13 (`p8_t13_global_df_segments`), T14 (`p8_t14_mixed_legacy_new_bm25`),
  T15 (`p8_t15_two_expanded_terms_sum`), T16 (`p8_t16_overlap_no_double_score`),
  T17 (`p8_t17_zero_expansion_or_semantics`). The oracle recomputes
  `n/df/dl/avgdl` and BM25 from fixture analyzer tokens.

### I05 — Boolean/PIT/ranking
- **Risk:** `Not` polarity changes; pure-negative queries score; phrase+prefix
  intersection wrong; TopK truncation changes `total_hits` or tie order.
- **Discharge:** T18 (`p8_t18_boolean_combinations`), T19 (`p8_t19_negative_only_zero`),
  T20 (`p8_t20_phrase_and_prefix`), T21 (`p8_t21_topk_exact_total_tie_order`).

### I06 — boundedness
- **Risk:** expansion/work/state/FST/fuzzy-length limits unenforced, off-by-one,
  or enforced only after partial results; broad `*` unchecked.
- **Discharge:** T22 (`p8_t22_expanded_terms_exact_one_over`), T23
  (`p8_t23_combined_unique_terms`), T24 (`p8_t24_broad_glob_no_match_work`),
  T25 (`p8_t25_fst_bytes`), T26 (`p8_t26_automaton_states`),
  T27 (`p8_t27_fuzzy_scalar_length`), T28 (`p8_t28_pr7_limits_retained`).

### I07 — cancellation and failure recovery
- **Risk:** cancellation only before/after the whole query; partial results on
  failure; snapshot left unusable.
- **Discharge:** T29 (`p8_t29_precancel`), T30 (`p8_t30_cancel_during_traversal`),
  T31 (`p8_t31_cancel_during_postings`), T32 (`p8_t32_failure_then_recovery`).
  `SearchWork::charge` polls cancellation at fixed intervals during trie walks.

### I08 — lifecycle and compatibility
- **Risk:** a format/writer change; frozen legacy fixture regenerated; PIT leaks
  a later generation; single vs sorted-remapped segment differ.
- **Discharge:** T33 (`p8_t33_memory_commit_reopen`), T34
  (`p8_t34_fs_commit_reopen_no_writes`), T35 (`p8_t35_pit_vs_fresh`),
  T36 (`p8_t36_frozen_legacy_all_operators`), T37
  (`p8_t37_single_vs_multisegment_remap`). Frozen fixture bytes are asserted
  unchanged and are never regenerated.

### I09 — domain identity
- **Risk:** implicit confusable skeleton / TLD weighting; original keys changed;
  case/IDNA normalization inconsistent with PR 4.
- **Discharge:** T38 (`p8_t38_domain_canonical`), T39 (`p8_t39_domain_typo_transposition`),
  T40 (`p8_t40_domain_tld_raw_distance`), T41 (`p8_t41_domain_identity_preserved`).
  Domain fuzzy reuses the same `Fuzzy` operator over the canonical domain field.

### I10 — unchanged formats / standalone core
- **Risk:** new segment section or feature id; PR 7 regressions; remote/distributed
  import into `quervant-core`.
- **Discharge:** T42 (`p8_t42_golden_bytes_features_unchanged`), T43 (all PR 7
  suites), T44 (`p8_t44_core_no_remote_distributed`). No codec/writer/manifest
  change is present in the diff.

## Residual/known risks

- Runtime derived trie construction is per request/segment/field and is not
  cached across requests. This is the deferred `SegmentCache`/norm-cache
  optimization (roadmap performance work); it is **not** a semantic risk.
- `max_fst_bytes` accounts logical trie bytes, not measured RSS; this is
  documented in the API and in production comments.
- Remote ObjectStore runtime and real RustFS acceptance belong to PR 13; PR 8
  exercises only local `MemoryDirectory`/`FsDirectory`.

---

**Amendment 01 (resource accounting):** see
[amendment-01-implementation-report.md](amendment-01-implementation-report.md),
[amendment-01-preflight.md](amendment-01-preflight.md),
[amendment-01-adversarial-review.md](amendment-01-adversarial-review.md),
[amendment-01-validation-report.md](amendment-01-validation-report.md) and
[amendment-01-test-traceability.md](amendment-01-test-traceability.md). The original
PR 8 evidence above is unchanged.
