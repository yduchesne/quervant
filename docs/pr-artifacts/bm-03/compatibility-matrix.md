# BM-03 compatibility matrix

BM-03 is additive. It reuses the merged BM-01 and BM-02 contracts unchanged and
adds an internal simulation layer.

## 1. Frozen interfaces reused (not modified)

| Symbol | Owner | BM-03 use | Status |
| --- | --- | --- | --- |
| `config.contracts.load_experiment_bundle`, `ExperimentBundle`, `validate_bundle` | BM-01 | the only configuration parser; re-run before compiling and before sealing | unchanged |
| `Protocol.schedule`, `Protocol.arm_multiplicity`, `Protocol.metric_unit`, `warmups_per_lane_slot`, `samples_per_lane_slot` | BM-01 | compiled-schedule inputs | unchanged |
| `BenchmarkAdapter.prepare/check_oracle/warmup/measure/cleanup` | BM-01 | the sole adapter seam; `SyntheticAdapter` implements exactly these five methods | unchanged (no new method) |
| `AdapterContext`, `PreparedFixture`, `OracleResult`, `WarmupResult`, `MeasurementResult`, `ADAPTER_STATUSES` | BM-01 | returned verbatim by the synthetic adapter and independently validated by the controller | unchanged |
| `config.codec.canonical_document_bytes/content_digest/load_document/loads_json/decode_text/sha256_prefix` | BM-01 | all canonical bytes, digests and parses; no second parser, no custom cryptography | unchanged |
| `config.identity.validate_uuid4/validate_semantic_id/validate_uint64/validate_digest` | BM-01 | run identity, semantic ids, seeds and digests | unchanged |
| `config.errors.BenchError`, `CODE_TABLE` | BM-01 | all public failure categories; **no new code was added** | unchanged |
| `evidence.paths.require_publication_base/require_disjoint_admission_roots/open_regular_beneath/require_safe_root/list_directory_beneath/validate_relative_member` | BM-02 | safe roots and no-follow reads/writes; no second trust policy | unchanged |
| `host.capabilities.collect_host_capabilities/validate_host_capabilities`, `CapabilityProvider` | BM-02 | simulated static capability record only | unchanged |
| `host.readiness.evaluate_readiness/ReadinessLimits/ReadinessObservation/ReadinessDiagnostic` | BM-02 | injected limits and diagnostics; re-evaluated on replay | unchanged |
| `evidence.publication.publish_admission/admit_synthetic/verify_admission_receipt` | BM-02 | **not used** to seal BM-03 measurements | unchanged |
| `cli.py` (`inspect`, `run` → exit 77, reserved verbs) | BM-01 | untouched; no new verb, no enablement flag | unchanged |
| Six v1 JSON schemas (`protocol`, `experiment`, `workload`, `adapter`, `receipt`, `outcome`) | BM-01 | unchanged, no `protocol.v2` | unchanged |

## 2. New BM-03 internal contracts (not public schemas)

| Record | Owner | Public schema? | Notes |
| --- | --- | --- | --- |
| `synthetic-schedule` | `protocol/schedule.py` | no | internal `kind`/`schema_version: 1` |
| `synthetic-control-schedule` | `protocol/controls.py` | no | `scheduled` or `not-required` |
| `synthetic-freeze` | `protocol/freeze.py` | no | synthetic source/build markers only |
| `synthetic-scenario` | `execution/scenario.py` (fixture) | no | internal simulator fixture |
| `synthetic-state-event` | `execution/recorder.py` | no | closed reason set |
| `synthetic-readiness` | `execution/recorder.py` | no | frozen limits + reproduced diagnostic |
| `synthetic-lane-envelope` | `execution/recorder.py` | no | logical-tick arithmetic validated |
| `synthetic-slot-complete` | `execution/recorder.py` | no | lane digests, written after cleanup |
| `synthetic-control-check` | `execution/recorder.py` | no | PASS equality record only |
| `synthetic-execution-seal` | `execution/recorder.py` | no | `status = "sealed-structural"` |

None of these is a receipt, a Gate A–E artefact, an attestation or an official
protocol. They are closed internal records owned by their modules.

## 3. Historical surfaces

| Surface | Status in BM-03 |
| --- | --- |
| `benchmarks/pr15i_d3_c/{run,verify}.py`, `protocol_v3r3.json` | read-only, unmodified, still governed by their own historical rules |
| `benchmarks/pr15d/harness/run.py`, `benchmarks/pr15d/adapters/quervant` | never invoked by BM-03 |
| `crates/quervant-core/benches/*` (Criterion targets) | unmodified; `cargo bench --no-run` compiles only |
| `crates/quervant-core --test pr15i_d3_c` | re-run as a genuine **untimed** semantic regression |
| BM-01 legacy inventory (`docs/pr-artifacts/bm-01/legacy-inventory.json`) | unchanged; inventory script re-run against the frozen baseline |
| BM-02 synthetic admission golden (`receipt.synthetic.json`) | unchanged; BM-03 does not create or alter admission receipts |

## 4. What is structurally comparable, and what is not

| Question | Answer |
| --- | --- |
| Does BM-03 support the historical 12×8, four-arm, two-per-arm geometry structurally? | **Yes** — 96 slots, 24 occurrences per arm, 3 per arm per position (`SCHED-02`). |
| Does BM-03 reproduce the frozen `pr15i_d3_c` campaign order byte for byte? | **No claim.** The new schedule is a new algorithm identity with new bytes; `explicit-v1` would accept a historical order only if it is genuinely position balanced. |
| Can BM-03 evidence be compared with historical measurements? | **No.** Every record is `synthetic/simulated`; replay refuses any relabelling. |
| Does BM-03 replace the BM-02 admission receipt? | **No.** Different contract, different purpose, no Gate A claim. |
| Does BM-03 qualify Quervant performance? | **No.** Deferred to BM-07/08 (adapter family) and BM-09 (real full qualification). |

## 5. Deliberately unavailable in BM-03

* `quervant-bench run`, any `simulate` verb, any secret enablement flag;
* real timed acquisition, live A/A, profiler, external engine comparison;
* statistics, bootstrap, confidence intervals, pruning, winner selection (BM-04/05);
* Gate A–E receipts, attestation, official freeze authorization (BM-06);
* real Quervant adapter migration and external engine orchestration (BM-07/08);
* real RustFS/remote evidence durability for BM-03 records (unchanged `rustfs` CI
  job continues to cover the production Rust paths only).

Requests for any of the above return `BM_NOT_IMPLEMENTED` or are simply absent;
none is silently approximated.
