# PERF-05-C — B-Only Warm-Query Qualification Against Retained Historical A

**Prescriptive coding-agent execution plan — 2026-11-23 — v1.0**
**Decision:** `PERF05C_B_ONLY_HISTORICAL_A_NO_RUSTFS_NO_UNNECESSARY_WORK`
**Repository:** `yduchesne/quervant` · **existing branch:** `dev/perf05-physical-execution-series` · **existing PR:** [#117](https://github.com/yduchesne/quervant/pull/117) · **do not create another PERF-05 PR**.

> **MANDATORY:** This document authorizes a bounded, B-only warm-query acquisition. Do **not** benchmark, compile, index, run, or profile an historical A executable; do **not** run Tantivy or Lucene; do **not** start RustFS. Existing indexed local-filesystem Quervant is the production boundary relevant to this study. PERF-05-C is **not** a paired A/B study, and no statistics may pretend that samples from separate sessions were paired.

## 0. Immutable identities, outcome and precedence

| Role | Exact authoritative identity |
| --- | --- |
| A: **retained historical measurement**, never executed in C | `benchmarks/studies/cross-engine/warm/results/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json` |
| A result Git blob SHA-1 (run `git hash-object`) | `a809f0362553e4e5c93ac1593ef478e8eef6a865` |
| A result `run_id` | `f2df1d40-2eee-4fcb-9593-ba8433e08c4a` |
| A result `configuration_id` | `c4083f1e-4ce2-4477-b282-04c4d40b187f` |
| A **actual measured** source, from `context.source_revision` and `context.build.source_revision` | `256501f0e700ed199f316e79d128389375177530` |
| Pre-PERF-05 `main` base (separate from measured A source) | `9775bfca4c58a27e65ca28c1d705efad00a65ec8` |
| B: **only source to compile/index/measure** | `ee18ed63bbeeb54b544393ee0f676987ff9987d1` (PERF-05-B1…B5) |
| B4 predecessor required in B's history | `3b25a76b99f699c45aa2050c4f889880a138948a` |
| B5 successful hosted Rust CI | run `45126782770` (Rust CI #522); no reason to repeat full Rust QA without a Rust source change |
| Existing B5 status | `B5_IMPLEMENTED_LOCAL_QA_PASS_CI_GREEN_RUSTFS_NOT_REQUIRED_FOR_LOCAL_WARM_QUERY` (independent source review; PERF-05 is not yet performance-qualified) |
| Output study | `benchmarks/studies/perf-05/warm/{configurations,results}/` using permanent `<name>-<UTC-date>` naming |
| Configuration name, new and unique | `quervant-perf05-b-only-warm` |
| Required benchmarks | B only, one measured campaign, **16 warm lanes**, one B binary and B-only indexes at 10K and 100K |
| Comparator | Immutable historical Q-arm *absolute* measurements, descriptive only; no cross-session paired confidence interval |

**Authority order:** latest maintainer decisions in this plan (B-only, no RustFS, no unnecessary operations) > earlier proposed PERF-05-C paired acquisition/RustFS/profiling instructions > the approved BM-10 general rules, `docs/BENCHMARKING.md`, `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`, `docs/TESTING.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`. Existing mandatory correctness, error, resource, reproducibility, readiness and artifact integrity rules remain binding. Reconcile the earlier PERF-05-B implementation register to this **specific** exception; do not silently rewrite general paired-benchmark methodology.

**Plan status:** No PERF-05-C code or measurements are claimed by this document. Current `main`/PR sources were inspected to specify this design. **This plan is executable authority after maintainer handoff; the coding agent does not design a different runner or choose alternate study arms.**

## 1. What is necessary — and what is forbidden

### Exactly necessary

1. On existing PR #117, implement **one minimal `perf-05/warm` B-only study mode** using BM-10's tested adapter, corpus/index builder, oracle, seeded scheduler, work/readiness checks, artifact publisher, and existing statistics for B/B stability.
2. Require the configuration's sole Quervant arm `B` to contain a full 40-hex Git commit in `arms.B.revision`. Stage/compile from a detached checkout of that exact commit, never from ambient `HEAD`. Preserve existing configuration families and their historical JSON.
3. Verify the retained A result's Git blob, exact source, result/config IDs, all 16 lane and per-block measurements, A's 16/16 A/A PASS, and compatible workload/timed-operation before measuring B.
4. Build the B release adapter once, create/commit/reopen/validate **two** local B indexes (10K and 100K), then collect one **B/B** position-balanced stability campaign. Both temporary B/B role labels invoke the **same B executable and indexes**; neither is A.
5. Preserve B samples and derive B's absolute block medians. Compare B vs preserved A's absolute block medians by lane **descriptively**, without a paired estimator or causal CI.
6. Save **one immutable new configuration JSON and one immutable new result JSON**. Run the relevant deterministic Python test/coverage gates, complete the execution report, commit and push to **PR #117** without merging.

### Explicitly forbidden / unnecessary

- **NO A acquisition:** No A worktree, A build, A index, A warmups, A/A on A, A queries, or A profiler. Loading/reanalyzing A JSON is permitted and required.
- **NO competitor acquisition:** No Tantivy/Lucene build, query or index, cross-engine rerun, process-cold run, retained-key campaign or unrelated study.
- **NO RustFS:** No container/runtime detection, `tests/rustfs/run.sh`, `docker compose`, remote service start, remote integration tests, credentials, bucket setup, or remote teardown. B5 changes search/execution ownership only; the current warm study uses local filesystem paths.
- **NO independent profiler capture in this campaign:** No `perf record`, `perf script`, frame-pointer rebuild, demangler experiment, Criterion execution or allocator/CPU profiling. The prior register mentioned optional diagnostics; for this minimal B-only decision, profiling is **deferred**, and it is not a gate. If regression diagnosis is later authorized, it is a separate plan, not a reason to extend this campaign.
- **NO extra benchmark:** no paired rerun, warm A/B, same-source A/A of old baseline, free restart to obtain a better result, extra blocks/lanes, threshold tuning, cache flushing, CPU affinity experiments, source-code tuning, physical-layout refactors, heuristic retry, manual exclusion of unfavorable samples, or per-candidate timers.
- **NO Rust production changes:** do not alter `crates/**`, codecs, column/storage readers, `Cargo.toml`, `Cargo.lock`, CI, old configuration/results, BM-10 historical decisions or other PRs.
- Do not automatically merge PR #117 or label historical-relative gain a statistically paired or proven causal performance improvement.

### Why a narrowly new runner mode is required

At `main@9775bfca…`, BM-10 supports `retained-key`, `cross-engine`, and `perf-02`, but **not** a one-arm B-only study. `statistics.schedule` rejects fewer than two arms; `runtime.run_benchmark` always runs source-equivalent control **and** a multi-arm treatment, and `cross-engine` necessarily builds Q/T/J. Therefore simply editing an existing JSON `arms` field cannot satisfy the request. The new family uses **two temporary aliases of the one B source for stability only**, not a second production arm or a new pairwise treatment campaign. The design and exact accounting are frozen below. Do not “get around” schema checks by suppressing an arm or feeding historical A raw samples as contemporary slots.

## 2. Source evidence and implementation boundaries

Inspect/freeze these actual symbols (lines shift after implementation):

| ID | Inspected fact | B-only implication |
| --- | --- | --- |
| S01 | `benchmarks/quervant_bench/lean/configuration.py::{default_configuration,validate_configuration,lanes_for}` defines 3 families; warm has 16 lanes | Add only the `perf-05` family; reuse 16-lane warm matrix unchanged |
| S02 | `lean/artifacts.py::STUDY_REGIMES`, `configuration_directory`, `create_configuration`, `publish_result`, `load_result` enforce unique UUID/names, sibling results and exclusive publication | Add `"perf-05":("warm",)`; preserve all writer/loader guarantees |
| S03 | `lean/cli.py::parser/main` supports `prepare`, `validate`, `stage`, `run`, `report`, `analyze`, etc. | Add only one creation option `--quervant-revision` for family `perf-05`; keep legacy options working |
| S04 | `lean/runtime.py::_build_rust` is the exact locked release builder and supports `source_root` | For B, use independent detached worktree at pinned B5 commit; don't build ambient `HEAD` |
| S05 | `runtime.build_programs` already creates independently pinned PERF-02 worktrees | Reuse that pattern for **one** `B` adapter; do not build an A adapter |
| S06 | `lean/preparation.py::source_identity`, `stage_inputs`, `_commands_from_cache` bind preparation cache to config/source/environment, verify binaries and untimed oracles | Extend cache for pinned B source; preserve cache safety, fingerprinting, root clean check |
| S07 | `runtime.collect_slot` measures `engine_ns` warm query with 5 warmups and 20 samples, checking each query against independent `expected_answer` | Reuse without modifying query, observer or timed boundary |
| S08 | `statistics.schedule` supports 2–8 distinct role labels; `statistics.analyze` accepts whole-block equivalence with `policy.control_arms` | Use temporary BB/BB2 roles and existing B/B control statistics; **never** fabricate an A source |
| S09 | `runtime._phase` currently maps AA aliases to a configured `source_arm` | Change the mapping to use `source_arm` whenever set, independent of role prefix, preserving prior AA behavior |
| S10 | `runtime.run_benchmark` always performs a separate treatment and may run throughput for cross-engine | Insert a **family-specific B-only branch**; do not invoke `_phase` for treatment or throughput |
| S11 | `lean/reporting.py::render_report` currently assumes a paired B/A comparison | Add a special `perf-05` presenter for B absolute + historical-relative numbers only |
| S12 | `docs/BENCHMARK_RESULT.md` notes regular top-level `raw_samples` are treatment records | Document PERF-05 exception: B/B aliases are the sole B-acquisition records in the top-level field |
| S13 | `docs/BENCHMARK_CONFIGURATION.md` describes fixed fields; `perf-02` revision checks exist | Add a formal `perf-05` pin and historical-reference shape; no arbitrary JSON keys |
| S14 | Historical retained A `context.source_revision` is **`256501f0…`**, not the later main `9775bf…` | Correct prior mistaken baseline identification explicitly in all new reports |
| S15 | Historical `Q` result: `COMPLETE`, 16/16 A/A PASS, same native `doc_id` keyword UTF-8 string sort, `Tantivy 0.25` comparator present in old file only | Reuse **only its Q data**, do not start T/J processes |
| S16 | `.github/workflows/ci.yml` runs Python `pytest`, 85% branch coverage, CLI help and discovery validation of checked-in configurations | No CI workflow changes; use existing job on pushed PR |
| S17 | PERF-05-B1–B5 sources and tests are in `dev/perf05-physical-execution-series` at `ee18ed63…`; CI run #522 green | Do not touch engine or repeat full Rust suites locally when no Rust file changes |

### Design non-novelties

No new dataset specification, query language, custom scorer, sorting implementation, replica, storage provider, schema version for committed segment files, cancellation or allocation model, or third benchmark artifact. Query indexing and commit remain outside warm latency. This is a read-only performance study against immutable, independently verified local indexes.

## 3. Historical A contract, exact reference table

The retained A file is *the* authoritative reference. It has `configuration_id=c4083f1e…`, `run_id=f2df1d40…`, `status=COMPLETE`, 16 lanes, all A/A PASS; `context.build.quervant_strategy_feature_enabled=false`, `compiler_options="cargo --release --locked"`, `context.host.system="Linux"`, architecture `x86_64`, filesystem `ext4`, WSL2 kernel, Rust toolchain `1.98.1`. It contains Q, T and J but **only Q** is consumed by PERF-05-C.

A's preserved Q-arm `analysis.lanes[id].arm_absolute.Q.median_block_value` values are given as assertion fixtures (nanoseconds):

| Lane | A Q-arm median (ns) |
| --- | ---: |
| `10000/absent/k10/warm` | 39013 |
| `10000/absent/k100/warm` | 38825.25 |
| `10000/rare/k10/warm` | 47526 |
| `10000/rare/k100/warm` | 47150.5 |
| `10000/medium/k10/warm` | 1487246.125 |
| `10000/medium/k100/warm` | 1593144.75 |
| `10000/common/k10/warm` | 3239065.125 |
| `10000/common/k100/warm` | 3273317 |
| `100000/absent/k10/warm` | 231715.625 |
| `100000/absent/k100/warm` | 232478 |
| `100000/rare/k10/warm` | 242403.125 |
| `100000/rare/k100/warm` | 241365.625 |
| `100000/medium/k10/warm` | 15438918.875 |
| `100000/medium/k100/warm` | 15528062.875 |
| `100000/common/k10/warm` | 33829324 |
| `100000/common/k100/warm` | 33481856.875 |

Historical index byte sizes: Q at 10K **1,560,111**; Q at 100K **15,747,551**; each one segment. Freeze these as comparability diagnostics. Do not reject solely on a differing index byte count without first diagnosing why a query-only PR could change bytes; **STOP** on unexplained index byte/segment-count disparity before timed acquisition.

**Mandatory read-only preflight:**

1. `git hash-object` of the historical file must equal `a809f0362553e4e5c93ac1593ef478e8eef6a865`. Never rewrite/copy/reformat it or modify existing results/configurations.
2. Load using `artifacts.load_result`, verify both revision fields equal `256501f0…`, the run/config IDs, `status=COMPLETE`, 16 lanes of exactly the warm matrix, independent Q oracles, and every historical `controls.analysis.lanes[id].comparisons[*].status == PASS`.
3. Verify historical readiness observations with `status` are `clear`; skip only the descriptive `readiness_index_source` string field. Check all Q raw slot/lane records are present and `oracle_ok=True`.
4. Read `analysis.lanes[*].arm_absolute.Q.block_values`: **12** positive finite values per lane; recompute each median with `Decimal` and compare with the saved `median_block_value` exactly at its stored numeric precision. The assertion table above must match. If any fails, HARD STOP; do not create a replacement A result or drop a lane.
5. Verify exact workload, sizes, cardinality classes, K values, `doc_id` string-sort contract, P2 production dispatch and warm timed scope against the planned B configuration. If any differ, HARD STOP before B acquisition.

## 4. Frozen B-only configuration, acquisition schedule and analysis

### 4.1 Saved configuration

Add supported `family="perf-05"`, warm-only, under `studies/perf-05/warm/configurations/` with **one measured arm**:

```json
{
  "family": "perf-05",
  "baseline": "B",
  "arms": {
    "B": {
      "engine": "quervant",
      "mode": "by-top-k",
      "source": "pinned",
      "revision": "ee18ed63bbeeb54b544393ee0f676987ff9987d1"
    }
  },
  "control": {"enabled": true, "baseline": "BB", "equivalent": "BB2"},
  "build": {
    "release": true, "locked": true, "baseline_ref": null,
    "prefilter_profile": "P2", "quervant_feature": null
  },
  "historical_reference": {
    "family": "cross-engine",
    "result_file": "quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json",
    "git_blob_sha1": "a809f0362553e4e5c93ac1593ef478e8eef6a865",
    "configuration_id": "c4083f1e-4ce2-4477-b282-04c4d40b187f",
    "run_id": "f2df1d40-2eee-4fcb-9593-ba8433e08c4a",
    "arm": "Q",
    "source_revision": "256501f0e700ed199f316e79d128389375177530",
    "mode": "historical-absolute-unpaired"
  }
}
```

This is a *field subset*. The normal creator fills `schema="benchmark-configuration-v1"`, unique UUID `configuration_id`, `name="quervant-perf05-b-only-warm"`, `description`, `created_utc`, and the **exact** warm workload declaration and policy fields from BM-10. Do not manually fabricate a UUID. Reject `--candidate-revision`, `--baseline-revision`, `--regime process-cold` or any unrecognized source role with this family. Retained-key and cross-engine historical JSON remain unchanged and readable.

### 4.2 Exact measurement schedule — B only

Freeze policy:

```json
{
  "blocks": 12, "slots_per_arm": 1,
  "warmups": 5, "samples": 20,
  "bootstrap_resamples": 10000, "seed": 20261122,
  "min_blocks": 4,
  "min_gain_percent": 0, "max_regression_percent": 0,
  "max_aa_gain_percent": 15,
  "exclude_blocks": {}, "control_arms": [],
  "readiness": {
    "intervals": 4, "interval_ms": 250,
    "max_busy_percent": 25, "max_steal_percent": 2
  }
}
```

- The persisted configuration has one source arm `B`. The acquisition constructs **ephemeral alias arms `BB` and `BB2`**, both mapped to the *same* B binary, source, strategy, source revision and index. They are not A. Both are checked for identical results and used for **B/B stability**.
- Call existing `statistics.schedule(["BB","BB2"], blocks=12, slots_per_arm=1, seed=20261122)` and existing `_phase`/`collect_slot` exactly once. There are **24 total slots × 16 lanes = 384 B slot/lane records**; each record includes 5 warmups and 20 measured queries: **1,920 warmup + 7,680 measured = 9,600 scheduled B query calls**, plus the separately untimed per-lane staging oracles. No other timed queries or throughput sessions.
- Every adapter reply (warmup and timed) is checked against the independent `expected_answer` oracle; source code can compute exact `total_hits` and expected ascending string `doc_id` identities. Query timing uses the existing adapter `engine_ns` only: no index build, commit, reader open, process spawn, JSONL overhead or RustFS.
- Use current mandatory readiness checks before indexing (stage), before and after B/B acquisition. Assume the host is idle; **no extra idle probe/wait loop** beyond the existing BM-10 readiness checks. Preserve actual probe results. A readiness fail aborts/invalidates; it is not permission to wait and rerun.
- Run existing `statistics.analyze` on the **BB/BB2 raw data** with `arms=["BB","BB2"]`, `baseline="BB"`, policy `control_arms=["BB2"]` to derive **one stability PASS/FAIL per lane**. A/A notation in legacy code becomes **B/B** for this family. Fail if any lane is not PASS; do not rerun.

### 4.3 Absolute B estimator and historical comparison (no false pairing)

From the validated B/B analysis, for each of the 16 lanes obtain the two 12-element block vectors `BB_block[i]`, `BB2_block[i]`. The B block value is exactly:

`B_block[i] = (Decimal(str(BB_block[i])) + Decimal(str(BB2_block[i]))) / Decimal(2)` for `i=0..11`.

Then `B_median = statistics.median(B_block)` as a Decimal, converted for JSON presentation as a finite number. This reproduces a **mean of two slot medians in each block** followed by the median of the 12 block values, matching the historical Q absolute-aggregation method; the aliases merely provide an independently checked balance diagnostic.

For each lane, `A_median` comes **only** from historical `analysis.lanes[lane].arm_absolute.Q.median_block_value`, not from a new A process. Compute **descriptive** `ratio_B_over_historical_A = B_median/A_median` and `gain_percent = 100*(1-ratio)` for lower-is-better latency. Preserve the full historical and B 12-block vectors, medians, identifiers, ratio, threshold flags, and `comparison_kind="HISTORICAL_UNPAIRED_ABSOLUTE"` in the *new B result*.

**DO NOT:** seed-pair A's block 1 with B's block 1, call `statistics.analyze` with A and B, use BM-10's paired bootstrap, claim a paired CI, infer the improvement is caused solely by code, use `compare_historical` (that compares *within-run treatment effects*), or silently drop an unfavorable lane. No new independent two-sample CI is required for this minimal plan. The ratio is descriptive; B/B PASS establishes only within-B session stability.

### 4.4 Deterministic outcome classification — report, never auto-merge

Define **primary warm lanes** as the four 100K medium/common, K10/K100 combinations. Define **guard lanes** as the other 12 warm lanes (including 10K common/medium and all absent/rare cases).

- `B_ONLY_HISTORICAL_TARGETS_MET` if all four primary `ratio <= 0.95` (at least 5% historical-relative improvement) **and** all 12 guard `ratio <= 1.10` (no >10% historical-relative regression), all 16 B/B PASS, 16 oracle PASS, exact source/build/corpus checks, compatible host and result `COMPLETE`.
- `B_ONLY_HISTORICAL_TARGETS_NOT_MET` if any primary >0.95 or guard >1.10 despite valid acquisition. **Do not** retune, rerun, revert B or call it a tooling error. Record failing lanes, ask human reviewer whether to adopt/adjust work.
- `B_ONLY_HISTORICAL_CONTEXT_CHANGED` if verified host/toolchain/cache/sort/source policy differs materially from the historical reference. Keep measured B data but **do not** claim targets met even when numeric ratios look favorable; report exact differences and require human assessment. Linux/x86_64/native ext4 and uninstrumented release/locked build are mandatory; other environments must not be normalized silently.
- `B_ONLY_INCOMPLETE` for failed readiness, B/B instability, missing measurement/oracle, invalid baseline, corrupted config/index, failure to identify B SHA, interrupted run or publication error. Retain any legitimately captured raw B data; never claim `COMPLETE`.

These numeric **screening thresholds are predeclared operational review flags, not paired statistical acceptance gates**. Neither a `TARGETS_MET` flag nor a Python exit code authorizes a merge or a causal claim. The final human decision must disclose that A and B were measured in different sessions.

## 5. Prescribed source implementation (no design choices delegated)

### 5.1 Files, exactly

**Allowed tracked code / docs (only when needed by the frozen design):**

```
benchmarks/quervant_bench/lean/artifacts.py
benchmarks/quervant_bench/lean/configuration.py
benchmarks/quervant_bench/lean/cli.py
benchmarks/quervant_bench/lean/preparation.py
benchmarks/quervant_bench/lean/runtime.py
benchmarks/quervant_bench/lean/reporting.py
benchmarks/quervant_bench/lean/perf05.py                    # NEW: pure B-only historical analysis
benchmarks/quervant_bench/lean/tests/test_perf05.py         # NEW: deterministic fake-only tests
benchmarks/BM10_README.md
docs/BENCHMARK_CONFIGURATION.md
docs/BENCHMARK_RESULT.md
docs/BENCHMARKING.md
docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md
docs/pr-artifacts/perf-05/PERF05C_DETAILED_PLAN.md         # verbatim copy
docs/pr-artifacts/perf-05/PERF05C_EXECUTION_REPORT.md      # evidence and disposition
benchmarks/studies/perf-05/warm/configurations/quervant-perf05-b-only-warm-<creation-date>.json
benchmarks/studies/perf-05/warm/results/quervant-perf05-b-only-warm-<execution-date>-001.json
```

No modification of any existing result/configuration JSON, no behavioral change to any other benchmark family, and no modification of Rust crates, RustFS files, CI YAML, Cargo manifests or historical test fixtures. No new third benchmark artifact. If updating an existing benchmark-test file is absolutely necessary due an immediate clearly deterministic new-family assertion, use **only** `benchmarks/quervant_bench/lean/tests/test_perf05.py` for new tests and leave other tests as they are; if this proves impossible, **HARD STOP** for human scope amendment, not broad test rewrites.

### 5.2 `artifacts.py`

- Add **exactly** `"perf-05": ("warm",)` to `STUDY_REGIMES`.
- Do not alter `_publish_exclusive`, registry checks, path/symlink checks, `publish_result`, `load_result` or result-file naming logic.
- A new PERF-05 config gets one UUID and an immutable date-bearing name; each real attempt saves one result in its sibling `results` directory with the standard incrementing sequence.

### 5.3 `configuration.py` and `cli.py`

- Extend family catalogs, `default_configuration` and `prepare_configuration` for `"perf-05"` **warm-only**. Add a single optional argument `quervant_revision: str | None`; accept it **only** for family `perf-05`. For `perf-05` it is **mandatory**, lowercase 40-hex, `source="pinned"`, mode `by-top-k`, one arm `B`, baseline role `B`.
- Use existing warm workload EXACTLY: sizes `[10000,100000]`, classes `absent,rare,medium,common`, K `[10,100]`, regime `["warm"]`, oracle semantics and existing warm `timed_operation` unchanged.
- `control` must be `{"enabled":true,"baseline":"BB","equivalent":"BB2"}`; freeze policy from §4.2. Populate `historical_reference` from §4.1 as constants, not caller-chosen.
- Add `--quervant-revision` to the existing `prepare` command; only `--family perf-05` may use it. Reject absent, malformed, uppercase, ref-name, `HEAD`, and extra-family use. Do not add any option to disable controls, skip oracles or weaken thresholds.
- `validate_configuration` MUST enforce exact B-only arm, source, revision format, historical reference exact identifiers, control, warm-only policy and workload. Historical existing families remain valid with their original schemas; don't alter their read semantics. New PERF-05 result must use the same existing JSON artifact `schema` markers, with a documented **family-specific analysis estimator**.
- Preserve CLI `stage`, `run`, `report`, `analyze`, and historical `compare` behavior for other families. For `perf-05`, `compare` must return a clear `NOT_COMPARABLE` rather than treating the B-only absolute result as a conventional paired effect; do not reinterpret any old outcome.

### 5.4 `preparation.py` and `runtime.build_programs`

- In `source_identity`, keep `_clean_source(root)` and existing source/tree, environment and toolchain fingerprints. For `family=="perf-05"`, extract `arms.B.revision`, run `git cat-file -t <SHA>`, require exact `commit`; persist `arm_source_revisions={"B": <SHA>}` in identity and build context. Cache key **must** change if B SHA changes.
- In `runtime.build_programs`, before shared current Quervant/Tantivy/Lucene builds, handle `family=="perf-05"`: `git -C <root> worktree add --detach <scratch>/source-b <revision>`, call existing `_build_rust(root, scratch/build/quervant-b, engine="quervant", feature=False, source_root=<scratch>/source-b)`, then always remove the worktree in `finally` with the existing `git worktree remove --force` pattern. Return **only** program key `B`, no `A`, `Q`, `T`, or `J`; build_info must include exact B source revision, release/locked options, and experimental feature `false`.
- For `preparation._commands_from_cache`, map PERF-05 `B` to `scratch/build/quervant-b/release/pr15d-quervant-adapter`; other families untouched. Stage creates B index paths under `indexes/B/n10000` and `indexes/B/n100000` and runs the *existing* oracle for all 16 lanes. Do not stage historical A indexes or competitor indexes.
- Do not change adapter source, dataset generator, corpus row formula, analyzer, index format or timed operation.
- The source worktree has no benchmark-run side effects and is removed after build; the built B executable remains in the verified cache. Use production release flags; no `RUSTFLAGS` profiling override. Cache reuse must still verify fingerprints and current oracles.

### 5.5 `runtime._control_config`, `_phase` and B-only run path

- Do not change generic statistics/schedule code. In `_control_config`, use the config's declared `control.baseline` and `control.equivalent` to construct the two equivalent aliases instead of hardcoding `AA/AA2`; for existing families these **remain** `AA` and `AA2`, and they must continue behaving exactly as before. Set `source_arm` to the persisted baseline (`B` for perf-05). Mark control role 2 in `control_arms`.
- In `_phase`, where an alias role currently resolves a command by checking `arm_id.startswith("AA")`, replace only that condition with: **if the synthetic control config has a `source_arm` key, use `config["source_arm"]` for both aliases; otherwise use the actual `arm_id`.** Keep slot order, cancellation, checks, and `collect_slot` identical.
- In `run_benchmark`, recognize `family=="perf-05"` **before invoking `stage_inputs`**: verify the immutable historical A identity first, then proceed through the normal B-only host/preparation checks, and select the one B/B acquisition branch **instead of** the generic A/A/treatment sequence. `stage_inputs` itself must also verify the historic identity before starting its first B build or index. Use the existing `pinned_controller`, `assess_readiness`, `_phase`, and `statistics.analyze` for `BB/BB2`. Record BB and BB2 raw observations in **top-level `raw_samples` exactly once**, not copied from elsewhere; these are the complete B samples. Record the B/B analysis under `controls.analysis`. For this family `controls.raw_samples` need not duplicate the same entries; document this explicitly.
- The B-only branch: (1) run and validate historical A read-only before any timed B, (2) stage B source/index/oracles once, (3) readiness pre, (4) one `_phase` for aliases BB/BB2, (5) existing statistics B/B analysis, (6) readiness post, (7) pure `perf05` absolute and historical summary, (8) `status=COMPLETE` iff all above succeed, (9) existing `publish_result` in the usual `finally`/error path.
- **Do not call** a second generic `_phase` treatment, serial throughput, any competitor code, or any process-cold branch. If the primary `_phase` raises or B/B is unstable, publish `INCOMPLETE` with captured samples/error; no free retry.
- Extend `runtime`'s benchmark `INCOMPLETE` error classification for PERF-05 without catching exceptions that existing code treats as internal programming errors. Leave regular family A/A/treatment behavior unchanged; focused tests must prove it.

### 5.6 New `lean/perf05.py`: exactly two pure functions plus fixed constants

Define:

1. `verify_historical_reference(root: Path, config: Mapping[str, Any]) -> dict[str, Any]` that locates only the fixed path in §0 under `root`, uses existing `load_result` and read-only `git hash-object` identity, enforces every §3 assertion including readiness, source, stable original `Q` data, slots and 16 medians, and returns immutable-or-unmodified validated historical data. **Never reads a user-chosen arbitrary file, mutates A or runs A.** Return typed `ArtifactError`/`MeasurementBlocked` on mismatch.
2. `analyze_b_only(b_raw: Sequence[Mapping[str,Any]], bb_analysis: Mapping[str,Any], historical: Mapping[str,Any], config: Mapping[str,Any], host_context: Mapping[str,Any]) -> dict[str,Any]` that verifies every B/B status PASS and exactly the schedule's 24 slots×16 lanes, computes the B block means and historical ratios **exactly** per §4.3, declares thresholds and context differences per §4.4, and returns an object with `schema="bm10-b-only-analysis-v1"`, `estimator="median-of-two-b-slot-medians-per-block-v1"`, `bootstrap_method="NONE_FOR_HISTORICAL_COMPARISON"`, `lanes` (B absolute), `historical_comparison` (A-Q absolute, B/A ratios, flags), and final **descriptive** disposition.

Use existing `Decimal` and `statistics._median` (or Python `statistics.median` on `Decimal` objects), `ArtifactError`, and native standard library. **No second computation of BM25, no new bootstrap or t-test, no cross-run pairing, no synthetic baseline samples, no external service, no dependency addition.** Only frozen threshold comparisons and read-only descriptive calculations.

### 5.7 Reporting and docs

- Add a PERF-05 special case in `reporting.render_report`: show one table with lane, historical A (ms), new B (ms), B/A, gain%, target/guard flag and **explicit text “HISTORICAL, UNPAIRED, DESCRIPTIVE; not a contemporaneous paired A/B CI.”** Preserve existing output for all older families. Replays use saved result values and require **zero** timers, builds or new queries.
- Document the `perf-05/warm` configuration field dictionary, `historical_reference`, arm `B.revision`, B/B stability design, saved-result raw aliases/analysis, no paired CI, naming and source/build provenance in `docs/BENCHMARK_CONFIGURATION.md`, `docs/BENCHMARK_RESULT.md`, `docs/BENCHMARKING.md`, `benchmarks/BM10_README.md`. Make the B-only exception **specific to PERF-05**, not a replacement for scientific paired protocols elsewhere. Explain earlier `9775…` vs true measured `256501…` difference.
- In `PERF05B_IMPLEMENTATION_REGISTER.md`, update *only* the final C portion to say **B-only warm against retained historical A, no A/T/J acquisition, no RustFS, profiling deferred**; clearly say comparison is descriptive and merge requires human review. Do not rewrite older B stages, frozen prior evidence, architecture or roadmaps as if C had already passed.
- Copy this approved plan unchanged into `docs/pr-artifacts/perf-05/PERF05C_DETAILED_PLAN.md`. Add one truthful `PERF05C_EXECUTION_REPORT.md` with commands/outcomes/source pins, A blob+run+config identity, B build provenance, B/B controls, 16 lanes, B-only slot count, indexed corpus/size checks, QA and final decision. No third tracked benchmark artifact is introduced by an execution-report Markdown document.

## 6. Preflight — exact operations and branch guard

The agent starts on its normal repository host. Do not provision Docker/RustFS, perform system upgrades, or initiate another automation. Python package/test tools already installed should be reused; install missing tools once only when necessary, then stop if installation fails.

```bash
set -euo pipefail
git status --porcelain=v1 --untracked-files=all
git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series
START_SHA=$(git rev-parse HEAD)
MAIN_SHA=$(git rev-parse origin/main)
B_SHA=ee18ed63bbeeb54b544393ee0f676987ff9987d1
B4_SHA=3b25a76b99f699c45aa2050c4f889880a138948a
# Expected before PERF-05-C implementation:
test "$START_SHA" = "$B_SHA"
test "$MAIN_SHA" = 9775bfca4c58a27e65ca28c1d705efad00a65ec8
git merge-base --is-ancestor "$B4_SHA" "$B_SHA"
test "$(git cat-file -t "$B_SHA")" = commit
# Verify absolute historical artifact identity without editing it:
A_PATH=benchmarks/studies/cross-engine/warm/results/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json
test "$(git hash-object "$A_PATH")" = a809f0362553e4e5c93ac1593ef478e8eef6a865
python -m pytest --version
rustc --version
cargo --version
python --version
```

A clean tree is required (known generated outputs may be excluded by existing *documented* local exclusions; never modify exclusions to conceal unknown tracked/untracked source). If the branch has advanced **only** via a documented reviewed PERF-05-C code+test commit created by the agent during this authorized execution, resume from the current recorded state. Otherwise, unexpected new commits/main divergence/different B source/dirty source => `HARD_STOP_SOURCE_DIVERGENCE`, not an autonomous rebase or changing B SHA. No force push, `git reset`, `git clean`, stash, merge or new PR.

**Proof before production benchmark acquisition:** Confirm only the expected Quervant query-code changes from B1–B5 are present; compare the exact relevant files between main and B, and record their names. Validate historical artifact and expected 16-lane medians; if `git hash-object`, run ID or source differs, hard stop. Verify B5 Rust CI #522 on its source commit already succeeded. Do not redo the Rust workspace because benchmark Python code is the only planned new implementation.

## 7. Deterministic test-first matrix; no timed real runs in tests

Use mocked Git, synthetic adapter path/build, deterministic stub JSONL child and real pure statistics. **Never** mock the score/segment/search algorithm as evidence of benchmark correctness; actual B-only staged oracles exercise the production adapter in §8.

| Test ID | Required case | Exact pass/fail property |
| --- | --- | --- |
| C-U01 | Valid `perf-05` config | one B arm, pinned SHA, 16 warm lanes, BB/BB2, proper date/name/id and historic fields |
| C-U02 | Invalid config shapes | missing/bad/noncommit/uppercase revision, two arms, non-warm, changed history, altered K, experimental feature, numeric sort, no controls all rejected |
| C-U03 | Read-only history | exact result blob, source `256501…`, Q 16 medians, 12 block values, A/A PASS; corrupted ID/blob/slot/median/readiness fails **before** any B queries |
| C-U04 | One pinned B compile | spy `_run`, `_build_rust`: exact detached SHA, release locked no experiment, one B build, `finally` worktree cleanup; no A/T/J |
| C-U05 | Preparation cache | first BUILT, second HIT, B SHA/config/toolchain/source-object change rekeys, invalid cache refuses reuse, no historical-A cache/build |
| C-U06 | BB/BB2 schedule | precisely 12×2=24 slots, 16 lanes=384 records, 5 warmups+20 samples, seeded 20261122, balanced aliases, same binary/index |
| C-U07 | B/B control | stable synthetic 100ns/100ns PASS; noisy or one bad lane FAIL and the result remains INCOMPLETE; no second phase |
| C-U08 | Bad oracle | wrong total hits, wrong sorted string ID, missing/unselected candidate, malformed duration, missing slot, altered schedule => typed rejection, no complete B result |
| C-U09 | Absolute B statistic | block-wise `(BB+BB2)/2`, 12 medians, one historical A value, positive finite exact Decimal ratio and signed gain |
| C-U10 | Historical comparison | never paired, no bootstrap/CI; null/negative/NaN/zero or changed workload rejects; source/context difference classified, no fake speedup |
| C-U11 | Outcome flags | all four primaries ≤0.95 and guards ≤1.10 -> targets; boundary equality passes; > bound fails; context mismatch is not accepted |
| C-U12 | Run failure/save | interruption/readiness/cancel/allocator/program failure preserves already collected B raw, one `INCOMPLETE` result and no relaunch |
| C-U13 | Result publication | stable config ID/file, new run UUID, sibling dated sequence, no overwrite, no extra tracked artifact, read-only report deterministic |
| C-U14 | CLI preparation | `--quervant-revision` accepted only for PERF-05; no revision/invalid SHA/legacy family misuse errors |
| C-U15 | Legacy regressions | old retained-key, cross-engine, perf-02 config creation/validation/report/stage/run mocks unchanged; original historical configs still validate |
| C-U16 | No forbidden work | test spy fails if A/T/J worktree, build, index, query, RustFS, profiler, throughput or process-cold acquisition invoked |

**RED FIRST:** Add the minimum new tests for C-U01/C-U04/C-U06/C-U09 so they fail **only** because the `perf-05` family/helper does not exist; capture the expected reason. Unexpected failure or fixture mistake => hard stop; don't weaken the test. Implement §§5.2–5.7, rerun GREEN and full existing Python framework suite. A new `test_perf05.py` is the sole new test module; its mocks must stay isolated from other test files.

**Required local deterministic commands:**

```bash
# Use installed tools when available; do not reinstall unnecessarily.
# If imports are missing, install once from the repository instructions:
# python -m pip install -e ./benchmarks pytest coverage
PYTHONPATH=benchmarks python -m compileall -q benchmarks/quervant_bench
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests/test_perf05.py
PYTHONPATH=benchmarks python -m pytest -q benchmarks/quervant_bench/lean/tests
PYTHONPATH=benchmarks coverage run --branch --source=quervant_bench.lean -m pytest -q benchmarks/quervant_bench/lean/tests
coverage report --fail-under=85
PYTHONPATH=benchmarks python -m quervant_bench --help
# Test installed CLI only if installed; the module entry point is authoritative.
# quervant-bench --help
git diff --check
```

Coverage is **Python benchmark framework branch coverage ≥85%** (existing CI floor); no Rust production source is changed, so Rust workspace line coverage is **not remeasured locally for this bench-only C change**. Existing B5 Rust code already passed relevant stable/MSRV+RustFS hosted CI; do not repeat full Rust suite, MSRV, rustdoc, cargo benches, RustFS, or unrelated integration matrices locally. CI will exercise normal repository QA after the new PR #117 commit as configured; report its status honestly. No test may execute an actual timed benchmark.

## 8. Single real B-only execution (after tests/code/doc commit)

**Pre-acquisition commit:** Commit code/tests/docs, push to existing PR #117, ensure git tree clean and Python CI passes if it has completed. Do not merge. The benchmark runner may use a newer framework `HEAD`, but **the B executable always comes from the pinned B5 SHA**.

**Create exactly one configuration** with the existing CLI extended in §5.3:

```bash
B_SHA=ee18ed63bbeeb54b544393ee0f676987ff9987d1
quervant-bench prepare --family perf-05 --regime warm \
  --name quervant-perf05-b-only-warm \
  --description 'PERF-05 B1-B5 pinned Quervant B-only warm study against retained 2026-11-22 historical A' \
  --quervant-revision "$B_SHA"
# Set CONFIG to the exact printed pathname. Never use a glob that could pick another study.
quervant-bench validate --config "$CONFIG"
# Stage B only; this builds one B executable and indexes 10K/100K, checks all 16 oracles.
quervant-bench stage --config "$CONFIG"
# Exactly ONE timed B/B acquisition, reusing the staged B index and executable:
quervant-bench run --config "$CONFIG"
```

**Acquisition safeguards:**

- Use the **existing** local Linux/WSL2 native filesystem and BM-10 CPU-affinity/readiness policy; assume host is idle and ready, no separate operator idleness check. No external service startup or cache flushing.
- Preserve staged corpus/index and full provenance under `target/bm10/prepared/<key>`; do not remove/modify a verified in-use cache. If stage is a HIT, verify all declared-lane oracles again (existing policy); do not rebuild merely for a fresh timestamp.
- Capture exact B SHA, release command, binary path and optional binary SHA256, target CPU and host context; confirm B uninstrumented feature `false` and P2 default dispatch. If B build cannot prove exact revision, HARD STOP before timing.
- Stage the indexes once, verify deterministic corpus row and `index_metrics.B.10000/100000` as reference diagnostics; where a direct index digest cannot be compared to historical A (not saved in the old result), do **not** invent one. Enforce the same one-segment index shape and document sizes.
- Do not run `quervant-bench compare` for this result. Invoke only `quervant-bench report --result "$RESULT"` for presentation/replay, plus source-backed read-only validation of saved results if needed.
- `run` must save its result automatically without asking to approve saving; inspect the actual printed result path, status, 16 B/B PASS, 384 records, historical comparison and every lane.
- Never silently rerun if a lane is noisy, the result is bad, the benchmark is slow, or A appears faster. One real attempt only; a genuinely interrupted acquisition is **not** authority for an automatic replacement campaign.

**Commit resulting new config/result JSON** (and execution report) on PR #117 with truthful source and statuses. Do not stage `target/`, pycache, raw `perf` files, A result edits, temporary copies or background logs. Do not relabel a `INCOMPLETE` result as COMPLETE. If report finalization happens after the code/CI commit, one follow-up docs+result commit is permitted; it must not change B source or measured config.

## 9. Error precedence, resource, cancellation, retry and storage boundaries

- **B source and historical identity validation precede indexing/measurement.** Misidentified A or B is a hard stop, not fallback to `HEAD`.
- **B stage index-build/commit/reopen/oracle validation precedes any timed query**. The local adapter's real engine reads immutable local segments; no storage schema or transaction semantics change.
- **Readiness/affinity failure precedes timed slot collection**, and any later failed readiness invalidates the result while preserving already measured raw data.
- **Each warmup and timed reply must pass the oracle**; an unselected corrupt posting is not permission to skip a sample, reduce M or alter error precedence.
- **Work/cancellation/resource policy:** Production executor is unchanged; use its existing defined limits. Benchmark orchestration exceptions preserve partial records with `INCOMPLETE`; don't substitute synthetic results or retry only favorable lanes.
- **Atomic publication:** Reuse `artifacts.publish_result` exclusive no-replace writer, UTC filename sequence and stable `configuration_id`; temporary cache staging remains disposable. No extra publication contract or evidence/receipt model.
- **Idempotency:** `stage` can be rerun for cache validation (no timing); `run` is intentionally **not** idempotent and must not be auto-retried. A second run, even with a new suffix, requires fresh human approval.
- **B5 source code:** No Rust change, no index format/version changes, no mutation or remote I/O. PIT, cursor, Unicode sort, false callback, BM25/CorruptIndex/ResourceLimit behavior are protected by the already approved B1–B5 tests and the real B oracle, not reimplemented in this plan.

## 10. Preauthorized Architectural Decisions and Exception-Handling Matrix

**Rule:** Choose the most restrictive matching row; record row IDs with exact observations in the execution report. AUTO-RESOLVE only applies when every specified condition is verified. DEFER AND CONTINUE permits **only demonstrably independent** tasks; otherwise HARD STOP. For any unforeseen condition affecting dependent code or validity, **HARD STOP**—no improvisation or alternative architecture.

| ID | Observable trigger / source evidence | Class | Exact authorized action | Explicitly prohibited | Gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Clean PR #117 head `ee18ed63…`, main `9775bfca…`, A blob matches | AUTO-RESOLVE | Execute §6; continue | switch PR, rebase or recut B | source preflight / maintainer |
| D02 | PR/main advanced to different commit or target source changed | HARD STOP | Record SHA/diff, stop | auto merge/rebase/change B | source authority / human |
| D03 | Known locally excluded prior generated outputs only | AUTO-RESOLVE | Leave untouched, stage explicit paths | `git clean`, change excludes | repo housekeeping |
| D04 | Unknown tracked/untracked code or staged modifications | HARD STOP | Preserve files, report paths | reset, stash, hide files | repo safety / human |
| D05 | Historical file exact blob SHA, IDs, source and 16 lanes PASS | AUTO-RESOLVE | Use historical Q values read-only | run A or change old result | A provenance |
| D06 | Historical blob/run/source/medians mismatch | HARD STOP | Stop before B timing, record mismatch | reinterpret SHA, regenerate A | A provenance / human |
| D07 | Historical `256501…` differs from PRE-PERF `9775…` as already documented | AUTO-RESOLVE | Record **true measured A source** `256501…` | overwrite actual measured SHA | source identification |
| D08 | PERF-05 family absent from old BM-10 runtime | AUTO-RESOLVE | Apply exact §5 additions only | use perf-02 A=B twice, fake labels, silent config key | framework gate |
| D09 | Python import/format-only error within allowed new code | AUTO-RESOLVE | Fix syntax/import and rerun *same* test; record | change architecture or relax assertion | code QA |
| D10 | Unspecified behavioral conflict in existing BM-10 APIs | HARD STOP | Record symbol, inputs, conflicting contract | choose alternative scheduler or runner | design owner |
| D11 | One B worktree+release build and no others; SHA validated as commit | AUTO-RESOLVE | Stage B and check oracles | build ambient HEAD or A/T/J | B identity |
| D12 | Missing B Git object or inability to build exact pinned B | HARD STOP | Stop before acquisition | shallow fallback, use latest `main` | B build / human |
| D13 | B deterministic oracle fails or index counts/bytes unexpectedly differ | HARD STOP | Preserve evidence, do not acquire | alter corpus, skip bad docs | correctness / human |
| D14 | Cache matching verified config/source/host fingerprint is a HIT | AUTO-RESOLVE | Reuse after all untimed oracles | rebuild just for fresh clock | preparation |
| D15 | Cache completed but corrupt/inconsistent | HARD STOP | Record key, preserve cache and stop | delete cache in use or ignore digest | prep safety / human |
| D16 | Host ready under BM-10 declared checks | AUTO-RESOLVE | Run one scheduled B/B study | independent idle tests/waits | measurement |
| D17 | Host readiness busy/affinity lost; source/ABI mismatch | HARD STOP | Save incomplete if started; stop | relax thresholds, rerun | validity / human |
| D18 | All 16 B/B controls PASS, records complete | AUTO-RESOLVE | Compute §4.3 historical descriptive ratios | paired bootstrap of A/B | B validity |
| D19 | Any B/B FAIL, missing/invalid raw sample or query oracle | HARD STOP | Publish INCOMPLETE, preserve samples | rerun unfavorable slots or exclude blocks | statistics / human |
| D20 | All four primary ratios ≤0.95, other 12 ≤1.10, context match | AUTO-RESOLVE | Label `TARGETS_MET` **descriptive** and request review | auto accept/merge or causal CI | review / human |
| D21 | Any target/guard ratio fails, all measurements valid | AUTO-RESOLVE | Label `TARGETS_NOT_MET`, report every regression | rerun/tune/change code | review / human |
| D22 | Material host/compiler/sort/context difference, otherwise valid B | DEFER AND CONTINUE | Preserve B result, report `CONTEXT_CHANGED`, finish independent docs | claim target met or normalize ratios | accept decision / human |
| D23 | RustFS not running / no Docker / no credentials | AUTO-RESOLVE | **Ignore completely; RustFS not part of this scope** | provision or run RustFS | none |
| D24 | `perf`, profiling symbols or callgraph unavailable | AUTO-RESOLVE | **Ignore completely; profiling not executed** | diagnostics, rebuild with flags | none |
| D25 | Historical A comparison helper asked to compute CI or to reinterpret within-run `compare` | HARD STOP | Preserve data, request plan amendment | fabricate paired rows | statistical integrity |
| D26 | Full Python tests/branch coverage ≥85% and formatting check PASS | AUTO-RESOLVE | Commit allowed files and proceed | rerun Rust full QA merely to fill time | QA |
| D27 | Python tests/coverage fail | HARD STOP after bounded syntax fix | Preserve evidence, stop benchmark | exclude tests, change floor | QA / human |
| D28 | CI pending but local deterministic suite passed | DEFER AND CONTINUE | Complete source-safe docs; record `HOSTED_CI_PENDING` | claim CI PASS | CI / human |
| D29 | Existing B5 exact-head Rust CI #522 green, no Rust changes | AUTO-RESOLVE | Cite prior QA; no additional local RustFS/Rust tests | modify Rust or imply new Rust tests run | Rust baseline |
| D30 | Single B result COMPLETE or INCOMPLETE published exclusively | AUTO-RESOLVE | Commit immutable config/result/report to PR #117 | overwrite or second run | publication |
| D31 | Result publisher fails (collision/IO) after acquisition | HARD STOP | Preserve raw scratch and evidence; no retry | rename result manually or rerun | artifact safety / human |
| D32 | Unknown condition outside table, no provably independent safe work | HARD STOP | Preserve evidence, return exact stop | invent fix/threshold/new arm | architecture / human |

**Exception log fields:** ID, observed trigger, path/function/test/command, comparison to preconditions, action taken, pending/blocked gate, final disposition and human decision required if any. No blanket discretion to self-approve deviations.

## 11. Run/report checklist and output contract

Report all of the following with exact commands and observed output (not assumed):

- [ ] Starting/remote SHA, main SHA, B5 ancestry, historical file blob SHA and B and A actual source IDs separately.
- [ ] `PERF05C_DETAILED_PLAN.md` byte-identical; `PERF05C_EXECUTION_REPORT.md` truthfully completed, no unauthorized files.
- [ ] No A/T/J/RustFS/profile/process-cold/retained-key runtime work; B-only indexing 10K/100K and B-only 9,600 scheduled warm calls.
- [ ] All 16 B/B stability comparisons PASS and all 16 B actual oracle/score/sort/total-hit expectations valid.
- [ ] All 16 A source medians and 12 blocks matched immutable historical result; no `A` new result, no A phase.
- [ ] Actual B build exact commit `ee18ed63…`, uninstrumented release/locked, pinned worktree removed; no ambient HEAD confusion.
- [ ] B result status, per-lane A/B descriptive ratio, both primaries/guards, context matches/differences, limitations.
- [ ] Python `pytest` and branch coverage ≥85%, existing CI status, B5 Rust CI evidence, changed-path scope, `git diff --check`.
- [ ] New config/result JSON names and IDs, saved actual path, run UUID, source SHA and hash, no other benchmark artifacts overwritten.
- [ ] No automatic retry, code tuning, forced push, merge or adoption.

**Final dispositions (exact family-specific labels):**

- `PERF05C_B_ONLY_QUALIFIED_HISTORICAL_TARGETS_MET_REVIEW_REQUIRED`
- `PERF05C_B_ONLY_QUALIFIED_HISTORICAL_TARGETS_NOT_MET_REVIEW_REQUIRED`
- `PERF05C_B_ONLY_QUALIFIED_CONTEXT_CHANGED_REVIEW_REQUIRED`
- `PERF05C_B_ONLY_INCOMPLETE_<GATE>`
- `PERF05C_HARD_STOP_<CAUSE>`

All complete outcomes are **independent B session qualification with historical A descriptive comparison**, not paired statistical causality. PR #117 remains OPEN/unmerged for human review. A diagnostic profiler plan, if ever needed, is separate and not authorized here.

## 12. Predefined commit/PR procedure

Commit 1: narrow Python benchmark `perf-05` family + deterministic tests + documentation + copied plan. Example: `bench(perf05c): add pinned B-only warm qualification with historical A reader`. Push to **existing PR #117** without force. Verify remote SHA and Python framework CI state. No new PR. The coding agent must not change `main` or cherry-pick unrelated source pinning changes from separate work.

Then stage/execute **exactly once**, create a unique new config and new immutable result. Commit 2: configuration, result and truthfully filled execution report, e.g. `bench(perf05c): retain B-only qualification and historical comparison`. Push to same branch and verify remote HEAD matches local. No merge.

**Suggested PR summary update (no extra PR):** “PERF-05-C measured only Quervant B1–B5 at a pinned B5 revision. Reused the existing Nov 22, 2026 baseline Q results without rerunning A, Tantivy or Lucene. Used B/B control, native local indexes, exact oracles, complete 16-lane warm observations and explicitly descriptive cross-session comparisons. No RustFS, profiling, altered engine code, or causal paired CI.”

## 13. Next work and stop boundary

After the single authorized result, independent reviewer assesses provenance, tests, control stability and historical-relative trend. A human may accept, reject, or commission a **new separately approved** paired comparison or diagnostic investigation if across-session ambiguity matters. The coding agent must not decide the architecture, relax the quantitative flags, automatically start PERF-04, merge #117, or schedule another benchmark.

**Final rule:** B-only means *the sole executable under timing is the optimized Quervant B5 source*. Using historical A means *reading validated saved JSON, not rebuilding or sampling A*. Any procedure that violates either rule is out of scope and must STOP.
