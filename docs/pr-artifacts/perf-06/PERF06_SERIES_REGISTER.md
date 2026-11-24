# PERF-06 — Optimization Series Register

**Status:** SERIES STRUCTURE AGREED — INDIVIDUAL DESIGNS AND EXECUTION NOT YET AUTHORIZED  
**Milestone:** `v0.1-perf`  
**Repository:** `yduchesne/quervant`  
**Planning branch / PR:** `dev/perf06-optimization-series` / [draft PR #118](https://github.com/yduchesne/quervant/pull/118)  
**Starting source:** `main@a7011fbe45c3715333b2de8864a49aedba240417` (merged PERF-05 PR #117)  
**Canonical roadmap:** [`docs/PERF_OPTIMIZATION_ROADMAP.md`](../../PERF_OPTIMIZATION_ROADMAP.md#perf-06--architectural-efficiency-series-planned-no-implementation-authorized)  

## 1. Agreed organizational decisions

PERF-06 consists of **three engineering subseries**, ordered **A → B → C**. Each has **four planned, separately reviewable PRs**: three bounded implementation/design steps followed by a **consolidated correctness and warm-performance qualification PR**. The stage IDs describe **planned work**, not GitHub PR numbers, created PRs, code already implemented, or blanket approval to begin coding.

| Subseries | Planned individual PRs | Deliverable | Prerequisites |
| --- | --- | --- | --- |
| **PERF-06-A — Scoring and postings efficiency** | A1: Precomputed BM25 term weights; A2: doc/frequency-only decoder; A3: separated, versioned postings layout; A4: integration/correctness/warm qualification | Efficient scoring/postings primitives | Merged PERF-05 baseline |
| **PERF-06-B — Fast-field and document identity** | B1: persistent keyword ordinals; B2: ordinal sort/segment merge; B3: compact key + duplicate identity; B4: integration/correctness/warm qualification | Efficient immutable sort/identity structures | Accepted A |
| **PERF-06-C — Integrated physical executor** | C1: physical plan and contracts; C2: exact-count/Top-K executor; C3: deferred scoring and materialization where safe; C4: integration/correctness/warm qualification | Specialized executor using A and B | Accepted A+B |

**Dependency chain:** `PERF-05 (merged) → A1 → A2 → A3 → A4 → B1 → B2 → B3 → B4 → C1 → C2 → C3 → C4`. A and B address different technical subsystems, but sequential landing is the default to avoid overlapping incompatible changes and give C one stable dependency baseline. Changing the order requires a separate maintainer decision.

**PR topology:** PR #118 is **planning and documentation only**. A1–A4, B1–B4, C1–C4 each become a separate PR after their exact design is approved. No implementation is automatically authorized by this register. Avoid carrying unreviewed code across PR boundaries.

## 2. Overarching engineering approach — retained from PERF-05

1. **Identify and remove source-proven waste, without speculative benchmark prerequisites.** Redundant allocations, repeated calculations, unnecessary decoding and structurally inferior physical operations can justify a design without predicted speedup or a materiality-profiling expedition. Real warm measurements are required **to accept the completed subseries**, not to permit an already justified code design.
2. **Prescribe the design before invoking a coding agent.** Each PR must have a detailed, source-anchored design using at least `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`. Specify exact ownership/data flow, allowed files, tests, budget and error obligations, source SHAs, success criteria, predefined exception matrix, and HARD STOP for anything unanticipated. The coding agent must not improvise architecture.
3. **Use correctness-first PRs and independent reviews.** A1–A3, B1–B3, and C1–C3 use mocked, synthetic, property-based and adversarial tests, relevant codec/writer/reader fixtures, and applicable CI. Assess negative evidence from earlier rejected designs. No real benchmark, profiling acquisition, RustFS startup, cross-engine benchmark, or unneeded full QA cycle just to complete an implementation step.
4. **Qualify only once per completed subseries.** A4, B4 and C4 each own a separately approved, pinned **warm query** qualification of the cumulative change plus comprehensive final correctness/CI gates. A/B/C promote an accepted baseline only after maintainer review. Preserve source/build/test provenance and unmodified evidence, including failures.
5. **Prefer historical A reuse when scientifically comparable.** As in PERF-05-C, do not automatically rebuild or rerun A when a completed, qualified, immutable warm baseline result exists for the **exact relevant source and logically equivalent workload**. Instead run the **new B only**, using randomized `BB`/`BB2` stability aliases of the same candidate executable, full oracles and host-readiness checks. Verify historical A source, configuration, host/build conditions, cache regime, sort semantics and corpus comparability; compare absolute medians descriptively. No paired A/B confidence intervals or source-only causal claims from cross-session measurements.
6. **Fail closed on uncertainty.** If historical comparability fails (for example after a material format/workload change), do **not** adapt or fabricate the old A; STOP and request a separately approved new benchmark design. If B/B stability or correctness fails, publish an immutable `INCOMPLETE` result and STOP; no automatic rerun, block omission, retuning, threshold relaxation or result replacement. A further acquisition requires explicit new authorization. If causality is required, approve a contemporaneous paired A/B study separately.
7. **Avoid irrelevant work.** Do not start RustFS, run Tantivy/Lucene, process-cold benchmarks, Criterion, `perf` profiling or full Rust QA merely because PERF-05 used them in some earlier phase. Run specifically relevant real-storage/codec/remote correctness tests when a new format or reader contract actually requires them. Keep untimed index construction separate from query latency, and distinguish index footprint/write cost from warm performance.
8. **Allow deep refactoring and reindexing.** Quervant has no production customers. Breaking internal interfaces and shipping a new versioned on-disk representation are valid design options, without a presumed customer migration obligation. However, integrity, exact result counts/order/scores where promised, duplicate suppression, corruption detection, snapshot/PIT/cursor, resource/cancellation bounds and security remain mandatory unless a deliberate contract revision is expressly approved. Deep changes do not reduce the need for tests.

**PERF-05 evidence used as precedent:** PR #117 merged B1–B5; PERF-05-C's first B-only acquisition failed one `BB`/`BB2` stability lane and was preserved as `INCOMPLETE`. A separately authorized second B-only acquisition passed 16/16 controls and all declared historical-relative primary/guard thresholds. That was a **descriptive, unpaired** comparison against a separately measured historical source, not a contemporaneous paired A/B or profiler campaign. See [PERF-05-C `002` result](../../../benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-002.json). It does **not** mean that future results with materially different datasets/index behavior automatically inherit comparability.

## 3. Still undecided — require detailed PR design

| Decision | State |
| --- | --- |
| Subseries names, high-level targets, order, and A1–C4 IDs | **AGREED** |
| Implementation of each algorithm, code anchors, APIs and ownership | UNDESIGNED / NEEDS APPROVAL |
| Format versions, dictionary/ordinal geometry, migration/reindex steps | UNDESIGNED / NEEDS APPROVAL |
| Validation trust boundaries and intentional semantic/error policy changes | UNDESIGNED / NEEDS APPROVAL |
| Per-PR allowlists, unit/negative-case tests and acceptance gates | NOT FROZEN |
| A4/B4/C4 exact target lanes, historical source identities, statistical/BB stability thresholds | NOT FROZEN |
| Whether any stage needs real storage integration testing or additional profiling | NOT AUTHORIZED BY DEFAULT |
| Fallback when historical measurements cannot support comparison | STOP FOR NEW AGREEMENT |

**No code or performance acquisition authorization:** agreeing on series topology is not agreement on individual architecture, implementation, benchmark thresholds, merge decisions or result claims.

## 4. Approval and handoff contract

1. Independently review the current repository source and historical rejected approaches before designing **A1**. The next implementation detailed plan must specify exact edits, invariants, test cases, and fail-closed decisions; follow the authoring guide as a minimum. Never ask a low-reasoning coding agent to design missing parts.
2. Create the implementation PR only after the maintainer authorizes its plan. Keep each PR's diff/review bounded; merge accepted dependencies in the agreed order.
3. After A1–A3, separately authorize **A4** qualification; only after accepted A4 proceed to B1. Likewise B4 before C1, and C4 concludes the cumulative series.
4. Record both qualified and failed attempts immutably; do not mutate previous configurations/results or quietly rewrite historical outcomes.
5. Keep planning PR #118 in draft until its planning closeout decision; implementation PRs are separate and remain uncreated as of this register.

## 5. Scope of this planning update

This is a documentation-only agreement: update **this register** and `docs/PERF_OPTIMIZATION_ROADMAP.md`, correcting PERF-05's merged status and documenting the PERF-06 sequence and operating model. Do not change `docs/ROADMAP.md` yet; do not touch Rust/Python code, CI, benchmark configurations/results, or PERF-05 artifacts. Do not run any real benchmarks or profiling.

**Next authorized work:** refine and approve the **PERF-06-A1** detailed design. No implementation has begun.

## 6. Current-status amendment (PERF-06-A5)

This amendment records later facts; it does not rewrite the original authorization
above. Sections 1–5 remain the historical series-opening agreement.

A1–A3 remain retained. A4 PR #123 is merged; its complete second paired campaign
met two of four primary targets and all guards, with no lane classified as
regressed. The measured targets-not-met disposition remains historical evidence.
A5 addresses short-list postings metadata and correctness/structural footprint.
A6 is a separately planned consolidated compatibility/storage/warm-performance
qualification before B1. No A6 acquisition is authorized by A5.

| Subseries | Status now | Notes |
| --- | --- | --- |
| **PERF-06-A** | A1–A3 merged; A4 merged with `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`; A5 `IMPLEMENTED — INDEPENDENT REVIEW PENDING`; A6 `PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED` | A5 adds `FEATURE_ADAPTIVE_POSTINGS = 0x000F/1` compact framing for 1–128-document terms, retains split/A3 payloads for longer lists, and wires both the segment builder and compaction to the same encoder. A6 owns genuine complete E-index compatibility, real benchmark-corpus index sizes and warm qualification. |
| **PERF-06-B** | Still blocked | B1 (persistent keyword ordinals) remains pending A6 evidence and maintainer disposition. A5 does not absorb B1. |

**Dependency chain:** `PERF-05 (merged) → A1 → A2 → A3 → A4 (merged, targets not
all met) → A5 → A6 → B1 → B2 → B3 → B4 → C1 → C2 → C3 → C4`.

**Status vocabulary:** `IN_PROGRESS`, `IMPLEMENTED — VERIFICATION_BLOCKED`,
`READY_FOR_INDEPENDENT_REVIEW`, `ACCEPTED — IMPLEMENTATION`,
`PLANNED — SEPARATE DESIGN/ACQUISITION REQUIRED`. A5 does not merge, retune A4's
thresholds, or authorize any performance acquisition. See
[A5 execution report](../perf-06-a/PERF06A5_EXECUTION_REPORT.md).

## 7. Current-status amendment (PERF-06-A6)

This amendment records the executed A6 qualification; sections 1–6 remain the
historical planning agreement and the A5 amendment.

| Subseries | Status now | Notes |
| --- | --- | --- |
| **PERF-06-A** | A1–A3 merged; A4 merged with `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`; A5 merged at `3bb232f868cb556ce9b4273d902164c65416af0f`; A6 executed with `PERF06_A6_VERIFICATION_BLOCKED` | A6 delivered two complete, replay-verified paired warm campaigns, measured whole-index byte gates (both met; F is 38.2%/38.0% smaller than E and below A0), and four descriptive writer observations. Genuine native and real-RustFS E→F compatibility (G2/G3) are unqualified because the frozen A6 qualification driver does not compile at either pinned arm; remote compaction publication stays a maintainer-owned residual. |
| **PERF-06-B** | Still blocked | B1 (persistent keyword ordinals) awaits maintainer disposition of A6 evidence and the qualification residuals. A5 and A6 do not absorb B1. |

A6's numeric outcomes as measured, not as accepted wins:

- Isolated A5 retention (E→F): 15/16 lanes inside the frozen retention budget;
  `10000/absent/k10` is the single NOT_MET lane at −2.122%.
- Cumulative (A0→F): 2/4 primary lanes meet the 5% target (`100000/common` K10
  +6.2%, K100 +5.4%); `100000/medium` K10 +3.1% and K100 +3.4% fall short;
  12/12 guard lanes pass and no lane regressed.
- Historical `90·(N+1)` byte model: MODEL_CONFIRMED exactly at both sizes.
- Writer resources: four single-run descriptive observations, no threshold.

A6 required no baseline/regression suite, QA or CI wait under an explicit user
instruction for that task only; nothing in this register turns that exception into
permanent policy, and no unqualified capability is described as implemented. See
[A6 execution report](../perf-06-a/PERF06A6_EXECUTION_REPORT.md).
