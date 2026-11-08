# PR 15I-C — Diagnostic stage profile and the inlining-cliff finding

Status: `DIAGNOSTIC_PARTIAL` — candidate-side stage data executed; baseline-side
stage data is structurally unavailable (see §4). This is a diagnosis, not an
acceptance gate.

## 1. Instrumentation

* Opt-in, non-default, empty `pr15ic-probe` feature in `quervant-core`
  (no dependency, no default activation).
* `search/diagnostics.rs::probe` — thread-local `[u64; 9]` accumulator with the
  fixed vocabulary `open_and_live_ns`, `expansion_ns`, `stats_ns`,
  `leaf_decode_ns`, `live_work_ns`, `matched_budget_ns`, `scoring_ns`,
  `candidate_sort_heap_ns`, `projection_ns`.
* Guarded stage boundaries only in `search/unified.rs::collect_mixed` /
  `execute_unified` and `search/execute.rs::for_each_exact_term_score_with`. Each
  region is timed exclusively; no inclusive nesting is double-counted.
* Driver: `benchmarks/pr15i_c/stage_probe` (standalone pinned lockfile, public
  API only). It resets the accumulator, times `UnifiedSearcher::search` for
  `total_search_ns`, and computes
  `other_unattributed_ns = max(0, median_total - sum(median stages))`.
* Verified absent from default builds:
  `strings target/release/libquervant_core.rlib | grep -c open_and_live_ns` → `0`
  without the feature and `2` with it.

## 2. Candidate-side stage samples (100K, `runs=5`, `warmups=3`)

Median nanoseconds, from `target/pr15i-c/diag/out/B-*.json`:

| stage | rare/k100 | common/k100 |
|---|---|---|
| `total_search_ns` | 502,208 | 42,107,937 |
| `open_and_live_ns` | 144,703 | 151,402 |
| `expansion_ns` | 600 | 2,000 |
| `stats_ns` | 53,301 | 55,400 |
| `leaf_decode_ns` | 1,000 | 8,327,826 |
| `live_work_ns` | 264,205 | 344,405 |
| `matched_budget_ns` | 100 | 200 |
| `scoring_ns` | 600 | 1,178,317 |
| `candidate_sort_heap_ns` | 2,000 | 25,215,181 |
| `projection_ns` | 8,000 | 5,259,879 |
| `other_unattributed_ns` | 27,699 | 1,573,327 |

The 100K common query is dominated by posting decode (the `live_work` scan then
costs 8.3 ms), scoring 1.2 ms and the canonical sort/heap 25.2 ms — which is
exactly where the removed matched/scored trees used to sit.

## 3. Controlled experiments (adapter binary, same index, same corpus)

| Variant (all from candidate source unless noted) | 100K absent/k100 | 100K rare/k100 | 100K common/k100 |
|---|---|---|---|
| merged PR 15I-B baseline A | 251,704 | 263,204 | 46,935,378 |
| candidate B (fast path active) | 424,307 | 425,907 | 40,192,966 |
| candidate, `c_physical` forced `false` (generic path) | 436,606 | 429,107 | — |
| candidate, predicate call replaced by literal `false` | 247,303 | 262,404 | 49,281,333 |
| candidate, predicate call replaced by a trivial non-inlined call | 440,707 | 434,507 | 50,450,656 |
| candidate, `#[inline(always)]` predicate | 464,907 | 451,107 | 41,824,433 |
| baseline A + candidate helper added as dead code (no call) | — | 280,204 | 49,264,828 |

Interpretation: the regression on low-match lanes is **not** produced by the new
operator's work. It appears as soon as `collect_mixed` contains *any* data-dependent
non-inlined call before the segment loop — even a call whose body is
`standalone && !retain && false`. A dead-code copy of the helper and restoring the
call to a compile-time `false` both return the baseline timings. This is a
codegen/inlining cliff in the (large, fully inlined) `collect_mixed`, not an
algorithmic cost of `C-EXACT-ONE`.

## 4. Declared gap

The plan asks for the stage probe to run on baseline **A** and candidate **B**. A
cannot build it: the `pr15ic-probe` feature and its instrumentation are introduced
by C, so the feature does not exist at the baseline commit and
`cargo build --features pr15ic-probe` fails there. A scratch baseline worktree was
instead instrumented with an identical probe patch, but that changes the measured
baseline and cannot be used as baseline evidence. Per the plan's diagnostic
completion rule, the final status is therefore
`15IC_PERFORMANCE_MEASURED_DIAGNOSTIC_PENDING`, never
`15IC_LOCAL_QUALIFIED_REVIEW_READY`.
