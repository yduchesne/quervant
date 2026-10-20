# PR 14 — P2 batch governance implementation

## Implemented

### `search/batch_meter.rs` (new)
`BatchExecutionMeter` with checked `work_used`, `memory_current`/`memory_peak`, `response_used`
against policy-resolved ceilings. `preflight_work`/`commit_work`/`charge_work`,
`reserve_memory`/`release_memory`, `charge_response`. `BatchMeterError { kind, limit, requested }`
maps to `QueryError::BudgetExceeded { kind }`. Unit tests cover exact-limit, one-over atomicity,
memory peak, and overflow.

### `search/work.rs`
`MixedWorkMeter` gained `batch: Option<&mut BatchExecutionMeter>` and a `with_batch`
constructor. `charge_lexical`/`charge_typed`/`charge_scanned_postings` now preflight the local
typed/scanned/total limits **and** the batch work ceiling before committing either counter;
rejection leaves both unchanged. `MixedWorkMeter::new` is unchanged for non-batch callers.

### `search/execute.rs`
`evaluate_lexical_with` now charges one unit per examined effective-live document (typed when the
plan has typed leaves, otherwise lexical) and still polls cancellation per document. This closes
the MatchAll/typed-only/zero-hit work bypass.

### `search/unified.rs`
Crate-private `search_with_batch(..., &mut BatchExecutionMeter)`; public `search` delegates with
`None`. The shared meter is created once per slot with `with_batch` and threaded through all
query classes.

### `search/batch.rs`
- Resolves effective ceilings via `BudgetPolicy::effective` for `BatchAggregate`,
  `BatchMemoryBytes`, `BatchResponseBytes`; absent policy ceilings fail closed.
- `BatchLedger`/hit-count aggregate removed.
- Each successful slot computes deterministic `response_bytes`, reserves memory, then commits
  cumulative response bytes before appending `Success`; failure emits
  `BudgetExceeded { kind }` with no counter advance.
- `to_query_error`: query-local `ResourceLimit` now maps to
  `ExecutionFailure { reason: "query_resource_limit" }`, not `BatchAggregate`.
- Public `execute_batch` signature unchanged.

## Not implemented / partial
- Temporary candidate/heap/projection memory is still bounded by the query-local
  `CandidateBudget`/`ProjectionLedger`; only retained response bytes are wired to the batch
  memory meter. Peak retention across simultaneous query scratch + outcomes is therefore
  **partial** (B10/B11/B12/B13 not fully proven).
- B02/B03/B05/B07/B15/B18/B20/B22/B24 are covered indirectly or not added as dedicated tests.
- Public PIT cursors and batch aggregation remain fail-closed (out of scope).
