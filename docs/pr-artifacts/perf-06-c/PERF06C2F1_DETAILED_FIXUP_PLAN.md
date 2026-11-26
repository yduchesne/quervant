# PERF-06-C2-F1 — Close C2 review findings with deterministic tests and corrected evidence

**Repository:** yduchesne/quervant  
**Existing PR:** [#131](https://github.com/yduchesne/quervant/pull/131)  
**Required branch:** `dev/perf06-c2`  
**Plan date:** November 26, 2026 (America/Los_Angeles)  
**Reviewed and freshly inspected PR head:** `46ccab0a606a56a8b9034ab4db5c9c4df969d098`  
**Fresh main / accepted C1:** `bc726420cede2e26681d6e8192b45a5d0169abbf`  
**Current review disposition:** `PERF06_C2_REVIEW_CHANGES_REQUIRED`  
**Plan disposition:** `PERF06_C2_F1_PLAN_READY_FOR_EXECUTION` — this is a plan, not executed fixup evidence.

## 0. Execution contract

This is a narrow follow-up to the independent review of C2. Preserve the existing strict-term executor and close the five test/evidence findings below. Implement the exact test designs in this document; the coding agent has no authority to choose another algorithm, broaden eligibility, change production semantics, weaken assertions, or redesign the test framework.

When given this plan for execution, continue through source admission, baseline evidence, all prescribed changes, local verification, evidence preparation, an ordinary push to the existing branch, and observation of its ordinary CI. Keep PR #131 draft and unmerged. G10 independent review and maintainer acceptance remain open.

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

An unforeseen condition not covered by the decision matrix is a **HARD STOP for the affected work**. Preserve evidence and finish only demonstrably independent prescribed work. Do not infer permission from silence.

### 0.1 Frozen outcome

1. Actual B3 optional allocation refusal is injected and observed while C2 continues through the owned B2 key path.
2. A failure in segment 1 is proved to occur after segment 0 completed collection and populated its K+1 heap.
3. The missing C2-U12 adversarial collector/validation matrix exists and executes with exact typed errors and stage witnesses.
4. P05 and I08 require their calculated resource failures; success cannot satisfy a failure row.
5. Test inventory, branch identity, review status, and evidence claims accurately distinguish new tests, older filtered tests, matrix cases, historical runs, and final F1 runs.

The only changes near normal-build code are **two explicitly specified `#[cfg(test)]` observation sites** in `collect_strict_term_ordinal_body`. They compile out of every non-test build. There is no production defect authorized for repair by this plan. A newly exposed production defect invokes the decision matrix and a scoped STOP.

### 0.2 Performance boundary

No benchmark campaign, warm/cold latency measurement, profiler, `perf record`, synthetic timing loop, cross-engine run, threshold tuning, or C3/C4 implementation belongs in F1. `cargo bench --no-run` is a required compile check, not a benchmark. Correctness loops and fixed test matrices are not performance measurements. C4 retains responsibility for warm performance qualification; this fixup makes no performance claim.

## 1. Source-grounded reconciliation

The plan was authored after fresh GitHub inspection of both main and PR #131, their relevant Rust source, the authoring guide, AGENTS, TESTING, current CI, the C1 contract, the C2 plan/report, and checked-in test evidence. No Rust fixup was implemented, compiled, tested, or benchmarked during plan authoring.

### 1.1 Current facts

| Fact | Inspected evidence / consequence |
|---|---|
| Main is still the merged C1 commit `bc726420…` | C1 is the architecture contract; C2 remains a separate unmerged implementation. |
| PR #131 is open, draft, unmerged, on `dev/perf06-c2` at `46ccab0a…` | Continue this PR. The old report's `dev/perf06-c2-physical-executor` entry is incorrect for the actual branch. |
| Historical tested source is `cc2691bb9ff061cd149b990ab987a4db9b2ab400` | The repository comparison from this commit to the inspected head contains documentation/evidence changes only. Historical source QA is useful baseline context, not F1 acceptance. |
| Historical broad unit log ran 38 tests | It contains 23 `unified::c2_tests`, 5 `execute::c2_physical_tests`, 9 older `execute::budget_tests::c2_*`, and 1 older `memory::tests::c2_*`. Thus it proves 28 new unit functions, not 38. |
| Historical dedicated integration log ran 9 functions | The C2-I01 and C2-I10 acceptance IDs intentionally share one function. Original new-test inventory is 28 + 9 = 37. |
| Exact-head CI metadata currently reports run [45745505018](https://github.com/yduchesne/quervant/actions/runs/45745505018) completed successfully | This is historical starting-state context. Obtain new ordinary CI evidence after F1; do not reuse the old run for changed tests. |
| CI explicitly installs Rust 1.98.1; MSRV is 1.85.0 | Use the pinned commands in section 12. Do not silently replace them with whatever `stable` resolves to. |
| C2 production path already uses full decode, eager BM25, in-place reuse, and B1/B2/B3 collectors | Preserve it. The findings concern missing or insufficient tests and overstated evidence. |

### 1.2 In-progress capability classification

| Capability | Classification at start | F1 treatment |
|---|---|---|
| StrictTermOrdinalTopK implementation and unchanged legacy body | DONE + VERIFIED for the historical executed checks; independent acceptance open | Preserve normal-build source; rerun mandated regressions/QA after test changes. |
| Existing route, score-bit, ledger, PIT, cursor and sibling-path tests | DONE + VERIFIED for their actual assertions | Retain; do not reinterpret broad passing suites as proof of the missing cases. |
| Genuine B3 refusal in U17 | NOT STARTED in the purported refusal case | Install the existing refusal probe and exact route/fallback witnesses. |
| Later-segment failure boundary in U21/I08 | PARTIAL | Replace permissive/sweep evidence with exact boundary cases and prior-segment completion observations. |
| Required U12 adversarial matrix | NOT STARTED | Add exactly one named Rust test containing the frozen cases. |
| P05/I08 resource-negative assertions | PARTIAL | Replace success-or-error branches with exact failure and success rows. |
| Correct attribution of test counts and current identity | PARTIAL | Preserve old logs; append explicit corrections and a new F1 report. |
| C3 / C4 | NOT STARTED | Remain future work. |
| G10 independent review / maintainer acceptance | OPEN | Agent cannot self-approve or merge. |

### 1.3 Review findings and minimum correction

The IDs below are local to this fixup; they do not invent previously assigned review IDs.

| ID | Observed defect at inspected head | Exact correction |
|---|---|---|
| F1-01 (P2) | `c2_u17_ordinal_unavailable_and_b3_refusal` runs an ordinary search without arming a B3 refusal. | Section 7A: existing `BeforeHashAllocation` probe, refusal counter, explicit per-segment owned fallback, C2 route, complete-response parity. |
| F1-02 (P2) | U21 requires only that some limit fails; I08 permits success and cannot establish prior segment completion. | Section 7B and 8C: fixed limits, full error payloads, segment-completion/heap witness, exact Legacy comparison, same-snapshot independent retry. |
| F1-03 (P2) | `c2_u12_corrupt_selected_unselected_and_multi_fault` is absent. | Section 8A: one pristine control and nine labeled fault cases through actual query/reader/collector paths. |
| F1-04 (P3) | P05 accepts success at a cap that must fail; I08 uses scanned cap 30 for only 23 occurrences. | Sections 8B–8C: calculated failure/success boundaries, exact returned errors, zero completed callbacks where applicable, real budget/snapshot reuse. |
| F1-05 (P3) | “38 new unit tests” includes ten pre-existing accounting tests; status/identity claims are stale or overbroad. | Sections 10 and 13: exact module inventories, 28/37 historical correction, 29/38 expected final inventory, append-only errata and final source identity. |

## 2. Scope, protected files, and explicit reuse

### 2.1 Closed allowlist

Only these paths may change relative to the admitted F1 START:

| Path | Authorized delta |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | Existing `#[cfg(test)] c2_observation` module; exactly two test-only observation sites specified below; private helpers/imports inside `c2_tests`; expand existing U17/U21; add the single missing U12 test. No other test or production behavior changes. |
| `crates/quervant-core/src/search/execute.rs` | Existing `#[cfg(test)] mod c2_physical_tests` only: strengthen P05 and its private helper code as specified. |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | Existing I08 body and directly supporting private assertion helper, if needed, using the exact design. Correct narrow comments that refer to the strengthened U12/U17/U21 evidence. No unrelated integration changes. |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_DETAILED_FIXUP_PLAN.md` | Commit this plan verbatim at execution; new file. |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_EXECUTION_REPORT.md` | New report following section 13. |
| `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` | Append a dated F1 correction/supersession section only. Preserve all original text and historical logs. |
| `docs/pr-artifacts/perf-06-c/evidence/c2-f1-*` | New bounded text/JSON evidence and inventories. Never overwrite an old `c2-*` receipt or an earlier attempt. |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Append a short F1 status/evidence link; preserve historical entries. |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | One narrow current C2 status update/link that reports the actual disposition; C3/C4 remain planned. |

PR metadata may be updated with the prepared description after execution, under the authorization to deliver this fixup. Do not post review approvals, resolve reviewer threads, request reviewers, send messages, merge, mark ready, or enable auto-merge.

### 2.2 Protected areas

Keep the original `PERF06C2_DETAILED_PLAN.md`, authoring guide, AGENTS, TESTING, C1 physical contract, architecture, historical evidence, and B1/B2/B3 tests/fixtures unchanged. Keep `search/score.rs`, `search/work.rs`, `search/memory.rs`, query/compiler/cursor/typed/batch/select_keys APIs, all `index/**`, `segment/**`, storage/ObjectStore code, crate manifests, lockfiles, toolchains, workflows, benchmark framework/adapters/configurations/results, and distributed/vector code unchanged.

Do not repair unrelated documentation conflict markers, the known stored-block certificate-counter flake, or host housekeeping as a side effect. Record an applicable blocker instead.

### 2.3 Reuse, not replacement

Reuse:

- `UnifiedSearcher::search`, `collect_mixed` and the accepted forced-Legacy seam; the same query shape, snapshot and limits are the unit differential oracle.
- `Fixture::new` / `documents` / `body_documents` / `other_documents` and current schema/query/sort helpers.
- `ReaderSnapshot::for_test`, `SegmentSnapshot`, `SegmentMeta`, `ContainerBuilder`, `parse_container`, `ContentDescriptor::of` for bounded immutable test fixtures.
- Existing `B3Probe` / `B3ProbeOutcome` / probe setters and counters in `segment/reader.rs`, without editing that file.
- Existing `physical::ScoreFailureArm` solely for explicitly labeled `INJECTED_C2_ONLY` structural evidence.
- Existing `CandidateBudget`, `MixedWorkMeter` and their actual fields/test accessors.
- Existing real `FsDirectory` integration fixture and assertions. No new container service or mock search engine.

No new dependency, generalized corruption framework, parser, codec, BM25 implementation, duplicate policy, public configuration, feature flag, environment switch, production counter, logging, or dynamic-dispatch hook is authorized.

## 3. Correctness contract and traceability

### 3.1 Falsifiable invariants

| Invariant | Positive acceptance | Negative / adversarial acceptance | Required evidence |
|---|---|---|---|
| F1-I01: every F1 normal-build statement equals START after removing only the approved test regions/sites | Frozen source check in section 9 | Any other changed statement fails the check | Source-freeze receipt and inspected diff. |
| F1-I02: B3 refusal is real, segment-local, and leaves the request on C2 | U17 ready and ExactSet controls | U17 single/first/second refusal with exact counter and fallback vector | Five named rows, observed counters, same-query Legacy parity. |
| F1-I03: a later error cannot return a partial successful page | U21 exact cap 100; I08 cap 23 | U21 cap 13/99 with prior heap; I08 cap 22 | Exact error fields, completed-segment records, public Err and successful retry. |
| F1-I04: complete posting validation precedes candidate entry | U12 pristine | U12 final-posting fault, including posting+key fault | Exact ZeroFrequency error; strict route/evaluator 1; numeric/completed callbacks 0. |
| F1-I05: key corruption in a winner, matching loser, or nonmatch remains observable | U12 pristine and zero-match controls | U12 D0/D29/D31 | Exact DOC_KEYS error, 30 converted rows, first candidate entered, zero completed callbacks. |
| F1-I06: malformed sort columns retain eager reader validation and its error precedence | U12 healthy v2 column fixture | U12 C0/C29/combined triple fault | Exact Index→Segment wrapper, both route counters 0. |
| F1-I07: complete scoring precedes candidate key processing; later segment binding is not eager | Ordinary score-bit parity and successful two-segment control | U12 S29+D0 and U17 first-segment score fault | Explicit INJECTED_C2_ONLY labels; no claimed Legacy same-fault injection. |
| F1-I08: work limits are exact and failed admissions leave reusable ledgers | P05 caps 20/21 and total 53 | P05 caps 10/19 and total 52 | Exact doc IDs/error fields/meter totals; actual budget fields zero; same budget reused. |
| F1-I09: public resource/cancellation failure preserves immutable snapshot reuse | I08 admitted/reference/retry | I08 exact entry/byte/scanned failures and Cancelled | Real FsDirectory path; identical post-failure complete response and score bits. |
| F1-I10: test/evidence status is attributable to actual executed source and registered tests | Final 24+5+9 inventory and completed gates | Missing names, zero-test filters, stale logs, or mislabeled rows fail | Exact inventory, command receipts, TESTED/FINAL linkage, open G10. |

“Callbacks” in the physical observation module means **successfully completed callbacks**, because its increment follows `on_scored(...)?`. `numeric_candidates` records candidate entry before key binding. Never confuse those two observations. “Converted rows” is recorded only after an entire segment’s scoring loop succeeds; zero does not prove that no partial scoring occurred.

### 3.2 State and visibility boundaries

| Stage | Permitted state / visibility | Failure outcome |
|---|---|---|
| Request and reader preflight | No physical/Legacy route recorded yet; immutable metadata may be validated/cached | Exact typed error; both route counters 0. |
| Route selected; segment decoding/scoring | C2 once; no candidate entry for that segment yet | Error aborts request; no completion record for that segment. |
| Candidate callback entered | Numeric counter increments; key binding or comparison can fail | Error aborts request; completed-callback counter does not increment for that failed call. |
| Segment collection completes | Record segment index, heap length and cumulative hits; this is request-private state | A later failure still returns Err, never this partial heap. |
| Request returns success | Full exact response, K+1-derived cursor, bit-identical scores and projection | Only successful full response is externally visible. |
| Independent retry | Fresh request work meter; same immutable snapshot; existing safe metadata caches may remain warm | Outcome must match the relevant healthy/error oracle. No internal retry or Legacy replay is introduced. |

Boundary coverage is finite and explicit: K=2/3 with K+1=3/4; 0-hit controls; selected winner/matching loser/nonmatching key; first/last matching posting; first/second segment; below/exact/above scanned limit; below/exact work limit; interrupted score pass; pre-cancelled request; repeated error; same-budget or same-snapshot reuse. Existing C2 tests retain empty, singleton, M≤K+1, overflow, cursor, PIT, duplicate and sibling-path coverage.

### 3.3 Failure-mode matrix

| Failure class | Exact expected disposition | Cleanup/usability evidence | Scope |
|---|---|---|---|
| Optional B3 allocation refusal | Successful C2 request using owned B2 for only the refused segment | Probe/counter/fallback vector and full response parity | U17. |
| Malformed DOC_KEYS UTF-8 | SearchError::Segment(InvalidUtf8, context “doc key”) | Same immutable corrupted snapshot repeats exact error; pristine snapshot unchanged | U12. |
| Final posting frequency zero | SearchError::Segment(ZeroFrequency, doc_id 29) | No candidate entry; repeat and healthy control | U12. |
| Malformed sortable keyword dictionary | SearchError::Index(IndexError::Segment(InvalidUtf8, context “keyword”)) | Pre-route failure, never a false C2 collector claim | U12. |
| Synthetic C2 score failure | InvalidScore with exact existing detail | RAII arm dropped; ordinary query works again; no candidate entry | U12 and U17 structural cases only. |
| Scanned/work/candidate-memory exhaustion | Exact ResourceLimit values specified below | P05 same-budget zero ledgers; U21/I08 same-snapshot independent retry | Mandatory. |
| Cancellation | Existing exact Cancelled result | Existing I08 retry and retained C2 cancellation regressions | No new cancellation mechanism. |
| Concurrent tests/probe state | Thread-local observations; probe guard clears on unwind | Fully qualified unit suites run serial and with 8 threads | Mandatory. |
| Partial I/O, network timeout, crash recovery, remote publication, distributed retry | No implementation changes in F1 | Existing required ordinary CI/RustFS regressions remain in force | New fault infrastructure is not applicable. |
| Any unlisted outcome | Scoped HARD STOP | Preserve exact result and fixture guards | No weakening/tuning. |

### 3.4 Cross-component impact

| Component / consumer | F1 change | Acceptance |
|---|---|---|
| Standalone strict-term collector | Two test-only observation sites; unchanged normal build | New/strengthened U12/U17/U21 and frozen source check. |
| Physical evaluator | P05 tests only | Direct exact accounting/budget recovery; retained evaluator tests. |
| Legacy mixed collector, scorer, work meter and B1/B2/B3 implementations | None | Same-query forced Legacy, existing regression suites, source freeze. |
| Public FsDirectory query path | I08 assertions only | Nine-function C2 integration target executes normally. |
| Batch, aggregation, select_keys, typed/Boolean/phrase/geo/JSON/cursor paths | None | Retained U01/U03/U16/U18/U19, I03/I05/I07, whole workspace tests. |
| Segment formats, writer, manifest, immutable generations and storage | None | Copied corruption fixtures only; original bytes verified unchanged; ordinary RustFS CI regression. |
| Benchmark harness, adapters and performance baselines | None | Existing script/CI regression; no timing campaign. |
| Public API and response/cursor serialization | None | Complete-response comparison plus explicit score bits. |

### 3.5 Residual evidence limits

- Native malformed v2 sort dictionaries fail at reader open. Their tests prove that shared validation boundary; they cannot prove execution inside C2.
- The score injector exists only in C2. The injected tests are structural precedence evidence, not a real malformed-score corpus or same-fault Legacy comparison.
- The no-eager-binding case proves first-segment scoring failure prevents the second successful binding checkpoint from being reached. It does not inject malformed later columns.
- B1 NotAvailable checks in existing U17 remain enum/error-mapping evidence. This fixup does not create a new end-to-end B1 refusal fixture.
- Correctness, source isolation, and passing QA do not prove a latency improvement. C4 owns measurement.
- These limitations are inherited/disclosed scope, not authority to waive a newly failing mandatory gate. If a reviewer requires stronger proof outside the frozen fixtures, stop that affected work and request an amendment.

## 4. Source admission and pre-implementation correctness gate

### 4.1 Admit the existing branch

Read-only work may precede checkout. Before editing:

1. Record repository root, current branch, `git status --short`, remotes without exposing credentials, and PR #131 metadata.
2. Fetch current main and the existing task branch. Check out `dev/perf06-c2` or create its local tracking branch if absent. Pull fast-forward only.
3. Verify remote head is the pinned head and main is the pinned C1 commit. See D02 for a narrowly permitted documentation-only descendant; any code/test/contract/toolchain drift stops affected execution.
4. Record immutable START and BASE, and verify PR #131 is still open/draft/unmerged and targets main. Preserve foreign changes.
5. Verify the known original plan, guide and protected files are present and match the admitted source. Do not base the fixup on an older downloaded artifact.
6. Copy this file verbatim to the authorized repository plan path; record its SHA-256.

Exact normal path, from repository root:

~~~bash
git status --short
git fetch origin main dev/perf06-c2
git switch dev/perf06-c2
git pull --ff-only origin dev/perf06-c2
git rev-parse HEAD origin/dev/perf06-c2 origin/main
git merge-base --is-ancestor bc726420cede2e26681d6e8192b45a5d0169abbf HEAD
git diff --check
gh pr view 131 --repo yduchesne/quervant --json number,state,isDraft,headRefName,headRefOid,baseRefName,url
~~~

When the local branch does not exist, the only alternate checkout is `git switch --track -c dev/perf06-c2 origin/dev/perf06-c2`. Never reset, clean, stash others’ work, rebase, merge main, force-push, or create a second PR to bypass a mismatch.

### 4.2 Baseline evidence

Before edits, inventory the three exact C2 scopes and the historical broad filter using section 10’s commands. Expect 23 unified unit functions, 5 physical unit functions, 9 integration functions, and 38 broad-filter unit functions.

Run the existing three exact scopes once serially with Rust 1.98.1. Capture command, start/end time, exit status and full output. These runs establish starting health for the actual changed test scopes, not proof that the missing assertions exist. Do not repeat the entire workspace merely to obtain another baseline; section 12 requires the full final verification.

Record the observed source defects: no U12 registration; no armed B3 refusal in U17; U21’s `saw_failure`; P05’s accepted Ok branch; I08’s cap30/accepted Ok branch; the 28/37 versus 38-filter inventory.

### 4.3 Correctness worksheet before editing

Complete and retain these concrete answers:

- Why does U17 require a fresh never-searched fixture and an explicit threshold configuration that resolves to internal Linear mode?
- What source statements prove 13 scanned occurrences in U21 segment 0 and 100 overall?
- Why do U12 key errors have one entered candidate but zero completed callbacks?
- Why must malformed-column rows have zero routes?
- Why is P05 total work 53 only for its direct evaluator, after separately prepared inputs?
- Which comparisons are same-query forced Legacy, which are public Boolean-wrapper controls, and which are C2-only injections?
- Which two observation sites disappear from non-test builds?
- Which exact report claims are superseded without changing historical raw output?

Map all F1-I01..I10 invariants to the planned test rows and gates. If a fixture, error wrapper, observer, helper or source assumption differs, use section 15 before editing. Do not reinterpret the design.

## 5. Fixed implementation sequence

| Stage | Work | Exit evidence / next action |
|---|---|---|
| P0 | Source admission and baseline inventories/runs | START/BASE, PR state, baseline receipts. Continue automatically. |
| P1 | Complete correctness worksheet; introduce only specified test observations/helpers | Invariant mapping and source-scope check. |
| P2 | Strengthen U17 and U21 exactly as section 7 | Each exact named test executes one registered function and passes every named row. |
| P3 | Add U12 and strengthen P05/I08 exactly as section 8 | Exact typed errors, boundary counters, immutable fixture/recovery assertions. |
| P4 | Run full C2 serial/parallel, integration, retained regressions, inventories | 24+5+9 final inventory and complete feature matrix evidence. |
| P5 | Final source freeze and mandatory workspace QA | Local gates at final test/source state; any later test/source edit invalidates affected results. |
| P6 | Commit tested source/tests/plan; add reports and status corrections; push ordinarily | TESTED/FINAL/source-equivalence identities, scoped diff and draft PR. |
| P7 | Observe normal CI; finish evidence and final report | Actual five-job evidence or truthful pending/blocked status. G10 stays open. |

The stage order controls dependencies; it does not create new permission checkpoints. A blocked CI read, for example, does not block independent report completion. Do not change production source to make P2/P3 pass.

## 6. Test-only observations and shared test rules

### 6.1 Exact new observations

In the existing `unified::c2_observation` module, import `RefCell` alongside `Cell` and add:

~~~rust
thread_local! {
    static OWNED_KEY_FALLBACK_SEGMENTS: RefCell<Vec<usize>> =
        const { RefCell::new(Vec::new()) };
    static COLLECTED_SEGMENTS: RefCell<Vec<(usize, usize, u64)>> =
        const { RefCell::new(Vec::new()) };
}

pub(crate) fn record_owned_key_fallback_segment(segment_index: usize) {
    OWNED_KEY_FALLBACK_SEGMENTS.with(|value| value.borrow_mut().push(segment_index));
}

pub(crate) fn owned_key_fallback_segments() -> Vec<usize> {
    OWNED_KEY_FALLBACK_SEGMENTS.with(|value| value.borrow().clone())
}

pub(crate) fn record_collected_segment(
    segment_index: usize,
    heap_len: usize,
    total_hits: u64,
) {
    COLLECTED_SEGMENTS.with(|value| {
        value.borrow_mut().push((segment_index, heap_len, total_hits));
    });
}

pub(crate) fn collected_segments() -> Vec<(usize, usize, u64)> {
    COLLECTED_SEGMENTS.with(|value| value.borrow().clone())
}
~~~

Use the existing thread-local block rather than creating duplicate facilities. Extend the existing `reset()` to clear both vectors. All code stays under the existing `#[cfg(test)]` module. No static cross-thread state.

Inside `collect_strict_term_ordinal_body` add only these sites:

**Site A:** inside `if matches!(key_binder, KeyBinder::Unattempted)`, immediately after the existing assignment to `key_binder`:

~~~rust
#[cfg(test)]
if matches!(key_binder, KeyBinder::Fallback) {
    c2_observation::record_owned_key_fallback_segment(segment_index);
}
~~~

The `#[cfg(test)]` attribute must cover the **whole if statement**. The new condition must not survive a non-test build.

**Site B:** immediately after `execute::visit_strict_term_scored_with(...)?;` returns successfully, before existing geo cleanup:

~~~rust
#[cfg(test)]
c2_observation::record_collected_segment(segment_index, heap.len(), *total_hits);
~~~

Do not alter the legacy body, the evaluator, function signatures, ownership, error flow or cleanup order. The completion record refers to collection, not publication or completion of later cleanup.

### 6.2 Test helper boundaries

All additional Rust helpers must be private and inside `c2_tests` or the already authorized test module. Their behavior is prescribed below. Simple Rust import/borrow/type corrections that implement this behavior are permitted by D10; architectural substitutions are not.

Use existing `projected()` for key/score-bit/projected-field equality, and also assert `total_hits`, `generation`, `view_ordinal`, `next_cursor` and `aggregation` equality. Explicit `bits()` or integration `scores()` comparisons remain required. Do not compare only keys, counts or cursor presence when complete-response parity is required.

For forced-Legacy calls that can return errors or use explicit duplicate config, add a private helper taking the same fixture/snapshot, request, limits and config, then:

1. Reset observations before creating `ForceLegacy`.
2. Create the existing RAII force guard.
3. Invoke `run_with` or the fixed snapshot search helper.
4. Exit the force scope and capture the result.
5. Verify the expected route counters for its stage.

Never reset witnesses after arming `ScoreFailureArm` or `ForceLegacy` but before the call. Existing `strict()` resets witnesses and therefore must not be called while a score arm is active.

For exact typed errors use structural `match`/`matches!` checks on the complete variant/wrapper and all specified fields. Debug text is supplemental diagnostic output, not the oracle.

### 6.3 Evidence for table cases

Print one bounded line per prescribed case with its stable row ID and observed error/route/phase/budget values; use `--nocapture` for focused receipts. This is test output only. A case line never replaces assertions.

Capture observations before any reference/retry/reset changes them. All loops use the fixed rows and bounded repeat counts; no random search for a passing budget, sleeps, polling, timing or “at least one failure” flags.

## 7. Exact boundary-test design

The following subsections are binding implementation specifications.

### 7A. U17 — Actual per-segment B3 refusal


Preserve the original test name and B1 enum mapping/error assertions. Replace the misleading ordinary-search refusal section with actual injected refusal. Keep ExactSet as a distinct control.

#### Imports and probe cleanup

Import existing `B3Probe`, `B3ProbeOutcome`, `b3_build_attempts`, `b3_directory_builds`, `b3_preflight_fallbacks`, `clear_b3_probe`, `reset_b3_counters`, and `set_b3_probe` from `crate::segment::reader`.

Add a private test-only `B3ProbeReset` RAII helper inside `c2_tests`:

- `new()` calls `clear_b3_probe()` and returns the guard.
- `Drop` calls `clear_b3_probe()`.
- Always bind the guard before installing a probe; retain it until after result/counter assertions. Thus a panic cannot contaminate another test on the same worker thread.

Use `Rc<Cell<usize>>` captured by the probe to record the exact number of probe callbacks fired. Never infer callback execution from output parity alone.

#### Fixed cases

For every case create a **fresh**, never-searched fixture. A prior search warms the sticky fingerprint cache and can prevent the probe from firing. Do not run the reference search until the actual injected search and all its witnesses have been captured.

Explicit duplicate config: `TopKDuplicateConfig::new(NonZeroUsize::new(4).expect("four"), TopKDuplicateStrategy::Prefilter)`; query `term_common()`, ascending `doc_id`, `K=3`. The public enum has no Linear variant: this threshold selects the existing internal Linear mode because `K < 4`. Use threshold `1` with `TopKDuplicateStrategy::ExactSet` only for the distinct ExactSet control.

| Case | Segments | Probe schedule | Callbacks fired | Builds attempted | Directory builds | Refusals | Recorded fallback segments |
|---|---|---|---:|---:|---:|---:|---|
| Single refusal | `[documents(40)]` | first BeforeHashAllocation returns RefuseAllocation | 1 | 1 | 0 | 1 | `[0]` |
| First of two refuses | `[documents(20), documents(40).into_iter().skip(20).collect()]` | first returns RefuseAllocation | 1 | 2 | 1 | 1 | `[0]` |
| Second of two refuses | same two-segment fixture, fresh | first callback re-arms BeforeHashAllocation with a second callback and returns Continue; second returns RefuseAllocation | 2 | 2 | 1 | 1 | `[1]` |
| All ready control | fresh two-segment fixture | no probe | 0 | 2 | 2 | 0 | `[]` |
| ExactSet control | fresh two-segment fixture | no probe; explicitly choose ExactSet | 0 | 0 | 0 | 0 | `[0,1]` |

Before each actual request call `reset_witnesses()`, `b2_observation::reset()`, `b3_observation::reset()`, and `reset_b3_counters()`. Apply/reset in that order before arming the probe. All table assertions are exact equality, not `>=`.

For every case assert C2 route count `1`, Legacy route count `0`, physical evaluator calls equal number of segments, converted rows `40`, callbacks `40`, B2 numeric candidates `40`, total hits `40`, literal returned keys `doc000000`, `doc000001`, `doc000002`, and nonempty next cursor. Assert the completed-segment vector is `[(0,4,40)]` for the single segment or `[(0,4,20),(1,4,40)]` for two segments. This demonstrates the refusal did not replay or abandon C2.

Capture these observations before calling `forced_legacy`, because that helper resets C2 observations. Then compare `projected()` (includes score bits and fields), `total_hits`, `generation`, `view_ordinal`, `next_cursor`, and `aggregation` against forced Legacy of the **same** query/snapshot/config. For explicit configs use a small test helper mirroring `forced_legacy` but passing the supplied config to `run_with`; do not force Legacy by changing the query shape. 

Preserve B1 optional-not-available scope honesty: this test still proves enum mapping, not a new public B1 failure mode. Do not rewrite protected snapshot/reader code to create B1 faults.


#### 7A.1. Existing-injector no-eager-binding case


Add this scenario **within** `c2_u17_ordinal_unavailable_and_b3_refusal`, with no new test function and no new injection seam. It supplements the refusal rows and replaces the unsupported claim attached to the existing happy-path two-binding assertion.

Use a fresh clean fixture `[body_documents(6), body_documents(40).into_iter().skip(6).collect()]`, `request_asc(term_body(), 2)`, default limits, and the explicit Prefilter/threshold-4 configuration that resolves to internal Linear mode at K=2. Ensure prior B3 probe scope has ended; call `clear_b3_probe()`. Call `reset_witnesses()`, `b2_observation::reset()`, `b3_observation::reset()`, `reset_b3_counters()` **before** arming.

```rust
let result = {
    let _arm = physical::ScoreFailureArm::arm(5);
    run_with(&fixture, &request, SearchLimits::default(), linear_config)
};
```

Do **not** use `strict()` inside the armed scope: that helper calls `reset_witnesses()` and would erase `SCORE_FAILURE_DOC`. Do not call any reset between arming and `run_with`. The RAII guard must leave scope before the recovery query.

Require exactly `Err(SearchError::InvalidScore { detail: "injected C2 score failure" })`; strict routes `1`; Legacy routes `0`; bound columns `1`; strict evaluator calls `1`; membership observations `6`; converted rows `0` (the finish witness records only a fully converted vector, not the five partially rewritten rows); successful callbacks `0`; numeric candidates `0`; collected segments `[]`; owned-key fallback segments `[]`; and B3 build attempts `0`. Those facts show that first-segment scoring failed before any candidate key binding, and the second segment's actual column-binding/evaluator checkpoint was never reached.

After dropping the arm, reset observers and run the same request/snapshot without injection. Require success with total `40`, literal first two keys, bound columns `2`, callbacks/numeric candidates `40`, and collected segments `[(0,3,6),(1,3,40)]`; capture these before comparing against forced Legacy's successful response and score bits.

Classify this as **INJECTED_C2_ONLY — no-eager-binding structural evidence**. It does not create malformed later columns and does not prove same-fault InvalidScore parity with Legacy; the successful Legacy control is output parity only. This refinement closes an executable structural coverage gap without pretending that a distinct later-column corruption was injected. No normal-build behavior, protected reader code, public API, or new observer beyond the two frozen facilities changes.

### 7B. U21 — Exact later-segment resource boundary


Preserve test name `c2_u21_work_budget_exhaustion_after_prior_segment`; replace the sweep and `saw_failure` with the table below.

Use precisely the existing fixture:

```rust
Fixture::new(&[
    body_documents(6),
    body_documents(40).into_iter().skip(6).collect(),
])
```

Query is `request_asc(term_body(), 2)`. Every document contains alpha with frequency `1 + global_index % 4`; the first six frequencies are `1,2,3,4,1,2`, sum `13`; second segment begins at global index `6`, frequency `3`; full forty frequencies sum `100`. All current writer-created documents are live and have persisted `body` field norms, so `compute_stats` uses dictionary df and performs **no scanned-occurrence charge** before the evaluator. `expand_query` likewise does not charge posting occurrences for this exact term.

Assert those fixture prerequisites instead of assuming them: exactly two segments, reader document counts `6` and `34`; effective-live bitmap length equals doc count and every flag true; `reader.field_norms().and_then(|norms| norms.field(body_field_id)).is_some()` for each segment. Obtain body field id through the schema. If those prerequisites fail on the pinned source, STOP rather than choosing a different limit.

| max scanned | Required result | Strict evaluator calls | Converted rows | Successful callbacks | B2 numeric candidates | Bound columns | Completed collection records |
|---:|---|---:|---:|---:|---:|---:|---|
| 12 | `Err(ResourceLimit { limit:12, requested:13 })` | 1 | 0 | 0 | 0 | 1 | `[]` |
| 13 | `Err(ResourceLimit { limit:13, requested:16 })` | 2 | 6 | 6 | 6 | 2 | `[(0,3,6)]` |
| 99 | `Err(ResourceLimit { limit:99, requested:100 })` | 2 | 6 | 6 | 6 | 2 | `[(0,3,6)]` |
| 100 | `Ok`, exact total hits 40 | 2 | 40 | 40 | 40 | 2 | `[(0,3,6),(1,3,40)]` |

For each row reset all route/physical/B2 observations before the actual request. Set only `with_max_scanned_posting_occurrences(limit)` on default limits; other ceilings remain ample. Assert strict route `1`, Legacy route `0` for every row. Match the actual `SearchError::ResourceLimit` variant and both numeric payloads; any `Ok` on a failure row or any other error is a test failure. Do not rely solely on `verdict` agreement.

For each failure row, after capturing C2 observations, run the same request/snapshot/limit under `ForceLegacy` and require the **same exact** ResourceLimit payload. Assert forced Legacy route and zero physical evaluator calls using a fresh observation reset before that call. Both invocations return `Err`, therefore neither contains a partial response/page/cursor.

Run a successful independent request after every failure on the **same snapshot** with limit `100`; assert exact total `40`, literal keys `[doc000000, doc000001]`, nonempty cursor, matching generation/view and full response/score-bit parity with the same forced-Legacy success. A failed query may warm legitimate immutable metadata caches; never equate changed cache state with leaked query resources. P05 and the retained ledger tests own logical resource-release proof.

#### What this establishes

- Limit 12 is the negative control: no preceding segment was completed.
- Limit 13 fails on the first posting of segment B after segment A provided six successful candidate callbacks and a full `K+1=3` heap.
- Limit 99 fails at the end of segment B before any of its callbacks, while the earlier partial heap remains observable only inside the request.
- Limit 100 is an exact-at-limit success, preventing overstrict limits or failure-only behavior from passing.
- Fresh successful queries on the same snapshot demonstrate request isolation/reusability. This is correctness evidence, not latency or performance measurement.



## 8. Exact adversarial and resource-test design

The following subsections are binding implementation specifications.

### 8A. U12 — Native fixture, exact byte mutations and oracle


Build one native `Fixture` using the existing c2 `document`, `other_documents`, `Fixture::new`, `request_asc`, `term_common`, `strict`, `forced_legacy`, `keys`, `bits`, and `projected` helpers:

1. `let mut rows = documents(30); rows.extend(other_documents(2, 30));`
2. `Fixture::new(&[rows])` creates one committed/reopened MemoryDirectory segment.
3. Query exactly `request_asc(term_common(), 3)`; 32 physical live rows, 30 matching rows, K=3, K+1=4. Only docs 0..29 match.
4. Assert actual pristine physical DOC_KEYS equal `bounded_key(0)..bounded_key(31)` in that order before any mutation. Assert target dictionary `grp/common` entry `doc_freq == 30`.
5. Healthy strict control: total_hits=30, keys exactly `doc000000`, `doc000001`, `doc000002`, cursor present; full response/projected values/score bits equal same-query forced Legacy on the same healthy snapshot.
6. Take a copied `pristine` byte vector; never mutate original snapshot or committed storage. Rebuild copied immutable containers with `parse_container` and `ContainerBuilder`, preserving container kind, doc_count, required features, optional features, every section's flags/aux and every unmodified body. This repeats the established `b3_f1_u01_matching_query_rejects_corrupt_unselected_doc_key` fixture pattern.
7. Put each rebuilt byte vector into a new `ReaderSnapshot::for_test` using the exact constructor in section 8D, `doc_count=32`, `SegmentLimits::default()`, reader-copy cap `256*1024*1024`, and metadata cap `256*1024*1024`. Use a deterministic per-row segment id/path. Recompute authentic section/container descriptors with existing builders; never alter manifests or bypass digest verification.
8. Add a private `c2_f1_run_snapshot(fixture: &Fixture, snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> SearchResult<UnifiedResponse>` helper whose body is the existing `UnifiedSearcher::new(snapshot, &fixture.schema, &fixture.registry, SearchLimits::default()).with_topk_duplicate_config(TopKDuplicateConfig::default()).search(request, &Budgets::new(), &NeverCancel)` call. Do not try to clone/move `Fixture.index` into each case.

#### Frozen mutation recipes

Use private bounded helpers inside c2_tests, with hard assertions of every stated original byte before changing it. A failed fixture guard is a plan/source mismatch, not permission to find another arbitrary byte.

**D(j): invalid UTF-8 DOC_KEYS payload**, j in {0,29,31}:

- Body is exactly version 1 (`u16 little-endian`), count32 (`u64 little-endian`), 32 records of length9 (`u16 little-endian`) plus literal `docNNNNNN` bytes.
- Assert body length `10 + 32*11 = 362`, header, and every record's expected length/key; this proves the selected/nonselected physical position independently.
- Set only body byte `12 + 11*j` from ASCII `d` to `0xFF`.
- This alters only DOC_KEYS; sort column, postings, field norms and other sections remain intact.
- A standalone `SegmentReader::open(rebuilt.clone(), limits)` succeeds because key payload validation is lazy. Its `doc_key(0)` fails exactly `SegmentError::InvalidUtf8 { context: "doc key" }`, even for j=29/31 because authoritative full key decoding checks every record.

**P: zero frequency in final matching posting (doc29)**:

- Use the pristine reader's `schema().field_id("grp")`, `dictionary().lookup(field_id,"common")`; copy its `postings_offset`, `postings_length`, `doc_freq` before rebuilding.
- Assert target payload is exactly 67 bytes: seven-byte header `[6,1,30,30,30,30,0]` (compact-short doc-only marker, version, count, total freq, doc stream len, freq stream len, empty positional stream), doc stream `[0,1,...,1]` of length30, frequency stream all ones of length30.
- Set only POSTINGS body byte `postings_offset + 66` from1 to0. Keep extent, dictionary and header frequency total unchanged.
- Standalone open still succeeds. A direct cursor over grp/common yields exactly docs0..28 with freq 1, then fails on the next call with `SegmentError::ZeroFrequency { doc_id: 29 }`. It must not report a header/digest or unrelated-term error.
- Public normal/forced-Legacy queries must both produce `SearchError::Segment(SegmentError::ZeroFrequency { doc_id: 29 })`. Since all rows remain live and native field norms are retained, statistics preparation uses dictionary doc_freq and does not scan this corrupt posting stream before the route decision. Assert strict route actually ran.

**C(j): invalid UTF-8 in sortable doc_id dictionary**, j in {0,29}:

- In the copied COLUMNS section only, find the exact nine-byte `bounded_key(j)` payload. Assert exactly one occurrence; replace its first byte (ASCII d) with0xFF. All section lengths/features/geometry stay unchanged.
- Native v2 keyword dictionaries are eagerly validated by the column parser at segment open. A standalone `SegmentReader::open` must fail exactly `SegmentError::InvalidUtf8 { context: "keyword" }`.
- In the search test, do **not** call `Index::open_existing` on corrupted persisted bytes. Wrap the rebuilt bytes in `ReaderSnapshot::for_test`; `UnifiedSearcher::search` performs the first snapshot reader open and must yield exactly `SearchError::Index(crate::index::IndexError::Segment(SegmentError::InvalidUtf8 { context: "keyword" }))`.
- Both route counters and C2 evaluator counters stay0. This is pre-route validation/error-precedence acceptance; it is not proof that the C2 collector ran.

#### Exact U12 rows and assertions

One test function executes these nine labeled rows. Rows are matrix cases, not nine Rust tests.

| Row | Faults | Required error | Strict route / evaluator | Completed converted rows | Completed callbacks | B2 numeric candidates |
|---|---|---|---|---|---|---|
| D0 | D(0), retained winner | Segment InvalidUtf8 `doc key` |1 /1 |30 |0 |1 |
| D29 | D(29), matching numeric loser | Segment InvalidUtf8 `doc key` |1 /1 |30 |0 |1 |
| D31 | D(31), nonmatching/unselected row | Segment InvalidUtf8 `doc key` |1 /1 |30 |0 |1 |
| P29 | P | Segment ZeroFrequency doc29 |1 /1 |0 |0 |0 |
| P29+D0 | P plus D(0) | Segment ZeroFrequency doc29 |1 /1 |0 |0 |0 |
| C0 | C(0), winner sort value | Index(Segment InvalidUtf8 `keyword`) |0 /0 |0 |0 |0 |
| C29 | C(29), loser sort value | Index(Segment InvalidUtf8 `keyword`) |0 /0 |0 |0 |0 |
| C29+P29+D0 | all three real byte faults | Index(Segment InvalidUtf8 `keyword`) |0 /0 |0 |0 |0 |
| S29+D0 | D(0) plus existing C2 `ScoreFailureArm::arm(29)` | InvalidScore detail `injected C2 score failure` |1 /1 |0 |0 |0 |

Before each execution, call existing `reset_witnesses()` and `b2_observation::reset()`. Apply any ForceLegacy/ScoreFailureArm **after** resets; reset_witnesses clears those overrides. No nested score arms. Existing RAII clears the score injector when the local scope exits.

For D rows, membership observations=30, inplace_preserved=true. The callback counter records only successful callback completions: it is0 although the first callback entered and failed. `b2_observation::numeric_candidates()==1` proves this exact distinction. Do not claim no callback invocation for key errors.

For P rows, membership observations=0 because full decoding fails before the subsequent membership/scoring phase. For S row, membership observations=30 but converted_rows=0 because that counter is updated only on whole-segment scoring completion; do not claim no rows were scored. S row has no candidate entry (`numeric_candidates==0`).

For every real-byte row D/P/C, perform the identical request against the same mutated snapshot with existing `ForceLegacy` RAII; assert the same exact nested error, not a broad family or debug-string-only comparison. If error occurs after route selection, forced-Legacy counters are legacy1/strict0 and C2 evaluator0. For C rows both route counters remain0 in either mode.

For S29+D0, no same-fault Legacy comparison is permitted because its injector exists only in C2. Run explicit controls without the score arm: normal strict and forced Legacy each yield the real DOC_KEYS error; then arm doc29 and require the distinct InvalidScore plus zero candidate entries; drop the arm and require the DOC_KEYS error again. Classify S as `INJECTED_C2_ONLY` structural ordering evidence, while its byte-fault controls are genuine shared-source parity evidence.

For D and P rows, a zero-match grp term `"no-such-group"` must return total_hits0/empty hits/no cursor before the matched query. Do not require zero-match success for C rows: column preflight is authoritative regardless of hit count.

Repeat each real fault query once against the same immutable mutated snapshot and require the same exact error. After each row, query the pristine fixture successfully and compare literal keys/counts plus score bits with its initial healthy result. At end, assert original segment bytes are still byte-identical to `pristine`.

No actual C2-only query is required to process malformed v2 columns after open: the accepted reader intentionally rejects them earlier. Later ordinal-binding-vs-earlier-scoring ordering is a distinct structural obligation; these pre-route failures cannot discharge it and must not be described as doing so.


### 8B. P05 — Exact evaluator work and scanned limits


Keep the existing 20-row single-keyword fixture, tombstoning physical positions0,3,6,9,12,15,18. Every physical posting has freq1. There are 20 scanned occurrences and 13 effective-live matches; live ids are exactly `[1,2,4,5,7,8,10,11,13,14,16,17,19]`.

The `strict_inputs` preparation uses its own meter; each direct evaluator call gets a fresh meter starting at zero. Successful evaluator work is `20*(1+1)+13 = 53` units:40 from scanned postings and 13 from N examination. This is directly observable by `MixedWorkMeter::total_used()` already available under cfg(test).

Replace permissive `Ok(count)` acceptance with table rows:

| total cap | scanned cap | Exact outcome | callbacks | meter total_used |
|---|---|---|---|---|
|u64::MAX|10|ResourceLimit{limit:10,requested:11}|0|20|
|u64::MAX|19|ResourceLimit{limit:19,requested:20}|0|38|
|u64::MAX|20|success, exact live ids/count 13|13|53|
|u64::MAX|21|success, same exact answer|13|53|
|52|20|ResourceLimit{limit:52,requested:53}|0|40|
|53|20|success, same exact answer|13|53|

After **every** outcome assert actual `budget.segment_entries==0`, `budget.segment_bytes==0`, `budget.global_bytes==0` (accessible from execute.rs child test module). Failure cases require literal ResourceLimit fields via expect_err/matches and physical completed callbacks0. Successful callbacks assert matched_count 13 and finite score; final exact doc-id vector equals literal above.

After each rejected call, keep that same CandidateBudget, create a fresh meter with total cap53/scanned cap20, reset witnesses, rerun the evaluator and require full 13-hit success and all budget fields0. This proves actual ledger cleanup/reusability; a new budget cannot substitute. No polling/sleeps/randomness.

No public-work accounting total of53 is claimed: this exact number applies to the direct evaluator after separately prepared inputs. Existing U05 retains varying-frequency public parity coverage.


### 8C. I08 — Exact public resource errors and snapshot reuse


Preserve existing single-segment `Corpus::single("i08",48)` K3 and its exact peak controls: matches23; entries69; bytes2944. Keep at-limit success, entries68=>ResourceLimit{68,69}, bytes2943=>ResourceLimit{2943,2944}, and cancellation=>Cancelled. Add same-snapshot successful independent retry with the exact admitted limits after each resource error, comparing literal count 23, expected common-lane first 3 keys, score bits via `scores`, projected fields, generation/view and cursor presence with the admitted response. For same request/snapshot full response equality is also available, supplemented by score-bit equality.

The split corpus `[0..24,24..48]` contains 11 then 12 common-term postings. All are live, native norms make preparation scan-free, so total scanned occurrences are exactly 23.

- Replace the permissive scanned30 match with scanned22 and unconditional `expect_err`; require exactly ResourceLimit{limit:22,requested:23}.
- Add exact scanned23 success before the rejection and an independent scanned23 retry after it. Require total_hits23, three expected common keys, cursor present, exact score bits/projection and response identity against the admitted split result.
- This public integration establishes genuine FsDirectory atomic error/no response and recoverability. The strengthened private U21 must separately prove that segment0 completed and retained candidates before the failure in segment1. Do not infer the internal boundary solely from public Err or substitute public success at30 as failure evidence.



### 8D. Complete copied-snapshot constructor and fixture discipline

The following is the exact existing constructor shape to reuse for each U12 row. `case_id` is one of the fixed row IDs; `rebuilt`, `required`, `optional` and `doc_count` come from the validated copied container as specified above.

~~~rust
let snapshot = ReaderSnapshot::for_test(
    vec![crate::index::SegmentSnapshot::new(
        crate::index::SegmentMeta::new(
            format!("c2-f1-{case_id}"),
            format!("test/c2-f1-{case_id}"),
            ContentDescriptor::of(&rebuilt),
            required,
            optional,
            None,
        ),
        Arc::new(rebuilt),
        doc_count,
    )],
    SegmentLimits::default(),
    256 * 1024 * 1024,
    256 * 1024 * 1024,
);
~~~

`ContentDescriptor` is the existing `quervant_objectstore::ContentDescriptor`. The snapshot constructor returns `ReaderSnapshot`. Retain it for all same-row queries. Do not mutate the native fixture or its committed directory.

The rebuilding helper copies `view.required_features()` and `view.optional_features()`; iterates `view.sections()`; preserves each entry’s `kind`, `flags` and `aux`; obtains each body via `view.body(entry.kind)`; applies only the row’s specified byte mutations; uses `ContainerBuilder::new(ContainerKind::Segment, doc_count)`, `require_feature`, `optional_feature`, `section` and `build`. Preserve section order. This is bounded test fixture construction using the existing codec, not a new serialization implementation.

Perform U12 prerequisite checks on the original pristine native snapshot before rebuilding fault rows. Never require a successful snapshot reader open or an all-valid postings scan on a mutated C or P row; its explicit direct probe and expected query failure are specified separately.

For U21 and pristine U12 scanned-accounting prerequisites, assert the relevant field ID exists, `reader.field_norms().and_then(|norms| norms.field(field_id)).is_some()`, and the effective live mask is all true. Obtain the mask with the existing `snapshot.effective_live_docs(segment_index, reader)`. Assert the fixed segment sizes and literal posting frequencies. The actual query still performs its own unchanged stats/validation. Do not bypass preflight or replace statistics with a fake.

Within U12, use the fixed fault identifiers `D0`, `D29`, `D31`, `P29`, `P29+D0`, `C0`, `C29`, `C29+P29+D0` and `S29+D0`. Implement with a private finite enum/table or nine explicit blocks following that order; choosing another test corpus, corruption location or expected error is forbidden. Each real-byte fault gets exactly one repeated matched query on the same row snapshot, in addition to its forced-Legacy comparison. The original raw bytes must remain byte-identical at the end.

### 8E. Reporting the oracle precisely

- U12 D/P/C rows compare the exact same query and immutable snapshot through normal execution and forced Legacy.
- U12 S29+D0 compares ordinary unarmed DOC_KEYS controls on both routes, and separately proves the injected C2 score error. The Legacy route does not receive that synthetic score fault.
- U17 refusal compares the same query, snapshot, limits and explicit duplicate strategy after capturing the refusal observations.
- U17 no-eager-binding is an existing C2-only injector plus real binding/evaluator observations; its recovery control compares successful responses.
- U21 uses actual scanned-limit errors on the same query/snapshot/limits in both routes.
- I08 is the real public FsDirectory boundary and independent retry. Unit U21 establishes the internal prior-segment heap witness; I08 must not claim access to unit-only counters.
- No second copy of the collector, postings decoder, BM25 formula, or sort algorithm is an oracle.

## 9. Normal-build source freeze and diff verification

Before claiming F1 source completion, verify all of the following:

1. `execute.rs` differs only inside its existing `#[cfg(test)] mod c2_physical_tests` block.
2. `unified.rs` differs only inside its existing `#[cfg(test)] c2_observation` and `#[cfg(test)] c2_tests` blocks, plus the exact two sites in section 6.
3. Neither site has an unguarded condition, operand, argument construction, variable, import or helper dependency in a normal build.
4. `collect_mixed_legacy_body`, selection, normal physical evaluator, scoring, B1/B2/B3 implementations, accounting and APIs remain byte-for-byte unchanged.
5. No F1 delta exists in any protected file.

Produce `c2-f1-normal-build-freeze.txt` with START, the tested worktree/source commit, inspected diff and a PASS/FAIL conclusion. Use an exact source-region comparison, not an assertion that “these look test-only”:

- For `execute.rs`, remove the region beginning at the unique marker `#[cfg(test)]\nmod c2_physical_tests {` up to, but not including, the following unique `#[cfg(test)]\nmod budget_tests {` from both START and candidate text.
- For `unified.rs`, remove the unique `#[cfg(test)]\npub(crate) mod c2_observation {` region up to, but not including, the following `#[cfg(test)]\n#[allow(clippy::needless_option_as_deref)]\nmod tests {`.
- Remove the unique `#[cfg(test)]\nmod c2_tests {` region through its existing `// C2_TESTS_CLOSE_MARKER` from both versions. Assert only whitespace follows the closing marker.
- In the candidate unified text only, remove the exact formatted section-6 Site A and Site B snippets, each required to occur exactly once.
- Require equality of the remaining complete strings for each path. Assert marker/snippet uniqueness; a mismatch is a STOP, not permission to broaden the exclusions.

Implement this small check as an ephemeral Python command using `git show START:path` and `Path.read_text()`. Keep its exact source and output in the receipt; do not add a reusable framework or new project script. Use the admitted literal START SHA, not a moving ref. Normalize neither Rust tokens nor whitespace; rustfmt must leave all remaining source unchanged.

Also inspect the full diff to ensure changes inside permitted test modules are limited to the specified tests/helpers. Passing the region check does not authorize rewriting other tests in those modules.

## 10. Exact inventories and counts

### 10.1 Registered function counts

This plan adds **exactly one** Rust test function: `search::unified::c2_tests::c2_u12_corrupt_selected_unselected_and_multi_fault`. It expands existing functions; matrix rows and retries are not new test functions.

| Scope | START | Required after F1 |
|---|---:|---:|
| `search::unified::c2_tests::` | 23 | 24 |
| `search::execute::c2_physical_tests::` | 5 | 5 |
| New PERF-06 C2 unit functions | 28 | 29 |
| Dedicated integration functions | 9 | 9 |
| Total distinct PERF-06 C2 test functions | 37 | 38 |
| Historical broad `--lib c2_` selection | 38 | 39 if run after F1: 29 new-series + 10 older accounting tests |

The historical 38 broad-filter result remains true. Correct its attribution; never edit that raw output to say 28.

Run these inventories before and after changes:

~~~bash
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --list --format terse
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --list --format terse
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list --format terse
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib c2_ -- --list --format terse
~~~

Capture each command separately. Parse full lines ending `: test` into sets of fully qualified names. Reject duplicates, empty inventories, missing required names, unexpected new functions, or altered retained names. Compare baseline and final sets:

- Unified final minus baseline must be precisely the one U12 name above.
- Physical final must equal baseline.
- Integration final must equal baseline.
- The broad-filter set must equal the union of both C2 unit modules and the same ten older accounting tests.

Store both sets and the set-difference report. Do not infer registration counts by counting source substrings or summing rerun executions.

### 10.2 Required focused function commands

Each command below must select exactly **one** test function. Use its full name with `--exact`; a zero-test exit 0 fails the gate.

~~~bash
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u17_ordinal_unavailable_and_b3_refusal -- --exact --nocapture --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u21_work_budget_exhaustion_after_prior_segment -- --exact --nocapture --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u12_corrupt_selected_unselected_and_multi_fault -- --exact --nocapture --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p05_n_examination_and_scanned_frequency -- --exact --nocapture --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c2_i08_resource_cancellation_atomicity -- --exact --nocapture --test-threads=1
~~~

The expected focused case coverage is U17: five refusal/ready/ExactSet rows plus one no-eager-binding injected case and its recovery; U21: four boundary rows plus prescribed retries; U12: one pristine control plus nine fault rows and their specified controls/repeats; P05: six rows plus same-budget recovery; I08: retained memory/cancellation cases plus exact scanned success/failure/retry. Report those as cases, not inflated Rust test counts.

## 11. Feature acceptance, retained regressions, and execution topology

### 11.1 Full C2 feature suites

After the last test/helper/observation change, execute all commands below. Unit tests run in both serial and 8-thread modes so thread-local reset/probe cleanup is exercised under ordinary concurrent scheduling.

~~~bash
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --test-threads=1
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests:: -- --test-threads=8
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests:: -- --test-threads=8
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1
~~~

Required counts: 24, 5, 24, 5 and 9 respectively; zero ignored/failed C2 functions. Counts supplement the named assertions and case receipts.

### 11.2 Retained regression suites

~~~bash
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib b1_
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib b2_
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --lib b3_
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test perf06_b3_keys
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test pr15h_a_candidate_materialization
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test -p quervant-core --test pr15h_a2_dispatch
~~~

Record actual counts and ignored names rather than copying historical totals. Existing ignored external-service tests are not completed by these commands. No new ignore, filter, exclusion, retry or reduced concurrency may conceal a failure.

### 11.3 Topology and substitutions

| Evidence | Actual path | Permitted substitution / limit |
|---|---|---|
| U17/U21 and normal C2 unit differential | Real schema→analyzer→writer→committed MemoryDirectory bytes→snapshot→UnifiedSearcher→real collectors | MemoryDirectory is the existing deterministic storage backend; search/codec/scorer are real. |
| U12 | Native valid bytes copied, precisely mutated, rebuilt/checksummed with existing ContainerBuilder, new test snapshot, actual search path | Existing test snapshot constructor supplies ownership/identity; no mock decoding/scoring. Original committed storage is untouched. |
| Score precedence | Real C2 evaluator plus existing thread-local score-failure injector | Explicitly INJECTED_C2_ONLY; no fabricated Legacy injection. |
| P05 | Real reader/compiled leaves/expansion/stats; direct evaluator; actual meter and budget | Existing effective-live bitmap is the deterministic test input. Preparation and evaluator meters are separate. |
| I08 and all dedicated integration | Real local FsDirectory create/commit/reopen/query, public limits/cancellation, same immutable snapshot retry | No fake directory for this acceptance. |
| Hosted RustFS | Existing ordinary CI `rustfs` job, pinned image and real S3/core acceptance steps | Regression evidence for unchanged storage. It does not substitute for new C2 feature tests. |

No extra local RustFS deployment is required for this test/evidence fixup. The original C2 plan assigns real remote regression to the existing hosted job. The agent must still verify that its required bodies actually executed successfully in the new ordinary run; an ignored registration or a skipped job does not satisfy that gate.

## 12. Final mandatory QA and evidence capture

### 12.1 Local commands after final code/test changes

Every local cargo/script invocation in this plan runs in a child environment with `QUERVANT_PR15I_D3C_STRATEGY` and `QUERVANT_PR15I_D3C_PREFILTER_PROFILE` absent. Those existing all-features experiment overrides can otherwise change the intended duplicate mode. The command prefixes below enforce absence for the child process only. Do not alter user profiles, change the workflow, or mutate process-global environment from Rust tests. Record this sanitized invocation in each receipt. Apply the same prefix to development and baseline reruns, including commands named in prose.

Run from the repository root using the supported pinned toolchains. Execute every applicable command; a green CI run does not replace local execution.

~~~bash
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 fmt --all -- --check
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test --workspace --all-targets
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 test --workspace --all-targets --all-features
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 doc --workspace --no-deps
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 doc --workspace --all-features --no-deps
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.98.1 bench --workspace --no-run
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.85.0 fmt --all -- --check
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE cargo +1.85.0 test --workspace --all-targets --all-features
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE bash benchmarks/scripts/test-scripts.sh
git diff --check origin/main...HEAD
git diff --check
~~~

Both coverage configurations must report at least **85% production Rust workspace line coverage**, without changing exclusions or omitting crates/modules. Record covered/missed totals, measured percentage, configuration and source identity. Coverage alone cannot close an invariant.

Do not run several cargo builds/tests/coverage commands concurrently against the same target directory. Final workspace tests use their ordinary concurrency, not a global serial workaround for the known flake.

### 12.2 Log discipline

Use `set -o pipefail` when piping commands into `tee`, and record the actual cargo/script exit status. A logger exit 0 cannot convert a failing command into PASS. Prefer distinct numbered attempt filenames, such as `c2-f1-u17-attempt-01.txt`; check nonexistence before creating a receipt. Never truncate or overwrite an earlier attempt.

Each receipt identifies: command/arguments, working directory, toolchain versions, immutable source or tracked worktree diff hash, start/end timestamps, exit code, complete relevant output, selected test count, failure/ignore names and classification. Keep fixed per-case diagnostic lines for the focused tests. Bound the evidence to this task; do not collect unrelated environment secrets or full environment dumps.

Correctness tests may run during development. Final acceptance must be from the final test/source state. After final source/test changes, rerun affected feature/regression checks and all applicable mandatory final workspace QA, including coverage. A later documentation-only evidence commit may reuse those results only after a proven empty source/test/toolchain/CI diff.

### 12.3 Ordinary CI

Push normally to `dev/perf06-c2`. Observe the single ordinary pull_request workflow generated by that push. Preserve required jobs:

- `rust`;
- `msrv`;
- `python-benchmark-framework`;
- `benchmark-adapter-contract`;
- `rustfs`.

Record run ID/URL, event, head revision, PR merge/source revision where applicable, each job’s terminal status, and executed required steps. Distinguish GitHub’s PR merge-ref checkout from the actual PR head. Do not pretend one is the other.

Verify the run corresponds to the pushed source, or prove source equivalence for later documentation-only commits. Do not modify triggers, add branch push triggers, launch duplicate equivalent workflows, or invent a head-only workflow. Poll existing status without busy loops and keep the user informed. If CI is pending/inaccessible, finish independent work and report CI_PENDING/VERIFICATION_BLOCKED truthfully; do not merge or claim G8.

## 13. Evidence correction, documentation, and delivery

### 13.1 New report

Create `docs/pr-artifacts/perf-06-c/PERF06C2F1_EXECUTION_REPORT.md` with these sections, filling results only after actual execution:

1. **Identity:** repository, PR, actual branch, plan SHA-256, BASE, START, TESTED, FINAL, remote-verified SHA, tested worktree state/hash and toolchains.
2. **Starting defects and reconciliation:** F1-01..F1-05, original assertions and exact historical count correction.
3. **Pre-implementation correctness worksheet and rule ledger:** each applied decision ID, evidence and affected gate.
4. **Source delta:** exact helpers/tests/two observation sites; normal-build freeze receipt.
5. **Per-case acceptance:** every fixed U17/U21/U12/P05/I08 row with observed counters/error payloads/controls and evidence path.
6. **Inventory:** baseline/final name sets, 28/37 historical versus 29/38 final counts, old broad-filter explanation, matrix-case counts kept separate.
7. **QA:** command-by-command PASS/FAIL/BLOCKED/NOT APPLICABLE, actual test totals/ignored cases and both coverage measurements.
8. **CI/topology:** required job identities, real RustFS execution versus local FsDirectory feature acceptance.
9. **Failures and limitations:** all attempts, taxonomy, any open gate; INJECTED_C2_ONLY/pre-route boundaries and future performance qualification.
10. **Final adversarial self-review:** checklist below with evidence.
11. **Handoff:** derived disposition; draft/unmerged; G10 open; C3/C4 unstarted; precise pending external or reviewer action.

### 13.2 Append-only correction of original report

Append a dated section titled **“PERF-06-C2-F1 review corrections and superseding status”**. Its first sentence says the original report’s “Current disposition,” branch identity and specified coverage claims are historical and superseded by this new section/new F1 report.

State all of the following explicitly:

- Original new test functions were **28 unit + 9 integration = 37**. The logged 38-unit selection included ten older accounting tests.
- The old U17 “refusal” search never armed a refusal; the new evidence is the actual injected/refused path.
- The old U21 sweep and I08 cap30 did not prove a failure after prior collection. The new exact boundary receipt supplies that proof.
- U12 was absent and is now present only if its prescribed cases actually executed.
- P05’s accepted-success branch and I08’s accepted-success branch were removed from failure rows.
- Actual branch is `dev/perf06-c2`. Use the new report for current immutable revision identities.
- The resulting disposition comes from the gates, not from historical ready-for-review prose.

Do not edit past raw logs, retrospectively change observed counts, or claim a test ran earlier than it did. The append-only correction supersedes the stale text without erasing its history.

### 13.3 Narrow status documents

Append an F1 entry/link to `PERF06_SERIES_REGISTER.md` and update only the current C2 row/note in `PERF_OPTIMIZATION_ROADMAP.md`. Use the actual F1 disposition. No DONE/accepted/merged marker while G10 is open. Keep B-series measurement history and C3/C4 responsibilities unchanged.

### 13.4 Source freeze, commits and push

1. Complete final tests/QA against the final tracked test/source state. Record its exact diff/content hashes.
2. Commit the allowed source/test changes and verbatim plan. Record that commit as TESTED after proving the committed source/test bytes equal those actually tested.
3. Add reports/evidence/status docs in a separate documentation-only commit. Record it as FINAL.
4. Require an empty diff from TESTED to FINAL across `crates/`, `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, `.github/` and `benchmarks/`. Also require the guide/contract/protected files unchanged from START.
5. Push ordinarily to the existing remote branch, then fetch and verify the remote equals FINAL. Never force.
6. Observe normal CI. If adding final CI receipts causes another documentation-only commit, record the new FINAL/remote identity and prove the same protected-source equality. Do not fabricate a self-referential commit SHA inside the commit that would define it; the final chat/handoff supplies the final observed identity.
7. Prepare the PR body in a file and update existing metadata under execution authorization. Preserve draft state. No reviewer messages or approvals.

If changes remain unverified or blocked, preserve/push the allowed partial work only with a truthful blocked disposition and no completion claim; independent authorized work continues. Do not cross an applicable hard-stop boundary to obtain a green report.

### 13.5 Suggested PR description addition

Use this text after inserting actual completed evidence; remove or mark any unpassed gate accurately:

> **C2-F1 closes the independent review’s test and evidence gaps.** It exercises real optional B3 allocation refusal, proves a later-segment failure after earlier candidates populated the K+1 heap, adds the missing selected/unselected corruption and error-precedence matrix, and makes resource-limit tests require their exact expected outcomes.
>
> Production execution semantics are unchanged. Two cfg(test)-only observations expose owned-key fallback and completed-segment state; normal-build source equality is verified.
>
> The F1 report records exact module inventories, case-level observations, final local QA/coverage and ordinary CI. Historical C2 counts are corrected: 28 unit and 9 integration functions originally; 29 unit and 9 integration functions after the single new U12 test.
>
> PR remains draft/unmerged pending independent review and maintainer acceptance. C3/C4 remain unstarted; no performance measurement or claim is part of this fixup.

The coding agent must add the actual report link, TESTED/FINAL revisions and per-gate status; this prose is not evidence by itself.

## 14. Failure classification and bounded diagnostics

Every failing mandatory command is classified as: **introduced test/fixture regression**, **exposed feature implementation defect**, **deterministic pre-existing failure**, **nondeterministic/flaky failure**, or **environment/harness failure**. These specialize the guide’s required taxonomy without weakening it.

- A fixture syntax/import/borrow error introduced by F1 may be corrected only within the frozen design and allowlist; retain its initial failure and rerun affected checks.
- A runtime result contradicting a frozen error, budget, byte guard or semantic invariant is not a syntax fix. Stop that affected test and preserve the failure; do not alter production or relax expectations.
- Call a failure pre-existing only after relevant baseline reproduction or equivalent immutable baseline evidence for the same condition. Call it flaky only with evidence of nondeterminism.
- For the known `segment::reader::stored_blocks_reader_tests::certificate_retains_flat_offsets_and_hot_path_is_direct` counter failure, preserve the first failure. Permit at most one repeat of the identical failing command on unchanged F1 source and at most two identical baseline diagnostic executions in an isolated worktree at BASE. Stop diagnostics after those bounds. The purpose is classification, not rerunning until green.
- A known or newly reproduced flaky/pre-existing mandatory-gate failure remains **BLOCKED pending maintainer disposition** under the original C2 decision rules. A later green diagnostic does not silently waive it. Finish independent F1 work and report it.
- Do not use a lower thread count, ignore flag, changed seed/corpus, larger budget, skipped test, altered coverage exclusion, changed toolchain/dependency, or edited protected code to conceal failure.

Missing required tools/services/permissions permit reasonable non-destructive setup using the existing pinned versions. They do not authorize infrastructure redesign. Record the exact failed setup/command, finish independent work, and mark the gate blocked.

## 15. Preauthorized decisions and exception-handling matrix

**Categories:** AUTO = AUTO-RESOLVE; DEFER = DEFER AND CONTINUE; STOP = HARD STOP for affected work.  
**Owners:** Agent executes only the listed rule. Maintainer owns design/source amendments, waivers, acceptance and merge. Repository owner owns unavailable access/CI dependencies.  
Source admission and independent scope/contract STOP conditions always take precedence. Once those gates admit the work, a proven D10/D11/D13/D21a/D23a/D31a conformance mistake permits only its precisely listed correction and one focused verification before reclassifying the outcome. A successful listed repair resumes execution automatically; a remaining mismatch takes the applicable STOP. These corrections cannot change the corpus, expected semantics, byte guards, production behavior, source exclusions or architectural contract. All other simultaneous conditions use the most restrictive category. Every applied row goes into the decision ledger.

### 15.1 Source and scope

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Evidence / affected gate / owner |
|---|---|---|---|---|---|
| D01 | PR #131/head/main match pinned identities; branch clean for affected paths | AUTO | Admit START and execute remaining stages | Routine approval pause | Metadata/SHAs/status; G0; Agent. |
| D02 | Remote head is a descendant of pinned head, differing only in existing C2 execution-report/evidence text; guide, contracts, all source/tests/build/CI and original plan are byte-identical | AUTO | Preserve those docs; record actual START and complete diff; execute unchanged design | Treat code/test/contract drift as doc-only | Exact path diff and blob equality; G0/G9; Agent. |
| D03 | Main advanced, PR merged/closed/retargeted, or remote changed source/tests/contracts/toolchain | STOP | Preserve inspection; request plan amendment | Rebase, rewrite plan, assume equivalent semantics | Metadata/diff; G0; Maintainer. |
| D04 | Local task branch absent; remote exact branch exists | AUTO | Create tracking branch with section-4 command | New unrelated branch/PR | Branch refs; G0; Agent. |
| D05 | Local is strictly behind admitted remote with no affected dirty files | AUTO | Fast-forward via prescribed pull | Reset/force/merge commit | Before/after SHAs; G0; Agent. |
| D06 | Local ahead/diverged unexpectedly, or dirty change collides with allowed edits | STOP | Preserve work and report collision | Discard/stash/overwrite another author’s work | Status/diff; G0; Maintainer. |
| D07 | Foreign dirty/untracked items are outside all affected paths and cannot influence builds/tests | AUTO | Record and leave untouched; stage explicit paths only | git add -A, deletion or broad cleanup | Foreign path list; G0/G9; Agent. |
| D08 | Required fix demands protected path, public API, behavior, new dependency or new runtime flag | STOP | Record exact necessity and smallest amendment | Expand allowlist or disguise change as a test | File/symbol/invariant; G2/G9; Maintainer. |
| D09 | A missing required source/helper/marker contradicts pinned snapshot | STOP | Preserve mismatch; stop dependent implementation | Guess API/rename or create substitute abstraction | Exact symbol/marker/source; G0/G2; Maintainer. |

### 15.2 Tests, fixtures and observations

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Evidence / affected gate / owner |
|---|---|---|---|---|---|
| D10 | New helper fails only due to import/type/borrow/formatting syntax while the specified behavior and API are unchanged | AUTO | Correct the local test syntax/import/borrowing; retain failure and rerun | Change fixture, expected error, production ownership or algorithm | Compiler diagnostic/diff/rerun; G2–G5; Agent. |
| D11 | Expected B3 probe does not fire because a fixture was searched before arming | AUTO | Restore exactly the prescribed fresh-fixture order, then rerun once | Reuse warmed cache, remove probe assertion | Probe count and ordering diff; G3; Agent. |
| D12 | Probe remains unobserved on prescribed fresh fixture, or counts/fallback segments differ | STOP | Preserve result; stop affected U17 case | Accept output parity alone or loosen exact counts | Row/counters; G3; Maintainer. |
| D13 | Reset occurs after ScoreFailureArm/ForceLegacy is armed | AUTO | Move reset to the prescribed before-arm location and rerun | Modify injector/route behavior | Source order and focused receipt; G3/G4; Agent. |
| D14 | Any byte-layout/unique-payload/field-norm/live-mask/segment-order guard fails | STOP | Retain pristine bytes/guard output; request fixture amendment | Search random bytes, alter codec, use weaker corruption | Row, guard, source identity; G4; Maintainer. |
| D15 | A mandatory failure row still returns success, or any mandatory row disagrees with its specified outcome/error/counters, after fixture guards, freshness and reset/arm order are verified and any exactly applicable D10/D11/D13 correction is applied | STOP | Preserve failing test/log; classify exposed defect | Accept either outcome, broaden error match, tune cap | Exact expected/actual; G3–G5; Maintainer. |
| D16 | U12 column error occurs before route exactly as specified | AUTO | Assert both routes0; classify as pre-route evidence | Claim collector execution or push corruption later | Exact nested error/counters; G4; Agent. |
| D17 | DOC_KEYS error enters one numeric candidate but completes no callback | AUTO | Require numeric1/callback0 and documented semantics | Report zero invocations or alter observer location | D-row receipt; G4; Agent. |
| D18 | Synthetic score fault is C2-only | AUTO | Run specified unarmed shared-error controls and label injected evidence | Fabricate Legacy fault parity or edit scorer | S/U17 receipts; G3/G4; Agent. |
| D19 | Same-budget retry leaves nonzero ledger or fails | STOP | Preserve actual budget fields/outcome | Replace budget, manually zero fields, weaken RAII claim | P05 row; G5; Maintainer. |
| D20 | Same-snapshot retry returns different healthy response or corrupted source bytes changed | STOP | Preserve identities/bytes/results | Rebuild fixture instead of proving reuse | U12/U21/I08 receipt; G3–G5; Maintainer. |
| D21a | Exact filter selects zero solely because of a demonstrable invocation typo; the intended exact name is already present in the captured inventory | AUTO | Correct only the command to the prescribed registered name; rerun once and require exactly one selected test | Rename/add tests to fit a typo or accept zero selection | Inventory and both invocations; G6; Agent. |
| D21b | Inventory has unexpected/missing names, or corrected exact command still selects zero | STOP | Preserve inventory/commands; request amendment | Accept exit0 or broad-filter totals as substitute | Name sets and command; G6; Maintainer. |
| D22 | Serial passes but 8-thread feature run fails | STOP | Retain both receipts; inspect only approved thread-local reset/probe scope; apply D10/D13 only if their exact conditions hold | Force serial, add process-global locks or modify protected tests | Serial/parallel receipts; G3–G6; Maintainer for unlisted defect. |
| D23a | Source-region equality fails solely on identified agent-owned unauthorized drift, with the exact START bytes known and no foreign change in those hunks | AUTO | Restore only that drift to START; preserve prescribed test changes; rerun freeze once | Broaden exclusions, discard foreign work or preserve runtime drift | Full diff/restoration/receipt; G2/G9; Agent. |
| D23b | Source-region mismatch is foreign, unexplained, required by a new behavior, or persists after exact authorized restoration | STOP | Preserve mismatch and seek amendment | Broaden exclusions or rewrite production | Full diff/receipt; G2/G9; Maintainer. |
| D24 | A new test/fixture would be needed beyond the frozen rows to close an unforeseen issue | STOP | Report precise additional requirement | Design it autonomously or add a generic framework | Gap/invariant; affected G3–G5; Maintainer. |

### 15.3 Gates, delivery and external blockers

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Evidence / affected gate / owner |
|---|---|---|---|---|---|
| D25 | All focused checks pass after final tests; remaining mandatory stages are unblocked | AUTO | Continue full suites/QA/docs/delivery | Stop for routine confirmation | Receipts; G6–G9; Agent. |
| D26 | Final source/test/manifest/CI-related bytes change after QA | AUTO | Rerun every affected mandatory check, including workspace coverage for test/source changes | Reuse stale final QA | Changed paths/new TESTED; G7; Agent. |
| D27 | Only allowed docs/evidence changed after TESTED and protected-source diff is empty | AUTO | Reuse source QA; record new FINAL/remote linkage | Call changed executable code tested; rerun optional suites merely for prose | Empty diff/hashes; G9; Agent. |
| D28 | Required toolchain/dependency/service unavailable | DEFER | Attempt bounded non-destructive setup of pinned prerequisites; finish independent work | Substitute versions/waive required gate | Setup/command/blocker; affected G6–G8; Repository owner. |
| D29 | Required command fails and baseline reproduction establishes pre-existing behavior | DEFER | Preserve failures and baseline evidence; finish independent work; leave gate blocked | Protected fix, deletion, “unrelated” without evidence | Both revisions/commands; G7/G8; Maintainer. |
| D30 | Known certificate-counter flake or other nondeterminism appears | DEFER | Use section14’s bounded diagnostics; leave mandatory gate blocked pending disposition | Rerun to green, lower concurrency, hide attempt | All attempts/classification; G7/G8; Maintainer. |
| D31a | A specific assertion or registration explicitly required by this plan was omitted, and its exact prescribed implementation is known | AUTO | Add only that omission; execute its focused check once; then rerun all affected required suites and final QA/coverage under D26 | Invent additional cases or weaken the invariant | Omission-to-plan mapping, diff and reruns; G4–G7; Agent. |
| D31b | Coverage is below 85% or an invariant remains unproven after all prescribed assertions/registrations execute, or new unplanned design/testing is required | STOP | Preserve coverage/trace result and request amendment | Exclusions, threshold reduction or unrelated coverage tests | Coverage/trace gap; G4–G7; Maintainer. |
| D32 | CI pending or read access blocked while local work can continue | DEFER | Finish all local/delivery evidence, observe existing run when accessible, report pending/blocked | Claim pass, merge, start duplicate workflow | Run/source/status; G8; Repository owner. |
| D33 | Ordinary CI has terminal failure | DEFER | Classify exact source/job; use only applicable narrow rules for an introduced test error; retain gate failure | Ignore required job, change workflow or unrelated code | Job logs/source; G8; Agent/Repository owner. |
| D34 | Push rejected because remote advanced | STOP | Fetch/read new head, preserve local work, request disposition | Force-push, automatic rebase/merge or overwrite | Local/remote SHAs; G9; Maintainer. |
| D35 | Metadata update unavailable after source push | DEFER | Save exact prepared PR body/status in allowed evidence; report action blocked and leave G9 BLOCKED; accurate blocker reporting does not pass delivery | Post via another identity/service or claim update | Body/file and error; G9; Repository owner. |
| D36 | A next step requires benchmark/profiler/C3/C4/merge/approval | STOP | Keep future gate open and identify owner | Execute excluded work | Request/scope; G9/G10; Maintainer. |
| D37 | Any unforeseen case lacks an exact applicable rule | STOP | Stop affected work, report smallest decision; continue only proven independent prescribed work | Improvise design, silently defer acceptance, weaken tests | Observation/dependency map; affected gate; Maintainer. |
| D38 | Either named duplicate-mode experiment override is inherited by the local task environment | AUTO | Use the specified `env -u` child-process prefix for every local cargo/script invocation; keep all other settings and the user environment unchanged | Rust env mutation, profile edits or an altered expected mode | Sanitized command receipt; G0–G7; Agent. |

## 16. Acceptance gates and completion vocabulary

| Gate | PASS condition | Failure / open condition |
|---|---|---|
| G0 — Source admission | Actual branch/PR/START/BASE satisfy section4/matrix | Source or worktree conflict. |
| G1 — Correctness preparation | All worksheet answers, invariant/case map and decision ledger complete | Ambiguity unresolved. |
| G2 — Scope/implementation isolation | Exact two test-only sites; allowed test changes; normal-build equality | Runtime/protected drift. |
| G3 — Boundary acceptance | Every U17/U21 row and recovery executed with exact counters/errors/response parity | Any missing/refused/later-segment proof. |
| G4 — Adversarial acceptance | U12 pristine+nine rows, exact stage/error distinctions, controls/repeat/immutable bytes | Missing row or weaker oracle. |
| G5 — Resource/public acceptance | P05 six exact rows and same-budget recovery; strengthened real-FsDirectory I08 | Permissive success, wrong boundary, missing recovery. |
| G6 — Inventory/regression acceptance | 24+5+9 inventories; serial/8-thread features and retained regressions actually pass | Empty selection, wrong inventory, unexecuted/failing suite. |
| G7 — Local repository QA | All section12 local commands and both 85% coverage gates pass at final tested source; unresolved failure policy satisfied | Failed/unexecuted/waived-without-approval gate. |
| G8 — Hosted regression | Required ordinary CI jobs actually execute/pass on corresponding source, including real RustFS bodies | Pending, inaccessible, skipped or failed. |
| G9 — Evidence/delivery | Corrections/report/plan/source freeze complete, pushed normally, remote verified, draft preserved; required PR metadata update succeeded and accurately links the F1 report and observed gate status | Inaccurate claims, out-of-scope file, drift, delivery block. |
| G10 — Independent acceptance | Independent reviewer/maintainer explicitly accepts and separately authorizes subsequent action | Always OPEN at coding-agent handoff. |

Permitted final dispositions:

- **`PERF06_C2_F1_READY_FOR_INDEPENDENT_REVIEW`:** G0–G9 all PASS; G10 OPEN; draft/unmerged.
- **`PERF06_C2_F1_LOCAL_QA_PASS_CI_PENDING`:** all local feature/scope/evidence gates pass; only ordinary CI pending, with no known failure; G8 OPEN and delivery status explicit.
- **`PERF06_C2_F1_IMPLEMENTED_VERIFICATION_BLOCKED`:** prescribed changes exist but any required local/CI/topology/delivery gate cannot be verified or has an unresolved classified failure.
- **`PERF06_C2_F1_STOPPED_PLAN_AMENDMENT_REQUIRED`:** a hard-stop issue prevents completing the frozen design. List affected and independently completed work.

Do not report “C2 complete,” “accepted,” “merged,” “performance improved,” or G10 PASS from an agent self-review.

## 17. Reviewer checklist and final adversarial self-review

Require explicit yes/evidence or no/open-gate answers:

- [ ] Fresh main and PR head were admitted; actual branch is dev/perf06-c2.
- [ ] Production algorithms, APIs, formats, thresholds, budgets and error semantics are unchanged.
- [ ] Both new observation sites and their arguments/conditions compile out of normal builds; normal-build source comparison passes.
- [ ] U17 records the actual refusal callback and exact B3 refusal count on fresh caches.
- [ ] U17 proves first-only and second-only refusal, an all-ready control and a distinct ExactSet path.
- [ ] U17’s existing score injection is armed after reset; its label does not claim a malformed later-column or Legacy injected failure.
- [ ] U21 cap13/99 has a completed segment0 record with heap length3 and cumulative hits6 before the exact request error.
- [ ] U21 cap12 proves the “no prior completed segment” control; cap100 proves exact success.
- [ ] U12 covers winner, matching loser, nonmatch, final posting, malformed columns and competing errors.
- [ ] U12 pre-route columns rows have zero routes; key rows have one entered candidate and zero completed callbacks.
- [ ] Genuine byte faults have identical typed Legacy outcomes; score-injected rows are labeled C2-only.
- [ ] P05 verifies physical scanned occurrences despite tombstones and reuses the same zeroed budget after failure.
- [ ] I08 requires cap22 failure and cap23 success/retry through actual FsDirectory.
- [ ] Test registrations and case counts are separated; historical28/37 and final29/38 are accurate.
- [ ] Prior evidence is preserved and superseded explicitly; stale branch/status claims are corrected by dated errata.
- [ ] Full local QA and coverage actually ran after final source/tests; no attempt or failure is hidden.
- [ ] Ordinary CI/RustFS evidence is tied to the correct source; no duplicate workflow added.
- [ ] No benchmarks/profilers/C3/C4/merge occurred; PR stays draft with G10 open.

For each high-risk invariant, name a plausible incorrect implementation that would now fail: ignored refusal, generic replay after refusal, early partial success, skipped last posting, skipped unselected key validation, column-error reordering, candidate entry before complete scoring, wrong scanned-live accounting, leaked candidate budget, or a zero-test filter. Point to its exact counterexample row rather than citing overall coverage.

## 18. Final coding-agent report format

Return a concise report with:

~~~text
REPO / BRANCH / PR
BASE / START / TESTED / FINAL / REMOTE_VERIFIED
PLAN_SHA256
DISPOSITION
G0..G10 table (G10 OPEN)
F1-01..F1-05: exact fix and evidence
U17/U21/U12/P05/I08 case-table outcomes
Baseline and final registered inventories
Normal-build source-freeze result
Local command results and both coverage measurements
CI run, source identity and required-job results
All failures, diagnostics, deferred decisions and residual limits
Authorized file list / protected diff
Draft/unmerged state; C3/C4 unstarted; no performance claim
Precise independent-review or external dependency remaining
~~~

Execute all remaining authorized work continuously. Do not ask for permission at successful checkpoints. Stop only affected work under the explicit matrix, preserve the evidence and make the smallest unresolved decision clear.

## 19. Authoritative source references

All repository links below are pinned to the inspected head unless explicitly labeled main. Symbols and invariant names control if displayed line numbers drift.

- [Detailed PR Plan Authoring Guide](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md), including correctness, continuous execution, matrix and narrow-fixup requirements.
- [AGENTS.md](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/AGENTS.md) and [TESTING.md](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/TESTING.md).
- [C1 physical execution contract](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md).
- [Original C2 detailed plan](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/pr-artifacts/perf-06-c/PERF06C2_DETAILED_PLAN.md) and [original C2 execution report](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md).
- [Unified collector and unit fixtures](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/search/unified.rs): collector1367; observations3777; c2_tests11326; U17 12761; U21 12973; existing B3 copied-container fixture11017.
- [Evaluator and P05](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/search/execute.rs): observations1977; evaluator2383; direct tests2550; P05 3028.
- [Real FsDirectory C2 tests](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/tests/perf06_c2_physical.rs): I08 around995.
- [Reader and B3 probe API](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/segment/reader.rs), [posting codec](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/segment/postings.rs), [column codec](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/segment/column.rs).
- [Scoring/statistics](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/search/score.rs), [work meter](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/search/work.rs), [typed error wrappers](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/crates/quervant-core/src/search/error.rs).
- [CI workflow](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/.github/workflows/ci.yml).
- [Historical broad-filter unit receipt](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/pr-artifacts/perf-06-c/evidence/c2-unit-c2-serial.txt) and [historical integration receipt](https://github.com/yduchesne/quervant/blob/46ccab0a606a56a8b9034ab4db5c9c4df969d098/docs/pr-artifacts/perf-06-c/evidence/c2-integration.txt).
- [Fresh accepted main](https://github.com/yduchesne/quervant/commit/bc726420cede2e26681d6e8192b45a5d0169abbf) and [historical tested-source to inspected-head comparison](https://github.com/yduchesne/quervant/compare/cc2691bb9ff061cd149b990ab987a4db9b2ab400...46ccab0a606a56a8b9034ab4db5c9c4df969d098).

**Planning limit:** source inspection and independent plan review establish the specificity of these instructions, not the future execution results. All F1 test, compilation, coverage, CI and acceptance claims remain to be produced by execution.

