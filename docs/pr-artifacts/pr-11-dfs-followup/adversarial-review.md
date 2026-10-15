# PR 11 Follow-up B1 — Adversarial review

**State:** `fix/pr11-json-dfs-frontier` working tree on base `026f6e045b6cc0956210e8ea941a46d4a0906969`.
**Scope of change:** `segment/json_paths.rs` (extractor), plus test-only additions, tests, and these
artifacts. No wire, feature ID, public API, search semantics, `SearchLimits`, or default budget change.

## Threat model and counterexample disposition

| Counterexample | Disposition | Evidence |
|---|---|---|
| Wide object (10,000 members) queues 10,000 pending frames | Fixed — one cursor frame per active container | pre-fix high-water 10,000 → post-fix ≤ 1 (`b1_wide_object_frontier_is_bounded`) |
| Wide array (10,000 elements) queues 10,000 pending frames | Fixed | pre-fix high-water 10,000 → post-fix ≤ 1 (`b1_wide_array_frontier_is_bounded`) |
| Wide at multiple depths accumulates width × depth frames | Fixed — exhausted frames are popped before descending siblings | cursor algorithm + `b1_property_vs_recursive_reference` |
| Pending frontier escapes `max_single_allocation` | Fixed — `push_frame` preflights requested/proposed/actual capacity | `b1_stack_capacity_preflight` |
| Geometric `Vec` growth past the ceiling | Fixed — `try_reserve(1)` + post-reserve actual-capacity check, typed `LimitExceeded` | `b1_stack_capacity_preflight` |
| Traversal-order change alters persisted bytes | Rejected — output is sorted; golden SHA-256 unchanged | `t13_json_paths_golden_fixture` (`0528a62c…a02f`) |
| Duplicate member ambiguity | Unchanged rejection | `b1_multi_root_prefixes_and_duplicates`, existing duplicate tests |
| Depth/member/array/occurrence limits weakened | Unchanged; boundary tests added | `b1_depth_boundary_at_and_over`, `b1_member_bytes_and_array_boundaries` |
| Non-finite F64 regression | Unchanged; existing A1 tests still PASS | `nonfinite_f64_rejected_by_*`, `t_nonfinite_json_path_payloads_fail_at_segment_open` |
| Legacy fallback silently misses | Fallback uses the same hardened extractor; wide field matches | `b1_legacy_source_fallback_wide_field` |
| Compaction drops indexed-but-not-stored JSON | Rebuild from decoded occurrences; wide field survives remap | `b1_compact_wide_indexed_only_json` |
| Search sees a partial/false result | No partial vec on error; exact query results | `b1_wide_shallow_builder_search`, PR 11 suites |
| Remote/distributed interaction | Not applicable — local extractor only | N/A |

## Self-review of the implementation

- `DfsFrame` holds `parent_len: usize`, `next_child: usize`, `value: &JsonValue` only — no cloned
  `JsonValue`, entry list, iterator trait object, or per-child allocation.
- Traversal is iterative (no recursion) and pre-order; `path` is truncated to the frame's
  `parent_len` then extended by exactly one borrowed member/index seed.
- `child_at` returns borrowed references; `Member` names are borrowed from the tree.
- `push_frame` preflights `next_frames * size_of::<DfsFrame>()`, the proposed geometric capacity and
  the actual post-`try_reserve` capacity, converting allocation failure to `LimitExceeded`.
- `path` growth preflights `check_alloc::<JsonPathComponent>` and the existing depth check before
  `member.to_owned()`.
- `charge_occurrence` still enforces the retained-occurrence budget independently; stack bytes are not
  double-charged into `estimated`.
- `extract_field_paths` signature, final `sort_occurrences` and `reject_duplicate_paths` unchanged.

## Deviations accepted

- `#[cfg(test)]`-only `SegmentLimits::with_max_array_elements_for_test` to test the existing array
  guard cheaply (no release surface, no default change). The plan forbids new public limits; this is
  test-only.
- B1-T08 uses a modest budget rather than a literal sub-`width*frame_bytes` budget because the
  retained-occurrence charge dominates the same ceiling; frame preflight is isolated in B1-T07.

## Residual risks

Logical budgets are not a hard process-RSS ceiling. Other retained allocations (occurrence vectors,
cloned occurrence paths, stored-source decoding, builder staging) remain governed by their existing
budgets and are out of scope for this correction.
