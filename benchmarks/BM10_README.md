# BM-10 — Direct Benchmark Framework

**Status: BM-10 DONE — MERGED** ([PR #113](https://github.com/yduchesne/quervant/pull/113), 2026-11-22); **BM implementation series CLOSED**. The original 2026-11-22 cross-engine warm result (`quervant-tantivy-lucene-warm-2026-11-22-001.json`) used Tantivy numeric `ordinal` sorting and remains immutable **historical, not strict string-sort-comparable** evidence. The corrected native ascending `doc_id` keyword/string, Tantivy 0.25.0 **16-lane warm campaign has now run and completed** as [`quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json`](studies/cross-engine/warm/results/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22-001.json) (16/16 A/A PASS, valid readiness, preserved raw samples). Retained-key and process-cold campaigns were **not executed** and remain operational follow-ups; the original three-study `v0.1-bench` C6 criterion is incomplete.

## Exactly two persisted benchmark artifact types

**Field-by-field format references:** [Configuration JSON](../docs/BENCHMARK_CONFIGURATION.md) · [Result JSON](../docs/BENCHMARK_RESULT.md). The [configuration → result relationship](../docs/BENCHMARK_RESULT.md#2-how-a-result-relates-to-its-configuration) explains the stable configuration ID, originating filename, embedded configuration snapshot, new run UUID, execution date, and cross-date sequence. These references describe the implemented formats, not a future generic schema.

1. **Configuration** — `benchmarks/studies/<family>/<regime>/configurations/<name>-<yyyy-mm-dd>.json` (UTC configuration creation date, human-readable slug and description, permanent `configuration_id`, immutable after results refer to it).
2. **Result** — `benchmarks/studies/<family>/<regime>/results/<same-name>-<yyyy-mm-dd>-<NNN>.json` (UTC execution date, original configuration filename/ID, permanent `run_id`, raw timed samples, A/A control observations, statistics, per-arm indexing/commit/index-size observations, throughput where measured, host/build settings, limitations and failures). `NNN` starts at `001` and increments across dates for the **same configuration**. Result publication is exclusive and never overwrites an existing filename.

Supported studies are **retained-key/warm**, **cross-engine/warm**, **cross-engine/cold-start**, **perf-02/warm** (prospective, pinned two-revision Quervant A/B), **perf-05/warm** (B-only historical descriptive reference), and **perf-06/warm** (cumulative PERF-06 A-series paired A/B qualification). A `retained-key/cold-start`, `perf-02/cold-start` or `perf-06/cold-start` directory is intentionally absent because those families measure warm query execution, not startup overhead. Each study has sibling `configurations/` and `results/` directories. The CLI automatically selects the first and publishes to the second. Git does not track empty `results/` directories before the first result. See the [permanent study layout](../docs/BENCHMARKING.md#permanent-study-directory-hierarchy).

There are **no receipts, seals, evidence manifests, G0 approvals, certifications, attestation records or third-party evidence bundles**. The `.md` view is printed to stdout from saved values and is not a separately persisted benchmark artifact. Build, index and generated corpus files under `target/bm10` are disposable execution scratch, not evidence artifacts. Git commit/push is a separate repository operation after a local result is written.

## PERF-02-A Quervant A/B warm study support [DONE — IMPLEMENTATION]

The `perf-02/warm` family compares exactly two independently compiled **Quervant** release adapters. `arms.A.revision` and `arms.B.revision` are full immutable 40-hex Git commit SHAs; staging refuses unavailable/non-commit objects and builds each arm in its own temporary detached Git worktree and Cargo target directory. Both source identities are included in the preparation cache and result build provenance. All 16 warm exact-keyword lanes, A/A, readiness, correctness oracles, paired-block statistics and immutable result publication are inherited from BM-10. No Tantivy/Lucene build or serial throughput phase is involved.

The versioned [PERF-02-A A=A study](studies/perf-02/warm/configurations/quervant-sort-processing-equal-build-2026-11-22.json) pins **both** arms to the same pre-PR accepted production revision, while still building them separately. **PERF-02-A does not require a timed run.** On the real host, validate and stage this configuration to check separate builds, indexes and 32 untimed lane/arm oracles. **Stop after `stage`**: do not invoke `quervant-bench run` or collect A/A or A/B timing as part of PERF-02-A. The full acquisition is deferred to a PERF-02-B candidate study. See the [coding-agent handoff](../docs/pr-artifacts/perf-02-a/REAL_HOST_HANDOFF.md).

To generate a **new** prospective PERF-02 candidate configuration (only after candidate source exists), run:

```bash
quervant-bench prepare --family perf-02 --regime warm \\
  --name quervant-sort-processing-candidate-v1 \\
  --description 'Pinned Quervant PERF-02 warm A/B candidate' \\
  --baseline-revision <40-hex-baseline-SHA> \\
  --candidate-revision <40-hex-candidate-SHA>
```

The `perf-02` arms use production `by-top-k` dispatch; the historical `pr15i-d3c-experiment` feature and strategy environment overrides are **not** enabled. Qualification uses only uninstrumented warm query measurements; Criterion, perf and allocation sampling are diagnostic inputs, not statistical A/B acceptance.

## CI configuration validation

The existing `python-benchmark-framework` job in `.github/workflows/ci.yml` automatically discovers **every** JSON configuration under `benchmarks/studies/**/configurations/*.json` and validates it using the production configuration loader and semantic validator. The job fails if no configurations are found or if any configuration is malformed, misplaced or semantically invalid. New studies/configurations do **not** require another CI job or a manually added workflow command. This validation performs **no real benchmark acquisition**; host-dependent timing is always a separate operation.

## CLI

For **new** cross-engine acquisitions, use the [strict `doc_id` string-sort warm configuration (16 lanes)](studies/cross-engine/warm/configurations/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22.json) and the [strict string-sort process-cold configuration (one lane)](studies/cross-engine/cold-start/configurations/quervant-tantivy-lucene-lexical-sort-cold-start-2026-11-22.json). Each has a distinct UUID and independent result sequence. The previous [warm numeric-sort configuration](studies/cross-engine/warm/configurations/quervant-tantivy-lucene-warm-2026-11-22.json) and its [completed historical result](studies/cross-engine/warm/results/quervant-tantivy-lucene-warm-2026-11-22-001.json) are preserved; the previous unexecuted [cold configuration](studies/cross-engine/cold-start/configurations/quervant-tantivy-lucene-cold-start-2026-11-22.json) is also retained as a retired specification. Legacy numeric-sort configurations can be validated/read but **cannot be staged or rerun** with the upgraded Tantivy adapter.

With `python -m pip install -e benchmarks` or `PYTHONPATH=benchmarks`, the installed entry point is `quervant-bench` (also `python -m quervant_bench`). Examples:

```bash
# Create one dated configuration under studies/retained-key/warm/configurations.
# The default --studies-root is benchmarks/studies. Never overwrite an old spec.
quervant-bench prepare \
  --family retained-key --name retained-key-prefilter-v2 \
  --description 'Four-arm retained-key comparison, prefilter P2'

# Validate a configuration without doing work or timing anything.
quervant-bench validate --config benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json

# Explicit separate input preparation (release builds, index/commit, untimed oracles).
# No A/A, timed query campaign or result JSON. Requires a real compatible host;
# Stage only when operating on an authorized real host; this is not a mocked CI check.
quervant-bench stage --config benchmarks/studies/cross-engine/warm/configurations/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22.json

# Explicit real benchmark acquisition on a dedicated, idle Linux/WSL2 host.
# Reuses a matching staged input set automatically; stages once if absent.
# Real benchmark acquisition is an explicit operator action, not an automatic test/CI step.
quervant-bench run --config benchmarks/studies/cross-engine/warm/configurations/quervant-tantivy-lucene-lexical-sort-warm-2026-11-22.json

# Presentation ONLY, no statistical calculations, source checks, or acquisition.
quervant-bench report --result benchmarks/studies/<family>/<regime>/results/<name>-<date>-001.json

# Separate, read-only recalculation of stored raw measurements.
quervant-bench analyze --result benchmarks/studies/<family>/<regime>/results/<name>-<date>-001.json

# Comparison of WITHIN-run signed gains, never unmatched old/new absolute durations.
quervant-bench compare --current <current-result.json> --historical <older-result.json> \
  --lane '10000/medium/k100/warm' --arm P
```

`run` executes **Validate → Stage/reuse prepared inputs → Independent readiness/A/A → Measure → Analyze → Save** without manual approvals, then renders the saved result immediately to Markdown on stdout. `stage` can execute the heavy release build, corpus creation, indexing/commit/reopen and independent **untimed** oracle validation in advance, without a query benchmark campaign. Under `target/bm10/prepared/<cache-key>/` the temporary input cache is reusable only if configuration content, unchanged committed build-relevant source trees/files, build environment, toolchain and host match and required files plus every declared-lane oracle revalidate. A results-only or documentation-only Git commit does not invalidate an otherwise matching prepared input set; dirty build/runner source does. A completed corrupted cache blocks reuse until manually retired when no run is using it; a changed identity creates a separate entry. Cache metadata is not a third persisted benchmark artifact or integrity certificate. The runner records phase durations and `BUILT`/`HIT` in its result so preparation overhead is distinguishable from A/A, treatment and throughput. The same `--scratch-root` should be used for `stage` and `run` if overriding `target/bm10`; only the result JSON is Git-trackable. See the [permanent preparation and wall-clock accounting rules](../docs/BENCHMARKING.md#reusable-preparation-versus-timed-query-acquisition-permanent-rule). If a sample, search oracle, strategy marker, host readiness or subprocess fails, it writes an `INCOMPLETE` result with all successfully captured observations and diagnostic errors. No favorable reruns are authorized. A `REGRESSED` or `INCONCLUSIVE` statistical decision is a valid completed result, not a framework failure.

## Method and comparability

**Query measurement always follows [the permanent three-stage sequence](../docs/BENCHMARKING.md#query-benchmark-execution-sequence-permanent-methodology):** (1) build, commit and verify each arm's index; (2) open the **existing** index and initialize its reader; (3) perform untimed warmups where applicable, then measure queries under the declared schedule. **Indexing and commit are excluded from both warm query `engine_ns` and cold first-response wall time**. Warm `engine_ns` also excludes reader opening. Cold-start measures fresh opening separately as adapter `index_open_ns` while its total wall duration includes only process launch through first query response against the already-built index. Indexing and commit durations remain independently recorded descriptive metrics, not qualified write-performance comparisons.

- Retained-key uses A (a **pinned historical pre-optimization** source; not the baseline for future improvements), L (`linear`), P (`prefilter`, profile P2), H (`exact_set`); 10K/100K corpora, absent/rare/medium/common match classes and K = 1, 10, 32, 64, 100, 128, 256, 512, 1024, warm regime. This is a **retrospective optimization study**.
- **Strict cross-engine sorting contract:** Q, T and J all sort the actual stored **keyword/string `doc_id` in ascending lexical order** (not numeric ID order). T is pinned to Tantivy 0.25.0 with native `TopDocs::order_by_string_fast_field("doc_id", Order::Asc)`; the numeric `ordinal` field has been removed. Adversarial `d1, d10, d2` and multi-segment tests exercise this difference. Q and J retain their native string-sort paths; exact counts and projected IDs remain measured. The previous numeric-surrogate run is not reinterpreted or overwritten.
- Cross-engine uses **Q = current production-default Quervant**, T (Tantivy), J (Lucene). Quervant's confirmed default is linear below K=32 and P2 prefilter from K=32 onward. Q is compiled **without** the experimental strategy feature; experimental overrides are removed. The **warm study** measures all 16 lanes: 10K/100K corpora, four cardinality classes and K=10/100. The separate **cold-start study** measures **one lane**, 10K/medium/K100, including process launch, index/reader open and query/JSONL response. The latter is not OS-page-cache-cold and is not directly comparable to warm search-only `engine_ns`.
- **Query optimization selection uses qualified warm performance only.** For PERF-02 and later search optimizations, compare the candidate against the accepted production baseline on predeclared **warm search latency** target/guardrail lanes with correctness and A/A/readiness controls. **Cold-start timings cannot qualify, rank, select or rescue a query optimization**; report them as separate operational diagnostics, including regressions. A startup-specific optimization requires a separately defined contract. See the [permanent selection rule](../docs/BENCHMARKING.md#query-optimization-selection-warm-performance-is-authoritative-permanent-rule).
- **Baseline promotion:** Once an optimization is accepted into production, it becomes part of the Quervant reference for every *subsequent* optimization and cross-engine study. See [the canonical methodology](../docs/BENCHMARKING.md#within-run-comparisons-treatment-versus-baseline).
- All experiments use seeded, randomized, exactly position-balanced **paired blocks** with two slots per arm. Slot median is the median of measured requests; each arm/block value is the mean of its two slot medians. The effect is the median of paired **B/A** block ratios, not an unpaired ratio of sample pools; uncertainty resamples whole blocks with a deterministic seed.
- Gains are `100*(1-B/A)` for lower-is-better metrics and `100*(B/A-1)` for higher-is-better metrics. An A/A phase checks measurement stability. Baseline/arm absolute measurements and complete samples are preserved even when comparisons are inconclusive.
- Cross-engine competitive ratios are only meaningful after the actual adapter timed boundaries, total-hit semantics, sorted-result materialization, reader lifecycle and cache regimes have been independently checked on the real host. Noncomparable lanes must not be ranked or aggregated.
- The cold-start study retains 12 balanced blocks, two slots per arm, 20 fresh processes per slot and the A/A control: **2,400 planned process launches** across three comparison arms plus two control roles, versus 38,400 under the discarded 16-lane cold design. It records wall-clock launch-to-first-reply latency in `samples_ns`, adapter-measured reader/index opening in `index_open_samples_ns`, query/search-only `engine_samples_ns`, and the remaining `other_overhead_samples_ns` (process/JVM startup, scheduling, JSONL transport; not pure OS startup). Every raw observation must reconcile, and a missing opening timer fails closed. The adapters emit `index_open_ns` **only on the first query following a reader open**. No warm throughput phase runs in the cold-start study.
- Index insert and commit durations, reopen duration, index bytes and warm-session **serial ops/s** are separately labeled. **Write-side indexing** timings are descriptive; the statistical paired primary measurement is read-side query latency (warm) or first-response latency (cold). The cold-session `index_open_ns` is a **read-side initialization** measurement and must not be confused with write-phase `reopen_ns`. Throughput is measured by sequential request/response wall-clock, excluding process startup; it is not derived from `engine_ns` latency or assumed parallel throughput.
- Historical comparison uses `current_gain_percent - historical_gain_percent` in **percentage points** only if workload and estimator match. Context changes are disclosed; no code-only causal claim follows from mismatched hosts.

## Local testing — no real benchmarks

```bash
python -m pip install -e ./benchmarks
python -m pip install pytest coverage
python -m compileall -q benchmarks/quervant_bench
python -m pytest -q benchmarks/quervant_bench/lean/tests
coverage run --branch --source=quervant_bench.lean -m pytest -q benchmarks/quervant_bench/lean/tests
coverage report --fail-under=85
python -m quervant_bench --help
quervant-bench --help
```

Every adapter/process test uses a stub, mock, pure oracle or synthetic JSONL child; these commands **must not** build or measure production engines. Existing standalone PR15D benchmark adapter code and historical PR15I-D3-C artifacts remain unmodified. Separate framework-implementation acceptance and real study qualification are required; the latter is explicitly deferred.

## Known boundaries

- `run` intentionally rejects unsupported hosts, unsuitable filesystems, missing distinct physical cores, failed CPU contention checks, unavailable toolchains and incorrect query answers. It does not obtain any administrative approval.
- BM-10 did not adopt a new query optimization or change Quervant's production search default. The corrected warm result supports **per-lane** comparisons, not a universal ranking or a causal F1 speedup claim.
- CI tests the framework and compile-only/correctness contracts as applicable. Real performance campaigns must be scheduled separately; they are **not** a CI or coding-agent handoff step.
- Historical BM-01–BM-09 certification machinery is retired from the new execution path; history remains in the repository's archived source/PR references. The canonical naming and scientific rules are in `docs/BENCHMARKING.md` (PR #112 is already merged). The exact current configuration/result field contracts are linked above.

## PERF-05 B-only warm study

`perf-05/warm` is a narrow B-only family used by PERF-05-C. It pins one Quervant commit (`arms.B.revision`), builds that single release adapter from a detached worktree, indexes 10K/100K locally, and runs one 16-lane warm B/B stability acquisition using temporary `BB`/`BB2` aliases of the same B executable. It then compares B's absolute block medians descriptively against the retained 2026-11-22 historical Q result (blob `a809f036…`, measured source `256501f0…`).

Create it with:

```bash
quervant-bench prepare --family perf-05 --regime warm \
  --name quervant-perf05-b-only-warm \
  --description 'PERF-05 pinned B-only warm study against retained historical A' \
  --quervant-revision ee18ed63bbeeb54b544393ee0f676987ff9987d1
```

No A, Tantivy, Lucene, RustFS or profiler acquisition occurs, and no paired confidence interval is claimed. See [BENCHMARK_CONFIGURATION.md](../docs/BENCHMARK_CONFIGURATION.md#perf-05-b-only-warm-family) and [BENCHMARK_RESULT.md](../docs/BENCHMARK_RESULT.md#perf-05-b-only-result-shape).

## PERF-06 A-series paired warm qualification (`perf-06/warm`)

`perf-06/warm` is a **paired** cumulative A-series qualification family. It is *not* a new runner: it routes through the identical `perf-02` two-pinned-arm code path (independent detached worktrees, separate release targets, 16 warm lanes, A/A control, paired block bootstrap, exclusive result publication). Its only difference from `perf-02` is the registered family name and the two pinned source commits, so an A-series result is never filed under `perf-02/warm`.

Full methodology and authorization are in [the approved PERF-06-A4 plan](../docs/pr-artifacts/perf-06-a/PERF06A4_DETAILED_PLAN.md). The currently authorized arms are the accepted pre-A1 PERF-05 source (`2a74017958c8ac61948f931e8745bf8134827025`, arm `A`) and the merged A1+A2+A3 source (`b70f624fffe0329def62701b61e997c4e303e167`, arm `B`). Because A3 changes the persisted postings format, the two indexes legitimately differ in bytes; each arm is validated against its own untimed oracles and fingerprints, and index/commit/reopen metrics are reported **separately** from warm `engine_ns`.

The historical PERF-05 B-only result is **historical and unpaired** and is never used as this family's A baseline.

### Operator sequence (per authorized campaign)

```bash
# 1. Create the one immutable configuration for this campaign (UTC-dated filename).
#    The CLI prints the exact path; never glob or hand-author it.
quervant-bench prepare --family perf-06 --regime warm \\
  --name quervant-perf06a-paired-warm \\
  --description 'PERF-06-A4 cumulative A1-A3 paired warm qualification against accepted pre-A1 PERF-05 source; independent indexes, query-only timing' \\
  --baseline-revision 2a74017958c8ac61948f931e8745bf8134827025 \\
  --candidate-revision b70f624fffe0329def62701b61e997c4e303e167
CONFIG='<exact path printed above>'

# 2. Validate the saved specification (no timing).
quervant-bench validate --config "$CONFIG"

# 3. Stage ONCE (untimed): two pinned release builds, both corpora, both indexes,
#    16 lanes x 2 arms untimed oracles, all fingerprints. Prints PREPARATION=BUILT|HIT.
quervant-bench stage --config "$CONFIG"

# 4. Exactly ONE authorized timed acquisition: automatic readiness, full A/A
#    control, then A/B treatment only if A/A passes. Publishes one immutable
#    result JSON even when INCOMPLETE (CLI exit code 4).
quervant-bench run --config "$CONFIG"

# 5. Read-only rendering of the saved result.
quervant-bench report --result '<exact RESULT_JSON path printed by run>'
```

`stage` is untimed preparation, not a second acquisition. Do **not** run step 4 more than once for the same configuration, and do not rerun after an `INCOMPLETE` or unfavorable result: those outcomes are preserved and require a new human decision. `COMPLETE` is a structural status only; the predeclared primary/guard thresholds are applied during read-only review and adoption remains a human decision.
