# PR 14 — P2B Phase C3 implementation

## Implemented

`search/execute.rs`
- `CandidateBudget::preflight_release_global_bytes` (checked, non-mutating); `release_global_bytes`
  now uses it.
- `reserve_global_bytes` is test-only now (unified admission uses preflight+commit).

`search/unified.rs`
- Private dual-ledger helpers:
  - `heap_preflight_insert` (local preflight → batch preflight, no mutation)
  - `heap_commit_insert` (batch commit → infallible local commit)
  - `heap_preflight_release` (local release preflight + batch `preflight_release`)
  - `heap_commit_release` (batch release → checked local release)
- Heap admission (`len < K+1`): preflight both, commit batch then local, then push.
- Noncompetitive candidate: no reservation/mutation.
- Replacement is **conservative overlap-aware**: both the old (still retained) and new charges
  are live during admission. Sequence: preflight new, preflight release old, commit new (batch
  then local), pop and drop the old entry, commit release old, push new. A preflight failure
  leaves the heap and both ledgers unchanged; no pop occurs before admission is proven.
- The ephemeral `SlotMemoryScope` survives segment evaluation and heap admission; the C2
  `memory_sink` borrow ends at its last use (no explicit `drop` needed; NLL ends the borrow).

## Tests executed (all PASS)
- `search::unified::tests::c3_insert_exact_one_over_atomic` — exact local+batch limit passes,
  one-over rejects with both ledgers unchanged, release returns to zero.
- `search::unified::tests::c3_replacement_overlap_peak` — old 30 + new 35 admitted against a
  65-byte batch ceiling (peak includes both), final local/batch charge is 35.
- Existing `pr14_unified_cursor` 11, `pr14_f1_hardening` 23, `pr14_batch` 12,
  `pr14_batch_governance` 7 (incl. `b09`), `search::execute` 36, `search::phrase` 7,
  `search::memory` 11.
- `cargo fmt --check` PASS; `clippy -p quervant-core --all-targets --all-features -D warnings`
  PASS.

## Residual C3 work (not yet authored)
The full `c3_*` matrix is not complete: real `collect_mixed`-path exact/one-over, larger/smaller
replacement, noncompetitive zero-charge, replacement-rejection-preserves-heap, failed-next-slot,
retained-response+heap overlap, overflow, and K+1 cursor parity under binding limits. The helper
tests prove the dual-ledger/overlap algorithms; the path-level tests remain.

## Status
C3 implementation complete; C3 test matrix partial. **P2B NOT ACCEPTED.** D (geo/JSON), E
(projection/response), F (B10a–B13j), P3 and P4 remain. PR14 NOT READY.
