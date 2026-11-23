# PERF-05-B5 — Reuse the Fully Validated Strict-Term Posting Buffer by Ownership Handoff

**Detailed, bounded coding-agent implementation contract**
**Plan version:** 1.0 — 2026-11-22 (America/Los_Angeles)
**Authority:** Maintainer-approved B5 feasibility decision `B5_GO_NARROW_BORROW_THEN_MOVE_HANDOFF` (see adjacent `PERF05B5_FEASIBILITY_REVIEW.md`)

| Attribute | Frozen value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Existing branch | `dev/perf05-physical-execution-series` |
| Existing PR | [#117](https://github.com/yduchesne/quervant/pull/117); **no new PR** |
| Inspected B4 HEAD / required ancestor | `3b25a76b99f699c45aa2050c4f889880a138948a` |
| Inspected `main` SHA | `9775bfca4c58a27e65ca28c1d705efad00a65ec8` |
| Implementation owner | Coding agent: code and tests only; no architecture selection |
| After B5 | Independent review; then PERF-05-C integrated correctness, uninstrumented warm A/B and separate profiling |
| Authoritative repository contracts | `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md`, `docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md` |

**Important:** This file is a plan only. The plan author inspected current GitHub source and historical documents but **did not implement or run B5 tests, benchmark or profile**. Recheck the pulled branch before any edit. Do not claim B5 is implemented or qualified because this plan exists.

## 0. Authorization, objective and mandatory boundaries

**One objective:** For the existing strictly eligible single-positive-term branch of `search/execute.rs::evaluate_lexical_with`, avoid the second M-sized `(doc_id, u64 freq)` vector/all accepted-pair copies. Borrow `TermPostings.postings` through **all** existing callbacks, then transfer that exact fully decoded/validated `Vec` allocation to the B4 scorer input using safe `std::mem::take`, **only if every callback accepted**. Preserve a deterministic B4-equivalent fallback if a test/injected callback rejects any posting.

**This is an ownership optimization, NOT a streaming optimization.** Keep the existing `build_leaf_data` eager decoder, `PostingsReader`, encoded segment format, existing unified executor, eligibility policy, BM25, scored-output vector, full-M validation and accounting. The real production B1 callback returns `true` for the strict eligible leaf, so the normal path needs no extra `(doc_id,freq)` buffer; the broader `evaluate_lexical_with` callback contract must nonetheless preserve `false` filtering, callback visibility and error behavior.

**Do not change:** `build_leaf_data` implementation/signature; `TermPostings` or `LeafData` type definitions; `LeafData::matches`; `score_segment`; `score_single_term_candidates`; `execute_segment_inner`; `visit_lexical_membership_with`; `single_term_postings_eligible`; `collect_mixed` production; the fallback traversal; B1/B2/B3/B4 budget and scoring arithmetic; `SlotMemoryScope`; any public API; `Cargo.toml`/`Cargo.lock`; any stored/postings codec, index format, cache, manifest, directory, CI, benchmark/profiler code, query planner, Top-K heap or threshold.

**No real performance acquisition:** B5 must not run `quervant-bench run`, timed A/A or A/B, `perf record`, `perf script`, CPU symbol/callgraph experiments, `cargo bench` execution, microbenchmark, or profiler preflight. PERF-05-C exclusively owns the final uninstrumented warm A/B study and separate diagnostic profiling. `cargo bench --workspace --no-run` is allowed (compile only). Assume host is idle and ready to benchmark, **but do not run benchmarks or host-idleness checks here**.

**Autonomous execution:** On receiving this approved plan, run all prescribed preflights, RED/GREEN tests, source edits, QA and push on the existing PR without requesting routine intermediate approval. Apply §13's preauthorized matrix exactly. If any unlisted condition would require design inference, apply a **HARD STOP** to dependent work and report evidence. No improvisation, no production feature flag, no speculative alternative, no skipped gate, no forced push, no merge.

## 1. Reconciled implementation state: B1–B4 and residual B5 delta

| Component | At inspected B4 head | B5 action / acceptance |
| --- | --- | --- |
| B1 membership shortcut | Implemented, source inspected; local test evidence reported | Keep; rerun unchanged tests |
| B2 verified live count, work and poll schedule | Implemented; local test evidence reported | Keep; do not move or reduce checks |
| B3 matched ID `Vec<u64>` for generic fallback | Implemented | Keep identical fallback path |
| B4 `score_single_term_candidates` and owned `Vec<(u64,f64)>` | Implemented; local QA reported; external CI/RustFS pending | Keep exactly; compare all scores/results |
| B4 `single_term_matched: Vec<(u64,u64)>` | Added for eligible accepted-pair copies | In normal all-accepted case, reuse **original** `TermPostings.postings` allocation instead |
| General false-return callback behavior | Any posting can be rejected by the callable even though production eligible callback always accepts | Preserve by copying only on the first rejection and thereafter |
| PERF-05-C | Not started | Do not execute; only name as next gate |

**Main-vs-branch:** At plan authoring `main` was `9775bfca…` and PR head `3b25a76b…`, ahead by 16, behind by 0. B5 work must be based on the **actual pulled PR branch**, not main alone. Treat B4 as source-implemented/local QA reported, **not external-gate completed**. Do not erase B4's pending RustFS/CI evidence.

## 2. Source anchors and pre-implementation proof obligations

Verify each against the freshly pulled branch and include the findings in the B5 execution report. All are evidenced at `3b25a76b…` by source inspection:

| ID | Verified source / implication |
| --- | --- |
| S01 | `unified.rs::single_term_postings_eligible` requires root `Lexical(0)`, one ordinary analyzed term, exactly one positive leaf `{0}`, no typed leaf, no aggregation, no `after`. Reuse the existing flag. |
| S02 | `unified.rs::collect_mixed` passes the flag to `execute::evaluate_lexical_with`; strict eligible callback returns `true` without needing leaf-data lookup, but is still called for **each** posting. All other shapes use `evaluate_unified`. |
| S03 | `execute.rs::build_leaf_data` completely decodes each posting, checks scanned work, validates doc IDs/liveness, charges `TERM_POSTING_BYTES`, and **then** returns `LeafData::Term { terms: Vec<TermPostings> }`. No callback has run yet. |
| S04 | `TermPostings` stores `term: String` and `postings: Vec<(u64,u64)>`; `(doc_id,freq)` is ascending-unique in doc ID and freq stays `u64`. `TermPostings` and `LeafData` must not be changed. |
| S05 | `evaluate_lexical_with` first guards the strict eligible shape (`[LeafData::Term{terms,..}]`, `terms.len()==1`, `!typed_examination`) and returns the exact existing `SearchError::CorruptIndex { detail: "single-term postings eligibility mismatch" }` on mismatch. |
| S06 | Eligible enumeration obtains B2's verified-live count, charges lexical examination once for each live doc, checks cancellation once before traversal and each candidate, invokes `is_match` exactly once per candidate. Do not change this order or count. |
| S07 | B4 stores every callback-accepted pair in a separate `single_term_matched: Vec<(u64,u64)>`; normal production eligible callback always returns `true`. That vector is **duplicated payload**, not an independent validation source. |
| S08 | After callbacks, `matched_entries` controls `M*SET_BYTES_PER_ENTRY` (48) reservation; B4 helper then reserves `M*SCORED_MAP_BYTES_PER_ENTRY` (64), computes all BM25 scores, and returns an owned scored output Vec. Keep every operation in this position. |
| S09 | The B4 helper uses only the accepted pair slice and immutable `field_id`, `term`, stats, positive owner and segment index; it does **not** need the original posting Vec after callbacks. |
| S10 | Tail drops `matched`, `single_term_matched`, `leaf_data` before releasing modeled matched, leaf and scored charges in that exact order. Moved Vec must remain alive through scoring and die before the **leaf**-charge release. |
| S11 | Generic fallback uses `matched: Vec<u64>` and `score_segment`, and sibling `execute_segment_inner` uses generic scorer. These must remain unchanged. |
| S12 | Unified consumer processes **every** scored candidate for exact total hits, logical key, sort, duplicates and Top-K; scores including losing candidates remain computed. |
| S13 | Historical PR 15G-C/D, 15H-A/A2, 15I-C rejected broad streaming, linear staging, cardinality gate or new physical executor mechanisms, including absent/rare regressions. B5 is limited to ownership handoff; no separate dispatcher, no changed generic code. |
| S14 | B4's `test_observation` witnesses remain thread-local and `#[cfg(test)]` only. B5 may add **test-only** handoff-selection witnesses, not runtime metrics. |
| S15 | The [B5 feasibility review](PERF05B5_FEASIBILITY_REVIEW.md) concludes GO only for borrowed-view-then-move, and NO-GO for a streaming reader/cursor/physical collector. Reconcile this proof before coding. |

**Hard source gate:** If any S01–S12 premise has changed, do not adapt this design; **HARD STOP**. A newer remote descendant containing only unrelated reviewed docs may proceed if the exact source anchors and all source checks remain identical. New target-source edits require a reviewed plan amendment. Do not rebase on main or open a new PR.

## 3. Frozen ownership and error-precedence contract

Original B4 eligible sequence (P = retained effective-live decoded postings, M = callbacks returning true):

```text
build_leaf_data: fully decode and validate P, reserve P*16, retain TermPostings.postings
B2 verified-live examination + charge + polls
for each posting: cancellation poll -> is_match -> if true, COPY pair to candidate Vec
reserve matched M*48
reserve scored M*64
B4 BM25 -> owned Vec<(doc_id,score)>
drop generic matched / candidate / leaf
release matched / leaf / scored logical charges
unified consumer validates all M before bounded Top-K
```

Required B5 eligible sequence:

```text
build_leaf_data: IDENTICAL full decoding, validation, P*16 charge, retained original Vec
B2 verified-live examination + charge + polls: IDENTICAL
for each original posting: IDENTICAL poll + is_match, with immutable full leaf_data visible
    true before any false: no candidate-copy allocation, record accepted doc for debug invariant
    first false: copy previously accepted prefix once into fallback Vec
    later true: append pair to fallback Vec; later false: do not append
AFTER all callbacks:
    if no false: move original Vec allocation out of TermPostings using std::mem::take
    if any false: retain fallback candidate Vec; leave original TermPostings.postings intact
reserve matched M*48 (same position, same count)
reserve scored M*64 (same position, same count)
unchanged B4 BM25 -> owned Vec<(doc_id,score)>
drop generic matched / candidate / leaf
release matched / leaf / scored logical charges (unchanged order)
unchanged unified consumer validates all M before bounded Top-K
```

**Critical proof:** No `std::mem::take`, `.clear()`, `.drain()`, `.retain()` or mutation of the leaf's posting Vec **before or during** candidate callback traversal. Every `is_match` callback, including after the first false, must receive the complete intact original leaf data. Do not call callback a second time, do not execute a second posting-decoder pass, do not append an accepted pair before its callback succeeds, and do not calculate BM25 until after both logical admissions.

**Logical vs physical accounting:** Keep `leaf_charges` at P*`TERM_POSTING_BYTES`, matched at M*48, scored at M*64. On the normal all-accepted path the physical posting Vec **moves owner** from leaf to candidate; that is not permission to release `leaf_charges` at the handoff. The buffer remains live through BM25 and is dropped with the candidate before the existing leaf-charge release. Do not reduce the conservative modeled peak or alter `SegmentCandidateLedger`, `SlotMemoryScope` or failure detail fields.

**Error precedence:** All corruption, posting-scan and work failures during `build_leaf_data` precede callback errors; B2 live/examination failures precede callback calls; each callback error precedes the matched/scored reservation and BM25; the matched limit precedes scored limit; BM25's `InvalidScore` follows both admissions; consumer key/sort/duplicate errors follow complete scoring. The additional fallback copy uses ordinary Vec allocation (as B4's prior per-accepted-copy allocation did); do not invent a new typed budget or claim physical allocator OOM is modeled.

## 4. Exact allowed files and prohibited source changes

**Only these five tracked paths may be changed/created for B5:**

1. `crates/quervant-core/src/search/execute.rs` — narrow ownership-helper and eligible selection changes; tests in its existing `budget_tests` module; strictly test-only counters in existing `test_observation`.
2. `crates/quervant-core/src/search/unified.rs` — **tests only**, within existing `#[cfg(test)] mod phase4_tests`. Zero production-code changes.
3. `docs/pr-artifacts/perf-05/PERF05B5_FEASIBILITY_REVIEW.md` — byte-identical copy of approved source feasibility report.
4. `docs/pr-artifacts/perf-05/PERF05B5_DETAILED_PLAN.md` — byte-identical copy of this plan.
5. `docs/pr-artifacts/perf-05/PERF05B5_EXECUTION_REPORT.md` — truthful evidence, test and status report created by the agent.

No new `.rs` file, Cargo dependency, test fixture binary, benchmark code, public type, core API signature, index format, persistent metadata, CI workflow, feature flag, profiler instrumentation or separate PR. No edits to `docs/TESTING.md`, `AGENTS.md`, `docs/BENCHMARKING.md`, `docs/PERF_OPTIMIZATION_ROADMAP.md`, older B-stage reports, `score.rs`, `typed.rs`, `unified_plan.rs`, `segment/**`, `index/**` or any sibling executor. Do not introduce a general `Cow`, `Arc`, `Rc`, arena, unsafe cast, `Vec::from_raw_parts`, batch cursor, block reader or WAND.

## 5. Prescriptive production design — implement exactly

### 5.1 Add one private checked ownership-transfer helper

**File:** `crates/quervant-core/src/search/execute.rs`. Insert immediately after `score_single_term_candidates` and before the `#[cfg(test)] test_observation` module. Define exactly the following logic, with rustfmt-only layout adjustments allowed:

```rust
/// Move the already decoded and validated sole term's posting Vec into the
/// strict candidate owner. Call only after every matching callback completed.
fn take_strict_one_term_postings(
    leaf_data: &mut [LeafData],
    typed_examination: bool,
) -> SearchResult<Vec<(u64, u64)>> {
    match leaf_data {
        [LeafData::Term { terms, .. }] if terms.len() == 1 && !typed_examination => {
            #[cfg(test)]
            test_observation::record_postings_move();
            Ok(std::mem::take(&mut terms[0].postings))
        }
        _ => Err(SearchError::CorruptIndex {
            detail: "single-term postings eligibility mismatch".to_owned(),
        }),
    }
}
```

Must not inspect, decode, allocate, iterate or score postings. The returned Vec must have **identical pointer, length and capacity** to the original nonempty Vec; the original field becomes `Vec::new()` while `term: String` and `field_id` remain. Preserve exact typed guard failure without mutating anything. Do not force `#[inline]` or `#[inline(never)]`.

### 5.2 Add one fixed-purpose lazy rejection-selection state

Place next to the helper in `execute.rs`:

```rust
/// Record whether an eligible caller ever rejected a decoded posting.
/// Normally the B1 callback accepts all; only a rejection needs a copied Vec.
#[derive(Default)]
struct StrictTermMatchSelection {
    saw_rejection: bool,
    copied_matches: Vec<(u64, u64)>,
}

impl StrictTermMatchSelection {
    fn observe(&mut self, postings: &[(u64, u64)], index: usize, accepted: bool) {
        if !accepted {
            if !self.saw_rejection {
                // All positions before the first rejection were accepted.
                self.copied_matches.extend_from_slice(&postings[..index]);
                self.saw_rejection = true;
            }
        } else if self.saw_rejection {
            self.copied_matches.push(postings[index]);
        }
    }

    fn finish(
        self,
        leaf_data: &mut [LeafData],
        typed_examination: bool,
    ) -> SearchResult<Vec<(u64, u64)>> {
        if self.saw_rejection {
            #[cfg(test)]
            test_observation::record_postings_rejection_fallback();
            Ok(self.copied_matches)
        } else {
            take_strict_one_term_postings(leaf_data, typed_examination)
        }
    }
}
```

**No alternative selection method authorized.** No acceptance bitmap, rejected-index list, second invocation of callbacks, early append to an all-accepted candidate Vec, cloning of all postings, `retain` mutation during callbacks, or generic iterator abstraction. The fallback's first-rejection prefix copy matches all previously accepted positions exactly; every later true appends its original `(doc_id,u64 freq)`, every later false is ignored. For zero postings, `finish` moves an empty Vec, preserving zero-charge behavior; for all-false, the fallback remains empty.

### 5.3 Change the eligible iterator in `evaluate_lexical_with` only

A. Change only the binding of `build_leaf_data` in **`evaluate_lexical_with`**, not the sibling visitor:

```rust
let (mut leaf_data, leaf_charges) = { /* existing unchanged build_leaf_data block */ };
```

B. Preserve the B3 generic `matched: Vec<u64>` and the existing declaration of `single_term_matched: Vec<(u64,u64)>`. Keep the initial eligible shape guard, B2 verified live count and `charge_lexical` statements **byte-for-byte apart from harmless rustfmt**.

C. In the eligible branch, replace **only the B4 candidate for-loop** with the following. Do not change any statement before the loop or the generic `else` traversal:

```rust
let mut selection = StrictTermMatchSelection::default();
let mut last_accepted: Option<u64> = None;
for (index, (doc_id, _freq)) in postings.iter().enumerate() {
    meter.check_cancelled()?;
    #[cfg(test)]
    test_observation::record_predicate_call();
    let accepted = is_match(*doc_id, &leaf_data, meter, memory.as_deref_mut())?;
    if accepted {
        debug_assert!(last_accepted.is_none_or(|last| last < *doc_id));
        last_accepted = Some(*doc_id);
    }
    selection.observe(postings, index, accepted);
}
// All callbacks finished while the full original leaf_data remained intact.
single_term_matched = selection.finish(&mut leaf_data, typed_examination)?;
```

**Rust borrow contract:** The immutable `postings` view and `for` iterator must have ended before `selection.finish(&mut leaf_data, ..)` takes a mutable borrow. If the compiler rejects this because of a borrow/lifetime mismatch, scope the immutable slice/loop in a nested `{ ... }` block and declare `selection` outside it. This **exact syntactic repair** is preauthorized. Do **not** add `unsafe`, `RefCell`, `Arc`, clone or an alternate type. If the scoped-borrow repair is insufficient, HARD STOP.

D. Leave the post-loop `matched_entries` selection, `matched_bytes` reserve, B4 scorer call, full generic fallback dispatch, three `drop`s, three releases, and final return **unchanged**. The moved physical Vec now resides in `single_term_matched` through score and dies at its existing `drop`.

E. Reverify `field_id`, `term` lifetime used by `score_single_term_candidates`: the `TermPostings.term` String remains in `leaf_data` after `std::mem::take`. The source scorer must not reference the emptied `postings` member. If it does due to a source change, HARD STOP.

### 5.4 Add test-only branch witnesses, no release instrumentation

In the existing `#[cfg(test)] mod test_observation` add two thread-local `Cell<usize>` counters, `POSTINGS_MOVES` and `POSTINGS_REJECTION_FALLBACKS`, with exactly these public(crate) test-only operations:

```rust
pub(crate) fn reset_postings_handoff();
pub(crate) fn postings_moves() -> usize;
pub(crate) fn postings_rejection_fallbacks() -> usize;
pub(crate) fn record_postings_move();
pub(crate) fn record_postings_rejection_fallback();
```

Implement with the same TLS `Cell` pattern as the current scorer counters, not `Atomic*`, global locks or runtime metrics. `reset_postings_handoff` resets **both** new counters only. The move helper increments the move counter exactly once when shape passes (even if zero posts). `finish` increments fallback counter exactly once when any callback returned false. No production metrics, environment variables or allocation probes.

## 6. Test-first and new deterministic acceptance tests

New tests only in `execute.rs::budget_tests` and `unified.rs::phase4_tests`; use original helpers, actual `bm25`, `SegmentReader`, real in-memory segments and actual `UnifiedSearcher`. Do not mock the algorithm or create a shadow scorer/executor.

| ID / exact Rust test name | Setup | Mandatory assertions |
| --- | --- | --- |
| **B5-U01** `b5_u01_handoff_moves_exact_vec_allocation` | In `execute.rs::budget_tests`, construct `LeafData::Term { field_id:7, terms:vec![TermPostings { term:"alpha".to_owned(), postings:vec![(0,1),(3,2),(9,4)] }] }`; record original `as_ptr`, `len`, `capacity`. Call as-yet-missing helper with `typed_examination=false` | Handoff returns exact `(doc_id,freq)` pairs, **same pointer/capacity/len**, original `postings` empty, `term` and field still present; move counter exactly 1 and fallback 0. This is the sole expected **RED-first** test. |
| **B5-U02** `b5_u02_lazy_rejection_selection_preserves_subsets` | Use an original sorted vector `[(0,1),(3,2),(7,3),(9,4)]`, and create a fresh `LeafData::Term` per case. For each bool mask `[]` on empty, `[true]` on singleton, `[true,true,true,true]`, `[true,true,false,true]`, `[false,true,false,true]`, `[false,false,false,false]`, `[true,true,true,false]`, call `StrictTermMatchSelection::observe` in exact index order, then `.finish` | Result is exactly zipped/filter expected IDs and exact u64 frequencies. All-true/empty uses move (counter 1, fallback 0, original postings emptied); any false uses fallback (move 0, fallback 1), preserves **original complete postings**, including rejected ones. Neither branch sorts or deduplicates. |
| **B5-U03** `b5_u03_strict_handoff_shape_failure_nonmutating` | Construct empty leaf slice, two leaves, `LeafData::Phrase` and one-term `LeafData::Term` with `typed_examination=true`, plus a term leaf with two term entries; store length/pointer for nonempty cases | Helper returns exact `CorruptIndex` detail `single-term postings eligibility mismatch`, no source mutation, both witness counters zero. No panic or fallback-to-generic on a falsely asserted eligibility flag. |
| **B5-U04** `phase4_b5_u04_strict_move_full_query_differential` | Reuse existing `phase4_b4_u03` real indexed corpora with 0/1/sparse/dense/all matches, relevance and explicit `doc_id ASC` sort, K=1/10/100; direct term vs wrapped `Query::And(vec![term("alpha")])` | Direct calls move **once per segment** and rejection fallback zero, single scorer once/segment, generic scorer zero, B1 membership lookups zero, callback count equals eligible decoded live postings. Wrapped query has zero move and uses generic. Exact hand-known totals, hit keys/order, `score.to_bits()`, projection and K results identical. For empty postings direct must still call move once (empty Vec). Reset witnesses before **each** query. |
| **B5-U05** `phase4_b5_u05_ineligible_never_handoffs` | Reuse `phase4_b4_u04` legal ineligible shapes including And/Or/Not, phrase, analyzed-multi, lexical+typed, valid `after` cursor; add one multi-segment and one batch request from existing phase4 fixtures | No B5 move or fallback witnesses for ineligible shapes; no B4 single-term scorer. Their existing result/oracle assertions pass. Do not assume every typed-only path calls generic scorer; only assert generic where actually used. |

**Required direct-callback negative behavior:** B5-U02 exercises the actual production selection helper, not a separately implemented reference algorithm. In addition, the existing B4/B1 callback count and cancellation regressions must pass unchanged. If a method cannot be exercised without changing a private production interface or adding an unapproved test-only dispatcher, HARD STOP and report the minimal gap; do not silently omit B5-U02 or replace it with a mock.

### RED-first command and expected outcome

1. Add only B5-U01 test (and its test module imports) calling `take_strict_one_term_postings`. Do not add helper or production changes yet.
2. Run:

```bash
cargo test -p quervant-core --lib b5_u01_handoff_moves_exact_vec_allocation -- --nocapture
```

**Expected RED:** sole relevant compile failure: undefined `take_strict_one_term_postings` (Rust E0425 or equivalent). Capture first error, then implement §5 and rerun the same test to GREEN. Other compilation/test/fixture errors in RED are **HARD STOP**, not permission to modify unrelated source or weaken assertions.

3. Add U02–U05, run all B5 tests and required regression suites. `#[cfg(test)]` handoff witnesses must not appear in a non-test production binary.

### Mandatory existing regression suites

Run these focused suites **without skipping tests or relaxing assertions**:

```bash
cargo test -p quervant-core --lib b5_ -- --nocapture
cargo test -p quervant-core --lib phase4_tests -- --nocapture
cargo test -p quervant-core --lib b4_ -- --nocapture
cargo test -p quervant-core --lib b3_ -- --nocapture
cargo test -p quervant-core --lib b2_ -- --nocapture
cargo test -p quervant-core --lib b_tests -- --nocapture
cargo test -p quervant-core --lib budget_tests -- --nocapture
cargo test -p quervant-core --lib score::tests -- --nocapture
cargo test -p quervant-core --test pr13_oracle
cargo test -p quervant-core --test pr15e_b1
cargo test -p quervant-core --test pr06_local_integration
```

Note that `b5_` tests under `unified.rs::phase4_tests` also run through `phase4_tests`; no new test-runner infrastructure is permitted. Use the existing independent `pr13_oracle` and real `FsDirectory`/reopen integration path; do not call an in-memory fake a real filesystem boundary.

### Adversarial and full-query obligations

| Invariant / fault | Required evidence |
| --- | --- |
| Missing term, zero matches and tombstoned-only term | U04 + existing phase4 empty/tombstone tests; zero matched/scored reserve unchanged |
| One posting, sparse, medium, common/all | U01/U02/U04 + phase4 B1–B4 regressions, exact IDs/scores |
| False callback after a long accepted prefix; false-first; false-last; all false | U02; no postings moved while callback-visible |
| Exact `u64` freq above 2^53 | Rerun B4-U07; move must not cast frequencies |
| `df>n`, missing stats/owner, +0.0 | Rerun B4-U06; no score-order change |
| Exact and one byte below posting/matched/scored peak | Rerun B4-U05, existing C2 whole-query and batch-budget regressions; no changed error detail |
| Cancellation before/full decode, examination, first/middle/last posting and batch scope | Existing phase4 B2 cancellation/fault suites; no added/omitted poll |
| Corrupt postings including nonwinning entries | Existing real segment corruption/oracle tests; full decoder still completes before callbacks |
| Corrupt selected and unselected sort/keys, duplicate keys, null/missing sort, tie ordering | Existing `b_tests`, `pr13_oracle`, phase4 integration; unified consumer untouched |
| Multiple segments, PIT/refresh/delete/upsert, cursor and batch | Existing phase4 and `pr15e_b1` suites; no new shape eligibility |
| Fallback Boolean, phrase, typed/JSON/geo, aggregation | U05 + existing oracle and phase4 suites; no score/helper change |

If an existing targeted suite lacks an expected negative case but adding the case would require a new source API or out-of-scope file, record the gap as **BLOCKED / DECISION REQUIRED** and do not claim the gate completed. New tests should use reusable test factories and real search behavior, not hand-rolled BM25 or work meters.

## 7. Test and acceptance matrix for new B5 invariants

| ID | Falsifiable requirement | Tests / evidence |
| --- | --- | --- |
| I01 | A normal strict request allocates **no second full-M accepted-pair Vec**; exact original Vec is moved after all callbacks | U01 pointer+capacity identity, U04 test-only move witness, inspect strict loop |
| I02 | No decoded posting is omitted; every posting validated before callbacks, including losers | Source S03; posting-corruption regressions |
| I03 | Every callback sees intact leaf data in original order; no re-call | U02 accepted/rejected cases; B1 predicate count; phase4 cancellation |
| I04 | False callbacks produce exact subset without mutating source leaf during callbacks | U02, preserved original vector and frequencies |
| I05 | Full producer eligibility/fallback policy is unchanged | U04/U05, existing B1/B4 eligible tests |
| I06 | Ascending-unique doc IDs and exact original `u64` frequencies | U01/U02; B4-U07; phase4 results |
| I07 | All-M exact BM25 and total hits, including K < M, same score bits | U04, B4-U01/U02/U06; independent oracle |
| I08 | Modeled posting P*16 + matched M*48 + scored M*64 admissions and order unchanged | Source+whole-query C2/B4-U05/batch regressions |
| I09 | Candidate/leaf physical ownership death precedes leaf charge release; no ledger leak on errors | Source tail; budget/fault/cancellation suites |
| I10 | Typed errors, `InvalidScore`, `Cancelled`, `CorruptIndex`, `ResourceLimit` and precedence unchanged | U03, B2/B4 and fault regressions |
| I11 | Generic scorer, sibling executor, unified consumer, cursor/PIT and batch unaffected | Zero production diff in `unified.rs`, U05, `b_tests`, `pr13_oracle` |
| I12 | Test witnesses compile only under `#[cfg(test)]` | Source inspection and `cargo bench --no-run` compile |
| I13 | Full workspace stable/MSRV and >=85% production line coverage | §10 commands and evidence |
| I14 | No timed benchmark, profiler, source-codegen experiments or C implementation under B5 | Scope audit and agent report |

## 8. Readiness/ownership/transaction/failure scope

- **Query-local ownership only.** `TermPostings.postings` remains owned by `leaf_data` through all callbacks. On all true, `std::mem::take` transfers allocation to `single_term_matched`; there is no cross-query cache, persistent state, locking or external I/O handoff.
- **Snapshot and durability:** Search is read-only. Index/segment identities, schema/analyzer versions, immutable committed generations, cache/object-store interfaces, PIT views and local/RustFS durability semantics are unchanged. No migration, version bump or retry behavior is introduced.
- **Atomic reservations:** Preserve existing `SegmentCandidateLedger` transitions, `BatchMemoryMeter` and `SlotMemoryScope` behavior. Do not change cap values, accounting labels, exact-limit outcomes, failure precedence or `Drop` cleanup. The physical move does not transfer or release any ledger byte.
- **Positive and negative failures:** Decoder corruption precedes callbacks; callback error precedes matching/scoring reserves; matched/scored `ResourceLimit` precedes BM25; invalid score precedes selected/unselected key and sort checks. A mismatch in strict shape remains exact typed `CorruptIndex`. Do not normalize errors or introduce a special accepted-only `Ok` that skips work.
- **No idempotency change:** Repeated read-only queries do not mutate segments or manifests. Every invocation constructs new query-local data. No callbacks are replayed during B5.
- **Memory safety:** Only safe Rust `std::mem::take`; retain source term String, Field ID and B4 score helper borrowing. No `unsafe`, transmute, raw-pointer ownership or `Vec<(u64,u64)>` → `Vec<(u64,f64)>` reinterpretation.

## 9. Sequential implementation protocol

### P0. Required clean, fresh branch preflight **before edits**

Execute at repo root, preserving stdout/stderr and SHA evidence:

```bash
set -euo pipefail
git branch --show-current
git status --porcelain=v1 --untracked-files=all
git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor 3b25a76b99f699c45aa2050c4f889880a138948a HEAD
rg -n 'fn take_strict_one_term_postings|struct StrictTermMatchSelection|fn score_single_term_candidates|fn evaluate_lexical_with|fn build_leaf_data|TERM_POSTING_BYTES|SCORED_MAP_BYTES_PER_ENTRY|SET_BYTES_PER_ENTRY' crates/quervant-core/src/search/execute.rs
rg -n 'fn single_term_postings_eligible|postings_candidate_eligible' crates/quervant-core/src/search/unified.rs
rg -n 'fn bm25|fn compute_stats' crates/quervant-core/src/search/score.rs
rustc --version
cargo --version
rustup toolchain list
START_SHA=$(git rev-parse HEAD)
printf 'PERF05B5_START_SHA=%s\n' "$START_SHA"
```

**Expected:** PR head equals inspected B4 SHA (or a clearly reviewed descendant with identical target source); no B5 helper already exists; B4 implementation and tests present; B1/B2/B3/B4 commits ancestors, branch fast-forwarded and clean. Record main SHA but **do not rebase**. Generated untracked `.coverage`, `benchmark-results/`, `benchmarks/quervant_bench.egg-info/` may remain only if locally excluded in the established B4 manner; do not delete, stage or modify exclude rules. Unexpected tracked changes, unknown untracked source, divergence, changed target code or new B5 work: **HARD STOP**.

### P1. Mandatory source and correctness preflight

Inspect and log S01–S15, exact initial eligibility shape, B4 `score_single_term_candidates` signature and score input, full `build_leaf_data` decode/validation order, callback's full-leaf borrow, matched/scored ledger admissions, `drop`/release tail, and generic caller count. Confirm all I01–I14 are testable with current crate APIs. Confirm historical differences from 15G-C/D, 15H-A/A2 and 15I-C in the feasibility report. If any premise is not verified, **HARD STOP** rather than design a workaround.

### P2. RED-first test

Copy both approved documents to exact repository paths listed in §4 (byte-identical; do not rewrite them). Add B5-U01 to existing `budget_tests`, run RED command from §6 and retain the sole expected undefined-helper compiler failure. An unrelated diagnostic is a HARD STOP.

### P3. Frozen code implementation

1. Add §5.1 helper (checked shape, move semantics).
2. Add §5.2 `StrictTermMatchSelection` exactly as specified.
3. Change only `let (mut leaf_data, leaf_charges)` in `evaluate_lexical_with` and its eligible loop as in §5.3; use the named nested-scope syntactic repair **only if needed**.
4. Keep generic fallback branch, scorer dispatch and all reservations/releases untouched.
5. Add §5.4 TLS witnesses.
6. Run B5-U01 GREEN; add B5-U02/U03 and U04/U05 in existing test modules. Complete mandatory focused/regression tests.

### P4. Full stable/MSRV repository QA

Run all commands and record results, without marking a failed test as passed:

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

**85% coverage:** Use the actual *workspace production line coverage* from `cargo llvm-cov`, not a selective file or one package. Do not change thresholds, exclusions, Rust flags, test runner or dependencies. Cite existing Rust/CI policy when interpreting `ignored` integration tests; an ignored RustFS test is NOT a RustFS PASS.

### P5. Required real integration topology

- **Local real `FsDirectory`:** `cargo test -p quervant-core --test pr06_local_integration`, `pr13_oracle`, `pr15e_b1` at the exact B5 source; include effective-live, scoring, selected projection and reopen paths. Unit tests also use actual segment/codec implementations.
- **RustFS:** If the project's previously configured real RustFS service and `QUERVANT_RUSTFS_*` environment are available, run the existing pinned real-service harness per current `docs/TESTING.md`; record exact command and result. If absent, set `RUSTFS_LOCAL_BLOCKED` and keep B5 external acceptance **pending**; do not provision a replacement service, call fakes RustFS, edit CI, or claim skip=pass.
- **Hosted CI:** Observe/check PR #117's exact pushed B5 SHA when accessible. If not run/completed, set `HOSTED_CI_PENDING`, do not declare CI PASS. Local complete source correctness can be independently reviewed with truthful pending external gates.

### P6. Scope audit, report, commit and push

1. Run `git diff --name-only` and `git diff --check`. Verify only §4 five paths changed, `unified.rs` production diff is **empty**, no new dependencies, no edits to `score.rs`, budget definitions, APIs, byte formats, index or bench files. Verify the feasibility and plan copies byte-identical to the provided files (`cmp`), and no trailing whitespace introduced.
2. Create `PERF05B5_EXECUTION_REPORT.md` with exact START/MAIN/FINAL/REMOTE_VERIFIED SHAs (file cannot embed SHA of its containing commit), S01–S15 proof, I01–I14 test mapping, RED/first error and GREEN, test outcomes and counts, coverage, real Fs/RustFS and CI status, all encountered decision-matrix rows, residual risks and no-benchmark/no-profiling affirmations.
3. Stage **only** the five allowed files using explicit paths; commit once with message `perf(perf05b5): reuse validated single-term postings allocation`. Never `git add -A` if unrelated files exist. Push normally (no force) to the same PR branch:

```bash
git push origin HEAD:dev/perf05-physical-execution-series
git rev-parse HEAD
git ls-remote origin refs/heads/dev/perf05-physical-execution-series
git status --porcelain=v1 --untracked-files=all
```

4. Require local HEAD equals remote verified SHA, clean tracked tree, PR #117 open and unmerged. Preserve its existing draft state; **do not change draft/non-draft state**, rebase, merge, open a successor PR or start PERF-05-C.

**Allowed terminal disposition:** `B5_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING` when required local gates all pass but hosted/RustFS remain pending; `B5_READY_FOR_INDEPENDENT_REVIEW` only when stated gates are truly met; otherwise `B5_HARD_STOP_<CAUSE>` or `B5_BLOCKED_<GATE>` with exact evidence. Never declare B5/perf improvements `ACCEPTED` without PERF-05-C.

## 10. Mandatory independent acceptance and reviewer checklist

Before approval to move to PERF-05-C, independently verify:

- [ ] Exact PR head, main ancestor, no unreviewed target-source divergence.
- [ ] B5 feasibility decision is **narrow move**; no new streaming decoder, physical executor, cursor, feature flag or codegen experiment.
- [ ] Full eager posting decoding/validation precedes all callbacks; all original leaf data remains available until final callback.
- [ ] Normal strict call **moves** the exact `Vec<(u64,u64)>` allocation (pointer and capacity test); does not allocate/copy a second full-M accepted Vec.
- [ ] Rejection fallback handles false-first, false-last, some-false, all-false, plus empty; full leaf remains intact for all callback invocations.
- [ ] Zero, sparse, medium, high-hit, multi-segment and K < M results have exact totals, score bits, sort, projection and key behavior against independently chosen oracle.
- [ ] No changed `build_leaf_data`, BM25, generic scorer, eligibility, unified consumer, byte formats, work/poll counts or logical ledger transitions.
- [ ] Error precedence, cancellation, decoded nonwinner corruption, selected/unselected sort failures and whole-query exact/one-under resource caps hold.
- [ ] Every mandatory focused test, stable/MSRV full test, Clippy, fmt, docs, workspace production line coverage >=85% and real FsDirectory integrations executed and passed; blocked RustFS/CI reported honestly.
- [ ] Only allowed five paths changed; `unified.rs` production untouched; no dependencies, `unsafe`, bench/profiler code or new PR.
- [ ] No performance claim, A/A, A/B, profiler capture, metric retuning or C work during B5.

**Reviewer classifications:** `PASS` when implementation and required local correctness/source evidence conform; `FIXUP` for a bounded correctable implementation defect with a separate precise fixup plan; `STOP` for changed architecture, violated invariant, tests not passable without redesign or unapproved scope. External CI/RustFS can remain an explicit pending gate, not falsely claimed PASS.

## 11. Failure taxonomy and evidence protocol

Classify every failure before invoking recovery:

| Failure class | Evidence | Permitted response |
| --- | --- | --- |
| Introduced failure | Exact failing new/modified test or source path | Narrow correction **within frozen design and allowlist**, then rerun dependent gates; do not change invariant |
| Pre-existing failure | Independent reproducible evidence on the exact pinned B4 source or unchanged main | Report exact source/control and block affected gate; no automatic waiver |
| Flaky/unstable | Multiple independent, reproducible observations showing environment instability; not an unsupported assertion | Report and STOP affected gate; no threshold change or infinite retry |
| Harness/tool failure | Exact command, version, stack/exit status and cause | Fix only a purely local command/invocation typo within §13 rules; otherwise STOP |
| Environment-gated RustFS/CI | Missing required service credentials, remote job unavailable/pending | `DEFER AND CONTINUE` for truly independent work; gate remains BLOCKED/PENDING |

A single failure is not proof of flakiness or of a pre-existing defect. Never rewrite test oracles to make a test pass, lower coverage, skip the test, alter CI or silently omit error-precedence checks.

## 12. Historical non-repetition and source novelty obligation

Before coding, cite the adjacent feasibility review, plus actual repository historical documents:

- PR 15G-C: fused streaming collector changed per-match processing and Top-K, rejected with 100K common K100/K10 regressions; B5 does **not** reproduce it.
- PR 15G-D: rejected D2 isolated streaming/two-pass, including rare regression; B5 stays with the current one full decode and no re-read.
- PR 15H-A/A2: new linear staging and cardinality gate regressed absent/rare; B5 only changes **ownership of the already-existing B4 vector** and adds no cardinality gate.
- PR 15I-C: separate physical executor and generic-boundary instrumentation regressed absent/rare even when fast collector disabled; B5 adds no physical dispatcher or runtime flag. A compiler-layout/sparse-lane regression cannot be ruled out by source, so PERF-05-C must test it.

**Decision rule:** The conditional B5 source novelty is the post-callback safe move of the *already fully validated original* `Vec`, not a direct-disk streaming replacement. If implementation requires any of the retired mechanisms or changes early error ordering, B5 becomes **NO-GO / HARD STOP**, and PERF-05-C can proceed with B1–B4 once the maintainer reviews the STOP. The coding agent is not authorized to choose a replacement architecture.

## 13. Preauthorized Architectural Decisions and Exception-Handling Matrix

Evaluate before acting. Each row includes observable trigger, category, exact action, prohibition, evidence and gate/owner. More restrictive classification wins when rows overlap; an unexpected situation is `DEFER AND CONTINUE` only if other work is demonstrably independent, otherwise `HARD STOP`.

| ID | Observable trigger | Category | Authorized action | Prohibited action | Evidence, affected gate and escalation |
| --- | --- | --- | --- | --- | --- |
| D01 | PR head exactly `3b25a76b…`, B4 source anchors unchanged and clean | AUTO-RESOLVE | Execute B5 stages sequentially | Skip source verification | SHA/source report; B5 preflight; agent |
| D02 | Remote is descendant with changes only to unrelated **reviewed documents**, target source/source invariants identical | AUTO-RESOLVE | Proceed, record intervening SHAs and source diff | Rebase or adapt changed target source | PR/compare evidence; preflight; agent |
| D03 | Target source changed, helper already exists or branch diverged | HARD STOP | Halt code work and report exact diff | Reimplement, overwrite or force-push | Source/ancestor evidence; maintainer |
| D04 | Known pre-existing generated `.coverage`/`benchmark-results`/`egg-info` paths locally excluded; no new tracked/unknown sources | AUTO-RESOLVE | Preserve untouched, stage only allowed files | `git clean`, change `.gitignore` or local exclude | status evidence; agent |
| D05 | Unexpected dirty tracked/untracked source | HARD STOP | Preserve state and report paths | Clean/reset/stash/delete | working tree; maintainer |
| D06 | B5-U01 compile RED solely E0425 missing helper | AUTO-RESOLVE | Add frozen helper and run GREEN | Treat other errors as expected RED | first error + command; test gate; agent |
| D07 | RED has unrelated error/missing fixture | HARD STOP | Halt implementation and report compiler stderr | Change expected RED arbitrarily | test gate; maintainer |
| D08 | Rust immutable borrow of postings overlaps required mutable handoff | AUTO-RESOLVE | Put borrow+loop in nested scope; call `.finish` after scope ends | `unsafe`, clone, RefCell, change API | rustc E0502/E0505 + minimal diff; source gate; agent |
| D09 | Scoped-borrow repair D08 insufficient | HARD STOP | Preserve diagnostic and halt | Redesign ownership/callback | source proof; maintainer |
| D10 | Normal production eligible callback remains all-true and original leaf intact | AUTO-RESOLVE | Use `std::mem::take` exact Vec once after callbacks | Pre-callback move, direct stream, extra decode | U01/U04+witness; agent |
| D11 | Any callback returns false in synthetic/test caller | AUTO-RESOLVE | Use exact first-rejection prefix copy + subsequent true appends; original leaf unchanged | Call callback again, treat false as corruption | U02; agent |
| D12 | Shape mismatch or typed examination asserted eligible | AUTO-RESOLVE | Return exact old `CorruptIndex` without mutation | Silently fallback or bypass guard | U03; agent |
| D13 | BM25/ledger release/charge/poll order differs or callback sees incomplete leaf | HARD STOP | Halt and report first broken invariant | Move score earlier or weaken contracts | I02/I03/I07–I10; maintainer |
| D14 | Existing B4 score helper now consumes original postings after callbacks | HARD STOP | Halt; plan not source-compatible | Clone/postpone scoring to compensate | source diff; maintainer |
| D15 | New unit test fails due to a narrow implementation mistake with frozen algorithm | AUTO-RESOLVE | Correct only B5 code/test setup to frozen spec and rerun all impacted gates | Change expected results or tests' semantic assertion | failure/test evidence; agent |
| D16 | Existing non-B5 regression fails | DEFER AND CONTINUE | Independently reproduce and classify; complete unaffected tasks | Call it flaky/pre-existing without proof | full command/log; affected QA BLOCKED; maintainer |
| D17 | Exact budget or cancellation/error precedence changes | HARD STOP | Halt, preserve trace and SHA | Redefine budget or remove guard | mandatory correctness gate; maintainer |
| D18 | Existing real local `FsDirectory` harness passes | AUTO-RESOLVE | Record command/real topology | Call fake a real-service acceptance | local integration; agent |
| D19 | No pinned real RustFS service/env available | DEFER AND CONTINUE | Report `RUSTFS_LOCAL_BLOCKED`; finish independent local gates | Spin up unapproved service or claim skip=pass | external acceptance; maintainer |
| D20 | Hosted CI pending/not accessible | DEFER AND CONTINUE | Record exact SHA + `HOSTED_CI_PENDING`, push if local QA passes | Declare CI PASS | hosted gate; maintainer |
| D21 | Stable/MSRV tools absent or fail outside the allowed compile-borrow repair | DEFER AND CONTINUE | Record tool/version/failure and complete safe independent checks | Install unapproved tool, suppress warnings or change MSRV | QA BLOCKED; maintainer |
| D22 | Unit or integration assertions would need weakening, score changes, `unsafe`, extra full-M buffer, new cursor/dispatcher | HARD STOP | Abort B5 code path; report exact dependency | Improvise alternative | architecture gate; maintainer |
| D23 | Unexpected unlisted condition has independent safe work | DEFER AND CONTINUE | Document precise condition, alternatives, dependent tasks; continue only independent work | Implement unresolved choice | maintainer decision required |
| D24 | Unexpected condition prevents correctness or independent progress | HARD STOP | Stop affected work and preserve evidence | Guess or bypass | maintainer decision required |
| D25 | `cargo bench --workspace --no-run` compiles; no real samples acquired | AUTO-RESOLVE | Record compile-only QA success | Execute timed bench/profiler | QA/no-bench proof; agent |
| D26 | Non-fast-forward push or remote changes after tested HEAD | HARD STOP | Keep local commit; report local and remote SHA | Force push, rebase or silently retry | remote provenance; maintainer |
| D27 | PR externally changed draft state but head unchanged | AUTO-RESOLVE | Leave metadata untouched; report observed state | Toggle draft state | PR metadata; agent |

**Agent response on STOP:** Name the row, exact source path/symbol/line, observed failure/command, first divergent behavior, why frozen design cannot continue, smallest human decision required, work safely completed and files/commits already present. **No alternate implementation** unless a human approves an amended plan.

## 14. Suggested PR description (same PR #117, B5 commit only)

> **PERF-05-B5 — validated posting-buffer ownership reuse**
>
> The strict single-positive-term unified path now keeps the fully decoded/validated `TermPostings` slice available through every existing matching callback, then moves the original pair-vector allocation into the B4 candidate scorer when all callbacks accept. Injected callback rejection uses a bounded lazy-copy fallback preserving the original leaf. This removes the normal eligible path's second full-M `(doc_id,freq)` allocation/copy without changing BM25, full validation, score/error/resource accounting, Top-K selection, stored/index formats or generic execution. Full stable/MSRV QA, focused negative tests and local real filesystem integration are documented in `PERF05B5_EXECUTION_REPORT.md`; RustFS and hosted CI gates must be reported truthfully. No benchmark/profiling result or performance acceptance is claimed; PERF-05-C owns the consolidated warm A/B and separate diagnostic profiling.

## 15. Completion and successor boundary

**B5 completion for independent review** requires the approved handoff code, falsifiable unit+full-query evidence, all named local regression and full workspace QA commands executed and passed, coverage >=85%, real local boundary evidence, immutable documents plus execution report, allowlist-only clean commit, and remote-verification on the **same PR #117**. CI/RustFS gaps remain separately visible and cannot be laundered into PASS. Nothing in B5 is a performance qualification.

**Only after independent B5 review** may the maintainer authorize PERF-05-C. C owns *one* final correctness/QA plus qualified, uninstrumented warm A/B study on the frozen 10K/100K × absent/rare/medium/common × K10/K100 matrix against the accepted baseline, as well as a separate-source-equivalent diagnostic CPU profile capture. Real warm gains and all guardrails — not code structure or profile share — determine optimization adoption. If B5 HARD STOPs, do not devise B6; return to the maintainer for the decision to omit B5 and proceed with B1–B4 into C.
