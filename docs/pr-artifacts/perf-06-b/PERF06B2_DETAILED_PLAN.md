# PERF-06-B2 — Snapshot-wide ordinal keyword sorting in the existing global Top-K collector

**Execution-ready detailed implementation contract — revision 1 (planning artifact only)**  
**Repository:** `yduchesne/quervant` · **planned PR:** `PERF-06-B2` (new, separate from PR #126)  
**Authoritative design inputs:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`, `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`, the accepted B1 plan and B1 execution/F1/F2 reports.  
**Reviewed B1 implementation candidate:** `ad66e5e833616bafaaa97e15d89cdc511d715868` (PR #126). **Original accepted A6 main:** `480a77e78c6897e05cb7ceb76b01434974b82ec6`.  
**IMPORTANT SOURCE ASSUMPTION:** The maintainer directs us to *assume B1 has merged*. At planning time PR #126 was still `OPEN`, `merged=false`, and `main` still pointed to `480a77e...`; this document is therefore a **prospective, source-specific design**. **The coding agent MUST prove that B1 is accepted/merged and that the post-merge source matches the reviewed B1 executable blobs before doing B2 production work. If not, HARD STOP the production start (decision X01); do not merge B1, cherry-pick it, or begin B2 on an unmerged branch.** The resulting accepted post-B1 `main` commit is **not invented or pre-assigned** here: record its actual 40-character SHA at preflight.

**Deliverable:** One B2 implementation PR with no on-disk-format change, preserving all public behavior and using numeric string-value ordinals for **both intra- and cross-segment candidate comparisons** in the existing supported hot path. B3 remains identity/dedup work; B4 owns cumulative B-series warm qualification. **No warm benchmark acquisition is authorized in B2.**

---

## 0. Absolute execution and autonomy contract

> **Continuous execution authorization:** Execute every prescribed phase from successful source admission through implementation, focused and final verification, documentation, ordinary push, PR creation, and CI inspection without asking for routine reconfirmation. A passing preflight, implementation phase, AUTO-RESOLVE rule, or test checkpoint does not require new permission. Only an applicable HARD STOP, truly missing human design choice, or essential external dependency stops affected work. Continue independently safe authorized tasks when an obstacle is isolated. Never invent an architecture, broaden scope, weaken correctness, merge, or self-approve G10.

1. **First** fetch and inspect `origin/main` and PR #126's merged state. Start B2 **only from the accepted/merged post-B1 main**, not from the A6 SHA, a stale worktree, the F2 PR head, or another feature branch. Use a new branch named `dev/perf06-b2` and new **draft** B2 PR; avoid modifying PR #126. Only fast-forward updates; no reset/rebase/force-push/automatic merge. Do not touch a dirty worktree.
2. Perform the preimplementation invariant/counterexample worksheet before modifying production. Use the concrete instructions and choices below. Source anchors must be reconfirmed by symbol and behavior after B1 merge, not by line number alone.
3. Implement exactly **one** fast path in `UnifiedSearcher::collect_mixed` using the same global `BinaryHeap<MixedEntry>`, same duplicate `d3c::State`, same scoring and matched-document enumeration, and the B1 snapshot-wide map. **No new top-K collector, per-segment heaps, scorer, duplicate filter, index writer, format, map cache, global field registry, or cursor format.**
4. A B1 map `NotAvailable` is a **whole-request nonoptimized fallback** decided before candidate processing. A B1 map **error** is not an optional fallback. An unexpected missing ordinal handle after `Ready` is a typed error, never a partial fallback.
5. Run focused correctness/adversarial tests and applicable final Rust QA/CI once against the finished executable source. Trust healthy accepted main; do **not** run baseline suites. Do not run BM-10 timing, PERF-06-B4, `perf`, Criterion sampling, cross-engine acquisition or local RustFS startup merely for B2. CI's existing RustFS job remains active and must pass.
6. Preserve the exact A6 unfavorable numerical evidence and the B1 F1/F2 history. B2 is **implementation correctness**, not evidence of faster warm queries, smaller index, better RSS, or completion of PERF-06-B.

### Completion states

- `PERF06_B2_READY_FOR_INDEPENDENT_REVIEW`: source/format/semantics/focused QA and applicable CI G0–G9 passed on the declared source; G10 open.
- `PERF06_B2_IMPLEMENTED_VERIFICATION_BLOCKED`: implementation completed but a mandatory test/CI/service gate is unexecuted or unresolved. State the exact blocked gate; no PASS claim.
- `PERF06_B2_HARD_STOP_DESIGN_AMENDMENT_REQUIRED`: a source fact or failure requires an unapproved semantic or architectural choice; halt affected work and report the narrowest necessary decision.
- `PERF06_B2_NOT_STARTED_B1_NOT_ACCEPTED`: B1 is not merged/accepted, or the accepted source does not match its frozen executable contract. No B2 production branch work.

---

## 1. Source admission and existing implementation (G0)

### 1.1 Preflight commands and source-proof matrix

From a clean repository root, record command output with actual timestamps and SHAs:

```sh
set -euo pipefail
git status --porcelain=v1
git fetch origin
git rev-parse origin/main
git rev-parse origin/dev/perf06-b1
git merge-base origin/main origin/dev/perf06-b1
git diff --name-status 480a77e78c6897e05cb7ceb76b01434974b82ec6..origin/main
# Using authenticated GitHub CLI if configured; otherwise the GitHub PR API:
gh pr view 126 --repo yduchesne/quervant --json state,mergedAt,mergeCommit,headRefOid,baseRefName,url
```

**Required evidence:** PR #126 is merged; the post-merge `main` has B1's persistent codec, public ordinal APIs and approved F2 corrections. If GitHub used a merge commit/rebase and the B1 executable commit is an ancestor, record the ancestry proof. If it used squash and ancestry fails, compare the **Git blobs**, not Git commit ancestry, of the following B1-critical paths between the F2 final source `ad66e5e...` and `origin/main`; they must match **byte-for-byte**, or the differences must be explicitly identified as a later accepted change requiring a new plan:

```text
crates/quervant-core/src/index/keyword_ordinals.rs
crates/quervant-core/src/index/snapshot.rs
crates/quervant-core/src/index/mod.rs
crates/quervant-core/src/segment/column.rs
crates/quervant-core/src/segment/format.rs
crates/quervant-core/src/segment/reader.rs
crates/quervant-core/src/segment/build.rs
crates/quervant-core/src/index/merge.rs
crates/quervant-core/src/search/unified.rs
crates/quervant-core/src/search/typed_compare.rs
```

For example, `git rev-parse 'origin/main:crates/quervant-core/src/index/keyword_ordinals.rs'` and `git rev-parse 'ad66e5e...:crates/quervant-core/src/index/keyword_ordinals.rs'` must identify the same blob for unchanged B1 components. If *any* of the two search files changed in a later accepted implementation, STOP pending a source-specific compatibility amendment rather than silently applying stale line-oriented edits. Confirm the actual `main` contains no B2 implementation already; if it does, classify its exact remaining delta before proceeding (X02).

**After proof:** create/switch only `dev/perf06-b2` from exact `origin/main`. Verify `HEAD`, remote base, clean worktree and complete B1 reference identities in `docs/pr-artifacts/perf-06-b/PERF06B2_EXECUTION_REPORT.md` before editing. Do not copy the B1 PR branch onto main.

### 1.2 Source facts already verified on B1 final candidate

| Existing symbol / file | Observed source contract; mandatory reuse |
|---|---|
| `index/snapshot.rs::ReaderSnapshot::prepare_keyword_ordinals(field_id, &[GuardedSegmentReader], cancel)` | A map is bound to one exact snapshot and field; guards must be ordered and admitted from the same snapshot. Result is `Ready(Arc<SnapshotKeywordOrdinals>)` or typed sticky `NotAvailable` (`LegacySegment`, `ResourceBudget`, `Allocation`, `UnsupportedField`). Real corruption, schema mismatch, cancellation and poison are errors. |
| `index/keyword_ordinals.rs::{SnapshotKeywordOrdinals,SegmentOrdinalMap}` | `map.bind_segment(&guard)?.translate(local_ordinal)?` yields a **shared lexical rank**, including when identical terms have different local ordinals. Per-snapshot ordinal numbers may change after append/compaction; old PIT retains its mapping. One-segment map is identity. |
| `segment/column.rs::{ColumnReader,KeywordOrdinalColumn,KeywordOrdinalValue}` | `bind_keyword_ordinals(field_id)` resolves the numeric field ID once; `doc_ordinal(doc_id)` returns `Missing`, `Null`, `Value{ordinal,state:Single|MultiOne}`. `dictionary_term(ordinal)` borrows validated raw bytes. `ColumnReader::value` retains logical decode/allocation semantics; v2 input has already been fully validated at open. |
| `search/typed_compare.rs::{ColumnAccess,SortValue,sort_tuple_for_doc,compare_candidates,compare_borrowed_keyword_to_owned,owned_keyword_sort_value}` | Existing general typed sorting, missing/null precedence, raw keyword bytes, multi selector and owned value semantics are authoritative. Reuse the existing ordinary path as fallback and for materialization. |
| `search/unified.rs::{UnifiedSearcher::collect_mixed,keyword_sort_late_eligible,consider_borrowed_keyword_candidate,MixedEntry,SelectedHit,candidate_charge,d3c::State}` | One global bounded `BinaryHeap<MixedEntry>` merges candidate results from all segments; `MixedEntry::cmp` orders best as `Less`. The heap limit is **K+1**, and the cursor contains an owned string-valued sort tuple from the Kth entry. Duplicate prefilter, exact counts, BM25, projection and work meters are already present and must not be replaced. |
| `search/unified.rs::search_impl/execute_unified` | Query and sort validation precede segment work; cursor binding/fingerprint validation precedes compilation/open; no change to those error boundaries. |
| `benchmarks/pr15d/adapters/quervant/src/main.rs::{QuerySession,search}` | One process session retains **one `Arc<ReaderSnapshot>`** across query requests; its benchmark workload is a strict keyword Term query sorted by `doc_id ASC` (K10/K100), matching B2 eligibility. This remains **read-only source evidence**, not a B2 timing result. |
| `search/typed_compare.rs::sort_value_cmp` | With missing-first: Missing < Null < Value; missing-last: Value < Null < Missing. `Desc` reverses **only Value versus Value**, not placement. Logical key ascending is the final tie-break. |

### 1.3 In-progress versus new work (do not reimplement B1)

| Capability | Classification at reviewed F2 source | B2 action |
|---|---|---|
| Versioned persistent keyword dictionary/ordinal column and legacy reads | DONE + VERIFIED in B1 | Reuse; do not edit format or writer |
| Shared reader/PIT-scoped map, memory admission, sticky optional results, cancellation/concurrency | DONE + VERIFIED in B1 | Call existing API; do not add cache or redo map algorithm |
| Bound numeric field access | DONE + VERIFIED in B1 | Add only a narrowly scoped query-local **logical-sort admission wrapper**; no new persistent format |
| Existing borrowed keyword late materialization | DONE + VERIFIED previously | Preserve as the complete fallback, with its negative/corruption tests |
| Cross-segment numeric collector ranking | NOT STARTED on B1 source | Implement in B2 |
| Numeric tie/ordering parity, cursor fallback, optional-unavailability parity | NOT VERIFIED for B2 | Implement and execute dedicated tests |
| B3 document identity/duplicate optimization and B4 timing campaign | NOT STARTED / OUT OF SCOPE | Explicit defer to their own PRs |

---

## 2. Frozen scope and requirements (G1)

### 2.1 Eligible B2 request — ALL of these conditions must hold

Apply the predicate **once per request**, before the match-candidate loop:

1. The request is `UnifiedSearcher::search`, **standalone** (`batch.is_none()`).
2. `single_term_postings_eligible(plan,request,aggregation)` is true: exact root `UnifiedNode::Lexical(0)` with exactly one analyzed Term, no typed leaves, one positive lexical leaf, no aggregation and no `after`.
3. Exactly **one** explicit sort field; no `distance_from`, no `json_path`, and `multi.is_none()`. (A `multi` selector on a single field remains valid but is intentionally legacy-only in B2.)
4. The sort field is existing `Keyword`, `Cardinality::Single`, and `options.columnar == true` in the canonical query schema; the `CodecSchema` has a canonical `field_id` for it.
5. All guards have been successfully admitted and checked under the existing segment schema/corruption contract. `ReaderSnapshot::prepare_keyword_ordinals(field_id,&guards,cancel)` returns **Ready** for the exact requesting snapshot.
6. No additional B2-specific config, feature flag, environment override, activation threshold, query rewrite or background preparation is allowed. Do **not** base eligibility on doc count, selectivity, K, live mask, score, string contents or benchmark lane.

### 2.2 Ineligible or unavailable: mandatory fallback before candidate enumeration

| Condition | Exact behavior |
|---|---|
| No explicit sort, multiple sort fields, non-Keyword, non-columnar, schema Multi, `multi.is_some()`, JSON path, geo distance | Do not prepare the ordinal map. Use the existing owned/borrowed/typed executor as dictated by existing code. |
| `request.after.is_some()` (including public PIT-bound subsequent pages) | Do not prepare a new B2 map for this request. Preserve existing cursor validation and string-sort continuation. The **first** page may use ordinal ranking; subsequent pages use the canonical old path. |
| Non-strict term, phrase, Boolean `And`/`Or`/`Not`, typed, MatchAll, aggregation, batch | Existing path unchanged; no new global map initialization just for these requests. |
| Zero segments | No ordinal preparation needed; preserve empty result/validation behavior. |
| `prepare_keyword_ordinals` returns `NotAvailable(LegacySegment | ResourceBudget | Allocation | UnsupportedField)` | **Whole-request** fallback, with no partial ordinal heap, new error, implicit rewrite or retry. Do not call preparation again for that field/snapshot to “get lucky”; sticky semantics remain B1-owned. |
| `prepare_keyword_ordinals` returns `IndexError::Cancelled` | Return the canonical `SearchError::Cancelled` (not `SearchError::Index(Cancelled)`). |
| Other B1 `IndexError` (corruption, schema mismatch, poison, wrong guard) | Preserve the typed error using existing `SearchError::Index`, never `NotAvailable` and never fallback. |
| B1 `Ready` but a segment's bound ordinal column is unexpectedly missing/incompatible | `SearchError::CorruptIndex { detail: "ready keyword ordinal map has no matching segment column" }`; **do not** mix ordinal and string heaps. |
| Any candidate numeric translation or source-reader error | Preserve the existing `SearchError::Segment` (or typed authoritative index error). Do not discard or retry via fallback after candidate processing begins. |

**Why deliberate scope matters:** B2 changes candidate comparisons in one source-backed hot path; existing cursor/aggregation/batch/typed/JSON/geospatial implementations remain semantic reference oracles and independent fallbacks. This is not permission to redesign the general query planner or to claim the ordinal path is universal.

### 2.3 Explicit non-goals

No COLUMNS v3 or modified v2 bytes; no change to any codec/required-feature/manifest; no persisted global ordinals; no permanent cross-snapshot IDs; no new field-ID registry; no multi-valued field ordinal sort; no JSON string sort; no relevance-sort change; no block-max/early-termination or reduced `total_hits`; no B3 document-key or duplicate-precheck optimization; no B4/BM-10 timing/stability/acquisition; no new cross-engine adapter; no remote publication, compaction or GC redesign; no new service, dependency, unsafe code, lock, LRU/cache or public API. No unapproved `SortValue` variant, public cursor component or query-contract change.

---

## 3. Correctness invariants, counterexamples and traceability

| ID | Falsifiable invariant | Counterexample that MUST fail acceptance | Primary tests |
|---|---|---|---|
| INV-B2-01 | Same raw string in different segments has the same shared numeric rank, even with different local ordinals | Directly comparing local ordinal `1` in segment A to local ordinal `1` in segment B yields a false equality/order | U03, U14, I01 |
| INV-B2-02 | Within B2 ranking the order is exactly `sort_value_cmp` and `compare_candidates`; only value/value reverses for Desc; raw UTF-8 bytes; key asc ties | Null moves on Desc, composed/decomposed Unicode collapses, or equal strings tie by segment index | U01, U02, U05, I01 |
| INV-B2-03 | All relevant B1 `Ready` candidates are validated/charged **before** duplicate/heap competitiveness checks, including losing rows | Long losing value exceeds logical value decode budget but is silently skipped because rank loses | U07, U08, U17 |
| INV-B2-04 | On B1 `NotAvailable` there is only legacy execution, beginning before enumeration | Partial ordinal heap mixed with a string-backed entry or an optional failure mapped to query error | U09, U10, I03 |
| INV-B2-05 | B1 codec/schema/metadata/guard/cancellation errors are never hidden as optional unavailability | Corrupt term or poisoned map silently switches to old mode | U11, U17, I03 |
| INV-B2-06 | Exact `total_hits`, score presence and IEEE-754 score bits, physical projection, duplicate detection and effective-live masks match legacy | New ordinal rank causes a different score, missed duplicate, projection from the wrong segment or a truncated hit count | U04, U06, U13, I01, I02 |
| INV-B2-07 | Heap and final top-K use a single consistent ordering for all retained entries; sort tuples of selected hits remain canonical owned strings | Heap and `into_sorted_vec` order disagree, `next_cursor` contains numeric ordinal instead of keyword | U05, U12, I02 |
| INV-B2-08 | No numeric cross-snapshot comparison: a new generation/refresh gets its own map; old PITs and cursors retain their view | A pre-append map used to sort new-segment docs or a cursor silently accepted on a different PIT | U12, I02 |
| INV-B2-09 | No per-candidate field-name/schema lookup, term-string comparison or owned keyword string for **Single losing candidates**; a field is bound once/segment | Hidden `sort_tuple_for_doc` or raw lexical compare runs for every normal Single candidate | U15, U16 |
| INV-B2-10 | All candidate budget, decoded-value charges, heap preflight/commit/release and cancellation remain bounded; no new unmetered variable-sized allocations | New vector/cache, early heap mutation on error, dropped reservation, silently raised limits | U07, U08, U13, U16, I04 |
| INV-B2-11 | One-element MultiOne of Single-cardinality Keyword retains existing logical decode/error behavior, and sorts by its single value | A MultiOne is normalized into a Single, bypasses its vector admission, or a losing MultiOne ignores a decode failure | U06–U08, I01 |
| INV-B2-12 | Cursor, batch, aggregation, typed, geo, JSON, relevance and unsupported shapes retain their previous path and exact results | B2 map initializes during a BatchQuery, MatchAll or a continuation query, or the cursor's sort atom changes | U09, U12, U18, I02 |
| INV-B2-13 | Source scope and benchmark provenance stay bounded: B1 binary/persistent bytes and all A4/A6 evidence unchanged; no B2 gain claim | Codec, stored/manifest bytes, benchmark configuration/results, old experiments or CI topology edited | Diff/CI G0/G9 |

Before implementation, write a short `INV-B2` worksheet linking each source symbol and at least one negative test to these invariants. Challenge missing, null, empty, Unicode, MultiOne, same-string/different-local-rank, many-segment, no-segment, K=1, K+1, legacy, resource-bound, corruption, cancellation, stale-cursor and after-error states. If current APIs cannot support a frozen behavior, apply decision X34 (HARD STOP), not an informal change of semantics.

---

## 4. Frozen architecture — one snapshot map, one global heap

### 4.1 Data flow and ownership

```text
UnifiedSearcher::search_impl
  -> validates query/sort/top_k/projection
  -> execute_unified verifies cursor binding and compiles plan
  -> collect_mixed
       [existing] open ALL ordered GuardedSegmentReader(s)
       [existing] schema check -> effective-live -> expansion -> compute_stats
       [NEW, only eligible] prepare_keyword_ordinals(field_id,&guards,cancel) ONCE
          Ready(Arc<SnapshotKeywordOrdinals>) ---> numeric path for WHOLE request
          NotAvailable(...) ---------------------> existing whole-request path
          Error -------------------------------> typed error (no retry)
       for each segment:
          [existing] ColumnAccess::open(reader) once
          [NEW, Ready only] bind KeywordSortOrdinalColumn once
          [NEW, Ready only] bind map.bind_segment(&guard) once
          [existing] evaluate_lexical_with(...) enumerates/validates/scorers
          for every matched effective-live doc:
             [existing] exact total_hits increment, existing doc key resolution
             [NEW, Ready only] read bounded local ordinal/state and translate
             [NEW, Ready only] compare shared numeric rank + key in same global heap
             [NEW, Ready only] own string sort tuple ONLY upon competitive admission
             [existing otherwise] borrowed/owned/typed candidate path unchanged
       [existing] heap.into_sorted_vec / K+1 truncation / cursor sort tuple
       [existing] physical projection/response and aggregate lifecycle
```

- The map is `Arc`-owned by the caller for the lifetime of `collect_mixed` and by its B1 snapshot cache; only `SegmentOrdinalMap<'_>` borrows it. Never retain references to temporary `ColumnReader` or `ColumnAccess`; the column handle borrows the immutable segment bytes owned by an admitted guard.
- Keep all original `GuardedSegmentReader`s alive for the entire search; no extra reader admission or second reader copy for preparation. **Do not call `Index::snapshot()` inside B2**: it returns another binding even if the committed generation is identical.
- Preparation is explicit and lazy, attempted only for eligible requests. The existing adapter `QuerySession` proves queries can reuse the same snapshot; B2 does not own a new cache or LRU.
- A B1 `Ready` result means every participating segment has a fully validated, version-2 ordinal column. Do not run a separate per-segment B2 availability scan or mix v1/v2 during ranking.

### 4.2 Private numeric sort key and exact comparator

In `crates/quervant-core/src/search/typed_compare.rs` add a **crate-private** (not public contract) representation:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum OrdinalSortKey {
    Missing,
    Null,
    Value(u64), // exact snapshot-wide rank from B1, not a segment-local ordinal
}
```

Define `pub(crate) fn ordinal_sort_key_cmp(a: OrdinalSortKey, b: OrdinalSortKey, direction: SortDirection, missing: MissingValuePosition) -> Ordering` by this **complete, frozen** table:

| Missing placement | Priority classes (first to last) | `Value(a)` vs `Value(b)` | Same class |
|---|---|---|---|
| First | Missing, Null, Value | `a.cmp(&b)` Asc; `b.cmp(&a)` Desc | Equal |
| Last | Value, Null, Missing | `a.cmp(&b)` Asc; `b.cmp(&a)` Desc | Equal |

`sort_field.direction` must **never** reverse missing/null class order. After equal numeric components, compare logical document keys using `a_key.as_str().as_bytes().cmp(b_key.as_str().as_bytes())`, always ascending. No locale normalization, hash-based rank, segment-index tie-break or score-based tie-break for explicit sorts.

Modify the existing private `MixedEntry<'a>` in `search/unified.rs` to include exactly one **inline** field:

```rust
ordinal_sort: Option<OrdinalSortKey>
```

Existing/legacy entry constructors initialize `None`; B2 entries initialize `Some(key)`. Its `Ord::cmp` must use `ordinal_sort_key_cmp` plus ascending logical-key bytes **iff both** are `Some`; otherwise preserve `compare_candidates` unchanged as a defensive canonical comparison. The B2 candidate builder **must separately reject** a mixed heap (`Some` with a retained `None`) using `SearchError::CorruptIndex { detail: "mixed ordinal and legacy sort entries" }` before mutating heap. No caller ever intentionally mixes modes. Leave `MixedEntry::Eq`, `heap_admit_candidate`, `d3c::State`, `SelectedHit`, score, and `sort_tuple: Vec<SortValue>` contracts intact. In particular, no new `SortValue` or `CursorAtom` variant is permitted.

**Accounting:** `ordinal_sort` is an inline fixed-size scalar, not a heap allocation. Keep the existing **logical** `candidate_charge` and heap preflight/release formula *exactly* for a retained `SelectedHit` (base + key + full owned sort-value semantics); do not charge a packed ordinal byte count in place of the logical owned keyword. The B1 map's retained memory is already governed by `MetadataBudget`. The inline field is not claimed to make this an exact-RSS model. If source inspection proves it introduces a new independent heap allocation or violates a documented candidate-charge invariant, STOP; do not silently exempt it.

### 4.3 New query-local bound ordinal sort accessor (no codec redesign)

B1 exposes `ColumnReader::bind_keyword_ordinals(field_id)`, but `KeywordOrdinalColumn::doc_ordinal` **does not apply** the old per-value `DecodeBudget::reserve_string` check. B2 must not skip that check for a losing Single candidate. Implement a *small crate-private query-local wrapper* in `segment/column.rs` (inside the same file as `ColumnReader` and `DecodeBudget`):

```rust
pub(crate) struct KeywordSortOrdinalColumn<'a> {
    column: KeywordOrdinalColumn<'a>,
    limits: SegmentLimits, // copy from the existing ColumnReader; no allocation
}

impl<'a> ColumnReader<'a> {
    pub(crate) fn bind_keyword_sort_ordinal(
        &self, field_id: u32
    ) -> SegmentResult<Option<KeywordSortOrdinalColumn<'a>>>;
}

impl KeywordSortOrdinalColumn<'_> {
    pub(crate) fn read_sort_row(&self, doc_id: u64)
        -> SegmentResult<KeywordOrdinalValue>;
    pub(crate) fn dictionary_term(&self, local_ordinal: u64)
        -> SegmentResult<&[u8]>;
}
```

Construction **only** wraps `bind_keyword_ordinals(field_id)?` and copies `self.limits`. No cached decoded values, second geometry or string owner. `read_sort_row` calls `self.column.doc_ordinal(doc_id)` **exactly once** and, for `Value{state:Single,ordinal}`, looks up the B1 validated raw term length and applies the **same** `DecodeBudget::new(&self.limits).reserve_string(term_len)` as existing `ColumnReader::keyword_sort_view` on an ordinal Single row. It returns the original `KeywordOrdinalValue`. For `Missing`/`Null`, it returns unchanged without allocating; for `MultiOne`, return the state unchanged—**the search candidate handler MUST run `sort_tuple_for_doc`/`ColumnReader::value` before any reject decision**, thereby preserving the distinct MultiOne entry/vector/string allocations and errors. A raw term that cannot be located is an authoritative `SegmentError`, not `NotAvailable`.

The dictionary bytes were validated for UTF-8 and order by the v2 reader-open trust boundary. B2 **does not** decode or UTF-8-validate them for every losing Single candidate. On competitive string materialization, `std::str::from_utf8(dictionary_term(...))` must still return a typed `SegmentError::InvalidUtf8 { context:"keyword" }` on an unexpected bad byte, never `unwrap`; `owned_keyword_sort_value(ColumnKeywordView::Value(...))` remains the existing fallible owned-string constructor. This is an optimization of already-verified access, **not** permission to skip full v2 validation at open or the logical per-candidate budget. Do not change B1's `KeywordOrdinalColumn` stored fields, on-disk format, public API, or `ColumnReader::keyword_sort_view` fallback.

Expose only this forwarding method in `search/typed_compare.rs::ColumnAccess<'a>`:

```rust
pub(crate) fn bind_keyword_sort_ordinal(
    &self, field_id: u32
) -> Result<Option<KeywordSortOrdinalColumn<'a>>, SegmentError>
```

For the `None` COLUMNS case return `Ok(None)`; an invalid `Ready`+`None` is handled as the specified `CorruptIndex` by `collect_mixed`. The handle must outlive only its segment loop and be bound once. No field-name search inside `read_sort_row` or `SegmentOrdinalMap::translate`.

### 4.4 Candidate processing and materialization — full decision table

Create one private `consider_ordinal_keyword_candidate(...) -> SearchResult<()>` in `search/unified.rs`. It receives existing `request`, `columns`, `schema`, `field_id`, `segment_index`, `doc_id`, `key`, `score`, `include_score`, `bound: &KeywordSortOrdinalColumn`, `translation: &SegmentOrdinalMap`, `heap`, `heap_limit`, `CandidateBudget`, `scope`, `d3c::State`; do not add a new heap or duplicate-policy state. The following order is mandatory for **every** matched candidate (including noncompetitive candidates):

1. The *existing* caller increments exact `total_hits`, resolves the same key and score before entering the new handler. Do not change the order of lexical/typed validation, scoring, match enumeration, key decoding or cancellation.
2. `row = bound.read_sort_row(doc_id)?`: one numeric row lookup; for Single this performs the old logical string budget check; for MultiOne it identifies the shape without claiming it is a Single.
3. Convert row to `OrdinalSortKey`: `Missing -> Missing`, `Null -> Null`, `Value{ordinal,..} -> Value(translation.translate(ordinal)?)`. The map is bound to this segment once, never compared using the un-translated `ordinal`.
4. Compute the **legacy-equivalent logical candidate charge** *before* duplicate and heap decisions. For `Missing/Null`: checked `64 + key.len() + 32`. For Single: checked `64 + key.len() + 32 + (term_len + 4)` (the same units as `borrowed_keyword_candidate_charge`). Preserve `SearchError::ResourceLimit` overflow mapping. For MultiOne: call the existing `sort_tuple_for_doc(columns,schema,&request.sort,None,doc_id)?` **before** any competitive/duplicate decision and derive its charge through `candidate_charge` on a temporary existing-shaped `SelectedHit`. This intentionally retains legacy allocations/errors on MultiOne losers; do not optimize away their vector or scalar string decoding under B2.
5. Run `experiment.check(heap,&key)?` **in the same place as the old borrowed handler**. Do not skip duplicate verification for a numeric-losing candidate. Check that each existing heap entry has `ordinal_sort=Some(_)` before any numeric comparison; if not, return the frozen mixed-heap `CorruptIndex` without modifying the heap.
6. If `heap.len() >= K+1`, compare the candidate's **numeric** `OrdinalSortKey` with `heap.peek()`'s stored numeric key using §4.2; when equal, apply ascending document-key byte order. If not strictly better, return without constructing any owned string **for Single/Missing/Null**; MultiOne's earlier owned decode remains intentional. Existing duplicate check and logical value budget must already have executed.
7. If the heap has room or candidate is better, construct a normal **owned, one-element `sort_tuple`**: Missing → `SortValue::Missing`, Null → `SortValue::Null`, Single → borrow dictionary term and use `owned_keyword_sort_value(&ColumnKeywordView::Value(...))?`, MultiOne → consume the already-decoded legacy tuple. Construct `SelectedHit` with the original score presence/physical identity/key, then `MixedEntry { ordinal_sort:Some(numeric_key), sort:&request.sort, relevance:false, charge, hit }`. In `cfg(test)`, prove `candidate_charge(&hit) == precomputed_charge` for Single/Missing/Null. On MultiOne, the existing `candidate_charge` is authoritative.
8. Call **existing** `experiment.admit(entry,heap,heap_limit,budget,scope)`; it owns the existing preflight, heap replacement, accounting/release and duplicate-strategy transitions. Do not separately push/pop heap or bypass `d3c::State`.

A `MultiOne` in a single-cardinality column is **not** silently treated as `Single` for output or decode budgets. Its one value has the same lexical ordering as a Single value, so the numeric rank itself is valid. Its materialization/error sequence stays on the old owned route. If an unexpected `FieldValues` shape appears, return `SearchError::CorruptIndex { detail: "keyword ordinal MultiOne decoded an unexpected value shape".to_owned() }` before heap mutation; never silently convert it or turn it into Missing.

### 4.5 Collector integration — precise change points

1. Keep `search_impl` and `execute_unified` entry validation, cursor check, compilation and projection unchanged.
2. Keep `keyword_sort_late_eligible` for the existing borrowed fast path. Add a *narrow* B2 eligibility wrapper calling that predicate plus `sort.fields[0].multi.is_none()`; do not broaden beyond strict root term, standalone, no cursor, no aggregation. Test the two predicates separately.
3. In `collect_mixed`, preserve all existing guard and schema acquisition and work-meter setup. **After the existing expansion/stats setup and before the first segment is processed**, call `self.snapshot.prepare_keyword_ordinals(field_id,&guards,cancel)` at most once **only** for eligible requests; use a local `Option<Arc<SnapshotKeywordOrdinals>>` as mode. Map `IndexError::Cancelled` to `SearchError::Cancelled`; other `IndexError` to `SearchError::Index`. A `NotAvailable` sets mode to legacy **without** any B2 entry added. Do not prepare during ineligible requests.
4. Inside each segment loop and after the existing `ColumnAccess::open(reader)`, if mode is Ready, bind `columns.bind_keyword_sort_ordinal(field_id)?` and `map.bind_segment(&guards[segment_index])?` **once**, preserving their borrow lifetimes for the segment's scored-document loop. If `None` for a Ready map, return the exact typed internal error before processing this segment.
5. In the existing `for (doc_id,score) in scored` loop, check the ordinal mode **before** `keyword_field_id`'s borrowed handler, and call `consider_ordinal_keyword_candidate`. Other requests continue to the existing borrowed and owned/typed branches, untouched. `total_hits`, key retrieval, score bits and other `scored` logic stay in the same order.
6. `MixedEntry::Ord` selects numeric vs existing comparator as §4.2 specifies. The original `heap.into_sorted_vec`, K+1 cursor construction, projection and response logic are byte-for-byte semantically unchanged. Every B2 competitive entry already owns its string-valued tuple, so `cursor.last_sort` cannot contain numeric ranks.
7. Avoid changing the `UnifiedCursor`, public PIT `CursorContinuationV1`, `TopKDuplicateConfig`, `CandidateBudget`/`MemoryCharge`, `SearchWork`, generic `sort_tuple_for_doc`, `sort_value_cmp`, or any B1 map code. Keep the B1 cache's `NotAvailable` stickiness and map lifetime as-is.
8. No per-segment Top-K harvest or new cross-segment merge stage. The **existing single global heap** already performs the exact merge when its comparator sees shared ordinals. This is deliberate.

### 4.6 Negative-case handling and error timing

- B1 v2 parser has already checked **every** dictionary term, state, ordinal, offsets, version and required feature when opening a segment, including unselected rows. B2 must preserve that parser and all corrupted-container tests.
- Still perform logical per-value decode-budget admission on **every matched candidate**, not only winners. A losing value with e.g. 80 UTF-8 bytes and a 79-byte decode limit must return the same typed `LimitExceeded { limit:79, requested:80 }` as the existing borrowed/owned path, before competitive discard. For MultiOne preserve entry/FieldValue vector/string check order.
- On a competitive Single, `owned_keyword_sort_value` uses the existing fallible copy and errors before `experiment.admit`; heap and duplicate state must remain unchanged if copying fails. No conversion of allocation failure into a silent fallback or a partial response.
- B1 map preparation may encounter an existing schema/corruption/cancellation error: preserve the corresponding typed result and fail the request, no fallback. A cancellation from the preparation wrapper maps to `SearchError::Cancelled`, matching existing search cancellation.
- A cancelled request must not lose an already published B1 map (B1's post-publication rule), and a cancelled waiter must not block another query using that snapshot.
- No new early termination: `evaluate_lexical_with` still evaluates every required candidate/leaf and `total_hits` remains exact even if the heap is full.

---
## 5. Deterministic reference corpus and independent oracles

### 5.1 Reuse the actual B1 corpus; do not invent another semantic model

For local integration, reuse `crates/quervant-core/tests/perf06_b1_common/mod.rs` as a **test-only input oracle**, **without modifying that frozen fixture file**. Its established schema has `body` (`Text` indexed/stored), `city` (single cardinality Keyword, columnar), `category`, `n`, `stored_tag`, and multi-valued `tags`; the first 18 documents occupy three immutable segments (six per batch), and `GLOBAL_CITY_ORDER` is:

```text
[ "", "\0", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀" ]
```

Use `Query::Term { field: "body".to_owned(), value: FieldValue::Text("common".to_owned()) }` (one analyzed term) as the eligible logical query; `Query::And(vec![the_same_Term])` is the **semantically equivalent ineligible reference**. That is the same structural fallback already used for PR 15H-B tests. Use `Sort::new(vec![SortField::new("city", direction)])` with both missing placements. Expected keys/order, complete six-field projection, values, local dictionaries, and shared ordinal ranks are derived from the B1 **literal input table**, not from production comparator or map output.

For every comparison run, demand simultaneously:

- `total_hits == 18`; exact ordered keys for **both** ASC and DESC and MissingFirst/Last; distinct missing and null order; no duplicate hit keys;
- full projected `(field_name, FieldValues)` tuples in canonical order from B1's `expected_projected_fields(key)`;
- score-presence parity and **`score.to_bits()`** equality for every corresponding hit (no scoring change);
- correct response generation and view ordinal; first-page `next_cursor` contains the existing **owned string sort tuple**, never a numeric ordinal;
- one and the same snapshot binding is used for B1 preparation and every guard and map translation.

**Additional B2-specific counterexample:** two segments where local ordinal `0` means different strings (`Austin` vs `Boston`), plus a repeated `Seattle` assigned **different local ordinals** in the two segment dictionaries. Confirm the B1 map translates them to one shared rank and the B2 heap uses that rank, not the raw local ordinals. Derive expected order directly from `Vec<u8>`-byte comparisons, with tie-breaking by raw logical-key bytes.

### 5.2 Fresh deterministic generated corpus (64 cases, fixed seed)

In unit tests under `search/unified.rs`, use a test-only `xorshift64` PRNG seeded with **`0xB2_06_20_26_00_00_0001u64`**, and exactly 64 cases. For case `i`, use `segments=1+(i % 5)`, up to 24 docs per segment, `top_k` chosen from `[1,2,5,10,20]` (clamp only if `TopK` requires a lower bound), and raw keyword values from `""`, `"\0"`, `"A"`, `"a"`, `"aa"`, `"Austin"`, `"Boston"`, `"Seattle"`, `"e\u{301}"`, `"é"`, `"😀"`, a shared-prefix pair, Missing, Null and occasional MultiOne. Keep all doc keys unique and deterministic. Every case has the same indexed `body=common` logical query and the same query schema across segments.

The **oracle is independent**: create test-only `(key, raw bytes or explicit state, category)` rows directly from the generator before passing them to Quervant, and use ordinary `Vec::sort_by` with (class rank, raw byte comparison adjusted for Desc, key bytes ascending) to compute order. Never call `ordinal_sort_key_cmp`, B1 translator, `compare_candidates`, or the production heap to derive expected results. Execute four direction/missing combinations and compare to a generic legacy query fallback; compare score bits, counts and projection. Persist seed and a failing case number in the test failure message. Do not introduce `proptest`, external fixtures or a new dependency.

### 5.3 MultiOne and resource-exception corpus

Use an eligible **single-cardinality Keyword** schema with a real row whose logical `FieldValues` is `Multi(vec![Keyword("Austin")])`; compare to Single("Austin"), Missing, Null and a longer ordinary Single competitor. The B1 local ordinal state must remain `MultiOne`; B2 must value-sort by its one actual string but preserve its **MultiOne full decode** on every matched candidate. Include the frozen B1 80-byte keyword cases:

- Section decode budget **80**: Single and permitted MultiOne logically succeed when other limits allow.
- Section decode budget **79**: a matched **losing** Single of length 80 returns `SearchError::Segment(SegmentError::LimitExceeded { limit:79, requested:80 })` before the candidate can be discarded; no success response.
- For MultiOne, a single-allocation cap one below `size_of::<FieldValue>()` must fail at the **vector check** before string-copy admission; do not combine vector and string budgets.
- Missing/null/empty-string must remain distinct: a zero-length term has a *real* `Value(shared_rank)` not `Missing` or `Null`.

Construct/open all codec fixtures under ordinarily permissive limits first when necessary, then exercise selected value-access limits using the existing `ColumnReader`/`SegmentLimits` unit interfaces. Never fabricate corrupt committed bytes without rebuilding a valid outer container checksum/envelope if the test asserts a public `Index` failure.

---

## 6. Required tests — precise matrix and assertions (G2–G6)

**Test presence is not test execution.** Implement the following named groups as actual Rust tests and record command/output. For each group the production path and reference oracle must be explicit; a mock map or a second copy of the production comparator does not count as the primary proof. Use `b2_uNN_...` for unit tests and `b2_iNN_...` for integration tests. One test may demonstrate several adjacent assertions but every row must have traceable evidence.

### 6.1 Comparator, candidate and dispatch unit tests (`#[cfg(test)]`)

| ID | Exact case(s) | Mandatory acceptance witness |
|---|---|---|
| **B2-U01** | Numeric `Missing`, `Null`, `Value(0)`, `Value(1)`, `Value(2)` in all 4 direction/placement combinations | Every pair equals **independent `sort_value_cmp`** on synthetic Keyword values with matching lexical rank; `Desc` reverses values only. |
| **B2-U02** | Raw bytes `""`, NUL, ASCII case, prefix, composed/decomposed Unicode, emoji | Independent byte oracle equals ordinal comparator, no Unicode normalization, no sentinel collision. |
| **B2-U03** | Two or three dictionaries with equal local ordinal but different term, and same term with different local ordinal | B1 translation yields one exact shared numeric order; B2 candidate comparison never uses local ordinal un-translated. |
| **B2-U04** | Empty/singleton/many matches; TopK K=1,2,10,100; exactly K/K+1; 3 segments; `total_hits > K` | Complete count, stable order and K+1 truncation/cursor tuple; identical to generic reference. |
| **B2-U05** | Equal shared ordinal across segments, differing document keys | Always compare key bytes ascending for ties, independent of direction and segment order. |
| **B2-U06** | One-element MultiOne within schema Single and matching Single term | Same lexical rank; original shape survives in `ColumnReader::value`; both winning and losing MultiOne use old full owned-decoder path, with exact score/order. |
| **B2-U07** | Single loser with 80-byte term under decode budget79; allowed80; MultiOne vector-bytes−1 | Identical `SegmentError::LimitExceeded` type/units and validation order; not silently skipped by numeric heap. |
| **B2-U08** | Competitor would replace worst but **existing candidate-budget preflight** fails at an exact bound (deterministic). Independently inspect the existing owned-string `try_reserve_exact` error-before-admit path. | Heap retained keys/charges and duplicate-policy state unchanged; no partial response. Do not invent a new allocator fault hook or claim a process-OOM test executed. |
| **B2-U09** | Eligibility table: no sort, multi field, nonkeyword, `multi` selector, JSON, geo, multi-sort, batch, aggregations, nonstrict term, `after` | Map prep counter stays zero; existing path runs and produces same results. |
| **B2-U10** | Real `LegacySegment` via frozen v1 fixture; `NotAvailable(Allocation)` via the pure private preparation-dispatch helper (construct the public `KeywordOrdinalPreparation::NotAvailable` variant in unit test) | Complete generic fallback **before** candidate processing; outcomes equal reference on real legacy data, no erroneous SearchError or partial ordinal heap; no new retry loop. |
| **B2-U11** | `Allocation`/`ResourceBudget`/`UnsupportedField` via the same pure private dispatch classifier, plus B1’s already-executed bounded-map tests | Every optional reason maps to legacy mode; no artificial map owner, no attempt to access B1’s private allocation-fault seam from a sibling Rust module. A real running query must demonstrate `LegacySegment` fallback; resource-limited snapshot may be tested only with a source-proven admission fixture, not guessed limits. |
| **B2-U12** | Entry/mid-preparation/ready-cache cancellation, B1 schema mismatch/corruption/poison | `IndexError::Cancelled -> SearchError::Cancelled`; authoritative other errors remain typed `SearchError::Index`/`Segment`; no fallback or map invalidation. |
| **B2-U13** | 64 generated deterministic cases (§5.2) | Exact independently sorted keys, `total_hits`, score bit patterns, projections and equality against ineligible generic query for all direction/missing/K cases. |
| **B2-U14** | Check all `MixedEntry` old constructors in all feature configurations and new ordinal constructor | Old entries have `ordinal_sort=None`; B2 ones `Some`; mixed unexpected heap rejected *before* mutation; `Ord` remains canonical and total. |
| **B2-U15** | Test-only per-query structural counters under `#[cfg(test)]` | One preparation attempt/eligible request, zero for ineligible; one bound local ordinal accessor per segment; no name lookup or string compare in numeric ranking; no term-string-owned copy for Single losers. |
| **B2-U16** | 1,000+ matched docs, K=10 and100, ascending input with no replacements; then adversarial descending input | For ascending case, owned Single strings <= K+1; for descending case, copies equal *actual competitive admissions* (not M); all M candidates still counted/validated. Retained charge equals canonical logical tuple charge. |
| **B2-U17** | Corrupted v2 term, state, offset and numeric rank in an otherwise valid outer container; losing malformed candidate | Reader fails at authoritative validation boundary or original typed error; no `NotAvailable` downgrade. Preserve B1 U05/U06/I07 evidence. |
| **B2-U18** | `d3c::State` Linear/Prefilter/ExactSet tests, duplicate retained keys and replacement | No bypass of `experiment.check` or `admit`; actual old strategy behavior and accounting still hold. Reuse `pr15i` regression without reviving rejected experiments. |
| **B2-U19** | Same `ReaderSnapshot` reused for repeated requests; two distinct snapshot objects at same generation; held PIT after append | Map reuse within same snapshot only; no cross-snapshot/shared-rank mix. No `Index::snapshot()` call added per query. |
| **B2-U20** | Single-segment identity; all absent/null; empty snapshot | Identity returns correct values; no heap merge/extra strings; empty has the old result, no error. |
| **B2-U21** | Numeric field id bound once per segment, and `KeywordSortOrdinalColumn::read_sort_row` | One B1 `doc_ordinal` per matched Single, one logical string budget check, no per-row metadata field search and no term ownership until retained. |
| **B2-U22** | Exact old `candidate_charge` for Single, missing, null, MultiOne and two heap ownership branches | The charged owned tuple stays the reference formula; extra numeric state is inline only, no separate allocation or uncharged map. |
| **B2-U23** | Cursor fingerprint mismatch, foreign PIT and wrong sort | Existing cursor error precedence remains before map preparation; no numeric cursor payload. |
| **B2-U24** | `BatchQuery` strict-term sort, aggregation, typed predicates, JSON-path sort, geo sort, relevance | Existing behavior and output unchanged; ordinal map not initialized by B2 for these shapes. |

**Private optional-outcome dispatcher for testability:** Implement `fn ordinal_ready_from_preparation(prep: KeywordOrdinalPreparation) -> Option<Arc<SnapshotKeywordOrdinals>>` in `search/unified.rs`, returning `Some(owner)` only for `Ready` and `None` for all four `NotAvailable` reasons. This helper is used in actual collector dispatch and is directly unit-tested with constructed `KeywordOrdinalPreparation::NotAvailable(...)` values. Do not reach into `index::keyword_ordinals` private `cfg(test)` fault seams, modify `index/mod.rs` visibility, or construct a fabricated `Ready` map. An actual fallback is separately proven by the genuine legacy fixture.

**Structural test-only instrumentation, strictly scoped:** Add a private `#[cfg(test)]` module `b2_observation` in `unified.rs` recording (`eligible_requests`, `map_preparations`, `ready_uses`, `optional_fallbacks`, `bound_columns`, `numeric_candidates`, `numeric_compares`, `owned_single_strings`, `multi_one_legacy_decodes`, `single_rejected_without_copy`). Increment counters only in the corresponding `#[cfg(test)]` blocks; release/normal library source contains no diagnostic atomic, timer, per-candidate log or fault configuration. Existing PR 15H-B `b_observation` keeps its original meaning for the **legacy borrowed** path. If old tests assumed every keyword request used that path, update only those tests' instrumentation expectations to reflect the new explicit B2 path; never delete their actual result/error assertions, or fake an old counter increment for a new algorithm. Keep a differential test that specifically exercises a genuine v1 legacy borrowed path.

### 6.2 End-to-end local integration (`crates/quervant-core/tests/perf06_b2_ordinals.rs` — NEW)

Use real public `Index`, `IndexWriter`, `FsDirectory`, `ReaderSnapshot`, `UnifiedSearcher`, `Index::pin`, `Query::Term`, `Query::And`, projection, and existing PIT/cursor APIs. Reuse B1 test `perf06_b1_common` directly if feasible; do not change the frozen corpus table or historical package. Never substitute a fake QueryEvaluator for the real B2 execution path.

| ID | Topology and steps | Mandatory acceptance |
|---|---|---|
| **B2-I01** | Write/commit B1's 18-row, three-segment corpus in real `FsDirectory`, drop writer and reopen. Query strict single body term with city ASC/DESC × missing First/Last × K=1,5,10,18. | Exact 18 `total_hits`; all expected keys/order, field projections, score bits vs `Query::And([Term])`; same city across segments and conflicting local ordinals verified through B1 mapping. |
| **B2-I02** | On one PIT-owned snapshot, execute page K=5 first with B2, then continue with original string-backed cursor path (5,5,5,3). Repeat ASC and DESC; wrong PIT/wrong sort/expired cursor. | Concatenated pages equal full independently sorted 18 keys, no repeats/misses, final `next_cursor=None`; cursor keyword value is owned string; exact negative errors. Do not invoke `after=None` again after exhaustion. |
| **B2-I03** | Copy B1 genuine pre-B1 fixture (`tests/fixtures/index/perf06_b1_columns_v1`) into a fresh disposable FsDirectory. Run strict-term query on g3 (v1), append two documents to g4 mixed v1/v2, compact to g5 all-v2 and re-query. | g3/g4 fall back to legacy and retain full result/score/projection; g5 can rank numerically; every immutable old object remains untouched; full 18/20-row input oracle; no fixture regeneration. No remote compaction. |
| **B2-I04** | Hold g3 PIT, append Chicago under g4, delete Boston under g5, compact under g6 using existing APIs. Keep previously held PITs alive. | Old snapshot uses old shared ranks and results; new snapshot renumbers appropriately; new/old query results and score bits match logical visibility; deleted-only physical dictionary does not imply a live hit. |
| **B2-I05** | One-segment index, all-empty/absent/null corpus, zero-segment index and one-element MultiOne corpus | Results exact, no rank/null sentinel collision; local identity mapping; fallback for unsupported shape; MultiOne keeps exact value and logical error conditions. |
| **B2-I06** | Real `FsDirectory` with both an eligible Keyword sort and unchanged numeric/JSON/geo/multi-value fields; run ineligible Boolean/typed/JSON/geo/relevance and public batch aggregate paths. | All unaffected outputs and budgets equal established oracles; no new query shape acquires a B2 map. Use existing test helpers from `pr14_*`, B1 and `pr15h_b` rather than duplicate entire suites. |
| **B2-I07** | Long value in later, noncompetitive candidate and exact-limits single-Keyword fixture; simulate corrupt unselected v2 value by reconstructing the full container as B1 does. | Even losing candidate returns same typed resource error; corrupt container refused before numeric selection; index generation and immutable data remain intact. |
| **B2-I08** | Run one *untimed* synthetic Quervant adapter contract test and inspect its `QuerySession` source; no new benchmark index/result config. | `cargo +1.98.1 test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml query_session_constructs_exactly_one_snapshot_for_the_whole_session`; one-snapshot-per-session reuse; no actual timing campaign or performance claim. |

For B2-I01/I02, derive expected orders from literal B1 corpus fields rather than the fallback's own output; the fallback is a **second independent execution-path comparison**, not the only oracle. For B2-I03 use existing B1 child-process/fixture provenance code **without editing the B1 fixture package**; the B2 integration must still execute its own g3/g4/g5 query assertions. For B2-I07 use the correct `SegmentLimits` values (80/79) to distinguish per-candidate logical admission from container-read acceptance; never adjust limits after a failing test merely to get green.

### 6.3 Real RustFS, CI and provider boundary

**No new remote publication or reader contract is introduced in B2.** Existing remote-backed indexes materialize verified segment bytes and pass an ordinary `ReaderSnapshot` to the **same** `UnifiedSearcher`. Do not add a new ignored RustFS B2 test or start a local RustFS service merely to satisfy a checklist. The ordinary repository CI already runs the real pinned RustFS integration suites, including B1-R01; retain them unchanged. If source inspection reveals B2 must change `remote/`, `objectstore/`, CI RustFS topology, or callback semantics, **HARD STOP X29** and request a separately approved real-topology design. Remote compaction publication remains the A6 residual and is not qualified by B2.

At final acceptance, require actual passing CI `rustfs` job for the final executable source, and actual execution of the repository's existing real-RustFS tests; a mock success or a green unrelated historic run is not a substitute. Source-specific B2 execution is independently established by B2-I01–I07 over `FsDirectory` plus `MemoryDirectory` where useful. Host stability/idle probes are **advisory only** and not a correctness blocker.

### 6.4 Failure classification and test provenance

Every failing gate must be classified before closeout: **introduced B2 regression**, **B2 implementation defect**, **deterministic pre-existing failure** (with exact baseline reproduction/evidence, not a guess), **nondeterministic failure** (with concrete nondeterminism), or **environment/harness failure**. Save source SHA, exact command, test name, argument flags, error category, and log. Do not delete negative evidence, selectively rerun for luck, weaken expected values, raise limits, add an `ignore`, or call an unexecuted test PASS. When the failure is within the frozen algorithm, fix narrowly and rerun affected tests; when it requires a new design, STOP.

---
## 7. Preauthorized Architectural Decisions and Exception-Handling Matrix (mandatory)

**The agent MUST apply this matrix, not design a replacement.** Every row states an exact trigger, category, *only* authorized action, prohibited action, proof/gate, and owner. Priority when several apply: `HARD STOP` > `DEFER AND CONTINUE` > `AUTO-RESOLVE`. An unlisted condition is **HARD STOP** (X40) under the maintainer's instruction, even if the generic guide would permit broader discretion. Source-level preconditions must be observed before applying an AUTO rule. Record each exercised row and evidence in the B2 report.

| ID | Observable condition / trigger | Category | Only authorized action | Prohibited action | Proof, affected gate, owner |
|---|---|---|---|---|---|
| **X01** | PR #126 not actually merged/accepted, accepted B1 source missing, or `main` still A6 | **HARD STOP production start** | Record exact GitHub state, `main` SHA, source comparison; produce/retain planning notes only | Self-merge/cherry-pick B1, implement on F2 branch, assert fictitious merge SHA | G0; maintainer |
| **X02** | Accepted main already contains a B2 collector or later changes in search files | **HARD STOP** | Identify actual symbols/delta; request updated B2 source design | Overwrite or duplicate working collector | G0/G1; maintainer |
| **X03** | B1 merged via squash; exact critical executable blobs match F2 head | **AUTO-RESOLVE** | Record blob-by-blob proof and actual post-merge SHA; proceed from `origin/main` | Require ancestry when a byte-equivalent squash exists; invent SHA | G0; agent |
| **X04** | Extra merged production differences vs reviewed B1 API/semantics | **HARD STOP** | Provide exact path/blob/symbol and impact | Infer compatibility from old plan | G0; maintainer |
| **X05** | Dirty worktree/foreign changes before branch creation | **HARD STOP mutation** | Stop, report exact paths; safe read-only inspection may continue | Stash/reset/clean unrelated work | G0; repository owner |
| **X06** | Request meets all §2.1 conditions and B1 `Ready` | **AUTO-RESOLVE** | Bind once/segment; process entire request in numeric mode | Per-segment heap, mixed modes, permanent rank assumption | U03/I01; G2/G3; agent |
| **X07** | No segments | **AUTO-RESOLVE** | Old empty-snapshot result, no ordinal preparation | New error or forced `Ready` map | U20; G3; agent |
| **X08** | One segment, B1 `Ready(Identity)` | **AUTO-RESOLVE** | Use same numeric code with B1 identity map, no extra translator allocation | Special unverified branch or duplicate dictionary copy | U20; G3; agent |
| **X09** | B1 `NotAvailable(LegacySegment)` | **AUTO-RESOLVE** | Whole-request existing path; old format remains readable | On-demand document scan/legacy rewrite or partial ordinal heap | U10/I03; G3/G5; agent |
| **X10** | B1 `NotAvailable(ResourceBudget)` | **AUTO-RESOLVE** | Whole-request existing path; leave B1 sticky state | Raise metadata cap, allocate unbounded map, retry with alternate limits | U11; G3; agent |
| **X11** | B1 `NotAvailable(Allocation)` | **AUTO-RESOLVE** | Whole-request existing path; leave B1 sticky state | Treat optional map failure as query failure or retry for a successful run | U10; G3; agent |
| **X12** | B1 `NotAvailable(UnsupportedField)` | **AUTO-RESOLVE** | Whole-request existing path without runtime query-shape expansion | Invent new global field registry or infer missing ID | U11; G3; agent |
| **X13** | Map `IndexError::Cancelled` | **AUTO-RESOLVE** | Propagate **SearchError::Cancelled** and keep B1 publication semantics | Swallow, repeat preparation or downgrade to fallback | U12; G3; agent |
| **X14** | Map corruption/schema/poison error | **AUTO-RESOLVE** | Propagate existing typed `SearchError::Index` / `Segment` | Return `NotAvailable` or skip bad segment | U12/U17; G3/G4; agent |
| **X15** | B1 `Ready` but ordinal accessor missing or incompatible | **AUTO-RESOLVE error** | Return exact `CorruptIndex("ready keyword ordinal map has no matching segment column")` | Start mixed heap or silently switch to legacy mid-request | U14; G3; agent |
| **X16** | Numeric local ordinal out of bounds / map bind mismatch | **AUTO-RESOLVE error** | Propagate authoritative typed error | Treat as Missing/Null, ignore row or rebuild mapping | U17; G3; agent |
| **X17** | Candidate row `Missing` or `Null` | **AUTO-RESOLVE** | Preserve distinct numeric sort class, class comparison, canonical logical charge | Use ordinal sentinel or reverse class on Desc | U01/U20; G2; agent |
| **X18** | Candidate row `Single` | **AUTO-RESOLVE** | `read_sort_row` checks old logical string budget; translate ordinal; own string only upon competitiveness | Skip budget, compare raw strings in numeric heap, own losing strings | U07/U15; G2/G4; agent |
| **X19** | Candidate row `MultiOne` on Single-cardinality schema | **AUTO-RESOLVE** | Run full original `sort_tuple_for_doc` before reject, retain old allocation/error order, compare shared rank | Silently treat as Single for resource checks or bypass legacy one-member decode | U06/U07; G3/G4; agent |
| **X20** | `Value` versus `Value`, direction Desc | **AUTO-RESOLVE** | Reverse only the two numeric value ranks | Reverse Missing/Null positions or keys | U01; G2; agent |
| **X21** | Equal shared rank across segments | **AUTO-RESOLVE** | Compare full logical key ascending raw bytes | Compare segment/doc physical ID, score, or local ordinal | U05/I01; G2; agent |
| **X22** | Request has `after`, public PIT cursor, batch, aggregate, nonstrict query, JSON/geo, or multi-sort | **AUTO-RESOLVE** | Retain existing path and errors, never initialize B2 map for this shape | New cursor format, broader planner, hidden map work | U09/U23/U24; G3/G5; agent |
| **X23** | Candidate is noncompetitive under numeric comparator | **AUTO-RESOLVE** | Run prior validation/duplicate check; reject Single without owned tuple, retain old MultiOne allocation obligations | Skip full match count, skip corruption/logical admission/duplicate check | U07/U16; G3; agent |
| **X24** | Competitive candidate fails owned string allocation | **AUTO-RESOLVE error** | Return original `ResourceLimit` before heap mutation; retain original heap/duplicate state | Partial admit/release error or silent fallback | U08; G3/G4; agent |
| **X25** | Heap contains a `None` entry while ordinal mode is active | **AUTO-RESOLVE error** | Return exact mixed-heap `CorruptIndex` before mutation | Approximate mixed comparison, clear heap or restart query | U14; G3; agent |
| **X26** | Existing `MixedEntry` constructors/feature-specific tests after adding inline field | **AUTO-RESOLVE** | Initialize all legacy constructors to `None`, B2 constructors to `Some`, preserve old Ord path | Remove test cases or default to fake value rank | U14; G4; agent |
| **X27** | Cursor first page contains B2 entries; next page uses canonical old path | **AUTO-RESOLVE** | Build cursor from existing owned `SortValue` and keep exact snapshot/fingerprint validation | Serialize rank, bind new snapshot, fabricate last_sort | U23/I02; G5; agent |
| **X28** | Score, total-hits, matching or duplicate code appears avoidable | **DEFER AND CONTINUE** | Record potential C/B3 future opportunity, continue only B2 | Optimize evaluator, shrink full-match vectors, change BM25 or duplicate policy | Scope/G9; future maintainer |
| **X29** | Remote/objectstore/manifest or new RustFS topology needed to implement B2 | **HARD STOP affected work** | Report source dependency and smallest architecture amendment; continue independent local tests if safe | Modify remote publication or CI topology autonomously | G1/G6; maintainer |
| **X30** | Host load/stability probe missing, noisy or not observed | **AUTO-RESOLVE** | Record advisory and proceed with correctness tests | Block correct tests or claim host-caused result | Advisory/G7; agent |
| **X31** | B2 planned raw Unicode comparison conflicts with verified canonical bytes | **HARD STOP** | State exact contract mismatch; request decision | Normalize/case-fold or select hash order | G1/G2; maintainer |
| **X32** | Invalid v2 data/codecs cause old integrity error | **AUTO-RESOLVE** | Preserve failing typed error, add targeted regression | Adjust test to `.is_err()` or hide error in fallback | U17; G4; agent |
| **X33** | Introduced compiler/test failure within frozen symbols and allowlist | **AUTO-RESOLVE** | Diagnose narrowly, correct, execute red/green, log source SHA | Redesign or weaken contract, blanket retry unrelated tests | G4/G7; agent |
| **X34** | Requirement cannot be satisfied with allowed source/API without changing existing semantic/resource contract | **HARD STOP affected work** | Report exact source, counterexample, desired vs actual, limited options/impact | New API/budget/cache, unapproved semantic waiver or speculative refactor | G1/G2; maintainer |
| **X35** | Need to change Cargo/toolchain, dependencies, nonallowed production path, unsafe code, benchmark harness/config/results or B1 fixture | **HARD STOP** | Preserve source and request separate approval | Self-expand allowlist or adjust baseline | G0/G9; maintainer |
| **X36** | Candidate budget/heap/duplicate invariant fails despite valid numeric order | **HARD STOP if no exact frozen repair** | Retain counterexample and request a bounded amendment; continue independent tests | Rewrite d3c/heap algorithm or raise limits | G3/G4; maintainer |
| **X37** | CI pending, unavailable or credentials unavailable, while local work is safe | **DEFER AND CONTINUE** | Finish source/tests/report; mark G8 BLOCKED/PENDING, exact job/head, no green claim | Manual dispatch, cancel/rerun green jobs, bypass CI | G8; infrastructure/maintainer |
| **X38** | RustFS CI failed in pre-existing unchanged provider tests | **DEFER AND CONTINUE** | Classify with exact logs and narrow baseline evidence; continue local safe work | Say pre-existing without proof, mock PASS, restart broad services | G6/G8; maintainer |
| **X39** | Only documentation/evidence changed after final tested executable/test/CI source | **AUTO-RESOLVE** | Compare exact protected blob sets, run diff-check; reuse source QA with dated provenance; still inspect actual final-head CI | Repeat all suites solely for prose or claim unobserved final CI | G7/G9; agent |
| **X40** | Unforeseen failure, new semantic decision, unsupported type/shape, or trigger not listed in this matrix | **HARD STOP** | Stop affected work and report smallest amendment; continue unrelated safe work only | Choose alternate implementation, coerce statuses or improvise | Affected gate; maintainer |
| **X41** | Real warm benchmark, profiling or cross-engine timing appears useful while coding | **DEFER AND CONTINUE** | Record candidate study question under B4; finish B2 correctness only | Acquire measurements, choose thresholds, adjust implementation based on unapproved timing | B4 handoff; maintainer |
| **X42** | Final CI indicates new source defect | **AUTO-RESOLVE only within frozen design** | Fix narrow source, run invalidated gates, create ordinary updated PR CI; retain negative evidence | CI bypass, blanket repeat, cherry-pick unrelated change | G7/G8; agent |
| **X43** | Test-only counters/hooks leak into normal executable build | **HARD STOP delivery** | Remove leak without changing behavior, rebuild affected gates; otherwise request amendment | Ship production instrumentation on benchmark hot path | G2/G7; maintainer if unresolved |
| **X44** | Authenticated GitHub access is unavailable after local source acceptance | **DEFER AND CONTINUE** | Complete locally, record local SHAs and blockers; no fabricated PR/CI state | Force push, remote assumption or automatic retry forever | G8/G9; infrastructure |
| **X45** | Retained winner charge/count differs from old canonical `candidate_charge` | **AUTO-RESOLVE for fixed bug** | Correct B2 temporary charge or tuple construction and add failing regression before admission; stop if new contract would be required | Change `CandidateBudget` formulas or omit physical string charge | U22; G3/G4; agent (escalate X34 if necessary) |

### Mandatory decision protocol

1. Verify the row's exact trigger and prerequisites. Use **only** its authorized response and capture the actual source/test/command evidence. The table is not a menu of alternative designs.
2. `AUTO-RESOLVE` means act and **continue**. `DEFER AND CONTINUE` means mark that dependent gate incomplete and continue all independent approved work; it does **not** permit approving the dependent decision. `HARD STOP` means stop affected work, protecting old source/data; if independent work cannot be isolated safely, stop the entire implementation.
3. When a gate fails, distinguish an introduced regression, feature defect, deterministic pre-existing failure, nondeterministic failure, or environment failure. A failure cannot be called pre-existing or flaky without evidence.
4. The maintainer owns architectural amendments, merge, G10, release, performance targets and future PR authorization. No agent may self-issue those approvals.

---

## 8. Ordered coding procedure — implement, do not design

| Phase | Exact authorized work | Exit evidence; continue automatically when satisfied |
|---|---|---|
| **P0 source** | Verify B1 merged/accepted, actual `main`/branch/source SHA, B1 F2 blob/API and guide, clean tree. Create new branch only when X01–X05 permit. | G0 proof, baseline assumed healthy (no baseline QA), planning hash/branch inventory. |
| **P1 correctness challenge** | Produce INV-B2 worksheet and negative-case matrix (§3/§5); check existing `MixedEntry` constructors, SortValue comparator, B1 APIs and cursor source. | G1 contracts and required test names traced; no unresolved design decision. |
| **P2 numeric comparator** | Add private `OrdinalSortKey`, exact comparator, add `MixedEntry.ordinal_sort`, initialize old constructors to None, add comparator tests U01/U02/U05/U14. | Red-first tests then green targeted `typed_compare` and heap tests. |
| **P3 bound logical accessor** | In `segment/column.rs`, add only `KeywordSortOrdinalColumn` wrapper and `read_sort_row`; forward from `ColumnAccess` in `typed_compare`. Preserve B1 public APIs and v1/v2 bytes. | Targeted Single/Missing/Null/MultiOne and 80/79 tests; no per-row name lookup. |
| **P4 one request-wide mode** | Add B2 eligibility and single B1 preparation in `collect_mixed` at frozen boundary; map optional outcomes to whole-request fallback; type-map genuine errors. Bind once per segment. | U09–U12/U19/U20, 1 prepare/eligible request, zero ineligible; no heap work before fallback. |
| **P5 numeric candidate** | Implement `consider_ordinal_keyword_candidate` and exact charge/competitiveness/owned materialization order; integrate through existing `experiment.check`/`admit`. | U03–U08/U13–U18/U21/U22; no loss of errors or score/count semantics. |
| **P6 lifecycle integration** | Add `tests/perf06_b2_ordinals.rs` with I01–I08, B1 frozen corpus, genuine v1 mixed fixture, PIT/cursor, append/delete/compaction, projection and fallback. | Actual local FsDirectory paths, full oracle, negative cases; no timing acquisition. |
| **P7 scoped QA** | Run §9.1 focused tests as needed, then final source-specific QA ledger §9.2 once. Resolve only X33/X42 narrow defects. | Actual passing QA, default+all-feature 85% line floor, test evidence on the committed executable source. |
| **P8 docs/delivery** | Add the B2 plan/report and a dated roadmap/architecture amendment; update source/test allowlist evidence, source SHAs and CI registration audit; push one cohesive B2 commit set and open **draft** B2 PR. | Correct diff inventory, report, tested source, remote head and PR identities. |
| **P9 CI/review** | Observe ordinary CI run for final executable source; no manual dispatch or benchmark. If terminal and green, record all jobs; otherwise precise BLOCKED/PENDING status. Perform final adversarial self-review. | G0–G9 PASS permits `READY_FOR_INDEPENDENT_REVIEW`; G10 maintainer-only. |

### 8.1 Implementation-source anchors that require no design discretion

- `crates/quervant-core/src/search/typed_compare.rs`: insert the private key/comparator next to `SortValue` and the forwarding method inside `ColumnAccess`; do **not** modify existing `sort_value_cmp` or the public `Sort` contract.
- `crates/quervant-core/src/segment/column.rs`: add the query-local private wrapper next to B1's `KeywordOrdinalColumn`, using existing `DecodeBudget`, B1 `dictionary_term`, `doc_ordinal` and `ColumnReader::limits`. No encoder, parser, writer or geometry changes.
- `crates/quervant-core/src/search/unified.rs`: extend `MixedEntry`, add the exact new eligibility and private candidate function, then wire mode/one per-segment bind in `collect_mixed`. Keep the `scored` enumeration, `d3c::State`, `heap_admit_candidate`, `candidate_charge`, cursor and projection routines unchanged.
- New integration test `crates/quervant-core/tests/perf06_b2_ordinals.rs`; private unit tests in the three edited Rust files. Reuse B1 test source module through a `#[path="perf06_b1_common/mod.rs"]`-style import **only if Rust's existing module convention requires it**; the existing `mod perf06_b1_common;` in adjacent B1 integration tests establishes the preferred source pattern.
- Do not modify producer `segment/build.rs`, `index/merge.rs`, `index/snapshot.rs`, `index/keyword_ordinals.rs`, `search/execute.rs`, `search/typed.rs`, or any adapter, regardless of possible future optimizations.

---
## 9. Verification commands, source identity, and CI (G4–G8)

### 9.1 Focused red/green checks during implementation

Run only when the named tests exist and their associated code has been written. Record failures and their correction; do not repeatedly run all suites between phases. All commands execute from repository root with the current source SHA and exact toolchain recorded:

```sh
# Private ordinal comparator, candidate, eligibility and correctness cases:
cargo +1.98.1 test -p quervant-core --lib b2_ -- --test-threads=1

# Real local public Index/ReaderSnapshot/UnifiedSearcher end-to-end:
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals -- --test-threads=1

# Existing B1 codec/map and historical lifecycle regression (unchanged tests):
cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --test-threads=1

# Existing PR 15H-B borrowed-sort targeted regression where appropriate:
cargo +1.98.1 test -p quervant-core --lib b_u -- --test-threads=1
```

The two `b1_` and `b_u` commands are **regression** checks, not a substitute for B2 acceptance. Existing tests of old paths may legitimately need observational counter assertions updated to account for B2 eligibility, but never remove a meaningful equality/negative/error assertion. If the `b_u` filter selects zero tests after source inspection, use the exact existing `b_observation` test names found by inspecting the current file instead of claiming an empty PASS.

For test processes with a child helper, verify that its *actual child body executes and passes* (as B1-I04 did); an `ignored` or zero-test invocation is not evidence. A test-only injected invalid outer segment must be wrapped through the actual container builder/verification seam rather than corrupting memory after the parser established immutable integrity.

### 9.2 One final local QA ledger on the finished executable/test source

Trust the accepted B1 main as healthy; **do not run baseline QA before implementing B2**. When all B2 production/test changes are complete, execute this repository-prescribed ledger **once** on the final source. A subsequent narrow source fix invalidates its affected tests/QA checks and must cause the required source-dependent gates to rerun; pure report text alone does not trigger full QA reruns.

```sh
set -o pipefail
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

`bench --no-run` is a **compile-only** gate and never permission to measure warm performance. Coverage must be **at least 85% Rust workspace line coverage** for both default/all-features, no new exclusions. Record the **actual** coverage numerator/denominator, command, return code, counts, compiler and log path; do not copy B1 F2's 92–93% figures into B2. Preserve failure exit codes if logging with `tee`; use `PIPESTATUS`/`pipefail`. A green CI job does not replace a required locally executed feature-specific test.

Do not rebuild/measure Tantivy or Lucene, run Quervant B4, stage a BM-10 study, perform `perf record`, or do an operator-host stability acquisition. The B2 PR is not a benchmark.

### 9.3 Ordinary hosted CI

Use the repository's existing `.github/workflows/ci.yml` **unchanged**. Expected job names on the accepted B1 baseline are:

```text
rust
msrv
rustfs
benchmark-adapter-contract
python-benchmark-framework
```

Push after finishing implementation and local QA. Create the **new B2 draft PR** against accepted `main`. Inspect the ordinary pull-request run for the **exact final executable/test/CI source**; a job is PASS only if it is terminal-success on the correct source. The existing real `rustfs` job must actually execute and pass its specified suites. Do not manually dispatch, cancel or rerun a successful job to force a convenient green status. A pending CI run means **G8 PENDING**, not PASS; finish all independent documentation and report work. If the final PR head differs from the tested commit only in docs/evidence, explicitly prove `git diff --name-only TESTED..FINAL -- crates/ .github/ benchmarks/ Cargo.*` is empty and record both identities. Hosted merge checks/policies still apply to the real final PR head.

### 9.4 Performance boundary and QA cost

Structural counters may demonstrate *absence of per-candidate string comparisons/copies*; they are **not** timing results. Record that B2 prepares an optional B1 map which incurs build/metadata costs and may refuse under the metadata cap. Do not claim a win over Tantivy, Lucene or previous Quervant without B4's separately approved warm qualification. A6's measured misses and the remote-compaction publication residual stay unchanged. No cold-start diagnostic can substitute for B4 warm-query selection.

---

## 10. Documentation, source allowlist and protected paths (G9)

### 10.1 Permitted production/test files

| Path | Allowed change, narrowly interpreted |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | One optional map preparation and bound numeric candidate path; `MixedEntry` inline rank; private comparator integration; focused `#[cfg(test)]` observations and cases. No changes to evaluator, scorer, duplicate strategy algorithm, cursor representation, query DSL or projection. |
| `crates/quervant-core/src/search/typed_compare.rs` | Private `OrdinalSortKey` and exact comparator, ColumnAccess forwarding and focused unit cases. Existing typed scalar/comparator/tuple APIs unchanged. |
| `crates/quervant-core/src/segment/column.rs` | Only **private** bound query-sort ordinal wrapper and logical Single admission; focused unit cases. No encoder/parser/wire change or changed public B1 accessor. |
| `crates/quervant-core/tests/perf06_b2_ordinals.rs` (**new**) | Real FsDirectory/Index/UnifiedSearcher, B1 literal oracle, historical fixture/compaction/cursor/fallback cases I01–I08. |
| Existing PR15H-B test assertions *inside* `unified.rs`/`typed_compare.rs` | Only counter-expectation updates strictly required by choosing numeric B2 instead of borrowed B, retaining all semantic/error tests; report every adjusted assertion. |

No other existing production/test files are authorized. If a compiler error or an API contradiction requires another file, apply X35/X34 and **STOP that work** instead of silently expanding the allowlist. New B2 test helpers may live **inside the named new integration file**; no second fixture framework or dependency.

### 10.2 B2 documentation files

All documentation amendments are **additive**, source- and status-accurate, and must not rewrite old A4/A6/B1 results:

| Path | Required content |
|---|---|
| `docs/pr-artifacts/perf-06-b/PERF06B2_DETAILED_PLAN.md` (**new**) | Copy the approved downloadable plan **verbatim**; record actual SHA-256 and blob ID. If the approved plan is revised by the maintainer, record version and approval before agent execution; do not edit the frozen copy to justify deviations. |
| `docs/pr-artifacts/perf-06-b/PERF06B2_EXECUTION_REPORT.md` (**new**) | Actual G0–G10 gate ledger, source SHAs, list of changed paths and protected digest comparison, executed commands, failing/adversarial cases, optional fallback decisions, CI jobs, residual risks, B3/B4 handoff. |
| `docs/pr-artifacts/perf-06-b/evidence/b2-*` (**new**) | Compact necessary logs and exact source/CI/diff inventories; no huge target directory, secrets, benchmark result, local service dump or binary corpus payload. |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | Dated current B2 amendment: B1 accepted/merged (actual SHA), B2 numeric collector implementation/readiness only; B3/B4 still pending, no warm claim. Do not silently rewrite historical B1/A6 sections. |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Same source-true dependency and B2 status; G10 remains human-owned; B3 identity, B4 qualification unchanged. |
| `docs/ARCHITECTURE.md` | A narrow, accurate paragraph on B1 snapshot-owned shared ordinals consumed by B2's strict-term string-sort path, with explicit fallback, cursor and resource/corruption semantics; no general query-plan promise. |
| `docs/BENCHMARKING.md` | At most a short provenance note: B2 has no benchmark acquisition; B4 will decide adoption using qualified warm evidence. Do not alter methodology or thresholds. |
| `docs/ROADMAP.md` | Optional short current-status note only **after** relevant feature gates actually pass; no whole PERF-06 done. |

### 10.3 Explicitly protected (must be unchanged)

`Cargo.toml`, `Cargo.lock`, toolchain/`.cargo` settings, `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, every B1 plan/report and immutable fixture, `crates/quervant-core/src/index/**`, `segment/format.rs`, `segment/reader.rs`, `segment/build.rs`, `segment/metadata.rs`, `search/execute.rs`, `search/typed.rs`, `search/unified_cursor.rs`, `contract/**`, `storage/**`, `remote/**`, `quervant-objectstore/**`, distributed/vector code, `.github/workflows/**`, `benchmarks/**`, archived A4/A5/A6 results and configurations. In `segment/column.rs` all B1 encoder/parser logic is protected: only the newly specified private wrapper + tests may change. Do not upgrade dependencies/format/MSRV to make B2 tests pass.

Generate and review `git diff --name-status` and `git diff --check` against the **actual post-B1 main** and against the B1 reviewed executable source. If a protected file is modified even by an auto-formatter, restore only the task-owned diff after verifying its identity; never discard another developer's work.

---

## 11. Objective acceptance gates and final report

| Gate | PASS requires | Failure / pending disposition |
|---|---|---|
| **G0 — accepted source** | B1 actually merged; B1 candidate and accepted main reconciled by exact executable blob/ancestry; clean new B2 branch; plan/guide identities recorded. | If B1 not merged/source diverges: `NOT_STARTED_B1_NOT_ACCEPTED` or HARD STOP; no coding. |
| **G1 — correctness design** | INV-B2-01..13 mapped to source/negative tests; eligibility & fallback tables reconciled; no unresolved design choice. | HARD STOP any contradictory semantic contract. |
| **G2 — private comparator/access** | Exact ordinal enum/comparator, bound local accessor, logical admission, no B1 format changes or per-candidate name lookup. | Implementation incomplete. |
| **G3 — collector integration** | One request-wide map; one global heap; score/count/duplicate/cursor and owned tuple unchanged; optional fallback and typed errors correct. | Implementation incomplete. |
| **G4 — focused unit/adversarial** | U01–U24 actual executions, including 64-case oracle, all four direction/placement combos, 80/79 loser and MultiOne budget, negative/error cases, counter witnesses. | Missing meaningful assertion is BLOCKED even with green CI/coverage. |
| **G5 — local real vertical slices** | I01–I08 real `FsDirectory`/Index/PIT/compaction/genuine v1 fixture and full input-derived result/source proof; correct child execution if applicable. | Missing lifecycle/output proof is BLOCKED; do not defer to B4. |
| **G6 — provider-neutral regression** | Existing hosted RustFS suites actually execute/pass; protected remote/format paths unchanged. No new remote topology needed. | Pending/infra failure is BLOCKED; no mock pass. |
| **G7 — final QA** | Entire §9.2 ledger passes on exact tested source, default+all-feature line coverage ≥85%, no exclusions, MSRV 1.85.0 preserved. | Preserve failed command/source; do not mark PASS. |
| **G8 — CI** | Five required jobs terminal success on the admitted tested executable source/current PR head per GitHub evidence. | Pending/outage `IMPLEMENTED_VERIFICATION_BLOCKED`; do not wait indefinitely or claim success. |
| **G9 — docs/delivery** | Allowlist/protected-diff proof; complete report/negative evidence/decision ledger; valid draft PR, tested/final/remote SHAs and review handoff. | No completion/promotion claim. |
| **G10 — maintainer acceptance** | Independent reviewer explicitly accepts B2 and manages merge; B3 may use only the subsequently accepted source. | Always open for coding agent; no self-merge. |

### Final execution report — mandatory fields

1. **Identity:** repository, branch, B2 PR URL/number/draft state, post-B1 `main` SHA, B1 F2 executable SHAs/verification, B2 start, tested, final and remote-verified SHAs; whether `main` changed underneath and how reconciled.
2. **Scope:** old vs new code/paths, no format or search API change, no adapter/benchmark changes, exact protected blob inventory.
3. **Algorithm:** eligibility matrix, numeric key comparator, bound logical-value admission, MultiOne route, once-per-request map, per-segment binding, same global heap and old cursor tuple.
4. **Traceability:** each INV-B2 ID → implementation symbol → U/I test → executed command/log; ineligible/NotAvailable/error tables and actual cases.
5. **Resource/cancellation:** measured/checked logical charges, loser decode budgets, MultiOne checks, candidate heap unchanged on errors, B1 map budget/fallback, cancellation and last-Arc ownership preserved.
6. **Tests:** actual named U01–U24, I01–I08, old B1/15H-B regressions, toolchain/flags, pass/fail/ignored counts; independent oracle input vs produced results.
7. **CI:** run ID, exact head, each job terminal status and real RustFS execution, or precisely what remains blocked.
8. **Negative evidence and decision matrix:** every applied X row, environment blocker, pre-existing/flaky classification proof, tests that initially failed and what fixed them; never erase earlier attempts.
9. **Residual risk:** shared B1 map may be unavailable on legacy/mixed/high-cardinality or tight metadata caps; B2 then uses legacy sort. Old PIT snapshots keep their own rank. MultiOne pays legacy decode. B2 still materializes strings for *competitive heap entries*, not solely final winners. No stable global ID across snapshots. Existing reader-cache/open costs remain; remote compaction publication is unqualified. No latency, whole-index footprint or RSS success claim.
10. **Next dependency:** B3 owns document-key identity; B4 owns consolidated warm performance/size/writer and exact-sort qualification; do not automatically launch either, merge, or change performance thresholds.

### Recommended PR description (agent may use after successful G0)

> **PERF-06-B2 — snapshot-wide ordinal ranking for strict keyword sort**
>
> Uses the accepted B1 persistent dictionaries and snapshot-owned shared numeric ordinals to rank eligible single-field Keyword sort candidates in Quervant's existing global Top-K heap. Retains identical raw UTF-8 value order, Missing/Null placement, key ties, total counts, score bits, candidate/decoded-resource admission, duplicate checking, projections and owned string cursor tuples. B1 optional unavailability and unsupported query shapes use the original string/typed path; B2 does not change index bytes, storage, public query/cursor contracts or benchmark tooling.
>
> Includes focused adversarial unit and local end-to-end tests, accepted historical fixture compatibility, existing hosted CI, no performance acquisition. B3 document identity and B4 warm qualification remain separate. Maintainer G10/merge remains open.

---

## 12. Final independent review checklist

- [ ] B1 was **actually accepted and merged** before B2 code; post-merge source identities are exact, not speculative.
- [ ] The B2 scope is one dominant collector optimization; no source drift or unrelated edits.
- [ ] Numeric ranks come exclusively from B1's `SnapshotKeywordOrdinals` translation for the **same** snapshot field and segment.
- [ ] All four direction/missing-placement cases equal canonical comparison; equal raw strings tie by logical key asc.
- [ ] `MultiOne` remains a full logical old decoder including vector and string budgets on **losing** candidates; `Single` losers perform the old budget check without an owned copy.
- [ ] Optional `NotAvailable` cases decide whole-request fallback before processing; B1 corruption/cancellation/poison errors are not hidden.
- [ ] All legacy heap-entry constructors initialize the new private ordinal field `None` and B2 entries `Some`; no mixed heap path is silently accepted.
- [ ] Existing K+1 global heap, duplicate prefilter/exact strategy, `total_hits`, score bits and physical projection are unchanged.
- [ ] First B2 cursor page produces original owned string-valued cursor; subsequent pages using old path reassemble exact complete order.
- [ ] B1 cache not initialized by JSON/geo/typed, batch, aggregate, multi-sort, nonstrict or cursor requests.
- [ ] Independent raw-byte oracle and full literal projection verify new and legacy paths; 64-case generated differential and 80/79 limits executed.
- [ ] Fresh real local `FsDirectory` and historical v1/mixed/v2 lifecycle tested; the B1 archived fixture has not been rewritten.
- [ ] No benchmark result, new adapter, profiler, remote publication change, permanent rank promise, unsafe code, or extra dependency.
- [ ] Actual source-dependent QA and hosted CI meet thresholds, with pending/not-run gates reported accurately.
- [ ] No roadmap completion/performance win is claimed before independent G10 and later B4 qualification.

**Terminal instruction to the coding agent:** On successful preflight, implement this design continuously, execute the specified checks, create only the new draft B2 PR, and report exact evidence. On an unforeseen condition, invoke **X40 HARD STOP**, preserve all prior work and independent evidence, and request the smallest needed maintainer design amendment. Never improvise an alternative architecture, extend eligibility, tune thresholds, merge, or start B3/B4.
