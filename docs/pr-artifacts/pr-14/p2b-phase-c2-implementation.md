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

## C2 acceptance tests (executed)
- `c2_postings_exact_and_one_over` — independent `LIVE_SET_BYTES_PER_ENTRY`/`TERM_POSTING_BYTES`
  oracle; exact peak passes, one-under rejects postings atomically, both ledgers unchanged.
- `c2_phrase_scratch_exact_and_one_over` — real `PhraseScratch` sink; exact/one-over + cleanup.
- `c2_scored_map_exact_and_one_over` — `SET_BYTES_PER_ENTRY`+`SCORED_MAP_BYTES_PER_ENTRY` oracle.
- `c2_cancel_phrase_cleanup` — abandoned phrase scratch: local Drop + slot-scope batch cleanup.
- `c2_segment_exact_and_one_over_atomic`, `c2_local_reject_no_batch_change`,
  `c2_release_underflow_no_mutation`, `c2_two_segment_reuse_single_scope`,
  `c2_standalone_none_parity`.
- `pr14_batch_governance::b09_segment_memory_is_charged` (real batch path).
- Failed-then-successful slot isolation is covered by `pr14_batch::b02`/`b13`; overflow by
  `c1_overflow_atomic`/`batch_meter::overflow_is_typed_not_wrapped`; standalone/batch parity by
  `pr14_batch_governance::b21_one_slot_matches_direct_unified`.

## Status
C2 implementation and dedicated acceptance are complete for the approved scope. P2B NOT ACCEPTED;
C3 (heap), D (geo/JSON), E (projection/response), F (B10a–B13j) and P3/P4 remain. PR14 NOT READY.
## Status
C2 implementation is complete; C2 test matrix is partial. P2B NOT ACCEPTED; PR14 NOT READY
(C3–F, P3, P4 outstanding).
