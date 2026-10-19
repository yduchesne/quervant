# PR 14 — P3 compound aggregation implementation

Status: IN PROGRESS. Do not claim P3 or PR 14 accepted.

Baseline: `dev/pagination` at `a444db27b4db87cbd190e8542bd3ff24601ee434` (P2B accepted/committed).

## Slice log

### P3-0 — baseline
- Working tree clean; P2B baseline preserved.
- `contract::batch::SearchResponse` has no aggregation field; the only production
  literal is `search/batch.rs::execute_slot` (plus `SearchResponse::empty()`).
- Runtime result types (`AggregateResponse`, `AggregateGroup`, `GroupValue`,
  `MetricValue`, `NumericAggregate`) live in `search/analytics.rs`; `contract`
  must not depend on `search`.
- `search/typed.rs::visit_aggregate{,_inner}` owns decoding/group/metric logic and
  is reusable with a `TypedPlan` built from the schema.
- `search/unified.rs::collect_mixed` owns the single effective-live membership pass.
- `execute_slot` still rejects aggregation with `batch_aggregation_pending_stop_s1`.

### P3-1 — contract response shape (this slice)
- Added data-only `AggregationResult`, `AggregationGroupResult`,
  `AggregationGroupValue`, `AggregationMetricValue`, `NumericAggregate`,
  `FrequencyEntry` in `contract/aggregation.rs`.
- Added `SearchResponse.aggregation: Option<AggregationResult>` (None for ordinary
  search and `empty()`).
- Conversion from runtime analytics lives in `search` (no `contract -> search`).

## Invariant mapping (to be completed with executed evidence)
| ID | Status |
|---|---|
| P3-I01 | pending |
| P3-I02 | pending |
| P3-I03 | pending |
| P3-I04 | in progress |
| P3-I05 | pending |
| P3-I06 | pending |
| P3-I07 | pending |
| P3-I08 | pending |
| P3-I09 | pending |
| P3-I10 | pending |

### P3-2/3/4 (partial) and P3-5 — committed at `d797878b9b8fe058d3b1dc827909df337404958e`

Implemented:
- Contract-only result shape (`AggregationResult`, `AggregationGroupResult`,
  `AggregationGroupValue`, `AggregationMetricValue`, `NumericAggregate`,
  `FrequencyEntry`) and lossless conversion in `search::analytics`.
- `SearchResponse.aggregation: Option<AggregationResult>`; `None` for ordinary
  search/`empty()`. One production literal updated (`batch::execute_slot`).
- Extracted `validate_aggregate_fields`, `resolve_bucket`, `prepare_aggregation`,
  and made `visit_aggregate` `pub(crate)`; `TypedSearcher::aggregate` keeps the
  same adapter and standalone behavior.
- `collect_mixed` now runs a single membership pass, invokes the shared
  aggregation adapter for every matched effective-live document **before** heap
  admission/cursor filtering, and finishes after the segment loop.
- Batch integration: removed only `batch_aggregation_pending_stop_s1`; cursor
  STOP S2 rejection remains; `execute_slot` uses the combined
  `search_with_batch_aggregation_retained` path and populates
  `SearchResponse.aggregation`.
- Shared response sizing: `batch::aggregation_result_bytes` is used by both the
  retained handoff (`unified::response_bytes_for`) and `BatchResponseBytes`.
- Updated `pr14_batch::b08` to assert a successful aggregation slot.

Tests executed (PASS): `pr14_compound_aggregation` 9 —
T01 (mixed AND all matches, top_k independent), T02 (lexical OR JSON + geo),
T05 (sort/top_k independence), T07 (count/sum/min/max/avg/distinct), T08
(frequency presence), T10 (empty global vs grouped empty), T11 (None
compatibility/lossless response), T22 (invalid group/bucket typed per-slot),
T26 (cursor+aggregation fail-closed). Full `cargo test -p quervant-core
--all-targets` PASS; `cargo clippy -p quervant-core --all-targets --all-features
-D warnings` PASS; `cargo fmt --check` PASS.

## Remaining for P3 acceptance (NOT DONE)
1. **P3-I05/I06 — aggregation memory sink.** `AggregateMemory` is still
   local-only. Thread an ephemeral `Option<&mut (dyn MemoryCharge + '_)>`
   through `AggregationEngine::{add_document, reserve_staging,
   release_transient, finish, ensure_global_group}` and `visit_aggregate`.
   Order: local preflight → batch preflight → batch commit → local commit;
   releases preflight both then release batch then local. In `collect_mixed`,
   pass `scope.as_mut()` per matched document; drop staging before release.
   Retained engine state must stay charged through the heap/projection overlap
   and be released before the single `finish_success` response handoff. Add
   exact/one-over/overflow/underflow unit tests.
2. **Remaining T-matrix:** T03, T04 (multi-segment + mutation/PIT), T06
   (missing/null/empty/multivalue), T09 (time buckets), T12 (canonical order
   across segments), T13 (local group budgets), T14 (work exact/one-over), T15
   (overflow), T16/T17/T18 (peak/response overlap exact), T19 (S/F/S), T20
   (cancellation), T21 (failure cleanup), T23 (`TypedSearcher::aggregate`
   differential), T24 (full P2B/PR14 regressions), T25 (malformed/pre-scan
   cancellation).
3. **Final gates:** stable + MSRV fmt/clippy/workspace tests, coverage ≥85%,
   `pr14_batch_memory` 31, all PR14 suites, then update this artifact with
   executed evidence. PR 14 remains NOT READY (P4 RustFS/benchmarks/final-SHA
   CI).
