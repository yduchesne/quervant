# 05 — ObjectStore durability, publication and retention

**Status:** D3 approved direction, FP-002/GC-002 required before destructive operations.

## Storage authority

ObjectStore is authoritative for each logical shard's immutable committed generations and installed ownership. Search Node materialization and caches are disposable. Shard namespaces are isolated by cluster/index/shard identity; content sharing is shard-scoped for v0.2. Core's existing segment/manifest formats and cold bootstrap should be reused, not reimplemented by distributed services.

**Exactly one authoritative committed-generation pointer per shard.** The existing standalone `index/CURRENT` contract and distributed fencing-aware authority must be adapted into one logical source of truth; never allow two independently writable pointers. Specify the exact adapter before coding.

## Publication authority boundary

Only a leader-fenced Publication Authority may validate and perform ownership installation, generation publication, and recovery-barrier transitions. Writers upload immutable dependencies and submit protected publication intents; they cannot bypass validation with direct pointer overwrite. Every transition is an exact-revision conditional update against a qualified linearizable ObjectStore pointer. Re-read and reconcile ambiguous CAS results; no blind retry or premature `DURABLE`.

Pointer fields include cluster ID, recovery generation, owner epoch and incarnation, lifecycle, committed generation, manifest digest, and pointer revision/version token. Owner change increases epoch within a recovery generation; ordinary generation commit preserves owner and recovery generation; recovery barrier advances recovery generation and invalidates old-incarnation grants. These are **protocol checks**, not semantics automatically supplied by a generic S3 conditional PUT. See [FP-002](06-SAFETY-PROTOCOLS.md#fp-002--writer-publication-fencing).

## Object lifecycle and retention

Logical classifications: STAGED → COMMITTED/RETAINED → GC_ELIGIBLE → DELETED. Shared immutable objects are reachable from potentially many manifests; do not infer object liveness from a single generation. Current authoritative generation, explicitly retained historical generations, active distributed snapshots, unresolved authorized publication intents and recovery state protect their dependencies.

Snapshot retention uses durable generation records and lease-bound pins with an atomic pin-vs-GC-claim barrier. Retention must survive Search Node failure and Coordinator restart; local reader pins alone are insufficient. Expired cursor use fails explicitly. Enforce snapshot count/lifetime/bytes limits with admission errors rather than silent revocation.

Publication intents must declare/protect dependency manifests **before** authoritative publication. Attempt-scoped staging namespaces isolate uncommitted objects. A collector cannot treat an object as orphaned merely because the current committed manifest does not reference it. Failed/ambiguous publications require reconciliation; cleanup needs a proof that no authorized publisher can reference the staged objects.

## GC-002 policy

Two-stage conservative mark/claim and sweep. Pin acquisition, publication-intent registration and GC claims must serialize on compatible shard-level retention state. The collector claims eligible generation/object groups durably, verifies current authoritative pointer and protected manifests, then deletes only proven unreachable objects. Claims survive collector crashes; stale collectors cannot extend their deletion sets. Storage listing is candidate discovery, never proof of committed state.

**Mandatory safety invariant:** no successful publication may introduce a reference to an object after it becomes GC-claimed. Every publishing path—including merge, import, initial provisioning, writer takeover and restore—must participate. A time grace period, two scans, or an etcd snapshot alone does not establish this invariant. If proof or provider qualification is incomplete, disable destructive remote GC and conservatively retain objects.

## Failure behavior

ObjectStore unavailable: existing fully verified local snapshots may remain readable under retention contract; no new durable publication or cold bootstrap. etcd unavailable: destructive GC suspended. Missing object/digest mismatch: fail snapshot materialization and report integrity failure. Interrupted GC: idempotent resume. Publication-pointer CAS conflicts: reconcile exact pointer. Local cache eviction is independent of remote GC.

## Acceptance

Publication crash pre/post CAS, ownership transfer with unresolved intent, snapshot pin vs GC claim, intent registration vs GC claim, shared immutable objects, stale collector, partial deletion, corrupted object, inconsistent listing, etcd restore, remote outage, expired cursor and reader failure with retained snapshot. Real RustFS/S3-compatible conditional-update qualification is mandatory.
