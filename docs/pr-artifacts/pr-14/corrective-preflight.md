# PR 14 — Corrective preflight

- Branch: `dev/pagination`
- HEAD at preflight: `e0e1dcbff9ab72288945c424c44fbabd008f4416` ("PR 14 Phase 0") on top of `main` @ `7ca1b2ec59fec648602e0e4a52e8f903a596f106` (merge base).
- Working tree at preflight: clean; corrective edits made after this record.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`.

## Inventory of exact signatures consulted

- `search/plan.rs`: private `Compiler`; `pub(crate) CompiledLeaf` (`Term`/`Phrase`/`MultiTerm`), `CompiledNode` (`MatchAll`/`Leaf`/`And`/`Or`/`Not`), `CompiledQuery { root, leaves, positive_leaf_indices, scoring_field_ids, codec }`; `pub(crate) fn compile(...)`.
- `search/execute.rs`: private `CandidateBudget`, `SegmentCandidateLedger`, `LeafData`, `ReservedSet`, `compute_stats` (in `score.rs`), `expand_query` (in `expand.rs`), `build_leaf_data`, `eval_node`, `score_segment`, `execute_segment_inner`, `pub(crate) execute_search`, `pub(crate) SearchWork`.
- `search/typed.rs`: `TypedSearcher::new(snapshot, schema, limits)` (no analyzer registry); private `Compiled`/`CompiledQuery`, `evaluate_query`, `ScanGuard`, `SearchAccumulator`; public `TypedCursor` (snapshot binding + fingerprint + last tuple + last key).
- `index/snapshot.rs`: `ReaderSnapshot::{binding_id, generation, view_ordinal, effective_live_docs, open_segment_reader, segment_count}`.
- `segment/reader.rs`: `SegmentReader::{stored, stored_doc, doc_keys, doc_key, live_docs}`.
- `contract/{result,batch,budget,capability,error}.rs`: `Cursor::{new,matches,validate}`, `SearchHit`, `SearchResponse`, `QueryRequest::validate`, `BatchQueryRequest::{validate_envelope,validate_envelope_with_policy}`, `BudgetKind`, `QueryError::{Cancelled,BudgetExceeded,ExpiredCursor}`.

## STOP register findings for this pass

| STOP | Status | Evidence |
|---|---|---|
| C1 cursor compatibility/expiry/PIT + complete tuple | **UNRESOLVED** | `contract::result::Cursor` has only pit/sort/last-key/expiry; `TypedCursor` already carries the full tuple but is typed-only. No public shape changed; see options below. |
| C2 lexical extraction changes BM25/stats/polarity | **NOT TRIGGERED** (approved by plan) but **NOT IMPLEMENTED** | Extraction is a large refactor of `execute.rs` ledger plumbing; not attempted in this pass. `score_segment` (`execute.rs:1402`) is the single scorer and must remain the source of truth. |
| C3 runtime work/memory charges observable | **TRIGGERED** | `SearchError::ResourceLimit { limit, requested }` carries no `BudgetKind`; `SearchLimits` (not contract `Budgets`) drive runtime bounds, so a slot cannot report an accurate `BudgetExceeded` kind or expose actual work without a targeted executor change. |
| C4 aggregation visitor consumes unified matched docs | **TRIGGERED** | `TypedSearcher::aggregate` re-validates and re-scans from a `Query`; `evaluate_query`/`Compiled` are private. Reusing one predicate requires exposing the typed compiled predicate or a matched-doc visitor. |
| C5 `SearchHit` lossless change | **RESOLVED** | Plan approved; changed `contract::batch::SearchHit.fields` to `Vec<(String, FieldValues)>`. |
| C6 authoritative `BudgetPolicy`/`CapabilitySet` at batch boundary | **TRIGGERED** | `execute_batch` currently takes no `BudgetPolicy`/`CapabilitySet`; `BatchQueryRequest::validate_envelope_with_policy` is not invoked. |
| C7 typed execution/corruption error | **RESOLVED** | Added `QueryError::ExecutionFailure { reason }`; `to_query_error` now maps each `SearchError` variant exhaustively. |
| C8 aggregate result shape in `SearchResponse` | **TRIGGERED** | `contract::aggregation` defines request shapes only; no approved runtime aggregate result shape exists in `contract::batch`. Batch aggregation remains rejected. |
| C10 real RustFS / coverage / CI | **BLOCKED** | No `QUERVANT_RUSTFS_*` endpoint in this environment; no push/CI. |

## Baseline test counts (pre-corrective)

`pr14_typed_predicates` 12, `pr14_json` 13, `pr14_projection` 10, `pr14_aggregation` 5, `pr14_batch` 10 — all passing.
