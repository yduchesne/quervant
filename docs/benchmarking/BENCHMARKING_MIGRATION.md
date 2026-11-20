# Quervant Benchmarking Infrastructure — Migration Specification

**Status:** Proposed migration contract for **v0.1-bench**. Companion to [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md), [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) and [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md).

**Approved BM-09 continuation (19 November 2026):**
[Benchmark migration acceptance](../BENCHMARK_MIGRATION_ACCEPTANCE.md) is the
normative amendment to the remaining completion requirements; use
[BM09_COMPLETION_PLAN.md](../BM09_COMPLETION_PLAN.md) for implementation and
execution. Native Linux and WSL2 capability support is **IMPLEMENTED locally**.
The `current-baseline-v2` runtime/acceptance and complete committable result
export are **PLANNED**. Existing historical records and strict v1 runtime readers
keep their original meanings and requirements.

## 1. Baseline and migration rules

The audited development branch had 32 PR 15 benchmark directories, 26 PR-specific `run.py` files, 15 PR-specific `verify.py` files and dedicated T7/T7-F2 analysis/verification/freeze packages. This is a **static architecture inventory**, not a completed behavioral equivalence audit. Main and the development branch may differ; **each BM PR must reconcile against fresh `main` before coding**. The historical D3-C/T7-F2 flow is the primary reference; PR 15D cross-engine comparison is the second, deliberately different proof case.

Nonnegotiable:
- Never mutate, rename in place, or re-sign frozen historical protocol/evidence/report/receipt bytes.
- No retrospective change to statistical decisions, acceptance, or source provenance.
- Never silently replace a historical verifier with a new interpretation; retain legacy-version reading and exact historical checks.
- New shared modules must not embed PR or T-step identifiers.
- Separate independent assurance from shared low-level mechanisms.
- Documentation-only changes never authorize benchmark acquisition.
- Migration and code refactoring do not imply production adoption of an experimental optimization.

## 2. Inventory and responsibility map

| Legacy family | Main responsibilities | Target | Disposition |
| --- | --- | --- | --- |
| Criterion/fixtures under `crates/quervant-core/benches` | deterministic microbench and correctness fixtures | benchmark adapters | retain native Rust tools, expose metadata |
| `benchmarks/pr15d/harness` | cross-engine runner, corpus oracle, validation, aggregation | adapter + execution + evidence + analysis | migrate as independent proof case |
| PR 15E/F profiling scripts | profiling, resource/cost probes and evidence | profiling adapter | retain tool semantics, extract common machinery |
| PR 15G/H/I `run.py` | source/build, schedules, readiness, query execution, sealing | execution, protocol, evidence | phased extraction |
| PR 15G/H/I `verify.py` | source/build/evidence checks and metric recomputation | evidence + verification | migrate with independent calculation contracts |
| D3-C `run.py` / `verify.py` | four-arm randomized comparative acquisition | execution + reference verifier | first benchmark migration |
| D3-C T7 `analysis.py` / `policy.py` | statistical derivation and strategy decision | analysis + policy | first analytical migration |
| D3-C T7-F2 `admission.py` | archive, provenance, micro and series admission | evidence | first admission migration |
| D3-C T7-F2 `oracle.py` / `verify_policy.py` | independent policy verification | verification | preserve independent implementation |
| D3-C T7-F2 `acceptance_gate.py` / `freeze_gate.py` | fixed suite, QA and freeze receipt | acceptance + attestation | generalize after receipt schema |

Existing `docs/BENCHMARKING.md` remains the current policy and historical-methodology entry point during transition. The interim docs remain under `docs/benchmarking/` until final integration.

## 3. Migration approach

**Strangler migration**: build generic services alongside historical code and convert one reference experiment at a time. For BM-09, execute one complete current run per required family through the new framework, independently verify its raw observations and calculations, and preserve it as a new baseline. No legacy-reference acquisition or old/new analyzer equivalence gate is required. Use historical results when authentic or faithfully recoverable; absent history does not block the baseline. Retain original readers and entrypoints; destructive retirement is outside the amendment.

Stages and required proofs:

### Stage 1 — Establish contracts and inventory
- Freeze a baseline inventory of module paths, interfaces, protocol files, schema versions, source hashes and historical evidence locations.
- Specify versioned JSON schemas; canonical serialization; normalized errors and CLI exit codes.
- Specify immutable identities for experiment, protocol, series, run, workload, arm, policy, QA and receipts.
- Establish a schema/compatibility registry with explicit supported/unsupported versions.
- Make all unknown or incomplete configurations fail closed.

**Pass:** documented mapping from each historical format to either a read-only adapter or an explicit unsupported legacy category; contract tests for all new schema types.

### Stage 2 — Shared utilities and admission
- Extract strict parsing, cryptographic hashes, path confinement, safe archive inventories, source/build provenance and receipt binding.
- Extract host capability/readiness checks as an independent component with time-bound results.
- Replace repetitive admission invocations with content-addressed receipts validated against complete dependencies.
- Keep historical verifier invocations as compatibility checks when mandated for a frozen study.

**Pass:** old vs new checks agree on approved fixtures; negative tests reject malformed archives, symlinks/traversal, changed bytes, wrong source/protocol and stale receipts. Do not reuse live host readiness.

### Stage 3 — Execution core and adapters
- Introduce a generic state machine for planned, frozen, ready, acquiring, completed, sealed, verified, failed/stopped.
- Generate and validate randomized balanced schedules based on protocol, not compiled arm names.
- Introduce typed adapter contracts for query execution, warmup, correctness, resource measurement and metadata.
- Migrate retained-key-D3-C semantics first without changing the original frozen run.
- Do not execute new real timed benchmarks in BM-01–BM-08, even with an idle host; use synthetic acquisition, injected readiness and offline read-only replay for stage qualification.

**Pass:** deterministic scheduling and replay, exact handling of failures/HARD STOP, no implicit retries; parity on representative success and failure fixtures.

### Stage 4 — Analysis, policy, independent verification
- Extract metric direction, per-slot aggregation, paired block ratios, symmetric exclusions, bootstrap uncertainty and GM methods.
- Define typed policy rules and selection reasons with exact boundary semantics.
- Keep reference statistics/policy verification in independent modules; do not reuse primary decision functions.
- Reproduce D3-C historical analysis/policy meaning from original evidence read-only.

**Pass:** current calculations independently verified under the stated method, seed/boundary tests and mutation rejection. Historical replay is optional when its authentic inputs exist; never reinterpret a frozen historical decision or fabricate missing inputs.

### Stage 5 — Gates, qualification and attestation
- Build dependency-aware A–E gates following the architecture contract.
- Split framework/source QA receipts from experiment-specific acceptance.
- Create generic freeze and final attestation; remove hardcoded 13-file/60-test/11-command rosters from common code (versioned historical profiles may retain those literal rosters).
- Verify time-of-check/time-of-use binding, exclusive publication and stale receipt rejection.

**Pass:** complete qualification can consume unchanged receipts without unnecessary work; any covered input/source/tool/test change invalidates the dependent result; official readiness checks are not cached.

### Stage 6 — Cross-family reuse and documentation preparation (real qualification deferred to BM-09)
- Run the PR 15D-style cross-engine semantic comparator through generic contracts, including explicit noncomparable lanes.
- Ensure profiling and Criterion entry points remain accessible and documented.
- Migrate additional families only where they create reuse value; preserve historical legacy entry points/readers for reproducibility. Do not destructively retire legacy execution paths before BM-09 real qualification.
- Move the adopted methodology and implemented architecture into current docs directly under `docs/`, updating `docs/BENCHMARKING.md`, related docs, CLI examples and indexes; retain this folder as historical.

**Pass:** at least one search-latency and one cross-engine family exercise the shared framework in **synthetic/offline mode**; no copied PR-specific runner/verifier for new studies; no broken historical verification. Real full-scale qualification and final retirement occur only in BM-09.

## 4. Equivalence matrix — required before legacy retirement

For each migrated family, record **legacy input**, **new input**, **legacy result**, **new result**, **expected equivalence type**, **actual comparison**, **disposition** and **reviewer approval**.

The approved BM-09 primary acceptance requires one complete current run per
required family and independent verification of its calculations. Experiment arms A/B
remain distinct from runner identity. Performance comparisons are treatment
relative to baseline within a run; across runs compare those relative effects,
never absolute old-A/current-A, old-B/current-B or old/new-runner latency ratios.
Different independently acquired timings or decisions are not themselves a
current-verification failure. A legacy/new execution comparison is not required.

Where comparable authenticated historical results exist, compare the previous
and current within-run proportional effects. This is a supported report,
not a prohibited cross-run comparison. Match metric/direction, arm orientation,
workload and method, and show both actual host environments and qualification.
A 20% latency reduction previously versus 10% now is a ten-percentage-point
narrowing of relative advantage, not proof that either runtime became slower.
Absolute A-minus-B differences across runs are not a substitute for these effects.

Require the same host/configuration within each A/B run. Do not require identical hosts across a
historical run and a current run: proportional comparison remains supported,
with the actual environment difference displayed. Relative effects do not remove
every environmental influence, so such a difference cannot establish a code-only
regression. Native Linux/WSL2 collection is implemented; native Windows collection
is not. Provenance-valid, comparable historical Windows effects may be displayed
without relabelling their platform or claiming new Windows acquisition support.

| Class | Required checks | Required parity |
| --- | --- | --- |
| Clean protocol/source | exact schema, digests, identities, schedules | equivalent accept/reject and output semantics |
| Wrong protocol/source/binary | mismatched hashes, altered Git bytes, wrong adapter | both fail closed |
| Correctness oracle | good and deliberately bad query results | same correctness verdict |
| Host readiness | ready, busy, steal, capability missing, changing topology | same mandatory stop semantics |
| Acquisition lifecycle | missing slot, duplicate slot, truncation, crash, output exists | no silent resumption or promotion |
| Randomized schedule | arm multiplicity, position balance, fixed seed | exact schedule when protocol requires exactness |
| Archive security | tamper, traversal, links, oversize, missing member | reject malicious/invalid evidence |
| Statistics | medians, paired ratios, exclusions, bootstrap, GM | exact when deterministic/canonical; numeric tolerances only when justified |
| Policy boundaries | guardrails, CI edges, memory, tie, inconclusive | same historical decisions and reasons |
| Independent verification | mutate status, selected arm, CI, source and evidence | rejection parity; preserved independence |
| Acceptance | missing test, skip, xfail, stale QA, changed source | same fail-closed intent; no false PASS |
| Attestation | freeze, changed bytes, changed roster/receipt, double publish | fresh identity and immutable history |
| Cross-engine | matched semantic lanes, unsupported comparator | identical semantic eligibility |

**No blanket byte-equality claim:** new schema layouts and manifest formatting will differ. Compare historical *decision and calculation semantics*, and use byte equality only within the same canonical schema/algorithm identity. Record all approved transformations and numeric tolerances explicitly.

## 5. Migration data handling

- Treat historic `target/` and archived evidence as external, potentially missing in a fresh clone; absence must be reported, not replaced by synthetic official data.
- Never create a new historical attestation using transformed evidence; legacy adapters expose a normalized *view* with a provenance link to original immutable bytes and original verifier.
- Record authoritative historical source commit, original relative path, original digest, schema version and adapter version for any normalized view.
- New output roots must use unique run IDs, exclusive creation, canonical paths and bound manifests.
- Keep archived and raw inputs immutable. Outputs of replay/analysis go into a distinct destination.
- No automatic source-file rewrites or mass renames of historical directories as part of migration.
- Preserve the complete current baseline at `benchmark-results/baselines/<baseline-uuid>/`, with a closed member/digest inventory and clean-checkout replay. One baseline UUID groups both family run UUIDs. Preserve raw observations, provenance, controls, analysis/independent verification and policy inputs actually used; the fifteen-member derived bundle alone is insufficient. This exporter is planned work.
- Record absent historical inputs `UNAVAILABLE`; original derived ratios without raw rederivation `AS_REPORTED`; and incompatible comparisons `NOT_COMPARABLE`. Exclude invalid/unverified history from quantitative reporting. None is a universal baseline prerequisite; any discovered defect affecting current calculations must still be resolved. Strict v1 readers are unchanged.
- Missing micro/F1 optimizer inputs leave v2 policy `NOT_EVALUATED`, with no selected arm or adoption claim; they do not prevent valid current measurements or require a fresh micro loop. Retained BASE/experiment sources remain pinned to `39dbd9f571a58bea8cc03d5a406533298e809bfe` / `3ad6c5184fbe9c011abb731415a007e3f19d21de`; a fresh baseline is new measurement, not an implied current-HEAD engine.

## 6. Simulation-first testing and CI transition

### 6.1 Prohibited and permitted execution by milestone

**Hard boundary:** BM-01 through BM-08 MUST NOT initiate **any new real timed benchmark acquisition**—neither a full official series nor a smaller timed pilot, Criterion measurement, real performance profile or official A/A control. **The first full real benchmark campaigns are reserved for BM-09.** This is a deliberate engineering decision to accelerate the PR series and focus on functional solidity rather than measurement-host availability. The boundary cannot be relaxed by a coding agent or a convenient idle host.

Allowed before BM-09:
- Rust/Python unit, integration, property, security, mutation and contract tests.
- Build-only benchmark compilation (for example, `cargo bench --no-run`), lint, formatting, documentation and coverage tests that do **not** execute benchmark timing.
- Untimed real adapter correctness and semantic-comparability smoke tests.
- Deterministic synthetic acquisitions using a logical clock and mock host readiness through the **same** public orchestration path.
- Read-only replay and reanalysis of existing genuine historical evidence, with new outputs in separate directories.

The testing policy in [BENCHMARKING_METHODOLOGY.md §10.4](BENCHMARKING_METHODOLOGY.md#104-verifying-our-methodology-before-running-real-benchmarks) is normative throughout the BM series.

### 6.2 Mandatory test layers

**L1 — Deterministic component and property tests.** Required from BM-01 onward for affected components: strict schemas, identity and serialization, schedule balance/seed reproducibility, numerical boundary and independent oracle cases, archive security, receipt dependencies and failure state behavior. Generate combinations of valid and invalid arm/lane/block/slot configurations; record seeds and failing counterexamples.

**L2 — Synthetic end-to-end qualification.** Build one synthetic adapter, injected logical clock, deterministic process/host readiness provider and temporary artifact store. By BM-03 run protocol → simulated acquisition → sealed synthetic records. By BM-06 exercise the **entire** A–E gate chain, including independent recomputation, receipt reuse, invalidation, negative tests and final attestation. BM-07 and BM-08 use that same pipeline for retained-key and cross-engine families.

**Offline historical replay.** Authentic archived inputs may be replayed without new measurement to recover their original effects. Preserve their methods and claims; label unavailable raw rederivation explicitly, including when an authentic original ratio is shown only `AS_REPORTED`. Checked-in **small synthetic golden fixtures** still cover mandatory deterministic tests. Absent history does not block `current-baseline-v2` acceptance and never becomes a historical PASS. Newly running an old program produces fresh observations, not recovered history.

**L3 — Real full-scale qualification.** Only BM-09, after mandatory synthetic verification, explicitly approved frozen protocols, verified source and workload identities, live host readiness and A/A authorization. A blocked real campaign is not a qualification PASS.

### 6.3 Executable failure matrix

Before BM-09, use deterministic fault injection to verify at least:

| Fault category | Cases | Required behavior |
| --- | --- | --- |
| Experiment identity/protocol | unfrozen, wrong hash, altered source | no official acquisition or invalid evidence |
| Readiness/controls | busy/steal, missing capability, bad A/A | no treatment authorization |
| Adapter/correctness | wrong results, noncomparable lane, crash | fail closed, preserve partial evidence |
| Acquisition | duplicate/missing slots, illegal schedule, output exists | reject or explicitly mark incomplete; no silent retry |
| Integrity | missing/tampered files, path traversal, symlinks, archive oversize | reject |
| Statistics/pruning | asymmetric or outcome-driven exclusions, CI boundaries | reject bad pruning; exact decision rule |
| Decision oracle | altered selected arm/status/CI/memory | independent rejection |
| QA/receipts | skip, xfail, wrong test roster, source/tool change | invalidate acceptance |
| Freeze/attestation | stale input, altered digest, re-publication | reject changed or duplicate artifacts |
| Scope confusion | synthetic artifact presented as real | **reject**, regardless of simulated PASS |

Every test must inspect machine-readable error/status, lifecycle transition, immutable input preservation and output validity. Neither a scripted "happy path" nor a synthetic PASS alone satisfies the failure matrix.

### 6.4 Fast PR feedback versus full synthetic acceptance

Run two development profiles:
1. **Fast PR validation:** affected deterministic units/properties, strict schemas, compiler/lint checks, adapter contracts and small simulated lifecycle cases; optimize for short feedback without making timing assertions.
2. **Full synthetic qualification:** complete applicable deterministic suites (including mutation, fault injection, independent math, receipt invalidation and offline equivalence when available), required before accepting each affected BM PR. Long suites may be run separately or parallelized but cannot be silently waived at closeout.

Tie QA receipts to relevant source, toolchain, test roster, schema, configuration and fixture digests, and revalidate their dependencies. Framework QA, source/toolchain qualification and experiment acceptance remain distinct. A cached QA result may be reused only if every covered dependency matches. Simulated readiness does not authorize subsequent real runs; live readiness is never cached between real campaigns.

### 6.5 Synthetic provenance and completion claims

Every synthetic sample, archive, receipt, result and final attestation MUST retain a validated origin/scope tag (typed equivalents of `evidence_origin=synthetic`, `qualification_scope=simulated`). The real official qualification profile MUST reject any synthetic artifact, including artifacts with altered or missing scope metadata. Add adversarial attempts to promote synthetic evidence as real.

Before BM-09, allowed completion language is **framework implementation verified / synthetic qualification PASS / read-only historical equivalence PASS**, with scope clearly stated. **Never claim real benchmark qualification, performance improvement or real host fidelity.**

### 6.6 Final BM-09 sequence

BM-09 must (1) implement and qualify `current-baseline-v2`, (2) confirm real
adapter correctness, actual source/workload/build/host identities and independent
G0, (3) acquire one complete current new-framework run per retained-key and
cross-engine family under frozen controls, (4) independently verify current
observations and calculations under the explicit baseline scope, and (5) commit
complete results and pass clean-checkout replay before independent review and
closeout. Use historical results where supportable and disclose their limits;
missing history or policy micro/F1 inputs are not universal blockers. The new
retained runtime freeze and its explicitly marked backend compatibility receipt
must not overwrite or impersonate the original T6. Preserve legacy readers.
Missing current capabilities, failed controls or incorrect current calculations
still block acceptance. No invented evidence or simulated substitute is allowed.

## 7. Risks, checkpoints, rollback

| Risk | Preventive measure | Rollback / STOP |
| --- | --- | --- |
| New shared code changes acquisition semantics | dual-path replay and golden control fixtures | retain old execution route; stop promotion |
| Oracle loses independence | dependency checks and separate reference test fixtures | reject verification status |
| Receipt cache incorrectly reused | full binding and mutation invalidation tests | disable cache for affected gate; invalidate receipts |
| Legacy hashes change | read-only copies, frozen digests, strict adapters | restore legacy paths without rewriting artifacts |
| WSL2-specific assumptions | capability-based native Linux/WSL2 tests; preserve observed identity | reject missing capabilities, not WSL2 classification alone; no host switch after G0 |
| Incomplete execution-host capabilities | explicit diagnostic and status | stop affected acquisition; do not relax readiness or filesystem rules |
| Historical archive absent | bounded inventory and explicit unavailable ledger | continue current-baseline-v2; strict v1 remains unchanged |
| Historical candidate invalid or unverified | preserve its status and exclude quantitative history | investigate any current correctness implication; absence of usable history alone does not block the baseline |
| Broad cleanup causes regression | staged retirement and review after parity | keep compatibility adapters |
| Unforeseen policy/schema conditions | strict registry and error categories | STOP for architecture decision |

BM PRs MUST leave the prior stable interfaces available until an explicitly approved deprecation checkpoint. No destructive cleanup without a recorded equivalence decision.

## 8. Completion and historical documentation

A migration is complete only after:
1. Retained-key and cross-engine families each complete one current new-framework run, current correctness, controls and independent baseline verification under `current-baseline-v2`.
2. All admitted evidence/attestations and tests remain traceable and historically valid.
3. Gate deduplication is measured by an execution trace: unchanged qualified dependencies are not revalidated or rerun, while changed dependencies invalidate reuse.
4. New experiments require zero copied PR-specific runner/verifier modules.
5. CLI and developer docs are current; active architecture is integrated into docs directly under `docs/`.
6. `docs/benchmarking/` is retained, clearly marked historical, with README and links to the active documentation.
7. BM-01–BM-08 contain no new real timed acquisitions, and final BM-09 real evidence is separately protocol-frozen, authorized and verified; simulated receipts cannot be accepted as real.
8. The complete result at `benchmark-results/baselines/<baseline-uuid>/` replays from a clean checkout without producer-only files. Historical availability and any unevaluated optimizer policy remain explicit; neither is silently promoted to PASS.

No part of this specification authorizes a coding agent to improvise a new experimental protocol, relax stop gates, or change statistical policy without a separately reviewed design.
