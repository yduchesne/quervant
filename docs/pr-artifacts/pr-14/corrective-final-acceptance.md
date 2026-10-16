# PR 14 — Corrective final acceptance

**Status: NOT READY.** Two of the nine review blockers are corrected; the remainder are blocked
or not implemented. No DONE/merge-ready claim.

| Gate | Status |
|---|---|
| Corrective preflight recorded | DONE |
| F1 reusable lexical seam + mixed Boolean engine | NOT IMPLEMENTED |
| F2 selected-hit identity + full-tuple cursor | NOT IMPLEMENTED (STOP C1) |
| F3 lossless projection (contract/batch) | DONE (states + mapping); exact HitRef retrieval NOT IMPLEMENTED |
| F4 shared work/memory meter + policy/capability admission | NOT IMPLEMENTED (STOP C3/C6); typed error mapping DONE |
| F5 compound aggregation + batch aggregation response | NOT IMPLEMENTED (STOP C4/C8) |
| F6 local/Fake/RustFS verticals, faults, benchmarks | NOT EXECUTED / BLOCKED (C10) |
| Stable + MSRV fmt/clippy/tests | PASS |
| Workspace line coverage ≥85% | PASS — 91.22% |
| I01–I16 mapped to passing tests | PARTIAL (I01/I03/I05/I07/I09/I11/I12/I14/I16 incomplete) |
| Unchanged persisted formats | PASS |
| Final-SHA CI + real RustFS | BLOCKED |

## Open STOP decisions requiring a maintainer decision

1. **C1** — public cursor vs complete tuple. Options: (a) add a crate-controlled opaque runtime
   cursor payload (recommended; legacy `Cursor::new` becomes non-resumable); (b) version the
   public `Cursor` contract. Unified search currently has no cursor.
2. **C3** — runtime work/memory observability. Needed: add a `BudgetKind` (or equivalent) to
   `SearchError::ResourceLimit` / expose a shared `SearchWork` meter to the batch ledger.
3. **C4/C8** — aggregate result shape in `SearchResponse`. Needed: an approved contract result
   type (e.g. `contract::aggregation::AggregateResponse` mirroring the runtime groups) plus an
   optional batch outcome field.
4. **C6** — authoritative `BudgetPolicy`/`CapabilitySet` at the batch boundary.

## Minimal next steps (recommended order)
1. Approve C1/C3/C4/C6/C8 amendments.
2. Implement F1 (extract `execute.rs` leaf/score seam; add `search/unified_plan.rs`; evaluate
   mixed trees over effective-live docs; score via the existing `score_segment`).
3. Implement F2 using the typed `TypedCursor` concepts for every sort path.
4. Implement F3 exact `SelectedHit {segment_index, doc_id}` projection.
5. Implement F4 cumulative meter + policy/capability admission.
6. Implement F5 unified aggregation + batch aggregate response.
7. Run F6 verticals, benchmarks, final-SHA CI.
