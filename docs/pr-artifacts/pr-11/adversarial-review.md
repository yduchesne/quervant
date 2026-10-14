# PR 11 — Adversarial review and counterexample disposition

**State:** PR 11 working tree on `dev/json-indexing`.
**Method:** every counterexample listed in
[`preimplementation-correctness.md`](preimplementation-correctness.md) was re-tested against the
final implementation; corrupt/legacy/PIT/limit paths were probed with malformed bytes and starved
budgets.

## Counterexample disposition

| # | Counterexample | Disposition / evidence |
|---|---|---|
| 1 | `$.events[*].ip = "a"` wildcard equality | Rejected in `Query::validate` and again in `validate_query`; `t10_preflight_failures`. |
| 2 | Independent `Exists` clauses must not correlate arrays | `t11_document_level_boolean`; wildcard equality rejected. |
| 3 | `I64(1)`/`U64(1)`/`F64(1.0)` distinct | `t08_equality_type_exact`; node kind is part of the wire. |
| 4 | `-0.0 == 0.0` | Normalized in extraction, encoding and `JsonScalar`; `t08`, codec unit test. |
| 5 | NFC vs NFD distinct | `t09_string_bytes_and_path_aliases`. |
| 6 | `$.a` ≡ `$["a"]` | `t09`; parser decodes both to the same `Member`. |
| 7 | Duplicate members: indexed rejected, stored-only kept | `t02_duplicate_members`. |
| 8 | Absent / ExplicitNull / Json null / Empty distinct | `t06_field_state_truth_table`. |
| 9 | Multi-root virtual `[0]`/`[1]` | `t05_multi_root_virtual_index`, codec unit test. |
| 10 | JSON null / empty array / empty object **exist** | `t04_empty_and_nested`, `t07_wildcard_existence`. |
| 11 | Feature/section mismatch fails closed | `t14_negotiation_and_corruption_fail_closed`. |
| 12 | Legacy fallback / unstored typed error | `legacy_source_fallback_and_unstored_error`. |
| 13 | `[*]` over scalar no match, over null array match | `t07`. |
| 14 | `Not(Exists)` keeps path-less live docs, excludes tombstoned | `t19_delete_upsert_and_negation`. |

## Corruption probes

- Flipped byte inside the section body → envelope/section digest mismatch → `SegmentReader::open` error.
- Version byte bumped → decode rejects unsupported version.
- Trailing byte appended to a rebuilt section → `expect_end` rejects.
- Non-JSON field id (`n`) in the field table → decode rejects.
- Every truncation prefix of an encoded section decodes as a typed error (no panic).
- Feature without section and section without feature both fail at open.

## Legacy and PIT behaviour

- A legacy segment (JSON feature/section stripped) still opens for non-JSON work; a JSON predicate
  uses the bounded stored-source evaluator for a stored field and returns
  `UnsupportedOperator` (not a silent miss) for an indexed-but-not-stored field.
- A PIT taken before an upsert still resolves the prior revision's JSON paths; compaction rebuilds
  the section by remapping decoded occurrences and an after-compact reopen returns the same hits.

## Amendment 01 (A1) disposition

A1 claimed the JSON-path `skip_node`/`decode_node` kind-4 branches accept non-finite F64. This did
**not** reproduce: `ByteReader::f64` (`segment/format.rs:350`) has rejected non-finite values since
the pre-PR-11 baseline, so both branches already return
`SegmentError::NonFiniteFloat { context: "json path f64" }`. A1-T01/T02/T03/T04 pass against
unmodified production; A1-T03 uses a valid-checksum rebuilt envelope, so rejection is semantic.
Per plan §0/Phase 0 the redundant production edit was not applied. See
[amendment-01-preimplementation.md](amendment-01-preimplementation.md).

## Residual risks accepted

- Logical budgets do not guarantee a hard process-RSS ceiling.
- A per-segment occurrence scan is exact and bounded but is not a specialized inverted dictionary.
- Correlated array ancestor binding, range/membership JSON operators, projections and sorting remain
  deferred (PR 14+).
