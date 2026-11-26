# v0.1-perf — Performance optimization roadmap

> **Milestone:** `v0.1-perf` — standalone Quervant search-engine performance improvements.
>
> **Status:** PERF-01 and PERF-02-A DONE; PERF-02-B **MERGED — `PERF02B_BLOCKED`** ([PR #116](https://github.com/yduchesne/quervant/pull/116)). **PERF-05 MERGED** ([PR #117](https://github.com/yduchesne/quervant/pull/117)): B1–B5 implemented; C completed a qualified B-only warm run with historical, unpaired performance targets met (first unstable attempt retained). **PERF-06 IN PROGRESS**: three ordered engineering series, A1–A4, B1–B4, C1–C4; planning [PR #118](https://github.com/yduchesne/quervant/pull/118) remains draft; B1–B3 merged and B4 executed (`PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`, G10 open). PERF-03/04 remain separate/deferred; ordinal-sort design is now proposed within PERF-06-B.
>
> **Authority boundary:** This is an ordered work register and research agenda, **not** blanket authorization to implement a proposed fast path, change a segment format, relax correctness rules, or run an unapproved benchmark. Each future PR requires a detailed execution plan and explicit acceptance gates under [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md).

## Purpose and sequencing

The `v0.1-perf` milestone resumes Quervant's **engine optimization** program using the BM-10 direct benchmarking framework, successor to the terminated BM-09 certification approach. Benchmark framework work supplies measurement, statistical comparison and saved results; it is **not** an engine optimization. BM-09 was terminated incomplete; **BM-10 is DONE — MERGED** and the BM implementation series is closed. BM-10 delivered a corrected native-string-sort warm cross-engine campaign, while the separately planned retained-key and process-cold campaigns remain outstanding operational studies. No BM-series completion status establishes a new search optimization or a causal performance improvement.

The accepted reference includes the PERF-01 retained-key duplicate **prefilter** and all merged PERF-05-B1–B5 changes. For each future optimization, identify the **actual accepted source** before that change (not an older retained-key diagnostic baseline or a later branch that contains the treatment). Warm-query performance remains authoritative under the [permanent query-optimization selection rule](BENCHMARKING.md#query-optimization-selection-warm-performance-is-authoritative-permanent-rule). The general prospective A/B protocol and the explicitly authorized PERF-05 B-only, historical-A protocol are **different evidence types**: only a contemporaneous paired experiment yields paired A/B intervals. PERF-06 retains the B-only/historical approach when the archived baseline is genuinely comparable; each qualification plan must verify provenance, identical logical work, semantic equivalence, build/host context, and readiness before computing descriptive relative gains. If no qualified historical reference exists, stop and obtain a separately approved acquisition design rather than inventing a comparison. New optimization studies require their own immutable configuration and result identities.

This milestone targets the **v0.1 single-shard lexical engine**. It does not include v0.2 distributed orchestration, vector/ANN, ontology, or unrelated product functionality. A performance improvement is not evidence of a functional release boundary being met.

## PR register and revised investigation priority

| PR / scope | Subject | Status / priority | Required first deliverable |
| --- | --- | --- | --- |
| **PERF-01** | Retained-key duplicate detection: request-local prefilter | **DONE — implementation** | Preserve shipped configuration and source evidence; no new optimization work |
| **PERF-02-A** | Pinned Quervant-only warm A/B benchmark study | **DONE — implementation, PR #115** | Pinned A/B build/stage study; no full timed readiness campaign |
| **PERF-02-B** | Bounded warm sort-path profiling | **MERGED — `BLOCKED`, PR #116** | Preserve the report and captured evidence. One lane has valid 11.6% sampled sort-path CPU; three fail the 85% attribution gate. No further PERF-02-B profiling or optimization claim |
| **PERF-05** | High-hit physical execution and representation reuse | **MERGED — PR #117** | B1–B5 implemented and independently reviewed; [C qualification results](../benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-002.json) COMPLETE with 16/16 B/B PASS and all historical-relative targets met. Earlier INCOMPLETE attempt preserved. No profiling was part of final C.
| **PERF-06-A** | Scoring and postings efficiency | **A1–A3 MERGED; A4 MERGED (targets not all met); A5 IMPLEMENTED — INDEPENDENT REVIEW PENDING; A6 PLANNED** | A1–A3 retained; A4 PR #123 merged with its measured `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` disposition unchanged; A5 adds compact postings for 1–128-document terms and wires compaction to the same encoder; A6 is a separately planned qualification.
| **PERF-06-B** | Fast-field and document-identity architecture | **B1–B4 MERGED; B4 QUALIFIED, PR #129** | Persistent keyword ordinals, numeric cross-segment sorting and compact document identity; B4 qualified the cumulative paired warm campaign. Historical per-lane result and guardrails remain unchanged. |
| **PERF-06-C** | Integrated physical query executor | **C1 DOCUMENTATION PR — REVIEW PENDING; C2–C4 PLANNED** | [C1 physical-execution contract](architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md) and [source reconciliation](pr-artifacts/perf-06-c/PERF06C1_SOURCE_AUDIT.md); then direct exact-term count/Top-K, guarded deferred scoring and consolidated warm qualification.
| **PERF-04 (second investigation)** | Residual reader-state / validated access reuse | **PLANNED — SHORT AUDIT** | Compare accepted code against PR 15G-A/B already delivered; identify one still-repeated material operation or close without broad profiling |
| **Earlier ordinal-sort feasibility** | Prior source-only hypothesis | **INCORPORATED AS PERF-06-B DESIGN INPUT** | Design remains to be proven in B1/B2; not a preapproved implementation or a PERF-02-B revival. |
| **PERF-03 (fourth)** | Heap admission / comparison / ownership | **DEFERRED — NEW EVIDENCE REQUIRED** | Reopen only on a credible material remaining whole-query cost; historical heap-child shares alone do not qualify |

**Sequence:** PERF-05 is the **merged baseline**. PERF-06 is a three-series initiative executed in dependency order **A → B → C**, with **one separate implementation PR for each numbered substage**; [draft PR #118](https://github.com/yduchesne/quervant/pull/118) is documentation/planning only. Earlier PERF-03 and PERF-04 entries remain independent/deferred; their identifiers are not automatically reused. The earlier ordinal-sort feasibility topic is now an input to PERF-06-B, with no implied design approval. This register authorizes planning, **not** autonomous architecture selection, implementation, benchmark acquisition, profiling or merge. Rejected earlier experiments require a materially different approved design before revival.

**PERF-05 precedent retained for PERF-06:** source-proven redundant or unnecessarily expensive work justifies a prescriptive, correctness-first engineering design **without speculative pre-implementation speedup estimates or per-PR real benchmarks**. Mocked/deterministic adversarial QA and source reviews occur after each implementation PR; one separately approved **consolidated warm qualification** concludes each A/B/C subseries. Reuse qualified historical baseline measurements when the work and provenance are truly compatible, measure the candidate only with same-build B/B stability controls, and label all resulting historical-relative estimates **descriptive and unpaired**. Such evidence must never be represented as a paired A/B CI or a universal causal attribution. When a causal paired claim is necessary, it requires a separately authorized same-session A/B study. Do not retune failures or run unrelated tests and services solely to complete a checklist.

## PERF-06 — Architectural efficiency series [PLANNED; NO IMPLEMENTATION AUTHORIZED]

**Authority and topology:** [PERF-06 planning PR #118](https://github.com/yduchesne/quervant/pull/118) and [series register](pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md) record the agreed workstream structure. PR #118 is **planning/documentation only**; **A1–A4, B1–B4 and C1–C4 are twelve *planned, separately reviewable implementation/qualification PRs***, not twelve already-created GitHub PRs. No numbered PR can start until its source-specific detailed design is approved. Every next PR starts from the last accepted/merged dependency; do not carry unreviewed experiments forward.

**Baseline:** The starting source is the merged PERF-05 `main` lineage, including B1–B5. A1 begins against that accepted baseline. The accepted **A** completion becomes B1's baseline; accepted **A+B** becomes C1's baseline. Source revisions and archived benchmark identities must be pinned and verified for each new qualification. No PERF-05 result should be silently treated as the contemporaneous benchmark of later, structurally different work.

### PERF-06-A — Scoring and postings efficiency

**Goal:** eliminate unnecessary per-match computation and decoding, and provide a postings representation suitable for efficient lexical execution.

| Planned PR | Target and deliverable | Dependency / scope boundary |
| --- | --- | --- |
| **PERF-06-A1** | Precompute query-constant BM25 term weights and values (especially IDF) and use a shared term-scoring context; verify exact externally returned scores and non-finite/error contracts. | First; narrow scorer change, no postings-format change. Floating-point evaluation order and bitwise score parity must be explicitly designed and tested; STOP if exact preservation is infeasible without authorization. |
| **PERF-06-A2** | Introduce an explicit document-ID/frequency-only postings decoding API; avoid per-match positional `Occurrence` allocations/`Posting` clones where the consumer requires no positions. | After A1; preserve phrase/positional APIs, full corruption validation policy, limits and cancellation. No opportunistic skip of unvalidated positions. |
| **PERF-06-A3** | Versioned postings layout with separately accessible doc-ID, frequency and positional streams and block/skip metadata; integrate writer, decoder and index construction. | After A2; deep codec/storage refactor and reindexing allowed. Specify validation trust boundary, phrase compatibility, decoded-resource admission and index-size tradeoffs before coding. No unapproved change to query semantics. |
| **PERF-06-A4** | Integrate and independently review A1–A3, finish full deterministic/adversarial correctness QA, then run **one approved warm qualification** for the cumulative A-series candidate, including negative-case guards and preserved results. | Final A gate; no new optimization algorithm selected during qualification. Accepted A forms the B starting baseline. |

#### PERF-06-A current-status amendment (PERF-06-A5)

A1–A3 remain retained. A4 PR #123 is merged; its complete second paired campaign
met two of four primary targets and all guards, with no lane classified as
regressed. The measured targets-not-met disposition remains historical evidence.
A5 addresses short-list postings metadata and correctness/structural footprint.
A6 is a separately planned consolidated compatibility/storage/warm-performance
qualification before B1. No A6 acquisition is authorized by A5.

| Stage | Status | Deliverable / boundary |
| --- | --- | --- |
| **PERF-06-A5** | `IMPLEMENTED — INDEPENDENT REVIEW PENDING` | `FEATURE_ADAPTIVE_POSTINGS = 0x000F/1`; compact framed streams for `df <= 128`, unchanged A3 payloads for `df >= 129`; one-buffer compact encoding with fused size accounting; shared lazy full/lean decoder; both `SegmentBuilder` and `IndexWriter::compact` emit the adaptive family; legacy and split readers retained. Correctness/structural change only — no latency, writer-cost, RSS or real index-size claim. |
| **PERF-06-A6** | `PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED` | Consolidated A-series compatibility, storage and warm-performance qualification, including a genuine complete A3-produced (E) index appended/compacted by A5 and real benchmark-corpus index sizes. Must be separately designed and authorized; A5 authorizes no acquisition. |

**Updated dependency:** `A1 → A2 → A3 → A4 (merged, targets not all met) → A5 →
A6 → B1 → ...`. A6 remains a precondition for B1 and does not retune A4's
declared targets.

#### PERF-06-A current-status amendment (PERF-06-A6)

A6 executed the consolidated qualification of merged A5 at
`3bb232f868cb556ce9b4273d902164c65416af0f` under an explicit user instruction that
treats main as stable and waives unit/integration/QA/CI waiting for that task.
Two prospective paired warm campaigns were run once each (E→F isolation and
A0→F cumulative), real whole-index bytes were measured, and four descriptive
writer build-process observations were recorded. The compatibility gate initially
blocked on a driver compile defect and was then completed by the A6-F1
continuation, which corrected only the digest serializer and ran all six native
and real-RustFS modes successfully. Disposition:
`PERF06_A6_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` — every compatibility, storage
and replay gate now passes, while one of sixteen A5 retention lanes and two of four
cumulative primary lanes remain below their frozen thresholds.

| Item | Measured A6 outcome |
| --- | --- |
| Retained metric changes | None. A1–A3 and A5 are unchanged; the A5 codec is not modified by A6. |
| Warm A5 retention (E→F) | 15/16 lanes inside the frozen retention budget; `10000/absent/k10` at −2.122% is the single NOT_MET lane. |
| Warm cumulative (A0→F) | 2/4 primary lanes ≥5% (`100000/common` K10 +6.2%, K100 +5.4%); `100000/medium` K10 +3.1% and K100 +3.4% are below target; 12/12 guards pass. |
| Whole-index bytes | F/E = 0.618 (10K) and 0.621 (100K): 38.2%/38.0% smaller than E and ~6.6% below A0. Both predeclared byte gates MET; the historical `90·(N+1)` byte model is MODEL_CONFIRMED exactly. |
| Writer resources | Descriptive single-run observations only; no acceptance threshold exists. Peak RSS ≈0.95–0.96×E, commit ≈0.80×E, reopen ≈0.67–0.70×E, total process CPU ≈0.81–0.83×E, narrower insertion `index_ns` ≈1.02–1.04×E. |
| Compatibility | Genuine old-writer coexistence, native compaction of E+F to one F segment, held PITs and real-RustFS cold reopen were **demonstrated** by six passing compatibility processes in A6-F1 (E created generation 1, F appended generation 2, native compaction produced one F segment at generation 3, and a separate process cold-opened the remote E+F mix). Remote compaction publication remains a maintainer-owned residual. |
| A4 history | Unchanged. A6 does not relabel, retune or re-derive A4's stored targets-not-met verdict. |

**B1 remains blocked.** A6 neither starts B1 automatically nor authorizes a merge,
release or promotion; independent maintainer review of the writer tradeoff and the
remote-compaction residual is still required. See
[PERF-06-A6 execution report](pr-artifacts/perf-06-a/PERF06A6_EXECUTION_REPORT.md).

### PERF-06-B — Fast-field and document-identity architecture

**Goal:** reduce string and identity work on candidates that cannot enter Top-K, using validated immutable representations.

| Planned PR | Target and deliverable | Dependency / scope boundary |
| --- | --- | --- |
| **PERF-06-B1** | Persistent, sorted keyword dictionaries plus per-document ordinal lookup for relevant single-valued keyword fields; define missing/null states and versioned segment codec. | After accepted A; separate schema/format design and reindexing permitted. Match UTF-8 lexical ordering, snapshot semantics, validation and logical work bounds. |
| **PERF-06-B2** | Segment-local ordinal-based ranking and exact cross-segment lexical merge, decoding retained strings only where semantically safe. | After B1; support correct sort direction, ties, null/missing, cursor/PIT, and fallback for unsupported shapes. No assumption that different segments share ordinal spaces. |
| **PERF-06-B3** | Compact validated document-key access and improved duplicate-identity handling so rejected candidates need not clone an owned key. | After B2; reconcile earlier 15H-C negative results and preserve exact-key deduplication, corruption/error ordering, mutation and resource semantics. No identity bypass or unapproved duplicate-policy change. |
| **PERF-06-B4** | Integrate and independently review B1–B3, finish format/reader/sort/identity QA and run **one approved warm qualification** for cumulative B. | Final B gate; include index-size, writer/rebuild and correct-sort checks as separate diagnostics, not warm latency. Accepted B forms C baseline. |

#### PERF-06-B current-status amendment (PERF-06-B3)

| Item | Status | Permanent design and evidence |
|---|---|---|
| **PERF-06-B3** | `IMPLEMENTED — INDEPENDENT REVIEW PENDING` | Runtime-only per-verified-segment-state key fingerprints (`DefaultHasher` over `str::Hash` of the raw key) built lazily on the first matched candidate of an eligible B2 `Ready` segment, charged to `MetadataBudget` under the existing `SegmentLimits`, retained once per verified state, and used *only* as a duplicate-check prefilter: a hash match is always confirmed with full raw UTF-8 key equality. Active only in the resolved `Linear`/`Prefilter` duplicate modes; resolved `ExactSet` keeps its unchanged `HashSet<DocumentKey>` path, and any metadata/allocation refusal downgrades the whole segment to the original owned-key path. Losing `Single` candidates own no `DocumentKey`, string or sort value; a numeric tie borrows the raw key once for the ascending byte tie-break; only a competitive candidate performs one fallible owned key allocation. No persisted hash, codec/writer/manifest change, public API or configuration addition. Correctness/resource evidence only — B4 owns every warm-performance, index-size and RSS question. Execution report: [PERF06B3_EXECUTION_REPORT.md](pr-artifacts/perf-06-b/PERF06B3_EXECUTION_REPORT.md). |

### PERF-06-C — Integrated physical query executor

**Goal:** build a coherent execution strategy on A/B's primitives rather than continue layering redundant full-match intermediates.

| Planned PR | Target and deliverable | Dependency / scope boundary |
| --- | --- | --- |
| **PERF-06-C1** | **Documentation only:** [physical execution contract](architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md) and [accepted-source/negative-evidence reconciliation](pr-artifacts/perf-06-c/PERF06C1_SOURCE_AUDIT.md). | From merged B4; review and approve the contracts, with **no C1 implementation, tests or coding-agent plan**. C2 starts only after C1 merges. |
| **PERF-06-C2** | Implement a specialized strict exact-term executor that validates/enumerates the full match set, preserves exact `total_hits` and retains only competitive Top-K entries. | After C1; no early stop at K, no unvalidated candidate bypass, no general Boolean/typed/phrase expansion without approval. |
| **PERF-06-C3** | Defer BM25 computation and owned result materialization until final winners **only where formally proven safe**, preserving required returned scores and every error/validation obligation. | After C2; use winner-only work when explicit sort is independent of score; relevance sorting and other ineligible shapes keep required scoring. Define score-error precedence before editing code. |
| **PERF-06-C4** | Integrate and independently review C1–C3, run final deterministic/end-to-end correctness and resource gates, then **one approved warm qualification** for the integrated C series. | Final C gate; report the **incremental C gain over accepted A+B** separately from any cumulative PERF-06 change since PERF-05. |

**Dependency graph:** `PERF-05 (merged) → A1 → A2 → A3 → A4 (merged; targets not all met) → A5 → A6 (qualification/acceptance) → B1 → B2 → B3 → B4 (qualification/acceptance) → C1 → C2 → C3 → C4 (qualification/acceptance)`. A and B are architecturally separable concepts, but the default release order is sequential to keep one reviewed baseline and prevent overlapping format/executor migrations. Altering dependencies or PR topology requires a documented maintainer decision.

### Overarching execution and benchmark approach — retained from PERF-05

1. **Plan, then implement.** For every numbered implementation PR, independently freeze exact source anchors, complete architecture, allowed changes and out-of-scope paths, data ownership, errors and validation precedence, scores, resource/cancellation charges, expected tests, and condition→decision→STOP matrix following [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md). Coding agents implement the specified design; they do not select alternatives or redefine contracts.
2. **Correctness-first implementation PRs.** A1–A3, B1–B3, C1–C3 perform focused unit/property/differential/integration tests using mocks, deterministic fake-world fixtures and adversarial inputs. Require independent review and green applicable CI before the next dependency. No real performance campaign, `perf record`, profiler, RustFS bootstrap, Tantivy or Lucene run is automatic during implementation PRs. Tests may exercise a local segment codec/writer when required; do not confuse correctness integration tests with timed benchmarking.
3. **Deep refactors and formats are allowed.** Quervant is pre-customer and not deployed; versioned segment redesigns, breaking internal interfaces and rebuilding indexes are legitimate. Do not impose customer migration or legacy-read compatibility as an unapproved requirement. Still preserve or expressly re-specify query/result semantics, data integrity, snapshot isolation, security, corruption detection, error timing, budget/cancellation, and recovery. Index bytes, index-build cost and memory are recorded separately from warm-query latency.
4. **Benchmark once at each subseries' final PR.** A4, B4 and C4 own consolidated **uninstrumented warm** query acquisition for that subseries against the latest accepted source, with predeclared primary lanes, absent/rare/K10/K100 guardrails, 10K/100K logical corpus where applicable, deterministic oracle, pinned source/build/config, CPU-affinity/readiness, controls, immutable dated results and defined STOP. Source changes after qualification invalidate source-specific claims.
5. **Reuse historical A when sound.** Prefer a previously **qualified, immutable, exact-source** warm baseline and run **only the new candidate B** with same-candidate B/B stability aliases, as PERF-05-C did. Verify workload/semantic equivalence, relevant format-specific effects, compiler/host conditions, time boundaries, control records and historical provenance before reporting **descriptive, unpaired** B/A ratios. No manufactured paired CI and no automatic A execution; if comparability fails, stop for an approved alternative study. The permanent prospective paired-A/B methodology is still available only with a separately approved acquisition and is not silently replaced.
6. **Fail closed and preserve negative evidence.** A failing control or oracle yields an immutable `INCOMPLETE` result and stops; no automatic retuning, block pruning, favorable selective rerun, changed host, threshold relaxation or overwritten artifact. New acquisition after failure requires explicit fresh authorization and separate result identity. All attempts, including failed ones, remain visible in review.
7. **Avoid irrelevant work.** No automatic RustFS start, full three-engine benchmarks, process-cold studies, profiling, Criterion, or full Rust QA repeated after doc/result-only commits. Run applicable real storage/format correctness tests when a substage actually changes those contracts; test fixtures and preflight must be tailored to the change. Profiling is diagnostic only when a separately defined question requires it.
8. **Review and promote deliberately.** A4/B4/C4 present accepted/rejected/inconclusive evidence and explicitly recommend or block adoption. A subseries baseline advances only after correctness/CI, warm qualification, and maintainer acceptance. Do not merge or promote solely because a target flag was favorable.

**Measurement semantics:** PERF-05-C used **B-only warm qualification** of `ee18ed63…` against the separately measured, verified Nov 22 historical Q arm, not same-session A/B and not CPU profiling; it retained an initial unstable `INCOMPLETE` result and a separately authorized `COMPLETE` run ([result `002`](../benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-002.json)). PERF-06 keeps that resource-conscious approach **when its prerequisite comparability proofs hold**. This section authorizes **no new acquisition by itself**.

## PERF-01 — Retained-key prefilter [DONE]

**Delivered behavior.** The unified searcher implements configurable retained-key duplicate checking. Its production default is `TopKDuplicateConfig { min_top_k: 32, strategy: Prefilter }`; `ExactSet` remains separately configurable. Below the configured Top-K threshold the existing bounded linear behavior remains available. The prefilter is a **negative filter only**: a definitely absent key can avoid a duplicate scan, but a possible match still requires exact checking. It must never permit duplicate live document keys, alter top-K ordering, or weaken resource/cancellation semantics.

**Implementation authority:** `crates/quervant-core/src/search/unified.rs` (`TopKDuplicateConfig`, `TopKDuplicateStrategy` and the owned candidate-admission strategy). **DONE describes the implementation**, as explicitly adopted for this milestone. It does **not** retroactively turn the original PR 15I-D3-B measurement branches into qualified performance wins, assert an unobserved current-head speedup, or complete BM-09. The historic D3-B and F1/F1.1/F1.2 blocked/rejected experiments remain recorded without rewriting their dispositions in [ROADMAP.md](ROADMAP.md) and [BENCHMARKING.md](BENCHMARKING.md).

**Resulting baseline rule.** PERF-02 and later must use a source revision whose actual duplicate configuration is declared and verified. Record the default prefilter threshold and any experimental override, and compare like-for-like settings unless the override is the explicit treatment under study.

## PERF-02-A — Quervant warm A/B benchmark readiness [DONE — IMPLEMENTATION]

**Scope:** Extend the merged BM-10 direct runner with a dedicated `benchmarks/studies/perf-02/warm/` family, exactly two Quervant production-default arms (`A` baseline and `B` candidate), each bound to an explicit 40-hex immutable Git commit. A and B are separately compiled with identical release/locked settings, isolated target directories, independent prepared index paths, shared semantics and a common independent correctness oracle. The historical PR15I strategy feature and environment overrides are disabled; PERF-01 remains part of both source revisions' actual production defaults.

**Required framework gates:** preserve BM-10's existing 12-block/2-slot randomized schedule, A/A readiness, warmups, 10K/100K × absent/rare/medium/common × K10/K100 matrix (16 warm lanes), paired whole-block estimator and bootstrap uncertainty, retained raw samples, immutable artifact naming, exclusive result publication, source/host provenance, and fail-closed preparation-cache fingerprinting. No cross-engine binaries or unnecessary startup/throughput qualifications. All framework tests use stubs/mocks; no synthetic timing is presented as a real performance result.

**Host sanity boundary (stage-only):** The same-source A/B configuration pins both arms to the accepted production revision and prepares two separately compiled executables and four distinct committed indexes. On the benchmark host, the operator may run `validate` and `stage`, which checks all 16 declared lanes in both arms with **untimed** correctness oracles. **No `quervant-bench run`, A/A control acquisition, shortened campaign or timed A/B samples are authorized as part of PERF-02-A.** The coding agent was instructed to abort the mistakenly initiated full campaign; do not resume it. Host-stage evidence, if separately collected, must be reported as such, not as a statistically qualified performance result. See the [corrected handoff](pr-artifacts/perf-02-a/REAL_HOST_HANDOFF.md).

**Closeout decision:** **DONE — implementation**, by maintainer direction. The required implementation scope is the reusable warm A/B study, pinned build/prepare path, deterministic framework checks and a bounded stage-only host sanity procedure. A full real-host timed A=A run is **not** an exit criterion. This status does not independently assert a successful host-stage run or final CI jobs without corresponding recorded evidence; report those separately if needed. The first authorized full A/B campaign belongs to PERF-02-B, after a candidate and predeclared measurement contract exist.

## PERF-02-B — Residual sort-value processing [MERGED — PROFILING BLOCKED, PR #116; HISTORICAL RECORD]

**Hypothesis.** After eliminating much of duplicate-key checking, repeated sort-value access, validation, comparisons and sort-key construction may account for the next material portion of candidate-processing cost. The existing five-run D3-A-F2 attribution measured **steady-candidate child shares** for sort views of 23.83% (100K medium/K100), 17.58% (100K common/K100), and 26.26% (100K common/K10). These percentages are **not** end-to-end latency shares or proven removable work, and they predate the fully configured prefilter baseline. [D3-A-F2 five-run data](pr-artifacts/pr-15i-d3a/fixup-f2-five-run-performance.md).

**Prior work to reuse.** PR 15H-B investigated a borrowed keyword sort view with late owned tuples and recorded locally qualified improvements; its implementation and review status must be audited on the exact new baseline before designing anything overlapping. Do **not** implement that same borrowed-`&str` technique a second time, infer that its earlier measurement is a current-head gain, or broaden its eligibility by default. [PR 15H-B qualification](pr-artifacts/pr-15h-b/qualification.md).

**PERF-02-B scope and engineering principle:** **PERF investigations are bounded, bottleneck-driven engineering efforts.** Profiling identifies material contributors to *end-to-end warm-query latency* in the **already identified sort-value processing path**, not a new general search-engine profiling exercise. Optimization work proceeds only when a clearly identified change offers a material, defensible potential benefit. **Microbenchmarking, instruction-level tuning, machine-code instruction ordering, compiler-flag experimentation, and iterative trial-and-error optimization are not objectives.** When the evidence does not justify a bounded implementation, the investigation terminates and the roadmap advances.

**Execution-path boundary:** Focus on `UnifiedSearcher::collect_mixed()` → `consider_borrowed_keyword_candidate()` and the relevant `ColumnReader::keyword_sort_view()` borrowed/fallback paths, sort comparisons, and conditional owned tuple materialization. Include the ordinary owned `sort_tuple_for_doc()` fallback to understand eligible versus fallback traffic. Heap behavior, duplicate detection, and document-key resolution may be recorded **only as nearby context**, not independently optimized under PERF-02-B; postings/scoring, general query planning, heap redesign (PERF-03) and reader caching (PERF-04) are outside this investigation.

**PERF-02-B investigation contract (fixed bounds):**

1. **Establish the warm baseline and denominator.** Inspect existing PERF-01/PR 15H-B behavior and profile the current production Quervant sort-processing path on **100K medium/common at K10 and K100**. Retain absent/rare and 10K cases as cheap contextual/regression guards. Use uninstrumented end-to-end warm latency as the performance reference, not a target for general profiling. Preserve the production default: K10 linear duplicate detection, K100 P2 prefilter.
2. **One focused profiling campaign.** Attribute the path's approximate **exclusive CPU share of whole-query execution** and count candidates examined, path eligibility, borrowed-view usage, legacy fallbacks, rejected-before-materialization candidates, owned sort tuples, and relevant comparisons. Profile at subsystem/function level using sampling and low-overhead aggregate counters; distinguish inclusive/exclusive costs and mandatory validation from plausibly removable work. No per-candidate nanosecond timers or attempt to reconcile every instruction.
3. **At most one consequential diagnostic follow-up.** If the first profile reveals a *material* sort-path hotspot but leaves two plausible causes unresolved, authorize **one narrowly targeted** additional measurement. Criterion microbenchmarks are optional and only when they can resolve that bounded engineering decision. Do not iterate through speculative small changes, repeated microbenchmarks, assembly inspection, branch-predictor tuning, instruction scheduling, or nanosecond-level savings.
4. **Apply a materiality gate before designing code.** Pursue an optimization only if a specific, bounded change has a credible opportunity for **approximately 5% or greater improvement in whole-query warm latency**, preferably more, on representative primary lanes without unacceptable guardrail risk. This ~5% is an *investigation heuristic*, **not** an automatic adoption threshold or a fabricated measured benefit. Predeclare actual statistical acceptance/guardrail criteria separately before any candidate A/B acquisition. A function's high local percentage alone does not prove a removable end-to-end benefit.
5. **Terminate deliberately.** End this investigation with exactly one of `OPTIMIZE` (one named, bounded candidate plus separate design and authorization for implementation), `NO-OPTIMIZATION-REQUIRED` (sort path is no longer material or savings do not justify cost/risk), or `BLOCKED` (precise missing evidence). **Do not implement speculative optimizations to complete the PR.** If a later approved candidate is implemented, evaluate it with the independent, **uninstrumented** `perf-02/warm` A/B study; accept or reject on predeclared whole-query warm performance, not microbenchmark wins. An unsuccessful candidate does not authorize an unbounded series of alternate variants.

**Explicit stop rule:** One focused baseline profile, at most one diagnostic follow-up, and one defensible optimization decision. Stop rather than chasing diminishing nanosecond-scale effects. With PERF-02-B now reporting `BLOCKED`, the next prioritized **new investigation** is PERF-05 physical execution; do not turn PERF-02-B attribution recovery into another campaign.

**Tantivy architectural comparison (source-only; conditional future option).** Tantivy 0.25.0 selects segment-local top-K string-sort candidates by numeric fast-field term ordinal and defers decoding retained strings until segment harvest. Quervant's current `COLUMNS` v1 Keyword representation is per-document variable-length UTF-8 with offset lookup and per-candidate validation; it has no verified equivalent doc-to-ordinal FAST mapping. A Tantivy-style representation is **not a drop-in PERF-02-B comparator fix** and may require a separately approved representation/format, validation and compatibility design. The single qualified 11.6% sampled sort-path CPU lane does not establish removable CPU time or a material warm-query gain; the three remaining lanes are attribution-blocked. Preserve `PERF02B_BLOCKED`, perform no further profiling under this PR, and treat ordinal-based ranking only as a **source-evidenced future hypothesis**, subject to new authorization and evidence. See [PERF-02-B architecture evidence](pr-artifacts/perf-02-b/PROFILE_REPORT.md#11-architecture-evidence-only--tantivy-ordinal-sorting).

Any eventual PERF-02 optimization must preserve byte-exact sort semantics, null/missing/multivalue handling, ties, return scores, ordered keys, cursor/PIT consistency, snapshot immutability, corruption detection, error precedence, work/memory accounting and cancellation. A segment-format change is outside PERF-02 unless separately approved.

## PERF-03 — Heap and remaining candidate processing [DEFERRED — EVIDENCE REQUIRED]

**Hypothesis.** Heap comparisons, worst-candidate checks, replacements and ownership transitions may remain expensive after PERF-01/02. D3-A-F2 recorded heap compare/update steady-child shares of 3.71%, 4.21% and 6.40% in the same three 100K primary lanes. Its separate intermediate matched/scored collection region was below the original materiality gate, and steady candidate materialization was often zero; **do not promote those regions to a major hotspot without fresh evidence**. [Attribution report](pr-artifacts/pr-15i-d3a/fixup-f2-five-run-performance.md).

**Deferred investigation, only if reactivated:** number of candidates examined versus admitted, replacement frequency, key/sort allocation and retention, heap comparison cost, candidate/segment work counters, and any interaction with the prefilter and PERF-02 changes. Use source-observed, non-overlapping cost buckets. **Do not launch profiling or replace the heap based on the historical 3.71–6.40% steady-candidate-child shares alone**: these are not end-to-end percentages, and the cost may already be too small to warrant a change. Reopen only after new credible whole-query evidence supports material potential benefit.

**Guardrails:** no duplicate bypass; preserve complete `total_hits`, exact ordering and ties, failed-admission atomicity, budget/peak accounting, cancellation, and corruption detection. Earlier candidate/materialization and DOC_KEYS-borrowing attempts failed important gates; do not relaunch them unchanged. If the marginal improvement is not material relative to measurement uncertainty and engineering risk, record `NO-OPTIMIZATION-REQUIRED`.

## PERF-04 — Reusable query state and reader access [SECOND — SHORT SOURCE AUDIT]

**Hypothesis.** Recreating validated geometry, per-query metadata and selected-document access structures, or expensive reopen/mutation-state work, may be avoidable in a source- and snapshot-safe way. This requires a clear lifetime/ownership model rather than simply widening a cache.

**Reuse and previous evidence:** PR 15G-A explored immutable column geometry caching; PR 15G-B explored validated lazy STORED/DOC_KEYS offsets, both with recorded favorable local performance evidence and separate completion gates. First inspect which pieces actually exist in the accepted production source and which are test-only or unmerged; **do not duplicate an already delivered cache or assume its historical status is current acceptance**. [Column geometry](pr-artifacts/pr-15g-a/performance-qualification.md) · [reader offsets](pr-artifacts/pr-15g-b/performance-qualification.md).

**Short source audit first; no broad profiling by default:** verify in the accepted baseline that retained `ColumnGeometry` and lazy validated STORED/DOC_KEYS offset directories are already implemented; distinguish query-local from shared immutable state. Then inspect only remaining repeated column/dictionary/record setup, selected-document access, snapshot open/refresh and relevant local/remote cache behavior. State one demonstrably unaddressed, material candidate or terminate with `NO-OPTIMIZATION-REQUIRED`. Do not rebuild previously delivered PR 15G-A/B optimizations or assume their historical speedups recur. Only a separately justified material source finding can authorize one targeted follow-up measurement.

**Required design before any optimization:** specify source/segment/generation/format trust roots, immutable cache ownership, exact resource charging/eviction, safe fallback, corruption of **unselected** records, legacy-format parity, remote RustFS compatibility, and error-order/cancellation behavior. Changes to persistent offsets or segment formats require their own versioned compatibility approval. No silent validation short circuit.

## PERF-05 — Physical execution and postings work [MERGED — PR #117; HISTORICAL RECORD]

**PERF-05-A whole-pipeline reassessment (complete):** [Initial source audit](pr-artifacts/perf-05/PERF05A_SOURCE_AUDIT.md) established the active `UnifiedSearcher` path, and [the authoritative Tantivy/ownership/complexity comparison](pr-artifacts/perf-05/PERF05A_PIPELINE_COMPARISON.md) identifies demonstrable redundancy. A strict one-term posting iterator repeatedly binary-searches the very same postings list through `evaluate_unified` → `LeafData::matches`, and the pipeline constructs full-M `BTreeSet`/`BTreeMap`/`Vec` intermediates and re-traverses postings for scores. Separately, snapshot live metadata is scanned O(N) several times. **The next objective is to remove these proven sources of waste through small, correctness-preserving changes**, not to obtain a pre-change CPU-cost estimate. The historic D3-A-F2 intermediate-region measurements (0.230869 ms/1.23% medium/K100, 0.987877 ms/2.21% common/K100) cover only one disjoint region, cannot dismiss all pipeline inefficiency, and are not estimates of future gain.

**PERF-05 executed disposition (supersedes the original plan):** All **B1–B5** implementations were completed with focused, correctness-first testing and independent review on [PR #117](https://github.com/yduchesne/quervant/pull/117), now merged. **PERF-05-C** used a final **B-only warm acquisition with historical, unpaired A comparisons**, not the originally described contemporaneous A/B or CPU profiling. The first B/B attempt failed one stability lane and remains immutable `INCOMPLETE` ([result `001`](../benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-001.json)); a separately authorized second run qualified **16/16 B/B lanes, 4/4 primary improvement targets, 12/12 guardrails** ([result `002`](../benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-002.json)). These are between-session descriptive improvements without paired intervals. No profiling or RustFS acquisition was required for PERF-05-C. The original investigation questions and negative-evidence notes below are retained as **historical design context**, not still-pending PERF-05 work.

**Original investigation question (now audited):** Does the present high-hit exact-term execution pipeline perform materially avoidable intermediate work? Inspect `crates/quervant-core/src/search/execute.rs` (`TermPostings`, `match_set`, `score_segment`, `evaluate_lexical_with`) and `search/unified.rs::collect_mixed`, especially postings → matched `BTreeSet` → scored `BTreeMap` → result `Vec` → final candidate retention. Separate exact-count/predicate/validation/budget work that must continue from avoidable intermediate allocations or traversals. The goal is a **bounded, source-evidenced physical execution opportunity affecting end-to-end warm latency**, not general profiling of the search engine.

**Mandatory negative-evidence reconciliation before proposing anything:** The historical [architecture/evidence index](PERF_OPTIMIZATION_PLAN.md) records rejected/rolled-back PR 15G-C/D, PR 15H-A/A2 streaming/linear candidate work, and PR 15I-C physical executor. Read their concrete acceptance failures (notably low-hit regressions and correctness/resource gates) and state **what substantially different mechanism** would avoid repeating them. No existing candidate can be revived unchanged, and no "try a different collection type" implementation is authorized by source inspection. If a proposed refactor cannot preserve correctness, logical work/memory budgets, error precedence or low-hit behavior, stop and redesign or reject **that refactor**; absence of an estimated ≥5% gain is not itself a reason to retain source-proven duplication.

**Hard invariants:** exact `total_hits`, sorted results/ties, complete predicate evaluation, corruption detection even in unselected data as required, duplicate-key checks, budgets and logical resource charging, cancellation, scoring returned hits, cursor/PIT and snapshot stability, low-hit guards, and safe fallback for other query shapes. **Do not assume** that a scoring shortcut (including block-max/WAND) applies to an exact-count, explicit-string-sort workload.

**Deferred PERF-05 subproblems (not part of the first investigation):** block-oriented postings/skips, compression/SIMD, new fast-field/dictionary layouts (including ordinal keyword sorting), index footprint and local/RustFS access strategy. These are **independent architectural questions**, not a single rewrite. Any index-format change, mmap assumption, remote-range strategy or migration requires separate validation, compatibility, correctness and RustFS portability approvals. Historical compact-dictionary/persistent-offset approaches that failed whole-index or sparse-query gates cannot be reused without a materially new design.

**Standalone conditional feasibility — ordinal sorting (third in priority):** Tantivy 0.25.0 ranks per-segment string fast-field values by numeric ordinals and decodes retained strings later. Quervant currently uses variable-length UTF-8 keyword values with per-candidate validation; no matching ordinal mapping is proven. A later **source-only** study must consider ordered dictionary representation, per-document lookup, byte-exact cross-segment semantics, null/missing/multivalue handling, corruption/error precedence for unselected records, work/memory budgets and legacy-segment/remote compatibility. This is *not* an approved PERF-02-B optimization, nor an approval to change any persistent format. See [PERF-02-B source comparison](pr-artifacts/perf-02-b/PROFILE_REPORT.md#11-architecture-evidence-only--tantivy-ordinal-sorting).

## Measurement and decision contract for PERF-02 onward

**PERF-06 interpretation:** the prospective paired-A/B rules below apply when an A/B study is explicitly chosen; PERF-06's default resource-conscious qualification is the separate B-only/B-B-with-verified-historical-A approach defined above. Do not blend estimators or infer causality from cross-run medians.

1. **Use BM-10's direct methodology, not abandoned BM-09 acceptance.** Use the current production default as A (including PERF-01), a properly versioned prospective candidate study and controlled source/build/workload/host context. Ensure the needed benchmarking implementation and actual qualification evidence are available for this particular study before any adoption; BM-09 archival receipts/attestations or a BM-09 completion gate are **not** prerequisites. Do not alter an earlier benchmark configuration or claim synthetic data are real evidence.
2. **Define each warm optimization experiment before timing.** PERF-02-A provides a **prospective paired A/B** facility, while PERF-05-C demonstrated a dedicated **B-only + B/B stability + immutable historical A** facility. PERF-06-A4/B4/C4 must each select and document one legitimate methodology and create a new named/versioned configuration with pinned source identities; never reuse an unrelated study's name/UUID or imply an old baseline still matches a new workload. Freeze target lanes, guardrails, estimator, controls and STOP rules before acquisition.
3. **Predeclare the warm selection contract before timing.** A is the latest accepted source immediately before the particular change (including all earlier accepted PERF subseries); B adds only the new candidate. Record exact Git SHAs, compiler/build options, host, corpus, warm lanes, selectivity/Top-K guards, schedule, estimator, statistical/stability thresholds and readiness/stop rules. Require an independent correctness oracle and **appropriate equivalent-build controls**: A/A for prospective paired A/B; B/B for candidate-only runs against historical A. Only qualified warm-query observations enter the decision, and a historical decision is explicitly descriptive.
4. **Use the estimator belonging to the approved experiment.** For prospective, contemporaneous A/B, randomize and position-balance both arms in the same blocks and use paired block ratios/bootstrap intervals; never manufacture pairing or apply selective pruning. For **B-only** historical reference, qualify independently measured B using B/B controls, preserve every attempt, and compute historical-relative ratios from independently validated absolute medians **only for comparable workloads**; label them unpaired and report **no historical paired CI or causal attribution**. Document context differences and any comparability blocker, and stop when it fails.
5. **Protect correctness and negative cases.** Test absent/rare/medium/common selectivity, K boundaries, missing and duplicate keys, corruption in selected/**unselected** records, tombstones, refresh/merge/reopen, PIT/cursor pagination, typed/JSON/geo/aggregate fallbacks, saturation, overflow, cancellation and memory budget release. Reject a faster result that violates any nonnegotiable semantic boundary.
6. **Preserve versioned configuration and result JSON.** Store each immutable configuration at `benchmarks/studies/<family>/<regime>/configurations/` and its non-overwriting result JSON in the sibling `results/` directory, following the [permanent naming convention](BENCHMARKING.md#permanent-study-directory-hierarchy). Preserve raw samples, arm/source/host context, A/A outcomes, the warm analysis, uncertainty and acceptance decision. Read-only `analyze` may recalculate statistics from the stored sample data; `report`/`replay` only render saved analysis. No repeated independent certification replay, sealed evidence, third result artifact or fresh timing is required for this presentation/reanalysis. Never overwrite existing evidence or substitute synthetic controls for a real campaign.
7. **Choose query optimizations solely by qualified warm effects.** Each PERF query-optimization PR must end with `ACCEPTED`, `REJECTED_ROLLED_BACK`, `INCONCLUSIVE`, `NO_OPTIMIZATION_REQUIRED`, or `BLOCKED`, grounded in correctness, resource/safety checks and **predeclared warm query improvement/guardrail criteria**. Cold-start latency and `index_open_ns` are **separate diagnostics**, not tie-breakers, compensating benefits or positive evidence of warm optimization value. Report any cold regression or explicit operational limit breach for separate review; do not silently suppress it. A project targeting startup/reader-initialization overhead specifically must define a **different** measurement/acceptance contract; it cannot be relabeled a query optimization. Include actual commands, tested revision and proof of restoration where relevant. Do not auto-promote or selectively rerun to seek a favorable outcome.

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

`v0.1-perf` is **not DONE** merely because PERF-01 and PERF-05 have been merged. An approved set of remaining investigations must receive reviewable dispositions. Each adopted A/B/C subseries must satisfy independent correctness, **same-run stability controls and the chosen approved warm qualification methodology**, applicable Rust stable/MSRV/coverage/CI and relevant storage tests, immutable data, and read-only reanalysis. A qualified **historical B-only** comparison does not equal a same-session paired A/B result. RustFS is required only for work whose affected storage/remote contracts justify it, not automatically for unrelated query or documentation changes. Cold-start and index build metrics are separate diagnostics. Preserve failures and no-change outcomes without relabeling them.

Advance each table status only after its required gate and human review. Keep `docs/ROADMAP.md` and this register aligned at milestone boundaries; leave earlier immutable qualification and historical PR reports unchanged.

## PERF-06-B1 amendment (current status, 2026-11-24)

> **Superseding status note.** A6 is user-accepted and merged (PR #125); the A6
> numerical misses recorded above remain unchanged and are not relabelled. An
> approved B1 execution plan now exists
> ([detailed plan](pr-artifacts/perf-06-b/PERF06B1_DETAILED_PLAN.md)) and the
> implementation is recorded in
> [the B1 execution report](pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md).
> B1 now delivers the persistent segment representation, bounded local access and
> the snapshot-wide numeric map foundation; **B2 owns collector adoption**, B3
> owns document/duplicate identity and B4 owns the warm qualification. B1 is not
> an accepted or measured performance win.

B1 does not run or re-label any A6 acquisition, does not change the benchmark
framework, thresholds or configurations, and does not claim latency, RSS or
whole-index size improvements. Its evidence is correctness, exact wire bytes,
structural size formulas and real local/remote lifecycle integration.

## PERF-06-B2 amendment (current status, 2026-11-25)

> **Superseding status note.** B1 is accepted and merged (PR #126, merge commit
> `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`; the reviewed B1 executable source
> `ad66e5e833616bafaaa97e15d89cdc511d715868` is an ancestor). Its unfavorable or
> structural-only evidence is unchanged. B2 implements the collector adoption of
> the B1 foundation per
> [the B2 detailed plan](pr-artifacts/perf-06-b/PERF06B2_DETAILED_PLAN.md) and
> records results in
> [the B2 execution report](pr-artifacts/perf-06-b/PERF06B2_EXECUTION_REPORT.md).

B2 ranks eligible strict single-term single-field `Keyword` sorts by
snapshot-wide numeric ordinals in the existing global Top-K heap, with raw-UTF-8
value order, missing/null placement, logical-key ties, exact `total_hits`, score
bits, projections, duplicate checks, resource admission and owned string cursor
tuples preserved. Ineligible shapes and B1 `NotAvailable` outcomes keep the
original string/typed path; B1 corruption/cancellation errors remain typed. B2
changes no index bytes, storage, public query/cursor contract, CI topology or
benchmark configuration, and performs no timing acquisition. **B2 is not a warm
performance, footprint or RSS result.** B3 (document identity) and B4 (cumulative
correctness plus separately approved warm qualification) remain pending; the A6
remote-compaction publication residual is unchanged.

## PERF-06-B4 amendment (current status, 2026-11-25)

> **Superseding status note.** B2 is accepted and merged (PR #127, merge commit
> `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2`), and B3 is accepted and merged
> (PR #128, merge commit `d660ca9f487d5c54363d790a240abb7da30af245`; the reviewed
> B3 executable source `52d7e69f40759f27be79434118c47171b06702b7` reaches `main`
> unchanged, with only documentation/evidence commits after it). Their evidence is
> unchanged. B4 then ran **one** paired cumulative warm qualification of B1+B2+B3
> against the last accepted pre-B1 source, per
> [the B4 detailed plan](pr-artifacts/perf-06-b/PERF06B4_DETAILED_PLAN.md), with
> results in [the B4 execution report](pr-artifacts/perf-06-b/PERF06B4_EXECUTION_REPORT.md).

B4 is a **measurement/qualification** PR: it adds no engine optimization. Its only
product change is a narrow, PERF-06-only benchmark-tool capability that preserves
real host-load observations (`policy.readiness.mode="advisory"`, creation-only
`prepare --readiness-advisory`) while leaving the original 25%/2% ceilings, the
structural host prerequisites and the A/A equivalence control fully binding for
every other family and every historical configuration.

Acquisition identity: configuration
`quervant-perf06b4-paired-warm-2026-11-25.json` (`4608c79a-c5a3-4d24-bec9-4ad61cd7bd94`),
A `480a77e78c6897e05cb7ceb76b01434974b82ec6` vs B `d660ca9f487d5c54363d790a240abb7da30af245`,
16 warm lanes, 12 randomized paired blocks × 2 slots × 5+20, seed `20261122`,
10,000 whole-block bootstrap, `exclude_blocks={}`; one result
`quervant-perf06b4-paired-warm-2026-11-25-001.json` (`run_id`
`86fe9601-2574-4335-a673-63de7d0dcc26`), status `COMPLETE`, 16/16 A/A PASS, all
per-sample oracles exact, host readiness observed `clear` at every checkpoint
(informational).

Frozen B4 policy applied to the stored, unrounded values: **4/4 primaries** passed
(`100000/{common,medium}/k{10,100}`: +24.873% to +35.819%, each `IMPROVED` with a
positive lower CI bound) and **12/12 guards** passed (worst point −2.685%, worst
lower bound −3.570%, all inside the −10% bound). Disposition:
`PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`.

The observed effect is **cumulative B1+B2+B3 on this host/configuration**, per
lane; it is not a universal Quervant speedup, not a cross-engine ranking and not a
per-stage causal attribution. The small absent/rare regressions (within ~2.7%) stay
reported. Writer/commit/reopen/byte differences are descriptive untimed
diagnostics, not warm latency and not a compaction or RSS result. **G10 remains
maintainer-owned:** B4 does not merge, does not promote the B-series baseline, does
not start PERF-06-C1, and leaves the historical 15H-C / 15I-D1-F rejections and the
A-series outcomes intact.


## PERF-06-C1 documentation-only handoff (2026-11-25)

B4 is **accepted and merged** in [PR #129](https://github.com/yduchesne/quervant/pull/129) at `main@8c9f51f311afa5b327f70432e32c0f6f5c205eab`. Historical B4 execution notes above retain their original contemporaneous `G10 OPEN` wording and are not rewritten as if acceptance preceded review.

The maintainer selected a **documentation-only C1 PR**, rather than a coding-agent plan for a non-implementation stage. [The C1 physical-execution contract](architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md) freezes strict-term/keyword Top-K eligibility, request-local dispatch, B1–B3 reuse, exact-count and score obligations, virtual accounting/error ordering, optional-fallback rules, and the safe-deferred-scoring proof boundary. [The C1 source audit](pr-artifacts/perf-06-c/PERF06C1_SOURCE_AUDIT.md) reconciles the current accepted strict-postings path against rejected PR 15H-A/A2 and 15I-C. **No C1 runtime/test change or warm benchmark is claimed.**

C2 remains the first executor implementation PR, C3 is a separate guarded scoring implementation, and C4 is the next performance qualification. C1 approval/merge is maintainer-owned; the C1 draft does not authorize a coding agent to implement C2 or C3 without separate detailed plans and acceptance.
