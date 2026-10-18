# PR 14 — F1 hardening implementation report

## H4 — Validation order (DONE)
`UnifiedSearcher::search` now validates, in order and before any projection compile/segment
open: `query.validate`, `sort.validate`, `top_k.validate`, `projection.validate`. Invalid sorts
return the established `SearchError::Query(QueryError::InvalidQuery(...))`.

## H2 — Bounded mixed candidate ownership (DONE)
- Added production `CandidateBudget::reserve_global_bytes` / `release_global_bytes`; the combined
  `global_bytes + segment_bytes` peak is checked. `CandidateBudget` remains the single logical-byte
  owner (no disconnected counter).
- Replaced the unbounded `BTreeMap<DocumentKey, SelectedHit>` with a bounded `BinaryHeap` of
  `MixedEntry` (K = `top_k.limit`), ordered by the existing `default_relevance_cmp` or
  `compare_candidates`. Eviction releases the evicted reservation exactly once.
- `total_hits` is counted for every matched effective-live document before top-K.
- `candidate_charge` conservatively accounts key bytes, per-tuple overhead and scalar payloads.
- Retained-candidate duplicate keys fail `CorruptIndex`; effective-live uniqueness is a snapshot
  invariant (residual: duplicates where neither copy is retained are not detected, matching the
  documented snapshot guarantee).

## H3 — Physical hit identity for all projections (DONE)
- All query classes now execute through the unified physical-hit path (`collect_internal` /
  `execute_unified`); the delegated pure paths, `project_selected` (all-segment key rescan) and
  `finish_delegated`/`lexical_search`/`typed_search` were removed.
- `project_selected_hits` fetches `reader.stored_doc(doc_id)` from the exact selected segment and
  verifies `reader.doc_key(doc_id) == hit.key`; mismatch is `CorruptIndex`.
- Consequence: pure lexical explicit canonical sorts are now supported; pure typed results/sort
  are preserved via the same `sort_tuple_for_doc` + `compare_candidates`.
- Pure typed / negative-only-lexical results now report `score: None` (no positive lexical
  contribution), matching the typed contract.

## H5 — Mixed geo-distance sorting (DONE)
- Removed the `mixed_geo_distance_sort` rejection.
- `build_geo_sort_distances` is now crate-private and is used per segment with the same bounded
  `GeoScratchBudget`; `sort_tuple_for_doc` receives `Some(&geo_sort)`. Missing/multivalue/ties and
  descending semantics are the existing PR 10 behavior (no new math).

## H1 — Single cumulative work meter (NOT IMPLEMENTED; STOP H1)
See preflight STOP H1. Lexical and typed still use independent `SearchWork`/`ScanGuard` counters;
the mixed total-work invariant I01/I02 is **not** met.

## H6 — Tests
New `tests/pr14_f1_hardening.rs` (14 tests): S01/S02/S03/S05 bit-exact mixed parity, V01–V05
validation, G01–G03 geo sort, M02 top-K total, P02 physical version. Existing
`pr14_unified_mixed` (14) and `pr14_batch` (12) remain green.
