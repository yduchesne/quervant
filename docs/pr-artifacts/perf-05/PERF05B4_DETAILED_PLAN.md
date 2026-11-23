# PERF-05-B4 — Score Strict Single-Term Candidates Without a Full-M Scored Map

**Detailed, bounded coding-agent implementation contract — 2026-11-22 — version 1.0**

| Attribute | Authority |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Existing PR | [PR #117](https://github.com/yduchesne/quervant/pull/117) — no successor PR |
| Required branch | `dev/perf05-physical-execution-series` |
| Source HEAD inspected | `af69e3859f21fac9dcb0e254dab6a46e1b2cf5c8` (B3) |
| Main ancestor | `9775bfca4c58a27e65ca28c1d705efad00a65ec8` |
| Authoritative documents | `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md`, `docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md` |
| Next stages | Optional B5, then final integrated PERF-05-C |

**Status:** This is an implementation plan only. No B4 implementation, tests, benchmarks or profiles were performed while preparing it. Recheck the branch after pulling; this plan does not authorize applying stale instructions to changed source.

## 0. Mandatory execution and authorization contract

**One objective:** For the existing strictly eligible single-positive-term postings path of `evaluate_lexical_with`, carry the exact original `u64` term frequency alongside each accepted document ID, then compute exactly the current BM25 contribution into a `Vec<(u64, f64)>` **after** the existing matching and modeled resource admissions. Eliminate the eligible path's full-M scored `BTreeMap`, its `get_mut` searches, owner map for the single term, map-to-vector conversion, and the second pass over postings.

**Frozen design:** Add one private helper `score_single_term_candidates` in `search/execute.rs`. Keep B3's `Vec<u64>` for the ineligible branch; add a **separate** `Vec<(u64, u64)>` for the eligible branch. Only one buffer grows to M elements per query. Preserve the generic `score_segment` implementation for all other query shapes and the sibling lexical executor. The helper outputs an owned `Vec<(u64, f64)>`; the evaluator's output type and unified caller stay unchanged.

**Why a separate scored-output vector remains:** In safe ordinary Rust, `Vec<(u64,u64)>` cannot be treated as `Vec<(u64,f64)>` in place without unsafe reinterpretation or packing frequencies into floating-point bit patterns. Both are **forbidden**. B4 removes the full-M scored tree and duplicate postings pass without expanding the public/scorer interfaces or inventing a new representation. B5 separately handles any further postings-buffer lifetime work.

**Continuous execution authorization:** Once the maintainer supplies this approved plan to the coding agent, execute all prescribed stages continuously, including ordinary checkpoints, local QA and push, without asking for routine reconfirmation. Apply the preauthorized decision matrix in §14. `AUTO-RESOLVE` means act under the exact rule and continue. `DEFER AND CONTINUE` means record the blocked external gate and finish provably independent authorized work. `HARD STOP` means stop affected work immediately, preserve evidence, and do not improvise an alternate design. An unforeseen condition is a HARD STOP for dependent code; only safe independent evidence collection can continue. No authorization to merge, release, broaden the allowlist or start B5.

**Host assumption:** Treat the host as idle and ready to benchmark. **Do not run an idle check, a warm A/B run, a real benchmark, a profiler capture, CPU-symbol probing or a microbenchmark during B4.** PERF-05-C alone owns the consolidated warm A/B and profiling campaign. `cargo bench --workspace --no-run` compiles only and is permitted as normal CI-style QA.

**Earlier CI:** Do not wait for B1/B2/B3 CI or real RustFS completion. Do run all required local correctness, stable/MSRV, coverage and applicable local integration gates; state any remote gate as PENDING/BLOCKED rather than passed. No new CI workflow or separate PR.

## 1. Source-grounded proof: the specific redundant work

Verified at B3 HEAD; line numbers are approximate, use symbols as anchors after preflight.

| ID | Concrete source fact and B4 implication |
| --- | --- |
| S01 | `search/unified.rs::single_term_postings_eligible` requires `UnifiedNode::Lexical(0)`, one `CompiledLeaf::Term` containing exactly one analyzed term, no typed leaf, positive leaf `{0}`, no aggregation and no `after` cursor. Sort and batch are **not globally excluded**. Reuse exactly this already-computed eligibility flag; never introduce a new eligibility policy. |
| S02 | `search/unified.rs::collect_mixed` passes that flag to `execute::evaluate_lexical_with` and has B1's existing `is_match` callback. This branch returns true for already proven membership; its callback, aggregation guard, score/heap consumer, key checking and sort handling must remain unchanged. |
| S03 | `search/execute.rs::build_leaf_data` validates/decodes effective-live postings as sorted `TermPostings.postings: Vec<(u64,u64)>` (`doc_id`, original term frequency). All decoder, corruption, scanned-work and memory charges occur **before** the B4 target. Keep them. |
| S04 | `execute.rs::evaluate_lexical_with` (around 1947–2080) checks a strict runtime shape `[LeafData::Term{terms,..}] if terms.len()==1 && !typed_examination` **before** invoking the eligible callback. A mismatch returns `SearchError::CorruptIndex` with `single-term postings eligibility mismatch`. |
| S05 | Eligible code uses B2's verified segment live count and `effective_live_examination_count`, 4,096-slot cancellation checks, unchanged `meter.charge_lexical(live_count)`, one `meter.check_cancelled()` for each posting, and exactly one `is_match` callback per candidate. Keep all checks, order and charges. |
| S06 | B3's two enumerators visit ascending-unique physical IDs. The eligible path follows one sorted posting list; fallback scans the bitmap in ascending slot order. Matched Vec debug assertions enforce strictly increasing IDs. Preserve this property. |
| S07 | After callbacks, the evaluator reserves `M*SET_BYTES_PER_ENTRY` (48 per matched doc) **before** calling `score_segment`. The generic scorer reserves `M*SCORED_MAP_BYTES_PER_ENTRY` (64 per doc) before constructing its `BTreeMap`. After the map becomes an output Vec, the evaluator drops matched and leaf data and releases matched, leaf, scored reservations in that order. Preserve exact modeled admissions and release sequence. |
| S08 | `execute.rs::score_segment` (around 1669–1780) seeds each matched ID's score with `0.0`, identifies one positive `(field,term)` owner, then iterates the term's postings and, for admitted IDs, computes `let contribution = super::score::bm25(freq, df, n, dl, avgdl)?; *current += contribution`. For S01 there is exactly one contribution per accepted doc. |
| S09 | `search/score.rs::bm25` is the only authorized score calculator. `stats.field(field_id)` can be absent, in which case the generic scorer leaves the initialized score **+0.0**. `FieldStats::doc_freq(term)` returns zero if missing; `FieldStats::length(segment_index,doc_id)` is authoritative. The helper must compute the identical arguments and perform `score += contribution` from an initialized `0.0_f64`, retaining exact score bits and typed errors. |
| S10 | `execute_segment_inner` invokes the **same** generic `score_segment(matches.set.iter(),...)` for sibling lexical/Boolean work. B4 MUST NOT alter it, `eval_node`, `ReservedSet`, generic scorer signature/body or any other caller. A test-only call witness is the only permitted addition inside `score_segment`. |
| S11 | Unified caller consumes `Vec<(u64,f64)>` to calculate exact total hits, validate every key and sort value, apply duplicate checks and maintain Top-K. B4 must return the same complete ordered vector and preserve validation for losers. |
| S12 | Existing `execute.rs::budget_tests` includes B3 scorer comparisons, C2 exact/one-over modeled scored-map memory tests and B2 cancellation/charge tests. `unified.rs::phase4_tests` and `b_tests` include B1/B2/B3 results, scores, sorted ties, multi-segment and K tests. Reuse unmodified. |
| S13 | At B3 HEAD there are exactly **two** production `score_segment` call sites. B4 changes only `evaluate_lexical_with` to choose a new narrow helper; sibling caller and generic scorer remain. |
| S14 | `SegmentCandidateLedger::reserve_with_memory` and optional `SlotMemoryScope` fail closed, accounting for logical candidate bytes and cleaning up under RAII. B4 retains both 48 and 64 modeled per-match charges even though actual physical allocations differ. |
| S15 | The PERF-05-B register assigns all narrow scoring object-reuse work to B4, future decoded-postings lifetime experiments to conditional B5, and profiling/benchmarking only to C. |

### Scoring equivalence proof — must still hold after pull

1. The eligible path is exactly one positive term: term ownership in `score_segment` is unambiguous.
2. The current accepted `(doc_id,freq)` is copied **after** successful `is_match`, not before. Thus a future callback returning false does not create a score; the complete input postings remain decoded/validated.
3. The old map's `0.0` seed receives exactly **one** contribution for each accepted doc. A new `let mut score=0.0_f64; score += super::score::bm25(...) ?;` with the **same** `freq`, `df`, `n`, `dl` and `avgdl` has the same result bits and error behavior.
4. The accepted IDs are ascending-unique, so outputting scores in candidate order produces the same order as BTreeMap iteration without sorting or deduplication.
5. **Scoring occurs only after the unchanged 48-byte matched reservation and 64-byte scored reservation.** All matching callbacks and their work/cancellation/error opportunities finish first; do not calculate BM25 during the postings loop.
6. When no matching doc exists, reserve zero bytes just as the old path did and return an empty Vec. When the positive leaf or stats field is absent in synthetic unit tests, scores remain +0.0. A malformed `df>n` still propagates the exact typed `InvalidScore` from the existing BM25 function.

This proof is **specific to this eligible path**; the generic scorer must remain unchanged for every other query shape.

## 2. Current state and precise delta

| Component | B3 state | B4 action |
| --- | --- | --- |
| B1 membership relookup removal | Present, tested locally | Preserve; rerun regressions |
| B2 verified live counts/cancellation parity | Present, tested locally | Preserve; rerun regressions |
| B3 ordered matched-ID `Vec<u64>` and iterator scorer seam | Present | Keep for **ineligible** path; eligible path also carries original frequencies |
| Generic `score_segment` + scored `BTreeMap` | Needed for all other query shapes | Leave algorithm unchanged |
| Eligible one-term `score_segment` call | Reconstructs a full-M map and scans postings again | Replace by one private, direct-output scorer from stored `(doc_id,freq)` pairs |
| Public response, columns, heap, projection, cursor, batch | Present | Absolutely no change |
| B5 and final C | Not started | No implementation or performance work |

**One dominant architectural concern:** remove unnecessary intermediate score tree and repeated posting pass from exactly the strict eligible branch. This B4 is **not** a second generic scorer implementation, public response change, complete streaming executor or index-layout rewrite.

## 3. File allowlist, explicit non-goals and reuse

**Only four tracked files may change:**

1. `crates/quervant-core/src/search/execute.rs` — one private scorer, a narrow eligible candidate buffer/dispatch, tests and test-only counters.
2. `crates/quervant-core/src/search/unified.rs` — **tests only**, within existing `#[cfg(test)] mod phase4_tests`; production byte changes forbidden.
3. `docs/pr-artifacts/perf-05/PERF05B4_DETAILED_PLAN.md` — byte-identical copy of this approved plan.
4. `docs/pr-artifacts/perf-05/PERF05B4_EXECUTION_REPORT.md` — truthful implementation/evidence report.

No edits to `score.rs`, `work.rs`, `typed.rs`, `unified_plan.rs`, other executor/scorer components, segment codecs, manifests, `Cargo.toml`/`Cargo.lock`, CI, `AGENTS.md`, benchmark configs/results/scripts, `docs/BENCHMARKING.md`, roadmap, or earlier B-stage documents. No dependency, feature, public API, new persistent state, unsafe cast, SIMD, WAND, early Top-K stop, or runtime tuning.

**Existing APIs to reuse:** `super::score::bm25`; `FieldStats::{doc_freq,length,n,avgdl}`; `SnapshotStats::field`; `SegmentCandidateLedger::reserve_with_memory` / `release_with_memory`; `CandidateBudget`; `SlotMemoryScope`; current `score_segment`; B1/B2/B3 eligibility, predicate and cancellation code. Do not duplicate these abstractions.

**No reinterpretation trick:** Do NOT cast the frequency to `f64` before scoring, pack it in float bits, `transmute` a Vec, reuse output buffer via unsafe ownership, add a new output enum/trait, or change BM25 formula. The typed candidate Vec and separate final scored Vec are the safe frozen design.

## 4. Frozen production implementation — apply only these edits

### 4.1 One private, narrow single-term scorer

**File:** `crates/quervant-core/src/search/execute.rs`. Insert **immediately after** the closing brace of the existing generic `score_segment` and **before** the `#[cfg(test)] mod test_observation`. Do not change any existing scorer code, beyond one test-only counter addition in §5.

Copy the following implementation (ordinary rustfmt-only layout changes permitted):

```rust
#[allow(clippy::too_many_arguments)]
fn score_single_term_candidates(
    matches: &[(u64, u64)],
    field_id: u32,
    term: &str,
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(Vec<(u64, f64)>, Charges)> {
    #[cfg(test)]
    test_observation::record_single_term_scorer_call();

    // Preserve the old scored-map admission even without the physical map.
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };

    // Direct final output: no scored BTreeMap, no second postings walk.
    let mut scored: Vec<(u64, f64)> = Vec::with_capacity(matches.len());
    let field_stats = if positive.contains(&0) {
        stats.field(field_id)
    } else {
        None
    };
    let df = field_stats.map_or(0, |field| field.doc_freq(term));

    for &(doc_id, freq) in matches {
        let mut score = 0.0_f64;
        if let Some(field) = field_stats {
            let dl = field.length(segment_index, doc_id);
            let contribution = super::score::bm25(
                freq,
                df,
                field.n,
                dl,
                field.avgdl,
            )?;
            // Generic score_segment adds to an initially +0.0 map slot.
            score += contribution;
        }
        scored.push((doc_id, score));
    }
    Ok((scored, charges))
}
```

**Exact obligations:** The call to `reserve_with_memory` precedes `Vec::with_capacity`, BM25 and all score writes. Use the same `SCORED_MAP_BYTES_PER_ENTRY` value (64) and `Charges` object as generic scoring. `map_or(0, ...)` only chooses a term frequency statistic; it does not suppress scoring when the `df` is zero. The existing `bm25` function decides whether that is valid. For zero matched entries, preserve `reserve_with_memory(0,0,...)` and return an empty vector.

Do not add cancellation polls/work charges inside this helper: generic `score_segment` has none. The first `InvalidScore` must still arise **after** the match/score ledger reserves and from the existing `bm25` call. If a changed version of the current source does not satisfy that premise, HARD STOP.

**Allocator residual risk:** `Vec::with_capacity` may allocate, just as the generic map materialization did. Do not invent a new allocation-failure error path or assert physical OOM is tested. Deterministic *modeled* budget/ledger errors must remain identical; no change to the conservative logical accounting because physical memory use has changed.

### 4.2 Add an eligible-only frequency-bearing buffer

In `evaluate_lexical_with`, immediately after the **unchanged** B3 line:

```rust
let mut matched: Vec<u64> = Vec::new();
```

add precisely:

```rust
// Only the eligible one-term branch fills this ordered (doc_id, freq) buffer.
// The generic `matched` Vec stays empty for that branch.
let mut single_term_matched: Vec<(u64, u64)> = Vec::new();
```

No matched IDs are duplicated into both buffers; only one reaches M entries. Do not replace `matched` with a general enum, change the generic fallback, or preallocate `single_term_matched` to the whole live count.

### 4.3 Change only the eligible candidate push; preserve every guard and callback

Find the eligible branch of `evaluate_lexical_with` (strict guard already performed, verified-live count obtained, charge applied, cancellation polled). Replace **only**:

```rust
for (doc_id, _freq) in postings {
    meter.check_cancelled()?;
    #[cfg(test)]
    test_observation::record_predicate_call();
    if is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())? {
        debug_assert!(matched.last().is_none_or(|last| last < doc_id));
        matched.push(*doc_id);
    }
}
```

with:

```rust
for (doc_id, freq) in postings {
    meter.check_cancelled()?;
    #[cfg(test)]
    test_observation::record_predicate_call();
    if is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())? {
        debug_assert!(single_term_matched.last().is_none_or(|last| last.0 < *doc_id));
        single_term_matched.push((*doc_id, *freq));
    }
}
```

**No BM25 calculation here.** Do not change `is_match`, `build_leaf_data`, `effective_live_examination_count`, `charge_lexical`, the shape guard, B1's test call count, or the ineligible branch's `matched.push(doc_id)`. The `freq` is copied directly from the already-decoded postings, not cast or reacquired.

### 4.4 Replace only the scoring selection and ownership tail

Immediately after both enumeration arms, the B3 source currently calculates `matched.len()`, reserves 48 bytes per match, calls the generic scorer, converts its map to a vector, drops `matched` and `leaf_data`, and releases three logical reservations.

Replace only that tail with the following, retaining the **same release order**, error propagation and final return type:

```rust
let matched_entries = if postings_candidate_eligible {
    single_term_matched.len() as u64
} else {
    matched.len() as u64
};
let matched_bytes = bytes_for_count(matched_entries, SET_BYTES_PER_ENTRY)?;
ledger.reserve_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;

let (scored_vec, scored_charges): (Vec<(u64, f64)>, Charges) =
    if postings_candidate_eligible {
        // Reconfirm only the already runtime-validated one-term shape.
        let (field_id, term) = match leaf_data.as_slice() {
            [LeafData::Term { field_id, terms }]
                if terms.len() == 1 && !typed_examination =>
            {
                (*field_id, terms[0].term.as_str())
            }
            _ => {
                return Err(SearchError::CorruptIndex {
                    detail: "single-term postings eligibility mismatch".to_owned(),
                });
            }
        };
        score_single_term_candidates(
            &single_term_matched,
            field_id,
            term,
            stats,
            segment_index,
            positive,
            &mut ledger,
            memory.as_deref_mut(),
        )?
    } else {
        // The existing scorer is unchanged for all other query shapes.
        let (scored, charges) = score_segment(
            matched.iter(),
            &leaf_data,
            stats,
            segment_index,
            positive,
            &mut ledger,
            memory.as_deref_mut(),
        )?;
        (scored.into_iter().collect(), charges)
    };

// Drop both buffers and decoded leaves before their logical reservations.
drop(matched);
drop(single_term_matched);
drop(leaf_data);
ledger.release_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
ledger.release_with_memory(
    leaf_charges.entries,
    leaf_charges.bytes,
    memory.as_deref_mut(),
)?;
ledger.release_with_memory(
    scored_charges.entries,
    scored_charges.bytes,
    memory.as_deref_mut(),
)?;
Ok(scored_vec)
```

**Compiler and lifetime guard:** `term` borrows from `leaf_data`, which stays alive throughout the helper call. All decoded term frequencies and document IDs were copied into `single_term_matched`. The helper returns an owned scored vector. If a compiler error requires changing the API, adding a clone of all postings, changing scorer input ownership, or moving releases, **HARD STOP**. Only trivial rustfmt or clearly prescribed local imports are AUTO-RESOLVE.

**Asymptotic effect of this exact design:** eligible path still pays O(M) to decode/validate postings and O(M) to collect candidates, but no longer creates a full-M scored tree or performs O(M log M) map insert/find operations or re-reads the postings for scores. It uses two compact M-scale vectors (one temporary `(id,freq)`, one returned `(id,score)`), not three candidate trees. **This is a source-level work reduction, not a claimed measured speedup.**

## 5. Exact test-only scorer-dispatch witness

Use the **existing** `#[cfg(test)] pub(crate) mod test_observation` in `execute.rs` (where B1's lookup witness already lives). Add these two thread-local `Cell<usize>` values alongside the existing counters:

```rust
static GENERIC_SCORER_CALLS: Cell<usize> = const { Cell::new(0) };
static SINGLE_TERM_SCORER_CALLS: Cell<usize> = const { Cell::new(0) };
```

Add **exactly** these functions in that same test module:

```rust
pub(crate) fn reset_scorer_calls() {
    GENERIC_SCORER_CALLS.with(|v| v.set(0));
    SINGLE_TERM_SCORER_CALLS.with(|v| v.set(0));
}
pub(crate) fn generic_scorer_calls() -> usize {
    GENERIC_SCORER_CALLS.with(Cell::get)
}
pub(crate) fn single_term_scorer_calls() -> usize {
    SINGLE_TERM_SCORER_CALLS.with(Cell::get)
}
pub(crate) fn record_generic_scorer_call() {
    GENERIC_SCORER_CALLS.with(|v| v.set(v.get() + 1));
}
pub(crate) fn record_single_term_scorer_call() {
    SINGLE_TERM_SCORER_CALLS.with(|v| v.set(v.get() + 1));
}
```

Add **only** these lines at the very beginning of generic `score_segment`'s body, before its logical reservation:

```rust
#[cfg(test)]
test_observation::record_generic_scorer_call();
```

The specialized helper already records `record_single_term_scorer_call()` before its reserve in §4.1. These calls do not exist in production, optimized builds or benchmarks. Do not add a feature, production metrics or hot-path diagnostics. Each full-query test resets both counters immediately before running the query it observes.

## 6. Falsifiable correctness invariants and evidence mapping

| ID | Required behavior | Implementation | Independent acceptance evidence |
| --- | --- | --- | --- |
| I01 | Exact `total_hits` for absent, singleton and many matches; never stop at Top-K | §4.3–4.4 | B4-U03; existing phase4 U09 |
| I02 | The strict eligible path never invokes generic scored-map construction; the fallback does | §§4–5 | B4-U03/U04 scorer counters, source inspection |
| I03 | Original term frequency stays `u64` until the **existing** BM25 converts it; no second postings traversal | §4.1/4.3 | B4-U01/U07, source diff |
| I04 | BM25 numeric bits equal the generic scorer, including zero scores and empty matches | §4.1 | B4-U01/U02/U06, B3 scorer regressions |
| I05 | B1 shortcut / `LeafData::matches` fallback unchanged | §4.3/4.4 | B1 U01–U04, B4-U04 |
| I06 | B2 verified live count, work units and cancellation polling unchanged | §4.3 | B2 U01–U06, phase4 U10–U16 |
| I07 | B3 ascending-unique IDs, deterministic ordering and multi-segment results unchanged | §4.3/4.4 | B4-U03, B3 U01–U03, `b_u12_two_segment_score_bits` |
| I08 | Modeled matched `M*48` then scored `M*64` reservation, matched/leaf/scored release, exact/one-below errors unchanged | §4.1/4.4 | B4-U05, C2 budget regression |
| I09 | Invalid score errors remain typed and occur after all callbacks / logical admissions; no skipped validation | §4.1/4.4 | B4-U06, error/corruption regressions |
| I10 | Callback invoked for every posting in eligibility branch **before** scoring; rejected callback yields no match | §4.3/4.4 | B4-U02/U03 plus B1 predicate-call witness |
| I11 | Generic scoring, sibling `execute_search`, `eval_node` and Boolean/phrase handling intact | §3 | B4-U04, B3 U01/U02, `pr13_oracle` |
| I12 | Exact score, projected fields, sort, tie, cursor/PIT and duplicate checks preserved for all candidates including losers | §4.4 | B4-U03/U04, `b_tests`, `pr13_oracle` |
| I13 | Only query-local temporary buffers; no format, remote, manifest, index or cache changes | §3 | changed-path audit + local `FsDirectory` / hosted RustFS |
| I14 | No benchmark/profiling acquisition, no B5/C work, same PR | §0/§3 | execution report + file allowlist |
| I15 | No weakening of exact `ResourceLimit`, `InvalidScore`, `Cancelled` and `CorruptIndex` behavior | §4 | B4-U05/U06 and existing negative suites |
| I16 | Stable and MSRV compilers work; project coverage >=85% | all | stable + 1.85 test/Clippy/fmt, llvm-cov report |

**State and boundary analysis:** Empty posting list and all-dead snapshot still execute existing setup, count verification, zero reservation and final zero-hit response. A one-posting list produces one candidate; many postings produce exactly M candidate scores regardless of Top-K size. The loop's callback may reject a posting, and the specialized candidate buffer must exclude it (but all postings were still decoded). A negative/phrase/typed/multi-analyzed request remains on its old generic scan and scorer. Segment ordinal is unchanged; each segment is handled independently. Overflow or too-small candidate/batch budgets reject at existing admission sites; errors unwind the same RAII ledger. An already-cancelled request fails at existing checks before scoring. Corrupted decoded postings and malformed losing candidates remain checked on every candidate, not just K winners.

**Error/side-effect priority:** `expand_query` and `compute_stats` -> `build_leaf_data` validation -> effective-live verified count/charge -> per-posting `check_cancelled` and `is_match` callbacks -> matched reservation (48M) -> scored reservation (64M) -> BM25 contributions -> `drop(matched)`, `drop(single_term_matched)`, `drop(leaf_data)` -> release matched, leaf, scored reservations -> caller key/sort validation and Top-K. A B4 plan must **not** move BM25 before the reservations or callback, change observed cancellation checks or skip a losing candidate's validation. The scorer helper itself is purely CPU arithmetic with no added work/cancel polls, matching the original generic scorer's behavior.

**Ownership boundaries:** `leaf_data` owns decoded postings; the eligible candidate Vec owns copied `(u64,u64)` tuples; the specialized helper borrows candidate tuples and query-local `SnapshotStats`; its returned `Vec<(u64,f64)>` is owned by the caller. The original ledger and optional batch slot scope remain the only resource-accounting owners. No cross-query cache, reference cycles, persistent state, transaction, remote I/O, service startup or retry is introduced.

## 7. Mandatory test-first and adversarial matrix

New tests belong **only** to existing `execute.rs::budget_tests` and `unified.rs::phase4_tests`; reuse current imports, B3 fixture setup and real segment decoding. Name tests as specified below. Do not introduce benchmark scripts, dependencies or synthetic implementations of the production scorer. The old generic scorer is the differential oracle, supplemented by independent hand-enumerated document fixtures.

| ID / exact Rust test name | Setup / action | Non-negotiable expected result |
| --- | --- | --- |
| B4-U01 `b4_u01_single_term_scores_match_generic_bm25_bits` | Real `golden_norms.seg`, `title`/`hello`, decode real `(doc_id,freq)` postings, real stats and `positive={0}`. Call generic scorer and B4 helper under separate identical ledgers. | Ordered `(doc_id, score.to_bits())` equal, both charges `M * 64`, positive finite scores, no ledger leak. This is the **red-first** test. |
| B4-U02 `b4_u02_empty_and_selected_subset_score_parity` | Same real norms/decoder; test empty, first-doc-only, all-docs subsets. Generic input is exactly subset IDs, but its `LeafData::Term` still contains all postings. | Byte-exact scores, ascending IDs and charges equal for every subset. Zero-match case must return empty and still call zero-charge reserve. |
| B4-U03 `phase4_b4_u03_strict_single_term_scoring_and_fallback_parity` | Real phase4 index fixtures `(40,[])`, `(40,[7])`, `(40,[0,3,9,39])`, `(1000,[0,1,7,511,999])`, `(1000,all)`; relevance and explicit sort; K1/10/100. Direct term vs `Query::And(vec![term("alpha")])`. | Direct fast scorer calls=1, generic=0; wrapped generic=1, fast=0. Exact hand-known total, full key sequence, `score.to_bits()`, projection and K length equal. B1 lookup and callback counts preserved. |
| B4-U04 `phase4_b4_u04_ineligible_shapes_use_only_generic_scorer` | Wrapped `And`, Or, Not, expanded multi-term, phrase, mixed lexical+typed, plus valid `after` cursor. Use existing valid phase4 queries and expected fixtures. | Strict fast score helper count **zero** for all ineligible shapes; at least one eligible fallback does call generic scorer. No changed results; no invented count requirement for a path that delegates elsewhere. |
| B4-U05 `b4_u05_scored_reservation_exact_and_one_below` | Two accepted docs, same `48M+64M` modeled budget for old generic vs helper. Check exact bytes, one below; repeat with existing batch `BatchMemoryMeter`/`SlotMemoryScope` contract. | Exact limit passes, one-under returns same typed `ResourceLimit` with same requested/limit fields, same reservations and RAII cleanup. Do not alter constants. |
| B4-U06 `b4_u06_invalid_df_and_zero_score_parity` | Real norms stats + test-only `stats.fields.get_mut(&field_id).unwrap().df.insert("hello".to_owned(), n + 1)`; compare both scorers. Also test missing field stats and `positive={}`. | Both return `SearchError::InvalidScore` at the same phase, or both return **+0.0** bitwise scores when scoring field/owner absent; no retained result on error. |
| B4-U07 `b4_u07_exact_u64_frequency_transport` | Construct test-only `(doc_id, freq)` with `freq=9_007_199_254_740_993_u64` (greater than 2^53), use real stats and matching manually built one-term `LeafData` with that frequency for generic reference. | Both scores bit-identical after `bm25`'s existing conversion, proving the candidate buffer never prematurely casts `freq` to f64. This is a synthetic unit check, **not** an on-disk posting fixture. |

### Test assembly requirements (no architecture delegated)

**B4-U01 and U02:** Follow existing `b3_u02_positive_bm25_tree_and_vec_score_bits_match` in `execute.rs::budget_tests` for the literal real norms fixture, field/term discovery, `QueryTerms`, all-live bitmap, `SegmentReader::postings(...).next_with(&NeverCancel)` and stats. Reuse those exact APIs. For the **reference scorer**, construct `LeafData::Term { field_id, terms: vec![TermPostings { term:"hello".to_owned(), postings: all_postings.clone() }] }`. Pass `accepted.iter().map(|(doc_id,_)| doc_id)` to the unchanged `score_segment`, which accepts `impl ExactSizeIterator<Item=&u64>`; collect its BTreeMap to ascending `(doc_id,score.to_bits())` pairs. For B4 pass the accepted `(doc_id,freq)` slice directly to `score_single_term_candidates`. Use fresh `CandidateBudget` and `SegmentCandidateLedger` for each path, not one shared budget with prior state. Before calling either scorer, reserve `M*SET_BYTES_PER_ENTRY`; after obtaining `Charges` release matched and scored reservations, call `ledger.finish()` and assert clean. Do not reuse `b3_score_from_iterator` unchanged if its helper preconditions (it reserves only scored entries) would make the budget comparison invalid; write one **test-only** thin adapter with exactly this prescribed reserve/release protocol.

**B4-U01 expected RED:** Add only this test and its necessary test scaffolding, with a call to the as-yet-nonexistent `score_single_term_candidates`. Before implementing §4, run exactly:

```bash
cargo test -p quervant-core --lib b4_u01_single_term_scores_match_generic_bm25_bits -- --nocapture
```

Expected compile error **solely** unresolved function `score_single_term_candidates` (Rust E0425 or equivalent). Log first error. A missing fixture, invalid import, borrow issue, unexpected scorer behavior or other diagnostic is **not** an authorized RED: HARD STOP, no production patch. After the expected RED, implement §4 then rerun the same test to GREEN; complete U02–U07 thereafter.

**B4-U03:** Before every query reset the two scorer witness counters. Require `single_term_scorer_calls()==1` and `generic_scorer_calls()==0` for direct one-segment fixtures, and the reverse for the wrapped `And` query. Compare scores using `hit.score.expect("lexical score").to_bits()`. Do not compare exact cursor token bytes between distinct ASTs; cursor fingerprints differ by design. Assert direct candidate predicate calls still equal exact matching count and B1 term lookup count remains zero. The wrapped fallback examines every live doc; its lookup counter remains nonzero. Verify `total_hits` for K1 despite more matches. All expected match IDs come from hand-authored fixture indices, not an optimized query run.

**B4-U04:** Use existing `phase4_u01_u05_eligibility_matrix` to choose legal shapes. The hard assertion is `single_term_scorer_calls()==0` when `postings_candidate_eligible` is false; do not invent that every typed-only/leaf-free path reaches this same unified scoring helper. Ensure an explicit wrapped lexical fallback calls generic at least once. Keep aggregation, batch and cursor policy unchanged; run existing batch/oracle suites rather than adding new compiler options.

**B4-U05:** Use `budget_tests::limits()` and existing `CandidateBudget`, `SegmentCandidateLedger`, `BatchMemoryMeter` and `SlotMemoryScope` patterns from `c2_scored_map_exact_and_one_over`. For a direct scorer-only unit test, modeled peak is **exactly** `M*48 + M*64`, excluding postings because no `build_leaf_data` is called. Use identical separate ledgers for old/new, and identical separate batch scopes. Under one-below, the 64-byte scored reservation must fail **before** any contribution calculation and both paths return the same typed `ResourceLimit` values. The whole-query tests cover all other upstream charges. Test failed ledger/scope cleanup after RAII drop rather than manually resetting counters.

**B4-U06:** Use a **separate** fresh real stats object for invalid statistics and mutate **only in the test**: record `n=stats.field(field_id).unwrap().n`, then insert df `n+1` for `"hello"` into its `df` map (which is `pub(crate)`). Supply a positive-frequency posting. Verify both helpers fail with the same `InvalidScore` detail; no `bm25` formula copy. For absent stats use `compute_stats(..., scoring_field_ids=&[], query_terms=&empty, ...)` from B3-U01; both generic and specialized scores remain positive zero when `stats.field(field_id)` returns `None`. With `positive=BTreeSet::new()`, both also remain zero. Preserve old error/budget precedence.

**B4-U07:** A decoded frequency above `2^53` is not necessary for a corpus fixture and may be rejected by the codec; do **not** alter codec limits. Unit-construct a `LeafData::Term` with the same large frequency and matching doc ID (use a valid normed doc ID 0/1). Use the real positive field stats for `df`, `n`, `avgdl` and `dl`, and compare generic/B4 contribution bits. This proves the in-memory buffer carries exact u64 frequency until the authorized calculator applies its own conversion.

**Do not invent test oracles, skip failures, reduce error assertions, or insert per-candidate timers.** Use fixed small deterministic fixtures, exact-size iterators and existing crates only. In-file `#[cfg(test)]` implementation can use explicit helper functions for repeated ledger setup, but those helpers must follow the above exact protocol and must not implement a second BM25 equation.

### Mandatory existing regressions and real-boundary tests

- `phase4_tests` (B1 + B3, cancellation, cursor, eligible-only visitation and work parity), `b_tests` (sort/missing/null UTF-8 and multi-segment BM25 bits), B2-U01…U06, B3-U01…U03, `score::tests`, and `budget_tests`.
- `pr13_oracle` (independent query expectations), `pr15e_b1` (batch parity), `pr06_local_integration` (real `FsDirectory` and process/reopen lifecycle). These tests use the actual analyzer -> writer -> immutable segment -> reader -> search path.
- RustFS real-service acceptance if the already-configured pinned service is accessible; otherwise report honest local BLOCKED and CI pending. Fakes are not a substitute for RustFS.

## 8. Pre-implementation correctness gate

Before modifying production code, record the following in the execution report:

1. S01–S15 anchors observed on actual pulled branch source and the S01/S04 eligibility equivalence proof.
2. Both existing generic scorer call sites and the actual B3 matched-Vec locations. Confirm the strict branch has access to the **original exact frequency** without another postings read.
3. I01–I16 mapped to tests and failure conditions, including empty, one, multiple, K smaller than M, cursor, null sort, full-dead, multi-segment, mixed, `df>n`, logical exact-limit and cancellation.
4. The main concern: **never compute BM25 before callbacks and logical admissions**; verify the code as planned leaves this order unchanged. Score errors must not precede a matching callback failure or a tight resource budget.
5. No contradiction between this new scorer and generic one-term ownership logic. If the generic scorer now has additional one-term contributions, a new work/cancellation side effect, or extra ownership rules, stop for amended human design.

If any item fails, invoke §14 HARD STOP; do not implement a guessed replacement. An agent may report which invariant is at risk but may not approve a changed contract.

## 9. Ordered autonomous execution, commands and real topology

### P0 — Inspect latest branch BEFORE edits (and do not wait for CI)

From the repo root, execute these commands in order. Preserve stdout/stderr, SHAs, status and relevant source excerpts. Do **not** use `git clean`, `git reset`, `git stash`, `git rebase`, a force push, or auto-merge:

```bash
set -euo pipefail
git branch --show-current
git status --porcelain=v1 --untracked-files=all
# Unexpected tracked change/conflict or previously unknown untracked source => HARD STOP.
git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor af69e3859f21fac9dcb0e254dab6a46e1b2cf5c8 HEAD
# B1/B2/B3 must be ancestors; verify source, not only commit messages.
rg -n 'fn score_segment|fn evaluate_lexical_with|score_segment\(' \
  crates/quervant-core/src/search/execute.rs
rg -n 'fn single_term_postings_eligible|postings_candidate_eligible' \
  crates/quervant-core/src/search/unified.rs
rg -n 'SET_BYTES_PER_ENTRY|SCORED_MAP_BYTES_PER_ENTRY|fn build_leaf_data|struct SegmentCandidateLedger' \
  crates/quervant-core/src/search/execute.rs
rg -n 'fn bm25|pub\(crate\) struct SnapshotStats|fn verified_segment_live_count' \
  crates/quervant-core/src/search/score.rs
rustc --version
cargo --version
rustup toolchain list
START_SHA=$(git rev-parse HEAD)
printf 'PERF05B4_START_SHA=%s\n' "$START_SHA"
```

**Preflight decision:** Exact inspected B3 HEAD is the expected source. A *new descendant* is allowed only if every S01–S15 proof remains literally valid, the B1/B2/B3 source and target functions have not changed, and any intervening changes are explained and reviewed. **Do not automatically rebase to a newer `main`.** A stale/different executor, changed scorer, changed ledger rules, remote branch divergence, or an unexplained new source change is a HARD STOP, not permission to adapt the architecture.

**Generated files:** Preserve the previously disclosed `.coverage`, `benchmark-results/` and `benchmarks/quervant_bench.egg-info/` if they already exist and are excluded locally. Do not modify `.git/info/exclude`, delete them, or stage any generated directory. Other untracked paths or tracked changes require STOP, not a fresh exclude workaround. No host-idleness probe is needed.

### P1 — correctness challenge and RED-first test

- Inspect all source anchors, fill the I01–I16 evidence matrix and record a one-paragraph proof that one positive term contributes exactly one `bm25` add to each accepted doc in the existing scorer.
- Write B4-U01's test and its **test-only** adapters, intentionally calling the not-yet-existent `score_single_term_candidates` under the same reservation protocol as the generic scorer.
- Execute the exact RED-first command from §7. Capture only the expected unresolved-helper symbol error. Any other error is HARD STOP: do not change the fixture or expected values to force an apparent RED.

### P2 — exact implementation

- Apply §4.1 helper, §4.2 dual exclusive buffers, §4.3 eligible frequency push and §4.4 scoring selection/lifetime/release tail, in that order.
- Add §5 test-only dispatch counters; no release instrumentation.
- Run the RED test again to GREEN, then complete B4-U02…U07 and the specified integration-focused checks.
- Do **not** add a fast path to the generic scorer, a new mode or a dynamic flag, or change `execute_segment_inner`.

### P3 — focused tests against the actual production search path

```bash
cargo test -p quervant-core --lib b4_ -- --nocapture
cargo test -p quervant-core --lib phase4_tests -- --nocapture
cargo test -p quervant-core --lib b_tests -- --nocapture
cargo test -p quervant-core --lib budget_tests -- --nocapture
cargo test -p quervant-core --lib b2_ -- --nocapture
cargo test -p quervant-core --lib b3_ -- --nocapture
cargo test -p quervant-core --lib score::tests -- --nocapture
cargo test -p quervant-core --test pr13_oracle
cargo test -p quervant-core --test pr15e_b1
cargo test -p quervant-core --test pr06_local_integration
```

**Mandatory:** the newly added `phase4` test calls real `Index` create/commit/reopen, decoded postings, normal scorer/candidate budget, result projection, sort and heap; it is not a fake replacement for the core execution. `pr06_local_integration` includes the actual `FsDirectory` boundary, while `pr13_oracle` independently checks query semantics. Record test counts, skipped/ignored tests, topology and exact command results. A missing external service cannot turn a fake test into RustFS acceptance.

### P4 — mandatory final local QA, full coverage and MSRV

After **all final Rust and test edits**, execute the actual repository-prescribed gates (the inspected `.github/workflows/ci.yml` uses stable 1.98.1 and Rust 1.85.0 MSRV):

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
cargo bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
git diff --check
```

These are real execution gates; tool installation alone or a green prior CI is not evidence. Record actual toolchains, test counts and `cargo llvm-cov` **whole applicable production-workspace line coverage >=85%** (no exclusions or floor changes). After any further Rust/test change, rerun all affected mandatory checks including workspace coverage. Mechanical rustfmt changes in allowlisted code are permitted if diff-verified and tested; compiler errors requiring another design are HARD STOP.

**No timed benchmark or profiling command:** `cargo bench --workspace --no-run` compiles benchmarks without executing them. Do not run `quervant-bench run`, bare `cargo bench`, `perf record`, `perf script`, sample collection, perf symbols/stack preflight, timed A/A or A/B, or a custom microbenchmark. Host is assumed idle and ready for the later PERF-05-C campaign. `bash benchmarks/scripts/test-scripts.sh` is a non-timed script self-test.

**Real RustFS:** If the **already available** pinned RustFS service and the necessary `QUERVANT_RUSTFS_*` settings are present, run at minimum these existing real-service integration tests (other required pinned CI suites are unchanged):

```bash
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1
```

If RustFS is absent, mark `RUSTFS_LOCAL_BLOCKED` and `HOSTED_CI_PENDING`, finish independent local tests and source review, and push a truthful pending-gate report. Do not provision privileged services, change CI, launch another full run, wait for previous B-stage CI, or claim that ignored tests passed. RustFS isn't simulated by an in-memory fake.

### P5 — final scope/diff checks, verbatim plan, report and push

1. Confirm exactly **four** tracked files changed from `START_SHA`: `execute.rs`, test-only `unified.rs`, `PERF05B4_DETAILED_PLAN.md`, and `PERF05B4_EXECUTION_REPORT.md`. Verify no production code in unified.rs changed, and `score_segment` was changed only by the optional `#[cfg(test)]` counter.
2. Copy the supplied Markdown **verbatim** (byte-identical) to the plan path above; verify with `cmp` against the original supplied file. Do not reconstruct or reformat it. This plan is intentionally written **without Markdown hard-break trailing spaces**, so verbatim copying and `git diff --cached --check` must both PASS. No waiver based on the old B2 conflict.
3. Prepare the execution report using §12, with actual commands/counts/coverage, test/feature evidence, encountered exceptions and open CI/RustFS gates. Distinguish baseline evidence from tests of B4 and regression tests for B1–B3. A report is not proof a test actually executed.
4. Run `git diff --name-only "$START_SHA"`, `git diff --check`, and review all changed hunks. Stage **only** the four allowlisted paths. Run `git diff --cached --name-only` and `git diff --cached --check` (both must succeed). No `git add .`.
5. Commit once with a bounded message such as `perf(perf05b4): remove strict-term scored map`; push `git push origin HEAD:dev/perf05-physical-execution-series` **without force**; verify local HEAD equals the remote branch. Confirm PR #117 remains OPEN/unmerged; do not change its draft state or create a separate PR.
6. Return terminal report: final commit and remote-verified SHA, exhaustive gates and disposition. Do not auto-start B5. If remote advanced and the push is non-fast-forward, preserve the local commit, HARD STOP and ask for human reconciliation. A documentation-only report edit after final code QA needs whitespace/link rechecks; any code edit requires affected full QA rerun.

**Commit SHA self-reference:** A report stored in the commit cannot embed the hash of that very commit without changing it. In the committed Markdown report, state `FINAL_SHA: containing pushed commit; exact value given in terminal report and git log`. Report the exact immutable final/remote SHA outside the commit after push. Never amend to insert its own SHA.

## 10. Failure modes, cross-component impact and oracle discipline

| Component / failure | Production change? | Required disposition and evidence |
| --- | --- | --- |
| Strict one-positive-term path | YES, in `execute.rs` only | New specialized helper, counted exact candidate set, no all-M score map, bitwise BM25 equivalence |
| Sibling `execute_segment_inner`, `eval_node`, `score_segment` | NO | Must remain unchanged apart from test-only call counter; existing B3 and lexical oracle regressions |
| `UnifiedSearcher` callback, batch, sort, result and cursor | NO | `unified.rs` only tests; real phase4/batch/oracle suites verify it |
| `build_leaf_data`, postings decoder, validation and cancellation | NO | Still decode all postings, preserve `freq`, validate even losing docs; no Top-K early stop |
| Query-work and byte/memory ledger | NO contract change | Same 48/64 units and ordering, exact/one-below and RAII tests; no post-hoc cap adjustments |
| Snapshot/segment/reader/store/manifest/local Fs/RustFS | NO | Query is read-only; existing real-boundary regression suites and accurate RustFS status |
| Invalid score `df > n` / absent scoring field | Arithmetic uses existing `bm25` | Same typed `InvalidScore` or positive-zero score bits; B4-U06 |
| Match callback cancellation / malformed data | No new checks or suppression | Old error and polling order before scoring; existing negative suites |
| Allocator OOM | No new public allocator-error policy | Distinguish physical allocator risk from deterministic modeled budgets; do not fabricate OOM acceptance |
| Missing CI/real RustFS | External-only blocker | Record as PENDING/BLOCKED, continue independent B4 QA; no unverified PASS |

Failure categories required by the authoring guide: **introduced regression**, **feature implementation defect**, **deterministic pre-existing failure**, **nondeterministic/flaky failure**, **environment/harness failure**. One successful retry does not establish flakiness; a claimed pre-existing failure needs a safe baseline reproduction or equivalent immutable evidence. "Unrelated" is not an acceptance classification. Report the first error and minimal reproducible fixture; never hide it by repeated random reruns or weakened expectations.

**Out-of-scope risks:** New index format/codec/remote protocol, storage caching, vector/distributed search, novel score policy, Top-K algorithm, term-prefix dispatch, WAND/pruning, profiling framework and performance acceptance. These require separate authority. A successful B4 source cleanup is not a measured warm performance win and does not complete `v0.1-perf`.

## 11. Independent reviewer and acceptance checklist

- [ ] Preflight source matches S01–S15, B3 ancestor verified and current branch identity checked; no unreviewed intervening production change.
- [ ] Exactly one private `score_single_term_candidates` helper with the specified signature and no duplicate BM25 equation.
- [ ] Eligible candidate buffer stores exact `(u64 doc_id,u64 term_freq)` values, only after successful callback, in strictly increasing order.
- [ ] Eligible scoring has **no** scored `BTreeMap`, no `get_mut` score lookup, no term-postings second traversal and no map-to-vector conversion.
- [ ] The generic `score_segment` remains byte-identical in release behavior; sibling `execute_segment_inner` and complex/typed/phrase/Boolean paths unchanged.
- [ ] Matched and scored logical admission remains 48M then 64M, and matched/leaf/scored release order is unchanged. Counts, limits and error types match the reference.
- [ ] BM25 called **after** callbacks and both modeled reservations, using original `freq`/field stats, with `score += contribution`; exact `to_bits()` comparison PASS.
- [ ] Synthetic no-owner/no-stats scores equal positive zero, malformed df propagates typed `InvalidScore`, filtered subset excludes rejects.
- [ ] Error/cancellation/validation for zero, sparse, deleted, multiple-segment and nonwinning results remain intact; cursor and tie sorting regression tests pass.
- [ ] Test-only counters prove eligible helper (and not generic scorer) in one-term shape and generic scorer on ineligible shapes; compiled out in release.
- [ ] Expected RED was solely missing helper; GREEN and all B4-U01…U07 and B1/B2/B3/fallback regression suites passed against the final code.
- [ ] Full stable/MSRV formatting, default/all-feature Clippy and tests, `cargo doc`, compile-only bench, script tests, and **>=85% actual whole-workspace Rust line coverage** passed locally, with measured value recorded.
- [ ] Real `FsDirectory` integration and oracle executed; pinned RustFS executed with evidence or reported precisely BLOCKED/PENDING, never inferred.
- [ ] Four-path allowlist respected, production `unified.rs` untouched; no Cargo/CI/benchmark/codec/memory-contract changes; no cross-stage work.
- [ ] The plan copy is byte-identical to approved input and both staged/worktree whitespace checks PASS, with no exception invented.
- [ ] No real benchmark/profiling/host-idle probe; result makes **no** unmeasured latency claim; no new PR, force push, PR merge or B5 start.

**Implementation PASS:** The precise two-buffer/specialized-scorer design is built with no unrelated changes. **Correctness PASS:** The invariant-to-test map is fully exercised (positive and negative cases), the local stable/MSRV and coverage gates actually passed against the final source and all residual risks are explicitly labeled. **Hosted acceptance:** RustFS/CI is PASS only after real jobs execute; external pending does not retroactively invalidate B4 local QA but must not be called accepted. **Performance:** NOT APPLICABLE to B4; PERF-05-C is the one final campaign.

## 12. B4 execution report and existing PR handoff

Create `docs/pr-artifacts/perf-05/PERF05B4_EXECUTION_REPORT.md` using **all** these sections and concrete, observed results (do not present placeholders as facts):

```text
PERF-05-B4 EXECUTION REPORT
REPO / BRANCH / PR
START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA
S01–S15 SOURCE PROOFS / I01–I16 INVARIANT-TEST TRACE
IMPLEMENTED_FILES (the four-path allowlist)
PRODUCTION DIFFERENCE: helper, exact candidates, selected scorer branch
RED_FIRST: exact command, sole unresolved-helper diagnostic
GREEN: test names/counts and comparisons
SCORER DISPATCH: generic vs strict eligible counter values
BM25: real decoded corpus score bits, filtered subset, invalid df, u64 frequency
LOGICAL ACCOUNTING: exact/one-below 48+64, errors and cleanup
TESTS: command | toolchain / topology | PASS/FAIL/BLOCKED/NOT_APPLICABLE | actual output
WORKSPACE_COVERAGE: command/tool version, measured lines %, exclusions
REAL LOCAL FS / RUSTFS / CI: performed checks, actual statuses
EXCEPTION MATRIX ROWS: IDs, observed triggers, actions and verification
OPEN GATES / RESIDUAL RISKS / FAILURE CLASSIFICATIONS
NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE
B4_DISPOSITION and reasons
NEXT=independent B4 review; B5 separately gated
```

**Commit SHA self-reference:** A file in the final commit cannot embed that very commit's hash without changing it. State that `FINAL_SHA` is the containing commit and give the **exact final/remote SHA in the user-visible terminal report** verified using `git rev-parse HEAD` and the remote ref after push. Do not amend/rewrite a pushed commit solely to insert a self-reference.

Suggested summary to add to the *existing* PR #117 (not a new PR):

> PERF-05-B4 computes strict single-positive-term scores from exact `(doc_id, frequency)` candidate pairs after existing matching and logical budget gates. It eliminates the eligible scored `BTreeMap` and duplicate term-postings pass while leaving the generic scorer and B1–B3 unchanged. See `PERF05B4_EXECUTION_REPORT.md` for exact correctness, score-bit, work/memory and stable/MSRV/coverage evidence. No performance benchmark/profile run; RustFS/CI pending when applicable. B5 is a separate decision.

## 13. Continuous execution, blocked tasks and independent work

Execute the full plan without routine reconfirmations after it is explicitly authorized. Record relevant matrix rows as soon as their trigger is observed; the plan's architecture and repository invariants outrank convenience. For a blocked external tool/service or hosted CI result, finish all independent source changes, test artifacts, local QA and documentation within the prescribed allowlist; report pending honestly. For a correctness ambiguity, a mismatch in scored bits, memory accounting, callback ordering, changed source, or a failure to meet hard gates, stop affected work immediately. Continue independent evidence gathering only when safe and incapable of disguising the blocker. A status report is not an approval request; do not wait at routine intermediate milestones.

## 14. Preauthorized architectural decisions and exception-handling matrix

**Priority:** repository correctness/resource contract > HARD STOP > DEFER AND CONTINUE > AUTO-RESOLVE. An exact rule applies only if every stated observable precondition is verified. When two rules conflict, use the more restrictive. A condition not expressly covered by D01–D28 is a HARD STOP for dependent work, not an opportunity to invent a third scorer, change file scope or modify a test. Escalation owner is the PR #117 maintainer/reviewer; the agent may not authorize itself.

| ID | Observable trigger / source check | Category | Approved action | Prohibited action | Evidence / gate / owner |
| --- | --- | --- | --- | --- | --- |
| D01 | Wrong branch, unclean unexpected tracked state, non-FF pull, B3 SHA not ancestor, changed scorer shape, or other S01–S15 source contradiction | HARD STOP | Record exact refs, diff, first contradiction; stop edits; request updated plan | Reset, stash, clean, rebase, force-push, adapt design to unknown code | Preflight; maintainer |
| D02 | Only previously known locally excluded `.coverage`, `benchmark-results/`, `benchmarks/quervant_bench.egg-info/` are present; no other change | AUTO-RESOLVE | Leave untouched and continue using explicit staged paths | Modify excludes, delete data or stage artifacts | Preflight exception report |
| D03 | Earlier B1/B2/B3 CI/RustFS unfinished but B3 source/semantics verified | DEFER AND CONTINUE | Record external pending and proceed with B4 local work | Wait for jobs or declare earlier results PASS | External evidence; maintainer |
| D04 | Exactly S01–S15 hold, including strict runtime guard, decoded freq and two scorer callers | AUTO-RESOLVE | Implement §§4–5 verbatim | New dispatch architecture, generic scorer rewrite | Source/implementation gate |
| D05 | B4-U01 compile RED is solely missing `score_single_term_candidates` symbol | AUTO-RESOLVE | Record expected error, apply §4 helper, continue to GREEN | Alter fixture/expected values | Red-first gate |
| D06 | RED shows unexpected error, borrow mismatch in test scaffold, wrong fixture/score, or another missing symbol | HARD STOP | Capture first diagnostic, halt code changes pending corrected plan | Modify tests to force expected RED | Test contract; maintainer |
| D07 | Postings loop and `is_match` callback exactly match S03–S05 | AUTO-RESOLVE | Capture `(doc_id,freq)` after successful callback; preserve checks | Score in loop, skip callback/losers, re-read postings | I03/I09/I10 |
| D08 | A real candidate list is nonascending/duplicate or a B3 debug assert trips | HARD STOP | Record offending physical IDs/fixture and stop | Sort, dedup or discard duplicates | I07; maintainer |
| D09 | BM25 arguments, score bits, zero sign, field ownership or typed `InvalidScore` differ | HARD STOP | Record first doc/term/expected/actual score/error and source | Change BM25 formula, tolerance or skip error | I04/I09/I15 |
| D10 | 48/64 modeled reservation, exact/one-under peak, release order, batch meter or cleanup differs | HARD STOP | Capture exact limit/requested, meter state and source | Lower logical charge, add ad hoc cap or reorder release | I08 |
| D11 | Poll counts, scanned work, callback side effects, key/sort validation or failure precedence differ | HARD STOP | Keep minimal fixture and first typed error; stop | Move scoring earlier, short-circuit K, relax validation | I01/I06/I09/I10/I12 |
| D12 | Compiling B4 would require production changes outside `execute.rs`, new `score.rs`, generic scorer algorithm, `unified.rs` APIs, feature, codec or fifth tracked path | HARD STOP | Record exact missing seam and seek a plan amendment | Broaden allowlist, introduce output enum/trait/new index format | Scope; maintainer |
| D13 | Rustfmt or Clippy reports a simple mechanical formatting/unused-import issue wholly within prescribed new lines | AUTO-RESOLVE | Apply only deterministic local adjustment, inspect diff and rerun affected QA | Disable lint or change scorer/error semantics | Local QA; report |
| D14 | Test-only scorer counters compile and direct/ineligible witnesses agree with eligibility | AUTO-RESOLVE | Retain only `#[cfg(test)]` instrumentation and continue | Expose production counters or new runtime knob | Witness gate |
| D15 | Scorer counters can only be implemented with production overhead, or existing B1/B2/B3 test expectations must be weakened | HARD STOP | Preserve observation, require new design approval | Turn off counter, relax test, change old assertions | Test/semantics gate |
| D16 | Local RustFS unavailable; hosted CI pending | DEFER AND CONTINUE | Run all independent local gates, mark real external test BLOCKED/PENDING, push truthful report | Privileged provisioning, infinite wait, fake PASS | External topology |
| D17 | MSRV, stable or `cargo llvm-cov` unavailable after safe standard setup | DEFER AND CONTINUE | Document missing tool/command; run independent gates; keep QA NOT VERIFIED | Lower 85% floor or claim CI passed locally | Mandatory QA |
| D18 | Required test/lint/coverage gate failed and root cause unresolved | DEFER AND CONTINUE | Classify with evidence, at most one safe scoped baseline reproduction; independent work only; acceptance BLOCKED | Repeated random retries, skip/censor failing gate | QA failure; maintainer |
| D19 | One deterministic typo strictly in newly added B4 test scaffolding, with exact correction obvious from §7 | AUTO-RESOLVE | Correct once, rerun affected plus final QA, disclose | Change expected BM25 values/limits to make test green | Test-local fix |
| D20 | Any implementation needs unsafe, Vec reinterpretation, frequency cast/float-bit packing, cross-query cache, or generic output API change | HARD STOP | Record proposed extra operation and stop | `transmute`, `from_raw_parts`, alternative architecture | Ownership/safety |
| D21 | Request to benchmark, profile, check CPU symbols/host idle or quantify speed in B4 | AUTO-RESOLVE | Do NOT perform; continue correctness, leave C campaign untouched | Timed A/B, `perf record`, microbenchmark, host probe | Stage boundary |
| D22 | Approved Markdown plan copy contains trailing whitespace or staged `git diff --cached --check` conflicts with verbatim copy | HARD STOP | Record offending lines/check result and request corrected plan bytes | Waive check, silently alter verbatim approved plan | Documentation; maintainer |
| D23 | Non-FF push, remote branch changed after test preflight, or remote SHA mismatch after push | HARD STOP | Preserve local commit, show local/remote SHAs and request reconciliation | Force-push, merge/rebase by agent, auto-resubmit | Git integrity |
| D24 | Local QA passes; CI/RustFS incomplete and no other blocker | DEFER AND CONTINUE | Push/report `B4_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`, stop at review handoff | Claim complete hosted acceptance, merge or start B5 | Final handoff |
| D25 | All required local and external gates truly pass with complete evidence | AUTO-RESOLVE | Report `B4_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW`; leave PR open | Merge, benchmark or launch B5 | Final handoff |
| D26 | Selected scoring branch ever runs with malformed one-term leaf or checked metadata mismatch | HARD STOP | Preserve exact `CorruptIndex`, source/ordinal and stop | Assume match/score is safe, fabricate fallback | Query integrity |
| D27 | Score error or cancellation cleanup leaves a nonzero ledger/slot charge versus generic reference | HARD STOP | Retain meter proof and failing fixture; stop | Reset counters or ignore cleanup test | Memory/error parity |
| D28 | Any unforeseen case not *exactly* covered above, or contradictory rules apply | HARD STOP | Stop dependent work, list smallest missing human decision and unaffected steps | Guess, interpret plan loosely, add another algorithm | Maintainer amendment |

**Mandatory failure taxonomy:** Introduced regression; feature implementation defect; deterministic pre-existing failure; nondeterministic/flaky failure; environment/harness failure. A pre-existing claim requires concrete baseline evidence, not "unrelated"; a flaky claim requires demonstrated nondeterminism. An unclassified failure leaves dependent acceptance BLOCKED. All matrix actions and external pending conditions belong in the final report with source/command evidence.

## 15. Terminal directive

Carry out **only PERF-05-B4** exactly as specified: source-trace preflight, a narrowly scoped expected RED, the two-buffer eligible scoring helper, exact parity/negative tests, complete local stable/MSRV/coverage and real FsDirectory gates, controlled four-file diff, byte-identical whitespace-clean plan copy, one bounded pushed commit and independent-review report. **No timing, benchmarking, profiling or B5 work.** On any unanticipated architecture or correctness issue, stop instead of designing. The sole PR is #117 and must remain unmerged.
