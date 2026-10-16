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

## Corrective test matrix

Executed on the corrective pass. `PASS` = test ran and passed; `PARTIAL` =
partially exercised; `NOT EXECUTED` is recorded rather than inferred.

| ID | Test | Result |
|---|---|---|
| M01 | Ranged stage of a large object (`ranged_get_stages_all_chunks_in_order`); real RustFS `rustfs_ranged_segment_transfer_matches_whole` | PASS (fake + RustFS), 128 MiB-scale size NOT EXECUTED |
| M02 | `no_range_support_and_oversize_rejects_before_network` (`get_calls == 0`) | PASS |
| M03 | `retained_response_bytes_peak_stays_within_ceiling` (BytePool peak ≤ ceiling) | PASS |
| M04 | Retained byte lease survives through staged write (source + `FetchedChunk`); no controlled-slow-write test | PARTIAL |
| M05 | Hundreds of chunks streamed via `while let` (no `try_collect`); source + large-range test | PASS (source) |
| M06 | `m06_warm_cache_hit_performs_no_remote_get` | PASS |
| M07 | `m07_concurrent_same_key_fills_run_one_leader_transfer` | PASS |
| M08 | Exact/one-over disk limits, concurrent eviction (existing cache suites; shared `reserve`) | PARTIAL |
| M09 | Nonmultiple final range + coverage + SHA-256 (`plan_ranges_exact_and_final_short_chunk`, staging digest) | PASS |
| M10 | HTTP 200 / bad Content-Range / short body rejection (`s3::tests::validates_content_range_exactly`); real fault proxy NOT EXECUTED | PARTIAL |
| M11 | Interrupted GET leaves no visible file (`interrupted_ranged_transfer_fails_without_publication`); write/verify cancel NOT EXECUTED | PARTIAL |
| M12 | Failed temp deletion charged; restart reconciliation (existing cache suites) | PASS (pre-existing) |
| M13 | `m13_wrong_digest_rejects_before_promotion` | PASS |
| M14 | Pinned reader survives eviction; no remote DELETE (`delete_and_reload_from_remote`) | PARTIAL |
| M15 | `v01_lexical_results_match_local_oracle` (`get_calls == 0` after hydration) | PASS |
| M16 | Permit/byte ceiling tests; cancellation waiters PARTIAL | PARTIAL |
| T01 | `transient_failure_is_retried_with_backoff_then_succeeds` (2 attempts, 100 ms) | PASS |
| T02 | `two_transients_use_100_then_200ms` (3 attempts) | PASS |
| T03 | `retry_exhaustion_uses_exactly_max_retries_plus_one_attempts` | PASS |
| T04 | `nontransient_failure_is_not_retried` | PASS |
| T05 | Cancel during backoff (source: sleeper drop cancels; no dedicated test) | PARTIAL |
| T06 | Real proxy timeout/5xx and SDK retry count | NOT EXECUTED |
| C01 | `segment_upload_failure_leaves_current_unchanged` | PASS |
| C02 | Mutation-state PUT failure (same ordered-upload path; not individually injected) | PARTIAL |
| C03 | Manifest PUT failure (same path) | PARTIAL |
| C04 | `two_writers_same_base_one_wins_one_conflicts`, real `rustfs_stale_writer_cannot_overwrite_current` | PASS |
| C05 | `ambiguous_current_publication_reconciles_exact_candidate` | PASS |
| C06 | `ambiguous_unreadable_current_requires_recovery` | PASS |
| C07 | Cancel during upload poisons writer (terminal rejection asserted after upload failure) | PARTIAL |
| C08 | Cancel after local commit before CAS (synchronous terminal set; dedicated dropped-future test NOT EXECUTED) | PARTIAL |
| C09 | Cancel during CAS; fresh reopen (real proxy) | NOT EXECUTED |
| C10 | Separate-process crash after manifest before CURRENT | NOT EXECUTED |
| C11 | Separate-process crash after CURRENT before ack | NOT EXECUTED |
| C12 | Old PIT stable (`r04_old_pit_observes_its_generation`) | PASS |
| V01 | `v01_lexical_results_match_local_oracle` | PASS |
| V02–V05 | Typed/time/JSON/geo/PIT independent oracle | NOT EXECUTED |
| V06 | `v06_upsert_delete_reopen_has_no_resurrection` | PASS |
| V07 | Real `rustfs_write_cold_open_query_and_restart` | PASS |
| V08 | Query-scoped pruning | DEFERRED / NOT EXECUTED (planner-contract amendment) |
| P01–P03 | Remote benchmark lane | NOT EXECUTED |
| L01 | Default local-only build compiles/tests without runtime | PASS |

## Final acceptance matrix (H/K/O/P)

Executed on the final candidate. `PASS` = executed and passed; `PARTIAL` = only
part exercised; `NOT EXECUTED`/`DEFERRED` recorded as such.

### HTTP fault proxy (H) — real signed RustFS via loopback proxy

| ID | Test | Result |
|---|---|---|
| H01 | `pr13_proxy_rustfs::h01_transparent_proxy_preserves_signed_cas_and_ranges` | PASS (10×) |
| H02 | `pr13_proxy_rustfs::h02_truncated_ranged_response_is_a_typed_failure` | PASS (10×) |
| H03 | `pr13_proxy_rustfs::h03_ranged_request_returning_200_is_rejected` | PASS (10×) |
| H04 | `pr13_proxy_rustfs::h04_invalid_content_range_is_rejected` | PASS (10×) |
| H05 | `remote::transfer::tests::retained_response_bytes_peak_stays_within_ceiling` | PARTIAL (unit, not proxy-delayed) |
| H06 | `pr13_remote_proxy::h06_segment_transient_503_is_retried` | PASS (10×) |
| H07 | `pr13_remote_proxy::h07_persistent_503_exhausts_attempts` | PASS (10×) |
| H08 | `pr13_remote_proxy::h08_nontransient_403_is_not_retried` | PASS (10×) |
| H09 | `pr13_remote_proxy::h09_cancel_during_delayed_get_publishes_nothing` | PASS (10×) |
| H10 | `pr13_remote_proxy::h10_cas_applied_response_dropped_reconciles` | PASS (10×) |
| H11 | `pr13_remote_proxy::h11_cas_blocked_then_timeout_requires_recovery` | PASS (10×) |
| H12 | `pr13_remote_proxy::h12_concurrent_stale_writers_one_winner` | PASS (10×) |

### Separate-process crash checkpoints (K)

| ID | Test | Result |
|---|---|---|
| K01 | `pr13_crash_rustfs::k01_crash_after_segment_before_state` | PASS (10×) |
| K02 | `pr13_crash_rustfs::k02_crash_after_state_before_manifest` | PASS (10×) |
| K03 | `pr13_crash_rustfs::k03_crash_after_manifest_before_current` | PASS (10×) |
| K04 | `pr13_crash_rustfs::k04_crash_after_cas_before_ack` | PASS (10×) |
| K05 | Crash during partial ranged download | NOT EXECUTED (H02/H09 partial) |
| K06 | Cancelled commit after local commit before publication | PASS via H11 (in-process, distinct classification) |

### Independent oracle (O)

| ID | Family | Result |
|---|---|---|
| O01 | Lexical term/phrase/Boolean/BM25 | PASS (local + fake + RustFS) |
| O02 | Typed range incl/excl | PASS |
| O03 | Temporal half-open boundary | PASS |
| O04 | JSON paths | NOT EXECUTED (not supported by current searchers) |
| O05 | GeoPoint bbox/radius/polygon | NOT EXECUTED |
| O06 | Geo ranking/ties | NOT EXECUTED |
| O07 | PIT stability | PASS |
| O08 | Upsert/delete/reopen no resurrection | PASS |
| O09 | Cold reopen RustFS; warm scoring zero GET | PASS |
| O10 | Explicit commit visibility | PASS |

### Benchmarks (P)

| ID | Result |
|---|---|
| P01 | PASS — whole vs ranged identical hits/bytes; measured |
| P02 | PASS — warm scoring zero remote GET (asserted per trial) |
| P03 | PASS — ranged peak retained bytes = configured ceiling; no incomplete visibility |
| P04 | PASS — no speedup threshold asserted |

## Review-fixup matrix (O04–O06, K05, E, T07–T10, P05–P07)

Executed after the review fixups. `PASS` = executed and passed on the stated
backend; `NOT EXECUTED` recorded explicitly.

### JSON / GeoPoint / GeoDistance oracles (`pr13_oracle_geo`)

| ID | Case | Result |
|---|---|---|
| O04A | JSON path exists (nested member, array wildcard) | PASS (local + fake + RustFS) |
| O04B | JSON scalar equality (string/int/bool) + type mismatch | PASS |
| O04C | JSON null vs missing; null never equals a scalar | PASS |
| O04D | wildcard equality → typed error; invalid path → parse error | PASS |
| O05A | bbox ordinary inclusive edges | PASS |
| O05B | bbox antimeridian crossing | PASS |
| O05C | radius inside/outside (100 km, 1000 km, 1200 km) | PASS |
| O05D | polygon interior/exterior and hole exclusion | PASS |
| O05E | geo in And/Or/Not with typed range | PASS |
| O05F | invalid polygon/radius/bbox validation | PASS |
| O06A | GeoDistance ascending/descending | PASS (supported) |
| O06B | equal-distance key tie-break; missing-loc last | PASS |
| O06C | GeoDistance search-after pagination (no gap/duplicate) | PASS |

### K05 real child-process mid-range crash (`pr13_crash_rustfs`)

| ID | Case | Result |
|---|---|---|
| K05A | kill after a staged chunk, before remaining range completes → no final segment key | PASS (10×) |
| K05B | same-workspace abandoned cache reconciled via public `SegmentCache` → orphan cleaned | PASS (10×) |
| K05C | fresh empty workspace recovers generation 1 and all 600 documents | PASS (10×) |

### Fail-closed RustFS acceptance (E)

| ID | Case | Result |
|---|---|---|
| E01 | unset `QUERVANT_RUSTFS_ENDPOINT` | PASS — process exit 101, "must be set" |
| E02 | empty endpoint | PASS — process exit 101, "must not be empty" |
| E03 | unreachable endpoint | PASS — process exit 101 |
| E04 | invalid credentials | PASS — process exit 101 |
| E05 | correct pinned RustFS + env | PASS — targets execute and pass |

### Retry timer (T07–T10)

| ID | Case | Result |
|---|---|---|
| T07 | default (non-s3) build, two transients → real elapsed ≥ 250 ms, 3 attempts | PASS |
| T08 | s3 + real proxy, two transients → 3 attempts, elapsed ≥ 250 ms | PASS (H07) |
| T09 | cancel during backoff → 1 GET, byte lease released | PASS (unit) |
| T10 | non-transient → 1 attempt, no sleep | PASS (unit + H08) |

### Large-segment stress (P05–P07)

| ID | Case | Result |
|---|---|---|
| P05 | 104,864 docs → 22,635,901-byte (~21 MiB) segment, ranged, oracle hits = docs | PASS |
| P06 | ranged peak retained = 2,097,152 B ≤ 16 MiB ceiling | PASS |
| P07 | two concurrent cold opens on the same generation | PASS |
| — | 64 MiB case (`QUERVANT_PR13_STRESS_MIB=64`) | NOT EXECUTED (opt-in; heavy) |

### Correlated corrections

- `test-traceability.md` O04–O06 "NOT EXECUTED / not supported" entries above are
  **superseded**: JSON and GeoPoint operators are implemented and now tested.
- K05 is now a **real child-process crash**, not an in-process H02/H09 shorthand.
