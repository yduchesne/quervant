# XJ-001 — Cross-index catalog, identity and query foundation

**Status:** proposed v0.2 architecture extension, documentation only. Supports multi-index search and a future relational/graph/ontology query layer; **does not authorize distributed joins, shuffle, cross-index graph relationships or federated ontology inference**. Implementation ownership: [D08 and D11](ROADMAP.md). Design references: [C1–C6](03-QUERYING.md), [C7](07-STREAMING.md), [DS-001](09-SERVICE-PROTOCOLS.md), [QGS-005](../graph/QGS-005.md), [QGS-006](../graph/QGS-006.md), [QOS-001](../ontology/QOS-001.md), [QOS-004](../ontology/QOS-004.md).

## XJ-001-01 — Index catalog, identity and scope

- Stable immutable `IndexId` independent of display name, shard/node identity, and schema; index rename cannot change result identity. Index deletion/recreation does not recycle `IndexId`. Index identity is cluster-qualified where systems can encounter external references; cross-cluster federation remains unimplemented.
- Source-qualified document identity is `(IndexId, DocumentKey)` inside one cluster, not `DocumentKey` alone. Include index identity in result provenance, dedup key, pagination tie-breaker, and authorization check. Never use segment-local document IDs as cross-index identity.
- Catalog entry pins lifecycle status, schema and analyzer fingerprints, index routing/topology version, query capabilities, and shard identities. Catalog version/selector-expansion fingerprint is included in plan identity. No accidental query of a tombstoned/recreated index.
- Multi-index query selector initially accepts bounded explicit index IDs/names, optionally catalog-expanded selectors only if determinism, authorization, bounded count and revalidation are defined before exposing them. Treat unauthorized indexes as denied rather than hiding partial results where correctness would be affected. Require an explicit policy for unavailable/tombstoned indexes.
- Each index retains its own schema, analyzer, scoring semantics, ontology definitions (future), and shard routing. Joining index namespaces or selecting multiple indexes does **not** merge their definitions.

## XJ-001-02 — Typed schema reconciliation and query validation

For a logical field reference in multiple indexes, resolve it against **each** participating schema and compile index-specific shard subplans. A missing field, differing type, JSON path semantics, keyword normalizer, timestamp resolution, collator, multivalue sort policy, and analyzer compatibility must have explicit schema-level rules. Initial default: reject incompatible global filter/sort/aggregation operations with a typed validation error; optional per-index field mapping requires its own validated explicit configuration.

A field appearing in only some indexes may be represented by explicit missing/absent values *only if* requested predicate/projection semantics permit it and are validated against each schema. Preserve null vs missing distinctions. Reuse existing core lexical/typed predicates, JSON/time/geospatial operators and projection semantics; do not invent a second expression evaluator to implement multi-index search.

No silent numeric conversion (including loss-of-precision), untyped JSON stringification, timezone reinterpretation or lexicographic comparison of unlike scalar types. Define normalization and comparison version/fingerprint; a future join key must be a canonical typed value with explicit equality/null semantics, not a stringified field.

## XJ-001-03 — Logical relation and extensible plan boundary

Introduce a small higher-level, versioned logical plan independently of the optimized core Boolean predicate plan. v0.2 *executable* operators:

- `IndexScan(index_id, predicate, projection, optional_sort)`: shard-local predicates and projection pushed into existing core execution.
- `IndexSetScan(selection)`: resolves a bounded authorized set into individually compiled `IndexScan` leaves.
- `UnionAll(inputs)`: preserves bag multiplicity; results always retain source index. `Distinct` is explicit.
- `Filter` and `Project`: only capabilities with proven parity to core or directly composed existing operators; prefer safe pushdown.
- `Sort`, `Limit`, and supported `Aggregate`: applied globally with same C3 exactness and C7 blocking/streamable semantics.

Plan IR includes typed result schema; optional source slots and typed binding identifiers reserved for QGS-005. Future `Join`, `Exchange`, `VertexScan`, `AdjacencyExpand`, `OntologyScan` and `EffectiveFactScan` are **reserved but non-executable** until separate approval and capability negotiation; either omit variants initially or reject at validation, never silently fallback. Define stable operator IDs/plan fingerprints, ordering guarantees and version negotiation. QOS-004 canonical URNs are future operator-identity authority where applicable; don't assume proposed QOS-009 is approved.

One logical query has one outer `SearchService` execution; adapter handlers do not duplicate planners. A single-index plan should not regress by forcing result materialization into a generic relation table.

## XJ-001-04 — Index-set snapshot descriptor

Extend C4 snapshot to `(catalog_version, selector_fingerprint, [ (index_id, routing_version, schema/operator_fingerprint, [ (shard_id, generation, manifest_digest) ]) ])`. Authoritative per-index shard generations and retention pins survive the multi-phase query and continuation lifetime. An index-set snapshot is a vector of **independent committed index/shard generations**, not an atomic multi-index transaction nor a shared global timestamp.

- `AVAILABLE`: choose eligible independently committed generations and report actual selected vector, no cross-index simultaneity.
- `AT_LEAST(vector)`: each required shard must reach the specified lower bound or typed timeout/error.
- `EXACT(vector)`: use precise generation/manifest digests for all required shards, including after failover.
- Catalog expansion and index identity must not silently change during a multi-stage query or cursor continuation. A dropped/renamed/recreated index cannot be substituted by another index sharing a name.
- Pin/acquire cluster-level snapshot protection for all selected index/shard dependencies before executing; on partial acquire failure release reservations and fail before data emission. GC-002 retention/DR barriers remain prerequisites.

A replay/cursor token must bind index-set identity, schema/plan/query fingerprints, pinned vector, total sort key, positions, expiry and integrity protection. Standalone `UnifiedCursor` is not implicitly a durable cross-index cursor.

## XJ-001-05 — Global combination and scoring

For `UnionAll`, duplicates across different source indexes remain distinct; duplicates of the same shard/replica attempt never count twice. Global deterministic sort adds source index identity and stable document key to the total tie-breaker (with shard identity as needed for unambiguous canonical identity). Ordering of missing/null values and multivalued typed fields follows the compiled canonical comparator. Limit is applied **after** global merging.

Exact supported count, sum, min, max, avg, group-by, distinct and time buckets merge all relevant source contributions under C3 and C5; do not pre-truncate per-index data in a way that changes the aggregate. `Distinct` identity/value projection must be explicit; `UNION ALL` does not deduplicate.

BM25: C2 `GLOBAL_STATS` means global statistics **across shards of one logical index** unless a separately designed, compatible cross-index corpus is deliberately defined. Different analyzer/schema/field-length semantics yield scores that cannot be silently compared or averaged across indexes. Initial multi-index ranked policy: reject global relevance-based ordering with incompatible scoring configurations; otherwise explicitly named per-index grouping/rank-combination modes are allowed only if their semantics are separately specified and tested. Do not claim statistically comparable global BM25 simply because scores are numeric.

## XJ-001-06 — Resources, streaming, authz and failure semantics

- Admit one global C5 budget with non-overlapping reservations across indexes/shards, query phases, replicas, retries, spill, output and client transport; no per-index budget reset. Bound selector cardinality, fan-out, index-schema mapping, retained snapshots and cursor size.
- C7 finite result stream frames include index-qualified row origin; native gRPC and NDJSON have identical completeness/error semantics via DS-001. Cancel propagates to every index and shard. Unclean close is not success; a missing required index fails strict query with typed terminal error even after partial output.
- Opt-in partial mode returns explicitly covered and omitted **indexes and shards**, not just shard count. No partial success mistaken for exact aggregates, global top-K or proven absence.
- Authorization is evaluated per index before selection and at every query source; schema/catalog/EXPLAIN/cursor details must not leak inaccessible index names. A syntactically valid query is not authorization to all index entries.

## XJ-001-07 — Mandatory differential, contract and failure tests

1. Two indexes with the same `DocumentKey` remain distinct under UNION, projection, aggregation, sorting and cursor round-trip.
2. Index rename/delete/recreate during plan preparation, execution and continuation never substitutes a different `IndexId`.
3. Missing fields, null, multivalues, incompatible timestamp/JSON/geo/numeric types and analyzer differences fail or match independently specified semantics.
4. Multi-index `UNION ALL` result matches concatenated per-index independent snapshot reference oracle with global sorting; no physical replica double count.
5. Exact aggregate results equal an independent reference implementation over full selected corpus, including ties and high-cardinality budget rejection.
6. Multi-index sort + `LIMIT` + cursor paging produce no gaps or duplicates across equal timestamps and cross-index duplicate keys.
7. Pinning a catalog+index generation vector survives replica changes but not invalid snapshot substitution, index deletion or retention loss; explicit typed errors.
8. Partial index/shard failures, delayed attempt frames, and cancellation produce truthful terminal failures/partiality and conserved global budget.
9. HTTP NDJSON and native gRPC emit identical semantic events for the same query and snapshot; slow clients never create unbounded memory or background tasks.
10. Mixed scoring configurations cannot silently produce globally comparable BM25; per-index scores remain clearly labeled with the selected mode.
11. Cross-index join/exchange, graph traversal and ontology inference operator execution is rejected as unsupported in v0.2, even if encoded in a future-version plan.
12. Real multi-node etcd/RustFS integration and fault injection, >=85% production Rust coverage gate, immutable generation recovery, and cold-cache access as appropriate.

## XJ-001-08 — Post-v0.2 join dependency handoff

This specification deliberately lays **interfaces, not fake implementations** for future work:

1. **XJ-002:** binding relation values/identity, bag/set/null semantics and local indexed-loop, hash, semi/anti join operator implementations over local sources.
2. **XJ-003:** versioned Tonic Gather/Broadcast/Repartition exchange protocol; bounded demand, partition-level attempt IDs, duplicate suppression, failure/stream termination and optional spill.
3. **XJ-004:** colocated, broadcast and repartition distributed hash join with stage ownership, consistent snapshot, global accounting.
4. **XJ-005:** bounded join planner, safe predicate pushdown, estimates and EXPLAIN/ANALYZE.
5. **XJ-006:** differential parity, real-service retries, skew, memory/spill and streaming qualification.

Later graph QGS-005/006 uses binding relations and exchange for vertex/edge sources and frontier rounds; **DG-P1/DG-P2** remain mandatory for actual distributed graph integrity. Ontology QOS-001 remains index-local: joining independently entailed facts across indexes is not cross-index inference. Federated rule evaluation, rule ownership and global invalidation need a separately qualified design.

**STOP:** v0.2 implementation PRs may not turn a multi-index scan into a distributed join engine, weaken C4/C5/C7 semantics, infer cross-index transactional consistency, or advertise graph/ontology execution because an IR variant exists. Detailed implementation plans must derive exact Rust interfaces from fresh source per [authoring guide](../DETAILED_PR_PLAN_AUTHORING_GUIDE.md).
