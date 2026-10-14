# PR 9 Amendment 01 — test traceability

Every row records the invariant, implementation path, test function, execution
command, result and topology. All tests were executed on the final amendment tree
with `cargo test -p quervant-core --lib` (the whole in-crate suite) and the
workspace gate `cargo test --workspace --all-targets`.

Legend: **PASS** = executed and green. Topology: `Mem` = real `MemoryDirectory`;
`Fs` = real temporary `FsDirectory`; `Hook` = deterministic test-only stage/unit
hook (same production `check()` path).

| Invariant | Test | Implementation path | Test function | Command | Result | Topology |
|---|---|---|---|---|---|---|
| A1-I01 | A1-T01 | `writer.rs::apply` checked revision + state fixture | `amendment01::a1_t01_at_max_minus_one_new_operation_reaches_max` | `cargo test -p quervant-core --lib amendment01` | PASS | Mem |
| A1-I01 | A1-T02 | `writer.rs::apply` overflow paths | `amendment01::a1_t02_new_operation_at_max_overflows_without_state_change` | same | PASS | Mem |
| A1-I02 | A1-T03 | replay-before-allocation ordering | `amendment01::a1_t03_replay_at_max_succeeds_and_new_token_overflows` | same | PASS | Mem |
| A1-I02 | A1-T04 | inert overflow | `amendment01::a1_t04_overflow_is_inert_and_writer_remains_usable` | same | PASS | Mem |
| A1-I01/I05 | A1-T04 neg | pointer validation | `amendment01::a1_t04_negative_control_inconsistent_pointer_is_rejected` | same | PASS | Mem |
| A1-I03 | A1-T05 | `commit`/`reconcile_current_failure` | `amendment01::a1_t05_write_then_fail_poisons_and_new_generation_is_authoritative` | same | PASS | Mem + injection |
| A1-I03 | A1-T05b | same against `FsDirectory` | `amendment01::a1_t05b_write_then_fail_against_real_fs_directory` | same | PASS | Fs + injection |
| A1-I03 | A1-T06 | delete-only + token commit | `amendment01::a1_t06_write_then_fail_delete_only_and_replay_are_authoritative` | same | PASS | Mem + injection |
| A1-I04 | A1-T07 | `ensure_writable` on every entry point | `amendment01::a1_t07_poisoned_writer_rejects_every_entry_point` | same | PASS | Mem + injection |
| A1-I04 | A1-T08 | lock + fresh writer reload | `amendment01::a1_t08_fresh_writer_sees_revision_and_token_and_lock_is_released` | same | PASS | Mem + injection |
| A1-I05 | A1-T09 | pre-write failure reconciliation | `amendment01::a1_t09_fail_before_write_preserves_old_generation_and_retries_once` | same | PASS | Mem + injection |
| A1-I05 | A1-T10 | single retry, one token/revision | `amendment01::a1_t10_retry_after_prepublication_failure_has_one_revision_and_one_token` | same | PASS | Mem + injection |
| A1-I06 | A1-T11 | pre-cancelled entry check | `amendment01::a1_t11_pre_cancelled_compact_is_rejected_without_publication` | same | PASS | Mem |
| A1-I06 | A1-T12 | `BeforeDecode` occurrence 2 | `amendment01::a1_t12_cancel_before_second_segment_decode` | same | PASS | Hook |
| A1-I06 | A1-T13 | postings `step(1)` + unit hook | `amendment01::a1_t13_cancel_within_large_postings_remap` | same | PASS | Hook |
| A1-I06 | A1-T14 | column/norm checkpoints | `amendment01::a1_t14_cancel_during_columns_and_norms_remap` | same | PASS | Hook |
| A1-I06 | A1-T15 | `BeforeEncode`/`AfterEncode` | `amendment01::a1_t15_cancel_before_and_after_output_encode` | same | PASS | Hook |
| A1-I05/I06 | A1-T15b | compaction write-then-fail | `amendment01::a1_t15b_compaction_write_then_fail_poisons_and_reopens` | same | PASS | Mem + injection |
| A1-I05 | A1-T15c | compaction pre-write retry | `amendment01::a1_t15c_compaction_prepublication_failure_is_retryable` | same | PASS | Mem + injection |
| A1-I06 | A1-T16 | `DuringSnapshot` + mask check | `amendment01::a1_t16_cancel_during_snapshot_construction` | same | PASS | Hook |
| A1-I07 | A1-T17 | retry after cancellation | `amendment01::a1_t17_retry_after_cancellation_preserves_replay_and_revisions` | same | PASS | Mem |
| A1-I08 | A1-T18 | no post-publication check | `amendment01::a1_t18_cancellation_after_final_check_does_not_false_cancel` | same | PASS | Hook |
| A1-I09 | A1-T19 | plain vs flag equivalence | `amendment01::a1_t19_plain_and_flag_compaction_are_equivalent` | same | PASS | Mem |
| A1-I09 | A1-T20 | independent document oracle | `amendment01::a1_t20_lossless_merge_against_document_oracle` | same | PASS | Mem |
| A1-I10 | A1-T21 | 256-unit counter/overflow | `merge::tests::a1_t21_bounded_polling_counter_boundaries_and_overflow` | `cargo test -p quervant-core --lib merge::tests` | PASS | unit |
| A1-I10 | A1-T21 | interval poll within a step | `merge::tests::a1_t21_interval_poll_catches_request_within_a_large_step` | same | PASS | Hook |
| A1-I10 | A1-T22 | wire-format ids | `amendment01::a1_t22_no_wire_format_or_scope_change` + diff audit | `cargo test -p quervant-core --lib amendment01` | PASS | unit |

## Original PR 9 acceptance gaps

| Original | Now proven by | Result |
|---|---|---|
| T06 revision overflow | A1-T01–T04 | PASS (executed) |
| T30 ambiguous `CURRENT` | A1-T05–T10, T15b/T15c | PASS (executed) |
| T35 merge cancellation | A1-T11–T21 | PASS (executed) |

## Injection validity

- The `FaultyCurrentDirectory` wrapper delegates every method except
  `atomic_write` for exactly `index/CURRENT`, transitions one-shot to
  pass-through before the inner call, and exposes an interception counter. Each
  fault test asserts exactly the intended number of intercepted publications.
- Stage/unit hooks are thread-local and cleared after each test; a test that
  never reaches its stage would fail because the flag is never set and the
  operation would return `Ok` rather than `Cancelled`.

## Diff audit (A1-T22)

`git diff` for the amendment touches only:
`src/index/{error,merge,mod,visibility,writer}.rs` and the new
`src/index/amendment01.rs`. No `contract/*`, `search/*`, `objectstore`,
`quervant-distributed`, `Cargo.toml` dependency, wire-format id, or GC change.
