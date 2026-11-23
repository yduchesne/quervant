# PERF-05-B1 — Eliminate Redundant Single-Term Membership Re-lookup

**Detailed coding-agent execution plan — version 1.0 (2026-11-22)**  
**Project:** `yduchesne/quervant` · **Milestone:** `v0.1-perf` · **Existing series PR:** [#117](https://github.com/yduchesne/quervant/pull/117)  
**Required branch:** `dev/perf05-physical-execution-series` (never create another branch/PR for B1)  
**Inspected series HEAD at authoring:** `0bd712dee5bfbc378e7c9830e83a104997be1529`  
**Inspected accepted `main` ancestor:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8` (PERF-02-B merge)  
**Status of this plan:** Design frozen for agent handoff; **no B1 production implementation or tests are claimed to have been executed**.  
**Authoritative guidance:** [`docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`](https://github.com/yduchesne/quervant/blob/main/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md), `AGENTS.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md` and [`PERF05B_IMPLEMENTATION_REGISTER.md`](https://github.com/yduchesne/quervant/blob/dev/perf05-physical-execution-series/docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md).

---

## 0. Mandatory execution contract — READ FIRST

**One dominant correction:** A strict, validated, single-positive-term postings iterator already yields only matching effective-live document IDs. The current unified callback nevertheless invokes `evaluate_unified()` → `LeafData::matches()` → `binary_search_by_key()` on that **same** postings vector for each yielded ID. **B1 eliminates only this redundant proof of membership**; nothing else in the query engine is redesigned.

**Preauthorized design:** Change only the `is_match` callback **inside** `UnifiedSearcher::collect_mixed()`: when the *existing*, already computed `postings_candidate_eligible` is true, it returns `true` rather than invoking `evaluate_unified()`. The guarded per-segment enumeration in `evaluate_lexical_with()` stays unmodified. Its runtime shape check, validated postings, callback invocation, work/cancellation checks, matched set, BM25 scoring, vector, document-key lookup, sort handling and heap remain unchanged. Preserve creation of the existing `TypedCharge` and `ScanGuard` at the callback site. Add a **test-only** observation proving the old membership lookup is absent in the narrow path and still present in ineligible paths. **Do not add a second executor, feature flag, or callback API parameter.**

**Execution model:** Once the maintainer gives this approved plan to the coding agent for execution, carry out **all** prescribed phases continuously. Do **not** request routine reconfirmation after clean preflight, a red-first test, a green test, documentation, or a stage checkpoint. Use the finite decision matrix in §13 for any exception. `AUTO-RESOLVE` → act and continue; `DEFER AND CONTINUE` → record the blocked gate and safely finish independent tasks; `HARD STOP` → stop the affected path immediately and do not invent a fix. A genuinely missing architectural decision or unclassified threat to correctness is a HARD STOP, not permission to improvise.

**Host assumption:** The operator explicitly instructs the coding agent to **assume the host is idle and benchmark-ready**. Do not conduct host-idle probes or ask for an idle confirmation. **This is not permission to benchmark in B1.** PERF-05-B1–B5 require correctness tests and normal repository QA **only**. **Do not run any timed A/B campaign, `quervant-bench run`, `perf record`, `perf script`, CPU profiling, custom microbenchmark, or other performance acquisition.** PERF-05-C alone owns the final integrated benchmark **and** Rust-symbol-aware profiling campaign. The CI's `cargo bench --workspace --no-run` is compile-only; it is not a timed benchmark and may remain in the existing CI workflow. Do not add/change CI or benchmark scripts for B1.

**Ownership:** All work, including plan and execution report when committing, belongs on existing branch/PR **#117**; **do not merge PR #117**, mark PERF-05 complete, tag a release, rebase, force-push, change `main`, or initiate B2. Complete B1, push a bounded commit, and return the report for independent review.

---

## 1. Source-grounded facts and precise failure

These anchors were verified on the existing series branch and its accepted main ancestor before authoring; the agent **must inspect them again at execution** (§3), because file line numbers may shift.

| ID | Verified source | Existing behavior / authority |
|---|---|---|
| S01 | `crates/quervant-core/src/search/unified.rs`, `single_term_postings_eligible()` (~lines 120–142) | True **only** when compiled root is `UnifiedNode::Lexical(0)`, exactly one lexical leaf, exactly one analyzed term in `CompiledLeaf::Term`, no typed leaves, one positive lexical leaf at index zero, no aggregation, and no `after` cursor. **Does not require Keyword sort; relevance, other sorts and batch may still use postings enumeration.** |
| S02 | Same file, `collect_mixed()` (~lines 794–847) | Computes `postings_candidate_eligible` and passes it to `execute::evaluate_lexical_with()`, along with an `is_match` closure. Closure builds `TypedCharge` and `ScanGuard`, calls `evaluate_unified`, and (if matched) performs optional aggregate visitation. |
| S03 | `crates/quervant-core/src/search/execute.rs`, `evaluate_lexical_with()` (~lines 1936–2066) | In eligible branch, runtime-checks that `leaf_data` is exactly one `LeafData::Term` with one postings vector and `!typed_examination`; otherwise returns `SearchError::CorruptIndex`. Retains full-live examination charge, iterates **already validated** `(doc_id, freq)` pairs, polls cancellation, increments test-only `PREDICATE_CALLS`, calls `is_match` **once per pair**, inserts successful IDs into matched `BTreeSet`, computes scores and returns an ordered vector. |
| S04 | `execute.rs`, `build_leaf_data()` (~lines 1256–1305) and `TermPostings` (~lines 908–918) | `PostingsReader::next_with()` enforces sorted doc IDs; each decoded occurrence is resource charged, bounds-checked and filtered by effective-live bitmap; no reordering after construction. |
| S05 | `execute.rs`, `LeafData::matches()` (~lines 921–938) | `LeafData::Term` uses `binary_search_by_key(doc_id)` on each term's sorted postings. For the S01/S03 shape, this repeats an already established membership fact for **every** enumerated posting. **Do not alter this generic routine in production.** |
| S06 | `unified.rs`, `evaluate_unified()` (~lines 2129–2157) | `UnifiedNode::Lexical(index)` merely obtains the leaf and invokes `leaf.matches(doc_id)`. It does not charge work, change state, or return a typed error. Typed and Boolean branches have different semantics and must remain unchanged. |
| S07 | `search/typed.rs`, `ScanGuard::shared()` (~lines 179–185) | Constructor only stores a borrow to shared work meter. Without typed predicates, creating it performs no work charge. Preserve its construction in B1; do not adjust cancellation, aggregation or accounting. |
| S08 | `unified.rs`, existing `mod phase4_tests` (~lines 4342–4874) | Real analyzer→writer→commit→reader→`UnifiedSearcher::search` tests, `phase4_schema`, `build`, `corpus`, `term`, `req`, `search`, `min_work`, `keys`, and exact eligibility, visits, work-charge, cancellation and cursor regressions. |
| S09 | `execute.rs`, `#[cfg(test)] mod test_observation` (~lines 1781–1822) | Existing `PREDICATE_CALLS` test-only thread-local witness. Reuse the same module for the **new** test-only `TERM_MEMBERSHIP_LOOKUPS` witness; no release instrumentation. |
| S10 | `unified.rs`, existing `mod b_tests` (~lines 4877–5385) | Already compares strict one-term and `Query::And(vec![term()])` fallback for exact count, key order, score **bits**, null/ties and two segments. Reuse as regressions, do not rewrite these fixtures. |

**Source proof:** S01 ⇒ S03's runtime shape check passes or the request fails *before invoking the callback*; S04 guarantees each yielded `doc_id` occurs in precisely the S03 single positive-term postings vector; S06 `Lexical(0)` therefore returns `true`. The old `leaf.matches()` has no side effects, resource charge, cancellation checks, or fallible operation. Replacing **only that value** with `true` in this already verified context preserves the callback's execution, its remaining work, and the downstream pipeline. The proof is **not valid** for any fallback, multi-term, Boolean, typed, phrase, cursor or aggregation shape.

**Important separation:** `single_term_postings_eligible` and `keyword_sort_late_eligible` are different gates. The first governs enumeration and B1; the second only governs borrowed `Keyword` sort tuples (requires standalone and other sort restrictions). **Do not use `keyword_sort_late` as B1's guard**, and do not assume batch requests cannot use postings enumeration.

---

## 2. Current state, delta and dependencies

| Component | State at authoring | B1 treatment |
|---|---|---|
| PERF-01 duplicate-key prefilter and PR 15H-B borrowed Keyword sort | Present, production baseline | **PRESERVE**; do not change |
| PERF-02-B diagnostics and Rust demangling | Merged in `main` | **PRESERVE**; no use or update in B1 |
| `single_term_postings_eligible` + S03 per-segment guard | Present | **PRESERVE EXACTLY**, no widening |
| `LeafData::matches` generic binary search | Present and required on fallback | **PRESERVE production behavior**; add test-only counter only |
| `collect_mixed` callback | Performs redundant S06 lookup even in eligible path | **IMPLEMENT** one conditional return of `true` |
| Existing phase4 and b_tests | Already cover semantic behavior | **REUSE + ADD** targeted B1 witness tests |
| PERF-05-B2…B5 and PERF-05-C | Planned, not B1 | **DO NOT START** |

If the current branch already contains an implementation of B1, or the source proof changes, **do not replace it**. Record the delta and apply §13's stop rule; obtain an amended plan.

---

## 3. Phase 0 — repository and host preflight (NO CODE CHANGES)

Run commands **in order**, from the repository root; capture stdout/stderr and SHA values for the report. Prefer the installed Rust 1.98.1 toolchain (the CI exact stable pin) and Rust 1.85.0 MSRV. No destructive commands.

```bash
set -euo pipefail
# Confirm no local changes are at risk; do not stash, reset or discard them.
git status --short
# If nonempty: HARD STOP before checkout or pull.
git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series

git status --porcelain
# Must be empty; otherwise HARD STOP.
git rev-parse HEAD
git rev-parse origin/main
git branch --show-current
# Series branch MUST descend from the historical PERF-02-B accepted base:
git merge-base --is-ancestor 9775bfca4c58a27e65ca28c1d705efad00a65ec8 HEAD
# The accepted main and series branch MUST have identical B1 production source:
git diff --exit-code origin/main HEAD -- \
  crates/quervant-core/src/search/unified.rs \
  crates/quervant-core/src/search/execute.rs
# No B1 source edits exist on this fresh series branch.
START_SHA=$(git rev-parse HEAD)
printf 'B1_START_SHA=%s\n' "$START_SHA"

rg -n 'fn single_term_postings_eligible|fn collect_mixed|fn evaluate_unified|fn keyword_sort_late_eligible' \
  crates/quervant-core/src/search/unified.rs
rg -n 'pub\(crate\) fn evaluate_lexical_with|fn build_leaf_data|pub\(crate\) fn matches|mod test_observation' \
  crates/quervant-core/src/search/execute.rs
rustc --version
cargo --version
rustup toolchain list
```

**Allowed normal case:** `main` has advanced in unrelated files but the two production B1 files remain **byte-identical** between `origin/main` and series branch; continue. Do not rebase for this. **STOP** if either source file differs, the branch is wrong, there are local modifications, the expected functions/guards are missing, or the ref fast-forward fails. A changed `main` unrelated to these files is not permission to copy other changes into B1.

**Pre-implementation correctness gate (required):** Before writing code, record in the B1 report the S01–S10 proof, invariant IDs from §6 with tests from §7, and confirm the S03 runtime guard precedes callback invocation; S06 contains no side effects; the patch cannot bypass `total_hits`, `score_segment`, decode or work charges. If any claim is false on the checked-out source, **HARD STOP**.

**Host-idle assumption applies**; no idle/readiness verification is necessary. **No benchmark/profile commands** are to be run.

---

## 4. Exact production patch — ONLY ONE BEHAVIORAL CHANGE

**File:** `crates/quervant-core/src/search/unified.rs`  
**Function:** `UnifiedSearcher::collect_mixed()`  
**Location:** The existing closure passed as the final `is_match` parameter to `execute::evaluate_lexical_with()`, specifically its local `let matched = { ... }` block.

**Keep all existing code and ordering immediately outside this block.** Replace only the current `evaluate_unified(...)?` expression **inside** the existing guard-creation block with the following conditional. Do not change the closure signature, the function call to `evaluate_lexical_with`, eligibility calculation or runtime guard.

```rust
// Within the existing evaluate_lexical_with(...) is_match closure:
let matched = {
    let mut typed_charge = TypedCharge::new(&mut *meter);
    let mut guard = ScanGuard::shared(&mut typed_charge);
    if postings_candidate_eligible {
        // The strict root-Term eligibility and evaluate_lexical_with's
        // one-term/one-postings runtime guard prove every yielded doc_id
        // already satisfies UnifiedNode::Lexical(0).  Do not repeat the
        // same term's binary search in LeafData::matches.
        true
    } else {
        evaluate_unified(
            &plan.root,
            doc_id,
            leaf_data,
            &plan.typed_leaves,
            &columns,
            &json,
            &typed_geo,
            &mut guard,
            memory.as_deref_mut(),
        )?
    }
};
```

**After this block:** Preserve the existing `if matched { ... aggregation ... }` (even though aggregation is excluded from the eligible branch) and `Ok(matched)` **unchanged**. The `is_match` callback must still run exactly once per eligible posting. It must not be replaced with `true` in `evaluate_lexical_with` itself, because that would suppress its callback and break the meaning of its test-only predicate witness and future callers.

**Do not** refactor `evaluate_unified`, `LeafData::matches` (except test instrumentation in §5), `score_segment`, `build_leaf_data`, `effective_live_examination_count`, `keyword_sort_late_eligible`, cursor processing, `heap_admit_candidate` or `ColumnAccess`. No direct call to `doc_key`, no early Top-K stop, no additional cache/collection, no new runtime flag or configuration.

**Fail-closed safety:** The conditional is only safe because the existing eligibility value drives the *same* `evaluate_lexical_with` branch with its runtime guard. If implementation would require duplicating/replacing that guard, or extending eligibility to an unverified shape, STOP. This plan authorizes **no alternative algorithm**.

---

## 5. Test-only observability and red-first protocol

**File:** `crates/quervant-core/src/search/execute.rs`  
**Scope:** Test-only counter + no change to the production binary's membership algorithm.

### 5.1 Exact witness implementation

Inside the existing `#[cfg(test)] pub(crate) mod test_observation`, extend the `thread_local!` block with:

```rust
static TERM_MEMBERSHIP_LOOKUPS: Cell<usize> = const { Cell::new(0) };
```

In that same module, add **exactly** these methods (names are part of the B1 test contract):

```rust
pub(crate) fn reset_term_membership_lookups() {
    TERM_MEMBERSHIP_LOOKUPS.with(|value| value.set(0));
}

pub(crate) fn term_membership_lookups() -> usize {
    TERM_MEMBERSHIP_LOOKUPS.with(Cell::get)
}

pub(crate) fn record_term_membership_lookup() {
    TERM_MEMBERSHIP_LOOKUPS.with(|value| value.set(value.get() + 1));
}
```

Within the **existing** `LeafData::matches` match arm for `Self::Term { terms, .. }`, wrap its current `terms.iter().any(...)` expression in a block and invoke the witness **only** in test builds, immediately before the original expression:

```rust
Self::Term { terms, .. } => {
    #[cfg(test)]
    test_observation::record_term_membership_lookup();
    terms.iter().any(|term| {
        term.postings
            .binary_search_by_key(&doc_id, |(posting_doc_id, _)| *posting_doc_id)
            .is_ok()
    })
}
```

Leave the phrase arm, binary search itself, term iteration and all non-test logic unchanged. `#[cfg(test)]` eliminates the observation call from production/benchmark builds; this is not a performance instrument or an externally visible API. Existing `PREDICATE_CALLS` must stay exactly as it is.

### 5.2 Red-first test

Add a small test **inside the existing `#[cfg(test)] mod phase4_tests`** in `unified.rs`, using that module's `build`, `phase4_schema`, `corpus`, `term`, `req`, `search`, `keys` and `test_observation` helpers. **Do not create a new fixture framework.**

```rust
#[test]
fn phase4_b1_u01_u02_proven_term_skips_relookup_with_fallback_parity() {
    let matching = [0usize, 2, 13, 39];
    let index = build(phase4_schema(), corpus(40, &matching));
    let snapshot = index.snapshot();

    for sorted in [false, true] {
        for k in [1usize, 10] {
            let direct = req(term("alpha"), k, sorted);
            test_observation::reset_predicate_calls();
            test_observation::reset_term_membership_lookups();
            let actual = search(&snapshot, &direct, SearchLimits::default()).unwrap();
            assert_eq!(test_observation::predicate_calls(), matching.len());
            assert_eq!(test_observation::term_membership_lookups(), 0);

            let wrapped = req(Query::And(vec![term("alpha")]), k, sorted);
            test_observation::reset_predicate_calls();
            test_observation::reset_term_membership_lookups();
            let reference = search(&snapshot, &wrapped, SearchLimits::default()).unwrap();
            assert_eq!(test_observation::predicate_calls(), 40);
            assert_eq!(test_observation::term_membership_lookups(), 40);

            assert_eq!(actual.total_hits, reference.total_hits);
            assert_eq!(actual.total_hits, matching.len() as u64);
            assert_eq!(keys(&actual), keys(&reference));
            assert_eq!(actual.hits.len(), k.min(matching.len()));
            let actual_scores: Vec<u64> = actual.hits.iter()
                .map(|hit| hit.score.expect("lexical hit").to_bits()).collect();
            let reference_scores: Vec<u64> = reference.hits.iter()
                .map(|hit| hit.score.expect("lexical hit").to_bits()).collect();
            assert_eq!(actual_scores, reference_scores);
            let actual_fields: Vec<_> = actual.hits.iter().map(|hit| &hit.fields).collect();
            let reference_fields: Vec<_> = reference.hits.iter().map(|hit| &hit.fields).collect();
            assert_eq!(actual_fields, reference_fields);
            // DO NOT compare `next_cursor` bytes between distinct query ASTs:
            // it includes a query fingerprint and is intentionally different.
        }
    }
}
```

**Red-first order:**

1. Add the §5.1 **test-only** witness and the above test; do **not** apply §4 yet.
2. Run `cargo test -p quervant-core --lib phase4_b1_u01_u02 -- --nocapture`.
3. Expected **RED**: test compiles, but the eligible path reports **4** term-membership lookups rather than **0**. The fallback would still report 40; failing on an unrelated assertion, compilation, panic or environmental error is **not** an accepted RED and is a STOP under §13.
4. Apply §4's prescribed conditional.
5. Re-run the same command; expected **GREEN**, with `0` direct lookups and `40` fallback lookups for both sorts and K values.

Do not modify test expectations to force green. Do not add a custom assertion-free benchmark or use wall-clock output as evidence.

---

## 6. Invariants, state boundaries, and cross-component impact

| Invariant | Required observable behavior | Scope/safety rationale | Acceptance tests |
|---|---|---|---|
| I01 **Exact hits** | Eligible path retains exact `total_hits` before K truncation; zero/one/many all correct | Entire postings stream still iterated; `matched` insert unchanged | B1-U01/U03; existing phase4 U09 |
| I02 **No redundant lookup** | `term_membership_lookups()==0` for strict eligible term; `predicate_calls()==M` | Skip only side-effect-free S06 match check, not callback | B1-U01/U02 |
| I03 **Fallback unchanged** | `And`, `Or`, `Not`, multi-analyzed term, phrase, typed, cursor and aggregations cannot reuse proof incorrectly | S01 gate remains the sole predicate | B1-U02/U04; phase4 U01–U05, cursor test |
| I04 **Scores bit-identical** | Same score `to_bits()` for every returned hit, for both relevance and explicit sort | `score_segment`, term frequencies and loop order unchanged | B1-U01, existing b U01/U12 |
| I05 **Determinism/order** | Same physical IDs, `DocumentKey`, sort values, ties and projection, no missing/duplicate hits | Heap, projection and key/sort validation unchanged | B1-U01; existing b U06/U07/U10/U12 |
| I06 **Work/budget** | Same modeled examination count, scanned posting work, entry/byte/peak limits; exact-at-limit passes and one-under/one-over fails as before | All charges and ledger reservations remain untouched | existing phase4 U10–U12; B1-U05 |
| I07 **Cancellation** | Same cancellation poll boundaries and typed `Cancelled` outcome; subsequent query reusable | Guard creation unchanged; binary search had no polling | existing phase4 U14; B1-U06 |
| I08 **Corruption/error** | Bad posting, live bitmap, stored or sort data still fails at same relevant stage; no nonwinner validation skipped | Runtime shape guard + `build_leaf_data` validation unchanged; no early K stop | source diff proof S03/S04 + existing negative/corruption suite |
| I09 **Batch & aggregation** | Batch does not silently skip accounting; aggregated/mixed query never enters unapproved path | S01 gate independent of `keyword_sort_late`; aggregate disabled, batch may still use postings path | phase4 eligibility, existing batch suites, B1-U04 |
| I10 **Snapshot & topology** | No persisted index/manifest/codec change, old readers stable, local and RustFS results identical | Read-only callback code, zero external service changes | pr06/pr13/pr15g integration, CI rustfs |
| I11 **No production instrument** | Counter not present in release path, no public API/config/test-only feature in product | `#[cfg(test)]` entirely confines witness | `cargo clippy`, all-features tests; code inspection |
| I12 **Baseline defaults** | K10 linear/K100 P2 retained-key prefilter unchanged | Unrelated PERF-01 rule | source diff allowlist, existing b/d3c tests |

**State transitions:** Empty posting list ⇒ no `is_match` callback, zero hits. One posting ⇒ one callback and one match, zero redundant term lookups. M postings ⇒ M callbacks, M matches, unchanged scoring and Top-K. Ineligible request ⇒ live bitmap traversal and original `evaluate_unified` for each examined effective-live doc. Runtime shape mismatch ⇒ `SearchError::CorruptIndex` **before** callback and without a guessed fallback. Cancellation/resource failure ⇒ existing typed error, and all ledger/reader RAII cleanup remains unchanged.

**Cross-component matrix:**

| Component | Modification? | Justification |
|---|---|---|
| `unified.rs::collect_mixed` | **YES: exactly §4** | Only conditional known-true membership result |
| `execute.rs::LeafData::matches` | **TEST-ONLY observation** | Fallback behavior must still use original binary search |
| `execute.rs::evaluate_lexical_with` | **NO** | Owns preapproved runtime proof, accounting and callback count |
| `unified.rs::single_term_postings_eligible` | **NO** | Existing strict safety gate |
| `unified.rs::evaluate_unified` | **NO** | Other Boolean/typed/phrase paths need generic logic |
| `score.rs`, `typed.rs`, sort/heap and projection | **NO** | Scores and output behavior are unchanged |
| `Index`, `SegmentReader`, codecs, `Directory`, RustFS/S3 | **NO** | No storage/format changes |
| Benchmark adapters, configs, results, statistics, CI | **NO** | PERF-05-C owns performance acquisition |

**Oracle:** The existing `Query::And(vec![term("alpha")])` path is a **control**, not an independent semantic oracle by itself. Pair its outputs with the **independently enumerated fixture model** (`corpus(40, &matching)` known IDs and counts), existing bitwise-score tests, work-budget boundary tests, and real-index integration tests. Never infer correctness merely because two implementation branches agree. Different query ASTs have different cursor fingerprints; compare keys/scores/projection/count, not cursor bytes.

---

## 7. Deterministic and adversarial acceptance matrix

**Add only B1-U01–U04 as new tests in `phase4_tests` where the helper is reusable.** Existing tests listed below supply additional required evidence; do not duplicate their harnesses. A test ID is a behavioral requirement, not permission to create a new benchmark or new public API.

| ID | Fixture/operation | Required assertion / exact gate |
|---|---|---|
| **B1-U01** | 40 live docs, known `[0,2,13,39]` hits; K1/K10, relevance and explicit `n ASC` | Strict `Term(alpha)` returns all 4 count, top K, calls callback 4×, **0 term lookups**; exact keys and bitwise scores vs known fixture and wrapped control |
| **B1-U02** | Same corpus wrapped in `Query::And([Term(alpha)])` | Fallback calls callback 40× and term membership 40×; equal keys, counts, score bits and projection to direct query |
| **B1-U03** | 40 docs, `Term(absent)` and one-hit `[7]` cases | Absent: 0 callbacks, 0 lookups, 0 hits; singleton: 1 callback, 0 lookups, one exact hit; wrapped controls preserve results |
| **B1-U04** | Existing phase4 eligibility array plus at least one multi-analyzed query `term("alpha beta")`, cursor continuation and an `And` with typed `Exists("n")` | Each ineligible shape remains on original evaluation (positive term lookup present where lexical term evaluated); no bypass on cursor, compound, typed, phrase or aggregation. Use existing phase4 U01–U05 and cursor test for items whose contract is already proven; add one focused witness assertion for the multi-analyzed shape if needed |
| **B1-U05** | Existing phase4 U10–U12 work budget boundary | Strict and wrapped queries use same minimum admitted work units; exact succeeds; one-under returns `SearchError::ResourceLimit` |
| **B1-U06** | Existing phase4 U14 cancellation | Cancelled query returns `SearchError::Cancelled` at already established polls; same snapshot subsequently queryable |
| **B1-U07** | Existing phase4 U09/U16 + `b_tests::b_u01_u08_u36_counts_order_and_materialization` | All-live/none-live, K1/K10/K100, full counts, no extra owned tuples, 4097-doc count chunk |
| **B1-U08** | Existing `b_tests::b_u12_two_segment_score_bits`, null/tie and UTF-8 tests | Two segments, exact byte ordering, null/missing and score bits unchanged |
| **B1-I01** | Real `FsDirectory` analyzer→writer→commit→fresh reader→search (existing `pr06_local_integration` and `pr13_oracle` integration targets) | Real production storage path passes; no new fake-only integration |
| **B1-I02** | Existing real RustFS core oracle and prior selected-key acceptance under pinned CI service | CI `rustfs` jobs pass; local service run when environment is actually provided; otherwise mark **BLOCKED**, never fabricate |
| **B1-I03** | Default and all-features Rust workspace, stable and MSRV | Full suites and toolchains pass, ≥85% workspace production line coverage, no altered feature behavior |

**B1-U03 prescribed addition** (in `phase4_tests`): create an index using `corpus(40, &[7])`; run a strict `Term("absent")` then strict `Term("alpha")` with K10; for each reset both counters. Assert `(total_hits, predicate_calls, term_membership_lookups)` equals `(0,0,0)` and `(1,1,0)`, respectively. Compare their keys and exact score bits with independent fixture expectations. Then run wrapped `Query::And(vec![term("alpha")])` and assert it invokes the membership lookup once per all 40 live docs. No new helper needed.

**B1-U04 prescribed addition:** In the same fixture, verify `term("alpha beta")` does **not** pass `single_term_postings_eligible` (existing U01–U05 already proves this). Execute it once, reset the membership witness, and assert `term_membership_lookups() > 0` (the fallback examines live documents). For typed + lexical, `Query::And(vec![term("alpha"), Query::Exists { field: "n".to_owned() }])` must remain ineligible; execute with existing `req` and assert no change to typed query correctness. If this exact mixed query is rejected by the established contract on baseline, **do not change the query API**; preserve the baseline typed error and report the test as an explicit negative contract case. Check cursor and aggregation using existing tests, not custom cursor-token substitution.

**Error and failure matrix:**

| Failure / boundary | Expected response | Evidence |
|---|---|---|
| Empty, singleton, all matches | Exact counts and best-first K; callback only for actual eligible postings | B1-U01/U03/U07 |
| Noneligible query (nested, expanded, typed, aggregation, cursor) | Existing fallback, not unconditional true | B1-U04; phase4 eligibility/cursor |
| Runtime impossible postings shape | Existing `SearchError::CorruptIndex`; do not bypass guard or guess true | No edit to S03 runtime guard; regression suite |
| Invalid/corrupt index data incl. nonwinning | Existing typed error / validation and ordering | Full decode and per-candidate key/sort logic unmodified; relevant corruption suites |
| Work budget exact vs one-under | Same pass/fail, same typed error | phase4 U10–U12 |
| Cancel at polls 0/1 | Same `Cancelled`, no leaked ledger | phase4 U14 |
| Multiple segments/tombstones/upsert | Same keys, scores, effective-live selection | b U12, pr13 oracle and RustFS suite |
| Remote failures/restart/cache | Existing storage semantics untouched; reported integration status must be real | CI rustfs; no new storage code |

### Red-first / green-first acceptance

The intentional RED in §5 is a required **feature-existence demonstration**, not an unresolved regression. Once §4 is applied, every required test must be GREEN. Do not claim `B1 PASS` if the red test passes before the production change (witness broken), if the green test passes with nonzero direct lookups, or if any unchanged fallback stops looking up terms.

---

## 8. Integration topology and canonical QA — NO TIMED BENCHMARKS

**Before coding:** verify installed tools. Do not create a new benchmark framework or use performance profiling to diagnose failures. Use regular `cargo test` and the repository's existing CI workflow, including actual RustFS where available. The host's idle status is assumed as requested.

**Run after the final source/test changes (in this order; record real results):**

```bash
# A. Focused feature/semantic tests, real in-crate algorithms and indexes:
cargo test -p quervant-core --lib phase4_b1 -- --nocapture
cargo test -p quervant-core --lib phase4_tests -- --nocapture
cargo test -p quervant-core --lib b_tests -- --nocapture

# B. Real-boundary local integration and oracle suites:
cargo test -p quervant-core --test pr06_local_integration
cargo test -p quervant-core --test pr13_oracle
cargo test -p quervant-core --test pr15e_b1

# C. Stable toolchain workspace, both feature regimes:
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo doc --workspace --all-features --no-deps

# D. Rust 1.85.0 MSRV:
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features

# E. Repository housekeeping checks (no timed benchmarks):
bash benchmarks/scripts/test-scripts.sh
git diff --check
```

- `cargo llvm-cov` measures the full **production workspace**, not a selected module. The threshold is **85% line coverage**, as verified in `.github/workflows/ci.yml`. Do not exclude production code or change the limit. Capture actual line percentage and toolchain version. If tool is missing, attempt ordinary installation of the prescribed toolchain component and `cargo-llvm-cov` without changing repository files or system security settings; if installation is unavailable, record **BLOCKED**, finish independent checks, and do not call B1 fully accepted.
- CI additionally runs `cargo bench --workspace --no-run` (**build/compile only**) and tests benchmark scripts; **do not** call real benchmark or profiler commands. CI `python-benchmark-framework` and `benchmark-adapter-contract` should remain unmodified and serve as regressions.
- Real RustFS acceptance requires an actual service. The existing CI workflow supplies pinned RustFS under the `rustfs` job and runs, among others:

```bash
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1
```

  Run locally **only** if the preconfigured `QUERVANT_RUSTFS_*` service environment is genuinely present; do not provision external services, invent credentials, lower service/security settings or claim ignored tests executed without their explicit `--ignored` invocation. CI's RustFS outcome is a mandatory recorded acceptance gate. If unavailable at report time, mark `RUSTFS_CI_PENDING`/`BLOCKED` and continue safe code/report tasks. This plan does not add new RustFS storage behavior.
- **Toolchains:** CI pins stable `1.98.1` and MSRV `1.85.0`. If the host's default `cargo` is not the required stable version, use a verified installed `cargo +1.98.1 ...` equivalent. If neither is installed, environment gate **BLOCKED**; do not silently run an unrelated version and label it compliant.
- **Full-suite policy:** Repository `AGENTS.md` requires local full applicable QA. Do not skip full checks because B1 code is small. After any corrective patch to source/test/manifest, repeat every affected gate, including workspace coverage. Rerun final tests on the final tracked tree before committing.
- **Mandatory line coverage:** ≥85% on applicable production workspace. New test-only witness does not justify any altered exclusion.

**Important:** These are correctness and build/CI checks; they are not a PERF-05-B benchmarking/profiling campaign. Do not measure or report query latency, CPU shares, A/B ratios, benchmark samples or host idle fractions. PERF-05-C will do those once for the coherent implemented series.

---

## 9. Documentation, allowlist and evidence obligations

**Only these tracked paths may change in B1:**

1. `crates/quervant-core/src/search/unified.rs` — one bounded conditional and in-file B1 tests.
2. `crates/quervant-core/src/search/execute.rs` — `#[cfg(test)]` witness only; production matching algorithm unchanged.
3. `docs/pr-artifacts/perf-05/PERF05B1_DETAILED_PLAN.md` — exact approved plan copied into shared PR for durable traceability; no edits to its design during agent execution.
4. `docs/pr-artifacts/perf-05/PERF05B1_EXECUTION_REPORT.md` — implementation provenance, test results, scope audit, decisions and limitations.

**Normally never change:** `Cargo.toml`/`Cargo.lock`, `AGENTS.md`, `.github/**`, `docs/BENCHMARKING.md`, benchmark configs/results or scripts, `search/score.rs`, `search/typed.rs`, `search/unified_plan.rs`, `search/execute.rs::evaluate_lexical_with`, segment codecs, readers/writers, RustFS, Top-K heap or duplicate strategy, the original source-audit/roadmap conclusions or any other stage's files. If any further file appears necessary, **HARD STOP** pending a separately approved plan amendment; do not broaden the allowlist yourself.

**Document status:** B1 may be reported `B1_IMPLEMENTED_LOCAL_QA_PASS_PENDING_INDEPENDENT_REVIEW` if all required *local* gates actually pass and remote/CI requirements are separately labeled pending; it is not final acceptance. Do not mark all PERF-05 complete, merge PR #117, trigger B2 automatically or mislabel planned PERF-05-C benchmark evidence as already acquired. The shared register's proposed statuses remain valid until independently reviewed.

**Produce the report with this exact structure:**

```text
PERF-05-B1 EXECUTION REPORT
REPO / BRANCH / PR
START_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA / MAIN_SHA
IMPLEMENTED_FILES (exact list)
SOURCE_PROOF_CHECKS: S01–S10; INVARIANTS: I01–I12
RED_FIRST: command, expected-vs-actual assertion, status
GREEN: command, test count, status
TESTS: command | toolchain/topology | PASS/FAIL/BLOCKED/NOT_APPLICABLE | evidence
WORKSPACE_COVERAGE: real percentage or BLOCKED
RUSTFS: service/execution/CI status, do not invent PASS
EXCEPTION_MATRIX_ROWS: trigger, action, evidence (or NONE)
OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION
NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE
B1_DISPOSITION and reasons
NEXT=independent review; B2 not authorized by this report
```

**Completion provenance:** `git diff --name-only "$START_SHA" HEAD`, `git diff --check`, commit ID, `git status --porcelain`, and proof the same SHA exists on the existing PR branch. Never claim tests ran after final changes unless their logs are from that final tree. Do not attach generated `target/` benchmark results.

---

## 10. Ordered autonomous implementation sequence

1. **Preflight:** Apply §3. If any hard blocker, report STOP. Capture exact source and source-path parity vs `origin/main`.
2. **Correctness review:** Fill the §6 invariant-to-test checklist, read S01–S10, verify guard and no-op matcher semantics. STOP if source differs.
3. **Red-first witness:** Implement §5.1 and the literal §5.2 test, run the single test expecting the specified **lookup count failure**. If RED differs, STOP.
4. **Production fix:** Apply §4 **verbatim** within the existing callback. Do not move evaluation into the iterator or alter callback signature.
5. **Green witness:** Run §5.2 test. Require 0 direct term lookups, 40 fallback, 4 direct callback invocations, exact key/count/score/projection parity.
6. **Targeted adversarial tests:** Add B1-U03/U04 as specified (reuse existing fixtures). Run targeted phase4 and b tests (B1-U01–U08). Any mismatch → classify and follow §13.
7. **Normal QA:** Run the canonical commands in §8, including full workspace coverage, MSRV and real integration gates (hosted RustFS if local unavailable). Record actual pass/fail, no silence.
8. **Scope/diff audit:** Inspect `git diff`, prove only the four permitted paths changed and S03/S05 production logic remains untouched. Run `git diff --check` and final affected QA after the last edit.
9. **Documentation:** Copy the approved plan unmodified as `PERF05B1_DETAILED_PLAN.md`; create the execution report from §9. Do not rewrite historical evidence or roadmap status.
10. **Commit and push:** One bounded B1 commit (or one code+report commit if possible), e.g. `perf(perf05b1): eliminate proven single-term relookup`. Use **only** the existing branch. `git push origin HEAD:dev/perf05-physical-execution-series` (no `--force`). Verify remote branch SHA equals the reported FINAL_SHA and PR #117 stays open. Report outstanding CI as pending, not green.
11. **Terminal report:** Return the requested status, full gate table and any STOP/DEFER. **Do not start B2, profiling, benchmarking, PR merge or release.**

If the report's own documentation edit occurs after QA, rerun `git diff --check` and any affected doc/format verification; code/test changes require all relevant tests and coverage again.

---

## 11. Independent reviewer checklist

- [ ] The source proof in §1 still applies exactly on the final diff.
- [ ] The only production semantic delta is `postings_candidate_eligible ? true : evaluate_unified(...)` **inside** the existing callback.
- [ ] Per-segment runtime shape guard, callback invocation and `PREDICATE_CALLS` remain intact.
- [ ] Only test-code instrumentation changed `LeafData::matches`; no release overhead or generic fallback change.
- [ ] Red-first witness failed only because the old eligible path performed 4 unnecessary lookups.
- [ ] Green tests demonstrate direct=0 and fallback=40 lookups; M callbacks are preserved.
- [ ] Count/key/score **bits**/projection/sort/cursor behavior agrees with fixture and fallback controls.
- [ ] Work, decoded postings integrity, cancellation, error precedence, budget/ledger and duplication semantics are unchanged.
- [ ] Multiple segments, tombstones, null sorting, K1/K10/K100, multi-analyzed terms, typed queries and cursor paths are covered by verified suites.
- [ ] Stable/MSRV default/all-features QA passed on final source; workspace line coverage ≥85% measured.
- [ ] Real FsDirectory path executed; pinned RustFS CI executed or exact pending/blocker documented; no fake reported as real.
- [ ] Every file change is allowed and attributable to B1; no Cargo, CI, format, BM-10, reader, scorer or heap redesign.
- [ ] `NO_BENCHMARK_RUNS=TRUE`, `NO_PROFILING_RUNS=TRUE`; host idle assumption honored without probes.
- [ ] Final commit pushed to PR #117, no force push, merge, B2 initiation or fabricated completed status.

---

## 12. Suggested PR #117 B1 progress note (append, do NOT create a new PR)

```markdown
### PERF-05-B1 — redundant single-term membership lookup

- **Scope:** Reuse the already-proven positive lexical membership from the validated
  one-term posting iterator in the existing unified callback. Generic predicate,
  scorer, budgets, work/cancellation, heap and sort remain unchanged.
- **Evidence:** Test-only term-membership witness demonstrates zero re-lookups on
  eligible postings and unchanged full-scan lookup on ineligible controls.
- **QA:** See `docs/pr-artifacts/perf-05/PERF05B1_EXECUTION_REPORT.md` for actual
  commands, stable/MSRV/coverage/local/RustFS statuses and errors.
- **Deferred:** B2–B5 and C; **no benchmarking or profiling was performed**.
```

Do not modify the PR's draft/merge state. Use this note only after B1 changes and evidence exist, and distinguish code complete from all gates verified.

---

## 13. Preauthorized architectural decisions and exception-handling matrix

**Rule hierarchy:** existing Quervant semantics and this plan's allowlist > AUTO-RESOLVE > DEFER AND CONTINUE. If multiple rows match, use the most restrictive. **No match ⇒ HARD STOP** for the dependent code path; independent documentation/evidence may continue only if safe. Every applied row must appear in the execution report with source observation, action and result. The **escalation owner** is the maintainer/reviewer of PR #117; the coding agent cannot approve its own design changes.

| ID | Observable trigger / source check | Category | Authorized action | Prohibited action | Evidence / affected gate / escalation |
|---|---|---|---|---|---|
| D01 | Branch is wrong, local changes exist, pull is non-fast-forward, source files differ from `origin/main` or S01–S10 changed | **HARD STOP** | Record exact HEAD/remote SHA, status/diff and affected source; halt source edits | Stash, reset, rebase, force-push, rewrite source to fit old plan | Preflight BLOCKED; maintainer must revise plan |
| D02 | Source matches verified S01–S10 and existing callback is exactly the known structure | **AUTO-RESOLVE** | Apply §4 verbatim and continue after red-first test | Change callback API, replace guard, change other query paths | Record source lines/diff; implementation gate |
| D03 | Red-first test compiles and fails **only** because direct term lookups equal M=4 instead of zero; fallback M=40 | **AUTO-RESOLVE** | Record expected RED, apply §4, continue to GREEN | Retune test data/expected count, declare other failure an acceptable RED | Red-first gate PASS-as-expected |
| D04 | Red-first test fails compilation, returns incorrect hits/scores, panics, or lacks a 4-lookup witness | **HARD STOP** | Preserve logs, source and fixture details; stop production patch | Modify eligibility, fixture semantics, expected values or tests to force expected failure | Test harness gate BLOCKED; maintainer |
| D05 | New witness would require modification outside `LeafData::matches` Term arm or test_observation module | **HARD STOP** | Record why; do not introduce release instrumentation | Add public metrics, feature toggles, benchmark counters | Test-only observability scope |
| D06 | Simple Rustfmt/Clippy formatting or unused-import issue **strictly inside the authorized changed lines** | **AUTO-RESOLVE** | Apply deterministic formatting or remove the accidental local unused import, rerun affected gates | Change generic scorer, add a crate/dependency, disable Clippy or suppress warnings | Record actual compiler finding/fix |
| D07 | `postings_candidate_eligible` would be true for any shape outside S01 or S03 guard moved after callback | **HARD STOP** | Stop; record minimal counterexample and code path | Assume membership true on broader Boolean/typed/cursor/batch shapes, widen gate | Eligibility/safety proof BLOCKED |
| D08 | `term_membership_lookups` remains nonzero in eligible GREEN run, or zero in ineligible control | **HARD STOP** | Preserve diff/counters and stop; require design amendment | Skip callback, change counter to fake zero, weaken assertion | B1-U01/U02 correctness BLOCKED |
| D09 | Count, score bits, projection, key ordering, sort ties, `total_hits` or cursor semantics differ | **HARD STOP** | Record exact fixture, actual vs expected and first failing function | Disable scoring, drop candidates, alter sort comparator, relax oracles | I01/I04/I05; maintainer |
| D10 | Work/byte/peak admission boundary, cancellation timing/poll outcome, corruption or duplicate detection differs | **HARD STOP** | Preserve typed errors, source deltas, minimal reproducer; stop | Change counters, caps, decode/validation, cancellation polls or error precedence | I06–I09; maintainer |
| D11 | A mandatory test fails; baseline may also fail | **DEFER AND CONTINUE** | Classify as introduced/feature/pre-existing/flaky/environment with evidence. For pre-existing, reproduce on baseline in a **temporary clean checkout** only if authorized and safe; continue independent checks; leave acceptance blocked | Claim unrelated/flaky without proof, unbounded reruns, skip failing gate, change test to hide failure | QA gate BLOCKED; maintainer |
| D12 | A failing test has a clear mechanical typo confined to B1 test/witness (not behavior), verified against §5's literal contract | **AUTO-RESOLVE** | Fix that exact typo once; run affected + final full required QA | Alter expected outputs or source eligibility; touch unrelated files | Document one bounded fix and rerun |
| D13 | `cargo llvm-cov` or MSRV toolchain absent, normal installation impossible, or external RustFS service unavailable | **DEFER AND CONTINUE** | Try safe standard setup where applicable, report exact command/missing dependency, finish independent QA and commit truthful pending report | Lower 85% gate, substitute fake RustFS, install privileged services, claim PASS | Tool/CI/RustFS gate BLOCKED; maintainer |
| D14 | CI not finished or unavailable after safe push | **DEFER AND CONTINUE** | Record `CI_PENDING`, remote HEAD, job URL if available; report pending without polling indefinitely | Declare green, bypass required checks or dispatch redundant full CI | CI acceptance PENDING; independent review |
| D15 | Any change requires Cargo/features, codec, reader, `evaluate_lexical_with`, scorer, heap, stats, RustFS, benchmark config or workflow edit | **HARD STOP** | Stop affected work; report required design delta | Broaden file allowlist, add alternate executor, new framework or query-mode switch | Scope BLOCKED; maintainer approval required |
| D16 | More than a narrow §4 conditional needed to preserve the callback's effects | **HARD STOP** | Record precise contradiction; halt code path | Invent alternate architecture, skip `is_match`, or make generic fallback return true | S01–S07 proof invalid; maintainer |
| D17 | Host assumed idle, agent tempted to run microbenchmark / profile to estimate improvement | **AUTO-RESOLVE** | **Do not run it**; continue approved correctness QA, reserve performance to PERF-05-C | `quervant-bench run`, `perf record`, timed loops, CPU sampling, host-idle probes | B1 no-acquisition rule |
| D18 | A test-only instrumentation issue appears only under `#[cfg(test)]` and has a deterministic fix **within §5.1** | **AUTO-RESOLVE** | Apply exactly the prescribed counter name/import/placement fix, then rerun red/green + QA | Add production instrumentation, alter `LeafData::matches` algorithm | Witness gate; log change |
| D19 | Branch advanced remotely after B1 start or push rejected for non-fast-forward | **HARD STOP** | Keep local commit, report local and remote SHAs, request reconciliation | Force-push, auto-merge, cherry-pick unrelated work, rewrite other's commit | Source consistency; maintainer |
| D20 | All local tests passed but hosted CI/real RustFS still pending | **DEFER AND CONTINUE** | Commit evidence and report `B1_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING` | Mark PR #117 merge-ready or B1 fully accepted | Final status pending external acceptance |
| D21 | All gates PASS with verified final source and no unclassified failures | **AUTO-RESOLVE** | Commit/push B1 and report `B1_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` | Merge, begin B2 or run a performance campaign | Review handoff only |
| D22 | Any circumstance not exactly covered above, including ambiguous source proof or a new semantic contract | **HARD STOP** | Stop affected work, document minimal decision required, continue only provably independent report preparation | Guess, infer new permission, choose an alternative algorithm | Maintainer plan amendment needed |

**Failure classification requirement:** Every failing command must be categorized explicitly as **introduced regression**, **feature implementation defect**, **deterministic pre-existing failure**, **nondeterministic/flaky failure**, or **environment/harness failure**. Do not label a failure pre-existing without checking it against the relevant baseline or credible immutable evidence; do not label it flaky based on one pass. An unknown result remains BLOCKED. A category never waives required tests.

---

## 14. Acceptance summary and next-stage boundary

**Implementation PASS** requires one exact conditional in `collect_mixed`, strictly test-only Term membership witness, correct new tests and no unrelated production changes.  
**Correctness PASS** requires red→green evidence, exact count/key/score-bit/projection parity, all applicable adversarial/fallback/budget/cancellation integration results, full stable+MSRV QA and ≥85% measured production workspace line coverage.  
**External acceptance** requires real RustFS topology and CI results; pending/blockers remain explicit until actually executed.  
**Performance:** **NOT APPLICABLE TO B1** — none is run or claimed; PERF-05-C is the only benchmark/profiler acquisition stage.  
**B1 terminal result:** A bounded pushed commit with truthful verification report, independent review pending; **PR #117 remains open and unmerged**.  
**Next step (not executed here):** Only after review and a separate B2 detailed plan, continue object-reuse work on the same branch/PR. Do not preempt B2 or B3 design.

> **Coding-agent rule:** The plan is the architecture. Implement it exactly; prove the one redundant lookup is gone while all fallback operations and observable semantics remain unchanged. If a situation is not explicitly decided by §13, **STOP instead of improvising**.
