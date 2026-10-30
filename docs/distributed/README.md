# Distributed architecture — v0.2 design register

**Status:** approved architectural direction; implementation and protocol qualification pending. These documents specify the intended distributed system, not shipped functionality. The standalone `quervant-core` remains usable without etcd, cluster services, or distributed dependencies.

## Documents and authority

1. [01 — Roles, topology, sharding and placement](01-TOPOLOGY-PLACEMENT.md): ownership boundaries, routing, scheduling, replica lifecycle.
2. [02 — Distributed ingestion](02-INGESTION.md): routing, idempotency, mutation ordering, writer recovery and acknowledgment semantics.
3. [03 — Distributed querying](03-QUERYING.md): planning, global BM25, exact analytics, consistency, snapshots, retries, budgets, join extension points.
4. [04 — Availability, scaling and operations](04-AVAILABILITY-OPERATIONS.md): Coordinator HA, node recovery, rebalancing, lifecycle, metadata and upgrades.
5. [05 — Storage, publication and GC](05-STORAGE-GC.md): immutable state, publication authority, snapshot retention and reclamation.
6. [06 — Safety protocols and proof obligations](06-SAFETY-PROTOCOLS.md): FP-002, GC-002, DR-002, cross-store races, failure-injection gates.
7. [07 — Distributed result streaming (C7)](07-STREAMING.md): core cursor reuse, bounded multi-shard flow, ordering, cancellation, terminal errors and resume policy.
8. [08 — B2 distributed batches and query-target mutations](08-BATCH-MUTATIONS.md): reuse core atomic batches, cross-shard partial outcomes, query selection, restricted upsert and replay gates.
9. [09 — DS-001 service interfaces and presentation protocols](09-SERVICE-PROTOCOLS.md): common application services; Tonic/gRPC internal RPC; Axum/HTTP JSON, NDJSON and native gRPC client streaming.
10. [10 — XJ-001 cross-index query foundation](10-CROSS-INDEX-FOUNDATION.md): stable IndexId, schema/index-set catalog, typed union query IR, pinned multi-index vectors and exact multi-index semantics.

**Implementation roadmap:** [D01–D15 — distributed v0.2 work packages](ROADMAP.md). **Cross-subsystem coordination:** [Distributed / Graph / Ontology integration roadmap](../INTEGRATION_ROADMAP.md), which defines shared contract and safety gates for later graph/ontology consumers. Work-package IDs are planning labels; this documentation does not claim implementation.

These files are the **normative distributed design register**. [../ARCHITECTURE.md](../ARCHITECTURE.md) is the cross-release overview; [../ROADMAP.md](../ROADMAP.md) owns release boundaries. Existing core storage, query and mutation contracts remain authoritative for shard-local behavior. Where a prior distributed overview differs, this register supersedes it. Do not modify core behavior to satisfy distributed orchestration without an explicit compatibility decision.

## Decision register

| ID | Decision | Status |
|---|---|---|
| A | Stable logical shards, etcd desired placement, independent readers, fenced single writer | Approved |
| B | Stateless Indexing Coordinator, shard-local mutation/dedup, per-shard outcomes | Approved |
| B2 | Core atomic batch reuse and global query-target mutation safety; explicit-key v0.2 baseline | Proposed architecture extension; query-target release scope gated |
| C1–C5 | Stateless query fan-out, global BM25, exact analytics, snapshot vectors, global budgets | Approved |
| C6 | Pushdown and physical-plan foundation; join/exchange extension points only | Approved |
| XJ-001 | Cross-index catalog/identity, typed multi-index UNION, schema/snapshot/query contracts; no joins | Proposed v0.2 scope extension |
| C7 | Distributed result streaming composed from core streaming; bounded flow/backpressure and terminal correctness | Proposed documentation extension |
| DS-001 | Common service core, Tonic/gRPC, Axum HTTP JSON/NDJSON, native gRPC streaming | Proposed architecture decision; mandatory v0.2 delivery target on approval |
| D1–D2 | Coordinator HA and Search Node recovery | Approved |
| D3 | ObjectStore authority, retention and conservative GC | Approved direction; proof gates |
| D4–D5 | Scaling, metadata, lifecycle, upgrade compatibility | Approved |
| FP-002 | Publication authority and recovery-generation fencing | Approved design; qualification required |
| GC-002 | Retention barriers, publication intents, deletion safety | Approved design; formal proof required |
| DR-002 | Recovery barriers, metadata reconciliation, quarantine | Approved design; formal proof required |

**Approved does not mean implemented, formally proven, or benchmark-qualified.** The safety specifications distinguish architectural requirements from unresolved provider and protocol proof obligations.

## v0.2 minimum and exclusions

The v0.2 design target is a complete, correct distributed lexical/typed engine **with a proposed cross-index search foundation**: shard routing, one fenced writer per shard, stateless ingestion and query planes, index catalog/identity, typed multi-index UNION and exact supported cross-index sorting/analytics, bounded finite-result streaming, HA placement, recovery, and necessary retention safeguards. Multi-index snapshot vectors do not imply global cross-index transactions. Precise release acceptance and PR decomposition remain subject to [ROADMAP.md](../ROADMAP.md) and later implementation planning.

Excluded from v0.2: automatic resharding, general SQL, **distributed relational joins/shuffle** (despite a reserved IR boundary), cross-index graph references, graph/ontology execution and inference, vector/ANN/hybrid, a durable ingestion journal, dedicated writer-only node processes, and sophisticated predictive autoscaling. Ontology/graph joins are future consumers, not v0.2 execution operators.

## Implementation STOP rules

- Never treat etcd lease expiry alone as ObjectStore writer fencing.
- Never create two independently authoritative `CURRENT`/distributed publication pointers.
- Never acknowledge `DURABLE` before authoritative publication confirmation.
- Never imply cross-shard atomicity from a core `MutationBatch`; never independently execute globally constrained query upserts on each shard.
- Never substitute a different generation for a pinned distributed snapshot.
- Never silently approximate exact aggregation or global BM25.
- Never treat transport disconnect as successful stream completion or confuse a live cursor with a resumable token.
- Never put query execution or independent authorization policies inside an HTTP/gRPC adapter.
- Never enable destructive remote GC before its deletion-barrier proof and provider qualification.
- Never permit unvalidated direct Search Node writes to the publication pointer.
- Never claim v0.2 implementation complete based solely on these documents.

## Test policy

Apply [../TESTING.md](../TESTING.md), including reproducible coverage gates, deterministic fault injection and real etcd/ObjectStore integration. Tests must distinguish implemented, executed and passed. Use qualified RustFS/S3-compatible CAS behavior; mocks alone cannot prove storage atomicity.


## Future native graph integration — outside v0.2 scope

The conceptually approved [QGS-006 distributed graph design](../graph/QGS-006.md) extends the roles, ownership and C6/C7 query/streaming contracts in this register **after v0.2**. It does not enable general distributed joins in v0.2 or create another publication authority. Cross-shard vertex/edge mutation (DG-P1) and graph-consistent generation-vector qualification (DG-P2) are mandatory *unresolved* protocol and provider-qualification gates. Per-shard `EXACT(vector)` is not automatically an atomic global graph snapshot. Consult [graph roadmap/review](../graph/ROADMAP.md).
