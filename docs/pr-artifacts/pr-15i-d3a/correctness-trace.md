# PR 15I-D3-A correctness trace

Status: `IMPLEMENTED_MEASUREMENT_BLOCKED` (T0b). Every invariant below has
a named executable check in `benchmarks/pr15i_d3a/test_*.py` or in the verifier
itself. This file is updated only with executed evidence.

| ID | Invariant | Positive / adversarial check | Evidence |
|---|---|---|---|
| I-01 | Final production source equals verified BASE | Base worktree HEAD/blob check; `git diff` gate in QA | VT-01, G00 |
| I-02 | Scratch patch is insertion-only, six paths, reversible | `source_proof.verify_derivative` + `reverse_insertions` | VT-02, VT-03, VT-04 |
| I-03 | A has no probe; Q/P are one identical binary inactive vs active | Build metadata and `verify_binaries` | VT-05, VT-06 |
| I-04 | Query results, hit counts, order, keys, score bits, cursor unchanged | PR15D independent oracle; D2-A scoring contract suite | VT-07, G01 |
| I-05 | Budgets, cancellation, errors and reservations unchanged | Existing Rust budget/error tests; probe has no error suppression | VT-08 |
| I-06 | Candidate parent encloses all sampled children; children do not overlap | `decompose` tolerance checks | VT-09, VT-10 |
| I-07 | Deterministic per-segment sampling, disabled below 512 | `expected_sample_counts` and descriptor checks | VT-11, VT-12 |
| I-08 | Match-insert sample excludes small/rare results | Both `matched.insert` guards and descriptor totals | VT-13 |
| I-09 | Counters and stages are checked unsigned integers | `strict_array`, `strict_int` | VT-14 |
| I-10 | Top-level, evaluate, score and candidate partitions obey frozen tolerances | `decompose` | VT-15, VT-16, VT-17 |
| I-11 | A/A, Q/A and P/Q intrusion thresholds honored | `recompute_classification` | VT-18, VT-19, VT-20 |
| I-12 | Index, source, corpus, toolchain and oracle identities match | `verify_sources`, `verify_index_layout`, `index_sentinel_failures` | VT-21, VT-22 |
| I-13 | Archival is exclusive, sanitized, re-extractable and immutable | archive round-trip tests | VT-23, VT-24, VT-25, VT-26 |
| I-14 | Closed priority rule applies across both qualified campaigns | `series_decision`, `aggregate_series` | VT-27, VT-28, VT-29, VT-30 |
| I-15 | No optimization, format, scorer or API change | source allowlist and `git diff` gate | G00, G06 |
| I-16 | Every mandatory gate is executed, not merely present | QA table and execution status | G04–G07 |

## Pre-implementation counterexamples

1. **Probe double-counts a fallback path.** A candidate that starts on the
   borrowed keyword path and later falls back must be classified once as
   `fallback`, never as `fast`. Resolution: `CANDIDATE_SAMPLES_FALLBACK` is
   inserted only at entry to `admit_legacy_keyword_candidate`, and
   `CANDIDATE_SAMPLES_FAST` only at the three completed borrowed-path sites.
   The verifier requires `fast + fallback == sampled` and primary lanes require
   zero fallbacks. Checked by `test_04` source anchors and the slot loader.
2. **All small hits are sampled and cause low-hit intrusion.** Resolution: the
   recorder suppresses every candidate micro-timer for `n < 512`, and the
   verifier requires zero sampled time and zero counters for such segments.
   Checked by VT-11/VT-12.
3. **`score_vector` and its nested map time are summed as separate exclusive
   costs.** Resolution: the exclusive partition uses `score_map`,
   `score_owner`, `score_accumulate` only as children of `score_vector`; the
   candidate/intermediate decision uses `score_map + scored_vec_build +
   matched_reserve + temp_release` as disjoint complete intervals and never adds
   `score_accumulate`, `score_vector`, `evaluate` or `membership`. Checked by
   VT-16 and `test_intermediate_disjoint_sum_excludes_nested_score`.

No uncovered counterexample, ambiguous ownership, changed call graph or sibling
path was found after materialization. If any appears during measurement, the
affected instrumentation is a HARD STOP under DXA-07/DXA-10.
