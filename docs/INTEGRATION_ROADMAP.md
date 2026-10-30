# Quervant cross-subsystem integration roadmap — Distributed / Graph / Ontology

**Status:** proposed cross-cutting implementation sequencing and integration-gate register; documentation only. **No new runtime capability is implemented or approved by this roadmap.** Its purpose is to coordinate PR order, compatibility decisions and acceptance gates across the existing separate roadmaps—not to replace their architectures, freeze Rust APIs/codecs or move graph/ontology functionality into v0.2.

**Fresh-main planning baseline:** `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e` (2026-10-30). Re-check actual `main` and PR status before producing each implementation plan; the baseline is a documentation anchor, not an assertion that current code stays unchanged.

## Authorities, precedence and scope

1. [Cross-release roadmap](ROADMAP.md) owns release boundaries; [distributed D01–D15](distributed/ROADMAP.md) and [XJ-001](distributed/10-CROSS-INDEX-FOUNDATION.md) own v0.2 work packages and cross-index search contracts. v0.2 covers single-index distributed and multi-index UNION; it **does not** implement distributed joins/exchanges, graph processing or ontology inference.
2. [Distributed 01–10](distributed/README.md) govern cluster routing, per-shard writer fencing, shard-local batching, query snapshots/budgets, C7 streaming, DS-001 protocols, XJ-001 identity and schema semantics. `quervant-core` remains independently usable without cluster/transport services.
3. [QGS-001–008](graph/README.md) own native graph identity, storage, traversal, algorithms, graph/search planning, distributed graph processing, graph/ontology mapping and temporal semantics. [Graph G0–G9](graph/ROADMAP.md) own graph work-package scope. Their conceptual approval is not implementation completion.
4. [QOS-001–004](ontology/README.md) own index-local ontology definitions, assertions, positive inference, constraints, adjacency, mutation and operator URNs. The concrete contracts are [QOS-001](ontology/QOS-001.md), [QOS-002](ontology/QOS-002.md), [QOS-003A](ontology/QOS-003A.md), [QOS-003B](ontology/QOS-003B.md), [QOS-003C](ontology/QOS-003C.md) and [QOS-004](ontology/QOS-004.md). QOS-005, QOS-008, QOS-009 and the graph/ontology addendum are proposals, not approved runtime scope. Do not treat [QGS-007](graph/QGS-007.md) approval as the required amendment of QOS-003A/B/C.
5. [QGS-006](graph/QGS-006.md) explicitly requires **DG-P1** cross-shard graph mutation safety and **DG-P2** graph-qualified snapshot safety before unrestricted distributed graph mutation/read. Index-shard `EXACT(vector)` is **not** a globally graph-consistent snapshot. QOS-001 keeps inference index-local initially.
6. All coding-agent PR plans follow [DETAILED_PR_PLAN_AUTHORING_GUIDE](DETAILED_PR_PLAN_AUTHORING_GUIDE.md), with exact source baselines, prescriptive design, tests, decision matrices and **STOP on unapproved architectural alternatives**. A combined integration plan is not an authorization to let the coding agent invent a shared abstraction.

## Strategy: concurrent architecture, staged delivery

**Chosen default:** design the shared identity/storage/query/snapshot contracts together; implement small, independently qualified PRs in partly overlapping lanes, with explicit freeze/ownership rules around shared files. Neither three fully concurrent large feature branches nor a strict Distributed → Graph → Ontology waterfall.

- Primary early implementation critical path: **D01–D07** distributed spine; qualify D04 FP-002 early. Parallel **G0** graph contracts, compatibility proofs and test-oracle planning may proceed without modifying the same production code.
- After stable interfaces: **D08–D15** distributed cross-index search, streaming, failure/recovery and qualification. Independent **G1–G3** standalone graph storage/read/traversal PRs may overlap only if they preserve frozen core manifest/query contracts or explicitly sequence their changes outside D14/D15 acceptance.
- Once query algebra is frozen: **XJ-002+** general joins and **G4** unified search/graph queries share one higher-level typed binding IR, not separate execution languages. **O1–O5** standalone ontology can proceed after identity/adjacency/semantic gates, without waiting for distributed graph algorithms.
- Later **G7–G8** distributed graph execution after DG-P1/DG-P2, and **G5/O6** graph/ontology mapping after QOS authority amendment. Distributed ontology joins and *federated inference* are distinct later scope decisions; no implicit federation.
- G3 graph algorithms, G6 temporal graph and QOS explanation/agent work can be separately prioritized; they are **not unconditional prerequisites** for the minimum local search/graph/ontology query integration. Retain their own spec acceptance gates.

### Suggested waves (dependencies, not fixed calendar dates)

| Wave | Primary delivery track | Parallel *permitted* work | Exit condition / not yet permitted |
|---|---|---|---|
| **W0 — Contract reconciliation** | Integration gates IG-01–IG-04, identify shared owners | D01 implementation-plan drafting; G0/QOS amendment design | Identity, durable-format compatibility and IR dependency decisions reviewed before conflicting production PRs |
| **W1 — Distributed spine** | D01–D07 RPC, catalog, placement, authority, nodes, ingestion and single-index query | G0; isolated G1 storage prototypes/oracles after IG-02 | FP-002 and runtime single-index integration evidence; no graph/ontology code merged into unsettled publication authority |
| **W2 — v0.2 closeout + standalone graph** | D08–D15 XJ-001, multi-index UNION, C7/DS-001 and safety qualification | G1–G3 local immutable graph records, adjacency and traversal in separately qualified small PRs; O1 semantic/type design | v0.2 qualified on a declared SHA; protect D14/D15 against concurrent format/manifest churn |
| **W3 — Local cross-domain queries** | XJ-002 local typed binding and joins; G4 local search/graph query composition | O1–O5 ontology definitions, asserted readers, inference and incremental validation after relevant gates; optional G3/G6 | Local differential oracle for joins, graph bags vs ontology sets, pinned snapshots and shared budgets; do not advertise distributed join support |
| **W4 — Distributed joins and graph** | XJ-003–006 exchange/joins; G7 qualified DG-P1/DG-P2 then G8 owner-routed graph execution | G5/O6 local native graph ↔ ontology mapping after QOS amendment; graph tuning | No unrestricted cross-shard graph mutation/query before required proof and real-provider qualification |
| **W5 — Distributed ontology extension** | Cross-index joining of independently evaluated ontology relation sources, if approved | Separate protocol design for cross-index rule/definition federation, invalidation and global inference | Distributed least-fixed-point inference is **separately approved and qualified**; ontology joins do not imply federated entailment |

**O1–O6 are tentative planning labels introduced here solely for scheduling:** O1 definitions/URN/dictionaries; O2 local instance/membership and canonical assertions; O3 snapshot readers and direct/effective predicate interfaces; O4 fixed-point inference/constraint validation; O5 incremental invalidation/retraction plus complete fallback; O6 local graph/ontology integration. Their detailed PR decomposition must be designed against fresh source and approved QOS contracts, not inferred from these labels.

## Integration gates: owner, consumer and immutable acceptance evidence

Gate status is **OPEN / NOT YET QUALIFIED** by this documentation PR. A gate can close only through a specifically approved decision and executed validation appropriate to its risk.

| Gate | Shared contract / owner | First affected work | Evidence to close; STOP if missing |
|---|---|---|---|
| **IG-01 — Namespaced identity** | D02/XJ-001 IndexId + graph QGS-001 graph/vertex/edge incarnation + QOS-001/003B ontology instance | D08, G1, O2 | Stable never-reused index/vertex identities; typed document↔vertex association; no key reuse resurrection; parallel edges preserved, ontology triples deduplicated. STOP if new identity representation conflates keys. |
| **IG-02 — Immutable storage/manifest compatibility** | Core storage/manifest owner + QGS-002 + QOS-003A/B | G1, O2, D04/D05/D14 | One authoritative shard generation/CURRENT publication; format version/feature-bit compatibility, PIT/compaction/remote/cache/GC parity, independent codec oracle and real RustFS. STOP on unapproved format change during safety qualification. |
| **IG-03 — Shared query semantics and IR** | XJ-001/D08 + QGS-005 + QOS-004 | D08, G4, XJ-002, O3/O6 | One higher-level typed binding relation interface; versioned operator capability and canonical fingerprints, bag/set/nullable values, index/graph/ontology source identity. Search core Boolean optimizer remains separate. Unsupported operators reject before execution. |
| **IG-04 — Snapshot/pin and one work budget** | C4/C5/C7 + QGS-003/005 + QOS-003C | D07/D11/D12, G2/G4, O3/O4 | Pinned per-shard/index identities, explicit non-transactional cross-index vector, bounded stream and exact error completion, shared deadline/cancellation/reservations. No budget reset or implicit re-pin. |
| **IG-05 — Publication and mutation failure safety** | FP-002/GC-002/DR-002 + QGS-002 + QOS-003A/C | D04/D06/D14; graph/ontology writer PRs | Stale owner blocked, qualified CAS, candidate all-or-none within shard, crash recovery and retention barriers; no second graph/ontology authority or unsafe destructive GC. |
| **IG-06 — Query identity joins and correctness** | QGS-005 + XJ-002–006 | G4, distributed joins, O6 | Document↔vertex mapping is incarnation-aware; local join differential oracle includes bag multiplicity, anti-join completeness, top-K after join, typed null and authorization. Separate distributed exchange qualification later. |
| **IG-07 — Ontology assertion authority mapping** | QGS-007 GO-003/004/007 + **explicit** QOS-003A/B/C amendment | G5, O6 | Defined EXPLICIT vs MANAGED_MAPPING authority/support ledger, idempotency, last-support deletion, inference invalidation, authorization and atomic candidate validation. STOP if not amended and approved. |
| **IG-08 — Cross-shard graph mutation protocol (DG-P1)** | QGS-006 | G7/G8 unrestricted edge/vertex mutations | Durable endpoint/edge ownership, delete races, remote reverse projection, failover/compensation and referential-integrity failure matrix, real etcd/RustFS qualification. STOP otherwise. |
| **IG-09 — Graph-qualified read snapshot (DG-P2)** | QGS-006 | G8 cross-shard traversal/exact reads | Dependency/barrier and retention proof for coherent graph versions; stale reverse projections must have sound fallback or fail; no ordinary EXACT(vector) substitution. STOP otherwise. |
| **IG-10 — Ontology inference consistency** | QOS-001–004/003C | O4/O5, any effective-fact query | Finite positive least-fixed-point equivalence to complete reference oracle, DRed retraction, constraints, cache fingerprinting, completeness for negative claims, budget failure atomicity. |
| **IG-11 — Cross-index ontology federation boundary** | QOS-001 + future explicit federation design | Any cross-index inference | Namespace/rule/identity mapping, global rule and assertion authority, dependency/invalidation and qualified snapshot/publication protocol. Joining index-local results may precede; **do not call it federated inference**. |
| **IG-12 — Cross-subsystem release freeze** | Release owner, D15 + local graph/ontology acceptance owners | D15, G1 format merge, O2 mutation merge | Fresh SHA and CI/real-provider replay; halt or explicitly requalify when a shared manifest/IR/API change invalidates frozen acceptance evidence. No stale PASS. |

### Gate state register (initial)

| Gate IDs | State | Rationale |
|---|---|---|
| IG-01–IG-06 | **OPEN** | Existing specifications provide design intent, not unified frozen implementation/test evidence |
| IG-07 | **BLOCKED ON QOS AMENDMENT** | QGS-007 explicitly requires a separate QOS-003A/B/C compatibility amendment |
| IG-08–IG-09 | **BLOCKED ON DG-P1/DG-P2** | Protocols mandatory and unresolved in QGS-006 |
| IG-10 | **OPEN — LOCAL QUALIFICATION REQUIRED** | QOS inference is a spec, not delivered runtime |
| IG-11 | **DEFERRED — NEW SCOPE APPROVAL** | Federated ontology inference is not index-local QOS semantics |
| IG-12 | **OPEN — PER RELEASE/PR** | Requalify on fresh SHA for affected consumers |

## Parallel PR ownership and freeze rules

1. **One owned interface, one integration decision.** The relevant contract-owning PR defines identity schemas, manifestation/codec extensions, logical relation schema, snapshot binding or cross-shard protocol; dependent PRs reference the approved commit/decision. Two agents may not independently freeze incompatible variants.
2. **Allowed overlap:** D01–D03 cluster interfaces with G0 test-oracle/design; D07 query orchestration with local adjacency cursor after IG-02/IG-04; D08 index/catalog type work with O1 ontology dictionary spec after IG-01/IG-03; independent tests and documentation can progress concurrently.
3. **Requires serialization:** D04/D14 writer fencing/GC/recovery against G1/O2 touching `manifest`, `CURRENT`, writer or compaction; D08/XJ logical query representation against G4 or O6; D15 release acceptance against changes to on-disk or network contracts. Land one owner change, then rebase and requalify consumers.
4. **Branch policy:** prefer small, mergeable PRs rather than three long-lived interdependent branches. A downstream PR may be planned while prerequisites remain open, but must not be marked implemented/accepted on a hypothetical API. Rebase onto fresh main and rerun affected gates.
5. **Milestone ownership:** D01–D15 retain distributed PR and release status, G0–G9 retain graph status, QOS O1–O6 remain tentative; **this integration register alone owns cross-cutting compatibility decisions and gate closure**. Do not duplicate independent implementation ledgers here.

### Mandatory decisions for unanticipated conflicts

| Observed condition | Authorized action |
|---|---|
| PR touches only isolated subsystem internals and no shared contract, all predecessors closed | Proceed with subsystem acceptance on fresh main |
| Shared interface still proposed/unstable | Implement reference oracle/prototype/docs only; **STOP** before freezing wire/codec/Rust public contract |
| Two approved plans require incompatible identity or query semantics | **STOP**, open explicit architecture amendment for both owners; no automatic preference |
| Writer/segment/manifest changes during D14/D15 proof window | Serialize after release or **STOP** acceptance and restart affected safety qualification on new SHA |
| Cross-shard graph write/read without qualified DG-P1/DG-P2 | Reject unsupported operation; **STOP** implementation path |
| QGS mapping requires unapproved QOS authority ledger | **STOP** graph→ontology mapping integration; local graph and independent asserted ontology may continue |
| Proposed cross-index inference uses independent QOS snapshots as one global truth | **STOP** and require explicit federation design; index-local joins only if separately validated |
| Multi-index join/exchange requested as v0.2 feature | Do not implement; log future XJ scope decision; v0.2 UNION boundary stays |
| No matching row above or test result ambiguous | **STOP**, report exact blocker, required decision authority and repeatable evidence; do not improvise |

## Contract-preserving example end-to-end milestones

**E1 — Distributed multi-index search (v0.2):** create two named indexes with same external document key, ingest through fenced shard writers, search both by bounded index selection, produce `(IndexId, DocumentKey)` results and exact supported global ordering/aggregates, stream gRPC + NDJSON, reproduce snapshot/partial error behavior. Does not need a graph engine.

**E2 — Standalone native graph:** create live vertices/parallel edges and an optional document association; commit, PIT, delete/recreate external key, read adjacency without resurrecting identities; run bounded traversal with cancellation and independently oracle-checked path semantics. No distributed service required.

**E3 — Standalone ontology:** register index-local classes/relationships, assert/retract canonical triples, infer effective relationships and constraints against pinned generation, confirm alternate proofs and last-support retraction, fail atomically on validation/budget exhaustion. No distributed fixpoint claimed.

**E4 — Local search/graph/ontology composition:** use typed query IR and explicit `NATIVE_GRAPH`/`ASSERTED_ONTOLOGY`/`EFFECTIVE_ONTOLOGY` relation source modes; verify document↔vertex incarnation mapping, parallel-edge bags vs canonical fact sets and no inferred native edge ID, full query budget and negative-completeness.

**E5 — Qualified distributed graph:** only after XJ exchange correctness and DG-P1/DG-P2, cross-shard frontier traversal on pinned graph-qualified vector with bounded fan-out, retry identity, stale projection handling, cancellation and fault-injection. Query-only joins across independently evaluated ontology sources are separate from distributed ontology entailment.

## Continuous validation and acceptance

- Keep local and distributed differential reference models independent from optimized code. Always include duplicate external keys across indexes; deleted/recreated incarnations; native parallel edges; asserted duplicate-set facts; inferred cycles/alternate proofs; exact anti-join negative vs budget failure; broken snapshot pins and late retry frames.
- Shared changes must be tested for v0.1 `quervant-core` standalone behavior, immutable PIT visibility, stored/typed/JSON correctness, serializer compatibility and local/RustFS parity. For distributed changes add actual etcd/ObjectStore, clock/partition/fencing, bounded RPC/network memory and failure cases.
- Preserve [TESTING.md](TESTING.md) >=85% production Rust line-coverage gate and full executed acceptance ledger; docs-only PRs do not claim executable proof.
- Each gate closes with explicit owner approval, change SHA(s), relevant tests and evidence, scope of guarantee, remaining limitations and downstream consumers that must requalify when the contract changes. Do not mark a gate PASS on rationale alone.

## Release/status register and next planning action

| Track | Current architectural status | Runtime claim in this PR | Next authorized planning action |
|---|---|---|---|
| Distributed D01–D15 / XJ-001 | Documented proposed v0.2 plan | None | Detailed D01 plan after fresh-main API inventory; inspect FP-002 risk before D04 |
| Graph G0–G9 / QGS-001–008 | Conceptual approval, execution unassigned | None | G0 identity/codec/IR compatibility review; plan isolated G1 local storage |
| Ontology QOS-001–004 | Conceptual approval, post-v0.1 | None | Prepare O1/O2 designs and QOS-003A/B/C mapping amendment boundary |
| Distributed graph/ontology | Post-v0.2 and safety-gated | None | DG-P1/DG-P2 proposals, later XJ-002–006; federated inference only after separate scope approval |

**Not authorized by this documentation PR:** runtime/format changes; merges of ontology and native multigraph authorities; new distributed transactions or globally atomic snapshots; implementation of QOS-005/QOS-008/QOS-009; moving joins/graph/ontology into v0.2; passing or waiving any required safety gate.
