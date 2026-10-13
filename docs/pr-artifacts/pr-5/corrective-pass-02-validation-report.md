# PR 5 corrective pass 02 validation report

> Final tree, `cargo +1.85.0` (`rustc 1.85.0 (4d91de4e4 2025-02-17)`). No merge.

## 1. Mandatory commands

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — **738 passed / 0 failed / 2 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — **85.13% line / 89.56% function / 92.54% region** |
| Whitespace | `git diff --check` | 0 | clean |

Targeted suites also run: `segment_corrective` (24), `segment_codec` (24),
`segment_golden` (1 + 1 ignored), `segment_corrective_pass02` (22). The 2
workspace-ignored tests are the pre-existing RustFS SKIP and the golden
regeneration helper; no new ignored tests were added.

## 2. Baseline vs fixed

| Phase | Command | Result |
|---|---|---|
| Baseline (pass-01 tree `75134b8`) | `cargo +1.85.0 test -p trawler-core --test p2_baseline_repro` (worktree) | **0 passed / 1 failed** — oversized single read rejected |
| Fixed tree | `cargo +1.85.0 test -p trawler-core --test segment_corrective_pass02` | **22 passed / 0 failed** |

## 3. C6 test execution

| Test ID | Rust test | Result |
|---|---|---|
| C6-U01 | `c6_u01_requests_are_chunk_bounded` | PASS |
| C6-U02 | `c6_u02_exact_chunk_is_one_request` | PASS |
| C6-U03 | `c6_u03_chunk_one_below_needs_two_requests` | PASS |
| C6-U04 | `c6_u04_empty_object_makes_no_read` | PASS |
| C6-U05 | `c6_u05_zero_chunk_fails_before_read` | PASS |
| C6-U06 | `c6_u06_single_byte_short_reads` | PASS |
| C6-U07 | `c6_u07_variable_fragments` | PASS |
| C6-U08 | `c6_u08_no_redundant_read_after_completion` | PASS |
| C6-U09 | `c6_u09_short_object_is_length_mismatch` | PASS |
| C6-U10 | `c6_u10_io_error_is_propagated` | PASS |
| C6-U11 | `c6_u11_total_size_cap_rejects_before_read` | PASS |
| C6-U12 | `c6_u12_duplicate_object_key_rejected` | PASS |
| C6-U13 | `c6_u13_three_unique_keys_decode_matches_model` | PASS |
| C6-U14 | `c6_u14_empty_manifest_round_trip` | PASS |
| C6-U15 | `c6_u15_many_unique_keys_within_budget` | PASS |
| C6-U16/U19/U20 | `c6_u16_u19_u20_retained_budget_boundaries` | PASS |
| C6-U17/U18 | `c6_u17_u18_truncated_and_malformed_manifest` | PASS |
| C6-I01 | `c6_i01_memory_directory_real_reopen` | PASS |
| C6-I02 | `c6_i02_fs_directory_fresh_reopen` | PASS |
| C6-I03 | `c6_i03_unknown_required_feature_fails_closed` | PASS |
| C6-I04 | `c6_i04_public_retained_bytes_is_conservative` | PASS |
| C6-G01 | `segment_golden::p5_g02_golden_decodes_expected_table` | PASS |
| C6-G02 | `segment_codec` round-trip + pass-02 manifest tests | PASS |
| baseline repro | `c6_baseline_oversized_read_reproducer` | PASS (red on baseline) |

## 4. Real-boundary topology

`MemoryDirectory` (`c6_i01`) and a **freshly reopened `FsDirectory`**
(`c6_i02`) read a real on-disk segment and compare bytes to the original
immutable input. The instrumented `Directory`/`ReadHandle` double proves request
chunking on the production `SegmentReader::open_directory` path; it is not a
private-function copy. RustFS is out of scope and was not tested.

## 5. Golden fixture

`crates/trawler-core/tests/fixtures/segment/golden.seg`
`sha256 = ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`
— **unchanged**. No fixture regeneration.

## 6. Failure classification

No mandatory gate failed. No introduced regression, feature defect, flaky
failure, or environment/harness failure. Pre-existing `docs/TESTING.md` markers
and the RustFS SKIP remain out of scope.

## 7. Limitations

- Whole-object buffering up to `accepted_segment_bytes` remains.
- `Manifest::retained_bytes` is a conservative upper bound.
- No authenticated selective range reads.
