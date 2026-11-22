# BM-10 — `main` benchmark-code audit and integrity-removal plan

**Status:** Planning / source audit only. **No implementation, acceptance, performance measurement or code deletion has occurred.** This is the implementation-change inventory for [BM-10](BENCHMARKING_ROADMAP.md), not an instruction to merge BM-09.

**Audited source:** `yduchesne/quervant`, branch `main`, commit [`70392e9e7e7ea24184f063f531bdad8ee09ec47e`](https://github.com/yduchesne/quervant/commit/70392e9e7e7ea24184f063f531bdad8ee09ec47e). BM-09 [PR #110](https://github.com/yduchesne/quervant/pull/110) is closed and unmerged; its extra `official/` code is **not in `main`**. The audit is based on file inspection and dependency tracing, **not** executable import-graph analysis or tests on the host.

## 1. Scope boundary

**Delete from BM-10's active code, data contracts and dependencies:** authorization/approval mechanisms; source-set, protocol, policy, executable and evidence **integrity verification** (not descriptive metadata); mandatory hash/digest identity comparisons; frozen-source bindings and trusted spec anchors; evidence seals and byte inventories; admission/QA/verification/acceptance/attestation receipt graphs; certification publication; automatic structural replay and its mandatory repeated verification; and all orphan imports, schemas, tests, fixtures, entry points and package-data references supporting those mechanisms. **Do not merely flag, bypass or rename them.**

**Retain or reintroduce only for a different purpose:** search-answer correctness and independent semantic oracles; experimental/statistical quality checks (including paired blocks, A/A and uncertainty); ordinary schema/type/data validation; bounded processes, timeouts and error handling; path traversal/symlink protection and safe result-file writes; OS/host capability and contention checks; and Quervant production persistence/data-corruption protections. These are **not** the abandoned benchmark evidence-certification system. The legacy PR15D/PR15I-D3-C frozen historical sources and reports are preserved read-only; BM-10 does not claim to rewrite or requalify their original verdicts.

**Hashing distinction:** a SHA-256 counter stream in a deterministic bootstrap sampler is a *statistical pseudorandomness mechanism*, not evidence-integrity verification. It may remain if justified independently; its current **protocol-digest input binding** must not be an authority/check for new BM-10 runs. The Gradle-wrapper checksum in `.github/workflows/comparative-adapters.yml` protects dependency execution (supply-chain security), not benchmark evidentiary certification; preserve it unless a separately reviewed security change replaces it.

## 2. Actual baseline behavior in `main`

- [`benchmarks/quervant_bench/cli.py`](../../benchmarks/quervant_bench/cli.py): `run` explicitly raises `BM_ACQUISITION_PROHIBITED`; `inspect` is the only ordinary operating verb; `validate/analyze/verify/accept/report --offline` delegate to `migrations/offline.py`, which opens a previously committed synthetic qualification. **There is no BM-10 real-run CLI today.**
- [`benchmarks/quervant_bench/qualification/coordinator.py`](../../benchmarks/quervant_bench/qualification/coordinator.py): full synthetic **A→B→C→D→E** admission, statistics, independent verification, QA receipts, attestation, and 15-file immutable publication. The pipeline imports `evidence`, `execution.replay`, `analysis`, `verification`, `qualification` and source-set identities.
- [`benchmarks/quervant_bench/analysis/derive.py`](../../benchmarks/quervant_bench/analysis/derive.py): otherwise useful paired statistics are **blocked by** `replay_sealed_synthetic`, `seal.json`, source/analysis/profile digests and consumed-byte rehashing.
- [`benchmarks/quervant_bench/config/contracts.py`](../../benchmarks/quervant_bench/config/contracts.py): experimental models are coupled to `PolicyBinding.policy_digest`, `AnalysisBinding.analysis_digest`, `Protocol.workload_digest`, `Dataset.digest`, `BuildIdentity.source_digest/executable_digest`, `ExperimentBundle.*_digest`, and receipt models/validators. Removing only receipt issuance would leave certification constraints in ordinary input validation.
- [`benchmarks/quervant_bench/migrations/cross_engine_contract.py`](../../benchmarks/quervant_bench/migrations/cross_engine_contract.py): mixes **valuable independent keyword oracle and reply-semantic validation** with raw adapter-source SHA checks, frozen source pins and digest-bound comparability ledgers. Split these responsibilities.

## 2.1. Configuration/result naming and association (new BM-10 contract)

- **Configuration JSON filename:** `<name>-<yyyy-mm-dd>.json`, with a stable, human-readable slug `name`, its configuration-creation date, a short `description` inside the file, and an independent unique `configuration_id`.
- **Result JSON filename:** `<name>-<yyyy-mm-dd>-<suffix>.json`, taking `name` **verbatim from the referenced configuration**, using the benchmark **execution date**, and allocating `001`, `002`, `003`, etc. **monotonically per configuration ID across dates**. Store a `run_id`, `configuration_id`, configuration filename, run index and timestamp in each result. Different configurations can have independent suffix sequences; names/date alone never substitute for configuration ID.
- Example: configuration `retained-key-prefilter-2026-11-21.json` produces `retained-key-prefilter-2026-11-21-001.json` and then `retained-key-prefilter-2026-11-22-002.json` on the following date. The human-readable description is independent of the filename slug.
- Both JSON types are Git-tracked output artifacts. Treat a result as **write-once**: allocate sequence numbers atomically and refuse overwrite/collision, including concurrent runs; do not use integrity seals/receipts to enforce this. Keep full timezone-aware timestamps. A repository write does not require an interactive approval.
- **Report replay only renders** the complete result JSON to Markdown (default output filename uses the same stem). All statistics and decisions are calculated **during the run and stored in the result JSON**. Plain parsing/shape validation for safe presentation is permitted; cryptographic evidence validation, second-checkout replay, rerunning measurements and statistical recomputation are not.

**Required code-level additions:** name/date/suffix parser and schema/validator; `configuration_id` and `run_id` fields; date and slug validation; per-configuration monotonic sequence discovery/allocation; non-overwriting atomic result writer; Git-facing tracked artifact layout; result-to-Markdown renderer that does not invoke the analyzer. Add tests for same-date runs, cross-date progression, multiple configuration IDs with the same slug, filename/config mismatch, concurrency collisions, oversized suffix, and presentation without analysis/measurement imports.

## 3. Delete from BM-10's active execution/import surface

These are candidates for **complete removal after checking their consumers**, not instructions to delete frozen historical scripts.

| Path(s) in `benchmarks/quervant_bench/` | Why remove | Dependency cleanup |
| --- | --- | --- |
| `qualification/admission.py`, `contracts.py`, `coordinator.py`, `identity.py`, `manifest.py`, `profiles.py`, `publication.py`, `qa.py`, `receipts.py`; `qualification/profiles/synthetic-framework.v1.json` | Entire BM-06 A–E certification, source roster, QA evidence, receipt graph, frozen manifest and publication stack | Remove all `qualification.*` consumers, 15-member bundle schemas, source/QA digest fields and qualification fixtures/tests. Do not keep a renamed coordinator that still requires stage receipts. |
| `evidence/admission.py`, `manifests.py`, `receipts.py`, `hashing.py`, `provenance.py` | BM-02 independently pinned evidence, source/build/verifier hash checks, trusted anchors and admission receipts | Migrate **only** the small `repository_root()` convenience used elsewhere into a non-certification path utility if needed; remove source-roster digesting and file-hash gates. |
| `evidence/archives.py` | TAR/ZIP member digest enumeration for old evidence admission | Remove if no non-certification consumer remains; retain separately only if a genuine safe-archive reader is needed. Never require archival verification for BM-10 results. |
| `evidence/publication.py` | Admission receipt as immutable completion marker | Replace with a small atomic/exclusive write utility for samples/results, **without digest manifests or receipts**. |
| `protocol/freeze.py` | Pre-acquisition source/adapter/protocol/scenario digest binding | Retain an ordinary effective configuration snapshot in reports, not an authorization/freeze verifier. |
| `execution/replay.py` | Hash-bound structural replay of sealed synthetic run | Replace with simple read-only **reanalysis from raw samples**. No second checkout, path relocation, seal verification or mandatory structural replay. |
| `migrations/offline.py` | Loads qualified A–E bundles and independent anchor file for CLI offline commands | Replace `analyze`/`report` with commands that read raw measurement JSON directly. Remove `accept`/`verify` if they only express the discarded gates. |
| `migrations/historical_retained_key.py` | Metadata-digest and historical archive eligibility gate | Retain historical source data/scripts outside the new execution path; move historical interpretation to optional read-only documentation tooling if still needed. |
| `verification/verify.py` and `verification/reference_input.py` (and certification-specific public contracts) | BM-05 reopens/rehashes sealed synthetic input and compares full canonical certificate documents | Preserve independent **math** test vectors/functions where beneficial; remove input-seal verification and official verification status/receipt pathways. |

**Do not accidentally delete:** `evidence/paths.py` is primarily path-confinement/no-follow filesystem safety, not cryptographic certification. Extract/retain a minimal safe-path helper if removing the `evidence` package. Likewise retain bounded outputs/process cleanup rather than unsafe direct file/process operations.

## 4. Refactor retained components to remove transitive integrity dependencies

| Component | Required change | Scientific or operational value to retain |
| --- | --- | --- |
| `config/contracts.py`, `config/identity.py`, `config/codec.py`, `config/schemas.py`, `config/schemas/*.json` | Remove `Receipt`, `EvidenceEntry`, `DependencyEntry`, `ReceiptSubject`, `ValidatorIdentity`, `validate_receipt`, `receipt.v1.schema.json`; drop digest-identity fields from experiment, workload, protocol, adapter and policy/analysis model validation. Replace with **descriptive** revision/strategy/toolchain/workload fields and ordinary input validation. Prune `validate_digest`, `binding_digest`, `content_digest` *only once actual consumers are removed*; keep safe JSON/YAML decoding and typed errors. | Simple documented experiment configuration, stable semantic IDs, typed lanes/arms/adapters and no malformed inputs. |
| `analysis/aggregation.py` | Remove seal inventory checks, `sha256` per-input consumption, and dependence on `execution.recorder` certification envelopes; read straightforward raw samples with completeness/shape checks. | Paired sample extraction and per-arm/per-block layout. |
| `analysis/derive.py` | Separate pure `analyze(samples, effective_policy)` from sealed synthetic replay, scenario-root identity, and source/profile digests. Accept observed real measurements from either family. | Direct within-run A/B paired estimates and treatment effects. |
| `analysis/contracts.py`, `profiles.py`, `policy.py` | Remove `source_seal_digest`, `freeze_digest`, `protocol_digest`, pinned analysis/policy digest contracts and synthetic-only scope requirements on real studies. Replace certificate-shaped results with ordinary analysis schema and version-controlled declared policy. | Exact direction-aware effects, eligibility/guardrails, explicit inconclusive and resource-limit decisions. |
| `analysis/bootstrap.py` | Decouple the statistical sampler from `protocol_digest` trust/binding. Prefer explicit reproducible seed plus stable lane/arm/campaign identifiers; retain deterministic block resampling and established percentile semantics. | Paired-block confidence intervals and uncertainty. |
| `analysis/arithmetic.py`, `pruning.py` | Primarily reuse without redesign; remove only orphaned imports/contracts as necessary. | Decimal-ratio computations, geometric means, symmetric outcome-blind exclusions and per-block statistics. |
| `analysis/history.py` | Do not invoke legacy verification as a prerequisite to new runs; optional historical relative-effect comparison may read independently available historical output. | Historical-vs-current **relative** gain comparison in percentage points, not absolute latency ratios across hosts. |
| `protocol/schedule.py`, `protocol/controls.py` | Keep randomized balanced schedules and A/A layout; remove digest-bound schedule/control documents and simulation-only exact-equality restrictions where implementing **real** A/A. | Randomization, position balance, real control assessment. |
| `execution/controller.py`, `recorder.py`, `store.py`, `contracts.py` | Replace synthetic freeze→sealed journal→structural replay dependencies with **Prepare → Validate → Measure → Analyze → Report → Save**; remove `seal.json`, per-record hashes, content-addressed slot/event chains and certificate-shaped statuses. Keep safe output and process interruption/failure handling. Do not attempt to retrofit all 1,366 lines of the synthetic controller unexamined. | Simple bounded lifecycle, actual trials and samples, transparently incomplete runs, actionable diagnostics. |
| `execution/scenario.py`, `synthetic.py`, `clock.py` | Retain minimal fake-world fixtures for focused deterministic unit tests only; no synthetic-run qualification required before legitimate real measurement. | Fast test execution for schedule, stats, failure and report generation. |
| `migrations/cross_engine.py`, `cross_engine_contract.py`, `retained_key.py` | Remove synthetic catalog SHA pins, source-file digest comparisons, frozen comparability-ledger digests and qualification handoff; extract `exact_total_hits`, `exact_matching_ids`, `compute_oracle_row`, `validate_keyword_reply_projection` and per-lane semantic comparability. **Expand** actual workload comparability to warm/cold, index build/commit, throughput and size instead of copying BM-08's synthetic warm-only whitelist. | Independent oracle, engine-neutral operation semantics and realistic cross-engine correctness. |
| `cli.py` | Retire `BM_ACQUISITION_PROHIBITED` handling and old `--offline` certified-bundle dispatcher. Provide simple `prepare`, `run`, `analyze`, `report` commands with explicit input/output paths and clear statuses; `validate` may mean ordinary correctness/shape checks, **not** an A–E gate. | An actually usable BM-10 interface. |

**Call graph to cut (present in `main`):**

```text
cli --offline
  -> migrations/offline
  -> qualification/coordinator + publication + manifests + receipts + identity
  -> evidence admission / hashing / provenance / trusted anchors

qualification/coordinator
  -> qualification/admission -> execution/replay -> seal + freeze + record digests
  -> analysis/derive -> execution/replay -> seal + consumed-file rehash
  -> verification/verify -> verification/reference_input -> sealed evidence
  -> qualification/qa + manifest + publication -> A–E attestation

migrations/cross_engine
  -> source-file SHA-256 binding + synthetic qualification + companion digest rechecks

new BM-10 path should instead be:
  config -> prepare adapters/corpus -> real oracle/semantics/readiness/control
  -> measure -> raw samples -> arithmetic/statistics -> Markdown + JSON
  `analyze` reads raw samples again; no certificate layer.
```

## 5. Legacy benchmark runners and historical preservation

- Existing real-capable sources are already present independently on `main`: [`benchmarks/pr15d/`](../../benchmarks/pr15d/) (Quervant, Tantivy, Lucene standalone adapters, corpus/oracle, timed harness) and [`benchmarks/pr15i_d3_c/`](../../benchmarks/pr15i_d3_c/) (four-arm retained-key controller). **Reuse timing primitives, adapters and workload semantics; do not invoke their complete old controller/validator as BM-10's new run path** because they also contain historical provenance, checksum and qualification gates.
- Extract just what is necessary into the BM-10 runner; preserve the old files, source identities and verdicts for history. Do not assert that the old PR15D comparative timing was semantically fair merely because its internal checks passed. Independently prove timing-boundary, result-materialization and cache-regime equivalence before cross-engine claims.
- The BM-09 [PR #110](https://github.com/yduchesne/quervant/pull/110) and [archival branch](https://github.com/yduchesne/quervant/tree/archive/bm09-incomplete-20261122) are **optional selective code sources**, not part of `main`, not merged dependencies and not trusted performance evidence. See the BM-09 preservation and reuse register in [the roadmap](BENCHMARKING_ROADMAP.md).

## 6. Tests, packaging, CI and documentation that must follow the removal

- **Delete/rewrite certification-specific Python tests:** `test_evidence_admission.py`, `test_evidence_archives.py`, `test_evidence_provenance.py`, `test_evidence_publication.py`, `test_evidence_receipts.py`, all `test_qualification_*.py`, `test_protocol_freeze.py`, `test_execution_replay.py`, `test_retained_key_offline_cli.py`, `test_cross_engine_offline.py`, and legacy-only certification branches in `test_cli.py`, `test_identity.py`, `test_schemas.py`, `test_cross_engine_historical.py` and `test_evidence_paths.py`. **Retain path-safety tests** even if the package path changes. Replace removed tests with direct acquisition, real adapter correctness, statistic golden vectors, schema, failure, report and read-only reanalysis tests.
- **Preserve/refactor scientific tests:** `test_analysis_arithmetic.py`, `test_analysis_bootstrap.py`, `test_analysis_pruning.py`, `test_analysis_policy.py`, `test_verification_reference_math.py`, `test_verification_reference_bootstrap.py`, `test_verification_reference_policy.py`, `test_cross_engine_semantics.py`, `test_protocol_schedule.py`, `test_host_readiness.py`, `test_host_capabilities.py` and relevant independent oracle fixtures. Rebind tests to plain effective configuration and raw samples, not receipts/seals/digest identities.
- **Filename and Git retention tests:** validate the exact dated configuration/result patterns, identifier references, sequential numbering across dates, exclusive creation, no silent overwrite, and deterministic Markdown rendering using only saved JSON. Do not reintroduce an integrity-attestation step to implement uniqueness.
- **Catalogs and schema data:** `benchmarks/experiments/synthetic-*` catalogs, `config/schemas/receipt.v1.schema.json`, `qualification/profiles/synthetic-framework.v1.json`, `tests/fixtures/{qualification,evidence-admission,verification,execution}/` and test rosters must be inventoried for orphan references. Migrate only small useful fixtures to test-local files; preserve historical PR artifacts separately as historical records.
- **Dependencies:** `benchmarks/pyproject.toml` currently declares `PyYAML==6.0.3` and `jsonschema==4.26.0`; these are **parsing/validation**, not integrity dependencies. Retain only if the simplified format and active code still need them, then remove orphan package-data glob entries for `qualification/profiles` and `receipt` schema. `hashlib` is Python stdlib, not a third-party dependency; remove obsolete file-digest uses, but don't remove a justified deterministic-bootstrap sampler.
- **CI:** `.github/workflows/ci.yml` runs complete `benchmarks/quervant_bench/tests` discovery and legacy-inventory plus `inspect` smoke. Replace obsolete certification-case expectations with tests for the new CLI, direct real correctness and report/reanalysis. Keep required Rust, RustFS and coverage jobs; `comparative-adapters.yml` provides useful untimed 3-engine oracle checks. Do not create branch-specific `push` triggers that duplicate `pull_request` CI (see `AGENTS.md` on the PR branch).
- **Documentation:** update `benchmarks/README.md`, `docs/BENCHMARKING.md`, CLI examples, package metadata and experiment catalogs to describe actual BM-10 behavior; leave historical `docs/pr-artifacts` and frozen legacy references unchanged.

## 7. Recommended implementation order and acceptance inventory

**Phase 1 — Extract utility seams, without changing behavior:** isolate genuinely pure statistics, scheduling, host checks, result oracles, cross-engine semantic checks and safe file/process utilities. Confirm exactly which source files and test vectors are retained.

**Phase 2 — Define simple configuration and measured-sample/result models:** no digest/source/receipt/attestation fields; ordinary required fields for workload, operation, engine/strategy, toolchain, host, warmups, samples, randomized block/slot order, measured values and analysis settings. Record descriptive Git revision and effective configuration (not as trust anchors).

**Phase 3 — Remove certificate dependencies and code completely:** delete the modules in §3 once their callers are cut; prune remaining `content_digest` and `validate_digest` call sites, contract models, JSON schemas, fixtures, package-data entries and tests in the **active** BM-10 path. Retain frozen historical source separately and filesystem/supply-chain safety controls.

**Phase 4 — Wire real runs and direct reports:** use existing corpora/adapters to perform correctness-verified per-lane timings, host readiness, honest A/A controls, paired analysis, uncertainty and direct `.json`/`.md` output. Read-only `analyze <raw samples>` recalculates statistics without running or verifying the old A–E chain. Provide recoverable error/status reporting rather than false PASS.

**Phase 5 — Demonstrate the two real benchmark families:** retained-key A/L/P/H with Top-K 1…1024 and cross-engine Quervant/Tantivy/Lucene with semantically equivalent timed operations, including Top-K=100 prefilter-active. Report per-lane effects and **within-run relative ratios**; historical-vs-current change in improvements is in **percentage points**, not absolute cross-host latency comparison. Mark inconclusive/noncomparable results explicitly.

**Acceptance checks for the eventual BM-10 implementation:**
1. No BM-10 operational CLI or runtime import path refers to `qualification.*`, `evidence.admission`, `evidence.receipts`, `evidence.hashing`, `protocol.freeze`, `execution.replay`, `migrations.offline`, or their renamed equivalents. No discarded certification schema, receipt, A–E status or hash-binding remains a prerequisite.
2. No `source_set_digest`, `binary_sha256`/byte-equality gate, trusted anchor, signed authorization, certificate receipt, seal or cryptographic source/policy/QA verification is required to **run, analyze or report** a fresh BM-10 study. Ordinary descriptive source/host/build fields are allowed.
3. Real search-result semantics, per-lane completeness and comparable timing boundaries are checked; unsafe filesystem paths and unbounded processes are rejected; ordinary errors do not claim valid timing.
4. A direct real run produces raw samples and readable Markdown/JSON immediately. A second analysis from the stored raw samples reproduces its statistics **without timing, second checkout or archival verification**.
5. Both prescribed studies have usable real measured reports, applicable tests and repository CI passing; no duplicate automatic CI triggers are introduced; source-only/synthetic-only success cannot claim BM-10 complete.

**Stop/decision policy:** If removing a module affects production storage integrity, protected historical artifacts or an as-yet-unrecognized consumer, **stop that deletion and record the dependency**. Preserve the scientific/safety behavior and redesign the coupling rather than weakening it. Do not complete the task by commenting out tests or hiding certificate failures while leaving the old architecture loaded.
