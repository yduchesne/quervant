# Quervant v0.1-bench — Benchmarking Infrastructure Refactoring Roadmap

**Status:** Proposed high-level PR series; no BM implementation PR is implied completed.

## 1. Position in the release plan

`v0.1-bench` is an **interim engineering milestone** between the current Quervant v0.1 implementation and the post-refactoring v0.1 codebase. It is not v0.2 and does not change product feature scope. The BM series modernizes performance benchmarking and verification infrastructure while retaining optimization outcomes and experimental history.

Human-readable target process: [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md). Source of truth for architectural requirements: [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md). Migration and historical-parity obligations: [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md). BM numbers denote implementation PRs, **not package names, runtime identifiers, schemas or experiment IDs**.

## 1.1 Mandatory acquisition boundary and testing strategy

**BM-01 through BM-08 are simulation-first implementation PRs: NO NEW REAL TIMED BENCHMARK ACQUISITION.** This prohibition includes partial or exploratory live timed runs, official A/A and treatment campaigns, Criterion timing and live performance profiling. An idle machine is not an exception. Permitted work includes compile-only benchmark checks, ordinary Rust/Python tests, untimed correctness checks, deterministic synthetic acquisition and read-only historical evidence replay.

The **first real full-scale benchmark qualification takes place in BM-09**, only after final synthetic qualification, frozen official protocols and explicit host/series authorization. The BM-09 implementation plan must enumerate the real reference campaigns and mandatory external dependencies; blocked real acquisition blocks v0.1-bench completion. Historical data or synthetic samples are not substitutes for new BM-09 real evidence.

We require **L1 deterministic unit/property and adversarial tests**, **L2 end-to-end simulated lifecycle qualification**, and **L3 real performance qualification only in BM-09**. See [BENCHMARKING_METHODOLOGY.md §10.4](BENCHMARKING_METHODOLOGY.md#104-verifying-our-methodology-before-running-real-benchmarks) and [BENCHMARKING_MIGRATION.md §6](BENCHMARKING_MIGRATION.md#6-simulation-first-testing-and-ci-transition).

## 2. Dependency sequence

```text
BM-01 Contracts and inventory
  └── BM-02 Common primitives and evidence
        └── BM-03 Protocol and execution engine
              └── BM-04 Analysis and policy
                    └── BM-05 Independent verification
                          └── BM-06 Acceptance and attestation
                                └── BM-07 Reference retained-key migration
                                      └── BM-08 Cross-engine integration
                                            └── BM-09 Real qualification, consolidation and closeout
```

The sequence is intentionally conservative: each PR is reviewable and must remain safe to merge on its own. A future implementation plan may split a BM item into sub-PRs without changing the top-level contracts or reusing BM numbers.

## 3. High-level PR descriptions

### BM-01 — Foundation: inventory, naming, schemas and CLI contracts
- Enumerate legacy runners, verifiers, protocols, evidence schemas and source dependencies from fresh main; classify migrate/read-only/retain.
- Establish `benchmarks/quervant_bench/` package skeleton, `benchmarks/experiments/` layout, semantic identifiers and versioned schemas.
- Define strict typed experiment/protocol/adapter/receipt contracts, canonical serialization, error codes, CLI contracts and profile semantics.
- Establish deterministic synthetic/golden fixture conventions, reproducible property-test seeds and the fast/full-synthetic test profiles; prohibit any real timing in BM-01.
- **Exit:** no PR-specific name in new public contracts, full legacy format registry, approved compatibility inventory and passing L1 contracts/negative tests. **No real acquisition.**

### BM-02 — Shared utilities, provenance, evidence admission
- Consolidate strict JSON, hashing, safe archives/path confinement, Git/source/build provenance, exclusive publication and metadata collection.
- Implement admission receipts with complete dependency bindings and invalidation tests.
- Extract host-capability probes/readiness rules without reusing time-bound authorization.
- **Exit:** matching legacy acceptance/rejection on deterministic fixtures; property/security/adversarial and synthetic-vs-real-origin rejection tests pass; unchanged evidence can be admitted once and verified by receipt without weakening trust. **No real acquisition.**
- **Status (BM-02 implementation PR):** implemented on `dev/bm02-evidence-admission`; local Python L1 contract/security tests, MSRV/stable Rust QA, workspace coverage and deterministic legacy parity pass; remote CI is pending PR creation. Only synthetic/simulated admission receipts are issued; real evidence remains read-only and out of scope. **No real acquisition.**

### BM-03 — Declarative protocol and generic execution
- Implement pre-acquisition freeze, schedule generation/validation, controller state machine, measurement envelopes, readiness checks, adapter invocation and failure/STOP taxonomy.
- Introduce a deterministic **synthetic adapter on the real public adapter interface**, injected logical clock, seeded scheduler, simulated host readiness and failure-injectable evidence store. Quervant adapter receives untimed semantic contract tests.
- **Exit:** synthetic protocol→readiness/A/A→balanced blocks/slots→sealed evidence, plus crash/STOP/duplicate/missing-slot tests, match approved historical semantics; no unauthorized retries or evidence promotion. **No real timed measurements permitted.**

### BM-04 — Analysis engine and policy framework
- Implement reusable paired statistics, block exclusions, bootstrap, geometric means and direction-aware metric comparisons.
- Implement strictly typed, versioned policies with eligibility/guardrails/resource limits/selection precedence; preserve exact numeric boundary semantics.
- **Exit:** independent mathematical golden/property cases and synthetic statistics/policy scenarios pass; reproduce frozen historical D3-C analytical outputs/decisions in read-only replay where authentic evidence is available, report missing history explicitly; no implicit tie or missing data fallback. **No real acquisition.**
- **Status (BM-04 implementation PR):** implemented on `dev/bm04-analysis-policy` as an internal `quervant_bench/analysis/` package plus a new `synthetic-analysis-smoke` fixture. Local gates: 142 new Python L1 tests (504 total, 0 failures), independent §19 bootstrap-index golden, a full 24-slot/48-envelope/144-sample simulated vertical slice, MSRV/stable Rust QA with 92.70% line coverage, and `cargo bench --no-run` compile only. Output is synthetic/simulated in-memory evidence only: no CLI verb, no Gate A–E receipt, no durable Gate B artifact and no real timing. Historical D3-C parity is `EVIDENCE_UNAVAILABLE` (no authentic external archive); the synthetic fixture never substitutes for it. Independent recomputation remains BM-05 and remote CI is pending. **No real acquisition.**

### BM-05 — Independent correctness, statistics and decision verification
- Define separable reference-verifier interfaces; port T7-F2 independent oracle semantics without sharing primary policy decision functions.
- Implement mutation and adversarial suites covering modified evidence, CI, memory, candidate eligibility and selected status.
- **Exit:** deterministic policy/mutation matrix passes; exact historical decision parity for required available evidence, deliberate corruption rejection and documented scope of independent checks. **No real acquisition.**
- **Status (BM-05 implementation PR):** implemented on `dev/bm05-independent-verification` as a separable `quervant_bench/verification/` reference verifier plus hand-authored reference vectors. It independently reconstructs the full BM-04 analysis and policy documents from sealed synthetic treatment records, including both estimators, symmetric pruning, the SHA-256 paired bootstrap, reason precedence, GM ranking and tie selection, and rejects structurally valid forgeries. Local targeted Python suites pass; independence is enforced by an AST audit and a runtime poison probe. Historical D3-C parity remains `EVIDENCE_UNAVAILABLE` (empty external archive) and no legacy path is retired. Output is in-memory synthetic/simulated verification only: no receipt, persistence, CLI verb, adapter launch or real timing. Remote CI is pending. **No real acquisition.**

### BM-06 — Gate coordinator, QA receipts and final attestation
- Implement A–E logical dependency graph, reuse/revalidation policy, framework QA versus source QA versus experiment acceptance, deterministic output checks and content-addressed final manifest.
- Replace experiment-specific hardcoded file/test/QA rosters in shared infrastructure with versioned qualification profiles; retain legacy rosters as historical contracts.
- **Exit:** complete **simulated end-to-end A–E qualification** passes, including full negative/fault-injection matrix; unchanged dependencies reuse valid receipts, while changed code/rosters/inputs reject or requalify; synthetic artifacts cannot be promoted as real; no cached live readiness. **No real acquisition.**
- **Status (BM-06 implementation PR):** implemented on `dev/pr-bm06` as an internal `quervant_bench/qualification/` package: sealed Gate A admission with a canonical 15-file inventory, Gate B over the existing BM-04 derivation, Gate C over the existing BM-05 independent verifier, pinned/simulated framework+source QA gates, Gate D acceptance and an acyclic Gate E freeze attestation plus manifest. Output is exactly 15 canonical files with the manifest as the last completion marker; publication is exclusive, crash-aware and never repaired; valid reuse revalidates all anchors/edges without re-running BM-04/BM-05. Local Python (756 total, 0 failures, 1 pre-existing skip; 93 new qualification tests) and MSRV/stable Rust gates pass with 92.68% line coverage and `cargo bench --no-run` compile only. The framework/source QA fixture is **simulated L2 evidence**, not a CI attestation; historical parity remains `EVIDENCE_UNAVAILABLE`; no CLI verb, real timing or official qualification exists and remote CI is pending. **No real acquisition.**

### BM-07 — Retained-key benchmark reference migration
- Move the *new* retained-key-dedup experiment definition onto generic services; keep historic D3-C/T7/T7-F2 files unchanged.
- Run dual-path verification against previously frozen artifacts, if available, or label unavailable evidence explicitly; no fabricated measurements.
- Exercise admission, statistics, policy, reference verification and attestation through the standard CLI against **synthetic and read-only historical inputs only**.
- **Exit:** complete L1/L2 retained-key reference coverage and required offline equivalence matrix, or explicit evidence-unavailable STOP for unmet mandatory parity; no copied PR-specific controller/verifier; original experiment-only conclusions remain unchanged. **No new real measurements.**
- **Status (BM-07 implementation PR):** implemented on `dev/pr-bm07` as a new synthetic-only `synthetic-retained-key-reference` catalog plus a thin `quervant_bench/migrations/` package. The real BM-03→BM-06 path qualifies a four-arm/eight-lane, 4-block simulated study (literal effects 0.94/0.79/0.815; policy selects `prefilter`), and the five reserved verbs now return bounded read-only views only when `--offline` is explicit and a caller-provisioned workspace plus independent anchors fully revalidate a committed 15-file bundle. `run` remains exit 77. The BM-06 source roster gained exactly the new `migrations` package and the simulated QA anchors were re-frozen from final tracked source. Historical D3-C/T7/T7-F2 bytes are unchanged; the external archive is empty, so evidence is `EVIDENCE_UNAVAILABLE`, numeric/decision parity is `NOT_EXECUTED`, and historical acceptance remains BLOCKED without legacy retirement. Local Python and MSRV/stable Rust gates pass with Rust line coverage above 85%; remote CI is pending. **No real acquisition.**

### BM-08 — Cross-engine reference migration and adapter proof
- Apply generic adapter/protocol/results contracts to Quervant/Tantivy/Lucene comparative harness.
- Retain semantic oracle and noncomparable-lane rules, per-engine build identity, cache regime, and source/workload reproducibility. Run cross-engine **synthetic acquisition** on the same execution/gate core and untimed adapter contract tests; never execute timed engine comparisons.
- **Exit:** L1/L2 complete for both search-latency and cross-engine families (including noncomparable lanes, faults and synthetic A–E attestation) with unchanged historical evidence and no fabricated competitive claim. **No real timing.**

### BM-09 — Real full-scale benchmark qualification, consolidation and v0.1-bench closeout

**This is the first BM PR authorized to execute real timed benchmark campaigns.** Qualification is mandatory, not optional.
- Re-run the complete required L1/L2 synthetic suite against final source. Verify scope separation and all pending historical compatibility obligations; do not substitute synthetic PASS for real qualification.
- Prepare and independently approve **frozen real protocols** for representative retained-key/search and cross-engine benchmark families. Pin source/build/corpus/semantics, environment, exact schedules, host readiness, A/A controls, policies, stopping rules and acceptance evidence; establish external engine/tool availability *before* acquisition.
- On an authorized and genuinely qualified host, run the **full real benchmark series** for the prescribed representative families, not a shortened cherry-picked smoke test. Admit, independently analyze/verify, accept and attest actual measured artifacts through the unified A–E gates.
- Preserve failed/blocked campaigns and refuse quiet retries, protocol relaxation, invented measurements, cross-engine semantics substitutions or conditional waivers. If mandatory real conditions are absent, record BLOCKED and do not close out v0.1-bench.
- Only **after** real qualification and historical equivalence are accepted, review legacy components item-by-item for retain, compatibility-wrapper, archived-only or safe retirement. Keep all frozen historical artifacts and approved read-only adapters.
- Update canonical documentation directly under `docs/` (including `docs/BENCHMARKING.md`, CLI instructions and related indexes) to reflect the adopted methodology and **implemented** architecture. Preserve `docs/benchmarking/` as historical and mark its README accordingly.
- **Exit:** real, source/protocol-frozen retained-key and cross-engine qualification evidence accepted; complete synthetic suite PASS; required historical parity PASS; valid attestation and stable real/synthetic provenance boundaries; safe compatibility cleanup; no new PR-named shared infrastructure, no unnecessary duplicate gates and no unqualified performance claim.

## 4. Cross-cutting requirements for every BM PR

1. **No implementation improvisation:** each coding PR gets a separately reviewed detailed implementation plan consistent with the architecture and migration contracts; unknown conditions STOP.
2. **No unrelated optimization or product change:** benchmarking refactoring must not silently alter search code or policy-selected defaults.
3. **No historical mutation:** frozen evidence, receipts, protocol identities and existing verdicts remain untouched.
4. **Independent assurance:** reference calculators/oracles remain independently implemented where independence is an acceptance property.
5. **Tests first for behavioral changes:** include positive, negative, malformed, boundary and fault-injection tests; enforce required coverage/QA policy.
6. **Native Linux and WSL2:** capability-based checks; fail closed for unsupported systems.
7. **Strict stage boundary:** BM-01–BM-08 prohibit **all new real timed benchmark acquisition** (including unofficial quick pilots, A/A, Criterion timing and profiling); only BM-09 may perform the first real full-scale campaigns, after separately frozen protocol, readiness and authorization. Offline replay and untimed functional checks are permitted earlier.
8. **Compatibility and rollback:** document which legacy paths remain live and how to revert the new path without invalidating evidence.
9. **No false completion claims:** distinguish source ready, tests passed, *simulated* qualification, historical offline replay, and *real* acquisition/attestation; the real acceptance path must reject synthetic artifacts.
10. **Required suites:** every affected BM PR passes fast deterministic PR checks and the complete applicable synthetic qualification suite before acceptance; no required tests may be waived to preserve speed.

### Required test coverage by BM PR

| PR | Evidence required before acceptance | Real timed acquisition |
| --- | --- | --- |
| BM-01 | strict schema/CLI/identity and seeded property-test foundation; synthetic golden fixtures | **Prohibited** |
| BM-02 | archive/provenance negative tests, receipt mutation and scope binding | **Prohibited** |
| BM-03 | deterministic simulated schedule, readiness/A/A, execution state machine, interruptions | **Prohibited** |
| BM-04 | independent statistics golden cases, bootstrap/pruning properties, policy boundaries | **Prohibited** |
| BM-05 | independent reference decisions, altered evidence/policy mutation cases, offline parity | **Prohibited** |
| BM-06 | full synthetic A–E acceptance, frozen output/QA roster invalidation and attestation | **Prohibited** |
| BM-07 | retained-key synthetic end-to-end and required offline historical equivalence | **Prohibited** |
| BM-08 | cross-engine synthetic end-to-end and untimed semantic parity; both families share core | **Prohibited** |
| BM-09 | all L1/L2 + authorized **real full-scale campaigns**, real A–E acceptance and final closeout | **Required** |

## 5. Milestone checkpoints

| Checkpoint | After | Required outcome |
| --- | --- | --- |
| C1 — Contracts stable | BM-01 | **Implemented; local gates PASS, remote CI pending.** Six versioned closed schemas, semantic identity/canonical encoding, read-only `inspect`, complete legacy format registry and 82 passing L1 contract tests. Contracts are frozen only after the implementation PR's CI job passes. |
| C2 — Mechanics reusable | BM-03 | execution/evidence reuse and replay contract tests pass. **BM-03 implementation PR local gates PASS (362 Python L1 tests, MSRV/stable Rust QA, coverage); remote CI pending.** |
| C3 — Decisions independently checked | BM-05 | analysis/policy and oracle parity with adversarial rejection. **BM-04 primary analysis/policy engine is implemented and locally verified (synthetic only); independent verification is still BM-05.** |
| C4 — Qualification reusable | BM-06 | safe gate receipts/QA deduplication/final manifests |
| C5 — Cross-family proven | BM-08 | retained-key and cross-engine use identical core services. **BM-08 local implementation and correctness gates PASS (synthetic only): 90 cross-engine tests, 942-test full Python suite, MSRV/stable Rust QA and 92.69% line coverage. Cross-engine labels are logical sample streams bound to the one BM-03 simulator; no engine was queried or timed. Historical numeric/decision parity remains `NOT_EXECUTED`/`BLOCKED`. Final-head CI and independent review pending.** |
| C6 — v0.1-bench completed | BM-09 | **real full-scale qualification and acceptance** of the required representative families, safe legacy consolidation, current docs integrated and historical folder retained |

## 6. Out-of-scope / deferred

Actual performance optimization, algorithm selection changes, distributed benchmark orchestration, automatic cloud provisioning, public performance claims and reinterpretation of old statistical outcomes are not deliverables of v0.1-bench. Future workload adapters may be added after the common architecture is established.

## 7. Exit decision

`v0.1-bench` may be marked **COMPLETE** only after BM-01 through BM-09 acceptance, all applicable roadmap checkpoints, **BM-09 real full-scale qualification** and migration exit criteria pass. Synthetic framework PASS alone is insufficient. At that point the post-refactoring codebase is still Quervant **v0.1**. Any Git release/tag, merge of experimental optimizations, or transition to v0.2 needs a separate decision.
