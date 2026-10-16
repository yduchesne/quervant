# PR 14 — Preimplementation correctness gate

This document records the §3 gate findings at HEAD `7ca1b2e` before production edits.

## STOP conditions

| STOP | Status | Finding / resolution |
|---|---|---|
| S1 — reusable lexical leaf/scorer seam | **TRIGGERED, UNRESOLVED** | No per-segment lexical membership seam exists without extracting `execute.rs` internals (`build_leaf_data`, `eval_node`, `SnapshotStats`, `Expansion`, `SegmentCandidateLedger`) and changing lexical execution plumbing. Per the contract this was **not** implemented by copying `execute.rs`. Mixed lexical+typed queries fail closed with `SearchError::UnsupportedOperator { operator: "mixed_predicate_stop_s1" }`. Pure lexical and pure typed trees remain fully supported. **Maintainer approval of a minimal extraction API + regression oracle is required to proceed.** |
| S2 — public cursor cannot represent sorted search-after | **TRIGGERED, UNRESOLVED** | `contract::result::Cursor` carries only pit/sort/last-key, not the full sort tuple. No unified cursor is exposed; `QueryRequest::cursor`/batch cursor slots are rejected (`batch_cursor_stop_s2`). No public shape was modified. |
| S3 — JSON missing/null/mixed-type ordering | **RESOLVED** | The existing `SortValue` categories (`Missing` < `Null` < `Value`, direction-independent) plus `canonical_scalar_cmp` type rank provide a total, deterministic order. JSON string nodes map to `Keyword` for byte comparison. Implemented and tested (J09/J10/J11). |
| S4 — indexed-but-not-stored JSON operators | **RESOLVED (no format change)** | The immutable indexed JSON-path section exposes every concrete scalar occurrence with ancestry, so range/membership can be evaluated for `indexed=true, stored=false` fields. Tested (J06). Legacy segments without the section retain the existing stored-source fallback or fail closed; no codec/manifest change. |
| S5 — PR 2 missing/null/multivalue semantics | **RESOLVED WITH DOCUMENTED DISCREPANCY** | Plan §2.4 prose says “Exists = present non-null”; the **approved** PR 2 decision A09 says `EXISTS` is true for present **including explicit null and empty multi** (`EXISTS` is the exact complement of `MISSING`). Per the plan’s own instruction to follow the approved contract, the implementation follows A09/A10 and the plan prose discrepancy is recorded here. |

## Invariant → intended evidence mapping (I01–I16)

| Invariant | Implementation approach | Evidence |
|---|---|---|
| I01 identical AST+snapshot → identical logical hit set | pure engines delegated, one snapshot per request | X-local oracles in PR14 tests; mixed deferred by S1 |
| I02 no deleted/obsolete docs | `effective_live_docs` reused; deletes/PIT tested | T11, P06 |
| I03 BM25 only from positive lexical leaves | delegated to PR 7/8 engine unchanged | P07 + existing PR 7 suites |
| I04 exact counts, gap-free pagination | engine `total_hits` + cursor binding | P07/P10; JSON J11 |
| I05 cursor binds snapshot/query/sort/tuple | typed cursor unchanged; JSON path added to fingerprint | J11; S2 for public cursor |
| I06 JSON scalar type and range boundaries | same-type comparison, no coercion | J01–J04 |
| I07 JSON missing/null/multivalue sort deterministic | `SortValue` + min/max selector | J09/J10 |
| I08 no unstored-field leak | `ProjectionPlan` requires `stored=true` | P01/P04 |
| I09 IP/CIDR family and missing/null truth tables | typed compiler + A09/A10 | T01–T10 |
| I10 exact aggregates share predicate | adapter reuses `AggregationEngine` | A01–A05 |
| I11 batch cardinality and shared budgets | serial executor, `from_outcomes_for` | B01–B10 |
| I12 bounded work/memory/output, cancellation | existing ledgers + projection ledger | T12/J13/P05/B06/B07 |
| I13 zero query-time remote GET | scoring/projection read only the bound snapshot | not separately instrumented (14F unexecuted) |
| I14 persisted formats unchanged | no codec/manifest/section edits | golden suites unchanged |
| I15 legacy segments correct or typed fail-closed | unchanged fallback paths | existing PR 11 suites |
| I16 unsupported capabilities fail before expensive work | validation/compile before scan | P08/P09/B10 |

## Adversarial counterexamples selected

- Negative-only lexical leaf must not score (PR 7 Amendment 01 oracle) — reused unchanged.
- `NOT IN` must not resurrect absent/null — T02/T08.
- JSON `1`, `1.0`, `"1"`, `true` must not conflate — J02.
- Nested array element must not satisfy scalar-array membership — J05.
- Missing/null JSON sort must not skip pages — J09/J11.
- Unstored field must not leak — P01/P04.
- Batch budget must not reset per slot — B06.
- Mixed query must not be silently mis-scored — P08.
