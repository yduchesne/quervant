# PR 15A — invariant and test traceability

**Status:** all local and real-provider rows below are `PASS (EXECUTED)` or
`PASS (HISTORICAL REUSED; SOURCE-LOCK VERIFIED)` as labelled. GitHub CI is
`DEFER AND CONTINUE` (no PR/push from this environment) and maintainer
acceptance is `NOT STARTED`. v0.1 remains **NOT RELEASED**.

Validated implementation head: `f8392db`. Base: `80a3864`. Every ignored count
is reported separately and is never counted as a pass.

## 1. Normative invariants

| Invariant | Witness | Expected-value source | Topology / command | Status |
|---|---|---|---|---|
| A-I01 hit sets, totals, projection | `pr15a_regression::a15_t01_lexical_and_mixed_boolean_oracle`, `a15_t02_memory_and_fs_reopen_equivalence`, `a15_t03_absent_and_boolean_negatives` | static `pr15a_v1` rows in `pr15a_common`; literal sets | Memory + native `FsDirectory`; `cargo +stable test -p quervant-core --test pr15a_regression` | **PASS (EXECUTED)** |
| A-I02 IP/CIDR/time/JSON composition | `a15_t04_cidr_and_time_range`, `a15_t05_json_scalar_and_source_states`, `a15_t06_ip_family_json_states_and_typed_failures` | static IP/CIDR and timestamp arithmetic over frozen integers; JSON state table | same target | **PASS (EXECUTED)** |
| A-I02 geo surface (separate fixture) | REUSED `pr12_geo` (25 tests) and PR 14 local geo projection | dedicated `pr12_geo`/PR 14 fixtures, not the eight canonical rows | workspace test gate | **PASS (EXECUTED)** |
| A-I03 groups/distinct/top-K determinism | `a15_t07_groups_metrics_and_exact_distinct`, `a15_t08_ties_empty_groups_and_top_k`; REUSED `pr10_groups`/`pr10_distinct` (5 + 5) | independent host tally and documented canonical tie rule | same target + workspace gate | **PASS (EXECUTED)** |
| A-I04 pinned pages concatenate exactly | `a15_t09_pinned_pages_concatenate_exactly` (sizes 1/2/3/8) | static `n`-ascending key table | native `FsDirectory` + retained `PitHandle` | **PASS (EXECUTED)** |
| A-I04 negatives (wrong PIT/sort/query/naked) | `pr14a_public_cursor::{t01_naked_snapshot_rejects_pit_and_cursor_before_slots,t06_wrong_handle_and_snapshot_binding_fail_without_fallback,t07_query_and_sort_mismatch_fail_typed,t08_three_slot_batch_isolates_cursor_failure_in_input_order,t10_expiry_boundaries_and_no_renewal}` | existing contract negatives | `cargo +stable test -p quervant-core --test pr14a_public_cursor` | **PASS (EXECUTED)** |
| A-I05 atomic mutation + durable replay | `a15_t11_generation_three_mutation_and_replay` | frozen generation-3 key/host table | native `FsDirectory`, drop + reopen, replay | **PASS (EXECUTED)** |
| A-I05 negatives (stale revision/overflow/token) | `m5_mutation_qualification::{m5_t05_stale_expected_revision_fails_without_mutation_memory_and_fs,m5_t11_one_over_the_query_match_limit_is_a_typed_failure_without_truncation,m5_t20_changed_token_payloads_conflict_without_admission_fs}` plus `m5_t07`, `m5_t19` | M5 independent oracle | `cargo +stable test -p quervant-core --test m5_mutation_qualification` | **PASS (EXECUTED)** |
| A-I06 old snapshot immutability | `a15_t13_retained_pit_is_immutable`, `a15_t14_stale_reader_cannot_see_new_commit`, `pr15a_compatibility::a15_c01_reopened_fs_with_retained_pin_and_mutation` | frozen old/new key and host table | native `FsDirectory`, mutation, compaction, reopen | **PASS (EXECUTED)** |
| A-I07 golden/legacy accept/reject | `pr14_storage_vertical::b18_b19_historical_json_segment_compatibility`, `segment_golden`, `pr11_json_corruption::t14_negotiation_and_corruption_fail_closed`, `pr15a_compatibility::a15_c03_historical_json_segment_digest_unchanged` | frozen fixture digests and typed errors | local targets listed in `compatibility.md` | **PASS (EXECUTED)** |
| A-I08 remote/local equivalence + zero GET | `pr15a_provider::a15_r01_r02_r03_fake_provider_vertical_and_zero_get`, `pr15a_provider::real::a15_r02_real_rustfs_pr15a_vertical`, `pr14g_remote_zero_get::a02_real_rustfs_zero_get_after_warmup` | static oracle identical to A-T01/A-T04/A-T05/A-T07; exact fake GET counter; real `TransferStats` | deterministic fake + pinned RustFS | **PASS (EXECUTED)** |
| A-I08 negatives (wrong generation/cache) | `pr14_storage_vertical::real::r03_wrong_generation_is_not_substituted`, `r12_empty_cache_no_writer_state`; `pr14_storage_faults` F01–F10 | existing fault harness | real RustFS | **PASS (EXECUTED)** |
| A-I09 cancellation/resource/fault bounds | `a15_t17_cancellation_is_slot_local`, `pr14a_public_cursor::{t11_response_and_memory_budgets_include_cursor_exactly_once,j10_json_work_limit_exact_and_one_under}`, PR 14 faults F01–F10 | existing typed cancellation/budget/fault outcomes | local + real RustFS | **PASS (EXECUTED)** |
| A-I10 evidence backed by executed commands | this document, `preflight.md`, `local-validation.md`, `provider-validation.md`, `compatibility.md` | command logs under `target/pr15a/` | every gate above | **PASS (EXECUTED; CI PENDING)** |
| A-I11 no compatibility change | `git diff --name-status 80a3864..HEAD` | all 12 paths additive tests/docs/data | `git diff --check` | **PASS (EXECUTED)** |

## 2. New test IDs

| ID | Test name | Oracle independence | Result |
|---|---|---|---|
| A-T00 | `a15_t00_frozen_fixture_and_pure_oracle` | static records evaluated before indexing; literal hardcoded expectations; intentional wrong-set negative; digest recomputed twice | **PASS (EXECUTED)** |
| A-T01 | `a15_t01_lexical_and_mixed_boolean_oracle` | frozen title/n table | **PASS (EXECUTED)** |
| A-T02 | `a15_t02_memory_and_fs_reopen_equivalence` | frozen table; memory vs reopened native FS | **PASS (EXECUTED)** |
| A-T03 | `a15_t03_absent_and_boolean_negatives` | set algebra over frozen titles | **PASS (EXECUTED)** |
| A-T04 | `a15_t04_cidr_and_time_range` | static CIDR/timestamp membership | **PASS (EXECUTED)** |
| A-T05 | `a15_t05_json_scalar_and_source_states` | frozen severity/tags state table | **PASS (EXECUTED)** |
| A-T06 | `a15_t06_ip_family_json_states_and_typed_failures` | address-family and JSON-kind contract | **PASS (EXECUTED)** |
| A-T07 | `a15_t07_groups_metrics_and_exact_distinct` | independent host tally/sums/distinct | **PASS (EXECUTED)** |
| A-T08 | `a15_t08_ties_empty_groups_and_top_k` | canonical tie rule + static order | **PASS (EXECUTED)** |
| A-T09 | `a15_t09_pinned_pages_concatenate_exactly` | static `n`-ascending order | **PASS (EXECUTED)** |
| A-T10 | REUSED — see `pr14a_public_cursor` rows above | existing negatives | **PASS (EXECUTED)** |
| A-T11 | `a15_t11_generation_three_mutation_and_replay` | frozen generation-3 state table | **PASS (EXECUTED)** |
| A-T12 | REUSED — see `m5_mutation_qualification` rows above | M5 independent oracle | **PASS (EXECUTED)** |
| A-T13 | `a15_t13_retained_pit_is_immutable` | frozen old/new table | **PASS (EXECUTED)** |
| A-T14 | `a15_t14_stale_reader_cannot_see_new_commit` | frozen old/new keys | **PASS (EXECUTED)** |
| A-T15 | REUSED — `b18_b19` + `segment_golden` | frozen fixture digests | **PASS (EXECUTED)** |
| A-T16 | REUSED — `pr11_json_corruption::t14` + `b18_b19` unsupported major | typed rejection contract | **PASS (EXECUTED)** |
| A-T17 | `a15_t17_cancellation_is_slot_local` | typed cancellation contract | **PASS (EXECUTED)** |
| A-T18 | REUSED — `pr14a_public_cursor::{t11,j10}` | exact/one-under budget contract | **PASS (EXECUTED)** |
| A-R01/A-R02/A-R03 | `a15_r01_r02_r03_fake_provider_vertical_and_zero_get`, `real::a15_r02_real_rustfs_pr15a_vertical` | static oracle + exact counters | **PASS (EXECUTED)** |

## 3. Provider evidence map

| Row | Command | Observed |
|---|---|---|
| A-R01 fake cold reopen + oracle | `cargo +stable test -p quervant-core --test pr15a_provider` | 1 passed; cold `get_calls() > 0`; warmed families unchanged |
| A-R02 real cold reopen + oracle | `cargo +stable test -p quervant-core --all-features --test pr15a_provider -- --ignored --exact real::a15_r02_real_rustfs_pr15a_vertical --test-threads=1` | 1 passed; `whole+range = 2`; warmed `requests()` unchanged |
| A-R03 wrong generation/cache | `pr14_storage_vertical::real::r03_wrong_generation_is_not_substituted`, `r12_empty_cache_no_writer_state` | PASS |
| A-R04/A-R05 faults | `pr14_storage_faults -- --ignored f0` | 9 passed, 10 iterations per stateful case |
| Zero-GET inherited witness | `pr14g_remote_zero_get -- --ignored` | 1 passed |

## 4. Explicit non-claims

- No PR 15A row relies on a skipped/ignored test as a pass.
- No historical PR 14 result is promoted to fresh PR 15A acceptance; historical
  fixtures are reused only with unchanged bytes/digests.
- No benchmark throughput or memory claim is made.
- No GitHub CI result is claimed.
- No merge, release or tag is authorized by this document.
