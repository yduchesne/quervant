# v0.1-perf — Performance optimization roadmap

> **Milestone:** `v0.1-perf` — standalone Quervant search-engine performance improvements.
>
> **Status:** PERF-01 DONE (implemented); PERF-02–PERF-04 PLANNED (investigation first); PERF-05 FUTURE / CONDITIONAL.
>
> **Authority boundary:** This is an ordered work register and research agenda, **not** blanket authorization to implement a proposed fast path, change a segment format, relax correctness rules, or run an unapproved benchmark. Each future PR requires a detailed execution plan and explicit acceptance gates under [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md).

## Purpose and sequencing

The `v0.1-perf` milestone resumes Quervant's **engine optimization** program after the benchmarking-framework migration (BM-01–BM-09). The BM sequence builds the means to qualify, preserve, and replay performance experiments; it is **not** itself an engine optimization. This document does not mark BM-09 complete or modify [PR #110](https://github.com/yduchesne/quervant/pull/110).

The reference engine for new experiments includes the previously delivered retained-key duplicate **prefilter** (PERF-01). Future experiments must compare against the **actual accepted pre-optimization source**, not silently substitute an older baseline, a historical benchmark runner, or the pinned variants from the old retained-key experiment. First acquire and accept the current benchmark baseline through BM-09; retain its raw data and qualifications. A new optimization experiment must receive its own registered workload and versioned execution contract in the migrated framework where the existing two families do not already fit.

This milestone targets the **v0.1 single-shard lexical engine**. It does not include v0.2 distributed orchestration, vector/ANN, ontology, or unrelated product functionality. A performance improvement is not evidence of a functional release boundary being met.

## Ordered PR register

| PR | Subject | Status | Required first deliverable |
| --- | --- | --- | --- |
| **PERF-01** | Retained-key duplicate detection: request-local prefilter | **DONE — implementation** | Preserve shipped configuration and source evidence; no new optimization work |
| **PERF-02** | Residual sort-value extraction, validation and candidate sort-key handling | **PLANNED — next investigation** | Source and post-prefilter profiling dossier; concrete optimization decision |
| **PERF-03** | Heap admission, candidate comparison/update and remaining materialization | **PLANNED — conditional** | Residual-cost attribution and narrow candidate decision |
| **PERF-04** | Reusable per-query state, validated reader access and reopen overhead | **PLANNED — conditional** | Ownership/cache audit, fresh profiling and safe lifetime/charging design if warranted |
| **PERF-05** | Postings traversal, skipping/compression and storage/I/O improvements | **FUTURE — conditional** | Evidence-based architecture investigation; separate format/remote-store approvals if necessary |

Order means **priority for investigation**, not a promise that every row will ship code. A completed measurement-only PR with a well-supported `NO-OPTIMIZATION` or `REJECTED` disposition is legitimate. No subsequent PR should implement an approach that failed an earlier acceptance gate without a materially new, approved design.

## PERF-01 — Retained-key prefilter [DONE]

**Delivered behavior.** The unified searcher implements configurable retained-key duplicate checking. Its production default is `TopKDuplicateConfig { min_top_k: 32, strategy: Prefilter }`; `ExactSet` remains separately configurable. Below the configured Top-K threshold the existing bounded linear behavior remains available. The prefilter is a **negative filter only**: a definitely absent key can avoid a duplicate scan, but a possible match still requires exact checking. It must never permit duplicate live document keys, alter top-K ordering, or weaken resource/cancellation semantics.

**Implementation authority:** `crates/quervant-core/src/search/unified.rs` (`TopKDuplicateConfig`, `TopKDuplicateStrategy` and the owned candidate-admission strategy). **DONE describes the implementation**, as explicitly adopted for this milestone. It does **not** retroactively turn the original PR 15I-D3-B measurement branches into qualified performance wins, assert an unobserved current-head speedup, or complete BM-09. The historic D3-B and F1/F1.1/F1.2 blocked/rejected experiments remain recorded without rewriting their dispositions in [ROADMAP.md](ROADMAP.md) and [BENCHMARKING.md](BENCHMARKING.md).

**Resulting baseline rule.** PERF-02 and later must use a source revision whose actual duplicate configuration is declared and verified. Record the default prefilter threshold and any experimental override, and compare like-for-like settings unless the override is the explicit treatment under study.

## PERF-02 — Residual sort-value processing [PLANNED: NEXT]

**Hypothesis.** After eliminating much of duplicate-key checking, repeated sort-value access, validation, comparisons and sort-key construction may account for the next material portion of candidate-processing cost. The existing five-run D3-A-F2 attribution measured **steady-candidate child shares** for sort views of 23.83% (100K medium/K100), 17.58% (100K common/K100), and 26.26% (100K common/K10). These percentages are **not** end-to-end latency shares or proven removable work, and they predate the fully configured prefilter baseline. [D3-A-F2 five-run data](pr-artifacts/pr-15i-d3a/fixup-f2-five-run-performance.md).

**Prior work to reuse.** PR 15H-B investigated a borrowed keyword sort view with late owned tuples and recorded locally qualified improvements; its implementation and review status must be audited on the exact new baseline before designing anything overlapping. Do **not** implement that same borrowed-`&str` technique a second time, infer that its earlier measurement is a current-head gain, or broaden its eligibility by default. [PR 15H-B qualification](pr-artifacts/pr-15h-b/qualification.md).

**PERF-02 investigation contract:**

1. Freeze and inspect the post-prefilter baseline; map `ColumnAccess`, `SortValue`, selected-hit/sort-tuple ownership, heap admission and any previously borrowed-view path. Identify validation and budget work that **must** remain even for losing candidates.
2. Measure separate costs of value location, decoding/validation, sort comparison, owned tuple construction, and repeated per-candidate setup across **medium/common and absent/rare guards**, K10/K100 (and other eligible top-K levels justified by the source).
3. Use counters and profiling attribution that distinguish exclusive from inclusive costs, and prove whether sort handling remains material **after** the prefilter. Report a ranked, bounded hypothesis; distinguish actual savings from costs that remain mandatory.
4. End with `OPTIMIZE` (a named, bounded candidate and separate approved implementation design), `NO-OPTIMIZATION-REQUIRED`, or `BLOCKED` with exact missing evidence. Do not implement a speculative plan merely to finish the PR.

Any eventual implementation must preserve byte-exact sort semantics, null/missing/multivalue handling, ties, return scores, ordered keys, cursor/PIT consistency, snapshot immutability, corruption detection, error precedence, work/memory accounting and cancellation. A segment-format change is outside PERF-02 unless separately approved.

## PERF-03 — Heap and remaining candidate processing [PLANNED: CONDITIONAL]

**Hypothesis.** Heap comparisons, worst-candidate checks, replacements and ownership transitions may remain expensive after PERF-01/02. D3-A-F2 recorded heap compare/update steady-child shares of 3.71%, 4.21% and 6.40% in the same three 100K primary lanes. Its separate intermediate matched/scored collection region was below the original materiality gate, and steady candidate materialization was often zero; **do not promote those regions to a major hotspot without fresh evidence**. [Attribution report](pr-artifacts/pr-15i-d3a/fixup-f2-five-run-performance.md).

**Investigate:** number of candidates examined versus admitted, replacement frequency, key/sort allocation and retention, heap comparison cost, candidate/segment work counters, and any interaction with the prefilter and PERF-02 changes. Use source-observed, non-overlapping cost buckets.

**Guardrails:** no duplicate bypass; preserve complete `total_hits`, exact ordering and ties, failed-admission atomicity, budget/peak accounting, cancellation, and corruption detection. Earlier candidate/materialization and DOC_KEYS-borrowing attempts failed important gates; do not relaunch them unchanged. If the marginal improvement is not material relative to measurement uncertainty and engineering risk, record `NO-OPTIMIZATION-REQUIRED`.

## PERF-04 — Reusable query state and reader access [PLANNED: CONDITIONAL]

**Hypothesis.** Recreating validated geometry, per-query metadata and selected-document access structures, or expensive reopen/mutation-state work, may be avoidable in a source- and snapshot-safe way. This requires a clear lifetime/ownership model rather than simply widening a cache.

**Reuse and previous evidence:** PR 15G-A explored immutable column geometry caching; PR 15G-B explored validated lazy STORED/DOC_KEYS offsets, both with recorded favorable local performance evidence and separate completion gates. First inspect which pieces actually exist in the accepted production source and which are test-only or unmerged; **do not duplicate an already delivered cache or assume its historical status is current acceptance**. [Column geometry](pr-artifacts/pr-15g-a/performance-qualification.md) · [reader offsets](pr-artifacts/pr-15g-b/performance-qualification.md).

**Investigate:** query-local versus shared immutable state, repeated column/dictionary/record setup, selective STORED/DOC_KEYS access, snapshot opening/reopening and mutation-state refresh, and local/remote cache visibility. Distinguish mandatory full-record validation from removable repeated parsing.

**Required design before any optimization:** specify source/segment/generation/format trust roots, immutable cache ownership, exact resource charging/eviction, safe fallback, corruption of **unselected** records, legacy-format parity, remote RustFS compatibility, and error-order/cancellation behavior. Changes to persistent offsets or segment formats require their own versioned compatibility approval. No silent validation short circuit.

## PERF-05 — Postings and storage physical work [FUTURE: CONDITIONAL]

After PERF-02–04 evidence is reviewed, evaluate block-oriented postings traversal, skip structures, compression/SIMD where profitable, fast-field/dictionary representations, and portable I/O or bounded range access. These are **separate subproblems**, not one authorized rewrite. Distinguish scored-query acceleration (including any future block-max/WAND work) from exact-count/explicit-sort workloads: a ranking shortcut cannot silently weaken exact `total_hits`.

Trigger only on a demonstrated, still-significant CPU, allocation, I/O, or index-size bottleneck. Any index-format revision, mmap assumption, remote-range strategy, or migration requires specific correctness, failure/repair, and RustFS portability decisions before implementation. Historical compact-dictionary/persistent-offset attempts that missed whole-index or low-hit gates remain negative evidence, not templates to reinstate. [Earlier optimization investigation index](PERF_OPTIMIZATION_PLAN.md).

## Measurement and decision contract for PERF-02 onward

1. **Begin after BM-09 acceptance.** Use the independently verified current baseline and committed source/evidence identities. Resolve any BM-09 qualification defects separately; do not change the BM study to create favorable optimization results.
2. **Define a new experiment explicitly.** The migrated framework currently has fixed cross-engine and retained-key families; a two-arm optimizer study may require a **new registered, versioned experiment**. Reuse its orchestration, source/host pinning, A/A controls, analysis, publication and replay—never falsify old study IDs, pinned revisions or thresholds to reuse an adapter.
3. **Freeze the scientific contract before timing.** A is the latest accepted source **including PERF-01** (and subsequently accepted PERF changes); B is A plus only the proposed optimization. Record exact Git SHAs, build binaries, host, corpus, workload, eligibility, arms, block/slot schedule, estimator, uncertainty/thresholds, readiness gates and permitted retries. Require independent oracle checking and a stable same-source A/A control.
4. **Measure paired relative effects, not absolute cross-run timings.** Randomize and position-balance A/B within qualified blocks, collect all prescribed observations before any symmetric arm-neutral noise pruning, and retain raw and excluded blocks with reasons. The applicable numeric estimator and confidence interval belong to the approved experiment; do not substitute a quotient of unrelated medians. Current-vs-historical effect differences are percentage points when methods/workloads are compatible, with environment differences disclosed.
5. **Protect correctness and negative cases.** Test absent/rare/medium/common selectivity, K boundaries, missing and duplicate keys, corruption in selected/**unselected** records, tombstones, refresh/merge/reopen, PIT/cursor pagination, typed/JSON/geo/aggregate fallbacks, saturation, overflow, cancellation and memory budget release. Reject a faster result that violates any nonnegotiable semantic boundary.
6. **Preserve and independently replay.** Store the complete evidence under a committable `benchmark-results/` baseline with raw samples, independent references, source/binary/host identities, acceptance decisions and readable proportional reports; reproduce calculations from a clean checkout without new measurements. Do not rewrite old evidence or use a synthetic control as proof of a real run.
7. **Decide before moving on.** Each PERF PR must end with `ACCEPTED`, `REJECTED_ROLLED_BACK`, `INCONCLUSIVE`, `NO_OPTIMIZATION_REQUIRED`, or `BLOCKED`, with actual commands, tested revision, proof of restoration where relevant, and review authority. Do not auto-promote the next candidate or repeat a failed campaign to pursue a favorable result.

The [benchmark methodology](BENCHMARKING.md) is normative for terms such as lane, arm, block, slot and sample, balanced scheduling, failure classification and symmetric pruning. **Its previous experiment's number of blocks, samples and arms is not automatically the new PERF protocol.** The current design and acceptance standards also follow [TESTING.md](TESTING.md) and [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md).

## Historical findings and non-duplication index

| Earlier work | Relevance to this milestone | Constraint |
| --- | --- | --- |
| [PR 15I-D3-A-F2 attribution](pr-artifacts/pr-15i-d3a/fixup-f2-five-run-performance.md) | Candidate duplicate and sort/heap subcosts localized | Old source and sampled child shares; remeasure after PERF-01 |
| [PR 15I-D3-B history](ROADMAP.md) | Prefilter experiments, control requalifications and early negative results | PERF-01 DONE is an implementation status, **not** a rewrite of the earlier verdicts |
| [PR 15H-B borrowed sort key](pr-artifacts/pr-15h-b/qualification.md) | Prior sort-value optimization with local qualification | Reuse/audit; do not repeat unmodified |
| [PR 15I-D1-F DOC_KEYS borrow](pr-artifacts/pr-15i-d1-f/execution-status.md) | Candidate ownership approach rejected and rolled back | Do not retry unchanged |
| [PR 15I-D2-A late scoring](pr-artifacts/pr-15i-d2a/execution-status.md) | Measured scoring cost low priority | Do not schedule late scoring without new evidence |
| [PR 15I-C physical executor](pr-artifacts/pr-15i-c/closeout.md) | Rejected and retired | Materially new design + explicit approval required |
| [PR 15G-A/B reader-state work](PERF_OPTIMIZATION_PLAN.md) | Favorable earlier cache/offset investigations | Audit accepted source and remaining gates before reuse |
| [PR 15H-E compact dictionary](pr-artifacts/pr-15h-e/decision.md) | Section-level size reduction failed whole-index gates | Whole-index and low-hit acceptance required |

## Milestone exit and documentation rules

`v0.1-perf` is **not DONE** just because PERF-01 is DONE. An explicitly approved set of remaining performance investigations must have final dispositions; any implementation accepted for shipment must have independent correctness and same-run performance verification, applicable Rust stable/MSRV/real-RustFS/coverage/CI gates, preserved data, and a clean-checkout replay. Report rejected and no-change outcomes without weakening acceptance or silently discarding evidence.

Advance each table status only after its required gate and human review. Keep `docs/ROADMAP.md` and this register aligned at milestone boundaries; leave earlier immutable qualification and historical PR reports unchanged.
