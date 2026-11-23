# PERF-05-B3 — Replace Unified Matched-Document Tree with an Ordered Vector

**Detailed coding-agent execution plan — frozen design v1.0, 2026-11-22**

**Repository:** `yduchesne/quervant`
**Series branch:** `dev/perf05-physical-execution-series`
**Existing PR:** [#117](https://github.com/yduchesne/quervant/pull/117), draft/open; **do not create a branch or PR**
**Inspected B2 head:** `dfa876c52d5227087ee2085525f64f9ce97600ed`
**Inspected main:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8`
**Upstream prerequisites:** PERF-05-B1 commit `668206ba1ba94fda696fb9f395b6b65023b0e1cf` and B2 commit `dfa876c52d5227087ee2085525f64f9ce97600ed`
**Status at plan creation:** B3 **NOT IMPLEMENTED**; this is a bounded implementation contract, not proof of completed work.
**Authoritative sources:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md`, and `docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md`.

---

## 0. Mandatory execution contract — READ FIRST

**Single dominant architectural change:** In the existing `search/execute.rs::evaluate_lexical_with`, matching physical document IDs are visited in strictly ascending order exactly once. Instead of inserting each ID into a newly allocated `BTreeSet<u64>`, accumulate it in an append-only `Vec<u64>`. Adapt the **same existing** `score_segment` function to consume an `ExactSizeIterator<Item = &u64>`, so it can accept both the existing sibling `execute_segment_inner` tree iterator and the new unified ordered-vector iterator. Do **not** duplicate the scorer or change its BM25 arithmetic.

**Precisely what B3 removes:** the matched-ID `BTreeSet` and its O(log M) insertions in the unified evaluator. **Precisely what stays:** decoded postings, predicate evaluation and B1 shortcut, B2 verified live counts/cancellation, the scored `BTreeMap`, the `Vec<(u64, f64)>` built from that map, all work/memory-budget charges, full-match scoring, key validation, sort and Top-K selection. Removing the score map, eliminating additional postings traversals, or changing scored output is reserved for **B4**, not B3.

**Continuous execution authorization:** Once this approved plan is given to the coding agent, execute all its ordered phases without asking for routine reconfirmation. Continue automatically after successful preflight, expected red-first failure, stage completion, routine QA, and an applicable AUTO-RESOLVE decision. For a DEFER AND CONTINUE condition, preserve evidence and perform all provably independent work. Stop affected work only under an exact HARD STOP rule, an unresolved human-only architectural decision, or a genuine essential dependency. For an unforeseen condition not covered by §14, **HARD STOP the affected implementation; never improvise a different algorithm**.

**Host and timing:** Assume the host is **idle and ready to run performance benchmarking** as expressly instructed; **do not probe or wait for an idle host**. This does **not** authorize timed measurements. **No benchmarking, profiling, A/A, A/B, `quervant-bench run`, `perf record`, `perf script`, timing loops, or new performance counters during B3.** Compilation-only `cargo bench --workspace --no-run` and existing benchmark-script *self-tests* are permitted. A single consolidated benchmark/profiling campaign occurs later in **PERF-05-C**.

**Prior-stage CI:** **Do not wait** for B1/B2 hosted CI or RustFS to complete before implementing B3. Record any failures/pending status honestly. Do not claim B1/B2 external acceptance because B3 depends on their source changes. B3's exact final source must still meet its own local correctness/QA gates.

**Ownership and authority:** All implementation, tests and agent report go on the **same** `dev/perf05-physical-execution-series` branch and existing PR #117. Do not merge, rebase, force-push, change `main`, alter branch protection, mark all of PERF-05 DONE, run B4, or make index-format/benchmark-framework changes.

---

## 1. Source-verified facts and the architectural proof

The following facts were checked on the **actual B2 series head**, not inferred solely from the roadmap. The agent MUST revalidate them against the pulled working branch before modifying source. Line numbers are approximate and shift as earlier stages add tests.

| ID | Exact source / symbol | Verified fact |
| --- | --- | --- |
| S01 | `crates/quervant-core/src/search/execute.rs::evaluate_lexical_with` (~1950–2090) | Uses `let mut matched: BTreeSet<u64> = BTreeSet::new();`, calls `matched.insert(...)` in **exactly two branches**, reserves `matched.len() * SET_BYTES_PER_ENTRY`, passes `&matched` to `score_segment`, then drops matched before releasing its logical reservation. |
| S02 | Same function, eligible posting branch | Strict `LeafData::Term` shape guard and B2 verified-live helper run before visiting a validated, sorted, effective-live single-term postings vector. Each `(doc_id, _freq)` occurs **once**, in strictly ascending order. B1 shortcut in the unified closure makes the already-proven positive lexical match true without relookup. |
| S03 | Same function, fallback live-bitmap branch | `live.iter().enumerate()` visits each physical document index in strictly ascending order and at most once. `is_match` may be true or false and may have effects; only true IDs are appended. No duplicate physical ID is possible even for Boolean/mixed/typed predicates. |
| S04 | `execute.rs::build_leaf_data` and `TermPostings` (~908–918 and ~1256 onward) | Postings decoder rejects nonincreasing IDs before the eligible visitor; no resampling or sorting of decoded postings. |
| S05 | `execute.rs::score_segment` (~1669 onward) | Its matched input is used **only** to read exact `len()` and iterate the IDs **once** to seed `BTreeMap<u64, f64>` at `0.0`. All further BM25 contribution iteration traverses leaf postings / phrase matches and updates the map. It does **not** perform `matches.contains`, set union, or need random access. |
| S06 | `execute.rs::execute_segment_inner` (~1180–1250) | Separate lexical/sibling path creates a `ReservedSet { set: BTreeSet<u64>, ... }` using `eval_node`, then passes `&matches.set` to the **same** `score_segment`. This path and its set/boolean logic MUST stay intact; only pass its existing `BTreeSet::iter()` at the scorer boundary. |
| S07 | `execute.rs::SET_BYTES_PER_ENTRY = 48`; `SCORED_MAP_BYTES_PER_ENTRY = 64` | Conservative **logical** accounting units, not Rust heap allocation measurements. Unified matched-ID charge is performed after traversal, before `score_segment`, and released after scoring; the scored-map charge occurs while the matched buffer and postings remain live. Preserve exact peak arithmetic and release order. |
| S08 | `execute.rs::SegmentCandidateLedger` and `CandidateBudget` | `reserve_with_memory` / `release_with_memory` and RAII `Drop` govern checked segment and batch accounting. No new ledger, work meter, byte multiplier, or early release is needed. |
| S09 | `unified.rs::collect_mixed` (~800 onwards) | Calls `evaluate_lexical_with`, consumes its ordered scored `Vec` and performs exact hit counting, key/sort validation, duplicate policy and bounded heap admission. **No production caller API change** is needed. |
| S10 | `score_segment` has **two** production call sites, both in `execute.rs` | One is from `execute_segment_inner` with `&matches.set` and one from `evaluate_lexical_with` with `&matched`. Change each to `.iter()` and retain one common scorer implementation. Verify no new call sites have appeared. |
| S11 | Existing in-file `execute.rs::budget_tests`, `unified.rs::phase4_tests`, `unified.rs::b_tests` | Already test ledger limits and release, B1 direct/wrapped term parity, B2 count/cancellation, exact result/score bits, sort, deletions and multiple segments. Reuse and extend; do not rewrite prior tests. |
| S12 | `score.rs::SnapshotStats` after B2 | Includes query-local verified per-segment live counts. B3 consumes the existing object through the existing scorer input. Do not change `score.rs`, recompute stats, or remove B2's cache. |
| S13 | The Rust standard library | `BTreeSet::iter()` and `Vec::iter()` both implement `ExactSizeIterator<Item = &u64>` on the project's supported Rust toolchains; this lets a single scorer accept either without boxing, cloning the collection, or allocating an adapter. |

**Proof of sorted uniqueness:** S02 covers the one-term decoded postings path; S03 covers every remaining unified path. Filtering an ascending unique input by a Boolean predicate preserves ascending uniqueness, even with negative/typed/multi-term conditions. The original `BTreeSet::insert` therefore never performs meaningful deduplication on the unified path. The sibling S06 path still requires tree set operations and is **not** to be converted.

**Complexity:** In the unified path, append to a `Vec<u64>` is amortized O(1) per match, versus O(log M) insertion into a balanced tree. The scorer's original `BTreeMap<u64, f64>` and all scoring passes are unchanged in B3. The overall query is **not** yet O(M); do not claim an end-to-end speedup before PERF-05-C.

**Lifetime:** `matched: Vec<u64>` is owned by the unified segment evaluator, borrowed immutably by `score_segment`, then dropped before its old logical matched-set reservation is released. The caller still receives only the separate scored vector. No new memory alias, cross-query state, global cache, storage change, transaction or remote read is introduced.

---

## 2. Reconcile main, branch and preceding stages

| Component | Inspected status before B3 | B3 action |
| --- | --- | --- |
| Accepted `main` / PERF-02-B | `9775bfca…` baseline, still on main at authoring | Read only; never merge/rebase to accommodate B3 |
| B1 membership relookup fix | `668206ba…`, retained on series branch | Preserve verbatim; test it still returns 0 lookups for strict eligible term and normal fallback lookups |
| B2 verified-live metadata | `dfa876c5…`, current branch head | Preserve verbatim; test its chunk-poll/accounting invariants |
| Unified matched `BTreeSet` | Present in `evaluate_lexical_with` | Replace **only this** tree with append-only ordered `Vec` |
| Sibling matched `ReservedSet` | Present in `execute_segment_inner` | Preserve tree and evaluator; only scorer argument becomes `.iter()` |
| Shared `score_segment` | Takes `&BTreeSet<u64>`, seeds scored map using `.iter()` | Broaden **input only** to exact-sized iterator, keep algorithm and output unchanged |
| B4 matched/scored buffer reuse | Not implemented | **OUT OF SCOPE** |
| B5 decoded postings lifetime | Not implemented, conditional | **OUT OF SCOPE** |
| PERF-05-C warm benchmark/profiler | Planned | **DO NOT RUN** |

**Preflight interpretation:** A clean head equal to `dfa876c52d5227087ee2085525f64f9ce97600ed` is the exact expected state. A newer descendant is acceptable **only if** none of the source contracts S01–S13, B1/B2 files or proposed code/test locations has changed and the additional commits are understood and reviewed; otherwise HARD STOP. Never copy B3 code from main, which intentionally lacks B1/B2.

---

## 3. Boundaries, exclusions and allowed files

### 3.1 Authorized tracked file changes (EXACT allowlist)

1. `crates/quervant-core/src/search/execute.rs`: production modifications limited to the `score_segment` **input type + seeding expression**, its **two call sites**, and unified `matched` collection declaration and two inserts. New B3 unit tests may be appended to existing `#[cfg(test)] mod budget_tests`. A concise source comment about ordered uniqueness and unchanged logical accounting is permitted.
2. `crates/quervant-core/src/search/unified.rs`: **test code only**, inside existing `#[cfg(test)] mod phase4_tests`, for one real unified query-output parity regression. Production B1 logic must be byte-identical to B2 head.
3. `docs/pr-artifacts/perf-05/PERF05B3_DETAILED_PLAN.md`: exact supplied approved plan, copied byte-for-byte by the coding agent for traceability.
4. `docs/pr-artifacts/perf-05/PERF05B3_EXECUTION_REPORT.md`: agent's actual execution, evidence, exceptions and status.

**No other tracked files.** In particular, no changes to `search/score.rs`, `search/work.rs`, `search/typed.rs`, `search/plan.rs`, `search/unified_plan.rs`, segment reader/codecs, RustFS, top-K/duplicate strategy, Cargo manifests, feature flags, CI, benchmark runner/config/results, project ROADMAP/BENCHMARKING, or the B1/B2 reports. Do not change `execute_search`, `eval_node`, `ReservedSet`, `build_leaf_data`, `LeafData::matches`, `TermPostings`, BM25 formula, the scored `BTreeMap`, or output `Vec<(u64, f64)>`.

### 3.2 Explicit non-goals

- No optimized special-case scorer, second scoring algorithm, direct-to-heap pipeline, late scoring, new iterator trait, boxed iterator, enum executor, virtual dispatch, or instruction-level tuning.
- No early stop after K, candidate-count approximation, typed/Boolean shape exclusions, reordering, sorting/dedup of the new matched vector, dropped corruption validation, new cache, or changed ResourceLimit/cancellation behavior.
- No new benchmark/profiler instrumentation, no profiling build and no timed results. PERF-05-C handles final combined qualification.

### 3.3 Deliberate compatibility choices

- Preserve the logical `SET_BYTES_PER_ENTRY = 48` accounting **even though the physical container is now a `Vec<u64>`**. This is an existing conservatively modeled logical admission contract, not the allocation size. No reduction in allowed/rejected work or result budget is permitted as an accidental side effect.
- Keep the old time of reservation (after all matches have been collected). Do not move `reserve_with_memory` before each append, skip the charge because the vector is smaller, or release earlier.
- Use `Vec::new()` and ordinary `Vec::push` with Rust's normal amortized growth. Do **not** preallocate `live.len()` or `postings.len()` (would add sparse-path work), call `sort`, `dedup`, `binary_search`, or add a per-document fallible reserve that changes the failure surface. The physical allocator's out-of-memory behavior remains an environmental limitation; do not invent a new resource policy here.
- For debug builds only, assert that appended IDs are strictly ascending. This is a sanity witness of S02/S03, **not** an added release-time validation/charge.

---

## 4. Exact production design — no choices left to the agent

**All production code changes occur inside `crates/quervant-core/src/search/execute.rs`.** Apply in the numbered order below. If source differs from the inspected shape, use §14's STOP matrix, not a different design.

### 4.1 Change only `score_segment` input to an exact-sized iterator

Current function starts approximately:

```rust
fn score_segment(
    matches: &BTreeSet<u64>,
    leaf_data: &[LeafData],
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(BTreeMap<u64, f64>, Charges)> {
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };
    let mut scores: BTreeMap<u64, f64> = matches.iter().map(|doc| (*doc, 0.0)).collect();
```

Replace **only** the function's first parameter, add the explicit item lifetime, and replace the one map-seeding expression. Use this exact resulting shape:

```rust
fn score_segment<'a>(
    matches: impl ExactSizeIterator<Item = &'a u64>,
    leaf_data: &[LeafData],
    stats: &SnapshotStats<'_>,
    segment_index: usize,
    positive: &BTreeSet<usize>,
    ledger: &mut SegmentCandidateLedger<'_>,
    memory: Option<&mut (dyn MemoryCharge + '_)>,
) -> SearchResult<(BTreeMap<u64, f64>, Charges)> {
    let entries = matches.len() as u64;
    let bytes = bytes_for_count(entries, SCORED_MAP_BYTES_PER_ENTRY)?;
    ledger.reserve_with_memory(entries, bytes, memory)?;
    let charges = Charges { entries, bytes };
    let mut scores: BTreeMap<u64, f64> = matches.map(|doc| (*doc, 0.0)).collect();
```

**Do not touch any subsequent line** in `score_segment`, including the early `scores.is_empty()` return, term-ownership map, both positive lexical scoring loops, BM25 arguments, `scores.get_mut`, or final return. It still creates the exact same BTreeMap entries and updates them in the exact same leaf/postings order. The input iterator is **consumed exactly once** in map seeding; its `len()` is an O(1) exact count, and no clone, copy of the whole collection, boxing or virtual dispatch is needed.

**Call site A — sibling old lexical executor** (`execute_segment_inner`, ~line 1213):

```rust
let (scored, scored_charges) = score_segment(
    matches.set.iter(), // ONLY change from &matches.set
    &leaf_data,
    stats,
    segment_index,
    &compiled.positive_leaf_indices,
    ledger,
    None,
)?;
```

All `eval_node`, `matches.release(ledger)?` and sibling scoring/output logic remains intact. No new `Vec` or converted set is allocated in the sibling path.

**Call site B — unified lexical evaluator** (`evaluate_lexical_with`, ~line 2050):

```rust
let (scored, scored_charges) = score_segment(
    matched.iter(), // ONLY change from &matched
    &leaf_data,
    stats,
    segment_index,
    positive,
    &mut ledger,
    memory.as_deref_mut(),
)?;
```

Do not introduce a second scorer, trait, enum, helper callback or generic parameter on `evaluate_lexical_with` itself. The existing public and private executor interfaces, apart from the private scorer's input, remain unchanged.

### 4.2 Replace the unified matched-ID tree with an ordered vector

In `evaluate_lexical_with`, replace exactly:

```rust
let mut matched: BTreeSet<u64> = BTreeSet::new();
```

with:

```rust
// Both enumerators visit each effective-live physical doc ID once and in
// strictly ascending order. Keep the old logical SET_BYTES_PER_ENTRY charge.
let mut matched: Vec<u64> = Vec::new();
```

In the **eligible postings loop** replace exactly its success arm:

```rust
if is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())? {
    matched.insert(*doc_id);
}
```

with:

```rust
if is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())? {
    debug_assert!(matched.last().is_none_or(|last| last < doc_id));
    matched.push(*doc_id);
}
```

In the **fallback live-bitmap loop** replace exactly its success arm:

```rust
if is_match(doc_id, &leaf_data, meter, memory.as_deref_mut())? {
    matched.insert(doc_id);
}
```

with:

```rust
if is_match(doc_id, &leaf_data, meter, memory.as_deref_mut())? {
    debug_assert!(matched.last().is_none_or(|last| *last < doc_id));
    matched.push(doc_id);
}
```

The `debug_assert!` checks use only already-owned IDs and disappear from ordinary optimized release binaries. The `is_none_or` Option method is available in Rust 1.85; if compilation on the mandated MSRV disproves this, STOP rather than silently adopting an alternate implementation. Do not add a release-time compare or independent duplicate-check structure.

**Preserve unchanged** the remainder of `evaluate_lexical_with`:

```rust
let matched_entries = matched.len() as u64;
let matched_bytes = bytes_for_count(matched_entries, SET_BYTES_PER_ENTRY)?;
ledger.reserve_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
// score_segment(matched.iter(), ...) as specified above
let scored_vec: Vec<(u64, f64)> = scored.into_iter().collect();
drop(matched);
drop(leaf_data);
ledger.release_with_memory(matched_entries, matched_bytes, memory.as_deref_mut())?;
// then unchanged postings and scored-map release, Ok(scored_vec)
```

The comment above is a **sequence illustration**, not a replacement block; do not remove intermediate lines or reorder drops. Crucially, the matched vector stays alive through `score_segment`, is dropped before the logical charge release, and the output vector is still built **from the scored map**, not from the matched vector. B4 may revisit that relationship later, but not B3.

### 4.3 Why these are the only necessary production edits

The scored BTreeMap remains unchanged, seeded from ordered unique IDs in either caller. Its BM25 loop still searches contributions by ID and accumulates in the same order, so score bits are expected to remain equal. The scorer's input is read only once and only requires exact length; an exact-sized iterator is the minimal internal seam. Using a vector on both unified enumerators removes M tree inserts without adding a new query mode or changing the `UnifiedSearcher` API. The sibling boolean evaluator still uses its original BTreeSet, because B3 is not a rewrite of generic `eval_node`.

**If changes beyond the listed expressions are necessary for correctness or compilation, STOP; the plan does not authorize another architectural representation.** An ordinary rustfmt line wrap confined to these expressions is preauthorized.

---

## 5. Correctness invariants and proof obligations

The agent must complete an invariant-to-test map *before* changing production source, and record exact evidence in the execution report.

| ID | Falsifiable invariant | Production anchor | Acceptance evidence |
| --- | --- | --- | --- |
| I01 | Every effective-live matching physical ID appears **once**, strictly ascending, in the unified matched vector | §4.2, S02/S03/S04 | B3-U03 fixture, phase4 candidate visitation, debug assertions, source audit |
| I02 | No nonmatching, deleted or superseded physical ID is added | §4.2 | phase4 U06/U07/U08, phase4 U16, real mutation/oracle tests |
| I03 | The two original enumerators and `is_match` callback execute unchanged; B1 still skips redundant strict-term relookup | §4.2, B1 | phase4 B1-U01–U04, old predicate witness |
| I04 | The scorer uses the exact same single `score_segment` implementation for sibling BTreeSet and unified Vec | §4.1 | B3-U01/U02 plus full relevant sibling integration tests |
| I05 | Scored-map initial ID keys, zero values, and subsequent BM25 accumulation order remain the same and **score bits** match | §4.1 | B3-U02/U03, existing `b_tests`, `score::tests` |
| I06 | `total_hits`, K1/K10/K100 truncation, document keys, sort and tie ordering, selected projection and cursor output remain correct | §4.2 | B3-U03, phase4 U09 and `b_tests` |
| I07 | Logical matched entry count and `SET_BYTES_PER_ENTRY=48` charge are unchanged at identical site; no early release | §4.2 | B3-U01 charges, source diff, `c2_scored_map_exact_and_one_over` and `c2_*` tests |
| I08 | Scored-map reservation, retained heap/batch accounting, exact/one-below ResourceLimit remain unchanged | §4.1–4.2 | B3-U01 charges, existing `budget_tests`, `pr15e_b1`, phase4 work tests |
| I09 | Cancellation remains checked at the same enumeration, scoring and cleanup boundaries; B2 4096-slot poll schedule unchanged | unchanged callers | B2-U06, phase4 U14, existing cancel/batch tests |
| I10 | Posting decoder continues to validate every decoded posting; corrupt selected or unselected documents and invalid scores are not silently skipped | untouched `build_leaf_data`, `score_segment` | full search corruption/error suites, source diff, RustFS oracle when available |
| I11 | Generic sibling `execute_search` retains its BTreeSet/`eval_node` logic and output contract | §4.1 Call site A | B3-U01/U02, lexical oracle and integration regressions |
| I12 | Typed, phrase, negation, multi-term, aggregation and cursor paths remain correct; no new eligibility rules | unified fallback untouched | B3-U03, phase4 U01–U05, relevant all-feature tests |
| I13 | No new sorting/dedup pass or M-scale temporary object is introduced in B3 | §4.2 | source diff inspection; grep for `sort`, `dedup`, `collect` in changed lines |
| I14 | The physical Vec can grow amortized while old conservative **logical** candidate limits remain enforced | §3.3, §4.2 | source review and candidate budget exact/one-over tests |
| I15 | No public API, persistent codec, manifest, index layout, RustFS I/O, cache, feature flag or profiling mode changes | allowlist | diff audit, stable/MSRV, local and RustFS where available |
| I16 | B1 and B2 code/behavior is preserved; their external gates stay truthful and independent | prior commits | git diff vs START_SHA, B1/B2 focused regressions, report/CI status |

**A red-first test that proves a new scorer iterator type compiles** is distinct from a green correctness test. A unit test with empty scoring leaves alone is not proof of BM25 parity: B3-U02 tests actual positive-term BM25 using real decoded fixture postings, while existing cross-component tests preserve the broader semantics.

---

## 6. Prescribed tests and red-first protocol

**Only two test modules may be edited:** existing `execute.rs::budget_tests` and existing `unified.rs::phase4_tests`. Do not invent a new test crate, benchmark, macro framework, fake scorer, or runtime instrumentation. Expected IDs and outputs must come from independent fixed fixture facts, and tests should examine actual production functions.

### 6.1 Test helper (test-only, no new production API)

At the end of `#[cfg(test)] mod budget_tests` in `execute.rs`, add the following internal helper. It invokes the **real** `score_segment`, consumes the result to score bit patterns and releases the real scorer reservation before finishing the ledger. It introduces **no new production scorer**:

```rust
fn b3_score_from_iterator<'a>(
    ids: impl ExactSizeIterator<Item = &'a u64>,
    leaf_data: &[LeafData],
    stats: &SnapshotStats<'_>,
    positive: &BTreeSet<usize>,
) -> (Vec<(u64, u64)>, Charges) {
    let limits = SearchLimits::default();
    let mut budget = CandidateBudget::new(&limits);
    let mut ledger = SegmentCandidateLedger::new(&mut budget).unwrap();
    let (scored, charges) =
        score_segment(ids, leaf_data, stats, 0, positive, &mut ledger, None).unwrap();
    let result_bits = scored
        .into_iter()
        .map(|(doc_id, score)| (doc_id, score.to_bits()))
        .collect::<Vec<_>>();
    ledger.release(charges.entries, charges.bytes).unwrap();
    ledger.finish().unwrap();
    (result_bits, charges)
}
```

This helper is **test-only** and available only within `budget_tests`; the source did not require any additional imports for `Vec`, `BTreeMap`, `BTreeSet`, `SegmentReader`, `Rc` or scorer types because `use super::*` is already present. Do not expose it or use it in release paths.

### 6.2 B3-U01 — first RED then GREEN: exact-sized tree and vector iterator

**Before applying any production edits**, add this exact test after the helper:

```rust
#[test]
fn b3_u01_scorer_accepts_tree_and_vec_iterators() {
    use crate::analysis::NeverCancel;

    let cancel = NeverCancel;
    let limits = SearchLimits::default();
    let readers: [&SegmentReader; 0] = [];
    let live: Vec<Rc<Vec<bool>>> = Vec::new();
    let terms: super::super::score::QueryTerms = BTreeMap::new();
    let mut work = SearchWork::new(limits.max_total_work_units(), &cancel);
    let stats = compute_stats(&readers, &live, &[], &terms, &limits, &mut work, &cancel)
        .expect("empty scoring stats");
    let positive = BTreeSet::<usize>::new();
    let leaves: Vec<LeafData> = Vec::new();
    let cases: [&[u64]; 4] = [&[], &[0], &[0, 3, 9], &[0, 1, 2, 3]];

    for case in cases {
        let ordered = case.to_vec();
        let tree: BTreeSet<u64> = ordered.iter().copied().collect();
        let (from_tree, tree_charge) =
            b3_score_from_iterator(tree.iter(), &leaves, &stats, &positive);
        let (from_vec, vec_charge) =
            b3_score_from_iterator(ordered.iter(), &leaves, &stats, &positive);
        let expected: Vec<(u64, u64)> = case.iter().map(|doc| (*doc, 0.0f64.to_bits())).collect();
        assert_eq!(from_tree, expected);
        assert_eq!(from_vec, expected);
        assert_eq!(tree_charge, vec_charge);
        assert_eq!(vec_charge.entries, case.len() as u64);
        assert_eq!(vec_charge.bytes, case.len() as u64 * SCORED_MAP_BYTES_PER_ENTRY);
    }
}
```

Run **exactly**:

```bash
cargo test -p quervant-core --lib b3_u01_scorer_accepts_tree_and_vec_iterators -- --nocapture
```

**Expected RED:** the old `score_segment` requires `&BTreeSet<u64>`, so the test-only helper's `score_segment(ids, ...)` call produces a **single type mismatch** (Rust E0308 or equivalent) with no unrelated errors. This is a **compile-time RED**, not a performance result. If compilation fails for any other reason, the agent MUST use §14's HARD STOP rule; do not change the design to force a red result.

Apply §4.1 plus call-site edits, then rerun B3-U01 and require it to PASS before changing the unified matched tree. The tree and vector represent exactly the same sorted unique IDs and must produce identical score-map entries and charges.

### 6.3 B3-U02 — real positive BM25 scoring parity across both iterator forms

Add this test in the same existing `budget_tests` module, using the checked-in real norms fixture, real stats computation and real decoded postings. Do **not** invent term frequencies, a fake scorer, or alternative score arithmetic:

```rust
#[test]
fn b3_u02_positive_bm25_tree_and_vec_score_bits_match() {
    use crate::analysis::NeverCancel;
    use crate::segment::SegmentLimits;

    const NORMS: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
    let reader = SegmentReader::open(NORMS.to_vec(), SegmentLimits::default()).unwrap();
    let field_id = reader.schema().field_id("title").expect("title field");
    let cancel = NeverCancel;
    let limits = SearchLimits::default();
    let readers = [&reader];
    let live = vec![Rc::new(vec![true; reader.doc_count() as usize])];
    let mut terms: super::super::score::QueryTerms = BTreeMap::new();
    terms.insert(field_id, BTreeSet::from(["hello".to_owned()]));
    let mut work = SearchWork::new(limits.max_total_work_units(), &cancel);
    let stats = compute_stats(
        &readers, &live, &[field_id], &terms, &limits, &mut work, &cancel,
    )
    .expect("real field norms");

    let mut source = reader.postings(field_id, "hello").unwrap().expect("hello postings");
    let mut postings: Vec<(u64, u64)> = Vec::new();
    while let Some(posting) = source.next_with(&cancel).unwrap() {
        postings.push((posting.doc_id, posting.freq));
    }
    assert!(!postings.is_empty());
    let ordered: Vec<u64> = postings.iter().map(|(doc_id, _)| *doc_id).collect();
    let tree: BTreeSet<u64> = ordered.iter().copied().collect();
    assert_eq!(tree.len(), ordered.len());
    let leaf_data = vec![LeafData::Term {
        field_id,
        terms: vec![TermPostings { term: "hello".to_owned(), postings }],
    }];
    let positive = BTreeSet::from([0usize]);

    let (tree_bits, tree_charge) =
        b3_score_from_iterator(tree.iter(), &leaf_data, &stats, &positive);
    let (vec_bits, vec_charge) =
        b3_score_from_iterator(ordered.iter(), &leaf_data, &stats, &positive);
    assert_eq!(tree_bits, vec_bits);
    assert_eq!(tree_charge, vec_charge);
    assert_eq!(vec_charge.entries, ordered.len() as u64);
    assert!(tree_bits.iter().all(|(_, bits)| f64::from_bits(*bits).is_finite()));
    assert!(tree_bits.iter().all(|(_, bits)| f64::from_bits(*bits) > 0.0));
}
```

Require the two paths' BM25 **bit patterns** and exact scored-map logical charges to match. This is differential evidence using *one* production scorer and real indexed postings; it is not a separate independent BM25 oracle. Existing `score::tests::bm25_golden_values`, real-query B1/B2 regressions and independent `pr13_oracle` complement it.

### 6.4 B3-U03 — actual unified query path and standalone/fallback parity

Append this test **only** inside `unified.rs::phase4_tests`, using its existing real in-memory index helpers (`build`, `corpus`, `term`, `req`, `search`, `keys`):

```rust
#[test]
fn phase4_b3_u03_ordered_unified_matches_preserve_results() {
    let cases: &[(usize, &[usize])] = &[
        (40, &[]),
        (40, &[7]),
        (40, &[0, 3, 9, 39]),
    ];
    for &(doc_count, matching) in cases {
        let index = build(phase4_schema(), corpus(doc_count, matching));
        let snapshot = index.snapshot();
        for sorted in [false, true] {
            for k in [1usize, 10, 100] {
                let direct = search(&snapshot, &req(term("alpha"), k, sorted), SearchLimits::default())
                    .expect("strict eligible query");
                let fallback = search(
                    &snapshot,
                    &req(Query::And(vec![term("alpha")]), k, sorted),
                    SearchLimits::default(),
                )
                .expect("full-scan control");
                assert_eq!(direct.total_hits, matching.len() as u64);
                assert_eq!(direct.total_hits, fallback.total_hits);
                assert_eq!(keys(&direct), keys(&fallback));
                assert_eq!(direct.hits.len(), matching.len().min(k));
                let direct_scores: Vec<u64> = direct.hits.iter()
                    .map(|hit| hit.score.expect("lexical score").to_bits()).collect();
                let fallback_scores: Vec<u64> = fallback.hits.iter()
                    .map(|hit| hit.score.expect("lexical score").to_bits()).collect();
                assert_eq!(direct_scores, fallback_scores);
                let direct_fields: Vec<_> = direct.hits.iter().map(|hit| &hit.fields).collect();
                let fallback_fields: Vec<_> = fallback.hits.iter().map(|hit| &hit.fields).collect();
                assert_eq!(direct_fields, fallback_fields);
                // Cursor bytes include query AST fingerprint; not comparable here.
            }
        }
    }
}
```

This test does not create a fake index. It exercises the real analyzer, index writer, commit, snapshot, `UnifiedSearcher`, scorer and selected projection. The expected match count comes from the independent fixture list. **Do not compare cursor bytes between different query ASTs** because fingerprints legitimately differ.

### 6.5 Required existing regressions — no edits to their assertions

| Test family / command filter | What it protects |
| --- | --- |
| `cargo test -p quervant-core --lib b3_` | All B3 scorer input and real-index regression tests |
| `cargo test -p quervant-core --lib phase4_tests` | B1 eligible/fallback witnesses, B2 work/cancel checks, source eligibility, empty/single/large matches, cursor |
| `cargo test -p quervant-core --lib b_tests` | 50K common high-hit case, borrowed Keyword sort, null/ties, multi-segment score bits, corruption-fallback checks |
| `cargo test -p quervant-core --lib budget_tests` | Matched/scored/heap budget and ledger accounting, overflow/cleanup |
| `cargo test -p quervant-core --lib score::tests` | Golden BM25 and norm/legacy length/df correctness |
| `cargo test -p quervant-core --lib b2_` | Cached live count, exact chunk cancellation and logical work parity |
| `cargo test -p quervant-core --test pr13_oracle` | Independent expected query output from real writer/snapshot; local/fs/remote appropriate tests |
| `cargo test -p quervant-core --test pr15e_b1` | Batch and standalone exact results/work-accounting |
| `cargo test -p quervant-core --test pr06_local_integration` | Real local filesystem commit/reopen and query integration |

**Do not change any previous tests to make B3 pass.** If a pre-existing suite asserts a property that the new code violates, preserve the evidence and follow §14. Hidden RustFS ignored tests are **not** validated merely by building `--all-features`.

---

## 7. Pre-implementation correctness gate and adversarial risk matrix

The coding agent must complete this gate **before writing production code**. Record S01–S13 source observations, I01–I16 invariant → B3-U01/02/03 or prior-suite mappings, and all relevant error transitions in `PERF05B3_EXECUTION_REPORT.md`.

### Required adversarial challenges to the design

| ID | Scenario / proposed incorrect implementation | Required conclusion / test |
| --- | --- | --- |
| A01 | Full-M eligible single-term query with M > K | No early exit: every posting counted, score and `total_hits` exact; B1/phase4 and 50K b_tests |
| A02 | Sparse / absent / singleton | `Vec` has zero/small retained matches, no preallocate-to-N; B3-U03 |
| A03 | Multi-term expansion with duplicate term membership | Fallback enumerates physical docs once; append only matching IDs, do not append per term; phase4 expanded-term and sibling tests |
| A04 | Boolean conjunction, OR, NOT, typed + lexical | Live enumeration stays once per doc, callback semantics unchanged; `phase4_tests`, `pr13_oracle` |
| A05 | Phrase, negative-only, MatchAll, zero-positive-score | Same empty/zero score semantics; `b_tests`, `pr13_oracle` and all-feature suites |
| A06 | One or many tombstones/superseded documents | Iterate effective-live vector and validated postings only; no stale physical ID; phase4 U16, mutation suites |
| A07 | Multi-segment with overlapping term IDs | Each segment independently scores its physical IDs, global key ordering/dedup unchanged; b_u12 and oracle |
| A08 | BTreeSet would have removed duplicates that Vec would retain | S02/S03 source proof makes this unreachable on valid production paths. Debug monotonic asserts help catch future violations; **if any real fixture produces nonascending/duplicate match IDs, HARD STOP** (do not sort/dedup to hide it). |
| A09 | Byte-exact BM25 scores / NaN / invalid df | Score formula and map-update order unchanged; B3-U02, score golden and invalid-score suites |
| A10 | Tight peak candidate budget, batch memory, early error | Preserve logical M × 48 matched and M × 64 scored charges at same sites; `c2_*` tests and `pr15e_b1` |
| A11 | Cancellation during posting decode, candidate enumeration or scoring | No poll moved/removed; phase4 U14, B2-U06, oracle cancellation |
| A12 | A later unselected corrupt document is skipped after early Top-K | Never add early stop; decoding and validation remain exhaustive; existing corrupted/nonwinner tests |
| A13 | Physical `Vec` reallocates / OOM | Logical candidate budget unchanged; standard allocator growth only; do not invent new reservation failure timing or `try_reserve` policy |
| A14 | Same code compiled in Rust 1.85 and 1.98 | Only stabilized `impl ExactSizeIterator`, `Vec::iter`, `BTreeSet::iter` and `Option::is_none_or`; stable/MSRV QA |
| A15 | Generic scorer is duplicated or later stages are implemented prematurely | Exactly one `score_segment` body, no new physical executor; diff audit |
| A16 | Local FS or remote RustFS not accessible | Source change is query-local; run real local suites; if RustFS missing, report external BLOCKED and continue without fabrication |

### Failure states and atomic cleanup

- **Error during `build_leaf_data` or enumeration:** Existing ledger RAII releases retained posting reservations. No new publication or partial query response.
- **Error during matched logical reservation:** Identical exact M and charge as baseline; drop Vec on unwind and ledger releases outstanding segment reservations as before.
- **Error during scored map reservation/BM25:** Same scorer code, map and ledger; matched Vec dropped on unwind, no final query response or premature charge release.
- **Cancellation:** Existing `MixedWorkMeter` and `SearchWork` checks remain at same source locations and counts on unchanged inputs.
- **Missing RustFS/CI:** Gate remains pending, not PASS. Code progress is not held for remote CI by maintainer instruction.
- **No writes:** B3 does not change indexing, commits, immutable reader state, cache/remote I/O, or recovery. Retried read-only queries construct fresh query-local Vecs and return the same response.

### Residual risks to disclose (not reasons to improvise)

- The shared scorer's generic iterator may produce a different machine-code layout on release builds; **not known to improve wall time** until PERF-05-C.
- The new Vec has a different physical allocation pattern from BTreeSet while retaining the same conservative logical admission charge; standard OS/allocator out-of-memory behavior is not a separately verified persistence guarantee.
- Strict ascending-unique production invariants are source-proven today but would require review if an earlier stage extends the eligible visitor or introduces new enumeration shapes.

---

## 8. Exact agent preflight — no destructive cleanup

Run from repository root in this order. **Inspect status before changing branches or pulling.** Capture exact command outputs in the report. No host-idle probe or benchmark allowed.

```bash
set -euo pipefail

git status --porcelain=v1 --untracked-files=all
# STOP for unexpected tracked changes, conflicts, or untracked source files.
# B1/B2 previously generated .coverage, benchmark-results/** and
# benchmarks/quervant_bench.egg-info/** are allowed to remain untouched;
# DO NOT hide, delete, clean, stash, reset or modify .git/info/exclude.

git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series

git rev-parse HEAD
git rev-parse origin/main
git branch --show-current
git status --porcelain=v1 --untracked-files=all
# Required B2 ancestor:
git merge-base --is-ancestor dfa876c52d5227087ee2085525f64f9ce97600ed HEAD
# Required B1 ancestor:
git merge-base --is-ancestor 668206ba1ba94fda696fb9f395b6b65023b0e1cf HEAD
# If HEAD differs from dfa876c5, review EVERY intervening commit and
# HARD STOP if B3 source symbols, existing tests, or B1/B2 behavior changed.

rg -n 'fn score_segment|score_segment\(|fn evaluate_lexical_with|let mut matched|matched.insert|SET_BYTES_PER_ENTRY|mod budget_tests' \
    crates/quervant-core/src/search/execute.rs
rg -n 'mod phase4_tests|mod b_tests|phase4_b1|b2_|single_term_postings_eligible' \
    crates/quervant-core/src/search/unified.rs
rustc --version
cargo --version
rustup toolchain list
```

**Mandatory source checks:** confirm S01–S13, exactly two `score_segment` calls, exactly two unified matched-ID insertions, unchanged B1 callback and B2 count/poll helper, and that no B3 source already exists. If source already implements B3, **STOP and report it** rather than reimplement. If branch has diverged or `main` differs in B3-specific sources, explain but do not reset/rebase. External B1/B2 CI pending is **not** a reason to wait.

**Pre-implementation correctness challenge:** Before production edit, enumerate concrete counterexamples for duplicate IDs, nonmonotone enumeration, scorers using `contains`, budget charge moved earlier, and scorer reimplementation. Resolve each only using S01–S13 and the fixed design. If any counterexample is reachable in the current production path, HARD STOP and request a corrected design.

---

## 9. Ordered autonomous implementation and verification

### Phase P0 — status, source, baseline and test mapping

1. Complete §8 preflight. Save start SHA, main SHA, branch/PR state, toolchains and scoped diff.
2. Record all S01–S13 and I01–I16 mappings to tests from §5–7. Do not assume B1/B2 external CI was successful; record pending if so.
3. Run an **untimed baseline correctness** check on the pulled current B2 source:

```bash
cargo test -p quervant-core --lib phase4_tests
cargo test -p quervant-core --lib b2_
```

If baseline fails, classify with §14; do not edit B3 source until the failure has an approved disposition. Existing generated artifacts may remain untouched. These are ordinary tests, not performance measurements.

### Phase P1 — test-only scorer-input RED

1. Add **only** the §6.1 test helper and §6.2 B3-U01 test at the end of `execute.rs::budget_tests`. Do not edit production `score_segment` yet.
2. Run the exact B3-U01 test command from §6.2 and require a compilation RED attributable solely to old scorer expecting `&BTreeSet<u64>` instead of exact-size iterator.
3. Record compiler diagnostic and SHA/worktree state. If RED differs (missing test dependencies, bad fixture, linker error, unrelated failure), HARD STOP. Do not adjust expected scores or rewrite the design to force RED.

### Phase P2 — one scorer seam, two caller updates

1. Apply §4.1 **verbatim** to `score_segment` input and single map seeding expression.
2. Update sibling `execute_segment_inner` call to `matches.set.iter()`, preserving its tree and ledger contracts.
3. Update unified call to `matched.iter()` (old BTreeSet still present at this moment).
4. Rerun B3-U01. Require GREEN, including exact ordered IDs, zero-bit scores and charges for tree and Vec iterator sources.
5. If any extra caller or type appears, STOP; do not add a wrapper or change public interfaces.

### Phase P3 — unified matched `Vec` and positive-BM25 tests

1. Apply §4.2 declaration, two success arms and *only* those edits. Keep predicate calls, meter charges, checks and drop/release positions fixed.
2. Add §6.3 B3-U02; require scorer tree/vector **score-bit parity on real index postings**.
3. Add §6.4 B3-U03 in `unified.rs::phase4_tests`; require exact fixture counts, ordering, score bits and projection vs wrapped fallback.
4. Run all B3 and focused regressions from §6.5. Investigate failures only through §14; no alternate data structure.
5. Review `execute.rs` diff to show that only the unified matched collection is Vec, while sibling `ReservedSet` and score map remain BTreeSet/BTreeMap.

### Phase P4 — full mandatory local QA (after final code/test edits)

Use the actual CI commands from `.github/workflows/ci.yml` and engineering policy in `AGENTS.md`. Run all commands below; record command, real count/version, PASS/FAIL/BLOCKED and exact source SHA. **Do not skip workspace gates just because focused tests passed.**

```bash
# Focused Rust tests: real algorithm / writer / reader / scorer.
cargo test -p quervant-core --lib b3_ -- --nocapture
cargo test -p quervant-core --lib phase4_tests -- --nocapture
cargo test -p quervant-core --lib b_tests -- --nocapture
cargo test -p quervant-core --lib budget_tests -- --nocapture
cargo test -p quervant-core --lib score::tests -- --nocapture
cargo test -p quervant-core --lib b2_ -- --nocapture
cargo test -p quervant-core --test pr13_oracle
cargo test -p quervant-core --test pr15e_b1
cargo test -p quervant-core --test pr06_local_integration

# Stable toolchain (CI 1.98.1 at inspected head).
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps

# Minimum supported Rust 1.85.0.
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features

# Compile-only, script self-tests (no timed acquisition).
cargo bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh

git diff --check
```

**Coverage gate:** actual **workspace-wide applicable production Rust line coverage ≥85%**, no exclusions/threshold change; report command, toolchain, numerator/denominator/percentage, and new-code coverage observations. A coverage command existing in CI is not proof it ran locally.

**Formatting repair:** If rustfmt changes **only** authorized Rust lines, run `cargo fmt --all`, inspect exact diff and rerun all affected mandatory tests/lints/coverage on final source. If formatting would modify any forbidden file, STOP and report it. Do not add Clippy allows, disable tests, or change release compiler flags.

**Real RustFS:** If an already available pinned local RustFS endpoint and required `QUERVANT_RUSTFS_*` settings exist, run at minimum the existing `pr13_oracle` and `pr15g_b_rustfs` ignored real-service tests per `.github/workflows/ci.yml`:

```bash
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1
```

If RustFS is not available locally, report **RUSTFS_LOCAL_BLOCKED / HOSTED_RUSTFS_CI_PENDING**, complete independent checks and push truthful local evidence. Do not provision privileged services, substitute mocks for real RustFS, or await CI indefinitely. B3 is not final external acceptance and no benchmark occurs here.

**Failure taxonomy:** Every mandatory failure must be classified as (1) introduced regression, (2) B3 implementation defect, (3) deterministic pre-existing failure, (4) nondeterministic/flaky failure, or (5) environment/harness failure. “Unrelated” is not sufficient. A pre-existing diagnosis needs a bounded reproduction on the pinned B2 source or equivalent immutable evidence. Flakiness needs observed nondeterminism. One evidence-driven retry/reproduction maximum unless expressly approved; never silently rerun until green.

### Phase P5 — audit, provenance, commit and push

1. Verify only the four explicitly allowed tracked paths changed from START_SHA. Check that `score_segment` remains a **single body**; the sibling still owns a BTreeSet; unified owns Vec; scored map, BM25 and result `Vec` unchanged. Verify B1/B2 untouched by content diff.
2. Copy this **approved plan exactly** into `docs/pr-artifacts/perf-05/PERF05B3_DETAILED_PLAN.md` and verify with `cmp` against the supplied file. This authored plan contains **no trailing whitespace**, so it must satisfy staged `git diff --cached --check`. Do not repeat the conflicting Markdown-hard-break problem from B1/B2.
3. Create `PERF05B3_EXECUTION_REPORT.md` with the exact structure in §12. Include red/green, invariant map, all commands/statuses, errors and external gates. The report must not claim timed measurements.
4. After source/test edits, rerun affected QA and full coverage. A report-only Markdown edit requires whitespace/link checks, not a fresh Rust rebuild if code/test content is unchanged.
5. Stage only the four allowed paths by explicit names, then run `git diff --cached --name-only`, `git diff --cached --check`, and `git status --porcelain=v1 --untracked-files=all`. **Staged diff must be whitespace-clean.** If the exact plan copy unexpectedly contains trailing whitespace, HARD STOP and request plan-author correction; do not choose between two contradictory requirements yourself.
6. Commit as a single bounded B3 commit, e.g. `perf(perf05b3): use ordered matched IDs in unified scorer`. Push to **existing** `dev/perf05-physical-execution-series` without force. Verify `git rev-parse HEAD` equals remote branch and PR #117 is still open/draft/unmerged.
7. Report actual terminal status. Do not initiate B4, create another PR, merge, release, run a benchmark, or claim hosted RustFS CI passed when it has not.

---

## 10. Failure modes, cross-component impact, topology and non-goals

| Component/boundary | B3 production change? | Why no broader action is allowed |
| --- | --- | --- |
| `execute.rs::evaluate_lexical_with` | **YES — matched Vec and two append arms** | Only this path's matched IDs are ascending unique; result and scoring remain unchanged |
| `execute.rs::score_segment` | **YES — exact-sized iterator input only** | One scorer body used by both callers; no BM25/error/budget changes |
| `execute.rs::execute_segment_inner` | **YES — scorer argument `.iter()` only** | Its `eval_node`, BTreeSet and ledger remain intact |
| `search/unified.rs` | **NO production; tests only** | B1 eligible shortcut, returned scores/keys/heap and cursor cannot change |
| `search/score.rs` | **NO** | B2 verified live metadata and field lengths/df remain unchanged |
| `search/work.rs`, `search/typed.rs`, batch meter | **NO** | Same work/cancellation/batch charges at same boundaries |
| Segment codec, `ReaderSnapshot`, durable writer / local FsDirectory, remote RustFS | **NO** | No persistent version, cache, adapter or publication changes; existing real-boundary suites provide regression evidence |
| Top-K, duplicate prefilter, sort, projection and exact counts | **NO** | Still operate on scored vector and validate every candidate |
| Benchmark and profiling framework | **NO** | PERF-05-C owns all performance acquisitions |

**No new state machine, transaction, retry identity or persistence protocol:** B3 is query-local and read-only. A retry after cancellation creates a new vector and uses the same immutable snapshot; any failure leaves no persistent partial state. Existing cached/remote committed data is never mutated by this change. Index-format compatibility is therefore unchanged; no rebuild or migration is needed.

**Absolute STOP boundary:** A requirement to change `eval_node`, scoring order, `build_leaf_data`, public contracts, actual budget ceilings, or storage/reader I/O means the proposed B3 design is not sufficient. Return an evidence-backed STOP and request a revised detailed plan. The coding agent has no authority to expand B3 into B4.

---

## 11. Reviewer checklist and B3 stage acceptance

- [ ] Source proof verified on actual pulled B2 descendant: ascending and unique eligible postings and fallback live enumeration; exactly two scorer callers.
- [ ] Only unified matched-ID `BTreeSet` was replaced with a `Vec<u64>`; sibling `eval_node` and `ReservedSet` remained BTreeSet.
- [ ] Same `score_segment` body accepts exact-sized iterators; no new trait/enum/scorer copy, heap or dispatch.
- [ ] No extra `sort`, `dedup`, copy, O(M) temporary or per-match budget preflight was introduced.
- [ ] B3-U01 red-first failed **only** due to prior scorer input type; green passes with both BTreeSet and Vec iterators.
- [ ] B3-U02 uses actual decoded postings and `golden_norms.seg` and produces bit-exact BM25 equality.
- [ ] B3-U03 plus original B1/B2, budget, phrase/Boolean/typed, cursor, mutation, sparse/large and multi-segment tests execute and pass.
- [ ] `SET_BYTES_PER_ENTRY=48`, `SCORED_MAP_BYTES_PER_ENTRY=64`, the charge site, peak lifetime, RAII drop/release sites and work/cancellation polling remain unchanged.
- [ ] Stable and 1.85.0 MSRV default/all-features tests, Clippy, fmt, docs, compile-only benches and scripts pass on final code.
- [ ] Actual workspace-wide production Rust coverage ≥85% and new-code coverage reviewed.
- [ ] Real local FsDirectory writer/commit/reopen/query path executed and passed; pinned RustFS either actually executed or accurately marked BLOCKED/PENDING.
- [ ] No selected/unselected corrupt data, low-hit guard, exact count, sort tie, returned score bit, duplicate, aggregation/batch, cursor/PIT or reader-snapshot semantics altered.
- [ ] Only four allowed paths changed; no new dependencies, benchmark configs, CI edits, format or public APIs.
- [ ] Plan copied byte-for-byte; staged whitespace check clean; report actual evidence and no performance claims.
- [ ] PR #117 remains the only branch/PR, open and unmerged; B4 and PERF-05-C not started.

**Implementation PASS:** One scorer iterator seam, two call-site adaptations, two tree inserts replaced by ordered appends, correct tests and scope. **Correctness PASS:** all new/adversarial/local QA requirements passed, including 85% measured workspace coverage and invariant traceability. **External acceptance:** hosted CI and real RustFS gates actually ran and passed; if not, mark pending without blocking authorized B3 source progress. **Performance acceptance:** **NOT APPLICABLE** in B3; deferred to PERF-05-C. **Entire PERF-05 series:** not done, not merged.

---

## 12. Required execution report and PR note

Create `docs/pr-artifacts/perf-05/PERF05B3_EXECUTION_REPORT.md` using the exact headings:

```text
PERF-05-B3 EXECUTION REPORT
REPO / BRANCH / PR
START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA
IMPLEMENTED_FILES: 4-path exact allowlist
SOURCE_PROOF_CHECKS S01–S13 / INVARIANTS I01–I16
TESTS_FIRST RED: exact command and expected E0308 vs actual compiler diagnostic
PRODUCTION_CHANGE: scorer iterator, sibling iterator, matched Vec and two appends
GREEN + FOCUSED_TESTS: names and counts
REGRESSION_QA: actual command | toolchain/topology | PASS/FAIL/BLOCKED | evidence
WORKSPACE_COVERAGE: measured line percentage and tool/version
REAL_LOCAL_FS / RUSTFS / CI: topology, actual evidence or PENDING
EXCEPTION_MATRIX_ROWS: ID / trigger / actual action / evidence
OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION
NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE
B3_DISPOSITION and reasons
NEXT=independent review; B4 NOT STARTED
```

A report stored in the same commit cannot contain that commit's own SHA. Write `FINAL_SHA` as a command-derived value in the terminal report or use clear instructions to retrieve it (`git rev-parse HEAD`) rather than inventing a self-referential hash in committed Markdown. Verify remote separately after push.

**Suggested PR #117 progress note** (append to the existing PR, do not create another):

> PERF-05-B3: Unified matching now uses one ordered `Vec<u64>` instead of a per-match BTreeSet. The sibling evaluator still uses the existing BTreeSet and both call one unchanged scorer with exact-sized iterators. Matched-set logical accounting, full-M BM25, scored map and candidate output remain unchanged. See execution report for actual QA, CI/RustFS and no-benchmark status. B4/C not started.

**Review handoff, not stage automatic closure:** B3 can be `B3_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING` after passing local gates and accurately disclosing external pending status. An independent reviewer must review source and tests before B4 planning; no performance experiment is required during B3.

---

## 13. Mandatory decision/evidence discipline and continuous execution

1. Classify each encountered situation using §14 **before pausing**. If a concrete AUTO-RESOLVE rule applies and its source preconditions hold, take that action and continue automatically; do not ask for confirmation.
2. For DEFER AND CONTINUE, mark only the dependent acceptance gate BLOCKED/PENDING and finish every other safe authorized task, including report and push when source correctness is established.
3. For HARD STOP, halt the affected implementation and report exact source line, branch SHA, failing invariant and the smallest maintainer decision required. Continue only independent and safe evidence/reporting, not an alternative optimization.
4. Do not infer that an unclassified code-design problem is a minor typo. Do not change tests or thresholds to create a green result; an unlisted situation is a HARD STOP.
5. All implementation decisions needed for B3 are in §4 and §6. The agent may perform deterministic formatting and literal test insertion but may not select a new representation/scorer algorithm or alter B1/B2.
6. Failed mandatory tests must be assigned one of: introduced regression, B3 feature defect, deterministic pre-existing failure (proven on baseline), nondeterministic/flaky failure (observed nondeterminism), environment/harness failure. “Unrelated” is not a category; one bounded evidence-driven retry is permitted only under D15.
7. Do not confuse test code existing with that test executing, test passing in a required topology, hosted CI green, or performance acceptance. Document each separately.
8. Host is assumed idle; no host check and **no timing/profiling** is necessary or authorized in B3.

---

## 14. Preauthorized architectural decisions and exception-handling matrix

**Priority:** repository correctness and scope boundaries > HARD STOP > DEFER AND CONTINUE > AUTO-RESOLVE. If multiple rows match, choose the most restrictive. **Every used row must be reported** with source observation, rule, action, evidence and remaining gate. Maintainer of PR #117 owns any new architecture, contract or acceptance waiver. An event without an exact matching rule is a **HARD STOP on affected work**; no improvised alternative.

| ID | Observable trigger / source check | Category | Preauthorized action / fallback | Explicit prohibition | Evidence / affected gate & escalation |
| --- | --- | --- | --- | --- | --- |
| D01 | Wrong branch, unexpected tracked changes, index conflict, pull non-FF, missing B2 ancestor or source proof S01–S13 materially different | **HARD STOP** | Preserve status/SHAs/diff and stop code edit | Reset, stash, cherry-pick, force push, rebase, overwrite peer work | Preflight blocked; PR maintainer |
| D02 | Only previously documented generated untracked `.coverage`, `benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**` exists, with no tracked changes | **AUTO-RESOLVE** | Preserve untouched; use explicit-path stage commands; proceed | Delete/hide/untrack other files or edit `.git/info/exclude` | Record paths and P0 disposition |
| D03 | B2 is ancestor and only B1/B2 source changes exist beyond inspected main; CI still pending | **AUTO-RESOLVE** | Continue as instructed without waiting for CI; record pending | Assume CI PASSED, merge main or start new PR | Stage dependency provenance |
| D04 | `score_segment` has exactly two call sites and uses its matched input only for len + map-seeding iteration | **AUTO-RESOLVE** | Apply §4.1 exact seam and `.iter()` calls | Add custom trait, boxed iterator, clone or second scorer | S05/S06/S10; build acceptance |
| D05 | B3-U01 test-only helper produces compiler RED only from old `score_segment` needing `&BTreeSet`, no other diagnostics | **AUTO-RESOLVE** | Record expected RED; implement §4.1 then continue | Change test expected outputs or weaken assertions | Red-first gate |
| D06 | Test-first compilation fails for missing imports/API not specified, or scores fail before production change | **HARD STOP** | Preserve compiler output / fixture and request corrected plan | Invent test infrastructure or substitute mock scorer | Test validity |
| D07 | Both unified enumerators proved ascending unique; B1/B2 and callback unchanged | **AUTO-RESOLVE** | Replace only matched declaration and two inserts per §4.2 | Sort/dedup, preallocate N, move budget charge or skip callback | S01–S04, I01–I03 |
| D08 | Nonmonotone or repeated matching ID appears in a real execution fixture, debug assertion fails | **HARD STOP** | Record minimum fixture, physical doc IDs and source; stop | Sort/dedup to conceal it, remove assertion, skip bad posting | I01/I02 safety |
| D09 | Scorer input requires membership/contains/random access, or a third caller needs another type | **HARD STOP** | Record exact use/caller; request design amendment | New scorer, trait, special-case branch or duplicated map | I04/I11, source proof invalid |
| D10 | B3-U01 green, B3-U02 score bits/charges or B3-U03 result differ | **HARD STOP** | Capture first divergence and typed outcome | Change scorer order, BMP25 formula, fixture expected values, suppress test | I05/I06/I07 |
| D11 | Logical matched/scored budget charge, time of reserve/release, `SET_BYTES_PER_ENTRY` or ledger ownership differs | **HARD STOP** | Preserve audit and failing bound; request maintainer decision | Lower modeled charge because Vec is smaller; change cap/ledger | I07/I08/I14 |
| D12 | Cancellation, corruption/error precedence, total hits or score bits differ from production fixtures | **HARD STOP** | Record typed error and reproducer; stop affected implementation | Skip validations, early stop K, change poll or charge | I06/I09/I10 |
| D13 | A rustfmt wrap or trivial unused local test import confined to authorized changed lines | **AUTO-RESOLVE** | Apply deterministic compiler/rustfmt correction, rerun affected gates | Refactor unrelated modules, alter algorithms or suppress lint | QA source check |
| D14 | Exact approved plan file copied with whitespace-clean source and staged diff clean | **AUTO-RESOLVE** | Keep verbatim file, complete stage and push | Add Markdown hard breaks trailing spaces or change plan content | Doc traceability |
| D15 | Mandatory command fails with possible existing/environment issue and unaffected work remains | **DEFER AND CONTINUE** | Classify evidence; at most one bounded clean-baseline reproduction if safe; perform independent checks; keep gate blocked | Call failures “unrelated”, unlimited reruns, edit scope to hide defect | QA reviewer/maintainer |
| D16 | Local RustFS unavailable or GitHub CI still pending, while local source correctness and QA passed | **DEFER AND CONTINUE** | Record `RUSTFS_LOCAL_BLOCKED` / `CI_PENDING`; proceed to truthful report and push | Claim real remote PASS, wait indefinitely or dispatch redundant CI | External acceptance pending |
| D17 | Stable/MSRV/coverage tool absent and safe standard setup unavailable | **DEFER AND CONTINUE** | Record exact missing command and results; complete independent work | Lower 85% floor, substitute different tool and call it equivalent | Local gate blocked |
| D18 | Any extra production code path/file, codec, scorer, work meter, Index/ReaderSnapshot, RustFS, or benchmark config needs modification | **HARD STOP** | Record missing contract and request a new design | Broaden allowlist, change public API, add feature flag or new executor | Scope blocked |
| D19 | Standard Vec growth, one original matched logical reservation and zero preallocation established on source | **AUTO-RESOLVE** | Keep plain `Vec::new()`/`push`, no extra reallocation algorithm | Add `try_reserve` per match, sort, dedup or compare physical RSS and change modeled cap | Representation contract |
| D20 | B1 or B2 source regression, membership test witness changes or B2 count/poll tests fail | **HARD STOP** | Save failing test and exact source; stop B3 edits | Edit B1/B2 implementation to “fix” B3 | Prerequisite source integrity |
| D21 | Need to execute a performance benchmark, sample CPU, profile, or check host idleness | **AUTO-RESOLVE** | Do not execute; continue correctness QA; defer to PERF-05-C | `quervant-bench run`, `perf record`, timing loops or hardware probes | No-acquisition contract |
| D22 | Other newer commits on shared branch are clearly doc-only and do not touch S01–S13 or stage test surfaces | **AUTO-RESOLVE** | Record their SHAs, verify no source delta, continue on their descendant without rebase | Ignore unexplained production code, overwrite new work | Reconciliation evidence |
| D23 | Remote branch advanced during execution or push is rejected non-FF | **HARD STOP** | Preserve local commit and compare remote/local SHA, request reconciliation | Force push, automatic merge/rebase or rewrite another commit | Branch integrity |
| D24 | Local mandatory gates truly pass; CI/RustFS pending; scope and staged whitespace clean | **AUTO-RESOLVE** | Commit/push four allowed files and report `B3_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING` | Mark full PERF-05 done, merge PR, start B4 | Stage-local completion |
| D25 | Approved plan copy unexpectedly has trailing whitespace / staged diff conflicts with exact `cmp` requirement | **HARD STOP** | Preserve evidence; request corrected **plan** from author | Edit approved plan silently or waive diff check | Documentation gate |
| D26 | New/unlisted condition, competing decisions, or unresolved safety/ownership assumption | **HARD STOP** | Stop affected work; report minimal decision and safe independent tasks | Improvise algorithm, weaken semantics, expand scope | Maintainer approval required |

**Mandatory rule:** The decision matrix permits **only** literal preauthorized actions, never changes to correctness contracts. HARD STOP applies to affected source paths; preserve existing branch/user data and finish unrelated report steps only if safe.

---

## 15. Terminal instruction to coding agent

Execute the approved B3 plan autonomously from clean preflight to one bounded pushed commit on **existing PR #117**, preserving source-verified B1/B2. The sole performance-oriented change is the unified matched-ID representation (`BTreeSet` → sorted append-only `Vec`), with the single shared scorer accepting an exact-sized iterator from either the original sibling tree or new vector. Implement the literal production edits and deterministic tests, run all mandatory local QA, report any missing RustFS/CI gate honestly, and **run no benchmark or profile**. If a condition does not exactly match the §14 matrix, **STOP rather than redesign**. Do not launch B4 or finalize PERF-05-C.
