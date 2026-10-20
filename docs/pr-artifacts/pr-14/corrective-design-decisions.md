# PR 14 — Corrective design decisions

Approved by the corrective plan (maintainer design approvals): (1) minimal lexical seam,
(2) opaque process-local cursor with complete sort tuple, (3) lossless batch projection,
(4) one cumulative batch budget meter, (5) approved `Exists` semantics.

## Decisions implemented in this pass

1. **Lossless batch projection (approval 3).** `contract::batch::SearchHit.fields` is now
   `Vec<(String, FieldValues)>`. `search::batch::project_hit` copies the internal
   `ProjectedHit.fields` unchanged, so absent/null/empty/single/multi round-trip exactly. The
   previous lossy `flatten_hit` was removed.
2. **Typed failures (approval-adjacent).** Added `QueryError::ExecutionFailure { reason }` and
   made `search::batch::to_query_error` exhaustive: contract query errors pass through,
   cancellation → `Cancelled { ClientCancellation }`, resource limits → `BudgetExceeded`,
   unsupported operators → `InvalidQuery(UnsupportedOperator)`, analyzer/segment/index reads,
   corruption and invalid scores → `ExecutionFailure`. No catch-all `UnsupportedOperator`.
3. **`Exists` semantics** remain the approved A09 contract (present including explicit null and
   empty multi), as implemented in the previous pass.

## Decisions deliberately NOT implemented (with reason)

- **Mixed lexical+typed execution.** The approved seam requires exposing `build_leaf_data`,
  `LeafData`, `score_segment`, the segment candidate ledger and `SnapshotStats`/`Expansion`
  from `execute.rs`, plus the typed per-leaf compiler/evaluator and a registry. This is a
  substantial refactor of two engines and was not completed. No degraded substitute was
  introduced: mixed queries still fail closed.
- **Unified opaque cursor.** `contract::result::Cursor` cannot carry the full sort tuple. A
  non-resumable legacy cursor plus a separate crate-controlled bound cursor was not added in
  this pass; no partial/incorrect resume was introduced.
- **Cumulative runtime work/memory meter.** Blocked by STOP C3: `SearchError::ResourceLimit`
  carries no `BudgetKind` and the engines bound work via `SearchLimits`, so a slot cannot
  report actual charges. The existing response-byte/hit ledger is retained but is not claimed
  to be work-accurate.
- **Batch aggregation response.** Blocked by STOP C8: no approved aggregate result shape in
  `contract::batch::SearchResponse`.
- **Batch policy/capability admission.** Blocked by STOP C6: `execute_batch` has no
  authoritative `BudgetPolicy`/`CapabilitySet` input.
