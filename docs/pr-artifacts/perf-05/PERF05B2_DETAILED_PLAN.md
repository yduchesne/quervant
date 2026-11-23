# PERF-05-B2 — Reuse Verified Effective-Live Metadata Across Query Stages

**Detailed, execution-ready implementation contract for a low-reasoning coding agent — v1.0, 2026-11-22**  
**Repository:** `yduchesne/quervant`  
**EXISTING branch / PR:** `dev/perf05-physical-execution-series` / [PR #117](https://github.com/yduchesne/quervant/pull/117) — **do not create another branch or PR**  
**Inspected branch head:** `668206ba1ba94fda696fb9f395b6b65023b0e1cf` (B1 implementation, not necessarily CI-complete)  
**Inspected accepted main:** `9775bfca4c58a27e65ca28c1d705efad00a65ec8` (PERF-02-B merged)  
**Authority:** `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `AGENTS.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md`, and `docs/pr-artifacts/perf-05/PERF05B_IMPLEMENTATION_REGISTER.md`.  
**Status:** **DESIGN / INSTRUCTIONS ONLY.** Nothing in this document establishes that B2 was implemented, verified or accepted.

---

## 0. Execution contract — read first

**One dominant change:** `score::compute_stats()` already scans every effective-live bitmap to compute the total live-document count. It then scans a bitmap again for every persisted-norm scoring field to determine `all_live`. Later, the eligible postings-driven `execute::evaluate_lexical_with()` **recounts the same bitmap** to reproduce the legacy per-live-document *logical* examination charge. B2 retains a **query-local, per-segment summary** from the first scan and uses that summary in both places. It eliminates the redundant physical bitmap recount **without eliminating any logical work charge, cancellation poll, scoring computation, corruption check or semantic fallback**.

**Frozen implementation choice:** Store an immutable, compact `Vec<SegmentLiveSummary>` **inside the existing `SnapshotStats` value** returned by `compute_stats`. Each entry contains `(slot_count: usize, live_count: u64)` and is indexed by the existing segment ordinal. The counts are computed during the **existing initial count pass**; no extra per-document scan is introduced. The existing `compute_stats()` signature, `evaluate_lexical_with()` signature and `UnifiedSearcher` call site are **unchanged**. `execute.rs` reads the verified count through one `SnapshotStats` method and retains the old helper's cancellation-poll sequence **without iterating bitmap elements**. No `ReaderSnapshot` change, cross-query cache, extra ownership of bitmap bytes, new public API, or parallel/streaming executor is authorized.

**Continuous execution authorization:** Once authorized to execute this approved B2 plan, perform **all prescribed phases** from preflight through tests, documentation and push **without routine reconfirmation**. After a passing phase or an exactly applicable AUTO-RESOLVE matrix row, continue. DEFER AND CONTINUE means complete safe independent work while accurately recording pending gates. HARD STOP means halt the affected work and avoid improvisation; halt the whole B2 implementation if the source proof or data-flow design is affected. Never treat a progress checkpoint as a new permission request. An unforeseen case absent from §14 is **HARD STOP** for any dependent code.

**Host:** **Assume idle and benchmark-ready as directed.** Do not seek confirmation, run an idle probe or infer other environmental guarantees. **No timed benchmarking, `quervant-bench run`, `perf record`, `perf script`, CPU-sampling, microbenchmarks, A/A, A/B or profiler preflight during B2.** These acquisitions are **exclusively PERF-05-C**. Normal compiler/test/coverage/Clippy/`cargo bench --no-run` (compile-only) activities are QA, not benchmarking.

**CI:** **Do not wait for B1 CI** or block local B2 work merely because PR #117's prior workflow is pending. B2 must pass its local gates and document CI/RustFS truthfully. No additional CI triggers, polling loops or workflow dispatches. Do not assert B1 was finally accepted by CI if it has not been verified. Never merge PR #117, change `main`, force-push, start B3, or claim PERF-05 is complete.

**Scope ownership:** All changes and reports go to the **same branch and draft PR #117**. No production modification outside `score.rs` and `execute.rs` (including their in-file test modules). Detailed plan and execution report are the only other tracked B2 files (§11). Preserve all B1 production and test behavior.

---

## 1. Current, source-verified implementation and exact redundancy

These anchors were examined on the **B1 HEAD** stated above. The agent **must recheck them on the live branch**, not rely on line numbers alone.

| Source ID | Existing file / symbol | Verified facts; permitted change |
| --- | --- | --- |
| S01 | `crates/quervant-core/src/search/score.rs::compute_stats()` (~lines 207–415) | Initial `live.iter().try_fold()` counts `true` flags in each `Rc<Vec<bool>>`, checked-adds into global `n`. This **first pass stays**. Replace the fold with a loop that also retains each count; preserve segment order, the exact checked sum, and its `SearchError::ResourceLimit` overflow behavior. |
| S02 | `score.rs::SnapshotStats` (~105–113) | Currently contains `fields: BTreeMap<u32, FieldStats<'a>>`. Extend with **private** `segment_live: Vec<SegmentLiveSummary>`; retain the public-to-crate `fields` and `field()` unchanged. Add exactly one checked accessor. |
| S03 | `score.rs::compute_stats()` persisted-norm path (~251–321) | For each scoring field/segment after `work.check_cancelled()` and the existing `reader.doc_count()` geometry check, `segment_live.iter().all(|flag| *flag)` scans the bitmap again. Replace **only this test** with the precomputed count-vs-slot-count equality. Preserve both the all-live fast path and partial-live recomputation/postings validation exactly. |
| S04 | `search/execute.rs::effective_live_examination_count()` (~992–1022) | Currently: `meter.check_cancelled()`, iterate `live.chunks(4096)`, **inspect every flag and count**, `meter.check_cancelled()` after each chunk, final check, return count. Retain the **same number and order** of checks, but consume the precomputed count and do not inspect flags here. |
| S05 | `execute.rs::evaluate_lexical_with()` (~1955–2068 on B1) | Eligible term runtime shape guard occurs **before** the helper; it uses the `stats: &SnapshotStats` already passed in. Extract verified metadata for the *same* `segment_index` and `live.len()`, then call the revised helper. Do not change the function's signature, postings decoder, predicate loop, matched set, scorer or return vector. |
| S06 | `search/unified.rs::collect_mixed()` (~619–1013) | Builds one vector of effective-live `Rc<Vec<bool>>`, calls `compute_stats(&readers, &live, …)` **before** segment iteration, passes the same segment ordinal and live bitmap slice into `evaluate_lexical_with()`. This is the identity/provenance link for the summary; **leave this file unchanged in B2**. |
| S07 | `search/score.rs` existing in-file unit tests | Real legacy/field-norm fixtures: `legacy_segment_field_length_budget_is_enforced`, `live_bitmap_excludes_dead_documents_from_stats`, `mixed_legacy_and_norms_segments_aggregate`. Reuse them and extend with B2 tests (§7), without changing expected semantics. |
| S08 | `unified.rs::phase4_tests` | Existing `phase4_u10_u11_u12_work_charge_parity` uses an **independent eligible-vs-`And` oracle** and exact/one-below work limits. U14 tests cancellation, U16 spans 4097 document slots, B1 tests preserve direct/fallback parity. Execute these unchanged. |
| S09 | `search/work.rs::MixedWorkMeter::check_cancelled()` | A direct call observes the provided cancellation object, but does not mutate work counters. The original S04 performs one leading, one per **physical 4096-slot chunk**, and one final cancellation check. Preserve all checks without introducing extra polls in `compute_stats`. |
| S10 | `search/execute.rs::execute_search()` and `unified.rs::select_keys()` | **Sibling consumers** of `compute_stats()` also receive the augmented `SnapshotStats`; no observable behavior changes are authorized. Only the eligible unified-scoring path reads the new counts for examination accounting. |
| S11 | `search/execute.rs::build_leaf_data` / `score_segment` | Entire postings decoding, term-frequency scoring, error ordering, corruption checks, candidate budget and lifecycle remain unchanged; B2 does **not** implement B3/B4. |
| S12 | Existing PERF-05-B1 HEAD | `collect_mixed` callback returns a proven `true` for strict single positive-term postings, retains the runtime shape guard and all work/cancellation behavior. B2 must preserve B1's fix and its test-only membership observer. |

**Identity argument:** The new `SnapshotStats` is a **request-local value** built from `live`, itself sourced from one immutable `ReaderSnapshot`. Its summaries do **not** outlive the query and contain numbers, not borrowed bitmap pointers or references to mutable state. The same `segment_index` and bitmap length are used for lookup in `evaluate_lexical_with`. A mismatch is a fail-closed internal inconsistency, never an excuse to recount, fall back silently or ignore a corrupt segment.

**Preservation argument:** This change removes *data rereads*, not approved *work*. Original `meter.charge_lexical(live_count)` must still charge **N** effective-live docs irrespective of postings count M. The original cancellation helper's check-call sequence must stay **1 + ceil(slot_count / 4096) + 1** on successful passage. No new polls during the initial count. Counts and all-live classification are exact if and only if the first initial pass counted the same immutable bitmap.

**Space tradeoff:** One short `Vec` with **O(segment-count)** elements (two machine words per segment) is added inside the already query-local statistics state to eliminate further **O(total bitmap slots × repeat consumers)** traversals. The vector is fallibly allocated and dropped with `SnapshotStats`; no persistent or shared cache and no full-N/M object is created. This is an O(segments) statistics-metadata allocation, in the same setup scope as existing unmetered `FieldStats` maps/vectors; it does **not** change modeled candidate reservations or batch work charges. If source review shows that new statistics metadata must instead be explicitly charged under a strict peak-memory contract, **HARD STOP** for an architecture amendment rather than silently omit that charge. Allocation failure must yield a typed `SearchError::ResourceLimit`, not panic or partially publish results. **Do not claim zero new allocation or identical error order when a genuinely new allocation itself fails.** That exceptional resource error is explicitly approved; all pre-existing work/budget/corruption and cancellation boundaries for valid allocation are unchanged.

---

## 2. Scope and prohibitions

### Authorized

1. Add the immutable, private per-segment summary and checked accessor to `score.rs::SnapshotStats`.
2. Use the **existing** initial bitmap count pass to populate the summary and compute `n` exactly as before.
3. Replace repeated persisted-field `all_live` bitmap scans with summary equality.
4. Replace the eligible term's examination recount with the cached segment count while keeping check/poll/charge locations unchanged.
5. Add focused in-file deterministic and adversarial Rust tests; reuse existing local and remote integration tests.
6. Commit plan and evidence report under `docs/pr-artifacts/perf-05/` on PR #117.

### Never authorized in B2

- Changing the B1 callback or eligibility, lexical query planner, postings iterator, duplicate prefilter, `LeafData::matches`, score/BM25 equation, matched `BTreeSet`, scored `BTreeMap`, scored `Vec`, candidate heap or sort values.
- Moving or eliminating work charges, corruption detection, full-document validation, cancellation checks, read-only snapshot semantics, or changing the limits/API defaults.
- Persistent bitmap caches, `ReaderSnapshot` or segment format changes, RustFS/Directory changes, new feature flags/dependencies, unsafe code, threads, atomics, logging or production telemetry.
- Refactoring sibling `execute_search()` or `select_keys()`, changing batch semantics, modifying CI, tooling, benchmark configuration/result files or profiling code.
- Running any timed performance acquisition before PERF-05-C, or waiting indefinitely for existing hosted CI.

**B2 is not a performance verdict.** No gain is measured or claimed. Adoption of the entire PERF-05 implementation will be governed by the final qualified warm A/B in PERF-05-C.

---

## 3. Preflight, branch reconciliation and continuous source verification

From repository root, in sequence. Record exact outputs in the execution report.

```bash
set -euo pipefail
# Inspect first; never stash/reset/clean/discard another person's files.
git status --porcelain=v1 --untracked-files=all
# Tracked changes, index conflicts, or unknown untracked paths => HARD STOP.
# Exception P02 below allows ONLY known previously generated untracked artifacts.

git fetch origin main dev/perf05-physical-execution-series
git switch dev/perf05-physical-execution-series
git pull --ff-only origin dev/perf05-physical-execution-series

git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --porcelain=v1 --untracked-files=all
# B1 implementation MUST be an ancestor. No reset/rebase/force push.
git merge-base --is-ancestor 668206ba1ba94fda696fb9f395b6b65023b0e1cf HEAD
START_SHA=$(git rev-parse HEAD)
printf 'B2_START_SHA=%s\n' "$START_SHA"

rg -n 'struct SnapshotStats|fn compute_stats|all_live|live.iter\(' \
  crates/quervant-core/src/search/score.rs
rg -n 'EXAMINATION_COUNT_CHUNK|effective_live_examination_count|fn evaluate_lexical_with' \
  crates/quervant-core/src/search/execute.rs
rg -n 'single_term_postings_eligible|evaluate_lexical_with|postings_candidate_eligible' \
  crates/quervant-core/src/search/unified.rs
rustc --version
cargo --version
rustup toolchain list
```

**Preflight allowlist for untracked generated files:** Prior B1 recorded `.coverage`, paths under `benchmark-results/`, and paths under `benchmarks/quervant_bench.egg-info/` as pre-existing local-only artifacts. If the **only** nonempty `git status --porcelain` rows are `??` paths **strictly** beneath those three known prefixes, classify P02 and continue **without altering `.gitignore`, `.git/info/exclude`, the worktree or the index**; stage files by exact path later. If the previous agent already hid those rows in `.git/info/exclude`, record that fact but **do not modify it**. If **any tracked change** or another untracked path exists, HARD STOP. Do not automatically delete or hide generated content.

**CI continuation:** Do not require a green B1 workflow to start; annotate it as `B1_CI_PENDING` or its observed actual status, but do not claim B1 independently accepted. Reconcile any known B1 source changes: only the exact B1 logic is expected. If the current branch contains any B2 code already or key S01–S12 facts do not hold, HARD STOP for implementation and request an updated plan.

**Pre-implementation correctness gate:** Before editing production, write down the invariant→test trace (§6–§8), inspect the S01–S12 source, and confirm the same `live` vector is handed to `compute_stats` and the evaluation loop without mutation or re-acquisition. Confirm that the old cancellation helper has exactly **leading, per-chunk, trailing** calls. If any proof fails, STOP—do not implement a guessed cache architecture.

---

## 4. Exact design: `score.rs` owns the query-local live summary

**Only production change #1 — `crates/quervant-core/src/search/score.rs`.** Do not invent an alternative cache or wrapper type.

### 4.1 Private representation and checked accessor

Immediately before `SnapshotStats`, introduce this private, immutable metadata value (the names and fields below are fixed for B2):

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct SegmentLiveSummary {
    slot_count: usize,
    live_count: u64,
}
```

Extend existing `SnapshotStats<'a>` **without changing its `fields` visibility or the existing `field()` method**:

```rust
#[derive(Debug)]
pub(crate) struct SnapshotStats<'a> {
    pub(crate) fields: BTreeMap<u32, FieldStats<'a>>,
    segment_live: Vec<SegmentLiveSummary>,
}

impl<'a> SnapshotStats<'a> {
    pub(crate) fn field(&self, field_id: u32) -> Option<&FieldStats<'a>> {
        self.fields.get(&field_id)
    }

    pub(crate) fn verified_segment_live_count(
        &self,
        segment_index: usize,
        bitmap_slots: usize,
    ) -> SearchResult<u64> {
        let Some(summary) = self.segment_live.get(segment_index) else {
            return Err(SearchError::CorruptIndex {
                detail: "snapshot live summary segment index is missing".to_owned(),
            });
        };
        if summary.slot_count != bitmap_slots {
            return Err(SearchError::CorruptIndex {
                detail: "snapshot live summary slot count mismatch".to_owned(),
            });
        }
        Ok(summary.live_count)
    }
}
```

The `verified_segment_live_count` method must **not** recalculate, allocate, borrow/reopen a segment or issue a work charge. It is a checked constant-time lookup. Its two error strings are specified; do not silently fall back to recounting or panic.

### 4.2 Reuse the existing first complete bitmap pass

Replace **only** the existing initial `let n: u64 = live.iter().try_fold(...)` with this exact, equivalent counted-and-retained loop:

```rust
let mut live_summaries: Vec<SegmentLiveSummary> = Vec::new();
live_summaries
    .try_reserve_exact(live.len())
    .map_err(|_| SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: live.len() as u64,
    })?;
let mut n = 0u64;
for bitmap in live {
    let count = bitmap.iter().filter(|flag| **flag).count() as u64;
    n = n.checked_add(count).ok_or(SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    live_summaries.push(SegmentLiveSummary {
        slot_count: bitmap.len(),
        live_count: count,
    });
}
```

This preserves **exactly one initial per-segment pass**, the order of segment accumulation, `count()` behavior and the checked overflow error. It does not call `work.check_cancelled()` or charge additional work: the original count fold did neither. Do **not** use `saturating_add`, bitmap `len` as a substitute for live count, an atomically cached shared value, or a second scan. Do not alter `FieldStats` or any BM25 calculation.

### 4.3 Replace only the redundant persisted-norm `all_live` scan

In `compute_stats`, inside the current `Some(norms)` branch, **leave** the existing `let segment_live = &live[segment_index];` and its preceding `work.check_cancelled()` and `reader.doc_count()` geometry check untouched. Replace exactly:

```rust
let all_live = segment_live.iter().all(|flag| *flag);
```

with:

```rust
let all_live = live_summaries[segment_index].live_count
    == live_summaries[segment_index].slot_count as u64;
```

Here `live_summaries` is the **local vector populated in §4.2**; `segment_live` remains the existing `&Rc<Vec<bool>>` for the unchanged partial-live branch. **No helper or duplicate summary is needed.** If these bindings cannot be used exactly because source has changed, **HARD STOP** rather than choosing another architecture.

At the end of `compute_stats`, replace exactly `Ok(SnapshotStats { fields })` with:

```rust
Ok(SnapshotStats {
    fields,
    segment_live: live_summaries,
})
```

The existing `if all_live { … } else { … }` branches remain unchanged. In particular, the **partial-live branch still traverses live docs, reconstructs exact live term frequencies where required and verifies every applicable posting**. The legacy-without-norms path remains untouched. There is no fast path based on “usually all live.” The count equals slot count **iff** all flags are true, including the empty bitmap case.

### 4.4 No other `score.rs` production edits

Do not modify `compute_stats` arguments, returned field-statistic values, `FieldStats::length`, `FieldStats::doc_freq`, `score_segment`, query-term dictionary lookup, read/write codecs, stale snapshots or field-norm structures. Query scope is controlled by the existing `SnapshotStats` value; no global cache or extra `Rc` ownership is added.

---

## 5. Exact design: `execute.rs` reuses the count and preserves polling

**Only production change #2 — `crates/quervant-core/src/search/execute.rs`.** All candidate-predicate, scoring, matched collection, budget and aggregation logic remains untouched.

### 5.1 Helper signature and body

Change the private helper to accept the precomputed count from the same segment:

```rust
/// Reuse the query-local, verified effective-live count for the unchanged
/// logical examination charge on the strict postings-driven path.
///
/// Poll exactly as the previous bitmap recount: once before processing,
/// once for each physical 4096-slot chunk, and once afterward. No bitmap
/// element is read here; `compute_stats` already counted the same immutable data.
fn effective_live_examination_count(
    live: &[bool],
    verified_live_count: u64,
    meter: &MixedWorkMeter<'_>,
) -> SearchResult<u64> {
    meter.check_cancelled()?;
    for _ in live.chunks(EXAMINATION_COUNT_CHUNK) {
        meter.check_cancelled()?;
    }
    meter.check_cancelled()?;
    Ok(verified_live_count)
}
```

**No alternative:** Do not remove the loop entirely, change `EXAMINATION_COUNT_CHUNK`, turn it into a different number of checks, add unsafe optimizations or relocate the charging step. The new loop is over **chunks**, not individual bitmap elements. It must not return `live.len()` instead of the verified live count; dead slots must not be charged.

### 5.2 Exactly one call-site edit

Within `evaluate_lexical_with`, **after** the existing strict `LeafData::Term { terms.len() == 1 }` runtime guard, replace only:

```rust
let live_count = effective_live_examination_count(live, meter)?;
```

with:

```rust
let verified_live_count = stats.verified_segment_live_count(segment_index, live.len())?;
let live_count = effective_live_examination_count(live, verified_live_count, meter)?;
```

Keep the following lines in their original position:

```rust
if live_count > 0 {
    meter.charge_lexical(live_count)?;
}
meter.check_cancelled()?;
```

**Failure-order qualification:** The lookup is in-memory and checked, but a mismatch would produce a typed `CorruptIndex` *before* the helper's first cancellation check. This mismatch is impossible for the verified same-query source path S06. A test must confirm the error on an explicitly fabricated mismatch; no new fallback is authorized. For valid queries all cancellation polls and charge order remain the same, and **only physical bitmap recounting disappears**.

### 5.3 No signature changes to the public or shared evaluator

Do **not** change `evaluate_lexical_with` parameters, caller closure, `build_leaf_data`, `LeafData`, `score_segment`, `visit_lexical_membership_with`, `execute_search`, any unified files, `MixedWorkMeter`, `WorkCharge` or `Cancellation` APIs. B1's proven shortcut remains intact.

---

## 6. Invariant and cross-component traceability

| Invariant | Must remain true | Source steps | Acceptance tests |
| --- | --- | --- | --- |
| I01 | Exactly the number of `true` effective-live flags in each original segment, even when deleted or entirely dead; no `len` substitution | §4.2, §4.3, §5 | B2-U01/U02/U03, phase4 U16 |
| I02 | Snapshot-wide `FieldStats.n` and per-term `df`, `avgdl`, lengths and returned scores unchanged for norms, legacy and mixed segments | §4.2–4.4 | B2-U01/U02, score existing live/mixed tests, B1 tests, b_tests |
| I03 | `all_live` true **iff** count == bitmap slots, including empty slice; partial-live branch executes exactly as before | §4.3 | B2-U01/U02/U03, legacy tests |
| I04 | The helper no longer physically inspects bitmap flags; eligible path only reuses computed count; generic fallback unchanged | §5 | B2-U04/U05, static source-diff audit, phase4 U06–U08 |
| I05 | `meter.check_cancelled()` count/order within the examination helper remains **1 + ceil(slots/4096) + 1** | §5.1 | B2-U06 with old-helper reference, phase4 U14 |
| I06 | Logical per-live examination charge, scanned occurrence charge and exact/one-below work limit remain identical | §5.2 | B2-U07, phase4 U10–U12, pr15e_b1 |
| I07 | Already decoded postings are validated and complete; corruption of unselected data remains detectable and type/order of errors unchanged under successful allocation | §5.3 | existing phase4 / pr13_oracle and full all-features QA |
| I08 | Exact `total_hits`, ordered keys, score **bits**, projections, duplicate detection, K boundary and sort/cursor semantics remain unchanged | §4–5 | B2-U08, B1, b_tests, pr13_oracle |
| I09 | Query-local immutable metadata cannot be used with a different segment ordinal or bitmap geometry; wrong ordinal/slots fail typed | §4.1, §5.2 | B2-U03 |
| I10 | No persistent segment/index/manifest/RustFS changes; sibling `execute_search`/`select_keys` paths retain behavior | §2, §4–5 | pr06_local_integration, pr13_oracle, relevant real RustFS CI |
| I11 | No global cache, unsafe operations, runtime configuration, extra bitmap pass, or performance instrumentation added | §4–5, §11 | diff, grep, fmt, clippy and code review |
| I12 | New metadata storage is O(number of segments), safely fallible and dropped with `SnapshotStats`; no false “no allocations” claim | §4.2 | B2-U03, code review |
| I13 | B1 shortcut (eligible=0 redundant binary searches; fallback unchanged) is preserved on final HEAD | source untouched | existing B1 red/green (green only), phase4 and b_tests |
| I14 | Batch, typed/multi-term/phrase, legacy and multi-segment requests do not silently get a new query fast path | §4–5 | B2-U02/U08, phase4 eligibility and pr15e_b1 |

**Cross-component impact:** 

| Component | Production change | Reason / mandatory proof |
| --- | --- | --- |
| `search/score.rs` | YES, private summary only | Holds count from old initial scan; field/legacy branches identical |
| `search/execute.rs` | YES, private helper and eligible call | Reuses summary and retains original cancellation/charge semantics |
| `search/unified.rs` | NO | Same readers/live/segment ordinal and B1 callback; full fixture tests |
| `search/work.rs`, `typed.rs` | NO | Logical meter and cancellation API unchanged |
| ReaderSnapshot / segment codec / local FsDirectory / RustFS | NO | No on-disk state, new cache or remote I/O; local/remote existing suites |
| Contract result/cursor, aggregator, batch, score equation | NO | Byte-exact scores and result counts/order, batch guardrails |
| Benchmark framework / profiling / CI | NO | PERF-05-C only for performance acquisition |

No public API, persistent data, transaction or publication boundary is introduced. The summary's only lifetime is that of the query-local `SnapshotStats`; snapshots remain immutable. A failed query returns a typed error and drops local state under RAII; no incomplete commit or remote write can occur from this edit.

---

## 7. Deterministic unit and adversarial test matrix

**Test location:** Put `b2_*` tests into existing in-file `#[cfg(test)]` modules of **`score.rs` and `execute.rs` only**. Do **not** add a new crate/test framework, dependency, nightly feature or integration file. Reuse existing fixtures and test imports in those modules. Each test must exercise real `compute_stats` / `MixedWorkMeter` logic, not a fake scorer.

| ID / exact test target | Fixture / action | Independent expectation / oracle |
| --- | --- | --- |
| B2-U01 `b2_u01_live_summary_all_and_partial` (`score.rs`) | Use existing `golden_norms.seg` reader; `live = [true,true]`, then `[false,true]`, then `[false,false]`. Call unmodified `compute_stats` with same field and queried term. | `verified_segment_live_count(0,2)` returns 2/1/0; `FieldStats.n` 2/1/0 and `df` equals hand-known live matching docs; `all_live` classification follows count equality; all norms/lengths are unchanged. |
| B2-U02 `b2_u02_two_segment_mixed_counts` (`score.rs`) | Existing legacy golden and norms golden; use two physical `SegmentReader` refs and matching `Rc<Vec<bool>>`: all-live (2,2), mixed (2,1), all-dead on segment 1 (2,0). | Per-segment counts exactly (2,2), (2,1), (2,0); global `FieldStats.n` 4/3/2; independently count live docs from fixture booleans. Preserve existing mixed-format `df/length` tests. |
| B2-U03 `b2_u03_invalid_summary_lookup_fails_closed` (`score.rs`) | Build a real `SnapshotStats` via existing fixture; query ordinal 1 when one segment exists, and ordinal 0 with wrong `bitmap_slots`. | Both return `SearchError::CorruptIndex` with the **exact** design strings from §4.1; valid call succeeds. Do not mutate a committed bitmap to manufacture the failure. |
| B2-U04 `b2_u04_count_helper_chunk_edges` (`execute.rs`) | Synthetic bitmaps of lengths 0, 1, 4095, 4096, 4097, 8192, 8193; mixed `true`/`false` positions. Compute `count` independently from fixture flags; call the new helper with that count. | Result == independent count for all boundaries, including all-dead / all-live. Test checks that all bitmap positions are **not** scanned by the implementation via source guard at review, not a misleading runtime clock. |
| B2-U05 `b2_u05_helper_preserves_work_charge` (`execute.rs`) | Use a `MixedWorkMeter` with normal limits; after helper, execute the unchanged `if count > 0 { meter.charge_lexical(count)?; }`; compare to independent count and the existing fallback's minimum work boundary. | `total_used` equals exactly the number of `true` flags; no charge on all-dead; exact limit passes, one-below returns typed `ResourceLimit`. Count and charge must never equal bitmap slot count when there are deletions. |
| B2-U06 `b2_u06_cancel_poll_schedule_same_as_legacy` (`execute.rs`) | In test-only code, define an isolated **reference** implementing the original §1 S04 helper exactly (count flags and poll leading/chunk/final). Use deterministic `Cancellation` object with a counter and a configurable cancel-after-poll threshold. For 0,1,4095,4096,4097,8193 slots and thresholds 0 through `ceil(slots/4096)+2`, run old reference and new helper on fresh meters with same fixture and cancel rule. | Both return equal counts or `Err(SearchError::Cancelled)` at the **same cancellation poll number**, and record the same number of calls. This reference checks polling parity only; use independent fixture count for result correctness. No sleeps or wall-clock timing. |
| B2-U07 `b2_u07_unified_budget_and_sparse_parity` (existing `unified.rs` tests, **no edit**) | Run `phase4_u10_u11_u12_work_charge_parity`, `phase4_u16_zero_live_and_chunk_boundary`, `phase4_u14_cancellation_unwinds_cleanly`. | All remain PASS without changed tests or relaxed work/cancellation budget, including the 4097 boundary. |
| B2-U08 `b2_u08_b1_and_score_regressions` (existing tests, **no edit**) | Run `phase4_b1`, `phase4_tests`, `b_tests`, score tests and real local oracle. | Exact result set, sorted keys, BM25 **bits**, returned fields, cursor path, multi-segment and legacy/norms behavior unchanged. |

**Do not falsely claim an independent scoring oracle** based solely on running the optimized function twice. Use hand-derived fixture totals for summary tests, the existing indexed oracle suites for query outcomes, and `to_bits()` comparison with the known fallback when the query AST permits. A test-only preserved-old helper is acceptable **only** for polling-parity diagnosis and is not production code.

**Ineligible/negative cases:** zero/one/many/fully deleted effective-live docs; 4096 chunk exact/boundary; stale/missing ordinal and wrong bitmap length; mix of persisted norm + legacy segments; all-live/partly-live per field; single/multiple segments; low-hit absent/rare; multi-analyzed-term Boolean/typed fallback; K1/K10/K100; exact/one-below budgets; cancellation before/counting/after chunk. Existing RustFS tests remain authoritative for remote boundary behavior.

**No per-test benchmark loops or timing assertions.** Iterate fixed, bounded synthetic fixtures solely for deterministic correctness, not latency.

---

## 8. Implementation sequence, baseline/red-first, green and local QA

### Phase 0 — preflight and state reconciliation

Run §3; independently verify S01–S12, then write the invariant/test matrix into the eventual execution report. Capture the actual B1 HEAD, its CI state if accessible, and note the user explicitly chose not to wait. **Do not copy B1's historic SHA into the final report as if it were B2's final SHA.**

### Phase 1 — tests-first contract check

Add B2-U01/U02/U03 to `score.rs` using the new **specified** `verified_segment_live_count` API. Run:

```bash
cargo test -p quervant-core --lib b2_u01 -- --nocapture
```

**Expected preimplementation RED:** Existing source lacks `SnapshotStats::verified_segment_live_count`; compile fails with the corresponding missing-method error (or an explicitly equivalent missing-method diagnostic). This RED is an **API-presence test**, not proof of a runtime performance issue. Capture log; then apply §§4–5. If the test fails for fixture/import/API mismatch or another error, classify using D03–D05 and STOP instead of editing expectations to force the specified failure.

### Phase 2 — exact, bounded production change

1. Implement §4.1 private summary/accessor.
2. Implement §4.2 initial count+retain loop (use final local binding name `live_summaries`).
3. Implement §4.3 `all_live` comparison; preserve all branches and stats equations.
4. Implement §4.4 `Ok(SnapshotStats { fields, segment_live: live_summaries })`.
5. Implement §5.1 helper and §5.2 **single** caller adjustment; no source outside these two files.
6. Check no `segment_live.iter().all()` remains inside the persisted-norm loop and no bitmap `for flag` loop remains inside the examination helper. Confirm that `score.rs` still has **one** initial `filter(true).count()` per bitmap and that partial-live and legacy loops remain.

### Phase 3 — green and focused tests

Add B2-U04/U05/U06 inside `execute.rs`'s existing test module, using the literal verified helper signature. Run:

```bash
cargo test -p quervant-core --lib b2_ -- --nocapture
cargo test -p quervant-core --lib score::tests -- --nocapture
cargo test -p quervant-core --lib phase4_tests -- --nocapture
cargo test -p quervant-core --lib b_tests -- --nocapture
cargo test -p quervant-core --test pr15e_b1
cargo test -p quervant-core --test pr13_oracle
cargo test -p quervant-core --test pr06_local_integration
```

**Required GREEN:** all new B2 tests pass; prior phase4/B1, score, b_tests, local `FsDirectory` and oracle tests pass, with exactly the same behavior under unchanged fixtures. Any failure is classified, not ignored.

### Phase 4 — mandatory workspace and MSRV QA

Run these **after all final Rust/test edits**. Do not call the presence of a command in CI proof it executed locally.

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
bash benchmarks/scripts/test-scripts.sh
cargo bench --workspace --no-run
# `cargo bench ... --no-run` is COMPILATION ONLY, no benchmark execution.
git diff --check
```

**Coverage:** 85% floor across actual production Rust workspace lines, including affected code, with actual measured %; no excluding crates, reduced floor or synthetic result. Additional stable/default+all-features and MSRV toolchains are real gates. If rustfmt reports changes only in authorized files, execute `cargo fmt --all`, inspect exact diff, then rerun **every affected** test/lint/coverage gate. Formatting is not license to touch new files.

**Real RustFS boundary:** If the pinned RustFS environment is already accessible, execute the existing real-service tests as prescribed by `.github/workflows/ci.yml` (at minimum core remote oracle and validated STORED/DOC_KEYS paths):

```bash
cargo test -p quervant-core --all-features --test pr13_oracle -- --ignored --test-threads=1
cargo test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1
```

If `QUERVANT_RUSTFS_*` settings or service are absent, **do not invent PASS, provision privileged services, or block independent local QA**. Record `RUSTFS_LOCAL_BLOCKED / CI_PENDING` and continue. The existing pinned hosted RustFS CI is the remote acceptance route; **do not wait for it** before reporting B2 locally complete and requesting independent review. Never replace it with a fake ObjectStore and call that equivalent acceptance.

**Baseline failure classification:** An error in mandatory QA must be classified as: introduced regression, feature implementation defect, deterministic pre-existing failure, nondeterministic/flaky failure, or environment/harness failure. “Unrelated” alone is not a category. Baseline checks for pre-existing require reproducible baseline evidence, not guesswork. Limit reruns to a **single evidence-driven reproduction**, not unlimited retries. If an external gate is unavailable, mark it BLOCKED rather than DONE.

### Phase 5 — source-level diff, plan and execution report, push

1. Verify only the four permitted tracked paths changed (§11). Use `git diff --name-only "$START_SHA"`, `git diff --check`, `git diff` and `git status --porcelain=v1 --untracked-files=all`; known generated untracked exception P02 may remain but cannot be staged.
2. Copy this **approved plan file verbatim** to `docs/pr-artifacts/perf-05/PERF05B2_DETAILED_PLAN.md`. Require byte-for-byte equality (`cmp`) with the originally supplied Markdown; if supplied file bytes unavailable, STOP rather than reconstruct from memory.
3. Create `docs/pr-artifacts/perf-05/PERF05B2_EXECUTION_REPORT.md` with §12's required fields, including actual commands, test counts, coverage, start/final/remote SHAs, applied decision rows, CI/RustFS truth and no-benchmark assertion.
4. After any further **code/test** change, rerun the affected required QA, including full coverage. A doc-only report edit after successful final QA requires `git diff --check` and doc/link validation only.
5. Stage **only** the four explicit paths. Example: `git add crates/quervant-core/src/search/score.rs crates/quervant-core/src/search/execute.rs docs/pr-artifacts/perf-05/PERF05B2_DETAILED_PLAN.md docs/pr-artifacts/perf-05/PERF05B2_EXECUTION_REPORT.md`. Then run `git diff --cached --name-only` and `git diff --cached --check`: both the **staged** file allowlist and whitespace must be clean before committing. Use one bounded commit such as `perf(perf05b2): reuse query-local live metadata`.
6. `git push origin HEAD:dev/perf05-physical-execution-series` **without force**. Verify remote SHA equals local, confirm PR #117 remains OPEN/draft/unmerged. If rejected as non-fast-forward, preserve the local commit and HARD STOP (no automatic merge/rebase).
7. Return terminal disposition `B2_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING` only if all applicable **local** checks pass; otherwise explicitly `B2_BLOCKED_<CAUSE>` or `B2_IMPLEMENTATION_INCOMPLETE`. **Do not launch B3.**

---

## 9. Real-boundary, error and topology risk matrix

| Risk / input | Expected behavior | Evidence / gate |
| --- | --- | --- |
| All-live segment | Summary count equals slots, norms fast branch unchanged | B2-U01; existing score fixtures |
| One/many deleted docs | Summary excludes dead slots, norms partial branch still validates postings | B2-U01/U02; existing score and phase4 tests |
| Multiple segments; mixed all/partial live | Each segment uses its own ordinal-specific count, global `n` equals sum | B2-U02; two-segment score-bit tests |
| Empty bitmap and count=0 | Reuse zero, still execute initial/final cancellation checks; no examination charge | B2-U04/U05/U06 |
| 4096/4097 boundary | Exactly old number of checks, count independent of slot count | B2-U04/U06; phase4 U16 |
| Wrong ordinal or count geometry | `CorruptIndex` with fixed message; **no silent recount** | B2-U03 |
| Work cap exactly met / one below | Same accepted/rejected outcome, same charged units | B2-U05/U07; phase4 U10–U12 |
| Cancellation before/during/after chunks | Same poll index and typed cancellation outcome for deterministic cancel object | B2-U06; phase4 U14 |
| Corrupt postings/invalid score | No skipped validation; same error and order on valid summary allocation | Existing all-features/negative query tests |
| Additional O(segments) metadata allocation fails | Fail closed with typed `SearchError::ResourceLimit`, no stale state published | §4.2 source review; no allocator-failure simulation required unless existing harness supports safe injection |
| Invalid query, unsupported operator, negative/typed/phrase/Boolean | Original generic fallback unmodified | phase4 eligibility, pr13_oracle |
| Concurrent readers, reopen, mutation, local filesystem | Snapshot bytes immutable, no new state publication | pr06_local_integration, pr13_oracle |
| Real RustFS absent locally | Honest BLOCKED; no claims of real topology execution | CI pinned rustfs job; §8 |

**Out-of-scope failures:** Segment-format, manifest and S3 recovery are not modified; existing relevant suites provide regression checks, not new protocol tests. No new transaction/commit primitive is introduced. No new fuzzing or property-test dependencies: fixed complete small bitmap combinations and existing real fixture oracles sufficiently exercise this bounded summary refactor.

---

## 10. Acceptance gates, reviewer checklist and required evidence

- [ ] B2 `SnapshotStats` summary created exactly once from the old initial pass; segment count/slot size exact, no global cache or cross-query lifetime.
- [ ] No extra per-document bitmap pass; persisted-norm `all_live` computed via cached count equality; **partial-live and legacy processing unchanged**.
- [ ] Eligible examination helper contains leading/per-chunk/trailing cancellation checks and **zero bitmap element reads**; `charge_lexical(live_count)` unchanged in location and amount.
- [ ] Correct index/geometry lookup is typed and fail-closed, with no fallback guessing.
- [ ] Source/lifetime/ownership remains one query-local `SnapshotStats` bound to the same immutable `live` slices; additional O(S) allocation is fallible and disclosed.
- [ ] B1 proven membership shortcut, scores, counts, sort, cursor, duplicate prefilter, batch and ineligible paths unchanged.
- [ ] B2-U01–U06 plus phase4, score and B1 regression tests PASS; independent oracle and real local filesystem tests PASS.
- [ ] Exact/one-below work and cancellation poll **sequence** match the existing contract, including empty/4096/4097/multiple segments.
- [ ] Full local stable+MSRV QA PASS after the **final** source/test modification; actual workspace coverage ≥85% recorded and CI status separate.
- [ ] Pinned real RustFS executed with evidence or reported BLOCKED/PENDING; no fake acceptance.
- [ ] No benchmark/profile acquisition occurred, though host assumed idle; PERF-05-C remains sole profiling/benchmark stage.
- [ ] Scope limited to allowed files; no new crate, unsafe code, new public APIs, persistent formats, CI or benchmark framework changes.
- [ ] Commit is on same PR #117, remote SHA verified; PR left open/draft/unmerged; B3 not started.

**Implementation PASS** = exactly §§4–5, compiles and focused tests pass.  
**Correctness PASS** = invariants traced, adversarial and local vertical-slice gates execute successfully; local stable/MSRV and coverage pass.  
**External acceptance** = hosted CI/RustFS actually executed; pending remains pending without halting authorized B2 progress.  
**Performance** = NOT APPLICABLE TO B2; a static reduction in redundant scans is not a measured warm speedup.  
**PR completion** = NOT APPLICABLE; PR #117 contains the continuing PERF-05 series.

---

## 11. File allowlist / protected paths

**Exactly these tracked paths are allowed to change:**

1. `crates/quervant-core/src/search/score.rs` — live summary, original count pass retained, norm-branch equality, test fixtures.
2. `crates/quervant-core/src/search/execute.rs` — one private helper signature/body + one call site, in-file tests.
3. `docs/pr-artifacts/perf-05/PERF05B2_DETAILED_PLAN.md` — verbatim approved plan, immutable in agent execution.
4. `docs/pr-artifacts/perf-05/PERF05B2_EXECUTION_REPORT.md` — actual evidence and dispositions.

**Protected:** `crates/quervant-core/src/search/unified.rs` (B1!), `work.rs`, `typed.rs`, `unified_plan.rs`, `plan.rs`, `score_segment` implementation, `benchmarks/**`, `docs/BENCHMARKING.md`, `Cargo.toml`, `Cargo.lock`, `AGENTS.md`, `.github/**`, `segment/**`, `index/**`, storage/RustFS, scripts and the prior PERF-05-B/A reports. If the required change touches any protected file, HARD STOP and report the dependency; do not authorize yourself to widen the allowlist.

Generated artifacts (`target/`, coverage, egg-info, benchmark-results) are **not staged**. Existing ignored or untracked data are never discarded, reset or force-removed.

---

## 12. Execution report template and stage boundary

Create `PERF05B2_EXECUTION_REPORT.md` with this exact heading/field structure (replace all placeholders with actual evidence; never fabricate):

```text
PERF-05-B2 EXECUTION REPORT
REPO / BRANCH / PR
START_SHA / MAIN_SHA / FINAL_SHA / REMOTE_VERIFIED_SHA
IMPLEMENTED_FILES (four-path allowlist)
SOURCE_CHECKS S01–S12 / INVARIANTS I01–I14
TESTS_FIRST: pre-fix missing-method red observation (or BLOCKED)
PRODUCTION_DESIGN_APPLIED: score.rs summary + execute.rs helper/call site
FOCUSED_TESTS: B2-U01…U08 and counts
REGRESSION_QA: stable, MSRV, format, clippy, tests, docs, coverage and local integration
WORKSPACE_COVERAGE: actual percentage, tool and measured scope
RUSTFS: executed real topology or BLOCKED/PENDING, never fabricated
EXCEPTION_MATRIX_ROWS: applied rule IDs / triggers / actions
CI: actual run status at report time; do not wait for completion
OPEN_GATES / RESIDUAL_RISKS / FAILURE_CLASSIFICATION
NO_BENCHMARK_RUNS=TRUE; NO_PROFILING_RUNS=TRUE
B2_DISPOSITION: B2_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING or exact BLOCKED state
NEXT: independent B2 review; B3 not authorized by this report
```

**Commit-SHA self-reference:** A committed report cannot contain its own containing commit SHA without changing that commit. Report FINAL_SHA and REMOTE_VERIFIED_SHA in the terminal agent response with `git rev-parse HEAD` and `git rev-parse origin/dev/perf05-physical-execution-series` after push; in the committed report, describe how they were verified without falsely embedding an unknowable self-reference.

**Suggested PR #117 progress note (append, do not open a new PR):**

> PERF-05-B2: Reused a validated query-local per-segment live count across scoring-statistics all-live selection and the postings-driven examination charge. The old per-field all-live bitmap scan and the later per-candidate counting scan are removed; cancellation checks, charges, field norms, all score/result contracts and B1 remain intact. Full local QA and coverage are recorded in the B2 execution report. Real RustFS/CI statuses are separately disclosed. No benchmark or profiling was run; final acquisition stays in PERF-05-C.

---

## 13. Autonomous ordered execution summary

**P0:** Preflight (§3), verify branch, source and B1.  
**P1:** Map invariants/tests, tests-first missing-method red (§8).  
**P2:** Apply the **exact** `score.rs` summary design (§4).  
**P3:** Apply the **exact** `execute.rs` reuse/poll design (§5).  
**P4:** Complete B2-U01–U06 and focused regressions; independently verify work/poll parity.  
**P5:** Full local QA, MSRV, coverage, real local filesystem and relevant RustFS if already available; otherwise truthful blocked/CI pending.  
**P6:** Diff/protected-file check, commit plan+report+two Rust files on PR #117, verify remote, and report.  
**STOP:** Apply §14 to any obstacle. No routine checkpoint requires renewed approval once the agent is authorized to execute.

---

## 14. Preauthorized architectural decisions and exception-handling matrix

**Priority:** Existing repository correctness/work/safety semantics > HARD STOP > DEFER AND CONTINUE > AUTO-RESOLVE. A rule only applies if its **exact observable precondition** holds. Every used row must be listed in the execution report. Escalation owner is the PR #117 maintainer/reviewer; coding agent cannot authorize a new architecture, loosen a gate or merge PR. **Unmatched/unforeseen circumstance ⇒ HARD STOP** for the affected work; continue independent report preparation only if provably safe.

| ID | Observable trigger / source check | Category | Preauthorized action / fallback | Forbidden action | Evidence / gate & escalation |
| --- | --- | --- | --- | --- | --- |
| D01 | Wrong branch, unexpected tracked change, index conflict, non-FF pull, B1 SHA not ancestor or source symbols differ from S01–S12 | **HARD STOP** | Record status, SHAs, minimal diff and stop edits; request amended plan | Reset, stash, rebase, cherry-pick, force-push or invent different APIs | P0 BLOCKED; maintainer |
| D02 | Only previously listed generated untracked `.coverage`, `benchmark-results/**`, `benchmarks/quervant_bench.egg-info/**` are present; no tracked modification | **AUTO-RESOLVE** | Preserve data, do not modify ignores or index; proceed using exact-path `git add` | Delete/hide newly, alter `.git/info/exclude`, stage a directory | P0 exception report |
| D03 | Tests-first B2-U01 fails compilation solely due to missing specified `verified_segment_live_count` method | **AUTO-RESOLVE** | Preserve expected RED log and implement §4, continue | Loosen test, change method contract, accept other errors as expected red | Test-first PASS-as-expected |
| D04 | Tests-first failure is fixture mismatch, missing imports not prescribed, panic, wrong scores, or unrelated compile errors | **HARD STOP** | Preserve logs and minimal reproducer; stop source edits | Rewrite fixtures/oracle to force RED | Test harness BLOCKED; maintainer |
| D05 | Verified existing count fold, norm branch or helper differs from §1 anchors; no single old pass exists | **HARD STOP** | Record exact source and needed design amendment | Introduce alternate cache or data-flow | Source proof invalid |
| D06 | All S01–S12 match and required B1 fix is intact; exact naming and code in §§4–5 apply | **AUTO-RESOLVE** | Implement the prescribed two-file design and continue QA | Change `compute_stats` or `evaluate_lexical_with` APIs, scorer/heap, use `len()` as count | B2 implementation gate |
| D07 | Shadowing between the old `segment_live = &live[index]` slice binding and new metadata vector | **AUTO-RESOLVE** | Use the **fixed local binding** `live_summaries` from §4.3 and private field `segment_live`; no new helper | Rename APIs arbitrarily, remove original live slice | Build correctness gate |
| D08 | Rustfmt or Clippy flags a deterministic formatting/unused import introduced strictly in modified lines | **AUTO-RESOLVE** | Apply only `cargo fmt --all`/exact compiler-suggested local correction within allowlist; rerun affected QA | Change API/safety behavior or suppress lints | Local QA; report change |
| D09 | Per-segment count or global `FieldStats.n` disagrees with fixture/oracle, including deletion/empty/multi-seg | **HARD STOP** | Capture actual and expected values; stop logic edits | Change expected flags or substitute `.len()` | I01/I02 BLOCKED |
| D10 | Normed partial-live or legacy path differs, wrong `df`/score-bit/projection/corruption behavior | **HARD STOP** | Preserve first divergence, typed error and source diff | Skip validation, relax oracle or alter scoring equations | I02/I03/I07/I08 |
| D11 | Helper loses, reorders or adds cancellation polls or charges; 4096/4097 tests disagree with old reference | **HARD STOP** | Record poll counters, bitmap fixture, work limit; stop | Change chunk size or cancellation frequency | I05/I06 |
| D12 | Cached summary ordinal/slot mismatch would be silently accepted or return data for wrong segment | **HARD STOP** | Preserve mismatch case and stop | Fall back without logging, use unchecked `.get().unwrap()` | I09 |
| D13 | Local RustFS service absent; CI pending, even if B1 CI has not passed | **DEFER AND CONTINUE** | Record `RUSTFS_LOCAL_BLOCKED`/`CI_PENDING`, finish all independent local QA and source work, push truthful report | Wait indefinitely, fake PASS, dispatch extra run or change CI | External gate PENDING; maintainer |
| D14 | Stable/MSRV/llvm-cov tool missing, safe standard installation unavailable | **DEFER AND CONTINUE** | Record exact command/missing dependency; execute other gates; mark B2 NOT VERIFIED | Lower coverage floor, omit toolchain, fake percentage | Tool gate BLOCKED |
| D15 | Any error from mandatory tests, lint, coverage, local integration or RustFS (when available) | **DEFER AND CONTINUE** | Classify introduced/feature/pre-existing/flaky/environment with evidence; run one bounded baseline reproduction only if safe, complete independent checks; leave acceptance BLOCKED | Call it unrelated without evidence, unlimited reruns, edit unrelated tests to pass | QA failure; maintainer decision |
| D16 | Obvious one-line typo strictly in newly added B2 test/reference fixture, with no intended semantic change | **AUTO-RESOLVE** | Correct once to exact contract, rerun test and final QA; document typo | Alter expected results/count/cancel schedule | Test correction review |
| D17 | New metadata vector requires a new crate, persistent state, telemetry, unsafe access, reference-sharing or a format change | **HARD STOP** | Stop, describe design conflict, seek maintainer amendment | Broaden implementation or file scope | Scope BLOCKED |
| D18 | New count/`all_live` calculation requires modifying `search/unified.rs`, `work.rs`, decoder, scorer or any protected file | **HARD STOP** | Report exact missing seam and stop code | Widen allowlist, change caller/feature flag | Cross-component gate |
| D19 | B1 eligible-vs-fallback behavior, score bits, or test-only counters regress | **HARD STOP** | Save smallest failing fixture, stop affected B2 edits | Reopen B1, alter callback or weaken B1 tests | I13 |
| D20 | Tester requests any real benchmark, profiler, idle probe or arbitrary performance check | **AUTO-RESOLVE** | **Do not run**; continue correctness work and defer all acquisitions to PERF-05-C | Timed runs, `perf record`, new benchmark config | No-acquisition rule |
| D21 | Remote branch advanced after checkout or push non-FF; branch SHA inconsistent with local checked source | **HARD STOP** | Preserve local commit, list local/remote SHAs and seek reconciliation | Force push, auto-merge/rebase/rewrite another commit | Source integrity |
| D22 | Local QA passes; CI/RustFS remains incomplete | **DEFER AND CONTINUE** | Push report as `B2_IMPLEMENTED_LOCAL_QA_PASS_CI_OR_RUSTFS_PENDING`, keep PR open | Mark B2 finally accepted, merge, start B3 | External acceptance boundary |
| D23 | All local mandatory gates executed/pass and no unclassified failures; remote matches pushed B2 source | **AUTO-RESOLVE** | Commit/push bounded B2, report actual evidence and request independent review | Claim final PERF-05-C result, start next stage | Implementation handoff |
| D24 | New condition not exactly described by any other matrix row, or two rules conflict | **HARD STOP** | Stop affected work, list evidence and minimal human choice; finish only safely independent documentation | Improvise code/architecture or waive a rule | Maintainer plan amendment |
| D25 | Current approved memory-accounting contract requires a query-scope charge for the additional O(segments) `SnapshotStats` vector, contrary to the inspected unmetered statistics-setup pattern | **HARD STOP** | Record the exact contract/charge gap; request a separately specified accounting design | Silently add uncharged metadata, bypass batch ledgers, invent charges or redesign ownership | Memory-safety/accounting review; maintainer |

**Deferral discipline:** A blocked external or independent QA gate does not erase the completed work; but a B2 correctness or compilation failure **does block an implementation PASS** until fixed under an approved plan. Distinguish *implemented*, *locally verified*, *hosted accepted* and *merged*—none implies the next.

---

## 15. End-state and coding-agent instruction

**B2 succeeds locally only when:** one initial pass computes and retains segment counts, every persisted `all_live` branch reuses them, the eligible helper avoids re-reading flags but retains cancellation polls and logical charge, all specified new+existing tests pass, stable/MSRV/coverage/local integration gates execute and pass, and the four-file diff is clean. The agent may still report hosted CI/RustFS as PENDING. No measured latency improvement is claimed; the host-idle assumption does not authorize performance acquisition.

**After B2:** B3's future plan may replace the full matched-document tree with an ordered representation; **nothing about B3/B4/B5 is implemented by this plan**. PERF-05-C owns consolidated warm A/B and Rust-symbol-aware profiling. The single PR #117 remains open and draft.

> **Agent's binding rule:** This document contains the architecture, exact Rust changes, tests, verification and exception decisions. Implement **only** the approved design. If a situation is not covered or any proof is invalid, **STOP rather than create a new design**.

---

## 16. Exact test construction notes — no delegated architectural decisions

These notes constrain implementation of the tests in §7. They do not authorize extra functionality or performance measurements.

### 16.1 `score.rs` fixture reuse

In the existing `#[cfg(test)] mod tests`, use the **existing** source patterns of `live_bitmap_excludes_dead_documents_from_stats` and `mixed_legacy_and_norms_segments_aggregate`. The known fixture constants are:

```rust
const NORMS_GOLDEN: &[u8] = include_bytes!("../../tests/fixtures/segment/golden_norms.seg");
const LEGACY: &[u8] = include_bytes!("../../tests/fixtures/segment/golden.seg");
```

Instantiate them with `SegmentReader::open(bytes.to_vec(), SegmentLimits::default())`; query the verified `title` field ID and `"hello"` term using the existing `query_for()` helper. For B2-U01, construct **one** live vector per case:

```rust
vec![Rc::new(vec![true, true])]
vec![Rc::new(vec![false, true])]
vec![Rc::new(vec![false, false])]
```

Each `compute_stats` invocation uses fresh `SearchWork::new(limits.max_total_work_units(), &NeverCancel)` and the **same** `&[&reader]` and live vector. Assert `verified_segment_live_count(0, 2)` equals `2`, `1`, and `0`, and each corresponding `FieldStats.n` matches. The preexisting test records that both golden-norm documents contain `"hello"`; expected `df` is therefore `2`, `1`, and `0` respectively. No test may derive expected `df` by calling Quervant's scorer a second time. Do not modify the fixtures.

For B2-U02, use the verified two-reader pairing from the existing mixed legacy/norms test, and choose live vectors exactly:

```rust
vec![Rc::new(vec![true, true]), Rc::new(vec![true, true])]
vec![Rc::new(vec![true, true]), Rc::new(vec![false, true])]
vec![Rc::new(vec![true, true]), Rc::new(vec![false, false])]
```

Expect per-segment summaries `(2,2)`, `(2,1)`, `(2,0)` and snapshot-wide `n` values `4`, `3`, `2`. Use separate fresh `SearchWork` for every case. Verify the existing full all-live mixed-format test still expects `df = 4`. If golden fixture content differs from these **verified source facts**, apply D05: STOP, do not adjust expected outcomes speculatively.

For B2-U03, retain a completed `SnapshotStats` from a valid `compute_stats` call and assert the exact errors from §4.1:

```rust
assert!(matches!(
    stats.verified_segment_live_count(1, 2),
    Err(SearchError::CorruptIndex { .. })
));
assert!(matches!(
    stats.verified_segment_live_count(0, 3),
    Err(SearchError::CorruptIndex { .. })
));
```

Additionally inspect `detail` with a `match` and compare the exact prescribed strings for both cases. No production mutation, fake corruption or unsafe state injection is permitted.

### 16.2 `execute.rs` cancellation-parity reference — tests only

Within the existing in-file `#[cfg(test)] mod budget_tests`, use `super::*`, `std::cell::Cell`, and the existing `MixedWorkMeter::new` constructor. Define a strictly test-only cancellation object; its count is **not** a performance timer:

```rust
struct B2PollCancel {
    checks: Cell<usize>,
    fail_at: usize,
}
impl crate::analysis::Cancellation for B2PollCancel {
    fn is_cancelled(&self) -> bool {
        let before = self.checks.get();
        self.checks.set(before + 1);
        before >= self.fail_at
    }
}
```

Copy the **preserved historical helper body** into a **test-only** function named `b2_legacy_recount_for_test(live, meter)` with exactly the old leading / chunk inner flag count / chunk check / trailing check structure from §1 S04. No use of it in production. For each synthetic bitmap size in §7, compute `expected_count` independently from fixed input flags, and create two distinct `B2PollCancel` objects plus two independent `MixedWorkMeter::new` instances with the same ordinary limits. Call one helper per meter. Compare outcomes (`Ok(count)` or typed `Cancelled`), number of calls to `is_cancelled`, and successful count to the independent expected fixture count.

The **expected successful cancellation-check counts** are immutable:

| Physical slots | Chunks of 4096 | Required helper cancellation calls |
| ---: | ---: | ---: |
| 0 | 0 | 2 |
| 1 | 1 | 3 |
| 4095 | 1 | 3 |
| 4096 | 1 | 3 |
| 4097 | 2 | 4 |
| 8192 | 2 | 4 |
| 8193 | 3 | 5 |

For each size, exercise `fail_at` from `0` through `(required_calls + 1)` inclusive. The `B2PollCancel` returns false until it has observed exactly `fail_at` prior checks; both implementations must produce the same cancellation status and count. No sleeps, thread scheduling, stopwatch, profiler or retry loop. If the **old reference** cannot be copied with the same semantics, STOP under D05/D11; do not redefine the approved cancellation contract.

### 16.3 Source-review checks for the optimization itself

After the final patch, the reviewer must be able to see that: (a) `compute_stats` reads bitmap flags **once** to count per segment; (b) its persisted-norm `all_live` uses only `live_summaries[segment_index]` fields; and (c) the examination helper loops over `live.chunks(4096)` for cancellation only, with **no** `for flag in chunk`, `iter().filter`, `any`, or `all` over bitmap elements. The tests validate output and cancellation; this source inspection validates the absence of the redundant scan. **Do not add a test-only counter that pretends to prove no bitmap reads by always returning zero.**
