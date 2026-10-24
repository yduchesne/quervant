# B2 — Distributed atomic batches and query-targeted mutations

**Status:** proposed distributed architecture extension approved in principle for documentation; this file is a normative *design proposal*, not a claim of implemented distributed functionality or a proof of global transactional semantics. See the existing [distributed ingestion contract](02-INGESTION.md), [QMA-001](../decisions/QMA-001_MUTATION_ARCHITECTURE.md), and actual `quervant-core::contract::mutation` / `IndexWriter::apply_batch` on current main. Core batch behavior is the source of truth for one shard. This specification does not change the standalone core API.

## B2-01 — Supported core semantics and non-negotiable reuse

Core `MutationBatch` is ordered and all-or-nothing *within one index writer*, with a whole-batch optional idempotency key. Targets: `Key`, `Keys`, `Query(QueryMutationSelector)`. Actions include explicit-key insert/upsert/delete, replace, patch update, query-selected delete/update/replace, and restricted `QueryUpsert { replacement, fallback }`. Query selection is based on the committed batch-initial snapshot, never a partial top-K page or volatile unpublished view; bounded complete match resolution, deterministic key order, expected generation/revision protection, reconstruction and fail-closed limits remain core responsibilities. Ordered explicit-key commands observe prospective staged state; query selectors refer to the initial committed selection view.

No distributed service may reimplement the core's writer-side batch planner, revision/tombstone allocation, reconstruction, durable replay fingerprint, failure rollback or segment/manifest commit. The Indexing Coordinator handles routing, coordination and outcomes only.

## B2-02 — Atomicity boundaries and API truthfulness

**Shard atomicity:** each `IndexWriter::apply_batch` either admits the entire supplied *shard-local* batch or admits none; refresh/commit and replay follow QMA-001.

**Distributed atomicity:** a distributed request touching several shards is a set of independently atomic sub-batches. No global prepare/commit, 2PC, all-or-nothing rollback, global transaction isolation or global replay ledger is assumed. A previous shard's `DURABLE` success is never rolled back merely because a later shard rejects.

Expose separate typed operations or an explicit `atomicity_scope = SHARD` contract. Do NOT reuse the standalone `MutationBatch` name in a way that implies atomicity over several shards. If client explicitly requests whole-request atomicity and routing resolves to multiple shards, fail before any side effect with `CrossShardAtomicityUnsupported`. Failure responses distinguish `NOT_ATTEMPTED`, `REJECTED`, `ACCEPTED` (volatile), `DURABLE`, `SEARCHABLE`, and `UNKNOWN_RECONCILE`. Never report overall atomic success when only a subset succeeded. The coordinator never treats accepted volatile work as durable.

## B2-03 — Stable identity and exact replay

Client supplies a stable distributed request token and the canonical original request. Indexing Coordinator computes and validates a canonical whole-request fingerprint including **all target keys, full selector query, selector limits/expected generation, action payloads, preconditions, routing version and command order**. A duplicate token with a different canonical request is a conflict. The earlier omitted-query-fingerprint failure mode is a mandatory regression case.

Within each partition, derive a stable shard batch token from `(distributed_request_identity, routing_version, shard_id, deterministic sub-batch plan digest)`, using an explicitly versioned collision-resistant derivation. Each retry must submit identical shard commands in identical order with the same shard-local core token. Core's durable replay is authoritative for that shard; do not interpret a distributed in-memory cache as sufficient for durability. A coordinator restart or crash between shard acknowledgments cannot rewrite already durable results; unresolved outcomes are reconciled by retry of stable shard batches / querying the durable replay ledger.

**Unresolved design requirement:** durable replay of query-resolved target sets needs durable request-plan identity or exact deterministic re-resolution protection. A stateless Indexing Coordinator must not silently re-run an already partially committed global query against a newer snapshot and target a different set. Until a durable plan/operation record or equivalent safe mechanism is specified and tested, cross-shard query-targeted execution must fail closed before mutation. Do not invent a durable distributed journal merely to make this statement true.

## B2-04 — Explicit-key batch routing (v0.2 baseline)

Map each explicit document key to its stable logical shard with the index routing topology version. `Keys` spans shards by deterministic partition of keys; an ordered request is split into per-shard subsequences preserving **original command order and, within each command, deterministic key order**. Duplicate keys and multi-command overlaps must retain the core's staged-state semantics *within each shard*. Cross-shard command order has no global serialization promise.

Preflight routing version and reject unsupported routing-key changes. Before sending any shard batch, validate structural invariants and hard request-level limits; individual shard failures may still yield partial success. Shard writer performs final canonical validation, atomic admission, revisions and replay. Ensure stable sub-batches and aggregate response preserves original command ordinals, per-key outcomes, shard identity and terminal status. Do not claim a single global linearization point.

## B2-05 — Query selection and exact global preflight

Query-targeted commands may match across all shards, so sending the core's query command to every writer without coordination is forbidden for **global** cardinality, uniqueness, fallback or no-side-effect guarantees.

The distributed selection phase must:
1. Resolve and validate index schema, routing version, query semantics and global request fingerprint.
2. Establish a pinned vector of committed per-shard `(shard_id, generation, manifest_digest)` identities; **this is not an atomic cross-shard point-in-time snapshot**.
3. Evaluate each selector against **every required shard**, using the existing core query semantics and a complete bounded key enumerator rather than top-K results. Global `max_matches` caps the total deduplicated matched keys; reject on overflow without any mutation. For `QueryUpsert`, short-circuiting to detect a second match is allowed only for rejection.
4. Produce a deterministic selected-key plan, global match cardinality, source shard/generation/revision preconditions and target routing. Query-upsert fallback key routes to exactly one deterministic shard.
5. Enforce request-wide scanned candidates/work, materialization, selected keys, bytes, deadline and cancellation before side-effect admission; no truncated success.
6. Revalidate conditions at the shard writer during execution, with an explicit **stale-selection conflict** if selected revision or required committed generation changed.

**Global TOCTOU limitation:** a successful preflight on a vector of independent shard generations does not prevent a newly matching document from appearing on another shard before the action commits. A global "no matches anywhere at commit time" or globally unique match under concurrent writes cannot be guaranteed without stronger exclusion/transaction coordination. The API must distinguish **selection-snapshot semantics** from a live global serializable predicate guarantee. If the latter is requested, reject as unsupported, not silently downgrade.

## B2-06 — Query mutation actions and routing

| Action | Distributed rule |
|---|---|
| Query delete | Select all global matching keys (within total cap), then issue deterministic explicit-key tombstones to owning shard writers, with snapshot/revision guards. Empty selection is no-op; cross-shard partial commit is possible. |
| Query update | Resolve complete global selection; each owning shard reuses core document reconstruction/patch validation and atomic writer planning; no cross-shard rollback. |
| Query replace | Each selected key retains its stable identity; field-template identity is inert; perform replacements through core-equivalent validated semantics, never rewrite keys based on template identity. |
| QueryUpsert, 0 matches | Only **one** explicit fallback insert, routed by its stable key; validate that key's original selection/staged existence conditions and no earlier command touches it. |
| QueryUpsert, 1 match | Replace exactly the selected stable key with replacement field values; do not insert fallback. |
| QueryUpsert, >=2 matches | Reject globally before side effects with ambiguity; no per-shard independent fallback attempts. |
| Explicit-key Upsert/Insert/Delete/Replace/Update | Route by key and preserve local core semantics. |

**Cross-shard command dependency STOP:** a query-target command and another command in the same distributed request can interact through staged state on different shards. The implementation must either (a) prove an equivalent deterministic per-shard decomposition respecting initial-selection semantics and ordering, or (b) reject that request shape before any mutation. Do not silently reorder or weaken core batch behavior.

### Support stages and scope gate

- **Required v0.2:** explicit-key/Keys shard partitioning, atomic shard-local batches, stable replay, request-to-shard status aggregation and failover.
- **Query-targeted delete/update/replace and restricted QueryUpsert:** architectural target conditional on preflight, durable plan/replay reconciliation, snapshot contract and concurrency qualification. Their inclusion as mandatory v0.2 release gates requires a dedicated explicit scope decision before PR decomposition. No unsupported cross-shard query-targeted action may be silently executed as per-shard independent queries.
- **Deferred:** cross-shard atomic transactions, global serializable query mutation predicates, automatic resharding during an in-flight batch, multi-match QueryUpsert, durable distributed transaction log without separately approved design.

## B2-07 — Failure and recovery semantics

- If selection fails on any required shard, **do not admit** any shard batch.
- If a shard precondition conflicts during execution, reject that shard's entire atomic batch; previously committed shards remain committed and are itemized.
- If an acknowledgment is lost, recover via authoritative shard replay; do not infer rollback or duplicate application.
- When routing/placement changes, a retry targets the same **logical shards**, independently of Search Node placement; resharding topology changes need an explicit migration protocol.
- If a selection pin expires before execution, fail or reject remaining work under the defined contract; do not silently select against latest.
- If a writer fails after admission but before publication, `ACCEPTED` may be lost; same token/revision semantics govern retry.
- Error typing must separate ambiguous global predicate, match-limit overflow, stale selection, insufficient query budget, storage outage, routing-version mismatch, missing snapshot and partial durable success.

## B2-08 — Mandatory acceptance and fault-injection matrix

1. One-shard batch parity for insert, upsert, delete, replace, patch and query-targeted actions.
2. Explicit-key multi-shard batch partition preserves command ordinals and per-shard atomic rollback on validation errors.
3. Partial durable success followed by retry never replays a committed shard with changed payload or changes revision twice.
4. Fingerprint includes full selector query; MatchAll vs Term with same bounds must conflict on reused token.
5. Global query-delete selection counts every shard, enforces global `max_matches`, and rejects before mutations on overflow.
6. Global query-upsert has zero/one/multiple match tests across different shards; fallback inserted at most once and never on >=1 global matches.
7. Query update/replace preserves keys, lossless reconstruction and typed/JSON/geospatial field semantics via core.
8. Selection-vector generation changes and selected-key concurrent revisions fail with explicit conflicts; tests demonstrate non-serializable global predicate caveat.
9. Coordinator/Indexing Coordinator crash during selection, after some shard commits, after CAS, and during replay recovery.
10. Writer failover, stale owner, objectstore CAS ambiguity, replay ledger recovery and lease partition.
11. Global budget exhaustion/cancellation before preflight completion yields zero writes; after execution begins returns per-shard truthful outcomes.
12. Unsupported global transactional/serializable request and unsupported dependent mixed command shapes fail **before side effects**.
13. Real etcd + RustFS multi-shard integration, deterministic schedule/fault injection, and independently oracle-checked key/revision/manifest state.

**STOP gates:** do not let an implementation agent design cross-shard transactionality, durable global selection-plan replay, or global predicate synchronization. If no safe protocol exists under stateless coordinator + shard-local committed-snapshot selection, restrict the public operation and document why. No code is delivered by this PR.
