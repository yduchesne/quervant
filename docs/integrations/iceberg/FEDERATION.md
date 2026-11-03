# Quervant + Iceberg federated query proposal (IFQ-001)

**Status:** PROPOSED architectural extension, documentation only. This document does not implement SQL, an Iceberg provider, native external scans, federated joins, or any Quervant graph/ontology feature. Read [overview](README.md), [synchronization](SYNC.md), [XJ-001](../../distributed/10-CROSS-INDEX-FOUNDATION.md) and [QGS-005](../../graph/QGS-005.md).

## Goal and precise boundaries

Allow a query to combine Quervant indexed matches with columns/aggregations sourced from **a pinned Apache Iceberg table snapshot** without requiring Quervant to index every Iceberg column. Quervant indexes selected source fields and maintains stable logical keys; Iceberg keeps canonical records and analytical data. Ordinary SQL scans require a separate execution engine (candidate: Apache DataFusion).

The initial proof of concept is **standalone external SQL federation**: Quervant is registered as an indexed DataFusion relation source and Iceberg is registered through Apache's DataFusion/Iceberg provider. DataFusion handles relational SQL and joins; Quervant retains native scoring and predicate execution. This prototype is **not** a replacement for the planned native higher-level Quervant IR, does not move general joins/shuffle into v0.2, and must not couple quervant-core to DataFusion.

A later native extension may introduce a general ExternalTableScan leaf under the approved higher-level typed relation IR, with Iceberg as one adapter and possible future PostgreSQL/Delta adapters. The concrete operator encoding, provider/optimizer ABI, security policy and distributed exchange contracts are **open** and must be owned by the corresponding XJ/QGS work before implementation.

## Conceptual query model

Source relation: Quervant IndexScan binds (IndexId, DocumentKey, source table UUID, ref, source logical row key, index generation/vector, indexed-source snapshot, configured fields and score where requested).

External relation: IcebergSnapshotScan binds (catalog, table UUID, ref, exact snapshot ID, schema/field IDs, selected columns and filter). Never use file path/row position as durable business row identity; compaction can relocate records.

Execution layer: typed joins, filters, projections, sort, aggregate and limit over bounded Arrow/record batches. Preserve SQL bag multiplicities and explicit null/missing/type conversions. BM25 relevance is a Quervant-specific score with explicit semantics; do not invent statistical comparability across distinct search indexes.

**Illustrative logical SQL only** (syntax, functions and catalog names are not implemented):

~~~sql
WITH candidates AS (
  SELECT event_id, score
  FROM TABLE(quervant_match('security_events', 'privilege escalation'))
)
SELECT e.event_id, e.event_time, e.payload, c.score
FROM candidates c
JOIN iceberg.security_events e ON e.event_id = c.event_id
WHERE e.event_time >= TIMESTAMP '2026-11-01 00:00:00'
ORDER BY c.score DESC
LIMIT 100;
~~~

The planner must prove whether restricting Quervant to top 100 *before* applying the Iceberg filter/join is safe; in general it is **not**. Fail or retain enough candidates to compute the correct final top 100. Search corpus completeness relative to the pinned Iceberg snapshot is also required to interpret NOT EXISTS, anti-joins, global counts and negative conclusions.

## Physical execution choices

| Plan | Trigger | Execution / safeguards |
| --- | --- | --- |
| Quervant-first | Highly selective indexed lexical/JSON/IP/time/geo predicates | Search pinned index, batch stable keys, hydrate/filter via snapshot-pinned Iceberg; don't blindly push global LIMIT or drop scores |
| Iceberg-first | Highly selective Iceberg-only partition/statistics predicate or cheap analytical prefilter | Iceberg scan with safe pruning/projection, batch canonical typed keys to Quervant filter/join; bound key transfer, no giant unbounded SQL IN-list |
| Independent scans + join | Neither side highly selective; large join | Bounded hash/merge or indexed nested loop, optional qualified spill; additional distributed exchange only after XJ-003+ approvals |
| Iceberg-only analytical query | No Quervant index advantage | Delegate to DataFusion/Iceberg rather than route through Quervant |
| Quervant-only search | No external columns/relations needed | Use existing Quervant SearchService/core execution without DataFusion overhead |

Pushdown is legal **only when proven semantics preserving**: filters, projections, dynamic filters, top-K/limit, sort order, null/NaN/decimal/timestamp/zone/collation, multivalue and analyzer semantics are not automatically interchangeable. Push down an Iceberg predicate only if the provider declares and actually honors the required accuracy contract; otherwise execute it in the outer engine with correct row and authorization semantics. Cost estimates may select plans but may never justify unsafe result pruning.

## Proposed DataFusion prototype

1. Use an isolated Quervant DataFusion TableProvider (or equivalent supported extension) to translate supported pushdown expressions into existing Quervant indexed predicates and return typed Arrow batches, stable row keys, score and origin metadata.
2. Use the Apache datafusion-iceberg table provider for Iceberg table reads; require verification of **explicit snapshot binding**, read modes, supported v2+ row deletes, nested value/type parity, predicate pushdown and catalog access. Registration alone proves none of these.
3. Register a strictly specified search table function/UDF or logical extension for BM25; ordinary SQL scalar function invocation must not trick the optimizer into full scan semantics or unsafe scoring.
4. Add a coordination layer to select and pin eligible source/index snapshots **before** creating scan plans. Prove both DataFusion providers consume exactly those versions, not a fresh latest version during retries.
5. Return Arrow RecordBatches incrementally with bounded memory/backpressure/cancellation and truthful terminal success/error; a SQL operator may block for a correct sort/top-K or aggregate.
6. Do **not** duplicate Quervant's native planner inside two client transport stacks; separate SQL adapter from the Quervant SearchService query implementation. No automatic translation of SQL to graph or ontology inference.

Dependency policy: evaluate current compatible Rust toolchains, DataFusion/iceberg-datafusion/iceberg-rust versions and data types before choosing exact crates. The Apache datafusion-iceberg repository currently pins an iceberg-rust revision; do not assume arbitrary version compatibility. Never add these heavyweight dependencies to quervant-core for a standalone proof of concept.

## Cross-system snapshot and query eligibility

Let the durable synchronization record associate **Iceberg table UUID/ref/source snapshot S** with a **complete, verified Quervant index generation G** (or later a qualified shard generation vector). A source-table join is exact only if that mapping, a retained readable source snapshot, a retained readable index generation, compatible field mapping and applicable policy are all proven at query admission and remain valid throughout execution.

| Read policy (proposed) | Meaning |
| --- | --- |
| LATEST_INDEXED (recommended default) | Bind newest provably complete, retained source snapshot/index generation pair for the selected ref |
| SNAPSHOT_EXACT | Caller supplies exact table UUID/ref/source snapshot and matching eligible Quervant generation; absent a proven binding, reject |
| AT_LEAST | Wait within deadline until a snapshot **on the required ref's validated ancestry** is indexed and retained at/after a specified source commit watermark; snapshot IDs are not ordered integers |
| BEST_EFFORT (explicit opt in) | Independently chosen source/index versions may differ; report exact selected versions and incompleteness/staleness, **not** eligible for exact absence or full-source aggregates |

A multi-table/multi-index query binds a version vector. This is **not an atomic cross-table transaction**: each element is independently committed unless a separately approved multi-source transaction protocol proves otherwise. The query may only claim a consistent *declared set of versions*, not a globally simultaneous state. The [C4](../../distributed/03-QUERYING.md) EXACT vector is not by itself an Iceberg/Quervant transaction or a graph-consistent vector (DG-P2 remains separate).

**Reference motion:** branch head may advance or rewind, tags may refer to historic snapshots, and snapshots may expire. A cursor/retry must never silently substitute a newer snapshot/generation. Acquire and release retention leases/pins or enforce an equivalent provider-level guarantee. If source/version retention cannot be proven, fail admission or a running query explicitly. Source rows may be deleted or access revoked after index publication: policy must define immediate invalidation/redaction behavior and never use stale derived index fields to bypass current authorization.

## Query correctness and security

* **Joins:** explicit canonical typed key equality and SQL null semantics; duplicates remain distinct unless requested DISTINCT; do not assume one-to-one without validated uniqueness. Key names must be source-qualified, not raw document IDs.
* **Ranking:** final ORDER BY score is applied after every eligibility-changing join/filter, unless an independently proven safe ranked-join algorithm permits early stopping. Explicit tie breaker uses source/index identity and stable row key.
* **Aggregation:** exact COUNT/DISTINCT/GROUP BY and anti-join/NOT EXISTS require complete eligible source views and globally exact inputs. Partial scans, failed shards or stale previews cannot produce an exact negative.
* **Pushdown:** only with type/collation/timezone/missing/null/NaN, score, multivalue and predicate semantics proven equivalent. Treat statistics as estimates, never oracle truth.
* **Security:** enforce authorization per catalog/table/ref/row/column, per Quervant index and for every returned projection. DataFusion/Iceberg libraries do not automatically implement a source organization's SQL-engine RLS/masking policy. Use a trusted enforcement adapter or reject. EXPLAIN, metadata, query logs, candidate sets and timing must not leak unauthorized data.
* **Resource/failure:** one end-to-end admission budget for indexes, external reads, join build/probe, retries, spill/network, and client response; bound keys, scan tasks, memory, bytes, deadline and concurrency. Cancellation flows to Iceberg I/O and Quervant readers. If output already streamed then a backend fails, return explicit terminal incomplete/error, not an unmarked success.
* **Mutability:** latest live Iceberg snapshot cannot be joined to a stale Quervant generation and described as exact. SNAPSHOT_COMPLETE and STREAM_PREVIEW source modes are not interchangeable.

## API and plan boundary (future native path only)

Potential extension of the post-v0.2 logical binding relation vocabulary:

* ExternalTableScan(source_id, version_binding, typed_projection, validated_predicates)
* Existing IndexScan / SearchScan with source-row identity, provenance and score
* Join, SemiJoin, AntiJoin, Filter, Project, Aggregate, Sort, Limit, Exchange as separately approved XJ operators

This is a vocabulary sketch, **not** an addition to executable XJ-001. Preserve [XJ-001](../../distributed/10-CROSS-INDEX-FOUNDATION.md) v0.2 IndexScan/IndexSetScan/UnionAll boundary. Require explicit XJ-002 typed equality, XJ-003 exchanges, XJ-004 distributed joins and XJ-005 optimizer gates before native distributed mixed-source plans. Graph QGS-005 source variables and ontology QOS-004 inference modes remain separate; a cross-system join is not federated inference.

## Differential acceptance and performance evidence

1. For a pinned source/index pair, compare Quervant-first, Iceberg-first and independent-join strategies with an independent full source oracle, including duplicates, nulls, updated/deleted rows and rewritten Parquet.
2. Exhaustive small fixtures demonstrate that TOP K before join/filter is rejected unless safe and that post-join scoring/tie order is correct.
3. Predicate and projection pushdown match unpushed execution on nested JSON, decimal, timestamp, timezone, string normalization, missing/null and authorization cases.
4. Mutation/checkpoint lag, branch rewind, dropped/expired Iceberg snapshot, released Quervant PIT, retry/failover and cursor continuation must produce explicit errors rather than version substitution.
5. Anti-join, exact count/distinct and missing-shard/backend tests must reject partial/unproven source coverage.
6. Security tests exercise row and column masking, table/ref authorization, denial before EXPLAIN, source retention and revocation while a query runs.
7. Verify bounded Arrow batches, backpressure, cancellation, spilling, budgets, terminal failure and source/version provenance under a slow consumer.
8. Benchmark selective search+hydration, filter-only Iceberg, broad joins, cold RustFS reads and remote Iceberg scan bytes against DataFusion/Iceberg-only and Quervant-only baselines, reporting measured work rather than assuming speedups.

For executable follow-up plans use [TESTING.md](../../TESTING.md), [BENCHMARKING.md](../../BENCHMARKING.md) and the [detailed PR plan authoring guide](../../DETAILED_PR_PLAN_AUTHORING_GUIDE.md). This documentation PR does **not** claim these tests have run.

## External references

* [Apache DataFusion](https://datafusion.apache.org/) — SQL, Arrow-based relational execution.
* [Apache datafusion-iceberg](https://github.com/apache/datafusion-iceberg) — candidate Iceberg TableProvider.
* [Apache Iceberg REST protocol](https://iceberg.apache.org/docs/latest/rest-protocol/) — catalog authority, snapshot reference and supported scan planning.
