# PR 14D — compatibility report

Implementation commit `d0e1bbb`; baseline `2cb91be` (PR #62 merged).

## 1. Scope of the diff

Changed paths:

- `crates/quervant-core/src/search/typed.rs` — scratch owner, metered occurrence
  push, single-pass winner selection, typed caller plumbing.
- `crates/quervant-core/src/search/unified.rs` — pass the existing batch memory
  scope to the JSON sort helper.
- `crates/quervant-core/src/segment/json_paths.rs` — `ScratchCharge` sink,
  admitted capacity/owned-byte growth, `extract_field_paths_charged`.
- `crates/quervant-core/src/segment/mod.rs` — crate-private re-exports.
- `crates/quervant-core/tests/{pr14_storage_vertical,pr14b_json_memory}.rs` and
  new `pr14d_json_sort_memory.rs`.
- `docs/pr-artifacts/pr-14d/*` and an additive note in
  `docs/pr-artifacts/pr-14c/resource-risk-disposition.md`.

No changes to segment/manifest/`CURRENT` formats, codec versions, JSON wire
version, cursor serialization, public APIs, dependencies, CI workflows, or
distributed crates.

## 2. Public API and contracts

- `execute_batch` still rejects PIT/cursor-bearing requests with
  `InvalidBatch(PinnedContextRequired)`; `execute_batch_pinned` remains the only
  pinned entry point.
- `Cursor`/`UnifiedCursor` shapes are unchanged; no new serialization.
- `SearchError`/`QueryError` variants are unchanged. The intentional tightening
  is that JSON-sort workloads previously admitted under a budget that ignored
  occurrence/winner scratch may now fail with the **existing** typed
  `BudgetExceeded { kind: BatchMemoryBytes }`.
- Standalone `TypedSearcher::search` keeps query-local limits and passes no batch
  sink (`None`); ordering is unchanged.

## 3. Persisted-format compatibility

- No fixture bytes were modified. Frozen identities still hold:
  - `json_paths_golden.seg` — 1,186 B, SHA-256
    `0528a62cdb02fcd08754d5776f23bd16de787f788597ade93d5dfbc65c30a02f`
    (asserted by `d07` and the existing B18/B19 regression).
  - `golden.seg` / `golden_norms.seg` / PR 07 index / M1 fixture unchanged.
- Historical JSON **v1** read compatibility: `b18_b19_historical_json_segment_compatibility`
  and `real::b18_real_historical_json_remote` remain green; corrupt bytes and
  unsupported major versions still fail typed.
- Legacy segments without the JSON-path section retain the stored-source
  fallback, duplicate detection, and the typed
  `UnsupportedOperator("json_path_legacy_unstored")` failure for unstored fields.

## 4. Ordering and semantic equivalence

- Single-pass `Min`/`Max` selection preserves the canonical comparator
  (`canonical_scalar_cmp`), type ranks, missing/null placement and first-winner
  tie behavior. `d03`, `d08` and the unchanged PR 14A/14B suites assert key
  order and totals.
- Typed standalone, unified batch and pinned batch return the same keys, totals
  and cursor presence for the same JSON sort (`d04`); provider `d11` compares
  remote keys to a hand-authored local oracle.

## 5. Durability and fault equivalence

- No storage/durability code changed. Existing recovery expectations hold on the
  real provider: F01–F09/F10 (10 iterations each), PR 13 proxy/crash suites and
  objectstore conformance all pass after the change.
- Cancellation remains typed and publishes no partial success (`d06`, provider
  `d12`, existing `pr14a` t13).

## 6. Migration and rollback

- No migration, format bump, feature flag or cursor version is required.
- Rollback is a revert of the PR 14D commits; no user data or remote committed
  objects need modification.
- The stricter admission may reject previously underbudgeted sorts by design;
  the failure is the existing typed budget error, not a new error surface.
