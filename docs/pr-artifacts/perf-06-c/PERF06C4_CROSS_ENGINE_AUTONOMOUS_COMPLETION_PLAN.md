# PR #133 — Autonomous completion of the PERF06-C4 comparative benchmark

**Task:** `PERF06_C4_CROSS_ENGINE_AUTO`  
**Repository / branch / existing PR:** `yduchesne/quervant` / `dev/perf06-c4` / [#133](https://github.com/yduchesne/quervant/pull/133)  
**Reviewed starting head:** `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b`  
**Plan authored:** 2026-11-27, America/Los_Angeles  
**Primary deliverable:** acquire and report the full 16-lane warm Quervant/Tantivy/Lucene comparison and the native serial-throughput windows. Reuse the already-completed cold study as a separate historical result.

## 1. Execution authorization — proceed without another approval

**The user's instruction authorizes the coding agent to execute this entire plan. Do not ask for additional authorization or confirmation before applying the supplied patch, creating the new configuration, performing necessary release builds and index preparation, starting the prescribed new warm acquisition, analyzing its saved data, committing, pushing or updating the existing PR description.** Execute those steps continuously. A successful checkpoint is a reason to proceed, not to ask permission.

This plan explicitly authorizes **one new warm acquisition**, under the new fixed configuration identity in §6. It prospectively changes statistical A/A failure handling for that new study so the earlier failure cannot merely repeat the old approval dead end. A native A/A `FAIL` and informational host-load observations do not block its treatment or throughput phases. Every failed control remains visible. If any control fails, the acquired comparisons are exploratory and statistically unqualified; they must not be advertised as a qualified performance win.

The exact implementation, decisions, commands, result handling and reporting rules are supplied here. The coding agent does not design a replacement harness or choose another experiment. Unforeseen conditions outside §11 cause a **scoped STOP** and an evidence-based report; they do not confer permission to improvise. Finish independent safe reporting/publication work when its rule permits it. Do not turn a known A/A failure, unfavorable ranking, ordinary stage transition or CI activity into an authorization request.

### 1.1 User constraints retained

- Assume the host is idle and ready. Native CPU busy/steal observations remain informational; do not wait for a quiet period, repeat probes, retune the host or kill other work.
- Treat the C4 engine branch as stable. **Do not run unit or integration suites, fmt, Clippy, coverage, doctests, documentation builds, dependency audits, benchmark compile-only QA or script-test suites.** Do not add tests for this execution. Record them as `NOT RUN — USER-AUTHORIZED WAIVER`, never PASS.
- Native configuration validation, locked release builds needed to execute the benchmark, index construction, exact-result oracle checks, timed acquisition, saved-data reanalysis and rendering **are authorized operational steps**. They are not the waived general QA campaign.
- Preserve the original failed warm result and successful cold result. Do not rerun cold, edit old configurations/results, replace the first experiment, change its verdict or pool its samples with the new one.
- No production engine, adapter, corpus, query, scoring, sort, timer, sampling schedule, statistical estimator, threshold, dependency or workflow changes are allowed. Apply only Appendix A's four Python-file policy/presentation changes and six documentation corrections/updates.
- No merge, readiness toggle, baseline promotion, rollback, optimization tuning or request for review is authorized. Preserve the PR's observed readiness; it was DRAFT at review.

### 1.2 Supersession is precise

The original plan's one-attempt limit remains true for its original warm/cold UUIDs. This plan authorizes a **distinct new** warm configuration and one attempt for it; it does not resume or alter the old run. The original rule that made A/A failure binding is preserved by default and for every historical configuration. Only the new explicit `policy.aa_mode="advisory"` path changes continuation. This plan replaces the provisional documentation-only follow-up; no separate approval of that follow-up or of this new acquisition is needed.

## 2. Fresh-source facts and reconciliation

| Item | Verified review fact |
| --- | --- |
| Current PR head and remote branch | `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b`, OPEN, DRAFT, unmerged |
| Fresh main / PR base SHA | `f169fbba93e10d174cad8ab3bca55cdb7ae6aa03` |
| Original cross-engine measurement source | `0148aaaa922c398a0b8b33581e72918ad212e67f` |
| Original cross-engine plan SHA-256 | `e04a8fa61ed507a06ebf00f660c616b61a7000af1ef896c9012d31052b0840ce` |
| Authoring guide blob | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |

The author reconciled the pushed branch, report, exact policy diff, native configurations and saved data. The prior seven-line host-advisory extension is exactly as prescribed, and the original plan is verbatim. Independent offline reconstruction reproduced all 16 warm A/A comparisons, cold control/treatment statistics and bootstrap intervals. No benchmark or engine was run during authoring.

| Existing work | State | Plan treatment |
| --- | --- | --- |
| Stable C4 production engine and adapters | DONE + VERIFIED for this source review; general QA not repeated | Preserve source bytes. |
| Host-readiness advisory mode | DONE + VERIFIED | Reuse it; do not weaken native structural execution requirements. |
| Original warm A/A | DONE + VERIFIED | 768 rows, 15,360 timed samples, 3,840 warmups, 15 PASS / 1 FAIL; preserve. |
| Original warm treatment / throughput | NOT STARTED because the native A/A gate blocked them | Acquire the entire matrix in a new study under this explicit prospective policy. |
| Original cold comparison | DONE + VERIFIED | 48 control rows, 72 treatment rows, 2,400 fresh-process observations; reuse without reacquisition. |
| Original overall disposition | PARTIAL | Preserve `PERF06_CROSS_ENGINE_PARTIAL` in its historical report. |
| Report prose / roadmap links | PARTIAL | Fix the exact four groups below. |
| New warm study | NOT STARTED | Execute now under this plan, without another authorization step. |
| Maintainer adoption / merge | OPEN | Leave open. |

### 2.1 Observed corrections

| Fix | Finding | Fixed design |
| --- | --- | --- |
| F01 | Report §8 incorrectly associates positive gain with a slower competitor when ratio > 1. | State `gain = 100 * (1 - ratio)`; negative gain means the competitor is slower. Preserve correct numeric tables. |
| F02 | §6.1 calls 2.053 s lookup; §6.2 calls 0.783 s lookup. | Label them preparation totals and show real cache lookups: 0.111 s / 0.056 s. |
| F03 | Ledger wrongly attributes A/A-only failure to D14, unchanged main to D23, and no hook bypass to D27; D19 cites the wrong competitor as its trigger. | Keep applied D17/D18, use Quervant's loss to Tantivy for D19, and mark D14/D23/D27 checked but not triggered. |
| F04 | Two new roadmap result targets start `../../benchmarks/` from `docs/`. | Correct exactly those links to `../benchmarks/`. |

The old warm failure is `10000/absent/k10/warm`, gain −1.1399911064%, 95% gain CI [−24.7016487022%, +0.4340978130%]. Its interval violates the retained ±15% control condition; its point estimate does not. No causal host-load explanation is established. This new policy records future control failures rather than changing that threshold or retesting until one passes.

## 3. Fixed design and invariants

### 3.1 Public and serialized surface

Apply Appendix A literally. It adds `--aa-advisory` **only to `prepare`**, propagated through the existing `prepare_configuration` and `default_configuration` functions. The new optional field is:

```json
{"policy":{"aa_mode":"advisory"}}
```

Absent `aa_mode` or explicit `"required"` retains the current gate. Any other value is invalid. Advisory is accepted **only** for `family="cross-engine"` and `workload.regimes=["warm"]`; other families and process-cold reject it. There is no `stage` or `run` bypass flag. An unflagged newly created configuration omits the new field. The native validator remains authoritative; no separate JSON Schema or artifact format is introduced.

The new run records `context.aa_control_mode="advisory"`. After complete eligible control analysis, it records:

```json
{
  "controls": {
    "aa_gate": {
      "mode": "advisory",
      "status": "PASS",
      "failed_lanes": [],
      "continued_after_failure": false
    }
  }
}
```

For one or more actual native FAIL outcomes, `status` is `"FAIL"`, `failed_lanes` is the lexically sorted actual list, and `continued_after_failure` is `true`. This Boolean means the gate allowed continuation, **not** that treatment finished. A later error still yields `INCOMPLETE`. If the control never reaches an eligible complete decision, `aa_gate` is absent. Do not manufacture metadata afterward.

### 3.2 Control flow and presentation

1. Collect all native A/A samples and run the unchanged native analyzer.
2. For advisory continuation, require exactly the declared nonempty lane set, exactly AA2 as each lane's comparison, `kind="A/A"`, correct AA/AA2 roles, only fully computed PASS/FAIL statuses, all scheduled blocks retained and no exclusions.
3. A fully computed statistical FAIL is informational for continuation. Preserve the raw samples, analyses, decisions and intervals. Continue every prescribed treatment lane and the three throughput windows.
4. Unknown, missing, non-computable or incomplete control outcomes and source/build/cache/oracle/protocol/timer/process errors keep the existing error path. They do not become advisory.
5. After every acquisition phase finishes, any advisory FAIL forces top-level `INCONCLUSIVE`. All-PASS uses the unchanged native `_run_status`. Exceptions and interruption still yield `INCOMPLETE` with captured evidence. Native CLI exit 0 already covers INCONCLUSIVE; no exit-code change is needed.
6. Before treatment tables, the renderer prints the actual advisory decision, failed lanes and all native A/A lane gains/intervals. FAIL has a conspicuous exploratory/unqualified banner. Every advisory INCOMPLETE also shows native errors and an incomplete-acquisition warning, including failure after treatment analysis. Default-required rendering remains unchanged.

### 3.3 Outcome matrix — no approval branch

| Actual outcome | Native status | Agent action | Interpretation |
| --- | --- | --- | --- |
| Full control, treatment and throughput; 16 A/A PASS | COMPLETE | Analyze, report every lane, commit and publish automatically. | Completed acquisition with passing A/A controls; no adoption decision. |
| Full acquisition; at least one native A/A FAIL and all outcomes PASS/FAIL | INCONCLUSIVE | Analyze, report every lane and failed control, commit and publish automatically. | Completed **exploratory** acquisition; all treatment ratios/classifications/nominal CIs are unqualified. |
| Unfavorable or inconclusive treatment comparison but complete valid data | Native value unchanged | Report it and finish automatically. | Performance outcome, not an operational failure. |
| Operational/structural/oracle failure or interruption | INCOMPLETE | Preserve actual rows/errors; finish safe reporting and delivery; no new invocation. | Incomplete evidence; no full comparative claim. |
| Saved status, metadata or data contradict each other | Preserve actual result | STOP comparative acceptance; publish the precise discrepancy without editing evidence. | Verification failure, not a reason to reacquire. |

### 3.4 Invariant-to-acceptance map

| ID | Falsifiable invariant | Acceptance evidence / counterexample |
| --- | --- | --- |
| I01 | Production, adapters, corpus, query/sort semantics, timers, schedules and statistics are unchanged. | E02 exact patch and full changed-path review. A change in any protected source is a STOP. |
| I02 | Advisory is explicit, prospective and warm-only; defaults stay binding. | E02 literal patch inspection; E03 native config validation and inspector. A run-only override or old UUID edit fails. |
| I03 | Statistical FAIL never suppresses treatment in the new eligible path, and never becomes a fabricated PASS. | E04 actual phase execution; E05 control/raw/gate equality. Any COMPLETE result with failed A/A fails inspection. |
| I04 | Advisory does not suppress correctness or malformed-data failures. | Unchanged native collectors/oracles/analyzer exceptions plus exact guard patch; any injected/fake or skipped oracle path is forbidden. |
| I05 | All 16 lanes / 32 comparisons / 3 throughput windows are acquired and reported when acquisition completes. | E05 exact row inventories, native reanalysis and throughput predicates. Dropped absent lane, block or engine fails. |
| I06 | Original warm/cold artifacts and original execution identity remain immutable. | E01 anchors; E02/E06 whole-delta scope. No old sample, config or result rewrite. |
| I07 | Host observations and A/A FAIL do not introduce approval prompts, waiting loops or retries. | E04 command history and applied-rule ledger; one new invocation maximum. |
| I08 | Status and reporting distinguish acquisition, control qualification and delivery. | E05/E06 output matrix and terminal record; analysis presence alone is not completion. |

Before editing, record brief answers in the task note: why old treatment is absent; which precise failure can continue; which failure types remain fatal; what FAIL means for final status; expected row/sample/window counts; the three runtime identity fields; and why the original cold result is not rerun. The answers are fully specified above and below. A contradiction in real source follows the matrix; it does not require the agent to invent architecture.

### 3.5 Scope-specific correctness treatment

This changes no Rust API, codec, persistence protocol, concurrency model, cancellation implementation or storage format. Unit/integration/fault-injection/coverage acceptance is explicitly waived by the user, including for the small Python policy change; do not invent tests or claim comprehensive regression validation. The planned operational vertical slice is the real native corpus → index → commit/reopen → exact query/count/ordered-ID oracle → timed collection → native saved-data analysis. Native correctness checks remain required.

The patch's advisory-FAIL branch may or may not be exercised by the real new control outcome. If all controls pass, state that the fail-continuation branch was inspected but not observed in this acquisition; do not force a noisy run or add a synthetic benchmark. Saved-data reanalysis proves consistency with the unchanged analyzer, not an independent mathematical proof of that analyzer. The prior independent reconstruction is reusable review evidence, not a fresh test-suite execution.

## 4. Exact file scope and anchors

Appendix A changes exactly ten existing files: four Python files, four policy/reference documents, the old execution report's factual prose and two roadmap links. It includes all fixes; the agent must not author alternatives. The baseline and exact post-patch whole-file Git blobs are below. The roadmap may receive only the later append specified in §10 after acquisition; before that append its post-patch blob must match.

| File | START Git blob | Required post-patch Git blob |
| --- | --- | --- |
| `benchmarks/quervant_bench/lean/cli.py` | `77355a736d720767f2a5ef4db52b95bf825fbe9c` | `5a0c1bcc8a2f36ea70504fadca64292f0697e238` |
| `benchmarks/quervant_bench/lean/configuration.py` | `94dd172b2c866452dd52f2b9781654982d3a5101` | `6b45946db428c647b1977baed4ce2d9fc3bb4e44` |
| `benchmarks/quervant_bench/lean/runtime.py` | `2624e2406212fdc28757307ff0259943a87153ea` | `6a760945a27dd802b49a124c6a973f4ca7a6e3cb` |
| `benchmarks/quervant_bench/lean/reporting.py` | `43725fc2da76aa7230a3420ca641635b05dd058b` | `a035fd0d3d9ab180b7ef90cf82ca209882a431cb` |
| `benchmarks/BM10_README.md` | `ee057e88d78e28586ef64ad32cc4fbbe583bd79b` | `9b39506d2f33f067e10e96f567ce2f31f1cfc8ba` |
| `docs/BENCHMARK_CONFIGURATION.md` | `f0a25c26064c59a237361452fee207a2be21b458` | `4bd9f511017d9d6aadeb797768cb79208b71dcd5` |
| `docs/BENCHMARK_RESULT.md` | `3cc62e31aa504fdf35aeaf10a719ddda48f29ee3` | `40042f50721553e8951378d0d7277a6891e173f7` |
| `docs/BENCHMARKING.md` | `6c1fa5db0271004377483098580635b8f685907f` | `c101bdbbc9b87a9092a84cf35c969f3655103409` |
| `docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md` | `be465000438d0b00bb685eeab0d82b8460964765` | `58d94c6e61b2aab2d7a2db6231dda6679e5747c6` |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `98c5a2fc8e3de84108c29995aa8df154da407b22` | `87a1a4499fdb4e2fc5caae77f8523b512dbd23c0` |


Also add this supplied plan verbatim at `docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md`.

After the policy commit, the only new native configuration is the exact slug in §6, under `benchmarks/studies/cross-engine/warm/configurations/`. After measurement, the only new native result is its own result in the corresponding `results/` directory. Add one report at `docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_EXECUTION_REPORT.md` and one outcome paragraph to the roadmap. No other repository artifact or helper script is committed.

**Protected:** all `crates/**`, `benchmarks/pr15d/**` adapters/corpus/protocol, `lean/preparation.py`, `lean/statistics.py`, `lean/artifacts.py`, all tests, all existing configuration/result JSON, dependency files, toolchains, `.github/**`, `AGENTS.md`, the guide, architecture, original plans and every historical evidence file except the exact original-report prose correction. Every edit not explicitly enumerated is a STOP.

Temporary patch, helper, logs and reanalysis output belong under the new task's ignored target directory. Never delete or overwrite the earlier task's logs or caches. No broad `git add`, cleanup/reset, or global configuration change.

## 5. Part A — Select source, apply the patch and commit it

### 5.1 Admission and recovery first

Read this plan, repository `AGENTS.md`, and `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`. The user's explicit waiver and execution authorization govern this task. Fetch once, inspect status and PR metadata:

```bash
git fetch origin
git status --porcelain=v1 --untracked-files=all
git branch --show-current
git rev-parse HEAD origin/dev/perf06-c4 origin/main
gh pr view 133 --repo yduchesne/quervant --json state,isDraft,mergedAt,headRefName,headRefOid,baseRefName,url
```

For fresh execution, use START `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b` on `dev/perf06-c4`, PR #133, base main, open and unmerged. Preserve actual readiness. If the clean local matching branch is behind exact remote START, fast-forward with `git merge --ff-only origin/dev/perf06-c4`. If absent, create its tracking branch with `git switch --track -c dev/perf06-c4 origin/dev/perf06-c4`. A clean checkout on another branch may use `git switch dev/perf06-c4`. Never stash, reset, force-checkout, rebase or merge main. A disjoint untracked prior note, including `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt`, is left untouched.

If GitHub access is temporarily unavailable but exact START and the matching local branch are established, continue local work under D03 and defer metadata/publication. Main advancement alone does not change the chosen engine source or require approval. Unknown branch/source changes or conflicting tracked edits are D04.

**Recovery dispatch precedes every fresh command.** If the new task directory, exact configuration, result or attempt log exists, inspect it before creating or overwriting anything. A result or `warm-run.txt` means this new study has already been attempted. Reuse its saved evidence or wait on its known live process; never invoke `run` again. Recover `AUTO_EXECUTION` from its existing `execution-sha.txt`, or uniquely matching saved `context.source_revision` for publication only. Never replace it with current delivery HEAD. If its history is uncertain, STOP new acquisition and preserve/report. A known unstarted task may resume remaining exact setup steps under D06. Once `execution-sha.txt` exists, any remaining staging or unstarted acquisition requires current HEAD to equal that exact AUTO_EXECUTION. A documentation-only descendant may finish saved-data publication, but may not execute a new run under the old identity.

### 5.2 Fixed task variables

Use a Bash session at the repository root. `AUTO_PLAN_INPUT` is the actual local path of this supplied file; locating it is the only input substitution, not a design choice. Do not select an older similarly named plan.

```bash
set -euo pipefail
AUTO_ROOT=$(git rev-parse --show-toplevel)
cd "$AUTO_ROOT"
AUTO_START=0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b
AUTO_DOC=docs/pr-artifacts/perf-06-c
AUTO_LOG="$AUTO_ROOT/target/perf06c4-cross-engine-autonomous"
AUTO_SCRATCH="$AUTO_ROOT/target/bm10-perf06c4-cross-engine-autonomous"
AUTO_NAME=quervant-perf06c4-tantivy-lucene-lexical-sort-warm-aa-advisory
export PYTHONPATH="$AUTO_ROOT/benchmarks"
export RUSTUP_TOOLCHAIN=1.98.1
export AUTO_ROOT AUTO_START AUTO_DOC AUTO_LOG AUTO_SCRATCH AUTO_NAME
unset QUERVANT_PR15I_D3C_STRATEGY QUERVANT_PR15I_D3C_PREFILTER_PROFILE
mkdir -p "$AUTO_LOG" "$AUTO_SCRATCH" "$AUTO_DOC"
```

If either target directory is a symlink, STOP. Existing files must follow recovery rules, not be overwritten. Keep `errexit` for dependent setup/stage steps. An error stops that shell block so the matrix can classify it; it does not mean the agent should ask a routine confirmation question or abandon safe reporting. The acquisition command deliberately captures its exit through `if` below.

Use installed Python ≥3.11, Rust/Cargo 1.98.1 and JDK21. Record `python3 --version`, `rustc --version`, `cargo --version`, `java --version`, `git --version`, and `findmnt -T "$AUTO_SCRATCH" -n -o FSTYPE`. If Rust 1.98.1 alone is absent, one `rustup toolchain install 1.98.1 --profile minimal` is preauthorized before staging. Missing JDK21/Python/native filesystem/taskset/two physical cores is an operational dependency failure, not a load observation; follow D09 without choosing substitute versions.

Preserve normal PATH/caches/credentials. Detect unexpected compiler/JVM overrides (`RUSTFLAGS`, `CARGO_ENCODED_RUSTFLAGS`, compiler/linker/wrapper/profile settings, `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS`, `JDK_JAVA_OPTIONS`, `GRADLE_OPTS`, shadow Cargo configs). Report variable names only; do not dump secrets or silently clear unknown settings. Only the two historical strategy variables above are preauthorized removals. Native host checks handle actual execution capabilities; no separate load/temperature/soak loop is required or authorized.

### 5.3 Apply exactly and commit before staging

1. Compare the §4 START anchors using `git rev-parse "$AUTO_START:<path>"`. Copy this plan verbatim to `docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md`; if a destination already exists, require byte equality rather than overwriting another file. Record supplied/copy SHA-256 equality.
2. Extract Appendix A's single `diff` block, without fences, to `$AUTO_LOG/autonomous-completion.patch`. Extract Appendix B's single Python block to `$AUTO_LOG/warm_autonomous_inspect.py`. Do not commit extracted helpers.
3. Run `git apply --check "$AUTO_LOG/autonomous-completion.patch"`, then `git apply "$AUTO_LOG/autonomous-completion.patch"`. Verify every post-patch blob in §4 with `git hash-object -- <path>`. A mismatch is D07, not permission to use a similar patch.
4. Inspect the exact full delta. It must comprise only those ten files plus the supplied plan at this stage. No extra module, flag, configuration edit, test file or production change.
5. **Inspect Git hooks before invoking a commit.** If they only run the explicitly waived QA, D22 permits a per-command override. Unknown/security hooks must not be bypassed. Do not discover a QA hook by executing it first.
6. Stage exact paths and make the policy commit; no approval pause follows it:

```bash
git add -- benchmarks/quervant_bench/lean/cli.py benchmarks/quervant_bench/lean/configuration.py benchmarks/quervant_bench/lean/runtime.py benchmarks/quervant_bench/lean/reporting.py benchmarks/BM10_README.md docs/BENCHMARK_CONFIGURATION.md docs/BENCHMARK_RESULT.md docs/BENCHMARKING.md docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md docs/PERF_OPTIMIZATION_ROADMAP.md docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md
git commit -m "bench: allow prospective advisory A/A for full warm acquisition"
```

The commit is necessary because native preparation refuses dirty runner/build inputs. Do not push yet or run concurrent builds/tests; the normal delivery push follows acquisition. Do not change the policy after seeing any new timing data.

## 6. Part B — Create and freeze one new configuration

### 6.1 Fixed name, one-time creation and native validation

The **only** new name is `quervant-perf06c4-tantivy-lucene-lexical-sort-warm-aa-advisory`. Search native configuration files for this exact name before calling `prepare`; native names are globally unique across dates. If present, use D06. Do not invent a suffix or generate a second UUID to evade the attempt boundary.

On the fresh path:

```bash
python3 -m quervant_bench prepare --family cross-engine --regime warm \
  --name "$AUTO_NAME" \
  --description 'Prospectively authorized post-C4 full warm comparison; host load and statistical A/A failures advisory; exact-result checks binding; all failed-control comparisons exploratory' \
  --readiness-advisory --aa-advisory > "$AUTO_LOG/config-path.txt"
AUTO_CONFIG=$(cat "$AUTO_LOG/config-path.txt")
export AUTO_CONFIG
python3 -m quervant_bench validate --config "$AUTO_CONFIG"
python3 "$AUTO_LOG/warm_autonomous_inspect.py" config "$AUTO_CONFIG"
```

Each command must succeed before its dependent command. Require one existing canonical configuration path from `prepare`; an empty/error output is not a path. Native validation prints `VALID`; the inspector prints `CONFIGURATION_MATCHES_FIXED_DESIGN`. Use the actual UTC date and UUID returned by native creation; do not backdate them or hand-edit the JSON.

The inspector compares against the protected original warm configuration. **Only name, description, UUID, creation timestamp and optional `policy.aa_mode="advisory"` differ.** Every other field, including readiness advisory, stays equal. A mismatch requires STOP; never alter generated fields to appease the checker.

### 6.2 Workload and frozen numbers

| Dimension | Exact value |
| --- | --- |
| Family/regime | cross-engine / warm |
| Treatment arms | Q production Quervant, T Tantivy 0.25.0, J Lucene 9.12.3; baseline Q |
| Control arms | AA and AA2, identical production Quervant baseline |
| Sizes | 10,000 and 100,000 documents |
| Classes | absent, rare, medium, common |
| Top-K | 10 and 100 |
| Lanes | All 16 size × class × K combinations |
| Query/answer | Exact keyword match, exact total hit count, UTF-8 lexical ascending `doc_id`, ordered first K IDs |
| Sort contract | `doc_id:keyword:utf8-lex-asc:v1` |
| Timed warm operation | `exact-term-search-plus-topk-projection` using native engine-reported nanoseconds |
| Build | release, locked; no experimental Quervant strategy feature; existing Gradle 8.14.3/JDK21 |
| Blocks / slots per arm | 12 / 2 |
| Warmups / samples per lane-slot row | 5 / 20 |
| Seed / bootstrap resamples | 20261122 / 10,000 |
| Minimum blocks / retained required | Native minimum 4; this campaign must retain all 12 |
| A/A threshold | Existing ±15% point/CI criterion, unchanged |
| Treatment gain/regression policy | Native zero thresholds, unchanged |
| Excluded blocks | `{}`; none |
| Host-readiness policy | Existing advisory, four 250 ms observations, thresholds 25% busy / 2% steal |
| New statistical control policy | `aa_mode="advisory"` |

The keyword oracle remains the native one: absent `key=never` has zero hits; rare `key=singleton` has one, `d00000000`; medium `group=medium` selects every eighth ID (1,250/12,500 hits); common selects positive even IDs (4,999/49,999 hits). IDs use `d` plus eight decimal digits. Verify full hit count and full ordered K-ID list through the existing native oracle. Do not add scores or require cross-engine BM25 equality.

The native schedule remains unchanged. Canonical saved JSON orders treatment arms J,Q,T; use the existing scheduler and seed. Never hand-sort or reschedule slots. The estimator remains slot median → mean of two slot medians per arm/block → median of paired competitor/Q block ratios; whole-block bootstrap uses existing Decimal precision, seed derivation and percentile rules.

Expected full inventory:

| Phase | Rows/windows | Timed queries | Warmup replies |
| --- | ---: | ---: | ---: |
| A/A | 768 lane-slot rows | 15,360 | 3,840 |
| Q/T/J treatment | 1,152 lane-slot rows | 23,040 | 5,760 |
| Native throughput | 3 windows | 300 total, 100/engine | 15 total, 5/engine |

Treatment produces **32 paired latency comparisons and 48 absolute lane/arm summaries**. Throughput uses only `10000/medium/k10/warm`; its three serial windows are descriptive, include JSONL round trips and exclude process startup/open. They do not have paired confidence intervals or represent saturated concurrent throughput. Native warm latency excludes process startup, index opening, index construction and JSONL transport; no timing boundary is changed.

### 6.3 Execution identity

Commit only the new configuration, then freeze the actual revision used by native builds/run:

```bash
git add -- "$AUTO_CONFIG"
git commit -m "bench: specify autonomous full warm comparative acquisition"
AUTO_EXECUTION=$(git rev-parse HEAD)
export AUTO_EXECUTION
set -o noclobber
printf '%s\n' "$AUTO_EXECUTION" > "$AUTO_LOG/execution-sha.txt"
set +o noclobber
```

If that exclusive write refuses an existing file, stop this fresh block and use recovery; never overwrite or ignore the original identity. Before staging, inspect START..AUTO_EXECUTION: only Appendix A, this plan and the exact new configuration may differ. `crates/**`, adapters, `preparation.py`, `statistics.py`, `artifacts.py`, dependencies, workflows and all historical JSON must be identical. Record the source-scope result. Keep HEAD/environment unchanged through staging and acquisition.

## 7. Part C — Native preparation, then proceed immediately

On the fresh path, require `stage.txt` absent and preserve it once created:

```bash
set -o noclobber
python3 -m quervant_bench stage --config "$AUTO_CONFIG" --scratch-root "$AUTO_SCRATCH" > "$AUTO_LOG/stage.txt" 2>&1
set +o noclobber
```

Only if D11's precise interrupted-stage conditions hold, retain that first log and execute the single authorized retry using this fixed, distinct destination:

```bash
set -o noclobber
python3 -m quervant_bench stage --config "$AUTO_CONFIG" --scratch-root "$AUTO_SCRATCH" > "$AUTO_LOG/stage-retry-01.txt" 2>&1
set +o noclobber
```

An existing retry log refuses execution; no second retry is allowed. Keep `errexit` active so either a redirection refusal or native stage failure stops that shell block before any dependent acquisition. Record both observed command outcomes. Do not reuse or overwrite `stage.txt`. A known successful prior stage is reused through native cache validation rather than rerun merely to regenerate a log.

Require exit 0 and native `PREPARATION=BUILT` or `PREPARATION=HIT`, key, timestamp and phase durations. Either legitimate native state is acceptable. The new config/source identity may require fresh release builds, six indexes and 48 untimed lane/engine oracle validations. These are required inputs to the requested benchmark and are authorized. Do not mislabel them as general QA.

Only use native cache validation/reuse. No old cache substitution, index copying, fake HIT, completed-cache deletion or edited cache manifest. The new run will validate the same prepared oracles again before timing. A successful stage proceeds automatically to §8, even if host diagnostics are busy/unavailable. One retry of a genuinely interrupted, incomplete **untimed stage** is allowed under D11; that does not authorize an acquisition retry.

## 8. Part D — Run the full new warm campaign once

Before the run, require no result for the new configuration UUID, no `$AUTO_LOG/warm-run.txt`, and no `$AUTO_LOG/warm-run-exit.txt`. Existing/uncertain attempts follow D14. Record the intended configuration and AUTO_EXECUTION before launch. Use one native invocation:

```bash
if [[ -e "$AUTO_LOG/warm-run-exit.txt" || -L "$AUTO_LOG/warm-run-exit.txt" ]]; then
  printf '%s\n' 'D14: prior exit receipt exists; use recovery, do not launch.' >&2
  exit 1
fi
set -o noclobber
if exec {AUTO_RUN_LOG_FD}> "$AUTO_LOG/warm-run.txt"; then
  set +o noclobber
else
  set +o noclobber
  printf '%s\n' 'D14: exclusive attempt-log creation failed; no new native invocation.' >&2
  exit 1
fi
if python3 -u -m quervant_bench run --config "$AUTO_CONFIG" --scratch-root "$AUTO_SCRATCH" >&"$AUTO_RUN_LOG_FD" 2>&1; then
  AUTO_RUN_EXIT=0
else
  AUTO_RUN_EXIT=$?
fi
exec {AUTO_RUN_LOG_FD}>&-
set -o noclobber
if printf '%s\n' "$AUTO_RUN_EXIT" > "$AUTO_LOG/warm-run-exit.txt"; then
  set +o noclobber
else
  set +o noclobber
  printf '%s\n' 'Exit receipt could not be written exclusively; preserve the actual run/result and use D18.' >&2
fi
```

The log file descriptor is created exclusively **before** Python can launch. If that open fails, do not assign a native exit status or write an exit receipt. An existing log is **not** a new native outcome. If the process ran but its exit receipt cannot be published, preserve the actual command exit in the terminal record and recover the saved result; never overwrite an older receipt or reacquire. Do not overwrite the log with `>|`, remove it or choose another name. Find the original attempt under D14. If the tool returns a live session, keep waiting on **that same process**, with progress updates; do not relaunch because output is quiet or an arbitrary polling window elapsed. Native per-operation timeouts stay unchanged.

Do not run builds, tests, another benchmark, a profiler or compression concurrently with acquisition. No manual thermal/wait loop or control-only rehearsal. A/A FAIL automatically proceeds through native treatment and throughput; the agent must not stop or ask permission on seeing it. A significant slowdown also does not stop work.

| Native exit/result | Required continuation |
| --- | --- |
| Exit 0, COMPLETE | Inspect all data; report and deliver. |
| Exit 0, INCONCLUSIVE after advisory FAIL | Inspect the **entire** acquisition, including throughput; report all values as exploratory and deliver. This is not an approval request or retry condition. |
| Exit 4, saved INCOMPLETE | Preserve exact diagnostic and actual rows; finish safe rendering/report/delivery. No new invocation. |
| Exit 2, abrupt termination, missing result or unexpected error | Preserve logs/state; STOP new timing; complete safe reporting with the exact blocker. |
| Result published but rendering/delivery failed | Repair only from that saved result; never reacquire. |

There is one new invocation total, not one per A/A outcome. No cold run or second throughput command. Nothing in this plan permits retry-until-green, retuning, pruning an absent lane, changing blocks/samples or threshold changes after observation.

## 9. Part E — Read-only inspection and complete tables

Select the result from the single `RESULT_JSON=` line emitted in the attempt log. If that line is unavailable after a publication/rendering failure, identify the **unique** native result matching the new configuration UUID/name and AUTO_EXECUTION. Zero/multiple candidates require the explicit recovery/STOP rule; never choose by latest timestamp alone.

Set `AUTO_RESULT` to that exact native path. Do not edit or copy-over the JSON. For a COMPLETE or INCONCLUSIVE result:

```bash
python3 -m quervant_bench analyze --result "$AUTO_RESULT" > "$AUTO_LOG/treatment-analysis.json"
python3 -m quervant_bench report --result "$AUTO_RESULT" > "$AUTO_LOG/native-report.md"
python3 "$AUTO_LOG/warm_autonomous_inspect.py" result "$AUTO_CONFIG" "$AUTO_RESULT" "$AUTO_EXECUTION" "$AUTO_LOG/treatment-analysis.json" > "$AUTO_LOG/inspection.md"
```

Require native reanalysis exit 0 and byte-parsed JSON equality with stored analysis. Appendix B also reanalyzes controls using the native analyzer, checks exact inventories, policy, source/build context, metadata, throughput and table orientation. Its successful exit is **0 for both full accepted acquisition cases**; it prints either `ACQUISITION_COMPLETE_AA_PASS` or `ACQUISITION_COMPLETE_AA_FAIL_EXPLORATORY`. The latter is a finished acquisition with failed statistical qualification, and delivery proceeds without permission.

For INCOMPLETE, run native `report` and Appendix B in a shell `if` so its expected exit 4 is captured. Do not run full treatment `analyze` on missing/partial data merely to manufacture a comparison. Appendix B's early incomplete branch does not read the analysis output path. Preserve that missing file as absent. It reports actual counts and errors; do not claim full validation passed. An inspector exit 2 is an actual inconsistency to report and STOP comparative acceptance, not an invitation to change its assertions or the result.

**Required tables in the new report:** all 16 A/A outcomes, all 32 T/Q and J/Q latency comparisons with Q/T/J absolute block medians, ratios, nominal 95% CIs, competitor gain, native label and qualification label; all three throughput windows; all six indexing/preparation metric rows. Copy generated tables from the inspector, not hand-recomputed numbers. Include actual missing phases if incomplete.

Ratios are competitor/Quervant. Ratio < 1 favors the competitor; ratio > 1 favors Quervant. Native gain is `100 * (1 - ratio)`. Positive gain and `IMPROVED` refer to the competitor. Keep point estimates and CIs exactly as computed, and use the paired ratio rather than dividing independently aggregated absolute medians. With any A/A FAIL, every displayed comparison is exploratory; a significant treatment CI does not repair the failed control. Do not select only passing control lanes to claim global qualification.

Readiness observations (including missing diagnostic entries) are disclosed without invalidating the run solely on that basis. Preparation totals and cache lookup fields are distinct. A cache HIT preserves earlier indexing timestamps; those descriptive costs are not timed query samples.

Do not invoke historical `compare`, estimate cumulative A+B+C gains, combine old cold and new warm data, or infer warm speed from cold components. The existing historical comparator can admit individual passing lanes of an INCONCLUSIVE run; this task deliberately makes no historical comparison or promotion claim.

## 10. Part F — Documentation and delivery, automatically

### 10.1 New report structure

Write only `docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_EXECUTION_REPORT.md`, using this fixed structure and observed substitutions:

1. **Disposition:** one of §12's measured states; native status; explicit acquisition-complete versus A/A qualification versus delivery status.
2. **Authorization/scope:** the user's no-further-authorization instruction; host assumed ready; both advisory modes predeclared; QA waiver. Exact Appendix A only; production/adapters/statistics protected.
3. **Identities:** START, fresh main observed, policy commit, configuration commit/AUTO_EXECUTION, configuration path/name/UUID/UTC date, result path/UUID/sequence, source/build revisions. Final remote SHA belongs in the terminal receipt, not a self-referential follow-up commit.
4. **Original review fixes:** F01–F04 and immutable old experiment references; old warm remains incomplete and old cold remains complete.
5. **Preparation:** actual BUILT/HIT, key/timestamp, six indexes, 48 oracle validations, operational build environment and phase fields; no fabricated cache outcome.
6. **Acquisition:** actual exit, one invocation, row/sample/warmup counts, all phases reached, failed controls and complete native errors if any.
7. **A/A table and interpretation:** all 16 lanes; exact mode/gate metadata; prominent exploratory warning if any FAIL.
8. **All latency comparisons:** generated 32 rows and 48 underlying absolute summaries; correct ratio/gain orientation and qualification label. If incomplete, state exactly what is absent.
9. **Native throughput:** all three windows, requests/warmups/wall/rate, descriptive scope; if absent/partial, actual state only.
10. **Index/host/phase observations:** six index metric rows; native host diagnostics informational; preparation total versus lookup correctly named.
11. **Acceptance / decisions / failures:** E01–E07 table with actual command outcomes, applied decision IDs only when triggered, checked-but-not-triggered separately, no waived QA PASS claim.
12. **Residual limits and delivery:** control qualification limits, one-host/workload scope, no general engine-superiority or baseline-promotion claim; cold result linked separately; readiness/merge preserved.

Append a new roadmap paragraph under the heading `## PERF06_C4_CROSS_ENGINE autonomous warm acquisition (<actual UTC result date>)`. It must name the new config/result and AUTO_EXECUTION, actual native status and A/A PASS/FAIL counts, whether full 32 comparisons/3 windows were captured, and the exact qualified/exploratory/incomplete interpretation. Link relative to `docs/` using `../benchmarks/...` and `pr-artifacts/...`. State that earlier results and the earlier C4 verdict remain unchanged. Do not mark an optimization accepted or baseline promoted.

### 10.2 Commit, push and PR-body update

After acquisition, only the single new result, the new report and the roadmap append may differ from AUTO_EXECUTION. All execution source/configuration blobs must remain identical. Make exact-path commits with the existing inspected hook policy:

```bash
git add -- "$AUTO_RESULT" docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_EXECUTION_REPORT.md docs/PERF_OPTIMIZATION_ROADMAP.md
git commit -m "bench: record autonomous warm comparative acquisition"
```

If no result was published, omit that path; report/log the real failure and commit only authorized prose. Do not invent an empty result. Unrelated untracked files are untouched.

Fetch/check the remote again before non-force push. Require remote START or the known task ancestor on a resumed path, and no conflicting remote advancement. Then:

```bash
git push origin HEAD:refs/heads/dev/perf06-c4
git ls-remote --heads origin refs/heads/dev/perf06-c4
gh pr view 133 --repo yduchesne/quervant --json state,isDraft,mergedAt,headRefName,headRefOid,baseRefName
```

Local final, remote branch and PR head must agree. Preserve readiness and unmerged state. Append exactly one new section to the existing PR body; preserve all existing sections and reread before writing to avoid overwriting concurrent edits. Use a temporary UTF-8 body file and `gh pr edit 133 --repo yduchesne/quervant --body-file <actual file>`, then read back and compare the intended body. No comment or review request is needed.

Ready-to-fill PR addition:

```text
## PERF06-C4 autonomous warm comparative acquisition

Executed the prospectively authorized full warm study with informational host
observations and explicit advisory A/A continuation. Production engine, adapters,
timers, workload, sampling and statistics are unchanged. The prior incomplete
warm and complete cold results remain immutable and separately identified.

- Execution source: <AUTO_EXECUTION>; configuration/result: <native identities>.
- Acquisition: <actual native status and full/partial counts>; one invocation.
- A/A: <PASS/FAIL counts and failed lanes>; <qualified/exploratory/incomplete wording>.
- Latency comparisons / throughput: <actual counts>; all outcomes reported.
- General QA: NOT RUN — explicit user waiver. Hosted CI is not a gate for this task.
- Report: <repository-relative new report link>.
- No merge, readiness change, optimization adoption or baseline promotion.
```

No additional approval is needed for this authorized delivery. If GitHub is unavailable, complete safe local work and report DELIVERY_BLOCKED under D21; never rerun measurements. Automatically triggered CI is left alone. Do not dispatch, wait for, rerun, cancel or edit CI to close this task.

## 11. Predesigned decision and exception matrix

AUTO means execute the exact action and continue; DEFER means finish explicitly independent work and record the blocked scope; STOP means halt the affected operation and preserve evidence. E = executor; M = maintainer/plan author for an unlisted future amendment. **There is no approval request in the normal or known-A/A-failure path.** Every applied row needs its actual trigger/evidence; merely inspecting a condition does not mean it fired.

| ID | Observable condition | Category | Authorized action | Forbidden action | Evidence / affected step / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Exact repository/START, existing open PR and matching branch | AUTO | Reuse branch/PR; preserve readiness; execute all steps. | New PR, readiness toggle, permission pause. | Refs/PR; E01; E. |
| D02 | Clean local matching branch absent or behind exact admitted remote | AUTO | Exact tracking/switch/fast-forward commands in §5. | Reset/stash/rebase/merge commit. | Status/ancestry; E01; E. |
| D03 | Remote metadata temporarily unavailable but exact local START/branch/source established | DEFER publication; continue local | Perform approved local patch/preparation/acquisition/report; verify remote/PR before any delivery. | Fabricate remote state or abandon independent local work. | Network error/local IDs; E01/E07; E. |
| D04 | Wrong/divergent source, conflicting dirty tracked files, closed/merged PR or unknown executable delta | STOP affected work | Preserve state; report exact conflict. | Absorb foreign edits, reset, pick a new base. | Diff/status/refs; E01/E02/E07; M. |
| D05 | Disjoint untracked old note outside build/task paths | AUTO | Leave it untouched; exact-path staging only. | Delete, read unrelated secrets, broad add. | Status/path; E01/E07; E. |
| D06 | Exact task patch/config already exists and recorded history proves no new acquisition began | AUTO resume only | Reuse exact files/UUID and skip completed commits; after execution identity exists, require HEAD equal AUTO_EXECUTION before any remaining stage/run. A later docs-only head permits publication only. | Duplicate config, regenerate date/UUID, empty commit, guessed identity. | Notes/paths/hashes; E02–E04; E. Uncertain attempt → D14. |
| D07 | Literal patch/helper/plan transcription error; or real source fails expected patch/hash | AUTO only for proven transcription; otherwise STOP | Restore exact supplied bytes and repeat affected non-timing check; stop substantive mismatch. | Alternative implementation or changing expected hashes. | Before/after mismatch; E02/E05; E/M. |
| D08 | Rust 1.98.1 absent before preparation | AUTO once | Minimal pinned rustup install in §5, then continue only if available. | Different compiler or dependency upgrade. | Install/version outcome; E03; E. |
| D09 | Essential JDK/Python/native filesystem/core/taskset capability missing, unknown build override, build failure | STOP dependent acquisition | Preserve diagnostic; finish safe report; no alternate toolchain design. | Retune/kill work, sudo changes, fake binaries, waived suite. | Native error/names only; E03/E04; M. |
| D10 | Host diagnostic clear/busy/unavailable/missing, including load above thresholds | AUTO | Disclose and continue immediately. | Approval request, wait/reprobe, fake clear, pruning or rerun. | Actual diagnostics; all acquisition; E. |
| D11 | Untimed stage interrupted; no completed-cache corruption; same source/config/environment; no acquisition yet | AUTO once | Repeat native stage once to the absent `stage-retry-01.txt`; preserve `stage.txt` and use native lock/incomplete-cache handling. | Delete complete cache, indefinite retry, repeat `run`. | Both stage outcomes; E03; E. |
| D12 | Complete cache invalid/corrupt, unsafe symlink or native cache refusal | STOP affected staging | Preserve exact diagnostic and report; no use of bad inputs. | Manual cache edit, fake HIT, deletion to force success. | Cache error; E03; M. |
| D13 | Full eligible A/A control has one or more native statistical FAILs | AUTO | Runtime continues full treatment and throughput; report all results exploratory; finish delivery. | Approval pause, FAIL→PASS, threshold change, pruning, new attempt. | Native controls/gate; E04/E05; E. |
| D14 | Result/log/live process or uncertainty shows the new configuration may already have been attempted | STOP new invocation; continue saved-data work | Wait on the known process or recover the unique saved result; no second run. | Change name/date/log or rerun because task restarted. | Process/log/UUID; E04–E07; E/M. |
| D15 | Oracle/sort/marker/source/protocol/timer error, incomplete or noncomputable control, subprocess failure/interruption | STOP that acquisition | Preserve actual result/log and finish safe reporting; one-attempt budget exhausted if invoked. | Substitute expected answers, fake boundary, suppress exception, retry. | Native error; E04–E06; M. |
| D16 | Full data but Quervant loses or treatment CI is inconclusive | AUTO | Report every value and finish automatically. | Treat unfavorable performance as harness defect or retune/repeat. | Saved comparisons; E05/E06; E. |
| D17 | New source/environment change after AUTO_EXECUTION is frozen | STOP dependent timing | Preserve state; use original source identity for saved-data reporting only. | Silent rebuild/restart or current-HEAD identity substitution. | Exact diff/context; E03–E05; M. |
| D18 | Saved result exists but rendering/analysis/report/publication failed | AUTO saved-data repair | Recover original identity; repeat only read-only render/reanalysis and authorized publication. | Another timing invocation or raw JSON rewrite. | UUID/context/error; E05–E07; E. |
| D19 | Saved-data inspector reports mismatch, unknown status, missing complete inventory or metadata contradiction | STOP comparative acceptance | Preserve evidence, report exact failed predicate and actual counts; finish honest delivery. | Modify helper/statistics/raw data to force acceptance, acquire again. | Inspector exit/diagnostic; E05/E06; M. |
| D20 | Main advances while chosen task source is unchanged | AUTO | Record new main SHA, continue selected-source work. | Rebase, repin or claim current-main engine. | Ref observation; E01/E07; E. |
| D21 | Push/PR access fails or remote advances unexpectedly | DEFER delivery | Finish local checks/report/commit; one retry of the same non-force publication is allowed only after read-only verification shows remote unchanged or already equals final. | Force push, overwrite concurrent work, repeat benchmark. | Errors/local/remote IDs; E07; E/M. |
| D22 | Hook inspected and proven to run only user-waived QA | AUTO for that commit | Use `git -c core.hooksPath=/dev/null commit ...` with the same planned message; record scope. | Global disabling or bypass of unknown/security/access-control hooks. | Hook text/waiver; commit; E. Unknown hook → STOP/M. |
| D23 | Ordinary automatic CI appears | AUTO | Leave it alone and finish; CI is not gated here. | Dispatch/wait/rerun/cancel/edit. | Only observed status; E07; E. |
| D24 | New report/PR-body wording has a mechanical transcription error, with raw data unchanged | AUTO | Correct prose from prescribed templates and native fields; repeat only affected document/readback checks. | New estimator, selective table, rewriting historical outcome. | Before/after prose; E06/E07; E. |
| D25 | Any unlisted condition or unresolved contradiction | STOP affected operation | Preserve evidence, identify exact file/command/invariant and smallest required amendment; safe reporting only. | Improvise or infer permission for a new design. | Exact impact; affected gate; M. |

Do not label a failure flaky, pre-existing or caused by load without evidence. Classify observed presentation defects, operational dependencies, measurement-control outcomes and source/implementation defects separately. No retry exists merely because a result is inconvenient. D11 permits only an interrupted untimed stage; D18 permits only saved-data recovery.

## 12. Acceptance, residual limits and terminal handoff

| Gate | Required evidence |
| --- | --- |
| E01 Source admission | Actual refs/status, baseline anchors, readiness preserved, existing artifacts intact. |
| E02 Fixed implementation | Appendix A exact before/after blobs and allowed paths; plan verbatim; no protected delta. This is source inspection, not claimed test execution. |
| E03 Inputs | New fixed configuration native-valid and inspector-equal; committed AUTO_EXECUTION; operational stage succeeded with correct source/env/oracles. |
| E04 Acquisition | At most one new native `run`; all actual phases/counts/statuses/errors reported. A/A FAIL does not block this gate if full acquisition finishes. |
| E05 Saved-data acceptance | Appendix B exit 0 for full PASS or full exploratory FAIL; exact native reanalysis, all inventories and throughput. INCOMPLETE remains incomplete; mismatch remains blocked. |
| E06 Reporting | F01–F04 fixed; every required table or explicit missing phase; qualified/exploratory distinction; QA not claimed; original cold reused separately. |
| E07 Delivery | Non-force remote/PR identity matches local final; PR-body append read back exactly; readiness/unmerged state preserved. |

Separate these outcomes: implementation, acquisition completion, statistical-control qualification, delivery and maintainer adoption. A full A/A-failed acquisition may complete this **execution** task with E05 PASS while its statistical qualification is FAIL and its native top status is INCONCLUSIVE. Never equate that with failed or missing measurement, and never equate it with qualified performance evidence.

Residual limits to state: one host and fixed exact-keyword/string-sort workload; no general search-engine superiority; no BM25 relevance parity claim; throughput is one serial window per engine; A/A pass is not proof of a noise-free host; any failed A/A makes all new treatment estimates exploratory; actual response payloads are not saved beyond oracle flags; source inspection/native runtime establishes that ordered IDs/counts were checked; waived suites were not executed. Old cold means fresh process, not flushed OS page cache, and is not pooled with warm.

Terminal format:

```text
REPO / BRANCH / PR / STATE / READINESS / MERGED
  yduchesne/quervant / dev/perf06-c4 / #133 / <observed> / <preserved> / <observed>
START / POLICY_COMMIT / AUTO_EXECUTION / FINAL / REMOTE_VERIFIED
  0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b / <actual> / <actual> / <actual> / <actual>
PLAN_SHA256 / SOURCE_SCOPE
  <supplied/copy equal> / exact Appendix A; protected engine/adapters/statistics unchanged
NEW_CONFIG / UUID / NEW_RESULT / UUID / SEQUENCE
  <native actual identities>
INVOCATIONS / EXIT / NATIVE_STATUS
  <0 or 1> / <actual> / <actual or not reached>
COUNTS
  AA rows/samples/warmups=<actual>; Q/T/J=<actual>; throughput=<actual>
AA_CONTROL
  <PASS/FAIL counts; sorted failures; advisory metadata>
ACQUISITION / QUALIFICATION
  <complete/incomplete> / <AA_PASS or AA_FAIL_EXPLORATORY or NOT_ESTABLISHED>
OLD_EVIDENCE
  Original warm INCOMPLETE and cold COMPLETE unchanged; cold not rerun
E01..E07 / F01..F04
  <individual actual statuses and evidence>
QA / HOST
  NOT RUN — USER-AUTHORIZED WAIVER / observations informational, no load gate
APPLIED RULES / FAILURES / RESIDUAL LIMITS
  <actual triggers only; include every blocker>
DISPOSITION
  PERF06_CROSS_ENGINE_WARM_ACQUIRED_AA_PASS
  or PERF06_CROSS_ENGINE_WARM_ACQUIRED_AA_FAIL_DESCRIPTIVE
  or PERF06_CROSS_ENGINE_WARM_ACQUISITION_INCOMPLETE
  or PERF06_CROSS_ENGINE_AUTONOMOUS_INPUT_BLOCKED
DELIVERY_STATUS
  DELIVERED or LOCAL_COMPLETE_DELIVERY_BLOCKED or STOPPED
REPORT
  docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_AUTONOMOUS_EXECUTION_REPORT.md
```

The first two dispositions require full E05 acceptance; the second is equally eligible for automatic task delivery and does not need further authorization. Report actual source final/remote in the terminal receipt without another self-referential commit. Maintainer review/merge remains open, not a prerequisite to finishing this already-authorized benchmark task.

## 13. Reviewer checklist and source references

- [ ] No permission checkpoint was inserted into normal execution or expected A/A failure handling.
- [ ] Fixed patch/default compatibility/warm-only mode and raw-control preservation match §3.
- [ ] The new configuration is distinct and immutable; no original outcome was changed.
- [ ] All protected engine/adapter/timer/statistics inputs are unchanged.
- [ ] Native configuration, real preparation/oracles, one invocation and full saved-data checks actually ran when prerequisites allowed.
- [ ] Full comparisons and throughput are present or their absence is explicit.
- [ ] Any A/A failure is visible in native metadata, report banner, all comparative interpretation and terminal qualification status.
- [ ] Old cold was not repeated or pooled; no unpaired historical claim was introduced.
- [ ] Tests/lints/coverage/CI gates were not run or claimed PASS.
- [ ] The decision ledger records triggered rules only; all unresolved failures are disclosed.
- [ ] Delivery is verified without force, readiness change, merge or promotion.

Authoring sources (immutable): [guide on reviewed main](https://github.com/yduchesne/quervant/blob/f169fbba93e10d174cad8ab3bca55cdb7ae6aa03/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md); [original plan](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_DETAILED_EXECUTION_PLAN.md); [original report](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md); [runtime](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/benchmarks/quervant_bench/lean/runtime.py); [configuration](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/benchmarks/quervant_bench/lean/configuration.py); [statistics](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/benchmarks/quervant_bench/lean/statistics.py); [result contract](https://github.com/yduchesne/quervant/blob/0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b/docs/BENCHMARK_RESULT.md).

## Appendix A — Exact policy, presentation and documentation patch

Apply the complete block once. It is the design, not an example. Do not add a second implementation or alter it after seeing the new benchmark outcome.

```diff
--- a/benchmarks/quervant_bench/lean/cli.py
+++ b/benchmarks/quervant_bench/lean/cli.py
@@ -41,6 +41,8 @@
                       help="full immutable Quervant Git commit for the single perf-05 arm B")
     make.add_argument("--readiness-advisory", action="store_true",
                       help="perf-06 and cross-engine: preserve actual host load observations without using them as an acquisition gate")
+    make.add_argument("--aa-advisory", action="store_true",
+                      help="cross-engine warm only: preserve A/A FAIL outcomes and continue exploratory acquisition")
     make.add_argument("--studies-root", type=Path, default=repo_root() / "benchmarks" / "studies",
                       help="root for family/regime studies (must be named studies)")
     stage = sub.add_parser("stage", help="build and validate reusable inputs, WITHOUT benchmark acquisition")
@@ -74,7 +76,8 @@
                                         baseline_revision=args.baseline_revision,
                                         candidate_revision=args.candidate_revision,
                                         quervant_revision=args.quervant_revision,
-                                        readiness_advisory=args.readiness_advisory))
+                                        readiness_advisory=args.readiness_advisory,
+                                        aa_advisory=args.aa_advisory))
         elif args.action == "validate":
             validate_configuration(load_configuration(args.config))
             print("VALID")
--- a/benchmarks/quervant_bench/lean/configuration.py
+++ b/benchmarks/quervant_bench/lean/configuration.py
@@ -49,10 +49,13 @@
                           baseline_revision: str | None = None,
                           candidate_revision: str | None = None,
                           quervant_revision: str | None = None,
-                          readiness_advisory: bool = False) -> dict[str, Any]:
+                          readiness_advisory: bool = False,
+                          aa_advisory: bool = False) -> dict[str, Any]:
     """Generate one *new* immutable configuration with its own UUID."""
     if readiness_advisory and family not in ("perf-06", "cross-engine"):
         raise ArtifactError("advisory host readiness is supported only for perf-06 and cross-engine")
+    if aa_advisory and (family != "cross-engine" or regime != "warm"):
+        raise ArtifactError("advisory A/A is supported only for cross-engine warm")
     if family not in ("retained-key", "cross-engine", "perf-02", "perf-05", "perf-06"):
         raise ArtifactError("family must be retained-key, cross-engine, perf-02, perf-05 or perf-06")
     if regime not in ("warm", "process-cold") or (family != "cross-engine" and regime != "warm"):
@@ -77,6 +80,8 @@
                             "max_busy_percent": 25, "max_steal_percent": 2}}
     if readiness_advisory:
         policy["readiness"]["mode"] = "advisory"
+    if aa_advisory:
+        policy["aa_mode"] = "advisory"
     if family == "retained-key":
         arm_settings = {"A": {"engine": "quervant", "mode": "BASE", "source": "baseline"},
                         "L": {"engine": "quervant", "mode": "linear", "source": "current"},
@@ -275,6 +280,11 @@
             raise ArtifactError(f"policy.{field} must be a finite nonnegative number")
     if policy.get("control_arms") != []:
         raise ArtifactError("A/A is a separate control phase, not a treatment arm")
+    aa_mode = policy.get("aa_mode", "required")
+    if aa_mode not in ("required", "advisory"):
+        raise ArtifactError("unsupported A/A control mode")
+    if aa_mode == "advisory" and (family != "cross-engine" or workload["regimes"] != ["warm"]):
+        raise ArtifactError("advisory A/A is supported only for cross-engine warm")
     readiness = policy.get("readiness")
     if not isinstance(readiness, dict):
         raise ArtifactError("policy.readiness must be a declared object")
@@ -333,11 +343,13 @@
                           baseline_revision: str | None = None,
                           candidate_revision: str | None = None,
                           quervant_revision: str | None = None,
-                          readiness_advisory: bool = False) -> Path:
+                          readiness_advisory: bool = False,
+                          aa_advisory: bool = False) -> Path:
     """Create under studies/<family>/<regime>/configurations automatically."""
     config = default_configuration(family, name, description, regime=regime,
                                    baseline_revision=baseline_revision,
                                    candidate_revision=candidate_revision,
                                    quervant_revision=quervant_revision,
-                                   readiness_advisory=readiness_advisory)
+                                   readiness_advisory=readiness_advisory,
+                                   aa_advisory=aa_advisory)
     return create_configuration(configuration_directory(studies_root, config), config)
--- a/benchmarks/quervant_bench/lean/runtime.py
+++ b/benchmarks/quervant_bench/lean/runtime.py
@@ -890,6 +890,12 @@
         config["family"] in ("perf-06", "cross-engine") and
         config["policy"]["readiness"].get("mode", "blocking") == "advisory")
     report["context"]["host_readiness_mode"] = "advisory" if readiness_advisory else "blocking"
+    aa_advisory = (
+        config["family"] == "cross-engine" and config["workload"]["regimes"] == ["warm"]
+        and config["policy"].get("aa_mode", "required") == "advisory")
+    aa_control_failed = False
+    if aa_advisory:
+        report["context"]["aa_control_mode"] = "advisory"
     try:
         started = time.monotonic_ns()
         report["context"]["host"] = host_context(scratch, check=check_host)
@@ -975,8 +981,39 @@
                                     lanes=lanes, policy=control_policy)
             report["phase_durations_ns"]["aa_analysis_ns"] = max(1, time.monotonic_ns() - started)
             report["controls"]["analysis"] = control_stats
-            if any(c.get("status") != "PASS" for lane in control_stats["lanes"].values()
-                   for c in lane["comparisons"].values()):
+            if aa_advisory:
+                control_lanes = control_stats.get("lanes") if isinstance(control_stats, dict) else None
+                if (not isinstance(control_lanes, dict) or not control_lanes
+                        or set(control_lanes) != {lane["id"] for lane in lanes}):
+                    raise MeasurementBlocked("advisory A/A requires every declared control lane")
+                failed_lanes = []
+                for lane_id, control_lane in control_lanes.items():
+                    comparisons = control_lane.get("comparisons") if isinstance(control_lane, dict) else None
+                    if not isinstance(comparisons, dict) or set(comparisons) != {"AA2"}:
+                        raise MeasurementBlocked("advisory A/A requires exactly one AA2 comparison per lane")
+                    if (control_lane.get("retained_blocks") != config["policy"]["blocks"]
+                            or control_lane.get("excluded_blocks") != []):
+                        raise MeasurementBlocked("advisory A/A requires every scheduled block without exclusions")
+                    comparison = comparisons["AA2"]
+                    if (not isinstance(comparison, dict) or comparison.get("kind") != "A/A"
+                            or comparison.get("baseline_arm") != "AA"
+                            or comparison.get("treatment_arm") != "AA2"
+                            or comparison.get("status") not in ("PASS", "FAIL")):
+                        raise MeasurementBlocked("advisory A/A accepts only native PASS or FAIL outcomes")
+                    if comparison["status"] == "FAIL":
+                        failed_lanes.append(lane_id)
+                aa_control_failed = bool(failed_lanes)
+                report["controls"]["aa_gate"] = {
+                    "mode": "advisory", "status": "FAIL" if aa_control_failed else "PASS",
+                    "failed_lanes": sorted(failed_lanes),
+                    "continued_after_failure": aa_control_failed,
+                }
+                if aa_control_failed:
+                    report["notes"] += (
+                        " Predeclared advisory A/A allowed acquisition after a native statistical FAIL; "
+                        "comparative values are exploratory and not statistically qualified.")
+            elif any(c.get("status") != "PASS" for lane in control_stats["lanes"].values()
+                     for c in lane["comparisons"].values()):
                 raise MeasurementBlocked("A/A control is unstable; comparative acquisition is blocked")
             if check_host:
                 report["controls"]["readiness_treatment"] = observe()
@@ -1022,7 +1059,8 @@
                     if (report["controls"]["readiness_throughput_post"]["status"] != "clear"
                             and not readiness_advisory):
                         raise MeasurementBlocked("host contention after throughput; preserve samples but invalidate run")
-            report["status"] = _run_status(report["analysis"])
+            report["status"] = ("INCONCLUSIVE" if aa_control_failed
+                                else _run_status(report["analysis"]))
     except KeyboardInterrupt:
         # Operator interruption must not discard already captured measurements.
         report["errors"].append("interrupted by operator; partial observations preserved")
--- a/benchmarks/quervant_bench/lean/reporting.py
+++ b/benchmarks/quervant_bench/lean/reporting.py
@@ -40,6 +40,53 @@
                     "descriptive metrics, not part of this run's query timings.")
     rows.append("")
     return rows
+
+
+def _aa_advisory_lines(result: Mapping[str, Any]) -> list[str]:
+    """Display the saved opt-in decision without changing any analysis value."""
+    config = result.get("configuration")
+    policy = config.get("policy") if isinstance(config, Mapping) else None
+    if not isinstance(policy, Mapping) or policy.get("aa_mode", "required") != "advisory":
+        return []
+    controls = result.get("controls")
+    gate = controls.get("aa_gate", {}) if isinstance(controls, Mapping) else {}
+    if not isinstance(gate, Mapping):
+        raise ArtifactError("saved advisory A/A decision is not an object")
+    status = gate.get("status", "NOT_REACHED")
+    rows = [
+        "", "## Predeclared advisory A/A policy", "",
+        f"- Actual A/A outcome: **{_cell(status)}**",
+        f"- Failed control lanes: {_cell(gate.get('failed_lanes', []))}",
+        f"- Gate continued after failure: {_cell(gate.get('continued_after_failure', False))}",
+        "- A/A samples, thresholds, native PASS/FAIL decisions and confidence intervals are unchanged.",
+    ]
+    if status == "FAIL":
+        rows.extend(["", "**EXPLORATORY: A/A CONTROL FAILED.** Treatment ratios and confidence "
+                     "intervals are reported as observed; they are not statistically qualified "
+                     "comparative conclusions. Completed acquisition is INCONCLUSIVE; any "
+                     "later structural failure remains INCOMPLETE."])
+    elif status == "PASS":
+        rows.append("- All control lanes passed despite the predeclared non-blocking statistical policy.")
+    else:
+        rows.append("- No admissible PASS/FAIL control decision was recorded; acquisition is incomplete.")
+    if result.get("status") == "INCOMPLETE":
+        rows.extend(["", "**ACQUISITION INCOMPLETE — no completed comparative claim.**",
+                     f"- Errors: {_cell(result.get('errors', []))}"])
+    analysis = controls.get("analysis", {}) if isinstance(controls, Mapping) else {}
+    lanes = analysis.get("lanes", {}) if isinstance(analysis, Mapping) else {}
+    if isinstance(lanes, Mapping) and lanes:
+        rows.extend(["", "| Control lane | Native status | Gain % | 95% gain CI |",
+                     "| --- | --- | ---: | --- |"])
+        for lane_id, lane in sorted(lanes.items(), key=lambda item: str(item[0])):
+            comparisons = lane.get("comparisons", {}) if isinstance(lane, Mapping) else {}
+            comparison = comparisons.get("AA2", {}) if isinstance(comparisons, Mapping) else {}
+            if not isinstance(comparison, Mapping):
+                comparison = {}
+            rows.append("| " + " | ".join(map(_cell, (
+                lane_id, comparison.get("status"), comparison.get("gain_percent"),
+                comparison.get("gain_ci_95_percent"),
+            ))) + " |")
+    return rows + [""]
 
 
 def _render_perf05(result: Mapping[str, Any], analysis: Mapping[str, Any]) -> str:
@@ -111,6 +158,7 @@
             f"- Errors: {_cell(result.get('errors', []))}",
             "", "This is incomplete evidence, not a performance comparison.", "",
         ]
+        incomplete.extend(_aa_advisory_lines(result))
         incomplete.extend(_phase_lines(result))
         return "\n".join(incomplete)
     if result.get("family") == "perf-05" and analysis.get("schema") == "bm10-b-only-analysis-v1":
@@ -123,11 +171,14 @@
         f"- Executed (UTC): {_cell(result.get('executed_utc'))}",
         f"- Family: {_cell(result.get('family'))}",
         f"- Overall status: **{_cell(result.get('status'))}**", "",
+    ]
+    lines.extend(_aa_advisory_lines(result))
+    lines.extend([
         "Results show within-run treatment/baseline ratios (B/A). Positive gain means improvement.",
         "Separate runs must be compared using the change in within-run gain in percentage points, not absolute timings.", "",
         "| Lane | Metric | Arm | Absolute median per block (ns) | B/A | Gain % | 95% ratio CI | Status |",
         "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
-    ]
+    ])
     for lane_id, lane in analysis["lanes"].items():
         arm_absolute = lane.get("arm_absolute", {})
         metric = f"{lane.get('metric', 'latency')} ({lane.get('unit', 'ns')}; {lane.get('direction', 'lower')} better)"
--- a/benchmarks/BM10_README.md
+++ b/benchmarks/BM10_README.md
@@ -114,7 +114,11 @@
 
 ## Advisory host readiness (opt-in, PERF-06 and cross-engine)
 
-**Advisory mode (PERF-06 and cross-engine).** A `perf-06` or `cross-engine` configuration created explicitly with `quervant-bench prepare --readiness-advisory` declares `policy.readiness.mode="advisory"`. Cross-engine supports this mode for both warm and process-cold studies. The native CPU busy/steal observations are still acquired at every existing checkpoint and retained with their actual `clear`, `busy` or `unavailable` status and unchanged 25%/2% thresholds. These observations are informational and do not block staging or acquisition. An absent mode retains the original blocking behavior. Structural execution capabilities and the native A/A measurement-validity control remain required. Other families reject advisory mode; `stage` and `run` accept no runtime bypass flag. Historical configurations and result interpretations are unchanged.
+**Advisory mode (PERF-06 and cross-engine).** A `perf-06` or `cross-engine` configuration created explicitly with `quervant-bench prepare --readiness-advisory` declares `policy.readiness.mode="advisory"`. Cross-engine supports this mode for both warm and process-cold studies. The native CPU busy/steal observations are still acquired at every existing checkpoint and retained with their actual `clear`, `busy` or `unavailable` status and unchanged 25%/2% thresholds. These observations are informational and do not block staging or acquisition. An absent mode retains the original blocking behavior. Structural execution capabilities remain required. Host advisory mode alone leaves the A/A statistical decision blocking; the separate cross-engine warm `--aa-advisory` option is described below. Other families reject advisory mode; `stage` and `run` accept no runtime bypass flag. Historical configurations and result interpretations are unchanged.
+
+## Cross-engine warm advisory A/A (opt-in)
+
+A new cross-engine **warm** configuration may be created with `quervant-bench prepare --family cross-engine --regime warm --aa-advisory ...`. This freezes optional `policy.aa_mode="advisory"`; absent mode or explicit `"required"` retains the existing blocking A/A behavior. Other families and process-cold reject advisory A/A. The flag exists only on `prepare`; `stage` and `run` have no bypass flag. Full A/A acquisition and native analysis still run with unchanged samples, ±15% default bound, bootstrap and PASS/FAIL decisions. Only a native statistical FAIL may continue to the complete treatment/throughput schedule. Missing/incomplete/non-comparable control outcomes and every source, build, oracle, protocol, timer or acquisition failure remain fatal. A completed study that continued after any FAIL has top-level `INCONCLUSIVE`, retains all native values and is reported as exploratory, statistically unqualified comparison; all-PASS retains normal status. No historical configuration or result is reinterpreted. `--readiness-advisory` remains a separate host-observation policy and may be explicitly combined with this option.
 
 ## PERF-05 B-only warm study
 
--- a/docs/BENCHMARK_CONFIGURATION.md
+++ b/docs/BENCHMARK_CONFIGURATION.md
@@ -141,6 +141,7 @@
 | `min_gain_percent` | finite nonnegative number | 0 | Treatment improvement threshold applied to the lower bound of gain CI. |
 | `max_regression_percent` | finite nonnegative number | 0 | Treatment regression threshold applied to the upper bound of gain CI. |
 | `max_aa_gain_percent` | finite nonnegative number | 15 | Maximum absolute signed gain and CI bound for equivalent-baseline A/A PASS. |
+| `aa_mode` | string | absent (= `required`) | Optional `required` or `advisory`; `advisory` is supported only by cross-engine warm. It changes continuation, not the native A/A decision or threshold. |
 | `exclude_blocks` | object | `{}` | Map of declared lane IDs to lists of **unique block numbers** in `[1,blocks]`; exclusions are symmetric across arms. |
 | `control_arms` | array | `[]` | Must be empty in the normal configuration. A/A analysis separately uses `["AA2"]`. |
 | `readiness` | object | See §8 | Predeclared host observation settings. |
@@ -158,6 +159,8 @@
 
 **Statistical semantics:** a slot's value is the median of its measured query latencies; an arm's block value is the mean of its slot medians; each block supplies a paired treatment/baseline `B/A` ratio. The point effect is the median of eligible block ratios. The bootstrap resamples **whole blocks**, not individual query samples. Positive signed gain means improvement for the declared direction.
 
+**Optional advisory A/A.** A new cross-engine **warm** configuration may be created with `quervant-bench prepare --family cross-engine --regime warm --aa-advisory ...`. This freezes optional `policy.aa_mode="advisory"`; absent mode or explicit `"required"` retains the existing blocking A/A behavior. Other families and process-cold reject advisory A/A. The flag exists only on `prepare`; `stage` and `run` have no bypass flag. Full A/A acquisition and native analysis still run with unchanged samples, ±15% default bound, bootstrap and PASS/FAIL decisions. Only a native statistical FAIL may continue to the complete treatment/throughput schedule. Missing/incomplete/non-comparable control outcomes and every source, build, oracle, protocol, timer or acquisition failure remain fatal. A completed study that continued after any FAIL has top-level `INCONCLUSIVE`, retains all native values and is reported as exploratory, statistically unqualified comparison; all-PASS retains normal status. No historical configuration or result is reinterpreted. `--readiness-advisory` remains a separate host-observation policy and may be explicitly combined with this option.
+
 ## 8. `policy.readiness` object
 
 | Key | Type | Default | Constraint / role |
@@ -170,7 +173,7 @@
 
 The Linux/WSL2 runner checks physical-core availability, usable filesystem/toolchains and contention around timed phases. Readiness results live in the **result's** `controls` object, not in configuration. These checks prevent invalid comparisons; they are not manual approval or cryptographic attestation.
 
-**Advisory mode (PERF-06 and cross-engine).** A `perf-06` or `cross-engine` configuration created explicitly with `quervant-bench prepare --readiness-advisory` declares `policy.readiness.mode="advisory"`. Cross-engine supports this mode for both warm and process-cold studies. The native CPU busy/steal observations are still acquired at every existing checkpoint and retained with their actual `clear`, `busy` or `unavailable` status and unchanged 25%/2% thresholds. These observations are informational and do not block staging or acquisition. An absent mode retains the original blocking behavior. Structural execution capabilities and the native A/A measurement-validity control remain required. Other families reject advisory mode; `stage` and `run` accept no runtime bypass flag. Historical configurations and result interpretations are unchanged.
+**Advisory mode (PERF-06 and cross-engine).** A `perf-06` or `cross-engine` configuration created explicitly with `quervant-bench prepare --readiness-advisory` declares `policy.readiness.mode="advisory"`. Cross-engine supports this mode for both warm and process-cold studies. The native CPU busy/steal observations are still acquired at every existing checkpoint and retained with their actual `clear`, `busy` or `unavailable` status and unchanged 25%/2% thresholds. These observations are informational and do not block staging or acquisition. An absent mode retains the original blocking behavior. Structural execution capabilities remain required. Host advisory mode alone leaves the A/A statistical decision blocking; the separate cross-engine warm `--aa-advisory` option is described in §7. Other families reject advisory mode; `stage` and `run` accept no runtime bypass flag. Historical configurations and result interpretations are unchanged.
 
 ## 9. Current limitations, validation and versioning
 
--- a/docs/BENCHMARK_RESULT.md
+++ b/docs/BENCHMARK_RESULT.md
@@ -104,7 +104,7 @@
 | --- | --- |
 | `INCOMPLETE` | Acquisition/validation/host/process interruption or error. Collected measurements are preserved; do **not** present as accepted comparative performance. `analysis` may be `{}` or may already exist if failure came after analysis. |
 | `COMPLETE` | The runner finished mandatory stages without fatal measurement failure, and no per-lane status in the configured aggregate-ineligibility set forced `INCONCLUSIVE`. **This does not mean the candidate improved**. A measured slowdown (`REGRESSED`) or a per-lane `INCONCLUSIVE` may still be a valid completed result. |
-| `INCONCLUSIVE` | A completed run with no eligible comparisons or relevant structural/metric non-comparability or non-computability. Do not invent an overall winner. |
+| `INCONCLUSIVE` | A completed run with no eligible comparisons or relevant structural/metric non-comparability or non-computability; also a cross-engine warm run whose predeclared advisory A/A policy continued after a native FAIL. The latter preserves exploratory values without statistical qualification. Do not invent an overall winner. |
 
 **Within-run analysis comparison statuses:** `IMPROVED`, `REGRESSED`, `INCONCLUSIVE`, `NON_COMPARABLE`, `NOT_COMPUTABLE`; A/A comparisons use `PASS`/`FAIL`. Numeric comparisons retain point estimates and confidence intervals; non-comparable or non-computable comparisons may contain only a status and reason.
 
@@ -172,6 +172,7 @@
 | `readiness_pre` | Checked real host before A/A | Pre-control contention. |
 | `raw_samples` | A/A acquisition began | A/A arm/slot/lane samples, with `AA` and `AA2` roles; same general record structure as §6. |
 | `analysis` | A/A analysis succeeded | Normal `bm10-analysis-v1` object, with `kind: "A/A"` and per-lane `PASS`/`FAIL`. |
+| `aa_gate` | Opt-in cross-engine warm advisory A/A reached a complete native PASS/FAIL decision | `{mode:"advisory", status: string, failed_lanes:[sorted lane IDs], continued_after_failure:boolean}`. Status is `PASS` or `FAIL`. The Boolean records the gate's continuation decision, not completed treatment. |
 | `readiness_treatment` | Checked real host before treatment | Contention before timed treatment slots. |
 | `readiness_post` | Checked real host after treatment | A failure invalidates the run while retaining raw samples/analysis. |
 | `readiness_throughput_pre` | Checked cross-engine real host before throughput | Contention before separately timed serial throughput. |
@@ -179,7 +180,7 @@
 
 Readiness observations normally contain `cpu` (integer), `observations` (array of `{busy_percent, steal_percent}` numbers), `max_busy_percent`, `max_steal_percent` and `status` (`clear` or `busy`). Under deterministic test injections (`check_host=False`) these keys may be absent; such an injected test is **not** real-host qualification.
 
-An unstable A/A control blocks further comparative acquisition. The presence of an `analysis` object alone is **not** proof of valid readiness, correctness or complete acquisition; evaluate `status` and `controls`.
+An unstable A/A control blocks further comparative acquisition by default. Only a new cross-engine warm configuration with `policy.aa_mode="advisory"` may continue after native statistical FAIL outcomes. Its result records `context.aa_control_mode="advisory"` and the `controls.aa_gate` decision, preserves every native A/A/treatment value, and has top-level `INCONCLUSIVE` after completed acquisition if any control lane failed. Every structural/oracle/protocol/acquisition error still yields `INCOMPLETE`; `aa_gate` is absent if no admissible complete PASS/FAIL control decision was reached. Report rendering labels the failed-control comparison exploratory and statistically unqualified and lists the failed lanes. All-PASS advisory runs keep normal native status. The presence of an `analysis` object alone is **not** proof of valid readiness, correctness or complete acquisition; evaluate `status` and `controls`.
 
 ## 8. `analysis`: computed per-lane statistics and decisions
 
--- a/docs/BENCHMARKING.md
+++ b/docs/BENCHMARKING.md
@@ -381,6 +381,18 @@
 measurement stability under equivalent baselines. The actual A/A pass/fail
 requirements and subsequent campaign authorization are defined by that
 experiment's frozen control policy, not by post-hoc selection of good blocks.
+
+**Optional cross-engine warm advisory A/A.** A new configuration may prospectively
+declare `policy.aa_mode="advisory"` through `prepare --aa-advisory`. This permits
+complete treatment and serial-throughput acquisition after a native statistical
+A/A FAIL, while preserving all control samples, thresholds, decisions and
+confidence intervals. Only cross-engine warm supports this policy; defaults and
+historical studies retain required A/A. Structural/oracle/protocol/timing failures
+still stop acquisition. A completed study with any failed control lane is
+`INCONCLUSIVE`: its displayed comparative values are exploratory and statistically
+unqualified. They do not qualify an optimization or authorize baseline promotion.
+This prospective acquisition policy does not turn an earlier failed study into
+accepted evidence or permit pruning/repeating selected lanes.
 
 ### Aggregation and paired statistics
 
--- a/docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md
+++ b/docs/pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md
@@ -124,7 +124,7 @@
   `readiness_treatment`, `readiness_post` and the throughput checkpoints are absent
   because the native control blocked acquisition before them; this is disclosed and
   is not itself treated as an invalidity condition.
-- Phases: host preflight 0.051 s, preparation lookup 2.053 s, A/A acquisition
+- Phases: host preflight 0.051 s, preparation total 2.053 s (cache lookup 0.111 s), A/A acquisition
   89.364 s, A/A analysis 0.778 s, total before save 93.297 s.
 
 ### 6.2 Process-cold
@@ -140,7 +140,7 @@
 - Host observations (advisory, informational): `readiness_index_pre` `clear` (one of
   four intervals reported busy `7.692%`, still `clear`), `readiness_pre` `clear`,
   `readiness_treatment` `clear`, `readiness_post` `clear`; all with steal `0.0%`.
-- Phases: host preflight 0.050 s, preparation lookup 0.783 s, A/A acquisition
+- Phases: host preflight 0.050 s, preparation total 0.783 s (cache lookup 0.056 s), A/A acquisition
   38.224 s, A/A analysis 0.050 s, treatment acquisition 319.570 s, treatment analysis
   0.095 s, total before save 361.826 s.
 - Build/context (both studies): `rustc 1.98.1`, `cargo 1.98.1`, `python 3.12.3`,
@@ -178,9 +178,10 @@
 
 ## 8. Process-cold comparison
 
-Ratios are competitor/Quervant. Ratio > 1 and positive native gain mean the
-**competitor is slower**; ratio < 1 / positive gain mean the **competitor is faster**.
-Native `IMPROVED`/`REGRESSED` describes the competitor relative to Q.
+Ratios are competitor/Quervant, and native gain is `100 * (1 - ratio)`.
+Ratio > 1 and negative native gain mean the **competitor is slower**; ratio < 1
+and positive native gain mean the **competitor is faster**. Ratio = 1 means zero
+native gain. Native `IMPROVED`/`REGRESSED` describes the competitor relative to Q.
 
 | Lane | Q wall (ms) | T wall (ms) | J wall (ms) | Competitor | Ratio vs Q | 95% ratio CI | Competitor gain % | Native status | Blocks |
 | --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- | ---: |
@@ -243,12 +244,16 @@
 | D06 | Disjoint untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` | Preserved untouched; exact-path staging only | status; setup/delivery |
 | D11 | Advisory load observations clear (cold included one `7.692%` busy interval, still `clear`) | Recorded as informational; acquisition continued; no wait/recheck/retune | native `controls`; all stages |
 | D18 | Warm's sole failure was the exact native A/A-instability error | Preserved warm `INCOMPLETE`; ran the already-staged, uninvoked cold config once with its own control | warm result + cold stage/result; acquisition |
-| D17/D14 | Warm run exited 4 with saved `INCOMPLETE` | No retry, no pruning, no reconstructed samples; reported actual counts | warm result/log; acquisition |
-| D19 | Cold `COMPLETE` with an unfavorable Lucene comparison | Reported both comparisons as measured evidence; no threshold or retry | cold result; reporting |
-| D23 | `origin/main` unchanged at `f169fbb…` throughout | No rebase/repin; experiment stayed on the selected source | refs; all stages |
+| D17 | Warm run exited 4 with saved `INCOMPLETE` | No retry, no pruning, no reconstructed samples; reported actual counts | warm result/log; acquisition |
+| D19 | Cold `COMPLETE`; Quervant slower than Tantivy (T/Q `0.049416`) | Reported both competitor comparisons as measured evidence; no threshold change or retry | cold result; reporting |
 | D25 | Only allowlisted artifacts pending after measurement | Exact-path commit; non-force push to `dev/perf06-c4`; append PR description | delivery |
-| D27 | No non-sample Git hooks present | Normal commit, no hook bypass | `.git/hooks`; commit |
 | D28 | Ordinary hosted CI may start from the push | Left alone; not gated | delivery |
+
+D14, D23 and D27 were checked but did not trigger. There was no shared
+source/oracle/protocol failure (D14); `origin/main` remained at
+`f169fbba93e10d174cad8ab3bca55cdb7ae6aa03`, so there was no main advancement
+(D23); and no non-sample Git hook was present or bypassed (D27). The original
+execution therefore applied D01, D06, D11, D17, D18, D19, D25 and D28.
 
 No other rule fired. No unexpected source, oracle, protocol, build or cache failure
 occurred; the single warm failure is a native measurement-validity (A/A) outcome.
@@ -291,3 +296,26 @@
   natural next step, if warm behaviour is still required, is a separately authorized
   new warm acquisition (the single warm invocation for this plan is exhausted); no
   retry is authorized by this report.
+
+## 14. Independent review corrections
+
+Review basis: delivery commit `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b`;
+measurement source `0148aaaa922c398a0b8b33581e72918ad212e67f`. The corrections
+below supersede the earlier presentation at that delivery commit.
+
+| Fix | Correction |
+| --- | --- |
+| F01 | Corrected the sign explanation in §8; ratios and native comparison tables are unchanged. |
+| F02 | Distinguished preparation totals from cache lookups in §6.1 and §6.2. |
+| F03 | Corrected applied-rule attribution: D17 for the warm stop, D18 for cold continuation, and D19 for Quervant's measured loss to Tantivy; D14/D23/D27 did not trigger. |
+| F04 | Corrected the two result-link targets in the new cross-engine roadmap entry. |
+
+These corrections preserve this original experiment's configurations, result
+JSON, source revisions, all measurements and both study statuses. Its disposition
+remains **`PERF06_CROSS_ENGINE_PARTIAL`**; its warm treatment and throughput were
+not acquired. A separately identified new warm acquisition is prospectively
+authorized by the autonomous completion plan below. That new experiment must not
+replace this result or backfill its missing observations. General test and quality
+suites remain waived by the user.
+
+Autonomous completion plan: [PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md](PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md).
--- a/docs/PERF_OPTIMIZATION_ROADMAP.md
+++ b/docs/PERF_OPTIMIZATION_ROADMAP.md
@@ -540,8 +540,8 @@
 (native gain +95.06%, Tantivy faster) and J/Q ratio 15.331842 [15.295242,
 15.408109] (native gain -1433.18%, Lucene slower). Overall disposition
 **`PERF06_CROSS_ENGINE_PARTIAL`**. Results:
-[`warm`](../../benchmarks/studies/cross-engine/warm/results/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-2026-11-27-001.json),
-[`cold`](../../benchmarks/studies/cross-engine/cold-start/results/quervant-perf06c4-tantivy-lucene-lexical-sort-cold-start-2026-11-27-001.json);
+[`warm`](../benchmarks/studies/cross-engine/warm/results/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-2026-11-27-001.json),
+[`cold`](../benchmarks/studies/cross-engine/cold-start/results/quervant-perf06c4-tantivy-lucene-lexical-sort-cold-start-2026-11-27-001.json);
 report: [PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md](pr-artifacts/perf-06-c/PERF06C4_CROSS_ENGINE_EXECUTION_REPORT.md).
 General QA suites were not rerun by explicit maintainer instruction. This adds no
 optimization, no baseline promotion and no change to the earlier C4
```

## Appendix B — Exact read-only input/result inspector

Extract this block verbatim to the task's ignored log directory. Run `config CONFIG` before freezing execution, and `result CONFIG RESULT AUTO_EXECUTION ANALYSIS_JSON` after acquisition. It imports existing parsers/statistics, reads saved data, prints tables and exits; it never launches an engine or modifies artifacts. Exit 0 accepts a full acquisition regardless of whether native A/A passed or failed; exit 4 honestly reports INCOMPLETE; exit 2 is a mismatch requiring the matrix.

```python
#!/usr/bin/env python3
"""Read-only autonomous warm inspection; never launches engines or edits results."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys

from quervant_bench.lean.artifacts import load_configuration, load_result
from quervant_bench.lean.configuration import lanes_for, validate_configuration
from quervant_bench.lean.statistics import analyze


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


NAME = "quervant-perf06c4-tantivy-lucene-lexical-sort-warm-aa-advisory"
DESCRIPTION = "Prospectively authorized post-C4 full warm comparison; host load and statistical A/A failures advisory; exact-result checks binding; all failed-control comparisons exploratory"
ORIGINAL_CONFIG = Path("benchmarks/studies/cross-engine/warm/configurations/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-2026-11-27.json")


def checked_config(path: str) -> dict:
    config = load_configuration(Path(path))
    validate_configuration(config)
    original = load_configuration(ORIGINAL_CONFIG)
    expected = json.loads(json.dumps(original))
    actual = json.loads(json.dumps(config))
    for key in ("name", "description", "configuration_id", "created_utc"):
        del expected[key]
        del actual[key]
    expected["policy"]["aa_mode"] = "advisory"
    require(actual == expected, "new configuration differs beyond declared identity and A/A mode")
    require(config["name"] == NAME and config["description"] == DESCRIPTION,
            "wrong autonomous study identity/description")
    require(config["configuration_id"] != original["configuration_id"], "old UUID reused")
    require(config["workload"]["regimes"] == ["warm"], "only new warm acquisition is allowed")
    require(config["policy"]["aa_mode"] == "advisory", "A/A policy not predeclared advisory")
    return config


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "config":
        config = checked_config(sys.argv[2])
        print("CONFIGURATION_MATCHES_FIXED_DESIGN")
        print("configuration_id=" + config["configuration_id"])
        return 0
    require(len(sys.argv) == 6 and sys.argv[1] == "result",
            "usage: inspect.py config CONFIG | inspect.py result CONFIG RESULT EXECUTION_SHA ANALYSIS_JSON")
    config_path, result_path, execution_sha, analysis_path = sys.argv[2:]
    config = checked_config(config_path)
    result = load_result(Path(result_path))
    require(result.get("configuration") == config, "saved configuration differs from selected input")
    require(result.get("configuration_id") == config["configuration_id"], "configuration UUID mismatch")
    require(type(result.get("sequence")) is int and result["sequence"] == 1,
            "new study must have sequence 1")
    require(result.get("family") == config["family"]
            and result.get("configuration_name") == config["name"]
            and result.get("configuration_file") == Path(config_path).name,
            "result-to-configuration identity mismatch")
    require(config["family"] == "cross-engine" and config["baseline"] == "Q", "wrong study family/baseline")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_sha) is not None, "execution SHA must be full Git SHA")
    cold = config["workload"]["regimes"] == ["process-cold"]
    lanes = lanes_for(config)
    controls = result.get("controls", {})
    actual_rows = result.get("raw_samples", [])
    control_rows = controls.get("raw_samples", [])
    print(f"# {'Process-cold' if cold else 'Warm'} comparative benchmark inspection\n")
    print(f"- Native status: **{result.get('status')}**")
    print(f"- Run ID: `{result['run_id']}`")
    print(f"- Configuration ID: `{config['configuration_id']}`")
    print(f"- Expected execution source: `{execution_sha}`")
    print(f"- Observed execution source: `{result.get('context', {}).get('source_revision', 'UNAVAILABLE')}`")
    print(f"- Captured control rows / samples: {len(control_rows)} / {sum(len(r.get('samples_ns', [])) for r in control_rows)}")
    print(f"- Captured treatment rows / samples: {len(actual_rows)} / {sum(len(r.get('samples_ns', [])) for r in actual_rows)}")
    print("\n## Advisory host observations\n")
    for key, value in controls.items():
        if key.startswith("readiness_"):
            print(f"- `{key}`: `{json.dumps(value, sort_keys=True)}`")
    observation_keys = ["readiness_index_pre", "readiness_pre", "readiness_treatment", "readiness_post"]
    if not cold:
        observation_keys += ["readiness_throughput_pre", "readiness_throughput_post"]
    for key in observation_keys:
        value = controls.get(key)
        if not isinstance(value, dict) or value.get("status") not in ("clear", "busy", "unavailable"):
            print(f"- INFORMATIONAL_DIAGNOSTIC_GAP: `{key}` is missing or not a native observation; "
                  "disclose this without invalidating measurements solely for the load diagnostic.")
    if result.get("status") == "INCOMPLETE":
        print("\nACQUISITION_INCOMPLETE — no complete comparative acceptance is claimed.")
        for error in result.get("errors", []):
            print(f"- Native error: {error}")
        return 4

    require(result.get("status") in ("COMPLETE", "INCONCLUSIVE"), "unexpected native status")
    require(result.get("errors") == [], "purported finished acquisition contains errors")
    require(result["lanes"] == lanes, "lane descriptors differ from native configuration")
    require(config["policy"]["exclude_blocks"] == {}, "blocks were excluded")
    require(config["policy"]["readiness"]["mode"] == "advisory", "readiness is not advisory")
    context = result["context"]
    require(context["source_revision"] == execution_sha, "wrong execution revision")
    require(context["host_readiness_mode"] == "advisory", "runtime did not honor host advisory policy")
    require(context.get("aa_control_mode") == "advisory", "runtime did not honor A/A advisory policy")
    build = context["build"]
    require(build["source_revision"] == execution_sha, "build source differs from execution source")
    require(build["compiler_options"] == "cargo --release --locked", "unexpected compiler mode")
    require(build["quervant_strategy_feature_enabled"] is False, "experimental strategy feature enabled")
    require(build["sort_contract"] == config["build"]["sort_contract"]
            and build["tantivy_version"] == config["build"]["tantivy_version"],
            "native string-sort build provenance mismatch")
    require(context["preparation"]["verified_oracles"] is True, "preparation oracles not verified")
    require(context["preparation"]["cache_status"] in ("BUILT", "HIT"), "unknown preparation state")
    host = context["host"]
    require(host["system"] == "Linux", "unexpected host system")
    require(host["filesystem"] in ("ext4", "xfs", "btrfs"), "unexpected scratch filesystem")
    require(context["controller_cpu"] is not None and context["adapter_cpu"] is not None
            and context["controller_cpu"] != context["adapter_cpu"], "CPU roles not distinct")
    require(host["toolchains"]["rustc"].startswith("rustc 1.98.1 "), "unexpected Rust toolchain")
    require(host["toolchains"]["cargo"].startswith("cargo 1.98.1 "), "unexpected Cargo toolchain")
    require(re.search(r'(?:openjdk|java) (?:version )?"?21(?:[. \"-]|$)',
                      host["toolchains"]["java"]) is not None, "unexpected Java runtime")

    lane_ids = {lane["id"] for lane in lanes}
    expected_warmups = 0 if cold else 5
    for rows, arms, expected_count in ((control_rows, ["AA", "AA2"], 48 if cold else 768),
                                       (actual_rows, list(config["arms"]), 72 if cold else 1152)):
        require(len(rows) == expected_count, "wrong raw row count")
        counts = Counter((row["lane_id"], row["arm_id"]) for row in rows)
        require(counts == Counter({(lane, arm): 24 for lane in lane_ids for arm in arms}),
                "wrong per-lane/arm row inventory")
        for row in rows:
            require(row["oracle_ok"] is True and row["warmups"] == expected_warmups,
                    "oracle/warmup mismatch")
            require(row.get("strategy_marker") is None, "unexpected experimental strategy marker")
            values = row["samples_ns"]
            require(len(values) == 20 and all(type(v) is int and v > 0 for v in values),
                    "invalid timed sample series")

    saved_analysis = result["analysis"]
    require(json.loads(Path(analysis_path).read_text()) == saved_analysis,
            "native treatment reanalysis differs from saved analysis")
    control_analysis = analyze(control_rows, arms=["AA", "AA2"], baseline="AA", lanes=lanes,
                               policy=dict(config["policy"], control_arms=["AA2"]))
    require(control_analysis == controls["analysis"], "native control reanalysis differs")
    require(set(control_analysis["lanes"]) == lane_ids, "wrong control analysis lane set")
    failed_lanes = []
    for lane_id, row in control_analysis["lanes"].items():
        require(row["retained_blocks"] == 12 and row["excluded_blocks"] == [],
                "control lacks all scheduled blocks")
        require(set(row["comparisons"]) == {"AA2"}, "wrong control comparison set")
        comp = row["comparisons"]["AA2"]
        require(comp["kind"] == "A/A" and comp["baseline_arm"] == "AA"
                and comp["treatment_arm"] == "AA2" and comp["status"] in ("PASS", "FAIL"),
                "control lacks a native fully computed PASS/FAIL outcome")
        if comp["status"] == "FAIL":
            failed_lanes.append(lane_id)
    failed_lanes.sort()
    gate = controls.get("aa_gate")
    require(gate == {"mode": "advisory", "status": "FAIL" if failed_lanes else "PASS",
                     "failed_lanes": failed_lanes, "continued_after_failure": bool(failed_lanes)},
            "saved advisory gate does not match raw control outcomes")
    require(type(gate["continued_after_failure"]) is bool, "gate continuation must be Boolean")
    require(result["status"] == ("INCONCLUSIVE" if failed_lanes else "COMPLETE"),
            "native status contradicts control qualification")
    qualification = "EXPLORATORY — A/A FAILED" if failed_lanes else "A/A PASS"
    print("\n## Control qualification\n")
    print(f"- A/A lanes PASS / FAIL: {16-len(failed_lanes)} / {len(failed_lanes)}")
    print(f"- Failed lanes: `{json.dumps(failed_lanes)}`")
    print(f"- Comparative interpretation: **{qualification}**")
    if failed_lanes:
        print("All treatment ratios, native classifications and nominal confidence intervals below are "
              "exploratory, not statistically qualified. Completing acquisition does not repair the control.")
    print("\n| Control lane | Gain % | 95% gain CI | Native status |")
    print("| --- | ---: | --- | --- |")
    for lane_id, row in sorted(control_analysis["lanes"].items()):
        comp = row["comparisons"]["AA2"]
        lo, hi = comp["gain_ci_95_percent"]
        print(f"| {lane_id} | {comp['gain_percent']:.6f} | [{lo:.6f}, {hi:.6f}] | {comp['status']} |")
    require(set(saved_analysis["lanes"]) == lane_ids, "analysis lane inventory mismatch")
    require(set(result["index_metrics"]) == {"Q", "T", "J"}, "index arm inventory mismatch")
    for arm, corpora in result["index_metrics"].items():
        require(set(corpora) == ({"10000"} if cold else {"10000", "100000"}),
                f"index corpus inventory mismatch: {arm}")
        for values in corpora.values():
            for key in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
                require(type(values[key]) is int and values[key] > 0, f"invalid index metric: {key}")
    if cold:
        require(not result.get("throughput_metrics"), "cold study contains throughput")
    else:
        throughput = result["throughput_metrics"]
        require(set(throughput) == {"Q", "T", "J"}, "throughput arm inventory mismatch")
        for row in throughput.values():
            require(row["lane_id"] == "10000/medium/k10/warm" and row["requests"] == 100
                    and row["status"] == "MEASURED" and row["serial_ops_per_second"] > 0,
                    "incomplete throughput phase")
            require(row["warmups"] == 5, "wrong throughput warmup count")
            require(type(row["wall_ns"]) is int and row["wall_ns"] > 0,
                    "invalid throughput wall time")
            require(row["serial_ops_per_second"] == round(100 * 1_000_000_000 / row["wall_ns"], 6),
                    "throughput rate disagrees with observed wall time")
            require(row["timing_scope"] == "serial session, JSONL transport included; process start excluded",
                    "unexpected throughput timing scope")

    print("\n## All same-run comparisons\n")
    print("Ratios are competitor/Quervant. Above 1 favors Quervant; positive native gain favors the competitor.\n")
    print("| Lane | Q ms | T ms | J ms | Competitor | Ratio vs Q | 95% ratio CI | Competitor gain % | Native status | Interpretation |")
    print("| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- | --- |")
    statuses: Counter[str] = Counter()
    for lane_id, row in saved_analysis["lanes"].items():
        require(row["retained_blocks"] == 12 and row["excluded_blocks"] == [], "unexpected block retention")
        require(set(row["comparisons"]) == {"T", "J"}, "wrong comparison inventory")
        require(set(row["arm_absolute"]) == {"Q", "T", "J"}, "wrong absolute arm inventory")
        absolute = [row["arm_absolute"][arm]["median_block_value"] / 1_000_000 for arm in ("Q", "T", "J")]
        for arm in ("T", "J"):
            comp = row["comparisons"][arm]
            require(comp["baseline_arm"] == "Q" and comp["treatment_arm"] == arm,
                    "wrong comparison orientation")
            require(comp["status"] in ("IMPROVED", "REGRESSED", "INCONCLUSIVE"),
                    "non-comparable comparison")
            statuses[comp["status"]] += 1
            lo, hi = comp["ratio_ci_95"]
            print(f"| {lane_id} | {absolute[0]:.6f} | {absolute[1]:.6f} | {absolute[2]:.6f} | {arm}/Q | "
                  f"{comp['ratio_b_over_a']:.6f} | [{lo:.6f}, {hi:.6f}] | {comp['gain_percent']:.6f} | {comp['status']} | {qualification} |")
    require(sum(statuses.values()) == (2 if cold else 32), "wrong total comparison count")
    print(f"\nComparison-status counts: `{json.dumps(dict(statuses), sort_keys=True)}`.")
    print("\n## Serial throughput — descriptive windows\n")
    print("| Arm | Lane | Requests | Warmups | Window ms | Serial operations/s |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for arm, row in sorted(result["throughput_metrics"].items()):
        print(f"| {arm} | {row['lane_id']} | {row['requests']} | {row['warmups']} | "
              f"{row['wall_ns']/1_000_000:.6f} | {row['serial_ops_per_second']:.6f} |")
    print("\nThroughput is one serial window per engine, not a paired confidence estimate or saturated load.")
    print("\n## Preparation index metrics — descriptive\n")
    print("| Arm | N | Insert ms | Commit ms | Reopen ms | Index bytes |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for arm, corpora in sorted(result["index_metrics"].items()):
        for n, values in sorted(corpora.items(), key=lambda item: int(item[0])):
            print(f"| {arm} | {n} | {values['index_ns']/1e6:.6f} | {values['commit_ns']/1e6:.6f} | "
                  f"{values['reopen_ns']/1e6:.6f} | {values['index_bytes']} |")
    print("\nNative phase-duration fields (nanoseconds): `" +
          json.dumps(result["phase_durations_ns"], sort_keys=True) + "`.")
    print("\nPreparation total and cache lookup are separate fields; cache-HIT indexing metrics retain their original provenance.")
    outcome = "ACQUISITION_COMPLETE_AA_FAIL_EXPLORATORY" if failed_lanes else "ACQUISITION_COMPLETE_AA_PASS"
    print("\n" + outcome + " — full raw inventory, native reanalysis, oracles, policy and source agree.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"\nRESULT_INSPECTION_STOP: {error}", file=sys.stderr)
        raise SystemExit(2)
```

**Final coding-agent instruction:** execute this authorized plan through its defined terminal outcome. Do not ask whether to apply the patch, whether to continue after an A/A FAIL, whether to run the new warm study, or whether to finish its authorized delivery. Apply the exact predefined decisions; stop only when the scoped matrix requires it, and never improvise outside that matrix.
