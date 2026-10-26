# Quervant Distributed v0.2 — dependency-oriented implementation roadmap

**Status:** proposed documentation/implementation plan, **no code delivered and no implementation milestone verified**. D01–D15 are **planning work-package IDs, not GitHub PR numbers**. Scope is the distributed lexical/typed engine **plus multi-index query foundation**, **not distributed joins/shuffle**, graph traversal, or ontology inference. This roadmap is subordinate to [distributed architecture register](README.md) and cross-release [ROADMAP.md](../ROADMAP.md).

## Baseline and design authorities

- Read current `main` before every implementation plan; do not infer delivered features from architecture documents or stale acceptance reports. As of roadmap authoring, `quervant-distributed` remains only a foundation crate.
- [01 placement](01-TOPOLOGY-PLACEMENT.md), [02 ingestion](02-INGESTION.md), [03 query C1–C6](03-QUERYING.md), [04 operations](04-AVAILABILITY-OPERATIONS.md), [05 storage](05-STORAGE-GC.md), [06 safety](06-SAFETY-PROTOCOLS.md), [07 C7 streaming](07-STREAMING.md), [08 B2 mutation](08-BATCH-MUTATIONS.md), [09 DS-001 protocols](09-SERVICE-PROTOCOLS.md).
- [XJ-001 cross-index foundation](10-CROSS-INDEX-FOUNDATION.md) is the v0.2 multi-index design proposal. [QGS-005](../graph/QGS-005.md) sets higher-level relational/graph/ontology query semantics; [QGS-006](../graph/QGS-006.md) governs later graph distribution. Neither authorizes a join engine in v0.2.
- Existing standalone [core streaming](../STREAMING_SEARCH.md), mutation contracts and core query operators remain authoritative locally.
- Use [detailed PR plan authoring guide](../DETAILED_PR_PLAN_AUTHORING_GUIDE.md) for every coding-agent implementation PR. Acceptance must be executed, independently reproduced and recorded; documentation status does not mean delivered.

## Release boundary

**Required v0.2 outcome:** manage multiple independently routed, committed indexes on one distributed cluster; ingest via fenced per-shard writers; query any one index and a bounded explicit/authorized set of indexes; correctly combine compatible index results via `UNION ALL`, globally sorted/cursor-driven scans, exact supported analytics, bounded streaming, transparent index-qualified identities, and explicit snapshot/partiality semantics. Correct multi-index BM25 relevance is not the same as adding incomparable per-index scores: globally comparable scoring requires explicit compatible corpus/analyzer contract, otherwise use separate per-index ranking or reject score-mixed global ranking.

**Required v0.2 foundation for later joins:** index/schema catalog, typed source and binding metadata, versioned logical/physical operator capabilities for scan/filter/project/union/order/aggregate, index-set snapshots and resource budgets, source-provenance-preserving output. `Join`, `Exchange`, `GraphExpand`, `OntologyScan` can be reserved as *unsupported* physical/logical capabilities without executable stubs.

**Not v0.2:** indexed/colocated/broadcast/repartitioned distributed relational joins, exchange shuffle, SQL/Cypher grammar, cross-index transactional point-in-time, arbitrary federation to external clusters, cross-index native graph references, distributed traversal/algorithms, ontology federation or global inference, vector/ANN/hybrid, automatic resharding, continuous subscriptions/CDC/live-tail. B2 globally query-targeted mutations remain gated behind explicit release and safety approvals; explicit-key/`Keys` atomic shard batches are required.

## Dependencies and scheduling

```text
D01 Service/RPC
 └─ D02 Catalog, identities, index topology ─┬─ D03 HA/placement ─ D04 publication/fencing ─ D05 nodes ─ D06 ingestion
                                            │                                           └─ D07 distributed queries
                                            └───────────────────────────────────────────────┬─ D08 cross-index contracts
                                                                                           ├─ D09 BM25
                                                                                           └─ D10 analytics
D08 + D09 + D10 + D07 ─ D11 multi-index UNION ─ D12 C7/DS-001 streaming
D03–D07 ─ D13 recovery/operations; D04–D07 ─ D14 retention/GC/DR
D01–D14 ─ D15 end-to-end release qualification
```

The graph denotes **functional prerequisites**, not a mandate for a purely sequential coding schedule. D04 publication/safety, D13 recovery and D14 retention protection need design/qualification work **from the earliest cluster stages**; never defer safety design to the last two PRs. D08 and D09 can develop concurrently after D07 contracts stabilize.

## Implementation work packages and acceptance gates

| ID | Work package | Required deliverables / acceptance evidence | Depends on |
|---|---|---|---|
| **D01** | Service contracts and RPC foundation | Protocol-neutral service interfaces and typed errors; internal Tonic/Prost gRPC with version/capability negotiation; transport security and roles; bound messages, deadlines; real two-process RPC test. `quervant-core` stays standalone. | None |
| **D02** | Distributed index catalog and topology | Stable cluster/index IDs distinct from names; schema/version/catalog updates, shard count/hash/routing version, creation/tombstone lifecycle and index authority in etcd; metadata consistency/restart tests. Reserve index-set resolution interface. | D01 |
| **D03** | Coordinator HA and placement | Leadership-term fencing, desired vs observed placement, node incarnation/readiness, anti-affinity/resource budgets, reconcile after election and partition; actual etcd failover tests. | D02 |
| **D04** | Publication Authority and fenced writer grants | FP-002 sole authoritative ObjectStore CAS pointer, ownership epoch/incarnation/recovery generation, exclusive pointer credentials, ambiguous-CAS reconciliation, stale-writer rejection; real RustFS qualification **STOP if provider semantics unproven**. | D02–03 |
| **D05** | Search Node shard lifecycle | Recovery from authoritative manifest, independently activated readers, single writer/shard, cold-cache bootstrap, readiness by generation, safe activation/drain and node incarnation checks. | D03–04 |
| **D06** | Distributed ingestion | Indexing Coordinator routes deterministic explicit-key/`Keys` atomic shard batches; stable whole-batch replay and B2 scope; ack `ACCEPTED`/`DURABLE`/`SEARCHABLE`; typed per-shard partial outcomes; failover/replay tests. | D04–05 |
| **D07** | Distributed query foundation | Versioned plan dispatch, shard pruning, READY replica selection, pinned generation vectors, strict vs opt-in partial completeness, global C5 work reservations and snapshot-bound retries. | D05 |
| **D08** | Cross-index identity, catalog and logical foundation | Implement scoped index-set selection, authz, stable `(index_id,key)` identity, schema/type compatibility, typed source/binding metadata and versioned scan/union logical IR from XJ-001; `Join`/`Exchange` execution remains unsupported. | D02, D07 |
| **D09** | Distributed lexical relevance | C2 global term expansion/statistics/BM25 parity across shards of *one index* and deterministic ranking; explicit multi-index scoring policy, reject incomparable globally mixed ranks. | D07 |
| **D10** | Distributed exact analytics and ordering | Exact supported count/sum/min/max/avg, GROUP BY/DISTINCT under budgets, time buckets, stable total global order and snapshot-bound pagination. | D07–09 where scoring applies |
| **D11** | Multi-index query execution | Execute bounded index sets via `UNION ALL` with exact completeness and index-qualified ties, schema-aware filter/projection, supported exact global analytics, per-index or explicitly compatible scoring, extended snapshot vectors and retained cursors. Test one-vs-many indexes, index deletion, partiality and schema conflicts. | D08–10 |
| **D12** | C7 streaming and external protocols | Demand-driven bounded shard/Aggregator streams; public native gRPC server streaming and Axum structured NDJSON via common `SearchService`; explicit terminal success/error, cancellation, slow-client backpressure, CLI-friendly records. | D07–11 |
| **D13** | Operations and recovery | Coordinator/node failover, replica replacement, placement transitions, index create/delete tombstones, administrative APIs, versioned rolling upgrade, documented recovery/backup procedures and failure injection. | D03–07 |
| **D14** | Retention/GC and disaster recovery | GC-002 publication-intent / claim barrier, snapshot/index-set pin ownership, DR-002 recovery-generation barrier and restored metadata reconciliation. **Keep destructive GC disabled until safety proof & real-provider qualification**. | D04–07, D11 for multi-index pins |
| **D15** | Qualification / release signoff | Multi-node real etcd + RustFS/S3 path; fault-injection matrix for pointer CAS, elections, shard crash, snapshot expiry, partial index failure, cursor/resume, backpressure, authz; parity oracle and repeatable benchmarks; >=85% Rust line coverage per testing policy. Record all PASS/BLOCKED with exact SHA and commands. | All |

### Per-work-package completion policy

Each PR plan MUST include: baseline SHA and evidence of implemented core APIs, precise changed files/modules, input/output contracts and wire/version constraints, migration implications, a small independently runnable acceptance matrix, deterministic and real-service adversarial tests, rollback/STOP instructions, and reproducible validation commands. Do not ask the coding agent to invent architecture or choose protocols. A work package can be split into smaller PRs without changing its acceptance boundary; statuses remain PLANNED until evidence exists.

## Cross-index-specific release tests

1. Query a single index and 2+ independent indexes; `UNION ALL` preserves source index and identical matching rows within the selected snapshots, even when document keys collide.
2. Index-set selector expansion bounded, authorization checked per index, catalog/routing changes after planning detected; no silent addition/removal of sources.
3. Compatible typed predicates, missing/null and timezone/sort semantics match reference oracle. Incompatible type/analyzer/field semantics produce typed reject or explicitly selected safe mapping; no coercion by accident.
4. Globally sorted results use stable total key ending with index ID + document key; pagination/cursor restarts under pinned generations yield no duplicate/missing results.
5. Exact supported aggregate and DISTINCT over UNION inputs match independently computed complete oracle; `UNION ALL` bag semantics retained unless DISTINCT requested.
6. Index-set snapshot extends C4 per-shard vector with index identity, schema/operator/routing fingerprints; not an atomic global transaction. Losing a pinned generation fails typed rather than switching.
7. Missing index/shard, mid-stream failure and optional partial mode surface omitted sources and explicit terminal status in HTTP NDJSON and gRPC. No successful EOF on disconnect.
8. Two indexes with different BM25 analyzer/field schemas **cannot** be silently scored as one comparable corpus. Same-index GLOBAL_STATS parity retained.
9. Per-index authorization remains enforced through index selection, projection, result, cursor reopening and explain diagnostics.
10. Unsupported join, exchange, graph and ontology IR/plans must produce `UnsupportedCapability` **before** execution, not pretend to run or silently change semantics.

## Safety critical path

- **FP-002:** authority fencing and qualified conditional CAS is a hard prerequisite for durable distributed writes.
- **GC-002:** require safe pin/publication/deletion barrier. Disable destructive remote GC on uncertainty.
- **DR-002:** etcd rollback cannot resurrect an old owner or advance stale epochs over committed state.
- **C4:** pinned vectors over several indexes are repeatable selections, **not** a global atomic transaction.
- **C5:** globally conserved budgets span every participating index/shard, retry, merge and stream; a retry never resets work.
- **C7/DS-001:** bounded frames, cancellation and explicit complete/partial/error signaling for both transports.
- **B2:** shard-local batch atomicity must never become a false cross-shard all-or-nothing claim.

## Effort and checkpoint targets (estimates, not committed dates)

Assuming a full-time operator with coding agents and stable v0.1 core: **baseline distributed effort 18–25 working days**, incremental cross-index foundation/multi-index union **3–6 working days**, aggregate **21–31 working days**; plan operationally for **25–30 days plus 5–8 days safety/integration contingency**. These ranges are not a sum of all individually overlapping workstreams and must be recalibrated using measured PR throughput and protocol failures.

Suggested checkpoints, contingent on passing preceding gates:
- Initial cluster and qualified RPC/authority integration: D01–D05.
- Fenced ingestion and single-index distributed querying: D06–D07.
- Cross-index contract and global query features: D08–D11.
- Client streaming, recovery and retention qualification: D12–D14.
- Release evidence: D15.

## After v0.2 — distributed relational joins and graph/ontology

Next planning sequence: **XJ-001** is the v0.2 design foundation, **XJ-002** typed binding relations and local indexed/hash/semi/anti joins, **XJ-003** distributed Gather/Broadcast/Repartition exchanges and exactly-once logical attempt accounting, **XJ-004** colocated/broadcast/repartitioned joins, **XJ-005** optimizer and EXPLAIN, **XJ-006** consistency/budgets/streaming qualification. These are placeholders requiring separate explicit design and release approval, **not v0.2 commitments**.

Native graph QGS-001–008 and ontology QOS-001–004 remain distinct standalone prerequisites for specialized relation sources. QGS-006 DG-P1/DG-P2 graph lifecycle/snapshot safety must be qualified before unrestricted distributed graph operations. QOS-001 keeps inference **index-local** initially: joining independently inferred ontology results does not authorize federated least-fixed-point inference. Cross-index native graph edges and federated ontology rule publication need their own protocols.

## Implementation status

| Work package | Status | Evidence |
|---|---|---|
| D01 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D02 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D03 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D04 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D05 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D06 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D07 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D08 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D09 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D10 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D11 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D12 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D13 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D14 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |
| D15 | PLANNED | No runtime implementation or acceptance evidence claimed by this documentation PR |

Update this ledger only after source verification, CI/test evidence and explicit completion review.
