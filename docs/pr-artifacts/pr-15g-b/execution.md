# PR 15G-B execution record

**Status:** `FIXUP_IMPLEMENTED_LOCAL_QA_PASS_PERF_QUALIFIED_CI_PENDING`
**Shared branch:** `dev/pr15g-a-retained-column-geometry`
**GB_BASE_SHA (pre-B):** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`
**Implementation commit:** `4e7949ad12236a0feeee671c6221119b8a998cc7`
**Final HEAD:** recorded after the documentation-only closure commit.
**Umbrella PR:** #86 `https://github.com/yduchesne/quervant/pull/86`

## Changed files

| Path | Change |
|---|---|
| `crates/quervant-core/src/segment/stored.rs` | optional offset-capture scanner, direct selected-record decoder, focused tests |
| `crates/quervant-core/src/segment/reader.rs` | `ValidatedOffsets`, two `OnceLock` cells, admitted `access_budget`, validated selected dispatch, DOC_KEYS scan helper, focused tests |
| `crates/quervant-core/tests/pr15g_b_access.rs` | real memory/FsDirectory/PIT/cursor/corruption/empty/singleton integration |
| `crates/quervant-core/tests/pr15g_b_rustfs.rs` | ignored pinned-RustFS cold-bootstrap selective-access test |
| `.github/workflows/ci.yml` | one additive `pr15g_b_rustfs` invocation in the existing pinned RustFS step |
| `benchmarks/pr15g_b/{README.md,run.py,test_run.py}` | isolated nine-lane B A/B runner and 18 deterministic tests |

No writer, format, schema, manifest, dependency, public query API or `main`
merge was changed. PR 15G-A files and evidence are preserved.

## Implementation summary

- `ValidatedOffsets` owns a `Vec<u64>` of `count + 1` relative record starts plus
  an independent `MetadataReservation`. `range()` performs checked `usize`
  conversion, range ordering and bounds access.
- `build_validated_offsets` checks `count + 1` overflow, existing entry and
  allocation limits, reserves the exact allowance through `MetadataMeter`, calls
  the authoritative scanner, validates first/terminal/monotonic boundaries and
  finalizes the measured capacity. Any failure drops both candidate vector and
  meter and is published as `OnceLock(None)`.
- STORED validation reuses one shared `decode_stored_selected_impl` body. Offset
  capture is observational; the selected caller passes `[]`, so every record
  still runs the original full modeled `DecodeBudget` and
  `skip_field_values_budgeted` validation.
- Direct STORED reads decode only checked selected slices, use a fresh
  selected-record `DecodeBudget`, preserve schema field order and five-state/JSON
  values, and call `expect_end` per record.
- DOC_KEYS scans with one shared body. Capture validates every key (version,
  count, limits, minimum bytes, UTF-8, nonempty, max 1024, trailing bytes) before
  publishing. Direct lookup decodes exactly one checked key slice.
- `VerifiedSegmentState` keeps two monotonic `OnceLock<Option<ValidatedOffsets>>`
  cells and an `access_budget` attached only after successful metered candidate
  finalization. Standalone/zero-cap/fallback states have no budget and never
  initialize a directory.
- Public full caches remain first. Malformed/out-of-range selections delegate to
  the legacy scanner before directory construction. `None` means optional
  acceleration unavailable; the original scanner remains authoritative for
  corruption, limits and error precedence.

## Test-to-witness mapping

| ID | Witness |
|---|---|
| GB-U01 | `stored::pr15g_b_tests::gbu01_zero_records_offsets_and_empty_selection` |
| GB-U02 | `gbu02_single_and_many_record_boundaries_are_consistent` |
| GB-U03 | `gbu03_selected_states_match_legacy_and_full_decode` |
| GB-U04 | `gbu04_invalid_unselected_key_fails_validation_and_legacy_alike` |
| GB-U05 | `gbu05_corrupt_unselected_nested_json_is_rejected` |
| GB-U06 | `gbu06_modeled_decode_limit_is_not_bypassed`; existing `segment::tests::phase3_u07_u10_budget_parity_exact_and_one_below` (exact/one-below) |
| GB-U07 | `gbu07_tiny_allocation_and_entry_limits_are_typed`; existing budget parity test |
| GB-U08 | `gbu08_malformed_selection_errors_match_legacy_order` |
| GB-U09 | `gbu09_empty_selection_validates_every_record` |
| GB-U10 | Existing `phase3_u07_u10_budget_parity_exact_and_one_below` plus `decode_budget` unit tests; no new duplicate model |
| GB-U11 | `gbu11_nested_json_direct_matches_full` |
| GB-U12 | `gbu12_injected_invalid_offsets_are_typed_and_never_panic` |
| GB-U13 | `reader::column_geometry_tests::gbu23_full_caches_take_precedence_and_do_not_initialize_offsets` |
| GB-U14 | `gbu23` plus `gbu21` assert query-local full caches remain unpopulated |
| GB-U15 | `gbu15_direct_reads_visit_only_selected_records` (thread-local operation counters) |
| GB-U16 | `gbu16_doc_keys_zero_one_and_many_match_legacy` |
| GB-U17 | `gbu17_invalid_unselected_keys_are_typed_on_both_paths` |
| GB-U18 | `gbu18_count_version_and_range_errors_are_typed` |
| GB-U19 | `gbu19_exact_budget_retains_and_one_under_falls_back`; `gbu26` panic/RAII |
| GB-U20 | `gbu20_two_readers_share_one_retained_directory` |
| GB-U21 | `gbu21_concurrent_first_access_publishes_once` |
| GB-U22 | `gbu22_validated_offsets_are_send_sync` |
| GB-U23 | `gbu23_full_caches_take_precedence_and_do_not_initialize_offsets` |
| GB-U24 | `gbu24_unmetered_and_zero_cap_never_allocate_offsets` |
| GB-U25 | `gbu25_directory_charge_releases_with_last_state_owner` |
| GB-U26 | `gbu26_initializer_panic_publishes_nothing_and_releases_budget` |
| GB-U27 | `gbu27_corrupt_unselected_stored_and_key_bytes_fail_closed` |
| GB-U28 | `gbu28_separate_states_never_share_offset_identity`; `pr15g_b_access::gb_i03` old/new generation |

| ID | Integration witness |
|---|---|
| GB-I01 | `pr15g_b_access::gb_i01_memory_projection_and_query_parity` |
| GB-I02 | `gb_i02_filesystem_reopen_projection_parity` |
| GB-I03 | `gb_i03_old_pit_and_new_generation_are_isolated` |
| GB-I04 | `gb_i04_cursor_pages_are_complete_and_unique` |
| GB-I05 | `gb_i05_reduced_metadata_cap_fallback_is_correct` + private `gbu24` |
| GB-I06 | `gb_i06_concurrent_readers_are_exact` |
| GB-I07 | `gb_i07_public_corrupt_stored_and_keys_fail_closed` + private `gbu27` |
| GB-I08 | `gb_i08_empty_and_singleton_segments` |
| GB-R01 | `pr15g_b_rustfs::gb_r01_real_rustfs_cold_bootstrap_selected_access` |
| GB-R02 | `pr13_remote_proxy` 7 passed; `pr13_crash_rustfs k0` 5 passed; `k05` 10/10 |
| GB-B01–B16 | `benchmarks/pr15g_b/test_run.py` — 18 tests |

## Byte/format parity

- Both benchmark arms produced identical deterministic index digests:
  - 10K `595b7783406d7bfbd9505e393ed355716c35b3cbee5d6d53c4ae1b8bfb062b77`
  - 100K `fd60b53fcfa1191f7a9b96602cf0aae2c1ebc7986608ed74bc7533ac59369995`
- Corpus manifest SHA-256:
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
- No `encode_stored`/`encode_doc_keys`, `SectionKind`, feature, manifest or schema
  change was made.

## Local QA (final code tree)

| Gate | Result |
|---|---|
| Stable/MSRV fmt | PASS |
| Stable/MSRV Clippy default/all-features | PASS |
| Stable/MSRV workspace tests | 2287 passed, 10 ignored, 121 result groups |
| Stable/MSRV all-feature workspace tests | 2291 passed, 77 ignored, 121 result groups |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.68%** |
| `segment/stored.rs` / `segment/reader.rs` line coverage | 92.65% / 91.34% |
| `cargo doc`, `cargo bench --no-run` | PASS |
| Script / PR15D / PR15F / PR15G-A / PR15G-B Python suites | 108 / 83 / 54 / 16 / 18 PASS |
| Pinned real RustFS GA-R01 | PASS (1 test) |
| Existing fault/recovery harness | 7 proxy + 5 K0 + 10× K05 PASS |
| `git diff --check` | PASS |

Logs: `target/pr15g-b/qa/final2/` and `target/pr15g-b/rustfs/`.

## Benchmark

The final campaign measured baseline `3329dd8` against candidate `4e7949a`,
three clear trials per arm, on the same host/corpus/index digests. All nine
lanes were `B_FASTER`; GB-P01–P05 all PASS. See
`performance-qualification.md`.
