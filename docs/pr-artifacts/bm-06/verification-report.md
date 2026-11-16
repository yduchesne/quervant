# BM-06 — Verification report

## 1. Provenance

| Field | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/pr-bm06` |
| Main base / start head | `f9125d2c4e95362511f568489de4b06d6236beaf` |
| BM-05 merge ancestor | `f9125d2c4e95362511f568489de4b06d6236beaf` — identical to `origin/main` and merge base (`D01`) |
| Pre-implementation gate | `docs/pr-artifacts/bm-06/design-and-contracts.md`, written before the first production edit |
| Implementation commit | `f31beafd48cac40db3d680332b81ceb8d16cbfeb` |
| Remote head at qualification run | `f31beafd48cac40db3d680332b81ceb8d16cbfeb` (pushed); this evidence-only docs commit follows |
| Python | 3.12.3 (CI is 3.12) |
| Rust | MSRV 1.85.0 and stable 1.98.1 |
| Worktree at final local run | clean after the evidence commit |

Changed files: `benchmarks/quervant_bench/qualification/{__init__,contracts,profiles,
identity,admission,receipts,qa,coordinator,publication,manifest}.py`;
`qualification/profiles/synthetic-framework.v1.json`;
five `tests/test_qualification_*.py`; `tests/fixtures/qualification/*`;
`benchmarks/pyproject.toml` (package-data only); `docs/pr-artifacts/bm-06/*`;
factual pointers in `benchmarks/README.md` and
`docs/benchmarking/BENCHMARKING_ROADMAP.md`.

No public schema, error code, CLI verb, Rust source, workflow, dependency or
historical artifact was changed.

## 2. Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 SOURCE | **PASS** | main/branch/clean baseline verified; allowlist respected; receipt-v1 supports all seven gates (`D07`) |
| G2 IMPLEMENTATION | **PASS** | 15 durable member types, exact A–E graph, production BM-04/BM-05 calls, exclusive publisher, strict loader |
| G3 CORRECTNESS | **PASS** (synthetic) | Q01–Q16 traceability; 93 qualification tests incl. 53 fault-injection points + concurrency |
| G4 REGRESSION | **PASS** | full Python suite (756), BM-01 inventory, script suite (108), all MSRV/stable Rust gates, 92.03% line coverage |
| G5 CI | **UNVERIFIED** | branch pushed; no PR could be created (`gh` token invalid, `D39`); no GitHub workflow run exists for this head |
| G6 REVIEW | pending human | independent review not performed by the coding agent |
| G7 SCOPE | **PASS** | no real acquisition, no historical mutation, no official promotion, no CLI activation |

**Disposition:** `BM06_SYNTHETIC_CORRECTNESS_PASS_CI_UNVERIFIED`.

## 3. Invariant traceability (Q01–Q16)

| ID | Status | Executed evidence |
| --- | --- | --- |
| Q01 synthetic/simulated only | PASS | `test_scope_01…`, `test_scope_02…`, `test_e2e_10…`, `test_contract_05…` |
| Q02 A replays/binds seal+inventory | PASS | `test_a_01…`–`test_a_06…`, `test_e2e_01…`, `test_e2e_04…` |
| Q03 B is the existing BM-04 output, bound | PASS | `test_b_01…`–`test_b_03…`, `test_e2e_03…` |
| Q04 C is the existing BM-05 assessment | PASS | `test_c_01…`–`test_c_03…`, `test_e2e_03…` |
| Q05 receipts legal, exact edges/digests | PASS | `test_rec_01…`–`test_rec_09…` (all seven gates, truth table) |
| Q06 three distinct obligations | PASS | `test_qa_01…`–`test_qa_12…`, `test_e2e_11…` |
| Q07 QA/source independently pinned | PASS | `test_src_01…`–`test_src_03…`, `test_qa_08…`, `test_qa_09…` |
| Q08 reuse only after fresh revalidation | PASS | `test_reuse_01…`–`test_reuse_10…`, `test_e2e_02…` (BM-04/05 poisoned) |
| Q09 exclusive/crash-aware publication | PASS | `test_pub_01…`–`test_pub_09…`, `test_publ_01…`–`test_publ_06…` |
| Q10 acyclic attestation/manifest | PASS | `test_e_01…`–`test_e_06…` |
| Q11 source/QA changes invalidate D/E | PASS | `test_reuse_05…`, `test_reuse_06…`–`test_reuse_09…` |
| Q12 INCONCLUSIVE/baseline-only remain valid | PASS | `test_policy_01…`–`test_policy_04…` |
| Q13 raw evidence unchanged; no redundant work | PASS | `test_e2e_02…`, `test_e2e_12…`, `test_pub_01…` |
| Q14 no real acquisition/CLI/schema change | PASS | `test_bound_01…`, `test_bound_02…` |
| Q15 bounds/closed shapes | PASS | `test_contract_01…`–`test_contract_10…` |
| Q16 full production A→E with faults | PASS | `test_e2e_01…`–`test_e2e_12…`, publication fault series |

Plausible false-PASS mutations exercised: recomputed `receipt_id` with a wrong edge,
cross-run dependency, forged QA self-digest with a new anchor, source-byte mutation
with identical analysis, crash after the hardlink, and an attestation that depends
on the manifest.

## 4. Local command evidence

Run from the repository root with `PYTHONPATH=benchmarks` where applicable.

| Command | Result |
| --- | --- |
| `python3 -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `python3 -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_qualification_*.py' -v` | **PASS — 93 tests**, 0 failures, 0 skips |
| `… -p 'test_analysis_*.py'` | PASS — 190 tests |
| `… -p 'test_verification_*.py'` | PASS — 111 tests |
| `… -p 'test_*.py'` | **PASS — 756 tests**, 0 failures, 1 pre-existing skip |
| `python3 -m quervant_bench inspect --experiment synthetic-contract-smoke --format json` | PASS (`BM_OK`) |
| `python3 benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef6… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2485 passed, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — lines **92.03%** (regions 92.68%, functions 87.72%) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS — compile only, no bench executed |
| `git diff --check` | PASS |

Baseline before implementation: 663 Python tests (0 failures, 1 skip) and
`cargo test --workspace --all-targets` PASS, so the 756/2485/2529 numbers contain no
introduced regression.

Fault-injection topology: real filesystem under a temporary directory on the native
WSL2 Linux filesystem (not `/mnt/c`), using the production `OsPublicationIO`
wrapped by a stateful single-failpoint subclass. 53 injected failure points:
`mkdir` experiment/run (2), exclusive open 1–14 (14), partial write 1–14 (14), file
fsync 1–14 (14), pending open/write/fsync (3), hardlink before/after (2),
directory fsync before/after marker/final (3), unlink pending (1) — plus a
two-writer barrier case with exactly one winner and one
`BM_PUBLICATION_CONFLICT`. Every pre-marker failure leaves no `manifest.json`; the
after-hardlink and after-marker cases retain `manifest.pending` and are rejected by
the loader; the final-fsync failure is content-complete but still raises a typed
non-success.

## 5. Executed synthetic A–E evidence

- Experiment `synthetic-analysis-smoke`; run identity is the sealed run directory's
  UUIDv4.
- Admission counts: 1 control campaign, 2 treatment campaigns, **24 control+
  treatment slots (8 control+16 treatment), 48 lane envelopes, 144 synthetic
  samples**.
- Verification assessment: exactly the nine frozen `VC-01…VC-09` IDs, reference
  `independent-synthetic-v1`.
- Output: exactly the 15 canonical members with `manifest.json` last and no
  `manifest.pending`; the manifest digest is deterministic across reruns.
- Policy decision status is preserved verbatim from the independently verified
  policy document (including `INCONCLUSIVE`/baseline-only) and never rewritten to a
  speed claim.
- `SOURCE_QA_FIXTURE=SIMULATED_ONLY`; `FRAMEWORK_QA_FIXTURE=SIMULATED_ONLY`.

## 6. Failure classification

No mandatory local check failed. `FAILURE_CLASSIFICATIONS=none`.

`RUSTFS_CI`: not run locally (`D40`); the mandatory real-RustFS job remains a
final-PR-head CI gate. `REAL_TIMED_BENCHMARK_ACQUISITION=NOT_RUN`.
`HISTORICAL_PARITY=EVIDENCE_UNAVAILABLE` (no authentic external archive; no legacy
path retired).

## 7. Decision-matrix rules used

| ID | Trigger observed | Action |
| --- | --- | --- |
| D01 | main == origin/main == BM-05 merge ancestor | branched from current main; recorded SHA |
| D05 | `pip` absent locally | used `PYTHONPATH=benchmarks`; installed-console-entrypoint gate deferred to CI |
| D06 | BM-02 publisher is fixed to two admission files | implemented a separate 15-file publisher |
| D07 | receipt.v1 already lists all seven gates | schema unchanged, semantic verifier added |
| D08 | receipt validation does not check logical edges | exact stage graph enforced in `receipts.py` |
| D09 | BM-03 sealed synthetic run replays | used the replayer; sealed tree never edited |
| D11 | BM-04 can legitimately return `INCONCLUSIVE` | preserved; framework qualification proceeds |
| D12 | BM-05 VC registry is exactly nine IDs | pinned and verified |
| D14 | BM-02 trusted spec is fixed to another experiment | BM-02-specific receipt builder not reused |
| D15 | QA digest matched an independently pinned anchor | validated roster/records and issued F/S |
| D18 | no ignored test is part of the required roster | ignored Rust counts documented separately |
| D20 | new BM-06 modules/tests added | staged and included in the frozen source roster |
| D23 | output base under an external safe temporary root | allowed; repo writes restricted to `benchmark-results` |
| D25/D29 | absent destination; concurrent publishers | exclusive `mkdir`; one winner, loser conflicts |
| D26 | committed destination with all anchors matching | loader-verified `REUSED_VERIFIED`, no BM-04/05 rerun |
| D31 | source/QA changed while analysis identical | D/E reuse rejected |
| D33 | publication I/O failure | partial tree preserved, typed error, no cleanup |
| D37 | historical archive absent | `EVIDENCE_UNAVAILABLE`; no retirement |
| D39 | `gh` token invalid | branch pushed; PR not created; CI recorded UNVERIFIED |
| D46 | `manifest.pending` observed | treated as incomplete and rejected |

No HARD STOP condition was triggered; no unauthorised architectural invention was
performed.

## 8. Residual risks and limitations

1. **CI unverified.** No PR exists (`gh` authentication invalid, `D39`), so
   `python-contracts`, `rust`, `msrv` and real-RustFS `rustfs` have not run on this
   head. G5 remains open.
2. **Installed entrypoint unverified locally.** No `pip`; the CI `python-contracts`
   job must confirm the editable install, packaged profile bytes and console
   entrypoint (`D05`).
3. **QA evidence is simulated.** The framework/source QA records are reviewed L2
   assertions of the gate mechanism; they do not demonstrate that any program ran
   or that CI/RustFS passed. BM-09 owns real trust semantics.
4. **Historical parity unavailable.** No authentic D3-C/T7 archive exists locally.
5. **Anchor re-freeze obligation.** `trust-anchors.v1.json` and the QA evidence
   bind the exact committed source roster. Any later change to a covered `.py`,
   workflow, `pyproject.toml`, `test-scripts.sh` or BM-01 schema invalidates the
   anchor and requires an explicit re-freeze; it must not be patched to make a
   failing test green.
6. **Filesystem topology.** Durability assertions were executed on the native WSL2
   Linux filesystem. Platforms without no-follow/link/directory-fsync support fail
   with `BM_NOT_IMPLEMENTED`; no weaker fallback exists.
7. **Python coverage tooling.** No measured Python coverage tool is available; the
   plan's semantic invariant/fault evidence is used instead of an invented
   percentage. The Rust 85% line floor is measured above.
8. **Independent review pending (G6).** No merge was performed.

## 9. Final report fields

```text
REPO=yduchesne/quervant
PR_SCOPE=BM-06-SYNTHETIC-GATES-AND-ATTESTATION
BRANCH=dev/pr-bm06
MAIN_BASE_SHA=f9125d2c4e95362511f568489de4b06d6236beaf
BM05_MERGE_ANCESTOR=f9125d2c4e95362511f568489de4b06d6236beaf VERIFIED
START_HEAD=f9125d2c4e95362511f568489de4b06d6236beaf
FINAL_IMPLEMENTATION_SHA=f31beafd48cac40db3d680332b81ceb8d16cbfeb
FINAL_REMOTE_HEAD=f31beafd48cac40db3d680332b81ceb8d16cbfeb (evidence docs commit follows)
WORKTREE=clean
PRE_IMPLEMENTATION_CORRECTNESS_GATE=PASS
INVARIANTS_Q01_TO_Q16=all PASS (see §3)
SIMULATED_A_TO_E=published; 15 files; manifest last; exact receipt graph
SOURCE_QA_FIXTURE=SIMULATED_ONLY
FRAMEWORK_QA_FIXTURE=SIMULATED_ONLY
REUSE_AND_INVALIDATION=REUSE-01..10 PASS
PUBLICATION_FAILPOINTS=53 injected points + concurrency PASS
PYTHON_TARGETED=93 qualification / 190 analysis / 111 verification PASS
PYTHON_FULL=756 tests, 0 failures, 1 pre-existing skip
RUST_MSRV=fmt/clippy/test(all features 2529) PASS
RUST_STABLE=fmt/clippy(default+all)/test(2485,2529) PASS
RUST_COVERAGE=lines 92.03% (>= 85)
RUSTFS_CI=UNVERIFIED (no PR run)
BENCH_COMPILE_ONLY=PASS
REAL_TIMED_BENCHMARK_ACQUISITION=NOT_RUN
HISTORICAL_PARITY=EVIDENCE_UNAVAILABLE
GITHUB_CI_PYTHON/RUST/MSRV/RUSTFS=UNVERIFIED (no workflow run for this head)
FAILURE_CLASSIFICATIONS=none
DECISION_MATRIX_RULES_USED=D01,D05,D06,D07,D08,D09,D11,D12,D14,D15,D18,D20,D23,D25,D26,D29,D31,D33,D37,D39,D46
DEFERRED_DECISIONS=D05 (installed entrypoint -> CI), D39 (PR/CI -> CI owner)
HARD_STOP_CONDITIONS=none
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS (synthetic)
FINAL_CI_GATE=UNVERIFIED
DISPOSITION=BM06_SYNTHETIC_CORRECTNESS_PASS_CI_UNVERIFIED
PR_URL=NOT_CREATED (branch pushed: https://github.com/yduchesne/quervant/pull/new/dev/pr-bm06)
MERGED=NO
```
