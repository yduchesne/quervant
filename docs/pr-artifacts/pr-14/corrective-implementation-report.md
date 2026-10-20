# PR 14 — Corrective implementation report

Head: `e0e1dcb` + local corrective edits (uncommitted at report time). Base `main` @ `7ca1b2e`.

## Implemented in this corrective pass

1. **Lossless batch hits.** `contract::batch::SearchHit.fields: Vec<(String, FieldValues)>`.
   `search::batch::project_hit` passes the five-state projection through unchanged; the lossy
   `flatten_hit` was deleted. Integration test `pr14_batch::b11_lossless_field_states`.
2. **Typed failure mapping.** New `QueryError::ExecutionFailure { reason }` in
   `contract/error.rs`. `search::batch::to_query_error` is exhaustive: cancellation →
   `Cancelled`, resource → `BudgetExceeded`, unsupported operator → `InvalidQuery`, fatal
   reads/corruption/score → `ExecutionFailure`. Unit test
   `search::batch::tests::error_mapping_preserves_contract_errors`.

## Not implemented (STOP / scope)

- **F1 mixed lexical+typed execution**: not implemented. Required exposing `execute.rs`
  leaf/score/ledger internals and the typed per-leaf compiler/evaluator; no degraded
  substitute was introduced. Mixed queries still return `mixed_predicate_stop_s1`.
- **F2 unified opaque cursor**: not implemented (STOP C1 — public cursor lacks the full tuple).
- **F4.4 cumulative work/memory meter**: not implemented (STOP C3 — `ResourceLimit` has no
  `BudgetKind`; engines bound work via `SearchLimits`).
- **F4.1/F4.2 batch policy/capability admission**: not implemented (STOP C6 — no authoritative
  policy/capability input at the batch boundary).
- **F5 compound aggregation / batch aggregation response**: not implemented (STOP C4/C8 — typed
  engine re-scans from a `Query`; no approved aggregate result shape in `SearchResponse`).
- **F6 real-boundary RustFS verticals/faults/benchmarks**: not executed (STOP C10 — no provider).

## Net diff in this pass

- `crates/quervant-core/src/contract/error.rs`: add `ExecutionFailure`.
- `crates/quervant-core/src/contract/batch.rs`: lossless `SearchHit.fields`.
- `crates/quervant-core/src/search/batch.rs`: lossless `project_hit`, exhaustive
  `to_query_error`, updated unit tests.
- `crates/quervant-core/tests/pr14_batch.rs`: `b11_lossless_field_states`.
- New corrective artifacts under `docs/pr-artifacts/pr-14/`.
