# PR 14 — Adversarial review

Each mandatory claim below is demonstrated by a named, executed test. Anything not demonstrated is listed as open.

| Required demonstration | Named test | Verdict |
|---|---|---|
| Negative-only BM25 is not scored | PR 7 `pr07_amendment01` suites (unchanged) | demonstrated by existing suite; not re-derived |
| OR/NOT cannot resurrect tombstones | `pr14_typed_predicates::t11_delete_and_pit`; `pr14_projection::p06_deleted_documents_excluded` | demonstrated |
| JSON `1`, `1.0`, `"1"`, null do not conflate | `pr14_json::j02_scalar_types_stay_distinct`, `j03_non_scalar_does_not_match` | demonstrated |
| Missing/null sorting and ties do not skip pages | `pr14_json::j09_sort_missing_null`, `j11_json_sort_search_after` | demonstrated |
| `NotIn` does not include absent fields | `pr14_typed_predicates::t02_membership_truth_table`, `t08_ip_not_in_cidr` | demonstrated |
| Unstored fields cannot leak | `pr14_projection::p01_source_projection`, `p04_invalid_projections_rejected` | demonstrated |
| Batch budgets do not reset | `pr14_batch::b06_shared_budget_not_reset` | demonstrated |
| Cancellation does not omit slots | `pr14_batch::b07_cancellation_preserves_cardinality` | demonstrated |
| Mixed predicates are not silently mis-scored | `pr14_projection::p08_mixed_predicates_fail_closed` | demonstrated (fails closed) |
| Scoring performs no RustFS GET | not instrumented | **OPEN** |
| Old segments are not silently misread | existing PR 11 legacy suites only | **PARTIAL** |
| RustFS acceptance is not skipped | not run | **OPEN (BLOCKED)** |

## Known risks / limitations

1. **Mixed lexical+typed execution is unimplemented (STOP S1).** Any query mixing lexical and typed leaves returns a typed unsupported error. This is deliberate and fail-closed; it is not an approximation. Callers cannot get a wrong mixed result.
2. **No public pagination cursor (STOP S2).** `UnifiedSearcher` returns no continuation token; batch cursor slots are rejected.
3. **Projection decoding granularity.** `SegmentReader::stored_doc` lazily decodes the whole stored section of a segment; the executor only opens stored sections for segments that actually contain selected keys. Sub-segment single-record decode is not provided by the current codec.
4. **Batch response is lossy at the contract boundary.** `contract::SearchHit` cannot represent absent/null/empty/multi states; the executor omits absent/null/empty and expands multi values. The internal `UnifiedResponse` is lossless.
5. **JSON sort for multi-root fields.** Concrete paths are prefixed with the virtual multi-root index; wildcard paths require an explicit multi-value selector.
