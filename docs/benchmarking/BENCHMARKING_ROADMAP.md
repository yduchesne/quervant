# Quervant v0.1-bench — Benchmarking Infrastructure Refactoring Roadmap

**Status:** Proposed high-level PR series; no BM implementation PR is implied completed.

## 1. Position in the release plan

`v0.1-bench` is an **interim engineering milestone** between the current Quervant v0.1 implementation and the post-refactoring v0.1 codebase. It is not v0.2 and does not change product feature scope. The BM series modernizes performance benchmarking and verification infrastructure while retaining optimization outcomes and experimental history.

Human-readable target process: [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md). Source of truth for architectural requirements: [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md). Migration and historical-parity obligations: [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md). BM numbers denote implementation PRs, **not package names, runtime identifiers, schemas or experiment IDs**.

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
                                            └── BM-09 Consolidation and documentation closeout
```

The sequence is intentionally conservative: each PR is reviewable and must remain safe to merge on its own. A future implementation plan may split a BM item into sub-PRs without changing the top-level contracts or reusing BM numbers.

## 3. High-level PR descriptions

### BM-01 — Foundation: inventory, naming, schemas and CLI contracts
- Enumerate legacy runners, verifiers, protocols, evidence schemas and source dependencies from fresh main; classify migrate/read-only/retain.
- Establish `benchmarks/quervant_bench/` package skeleton, `benchmarks/experiments/` layout, semantic identifiers and versioned schemas.
- Define strict typed experiment/protocol/adapter/receipt contracts, canonical serialization, error codes, CLI contracts and profile semantics.
- Deliver tests for malformed configuration, duplicate fields, unsupported schemas and identity correctness.
- **Exit:** no PR-specific name in new public contracts, full legacy format registry and approved compatibility inventory. No acquisition.

### BM-02 — Shared utilities, provenance, evidence admission
- Consolidate strict JSON, hashing, safe archives/path confinement, Git/source/build provenance, exclusive publication and metadata collection.
- Implement admission receipts with complete dependency bindings and invalidation tests.
- Extract host-capability probes/readiness rules without reusing time-bound authorization.
- **Exit:** matching legacy acceptance/rejection on representative fixtures; security/adversarial tests pass; unchanged evidence can be admitted once and verified by receipt without weakening trust.

### BM-03 — Declarative protocol and generic execution
- Implement pre-acquisition freeze, schedule generation/validation, controller state machine, measurement envelopes, readiness checks, adapter invocation and failure/STOP taxonomy.
- Introduce Quervant adapter and deterministic replay/dry-run fixtures.
- **Exit:** balanced-block and error-path parity with a selected historical search benchmark, including no unauthorized retries or evidence promotion. No new official measurements required.

### BM-04 — Analysis engine and policy framework
- Implement reusable paired statistics, block exclusions, bootstrap, geometric means and direction-aware metric comparisons.
- Implement strictly typed, versioned policies with eligibility/guardrails/resource limits/selection precedence; preserve exact numeric boundary semantics.
- **Exit:** reproduce frozen historical D3-C analytical outputs/decisions in read-only replay; record any schema-normalization differences; no implicit tie or missing data fallback.

### BM-05 — Independent correctness, statistics and decision verification
- Define separable reference-verifier interfaces; port T7-F2 independent oracle semantics without sharing primary policy decision functions.
- Implement mutation and adversarial suites covering modified evidence, CI, memory, candidate eligibility and selected status.
- **Exit:** exact historical decision parity and deliberate corruption rejection; documented scope of independently checked assertions.

### BM-06 — Gate coordinator, QA receipts and final attestation
- Implement A–E logical dependency graph, reuse/revalidation policy, framework QA versus source QA versus experiment acceptance, deterministic output checks and content-addressed final manifest.
- Replace experiment-specific hardcoded file/test/QA rosters in shared infrastructure with versioned qualification profiles; retain legacy rosters as historical contracts.
- **Exit:** unchanged dependencies reuse valid receipts; mutation, changed code or invalidated roster causes automatic rejection/requalification; no cached live readiness; stable final report and fail-closed freeze behavior.

### BM-07 — Retained-key benchmark reference migration
- Move the *new* retained-key-dedup experiment definition onto generic services; keep historic D3-C/T7/T7-F2 files unchanged.
- Run dual-path verification against previously frozen artifacts, if available, or label unavailable evidence explicitly; no fabricated measurements.
- Exercise admission, statistics, policy, reference verification and attestation through standard CLI.
- **Exit:** complete recorded equivalence matrix for search-latency benchmark; no copied PR-specific controller/verifier; original experiment-only conclusions remain unchanged.

### BM-08 — Cross-engine reference migration and adapter proof
- Apply generic adapter/protocol/results contracts to Quervant/Tantivy/Lucene comparative harness.
- Retain semantic oracle and noncomparable-lane rules, per-engine build identity, cache regime, and source/workload reproducibility.
- **Exit:** demonstrates genuinely reusable framework across two different benchmark families with unchanged historical cross-engine evidence and no fabricated competitive claim.

### BM-09 — Legacy consolidation, documentation and v0.1-bench closeout
- Review legacy inventory item-by-item for retain, compatibility-wrapper, archived-only and safe retirement.
- Preserve historical frozen directories/artifacts and required read-only adapters.
- Update current canonical docs directly under `docs/` (including `docs/BENCHMARKING.md`, CLI usage, related roadmap/index references); integrate the **adopted methodology and implemented** architecture, not unimplemented aspirations.
- Retain this `docs/benchmarking/` directory as historical and update its README accordingly.
- **Exit:** complete v0.1-bench acceptance report, working cross-family examples, traceable historical qualifications, no new PR-named infrastructure and no duplicate acceptance work for unchanged qualified dependencies.

## 4. Cross-cutting requirements for every BM PR

1. **No implementation improvisation:** each coding PR gets a separately reviewed detailed implementation plan consistent with the architecture and migration contracts; unknown conditions STOP.
2. **No unrelated optimization or product change:** benchmarking refactoring must not silently alter search code or policy-selected defaults.
3. **No historical mutation:** frozen evidence, receipts, protocol identities and existing verdicts remain untouched.
4. **Independent assurance:** reference calculators/oracles remain independently implemented where independence is an acceptance property.
5. **Tests first for behavioral changes:** include positive, negative, malformed, boundary and fault-injection tests; enforce required coverage/QA policy.
6. **Native Linux and WSL2:** capability-based checks; fail closed for unsupported systems.
7. **No official benchmark acquisition without separately frozen protocol, host readiness and authorization.** Synthetic/fixture-based verification is the default during refactoring.
8. **Compatibility and rollback:** document which legacy paths remain live and how to revert the new path without invalidating evidence.
9. **No false completion claims:** distinguish source ready, tests passed, admission qualified, statistical verification and final attestation.

## 5. Milestone checkpoints

| Checkpoint | After | Required outcome |
| --- | --- | --- |
| C1 — Contracts stable | BM-01 | schema/CLI/identity contracts frozen for implementation |
| C2 — Mechanics reusable | BM-03 | execution/evidence reuse and replay contract tests pass |
| C3 — Decisions independently checked | BM-05 | analysis/policy and oracle parity with adversarial rejection |
| C4 — Qualification reusable | BM-06 | safe gate receipts/QA deduplication/final manifests |
| C5 — Cross-family proven | BM-08 | retained-key and cross-engine use identical core services |
| C6 — v0.1-bench completed | BM-09 | current docs integrated; historical folder retained |

## 6. Out-of-scope / deferred

Actual performance optimization, algorithm selection changes, distributed benchmark orchestration, automatic cloud provisioning, public performance claims and reinterpretation of old statistical outcomes are not deliverables of v0.1-bench. Future workload adapters may be added after the common architecture is established.

## 7. Exit decision

`v0.1-bench` may be marked **COMPLETE** only after BM-01 through BM-09 acceptance, all applicable roadmap checkpoints and the migration exit criteria pass. At that point the post-refactoring codebase is still Quervant **v0.1**. Any Git release/tag, merge of experimental optimizations, or transition to v0.2 needs a separate decision.
