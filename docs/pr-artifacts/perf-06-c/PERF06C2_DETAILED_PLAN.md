# PERF-06-C2 — Strict-term physical execution and in-place scored-posting handoff

**Repository:** `yduchesne/quervant`  
**Dependency:** merged documentation-only C1 PR #130; verified `main` at authoring time: `bc726420cede2e26681d6e8192b45a5d0169abbf`  
**Suggested branch / PR:** `dev/perf06-c2-physical-executor` → `main`; draft PR `PERF-06-C2: integrate exact-count strict-term Top-K execution`  
**Document authority:** `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md`, `docs/pr-artifacts/perf-06-c/PERF06C1_SOURCE_AUDIT.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`, `docs/TESTING.md`.  
**Plan status:** **reviewed and corrected after a second source-level design audit (revision 2, 2026-11-25 UTC)**; **C2 not implemented by this document**. The coding agent must implement this exact design, not perform architecture selection. Revision 2 fixes the segment-binding/error-precedence conflict, a Rust borrow-order ambiguity, the 100K integration writer-limit setup, and synthetic fault-evidence classification. The former plan must not be executed; this complete revision replaces it.

## 0. Execution authorization and scope boundary

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

The agent is authorized to create **one draft C2 PR** from the merged C1 `main`, make the source/test/doc changes in §11, run the local verification in §10, push normal fast-forward commits and observe CI. It is **not** authorized to merge, release, run a real performance campaign, profile the host, create C3, adjust B4 qualification, weaken an invariant, amend an unmerged prior PR or alter the frozen C1 architecture. A clean code implementation plus failing/incomplete mandatory acceptance evidence is **not** a completed C2 PR.

**One dominant problem:** remove the remaining independent full-M scored-pair allocation and associated intermediate handoff between the accepted strict-term scorer and B2/B3 Top-K collection, while preserving the original complete-match count, eager BM25 scores, error precedence, logical work/resource charges and public response. C2 is not winner-only scoring: **every matched document is scored before any of that segment's candidate is considered**. Winner-only score deferral, its proof and exceptions belong exclusively to C3.

**Source is binding:** first `git fetch origin main`, pin the new `origin/main` SHA and check it descends from `bc726420…`. If any source or contract anchor has materially changed, classify using D01–D04 and stop the affected design rather than translating this document to a novel architecture. The authoring-time SHA is not permission to reset or discard subsequently accepted main changes. The base remains `main`, never an unmerged review branch.

## 1. Reconciliation of C1 and current production source

At `main@bc726420…`, C1 is accepted documentation, not a runtime physical planner. The production strict-term path is already substantially optimized by PERF-05 and B1–B3. Do **not** resurrect obsolete full-M `BTreeSet -> BTreeMap` implementations or add a second postings codec, compiler, field-statistics system, ranking comparator, heap, duplicate policy or per-document key cache.

| Existing authoritative symbol | Accepted behavior; required reuse | C2 delta |
|---|---|---|
| `search/unified.rs::UnifiedSearcher::search_impl`, `execute_unified` | Query/sort/TopK/projection validation; cursor binding before planning; ordinary output projection and response memory handoff | **Untouched public signatures and validation/projection path** |
| `search/unified_plan.rs::compile`; `UnifiedNode`, `CompiledLeaf` | One validated compiler, root-tree and interning; `positive_lexical` and scoring field IDs | C2 selects from the compiled plan; never compile twice |
| `unified.rs::single_term_postings_eligible`, `keyword_ordinal_eligible` | Accepted strict single-analyzed-term and single eligible Keyword sort predicates | **Necessary, not sufficient** C2 predicates |
| `unified.rs::collect_mixed` | Guarded readers, effective-live masks, query expansion and `compute_stats`, B1 map, B2/B3 segment rank/key binders, K+1 heap | Extract the *legacy hot loop* as a distinct function and dispatch once after common setup |
| `execute.rs::build_leaf_data` and `TermPostings` | Validated ascending `(doc_id,freq)` vector; `next_with(cancel)` full structure validation, scanned-frequency charging and live filtering | Reuse that exact decoded allocation; do not instantiate another postings reader |
| `execute.rs::evaluate_lexical_with` | Accepted strict-term no-membership-relookup path; logical matched/score reservations; scores all matches; allocates a **second** `Vec<(doc_id,f64)>` | **Preserve unchanged** for generic calls; C2 adds a distinct in-place variant |
| `execute.rs::{SegmentCandidateLedger,CandidateBudget}` | One segment/global logical peak, preflight/commit/release, RAII rollback | Same checkpoints/amounts/release ordering (§6) |
| `score.rs::{compute_stats,SnapshotStats,FieldStats::bm25_score}` | Snapshot-wide verified live stats, persisted or legacy norms, typed BM25 errors and prepared IDF | Reuse exact per-candidate scorer; no new BM25 math |
| `index/{snapshot.rs,keyword_ordinals.rs}` | Verified immutable guards and B1 request-local ordinal map | Preserve readiness/fallback and lifetime |
| `unified.rs::{consider_compact_ordinal_candidate,consider_ordinal_keyword_candidate}` | Numeric rank, key-hash/exact collision check, logical charges, B3 owned-key fallback, canonical K+1 admission | Reuse **these two functions**, not a copied comparator/duplicate implementation |
| `unified.rs::{MixedEntry,OrdinalHeapAudit,CompactHashAudit,d3c::State}` | One retained-duplicate state, heap ordering, one-time audits | Same one-per-request state for C2 |
| `unified.rs::select_keys`, `execute.rs::visit_lexical_membership_with` | Complete membership for query mutations, not top-K | **Never route via C2** |
| `search/unified_cursor.rs`, `project_selected_hits`, `ProjectionLedger` | Snapshot-bound cursor and exact projections; normal response publication | Share the accepted finalization logic, do not rewrite cursor format |

### 1.1 Historical negative evidence (binding)

* PR 15H-A/A2: candidate staging improved common/high-hit but degraded absent/rare and was rolled back.
* PR 15I-C: older `for_each_exact_term_score_with` implementation and its generic-boundary/dispatch experiments were rejected after rare/absent slowdowns (up to approximately 1.7×) and a generic code-layout effect even when the physical branch was disabled. Its full-M `Vec<f64>` and out-of-line boundary are **not C2 code to transplant**.
* Accepted PERF-05 already eliminated same-term binary relookup, moved the sole validated postings allocation, and removed the strict path's full-M scored `BTreeMap`. C2 must not reimplement those accomplishments.
* B4 qualified **cumulative** B1–B3 against the pre-B1 reference and has been merged; C2 makes **no** performance claim. C4 independently qualifies incremental C over accepted post-B4/C1.

**Materially different C2 mechanism:** keep the one existing validated `(doc_id,u64)` posting vector; after a complete, eager score pass, rewrite its `u64` frequency field **in place** as the score's `f64::to_bits()` (still `u64`), using only safe Rust. Later yield `(doc_id, f64::from_bits(bits))` directly to existing B2/B3 candidate handlers. The original vector is reused rather than allocating a *second* M-sized scored-pair buffer or a separate M-sized score array. No `unsafe`, `transmute`, raw pointers, new codec, or second posting scan is permitted. The vector remains the same 16-byte-per-entry allocation and stays owned for exactly the phase during which the legacy path retained its independently allocated scored-pair Vec. The physical representation holds no public score-bit encoding; it is an internal, per-segment, request-local buffer.

## 2. Pre-implementation correctness worksheet (must complete before code)

Before touching production Rust, append the following invariant ledger to `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md`. Each row must include source evidence, a concrete wrong-result counterexample, one named acceptance test, and its actual command/result once run. No contract can be marked PASS from source inspection alone.

| ID | Must remain true | Wrong implementation counterexample | Required test |
|---|---|---|---|
| C2-I01 | Only the C1 eligible *standalone* strict one-term, one-sort-column query with ready request-wide ordinal map and **proved** M > K+1 enters the new path; segment bindings remain validated in original segment order | `And(Term)`, relevance sort, typed predicate, K+1-only, `NotAvailable`, or an eager later-segment binding error incorrectly enters/aborts | C2-U01, U02, U17, I01 |
| C2-I02 | Every compiled/schema/cursor and per-reader validation precedes processing as in accepted code | Invalid sort lost to corrupt segment, cursor tested after reader opens | C2-U03, I07 |
| C2-I03 | For every segment, complete `DocFreqPostingsReader::next_with` validation before scoring/admission | Later malformed posting silently skipped after K winners | C2-U04, U12, I06 |
| C2-I04 | Logical live-document examination remains N; scanned posting occurrences charge `freq`, including dead postings, and cancellation is polled | Charge only M or stop charging after heap fills | C2-U05, U13 |
| C2-I05 | `total_hits` counts all effective-live matches in all segments, even if K is full | Truncate count at K/K+1 or count deleted rows | C2-U06, I01, I03 |
| C2-I06 | All M scores are computed **before** any candidate is admitted for that segment | Later `InvalidScore` hidden by earlier corrupt-key decision | C2-U07, U12 |
| C2-I07 | Every returned lexical hit has bit-identical `Some(f64)` from original `+0.0` BM25 order | Changed sign of zero/float grouping, score `None` for explicit sort | C2-U08, I02 |
| C2-I08 | The only O(M) owned candidate buffer is the original decoded posting allocation reused in place; no second M-sized scored-pair result Vec | Allocate `Vec<(u64,f64)>` in new evaluator | C2-U09, code review |
| C2-I09 | Resource preflight, peak, one-over errors, release and unwind are **logically identical** to accepted strict evaluator | Fewer virtual charges admit previously rejected query; stricter peak rejects formerly admitted query | C2-U10, U11, I08 |
| C2-I10 | Numeric sort direction, missing/null, MultiOne and exact byte-key ties remain B2-defined | Candidate admission uses `doc_id` as global sort order or hash as tie-break | C2-U14, I02 |
| C2-I11 | Duplicate identity is exact-key-based and tested before rejecting a loser | Same hash treated as equal key; duplicate loser ignored | C2-U15, I04 |
| C2-I12 | K+1 sentinel and cursor contents remain exact; subsequent cursor page uses Legacy | Heap capacity K; cursor from numeric rank instead of canonical string | C2-U16, I05 |
| C2-I13 | B1 `NotAvailable` chooses Legacy before any candidate; corruption, poison, cancellation are typed errors | Catch an error and silently replay generic after partial work | C2-U17, I06 |
| C2-I14 | Snapshot, PIT, updates/deletes, compaction and multiple segments obey the same live mask and identity | Reopen invalidates PIT or counts tombstoned hits | C2-U18, I03 |
| C2-I15 | Batch, aggregation, mutation `select_keys`, JSON/geo/Boolean/phrase/typed/multisort never use C2 | Batch response memory accounting bypassed | C2-U19, I07 |
| C2-I16 | Low-hit generic path remains functionally unchanged; dispatch runs once outside the document loop | Disabled fast operator still calls per-candidate physical selector | C2-U20, source/CI review |
| C2-I17 | Errors produce no successful partial response and no leaked segment/snapshot charges | First page returned despite error on later segment | C2-U11, U12, I08 |
| C2-I18 | No persisted bytes, writer/storage/reader API, feature flags, dependencies or experimental strategy overrides change | New versioned format added for C2 | Protected path inventory |
| C2-I19 | Acceptance evidence is executed at the final tested source; C2 has no real timing acquisition | Source changed after the only tests; green CI on older SHA cited | G7/G8 identity ledger |
| C2-I20 | C3 winner-only scoring remains **absent**; full BM25 errors on noncompetitive documents are retained | Skip score when numeric rank loses | C2-U07, U08, I02 |

**Mandatory challenge checklist (write concrete answers before coding):** (a) Why is C2's M certificate based on effective-live data rather than physical postings count? (b) Why does the use of the sole posting buffer eliminate the *additional* scored-pair allocation without reducing an existing logical charge? (c) Which error wins if candidate 0 has an invalid key and candidate M-1 has an invalid score? (d) How is no-postings in one segment handled while another has >K+1 matches? (e) Why is ExactSet still allowed but B3 compact hash optional? (f) Where does the last `Arc<ReaderSnapshot>`/ordinal map live? (g) How is a low-hit query guaranteed to reach the old generic loop? An answer inconsistent with the merged C1 contract is **HARD STOP D02**, not permission to reinterpret it.

## 3. Exact physical eligibility and dispatch (C1 §3)

### 3.1 Request-level selector — all predicates required

1. `batch.is_none()` (standalone `search`, not any batch entry point); `aggregation.is_none()`; `request.after.is_none()`.
2. `single_term_postings_eligible(plan, request, aggregation)` **and** `keyword_ordinal_eligible(plan, request, aggregation, true)` both true.
3. Verify compiled `plan.root == UnifiedNode::Lexical(0)`, one lexical `CompiledLeaf::Term { field_id, terms }` with `terms.len()==1`, `plan.positive_lexical == {0}`, no typed leaves, and that `plan.scoring_field_ids` contains the term field. This may overlap existing predicates intentionally as a fail-closed source guard, not a second analyzer.
4. The sort is exactly one explicit sortable columnar `Keyword` field, `Cardinality::Single`, no `multi`, `json_path`, `distance_from`, aggregation, relevance sort or cursor. This is already enforced by `keyword_ordinal_eligible` and must not be widened.
5. Request-wide B1 ordinal preparation has completed with `Ready`; it was built and validated against the admitted guarded reader slice. **Do not eagerly call `columns.bind_keyword_sort_ordinal` or `map.bind_segment` on every segment as a separate eligibility preflight.** The accepted `collect_mixed` binds each segment in ascending segment order, *after* the previous segment has completed; a later-segment error must not overtake an earlier-segment posting/score/key error. In C2, leave both actual binding calls at precisely their accepted **per-segment** position and propagate their existing typed errors if a segment is not usable. `NotAvailable` at request-wide preparation => Legacy **before candidate processing**; a true preparation error propagates unchanged. The selected C2 route never dynamically flips to Legacy after the first candidate.
6. `SnapshotStats::field(field_id).doc_freq(term)` is the source-validated, effective-live query-term count for the one positive term. It must exist and be representable as `u64`; require `M > request.top_k.limit.saturating_add(1)`. If the existing statistics cannot provide a reliable effective-live count for a given format/mask, dispatch **Legacy**. No corpus-dependent percentage, arbitrary `M > 100`, sample probe, or post-hoc threshold is permitted. `M` is a dispatch certificate, **not** the reported `total_hits`: C2 still decodes/enumerates and counts every match.
7. The selected source has the accepted B1/B2 `Ready` representation. Do not force missing map capability, reopen a segment solely to estimate M, nor reject a valid query because the optimization cannot be selected.

**Source evidence behind the count:** the accepted `compute_stats` computes term `doc_freq` using the live-masked postings when a mask excludes documents or when legacy norms require an actual postings walk, and the dictionary `doc_freq` when the field has persisted norms and every physical document is effective-live. It is the existing BM25 source count, not a new estimate. If inspection reveals a case where that accepted count is not a sound effective-live cardinality, **C2-D11** requires Legacy for that *whole request* (prior to per-candidate processing), with the exact state recorded. Do not invent a second counting pass. All declared C2 tests must show the verified certificate equals the actual final count on ordinary valid indexes.

### 3.2 Finite selection table

| Input/condition | Route | Reason |
|---|---|---|
| N=0 / M=0 or absent term | Legacy | no candidate benefit; no new work or error |
| M=1; M=K; M=K+1 | Legacy | all matches may be retained as K+1 lookahead |
| M=K+2 and every other predicate true | C2 | first eligible with a guaranteed loser |
| M>K+1; B1 `Ready`, `Linear` duplicate mode (K below threshold) | C2 | preserve Linear with current B2/B3 machinery |
| M>K+1; B1 `Ready`, `Prefilter` duplicate mode | C2 | preserve B3 hash prefilter and byte-exact checks |
| M>K+1; B1 `Ready`, resolved `ExactSet` | C2 with **owned B2 key** path | original `HashSet<DocumentKey>` behavior unchanged |
| B1 `LegacySegment` / `ResourceBudget` / `Allocation` / `UnsupportedField` | Legacy | documented optional unavailable |
| Segment B3 fingerprint directory optional refusal | Stay C2, use existing B2 owned-key handler for that segment | nonfatal, segment-local |
| `And([Term])`, `Or`, `Not`, phrase, multi-term, prefix/regex, JSON/geo/typed, `MatchAll` | Legacy | compiled shape not exact root-term |
| relevance/no sort, more than one sort field, multivalue selector, JSON path, distance sort | Legacy | not one ordinal keyword sort |
| `after` cursor, batch, aggregation | Legacy | must preserve output/accounting paths |
| Corruption, schema mismatch, poisoned cache, later-segment ordinal bind failure, cancellation, work/memory limit | **Error at the accepted execution checkpoint** | never treat as unavailable/success, and never eager-precheck a later segment before earlier work |
| Eligibility invariant fails **after processing begins** | **Error/STOP**, never restart Legacy | no mixed execution or double charges |

**C1 M guard:** no choice based on learned runtime latency, profiler readings, optimizer heuristics, or user-provided defaults. The **whole request** selects one physical family; the branch is not revisited per segment or per match.

### 3.3 Hot-path source isolation — specified Rust refactor

In `crates/quervant-core/src/search/unified.rs`, preserve `search_impl`/`execute_unified` and all validation/output/projection code. Split `collect_mixed` only at the already existing boundary **after** creating guarded readers, `live`, expansion, stats, optional ordinal map, `CandidateBudget`, duplicate-policy state, and heap/ordinal/hash audit state, but **before** entering the segment loop. **Do not move any `ColumnAccess::open`, `bind_keyword_sort_ordinal`, `map.bind_segment`, `JsonAccess::open` or geo-sort setup from the segment loop into the request preflight**: that would change which segment's first typed failure is observed. The common orchestration remains in `collect_mixed`. Create **two private non-generic-hot-loop functions**:

- `collect_mixed_legacy_body(...)` contains the accepted source's entire per-segment loop and aggregation/heap finalization, moved **mechanically**, not rewritten or optimized. Its required inputs are the already computed preflight locals borrowed from the original stack: `plan`, `request`, `readers`, `guards`, `live`, `expansion`, `stats`, `ordinal_map`, `ordinal_field_id`, `keyword_late`, `meter`, `budget`, `scope`, heap/audits/duplicate state, `aggregation_state`, `cancel` and `fingerprint`. Use explicit parameter types as required by the compiler, `#[allow(clippy::too_many_arguments)]` for the private helper, and no self-referential owning structure. Borrowed readers/stats are anchored in the **same** request-local stack frame. If `aggregation_state` and `heap` are easier to move into a second private request-local context struct, the **only permitted** struct is a plain borrow-only bundle without `Arc`, interior mutability or snapshots; document its fields. Do not introduce a new generic framework.
- `collect_strict_term_ordinal_body(...)` contains the C2 per-segment loop and direct-scored candidate admission described in §4, using the same preflight locals. The two per-segment loops are in separate functions; there is no new per-document dispatch condition or strategy flag in the legacy loop. **Do not add `#[inline(always)]`, `#[inline(never)]`, `cold`, `likely` hints or compiler flags**: the historical 15I-C source demonstrates that source layout alone can regress low-hit cases, and actual timing is reserved for C4.

Use one `if physical_eligible { ... } else { ... }` in `collect_mixed` **before any per-segment admission**. The branch choice is a local enum or boolean (not persisted), recorded by a **test-only** observation hook. Do not add a second call to `compute_stats`, `expand_query`, `ReaderSnapshot::prepare_keyword_ordinals` or `UnifiedSearcher::search_impl`. Do not call Legacy as a catch-all after any C2 candidate has been visited. Keep the generic branch's setup, `OrdinalHeapAudit` / `CompactHashAudit` initialization, `d3c::State::for_request` and failure order identical.

The refactor must be a **mechanical move** of generic code: compare its statement order and semantics before/after, document changed source anchors and any necessary borrow-only parameter plumbing, and prove all ineligible dispatch cases produce the exact accepted results and errors. If the extraction requires a behavior change to the generic loop, stop D14 rather than changing it opportunistically. Exact hot-code neutrality can be qualified only at C4; no C2 speedup claim is allowed.

## 4. Required in-place physical evaluator and collector — concrete design

### 4.1 One new `execute.rs` evaluator; never modify the generic evaluator

Add exactly one new **private-to-search** function to `crates/quervant-core/src/search/execute.rs`, next to `evaluate_lexical_with`. The implementation may use the actual visibility required by the sibling `unified` module (`pub(crate)` or `pub(super)`), but must not be exported from the crate. Prescribed conceptual signature (use the concrete existing lifetimes and source types):

```rust
#[allow(clippy::too_many_arguments)]
pub(crate) fn visit_strict_term_scored_with<F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    cancel: &dyn Cancellation,
    mut on_scored: F,
) -> SearchResult<()>
where
    F: FnMut(u64, f64, usize, &mut CandidateBudget) -> SearchResult<()>,
```

The closure argument `usize` is the **segment's full matched count**; it exists solely to preserve the accepted `single_hit_segment = matched_count == 1 && reader.doc_count() >= 1024` key-decoding optimization. The callback is invoked only **after all postings and scores for the segment have been validated**, all segment ledger reservations have been released and `ledger.finish()` has succeeded. One callback is issued for **every matched document** in ascending physical `doc_id` order, even after the global heap is full. Callbacks may return an error; a partial in-memory heap is then dropped and **no response** is published.

This evaluator is **strict only**. Its precondition is the C1 compiled root shape and already successful B1 readiness; at runtime recheck:

```text
leaf_data == [LeafData::Term { field_id, terms }] and terms.len() == 1
positive == {0}
typed_examination == false (not an argument: C2 never accepts typed queries)
```

An unexpected shape is the existing typed `SearchError::CorruptIndex { detail: "single-term postings eligibility mismatch" }`, not a fallback or panic. **Do not add a second call to `reader.postings`, a second validated postings decoder, a second term lookup or a separate selector that reinterprets query text.** `build_leaf_data` remains the single source of codec validation and occurrence/work charging.

### 4.2 Frozen ordered algorithm inside `visit_strict_term_scored_with`

Follow this sequence *exactly*, retaining the existing `SegmentCandidateLedger` as the sole segment-memory owner.

**A. Enter the ledger and decode the one posting buffer**

1. `let mut ledger = SegmentCandidateLedger::new(budget)?;` — same start and `begin_segment()` check as accepted evaluator.
2. `let (mut leaf_data, leaf_charges) = build_leaf_data(reader, leaves, expansion, segment_index, live, &mut SearchWork::shared(meter), &mut ledger, None, cancel)?;`. Scope the `SearchWork` temporary exactly as the existing method does so the meter is not doubly borrowed. C2 is standalone, hence **`memory=None`**; batch remains Legacy. `build_leaf_data` performs exactly one validated `DocFreqPostingsReader` walk and retains one sorted `Vec<(u64,u64)>` for live postings. Every push retains the same `TERM_POSTING_BYTES == 16` logical charge. No direct unvalidated section read.
3. Confirm the expected single-term runtime shape. Read and copy only the `field_id` (`u32`) **from the validated `leaf_data`**; verify the one term is present. **Do not retain a `&str` borrow of `leaf_data` across the upcoming mutable call to `take_strict_one_term_postings`**. An absent/extra term is typed `CorruptIndex` before any score/heap mutation. The canonical term used for scoring remains the actual validated `leaf_data` term, not raw request text. Its `&str` borrow must be created **after** step 6 moves the posting vector out.
4. Obtain `verified_live_count = stats.verified_segment_live_count(segment_index, live.len())?`; call `effective_live_examination_count(live, verified_live_count, meter)?` **once**, then `meter.charge_lexical(live_count)?` if nonzero, followed by `meter.check_cancelled()?`, exactly as accepted strict `evaluate_lexical_with`. Do not call `meter.charge_lexical(postings.len())` as a substitute for the N examination.
5. Iterate all decoded postings once in ascending order **while `leaf_data` remains intact**. For each: `meter.check_cancelled()?`, ensure doc id monotonically advances (validated decoder already establishes this), and apply the established strict predicate semantics (root is precisely the matching term, hence every effective-live decoded posting is true; no binary-search membership lookup and no type/Boolean evaluation). Preserve the old candidate-loop's observation count in test-only witnesses as described in §8; do not add a production counter, trace event or marker. If an existing guard or test shows that the strict root can return false, **HARD STOP D20**: do not silently drop candidates or substitute a new filter.
6. Only **after all callbacks/validation implied by the accepted strict root have completed**, move the sole postings vector from `leaf_data` using the **existing** `take_strict_one_term_postings(&mut leaf_data, false)?`. Do not clone, sort, reserve a replacement, or use raw memory reinterpretation. Record its original pointer/capacity in `#[cfg(test)]` only to prove reuse. **Now** match the post-`take` `leaf_data` as exactly `[LeafData::Term { field_id: f, terms }]` with `terms.len()==1`, verify `*f==field_id`, and borrow `terms[0].term.as_str()` for step 9. This term is still present because `take_strict_one_term_postings` takes only `terms[0].postings`. Use the verified actual owned term in `leaf_data` and do not allocate an extra clone. Hold this immutable term borrow only through the score loop; then release it before dropping `leaf_data` in step 10. No custom raw-pointer borrowing workaround is needed.

**B. Reproduce accepted matched/scored logical admissions while scoring eagerly**

7. Let `m = u64::try_from(postings.len())` (typed `ResourceLimit` on conversion overflow); compute `matched_bytes = bytes_for_count(m, SET_BYTES_PER_ENTRY /* 48 */)?`; call `ledger.reserve_with_memory(m, matched_bytes, None)?`. **This virtual matched-set reservation is mandatory even though there is no physical `Vec<u64>` or tree.** It happens after complete per-segment term decode and N examination and before any score is calculated, exactly as in baseline.
8. Compute `scored_bytes = bytes_for_count(m, SCORED_MAP_BYTES_PER_ENTRY /* 64 */)?`; call `ledger.reserve_with_memory(m, scored_bytes, None)?`. This reproduces the accepted `score_single_term_candidates` pre-scoring reservation, even though no physical `BTreeMap` or second scored Vec is created. **Do not change the `16/48/64` constants or make the extra reservation optional based on physical memory saved.**
9. Resolve the same accepted `stats.field(field_id)` and the **post-take immutable `leaf_data` term** borrowed at step 6. `positive == {0}` is required, so the calculation per element is the **exact** original `score_single_term_candidates` algorithm:

```rust
// At entry, `row.1` still holds validated term frequency.
let mut score = 0.0_f64;
if let Some(field) = field_stats {
    let dl = field.length(segment_index, row.0);
    let contribution = field.bm25_score(term, row.1, dl)?;
    score += contribution; // EXACT accepted initial +0.0/rounding order
}
row.1 = score.to_bits(); // still u64, no `unsafe` or changed allocation
```

Process the rows in original ascending physical order. **Score every row, including those that will lose numeric Top-K.** Never call `sort` or B2/B3 heap comparison in this phase. On a late `InvalidScore`, return immediately and allow RAII to drop any partially rewritten vector and release every reservation; no candidate has been touched in this segment yet. No second BM25 implementation and no `f32` conversion. `f64::from_bits(score.to_bits())` is bit-exact, including signed zero. The accepted scorer's zero/missing-field branches remain intact. Keep `score::FieldStats::bm25_score` and the original prepared statistics untouched. Introduce a small **private, non-public** wrapper `ScoredPostingBits` around the same vector **only if** needed to prevent accidental use of overwritten frequencies; it must not allocate or clone.
10. Release the logical reservations in the **accepted order** after scoring completes: discard the now-empty `leaf_data` after its last use, then release `(m, matched_bytes)`, `leaf_charges`, `(m, scored_bytes)` through `ledger.release_with_memory(..., None)` **in exactly the same observable order as the accepted `evaluate_lexical_with`**. The sole posting buffer is *not* dropped: after conversion it is physically equivalent in size and lifetime to the accepted evaluator's separately allocated scored output. It replaces that output, so its physical bytes do **not** introduce an additional overlap beyond baseline.
11. Call `ledger.finish()?` and drop its mutable borrow of `CandidateBudget` **before** invoking the collector callback. A leftover entry/byte charge is typed `CorruptIndex`, never cleared by manually zeroing budget counters.

**C. Handoff to the existing ordinal collector, with no intermediate output Vec**

12. For each `(doc_id, score_bits)` still in the sole owned vector: call `on_scored(doc_id, f64::from_bits(score_bits), matched_count, budget)?`. This is a direct iterator/closure: **do not construct `Vec<(u64,f64)>`** at this boundary. The callback must finish *before* the next element is yielded. No `async`, `'static` callback, cloned `Arc<ReaderSnapshot>`, remote I/O, or allocation based on M may be introduced.
13. The full vector is dropped when this function returns (or on error). There must be no borrow into an owned `SelectedHit` or cursor; retained hits already own their document key and sort tuple under the B2/B3 admission contract. The returned `SearchResult<()>` is all the executor exposes.

**Important error-order guarantee:** In baseline, score errors for the segment are surfaced during `evaluate_lexical_with` **before** the outer candidate loop processes keys/sort. C2 performs the complete score conversion *before* calling `on_scored`, preserving that order. This is the reason for the in-place two-phase transformation rather than interleaving score and heap admission. The agent must not “simplify” this design to score/admit one posting at a time.

### 4.3 Test-only proof of in-place ownership

Inside `#[cfg(test)]` in `execute.rs`, add a thread-local `c2_observation` with only the following small counters/witnesses: strict evaluator calls, converted row count, in-place pointer/capacity preservation, callback count. Include a test-only conditional hook that can cause a **synthetic typed score failure at a selected late doc** before the row is overwritten, to prove error precedence; the hook must be entirely compiled out of production, must have a thread-local RAII reset and must **not** replace or change `FieldStats::bm25_score`. No production runtime flag/env override, globally shared counter or tracing dependency. Tests may also use the existing `execute::test_observation` counters to verify zero legacy `score_single_term_candidates` calls in C2 and positive calls in Legacy. The test-only hook is not permission to fake posting decoding or field-rank calculation. **Synthetic-fault evidence is labeled `INJECTED_C2_ONLY`; it must not be reported as an actual baseline-vs-C2 same-fault differential.** Use real unmodified scorer behavior for all ordinary `to_bits()` parity, and compare genuinely shared malformed-posting/column/key/resource faults against the forced-Legacy reference. If a real `InvalidScore` multi-fault fixture cannot be constructed through the protected source boundary, disclose precisely which precedence claim remains source-derived/test-injected; do not modify `score.rs` or falsify a reference result. Any mandatory proof that cannot be supplied under this plan invokes D53/D64 rather than a hand-waved PASS.

A pointer/capacity witness proves allocation reuse only for a real decoded vector; it does **not** establish that the whole query uses less RSS. Physical memory is a separately measured concern for C4, not a claimed C2 result.

## 5. Exact candidate, heap and response integration in `unified.rs`

### 5.1 C2 per-segment setup: no semantic omissions

For each guarded segment, preserve the accepted segment-initialization order **even if C2 needs none of a particular helper**:

1. `ColumnAccess::open(reader)?`; resolve `keyword_field_id` and `ordinal_binding` (`columns.bind_keyword_sort_ordinal`, `map.bind_segment(&guards[index])`) once for this segment. Missing binding with a `Ready` request is a **typed error**, not optional fallback.
2. Preserve `typed::JsonAccess::open(reader)?`, empty `typed_geo`/`geo_scratches` construction and `typed::build_geo_sort_distances_with_memory` / sort scratch setup as in accepted `collect_mixed` for the same sort shape. Do not skip a validation or change which corrupt-section error wins merely because C2 will not consume the returned JSON/geo structures. No typed predicate or aggregation may have been admitted by the selector.
3. Preserve one `CandidateBudget`, `SlotMemoryScope` (None in C2 standalone), `d3c::State`, one `BinaryHeap<MixedEntry<'_>>` with capacity `request.top_k.limit.saturating_add(1)`, `OrdinalHeapAudit` and `CompactHashAudit` across the whole request.
4. Set `KeyBinder::Unattempted` once per segment; on the **first scored candidate of that segment**, follow the original code verbatim: if resolved duplicate mode supports compact keys, attempt `reader.bind_key_identity(cancel)?` once, with optional refusal mapped to `KeyBinder::Fallback`; otherwise force owned B2 fallback for that segment. Reuse the established `consider_compact_ordinal_candidate` / `consider_ordinal_keyword_candidate` and their internal ranking, charging, duplicate and heap behavior.
5. Preserve the `single_hit_segment` special case computed from the **segment's full matched count** supplied by C2 evaluator, not from request-wide M or current heap length.

Do not invent a separate C2 candidate comparator, hash table, sorted heap, distinctness policy, rank map, per-segment M-sized array, or alternate cursor constructor. The C2-only callback is a small adapter to **existing** B2/B3 candidate handlers. It may duplicate a few dispatch lines from the accepted loop but must not duplicate their ranking/validation algorithms. A proposed shared candidate wrapper that changes the Legacy loop's per-candidate code is **not permitted**: historical 15I-C warns against unqualified generic codegen changes. Keep the Legacy candidate block mechanically identical.

### 5.2 Per-candidate callback — exact prescribed order

The callback invoked by `execute::visit_strict_term_scored_with` must (with per-segment binding performed in the parent C2 loop at its original source position, never as an ahead-of-all-segments dispatch check):

1. Checked-increment request-wide `total_hits` once. On overflow return the established `ResourceLimit {limit:u64::MAX,requested:u64::MAX}`; do not saturate. The count includes matches rejected by Top-K and by `request.after` (cursor requests are excluded from C2 entirely).
2. Confirm the ordinal binding exists (the selector promised Ready). This is a runtime corruption guard, not a new optional capability check.
3. Initialize/resolve `KeyBinder` at the original first-candidate boundary. A capacity/allocation refusal downgrades just that segment's key processing; true errors propagate.
4. If B3 `KeyBinder::Ready(identity)`, call the already accepted `consider_compact_ordinal_candidate` with original request/sort, score, `include_score=true`, binding, audits, `budget`, `heap` and duplicate state. That function already validates numeric row/rank, logical charge, checks true duplicates before a loser is rejected, borrows key on numeric tie, and allocates only for competitive candidates.
5. Otherwise use the accepted `reader.doc_key_selected` when `single_hit_segment`, else `reader.doc_key`, then call `consider_ordinal_keyword_candidate` with the same arguments. This is the **original owned-key fallback** for ExactSet or refused B3 directory.
6. Do not construct any `SelectedHit` outside those established handlers; do not add a new per-candidate vector, memoization map, or scoreboard. Leave the physical score bits buffer in `execute.rs` until its callback has returned.

Once `visit_strict_term_scored_with` completes a segment, drop any local geo/sort scratch and release its reservations at the accepted segment boundary. Continue to the next segment even if the global heap already holds K+1 entries. The second or later segment may expose corruption/cancellation that the first segment did not.

### 5.3 One canonical finalization

Both the Legacy and C2 bodies must use the **same existing** terminal logic: `heap.into_sorted_vec().into_iter().map(|e| e.hit).collect()`, canonical sort order, K+1 lookahead, build `UnifiedCursor::new(self.snapshot.binding_id(), fingerprint, last.sort_tuple.clone(), if relevance && scoring { last.score } else { None }, last.key.clone())`, truncate to K, and return `(selected,total_hits,next_cursor,aggregation_result)` to the **unchanged** outer `execute_unified`. **There is no `last.score_if_relevance` member**; the explicit conditional matches the accepted source and preserves `None` for non-relevance sorts. You may extract the already existing ~20-line finalization into a private `finish_mixed_heap` function called by both bodies; copy it **mechanically** and retain exact borrow/type behavior. C2 cannot emit aggregation; Legacy retains the existing aggregation finish before finalization. Do not alter cursor encoding, `project_selected_hits`, response bytes, batch scope, `select_keys`, sorted-result tie resolution or emitted generation/view ordinal.

### 5.4 No-benchmark requirement

C2 is correctness-first: **do not run** `quervant-bench stage/run`, Criterion, `cargo bench` with execution, `perf record`, a cross-engine campaign, synthetic latency loops or a hidden microbenchmark. `cargo bench --no-run` is **compile-only** and may be used as an optional build gate if already required by CI. C4 owns every warm-latency decision and must independently measure any low-hit codegen effect.

## 6. Full memory/work accounting and ownership timeline (mandatory mechanical parity)

This table is **the authorized accounting design**. Every entry is a logical charge, including values that have no corresponding physical tree, and must be recorded in a test-only ledger trace. Let `m` be the **per-segment** effective-live match count, `G` be global already-retained heap bytes on entering that segment, and `P=16m`, `S=48m`, `T=64m`, all checked via existing `bytes_for_count`. This is the exact accepted strict evaluator's `TERM_POSTING_BYTES`, `SET_BYTES_PER_ENTRY`, and `SCORED_MAP_BYTES_PER_ENTRY`. `N` is per-segment effective-live documents. The actual Top-K candidate bytes `G` vary with the heap; do not replace it with a fixed estimate.

| Checkpoint | Segment entry charge | Segment bytes | Combined byte admission | Existing source / C2 action |
|---|---:|---:|---|---|
| Prior segment complete | 0 | 0 | `G` | `CandidateBudget::begin_segment()` checks zero |
| Decode i-th effective-live posting | `i` | `16i` | `G+16i` | `build_leaf_data`, validates source and `freq`-charges scanned postings |
| After full postings decode | `m` | `P` | `G+P` | one owned posting vector, no extra allocation |
| After logical matched admission | `2m` | `P+S=64m` | `G+64m` | `ledger.reserve_with_memory(m,48m,None)` |
| After logical scored admission | `3m` | `P+S+T=128m` | **`G+128m`** | `ledger.reserve_with_memory(m,64m,None)`; **must pass** before scoring |
| After all eager BM25 scores | `3m` | `128m` | `G+128m` | same allocation rewritten in place as `(doc_id,score_bits)`; no heap yet |
| Release matched (`S`) | `2m` | `80m` | `G+80m` | first accepted release |
| Release decoded leaf (`P`) | `m` | `64m` | `G+64m` | second accepted release; moved vector is now scored output |
| Release logical scored (`T`) | 0 | 0 | `G` | third accepted release; `ledger.finish()` then drop ledger |
| C2 callbacks / K+1 admission | 0 | 0 | `G'` (existing top-K accounting) | scored bits vector lives as the accepted scored output did; original B2/B3 heap charges only |
| Segment exit or error | 0 after release/RAII | 0 after release/RAII | surviving G until request ends | candidate heap/output owned by query; no persistent mutation |

**Do not charge the same allocation twice:** `P` is the existing retained leaf logical charge. When that allocation is repurposed to hold score bits, it physically replaces the old *second* scored output, but C2 still models both `S` and `T` as in baseline until the same release boundaries. `S/T` are compatibility charges, not a declaration that physical trees exist. A new additional logical charge for the in-place score bits would create a **stricter resource limit**, prohibited by C1. Removing `T` would create a **weaker limit**, also prohibited. The ledger must be atomic (checks before commits) and RAII releases all outstanding charges on failure. Heap accounting begins only after the segment ledger has returned to zero, exactly like baseline.

**Boundary ledger worksheet (agent must complete with actual values and tests before implementing):**

| Request K | Request M | Route | Example per-segment `m` | Peak segment entries/bytes | Required observed behavior |
|---:|---:|---|---:|---|---|
| 1 | 0 | Legacy | 0 | Legacy unchanged | exact count 0, no cursor |
| 1 | 1 | Legacy | 1 | Legacy unchanged | exact single hit |
| 1 | 2 = K+1 | Legacy | 2 | Legacy unchanged | lookahead/cursor parity |
| 1 | 3 = K+2 | C2 | 3 | `9 / 384` | first eligible boundary; final top1 + valid cursor |
| 10 | 10 | Legacy | 10 | Legacy unchanged | 10 hits, no extra page |
| 10 | 11 = K+1 | Legacy | 11 | Legacy unchanged | 10 hits + cursor |
| 10 | 12 = K+2 | C2 | 12 | `36 / 1536` | 10 hits + cursor, all 12 scored |
| 100 | 101 = K+1 | Legacy | 101 | Legacy unchanged | cursor still correct |
| 100 | 102 = K+2 | C2 | 102 | `306 / 13056` | 100 hits + cursor, all 102 scored |
| 10 | 12 across segments `1 + 0 + 11` | C2 | 1 / 0 / 11 | `3/128`, `0/0`, `33/1408` | global G overlaps each segment's 128m peak; segment `m=1` keeps selected-key optimization; no cross-segment leak |
| 10 | 12 across segments `0 + 12` | C2 | 0 / 12 | `0/0`, `36/1536` | empty first segment still charges its N examination |

At the maximum admitted segment m, checked multiplication overflow yields the **same** `ResourceLimit` type before any score or candidate, not a panic. `CandidateBudget.max_segment_entries` bounds peak **3m**, not merely m; `max_total_candidate_bytes` bounds `G+128m` at logical peak. Exercise exact and one-under / one-over thresholds with the **same query and same accepted source**, forcing Legacy only through the test seam, never by changing the limits in the reference run.

**Owned identities:** A `DocumentKey` is a stable logical key and **not** a physical `doc_id`. Numeric B1 ranks are scoped to the exact snapshot and may change on refresh. B3 hashes are runtime-only prefilters, and collisions require exact raw bytes. Each segment's scored-bit vector is request-local and does not survive `GuardedSegmentReader`, projection or cursor. The index writer, immutable segment bytes, manifests and local/remote stores are read-only in the query; there are no C2 durability writes/recovery states to test beyond existing real-index lifecycle.

## 7. Error precedence, state transitions and failure matrix

### 7.1 Reference stage order, not just final error type

The accepted `collect_mixed` order for the eligible query is: request validation → cursor/schema compile → guarded reader schema/live validation → expansion → snapshot statistics → B1 rank map preparation → one request's heap/duplicate policy initialization → for each segment: `ColumnAccess`, ordinal binding, JSON/geo-sort setup → **full posting decoding + logical N examination** → logical matched reservation → logical scored reservation → **score every matched doc** → release all per-segment charges → candidate numeric/key/duplicate processing → next segment → canonical heap finalization → projection/response. C2 must respect each observable error boundary and not allow a later stage's defect to hide an earlier one.

In particular:

- A score error on the final matched document **must beat** a corrupt key on the first matched document in the *same segment*, because score evaluation happens before candidate key resolution in baseline. A C2-only injected score fault is **a structural-order adversary**, not independent proof that the unmodified Legacy evaluator produces the same injected error (the injection intentionally does not affect Legacy). Actual parity claims for real typed faults must be backed by authentic source/codec fixtures exercised against the same request in both modes where feasible, or explicitly recorded as an unverified residual requiring a maintainer decision rather than inventing equality. The new score-bit conversion happens entirely before callback. This is a first-class adversarial test, not an assumption.
- A malformed posting late in the same term **must beat** early candidate-key/sort failures, because decoder completes before scoring and candidate admission. C2 may not process a partially decoded stream.
- A B1 map or invalid ordinal failure before candidate processing **must not** become an optional fallback. A truly optional B1 `NotAvailable` chooses Legacy early. B3 optional key directory refusal after route selection chooses only the **owned-key** handler for that segment.
- In a multi-segment snapshot, baseline processes whole segment 0 before whole segment 1; C2 retains the same segment order. An error in segment 1 invalidates the entire response even after segment 0 contributed heap entries; the heap is simply dropped.
- Error precedence across **different** segments and within zero-hit setup must be checked against the accepted forced-Legacy seam; do not introduce eager all-segment posting scanning or all-segment ordinal bind checks before normal per-segment execution.
- No fallback is allowed after starting a specialized segment. After a malformed posting, score, key, rank, duplicate or resource failure, abort the query with the original typed error; do not retry on Legacy using spent work quota.

### 7.2 Failure classes

| Fault or boundary | Required outcome | State/cleanup and oracle | Test |
|---|---|---|---|
| Invalid query, sort, K, projection | Exact accepted typed validation error in original order | No reader/match touched | C2-U03, I07 |
| Cursor wrong snapshot / invalid fingerprint | Existing cursor error; Legacy path | No C2 physical counters | C2-U16, I05 |
| No postings, K or K+1 matches | Legacy; exact output | No new owned score buffer | C2-U01, U02 |
| Late truncated/nonmonotone posting or bad frequency | Typed segment error from original decoder | No candidate callback for that segment, no response | C2-U04, U12, I06 |
| Corrupt field/sort ordinal or malformed DOC_KEYS, including unselected key | Existing typed error, not `NotAvailable` | No partial response; repeat remains typed error | C2-U12, U14, I06 |
| Stale/foreign ordinal binding or bad segment rank translation | Typed error **when that segment is reached**, after all preceding segments | No speculative eager all-segment bind, no Legacy replay or mixed numeric/string result | C2-U17 |
| B1 optional capacity/legacy unavailable | Legacy chosen before any candidate | Full result/error differential | C2-U17 |
| B3 optional key directory capacity/allocation refusal | C2 retained, segment owned B2 path | Same full hits, projection and sort; no retry | C2-U17, I04 |
| B3 forced hash collision / exact duplicate | Full byte comparison, duplicate typed error only for actual same key | Rejected loser does not bypass duplicate check | C2-U15, I04 |
| `InvalidScore` on losing document | Typed `InvalidScore` before key/rank collector | Later callback not reached; error beats earlier key error | C2-U07, U12 |
| Work/occurrence limit exactly and one-over | Exact accepted boundary and variant | Nonnegative charges; none leaked | C2-U05, U10 |
| Matched/score logical reservation threshold one-over | Original `ResourceLimit` with same limit/requested values | Atomic rejection before score/candidate | C2-U10, U11 |
| Cancellation during posting decode / N charge / scoring prelude / between segments | `SearchError::Cancelled` at accepted poll/charge points | Complete heap and scratch drop; no response | C2-U13, I08 |
| Fallible owned key/sort/heap allocation | Established `ResourceLimit`, heap unmodified on preflight failure | No partial result | C2-U11, U14 |
| Snapshot refreshed/deleted/compacted with old PIT pinned | Old snapshot exact, new snapshot current | No persistent mutation or stale map reuse | C2-U18, I03 |
| Unexpected runtime one-term shape after selector | Established `CorruptIndex` | Fail closed; do not fall back after partial operation | C2-U04 |
| Process crash / remote outage / durable write | **No new C2 recovery protocol**; existing reader/storage returns existing typed error | Existing CI RustFS regressions only; C2 does not write | G8 |

**No change to on-disk formats or mutation atomicity.** The only atomic transition added is internal query scratch state: frequency bytes → score bits in the same allocation. It is published to the collector *only after all scores have succeeded*. A partial overwrite on failure is dropped and never returned or stored.

### 7.3 Performance neutrality is a future measured acceptance gate

C2 must not claim its split generic/fast source structure is performance neutral. Historic PR 15I-C measured large **generic path** regressions even with disabled physical operator. C2 tests prove the correct Legacy route and no new per-document dispatch. **C4** must measure absent/rare low-hit nonprimary lanes under a predeclared guard; if C4 rejects the C series, retain immutable negative evidence rather than retune. C2 may inspect source/codegen *without running real timing* only when a specific build correctness question requires it; no C2 performance signoff is permitted.

## 8. Test implementation — all cases are feature acceptance, not decorative coverage

### 8.1 Authorized test-only seams

Within existing `#[cfg(test)]` modules in `unified.rs` and `execute.rs`, implement exactly:

- A **thread-local RAII** override that forces `LegacyUnified` **only at the final request-local route decision**. It does not change request, compiler, sort, reader, map, score, or budgets. It is visible only to unit tests, not integration targets/release. The override restores the prior thread value on `Drop`, including unwinding. This provides the strongest same-query same-snapshot differential: normal selected physical route versus the exact accepted Legacy route.
- Thread-local counters for selected `LegacyUnified` / `StrictTermOrdinalTopK` calls, scored rows, direct C2 callbacks, zero new full-M scored-pair allocations, and original pointer/capacity retained during in-place conversion. Keep them **outside production** and do not add a runtime strategy environment variable or feature flag.
- A thread-local single-doc score-failure injector **only** in the new C2 scorer, triggered *after* the normal decoder validated the selected physical row and at its scheduled scoring position, returning a real typed `SearchError::InvalidScore`. This tests error/heap precedence without falsifying the real `FieldStats` implementation. Clear it through RAII; do not modify generic scoring or use a fake index decoder.
- A thread-local test-only over-limit/fault witness if needed to inspect the existing `CandidateBudget`/ledger at reserve/release, but **no production hook** and no separately computed budget that is not the actual `SegmentCandidateLedger` state.

Do not expose a public forced strategy, add `#[cfg(test)]` fields to persisted structs, or introduce new dependencies. For each test, assert that the intended route really executed (not merely that the response happened to match). Every `--exact` filtered command must select **one** named test; `0 passed/0 failed` is not acceptance.

### 8.2 Unit/adversarial matrix (required IDs and stable test names)

Tests should be added to `#[cfg(test)] mod c2_tests` in `unified.rs` and `#[cfg(test)] mod c2_physical_tests` in `execute.rs`. Reuse existing `b3_tests` helpers (§1) and the existing `build_leaf_data` / field-stat fixture helpers. The agent must use real Rust implementation under test and independent literals/forced Legacy for oracles; no copied physical executor in a test.

| ID / test | Fixture and exact check | Oracle and false-positive ruled out |
|---|---|---|
| **C2-U01** `c2_u01_static_dispatch_matrix` | Table of root Term, `And([Term])`, Or, Not, Phrase, Prefix, fuzzy/glob/regex, typed, JSON, geo, aggregate, batch, cursor, no sort, two sort fields, `multi`, malformed sorts, noncolumnar fields | Each ineligible returns Legacy counter, no C2 callback; valid results/typed errors correct |
| **C2-U02** `c2_u02_cardinality_boundary` | K=1/10/31/32/100; M=0,1,K,K+1,K+2; single and multi-segment | C2 fires only when `M>K+1`; exact count and lookahead; no arbitrary minimum |
| **C2-U03** `c2_u03_validation_precedence` | Invalid sort vs invalid projection/query/K, bad cursor binding plus corrupt segment | Same first error and no physical call as accepted Legacy; no readers opened early |
| **C2-U04** `c2_u04_runtime_shape_and_decoder` | Valid sole sorted posting, then a structural bad shape and malformed late posting in a checksum-valid segment | All posting decode succeeds before callback; malformed errors exact, no partial output |
| **C2-U05** `c2_u05_n_work_and_scanned_freq` | N=10000, M>K+1; multiple frequencies and live masks; exact work/scanned caps and one-over | Same shared `MixedWorkMeter` work and `freq`-based scanner limits as forced Legacy, not M-only billing |
| **C2-U06** `c2_u06_exact_total_hits` | High-hit 100K K10/K100 and segment distribution 0+1+M | Literal formula M (including losers), `hits.len()==K`, correct `next_cursor` and order |
| **C2-U07** `c2_u07_late_score_error_beats_key_error` | First matching key corrupt; a late matching row triggers C2-only test-injected `InvalidScore` after actual decode | Structural precedence only: `InvalidScore` is observed and zero callbacks occur in **that segment**. The forced-Legacy path has no such injector and must **not** be cited as same-fault error parity; separately test real score/budget/corruption parity with shared-source faults |
| **C2-U08** `c2_u08_score_bit_parity` | Seeded 64 cases covering tf/frequencies, varying lengths, absent/rare/medium/common, K=1/10/100, both directions | Every returned `score.unwrap().to_bits()` equals forced Legacy; lexical score never `None` |
| **C2-U09** `c2_u09_inplace_allocation_identity` | Real decoded `Vec<(u64,u64)>` length M; record pointer/capacity before and after in-place rewrite | Same pointer and capacity; zero created `Vec<(u64,f64)>`, callback count M and no second postings reader |
| **C2-U10** `c2_u10_virtual_ledger_exact_boundaries` | m=0/1/K/K+1/K+2/102; `G+16m`, `G+64m`, `G+128m` exact and one-below/one-over | Same typed `ResourceLimit {limit,requested}` and same accepted vs forced Legacy peak counters; no weakened cap |
| **C2-U11** `c2_u11_preflight_atomic_and_raii` | Fault at decoded reserve, matched reserve, score reserve, injected score error, owned key/heap reserve | Ledger zero after each failure; retained G unchanged if preflight fails, no successful response |
| **C2-U12** `c2_u12_corrupt_selected_unselected_and_multi_fault` | Late invalid posting/UTF8 DOC_KEYS, malformed sort column, score error plus key error | Accepted typed error context and precedence; no early K stop |
| **C2-U13** `c2_u13_cancellation_progress` | Cancel at decoder, N work, last score prelude, first/last candidate and between segments; no-hit setup | Same accepted observable outcome and no leaked ledger charges |
| **C2-U14** `c2_u14_numeric_rank_null_missing_multione` | Asc/Desc, null/missing first/last, equal rank ties, MultiOne retained, selected/unselected corruption | Canonical B2 comparator, string sort tuple and score bits equal forced Legacy |
| **C2-U15** `c2_u15_duplicate_collision_and_loser` | Retained duplicate key; losing duplicate; two distinct keys with equal forced hash | Actual duplicate errors before loser suppression, different keys never collapsed |
| **C2-U16** `c2_u16_cursor_sentinel_and_legacy_continuation` | M=K+2, multiple pages, K=1 and 10, equality ties; wrong PIT binding | K+1 result and full canonical cursor, continuation routes Legacy and yields no skips/duplicates |
| **C2-U17** `c2_u17_ordinal_unavailable_and_b3_refusal` | B1 all documented NotAvailable causes; one segment B3 metadata cap refusal, forced ExactSet duplicate mode; **later-segment ordinal-binder fault after an earlier segment's scoring error** | B1 chooses Legacy before candidate; B3 stays selected with owned B2 key fallback; ExactSet unchanged; no eager all-segment ordinal binding and no later-segment error overtakes earlier one |
| **C2-U18** `c2_u18_pit_mutation_and_mixed_segments` | Refresh/update/delete/tombstone/compaction, old PIT pinned, two/three segments | Exact effective-live count, old/new views independent, rank snapshot-bound and no leak |
| **C2-U19** `c2_u19_sibling_paths_untouched` | `select_keys` mutation, batch retained response, aggregation, typed/Boolean/phrase | C2 counter 0, exact legacy results/charges, no new public path |
| **C2-U20** `c2_u20_generic_hot_loop_isolation` | Use same strict query in forced Legacy; absent/rare, plus disabled fast shape, before and after refactor | Generic body statement/effect parity, no C2 callback; source inspection verifies separate functions |
| **C2-U21** `c2_u21_work_budget_exhaustion_after_prior_segment` | Segment A provides candidates; segment B fails work/posting scan/memory | Whole request returns typed error; no partial page, old heap dropped |
| **C2-U22** `c2_u22_seeded_differential_matrix` | Fixed seed `0xC2_2026_1125`; 128 bounded, deterministic cases spanning 1–4 segments, 0–500 docs, K=1/10/31/32/100, masks, equal keywords and var-freq, corrupt-free cases | Exact `UnifiedResponse` key/order/count/field values/generation/view, cursor presence and score `to_bits()` versus test-only forced Legacy; for K=100 cases ensure some M>K+1 |
| **C2-U23** `c2_u23_b1_b2_b3_reuse_witness` | Ordinal Ready, compact binder, losing Single, numeric tie, MultiOne, ExactSet | Established B1/B2/B3 observations show reused path; no new owned loser's `DocumentKey` or new scorer routine |
| **C2-U24** `c2_u24_zero_effect_and_error_repetition` | Same snapshot, repeat after resource/score/cancel fault with independent cleared hook | No sticky malformed/ready state, no cross-request `KeyBinder` or score-buffer reuse |

**Baseline test source:** existing `b3_tests` in `unified.rs`, `b2_tests`, `b1_` tests, `perf06_b3_keys.rs`, `perf06_b2_ordinals.rs`, `perf06_b1_ordinals.rs`, `pr15h_a_candidate_materialization.rs` and `pr15h_a2_dispatch.rs`. They are **regressions**, not proof of the new C2 in-place function. Do not delete ignored tests or change historical rejected-performance fixtures.

### 8.3 Public-path integration matrix (new dedicated test target)

Create `crates/quervant-core/tests/perf06_c2_physical.rs` (exact new path) using the existing real `Index`, `FsDirectory`, writer/commit/reopen, `AnalyzerRegistry::builtin`, and public `UnifiedSearcher` APIs. Integration tests cannot access crate-private `#[cfg(test)]` counters: use an independent input-derived answer oracle and semantically equivalent ineligible `And([Term])` for *observable* fallback parity. For exact same-query route parity, use the unit-only forced-Legacy seam above. Place temporary files under uniquely owned temp directories with RAII removal and avoid external services.

| ID / integration test | Real topology and required assertions |
|---|---|
| **C2-I01** `c2_i01_10k_100k_exact_term_k10_k100` | Real writer→commit→close→fresh `FsDirectory` reopen; **use the test-local `IndexLimits` recipe below** for the 100K single-commit corpus. B4-formula corpus: `doc_id=d{index:08}`, group medium iff `i%8==0`, key common for even i≥2, singleton at i0; 10K/100K, absent/rare/medium/common, K10/K100. Exact `total_hits`, ascending first `min(K,M)` keys, full projection and `next_cursor.is_some() == (M>K)`; no benchmark timing. |
| **C2-I02** `c2_i02_scores_full_projection_and_reverse_sort` | Field with sortable Keyword, multiple score frequencies/lengths, descending and ascending, equal ranks, missing/null/multivalue-one; compare full projected fields and score bits with semantically equivalent `And([Term])` legacy reference on same snapshot; independent literal oracle for order. |
| **C2-I03** `c2_i03_pit_update_delete_merge_reopen` | Three committed segments, tombstone a matching document, refresh, hold old PIT, compact/merge, reopen; independently calculate effective-live counts and both old/new rankings and generations. Old cursor bound to old PIT remains correct; cross-PIT mismatch typed. |
| **C2-I04** `c2_i04_duplicates_and_optional_fallback` | Segment-level B3 refusal/forced duplicate-mode variants in unit seam; public FsDirectory fixture verifies real keys, duplicate policy, K+1 and semantically equivalent Legacy result. Do not manufacture duplicate live keys in a normal writer; make corruption fixture in a private unit test. |
| **C2-I05** `c2_i05_real_cursor_multi_page` | First page triggers C2; use returned cursor with the **same exact request and pinned snapshot**, follow pages through Legacy, concatenate keys with no gaps/duplicates, compare count and stable projection/score bits. |
| **C2-I06** `c2_i06_corrupt_container_and_legacy_errors` | Rebuild a checksum-valid segment in crate unit test for unselected invalid DOC_KEYS and corrupted postings; real FsDirectory integration verifies authenticated segment rejects malformed committed bytes before success. Do not change manifest or create unsupported on-disk corruption bypass. |
| **C2-I07** `c2_i07_batch_aggregate_and_unsupported_shapes` | Same index, batch request, one real aggregation and typed/Boolean/phrase query; observable results exactly match frozen reference or literal oracle; all ineligible. |
| **C2-I08** `c2_i08_resource_cancellation_atomicity` | Public `SearchLimits` exactly-at/one-over, cancellation and later-segment error; require typed failure and successful independent retry on same immutable index after clearing flag (no partial prior response). Full exact ledger parity remains the private-unit responsibility. |
| **C2-I09** `c2_i09_empty_and_sparse_physical_segments` | Query-global M>K+1 but segment distribution 0/1/M; correct `single_hit_segment` path, order, full count and cursor; corrupt late segment must abort whole query. |
| **C2-I10** `c2_i10_b4_reference_contract_untimed` | Reuse the actual B4 **logical** exact-keyword workload and result semantics (not historical measured samples or latency). On native local index using the **same explicit 100K writer limits**, verify 16 lane oracles for 10K/100K and K10/K100, with score bits checked against an ineligible query. No BM10 `run` or acquisition. |

**Mandatory 100K real-index fixture settings (source-verified):** `Index::create(...)` uses `IndexLimits::default()`, whose `max_pending_docs` is only **10,000**. A 100K single-commit dataset would therefore fail during writer insertion instead of exercising C2. Use **exactly** this existing public API and bounded test-local setting for I01/I10 (and any 100K single-commit fixture); do **not** alter global defaults, index production code, or committed fixture formats:

```rust
let index_limits = quervant_core::index::IndexLimits::new()
    .with_max_pending_docs(1_000_000)
    .with_max_pending_bytes(512 * 1024 * 1024)
    .with_max_replay_entries(1_000_000)
    .with_max_replay_bytes(256 * 1024 * 1024);
let index = Index::create_with_limits(fs_directory, schema(), registry(), index_limits.clone())?;
// writer.insert each corpus row -> commit -> close, then open with the same limits:
let reopened = Index::open_with_limits(reopen_directory, schema(), registry(), index_limits)?;
```

`IndexLimits` is a cloneable type in the accepted source; verify this exact import/trait before using the snippet. The setter for replay bytes clamps at 256 MiB; do **not** write `512 MiB` as an effective replay limit. Follow the accepted B4 adapter's five-field schema and corpus generation formula exactly (keys `doc_id`, `key`, `group`, `body`, `payload`; `doc_id` is indexed/stored/columnar `Keyword`). Populate the other four fields using `benchmarks/quervant_bench/lean/runtime.py::row_values`: row zero `key=singleton`, even positive indices `key=common`, odd indices `key=other`; `group=medium` iff `i%8==0`; `body=alpha beta` on even rows and `gamma delta` on odd; `payload=payload-{index:08}` (no `d` in the payload) per the checked-in formula. Test the four exact-term classes: `absent=(key,never)`, `rare=(key,singleton)`, `medium=(group,medium)`, `common=(key,common)`; compare with independent counts `0,1,N/8,N/2-1`. Sort `doc_id ASC`, project `doc_id`, assert returned score bits against forced-Legacy/unit counterpart. **This is a correctness fixture, never a timed benchmark.** If the public `Index` API or the corpus formula changes materially on a newer main, HARD STOP D04/D64 rather than choosing a different index/benchmark workload.

**Oracle discipline:** `expected_answer(n,field,term,k)` from BM10 is a reviewed independent formula and can inform literal expected results, but C2 tests must construct/query the real Rust writer and reader, not mock the Quervant search engine. The public integration test's `And([Term])` is an independent **legacy route**, not an independent mathematical count oracle; always pair it with literal expected counts and keys. A full `UnifiedResponse` equality check must be careful about the query fingerprint in cursor tokens: a semantically different wrapper query legitimately has a different cursor fingerprint. Compare cursor *presence* across different query expressions and verify pages using each expression's own cursor; test-only forced Legacy with the **identical** request verifies cursor bytes/identity exactly.

### 8.4 Invariant-to-test trace and adversarial red-first

The ledger C2-I01..I20 in §2 is the required traceability index. Before implementation, demonstrate at least one **true** RED condition in the new test-only forced-selection or allocator witness when a case would otherwise be a false positive; record exact test/source/log. If a newly written test happens to pass against old production (because it checks a preserved invariant), **record it as baseline-preserving green**, not fabricated RED. On source changes, first run focused C2 tests and compare against a baseline control. For any discrepancy, isolate the smallest case and classify the failure before making a narrow authorized fix. Do not modify the oracle to make a red test green without evidence.

**A negative case cannot be discharged by an unrelated successful test.** For example, one generic public I01 query cannot prove that invalid score on a losing document wins over an earlier key corruption; C2-U07 must execute precisely that multi-fault boundary. The full suite and 85% coverage add assurance but do not replace source-specific acceptance.

## 9. Cross-component impact and files

### 9.1 Permitted changes

| File | Exact authorized work |
|---|---|
| `crates/quervant-core/src/search/execute.rs` | Add the single strict-term in-place scored-posting evaluator, reuse existing private ledger/helpers, add `#[cfg(test)]` witnesses and unit/adversarial tests |
| `crates/quervant-core/src/search/unified.rs` | Extract generic hot loop mechanically, implement one request-local dispatch into new physical loop, wire existing B1/B2/B3 numeric/key/heap helpers; shared finalization only; test-only forced Legacy/counters and unit/adversarial tests |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | New public API/FsDirectory vertical-slice and regression integration tests (C2-I01..I10) |
| `docs/pr-artifacts/perf-06-c/PERF06C2_DETAILED_PLAN.md` | Commit this authorized plan **verbatim** into the PR (not an edited alternate design) |
| `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` | Source/contract worksheet, invariant ledger, decision matrix applications, source identities, QA and gate evidence |
| `docs/pr-artifacts/perf-06-c/evidence/c2-*` | New bounded, sanitized text logs and evidence only; do not overwrite other stages' reports |
| `docs/architecture/PERF06C_PHYSICAL_EXECUTION_CONTRACT.md` | **Documentation-only status note**, if needed after implementation; no architecture changes without human approval |
| `docs/ARCHITECTURE.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Narrow C2 implementation/status links **after** relevant gates, leaving historical statuses intact; never declare C4 qualified |

### 9.2 Explicitly protected

**No changes** to `crates/quervant-core/src/search/{score.rs,plan.rs,unified_plan.rs,typed*.rs,topk.rs,memory.rs,work.rs,unified_cursor.rs,limits.rs,error.rs}`, `index/**`, `segment/**`, `storage/**`, `quervant-objectstore/**`, `quervant-distributed/**`, `benchmarks/**`, `Cargo.toml`, `Cargo.lock`, toolchain/CI workflows, `AGENTS.md`, `docs/TESTING.md`, immutable historical result/config JSON, B1/B2/B3 tests/fixtures, C1's approved semantics, or any public contract API. Only changes listed in §9.1 are task-owned. A new test-only seam in a protected file is **not** automatically authorized; use D34 to stop and request an amendment if absolutely necessary.

**No persistence writes** occur in the C2 executor. Index/manifest/segment and RustFS identities remain owned by the writer and readers. C2's one buffer is a query-local in-memory value with no durable format version, migration, remote protocol or crash/replay logic. Normal `FsDirectory` integration verifies that the executor works on genuine immutable committed data; it does not authorize edits to the writer.

## 10. Exact QA, CI, and acceptance evidence

### 10.1 Baseline and feature commands

Use the repository's actual supported toolchains; authoring-time Rust stable `1.98.1`, MSRV `1.85.0`. Refresh version facts at preflight, but do not change `rust-version` or a dependency. Run shell commands under `set -o pipefail` when using `tee`, capture exit codes and exact source SHA in the report.

```bash
# Source preflight (no destructive reset):
git fetch origin main
git branch --show-current
git rev-parse HEAD origin/main
git status --short
git merge-base --is-ancestor bc726420cede2e26681d6e8192b45a5d0169abbf origin/main
# Create task branch once from the verified accepted main, unless safely resuming it:
git switch -c dev/perf06-c2-physical-executor origin/main

# Focused C2 unit feature acceptance:
cargo +1.98.1 test -p quervant-core --lib c2_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --test-threads=1
# Repeat the C2 tests under parallel scheduling to expose thread-local seam leaks:
cargo +1.98.1 test -p quervant-core --lib c2_ -- --test-threads=8

# Relevant already accepted A/B strict physical, key and ordinal regressions:
cargo +1.98.1 test -p quervant-core --lib b3_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b3_keys -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test pr15h_a_candidate_materialization -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test pr15h_a2_dispatch -- --test-threads=1
```

If the integration test target names differ from a source-confirmed path, use `cargo test -- --list` and the **exact** discovered named target; do not count a zero-test filter as PASS, silently change names, disable the tests, or skip a failed target. A command that references an intentionally ignored real-RustFS test and executes zero test bodies is **not** evidence of that integration. Do not run the obsolete historical PR 15I-C timed scripts or treat their tests as accepted capability checks.

### 10.2 Mandatory whole-workspace final QA (not optional)

After the **last executable/test/config change**, commit `TESTED` and run the complete one-time local QA ledger. The C2 implementation does not inherit B4's user-specific test-suite exception: this is a code-bearing PR and **requires** unit/integration/coverage/lint tests.

```bash
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
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
bash benchmarks/scripts/test-scripts.sh
git diff --check origin/main...HEAD
```

**Required coverage scope:** all applicable Rust workspace **production** modules and all targets, no new exclusions, **≥85% line coverage** both default and all features. Record actual numerator/denominator/percentage, ignored counts and tool version. Do not substitute a selective `-p quervant-core` figure for whole-workspace compliance. Check changed lines that are untested; aggregate coverage is not semantic proof. If running the explicit MSRV commands requires a locally absent already-approved toolchain, follow D48 (safe installation allowed only with ordinary toolchain manager and no system/source mutation) and classify actual blocker, not PASS.

**Final source discipline:** source/test fixes after `TESTED` invalidate affected QA and CI results. Rerun affected mandatory commands and refresh `TESTED`. Documentation-only evidence/report commits may follow after TESTED if `git diff TESTED..FINAL -- crates/ Cargo.* .github/ benchmarks/` is empty; record the exact diff. Do not rerun full QA merely because a report was committed. Do not modify frozen C1 docs semantically as a way around failing implementation.

### 10.3 Hosted CI / real integration

Push only to the **single draft C2 PR** and let the existing `.github/workflows/ci.yml` run normally. Verify all job names that exist on this repository (at authoring time: `rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`, `rustfs`) and actual `success` on the final source-equivalent head. For the RustFS job, verify the actual real-service test body executed if the existing harness reports it; a job status without evidence of the required body is not a new C2-specific RustFS proof. C2 does **not change storage or remote semantics**, so add no extra remote tests/bootstrap/containers; the existing hosted RustFS suite is regression evidence. The **new C2 public FsDirectory integration** is feature acceptance and cannot be replaced by that regression.

A PR with green local QA but CI pending is `C2_IMPLEMENTED_LOCAL_QA_PASS_CI_PENDING` (not independently accepted); if CI fails, classify with source/stale head and do not ask to merge. Independent code review and maintainer merge **G10 remain open**. C4 warm acquisition remains separate and unstarted.

### 10.4 Failure classification

Every failed required gate must be recorded as one of: introduced regression; feature implementation defect; deterministic pre-existing failure (proved on the accepted `main` or equivalent evidence); nondeterministic/flaky failure (reproduced and controlled, not guessed); environment/harness failure (specific missing tool/permission/service). A failed gate cannot be relabeled “unrelated” without a baseline reproduction. Preserve red output, source SHA, exit code and a narrow fix; never hide the failure with an automatic retry, a subset rerun or a weakened oracle. When a mandatory service is unavailable, continue safe independent work under DEFER AND CONTINUE but leave the gate BLOCKED.

## 11. Preauthorized Architectural Decisions and Exception-Handling Matrix — binding

**Binding execution rule:** Every foreseeable condition must be classified by its **specific** rule before acting. The rows below preauthorize only the indicated narrow resolution under source-verified preconditions; they do not delegate architecture. If multiple rules match, apply the most restrictive. **AUTO-RESOLVE** means act, record and continue without asking. **DEFER AND CONTINUE** means explicitly block the affected gate/decision, record implications, and keep performing demonstrably safe independent tasks. **HARD STOP** means halt affected work immediately (entire PR if isolation is unsafe), preserve state, and request the smallest specific maintainer decision. Any condition not matched by an explicit rule is **HARD STOP D64** for dependent work. The escalation owner is **maintainer** unless noted “agent”; owner of CI/external environment is **repo/infrastructure owner**. Do not treat a rule as a generalized license to redesign.

Every row specifies: **ID**, **observable trigger / exact source check**, **category**, **preauthorized action**, **forbidden response**, and **required evidence / affected gate / owner**. Applied rows and genuinely unforeseen conditions must appear in the final append-only decision ledger.

| ID | Observable trigger / source check | Category | Authorized action | Forbidden response | Evidence; gate / owner |
|---|---|---|---|---|---|
| **D01** | `origin/main` descends from C1 merge `bc726420…` and C1 contract path exists unchanged | AUTO-RESOLVE | Pin exact base SHA, proceed with C2 branch | Reset to authoring-time SHA, cherry-pick draft C1 | Git ancestry/contract hash; G0 / agent |
| **D02** | C1 semantic contract or required source function has materially changed since this plan | HARD STOP | Report old/new symbols and required design amendment | Guess new semantics or use stale plan | Precise diff, proposal; G0/G1 / maintainer |
| **D03** | Main advanced only by irrelevant docs/evidence; executable anchors unchanged | AUTO-RESOLVE | Use actual latest accepted SHA, preserve provenance | Pretend authoring SHA is current | Relevant blob-ID diff; G0 / agent |
| **D04** | Main advanced with changes to source in §1/§3–§6 | HARD STOP | Reconcile with maintainer before editing affected code | Mechanical adaptation without approval | Changed blobs/contracts; G0 / maintainer |
| **D05** | Task branch does not exist, worktree clean, no destination collision | AUTO-RESOLVE | Create one `dev/perf06-c2-physical-executor` from main | Change main or new arbitrary branch | Branch/base and status; G0 / agent |
| **D06** | Task branch exists and is strict descendant of accepted main with compatible C2 work | AUTO-RESOLVE | Resume without force/reset, classify existing work and evidence | Recreate, overwrite, start second PR | Ancestry, file inventory, stage ledger; G0 / agent |
| **D07** | Task branch exists with foreign/conflicting source edits or divergent base | HARD STOP | Protect all work, request reconciliation | Hard reset, force push, silently cherry-pick | Actual git status/commits; G0 / maintainer |
| **D08** | Foreign untracked/unstaged item outside C2 allowlist exists | AUTO-RESOLVE | Record it, leave untouched; proceed if no collision | Delete, clean or commit foreign work | `git status --short` and path; G0 / agent |
| **D09** | Task-owned output collides with a foreign pre-existing path | HARD STOP | Stop affected path creation; request ownership decision | Overwrite or rename to guessed path | Existing path SHA/owner; G0/G9 / maintainer |
| **D10** | Source has the accepted `single_term_postings_eligible` and `keyword_ordinal_eligible` | AUTO-RESOLVE | Reuse as conjunctive prerequisites | Create second analyzer/optimizer | Code anchors; G1/G2 / agent |
| **D11** | Stats term `doc_freq` is provably **not** effective-live exact for a particular segment/format | AUTO-RESOLVE | Route **whole request** Legacy before any candidate and document format-specific condition | Use approximate count, add a second decoding count, take C2 on uncertainty | Source counterexample and negative test; G2/G4 / agent |
| **D12** | Existing B1 ordinal preparation produces documented `NotAvailable` | AUTO-RESOLVE | Use existing Legacy request path before first candidate | Treat as corruption or retry per segment | Exact variant, route witness; G2 / agent |
| **D13** | B1 ordinal preparation produces `Err`, poison, corrupt rank, cancelled | AUTO-RESOLVE | Propagate original typed error | Turn it into `NotAvailable` or fall back | Error variant/oracle; G2/G5 / agent |
| **D14** | Mechanical extraction of generic loop requires behavior/code-order change beyond borrower plumbing | HARD STOP | Preserve baseline; report exact borrow/semantic conflict | Rewrite generic ranking, add dispatch in hot loop | Specific Rust error and proposed alternative; G2 / maintainer |
| **D15** | Two separated hot-loop functions can share one preflight without re-compilation | AUTO-RESOLVE | Use one request-level dispatch after B1 preparation | Duplicate stats/expand/map preparation | Source diff, call-count test; G2 / agent |
| **D16** | Compiled root is not exact `Lexical(0)` with one Term and one positive leaf | AUTO-RESOLVE | Legacy route; record route-counter negative test | Reuse C2 on wrapper/multiterm | C2-U01; G2 / agent |
| **D17** | Request is batch, aggregate, cursor, relevance sort, multicolumn, JSON/geo/typed/multi selector | AUTO-RESOLVE | Legacy route, unchanged result/cursor | “Optimize” similar shapes | Source eligibility+negative tests; G2 / agent |
| **D18** | Verified M is 0/1/K/K+1, or a no-benefit query | AUTO-RESOLVE | Legacy route, preserve original low-hit work/errors | Lower structural guard to M>K, add percentage heuristic | M proof and counter; G2 / agent |
| **D19** | Verified M>K+1, request-wide B1 map is Ready, and all static C1 predicates true | AUTO-RESOLVE | Select C2 **once** before candidates; keep each segment's actual ordinal bind and translation at the accepted per-segment location | Select by timing/approximation **or prebind all segments ahead of the generic execution order** | Route and multi-fault precedence; G2 / agent |
| **D20** | A decoded posting may fail the supposedly guaranteed strict root-Term membership callback | HARD STOP | Document counterexample; request C1 eligibility amendment | Filter it silently, clone a second accepted vector | Fixture, symbols; G2/G3 / maintainer |
| **D21** | Runtime sole-term shape disagrees with statically eligible source | AUTO-RESOLVE | Return existing `CorruptIndex` before score/admission | Panic, silent fallback or ignore extra leaf | Exact shape and typed error; G3 / agent |
| **D22** | `build_leaf_data` exposes one validated `(u64,u64)` Vec and `take_strict_one_term_postings` exists | AUTO-RESOLVE | Reuse one buffer; move it first, **then** borrow the still-owned term from `leaf_data` for the scorer | Second decoder, term clone, borrowed term retained across mutable move, unsafe workaround | Pointer/borrow-source/test evidence; G3 / agent |
| **D23** | Decoded posting vector would need cloning/sorting to satisfy C2 | HARD STOP | Stop and report source contradiction | Allocate another full-M buffer | Source evidence; G3 / maintainer |
| **D24** | N live-examination formula and `verified_segment_live_count` are available | AUTO-RESOLVE | Use same once-per-segment N charge and cancellation polls | Charge M only or skip zero-match N | Ledger/work oracle; G3 / agent |
| **D25** | Checked full decoded posting `m` fits actual segment entry limit | AUTO-RESOLVE | Reserve P=16m, S=48m, T=64m at exact original sites | Drop virtual S/T charges | Ledger trace; G3/G4 / agent |
| **D26** | `m * 16`, `m * 48`, `m * 64` overflow a `u64` | AUTO-RESOLVE | Return accepted `ResourceLimit` from existing checked calculator | Saturate, truncate, allocate uncharged | Error trace; G3 / agent |
| **D27** | Logical cap fails at P, S or T reservation | AUTO-RESOLVE | Propagate original typed `ResourceLimit`, let RAII release | Skip T, retune limit or retry generic | One-below/one-over and RAII; G3/G4 / agent |
| **D28** | A new physical charge would make formerly valid query fail | HARD STOP | Compare old/new simultaneous peaks and request decision | Add uncompensated score buffer or cap exception | Ledger numeric counterexample; G3 / maintainer |
| **D29** | Removing a virtual charge would let formerly rejected query pass | HARD STOP | Preserve historical logical peak and escalate if unable | Call it harmless memory saving | Old/new exact boundary; G3 / maintainer |
| **D30** | Same posting Vec can be overwritten as `score.to_bits()` via safe Rust | AUTO-RESOLVE | Rewrite `row.1` in-place, return `from_bits` in callback | Unsafe transmute, `Vec<(u64,f64)>`, new score map | Pointer/capacity and bit tests; G3 / agent |
| **D31** | `FieldStats` exists or is legitimately absent in accepted zero-score branch | AUTO-RESOLVE | Use exact `0.0_f64` and accepted `bm25_score`; apply `score += contribution` | Invent BM25 formula, normalize float bits | Bit oracle and source call count; G3 / agent |
| **D32** | `bm25_score` fails for any matched doc | AUTO-RESOLVE | Abort before any segment candidate callback, RAII cleanup | Skip loser error, continue with partial heap | Late-score fault witness; G3/G4 / agent |
| **D33** | Need separate score-only `Vec<f64>` or scored-pair `Vec` to implement C2 | HARD STOP | Stop; report why original in-place buffer cannot suffice | Implement 15I-C-style two buffers or unsafe representation | Source/borrow error; G3 / maintainer |
| **D34** | Task requires editing protected `score.rs`, index/segment/codec, Cargo or CI | HARD STOP | Request narrow signed amendment with exact necessity | Expand allowlist or add dependency | File/symbol; G3/G9 / maintainer |
| **D35** | Physical callback called before full scoring/ledger release | HARD STOP | Restore ordered two-phase evaluation | Interleave score and heap for throughput | Counterexample / error order; G3 / maintainer |
| **D36** | Segment has m=0 or m=1 within an eligible request with M>K+1 | AUTO-RESOLVE | Still process segment, preserve N charge and selected-key optimization | Skip segment’s setup or use global M for key optimization | Multi-segment test; G3 / agent |
| **D37** | B3 key binder returns documented optional refusal after C2 chosen | AUTO-RESOLVE | Keep C2; use owned B2 key path for *that segment* | Replay Legacy after candidate or drop heap | Binding/response oracle; G3 / agent |
| **D38** | B3 hash collides for different keys or duplicate key is a numeric loser | AUTO-RESOLVE | Reuse exact-key equality and original duplicate-before-reject check | Hash equality as identity or skip loser duplicates | Forced collision/duplicate test; G3 / agent |
| **D39** | Resolved duplicate mode is ExactSet, even if ordinal map is Ready | AUTO-RESOLVE | Use original B2 owned key / ExactSet table with its reservation | Invoke B3 compact path on ExactSet | Policy/charge witness; G3 / agent |
| **D40** | Global heap already contains K+1 entries before final matching postings | AUTO-RESOLVE | Continue full count, scoring and candidate duplicate checks | Early exit, approximate `total_hits` | K+1/K+2 oracle; G3 / agent |
| **D41** | Cursor requested on second page of a C2-eligible initial query | AUTO-RESOLVE | Route follow-up to Legacy; validate original snapshot/fingerprint | Reuse first-page numeric temporary across requests | Cursor multistep test; G4/G5 / agent |
| **D42** | Legacy finalization duplicated by C2 and could diverge | AUTO-RESOLVE | Extract exact existing heap/cursor finish to small shared private helper | New cursor schema/last-key rule | Mechanical source diff & cursor test; G3 / agent |
| **D43** | Later segment fails after earlier segment filled heap | AUTO-RESOLVE | Abort entire query and drop partial heap/score vector | Return partial successful first page | Multi-segment fault test; G3 / agent |
| **D44** | Scorer error and key error both occur in same segment | AUTO-RESOLVE | Pre-score complete segment first; return scorer error | Process earlier key first, alter priority | Multi-fault test; G4 / agent |
| **D45** | Corrupt posting payload discovered late in decoder | AUTO-RESOLVE | Typed decode error before first per-segment callback | Stop decoding at K or ignore unselected data | Corruption fixture; G4 / agent |
| **D46** | Test-only forced Legacy/counters could leak between parallel tests | AUTO-RESOLVE | Use thread-local RAII reset/restore; verify with parallel focused run | Global mutable flag/runtime env override | Parallel test evidence; G4 / agent |
| **D47** | Integration test cannot access private unit-only route counters | AUTO-RESOLVE | Use public result+literal oracle and `And([Term])` reference; keep exact route test in lib unit | Expose C2 internals as public API | Split test evidence; G5 / agent |
| **D48** | Standard rustup toolchain absent but approved toolchain manager works | AUTO-RESOLVE | Install pinned supported Rust toolchain through ordinary rustup, no system/source changes | Lower MSRV/disable lints/skip local tests | Version+command log; G7 / agent |
| **D49** | Mandatory check unavailable after safe ordinary setup or hosted CI lacks service | DEFER AND CONTINUE | Record exact blocker and gate, finish independent tests/docs, mark verification blocked | Claim PASS or merge anyway | Command/error/CI URL; G7/G8 / repo owner |
| **D50** | New unit/integration test fails due to clearly introduced narrow bug | AUTO-RESOLVE | Fix only C2 source/tests according to frozen design, preserve RED log, rerun affected QA | Redesign or weaken oracle | Failure classification and green run; G4/G7 / agent |
| **D51** | A failure appears pre-existing on accepted main and reproduces there | DEFER AND CONTINUE | Record baseline reproduction; continue independent C2 work, leave mandatory gate BLOCKED | Delete test or label unrelated without proof | Base vs C2 commands; G7 / maintainer |
| **D52** | A test fails intermittently under unchanged code | DEFER AND CONTINUE | Repeat deterministically, capture scheduling/seed evidence, keep gate unverified | Silent re-run-to-green / “flaky” without proof | Full log+repro; G4/G7 / maintainer |
| **D53** | C2 resource/typed-error parity fails but requires an unapproved behavior change to fix | HARD STOP | Preserve failing oracle and seek architecture decision | Tweak limits, skip charge/validation | Exact old/new error; G3/G4 / maintainer |
| **D54** | All mandatory feature, unit/integration and QA gates PASS at TESTED SHA | AUTO-RESOLVE | Continue documentation/source freeze and normal push | Stop for routine reconfirmation | Source SHA + ledger; G7 / agent |
| **D55** | Engine/test/config changed after passing QA | AUTO-RESOLVE | Rerun affected full final QA/coverage; refresh TESTED | Reuse stale counts | Changed path list and rerun; G7 / agent |
| **D56** | Only docs/evidence files changed after TESTED | AUTO-RESOLVE | Prove protected diff empty and reuse source QA; record exact final SHA | Rerun suites just for prose / claim changed code tested | `git diff TESTED..FINAL`; G9 / agent |
| **D57** | C2 execution would require full real benchmark, profiler or retune for proof | HARD STOP | Defer performance to C4; request separately approved work if essential | Run BM10 acquisition under C2 | Scope/demand; G9 / maintainer |
| **D58** | CI jobs pending on source-equivalent head | DEFER AND CONTINUE | Preserve local implementation/evidence, monitor CI to terminal when available; report `CI_PENDING` | Merge, claim G8 PASS, launch extra duplicate workflow | CI run/head/jobs; G8 / repo owner |
| **D59** | Hosted CI has terminal failure | DEFER AND CONTINUE | Classify against exact source/head and correct only narrowly introduced issue; rerun affected local QA | Ignore failure or start unrelated workflow | Job logs/commit and classification; G8 / agent/repo owner |
| **D60** | Real-RustFS integration passed on old or unrelated commit only | DEFER AND CONTINUE | Require actual current CI/head body or clearly record unverified regression | Claim G8 from old pass/ignored registration | Actual job log; G8 / repo owner |
| **D61** | Unit or integration runner selected zero test bodies | AUTO-RESOLVE | Discover exact test name with `-- --list`, rerun required target, assert nonzero selected | Treat exit=0 with zero tests as PASS | Test name/count/log; G4/G5 / agent |
| **D62** | All checks green, draft PR branch clean and pushed | AUTO-RESOLVE | Report READY_FOR_INDEPENDENT_REVIEW; G10 stays open | Merge or mark C2 performance qualified | PR, exact source/gate ledger; G9/G10 / agent |
| **D63** | Maintainer has not independently accepted C2 | DEFER AND CONTINUE | Leave draft, keep C3/C4 unstarted, continue only read-only evidence inspection | Declare C2 DONE/merged or start C3 | Review status; G10 / maintainer |
| **D64** | Unforeseen semantic/source/compiler/ownership condition with no exact rule | HARD STOP | Preserve state, emit exact file/symbol and smallest decision; continue unrelated work only if safely isolated | Improvise, choose new architecture, hide failure | Trigger, alternatives, owner decision; affected gate / maintainer |

**Use of the matrix:** Every applied row is a narrowly approved instruction, not a menu of optimization tactics. The default for an unlisted condition with possible semantic impact is **HARD STOP**. A task-specific code fix must respect all prior invariants, never only the condition that made it fail. If multiple failures interact (e.g., score error plus budget exhaustion) derive the actual accepted error ordering and request amendment when the specification is insufficient.

## 12. Ordered autonomous execution phases (no routine approval checkpoints)

| Phase / gate | Exact work | Required evidence and continuation |
|---|---|---|
| **P0 / G0 — source admission** | Fetch fresh main, verify merged C1/ancestry, branch cleanliness, old C2 work classification, inspect `AGENTS.md`, source anchors, CI, existing tests | Preflight log, immutable starting SHA and explicit no-foreign-deletion proof; automatically continue if PASS |
| **P1 / G1 — correctness worksheet** | Create C2 report before code; map C2-I01..I20, a negative scenario and named U/I test per row; prove buffer and ledger state model from §4–§6 | Preimplementation worksheet and design challenge answers; STOP if contradictory |
| **P2 / G2 — mechanical routing** | Extract accepted legacy segment loop out-of-line, implement one preflight route choice with M/K+1 and B1 Ready; add test-only forced Legacy/route observation | Unit dispatch/static/ineligible tests; exact generic source diff and no per-doc mode switch |
| **P3 / G3 — in-place evaluator** | Implement sole-buffer complete posting validation, N work, logical admissions, eager BM25 in-place `to_bits`, release/finish, callback handoff | Source/ownership trace; C2-U04–U13 tests, pointer witness, no additional M scored array |
| **P4 / G3 — B2/B3 collector integration** | Call established numeric candidate handlers, per-segment key fallback and K+1 cursor finalization; no public API or codec change | C2-U14–U17 and exact-count/score error parity |
| **P5 / G4 — adversarial unit acceptance** | Execute full C2-U01–U24, mandatory RED/green evidence, seeded differential and multi-fault errors, source/ledger decision matrix | Source/test SHA, selected counts, independent oracles, no false pass |
| **P6 / G5 — real index integration** | Implement C2-I01–I10 through genuine native writer/commit/reopen/PIT/query, then run suite | Actual FsDirectory integration selected/passed counts; not fake-only |
| **P7 / G6 — regression suite** | Run existing B1/B2/B3 strict tests, historical retained public tests and batch/cursor/mutation regressions | Named suites, negative/ignored counts, source-equivalent evidence |
| **P8 / G7 — source freeze and full local QA** | Commit TESTED source, run §10.2 stable+MSRV, all-feature tests, ≥85% workspace coverage, docs, compile-only and script tests | Full exact command/coverage ledger; after source change rerun affected tests; no timed benchmark |
| **P9 / G8/G9 — delivery** | Commit verbatim plan, append report/decision ledger, narrow docs, push one draft C2 PR. Verify TESTED→FINAL protected diff and ordinary hosted CI; no force | PR URL/draft, exact SHAs, CI run/actual jobs, all allowlisted files |
| **P10 / G10 — independent review handoff** | Review own diff adversely against source+C1+plan, record residual risks; do not merge | `PERF06_C2_READY_FOR_INDEPENDENT_REVIEW` **only** when G0–G9 verified; G10 always maintainer-owned/open |

**Continuous-execution confirmation:** do not stop after P1, preflight, first successful test, stage completion, CI check, or any AUTO-RESOLVE decision. Only a named D rule or truly external dependency may block dependent work. When CI is pending, complete all safe independent local/report tasks and deliver a truthful pending disposition; never promise completion or merge in the future.

## 13. Acceptance gates and completion vocabulary

| Gate | Requirement for PASS | If not met |
|---|---|---|
| **G0** | Main contains merged C1; one clean task branch; no foreign workspace changes harmed | `STOP_SOURCE` or pending identity resolution |
| **G1** | Pre-code C2-I01..I20 traceability, negative challenges and finite state/ledger worksheet complete | HOLD affected implementation / HUMAN DECISION |
| **G2** | Static/ready/M selection exact; single preflight; separate generic and C2 hot-loop functions; no second query compile | C2 implementation incomplete |
| **G3** | In-place score bits reuse one decoded vector, all matched eager scores, B2/B3 current handlers, exact virtual ledger+error order | BLOCKED / HARD STOP on semantic variance |
| **G4** | Actual named C2-U01..U24 pass including negative/seeded/fault/ledger/bit comparisons; existing B1/B2/B3 regressions pass | BLOCKED; no generic suite substitution |
| **G5** | Real `FsDirectory` writer/commit/reopen/snapshot/PIT/cursor C2-I01..I10 executed/pass | BLOCKED; unit fake does not count |
| **G6** | All applicable accepted strict path, mutation, batch/aggregate regressions execute/pass | BLOCKED, classify failures |
| **G7** | Full local stable+MSRV fmt/Clippy/tests/doc/compile-only, script tests; all workspace line coverage ≥85% default/all-features; no exclusions | `IMPLEMENTED_VERIFICATION_BLOCKED` |
| **G8** | Five ordinary hosted CI jobs terminal success on final source-equivalent SHA, relevant real RustFS body confirmed when applicable | `CI_PENDING` or `CI_FAILED` |
| **G9** | Only allowlisted code/test/doc files changed; plan verbatim, report append-only, durable evidence, final source freeze, draft PR, no C2 benchmarks | BLOCKED delivery |
| **G10** | Independent reviewer accepts C2 and maintainer approves merge | **OPEN to coding agent always** |

**Disposition vocabulary:**

- `PERF06_C2_READY_FOR_INDEPENDENT_REVIEW` — source and G0–G9 mandatory evidence PASS; draft/unmerged, G10 OPEN. **Not** a warm performance result.
- `PERF06_C2_IMPLEMENTED_LOCAL_QA_PASS_CI_PENDING` — code, feature and local QA PASS, hosted CI not terminal.
- `PERF06_C2_IMPLEMENTED_VERIFICATION_BLOCKED` — code may exist, at least one required test/coverage/integration/host gate not verified.
- `PERF06_C2_STOP_<Dxx>` — relevant hard-stop rule, unresolved design/semantic/scope decision; preserve source/evidence.
- `PERF06_C2_NOT_IMPLEMENTED` — no meaningful executable delta; do not call C2 done because plan/docs exist.

Never record `DONE`, `MERGED`, `C3 STARTED` or performance-improvement claims from the coding agent. Roadmap status may say implementation complete **pending independent review** only after G0–G9 PASS.

## 14. Required append-only execution report and review checklist

Create `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` with these mandatory sections:

1. **Identity:** repo, accepted C1 main SHA, branch/PR, START, BASE, TESTED, FINAL and remote-verified SHA; exact `git diff TESTED..FINAL` for protected source; clean tree proof; if main advanced, ancestry/semantic reconciliation and D rule.
2. **Source delta:** exact file/symbol change map, generic hot-loop mechanical move proof, one request-level route, in-place evaluator and callback, B2/B3 reuse, unchanged public/format/storage/reader paths.
3. **Invariant ledger:** for each C2-I01..I20, status, named negative and positive test, actual executed command, pass/fail/ignored count and evidence. Detail rejected wrong result/counterexample for each high-risk invariant.
4. **Accounting worksheet:** explicit per-segment `m`, historical P/S/T and G overlap at every checkpoint; exact one-over boundaries, observed typed errors and all release/unwind counters. Explain why the retained decoded buffer after score conversion occupies the same phase/size as the accepted scored output and causes no new peak.
5. **Selection trace:** all §3.2 outcomes, request-global M certificate on valid indexed input, static and dynamic eligibility, source of B1 Ready, exact per-segment B3 optional refusal and forced ExactSet handling.
6. **Error precedence:** matching-query corruption, late posting failure and late injected `InvalidScore` vs early malformed key, no partial response, cancellation at all stages, repeated same-snapshot independent query success after fault cleared.
7. **Scoring and ordering:** seeded cases, score `to_bits` parity, `total_hits`, K+1 cursor, all sort directions/null/missing/MultiOne/key ties, returned projection and PIT stability.
8. **Actual QA:** stable/MSRV versions, test counts/ignored, whole Rust workspace default/all-feature measured line coverage and denominator, Clippy/fmt/doc/script/compile-only exact commands/exit codes, real FsDirectory topology and hosted CI/RustFS body or precise blocker.
9. **Rule ledger:** D01..D64 applied with trigger, action, evidence, gate/owner; any deferred/STOP state and minimal decision. Classification of every failed gate as introduced, feature, baseline, flaky or environment with proof.
10. **Residual risk and performance status:** historical 15H/15I negative results preserved; no measured warm gain, no C3 deferral, no codegen neutrality guarantee, no new persisted format; C4 owns adoption. Any accepted test limitation must have explicit maintainer disposition, never hidden by coverage.
11. **Handoff:** draft PR URL, G0–G9 status, G10 OPEN, no merge, no C3/C4 start, final exact disposition.

### Final adversarial self-review (answer all before handoff)

- Is C2 ever selected for `M<=K+1`, a non-strict root, a cursor or batch? Has a test proved each **actual route**, not only the response?
- Can one invalid late posting be hidden by stopping after K? Did the authentic decoder traverse and validate the whole posting stream?
- Does an eligible request charge **N** live examinations and every scanned term frequency, including dead physical postings? Does multi-segment G overlap match the original ledger?
- Has the original sole posting Vec's **same allocation** been converted to bits, with no second M scored Vec or score-only array and no unsafe cast?
- Is the entire segment scored before **any** candidate key/duplicate/sort check, so late `InvalidScore` or malformed postings win the accepted error-precedence contest?
- Does every final lexical score match accepted `to_bits`, including the zero-score branch? Does any score change cause a separate error or signature?
- Are B1 rank map, B2 exact lexical sort/key tie, B3 hash prefilter with full collision equality and ExactSet owned path all the same symbols as before?
- Is K+1 preserved, and does a follow-on cursor use Legacy with the same snapshot binding/fingerprint and no gap/duplicate?
- Are snapshot/PIT updates, tombstones, compaction, batch/aggregate/mutation `select_keys` unchanged by the dispatch?
- Is the generic hot loop in a **separate** function with no per-match selector, no new scoring/branch hint, and preserved statement/error order? Was PR 15I-C negative evidence retained?
- Did *every* named acceptance test execute, not merely compile; did whole-workspace coverage exceed 85%; are CI/head/real-service claims backed by actual logs?
- Did the agent avoid **all** real benchmarking/profiling and avoid starting C3? Is G10 still maintainer-owned?

If any answer cannot be supported by executed evidence or source reconciliation, the relevant gate **cannot be PASS**.

## 15. Suggested draft PR description (copy after actual implementation; do not claim results not yet observed)

```markdown
## PERF-06-C2 — strict-term physical execution

Implements the accepted C1 request-local StrictTermOrdinalTopK path for eligible standalone single-analyzed-term queries with one sortable Keyword column, B1 ordinal readiness and proven M>K+1. Generic query shapes remain on the unchanged legacy loop.

The new per-segment evaluator reuses the validated sole `(doc_id, freq)` posting allocation, performs complete N/matched/scanned work charging, preserves virtual 16/48/64-byte logical reservations, **eagerly scores every matching document**, and safely overwrites its frequency words with BM25 score bits in place. After all scores/ledger cleanup, it iterates the same allocation directly into the existing B2/B3 K+1 collector. No second full-M scored-pair Vec, new BM25 implementation, public API or index format.

Includes C2-specific adversarial unit tests, genuine FsDirectory writer/reopen/PIT/cursor integration, forced-legacy exact differential and seeded tests, ledger/late-error/cancellation proofs, and recorded stable/MSRV/coverage/CI results. [Insert actual tested SHA and gate table only after execution.]

No C3 winner-only scoring, BM-10 acquisition, C4 qualification, unrelated search optimizations, or change to historical rejected performance evidence. Independent review and maintainer merge remain open.
```

## 16. Dependency and closing instructions

C1 (`bc726420…`) is the merged architecture source. C2's only implementation goal is **integrated exact-count strict-term physical execution with eager scoring**, preserving accepted A+B semantics. C3 is a distinct subsequent plan and PR responsible for safely deferring winner scoring; C4 is separately responsible for final correctness/resource review and one approved warm qualification against the **accepted A+B B4 baseline**. C2's new tests and source must be independently reviewed before it can become C3's base.

**No coding-agent design license.** Source conflicts, an unprovable live-count certificate, need for additional score/budget buffers, a changed error ordering, source layout that requires redesign, test fixture limitations that prevent an essential case, new transport/format work, or any condition missing from D01–D64 require **HARD STOP on affected work**, a precise evidence-backed question for the maintainer, and no creative substitution. For a safe independent task the agent may continue, but must never close a dependent blocked gate. All normal authorized steps proceed automatically without renewed approval.


## 17. Second-review corrections and scope of independent verification (revision 2)

This revised plan supersedes the first 658-line draft. Its corrections were made against **merged** C1 at `main@bc726420cede2e26681d6e8192b45a5d0169abbf` and direct source inspection of `unified.rs`, `execute.rs`, `score.rs`, `index/mod.rs`, `index/limits.rs`, the B4 adapter, and the repository authoring/QA guides. **No Rust implementation was compiled, tested or benchmarked during plan review.** The following requirements are substantive, not optional errata:

| Review ID | Former ambiguity/inaccuracy | Binding corrected instruction / verification |
| --- | --- | --- |
| RV2-01 | Pre-binding every segment's ordinals as a prerequisite for request-level dispatch could expose a later-segment error before an earlier-segment decoding/scoring error | Select from **request-level B1 Ready + exact M** only; keep `columns.bind_keyword_sort_ordinal` and `map.bind_segment` at their unchanged per-segment point. Any invalid binding is typed at the accepted point. U17 must exhibit the multi-segment precedence case. |
| RV2-02 | Borrowing the term from `leaf_data` before `take_strict_one_term_postings(&mut leaf_data,...)` leaves an avoidable Rust aliasing/lifetime problem | Capture `field_id` and validate shape first; **move the posting vector**, then borrow the still-owned term from `leaf_data` for the score pass; drop the borrow before releasing `leaf_data`. No clone, new allocation or unsafe. |
| RV2-03 | The original 100K test recipe omitted the default writer's pending-document cap of 10K | I01/I10 use `Index::create_with_limits/open_with_limits` and the pinned bounded fixture recipe in §8.3; preserve all production defaults. |
| RV2-04 | A test-only `InvalidScore` injected only into C2 cannot itself prove parity with an uninstrumented Legacy scorer | Call it a **structural error-order witness** only; use genuine shared-source faults for comparative parity and disclose any residual inability to reproduce authentic late BM25 faults. |
| RV2-05 | `last.score_if_relevance` was an illustrative non-existent member | Call `UnifiedCursor::new` with the exact accepted `if relevance && scoring { last.score } else { None }` expression. |

**Review limit:** These source-supported corrections make the prescribed architecture internally consistent; they cannot certify that the future implementation will compile, pass all adversarial tests, satisfy coverage, or improve latency. All such claims remain G2–G10 requirements to be proved by the agent and independent reviewer. If a further mismatch appears at execution, use the binding D01–D64 decision matrix and **HARD STOP** on unlisted design decisions.
