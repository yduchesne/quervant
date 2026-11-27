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
| **PERF-06-C — Integrated physical executor** | C1: **documentation-only** physical plan and source/evidence contracts; C2: exact-count/Top-K executor; C3: deferred scoring and materialization where proven safe; C4: integration/correctness/warm qualification | Specialized executor using A and B | Accepted A+B |

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
| **PERF-06-A** | A1–A3 merged; A4 merged with `PERF06_A4_PAIRED_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED`; A5 merged at `3bb232f868cb556ce9b4273d902164c65416af0f`; A6 executed with `PERF06_A6_COMPLETE_TARGETS_NOT_MET_REVIEW_REQUIRED` | A6 delivered two complete, replay-verified paired warm campaigns, measured whole-index byte gates (both met; F is 38.2%/38.0% smaller than E and below A0), and four descriptive writer observations. Genuine native and real-RustFS E→F compatibility (G2/G3) were completed by A6-F1: all six modes passed after correcting only the driver's digest serialization. One of sixteen retention lanes and two of four cumulative primary lanes remain below their frozen thresholds; remote compaction publication stays a maintainer-owned residual. |
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
permanent policy, and no unqualified capability is described as implemented. The
A6-F1 continuation executed the six compatibility modes that the initial attempt
could not start (three native, three real-RustFS), all passing, and introduced no
benchmark acquisition, staging invocation, writer observation or quality check.
Host stability observations during F1 were advisory and non-blocking by the same
explicit user instruction. See
[A6 execution report](../perf-06-a/PERF06A6_EXECUTION_REPORT.md).

## PERF-06-B1 status amendment (2026-11-24)

The historical "B1 blocked" statements above predate the user's explicit
acceptance/merge of A6 (PR #125) and the subsequent approved B1 execution plan.
Current dependency and status reconciliation:

* **A6:** user-accepted and merged; unfavorable numerical evidence unchanged.
* **B1:** implementation of the persistent keyword-ordinal codec, bounded local
  access and the snapshot-wide numeric map foundation. Gates are recorded in
  [PERF06B1_EXECUTION_REPORT.md](../perf-06-b/PERF06B1_EXECUTION_REPORT.md).
  **Not accepted before independent maintainer review (G10 remains open).**
* **B2:** query-collector adoption of the B1 foundation — separate plan.
* **B3:** document-key/duplicate identity — unchanged scope.
* **B4:** cumulative correctness plus the separately approved warm
  qualification — unchanged scope.

This register does not mark PERF-06-B done, does not describe B1 as a performance
result and does not promote an unreviewed branch into the B2 dependency.

## PERF-06-B2 status amendment (2026-11-25)

Sections above remain the historical planning agreement. Current facts:

* **A6:** accepted/merged; numerical misses unchanged.
* **B1:** accepted and merged (PR #126, merge commit
  `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`); reviewed executable source
  `ad66e5e833616bafaaa97e15d89cdc511d715868` is an ancestor of `main`.
* **B2:** implemented collector adoption of the B1 map, with the plan at
  [PERF06B2_DETAILED_PLAN.md](../perf-06-b/PERF06B2_DETAILED_PLAN.md) and the gate
  ledger at
  [PERF06B2_EXECUTION_REPORT.md](../perf-06-b/PERF06B2_EXECUTION_REPORT.md).
  Status is `READY_FOR_INDEPENDENT_REVIEW` only if every local and hosted gate in
  that report passes on the final tested source; otherwise it is
  `IMPLEMENTED_VERIFICATION_BLOCKED`.
* **B3:** document-key/duplicate identity — unchanged.
* **B4:** cumulative correctness plus separately approved warm qualification —
  unchanged.

B2 does not claim latency, size or RSS improvement, does not renumber B1’s
historical evidence, and does not authorize B3/B4. G10 remains maintainer-owned.

## PERF-06-B3/B4 status amendment (2026-11-25)

Sections above remain the historical planning agreement. Current facts:

* **A6:** accepted/merged; numerical misses unchanged.
* **B1:** accepted and merged (PR #126, merge commit
  `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`).
* **B2:** accepted and merged (PR #127, merge commit
  `ce7dea12c0f8f84fdc3a80306083e38c8df30ce2`).
* **B3:** accepted and merged (PR #128, merge commit
  `d660ca9f487d5c54363d790a240abb7da30af245`). The reviewed executable source
  `52d7e69f40759f27be79434118c47171b06702b7` reaches `main` unchanged; only
  documentation/evidence commits follow it.
* **B4:** executed. One paired cumulative warm qualification (A = pre-B1
  `480a77e7…`, B = post-B3 `d660ca9f…`) completed with disposition
  `PERF06_B4_QUALIFIED_TARGETS_MET_REVIEW_REQUIRED`. Plan:
  [PERF06B4_DETAILED_PLAN.md](../perf-06-b/PERF06B4_DETAILED_PLAN.md); gate ledger:
  [PERF06B4_EXECUTION_REPORT.md](../perf-06-b/PERF06B4_EXECUTION_REPORT.md);
  configuration `4608c79a-c5a3-4d24-bec9-4ad61cd7bd94`; result `run_id`
  `86fe9601-2574-4335-a673-63de7d0dcc26` (`-001`, `COMPLETE`, 16/16 A/A PASS).

B4 is a measurement/qualification PR: no engine optimization, no engine or
statistics change, and its single tool addition (`perf-06` advisory host readiness)
leaves the A/A control and structural host prerequisites binding. The result is a
**per-lane cumulative B1+B2+B3** comparison on one host/configuration, not a
universal speedup and not a per-stage causal claim. Historical 15H-C / 15I-D1-F
rejections and A-series outcomes are untouched. **G10 remains maintainer-owned:**
no merge, no baseline promotion, no PERF-06-C1 start.

## PERF-06-C1 contract status amendment (2026-11-25)

**Current baseline:** B4 was independently accepted and merged in PR #129; the C-series source baseline is `main@8c9f51f311afa5b327f70432e32c0f6f5c205eab`. Earlier stage/status rows above remain the historical planning and pre-merge records; they are not retroactively recast as C1 approval.

**C1 delivery is now documentation only (maintainer choice):**

- [PERF06C_PHYSICAL_EXECUTION_CONTRACT.md](../../architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md) — strict compiled-term/keyword-sort shape, request-local physical dispatch, M>K+1 no-benefit fallback, full count and posting validation, B1/B2/B3 ranking/key reuse, C2 eager scoring, C3 score-safety certificate, memory/work/error ordering, immutable snapshots, cursor and mutation boundaries, and required future test matrices.
- [PERF06C1_SOURCE_AUDIT.md](../perf-06-c/PERF06C1_SOURCE_AUDIT.md) — reviewed post-B4 code path, remaining full-M temporary representation, failures of 15H-A/A2 and 15I-C, design decisions and stage-specific evidence ownership.

The C1 PR changes **docs only**. It creates no physical-plan type in Rust, no unit/integration tests, no benchmark acquisition or code changes, and no implementation plan for a coding agent. Approval of C1 documentation is **not** approval to run C2. C2 and C3 each require a separate prescriptive detailed plan and correctness/CI acceptance; C4 requires a separately frozen warm benchmark against the accepted A+B baseline and an independent adoption decision. No PR stage may bypass the historical low-hit regression evidence or assume that non-scoring sort allows loser's BM25 errors to be ignored.

**C1 acceptance state:** independent document review and maintainer merge **OPEN**. After merge, use merged main for the C2 base, not this C1 branch.

## PERF-06-C2 implementation status amendment (2026-11-25)

**Baseline:** merged C1 `main@bc726420cede2e26681d6e8192b45a5d0169abbf`.
C2 was implemented on the draft branch `dev/perf06-c2-physical-executor` from the
approved prescriptive plan
[PERF06C2_DETAILED_PLAN.md](../perf-06-c/PERF06C2_DETAILED_PLAN.md) (committed
verbatim). The executed evidence ledger, invariant trace and disclosed
limitations are in
[PERF06C2_EXECUTION_REPORT.md](../perf-06-c/PERF06C2_EXECUTION_REPORT.md).

- **C2 scope delivered:** one request-local `StrictTermOrdinalTopK` route for a
  standalone single-analyzed-term query with one sortable `Keyword` column and a
  proven `M > K+1`; a new private in-place scored-posting evaluator that reuses the
  single validated `(doc_id, freq)` posting allocation and rewrites its frequency
  word to `f64::to_bits()` after eagerly scoring **every** match; the accepted
  B1/B2/B3 candidate handlers, duplicate policy and K+1 cursor finalization reused
  unchanged; the accepted legacy per-segment loop moved out of line mechanically
  with no per-document dispatch.
- **Still open:** C2 is **not merged**, **not performance-qualified** and makes no
  warm-latency claim. Independent review (G10) and maintainer merge are
  maintainer-owned. **C3 has not started.** C4 owns every warm measurement,
  including the low-hit/absent/rare guard.
- **Unchanged:** no persisted format, writer/storage/reader API, dependency,
  feature flag, benchmark asset, CI workflow or historical negative evidence was
  modified. C2 performs no durable writes.

## PERF-06-C2-F1 test/evidence fixup status (2026-11-26)

PR [#131](https://github.com/yduchesne/quervant/pull/131) (branch `dev/perf06-c2`)
carried the C2 implementation. Independent review raised five test/evidence
findings, and the follow-up plan
[PERF06C2F1_DETAILED_FIXUP_PLAN.md](../perf-06-c/PERF06C2F1_DETAILED_FIXUP_PLAN.md)
was executed with results in
[PERF06C2F1_EXECUTION_REPORT.md](../perf-06-c/PERF06C2F1_EXECUTION_REPORT.md).

- **Closed:** the actual per-segment B3 allocation refusal (five exact probe rows),
  the exact P05 evaluator work/scanned table with same-budget recovery, the exact
  public I08 resource boundaries with same-snapshot retries, the new C2-U12
  corruption/precedence test (6 of 9 prescribed rows), and the corrected
  inventory/identity/evidence attribution (28 unit + 9 integration at START;
  29 + 9 after F1).
- **Blocked (`PERF06_C2_F1_STOPPED_PLAN_AMENDMENT_REQUIRED`):** three prescribed
  fixtures are contradicted by the accepted source — physical segment order is
  content-addressed (`s-{sha256}`) rather than commit order, and the `grp/common`
  postings payload is compact-short *positional* (218 bytes) rather than the plan's
  67-byte doc-only form. The C2-U21 boundary table, the U17 no-eager-binding
  refinement and the U12 posting-mutation rows therefore did not execute; no
  expectation or byte offset was rewritten.
- **Unchanged:** production execution semantics (normal-build source equality
  verified), persisted formats, storage, benchmark assets and CI workflows. Local
  stable/MSRV QA and both coverage gates pass (93.24 % / 92.82 % lines).
- PR #131 remains **draft and unmerged**; G10 independent review/maintainer
  acceptance stays open; C3/C4 are unstarted and no performance claim is made.

## PERF-06-C2-F1-A1 amendment execution status (2026-11-26)

The approved
[PERF06C2F1_A1_DETAILED_AMENDMENT.md](../perf-06-c/PERF06C2F1_A1_DETAILED_AMENDMENT.md)
resolved both F1 D14 stops by adopting the settled source facts — content-addressed
query segment order (34-document slice first) and compact-short positional
`grp/common` postings — and strengthened the response comparisons. Results:
[PERF06C2F1_A1_EXECUTION_REPORT.md](../perf-06-c/PERF06C2F1_A1_EXECUTION_REPORT.md).

- **Now executed and passing:** all nine U12 corruption/precedence rows
  (`completed=9`), the four native-order U21 boundary rows with three same-snapshot
  recoveries, the U17 `INJECTED_C2_ONLY` no-eager-binding case, the five U17 B3
  refusal rows with complete forced-Legacy parity, the retained P05 resource table,
  and I08's exact resource/cancellation outcomes with complete cursor and
  aggregation equality.
- **Unchanged:** production execution semantics (`execute.rs` byte-identical to
  A1 START; the A1 and F1 normal-build region checks both pass), persisted formats,
  storage, benchmark assets and CI workflows.
- **G7 remains BLOCKED** on two maintainer-owned decisions: the 55 committed-range
  whitespace diagnostics confined to 40 frozen plan/receipt artifacts (exactly
  matching the amendment's Appendix A proposal, with `A1_START..HEAD` clean), and a
  reproduced pre-existing `stored_blocks_reader_tests` counter flake.
- **Delivery:** PR [#131](https://github.com/yduchesne/quervant/pull/131) is open and
  **unmerged** with its observed readiness flag preserved; G10 independent
  review/maintainer acceptance is open; C3/C4 are unstarted and no performance claim
  is made.

## PERF-06-C2-F1-A2 closeout (2026-11-26)

The approved
[PERF06C2F1_A2_CLOSEOUT_PLAN.md](../perf-06-c/PERF06C2F1_A2_CLOSEOUT_PLAN.md) finished
the F1/A1 closeout. Results:
[PERF06C2F1_A2_EXECUTION_REPORT.md](../perf-06-c/PERF06C2F1_A2_EXECUTION_REPORT.md).

- **Certificate counter interference CLOSED BY REPAIR.** Test-only observation is now
  thread-local (`stored_blocks.rs` `Cell` in the existing `thread_local!` block), the
  single real build site calls the helper, and the existing test gained a
  deterministic sibling-thread regression: the worker builds a real certificate
  (delta 1) while the parent observes delta 0 before its own first access (delta 1),
  with every original hot-path assertion and the warm no-rebuild equality retained.
  The retired global mechanism fails red-first (`exit 101`, left 1 / right 0); the
  final state passes T02–T07 (stable, MSRV, MSRV+all-features, and the nine-test
  module serial/8-thread/MSRV).
- **Frozen C2 acceptance re-executed on immutable A2_TESTED:** U17 (five B3 rows +
  structural), U21 (86/87/99/100 + three recoveries), U12 (nine rows, `completed=9`),
  P05 (six exact rows), I08 (exact resources + complete retry parity); inventories
  24/5/9/39 and nine reader tests; all local QA and both coverage gates pass
  (93.33 % / 92.91 % lines).
- **Normal builds unchanged:** `execute.rs`, `unified.rs` and the integration tests are
  byte-identical to A2_START, verified by the supplied exact checker in both regimes.
- **G7 remains BLOCKED** solely on the human decision about exactly 81 whitespace
  diagnostics in 41 unchanged frozen artifacts (A2's own range is 0). Delivery,
  reports and the PR body are corrected; PR #131 stays open and **unmerged** with its
  observed readiness preserved; G10 is open; C3/C4 are unstarted and no performance
  claim is made.

## 2026-11-26 — C2 merged; C3 implemented (correctness-only)

- **C2 done at `B`.** PR [#131](https://github.com/yduchesne/quervant/pull/131)
  merged at `main@6bc977e6a26c183609b7ca53eca51d3ab09ce337`
  (`mergedAt=2026-11-26T23:00:00Z`, reviewed head
  `da033ff19b3facd4f0a5319506a64e658156e93f`). Earlier entries in this register
  that record C2 as open/unmerged or G10/whitespace-blocked are preserved
  verbatim as contemporaneous history.
- **C3 implemented, draft, unmerged** on `dev/perf06-c3` from `B`. Plan:
  [PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md](../perf-06-c/PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md);
  report and evidence:
  [PERF06C3_EXECUTION_REPORT.md](../perf-06-c/PERF06C3_EXECUTION_REPORT.md).
- **Exact proof boundary:** certified deferred BM25 (`n>0`, `df>0`, `df<=n`,
  finite `avgdl ∈ [2^-64, 2^64]`, finite prepared IDF `∈ [0, 64]`) scores only
  the `K` returned hits with the unchanged prepared scorer and `+0.0`
  accumulator. C2 selection and the `M > K+1` guard are byte-identical; unproven
  statistics keep eager C2, ineligible shapes keep Legacy. Full posting
  validation, exact counts, work charges, virtual admissions, B1/B2/B3
  validation/duplicate policy, fallible candidate materialization, cursor and
  projection are unchanged. Physical heap entry +1 `u64` word; logical charges
  unchanged.
- **Evidence:** red-first 40→3 scorer calls; 17 new unit tests + 3 real
  `FsDirectory` integration tests; old C2 inventories 24/5/9 retained; broad
  `--lib c2_` 52 and `perf06_c2_physical` 12; stable 1.98.1 and MSRV 1.85.0
  format/clippy/tests both feature regimes; coverage 93.85 % / 93.54 % lines.
- **No performance sample.** C4 not started; it owns the integrated incremental
  warm qualification and the cumulative series report. G10 independent review
  and maintainer acceptance remain open; C3 is not DONE and no baseline is
  promoted.
