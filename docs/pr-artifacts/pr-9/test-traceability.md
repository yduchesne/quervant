# PR 9 test traceability

**Base:** `17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`. **Tested working tree:**
`dev/stable-key-mutations` (final PR 9 working tree; see
`validation-report.md` for the exact commands/results).

Legend: **PASS** = a named executable test passed locally. **PARTIAL** = the
invariant is covered on one path; the residual path is documented in
`adversarial-review.md`. **NOT RUN** = no executable test in this tree.

| Invariant | Test | File / test name | Result |
|---|---|---|---|
| I01 | T01 | `pr09_mutations.rs::t01_insert_upsert_delete_insert_one_winner` | PASS |
| I01 | T04 | `pr09_mutations.rs::t04_same_key_multiple_segments_one_live_pointer` | PASS |
| I01 | T14 | `pr09_mutations.rs::t14_old_pit_sees_previous_version` | PASS |
| I01 | T23 | `pr09_merge.rs::t23_merge_removes_dead_docs` | PASS |
| I02 | T02 | `pr09_mutations.rs::t02_revisions_increase_no_reuse` | PASS |
| I02 | T03 | `pr09_mutations.rs::t03_absent_delete_tombstone_then_reinsert` | PASS |
| I02 | T05 | `pr09_mutations.rs::t05_duplicate_live_insert_error` | PASS |
| I02 | T06 | revision-overflow injection | NOT RUN (code path only) |
| I03 | T07 | `pr09_mutations.rs::t07_idempotent_replay_before_and_after_commit` | PASS |
| I03 | T08 | `pr09_mutations.rs::t08_idempotency_conflict` | PASS |
| I03 | T09 | `pr09_mutations.rs::t09_restart_replay` | PASS |
| I04 | T10 | `pr09_mutations.rs::t10_refresh_visibility_vs_commit_durability` | PASS |
| I04 | T11 | `pr09_mutations.rs::t11_delete_only_commit_advances_generation_without_segment` | PASS |
| I04 | T12 | `pr09_recovery.rs::t12_pre_current_failure_is_recoverable` | PARTIAL (pre-CURRENT) |
| I04 | T30 | indeterminate `CURRENT` poisoning | NOT RUN |
| I05 | T13 | `pr09_recovery.rs::t13_failed_refresh_retains_last_view` | PASS |
| I05 | T14 | `pr09_mutations.rs::t14_old_pit_sees_previous_version` | PASS |
| I05 | T15 | `pr09_mutations.rs::t15_old_handle_stays_fixed_reopen_sees_latest` | PASS |
| I05 | T26 | `pr09_merge.rs::t26_old_pit_survives_compact_and_close` | PASS |
| I06 | T16 | `pr09_visibility.rs::t16_term_and_phrase_exclude_deleted` | PASS |
| I06 | T17 | `pr09_visibility.rs::t17_multi_term_operators_and_not_exclude_dead` | PASS |
| I06 | T18 | `pr09_visibility.rs::t18_bm25_statistics_reference_after_delete` | PASS |
| I06 | T19 | `pr09_visibility.rs::t19_negative_only_has_no_ghost_scores` | PASS |
| I07 | T20 | `pr09_merge.rs::t20_indexed_not_stored_phrase_survives_merge` | PASS |
| I07 | T21 | `pr09_merge.rs::t21_columns_and_stored_values_survive_merge` | PASS |
| I07 | T22 | `pr09_merge.rs::t22_revisions_tombstones_and_replay_survive_merge` | PASS |
| I07 | T23 | `pr09_merge.rs::t23_merge_removes_dead_docs` | PASS |
| I07 | T24 | `pr09_merge.rs::t24_merge_scores_equivalent` | PASS |
| I08 | T27 | `pr09_visibility.rs::t27_corrupt_state_fails_closed` | PASS |
| I08 | T28 | `index::mutation_state::tests::*` | PASS |
| I08 | T29 | `index::visibility::tests::key_mismatch_and_duplicate_pointers_are_rejected` | PASS |
| I09 | T31 | `pr09_reclamation.rs::t31_current_objects_never_reclaimable` | PASS |
| I09 | T32 | `pr09_reclamation.rs::t32_independent_handles_prevent_deletion` | PASS |
| I09 | T33 | `pr09_reclamation.rs::t33_orphan_is_unknown` | PASS |
| I10 | T34 | `pr09_recovery.rs::t34_resource_bounds_exact_and_one_over` | PASS |
| I10 | T35 | cancellation during decode/merge/snapshot | NOT RUN (not implemented) |
| I10 | T36 | `pr09_recovery.rs::t12_pre_current_failure_is_recoverable` + PR 6 fault suites | PARTIAL |
| I11 | T25 | `pr07_compatibility.rs`, `segment_golden.rs`, `pr06_lifecycle_unit.rs` frozen fixtures | PASS |
| I11 | T37 | `pr09_visibility.rs::t37_v1_manifest_readable_and_migrates` | PASS |
| I12 | T38 | `pr09_reclamation.rs::t38_explicit_retention_uses_normal_deletes` | PASS |
| I12 | T39 | `pr09_reclamation.rs::t39_retention_validation_is_atomic` | PASS |
| I13 | T40 | `pr09_recovery.rs::t40_stale_handle_writer_reloads_current` | PASS |
| I13 | T41 | `pr09_mutations.rs::t41_competing_writer_is_busy` | PASS |
| I14 | T42 | `pr09_properties.rs::t42_seeded_stream_matches_independent_oracle` + diff audit | PASS |
| — | notes | Property oracle replays a seeded 80-op stream, commits and reopens every 10 ops | PASS |

## Commands

```sh
cargo test -p quervant-core --test pr09_mutations
cargo test -p quervant-core --test pr09_visibility
cargo test -p quervant-core --test pr09_recovery
cargo test -p quervant-core --test pr09_merge
cargo test -p quervant-core --test pr09_reclamation
cargo test -p quervant-core --test pr09_properties
```

All six suites passed. Frozen-fixture coverage (T25) is provided by the
pre-existing `pr07_compatibility`, `segment_golden` and `pr06_lifecycle_unit`
suites, which were run as part of `cargo test --workspace --all-targets`.

## Amendment 01

The previously `NOT RUN` T06/T30/T35 rows are closed by
[`amendment-01-test-traceability.md`](amendment-01-test-traceability.md)
(A1-T01–A1-T22, all executed and green).
