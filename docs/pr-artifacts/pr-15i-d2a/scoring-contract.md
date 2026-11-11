# PR 15I-D2-A — real production-path scoring contract

## Test topology

`crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` is test-only. Every
scenario uses a real `FsDirectory`, the public `Index` → writer → commit →
reopened `ReaderSnapshot` path and `UnifiedSearcher::search`. No scorer is
mocked, no in-memory directory substitutes for SC-15 and no production
visibility is widened. Comparisons use logical `DocumentKey` maps and exact
`f64::to_bits()` values.

## SC results

| ID | Scenario | Result |
|---|---|---|
| SC-01 | Zero matches, explicit ascending Keyword sort, K10 | PASS: zero hits, `total_hits=0`, no score, no hidden failure |
| SC-02 | One hit, explicit sort vs relevance | PASS: `Some(f64)` and identical bits per key |
| SC-03 | Nine documents with varying frequency/length | PASS: explicit-sort and relevance bits identical; order follows sort |
| SC-04 | 101 matches, K10 and K100 | PASS: exact K hits, total 101, each bit equals full-result reference |
| SC-05 | Reversed sort direction and repeated tie values | PASS: scores unchanged per key; deterministic page keys |
| SC-06 | One segment vs two segments, committed reopen | PASS: keyed bits and totals unchanged by segment split |
| SC-07 | Delete + upsert + old PIT and current snapshot | PASS: old PIT immutable; current total 490; fresh reopen agrees |
| SC-08 | Explicit-sort cursor pages 1 and 2 | PASS: no repeated/omitted keys; each score matches full reference |
| SC-09 | Ineligible `And([Term])` vs single `Term` | PASS: same keys, totals and exact score bits |
| SC-10 | `MatchAll` and typed-only `Exists` | PASS: `score = None` for filter-only hits |
| SC-11 | Negative-only lexical and mixed typed/lexical | PASS: pure negative has no positive contribution (`None`); mixed stays scored and bit-equal to the single term for the same keys |
| SC-12 | Pre-cancelled search, invalid sort, stale PIT cursor | PASS: `SearchError::Cancelled`, `Query(InvalidQuery(InvalidSortField))`, `Query(InvalidQuery(CursorPitMismatch))` |
| SC-13 | Constrained candidate entries | PASS: existing `SearchError::ResourceLimit` category |
| SC-14 | Repeated query, same and reopened snapshot | PASS: ordered keys and score bits identical |
| SC-15 | Native `FsDirectory` commit → process-scope reopen | PASS: fresh directory and reopened index produce identical bits |
| SC-16 | `bm25` `tf=0`, `n=0`, `df>n`, non-finite | Covered by existing private scorer unit tests `search::score::tests::bm25_boundaries_and_invalid`; no production visibility was added |

All 15 executable SC tests pass in the workspace test run
(`cargo test -p quervant-core --test pr15i_d2a_scoring_contract`: 15 passed,
0 failed).

## Adversarial counterexamples recorded before implementation

| Contract | Concrete counterexample a naive late scorer would get wrong |
|---|---|
| Observable score | A winner is scored only after heap admission, while the accepted pipeline computes `ProjectedHit.score = Some(bm25(...))` for every returned hit. Deferring the call can change the f64 rounding path or omit `-0.0`/`NaN` checks; SC-02/03/04/06/07 compare exact bits and reject a zero-substitute. |
| Error precedence | A non-winning document with `df > n` makes eager `bm25` return `InvalidScore` and fails the whole query. Scoring only winners would silently return success; D2-A records this as an unproven contract-changing shortcut. |
| Resource admission | `score_segment` reserves `SCORED_MAP_BYTES_PER_ENTRY = 64` for **all** matches before building the `BTreeMap`. A late scorer that reserves only for winners can admit a query that the accepted path rejects with `ResourceLimit`; SC-13 pins the accepted category. |
| Cancellation | The eager pipeline polls cancellation and charges work for every examined live document, including non-winners. A winner-only scorer can defer the first cancellation point; SC-12 pins cancellation-before-search only, and the report marks mid-scan parity unproven. |
| Multi-segment | Scores depend on globally aggregated `n`/`avgdl`/`df`; a per-segment late scorer that omits stats for segments with no winners changes bits. SC-06 compares one segment with two segments and SC-07 reopens committed state. |
| Cursor | Cursor validation depends on `last_score` presence and the sort fingerprint. A late score that is absent on a page can turn a valid cursor into `CursorSortMismatch`; SC-08 exercises page 1/page 2 and SC-12 a stale PIT cursor. |
| Aggregation | An aggregation request must count all effective-live matches while the heap keeps only K. Deferring scores until after aggregation admission can change total hits or error order; the D2-A frozen lanes do not request aggregation, so this remains `UNPROVEN` for D2-B. |
| Document mutations | Old PIT snapshots must not observe later deletes/upserts. Reusing a post-commit score cache in a late scorer would mutate the old view; SC-07 compares the old PIT before and after the mutation. |

## Oracle policy

The independent frozen PR15D oracle validates returned keys and exact totals,
not scores. SC-02/03/04/06/07 therefore use a second genuinely different public
query form (`And([Term])` or relevance order) only when the term frequencies,
scoring leaves and snapshot are identical. Score order is never used as a
substitute for score equality. SC-16 cites the executed private scorer tests
rather than adding production access.
