# PR 14 — Test traceability

Topology: real `IndexWriter` → immutable segments → `MemoryDirectory`/`FsDirectory` (via PR 10/11/12 helpers and the new `pr14_common`) → explicit commit → fresh `Index::open_existing`/snapshot → production `TypedSearcher`/`LexicalSearcher`/`UnifiedSearcher`/`execute_batch`. Expected values are enumerated independently in-test; no implementation internals are asserted for correctness.

| ID | Test symbol | Status |
|---|---|---|
| T01 | `tests/pr14_typed_predicates.rs::t01_presence_truth_table` | PASS |
| T02 | `t02_membership_truth_table` | PASS |
| T03 | `t03_multivalue_membership` | PASS |
| T04 | `t04_ip_exact_family` | PASS |
| T05 | `t05_ip_range_endpoints` | PASS |
| T06 | `t06_ipv4_cidr_boundaries` | PASS |
| T07 | `t07_ipv6_cidr_boundaries` | PASS |
| T08 | `t08_ip_not_in_cidr` | PASS |
| T09 | `t09_ip_network_containment` | PASS |
| T10 | `t10_compound_typed_boolean` | PASS |
| T11 | `t11_delete_and_pit` | PASS |
| T12 | `t12_cancellation` | PASS |
| J01 | `tests/pr14_json.rs::j01_range_endpoints` | PASS |
| J02 | `j02_scalar_types_stay_distinct` | PASS |
| J03 | `j03_non_scalar_does_not_match` | PASS |
| J04 | `j04_signed_unsigned_float` | PASS |
| J05 | `j05_immediate_array_membership` | PASS |
| J06 | `j06_indexed_not_stored` | PASS |
| J07 | `j07_path_budgets_fail_closed` | PASS |
| J08 | `j08_reversed_and_mismatched_bounds` | PASS |
| J09 | `j09_sort_missing_null` | PASS |
| J10 | `j10_sort_multivalue_selector` | PASS |
| J11 | `j11_json_sort_search_after` | PASS |
| J12 | `j12_json_composes_with_typed_predicates` | PASS |
| J13 | `j13_cancellation` | PASS |
| P01 | `tests/pr14_projection.rs::p01_source_projection` | PASS |
| P02 | `p02_field_order` | PASS |
| P03 | `p03_five_state_preserved` | PASS |
| P04 | `p04_invalid_projections_rejected` | PASS |
| P05 | `p05_projection_budget` | PASS |
| P06 | `p06_deleted_documents_excluded` | PASS |
| P07 | `p07_pure_lexical_delegation` | PASS |
| P08 | `p08_mixed_predicates_fail_closed` (STOP S1 negative) | PASS |
| P09 | `p09_lexical_explicit_sort_fails_closed` | PASS |
| P10 | `p10_pure_typed_delegation` | PASS |
| A01 | `tests/pr14_aggregation.rs::a01_grouped_metrics` | PASS |
| A02 | `a02_distinct_and_frequency` | PASS |
| A03 | `a03_time_buckets` | PASS |
| A04 | `a04_time_bucket_requires_field` | PASS |
| A05 | `a05_mapping_is_explicit` | PASS |
| B01 | `tests/pr14_batch.rs::b01_single_slot` | PASS |
| B02 | `b02_ordered_mixed_outcomes` | PASS |
| B03 | `b03_empty_envelope` | PASS |
| B04 | `b04_too_many_queries` | PASS |
| B05 | `b05_conflicting_pit` | PASS |
| B06 | `b06_shared_budget_not_reset` | PASS |
| B07 | `b07_cancellation_preserves_cardinality` | PASS |
| B08 | `b08_aggregation_slot_isolated` | PASS |
| B09 | `b09_cursor_slot_fails_closed` (STOP S2 negative) | PASS |
| B10 | `b10_invalid_aggregate_kind` | PASS |

## Matrix coverage gaps (NOT READY)
- U01–U06 (mixed execution, mixed live universe): blocked by STOP S1; only the fail-closed negative P08 exists.
- J14 old-segment JSON fallback, J15 legacy segments: not exercised by a dedicated PR 14 test (covered indirectly by existing PR 11 legacy suites for the unchanged fallback path).
- G01–G14 dedicated budget/cancellation matrix: only partial (T12/J13/P05/B06/B07).
- R01–R07 RustFS cold/warm/fault/golden: not executed.
- X01–X13 independent local/FakeObjectStore/real-RustFS oracles: local oracles only; FakeObjectStore/RustFS verticals not executed.

## Pre-existing behavior changes in updated tests
- `pr10_integration.rs` T59: replaced `Query::Exists` (now supported) with `Query::Prefix` in the “unsupported fails closed” set.
- `pr11_json_corruption.rs` T23: replaced `Query::Exists` with `Query::In` on a JSON field (still unsupported in the typed engine).
- `pr10_sort.rs`, `pr13_oracle_geo.rs`: added `json_path: None` to `SortField` literals after the new field was introduced.
