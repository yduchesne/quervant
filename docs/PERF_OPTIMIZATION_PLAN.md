# Quervant — Performance Optimization Architecture Plan

> **Status: PROSPECTIVE / NOT APPROVED FOR IMPLEMENTATION.**
> This document records the architecture observations and potential follow-up work identified after PR 15E. It is **not** a PR 15E implementation plan, an authorization to modify segment formats or query semantics, or a claim of competitive benchmark parity. Design and implementation require separate, independently reviewed PR plans under [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md).
>
> **PR 15E boundary:** PR #83 implements B1a, B1b, Phase 3, Phase 4 and Phase 5; Phase 6/6F are profiling/attribution only. The accepted Phase 6F disposition is **C06_NO_SAFE_LOCAL_CHANGE**. Do not reopen PR #83's accepted code to implement the proposals below. Its G11 independent evidence-review/merge-specific waiver and maintainer sign-off remain separate gates.

## 1. Objective and evidence quality

Quervant's longer-term goal is not merely to imitate a lexical search engine. Its planned distributed, cross-index, graph and ontology operators must be able to reuse efficient physical search primitives. The immediate objective is to reduce avoidable work in exact-term search **without weakening** snapshot visibility, on-disk integrity, corruption detection, error precedence, resource accounting, cancellation, cursor/PIT semantics or exact-result correctness.

Evidence classes in this document:

- **Measured (Quervant-only):** the qualified PR 15E same-host, same-session, nine-lane cumulative comparison, original source `c3083d83ab88fd53f30d34d34c4860d29aa6493e` versus optimized source `40ca10bae46f2d7df7804a0a129a99a4daf35ef0`. Three independent trials per arm; five warmups and 20 timed samples per lane/trial; nine of nine `B_FASTER`, zero `A_FASTER`; real contention probes clear. Source: [cumulative-closeout.json](../benchmarks/reports/pr15e-b1/cumulative-closeout.json) and [closeout qualification](pr-artifacts/pr-15e-b1/closeout-qualification.md).
- **Measured (historical cross-engine):** qualified PR 15D, source `40a9c26a57aa23640904075e77be956ee52718bc`, frozen `pr15d_v1` corpus, Tantivy 0.22.1 and Lucene alongside earlier Quervant. Source: [PR 15D qualification](pr-artifacts/pr-15d/qualification.md) and [machine report](../benchmarks/reports/pr15d/pr15d-qualified.json).
- **Projected, not measured cross-engine:** comparison of the above two campaigns. The source revisions and frozen workload are compatible enough for an approximate ranking, but ratios spanning separate runs are **not** a qualified fresh three-engine measurement. Do not publish projected ratios as measured Tantivy/Lucene results for optimized Quervant.
- **CPU attribution:** Phase 6 and Phase 6F focused investigation, including admitted limits of inclusive-vs-exclusive attribution; consult [Phase 6 qualification](pr-artifacts/pr-15e-b1/phase6-qualification.md) and [Phase 6F qualification](pr-artifacts/pr-15e-b1/phase6f-qualification.md). The Phase 6 broad campaign was partial (4/20 valid targeted captures); Phase 6F reused recorded evidence and introduced no new CPU capture.
- **Source observations:** verified code paths on the optimized PR #83 head. Identifying a costly-looking algorithm is a hypothesis until new stage-level measurements establish its contribution.

### 1.1 Confirmed cumulative gains

Times below are median-of-trial-medians in milliseconds (lower is better); the ratios are from directly paired PR 15E runs, not an inferred product of individual phase gains.

| Frozen lane | Original Quervant | Optimized Quervant | Speedup |
|---|---:|---:|---:|
| 10K absent / K100 | 0.295 | 0.144 | 2.05x |
| 10K rare / K100 | 7.667 | 3.028 | 2.53x |
| 10K medium / K100 | 12.742 | 5.107 | 2.50x |
| 10K common / K100 | 28.926 | 8.738 | 3.31x |
| 100K absent / K100 | 3.102 | 1.251 | 2.48x |
| 100K rare / K100 | 83.403 | 28.289 | 2.95x |
| 100K medium / K100 | 642.870 | 51.118 | 12.58x |
| 100K common / K100 | 1,940.649 | 87.377 | 22.21x |
| 100K common / K10 | 1,952.422 | 72.218 | 27.04x |

### 1.2 Indicative gap to Tantivy — not a new three-engine result

The historical PR 15D **warm** Tantivy medians are 0.0162, 0.0189, 0.2376, 0.6573 and 0.6048 ms for the 100K absent/K100, rare/K100, medium/K100, common/K100 and common/K10 lanes, respectively. Dividing the optimized PR 15E medians by those historical values gives approximate Quervant/Tantivy latency ratios of **77x, 1,497x, 215x, 133x and 119x**. These are indicative cross-session ratios, **not** an accepted head-to-head ranking. The corresponding PR 15D Lucene results likewise indicate a substantial, although generally smaller, gap. The full PR 15D rerun against optimized Quervant is required before accepting current competitive claims.

The frozen task is exact-term membership plus exact `total_hits`, ordered by logical `doc_id`, K10/K100, and selected stored-document materialization; it does **not** measure comparable BM25 ranking quality. The adapters use different physical sort representations (Quervant keyword column; Tantivy numeric ordinal fast field; Lucene string SortedDocValues), and Tantivy/Lucene use a separate count and top-K search whereas Quervant uses one public search call. These are disclosed workload-shape differences, not reasons to manufacture a normalized score.

## 2. Verified current execution-path observations

### O-01 — STORED selective materialization still scans all records

`crates/quervant-core/src/segment/reader.rs::stored_docs_selected` invokes `segment/stored.rs::decode_stored_selected` when the query-local full-record cache is absent. The decoder scans **all** physical STORED records, including unselected records, validating frame structure, keys, field presence/order, UTF-8 and typed values while charging the modeled full-decode budget. Only selected records are materialized. This preserves current corruption/error/admissibility behavior, but creates work proportional to section size for a one-hit result.

Phase 6 observed an **82.39% inclusive** G05 chain in the primary 100K rare lane; Phase 6F's separate, sample-derived exclusive buckets include framing 18.70%, UTF-8 stored validation 16.14%, modeled budget admission 9.64%, and skip dispatch 9.51% of sampled process CPU. Do **not** sum these with the inclusive G05 number or interpret them as independently removable costs. Phase 6F's decision was `C06_NO_SAFE_LOCAL_CHANGE`: no dominant, proven redundant local operation met the preapproved threshold.

### O-02 — DOC_KEYS singleton access also scans keys

`SegmentReader::doc_key_selected` avoids owning all document keys but still validates the `DOC_KEYS` section by scanning. Phase 5's materialization reduction is real; it does not create random access. `doc_keys()`, `stored()` and `live_docs()` caches currently reside in the **query-local** `SegmentReader`, not in shared immutable `VerifiedSegmentState`.

### O-03 — Intermediate matched/scored collections remain

`search/execute.rs::evaluate_lexical_with` populates `BTreeSet<u64>` of matches, invokes `score_segment` (which constructs a `BTreeMap<u64, f64>`), then returns a vector. `search/unified.rs::collect_mixed` creates `SelectedHit` entries, sort tuples and a bounded heap. Even for a query sorted by `doc_id ASC`, the existing route computes lexical scores for the matched set.

The PR 15D Quervant adapter explicitly issues `UnifiedRequest` with `Query::Term`, sort `doc_id ASC`, K10/K100 and projection `doc_id`. Therefore the observed scoring/collection pipeline is relevant to the frozen benchmark. The amount of elapsed time attributable to each layer remains to be measured on the **optimized** code.

### O-04 — Per-query typed-column geometry setup

`search/unified.rs::collect_mixed` opens `ColumnAccess::open(reader)` and `typed::JsonAccess::open(reader)` during each query's segment processing; `ColumnAccess` calls `SegmentReader::open_columns`, whose `ColumnReader::open` reparses column geometry. `VerifiedSegmentState` already shares several parsed immutable structures, but not an equivalent retained column geometry directory. Phase 6F's absent-lane control attributed about **60.30%** of the process samples to G03 column setup, a **control-lane attribution** rather than a separately authorized optimization.

### O-05 — Existing postings specialization has narrow eligibility

`single_term_postings_eligible` in `search/unified.rs` permits posting-driven candidate enumeration only for an exact single analyzed term at the plan root, with no typed leaf, aggregation or `after` cursor. It works with explicit sorts (including the benchmark). `evaluate_lexical_with` still creates the matched set and computes scores after that enumeration. Other query shapes fall back to the general scan path.

### O-06 — Additional possible costs

The candidate heap currently checks for duplicate logical keys by iterating existing heap entries. Invariant-preserving duplicate detection may be a worthwhile local profiling target, but **must not** be removed merely because the benchmark fixture has unique keys. Query planning, dictionary expansion, field statistics, and selected-hit key/sort-tuple resolution may also contribute. None has a sufficiently isolated current cost estimate to justify an implementation by itself.

## 3. Proposed physical architecture

These are **design directions**, not locked implementation contracts.

### A1. Fused streaming candidate operator + late scoring — first architectural candidate

Replace the multi-stage `matched BTreeSet -> scored BTreeMap -> Vec -> SelectedHit/heap` pipeline, when a compiled plan proves eligibility, with a per-segment iterator/visitor that:

1. Consumes postings in deterministic document order and applies effective-live filtering.
2. Evaluates the complete predicate and advances **exact** `total_hits`, work meters and cancellation checks; it may not stop counting at K.
3. Maintains only the bounded top-K candidates and sort keys required by the request; avoid materializing all matches.
4. Defers score computation for non-winning candidates **only if** the requested ordering is score-independent and response semantics can still provide exact scores for every returned hit.
5. Enriches winners with byte-exact document keys, final scores when contractually required, and selected projections.
6. Uses the existing general path whenever eligibility, budget equivalence, precise first-error precedence or count semantics cannot be proven.

**Non-negotiable:** preserve query-wide counters and budget admission boundaries (including deliberate logical charges for full-live examination), duplicate live-key corruption detection, PIT/cursor ordering, aggregation, typed/lexical Boolean semantics, cancellation, and score values of returned hits. The existing P4 query-shape eligibility and fallback tests are the starting point, not an authorization to expand silently.

A longer-term extension may use posting-list intersections/unions and score-aware top-K collectors for more complex queries, but only with separate correctness proof. Block-max WAND is **not** a first-line solution for mandatory exact counts plus explicit `doc_id` sorting.

### A2. Share validated immutable column geometry; add sortable ordinal access

Investigate moving appropriately validated, immutable column directory/geometry data into a bounded `VerifiedSegmentState` cache, so `ColumnAccess` can open a cheap view instead of reparsing it for each query. Preserve query-local mutable state and snapshot ownership boundaries; the shared structure must remain immutable, charged against metadata limits, and safe on cache exhaustion.

As a separate, more invasive format evolution, consider dictionary-encoded `Keyword` sort ordinals with a stable field dictionary and block/ordinal access. Compare numeric ordinals during top-K selection and recover actual strings only for chosen hits. Prove byte-exact lexical ordering, missing/null and multi-value selection semantics, compatibility with legacy segments, and equal cursor comparisons. Do not assume an ordinal representation is free or equivalent for all typed field kinds.

### A3. Versioned random-access STORED / DOC_KEYS with trusted validation provenance

Add a **new on-disk segment-format version**, with an immutable record/block offset index for stored documents and document keys, enabling selected physical IDs to be decoded without an O(segment-record-count) scan *at query time*.

The central design challenge is not the offsets: it is preserving today's validation and full-decode modeled-budget behavior. A separate architecture specification must resolve:

- **Trust root:** content descriptor/digest and exact segment bytes, generation/snapshot binding, codec version/schema/feature set and immutable offset-directory identity.
- **Validation lifecycle:** which structural, semantic, UTF-8, bounds and resource checks occur at write, commit, bootstrap/open, first access or each query; whether a durable validation receipt can safely replace repeated full scans.
- **Corruption observability:** how corruption of **unselected** records is still detected with a contractually equivalent failure surface; what cannot be preserved without upfront validation; exact error precedence on multiple faults.
- **Budget compatibility:** modeled full-decode admission limits, allocation ceilings, overflow, fallible allocation and query-local temporary accounting; moving validation must not silently make formerly rejected queries succeed or vice versa unless separately approved.
- **Access/cache:** immutable block offsets, bounded decompression/decoding, cache eviction, snapshot isolation, remote RustFS range-read semantics (without assuming S3 conditional-write guarantees), and corruption recovery.
- **Legacy reads:** existing segment format stays supported through its established checked path unless a separately approved migration/compatibility contract says otherwise.

A file checksum, page checksum or unverified cache flag by itself is **not** sufficient evidence of semantic validation.

### A4. Planner-selected fast execution strategies

Add a narrow internal physical-plan operator selection, behind the existing public `UnifiedSearcher` API and contract validation. The first prospective shape is exact `Term` + count + explicit ascending field sort + bounded projection, with a pure dictionary miss path that avoids opening unused column/stored machinery. Expand eligibility only after query-shape equivalence tests and an explicit fallback matrix cover typed predicates, JSON, geo, aggregation, negative clauses, cursor/PIT and batch requests.

The operator interfaces should be reusable by **distributed local-shard search**, cross-index joins and graph/ontology query execution, not hardcode the PR 15D term names, `doc_id` field or corpus layout.

### A5. Longer-term postings and I/O work

After profiling the previous changes, examine block-oriented posting iterators, skips, compact fast-field representations and suitable local mmap access. These may require versioned layout changes and a separate RustFS read/cache strategy; mmap is not an assumed universal implementation for remote object storage. Treat WAND/block-max ranking as a distinct **relevance-ordered** problem, not a shortcut for exact-total-hit + explicit-sort benchmarks.

## 4. Prioritized investigation and PR sequencing

| Stage | Candidate work | Format impact | Target lane(s) | Gate before proceeding |
|---|---|---|---|---|
| P0 | Optimized-head operator-level CPU/allocation profiling; stable stage attribution | None | All | **COMPLETE — measurement only.** Source `80a2fd73245b4e981b635f02bf9c7f136711f4e4`; [P0 qualification](pr-artifacts/pr-15f/p0-qualification.md), [analysis](pr-artifacts/pr-15f/p0-analysis.md), [sanitized summary](../benchmarks/reports/pr15f/p0-profile-summary.json). No optimization is authorized. |
| P1 | A1 fused stream + bounded top-K + late scoring | None intended | Medium/common | **PR 15G-C REJECTED — SAFE ROLLBACK.** C and its two-pass fixup failed performance and were rolled back to accepted B. **PR 15G-D** added D1 and D2; the corrected isolated D2-only campaign qualified but **REJECTED D2** (100K common/K10 inconclusive, 10K rare `A_FASTER`), restoring byte-exact A. **PR 15G-E** implemented segment-only v1.1 persistent offset directories, then a qualified format-aware campaign **REJECTED E**: both rare lanes were `A_FASTER` (100K rare ~6.4–6.9× slower) and several common lanes regressed. Production format/fast path was rolled back to exact A+B. See `docs/pr-artifacts/pr-15g-e/`. |
| P1b | Linear single-term candidate staging (PR 15H-A) | None | 100K medium/common, guards | **PR 15H-A PERFORMANCE_REJECTED — SAFE ROLLBACK.** Seven frozen warm Quervant lanes, four mirrored paired blocks and a sealed pre-optimization baseline qualified. 100K common K100/K10 improved (`B_FASTER`) and 100K medium was not slower, but all low-hit guards regressed: 100K rare and 100K absent were `A_FASTER` by roughly 1.7–1.8×, and 10K rare by roughly 1.25×. HA-P04 failed, so the production change was reverted byte-for-byte to the pinned baseline. See `docs/pr-artifacts/pr-15h-a/`. |
| P2 | A2 immutable column geometry caching | None for first subphase | Absent, sort-heavy | **PR 15G-A PERFORMANCE_QUALIFIED_CI_BLOCKED.** Retained validated geometry, exact metadata admission, fallback and correctness evidence are in place. The authorized nine-lane same-host A/B campaign passed P01–P04: 100K absent/K100 ratio 0.367 and 10K absent/K100 ratio 0.495 (`B_FASTER`), no other lane `A_FASTER`; supplementary nine-lane geometric-mean speedup 1.216×. See `docs/pr-artifacts/pr-15g-a/performance-qualification.md`. Hosted CI and independent review remain pending. |
| P3 | A3 random-access stored/key access | **No format change in PR 15G-B** | Rare/projection | **PR 15G-B PERFORMANCE_QUALIFIED_CI_BLOCKED.** In-memory lazy validated v1 offsets on admitted snapshot states passed the authorized nine-lane A/B: both rare lanes `B_FASTER`, no lane `A_FASTER`; supplementary geomean speedup 3.773×. Persistent offset formats/compression remain future PR 15G-E work. See `docs/pr-artifacts/pr-15g-b/performance-qualification.md`. Hosted CI and independent review remain pending. |
| P4 | A4 broader physical planner specialization | None initially | Mixed/zero-hit/single-term | Explicit eligibility matrix, no hidden cursor/aggregation/typed bypass, cross-segment equivalence |
| P5 | A5 posting compression/skip/mmap design | Possibly | Workload-dependent | New profiling evidence, I/O portability and remote-store contract |

The suggested investment order after P0 is **P1 -> P2 -> P3**. P4/P5 are contingent, not promised implementation phases. Separate each architecture/design decision from the PR that implements it. Never implement all of these together under PR #83.

### Qualification for every future implementation PR

- Reuse the frozen **nine-lane cumulative Quervant** matrix against the last accepted optimized revision; compare on one properly authorized idle host, with genuine clear contention probes, exact oracle checks, three trials and disclosed inconclusive results. Do not multiply phase ratios into a cumulative claim.
- Run the **full qualified PR 15D three-engine suite** against the new candidate when competitive claims are needed: 32 query lanes per engine (warm/process-cold, 10K/100K, absent/rare/medium/common, K10/K100), exact counts/order/doc IDs, three trials and the independent validator. Keep old results immutable, distinguish cross-session projections from same-session comparison, and preserve the PR 15D physical sort/API-shape caveats.
- Require default/all-feature stable and MSRV QA, >=85% workspace production line coverage, real local filesystem/commit/reopen/recovery, the real RustFS acceptance matrix and exact-head CI when applicable. A local container substitute is supporting evidence, not a replacement for required hosted acceptance.
- Adversarial differential tests must cover missing/zero/one/many postings; tombstones/superseded keys; corrupt selected and **unselected** data; key mismatches; limit exact/one-over; overflow; cancellation at each pipeline phase; batch shared budget release; PIT/refresh/delete/upsert; tie sorts; search-after; JSON/typed/geo/aggregation and both legacy/new segment formats when relevant.
- Compare matched documents, `total_hits`, exact keys/order/sort tuples, returned scores, error classes and precedence, modeled work/byte counters, and retained bytes. Any intentional semantic change requires separate maintainer approval, not an optimization-only waiver.
- Publish per-lane latency, memory/allocation and CPU observations only where actually measured, plus run identity, trial dispersion, source/corpus digest, methodology and limitations; retain private raw evidence under `target/`.

## 5. Explicit non-goals and decision gates

- **Not approved:** query-time validation shortcuts, skipping malformed unselected records, relaxing resource/candidate limits, dropping returned scores, weakening exact counts, changing public API or on-disk format, or adopting new caches with unverifiable lifetime/eviction semantics.
- **Not established:** that every projected Tantivy/Lucene gap is attributable to STORED scanning; that block- or ordinal-based designs will achieve Tantivy parity; that this single-host exact-term result predicts BM25, distributed, analytics or remote-RustFS throughput.
- **Not part of PR #83:** Phase 7, new profiling, new optimization implementation, segment-format migration, scored-query benchmark redesign, or merge. G11 and maintainer sign-off are governed by the existing PR closeout process.
- **Stop rule for future design agents:** if an invariant cannot be preserved under an explicit approved decision, record the counterexample and stop the affected design/implementation; do not substitute a plausible behavior, reinterpret a validator, weaken tests, or silently treat a performance goal as authorization to change correctness.

## 6. Source and evidence index

- [PR 15E cumulative nine-lane comparison](../benchmarks/reports/pr15e-b1/cumulative-closeout.json)
- [PR 15E closeout qualification](pr-artifacts/pr-15e-b1/closeout-qualification.md)
- [PR 15E Phase 6 CPU attribution](pr-artifacts/pr-15e-b1/phase6-qualification.md)
- [PR 15E Phase 6F narrow attribution](pr-artifacts/pr-15e-b1/phase6f-qualification.md)
- [PR 15D qualified cross-engine report](../benchmarks/reports/pr15d/pr15d-qualified.json)
- [PR 15D benchmark contract](../benchmarks/pr15d/README.md)
- `crates/quervant-core/src/search/{unified,execute,typed_compare}.rs`
- `crates/quervant-core/src/segment/{reader,stored,value}.rs`
- `benchmarks/pr15d/adapters/{quervant,tantivy,lucene}/`

*This is a design-candidate backlog. Close PR #83 on its own acceptance criteria; scope later architecture changes as separately reviewed work.*
