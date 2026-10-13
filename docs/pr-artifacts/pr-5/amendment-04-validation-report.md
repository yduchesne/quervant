# PR 5 Amendment 04 validation report

> Final working tree (committed SHA recorded in branch log). `cargo +1.85.0`
> (`rustc 1.85.0`) and stable `1.99.0`. No merge.

## 1. Mandatory commands

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — **771 passed / 0 failed / 2 ignored** |
| Tests (stable) | `cargo test --workspace --all-targets` | 0 | PASS — **771 passed / 0 failed / 2 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint (MSRV) | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Lint (stable) | `cargo clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — **85.25% line / 89.56% fn / 92.58% region** |
| Whitespace | `git diff --check` | 0 | clean |

The 2 ignored are the pre-existing RustFS SKIP and the golden regeneration
helper; no new ignores.

## 2. A4 test execution

`cargo +1.85.0 test -p trawler-core --test segment_corrective_pass04` →
**17 passed / 0 failed**; `segment::decode_budget` unit tests → **5 passed**.

| Test ID | Rust test | Result |
|---|---|---|
| U01–U03 | `decode_budget::tests::{failed_reservation…, vector_cumulative…, vector_multiplication…, byte_addition…, string_and_btree…}` | PASS |
| U04–U07 | `a4_u04_u05_dictionary_outer_vector_boundary`, `a4_u04_u06_dictionary_inner_entry_boundary`, `a4_u07_dictionary_order_utf8_duplicate_truncation` | PASS |
| U08–U10 | `a4_u08_u09_schema_vector_and_name_boundary`, `a4_u10_schema_invalid_and_truncated` | PASS |
| U11–U15 | `a4_u11_u12_stored_shared_budget`, `a4_u14_stored_key_and_invalid`, `a4_u15_stored_multi_value_and_nested_string` | PASS |
| U16–U18 | `a4_u16_u17_nested_json_array_shared_budget`, `a4_u18_json_depth_count_and_truncation` | PASS |
| U19–U20 | `a4_u19_u20_public_wrappers_and_ordering` | PASS |
| U21 | existing `segment_corrective` column tests (`c5_i01`, `p5_a23`) | PASS |
| U22–U26 | `a4_u22_identity_both_vector_boundary`, `a4_u23_explicit_two_vector_boundary`, `a4_u24_u25_remap_validation`, `a4_u26_remap_truncation_and_trailing` | PASS |
| U27 | `a4_u27_error_then_valid_no_partial_state` | PASS |
| I01 | existing `p5_g01` builder→reader (dictionary/schema/stored/remap) | PASS |
| I02 | existing `p5_g01`, `p5_a08`, `p5_a23` stored/JSON/column | PASS |
| I03 | `a4_i03_tight_budget_failure_then_valid_open` | PASS |
| I04 | existing `p5_i01_memory_directory_reopen`, `p5_i06_fs_directory_fresh_instance_reopen` | PASS |
| G01 | golden SHA `ebb078…dae979` unchanged | PASS |
| G02 | `segment_codec`, `segment_golden`, `segment_corrective*` suites | PASS |

## 3. Independent charge oracle

Tests compute expected charges from fixture counts/lengths and `size_of::<T>()`
(e.g. dictionary `outer + 2*entry + term bytes`, stored shared budget, JSON
`4*size_of::<JsonValue>() + 6`, remap `2*doc_count*8`). Sibling records / nested
children are used to detect accidental budget resets (U12, U16). The production
`retained()` accessor is asserted only in the unit tests, not used to derive
expectations.

## 4. Topology

The production path is exercised by existing real `SegmentBuilder` → bytes →
`SegmentReader::open` and `MemoryDirectory`/fresh `FsDirectory` reopen tests
(I01–I04). RustFS is out of scope and was not tested.

## 5. Golden fixture

`crates/trawler-core/tests/fixtures/segment/golden.seg`
`sha256 = ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`
— unchanged; not regenerated.

## 6. Failure classification

No mandatory gate failed. No introduced regression, feature defect, flaky
failure, or environment/harness failure. Pre-existing `docs/TESTING.md` markers
and the RustFS SKIP remain out of scope.

## 7. Limitations

- Modeled retained-byte charge, not allocator/RSS.
- `BTreeMap` node overhead estimate.
- Manifest budget intentionally separate.
- Each logical decode has its own budget.
