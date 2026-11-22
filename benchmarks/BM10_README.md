# BM-10 — Direct Benchmark Framework

**Status:** Source implementation and deterministic mock tests; real retained-key and cross-engine performance measurements **not executed** in this PR. The `v0.1-bench` milestone remains incomplete until both real studies pass their separate acceptance criteria.

## Exactly two persisted benchmark artifact types

1. **Configuration** — `benchmarks/configurations/<name>-<yyyy-mm-dd>.json` (UTC configuration creation date, human-readable slug and description, permanent `configuration_id`, immutable after results refer to it).
2. **Result** — `benchmarks/results/<same-name>-<yyyy-mm-dd>-<NNN>.json` (UTC execution date, original configuration filename/ID, permanent `run_id`, raw timed samples, A/A control observations, statistics, per-arm indexing/commit/index-size observations, throughput where measured, host/build settings, limitations and failures). `NNN` starts at `001` and increments across dates for the **same configuration**. Result publication is exclusive and never overwrites an existing filename.

There are **no receipts, seals, evidence manifests, G0 approvals, certifications, attestation records or third-party evidence bundles**. The `.md` view is printed to stdout from saved values and is not a separately persisted benchmark artifact. Build, index and generated corpus files under `target/bm10` are disposable execution scratch, not evidence artifacts. Git commit/push is a separate repository operation after a local result is written.

## CLI

With `python -m pip install -e benchmarks` or `PYTHONPATH=benchmarks`, the installed entry point is `quervant-bench` (also `python -m quervant_bench`). Examples:

```bash
# Create one dated configuration, exactly once; NEVER overwrite it.
quervant-bench prepare \
  --family retained-key --name retained-key-prefilter-v2 \
  --description 'Four-arm retained-key comparison, prefilter P2'

# Validate a configuration without doing work or timing anything.
quervant-bench validate --config benchmarks/configurations/retained-key-prefilter-2026-11-22.json

# Explicit real benchmark execution only on a dedicated, correctly configured Linux/WSL2 host.
# DO NOT RUN during BM-10 framework implementation, tests, or coding-agent handoff.
quervant-bench run --config benchmarks/configurations/retained-key-prefilter-2026-11-22.json

# Presentation ONLY, no statistical calculations, source checks, or acquisition.
quervant-bench report --result benchmarks/results/<name>-<date>-001.json

# Separate, read-only recalculation of stored raw measurements.
quervant-bench analyze --result benchmarks/results/<name>-<date>-001.json

# Comparison of WITHIN-run signed gains, never unmatched old/new absolute durations.
quervant-bench compare --current <current-result.json> --historical <older-result.json> \
  --lane '10000/medium/k100/warm' --arm P
```

`run` executes **Prepare → Validate → Measure → Analyze → Save** without manual approvals, then renders the saved result immediately to Markdown on stdout. If a sample, search oracle, strategy marker, host readiness or subprocess fails, it writes an `INCOMPLETE` result with all successfully captured observations and diagnostic errors. No favorable reruns are authorized. A `REGRESSED` or `INCONCLUSIVE` statistical decision is a valid completed result, not a framework failure.

## Method and comparability

- Retained-key uses A (`BASE`, separately pinned baseline source), L (`linear`), P (`prefilter`, profile P2), H (`exact_set`); 10K/100K corpora, absent/rare/medium/common match classes and K = 1, 10, 32, 64, 100, 128, 256, 512, 1024, warm regime.
- Cross-engine uses Q (Quervant linear at K=10, P2 prefilter at K=100, verified by runtime marker), T (Tantivy), J (Lucene); 10K/100K, the same exact-keyword corpus and cardinality classes, warm and process-cold separately. A process-cold reader restart does **not** guarantee an OS-page-cache cold state.
- All experiments use seeded, randomized, exactly position-balanced **paired blocks** with two slots per arm. Slot median is the median of measured requests; each arm/block value is the mean of its two slot medians. The effect is the median of paired **B/A** block ratios, not an unpaired ratio of sample pools; uncertainty resamples whole blocks with a deterministic seed.
- Gains are `100*(1-B/A)` for lower-is-better metrics and `100*(B/A-1)` for higher-is-better metrics. An A/A phase checks measurement stability. Baseline/arm absolute measurements and complete samples are preserved even when comparisons are inconclusive.
- Cross-engine competitive ratios are only meaningful after the actual adapter timed boundaries, total-hit semantics, sorted-result materialization, reader lifecycle and cache regimes have been independently checked on the real host. Noncomparable lanes must not be ranked or aggregated.
- Index insert and commit durations, reopen duration, index bytes and warm-session **serial ops/s** are separately labeled. Throughput is measured by sequential request/response wall-clock, excluding process startup; it is not derived from `engine_ns` latency or assumed parallel throughput.
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
- Historical BM-01–BM-09 certification machinery is retired from the new execution path; history remains in the repository's archived source/PR references. The canonical naming and scientific rules are in `docs/BENCHMARKING.md` after documentation PR #112 is merged and the implementation PR is rebased.
