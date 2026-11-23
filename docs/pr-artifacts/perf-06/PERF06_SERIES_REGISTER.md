# PERF-06 — Optimization Series Register

**Status:** SERIES PLANNING — SCOPE, SEQUENCE, AND DESIGNS NOT YET APPROVED  
**Milestone:** `v0.1-perf`  
**Repository:** `yduchesne/quervant`  
**Working branch:** `dev/perf06-optimization-series`  
**Pull request:** New PERF-06 series PR, initially **draft**  
**Starting baseline:** `main@a7011fbe45c3715333b2de8864a49aedba240417` (includes merged PERF-05, PR #117)  

## 1. Purpose

Establish a dedicated, reviewable branch and pull request for the **next** Quervant search-engine optimization series, PERF-06. The PERF-06 subseries and architectural choices will be agreed **before** any optimization is implemented or assigned to an agent.

This file is a **planning scaffold**, not a detailed PR plan, ordered optimization roadmap, approval of any particular algorithm, authorization for real benchmark acquisition, or acceptance claim. No implementation or experimental decision follows from creating this PR.

## 2. Accepted baseline and constraints

- PERF-05 (PR #117) was merged into `main` before this branch was created. PERF-05-B1 through B5 are part of the starting engine baseline; the PERF-05-C results and their qualifications remain unchanged.
- The user has confirmed that Quervant has **no customers** and is **not in production**. Major internal refactors, new versioned on-disk layouts, and reindexing are therefore legitimate design options; customer migration or backward-compatibility commitments must not be invented.
- That freedom does **not** itself authorize weakening query correctness, exact hit counts, sort order/ties, returned scores where required, snapshot/PIT consistency, data integrity, corruption detection, resource/cancellation guarantees, or security boundaries. Any intentional contract changes require a separately explicit decision.
- Existing failed/rejected optimization experiments are evidence to consider when designing a materially different approach; they are not automatic grounds to disallow a redesign.
- Warm-query performance is the criterion for query optimization decisions. Benchmark design, source identities, acceptance targets, negative-case guardrails, and any use of historical results must be agreed for each stage before acquisition. No benchmark or profiler run is authorized by this scaffold.

## 3. Open design decisions — to be agreed with the maintainer

All of the following are **UNDECIDED**:

| Decision | Status |
| --- | --- |
| Exact optimization topics and their ordering | NOT AGREED |
| PERF-06 substage identifiers, dependencies, and PR boundaries | NOT AGREED |
| Architecture, data representations, API and on-disk versioning for each stage | NOT AGREED |
| Which semantics are invariant versus deliberately revised | NOT AGREED |
| Required test matrix, benchmarks, and measurement protocol | NOT AGREED |
| Per-stage success, failure, rollback, and stop criteria | NOT AGREED |
| Whether to adopt a new format, remove historical format support, or reindex | NOT AGREED |

Prior discussions identified possible opportunities in postings representation/decoding, BM25 scoring, exact counting and top-K, keyword sort ordinals, document-key access, and reader state. **These are discussion inputs only**: this register establishes **no priority, implementation permission, or architectural preference** among them.

## 4. Future authorization and execution protocol

1. **Agree on the PERF-06 series first.** Document a reviewed ordering and the rationale, with dependencies and explicit stage goals. This scaffold must not be interpreted as that agreement.
2. **Design each stage before coding.** Author a separate prescriptive plan following at least `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, including frozen source anchors, exact edits, tests, acceptance criteria, and a fail-closed exception decision matrix. Coding agents must not improvise architecture.
3. **Implement only approved stages.** Work under this PR unless a later maintainer decision explicitly changes the topology. Maintain an independent source review between stages and record evidence without rewriting earlier outcomes.
4. **Measure only under a separately approved benchmark contract.** Do not automatically rerun baseline engines, cross-engine campaigns, RustFS, or profiling merely because they appeared in earlier efforts. Use the minimum actual work needed for the approved question.
5. **Do not merge merely because this PR exists.** Merge only after implementation and the agreed final review/qualification gates.

## 5. Deliberate nonchanges in the opening commit

- **Do not edit** `docs/PERF_OPTIMIZATION_ROADMAP.md` or any other roadmap yet.
- Do not modify Rust or Python production/benchmark code, schemas, configurations, retained results, CI workflows, or prior PERF-05 records.
- Do not create substage plans or claim any optimization as selected or completed.
- The opening PR changes **this file only**. Its purpose is to reserve the PERF-06 workspace for subsequent decisions.

**Next:** Maintainer discussion and agreement on the PERF-06 stage map.  
