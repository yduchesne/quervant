# Graph–Ontology Query Integration — Proposed contract

**Status:** 0.1-proposal, not approved | **Scope:** post-v0.1, unassigned | **Type:** cross-cutting design addendum (not a replacement for QOS-003B).

## Motivation and existing authoritative decisions

Quervant's ontology storage already specifies forward/reverse, generation-scoped *asserted* adjacency (QOS-003B D06–D25), immutable segment mutation resolution (QOS-003A), candidate fixed-point inference, retraction and fingerprinted caches (QOS-003C), and class/relationship semantics (QOS-001/002). Do **not** introduce a separate mutable graph database, require persistent closure materialization, or reinterpret effective inference as asserted edges.

The cross-release roadmap separately explores general-purpose BFS/DFS, K-hop and shortest paths. Those are **future candidate graph features, not approved execution operators**. This document proposes the missing binding contract between graph traversal and ontology-aware predicates, while retaining their independent optionality.

## Three logical layers

1. **Storage/search:** index-local document identities, authoritative asserted triples, typed/lexical/time/geo search, snapshot/refresh/PIT and mutation semantics. Primary authoritative data resides in existing index generations.
2. **Graph computation:** optional traversals over typed directed relationships using bounded, cancellable cursor interfaces; graph traversal does not require an ontology rule program.
3. **Ontology reasoning:** typed classes, effective memberships and inferred relationships computed above asserted adjacency using snapshot-pinned deterministic rules. No hypothetical state (QOS-008).

These are logical capabilities in standalone `quervant-core`, not separate physical services. They must share pinned snapshot, cancellation and accounting.

## Candidate relationship views

- `ASSERTED`: only triples in QOS-003A's latest visible asserted set, from QOS-003B's asserted cursors. No derived edges.
- `EFFECTIVE`: asserted plus sound derived triples under QOS-002/QOS-003C least-fixed-point rules; completeness required for claims of absence.
- Selection is explicit in typed IR; the default for raw graph traversal should be `ASSERTED` to preserve predictable semantics, subject to approval.
- Results identify the relationship type's canonical URN, endpoint incarnation IDs, snapshot, and asserted/inferred origin. An effective duplicate of an asserted triple must not appear twice in set semantics. A future QOS-005 proof is a separate optional feature.
- Relationship direction is explicit; inverses, symmetries and transitive closure are applied only in the effective view according to ontology semantics, never silently in an asserted view.
- Ontology inheritance/class resolution must not add endpoints through recycled external document keys.

## Candidate query algebra and planner constraints

- A typed relation expansion accepts source bindings, type URNs, direction, selected view, hop/fan-out/result ceilings, shared work budget, and predicates for candidate endpoints.
- Graph operators proposed for staged design: bounded one-hop adjacency, K-hop reachability, optional BFS/DFS, and optional unweighted shortest path. General graph operators have no finalized semantics until independently approved.
- Boolean AND/OR and existing typed/lexical/temporal/geo filters compose with ontology predicates against the same pinned index generation; planner pushdown/pruning is permitted only if conservative and semantics-preserving.
- An inferred edge may participate in traversal only when the explicit effective view is supported and certified sound; avoid recursive planner cycles between graph expansion and rule inference.
- `NOT`/absence and "no path" require completion of all relevant work; exhaustion, unsupported modes, and cancellation are indeterminate/errors, never false. Positive witnesses may terminate early if sound.
- Stable pagination/order must bind snapshot and plan; unordered exploration does not imply deterministic shortest paths. No result can be emitted as final if later evaluation could invalidate its completeness/order (including streaming).
- Shared work meter: charge lexical candidates, adjacency seeks/records, traversal fan-out/frontier, inferred facts and rule firings, remote bytes, materialization, memory, output bytes and time to a single query-level envelope. Suboperators cannot reset limits.

## Execution placement and future distribution

Begin in standalone `quervant-core`; avoid dependency on cluster management. Existing QOS-003B cursor/merge and QOS-003C inference boundaries remain controlling. Local/RustFS correctness and pinned-snapshot equivalence precede optimizations. Predicate pushdown into graph source/target scans is permitted only after soundness and budget accounting are established.

For later distributed execution: declare cross-shard traversal/ontology inference **unsupported** until separate shard ownership, routing, snapshot vector, global work budget, streaming backpressure, deduplication, and completion semantics are approved. Do not imply the approved v0.2 distributed query architecture includes ontology or graph traversal.

## Reconciliation with roadmap

The roadmap's *edge-document plus repeated indexed lookup first* suggestion is a prospective delivery/benchmark strategy for general-purpose graph indexing. QOS-003B already chooses dedicated immutable adjacency for ontology asserted triples. Neither supersedes the other: any general-purpose graph feature should evaluate reuse of QOS-003B adjacency under compatible semantics, and must not duplicate authoritative edge mutation paths without an explicit rationale.

## Design decisions still requiring explicit approval

1. Whether the same relationship records and identity model are reusable for graph-only indexes without an active ontology definition.
2. Raw-graph default asserted-view semantics, behavior when no ontology is defined, and constraints on relationship-type registration.
3. Typed relation-expansion IR, traversal algorithms and their precise result ordering, path uniqueness, cycle semantics and materialization policy.
4. Cost/plan selection across indexed candidate filters, adjacency, and inference.
5. Shared work accounting and cursor/streaming failure contracts.
6. Security and authorization of edge exploration, graph endpoints, and inferred paths.
7. Local/remote benchmark gates for edge documents vs dedicated adjacency.
8. Distributed compatibility without committing cross-shard traversal.

## Reference conformance scenarios

- Same asserted outgoing/incoming neighbors across segment merges, retract/reassert, PIT, delete/recreate, cold ObjectStore readers.
- Raw asserted paths differ from effective inference paths for inverse/transitive relationships; effective set results deduplicate multiple derivations.
- Filter candidate vertices by indexed timestamp and typed field, then compare composed query with independently evaluated filter-and-expand reference semantics.
- Alternative proofs and a retracted foundational edge invalidate only unsupported effective paths in a new snapshot.
- Negative reachability cannot return false on fan-out/deadline/resource exhaustion.
- Alias collisions, mismatched ontology fingerprints and unsupported graph capabilities reject.
- Stress huge hubs, deep cycles, remote pruning and cancellation; no whole-graph materialization or unlimited work.
- Query snapshots pinned across pagination, compaction and concurrent mutation; no mixed-generation results.

## Non-goals

No general-purpose graph database product promise; no PageRank or community detection; no RDF/OWL compatibility requirement; no approval of QOS-005 explanation API; no QOS-008 hypothetical transitions; no v0.1/v0.2 implementation expansion.

**Decision gate:** This is a proposed addendum. Existing QOS-001–QOS-004 and QOS-003A/B/C approved invariants prevail if any wording differs.
