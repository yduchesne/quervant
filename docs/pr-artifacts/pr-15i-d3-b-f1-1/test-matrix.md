# PR 15I-D3-B-F1.1 — test matrix

## F1.1 unit tests (T01–T48) — 48/48 PASS

Executable in `benchmarks/pr15i_d3_b_f1_1/test_replay.py` (plus the inherited F1
suites in `test_run.py`/`test_verify.py`, 95/95 PASS). Each test has a concrete
assertion; negative tests assert the typed error or fingerprint change.

| ID | Test | Result |
|---|---|---|
| T01 | `test_f11_t01_controller_verifier_digest_parity` | PASS |
| T02 | `test_f11_t02_allowed_list_changes_digest` | PASS |
| T03 | `test_f11_t03_preflight_only_shape_rejected_for_campaign` | PASS (`D3B_HOST`/`V_HOST`) |
| T04 | `test_f11_t04_attestation_key_accepted` | PASS |
| T05 | `test_f11_t05_missing_allowed_list_rejected` | PASS |
| T06 | `test_f11_t06_duplicate_cpu_rejected` | PASS |
| T07 | `test_f11_t07_boolean_cpu_rejected` | PASS |
| T08 | `test_f11_t08_negative_cpu_rejected` | PASS |
| T09 | `test_f11_t09_equal_pinned_cpus_rejected` | PASS |
| T10 | `test_f11_t10_pinned_cpu_outside_allowed_rejected` | PASS |
| T11 | `test_f11_t11_unsorted_allowed_list_rejected` | PASS |
| T12 | `test_f11_t12_missing_role_rejected` | PASS |
| T13 | `test_f11_t13_duplicate_role_rejected` | PASS |
| T14 | `test_f11_t14_extra_role_rejected` | PASS |
| T15 | `test_f11_t15_non_native_filesystem_rejected` | PASS |
| T16 | `test_f11_t16_harness_findmnt_disagreement_rejected` | PASS |
| T17 | `test_f11_t17_invalid_host_fields_typed_error` | PASS (no uncaught `KeyError`) |
| T18 | `test_f11_t18_preflight_cpu_list_changes_fingerprint` | PASS |
| T19 | `test_f11_t19_preflight_and_campaign_scopes_distinct` | PASS |
| T20 | `test_f11_t20_explicit_valid_attestation_parity` | PASS |
| T21 | `test_f11_t21_root_compile_source_excluded` | PASS |
| T22 | `test_f11_t22_archive_without_compile_source` | PASS |
| T23 | `test_f11_t23_compile_source_file_rejected` | PASS (`V_INVENTORY`) |
| T24 | `test_f11_t24_compile_source_symlink_rejected` | PASS (`V_SYMLINK`) |
| T25 | `test_f11_t25_sealed_compile_source_rejected` | PASS (`V_SEAL`) |
| T26 | `test_f11_t26_root_intruder_rejected` | PASS (`V_INVENTORY`) |
| T27 | `test_f11_t27_nested_compile_source_not_exempt` | PASS (`V_INVENTORY`) |
| T28 | `test_f11_t28_historical_excluded_dirs_unchanged` | PASS |
| T29 | `test_f11_t29_tampered_sealed_file_still_rejected` | PASS (`V_SEAL`) |
| T30 | `test_f11_t30_duplicate_json_key_rejected` | PASS (`V_JSON`) |
| T31 | `test_f11_t31_protocol_exactly_six_changes` | PASS |
| T32 | `test_f11_t32_aa_configuration_unchanged` | PASS |
| T33 | `test_f11_t33_gates_unchanged` | PASS |
| T34 | `test_f11_t34_lanes_and_schedule_unchanged` | PASS |
| T35 | `test_f11_t35_corpus_and_sentinels_unchanged` | PASS |
| T36 | `test_f11_t36_campaign_names` | PASS |
| T37 | `test_f11_t37_tooling_manifest_exact_inventory` | PASS |
| T38 | `test_f11_t38_source_policy_and_candidate` | PASS |
| T39 | `test_f11_t39_controller_verifier_aa_parity` | PASS |
| T40 | `test_f11_t40_controller_verifier_gate_parity` | PASS |
| T41 | `test_f11_t41_control_numerical_retry` | PASS |
| T42 | `test_f11_t42_structural_control_blocks_retry` | PASS |
| T43 | `test_f11_t43_first_paired_rejection_stops_series` | PASS |
| T44 | `test_f11_t44_incomplete_series_not_accepted` | PASS |
| T45 | `test_f11_t45_rehearsal_marker_publish_guard` | PASS (`D3B_REHEARSAL_PUBLISH_FORBIDDEN`) |
| T46 | `test_f11_t46_rehearsal_path_publish_guard` | PASS |
| T47 | `test_f11_t47_original_inventory_detects_change` | PASS |
| T48 | `test_f11_t48_harness_fails_closed_on_wrong_expectation` | PASS (nonzero exit on mismatch) |

## Rehearsal matrix (R01–R16) — 16/16 expected

Executed by `replay.py` round-03 through the **external** verifier.

| ID | Expected | Actual |
|---|---|---|
| R01 | PASS, synthetic `CONTROL_QUALIFIED` | PASS |
| R02 | `V_ORACLE` | `V_ORACLE` |
| R03 | `V_ORACLE` | `V_ORACLE` |
| R04 | `V_SAMPLE_TYPE` | `V_SAMPLE_TYPE` |
| R05 | `V_INVENTORY` | `V_INVENTORY` |
| R06 | `V_INVENTORY` | `V_INVENTORY` |
| R07 | `V_SYMLINK` | `V_SYMLINK` |
| R08 | `V_SEAL` | `V_SEAL` |
| R09 | `V_SEAL` | `V_SEAL` |
| R10 | `V_HOST` | `V_HOST` |
| R11 | `V_HOST` | `V_HOST` |
| R12 | `V_HOST` | `V_HOST` |
| R13 | `V_BUILD_PROVENANCE` | `V_BUILD_PROVENANCE` |
| R14 | `V_TOOLING_SHA` | `V_TOOLING_SHA` |
| R15 | `V_PROTOCOL` | `V_PROTOCOL` |
| R16 | invariance: full verifier still PASS | PASS |

The harness self-test with a deliberately wrong expected code produced
`matched_expectation=false` and `harness_fail_closed=true`.

## Integration scenarios (I01–I12)

| ID | State | Evidence |
|---|---|---|
| I01 | PASS | `replay.py` → external `verify.py`: exit 0, `CONTROL_QUALIFIED` synthetic, 16 slots, 59 members, `UNAVAILABLE_ARCHIVE` |
| I02 | PASS | R02–R16 external invocations: 15/15 exact codes/invariance |
| I03 | PASS | official control: two real BASE builds from one path, identical binary SHA/size |
| I04 | PASS | campaign 01: same-path BASE→candidate switch, distinct binaries, pinned SHAs |
| I05 | PASS | control: 16 slots, 144 records, 2,880 positive samples, 720 warmups, 32 clear probes |
| I06 | PASS | control independent verifier PASS, `live_binary_rehash=PASS`, structural PASS |
| I07 | PASS | control archive `f58ef556…`, 61 members, sidecar, extraction rehash |
| I08 | PASS (verifier) / BLOCKED (campaign) | campaign 01 verifier PASS with `MEASUREMENT_BLOCKED` (drift); no performance verdict |
| I09 | NOT_RUN_BY_PROTOCOL | campaign 02 prohibited after a structural block |
| I10 | BLOCKED | series verifier PASS, `verdict=MEASUREMENT_BLOCKED`, `d3b_p08=FAIL` |
| I11 | PASS | existing real `FsDirectory` commit/reopen/query test (`i11`) |
| I12 | RUSTFS_PENDING | pinned image cannot start under podman-compose 1.0.6; no fake pass |

## Inherited suites

`benchmarks/pr15i_d3_b` (61 tests), `benchmarks/pr15i_d3_b_f1` (95 tests),
`benchmarks/pr15d/harness/test_pr15d.py` (83 tests, 3 skipped) and the full Rust
workspace suites (2,496 tests with all features; 92.85% line coverage) all pass.
