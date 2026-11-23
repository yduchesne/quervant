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

## 4. PERF-05-C — Final integrated QA, benchmarking **and profiling** (formerly D)

This is the **only performance-acquisition stage** of PERF-05. Execute it **once after all chosen B substeps have passed their correctness reviews**, on the same PR #117.

### C1. Correctness, source and warm A/B acceptance

Full stable/MSRV Rust QA, project coverage and local/RustFS integration, adversarial invariants above, CI at exact final source head, and **one controlled, qualified, uninstrumented warm A/B study** versus the accepted production baseline, with immutable source/build pins and frozen 10K/100K × absent/rare/medium/common × K10/K100 guardrails. Build both A and B with matching, *ordinary production release* flags (no profiling-only compiler modifications). Preserve all raw/derived A/B evidence and independent oracle results. Warm end-to-end effects alone decide performance adoption; CPU percentages do not substitute for them.

### C2. CPU profiling and Rust symbol readiness — **do not assume current framework is sufficient**

The merged PERF-02-B bench-only diagnostic `benchmarks/quervant_bench/lean/perf02b_diagnostics.py` **already** parses saved `perf script` samples, normalizes known Rust-v0 demangler output and tests nonoverlapping classification. The host's Rust-v0 symbols were recoverable offline with `c++filt` (captured `_R…` tokens → `quervant_core[hash]::…` etc.). **But the original PERF-02-B `perf --call-graph dwarf` captured insufficient usable caller stacks in 3/4 lanes**: they failed the ≥85% attributable gate at 68.95%, 79.84% and 82.08%, despite successful symbol demangling. A valid Rust symbol name **does not imply** a valid call tree or trustworthy subsystem CPU share. The BM-10 runner itself is primarily a query benchmark harness, **not an automatically reliable Rust profiler**.

**Required PERF-05-C-only preflight and capture design (freeze before recording):**

1. **Keep uninstrumented performance binaries isolated.** Build a **separate**, pinned source-equivalent *profiling* executable with optimized release code, retained symbols/debug information (candidate settings: `-C debuginfo=2` and `-C force-frame-pointers=yes`). Record the exact toolchain, feature set, compiler flags, binary SHA256/build ID, index and query IDs. Frame pointers may improve user-space callchain recovery but are **not a guarantee**, especially across precompiled runtime/libc frames. Do not treat the profiling binary's wall time as the A/B acceptance measurement.
2. **Preflight without launching a new benchmark campaign:** verify supported profiler event and user-space permissions, available `perf`, `c++filt`, optional `llvm-symbolizer`/`addr2line`, binary symbols and the executable/build-ID binding. Select **one fixed call-graph strategy** in the approved C capture contract (prefer `perf record --call-graph fp` *if* the profiling build has valid frame-pointer chains; otherwise an explicitly documented DWARF strategy). Do not repeat open-ended experiments with rates, unwinders or compiler settings. No full timed tests during this preflight.
3. **One finite capture inside C:** collect retained `perf.data` and `perf script` (and optionally `perf report`) on the final optimized source, with request and sample provenance. Save the **original raw files**, checksums, and distinct **demangled derived copies**. Rust-v0 demangling is a read-only offline transform of preserved `perf script` (`c++filt` as used in PERF-02-B); normalize verified crate hashes and trait paths with the existing canonicalization helper. Never overwrite the raw captures to obtain an apparently cleaner sample count.
4. **Extend only the narrowly needed profiler classifier:** PERF-02-B's fixed `QUERY`/`SORT` markers do **not** automatically classify PERF-05 stages. Freeze *before capture* an explicit non-overlapping source-backed symbol map for setup/stats, postings, membership, matched collection, score map/BM25, candidate retention, projection, startup and `UNKNOWN`. Use the established pure Python/mock-test approach and avoid changing BM-10 result schemas, benchmark estimators or unrelated harness behavior.
5. **Fail closed on visibility:** require query-root presence, recognized Rust functions, a sufficient number of query samples, a predeclared accountable share (the earlier 85% gate is an appropriate non-weakening reference if reused), non-dominant unknown stacks and no overlapping attribution. If libc allocator leaves/empty stacks again prevent reliable attribution, report **`PROFILING_BLOCKED_UNWINDING`** with exact missing evidence. Do **not** call unknown samples `SORT`/`SCORE`, lower thresholds after observation or infer stage shares from one valid lane. Profiling failure does **not** invalidate independently qualified, uninstrumented A/B measurements, though it prevents a trustworthy CPU breakdown.
6. **Retain a complete diagnostic dossier:** toolchain and host information, raw+derived hashes, demangler proof, root/call-stack coverage, per-workload source stage shares only where qualified, sample counts, unknown buckets, baseline/optimized binary identity, and explicit separation of sampled CPU from measured wall-clock improvement. Declare exactly which lanes were profiled, what was and was not attributable, and any limits or blockers.

**No need to retrofit PROFILING into every B step**; all symbol readiness, test-only classifier changes and real profiling acquisitions belong to C. Actual capture method must be validated against the user host; `-C debuginfo=2` / `-C force-frame-pointers=yes` improves the prospects but cannot guarantee successful unwinding under WSL2 and system libraries.

### C3. Final decision

Accept/adopt the completed change only if functional/resource contracts pass and the **qualified uninstrumented warm A/B** meets predeclared improvement/guardrail requirements; otherwise reject/roll back through review. A valid performance result can coexist with a blocked profiling report, but the latter must not claim an identified CPU bottleneck. **Do not claim performance from big-O or incomplete CPU samples alone.**

The final stage is named **PERF-05-C**. There is **no PERF-05-D**. No separate PR is opened for qualification or profiling.

## 5. What is deliberately excluded

Index-format and sortable-ordinal changes, storage compression/SIMD and WAND, new query-planner/dispatcher architecture, generic Top-K heap replacement, modifying output score contracts, and profiling/benchmark framework refactoring. The prior negative experimental evidence remains binding; these items require separate architectural authority outside the present B plan register.

**State at register creation:** No B implementation has been started. This file is the plan-of-plans; each subplan's detailed design and permission to execute remain separate actions.
