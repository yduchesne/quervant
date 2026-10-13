# PR 5 corrective validation report

> Final tree (uncommitted at time of writing, then committed). `cargo +1.85.0`
> (`rustc 1.85.0 (4d91de4e4 2025-02-17)`). No merge.

## 1. Mandatory command results (final tree)

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — **716 passed / 0 failed / 2 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — **85.16% line / 89.51% function / 92.45% region** |
| Whitespace | `git diff --check` | 0 | clean |

`--fail-under-lines` enforcement re-verified in the previous pass (`99` exits
non-zero). The 2 ignored tests are the pre-existing RustFS SKIP and the golden
regeneration helper.

## 2. Baseline vs corrective evidence

| Phase | Command | Result |
|---|---|---|
| Baseline (pre-correction `b47861c`) | `cargo +1.85.0 test --workspace --all-targets` | 689 passed / 0 failed / 2 ignored |
| Baseline reproducers (worktree `b47861c`) | `cargo +1.85.0 test -p trawler-core --test baseline_repro` | **0 passed / 3 failed** (column `values_length`, column `state_offset`, manifest required feature) |
| Corrective tree | full suite | 716 passed / 0 failed / 2 ignored |
| Corrective acceptance | `cargo +1.85.0 test -p trawler-core --test segment_corrective` | 24 passed / 0 failed |

## 3. C5 acceptance test execution

| Test ID | Rust test(s) | Result |
|---|---|---|
| C5-U01–U05 | `c5_u01_…`, `c5_u02_…`, `c5_u03_…`, `c5_u04` (at-limit) via `c5_u01`, `c5_dictionary_retained_budget_and_errors` | PASS |
| C5-U06–U12 | `c5_u06`, `c5_u07`, `c5_u09`, `c5_u10`, `c5_u11`, `c5_column_geometry_branch_coverage` | PASS |
| C5-U13–U15 | `c5_i01_valid_columns_still_read_all_docs`, `p5_a23` | PASS |
| C5-U16–U18 | `c5_u16_manifest_segment_count_is_preflighted`, `manifest_feature_order_and_schema_length_errors` | PASS |
| C5-U19–U23 | `c5_u19`, `c5_u20`, `c5_u22`, `manifest_feature_order_and_schema_length_errors` | PASS |
| C5-U24–U25 | `c5_u22` duplicate ids, `manifest_round_trip_full` | PASS |
| C5-U26–U30 | `p5_u27_group_keys_do_not_collide`, `p5_g01_group_key_wire_bytes_match_approved_f07` | PASS |
| C5-U31–U34 | `c5_u31`, `c5_u32`, `p5_a08` | PASS |
| C5-U35–U43 | `c5_u37`, `c5_u38`, `c5_u39`, `c5_u41`, `c5_stored_truncation_and_count_mismatch`, `c5_dictionary_retained_budget_and_errors` | PASS |
| C5-U44–U48 | `c5_p03_truncation_never_panics_and_fails_typed`, existing typed-error tests | PASS |
| C5-I01–I04 | `c5_i01`, `p5_i01_memory_directory_reopen`, `p5_i06_fs_directory_fresh_instance_reopen`, `c5_reader_rejects_forged_columns_and_coherence` | PASS |
| C5-G01–G03 | `p5_g01_group_key_wire_bytes_match_approved_f07`, `p5_g02_golden_decodes_expected_table` | PASS |
| C5-P01–P03 | `c5_u01` (dictionary), `c5_p03_truncation_never_panics_and_fails_typed`, mutation battery in `c5_column_geometry_branch_coverage` | PASS |

## 4. Real-boundary topology

`MemoryDirectory` and a **freshly reopened `FsDirectory`** are exercised in
`p5_i01_memory_directory_reopen` / `p5_i06_fs_directory_fresh_instance_reopen`
against a temporary on-disk segment, and the multi-column/multi-block vertical
slice is covered by `p5_a23` + `p5_g02`. RustFS is not required for this codec
fixup and was not tested; no remote integration is claimed.

## 5. Golden fixture integrity

`crates/trawler-core/tests/fixtures/segment/golden.seg`
`sha256 = ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`
— **unchanged** before and after the corrective pass.

## 6. Failure classification

No mandatory gate failed. No introduced regression, feature defect, flaky
failure, or environment/harness failure observed. Pre-existing items unchanged:
`docs/TESTING.md` conflict markers (out of scope) and the RustFS/S3 SKIP (PR 13).

## 7. Limitations

- Coverage margin is 0.16 pt above the 85% floor.
- `check_alloc` is a conservative bound.
- Whole-file read bounded by `accepted_segment_bytes`.
- Group-key API correction is documented for review.
