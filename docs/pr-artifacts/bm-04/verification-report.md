# BM-04 — Verification report

Scope: BM-04 primary statistical analysis and frozen policy engine.
Disposition at the time of writing: **BM04_IMPLEMENTED_CI_UNVERIFIED** — every
local gate that can run here passes, one mandatory MSRV test target is
nondeterministically red in a pre-existing `quervant-core` test, and remote CI has
not been observed.

## 1. Identities

| Field | Value |
| --- | --- |
| Base `main` (`origin/main` = `main`) | `b085d7bf83d67c99ec510952042cc57c49fcee4a` (Merge PR #104, BM-03) |
| BM-03 fixup ancestor check | `0909dd5401d80460a92727cdf538197de4fe84be` is an ancestor of both `main` and `origin/main` |
| Branch | `dev/bm04-analysis-policy` |
| Toolchain (Python) | 3.12.3 |
| Toolchain (Rust stable) | 1.98.1 |
| Toolchain (Rust MSRV) | 1.85.0 |

No assumed merge SHA was hard-coded; the base was resolved with `git rev-parse`.

## 2. Change allowlist

New:

```text
benchmarks/quervant_bench/analysis/{__init__,contracts,profiles,arithmetic,pruning,
    bootstrap,aggregation,policy,derive,history}.py
benchmarks/experiments/synthetic-analysis-smoke/{experiment,protocol,workloads,adapter}.yaml
benchmarks/experiments/synthetic-analysis-smoke/{analysis-profile,policy-profile,
    resource-observations,synthetic-scenario}.v1.json
benchmarks/quervant_bench/tests/analysis_support.py
benchmarks/quervant_bench/tests/test_analysis_{arithmetic,pruning,bootstrap,contracts,
    policy,vertical_slice,history}.py
benchmarks/quervant_bench/tests/fixtures/analysis/{bootstrap-index-golden.v1.json,
    bootstrap-index-reference.py}
docs/pr-artifacts/bm-04/{README,design-and-contracts,mathematical-oracles,policy-matrix,
    historical-parity,verification-report}.md
```

Modified:

```text
benchmarks/README.md                       (one BM-04 pointer paragraph)
docs/benchmarking/BENCHMARKING_ROADMAP.md  (one factual BM-04 implementation-status note)
```

Unchanged (verified by `git diff --stat`):

```text
BM01_V1_SCHEMAS_MODIFIED=0
BM02_SHARED_FILES_MODIFIED=0
BM03_EXECUTION_PROTOCOL_SOURCE_MODIFIED=0
HISTORICAL_TRACKED_FILES_MODIFIED=0
RUST_SOURCE_MODIFIED=0        (git diff --stat b085d7b -- crates/ Cargo.toml Cargo.lock .github/ = empty)
REAL_TIMED_BENCHMARK_ACQUISITION=NOT_RUN
```

## 3. Local gate results

### 3.1 Python (`python-contracts` equivalent, Python 3.12.3)

| Command | Result |
| --- | --- |
| `python -m pip install -e ./benchmarks` | PASS |
| `python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_analysis_*.py'` | PASS — **142 tests**, 0 failures |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | PASS — **504 tests**, 0 failures |
| `PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json` | PASS (rc 0) |
| `quervant-bench inspect --experiment synthetic-contract-smoke --format json` | PASS (rc 0) |
| module vs console stdout byte comparison (`cmp`) | PASS — **byte-identical**, 563 bytes |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS (rc 0) |
| `quervant-bench run` exit status | PASS — **77** (`BM_ACQUISITION_PROHIBITED`), no side effects |

Baseline inventory: the merged BM-03 base carries **362** Python tests; BM-04 adds
**142** (362 + 142 = 504). Test counts are measured, not assumed.

Python line coverage of the new package (informational; the 85% floor is a Rust
gate):

```text
TOTAL  2041 statements  210 missed  90%
```

### 3.2 Rust — required commands (§18)

| Command | Result |
| --- | --- |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | **FLAKY** — see §4 (clean on retry) |
| `cargo +1.85.0 test --workspace --all-targets` (default features) | PASS — 138 test targets OK |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 0 failures (1003 lib tests + integration targets) |
| `cargo test --workspace --all-targets --all-features` | PASS — 138 test targets OK, 0 failures |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.70% lines** (87.72% functions, 92.04% regions) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only; **no timing executed**) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script assertions |
| `git diff --check` | PASS |

`cargo bench` was **never** invoked without `--no-run`. No Criterion run, profiler,
live A/A, pilot measurement or timed acquisition was performed.

### 3.3 Required CI

| Job | Result |
| --- | --- |
| `python-contracts` | UNVERIFIED (local equivalent PASS) |
| `rust` | UNVERIFIED (local equivalent PASS) |
| `msrv` | UNVERIFIED (local equivalent flaky — §4) |
| `rustfs` | UNVERIFIED — local topology absent; the real RustFS container is CI-owned |

No CI result is claimed. Acceptance remains open until all four jobs pass at the
final PR HEAD.

## 4. Unresolved failure — `u43_replacement_witness_all_variants`

| Field | Value |
| --- | --- |
| Test | `search::unified::d3c_tests::u43_replacement_witness_all_variants` |
| Location | `crates/quervant-core/src/search/unified.rs:6371` |
| Panic | `ExactSet K{K} round {R}: Err(CorruptIndex { detail: "exact-set capacity grew after reservation" })` |
| Classification (§18.2) | **(4) nondeterministic issue demonstrated by repeated identical executions**, reproduced on the unmodified base |
| Owner | `quervant-core` (separate investigation); **not** BM-04 |

Evidence (logs preserved under `/tmp/bm04qa/` during the run):

| Environment | Command | Runs | Failures |
| --- | --- | --- | --- |
| BM-04 branch, `target/` | `cargo +1.85.0 test --workspace --all-targets --all-features` | 8 | 4 |
| BM-04 branch, `target/` | `cargo +1.85.0 test -p quervant-core --lib --all-features d3c_tests` | 8 | 1 |
| BM-04 branch, `target/` | the single test in isolation (`--exact`) | 3 | 0 |
| Base `b085d7b` worktree, shared `target/` | `cargo +1.85.0 test -p quervant-core --lib --all-features d3c_tests` | 20 | 3 |
| Base `b085d7b` worktree, own `target/` | `cargo +1.85.0 test --workspace --all-targets --all-features` | 3 | 0 |
| Base `b085d7b` worktree, shared `target/` | `cargo +1.85.0 test --workspace --all-targets --all-features` | 7 | 0 |

The identical panic (same file, same line, same message) is produced by the
**unmodified base source**, so this is not introduced by BM-04. The observed `K`
varies between `K100` and `K1024`, consistent with a hash-seed/allocation-dependent
capacity estimate in the exact-set accounting.

Actions taken: logs captured for both states; no test was skipped, filtered,
`#[ignore]`d, retried-until-green without disclosure, or edited, and no Rust source
was modified (D63). Per §18 a failing mandatory CI job blocks acceptance whether or
not the failure is known.

## 5. Simulated feature gate (§18.1)

Full BM-03 → BM-04 vertical slice executed in a fresh external temporary root
against the final implementation:

```text
sealed_status               sealed
replay_status               verified-synthetic-structure
controls / treatments       1 / 2
slots                       24
lane envelopes              48
synthetic samples           144
run_dir file count          89 (unchanged before and after derivation)
seal raw sha256             sha256:db682f9ce0bfcc0fd853c3c14389ba07f4741a53ce7138dd59a716dd2c5d54c8
analysis profile digest     sha256:1f8b4ae6fb7a2f1c632c235d096ed853151fb964e7db0c211766f753652a6af1
policy profile digest       sha256:d1e2c0b681ba90ea0f13e16acf9cd7bd5ff5f27b7445da04d4f72b034dab0e90
resource digest             sha256:fb019b242fbd93cf474c208f724d3618a296d8898ccd0c102ab5729d2d07d53d
second derivation identical  true (byte-identical canonical bytes)
selected_arm_id             candidate
decision_status             SELECTED_ELIGIBLE_SYNTHETIC
worst_campaign_gm           0.816496580928
missing-seal rejection      BM_EVIDENCE_UNAVAILABLE
```

Per-campaign/lane arithmetic observed (both treatment campaigns):

```text
rare-query    raw 0.800000000000  retained 0.800000000000  CI [0.800000000000, 0.800000000000]  4/4 blocks retained
common-query  raw 0.833333333333  retained 0.833333333333  CI [0.833333333333, 0.833333333333]  4/4 blocks retained
```

No artifact was written into the sealed run; the returned documents were not
persisted (BM-06 owns publication).

## 6. Independent goldens

| Golden | Result |
| --- | --- |
| §19 domain key `e721deea…a12a8` | PASS — matches the checked-in literal |
| §19 first 16 indices `[0,2,0,2,1,2,1,0,0,0,0,1,0,2,2,0]` | PASS |
| Standalone reference reproducer (`bootstrap-index-reference.py`, no `quervant_bench` import) | PASS — identical output |
| Percentile indexes `(24, 974)` for R=1000, `(249, 9749)` for R=10000 | PASS |
| Estimator distinction `1.000000000000` vs `2.500000000000` | PASS |
| Exclusion cap equality retained / one step over excluded | PASS |
| Strict `lt` CI bound equality unproven | PASS |
| Resource equality eligible / +1 byte ineligible / missing inconclusive | PASS |
| Tie at `0.0222…`, non-tie at exactly `0.030000000000` | PASS |

## 7. Decision-matrix rules used

| ID | Trigger | Action taken |
| --- | --- | --- |
| D01 | `origin/main` contains the BM-03 fixup and full `protocol/` + `execution/` tests | Recorded base `b085d7b`, branched from verified `main` |
| D03 | `dev/bm04-analysis-policy` absent, tree clean | Created the exactly named branch from `main` |
| D06 | BM-01/02/03 APIs as inspected | Reused by import; no second parser/replayer/adapter |
| D09 | BM-03 fixture carries placeholder bindings | Created the distinct `synthetic-analysis-smoke` experiment |
| D14 | Ambient decimal context must not leak | `localcontext(Context(prec=50, ROUND_HALF_EVEN))` everywhere |
| D22/D23 | Spread equal to / over the cap | Equality retained; over ⇒ whole-pair exclusion |
| D25 | Retained blocks below `max(minimum, 2)` | Valid inconclusive, null retained effect/CI, raw preserved |
| D27/D29 | New bootstrap profile | SHA-256 rejection stream + nearest-rank indexes 24/974 |
| D36/D37 | CI equality at `lt` / `le` bounds | Unproven / pass respectively |
| D40/D41/D42 | Resource at / over / absent | Eligible / ineligible / inconclusive |
| D45/D46/D47/D49/D50 | Election precedence and tie boundaries | Implemented exactly, including "exactly 3% is not a tie" |
| D52 | Structural replayer rejects | Typed fail-closed before any arithmetic |
| D53 | Input changed during derivation | Typed failure, no outputs, no writes |
| D54 | Authentic D3-C archive absent | `EVIDENCE_UNAVAILABLE` record; synthetic L1/L2 completed |
| D58/D59 | Host idle | Synthetic/offline work only; **no** live timing |
| D63 | Known intermittent `u43` | Logs captured, reproduced on base, CI still required, no skip |
| D71 | Temporary generated outputs | Only BM-04-owned temporary roots and build caches removed |
| D74 | Uncovered decision | None encountered |

Deferred: D54 (BM-07/BM-09), D57 (BM-05/07), D63/D64 (quervant-core owner),
D66 (PR creation / CI observation).

## 8. Residual risks

| Risk | Severity | Owner |
| --- | --- | --- |
| No authenticated external real evidence / no Gate B receipt | High for real acceptance, outside BM-04 | BM-06/BM-09 |
| Primary implementation may share a mistake with its own goldens | Medium | BM-05 independent recomputation |
| Bootstrap percentile coverage on small/correlated blocks | Medium | Documented; BM-09 protocol qualification |
| New default estimator differs from the historical estimator | High if conflated | Distinct IDs + `analysis/history.py`; BM-07 |
| Missing genuine D3-C archives | Medium | BM-07/BM-09 |
| Historical T7 policy-verifier independence not migrated | Medium | BM-05/07 |
| Intermittent `u43` exact-set capacity assertion | Potentially high for `quervant-core` correctness | Separate investigation; blocks acceptance while CI is red |
| TOCTOU race against an adversarial byte-restoring actor | Medium | Ordinary rehash/replay only; authenticity is BM-06/09 |
| Python 3.11 reproducibility unproven locally | Low | CI pins 3.12; `requires-python >=3.11` retained |
| Remote CI not observed | Blocking for acceptance | Human / CI owner |

## 9. Reproduction

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ./benchmarks
python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_analysis_*.py' -v
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json
quervant-bench inspect --experiment synthetic-contract-smoke --format json
python benchmarks/scripts/bm-contract-inventory.py \
    --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de \
    --check docs/pr-artifacts/bm-01/legacy-inventory.json

cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps
cargo bench --workspace --no-run          # compile only — never run the benchmarks
bash benchmarks/scripts/test-scripts.sh
git diff --check
```

---

# 10. Independent-review fixup acceptance (RF04-01…04)

This section is appended for the PR #105 independent-review fixup. Section 1–9
above describe the original implementation head `9300e84`; this section records the
fixup execution state. Nothing above is rewritten.

## 10.1 Preflight (F0)

| Field | Value |
| --- | --- |
| Reviewed implementation head | `9300e84085d64e9aee2c24faa43c118aac19c6fb` |
| Actual start head (local and `origin/dev/bm04-analysis-policy`) | `9300e84085d64e9aee2c24faa43c118aac19c6fb` |
| `origin/main` / merge-base | `b085d7bf83d67c99ec510952042cc57c49fcee4a` (unchanged) |
| Branch | `dev/bm04-analysis-policy` |
| Worktree | clean (`git status --porcelain=v1` empty) |
| Prior CI run | `43780298373` on `9300e84`: Python PASS (504 tests), MSRV PASS, RustFS PASS, **Rust FAIL** (`u43_replacement_witness_all_variants`, `unified.rs:6371`) |
| Python baseline before edits | Python 3.12.3, `compileall` PASS, `unittest discover -p 'test_*.py'` → **504 tests, 0 failures, 0 skips** |
| Rust source changed | **NONE** (`git diff origin/main...HEAD --name-only` contains no `crates/`, `Cargo.toml`, `Cargo.lock`, `.github/`) |

Decision rules applied at preflight: `D01` (branch/head identity confirmed),
`D05` (all four reviewed findings reproduce in source). No `D02`/`D03`/`D04`
trigger: the base has not moved and there is no branch conflict.

## 10.2 Source confirmation of the four findings

| Finding | Confirmed location | Observed defect |
| --- | --- | --- |
| RF04-01 | `analysis/contracts.py::validate_policy_decision` (ranking/selection block) | `ranked_arms != eligible` compares GM order against *declaration* order; `DECISION_SELECTED` rejected unless `len(eligible) == 1` |
| RF04-02 | `analysis/derive.py::{_baseline_arm,_build_campaigns,analyze_synthetic_run}` | `_baseline_arm` returns `experiment.arms[0]`, ignoring the validated `policy_profile.baseline_arm_id` |
| RF04-03 | `analysis/policy.py::LanePolicyResult.to_document` (also `CandidatePolicyResult`, `RankedCandidate`) | `format(value, 'f')` emits `"0.95"` where the output contract requires exactly 12 fractional digits |
| RF04-04 | `analysis/contracts.py::{validate_analysis_result,validate_policy_decision}` | campaign counts are only checked for increasing indices; `blocks_total` is never compared to `protocol.schedule.blocks` |

`analysis/policy.py::_select` already implements GM-ascending ranking with stable
equal-GM declaration order and a best-two tie rule; it is **unchanged** by this
fixup (D07–D17).

## 10.3 Invariant → test map (written before implementation)

| Invariant | Positive oracle | Negative / adversarial oracle | Steps | Required tests | Status |
| --- | --- | --- | --- | --- | --- |
| `INV-01` Eligible ranking is sorted by GM, not candidate declaration order | Two eligible arms with GM order reversed from declaration validate | Permuted ranking / forged rank GM rejected | §4 | `FX04-SEL-01..05` | written |
| `INV-02` Decision status and selected candidate match the existing best-two/tie rule | Clear winner, frozen tie, exact-3% non-tie, three candidates | Forged selected ID/status and preference mismatch rejected | §4 | `FX04-SEL-06..12` | written |
| `INV-03` One frozen baseline for every comparison and identity | Baseline declared second, full sealed synthetic derivation | First-arm fallback and unrebound baseline mutation rejected | §5 | `FX04-BASE-01..05` | written |
| `INV-04` All policy output numbers have exactly 12 decimal places | Short/whole and 12-place limits serialize and validate | Float, exponent, overprecise, NaN policy input rejected | §6 | `FX04-DEC-01..06` | written |
| `INV-05` Campaign count equals protocol; indices `0..N-1` | 2/2 treatment analysis and policy | 0/1/3 campaigns, missing final, per-candidate truncation rejected | §7 | `FX04-INV-01..07` | written |
| `INV-06` Every lane `blocks_total` equals the protocol schedule | 4 blocks valid in all campaigns | 0/3/5 blocks and internally consistent but protocol-incomplete inventories rejected | §7 | `FX04-INV-08..12` | written |
| `INV-07` Read-only, no origin promotion, no new timing | 24/48/144 synthetic vertical slice; CLI `run` still 77 | Side effects, synthetic→real promotion or changed sealed bytes rejected | §8–9 | `FX04-SCOPE-01..05` | written |
| `INV-08` Mandatory CI uses the exact final SHA | Python + Rust + MSRV + RustFS PASS on one head | A red Rust job cannot be hidden by a selective rerun | §10 | `FX04-CI-01..04` | written |

## 10.4 Mandated counterexamples (written before implementation)

| Case | Plausible wrong behaviour that passes the happy path | Assertion that must kill it |
| --- | --- | --- |
| (a) eligible GM order differs from declaration order | validator compares `ranking` to `candidate_order`, so it rejects a *correct* GM-sorted ranking and only accepts declaration order | `FX04-SEL-01` must **pass** full validation with `candidate_order=[alpha,beta]`, GM `alpha=.90 > beta=.80`, `ranking=[beta,alpha]`, selected `beta`; `FX04-SEL-02` must reject `[alpha,beta]` |
| (b) policy baseline is second | derive uses `experiment.arms[0]`, so effects silently use the wrong denominator and the analysis identity names the wrong baseline | `FX04-BASE-02`: arms ordered `[candidate,baseline]`, policy baseline `baseline`, must yield `baseline_arm_id=baseline`, `candidate_ids=[candidate]` and non-reciprocal effects |
| (c) short decimal `"0.95"` | `format(...,'f')` on a profile literal renders `"0.95"`, which the validator's own `require_formatted_effect` rejects | `FX04-DEC-01`: a profile with `point_upper="0.95"`, `ci_upper="1"` must emit `"0.950000000000"` / `"1.000000000000"` and pass the full validator |
| (d) one of two campaigns deleted with all remaining records valid | validators only require increasing campaign indices, so a truncated inventory validates | `FX04-INV-02`/`FX04-INV-05` must reject `BM_IDENTITY_INVALID` at the campaign path, even though every remaining record is internally consistent |

No semantic ambiguity was encountered: §4–§7 and `D07`–`D30` fully determine each
resolution, so no `D61`/`D17` hard stop applies.

## 10.5 Test-first red baseline (recorded before implementation)

The new `FX04-*` cases were written first and executed against the reviewed head
`9300e84`. Every failure below is the *defect* being fixed, not a fixture error;
the exact signatures are preserved for the record.

| Suite | Result on `9300e84` | Representative signature |
| --- | --- | --- |
| `test_analysis_policy.py` | 50 tests: **7 failures, 8 errors** | `BM_IDENTITY_INVALID: ranking must list exactly the eligible candidates in frozen order`; `SELECTED_ELIGIBLE_SYNTHETIC requires exactly one eligible candidate`; `'0.95' != '0.950000000000'` |
| `test_analysis_contracts.py` | 28 tests: **6 failures** | truncated/extended campaign inventories and protocol-incompatible `blocks_total` accepted |
| `test_analysis_vertical_slice.py` | 39 tests: **5 errors** | `analysis record is missing candidate 'candidate' for lane 'rare-query'` (RF04-02); `point_limit must carry exactly 12 fractional digits` (RF04-03 end-to-end) |

Two additional missing-rejection cases were demonstrated on the reviewed head:
forging the non-preferred member of a tie, and forging
`TIE_PREFERENCE_NOT_PROVEN_FASTER` when only one candidate is eligible, both
validated successfully (RF04-01 §4.2).

## 10.6 Implementation

| Finding | File | Change |
| --- | --- | --- |
| `RF04-01` | `analysis/contracts.py::validate_policy_decision` | Ranking is recomputed as `sorted(eligible, key=(gm, declared_index))` and compared to the reported ranking; every rank entry must repeat its candidate GM. Selection/status is validated against the frozen best-two/tie rule (1 eligible, clear winner, tie by `tie_preference` among the top two, null+`INCONCLUSIVE`, baseline-only). `analysis/policy.py::_select` is **unchanged**, and `contracts.py` does not import `policy.py`. |
| `RF04-02` | `analysis/derive.py` | `baseline_arm_id = policy_profile.baseline_arm_id` is resolved once, membership- and arity-checked, then threaded into `_build_campaigns(..., baseline_arm_id=, candidate_ids=)` and into `AnalysisResult`. `_baseline_arm` (first-arm fallback) is deleted. `candidate_ids` keeps experiment order with the baseline removed. |
| `RF04-03` | `analysis/policy.py` | `LanePolicyResult`, `CandidatePolicyResult` and `RankedCandidate` render every Decimal through `contracts.format_effect` (fixed 12 places, `None` preserved). No parser, quantiser, operator or threshold change. |
| `RF04-04` | `analysis/contracts.py` | `validate_analysis_result` requires `len(campaigns) == read_protocol_campaigns(bundle).required_treatments` and `blocks_total == bundle.protocol.schedule.blocks` per lane. `validate_policy_decision` requires exactly `required_treatments` `campaign_results` per candidate. No filler records are ever synthesised. |

No file outside the authorized production/test/doc allowlist was modified. The
external signatures of `analyze_synthetic_run`, `evaluate_policy`,
`validate_analysis_result` and `validate_policy_decision` are unchanged, and no
new public symbol was exported.

## 10.7 Invariant results

| Invariant | Tests | Result |
| --- | --- | --- |
| `INV-01` GM ranking, not declaration order | `FX04-SEL-01..05` | PASS |
| `INV-02` status/selection follow the frozen best-two rule | `FX04-SEL-06..12` | PASS |
| `INV-03` one frozen baseline | `FX04-BASE-01..05` | PASS (BASE-02/03 are full BM-03 controller → replay → derivation) |
| `INV-04` 12-decimal policy output | `FX04-DEC-01..06` | PASS (DEC-06 is a full derivation with short profile literals) |
| `INV-05` campaign count equals the protocol | `FX04-INV-01..07` | PASS |
| `INV-06` `blocks_total` equals the schedule | `FX04-INV-08..12` | PASS (INV-11 is internally consistent but protocol-incomplete) |
| `INV-07` read-only, no promotion, no timing | `FX04-SCOPE-01..05`, `AN-SCOPE-01..06` | PASS |
| `INV-08` exact-final-SHA CI | `FX04-CI-01..04` | see §10.9 |

End-to-end coverage (real BM-03 controller, structural replay, BM-04 derivation):

* **Scenario A** (checked-in fixture): baseline `baseline`, candidate `candidate`,
  rare `0.800000000000`, common `0.833333333333`, both CI endpoints equal to the
  point, both validators PASS.
* **Scenario B** (arms ordered `[candidate, baseline]`): after the fix the analysis
  identity and every effect use `baseline`; effects stay `0.800000000000` /
  `0.833333333333` (never reciprocals).
* **Scenario C** (arms `[alpha, baseline, beta]`, 6 blocks × 3 slots, frozen
  baseline declared second): `candidate_ids == ["alpha","beta"]`, both candidates
  eligible, `ranking == ["beta","alpha"]`, selected `beta` with
  `SELECTED_ELIGIBLE_SYNTHETIC`, worst-campaign GMs `0.8485…` (beta) and `0.9721…`
  (alpha). This is the HIGH-severity defect closed end-to-end.
* **Scenario D** (policy limits written as `"0.95"`, `"1"`, `"1.1"`): identical
  numerical decision, and every emitted effect/limit/GM has exactly 12 decimals.
* **Scenario E** (validation-only mutations): illegal campaign inventories, block
  totals, rankings, GMs and selection/status pairs are rejected by the standalone
  validators without touching sealed evidence.

## 10.8 Local gate results at the fixup head

| Command | Result |
| --- | --- |
| `python -m compileall -q benchmarks/quervant_bench` | PASS |
| `unittest discover -p 'test_analysis_policy.py'` | PASS — 50 tests |
| `unittest discover -p 'test_analysis_contracts.py'` | PASS — 28 tests |
| `unittest discover -p 'test_analysis_vertical_slice.py'` | PASS — 39 tests |
| `unittest discover -p 'test_analysis_*.py'` | PASS — **181 tests** |
| `unittest discover -p 'test_*.py'` | PASS — **543 tests, 0 failures, 0 skips** |
| `PYTHONPATH=benchmarks python -m quervant_bench inspect …` vs `quervant-bench inspect …` | PASS — byte-identical stdout |
| `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check …` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 138 targets |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 138 targets |
| `cargo test --workspace --all-targets --all-features` | PASS — 138 targets |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.69%** lines (87.72% functions, 92.03% regions) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS (compile only; **no timing executed**) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 assertions |
| `git diff --check` | PASS |

Historical parity remains `EVIDENCE_UNAVAILABLE` (no authentic external archive);
the read-only arithmetic-compatibility tests still pass and nothing was
substituted for the missing history.

## 10.9 Failure classification and final gate status

| Failure | Classification | Evidence / disposition |
| --- | --- | --- |
| `cf_t01`…`cf_t14` (`pr07_compatibility`) failed `NotFound` on the first MSRV all-features run of this fixup | **(5) environment/harness failure** | The `target/debug/deps` test binary embedded `/tmp/bm04-base/crates/quervant-core/tests/fixtures/…` — a stale artifact from the temporary base worktree created during the previous review round in the *shared* `target/` directory. `strings` on the binary showed the stale path. The 138 stale artifacts referencing that path were deleted (`target/` is generated, git-ignored, and no source was touched); the same command then passed with 138 targets. Not caused by BM-04: no `crates/` content changed. |
| Known intermittent `search::unified::d3c_tests::u43_replacement_witness_all_variants` | **(4) nondeterministic, previously proven on base** | Did not recur in the fixup runs; the original evidence in §4 stands (branch 4/8, base `b085d7b` 3/20, identical panic). Owner: `quervant-core`. It cannot be waived. |

| Gate | Status |
| --- | --- |
| Implementation gate | **PASS** — exact allowlist, four findings fixed, no parser/schema/CLI/timing change, zero unit-test regressions |
| Correctness gate | **PASS** — `INV-01..07` mapped to executed positive and negative cases, including two full BM-03→BM-04 derivations (non-first baseline, multi-eligible) and a protocol-incomplete-inventory rejection |
| Final-head CI gate | **UNVERIFIED** — local equivalents all green; the four GitHub jobs at the fixup SHA were not observable with the available credential (`D42`/`D59`) |

The pre-existing `u43` flake means the `rust` CI job may be red for reasons
outside BM-04; a green run on the exact final SHA is nevertheless required before
this fixup is review-ready (`D43`/`D45`).

## 10.10 Decision-matrix rules used in this fixup

`D01` (branch/head identity), `D05` (all four findings reproduced in source),
`D07`–`D17` (selection semantics as already implemented), `D18`–`D20` (baseline
authority and unrebound-mutation rejection), `D22`–`D24` (canonical rendering vs.
strict parsing), `D26`–`D30` (inventory and block-count contracts), `D33`
(existing goldens retained unchanged), `D34` (isolated real synthetic fixtures),
`D39` (u43 remains separately tracked), `D41` (local RustFS absent → CI-owned),
`D42`/`D59` (CI unverifiable → `CI_UNVERIFIED` disposition), `D49` (append-only
report), `D51` (isolated fixture builder in `analysis_support.py`), `D53`
(continuous execution), `D56` (push only allowlisted changes).

Deferred: `D39`/`D45` (`u43`, `quervant-core` owner), `D41` (RustFS, CI-owned),
`D42`/`D59` (remote CI observation), `D47` (historical archive absent).

No `HARD STOP` condition was encountered: no protected path needed editing, no
policy/status semantics required a new decision, and no fixture required a new
runtime feature.
