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

These files are the **normative distributed design register**. [../ARCHITECTURE.md](../ARCHITECTURE.md) is the cross-release overview; [../ROADMAP.md](../ROADMAP.md) owns release boundaries. Existing core storage, query and mutation contracts remain authoritative for shard-local behavior. Where a prior distributed overview differs, this register supersedes it. Do not modify core behavior to satisfy distributed orchestration without an explicit compatibility decision.

## Decision register

| ID | Decision | Status |
|---|---|---|
| A | Stable logical shards, etcd desired placement, independent readers, fenced single writer | Approved |
| B | Stateless Indexing Coordinator, shard-local mutation/dedup, per-shard outcomes | Approved |
| C1–C5 | Stateless query fan-out, global BM25, exact analytics, snapshot vectors, global budgets | Approved |
| C6 | Pushdown and physical-plan foundation; join/exchange extension points only | Approved |
| C7 | Distributed result streaming composed from core streaming; bounded flow/backpressure and terminal correctness | Proposed documentation extension |
| D1–D2 | Coordinator HA and Search Node recovery | Approved |
| D3 | ObjectStore authority, retention and conservative GC | Approved direction; proof gates |
| D4–D5 | Scaling, metadata, lifecycle, upgrade compatibility | Approved |
| FP-002 | Publication authority and recovery-generation fencing | Approved design; qualification required |
| GC-002 | Retention barriers, publication intents, deletion safety | Approved design; formal proof required |
| DR-002 | Recovery barriers, metadata reconciliation, quarantine | Approved design; formal proof required |

**Approved does not mean implemented, formally proven, or benchmark-qualified.** The safety specifications distinguish architectural requirements from unresolved provider and protocol proof obligations.

## v0.2 minimum and exclusions

The v0.2 design target is a complete, correct distributed lexical/typed engine: shard routing, one fenced writer per shard, stateless ingestion and query planes, exact distributed query semantics and bounded finite-result streaming for supported operators, HA placement, recovery, and necessary retention safeguards. Precise release acceptance and PR decomposition remain subject to [ROADMAP.md](../ROADMAP.md) and later implementation planning.

Excluded from v0.2: automatic resharding, general SQL, distributed relational joins/shuffle, vector/ANN/hybrid, a durable ingestion journal, dedicated writer-only node processes, and sophisticated predictive autoscaling. Ontology/graph joins are future consumers, not v0.2 execution operators.

## Implementation STOP rules

- Never treat etcd lease expiry alone as ObjectStore writer fencing.
- Never create two independently authoritative `CURRENT`/distributed publication pointers.
- Never acknowledge `DURABLE` before authoritative publication confirmation.
- Never substitute a different generation for a pinned distributed snapshot.
- Never silently approximate exact aggregation or global BM25.
- Never treat transport disconnect as successful stream completion or confuse a live cursor with a resumable token.
- Never enable destructive remote GC before its deletion-barrier proof and provider qualification.
- Never permit unvalidated direct Search Node writes to the publication pointer.
- Never claim v0.2 implementation complete based solely on these documents.

## Test policy

Apply [../TESTING.md](../TESTING.md), including reproducible coverage gates, deterministic fault injection and real etcd/ObjectStore integration. Tests must distinguish implemented, executed and passed. Use qualified RustFS/S3-compatible CAS behavior; mocks alone cannot prove storage atomicity.
