# PERF-02-A — Host sanity validation handoff (NO TIMED CAMPAIGN)

**Target:** [PR #115](https://github.com/yduchesne/quervant/pull/115), branch `dev/perf02a-quervant-warm-ab`.  
**Authority:** [Authoring guide](../../DETAILED_PR_PLAN_AUTHORING_GUIDE.md), [AGENTS.md](../../../AGENTS.md), [TESTING.md](../../TESTING.md), [benchmark methodology](../../BENCHMARKING.md), [PERF roadmap](../../PERF_OPTIMIZATION_ROADMAP.md).

**Scope correction (2026-11-22):** The earlier version of these instructions erroneously required a full 12-block real A=A campaign. **That instruction is revoked.** The user has directed that any campaign already underway be aborted. Do not resume or restart it. PERF-02-A requires only bounded **host staging / sanity validation**. The full warm A/B campaign is deferred until a PERF-02-B optimization candidate exists and its separate measurement protocol has been approved.

## 0. Non-negotiable boundaries

- **NEVER invoke `quervant-bench run` during PERF-02-A.** Do not invoke it through Python, a script, direct runner imports, altered sample counts or a "short" campaign. Do not execute A/A controls, timed A/B blocks, or serial throughput measurements.
- Do not modify the immutable configuration to shorten the schedule or fabricate a timing result. A valid configuration may contain a full future schedule; **validating or staging it does not authorize executing that schedule**.
- No benchmark result JSON is expected or required; do not claim A/A statistical stability, warm latency, a speedup, or a completed performance campaign.
- Preserve any partial/interrupted result or log from the previously aborted campaign for diagnostic review, without promoting it to accepted evidence or silently deleting/overwriting it. Do not commit it as a successful result. Report its location/disposition if it exists.
- No changes to benchmark architecture, statistics, measurement gates, sampling parameters, production search code, or existing result JSON. Only narrow, proven PERF-02-A defects and regression tests may be fixed.

## 1. Mandatory first action — refresh branch before any work

```bash
git fetch origin
git switch dev/perf02a-quervant-warm-ab
git pull --ff-only origin dev/perf02a-quervant-warm-ab
git rev-parse HEAD
git status --porcelain=v1
```

Stop if local modifications or an active benchmark process prevent a clean, safe fast-forward. **Do not discard, stash, reset, overwrite or delete in-progress user/agent files** to force synchronization. If a previous campaign was interrupted, first verify that its active processes have stopped and note any incomplete artifacts; no continuation is authorized.

The exact checked-in **same-source A/B preparation configuration** is:

```text
benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json
```

Both `arms.A.revision` and `arms.B.revision` must equal the accepted baseline:

```text
b79b1278a6f9e43fe6e9a760ee714e4f0a76dd51
```

The same Git revision is deliberately built as two **independent** release binaries (`quervant-a` and `quervant-b`). This proves build isolation, not performance equivalence. Both must use the production-default strategy (linear for K10; P2 prefilter for K100), with the historical strategy experiment disabled.

## 2. Targeted preflight and code quality

1. Confirm the required Linux/WSL2 host capabilities: native ext4/xfs/btrfs scratch filesystem, available distinct physical cores, `taskset` and a working Rust/Cargo toolchain. Do not bypass any stage-time host/readiness check.
2. Check that both pinned Git objects exist and have type `commit` (`git cat-file -t <SHA>`), with committed, clean benchmark build-relevant source. Reuse the existing immutable configuration.
3. Confirm the current PR's CI status: Python benchmark framework/config validation, Rust, MSRV, adapter contract, and RustFS jobs. If cancelled or blocked, record exact status; do not call it PASS.
4. Run relevant deterministic/mocked tests and repository-required checks for the final code revision. For example:

```bash
python -m pip install -e ./benchmarks
python -m pytest -q benchmarks/quervant_bench/lean/tests
quervant-bench validate --config benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json
git diff --check
```

Follow [AGENTS.md](../../../AGENTS.md) for additional mandatory final-source local QA/coverage if the implementation is to be declared review-ready. **These checks do not authorize timed acquisition.** If unrelated or environment-specific gates cannot run, classify them honestly; do not silently substitute a real benchmark.

## 3. One bounded real-host STAGE sanity check

After preflight, execute exactly these benchmark CLI operations:

```bash
CONFIG=benchmarks/studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json
quervant-bench validate --config "$CONFIG"
quervant-bench stage --config "$CONFIG"
```

**STOP after `stage`. Do not run `quervant-bench run`.** No extra acquisition command is authorized.

The existing `stage` operation performs:
- the host capability and pre-index readiness checks;
- building two Quervant release adapters from the two pinned revisions, with separate worktrees/Cargo outputs;
- generating the declared 10K/100K corpora, building and committing one index per arm and size (**four prepared indexes**), and reopening/verifying them;
- independent **untimed** exact-query correctness-oracle checks for all 16 declared warm lanes in each arm (**32 lane/arm checks**);
- publishing a disposable, cache-identity-bound preparation entry under `target/bm10/prepared/<cache-key>/` (no timed samples and **no** benchmark result JSON).

A valid `PREPARATION=BUILT` or `PREPARATION=HIT` indicates staging succeeded. A cache HIT must still revalidate the oracles; a missing/mismatched/corrupted published cache must fail closed. Inspect the returned preparation key and manifest without modifying them. Verify:
- two distinct executable paths, each identifying `pr15d-quervant-adapter`, one under `quervant-a` and the other `quervant-b`;
- four distinct prepared index paths (arm A/B × 10K/100K);
- both pinned source SHA values represented in the preparation identity/build context;
- the presence of index metrics and valid untimed oracles for both arms;
- no new timed benchmark result JSON and no active timed acquisition.

Stage-time `index_ns`, `commit_ns` and `reopen_ns` are preparation metadata **not** a query-latency benchmark or A/B evidence.

## 4. Decision matrix

| ID | Trigger | Action | Terminal/continuation |
| --- | --- | --- | --- |
| S01 | Config validation, source preflight, or host capability check fails | Capture exact failure and environment; fix only an obvious narrow PERF-02-A defect with tests | STOP staging if unresolved; `PERF02A_HOST_SMOKE_BLOCKED` |
| S02 | Deterministic harness/build/cache/oracle bug in touched PERF-02-A code | Smallest focused regression-tested correction; commit/push; repeat relevant checks and `stage` once when safe | AUTO-RESOLVE; no design changes |
| S03 | CI cancelled, local mandatory QA unavailable or non-pertinent external topology blocked | Report precisely; complete independent safe checks; distinguish host stage outcome from overall PR QA | DEFER QA, not falsely PASS |
| S04 | `stage` succeeds, binaries/indexes/oracles/provenance correct | Record preparation key, source SHA, host fingerprint, build isolation and stage timing | `PERF02A_HOST_STAGE_SMOKE_PASS` |
| S05 | `stage` reports corrupted completed cache or active/incomplete prior campaign | Preserve evidence and stop conflicting actions | HARD STOP affected stage; do not delete a cache in use |
| S06 | A user/agent instruction suggests `run`, A/A, timed slots, reduced samples, or a fresh performance result during PERF-02-A | Do **not** execute; cite this superseding scope correction | HARD STOP timed acquisition |
| S07 | An unanticipated source semantics, index format, stat/runner redesign or non-narrow fix is necessary | Produce an evidence-based blocker report and seek a separately approved design | HARD STOP affected change |

Do not run a complete or shortened real campaign to diagnose a stage error. Avoid repeating stages without a concrete source defect. Do not merge the PR or proceed to PERF-02-B profiling within this handoff.

## 5. Report to the reviewer

Report branch and exact tested commit, git cleanliness, CI/local QA status with counts, Linux/WSL2 host/toolchains/filesystem/core availability, `VALID` outcome, `stage` `BUILT/HIT`, preparation cache key, pinned revisions, independent executable/index paths, the 32 untimed oracle checks, and any blocked or corrected issue. Explicitly state **TIMED_QUERY_CAMPAIGN=NOT_RUN** and **A/A_STATISTICAL_QUALIFICATION=NOT_RUN**.

**PERF-02-A host-stage readiness disposition:** `PERF02A_HOST_STAGE_SMOKE_PASS` only if staging checks really succeeded; otherwise `PERF02A_HOST_SMOKE_BLOCKED` or `PERF02A_HOST_SMOKE_FAILED`. Full candidate A/B benchmarking requires a later, separately authorized PERF-02-B configuration and execution plan.
