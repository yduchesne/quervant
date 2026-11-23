# PERF-05-B5 — Source-Grounded GO/NO-GO Feasibility Review

**Review date:** 2026-11-22 (America/Los_Angeles)
**Repository / PR:** `yduchesne/quervant` / [PR #117](https://github.com/yduchesne/quervant/pull/117)
**Inspected branch:** `dev/perf05-physical-execution-series` at `3b25a76b99f699c45aa2050c4f889880a138948a`
**Base `main`:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8` (ahead by 16 commits; behind by 0 at inspection)
**Evidence class:** Static source review and historical-document reconciliation; **no build, test, performance benchmark or profiler was run**.

## Decision

**`B5_GO_NARROW_BORROW_THEN_MOVE_HANDOFF`**. B5 is feasible **only** as an ownership-transfer optimization that retains the current full, eager, validated posting-list decode. **`B5_NO_GO_STREAMING_CURSOR_OR_EXECUTOR`**: direct streaming from the segment reader, new physical dispatch, late/nonwinner scoring, Top-K early stop, and a revised postings format are not authorized.

This is a **design GO**, not an implementation, correctness acceptance, proof of speedup, or merge permission. B5 must pass independently reviewed implementation/QA gates. Adoption still depends on the single final warm A/B campaign of PERF-05-C.

## Verified current-source facts

1. `search/unified.rs::single_term_postings_eligible` requires root `UnifiedNode::Lexical(0)`, exactly one `CompiledLeaf::Term` with one analyzed term, no typed leaves, sole positive lexical leaf `{0}`, no aggregation and no `after` cursor. Sort and batch are not categorically excluded.
2. `search/unified.rs::collect_mixed` passes that eligibility to `evaluate_lexical_with`. For the eligible case, its `is_match` callback returns `true` without inspecting `LeafData`; the callback still runs for **every** candidate. Other shapes call the ordinary predicate evaluator.
3. `search/execute.rs::build_leaf_data` drains `PostingsReader::next_with`, charges scanned-frequency work, validates posting doc IDs against the effective-live bitmap, reserves `TERM_POSTING_BYTES` for every retained live posting, then stores ascending `(doc_id, u64 freq)` pairs in `TermPostings.postings`. **All this happens before eligible examination and match callbacks.**
4. B4's `evaluate_lexical_with` then copies every accepted `(doc_id,freq)` into a second `single_term_matched: Vec<(u64,u64)>`; full-match production requests copy all retained effective-live postings. The generic ineligible path uses a different `matched: Vec<u64>`.
5. Only after the callbacks does the evaluator reserve `M * SET_BYTES_PER_ENTRY` (48 bytes per accepted document) and the B4 helper reserve `M * SCORED_MAP_BYTES_PER_ENTRY` (64 bytes per accepted document), then calculate all `bm25` contributions into a separate `Vec<(u64,f64)>`. Existing release order is matched, leaf, scored. `SegmentCandidateLedger` provides checked admissions and RAII cleanup on errors.
6. `score_single_term_candidates` needs only the accepted pairs, field ID, term string, stats and segment index; it does **not** consult `TermPostings.postings` or call the predicate. A move can leave that vector empty **after all callbacks** while leaving its term string and field ID intact for scoring.
7. The eligible iterator's logical examination charge and cancellation polls are already decoupled from its buffer representation (B2), and the generic scorer/sibling lexical executor need no changes.

These facts were checked against the exact B4 source, not inferred solely from the plan or execution report.

## Concrete design: borrow during callbacks, then move the owned allocation

For the strictly eligible branch **only**:

1. Keep `build_leaf_data`, every decoding/corruption/work/memory operation, and the initial shape guard unchanged.
2. Borrow the original posting slice while invoking the original cancellation polls and original `is_match` callback exactly once per posting. **Do not mutate or move the postings while callbacks are running**; the callback's `&[LeafData]` remains complete.
3. Normal production requests accept every posting, so collect no duplicate candidate pairs. After **all callbacks** complete, use `std::mem::take(&mut terms[0].postings)` to move the original `Vec<(u64,u64)>` allocation into `single_term_matched`. The original `TermPostings` remains structurally present with its term text and an empty vector.
4. To preserve the more general `evaluate_lexical_with` callback contract for synthetic/injected rejection, use a **lazy rejection fallback**: on the first callback returning false, copy the previously accepted prefix into the candidate `Vec`, then append subsequent true matches; never move the original postings in this rejection case. Thus the callback still observes the complete original leaf data on every call, including after a rejection. False callbacks remain false, never become internal corruption errors.
5. Keep the entire post-loop matched reservation, B4 score helper dispatch, BM25 arguments, output vector, and matched/leaf/scored reservation **release order unchanged**. Drop the moved candidate vector before releasing its unchanged original *leaf* charge. This preserves conservative modeled accounting even though the underlying allocated buffer has changed owner.
6. Provide a small private checked handoff helper and a bounded match-selection state; add test-only witnesses to prove the normal path uses the move and an injected rejection uses the old copy semantics. No public API, storage format, flag or eligibility change.

**Expected structural saving:** no second full-M `Vec<(u64,u64)>` allocation, append sequence or corresponding physical retention for the normal eligible path. A 49,999-document, all-match term has 49,999 × 16 = **799,984 bytes** of payload in the redundant copied vector (excluding capacity overhead); this is a **source-based payload count, not measured heap savings**. B5 still performs full postings decoding and full-M BM25 and returns a separate full-M `Vec<(u64,f64)>`. It is not a streaming/Top-K collector and does not promise a 5% latency improvement.

## Error, ownership and budget precedence proof obligations

| Boundary | B4 order | B5 frozen order | Failure action |
| --- | --- | --- | --- |
| Decode and validate | Complete full `build_leaf_data` before any predicate callback | Exactly the same | STOP if eager validation changes |
| Per-posting work and corrupted nonwinner | All postings validated and work charged | Exactly the same | STOP if any omitted or deferred |
| Verified live examination, charge, polls | Before candidate callbacks | Exactly the same | STOP if counts or poll schedule differ |
| Callback | Exactly once per posting, full leaf visible; false excludes posting | Exactly the same; handoff occurs after final callback | STOP if any callback sees empty/moved data |
| Accepted candidate selection | Accepted `(doc_id,freq)` copied per successful callback | Borrow-only on all-true; lazy duplicate if any false | STOP if false/subset behavior differs |
| Matched reservation | Once, `M*48`, after callbacks | Exactly the same | STOP on earlier/lower admission |
| Scored reservation | Once, `M*64`, before BM25 | Exactly the same | STOP on earlier score calculation |
| BM25 | Existing B4 helper, all M accepted | Exactly the same | STOP on score bits, error differences |
| Drop/release | Drop matched, candidate, leaf; release matched, leaf, scored | Same order; moved allocation dies when candidate dies | STOP on leak or premature charge release |
| Unified consumer | All scored candidates checked for key, sort, duplicate, Top-K | Unchanged | STOP on skipped nonwinning validations |

**Physical allocator limitations:** The old and new paths can differ in allocator timing. The model does not guarantee absence of machine-level OOM or instruction-layout regressions; do not claim such a guarantee. Deterministic typed resource-limit and cancellation/error precedence must be tested and preserved.

## Novelty versus rejected experiments

| Historical investigation | Rejected mechanism/evidence | Why B5 is genuinely different |
| --- | --- | --- |
| PR 15G-C | Fused streaming/top-K collector and later two-pass fixes. Qualified high-hit regressions: B/A 1.154 for 100K common/K100 and 1.284 for common/K10; absent/rare regressions | B5 keeps eager full decoding, full-M matching, full-M scoring and the existing unified consumer. No new streaming executor, later score, or new Top-K algorithm |
| PR 15G-D | Isolated D2 change rejected with 10K rare guard and inconclusive common/K10 | B5 retains one existing decode, never adds a second reader pass or an alternate physical query mode |
| PR 15H-A / A2 | Linear candidate staging, then 8,192-posting cardinality gate; both regressed absent/rare guards despite high-hit gains | B3/B4 already supply the accepted ordered candidate and scorer. B5 changes **ownership only**; no new cardinality threshold, staging strategy or generic fallback switch |
| PR 15I-C | Specialized postings-driven physical executor; low-match regression even with physical collector runtime-disabled. Rejected and restored baseline | B5 introduces neither a physical executor nor runtime flag/dispatch. **Source-code layout risk remains**, so no low-hit neutrality claim until PERF-05-C warm A/B qualifies |

The register's conditional B5 objective is met by a **borrowed-view handoff into the canonical buffer followed by an owned `Vec` move**. A *direct segment cursor* is not safe to authorize from this source analysis because it would require re-proving the eager decoding/validation-before-callback boundary and potentially introducing old rejected mechanisms. This approval does **not** authorize replacing `build_leaf_data`.

## Decision gates

| Gate | Assessment |
| --- | --- |
| Distinct, source-proven redundancy left after B4 | PASS: second full-M accepted pair allocation/copy |
| Full eager decoding and corruption checks can remain | PASS: unchanged `build_leaf_data` |
| Callback sees complete `LeafData` until last callback | PASS by design: handoff occurs afterward |
| All-true normal request can reuse owned allocation without `unsafe` | PASS by design: `std::mem::take` |
| Callback false/subset semantics can be retained | PASS by bounded lazy rejection fallback; mandatory targeted tests |
| Conservative 16/48/64-byte logical admissions retained | PASS by design; mandatory tests |
| Novel compared with 15G/15H/15I | PASS at architectural mechanism level |
| Code compiled / tests run on B5 | NOT YET; B5 implementation pending |
| Measured warm latency improvement / sparse neutrality | NOT YET; PERF-05-C only |

**Recommended next step:** implement only the handoff specified above, using `PERF05B5_DETAILED_PLAN.md` on the **same PR #117**. Review B5 independently, then initiate the single consolidated PERF-05-C warm A/B and profiler campaign. Any design that cannot satisfy the frozen contract is a **B5 HARD STOP / skip B5**, not an instruction for the coding agent to improvise a new streaming executor.

## Evidence references

- [`search/execute.rs` at B4](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/crates/quervant-core/src/search/execute.rs)
- [`search/unified.rs` at B4](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/crates/quervant-core/src/search/unified.rs)
- [`PERF05B_IMPLEMENTATION_REGISTER.md`](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md)
- [`PERF05A_PIPELINE_COMPARISON.md`](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/docs/pr-artifacts/perf-05/PERF05A_PIPELINE_COMPARISON.md)
- [`PERF_OPTIMIZATION_PLAN.md`](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/docs/PERF_OPTIMIZATION_PLAN.md)
- [`PR 15I-C closeout`](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/docs/pr-artifacts/pr-15i-c/closeout.md)
- [`PR 15G-C qualification`](https://github.com/yduchesne/quervant/blob/3b25a76b99f699c45aa2050c4f889880a138948a/docs/pr-artifacts/pr-15g-c/performance-qualification.md)
