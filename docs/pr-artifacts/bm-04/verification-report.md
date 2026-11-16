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
