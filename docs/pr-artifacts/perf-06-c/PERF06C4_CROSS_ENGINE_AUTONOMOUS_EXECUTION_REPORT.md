# PERF06_C4_CROSS_ENGINE_AUTO — Execution report

**Task:** `PERF06_C4_CROSS_ENGINE_AUTO` · **Date (UTC):** 2026-11-28 ·
**Branch:** `dev/perf06-c4` · **PR:** [#133](https://github.com/yduchesne/quervant/pull/133) (existing, draft, unmerged)
· **Plan:** [`PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md`](PERF06C4_CROSS_ENGINE_AUTONOMOUS_COMPLETION_PLAN.md)

> **Subsequent status and reporting amendment — 2026-11-27 (America/Los_Angeles).**
> This report records execution and delivery before [PR #133](https://github.com/yduchesne/quervant/pull/133)
> merged at `44caa511f6e147836c446b970845f03de45eb515` (2026-11-28 UTC).
> Its draft/unmerged, readiness-preserved and maintainer-review statements describe
> that historical state. This amendment corrects only the A/A explanation, the
> Tantivy comparator wording and D16's rule attribution. Configurations, raw samples,
> numeric tables, native classifications and statistical qualification are unchanged.
> The warm comparison remains exploratory and statistically unqualified.

## 1. Disposition

**Disposition: `PERF06_CROSS_ENGINE_WARM_ACQUIRED_AA_FAIL_DESCRIPTIVE`.**

| Dimension | Actual state |
| --- | --- |
| Acquisition | **Complete** — one invocation, exit 0, full 16-lane treatment and three serial-throughput windows |
| Native status | **`INCONCLUSIVE`** (predeclared advisory A/A continued after one native statistical FAIL) |
| Statistical control qualification | **`AA_FAIL_EXPLORATORY`** — 15/16 A/A lanes PASS, `10000/absent/k10/warm` FAIL |
| Delivery | Delivered by non-force push and PR-body append (final identities in the terminal receipt) |
| Maintainer adoption | Open; no merge, readiness change or baseline promotion |

This is a completed acquisition with an honestly reported failed statistical control. All
32 treatment comparisons and nominal confidence intervals are **exploratory and not
statistically qualified**. Completing the acquisition does not repair the A/A control, and
nothing here qualifies an optimization.

## 2. Authorization and scope

The execution was authorized by the user with an explicit no-further-authorization
instruction; no permission checkpoint was inserted at any stage, including after the
A/A FAIL. The host was assumed idle; native busy/steal observations were informational
only. Both advisory modes were predeclared in the new configuration
(`readiness.mode="advisory"` and `aa_mode="advisory"`).

**QA waiver:** unit/integration suites, fmt, Clippy, coverage, doctests, documentation
builds, dependency audits, benchmark compile-only QA and script-test suites are
**`NOT RUN — USER-AUTHORIZED WAIVER`** and are not claimed as PASS. Native configuration
validation, locked release builds, index construction, exact-result oracle checks, timed
acquisition, saved-data reanalysis and rendering did run (they are operational benchmark
steps, not the waived QA campaign).

The only executable change is the exact Appendix A patch (four Python files). Production
`quervant-core`, adapters, corpus/protocol, `preparation.py`, `statistics.py`,
`artifacts.py`, timers, schedules, thresholds and dependencies are unchanged.

## 3. Identities

| Item | Value |
| --- | --- |
| Reviewed START / admitted head | `0917d94d1c3b9f4ee7dcd887b166a8f3a5a2824b` |
| Fresh `origin/main` observed | `f169fbba93e10d174cad8ab3bca55cdb7ae6aa03` (unchanged; no rebase) |
| Policy commit | `3ad26e555bfe48af9a8fd5a4c4061ba47c553bbd` |
| Configuration commit / `AUTO_EXECUTION` | `4a0d3b6f915ef8b756e023b0004bf2edf4804625` |
| Configuration | `benchmarks/studies/cross-engine/warm/configurations/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-aa-advisory-2026-11-28.json` |
| Configuration UUID / created | `f56c9e49-2e38-4834-941b-1019877565dd` / `2026-11-28T01:10:28Z` |
| Result | `benchmarks/studies/cross-engine/warm/results/quervant-perf06c4-tantivy-lucene-lexical-sort-warm-aa-advisory-2026-11-28-001.json` |
| Result run ID / sequence / executed | `efde9d26-4e00-4b5c-85b8-104d03ae0f54` / `1` / `2026-11-28T01:12:01Z` |
| Source/build revision (both context fields) | `4a0d3b6f915ef8b756e023b0004bf2edf4804625` |
| Plan SHA-256 (supplied = repository copy) | `123dbc252fccfcd8ba4a48ba9422799c9a697e5367a830e7a71a9d01c8a88bcc` |
| Build environment | `rustc 1.98.1`, `cargo 1.98.1`, `python 3.12.3`, OpenJDK 21.0.13.1; Linux WSL2 `6.18.33.2-microsoft-standard-WSL2`, `ext4`, controller CPU 0, adapter CPU 2 |

`git diff 0917d94..4a0d3b6` contains only the ten Appendix A files, the plan and the new
configuration; `crates/**`, adapters, corpus/protocol, `preparation.py`, `statistics.py`,
`artifacts.py`, dependency files, workflows and all historical JSON are identical.

## 4. Original review fixes (F01–F04)

| Fix | Correction applied |
| --- | --- |
| F01 | The original report's §8 sign explanation now states `gain = 100*(1-ratio)`; ratio > 1 with negative gain means the competitor is slower. Numeric tables unchanged. |
| F02 | §6.1/§6.2 now label 2.053 s and 0.783 s as preparation totals and show the real cache lookups (0.111 s / 0.056 s). |
| F03 | Ledger attribution corrected: D17 for the warm stop, D18 for cold continuation, D19 for Quervant's measured loss to Tantivy; D14/D23/D27 marked checked-but-not-triggered. |
| F04 | The two roadmap result links corrected from `../../benchmarks/` to `../benchmarks/`. |

The original experiments are immutable: the original warm result remains `INCOMPLETE`
with 768 control rows and no treatment; the original cold result remains `COMPLETE`
(48 control / 72 treatment rows, 2,400 fresh-process replies); the original
disposition remains `PERF06_CROSS_ENGINE_PARTIAL`. Cold was not rerun or pooled.

## 5. Preparation

| Item | Actual value |
| --- | --- |
| Native state | `BUILT` |
| Cache key | `da593298f8d950b11976762122976bf845ee4023d24ef1dec8a7f2bee89a0c40` |
| Prepared (UTC) | `2026-11-28T01:11:57Z` |
| Build | 73.966 s |
| Corpus generation | 0.085 s |
| Index construction | 6.054 s |
| Oracle validation | 1.830 s |
| Lookup | 0.0000298 s |

Preparation built the three locked release adapters, six indexes (Q/T/J × 10K/100K) and
validated 48 untimed lane/engine oracle answers. The subsequent `run` reported
`cache_status="HIT"` with the same `prepared_utc`, i.e. it reused and revalidated these
prepared inputs rather than rebuilding them.

## 6. Acquisition

- Command: `python3 -u -m quervant_bench run --config <new config> --scratch-root target/bm10-perf06c4-cross-engine-autonomous`
- Single invocation; exit **0**; native status **`INCONCLUSIVE`**; `errors=[]`.
- Captured: A/A **768** rows / **15,360** timed samples / **3,840** warmups; treatment
  **1,152** rows / **23,040** timed samples / **5,760** warmups; throughput **3**
  windows / **300** requests / **15** warmups. All rows `oracle_ok=true`, 20 positive
  samples each, no strategy markers.
- Advisory gate metadata (saved by the native runner):
  `{"mode":"advisory","status":"FAIL","failed_lanes":["10000/absent/k10/warm"],"continued_after_failure":true}`;
  `context.aa_control_mode="advisory"`.
- Host observations (informational): all six checkpoints `clear` with busy `0.0%` /
  steal `0.0%` in every 250 ms interval (`readiness_index_pre`, `readiness_pre`,
  `readiness_treatment`, `readiness_post`, `readiness_throughput_pre`,
  `readiness_throughput_post`).
- Phases: host preflight 0.050 s; preparation total 1.945 s (cache lookup 0.110 s);
  A/A acquisition 87.563 s; A/A analysis 0.746 s; treatment acquisition 100.908 s;
  treatment analysis 1.492 s; throughput acquisition 1.037 s; total before save 198.802 s.

## 7. A/A control — 15 PASS / 1 FAIL

**EXPLORATORY: the A/A control failed on `10000/absent/k10/warm` (gain +1.864%, 95% CI
[−5.733%, +19.529%], upper bound outside the retained +15% condition).** Every
comparison below is therefore exploratory and statistically unqualified.

| Control lane | Gain % | 95% gain CI | Native status |
| --- | ---: | --- | --- |
| 10000/absent/k10/warm | 1.863506 | [-5.732673, 19.528730] | FAIL |
| 10000/absent/k100/warm | -0.534717 | [-2.085466, 1.454544] | PASS |
| 10000/common/k10/warm | 0.779547 | [-0.467814, 2.637812] | PASS |
| 10000/common/k100/warm | 0.902174 | [-0.549979, 2.113923] | PASS |
| 10000/medium/k10/warm | 1.139155 | [-2.426037, 2.790751] | PASS |
| 10000/medium/k100/warm | -0.107903 | [-1.720586, 2.133502] | PASS |
| 10000/rare/k10/warm | 0.953599 | [-0.412751, 2.026479] | PASS |
| 10000/rare/k100/warm | 0.228457 | [-0.291443, 1.177976] | PASS |
| 100000/absent/k10/warm | -3.794865 | [-4.881943, 0.424722] | PASS |
| 100000/absent/k100/warm | 0.049841 | [-2.599626, 0.984838] | PASS |
| 100000/common/k10/warm | -0.333890 | [-1.405639, 0.675360] | PASS |
| 100000/common/k100/warm | -0.346449 | [-1.367151, 1.652957] | PASS |
| 100000/medium/k10/warm | 0.394090 | [-1.117479, 1.833256] | PASS |
| 100000/medium/k100/warm | -0.291103 | [-1.682665, 1.701559] | PASS |
| 100000/rare/k10/warm | -1.437456 | [-2.930758, 4.920979] | PASS |
| 100000/rare/k100/warm | 0.181692 | [-1.062185, 2.137159] | PASS |

The 10K absent-K10 control lane failed because its 95% gain interval extends to
+19.528730%, above the unchanged +15% upper control bound. Its +1.863506% point
estimate is within the ±15% bound. No causal explanation is established. No lane
was retried or pruned.

## 8. All 32 warm latency comparisons

Ratios are competitor/Quervant; native gain is `100 * (1 - ratio)`. Ratio < 1 means the
competitor is faster; ratio > 1 with negative gain means the competitor is slower. Native
`IMPROVED`/`REGRESSED` describes the competitor relative to Q. Every row is
**EXPLORATORY — A/A FAILED**. The Q/T/J columns are the 48 absolute lane/arm block
medians (native `median_block_value`, ms).

| Lane | Q ms | T ms | J ms | Competitor | Ratio vs Q | 95% ratio CI | Competitor gain % | Native status | Interpretation |
| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- | --- |
| 10000/absent/k10/warm | 0.031188 | 0.004888 | 0.262691 | T/Q | 0.158840 | [0.148707, 0.169907] | 84.116033 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/absent/k10/warm | 0.031188 | 0.004888 | 0.262691 | J/Q | 8.437360 | [8.021741, 9.041953] | -743.736033 | REGRESSED | EXPLORATORY — A/A FAILED |
| 10000/absent/k100/warm | 0.030951 | 0.005250 | 0.208065 | T/Q | 0.168911 | [0.159746, 0.199023] | 83.108921 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/absent/k100/warm | 0.030951 | 0.005250 | 0.208065 | J/Q | 6.160082 | [5.787878, 7.371167] | -516.008190 | REGRESSED | EXPLORATORY — A/A FAILED |
| 10000/common/k10/warm | 1.725411 | 0.070588 | 0.291579 | T/Q | 0.040815 | [0.040319, 0.041375] | 95.918466 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/common/k10/warm | 1.725411 | 0.070588 | 0.291579 | J/Q | 0.170319 | [0.161560, 0.181067] | 82.968108 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/common/k100/warm | 1.802512 | 0.137627 | 1.756460 | T/Q | 0.076461 | [0.075448, 0.077363] | 92.353942 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/common/k100/warm | 1.802512 | 0.137627 | 1.756460 | J/Q | 0.977829 | [0.910291, 1.140743] | 2.217125 | INCONCLUSIVE | EXPLORATORY — A/A FAILED |
| 10000/medium/k10/warm | 0.796586 | 0.034963 | 1.451957 | T/Q | 0.043756 | [0.043352, 0.044520] | 95.624442 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/medium/k10/warm | 0.796586 | 0.034963 | 1.451957 | J/Q | 1.808105 | [1.714829, 1.919525] | -80.810539 | REGRESSED | EXPLORATORY — A/A FAILED |
| 10000/medium/k100/warm | 0.901550 | 0.106827 | 8.003333 | T/Q | 0.118795 | [0.117456, 0.121713] | 88.120483 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/medium/k100/warm | 0.901550 | 0.106827 | 8.003333 | J/Q | 8.933571 | [8.704772, 8.981153] | -793.357140 | REGRESSED | EXPLORATORY — A/A FAILED |
| 10000/rare/k10/warm | 0.039101 | 0.010200 | 0.483644 | T/Q | 0.254704 | [0.232416, 0.279397] | 74.529595 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/rare/k10/warm | 0.039101 | 0.010200 | 0.483644 | J/Q | 12.005708 | [11.293619, 13.642111] | -1100.570789 | REGRESSED | EXPLORATORY — A/A FAILED |
| 10000/rare/k100/warm | 0.038713 | 0.011913 | 0.354017 | T/Q | 0.308240 | [0.235216, 0.318256] | 69.175963 | IMPROVED | EXPLORATORY — A/A FAILED |
| 10000/rare/k100/warm | 0.038713 | 0.011913 | 0.354017 | J/Q | 9.094371 | [8.304022, 9.641386] | -809.437125 | REGRESSED | EXPLORATORY — A/A FAILED |
| 100000/absent/k10/warm | 0.159127 | 0.014888 | 0.263979 | T/Q | 0.092717 | [0.087020, 0.095724] | 90.728263 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/absent/k10/warm | 0.159127 | 0.014888 | 0.263979 | J/Q | 1.654093 | [1.499826, 1.822266] | -65.409332 | REGRESSED | EXPLORATORY — A/A FAILED |
| 100000/absent/k100/warm | 0.150352 | 0.015075 | 0.200265 | T/Q | 0.099320 | [0.095211, 0.100748] | 90.067958 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/absent/k100/warm | 0.150352 | 0.015075 | 0.200265 | J/Q | 1.312628 | [1.247237, 1.535584] | -31.262794 | REGRESSED | EXPLORATORY — A/A FAILED |
| 100000/common/k10/warm | 17.200336 | 0.522994 | 0.307917 | T/Q | 0.030563 | [0.030242, 0.031097] | 96.943683 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/common/k10/warm | 17.200336 | 0.522994 | 0.307917 | J/Q | 0.018148 | [0.017158, 0.019180] | 98.185203 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/common/k100/warm | 16.906154 | 0.603233 | 2.266492 | T/Q | 0.035651 | [0.035365, 0.036318] | 96.434944 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/common/k100/warm | 16.906154 | 0.603233 | 2.266492 | J/Q | 0.133652 | [0.120801, 0.153245] | 86.634770 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/medium/k10/warm | 7.782368 | 0.150302 | 1.507019 | T/Q | 0.019502 | [0.019117, 0.020052] | 98.049822 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/medium/k10/warm | 7.782368 | 0.150302 | 1.507019 | J/Q | 0.193931 | [0.184179, 0.215356] | 80.606916 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/medium/k100/warm | 7.769093 | 0.235166 | 8.330350 | T/Q | 0.030297 | [0.029745, 0.031076] | 96.970278 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/medium/k100/warm | 7.769093 | 0.235166 | 8.330350 | J/Q | 1.079985 | [1.058892, 1.097282] | -7.998524 | REGRESSED | EXPLORATORY — A/A FAILED |
| 100000/rare/k10/warm | 0.164165 | 0.021738 | 0.509669 | T/Q | 0.132099 | [0.129913, 0.135020] | 86.790083 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/rare/k10/warm | 0.164165 | 0.021738 | 0.509669 | J/Q | 3.038280 | [2.826321, 3.227381] | -203.827959 | REGRESSED | EXPLORATORY — A/A FAILED |
| 100000/rare/k100/warm | 0.158577 | 0.021775 | 0.351030 | T/Q | 0.137111 | [0.128688, 0.138308] | 86.288894 | IMPROVED | EXPLORATORY — A/A FAILED |
| 100000/rare/k100/warm | 0.158577 | 0.021775 | 0.351030 | J/Q | 2.185727 | [2.046496, 2.327369] | -118.572735 | REGRESSED | EXPLORATORY — A/A FAILED |

Comparison-status counts: **`{"IMPROVED": 20, "INCONCLUSIVE": 1, "REGRESSED": 11}`**.
Tantivy had lower measured latency than Quervant in all 16 warm lanes
(T/Q ratio 0.0195–0.3082). Lucene is
faster than Quervant in 4 of 16 lanes (10K common K10; 100K common K10/K100; 100K medium
K10), inconclusive in 10K common K100, and slower in the remaining 11. All of this is
**exploratory** because the A/A control failed.

## 9. Native serial throughput (descriptive)

| Arm | Lane | Requests | Warmups | Window ms | Serial operations/s |
| --- | --- | ---: | ---: | ---: | ---: |
| J | 10000/medium/k10/warm | 100 | 5 | 294.002185 | 340.133527 |
| Q | 10000/medium/k10/warm | 100 | 5 | 100.572163 | 994.310921 |
| T | 10000/medium/k10/warm | 100 | 5 | 11.512256 | 8686.394743 |

One serial window per engine over a warm session, JSONL transport included and process
startup excluded. These are descriptive only: no paired confidence interval, no saturated
or concurrent-throughput claim.

## 10. Index, host and phase observations

Preparation index metrics (descriptive; segment count 1 for every index; a cache HIT
retains the `2026-11-28T01:11:57Z` preparation provenance):

| Arm | N | Insert ms | Commit ms | Reopen ms | Index bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| J | 10000 | 284.294974 | 276.054862 | 52.367213 | 186052 |
| J | 100000 | 1005.573303 | 670.601633 | 47.014339 | 1858642 |
| Q | 10000 | 20.168674 | 110.635202 | 20.093073 | 1406726 |
| Q | 100000 | 205.737693 | 1089.223187 | 209.544544 | 14312375 |
| T | 10000 | 0.489807 | 52.912218 | 0.285504 | 220270 |
| T | 100000 | 121.347748 | 86.396173 | 0.186702 | 2248052 |

Native host diagnostics (informational, never a gate): controller CPU 0, adapter CPU 2,
Linux WSL2 `ext4`; all six readiness checkpoints `clear` with busy `0.0%` / steal `0.0%`.
Preparation total (1.945 s) and cache lookup (0.110 s) are separate fields; preparation
subcomponents are not added to the total again.

## 11. Acceptance, decisions and failures

| Gate | Status | Evidence |
| --- | --- | --- |
| E01 Source admission | PASS | START/remote/`main` verified; branch and PR reused; PR readiness preserved; old artifacts untouched |
| E02 Fixed implementation | PASS | Ten post-patch blobs matched the prescribed hashes; plan supplied=copy SHA-256; delta confined to the allowed paths |
| E03 Inputs | PASS | Config native-`VALID` and inspector-equal; `AUTO_EXECUTION` committed; stage `BUILT`; six indexes and 48 oracles; run cache `HIT` |
| E04 Acquisition | PASS | One native `run`, exit 0; A/A, treatment and all three throughput windows executed; authoritative counts reported |
| E05 Saved-data acceptance | PASS | Inspector exit 0 = `ACQUISITION_COMPLETE_AA_FAIL_EXPLORATORY`; native reanalysis equal; raw/control/gate/inventory/throughput predicates satisfied |
| E06 Reporting | PASS | F01–F04 corrected; 16 A/A rows, 32 comparisons, 48 absolute summaries and 3 throughput windows present; exploratory labeling explicit; cold reused separately; QA not claimed |
| E07 Delivery | PASS | Exact-path commit, non-force push and PR-body append; remote/PR identity in terminal receipt; draft/unmerged preserved |

| Rule | Trigger → action |
| --- | --- |
| D01 | Exact START, matching branch and open draft PR → reused them; no new PR or readiness change |
| D05 | Disjoint untracked `f2-ci-status.txt` → left untouched; exact-path staging only |
| D10 | Host diagnostics all `clear` → recorded and continued; no wait, retune or rerun |
| D13 | Full eligible A/A with one native statistical FAIL → runtime continued treatment and throughput; all comparisons reported as exploratory; top status `INCONCLUSIVE` |
| D16 | Full treatment data include Quervant losses and a native `INCONCLUSIVE` comparison → reported every value and completed reporting without treating unfavorable performance as a harness defect or retuning/repeating the run. |
| D23 | Ordinary CI may start from the push → left alone; not a gate |

Checked but not triggered: D02 (local branch already at START), D04, D06 (no existing
task config/result), D07, D08, D09, D11 (stage succeeded first attempt), D12, D14, D15,
D17, D18, D19, D20 (`origin/main` did not advance), D21 (non-force push and
PR edit succeeded), D22 (no non-sample hooks), D24.

Failure classification: the single control-lane FAIL is a **measurement-control outcome**
(native statistical A/A), not a source, oracle, protocol, timer or environment failure. No
incorrectly labelled flaky/pre-existing cause is asserted.

## 12. Residual limits and delivery

- One host, one fixed exact-keyword / exact-count / UTF-8 string-sort / Top-K projection
  workload. This is not a general search-engine superiority, relevance/BM25 parity,
  remote/RustFS or distributed-performance claim.
- Because the A/A control failed on one lane, every treatment ratio, classification and
  nominal 95% interval above is **exploratory and statistically unqualified**; a
  significant treatment interval does not repair the control and no passing-subset claim
  is made.
- Serial throughput is one window per engine, not saturated/concurrent throughput; A/A
  passing (where it holds) is not proof of a noise-free host; actual response payloads
  are not saved beyond the oracle flags; waived suites were not executed.
- The original warm `INCOMPLETE` and cold `COMPLETE` results are unchanged and are not
  pooled with this new study. The prior `PERF06_CROSS_ENGINE_PARTIAL` disposition and the
  earlier C4 incremental-qualification verdict remain as written.
- Delivery is a non-force push to the existing `dev/perf06-c4` branch plus one appended PR
  section; the PR remains draft and unmerged. No optimization, adoption, rollback, merge
  or baseline promotion was performed; maintainer review is outstanding.
