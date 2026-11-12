# PR 15I-D3-B-F1 — test matrix (T01–T56, I01–I12)

All T-tests run in `benchmarks/pr15i_d3_b_f1/test_verify.py` (verifier component
checks with independent fixtures) and `benchmarks/pr15i_d3_b_f1/test_run.py`
(controller gates, schedules, control policy, archives, CLI and a full synthetic
`cmd_paired` wiring test). `python3 -m unittest discover -s
benchmarks/pr15i_d3_b_f1 -p 'test_*.py'` reports **95 tests, all passing**.

| ID | Test(s) | Result |
|---|---|---|
| T01 | `test_t01_campaign_names` | PASS |
| T02 | `test_t02_protocol_literal_matches_file` | PASS |
| T03 | `test_t03_tooling_manifest_inventory_and_freeze` | PASS |
| T04 | `test_t04_base_dual_build_records`, `test_t04_reject_copied_binary` | PASS |
| T05 | `test_t05_ab_sequential_checkout` | PASS |
| T06 | `test_t06_different_source_paths_rejected` | PASS |
| T07 | `test_t07_aa_identical_qualifies`, `test_t07_aa_binary_mismatch_blocks` | PASS |
| T08 | `test_t08_ab_identical_binary_rejected` | PASS |
| T09 | `test_t09_identical_target_dir_rejected` | PASS |
| T10 | `test_t10_overlapping_builds_rejected` | PASS |
| T11 | `test_t11_source_tree_not_clean_rejected` | PASS |
| T12 | `test_t12_source_changed_mid_build` | PASS |
| T13 | `test_t13_wrong_source_revision_rejected` | PASS |
| T14 | `test_t14_changed_corpus_blob` | PASS |
| T15 | `test_t15_changed_adapter_lock_blob` | PASS |
| T16 | `test_t16_old_manifest_detected` | PASS |
| T17 | `test_t17_wrong_protocol_digest_authorization` | PASS |
| T18 | `test_t18_wrong_build_protocol_digest` | PASS |
| T19 | `test_t19_wrong_host_protocol_digest` | PASS |
| T20 | `test_t20_missing_member_rejected` | PASS |
| T21 | `test_t21_duplicate_json_key_rejected` | PASS |
| T22 | `test_t22_symlink_traversal_rejected` | PASS |
| T23 | `test_t23_controller_equals_adapter_rejected` | PASS |
| T24 | `test_t24_missing_pre_capture` | PASS |
| T25 | `test_t25_missing_post_capture` | PASS |
| T26 | `test_t26_post_capture_moved` | PASS |
| T27 | `test_t27_controller_observed_cpu_differs` | PASS |
| T28 | `test_t28_findmnt_overlay_rejected` | PASS |
| T29 | `test_t29_non_native_rejected` | PASS |
| T30 | `test_t30_host_fingerprint_mismatch` | PASS |
| T31 | `test_t31_exempt_single_outlier` | PASS |
| T32 | `test_t32_two_exempt_outliers` | PASS |
| T33 | `test_t33_non_exempt_outlier` | PASS |
| T34 | `test_t34_median_bounds` | PASS |
| T35 | `test_t35_p01_boundaries` | PASS |
| T36 | `test_t36_k10_boundaries` | PASS |
| T37 | `test_t37_low_hit_boundaries` | PASS |
| T38 | `test_t38_p05_p06_guards` | PASS |
| T39 | `test_t39_shape_rejections` | PASS |
| T40 | `test_t40_oracle_tamper` | PASS |
| T41 | `test_t41_drift_and_contention` | PASS |
| T42 | `test_t42_structural_then_02_rejected` | PASS |
| T43 | `test_t43_numerical_then_qualified_02` | PASS |
| T44 | `test_t44_qualified_01_and_02_rejected` | PASS |
| T45 | `test_t45_series_history` | PASS |
| T46 | `test_t46_series_both_qualified` | PASS |
| T47 | `test_t47_series_second_fails` | PASS |
| T48 | `test_t48_partial_campaign_not_qualified` | PASS |
| T49 | `test_t49_archive_only_provenance` | PASS |
| T50 | `test_t50_live_binary_tamper` | PASS |
| T51 | `test_t51_exclusive_archive` | PASS |
| T52 | `test_t22_symlink_traversal_rejected` (traversal/symlink seal) | PASS |
| T53 | `test_t53_controller_verifier_disagreement` | PASS |
| T54 | `test_t03_tooling_manifest_inventory_and_freeze` (post-freeze change) | PASS |
| T55 | `test_t55_historical_v1_unaffected` | PASS |
| T56 | `test_t56_inverted_expectation_fails` | PASS |

Additional controller tests: frozen schedule, gate arithmetic, A/A policy,
control statuses, drift blocking, controller/verifier summary agreement,
source-policy allowlist, index sentinels, slot/seal/archive tampering, CLI, and
`test_control_campaign_wiring_and_seal` (full synthetic `cmd_paired` with fake
builds/slots checks file order, provenance/host sealing and
`CONTROL_QUALIFIED`).

## Integration checks

| ID | State | Evidence |
|---|---|---|
| I01 | PASS | `dry-proof-01/dry-proof-aa`: A and B binary SHA identical (`4994d273…`) |
| I02 | PASS | `dry-proof-01/dry-proof-ab`: A `81bacb88…` != B `3b2f17fc…` |
| I03 | PASS | pre/post checkout, `unified.rs` blob and frozen inputs verified for every build |
| I04 | PASS | frozen PR15D generator/oracle; exact hit counts and doc IDs in the control |
| I05 | PASS | 10K/100K real index builds; 100K 15,747,551 / 1,661,455; identical digests |
| I06 | PASS | existing candidate `FsDirectory` writer→commit→reopen→search (`i11`) |
| I07 | BLOCKED | 16-slot A/A executed; controller `CONTROL_QUALIFIED`; independent verifier FAIL (`V_INVENTORY`, `V_HOST` tooling defects) |
| I08 | NOT_RUN_BY_PROTOCOL | no independently qualified control |
| I09 | NOT_RUN_BY_PROTOCOL | no first paired campaign |
| I10 | BLOCKED | verifier replay FAIL; archive extraction unavailable because `publish` refused |
| I11 | PASS | production diff vs BASE unchanged; historical tooling diff empty |
| I12 | RUSTFS_PENDING | pinned image cannot start under podman-compose (unchanged from D3-B) |

## Coverage gate

The Rust workspace was unchanged by F1; the candidate QA and 92.85% line
coverage from the D3-B candidate state remain valid and were re-confirmed by the
final-state commands in `qa.md`.
