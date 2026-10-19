# PR 14 — P2B Phase E: projection/response handoff (IMPLEMENTED)

## Implementation

- `projection::ProjectionLedger::release` is checked: underflow returns
  `SearchError::CorruptIndex`; no saturating subtraction.
- `ProjectionLedger::reserve_with_memory` preflights the local ledger and the optional
  batch sink, then commits both; a rejected reservation mutates neither.
- `project_selected_hits` receives the slot sink and charges `projected_hit_bytes`
  through it, so projection is bounded by the batch memory ceiling while the
  projection-local limit still applies.
- `UnifiedSearcher::search_with_batch_retained` runs the batch slot with retention:
  after projection it computes the deterministic response byte model
  (`response_bytes_for`: 32 + per-hit 24 + key + 8 + projected fields), reserves the
  response-only overhead, and calls `SlotMemoryScope::finish_success(response_bytes)`
  so the projected payload transfers to retained ownership without release/re-reserve.
  `search` and direct `search_with_batch` keep `finish_success(0)` and retain nothing.
- `batch::execute_batch` uses the retained path, no longer re-charges memory on success,
  and releases the retained bytes if response-byte computation or the cumulative
  `BatchResponseBytes` charge fails. Prior successful outcomes remain resident.

## Tests (PASS)

Phase E `search::unified::tests`:
- `e_projection_exact_and_one_over`
- `e_prior_retained_response_overlaps_next_slot_scratch` (prior 11 + slot peak rejects,
  current stays 11; exact 10 + slot peak succeeds; later success preserves 10)
- `e_projection_cancellation_cleanup` (cancelled, current 0)
- `e_projection_standalone_and_batch_parity`
- `projection::ledger_bounds_are_checked` includes checked-release underflow.

Regressions: `search::typed` 32, `search::unified::tests` 24, `pr12_geo` 25,
`pr14_batch` 12, `pr14_batch_governance` 7, `pr14_projection` 10, `pr14_json` 13.
Workspace `cargo test --workspace --all-targets` PASS.

## Gates

- `cargo fmt --all -- --check` PASS; `cargo +1.85.0 fmt --all -- --check` PASS.
- `cargo clippy --workspace --all-targets --all-features -D warnings` PASS (stable 1.98.1).
- `cargo +1.85.0 clippy --workspace --all-targets --all-features -D warnings` PASS.
- `cargo +1.85.0 test --workspace --all-targets` PASS.
- `cargo llvm-cov --workspace --all-targets --fail-under-lines 85`: **91.53% lines**,
  87.61% functions, 91.26% regions.

## Status
Phase E **IMPLEMENTED**. P2B acceptance still requires Phase F
(`pr14_batch_memory` B10a–B13j and the final evidence/review artifacts).
