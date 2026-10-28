# PR 15B bottleneck dossier and candidate list for PR 15C

**Criterion source lock:** `e8ca1b03420e1ffe8cb19fafac06b2fe8082866b`
**Profiling amendment base:** `5668d6ef285fdff72b01072327f46a449ed104f2`
**Workload:** `pr15b_v1` (30 required Criterion lanes)
**Qualified Criterion trials:** 3, clean tree, idle-attested, contention `clear`
**Criterion artifacts:** `benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json/.md`
and the three trial manifests.
**Profiling evidence:** ignored `target/pr15b/profiles/`; concise source-locked
summary in `benchmarks/reports/pr15b-profiling-e8ca1b0.json`; details in
`profile-attempts.md`.

**This is not an optimization authorization.** Every candidate remains a
measurement-backed opportunity for a separately approved PR 15C plan. No
production search code, budget, result or format was changed.

## Evidence quality

- Criterion 0.7: `sample_size=20`, 3 s warmup, ≥5 s measurement; slow lanes
  legitimately extended measurement time. Trial-to-trial median dispersion
  across all 30 lanes: **1.005–1.092**.
- CPU: `perf version 6.8.12` (installed version-specific binary; the
  `/usr/bin/perf` distro wrapper cannot find tools for the WSL 6.18 kernel).
  `perf record -g --call-graph dwarf`, 20-second bounded loop, ~80K samples per
  workload. Self percentages are from `perf report --no-children`; inclusive
  percentages are from the default call-tree report and vary by branch.
- Allocation: `heaptrack 1.5.0`, same 20-second bounded loop.
  `heaptrack_print -p -a -T` produced peak, allocator, temporary-allocation and
  histogram data. Total allocated bytes are the histogram sum; they are
  **cumulative allocation traffic, not retained memory**.
- All profiled workloads use **10K documents / 4 segments**. There is no
  approved profiling entrypoint for 100K or for the `medium`/`common` lexical
  workload. The original Criterion 100K numbers remain the only 100K evidence.
- `absent` was profiled twice: SHA-256 self cost **82.75%** and **82.83%**,
  confirming stable sampling. The other workloads were profiled once.
- The generic perf binary does not match the running kernel; usable samples were
  verified, but this is a reproducibility caveat.
- Criterion estimates are microbenchmark iteration distributions, not production
  p99 or a QPS SLA. Absolute values are host-specific.

## Criterion baseline (unchanged)

| Lane | Median of three trial medians | Interpretation |
|---|---:|---|
| U01 absent 2K/10K/100K | 5.120 / 24.842 / 244.241 ms | near-linear with N |
| U02 rare 2K/10K/100K | 7.030 / 34.477 / 342.473 ms | near-linear with N |
| U03 gamma 2K/10K/100K | 9.391 / 38.972 / 711.998 ms | superlinear at 100K |
| U04 mixed 2K/10K/100K | 7.675 / 39.734 / 781.348 ms | superlinear at 100K |
| U05 CIDR+time 10K | 36.263 ms | +5.2% vs rare |
| U06 JSON scalar 10K | 40.652 ms | +17.9% vs rare |
| U07 sort K=10/100/1000 | 36.536 / 39.108 / 70.878 ms | K=1000 costs +81% |
| U08 Source / Fields(host,n) | 39.050 / 39.088 ms | no measurable difference |
| U09 group host 10K | 46.933 ms | +20.0% vs sort K=100 |
| U10 serial batch | 121.843 ms | 0.991× the sum of standalone slots |
| U11 rare S=1/4/16 | 60.300 / 34.149 / 30.123 ms | more segments is faster |
| U11 mixed S=1/4/16 | 79.189 / 41.954 / 31.379 ms | more segments is faster |
| U12 page 1 / page 2 | 39.292 / 39.202 ms | no page-2 penalty |
| U13 geo 8-point corpus | 0.054 ms | separate corpus; not comparable |

## New profiling evidence

### CPU: every query re-opens and re-verifies every segment

Self CPU percentages (10K/4; `perf report --no-children`):

| Workload | SHA-256 envelope | Next largest self costs |
|---|---:|---|
| `absent` | **82.75%** | ByteReader::varint 2.36%, SegmentError drop glue 1.96%, JSON path decode 2.43%, malloc/cfree 1.58% |
| `rare` | **74.30%** | SegmentError drop glue 2.55%, ByteReader::varint 2.41%, JSON path decode 2.28%, malloc/cfree 1.92% |
| `mixed` | **64.73%** | `evaluate_unified` **8.53%**, ByteReader::varint 2.68%, SegmentError drop glue 2.30%, JSON path decode 1.97% |
| `sort` | **64.92%** | SegmentError drop glue 2.29%, ByteReader::varint 2.13%, `MixedEntry` heap **1.84%**, `sort_tuple_for_doc` **0.75%**, BTreeMap 0.85% |
| `aggregation` | **55.53%** | SegmentError drop glue 2.79%, malloc/cfree 3.98%, `visit_aggregate` **1.95%**, `ColumnReader::span_of` **1.30%**, ByteReader::varint/u64 2.98% |

Representative inclusive path:

```text
ReaderSnapshot::open_segment_reader  (index/snapshot.rs:455)
  -> SegmentReader::open             (segment/reader.rs:54/61)
     -> parse_container              (segment/format.rs:734)
        -> sha256(&bytes[..trailer_offset])  (segment/format.rs:842)
```

| Workload | `open_segment_reader` | `parse_container` | envelope `sha256` | JSON path directory |
|---|---:|---:|---:|---:|
| `absent` | 96.37% | 81.93% | 81.87% | 11.57% |
| `rare` | 69.28% | 58.70% | 58.64% | 8.47% |
| `mixed` | 59.95% | 50.96% | 50.92% | 7.23% |
| `sort` | 60.52% | 51.22% | 51.15% | 7.36% |
| `aggregation` | 50.97% | 43.84% | 43.78% | 6.22% |

The inclusive values vary by branch; the flat self table is the primary
quantity. The direct source evidence is unambiguous: `parse_container` computes
SHA-256 over the entire segment envelope on every open, and
`open_segment_reader` clones the full segment byte vector before parsing. This
is the dominant measured explanation for why zero-hit and one-hit queries scale
with corpus size.

### Allocation: segment re-open/re-decode dominates repeated allocations

| Workload | Iterations in 20 s | Total allocations | Temporary allocations | Total allocated bytes* | Peak live heap | Peak RSS | Leaked |
|---|---:|---:|---:|---:|---:|---:|---:|
| `absent` | 399 | 21,728,612 | 10,111,909 | ~2.07 GiB | 16.03 MiB | 29.82 MiB | 544 B |
| `rare` | 252 | 23,787,507 | 8,098,161 | ~2.04 GiB | 16.03 MiB | 29.86 MiB | 544 B |
| `mixed` | 208 | 25,634,579 | 9,497,813 | ~2.11 GiB | 16.03 MiB | 29.82 MiB | 544 B |
| `sort` | 192 | 26,861,922 | 8,272,137 | ~1.94 GiB | 16.03 MiB | 29.88 MiB | 544 B |
| `aggregation` | 97 | 26,588,172 | 4,458,931 | ~1.87 GiB | 16.03 MiB | 29.95 MiB | 544 B |

\* Sum of `size × count` from the heaptrack histogram. **Not retained memory.**
Peak live heap is constant at 16.03 MiB across workloads and is dominated by the
resident immutable corpus/index, not by query temporaries. The 544 B leak is one
allocation and is not on the search path.

Dominant repeated allocation call sites (whole 20 s process; the query loop
dominates):

| Workload | Site | Count | Approx/query | Peak | Interpretation |
|---|---|---:|---:|---:|---|
| all | `segment/json_paths.rs:1099` + `segment/reader.rs:163` | 2.3M–9.5M each | ~23,750 | 0 B | JSON-path directory rebuilt per segment open |
| `absent` | `search/execute.rs:1899` live `BTreeSet` | 331,968 | ~832 | 0 B | per-segment live-set materialization |
| `absent` | `segment/format.rs:885` eager `format!` in `ok_or` | 15,960 | ~40 | 0 B | error string built on every section iteration, then discarded |
| `rare` | `segment/value.rs:395` | 1,102,500 | ~4,375 | 0 B | typed document value decoding |
| `mixed` | `segment/reader.rs:626` `DocumentKey::new` | 1,040,000 | ~5,000 | 0 B | key materialization |
| `mixed` | `search/projection.rs:130` field clone | 104,000 | ~500 | 0 B | projection of selected hits |
| `sort` | `search/unified.rs:710/714` key + sort tuple | 1,920,000 each | ~10,000 | 0 B | sorting materialization |
| `sort` | `segment/reader.rs:626` `DocumentKey::new` | 1,920,000 | ~10,000 | 0 B | key materialization |
| `aggregation` | `search/typed.rs:2393/2476`, `analytics.rs:885`, `contract/document.rs:100` | ~970,000 each | ~10,000 | 0 B | group/metric staging per document |
| `aggregation` | `segment/format.rs:255`, `contract/value.rs:286` | 970,000 each | ~10,000 | 0 B | typed value decoding |

## What the new evidence confirms, weakens or fails to resolve

| Prior dossier claim | New status |
|---|---|
| Full-corpus work for absent/rare | **CONFIRMED / MEASURED** as per-query segment open + envelope SHA-256 + JSON-path re-decode. The earlier "generic full-corpus scan / typed scan" wording was too broad; the measured dominant cause is segment integrity/parse work. |
| Segment topology inversion (S=1 slower than S=16) | **SUPPORTED HYPOTHESIS**, not isolated. The measured segment-open work is consistent with a layout/decode effect, but no approved profiling entrypoint covers S=1/S=16. |
| Superlinear 100K lexical (U03) | **HYPOTHESIS / INSUFFICIENT EVIDENCE**. No 100K or `medium` profiling entrypoint exists. The 10K `mixed` profile shows 64.73% SHA-256 and 8.53% `evaluate_unified`; the 100K extra cannot be attributed to scoring without a 100K profile. |
| Top-K materialization cost | Criterion contribution **MEASURED**; CPU root cause **SUPPORTED HYPOTHESIS**. `sort` (K=100) shows `MixedEntry` 1.84% self / 6.10% inclusive and `sort_tuple_for_doc` 0.75% self / 2.53% inclusive. K=1000 is not separately profiled. |
| Aggregation group-state cost | Criterion contribution **MEASURED**; CPU root cause **SUPPORTED HYPOTHESIS**. `visit_aggregate` 1.95% self (17.55% inclusive in its aggregation branch), column readers ~3%, and per-document staging allocations are visible; SHA-256 still dominates. |
| JSON scalar path overhead | Criterion contribution **MEASURED**; CPU/allocation **UNAVAILABLE** (not profiled; not in the priority table). |
| Serial batch has no redundant-work savings | Criterion effect **MEASURED**; CPU/allocation **UNAVAILABLE** (not profiled). The `mixed` self cost of `evaluate_unified` (8.53%) is the only related CPU evidence. |
| Projection width negligible | **INSUFFICIENT EVIDENCE**; `projection.rs:130` shows 104K/96K clones in mixed/sort, but no CPU hotspot and no significant Criterion difference. |
| Pinned page 2 no penalty | **MEASURED**, no action. |
| Geo | **INSUFFICIENT EVIDENCE**, separate corpus; not profiled. |

## Ranked PR 15C candidates

### 1. Per-query segment re-open, envelope re-verification and JSON-path re-decode — `MEASURED`

**Original Criterion evidence.** U01 absent 2K→10K→100K: 5.120→24.842→244.241 ms
(4.85×, 9.83×). U02 rare: 7.030→34.477→342.473 ms (4.90×, 9.93×). U11 rare
S=1/4/16: 60.300/34.149/30.123 ms; mixed: 79.189/41.954/31.379 ms.

**New CPU evidence.** SHA-256 envelope verification is **82.75%** (absent),
**74.30%** (rare), **64.73%** (mixed), **64.92%** (sort), **55.53%**
(aggregation) of self CPU samples at 10K/4. Inclusive path:
`open_segment_reader → SegmentReader::open → parse_container → sha256`. Source:
`segment/format.rs:842`; full-byte clone at `index/snapshot.rs:455`.

**New allocation evidence.** The JSON-path directory and `SegmentReader::open`
dominate repeated allocation counts: ~23,750 allocations/query in each workload,
plus ~2.0 GiB cumulative allocation traffic per 20 s and a constant 16.03 MiB
peak live heap. `parse_container` also eagerly formats an error string at
`segment/format.rs:885` on every section iteration (15,960 allocations/run at
10K/4), and `execute.rs:1899` materializes a per-segment live `BTreeSet`
(331,968 allocations in the absent run).

**Root-cause confidence.** `MEASURED` for the dominant cost. The exact fraction
of wall time recoverable by caching/avoiding re-verification is not measured; a
PR15C prototype and before/after trials are required.

**Proposed investigation / optimization boundary.** Investigate caching a
verified, parsed immutable segment reader (or at least a verified parse token)
per snapshot, avoiding the full-byte clone, and decoding the JSON-path directory
once per immutable segment. Preserve the existing integrity guarantee: the
ObjectStore/local bytes must still be verified at the defined trust boundary.
Do not weaken SHA-256 verification of untrusted or newly materialized bytes.

**Correctness risks.** High: integrity verification semantics, snapshot/PIT
lifetime and pinning, cache invalidation across generations, memory growth,
thread-safety, error identity, and merge/reopen behavior. Any change must keep
the existing segment format and public contracts unchanged.

**Estimated performance opportunity.** The CPU share is large but **no speedup
percentage is claimed**. A PR15C prototype must measure wall time, allocations,
peak memory and cache overhead on 2K/10K/100K and S=1/4/16.

**Outstanding evidence.** A 100K profiling entrypoint; topology-specific profiles
(S=1/4/16); cache memory/retention measurement; confirmation that a single
verification per snapshot preserves the intended security boundary.

### 2. Superlinear 100K lexical top-K — `HYPOTHESIS` / `INSUFFICIENT EVIDENCE`

**Original Criterion evidence.** U03 10K→100K: 38.972→711.998 ms (18.27× for
10× N); U04: 39.734→781.348 ms (19.66×). Absent/rare scale ~9.8–9.9×.

**New CPU evidence.** `NOT PROFILED — NO APPROVED ENTRYPOINT`. The approved driver
has no `medium`/`common` workload and always builds 10K/4. At 10K, `mixed`
shows 64.73% SHA-256 self and only 8.53% `evaluate_unified`; this does not
explain the 100K slope.

**New allocation evidence.** `UNAVAILABLE` for the 100K lane. At 10K mixed, the
query-specific allocation sites are much smaller than segment-open allocations
(`DocumentKey::new` ~5,000/query, projection clones ~500/query).

**Root-cause confidence.** `HYPOTHESIS`. The prior candidate is **weakened** as a
standalone explanation because a large per-query segment-open/hash cost exists at
every N; the 100K residual may be scoring, decode, or both.

**Proposed investigation boundary.** Add an approved 100K profiling entrypoint
for the U03/U04 requests (separate design approval) and capture CPU/allocation
profiles before considering any scoring/top-K change.

**Correctness risks.** High: exact score/rank equivalence and deterministic
tie-breaking. The scaling corpus does not independently score top-100 order.

**Estimated opportunity.** Not defensible without a 100K profile.

**Outstanding evidence.** 100K CPU and allocation profiles; independent ranking
oracle for the scaling corpus.

### 3. Top-K materialization above K=100 — `MEASURED` contribution, `SUPPORTED HYPOTHESIS` cause

**Original Criterion evidence.** U07 K=10/100/1000: 36.536/39.108/70.878 ms;
K=1000 is +81.2% over K=100.

**New CPU evidence.** `sort` (K=100): `MixedEntry` 1.84% self / 6.10% inclusive,
`sort_tuple_for_doc` 0.75% self / 2.53% inclusive, BTreeMap 0.85% self.
SHA-256 remains 64.92% self.

**New allocation evidence.** `unified.rs:710/714` key + sort tuple: 1,920,000
each (~10,000/query); `reader.rs:626` `DocumentKey::new`: 1,920,000
(~10,000/query). Projection clones: 96,000 in the sort run.

**Root-cause confidence.** Contribution `MEASURED`; K=1000 increment is
`SUPPORTED HYPOTHESIS` because no approved K=1000 profiling lane exists.

**Proposed investigation boundary.** Bounded heap/partial selection and fewer
per-hit allocations for large K, preserving exact ordering and cursor
continuation.

**Correctness risks.** Medium: deterministic tie-break, sort tuple equivalence,
cursor/PIT continuation.

**Estimated opportunity.** K=1000 is +81.2% over K=100 in Criterion; no claim
that removing the measured sort allocations recovers that full difference.

**Outstanding evidence.** K=1000 profiling lane; allocator attribution at K=1000;
before/after ordering oracle.

### 4. Aggregation group-state and per-document staging — `MEASURED` contribution, `SUPPORTED HYPOTHESIS` cause

**Original Criterion evidence.** U09 46.933 ms vs U07 K=100 39.108 ms (+20.0%).

**New CPU evidence.** `visit_aggregate` 1.95% self (17.55% inclusive in its
aggregation branch), `ColumnReader::span_of` 1.30% self, `ColumnReader::value`
0.62% self. SHA-256 remains 55.53% self.

**New allocation evidence.** `typed.rs:2393/2476`, `analytics.rs:885` and
`contract/document.rs:100` show ~970,000 allocations each (~10,000/query) in the
97-iteration aggregation run; `segment/format.rs:255` and
`contract/value.rs:286` show the same order.

**Root-cause confidence.** Contribution `MEASURED`; exact per-group cost is
`SUPPORTED HYPOTHESIS` because the batch/aggregation path includes multiple
stages and the profile is not isolated to one group operation.

**Proposed investigation boundary.** Reduce per-document group/metric staging
allocations and column read overhead while preserving exact group order, sums,
missing/null semantics and distinct counts.

**Correctness risks.** Medium-high: checked arithmetic, ordering, missing/null,
distinct/frequency semantics.

**Estimated opportunity.** Not quantified beyond the Criterion +20% and the
measured self/inclusive shares.

**Outstanding evidence.** Isolated aggregation profile with group-count scaling;
allocator attribution per group operation.

### 5. JSON scalar path overhead — `MEASURED` Criterion contribution, CPU `UNAVAILABLE`

**Original Criterion evidence.** U06 40.652 ms vs U02 34.477 ms (+17.9%).

**New CPU/allocation evidence.** `UNAVAILABLE` — `json` is a supported driver
workload but was outside the priority table for this amendment.

**Root-cause confidence.** `HYPOTHESIS`.

**Proposed investigation boundary.** Profile the approved `json` workload before
considering any JSON path/derived-representation change.

**Correctness risks.** High: JSON missing/null/empty and path semantics.

**Outstanding evidence.** `json` CPU and allocation profiles.

### 6. Serial batch cross-slot reuse — `MEASURED` neutral, CPU `UNAVAILABLE`

**Original Criterion evidence.** U10 121.843 ms vs 122.930 ms standalone sum
(0.991×): no batching overhead, but no shared-work benefit.

**New CPU/allocation evidence.** `UNAVAILABLE` for the `batch` workload. The
`mixed` profile shows `evaluate_unified` 8.53% self, which is the only related
CPU evidence.

**Root-cause confidence.** Neutral effect `MEASURED`; opportunity `HYPOTHESIS`.

**Proposed investigation boundary.** A separately approved design for shared
predicate/scan evaluation across slots, preserving per-slot isolation, budgets
and failure semantics.

**Correctness risks.** High: per-slot isolation, budget accounting, failure
isolation.

**Outstanding evidence.** `batch` CPU/allocation profile; per-slot work counts.

### 7. Eager error-string formatting in `parse_container` — `MEASURED` allocation inefficiency

**Original Criterion evidence.** No isolated Criterion lane; this is a
per-segment-open allocation observed inside the absent/rare/mixed/sort/aggregation
profiles.

**New allocation evidence.** `segment/format.rs:885` formats
`"unknown kind 0x{raw_kind:04x}"` inside `ok_or` on every section iteration:
15,960 allocations in the absent 399-iteration run (~40/query; 100% temporary).
The string is discarded when the section kind is valid.

**Root-cause confidence.** `MEASURED` allocation count; the wall-time share is
below the 1% self-CPU cutoff and is not claimed.

**Proposed investigation boundary.** Use lazy error construction (`ok_or_else`)
so the message is built only on the error path; no format or semantic change.

**Correctness risks.** Very low: error type/message must remain identical when
a failure actually occurs.

**Estimated opportunity.** Small CPU/wall-time impact; reduces allocation count
by ~40/query at 10K/4. It is a low-risk cleanup candidate, not a primary
performance lever.

**Outstanding evidence.** A before/after allocation count on the same profile.

### 8. Projection width at K=100 — `INSUFFICIENT EVIDENCE`

Original U08 Source/Fields difference 39.050/39.088 ms (1.001×). New allocation
sites show `projection.rs:130` clones (104,000 in mixed, 96,000 in sort) but no
CPU hotspot. No projection optimization is justified at this width/K.

### 9. Pinned page 2 — `MEASURED` no action

U12 page 1/page 2: 39.292/39.202 ms (0.998×). No page-2 penalty. Not profiled.

### 10. Geo — `INSUFFICIENT EVIDENCE`

U13 0.054 ms on the separate 8-point corpus. Not a scaling measurement and not
profiled.

## Recommended PR 15C ordering (candidate only)

1. Per-query segment re-open/re-verify/re-decode (largest measured CPU and
   allocation root cause; highest correctness risk).
2. Superlinear 100K lexical (largest absolute lane; needs a 100K profile first).
3. Top-K materialization (clear K=1000 Criterion contribution; needs a K=1000
   profile).
4. Aggregation staging (measured contribution; needs an isolated profile).
5. JSON path (needs a profile).
6. Cross-slot batch reuse (largest design change; lowest readiness).
7. Eager error-string allocation (small, low-risk allocation cleanup).

No item becomes `OPTIMIZE` without a separate maintainer decision and a new
approved PR 15C plan.
