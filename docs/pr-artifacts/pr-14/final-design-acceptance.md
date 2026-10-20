# PR 14 — Final design acceptance gate

**Status: NOT READY.**

| Phase | Status |
|---|---|
| F1 unified lexical/typed match stream (D1) | **DONE** |
| F2 selected identity + sort + full-tuple cursor (D2/D3/D8) | PARTIAL — exact `SelectedHit`/sort done for mixed; unified cursor NOT IMPLEMENTED (no PIT resolver) |
| F3 shared `ExecutionMeter` + batch admission (D4/D5) | PARTIAL — policy/capability admission DONE; shared work/memory meter NOT IMPLEMENTED |
| F4 compound aggregation + response contract (D7) | NOT IMPLEMENTED |
| F5 verticals/faults/RustFS/benchmarks | PARTIAL — mixed vertical DONE; RustFS BLOCKED; benchmarks NOT EXECUTED |
| Stable + MSRV fmt/clippy/tests | PASS |
| Workspace line coverage ≥85% | PASS — 91.22% |
| Persisted formats unchanged | PASS |
| Final-SHA CI + real RustFS | BLOCKED |

## Remaining STOP-relevant gaps
- **D2:** no authoritative `PitId`→`ReaderSnapshot` resolver; snapshot-bound runtime cursor not
  implemented. Batch cursor slots remain fail-closed.
- **D5/D6:** shared work-unit meter not threaded to scan sites; `SearchError::ResourceLimit`
  unchanged, so batch cannot report work-based `BudgetExceeded` kinds accurately.
- **D7:** no `contract::batch::AggregateResponse`; no matched-document aggregation visitor.

## Next steps (recommended order)
1. Implement `search/governance.rs::ExecutionMeter` and thread it through `evaluate_lexical_with`,
   `evaluate_query` and `VisitAggregate`, charging at existing charge sites.
2. Implement the snapshot-bound `RuntimeCursor` (binding id, query/sort fingerprints, full tuple,
   key, expiry) in `UnifiedRequest`/`UnifiedResponse`; keep batch PIT/cursor fail-closed.
3. Add `contract::batch::AggregateResponse` + `SearchResponse.aggregation` and a
   `visit_matches` aggregation visitor reusing `AggregationEngine`.
4. Add `pr14_cursor.rs`, `pr14_governance.rs`, `pr14_aggregate_batch.rs`,
   `pr14_storage_vertical.rs`; run RustFS verticals when an endpoint is provisioned.
5. Push and observe final-SHA CI.
