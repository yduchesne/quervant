# Iceberg -> Quervant synchronization proposal (IS-001)

**Status:** PROPOSED, design only; no adapter or CDC feature exists in Quervant. See [integration overview](README.md) and [federated queries](FEDERATION.md).

## Consistency target and transport selection

**Default:** catalog/snapshot-driven indexing. The committed Iceberg table snapshot is the canonical input, while Quervant publishes a separately durable, derived index generation. No Kafka/Redpanda broker is required. Polling, catalog notifications or a lightweight event hint may trigger re-evaluation, but a hint is not the source of truth.

**Optional low-latency:** producer/CDC -> Kafka/Redpanda -> both Iceberg and Quervant. Distinguish a speculative event projection from a verified Iceberg-snapshot-equivalent index. Do not represent independent Kafka consumer offsets as a cross-system commit or assume event order and Iceberg commit order coincide.

**Do not** assume Iceberg snapshots provide a universally usable per-row CDC feed. Append scans and manifest changes do not fully describe row-level effects of overwrite, delete files, MERGE, compaction and rewrite. The reader must distinguish physical file maintenance from logical row mutation. Use a proven supported changelog/diff strategy or rebuild/reconcile the pinned snapshot.

## Source identity and mapping

The proposed source identity tuple is:

| Component | Purpose |
| --- | --- |
| catalog identity | Stable configured logical catalog namespace; never credential material |
| table UUID | Immutable logical source identity; table rename must not silently redirect |
| ref name + ref type | Explicit branch or tag selection, including branch move/rewind detection |
| snapshot ID + parent/ancestry evidence | Exact committed Iceberg state to index; numeric snapshot ID order is **not** a freshness or reachability order |
| Iceberg schema ID + mapping fingerprint | Detect incompatible schema/mapping changes |
| Quervant IndexId + target generation/vector | Exact derived search state; shard-qualified if distributed |
| operation epoch / checkpoint digest | Idempotent job ownership and recovery/provenance evidence |

Require an explicitly validated, stable **logical row key** for mutable tables (e.g. business event ID, not segment doc ID, Parquet file/row offset or partition position). Specify source key uniqueness and collision policy, null handling, duplicate rows, deletion-and-recreation and how a multi-column key is typed/encoded. Rewrites and compaction must not change logical document keys.

Use explicit column mappings and compatibility checks for field ID/type, schema evolution, nested values, null vs missing, timestamp/zone/precision, decimal precision, partition transforms, JSON and categorical analyzers. Reject incompatible mappings instead of coercing silently. Avoid treating Iceberg row lineage alone as a guaranteed stable key across every supported table format/version/engine without validation.

## Single-table initial sync state machine

1. **DISCOVER:** authenticated REST catalog lookup; obtain table UUID, selected ref, snapshot lineage, schema/spec and capability metadata. Validate exact source identity and configured mapping.
2. **PIN_SOURCE:** establish an availability/retention arrangement for the chosen snapshot for the job duration; absent such a guarantee, detect expiry and fail before claiming success.
3. **PLAN:** first sync builds a full-snapshot row view. Subsequent sync evaluates a validated incremental path only if the contiguous source history, supported operations, data/delete formats and stable-key rules are proven. Otherwise choose full reconciliation/rebuild or fail closed.
4. **STAGE:** apply bounded idempotent inserts/upserts/deletes against a *non-exposed candidate* index state. Every source row must be accounted for; apply deletes resulting from source net-state difference. Do not expose a partially synchronized generation under an exact/snapshot-complete label.
5. **VERIFY:** independent comparison/oracle for row keys and configured fields, source snapshot and mapping fingerprint; bounds and typed errors are enforced. On a large table, acceptance must specify a qualified proof/reconciliation mechanism, not rely on unqualified sampling for exact guarantees.
6. **PUBLISH:** durably commit the complete candidate Quervant index state under its existing publication authority. In remote mode, preserve the qualified ObjectStore CAS/fencing semantics. For distributed indexes, all required shards need a separately approved *visibility barrier* before one source-snapshot-complete view can be advertised.
7. **CHECKPOINT:** durably bind published index generation (or qualified shard vector) to exact table UUID/ref/source snapshot/mapping fingerprint. Verify the binding on recovery **before** advertising COMPLETE. Never claim a single atomic cross-Iceberg/Quervant transaction: the two systems have separate commit authorities.
8. **RELEASE:** release leases/pins only when no retained query needs them; retain enough provenance for query eligibility and recovery.

Suggested states: DISCOVERED -> STAGING -> VERIFIED -> INDEX_COMMITTED -> CHECKPOINTED -> COMPLETE. INCOMPATIBLE / SOURCE_EXPIRED / NEEDS_REBUILD / RECOVERY_UNPROVEN are explicit **non-serving** states. On restart, reconcile the source snapshot, verified index publication and durable checkpoint, then replay idempotently or fail. **The checkpoint cannot be advanced before the index state is safely published and bound to the source.** Exact placement of an embedded manifest marker vs external journal is an **open architectural decision**, requiring core storage owner approval if a persisted format changes.

## Change-handling decision matrix

| Observed Iceberg change | Authorized prospective action | Mandatory guard |
| --- | --- | --- |
| Initial table snapshot | Full source snapshot scan/build | Stable key, schema, deletes applied correctly |
| Contiguous append-only snapshot | Incrementally index newly visible logical rows | Prove no net row deletes/overwrites and no unsupported delete files |
| Pure file maintenance / compaction | No logical change, or reconcile source logical rows | Never delete docs merely because an old file disappeared |
| Copy-on-write overwrite or MERGE | Proven row-level before/after delta, otherwise rebuild | Stable-key diff; physical manifest diff alone insufficient |
| Position/equality/deletion-vector effects | Supported exact reader/changelog with verification, otherwise rebuild or STOP | No ignored delete semantics |
| Metadata-only schema/partition change | Revalidate mapping; reindex if affected | No silent loss of indexed fields or partition mispruning |
| Missing ancestor, expired snapshot or ref rewind | Rebaseline/rebuild if allowed; otherwise STOP | Never advance by comparing numeric snapshot IDs |
| Duplicate/reordered Kafka record or divergent sink commit | Idempotent replay/reconciliation; no snapshot-complete label | Event offset != Iceberg committed snapshot |
| Unsupported spec feature or incomplete reader behavior | STOP with typed compatibility error | Never return a partial source index as complete |

For rebuild, preserve current complete generation for existing pinned readers, stage the replacement separately, and atomically switch visibility using the existing **Quervant** publication contract; do not overwrite Iceberg's catalog pointer.

## Optional broker-assisted path

Redpanda/Kafka is suitable when a stream already exists or a low-latency subscription is a product goal. Use two clearly named read modes:

* **SNAPSHOT_COMPLETE (default):** only index state proven equivalent to a committed Iceberg snapshot is queryable as source-authoritative.
* **STREAM_PREVIEW (opt in, separate visibility/provenance):** search may include uncommitted-to-Iceberg or not-yet-reconciled events; clients must not treat this as an exact join source. Authorization, replay and data retention still apply.

Broker notifications may accelerate DISCOVER; they cannot substitute for checking the catalog and verifying a source version. Source offsets should be captured with event provenance where feasible, but a future watermark requires proven mapping to committed Iceberg state, not mere offset comparison.

## Operational and security requirements

* Secrets remain in external credential providers; redact catalog headers, signed URLs, table metadata containing sensitive properties, source row data and query literals in traces.
* Apply tenant/source ACLs and Iceberg row/column security at the *correct enforcement boundary*; a general-purpose Iceberg reader does not automatically replicate SQL-engine masking policies. Reject unsafe source/index mappings. Deletions and permission changes must invalidate exposed derived data as required by policy.
* One job-wide memory, scanned bytes, IO, concurrency and deadline budget; bounded Parquet/Arrow batches, backpressure, cancellation and retriable-error accounting.
* Metrics: table/ref UUID, current source snapshot, last verified indexed snapshot, lag measured from commit timestamps (clearly approximate), build/rebuild progress, rejected operations, retention alarms, checkpoint/visibility state, reconciliation failures.
* Do not use Quervant remote ObjectStore cache GC to manage Iceberg table files; ownership and retention are separate.

## Acceptance / proof obligations

1. Full snapshot rows and every selected indexed field exactly match an independent reader oracle, including null/missing/array/decimal/temporal values.
2. Repeated sync, crash at every state boundary and reordered notifications never lose, duplicate or expose uncommitted logical source rows.
3. Append, overwrite, update, equality/position delete, compaction and mixed rewrite cases compare with full source snapshot, or are rejected/rebuilt according to the matrix.
4. Table rename/recreate, branch rewind, snapshot expiry, schema/partition evolution and unstable/duplicate logical keys produce correctly scoped typed errors.
5. Remote RustFS-backed generation and checkpoint recovery passes real-backend fault injection; staged generation cannot be mistaken for complete.
6. For distributed follow-on, multi-shard visibility and source-snapshot equivalence require independent proof; individual shard commits are not a global barrier.
7. Kafka gap, reorder, duplicate, retention loss and Iceberg sink failure do not masquerade as snapshot-committed consistency.
8. Security checks cover denied source/field/row, redaction, revocation and derived-index leakage. Fail closed if enforcement equivalence cannot be established.
9. Apply repo [TESTING](../../TESTING.md) requirements and the mandatory [detailed PR authoring guide](../../DETAILED_PR_PLAN_AUTHORING_GUIDE.md) to every future code PR. This documentation PR executes no such proof.

## External technical references

* [Iceberg table specification](https://iceberg.apache.org/spec/) — snapshot/manifest/ref and row-level delete semantics.
* [Iceberg REST catalog protocol](https://iceberg.apache.org/docs/latest/rest-protocol/) — catalog authority and conditional commits.
* [Apache iceberg-rust](https://github.com/apache/iceberg-rust) — prospective Rust catalog/scan APIs; audit feature coverage and MSRV at planning time.
