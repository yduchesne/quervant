# BM-03 verification report

## 1. Identity

```text
REPO=yduchesne/quervant
PR_SCOPE=BM-03
BRANCH=dev/bm03-protocol-execution
BASE_MAIN_SHA=e2de40330bffcb569e6a3ab7448004bd8b381a96   (merge of BM-02 PR #103)
BM02_MERGE_PRESENT=YES; MERGE_SHA=e2de40330bffcb569e6a3ab7448004bd8b381a96
START_SHA=e2de40330bffcb569e6a3ab7448004bd8b381a96
LOCAL_QA_SHA=<recorded in the closeout comment after push>
WORKTREE=BM-03 delta only (see §5)
PYTHON=3.12.3 (CI interpreter); 3.11 not installed on the verification host
RUST_TOOLCHAINS=1.85.0 (MSRV) and 1.98.1 (current stable)
```

`git merge-base --is-ancestor e2de4033 HEAD` succeeded, and the six v1 schemas,
`config/contracts.py`, the BM-02 evidence/host modules and
`docs/pr-artifacts/bm-02/verification-report.md` are all present on the base.

## 2. What was executed

**No real timed benchmark acquisition was executed.** `cargo bench --workspace
--no-run` compiled only. No `quervant-bench run`, no pilot, no live A/A, no
profiler, no external engine comparison and no real measured Quervant adapter
invocation. The synthetic suite is deterministic and needs no benchmark host.

## 3. Per-command results (final working tree)

| Command | Result |
| --- | --- |
| `python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v` | PASS — 336 tests, 0 failures |
| `PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json` | PASS |
| `quervant-bench inspect --experiment synthetic-contract-smoke --format json` | PASS — byte-identical to the module entry point (`cmp`) |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef6… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS (no output, exit 0) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — all suites ok (RustFS-only tests `ignored` as designed) |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.03 % line coverage** (regions 92.69 %, functions 87.72 %) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only; no bench binary executed) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `git diff --check` | PASS |

`cargo llvm-cov` measures the **Rust** production code. It is not a Python
coverage metric and no Python coverage floor is claimed.

## 4. BM-03 Python test inventory (106 new tests)

| Module | Tests | Coverage focus |
| --- | --- | --- |
| `test_protocol_schedule.py` | 10 | SCHED-01…SCHED-10 |
| `test_protocol_freeze.py` | 6 | FREEZE-01…FREEZE-06 |
| `test_execution_scenario.py` | 17 | closed scenario shape, bounds, canonical bytes, no-follow reads |
| `test_execution_adapter.py` | 10 | ADAPT-01…ADAPT-07, CLOCK-01/02 |
| `test_execution_readiness_control.py` | 11 | READY-01…READY-06, CTRL-01…CTRL-04 |
| `test_execution_controller.py` | 7 | FLOW-01…FLOW-03, STATE-01…STATE-04 |
| `test_execution_store.py` | 9 | STORE-01…STORE-06, PATH-01…PATH-03 |
| `test_execution_replay.py` | 11 | REPLAY-01…REPLAY-05, SEAL-01…SEAL-05 |
| `test_execution_faults.py` | 7 | FAULT-01…FAULT-05 + every fault point class |
| `test_execution_scope.py` | 6 | SCOPE-01…SCOPE-03, CLI-01 |
| `test_execution_limits.py` | 6 | LIMIT-01…LIMIT-04 |
| `test_execution_quervant_contract.py` | 6 | BM-01 adapter seam can model a Quervant search lane (untimed) |
| **new total** | **106** | all pass |
| pre-existing BM-01/BM-02 suites | 230 | all pass (REG-01/REG-02) |

The full-suite discovery count is therefore **336 tests, 230 pre-existing + 106 new**.

## 5. Source-diff inventory

```text
 M benchmarks/README.md                              (BM-03 pointer paragraph only)
?? benchmarks/experiments/synthetic-execution-smoke/  (4 declarative files)
?? benchmarks/quervant_bench/protocol/                (4 modules)
?? benchmarks/quervant_bench/execution/               (9 modules)
?? benchmarks/quervant_bench/tests/fixtures/execution/ (3 canonical fixtures)
?? benchmarks/quervant_bench/tests/test_protocol_*.py  (2 modules)
?? benchmarks/quervant_bench/tests/test_execution_*.py (10 modules)
?? docs/pr-artifacts/bm-03/                            (6 documents)
```

```text
BM01_V1_SCHEMAS_MODIFIED=0
BM02_SHARED_FILES_MODIFIED=0
HISTORICAL_TRACKED_FILES_MODIFIED=0
CONFIG_CLI_ERROR_TABLE_MODIFIED=0
RUST_SOURCE_MODIFIED=0
benchmarks/pyproject.toml modified=0
```

No change under `crates/`, `benchmarks/pr15*`, `benchmarks/quervant_bench/config/`,
`benchmarks/quervant_bench/evidence/`, `benchmarks/quervant_bench/host/`, the
existing `synthetic-contract-smoke` fixture, or the BM-01 legacy inventory. No new
third-party dependency was added.

## 6. Golden acceptance evidence

```text
SYNTHETIC_GOLDEN = 1 control campaign / 2 treatment campaigns / 24 slots /
                   48 lane envelopes / 144 integer samples / 96 warmups /
                   24 oracle, 24 prepare, 24 cleanup invocations /
                   6 readiness observations / 8 A/A checked pairs / 9 state events
```

Asserted from the hand-written `tests/fixtures/execution/golden-structural-summary.v1.json`
and `golden-schedule.v1.json`, not from production formulas
(`test_flow_01_*`, `test_seal_01_*`, `test_sched_01_*`, `test_sched_02_*`).

Independent structural replay of the default fixture returns
`StructuralReplayResult(status="verified-synthetic-structure", controls_completed=1,
treatments_completed=2, slots_completed=24, lane_envelopes=48,
synthetic_samples=144)` with every raw file digest verified.

## 7. Decision-matrix rules used

| Rule | Trigger observed | Action taken | Evidence |
| --- | --- | --- | --- |
| D01 | PR #103 merge present on `main`; all BM-01/BM-02 APIs present | branched from `e2de4033` and recorded it as `BASE_MAIN_SHA` | `git rev-parse HEAD`, presence checks |
| D02 | `git switch main` was unnecessary because the local default branch was already at the verified merge; no `fcbe384` requirement enforced | verified actual files + ancestry instead of a specific history shape | `git merge-base --is-ancestor` |
| D06 | BM-02 safe-path/no-follow APIs intact | reused `require_publication_base`, `require_disjoint_admission_roots`, `open_regular_beneath`; no shadow trust layer | `execution/store.py`, `execution/replay.py` |
| D07 | Inherited BM-02 `_hash_git_blob` raw `OSError` residual still present | recorded as a BM-02 follow-up, **not** modified; no BM-03 path depends on it | §9 R-1 |
| D09 | `seeded-balanced`, `B % T == 0`, caps satisfied | implemented `balanced-cyclic-v1` exactly as prescribed | `protocol/schedule.py`, SCHED-01/02 |
| D10 | Imbalanced explicit orders / non-divisible `B` | rejected with `BM_IDENTITY_INVALID`, no output | SCHED-04/05 |
| D11 | Historical 12×8 four-arm geometry | verified structurally (3 per arm per position), no claim of historical order equality | SCHED-02, `schedule-golden.md` |
| D13 | CPython 3.11 not installed on this host | 3.12 byte-level goldens verified; no cross-version assertion claimed | §9 R-4 |
| D14/D15 | Seed determinism and accidental row collisions | seed kept in the canonical payload; collisions accepted | SCHED-07 |
| D16/D17 | `nanoseconds`/`lower-is-better` synthetic samples only | other valid BM-01 units stay inspect-valid but execution stops `BM_NOT_IMPLEMENTED` | `test_other_metric_units_are_not_executable` |
| D18 | Real build identity or official scope reaching the executor | `BM_ACQUISITION_PROHIBITED` before any side effect | SCOPE-01 |
| D19 | Unexpected scenario fields/counts/pairings | strict rejection, no coercion | `test_execution_scenario.py` (17 tests) |
| D20/D21/D22 | `required_controls` 0 / exact-equality / unknown contract | `not-required` record / alias A/A / typed refusal before output | CTRL-03, CTRL-01, CTRL-04 |
| D23 | A/A replica mismatch | `STOPPED/CONTROL_MISMATCH`, zero treatment slots, no seal | CTRL-02 |
| D24/D25 | Fresh readiness clear / blocked | one campaign per batch / `STOPPED/HOST_NOT_READY` | READY-01…05 |
| D27/D28 | Adapter returns exact BM-01 types vs wrong status/scope/lane/unit/count | validated every field, then committed; wrong envelopes stop with no completed slot | ADAPT-01…07 |
| D29/D32 | Oracle failure before warmup / cleanup after prepare | stop with cleanup exactly once | ADAPT-02, ADAPT-07 |
| D31/D33/D34 | Partial lane bytes / duplicate UUID / symlink or protected path | preserved bytes, `BM_PUBLICATION_CONFLICT`, `BM_UNSAFE_INPUT` | STORE-02/04/05/06, PATH-01…03 |
| D36/D37/D38 | Crash, seal mismatch, extra file | replay reports interrupted/unsafe and never repairs | FAULT-04, SEAL-02/03, REPLAY-05 |
| D40 | No statistics/analysis implementation | BM-03 stays structural-only; no decision fields in any output | FLOW-03, SEAL-05 |
| D43 | Two deterministic defects found while building the tree (capability topology path depth; measurement-equality contradiction) | fixed inside the prescribed modules; see §8 | this report |
| D47/D48/D49 | Local gates passed, external CI/PR state unknown at report-writing time | reported as `BM03_IMPLEMENTED_CI_UNVERIFIED` until exact-SHA CI is inspected | §10 |

No HARD STOP condition was reached.

## 8. Defects found and corrected during implementation

1. **Simulated capability path depth.** `SimulatedCapabilityProvider` initially
   parsed eight-component `/sys/.../topology/<field>` paths with a seven-component
   assumption, so every capability snapshot looked incomplete and the controller
   stopped with `host-not-ready`. Corrected in `execution/controller.py`
   (`len(parts) == 8`, `parts[6] == "topology"`, field at `parts[7]`); covered by
   `test_ready_05_*` and by the full sealed-run fixtures.
2. **Measurement equality vs. A/A observability.** Requiring the controller to
   compare returned samples with the declared scenario values made a control
   mismatch unreachable (see `invariant-traceability.md` §"Detected
   contradictions"). The controller now validates count/positivity/unit/
   direction/lane/scope, and the read-only replayer independently enforces the
   declared scenario values and lane digests. `CTRL-02` and `SEAL-04` are both
   exercised.

## 9. Residual risks (dispositions)

| ID | Risk | Severity / owner | Disposition |
| --- | --- | --- | --- |
| R-1 | Inherited BM-02 defect: `evidence/provenance.py::_hash_git_blob()` rethrows a raw `OSError` when a streaming read raises | Low for BM-03; **BM-02 owner** | **Disclosed, unmodified.** No BM-03 path calls it (D07); would be a HARD STOP only if a required BM-03 gate depended on it (D08). Not represented as resolved. |
| R-2 | Actual host contention, thermal drift, OS scheduling and real A/A stability are not simulated faithfully | High for real benchmarks; **BM-09** | Explicitly DEFERRED. Simulated readiness is a control-flow test only. No real qualification claimed. |
| R-3 | The prescribed fixture gives identical readiness observations to every campaign, so a byte-identical "reused batch" cannot be distinguished from a correct one | Low; BM-03 design | Partially mitigated: the provider is single-use (`ScenarioReadinessProvider` consumes keys), the controller refuses a second request for the same campaign key, and any batch that is not exactly the declared one (missing/duplicated/altered) is rejected (`READY-06`). Documented rather than papered over. |
| R-4 | `balanced-cyclic-v1` byte goldens are defined for CPython 3.12; Python 3.11 was not installed on the verification host | Low; BM-03 owner | The package still declares `>=3.11`, CI uses 3.12, and no cross-version golden equality is claimed. A 3.11/3.12 divergence would be a HARD STOP for algorithm-version review (D13); none was observed because 3.11 could not be run. |
| R-5 | `ExecutionStore` durability is a local-filesystem simulation; real BM-09 evidence durability and host policy are unproven | Medium; **BM-09 architecture** | Documented in `design-and-contracts.md` §9; the store is not presented as a production evidence backend and cannot be promoted by changing an origin string. |
| R-6 | The real Quervant adapter is not yet migrated onto the shared Python execution seam | Medium; **BM-07/08** | Explicitly DEFERRED. BM-03 proves only that the frozen seam can represent a search lane and its oracle (`test_execution_quervant_contract.py`) plus the existing untimed Rust suite. |
| R-7 | Statistical policy, bootstrap/CI, pruning and A–E receipts are absent | Medium; **BM-04/05/06** | Explicitly DEFERRED; no placeholder PASS or invented winner exists. |
| R-8 | Legacy historical equivalence may depend on external archives | Low; **BM-07/09** | If unavailable, the historical comparison is `EVIDENCE_UNAVAILABLE`; nothing was fabricated. |

## 10. CI status

Local QA at the tree described above is complete. GitHub Actions jobs
(`python-contracts`, `rust`, `msrv`, `rustfs`) are required at the **exact PR head
SHA**; their status is recorded in the PR closeout comment after push. Until then
the disposition is `BM03_IMPLEMENTED_CI_UNVERIFIED`, and this document makes no C2
or architecture-acceptance claim.

The `rustfs` job remains the only real RustFS integration topology; BM-03's
simulated capability provider is **not** RustFS or WSL2 acceptance.

## 11. Disposition

```text
UNRESOLVED_FAILURES=none locally
DISPOSITION=BM03_IMPLEMENTED_CI_UNVERIFIED  ->  BM03_READY_FOR_INDEPENDENT_REVIEW
             once all four exact-SHA CI jobs pass
```

C2 means reusable simulated mechanics — never real measurement qualification.
