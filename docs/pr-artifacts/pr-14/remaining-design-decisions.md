# PR 14 — Remaining design decisions

## P1 — Snapshot-bound unified cursor (implemented)

- `search/unified_cursor.rs`: `UnifiedCursor { snapshot_binding, fingerprint, last_sort, last_score, last_key }`, private fields, crate-constructed, no serialization, no `PitId`.
- Fingerprint is a SHA-256 digest over a version tag (`quervant-unified-cursor-v1`), a canonical length-prefixed encoding of the validated `Query` AST (variant tags, child counts/order, IEEE bits, JSON/paths/IP/geo), the `CodecSchema` (field id/name/type/cardinality/options/analyzer+normalizer bindings) and the complete `Sort` (direction, missing placement, multi selector, JSON path, geo origin). It never hashes `Debug`, randomized hashes or expansions, and excludes `top_k`/projection.
- Validation order in `execute_unified`: query → sort → top_k → projection (in `search`) → cursor binding/fingerprint/class → plan compile → segment open.
- `last_score` is `Some` only for relevance ordering with a positive lexical leaf; `None` for typed-only relevance and all explicit sorts. Class mismatch is a typed `CursorSortMismatch`.
- Search-after filters **after** `total_hits` is counted, keeps `K+1` candidates in the existing bounded heap/ledger, and emits `next_cursor` from the last returned hit only when the extra candidate exists.

## P2/P3/P4 — not implemented in this pass

- P2 requires a borrowed shared meter threaded through `UnifiedSearcher` into `execute_batch`; not implemented. `BatchLedger` still meters response bytes and hit count only.
- P3 requires contract-layer aggregate result types plus a matched-document visitor; not implemented.
- P4 requires a provisioned RustFS endpoint and CI push; blocked.
