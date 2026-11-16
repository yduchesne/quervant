# BM-05 — Mutation and adversarial matrix

Each mutation is applied to a fresh copy of the sealed run or to a deep copy of
the supplied documents. Every test asserts the typed `BenchError` code, that no
assessment is produced, that the original trees are byte-identical and that no
repair or persistence occurs.

| ID | Attack/fault | Test | Observed rejection |
| --- | --- | --- | --- |
| V-MUT-01 | untouched valid pair | `test_v_mut_01_untouched_valid_pair_is_verified` | verified, 9 check ids, digests match sources |
| V-MUT-02 | repeat invocation | `test_v_mut_02_repeat_invocation_is_idempotent_and_read_only` | identical assessment; file snapshot unchanged |
| V-MUT-03 | changed ambient `decimal` context | `test_v_mut_03_ambient_decimal_context_cannot_change_the_outcome` | identical assessment |
| V-MUT-04 | missing treatment envelope | `test_v_mut_04_missing_treatment_envelope_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-05 | extra/unsealed treatment path | `test_v_mut_05_extra_unsealed_treatment_path_is_rejected` | `BM_UNSAFE_INPUT` |
| V-MUT-06 | byte alteration without seal update | `test_v_mut_06_treatment_byte_alteration_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-06b | bytes changed after first read | `test_v_mut_06b_post_read_integrity_detects_a_race` | `BM_IDENTITY_INVALID` from the raw ledger recheck |
| V-MUT-07 | altered envelope arm identity (seal rebound) | `test_v_mut_07_altered_envelope_identity_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-08 | wrong/removed profile binding | `test_v_mut_08_wrong_profile_binding_is_rejected` | `BM_IDENTITY_INVALID` / `BM_SCHEMA_INVALID` |
| V-MUT-09 | forged 12dp `raw_point_effect` | `test_v_mut_09_forged_raw_point_is_rejected` | `BM_IDENTITY_INVALID`, path contains `raw_point_effect` |
| V-MUT-10 | internally valid forged CI endpoint (+1e-12) | `test_v_mut_10_internally_consistent_forged_ci_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-10b | forged stream digest | `test_v_mut_10b_forged_stream_digest_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-11 | forged spread / inconsistent ledger | `test_v_mut_11_forged_exclusion_ledger_is_rejected` | `BM_IDENTITY_INVALID` / closed-contract rejection |
| V-MUT-12 | changed policy lane outcome or CI limit | `test_v_mut_12_changed_policy_outcome_is_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-13 | coherent forged resource decision (structural validator accepted) | `test_v_mut_13_coherent_forged_resource_decision_is_rejected` | `BM_IDENTITY_INVALID` from independent policy |
| V-MUT-14/15 | GM, ranking, selection rewritten together (structural validator accepted) | `test_v_mut_14_15_rewritten_ranking_and_selection_are_rejected` | `BM_IDENTITY_INVALID` |
| V-MUT-16 | deterministic race through the IO primitive | `test_v_mut_16_deterministic_race_through_the_io_primitive_is_rejected` | `BM_IDENTITY_INVALID` on the second read |
| V-MUT-17 | symlink / oversize canonical envelope | `test_v_mut_17_symlink_and_oversize_inputs_are_rejected` | `BM_UNSAFE_INPUT` |
| V-MUT-18 | synthetic→official scope promotion | `test_v_mut_18_scope_promotion_is_refused_before_reads` | `BM_SCOPE_MISMATCH` before source reads |
| V-POL-16/34 | forged eligible GM with matching ranking/selection | `test_v_mut_14_15_rewritten_ranking_and_selection_are_rejected` | independent policy mismatch |
| V-POL-17/35 | fabricated / duplicated / permuted reason records | `test_v_ind_08_forged_reason_sequence_is_rejected_or_structurally_invalid` | `BM_IDENTITY_INVALID` |

## Structural-validator-accepted false PASS

`test_v_ind_05`, `test_v_ind_06` and `test_v_ind_07` deliberately run
`validate_analysis_result` / `validate_policy_decision` on the forged document
first. The forgeries are schema-valid (12-place decimals, matching digest
bindings, coherent ranking/selection) and are rejected only by the independent
recomputation. This demonstrates that BM-05 is not merely repeating BM-04's
closed-output validator.

## Read-only evidence

`test_v_mut_02`, `test_no_persistent_state_or_new_file_on_rejection` and
`test_v_hist_01_empty_archive_is_reported_unavailable_without_writing` compare
full file-tree byte snapshots before and after verification/rejection. No new
file, no rewrite and no repair occurs.
