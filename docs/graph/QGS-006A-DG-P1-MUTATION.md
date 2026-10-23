# QGS-006A / DG-P1 — Cross-shard graph mutation and referential integrity protocol

**Version:** 0.1-protocol-candidate | **Status:** proposed, NOT yet safety-qualified or implementation-approved | **Scope:** post-v0.2 distributed graph. This document expands mandatory gate DG-P1 from [QGS-006](QGS-006.md). The protocol is a design candidate subject to the proof and provider gates below.

## 1. Existing authority and non-negotiable constraints

- Reuse [distributed ingestion](../distributed/02-INGESTION.md), [topology](../distributed/01-TOPOLOGY-PLACEMENT.md), [FP-002](../distributed/06-SAFETY-PROTOCOLS.md) and [storage/GC](../distributed/05-STORAGE-GC.md). No second independent authoritative per-shard publication pointer or unfenced direct Search Node pointer writes.
- Existing `Indexing Coordinator` is stateless and per-shard batches are **not** globally atomic; graph operations requiring cross-shard integrity must pass through an explicitly qualified graph-mutation coordinator role (can be a recoverable logical protocol actor, not an assumption that the existing service already provides this behavior).
- ObjectStore immutable artifacts and installed writer epochs remain authoritative for shard generations; etcd lease expiry alone never fences publication.
- Each vertex has one stable owner; each edge is source-owned; reverse adjacency at target is derived, not an independently authoritative edge. Endpoints must be live under a qualified graph view; deleting a vertex never allows dangling visible edges. Graph identities never encode shard or node.

## 2. Proposed safety model: durable intent + staged publication + graph visibility qualification

We propose a *graph operation* G with immutable `graph_tx_id`, canonical payload fingerprint, routing epoch, participant list, base shard generations and expected vertex/edge revisions. Every participant has a per-shard **staged mutation** that is durable and query-invisible until a qualified graph publication point is established. Authoritative per-shard generations are still published only by existing Publication Authority; a staged graph mutation is not visible simply because one shard persisted it.

A durable **graph decision certificate** (commit or abort) is an immutable protocol record, not a new mutable per-shard CURRENT or independently authoritative index-generation pointer. The publication/qualification system must prove that graph-visible vectors include all necessary participant commits and exclude incomplete ones. Reader-facing graph qualifiers remain governed by DG-P2. A decision record by itself does not make data visible and is never a substitute for fenced per-shard publication.

**Compatibility gate:** whether staging + decision metadata can be encoded using current immutable manifest/Publication Authority without creating an alternate authoritative publication channel requires an explicit FP-002/GC-002 review. If not, reject this candidate before implementation.

## 3. Participants and ownership

| Operation | Authoritative participants | Materialized projections / notes |
|---|---|---|
| Create vertex | vertex owner | local-only unless coupled with document or ontology dependencies |
| Create edge U→V | owner(U), owner(V) validation participant | canonical edge and outgoing adjacency at owner(U), target incoming projection at owner(V) if enabled |
| Update edge property | owner(source) | may affect indexed/managed mapping dependencies; coordination scoped to affected owners |
| Delete edge | owner(source) plus target projection participant where required | retract source authority; reverse projection may be repaired asynchronously only with qualified read fallback |
| Delete vertex V | owner(V) plus all authoritative source owners of incident incoming edges | complete incident enumeration and source-edge retractions; includes self-loops and already staged graph changes |
| Recreate external key | vertex owner | new incarnation; no old edge rebinding |

For deletion, an exact incident-owner enumeration must be obtained from a **qualified complete incoming index** or a guaranteed-complete scan of authoritative edge ownership. An unqualified reverse projection must not be used to prove there are no incident edges.

## 4. Protocol phases (candidate)

0. **Admission:** validate canonical request digest and stable idempotency key, actor permissions, graph/routing version and resource budget. Persist immutable intent before acknowledging recoverable admission.
1. **Discover/read:** resolve endpoint incarnations, required participant owners and complete incident edges for deletion under a qualified graph snapshot; record precise expected revisions and routing epoch. Unknown participant set or exhausted enumeration fails closed.
2. **Reserve/conflict control:** acquire durable, fenced logical vertex lifecycle guards for all endpoint identities (canonical order). Edge creation acquires guards for BOTH endpoints; vertex delete holds a guard through resolution and decision. Guard tokens must survive coordinator failover, expire/recover only through proven fencing, and block concurrent conflicting lifecycle commits. A successful stale read alone is not sufficient.
3. **Prepare:** each participant verifies current writer epoch, expected revisions, guard validity and candidate constraint checks, then persists a staged, read-invisible mutation descriptor with digest and graph_tx_id. Responses include immutable prepare digests and base/produced generation references. If one participant rejects, abort and discard/reclaim staged state conservatively.
4. **Decision:** validate all required prepare receipts and guards; durably record an unambiguous COMMIT or ABORT decision, with participant set and digests. An ambiguous provider response must be reconciled by reading authoritative decision material and per-shard pointers. Never decide both ways.
5. **Install:** participants publish the required immutable data and generation references via fenced Publication Authority; replay installation idempotently. A committed decision may be **not yet graph-visible** if one participant is lagging. Graph reads must use only qualified vectors, not partially installed generations.
6. **Qualify/activate:** DG-P2 determines when the cross-shard dependencies and projections are satisfied and exposes a graph-consistent vector. No success claim at graph-visible level until qualification. Existing ACCEPTED/DURABLE/SEARCHABLE response levels require separate mapping; a mere decision certificate is neither graph-DURABLE nor graph-SEARCHABLE.
7. **Retire/reclaim:** release guards only after no conflicting edge creation/delete can leak across the cutover; retain intents, tombstones, staged records, generations and qualification metadata according to GC-002 retention barriers. Late replays must be harmless.

## 5. Conceptual state machine

```text
ADMITTED -> DISCOVERED -> GUARDED -> PREPARING -> PREPARED
                                                |      |
                                                |      +-> DECIDED_COMMIT -> INSTALLING -> QUALIFIED -> COMPLETE
                                                |      |
                                                +-------> DECIDED_ABORT -> CLEANUP -> ABORTED
```

After a durable decision, state is monotonic. Neither timeout nor leader failover may turn DECIDED_COMMIT into ABORT. An undecided prepared operation is resolved under durable coordination/fencing rules, not by independently guessing at each participant. Participants reject stale coordinator epochs and mismatched payloads.

**Open design gate:** deterministic resolution of prepared-but-undecided transactions during permanent coordinator loss, including guard recovery and liveness, must be specified and proved prior to implementation. This candidate is not claimed to provide fully proven atomic commit.

## 6. Edge creation vs vertex deletion race

If edge-create E(U,V) and DeleteVertex(V) overlap, lifecycle guards establish a serializable order:

- If E logically precedes deletion, deletion's exhaustive incident set includes E and retracts it.
- If deletion precedes E, E fails endpoint incarnation/revision validation.
- There is no valid ordering in which E commits as graph-visible while V is deleted without the corresponding edge retraction.

A publish/visibility barrier must bind that ordering across participants. A guard held only in process memory or relying only on etcd lease expiry is insufficient. Recreated external key V' is a different incarnation and E may never attach to V'.

## 7. Reverse projection maintenance

Target-local incoming records carry canonical edge identity, source owner, authoritative source generation/revision and projection provenance. They may be installed asynchronously. A read may consume them only when its pinned graph vector is covered by a **completeness watermark/certificate** that includes both adds and deletes. The watermark must not advance before source authority and target projection are durable and verified.

If reverse projection is unqualified, exact incoming queries either:
(a) perform a correct bounded query of authoritative source edges/owners, or (b) fail explicitly. No omission from a lagging projection; no use of stale projection records without authority validation.

## 8. Failures and recovery

| Fault / boundary | Required handling |
|---|---|
| Coordinator crashes before durable intent | no admitted durable operation; caller may retry stable operation ID |
| Crash after intent, before prepare | recover/retry or durably abort without graph effects |
| One participant rejects prepare | globally abort, staged data never graph-visible |
| Crash after some prepares | replay decision procedure; prepared records immutable and guarded |
| Ambiguous commit decision write | reconcile authoritative decision by digest/idempotency, never issue contradictory decision |
| Some shards install COMMIT, others unavailable | no graph-visible partial state; recover installation, or fail queries requiring newer graph view |
| Writer failover during prepare/install | new fenced writer reconciles graph intent, decision, installed generation and staging; stale writer rejected |
| Reverse projection lag | qualified authoritative fallback or explicit error |
| Snapshot pin expires / GC racing | retain dependencies or fail exact reads; no snapshot substitution |
| Duplicate/malicious replay | digest/revision/authority checked, no duplicate edge or double application |
| Coordinator+etcd partition | no new unsafe decisions or writer authority based on lease alone |
| High-degree vertex delete exceeds budget | fail atomically; no partial incident-edge retractions |
| ObjectStore corruption / missing receipt | fail closed, quarantine/recover from authoritative verified state |

Recovery must converge to one authoritative outcome and preserve graph-visible referential integrity. Staged records can be cleaned only after durable decision, qualified visibility/abort cleanup, and all reader/GC retention barriers.

## 9. Proof obligations and explicit unresolved questions

- **Safety S1:** no graph-qualified snapshot exposes an edge with a nonexistent/deleted endpoint.
- **S2:** each logical edge incarnation has at most one authoritative owner; duplicate retry changes no meaning.
- **S3:** vertex deletion and concurrent edge creation have a serializable lifecycle order.
- **S4:** source-authoritative outgoing and qualified reverse incoming edge sets are logically equivalent.
- **S5:** stale writer/coordinator cannot publish after fencing, including ambiguous CAS.
- **S6:** aborted or undecided staged mutations never become graph-visible.
- **S7:** support QOS enrollment/mapping only after its separate atomic validation protocol is approved; DG-P1 is NOT a distributed ontology transaction.
- **Liveness L1:** healthy participants can eventually complete commit/abort/qualification without holding guards indefinitely; fairness/timeouts and recovery rules must be specified.

Open before code: concrete durable coordinator/guard ownership and fencing; decision record CAS/serialization; linearization point and acknowledgment levels; graph operations with expanding participant sets; GC/retention ordering; topology/routing change policy; provider support and formal model. *These are mandatory unresolved design details, not implementation discretion.*

## 10. Qualification and STOP rules

Create a TLA+/PlusCal, Alloy or equivalently explicit state-transition model covering lifecycle races, ambiguous decisions, writer epochs, source/target projections, partial install and snapshot qualification. Define invariants and enumerate small configurations to find counterexamples; model checking alone does not replace provider integration.

Required tests: two/three shard concurrent create-edge/delete-vertex, self-loop and parallel edge, complete incident enumeration, create/delete/recreate, stable operation IDs, coordinator crashes at every phase, old-writer publication, decision ambiguity, delayed projection, consumer reads during installation, retention/GC, ObjectStore partition, real etcd and qualified RustFS CAS.

**HARD STOP:** No unrestricted cross-shard graph mutation, graph-DURABLE/SEARCHABLE claim, or exact graph traversal over such mutations until DG-P1, DG-P2, FP-002 and GC-002 qualification have passed.