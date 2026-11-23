# PERF-05-A — Physical execution source audit and evidence reconciliation

**Milestone:** `v0.1-perf` · **Series:** PERF-05 (single branch and PR through any later, separately authorized PERF-05-B/C/D stages).  
**Evidence revision:** `main@9775bfca4c58a27e65ca28c1d705efad00a65ec8` (includes merged PERF-02-B PR #116).  
**Investigation disposition:** **`PERF05A_SOURCE_AUDIT_COMPLETE_NO_IMPLEMENTATION_CANDIDATE`**. No new design, measurement, or implementation is authorized by this document.  
**Evidence class:** source inspection + cited historical experiments, **not new profiling, timing, or A/B qualification**.

## 1. Executive answer

The relevant production path **does** retain complete matched/scored intermediate collections for the BM-10 exact-term workload, even though only K winners survive. For eligible single-term requests it already enumerates postings directly, skipping a full document-predicate scan. For each matching document it still retains a decoded posting, adds the physical doc ID to a `BTreeSet`, builds a `BTreeMap<doc_id, score>`, converts that map to a vector, resolves the logical key, and evaluates Top-K admission.

**This structural redundancy is not a demonstrated material or removable latency bottleneck.** Earlier attribution assigned only **0.230869 ms (1.23%)** at 100K medium/K100 and **0.987877 ms (2.21%)** at 100K common/K100 to the separately isolated intermediate matched/scored region, on an **older revision and methodology**. These are not upper bounds for *all* postings or scoring work and cannot be combined with the latest PERF-02-B baseline as a qualified speedup forecast. Separately, PR 15I-D2-A measured scoring cost as low priority; PR 15G-C, PR 15H-A/A2 and PR 15I-C rejected related physical-execution approaches on high-hit performance and/or sparse guards.

**A decision now:** do **not** implement another streaming, vector, heap, late-scoring or physical-executor variant based only on source structure. The most defensible unresolved cost question is whether **building and retaining full decoded per-leaf postings** (`build_leaf_data`), as distinct from the already isolated matched/scored region, accounts for material *avoidable* end-to-end warm time on today's baseline. That subcost is not independently qualified in this audit. Even a positive cost finding would **not** permit repeating the retired physical executor without a materially new, separately approved safety/design argument.

**PERF-05-B is conditional and NOT automatically authorized.** See §§7–10 for the concrete decision rule. If the preconditions fail, close the physical-execution investigation and move to the short PERF-04 audit or separate ordinal-sort feasibility rather than keep tuning.

## 2. Scope, source authority and non-goals

### Inspected current code (production, not a speculative architecture)

| Ref | Path / symbol | What the code actually does |
| --- | --- | --- |
| S01 | [`search/unified.rs:120-142`](../../../crates/quervant-core/src/search/unified.rs) `single_term_postings_eligible` | Restricts postings candidate enumeration to exact one-term root, one positive lexical leaf, no typed leaves/aggregation/cursor |
| S02 | [`search/unified.rs:618-1013`](../../../crates/quervant-core/src/search/unified.rs) `collect_mixed` | Opens readers, expansion/stats, common meter/budget, evaluates lexical candidates, counts matches, obtains keys and retains bounded Top-K |
| S03 | [`search/execute.rs:1256-1370`](../../../crates/quervant-core/src/search/execute.rs) `build_leaf_data` | Decodes entire effective-live term postings into sorted `Vec<(doc_id, freq)>` with work/entry/byte charges; validates posting order via decoder |
| S04 | [`search/execute.rs:896-969`](../../../crates/quervant-core/src/search/execute.rs) `LeafData::matches` | Uses binary search over those sorted vectors for per-document term membership |
| S05 | [`search/execute.rs:1936-2066`](../../../crates/quervant-core/src/search/execute.rs) `evaluate_lexical_with` | Posts-driven candidate loop or fallback live scan → `BTreeSet<doc_id>` → `score_segment` → scored vector, with budget releases |
| S06 | [`search/execute.rs:1673-1773`](../../../crates/quervant-core/src/search/execute.rs) `score_segment` | Allocates a scored `BTreeMap` over matched IDs and accumulates BM25, including duplicate-term ownership rules |
| S07 | [`search/unified.rs:852-1006`](../../../crates/quervant-core/src/search/unified.rs) | Converts every scored candidate to exact `DocumentKey`, increases exact `total_hits`, uses borrowed Keyword comparison then bounded heap admission |
| S08 | [`search/execute.rs:1831-1935`](../../../crates/quervant-core/src/search/execute.rs) `visit_lexical_membership_with` | **Existing, different** unscored membership visitor for complete-key selection, not a drop-in scored search replacement |
| S09 | [`search/unified.rs:1853-1888`](../../../crates/quervant-core/src/search/unified.rs) `heap_admit_candidate` | Preflights budget, admits and evicts entries atomically; heap-algorithm optimization belongs to deferred PERF-03 |
| S10 | [BM-10 Quervant adapter](../../../benchmarks/pr15d/adapters/quervant/src/main.rs) `search` | One public `UnifiedSearcher::search` with exact keyword term, `doc_id ASC`, K10/K100, projected `doc_id`; times query and output materialization |

**Important sibling-path distinction:** `search/execute.rs::execute_search` is a separate public/legacy scoring path with its own per-segment/global structures; **do not attribute its `global: BTreeMap<DocumentKey, f64>` to the BM-10 `UnifiedSearcher` call**. The present benchmark follows `collect_mixed` → `evaluate_lexical_with` above.

**Out of scope for PERF-05-A:** source edits to Rust, format/codec, benchmark code or configurations, extra instrumentation, compilation/testing, new profiler captures, external CI additions, new performance claims, heap selection changes (PERF-03), cache/offset changes (PERF-04), sortable ordinals, block skip lists, compression/SIMD, mmap/RustFS and WAND. Reading historical results does not certify them on current `main`.

## 3. Exact benchmark path and retained work

The 100K workload is a single-segment exact Keyword query with expected `total_hits` of 12,500 for medium and 49,999 for common. Its K10/K100 results follow this sequence:

```text
UnifiedSearcher::search
  -> search_impl/execute_unified -> collect_mixed
      -> open verified readers + compute expansion/stats
      -> build_leaf_data
           decode all relevant effective-live postings into TermPostings Vec<(doc_id,freq)>
           scanned-posting work charge and corruption/cancellation checks
      -> evaluate_lexical_with
           eligible: iterate postings sorted by physical doc_id
                    (fallback: scan effective-live bitmap)
           evaluate_unified predicate for each candidate
           insert every true doc_id into matched BTreeSet
           reserve logical matched-set capacity
           score_segment: build scored BTreeMap; BM25 every matched doc
           convert map into Vec<(doc_id, f64)>; release temporary ledger reservations
      -> collect_mixed
           increment exact total_hits; decode/validate DocumentKey for every scored hit
           validate borrowed UTF-8 Keyword sort value
           duplicate prefilter/exact check; compare with retained worst
           only admit competitive candidate as owned tuple into bounded heap
      -> sorted selected hits -> projection/output
```

**Already done; do not duplicate:** source-level postings candidate enumeration for eligible single-term queries; prefilter P2 for K≥32 (PERF-01); borrowed `&str` sort view and late owned tuple for noncompetitive candidates (PR 15H-B); bounded heap retention; retained column geometry / validated STORED and DOC_KEYS offsets (PR 15G-A/B). `visit_lexical_membership_with` also exists, but omits scoring and has different stop/error/return contracts.

### 3.1 Logical cost model — not measured bytes or latency

| Object | Growth on one effective-live term stream | Logical model source | Required / removable? |
| --- | --- | --- | --- |
| `TermPostings.postings` | M decoded posting pairs | `TERM_POSTING_BYTES = 16` per retained live posting | Necessary for current membership + BM25 path; *alternative streaming lifetime unproven* |
| `matched: BTreeSet<u64>` | M matched doc IDs | `SET_BYTES_PER_ENTRY = 48` per entry | Intermediate representation, but full predicate/count and resource semantics remain |
| `scores: BTreeMap<u64,f64>` | M scored entries | `SCORED_MAP_BYTES_PER_ENTRY = 64` | Intermediate; score/error and budget parity must remain |
| `scored_vec` | M `(doc_id, score)` pairs | Not a separate retained ledger reservation; generated from `scores` | Copy/move and allocation opportunity, not an independently measured savings |
| Heap / owned sort tuples | Bound near K+1, not M | `heap_limit = K+1`; late materialization | Already bounded; PERF-03 / PERF-02 |
| `DocumentKey` and borrowed sort validation | M candidates | Exact logical keys / corrupt-unselected behavior | **Cannot** assume it is removable because only K winners are returned |

Under the simplified **one-term, all-M-matched, one-segment** shape, the three explicitly charged live structures amount to `M × (16 + 48 + 64) = 128M` modeled bytes, or 1,600,000 modeled bytes at M=12,500 and 6,399,872 modeled bytes at M=49,999. This is a **model of simultaneous logical reservations near scoring**, **not** measured resident memory, a claim about `Vec` allocations, or a bound on avoidable bytes. The transformed vector and heap have separate physical lifetimes. Multi-term and multi-segment cases require different accounting.

**Complexity:** decode postings O(M), populate matched BTreeSet O(M log M), build scored map O(M log M), score lookup/update O(M log M) for this broad shape, materialize ordered score vector O(M), then candidate validation/retention O(M) with bounded Top-K comparison. This is a descriptive model, not a prediction that a hypothetical stream is O(M) in practice or yields a material speedup.

### 3.2 Mandatory behavior constraining a rewrite

| Invariant | Source behavior that must survive | Failure if naïvely removed |
| --- | --- | --- |
| I01 complete count | `total_hits` increases for *every* matching candidate, including nonwinners | Early stop at K produces wrong count |
| I02 scores and error precedence | `score_segment` evaluates positive lexical scores; selected results retain `Some(score)` | Late scoring may skip errors/charges for nonwinners or change score order |
| I03 postings integrity | Strict posting order, in-range ID, effective-live and frequency checks, scanned work charge | Partial/unchecked iterator can silently bypass corrupt data or budgets |
| I04 memory/work accounting | `SegmentCandidateLedger`, shared `MixedWorkMeter`, `CandidateBudget` track **logical** peaks, changes and error boundaries | Removing a temporary container must not silently reduce formerly enforced logical admission |
| I05 cancellation | Work/read loops and per-candidate checks poll cancellation at defined boundaries | Reordering and early abort can change cancellation/error ordering |
| I06 exact sorting / tie rules | Keyword ascending with key tie-break; K+1 cursor handling and selected projection | Partial candidate enumeration can alter order or PIT/cursor correctness |
| I07 duplicate/corruption | Retained-key checks, full `DocumentKey` resolution and validated sort-value lookup per candidate | Suppressing nonwinner validation can hide malformed committed segments |
| I08 fallback semantics | Single-term eligibility excludes typed/aggregation/cursor/batch-adjacent shapes, other sorts and multi-leaf plans | Fast path accidentally changes general search semantics or resource limits |
| I09 low-hit neutrality | Empty/one-hit queries already have short critical paths | Added dispatcher/init/code-layout overhead can regress absent/rare queries |
| I10 no experimental override | Default K10 linear and K100 P2 prefilter | Performance results no longer reflect the accepted production baseline |

A new design would need both positive and adversarial tests for these invariants before an optimization candidate could be accepted; **the source audit does not discharge those tests**.

## 4. Historical evidence and disqualifications

| Record | Relevance | Historical decision; why it matters |
| --- | --- | --- |
| [D3-A-F2 five-run cost attribution](../pr-15i-d3a/fixup-f2-five-run-performance.md) | Matched/scored intermediate region measured **0.230869 ms / 1.23%** (100K medium/K100), **0.987877 ms / 2.21%** (100K common/K100). Its control materiality gate was 3 ms / 10%, not met | **Below gate** on older source; **not** total cost of decoded postings or entire scoring/candidate path |
| [PR 15I-D2-A](../pr-15i-d2a/execution-status.md) | Measured score accumulation ~0.66 ms (100K medium/K100) / ~2.63 ms (100K common/K100/K10); only common/K10 cleared both 2 ms and 8% gates in both campaigns | `D2A_SCORE_COST_LOW_PRIORITY`; late-score design not authorized; nonwinner error/budget parity unresolved |
| [PR 15F P0](../pr-15f/p0-analysis.md) | Common lanes had ~10–12% **inclusive** membership path, ~4–5% inclusive staging/BM25, and 84–85% unknown exclusive samples | Cannot sum inclusive path shares or convert them into removable end-to-end gain; old baseline |
| [PR 15G-C](../pr-15g-c/performance-qualification.md) | Streaming/collector variant on nine-lane matrix | Rejected: 100K common/K100 B/A 1.154 and common/K10 1.284; rare/absent guards slower |
| [PR 15G-D / 15G-E](../../PERF_OPTIMIZATION_PLAN.md) | Isolated streaming and persistent-offset variants | Rejected: D2 common/K10 inconclusive and 10K rare `A_FASTER`; E rare queries ~6–7× slower and high-hit regressions; restore previous production |
| [PR 15H-A / A2](../../PERF_OPTIMIZATION_PLAN.md) | Linear staging and cardinality-gated variant | Common-query gains but all low-hit guards regressed, even after 8192-posting cardinality gate; both rolled back |
| [PR 15H-A3](../../PERF_OPTIMIZATION_PLAN.md) | Sparse-regression isolation attempt | Same-source A/A instability blocked causal resolution; no license for instruction-order experiments |
| [PR 15I-C closeout](../pr-15i-c/closeout.md) | Specialized postings-driven physical executor | Retired/rejected; generic-boundary guards failed at 10K and 100K absent/rare, even when physical collector was runtime-disabled; no safe causal explanation |
| [PR 15H-B accepted code](../pr-15h-b/qualification.md) | Borrowed string view / late owned tuple | Already included on production path, **do not implement again** |
| [PERF-02-B report](../perf-02-b/PROFILE_REPORT.md) | Current warm-query context; 100K medium ~15.1 ms, common ~33.7 ms, K100. Only one sort-path CPU lane qualified (11.6%); three were attribution-blocked | No new source-bounded CPU attribution for physical matched/scored collections. PERF-02-B is `BLOCKED`, not proof of low sort cost |

**Across-revision warning:** Old D3/D2/15F numbers and current PERF-02-B measurements are **not a paired candidate A/B comparison**. Do not subtract them, rescale them to claim net savings, or treat old lower-time sections as exact current-head upper bounds. The valid use here is *qualitative screening and avoiding known failures*.

For orientation only, a 5% *screening heuristic* on current short warm medians corresponds to about **0.76 ms** (100K medium/K100) and **1.68 ms** (100K common/K100). Those values are not predeclared acceptance thresholds.

## 5. Evaluated hypotheses — no new implementation design selected

| ID | Opportunity / mechanism | Evidence | Novel versus previously rejected work? | Audit disposition |
| --- | --- | --- | --- | --- |
| H05-01 | Remove/reduce the matched `BTreeSet` → scored `BTreeMap` → `Vec` chain | It exists; older separately isolated portion 1.23% / 2.21% | **No distinct safe mechanism established**; directly overlaps streaming/linear-staging experiments | **DO NOT IMPLEMENT**; not shown material |
| H05-02 | Compute BM25 only for final winners | Scores do not determine explicit keyword sort, but positive lexical scores are returned; prior score-stage attribution low-priority | No safety-equivalent error/budget/cancellation design; previously explored | **DO NOT IMPLEMENT**; D2A negative |
| H05-03 | Eliminate full decoded `TermPostings` materialization in eligible term path | `build_leaf_data` holds M posting pairs; its exclusive avoidable CPU cost on today's baseline is **unmeasured** | Generic streaming/physical-executor patterns tried and rejected; no provably distinct zero-regression mechanism identified | **CONDITIONAL RESEARCH QUESTION ONLY**, not an optimization candidate |
| H05-04 | Adjust `BinaryHeap`, duplicate scans, borrowed `doc_id` or string comparison | PERF-01 / PR 15H-B already handle major pieces; heap-child shares historically small, DOC_KEYS borrowing rejected | No | **OUT OF SCOPE** (PERF-03 / PERF-02) |
| H05-05 | New sorted ordinals / block skips / postings format / mmap or remote I/O | Separate, potentially material architecture directions | Would require format, validation, portability and compatibility design | **FUTURE SEPARATE WORK**, not H05-03's implied solution |

**Rank:** H05-03 is the only residual *unmeasured* source question worth retaining as a **conditional check**, not a go-ahead to build a streaming executor. H05-01/H05-02 are screened out absent genuinely new evidence. There is **no approved `OPTIMIZE` candidate** in this audit.

## 6. Explicit non-repetition rule

A future PERF-05 design must provide a reviewed comparison against **every** relevant rejected trial:

1. Mechanism and source delta — what exactly differs from 15G-C/D, 15H-A/A2, and 15I-C (not just a renamed helper, revised cardinality constant or reorganized function boundaries)?
2. Low-hit neutrality — why it cannot cause the documented absent/rare regressions; a `#[inline(never)]`/compiler-instruction-order theory without evidence is **not** an approved design.
3. Contracts — why all I01–I10 are invariant-preserving, especially work/memory budgets and error precedence on losers.
4. Materiality — why it plausibly removes ≈5% or more of **unmodified production warm-query latency**, not local nanoseconds or historical best-case CPU percentages.
5. One-change isolation — one bounded alternative, separate source SHAs, independently compiled baseline/candidate, and predeclared warm A/B acceptance only **after** design/implementation approval.

If any element is missing: **STOP the proposed implementation**. Do not try another variant hoping for a better benchmark result.

## 7. Decision boundary for PERF-05-B (NOT authorized here)

A single **targeted** measurement may be proposed **only if all** are true:

| Gate | Required specific evidence | Current state |
| --- | --- | --- |
| B01 source question | Restrict to per-query `build_leaf_data` retained-postings cost on **eligible** exact-term 100K medium/common K10/K100, not a general engine profile | **IDENTIFIED** |
| B02 novel safe avenue | Describe a bounded future mechanism unlike retired 15G/15H/15I implementations and show how it preserves I01–I10 | **NOT ESTABLISHED** |
| B03 quantified screening hypothesis | Source plus prior evidence justify a credible ≈5% or greater end-to-end *removable* warm-query cost on at least primary workloads; no independent-run ratios | **NOT ESTABLISHED** |
| B04 frozen diagnostic | Predefine read-only, aggregate stage attribution; no per-candidate nanosecond probes, assembly, compiler flags, threshold modifications or repeated capture | **NOT DEFINED / NOT AUTHORIZED** |
| B05 approval | Human reviewer approves an explicit short measurement contract after checking B01–B04 | **NOT GIVEN** |

**PERF-05-A exit:** `PERF05A_SOURCE_AUDIT_COMPLETE_NO_IMPLEMENTATION_CANDIDATE`. **Do not automatically execute B, C or D**. If B02/B03 cannot be satisfied by a materially new source design, record `PERF05_PHYSICAL_EXECUTION_NO_CURRENT_OPTIMIZATION` after reviewer disposition and move to PERF-04 rather than spending another campaign. Treat an evidence gap as `UNPROVEN`, not a positive potential benefit.

If B is separately approved, it is *one fixed, narrowly scoped measurement*, with at most one predeclared diagnostic follow-up, no new generic benchmarking framework, full correctness oracle and no result promoted to an A/B candidate gain. Any unusable profiler evidence yields `BLOCKED`; it does not authorize an instruction-level detour.

## 8. Same-PR program for remaining PERF-05 stages

**One shared branch/PR:** `dev/perf05-physical-execution-series` is the sole integration branch for PERF-05-A/B/C/D. Do not create a separate PR for B/C/D. Each stage is separately permissioned by the maintainer, committed to this branch, and given a distinct dated report under `docs/pr-artifacts/perf-05/`. A PR being open or this program being documented is **not** permission to run the next stage.

| Stage | Trigger | Permitted deliverable | Must not do |
| --- | --- | --- | --- |
| **05-A — this document** | User authorized source audit | Code/evidence map, negative-experiment reconciliation, gated next decision | Modify production, profile or qualify performance |
| **05-B — conditional** | Gates B01–B05 approved | One finite aggregate measurement of one named physical stage, plus immutable diagnostic evidence; materiality disposition | General profiling, repeat/retune, disassemble or infer unobserved savings |
| **05-C — conditional** | Accepted material opportunity **and** separate design authorization | Detailed self-contained implementation/correctness plan following `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; exact eligibility/fallback, I01–I10 test matrix, traceability and STOP rules | Start implementation on a hypothesis |
| **05-D — conditional** | Human-approved 05-C design | Implement exactly one candidate; run QA, correctness, and **qualified warm A/B** with immutable new config under BM-10-based harness, then accept/reject | Modify baseline gates, silently exempt sparse regressions, relaunch another variant after failure |

**05-D acceptance boundary if reached:** exact independent oracle, unchanged result scores/order/`total_hits`, mutation/PIT/cursor, selected/unselected corruption and error precedence, budget/overflow/cancellation parity, lower-hit regression guards, stable/MSRV Rust QA, ≥85% workspace production line coverage, relevant local + RustFS integration, exact-head CI, versioned A/B warm statistical controls. A future design must predeclare values; this source audit does **not** freeze or invent a candidate benchmark.

## 9. Test and evidence status for this PR commit

| Evidence | Status | Why |
| --- | --- | --- |
| Source inspection | **DONE** at recorded `main` SHA | S01–S10 reviewed |
| Historical reports | **REUSED AS BACKGROUND**, not current qualification | Listed in §4 with limitations |
| New benchmark measurements / profiling | **NOT RUN** | Explicitly excluded |
| Code compilation, Rust/Python tests, workspace coverage | **NOT RUN — NOT APPLICABLE TO DOCUMENTATION-ONLY SOURCE AUDIT** | No executable code changes |
| Production API / codec / adapter / benchmark configuration | **UNCHANGED** | Documentation-only stage |
| PERF-05-B/C/D acceptance | **NOT STARTED / NOT AUTHORIZED** | B01–B05 unsatisfied |
| Main/roadmap closeout | **PENDING REVIEW** | This dossier is source audit, not a merged optimization or a qualified gain |

## 10. Reviewer decision

- Confirm S01–S10 accurately describe **the active BM-10 UnifiedSearcher path**, not unrelated `execute_search`.
- Confirm rejected trials (15G-C/D, 15H-A/A2, 15I-C), low-priority scoring (D2A), and D3 intermediate costs are not erased or promoted to current-head gains.
- Decide whether B02–B05 can ever be met with a **new** source design before commissioning more profiling. If not, **do not proceed to PERF-05-B**; close the physical-execution opportunity without implementation.
- Do not select a Top-K heap or sorted-ordinal implementation within PERF-05-A.
- Keep the single PERF-05 PR open for reviewer decision and any explicitly authorized later stage; do not merge this source audit as completion of the entire series.

**Bottom line:** **Existing multi-container work is real, but a material, safe, new change is not established.** PERF-05-A delivers an evidence-based **HOLD**, not an optimizer proposal. Protect the low-hit guardrails and stop before another trial-and-error loop.
