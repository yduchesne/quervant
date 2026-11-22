# BM-10 — Direct Benchmark Framework

**Status:** Source implementation and deterministic mock tests; real retained-key and cross-engine performance measurements **not executed** in this PR. The `v0.1-bench` milestone remains incomplete until both real studies pass their separate acceptance criteria.

## Exactly two persisted benchmark artifact types

**Field-by-field format references:** [Configuration JSON](../docs/BENCHMARK_CONFIGURATION.md) · [Result JSON](../docs/BENCHMARK_RESULT.md). The [configuration → result relationship](../docs/BENCHMARK_RESULT.md#2-how-a-result-relates-to-its-configuration) explains the stable configuration ID, originating filename, embedded configuration snapshot, new run UUID, execution date, and cross-date sequence. These references describe the implemented formats, not a future generic schema.

1. **Configuration** — `benchmarks/studies/<family>/<regime>/configurations/<name>-<yyyy-mm-dd>.json` (UTC configuration creation date, human-readable slug and description, permanent `configuration_id`, immutable after results refer to it).
2. **Result** — `benchmarks/studies/<family>/<regime>/results/<same-name>-<yyyy-mm-dd>-<NNN>.json` (UTC execution date, original configuration filename/ID, permanent `run_id`, raw timed samples, A/A control observations, statistics, per-arm indexing/commit/index-size observations, throughput where measured, host/build settings, limitations and failures). `NNN` starts at `001` and increments across dates for the **same configuration**. Result publication is exclusive and never overwrites an existing filename.

Supported studies are **retained-key/warm**, **cross-engine/warm**, and **cross-engine/cold-start**. A `retained-key/cold-start` directory is intentionally absent because retained-key measures warm duplicate-strategy effectiveness, not startup overhead. Each study has sibling `configurations/` and `results/` directories. The CLI automatically selects the first and publishes to the second. Git does not track empty `results/` directories before the first result. See the [permanent study layout](../docs/BENCHMARKING.md#permanent-study-directory-hierarchy).

There are **no receipts, seals, evidence manifests, G0 approvals, certifications, attestation records or third-party evidence bundles**. The `.md` view is printed to stdout from saved values and is not a separately persisted benchmark artifact. Build, index and generated corpus files under `target/bm10` are disposable execution scratch, not evidence artifacts. Git commit/push is a separate repository operation after a local result is written.

## CLI

The cross-engine benchmark is now **two independent configurations and results**: [warm comparison (16 lanes)](studies/cross-engine/warm/configurations/quervant-tantivy-lucene-warm-2026-11-22.json) and [process-cold startup (one lane)](studies/cross-engine/cold-start/configurations/quervant-tantivy-lucene-cold-start-2026-11-22.json). Each has its own configuration UUID and independent result sequence. Both use the accepted Quervant production default. The earlier **unexecuted combined configuration** has been replaced, not silently edited.

With `python -m pip install -e benchmarks` or `PYTHONPATH=benchmarks`, the installed entry point is `quervant-bench` (also `python -m quervant_bench`). Examples:

```bash
# Create one dated configuration under studies/retained-key/warm/configurations.
# The default --studies-root is benchmarks/studies. Never overwrite an old spec.
quervant-bench prepare \
  --family retained-key --name retained-key-prefilter-v2 \
  --description 'Four-arm retained-key comparison, prefilter P2'

# Validate a configuration without doing work or timing anything.
quervant-bench validate --config benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json

# Explicit real benchmark execution only on a dedicated, correctly configured Linux/WSL2 host.
# DO NOT RUN during BM-10 framework implementation, tests, or coding-agent handoff.
quervant-bench run --config benchmarks/studies/retained-key/warm/configurations/retained-key-prefilter-2026-11-22.json

# Presentation ONLY, no statistical calculations, source checks, or acquisition.
quervant-bench report --result benchmarks/studies/<family>/<regime>/results/<name>-<date>-001.json

# Separate, read-only recalculation of stored raw measurements.
quervant-bench analyze --result benchmarks/studies/<family>/<regime>/results/<name>-<date>-001.json

# Comparison of WITHIN-run signed gains, never unmatched old/new absolute durations.
quervant-bench compare --current <current-result.json> --historical <older-result.json> \
  --lane '10000/medium/k100/warm' --arm P
```

`run` executes **Prepare → Validate → Measure → Analyze → Save** without manual approvals, then renders the saved result immediately to Markdown on stdout. If a sample, search oracle, strategy marker, host readiness or subprocess fails, it writes an `INCOMPLETE` result with all successfully captured observations and diagnostic errors. No favorable reruns are authorized. A `REGRESSED` or `INCONCLUSIVE` statistical decision is a valid completed result, not a framework failure.

## Method and comparability

**Query measurement always follows [the permanent three-stage sequence](../docs/BENCHMARKING.md#query-benchmark-execution-sequence-permanent-methodology):** (1) build, commit and verify each arm's index; (2) open the **existing** index and initialize its reader; (3) perform untimed warmups where applicable, then measure queries under the declared schedule. **Indexing and commit are excluded from both warm query `engine_ns` and cold first-response wall time**. Warm `engine_ns` also excludes reader opening. Cold-start measures fresh opening separately as adapter `index_open_ns` while its total wall duration includes only process launch through first query response against the already-built index. Indexing and commit durations remain independently recorded descriptive metrics, not qualified write-performance comparisons.

- Retained-key uses A (a **pinned historical pre-optimization** source; not the baseline for future improvements), L (`linear`), P (`prefilter`, profile P2), H (`exact_set`); 10K/100K corpora, absent/rare/medium/common match classes and K = 1, 10, 32, 64, 100, 128, 256, 512, 1024, warm regime. This is a **retrospective optimization study**.
- Cross-engine uses **Q = current production-default Quervant**, T (Tantivy), J (Lucene). Quervant's confirmed default is linear below K=32 and P2 prefilter from K=32 onward. Q is compiled **without** the experimental strategy feature; experimental overrides are removed. The **warm study** measures all 16 lanes: 10K/100K corpora, four cardinality classes and K=10/100. The separate **cold-start study** measures **one lane**, 10K/medium/K100, including process launch, index/reader open and query/JSONL response. The latter is not OS-page-cache-cold and is not directly comparable to warm search-only `engine_ns`.
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
- No new optimization is adopted, no production search default is changed, and no real speedup or competitive ranking is claimed.
- CI tests the framework and compile-only/correctness contracts as applicable. Real performance campaigns must be scheduled separately; they are **not** a CI or coding-agent handoff step.
- Historical BM-01–BM-09 certification machinery is retired from the new execution path; history remains in the repository's archived source/PR references. The canonical naming and scientific rules are in `docs/BENCHMARKING.md` (PR #112 is already merged). The exact current configuration/result field contracts are linked above.
