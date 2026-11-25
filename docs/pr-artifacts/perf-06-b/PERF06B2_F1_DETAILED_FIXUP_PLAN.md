# PERF-06-B2-F1 — Global-heap integrity and genuine losing-value acceptance

**Repository:** [`yduchesne/quervant`](https://github.com/yduchesne/quervant)  
**Existing PR:** [#127](https://github.com/yduchesne/quervant/pull/127), `dev/perf06-b2`, **open and draft** at plan authoring  
**Reviewed final branch head:** `ca573ef624529418fd1a6e4bdaa978b4e75f6b2a`  
**Reviewed/tested executable source:** `237ae6dcc01d1c179f292b05cf843df76c9f6ad4`  
**Accepted post-B1 `main` (PR #126 merged):** `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`  
**Source of this fixup:** Independent B2 review of PR #127, two P2 findings.  
**Authoritative instructions:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`; `docs/pr-artifacts/perf-06-b/PERF06B2_DETAILED_PLAN.md`; `docs/ARCHITECTURE.md`; `docs/TESTING.md`; `AGENTS.md`.  
**Target artifact in the repository:** `docs/pr-artifacts/perf-06-b/PERF06B2_F1_DETAILED_FIXUP_PLAN.md`.  
**Nature:** Narrow corrective implementation and acceptance evidence. **Not** a new architecture, performance campaign, B3/B4 task, or merge approval.

## 0. Mandatory execution contract

> **Continuous execution authorization:** Once this plan is approved and execution is authorized, execute every prescribed preflight, correction, focused test, integration check, final QA, documentation and ordinary PR delivery step without asking for routine reconfirmation. Continue automatically after successful checkpoints and AUTO-RESOLVE decisions. On an isolated external blocker, mark only the dependent gate blocked and continue all safe independent work. Stop affected work on a specifically applicable HARD STOP or unlisted/ambiguous condition. Never improvise a new design, change public semantics, weaken a required assertion, merge the PR, create a replacement PR, or start B3/B4.

1. **Work on existing PR #127 and branch `dev/perf06-b2` only**. Pull latest with `--ff-only`; do not reset, rebase, force-push, auto-stash, clean, cherry-pick, or change base. Preserve existing draft state. Only normal commits and pushes are authorized.
2. Preserve the accepted B1 `COLUMNS` v2/feature `0x0010/1` bytes, per-segment dictionaries, snapshot-wide ordinal translations, immutable snapshot/PIT identities, optional availability, validation and budgets. **No edits** to any B1 codec/map, format, segment writer, storage, remote, manifest, or benchmark component.
3. Preserve B2's approved **single global `BinaryHeap<MixedEntry>`**, `K+1` retention, `OrdinalSortKey`, numeric compare, key tie-break, full logical charges, duplicate strategy, exact hit count, score bits, field projection, owned string cursor atoms, MultiOne legacy decode, and whole-request legacy fallback.
4. Correct **F1-01**: a hidden `ordinal_sort=None` entry must be detected before numeric competitiveness comparison, even if `BinaryHeap::peek()` has `Some(rank)` and the new candidate would lose. **No O(K) heap scan per candidate or per competitive admission.** Implement the request-local, once-only audit in §4 exactly.
5. Correct **F1-02**: B2-I07 must prove an actually **noncompetitive** later 80-byte Single value in a `K=1`, **`K+1=2`** heap. Use three matching rows in the frozen order, plus a `cfg(test)` unit structural witness; see §5.
6. Keep original plan and unfavorable historical results unchanged. Add an F1 correction section to the existing execution report; do not retroactively edit earlier gate claims as though they had passed originally. G10 remains maintainer/independent-review owned.
7. **Do not run performance benchmarking**, timing acquisition, `perf`, Lucene/Tantivy runs, BM-10 or B4, change the benchmark adapters/configuration/results, or start RustFS locally. Final local test QA and existing hosted real-RustFS CI are allowed and required as below.

### 0.1 Final disposition vocabulary

| Status | Meaning |
|---|---|
| `PERF06_B2_F1_READY_FOR_INDEPENDENT_REVIEW` | F1 code complete, both adversarial findings proved, required QA and all five ordinary CI jobs pass on identical executable/test source; G10 still open. |
| `PERF06_B2_F1_IMPLEMENTED_VERIFICATION_BLOCKED` | Source correction and available tests complete but an essential gate (e.g. CI, job, service) unexecuted/pending/blocked. Exact gate and evidence recorded. |
| `PERF06_B2_F1_INCOMPLETE_STOP_<RULE>` | A HARD STOP applies or a source/semantic mismatch cannot be resolved under the matrix. Preserve the branch and specify the rule, paths, failing assertion and proposed narrow amendment. |

## 1. Source admission — do this before editing (G0)

From repo root, capture command stdout/stderr, code, and source SHA in `docs/pr-artifacts/perf-06-b/evidence/b2-f1-preflight.txt`:

```sh
set -euo pipefail
git status --porcelain=v1
git fetch origin
git switch dev/perf06-b2
git pull --ff-only origin dev/perf06-b2
git status --porcelain=v1
git rev-parse HEAD
git rev-parse origin/dev/perf06-b2
git rev-parse origin/main
git merge-base HEAD origin/main
git diff --name-status 3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc..HEAD
git diff --name-status 237ae6dcc01d1c179f292b05cf843df76c9f6ad4..HEAD
```

**Dirty tracked work or an output collision:** stop mutation rather than stash, clean or delete anything. **Non-conflicting untracked foreign evidence** (including any previous B1 `f2-ci-status.txt` left in a worktree) is expressly permitted under D04a: record its exact path, leave its bytes untouched and uncommitted, and continue. If it obstructs a specific task output path, HARD STOP D04. A remote head newer than `ca573ef6...` is not automatically a problem: first compare the actual executable/test tree with the reviewed source. If only F1-independent documentation/evidence changed, continue per D02. If production or relevant tests changed, stop and request a plan amendment rather than overwrite other work. Confirm via the available authenticated GitHub workflow or CLI that PR #127 is still open, still `dev/perf06-b2 → main`, and that `main` contains the accepted B1/B2 base described above. If main advanced, require that the changed source is compatible by actual blob comparison; see D03. Do **not** silently rebase or merge main into this PR.

Read and record exact blob/SHA/hash of `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, the approved B2 detailed plan, and this new F1 plan after it is copied verbatim into the repository. Inspect the exact source symbols listed in §2 and the changed-path inventory. No source modification before completion of the invariant/counterexample worksheet in §3.

**At authoring:** public GitHub shows PR #127 open/draft, head `ca573ef624529418fd1a6e4bdaa978b4e75f6b2a`, base and current `main` `3cb1cbdff4c3bc7bbc1cae1c4e92c5cb44ca95cc`. Hosted run `45559725417` has all five jobs successful; that is **pre-F1 evidence only**, not F1 acceptance. The head differs from tested `237ae6d...` only in documentation/evidence. Reconfirm this rather than assuming it at execution.

## 2. Current source and exact remaining delta (G1)

| Symbol / location (reviewed B2 source) | Verified behavior | F1 decision |
|---|---|---|
| `search/unified.rs::collect_mixed` ~L740–L1065 | One B1 preparation per eligible strict-term keyword request; `Ready` selects numeric for whole request; `NotAvailable` selects legacy; one global heap; per-segment binding; exact hit counts. | **Preserve.** Add a request-local `OrdinalHeapAudit` and pass it only to numeric candidate calls. |
| `search/unified.rs::consider_ordinal_keyword_candidate` ~L2292–L2428 | Applies logical Single budget, translates local rank, charges values, handles MultiOne, checks duplicates, compares worst numerically, materializes competitive strings. | **Correct ordering:** audit numeric-only heap **before** a losing candidate could return. Remove late repeated `ensure_ordinal_heap` scan. |
| `search/unified.rs::ensure_ordinal_heap` ~L2258 | Iterates all heap entries and rejects any `ordinal_sort=None`. | **Reuse** for a once-per-request audit. Do not replace by an incomplete `peek()`-only check. |
| `search/unified.rs::MixedEntry::cmp` ~L2450; `heap_admit_candidate`; `d3c::State::admit` | Numeric comparator when both `Some`, old canonical comparator otherwise; existing duplicate/heap commits move supplied entries. | **Preserve.** Verify all B2-created entries are `Some` and no B2-mode call can insert `None`. No change to canonical comparator or d3c. |
| `search/unified.rs::b2_u14_mixed_heaps_are_rejected_before_mutation` ~L7141 | Calls `ensure_ordinal_heap` directly on a heap with a single obvious legacy entry. | **Strengthen:** hidden legacy entry, numeric worst, losing numeric candidate **through the production candidate handler**. See §4.4. |
| `search/unified.rs::b2_u08_u22_budget_failure_leaves_heap_unchanged_and_charges_match` ~L6870 | Directly invokes numeric handler twice with heap mutations/budget boundary. | Supply same request-local audit instance to both handler calls; preserve exact `209/210` failure. |
| `tests/perf06_b2_ordinals.rs::b2_i07_losing_long_value_and_container_wrapped_corruption` ~L1038 | Writes two matching keys, `k0="a"`, `k1="z"×80`, then K=1: heap capacity is 2 so **long value is not rejected**. | Three keys `k0="a"`, `k1="b"`, `k2="z"×80`, processed in doc-id/insertion order, K=1; preserve separate corruption fixture. |
| `segment/column.rs::KeywordSortOrdinalColumn::read_sort_row` and `search/typed_compare.rs::ordinal_sort_key_cmp` | Single logical admission and shared-order comparator already implemented and correct by reviewed tests. | **Protected, no change.** |
| `tests/perf06_b2_ordinals.rs::b2_i01..i06,i08`, B1 acceptance fixtures, CI RustFS | Previously executed and passing, in the right local/CI topologies. | **Preserve** and rerun appropriate regression checks after F1 source changes. |

**Capability classification:** numeric B2 sort and B1 reuse are **DONE+VERIFIED** apart from F1-01/P2 and F1-02/P2. The internal-state integrity ordering is **PARTIAL / defect**; the I07 losing-row claim is **DONE NOT VERIFIED / inadequate fixture**. No other B2 capability should be redesigned or reimplemented.

## 3. Frozen correctness invariants and counterexamples

Complete a small worksheet under the F1 report **before editing**, with these exact IDs, inspected symbol paths, test names and expected errors. This pre-implementation worksheet is a gate, not a request to reconsider the architecture.

| ID | Invariant and positive proof | Adversarial counterexample and negative proof | Test |
|---|---|---|---|
| **F1-INV01** | A B1 `Ready` query operates in exactly one immutable ordinal-heap mode. Every entry ever admitted during that request has `ordinal_sort=Some(shared_rank)` or `Some(Missing/Null)`. | Numeric worst + hidden legacy `None` must be detected before any numeric compare/losing-return, not merely before replacement. | New `b2_f1_u01_hidden_mixed_heap_rejected_even_for_loser` |
| **F1-INV02** | The **first** numeric candidate runs the full O(K) audit once, and every later candidate uses an O(1) checked flag. In production the initial heap is empty. | Implementing `ensure_ordinal_heap` inside every candidate or each competitive branch is not acceptable; a descending 1,000-doc fixture may have 1,000 competitive admissions. | New `b2_f1_u02_one_time_audit_and_numeric_only_admissions`; unchanged U16 |
| **F1-INV03** | A clean numeric heap keeps its canonical ordering, `K+1` retention, logical budget, duplicate handling, and existing `SortValue` cursor tuples. | Lost/duplicated hit, wrong tie, wrong score bit, early admission or skipped duplicate check. | Existing B2 U03–U18, U22, I01/I02; focused F1 test |
| **F1-INV04** | Under strict Term with `K=1`, **two** earlier competitive Single candidates fill heap size 2; the **third** 80-byte `"z"...` Single is lexically worse, counted, logically admitted, compared, and discarded without an owned string. | Two-document fixture never fills `K+1`, so it cannot establish loser behavior. Also reject a test that merely asserts top result and `total_hits` without proving no materialization. | Strengthened I07 **and** new `b2_f1_u03_long_loser_after_k_plus_one` |
| **F1-INV05** | Inability to reach the per-value `limit:79, requested:80` through a public snapshot under those tight container-open limits remains documented accurately; it is already proven by the bound-reader U07. | Do not lower limits or invent public success/error; do not claim I07 executed the 79-byte rejection. | Retain B2-U07 and I07 source/evidence |
| **F1-INV06** | Invalid unselected v2 keyword in a *valid outer container* still fails with `SegmentError::InvalidUtf8 { context: "keyword" }`; immutable good bytes remain untouched. | Rebuilding only raw COLUMNS without checksum or suppressing the negative case is invalid. | Retain I07 second half; B1-U05/I07, B2-U17 |
| **F1-INV07** | F1 changes only allowed B2 query/test/report artifacts, with no new memory structure, format, cursor, remote, or benchmark contract. | Changed `CandidateBudget`, `d3c`, storage, format, RustFS workflow, adapter, B1 fixture, or timing results. | G0/G7/G9 source inventory and hosted CI |

### 3.1 State and failure boundaries

**Request state:** `NotAvailable`/ineligible = old legacy mode; `Ready` = numeric only. Audit states `Unchecked → Verified` on first actual numeric candidate; no reset/reuse across requests. A failing audit returns the existing bounded `SearchError::CorruptIndex("mixed ordinal and legacy sort entries")` **without changing the heap or accounting**. A valid request with zero candidates never needs a scan. On subsequent numeric admission all heap mutations preserve the invariant by construction; prove this from every branch of `heap_admit_candidate` and `d3c::State::admit`. Test source must not add an alternate heap mutation.

**Candidate order:** original row read/Single logical decode admission → shared ordinal translation → legacy-equivalent charge / MultiOne full decoder → duplicate check → **audit (first encounter only)** → numeric compare or acceptance → owned string only on competitive admission. A corrupt-heap error is internal and cannot arise from healthy immutable data. No change to normal query errors, candidate resource units, cancellation, work meter or score. The audit does not read or decode user strings.

**Empty, single, full, and negative cases:** empty numeric heap (first candidate), size `K+1` exactly, numeric worst with hidden legacy in a full heap, eligible vs ineligible query, zero segments, losing Single, winning Single, MultiOne losing full decoder, exact budget `79/80` reader-only witness, unselected corrupted term, and batch/PIT continuation. All missing/null/tie, ASC/DESC and UTF-8 comparisons stay in the original B2 regression matrix.

**External boundaries:** no new durable write, remote object, network call, process, file format, or task-owned RustFS service in F1. No crash/recovery design is required because the changed audit is query-local and no persistent state is introduced. B1's concurrency, cancellation, PIT ownership and map lifecycle are unchanged. Existing real RustFS CI is regression-only, not proof of F1's candidate ordering.

## 4. F1-01 — one-time mixed-heap guard, zero repeated O(K) scans (G2/G3/G4)

**Only production file to modify:** `crates/quervant-core/src/search/unified.rs`. Use existing `MixedEntry`, `BinaryHeap`, `SearchError`, `b2_observation`, `ensure_ordinal_heap`, `consider_ordinal_keyword_candidate`, `experiment.check`, `experiment.admit`, and old B2 constructors. Do not touch `search/typed_compare.rs`, `segment/column.rs`, `CandidateBudget`, `d3c::State` or `MixedEntry::cmp`.

### 4.1 Exact private implementation

Immediately adjacent to `ensure_ordinal_heap` (currently ~L2258), add **exactly one** small query-local audit state and method. Its name is frozen to avoid agent design:

```rust
/// Request-local proof that the ordinal heap was inspected before its first
/// numeric candidate comparison. Thereafter the numeric-only admission path
/// maintains the invariant by induction.
struct OrdinalHeapAudit {
    checked: bool,
}

impl OrdinalHeapAudit {
    fn new() -> Self {
        Self { checked: false }
    }

    fn verify_once(&mut self, heap: &BinaryHeap<MixedEntry<'_>>) -> SearchResult<()> {
        if self.checked {
            return Ok(());
        }
        ensure_ordinal_heap(heap)?;
        self.checked = true;
        Ok(())
    }
}
```

The code above is normative, apart from Rust formatting and **test-only** observation statements shown below. `OrdinalHeapAudit` must own only the `bool`: **no Vec, HashSet, map, extra heap, Arc, cache, thread-local production state, snapshot owner, dynamic dispatch, or public API**. `ensure_ordinal_heap` retains its existing exact typed failure on **any** `None` entry. On an error `checked` stays `false` and the candidate must not reach the numeric comparator or modify the heap; do not publish an optional fallback result. Do not set `checked=true` before the scan succeeds.

**Test-only full-scan counter:** Extend existing `#[cfg(test)] b2_observation` with one `Cell<usize>` named `FULL_HEAP_AUDITS`; reset it in its existing `reset()` and expose `full_heap_audits()`. Add `record_full_heap_audit()` under `#[cfg(test)]` inside the `if !self.checked` branch **before** the call to `ensure_ordinal_heap`, so an attempted failing audit is countable too. All additions must compile out in a normal production/benchmark build. Do not add a real trace, logger or metric.

### 4.2 Bind the audit to one request, not one segment or one candidate

In `UnifiedSearcher::collect_mixed`, locate the **existing** `heap` creation and optional B1 map selection. Create:

```rust
let mut ordinal_heap_audit = ordinal_map.as_ref().map(|_| OrdinalHeapAudit::new());
```

This is created once per `collect_mixed` invocation, after B1 `Ready`/fallback was decided and outside the segment/candidate loops. **Do not** create an audit inside `for (segment_index, reader)` or inside the `for (doc_id, score)` loop. Use `None` for `NotAvailable` and ineligible requests, so the legacy path is unaffected.

At the **existing** branch `if let Some((bound, translation)) = &ordinal_binding`, extract the request-local audit and pass `&mut OrdinalHeapAudit` to `consider_ordinal_keyword_candidate`. If the numeric binding exists but its audit is unexpectedly absent, return the **already defined** `mixed_ordinal_heap_error()`; do not instantiate an audit lazily or fall back to strings. The only authorized code change in this branch is passing this one extra private argument. Preserve the existing total-hit increment, logical key, score and `continue`.

The private handler signature gains exactly one argument `audit: &mut OrdinalHeapAudit` (position immediately after `translation` or immediately before `heap`, consistently everywhere). Update **all actual call sites**, including the two direct invocations in `b2_u08_u22_budget_failure_leaves_heap_unchanged_and_charges_match` (~L6909/L6935), using **one shared** local `OrdinalHeapAudit::new()` across both calls. No other caller should manufacture a new audit mid-query.

### 4.3 Correct the error-order defect in the handler

In `consider_ordinal_keyword_candidate` keep these existing steps, in this sequence:

```text
bound.read_sort_row(doc_id)?                     [same validation and Single budget]
translate local ordinal into shared rank?       [same typed error]
compute legacy-equivalent logical candidate charge / full MultiOne decode?
experiment.check(heap, &key)?                   [same duplicate check]
audit.verify_once(heap)?                       [NEW; once per request]
if heap.len() >= heap_limit {
    worst = heap.peek()  [O(1)]
    worst.ordinal_sort else mixed error         [existing O(1) guard]
    compare shared-rank candidate vs worst      [only after verified]
    if losing: return Ok(())                     [no owned Single copy]
}
construct normal owned SortValue if competitive [unchanged]
construct MixedEntry { ordinal_sort: Some(...) } [unchanged]
experiment.admit(...)                          [unchanged]
```

**Remove** the current `ensure_ordinal_heap(heap)?` immediately before `let sort_value = ...` (~L2370). It is now redundant because `audit.verify_once` runs before the first numeric comparison/decision. Do not move it to the top of each candidate loop: that would reintroduce O(K) work per candidate. Do not replace it with a check of only `heap.peek()` (the original defect). Retain the existing `worst.ordinal_sort` O(1) fail-closed check as a second defensive guard; it cannot substitute for the once-only full audit. Retain existing `MixedEntry::cmp` behavior for old callers and a defensive mixed pair. No new `panic!`, `unwrap`, `expect`, `assert` or memory-cap exception may be added to production logic.

**Formal preservation argument, required in report:** Initially the request heap is empty. `audit.verify_once` scans all existing entries before the first numeric competitiveness decision; in healthy production its first scan sees an empty heap. For the rest of this **same Ready request**, the only insertion/replacement is a `MixedEntry` constructed by `consider_ordinal_keyword_candidate` with `ordinal_sort: Some(numeric)` and forwarded through the existing `d3c::State::admit` / `heap_admit_candidate`. Eviction only removes entries; no legacy candidate branch executes once `ordinal_binding` exists for the request. Hence all retained entries stay `Some` inductively. Inspect every heap `push`, `pop`, and conditional admission under default **and** `pr15i-d3c-experiment` feature. If any other code can insert `None` into that heap in the same Ready request, **HARD STOP D12** instead of relying on the proof.

**Time complexity:** Full scan at most once per eligible Ready request, before the first numeric comparison; on normal initially empty heap the scan takes O(1) work. For all later candidates `checked` costs O(1) and the worst-entry check costs O(1). The correction does not add an O(K) operation to candidate processing or a second heap. Existing duplicate-policy work remains unchanged and is not part of this guard's cost.

### 4.4 Mandatory adversarial unit tests — use production handler, not only helper

Add these tests **within the existing B2 test module** in `search/unified.rs`. Keep the existing `b2_u14_mixed_heaps_are_rejected_before_mutation` and its comparator assertions; these new tests supplement it.

**`b2_f1_u01_hidden_mixed_heap_rejected_even_for_loser`** — exact negative witness:

1. Reuse the existing B2 unit `build`, `primary_guard`, `ColumnAccess`, `sort_field`, `request`, `d3c::State::for_test`, and `NeverCancel` helpers (as in `b2_u08_u22_budget_failure_leaves_heap_unchanged_and_charges_match`). Build one real B1 v2 segment of three source documents, in this physical/doc-id order: `("k0", City::Value("a"))`, `("k1", City::Value("b"))`, `("k2", City::Value("z"))`. Query is strict `term()`, `K=1`, `doc_id ASC`, `MissingLast`. Bind one real B1 `SnapshotKeywordOrdinals` and `KeywordSortOrdinalColumn`; translate real `doc_id=2` from the actual segment, not a fabricated ordinal.
2. Build a **synthetic retained heap** of size exactly **2** (`K+1`) using the existing private `MixedEntry` constructor shape: (a) legacy hidden entry `key="k0"`, owned keyword `"a"`, `ordinal_sort=None`; (b) numeric entry `key="k1"`, owned keyword `"b"`, `ordinal_sort=Some(OrdinalSortKey::Value(1))`. Use the canonical sort with `Asc/Last`. Assert `heap.peek()` is the numeric `"b"` entry, **not** the legacy `"a"`; assert one hidden `None` exists deeper in the heap. Do not rely on insertion order to establish `peek`: explicitly assert it.
3. Instantiate a **fresh unchecked** `OrdinalHeapAudit::new()`. Snapshot the heap's keys, original `ordinal_sort`, charges, scores and length (using read-only iteration); take baseline counters `b2_observation::reset()`. Call the **real `consider_ordinal_keyword_candidate`** for `doc_id=2`, key `"k2"`, score `1.0`, with bound reader/translation, current audit, existing `CandidateBudget`, `None` memory scope and existing Linear test duplicate policy. This candidate is lexically **worse** than the numeric worst `"b"` and would have returned early in the flawed implementation.
4. Demand exactly `Err(SearchError::CorruptIndex { detail })` with **`detail == "mixed ordinal and legacy sort entries"`**; assert `b2_observation::numeric_compares() == 0` and `owned_single_strings() == 0`, `full_heap_audits() == 1`, and every heap element/charge/key/score and length remains unchanged. No partial admission, retry or fallback. This test **fails under the reviewed source** because a losing candidate returns `Ok(())` before the late full scan.
5. Additional positive arm: run the same synthetic setup with **both** entries `Some` and a fresh audit; the numeric-losing `"z"` candidate must return `Ok(())` with **no** owned string or mutation, `numeric_compares()==1`, and `full_heap_audits()==1`. This rejects implementations that treat every full heap as corruption.

**`b2_f1_u02_one_time_audit_and_numeric_only_admissions`** — structural positive witness:

1. Reuse the existing `b2_u16_materialization_tracks_competitiveness` source fixtures (1,000 documents; K=10; sorted ascending and descending values). Run a clean eligible query under test-only observations; assert `full_heap_audits() == 1` per request even when **every** descending-input document is competitive and admitted. After each request, assert the previous exact counts, ordering, score-bit parity and numeric `owned_single_strings` behavior; do not weaken U16.
2. Verify a second separate eligible request has its own audit (after `b2_observation::reset()`, count again 1), even if the B1 map is cached on the same snapshot. Verify one ineligible `Query::And([Term])` request has `full_heap_audits()==0` and no B2 preparation. This distinguishes **request** lifetime from snapshot/map lifetime.
3. Review (`git diff`, source and test) that no full scan is performed per segment or candidate and the audit `checked` flag is not reset. This is static source evidence in addition to the actual test counter. No timing assertion or `Instant` benchmark.

Keep existing B2-U14, B2-U16, U08/U22, 64-case U13, `pr15h_b` and B1 tests intact. If an observed test helper's call signature differs from this pinned source, use only a mechanical private-argument update within the allowlist (D07); otherwise STOP.

## 5. F1-02 — make B2-I07 actually reject a later long Single (G4/G5)

**Only integration file to modify:** `crates/quervant-core/tests/perf06_b2_ordinals.rs`, inside existing `b2_i07_losing_long_value_and_container_wrapped_corruption`. Do not modify the frozen B1 input table, fixture package, or codec.

### 5.1 Fixed three-row topology and literal oracle

Replace the existing **two** inserted rows with these **three** rows, all in the same **one real FsDirectory segment**, inserted in this sequence in one ordinary writer commit:

| Physical input / expected doc-id order | Logical key | `city` (`FieldValues::Single(Keyword)`) | `n` | `body` | Lexical rank |
|---|---|---|---:|---|---:|
| 0 | `k0` | `"a"` | 0 | Text `"common"` | 0 |
| 1 | `k1` | `"b"` | 1 | Text `"common"` | 1 |
| 2 | `k2` | exactly **80 ASCII `z` bytes** | 2 | Text `"common"` | 2 |

Use existing `appended_document(key, City::Value(value), n)` and the existing `let long: &'static str = Box::leak("z".repeat(80).into_boxed_str())` (or a test-owned equivalent that does not alter public APIs). `category=type-d`, `stored_tag=stored`, `tags=[one,two]` remain identical across rows. Use existing `schema()/registry()` and real `Index::create`, commit, drop writer and **fresh** `Index::open_existing`; do not use a mock reader or a fabricated `Ready` map.

For K=1, the actual global heap capacity is **`K+1=2`**. The **first two** matched candidates fill it; `k2` is the **third** candidate and is lexically worse than both. The unit test in §5.2 must independently establish this candidate order and the non-materialization counter; simply returning the expected top key is insufficient proof. No new sort order, query rewrite, modified `K+1`, or alternate document-key identity is authorized.

### 5.2 Required exact integration assertions

Within I07 execute the real eligible strict `body` term query, `city ASC`, `MissingLast`, and retain exact oracles (not only equality to fallback):

| `TopK` | Expected `total_hits` | Expected returned keys | Expected `next_cursor` |
|---|---:|---|---|
| 1 | 3 | `["k0"]` | Some, Kth owned `Keyword("a")` |
| 2 | 3 | `["k0", "k1"]` | Some, Kth owned `Keyword("b")` |
| 3 | 3 | `["k0", "k1", "k2"]` | None |

Also run the ineligible semantic reference `fallback_query()` with the **same sort and TopK** for K=1 and K=2; assert ordered keys, `total_hits`, score presence/IEEE `score.to_bits()` and complete projection equality between B2 and fallback. For the input-derived assertions, check that `city` projected field values equal the three literal strings, and check the other five projected fields from the exact input constructor (not just a projection-field count). Check that all three source docs really match `body=common`, that there is exactly **one** v2 segment with an ordinal column, and that `doc_id=0/1/2` maps to `k0/k1/k2` before interpreting the rejection as later. If this order is not actually realized, **STOP D18**, rather than modifying the expected result or silently claiming a losing-candidate proof.

**Preserve unchanged** I07's second half: mutate the existing `Seattle` value within an authoritative B1 v2 COLUMNS dictionary, reconstruct the full `ContainerBuilder` with the original feature/section table and valid outer envelope, demand exactly `SegmentError::InvalidUtf8 { context: "keyword" }`, and verify original immutable bytes and snapshot-map readiness are untouched. Do not replace this with a raw `Vec<u8>` edit after reader validation.

### 5.3 Required `cfg(test)` structural witness (inside `search/unified.rs`)

Add **`b2_f1_u03_long_loser_after_k_plus_one`**, using the existing B2 `build` test harness (one real B1 v2 segment) and the same three `city/doc_id` input values `"a", "b", "z"×80` with unique `k0/k1/k2` keys. Run `K=1`, `ASC`, `MissingLast`, exact `term()`; assert:

```text
response.total_hits == 3
response keys == ["k0"]
b2_observation::eligible_requests() == 1
b2_observation::ready_uses() == 1
b2_observation::map_preparations() == 1
b2_observation::numeric_candidates() == 3
b2_observation::numeric_compares() == 1  # only the third candidate, after two heap admissions
b2_observation::owned_single_strings() == 2  # k0/k1 only, NOT k2
b2_observation::single_rejected_without_copy() == 1
b2_observation::full_heap_audits() == 1
```

Require exact expected candidate order by inspecting actual segment `doc_keys` as `k0,k1,k2` in document-id order (and fail if not). Compare the result against `Query::And(vec![term()])` for key, `total_hits`, projected `FieldValues`, and score bits; reset observations **only** between searches so the measured counter belongs to the eligible one. This structural witness **must fail** under the old two-row I07 topology (where `numeric_compares()==0` and `owned_single_strings()==2` simply means all matched values fit the heap). Do not claim a string was rejected merely because the resulting TopK page omitted it; distinguish page truncation from rejection before string ownership.

**79/80 limitation remains exact and honest:** The public snapshot's container-open admission rejects much tighter section or single-allocation limits before candidate processing. Retain the existing B2-U07 bound-accessor test that asserts `LimitExceeded { limit:79, requested:80 }` on real v2 bytes and the existing I07 permissive *public query*. Do **not** alter `SegmentLimits`, lower container limits, invent an injection path, or claim the public I07 observed the 79-byte failure. The two tests establish different obligations and are both mandatory.

## 6. Cross-component impact and deliberate non-goals

| Concern | F1 action | Preserved verification |
|---|---|---|
| Global heap `MixedEntry`, `d3c` duplicate strategies, `CandidateBudget` | Only one request-local `OrdinalHeapAudit` and one added handler argument; no new entry variant or charge. | B2-U08/U14/U16/U18/U22, all-feature CI. |
| B1 segment dictionary, local ordinal, snapshot map, PIT | **No change.** | B1 lib `b1_`, B1 I01–I08; B2 I01–I04. |
| Keyword value admission, missing/null/MultiOne, string copying | **No change.** | B2 U06/U07/U13/U16, B1 U13, B2 I05/I07. |
| Cursor K+1, cursor strings, batch, aggregate, typed/geo/JSON, relevance | **No change.** | B2 I02/I06, B2 U09/U23/U24. |
| Real local writer, immutable segment bytes, corruption | Only **test input size** in I07; no format/code modification. | B2 I03/I04/I07, B1 I04. |
| RustFS/ObjectStore/remote/CI topology | **No change.** | Existing hosted `rustfs` job, actual B1-R01 pass. |
| Benchmark adapters/methodology and B3/B4 | **Protected.** | Adapter contract and `bench --no-run`, no timing. |

**Failure classification required:** introduced regression, feature defect, deterministic pre-existing, nondeterministic/flaky, or environment/harness. A red test caused by F1 must remain in evidence and be fixed without deleting assertions. A test cannot be called pre-existing without reproducing on the correct base or equivalent source proof. Do not use broad retries or raise limits to silence failure.

## 7. Preauthorized Architectural Decisions and Exception-Handling Matrix

**Mandatory protocol:** Evaluate the exact trigger, act using **only** the specified authorized response, record the decision row/evidence, and continue after each AUTO-RESOLVE. `DEFER AND CONTINUE` leaves its affected gate blocked but does not stop independent authorized work. `HARD STOP` stops affected work; if isolation is impossible, stop the entire implementation. **Unlisted conditions are always D34 HARD STOP.** These rows do not authorize architectural improvisation, changing user-visible semantics, data loss, release, G10, or merging. When multiple apply, use the stricter one.

| Rule | Observable trigger | Category | Only authorized action | Prohibited shortcut | Evidence / gate / owner |
|---|---|---|---|---|---|
| **D01** | PR #127 open/draft, `dev/perf06-b2 → main`, reviewed source exactly as pinned | AUTO-RESOLVE | Fast-forward-only update, inspect symbols, complete worksheet, proceed. | New PR, force push, merge. | SHA/PR/branch G0; agent. |
| **D02** | A newer B2 head differs from pinned head only in docs/evidence | AUTO-RESOLVE | Compare actual executable/test blobs, preserve docs, proceed. | Claim equivalence without diff. | `git diff` paths G0; agent. |
| **D03** | `origin/main` advanced while B2 source is in flight | HARD STOP mutation | Compare merge base/affected code and report exact overlap for a maintainer decision. | Automatic rebase, merge main, overwrite. | G0; maintainer. |
| **D04** | Tracked worktree modification not owned by this fixup, or untracked file collides with required task path | HARD STOP mutation | Record exact paths and protect files; read-only investigation may continue. | Auto-stash, clean, reset, delete, overwrite. | G0; owner. |
| **D04a** | Only unrelated **non-conflicting untracked** foreign files are present | AUTO-RESOLVE | Record paths, leave them untouched and uncommitted, continue task-owned edits. | Stash, delete, add to F1 commit, infer ownership. | G0; agent. |
| **D05** | Frozen code symbols/heap structure differ materially from reviewed B2 | HARD STOP | Report file, exact diff, why plan no longer applies. | Adapt architecture by guess. | G1; maintainer. |
| **D06** | Numeric Ready request, global heap created once | AUTO-RESOLVE | Create one `OrdinalHeapAudit` for request; pass to numeric candidate handler. | Create audit per segment or candidate. | Source diff F1-INV01/02; agent. |
| **D07** | New private `&mut OrdinalHeapAudit` argument breaks existing B2 direct unit call sites | AUTO-RESOLVE | Update exactly the found callers mechanically; share one audit for consecutive calls in a test. | Change public API, drop tests. | Compile/red-green G2/G4; agent. |
| **D08** | First numeric candidate and `audit.checked=false` | AUTO-RESOLVE | Perform `ensure_ordinal_heap` once; only on success mark checked. | Assume `peek()` validates whole heap. | F1-U01/U02 G3; agent. |
| **D09** | Audit sees any `ordinal_sort=None` entry, even if worst is numeric | AUTO-RESOLVE error | Return exact `CorruptIndex("mixed ordinal and legacy sort entries")` **before** numeric comparison, no mutation. | Return `Ok` for a losing candidate, fallback. | F1-U01 G3/G4; agent. |
| **D10** | Audit already successfully checked same request | AUTO-RESOLVE | O(1) return; rely on proven numeric-only admission invariant. | Rescan K entries on every candidate/replace. | F1-U02/counters G3/G4; agent. |
| **D11** | Entry is inserted/replaced/evicted through existing d3c or heap helper | AUTO-RESOLVE | Reuse as-is; numeric handler supplies `Some`; no new helper or extra state. | Alter duplicate strategy or re-rank. | Source mutation inventory U18; agent. |
| **D12** | Any source path can insert `None` into numeric Ready heap *after* audit succeeds | **HARD STOP** | Report exact call path, mutation order, counterexample and smallest required design change. | Rely on stale verified bool, global scans, redesign d3c. | G1/G3; maintainer. |
| **D13** | No matched candidate or empty snapshot | AUTO-RESOLVE | Keep legacy empty result/no numeric comparison; zero/unused audit is allowed. | Force map prep or fabricated candidate. | U20; agent. |
| **D14** | Legacy/NotAvailable/ineligible request | AUTO-RESOLVE | No audit needed; follow original entire legacy path. | Partial numeric heap, fallback after processing. | B2-U09/U10/I03; agent. |
| **D15** | `experiment.check` detects duplicate before numeric comparison | AUTO-RESOLVE | Preserve existing duplicate typed error and heap; no new mutation. | Skip duplicate check or change precedence on healthy state. | U18; agent. |
| **D16** | A test of hidden mixed heap places a `None` at heap worst | AUTO-RESOLVE test correction | Fix **test fixture only** to require numeric worst and hidden `None` using exact `peek` assertion. | Call `ensure_ordinal_heap` alone and claim F1-U01. | F1-U01; agent. |
| **D17** | New F1 mixed-heap test passes on old code or never calls real handler | HARD STOP test acceptance | Inspect test harness and provide failing old-source witness before claiming repair. | Fake error, weaken assertion, rename test. | G4; maintainer if unresolvable. |
| **D18** | Real I07 source rows are not physically visited `k0,k1,k2` in order | HARD STOP affected I07 | Capture doc IDs/keys/evaluation ordering and explain source behavior; request narrow correction to fixture/plan. | Assume document order, lower K, claim false rejection. | G5; maintainer. |
| **D19** | I07 matched count=3, K=1, first two entries admitted and third `z×80` loses | AUTO-RESOLVE | Verify all exact §5.2 output/source and §5.3 counters, continue. | Claim rejection from truncated page alone. | F1-U03/I07; agent. |
| **D20** | I07 has only 2 matches for K=1 | AUTO-RESOLVE | Add third **source** row as prescribed; K+1=2 unchanged. | Set K=0 or shrink existing heap. | G5; agent. |
| **D21** | Long value has other byte length/lexical position | AUTO-RESOLVE | Use exactly 80 ASCII `z` and `"a"`, `"b"`, ensure `z` loses ASC. | Change runtime comparator, adjust assertions arbitrarily. | I07; agent. |
| **D22** | Tight 79-byte limit cannot open full segment container | AUTO-RESOLVE | Preserve U07 private bound-reader exact 79/80 proof and public I07 permissive proof separately. | Raise/lower hidden codec bounds; claim public typed 79 error. | G4/G5; agent. |
| **D23** | I07 outer checksum-valid corrupt term now produces exact B1 typed failure | AUTO-RESOLVE | Preserve unchanged adversary and good-byte check. | Delete negative case, accept `.is_err()` only. | I07; agent. |
| **D24** | A test failure is introduced by the exact allowed B2 change | AUTO-RESOLVE only if frozen repair | Make narrow correction inside the allowlist, retain red evidence, rerun invalidated gates. | Broader refactor, arbitrary test weakening. | G4/G7; agent. |
| **D25** | A test fails on unchanged source and appears pre-existing | DEFER AND CONTINUE | Reproduce on post-B1 main/equivalent source first; record classification and run independent gates. | Guess pre-existing or silently skip. | G7; maintainer if unresolved. |
| **D26** | A test is nondeterministic or external harness unavailable | DEFER AND CONTINUE | Preserve first failure, exact host/topology, retry only to classify when authorized, continue unrelated work. | Call flaky without evidence, fake PASS. | G7/G8; infrastructure. |
| **D27** | One local QA gate fails because of a narrow F1 compiler/clippy/test defect | AUTO-RESOLVE | Fix within frozen two production/test files, rerun invalidated checks; record source SHA. | Change toolchain/dependency to silence. | G7; agent. |
| **D28** | Existing CI is pending or a hosted service is temporarily unavailable | DEFER AND CONTINUE | Finish source/doc/evidence; mark G8/G6 pending, list run/job/head. | Manually dispatch, claim historic CI pass. | G6/G8; infrastructure. |
| **D29** | Ordinary CI finds a source-related failure in allowed files | AUTO-RESOLVE only if exact frozen design permits | Correct narrowly, run affected source gates, push ordinary follow-up commit and inspect new CI. | Change workflow or omit failed logs. | G7/G8; agent. |
| **D30** | Test-only counter/audit instrumentation appears in production hot path | HARD STOP delivery | Remove unintended instrumentation, rerun invalidated checks, audit release source. | Ship diagnostic log/atomic/telemetry. | G2/G7; agent, escalate if unresolved. |
| **D31** | Need to edit codec, segment limits, map, format, cursor, `d3c`, benchmark, Cargo, CI or remote/storage | HARD STOP affected work | Report exact cause and minimal required amendment; independent tests may continue. | Expand allowlist yourself. | G1/G9; maintainer. |
| **D32** | Desire to benchmark changed O(K) behavior now | DEFER AND CONTINUE | State structural complexity and defer measurement to B4. | Run benchmark acquisition or tune by time. | G9/B4; maintainer. |
| **D33** | Only docs/report/evidence change after tested source, with byte-identical executable/test tree | AUTO-RESOLVE | Compare protected path blobs `TESTED..FINAL`; retain QA provenance and verify final PR CI. | Rerun all suites solely for prose or invent CI result. | G7/G9; agent. |
| **D34** | Unlisted condition, semantic contradiction, undocumented API need, unknown resource/error behavior, or no matching rule | **HARD STOP** | Protect prior work, capture source/counterexample and request the smallest plan amendment. Continue independent work only if safe. | Design alternative, infer permission, relax tests. | Affected gate; maintainer. |

## 8. Ordered execution phases and exact gates

**Continuous authority applies to every phase; no further routine confirmation.** Record each phase outcome and applied decision row in the F1 report. A failed gate does **not** authorize using future green status as evidence that it passed.

### P0 — Preflight and independent correctness worksheet

Perform §1, then §3. Confirm the approved B2 source/report, **no foreign tracked changes or output-path collision** (unrelated untracked files are allowed under D04a), and exact PR identity. Record `main`, `HEAD`, `origin/dev/perf06-b2`, guide/plan blob IDs and G0. Count the existing `consider_ordinal_keyword_candidate` call sites; **at the reviewed source** these are the one production call (~L946) and two B2-U08 test calls (~L6909/~L6935). If others now exist, identify them; only mechanical updates under D07 are permitted.

### P1 — Adversarial red tests first

1. Introduce the F1-U01 mixed hidden-legacy test using the current handler before changing production. It must **fail** in the old handler because a losing candidate returns `Ok(())`; record exact negative assertion and source hash.
2. Introduce the F1-U03 three-row fixture and structural assertion before changing logic. Its new `owned_single_strings==2`, `numeric_compares==1`, `single_rejected_without_copy==1` are necessary to prove the third candidate loses. Record the first result; do not rewrite a passing oracle to force an artificial red.
3. The once-only audit counter test F1-U02 is added alongside the new implementation (it cannot compile until the audit exists). Compilation-red is an acceptable intermediate red, not feature acceptance.

### P2 — Production narrow correction

Implement §4.1–4.3 **only** in `search/unified.rs`, update direct handler call sites, preserve `d3c`/heap/accounting as-is. Add exactly one new private `bool` state per Ready request and one test-only `Cell` observation; do not rebind map, add a second segment guard or change `MixedEntry` layout.

### P3 — Local I07 correction

Implement §5.1–5.2 only in `tests/perf06_b2_ordinals.rs`. Preserve the existing I07 valid-container corruption case. Require actual physical doc-id ordering and full independent output/score/projected-field assertions. Add F1-U03 structural witness in `unified.rs` as §5.3 specifies.

### P4 — Focused red/green, once the implementation is complete

Run from repo root (real commands, capture exit statuses and logs with `set -o pipefail`; no accepted-B2 baseline suite before fixes):

```sh
cargo +1.98.1 test -p quervant-core --lib b2_f1_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_u08_u22_budget_failure_leaves_heap_unchanged_and_charges_match -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_u14_mixed_heaps_are_rejected_before_mutation -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_u16_materialization_tracks_competitiveness -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals b2_i07_losing_long_value_and_container_wrapped_corruption -- --exact --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b2_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b2_ordinals -- --test-threads=1
```

**Test-filter rule:** The test binary `b2_i07_losing_long_value_and_container_wrapped_corruption` is a top-level test in that integration file; `--exact` is permitted because it matches the full test name. For `--lib` tests Rust prints module prefixes, so use the non-exact filter shown. Verify selected tests actually ran and the counts are nonzero; `test result: ok` after `0 passed` does not satisfy a gate. Keep first red results and final green results in separate evidence files; do not overwrite failures.

Then rerun affected B1 and older PR15H borrowed-sort regressions (one time, not every checkpoint):

```sh
cargo +1.98.1 test -p quervant-core --lib b1_ -- --test-threads=1
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals -- --test-threads=1
cargo +1.98.1 test -p quervant-core --lib b_u -- --test-threads=1
```

For any test filter selecting zero tests, inspect current exact existing test names and rerun the correct named test instead; never mark zero tests PASS. Existing child helpers require actual child execution, not mere `ignored` registration. The existing B2 64-case generated differential remains mandatory and is covered by the full `b2_` invocation. No new property-based dependency is authorized.

### P5 — Single consolidated final QA ledger on frozen F1 executable/test tree

Do **not** rerun the healthy post-B1/main baseline first, and do not repeat full QA after each small code edit. Once all changed source/tests are committed or frozen for testing, execute the originally approved B2 §9.2 QA ledger **once**; capture command, exact source+worktree identity, compiler version, environment, exit code, test counts, log and coverage numerator/denominator. If later source/test changes invalidate a gate, rerun only necessary affected checks and the final ledger where required by the repository.

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

Do **not** assume original counts `2666`/`2711` are the new expected number; F1 adds new tests. Require all non-ignored tests to pass, no introduced regression, no new exclusions, and **≥85% line coverage** for default and all-features. Check the unchanged real adapter contract using the existing **untimed** command only if invalidated by scope or required by the unchanged B2 ledger:

```sh
cargo +1.98.1 test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml query_session_constructs_exactly_one_snapshot_for_the_whole_session
```

`bench --no-run` is compile-only; it does not authorize any benchmark acquisition. Host stability/idle observations are advisory and never block correctness QA. Do not change `.github/workflows/ci.yml` or start another RustFS container for F1.

### P6 — Documentation and delivery

1. Copy this complete approved plan **verbatim** to `docs/pr-artifacts/perf-06-b/PERF06B2_F1_DETAILED_FIXUP_PLAN.md`, record its SHA-256 and Git blob. Keep approved B2 detailed plan and its digest unchanged.
2. Append to `PERF06B2_EXECUTION_REPORT.md` a heading `# F1 independent-review correction` explicitly superseding only the overbroad G3/G4/G5 claims. Preserve prior F1-causing negative evidence and original QA log. Record exact F1 source identities, detailed invariant worksheet, code changes, test red/green identities, full-audit count, K+1 input, decision rows, test/CI results and residual risks.
3. Put compact, relevant logs only under `docs/pr-artifacts/perf-06-b/evidence/b2-f1-*` (preflight, source/diff, focused red/green, final QA, coverage, CI, review disposition). No `target/` payload, invented test trace, benchmark result, secrets, or huge binary artifact.
4. Compare the actual new diff against F1 starting head and against accepted main. Require **no** changes outside the allowlist in §9. If a protected file changed due to a formatter, revert only task-owned changes after verifying no foreign work; do not reset user state.
5. Commit and push to the **same** `dev/perf06-b2` branch ordinarily (`git push origin dev/perf06-b2`); inspect PR #127. Keep draft and unmerged. Do not open a second PR, merge B2, approve your own changes or start B3/B4.
6. Inspect the repository's existing ordinary `pull_request` CI run for the new executable/test head. Require terminal success of exactly the existing five mandatory job groups (`rust`, `msrv`, `rustfs`, `benchmark-adapter-contract`, `python-benchmark-framework`) and proof the hosted RustFS job actually ran `b1_r01_cold_shared_ordinals_and_pit ... ok`. A pre-F1 success such as run `45559725417` cannot establish G8 for the changed F1 executable.
7. If the final pushed commit modifies only prose/logs after a fully tested source and ordinary CI, use D33: verify `TESTED..FINAL` executable/test/workflow/manifest diffs are **empty**, preserve source-specific QA and verify the actual final-head CI. Do not report G8 green while pending or assume CI event head equals a previous source.

## 9. Exact file allowlist and protected ownership

**Permitted source/test files (existing):**

| Path | Sole authorized changes |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | Add `OrdinalHeapAudit` private `bool` state, once-only validation; pass one audit into existing numeric handler; remove its repeated competitive-branch scan; add `#[cfg(test)]` `full_heap_audits` observation and F1-U01/U02/U03 tests; mechanically update the two existing U08 numeric handler calls. No change to scoring, d3c, comparator, cursor, heap charge, B1 preparation/eligibility, or legacy candidate code. |
| `crates/quervant-core/tests/perf06_b2_ordinals.rs` | Add exactly the third matching input row to I07 and full input-derived/order/score/projection/K+1 assertions; **preserve** its corrupt-container half and I01–I06/I08 tests. |

**Permitted documentation and evidence:**

- NEW `docs/pr-artifacts/perf-06-b/PERF06B2_F1_DETAILED_FIXUP_PLAN.md` — verbatim this plan, hashed.
- EXISTING `docs/pr-artifacts/perf-06-b/PERF06B2_EXECUTION_REPORT.md` — additive F1 correction; no erasure of previously failed/unverified claims.
- NEW files under `docs/pr-artifacts/perf-06-b/evidence/b2-f1-*` — source identity, focused tests, QA, coverage and CI only.
- PR #127 description/update stating pending G10 and F1 corrected gates (no new PR or change to draft flag).

**Everything else is protected:** `crates/quervant-core/src/search/typed_compare.rs`, `search/execute.rs`, `search/typed.rs`, `search/unified_cursor.rs`, `search/memory.rs`, `search/batch_meter.rs`, `crates/quervant-core/src/index/**`, `crates/quervant-core/src/segment/**` including `column.rs`, `contract/**`, `remote/**`, `storage/**`, objectstore/distributed/vector/service, `Cargo.*`, toolchain files, `.github/workflows/**`, `benchmarks/**`, `tests/perf06_b1_*`, the historical frozen fixture, all A4/A5/A6 and B1 evidence, original B2 detailed plan, `AGENTS.md`, authoring guide, architecture/roadmap outside this additive report. Neither a formatter nor an asserted test convenience authorizes expanding scope. Apply D31 on any genuine dependency.

Source-identity proof must cover **all protected paths**, not only `crates/`: record changed paths and `git diff --check`, compare `TESTED..FINAL` for source/tests/CI/manifest/benchmark, and list actual CI head SHA. On a **docs-only** delivery commit, unchanged executable/test tree is required for source QA reuse.

## 10. Acceptance gates — exact pass conditions

| Gate | Passing evidence | Not-accepted cases |
|---|---|---|
| **G0 — preflight** | Correct PR/branch/base, no foreign tracked changes or task-output collision, harmless untracked items recorded and preserved, admitted source and original plan hash recorded. | Conflicting/dirty tracked source, merged/wrong PR, new executable drift not reconciled. |
| **G1 — pre-implementation invariant worksheet** | F1-INV01..07 linked to current symbols, positive and counterexample tests, relevant decision rows; no open design choice. | Generic assurance or missing mixed-heap counterexample. |
| **G2 — implementation** | One `OrdinalHeapAudit` request-local bool; full scan once on first numeric handler invocation **before comparison**; no repeated scan, no new map/heap/format, existing candidate/charge/duplicate paths intact. | Peek-only check, hidden legacy unobserved, O(K) scan each candidate or competitive entry. |
| **G3 — unit correctness** | F1-U01 exact hidden legacy/different worst, exact error and heap unchanged, positive clean arm; F1-U02 one full audit despite 1,000 competitive entries; F1-U03 real third 80-byte loser without owned copy; original U08/U14/U16/U18/U22 positive/error oracles. | New test only calls `ensure_ordinal_heap` helper or counts top page without owned-copy witness. |
| **G4 — local integration** | I07 real FsDirectory three matched docs `k0,k1,k2`, K1/K2/K3 exact results, `total_hits=3`, real physical order, full projection/score-bit parity, unchanged valid-container corruption refusal; all B2 I01–I08 pass. | Still only two docs, K+1 not filled, public 79-byte result invented, corrupt branch dropped. |
| **G5 — regression/semantics** | Existing B2 64-case, B1 64-unit and I01–I08, PR15H borrowed tests, PIT/continuation, MultiOne, duplicate modes, exact charge and schema/codec baseline still pass. | Failure hidden in a green subset. |
| **G6 — final QA** | Every §8 P5 command executes on final executable/test source, including MSRV, default/all-feature tests, `cargo llvm-cov` line coverage ≥85%, adapter contract as applicable, 108-script gate and diff-check. | Old-source logs presented as F1 result or coverage exclusions. |
| **G7 — hosted real provider** | Ordinary unchanged CI `rustfs` job passes with **actual** `b1_r01_cold_shared_ordinals_and_pit ... ok` under F1 source. | Historical old-source run, mock provider, skipped tests. |
| **G8 — final-head CI** | All five required jobs terminal `success` for F1 executable/test source or verified docs-only final head; exact run IDs/SHA in report. | Pending/failed/missing CI still marked PASS. |
| **G9 — delivery/traceability** | Same draft PR #127, allowlist proof, additive report, matrix ledger, red/green evidence, tested/final/remote SHA, no performance claim. | Untracked foreign file removed, new PR, parent plan altered, source not pushed. |
| **G10 — independent maintainer acceptance** | Only a separate maintainer/reviewer can accept/merge B2 after the review of this F1. | **Always OPEN for the coding agent.** |

**Final disposition:** use `PERF06_B2_F1_READY_FOR_INDEPENDENT_REVIEW` only when G0–G9 all pass. G10 stays open. If CI or external verification remains pending, report `...IMPLEMENTED_VERIFICATION_BLOCKED`, never green. An unresolved HARD STOP uses `...INCOMPLETE_STOP_<RULE>` with the smallest next required decision and unaffected work/evidence still complete.

## 11. Required execution report and adversarial self-review

The appended F1 execution report must contain **all** of the following with concrete values, not prose-only PASS claims:

1. PR #127, branch/draft/base, accepted `main`, F1 start, source-diff pin, tested source and final remote head SHAs. Verify byte-identical protected source between tested and final when using docs-only QA reuse.
2. The F1-INV01..07 worksheet and path/method mapping; explicit confirmation that the only production mutation is the request-local audit in `search/unified.rs`.
3. The full **initial failing** F1-U01 negative test, showing that the old handler incorrectly returned `Ok(())` for a losing candidate with a numeric worst and hidden legacy entry. Include the corrected exact error and proof no numeric compare/owned copy/mutation occurred.
4. F1-U02 structural witness: 1,000 candidates, K=10 ascending/descending, exact **one full heap scan** each eligible request, no scan for an ineligible request; existing result, score, count and competitive-admission properties unchanged.
5. I07 and F1-U03 fixture inventory: `k0="a",k1="b",k2="z"×80`, one v2 segment, doc IDs0–2 and K+1=2, third doc noncompetitive; `numeric_candidates=3`, `numeric_compares=1`, `owned_single_strings=2`, `single_rejected_without_copy=1`; `total_hits=3`; K=1/2/3 keys and next-cursor status. Full legacy comparison and input-derived values.
6. Proof the original I07 corrupt-container negative still runs and fails exactly with `InvalidUtf8 { context:"keyword" }` on the rebuilt valid outer envelope; original immutable source bytes are unchanged.
7. The honest 79/80 statement: exact error established by U07 bound accessor, **not** by the public I07 query because its container-open ceiling prevents the per-value threshold from being reached.
8. Every command, count, pass/fail/ignored, coverage ratio, compiler version and file path from the consolidated final QA; first red and final green tests kept separately; direct `b2_f1_` test inventory must contain all three new named functions.
9. Full five-job ordinary CI with run ID, head SHA and terminal status; real hosted RustFS B1-R01 execution; no manual extra performance campaign.
10. List every applied D rule and any blocked/unlisted condition. Identify residual risks: B1 optional fallback, legacy/mixed segment limitations, MultiOne full decoding, B4 warm-qualification pending, no cross-snapshot stable ranks, no B3 identity changes, A6 remote compaction unqualified. The audit is a one-time proof plus inductive construction invariant; it is not a memory-corruption detector for arbitrary post-proof mutation outside the approved code.

### Final adversarial reviewer checklist

- [ ] Test **actually drives `consider_ordinal_keyword_candidate`** with a **numeric worst** and a **hidden `None`** on a losing candidate. It does not simply call `ensure_ordinal_heap` in isolation.
- [ ] A `CorruptIndex` error occurs **before `ordinal_candidate_order`**, with zero numeric comparisons and zero heap changes.
- [ ] The audit is created once per Ready request and not re-created per segment/document; its successful full scan is executed at most once.
- [ ] Default and experimental duplicate policies cannot insert a `None` in a Ready request after audit; this is confirmed by source inspection and existing tests.
- [ ] No new per-candidate O(K) validation; the reviewed post-comparison full scan is removed.
- [ ] The first **two** actual matched I07 candidates occupy a **K+1=2** heap before the **third** loses; a K1 page with two matched documents is not accepted as proof.
- [ ] The 80-byte losing Single still undergoes its original logical decode admission and duplicate check; no owned string is produced for it, and all 3 matching documents count.
- [ ] Exact independent output, complete projection, score bits and cursor semantics remain unchanged in both numeric and legacy paths.
- [ ] Corrupt unselected v2 payload is rejected at the validated container boundary; original historical and RustFS paths remain intact.
- [ ] No changed `typed_compare`, B1 codec/map, source format, `d3c`, public APIs, adapter, benchmark results, Cargo or CI workflow.
- [ ] No timing/RSS/index-size win is claimed; B4 remains the warm-performance qualification owner.
- [ ] G0–G9 source-specific acceptance evidence is complete, G10 maintainer review remains OPEN, and PR #127 remains draft/unmerged.

---

**Final instruction to the low-reasoning coding agent:** Follow the exact private audit design, exact three-document K+1 adversary, ordered phases, allowlist and D01–D34 decision matrix (including D04a). Continue autonomously after approved checkpoints. If reality does not match a listed trigger or the prescribed design cannot safely preserve the invariants, HARD STOP rather than substitute an algorithm, enlarge the scope, relax a test, create a new PR, or approve/merge. Provide the final source identities and proof, not a prediction of correctness.
