# PR 14 — Implementation report

Working tree based on `main` @ `7ca1b2ec59fec648602e0e4a52e8f903a596f106`.

## Delivered

### 14A — Unified compiler and execution seam (PARTIAL)
- New `search/unified.rs`: `UnifiedSearcher`, `UnifiedRequest`, `UnifiedResponse`, `ProjectedHit`.
- Query classification into neutral/pure-lexical/pure-typed/mixed.
- Pure lexical delegates to `LexicalSearcher` (BM25); pure typed and explicit-sort `MatchAll` delegate to `TypedSearcher`; projections are applied to selected keys.
- **Mixed lexical+typed queries fail closed** with `mixed_predicate_stop_s1` (STOP S1). Explicit sort on a lexical query fails closed with `lexical_explicit_sort`.
- The previously planned `search/plan.rs` name was already taken by the PR 7 lexical compiler, so the unified plan/classification lives in `search/unified.rs` rather than overwriting an existing module.

### 14B — Typed/IP/CIDR completeness (DONE)
- `search/typed.rs` now compiles and evaluates `Exists`, `Missing`, `IsNull`, `In`, `NotIn`, `IpExact`, `IpRange`, `IpInCidr`, `IpNotInCidr`.
- Semantics follow approved PR 2 decisions A09/A10 and A07/A08; IP family mismatches are `false`, CIDR host/`/0`/`/32`/`/128` boundaries are handled by `IpNetwork::contains`.
- `IpInCidr` on an `IpNetwork` field matches a stored network that is a family-matched subset of the query network (documented extension; no approved contract contradicted).
- Cursor fingerprint encoding extended for every new leaf.

### 14C — JSON completion (DONE for range/membership/sort)
- `contract/query.rs`: `JsonPathRange`, `JsonPathArrayContains` with `ConcreteJsonPath` (wildcards rejected by type).
- `contract/result.rs`: `SortField::json_path: Option<JsonPathExpr>` with `with_json_path`; validation requires an indexed JSON field and a multi selector for multi-cardinality or wildcard paths.
- `segment/json_paths.rs`: same-type scalar range comparison, immediate-index-child detection, array detection, node→`FieldValue` conversion (JSON string → `Keyword`).
- `search/typed.rs`: `JsonRange`/`JsonArrayContains` compilation and evaluation, JSON sort value computation, fingerprint encoding.
- No on-disk format change.

### 14D — Stored source and projections (DONE)
- New `search/projection.rs`: `ProjectionPlan` (compile-time validation; `Source` and ordered `Fields`), `ProjectionLedger`, `projected_hit_bytes`.
- Five-state `FieldValues` preserved for `Fields`; `Source` returns present stored fields only. Unstored/unknown/duplicate requests fail before scanning.
- `UnifiedSearcher` reads stored records only for selected keys and charges output bytes.

### 14E — Aggregation and ordered batch (DONE for serial typed/neutral queries)
- `AggregateRequest::from_contract` in `search/analytics.rs` maps `contract::aggregation::Aggregation` to the runtime request, rejecting unsupported mappings.
- New `search/batch.rs`: `execute_batch` validates the envelope first, executes slots serially against one snapshot, shares one cumulative ledger (never reset), preserves exactly-one ordered outcome per slot, and isolates per-slot failures. Aggregation and cursor slots fail closed per-slot.

## Not delivered (see STOP / final gate)

- **Mixed lexical+typed execution** (STOP S1) — fail closed.
- **Public/unified pagination cursor** (STOP S2) — not exposed.
- 14F real-boundary RustFS vertical/fault tests and benchmark qualification.
- 14G new-SHA CI observation and real-RustFS ignored targets.
- Contract-level response representation for aggregation (contract `SearchResponse` has no aggregation field); batch aggregation is rejected rather than downgraded.

## Touch list
- Modified: `contract/query.rs`, `contract/result.rs`, `search/{analytics,mod,plan,typed}.rs`, `segment/{json_paths,mod}.rs`, and three existing tests whose pre-PR-14 “operator is unsupported” expectations changed by design (`pr10_integration.rs` T59, `pr11_json_corruption.rs` T23, and `SortField` literal fixups in `pr10_sort.rs`/`pr13_oracle_geo.rs`).
- Added: `search/{unified,projection,batch}.rs`, `tests/pr14_common/`, `tests/pr14_{typed_predicates,json,projection,aggregation,batch}.rs`.
