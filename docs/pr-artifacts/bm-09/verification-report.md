# BM-09 verification report

Append-only. This report records the implementation, local QA evidence and the
terminal disposition. It contains no private host paths.

## 1. Status matrix

| Dimension | Status |
| --- | --- |
| Implementation gate | **PASS** (all specified modules, templates, tests and docs exist and compile) |
| Correctness gate (O01–O22 deterministic/adversarial) | **PASS** — 230 official tests, including forged-G0, rehashed-forgery, scope-swap, slot/answer mutation, fault-seam and blocked-parity cases |
| Source/QA gate (local portion) | **PARTIAL** — all local Rust stable/MSRV/coverage/doc/bench-compile and Python gates pass; hosted CI and hosted RustFS are **UNVERIFIED** from this terminal |
| Real family acquisition | **BLOCKED** for both families (no independent G0 authorization; D3-C T6 absent; PR15D corpus/adapter set unprovisioned) |
| Historical parity | **BLOCKED** (authentic PR15D archive absent; D3-C numeric replay and reviewer-approved mapping not executed) |
| C6 / v0.1-bench closeout | **BLOCKED** |

Final disposition: **`BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED`**.

## 2. What a reviewer must not infer

- No real benchmark was run, no engine was launched and no timing series exists.
- `official` tests use temporary fixture roots tagged test-only; they are not
  evidence for any real claim.
- The 92.04% line coverage is Rust workspace coverage of unchanged crates.
- The roadmap `v0.1-bench` checkpoint C6 remains blocked; the roadmap file is
  intentionally untouched.

## 3. Change inventory

Added (23 files): `benchmarks/quervant_bench/official/{__init__,contracts,protocols,
acquisition,controls,admission,analysis,verification,receipts,publication,
coordinator,historical,report}.py`, `benchmarks/official-protocols/{retained-key-topk-v1,
cross-engine-keyword-v1}.json`, `benchmarks/quervant_bench/tests/official_support.py`,
twelve `test_official_*.py` modules, and the eight `docs/pr-artifacts/bm-09/*` files.

Modified (3 files): `benchmarks/quervant_bench/qualification/identity.py`
(`SOURCE_DIRECTORIES` + one entry), `benchmarks/quervant_bench/qualification/publication.py`
(private byte-level publisher extraction; public API, validators, inventory and fault
semantics unchanged), `benchmarks/quervant_bench/tests/fixtures/qualification/**`
(one controlled synthetic re-freeze).

Docs updated: `benchmarks/README.md`, `docs/BENCHMARKING.md` (current-state sections
only; historical sections untouched).

Untouched by design: `crates/**`, `benchmarks/pr15d/**`, `benchmarks/pr15i_d3_c/**`,
`benchmarks/pr15i_d3_c_t7*`, BM-01 schemas, BM-07/08 catalogs, `benchmarks/reports/**`.

## 4. Command evidence

| Command | Result |
| --- | --- |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_official_*.py'` | PASS — 230 tests |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | PASS — 1,195 tests, 0 skips (pinned venv) |
| `python benchmarks/pr15d/harness/test_pr15d.py` | 83 tests, **1 pre-existing failure** (`test_t01…`, reproduced on baseline `a5a8303`), 3 skips |
| `python benchmarks/pr15i_d3_c/test_verify.py` | pre-existing module skip (needs T6/dry-proof artefacts) |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check …` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |
| `pip install -e ./benchmarks` + `quervant-bench inspect …` | PASS — console entrypoint executes |
| `cargo fmt --all -- --check` / `cargo +1.85.0 fmt …` | PASS / PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS on rerun; one flaky `quervant-core` test (classification 4) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.04% lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `git diff --check` | PASS |

## 5. Required final report block

```text
REPO=yduchesne/quervant
PR_SCOPE=BM09-REAL-FULL-QUALIFICATION
BRANCH=dev/bm09-real-qualification
PLANNING_MAIN_SHA=a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b
ACTUAL_MAIN_BASE_SHA=a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b
BM08_REVIEWED_ANCESTOR=a1e97cb6b77096bf3431f1ba35bd794966c32420
START_HEAD=a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b
FINAL_IMPLEMENTATION_SHA=7878ebbbbfb0cba1bb715eef9cbf085a788a4279
FINAL_REMOTE_HEAD=7878ebbbbfb0cba1bb715eef9cbf085a788a4279
G0_CROSS_ENGINE_APPROVAL=PENDING
G0_RETAINED_KEY_APPROVAL=PENDING
G0_SOURCE_LOCK_SHA256=UNAVAILABLE
G0_HOST_FINGERPRINT=UNAVAILABLE
G0_CROSS_ENGINE_BINARY_SET=UNAVAILABLE
G0_RETAINED_KEY_BINARY_SET=UNAVAILABLE
HOST_READINESS_CROSS_ENGINE=NOT_EXECUTED
HOST_READINESS_RETAINED_KEY=NOT_EXECUTED
REAL_AA_CROSS_ENGINE=NOT_EXECUTED
REAL_AA_RETAINED_KEY=NOT_EXECUTED
REAL_CROSS_ENGINE_FULL_SERIES=NOT_EXECUTED
REAL_RETAINED_KEY_FULL_SERIES=NOT_EXECUTED
REAL_CROSS_ENGINE_RAW_ROOT=UNAVAILABLE
REAL_RETAINED_KEY_RAW_ROOT=UNAVAILABLE
REAL_CROSS_ENGINE_GATE_A_B_C_QA_D_E=NOT_EXECUTED
REAL_RETAINED_KEY_GATE_A_B_C_QA_D_E=NOT_EXECUTED
REAL_CROSS_ENGINE_MANIFEST=NOT_PUBLISHED
REAL_RETAINED_KEY_MANIFEST=NOT_PUBLISHED
REAL_ATTESTATION_REOPEN=NOT_EXECUTED
REAL_PERFORMANCE_POLICY=NOT_EXECUTED
HISTORICAL_PR15D_PARITY=EVIDENCE_UNAVAILABLE
HISTORICAL_D3C_T7_F2_PARITY=EVIDENCE_UNAVAILABLE
LEGACY_RETIREMENT=NONE
L1_TESTS=PASS (1195 Python tests, 0 skips)
L2_RETAINED_KEY=PASS
L2_CROSS_ENGINE=PASS
RUST_STABLE=PASS
RUST_MSRV=PASS (one pre-existing flaky test, classification 4)
RUSTFS_REAL_HOSTED=UNVERIFIED
COMPARATIVE_FULL_CORRECTNESS=UNVERIFIED
RUST_COVERAGE=92.04% lines (threshold 85%)
FINAL_CI_HEAD=UNVERIFIED
FINAL_CI_RUN_URL=NONE
INDEPENDENT_G0_REVIEW=BLOCKED
INDEPENDENT_PR_REVIEW=PENDING
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS
LOCAL_QA_GATE=PARTIAL
REAL_QUALIFICATION_GATE=BLOCKED
HISTORICAL_PARITY_GATE=BLOCKED
C6_CLOSEOUT=BLOCKED
REAL_TIMED_ACQUISITION=NOT_RUN
HARD_STOP_RULES=NONE
AUTO_RESOLVE_RULES_USED=M01,M06,M07,M08,M10,M11,M17,M19,M76
DEFERRED_DECISIONS=M12 (retained-key T6 owner: operator/research), M24 (G0 reviewer), M34 (cross-engine toolchain owner), M53/M55 (parity owner), M74 (CI/RustFS owner)
UNRESOLVED_FAILURE_CLASSIFICATIONS=3 (pr15d test_t01 CI job-list assertion, reproduced on baseline), 4 (quervant-core u43 flaky, untouched crate)
PR_URL=NOT_CREATED (push succeeded; `gh` token invalid, compare URL https://github.com/yduchesne/quervant/compare/main...dev/bm09-real-qualification)
MERGED=NO
DISPOSITION=BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED
```

## 6. Adversarial self-review (O01–O22 counterexamples)

| Invariant | Counterexample attempted | Test that rejects it |
| --- | --- | --- |
| O01 scope | `synthetic`/`simulated` and `real`/`historical_replay` documents offered to official intake | `test_official_scope` (`O09-SCOPE-01..13`) |
| O02 G0 | candidate authorization accepted with its own digest | `O09-PRO-10`, `O09-PRO-11` |
| O03 D3-C diagnostic | `backend_diagnostic_flag` relabelled to false | `O09-PRO-06` |
| O04 PR15D contract | missing trial, 19 samples, wrong regime, wrong trial id | `O09-ACQ-01..08` |
| O05 D3-C contract | missing slot, wrong mode marker, changed sentinel, rehearsal flag | `O09-ACQ-09..16` |
| O06 readiness/A/A | busy host, unsupported platform, same CPU pair, noisy A/A | `O09-CTL-01..12` |
| O07 blocked control | failing control blocks admission and treatment | `O09-CTL-04b`, `test_official_coordinator` |
| O08 Gate A | seam tamper, 100K sentinel change, seal mismatch, unexpected member | `O09-ADM-*`, `O09-ACQ-16b` |
| O09 units/regimes | process-cold/throughput in the eligible set | `O09-ANA-05..08` |
| O10 frozen policy | cross-engine winner selection, invented decision status | `O09-ANA-11/12`, `O09-ANA-20` |
| O11 Gate C | forged ratio/median/dispersion/status, rehashed coherently | `O09-VER-08..14`, `O09-VER-16..18` |
| O12 receipts | dropped dependency edge, relabelled status, wrong subject | `O09-REC-04..09` |
| O13 QA | other source set, wrong gate, mandatory skip, not-executed | `O09-QA-01..05` |
| O14 publication | fsync/hard-link faults leave no marker; marker-only success impossible | `O09-PUB-09/10/11` |
| O15 reuse | mutated member, non-canonical member, removed member, wrong anchors | `O09-PUB-04..08`, `O09-REU-01..04` |
| O16 shared machinery | one builder/publisher/taxonomy for both families | `O09-REC-12`, `O09-E2E-01..06` |
| O17 legacy bytes | changed legacy source detected; archive read does not modify it | `O09-HIS-01..06`, `O09-HIS-15` |
| O18 parity | missing archive, no reviewer, non-equivalent contract | `O09-HIS-07..14` |
| O19 inconclusive | valid `INCONCLUSIVE` accepted structurally, no winner | `O09-ANA-11`, `O09-E2E-01` |
| O20 safety | traversal/duplicate/symlink/oversize archives, existing output reuse | `O09-ADM-05..08`, `O09-ACQ-13/15` |
| O21 CI/RustFS | recorded as `UNVERIFIED`, never as pass | this report §5 |
| O22 docs/closeout | closeout predicate set requires every real/historical/CI/review gate | `O09-DOC-01..06` |

## 7. Blockers and owners

| Blocker | Owner | Exact missing evidence |
| --- | --- | --- |
| Retained-key real acquisition | operator + research owner | `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json` (T6), isolated `HOME` namespace provisioning |
| Cross-engine real acquisition | toolchain owner | `target/pr15d/corpus` (10K/100K), released adapter binaries + Lucene install, JDK/Gradle pin receipt |
| Both families | independent reviewer | G0 `authorization.v1.json` with approval IDs and an independently supplied approval digest |
| Retained-key policy | research owner | authentic T7 micro/F1/policy series |
| Historical parity | research owner | authentic PR15D archive; D3-C numeric replay with an approved mapping and reviewer ID |
| Source QA | CI owner | final-head GitHub runs for `python-contracts`, `rust`, `msrv`, `rustfs`, plus `comparative-full-correctness` |

---

# RF09-F1 fixup addendum (append-only)

Status: **`BM09_RF09_FIXUP_IMPLEMENTED_L1_L2_PASS_REAL_BLOCKED_READY_FOR_REVIEW`**.
The original report above is a historical execution claim; this addendum records
what changed and what is still blocked. Nothing above is retracted.

## Changed trust boundary

- Production work now requires `official.authorization.VerifiedOfficialAuthorization`,
  created only by `open_verified_official_authorization` after an external approval
  record, the canonical authorization bytes and independently observed identities
  all agree. A parsed `OfficialFreeze` cannot authorize anything.
- QA documents must match the G0-pinned `qa_framework_digest`/`qa_source_digest`;
  the embedded per-check digests are no longer self-sufficient.
- Historical parity requires a recomputed, externally approved equivalence mapping
  (`VerifiedHistoricalParity`); caller PASS rows and reviewer labels cannot open
  Gate D. `assess_required_historical_parity` never returns `PASS`.
- Gate A instantiates the pinned original verifier internally and checks its source
  digest before running it; callers cannot inject a verifier.
- The PR15D backend root is exactly `raw_root/backend`, matching Gate A.
- The publisher validates anchors, authorization, manifest, snapshot and the full
  receipt graph before any filesystem mutation.
- Six generated `egg-info` files are no longer tracked.

## Gate status after the fixup

| Gate | Status |
| --- | --- |
| Implementation (G-IMP) | PASS |
| Correctness/adversarial (G-COR) | PASS — 259 official tests, red-first per finding |
| Integration boundary (G-INT) | PASS — forged G0/QA/parity/verifier/anchors cannot produce a receipt or publication |
| Regression (G-REG) | PASS locally: 1,224 Python tests, scripts 108, inventory PASS; `test_pr15d.py` T01 remains PRE_EXISTING_DETERMINISTIC |
| Rust (G-RUST) | PASS — fmt/clippy/tests stable+MSRV, doc, bench compile, 92.03% lines |
| QA chain (G-QA) | PASS — single re-freeze; source digest stable afterwards |
| External CI (G-EXTERNAL) | UNVERIFIED — GitHub API credentials invalid |
| Independent review (G-REVIEW) | PENDING |
| Real G0 / L3-RK / L3-XE / HIST / CLOSEOUT | BLOCKED (unchanged) |

`FINAL_IMPLEMENTATION_SHA` for this fixup is recorded in the commit and in
`review-fixup-evidence.md`; the earlier `7878ebb` block above remains the original
implementation record.

---

# RF09-F2 fixup addendum (append-only)

Status: **`BM09_RF09_F2_IMPLEMENTED_L1_L2_PASS_REAL_BLOCKED_READY_FOR_REVIEW`**.

## What changed

- Production admission now returns a sentinel-guarded `VerifiedOfficialAdmission`
  capability that requires a safe `source_root`, an executed pinned original
  verifier and an unchanged raw inventory; the coordinator re-admits every raw byte
  at Gate A and Gate C refuses a production record without the capability.
- Both G0-pinned QA summaries are now backed by 33 executed check records and 33
  real log files read from an external evidence root, verified three times (before
  QA receipts, after Gate C, before publication).
- Cross-engine historical parity requires the complete 1,440-row PR15D matrix in
  frozen order with deterministic row ids, semantically validated lanes and
  independently recomputed metrics; retained-key parity remains unavailable.
- The duplicated `fixture_only` field on `AdmittedCrossEngine` was removed.

## Gate status

| Gate | Status |
| --- | --- |
| Implementation | PASS |
| Correctness (red-first adversarial) | PASS — 300 official tests |
| Regression | PASS locally — 1,265 Python tests, 108 script tests, inventory PASS; `test_pr15d.py` T01 remains PRE_EXISTING_DETERMINISTIC |
| Rust | PASS — fmt/clippy/tests stable+MSRV, doc, bench compile, 92.04% lines |
| QA chain | PASS — one re-freeze, stable afterwards |
| External CI | UNVERIFIED (`gh` 401) |
| Independent review | PENDING |
| Real G0 / L3 / HIST / closeout | BLOCKED (unchanged) |

## Remaining blockers

| Blocker | Owner | Missing evidence |
| --- | --- | --- |
| Real G0 authorization | operator + reviewer | approval record, approved digest, fresh observations |
| Retained-key L3 | operator | `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json` (T6) and full series |
| Cross-engine L3 | toolchain owner | PR15D corpus and adapter binary set |
| Historical parity | research owner | authentic PR15D archive + approved 1,440-row mapping; D3-C T7/F2 inputs |
| Executed QA artifacts | CI owner | approved external QA evidence root with 33 records + 33 logs |
| Final-head CI | maintainer | GitHub credential to observe the final run |

---

# RF09-F3 addendum (append-only, 2026-11-17)

Status: **`BM09_RF09_F3_IMPLEMENTED_LOCAL_PASS_CI_UNVERIFIED_REAL_BLOCKED`**.

- RF09-11 fixed: production Gate C re-admits through
  `reverify_official_admission`, requires complete recursive equality with the fresh
  record and computes RV-01..RV-10 only from authenticated data. Mode now derives
  from the verified authorization.
- RF09-12 fixed: QA-root tests use `REPO_ROOT`, `REPO_ROOT/benchmarks` and a
  guaranteed-absent path, producing `BM_UNSAFE_INPUT`, `BM_UNSAFE_INPUT` and
  `BM_FILE_MISSING` respectively; no production QA change.
- Local: 313 official tests, 1,278 full Python tests (0 skips), 108 script tests,
  inventory/compileall/console PASS, Rust stable+MSRV+coverage (92.04% lines)+doc+
  bench-compile PASS.
- Final-head hosted CI: **UNVERIFIED** (`gh` 401). Run #394 (previous head) had
  `python-contracts` failing exactly on the removed venv assumption.
- Real G0, D3-C T6, real L3 campaigns, historical parity and closeout remain
  **BLOCKED**; no legacy retirement.

---

# RF09-F4 Addendum A (append-only, 2026-11-17)

Status at authoring: **`BM09_RF09_F4_CONTROL_READY_FOR_LOCAL_ACCEPTANCE_RF09_14_IMPLEMENTED_REAL_BLOCKED`**.

- RF09-13 (parent F4): fixed and local-verified at `5a7b8e6`.
- RF09-14: ExactSet now reserves bounded set/scratch storage at construction, keeps
  its structural charge for the query, rebuilds through preallocated scratch when the
  insertion allowance is exhausted, and preflights the replacement overlap. The
  deterministic per-admission capacity accounting and its two defects were removed.
- Evidence: 12 RF09-14 unit tests, 20 focused `u43` repetitions, the `pr15i_d3_c`
  public-path suites (durable reopen, sentinel boundaries, pagination, batch memory),
  workspace tests/clippy/fmt/doc/bench-compile on both toolchains, 92.08% line
  coverage.
- Performance diagnostic (`RF09-14-query-regression-v1`): see the results recorded
  below in this addendum; if unavailable it is reported as BLOCKED, never as parity.
- Hosted CI: **UNVERIFIED** from this terminal (`gh` returns HTTP 401).
- Real G0, T6, real L3 campaigns, historical parity and closeout remain **BLOCKED**;
  no legacy retirement.

## RF09-F4 Addendum A — performance diagnostic results

Protocol `RF09-14-query-regression-v1` (A = `5a7b8e6`, B = `72ce388`, one host,
Rust 1.98.1, Criterion 0.7 harness, 3 s warm-up / 5 s measurement / 20 samples,
three benchmark IDs, four fixed pairs per phase, 25% coarse guard).

**Default strategy phase — PASS (all four pairs executed).**

| Benchmark | B/A ratios (4 pairs) | Median | Guard ≤ 1.25 |
| --- | --- | --- | --- |
| `pr15b_v1/u07/n10000_s4/k10/sort-n` | 0.9722, 1.0145, 0.9793, 1.0210 | **0.9969** | PASS |
| `pr15b_v1/u07/n10000_s4/k100/sort-n` | 0.9832, 0.9869, 0.9929, 0.9931 | **0.9899** | PASS |
| `pr15b_v1/u07/n10000_s4/k1000/sort-n` | 0.9881, 0.9580, 1.0092, 0.9943 | **0.9912** | PASS |

**ExactSet phase — `PERF_NONREGRESSION_LIMITATION=UNAVAILABLE`.** Both arms failed
the untimed correctness gate, for *different* reasons:

- Arm A (baseline) failed with the known
  `CorruptIndex("exact-set capacity grew after reservation")` — the RF09-14 defect
  this addendum repairs, so the baseline cannot provide valid ExactSet timings.
- Arm B (repair) then failed with `ResourceLimit { limit: 1024, requested: 3750 }`.
  The harness's own validation queries use top-k values above the frozen
  `MAX_EXACT_SET_K = 1024` (observed 100/500/750/**3750**), so forcing
  `QUERVANT_PR15I_D3C_STRATEGY=exact_set` cannot complete with *either* arm.

This is a harness/diagnostic-protocol limitation, not a regression from the repair:
the baseline never reached that validation because it failed earlier. No ExactSet
ratios were computed, and ExactSet nonregression is reported as **UNAVAILABLE** for
reviewer disposition (per the addendum's §8.4 fallback). Changing the harness or the
K limit is outside this addendum's allowlist.

---

# RF09-F4 Addendum B (append-only, 2026-11-17)

Status: **`BM09_RF09_F4B_PARTIAL_RF09_15_FIXED_RF09_18_BLOCKED_REAL_BLOCKED`**.

| Finding | State |
| --- | --- |
| RF09-15 Gate C family guard | **FIXED** and locally verified (red: `AssertionError: BenchError not raised`; green: canonical cross-engine control rejection at `admission`, wrong-family rejection in both orientations, CP-08 four filesystem cases, CP-10 field path + preservation, GC-04 read-only oracle) |
| RF09-18 diagnostic bounded scope | **BLOCKED (scoped HARD STOP)**: the branch was implemented and H01–H06 all passed, but retaining it makes the pre-existing BM-01 frozen-bytes regression fail and the only fix (`test_legacy_inventory.py`) is outside the allowlist. Branch reverted; patch retained externally (sha256 `389559230c…01b3f`). v2 timing not executed. |
| RF09-16 actual old-code red proof | NOT EXECUTED |
| RF09-17 A-U assertion completion | NOT EXECUTED |
| RF09-19 local real RustFS suites | NOT EXECUTED (no runtime probe performed) |
| Hosted CI | UNVERIFIED for this head (`gh` 401); run #396 applies only to `597ea6c` |

Local evidence: 1,299 Python tests (0 skips), 108 script tests, inventory/compileall/
console PASS, Rust gates on both toolchains, 92.08% workspace line coverage, one
controlled synthetic re-freeze. Real G0, T6, L3 campaigns, historical parity and
closeout remain **BLOCKED**; no legacy retirement; not merged.
