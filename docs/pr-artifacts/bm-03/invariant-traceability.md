# BM-03 invariant traceability

Every invariant below is falsifiable, mapped to implementation symbols and to the
executed test IDs from the BM-03 plan. Tests compute their expectation from
hand-constructed goldens, direct counts or independent recomputation — never by
calling the production predicate that they are checking.

Legend: **P** = positive case, **N** = negative/adversarial case.
Test modules live in `benchmarks/quervant_bench/tests/`.

| ID | Invariant | Implementation | P / N tests | Adversarial counterexample → failure transition | Independent oracle |
| --- | --- | --- | --- | --- | --- |
| I-01 | Only `synthetic/simulated` and the synthetic adapter may execute; no clocks or real timed measurements | `execution/synthetic.py::require_synthetic_bundle`, `SyntheticAdapter`; `execution/controller.py::execute_synthetic` scope guards; `execution/clock.py` | P: `test_scope_03_successful_paths_never_touch_clocks_processes_or_the_host`; N: `test_scope_01_real_build_identity_is_refused_before_any_effect`, `test_adapt_01_real_build_manifest_is_refused_at_construction`, `test_cli_01_run_remains_unconditionally_prohibited` | A `source-and-binary` adapter manifest, or a forged `official` scenario scope, reaching `execute_synthetic` → `BM_ACQUISITION_PROHIBITED` before any directory, provider or clock effect | Failure spies on `time.*`, `subprocess.*`, `os.system`, `LinuxCapabilityProvider`, `cli.dispatch`; `os.mkdir` call count 0 |
| I-02 | Every run binds exact experiment/workload/protocol/adapter, scenario and schedule digests | `protocol/freeze.py::build_freeze_document`, `verify_freeze_bindings` | P: `test_freeze_01_every_binding_is_recomputable_from_source_documents` | Editing the scenario, protocol document or adapter document after freeze → `INPUT_MUTATED` / `FREEZE_MISMATCH`, no seal | Digests recomputed from the four source documents via BM-01 `load_document` + `content_digest` |
| I-03 | Durable `freeze.json` precedes every adapter/readiness invocation | `execution/controller.py::_publish_plan`, `_execute` | P: `test_freeze_06_freeze_is_visible_before_any_readiness_or_adapter_call`; N: `test_freeze_05_failed_freeze_publication_touches_nothing_else`, `test_fault_01_freeze_publication_failure_prevents_all_acquisition` | A pre-freeze adapter/readiness call → capability/readiness/factory counters would be non-zero | File inventory snapshot taken inside the capability, readiness and factory callbacks; only the planned event may exist when freeze fails |
| I-04 | Every block contains exactly the declared arm multiplicities and no extra slot | `protocol/schedule.py::_verify_grid`, `_compile_spec` | P: `test_sched_01…`, `test_sched_02…`, `test_sched_06…`; N: `test_sched_03…`, `test_sched_09…` | A duplicated/short block → `BM_IDENTITY_INVALID` before output | `collections.Counter` over the stored slot grid |
| I-05 | Every arm has exact per-position occurrence count `(B·m[a])/S` | `protocol/schedule.py::_verify_grid` | P: `test_sched_01…` (2 per position), `test_sched_02…` (3 per position), `test_sched_06…` (128 per position) | A position-imbalanced explicit order → `BM_IDENTITY_INVALID` (`test_sched_04…`) | Direct `(position, arm_id)` counting, not `validate_schedule_document` |
| I-06 | Fixed seed, algorithm and declarations reproduce the exact schedule; no global entropy | `protocol/schedule.py::_balanced_rows` (`random.Random(seed)` only) | P: `test_sched_01…`, `test_sched_07…`, `test_sched_08…`; N: `test_sched_10_no_global_entropy_or_clock_is_consulted` | A `random.seed()`/`time`/`urandom` dependency → patched failures raise | Literal golden rows; two independent compiles compared |
| I-07 | Every campaign consumes its own fresh simulated readiness batch; no caching | `controller._require_readiness`, `_consumed_readiness`, `ScenarioReadinessProvider` | P: `test_ready_01_each_campaign_consumes_its_own_fresh_batch`; N: `test_ready_06_reused_missing_or_duplicated_batches_are_rejected` | A provider returning a non-declared, short or duplicated batch → `host-not-ready` | Provider call log must be exactly `[(control,0),(treatment,0),(treatment,1)]`; 6 persisted observations |
| I-08 | A failed synthetic A/A control prohibits all treatment slots | `controller._verify_control` | P: `test_ctrl_01_one_complete_control_produces_eight_paired_checks`; N: `test_ctrl_02_mismatched_replica_stops_before_any_treatment`; `test_ctrl_03…`, `test_ctrl_04…` | One perturbed `control-right` sample → `CONTROL_MISMATCH`, zero `slots/treatment-*` files, no PASS report, no seal | Raw sample tuple comparison of the persisted replicas per block and lane |
| I-09 | Per-slot oracle passes before the first warmup or measurement | `controller._require_oracle`, `_execute_slot` | P: `test_adapt_01…`, `test_flow_01…`; N: `test_adapt_02_failed_oracle_prevents_every_warmup_and_measure`, `test_adapt_03…` | Oracle `fail`/wrong identity → `oracle-failed`/`adapter-failure` with warmup = measure = 0 and cleanup = 1 | Instrumented adapter method counters |
| I-10 | Exactly W warmups and N positive samples per completed lane/slot with correct unit/scope | `controller._execute_lane`, `validate_measurement_result`, `validate_warmup_result`; `recorder.validate_lane_envelope_document` | P: `test_flow_01…` (96 warmups / 48 envelopes / 144 samples); N: `test_adapt_04…`, `test_adapt_05…`, `test_adapt_06…`, `test_clock_02…` | Wrong cardinality, unit, direction, lane, origin/scope, negative/float/bool/zero sample → `invalid-measurement` before the logical-clock advance | Counters + `LogicalClock.now_ns() == 2` after the rejected measurement (warmups only) |
| I-11 | One controller/adapter/recorder path for A/A and treatment; no special fake bypass | `controller._execute`, `_execute_slot`, `_create_adapter` | P: `test_flow_02_one_adapter_path_serves_control_and_treatment` | A control-only bypass would produce a different adapter call shape or slot layout | Recorded `(campaign_kind, display_arm_id)` sequence: `control-left/control-right` and both treatments share the factory and the `slots/` layout |
| I-12 | Only monotone state transitions; STOPPED/FAILED/SEALED never resume; no implicit retries | `contracts.check_transition`, `controller._transition`, `_terminate`, `_mark_failed` | P: `test_state_01_normal_transition_series_is_exact`; N: `test_state_02_unknown_transitions_are_rejected`, `test_state_03_first_slot_failure_is_never_retried`, `test_state_04_a_stopped_run_is_never_reused`, `test_fault_05…` | `planned→acquiring`, `stopped→ready`, `acquiring→completed` with the wrong reason, or `→sealed` outside the store → `BM_IDENTITY_INVALID` | Expected event chain hand-written; `plans→sealed` rejected; a second `run_id` is `BM_PUBLICATION_CONFLICT` |
| I-13 | Interrupted acquisition preserves partial bytes but never produces a seal | `controller._halt`/`_terminate`, `store.write_new` (exclusive), `replay` | P: `test_fault_03…`, `test_store_04…`; N: `test_fault_02…`, `test_fault_04…`, `test_fault_05…` | A hard `os._exit` or a mid-slot adapter exception → earlier lane records intact, no `complete.json`, no seal, replay `BM_EVIDENCE_UNAVAILABLE` (`crash-interrupted`) | Byte snapshots before/after; subprocess exit code 7 |
| I-14 | A sealed series has exactly all declared campaigns/slots/lanes/samples, no missing/duplicate/extra | `controller._collect_files`, `_expected_paths`; `replay._Replay.verify` | P: `test_seal_01_structural_counts_match_the_manual_oracle`; N: `test_seal_02…`, `test_seal_03…`, `test_seal_04…`, `test_replay_02…` | Deleting a lane, copying a record to an alternate path, or changing a sample with refreshed hashes → rejection | Expected inventory rebuilt by replay from the declared bundle; hand-written `golden-structural-summary.v1.json` |
| I-15 | Exclusive create + fsync + last marker, no overwrite/repair/symlink escape | `execution/store.py::ExecutionStore` | P: `test_store_01_seal_is_the_last_complete_canonical_inventory`; N: `test_store_02…`, `test_store_03…`, `test_store_05…`, `test_store_06…`, `test_path_01…`, `test_path_02…`, `test_path_03…` | Reusing a `run_id`, a symlinked output root, a FIFO entry or `events/../../escape.json` → `BM_PUBLICATION_CONFLICT`/`BM_UNSAFE_INPUT` with no writes | Raw SHA-256 + byte length of every stored file compared with `seal.files`; concurrent-create winner/loser split |
| I-16 | Read-only replay independently reconstructs inventory, freeze, structure and hashes | `execution/replay.py` | P: `test_replay_01_verification_is_repeatable_and_read_only`, `test_seal_01…`; N: `test_replay_02…`, `test_replay_03…`, `test_replay_04…`, `test_replay_05…`, `test_replay_requires_an_absolute_evidence_seal` | Missing/relabelled freeze, forged scope with a recomputed seal digest, same-length scenario mutation, truncated/duplicate-key/non-canonical records | Inode/mtime/size snapshots identical across two replays; expected inventory rebuilt from the bundle, not from controller state |
| I-17 | Evidence/output paths are disjoint and protected historical repository paths are unwritable | `evidence.paths.require_publication_base`, `require_disjoint_admission_roots`; `ExecutionStore.create` | P: `test_path_03…`; N: `test_path_01_overlapping_evidence_and_output_roots_are_refused`, `test_path_02_historical_repository_paths_are_unwritable` | `evidence_root == output_base`, nested roots, or an output under `benchmarks/`, `docs/`, `target/` → `BM_UNSAFE_INPUT` before writes | Directory listings unchanged (`output.iterdir()` empty) |
| I-18 | BM-01 schemas/CLI, BM-02 APIs, production Rust and frozen historical code are unchanged | untouched trees (`crates/`, `benchmarks/pr15*`, `config/`, `evidence/`, `host/`, `synthetic-contract-smoke/`) | P: full-suite regression (`REG-01`/`REG-02`: 230 pre-existing tests still pass; `REG-03`: source-diff audit in the verification report) | A changed schema/CLI/BM-02 contract would fail the pre-existing suites or the git diff audit | `git diff --name-status` shows only new BM-03 paths (+ optional `benchmarks/README.md` pointer) |
| I-19 | Structural verification never claims a statistical winner, gate receipt or real qualification | `recorder.SEAL_STATUS = "sealed-structural"`; `replay.StructuralReplayResult` | P: `test_flow_03_no_output_claims_a_performance_decision`, `test_seal_05_a_seal_never_claims_a_performance_decision` | A record containing `analysis`, `policy-verdict`, `attestation`, `official`, `winner`, `p_value`, `gate`, `receipt` keys/labels → test failure | Recursive key/value scan of every stored JSON document; `StructuralReplayResult` field set asserted exactly |
| I-20 | Every input/loop/file/sample/clock state is bounded and invalid boundaries are rejected before side effects | `execution/contracts.py` budgets; `scenario.validate_scenario_document`; `store.write_new`; `clock.LogicalClock` | P: `test_sched_06…`, `test_workload_type_allows_exactly_max_lanes`; N: `test_limit_01…` (×2), `test_limit_02…`, `test_limit_03…`, `test_limit_04…`, `test_fault_target_outside_the_schedule_is_rejected_before_output` | 17 arms, 257 blocks, 17 slots/block, 65 lanes, 257 samples, 33 warmups, a `2^63` sample, a >1 MiB scenario/record, or a fault target outside the frozen schedule → typed rejection with the output tree untouched | Golden/limit constants imported from `execution/contracts.py`; product computed with Python integers before allocation |

## Independent oracle matrix

| Oracle | Used by | Why it is independent |
| --- | --- | --- |
| Literal four-row vector (`golden-schedule.v1.json`) | SCHED-01, SCHED-03, SCHED-10 | Hand-written; the implementation is compared to it |
| Structural counts for the 12×8 geometry | SCHED-02 | Direct `Counter` over stored slots; the plan only requires the structural property |
| Hand-constructed structural summary (24/48/144/96/24/24/6/8/9) | FLOW-01, SEAL-01 | Frozen JSON table, not derived from `ExecutionResult` formulas |
| BM-01 codec digests of the four source documents | FREEZE-01, I-02 | Recomputed from re-parsed files with the frozen codec |
| Rebuilt expected file inventory | I-14, I-16 | Replay reconstructs it from the declared bundle and scenario, and never calls `controller._is_complete` / `_expected_paths` |
| Raw sample comparison of control replicas | I-08 | Zero tolerance integer tuple equality, no mean or threshold |
| Raw byte SHA-256 / length | I-15, I-16 | `hashlib` over stored bytes, compared with `seal.files` |

## Failure classification map

| Observed failure | Classification | Persisted evidence |
| --- | --- | --- |
| Adapter/oracle/prepare/cleanup defect | `adapter-failure` (STOPPED) | terminal event, no seal |
| Oracle returned a non-pass status | `oracle-failed` (STOPPED) | terminal event, no seal |
| Envelope/unit/scope/cardinality violation | `invalid-measurement` (STOPPED) | terminal event, earlier lanes preserved |
| Readiness/capability blocked | `host-not-ready` (STOPPED) | readiness record with diagnostic, no slots |
| A/A replicas differ | `control-mismatch` (STOPPED) | control envelopes, no PASS report, no treatment |
| Frozen input changed after freeze | `input-mutated` / `freeze-mismatch` (STOPPED) | terminal event, no seal |
| Publication/fsync/duplicate identity | `BM_PUBLICATION_CONFLICT` / `BM_NOT_IMPLEMENTED` raised | partial run, no seal |
| Unknown record/scope/structure | `unsafe-artifact` (STOPPED) or `BM_UNSAFE_INPUT` on read | no repair |
| Unexpected implementation defect | `unexpected-failure` (FAILED) + `BM_INTERNAL_ERROR` | terminal event, no seal |

## Detected contradictions and resolutions

1. **§4.3 budgets owner vs §3 import direction.** §4.3 requires the budgets to be
   defined once in `execution/contracts.py` and imported everywhere, while the
   module-direction note allows `protocol` to import only BM-01 `config`. The
   compiler must enforce `MAX_BLOCKS`/`MAX_SLOTS_PER_BLOCK` (`SCHED-06`), so the
   budgets are defined once in `execution/contracts.py` and imported by
   `protocol/schedule.py`. No cycle exists (`execution.contracts` imports only
   `config`), and the package `__init__` modules resolve names lazily.
2. **A/A equality is unobservable if the controller forces declared samples.**
   §6.4 requires the controller to validate identity, unit, direction,
   origin/scope and *cardinality*, while §7.2 requires A/A tuple equality over
   samples. Enforcing exact scenario equality in the controller would make a
   mismatch unreachable and `CTRL-02` untestable. The controller therefore
   validates positivity, count, unit, direction, lane and scope, and the read-only
   replayer independently enforces the declared scenario values (I-16/I-14). This
   keeps `CTRL-02` observable without trusting an adapter claim.
3. **Identical declared readiness batches.** The prescribed fixture gives every
   campaign the same two observations, so a byte-identical "reused batch" is
   indistinguishable from a correct one. `READY-06` therefore exercises missing,
   duplicated and refused batches; the controller also refuses to request the same
   campaign key twice (residual risk R-3).
4. **Fixture sequencing.** The scenario/golden fixtures were frozen after the
   compiler and controller tests were written against in-memory and temporary
   copies; all affected suites were re-run against the frozen fixtures.
