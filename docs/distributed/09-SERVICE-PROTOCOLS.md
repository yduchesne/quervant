# DS-001 — Service interfaces, RPC and presentation protocol architecture

**Status:** proposed architectural decision, approved in principle for documentation; normative when this PR is accepted. **v0.2 design requirement, not a claim of implementation or a frozen public wire/API schema.** Depends on [03 distributed querying](03-QUERYING.md), [07 C7 streaming](07-STREAMING.md), [core streaming](../STREAMING_SEARCH.md), [02 ingestion](02-INGESTION.md), and [06 safety protocols](06-SAFETY-PROTOCOLS.md).

## DS-001-01 — Decision

Choose **Tokio** async runtime, **Tonic + Prost / Protocol Buffers over HTTP/2 gRPC** for internal distributed RPC and native gRPC clients, and **Axum + Hyper/Tower** for external HTTP JSON APIs and NDJSON finite-result streams. The two client adapters execute the **same transport-independent application services**; no duplicate query planner, batch mutation planner, stream merger, snapshot allocator or authorization policy may be created inside protocol handlers. The internal shard RPC API is distinct from public service APIs. No generic plugin framework or additional client protocols are required in v0.2.

Protocol compatibility is a product capability: add later WebSocket, SSE, gRPC-Web, SQL-compatible or other presentation adapters without rewriting the execution service. HTTP NDJSON and native gRPC server-streaming are **both mandatory finite-result v0.2 delivery targets**. Internal gRPC is mandatory. Continuous subscriptions, CDC and live tail are outside DS-001.

## DS-001-02 — Layering and ownership

```text
   curl / CLI / jq / grep       Browser / JSON SDK          Native gRPC SDK
       HTTP JSON/NDJSON          HTTP JSON API              gRPC streaming
                 \                   |                         /
                      protocol-specific adapters
                    (decode, validate envelope, encode)
                                |
                shared application service contracts
       SearchService | MutationService | IndexService | ClusterAdmin
         typed RequestContext, authz, result frames, budgets
                                |
    standalone execution OR distributed execution implementation
    local core          Query Aggregator / Indexing Coordinator
                                |
                       versioned internal gRPC
                  Coordinator / Search Nodes / Authority
                                |
                 shard-local quervant-core cursor/writer
```

The standalone and distributed implementations expose equivalent client-level semantics where supported; capability negotiation and typed errors identify unavailable distributed-only features. Neither `quervant-core` nor the on-disk segment format imports Tonic, Axum, Protobuf, etcd, or HTTP concepts.

The shared *service contracts* are independent of framework-native request/response types. They may start as modules in `quervant-distributed` or a narrowly scoped independent crate (e.g. `quervant-service`) only after validating dependency direction; crate splitting is not a prerequisite for implementing the first RPC. Avoid protocol DTO types leaking into the domain/physical planner.

Suggested interface responsibilities:

| Interface | Primary operations | Owner |
|---|---|---|
| SearchService | `execute`, `stream`, optional cursor resume when proven | local search adapter or Query Aggregator |
| MutationService | validated batch mutation, visibility/commit status | local writer adapter or Indexing Coordinator |
| IndexService | index metadata/schema and lifecycle | local manager or Coordinator application service |
| ClusterAdmin | cluster status, placement, drain/recovery administrative operations | Coordinator application service; not exposed by Search Nodes by default |

Conceptual service boundary: `RequestContext` contains authenticated principal, tenant/scope if configured, deadline, cancellation handle, trace/correlation ID, negotiated capabilities, consistency/snapshot request and policy-derived budgets. `SearchRequest` is typed and transport-neutral. `ResultStream` is a **demand-driven asynchronous sequence of typed result events** with a single terminal outcome, not a materialized `Vec`. The exact Rust signature, `Send`/lifetime constraints and async trait technique are fixed in an implementation plan after inspecting the v0.1 core cursor.

**Authorization enforcement:** adapters authenticate credentials and translate verified identity into a non-forgeable service context; shared service core performs request/action/index authorization. Internal RPCs additionally authorize caller *role* and target shard/ownership; mTLS or equivalent service authentication is required for production deployment. Do not trust arbitrary `principal` fields supplied in client JSON or protobuf. Search Node RPCs must not expose administrative/public APIs by accidental trait reuse.

## DS-001-03 — Interface and transport versioning

- Define domain request/result/error enums independent of wire DTOs. Protobuf messages and HTTP JSON envelope are distinct versioned mappings to the same semantic model.
- Tonic/Prost Protobuf internal schema uses explicit `protocol_version`, `capability_set`, stable numeric field tags, optional fields and reserved removed tags. Unknown required operators fail typed before execution; don't silently downgrade exact semantics.
- Separate **internal shard RPC** (`ExecuteShardPlan`, `StreamShardResults`, readiness/capability checks, writer admission and status) from **public gRPC services** (`Search`, `StreamSearch`, `ApplyBatch`, index/admin as authorized). Shard plans and fencing grants are not public inputs.
- HTTP v0.2 routes under `/v1/` with one JSON request/response mapping and one finite streaming endpoint; do not build transport-specific query grammars. Exact URI naming and Protobuf package identifiers must be fixed together before code.
- The Aggregator is the only coordinator of global plans/merge; HTTP and public gRPC adapters call its common SearchService, not their own planner.
- Typed errors need stable semantic codes (invalid query, unauthorized, forbidden, overload, snapshot expired, incomplete shards, incompatible protocol, cancellation, deadline, budget, ambiguous mutation). Map to HTTP status and gRPC Status codes consistently, while keeping structured domain details.
- Provide health/readiness APIs separately from search application APIs. Propagate structured tracing IDs, deadline and cancellation across boundaries; redact credentials/PII from logs.

## DS-001-04 — Streaming service contract and event schema

**Use C7 as the authority for query semantics** and [STREAMING_SEARCH.md](../STREAMING_SEARCH.md) for shard-local pull/batch mechanics. Query plans classify streamable vs blocking operators. Both presentation adapters must preserve the same execution's pinned generation vector, global BM25 and exact aggregation semantics.

One finite stream uses this conceptual event sequence:

```text
Start(query_id, snapshot_id, plan_version, ordering, completeness_policy)
Batch(sequence, rows, serialized_bytes, optional_checkpoint)
[Progress(nonfinal_counters)]*
...
End(complete, emitted_count, shard_coverage, optional_cursor)
          OR
Error(code, partial_rows_emitted, last_completed_sequence, resumable)
```

- At most one terminal event, **End or Error**, and no data afterward. Missing terminal event (unexpected EOF/transport reset/timeout) is **failure**, not successful completion. A transport with out-of-band termination must retain equivalent semantics.
- Enforce max rows *and* serialized bytes per batch, bounded per-stage queues and per-query output caps. Oversize rows are typed errors, not an unbounded exception.
- Once a row was emitted, a shard failure may cause terminal partial failure. Transparent retry/resume requires verified exact suffix checkpoint under the *same* pinned vector. No promise of exactly-once delivery across disconnection.
- An ordinary running cursor is **not** a durable resumable pagination token. External resume is optional, authenticated/integrity-protected and time-bounded when supported.
- Exact top-K/BM25 scoring and exact global GROUP BY/DISTINCT may not emit finalized rows until a correctness proof permits it; streaming API presence does not imply early first byte for all operators.
- C7 strict completeness is default. Explicit partial-result mode must carry coverage/completeness in `End` and must never be confused with strict success.

### HTTP structured streaming

The mandatory HTTP streaming response uses `application/x-ndjson`, UTF-8, one JSON event object per **newline-terminated** line. Mandatory `type` discriminator: `start`, `batch`, `progress`, `end`, `error`; fields map to typed domain events. Streams are consumed with `curl -N` or any incremental JSONL reader; a client must check the terminal `end` event and `complete` status. If an error occurs after response headers or rows were sent, report it as a typed in-band terminal `error` when transport is still writable. An HTTP status code set before the body cannot represent a later stream error; do not treat HTTP 200 alone as proof of successful query completion.

Expose a separate *optional* raw-record export adapter/CLI mode emitting one projected document JSON object per line for tools such as `jq`, `grep`, `head` and Python pipelines. Because raw records cannot encode the structured terminal protocol unambiguously, raw export itself **must not claim strict completion** without a separately specified out-of-band mechanism. The first-party CLI should consume the authoritative structured event stream, print only records to stdout, report terminal failures on stderr and use a nonzero process exit status; document shell `set -o pipefail`. Client-side filtering is post-filtering; indexed predicates should be pushed into SearchService for efficiency. Direct `curl | grep` of structured events is permitted but not a correctness-sensitive complete-export workflow without checking `end`.

Examples are illustrative—not frozen URI/schema:

```sh
curl -sS -N -H 'Content-Type: application/json' \
  -d '{"query":{...}}' https://server/v1/search/stream
# Stream returns event envelopes; a client validates the final end frame.
```

HTTP adapters and production reverse proxies must disable response buffering for streaming, preserve flush boundaries to the extent supported by HTTP, avoid unbounded compression buffering, and propagate disconnect/cancellation. NDJSON remains viable over HTTP/1.1 or HTTP/2; this does **not** make HTTP and gRPC bidirectional streams interchangeable.

### Native gRPC streaming

Public native gRPC `StreamSearch` uses Tonic server streaming of Protobuf result-event messages with one-of frame variants mapping to exactly the same logical Start/Batch/Progress/End/Error states. Normal gRPC status alone is insufficient if application completeness metadata must be preserved; use explicit terminal event and distinguish transport Status failures. Internal `StreamShardResults` uses a separate, versioned shard frame envelope and carries attempt/shard identifiers, pinned generation and budget reservations.

gRPC's HTTP/2 flow-control windows help, but do not alone bound application queues, serialized-batch sizes or eager core prefetch. Support consumer cancellation and stop upstream I/O promptly. Browser gRPC-Web is **not** a mandatory v0.2 adapter; it must not be assumed equivalent to native gRPC capabilities.

## DS-001-05 — End-to-end bounded demand and cancellation

```text
client polls / reads
  → HTTP or gRPC transport is ready to write
  → shared ResultStream is polled (bounded adapter buffering)
  → Aggregator requests shard batches under credits
  → Search Node pulls from existing core cursor
  → segment/remote I/O bounded prefetch
```

- Explicit bounded credit/permit and max frame-size policy across each hop. Absence of client demand must not permit unbounded queuing, even with an internally spawned task, buffered channel or transport writer.
- C5 query-global budgets account for all phases, retries, RPC batches, serialization, memory and output bytes. Exceeding them yields typed terminal error, not silent truncation.
- Backpressure extends upstream through a finite number of in-flight frames and bounded remote prefetch. Validate slow-client, zero-consumer, client-disconnect and high-shard-count adversarial workloads.
- Cancellation, deadline and lease expiry terminate shard work, release PIT/snapshot protection and work reservations safely; an ambiguous in-flight attempt retains its reservation until termination is confirmed or a safe bound expires.
- HTTP and gRPC must produce equivalent data and query finality under comparable requests, with consistent handling of mid-stream shard loss, client disconnect, incomplete shard coverage and snapshot expiration.

## DS-001-06 — Deployment and internal RPC

One Tokio runtime per host process as appropriate. Use Tonic/Prost for unary and server-streaming internal RPCs; do not add a second RPC framework for Coordinator operations. Connection pools, max concurrent streams, message caps, deadlines, keepalive, retry policy and flow-control limits must be explicit and independently tunable for Coordinator, Search Node and client-facing workloads.

Internal service design:
- Coordinator: watch/lookup metadata, readiness/placement RPC where relevant; authoritative durable metadata remains etcd and publication barrier ObjectStore, not an RPC cache.
- Search Node: capability/readiness, shard-local query and bounded stream, writer batch admission, commit status.
- Publication Authority: restricted validated ownership/publication transitions; **never** expose unrestricted pointer writes or permit arbitrary shard-node invocation of recovery barriers.
- Query Aggregator and Indexing Coordinator: application implementations behind protocol adapters; no Coordinator on query hot path.

Protocol adapters can be co-hosted, but cannot cause query traffic to monopolize control-plane capacities. Query-side clients connect to a stateless Query Aggregator endpoint and mutation-side clients to an Indexing Coordinator endpoint or API gateway forwarding to them. A single public gateway is optional, not required for correctness.

## DS-001-07 — Security, compatibility, operations

- TLS for external transports; internal service authentication/authorization, mTLS recommended as the baseline for distributed production. Credential propagation is explicit, restricted and audited.
- Apply size/time/concurrency limits before large allocations; reject decompression bombs, oversized Protobuf and oversized JSON. Per-principal quotas and request correlation are enforced once in the shared service.
- Preserve stable public error codes and versioned event types; both adapters must be testable against independent semantic oracles rather than copied serializer implementations.
- Provide bounded telemetry on query_id, stage_id, shard_id and attempt_id; never log raw secrets or entire document bodies by default.
- Rolling upgrades require capability negotiation, backward-compatible schema evolution rules and defined failure behavior for unknown mandatory event variants.
- Failure of one presentation adapter must not corrupt or change core generation state; adapters are stateless regarding authoritative shard commits.

## DS-001-08 — Delivery plan boundaries

1. Before distributed RPC implementation: define the common service request/context/error/event types and dependency direction; decide module vs crate from the actual workspace.
2. Implement internal Tonic/Prost service definitions and real cross-process integration; execute deadline, authentication, capability/version and shard stream flow-control tests.
3. Implement one shared SearchService across distributed query execution, then map it into both public Tonic server streams and Axum NDJSON routes.
4. Implement MutationService and index/admin adapters with consistent typed status/error mappings.
5. Qualify transport equivalence with real etcd/ObjectStore, partial-output failures, backpressure and cancellation.

The transport architecture does not authorize implementing B2 cross-shard transactions, continuous search subscriptions or speculative public query languages.

## DS-001-09 — Mandatory acceptance tests

1. **One engine:** same typed query via HTTP JSON, HTTP NDJSON and native gRPC yields semantically identical sorted rows, projections, completeness, global BM25 and snapshots.
2. **Stream completion:** clean `end` success; query rejection before headers; post-first-batch shard crash yields `error` or unclean-close detectable failure; no false HTTP 200 success.
3. **Bounded consumer:** client stops reading; per-hop buffers, queues and core cursor/remote prefetch remain within measured budgets, no unbounded detached producer.
4. **Command-line consumption:** structured-event CLI adapter emits exactly one document per line for `jq` and `grep`; terminal error returns nonzero; `pipefail` guidance verified.
5. **Order/snapshots:** globally sorted merge, tie-breakers, strict completeness, pinned generation, pagination/checkpoint semantics identical across protocols.
6. **Cancellation:** disconnect/deadline/cancel propagated through transport, shared service, Aggregator, Search Node and remote I/O; snapshot leases and resources reclaimed.
7. **Error mapping:** unauthorized, forbidden, missing index, conflict, snapshot expiry, query budget, overload, protocol mismatch and partial failure retain typed semantics in both adapters.
8. **Isolation:** Search Node cannot invoke unrestricted publication transitions; public adapters cannot forge principal/context; ordinary shard access cannot invoke ClusterAdmin.
9. **Rolling upgrade:** old/new protocol capabilities interoperate only when semantics match; unsupported mandatory operator/event fails typed, not silent downgrade.
10. **Real boundaries:** actual Tonic network service, Axum HTTP server, multi-node Query Aggregator, etcd and RustFS; deterministic latency/failure injection plus throughput, first-batch latency and memory benchmarks.
11. **Core independence:** `quervant-core` works and passes standalone tests with no Tokio network adapter, Tonic, Axum or etcd requirement.

**STOP:** Do not let a low-reasoning implementation agent freeze Protobuf tags, public JSON envelope, crate layout, streaming error semantics or service authorization boundaries without a reviewed implementation plan consistent with this decision.
