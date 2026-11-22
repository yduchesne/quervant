# PERF-02-A — Real-host A=A Qualification Handoff

**Target:** [PR #115](https://github.com/yduchesne/quervant/pull/115), branch `dev/perf02a-quervant-warm-ab`.  
**Authority:** [Detailed PR Plan Authoring Guide](../../DETAILED_PR_PLAN_AUTHORING_GUIDE.md), [AGENTS.md](../../../AGENTS.md), [TESTING.md](../../TESTING.md), [BENCHMARKING.md](../../BENCHMARKING.md), [PERF optimization roadmap](../../PERF_OPTIMIZATION_ROADMAP.md).  
**Status at handoff:** Code and deterministic/mock tests are authored in the PR; **real-host execution and final local QA are not yet verified**. Do not report DONE until every mandatory gate below passes.

## 0. Continuous execution authorization and scope

Execute all authorized steps in order without asking for routine permission after passing a gate. Apply the decision matrix below before making corrections. Continue independently safe QA/reporting on a blocked external dependency, but never claim a blocked gate PASS.

The purpose is to establish that the merged BM-10 runner now supports a prospective, **Quervant-only, pinned two-source warm A/B study**. This is **not** a new optimization, not the PERF-02-B profiling phase, and not an attempt to demonstrate a speedup. A and B in the first real qualification must use the **same accepted Git revision**, compiled separately.

**No redesign permitted:** do not change the schedule, statistical estimator, stored schema, naming convention, A/A decision, readiness thresholds, benchmark family architecture, timed-operation boundaries, correctness oracle, corpus, or existing result artifacts. Narrow bug fixes and necessary tests are authorized only as defined below. Do not merge the PR.

## 1. FIRST ACTION — synchronize the exact PR branch

Before inspecting, testing, staging, editing, or running a benchmark, execute:

```bash
git fetch origin
git switch dev/perf02a-quervant-warm-ab
git pull --ff-only origin dev/perf02a-quervant-warm-ab
git rev-parse HEAD
git status --porcelain=v1
```

If local changes obstruct the fast-forward, **STOP** instead of discarding/stashing/resetting them without authorization. Do not run against an earlier revision. Record the exact head SHA; on any subsequent code fix, commit and push it, then repeat the mandatory checks against the new head. Ensure source/runner/adapters/manifests are committed and clean; untracked result JSON is allowed by existing scoped-source rules.

The immutable **A=A** configuration is:

```text
benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json
```

Both `arms.A.revision` and `arms.B.revision` must equal:

```text
b79b1278a6f9e43fe6e9a760ee714e4f0a76dd51
```

Do **not** replace these refs with `HEAD`, branch names, or a new candidate. The runner must build two different executable paths, `build/quervant-a/release/pr15d-quervant-adapter` and `build/quervant-b/release/pr15d-quervant-adapter`, from separate detached worktrees pinned to these exact commits. Both source revisions must be verified Git `commit` objects before builds. The accepted production policy remains linear below K32, P2 prefilter at K32+; experimental strategy feature and overrides must be absent.

## 2. Required preflight and baseline invariants

- Host: dedicated idle native Linux or WSL2, scratch on ext4/xfs/btrfs, at least two available *distinct physical* cores, CPU affinity via `taskset`. Do not bypass host readiness or claim ordinary CI supplies real-host qualification.
- Toolchains: Rust toolchain selected by repository `rust-toolchain.toml`, Rust 1.85.0 for MSRV checks, Cargo, Python 3.12+, `git`, and Python benchmark package dependencies. Perl/Java are not required for Quervant-only adapters. The existing host-context code may record Java identity but PERF-02 does not build or execute Lucene/Tantivy.
- The workload is unchanged BM-10 exact-keyword semantic parity: sizes 10K/100K; classes absent/rare/medium/common; K10/K100; 16 warm lanes; exact total hits and ordered `doc_id` values; query-only adapter `engine_ns`.
- Preparation builds, indexes, commits and opens outside measured warm query. The independent untimed oracle must validate **all 16 lanes for both arms** before any A/A or treatment samples.
- A/A checks compare AA and AA2 using the same baseline arm A, separately from A-vs-B treatment. Original policy is 12 randomized blocks, two slots per arm/block, five untimed warmups and 20 timed samples per slot/lane, 10,000 block-bootstrap resamples. Do not modify sample counts or choose later exclusions in response to observed values.
- A and B must retain independent prepared index directories even though their source revision is equal. Prepared cache must fingerprint executables, corpora and indexes. Each new `run` has its own host checks, controls, samples, result sequence/UUID.
- No `perf-02/warm/results/*.json` is asserted to exist until genuine real execution. The existing cross-engine and retained-key results remain byte-for-byte unchanged.

## 3. QA before real timed acquisition

Install/use the actual dependencies and run all applicable local gates against the **final** source revision:

```bash
python -m pip install -e ./benchmarks
python -m pip install pytest coverage
python -m compileall -q benchmarks/quervant_bench
python -m pytest -q benchmarks/quervant_bench/lean/tests
coverage run --branch --source=quervant_bench.lean -m pytest -q benchmarks/quervant_bench/lean/tests
coverage report --fail-under=85
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
cargo test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml
git diff --check
```

Also confirm mandatory GitHub Actions workflows for **the last pushed PR SHA** have completed successfully, including Rust, MSRV, RustFS, Python benchmark-framework and relevant adapter-contract checks. Do not waive a test/coverage failure because a different job passed. Distinguish blocked RustFS topology/permissions from PASS. After any fix, rerun affected local checks **and** final mandatory full gates.

Before measurement, inspect that `A` and `B` do not accidentally share the same compiled output path or index directory and that their build context records the pinned source revisions. The A=A test does **not** mean it is acceptable to use the same binary path for both labels.

## 4. Stage and execute ONE real A=A warm campaign

Run only when QA and host gates above pass. Use the versioned configuration unchanged:

```bash
CONFIG=benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json
quervant-bench validate --config "$CONFIG"
quervant-bench stage --config "$CONFIG"
quervant-bench run --config "$CONFIG"
```

`stage` must report `PREPARATION=BUILT` or a source-valid `HIT`; this phase never publishes a timed result. `run` executes readiness, full A/A, full A/B treatment, analysis and exclusive publication, returning `RESULT_JSON=<exact path>`. Do not manually supply an alternate results path. Preserve a machine-readable result under `benchmarks/studies/perf-02/warm/results/` with the automatic execution-date and sequence suffix; never overwrite an existing result.

**Expected complete sample shape**: 16 lanes × 12 blocks × 2 slots × 2 treatment arms = **768 A/B slot/lane rows** (15,360 timed query samples). A/A contributes another **768 slot/lane rows**. Every full row contains 20 positive integer nanosecond samples; `oracle_ok` true; no invented, missing, selectively removed or retimed samples. There are no Lucene/Tantivy arms or warm serial-throughput requirement in this study.

## 5. Inspect actual result and report evidence

After `run`, copy the exact `RESULT_JSON` printed by the CLI; inspect the JSON itself using Python/JQ and these read-only commands (replace the variable with its actual path):

```bash
RESULT_JSON=benchmarks/studies/perf-02/warm/results/<actual-execution-name-and-sequence>.json
quervant-bench report --result "$RESULT_JSON"
quervant-bench analyze --result "$RESULT_JSON"
```

Mandatory checks:

1. `status == COMPLETE`, `errors == []`, `configuration.family == perf-02`, both pinned `revision` fields equal the fixed baseline SHA, and `context.build.arm_source_revisions` reports the same pair.
2. All required host readiness probes report `clear`, including before/after A/A/treatment. All 16 A/A comparison statuses are `PASS`. No missing/invalid `engine_ns`, `oracle_ok`, strategy/feature mismatch or excluded blocks.
3. `raw_samples` has exactly 768 treatment rows, and `controls.raw_samples` exactly 768 A/A rows; all 16 lanes have 12 fully observed blocks with 2 slots per arm and 20 samples per slot.
4. Independently recalculated `analyze` output agrees numerically with the saved `analysis` (read-only; no new acquisition). Preserve all median/CI/per-lane comparisons. For this A=A study, expect ratios near 1.0 and no material systematic treatment difference. **Before inspecting values**, apply the existing 15% A/A stability tolerance as a diagnostic bound to A/B point estimates; any abs gain over 15%, unexpected strong arm bias or inconsistent CIs requires **STOP and investigation**, not selective reruns.
5. The cached preparation shows separately fingerprinted A/B binaries and indexes and each source is pinned; result provenance and preparation timing fields are present. No cross-engine production result is modified.

A complete run may legitimately report some `INCONCLUSIVE` A/B effects when the binaries are identical; this is **not** evidence of a failed runner or a zero-percent optimization win. A random-looking significant `IMPROVED`/`REGRESSED` lane is a **diagnostic to investigate**, not an automatic reason to cherry-pick another sample. Record it explicitly. This A=A run is not PERF-02-B candidate qualification.

Only after validated success, commit and push the **new, unmodified result JSON** in the same PR branch. No manual report Markdown is a third canonical artifact. Do not commit `target/` scratch or generated executable/index files.

## 6. Preauthorized exception and decision matrix

| ID | Observable trigger | Category | Authorized action | Prohibited behavior / disposition |
| --- | --- | --- | --- | --- |
| E01 | Missing Python package/tools but installation is permitted | AUTO-RESOLVE | Install using repository-prescribed commands and rerun failed gate | Never suppress tests or coverage |
| E02 | Narrow deterministic test/build/import bug attributable to PERF-02-A touched code | AUTO-RESOLVE | Smallest local fix with targeted red/green regression, commit and push; rerun full final gates | Do not redesign framework, adjust schedule/thresholds, or change public benchmark semantics |
| E03 | Formatting or straightforward Clippy issue in the touched PERF-02-A files | AUTO-RESOLVE | Apply required formatting/narrow lint correction, test and push; rerun required gates | Do not disable clippy, skip tests or weaken CI |
| E04 | Existing cache marked invalid, with no active readers | DEFER AND CONTINUE | Preserve data, classify exact corruption; continue independent QA; report safe proposed retirement | Never delete concurrent cache or silently overwrite completed cache |
| E05 | Unsupported WSL2 host/filesystem/physical cores, tools unavailable without safe setup | DEFER AND CONTINUE | Record host preflight failure; complete independent checks and docs | No fake host/readiness values, no claim of real measurement |
| E06 | A/A readiness failure, oracle mismatch, unexpected large A=A effect or partial run | HARD STOP — timed qualification | Preserve published INCOMPLETE result if one exists, report symptoms and source state, continue unrelated checks | No favorable selective reruns, threshold changes, forged success or manual sample pruning |
| E07 | Candidate changes required in `quervant-core`, search semantics, index format, source contract, outcome calculation, provenance or result schema | HARD STOP — affected implementation | Record the technical issue and request architectural authorization | Do not improvise production optimization or new framework |
| E08 | Pinned commit unavailable or not a commit / uncommitted or dirty source / invalid config SHA | HARD STOP — staging | Record SHA and reason, obtain correct authorized source state | No branch-name substitution or changing frozen configuration |
| E09 | Unexpected condition not covered here | DEFER AND CONTINUE if independent work safe; otherwise HARD STOP | Report source-level evidence and request a plan amendment | No discretionary rearchitecture |
| E10 | All gates pass and result is genuine and validated | AUTO-RESOLVE | Commit/push the exact new result JSON and provide final evidence report | Do not merge the PR or mark PERF-02-B done |

A mandatory failure must be classified with evidence as (1) introduced regression, (2) implementation defect, (3) deterministic pre-existing failure (prove on baseline), (4) demonstrated flaky/nondeterministic failure, or (5) environment/harness failure. "Unrelated" alone is not a disposition.

## 7. Final report and reviewer checklist

Report exactly:

- final source SHA, branch, cleanliness of touched files and CI run URLs; Git worktree/build separation verified;
- required local QA table: command, PASS/FAIL/BLOCKED, test counts and exact line/branch coverage values;
- host platform, toolchains, Linux filesystem, CPU affinity, readiness observations and reason if unavailable;
- source/config/UUID, A and B revision SHA and build provenance; generated result filename, run_id, disposition;
- A/A status for all 16 lanes; raw slot and sample counts; independent oracle/check counts;
- paired A/B ratios and uncertainty in the A=A diagnostic (no optimization claim); material outliers or residual risks;
- stage/cache disposition, result analysis/report reproducibility, committed result SHA (if genuine);
- applied exception-matrix decisions, any blocked gates and precise next action.

**Terminal outcomes:** `PERF02A_AA_REAL_PASS_READY_FOR_REVIEW` only after all mandatory local, CI and actual host/result checks pass; otherwise `PERF02A_BLOCKED` or `PERF02A_FAILURE_NEEDS_FIX` with specific evidence. PERF-02-B profiling and candidate selection remain independent future work.
