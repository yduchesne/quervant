# PR 14 — P2B Phase F final acceptance (B10a–B13j)

Tested tree: `dev/pagination` at HEAD `cfa5bfa145e8f5b4364431b1761978a5ea660c79`
plus the uncommitted Phase F working-tree changes
(`search/batch_meter.rs`, `search/projection.rs`, `tests/pr14_batch_memory.rs`,
`docs/pr-artifacts/pr-14/p2b-final-acceptance.md`). Toolchains: stable `1.98.1`,
MSRV `1.85.0`.

Primary suite: `crates/quervant-core/tests/pr14_batch_memory.rs` (31 tests, all pass).
Focused unit tests cover cases that require the private meter/scope internals.

## Traceability

| ID | Test | Invariant proven |
|---|---|---|
| B10a | `search::batch_meter::tests::b10a_disjoint_work_memory_borrows` + `pr14_batch_memory::b10a_work_and_memory_are_charged_together` | Disjoint `&mut work` / `&mut memory` without `RefCell`/`unsafe`; both charged through the public path. |
| B10b | `pr14_batch_memory::b10b_memory_exact_and_one_over` | Exact memory succeeds; first byte over is `BatchMemoryBytes`. |
| B10c | `search::batch_meter::tests::b10c_overflow_is_typed_and_atomic` + `b10c_overflow_is_typed` | `u64::MAX` reserve overflow typed and non-mutating; `u64::MAX` batch succeeds without wrap. |
| B10d | `search::projection::tests::b10d_checked_release_underflow` + `b10d_checked_release_underflow` | Release beyond reservation is `CorruptIndex`; no saturation. |
| B10e | `pr14_batch_memory::b10e_failed_slot_releases_temporaries_and_keeps_prior` | Failed slot releases temporaries; prior success survives. |
| B10f | `search::unified::tests::d_json_cancellation_cleanup` + `b10f_cancellation_has_no_success` | Cancellation releases slot memory; public path returns `Cancelled`, no Success. |
| B10g | `search::unified::tests::c3_path_heap_exact_one_over` + `b10g_heap_exact_and_one_over` | K+1 heap exact/one-over; bounded peak. |
| B10h | `c3_path_larger_replacement`, `c3_path_smaller_replacement`, `c3_replacement_reject_atomic` + `b10h_heap_replacement_boundary_is_atomic` | Replacement admission/rejection atomic; ordering preserved. |
| B10i | `b10i_segment_scratch_overlaps_heap` | Segment scratch + heap peak strictly exceeds the retained response alone. |
| B10j | `b10j_candidate_projection_overlap` + `e_projection_exact_and_one_over` | Projection payload is charged while candidate selection is live. |
| B11a | `b11a_geo_membership_exact_and_one_over` | Geo membership scratch exact/one-over and cleanup. |
| B11b | `b11b_geo_sort_distance_exact_and_one_over` + `d_geo_sort_path_exact_and_one_over` | Geo sort-distance scratch exact/one-over. |
| B11c | `b11c_json_transient_values_are_released` + `d_json_path_exact_and_one_over` | JSON transient occurrence charge is released and does not accumulate per document. |
| B11d | `b11d_geo_json_candidate_overlap_exceeds_each_local_path` + `d_json_geo_overlap` | Combined geo+JSON+lexical peak exceeds each single-path floor. |
| B11e | `b11e_shared_stored_bytes_are_not_charged` | Unprojected stored/shared immutable bytes are not slot-owned scratch. |
| B12a | `b12a_projection_exact_and_one_over` + `e_projection_exact_and_one_over` | Projection exact/one-over; memory floor equals the independent response-byte oracle. |
| B12b | `b12b_projection_failure_has_no_partial_success` + `e_projection_cancellation_cleanup` | Projection failure/cancellation returns no partial Success and releases scratch. |
| B12c | `b12c_handoff_does_not_double_or_uncount` + `e_prior_retained_response_overlaps_next_slot_scratch` | Handoff neither double-counts nor uncounts: two slots equal `2 × single`. |
| B12d | `b12d_prior_response_plus_next_scratch_rejects_second_slot` | First retained response + second slot scratch rejects the second; first survives. |
| B12e | `b12e_two_slot_current_is_sum_of_retained_responses` | Two-slot memory floor equals the sum of retained response charges. |
| B12f | `b12f_response_first_excess_releases_failed_slot` + `b13j_extreme_limits_are_typed_and_atomic` | `BatchResponseBytes` first-excess is typed; failed slot retains nothing. |
| B13a | `b13a_zero_hit_consumes_work` | Zero-hit query consumes work (`BatchAggregate` when exhausted). |
| B13b | `b13b_work_and_memory_have_distinct_provenance` | Work and memory failures report distinct `BudgetKind`s. |
| B13c | `b13c_query_local_limit_is_not_batch_exhaustion` + `b12b_projection_failure_has_no_partial_success` | Query-local candidate limit stays `ExecutionFailure{query_resource_limit}`. |
| B13d | `b13d_multi_segment_cancellation_leaves_no_success` | Multi-segment cancellation yields `Cancelled`, no retained Success. |
| B13e | `b13e_batch_and_standalone_parity` | Bit-exact key, score, fields, `total_hits` parity. |
| B13f | `b13f_matchall_typed_and_zero_hit_work_parity` | MatchAll charges exactly one unit per live document; term/typed add their own work (no double per-doc charge). |
| B13g | `b13g_sorted_geo_order_is_stable` + `d_geo_sort_path_exact_and_one_over` | Explicit geo-distance order is stable. |
| B13h | `b13h_five_states_and_no_unstored_leak` + `pr14_projection` | Five `FieldValues` states retained; unstored `raw` never leaks. |
| B13i | `b13i_three_slots_success_failure_success_shape` | `Success → memory Failure → Success` preserves ordered outcomes and later retention. |
| B13j | `b13j_extreme_limits_are_typed_and_atomic` + `b10c_overflow_is_typed_and_atomic` | Extreme/overflow limits are typed and atomic; `BatchResponseBytes` rejects at ceiling 1. |

## Executed validation

| Command | Result |
|---|---|
| `cargo test -p quervant-core --test pr14_batch_memory` | **31 passed**, 0 failed |
| `cargo fmt --all -- --check` (stable) | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable) | PASS |
| `cargo test --workspace --all-targets` (stable) | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | 91.60% lines / 87.68% functions / 91.32% regions |

Regression suites executed green: `pr14_batch` 12, `pr14_batch_governance` 7,
`pr14_f1_hardening` 23, `pr14_unified_cursor` 11, `pr14_unified_mixed` 14,
`pr14_json` 13, `pr14_projection` 10, `pr12_geo` 25, `search::typed` 32,
`search::unified::tests` 24.

## Exclusions / residual risks

- Phantom/generated data and shared immutable segment/snapshot caches are excluded
  by design (B11e verifies the exclusion).
- Nested heap inside `JsonOccurrence` is excluded; only the outer owned occurrence
  buffer is charged.
- Real RustFS acceptance, qualified benchmarks and final-SHA CI are **not executed**
  and remain PR 14 P4 blockers.
- P3 compound aggregation remains unimplemented.

## Status

**P2B: ACCEPTED** (A–F implemented, B10a–B13j executed, gates green).
**PR 14: NOT READY** (P3, P4 RustFS/benchmarks/final-SHA CI remain).
