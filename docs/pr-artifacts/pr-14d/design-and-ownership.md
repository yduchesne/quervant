# PR 14D — design and ownership

**Status:** implementation complete for review; PR 14 remains IN PROGRESS.
Baseline `2cb91be` (PR #62 merged), implementation commit `d0e1bbb`.

## 1. Objective

Eliminate unmetered transient allocation along typed and unified JSON-path
**sort** paths. Every retained growth of the occurrence buffer, the owned
path/member/node payloads, and the retained winning scalar is admitted through
the existing batch `MemoryCharge` **before** it is allocated or pushed. The
logical `BatchMemoryBytes` meter is a logical reservation ledger, never a
physical/RSS bound.

## 2. Call graph (after)

```
execute_batch / execute_batch_pinned
└── UnifiedSearcher::search
    └── collect_mixed(batch = Some(&mut BatchExecutionMeter))
        ├── scope = SlotMemoryScope::new(batch.memory)          (existing)
        └── per document
            ├── sort_scratch = JsonSortScratch::new(scope.as_mut())
            ├── typed::json_sort_value(..., &mut sort_scratch)   (same helper)
            │   ├── JsonAccess::occurrences(..., Some(&mut *sort_scratch))
            │   │   ├── indexed: DocOccurrences::next_occurrence + push_occurrence
            │   │   └── legacy: extract_field_paths_charged(..., sink)
            │   └── single-pass winner selection under Min/Max
            ├── sort_scratch.finish()?                          (release winner)
            └── heap admission charges the retained tuple       (existing)
```

Standalone typed execution (`TypedSearcher::search`) has no batch meter; it
passes `None` (AD-04/E09) and keeps its existing query-local limits. The same
`json_sort_value` code serves both paths.

## 3. Ownership model

| Owner | Bytes tracked | Lifetime |
|---|---|---|
| `JsonSortScratch` (`Occurrences` ledger) | occurrence vector slots + owned path/member/node payloads | one document sort |
| `JsonSortScratch` (`Winner` ledger) | retained `FieldValue` string payload | from winner clone until the caller installs and charges the sort tuple |
| `OccurrenceScratchSink` | adapter from segment `ScratchCharge` to `MemoryCharge` | one `occurrences()` call |
| `SlotMemoryScope` / `BatchMemoryMeter` | cumulative batch current/peak | existing contract |

`JsonSortScratch` implements `MemoryCharge` so the existing `occurrences` call
site needs no second meter; its `preflight`/`commit` route to the `Occurrences`
ledger. Winner reservations use `reserve_before_allocation(Winner, ..)`.

## 4. Charge formulas (checked, `u64`)

- **Occurrence vector slot**: `additional * size_of::<JsonOccurrence>()`, charged
  before `try_reserve_exact`; the actual capacity delta is reconciled afterwards
  (extra charged, or the surplus released).
- **Owned occurrence data**:
  `path.len() * size_of::<JsonPathComponent>()`
  `+ Σ Member(m).len()`
  `+ node string len()`.
  Indexed occurrences use the decoded vector's actual capacity; the legacy
  extractor charges the clone's exact length.
- **Winner**: `FieldValue::Text|Keyword` string length; numeric/bool payloads are
  inline and cost zero heap bytes.
- All arithmetic uses `checked_add`/`checked_mul`; overflow is a typed
  `CorruptIndex`/`LimitExceeded`, never a silent wrap.
- Batch rejection surfaces as
  `SearchError::Query(QueryError::BudgetExceeded { kind: BatchMemoryBytes })`.

## 5. Reservation-before-allocation proof

1. `push_occurrence` charges the capacity delta **before**
   `Vec::try_reserve_exact` and charges owned bytes before `Vec::push`
   (which is where the path clone would allocate).
2. The legacy extractor (`extract_field_paths_charged`) uses the same
   `push_occurrence` for every emitted occurrence, before its `out.push`.
3. `json_sort_value` reserves the winner bytes before `best.replace(value)`
   clones/replaces, and releases the previous winner only after the new one is
   accounted.
4. On a failed allocation after a committed charge, the charge is released
   before the typed error is returned; `finish`/`Drop` release everything on
   cancellation or unwind.

## 6. Indexed vs legacy paths

- **Indexed** (`JsonPathsReader` present): `DocOccurrences::next_occurrence`
  decodes one occurrence at a time. The **first/current** occurrence's own path
  and node allocations are a bounded decode transient (depth ≤ 128, member
  ≤ 65,535 bytes, section ≤ 256 MiB) that exists between decode and the
  immediately following admission of the same occurrence; it is never retained
  unmetered. `out.push` growth and all retained owned bytes are admitted.
- **Legacy** (no JSON-path section): `extract_field_paths_charged` preserves the
  existing traversal, sorting and duplicate-path rejection semantics, but routes
  every retained slot/owned payload through the sink. The walker's reusable path
  and depth-bounded cursor stack remain a bounded transient and are qualified in
  `resource-characterization.md`.
- Legacy unstored fields still fail typed
  (`UnsupportedOperator("json_path_legacy_unstored")`); corrupt bytes still fail
  at decode.

## 7. Retained-transfer lifecycle

In `collect_mixed`, the winner reservation stays live while the sort tuple is
built and the search-after filter runs. It is released by
`sort_scratch.finish()` immediately before `candidate_charge`/heap admission, so
the retained tuple is charged exactly once by the existing heap accounting and
the transient winner is not double-charged. No allocation occurs between the
release and the heap charge. The typed accumulator (no batch meter) performs the
same sequencing with a `None` sink.

## 8. Deviation / interpretation notes for review

- Plan P2.1 "prefer on-the-fly scalar selection" is satisfied for the winner
  (no second `Vec<FieldValue>`); the occurrence buffer is still materialized,
  which is the path explicitly described by frozen decision AD-05
  (preflight capacity reservation before `out.push` growth). This keeps the
  existing validation/duplicate semantics and traceability.
- AD-07's decoder transient is bounded and documented rather than claimed as a
  hard physical cap; see `resource-characterization.md`.
- No codec, manifest, cursor, public API, dependency, `unsafe`, or CI change was
  made.


## 9. SR-14D-01 addendum (2026-10-26)

Winner selection now compares **borrowed** `JsonNode` values via a private
`json_sort_scalar_cmp`; no `FieldValue` is materialized for non-winners. The
selected node's owned bytes are reserved through `JsonSortBuffer::Winner`
**before** the single `node_to_field_value` conversion
(`materialize_json_sort_winner`). Occurrence-buffer lifetime, release ordering,
caller `finish()` handoff and charge formulas are unchanged. See
[sr14d01-fixup.md](sr14d01-fixup.md).
