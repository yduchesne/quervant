# BM-08 RF08-01/RF08-02 trust-boundary fixup evidence

Plan: `BM08-RF08-F1` (independent-review fixup). Starting HEAD and branch were
verified against the reviewed values; no history was rewritten.

## Preflight (recorded before any production edit)

```
AUTHORIZED_START_HEAD   def018199dc4bdec3bcc038120002f9947d7b6bf
ACTUAL_START_HEAD       def018199dc4bdec3bcc038120002f9947d7b6bf
ORIGIN_BRANCH_HEAD      def018199dc4bdec3bcc038120002f9947d7b6bf
MAIN_MERGE_BASE         a6475c5d16d388ae5969071ba4ffa039cf042730
ORIGIN_MAIN             a6475c5d16d388ae5969071ba4ffa039cf042730
WORKTREE                clean
```

Catalog pin preflight: all eleven checked-in catalog files were independently hashed
(raw bytes, including the trailing newline) at the starting HEAD. **All eleven
matched the reviewed `EXPECTED_CATALOG_RAW_SHA256` values**, and
`content_digest(protocol.yaml)` equalled
`sha256:d157326d84cb33280e3fd9f78ca12f0b8ef6e2e6c0ed3f926cf91f9d18fb91a1`.
No pin was recalculated and no catalog byte was edited.

Baseline (starting HEAD, agent re-measured): `test_cross_engine_*.py` = 90 tests OK;
full Python suite = 942 passed, 1 environment skip (console script not installed).
These are the fixup baseline, not acceptance evidence.

## Reviewed findings

### RF08-01 — mutually forged oracle row and reply

`validate_keyword_reply_projection(lane, engine_id, reply, oracle_row)` checked only
that `oracle_row` was a mapping whose `lane_id` matched the lane, then compared the
reply to the *caller-supplied* `total_hits`/`doc_ids`. A coherent forged pair was
therefore self-validating.

False-PASS reproductions (see `ForgedOracleRowTests`):

| Test | Forged input | Old behaviour |
|---|---|---|
| `WFX-02` | rare lane, row `total_hits=2`, ids `[d00000000, d00000001]`, matching closed reply | accepted (`None`) |
| `WFX-03` | rare lane, row `total_hits=1`, ids `[d00000001]`, matching closed reply | accepted |
| `WFX-04` | rare lane, row `field='group'`, otherwise true, matching closed reply | accepted |
| `WFX-06` | row missing `term` (extra `engine_ns`, non-list `doc_ids`) | missing/extra keys accepted |

### RF08-02 — catalog drift survives companion-only recheck

`CrossEngineCompanionDigests` carried only the four companion digests. A schema-valid
edit to e.g. `protocol.yaml.schedule.seed` (42 → 43) left all four unchanged, so both
the producer and the offline reader could accept an unauthorized v1 catalog, and a
mutation injected after BM-06 verification was invisible.

False-ACCEPT reproductions:

| Test | Injected change | Old behaviour |
|---|---|---|
| `CFX-02` | copied catalog, only `schedule.seed` 42 → 43 | validated successfully |
| `CFX-07` | real BM-06 publication, then seed mutation before the wrapper's final check | returned `SIMULATED_QUALIFIED` |
| `CFX-10` | real BM-06 load, then seed mutation before the offline final check | rendered a success view |

## FX08 invariants → test ownership

| Invariant | Requirement | Positive | Negative |
|---|---|---|---|
| FX08-01 | Oracle truth recomputed from the validated lane | WFX-01 | WFX-02/03/04 |
| FX08-02 | Closed eight-key row with exact primitive types | WFX-01 | WFX-05/06 |
| FX08-03 | Count and ordered IDs equal the canonical oracle | WFX-01, WFX-07 | WFX-02/03/07 |
| FX08-04 | Six-field closed projection, no timer/score/binary | WFX-01 | WFX-08, WIR-02 |
| FX08-05 | Eleven hardcoded reviewed raw SHA-256 pins | CFX-01 | CFX-02/03/04 |
| FX08-06 | Reviewed protocol semantic digest is authoritative | CFX-01 | CFX-02/05 |
| FX08-07 | Prequalification freezes full 11-file identity | CFX-01 | CFX-02/03 |
| FX08-08 | Postqualification recheck refuses any drift | CFX-06 | CFX-07/08, CFX-16 |
| FX08-09 | Offline recheck of full 11-file identity | CFX-09 | CFX-10/11 |
| FX08-10 | No new derivation/write/retry/timing in offline views | CFX-09 | REG-01…04, SAFE-01…05 |
| FX08-11 | BM-01…07 readers/schemas/trust unchanged | regression suites | CFX-12, anchored source tests |
| FX08-12 | Synthetic evidence is not real/official/historical | E2E-01 | SCOPE-01/02, HIST-01…06 |

## Decision-rule families applied

- `D01`/`D03`: reviewed HEAD and merge base verified, no rebase.
- `D06`: all eleven raw pins re-verified locally before editing; all matched.
- `D07`/`D08`/`D09`/`D10`/`D11`/`D12`/`D13`/`D14`: RF08-01 implemented by
  independent recomputation, closed keys, strict types, existing ID validator and
  the existing six-field projection.
- `D16`–`D28`: RF08-02 implemented with the literal pin table, the reviewed protocol
  content digest, a full 11-member snapshot token, and pre/post comparisons in the
  producer and the cross-engine offline arm only.
- `D33`/`D34`/`D35`: retained-key path, 6-block schedule and golden-bound
  `field`/`term` preserved unchanged.
- `D37`/`D38`: all mutations applied to temporary catalog copies; the real BM-06
  call is executed and only the post-BM-06 seam is patched.
- `D39`/`D40`: one complete controlled QA re-freeze after the final Python edit.
- `D45`/`D47`/`D48`: RustFS and GitHub Actions availability handled as
  deferred/unverified, never as a pass.
- `D53`: no timed acquisition, no real adapter query.

## Result sections

Red/green outcomes, the per-test matrix results, the re-freeze ledger and the final
gate statuses are appended below after execution. This file is append-only.

---

# Execution results (appended after implementation)

## Red gate (observed on the pre-fix production code)

`python -m unittest quervant_bench.tests.test_cross_engine_semantics.ForgedOracleRowTests`

| Test | Red observation |
|---|---|
| WFX-01 | PASS (positive control, unchanged) |
| WFX-02 | `AssertionError: BenchError not raised` — forged count+IDs accepted |
| WFX-03 | `AssertionError: BenchError not raised` — forged singleton ID accepted |
| WFX-04 | `AssertionError: BenchError not raised` — forged `field` accepted |
| WFX-05 | `AssertionError: 'BM_IDENTITY_INVALID' != 'BM_SCHEMA_INVALID'` — bool leaked into the row type path |
| WFX-06 | `AssertionError: BenchError not raised` — extra/missing row keys accepted |
| WFX-07 | PASS (positive control) |
| WFX-08 | PASS (positive control) |

`python -m unittest quervant_bench.tests.test_cross_engine_catalog.CatalogPinTests`

| Test | Red observation |
|---|---|
| CFX-01 | `AttributeError: 'CrossEngineCompanionDigests' object has no attribute 'catalog_members_digest'` |
| CFX-02 | `AssertionError: BenchError not raised` — seed 43 accepted |
| CFX-03 | `AssertionError: BenchError not raised` for each of the 11 members |
| CFX-04 | PASS (existing closed-set/safe-path behaviour) |
| CFX-05 | `AssertionError: BenchError not raised` — coherently rehashed v1 edit accepted |

`python -m unittest quervant_bench.tests.test_cross_engine_synthetic.CatalogDriftTests`

| Test | Red observation |
|---|---|
| CFX-06 | PASS (positive control) |
| CFX-07 | `AssertionError: BenchError not raised` — wrapper returned success after post-BM-06 seed drift |
| CFX-08 | `AssertionError: 'policy_id' != 'catalog.policy-profile.v1.json'` (later retargeted to `resource-observations.v1.json`, which old code accepted with no rejection) |
| CFX-15 | `AssertionError: BenchError not raised` — a `process-cold` lane still produced a numeric projection |
| CFX-16 | `AssertionError: 'rows[0].field' != 'catalog.oracle-golden.v1.json'` |

`python -m unittest quervant_bench.tests.test_cross_engine_offline.OfflineDriftTests`

| Test | Red observation |
|---|---|
| CFX-09/11/12 | PASS (positive/regression controls) |
| CFX-10 | `AssertionError: 0 == 0` — offline read returned success after post-BM-06 seed drift |
| CFX-13 | anchor mismatch, because the checked-in QA chain predated the fixup source (closed by the re-freeze) |

Note: the two reviewed pin literals (`EXPECTED_CATALOG_RAW_SHA256`,
`EXPECTED_PROTOCOL_CONTENT_DIGEST`) were added as inert constants so the behavioural
assertions could be imported; no validation barrier existed at red-gate time.

## Green gate (final source)

| Suite | Result |
|---|---|
| `test_cross_engine_*.py` | **113 tests OK** (90 preserved + 23 new) |
| WFX-01…08 | 8/8 PASS |
| CFX-01…05 | 5/5 PASS |
| CFX-06/07/08/15/16 | 5/5 PASS |
| CFX-09…13 | 5/5 PASS |
| `test_retained_key_*.py` | PASS |
| `test_qualification_*.py` | PASS |
| `test_verification_*.py` | PASS |
| `test_analysis_*.py` | PASS |
| Full `test_*.py` | **965 passed, 0 failed, 1 skipped** |
| `compileall` | PASS |
| BM-01 contract inventory | PASS |
| `test-scripts.sh` | 108 passed, 0 failed |

Existing BM-08 tests whose mutation reached a deeper validator now observe the
earlier reviewed-raw-byte barrier. Their assertions were updated to the new
authoritative failure **and** the companion/semantic validators are still exercised
directly (`BND-02`, `CAT-04`, `CMP-02`), so no original semantic coverage was lost.

## Per-member rejection detail (CFX-03)

All eleven mutations are canonical JSON edits written with
`canonical_document_bytes` (no append-one-byte cases were needed). Each was rejected
at the **static pin** barrier with `BM_IDENTITY_INVALID` and
`field_path == "catalog.<name>"`:

`adapter.yaml`, `analysis-profile.v1.json`, `engine-source-bindings.v1.json`,
`experiment.yaml`, `oracle-golden.v1.json`, `policy-profile.v1.json`,
`protocol.yaml`, `resource-observations.v1.json`, `semantic-comparability.v1.json`,
`synthetic-scenario.v1.json`, `workloads.yaml`.

`CFX-04` rejects missing/extra members via the closed 11-file inventory
(`BM_IDENTITY_INVALID`), and symlinked/directory/oversized members via
`BM_UNSAFE_INPUT`.

## Controlled synthetic QA re-freeze

Performed once after the final Python edit (test-only anchor assertion fix), then
the whole chain was re-verified.

```
PREVIOUS source_set_digest   sha256:4a8bebdec04038bf1b92405940d3b05371909749b9b2352b629c894ef3f820ce
PREVIOUS framework_qa_digest sha256:c120b2a645c253268b63eaec4e155ded351a22e4d75eaa5ce9e712370a979689
PREVIOUS source_qa_digest    sha256:3500372bedd5626ed2bced4af50738390a71021c34a06cb985a939106db08967

FINAL source_set_digest      sha256:4d707657ed57b6dd8fea095a9d3e44e2da950f41a4397141dc4c4746817d28d7
FINAL framework_qa_digest    sha256:eae537ae846ddf342d456ce8d1d682de1847f79c633a6e26a55eba91530d8134
FINAL source_qa_digest       sha256:b91e5ca35b3759fabc0b66023b38102773b62d160a117a05586fd1ce8ed7fadb
PROFILE_DIGEST (unchanged)   sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c
```

Only the nine existing per-check `source_set_digest` values, their recomputed
`evidence_digest` entries and the three anchor digests changed. No QA status,
roster, toolchain ID or profile value changed. The **reviewed v1 catalog pins were
not touched**; the two hash families remain separate.

## Local QA gate

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 fmt/clippy/test …` | PASS |
| `cargo llvm-cov … --fail-under-lines 85` | PASS — 92.70% lines / 87.72% functions / 92.04% regions |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| `git diff --check` | PASS |

No timed benchmark, PR15D harness/smoke, adapter query, profiler or A/A campaign was
executed.

## Final report template

```text
REPO=yduchesne/quervant
PR=109
SCOPE=BM08-RF08-01-02-TRUST-BOUNDARY-FIXUP
BRANCH=dev/bm08-cross-engine-reference
AUTHORIZED_START_HEAD=def018199dc4bdec3bcc038120002f9947d7b6bf
ACTUAL_START_HEAD=def018199dc4bdec3bcc038120002f9947d7b6bf
MAIN_MERGE_BASE=a6475c5d16d388ae5969071ba4ffa039cf042730
RF08_01=CLOSED (WFX-02/03/04/05/06 red->green)
RF08_02=CLOSED (CFX-02/03/05/07/08/10/16 red->green)
CATALOG_MEMBER_COUNT=11
CATALOG_V1_PINS=all unchanged
AUTHORIZED_PROTOCOL_CONTENT_DIGEST=sha256:d157326d84cb33280e3fd9f78ca12f0b8ef6e2e6c0ed3f926cf91f9d18fb91a1
SOURCE_SET_DIGEST=sha256:4d707657ed57b6dd8fea095a9d3e44e2da950f41a4397141dc4c4746817d28d7
FRAMEWORK_QA_DIGEST=sha256:eae537ae846ddf342d456ce8d1d682de1847f79c633a6e26a55eba91530d8134
SOURCE_QA_DIGEST=sha256:b91e5ca35b3759fabc0b66023b38102773b62d160a117a05586fd1ce8ed7fadb
PROFILE_DIGEST=sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c
BM08_SYNTHETIC_A_E=PASS (15 members, 7 gates, INCONCLUSIVE, selected null)
BM07_REGRESSION=PASS
PYTHON_TARGETED=113 cross-engine, all pass
PYTHON_FULL=965 passed, 0 failed, 1 skipped
RUST_STABLE=PASS
RUST_MSRV=PASS
RUST_COVERAGE=92.70% lines (floor 85%)
REAL_TIMED_ACQUISITION=NOT_RUN
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
INDEPENDENT_REVIEW=PENDING
MERGED=NO
```

`FINAL_IMPLEMENTATION_SHA`, `FINAL_REMOTE_HEAD`, `FINAL_CI_HEAD`, `FINAL_CI_RUN_URL`,
`RUSTFS_CI` and the disposition are recorded in the pushed commit and the terminal
report: the fixup was pushed normally; hosted CI on the pushed SHA and independent
review remain external gates.

## Residual limitations

The reviewed pins are an in-repository version lock, not a signature or an immutable
remote trust root. Repository compromise and byte changes after the final filesystem
read are not prevented by this fixup; they remain disclosed residual risks. No
locking, watcher, filesystem transaction or background monitor was added.
