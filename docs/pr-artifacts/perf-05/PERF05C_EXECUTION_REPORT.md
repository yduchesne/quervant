# PERF-05-C — Execution Report

**Milestone:** `v0.1-perf` · **Stage:** PERF-05-C (B-only warm qualification against retained historical A)
**Branch / PR:** `dev/perf05-physical-execution-series` · PR [#117](https://github.com/yduchesne/quervant/pull/117)
**Plan of record:** [`PERF05C_DETAILED_PLAN.md`](PERF05C_DETAILED_PLAN.md) (verbatim copy; `cmp` identical, 0 trailing spaces)
**Decision:** `PERF05C_B_ONLY_HISTORICAL_A_NO_RUSTFS_NO_UNNECESSARY_WORK`

---

## REPO / BRANCH / PR

- **Repository:** `yduchesne/quervant`
- **Branch:** `dev/perf05-physical-execution-series` (existing PR #117; no new PR)
- **PR:** #117 (OPEN, unmerged; draft metadata untouched)

## START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA

- **B (measured source) / C start:** `ee18ed63bbeeb54b544393ee0f676987ff9987d1` (PERF-05-B1…B5)
- **C framework commit (commit 1):** `6764fe6a8d4e534af1a52b8838683f7981e69e98`
- **MAIN_SHA:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8` (pre-PERF-05 base, **not** the measured A source)
- **FINAL_SHA / REMOTE_VERIFIED_SHA:** the commit containing this report, configuration and result
  (commit 2), reported exactly in the terminal agent response via `git rev-parse HEAD` and
  `git rev-parse origin/dev/perf05-physical-execution-series` after push.

## HISTORICAL A IDENTITY (loaded read-only; never executed)

- Result: `benchmarks/studies/cross-engine/warm/results/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json`
- Git blob: `a809f0362553e4e5c93ac1593ef478e8eef6a865` (verified with `git hash-object`)
- `configuration_id`: `c4083f1e-4ce2-4477-b282-04c4d40b187f`
- `run_id`: `f2df1d40-2eee-4fcb-9593-ba8433e08c4a`
- Arm consumed: `Q`; mode `historical-absolute-unpaired`
- **Measured A source:** `256501f0e700ed199f316e79d128389375177530` (not `9775bfca…`)
- Verification: `status=COMPLETE`, 16 lanes, 16/16 A/A PASS, all readiness observations `clear`,
  Q raw samples `oracle_ok=True`, 12 positive block values per lane and every stored median
  recomputing exactly to the frozen fixture.

## IMPLEMENTED FILES

Commit 1 (framework, tests, docs, plan):
`benchmarks/quervant_bench/lean/{artifacts,configuration,cli,preparation,runtime,reporting}.py`,
new `benchmarks/quervant_bench/lean/perf05.py`, new `benchmarks/quervant_bench/lean/tests/test_perf05.py`,
`benchmarks/BM10_README.md`, `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`,
`docs/BENCHMARKING.md`, `docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md`,
`docs/pr-artifacts/perf-05/PERF05C_DETAILED_PLAN.md`.

Commit 2 (immutable artifacts + this report):
`benchmarks/studies/perf-05/warm/configurations/quervant-perf05-b-only-warm-2026-11-23.json`,
`benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-001.json`,
`docs/pr-artifacts/perf-05/PERF05C_EXECUTION_REPORT.md`.

## SOURCE PROOFS S01–S17 / OUTCOME

Confirmed on the pulled branch: the `perf-05` family is warm-only with a single pinned arm `B`;
`_control_config` derives `BB`/`BB2` aliases from the declared control roles while legacy families
keep `AA`/`AA2`; `_phase` resolves both aliases through `source_arm`; `build_programs` builds exactly
one pinned B worktree/target and removes it; `stage_inputs` verifies the historical reference before
the first build/index; `run_benchmark` dispatches the B-only path before generic A/A+treatment; the
historical verifier and B-only estimator are pure/read-only; reporting has a dedicated PERF-05
presenter. Existing BM-10 families are unchanged (full suite passes).

## RED FIRST

The frozen plan requires new tests to fail only because the `perf-05` family/analysis does not yet
exist. In this execution the framework implementation landed before the test module was written; the
RED was therefore captured deterministically against the extracted pre-C commit (`git archive HEAD
benchmarks/quervant_bench`) rather than by reverting the worktree:

- `ImportError: cannot import name 'perf05' from 'quervant_bench.lean'`
- `TypeError: default_configuration() got an unexpected keyword argument 'quervant_revision'`

Both failures are exactly the absent family/helper surface; no fixture or oracle error was involved.
The final test module is `test_perf05.py` (C-U01…C-U16 coverage).

## FRAMEWORK QA (Python only; no Rust source changed)

| Command | Result | Evidence |
|---|---|---|
| `PYTHONPATH=benchmarks python -m compileall -q benchmarks/quervant_bench` | PASS | compiles |
| `PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf05.py` | PASS | 23 passed |
| `PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests` | PASS | 273 passed |
| `coverage run --branch --source=quervant_bench.lean -m pytest -q …/tests` then `coverage report --fail-under=85` | PASS | **89% branch coverage** total (`perf05.py` 83%) |
| `quervant-bench --help` | PASS | CLI discovery |
| `git diff --check` / staged `--check` | PASS | clean |

Rust workspace QA was not repeated: no Rust source changed and the B5 Rust CI run #45126782770
(#522) is the applicable source qualification. No RustFS, profiler, Criterion or unrelated
integration work was performed.

## B ACQUISITION PROVENANCE

- Executable source: `ee18ed63bbeeb54b544393ee0f676987ff9987d1`, built from a detached Git worktree
  with `cargo build --release --locked`; strategy feature `false`; worktree removed after build.
- Preparation cache: `BUILT`, key `022379cd0598d9a93c2382e9a6dfbd142069e9b42705c9045d664c9770e593b8`.
- B-only indexes, one segment each: 10K `1,560,111` bytes; 100K `15,747,551` bytes — exactly matching
  the historical Q index diagnostics.
- Oracles: all 16 staged lane oracles passed; all 384 captured slot/lane records have `oracle_ok=True`.
- Acquisition: exactly one `quervant-bench run`; `BB` and `BB2` invoked the same B executable and
  indexes; 24 slots × 16 lanes = 384 records; 192 records per alias; 5 warmups + 20 samples each.
- Readiness: `readiness_index_pre=clear`, `readiness_pre=clear`. The post-readiness probe was not
  reached because the B/B gate raised first.
- No A/Tantivy/Lucene executable, index, query, RustFS service or profiler was involved.

## RESULT AND DISPOSITION

- Configuration: `f4e2b8a4-db2b-4dcf-8e68-3bdf207389a4`,
  `benchmarks/studies/perf-05/warm/configurations/quervant-perf05-b-only-warm-2026-11-23.json`.
- Result: run `1e22a06c-acee-422d-9a7e-c50cde543d20`, sequence `001`,
  `benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-2026-11-23-001.json`.
- **Status: `INCOMPLETE`.** Error: `B/B control is unstable; B-only acquisition is blocked`.
- **B/B stability: 15/16 lanes PASS.** Failing lane `10000/absent/k10/warm`, comparison `BB2` against
  `BB`: ratio `0.9918`, gain `0.82%`, 95% ratio CI gain `[-5.062%, 16.905%]`, which exceeds the frozen
  `max_aa_gain_percent = 15` bound. The 10K absent lane is the lowest-latency (~30 µs) and
  highest-variance lane; its block values show clear host scheduling noise.
- Because the frozen B/B gate failed, **no absolute B estimate, no historical descriptive ratios and
  no target/guard flags were computed or claimed**. The result retains the complete B raw samples.
- Per plan rule D19, the agent did **not** rerun, retune, exclude blocks, relax thresholds or switch
  hosts. One acquisition only; the INCOMPLETE result is preserved unchanged.

## WORKSPACE COVERAGE

Python benchmark framework branch coverage **89%** (floor 85%), measured by
`coverage run --branch --source=quervant_bench.lean`; `perf05.py` 83%. No exclusions or floor change.

## REAL LOCAL FS / RUSTFS / CI / PROFILING

- Real local native filesystem (ext4) staging and 10K/100K index build/commit/reopen: PASS.
- RustFS: **not in scope, not started** (maintainer decision).
- Profiling (`perf`/symbols/Criterion): **not executed; deferred, not a gate**.
- Hosted Python CI for the pushed commits: **PENDING** at report time; not claimed green.
- B5 Rust CI #45126782770 (#522) remains the applicable Rust-source evidence.

## EXCEPTION MATRIX ROWS

- **D05 (AUTO-RESOLVE)** — historical blob/IDs/source/16 lanes verified read-only.
- **D07 (AUTO-RESOLVE)** — recorded measured A source `256501f0…` distinct from `9775bfca…`.
- **D08 (AUTO-RESOLVE)** — added only the exact `perf-05` family/runtime/reporting additions.
- **D11 (AUTO-RESOLVE)** — one pinned B worktree/release build, SHA validated, worktree removed.
- **D14 (AUTO-RESOLVE)** — verified cache HIT on `run`; all lane oracles rechecked.
- **D16 (AUTO-RESOLVE)** — host readiness clear at stage and pre-acquisition.
- **D19 (HARD STOP, applied as directed)** — B/B control unstable on one lane after a valid single
  acquisition: published `INCOMPLETE`, preserved all 384 raw records, did not rerun or exclude.
- **D23/D24 (AUTO-RESOLVE)** — RustFS and profiling ignored/deferred per the decision.
- **D26 (AUTO-RESOLVE)** — deterministic Python suite and coverage passed before pushing.
- **D28 (DEFER AND CONTINUE)** — hosted CI pending; reported truthfully.
- **D29 (AUTO-RESOLVE)** — B5 Rust CI cited; no Rust re-QA or RustFS run.

No autonomous retry, threshold change, source tuning, force push or merge occurred.

## OPEN GATES / RESIDUAL RISKS / FAILURE CLASSIFICATION

**Open gates:** B/B stability must be re-established before any historical-relative qualification;
any subsequent acquisition requires fresh human approval and must not be described as a continuation
or retry of this attempt. Hosted CI remains pending. Profiling remains a separate, unapproved plan.

**Residual risks:** the B/B instability is a measurement-environment outcome on the lowest-latency
lane, not a correctness defect; the B executable, indexes and oracles are intact and reproducible.
Because no historical comparison was computed, no performance improvement or regression is claimed.
A/B here would in any case be cross-session and descriptive, never a paired causal estimate.

**Failure classification:** the B/B gate failure is a **nondeterministic/host-variance measurement
failure** (observed 95% ratio CI beyond the frozen stability bound on one lane). No source regression,
oracle failure, index mismatch or harness error was observed.

## NO_BENCHMARK_RERUN=TRUE; NO_PROFILING_RUNS=TRUE

Exactly one B-only acquisition was attempted. No second run, no retry, no A/Tantivy/Lucene/RustFS
acquisition, and no profiler/Criterion/`perf`/microbenchmark was executed.

## B_DISPOSITION

**`PERF05C_B_ONLY_INCOMPLETE_BB_CONTROL`**

The framework, pinned single-B provenance, index shape, oracles and complete 384-record B raw data
were produced and preserved, but the frozen B/B stability gate failed on one lane, so no B absolute
estimate or historical-relative comparison is reported. PR #117 remains open and unmerged; adoption
and any further measurement require human review and a new, separately authorized plan.

## NEXT

Human review of this INCOMPLETE qualification and the B/B instability evidence. If a further
acquisition is desired, it requires explicit authorization, must not reuse this result as a paired
estimate, and must keep the same fail-closed B/B gate. B6, PERF-05-D and profiling are not authorized.
