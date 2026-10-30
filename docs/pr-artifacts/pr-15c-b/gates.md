# PR 15C-B mandatory gates — command log

Status: **S2/S6 gate record.** Every row was executed locally on the host recorded
in `preflight.md`. Results are recorded verbatim from the command exit status and
tool output; no gate is claimed without a completed execution.

## 1. Tested state

| Item | Value |
|---|---|
| Branch | `dev/pr15c-b-performance-qualification` |
| Measured executable head ("after" source) | `b4682d0fdebaa691b55bb29b32f3499781a8fc04` |
| Executable tree (`HEAD^{tree}` at that commit) | `eb49bd4c36892bf77dc6860a604e970bcfb80cf8` |
| `crates/` subtree | `ad1a756c0ebc89344b55573da1fe00b7812c8ae9` |
| `benchmarks/` subtree | `56eaf9cff39eef5f5499be22a067bafc3f0f88f5` |
| Before source | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| Working tree during gate runs | clean except the untracked evidence directory |

Commits in the measured executable tree:

1. `453bf73` `fix(core): isolate the FST preflight build counter per thread`
2. `bd99596` `feat(bench): add strict PR 15C-B before/after comparator`
3. `b4682d0` `fix(bench): keep the comparator import from writing __pycache__`

## 2. Gate matrix

| # | Command | Topology | Exit | Result | Evidence |
|---|---|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | local | 0 | **PASS** | `target`-independent |
| 2 | `cargo +1.85.0 fmt --all -- --check` | MSRV | 0 | **PASS** | |
| 3 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | 0 | **PASS** | 0 warnings, 0 errors |
| 4 | `cargo clippy --workspace --all-targets -- -D warnings` | stable, default features | 0 | **PASS** | AGENTS.md gate |
| 5 | `cargo +1.85.0 check -p quervant-core` | MSRV | 0 | **PASS** | |
| 6 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | MSRV | 0 | **PASS** | |
| 7 | `cargo test --workspace --all-features` | local | 0 | **PASS** | 2173 passed, 0 failed, 75 ignored |
| 8 | `cargo +1.85.0 test --workspace --all-features` | MSRV | 0 | **PASS** | 2173 passed, 0 failed, 75 ignored |
| 9 | `cargo test --workspace --all-targets` | local, default features | 0 | **PASS** | 2169 passed, 0 failed, 10 ignored |
| 10 | `cargo test -p quervant-core --test pr15b_diagnostics` | local | 0 | **PASS** | 16 passed, 0 failed (`b_t01`–`b_t16`) |
| 11 | `cargo test -p quervant-core --test pr15c_a_segment_state` | local | 0 | **PASS** | 5 passed, 0 failed (`pr15c_a_t01`–`t05`) |
| 12 | `cargo test -p quervant-core --release --lib` | local, release | 0 | **PASS** | 840 passed, 0 failed, 1 ignored |
| 13 | `cargo doc --workspace --no-deps` | local | 0 | **PASS** | 0 warnings |
| 14 | `cargo doc --workspace --all-features --no-deps` | local, CI parity | 0 | **PASS** | 0 warnings |
| 15 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` (run 1) | local, coverage | 0 | **PASS** | lines **91.81 %** (51738 lines, 4236 missed) |
| 16 | same, run 2 (independent) | local, coverage | 0 | **PASS** | lines **91.81 %** (51738 / 4236) |
| 17 | same, run 3 (independent) | local, coverage | 0 | **PASS** | lines **91.81 %** (51738 / 4237) |
| 18 | `cargo test -p quervant-core --lib search::term_fst::tests::` | local | 0 | **PASS** | 16 passed, 0 failed |
| 19 | `cargo test -p quervant-core --lib index::snapshot::verified_state_cache::` | local | 0 | **PASS** | 38 passed, 0 failed |
| 20 | `python3 benchmarks/scripts/validate-pr15b.py self-test` | local | 0 | **PASS** | `SELF-TEST OK` |
| 21 | `python3 benchmarks/scripts/compare-pr15c-b.py self-test` | local | 0 | **PASS** | `COMPARATOR SELF-TEST OK` + 16 rejection classes |
| 22 | `bash benchmarks/scripts/test-scripts.sh` | local | 0 | **PASS** | 62 passed, 0 failed |
| 23 | `git diff --check` | local | 0 | **PASS** | CI whitespace gate |
| 24 | `cargo bench -p quervant-core --bench unified_diagnostics --no-run` | both worktrees | 0 | **PASS** | pre-built outside the timed region |
| 25 | GitHub Actions `rust` job (at final head) | CI | — | **NOT RUN — BLOCKED-EXTERNAL** | no push/credentials available to the agent |
| 26 | GitHub Actions `msrv` job (at final head) | CI | — | **NOT RUN — BLOCKED-EXTERNAL** | as above; MSRV gates 2/5/6/8 executed locally instead |
| 27 | GitHub Actions `rustfs` job (at final head) | real RustFS container | — | **BLOCKED-ENVIRONMENT** | no local `QUERVANT_RUSTFS_*` endpoint or RustFS service; not a PASS |

`cargo fmt`/coverage outputs: `/tmp/pr15cb-gates/{fmt,fmt-msrv,cov-run1,cov-run2,cov-run3}.log`
(ephemeral host paths; the commands are exactly those in the table).

## 3. Explicitly separated suites

The plan requires these not to be conflated. They were run and reported separately:

| Suite | Command | Result |
|---|---|---|
| Default-feature Cargo tests | `cargo test --workspace --all-targets` | 2169 passed / 0 failed / 10 ignored |
| All-features Cargo tests | `cargo test --workspace --all-features` | 2173 passed / 0 failed / 75 ignored |
| PR 15B oracle/diagnostics | `cargo test -p quervant-core --test pr15b_diagnostics` | 16 passed / 0 failed |
| PR 15C-A cache witnesses | `--test pr15c_a_segment_state` + `--lib index::snapshot::verified_state_cache::` | 5 + 38 passed / 0 failed |
| Coverage-instrumented tests | `cargo llvm-cov …` (3 runs) | all green, ≥ 85 % line floor met |
| Real RustFS | GitHub `rustfs` job | **not executed locally (BLOCKED-ENVIRONMENT)** |

The 75 all-features ignored tests are the `#[ignore]` real-service suites
(`pr13_s3_rustfs`, `pr13_proxy_rustfs`, `pr13_remote`, `pr13_oracle`,
`pr13_oracle_geo`, `m1_batches`, `m2_patches`, `m3_delete_by_query`,
`m5_mutation_qualification`, `pr13_remote_proxy`, `pr13_crash_rustfs`). They
require a live RustFS endpoint and were **not** silently skipped as a pass.

## 4. FST correctness-gate evidence (B-I06)

Three independent coverage-instrumented executions of the exact command from the
failed CI job
([run 40917513631, job 123601575771](https://github.com/yduchesne/quervant/actions/runs/40917513631/job/123601575771))
all passed, including:

```text
test search::term_fst::tests::build_invocations_are_thread_local ... ok
test search::term_fst::tests::preflight_fst_budget_one_over_prevents_build ... ok
test search::term_fst::tests::preflight_work_limit_prevents_build ... ok
```

Three green runs are evidence that the isolated counter works; they are **not**
presented as proof that the original failure was flaky (see `decisions.md`,
rule X09). The original failure mechanism is established from the source: a
process-global `AtomicU64` reset/asserted by two tests while unrelated parallel
tests called `TermFst::build` on other threads.

## 5. Benchmark harness gates (S3)

| Requirement | Evidence | Result |
|---|---|---|
| Two clean detached worktrees outside the editing tree | `/home/yduchesne/pr15cb-work/{before,after}` at `42b1944` / `b4682d0` | PASS |
| Native Linux filesystem | `ext4` on `/dev/sdd` for all three trees | PASS |
| Frozen runner used unmodified | `benchmarks/` subtree identical at `42b1944` and `b4682d0` (`git diff --stat` empty) | PASS |
| Canonical fixture digest re-checked by the runner before each series | `104d5ef0…` | PASS |
| Contention sampled pre/post/final on every trial | all `clear` (6/6 trials) | PASS |
| Correctness oracle gate before timing | `correctness_passed = true` (6/6) | PASS |
| 30 required lanes measured with `sample_size(20)`, 3 s warm-up, 5 s measurement | `lanes = 30` in every trial manifest | PASS |
| Operator idle attestation | **not given** — no human confirmation was available | **NOT SATISFIED** |
| Profiler-evidence rule of the frozen validator | **unsatisfiable on this host** (profiling tools installed, runner never records evidence) | **STOP-15CB-01** |
| A second reverse-order paired series | not executed | **NOT RUN** (optional per plan) |

## 6. Failure classification

| Observation | Classification | Basis |
|---|---|---|
| Historical CI failure `build_invocations() == 1` | **nondeterministic / test-only race in the pre-existing process-global counter** | source inspection proves an unguarded global touched by parallel tests; 3 coverage runs with the per-thread counter are green. The original failure was **not** reproduced in isolation, so it is **not** labelled "proven flaky". |
| All local gates green | — | no introduced regression detected by the gates |
| Qualified before/after aggregate unavailable | **environment/harness limitation** | frozen `validate-pr15b.py` requires `profiler_evidence` when a profiler is on `PATH`; the frozen `run-pr15b.sh` never records it (`STOP-15CB-01`) |

No gate was retried until green and no failure was discarded. Raw trial
directories, contention files, `env.txt`, Criterion raw data and profiler data
were preserved under each worktree's ignored `target/`.

## 7. Unresolved items

1. **STOP-15CB-01** — the frozen PR 15B runner/validator pair cannot emit a
   qualified aggregate on a host that has `perf`/`cargo-flamegraph`/`heaptrack`
   on `PATH`. The before/after assessment is therefore labelled
   `UNQUALIFIED`/`DIAGNOSTIC` in `comparison.md`.
2. No operator idle attestation was given, so the measured series is diagnostic
   even independently of (1).
3. GitHub CI (`rust`, `msrv`, `rustfs`) at the final head has **not** been run;
   the agent cannot push.

## 8. Final-head rerun (S6)

After the last source/script change and the evidence commit, the whole gate set was
executed again at head `4148e47bf4037358f8c82c9bb666e481e7bdf0c1`
(tree `8a86e42889b3f33152469148b930e3134715bb15`). No result is carried over from
an earlier run.

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo +1.85.0 test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo test --workspace --all-targets` | 0 | 2169 passed / 0 failed / 10 ignored |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | 16 passed / 0 failed |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | 5 passed / 0 failed |
| `cargo test -p quervant-core --release --lib` | 0 | 840 passed / 0 failed / 1 ignored |
| `cargo test -p quervant-core --lib search::term_fst::tests::` | 0 | 16 passed / 0 failed |
| `cargo test -p quervant-core --lib index::snapshot::verified_state_cache::` | 0 | 38 passed / 0 failed |
| `cargo doc --workspace --no-deps` | 0 | PASS, 0 warnings |
| `cargo doc --workspace --all-features --no-deps` | 0 | PASS, 0 warnings |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | **91.81 %** lines (51738 / 4236) |
| `python3 benchmarks/scripts/validate-pr15b.py self-test` | 0 | `SELF-TEST OK` |
| `python3 benchmarks/scripts/compare-pr15c-b.py self-test` | 0 | `COMPARATOR SELF-TEST OK` |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | 62 passed / 0 failed |
| `git diff --check` | 0 | PASS |

### Executable-content identity for the measured benchmark

The benchmark series was measured at `b4682d0…`; the final head differs only by
documentation plus a reporting-only change to the Python comparator. Verified:

```text
$ git diff --stat b4682d0 HEAD -- crates Cargo.toml Cargo.lock
(empty)
$ git diff --stat b4682d0 HEAD -- benchmarks
 benchmarks/scripts/compare-pr15c-b.py | 48 +++++++++++++++++++++++---------
```

So the measured release `unified_diagnostics` target, the workspace manifest, the
lockfile and every harness script the runner executes are byte-identical to the
measured commit. `compare-pr15c-b.py` is not invoked by `run-pr15b.sh`.

Comparator determinism was also verified: re-running `compare` on the same six
trial manifests reproduces `comparison.json` and `comparison.md` byte-for-byte.

### Recorded-state note (rule X28)

This section itself is a docs-only change, so the head SHA advances again without
altering `crates/`, `benchmarks/scripts/*` used by the runner, or `Cargo.lock`.
The executable-tree identity above is the authoritative link between the recorded
results and the final head. **GitHub `rust`, `msrv` and real-`rustfs` must still
run and pass at the final head before any merge decision.**

---

# 9. A-R2 gate set (profiler-evidence amendment)

Tested state: branch `dev/pr15c-b-performance-qualification`, head
`d2ce3ee42e5b03b4c22deabb64aa1663aa60629a` (tree
`d1d744992d06282c885d511e804434f35d3916cb`), `crates/` subtree
`ad1a756c0ebc89344b55573da1fe00b7812c8ae9` (identical to the measured engine
commit `b4682d0…`, so the FST and engine content is unchanged from §8),
`Cargo.lock` sha256 `83e73c8ea63a115a428690f869356df9dc38a31c06f9fc0a792cbd91fa07b789`.
Working tree clean apart from git-ignored `target/`.

## 9.1 Tooling and script gates

| Command | Exit | Result |
|---|---|---|
| `python3 benchmarks/scripts/validate-pr15b.py self-test` | 0 | **PASS** (`SELF-TEST OK`) |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | **PASS** — **104 passed, 0 failed** (was 62; +42 AR2 assertions) |
| `python3 -m py_compile benchmarks/scripts/validate-pr15b.py` | 0 | **PASS** |
| `bash -n benchmarks/scripts/run-pr15b.sh` | 0 | **PASS** |
| `bash -n benchmarks/scripts/profile-pr15b.sh` | 0 | **PASS** |
| `python3 benchmarks/scripts/compare-pr15c-b.py self-test` | 0 | **PASS** (`COMPARATOR SELF-TEST OK`, 16 rejection classes) |
| `python3 benchmarks/scripts/pr15cb-profiler-evidence.py --help` | 0 | **PASS** |
| `git diff --check` | 0 | **PASS** |

## 9.2 Rust workspace gates

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | **PASS** |
| `cargo +1.85.0 fmt --all -- --check` | 0 | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | **PASS** |
| `cargo +1.85.0 check -p quervant-core` | 0 | **PASS** |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | **PASS** |
| `cargo doc --workspace --no-deps` | 0 | **PASS**, 0 warnings |
| `cargo test -p quervant-core --lib` | 0 | 840 passed / 0 failed / 1 ignored |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | 16 passed / 0 failed |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | 5 passed / 0 failed |
| `cargo test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo +1.85.0 test --workspace --all-features` | 0 | 2173 passed / 0 failed / 75 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | **PASS — 91.81 % lines** (51738 lines, 4236 missed) |

The FST coverage-race witness ran green inside the instrumented suite
(`search::term_fst::tests::build_invocations_are_thread_local ... ok`,
`…preflight_work_limit_prevents_build ... ok`); no test was disabled and the
coverage floor was not changed.

## 9.3 Real capture-path validation (not a fake)

| Step | Command | Result |
|---|---|---|
| real heaptrack capture | `profile-pr15b.sh --mode heaptrack --workload absent --out <tmp>/profiler` | exit 0, `heaptrack.gz` 2 695 729 B |
| evidence write | `pr15cb-profiler-evidence.py write …` | exit 0, record with measured size and SHA-256 |
| evidence verify | `pr15cb-profiler-evidence.py verify …` | exit 0, `tool=heaptrack version='heaptrack 1.5.0'` |
| real perf capture | `profile-pr15b.sh --mode perf --workload absent …` | **exit 2** — `/usr/bin/perf` is the distro wrapper and cannot find a kernel-matched binary for `6.18.33.2-microsoft`. No `PATH`, kernel, package or privilege change was made, so the runner will honestly fall back to `heaptrack` on this host and record `perf` as a genuine capture failure. |

## 9.4 Service gate

| Gate | Result |
|---|---|
| Real RustFS (`cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1`) | **BLOCKED-ENVIRONMENT** — exit 101, `QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance: NotPresent`; no `QUERVANT_RUSTFS_*` variable is set, no container runtime is installed, and `http://127.0.0.1:9000/health` refuses the connection. Not a pass. |
| GitHub `rust` / `msrv` / `rustfs` at this head | **PENDING** — the agent cannot push |
| Operator idle attestation | **NOT PROVIDED** → qualified trials **DEFERRED-ATTESTATION** |

## 9.5 Benchmark status

No qualified benchmark was executed or labelled in this stage. All previously
published trials remain `UNQUALIFIED`. Rules X19 (profiler overlapping a timed
region), X20 (idle attestation), X23 (dirty measured worktree) and X24 (frozen
tooling divergence between the two sides) are the gates that keep a qualified
series withheld; none of them is currently satisfiable by the agent alone.

## 9.6 Final-head re-run (X28)

The last change before this section is
`3597efcf759d0546fbc7a7a32fc69fc0028dbd45` (`crates/` subtree
`ad1a756c0ebc89344b55573da1fe00b7812c8ae9`, `benchmarks/` subtree
`35f32e6f36bf3848ad29062c63fadfef662bf91d`).

The only file changed since the full §9.1–§9.2 run at `d2ce3ee…` is
`benchmarks/scripts/test-scripts.sh` (plus documentation). `git diff d2ce3ee HEAD
-- crates Cargo.toml Cargo.lock` is **empty**, so the fmt / clippy / MSRV / test /
doc / coverage results in §9.1–§9.2 remain attributable to the identical Rust
content.

Script-level gates were re-executed at `3597efc…`:

| Command | Exit | Result |
|---|---|---|
| `python3 benchmarks/scripts/validate-pr15b.py self-test` | 0 | **PASS** |
| `bash benchmarks/scripts/test-scripts.sh` | 0 | **PASS — 104 passed, 0 failed** |
| `python3 -m py_compile benchmarks/scripts/validate-pr15b.py` | 0 | **PASS** |
| `bash -n benchmarks/scripts/run-pr15b.sh` | 0 | **PASS** |
| `bash -n benchmarks/scripts/profile-pr15b.sh` | 0 | **PASS** |
| `python3 benchmarks/scripts/compare-pr15c-b.py self-test` | 0 | **PASS** |
| `git diff --check` | 0 | **PASS** |

This section itself is documentation-only, so `crates/`, `benchmarks/scripts/*`
used by the runner and `Cargo.lock` are unchanged by it. Exact-head GitHub `rust`,
`msrv` and `rustfs` are still required before any merge decision.

---

# 10. Qualified before/after series (operator attestation received)

Status: **QUALIFIED on both sides.** Details and interpretation:
`qualification.md`. Machine-readable report:
`benchmarks/reports/pr15c-b/pr15c-b-qualified-comparison.json`.

## 10.1 Pre-conditions

| Requirement | Evidence | Result |
|---|---|---|
| Operator idle attestation | supplied by the human operator; `--idle-confirmed` passed **by the operator's instruction**, not self-supplied | **SATISFIED** |
| Automated contention checks | 18/18 pre/post/final samples `clear` across 6 trials | **PASS** |
| Clean measured worktrees | both worktrees committed the identical tooling patch; `git status --porcelain` empty before each series | **PASS** |
| Identical tooling (X24) | `benchmarks/scripts/` SHA-256 identical in both worktrees (see `qualification.md` §1) | **PASS** |
| Frozen workload/corpus unchanged (X26) | canonical digest `104d5ef0…`; 30/30 lanes; `git diff f7d6be7 04ad350 -- benchmarks workloads Cargo.lock` empty for workloads and lockfile | **PASS** |
| Criterion settings unchanged | `sample_size(20)`, 3 s warm-up, 5 s measurement, `Throughput::Elements(1)` — enforced by the unmodified bench target and validator | **PASS** |
| Profiler evidence present on every qualified trial | six verified `evidence.json` records; `profiler_status = AVAILABLE` | **PASS** |
| `--allow-contended` never used | absent from both invocations | **PASS** |

## 10.2 Executions

| Series | Command | Window (UTC) | Exit | Trials qualified |
|---|---|---|---|---|
| A — before `f7d6be7…` | `bash benchmarks/scripts/run-pr15b.sh --trials 3 --idle-confirmed` | 00:10:28 → 00:31:52 | **0** | **3/3** |
| B — after `04ad350…` | `bash benchmarks/scripts/run-pr15b.sh --trials 3 --idle-confirmed` | 00:31:55 → 00:49:21 | **0** | **3/3** |
| Strict comparison | `compare-pr15c-b.py compare …` | — | **0** | `status = QUALIFIED` |

Both aggregates were re-derived with the frozen `validate-pr15b.py aggregate` from
the six published trial manifests and were **byte-identical** to the runner output.

## 10.3 Result

`QUALIFIED`: **13 improvement / 0 regression / 17 inconclusive** of 30 lanes; no
lane regressed; smallest effect 1.81×, largest 64.2×. The 17 `INCONCLUSIVE` labels
come from the predeclared 1.10× dispersion heuristic on the before side (spreads up
to 1.205×) and are explained in `qualification.md` §6. No significance claim is
made.

## 10.4 Preserved artifacts

| Artifact | Location | Tracked |
|---|---|---|
| Both qualified aggregates (+ rendered md) | `benchmarks/reports/pr15c-b/{before,after}/` | yes (216 KB total) |
| Six qualified trial manifests | same | yes |
| Six profiler-evidence records | same (`evidence-trial-*.json`) | yes |
| Comparison JSON / md | `benchmarks/reports/pr15c-b/pr15c-b-qualified-comparison.json`, `docs/pr-artifacts/pr-15c-b/comparison-qualified.md` | yes |
| Raw Criterion trees, `perf.data`/`heaptrack.gz`, capture logs | `<worktree>/target/pr15b/<stamp>-<sha>/trial-N/` | no (ignored) |
| Earlier **unqualified** diagnostic series | `docs/pr-artifacts/pr-15c-b/trials/`, `comparison.md` | yes, unchanged |

Nothing was overwritten and no earlier result was relabelled.
