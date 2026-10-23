# QGS-006B / DG-P2 — Graph-consistent distributed snapshot and reverse-adjacency qualification

**Version:** 0.1-protocol-candidate | **Status:** proposed; NOT formally proved, provider-qualified or implementation-approved | **Scope:** post-v0.2. Expands mandatory DG-P2 in [QGS-006](QGS-006.md); depends on [DG-P1](QGS-006A-DG-P1-MUTATION.md).

## 1. Why EXACT(vector) is insufficient

[Distributed C4](../distributed/03-QUERYING.md) defines `EXACT(vector)` as exact immutable per-shard generations and manifest digests; this **does not** imply an atomic globally coherent graph. A source shard may show edge E(U,V) while target's selected generation predates creation of V, or a target deletion may be visible without all incoming source-edge retractions. A target reverse-index replica may also be behind the authoritative source edge history.

Therefore an exact native graph read requiring global integrity must request **GRAPH_EXACT(qualified_descriptor)** (illustrative API name) or the equivalent typed qualified snapshot. No automatic promotion of AVAILABLE/AT_LEAST/EXACT into graph consistency.

## 2. Qualification descriptor

Candidate immutable `GraphSnapshotDescriptor`:
- `cluster_id, index_id, graph_id, graph_semantics_version`
- `routing_topology_version` and ownership/partition-map digest
- sorted vector of `(shard_id, generation, manifest_digest, writer_epoch)`
- graph protocol/catalog/schema/operator fingerprints and active graph mutation barrier identity
- dependency certificate digest covering relevant committed graph operations and logical visibility decisions
- per-projection completeness certificate/watermark by source shard **and** target shard when incoming indexes are used
- stable descriptor digest and expiration/retention lease metadata (expiration is not an alternative identity)
- proof/certificate version and qualification status

This descriptor is a **qualification of existing authoritative shard generations**, not a new authoritative CURRENT pointer. All generations remain pinned through existing distributed retention barriers. Manifest and certificate objects must be authenticated/checksummed, referentially complete and immutable.

## 3. Candidate graph-visible cuts

For graph operation T and shard s, define:
- `Prepared(T,s)`: immutable staged payload durably verified; never by itself graph-visible.
- `DecidedCommit(T)`: unique durable decision certificate.
- `Installed(T,s,g)`: fenced authoritative generation g contains all of T's required participant effects.
- `Qualified(S)`: complete metadata proves S forms a causally closed graph cut and no pending operation straddles the cut in graph-visible effect.
- `Projected(S,p)`: required reverse-adjacency projection p is complete for all source owner versions in S (or authoritative fallback selected).

**Candidate visibility rule:** T is visible in S if and only if it is committed and all required authoritative participant effects are installed at generations selected by S. An operation whose participant commits straddle S must be either wholly excluded by proven reader gating or cause S rejection. It is never partly applied to the query's logical graph.

Reader gating requires distinguishing graph-visible records from ordinary shard-local document visibility; QGS-001/002 readers must be able to apply qualified graph transaction visibility when operating on distributed graph candidates. This interaction is not present in v0.2 and needs explicit contract and format design.

## 4. Constructing a qualified vector

1. **Pin routing:** capture one versioned placement/owner mapping and all required shard identities. Physical replica assignments can vary; logical ownership does not.
2. **Choose candidate:** select exact authoritative shard generations (not reader's arbitrary latest if dependencies would be violated).
3. **Enumerate dependencies:** inspect graph commit decisions and participant installation manifests affecting the cut; verify no graph operation is half-visible. Include vertex lifecycle guards, source-edge adds/removes, managed projection dependencies and transaction visibility markers.
4. **Close cut:** if a graph operation is partially selected, either advance lagging shard generations (within retention and policy), select earlier compatible retained generations, or fail. Never silently omit a graph operation or switch generations mid-query.
5. **Verify integrity:** validate referenced live endpoints, source edge ownership, no visible post-delete incident edge, coherent catalogs/routing epochs and logical version constraints. Use durable dependency certificates plus audit/checkable digests; do not require enumerating the entire graph per query, but certificate adequacy needs proof.
6. **Qualify projection:** match requested incoming-index completeness to every relevant source owner's snapshot generation. If unqualified, choose an explicitly correct authoritative fallback or reject.
7. **Retain:** acquire/renew distributed retention pins for the whole vector, decision/dependency metadata and projection artifacts before serving; GC cannot remove a dependency while pinned.
8. **Issue immutable descriptor:** bind snapshot fingerprint to query plan/execution identity, authorization scope and operator capability; subsequent retries use exactly this descriptor.

A qualified descriptor is not a proof that domain-valid time, evidence time, or ontology effective closure are mutually consistent. It establishes **native graph lifecycle consistency only**. Distributed ontology entails separate validation.

## 5. Read operator contracts

| Operator | Qualification required |
|---|---|
| Vertex / edge lookup | authoritative generation and graph visibility marker |
| Outgoing adjacency | source owner generation, latest visible edge mutation and endpoint lifecycle validity |
| Incoming adjacency | target-local projection completeness for relevant source generations OR authoritative source lookup |
| Degree / graph analytics | complete eligible graph view and exact ownership dedup |
| BFS/frontier expansion | all used shard reads share same qualified descriptor; incomplete shard fails strict traversal |
| Search/graph join | document and graph relations obey declared index/snapshot consistency and document association identity |
| Path / inferred projection | no fictional native edge IDs or implicit ontology inference; explicit semantic adapter |

Even if only a subset of shards is scanned, a valid sound proof that omitted shards cannot affect result or qualification is required. Unavailable shard is not equivalent to an empty shard.

## 6. Reverse-index completeness protocol

For each source owner s and target owner t, maintain immutable projected update batches referencing canonical edge IDs and the exact authoritative source generation/operation interval. A projection certificate records a *contiguous prefix* of source mutations that includes adds **and tombstones**, not just a timestamp or maximum seen sequence. Gaps, duplicates, source generation rollover, stale target projection and concurrent edge creation must be accounted for.

Projection may be ahead of or behind source generation selected by a query. A reader must (a) select an exact compatible projection view, or (b) filter and verify records against authoritative state using a proven bounded strategy. A later projection's tombstones cannot erase edges that were visible in an older selected graph snapshot; projections must be versioned or reconstructed appropriately.

Inaccurate coverage metadata means fail closed; nonqualified projection must never become a negative-existence oracle.

## 7. Retention, failover and distributed streaming

- Retention covers vector generations, graph decisions, staged/projection objects required for that cut, and all active cursor/query pins. Apply [GC-002](../distributed/06-SAFETY-PROTOCOLS.md) barriers before deletion.
- On retry select READY replica with *exact* generation/digest and compatible protocol versions. A different newer snapshot may only be used for an explicit new query.
- Every distributed traversal round, graph/search join, iterative algorithm phase and client result frame retains the same descriptor.
- Apply [C7](../distributed/07-STREAMING.md): bounded demand-controlled batches, terminal End/Error, no success on EOF/disconnect, no invented resumability. Failure after output requires proven exact suffix continuation or terminal error.
- Snapshot descriptor expires only under explicit retention policy. Pin loss terminates the query with typed error, never silently replaces the vector.
- Qualification service or Aggregator failover must reconstruct qualification from durable authoritative artifacts rather than trusting ephemeral caches or etcd readiness hints.

## 8. Graph-consistent cut vs globally transactional history

A graph-qualified vector gives a valid global graph read, **not necessarily a single linearizable total order for unrelated concurrent operations**. Decide separately whether query semantics require a globally serializable graph transaction history; DG-P1 must supply enough lifecycle ordering to prevent conflicting edge/create/delete states.

For a graph query with `AVAILABLE` policy, either (i) construct and report a graph-qualified descriptor consistent with that policy, or (ii) reject operators requiring exact integrity. Never degrade silently to inconsistent graph traversal.

## 9. Formal invariants

- **G1 No dangling endpoint:** Every visible edge's endpoints are live in the same qualified descriptor.
- **G2 Atomic graph visibility:** A committed cross-shard graph operation is all-visible or all-invisible in a qualified view.
- **G3 Directional equivalence:** Qualified outgoing/incoming edge sets correspond exactly by edge ID and direction (allowing BOTH self-loop dedup).
- **G4 Immutable replay:** Reading the same descriptor yields equivalent graph results after compaction, retry or node replacement.
- **G5 No phantom resurrection:** Source tombstones, edge delete/recreate, vertex incarnation reuse attempts and projection lag cannot restore old edges.
- **G6 Retention:** Referenced authoritative generation, graph decision and qualifying projection remain retrievable while pinned; otherwise reader fails explicitly.
- **G7 Bounded completeness:** Exact reachability false, anti-joins, algorithms and aggregate results require complete relevant evaluation; budget exhaustion is not false.
- **G8 Failover:** Stale/lagging replica or routing epoch cannot qualify a cut using incompatible shard generations.
- **G9 Scope:** Qualifier cannot cross unauthorized graph/index boundaries or fabricate global ontology consistency.

## 10. Failure matrix / reference oracle

Test 2–3 shards with operation traces: vertex creation; cross-shard edge creation; opposite-direction parallel edges; source delete; target delete; target delete concurrent with incoming edge creation; key delete/recreate; edge property update; projection lag, reordering, missing batches and tombstones; decision ambiguity; crash between installs; writer failover; stale manifest; partial snapshot vector; GC race; live reader with mid-query mutation; slow client and post-output failure.

Use a small atomic in-memory graph oracle with operation order, then compare candidate qualified vectors against an explicit reference transaction/cut model. Run bounded model checking for small state spaces, fault-injection and real etcd/RustFS provider CAS tests. No test that merely confirms `EXACT(vector)` serves exact shard generations proves G1/G2.

## 11. Open protocol choices and approval gates

1. Specify durable dependency certification and coverage without per-query whole-graph scans, including proof size and incremental maintenance.
2. Define safe graph-visible staging/reader gating and compatibility with immutable source-shard publication and FP-002 (no second publication pointer).
3. Define coordinator epoch/decision certificate authority and conflict ordering with DG-P1; require permanent-failure resolution.
4. Define proof of reverse-projection contiguous coverage and snapshot-aware tombstone retention.
5. Define graph qualifier algorithm for mixed old/new shard generations, conservative fallback selection and bounded resource usage.
6. Specify how graph/document colocation and distributed joins bind one compatible snapshot without adding cross-index atomicity.
7. Prove retention behavior with GC-002, DR-002, provider CAS ambiguity and partial disk/object corruption.
8. Document precise client API consistency names and wire framing in a later approved API specification.

**HARD STOP:** Do not claim exact distributed graph traversal, graph-wide algorithms, negative reachability or valid incoming-edge completeness from ordinary EXACT shard vectors. Only a qualified descriptor and proven/fallback adjacency semantics can authorize exact execution. This document is a **protocol candidate**, not completed proof or implementation permission.