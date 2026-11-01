# PR 15E-B1 — test traceability

Invariant IDs follow the approved plan (`I01`–`I12`, `U01`–`U15`, `I01`–`I08`
adversarial/integration cases). Test names are the executed Rust/Python identifiers.

* `E::` = `crates/quervant-core/src/search/execute.rs` unit module
* `U::` = `crates/quervant-core/src/search/unified.rs` unit module
* `S::` = `crates/quervant-core/src/segment/tests.rs` unit module
* `T::` = `crates/quervant-core/tests/pr15e_b1.rs`
* `P::` = `benchmarks/pr15e_b1/test_run_targeted.py`

## 1. Invariants

| ID | Required property | Tests | Result |
|---|---|---|---|
| I01 | only effective-live docs, strict ascending order, once each, no tombstones | `T::u01_match_all_examines_exactly_the_live_ids_once_each`, `T::u02_no_charge_for_tombstoned_or_superseded_slots`, `T::u02_typed_only_examinations_equal_live_count`, `T::u03_mixed_bitmap_traversal_matches_independent_oracle` | PASS |
| I02 | cancellation poll before charge; exactly one lexical **or** typed charge per examined live doc; no charge for false flags | `T::u01_*`, `T::u02_typed_only_examinations_equal_live_count`, `T::u04_cancellation_stops_without_partial_results_and_leaks_nothing`, `T::u05_work_caps_are_exact_and_sharp_for_all_lanes` | PASS |
| I03 | `visit_lexical_membership_with` stops immediately on `VisitControl::Stop`, never inspects another doc after the first distinct over-limit key, no partial success | `U::u06_select_keys_limit_boundaries_are_exact`, `U::select_keys_stops_at_first_over_limit_distinct_match`, `U::select_keys_obeys_candidate_budget_and_mid_selection_cancellation` | PASS |
| I04 | `Term` membership equals an independent set oracle for 0/1/many terms, empty postings, boundaries and non-matches; phrase arm unchanged | `E::u07_term_membership_boundaries_match_oracle`, `E::u08_multi_term_or_with_overlapping_postings_matches_oracle`, `E::u09_seeded_generated_postings_match_reference_sets`, `E::u10_phrase_membership_unchanged`, `S::decoder_rejects_nonmonotone_doc_id_deltas` | PASS |
| I05 | BM25 scores, `total_hits`, key order, sort tuples, cursor/PIT, projection, analytics and batch parity preserved | `T::u03_*`, `T::u13_batch_memory_caps_keep_slot_ownership_without_cross_slot_bypass`, `pr14_unified_mixed` (14), `pr14_unified_cursor` (11), `pr14_aggregation` (5), `pr14_batch_governance` (7), full workspace suites | PASS |
| I06 | posting-decode validation and existing scanned-postings charges unchanged; no sort/copy of postings | `S::postings_round_trip_and_errors`, `S::decoder_rejects_nonmonotone_doc_id_deltas`, `E::u07`–`E::u10`, `pr07_amendment01/02/03` (38), source review (§4 of design doc) | PASS |
| I07 | no fictional live-set charge; all retained allocations still checked; shared batch memory intact | `T::u11_u12_retained_memory_caps_still_reject_but_the_transient_live_set_is_gone`, `E::c2_postings_exact_and_one_over`, `E::c2_two_segment_reuse_single_scope`, `E::production_global_bytes_exact_then_one_over_and_release` | PASS |
| I08 | no over-release/underflow/bypass/leaking RAII charge/silent cap relaxation | `T::u13_*`, `T::u14_batch_cancellation_charges_nothing_to_the_next_slot`, `E::t01`–`E::t08` (ledger model, atomicity, drop cleanup), `E::c1_*`, `pr07_amendment03::p05_global_plus_phrase_scratch_combined_bound` | PASS |
| I09 | no public API/dependency/format/on-disk/ObjectStore/cache/protocol change | source diff (§4), `Cargo.toml`/`Cargo.lock` untouched, CI config untouched | PASS |
| I10 | pure lexical `execute_segment_inner` `live_set` untouched | source diff: `execute_segment_inner` hunk count 0; `pr07_amendment01::b07_total_byte_budget_peak_is_exact` (exact 322-byte peak still holds), `pr07_unit` (18), `pr07_integration` (12) | PASS |
| I11 | independent expected outcomes; timing only after oracle PASS | every `T::` expectation is derived from the fixture model in the test file; the runner performs one untimed oracle response per lane before `measure_lane`, which validates every sample (frozen PR15D expected `total_hits`/`doc_ids`) | PASS |
| I12 | PR15D/PR15E-A artifacts immutable; B1 evidence append-only | frozen hashes verified by `P::test_frozen_pr15d_artifacts_match_the_pinned_hashes`; `benchmarks/reports/pr15e-a/profile-manifest.json` still `adfe7ead…`; no file under `benchmarks/pr15d/`, `benchmarks/pr15e/` or `docs/pr-artifacts/pr-15e-a/` modified | PASS |

## 2. Required test matrix

| ID | Case | Test | Result |
|---|---|---|---|
| U01 | bitmap `[]`/all false/all true/alternating/leading+trailing false → exactly true indexes ascending | `T::u01_match_all_examines_exactly_the_live_ids_once_each` (tombstones at first/last slot of each sealed segment plus one interior slot) | PASS |
| U02 | deletion/tombstone-effective false entries incur no examination/charge | `T::u02_no_charge_for_tombstoned_or_superseded_slots` (18 exams fully live vs 13 with 5 dead, identical physical layout), `T::u02_typed_only_examinations_equal_live_count` | PASS |
| U03 | mixed Boolean lexical+typed, multiple segments → identical hits/order/count to oracle | `T::u03_mixed_bitmap_traversal_matches_independent_oracle` | PASS |
| U04 | cancellation before first and after the Nth visited true doc → typed `Cancelled`, no unvisited true docs charged | `T::u04_cancellation_stops_without_partial_results_and_leaks_nothing` (`CancelAt(0)` and `CancelAt(polls/2)`) | PASS |
| U05 | work cap exact/one-below for zero-hit, `MatchAll`, mixed typed, high-match | `T::u05_work_caps_are_exact_and_sharp_for_all_lanes` (5 lanes) | PASS |
| U06 | `select_keys` limits 0, 1, N-1, N; duplicate logical keys | `U::u06_select_keys_limit_boundaries_are_exact` (limits 0/1/62/63/64 over 64 distinct keys, sorted unique result) | PASS |
| U07 | term postings `[]`, `[0]`, `[last]` | `E::u07_term_membership_boundaries_match_oracle` | PASS |
| U08 | multi-term OR with overlapping sorted postings | `E::u08_multi_term_or_with_overlapping_postings_matches_oracle` | PASS |
| U09 | 256 deterministic fixed-seed sparse/dense sets vs reference sets | `E::u09_seeded_generated_postings_match_reference_sets` (seed `0x5EED_0B1B_0000_0001`, recorded in the test) | PASS |
| U10 | phrase arm unchanged; corrupted/nonmonotone encoded postings still error | `E::u10_phrase_membership_unchanged`, `S::decoder_rejects_nonmonotone_doc_id_deltas` (delta patched to 0 → `NonMonotoneDocId`) | PASS |
| U11 | tight budget rejects real retained allocation | `T::u11_u12_…` second half: `min_bytes - 1` → `ResourceLimit` | PASS |
| U12 | budget previously exhausted solely by the live-set reservation now succeeds; ledger ends at zero | `T::u11_u12_…` first half: `min_bytes(1000 live) == min_bytes(10 live)` and the 10-doc ceiling admits the 1000-doc query; success itself implies `ledger.finish()` saw zero outstanding | PASS |
| U13 | batch aggregate retained caps unchanged, no cross-slot bypass | `T::u13_batch_memory_caps_keep_slot_ownership_without_cross_slot_bypass` (1-byte ceiling fails both slots; generous ceiling matches standalone results) | PASS |
| U14 | cancellation/failure with leaf data alive → RAII releases real charges | `T::u14_batch_cancellation_charges_nothing_to_the_next_slot`, `E::ledger_releases_outstanding_reservations_on_drop`, `E::t08_drop_cleanup_and_injected_inconsistency` | PASS |
| U15 | pure lexical executor behaviourally identical | source diff (no hunk in `execute_segment_inner`), `pr07_amendment01::a2_08_boolean_set_algebra_and_peak`, `pr07_unit`, `pr07_integration` | PASS |
| I01 | real `FsDirectory` 10K/100K exact-term corpus, 4 classes, K10/100 | `final` stage of the targeted benchmark: 9 lanes covering 10K/100K × {absent,rare,medium,common} at k100 plus 100K/common/k10, oracle-checked per lane and per sample (`total_hits`/`doc_ids`); `b1a`/`b1b` stages reuse the same corpus. See `qualification.md` | PASS |
| I02 | mixed lexical/typed, JSON/geo/time, phrase, `Not`, aggregation | `pr14_unified_mixed`, `pr14_typed_predicates`, `pr14_json`, `pr14_compound_aggregation`, `pr07_*`, full workspace run | PASS |
| I03 | query-mutation selector, batch delete/upsert, limit one-over, PIT/refresh/delete | `m3_delete_by_query` (local + real RustFS ×3), `m4_query_mutations`, `pr14_batch`, `U::u06_*` | PASS |
| I04 | sort ties, K10/K100, cursor/search-after stability | `pr14_unified_cursor`, `pr14a_public_cursor`, `pr10_*` suites, full workspace run | PASS |
| I05 | real local generation refresh/commit/reopen, old PIT pinned | `pr09_visibility`, `pr09_recovery`, `pr09_reclamation`, `pr06_local_integration`, `storage_fs_integration` | PASS |
| I06 | real RustFS cold bootstrap/queries, cache eviction, generation visibility | real RustFS gate: `pr13_s3_rustfs` (8), `pr13_proxy_rustfs` (5), `pr13_remote` (3), `pr13_oracle` (1), `pr13_oracle_geo` (1), `pr13_remote_proxy` (7), `pr13_crash_rustfs` k0 (5) / k05 ×10 (10) | PASS |
| I07 | full-source vs narrow projection parity | `pr14_projection`, `pr14b_json_memory`, `pr14d_json_sort_memory`, `pr14_aggregation` | PASS |
| I08 | `search_with_batch` vs standalone, failed slot/cancel accounting | `pr14_batch_memory` (31), `pr14_batch_governance` (7), `T::u13_*`, `T::u14_*` | PASS |

## 3. Counter-change (RED) evidence

The new integration test was executed against the untouched baseline worktree
(`c3083d8`) before being accepted:

```
T::u11_u12_… FAILED
  assertion `left == right` failed: no per-live-document transient charge may
  remain (wide=48016, narrow=496)
  left: 48016   right: 496
```

`48016 - 496 = 47520` plus the 10-document live set (480) reproduces exactly
`48 × 1000` logical bytes for the removed transient collection, i.e. the test is RED
before B1a and GREEN after. The remaining `u01`–`u05`, `u13`/`u14` cases pass on both
revisions by design: they assert *behavioural* invariants that B1a must preserve, so
they are regression controls rather than change detectors. The B1b change is
behaviour-preserving by construction, so its tests (`u07`–`u10`) are oracle
equivalence tests, not RED tests; the linear/binary-search swap is verified by
source review plus the ordering proof.

## 4. Intentional counter differences

* Work-meter `total_work_units` consumption is unchanged (same number of examined
  live documents, same charge sites).
* Logical candidate **bytes** may be *lower* than before for a query whose only
  former constraint was the transient live set. Tests therefore assert the retained
  peaks and their exact one-below rejection, not the old aggregate number. The
  pure-lexical 322-byte exactness assertion (`pr07_amendment01`) is unaffected and
  still passes.
* No test was weakened, skipped or re-scoped to obtain a pass.
