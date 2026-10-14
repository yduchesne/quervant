# Benchmarking architecture and methodology

**Status:** v0.1 design and acceptance policy. PR 7 Amendment 04 implements a
Linux/WSL2 Criterion microbenchmark, deterministic correctness-gated fixtures,
CPU/allocation profiling workflows and a reproducible pre-optimization baseline
for `quervant-core`. Cross-engine adapters (Tantivy/Lucene), remote RustFS and
release qualification remain PR 13/PR 15 work.

## Microbenchmark policy (permanent)

The following policy applies to all Quervant microbenchmarking, not just PR 7:

- **Environment.** Development microbenchmarks run on Linux or WSL2, on a native
  Linux filesystem (`ext4`/`xfs`/`btrfs`), never on `/mnt/c`/`drvfs`. Record the
  kernel, WSL2 status, CPU model, filesystem type and toolchain. Absolute
  latencies are host-specific; do not extrapolate them across environments.
- **Correctness first.** Every timed workload is validated against an independent,
  untimed oracle (exact hit sets, counts and, where applicable, ranking/scores)
  before any measurement. A mismatch aborts the run; no timing is reported.
- **Build outside the timed region.** Dataset generation, indexing, commit,
  snapshot opening and expected-result computation happen before timing. Each
  timed operation is the named production operation only.
- **Same-environment comparisons.** Competitor comparisons require the same
  machine, environment, filesystem, workload, cache regime and correctness gate.
  Conclusions are **relative ratios** on matching query IDs; raw absolute metrics
  are retained as underlying evidence. Never compare a warm Quervant run against a
  cold competitor run, or label non-equivalent analyzers as equivalent.
- **Statistical honesty.** Criterion iteration statistics (with warmup, repeat
  measurements and confidence intervals) are not production p99 latency. Do not
  treat sub-1% differences on a noisy host as significant.
- **Provenance.** Store source SHA, workload version, seed, dataset digest,
  environment, exact command and tool versions. Never overwrite a prior result;
  raw Criterion data stays in untracked `target/`, with concise sanitized
  manifests checked in.
- **Semantic metadata.** Hit counts in reports are generated from an independent
  fixture oracle, never inferred from timing or hardcoded. Non-query
  microbenchmarks carry `hit_count_applicable: false` and a null count, never a
  fabricated zero. The report validator cross-checks every row against the fixture
  metadata and refuses to certify a contradictory or incomplete report.
- **Qualification is not completion.** A run may complete while being unqualified.
  Publication as a comparison baseline requires: correctness PASS, all required
  targets measured, a clean tree, explicit operator confirmation that competing
  benchmark workloads are stopped, and all `/proc` contention checks `clear`.
  Suspected/unknown contention or a dirty tree yields an unqualified diagnostic
  run only. At least three independently qualified trials are aggregated before a
  qualified baseline is published. Contention detection is best-effort and does
  not observe Windows-host processes or other WSL guests; `clear` is not a proof
  of physical isolation.
- **Profiling.** CPU (`perf`/`cargo flamegraph`) and allocation (`heaptrack`)
  profiling run on the same representative workload but are never mixed with
  uninstrumented Criterion baselines. Missing/blocked profilers are reported
  UNAVAILABLE with diagnostics; no privilege escalation or kernel modification.

See `benchmarks/README.md`, `benchmarks/workloads/pr07_amendment04_v1.md` and the
`docs/pr-artifacts/pr-7/amendment-04-*.md` artifacts.

## Objectives and non-goals

Provide reproducible, correctness-gated, apples-to-apples comparisons of **Quervant (local-only)**, **Apache Lucene (Java)**, and **Tantivy (Rust)**. Establish an empirical performance baseline and expose optimization opportunities; **matching or exceeding Lucene/Tantivy is not a v0.1 release gate**. Benchmark Quervant's RustFS-backed ObjectStore/cache separately from local-engine comparisons. Never publish unmeasured performance claims.

## Proposed repository layout

```text
benchmarks/
  README.md
  datasets/            # source manifests, generators, checksums; large corpora not committed
  workloads/           # versioned schemas, queries, indexing/refresh/concurrency scenarios
  runners/
    quervant/           # Rust runner: local-only and remote-backed modes
    tantivy/           # Rust runner
    lucene/            # standalone Java runner using public Lucene APIs
  harness/             # orchestration, resource sampling, correctness and result validation
  reports/             # reproducible scripts and checked-in small report manifests
```

The layout is illustrative. The harness must use a **versioned engine-neutral workload specification** and adapter-specific translation. Each runner must report what it actually executed, not silently approximate unsupported semantics.

## Workload and corpus contracts

- Version and checksum input datasets. Record provenance, license, corpus size, document counts, field distributions, term frequencies, token lengths, and language mix. Use both deterministic synthetic datasets (controlled distributions) and at least one representative real corpus with documented rights to use it.
- Fix logical document IDs, insertion order, field definitions, stored/indexed fields, tokenization/normalization, position/offset options, and update/delete patterns. Where analyzers differ, either provide equivalent analyzer configurations verified against shared token fixtures or label the case **non-comparable**.
- Specify BM25 parameters (including `k1` and `b`), similarity settings, scoring fields, boosts, top-K, total-hit counting, query budgets, Boolean behavior, phrase slop, and prefix/glob/regex term-matching semantics. Validate equivalent result sets and, where meaningful, score/ranking tolerances before timing.
- Workload categories: bulk indexing; sustained ingestion with commits/refresh; deletes and updates; segment flush/merge; cold and warm reader open; term, Boolean, phrase, prefix, glob/wildcard, regex and BM25 top-K search; concurrent search; mixed read/write; resource limits and failure/recovery.
- Use fixed query sets with recorded selectivity and hit counts. Report unsupported operations explicitly as `unsupported`; exclude them from cross-engine aggregate rankings. Query expansion and regex semantics may not be identical across engines; document deviations.
- Separate **search-only** timing from end-to-end request/serialization timing, and **index construction** from durability/commit and merge costs. Include both where relevant.

## Comparison lanes

### Lane A: local lexical engine comparison (primary cross-engine lane)

Run Quervant local-only, Tantivy and Lucene against equivalent local storage and identical corpus/query specifications on the same machine. Record index size, indexing throughput, search QPS, p50/p95/p99 latency, CPU, process RSS, allocations where measurable, disk I/O, segment counts, merge/refresh cost, and correctness. Specify cold vs warm OS page-cache conditions and reader lifecycle; do not claim a cold run merely because an application cache was cleared.

### Lane B: remote storage and cache validation (Quervant-specific)

Use **RustFS through its S3-compatible API** as the initial remote ObjectStore. Test empty-cache bootstrap, whole-file segment materialization and checksum/integrity verification, warm-cache reuse, bounded cache eviction/reload, multiple readers, commit publication ordering, restart/recovery, timeouts, partial downloads, corrupt objects, and collector-independent operation. Report object requests/bytes, network latency/throughput, cache hit rate, disk use, startup time and query performance before/after warming. Distinguish local cache eviction from authoritative remote garbage collection and manifest retention.

**v0.1 PR 13/PR 15 download benchmark matrix:** compare single whole-object GET, parallel ranged GET of a complete large object, and concurrent downloads of independent segments. Use representative segment sizes (16 MiB, 64 MiB, 256 MiB, 1 GiB), per-object range parallelism (1/2/4/8/16), segment concurrency (1/2/4/8), cold and warm caches, and local RustFS plus reproducible latency-injected conditions. Report median/p95 segment completion time, aggregate MiB/s, time to first successful query after cold bootstrap, request count/bytes, CPU, peak RAM, in-flight bytes, temporary disk, cache hits and error/retry behavior. Ensure all compared modes return identical verified bytes and query results; include range-unsupported fallback and interruption/cancellation cases. These are experiment parameters, **not guaranteed speedups**. PR 13 owns implementation/integration evidence; PR 15 owns reproducible comparative qualification.

Do **not** present RustFS cold-start results against warm local Lucene/Tantivy as engine-performance comparisons. Future provider adapters must pass the same remote storage conformance and workload suite; do not rely on RustFS-specific behavior.

### Lane C: instrumentation overhead

On the same Quervant workloads, compare: no subscriber; filtered subscriber; production query/batch spans plus metrics; explicitly enabled verbose diagnostics. Include exporter slowdown/unavailability. Report latency, throughput, CPU, allocations, queue drops and any stalls. Instrument operation boundaries, not individual postings/documents/FST transitions.

## Runner and measurement protocol

1. Pin source revision, benchmark suite version, dependency versions, OS/kernel, CPU model and topology, RAM, filesystem/storage, JDK/JVM version, Rust compiler/profile, Lucene/Tantivy versions, and hardware/container resource limits.
2. For Lucene, implement a dedicated Java runner using public APIs; fix JDK, heap bounds, GC, thread configuration and indexing/query options. Warm up the JVM and capture GC pauses, heap and OS-level RSS. JMH principles may inform microbenchmarks; primary comparisons are end-to-end runner workloads.
3. Normalize thread counts, index writer settings, commit cadence, search concurrency, warmup and query mix. Document engine-specific unavoidable differences instead of hiding them.
4. Isolate benchmark processes, control background load and CPU frequency/power policy as feasible, record disk/cache state, and distinguish cold, warm and steady-state measurements. Randomize/rotate engine execution order to reduce order effects.
5. Run correctness verification first. Then run repeated independent trials with a documented warmup and steady-state window. Record all trials, sample counts, variability and confidence intervals (or clearly stated dispersion), not just best-case numbers.
6. Use monotonic clocks for latency; measure process and host resources with comparable OS-level tooling. Report JVM heap/GC separately from RSS; do not equate Java heap to Rust process memory. Include indexing durability semantics when comparing throughput.
7. Record failure modes, timeout policies, workload exclusions, query errors, and environmental deviations. Never silently discard failed or slow trials.
8. Store machine-readable results (e.g., JSON with schema version) and a human-readable summary with exact reproduction commands. Keep large datasets and generated indexes outside Git; retain manifests and checksums.

## Correctness gate

Before a workload qualifies for cross-engine performance reporting:
- Confirm equivalent indexed content and analyzer token streams (or explicitly mark the comparison non-equivalent).
- Validate document hit sets and deterministic ordering/tie-breaking where specified; apply documented floating-point tolerance to scores.
- Verify query operator semantics, especially phrase positions, glob/regex whole-term behavior and expansion limits.
- Validate committed-generation visibility, update/delete behavior, and reader consistency independently for Quervant.
- Report any semantic mismatch as a failure or exclusion, **not** as a performance win.

## Acceptance and delivery

**v0.1 required:** runnable Quervant/Tantivy/Lucene local benchmark adapters; versioned corpus/workload manifests; correctness gates; repeatable indexing and representative lexical query measurements; documented machine/environment and raw result artifacts; Quervant RustFS cold/warm cache and fault-injection suite; instrumentation overhead comparison. Implement in dependency order as engine capabilities become available, with early harness scaffolding before search performance optimization. PR 7 Amendment 04 provides the Linux/WSL2 Criterion microbenchmark and profiling baseline described above; PR 15 owns release comparative qualification.

**Later:** larger real-world corpora, detailed microarchitectural profiling, additional providers, partial caching, predictive prefetch, advanced posting codecs and optimization experiments. v0.2 adds distributed fan-out, shard placement/rebalancing and network/failure benchmarks, reported separately from v0.1 local-engine comparisons.

Do not turn relative performance to Lucene or Tantivy into an unconditional release gate; correctness, reproducibility and transparent methodology are mandatory.
