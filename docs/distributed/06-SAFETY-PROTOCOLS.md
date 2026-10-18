# 06 — FP-002, GC-002 and DR-002 safety protocols

**Status:** architectural mechanisms approved; formal state-machine/model-checking and real-provider qualification **not yet complete**. These are normative constraints and STOP conditions, not claims of verified correctness.

## Common assumptions

- The authoritative per-shard publication pointer supports linearizable atomic conditional updates against an exact revision, with read-after-write reconciliation and no undetected ABA.
- ObjectStore immutable dependency writes are durable/visible before pointer publication.
- etcd provides linearizable transactions, revisioned durable metadata, leases and leader-fenced control-plane writes; etcd and ObjectStore do **not** share a transaction.
- All authoritative pointer writes pass through a trusted Publication Authority boundary with enforced storage credentials; Search Nodes cannot directly overwrite the pointer.
- A provider's conditional PUT alone does not validate application fields. Publication Authority must validate legal transitions against the latest pointer and retry conflicts by revalidation; no generic client may overwrite a current pointer with an arbitrary higher number.
- Safety claims are relative to qualified storage behavior, non-compromised credentials and bounded/terminated publication attempts as required by GC. Catastrophic permanent ObjectStore loss is outside the recoverability guarantee.

## FP-002 — Writer publication fencing

Authority record (conceptual):
```text
(cluster_id, recovery_generation, recovery_operation_id?,
 pointer_state, owner_epoch, owner_incarnation,
 committed_generation, manifest_digest, revision)
```
Normal state transitions:
- `InstallOwner`: exact recovery generation, validated outstanding grant and revision; new epoch strictly greater than installed epoch; preserve committed generation.
- `PublishGeneration`: exact recovery generation, owner epoch, incarnation and revision; immutable dependencies and retention protection verified; advance committed generation.
- `BeginRecovery`: authorized recovery operation, exact revision; advance recovery generation, enter RECOVERING and preserve committed generation.
- `FinishRecovery`: same recovery operation, validated reconciliation, enter NORMAL.
- A normal grant or publication **cannot** advance or reduce recovery generation.

etcd serializes allocation of grants to specific shard, node incarnation and transition ID. Publication Authority serializes installed ownership through the pointer. A delayed lower-epoch grant cannot overwrite an installed higher epoch. After a recovery barrier, old-recovery-generation grants cannot install or publish, even if their numeric owner epoch is higher.

**Crucial temporal guarantee:** etcd lease expiry alone does not atomically revoke already installed ObjectStore authority. Before successor installation an old writer might still publish; after successor installation it cannot. Writers are required to fail closed on lease uncertainty. Do not advertise instantaneous lease-based revocation.

**Recovery-controller race:** recovery operation ID is durably bound to barrier; etcd-fenced leadership controls recovery actions; successors may resume same operation. Only privileged authority may invoke BeginRecovery. After installing barrier, re-read pointer to recover any publication serialized before it.

**Open proof/implementation gates:** exact conditional-update token semantics, exclusive authority credentials, delayed stale client with latest ETag, crash between validation and CAS, and restoration when higher uninstalled grants exist. If any path can submit an arbitrary pointer image using valid storage credentials, this fencing model is unsound.

## GC-002 — Retention, publication and deletion

Generation states: `PROTECTED → RETIRING → GC_CLAIMED → COLLECTED`. Pins are individually lease-identified, not an unsafe in-memory count. `AcquirePin` and `ClaimForGC` serialize against the same etcd revision: pin wins and claim fails, or claim wins and pin fails.

Publication attempt states: `PREPARING → PROTECTED → PUBLISHING → COMMITTED | ABORTED`; an unresolved/ambiguous attempt remains protected. A protected intent references an immutable dependency manifest (not necessarily every object in etcd). Staged objects use attempt-scoped namespaces and separate cleanup rules.

`RegisterIntent` must prove no dependency is already claimed and atomically establish protection before publication is allowed. `ClaimForGC` must prevent new intents from referencing claimed objects. The publication authority checks intent validity and reference protection before CAS. GC claims are durable, collector-epoch fenced and idempotently resumed. Marking walks all authoritative committed manifests, retained snapshots and protected intents; ObjectStore listing cannot establish authoritative reachability.

**Safety property:** at deletion time an object is neither reachable from any protected generation nor publishably referenceable by any active intent. An object selected for deletion cannot acquire a new authorized reference. A grace period or repeated listing alone is not a proof.

**Open proof/implementation gates:** define the exact atomic conflict key for intent registration vs object/group claim; prove no TOCTOU gap between manifest dependency validation and protected registration; handle merges reusing old segments; prevent in-flight uploads into a GC-claimed namespace; prove expired intents cannot still publish; make stale collector deletion-set isolation enforceable. Until closed, remote destructive GC stays disabled.

## DR-002 — Catastrophic metadata restoration

Cluster recovery states: `NORMAL → RECOVERY_REQUIRED → FENCING → RECONCILING → VALIDATING → NORMAL`; failures enter `QUARANTINED`. Restore does not silently create a new cluster or trust stale node readiness.

1. Restore etcd quorum and validate immutable cluster identity; stop ordinary grant issuance and mutation admission.
2. Establish a single fenced recovery operation ID.
3. For each shard, install an ObjectStore `BeginRecovery` barrier advancing the recovery generation. Reconcile ambiguous CAS outcomes.
4. Read **post-barrier** committed generation and manifest digest; verify immutable dependencies.
5. Reconcile routing/index definitions, allocation floors, pending operations, retention and durable deletion tombstones; quarantine inconsistencies.
6. `FinishRecovery`, reestablish placement and new-generation ownership grants, bootstrap readers, then allow writers to become ACTIVE.
7. Keep destructive GC disabled until retention reconstruction is complete.

An old grant from a prior recovery generation cannot install after the barrier, regardless of its owner epoch. A publication serialized before the barrier is legitimate and must be discovered by the post-barrier read. No new writer may activate before its shard has passed reconciliation. Unrecoverable ObjectStore state blocks recovery; ambiguous deleted-index identity is quarantined rather than resurrected.

**Open proof/implementation gates:** restoring etcd with a stale recovery operation, concurrent recovery controllers, partially installed per-shard barriers, index deletion tombstone durability, stale snapshot leases, recovery interrupted repeatedly, and authorization of BeginRecovery. A disaster-recovery procedure may require administrative quiescence; ordinary Coordinator failover must remain automatic.

## Failure-interleaving test register

| Race | Expected outcome |
|---|---|
| Two owner installations | One serialized pointer order; stale loser cannot overwrite |
| Publish vs owner takeover | Commit before takeover or rejection after takeover |
| Old high-epoch grant vs recovery barrier | Cannot install after barrier |
| Old writer with latest pointer revision | Cannot bypass transition validation |
| Crash after successful CAS before acknowledgment | Recover pointer, preserve durable commit |
| Concurrent recovery controllers | One authorized operation; successor resumes idempotently |
| Pin vs GC claim | Exactly one wins |
| Intent registration vs GC claim | Protection wins or publication rejected |
| GC worker crash after claim | Claimed set resumes idempotently |
| Stale GC worker after leadership change | Cannot delete outside authorized claim |
| etcd rollback after deletion | Tombstone/recovery evidence prevents resurrection |
| ObjectStore unavailable during recovery | Block without write activation |
| Unknown publication result during GC | Keep dependencies protected |
| Snapshot retry on missing generation | Typed failure, no generation substitution |

## Completion gates

Before distributed writer publication: demonstrate qualified real ObjectStore CAS, privilege enforcement, deterministic stale-leader/writer races, monotonic recovery generation and unambiguous durable acknowledgments.

Before destructive remote GC: demonstrate a precise cross-store deletion-barrier proof and adversarial tests of all publishing paths; otherwise retain garbage.

Before disaster-recovery enablement: demonstrate stale-grant fencing, tombstone reconciliation, interrupted barrier recovery and quarantine behavior.

Do not delegate design of missing serialization or proof details to a low-reasoning coding agent. An unresolved proof obligation is a STOP condition, not an invitation to weaken the invariant.
