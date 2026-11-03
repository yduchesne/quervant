# Iceberg integration — architecture and staged roadmap

**Status:** PROPOSED design, documentation only (2026-11-02). No runtime integration, code dependency, wire protocol, source-version support, or release assignment is approved or implemented by this document.

## Purpose and system boundaries

Apache Iceberg is an open analytical **table format**, catalog/snapshot protocol and file metadata model, not a search engine or a standalone query executor. Quervant is the indexed retrieval engine; it retains its own immutable segment codecs, manifest/CURRENT publication authority, PIT readers, mutation semantics and standalone core. The integration is **complementary, not replacement storage**.

* **Iceberg owns** canonical table data, branch/tag references, snapshot history, schema/partition evolution and Iceberg data files.
* **Quervant owns** derived search indexes, document keys, lexical/typed/JSON/temporal/geospatial search execution and its own committed generations.
* **A proposed optional adapter** owns source mappings, snapshot synchronization, correctness/recovery checkpoints and federated-query bindings.
* **An optional SQL layer** (evaluate Apache DataFusion + its Apache Iceberg integration) owns SQL parsing and ordinary relational execution for a proof of concept; it does not supersede Quervant's approved/proposed native higher-level query IR.

Do **not** place Iceberg or DataFusion dependencies in quervant-core. A tentative standalone connector crate/binary name is **quervant-iceberg**; it is not an established crate. External adapters must not introduce a second Quervant durable publication pointer or write Iceberg data under Quervant's own segment prefix.

## Integration modes

| Mode | Data flow | Authority | Initial recommendation |
| --- | --- | --- | --- |
| Snapshot-derived index | Iceberg snapshot -> selective Quervant index | Iceberg source; Quervant derived search | Default |
| Streaming-assisted index | Producer/CDC -> Redpanda/Kafka -> Quervant and Iceberg | Acknowledged source event and Iceberg committed state must be distinguished | Optional when latency requires it |
| Federated read | Quervant indexed matches <-> Iceberg table scan/hydration | Independently pinned versions with explicit consistency mode | Prototype with DataFusion |
| Analytics export | Quervant results -> Iceberg writer/query engine | New Iceberg table commit via supported writer | Later, independent work |

**Never** mistake Kafka offsets for Iceberg snapshot commits, file rewrites for logical row deletes, or a vector of independent Quervant generations for an atomic global transaction.

## Architectural authorities

* [Quervant core architecture](../../ARCHITECTURE.md), [cross-release roadmap](../../ROADMAP.md) and [testing](../../TESTING.md): core release and correctness rules.
* [XJ-001](../../distributed/10-CROSS-INDEX-FOUNDATION.md): v0.2 higher-level typed scan/UNION foundation, stable index-qualified identity, snapshot vectors, budgets and **no executable distributed join**.
* [C1–C7 query architecture](../../distributed/03-QUERYING.md), [streaming](../../STREAMING_SEARCH.md) and [distributed streaming](../../distributed/07-STREAMING.md): pushdown, pinned generations, global accounting and truthful terminal completion.
* [QGS-005](../../graph/QGS-005.md): eventual search/graph binding relations and joins; [cross-subsystem integration roadmap](../../INTEGRATION_ROADMAP.md): shared IR and gate ownership.
* [Source synchronization proposal](SYNC.md) and [federated query proposal](FEDERATION.md) in this directory: **external-adapter prospective design only**. These documents do not amend the preceding authorities.

## Implementation sequencing (independent prospective I-series; not GitHub PR numbers)

| Work item | Deliverable | Must be demonstrated before proceeding |
| --- | --- | --- |
| I0 | Review/approve source identity, snapshot, security, adapter capability and consistency contract | Open decisions in SYNC/FEDERATION resolved; independent oracle plan |
| I1 | One-table, one-snapshot read-only import into standalone core | Stable keys, pinned source snapshot, complete snapshot comparison; no distributed dependency |
| I2 | Validated append-only incremental sync and crash/retry recovery | End-to-end source-vs-index parity and provenance checkpoint qualification |
| I3 | Mutable-table snapshot reconciliation and schema/partition evolution | Deletion/update/rewrite oracle parity, retention and rewind failures |
| I4 | Optional Redpanda/Kafka hints/dual fan-out and low-latency projection | Clear visibility policy; lag tracking, missing/reordered/duplicate events |
| I5 | Standalone DataFusion Quervant source + Iceberg provider proof of concept | Snapshot-aligned search/hydration and filtered joins, no unsafe limit pushdown, policy parity |
| I6 | Federated optimization and later native/distributed binding relation integration | Explicit post-v0.2 XJ-002+ authorization, global resource and snapshot safety proofs |

I1–I5 can be proposed and prototyped without redefining v0.2 as a SQL/joins release; any production scope still requires its own approved detailed implementation plan. I6 cannot be smuggled into XJ-001; graph/ontology relation sources remain subject to their independent QGS/QOS gates. Export from Quervant to Iceberg is another prospective workstream, not a prerequisite for I1–I6.

## Decisions to close at implementation planning

1. Target Iceberg format versions, row-level delete encodings, reference types and concrete Rust API support: **unapproved**; do not presume full v2/v3 compatibility from a crate name.
2. Reliable stable row key and source-to-index field mapping, null/missing/decimal/timestamp semantics, schema evolution: **unapproved**.
3. Safe version/checkpoint representation and per-shard visibility barrier for distributed indexes: **unapproved**.
4. Pinning/retention arrangement for query-duration Iceberg snapshots and matching Quervant generations: **unapproved**.
5. DataFusion dependency compatibility, provider pushdown contract, UDF/table-function semantics and security enforcement: **to be proven by prototype**.

Where a decision is not approved or a reference oracle cannot establish equivalence, the future implementation must **STOP rather than silently degrade correctness**.

## External references (evaluated as candidates, not dependencies)

* [Apache Iceberg specification](https://iceberg.apache.org/spec/)
* [Apache Iceberg REST Catalog specification](https://iceberg.apache.org/rest-catalog-spec/)
* [Apache iceberg-rust](https://github.com/apache/iceberg-rust)
* [Apache DataFusion](https://datafusion.apache.org/)
* [Apache datafusion-iceberg](https://github.com/apache/datafusion-iceberg)

**Documentation PR verification:** navigation and relative link inspection only. No Rust code, runtime integration, feature tests or benchmark measurements are claimed.
