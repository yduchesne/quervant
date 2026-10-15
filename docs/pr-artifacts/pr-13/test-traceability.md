# PR 13 — test traceability

Baseline `653b412e0e7df8efe18602479b661629427fab57`. Commands and results are in
`validation-report.md`. `PASS` means the named test executed and passed; `PARTIAL`
means only part of the scenario was exercised; `NOT EXECUTED` is recorded honestly
rather than inferred.

## Provider and publication

| ID | Test | Result |
|---|---|---|
| S01 | `pr13_s3_rustfs::s01_concurrent_if_absent_single_winner` | PASS (real RustFS) |
| S02 | `pr13_s3_rustfs::s02_concurrent_if_match_single_winner` | PASS (real RustFS) |
| S03 | `pr13_s3_rustfs::s03_read_after_write_exact_bytes` | PASS (real RustFS) |
| S04 | `pr13_s3_rustfs::s04_exact_ranged_read` | PASS (real RustFS) |
| S05 | ETag≠SHA-256 mapping is the `IfMatch` protocol used by S02 | PASS (by protocol) |
| S06 | `s3::tests::validates_content_range_exactly`; adapter rejects missing `Content-Range` | PARTIAL |
| S07 | `s3::tests::validates_content_range_exactly` | PARTIAL |
| S08 | `pr13_s3_rustfs::s08_existing_identical_and_different` | PASS (real RustFS) |
| S09 | `pr13_s3_rustfs::s09_rejects_oversize_before_network`, `remote::config::*` | PASS |
| S10 | `pr13_s3_rustfs::s10_unqualified_endpoint_fails_closed` | PASS |
| C01 | `remote::tests::first_commit_publishes_current_last` | PASS |
| C02 | `remote::tests::second_commit_replaces_current_via_cas` | PASS |
| C03 | `remote::tests::two_writers_same_base_one_wins_one_conflicts`, `real::rustfs_stale_writer_cannot_overwrite_current` | PASS |
| C04 | `r04_old_pit_observes_its_generation` | PASS |
| C05 | Same as C03 (stale base loses CAS) | PASS |
| C06 | `remote::tests::ambiguous_current_publication_reconciles_exact_candidate` | PASS |
| C07 | `remote::tests::ambiguous_unreadable_current_requires_recovery` | PASS |
| C08 | `remote::tests::two_writers_same_base_one_wins_one_conflicts` asserts CURRENT stays at the winner | PASS |
| C09 | `remote::tests::segment_upload_failure_leaves_current_unchanged` | PASS |
| C10 | `remote::tests::two_writers_same_base_one_wins_one_conflicts` (distinct workspaces; CAS only) | PASS |

## Cache, transfer, budgets

| ID | Test | Result |
|---|---|---|
| D01 | `remote::transfer::tests::whole_get_when_below_threshold` | PASS |
| D02 | `remote::transfer::tests::ranged_get_when_large`, `real::rustfs_ranged_segment_transfer_matches_whole` | PASS |
| D03 | `remote::transfer::tests::ranged_falls_back_when_capability_absent` | PASS |
| D04 | `remote::transfer::tests::plan_ranges_exact_and_final_short_chunk` | PASS |
| D05 | `plan_ranges_are_gapless_and_nonoverlapping`, `interrupted_ranged_transfer_fails_without_publication` | PASS |
| D06 | `remote::transfer::tests::short_or_corrupt_response_is_rejected_by_cache_digest` (cache digest gate) | PARTIAL |
| D07 | Existing `storage::cache`/`a3_io` coalescing suites (unchanged by PR 13) | PASS (pre-existing) |
| D08 | `remote::tests::delete_and_reload_from_remote` (`delete_calls == 0`) | PASS |
| D09 | `remote::transfer::tests::interrupted_ranged_transfer_fails_without_publication` | PARTIAL |
| D10–D12 | Existing cache temp-cleanup/reconcile suites; not re-parameterized for remote | NOT EXECUTED (remote) |
| B03/B04 | `remote::transfer::tests::aggregate_byte_ceiling_is_enforced` | PASS |
| B05 | `remote::transfer::tests::permit_pool_ceiling_is_enforced` | PASS |
| B06/B07 | `remote::config::tests::effective_bounds_use_minima` + validation | PARTIAL |
| B08 | `RemoteTransferConfig::validate` + hydrate temp-disk preflight | PARTIAL |
| B09 | `plan_ranges` rejects zero chunk/overflow paths | PARTIAL |
| B10 | `s09` + cache per-object rejection | PASS |
| B11/B12 | Not specifically exercised for remote | NOT EXECUTED |

## Failure, recovery, vertical slice

| ID | Test | Result |
|---|---|---|
| F01 | `segment_upload_failure_leaves_current_unchanged` | PASS |
| F02/F03 | Same ordered-upload path; state/manifest faults not individually injected | PARTIAL |
| F04 | `remote::tests::missing_current_is_not_initialized` | PASS |
| F05 | `interrupted_ranged_transfer_fails_without_publication` | PARTIAL |
| F06 | `transient_failure_is_retried_then_succeeds` | PASS |
| F07 | `nontransient_failure_is_not_retried` | PASS |
| F08/F09 | Approximated by C06/C07 ambiguity tests; no separate-process crash test | PARTIAL |
| F10 | `short_or_corrupt_response_is_rejected_by_cache_digest` | PASS |
| F11 | Not executed | NOT EXECUTED |
| F12 | `two_writers_same_base_one_wins_one_conflicts`, real stale-writer test | PASS |
| R01 | `r01_cold_open_from_remote_after_workspace_delete`, `rustfs_write_cold_open_query_and_restart` | PASS |
| R02 | Real cold-open/restart test | PASS |
| R03 | `v01_lexical_results_match_local_oracle` asserts `get_calls == 0` during scoring | PASS |
| R04 | `r04_old_pit_observes_its_generation` | PASS |
| R05 | Real test deletes the workspace and reopens | PASS |
| R06 | `delete_and_reload_from_remote` (authoritative objects untouched) | PASS |
| R07 | `r07_concurrent_readers_observe_one_complete_generation` | PASS |
| R08 | Real interrupted-transfer proxy | NOT EXECUTED |
| V01 | `v01_lexical_results_match_local_oracle` | PASS |
| V02–V05 | Typed/time/JSON/geo oracle equivalence not separately executed against remote | NOT EXECUTED |
| V06 | `v06_upsert_delete_reopen_has_no_resurrection` | PASS |
| V07 | `r04_old_pit_observes_its_generation` | PASS |
| V08 | Query-scoped pre-materialization pruning | NOT EXECUTED (design amendment required) |
| P01–P03 | Benchmarks | NOT EXECUTED |
| L01 | Default build compiles/tests with no `s3`/Tokio (default clippy + tests) | PASS |
