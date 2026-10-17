# Ontology specification register

This directory indexes the planned Quervant **native ontology indexing and inference** architecture. The QOS identifiers below refer to design discussions and approved architectural decisions; **the complete normative QOS specifications have not yet been consolidated into standalone repository documents**. Do not mistake this register for an implementation-ready specification.

| ID | Subject | Design status |
| --- | --- | --- |
| QOS-001 | Index-local ontology semantics: classes, membership, typed relationships, hierarchy families, disjointness, atomic consistency | Conceptual decisions approved; standalone normative specification pending |
| QOS-002 | Relationship archetypes, roles, characteristics, positive recursive inference and composition | Conceptual decisions approved; standalone normative specification pending |
| QOS-003 | Immutable-segment physical architecture, adjacency, snapshot readers, validation and hybrid inference | P-01–P-14 architecture approved; detailed encoding/invalidation design pending |
| QOS-003A | Relationship mutation encoding, tombstones, ordering, merge and recovery | Not yet designed |
| QOS-003B | Cross-segment adjacency, stable-ID encoding and merged iterator visibility | Not yet designed |
| QOS-003C | Incremental inference invalidation, dependency tracking and fallback | Not yet designed |
| QOS-004 | Universal query operator URNs, operator scope unions, naming and strict collision handling | Conceptual decisions approved; standalone normative specification pending |

## Approved architecture highlights

- One indexed document per instance; stable logical identity; multiple direct classes and inheritance; named hierarchy families with a designated default.
- Authoritative asserted relationship facts; inferred facts are reproducible; derived-only roles cannot be directly asserted.
- Strict atomic rejection of invalid or incompletely validated mutations; deletion removes incident asserted facts.
- Finite positive range-restricted recursive rules, deterministic least-fixed-point semantics and explicit resource budgets.
- Immutable-segment relationship storage, forward/reverse adjacency, snapshot-level readers, incremental consistency validation with complete fallback, hybrid specialized/general inference and a reference evaluator.
- Every query operator, including non-ontology operators, has a canonical URN. For example, `urn:quervant:search:operators:match` and `urn:quervant:ontology:operators:is_ancestor_of`.
- Operator scope aliases may union namespaces; effective-name collisions are fatal at configuration validation and query compilation; no namespace-order or argument-type precedence.
- Ontology predicate operator names follow the approved `Is`/`Has` convention; non-ontology operators need not. Relationship definition names omit predicate verbs.

## Sequencing and release boundary

**Complete Quervant v0.1 before ontology implementation planning.** Ontology is a future, unassigned milestone, not a v0.1 acceptance criterion. Complete QOS-003A/B/C and consolidate QOS-001–004 into reviewable, normative versioned specifications before preparing implementation PR plans. Preserve the standalone `quervant-core` boundary; distributed inference is not part of the initial ontology design.

See [cross-release roadmap](../ROADMAP.md) and [v0.1 execution roadmap](../ROADMAP_V01.md).
