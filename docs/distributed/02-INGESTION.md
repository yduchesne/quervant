# 02 — Distributed ingestion and mutation semantics

**Status:** approved architecture, pending implementation and publication-protocol qualification.

## Path and ownership

Client → stateless Indexing Coordinator → authoritative shard writer on Search Node → shard-local `quervant-core` mutation/commit → Publication Authority → ObjectStore pointer. Readers independently refresh from authoritative committed generations.

Indexing Coordinator validates routing topology version, maps canonical stable routing key to a logical shard, groups bounded batches, applies backpressure and forwards to current writer incarnation. It never builds segments or mutates the publication pointer. Node churn must not reroute a document to a different logical shard.

## Mutation identity and ordering

Each operation has stable `operation_id`, canonical payload fingerprint, document key, optional expected revision and declared routing key. Same ID/same canonical payload returns its original outcome; same ID/different payload is a conflict. Deduplication **precedes** expected-revision validation, so retry of an already committed conditional update does not fail due to its own revision change.

- Shard writer serializes mutation order and assigns monotonically increasing document revisions through delete/recreate; tombstones preserve revision history.
- No global mutation order or cross-shard transaction.
- Mutation effects, revisions, tombstones and dedup outcome are committed atomically in one authoritative shard generation.
- Operation IDs survive writer takeover. Dedup retention/GC policy must be explicitly designed before expiry; no silent time-based deletion.
- An ordered batch has a defined per-shard operation order; cross-shard results may be partial.

## Acknowledgment levels

| Level | Meaning | Failure behavior |
|---|---|---|
| `ACCEPTED` | Admitted to volatile writer state | May disappear after crash; retry same operation ID |
| `DURABLE` | Authoritative generation publication confirmed | Must survive recovery, including ambiguous client acknowledgment |
| `SEARCHABLE` | Eligible reader confirmed required generation | Readiness may later regress due to node failure; durability does not regress |

Return explicit per-shard statuses and retry guidance. A multi-shard request may partially succeed; no implicit all-or-nothing promise. If a publication CAS response is ambiguous, reconcile pointer and durable operation records before returning success or retrying.

## Writer failover

A new writer receives a unique incarnation and higher fenced ownership epoch, installs ownership through Publication Authority, then recovers the latest authoritative generation before accepting writes. A stale writer cannot publish after successor installation. During loss of lease authority, fail closed for new admission and publication. A control-plane outage blocks new grants; the ObjectStore pointer is the final publication authority. Details: [FP-002](06-SAFETY-PROTOCOLS.md#fp-002--writer-publication-fencing).

## Admission and resource bounds

Bound client ingress, per-shard queues, batch sizes, outstanding publication attempts, local memory and retry fan-out. Distinguish overload, stale routing, stale owner, CAS conflict, unavailable ObjectStore and ambiguous commit. Preserve operation IDs across retries. A durable Kafka-style journal is deferred.

## Required tests

Same-ID replay; payload collision; revision-check ordering; tombstone/delete/recreate; mixed-shard partial batch; writer crash before and after CAS; ambiguous CAS; delayed stale writer; leader failover; lease partition; duplicate retries; read replica lag; bounded backpressure. Real ObjectStore and etcd failure cases must accompany deterministic fakes.
