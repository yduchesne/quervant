# PR 14 — Final design implementation report

Head: `e0e1dcb` + final-design edits (uncommitted at report time).

## F1 — Unified lexical/typed match stream (DONE)

- `search/unified_plan.rs` (new): `UnifiedNode` tree, `UnifiedPlan`, leaf interning, positive
  parity, scoring field ids.
- `search/plan.rs`: `compile_lexical_leaf`.
- `search/execute.rs`: `evaluate_lexical_with`, `LeafData::matches`, crate-private
  `CandidateBudget`/`SearchWork`; `build_leaf_data` now takes `&[CompiledLeaf]`.
- `search/typed.rs`: crate-private exposure only.
- `search/unified.rs`: mixed queries run through the unified tree over `effective_live_docs`;
  `Not` complements the live universe only; positive lexical leaves score via `score_segment`;
  negative-only leaves never score; typed-only matches get score `0.0`; explicit non-geo sort
  uses the typed canonical comparator; default relevance is BM25 desc then key asc.
- New `tests/pr14_unified_mixed.rs` (**14 tests**) covers nested And/Or/Not, double negation,
  negative-only lexical, phrase+range, regex+JSON, duplicate leaves, delete/reinsert, two
  segments, zero hits, pure-lexical score parity (bit-exact), and explicit sort. Mixed queries
  no longer fail closed; this supersedes the earlier `mixed_predicate_stop_s1` behavior.

## F2 — SelectedHit, sort, cursor (PARTIAL)

- `SelectedHit { segment_index, doc_id, key, score, sort_tuple }` exists internally for the
  mixed path; projection uses exact `reader.doc_key(doc_id)` verification + `stored_doc(doc_id)`
  (`project_selected_hits`), never a global key rescan.
- Explicit non-geo sorts use one canonical comparator (`sort_tuple_for_doc` +
  `compare_candidates`); default lexical relevance uses exact `f64` score.
- **Not implemented:** unified `RuntimeCursor`; geo-distance sort on mixed queries returns a
  typed unsupported error. No authoritative PIT resolver (D2). Batch cursor slots fail closed.

## F3 — Shared governance and batch admission (PARTIAL)

- D4 **done:** `execute_batch` now takes `policy: &BudgetPolicy` and `supported: &CapabilitySet`,
  calls `validate_envelope_with_policy` before any segment open, and validates each slot with
  `QueryRequest::validate(schema, supported)` in input order. New
  `pr14_batch::b13_capability_rejection_is_isolated`.
- D5 **not implemented:** no shared `ExecutionMeter`; work is still metered by the local
  `SearchWork`/`ScanGuard`. The batch ledger meters response bytes and hit count only.
- D6 **done (previous pass):** exhaustive `to_query_error`; `Cancelled { ClientCancellation }`.

## F4 — Compound aggregation (NOT IMPLEMENTED)

No matched-document visitor or `contract::batch::AggregateResponse` / `SearchResponse.aggregation`
was added. Batch aggregation slots still fail closed (`batch_aggregation_pending_stop_s1`).

## F5 — Verticals / faults / benchmarks (NOT EXECUTED)

`pr14_unified_mixed.rs` is the only new vertical. No RustFS endpoint was available (BLOCKED); no
benchmarks were run.

## Earlier corrections retained

- Lossless `contract::batch::SearchHit.fields: Vec<(String, FieldValues)>` and `project_hit`.
- `QueryError::ExecutionFailure` and exhaustive batch error mapping.
