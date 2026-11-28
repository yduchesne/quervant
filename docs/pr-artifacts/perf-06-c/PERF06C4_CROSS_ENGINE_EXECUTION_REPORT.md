# PERF06_C4_CROSS_ENGINE — Execution report

**Task:** `PERF06_C4_CROSS_ENGINE` · **Date (UTC):** 2026-11-27 ·
**Branch:** `dev/perf06-c4` · **PR:** [#133](https://github.com/yduchesne/quervant/pull/133) (existing, draft, unmerged)
· **Plan:** [`PERF06C4_CROSS_ENGINE_DETAILED_EXECUTION_PLAN.md`](PERF06C4_CROSS_ENGINE_DETAILED_EXECUTION_PLAN.md)

## 1. Disposition and scope

**Disposition: `PERF06_CROSS_ENGINE_PARTIAL`.**

| Study | Native status | Meaning |
| --- | --- | --- |
| Warm 16-lane Q/T/J | **`INCOMPLETE`** | Native A/A control instability blocked treatment; no warm comparison is claimed. |
| Process-cold 1-lane Q/T/J | **`COMPLETE`** | Full 12-block treatment, native A/A PASS, one T/Q and one J/Q comparison. |

Exactly one of the two planned studies qualifies, which is the plan's `PARTIAL`
definition (no pooled warm/cold conclusion). The warm study is preserved with its
captured control rows and exact native error; it was not retried or pruned. This is
a cross-engine comparison of the current production Quervant, Tantivy 0.25.0 and
Lucene 9.12.3 under one fixed exact-keyword/string-sort workload. It changes no
production engine, adapter, corpus, oracle, timer, estimator or threshold.

**QA waiver:** general Rust/Python unit and integration suites, formatting, Clippy,
coverage, doctests, documentation builds, benchmark compile/test QA and dependency
audits are **`NOT RUN — USER-AUTHORIZED COMPARATIVE-BENCHMARK WAIVER`**. None is
claimed as PASS. The native configuration validation, release builds, corpus/index
preparation, oracles, A/A control, acquisition, saved-data reanalysis and reporting
did run and are reported with actual outcomes.

## 2. Repository identities

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/perf06-c4` |
| PR | `#133`, `OPEN`, `isDraft: true`, unmerged, base `main`, head `dev/perf06-c4` |
| Reviewed C4 head (`C4_H`) / admitted starting head | `5c70d8cbf5872378ce094822878dcda7242eb0e0` |
| `origin/main` observed before and after the run | `f169fbba93e10d174cad8ab3bca55cdb7ae6aa03` (unchanged; no rebase) |
| Policy-amendment commit | `39bd9459060ffeee31f140fc2af1012a77e82886` |
| Configuration commit | `0148aaaa922c398a0b8b33581e72918ad212e67f` |
| `CROSS_EXECUTION` (recorded in `target/perf06c4-cross-engine-execution/execution-sha.txt`) | `0148aaaa922c398a0b8b33581e72918ad212e67f` |
| Runner `context.source_revision` / `build.source_revision` (both results) | `0148aaaa922c398a0b8b33581e72918ad212e67f` |
| Final delivery SHA | Recorded in the terminal handoff (not in this file) |

`git diff C4_H..CROSS_EXECUTION` contains only the four Appendix A Python files, the
two documentation amendments, this plan and the two new configurations. `crates/**`,
`benchmarks/pr15d/**` (adapters, corpus, protocol), dependency manifests/locks,
`statistics.py`, `reporting.py`, `artifacts.py`, `.github/**` and all historical
artifacts are unchanged. The prior C4 incremental result and its disposition
`PERF06_C4_QUALIFIED_TARGETS_NOT_MET_REVIEW_REQUIRED` are untouched.

## 3. Fixed amendment

The only executable change is the exact seven-line Appendix A patch across four
files, extending the existing advisory host-observation mode from `perf-06` to
`cross-engine` (five sites):

1. `benchmarks/quervant_bench/lean/cli.py` — `--readiness-advisory` help text.
2. `benchmarks/quervant_bench/lean/configuration.py` — default-configuration guard
   and validation guard accept `("perf-06", "cross-engine")`.
3. `benchmarks/quervant_bench/lean/preparation.py` — staging advisory predicate.
4. `benchmarks/quervant_bench/lean/runtime.py` — runtime advisory predicate.

Documentation was updated exactly per §5.4: `benchmarks/BM10_README.md` heading and
paragraph, and `docs/BENCHMARK_CONFIGURATION.md` §8 `mode` table row and paragraph.
`observe_readiness`, all thresholds, the native A/A decision, scheduling, sampling and
statistics are byte-unchanged. No engine, adapter, timing, query, corpus, oracle,
estimator or result-schema code was modified.

## 4. Configuration identities

| Study | Native configuration | UUID | Created (UTC) |
| --- | --- | --- | --- |
| Warm | `benchmarks/studies/cross-engine/warm/configurations/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-2026-11-27.json` | `0c67e2ea-f2be-4dc6-8a31-ef4f892f8008` | `2026-11-27T23:51:15Z` |
| Process-cold | `benchmarks/studies/cross-engine/cold-start/configurations/quervant-perf06c4-tantivy-lucene-lexical-sort-cold-start-2026-11-27.json` | `13cb8e69-0855-4239-b8ad-e78ef0ad62e0` | `2026-11-27T23:51:15Z` |

Both are `family="cross-engine"`, `baseline="Q"`, controls `AA`/`AA2`, arms
`Q=quervant/by-top-k/current`, `T=tantivy/default/current`, `J=lucene/default/current`,
`build={release:true, locked:true, sort_contract:"doc_id:keyword:utf8-lex-asc:v1",
tantivy_version:"0.25.0", prefilter_profile:"P2", quervant_feature:null,
baseline_ref:null}`, and `policy={blocks:12, slots_per_arm:2, warmups:5, samples:20,
bootstrap_resamples:10000, seed:20261122, min_blocks:4, min_gain_percent:0,
max_regression_percent:0, max_aa_gain_percent:15, exclude_blocks:{}, control_arms:[],
readiness:{intervals:4, interval_ms:250, max_busy_percent:25, max_steal_percent:2,
mode:"advisory"}}`. Workload: warm = `[10000,100000] × [absent,rare,medium,common] ×
[10,100] × [warm]`, `timed_operation="exact-term-search-plus-topk-projection"`; cold =
`10000/medium/k100/process-cold`, `timed_operation="process-launch-to-first-jsonl-response"`.
Both validated `VALID`. The cold configuration intentionally retains
`policy.warmups: 5`; the native cold collector recorded zero warmups.

## 5. Preparation

Warm and cold were staged serially before any acquisition, each `BUILT`:

| Study | State | Cache key | Prepared (UTC) | Build | Corpus | Index | Oracle |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| Warm | `BUILT` | `290a45c5e1324e2c919e74074714f318651f6acd3c22cd556f59354cbf1dc6fc` | `2026-11-27T23:52:49Z` | 76.906 s | 0.087 s | 6.076 s | 1.855 s |
| Cold | `BUILT` | `ec0d9b173d9984586c2e0ba0757216d7d8b0f9a2ae735754e3b653ef14b3c835` | `2026-11-27T23:54:07Z` | 74.610 s | 0.008 s | 1.497 s | 0.668 s |

Warm prepared six indexes (three engines × 10K/100K) and validated 48 lane/engine
oracle answers; cold prepared three indexes (10K) and validated three. Both
`run` invocations then reported `cache_status="HIT"` against these prepared inputs
(warm preparation lookup 0.111 s, cold 0.056 s). Index metrics below are
preparation-stage descriptive costs, not query-window samples; the original
preparation timestamp is `2026-11-27T23:52:49Z` / `2026-11-27T23:54:07Z`.

## 6. Acquisition

### 6.1 Warm

- Command: `python3 -u -m quervant_bench run --config <warm config> --scratch-root target/bm10-perf06c4-cross-engine`
- Single invocation; exit **4**; native result
  `benchmarks/studies/cross-engine/warm/results/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-2026-11-27-001.json`,
  run `803f75ac-9e64-42fe-aa45-e13eb0587c45`, sequence `1`, executed
  `2026-11-27T23:54:12Z`.
- Native status **`INCOMPLETE`**, `errors=["A/A control is unstable; comparative acquisition is blocked"]`.
- Captured: A/A **768** lane/slot rows, 3,840 warmups, 15,360 timed samples;
  treatment **0** rows (blocked before treatment). No throughput phase ran.
- A/A result: **15 lane PASS, 1 lane FAIL**
  (`10000/absent/k10/warm`, A/A gain `-1.140%`, 95% CI `[-24.702%, +0.434%]`,
  outside the `±15%` bound). No warm Q/T/J comparison exists.
- Host observations (advisory, informational): `readiness_index_pre` `clear` and
  `readiness_pre` `clear`, each four 250 ms intervals with busy `0.0%`/steal `0.0%`.
  `readiness_treatment`, `readiness_post` and the throughput checkpoints are absent
  because the native control blocked acquisition before them; this is disclosed and
  is not itself treated as an invalidity condition.
- Phases: host preflight 0.051 s, preparation total 2.053 s (cache lookup 0.111 s), A/A acquisition
  89.364 s, A/A analysis 0.778 s, total before save 93.297 s.

### 6.2 Process-cold

- Command: `python3 -u -m quervant_bench run --config <cold config> --scratch-root target/bm10-perf06c4-cross-engine`
- Single invocation; exit **0**; native result
  `benchmarks/studies/cross-engine/cold-start/results/quervant-perf06c4-tantivy-lucene-lexical-sort-cold-start-2026-11-27-001.json`,
  run `957653e1-aec2-4a01-b180-aebb346d6591`, sequence `1`, executed
  `2026-11-27T23:55:52Z`.
- Native status **`COMPLETE`**, `errors=[]`.
- Captured: A/A **48** rows / 960 timed samples / 0 warmups, all `PASS`; treatment
  **72** rows / 1,440 timed samples / 0 warmups = **2,400 fresh-process replies**.
- Host observations (advisory, informational): `readiness_index_pre` `clear` (one of
  four intervals reported busy `7.692%`, still `clear`), `readiness_pre` `clear`,
  `readiness_treatment` `clear`, `readiness_post` `clear`; all with steal `0.0%`.
- Phases: host preflight 0.050 s, preparation total 0.783 s (cache lookup 0.056 s), A/A acquisition
  38.224 s, A/A analysis 0.050 s, treatment acquisition 319.570 s, treatment analysis
  0.095 s, total before save 361.826 s.
- Build/context (both studies): `rustc 1.98.1`, `cargo 1.98.1`, `python 3.12.3`,
  `openjdk 21.0.13.1 2026-11-17`, Linux `6.18.33.2-microsoft-standard-WSL2`, `ext4`,
  controller CPU `0`, adapter CPU `2`, `quervant_strategy_feature_enabled=false`,
  `compiler_options="cargo --release --locked"`, `tantivy_version="0.25.0"`,
  `sort_contract="doc_id:keyword:utf8-lex-asc:v1"`.

## 7. Warm comparison

**No warm comparison can be reported.** Native A/A did not pass, so the runner
correctly refused treatment and published `INCOMPLETE`. There are no 32 warm
comparison rows and no 16×3 treatment absolute latencies to report, and no native
warm serial-throughput window. The preserved control evidence is:

| Item | Actual value |
| --- | --- |
| A/A rows / timed samples / warmups | 768 / 15,360 / 3,840 |
| A/A lanes PASS / FAIL | 15 / 1 |
| Failing lane | `10000/absent/k10/warm` |
| Failing lane A/A gain / 95% CI | `-1.140%` / `[-24.702%, +0.434%]` |
| Native error | `A/A control is unstable; comparative acquisition is blocked` |
| Treatment rows captured | 0 |

Warm preparation index metrics (descriptive, preparation stage; segment count 1):

| Arm | N | Insert | Commit | Reopen | Index bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q | 10,000 | 21.106 ms | 114.337 ms | 20.932 ms | 1,406,726 |
| T | 10,000 | 0.538 ms | 57.177 ms | 0.175 ms | 220,270 |
| J | 10,000 | 269.144 ms | 274.671 ms | 54.321 ms | 186,052 |
| Q | 100,000 | 214.458 ms | 1,101.923 ms | 211.031 ms | 14,312,375 |
| T | 100,000 | 129.635 ms | 85.220 ms | 0.195 ms | 2,248,052 |
| J | 100,000 | 959.360 ms | 658.221 ms | 56.091 ms | 1,858,642 |

## 8. Process-cold comparison

Ratios are competitor/Quervant, and native gain is `100 * (1 - ratio)`.
Ratio > 1 and negative native gain mean the **competitor is slower**; ratio < 1
and positive native gain mean the **competitor is faster**. Ratio = 1 means zero
native gain. Native `IMPROVED`/`REGRESSED` describes the competitor relative to Q.

| Lane | Q wall (ms) | T wall (ms) | J wall (ms) | Competitor | Ratio vs Q | 95% ratio CI | Competitor gain % | Native status | Blocks |
| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- | ---: |
| `10000/medium/k100/process-cold` | 39.078856 | 1.930238 | 599.042171 | T/Q | 0.049416 | [0.048871, 0.050003] | +95.058 | IMPROVED | 12/12 |
| `10000/medium/k100/process-cold` | 39.078856 | 1.930238 | 599.042171 | J/Q | 15.331842 | [15.295242, 15.408109] | -1433.184 | REGRESSED | 12/12 |

Component medians over all 480 captured cold replies per arm (descriptive; opening,
query and residual medians need not sum to the wall median). Every observation
satisfies `wall = open + query + residual` exactly (maximum decomposition error
`0 ns`); all wall/open/query durations are positive and residuals nonnegative.

| Arm | Wall (ms) | Index open (ms) | Query engine (ms) | Other residual (ms) |
| --- | ---: | ---: | ---: | ---: |
| Q | 39.086 | 22.578 | 14.436 | 1.941 |
| T | 1.917 | 0.250 | 0.187 | 1.456 |
| J | 600.695 | 434.545 | 97.376 | 69.310 |

Cold preparation index metrics (10K, segment count 1): Q insert 19.722 ms / commit
111.946 ms / reopen 20.560 ms / 1,406,726 bytes; T 1.269 ms / 54.261 ms / 0.184 ms /
220,270 bytes; J 271.476 ms / 286.755 ms / 52.604 ms / 186,052 bytes. Cold has no
throughput phase by contract.

## 9. Saved-data acceptance

- **Cold:** native `analyze` reanalysis equals the saved analysis exactly; native
  control reanalysis equals the saved control analysis, with A/A `PASS` on its single
  lane; 48 control and 72 treatment rows with the exact 24-rows-per-lane/arm
  inventory; 20 positive samples per row; all `oracle_ok=true`; zero warmups; 12
  retained blocks and no exclusions; index inventories and positive metrics verified;
  Appendix B exit **0** (`VALID_COMPLETE`).
- **Warm:** Appendix B exit **4**, honestly summarizing the `INCOMPLETE` study with
  its captured counts and exact native error; full-matrix reanalysis is intentionally
  skipped for non-`COMPLETE` results. No partial subset was promoted to a verdict.
- No raw result was modified, no threshold was changed and no missing sample was
  reconstructed.

## 10. Command/status table

| Step | Status |
| --- | --- |
| `git fetch`, branch/PR admission, `C4_H`/remote equality | PASS |
| Appendix A `git apply` (exact patch) | PASS |
| Policy-amendment commit `39bd945` | PASS |
| `prepare` warm / cold (one call each) | PASS |
| `validate` warm / cold | PASS (`VALID`, `VALID`) |
| Configuration commit `0148aaa` + `execution-sha.txt` | PASS |
| `stage` warm / cold (serial) | PASS (`BUILT`, `BUILT`) |
| Native warm `run` (one invocation) | exit 4, `INCOMPLETE` (A/A unstable) |
| Native cold `run` (one invocation) | exit 0, `COMPLETE` |
| Native warm `report` + Appendix B | PASS (honest incomplete summary, exit 4) |
| Native cold `report` + `analyze` + Appendix B | PASS (exit 0, reanalysis equal) |
| Unit/integration/format/lint/coverage/doc/dependency QA | **NOT RUN — USER-AUTHORIZED COMPARATIVE-BENCHMARK WAIVER** |
| Hosted CI | Not initiated, waited on, rerun or gated |

## 11. Decision ledger and failures

| Rule | Trigger | Action | Evidence / stage |
| --- | --- | --- | --- |
| D01 | Existing C4 branch/PR at admitted source | Reused branch and PR #133; no duplicate PR | refs/metadata; setup |
| D06 | Disjoint untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` | Preserved untouched; exact-path staging only | status; setup/delivery |
| D11 | Advisory load observations clear (cold included one `7.692%` busy interval, still `clear`) | Recorded as informational; acquisition continued; no wait/recheck/retune | native `controls`; all stages |
| D18 | Warm's sole failure was the exact native A/A-instability error | Preserved warm `INCOMPLETE`; ran the already-staged, uninvoked cold config once with its own control | warm result + cold stage/result; acquisition |
| D17 | Warm run exited 4 with saved `INCOMPLETE` | No retry, no pruning, no reconstructed samples; reported actual counts | warm result/log; acquisition |
| D19 | Cold `COMPLETE`; Quervant slower than Tantivy (T/Q `0.049416`) | Reported both competitor comparisons as measured evidence; no threshold change or retry | cold result; reporting |
| D25 | Only allowlisted artifacts pending after measurement | Exact-path commit; non-force push to `dev/perf06-c4`; append PR description | delivery |
| D28 | Ordinary hosted CI may start from the push | Left alone; not gated | delivery |

D14, D23 and D27 were checked but did not trigger. There was no shared
source/oracle/protocol failure (D14); `origin/main` remained at
`f169fbba93e10d174cad8ab3bca55cdb7ae6aa03`, so there was no main advancement
(D23); and no non-sample Git hook was present or bypassed (D27). The original
execution therefore applied D01, D06, D11, D17, D18, D19, D25 and D28.

No other rule fired. No unexpected source, oracle, protocol, build or cache failure
occurred; the single warm failure is a native measurement-validity (A/A) outcome.

## 12. Interpretation and limits

- **Cold:** Tantivy 0.25.0 was substantially faster than Quervant for the first
  complete JSONL reply on `10000/medium/k100/process-cold` (T/Q ratio `0.0494`, native
  gain `+95.06%`, 12/12 blocks, CI excludes 1.0). Lucene 9.12.3 was substantially
  slower (J/Q ratio `15.33`, native gain `-1433.18%`, 12/12 blocks). These are the
  only comparative conclusions this task supports.
- **Warm:** no comparative conclusion exists because the native A/A control failed on
  one of sixteen lanes. A/A failure is a measurement-validity outcome, not evidence
  that any engine is faster or slower; it is not attributed to a host-load advisory.
- Residual limits, restated: this is the fixed local exact-keyword, string-sort,
  exact-count, Top-K projection workload — not general search-engine superiority,
  relevance scoring, remote/RustFS or distributed performance. Process-cold does not
  mean a cold OS page cache; the residual is not isolated process startup or I/O.
  Warm serial throughput is one native window per engine where measured (absent here),
  not saturated/concurrent throughput or a paired confidence result. Host-load
  observations are informational; A/A passing is a statistical control, not proof of
  a noise-free host. General correctness/QA was intentionally not rerun; the advisory
  extension is validated operationally by this benchmark path only. Historical and
  current campaigns are separate; no summed A/B/C gain, causal decomposition or
  unpaired historical latency claim is made.
- No optimization, tuning, rollback, merge or baseline promotion was performed, and
  the earlier C4 incremental-qualification disposition is unchanged.

## 13. Delivery and remaining action

- New canonical artifacts: the two configurations, the two native results (warm
  `INCOMPLETE`, cold `COMPLETE`) and this report, plus one dated roadmap paragraph.
  Build caches, run logs, the extracted helper and reanalysis outputs remain under the
  task's ignored `target/` directories.
- Delivery uses a non-force push to the existing `dev/perf06-c4` branch and one
  append to the existing PR #133 description; the PR is not marked ready, not merged
  and no review is requested. Final/remote SHAs and the observed CI state are recorded
  in the terminal handoff, not in a follow-up commit.
- Independent review and any adoption decision remain maintainer-owned and open. The
  natural next step, if warm behaviour is still required, is a separately authorized
  new warm acquisition (the single warm invocation for this plan is exhausted); no
  retry is authorized by this report.

## 14. Independent review corrections

Review basis: delivery commit `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b`;
measurement source `0148aaaa922c398a0b8b33581e72918ad212e67f`. The corrections
below supersede the earlier presentation at that delivery commit.

| Fix | Correction |
| --- | --- |
| F01 | Corrected the sign explanation in §8; ratios and native comparison tables are unchanged. |
| F02 | Distinguished preparation totals from cache lookups in §6.1 and §6.2. |
| F03 | Corrected applied-rule attribution: D17 for the warm stop, D18 for cold continuation, and D19 for Quervant's measured loss to Tantivy; D14/D23/D27 did not trigger. |
| F04 | Corrected the two result-link targets in the new cross-engine roadmap entry. |

These corrections preserve this original experiment's configurations, result
JSON, source revisions, all measurements and both study statuses. Its disposition
remains **`PERF06_CROSS_ENGINE_PARTIAL`**; its warm treatment and throughput were
not acquired. A separately identified new warm acquisition is prospectively
authorized by the autonomous completion plan below. That new experiment must not
replace this result or backfill its missing observations. General test and quality
suites remain waived by the user.

Autonomous completion plan: [PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md](PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md).
