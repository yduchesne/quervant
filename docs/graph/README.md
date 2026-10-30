# Native graph architecture — QGS design register

**Status:** QGS-001 through QGS-008 conceptually approved in architecture review; documentation-only. **Not implemented.** No release assignment, format freeze, protocol qualification, or implementation authorization follows from approval.

| Specification | Scope | Decision IDs |
|---|---|---|
| [QGS-001](QGS-001.md) | Native attributed multigraph model and identity | AD-001–AD-008 |
| [QGS-002](QGS-002.md) | Immutable graph records and adjacency | SD-001–SD-011 |
| [QGS-003](QGS-003.md) | Traversal execution and streaming | TD-001–TD-012 |
| [QGS-004](QGS-004.md) | Algorithms and analytical projections | GA-001–GA-013 |
| [QGS-005](QGS-005.md) | Unified search/graph logical and physical plans | QP-001–QP-015 |
| [QGS-006](QGS-006.md) | Distributed graph ownership and execution | DG-001–DG-015; DG-P1/DG-P2 mandatory gates |
| [QGS-007](QGS-007.md) | Graph/ontology mapping and assertion authority | GO-001–GO-015 |
| [QGS-008](QGS-008.md) | Temporal, weighted and attributed graphs | TW-001–TW-015 |
| [ROADMAP](ROADMAP.md) | Dependencies, implementation sequencing, gates and review findings | Planning only |
| [Cross-subsystem integration roadmap](../INTEGRATION_ROADMAP.md) | Distributed/graph/ontology scheduling, shared contract ownership, PR concurrency and STOP gates | Planning only; does not supersede QGS |

## Authority, precedence and explicit boundaries

1. Existing [QOS-001–QOS-004](../ontology/README.md) remain authoritative for ontology instance semantics, canonical asserted triples, inference and operator resolution. QGS is authoritative for **native graph semantics**, including independent multigraph edge IDs. Any overlap requiring new assertion-authority state is a **future explicit QOS compatibility amendment**, not an implicit override.
2. The [distributed design register](../distributed/README.md) remains normative for v0.2 Coordinator, placement, writer fencing, generation vectors, streaming and ObjectStore publication. QGS-006 adds **post-v0.2** graph capabilities and does not change v0.2's no-general-joins boundary.
3. [QOS-005](../ontology/QOS-005.md) explanations and [QOS-008](../ontology/QOS-008.md) state-transition reasoning remain unapproved. Temporal ontology semantics (QOS-007) and agent query discovery (QOS-009) require separate approval/reconciliation. No inferred path is evidence of causality, confidence or executable privilege escalation.
4. `quervant-core` stays fully standalone. Graph logical storage, local traversal, algorithms and typed query planning build on core facilities; `quervant-distributed` composes them without introducing cluster dependencies into core.
5. No arbitrary global graph transaction, atomic cross-shard snapshot, cross-shard ontology validation, inferred-edge materialization or automatic temporal inference is claimed.
6. Reader/optimizer correctness is never based on approximate estimates. Fail explicitly on missing authoritative records, inconsistent snapshots, budget exhaustion, unsupported operator versions or incomplete validation.

## Common invariants

Never-reused UUIDv4-compatible 128-bit vertex and edge incarnations; optional graph-scoped external keys; no dangling edges; native graph parallel edges and self-loops; ontology triple set semantics; independent transaction/valid/observation times; committed generation/PIT isolation; explicit domain and projection semantics; exact versus approximate results distinguished; bounded buffers, memory/I/O/work and cancellation; authoritative ObjectStore data and disposable caches.

## Review / delivery state

Architecture **approved conceptually**, implementation **not started by this PR**, wire protocols/byte codecs/Rust ABI **undecided**, DG-P1 and DG-P2 **mandatory safety design gates**, no release scope moved. Every spec includes a verification contract and reserved decisions. See [ROADMAP](ROADMAP.md).