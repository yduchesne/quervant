# 07 — C7 distributed query-result streaming

**Status:** proposed C7 design extension for v0.2; documentation only, not implemented, qualified or a frozen wire API. **Source of truth for shard-local streaming:** [../STREAMING_SEARCH.md](../STREAMING_SEARCH.md). This specification composes that contract across shards and MUST NOT introduce a second search cursor engine into `quervant-distributed` or dependencies on distributed services into `quervant-core`.

## Protocol and service architecture (DS-001)

[DS-001](09-SERVICE-PROTOCOLS.md) fixes the presentation direction: Tonic/Prost native gRPC for internal shard streams and native client server-streaming; Axum/HTTP JSON and newline-delimited JSON event streams for external clients; common transport-independent SearchService and typed result events. Both external streaming protocols are v0.2 delivery targets. This C7 specification owns result ordering, snapshot consistency, correctness, backpressure and terminal semantics. DS-001 owns adapter boundaries, RPC/presentation technology and transport conformance. There must be no second distributed cursor engine or protocol-specific query planner.

## Purpose and non-goals

Support finite, snapshot-consistent queries that emit bounded incremental batches to clients when operators permit. This is not continuous query execution, subscription to new mutations, streaming indexing, change-data capture, live-tail, exactly-once delivery across disconnections, or a Unix-like pipeline language. A streaming transport is an adapter and must not dictate core execution; DS-001 selects HTTP NDJSON and native gRPC server-streaming for v0.2 while allowing future presentation adapters. Distinguish (a) pull-based engine batches, (b) shard-to-Aggregator transport, (c) Aggregator-to-client transport, and (d) optional client-side pipelines.

## Reuse and execution pipeline

```text
Client (bounded pull / transport flow control)
       ↑ result frames, terminal status
Query Aggregator (plan, snapshot vector, work reservation,
                  bounded per-shard input buffers, global merge)
       ↑ independent demand-controlled shard streams
Search Node (versioned shard plan, pinned generation, core cursor,
             finite bounded next_batch(max_rows, max_bytes))
       ↑
quervant-core (segment iteration, filters, projection, PIT, cancellation)
```

No Coordinator proxy. An Aggregator must use one accepted attempt per logical shard, not one per replica. A streaming query uses the **same logical/physical plan, GLOBAL_STATS default for BM25, exact-analytics guarantees, snapshot vector and resource budget** as [03-QUERYING.md](03-QUERYING.md). Streaming changes result delivery, not query meaning.

### Plan classification and execution phases

The physical planner MUST label stages according to whether output can be safely finalized incrementally, requires a bounded lookahead, or blocks until all necessary contributions are known.

| Query/operator | Emission rule |
|---|---|
| Filter/projection, unordered scan | Finite batches may emit incrementally; encounter order is not semantic sort and is not stable across retries |
| Globally sorted scan over provably ordered shard streams | K-way merge; cannot emit an item until every non-exhausted required shard has an established next bound/head or proof that it cannot precede the item |
| Sorted `head N` | Exact first N by globally defined total sort key; stop/cancel remaining upstream work when proven |
| Unsorted `head N` | First N in the specified encounter policy; never describe as newest/best scored |
| `tail N` | Bounded last-N state; cannot emit finalized tail before stream completion |
| Adjacent `uniq` | Streams with neighboring-key comparison; globally exact distinct needs completeness proof and budgets |
| Exact BM25 top-K | Global term expansion/stats and sufficient scoring/top-K proof before releasing final ranking; may block |
| Exact global sort without ordered access/index guarantee | Blocking or bounded external strategy, not premature output |
| Exact `GROUP BY`, `DISTINCT`, counts | Final results only once complete aggregation is known (unless deterministic completed-key/bucket frontier is proven); provisional progress distinctly typed and never final |
| Time buckets | Only finalized buckets after all relevant shard contributions are accounted for; late/out-of-order events prohibit naive early emission |
| Client `grep`/pipeline | Post-filters emitted records; index-side predicates are pushed down through existing core query IR |

No promise of low time-to-first-batch for blocking queries. Bounded streaming output does not imply constant-time source access or unlimited aggregation cardinality.

## API and frame contract (transport-neutral design)

A stream is a **finite execution** with a single terminal outcome. Conceptual frame types:

- `Start`: query/execution ID, plan/protocol version, effective consistency policy, snapshot identity or opaque reference, ordering/completeness mode, resource limits.
- `Batch`: monotonically increasing stream sequence number, batch rows, byte count, optionally a checkpoint marking fully delivered ordered progress. All rows belong to the immutable snapshot vector established at start.
- `Progress` (optional): explicitly non-final work counters/estimated counts; never a finalized aggregation result.
- `End`: terminal success, accurate completeness indicators, shard participation, total rows, accounting, optional validated continuation cursor where supported.
- `Error`: terminal typed error, whether any rows were already delivered, last acknowledged/visible sequence when known, and whether a safe restart or checkpoint resume is possible.

**No successful EOF-by-disconnect:** truncation, deadline, budget exhaustion, missing shard, expired pin and unexpected transport termination cannot be represented as successful complete results. A transport unable to guarantee a terminal frame must require its client to treat an unclean close as failure. The exact public schema and wire protocol are implementation-plan decisions; frame semantics are normative.

Every data frame obeys configured **maximum rows and serialized bytes**. An oversized single row is rejected by a documented policy; never bypass the byte cap silently. Error/completion metadata must not be truncated by a data-row cap.

### Backpressure, concurrency and fairness

- Backpressure flows **client → Aggregator → Search Node → core cursor → local/remote I/O**; bounded credits (rows/bytes) or explicit pull determine upstream demand. Each hop enforces finite queues and prefetch limits, not just TCP buffering.
- Each active shard attempt has bounded outstanding batches and buffered bytes. Aggregator's merge heap, network buffers, reordering state, stored fields, and optional aggregation state are separately metered; overall bounds scale with admitted shard fan-out under global memory/network caps.
- A slow client pauses source production; avoid holding unbounded batches in background tasks. Enforce idle/lease lifetime policies with explicit terminal errors, not silent snapshot switching.
- Bounded concurrent shard streams and admission classes integrate with C5 global work reservations. Work spent in planning, GLOBAL_STATS expansion, scans, discarded attempts, retries and final merge remains charged. Unknown attempts retain reservations until terminated or safely expired.
- A client cancellation/disconnect propagates to all active RPCs and shard-local cursors; close PIT/reader leases, release reserved budgets when safe, stop ObjectStore reads and bounded prefetch. Cancellation itself does not promise that already-in-flight work costs zero.

### Sorted multi-shard merge

Define a total order with complete sort tuple, explicit null/missing ordering and stable tie-breaker including `(index_id, logical_shard_id, stable_document_key)` (or equivalent deterministic unique identity); do not rely on local doc IDs across shards. Each shard returns monotonic rows in that total order, or an explicit bound sufficient for global emission; conflicting order metadata is a protocol error.

For each required non-exhausted shard, maintain a current head/verified lower bound. Repeatedly select the global smallest (or largest) head, emit it, then replenish that shard. A temporarily unavailable head is **not** evidence the shard has no earlier qualifying result. Bounded lookahead is mandatory; no full result-set materialization in the Aggregator for ordered-stream plans. Shard pruning is permitted only with a correctness proof under the plan.

Unordered streams may multiplex bounded batches, but define the encounter policy and avoid claiming stable results across attempts. Exact completeness still requires terminal success from all required shards.

### Snapshot, retention, cursor and resume

A stream binds at admission to an explicit routing version and per-shard `(index_id, shard_id, generation, manifest_digest)` vector. Acquire cluster-level retention pins before shard execution; local pins alone do not protect ObjectStore generations. Renew under policy and fail explicitly if the snapshot cannot remain valid. All phases, retries and batches use the same snapshot vector; never silently replace an unavailable generation.

**Streaming cursor ≠ durable pagination token.** Cursor position in a running shard stream is not automatically serializable, replayable or safe for client resume. Resume after partial delivery is optional and must be designed independently: integrity-protected checkpoint bound to snapshot, query/plan fingerprint, routing version, total order, per-shard positions and expiry. A checkpoint may be exposed only at a globally consistent output boundary where already emitted rows cannot reappear or be skipped. If exact resume cannot be guaranteed, return a typed non-resumable error and require an explicit new query; never promise exactly-once client delivery.

A retry before any client-visible output may restart the full execution against the same snapshot. After visible output, a failed shard attempt may be replaced only if it reproduces the exact remaining ordered suffix without gaps/duplicates and the Aggregator can verify the checkpoint; otherwise terminal error. For unordered streams, transparent restart after emission is generally not safe without a stronger stable ordering/progress contract.

### Replica failover and terminal completeness

Each shard stream has `(query_id, stage_id, shard_id, attempt_id)` identity and sequence/acknowledgment tracking. Late frames from superseded attempts are ignored. A replica that serves a different generation cannot replace an in-progress attempt on the existing stream. Default strict completeness: all selected logical shards must finish successfully for `End(success)`. Optional partial mode must be opt-in and identify omitted/failed shards both in metadata and final status; do not emit a misleading success before knowing completeness.

A client that cancels early (`head N`) can receive successful **limited-query** completion only if the plan's semantics prove that N final rows suffice; otherwise early termination is a cancellation/partial execution, not an exact count/sort/aggregation result.

## Capability negotiation and transport boundaries

Require capability/version negotiation for shard streaming, row framing, ordered streams, checkpoint support, plan/operator IDs and terminal status. During rolling upgrades select compatible replicas or fail typed; never fall back from exact globally ordered streaming to arbitrary unordered output. DS-001 commits to external HTTP NDJSON and native gRPC server streaming in v0.2; WebSocket and gRPC-Web remain optional future adapters. All transports must preserve bounded flow control, cancellation and distinguish clean terminal success from truncation. Cross-process payloads must have size limits and stable serialization guarantees.

## Acceptance tests and release gates

1. **Reuse:** shard execution uses core batch/PIT interfaces; core remains independent of distributed, etcd and transport SDKs.
2. **Incremental first batch:** selective scan produces first rows before whole-result enumeration when plan permits.
3. **Memory safety:** arbitrarily slow consumer with many shards respects per-hop rows/bytes/prefetch plus cluster-wide budgets.
4. **Global order:** mixed shard data, ties, null/missing and shard pauses yield correct k-way order and sorted `head N` parity with a single logical index.
5. **Unsorted semantics:** encounter-order `head` is not mislabeled time/latest or ranked top-K.
6. **Blocking operators:** global BM25, exact top-K/GROUP BY/DISTINCT and time buckets do not emit unfinalized values; budgets fail explicitly.
7. **Snapshot consistency:** mutations, refresh/merge, replica lag and retention expiry never switch the generation vector mid-stream.
8. **Failure after output:** dropped RPC, delayed old attempt, shard crash, partial frame, client disconnect and unclean transport close produce explicit failure or verified exact resume—not silent success, duplicates or gaps.
9. **Cancellation:** early proven `head N`, user cancel and deadline propagate; local/remote work stops and pins/budgets release safely.
10. **Resource accounting:** multi-phase global stats, retries/hedges, serialization and fan-out remain within C5 work/memory/network limits.
11. **Upgrade compatibility:** incompatible frame/operator capability cannot execute and yields typed error.
12. **Integration:** real multi-node + etcd + RustFS/ObjectStore transport tests, partition/fault injection, bounded memory and throughput/time-to-first-batch benchmarks.
13. **Protocol equivalence:** native Tonic gRPC and Axum NDJSON clients observe the same typed stream states, global ordering, completeness, snapshot and terminal failure semantics, with conformance tests as in DS-001.

**Implementation gate:** confirm on current `main` the actual core pull-batch/PIT API delivered by v0.1 before planning work; adapt to it, never invent a duplicate distributed cursor. Streaming feature completion requires executed tests in the required topology; documentation approval alone does not qualify it.
