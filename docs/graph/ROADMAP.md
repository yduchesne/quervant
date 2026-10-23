# Native graph architecture — implementation roadmap and review

**Status:** planning only; QGS-001–008 conceptually approved, not implemented or assigned to a release. This roadmap does not alter v0.1 single-shard or v0.2 distributed lexical/typed deliverables. The first delivery should remain local/standalone and avoid distributed runtime dependencies in `quervant-core`.

## Reviewed authority and compatibility

| Reference | Existing commitment | Graph preservation / review finding |
|---|---|---|
| QOS-001 | One indexed document per ontology instance; asserted triple set | Native graph-only vertex permitted, **enrolled** instances must retain required indexed document and classes; graph parallel edges not QOS assertions |
| QOS-002 | Positive least-fixed-point Datalog-like semantics and archetypes | Graph algorithms not inference, effective relations only via explicit projections |
| QOS-003A | Canonical triple mutation, atomic validation, latest delta | Native edge identity separate; **explicit amendment** required for mapping authority ledger |
| QOS-003B | Four logical direction/type access requirements, bounded cursor merge | Reuse primitives while preserving separate native `edge_id` and QOS triple key |
| QOS-003C | Complete candidate validation, DRed retraction, pinned caches | Mapped support changes must feed authoritative candidate before inference, never imply simple inferred reference counts |
| QOS-004 | Canonical operator URNs, strict resolution/fingerprints | Add graph operator namespace in same registry, no name collision fallback |
| QOS-005 | Proposed explanation/provenance, not approved | QGS link contract does **not** ratify proof format or imply evidence ownership |
| QOS-008 | Prospective hypothetical transition solver, not approved | No claim ordinary graph reachability proves effective cloud privilege escalation |
| Distributed 01–07 | v0.2 shard-level atomicity, fencing, EXACT vectors, C7 streams; no general joins | Distributed graph **post-v0.2**, C6/C7 extension only; DG-P1/DG-P2 required |
| STREAMING_SEARCH / C7 | Finite bounded cursor streams, terminal errors | Graph operator batches compose with, do not bypass, these semantics |

## Suggested dependency-oriented implementation slices

| Sequence | Documentation/implementation slice | Dependencies and acceptance |
|---|---|---|
| G0 | Contracts, QOS reconciliation, format/budget prototypes | Finalize graph/document routing, QOS authority-ledger amendment, graph-scoped IDs, typed IR and pure reference model |
| G1 | Standalone graph identities/storage | QGS-001/002; snapshot/commit, edge mutations, four logical adjacency capabilities, PIT, compaction, local/RustFS parity |
| G2 | Native local traversal and streaming | QGS-003; BFS/DFS, paths, predicates, resource limits, stream terminal completeness |
| G3 | Algorithms and projections | QGS-004; Dijkstra, components, degree, PageRank progression, typed projection/conformance |
| G4 | Unified search/graph querying | QGS-005; typed binding IR, identity join, graph patterns, safe pushdown, bounded joins and optimizer |
| G5 | Local ontology graph integration | QGS-007 + explicit QOS amendment; support ownership, enrollment, assertion reconciliation, complete validation |
| G6 | Temporal/weighted graph views | QGS-008; typed interval semantics, temporal pruning, weighted path, chronological traversal |
| G7 | Distributed graph safety gates | DG-P1, DG-P2 formal specs and real-provider qualified protocols; **block all unrestricted cross-shard graph writes/exact reads until qualified** |
| G8 | Distributed traversal/joins/analytics | QGS-006 layered over existing distributed C6/C7; owner-routed frontiers, exchange, iterative algorithms |
| G9 | Advanced integrations | Only after separate approval: QOS-005 explanations, QOS-007 temporal inference, QOS-009 agent integration, QOS-008 transition solver |

These are **relative workstreams, not PR numbers or delivery dates**. G5 and G6 can be reordered once G0 contracts are resolved. G7 may be developed in parallel on paper; runtime must await safety gates. Do not assume a two-week schedule or v0.3 graph delivery; v0.3 vector scope remains separate.

## Additional explicit reviews/gates before implementation

1. **DG-P1:** Spec a durable cross-shard edge/vertex lifecycle protocol preserving no-dangling-edge and single edge authority under partial failure, idempotent retries and remote projection lag. Need state machine, publication points, cleanup/rollback and failure-injection matrix.
2. **DG-P2:** Spec graph-qualified snapshot-vector construction, publication/retention dependencies and read qualification. Plain EXACT vector is insufficient for global graph integrity.
3. **Ontology amendment:** Define managed/explicit assertion authority ledger, mapping version fingerprint, atomic reconcile, support lifecycle, versioned API compatibility with QOS-003A/B/C and owner authentication. Not authorized merely by QGS-007 approval.
4. **Cross-domain semantics:** Check graph label versus ontology class separation; triple set versus edge bag; valid-time filtering versus temporal entailment; evidence confidence versus logical proof; graph paths versus hypothetical state authorization.
5. **Physical proof:** Evaluate four logical adjacency indexes versus shared prefix-compressed postings for write amplification, high-degree deletes, sparse seek locality and cold ObjectStore traffic. Benchmark before codec freeze.
6. **Query proof:** Validate rewrites against a reference evaluator, including anti-joins, top-K after joins, path-local visited state, opt-in inferred projections, authorization predicates and streaming mid-flight failures.
7. **Schema/operator compatibility:** Version graph type dictionaries and IR/URNs, define old-segment fallback or explicit migration. Rolling distributed capability negotiation must reject unsupported plans.
8. **Quality:** Existing >=85% production Rust line coverage gate, unit/integration/property-based differential tests, real RustFS and (for distributed) etcd, reproducible correctness and perf benchmarks, and recorded BLOCKED gates. Docs-only changes do not claim code tests.

## Non-goals and release boundaries

This change does not implement graph functions, promise general SQL/Cypher, authorize distributed transactions, alter v0.1/v0.2 scopes, approve unapproved QOS proposals, freeze codec/Rust ABI, or claim graph benchmark performance. Prioritize low-level semantic conformance ahead of speculative query optimizations and distributed execution.

## Review outcome

QGS-001–008 are mutually compatible **at the conceptual level**, contingent on the QOS authority-amendment and distributed safety protocols. Critical unresolved issues are visible rather than silently reconciled. Before coding, break G0–G9 into dedicated implementation PRs with precise acceptance/STOP conditions under `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`.

## Protocol candidate elaboration (not a gate pass)

See [QGS-006A / DG-P1](QGS-006A-DG-P1-MUTATION.md) and [QGS-006B / DG-P2](QGS-006B-DG-P2-SNAPSHOT.md). They specify a candidate staged graph mutation protocol, durable decision and lifecycle fencing, graph snapshot qualifier, reverse-index completeness and crash/failure matrices. **Neither protocol is implementation-qualified:** concrete decision/guard authority, cross-shard resolution, qualification certificate proof, writer fencing interaction, retention and real provider tests remain mandatory. G7 does not advance until these gates pass.
