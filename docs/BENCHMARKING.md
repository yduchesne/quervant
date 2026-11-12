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

## PR 15G-D isolated D2 A/X campaign

A second measurement-only campaign isolated D2 on A without D1 (A=`ca065a2`, X=`53e41df`) using the fixed 4×4 mirrored schedule, nine frozen PR15D lanes, 5 warmups + 20 samples, independent oracle and 32 real contention probes. The full 16-slot acquisition completed and 2,880 samples validated, but A's 100K rare lane crossed the predeclared 1.25 drift cap (`1.2994`). Per protocol the campaign is **MEASUREMENT_BLOCKED**, not a performance pass or fail; no selective retry was run. Shared production source remains unchanged. Report: `docs/pr-artifacts/pr-15g-d/d2-isolation/performance-blocked.md`.

## PR 15G-D isolated D2 qualified campaign

The corrected A/X controller ran one fresh 16-slot campaign with the frozen 4×4 mirrored schedule. All 2,880 samples, 144 oracle checks, 32 contention probes and both-arm drift checks qualified; the raw v2 seal contains exactly 18 files and `--verify-only` reproduced the reports byte-for-byte. Performance gates then **rejected D2-only**: 100K common/K10 was inconclusive (DX-P01) and 10K rare was `A_FASTER` (DX-P02). Production search was restored byte-for-byte to A. Report: `docs/pr-artifacts/pr-15g-d/d2-isolation/fixup-campaign.md`.

## PR 15G-E persistent-offset format campaign

A format-aware A/E campaign compared accepted A+B (segment v1.0) with an E candidate (segment-only v1.1 persistent STORED/DOC_KEYS offset directories). All 16 slots, 2,880 samples, 144 oracle checks, 32 contention probes and both-arm drift checks qualified; the arms intentionally had different encoded bytes. E was **performance-rejected**: both rare lanes were `A_FASTER` (100K rare approximately 6.4–6.9× slower) and several common lanes also regressed. Production emission and the fast path were rolled back to exact A+B. Evidence: `docs/pr-artifacts/pr-15g-e/`.

## PR 15H-A linear single-term candidate staging campaign

A Quervant-only campaign compared the pinned baseline with a candidate that replaced the eligible single-term branch's per-match `BTreeSet`/`BTreeMap` materialization with linear staging vectors. It timed exactly seven frozen warm lanes on one host: 100K medium/common (P1–P3) and 10K/100K common/rare/absent guards (G1–G4). A sealed pre-optimization baseline (three trials × 20 samples) was acquired before any production edit, followed by four mirrored `A,B`/`B,A`/`B,A`/`A,B` blocks: 8 slots, 56 lane records, 1,120 timed samples, 280 warmups, 16 clear contention probes and 56 independent oracle validations. All qualification and drift gates passed. 100K common K100/K10 improved (`B_FASTER`) and 100K medium was not slower, but every low-hit guard regressed (`A_FASTER`): 100K rare ~1.70×, 100K absent ~1.75× and 10K rare ~1.25× in the frozen B/A ratio terms. HA-P04 therefore failed and the optimization was **performance-rejected**; production search was restored byte-for-byte to the pinned baseline while the benchmark controller, tests and sealed raw evidence were preserved. Report: `docs/pr-artifacts/pr-15h-a/`.

## PR 15H-A2 cardinality-gated linear campaign

A second Quervant-only campaign tested the hypothesis that a fixed 8,192-posting
gate would keep the high-cardinality gains of PR 15H-A while avoiding its sparse
regressions: below the gate the exact accepted eligible branch runs, at or above
it the historical linear helper runs. The same seven frozen warm lanes, sealed
pre-optimization baseline and four mirrored blocks were used: 8 slots, 56 lane
records, 1,120 timed samples, 280 warmups, 16 clear probes, 56 oracle validations
and no drift breach. Both 100K common lanes were `B_FASTER` and 100K medium was
not slower, but the below-gate low-hit guards were still `A_FASTER`: 100K absent
~1.63–1.80×, 100K rare ~1.66–1.98× and 10K rare ~1.27–1.50×. HA2-P04 therefore
failed and the candidate was **performance-rejected**; production search was
restored byte-for-byte to the A2 base. A bounded diagnostic reproduced the sparse
regression on the same artifacts without asserting a cause. Report:
`docs/pr-artifacts/pr-15h-a2/`.

## PR 15H-A3 sparse-regression diagnostic

A diagnostic-only investigation tested whether the rejected A2 sparse-lane
regression is attributable to source, codegen or measurement. It added a locked
four-lane Quervant-only controller (S1 100K absent, S2 100K rare, S3 10K rare,
C1 100K common) with a sealed A/A environment control, an A/B reproduction stage
and conditional single-edit V2/V3 interventions. The A/A control failed its
frozen 1.15/1.20 caps even though both arms were byte-identical builds of the
same source (100K absent ratios 1.277/1.370, 100K rare 1.074/1.226, 100K common
1.134/1.155). The campaign is therefore `MEASUREMENT_BLOCKED_AA_CONTROL`; A/B and
V2/V3 were not run. Untimed source inspection found no extra sparse loop,
allocation, decoder or callback below the 8,192 gate, while the release binary
does contain the gate, the helper call and a larger `evaluate_lexical_with`.
`perf` was unavailable for the running kernel. No cause is asserted and no
production change is retained. Report: `docs/pr-artifacts/pr-15h-a3/`.

## PR 15H-B borrowed keyword sort materialization

A Quervant-only six-lane campaign measured a narrow optimization for the
existing single-term, single-valued-columnar-Keyword, standalone sort shape:
noncompetitive candidates validate a borrowed `&str` view of the immutable COLUMN
value, compare it with the heap's worst owned sort value, and skip the owned
`String`/`SortValue` tuple. The sealed pre-optimization baseline (3 trials) and
the four mirrored paired blocks (8 slots, 48 lane records, 960 samples, 240
warmups, 16 clear probes, 48 oracle validations) used the frozen PR15D adapter,
corpus and oracle; index digests were byte-identical between arms. Paired
`A − B` differences in milliseconds: 100K common/K100 median **+6.266 ms**, 100K
common/K10 median **+12.213 ms**, 100K medium/K100 **+0.543 ms**, 10K common/K100
**+0.536 ms**, 100K rare **−0.008 ms**, 100K absent **−0.025 ms**. All absolute
gates passed (`PERFORMANCE_ACCEPTED` locally). Evidence:
`docs/pr-artifacts/pr-15h-b/`.

## PR 15H-C borrowed document-key diagnostic

A six-lane Quervant-only follow-up to 15H-B reused the validated per-segment
`DOC_KEYS` cache to borrow document keys for losing single-term keyword-sort
candidates. The sealed four-block campaign was qualified but slower on both 100K
common primaries (P1 median −4.273 ms, P2 −0.954 ms) and medium (−4.067 ms);
the 10K/rare/absent guards passed. The candidate was **performance-rejected** and
`search/unified.rs` was restored byte-for-byte to the accepted B-fixup baseline.
Controller and sealed evidence remain under `benchmarks/pr15h_c/` and
`docs/pr-artifacts/pr-15h-c/`.

## PR 15H-D shared binding-resolution diagnostic

A six-lane Quervant-only follow-up tested sharing the already resolved
schema/analyzer bindings and `CodecSchema` between cursor validation and normal
unified compilation. The four-block campaign was qualified but saved only
+0.306 ms (100K common/K100), +0.298 ms (K10) and +0.866 ms (medium) conventional
medians, below the required +2 ms for two of three primaries; guards passed. The
candidate was **performance-rejected** and the two production search files were
restored byte-for-byte. Evidence: `docs/pr-artifacts/pr-15h-d/` (closeout: `closeout.md`, corrected derived summary: `derived-summary.md`).

## PR 15H-E compact dictionary size campaign

A format campaign tested feature-gated dictionary v2 metadata (canonical LEB128
`doc_freq`/`postings_offset`/`postings_length`, required feature `(0x000C,1)`).
Nine frozen lanes, 16 balanced warm slots, cold-open and build+commit blocks were
sealed. The dictionary shrank ~54% (100K E/A 0.4623) and all correctness and
latency gates passed, but the overall storage gates failed: 100K segment 0.9119
(limit 0.90, E-P03) and 100K committed index 0.9392 (limit 0.92, E-P04). The
candidate was **storage-rejected** and production source was restored byte-for-byte
to the pre-E baseline; tooling, helper tests and sealed evidence remain. Evidence:
`docs/pr-artifacts/pr-15h-e/` (`decision.md`, `storage.md`, `latency.md`, `rollback.md`).

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

## PR 15I-A compact mutation-state qualification

PR 15I-A replaces the repeated per-live-row segment-ID string and fixed `u64`
physical document ID in the mutation-state sidecar with a sorted per-sidecar
segment-ID table plus canonical varint ordinal/doc-ID pointers (payload version
3, required feature `0x000C/1`). It is a storage experiment only: segments,
search scoring, STORED blocks, the manifest wire version and the
`CURRENT`-last publication protocol are unchanged.

The A-specific paired controller is
[`benchmarks/pr15i_a/README.md`](../benchmarks/pr15i_a/README.md). It reuses the
frozen PR15D 10K/100K corpus and independent oracle, freezes the nine warm lanes
and the `ABBA/BAAB/BAAB/ABBA` schedule in
[`benchmarks/pr15i_a/protocol.json`](../benchmarks/pr15i_a/protocol.json), and
measures exact committed component bytes, fresh-process reopen, build+commit,
kernel peak RSS and real-RustFS cold bootstrap in four balanced blocks. Frozen
thresholds: 100K sidecar `<= 0.75` of A, 100K total committed index `<= 0.95`,
10K sidecar/total `<= 1.02`, reopen median `<= 1.10`, build+commit median
`<= 1.15`, every 100K/10K search lane median `<= 1.10`/`<= 1.15`, peak-RSS
median `<= 1.15` (absolute increase `<= 16 MiB`) and RustFS cold bootstrap
median `<= 1.15`, with the per-block ceilings frozen in the protocol.

No threshold is asserted until a sealed campaign is executed and verified;
`verify.py --verify-only` rehashes the seal and recomputes the gate matrix
without writing evidence. A rejected candidate is preserved as evidence and
rolled back rather than re-tuned.

## PR 15I-B compressed STORED v2 (rejected)

The source-locked LZ4 and Zstd level-1 STORED v2 candidates were measured with
the paired controller in [`benchmarks/pr15i_b/`](../benchmarks/pr15i_b/). Both
reduced the 100K STORED section to 17.2% / 6.5% of baseline and the total index
to 66.3% / 62.0%, but both failed the frozen `B-P06` rare/medium warm-lane gate
(10K rare medians 1.66/1.69). The candidates were rejected and production was
restored; see
[`docs/pr-artifacts/pr-15i-b/codec-selection.md`](pr-artifacts/pr-15i-b/codec-selection.md).
No threshold was relaxed.

The direct-record follow-up removed the 128-record certified hot-path scan and
improved 10K rare from 1.66/1.69 to 1.152/1.158 and 100K rare from 1.17 to
1.04/1.07, but the frozen 10K rare median ceiling of 1.10 still failed for both
codecs. Both were rejected; see
`docs/pr-artifacts/pr-15i-b/direct-record-codec-selection.md`.

PR 15I-B residual R1–R3: the selected-only boundary checks, singleton stack
scratch and one-block result return reduced LZ4 10K rare from 1.152 to 1.0592
and passed all frozen gates; Zstd1 remained ineligible (1.1923). See
`docs/pr-artifacts/pr-15i-b/residual-performance.md`.

## PR 15I-C — rejected physical exact-term executor and closeout

PR 15I-C evaluated a physical single-positive-term postings executor under the
frozen nine-lane PR15D workload. Multiple rejected candidates improved common
queries but regressed absent/rare queries. The final PR 15I-C-F diagnostic had
stable A/A controls and reproduced low-match regressions. Its generic-only arm
G (physical collector compiled but runtime-disabled; generic collector out of
line) failed neutrality on all absent/rare lanes: aggregate G/A 1.4382, 1.3568,
1.7737 and 1.7310, versus the prospective 1.05 aggregate ceiling. The
physical-enabled arm's common-query improvements **are not shipped results**.
`F_RELEASE` was not built; the original frozen feature-acceptance campaign was
not run in the final experiment. The frozen performance contract remains
unchanged. The experimental code was rolled back to the accepted baseline.

See [PR 15I-C final closeout](pr-artifacts/pr-15i-c/closeout.md) for pinned
historical reports, interpretation limits and evidence-retention status.

## PR 15I-D0 source-locked attribution methodology (blocked)

PR 15I-D0 added a diagnostic A/Q/P protocol for source-locked hot-path
attribution: the original Quervant adapter (A), the same instrumented binary with
the recorder inactive (Q), and that exact binary with the recorder active (P),
across two frozen 24-slot campaigns with independent sealing and verification.
The tooling is unit/adversarially tested and the diagnostic source derivative is
byte-reversible to BASE, but the measurement itself is blocked because the frozen
PR 15D Quervant adapter lockfile cannot satisfy `cargo build --locked` at the
pinned BASE. No current cross-engine ratio or stage attribution is published.
See [the D0 execution status](pr-artifacts/pr-15i-d0/execution-status.md) and
[the D0 tooling README](../benchmarks/pr15i_d0/README.md). This section adds no performance SLA and changes
no acceptance threshold.

## PR 15I-D1-F — DOC_KEYS borrowing (REJECTED, rolled back)

PR 15I-D1-F separately evaluated a new C2 that borrowed keys from the existing
snapshot-shared, fully validated DOC_KEYS offset directory and owned a
`DocumentKey` only on top-K admission, built directly on the D0-compatible BASE
(no rejected C1 code). A frozen nine-lane, 16-slot controller
(`benchmarks/pr15i_d1_f`, protocol `pr15i-d1-f-c2-v1`) ran one qualified A/A
control and `c2-base-01`. That campaign was structurally valid but failed the
mandatory `FC2-P01` primary win: 100K common/K100 was slower by 841,226 ns and
100K common/K10 improved by 1,570,665 ns (below the +2,000,000 ns threshold);
100K medium/K100 improved by 3,397,628 ns and all guards passed. Per the
predeclared contract the change was rejected (`D1F_C2_PERFORMANCE_REJECTED_ROLLED_BACK`),
production was restored to exact BASE bytes, `c2-base-02` was not run, and the
historical C1 rejection remains unchanged. Evidence and the postmortem are in
[`docs/pr-artifacts/pr-15i-d1-f/`](pr-artifacts/pr-15i-d1-f/execution-status.md).

## PR 15I-D2-A — scoring-cost qualification (measurement only)

PR 15I-D2-A added a source-locked A/Q/P diagnostic derivative on the merged
post-D1 BASE `9429dce`, three nested score subspans (`score_map_ns`,
`score_owner_ns`, `score_accumulate_ns`) inside the inherited D0
`score_vector_ns`, and six checked counters. One A/A control and two independent
24-slot A/Q/P campaigns ran with nine frozen lanes, exact oracle checks, byte
identical A/QP indexes, independent sealing/verification and 128 clear
contention probes. The independent aggregate verdict is
**`D2A_SCORE_COST_LOW_PRIORITY`**: only 100K common/K10 crossed both the
2,000,000 ns and 8%-of-engine priority thresholds in both campaigns; 100K
common/K100 (≈6.5% share) and medium/K100 (≈4.0% share) did not. No production
score, executor, adapter, corpus, threshold or format changed, and D2-B is not
authorized. See
[the performance qualification](pr-artifacts/pr-15i-d2a/performance-qualification.md)
and [evidence index](pr-artifacts/pr-15i-d2a/evidence-index.md).

## PR 15I-D3-A — candidate/intermediate attribution (measurement only, BLOCKED)

PR 15I-D3-A added a source-locked A/Q/P diagnostic derivative on the merged
post-D2-A BASE `409fb0f`, extending the inherited D2-A stages with complete
intermediate-materialization intervals (`matched_reserve_ns`,
`scored_vec_build_ns`, `temp_release_ns`), a sparse match-insert sample and
bounded deterministic candidate micro-samples. The recorder schema is fixed at
25 stages, 15 counters, up to 32 segment descriptors and two FIRST/STEADY
strata. Tooling, protocol, source proof and 56 targeted Python tests are frozen
at T0b `fd21658`; the derivative fingerprint is
`62e587715a9a2dd24281a99f9e05e378683dda4e82d9eac0837a4a140801fb60`.

The T0b A/A control did **not** qualify: the first complete control and the one
permitted DXA-17 retry each failed one frozen per-block `[0.80, 1.25]` ratio in
a low-hit 10K lane. All other blocks, the lower-median gate and the hard
`[0.67, 1.50]` bound passed, but a second complete control failure is a HARD
STOP. No paired campaign was run under T0b and no candidate or
intermediate-materialization conclusion is made. The verdict is
**`D3A_MEASUREMENT_BLOCKED`**. No production source, scorer, codec, adapter,
corpus, threshold or format changed. See
[the execution status](pr-artifacts/pr-15i-d3a/execution-status.md) and
[evidence index](pr-artifacts/pr-15i-d3a/evidence-index.md).

### PR 15I-D3-A-F fixup — five-run candidate attribution (measurement only, BLOCKED)

The D3-A-F fixup introduced a prospectively frozen v2 control policy allowing
one soft outlier only in the 10K absent/rare A/A lanes, isolated build
namespaces, sealed host-quiescence evidence and five predeclared paired runs.
The official control qualified (one tolerated 1.250799 soft outlier in 10K
absent). Three paired runs (`d3af-unbatched-01/02/03`) independently qualified;
run 04 failed the unchanged paired A/A stability gate on 10K absent (median
drift 1.3135, 3 outlier blocks) and halted the series under FDX-19. Run 05 was
not executed, no aggregate ranking was produced, and the verdict is
**`D3A_MEASUREMENT_BLOCKED`**. Historical D3-A remains blocked and its report is
unchanged. No production source or optimization changed. See
[the fixup execution status](pr-artifacts/pr-15i-d3a/fixup-f-execution-status.md).

### PR 15I-D3-A-F2 — lane-scoped five-run attribution (measurement only)

The F2 fixup preserved all T0/T0b/T0c evidence and replaced the global paired
timing gate with lane-scoped qualification while keeping every numeric and
global-integrity check unchanged. Five fresh v3 campaigns ran under T0d. The
control qualified; four runs were fully qualified and `d3af2-unbatched-03` was
lane-scoped because `10K rare` had a Q/A median of `1.1838 > 1.15`; that lane
was excluded while the other eight remained eligible. All three 100K primary
lanes have five eligible runs. The independent verifier localized the sampled
`candidate_duplicate` child on `100K medium/K100` and `100K common/K100` across
the same five run IDs: completion `D3AF2_ATTRIBUTION_QUALIFIED`, priority
`D3A_CANDIDATE_HOTSPOT_LOCALIZED`. This is a diagnostic sampled-child finding,
not an approved optimization; no production source changed. See
[the F2 execution status](pr-artifacts/pr-15i-d3a/fixup-f2-execution-status.md).

Independent review closure: a read-only replay harness under
`benchmarks/pr15i_d3a_review/` re-ran the verifier against copied F2 evidence.
Global oracle/form/binary/seal/tooling failures blocked; a single low-hit lane
timing failure remained lane-scoped; 4/5 shared runs localized and 3/5 did not.
Two non-result-changing hardening gaps (duplicate manifest entries and an
altered protocol hash) were confirmed and deferred to a future tooling revision;
actual F2 manifests and protocol hashes are clean. See
[the review closure](pr-artifacts/pr-15i-d3a/fixup-f2-independent-review-closure.md).

### PR 15I-D3-B — retained-key prefilter A/A control (measurement blocked)

The D3-B tooling froze a new nine-lane protocol (`pr15i-d3b-retained-key-prefilter-v1`),
D3B-P01–P08 gates, a provisional tooling inventory and an independent verifier
before timing. Preflight passed and the mandatory same-source A/A control
`d3b-base-aa-01` produced 2,880 timed samples, 720 warmups and 32 clear
contention probes with all nine numerical A/A medians inside `[0.85, 1.15]` and
all drift checks passing. The control was nevertheless structurally invalid:
the two isolated BASE worktrees embedded different absolute source paths and
therefore produced different adapter binaries (`cdc434c8…` vs `d0847853…`); a dry
rebuild of one source path into two target directories was byte-identical. Because the plan requires identical A/A
binaries and DBX-31 stops the series on a structural control failure, no paired
campaign ran and the outcome is `D3B_MEASUREMENT_BLOCKED`. The sealed control is
archived with an independent verifier receipt and SHA-256 sidecar. No
performance claim exists. See
[the A/A control record](pr-artifacts/pr-15i-d3-b/a-a-control.md).

### PR 15I-D3-B-F1 — one canonical compile path (measurement blocked at verification)

The F1 copy of the D3-B controller builds both arms from a single
campaign-local detached worktree (`compile-source`) into independent target
directories, seals build provenance, host filesystem/`findmnt` evidence and
observed per-process CPU affinity, and requires the independent verifier to
rehash the frozen PR15D inputs from immutable Git blobs. The non-timed proof
passed (AA binaries identical; AB binaries distinct) and the official control
produced identical BASE binaries, identical 100K index bytes (`15,747,551`
committed, `1,661,455` STORED) and nine in-bound A/A medians. Independent
verification failed on two frozen-tooling defects — the inventory walk did not
exclude the mandated `compile-source/` worktree, and the sealed host fingerprint
omitted the allowed-CPU set that the verifier recomputed — so no paired
campaign ran, nothing was archived, and the disposition is
`D3BF1_MEASUREMENT_BLOCKED`. A new freeze is required; no threshold was
modified and no performance claim exists. See
[the A/A control record](pr-artifacts/pr-15i-d3-b-f1/a-a-control.md).

### PR 15I-D3-B-F1.1 — fail-closed verifier repair, rehearsal and requalification

The isolated F1.1 tooling fixes the two F1 verifier defects (root-only
`compile-source` inventory exemption; one strict campaign host-fingerprint input
contract with a separate preflight identity), keeps the protocol's six-key delta
and all numeric gates bit-for-bit unchanged, and adds a synthetic full-verifier
rehearsal plus a rehearsal-only publish guard. The rehearsal passed one positive
and fifteen negative/invariance cases through the external verifier with the
original F1 files unchanged. T2 = `63b30a0b…`. The fresh A/A control
independently qualified (2,880 samples, 720 warmups, 32 clear probes, zero
drift, identical 100K indexes). Paired campaign 01 was independently verified but
structurally blocked by a `10K rare` within-block drift of 1.503058 > 1.50, so no
performance verdict is authorized, campaign 02 did not run, and no rollback was
performed. The verified blocked evidence is archived; the diagnostic per-lane
numbers are recorded but cannot be promoted. See
[the performance qualification record](pr-artifacts/pr-15i-d3-b-f1-1/performance-qualification.md).
