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

---

# RF09-F4 Addendum B — erratum `RF09-F4-B-E1` (append-only, 2026-11-17)

Status: **`BM09_RF09_F4B_E1_RF09_15_AND_18_DONE_RF09_16_17_19_NOT_EXECUTED_REAL_BLOCKED`**.

| Finding | State |
| --- | --- |
| RF09-15 Gate C family guard | **DONE** — production fix preserved; numeric-alias contrast and CP-08 protected cleanup completed and verified |
| RF09-18 bounded diagnostic | **DONE** — H01–H06 on the final patched copy, plus v2 default phase PASS (medians 1.0057 / 1.0218 / 1.0054 ≤ 1.25); ExactSet comparison UNAVAILABLE (arm A fails with the repaired defect; four B runs completed) → `PERF_ACCEPTANCE=REVIEW_REQUIRED` |
| RF09-16 actual old-code red proof | NOT EXECUTED |
| RF09-17 A-U assertion completion | NOT EXECUTED |
| RF09-19 local real RustFS suites | NOT EXECUTED (podman available; service not started) |
| Hosted CI | #397 SUCCESS for `25b6669`; this erratum's head requires its own run (unobservable locally: `gh` 401) |

Diagnostic identity: A `5a7b8e65…`, B `2538160…`, patch `389559230c…`, A/B diff
`389559230c…`, patched harness `d02dec431b94db6cf6f6de9fb915f3c19778ca490529a8aca955b73eac0240eb`,
tracked harness unchanged, BM-01 whitelist unchanged. Real G0/T6/L3/historical parity
remain blocked; no legacy retirement; not merged.

---

# RF09-F4 Addendum B — E1 round 2 (append-only, 2026-11-17)

Status: **`BM09_RF09_F4B_E1_R2_RF09_16_19_DONE_RF09_17_NOT_EXECUTED_REAL_BLOCKED`**.

| Finding | State |
| --- | --- |
| RF09-15 | DONE (previous round) |
| RF09-16 | **DONE** — actual old-code proof executed: 40-byte deficit (4828 expected / 4788 actual, scope 4788) and `exact-set capacity grew after reservation` on the second replacement; earlier "42-byte" replica figure corrected |
| RF09-17 | **NOT EXECUTED** — 12-row ledger of missing assertions recorded; no completion claim |
| RF09-18 | DONE (previous round): H01–H06 on the final patched copy; v2 default PASS (1.0057 / 1.0218 / 1.0054 ≤ 1.25); ExactSet comparison UNAVAILABLE with four B runs |
| RF09-19 | **DONE locally** — three real RustFS suites passed under an owned Podman topology, owned resources removed |
| Hosted CI | #397 SUCCESS for `25b6669`; this round's head requires its own run (unobservable locally: `gh` 401) |

Real G0/T6/L3/historical parity remain blocked; no legacy retirement; not merged.

---

# RF09-F4 Addendum B — RF09-17 EXECUTED (append-only, 2026-11-18)

Status: **`BM09_RF09_F4B_RF09_17_DONE_RF09_18_FINAL_RERUN_REAL_BLOCKED`**.

| Finding | State |
| --- | --- |
| RF09-15 | DONE |
| RF09-16 | DONE (actual old-code red proof: 40-byte deficit; `exact-set capacity grew after reservation`) |
| RF09-17 | **DONE** — `finish_construction` seam, `ReserveFault` factory, charged-state reservation guard, and the complete Addendum B §6 matrix: **12 rows / 18 executed tests / 0 failures** (ledger in `review-fixup-evidence.md`) |
| RF09-18 | DONE — final-source v3 re-run: H01–H06 green on the implementation arm, H06 red on the defective base; default phase 8/8 OK with median ratios 1.0209 / 1.0237 / 1.0097 (≤ 1.25); ExactSet comparison still UNAVAILABLE (`PERF_ACCEPTANCE=REVIEW_REQUIRED`) |
| RF09-19 | DONE locally (previous round, three real RustFS suites) |
| Hosted CI | UNVERIFIED for `b94a4d1` (`gh` 401); #397 SUCCESS applies to `25b6669` only |

Verification of the final source: fmt/clippy/doc/bench-compile clean on 1.98.1 and
1.85.0; **2,505 passed / 0 failed** (default) and **2,549 passed / 0 failed**
(all-features) on 1.98.1; 2,505 passed on 1.85.0; Python **1,299 tests / 0 failures**;
line coverage **92.67 %** (floor 85 %).

Implementation checkpoint is now `b94a4d1910ee24929f08f7553dc65816efe8f70c`; arm A of
the diagnostic remains `5a7b8e6533b0aadc885fb13b4d2730646a73df1f`.

Not claimed: real G0 authorization, T6 freeze, L3/historical parity, ExactSet perf
acceptance, legacy retirement, `v0.1-bench` completion, merge.

**RF09-19 on the final head:** the three real RustFS suites were re-executed on
`e61e7dc` under an owned Podman project and all exited 0 with their named real test
(`o01_o02_o03_o09_o10_real_rustfs`, `o04_o05_o06_real_rustfs`,
`m1_v04_real_rustfs_batch_replay_and_generation_consistency`); owned containers,
volumes and the compose network were removed afterwards.

---

# RF09-F4-B-E2 — final verification (append-only, 2026-11-18)

Implementation/test commit: **`4c8817df04248863df00fc20cbabc959e6c0a711`**
(`BM-09 RF09-F4-B-E2: independent ExactSet assertion model and complete evidence`).
Only `crates/quervant-core/src/search/unified.rs` changed; the delta is confined to the
`#[cfg(test)] mod rf09_14_tests` body (verifier prefix/suffix PASS). The measured
benchmark identity remains **`b94a4d1910ee24929f08f7553dc65816efe8f70c`**; the local
RustFS acceptance ran on **`e61e7dc2fd066d9e18d8700c8aba2b2dbaa7b0ff`**. Neither is
relabelled as E2-executed.

| Gate | Command (exact argv in `receipts/commands.jsonl`) | Result |
| --- | --- | --- |
| fmt 1.98.1 / 1.85.0 | `cargo +<tc> fmt --all -- --check` | PASS |
| clippy 1.98.1 (default, all-features) | `--workspace --all-targets [-–all-features] -D warnings` | PASS |
| clippy 1.85.0 (default, all-features) | same | PASS |
| tests 1.98.1 | `--workspace --all-targets` | **2,506 passed, 0 failed**, 13 ignored |
| tests 1.98.1 all-features | `--workspace --all-targets --all-features` | **2,550 passed, 0 failed**, 94 ignored |
| tests 1.85.0 (both) | same pair | **2,506 / 2,550 passed**, 0 failed |
| rustdoc | `doc --workspace --all-features --no-deps` (both toolchains) | PASS |
| bench compile | `bench --workspace --no-run` (both) | PASS |
| coverage | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **92.21 % lines** (62,467 lines, 4,865 missed), region 92.88 %, function 87.84 % |
| focused module | 4 configs × 19 selectors | 19/19 passed each, 0 ignored |
| individual selectors | 19 × `--exact` on 1.98.1/all-features | 19/19, exactly 1 selected per run |
| public integration | 4 configs of `--test pr15i_d3_c` | 22 passed each (real FsDirectory reopen/sentinel, pagination/pinned batch, batch-error/sibling-success) |
| U43 witness | 10 fresh processes per toolchain | 20/20, one selected test each |
| Python | `unittest discover -s quervant_bench/tests` | **1,299 tests, 0 failures** (503 s) |
| scripts | `bash benchmarks/scripts/test-scripts.sh` | **108 passed, 0 failed** |
| legacy protection | `test_legacy_inventory` + `bm-contract-inventory.py --baseline ea9bef6…` | PASS (whitelist/inventory unchanged) |
| `git diff --check` | — | PASS |

Python/QA anchors unchanged (no re-freeze): source set
`sha256:81bcdecc…a734` recomputed from the live 161-file roster; framework QA
`sha256:e3f178dd…aba9`, source QA `sha256:15732a6a…dbd0`, profile
`sha256:9db01390…046c` verified through the byte-identical committed fixture (blob
`ddd97452…` unchanged from the previous green head).

Local real-service (verified reuse under the E2 source-equivalence rule, executed on
`e61e7dc2…`): `pr13_oracle` → `real::o01_o02_o03_o09_o10_real_rustfs`,
`pr13_oracle_geo` → `real::o04_o05_o06_real_rustfs`, `m1_batches` →
`real_rustfs::m1_v04_real_rustfs_batch_replay_and_generation_consistency`, all `ok`
under the pinned `rustfs/rustfs:1.0.1@sha256:1803faef…` image with owned Podman
project `quervant-rf14b-5a24b89a4e16` and completed cleanup (stop/rm/volume-rm exit 0;
post-run 0 containers, 0 rf14b volumes, 0 rf14b networks).

Benchmark status: default-phase paired medians recomputed from the raw 20-sample
Criterion records are **1.0209 / 1.0237 / 1.0097** (≤ 1.25, PASS). The ExactSet phase
remains **UNAVAILABLE**: arm A `5a7b8e6` fails its untimed gate with the documented
`exact-set capacity grew after reservation`, exactly four arm-B observations were
retained and no A/B ratio is computed. `PERF_ACCEPTANCE=REVIEW_REQUIRED`.

Not claimed: final-head hosted CI for this commit (observed externally after the push),
real G0/T6/L3/historical parity, ExactSet comparative performance, legacy retirement,
`v0.1-bench` completion, merge.


## BM-09 operator migration after E2 — final local verification (2026-11-19)

Tested working tree: continuation of
`b7ce3a478af6012c607debea090dfad0b3d2ac17`, with final production/test/package
source identity
`sha256:7d838173bdb05d32136d81c604960cb1be9e905512362365536ebc62f6fdd527`.
Only documentation was appended after the final source freeze and full-suite run.

**Implementation is delivered; the local full-suite gate is not wholly green in
this environment.** The one error is an unchanged test's attempt to create a
Unix socket, rejected by the execution environment with `EPERM`. The test was
also executed individually and produced the same permission error. It was not
weakened, skipped or replaced. The existing authentic-archive absence accounts
for the other, already-declared skip.

| Executed check | Result |
| --- | --- |
| Editable installation: `python -m pip install --no-build-isolation -e ./benchmarks` | PASS; Python 3.12 with the package's pinned direct dependencies |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v` | **1413 tests: 1411 passed, 0 assertion failures, 1 environment error, 1 existing skip; exit 1; 398.423 seconds** |
| New/affected operator, preparation, control, retained policy and source-closure tests | All passed in the final discovery run |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS — 110 passed, 0 failed**; synthetic profiler/criterion records and untimed fixture metadata only |
| `python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS |
| Module and installed-console `inspect --experiment synthetic-contract-smoke --format json` | PASS, byte-equivalent parsed results, existing v1 envelope |
| Installed-console `inspect --experiment cross-engine-keyword-real-v1 --format json` | PASS, new closed v2 envelope, candidate inspection only |
| `python -m pip wheel --no-deps --no-build-isolation --wheel-dir target/migration-wheel ./benchmarks` and wheel-content assertions | PASS; new operator module/schema included, frozen v1 bytes unchanged |
| `git diff --check` and post-freeze source recomputation | PASS |
| Frozen legacy source/protocol/verifier paths and BM-01 schema directory | No diff from the starting head; original byte/inventory guards pass |
| Rust workspace tests/Clippy/coverage | NOT RERUN for this Python-only migration; Rust production, tests, manifests and locks have no diff. Earlier E2 percentages are not claimed as current measurements |
| Actual preparation, adapter smoke, timed benchmarks and real services | NOT EXECUTED, per the explicit migration-only task boundary |
| Final migration-head hosted CI | Not claimed by this local report; inspect the CI attached to the published commit |

Blocked existing test:
`test_evidence_paths.PathValidationTests.test_path_04_fifo_directory_and_socket_are_rejected`.
Failure occurs at `socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)` before
binding the test socket: `PermissionError: [Errno 1] Operation not permitted`.
Existing skip:
`test_official_historical.RetainedKeyArchiveTests.test_o09_his_15_real_archive_root_is_not_modified`
reports no authentic retained-key archive root on this host.

No benchmark timing or performance acceptance was inferred from these tests.
The test topology uses real temporary files/directories and bounded private
worker IPC, logical synthetic acquisition, real math/verification and explicit
adapter/archive boundary doubles. The script suite compiles its original Rust
fixture/profile examples but executes no real profiler or timed benchmark.
Rust 1.98.1 was installed locally to satisfy that script metadata dependency.

Local diagnostic log identities (kept under ignored `target/`, not an execution
archive or an input to qualification):

```text
FULL_PYTHON_LOG=sha256:d66cad4dab03dadf86882cc9fe9206aba9ed1d5fecf8c6076b6c7dc8cf0bfd52
SCRIPT_LOG=sha256:35186eb5c6913d45ecb1e69adbdc6c886c3b5b700f22f47984a3e25a28d75337
SOURCE_SET_DIGEST=sha256:7d838173bdb05d32136d81c604960cb1be9e905512362365536ebc62f6fdd527
REAL_BENCHMARKS_EXECUTED=NO
REAL_ACCEPTANCE=NOT_CLAIMED
LEGACY_RETIREMENT=NO
MERGED=NO
```

The next agent first repeats the full untimed suite on its normal host, resolving
this environment-only socket limitation and supplying authentic archives for the
existing archive check when available. It then follows `docs/BENCHMARK_WORKFLOW.md`
for preparation, executed QA, independent G0/T6 inputs and the real benchmark
series. This migration does not waive any real qualification or closeout gate.

---

# BM09-CONTINUATION-POST-MIGRATION-1 — C-F01/C-F02/C-F03 checkpoint (append-only, 2026-11-18)

Pulled start head `bff24340ed3e8f86ea0df87e3192fa0a5cd608f2` (fast-forward from
`b7ce3a4`), fresh main `a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`, merge base
`a5a8303e…`, clean tree.

| Gate | Result |
| --- | --- |
| Targeted modules (`test_official_qa_evidence`, `test_official_protocols`, `test_official_workflow`) | **72 tests, OK** |
| Qualification anchors (`FixupAnchorTests`, `QaTests`) | **14 tests, OK** |
| Full Python discovery | **1,426 tests, 0 failures, 0 skips** |
| Socket named test | PASS on this host (probe PASS; earlier EPERM not reproducible) |

Red→green counterexamples were recorded before the production edits: the roster,
forge, campaign-order and workflow-contract tests failed on the baseline and pass
after C-F01/C-F02/C-F03, without changing any protected file.

Rust, scripts, inventory, coverage, RustFS and hosted-CI gates for this checkpoint
are recorded in the following section once executed.

---

# BM09-CONTINUATION-POST-MIGRATION-1 — checkpoint C gates and terminal state (append-only, 2026-11-18)

Checkpoint **C** = `b2eb28786ac56597fbeaf347a40a2a17e3c63be5` (pushed, remote verified).
All commands ran in the detached execution worktree `/tmp/bm09-completion/exec` with
its own Python 3.12 venv (`/tmp/bm09-completion/venv`) resolving to that checkout;
receipts in `/tmp/bm09-completion/receipts.jsonl`.

| Gate | Exact command | Result |
| --- | --- | --- |
| Socket named test | `python -m unittest …test_path_04_fifo_directory_and_socket_are_rejected -v` | PASS (probe PASS; WSL host allows AF_UNIX) |
| Full Python | `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | **1,426 tests, 0 failures, 0 skips** (576 s) |
| compileall / inspect (module+console, both official studies) | see receipts | PASS |
| Inventory | `bm-contract-inventory.py --baseline ea9bef6… --check …` | PASS |
| Scripts | `bash benchmarks/scripts/test-scripts.sh` | **108 passed, 0 failed**; perf and heaptrack installed, so the UNAVAILABLE branches were skipped (recorded) |
| fmt / clippy | `+1.98.1` and `+1.85.0`, default + all features | PASS (six commands) |
| Workspace tests | `+1.98.1` and `+1.85.0`, default + all features | **2,506 / 2,550 passed, 0 failed** (13 / 94 ignored) |
| Coverage | `cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **92.21 % lines** (62,467 lines, 4,865 missed), region 92.88 %, function 87.84 % |
| doc / bench compile | `doc --workspace --all-features --no-deps`, `bench --workspace --no-run` | PASS |
| U43 witness | 10 fresh processes per toolchain | 20/20, one selected test each |
| Local RustFS | owned project `quervant-bm09-df9cc1850631`, ports 19000/19001, pinned image, health attempt 1 | `pr13_oracle`, `pr13_oracle_geo`, `m1_batches` **exit 0** with their named real tests; container/volume/network removed |

Hosted CI at C (both events, all four jobs, identity step success in each):

| Run | Event | Head | Tested merge | Jobs |
| --- | --- | --- | --- | --- |
| [#405](https://github.com/yduchesne/quervant/actions/runs/44439788135) | push | `b2eb2878…` | n/a (push) | python-contracts, rust, msrv, rustfs SUCCESS |
| [#406](https://github.com/yduchesne/quervant/actions/runs/44439795612) | pull_request | `b2eb2878…` | `8f8399421c8e3360018d5f140dd67906f4d91282` | python-contracts, rust, msrv, rustfs SUCCESS |

Terminal state of the execution chain (all blockers environmental/external, each
recorded with its own evidence):

| Stage | Outcome |
| --- | --- |
| Cross-engine preparation (S08) | **BLOCKED** — `BM_EVIDENCE_UNAVAILABLE`/`host`: the host observation reports `environment=wsl2`; the official contract rejects WSL for real host observations (D11) |
| Retained preparation (S08) | **BLOCKED** — no authentic T6 `freeze-receipt.json`, `micro.json` or T7-F1 receipt in any recorded location (D24) |
| Source QA (S09) | **BLOCKED** — hosted job logs are HTTP 403 unauthenticated, so authentic per-check logs cannot be sealed; metadata-level run/job identity exists (D20) |
| G0 (S10) | **NOT PREPARED FOR APPROVAL** — no independent reviewer input; a candidate cannot be claimed valid without source QA (D26) |
| Real acquisition (S11/S12) | **NOT EXECUTED** — depends on the two rows above plus a native Linux host |
| Historical parity (S13) | **BLOCKED** — authentic T6/micro/F1 inputs and the corrected PR15D archive `20261031T005545Z-…` are absent; the three retained archives *are* present with their exact expected hashes `e02ff566…`, `721e1f54…`, `72391496…` (D37/D24) |
| comparative-full-correctness | **DEFERRED** — `gh workflow run` returns HTTP 401; CI owner must dispatch it (D21) |
| Publication / closeout (S14/S15) | **NOT SATISFIABLE** — `closeout_status` returns `BLOCKED` with ten missing predicates |

Closeout API result (actual):

```
CLOSEOUT_STATUS=BLOCKED
MISSING=g0_approved_both,host_readiness_and_controls_pass,retained_key_full_series_pass,
        cross_engine_full_series_pass,real_gates_pass,historical_parity_pass,
        attestation_reopen_pass,final_ci_success,independent_review_accepted,
        no_unresolved_findings
DISPOSITION=BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED
```


## 2026-11-19 — Linux/WSL2 compatibility and current-baseline continuation

The maintainer's final direction is current benchmark results as a new baseline, with within-run proportional A/B effects and optional authentic historical relative-effect reporting. The proposed mandatory legacy-versus-new experiment is superseded. Missing history is not a future current-baseline acceptance gate. Native Windows collection is not claimed. The normative contract and executable-agent design are `docs/BENCHMARK_MIGRATION_ACCEPTANCE.md` and `docs/BM09_COMPLETION_PLAN.md`.

Implemented in this change: a reviewed native-Linux/WSL2 union selector; actual environment retained in G0 identity; consistent preparation, live readiness, both acquisition families and persisted cross-engine control checks. Literal-only selectors remain restrictive; mixed environments within one control fail. The retained acquisition caller now loads its own independently pinned retained template and passes it to the shared CPU check. Tests also finish the previously omitted campaign-order singleton negatives, retained opener no-effect assertion and actual QA-validator rejection of the removed operator check IDs. No frozen legacy source, Rust code, historical byte or benchmark sample changed.

Local verification: five affected host/protocol/acquisition/workflow modules PASS, 81 tests. The exact CI discovery command ran 1,441 tests in 403.997 seconds: zero assertion failures, one ERROR from the unchanged AF_UNIX path test (`PermissionError: [Errno 1] Operation not permitted`), and one existing authentic-archive-unavailable skip. This is not a full-suite PASS. An earlier discovery invocation with `-t benchmarks` also produced three flat-import errors; the supported CI command without that option removed those import errors. Compileall, module/installed-console inspection and exact legacy inventory check PASS. Script suite attempted, exit1: cargo/rustc are absent; profile/fixture-metadata tests could not build and the suite stopped before a final count. Rust fmt/clippy/tests/doc/coverage/bench compilation and local real RustFS were not executed here. No benchmark timings were acquired.

One controlled synthetic re-freeze after final source/test edits: source-set `sha256:94d237b9a22aed90b84d903856d2255b87274dc3c7a3e2da7cb4baf0ed2f6dce`; framework QA `sha256:13cee67a064700bf91144d7e210e1d953912e3bcec7e631d999e4b9361decd24`; source QA `sha256:19cae013a73368c58dccacb79d106dd3d25534a738a48b5b7fb693646e32187f`; profile unchanged `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c`. Both fixture chains reopened, source digest stable. These remain synthetic fixtures, not executed real SOURCE_QA.

Current-baseline-v2 acceptance/runtime-freeze/proportional-history/export/replay are DESIGNED, NOT IMPLEMENTED by this host patch. Their detailed continuation has explicit versions, fixed scientific source pins, positive baseline verification without an unsupported optimization-selection claim, automatic committable results and a bounded decision matrix. BM-09 real acceptance remains incomplete pending that work and execution. MERGED=NO. Final hosted CI must be observed for the actual pushed head; no prior-head result is promoted here.

---

# BM09-CURRENT-BASELINE-1 — relative-effects/history slice gates (append-only, 2026-11-19)

| Gate | Result |
| --- | --- |
| New module tests | `test_official_relative_effects` 18/18, `test_official_history` 14/14 |
| Full Python discovery | **1,473 tests, 0 failures, 0 skips** |
| Qualification anchors | 14/14 OK (single controlled refresh) |
| compileall / contract inventory / script tests | PASS / PASS / 108 passed |
| Rust workspace | unchanged; no Rust source was modified by this slice |

Terminal state of this slice: implementation and local QA complete for the
proportional-effect and bounded-history contracts; the v2 execution profile,
runtime freeze, transport/replay and the current benchmark acquisitions remain
unimplemented, so no BM-09 baseline acceptance claim is made.

---

# BM09-CURRENT-BASELINE-1-F1 — fixup gates (append-only, 2026-11-19)

| Gate | Result |
| --- | --- |
| `test_official_relative_effects` | 24 tests OK (literal vectors, canonical storage, intervals, closed row/comparison contracts, retained A/L/P/H oracle, ambiguity rejection) |
| `test_official_history` | 17 tests OK (catalog authority, declared-conflict, unsupported identity, `UNAVAILABLE`, safe reads, disclosure binding) |
| Full Python discovery | **1,482 tests, 0 failures, 0 skips** |
| Qualification anchors | 14/14 OK (single controlled refresh; profile unchanged) |
| compileall / contract inventory / script tests | PASS / PASS / 108 passed |

Source set after the fixup:
`sha256:8d7fa0cc72f3fd396f4cc206bc19627fb469d14bf5659dd76968e49d380fce87`;
framework QA `sha256:f8836e81…058e`; source QA `sha256:474f5cc1…aa30`; profile
`sha256:9db01390…046c` unchanged.
