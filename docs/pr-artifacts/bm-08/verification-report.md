# BM-08 verification report

Executed on the local working tree of branch `dev/bm08-cross-engine-reference`,
branched from `main` = `a6475c5d16d388ae5969071ba4ffa039cf042730` (BM-07 merge
ancestor `49e97ec7eb5992aee04c99f7a03e9386bab44f47` verified).

No real timing was acquired. `cargo bench` was only compiled (`--no-run`), no PR15D
harness/smoke script or adapter `query` was run, and no Gradle/JDK/Tantivy build was
attempted.

## Completion fields

```
REPO=yduchesne/quervant
PR_SCOPE=BM08-CROSS-ENGINE-SYNTHETIC-REFERENCE
BRANCH=dev/bm08-cross-engine-reference
MAIN_BASE_SHA=a6475c5d16d388ae5969071ba4ffa039cf042730
BM07_MERGED_ANCESTOR=49e97ec7eb5992aee04c99f7a03e9386bab44f47 VERIFIED
START_HEAD=a6475c5d16d388ae5969071ba4ffa039cf042730
FINAL_IMPLEMENTATION_SHA=ff747d80a4857f234e617794a919008d4120068f
WORKTREE=clean after commit ff747d8 (all checks executed on that tree)
PRE_IMPLEMENTATION_CORRECTNESS_GATE=PASS (baseline full Python suite green before edits)
CATALOG_LANES=16
SIMULATED_ENGINE_LABELS=quervant,tantivy,lucene
UNTIMED_PROJECTIONS=48 validated; no live adapters
SIMULATED_SLOTS=84; LANE_ENVELOPES=1344; SYNTHETIC_SAMPLES=4032
SIMULATED_BM03/BM04/BM05/BM06=PASS
POLICY_STATUS=INCONCLUSIVE; SELECTED_ARM=null (synthetic only)
BM06_MEMBERS=15; RECEIPT_GATES=7
BM07_RETAINED_KEY_REGRESSION=PASS
TWO_FAMILY_OFFLINE_CLI=PASS
REAL_ADAPTER_RUNTIME_CORRECTNESS=NOT_EXECUTED
REAL_TIMED_ACQUISITION=NOT_RUN
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
PYTHON_TARGETED=90 (cross-engine modules), plus 490 retained-key/qualification/verification/analysis tests
PYTHON_FULL=942 passed, 0 failed, 1 skipped
RUST_MSRV/STABLE=PASS (stable 1.98.1, MSRV 1.85.0)
RUST_COVERAGE=92.69% lines / 87.72% functions / 92.03% regions (floor 85%)
BENCH_COMPILE_ONLY=PASS
RUSTFS_CI=UNVERIFIED locally (not provisioned); requires final-head `rustfs` job
FINAL_REMOTE_HEAD=ff747d80a4857f234e617794a919008d4120068f (pushed)
FINAL_CI_RUN_URL=NONE (gh token invalid: PR creation and CI observation blocked by D57)
FINAL_CI_GATE=UNVERIFIED
INDEPENDENT_REVIEW=PENDING
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS
MERGED=NO
```

## Digests

```
SOURCE_SET_DIGEST     sha256:4a8bebdec04038bf1b92405940d3b05371909749b9b2352b629c894ef3f820ce
FRAMEWORK_QA_DIGEST   sha256:c120b2a645c253268b63eaec4e155ded351a22e4d75eaa5ce9e712370a979689
SOURCE_QA_DIGEST      sha256:3500372bedd5626ed2bced4af50738390a71021c34a06cb985a939106db08967
PROFILE_DIGEST        sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c (unchanged)
oracle-golden.v1.json         sha256:16251eab509742e51cab9bbc7c92489ed6bfa99928f445c09cbc293132215392
engine-source-bindings.v1.json sha256:549c3dfb3c5e583f77ea04390ca48affd5a577ea8a9d4c5d2871c77d3263e902
semantic-comparability.v1.json sha256:351d7edad064ed96beb6e37f37ee5ff1e3f00ac64861fd1148bb82435819d6e2
workloads.yaml                sha256:4f52590fb5de0aff5de7706b82cc2ef5ea94125e6fdf34fe9348ea2737105721
protocol.yaml                 sha256:d157326d84cb33280e3fd9f78ca12f0b8ef6e2e6c0ed3f926cf91f9d18fb91a1
```

Previous trust anchors (before the controlled re-freeze):

```
source_set_digest   sha256:28170ada72d89f00277543a7e2b73def9367bc6a24dcb82ad0be31ebf560a659
framework_qa_digest sha256:0e8408ebee8e54fe5465bc79610a07d5fd71b5f57ba584bded09b651637310e3
source_qa_digest    sha256:e1abe182ab046edf3cfc254932927a29346b75616919441fadaf89fe8a94f31a
```

## Commands executed (final tree)

| Command | Result |
|---|---|
| `python -m compileall -q benchmarks/quervant_bench` | PASS |
| `PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_cross_engine_*.py' -v` | PASS — 90 tests |
| `... -p 'test_retained_key_*.py'` | PASS — 80 tests |
| `... -p 'test_qualification_*.py'` | PASS — 109 tests |
| `... -p 'test_verification_*.py'` | PASS — 111 tests |
| `... -p 'test_analysis_*.py'` | PASS — 190 tests |
| `... -p 'test_*.py'` | PASS — 942 tests, 1 skipped |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.69% lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| `git diff --check` | PASS |

The single skip is the pre-existing
`test_cli_02_module_entrypoint_matches_console_contract` ("console script is not
installed in this interpreter"), classified **environment/harness**, not a BM-08
defect. The `D46` alternative (`PYTHONPATH=benchmarks`) was used; CI owns the
installed-console check.

## Invariants CE01–CE22

All PASS except CE22, which is PASS for the executed local gates with
`INDEPENDENT_REVIEW=PENDING` and `FINAL_CI_GATE=UNVERIFIED`.

| ID | Result | Evidence |
|---|---|---|
| CE01 | PASS | `CAT-01`, `CAT-02` |
| CE02 | PASS | `BND-01`–`BND-03` |
| CE03 | PASS | `CMP-01`, `CMP-02`, `ANA-05` |
| CE04 | PASS | `ORA-01`–`ORA-08` |
| CE05 | PASS | `WIR-01`–`WIR-08` |
| CE06 | PASS | `SRC-01`–`SRC-06` |
| CE07 | PASS | `SIM-01`, `SIM-05` |
| CE08 | PASS (observed slice) | `SCH-01`–`SCH-03`; see deviation 2 |
| CE09 | PASS | `ANA-01`–`ANA-04` |
| CE10 | PASS | `VER-01`–`VER-03` |
| CE11 | PASS | `E2E-01`, `E2E-03`, `E2E-04` |
| CE12 | PASS | `SCOPE-01`, `SCOPE-02` |
| CE13 | PASS | `REU-01`–`REU-03`, `REU-04` |
| CE14 | PASS | `CLI-01`, `CLI-06`, `CLI-07`, `CLI-10` |
| CE15 | PASS | `CLI-04`, `CLI-05`, `CLI-09` |
| CE16 | PASS | `REG-01`–`REG-04` |
| CE17 | PASS | `HIST-01`–`HIST-03` |
| CE18 | PASS | `CMP-03`, `CMP-04`, `ANA-05` |
| CE19 | PASS | `ANC-01`, `ANC-03`, `F06-A-01/02` (existing) |
| CE20 | PASS | `SAFE-01`–`SAFE-04`; no timed command executed |
| CE21 | PASS | `CAT-04`, `CLI-08` |
| CE22 | PASS (local) / review pending | this table + statuses above |

## Decision-matrix rules used

| Rule | Trigger | Action taken |
|---|---|---|
| D01 | `main` = `a6475c5…` with BM-07 ancestor | Branched from clean `main`; SHA recorded |
| D05 | BM-01 v1 loader accepts JSON-as-YAML | Catalog stored as canonical JSON bytes + LF |
| D07/D08 | exactly `quervant,tantivy,lucene`, one manifest | Labels bound in prescribed order to the one simulator |
| D09/D10 | BM-03 synthetic-only; adapters use `Instant`/`nanoTime` | Preserved guard; no live `op=query`; projections only |
| D11/D12 | frozen 16-lane matrix; exact version pins | Frozen matrix and raw-byte source bindings |
| D13/D16/D65 | adapter pins present, but prescribed schedule unrepresentable | Escalated as the two deviations below; controller/schema unchanged |
| D17/D18/D19 | ledger digest-bound; coherent rehash | Pre/post and offline revalidation, typed rejection |
| D20/D21/D22 | scored/cold/throughput have no verified contract | Recorded `NONCOMPARABLE`/`DEFERRED`, excluded |
| D23 | independent oracle matches formula | Exact 16-row golden, no BM-04 reuse |
| D25/D26 | timed/extra fields, count-only match | Closed six-field projection, element-wise IDs |
| D28/D29 | new `.py` files stale the anchors | Full controlled re-freeze repeated after the final `.py` edit |
| D32/D33/D34/D35 | family routing | Frozen two-entry literal map, ambiguity/foreign rejection, second ledger check |
| D36/D37/D38 | committed reuse/collision | `REUSED_VERIFIED` via unchanged BM-06 loader; no rewrite |
| D39/D40/D61 | no authentic historical archive | `EVIDENCE_UNAVAILABLE`; historical gate `BLOCKED` |
| D44/D45/D46 | toolchains present; RustFS absent; no editable install | MSRV+stable executed; RustFS `UNVERIFIED`; `PYTHONPATH` used |
| D47 | all-equal sample yields `INCONCLUSIVE` | Matches primary output; thresholds unchanged |
| D49/D50/D62 | stopped runs, relabelling, partial trees | No qualification, typed rejection, no repair |
| D57 | no GitHub auth in this environment | Branch push/PR/CI left to the operator; CI `UNVERIFIED` |

## Deviations requiring reviewer approval

1. **`field`/`term` live in `oracle-golden.v1.json`, not in lane `params`.** The
   frozen `workload.v1.schema.json` sets `params.additionalProperties = false` with
   only `corpus_size`, `top_k`, `selectivity_class`, `query_id`, `batch_size`,
   `segment_count`. Adding `field`/`term` would change a frozen public v1 schema,
   which BM-08 prohibits. The reviewed golden is digest-bound into the ledger and
   every lane is cross-checked against it, so the semantic contract is unchanged and
   arguably stronger.
2. **`schedule.blocks = 6`, not 4.** The frozen `balanced-cyclic-v1` generator
   rejects the prescribed layout: with three arms × 2 slots and `slots_per_block=6`
   the tile size is 3, so `blocks` must be a multiple of 3; the control contract also
   requires an even count. Observed controller evidence:
   `blocks 3 OK`, `blocks 4 REJECT BM_IDENTITY_INVALID "schedule.blocks must be
   divisible by the balanced tile size 3"`, `blocks 6 OK`, `blocks 8 REJECT`,
   `blocks 12 OK`. Six blocks yields 84/1344/4032 instead of the plan's 56/896/2688.
   The controller arithmetic was **not** modified to force the plan's numbers.

## Failure classifications

- `test_cli_02_module_entrypoint_matches_console_contract` skip →
  **environment/harness** (console script not installed; CI contract).
- No introduced regressions, feature defects, deterministic pre-existing failures or
  flaky failures were observed in the executed suites.
- RustFS service acceptance is **not executed locally** (infrastructure unavailable);
  the final-head `rustfs` CI job remains required.

## Residual risks (disclosed, not waived)

No live engine query was made; source inspection is not binary identity; projected
replies are synthetic; a logical warm regime is not physical cache comparability;
there is no scored BM25 or process-cold parity; historical external result parity is
absent; source/ledger hashes are identity, not signatures; there is no global
multi-root atomic snapshot; and no performance extrapolation is possible. All are
deferred to BM-09 or later separately approved integration.

---

## RF08-01/RF08-02 review fixup (appended; earlier observations above are unchanged)

An independent review found two trust-boundary defects. Both are closed and verified
under the `BM08-RF08-F1` plan; details and per-test evidence live in
[`review-fixup-evidence.md`](review-fixup-evidence.md). This section **corrects**,
and does not rewrite, the earlier status.

### Corrected statements

- `validate_keyword_reply_projection` no longer trusts a caller-supplied oracle row.
  It recomputes the reviewed row from the validated lane
  (`oracle_row_for_lane`), requires the exact closed eight-key shape with strict
  primitive types (a boolean is never an integer), and compares the reply against
  that independently derived truth only.
- Catalog authorization is now an explicit reviewed v1 identity, not a runtime
  self-check. `EXPECTED_CATALOG_RAW_SHA256` pins all eleven members by raw-byte
  SHA-256 and `EXPECTED_PROTOCOL_CONTENT_DIGEST` pins the protocol document. The
  frozen `CrossEngineCompanionDigests` gained a fifth required field,
  `catalog_members_digest`, a canonical snapshot over the eleven members.
  `load_cross_engine_reference` verifies the pins **before** the BM-01 loader, and
  the producer, `validate_cross_engine_reference` and the cross-engine offline arm
  all compare the full snapshot before and after BM-06.
- The retained-key (BM-07) offline branch is unchanged.

### Updated gate status

```
RF08_01=CLOSED
RF08_02=CLOSED
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS
LOCAL_QA_GATE=PASS
PYTHON_FULL=965 passed, 0 failed, 1 skipped (environment: console script absent)
CROSS_ENGINE_TESTS=113 passed
RUST_STABLE=PASS; RUST_MSRV=PASS
RUST_COVERAGE=92.70% lines
SOURCE_SET_DIGEST=sha256:4d707657ed57b6dd8fea095a9d3e44e2da950f41a4397141dc4c4746817d28d7
FRAMEWORK_QA_DIGEST=sha256:eae537ae846ddf342d456ce8d1d682de1847f79c633a6e26a55eba91530d8134
SOURCE_QA_DIGEST=sha256:b91e5ca35b3759fabc0b66023b38102773b62d160a117a05586fd1ce8ed7fadb
PROFILE_DIGEST=sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c (unchanged)
CATALOG_V1_PINS=11/11 unchanged
FINAL_CI_GATE=UNVERIFIED (see the fixup evidence file)
INDEPENDENT_REVIEW=PENDING
REAL_TIMED_ACQUISITION=NOT_RUN
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED; HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED; LEGACY_PATHS_RETIRED=NO
MERGED=NO
```
