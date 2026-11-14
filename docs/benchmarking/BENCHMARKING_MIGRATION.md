# Quervant Benchmarking Infrastructure — Migration Specification

**Status:** Proposed migration contract for **v0.1-bench**. Companion to [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) and [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md).

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

**Strangler migration**: build generic services alongside historical code; convert one reference experiment at a time; run both paths on the same **read-only** historical fixtures and evidence; retire legacy execution paths only after signed-off equivalence and compatibility. Do not attempt a single massive relocation.

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
- Keep official benchmarking off until separate explicit approval; use mock/synthetic replay fixtures for stage qualification.

**Pass:** deterministic scheduling and replay, exact handling of failures/HARD STOP, no implicit retries; parity on representative success and failure fixtures.

### Stage 4 — Analysis, policy, independent verification
- Extract metric direction, per-slot aggregation, paired block ratios, symmetric exclusions, bootstrap uncertainty and GM methods.
- Define typed policy rules and selection reasons with exact boundary semantics.
- Keep reference statistics/policy verification in independent modules; do not reuse primary decision functions.
- Reproduce D3-C historical analysis/policy meaning from original evidence read-only.

**Pass:** numerical tolerances and byte-equality expectations stated *before* execution; exact historical verdict parity, seed/boundary tests and mutation rejection. Do not reinterpret frozen historical decisions.

### Stage 5 — Gates, qualification and attestation
- Build dependency-aware A–E gates following the architecture contract.
- Split framework/source QA receipts from experiment-specific acceptance.
- Create generic freeze and final attestation; remove hardcoded 13-file/60-test/11-command rosters from common code (versioned historical profiles may retain those literal rosters).
- Verify time-of-check/time-of-use binding, exclusive publication and stale receipt rejection.

**Pass:** complete qualification can consume unchanged receipts without unnecessary work; any covered input/source/tool/test change invalidates the dependent result; official readiness checks are not cached.

### Stage 6 — Cross-family reuse, cleanup and documentation
- Run the PR 15D-style cross-engine semantic comparator through generic contracts, including explicit noncomparable lanes.
- Ensure profiling and Criterion entry points remain accessible and documented.
- Migrate additional families only where they create reuse value; preserve historical legacy entry points/readers for reproducibility.
- Move the implemented architecture into current docs directly under `docs/`, updating `docs/BENCHMARKING.md`, related docs, CLI examples and indexes; retain this folder as historical.

**Pass:** at least one search-latency and one cross-engine family exercise the shared framework; no copied PR-specific runner/verifier for new studies; no broken documented legacy evidence verification.

## 4. Equivalence matrix — required before legacy retirement

For each migrated family, record **legacy input**, **new input**, **legacy result**, **new result**, **expected equivalence type**, **actual comparison**, **disposition** and **reviewer approval**.

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

## 6. Testing and CI transition

Layer test execution:
1. **Framework QA**: unit, adversarial, protocol/schema, receipt invalidation, adapter contracts, mutation and deterministic replay; run on framework changes.
2. **Source/toolchain qualification**: Rust workspace, MSRV, lint, coverage and documentation as dictated by an explicitly versioned QA profile; run when relevant source/toolchain changes.
3. **Experiment acceptance**: verify only new experiment/evidence/decision dependencies, consume valid immutable receipts for unchanged prerequisites.

Maintain a compatibility test matrix for reference evidence without requiring a live performance host. Benchmark timings are never gathered as an implicit side effect of unit tests. Long tests may be separated from quick CI, but the required qualification suite must be unskippable when issuing a qualification attestation.

## 7. Risks, checkpoints, rollback

| Risk | Preventive measure | Rollback / STOP |
| --- | --- | --- |
| New shared code changes acquisition semantics | dual-path replay and golden control fixtures | retain old execution route; stop promotion |
| Oracle loses independence | dependency checks and separate reference test fixtures | reject verification status |
| Receipt cache incorrectly reused | full binding and mutation invalidation tests | disable cache for affected gate; invalidate receipts |
| Legacy hashes change | read-only copies, frozen digests, strict adapters | restore legacy paths without rewriting artifacts |
| WSL2-specific assumptions | capability-based native Linux/WSL2 tests | mark unsupported host; no implicit fallback |
| Incomplete host or missing archive | explicit diagnostic and status | HARD STOP; do not fabricate evidence |
| Broad cleanup causes regression | staged retirement and review after parity | keep compatibility adapters |
| Unforeseen policy/schema conditions | strict registry and error categories | STOP for architecture decision |

BM PRs MUST leave the prior stable interfaces available until an explicitly approved deprecation checkpoint. No destructive cleanup without a recorded equivalence decision.

## 8. Completion and historical documentation

A migration is complete only after:
1. Reference search and cross-engine families pass through one common surface.
2. All admitted evidence/attestations and tests remain traceable and historically valid.
3. Gate deduplication is measured by an execution trace: unchanged qualified dependencies are not revalidated or rerun, while changed dependencies invalidate reuse.
4. New experiments require zero copied PR-specific runner/verifier modules.
5. CLI and developer docs are current; active architecture is integrated into docs directly under `docs/`.
6. `docs/benchmarking/` is retained, clearly marked historical, with README and links to the active documentation.

No part of this specification authorizes a coding agent to improvise a new experimental protocol, relax stop gates, or change statistical policy without a separately reviewed design.
