# Ontology architecture specifications

**Status:** QOS-001–QOS-004 are approved conceptual architecture, version **1.0-design**; not implemented. QOS-005 and QOS-008 are unapproved proposals. All work is **post-v0.1**, without an assigned release or implementation PR. These documents capture the agreed architectural baseline, not finalized byte codecs, Rust APIs, or query parser grammar.

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

**Precedence:** QOS-001 defines semantics; QOS-002 defines declarative inference; QOS-003 defines physical principles; QOS-003A/B/C refine mutation, traversal and invalidation; QOS-004 defines operator resolution across all query domains. QOS-005 is a proposed, non-binding explanation/provenance extension. QOS-008 is a prospective, non-binding state-transition research candidate; it does not change QOS-002 fixed-snapshot inference semantics. Any apparent conflict requires an explicit design amendment, not an implicit reinterpretation.

**Definitions:** *Asserted* facts are authoritative user-provided triples. *Effective* facts are asserted plus inferred least-fixed-point consequences. *Snapshot* is a pinned coherent index generation. *Incarnation ID* is a never-reused internal identity, distinct from a reusable external document key.

See [cross-release roadmap](../ROADMAP.md). No ontology implementation planning until v0.1 is complete.
