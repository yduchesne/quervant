# PR 11 — Invariant and test traceability

**Working tree:** `dev/json-indexing` at `81b8a31713f79a0855210f89d8857c2e5cbb3802` + PR 11 changes (uncommitted at report time).
**Command form:** `cargo test -p quervant-core --test <name>` (stable 1.98.1 and MSRV 1.85.0 both PASS).

| Invariant | Step(s) | Test file / name | Executed result |
|---|---|---|---|
| J11-I01 source round-trip | 4,8 | `pr11_json_paths::t01_stored_json_round_trip`; `pr11_json_paths::t02_duplicate_members` | PASS |
| J11-I02 one exact concrete path | 3,4 | `pr11_json_paths::t03_array_ancestry`, `t04_empty_and_nested`, `t05_multi_root_virtual_index`; `segment::json_paths::tests::{round_trip_paths_and_nodes, multi_root_prefixes_indices}` | PASS |
| J11-I03 missing/null/empty distinct | 2,5 | `pr11_json_paths::t06_field_state_truth_table`, `t07_wildcard_existence` | PASS |
| J11-I04 type-exact equality | 2,5 | `pr11_json_paths::t08_equality_type_exact`; `pr11_json_properties::t_oracle_matches_exactly` | PASS |
| J11-I05 preflight failures | 2,5 | `pr11_json_mutations::t10_preflight_failures`; `pr11_json_corruption::t15_query_path_depth_bound` | PASS |
| J11-I06 document-level Boolean | 5 | `pr11_json_properties::t11_document_level_boolean`; `pr11_json_properties::t_oracle_matches_exactly` | PASS |
| J11-I07 feature/section/legacy | 4,6 | `pr11_json_corruption::{t13_feature_section_and_determinism, t13_json_paths_golden_fixture, t14_negotiation_and_corruption_fail_closed}`; `search::typed::legacy_json_tests::legacy_source_fallback_and_unstored_error`; `pr11_json_properties::t24_pr5_fixture_unaffected` | PASS |
| J11-I08 bounds / decode / work / cancel | 3,4,5 | `segment::json_paths::tests::{depth_and_member_bounds, corruption_fails_closed}`; `pr11_json_corruption::{t15_decode_budget_limits, t16_work_budget_and_cancellation}` | PASS |
| J11-I09 ids/live/PIT/refresh/compact/reopen | 4–7 | `pr11_json_mutations::{t18_refresh_commit_reopen_and_pit, t19_delete_upsert_and_negation, t20_compact_rebuilds_json_paths}` | PASS |
| J11-I10 stored/indexed policy | 2,5,7 | `pr11_json_mutations::{t21_index_and_storage_policy, t21_indexed_only_is_visible_after_reopen}` | PASS |
| J11-I11 determinism / order | 3,4 | `pr11_json_corruption::t13_feature_section_and_determinism`; `pr11_json_properties::t22_order_independent_results`; `segment::json_paths::tests::encoding_is_deterministic` | PASS |
| J11-I12 existing behavior unaffected | 5–8 | Entire baseline workspace suite (`cargo test --workspace --all-targets`), incl. PR 7/8/9/10; `pr11_json_corruption::t23_unrelated_operators_still_unsupported` | PASS |

## Independent oracle

`pr11_json_properties::t_oracle_matches_exactly` walks the in-memory `JsonValue` tree with a
test-only evaluator (`reference_eval`, `ref_path_matches`, `ref_scalar_matches`) that never uses the
production section, offset directory, compiled predicate or matcher. It generates 100 deterministic
documents (seed `0x11_2026`, max depth 5, arrays ≤ 4, member length ≤ 12, no duplicate keys) and 250
predicates (Exists, concrete Equals, `And`/`Or`), then compares the **logical document keys** of
production `TypedSearcher` against the oracle. 0 mismatches.

## Test counts

| Suite | Tests |
|---|---|
| `pr11_json_paths` | 9 |
| `pr11_json_mutations` | 6 |
| `pr11_json_corruption` | 7 (+1 ignored fixture generator) |
| `pr11_json_properties` | 4 |
| `segment::json_paths` unit | 9 |
| `search::typed::legacy_json_tests` unit | 1 |

## Coverage

`cargo llvm-cov --workspace --all-targets --fail-under-lines 85` → **TOTAL 91.69% line**,
87.79% branch, 91.27% function. `segment/json_paths.rs` 90.86% line. Threshold met.

## Not independently verified here

- Remote RustFS / distributed topology: out of PR 11 scope (PR 13 / v0.2).
- Real process-RSS hard cap: logical budgets only (documented residual risk).
