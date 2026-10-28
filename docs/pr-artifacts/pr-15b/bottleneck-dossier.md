# PR 15B bottleneck dossier and candidate list for PR 15C

**Source lock:** `e8ca1b03420e1ffe8cb19fafac06b2fe8082866b`
**Workload:** `pr15b_v1` (30 required lanes)
**Qualified trials:** 3, clean tree, idle-attested, contention `clear`
**Artifacts:** `benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json/.md` and the
three trial manifests in `benchmarks/reports/pr15b-v1-e8ca1b0-trial-*.json`.

**This is not an optimization authorization.** Every candidate below is a
measurement-backed opportunity for a separately approved PR 15C plan. No
production search code, budget, result or format was changed.

## Evidence quality

- Criterion 0.7 estimates with `sample_size=20`, 3 s warmup and at least 5 s
  measurement per lane. Slow lanes legitimately extended measurement time.
- Trial-to-trial median dispersion (max/min) across all 30 lanes: **1.005–1.092**.
  No lane is presented as a speedup, regression or statistically significant
  change.
- Criterion estimates are **microbenchmark iteration distributions**, not
  production p99 latency or QPS.
- CPU/allocator attribution is `UNAVAILABLE` (no `perf`, `cargo-flamegraph` or
  `heaptrack`; see `profile-attempts.md`). Work counters beyond
  `selected_hits`/`projection_fields` are `NOT INSTRUMENTED`. Therefore any
  statement about *why* a lane is slow is a `HYPOTHESIS`, not measured CPU
  attribution.
- Absolute values are host-specific (WSL2, i7-10750H, ext4). Compare ratios only
  within this campaign.

## Summary table (median of three trial medians)

| Lane | Median | Interpretation |
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

## Ranked candidates

### 1. Full-corpus work for absent and one-hit predicates — `HYPOTHESIS`

**Evidence.** U01 absent: 2K `5.120 ms` → 10K `24.842 ms` (4.85×) → 100K
`244.241 ms` (9.83× for the next 10×). U02 typed `n=0`: `7.030` → `34.477` →
`342.473 ms` (4.90×, 9.93×). Both queries return 0 and 1 hits respectively, yet
latency tracks corpus size almost linearly. At 100K, an absent term costs
`244 ms` while a `3N/8`-hit gamma query costs `712 ms`.

**Suspected boundary.** Unified executor/plan opening and scanning every
effective-live segment/document even when a lexical term is absent or a typed
predicate is highly selective.

**Expected improvement mechanism.** Prove whether plan compilation, dictionary
absence checks, per-segment column decode or typed scans dominate; then consider
early segment skip/pruning using existing persisted bounds (time/zone maps) or an
early term-dictionary absence path. The existing typed time bounds metadata is a
possible non-semantic skip source; it must be measured, not assumed.

**Correctness risk.** High if pruning metadata is incomplete or approximate: a
false negative changes results. Any skip must retain exact semantics and existing
budget/cancellation behaviour.

**Proposed PR 15C measurement.** Add approved counters for segments opened,
documents examined and dictionary probes (requires a separately approved
instrumentation design), or capture `perf`/flamegraph stacks on U01/U02 at
2K/10K/100K. Accept only a change that preserves U01–U13 oracles and PR15A.

**Confidence.** `HYPOTHESIS`. The scaling is measured; the cause is not.

### 2. Superlinear lexical top-K cost at 100K — `HYPOTHESIS`

**Evidence.** U03 gamma: 10K `38.972 ms` → 100K `711.998 ms` (18.27× for 10× N).
U04 mixed: `39.734` → `781.348 ms` (19.66×). In contrast, absent/rare scale
9.83×/9.93×. U01 100K (`244 ms`) vs U03 100K (`712 ms`) shows that returning
`3N/8` candidates and ranking top-100 adds substantial work beyond the
full-corpus baseline.

**Suspected boundary.** Postings decode, BM25 scoring and relevance top-K
materialization for all `3N/8` / `N/4` candidates before truncation.

**Expected improvement mechanism.** Reduce per-candidate scoring or decode work
for non-competitive documents, or use a bounded top-K strategy that avoids
materializing all candidates. The exact mechanism must be selected only after
counters/profile evidence.

**Correctness risk.** High for score/rank equivalence and deterministic
tie-breaking. The scaling corpus does not independently score the top-100 order,
so PR 15C must add an independent ranking oracle before changing scoring.

**Proposed PR 15C measurement.** Before/after on U03/U04 at 10K/100K with the
same oracle gates; exact score/rank parity on the eight-row PR15A oracle plus a
new independent ranking witness for the scaling corpus.

**Confidence.** `HYPOTHESIS`.

### 3. Non-monotonic segment topology effect at 10K — `MEASURED` effect, `HYPOTHESIS` cause

**Evidence.** U11 rare: S=1 `60.300 ms`, S=4 `34.149 ms`, S=16 `30.123 ms`.
U11 mixed: `79.189` / `41.954` / `31.379 ms`. More immutable segments are
*faster* for the same logical corpus and results, contradicting a naive
"fan-out is expensive" model.

**Suspected boundary.** Per-segment block/column layout and decode/cache
behaviour; a single 10K-document segment may have a less cache-friendly scan than
16 smaller segments.

**Expected improvement mechanism.** Investigate block sizing and columnar scan
layout rather than adding cross-segment parallelism. No mechanism is authorized
without a profile/counter.

**Correctness risk.** Low for layout-only work if the segment codec format and
results are unchanged; any format change is a separate, approved migration.

**Proposed PR 15C measurement.** Repeat U11 with counters for block decodes and
bytes read; capture allocation profiles if a profiler becomes available. Verify
identical results and PR15A compatibility.

**Confidence.** Effect `MEASURED`; cause `HYPOTHESIS`.

### 4. Top-K materialization cost above K=100 — `MEASURED` contribution

**Evidence.** U07: K=10 `36.536 ms`, K=100 `39.108 ms` (+7.0%),
K=1000 `70.878 ms` (+81.2% over K=100) on the same `MatchAll`/`n` ascending
query and corpus.

**Suspected boundary.** Larger retained top-K heap, final selection/sort and
per-hit sort tuple materialization.

**Expected improvement mechanism.** Bounded heap/partial selection and fewer
per-hit allocations for large K, while preserving the contract's deterministic
tie-break.

**Correctness risk.** Medium: exact ordering and cursor continuation must remain
identical.

**Proposed PR 15C measurement.** Before/after U07 at K=10/100/1000 with exact
prefix oracles and cursor/pagination equivalence; allocator evidence is required
before claiming a memory saving.

**Confidence.** Contribution `MEASURED`; optimization `HYPOTHESIS`.

### 5. Aggregation group-state cost — `MEASURED` contribution

**Evidence.** U09 group-by-host with `count` and `sum(n)` at 10K: `46.933 ms`
versus U07 `MatchAll` sorted by `n` at K=100: `39.108 ms` (+20.0%). The group
cardinality is exactly 3.

**Suspected boundary.** Per-document group-key extraction, hash lookup and
aggregate state updates.

**Expected improvement mechanism.** Columnar/grouped fast path with fewer
per-document allocations, preserving exact group ordering and sums.

**Correctness risk.** Medium: exact sums (including checked overflow), group
order, missing/null semantics and distinct counts.

**Proposed PR 15C measurement.** Before/after U09 and PR10/PR14 aggregation
suites; exact group/count/sum/distinct equivalence across all fixtures.

**Confidence.** Contribution `MEASURED`; mechanism `HYPOTHESIS`.

### 6. JSON scalar path overhead — `MEASURED` contribution

**Evidence.** U06 `body.severity == 2` at 10K: `40.652 ms` versus U02 typed
`n ∈ {0}`: `34.477 ms` (+17.9%). U05 CIDR+time is only +5.2% over U02.

**Suspected boundary.** JSON path decoding/evaluation versus typed column access.

**Expected improvement mechanism.** Faster indexed JSON path evaluation or a
columnar derived representation; not authorized without a design.

**Correctness risk.** High: JSON missing/null/empty and path semantics are
first-class contracts.

**Proposed PR 15C measurement.** Before/after U06 with PR11/PR14 JSON suites and
the independent U06 oracle.

**Confidence.** Contribution `MEASURED`; mechanism `HYPOTHESIS`.

### 7. Serial batch has no redundant-work savings — `MEASURED` neutral

**Evidence.** U10 three-slot batch `121.843 ms` versus the sum of standalone U04
(`39.734`) + U05 (`36.263`) + U09 (`46.933`) = `122.930 ms`; ratio `0.991×`.
There is no measurable batching overhead, but also no shared-work benefit.

**Suspected boundary.** Slots run independently; repeated corpus scans are not
shared.

**Expected improvement mechanism.** Cross-slot shared predicate/scan evaluation
or a common candidate pipeline. This is a larger architectural change and needs
a separate approved design.

**Correctness risk.** High: per-slot isolation, budget accounting and failure
isolation must remain exactly as today.

**Proposed PR 15C measurement.** Controlled batch-vs-standalone comparisons with
per-slot oracle equivalence and the existing batch governance suites.

**Confidence.** Neutral effect `MEASURED`; opportunity `HYPOTHESIS`.

### 8. Projection width at K=100 — `INSUFFICIENT EVIDENCE`

**Evidence.** U08 `Source` `39.050 ms` versus `Fields(host,n)` `39.088 ms`
(`1.001×`) at K=100. The difference is far below the observed trial dispersion
(1.017–1.063 for these lanes).

**Disposition.** No projection optimization candidate at this K/width. A future
case with wider projections or larger K would need new measurements.

### 9. Pinned page 2 — `MEASURED` no action

**Evidence.** U12 page 1 `39.292 ms`, page 2 `39.202 ms` (`0.998×`). No page-2
continuation penalty is visible at page size 100.

**Disposition.** No candidate.

### 10. Geo — `INSUFFICIENT EVIDENCE`

**Evidence.** U13 `0.054 ms` on the separate eight-point geo corpus. It is a
correctness/provenance lane, not a scaling measurement.

**Disposition.** No performance conclusion; a geo scaling lane would need a new
workload version and a larger fixed geometry corpus.

## Recommended PR 15C ordering (candidate only)

1. Full-corpus absent/rare work (largest measured scaling effect; needs evidence).
2. Superlinear lexical top-K at 100K (largest absolute lane; highest correctness
   risk).
3. Segment topology/block layout (measured inversion; needs profile/counters).
4. Top-K K=1000 (clear controlled contribution).
5. Aggregation state updates.
6. JSON path evaluation.
7. Cross-slot batch reuse (largest design change; lowest readiness).

No item becomes `OPTIMIZE` without a separate maintainer decision and a new
approved PR 15C plan.
