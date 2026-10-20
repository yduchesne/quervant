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

## FINAL P3 ACCEPTANCE

Implementation commit: `1a54de2a4653d69e475bc03fd3d5bc9fb4e68602`
(`feat(search): govern aggregation memory and complete P3 acceptance matrix`).
Acceptance-matrix commit: `0e163260d94a226c4843f328f30d53818078e0ba`
(`test(search): complete PR14 P3 compound aggregation acceptance matrix`).
Recorded on `dev/pagination`; this artifact commit is documentation-only.

### Shared-memory ownership and release order
- `AggregateMemory::{reserve_retained_with, reserve_transient_with,
  release_transient_with, release_retained_with}` validate the local ledger, then
  preflight/commit (or preflight-release/release) the shared `MemoryCharge`, then
  mutate the local ledger. A rejected admission mutates neither ledger.
- `AggregationEngine::{add_document, reserve_staging, expand_group_values,
  ensure_global_group, finish}` and `visit_aggregate`/`visit_aggregate_inner`
  thread an ephemeral `Option<&mut (dyn MemoryCharge + '_)>`; the sink is never
  stored in a long-lived structure.
- Per-document staging is released after the decoded/expansion buffers drop.
  `finish` releases the retained engine state and output transient only after
  constructing the owned groups; the response payload is then charged exactly
  once by the existing `finish_success` handoff.
- Standalone `TypedSearcher::aggregate` passes `None` and keeps local-only
  behavior. No second batch meter, `RefCell`, `unsafe`, global state, or
  saturating release arithmetic was introduced.

### T01–T26 traceability (all executed)
| ID | Test | Result |
|---|---|---|
| T01 | `t01_mixed_lexical_and_typed_range_all_matches` | PASS |
| T02 | `t02_lexical_or_json_and_geo_filter` | PASS |
| T03 | `t03_cross_domain_predicate` | PASS |
| T04 | `t04_multi_segment_aggregation` | PASS |
| T05 | `t05_sort_and_top_k_do_not_change_groups` | PASS |
| T06 | `t06_group_states_and_multivalue` | PASS |
| T07 | `t07_exact_metrics` | PASS |
| T08 | `t08_frequency_top_k_stable_ties` | PASS |
| T09 | `t09_time_bucket_boundaries` | PASS |
| T10 | `t10_empty_match_global_and_grouped` | PASS |
| T11 | `t11_none_compatibility_and_lossless_response` | PASS |
| T12 | `t12_canonical_order_is_stable` | PASS |
| T13 | `t13_local_group_budget` | PASS |
| T14 | `t14_aggregation_work_exact_and_one_over` | PASS |
| T15 | `t15_aggregate_overflow_is_typed_and_isolated` (exact i128 sum, no wrap) | PASS |
| T16 | `t16_aggregation_memory_exact_and_one_over` | PASS |
| T17 | `t17_response_bytes_exact_and_one_over` | PASS |
| T18 | `t18_retained_aggregation_response_overlap` | PASS |
| T19 | `t19_success_failure_success_order` | PASS |
| T20 | `t20_cancellation_has_no_success` (pre-scan cancellation) | PASS |
| T21 | `t21_failure_preserves_prior_success` | PASS |
| T22 | `t22_invalid_aggregation_is_typed_per_slot` | PASS |
| T23 | `t23_typed_aggregation_differential` | PASS |
| T24 | P2B `pr14_batch_memory` 31 + PR14 regressions (below) | PASS |
| T25 | `t20_cancellation_has_no_success` + `t22_invalid_aggregation_is_typed_per_slot` (malformed/pre-scan) | PASS |
| T26 | `t26_cursor_with_aggregation_fails_closed` | PASS |

Unit coverage: `search::analytics::tests::p3_sink_exact_one_over_overlap_and_underflow`
(exact/one-over, retained+transient overlap, underflow non-mutation, scope cleanup).

### Executed validation
| Command | Result |
|---|---|
| `cargo test -p quervant-core --test pr14_compound_aggregation` | 24 passed |
| `cargo test -p quervant-core --test pr14_batch_memory` | 31 passed |
| `cargo test -p quervant-core --test pr14_unified_mixed` | 14 passed |
| `cargo test -p quervant-core --test pr14_unified_cursor` | 11 passed |
| `cargo test -p quervant-core --test pr14_json` | 13 passed |
| `cargo test -p quervant-core --test pr12_geo` | 25 passed |
| `cargo test -p quervant-core --test pr14_projection` | 10 passed |
| `cargo test -p quervant-core --test pr14_batch_governance` | 7 passed |
| `cargo test -p quervant-core --test pr14_batch` | 12 passed |
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets --all-features -D warnings` (stable + 1.85.0) | PASS |
| `cargo test --workspace --all-targets` (stable + 1.85.0) | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | **91.61% lines**, 87.71% functions |

### Residual risks and exclusions
- Aggregation `finish` releases retained engine state and output transient after
  constructing owned groups; the public payload is charged at the single response
  handoff. There is no uncharged allocation across a slot boundary.
- Heap rejection removes a document from hit selection only; aggregation is
  invoked before heap admission and covers all matches.
- Nested `JsonOccurrence` heap and shared immutable segment/snapshot bytes remain
  excluded per P2B.
- Real RustFS, qualified benchmarks and final-SHA CI are **not executed**; they
  remain PR 14 P4 blockers.

### Status
**P3: ACCEPTED** (implementation, T01–T26 evidence, stable/MSRV/coverage gates).
**PR 14: NOT READY** (P4 RustFS/benchmarks/final-SHA CI).
