# PERF-06-C — Physical query execution contract

**Status:** C1 architecture and correctness contract proposed for independent review; **documentation only**. No executor, dispatch, API, format, or benchmark implementation is delivered by C1.

**Source examined:** `yduchesne/quervant` `main@8c9f51f311afa5b327f70432e32c0f6f5c205eab`, the merged PERF-06-B4 baseline (PR #129). **Scope:** single-shard v0.1 lexical `UnifiedSearcher`, not distributed, vector, or a new generic cost-based planner. Source reconciliation and historical negative evidence: [C1 source audit](../pr-artifacts/perf-06-c/PERF06C1_SOURCE_AUDIT.md).

## 1. Objective and nonnegotiable boundaries

A and B have optimized postings/scoring primitives, keyword sorting, and key identity. C integrates them as a narrowly eligible physical execution strategy that reduces full-match intermediate ownership while retaining the exact public query contract.

Let **N** be the number of effective-live physical documents, **M** the number of effective-live exact-term matches, and **K** the requested page size. A retained Top-K heap has capacity **K+1**, not K, to establish `next_cursor`. The target is to reduce redundant **O(M)** allocations and re-materializations, not to reduce correctness obligations to O(K). A successful response retains exact `total_hits=M`, complete ordering and ties, correct `Some(f64)` scores for lexical returned hits, projection and cursor semantics, and stable snapshot/PIT visibility.

**Hard boundaries:** No early termination at K; no approximate count; no unvalidated or skipped posting; no skipped full-key equality on a fingerprint collision; no hidden change to scoring error behavior, query work accounting, resource limits, cancellation, ranking or response ownership. Any failure returns a typed error, never a partial successful page.

C1 freezes contracts and evidence requirements. **C2** implements the exact-count/Top-K physical execution, **C3** implements guarded winner-only scoring and materialization, and **C4** independently reviews and qualifies the incremental warm impact. No stage may silently widen C1 eligibility or treat the rejected PR 15I-C implementation as an accepted baseline.

## 2. Accepted source: what actually runs

The following is the *current* baseline, not the older pre-PERF-05 pipeline:

1. `UnifiedSearcher::search_impl` validates query, then sort, Top-K, and projection. `execute_unified` validates cursor binding/fingerprint **before compiling/opening readers** and compiles the existing `UnifiedPlan`; the external result remains `UnifiedResponse`.
2. `collect_mixed` acquires guarded segment readers, enforces codec/schema equality, resolves effective-live masks, expands the compiled query, and computes `SnapshotStats` through a **single shared `MixedWorkMeter`**. The existing B1 ordinal map is optional and request-wide; a typed preparation error is never an optional fallback.
3. `single_term_postings_eligible` already recognizes a root `UnifiedNode::Lexical(0)` with one `CompiledLeaf::Term` containing one analyzed term, one positive lexical leaf, no typed leaf, no aggregation, and no cursor. The currently accepted `evaluate_lexical_with` strict branch **already avoids the repeated membership binary search** and moves the decoded `(doc_id, freq)` posting vector without copying it.
4. That branch still retains a full-M posting vector and a full-M `Vec<(doc_id, f64)>` returned to `collect_mixed`, with logical matched-set/scored-map reservation checks; `collect_mixed` then visits every scored hit and maintains the bounded K+1 heap. This is the remaining C2 consolidation opportunity. It is *not* the superseded `BTreeSet → BTreeMap → Vec` stack of earlier source revisions.
5. With a single eligible sortable Keyword field, `keyword_ordinal_eligible` and B1 `SnapshotKeywordOrdinals` permit B2 numeric rank comparison. B3 can use validated, per-segment runtime hashes as a **prefilter only**; equal hashes still require full raw-key equality. B1 optional unavailable states fall back *before* using numeric candidates. Each segment's B3 key binder may independently choose its existing owned-key fallback.
6. `collect_mixed` currently calls the score-producing evaluator before considering most candidates. `ProjectedHit.score` must be `Some(score)` for a positive lexical hit even when explicit sort is independent of score. `project_selected_hits`, the response-memory handoff and `UnifiedCursor` remain the authoritative output path.
7. `UnifiedSearcher::select_keys` serves atomic query mutation through a **different** complete-membership visitor (`visit_lexical_membership_with`). It is not a Top-K execution surface and is protected from C2/C3 replacement.

Source anchors: `crates/quervant-core/src/search/{unified.rs,unified_plan.rs,execute.rs,score.rs,memory.rs,work.rs,unified_cursor.rs}`; `src/index/{snapshot.rs,keyword_ordinals.rs}`; `src/segment/{reader.rs,column.rs,postings.rs}`.

## 3. Physical plan and eligibility

### 3.1 Two execution families, one semantic contract

The physical selection is an **internal, request-local**, deterministic choice between:

- **`LegacyUnified`**: call the accepted generic implementation, without behavioral modification.
- **`StrictTermOrdinalTopK`**: C2's separate, isolated executor for a proven single exact-term posting stream and one sortable keyword ordinal field.

These are *conceptual* internal variants, not new public `Query`, `UnifiedRequest`, `UnifiedPlan`, or result API shapes. The physical plan is not persisted, encoded in a cursor, exposed over the wire, or retained beyond the current request. It contains only validated references/IDs and the request-local ownership needed by C2. Do not add a second query compiler.

### 3.2 Required selection predicates (all must be true)

| Dimension | `StrictTermOrdinalTopK` requirement | Otherwise |
| --- | --- | --- |
| Call surface | Standalone `UnifiedSearcher::search`; no batch meter | `LegacyUnified` |
| Compiled root | Exactly `UnifiedNode::Lexical(0)` | Legacy |
| Lexical leaves | Exactly one `CompiledLeaf::Term`, with **one** normalized analyzed term | Legacy |
| Scoring | `positive_lexical == {0}`; only positive term contributes | Legacy |
| Typed/Boolean | Zero typed leaves; no `And`, `Or`, `Not` wrapper, phrase, multi-term, prefix, regex, glob, fuzzy or `MatchAll` | Legacy |
| Aggregation / pagination | `aggregation.is_none()`, `request.after.is_none()` | Legacy |
| Sort | Exactly one explicit field; field is `Keyword`, `Cardinality::Single`, columnar; no `multi` selector, JSON path or distance origin | Legacy |
| Rank capability | Snapshot-wide B1 ordinal preparation is `Ready` and every segment's rank translation/bound ordinal reader is valid | A documented optional unavailable => Legacy **before first candidate**; true error => error |
| Workload opportunity | Verified effective-live term match count **M > K+1** (no candidates can be discarded by Top-K when M ≤ K+1). Use the existing checked, snapshot-wide live term `df`/postings evidence; no new sampling heuristic or arbitrary threshold | Legacy |
| Reader/scoring integrity | Snapshot guard, schema, live masks, expansion/stats and reader preconditions have succeeded | Typed error, never fallback |
| Cursor/PIT | First-page query on the supplied immutable snapshot; existing PIT remains valid when accessed via ordinary snapshot binding | Legacy on `after` |
| Sort direction/placement | B2 handles ascending/descending, missing first/last, and exact byte-key ties | No special C logic |

**M is a proven effective-live count, not an estimate from physical dictionary frequency that includes deleted rows.** If the existing snapshot stats do not supply a sound count for a particular format/state, use Legacy. Never skip enumeration or final match validation because the count predicts the outcome. An empty/absent term and one-hit term remain on the accepted low-hit path. The M>K+1 threshold is a **structural no-benefit guard**, not an empirically tuned selectivity knob.

**Important:** An unsupported/optional capability is distinct from a genuine corruption, mismatch, lock poison, resource failure or cancellation. Only the documented optional-unavailable cases can choose Legacy; errors propagate unchanged. There is no "catch an exception and retry generic" path after observable candidate processing.

### 3.3 Dispatch and isolation contract

Select the physical family **once per request**, after the original request/cursor/compiled-plan validation and after the shared read-only prerequisites needed to certify eligibility, but **before admitting any candidate**. The generic and specialized hot loops must be **separate, out-of-line, independently reviewable call paths**, not a new per-document `if physical_mode` branch inside the existing `collect_mixed` loop.

This is a deliberate response to historical PR 15I-C: even a compiled but disabled physical branch changed low-hit code generation and was associated with substantial absent/rare regressions. C2 must not transplant that old generic-boundary design. It must document which cold/setup code may be factored and prove that the generic path keeps its approved semantics and budget behavior. Low-hit latency neutrality is a mandatory C4 guard; no unreviewed compiler/inlining flag or manual branch hint.

### 3.4 Selection outcomes

| Condition | Outcome |
| --- | --- |
| Any static shape predicate false | Legacy, no new physical preparation |
| No verified matches or M ≤ K+1 | Legacy, with all original pre-execution validation obligations |
| B1 ordinal returns documented `NotAvailable` | Legacy before candidate processing |
| B3 key directory optional capacity refusal in a Ready request | Stay on selected numeric execution, use that segment's established owned B2 key path |
| Corrupt rank, DOC_KEYS, posting, schema, foreign guard, poison or cancellation | Exact typed error; do not disguise as ineligibility |
| First candidate already processed, then unexpected unsupported shape | Internal `CorruptIndex` / typed failure; never replay on generic executor |
| Budget boundary exceeded | Existing typed `ResourceLimit`, no completed response |

## 4. C2 contract — exact-count, bounded Top-K physical execution

C2 is the first **code** stage. It reuses the accepted implementation's query compiler, postings reader, `compute_stats`, `MixedWorkMeter`, `CandidateBudget` / `SegmentCandidateLedger`, `ColumnAccess`, B1 ordinal map, B2 numeric comparator, B3 exact duplicate prefilter and K+1 heap. It must not define a second BM25 formula, schema interpreter or duplicate policy.

**Required physical stages, in order:**

1. **Preflight:** Complete the existing request/cursor validation, schema/reader checks, effective-live-mask resolution, query expansion, statistics and eligible ordinal preparation. Keep failure categories and work meter common with the accepted path.
2. **Term decode:** For each segment, decode and validate the **sole** exact term's `(doc_id,freq)` postings through `PostingsReader::next_with(cancel)`. Preserve strictly increasing doc IDs, full term-frequency/scanned-occurrence work charges including deleted postings, bounds checks and effective-live filtering. Retaining the one existing decoded posting vector is permitted in C2; copying it into additional M-sized ID containers is not.
3. **Examination:** Retain the existing logical effective-live-document lexical-examination charge (N), bounds verification and cancellation polling; a postings-driven iterator must not simply charge M instead of the legacy N. Validate every matched physical candidate in increasing doc-id order even if the heap is full.
4. **Count:** Increment request-wide `total_hits` once per effective-live match with checked `u64` arithmetic, independent of K or candidate competitiveness. No K-based early exit, selectivity approximation, duplicate conflation, or application of a cursor filter to `total_hits`.
5. **Score:** In C2, **eagerly score every effective-live matched candidate** using the accepted `FieldStats::bm25_score` and the exact existing `+0.0` arithmetic order. Preserve the positive lexical score type, score bits, and all scoring errors before making any score-dependent decision. A compact score-only temporary aligned with the one posting vector is allowed to preserve the existing score-before-candidate error boundary; a second M-sized `(doc_id,score)` result vector and full-M `BTreeMap` are not.
6. **Admit:** Feed the validated physical doc/score candidates directly to the current B2/B3 numeric Top-K collector; preserve rank translation, missing/null/MultiOne legacy decode, exact byte-key tie-break, duplicate error checks **before rejection**, logical candidate charges, K+1 sentinel, and fallible owned materialization only when currently required.
7. **Finalize:** Release segment-owned scratch and virtual compatibility reservations exactly once before finishing the page. Sort the retained K+1 entries using the canonical comparator; derive the complete last-key/last-sort cursor, truncate to K, and use the **unchanged** projection and batch-response handoff path.

**Accounting contract:** The removed matched-set and scored-map physical objects have established *logical* `CandidateBudget` admissions. C2 must explicitly preserve their ResourceLimit boundary and the cumulative segment/global reservation model using accounted, non-owned reservations at the corresponding validation stages; the retained posting and score scratch must also have an approved measured/logical charge, without double-charging the same allocation. The historical PR 15I-C "virtual 48*M/64*M" mechanism is evidence of a possible accounting shape, **not reusable code or blanket authorization**. Before any C2 code, its detailed plan must provide a mechanically checked ledger timeline (preflight, commit, release, failure unwind) for K=1/10/100, M=0/1/K/K+1/K+2 and mixed segments. A stricter new cap rejection and a newly successful formerly rejected request are both contract changes requiring explicit review, not automatic tradeoffs for speed.

**Error boundary:** Existing `evaluate_lexical_with` fully decodes relevant postings and eagerly computes all scores before the collector validates candidate keys/sort values. C2 may not cause a later malformed posting or `InvalidScore` to be hidden by premature successful Top-K completion. In multi-fault fixtures, the accepted error precedence is the reference; if one-pass admission changes which error wins, C2 must preserve the precedence using a bounded validation/score phase before heap admission, rather than relaxing assertions. A complete query failure emits no partial response.

**Ownership:** Posting/score scratch is per segment/request, tied to its reader guard and ledger; B1 numeric maps belong to the exact snapshot; B3 hash cache belongs to a verified segment state; the only cross-segment retained results are the bounded heap entries (plus existing cursor/projected response). No borrowed slice survives the reader/guard, crosses a snapshot, enters a persisted cursor, or is exposed in `ProjectedHit`.

## 5. C3 contract — conditional deferred BM25 and owned materialization

C3 is a separate, subsequent implementation PR. **It is not authorized by C1 to omit scoring merely because the sort ignores score.** The first implementation remains C2's eager scorer.

C3 may replace the C2 M-sized score phase with final-winner scoring only when a **source-proven, request-wide score-safety certificate** establishes all of the following *before rejecting any candidate*:

1. The same C2 `StrictTermOrdinalTopK` shape is selected, one explicit rank-based sort whose ordering never uses score (including ties, which must be broken by logical key, not score); no cursor, batch, aggregation, relevance sort, multi-positive-term or typed shape.
2. `compute_stats` has completed the original statistics, DF/live-count/length validation and resource/work charges. Prepared term/field stats are present and coherent or the accepted zero-score branch is exactly applicable.
3. For every enumerated valid matched posting, the accepted BM25 score is proven mathematically **finite, nonnegative, non-erroring**, with source-checked term frequency, DF ≤ N, valid prepared IDF/avgdl/length and exact existing behavior for degenerate cases. An unproven or anomalous case must take the **eager C2** path **before any candidate is admitted**.
4. Existing per-match non-score errors (postings, sort value, key corruption, duplicate validation, limits, cancellation) are still evaluated at their established points. No score validation may be replaced by a conjecture that corruption is unlikely.
5. The chosen winner-score calculation uses the original prepared `FieldStats::bm25_score` with exactly the same `+0.0` and float order, producing bit-equal `Some(f64)` values for every **returned** lexical hit; the extra K+1 lookahead entry does not require a user-visible score if it is not returned and does not influence sorting. The score-bearing response projection and batch contract are unchanged.
6. The scorer certificate's preparation and failure paths have explicit deterministic work/memory accounting. Any normally possible `InvalidScore` or `CorruptIndex` triggered by a losing document must still surface; otherwise deferral is **not eligible**.

**Proof obligation:** C3's detailed plan must include an explicit case-by-case argument over `score.rs::{bm25,bm25_with_idf,FieldStats::bm25_score}`, including `tf=0`, `N=0`, `avgdl≤0`, `DF>N`, missing term/field stat, invalid prepared IDF, extreme representable frequencies/lengths and non-finite arithmetic, plus adversarial tests showing both proof and eager fallback. C1 does **not** assert that this proof has already passed.

For noneligible cases, C3 uses C2's eager all-match scoring or the accepted Legacy executor as already selected. Never defer for relevance ordering, where BM25 determines Top-K membership.

## 6. Preservation matrix and failure precedence

| Contract dimension | Reference obligation for C2/C3 |
| --- | --- |
| Exact count | Every live match counted; checked overflow; independent of page size; no early stop |
| Full postings validation | Full authenticated, bounded, ordered decoder; invalid doc ID/frequency/UTF-8 or corrupt structure remains typed |
| Work | Same shared request meter; scanned `freq` charges, live examination, query stats and cancellation checks; zero-hit not free of setup |
| Candidate budget | One `CandidateBudget` and existing heap/response scope; no unmetered M allocation, no weakened or extra cap rejection |
| Ordering | B2 snapshot-wide rank, field direction and missing placement, exact byte-ascending logical-key tie; K+1 sentinel |
| Duplicate identity | B3 fingerprint never an exact identity; forced collisions resolve with bytes; duplicate errors before discarding losers |
| Score | C2 eager bit-equal scoring for all M; C3 defers only with proven no-error certificate and returns bit-equal scores |
| Cursor/PIT | First-page fast path only; existing `UnifiedCursor` identity and sort fields; follow-on pages use Legacy; PIT pinned snapshot never retargeted |
| Fallback | Unsupported shape and authorized optional `NotAvailable` only, before candidate processing; true errors never fallback |
| Atomicity | On failure there is no partial `UnifiedResponse`, no leaked ledger charge, no partially published cache/index/manifest |
| Projection and batch | Existing `project_selected_hits`, `ProjectionLedger` and response handoff; batch calls remain Legacy throughout C1–C3 |
| Mutation `select_keys` | Entirely unaffected; no shared callback rerouted to Top-K fast path |
| Source/storage | No new durable format, writer, manifest, S3/RustFS, cross-shard, or public API requirement |

**Ordered error checkpoints:** (1) query/sort/TopK/projection validation; (2) cursor/snapshot binding; (3) schema/plan compile; (4) guarded reader/live/expansion/statistics/ordinal preparation; (5) full posting validation and logical budget checks; (6) eager scoring validation or an approved C3 mathematical certificate; (7) per-candidate key/sort/duplicate validation and heap admission; (8) final projection/response handoff. C2/C3 must document and test any edge at which the accepted source's error precedence differs from this summary; the accepted executable, not this prose, decides the regression oracle.

## 7. Required acceptance evidence for C2, C3 and C4

No C1 executable test is created. The future implementation work is required to supply the following (without inventing fixtures or weakening a negative test).

| Stage | Required proof and independent oracle |
| --- | --- |
| C2 dispatch | Every row of `3.2; eligible positive, M=K+1 and M>K+1; absent/rare and unsupported => old generic branch; no hidden per-doc dispatch |
| C2 exactness | 10K/100K generated corpus; M=0/1/K/K+1/K+2/high-hit; K=1/10/31/32/100, both sort directions, null/missing and equal ranks, multiple segments, masks and updates |
| C2 key/sort | Genuine B1 `Ready` and `NotAvailable`, B3 key-directory capacity refusal, forced hash collision, duplicate retained key before a losing sort decision, invalid selected and unselected key/sort values |
| C2 scoring | All returned score `to_bits()` equal to accepted reference; scoring error/frequency/overflow/cancellation before any partial page; no second scored pair Vec retained |
| C2 accounting | Matched/scored virtual-charge boundary, global+segment peak, exactly-at-limit/one-over, preflight/release/unwind, max scanned postings/work units, batch memory untouched |
| C2 interface/lifecycle | Real `FsDirectory` commit/reopen, PIT held across update/delete/compaction, cursor continuation through Legacy, typed/Boolean/phrase/JSON/geo/aggregation and mutation-select-keys untouched |
| C3 certificate | Explicit math proof and case matrix `5`; bad scores in losing postings still yield the accepted typed error or **pre-decided** eager fallback; winners bit-equal |
| C3 materialization | Losers own no key/sort/score output beyond accepted B2/B3 obligations; one winner allocation; ordinal ties, K+1 extra hit, memory and cancellation parity |
| C4 qualification | One separately approved 16-lane warm experiment versus the **merged accepted A+B (B4)** baseline; no historical A0-versus-B result substituted for incremental C. Freeze 4 primary and 12 absent/rare/K guards plus control and STOP policy before timing. Preserve unfavorable evidence |

**Required test design:** red/green focused unit tests; public-path differential against the accepted generic implementation (not a second copy of the fast path), independently computed literal oracles for counts/order/projection; adversarial corrupt envelopes; at least one real persistent-index/PIT/cursor fixture; exact budget edges; seeded property matrix; default and all-features Rust QA/CI as applicable. Benchmark acquisition occurs **only at C4**, never in C1–C3.

## 8. Historical negative evidence and independent-review STOP boundaries

The prior PR 15H-A/A2 linear staging and PR 15I-C physical executor were performance-rejected and rolled back. PR 15I-C improved common-hit lanes but regressed rare/absent lanes 1.26–1.72×; the final branch showed a generic codegen/layout regression even when its physical operator was disabled. Thus "it produces the right answers" or "its common lane is faster" cannot justify adoption.

C2 must be materially different: build atop the accepted PERF-05 strict postings move and B1–B3 numeric/key primitives; eliminate the **remaining** M-sized scored pairs without copying the rejected operator; isolate the generic method from dispatch/codegen effects; use M>K+1 structural gating; prove byte-for-byte query answers and ledger behavior. C3 must add an independent score-safety certificate, not turn 15I-C's eager scorer into an unchecked winner-only shortcut. C4 must include all low-hit guardrails and preserve any negative result.

**Hard STOP for later coding agents:** required codec/score/resource/error contract not provable; eligibility needs a second compilation or hidden public semantic change; generic performance neutrality cannot be evaluated; budget peaks cannot be reconciled; an unselected corrupt candidate stops producing its accepted typed error; a new persisted format or extra storage I/O appears necessary; authoring guide or main source contradicts a frozen decision; any new condition outside the approved C2/C3 decision matrix. The maintainer must approve a design amendment before affected code proceeds.

## 9. Document boundary and adoption

This document is C1's **reviewable architecture specification**, not an implemented physical-plan module or a detailed coding-agent execution plan. Approving the C1 documentation accepts the above *constraints and intended narrow physical architecture*, not the performance effect or any unresolved compiler/ledger proof. C2 and C3 each require their own source-specific detailed agent plans under `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` before changing production code; those plans may only refine implementation within these invariants. A discovery that would change a frozen semantic rule requires a separately reviewed C1 amendment, not improvisation.

**C1 acceptance:** source audit reconciled to the merged B4 baseline; all fallback rows, score/count/error and ownership contracts explicit; rejected historical approaches classified; no `crates/`, `benchmarks/`, CI, dependency or index change; architecture document linked from the roadmap/register. After independent maintainer review C1 may merge. C2 must start from that merged document baseline, not the draft PR head.

## 10. C2 implementation status note (documentation only)

**Status:** C2 has been **implemented** on a draft, unmerged branch as
`StrictTermOrdinalTopK` per `docs/pr-artifacts/perf-06-c/PERF06C2_DETAILED_PLAN.md`.
This note records the status only; it changes no C1 semantic rule above.

- Eligibility, the `M > K+1` certificate, the request-local single route
  decision, full posting-stream validation, eager all-match scoring, the
  preserved virtual matched/scored admissions, the B1/B2/B3 reuse and the shared
  K+1 cursor finalization are implemented exactly as specified in §3–§6.
- The sole retained `(doc_id, freq)` posting allocation is rewritten **in place**
  to `(doc_id, score.to_bits())`, so no second full-M `(doc_id, f64)` vector is
  allocated. Both the `SET_BYTES_PER_ENTRY` and `SCORED_MAP_BYTES_PER_ENTRY`
  logical admissions are still made and released in the accepted order.
- **C2 makes no performance claim.** No benchmark, profiler or timing acquisition
  was executed. C3 (winner-only scoring) is **not started**; C4 remains the only
  stage authorized to measure the incremental warm effect and the low-hit
  codegen guard.
- Independent review and maintainer merge are **open** (G10). See
  `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` for the executed
  evidence, residual risks and the disclosed limitations.

## 11. C3 implementation note (2026-11-26)

**Status:** C3 is implemented on the draft branch `dev/perf06-c3` exactly within
§3–§6 above. This note records the implementation and changes **no** normative C1
rule. Plan: [PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md](../pr-artifacts/perf-06-c/PERF06C3_DETAILED_IMPLEMENTATION_PLAN.md);
evidence: [PERF06C3_EXECUTION_REPORT.md](../pr-artifacts/perf-06-c/PERF06C3_EXECUTION_REPORT.md).

- **Certificate (§5 point 3).** One private, request-local, read-only
  `DeferredBm25` token is issued by `FieldStats::certify_deferred` only when the
  already prepared statistics satisfy all of: `n > 0`, `df > 0`, `df <= n`,
  finite `avgdl` in the closed interval `[2^-64, 2^64]`, and a finite prepared
  IDF in `[0, 64]`. These are *sufficient* bounds: every valid decoded posting
  (`tf >= 1` enforced by the real decoder) then provably yields a finite,
  nonnegative `bm25_with_idf` result, so the eager `InvalidScore` branch is
  unreachable for a certified request. The token borrows the exact prepared
  field and normalized term, so it cannot outlive them or refer to another
  query. A rejected certificate is a successful decision to keep eager C2, never
  an error.
- **Eligibility and fallback.** C2's `strict_term_dispatch_eligible` and
  `M > K + 1` count guard are byte-identical and are still evaluated first. Only
  when C2 already selected `StrictTermOrdinalTopK` does C3 attempt the
  certificate — exactly once per request, before any candidate. Any guard
  failure keeps the accepted **eager C2** body. Every originally ineligible shape
  (relevance sort, cursor, batch, aggregation, typed/Boolean/phrase/prefix/
  regex/glob/fuzzy, B1 `NotAvailable`, non-columnar or multi-value sort) keeps
  `LegacyUnified` unchanged.
- **Mechanism.** The single validated `(doc_id, freq)` posting allocation is
  unchanged. Under the certificate the second word stays the raw positive
  integer frequency; the `K + 1` bounded heap entry carries it inline as
  `Option<NonZeroU64>`. After heap selection, `finalize_deferred_entries`
  validates every retained entry — including the sentinel — and then computes
  scores for the first `K` only, through the **same**
  `FieldStats::bm25_score` with the same `+ 0.0` accumulator and the same
  snapshot/norm lifetime. The `K + 1` lookahead keeps `score = None` and is
  truncated by the unchanged cursor handoff.
- **Not deferred.** Full posting-stream validation, exact `total_hits`, `N`
  lexical examination and scanned-frequency charges, the virtual matched/scored
  admissions and their release order, per-candidate sort/key validation, the B2
  numeric comparator, the B3 fingerprint prefilter plus exact key equality and
  its optional per-segment owned-key fallback, `MultiOne` full-tuple decode, and
  the **fallible** key/sort materialization of every competitive provisional
  entry all remain at their accepted points. Only a proven non-erroring score
  computation moves.
- **No public, format or accounting change.** No new storage section, sidecar,
  compatibility version, cursor field, dependency, feature flag, environment
  switch or runtime telemetry. The candidate-charge *logical* formulas are
  unchanged; the physical `MixedEntry` grows by exactly one `u64` word
  (136 → 144 bytes, alignment unchanged), bounded by the existing heap capacity.
- **Test coverage classes.** Deterministic certificate decision matrix and
  uniform-bound/bit-parity proof; direct deferred decoder/ledger parity; public
  dispatch/count matrix; shared synthetic-statistic fallback with competing real
  corruption; real corrupt-byte precedence; later-segment failure after an
  earlier collected segment; actual B3 refusal; replacement/final-identity;
  null/missing and equal-rank ties; exact logical-budget edges; complete
  cancellation-poll sweep; seeded differential matrix; private representation and
  finalization guard; B3 collision and `MultiOne`; and three real `FsDirectory`
  integrations (scores/cursor, PIT update/delete/compact/paging, resource and
  cancellation atomicity).
- **No performance claim.** C4 remains the only stage authorized to measure the
  incremental warm effect and to guard absent/rare lanes and the one-word entry
  growth. Independent review and maintainer acceptance (G10) remain open.

## 12. C3-F1 acceptance-status note (2026-11-26)

**Status:** acceptance repair only. This note records status and changes **no**
normative C1/C3 rule above. Plan:
[PERF06C3F1_DETAILED_FIXUP_PLAN.md](../pr-artifacts/perf-06-c/PERF06C3F1_DETAILED_FIXUP_PLAN.md);
report: [PERF06C3F1_EXECUTION_REPORT.md](../pr-artifacts/perf-06-c/PERF06C3F1_EXECUTION_REPORT.md).

- The C3 production implementation — the conservative certificate, the deferred
  executor, the inline integer frequency, the finalizer, the eager fallback, the
  preserved eager/`Legacy` routes and all accounting — is **byte-identical** to
  the independently reviewed head `ee77917d303b060b0d38ab88e5d9ae73625f6676`.
- Only test acceptance was repaired: certificate guard isolation, the exact
  dispatch domain, literal fault descriptors, literal resource outcomes and
  every-hit snapshot oracles. No scoring, accounting, projection-order,
  cancellation-poll, duplicate-policy, cursor or storage semantics changed.
- Clarified checkpoint: the U09 exact-peak case for `M = 102, K = 100` is refused
  by the **existing projection ledger** with `ResourceLimit { 13056, 13160 }`
  *after* C3 finalized exactly `100` scores. The original plan's broader
  "no final scores on any exact-peak failure" expectation was an author error for
  this specific request and is corrected in the F1 report; the accepted
  production order (collect/finalize, then project) is unchanged. Earlier
  failures still score zero.
- Coverage is reported from the `Lines` column only. G10 (independent review and
  maintainer acceptance) and C4 (warm qualification) remain open; no performance
  claim is made.

## 13. C3-F2 test-only conformance status note (2026-11-27)

**Status:** test-only conformance repair on the existing PR #132. This note
records status and changes **no** normative C1/C3 rule above. Report:
[PERF06C3F2_EXECUTION_REPORT.md](../pr-artifacts/perf-06-c/PERF06C3F2_EXECUTION_REPORT.md).

- Production behaviour is unchanged: the certificate, decoder, accounting,
  eager fallback, heap representation and winner finalization are byte-identical
  to the reviewed head `051104724125ba95d49a6d94b61500f974a3599f`. C1/C3
  normative ownership, scoring, accounting and projection order are untouched.
- Two test bodies changed: the F1-local `#[allow(clippy::too_many_arguments)]`
  and its nested recovery helper were removed (the recovery operations are
  inlined unchanged), and the plain-batch row now asserts literal
  `aggregation.is_none()` on both the normal and forced-Legacy responses. The
  resource table, exact projection checkpoint `{13056, 13160}` and all accepted
  outcomes are preserved.
- Historical C3 and F1 evidence is preserved; F2 evidence lives under
  `docs/pr-artifacts/perf-06-c/evidence/c3-f2/`. G10 (independent review and
  maintainer acceptance) and C4 (warm qualification) remain open; no performance
  claim is made.
