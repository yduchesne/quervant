# Benchmarking architecture and methodology

**Status:** v0.1 design and acceptance policy. PR 7 Amendment 04 implements a
Linux/WSL2 Criterion microbenchmark, deterministic correctness-gated fixtures,
CPU/allocation profiling workflows and a reproducible pre-optimization baseline
for `quervant-core`. Cross-engine adapters (Tantivy/Lucene), remote RustFS and
release qualification remain PR 13/PR 15 work.

## Verified reader-state reuse qualification

The permanent [verified immutable segment-state reuse architecture](architecture/VERIFIED_SEGMENT_READER_REUSE.md) governs integrity, caching, snapshot identity and memory admission; this document governs measurement. An implementation must preserve source-locked PR 15B baseline results, compare ≥3 qualified same-host release-mode trials against the optimized executable, and report successful verification/decode counts separately from latency and allocation statistics. Profile-backed PR 15C candidates are historical evidence, not changes to these architectural contracts.

## PR 15G-A retained column geometry measurement

PR 15G-A reuses the frozen PR15D/PR15E-B1 corpus, adapter, oracle and nine warm lanes without modifying them. Its dedicated runner is `benchmarks/pr15g_a/run.py`; protocol and authorization details are in `benchmarks/pr15g_a/README.md`, and results are in `docs/pr-artifacts/pr-15g-a/performance-qualification.md`. Arm A is pinned to merged `main` `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc`; arm B is the distinct committed descendant `9ddff6a79a7a9fa1932c5de7f37065252673397d`. One authorized same-host campaign was executed with three clear contention-qualified trials per arm. P01–P04 passed: 100K absent/K100 and 10K absent/K100 were `B_FASTER`, no other lane was `A_FASTER`, and exact oracle/index/corpus checks matched. The sanitized artifacts are under `target/pr15g-a/qualified-pair-9ddff6a-20261104T0437Z/`. Hosted exact-head CI and independent review remain outstanding.

## PR 15G-B validated STORED/DOC_KEYS offsets measurement

PR 15G-B continues on the shared `dev/pr15g-a-retained-column-geometry` branch; no merge to `main` is required for the B phase baseline. Its runner is `benchmarks/pr15g_b/run.py` and uses the same frozen nine warm lanes, PR15D adapter/oracle and five-warmup/twenty-sample shape. Arm A is the shared-branch pre-B tip `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`; arm B is the committed B candidate `4e7949ad12236a0feeee671c6221119b8a998cc7`. One authorized same-host campaign qualified all six trials with identical corpus/index digests and exact oracle hits. GB-P01–P05 passed: both rare lanes were `B_FASTER` and no lane was `A_FASTER`. Sanitized results are under `target/pr15g-b/qualified-pair-4e7949a-20261104T0648Z/`; the report is `docs/pr-artifacts/pr-15g-b/performance-qualification.md`. Hosted exact-head CI and independent review remain outstanding.

## PR 15G-C fused sorted single-term stream measurement

PR 15G-C continues on the shared `dev/pr15g-a-retained-column-geometry` branch. Its runner is `benchmarks/pr15g_c/run.py`, with arm A pinned to the shared pre-C tip `018fdd768d0898d6709baeb8661998ee1a82947c` and arm B to the measured C candidate `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e`. The authorized same-host nine-lane campaign qualified all trials with identical corpus/index digests and exact oracle hits, but **failed** GC-P01/P02/P04: both 100K common lanes were `A_FASTER`, as were 100K absent/rare and 10K rare. No lanes/samples were excluded or retimed. Raw and sanitized artifacts are under `target/pr15g-c/qualified-pair-5ec886f-20261104T1525Z/`; the failure report is `docs/pr-artifacts/pr-15g-c/performance-qualification.md`. C is not performance-accepted.

## PR 15G-C fixup — rejected two-pass stream and safe rollback

A prescribed two-pass replacement for the failed C four-pass stream was measured against accepted pre-C `018fdd768d0898d6709baeb8661998ee1a82947c` at candidate `0a55119b1d47ab4bbd7d9205ad1d84a636d96c2f`. The authorized same-host nine-lane campaign qualified all trials but failed GF-P01 (100K common/K100 `INCONCLUSIVE`) and GF-P04 (10K/100K absent and rare `A_FASTER`); 100K common/K10 was `B_FASTER` and 100K medium `INCONCLUSIVE`. Per the approved plan, C production search was additively rolled back to the accepted B source while preserving all negative evidence, C integration tests and B carryover tests. Results: `target/pr15g-c/qualified-fixup-pair-0a55119-20261104T1713Z/`; report: `docs/pr-artifacts/pr-15g-c-fixup/performance-qualification.md`; rollback proof: `docs/pr-artifacts/pr-15g-c-fixup/rollback.md`. C is not accepted.

## PR 15G-D compiled exact-term specialization measurement

PR 15G-D ran two independent nine-lane campaigns on the shared optimization branch against D_BASE `ca065a212987284144d8901aa5c54de093d6dbfc`. D1 (`1d2a6b0`) bypasses only per-segment query-time setup for a validated dictionary miss while retaining the exact effective-live work charge; it qualified with 100K absent/K100 `B_FASTER` and no guardrail `A_FASTER`. D2 (`dae5987`, including D1) removes the redundant binary search for postings already decoded by the P4 one-term path; it qualified with 100K medium/K100 and common/K100 both `B_FASTER` and no `A_FASTER` lane. Both campaigns used 3 clear trials/arm, 5 warmups + 20 samples, identical corpus/index digests and exact oracle hits. Results: `target/pr15g-d/d1-1d2a6b0-…` and `target/pr15g-d/d2-dae5987-…`; report: `docs/pr-artifacts/pr-15g-d/`. C remains rejected; no merge or independent review has occurred.

## PR 15G-D three-arm confirmation

A measurement-only three-arm confirmation (`benchmarks/pr15g_d/confirm.py`) remeasured A=`ca065a2`, B=D1=`1d2a6b0`, and C=D1+D2=`dae5987` in the fixed 18-slot mirrored schedule with the frozen nine PR15D lanes, 5 warmups + 20 samples per slot/lane, exact oracle, clear contention probes and predeclared drift checks. The campaign was structurally qualified but returned **NOT_RECONFIRMED**: D1 100K absent/K100 was inconclusive and D1 had 10K guardrail `A_FASTER` lanes; D2 incremental/cumulative high-hit targets reproduced, but guardrail checks also failed. This does not reverse D1/D2 production source or the historical two-arm results. Report: `docs/pr-artifacts/pr-15g-d/confirmation-performance.md`.

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

  The exact-workload PR 15D profile lane lives in
  [`benchmarks/pr15e/`](../benchmarks/pr15e/README.md): its captures wrap the
  unmodified Quervant adapter, are checksummed, are verified fail-closed, and are
  reported separately from the uninstrumented PR 15D-B comparison.

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

## Qualified before/after evidence: PR 7 Amendment 05 (persistent BM25 field norms)

Amendment 05 replaces the per-search corpus-wide statistics scan with persisted
per-document field norms and query-term-only document-frequency retrieval. The
performance objective was verified with a **qualified same-environment pre/post
comparison**:

- Pre-optimization: clean `a8adf37` (via isolated worktree, `git_dirty=false`),
  3/3 trials `qualified`, all contention checks `clear`.
- Post-optimization: clean `eb28f7e` (optimized code plus a test-only runner
  aggregate fix), 3/3 trials `qualified`, all contention checks `clear`.
- Identical guest, CPU, ext4 filesystem, Criterion 0.7.0, fixture metadata
  SHA-256 `09bb8987…` and dataset digest `930cdb59…`; each v2 trial independently
  validated with `validate-report.py`.

Aggregate artifacts: [`benchmarks/reports/pr07-amendment05-before.json`](../benchmarks/reports/pr07-amendment05-before.json),
[`…-after.json`](../benchmarks/reports/pr07-amendment05-after.json) and the
[`comparison`](../benchmarks/reports/pr07-amendment05-comparison.md) with per-workload
median ratios, dispersion, trial hashes and the recorded chronological-order note.

Result: scored lexical search improved **1.68x–2.06x** (e.g. 10K rare 25.25 → 12.45 ms,
100K common 285.59 → 148.78 ms), with `match-all`/`pure-negative`, postings decode,
dictionary lookup and the BM25 equation control all unchanged (±5%). `n`/live-norm
summation remains O(doc_count) per search; no O(1) or zero-allocation claim is made.
Profilers remain UNAVAILABLE. PR 7 remains pending review and merge; PR 15 owns
release comparative qualification.

## Remote RustFS cold/warm lane (PR 13)

A reproducible remote lane exists in addition to the local CPU lanes above:
`crates/quervant-core/tests/pr13_bench_remote.rs` (ignored unless
`QUERVANT_RUSTFS_*` is set), emitting raw CSV under `benchmarks/reports/`. A
large-segment stress mode is selected with `QUERVANT_PR13_STRESS_MIB` (default
16; 64 MiB opt-in) and reports the measured immutable segment size before any
size category. It
performs 3 warm-ups and 20 measured trials per configuration and reports
cold-open/query p50/p95/p99, GET count/bytes, peak retained response bytes and
RSS, with a fixed corpus and digest. Measured results are summarised in
`docs/pr-artifacts/pr-13/benchmark-report.md`. Counters are exposed through
`RemoteIndex::transfer_stats()` / `RemoteIndexWriter::transfer_stats()`
(requests, bytes, retries, whole/ranged, peak retained bytes), and
`TransferConfig::{range_threshold, chunk_size}` deterministically select whole
versus ranged transfer for the same corpus.

Required configurations against the pinned RustFS image
(`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`),
each with a fixed seeded corpus and recorded digest and an identical committed
generation:

1. local `FsDirectory` baseline,
2. cold whole-GET remote bootstrap where the object fits the response ceiling,
3. cold parallel ranged bootstrap,
4. warm query after hydration,
5. concurrent cold readers.

Each configuration must use 3 warm-ups and at least 20 measured runs and report
p50/p95/p99, QPS, CPU, GET count/bytes, retries, peak concurrent HTTP requests,
**peak retained response bytes**, staged disk and cache bytes, published as raw
CSV with the exact reproducible commands. `S3ObjectStore::head()` currently
performs a bounded full GET + hash, so verification traffic must be reported
separately from segment materialization. No performance speedup threshold is
asserted; correctness and hard resource bounds are mandatory.
