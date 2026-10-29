# PR 15C-B A-R2 implementation record

Status: **implementation complete and locally verified; qualified measurement
deferred pending the operator idle attestation.**

Append-only record for the A-R2 amendment
(`QUERVANT_PR15C_B_A_R2_PROFILER_EVIDENCE_FIXUP_PLAN.md`), which resolved
`STOP-15CB-02`. Rationale and scope: `frozen-tooling-exception.md`.
Decision log: `decisions.md`.

## 1. S0 reconciliation (observed, not assumed)

| Item | Value |
|---|---|
| Branch | `dev/pr15c-b-performance-qualification` |
| Head at S0 | `a9af8de10752282399b61adaedc6308fe1c17461` (clean) |
| Local `main` / `origin/main` | `0a0f912cc5424726adc50b37e9746055515dad38` / same |
| Causal before (engine) | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| Causal after (engine) | `b4682d0fdebaa691b55bb29b32f3499781a8fc04` |
| `STOP-15CB-02` record | `docs/pr-artifacts/pr-15c-b/decisions.md` (retained unedited) |
| Frozen scripts vs `origin/main` | identical for `validate-pr15b.py`, `run-pr15b.sh`, `profile-pr15b.sh`, `test-scripts.sh` |
| Baseline self-tests | `validate-pr15b.py self-test` → `SELF-TEST OK`; `test-scripts.sh` → 62 passed / 0 failed |

### Anchor verification

| Anchor | Observed |
|---|---|
| `profiler_status`/`profiler_evidence` acceptance rule | present at lines 310–315, unchanged |
| `"profiler_evidence": None,` occurrences | **2**: line 399 inside `build_trial` (eligible) and line 609 inside `synthetic_trial` (self-test fixture, deliberately untouched) |
| `--profiler-evidence` on the `trial` parser | absent (0 occurrences) |
| Discovery (`profiler_paths` → `profiler_status`) | present at lines 362–368, unchanged |
| Anchor `trial.add_argument("--correctness-passed", action="store_true")` | present, unique (line 764) |
| Runner evidence machinery | **absent** — the fixup plan's "already prepared" assumption did not hold. The runner was authored fresh against §3's exact algorithm; nothing pre-existing was overwritten. |

Rules exercised at S0: X01 (anchors match), X03 (local branch, no remote PR
inferred), X04 (one eligible assignment, flag absent).

## 2. Source and diff list

Executable changes (see `gates.md` for the tested head):

| File | Change |
|---|---|
| `benchmarks/scripts/validate-pr15b.py` | +7/−1: optional `--profiler-evidence` argument; `build_trial` assigns `args.profiler_evidence or None` |
| `benchmarks/scripts/run-pr15b.sh` | +123/−1: per-trial profiler capture → evidence record → independent re-verification → conditional CLI flag |
| `benchmarks/scripts/pr15cb-profiler-evidence.py` | new: `write`/`verify` for the evidence record |
| `benchmarks/scripts/test-scripts.sh` | +477: AR2-T01–T08 regression section |
| `.gitignore` | ignores `__pycache__/` and `*.pyc` |
| `benchmarks/scripts/__pycache__/validate-pr15b.cpython-312.pyc` | **removed from tracking** (accidentally added in `a9af8de`; absent on `origin/main`) |

Documentation: `decisions.md` (append-only A-R2 record),
`frozen-tooling-exception.md` (new), this file, and `acceptance.md` updates.

Unchanged: production `quervant-core`/`quervant-objectstore`/`quervant-distributed`
code, `Cargo.toml`, `Cargo.lock`, the CI workflow, `benchmarks/workloads`,
`benchmarks/datasets`, `benchmarks/reports`, `profile-pr15b.sh`,
`capture-pr07-env.sh`, `check-pr07-contention.py`, and the FST test-isolation
correction (already committed at `453bf73`).

## 3. Runner evidence flow as implemented

Per trial, after `cargo bench` exits **and** after the final contention sample:

1. `capture_profiler_evidence` tries `bash benchmarks/scripts/profile-pr15b.sh
   --mode perf --workload absent --out <trial>/profiler` (20 s, fixed), and on a
   nonzero exit tries `--mode heaptrack` with the same workload and interval.
   Both invocations are logged to `<trial>/profiler-capture.log` with their exit
   codes. No `sudo`, no installation, no kernel/sysctl change, no `PATH`
   manipulation, no forced process termination.
2. The winning candidate must yield a regular, non-symlink, non-empty primary
   artifact (`perf.data` plus `perf-report.txt` for perf; the `heaptrack*` data
   file for heaptrack). The tool version is read from `perf --version` /
   `heaptrack --version`.
3. `pr15cb-profiler-evidence.py write` records
   `schema/tool/version/workload/artifact_path/artifact_size_bytes/artifact_sha256/capture_command/capture_exit_code`
   plus the optional auxiliary (perf report) identity, atomically (`.json.tmp` →
   rename) at `<trial>/profiler/evidence.json`. `artifact_path` is trial-relative;
   no timestamp or machine path is stored.
4. `pr15cb-profiler-evidence.py verify` re-opens the JSON, re-stats and re-hashes
   the artifact, and rejects missing/malformed/symlinked/empty/mis-sized/
   mis-digested/out-of-trial evidence.
5. Only on success is `--profiler-evidence <trial>/profiler/evidence.json`
   appended to the existing `validate-pr15b.py trial` invocation. On any failure
   the flag is omitted, the reason is logged, and the unchanged validator rule
   decides `QUALIFIED` / `UNQUALIFIED`.
6. The validator still mints the trial manifest; the runner never does.
   `aggregate` is called exactly as before.

Timed-region safety: profiling starts only after the `cargo bench` process has
exited and after `contention-final.json` has been written, so it cannot overlap a
Criterion sample and cannot enter a contention attestation.

## 4. Regression tests (AR2-T01–T08)

All in `benchmarks/scripts/test-scripts.sh`. Synthetic inputs are labelled
`TEST FIXTURE`; none is published as benchmark evidence. The `--idle-confirmed`
flags used by the validator-contract cases are synthetic validator inputs, not an
attestation about this host.

| ID | Implemented assertion | Result |
|---|---|---|
| AR2-T01 | `AVAILABLE` + genuine evidence path → exit 0, serialised evidence equals the supplied path | PASS |
| AR2-T02 | `AVAILABLE`, flag omitted → exit 3, rejection text `AVAILABLE profiler status requires captured evidence` | PASS |
| AR2-T03 | `AVAILABLE` + `--profiler-evidence ""` → exit 3, evidence normalised to `null` | PASS |
| AR2-T04 | `UNAVAILABLE`, flag omitted → accepted, evidence `null` | PASS |
| AR2-T05 | Real runner: fake cargo emits the 30-lane Criterion tree, fake perf writes a real artifact → `evidence.json` written, `verify` passes, manifest carries the same path, only the idle reason remains; `aggregate` refuses the unqualified trial | PASS |
| AR2-T06 | Helper: missing / empty / symlinked / out-of-trial / invalid-JSON / empty-tool rejected. Runner: failed capture and incomplete perf output both leave `profiler_evidence = null` and `profiler_status = AVAILABLE`, and a synthetic idle attestation still leaves the trial rejected for missing evidence | PASS |
| AR2-T07 | `validate-pr15b.py self-test` and the whole script suite pass with no relaxed checks | PASS (103 passed / 0 failed) |
| AR2-T08 | Canonical digest unchanged, 30 unique lane IDs intact, `profile-pr15b.sh` byte-identical to `origin/main`, workload/dataset paths unmodified | PASS |
| Counterexample gate | Pre-patch parser rejects `--profiler-evidence` (exit 2) and cannot qualify on a profiler host (exit 3); patched parser accepts (exit 0); inverse patch round-trips byte-for-byte and the acceptance-rule region is identical | PASS |

Runtime of the full script suite: ~31 s (three throwaway `run-pr15b.sh
--trials 1` fixture runs with fake `cargo`/`git`/`perf`/`heaptrack`). Cleanup
removes exactly the run directory recorded in each run's `run_base=` line.

## 5. Coverage-race correction (retained)

The approved PR 15C-B FST test-only correction is present at `453bf73`:
`BUILD_INVOCATIONS` is a `#[cfg(test)] thread_local! Cell<u64>`, both preflight
tests and their `== 0` assertions are unchanged, and
`build_invocations_are_thread_local` is the deterministic cross-thread witness.
No test was disabled and the 85 % coverage floor was not changed.

## 6. Status of the gates

| Gate | Status |
|---|---|
| AR2 tooling tests (AR2-T01–T08) | **PASS** |
| Local quality gates (§6 command list) | **PASS** — see `gates.md` §9 |
| Coverage ≥ 85 % | **PASS** |
| Real RustFS | **BLOCKED-ENVIRONMENT** locally |
| Exact-head GitHub `rust`/`msrv`/`rustfs` | **PENDING** (agent cannot push) |
| Operator idle attestation | **NOT PROVIDED** → qualified trials **DEFERRED-ATTESTATION** |
| Qualified before/after comparison | **NOT EXECUTED** — correctly deferred |
| Reviewer acceptance / merge / roadmap DONE | **NOT GIVEN / NOT DONE** |

The six previously published diagnostic trials remain `UNQUALIFIED` under
`docs/pr-artifacts/pr-15c-b/trials/` and are not reclassified. Requalification
will be a fresh series on a clean tooling commit applied identically to both
engine sources.
