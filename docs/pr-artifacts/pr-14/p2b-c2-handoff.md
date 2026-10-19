# PR 14 — P2B C2 handoff (partial)

HEAD `7c0c2c9` + this session's validated change. Clean apart from this artifact.

## Completed and validated in this session

- `search/memory.rs`: added `MemoryCharge::preflight_release(&self, bytes) -> SearchResult<()>`
  and the `SlotMemoryScope` implementation (validates the scope's temporary balance; the meter
  current is always >= temporary, so the subsequent checked meter release cannot underflow).
  `SlotMemoryScope::release` now calls `preflight_release` before mutating.
- New test `c2_memory_preflight_release_balances` (11/11 `search::memory` tests pass).
- Gates run: `cargo fmt --check` PASS; `cargo clippy -p quervant-core --all-targets
  --all-features -- -D warnings` PASS; `cargo test -p quervant-core --lib search::memory` PASS.

## Exact next source edits (C2 ledger integration)

1. `search/execute.rs::SegmentCandidateLedger`:
   - `fn reserve(&mut self, entries, bytes, memory: Option<&mut dyn MemoryCharge>)`:
     `let next = self.checked_reserve(entries, bytes)?;`
     if let `Some(m) = memory.as_deref_mut()`: `m.preflight(bytes).map_err(BatchMeterError::to_search_error)?`;
     `if let Some(m) = memory { m.commit(bytes).map_err(...)?; }`; then `self.commit(next)`.
   - `fn release(&mut self, entries, bytes, memory: Option<&mut dyn MemoryCharge>)`:
     `let next = self.checked_release(entries, bytes)?;`
     `if let Some(m) = memory.as_deref_mut() { m.preflight_release(bytes)?; }`
     `if let Some(m) = memory { m.release(bytes)?; }`; then `self.commit(next)`.
   - `fn transfer_to_global(&mut self, entries, bytes, _memory: Option<&mut dyn MemoryCharge>)`:
     unchanged local transition; no batch release/commit (allocation stays live).
   - `Drop` stays local-only (no sink).
2. `PhraseScratch::reserve/release`: add `memory: Option<&mut dyn MemoryCharge>` and forward to
   `self.ledger.reserve/release`. `PhraseScratch::Drop` calls `ledger.release(..., None)`
   (local only; batch cleanup is the slot scope's responsibility).
3. `phrase.rs::match_phrase` (+ inner helpers): add `memory` parameter and forward at all 14
   `scratch.reserve/release` sites. `None` for pure-lexical `execute_search`.
4. `build_leaf_data`, `build_phrase`, `score_segment`, `eval_node`/`ReservedSet::release`:
   add `memory: Option<&mut dyn MemoryCharge>` and forward. `execute_segment_inner` passes `None`.
5. `evaluate_lexical_with`: add `memory` parameter; forward to `build_leaf_data`, its own
   `ledger.reserve/release` calls, and `score_segment`. Do not pass it across the typed callback.
6. `search/unified.rs::collect_mixed`: destructure the slot meter:
   `let (work, memory) = match batch { Some(b) => (Some(&mut b.work), Some(&mut b.memory)), None => (None, None) };`
   build `MixedWorkMeter` from `work` and `let mut scope = memory.map(SlotMemoryScope::new);`
   pass `scope.as_deref_mut()` (or `scope.as_mut().map(|s| s as &mut dyn MemoryCharge)`) to
   `evaluate_lexical_with`. C3 later adds heap usage of the same scope.
7. Add C2 tests (`c2_segment_exact`, `c2_segment_one_over_atomic`,
   `c2_local_reject_no_batch_change`, `c2_batch_reject_no_local_change`, `c2_overflow`,
   `c2_release_underflow_no_mutation`, `c2_two_segment_reuse`, `c2_segment_plus_existing_retained`,
   `c2_cancel_during_leaf_build_cleanup`, `c2_typed_callback_borrow_compiles`,
   `c2_standalone_parity`) using the real `BatchMemoryMeter` + `SlotMemoryScope` and a local
   reference model. Then run the C2 gates and continue to C3.

## Status

**P2B NOT ACCEPTED.** A/B/C1 verified; C2 is partially implemented (preflight-release primitive
only); C3/D/E/F outstanding. PR 14 still requires P3, P4 RustFS, benchmarks and final-SHA CI.
