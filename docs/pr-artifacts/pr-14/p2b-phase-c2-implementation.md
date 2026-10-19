# PR 14 — P2B Phase C2 implementation

## Implemented

`search/memory.rs`
- `MemoryCharge::preflight_release` + `SlotMemoryScope` implementation (checked balances,
  non-mutating preflight; `release` preflights before mutating).

`search/execute.rs`
- `SegmentCandidateLedger::reserve_with_memory` / `release_with_memory`: local preflight →
  batch preflight → batch commit → local commit; releases validate both balances first.
  2-arg `reserve`/`release` remain `None` wrappers for standalone.
- `evaluate_lexical_with` takes `&mut Option<&mut (dyn MemoryCharge + '_)>` and binds the live
  set, matched set and leaf-charge reservations to the batch scope.
- `build_leaf_data`, `build_phrase`, `score_segment` take the ephemeral sink; term/multi-term
  posting reservations, phrase candidate-upper reservation and the scored map now use
  `reserve_with_memory`/`release_with_memory`. `execute_segment_inner` passes `None`.

`search/unified.rs`
- `collect_mixed` destructures `&mut batch.work` / `&mut batch.memory`, builds
  `MixedWorkMeter` + `SlotMemoryScope`, and passes the scope into lexical evaluation. The scope
  drops at the end of `collect_mixed`, before the next slot.

## Tests executed (all PASS)
- `search::memory`: 11 (includes `preflight_release` balance).
- `search::execute`: 32 (includes C2 ledger tests: exact/one-over, local-reject isolation,
  release underflow, two-segment reuse, standalone parity).
- `pr14_batch_governance`: 7 — new `b09_segment_memory_is_charged` forces
  `BatchMemoryBytes` from live-set scratch.
- `pr14_batch` 12, `pr14_unified_cursor` 11, `pr14_f1_hardening` 23, `search::phrase` 7.
- fmt + `clippy -p quervant-core --all-targets --all-features -D warnings` PASS.

## Phrase scratch wiring (completed after the first draft)

`PhraseScratch::reserve/release` now take an ephemeral
`Option<&mut (dyn MemoryCharge + '_)>` and forward to `SegmentCandidateLedger::*_with_memory`.
`phrase.rs::match_phrase`, `phrase_chains` and `intersect_sorted_bounded` thread the sink through
all 14 `scratch.reserve/release` sites. `PhraseScratch::Drop` remains local-only (batch cleanup is
the slot scope's responsibility). So postings, phrase scratch, phrase candidate-upper, live/matched
sets and the scored map are all batch-accounted.

## Remaining C2 tests
The dedicated tests for exact postings/phrase/scored-map limits, cancellation/error during phrase
evaluation, failed-then-successful same-batch, and standalone/batch result parity are not all
added yet. Existing evidence: C2 ledger unit tests (5), `b09_segment_memory_is_charged`, phrase 7,
execute 32, PR14 regressions green.

## Status
C2 implementation is complete; C2 test matrix is partial. P2B NOT ACCEPTED; PR14 NOT READY
(C3–F, P3, P4 outstanding).
