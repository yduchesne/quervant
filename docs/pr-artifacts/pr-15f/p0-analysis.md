# PR 15F — P0 analysis and investigation ranking

**This document ranks investigation hypotheses. It does not authorize, schedule or
estimate the benefit of any optimization.** All numbers are new, source-bound
measurements from `benchmarks/reports/pr15f/p0-profile-summary.json` at measured
source `80a2fd73245b4e981b635f02bf9c7f136711f4e4`.

## 1. Evidence model and confidence

- **Exclusive** shares partition self samples. A symbol is owned only when every
  *material* call-tree occurrence (≥0.5% inclusive) resolves to one group;
  otherwise its self share is `G08`/`R08` unknown. Only exclusive shares feed the
  dominance rule.
- **Inclusive** shares are the maximum single-path share per group. They overlap
  and are never summed. Umbrella frames that enclose the whole query process
  (adapter root, `UnifiedSearcher::search`, `search_impl`, `execute_unified`) are
  excluded from inclusive-candidate evidence because their share is tautological.
- **Allocated exclusive** is a diagnostic proportional split used for transparency
  only; it is not used for ranking.
- Dominance rules: `STRONG_EXCLUSIVE_CANDIDATE` requires a named exclusive owner
  ≥20.0%, a lead ≥5.0 pp over the next named owner and unknown ≤10.0%.
  `LIKELY_INCLUSIVE_CANDIDATE` requires an inclusive path ≥35.0% with no disjoint
  competing path ≥35.0%; it is inclusive-only and is not an estimated improvement.
  Otherwise `UNRESOLVED`.

The strict exclusive view is dominated by allocator, `memcpy`, `drop_glue` and
runtime frames (G08), so **no query lane produced a strong exclusive candidate**.
The useful signal is inclusive and is reported as a hypothesis, not as removable
cost.

## 2. Query findings

### 2.1 Absent queries — column setup dominates the visible path

| Lane | G03 columns incl. | G02 planning/stats incl. | G01 reader incl. | G03 exclusive | Unknown excl. | Rank |
|---|---:|---:|---:|---:|---:|---|
| 10K absent / K100 | **44.20%** | 15.19% | 10.58% | 31.67% | 47.54% | `LIKELY_INCLUSIVE` G03 |
| 100K absent / K100 | **53.11%** | 19.69% | 10.23% | 43.19% | 32.83% | `LIKELY_INCLUSIVE` G03 |

`ColumnAccess::open` → `ColumnReader::open_with_doc_count` → `read_u64_at` is the
visible chain (`crates/quervant-core/src/search/typed_compare.rs`,
`crates/quervant-core/src/segment/column.rs`). At 100K, exclusive G03 reaches
43.19% with 32.83% unknown, so this is the strongest exclusive signal in the
campaign even though the strict rule is not satisfied. G02 exclusive is 11.17%
(10K) and 13.83% (100K). The absent-query cost is therefore not just "no
postings"; it pays per-query column geometry setup and planning/statistics work
before the empty result is known. This is descriptive: it does not prove the
setup is removable or cacheable without changing semantics.

### 2.2 Rare queries — STORED selective materialization is the dominant chain

| Lane | G05 STORED incl. | G04 key decoding incl. | G03 incl. | G05 exclusive | Unknown excl. | Rank |
|---|---:|---:|---:|---:|---:|---|
| 10K rare / K100 | **82.34%** | 5.29% | 2.99% | 7.92% | 88.33% | `LIKELY_INCLUSIVE` G05 |
| 100K rare / K100 | **82.41%** | 5.23% | 2.18% | 7.77% | 88.98% | `LIKELY_INCLUSIVE` G05 |

The inclusive chain is `project_selected_hits` → `stored_docs_selected` →
`decode_stored_selected` (`crates/quervant-core/src/search/unified.rs`,
`crates/quervant-core/src/segment/reader.rs`,
`crates/quervant-core/src/segment/stored.rs`). The exclusive G05 share is small
because the sampled leaf frames are framing/UTF-8/validation helpers and
allocator glue; those are exactly the caveats recorded in PR 15E Phase 6/6F. A
one-hit query still walks the complete STORED section, but this evidence alone
does **not** prove that random access is safe or that all-record validation can be
relaxed.

### 2.3 Medium queries — the same STORED chain, spread wider

| Lane | G05 incl. | G04 incl. | G03 incl. | G05 exclusive | Unknown excl. | Rank |
|---|---:|---:|---:|---:|---:|---|
| 10K medium / K100 | **49.14%** | 7.91% | 3.92% | 4.83% | 89.20% | `LIKELY_INCLUSIVE` G05 |
| 100K medium / K100 | **48.47%** | 9.48% | 4.25% | 4.62% | 89.45% | `LIKELY_INCLUSIVE` G05 |

Medium queries return `N/8` hits, so projection and key decoding remain visible
while scored/hit-staging groups stay below 5% inclusive. The STORED path is the
largest single-chain share; the exact-key group rises but is not dominant.

### 2.4 Common queries — no single dominant operation

| Lane | G05 incl. | G06A membership | G06B staging/BM25 | G06C sort/heap | G03 incl. | Unknown excl. | Rank |
|---|---:|---:|---:|---:|---:|---:|---|
| 10K common / K100 | 29.67% | 10.22% | 4.14% | 0.78% | 7.54% | 84.07% | `UNRESOLVED` |
| 100K common / K100 | 28.18% | 10.11% | 4.50% | 1.04% | 10.41% | 83.63% | `UNRESOLVED` |
| 100K common / K10 | 33.42% | 12.09% | 5.36% | 1.10% | 12.18% | 84.87% | `UNRESOLVED` |

The common lanes show several medium-sized paths (projection, candidate
membership, scoring, sort/collect) and no operation reaching the 35% inclusive
threshold. This is **counterevidence** to selecting a single fused stream or a
single heap change on this evidence. The strict view is 84% unknown, so no
dominance claim is possible.

## 3. Reopen findings

| N | `reopen_total_ns` median | p95 | `index_open_ns` share | `snapshot_acquire_ns` median |
|---|---:|---:|---:|---:|
| 10K | 42,824,322 | 43,980,686 | 99.96% | 2,639 |
| 100K | 434,657,998 | 445,055,541 | 99.997% | 20,088 |

`FsDirectory::open` is ~14 µs and snapshot acquisition is 2.6 µs / 20.1 µs. Reopen
is effectively `Index::open_with_limits`, not directory or snapshot overhead. The
historical build-phase `reopen_ns` (~423.193 ms at 100K) is independent context;
matching order of magnitude is not a same-session comparison.

CPU (inclusive, never summed):

| N | R03 segment read+digest | R04 container parse+metadata | R05 mutation-state decode | R06 visibility | Strict exclusive |
|---|---:|---:|---:|---:|---|
| 10K | **40.65%** | 43.70% | 21.11% | 1.44% | R08 100% |
| 100K | **40.42%** | 43.41% | 20.97% | 1.50% | R08 100% |

The dominant symbols are `sha2` compression under
`segment::format::sha256` / `ContentDigest::sha256_v1` and
`MutationStateV1::decode` → `parse_container`. Strict exclusive ownership is
unresolved because the same digest symbol appears under segment verification,
manifest verification and mutation-state decoding; the plan requires unknown
rather than guessed ownership. The allocated diagnostic (not used for ranking)
splits ~75–79% to R03 and ~11–16% to unknown at these corpus sizes.

Read-only layout shows why reopen is expensive:

| N | Total | Stored | Postings | Dictionary | Mutation state | Segment |
|---|---:|---:|---:|---:|---:|---:|
| 10K | 3,090,037 | 966,263 (31.27%) | 389,957 (12.62%) | 350,207 (11.33%) | 960,180 (31.07%) | 2,129,038 |
| 100K | 30,965,025 | 9,662,513 (31.20%) | 3,983,573 (12.86%) | 3,500,207 (11.30%) | 9,600,180 (31.00%) | 21,364,026 |

The 100K total exactly matches the historical 30,965,025-byte anchor: this is the
same layout generation. Stored + mutation state are ~62% of all bytes; section
sizes alone do **not** establish an achievable compression ratio or label existing
bytes as waste.

## 4. Allocation observations

Heaptrack 1.5.0 aggregates:

| Lane | Replies | Allocation calls | Sites |
|---|---:|---:|---:|
| 100K rare / K100 | 1,070 | 1,294,333 | 10 |
| 100K common / K100 | 140 | 90,139,348 | 10 |

Common queries allocate ~70× more than rare in the sampled window, consistent
with a much larger matched set and projection. These are coarse aggregate records,
not per-callsite attribution and not a substitute for the CPU profiles.

## 5. Investigation ranking (evidence, limits, risks, ownership)

### A1 — Streaming / bounded top-K / late scoring

- **Measured support:** common lanes are `UNRESOLVED` with G05 28.18–33.42%,
  G06A 10.11–12.09%, G06B 4.14–5.36%, G06C 0.78–1.10%; no group clears 35%.
- **Source anchors:** `search/unified.rs::collect_mixed`,
  `search/execute.rs::evaluate_lexical_with`, `score_segment`.
- **Evidence limits:** 84–85% of self samples are unknown glue/allocator; inclusive
  groups overlap; no lane isolates a removable pass.
- **Risks:** exact `total_hits`, explicit-sort ordering, tie behavior, budgets,
  cancellation, cursor/PIT continuation, batch semantics.
- **Independent validation:** format-preserving prototype benchmarked against the
  frozen nine-lane matrix plus adversarial exact-count/order tests and
  allocation comparison.
- **Owner:** future **P1 design/implementation PR** (not this PR).

### A2 — Immutable column-geometry cache

- **Measured support:** absent G03 inclusive 44.20% (10K) / 53.11% (100K),
  exclusive 31.67% / 43.19%; 100K G02 exclusive 13.83%, G01 exclusive 10.15%.
- **Source anchors:** `search/typed_compare.rs::ColumnAccess::open`,
  `segment/column.rs::ColumnReader::open_with_doc_count`,
  `index/snapshot.rs::open_segment_reader`.
- **Evidence limits:** absent-only; no cache identity or eviction measurement;
  exclusive signal is strong but below the strict dominance rule.
- **Risks:** cache identity must bind snapshot, segment digest and generation;
  metadata memory accounting; eviction; corruption checks and legacy segments;
  concurrent reader visibility.
- **Independent validation:** exact cache-identity/lifetime tests, corruption and
  legacy fallback tests, metadata-budget accounting, net-positive measurement on
  absent and sort-heavy lanes.
- **Owner:** future **P2 design/implementation PR**.

### A3 — Random-access STORED/DOC_KEYS + validation architecture

- **Measured support:** G05 inclusive 82.34% / 82.41% (rare) and 49.14% / 48.47%
  (medium); G04 inclusive 5.2–9.5%; STORED is 31.2% of 100K index bytes.
- **Source anchors:** `segment/reader.rs::stored_docs_selected`,
  `doc_key_selected`; `segment/stored.rs::decode_stored_selected`.
- **Evidence limits:** exclusive G05 is only 4.6–7.9%; the chain is dominated by
  framing/validation/glue frames. This supports investigating a layout, not
  removing validation.
- **Risks:** new format version; corruption/error precedence for *all* records
  including unselected ones; key/offset integrity; digest verification; snapshot
  and budget accounting; legacy compatibility.
- **Independent validation:** approved storage/validation specification,
  fail-closed corrupt-unselected-record tests, compatibility matrix, exact
  projection/order parity, real local filesystem and cold-cache checks.
- **Owner:** future **P3 format/design PR**. `ARCHITECTURE_DESIGN_REQUIRED`.

### A4 — Planner specialization for zero-hit / single-term shapes

- **Measured support:** absent G02 inclusive 15.19% / 19.69% and exclusive 11.17% /
  13.83%; G06C is 1.93% inclusive at 10K absent; common lanes show no dominant
  planner path.
- **Source anchors:** `search/unified_plan.rs::compile`, `compute_stats`,
  `search/execute.rs::effective_live_examination_count`.
- **Evidence limits:** modest share; the largest absent cost is column setup (A2),
  so planner-only work cannot address the whole gap.
- **Risks:** hidden eligibility matrix; bypassing typed/cursor/aggregation
  semantics; cross-segment equivalence; exact budget and cancellation behavior.
- **Independent validation:** differential tests across query shapes, explicit
  fallback to the general plan, no hidden semantic bypass.
- **Owner:** future **P4 design PR** (contingent).

### A5 — Index size and reopen (digest/format architecture)

- **Measured support:** 100K reopen median 434.66 ms, 99.997% inside
  `index_open_ns`; R03 inclusive 40.42%, R05 20.97%, R04 43.41%; mutation state is
  9,600,180 B (31.00%) and STORED 9,662,513 B (31.20%). The 10.7×-Tantivy size
  observation is descriptive only.
- **Source anchors:** `index/support.rs::read_verified`,
  `segment/format.rs::parse_container`/`sha256`,
  `segment/reader.rs::verify_bytes`/`SegmentReader::open`,
  `index/mutation_state.rs::MutationStateV1::decode`.
- **Evidence limits:** strict exclusive ownership is unresolved because digest
  symbols span objects; the allocated split is diagnostic only. Reopen is a fresh
  process; it is not an OS-cold page-cache study.
- **Risks:** integrity/validation semantics, manifest/segment compatibility,
  mutation-state durability and replay, generation visibility, recovery from
  partial objects.
- **Independent validation:** versioned format + recovery specification,
  corruption/fault injection, cold-reader ObjectStore bootstrap if remote-backed
  layout changes, and a fresh benchmark campaign.
- **Owner:** future **P5 / format architecture PR**. `ARCHITECTURE_DESIGN_REQUIRED`.

## 6. What this evidence does not establish

- It does not authorize A1–A5, choose between streaming and record offsets, or
  estimate speedups from inclusive percentages or section sizes.
- It does not compare instrumented Quervant with uninstrumented Tantivy/Lucene.
- It does not establish OS-cold behavior, remote ObjectStore latency, compression
  headroom or BM25 quality.
- It does not show that any validation frame is removable.
- **No optimization was implemented.**
