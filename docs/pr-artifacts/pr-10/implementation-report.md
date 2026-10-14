# PR 10 Implementation Report

**Title:** Typed numeric/temporal retrieval and bounded exact analytics
**Base:** `main` `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`
**Branch:** `dev/temporal-retrieval`
**Status:** implementation complete and locally verified; **not merged**, roadmap is
`IN REVIEW` (no DONE marker) pending reviewer acceptance and merge.

## Summary

PR 10 adds a single snapshot-bound typed scan engine to `quervant-core::search`:

- `TypedSearcher::new(&ReaderSnapshot, &Schema, SearchLimits)` with
  `search(TypedSearchRequest, ...) -> TypedSearchResponse` and
  `aggregate(AggregateRequest, ...) -> AggregateResponse`.
- Typed boolean subset `MatchAll`, columnar `Range`, half-open `TimeRange`,
  recursive `And`/`Or`/`Not`; unsupported operators fail closed before I/O.
- Deterministic typed sort with distinct missing/null handling, multi-value
  selectors, canonical scalar ordering and key tie-break.
- Opaque `TypedCursor` bound to a process-wide snapshot identity and a canonical
  SHA-256 query/sort fingerprint (page size excluded).
- Fixed-width signed time buckets via checked `i128::div_euclid`.
- Exact group-by (≤3 keys), `Count`, checked `i128`/`u128`/Neumaier-compensated
  `F64` `Sum`/`Avg`, `Min`/`Max` (including `Timestamp`), exact per-group distinct
  and exact frequency top-K.
- Conservative positive-`And` `TimeRange` segment pruning with diagnostics and a
  hidden pruning-disabled differential mode.
- Additive checked resource bounds and cooperative cancellation with no partial
  responses.

## Files

New production code:

- `crates/quervant-core/src/search/typed.rs`
- `crates/quervant-core/src/search/typed_compare.rs`
- `crates/quervant-core/src/search/analytics.rs`

Modified production code (additive / read-only):

- `crates/quervant-core/src/search/limits.rs` — nine new bounded `SearchLimits`
  fields (defaults + hard ceilings), getters, builders and validation.
- `crates/quervant-core/src/search/mod.rs` — module declarations and re-exports.
- `crates/quervant-core/src/index/snapshot.rs` — process-wide monotonic
  `binding_id` plus read-only accessor.
- `crates/quervant-core/src/segment/reader.rs` — read-only
  `open_columns()` accessor that opens one bounded `ColumnReader` per segment; no
  wire bytes change.

Tests, benchmark, docs:

- `crates/quervant-core/tests/pr10_common/mod.rs` and 12 `pr10_*.rs` suites (70
  integration tests).
- `crates/quervant-core/benches/typed_analytics.rs` (registered in `Cargo.toml`).
- `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md`, `docs/pr-artifacts/pr-10/*`.

## Design decisions

- **Reuse, not replacement.** The existing `Query`, `Sort`, `TopK`, `Budgets`,
  `SegmentReader`, canonical `encode_group_key`/`GroupComponent`, `TimeBounds` and
  PR 9 effective-live masks are reused unchanged. Legacy `contract::result::Cursor`
  is untouched; `TypedCursor` is separate.
- **One comparator.** Heap, final ordering and cursor validation share
  `compare_candidates`, so pagination cannot disagree with ordering.
- **Effective liveness.** The scan iterates only `effective_live_docs`, never
  physical bitmaps, so deleted/obsolete documents never leak.
- **Pruning.** Only persisted `TimeBounds::prunes_positive_range` for a positive
  top-level `And` `TimeRange` conjunct on the same codec field. Tombstones widen
  bounds, so there are no false negatives.
- **Budget policy.** Defaults and hard ceilings follow the plan table; existing
  candidate/heap/work bounds and `Budgets` apply as a minimum. Over-budget is a
  typed `ResourceLimit`; no clamp, no truncation.
- **No format change.** No new section/feature/manifest/CURRENT bytes; the
  optional time-sorted physical layout is explicitly deferred.

## Deliberate non-goals preserved

No compound lexical+typed planner, no JSON/geo execution, no approximate
analytics, no distributed/vector work, no SQL parser, no automatic GC, no new
segment format. `quervant-core` remains free of etcd/RPC/cluster dependencies.

## Residual risks

See `adversarial-review.md` for the full list. The most significant are the
unreachable-at-scale checked-integer overflow error path, the in-process-only
cursor, and the 1M benchmark fixture exceeding the default PR 9 mutation-state
byte ceiling.
