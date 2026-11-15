# PR 15I-D3-B-F1 — correctness trace

Written before the F1 tooling edit. Every invariant is mapped to the named F1
test(s) that must falsify or witness it, plus the observable evidence. The
candidate production source is not modified.

| ID | Invariant | Positive witness | Counterexample test |
|---|---|---|---|
| F1-I01 | BASE/candidate source SHA cannot change | `test_t04_base_dual_build_records`, `test_t05_ab_sequential_checkout` | `test_t11_dirty_source_before_switch`, `test_t12_source_changed_mid_build` |
| F1-I02 | A/A uses two actual builds at one canonical path | `test_t04_base_dual_build_records` | `test_t04_reject_copied_binary`, `test_t09_identical_target_dir_rejected` |
| F1-I03 | A/B use the same canonical path with sequential checkout | `test_t05_ab_sequential_checkout` | `test_t06_different_source_paths_rejected` |
| F1-I04 | A/A binaries bit-identical | `test_t07_aa_identical_qualifies` | `test_t07_aa_binary_mismatch_blocks` |
| F1-I05 | A/B distinct commits and binaries | `test_t05_ab_sequential_checkout` | `test_t08_ab_identical_binary_rejected` |
| F1-I06 | Independent target dirs; binary bytes stable through acquisition | `test_t09_identical_target_dir_rejected` | `test_t50_live_binary_tamper_rejected`, `test_t12_source_changed_mid_build` |
| F1-I07 | Frozen PR15D inputs and adapter lock match immutable Git blobs | `test_v01_frozen_inputs_match_git` | `test_t14_changed_corpus_blob`, `test_t15_changed_adapter_lock_blob` |
| F1-I08 | Native filesystem and distinct pinned CPUs | `test_host_attestation_accepts_native` | `test_t28_findmnt_overlay_rejected`, `test_t29_non_native_rejected`, `test_t23_controller_equals_adapter_rejected` |
| F1-I09 | Adapter affinity observed before and after each timing loop | `test_affinity_observations_accept` | `test_t24_missing_pre_capture`, `test_t25_missing_post_capture`, `test_t26_post_capture_moved` |
| F1-I10 | Source/host/build/protocol evidence sealed and independently checked | `test_v04_protocol_in_all_records`, `test_t03_manifest_inventory` | `test_t17`–`test_t20`, `test_t21`, `test_t22` |
| F1-I11 | Numeric A/A constraints unchanged | `test_t31_exempt_single_outlier`, `test_t34_median_bounds` | `test_t32_two_exempt_outliers`, `test_t33_non_exempt_outlier` |
| F1-I12 | No omitted lane/sample; exact oracle | `test_t39_shape_rejections`, `test_t40_oracle_tamper` | `test_t39`, `test_t40` |
| F1-I13 | Query/budget/cancellation/ranking semantics unchanged | candidate U01–U28, I01–I12 | full workspace QA |
| F1-I14 | Measurement block and performance rejection stay disjoint | `test_t07_aa_binary_mismatch_blocks`, `test_t45_series_history` | `test_t53_controller_verifier_disagree` |
| F1-I15 | Rejected candidate rolled back additively | §13 procedure (only on qualified rejection) | `I11` exact diff proof |
| F1-I16 | Historical archive/tooling not modified | `test_t55_historical_v1_unaffected`, QA `git diff --exit-code 155ebafa` | `test_t16_old_manifest_detected` |
| F1-I17 | Control retry only for numerical failure | `test_t43_numerical_then_qualified_02` | `test_t42_structural_then_02_rejected`, `test_t44_qualified_01_and_02_rejected` |
| F1-I18 | Fresh source identity after checkout | `test_t05_ab_sequential_checkout`, `test_t12_source_changed_mid_build` | `test_t18_wrong_build_protocol_digest` |
| F1-I19 | No data/source mutation during timing | provenance pre/post snapshots, two build events | `test_t50_live_binary_tamper_rejected`, `test_t10_overlapping_builds_rejected` |
| F1-I20 | Completion claims only from executed gates | `qa.md`, `execution-status.md` | `test_t56_inverted_expectation_fails` |

## Failure transitions checked

- Duplicate check remains exact-backed; a probabilistic positive never reports
  corruption (candidate U10/U11) and a real duplicate never escapes (U09).
- Budget/cancellation errors propagate before any filter bookkeeping (U18/U19).
- Borrowed/legacy keyword error precedence is unchanged (U13–U16).
- The F1 controller never builds from the external identity worktrees; only
  `<campaign>/compile-source` is passed to Cargo.
- A/A mismatch, A/B identity, wrong source revision, missing affinity capture,
  altered frozen blob, wrong protocol digest and ambiguous control history are
  all global invalidity, never lane-scoped performance failures.
- A dry proof is never promoted to an A/A control (`DRY_RUN_NO_TIMING`).
