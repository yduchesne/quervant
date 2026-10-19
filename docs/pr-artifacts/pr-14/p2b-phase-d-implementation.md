# PR 14 — P2B Phase D: geo and JSON memory accounting (ACCEPTED)

## Implemented

### Geo scratch
- `GeoScratchBudget` release is checked; `*_with_memory` methods add ephemeral
  `Option<&mut (dyn MemoryCharge + '_)>` admission (local projection → local ceiling →
  batch preflight → batch commit → local commit) and release (local preflight → batch
  preflight-release → batch release → local subtraction).
- `reserve_exact_with_memory` reconciles actual allocator capacity and releases the
  provisional reservation on allocation failure.
- `collect_mixed` drops `GeoMembership`/`GeoSortDistances` **before** releasing their
  batch reservations, so the charge is live for the whole allocation lifetime and
  overlaps lexical evaluation and K+1 heap retention.

### JSON occurrences
- `JsonAccess::occurrences` now charges `capacity * size_of::<JsonOccurrence>()` against
  the slot sink after building the buffer and returns the reserved byte count.
- `match_exists`, `match_equals`, `match_range`, `match_array_contains` execute their
  `ScanGuard` loops inside a closure, drop the occurrence buffer, then release the
  reservation — cancellation/error paths still release.
- Nested heap inside `JsonOccurrence` (path vectors, owned JSON nodes) is intentionally
  excluded; only the outer owned buffer is charged. Standalone paths pass `None`.
- Sink flows `evaluate_lexical_with` callback → `evaluate_unified` →
  `typed::evaluate_query` → JSON predicates. It is never stored in a long-lived
  structure; no `RefCell`, `unsafe`, global meter, or second batch meter.

## Tests (all PASS)

New `search::unified::tests` real-path tests (8):
- `d_geo_path_exact_and_one_over`
- `d_geo_path_overlaps_heap` (extra K+1 entry = `64 + key.len()`)
- `d_geo_sort_path_exact_and_one_over`
- `d_geo_standalone_batch_parity`
- `d_geo_failed_then_success_same_meter`
- `d_json_path_exact_and_one_over`
- `d_json_cancellation_cleanup` (committed charge, then `Cancelled`, current 0)
- `d_json_geo_overlap`

Existing suites:
- `search::typed` 32/32; `search::unified::tests` 20/20
- `pr12_geo` 25/25
- `pr14_batch` 12, `pr14_batch_governance` 7, `pr14_f1_hardening` 23,
  `pr14_unified_cursor` 11, `pr14_unified_mixed` 14, `pr14_json` 13
- `cargo fmt --check` PASS; `clippy -p quervant-core --all-targets --all-features -D warnings`
  PASS

## Status
Phase D is **ACCEPTED** (geo + JSON accounting and the required path matrix).
P2B overall remains open pending Phase E/F and the full workspace gates.
PR 14 remains NOT READY (P3 aggregation, P4 RustFS/benchmarks/final-SHA CI).
