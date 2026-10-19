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

## Transactional correctness proof (verified against source at `e46ab54`)

Replacement order in `collect_mixed`:
1. `heap_preflight_insert(new)` — local `preflight_global_bytes`, then batch `preflight`.
2. `heap_preflight_release(old)` — local `preflight_release_global_bytes`, then batch
   `preflight_release`, while old + new are both charged.
3. `heap_commit_insert(new)` — batch commit, then infallible local commit.
4. Pop and drop the old entry (its logical allocation is no longer live).
5. `heap_commit_release(old)` — batch `release`, then checked local release.

Because both preflights in (1)/(2) succeed before any mutation, and the only intervening
mutation (3) strictly increases both ledgers, the release in (5) is guaranteed to succeed:
batch temporary still contains `old + new`, and local global still contains `old + new`.
No fallible user operation occurs between the drop and the release. A preflight failure in
(1)/(2) returns before pop/drop, so the heap is unchanged (C3-04). `heap_commit_insert` batch
failure cannot occur after a successful preflight under the single-threaded exclusive borrow;
if it did, the local commit has not run, so the batch/local ledgers remain consistent and the
error propagates before heap mutation. No saturating arithmetic or ignored release errors.

## Additional executed evidence
- `search::unified::tests::c3_path_batch_parity_and_memory_reject` — real `collect_mixed` path:
  batch (`1_000_000` memory) matches standalone keys/total; `memory.current()==0` after the
  scope drops; a 1-byte batch memory ceiling returns `BudgetExceeded{BatchMemoryBytes}` and
  leaves `memory.current()==0`.
- `search::unified::tests` 6/6; `pr14_unified_cursor` 11, `pr14_f1_hardening` 23,
  `pr14_batch_governance` 7; fmt + targeted clippy PASS.

## Still outstanding for C3 acceptance
Path-level tests still missing: exact heap-ceiling insertion, one-byte-over at heap (as opposed
to segment scratch), larger/smaller replacements under binding limits, noncompetitive
zero-charge at the path level, replacement-rejection heap preservation, failed-then-successful
batch under heap pressure, and retained-response + heap overlap. The helper tests plus the
single real-path test do not yet constitute the full matrix.

## C3 path-level acceptance (executed at current HEAD)

Harness: `c3_build_segments` builds a real index in one segment (deterministic doc order) and
`UnifiedSearcher::search_with_batch` exercises the real `collect_mixed` path.

| Case | Test | Oracle / assertion |
|---|---|---|
| Exact heap ceiling + one-over | `c3_path_heap_exact_one_over` | charge = 64 + key len; exact limit succeeds, peak == exact; one-under returns `BatchMemoryBytes`, `current==0` |
| Larger replacement | `c3_path_larger_replacement` | new charge > old; conservative overlap peak (old+new) is exact; one-under rejects; best key returned |
| Smaller replacement | `c3_path_smaller_replacement` | new charge < old; overlap still counted; one-under rejects |
| Noncompetitive zero-charge | `c3_path_noncompetitive_zero_charge` | differential peaks: index with long noncompetitive key may grow only by segment scratch (< +500), not by the 1065 heap charge |
| Replacement reject atomicity | `c3_replacement_reject_atomic` | overlap preflight failure leaves existing local/batch reservation intact |
| Failed-then-successful slots | `c3_path_failed_then_success` | slot1 `BatchMemoryBytes` (heap pressure), slot2 succeeds, ordered cardinality |
| Ranking/insertion parity | `c3_path_batch_parity_and_memory_reject`, `pr14_unified_cursor` | batch keys/total equal standalone; cursor suite green |
| Checked arithmetic | `c3_insert_exact_one_over_atomic`, `c2_release_underflow_no_mutation`, `batch_meter::overflow_is_typed_not_wrapped` | typed failure, no counter mutation |

**Defect found and fixed during acceptance:** `evaluate_lexical_with` never released the scored-map
batch reservation (`_scored_charges`), so segment scratch accumulated across segments (measured
peak 2256 vs the correct 2128). It now releases `scored_charges` after consuming the scored map
into the returned vector. This was required for the exact heap oracle to match.

**Outstanding:** `c3_retained_response_overlap` (retained slot-1 response + slot-2 heap) is
deferred to Phase E, which owns response-memory retention and `finish_success`; C3 alone has no
retained response. Multi-segment ordering is deterministic because the harness writes one segment.
