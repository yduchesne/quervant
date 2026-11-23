# PERF-05-B — Coding-agent implementation plan register

> **Status:** Proposed decomposition, **not executable agent instructions and not authorization to change production source**. Detailed plans for B1, B2, etc. will be authored independently, to `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, immediately before each agent handoff, using the then-current branch source.
>
> **Repository / sole PR:** `yduchesne/quervant`, `dev/perf05-physical-execution-series`, [PR #117](https://github.com/yduchesne/quervant/pull/117). All PERF-05-B subplans commit **sequentially to this same branch/PR**. Do not open a PR per subplan.
>
> **Stages:** PERF-05-A = source analysis (done); **PERF-05-B1…Bn = all optimization implementation** (including what was formerly PERF-05-C); **PERF-05-C = one consolidated final correctness/QA, warm A/B benchmarking **and CPU-profiling campaign** (formerly PERF-05-D). There is **no PERF-05-D** and **no benchmark/profiler capture in any B substep**.

## 1. Design target and boundaries

The accepted `UnifiedSearcher` exact-term high-hit path performs redundant membership searches and creates a full-M decoded-postings `Vec`, matched `BTreeSet`, scored `BTreeMap`, scored-result `Vec` and bounded Top-K state. The [source and Tantivy comparison](PERF05A_PIPELINE_COMPARISON.md) identifies source-proven repeated or higher-complexity work and distinguishes it from Tantivy 0.25.0's no-score, ordinal FAST-field Top-N collector. **Objective:** share one verified representation between more execution stages and eliminate unnecessary traversals and allocations **without reducing Quervant's correctness, score, error or budget obligations**.

**Global engineering rule:** Do not run benchmarks to decide whether source-proven waste should be corrected. At each B stage, prove semantics and execute *focused correctness tests*. **B1–B5 run no real performance benchmarks, no `perf record`, no profiler dry-runs and no CPU attribution experiments.** After a coherent B implementation, PERF-05-C runs complete quality gates, **one controlled final warm A/B acquisition and a separate diagnostic CPU-profile capture within that same C campaign**. Static complexity improvement alone does not prove a latency improvement; adoption is performance-gated. The profile is explanatory evidence and must never contaminate the uninstrumented A/B latency estimate.

### One change per coding-agent subplan

Each detailed subplan must (a) name one dominant code path/representation, (b) specify exact files, target functions, data ownership, budget/charge/poll order and error precedence, (c) prescribe exact implementation steps and test cases, (d) require the agent to fetch and fast-forward the existing branch before starting, (e) contain a bounded **condition → action → STOP** decision matrix, (f) explicitly forbid architectural improvisation, test-gate relaxation, production feature flags and changes outside the allowlist, and (g) require one named reviewable commit/report on PR #117 before the next subplan begins.

The author's job is to **finish the design** in the detailed plan. A coding agent does *not* select a different collection representation, substitute a new dispatcher, redesign scoring, infer acceptable behavior from performance, or create a new PR.

## 2. Recommended sequence (B1–B5)

| Subplan | One dominant architectural change | Explicitly in scope | Explicitly out of scope | Dependency / gate |
| --- | --- | --- | --- | --- |
| **PERF-05-B1** | Eliminate redundant positive-term membership re-lookup | On `evaluate_lexical_with`'s already validated **strict single-positive-term postings** path, reuse the match certainty of the posting being visited rather than invoking `LeafData::matches` binary search on the *same* list. Preserve callback side effects, work/poll sequence and source eligibility; deterministic adverse-path tests | New physical executor, other Boolean/typed/phrase plans, scoring changes, heap, duplicate detection, postings codec | First. No performance test prerequisite |
| **PERF-05-B2** | Reuse effective-live metadata across adjacent stages | One query-local, snapshot-bound verified `live_count`/`all_live` summary reused by `compute_stats` and eligible examination accounting; avoid redundant per-document bitmap reads **only where** logical work charges and cancellation/error boundaries can be preserved. No shared cross-query cache | Altering `max_total_work_units`, reducing cancellation checks, changing missing/deleted-document semantics, storage format | Independent of B1; do after B1. STOP if required error/poll parity cannot be proven |
| **PERF-05-B3** | Replace the redundant matched-ID **tree** with a compact ordered sequence | `evaluate_lexical_with`: for its ascending, one-visit-per-doc traversal, represent matched doc IDs in an append-only ordered buffer; adapt the scorer's input **without changing the sibling `execute_search` contract or introducing a duplicate scorer**. Retain the same modeled matched-set admission limits and release semantics | Changing score computation, returning different scores, changing score map/output `Vec`, reordering matches, general operator dispatch | B1 and B2 complete. Detailed design must reconcile `score_segment`'s existing `BTreeSet` caller(s); STOP if parity design incomplete |
| **PERF-05-B4** | Reuse the ordered matched buffer as its own scored output | On the proven one-term eligible shape only, carry the already decoded term frequencies and compute exact existing BM25 values **in the ordered candidate buffer**, eliminating full-M scored `BTreeMap`, its tree lookups, extra postings pass and map→`Vec` conversion. Keep generic/multi-term/phrase `score_segment` unchanged. Preserve logical score-buffer resource admission and exact ordering/score/error sequencing | Disabling scores for losing candidates, late scoring, modifying BM25 or normalizing numbers differently, new Top-K operator, object-format changes | Requires B3; the author must provide a fully specified, fail-closed scoring/ownership/budget design before coding |
| **PERF-05-B5** | Remove duplicate full-term decoded-postings retention **only if source-safe** | A strictly scoped cursor/borrowed-view handoff that feeds the now-canonical one-term candidate buffer, while still validating every decoded posting (including nonwinners), maintaining exact logical posting charges, corruption/error order and cancellation. No extra full-M `TermPostings` allocation if equivalent, safe lifetime can be demonstrated | Generic streaming executor replacement, changes to index/postings layout, WAND, short-circuit at K, typed/Boolean/phrase broadenings, unvalidated nonwinners | **Conditional**, after B4 and only after a separate detailed design review proving novelty versus rejected 15G-C/D, 15H-A/A2 and 15I-C. If proof fails, omit B5 and proceed to PERF-05-C; no agent improvisation |

**Order:** `A → B1 → B2 → B3 → B4 → (B5 only if proved) → C`. B1/B2 are deliberately isolated and low-risk. B3/B4 are separate stages because representation/ownership and score production must be validated independently. **B5 is a real optional stopping gate**, not authorization to force a risky reimplementation of rejected streaming work.

### Why not split into more tiny changes?

- B1 must include the strict eligibility and callback-equivalence tests in the **same** change; separating them would leave an unsafe intermediate state.
- B3 must include its associated scorer-input adaptation and ledger proof; simply changing `BTreeSet` to `Vec` without adapting callers is not a deliverable.
- B4 must include score-source reuse **and** removal of the scored map/vector; changing one without the other merely adds temporary copies.
- B5's viability depends on the B4 final ownership shape. Designing/implementing it before that would invite rework and old regressions.

## 3. Suggested authoring/verification contract per subplan

A separately generated `PERF05B<n>_DETAILED_PLAN.md` and `PERF05B<n>_EXECUTION_REPORT.md` live under `docs/pr-artifacts/perf-05/`, both committed to PR #117 (a plan is not evidence it was executed).

**Before any B<n> agent step:**
1. `git fetch`, switch to `dev/perf05-physical-execution-series`, fast-forward pull; verify clean tree, exact parent stage commit and actual source; STOP on divergence or unexpected existing implementation.
2. Follow the plan's allowlist, concrete code edits and specified test fixture matrix. Run relevant unit/integration tests with mocking/fakes, rustfmt/clippy/compile as prescribed. Require exact error/sort/score/ledger/cancellation parity and no skipped failing test.
3. Commit/push only authorized files to **same PR #117**; include stage-specific red/green tests, test commands, execution evidence, scope audit and final disposition. **Do not run `quervant-bench run`, any timed A/B, `perf record`, profiler smoke test or other real performance acquisition during B1–B5.**
4. Independent review of each subplan's implementation before authoring/invoking the next, with `PASS`, `FIXUP` or `STOP`. Fixups remain bounded to the affected stage; no silent crossover into future stages.

**Nonnegotiable invariants:** exact `total_hits` and doc IDs/order/ties, exact returned BM25 scores, effective-live/tombstone/duplicate-key handling, selected/**unselected** corruption, failure precedence and atomic resource-limit errors, logical work/byte/peak accounting even when physical allocations disappear, cancellation polling, snapshot/PIT/cursor, batch and aggregation behavior, stable generic fallbacks and default PERF-01 duplicate prefilter (K10 linear / K100 P2).

**Stop immediately if:** a changed representation makes logical budget admissions less strict; scores differ; a corruption or cancellation test stops firing; sparse fallback enters a new slow dispatcher; a stage requires index-format changes; a stage regresses general execution semantics; or the coding agent needs to invent a new data-flow/score algorithm. Return a typed, evidenced STOP report rather than improvising or weakening tests.

## 4. PERF-05-C — B-only warm qualification against retained historical A

Maintainer decision `PERF05C_B_ONLY_HISTORICAL_A_NO_RUSTFS_NO_UNNECESSARY_WORK` supersedes the earlier paired A/B and profiling description **for this stage only**. PERF-05-C now:

- measures only the pinned PERF-05-B1…B5 Quervant source (`ee18ed63bbeeb54b544393ee0f676987ff9987d1`) on the existing 10K/100K × absent/rare/medium/common × K10/K100 warm matrix;
- loads the immutable 2026-11-22 historical Q-arm result (blob `a809f0362553e4e5c93ac1593ef478e8eef6a865`, run `f2df1d40-2eee-4fcb-9593-ba8433e08c4a`, measured source `256501f0e700ed199f316e79d128389375177530`) read-only and compares **absolute** medians descriptively; it never rebuilds, starts or samples A, Tantivy or Lucene;
- uses temporary `BB`/`BB2` aliases of the one B executable and its indexes for within-session B/B stability only; both aliases are the same B source, not a second production arm;
- runs no RustFS/container/service startup, no profiler, no Criterion and no `perf` capture; CPU profiling is deferred and is not a gate for this campaign;
- publishes exactly one new configuration and one new immutable result under `benchmarks/studies/perf-05/warm/`, recording the B absolute medians, the historical A reference, per-lane ratios and context comparison;
- does **not** claim a paired confidence interval, contemporaneous A/B, or causal code-only attribution. The `TARGETS_MET` / `TARGETS_NOT_MET` / `CONTEXT_CHANGED` flags are predeclared review signals; adoption and merge require human review.

The earlier `9775bfca4c58a27e65ca28c1d705efad00a65ec8` identity is the pre-PERF-05 main base, not the measured historical A source; the actual retained Q-arm measurement came from `256501f0…`. A future paired A/B study or diagnostic CPU profile requires a separate approved plan and must not reuse this B-only result as a paired estimate.

## 5. What is deliberately excluded

Index-format and sortable-ordinal changes, storage compression/SIMD and WAND, new query-planner/dispatcher architecture, generic Top-K heap replacement, modifying output score contracts, and profiling/benchmark framework refactoring. The prior negative experimental evidence remains binding; these items require separate architectural authority outside the present B plan register.

**State at register creation:** No B implementation has been started. This file is the plan-of-plans; each subplan's detailed design and permission to execute remain separate actions.
