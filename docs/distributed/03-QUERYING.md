# 03 — Distributed query architecture

**Status:** C1–C6 approved architecture. This is the normative distributed querying specification; no query-plane runtime is implied.

## Roles and execution flow

The stateless Query Aggregator receives a typed query, obtains a versioned routing snapshot, compiles logical and distributed physical plans, establishes a snapshot/consistency contract, admits global resources, prunes eligible shards, selects READY compatible replicas, dispatches directly to Search Nodes, and merges exactly one accepted contribution per logical shard. Coordinator is never a query proxy. Search Nodes execute shard-local lexical, typed, JSON, temporal and geospatial predicates through `quervant-core`, not by returning raw documents for central filtering.

Routing snapshot includes index/routing version, shard placements, node incarnations, capability versions and generation-specific readiness. Replicas of the same logical shard must not be counted twice. Strict completeness is default: missing required shards cause an explicit error. Optional partial results must report omitted shards and partiality; never silently present them as complete.

## Logical and physical planning (C6)

Keep logical semantics separate from physical execution:
- **Logical plan:** Boolean/lexical/typed predicates, projection, sorting, aggregations, optional future join operators.
- **Distributed physical plan:** shard pruning, shard-local pushdown, multi-stage global statistics, partial aggregates, ordered merge, stage exchanges reserved for future.
- **Shard execution plan:** versioned, capability-negotiated operations supported by core.

v0.2 includes predicate/projection pushdown and partial aggregation pushdown; routing-based shard pruning where provably sound; no independent post-hoc intersection of mixed lexical and typed results. A mixed predicate must be evaluated with core's unified membership/scoring semantics. Reject unsupported operators before execution or select a compatible replica. No silent semantic fallback.

Physical-plan version and operator capabilities are negotiated for rolling upgrades. Reserve `Exchange` and `Join` extension points, **do not implement an unused join/shuffle engine** in v0.2. Later candidate joins: colocated equijoins on matching partition keys, broadcast equijoins for bounded small sides, eventually repartitioned hash join with shuffle/spill; intra-index, cross-index, and ontology graph traversals are distinct. General SQL syntax, distributed joins, shuffle and cross-index transactional snapshots are not v0.2 commitments.

## Global BM25 (C2)

Default `GLOBAL_STATS` uses a multi-phase protocol:
1. Bind a consistent per-shard generation vector and physical-plan fingerprint.
2. Perform bounded, globally coordinated multi-term expansion (prefix/glob/regex/fuzzy) so shards do not independently select incompatible term universes.
3. Collect exact live-document counts, scoring-field length totals and term document frequencies from pinned shard snapshots; apply one globally agreed statistic set.
4. Dispatch scoring using those stats and the existing core BM25 formula; merge globally comparable top-K with deterministic total tie-breaking.

`LOCAL_STATS` is an explicit approximate/performance mode, never the silent default. Respect expansion, stats, fan-out, CPU, memory and deadline budgets across all phases. Required parity: same supported query, corpus, analyzer and snapshot should match single-index semantics within specified floating-point/tie rules. No claim that global BM25 can be computed by averaging shard-local scores.

## Exact analytics and ordered scans (C3)

Use map/combine/finalize with algebraically valid merge states:
- count/sum/min/max and average as `(sum,count)` with defined numeric overflow, null and precision semantics;
- exact `GROUP BY`: merge complete partial groups before global top-K; do not truncate each shard to local top-K;
- exact `DISTINCT`: canonical identity and complete union within explicit cardinality/memory budgets; fail rather than silently approximate;
- time buckets: identical UTC normalization, bucket origin, half-open boundaries and missing-value semantics across shards;
- sorted scans: globally ordered k-way merge with stable total tie-breaker and snapshot-bound cursor positions.

Resource caps may reject exact queries. Approximate algorithms require separately named modes and documented errors; they are not substitutes for exact operators.

## Consistency and snapshot vectors (C4)

Supported read policies:
- `AVAILABLE`: choose eligible available committed generations; no cross-shard point-in-time claim.
- `AT_LEAST(vector)`: every shard must serve a generation satisfying the requested minimum; otherwise wait within deadline or fail.
- `EXACT(vector)`: serve exactly the requested `(index_id, shard_id, generation, manifest_digest)` for every shard.

A snapshot descriptor includes routing topology version and exact generation/manifest digest per shard. This is a **vector of independently committed shard snapshots**, not an atomic global transaction. For multi-phase queries, every phase uses the same vector. Retry only against a replica capable of that exact snapshot; otherwise restart the whole query under a new snapshot or fail explicitly. Never mix generations silently.

Cluster-level retention leases protect snapshot dependencies from remote GC, independent of local reader pins. Cursor is opaque, integrity-protected, expires, and binds query fingerprint, routing version, snapshot vector, sort/tie state, per-shard positions and policy. Snapshot loss yields a typed error, not an implicit replacement with latest.

## Replica selection, retry and completeness (C1/C4)

Prefer READY replicas with verified required generation and compatible capabilities. Direct RPC, bounded hedging/retries, per-shard attempt IDs, cancellation and deadlines. Deduplicate logical shard contributions across retries and replica races. An unknown attempt outcome retains resource reservation until confirmed terminal or bounded execution lifetime. Strict result completeness and partial-result opt-in are separate API semantics.

## Global resource governance (C5)

One Aggregator-owned query budget; non-overlapping per-attempt work reservations enforced by the core mixed work meter. All phases (expansion, stats, scoring, analytics, retries) consume the same allowance. Unused reservations return only on confirmed termination; retries never reset work. Nodes cannot self-allocate global budget. Separate caps for CPU, memory, network, intermediate cardinality, scanned documents, deadline and cancellation. Admission classes: interactive, analytical, background, with fairness and explicit overload categories.

Execution identity: `(query_id, stage_id, shard_id, attempt_id)`. Late/superseded responses cannot alter finalized results. Trace stage and attempt costs without double counting.

## Query acceptance matrix

1. Single-shard vs multi-shard global BM25 parity, including multi-term expansions and deterministic ties.
2. `LOCAL_STATS` labeled approximate; global stats default and snapshot-bound.
3. Exact count/sum/min/max/avg, high-cardinality GROUP BY and DISTINCT without local top-K truncation.
4. Temporal bucket boundaries, typed/geospatial/JSON and mixed lexical/typed predicate parity.
5. Shard pruning preserves completeness; projection and aggregation pushdown preserve semantics.
6. Strict missing-shard error versus explicitly partial result.
7. Replica failure and retry at EXACT vector; no duplicate shard contributions.
8. Cursor expiration, tamper rejection, retained snapshot reopening, GC races.
9. Work reservation conservation across retries and multi-stage execution.
10. Rolling upgrade rejects unsupported plan/operator versions.
11. Future join/exchange placeholders cannot accidentally execute as supported v0.2 operators.
