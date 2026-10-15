# PR 13 — corrective pre-implementation gate

**Baseline:** `main` `653b412e0e7df8efe18602479b661629427fab57`; implementation
commit `43edef4` (`PR 13 Phase 0`). This gate precedes the corrective refactor.

## Inspected interfaces

- `crates/quervant-core/src/storage/cache.rs`: `prepare`/`fill`/`offload_write`,
  `FillOwnership`, `FillSlot`, `reserve`, `scan_directory`/`apply_reconciliation`,
  `classify_owned` (`cache-v1-*`, `tmp-v1-*`, `.trawler-tmp-*`).
- `crates/quervant-core/src/storage/io.rs`: `Offloader::submit(&self, bytes, op,
  reconcile)` — the bounded filesystem worker pool used for all blocking file
  work.
- `crates/quervant-core/src/storage/fs.rs`: `resolve`/`resolve_writable`,
  `atomic_write_impl` (temp → fsync → rename → dir sync), `sync_dir`.
- `crates/quervant-core/src/remote/{mod,transfer,publication}.rs`.
- `crates/quervant-objectstore/src/s3.rs`: `open` uses `RetryConfig::disabled()`.

## Why the private staging seam is safe

`FsDirectory` gains only two `pub(crate)` inherent methods
(`open_staged`, `promote_staged`) and one `pub(crate)` handle
(`FsStagedWrite`). These **do not** change the `Directory` trait, persisted
formats, or the cache reconciliation grammar: staged files use the existing
`tmp-v1-*` key class. The cache's existing reservation, accounting, pinning,
reconciliation and eviction remain the sole ledger; the staged file is charged
once through `reserved_bytes` and promoted by rename without a second ledger.
No public storage abstraction was added and no external framework was
introduced.

## Invariant-to-test map

| Invariant | Evidence | Status |
|---|---|---|
| I01 retained response buffers ≤ ceiling | `retained_response_bytes_peak_stays_within_ceiling` (BytePool high-water mark) | PASS (fake) |
| I02 no full-segment Vec / all-chunks collect | source inspection; `ranged_get_stages_all_chunks_in_order` streams via `buffer_unordered` + `while let` | PASS |
| I03 hit/follower makes no redundant GET | `m06_warm_cache_hit_performs_no_remote_get`, `m07_concurrent_same_key_fills_run_one_leader_transfer` | PASS |
| I04 cache owns staging/promotion/accounting | `FsDirectory` private stage + existing cache admission; `m13` | PASS |
| I05 permits/leases/cancellation | `permit_pool_ceiling_is_enforced`, `aggregate_byte_ceiling_is_enforced`, `retained_response_bytes_peak…`, `interrupted_ranged_transfer_fails_without_publication` | PASS |
| I06 verify before visibility | `m13_wrong_digest_rejects_before_promotion` + existing cache digest suites | PASS |
| I07 CAS-last durability + terminal writer | `first_commit_publishes_current_last`, `two_writers…`, `ambiguous_*`, `segment_upload_failure…` (terminal rejection) | PASS |
| I08 local-only/1.85/codecs/query/distributed unchanged | default-feature build + full workspace suite | PASS |
| I09 no remote I/O in scoring; eviction never deletes remote | `v01_lexical_results_match_local_oracle` (`get_calls == 0`), `delete_and_reload_from_remote` (`delete_calls == 0`) | PASS |

## Failure transitions challenged

| Transition | Expected | Result |
|---|---|---|
| GET interrupted mid-range | typed error; no publication; leases released | PASS (fake) |
| Fetch succeeds, digest wrong | `IntegrityMismatch`; no destination file | PASS |
| Transient then success | 2 attempts; 100 ms virtual delay | PASS |
| Two transients then success | 3 attempts; 100/200 ms | PASS |
| Exhausted retries | exactly `max_retries+1` attempts | PASS |
| Non-transient (auth/interrupt) | one attempt; no delay | PASS |
| Ambiguous CAS, candidate readable | reconciled success; writer usable | PASS (fake) |
| Ambiguous CAS, unreadable | `RecoveryRequired`; writer terminal | PASS (fake) |
| Upload failure | `CURRENT` unchanged; writer terminal; further mutations rejected | PASS (fake) |

## STOP assessment

No STOP was triggered: private staged finalize is possible with
`FsDirectory`-local methods, cache accounting is not duplicated, the committed
format is unchanged, and the default local-only build gains no runtime
dependency (Tokio is optional behind `s3`).
