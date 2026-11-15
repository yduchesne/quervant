# Quervant Benchmarking Infrastructure — Target Architecture

**Status:** Proposed normative architecture for interim **v0.1-bench**; not implemented merely by merging this document.

**Methodology:** [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md) is the human-oriented specification of the target experimental process: terms (lanes, arms, blocks, slots and samples), randomized balanced assignment, acquisition, symmetric post-acquisition pruning, paired inference and the purpose of pre-acquisition and A–E acceptance gates. This architecture specifies **how the software implements** that process. Where a section below summarizes methodological behavior, consult the methodology for explanations and the experiment's frozen protocol for exact authoritative parameters.

## 1. Goals and scope

Provide a reusable benchmarking system for Quervant's search, indexing, mutations, storage, compaction, distributed, graph and ontology workloads, including optional cross-engine comparison against external implementations. Make a new experiment possible without copying another PR's controller, verifier, admission implementation, or freeze machinery.

Goals:
1. Preserve deterministic correctness checks and reproducible, meaningful performance comparisons.
2. Separate acquisition, verification, statistical analysis, policy decision, acceptance and attestation.
3. Prevent repeated work through content-bound, dependency-aware gate receipts.
4. Preserve intentionally independent oracles and statistical verification; **do not deduplicate independent assurance**.
5. Use semantic and versioned names; PR numbers belong only in optional provenance.
6. Maintain fail-closed integrity, readiness, authorization and result handling.
7. Support native Linux and WSL2 through capability-based host adapters; do not assume that all hosts use WSL2.
8. Preserve all historical frozen source/evidence/protocol/receipt bytes and conclusions.

Non-goals: change Quervant's search-engine optimization decisions; remeasure historical studies; silently reclassify historical results; rewrite Criterion or external engine implementations; create a general distributed benchmark service in this milestone.

## 2. Package and repository boundaries

Target layout (new components introduced incrementally):

```text
benchmarks/
  quervant_bench/
    __init__.py
    cli.py
    config/             # strict typed schemas, version registry, canonical encoding
    protocol/           # validation, schedule compilation, source/protocol freeze
    execution/          # controller, host readiness, runs, process isolation, recording
    adapters/           # contracts for Quervant, external engines, profiling tools
    evidence/           # admission, provenance, safe archive readers, manifests, receipts
    analysis/           # independent-of-policy statistical primitives and comparisons
    policy/             # typed evaluator, candidate eligibility, guardrails, selection
    verification/       # independent reference calculations, correctness oracle contracts
    acceptance/         # dependency-aware gate coordinator and framework QA binding
    attestation/        # immutable logical snapshot and report/receipt generation
    reporting/          # normalized results and human-readable reports
    legacy/             # explicitly versioned read-only historical format adapters
    tests/              # framework unit, adversarial, integration, contract tests
  experiments/
    retained-key-dedup/
      experiment.yaml
      workloads.yaml
      selection-policy.yaml
    cross-engine-keyword/
      experiment.yaml
      workloads.yaml
  reports/               # historical reports remain as-is during migration
  scripts/               # compatibility entry points until explicitly retired
docs/
  BENCHMARKING.md        # canonical CURRENT documentation; updated after rollout
  benchmarking/          # interim docs; subsequently historical
```

Directory names above establish architectural responsibilities, **not a mandate to split every function into its own module**. Module/API details may be refined only through an approved BM-series PR design, without violating the contracts below. Avoid ambiguous dual ownership: protocol freeze occurs before acquisition; evidence/attestation freeze binds finalized results after acceptance.

## 3. Identity model

The following identities MUST remain distinct:
- **experiment_id:** stable semantic question, e.g. `retained-key-dedup` or `cross-engine-keyword`.
- **protocol_id / protocol_version / protocol_digest:** exact measurement design, prerequisites, schedule, stop/retry rules and analysis settings.
- **workload_id / workload_digest:** exact corpus, fixtures, lanes, query semantics and cache regime.
- **arm_id:** stable variant identifier such as `baseline`, `prefilter-bitset`, `exact-set`; resolved to immutable source/binary/runtime identities.
- **run_id:** unique execution instance, never the experiment ID; a qualified result also identifies its control/campaign/series.
- **analysis_id:** exact evidence, method and analysis tool identity.
- **policy_id / policy_version / policy_digest:** precise frozen decision semantics.
- **receipt_id:** hash of a canonically encoded, schema-versioned receipt binding inputs, checking implementation, outputs and verdict.
- **provenance:** optional source PR, issue and historical labels; must not affect computation.

New package names, import paths, schema names, commands and generated artifacts MUST NOT embed PR numbers or phase labels such as `t7f2`. Existing historical schema identifiers MUST NOT be rewritten. Use semantic identifiers plus explicit schema versions.

## 4. Contracts and input schema

Experiment definitions MUST be strict, versioned and declarative. They identify a supported workload family, arms, datasets, probes/adapters, execution profile, lane catalog, correctness oracle, protocol, statistical method and policy. Unknown fields, invalid enums, duplicate keys or unsupported schema versions fail closed; no untrusted dynamic Python import, arbitrary shell command or expression evaluation from experiment YAML.

A **profile** controls rigor (not benchmark semantics): `development`, `regression`, `qualification`. A protocol sets exact measurement requirements independently: randomized balanced schedules, arm multiplicities, warmups, samples, host constraints, A/A rules, retention/exclusion criteria, bootstrap iterations, seeds, stop/retry authorization and report expectations. Qualification profile cannot silently override a frozen protocol.

Illustrative, non-canonical configuration:

```yaml
schema_version: 1
experiment:
  id: retained-key-dedup
workload:
  id: search-topk
  digest: "<content digest>"
arms:
  - id: baseline
    adapter: quervant
  - id: prefilter-bitset
    adapter: quervant
  - id: exact-set
    adapter: quervant
protocol:
  id: balanced-paired
  version: 1
  profile: qualification
  blocks: 12
  bootstrap_resamples: 10000
policy:
  id: retained-key-selection
  version: 1
```

**This example is not an executable protocol**; important fields, including exact schedules, identities, readiness thresholds and stop conditions, are intentionally omitted. The implemented schema must reject such an incomplete declaration for official acquisition.

## 5. Subsystem responsibilities

### Protocol compiler

Validates all declared inputs, materializes canonical schedule(s) and source/build/workload locks, produces a protocol digest, and binds any official authorization. MUST freeze *before* the first official control or treatment measurement; later edits yield a different protocol identity. A pre-freeze control can never be promoted retroactively.

### Execution engine

Owns acquisition state machine, exclusive run directories, source checkout/build proof, host capability probes, CPU affinity/readiness, subprocess lifecycle, correctness oracle calls, balanced scheduling, slot recording, stop conditions, archive publication and cleanup. Supports both native Linux and WSL2 with explicit recorded host capabilities. No fabricated data, implicit retry, selective rerun or relaxed readiness criterion. Timings and readiness records are distinct. Variability alone is nonfatal unless a frozen rule explicitly makes it otherwise.

### Adapter boundary

Each adapter declares supported operations, version/capabilities, build or executable identity, deterministic fixture creation, oracle semantics, warmup/measure contract, stdout/measurement envelope, timeout/error categories and cleanup. Cross-engine comparisons require semantic equivalence per lane; unsupported scoring/ordering semantics are marked noncomparable, never incorporated into numeric ratios. Adapter output must not control acceptance policy.

### Evidence service

Strict JSON/schema parsing, path confinement, bounded safe archive reads, digest verification, immutable raw measurement envelopes, source/build provenance, complete series accounting, and eligibility checks. Produces a signed-*identity* receipt (content-addressed; **not necessarily cryptographically signed**) only after full admission. A trusted input digest and validator identity must be independently established; a checksum copied from the same untrusted payload is not authenticity.

### Analysis service

Primary calculations of slot medians, per-block arm estimates, paired direction-labeled ratios, symmetric predeclared exclusion, retained-block estimates, bootstrap uncertainty and optional geometric-mean aggregation. The block is the unit of paired resampling where prescribed; correlated timed samples in a slot are not independent blocks. Numerical choices are versioned and fully deterministic. Report effect sizes, uncertainty and inconclusive outcomes; never infer significance from point differences alone.

### Policy service

Consumes admitted measurements and analysis receipts. A typed, versioned policy defines eligibility, target/guardrail/attribution/filter constraints, numerical comparison direction, confidence requirements, memory/resource constraints, tie boundaries, and ordered selection reasons. No magic arm names (`P`, `H`) or fixed K/72-lane assumptions in common code. A decision must be traceable to frozen policy ID, input metrics and exact rule outcomes.

### Independent verification

Independently recomputes *the assertions it certifies* from authenticated inputs, using a separate reference implementation for critical statistics and policy boundaries. Sharing low-level filesystem, hashing or parsing utilities is permissible; sharing the primary decision implementation with its supposed independent oracle is not. Explicitly state verification coverage and any unverified assertion. Include adversarial/mutation tests that prove tampered evidence, malformed policy and changed conclusions are rejected.

### Acceptance coordinator and attestation

Orchestrates logical gates through dependency receipts, prevents TOCTOU substitution by verifying digest bindings at consumption time, and produces acceptance/attestation manifests. The final attestation names exact input/source/protocol/analysis/policy/QA identities, decisions and scope. A qualifying attestation does not by itself approve production adoption or merge.

## 6. Gate model and deduplication

For a plain-language explanation of each gate, how it differs from host/A/A pre-acquisition qualification, and when a gate can reuse a prior receipt, see [BENCHMARKING_METHODOLOGY.md §10](BENCHMARKING_METHODOLOGY.md#10-gates-purpose-checks-and-safe-reuse).

Five **logical** gates, rather than five required full re-executions:

| Gate | Inputs | Responsibility | Artifact |
| --- | --- | --- | --- |
| A Admission | frozen protocol, raw evidence, source/build/workload identity | authenticity, integrity, completeness, eligibility | `admission.json` |
| B Analysis | admission receipt, analysis and policy identities | statistics and policy derivation | `analysis.json`, `policy.json` |
| C Verification | admitted raw evidence, B outputs, reference verifier identity | independent calculations, policies and mutation-sensitive verification | `verification.json` |
| D Acceptance | A–C receipts, relevant framework/source QA receipts, prescribed qualifications | verify gate dependencies and mandatory tests; reject skips and incomplete suites | `acceptance.json` |
| E Attestation | accepted receipts, artifact identity manifest | bind a final immutable logical snapshot, issue final verdict | `attestation.json`, `manifest.json` |

**Gate receipts are capability-bound**, not reusable solely by filename or PASS string. Their identity MUST include: canonical validated inputs and digests; schema/protocol/policy versions as applicable; relevant verifier/analyzer implementation identities; configuration, platform/toolchain dependencies if affecting outcome; test/QA roster identities; and outputs. Changing any covered dependency invalidates the receipt. Verify that referenced bytes still match their digests before reuse. Reject missing dependency edges, forged receipt relationships, unexpected schema or modified source.

Gate D MUST distinguish:
- **framework QA** (unit, mutation, API, contract and integration suites run when framework source/affected dependencies change);
- **source/build qualification** (e.g. relevant Rust/MSRV checks, tied to source/toolchain identity);
- **experiment acceptance** (receipt dependencies, protocol-specific correctness, evidence and decision checks).

Do not rerun unchanged, content-bound QA for every derivation. Conversely, do not cache live readiness results across executions: host readiness is time-bound and acquired anew whenever the protocol requires it. Do not cache a past A/A control as authorization for a new official series unless the frozen protocol explicitly permits it.

Gate E SHOULD NOT perform redundant derivations when the qualified deterministic analysis/verifier contracts, independently verified artifacts and content hashes already satisfy the applicable assurance profile. A specified protocol MAY require independent fresh derivations; omission must not weaken historical acceptance standards.

## 7. Measurement semantics and safeguards

For the end-to-end process, randomization and position balance, block/slot/sample arithmetic, paired confidence intervals and symmetric exclusion rules, see [BENCHMARKING_METHODOLOGY.md §§3–9](BENCHMARKING_METHODOLOGY.md#3-end-to-end-workflow).

Retain current `docs/BENCHMARKING.md` methodology unless explicitly superseded for *new* protocols: correctness before timing; frozen arm/lane semantics; position-balanced randomized blocks; per-lane warmup and timed samples; symmetric predeclared pruning; paired block-level uncertainty; A/A equivalence controls; full source/binary/corpus identity; fail-closed host checks; distinguish `ACQUIRED_VERIFIED` from a favorable performance outcome.

Statistical outcome vocabulary must preserve inconclusive results and explicitly distinguish structural qualification from performance selection. No default implicit comparator or throughput/latency direction.

Errors are typed and stable by category (invalid configuration, unsupported capability, source mismatch, host not ready, acquisition incomplete, evidence mutation, analysis failure, verification mismatch, acceptance incomplete, publication conflict). Unrecognized conditions HARD STOP. Do not automatically restart, repair, prune, promote or rerun official experiments outside frozen authorization.

## 8. CLI and artifact contract

Stable CLI surface:
```text
quervant-bench inspect --experiment <id>
quervant-bench validate --run <run-id>
quervant-bench run --experiment <id> --protocol <path> --out <new-path>
quervant-bench analyze --run <run-id>
quervant-bench verify --run <run-id>
quervant-bench accept --run <run-id>
quervant-bench report --run <run-id>
```
Each command must have a machine-readable exit category, structured JSON artifact, exclusive output behavior, and offline/read-only variants where applicable. Actual argument names and serialization are locked in BM-01 before implementation.

Canonical new output layout:
```text
benchmark-results/<experiment-id>/<run-id>/
  protocol.json
  environment.json
  measurements/
  admission.json
  analysis.json
  policy.json
  verification.json
  acceptance.json
  attestation.json
  manifest.json
```
Missing outputs before their gate executes are normal; files appear only after successful stage completion. Artifact manifests include the digest and exact relationship of every published member; archive safety and atomic publication are mandatory.

## 9. Testing architecture, observability and security

### Simulation-first milestone boundary

**BM-01–BM-08 MUST NOT perform new, real timed benchmark acquisition, including official A/A or treatment runs and real performance profiling.** Real full-scale acquisition is deferred to **BM-09**, after explicit protocol freeze, host readiness and authorization. Compile-only benchmark checks, untimed functional tests, deterministic simulated acquisition, and read-only historical replay are permitted earlier. The rationale, terminology and required fault scenarios are specified in [BENCHMARKING_METHODOLOGY.md §10.4](BENCHMARKING_METHODOLOGY.md#104-verifying-our-methodology-before-running-real-benchmarks).

### Injected interfaces instead of test-only shortcuts

The execution service MUST make the following testable without real timing:
- **Clock**: logical/monotonic synthetic clock, with a real monotonic clock only for authorized acquisition.
- **Random schedule source**: frozen algorithm and seed; validates block multiplicity and position balance.
- **Adapter/process runner**: synthetic adapter and real Quervant/external-engine adapters implement the same interface.
- **Readiness/host capabilities**: deterministic simulated probe records; genuine per-acquisition readiness for real runs.
- **Correctness oracle**: synthetic expected answers and independent real workload oracle using the same verification contract.
- **Evidence store**: isolated/exclusive temporary store with failpoints for partial writes, corruption and output collisions.

The synthetic adapter MUST drive the **same controller, recording, admission, analysis, policy, independent-verification, gate and attestation implementation** as real adapters. Do not add a simpler pass-through verifier used only for tests. Dependency injection is intentional; unbounded monkey-patching of operating-system calls is not the design.

### Origin and qualification-scope separation

Every acquired synthetic sample and its derivative MUST carry a strict, machine-validated origin and qualification scope. For example, `evidence_origin=synthetic` and `qualification_scope=simulated` are conceptual field names; BM-01 fixes the actual schema and enums. The official real qualification profile MUST reject synthetic inputs, derived receipts and attempts to relabel synthetic records. The provenance fence must survive archives, normalized legacy views and all Gates A–E. Tests MUST deliberately attempt cross-scope substitution and verify fail-closed rejection.

A synthetic complete chain can claim only **simulated framework qualification**, never a real measured performance result. Real source compilation, adapter correctness and protocol validation before BM-09 also do not constitute real timing qualification.

### Test tiers and acceptance

| Tier | Content | Required when |
| --- | --- | --- |
| **L1 component/property** | strict schemas and JSON, schedule multiplicities/randomization, hashes, paths/archive safety, statistics and independently calculated boundaries, policy, receipt dependencies and negative cases | Every affected BM PR |
| **L2 simulated end-to-end** | controlled source/build semantics, simulated readiness/A/A, balanced slots/campaigns, corruption/crashes, pruning, independent recomputation, A–E gate reuse/invalidation, final synthetic report | Build beginning BM-03; complete by BM-06; search and cross-engine families by BM-08 |
| **Historical offline replay** | authentic archived inputs read-only, legacy/new decision and statistics comparison with explicitly defined parity; no timed execution | When available; mandatory equivalence cases must pass before retiring associated legacy path |
| **L3 real qualification** | real source/host/adapter, fully frozen and authorized comparison, genuine timed measurements, controls, admission, analysis, independent verification, attestation | **BM-09 only** |

Use a **fast PR validation profile** for deterministic focused feedback and a **full synthetic qualification profile** before accepting affected PRs. Full synthetic testing includes fault injection at every significant state transition, skipped/failed mandatory QA, stale receipts, changed input and deliberately malformed evidence. Make slow tests parallel or separately scheduled, but never waive required tests. CI must run without an idle benchmark host and without inaccessible historical external archives: small checked-in synthetic golden fixtures provide mandatory baseline coverage. Missing external archives are reported explicitly, not silently treated as replay PASS.

Include native Linux and WSL2 capability/adapter contract testing. The independent statistical/policy oracle may share low-level parsing/hash utilities but MUST NOT delegate its independent conclusion to primary analysis/policy functions. Record reproducible test seeds and exact failing scenarios.

### Observability and safeguards

Record deterministic state transitions, actor/adapter identifiers, synthetic versus real scope, protocol digests, gate receipt dependency graph, error categories and artifact hashes. Avoid secrets, uncontrolled filesystem paths, dangerous shell evaluation and automatic privilege escalation. Missing tooling yields explicit unavailable/blocked status; it must never trigger fabricated evidence or an accidental live benchmark fallback.

**BM-09 is the first real qualification gate:** no legacy execution implementation may be destructively retired until its required semantic equivalence and final real qualification conditions have passed. Passing L1/L2 establishes logic and integration correctness, not real-world timing fidelity.

## 10. Design acceptance criteria

The target is accepted only if a new semantic experiment requires no copied PR-specific controller/verifier; shared services are covered by deterministic and adversarial tests; retained-key and cross-engine experiments use the same public contracts; historical evidence remains untouched and verifiable; independent statistical/policy assurance remains independent; and the gates' dependency-aware reuse cannot permit stale evidence or false PASS.

Migration sequencing and proof obligations are defined in [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md); BM-series deliverables are defined in [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md).
