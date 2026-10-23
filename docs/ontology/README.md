# Ontology architecture specifications

**Status:** QOS-001–QOS-004 are approved conceptual architecture, version **1.0-design**; not implemented. QOS-005, QOS-008, QOS-009 and the graph–ontology integration addendum are unapproved proposals. All work is **post-v0.1**, without an assigned release or implementation PR. These documents capture the agreed architectural baseline, not finalized byte codecs, Rust APIs, or query parser grammar.

| Specification | Scope | Approval |
|---|---|---|
| [QOS-001](QOS-001.md) | Ontology semantics | Approved |
| [QOS-002](QOS-002.md) | Archetypes and declarative rules | Approved |
| [QOS-003](QOS-003.md) | Physical architecture | P-01–P-14 approved |
| [QOS-003A](QOS-003A.md) | Mutation encoding | D01–D22 approved |
| [QOS-003B](QOS-003B.md) | Cross-segment adjacency | D01–D25 approved |
| [QOS-003C](QOS-003C.md) | Inference invalidation | D01–D42 approved |
| [QOS-004](QOS-004.md) | Universal operator identity | QN-01–QN-12 approved |
| [QOS-005](QOS-005.md) | Inference explanation and provenance interfaces | **Proposed; not approved** |
| [QOS-008](QOS-008.md) | Capability and state-transition reasoning | **Prospective research; not approved** |
| [QOS-009](QOS-009.md) | Ontology discovery and agent-oriented query planning | **Proposed; not approved** |
| [GRAPH-ONTOLOGY-INTEGRATION](GRAPH-ONTOLOGY-INTEGRATION.md) | Graph traversal and ontology query composition | **Proposed; not approved** |

**Precedence:** QOS-001 defines semantics; QOS-002 defines declarative inference; QOS-003 defines physical principles; QOS-003A/B/C refine mutation, traversal and invalidation; QOS-004 defines operator resolution across all query domains. QOS-005 is a proposed, non-binding explanation/provenance extension. QOS-008 is a prospective, non-binding state-transition research candidate; QOS-009 and GRAPH-ONTOLOGY-INTEGRATION are non-binding agent/query-composition proposals; it does not change QOS-002 fixed-snapshot inference semantics. Any apparent conflict requires an explicit design amendment, not an implicit reinterpretation.

**Definitions:** *Asserted* facts are authoritative user-provided triples. *Effective* facts are asserted plus inferred least-fixed-point consequences. *Snapshot* is a pinned coherent index generation. *Incarnation ID* is a never-reused internal identity, distinct from a reusable external document key.

See [cross-release roadmap](../ROADMAP.md). No ontology implementation planning until v0.1 is complete.


## Native graph architecture integration

The [QGS-001–QGS-008 native graph register](../graph/README.md) is conceptually approved design for general-purpose property graph functionality. It **does not supersede** this register's ontology semantics: canonical asserted triples remain set-valued, native graph edges retain independent identities and parallel multiplicity, and ontology enrollment retains required indexed instance documents/classes. [QGS-007](../graph/QGS-007.md) introduces a prospective mapping/authority ledger that **requires an explicit QOS-003A/B/C compatibility amendment before implementation**. Proposed QOS-005 and QOS-008 do not gain approval by inclusion in QGS; temporal ontology inference and agentic interface details require independent QOS approval. See [graph roadmap](../graph/ROADMAP.md).
