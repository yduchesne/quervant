# 01 — Roles, topology, sharding and placement

**Status:** approved architectural direction; no distributed runtime implied.

## Layering

`quervant-core` is a standalone, independent single-index/single-shard engine. `quervant-objectstore` provides authoritative remote committed state with immutable segments/manifests and qualified conditional publication. `quervant-distributed` composes these capabilities without introducing etcd, routing or cluster dependencies into core.

Logical roles (may be colocated as processes without conflating authority):

| Role | Owns | Must not own |
|---|---|---|
| Coordinator | Desired topology, placement, membership, epoch allocation, reconciliation, admin lifecycle | Query data path, shard-local indexing |
| Query Aggregator | Stateless read admission, plan, routing snapshot, direct Search Node fan-out, global merge | Writers, direct index mutation, Coordinator-proxied queries |
| Indexing Coordinator | Stateless write admission, stable routing, batching, retries, per-shard results | Segment construction, publication, core mutation semantics |
| Search Node | One or more shard-local core readers and fenced writers; observed readiness | Global routing authority |
| Publication Authority | Validated, serialized shard ownership/publication transitions and recovery barriers | Query hot path or mutation indexing |
| ObjectStore | Installed ownership state, committed generation and immutable objects | Node placement |
| etcd | Durable desired state, election/leases, allocation records, retention coordination | Committed shard data |

Publication Authority is a **logical validation boundary**, initially deployable with the Coordinator control plane, not an independently required new network hop for every mutation. It must be leader-fenced, recoverable, and the only authorized path for pointer transitions. Search Nodes may upload immutable data but cannot bypass validated pointer publication.

## Logical shard identity and routing

- Stable identity: `(cluster_id, index_id, shard_id)`; fixed initial shard count per index.
- Canonical routing key defaults to stable document key; deterministic versioned hash and modulo/range mapping must be specified and tested. Document updates/deletes preserve their original shard; arbitrary routing-key changes are not ordinary mutations.
- Routing topology has an independent version; adding/removing Search Nodes changes **placement**, never document-to-shard mapping.
- Automatic resharding and cross-shard document moves are deferred. Future explicit migration requires topology versions, mutation catch-up, cutover, cursor policy and recovery.

## Authority and fencing

Separate desired assignment (etcd), installed writer authority (ObjectStore), and observed readiness (node report). One authoritative writer incarnation per shard may publish at a time, enforced by the publication pointer and [FP-002](06-SAFETY-PROTOCOLS.md#fp-002--writer-publication-fencing). etcd lease/election alone cannot fence ObjectStore writes. Ownership transitions require monotonically increasing epochs within a recovery generation. A writer-hosted reader is allowed but not required.

## Reader lifecycle

`UNASSIGNED → ASSIGNED → BOOTSTRAPPING → READY → DRAINING → RELEASED`.

- Assignment is revisioned and includes node incarnation.
- BOOTSTRAPPING obtains authoritative manifest and immutable objects from ObjectStore; verify digest and complete materialization.
- READY is scoped to exact `(generation, manifest_digest)`; stale reports from prior incarnation/revision cannot establish readiness.
- New replica activates before old reader drains whenever feasible; existing in-flight snapshot pins must finish or expire safely.
- No peer-to-peer mutable segment migration; local cache is disposable.
- Default desired reader count: two placements when capacity permits, subject to explicit hard anti-affinity and degraded-mode policy.

## Placement scheduler

Separate eligibility constraints from scoring and reconciliation. Hard constraints include node capability, resource capacity, supported index format, failure domain and lifecycle. Deterministic tie-breaking, movement hysteresis, bounded concurrent bootstrap and writer handoff prevent churn.

Priority: P0 recover missing safe writer; P1 restore at least one queryable replica; P2 restore target replicas and failure-domain diversity; P3 hard resource pressure; P4 balance; P5 cache locality. Only an active, etcd-fenced Coordinator leader may commit desired placement.

Writer transfer: allocate grant, install successor through Publication Authority, reconcile authoritative generation, then admit writes. Old writer may still have been executing before successor installation; its publications are rejected **after** successor authority is installed. No claim of atomic lease-expiry revocation.

## Acceptance

Stable document routing under node churn; node incarnation/revision checks; failure-domain placement; reader activate-before-drain; stale writer rejection; deterministic scheduling and no unnecessary movement after leader failover. Real provider CAS qualification and fault-injection tests are mandatory before writer failover is declared safe.
