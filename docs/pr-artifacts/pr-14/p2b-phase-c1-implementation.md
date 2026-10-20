# PR 14 — P2B Phase C1 implementation (candidate local preflight/commit)

Checkpoint C1 only. No batch sink, segment ledger, heap, typed, projection or batch changes.

## Changed file

`crates/quervant-core/src/search/execute.rs` (`CandidateBudget` + unit tests only):

- Added non-mutating `preflight_segment(entries, bytes)` — checked additions and both local
  ceilings, no counter mutation.
- Added `commit_segment(entries, bytes)` — infallible after a matching preflight; checked
  `expect` documents the internal precondition (no saturation).
- Added non-mutating `preflight_global_bytes(bytes)` and `commit_global_bytes(bytes)`; the
  combined `global_bytes + segment_bytes` peak is checked in preflight.
- `reserve_segment` (test-only) and `reserve_global_bytes` (production) now call
  `preflight_*` then `commit_*`, preserving signatures and error kinds.
- `release_segment`/`release_global_bytes` checked underflow behavior unchanged.

## Tests added (executed)

- `c1_local_segment_exact_then_one_over_atomic` — entry and byte ceilings; counters unchanged on
  rejection.
- `c1_global_exact_then_one_over_atomic`.
- `c1_overflow_atomic` — `u64::MAX` `checked_add` overflow, no counter mutation.
- `c1_release_underflow_atomic` — global and segment underflow, no mutation.
- `c1_existing_callers_parity` — `reserve_*` counters equal explicit preflight + commit.

## Ownership

`CandidateBudget` remains a pure local counter owner with no stored batch borrow. The batch sink
is intentionally not wired in C1; `preflight_segment`/`commit_segment` are annotated
`#[allow(dead_code)]` until C2 wires the ephemeral `MemoryCharge` argument.
