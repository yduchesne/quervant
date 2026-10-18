# 04 — HA, recovery, scaling and cluster lifecycle

**Status:** D1, D2, D4 and D5 approved architectural direction.

## Coordinator HA and etcd

Multiple Coordinators; exactly one active leader elected via etcd lease, with monotonic leadership term and **transactionally fenced** control-plane writes. A process-local leader flag is not authority. etcd stores durable index/routing definitions, desired placement, writer allocation records, operation intents, cluster identity and revisioned metadata; ephemeral membership/readiness observations are lease- and node-incarnation-bound. etcd does **not** store committed shard generations.

On failover: read a consistent etcd snapshot; recover desired topology and incomplete operations; reconcile ObjectStore installed ownership and generation; re-observe node readiness; resume idempotent transitions; defer elective balancing. Watch compaction/revision gaps trigger full reload; stale watch events cannot roll state backward.

etcd quorum loss: no new placement or ownership grants. Existing verified readers may serve bounded cached routing/snapshots where retention permits. Writers lose admission/publication when they cannot maintain required lease authority. Lease expiry means *suspect*, not proof that an old process stopped; ObjectStore publication fencing remains necessary.

## Search Node lifecycle and failure

Node identity is stable `node_id` plus fresh `incarnation_id` on each restart. Distinguish membership lease, generation-specific readiness and data-plane RPC health. States `REGISTERING → ACTIVE ↔ SUSPECT → LOST` and `ACTIVE → DRAINING → REMOVED`; LOST does not prove process termination.

Reader failure: route to surviving READY replica for required snapshot, otherwise mark shard read-unavailable; replacement bootstraps verified committed state from ObjectStore, never from another node's mutable cache. Writer failure: allocate/install new fenced ownership, recover authoritative committed generation and operation dedup state, then admit writes. `ACCEPTED` may be lost; `DURABLE` cannot. Degraded availability is operation- and consistency-specific, not a single Boolean.

Failure domains are administrator-labeled region/zone/rack/host constraints. Recovery prioritizes first queryable replica and safe writer, then target replica count/diversity. Bootstrap has per-node and cluster concurrency, memory, disk and ObjectStore bandwidth caps. Graceful drain activates readers before release and transfers writer through fenced cutover. A cold cache never proves READY without verification.

## Scaling and rebalancing

Three dimensions: add readers for query concurrency, distribute one writer per logical shard for aggregate ingestion throughput, grow ObjectStore for durable storage. Adding nodes **does not** change shard count or document routing; write parallelism is bounded by the number of independently active logical shard writers. Read-hot, write-hot and storage-hot shards need distinct remedies. Reader replica scaling is policy-bounded with minimum/maximum and cooldowns; v0.2 need not implement predictive autoscaling. Writer moves are conservative, hysteresis-controlled and fenced.

Eligibility/hard resource constraints precede scoring. Deterministic tie-breaks, failure-domain anti-affinity, movement budgets, bootstrap concurrency and recovery priority prevent storms and churn. Explicit capacity admission for index creation and degraded states when constraints cannot be met. Online shard split/merge/repartitioning deferred, with versioned routing reserved.

## Index and cluster lifecycle

Version **metadata format**, **routing topology** and **placement revision** independently. Index lifecycle: `CREATING → PROVISIONING → ACTIVE → DELETING → DELETED`, with explicit FAILED/recoverable operation state. ACTIVE is lifecycle, not perpetual full availability.

Creation: validate schema/shard count/placement; allocate immutable index ID; persist topology; initialize authoritative shard publication state; provision writer/readers; transition ACTIVE after required readiness. Every step idempotent across Coordinator failover.

Deletion: mark DELETING, reject new admission, fence writers, drain queries and pins under explicit policy, safely GC objects, preserve deletion tombstone and never reuse index ID. Deletion tombstones must survive metadata restoration or ambiguous restored state must be quarantined.

Cluster bootstrap is explicit and cluster-ID-bound, validates etcd metadata and ObjectStore conditional-write capabilities. Never auto-create a fresh cluster because etcd data disappeared. Durable metadata backups required; restore follows [DR-002](06-SAFETY-PROTOCOLS.md#dr-002--catastrophic-metadata-restoration), never blindly trusts stale allocation counters or readiness.

## Upgrade compatibility and APIs

Nodes advertise protocol versions, core index formats, plan/operator capabilities and storage features. Coordinator uses them for placement; Aggregator for plan dispatch. Reject incompatible operators or formats; do not silently upgrade persisted index formats. Define bounded mixed-version windows.

Minimal admin APIs: create/get/list/delete index, update placement policy, shard status, node drain, cluster status, long-running operation status. Long-running operations have stable IDs and survive leader failover.

## Required fault-injection gates

Coordinator crash before/after etcd txn and ObjectStore CAS; concurrent leaders; lease loss; quorum partition; watch compaction; stale incarnation; writer crash pre/post commit; reader loss; ObjectStore outage; simultaneous node failures; bootstrap storm; drain; capacity exhaustion; metadata rollback; rolling version mismatch. Observe time to first READY replica, writer takeover, under-replication, unavailable shards, recovery bytes, placement churn and stale-publication rejection. Set numerical SLOs only after measured benchmarks.
