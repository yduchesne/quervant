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
