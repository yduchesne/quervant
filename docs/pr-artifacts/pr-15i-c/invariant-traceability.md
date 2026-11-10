# PR 15I-C — Invariant traceability and pre-implementation challenge

Status: `PRE_IMPL_CONTRACT_CHECK_PASSED`
Scope: `C-EXACT-ONE` = standalone, single positive exact `Term`, single immutable
segment, single ascending scalar columnar `Keyword` sort, no cursor/aggregation.

## 0. Design question resolutions (frozen)

| 15I-0 open question | Resolution in this PR | Mechanism |
|---|---|---|
| Sort/key equivalence ("a `doc_id` column equals the logical key") | **Rejected — never asserted.** No name-based, metadata-based or corpus-based shortcut is taken. | The fast path calls the unmodified `consider_borrowed_keyword_candidate`, i.e. the canonical `ColumnKeywordView` decoder plus `compare_borrowed_keyword_to_owned` / `compare_candidates`. |
| Budget work/peak equivalence | Proved by **virtual preflight reservations** that reproduce the legacy matched-set and scored-map peaks before any key/sort/heap work, plus differential exact-and-one-below tests. | §4 below (`C-U14..C-U17`, `C-U21`, `C-U22`, `C-U35`). |
| Stage measurement | Benchmark-only, opt-in `pr15ic-probe` feature; zero branches in default release. | `benchmarks/pr15i_c/stage_probe/`. |

## 1. Invariant → test mapping

| ID | Invariant | Owner function(s) | Primary tests |
|---|---|---|---|
| C-INV01 | `total_hits` counts every matched effective-live document, not only K; K+1 cursor behavior unchanged | `unified.rs::collect_mixed` (callback + `heap_limit`) | C-U05, C-U08, C-I03, C-U37 |
| C-INV02 | Same ordered logical keys and physical `(segment_index, doc_id)` as generic | `collect_mixed` callback, `consider_borrowed_keyword_candidate` | C-U08, C-I01, C-I03 |
| C-INV03 | Bit-identical returned BM25 score (`f64::to_bits`) incl. zero/tie cases | `execute::for_each_exact_term_score_with` scoring loop; `score::bm25` | C-U09, C-U34, C-I02 |
| C-INV04 | Sort tuple from same column access; value/Null/Missing ranking and key tie-break; no key==column assumption | `typed_compare::*` via `consider_borrowed_keyword_candidate` | C-U10, C-U11, C-U12, C-U32, C-I04 |
| C-INV05 | First-error category and ordering unchanged (validation → metadata → postings/work → matched budget → scored budget → scoring → key → sort → heap → projection) | `search_impl`, `execute_unified`, `collect_mixed`, helper phase order | C-U16–C-U25, C-F01–C-F08 |
| C-INV06 | `max_total_work_units`, `max_scanned_posting_occurrences`, per-live examination units charged at the same positions as today | `build_leaf_data` (`1+freq`), `effective_live_examination_count`, `charge_lexical(live_count)` | C-U13, C-U14, C-U16, C-F01 |
| C-INV07 | `CandidateBudget` limits not bypassed; modeled legacy matched/scored peak reproduced before key/heap | helper `reserve_with_memory(M, 48·M, None)` then `(M, 64·M, None)` | C-U15, C-U17, C-U21, C-U22, C-F02, C-F03 |
| C-INV08 | Noncompetitive candidate and losing invalid sort-value behavior unchanged; borrowed view validated before competitive rejection | `borrowed_keyword_candidate_charge`, `columns.keyword_sort_view` | C-U10, C-U24, C-I04 |
| C-INV09 | No duplicate logical key among retained candidates | `consider_borrowed_keyword_candidate` duplicate guard | C-I06, C-I07 |
| C-INV10 | No serialization/feature/section/manifest/`CURRENT`/codec/index/public-API change | — (allowlist diff + byte parity) | C-I13, C-U28, C-P11 |
| C-INV11 | Effective-live + PIT snapshots immutable; no remote reads in scoring; no shared mutable long-lived scratch | `ReaderSnapshot::effective_live_docs`, per-request locals | C-I05, C-I09, C-I17, C-R01–C-R06 |
| C-INV12 | Fast path never builds matched `BTreeSet`, scored `BTreeMap` or calls `score_segment`; exact canonical heap preserved | test-only allocation witnesses in `c15i_physical_tests` | C-U04, C-U29 |
| C-INV13 | Every candidate has work/cancellation checks; posting bytes verified by the existing reader first | `next_with(cancel)`, `meter.check_cancelled()`, `effective_live_examination_count` | C-U06, C-U18, C-F04 |
| C-INV14 | All other shapes and the batch/mutation paths identical under shared limits | `single_term_postings_eligible` fallback branch unchanged | C-U03, C-U26, C-I10, C-I11 |

## 2. Adversarial counterexamples (constructed before implementation)

Each row is a deliberate attempt to break the tempting-but-wrong shortcut. The
"failing hypothetical" column names the implementation this plan forbids.

| # | Fixture | Protected behavior | Expected result/error | Failing hypothetical | Test |
|---|---|---|---|---|---|
| 1 | Keyword `doc_id` value differs from logical key, plus a second hit with an equal sort value | `compare_candidates` + key tie-break is authoritative | Force-generic-identical order | Sort postings by logical key / assume equality | C-U10, C-U32 |
| 2 | 1,001 matches, K=1 | `total_hits` is exhaustive | `total_hits == 1001`, one hit + cursor | Stop counting after K (or K+1) | C-U05 |
| 3 | Two postings, TF 1 vs 3, differing in low mantissa bits | returned score is the computed `f64` | `to_bits` equality per hit | Re-score winners / round | C-U09, C-U34 |
| 4 | `InvalidScore` on a late posting + invalid earlier sort column | scoring precedes sort decode | `InvalidScore` (score error first) | Interleave scoring with sort decode | C-U19, C-U38, C-F07 |
| 5 | M live matched postings, cap that failed at matched or scored reservation | legacy peak preserved | same `ResourceLimit { requested, limit }` | Use removed trees to admit | C-U15, C-U21, C-U22 |
| 6 | `Cancelled` during enumeration, work limit one below passing | cancellation/work precedence | `Cancelled`/`ResourceLimit` before any callback | Defer cancellation to heap | C-U14, C-U18, C-F06 |
| 7 | Missing/Null/Value keyword states, invalid UTF-8 losing value | borrowed view fully validated | prior typed error, no heap entry | Skip validation for losers | C-U11, C-U24 |
| 8 | Stale logical-key duplicate across two segments | generic duplicate/corrupt behavior | fallback (2 segments) + `CorruptIndex` | Specialize multi-segment dedup | C-I06, C-I07 |
| 9 | One parsed `Term` expanding to two analyzed terms | expansion semantics | fallback, full 2-term match set | First-term-only fast result | C-U02 |
| 10 | Cursor with plausible field values but mismatched snapshot | cursor validation precedes segment reads | cursor error before open | Ignore cursor on fast path | C-U33, C-I12 |
| 11 | Empty live set, deleted-only segment, absent posting list, 100K common list | exact charges and counts | `total_hits == 0`/`M`, per-live work charged | Skip per-live work when no postings | C-U05, C-U13 |
| 12 | 15I-B v2 local/RustFS immutable segment + legacy v1 snapshot | no migration, same query output | identical keys/order/scores, no new feature | New C feature ID / migration | C-U28, C-I13, C-R06 |

"Actual test output" for every row is recorded in
[`correctness-and-qa.md`](correctness-and-qa.md) after execution; a row without
executed evidence is not PASS.

## 3. Explicitly rejected shortcuts

1. Key/column equivalence shortcut — rejected (§0).
2. Postings sort by logical key — rejected (requires `doc_key` for *all* M up front, changing first-error order and per-live accounting).
3. Score-deferral / winner-only scoring — rejected (would move `InvalidScore` after key/sort/heap).
4. Zero-scratch streaming straight into the heap — rejected (cannot reproduce legacy matched/scored admission peaks).
5. Freeing the virtual matched/scored budget because the trees are gone — rejected (C-INV07).
6. Widening eligibility for cursor/batch/aggregation/multi-segment multi-term or numeric/descending sorts — rejected.
7. Any `unsafe`/`transmute` reinterpretation of `(u64,u64)` as `(u64,f64)` — rejected.

## 4. Exact budget model required by the helper

Order (unchanged from `evaluate_lexical_with`):

1. `SegmentCandidateLedger::new(budget)` → `budget.begin_segment()`.
2. `build_leaf_data(..., memory = None)` — reserves `16` bytes per live posting, charges `1+freq` scanned work per decoded posting.
3. `effective_live_examination_count(live, meter)` once, `check_cancelled()`.
4. `meter.charge_lexical(live_count)` once.
5. `check_cancelled()` per posting (legacy per-candidate poll) and once after the loop.
6. `ledger.reserve_with_memory(M, 48·M, None)` — **virtual legacy matched set**.
7. `ledger.reserve_with_memory(M, 64·M, None)` — **virtual legacy scored map**.
8. `scores: Vec<f64>` with `try_reserve_exact(M)`; compute `bm25` for every posting (0.0 when `FieldStats` is absent).
9. releases: matched `(M, 48·M)`, leaf `(M, 16·M)`, scored `(M, 64·M)`; `ledger.finish()` → zero owned entries/bytes.
10. Callback phase: `on_scored(doc_id, score, M, budget)` in ascending physical doc id, no early stop; key decode and heap admission happen here exactly as the legacy loop does.

A mismatch between the modeled peaks and the legacy path at exact/one-below
thresholds is a **C-D23/C-D24** condition and blocks the operator.
