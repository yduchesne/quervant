# PR 14 — P2B C2 progress handoff

## Implemented and validated (this session)

- `search/memory.rs`: `MemoryCharge::preflight_release` (committed earlier; `search::memory`
  11/11).
- `search/execute.rs`:
  - `SegmentCandidateLedger::{reserve_with_memory, release_with_memory}`: local preflight →
    batch preflight → batch commit → local commit; releases validate both balances first.
    2-arg `reserve`/`release` remain wrappers passing `None`.
  - `evaluate_lexical_with` takes `memory: &mut Option<&mut (dyn MemoryCharge + '_)>` and binds
    the live-set, matched-set and leaf-charge reservations to the batch scope.
  - C2 unit tests: `c2_segment_exact_and_one_over_atomic`,
    `c2_local_reject_no_batch_change`, `c2_release_underflow_no_mutation`,
    `c2_two_segment_reuse_single_scope`, `c2_standalone_none_parity` (5/5).
- `search/unified.rs`: `collect_mixed` destructures `&mut batch.work` / `&mut batch.memory`,
  builds `MixedWorkMeter` and `SlotMemoryScope`, and passes the scope into lexical evaluation.
  The scope drops at the end of `collect_mixed` (before the next slot), releasing temporary batch
  bytes.
- Validated: fmt, `clippy -p quervant-core --all-targets --all-features -D warnings`, `search::execute`
  32/32, `search::memory` 11/11, PR14 batch/governance/cursor/f1 suites (12/6/11/23).

## Remaining C2 (exact next edit)

`build_leaf_data`, `build_phrase` and `score_segment` still reserve leaf postings, phrase scratch
and the scored map **locally only**. Thread the same ephemeral sink through them using the
`_with_memory` ledger methods:

1. `build_leaf_data`: add `mut memory: Option<&mut (dyn MemoryCharge + '_)>`; replace the two
   `ledger.reserve(1, TERM_POSTING_BYTES)` with `reserve_with_memory(..., memory.as_deref_mut())`;
   pass `memory.as_deref_mut()` to `build_phrase`.
2. `build_phrase`: add the same parameter; replace `ledger.reserve/release` with
   `reserve_with_memory`/`release_with_memory`; construct
   `PhraseScratch::new(ledger, memory.as_deref_mut())`.
3. `PhraseScratch`: add `memory: Option<&'m mut (dyn MemoryCharge + '_)>` and a third lifetime;
   its `reserve`/`release` forward `self.memory.as_deref_mut()`; `Drop` passes `None`; update
   `phrase_scratch_for_test` and the Drop impl lifetime.
4. `score_segment`: add the parameter and use `reserve_with_memory`.
5. Call sites: `evaluate_lexical_with` passes `memory.as_deref_mut()` to both; the standalone
   `execute_segment_inner` passes `None`.
   Use `Option<&mut (dyn MemoryCharge + '_)>` (not `&mut dyn MemoryCharge`) to avoid the
   `'static` object-lifetime error.

Then add C2 integration tests (two segments sharing one real scope, batch/local rejection
isolation, retained-response overlap, cancellation cleanup, failing-then-successful batch) and run
the phase gates.

## Status

**C2 PARTIAL. P2B NOT ACCEPTED.** C3 (K+1 heap), D (geo/JSON), E (projection/response) and F
(B10a–B13j) remain. PR 14 still requires P3, P4 RustFS/benchmarks and final-SHA CI.
