# PR 14 — Remaining implementation report

Base `551f7f9` + uncommitted edits.

## P1 — Unified snapshot-bound pagination (DONE)

- New `search/unified_cursor.rs`: `UnifiedCursor` (private fields; read-only accessors) and the
  deterministic query+sort+schema fingerprint encoder.
- `search/unified.rs`:
  - `UnifiedRequest.after: Option<UnifiedCursor>`, `UnifiedResponse.next_cursor: Option<UnifiedCursor>`.
  - `execute_unified` validates the cursor binding/fingerprint/class **before** plan compilation
    and segment access.
  - `collect_mixed` counts `total_hits` for every match, then applies the canonical search-after
    filter (explicit `compare_candidates >`; relevance `score DESC,key ASC >`; typed-only key
    ascending), retains `K+1`, and emits the cursor from the last returned hit only when an extra
    candidate exists.
- Exported via `search/mod.rs`.
- `search/batch.rs` sets `after: None`; public PIT cursors remain fail-closed.

## P2 — Batch shared meter (NOT IMPLEMENTED)

`BatchLedger` still tracks response bytes and hit count only. No shared `MixedWorkMeter` is
threaded through `UnifiedSearcher`; B01–B12 are unexecuted.

## P3 — Compound aggregation (NOT IMPLEMENTED)

No contract-layer aggregate response, no matched-document visitor, batch aggregation still
rejected. A01–A12 unexecuted.

## P4 — RustFS/benchmarks/CI (BLOCKED)

No RustFS endpoint; no push/CI. R01–R04 and Q01–Q06 unexecuted.
