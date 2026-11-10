# PR 15I-C — Physical execution design (as implemented, then rolled back)

Status: implemented and measured; **not retained** in production because the
frozen performance gate failed (`C-P09`). See `performance-decision.md`.

## 1. Operator

`execute::for_each_exact_term_score_with` is the entire new production surface.

```rust
pub(crate) fn for_each_exact_term_score_with<F>(
    reader: &SegmentReader,
    leaves: &[CompiledLeaf],
    expansion: &Expansion,
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    live: &[bool],
    budget: &mut CandidateBudget,
    meter: &mut MixedWorkMeter<'_>,
    cancel: &dyn Cancellation,
    on_scored: F, // FnMut(u64, f64, usize, &mut CandidateBudget) -> SearchResult<()>
) -> SearchResult<()>
```

It reuses the accepted PR 15E/15H-B machinery unchanged:

* `build_leaf_data` for checked, effective-live filtered posting decoding;
* `MixedWorkMeter` for `1 + freq` scanned occurrences, per-live examination units
  and cancellation;
* `SegmentCandidateLedger` / `CandidateBudget` as the only temporary-memory owner;
* `score::bm25` and `SnapshotStats`/`FieldStats` for scoring;
* `consider_borrowed_keyword_candidate` and `heap_admit_candidate` for the
  canonical K+1 heap and late Keyword materialization.

## 2. Ordered algorithm

1. `SegmentCandidateLedger::new(budget)` (no second budget, `memory = None`).
2. `build_leaf_data(..., memory = None)`; structural assertion that the result is
   exactly one `LeafData::Term` with one `TermPostings` (typed `CorruptIndex`
   otherwise, no partial callback).
3. Move the already-decoded `(doc_id, freq)` vector out of `LeafData` (no copy, no
   re-sort, no second reader).
4. `effective_live_examination_count(live, meter)` once, then
   `meter.charge_lexical(live_count)` once, then `check_cancelled()` per posting.
5. **Virtual legacy matched-set admission**: `ledger.reserve_with_memory(M, 48·M, None)`.
6. **Virtual legacy scored-map admission**: `ledger.reserve_with_memory(M, 64·M, None)`.
7. Allocate one aligned `Vec<f64>` (`try_reserve_exact(M)`, typed `ResourceLimit`
   on failure) and score **every** posting with the exact single-positive-term
   case of `score_segment`: start at `0.0`, add one `bm25` contribution; missing
   `FieldStats` contributes exactly `0.0`.
8. Release matched, leaf and scored reservations in the legacy order, then
   `ledger.finish()` to prove zero segment-owned entries/bytes.
9. Call `on_scored(doc_id, score, M, budget)` in ascending physical doc id with no
   early exit. The callback decodes the logical key (`doc_key_selected` only for
   `M == 1 && doc_count >= 1024`) and admits the candidate through the unchanged
   canonical comparator and heap.

## 3. Why the trees stay in the budget model

The removed `BTreeSet<u64>`/`BTreeMap<u64, f64>` are still *modelled* at the legacy
admission checkpoints. This is a deliberate compatibility policy: no query may be
admitted that the generic path would reject, and the first failure category and
ordering remain identical. The physical trees disappear; the logical peak does
not. This is tested at exact-and-one-below boundaries (`C-U15`, `C-U21`,
`C-U22`).

## 4. Not attempted

Score deferral, winner-only scoring, zero-scratch streaming into the heap, a
postings-format change, a second postings reader, WAND/BMW, approximate counts,
early termination after top-K, or any `unsafe` reinterpretation of
`(u64,u64)` as `(u64,f64)`.

## 5. Measured outcome (finding kept for a future experiment)

The operator does what it was designed to do — on the primary common lanes it
removed 11–21% of query latency at `10K/K100`, `100K/K100` and `100K/K10`, with
bit-identical scores and counts. It nonetheless failed the frozen non-primary gate
because four low-match lanes regressed 1.26–1.72×. The diagnosis in
`diagnostic-stage-profile.md` shows this is a codegen/inlining cliff in
`collect_mixed` triggered by any data-dependent branch before the segment loop, not
the new operator's own work. Removing the branch restores the baseline timings at
identical source. A future, separately approved experiment should restructure
`collect_mixed` (for example, extract both branches into non-inlined methods) and
re-measure before any substrate is re-adopted.
