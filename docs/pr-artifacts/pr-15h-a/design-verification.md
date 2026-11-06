# PR 15H-A — Design verification and invariant traceability

**Baseline:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Plan:** `QUERVANT_PR15H_A_DETAILED_IMPLEMENTATION_PLAN.md` v1.0

## Scope

Only the existing `if postings_candidate_eligible { … }` arm inside
`execute::evaluate_lexical_with` changes. Everything else is untouched:

- `single_term_postings_eligible` — unchanged;
- `collect_mixed` key resolution, sort tuple, duplicate-key check, heap, cursor,
  projection — unchanged;
- `score_segment` — unchanged (plus one `#[cfg(test)]` entry counter);
- `score::bm25`, `compute_stats`, postings codecs, segment formats, manifests,
  `Directory`, `SegmentStore`, `ObjectStore`, remote paths — unchanged.

The new branch stages `(physical_doc_id, term_frequency)` in decoded order,
applies the **same** 48-byte matched-set and 64-byte scored-map virtual ledger
charges in the same order, scores every match with the existing `bm25` function
in ascending doc order, and returns an ordered `Vec<(u64, f64)>`.

## Pre-implementation counterexamples

Three concrete ways a naive implementation would break an invariant; each is
tested explicitly.

1. **Score-error precedence.** Baseline reserves the matched set, then the scored
   map, and only then evaluates `bm25`. If the linear path scored before the
   scored-map reservation, an `InvalidScore` would be observed where baseline
   raises `ResourceLimit`. Test: `h_a_u17_score_fault_after_reservations` plus
   `h_a_u23_double_fault_resource_wins`.
2. **Virtual budget overlap.** The baseline peaks at 48 + 64 bytes per match at
   the same time, even though the new vectors are physically smaller. Lowering
   either charge would make queries succeed that baseline rejects, silently
   relaxing the resource contract. Tests:
   `h_a_u11_u12_matched_ledger_boundary`,
   `h_a_u13_u14_scored_ledger_boundary`, `h_a_u15_global_budget_shared`.
3. **Source-term ownership.** In `score_segment`, only the owner leaf of a
   distinct `(field, term)` contributes and only positive leaves score. A
   bypass that scored unconditionally would change results for negative-only,
   typed or multi-leaf shapes. Mitigation: branch only under the pre-existing
   eligibility flag; keep the fallback byte-identical. Tests:
   `h_a_u01_u02_eligibility_and_counters`,
   `h_a_u03_u04_noneligible_shapes_fallback`.

## Invariant → test traceability

`U*` are Rust unit tests, `I*` local/RustFS integration, `B*` controller tests,
`Q*` quality gates. Every row must be executed with evidence before correctness
is claimed.

| Invariant | Evidence |
|---|---|
| HA-I01 optimization iff `postings_candidate_eligible` | `h_a_u01_u02_eligibility_and_counters`, `h_a_u20_and_term_fallback_is_ineligible`, `h_a_i02_two_segment_differential` |
| HA-I02 exact single-term runtime shape; typed `CorruptIndex` otherwise | `h_a_u08_runtime_shape_guard`, `h_a_u10_non_increasing_candidates_fail_closed` |
| HA-I03 matched IDs ascending, unique, effective-live | `h_a_u05_u09_exact_scores_and_order`, `h_a_u06_live_filtering`, `h_a_u10_non_increasing_candidates_fail_closed` |
| HA-I04 `is_match` called in the same order/count | `h_a_u07_predicate_and_work_parity`, `h_a_u19_cancellation_parity` |
| HA-I05 48 bytes / one entry per match before scoring | `h_a_u11_u12_matched_ledger_boundary`, `h_a_u22_batch_memory_charge_boundary` |
| HA-I06 then 64 bytes / one entry per match | `h_a_u13_u14_scored_ledger_boundary`, `h_a_u15_global_budget_shared` |
| HA-I07 reserve/release order and atomic failure | `h_a_u11_u12_matched_ledger_boundary`, `h_a_u13_u14_scored_ledger_boundary`, `h_a_u23_double_fault_resource_wins` |
| HA-I08 BM25 bitwise-equal contributions | `h_a_u05_u09_exact_scores_and_order`, `h_a_u09_frequency_and_norm_variants`, `h_a_i02_two_segment_differential` |
| HA-I09 error class/ordering preserved | `h_a_u13_u14_scored_ledger_boundary`, `h_a_u17_score_fault_after_reservations`, `h_a_u23_double_fault_resource_wins` |
| HA-I10 one ordered `(doc_id, f64)` per match | `h_a_u05_u09_exact_scores_and_order`, `h_a_i01_local_commit_reopen_term_query` |
| HA-I11 noneligible paths unchanged | `h_a_u03_u04_noneligible_shapes_fallback`, `h_a_u20_and_term_fallback_is_ineligible`, `h_a_i03_mixed_fallback_shapes` |
| HA-I12 `collect_mixed` key/sort/heap/cursor/projection unchanged | `h_a_i01_local_commit_reopen_term_query`, `h_a_i02_two_segment_differential`, `h_a_i04_pit_refresh_delete` |
| HA-I13 work meter, scanned postings, cancellation, cleanup unchanged | `h_a_u07_predicate_and_work_parity`, `h_a_u19_cancellation_parity`, `h_a_i05_batch_limits_and_cancellation` |
| HA-I14 physical formats/bytes/storage unaffected | `h_a_i06_corruption_injection`, `h_a_i07_rustfs_remote_path`, `h_a_i08_rustfs_fault_recovery`, `q01` |
| HA-I15 only seven frozen warm lanes | `B01`, `B02`, `B10` |
| HA-I16 baseline before production edit, same-host paired | `B03`, `B04`, baseline seal chronology, `B13` |
| HA-I17 no pass on missing/failed gate | `B05`, `B06`, `B08`, `B09`, `B11`, `B14`, `B15` |
| HA-I18 frozen sign-consistency decision | `B12`, `B13`, `B14`, `B15`, `B16` |
| HA-I19 stable/MSRV/coverage/RustFS/CI reported separately | `Q01`–`Q12`, `I07`, `I08` |
| HA-I20 rejected optimization restores byte-identical production search | `B17`, `Q13` |

## Failure-boundary state machine

| Boundary | Expected |
|---|---|
| Failure during candidate scan | no matched/scored virtual charge; leaf ledger `Drop` cleans leaf charges |
| Failure during matched reservation | neither matched nor scored committed; `Drop` cleans leaf |
| Failure during scored reservation | matched released by `Drop`; scored not committed |
| Failure during scoring | matched + scored + leaf cleaned by `Drop`; no partial output |
| Failure during explicit release | typed error; ledger counters never written directly |
| Cancellation | typed `Cancelled`, no persistent change, no suppressed polls |

## Cross-component impact

Unchanged: `unified.rs` production, `score.rs`, `postings.rs`, codecs/formats,
`SegmentReader`, cache, writers, `CURRENT`, remote paths. Modified:
`execute.rs` eligible branch only, plus `#[cfg(test)]` observation counters and
fault flags. New: this benchmark tool and the local integration test file.
