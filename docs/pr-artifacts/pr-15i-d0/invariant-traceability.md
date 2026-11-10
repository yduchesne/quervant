# PR 15I-D0 invariant traceability

This file is written **before** measurement implementation and is updated only
with observed facts. A gate marked `BLOCKED` is not a pass. A test that does not
exist is marked `NOT IMPLEMENTED`, not “covered”.

Test modules:

- `P` = `benchmarks/pr15i_d0/test_patch_instrumented_source.py`
- `S` = `benchmarks/pr15i_d0/test_source_proof.py`
- `R` = `benchmarks/pr15i_d0/test_run.py`
- `V` = `benchmarks/pr15i_d0/test_verify.py`

## 1. Falsifiable invariants

| ID | Invariant | Positive witness | Adversarial witness | Status |
|---|---|---|---|---|
| D0-I01 | BASE and canonical adapters byte-identical to pinned main | branch parent = BASE; protected diff empty; preflight PASS | `R.ProtocolTests.test_one_hex_digit_difference_is_rejected`; `S.test_changed_path_allowlist_rejects_hidden_score_change` | PASS for source identity; adapter **build** blocked by stale lock |
| D0-I02 | No production/format/API/acceptance change in D0 branch | `git diff BASE HEAD -- crates/ Cargo.* .github/` empty | `S.test_changed_path_allowlist_rejects_cargo_lock`; `S.test_changed_path_allowlist_rejects_hidden_score_change` | PASS |
| D0-I03 | Three engines compare exactly the frozen request/oracle | corpus digest matches; PR15D unit tests 83/83 | `V.test_p_q_above_ceiling_is_perturbed` does not apply; oracle mutations rejected below | **BLOCKED** (canonical build) |
| D0-I04 | A/Q/P identical logical query and projection | fixture oracle parity; `V.test_valid_synthetic_campaign_verifies` | `V.test_p_doc_ids_differ_from_oracle`, `V.test_q_total_hits_differs_from_oracle` | IMPLEMENTED, not measured |
| D0-I05 | Q/P same absolute path and SHA; same index files | `V.verify_binaries`, `V.verify_slot_binaries` | `V.test_a_q_binary_identical_is_rejected`, `V.test_slot_binary_digest_mismatch_is_rejected` | IMPLEMENTED, not measured |
| D0-I06 | Insertions only; no algorithm/control-flow change | `S.test_verify_derivative_accepts_the_approved_derivative` | `S.test_extra_inline_attribute_is_rejected`, `S.test_extra_cache_or_feature_default_is_rejected` | PASS |
| D0-I07 | No output/serialization inside timed region | adapter probe exports after `engine_ns`; source proof | `S.test_recorder_bytes_are_checked` (recorder tamper) | PASS by construction; real build BLOCKED |
| D0-I08 | Timers fully disabled in Q, enabled only in P | recorder has no `reset` on `op=query`; `V` mode proof | `V.test_q_carries_probe_fields`, `V.test_p_misses_probe_fields` | IMPLEMENTED, not measured |
| D0-I09 | Non-overlapping decomposition; no negative clamp | `R.test_exact_stage_partition_sums`, `V.test_exact_partition_passes` | `V.test_negative_evaluate_residual_is_invalid`, `V.test_top_level_stages_exceeding_engine_are_invalid` | IMPLEMENTED, not measured |
| D0-I10 | Same snapshot/filesystem/format for paired arms | index digests + sentinels + native FS | `V.test_index_a_qp_digest_mismatch_is_rejected`, `V.test_index_sentinel_mismatch_is_rejected` | IMPLEMENTED, not measured |
| D0-I11 | No low-match regression inferred from diagnostic binary | reports label P as diagnostic only; ranking withheld if perturbed | `V.test_perturbed_series_withholds_ranking` | PASS by documentation policy |
| D0-I12 | Statuses depend on independent re-derivation | `verify.py` reimplements statistics | `V.test_producer_timing_lie_is_rejected`, `V.test_malformed_derived_timing_is_rejected` | PASS for tooling |
| D0-I13 | No raw host paths/credentials/perf files committed | docs use relative paths; raw under `target/` | privacy inventory in `execution-status.md` | PASS |
| D0-I14 | Report never authorizes D1 or reports a speedup | no ratio published; status BLOCKED | documentation audit | PASS |

## 2. Test matrix

| ID | Test / evidence | Status |
|---|---|---|
| D0-T01 | `R.ProtocolTests.test_frozen_protocol_matches_literal`; preflight PASS | PASS |
| D0-T02 | `R.ProtocolTests.test_one_hex_digit_difference_is_rejected` | PASS |
| D0-T03 | `S.test_changed_path_allowlist_rejects_cargo_lock` | PASS |
| D0-T04 | `S.test_changed_path_allowlist_rejects_hidden_score_change` | PASS |
| D0-T05 | `R.EvidenceWritingTests.test_exclusive_write_refuses_existing_and_preserves_bytes` | PASS |
| D0-T06 | `R.EvidenceWritingTests.test_path_traversal_is_rejected` | PASS |
| D0-T07 | `R.EvidenceWritingTests.test_symlink_escape_is_rejected` | PASS |
| D0-T08 | `P.test_duplicate_anchor_is_refused` | PASS |
| D0-T09 | `P.test_missing_anchor_is_refused`; `P.test_region_requires_unique_delimiters` | PASS |
| D0-T10 | `S.test_extra_inline_attribute_is_rejected` | PASS |
| D0-T11 | `S.test_extra_cache_or_feature_default_is_rejected` | PASS |
| D0-T12 | `P.test_existing_derivative_is_refused` | PASS |
| D0-T13 | `P.test_present_probe_module_is_refused` | PASS |
| D0-T14 | `S.test_expected_derivative_reverses_to_base` | PASS |
| D0-T15 | `V.test_tooling_hash_mismatch_is_rejected` | PASS |
| D0-T16 | `V.test_a_q_binary_identical_is_rejected` | PASS |
| D0-T17 | `V.test_slot_binary_digest_mismatch_is_rejected` | PASS |
| D0-T18 | `verify_slot_binaries` checks every Q/P slot against the one QP SHA | IMPLEMENTED, not measured |
| D0-T19 | `V.test_q_carries_probe_fields` | PASS |
| D0-T20 | `V.test_p_misses_probe_fields` | PASS |
| D0-T21 | `R.StagePairTests.test_stage_pairs_require_exact_order` | PASS |
| D0-T22 | `R.StagePairTests.test_stage_pairs_require_exact_order` (reversed/extra); duplicate label rejected by exact list comparison | PASS |
| D0-T23 | absent/zero-hit lane is oracle-valid in every fixture | PASS |
| D0-T24 | rare/singleton lane is oracle-valid with one hit in every fixture | PASS |
| D0-T25 | `V.test_p_doc_ids_differ_from_oracle` | PASS |
| D0-T26 | `V.test_q_total_hits_differs_from_oracle` | PASS |
| D0-T27 | `V.test_index_a_qp_digest_mismatch_is_rejected` | PASS |
| D0-T28 | `V.test_index_sentinel_mismatch_is_rejected` | PASS |
| D0-T29 | `R.AffinityAndContentionTests.test_single_allowed_cpu_blocks` | PASS |
| D0-T30 | `R.AffinityAndContentionTests.test_nonclear_probe_blocks_the_campaign` | PASS |
| D0-T31 | `V.test_missing_contention_probe_is_rejected`; probe script nonzero maps to non-`clear` | PASS |
| D0-T32 | `V.test_missing_slot_prevents_seal`; seal inventory | PASS |
| D0-T33 | `V.test_duplicate_slot_number_is_rejected`; schedule literal | PASS |
| D0-T34 | `V.test_nineteen_samples_is_rejected` | PASS |
| D0-T35 | `V.test_bool_and_zero_samples_are_rejected` | PASS |
| D0-T36 | `V.test_wrong_warmup_count_is_rejected` | PASS |
| D0-T37 | `R.ScheduleAndLaneTests.test_frozen_schedule_literal`; `V.test_schedule_is_exactly_the_frozen_literal` | PASS |
| D0-T38 | `V.test_drift_at_inclusive_boundaries_passes`; `V.test_drift_upper_inclusive_boundary_passes` | PASS |
| D0-T39 | `V.test_drift_just_outside_boundary_is_unstable` | PASS |
| D0-T40 | `V.test_one_outlier_block_is_allowed` | PASS |
| D0-T41 | `V.test_two_outlier_blocks_are_unstable` | PASS |
| D0-T42 | `V.test_q_a_at_ceiling_passes` | PASS |
| D0-T43 | `V.test_q_a_above_ceiling_is_perturbed` | PASS |
| D0-T44 | `V.test_p_q_above_ceiling_is_perturbed` | PASS |
| D0-T45 | `V.test_one_block_above_single_block_guard_is_perturbed` | PASS |
| D0-T46 | `V.test_producer_timing_lie_is_rejected` | PASS |
| D0-T47 | `V.test_two_campaign_average_cannot_rescue_one_failure` | PASS |
| D0-T48 | `V.test_negative_evaluate_residual_is_invalid` | PASS |
| D0-T49 | `V.test_top_level_stages_exceeding_engine_are_invalid` | PASS |
| D0-T50 | `V.test_exact_partition_passes` | PASS |
| D0-T51 | `V.test_counter_disagreement_is_invalid` | PASS |
| D0-T52 | `V.test_q_total_hits_differs_from_oracle` | PASS |
| D0-T53 | `V.test_counter_type_is_invalid` | PASS |
| D0-T54 | `V.test_lane_descriptor_drift_is_rejected`; `R.ScheduleAndLaneTests.test_lane_descriptor_drift_is_rejected` | PASS |
| D0-T55 | `V.test_corrupted_seal_digest_is_rejected` | PASS |
| D0-T56 | `V.test_missing_contention_probe_is_rejected` | PASS |
| D0-T57 | `V.test_extra_unlisted_raw_file_is_rejected` | PASS |
| D0-T58 | `V.test_path_traversal_in_seal_is_rejected` | PASS |
| D0-T59 | `V.test_producer_timing_lie_is_rejected`, `V.test_malformed_derived_timing_is_rejected` | PASS |
| D0-T60 | `V.test_perturbed_series_withholds_ranking` | PASS |
| D0-T61 | `V.test_tie_break_uses_fixed_hypothesis_order`; `R.RankingTests.test_tie_break_is_the_fixed_hypothesis_order` | PASS |
| D0-T62 | `V.test_other_top_mandates_further_attribution`; `R.RankingTests.test_other_tops_without_inventing_a_new_hypothesis` | PASS |
| D0-T63 | Medians are reported per category and never summed into a fake total; `V.test_valid_synthetic_campaign_verifies` reports non-additive medians as distributions | PARTIAL (labeling asserted in docs; no dedicated counterexample fixture) |
| D0-T64 | `heaptrack` present locally; optional A-only capture not executed because the blocked build could not produce the required frozen A binary | BLOCKED |
| D0-T65 | JDK 21 present, so the “JDK missing” branch is not exercised; canonical blocked by the adapter lock instead | NOT APPLICABLE |
| D0-T66 | Documentation audit: historical 15I-0 numbers are labelled `NOT_CONTROLLED` and no current Q/T ratio is published | PASS |
| D0-T67 | `perf` present; no instruction/cycle/cache claim is made | NOT APPLICABLE |
| D0-T68 | RustFS is out of scope for this measurement-only change | NOT APPLICABLE |
| D0-T69 | Push/PR state recorded; no fabricated PR number | PASS (local only) |
| D0-T70 | No source/tooling change after sampling occurred because no sampling occurred | NOT TRIGGERED |

## 3. Residual risks

1. **Frozen lock drift:** the only blocker. Any resolution requires a human
   decision to update the frozen PR 15D adapter lock (or to pin a different
   baseline), which D0 explicitly forbids the agent from choosing.
2. **Mechanical import addition:** `use super::d0_probe;` is an additional
   insertion beyond the plan's literal timer statements. It is required for Rust
   name resolution, changes no behavior, and is fully reversible; it is recorded
   in the decision log. A reviewer must accept or reject this deviation before
   rerunning.
3. **Stage median non-additivity:** reports must never sum per-category medians
   into a total. The verifier reports per-sample partitions exactly; the
   documentation states the non-additivity explicitly.
4. **Process-affinity portability:** affinity is pinned only after a successful
   `/proc/<pid>/status` check; a failure blocks the campaign rather than falling
   back to floating CPUs.
5. **No real index/format evidence:** because the build is blocked, the LZ4
   sentinels, A/QP byte equality and oracle parity are enforced only by unit
   tests and by the controller/verifier logic, not by a real campaign.
