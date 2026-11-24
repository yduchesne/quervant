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

## 5. Current-status amendment (PERF-06-A4 and PERF-06-A5)

Sections 1–4 above remain the historical series-opening charter; A1–A4 were
authorized afterwards under separate detailed plans and this amendment records the
resulting state. It does not rewrite the earlier authorization text.

| Stage | Status | Boundary |
| --- | --- | --- |
| **PERF-06-A1** | Merged; implemented | Query-local BM25 preparation retained; score contract unchanged. |
| **PERF-06-A2** | Merged; implemented | Consuming document/frequency-only cursor retained; shared validation, ownership, cancellation and limits unchanged. |
| **PERF-06-A3** | Merged; implemented | Versioned split postings v1 retained as the long-list representation. |
| **PERF-06-A4** | Merged (PR #123) with measured `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` | Complete second paired campaign: 16/16 A/A controls and 12/12 guards passed; 2/4 primary lanes met the ≥5% target. Merge is not evidence that every original target passed; the disposition is unchanged. |
| **PERF-06-A5** | `IMPLEMENTED — INDEPENDENT REVIEW PENDING` | `FEATURE_ADAPTIVE_POSTINGS = 0x000F/1`; compact framing for `df <= 128`, unchanged A3 payloads for `df >= 129`; one-buffer compact encoding with fused validation/size accounting; shared lazy full/lean decoder; both producers emit the adaptive family; legacy/A3 readers retained. Correctness and structural footprint only: no latency, writer-cost or real index-size claim. |
| **PERF-06-A6** | `PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED` | Consolidated A-series compatibility, storage and warm-performance qualification. Must include a genuine complete A3-produced (E) index appended/compacted by A5, real frozen-corpus index sizes, and writer diagnostics. Not authorized by A5. |

**Dependency:** `A1 → A2 → A3 → A4 (merged, targets not all met) → A5 → A6 → B1 → B2 → B3 → B4 → C1 → C2 → C3 → C4`.

A5 authorizes no benchmark acquisition, no A4 rerun, no threshold retuning, and no
merge. A6 must define its own source pins, corpus/schema, result identity,
acceptance criteria and acquisition count. See
[A5 detailed plan](PERF06A5_DETAILED_PLAN.md) and
[A5 execution report](PERF06A5_EXECUTION_REPORT.md).

**Series disposition now:** `PERF06_A5_IMPLEMENTED_INDEPENDENT_REVIEW_PENDING`.

## 6. Current-status amendment (PERF-06-A6)

Sections 1–5 remain the historical charter and the A4/A5 amendment above. A6 was
authorized afterwards by its own detailed plan and executed against
`main@3bb232f868cb556ce9b4273d902164c65416af0f`, with the user explicitly treating
main as stable and waiving unit/integration/QA/CI-wait activity for that task.
A6 changed no production, adapter, harness, manifest, toolchain or workflow file.

| Stage | Status | Boundary |
| --- | --- | --- |
| **PERF-06-A6** | `PERF06_A6_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` | Complete, replay-verified paired warm evidence for both predeclared campaigns, measured whole-index bytes with both byte gates met, and four descriptive writer observations. G2/G3 (genuine native and real-RustFS E→F compatibility) were completed by the A6-F1 continuation after an initial driver compile defect: all six modes passed against genuine E-produced bytes, native compaction to one F segment at generation 3, held PITs, immutable-object survival and separate-process remote cold reopen. One of sixteen A5 retention lanes and two of four cumulative primary lanes remain below their frozen thresholds, so A6 is targets-not-met, not review-ready. Remote compaction publication remains unqualified. |

A6-F1 (compatibility continuation) corrected only the supplied driver's SHA-256
hexadecimal serialization, rebuilt the example at E and F, and executed the six
previously unstarted modes: three native (`create-e`, `advance-f`, `verify-f`) and
three real-RustFS (`remote-create-e`, `remote-append-f`, `remote-verify-f`). All six
exited 0 with terminal PASS, so G2 and G3 now pass; the task-owned RustFS
container and its anonymous volume were removed afterwards. No warm acquisition,
staging invocation, writer observation, general suite, quality check or CI wait
occurred in F1, and host stability was advisory and non-blocking by explicit user
instruction.

A6 measured outcomes that must not be restated as accepted wins:

- Isolated A5 retention (A3/E → A5/F): 15/16 lanes inside the frozen retention
  budget; the single NOT_MET lane is `10000/absent/k10` at −2.122% (INCONCLUSIVE).
- Cumulative A-series (A0 → F): 2/4 primary lanes reach the 5% target
  (`100000/common` K10 +6.2%, K100 +5.4%); `100000/medium` K10 +3.1% and K100
  +3.4% remain below target; 12/12 guards pass; no lane regressed.
- Whole-index bytes: 38.19% (10K) and 37.95% (100K) smaller than E, ~6.6% below
  A0; the historical `90·(N+1)` saving model closed exactly (MODEL_CONFIRMED).
- Writer observations are four single-run descriptive process samples with no
  acceptance threshold; they are not statistically qualified write benchmarking.
- Remote compaction publication is **NOT QUALIFIED** and remains a
  maintainer-owned residual; A6 does not broaden the remote lifecycle claim.

A6 also does not reopen A4's stored `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`
verdict, does not correct the pre-merge F1 report discrepancies, and does not
require or claim any CI result. See
[A6 detailed plan](PERF06A6_DETAILED_PLAN.md),
[A6 execution report](PERF06A6_EXECUTION_REPORT.md) and
[A6-F1 continuation instructions](PERF06A6_F1_CONTINUATION_INSTRUCTIONS.md).

**Dependency:** `A1 → A2 → A3 → A4 (merged, targets not all met) → A5 (merged) →
A6 (executed; compatibility qualified, numerical targets not all met) → B1 → B2 →
B3 → B4 → C1 → C2 → C3 → C4`.
**B1 remains blocked** pending maintainer disposition of A6.
