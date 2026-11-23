# PERF-06-A — Scoring and Postings Efficiency Series

**Status:** SERIES PR OPENING — NO STAGE IMPLEMENTATION AUTHORIZED  
**Milestone:** `v0.1-perf`  
**Repository:** `yduchesne/quervant`  
**Series branch:** `dev/perf06-a-scoring-postings-series`  
**Opening baseline:** `main@2a74017958c8ac61948f931e8745bf8134827025` (includes merged PERF-05 PR #117 and PERF-06 planning PR #118)  
**Authority:** [PERF optimization roadmap](../../PERF_OPTIMIZATION_ROADMAP.md#perf-06-a--scoring-and-postings-efficiency) · [PERF-06 planning register](../perf-06/PERF06_SERIES_REGISTER.md)  
**Detailed-plan minimum:** [`docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`](../../DETAILED_PR_PLAN_AUTHORING_GUIDE.md)

## 1. Purpose and PR topology

Establish the **PERF-06-A** workspace and its agreed high-level scope. The engineering objective is to remove per-match scoring/decoding overhead and provide an efficient immutable postings representation for later PERF-06-B (fast fields / document identity) and PERF-06-C (integrated executor) work.

This draft **series PR is a documentation-only charter**. It is **not A1**, not a substitute for the four agreed independently reviewable PRs, and not authorization to implement a proposed algorithm or run performance benchmarks.

**Agreed topology:** PERF-06-A1, A2, A3 and A4 are **four separate implementation/qualification PRs**, which do **not exist yet**. Each is independently reviewed and accepted against the appropriate latest merged dependency, with no unreviewed implementation code transferred across PRs. This charter can be reviewed/merged separately; it is not the future A1–A4 comparison base or an accumulation branch for their source changes.

## 2. Planned PR sequence (already approved at the series-planning level)

| Planned PR | Scope and deliverable | Dependencies / constraints |
| --- | --- | --- |
| **PERF-06-A1 — Precomputed BM25 term weights** | Move query-constant term weight work (notably IDF) outside the per-hit scoring loop; provide deterministic, source-compatible score/context tests. | First. No postings format change. Detailed design must reconcile floating-point evaluation, exact reported-score contract, invalid-score/error behavior and safe fallback. |
| **PERF-06-A2 — Document/frequency-only postings API** | Add a reader API for clients needing only document IDs and frequencies, avoiding unnecessary positional occurrence objects and copies where semantics permit. | Requires accepted A1. Retain positional consumers, mandated validation/corruption behavior, work and memory charging and cancellation. |
| **PERF-06-A3 — Separated, versioned postings layout** | Design and implement independently accessible doc-ID, frequency and positional streams, with agreed block/skip metadata, index writer and reader integration. | Requires accepted A2. Major format change and reindexing are permitted, but must define codec versioning, integrity validation, phrase compatibility, resource limits and reader consistency before coding. |
| **PERF-06-A4 — Consolidated qualification** | Independently verify A1–A3 and run one **separately authorized** warm query performance campaign for the cumulative accepted A implementation. Record all results and the subseries disposition. | Requires A1–A3 accepted. No last-minute algorithm redesign or unapproved benchmark-method changes. Successful A is the baseline for PERF-06-B1. |

**Order:** A1 → A2 → A3 → A4. Altering these scopes, dependencies or PR boundaries requires an explicit maintainer decision and roadmap update.

## 3. Retained PERF-05 execution model

1. **Source review and prescriptive design first.** Each numbered implementation PR requires its own source-anchored detailed plan following `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, with exact file allowlists, contracts, proposed APIs/algorithms, ownership and failure precedence, tests and a bounded condition/decision/STOP matrix. Do not delegate design decisions to the coding agent.
2. **Correctness-first intermediate PRs.** A1–A3 get targeted red/green tests, deterministic synthetic and adverse inputs, relevant codec/reader integration tests, applicable CI and independent review. Do **not** perform routine real benchmarking, profiling or cross-engine acquisition within those PRs.
3. **One warm qualification at A4.** Use immutable configurations/results, pinned code revisions, representative 10K/100K absent/rare/medium/common, K10/K100 target/guard lanes when applicable, independent oracles, readiness and stability controls. The exact performance criteria and experiment contract are **not frozen by this charter**.
4. **Historical A reuse where genuinely comparable.** Prefer PERF-05's qualified historical A + newly measured B-only/B/B approach if source identity, compiled options, corpus, query semantics, index format and timed operation remain comparable. Report cross-run ratios as **descriptive/unpaired**; no fabricated paired interval or causal source-only claim. A3's format changes may invalidate the old reference—then **STOP** and obtain approval for an appropriate new baseline/campaign instead of assuming comparability.
5. **No unnecessary work.** Do not start RustFS, run Tantivy/Lucene, rebuild historical A, run `perf`/Criterion, or execute process-cold benchmarks unless a specific authorized correctness or performance question requires it. Real storage/codec acceptance tests *can* be relevant to A3 and must be scoped in A3's detailed plan.
6. **Fail closed and retain negative outcomes.** No automatic rerun of an unstable campaign, pruning unfavorable blocks, threshold relaxation, swapping hosts, overwriting results or converting an incomplete run into a favorable claim. Every executed attempt remains part of the review record.
7. **Architectural freedom, preserved invariants.** Quervant has no production customers; deep refactoring, redesigned on-disk formats and reindexing are acceptable. Maintain or expressly amend query correctness, exact counts/order, mandatory returned scores, valid error/corruption detection, duplicate identity, snapshot/PIT/cursor, resource/cancellation and security contracts. Prior rejected 15G/15H/15I experiments are mandatory design evidence, not off-the-shelf implementation recipes.

## 4. Opening PR scope and next gate

**Opening change: this file only.** Do not alter `docs/PERF_OPTIMIZATION_ROADMAP.md` (already merged under PR #118), production/benchmark code, schemas, tests, CI, benchmark configurations/results, or historical PERF-05 artifacts.

**Next decision:** approve the source-specific **PERF-06-A1 detailed implementation plan** before creating and executing its separate PR. This charter does not itself authorize A1 code changes or a benchmark acquisition.

**Series disposition at opening:** `PERF06_A_SERIES_REGISTERED_NO_IMPLEMENTATION`.
