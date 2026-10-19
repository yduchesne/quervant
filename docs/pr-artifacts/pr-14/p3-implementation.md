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
