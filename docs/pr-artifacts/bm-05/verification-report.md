# BM-05 — Verification report

## 1. Provenance

| Field | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/bm05-independent-verification` |
| Main base / actual start head | `66ce06ab725ee1efed799ca8cfacb4d4934d616f` |
| BM-04 merged ancestor | `06373a5f64ea2162f28224d4b9dbea169274e34c` — `git merge-base --is-ancestor` PASS |
| Implementation commit | `c007ae1b70ad990b6586895125f4599f3e7a438d` |
| Remote branch | pushed to `origin/dev/bm05-independent-verification` |
| Python | 3.12.3 |
| Rust | MSRV 1.85.0 and stable 1.98.1 |
| Worktree at final local run | clean |

Changed files: `benchmarks/quervant_bench/verification/{__init__,contracts,reference_input,reference_math,reference_bootstrap,reference_policy,verify}.py`;
seven `tests/test_verification_*.py`; `tests/fixtures/verification/reference-vectors.v1.json`;
`docs/pr-artifacts/bm-05/*`; short factual pointers in `benchmarks/README.md`
and `docs/benchmarking/BENCHMARKING_ROADMAP.md`.

## 2. Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| Pre-implementation correctness gate | **PASS** | `design-and-contracts.md` invariant matrix, dependency allowlist and counterexamples frozen before the first production edit |
| A — Implementation | **PASS** | exact modules/API; no forbidden imports/calls; no write path; AST audit + runtime poison probe |
| B — Correctness | **PASS** | every V01–V11 row has executed positive and adversarial evidence (see §3) |
| C — Local regression | **PASS** | commands and counts in §4 |
| D — Remote CI | **UNVERIFIED** | branch pushed; no PR/CI because the available GitHub token is invalid (D23) |
| E — Historical status | **EVIDENCE_UNAVAILABLE**, not `PASS` | empty `target/pr15i-d3-c`; no fabricated parity, no retirement |
| F — Review/merge | pending human | not merged |

## 3. Correctness evidence

* Invariants V01–V11: each has at least one positive and one adversarial test
  (`design-and-contracts.md` §5).
* Oracle independence: AST audit rejects forbidden primary imports/calls; the
  runtime poison probe replaces primary `_select`, `evaluate_policy`,
  `bootstrap_interval`, estimator/median/pruning and `analyze_synthetic_run`
  functions with raising stubs and the verifier still returns
  `verified-synthetic`.
* Structurally valid false PASS: forged 12dp statistics, CI endpoint, GM,
  ranking/selection and coherent resource decision all pass the BM-04 closed
  output validators and are then rejected by independent recomputation
  (`test_v_ind_05..08`, `test_v_mut_09..15`).
* Reference bootstrap: published seed-42 key/index golden, prescribed
  seed-7 four-block vector (key, first 16 indexes, first 12 replicate medians,
  `(2,97)` bounds, CI `[0.750000000000, 1.100000000000]`, 400 accepted draws),
  modulo-bound rejection, percentile `(24,974)`/`(249,9749)`, counter-exhaustion
  rejection.
* Policy matrix: strict `lt` vs inclusive `le`, point/resource boundaries,
  MISSING/OVER reasons retained together, filter sensitivity, GM ranking,
  exact/relative tie, top-two preference restriction, all-ineligible baseline
  fallback, no-eligible inconclusive result.
* Vertical slices: checked-in baseline-first fixture, non-first baseline,
  three-arm GM reversal, short profile literals, multi-candidate tie, and both
  authorized estimators (fully rebound isolated catalog). Every slice derives
  proposed documents with BM-04 **in test setup only** and verifies them with the
  independent oracle.
* Insufficient-retained-block positive sealed slice is **not constructible**:
  the frozen BM-03 synthetic adapter replays one sample vector per arm/lane for
  every slot, so within-arm spread is always exactly `1` and no block is ever
  excluded. The arithmetic is covered by `test_v_prune_03` and forged-document
  rejection; this limitation is recorded honestly (D39) and changes no semantics.

## 4. Executed commands (final implementation SHA)

| Command | Result |
| --- | --- |
| `python3 -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_verification_*.py'` | **92 passed**, 0 failed, 0 skipped |
| `PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_analysis_*.py'` | **181 passed**, 0 failed |
| `PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | **635 passed**, 0 failed, 1 pre-existing skip |
| `PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json` | PASS |
| direct `cli.main(['inspect', ...])` vs `python -m quervant_bench` stdout | byte-identical |
| `python -m quervant_bench run …` | exit **77** (`BM_ACQUISITION_PROHIBITED`), no output directory created |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | **108 passed**, 0 failed |
| `cargo +1.85.0 fmt --all -- --check` / `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets [--all-features] -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | 2485 passed, 0 failed, 13 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 2529 passed, 0 failed, 94 ignored |
| `cargo test --workspace --all-targets` | 2485 passed, 0 failed, 13 ignored |
| `cargo test --workspace --all-targets --all-features` | 2529 passed, 0 failed, 94 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS — 92.03% lines** (functions 87.72%, regions 92.69%) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| `git diff --check` | PASS |

Not executed: `python -m pip install -e ./benchmarks` — **no `pip` module in this
environment**. The console script could therefore not be installed; the console
entry-point target (`quervant_bench.cli:main`) was compared directly and is
byte-identical to the module entry point.

No real timed benchmark, Criterion run, profile, pilot, A/A or performance
conclusion was executed. `REAL_TIMED_BENCHMARK_ACQUISITION=NOT_RUN`.

## 5. Historical evidence

```text
STATUS=EVIDENCE_UNAVAILABLE
HISTORICAL_SERIES_VERIFIED=NO
NUMERIC_PARITY=NOT_EXECUTED
POLICY_VERDICT_PARITY=NOT_EXECUTED
REASON=required authentic external archive not present (directory empty)
OWNER=BM-07/BM-09; no historical path retired
```

The checked-in original verifier `benchmarks/pr15i_d3_c/verify.py` (SHA-256
`54e91d99…`) exists and was inventoried, but was not executed because there is
no authentic archive to check. No historical bytes, verdicts or scripts changed.

## 6. Remote CI

Branch push succeeded. PR creation failed with `HTTP 401: Bad credentials`; the
configured `gh` token is invalid. No PR exists, so `python-contracts`, `rust`,
`msrv` and real-service `rustfs` checks are **UNVERIFIED** at this head. Local
RustFS service is unavailable (D22), so the real-service gate cannot be
substituted locally.

## 7. Failure classification

| Item | Class | Evidence |
| --- | --- | --- |
| `pip` unavailable | 5 — environment/harness | `/usr/bin/python3: No module named pip`; module and direct entry-point commands used instead |
| GitHub token invalid | 5 — environment/harness | `gh auth status`: invalid token; `gh pr create`: HTTP 401 |
| Local RustFS absent | 5 — environment/harness | no local S3-compatible service; real-service gate deferred to CI (D22) |
| Historical archive empty | not a failure of BM-05 | `inspect_archive` → `EVIDENCE_UNAVAILABLE` (D24) |
| Insufficient-slice non-constructibility | test-construction limitation | frozen one-vector-per-arm/lane scenario contract; no semantic change (D39) |

No introduced regression, feature defect, deterministic pre-existing failure or
flaky failure was observed locally.

## 8. Decision matrix rules used

D03 (branch created), D05 (Python 3.12), D07/D08 (frozen BM-03/BM-04 interfaces
reused as specified), D22 (local RustFS absent, CI owns it), D23 (GitHub token
invalid; finish/push, CI unverified), D24 (archive unavailable, no retirement),
D39 (unlisted test-construction limitation, unaffected work continued).

**Hard stops: none.**

## 9. Residual risks

| Risk | Impact | Disposition |
| --- | --- | --- |
| Remote Rust/Python/RustFS CI not inspected at this head | Acceptance gate D remains open | Re-run all four jobs after PR creation with valid credentials |
| Independent oracle mirrors the frozen written formulas | A shared misinterpretation could agree on both sides | Hand-authored literal vectors, estimator-divergence case and poison probe; reviewer must audit oracle-mapping |
| Insufficient-retained positive sealed slice absent | Narrower end-to-end evidence for one branch | Covered by reference-math and forged-document rejection; documented limitation |
| Historical parity not executed | No legacy retirement possible | BM-07/BM-09 own it; authentic archive required |

## 10. Disposition

```text
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS
LOCAL_QA_GATE=PASS
FINAL_CI_GATE=UNVERIFIED
DISPOSITION=BM05_IMPLEMENTED_CI_UNVERIFIED
PR_URL=NOT_CREATED
MERGED=NO
```

---

# RF05 review fixup — preimplementation correctness gate

Reviewed start head: `a5a1261f4abf74ea3b37bf062cd5bbbde4947518`.
Branch: `dev/bm05-independent-verification`. Merge-base with `origin/main`:
`66ce06ab725ee1efed799ca8cfacb4d4934d616f`. Worktree clean at start; remote
branch head equalled the reviewed head. `06373a5f64ea2162f28224d4b9dbea169274e34c`
remains an ancestor.

Confirmed before any source edit:

| Finding | Location | Observed |
| --- | --- | --- |
| RF05-01 primary | `analysis/policy.py::_filter_sensitive_lanes` | `_sign(a_raw - b_raw)` / `_sign(a_ret - b_ret)` compares pair differences to 1 |
| RF05-01 reference | `verification/reference_math.py::sign_of`, `verification/reference_policy.py::_filter_sensitive` | pair differences also compared to 1 through `sign_of` |
| RF05-02 | `verification/reference_math.py::format_12`, `reference_policy._lane_result` | policy limits pass through strict-positive `require_decimal`; zero bounds would be rejected |
| Wrong golden | `tests/test_verification_reference_policy.py::test_v_pol_08…` | stable `alpha > beta` order was incorrectly expected to be filter-sensitive |

Frozen FX05 invariants for this fixup:

| ID | Property |
| --- | --- |
| FX05-01 | individual parity compares an effect with 1 (unchanged) |
| FX05-02 | candidate order compares two effects relative to each other (0), never 1 |
| FX05-03 | any order/tie change flags every candidate in that campaign/lane |
| FX05-04 | stable order with changing distance is not sensitive |
| FX05-05 | missing effects never become zero or equality |
| FX05-06 | an otherwise eligible two-candidate case with an order flip is fully INCONCLUSIVE with null selection |
| FX05-07 | poisoned primary filter output is rejected by the independent reference |
| FX05-08 | zero policy point/CI limits render exactly `0.000000000000` |
| FX05-09 | zero remains invalid for samples, denominators and generic effects |
| FX05-10 | fully bound sealed synthetic zero-threshold catalogs derive and verify |
| FX05-11 | no BM-03/historical mutation, no acquisition, verifier stays read-only |
| FX05-12 | final-head GitHub CI is authoritative; old results are not reused |

Planned red evidence: `F05-POL-01`/`F05-REF-01` must fail on reviewed source with
the bad decision; corrected `V-POL-08` must fail before the change; the zero
policy-limit tests must fail because `format_12` rejects zero while BM-04 derives
a valid document. No production edit is made until those reds are recorded.

## RF05 fixup — adversarial red-test evidence (before production edit)

Source unchanged at `a5a1261f4abf74ea3b37bf062cd5bbbde4947518`. Added tests
first; observed on the reviewed source:

| Suite | Result | Predicted defect evidence |
| --- | --- | --- |
| `test_analysis_policy.FilterSensitivityOrderTests` | 6 failed, 3 passed | `F05-POL-01` true flip not flagged; `F05-POL-02` stable order falsely flagged; tie create/remove not flagged; full policy stays `ELIGIBLE`; 3-arm flip not lane-wide |
| `test_verification_reference_policy.ReferenceFilterSensitivityTests` | 6 failed, 1 error, 3 passed | same false negative/positive in the reference; `F05-REF-08` zero limits raise `BM_SCHEMA_INVALID: value must be positive` |
| corrected `V-POL-08` stable-order expectation | failed | old comparator flags `(alpha, beta)` although alpha remains above beta |
| `test_verification_reference_math.CandidateOrderAndPolicyLimitTests` | 4 errors | `compare_candidate_order` and `format_policy_limit_12` do not exist yet; generic `format_12` still rejects zero |
| `test_verification_vertical_slice.ZeroThresholdVerticalSliceTests` | 2 errors | BM-04 zero-profile derivation succeeds; BM-05 rejects at `format_12(point_limit)` |
| `test_verification_independence.PolicyFilterIndependenceTests` | 1 failed | reference returned no reasons while the poisoned/false primary stayed selectable |

No expected literal was changed to fit the old implementation, and no production
file was edited before this record.

## RF05 fixup — final implementation evidence

| Field | Value |
| --- | --- |
| Reviewed start head | `a5a1261f4abf74ea3b37bf062cd5bbbde4947518` |
| Fixup implementation SHA | `c20cb0a551fcdb4b8df9c234105a6c31caec9b48` |
| Branch | `dev/bm05-independent-verification` (existing PR #106; no new PR) |
| Worktree before commit | clean after commit; only §3 allowlisted paths changed |
| Python | 3.12.3 |
| Rust | MSRV 1.85.0, stable 1.98.1 |

### Implemented corrections

* `analysis/policy.py`: added private `_relative_order(first, second)` and changed
  only the pairwise condition in `_filter_sensitive_lanes` from `_sign(a-b)` to
  `_relative_order(a, b)`. `_sign` parity semantics are unchanged.
* `verification/reference_math.py`: `sign_of` remains parity-only with a corrected
  docstring; added independently coded `compare_candidate_order`; added
  `format_policy_limit_12` for finite nonnegative policy bounds. Generic
  `format_12`/`quantize_12`/`require_decimal` remain strict-positive.
* `verification/reference_policy.py`: uses the independent comparator for pair
  order and the nonnegative formatter only for `point_limit`/`ci_limit`.
* No BM-03, BM-04 arithmetic/bootstrap/pruning/serialization, Rust, schema,
  dependency, CLI, receipt, historical or workflow file was changed.

### Fixup invariant status

`FX05-01 PASS` (parity unchanged), `FX05-02 PASS` (relative order),
`FX05-03 PASS` (lane-wide marking), `FX05-04 PASS` (stable order),
`FX05-05 PASS` (missing skipped), `FX05-06 PASS` (full-policy inconclusive/null),
`FX05-07 PASS` (poisoned primary rejected), `FX05-08 PASS` (zero limit rendering),
`FX05-09 PASS` (zero still invalid for samples/effects), `FX05-10 PASS` (two
sealed zero-threshold slices), `FX05-11 PASS` (no mutation/acquisition; read-only),
`FX05-12 UNVERIFIED` (GitHub CI unavailable with the configured credentials).

### Executed commands at `c20cb0a`

| Command | Result |
| --- | --- |
| `python3 -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `test_analysis_*.py` | **190 passed**, 0 failed |
| `test_verification_*.py` | **111 passed**, 0 failed, 0 skipped |
| full `test_*.py` | **663 passed**, 0 failed, 1 pre-existing skip |
| `F05-POL-01..09`, `F05-REF-01..10`, `F05-IND-01`, `F05-NUM-01..05`, `F05-VERT-01/02` | PASS (literal oracles) |
| corrected `V-POL-08` stable-order case | PASS (no sensitivity) |
| module vs direct `cli.main` inspect stdout | byte-identical |
| `quervant-bench run` denial | exit **77**, no output directory created |
| `bm-contract-inventory.py --check …` | PASS |
| `test-scripts.sh` | **108 passed**, 0 failed |
| MSRV/stable fmt + clippy (default/all-features) | PASS |
| MSRV tests (`--all-targets`) | 2485 passed, 0 failed, 13 ignored |
| MSRV tests (`--all-targets --all-features`) | 2529 passed, 0 failed, 94 ignored |
| stable tests (`--all-targets`) | 2485 passed, 0 failed, 13 ignored |
| stable tests (`--all-targets --all-features`) | 2529 passed, 0 failed, 94 ignored |
| `cargo llvm-cov … --fail-under-lines 85` | **92.03% lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only) |
| `git diff --check` | PASS |

`REAL_TIMED_BENCHMARK_ACQUISITION=NOT_RUN`; no Criterion/Criterion timing,
profiling, pilot or A/A was run.

### Historical evidence

`HISTORICAL_ARCHIVE=EVIDENCE_UNAVAILABLE` (empty `target/pr15i-d3-c`).
Original historical verifier exists but was not executed; numeric and decision
parity remain `NOT_EXECUTED`; no legacy path retired.

### Remote CI

Branch pushed; remote head `c20cb0a551fcdb4b8df9c234105a6c31caec9b48` matched the
local implementation SHA at observation time. `gh` still reports
`HTTP 401: Bad credentials`, so no PR check results could be read and no PR was
created by this agent (PR #106 already exists). Final-head `python-contracts`,
`rust`, `msrv` and `rustfs` are **UNVERIFIED**. The previously documented `u43`
flake was not observed locally (all MSRV/stable local runs passed); it remains a
CI-owned risk and is not waived.

### Failure classification and decisions

| Item | Class | Disposition |
| --- | --- | --- |
| `pip` unavailable | 5 environment/harness | module/direct entry-point checks used; installed console script not claimed |
| `gh` token invalid | 5 environment/harness | branch pushed, CI unverified (D29) |
| local RustFS absent | 5 environment/harness | CI owns real-service gate (D27) |
| authentic archive empty | not a BM-05 failure | `EVIDENCE_UNAVAILABLE` (D28) |
| BM-03 cannot produce a sealed pruning reversal | test-construction limitation | policy-only independent fixtures + poison probe (D15) |

Rules used: `D01`, `D05`–`D12`, `D15`–`D20`, `D22`, `D24`, `D25`, `D26`–`D30`,
`D33`, `D36`, `D40`, `D43`. **No hard stop was triggered.** No expected literal
was adjusted to match the implementation.

### Gates and disposition

```text
IMPLEMENTATION_GATE=PASS
CORRECTNESS_GATE=PASS
LOCAL_QA_GATE=PASS
FINAL_CI_GATE=UNVERIFIED
HISTORICAL_PARITY=EVIDENCE_UNAVAILABLE
DISPOSITION=BM05_RF05_FIXUP_IMPLEMENTED_CI_UNVERIFIED
PR_URL=https://github.com/yduchesne/quervant/pull/106
MERGED=NO
```

Residual risks: final-head CI not observed; the BM-04 primary semantic fix is
inside a merged component but is the explicitly authorized one-line predicate
correction; independent reviewer must confirm the fixup delta and the u43 CI
classification.
