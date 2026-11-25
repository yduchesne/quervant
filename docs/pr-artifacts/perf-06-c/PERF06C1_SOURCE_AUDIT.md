# PERF-06-C1 — Source reconciliation, evidence and design decisions

**Artifact type:** documentation-only C1 record. **Source:** `yduchesne/quervant`, accepted `main@8c9f51f311afa5b327f70432e32c0f6f5c205eab`, after B4 PR #129 merged. **Delivery:** C1 documents the execution contracts; it implements **no Rust code and no contract tests**. This record supports the [physical executor contract](../../architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md).

## 1. Why C1 is documentation only

The approved C-series structure is C1 design/contracts → C2 direct exact-term count/Top-K → C3 safe deferred scoring → C4 integrated warm qualification. The maintainer chose to write C1's design directly rather than ask a coding agent to implement a docs-only plan. C2/C3 production changes, their executable tests and their detailed plans are explicitly separate. Therefore no test suite, Clippy, profiler, timing campaign, adapter build, RustFS bootstrap or CI workflow is *needed to substantiate this C1 documentation change*. Ordinary PR CI, if triggered by repository policy, is not claimed as a C1 runtime qualification.

## 2. Proven source anchors on the merged A+B baseline

| Accepted source | Relevant contract / observed operation | C1 implication |
| --- | --- | --- |
| `src/search/unified.rs::search_impl` | Query → sort → K → projection validation, before cursor/compile/segment traversal | No new physical routing before existing validation |
| `src/search/unified.rs::execute_unified` | Cursor binding/fingerprint checked before compilation/readers; calls `collect_mixed` then authoritative projection, cursor and response handoff | Keep public response path and cursor/PIT identity |
| `src/search/unified_plan.rs::compile` | Interned typed/lexical leaves, original Boolean tree, positive lexical set, `scoring_field_ids` and compiled codec | No second compiler; eligibility over compiled plan |
| `src/search/unified.rs::single_term_postings_eligible` | Root `Lexical(0)` + one `Term` leaf/one analyzed term, no typed/aggregate/cursor, only positive leaf | Reuse as a necessary eligibility condition |
| `src/search/unified.rs::{keyword_sort_late_eligible,keyword_ordinal_eligible}` | Standalone request; one single-valued columnar Keyword; no multi selector, JSON/geo or cursor | C2 strict rank-sort eligibility must not widen this |
| `src/search/unified.rs::collect_mixed` | Guarded readers, effective-live, expansion/statistics; optional B1 ordinal map; per-segment B2/B3 bind; after `execute::evaluate_lexical_with`, a loop over all scored entries admits into global K+1 heap | This M-sized scored return and second processing loop are the live C2 consolidation opportunity |
| `src/search/execute.rs::build_leaf_data` | Validated ascending term postings `Vec<(u64,u64)>`; charged `freq`, doc-id bounds and live-mask filter | C2 may retain this one posting vector; no silent corruption skip |
| `src/search/execute.rs::evaluate_lexical_with` | Strict-eligible postings path already removes redundant binary-search membership, moves/copies accepted sole postings based on callback result, models matched-set/scored-map ledger, returns `Vec<(doc_id,f64)>` | Do not describe old `BTreeSet → BTreeMap` as the current strict path. C2 must reduce the *remaining* scored-vector/ownership materialization |
| `src/search/execute.rs::{score_single_term_candidates,SegmentCandidateLedger,CandidateBudget}` | Prepared single-term eager scoring, logical temporary reservations, a single segment/global budget and explicit release | Preserve bit equality, modeled budgets, failure unwind |
| `src/search/score.rs::{compute_stats,FieldStats::bm25_score}` | Request-local live DF/norms/IDF; typed failures for invalid frequency, missing prepared state and non-finite score | C3 requires a score-safety certificate; no assumption that all BM25 calls are infallible |
| `src/index/{snapshot.rs,keyword_ordinals.rs}`; `src/segment/{reader.rs,column.rs}` | Verified immutable reader state, B1 snapshot-local ordinal map and B3 runtime-only key hash | Reuse existing lifetime and metadata accounts; no persisted rank/hash |
| `src/search/unified.rs::select_keys` + `src/search/execute.rs::visit_lexical_membership_with` | Complete membership for atomic query mutations, not a Top-K response | Explicitly exclude from C2/C3 dispatch |
| `benchmarks/pr15d/adapters/quervant/src/main.rs` | The accepted BM-10 adapter issues standalone strict `Term` queries sorted by `doc_id ASC`, K10/K100, complete count/ordered keys and projected `doc_id` | C2 narrow path covers the qualified B4 16-lane workload without adapter changes |

All references above are to `crates/quervant-core/` unless otherwise stated. The relevant B4 result is `benchmarks/studies/perf-06/warm/results/quervant-perf06b4-paired-warm-2026-11-25-001.json`; it compares pre-B1 A to cumulative B1+B2+B3 B. Those gains are **not** a measurement of C.

### Current strict-term ownership trace

~~~text
UnifiedSearcher::execute_unified
  -> collect_mixed: guarded readers / live masks / expansion / compute_stats
    -> B1 optional ordinal preparation (request scope)
    -> execute::evaluate_lexical_with
       -> build_leaf_data: one decoded full-M posting Vec<(doc_id,freq)>
       -> strict eligibility: logical N examination, one callback per posting
       -> StrictTermMatchSelection: move the sole posting Vec when no rejection
       -> logical matched-set admission
       -> score_single_term_candidates: eager M scores, Vec<(doc_id,f64)>
       -> release segment scratch/ledger reservations
    -> for every (doc_id, score): key/ordinal/duplicate checks, K+1 heap
  -> next_cursor / project_selected_hits / UnifiedResponse
~~~

The older diagnosis `BTreeSet → BTreeMap → Vec` applies to earlier generic source and must not be presented as the exact current strict branch. C2 is not authorized to reintroduce old repeated membership checks, full-M scored maps, or additional copied postings.

## 3. Historical rejected paths — required negative evidence

| Study | Decision and observation | Why it is not adopted unchanged |
| --- | --- | --- |
| [PR 15H-A](../pr-15h-a/performance-qualification.md) | `PERFORMANCE_REJECTED`: common high-hit targets improved, but 10K rare, 100K rare and 100K absent were slower in all paired blocks | A generic replacement with linear staging worsened low-hit queries; low-hit neutrality must be tested |
| [PR 15H-A2](../pr-15h-a2/source-disposition.md) | `PERFORMANCE_REJECTED_SAFE_ROLLBACK` of transplanted H-A helper and dispatch | Refactoring the dispatch alone is not evidence of a performance win |
| [PR 15I-C](../pr-15i-c/closeout.md), [performance decision](../pr-15i-c/performance-decision.md) | Rejected: four absent/rare unbatched lanes ~1.26–1.72× slower; final generic-boundary diagnostic ratios 1.36–1.77×, even when physical collector disabled. Common-lane experimental improvements did not qualify. | Code layout/inlining can regress generic source independently of new operator execution; avoid new per-doc mode branches and require low-hit guardrails |
| [PR 15I-C prior operator](../pr-15i-c/physical-execution-design.md) | `for_each_exact_term_score_with` reused posting decode, did virtual M matched/scored charges and eagerly scored every posting; removed from production after rejection | Do not copy old operator into C2 or claim it is current. Reuse its ledger-precedence lessons with fresh source-specific review |
| [PERF-05 accepted work](../perf-05/PERF05A_PIPELINE_COMPARISON.md) | Subsequent accepted B1–B5 eliminated repeated membership and improved strict term posting ownership; current `evaluate_lexical_with` reflects these changes | New design must target work still present **after** PERF-05 |
| [PERF-06 B4](../perf-06-b/PERF06B4_EXECUTION_REPORT.md) | Paired cumulative B1+B2+B3 qualified, four primary targets and twelve guards met | This is C's **baseline**, not a source of incremental C gain or a guarantee that C will improve it |

Prior rejection records remain immutable; no old failed experiment is reopened, reclassified or repaired by C1.

## 4. Frozen C1 decisions

| ID | Decision | Consequence / review |
| --- | --- | --- |
| C1-D01 | Doc-only C1, no production change, test or benchmark run | Independent reviewer approves architecture text, not runtime |
| C1-D02 | Only `LegacyUnified` and `StrictTermOrdinalTopK` physical families | No generic cost-based planner in C |
| C1-D03 | Compiled exact root term + eligible single Keyword rank sort + standalone/no cursor/aggregate/batch | Typed, Boolean, phrase, multterm, relevance sort, JSON, geo, aggregation and cursor remain Legacy |
| C1-D04 | Request-local B1 ordinal `Ready` required; optional absence before first candidate is Legacy | Corruption/poison/cancellation never fallback |
| C1-D05 | Verified M > K+1 is structural utility gate | Absent/rare and no-loser cases preserve legacy semantics and hot path |
| C1-D06 | Dispatch once outside hot loop; isolated legacy and fast call paths | Must confront PR 15I-C generic-codegen regression with C4 low-hit evidence |
| C1-D07 | C2 decodes and validates all postings, preserves N work, computes exact M, and keeps eager scores | No early stop, count shortcut or C3 behavior in C2 |
| C1-D08 | C2 may retain sole postings Vec and compact scores, but not another full-M scored-pair Vec or full-M tree | Concrete remaining intermediate eliminated |
| C1-D09 | Existing logical candidate/heap/memory charge and score/error order must be preserved | C2 requires source-specific ledger-state design, not an unaccounted memory optimization |
| C1-D10 | C3 winner-only scoring requires an explicit mathematical certificate and fallback before candidate admission | Skipping loser BM25 on sort independence alone is forbidden |
| C1-D11 | Source `select_keys` / batch / cursor / PIT output contracts remain unchanged | No shared mutation/top-K dispatch |
| C1-D12 | C4 separately qualifies **incremental C over merged B4**, not the original pre-B1 A | One approved warm study after C2/C3 acceptance and independent review |

**Contract tension explicitly preserved:** Making a full-M logical ledger reservation while building only bounded physical output can expose differences in peak simultaneous segment/global charges. Neither lowering the modeled cap nor introducing stricter errors is preauthorized. C2's detailed plan must derive the exact timeline and demonstrate threshold parity, otherwise it must STOP for a maintainer decision. Likewise, score error precedence across multi-fault fixtures is a correctness requirement, not something this documentation claims has already been solved by code.

## 5. Acceptance traceability — to be implemented in later PRs

**C1 documentation acceptance:** A+B source inspected; physical eligible/ineligible matrix fully defined; error/budget/count/score/cursor/fallback and ownership contracts explicit; prior rejections preserved; roadmap/register references updated; no changes to `crates/`, `Cargo.*`, `benchmarks/` or `.github/`; no test run claimed.

**C2 requires** a new detailed PR execution plan, independent review, unit/property tests and public-path integration proving full exact hit counts at K and K+1 boundaries; no re-lookup or redundant M scored-pair vector; unchanged explicit and relevance ordering on their respective paths; exact float bits; corrupt selected/unselected records; masked tombstones, PIT and cursor; duplicate rejection before numeric loser discard; budget and cancellation one-over; and low-hit generic branch isolation. The implementation must not run a performance campaign.

**C3 requires** another source-specific plan with the BM25 certificate proof, invalid score on losing documents, safe eager fallback, materialization/score bit parity and zero partial results. If mathematical error suppression cannot be excluded, C3 must restrict deferral or stop for review; C2 eager behavior remains acceptable.

**C4 requires** merged C2/C3 source identity, final correctness and resource integration, one separately approved warm acquisition, exact A+B baseline, immutable raw samples and primary/absent/rare guards. Adoption is maintainer-owned even if targets pass.

## 6. Review boundaries and follow-on ownership

C1 **does not** promise a performance gain or claim that the C2 or C3 physical algorithms already exist. This documentation is the architectural authority only after independent maintainer acceptance and merge. A coding agent starting C2/C3 must not substitute an unreviewed design, invent a threshold, add new public APIs or change index bytes because the C1 contract is inconvenient.

If a later source fact contradicts C1, report the exact symbol, counterexample, and smallest required decision. Amend the contract in a reviewed documentation change before implementing the affected stage. The historical 15I-C result cannot be used to authorize a new profiler, a rewritten generic boundary, a revised low-hit guard, or an extra benchmark campaign.

**C1 PR handoff:** draft documentation PR, base `main@8c9f51f311afa5b327f70432e32c0f6f5c205eab`, G10 independent acceptance and merge open. C2 starts only from the accepted, merged contract.
