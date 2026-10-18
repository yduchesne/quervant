# Quervant architecture (design targets)

> This document records intended architecture, not implemented features.
>
> **Implemented (PR 2, contract-only):** a validated contract layer for logical
document identity, typed field values, schema/field options, the typed query IR
(including the conservative A14 polygon rules), aggregation/sort/projection/PIT/
cursor shapes, resource budgets, capability negotiation, typed errors and
first-class ordered batch request/response contracts now exists in
`quervant_core::contract`. It validates shapes and types only; no indexing, query
execution, durable storage, PIT reader, ObjectStore, distributed or vector
runtime is implemented by it.

## Release boundaries

- **v0.1:** standalone single-index/single-shard lexical core, including analysis, BM25, Boolean/phrase/prefix/glob/regex search, immutable segments, commit/recovery, and ObjectStore cold bootstrap. No cluster runtime dependencies.
- **v0.2:** multi-shard distributed lexical search built on the unchanged standalone core, with Coordinator/etcd, separate Query Aggregator and Search Nodes, placement and rebalancing.
- **v0.3 target (post-v0.2):** vector fields, exact KNN, ANN/HNSW, metadata-filtered vector retrieval, and hybrid BM25/vector fusion. Vector support is **not a delivery requirement for v0.1 or v0.2**.

See [docs/ROADMAP.md](ROADMAP.md) for release acceptance boundaries.

## First-class temporal retrieval (v0.1 design target)

Quervant is a **general-purpose lexical search engine** with first-class timestamped-event/log retrieval, not a specialized time-series database. This requirement is part of the v0.1 architecture, although PR 1 only documents it.

- Support typed UTC-normalized timestamp fields (precision and conversion semantics to be fixed in the field/schema contract). An index can designate an optional **primary time field**; indexes without one remain fully supported.
- Support indexed half-open time-range predicates `[start, end)`, combinations with term/Boolean/exact filters, ascending and descending timestamp order, bounded top-K results, and deterministic cursor pagination with a stable tie-breaker.
- Support **minimal time-series analytics**: exact counts, fixed-duration time buckets, and numeric sum/min/max/average within documented type/overflow/empty-bucket semantics. Do not require a SQL language; these are typed query/aggregation API requirements. High-cardinality group-by, percentiles, moving windows, rollups and downsampling are deferred.
- Distinguish **event time** from ingestion time; late arrivals, out-of-order timestamps, duplicate timestamps, missing timestamps and deletes/updates must preserve query correctness.
- Every immutable segment records the primary field's minimum/maximum timestamps and whether timestamps are physically ordered. Time-oriented indexes default to timestamp-sorted segments, subject to documented buffering/merge and write-amplification limits; other indexes may leave documents in ingestion/index order. Per-segment layout metadata enables mixed generations and future strategies.
- Define optional block-level timestamp bounds and time-to-document lookup structures during format design. **Segment pruning is required for v0.1**; block skipping is required when a time-sorted block layout is implemented, not assumed beneficial for unsorted blocks. Avoid one remote object per small time interval/block.
- The query planner must be able to consider **time-first** scans versus **postings-first** retrieval, with correctness independent of strategy. Establish an initial deterministic strategy and measure workload selectivity before adding adaptive cost-based planning.
- Preserve consistent internal doc-ID remapping for physically sorted writes and merges across postings, term positions, stored fields, deletes and all other per-document structures.
- Shared segment codecs and manifest semantics apply to local and remote deployments. Timestamp bounds allow pruning **before ObjectStore materialization**. v0.1 may use whole-file bounded caching; reserve stable access boundaries for future ranged reads and partial cache without claiming they are implemented.
- Define timestamp timezone/precision, null treatment, stable ordering, time-bucket boundaries, resource limits and format compatibility explicitly before freezing index/query contracts.

Acceptance must cover event-time range boundary behavior, inclusive/exclusive edges, ascending/descending order, pagination tie-breaks, filter conjunctions, bucket/numeric aggregate correctness, out-of-order/late events, deletes/merges, manifest pruning, and local as well as RustFS cold-cache recovery. Benchmark recent-window selective queries and time-bucket scans alongside lexical workloads; measure bytes fetched, segment/cache touches, latency and memory, without assuming savings in advance.

## Native JSON and geospatial indexing (v0.1 design targets)

Quervant uses **one general-purpose typed document model**, shared by lexical, numeric, temporal, JSON and geospatial retrieval. JSON is a first-class ingestion/return format, not a required representation for non-JSON clients. PR 1 records contracts only; no JSON or spatial query engine is implemented here.

### Native JSON and forward compatibility

- Preserve full source JSON faithfully, including nesting, array order, scalar types, explicit null versus missing values, and values needed for future projections/transformations. Specify whether byte-for-byte source preservation or semantic JSON preservation is promised before implementation.
- Extract configured and selectively discovered JSON paths into typed index fields (keyword/text, Boolean, integer/float, timestamp, geographic point); enforce limits on path count/depth, array cardinality, document size and index expansion. Define conflicts when a path has different types across documents/segments.
- Compile an explicitly documented **RFC 9535-inspired, indexable JSONPath subset** into the shared typed query IR; do not scan and reparse every stored document for routine predicates. Initial indexed operations: nested scalar path equality/ranges, existence, scalar-array membership, conjunction, and sorting by indexed scalar paths with specified missing/null/multivalue semantics. JSONPath itself does not define sorting or aggregations; model these as separate operators.
- Preserve structural identity for nested arrays: path ancestry, parent-child relationships and array element positions must be recoverable from retained JSON. **Do not infer correlated-array predicate matches from independently flattened field postings.**
- Define extensible typed query IR and execution-stage contracts for future **correlated nested-array predicates**, **recursive JSONPath selectors**, and **JSON projections/transformations**. These are deferred execution features, not v0.1 promises. A future structural index may be added as a versioned optional segment capability; older segments must remain semantically accessible via a bounded correct source-document evaluator or explicitly supported reindexing/migration policy.
- Keep logical document identity distinct from physical segment doc IDs; sorting/merges must remap every associated field, structural and stored-value reference consistently. Segment format versions and capability metadata must distinguish present index structures; do not promise equal performance for older segments.

### Geospatial field and query model

- Define a typed `GeoPoint` in **WGS84 (longitude, latitude)** with explicit GeoJSON Point ingestion, validation of coordinate bounds/nonfinite values and unambiguous units. Retain source GeoJSON for later geometry types. Future geometry type identifiers/codecs must accommodate LineString, Polygon, MultiPolygon and spatial relations without encoding everything as two unrelated numeric fields.
- **v0.1 point queries:** bounding-box (including antimeridian crossing), radius/distance filtering with stated geodesic precision, distance-based top-K ordering with deterministic ties, and point-in-polygon (candidate pruning plus exact predicate). Define boundary inclusion, poles, invalid/self-intersecting query polygons and numerical tolerances before implementation.
- Keep spatial predicates in the common typed query IR so spatial candidates can intersect with lexical postings, JSON filters and temporal ranges. Physical spatial access remains pluggable: an immutable segment-local BKD-like 2D point index or hierarchical cell postings with exact verification; select the initial implementation through benchmark/complexity evaluation, not an implicit format commitment.
- Store exact/precision-defined coordinates for verification and distance sorting, with segment-level conservative geographic bounds for pruning before remote materialization. Bounds and candidate generation must not produce false negatives, including antimeridian cases.
- Permit multi-valued geospatial fields and preserve JSON array-element identity for future correlation of location/time/attributes within the same nested event. Rich geometry intersection/containment, geometry indexing, spatial grids/aggregations, and spatial joins are deferred; their type/query/codec extension points are required in v0.1.
- Share immutable segments, format-version/capability metadata, ObjectStore durability, bounded cache and query planning with temporal/JSON fields. Do not require geographic physical sorting or create small remote objects for each spatial cell.

**Pre-format design gate:** document field schema and coercion, JSONPath subset grammar, structural preservation and compatibility policy, typed query IR, geo coordinate/geometry semantics, spatial index choice and conservative pruning rules, source/stored-value access, sorting/tie/null rules, resource budgets, and segment codec capability/version policy. Benchmark time+geo+JSON compound predicates and cold RustFS pruning without asserting performance gains until measured.

## General-purpose search primitive architecture gate (before segment format freeze)

Quervant is a **general-purpose search engine**, not an append-only log engine. Structured events and logs are important workloads, but must not constrain document mutation, relevance ranking or standalone embedded/local use. The following are design contracts for follow-on PRs; PR 1 remains documentation/foundation only.

### Document identity, mutation and visibility

- Separate caller-visible stable logical document key from ephemeral segment-local doc IDs. Specify namespace, uniqueness, duplicate-key policy and deterministic upsert behavior; preserve logical identity through flush, merge, relocation and reopen.
- Support inserts, idempotent key-based upserts, replacement updates and logical deletes in v0.1. Represent obsolete versions/deletes through versioned live-document state or tombstones; compaction reclaims them only when no pinned reader needs the old view. Do not require in-place modification of immutable segments.
- Define sequence/version ordering and conflict resolution for repeated writes, retries and out-of-order operations. A delete followed by an upsert must have unambiguous visibility and recovery behavior.
- Distinguish **refresh** (makes acknowledged indexed changes visible to newly opened readers) from **durable commit** (atomically publishes a recoverable manifest and referenced segments). Specify acknowledgment/durability guarantees and crash recovery before implementing APIs.
- Point-in-time (PIT) readers pin a consistent manifest/live-doc generation; cursors bind to that snapshot plus complete sort keys and a stable tie-breaker. Define expiry, resource budgets, reopen semantics and behavior when a cursor's snapshot has been released.
- Segment merges, deletion reclamation, retention expiry and remote object garbage collection must respect active readers and the authoritative committed manifest. Retention is a policy-driven lifecycle operation, not a hidden consequence of timestamp filtering.

### Shared typed fields and index structures

- Establish a versioned field descriptor with logical type, cardinality, analyzer/normalizer, indexed/stored/columnar capabilities, JSON path/ancestry when applicable, spatial coordinate metadata and null/missing behavior. Mixed types, numeric precision, schema evolution and multi-valued sorting require explicit semantics.
- Provide a DocValues-like **typed per-document columnar value contract** for deterministic sorting, basic stored-field selection/projections, numeric and timestamp aggregation, and distance ordering. Specify encoding, doc-ID remapping, missing-value sentinels, multivalue selection, merge and local/remote read behavior; do not equate column values with inverted postings.
- Text fields require positional postings (and documented offset/position policies) for phrase queries and future proximity/highlighting. Keyword, Boolean, numeric, timestamp, JSON and geographic fields share the document identity and live-doc visibility model.
- Efficient postings intersection, skip/block metadata and safe segment/block pruning are execution requirements. Plan an optional block upper-bound statistics/codec extension for WAND or block-max WAND, without requiring those algorithms in the initial v0.1 implementation.
- Format and manifest versions must advertise optional codecs and capabilities; unknown required features fail explicitly. Maintain reader/writer compatibility policy, upgrade/reindex strategy and golden-fixture tests before format freeze.

### Streaming search and composable result pipelines

Quervant's standalone query engine must preserve the ability to deliver bounded result batches incrementally for streaming-compatible plans, without whole-result materialization. Pull-based flow control, cancellation, reader/PIT consistency, explicit ordering and terminal error reporting are first-class execution requirements. Distinguish engine result iteration from network streaming and client-side Unix-like pipelines. Blocking operators (e.g. global sort, exact top-K and global aggregation) must retain correctness and bounded budgets; they need not deliver final results early. PR 5 must preserve incremental segment/postings/columnar/stored-field access; PR 14 owns the initial core result-cursor execution contract. See [Streaming search and composable result pipelines](STREAMING_SEARCH.md) for ownership, semantics, future UI scope and acceptance scenarios.

### Unified query IR, execution and safety

- Use one typed query IR for lexical ranking, Boolean filters, numeric/time ranges, JSONPath-compiled predicates, geographic predicates, sorting, bounded aggregation and **basic field-selection projection**. Selecting stored fields is v0.1; arbitrary JSON restructuring/transformation remains deferred.
- Define filter-vs-score behavior, relevance score and deterministic tie rules, missing/null sort order, multi-valued field sort selectors, pagination/search-after semantics and PIT binding. Preserve consistent results across merges and storage backends.
- Support a deterministic correctness-first execution planner with index-driven candidate generation, intersection, optional time/spatial pruning and bounded top-K. Instrument plan choices and bytes/segments touched. Cost-based planning and WAND variants are future optimizations, not required to satisfy v0.1 correctness.
- Bound query execution by configurable limits (candidate count, multi-term expansion, regex automata/work, scanned bytes, memory, result window, timeout/cancellation, aggregation buckets, JSON depth and spatial complexity). Specify explicit resource-exhaustion errors and avoid unbounded full-source scans.
- Future fuzzy search, facets, highlighting, autocomplete, substring indexing, recursive JSONPath, correlated nested-array predicates and rich geometry require reserved operator/codec extension points; their full execution is not a v0.1 requirement.

### Workload policies, not separate engines

- **Append-oriented event profile:** optional primary event timestamp, late arrivals, timestamp-oriented segment layout, time-based retention, time-first pruning and ingestion-oriented flush/merge defaults.
- **Mutable document profile:** stable keys, update/upsert/delete, relevance-oriented access, PIT consistency, flexible indexing and merge defaults.
- Profiles select policies (schema discovery, indexing, layout, flush/merge, cache and retention) but **never alter query correctness, document identity or durability semantics**. Both use the same standalone `quervant-core` API, codecs and manifest lifecycle; neither depends on distributed services.
- Benchmark cost, indexing throughput, p50/p95 latency, read amplification, memory, object-store operations and recovery against relevant Tantivy/Lucene baselines and, where comparable, Quickwit. Do not assert differentiation or superior performance without measurements.

**Design gate before implementing immutable codecs:** approve stable document identity/mutation order, refresh/commit/PIT semantics, field and columnar value contracts, query IR and projection semantics, live-doc/tombstone/retention lifecycle, format compatibility, workload policy boundaries and query resource budgets. Keep v0.2 distributed and post-v0.2 vector milestones unchanged.

## Network-address and bounded aggregation primitives (v0.1 design gate)

These are **general-purpose typed search capabilities**, motivated in part by SIEM/security logging but not coupled to a security-specific schema, rule language or detection engine. They are v0.1 design and acceptance targets, **not implemented features**.

### IP address indexing and predicates

- Define distinct typed `IpAddress` (IPv4/IPv6) and `IpNetwork` (address family plus canonical prefix length). Index exact address, address ranges, `IN CIDR` and `NOT IN CIDR` predicates; reject mismatched or malformed address literals with typed errors.
- IPv4 and IPv6 use an explicit canonical binary ordering and family separation; do **not** silently treat IPv4-mapped IPv6 addresses as IPv4 unless a documented normalization policy explicitly opts in. CIDR matching is mathematical prefix membership, **not** geospatial proximity or textual prefix matching.
- Specify indexed/storage/DocValues representation, multivalued address fields, missing/null behavior, prefix-length validation (IPv4 0–32, IPv6 0–128), range bounds and merge/reopen stability before the segment format is frozen.
- Support composability with Boolean, JSON, time and lexical predicates. An IP field is not a GeoPoint; geolocation enrichment is external or a separately stored geo field.

### Bounded grouped and distinct aggregations

- Extend typed query/aggregation IR with `GROUP BY` one or more indexed/columnar scalar fields and bounded `COUNT`, `SUM`, `MIN`, `MAX`, `AVG` over eligible numeric fields. Define group key typing, missing/null handling, multi-valued membership and deterministic group ordering.
- Support exact `COUNT(DISTINCT field)` and top-K frequent field values with deterministic tie-breaking. Specify whether repeated values in one multivalued document count once or multiple times; prefer per-document distinct membership unless an explicitly named occurrence-count operation is introduced.
- Set configurable maximum groups, distinct keys, per-query memory, output size, timeout and cancellation. Exhaustion must produce an explicit typed error, **not silent truncation or incorrect exact counts**. `TOP K` is a separately requested bounded ranking of frequencies, not an implicit cap on an otherwise exact grouped result.
- Aggregations operate over the query's matching **live documents in a defined reader/PIT snapshot**, respect all filters and deletions, and produce identical logical results across local/RustFS modes and merges. Where group cardinality exceeds budgets, fail deterministically or require a documented explicit approximate operator in a later release.
- Preserve an extension point for approximate cardinality (e.g., HLL), precomputed/materialized aggregation indexes, sliding windows, temporal sequences, joins and continuous detection; **none is required in v0.1**.

### Universal typed field predicates

- Define `EXISTS`, `MISSING`, `IS NULL`, `IN` and `NOT IN` across eligible typed fields, not only JSON paths. Clarify three-valued/missing semantics, empty arrays, repeated values, incompatible types, and negation. `NOT IN` must not accidentally match missing/null fields unless explicitly specified by the approved query contract.
- Define membership over typed values rather than string coercion, and ensure the same predicate semantics for indexed scalar fields and supported JSON scalar paths.
- Reserve typed IR nodes for future temporal correlation, cross-index lookups and continuous queries without implementing detection-specific execution.

**Pre-format gate:** PR 2 must approve IP address encoding and query semantics, grouped/distinct/top-K IR and resource-budget/error behavior, and universal field predicate truth tables. PR 5 owns columnar/index encoding; PR 10 owns typed aggregation execution; PR 14 owns compound integration; PR 15 owns evidence and benchmarks.

## Separation of concerns

- **Core**: a self-contained index writer/reader/searcher, immutable segments, postings, scoring, manifests, refresh, and recovery.
- **ObjectStore adapters**: provider-independent operations, including streamed/ranged reads, durable writes, and explicit capabilities. S3-compatible adapters should support RustFS and AWS S3; additional providers may follow.
- **Distributed**: shard identity and routing, control plane, query aggregation, and search-node hosting.

Dependency direction: `quervant-distributed -> quervant-core`. The core must never depend on the distributed crate. Storage contracts must remain usable without distributed infrastructure.

## v0.1 decisions: standalone lifecycle and release gates

**Agreed design targets (not implemented by PR 1):** v0.1 supports both **fully local durable indexes** and **remote ObjectStore-backed indexes**. They share segment codecs, manifest representation, generation semantics, reader visibility, indexing, and search execution; durability/publication mechanisms differ. A local-only index must not require a running object-storage service. A remote-backed index treats remote committed state as authoritative and local materialized segments as disposable.

Use **one logical writer per index**, concurrent readers, immutable committed segment generations, and explicit refresh/commit visibility. Define update/delete semantics, background merges, old-reader retention, and crash recovery in the v0.1 lifecycle contracts. Version on-disk/on-object formats from the outset, but do not promise cross-version compatibility until explicitly specified.

Before implementation PR decomposition, finalize document/field schema, writer/reader/searcher API and lifecycle, query/analysis feature acceptance, local and remote commit publication and recovery, cache limits, and synchronous hot-path versus asynchronous I/O boundaries. Measure correctness and performance against a reproducible baseline (including Tantivy on equivalent data and hardware), without promising performance superiority.

### RustFS-first remote validation and portability

Use **RustFS as the first remote ObjectStore reference implementation**, accessed through the **S3-compatible API**, not RustFS-specific engine hooks. The remote `ObjectStore` interface must describe capabilities and failure semantics needed by the engine; avoid relying on provider-specific atomicity, conditional writes, or listing consistency without verifying them. A portable adapter must permit future S3-compatible and other remote providers without changing index formats or search logic.

Start with **whole-file immutable segment materialization** to a bounded local cache; validate integrity before exposing cached files to readers. Eviction and re-download are cache operations, never deletion of authoritative objects. Treat remote segment garbage collection separately, subject to committed-manifest retention and reader safety. For v0.1 PR 13, support **parallel ranged whole-object download** and concurrent independent segment materialization where the provider advertises range-read capability. A segment remains invisible until every range is assembled and the complete object passes length and SHA-256 verification followed by atomic local promotion. Fall back to a single bounded GET when ranges are unavailable or unsuitable. Bound connections, concurrent GETs, bytes in flight, memory and temporary disk, and cancel/clean up incomplete fills. PR 3 specifies optional range-read contracts; PR 13 implements the download scheduler and production RustFS adapter. **Partial caching, predictive prefetch and swapping refinements remain deferred** pending workload measurements; ranged transfer is not partial caching.

RustFS-backed acceptance/fault-injection scenarios must cover: empty-cache reader bootstrap; warm-cache reuse; cache eviction and re-materialization; multiple concurrent readers; committed-manifest visibility only after all referenced objects are durable; restart/recovery; network timeout, interrupted/partial download and corrupted object handling; bounded disk/memory usage; and provider portability. Remote commits must never expose incomplete generations. Define local durable commit and remote publication protocols separately while retaining shared logical generation/visibility rules. Do not assume local atomic rename is durable without synchronization, or that an S3-compatible provider offers atomic compare-and-swap without explicit verification.

### Remote mode: authority, CAS publication and cache ownership (PR 13)

PR 13 adds an opt-in remote-backed single-shard index (`quervant_core::remote`) without changing any persisted format. It reuses the existing immutable segment/manifest/`CURRENT` v1 codecs, the existing local single-writer lifecycle and the existing verified `SegmentCache`.

- **Authority.** In remote mode the ObjectStore is authoritative. The committed `index/CURRENT` pointer alone selects the generation; there is no listing or older-generation fallback. A malformed `CURRENT`, a corrupt manifest, or a missing referenced object is a typed failure.
- **Publication ordering.** A remote commit uploads the candidate's immutable, content-addressed segments, then the mutation-state sidecar, then the manifest, each with create-if-absent, and persists `index/CURRENT` **last** with a provider-enforced CAS precondition. Immutable objects are never overwritten: an existing byte-identical object is idempotent, and different bytes under the same key are a typed conflict. No orphan is deleted on failure; online remote garbage collection remains deferred.
- **CAS and the digest/ETag contract.** S3 `If-Match` compares the object ETag, which is not a content digest. `PutPrecondition::IfMatch(ContentDigest)` is implemented as: HEAD the current object to capture its ETag, GET the current bytes bounded and independently verify their SHA-256 equals the caller digest, then issue a conditional PUT with the captured ETag. The conditional PUT — not the preceding HEAD/GET — is the atomic guard. An ETag is never interpreted as a SHA-256 digest. `IfAbsent` issues a genuine atomic `If-None-Match: *` PUT; a 412 is resolved by reading the existing object and returning idempotent success for identical bytes or a conflict otherwise. Capabilities are advertised only for an endpoint qualified by a real concurrent probe; an unqualified endpoint advertises no capabilities and fails closed.
- **Writer workspace and fencing.** The remote writer hydrates the authoritative base into a **private** local workspace, runs the existing `IndexWriter` there, and tracks the remote base separately. Because the local `CURRENT` advances before remote CAS, any remote publication failure makes the writer terminal (`RemoteConflict` or `RecoveryRequired`) and requires a fresh authoritative reopen. Local writer locks are workspace cooperation only, never remote authority. Ambiguous CAS outcomes are reconciled by re-reading `CURRENT`: candidate present and complete means reconciled success; base unchanged or unreadable means recovery required; another pointer means conflict.
- **Reader and cache ownership.** The reader resolves remote `CURRENT`, verifies the manifest and mutation state before any segment download, then materializes each segment through the existing `SegmentCache` admission/coalescing/atomic-promotion path. Hit/follower/leader election and disk admission happen **before** any remote fetch: a cache hit issues zero GETs, a coalesced follower waits, and only the elected leader downloads. The leader streams whole-GET or parallel ranged responses directly into a cache-owned staged file (no full-segment `Vec`, no all-chunk collection); the aggregate retained response bytes are held by RAII byte leases until each chunk is written, and only become visible after exact-length and full SHA-256 verification followed by an fsync + atomic promotion. The cache remains the sole owner of admission, disk accounting, temp cleanup, coalescing and eviction. Eviction never deletes authoritative remote objects, and pinned readers keep their entries live. Scoring performs no remote I/O.
- **Retry timing.** Transient transfer failures are retried with a bounded capped exponential backoff (100 ms, 200 ms, ... up to 2 s) through the `Sleeper` seam. The production implementation (`TimerSleeper`) uses the runtime-neutral `futures-timer`, which lazily starts one global timer thread only when a retry is scheduled, so local-only builds that never retry spawn no runtime or thread. Deterministic tests inject a virtual sleeper.
- **Deferred in PR 13.** Query-scoped pre-materialization pruning of segments requires a planner-contract amendment and maintainer approval; its approval/tracking status is recorded in `docs/pr-artifacts/pr-13/`.

## Persistence and caching

ObjectStore is authoritative for committed segment files and manifests. Segments are immutable; commit manifests reference verified durable objects. Local disk is a disposable workspace/cache. Reader bootstrap must work with an empty cache using only the committed ObjectStore state.

Illustrative object keys within an index prefix:

```text
indexes/<index-id>/
  index.meta
  shards/<shard-id>/
    CURRENT
    manifests/<generation>
    segments/<segment-id>/...
```

The precise commit-pointer and atomic publication protocol remain to be specified; CAS/fencing must be enforced for writer failover. Cache eviction must not affect correctness.

## Local Directory and segment-access contracts

**Planned abstraction; API signatures are illustrative and not yet implemented.** Following Lucene's directory concept, `quervant-core` will expose a local `Directory` contract to separate index-file lifecycle and access from a concrete local filesystem implementation:

```rust
pub trait Directory {
    fn open_read(&self, path: &str) -> Result<...>;
    fn create(&self, path: &str) -> Result<...>;
    fn delete(&self, path: &str) -> Result<()>;
    fn atomic_write(&self, path: &str, data: &[u8]) -> Result<()>;
    fn exists(&self, path: &str) -> Result<bool>;
    fn sync(&self) -> Result<()>;
}
```

The final signatures must define read/write handle types, ownership and lifetimes, error types, path validation, atomicity and durability guarantees, synchronization semantics, and the treatment of concurrent readers and writers. In particular, `sync` must not be assumed to provide equivalent durability on all backends; `atomic_write` must state whether it includes a durable directory entry. Do not implement the sketch literally.

**Candidate local backends:**

- `FsDirectory`: portable conventional filesystem I/O, with buffered or positional reads/writes.
- `MmapDirectory`: read-only memory mapping of immutable committed segment files; writes use a separate filesystem-backed path. Mapping lifetime must outlive readers and account for platform restrictions.
- `IoUringDirectory`: optional Linux implementation for suitable asynchronous/batched local I/O, with portable fallback.
- `MemoryDirectory`: deterministic in-memory tests and fault injection.
- `SpdkDirectory`: **tentative name only** for a future specialized backend; SPDK's user-space NVMe/block access is not automatically compatible with ordinary filesystem paths, `mmap`, or POSIX atomic-rename semantics.

**Separate contracts by responsibility:**

```text
quervant-core indexing / searching
          |
    Directory (logical local index-file lifecycle)
          |
    +-----+----------------+----------------+
    |                      |                |
 FsDirectory          MmapDirectory   MemoryDirectory
    |
 optional io_uring local I/O backend

Future: separate segment-read/block-cache contract for SPDK,
        if the Directory contract cannot express its semantics.

SegmentStore / SegmentCache: immutable segment materialization,
                            validation, retention, and local cache lifecycle
ObjectStore: authoritative remote durable objects, ranged reads,
             conditional publication and provider capabilities
```

`Directory` must **not** be confused with `ObjectStore`: the former abstracts local index-file access, whereas the latter manages authoritative remote objects. `SegmentStore` and `SegmentCache` sit above the physical backends and must define their own responsibilities without duplicating durability guarantees. Cold-reader bootstrap must work from `ObjectStore` regardless of the chosen local backend.

Do not require SPDK to satisfy a POSIX-like `Directory` interface. If necessary, define a separate logical segment-reader interface supporting bounded range reads, prefetch, and immutable snapshots, with backend-specific lifetime and memory management. The precise trait layering, sync versus async operations, and capability model belong to the core storage-contract PR.

**Implementation status (PR 3, `dev/storage-abstraction`):** the local `Directory` contract, `MemoryDirectory`, `FsDirectory` (same-directory temporary file, file `sync_all`, atomic rename and parent-directory sync on the initial supported Linux local-filesystem target; other platforms fail closed), the provider-neutral asynchronous `ObjectStore` contract with explicit capabilities and exact bounded ranged reads, the deterministic `FakeObjectStore` with fault injection, and a bounded verified `SegmentCache` (pinning, LRU eviction, hard accounting, no remote deletion) are implemented with unit, conformance and real-filesystem tests. No segment codec, manifest, CURRENT pointer, writer, reader, query executor, production S3/RustFS adapter or remote cold bootstrap exists. `mmap`, `io_uring` and SPDK remain future backends.

`Directory` is deliberately **synchronous**. Asynchronous cache preparation offloads blocking filesystem work (stale-temp cleanup, atomic promotion and eviction deletion) to a small bounded worker pool with waker-based completion; the polling/executor thread never runs a blocking syscall or blocks on a queue. Synchronous local reads (`SegmentCache::open_read`) used on search hot paths stay synchronous, remote object I/O stays asynchronous, and `quervant-core` requires no async runtime or Tokio. Running filesystem syscalls are not forcibly cancellable: a cancelled `prepare` keeps its reservation and per-key exclusion until the worker completes and reconciles. CPU-bound SHA-256 verification still runs on the polling thread. See [decisions/PR03_FS_OFFLOAD_DESIGN.md](decisions/PR03_FS_OFFLOAD_DESIGN.md). A hard **logical-length** physical cache bound (`known_bytes + reserved_bytes <= max_cache_bytes`, one ledger entry per cache-owned file) is enforced; failed deletes retain their charge, temporary/destination overlap is reserved, and startup reconciliation charges pre-existing/orphaned/temp files before admitting fills. The bound covers cache-owned regular-file content lengths in a dedicated cache root only — not filesystem allocation, metadata, unrelated writers or device free space. The approved additive `Directory::list`/`file_len` capability ([A4-DIR-01](decisions/PR03_PHYSICAL_CACHE_ACCOUNTING.md)) supports it; `Directory` and hot-path reads stay synchronous. Interrupted `FsDirectory` temporary files (`.trawler-tmp-<pid>-<counter>`) are recognized by exact grammar, charged, and cleaned during reconciliation, and a failed write whose on-disk state cannot be established retains a conservative charge instead of releasing capacity ([PR03_CRASH_TEMP_RECOVERY.md](decisions/PR03_CRASH_TEMP_RECOVERY.md)).

**Local index lifecycle implemented in PR 6 (`quervant-core::index`); snapshot-bound lexical query execution implemented in PR 7 (`quervant-core::search`).** PR 6 adds a single cooperating writer and an insert-only local lifecycle over the existing `Directory` and immutable segment/manifest codecs:

- `index/CURRENT` is the **sole** durable generation selector. It is a strict five-line ASCII codec (≤ 512 bytes) naming the generation manifest key, exact length and SHA-256. Recovery reads `CURRENT` only, verifies the manifest and every referenced segment, builds the committed-key index from real stored records, and fails closed on corruption or a missing object with no fallback to an older generation.
- Durable commit ordering is segments (content-addressed, `create` → `write_all` → file sync → directory sync) → generation manifest (same durable ordering) → atomic `CURRENT` **last**. The writer acknowledges only after `atomic_write` returns success. A failure before `CURRENT` leaves the old generation authoritative and retains the pending batch; an indeterminate post-replacement outcome enters `RecoveryRequired` and is never interpreted as durable from a read-back.
- Flush stages immutable segment bytes without writing any file or publishing visibility. Refresh publishes a **volatile** immutable snapshot (committed + flushed + pending) and never writes `CURRENT`. Committed/volatile `ReaderSnapshot`s are `Send + Sync`; `SegmentReader` instances are constructed independently from shared `Arc<Vec<u8>>` bytes rather than shared across threads.
- `PitHandle` pins exactly one snapshot until close/drop; pins are process-local and bounded. No garbage collection runs in PR 6, so old readers/PITs remain valid and referenced files are never deleted.
- `IndexWriter` holds `index/WRITER_LOCK` for its lifetime; a stale lock after a crash is never stolen automatically and must be removed by an operator. This is cooperative admission, not writer fencing/failover.
- PR 6 adds one **additive** `Directory` method, `create_dir_all`, needed to establish the nested `index/`/`index/manifests/`/`index/segments/` layout; it does not change the existing `create`/`atomic_write` parent-directory semantics. See [pr-artifacts/pr-6/implementation-report.md](pr-artifacts/pr-6/implementation-report.md).

Remote ObjectStore publication and RustFS cold bootstrap remain PR 13; advanced multi-term operators (prefix/glob/regex/FST) are PR 8; updates/deletes/merges/retention/GC are PR 9.

**Lexical search implemented in PR 7 (`quervant-core::search`, branch pending review).** `LexicalSearcher` binds a borrowed `ReaderSnapshot`, the caller schema and the analyzer registry, and executes exact `Term` (Text/Keyword), positional `Phrase` on Text, arbitrarily nested `And`/`Or`/`Not` and `MatchAll`, returning deterministic BM25 top-K with an exact `total_hits`. Compilation rejects every contract operator not executable in PR 7 (`Prefix`, `Glob`, `Regex`, typed ranges, `Exists`/`Missing`/`IsNull`, `In`/`NotIn`, IP, JSONPath and geo shapes) with a typed `UnsupportedOperator` **before** any segment is read. Scoring eligibility is defined by `Not` parity: a compiled leaf contributes BM25 only if it is reachable through an even number of `Not` nodes, so a negative-only leaf contributes zero and negation never increases a score, while Boolean membership is unchanged. Field lengths are read from an immutable, optional per-segment `FieldNorms` section (`FEATURE_FIELD_NORMS`, v1) that the segment builder emits in the same analysis pass as postings; document frequencies are retrieved for the **queried terms only** (bounded dictionary binary search) rather than by scanning every dictionary entry and posting. Genuine legacy segments without the section use the original all-postings reconstruction for that segment only; malformed norms are corruption and never fall back. Norms are validated and bounded by the existing segment decode limits and are decoded once per `SegmentReader::open` (which is per search); they are not added to the manifest or `CURRENT`. Candidate accounting separates cumulative work/scanned occurrences from per-segment peak entries and search-wide segment+global logical bytes; each retained temporary is charged before materialization and released at its drop point, the per-segment result batch is atomically transferred to global ownership before the segment closes (no uncharged or double-charged interval), ledger transitions validate all budget and ledger state before committing any counter, and phrase-verification scratch (candidate, occurrence-reference and chain buffers) is bounded and charged through a scoped owner. These are deterministic **logical** accounting units, not allocator-exact RSS or OOM guarantees. Phrase matching requires an ordered occurrence chain within one `value_index` and honors `position_length`. The executor never mutates the snapshot, writer, manifest or `CURRENT`, and reuses PR 6 `open_segment_reader`/RAII reservations. See [pr-artifacts/pr-7/implementation-report.md](pr-artifacts/pr-7/implementation-report.md).

### Native JSON path index (PR 11)

JSON source structure remains byte-semantically recoverable from the existing typed stored-value codec (`FieldType::Json`); stored source is authoritative and the JSON path index never reconstructs JSON. Indexed JSON fields (`options.indexed == true`) additionally emit an immutable **JSON-path section**: required feature `FEATURE_JSON_PATHS = 0x0009` v1 and `SectionKind::JsonPaths = 0x0010`, appended without changing the format major/minor or any existing section/feature id. A segment declaring the feature without the section (or vice versa) fails to open; a malformed declared section is corruption and is never bypassed by a source fallback. Segments without the feature remain readable, and a JSON predicate against a legacy segment uses a bounded, exact stored-source evaluator when the field is stored, or a typed `UnsupportedOperator` when it is not.

The section body v1 (all integers little-endian, varints canonical unsigned LEB128) is:

```text
u16 section_version = 1
u64 document_count
u32 indexed_json_field_count
repeat field_id in strictly ascending order:
    u32 field_id
    u64 occurrence_count
    repeat occurrence in (physical_doc_id ASC, concrete_path ASC) order:
        u64 physical_doc_id
        varint segment_count
        repeat segment:
            u8 tag: 0 = Member, 1 = Index
            Member: varint UTF8_byte_len, then exact UTF8 bytes
            Index: varint nonnegative_u64
        u8 node_kind: 0 Null, 1 Bool, 2 I64, 3 U64, 4 F64, 5 String, 6 Array, 7 Object
        scalar payload:
            Null/Array/Object: none
            Bool: u8 0 or 1
            I64: i64
            U64: u64
            F64: finite IEEE754 f64; signed zero normalized to +0.0
            String: varint UTF8_byte_len, then exact UTF8 bytes
```

One occurrence is emitted for the root and **every** descendant node (containers and nulls included), so concrete array ancestry is retained: object members are byte-exact and array elements carry their exact index. A single JSON root is `$`; `ExplicitNull` is a root `Null`; `Absent`/`Empty` produce no root; each value of a multi-valued JSON field is an independent root under a virtual outer index (`[0]`, `[1]`, …). Duplicate object member names in an **indexed** JSON field are rejected at admission because a concrete path without a member-occurrence ordinal would be ambiguous; stored-only JSON is unchanged. `JsonPathExists` is document-level existential (`[*]` traverses exactly one array level and only an `Index` segment), and `JsonPathEquals` accepts concrete paths only and compares scalar variants exactly (`I64(1) != U64(1) != F64(1.0)`, `-0.0 == 0.0`, Text/Keyword RHS against JSON strings by exact UTF-8 bytes). Boolean `And`/`Or`/`Not` remain document-level and never imply same-array-element correlation. The decoder builds one validated per-`(field, doc)` offset table in a single pass and rejects non-monotone/duplicate paths, invalid tags/UTF-8, trailing bytes, non-JSON field ids, out-of-range doc ids and every count/offset overflow with a typed `SegmentError`. Limits are internal constants (`MAX_JSON_PATH_DEPTH = 128`, `MAX_JSON_PATH_OCCURRENCES_PER_DOCUMENT = 65_536`, `MAX_JSON_PATH_OCCURRENCES_PER_SEGMENT = 8_000_000`, `MAX_JSON_PATH_MEMBER_BYTES = 65_535`, `MAX_JSON_PATH_SECTION_BYTES = 256 MiB`) and reuse `SegmentLimits`/`DecodeBudget`/`ScanGuard`. Compaction rebuilds the section by remapping decoded occurrences, never by copying old bytes. JSON sorting, range/membership queries, projections and correlated array joins are out of scope for PR 11. See [pr-artifacts/pr-11/implementation-report.md](pr-artifacts/pr-11/implementation-report.md).

### GeoPoint spatial index (PR 12)

Indexed `GeoPoint` fields additionally emit an immutable, field-local **median-split 2D KD tree**: required feature `FEATURE_SPATIAL_POINTS = 0x000A` v1 and `SectionKind::SpatialPoints = 0x0011`, appended without changing the format major/minor or any existing section/feature id. Every point occurrence is stored with its physical doc id, multivalue ordinal and exact WGS84 coordinates; split axis alternates longitude (even depth) / latitude (odd depth); each node stores exact subtree extrema. Points are ordered deterministically by `(axis.total_cmp, other.total_cmp, doc_id, ordinal)` after signed-zero normalization, and serialized preorder with a fixed 77-byte node width. The reader validates feature/section coupling, field schema/type/indexed flags, increasing field ids, `count * 77` overflow, physical doc range, unique `(doc_id, ordinal)`, finite WGS84 values, child ordering/continuity, axis alternation, no cycles/orphans, bottom-up exact extrema, split ordering and trailing bytes, and fails closed on any digest-valid malformed section rather than falling back. The section is emitted whenever an indexed GeoPoint field exists, even with zero points; older segments remain readable and use a bounded exact column scan, or a bounded stored-source fallback, with indexed-not-stored/non-columnar legacy state failing typed rather than returning zero hits.

Query semantics are exact and spherical: bounding-box edges are inclusive and a `west > east` box is `[west, 180] ∪ [-180, east]` with `±180` the same meridian; radius is inclusive haversine with `R = 6_371_008.8 m` (not ellipsoidal); polygon is planar, non-crossing and non-geodesic, with the outer boundary inside and hole boundaries excluded. Membership predicates carry **no tolerance**: bounding-box longitude sets are split into canonical closed intervals compared directly (no modulo epsilon and no near-full-world special case), and polygon collinearity/boundary classification uses the adaptive `robust::orient2d` predicate with exact inclusive bounds. KD pruning remains conservative — it may visit extra nodes but never omits an exact match. Every spatial scratch allocation (per-leaf candidate sets, the DFS stack and distance-sort tables) is drawn from one fallible per-segment `GeoScratchBudget` bounded by `SearchLimits::max_total_candidate_bytes`, with the pre-dedup candidate count bounded by `max_segment_candidate_entries`; the top-K heap budget remains separate. Missing/null/empty contributes no point; a multi-valued document matches if any point matches and is returned once. Spatial leaves are compiled once and their exact candidate-doc membership is built once per segment by bounded KD traversal with exact geometry verification (no traversal per document); Boolean `And`/`Or`/`Not` reuse that membership. Distance sort uses the minimum point distance with missing last and participates in the PIT/search-after fingerprint. GeoJSON ingestion accepts exactly `{"type":"Point","coordinates":[lon,lat]}`. Compaction reads persisted spatial occurrences and rebuilds the deterministic tree; it never reconstructs points from stored fields when the feature is present. See [pr-artifacts/pr-12/implementation-report.md](pr-artifacts/pr-12/implementation-report.md).

**PR 6 Amendment 01 (writer freshness and bounded reader lifecycle).** An `Index` handle is a read-only snapshot of the generation visible at open time and is **not** writer authority: every new `IndexWriter` acquires the cooperative lock and then reloads the authoritative `CURRENT` while holding it, so a stale handle cannot lose intervening commits. Recovery preflights the checked sum of all declared segment lengths against `max_snapshot_bytes` (and each against the codec acceptance bound) before allocating the segment vector or opening any segment, and re-checks the cumulative verified bytes while loading, so an over-limit generation is rejected with no partial snapshot. A failed writer-lock delete leaves the guard unreleased and the lock held (a single best-effort Drop retry); stale locks still require manual operator cleanup. Point-in-time ids are process-local `pit-<16 hex session>-<16 hex ordinal>` values from a checked process-global session sequence, and ordinal exhaustion rolls back the reserved pin instead of wrapping. Managed reader materialization goes through `ReaderSnapshot::open_segment_reader`, which reserves the encoded byte length against a per-snapshot budget **before** cloning and returns a non-`Clone` RAII guard; the unmetered public `SegmentSnapshot::reader` path was removed. The reservation bounds cloned encoded bytes only, not decoder allocations or process RSS, and snapshot base residency and active reader copies remain separate ceilings of the same configured value. See [pr-artifacts/pr-6/amendment-01-implementation-report.md](pr-artifacts/pr-6/amendment-01-implementation-report.md).

**PR 6 Amendment 02 (commit/reopen budget parity).** A commit now applies the same `bounded_segment_total` validator that recovery uses to the complete prospective generation — the authoritative committed manifest references chained with all built new segments — before installing any immutable object or publishing `CURRENT`. A generation whose encoded segments exceed the writer's `max_snapshot_bytes` (or a per-segment codec bound) is rejected with a typed `ResourceLimit` before any durable write; the writer keeps its pending/flushed state, is not poisoned, and remains usable. No codec, manifest, `CURRENT`, storage or publication-ordering change. See [pr-artifacts/pr-6/amendment-02-implementation-report.md](pr-artifacts/pr-6/amendment-02-implementation-report.md).

## Text analysis, field indexing, and multi-term queries

**Analyzer subsystem implemented in PR 4 (`quervant-core::analysis`); postings-driven lexical execution implemented in PR 7; FST, automata and the prefix/glob/regex operators remain PR 8.** Text analysis is a core capability, not an application-side preprocessing requirement. It must be independent of distributed search and configured per field.

### Analyzer pipeline and token contract

```text
input text -> optional character filters -> tokenizer -> ordered token filters -> token stream
```

- Initial tokenizers: Unicode-aware word, whitespace, and keyword (entire input as one token).
- Initial filters/normalizers: lowercase, configurable Unicode normalization and ASCII folding, stop-word filtering, and language-specific stemming (English first, e.g. Snowball); n-grams and edge n-grams follow.
- Later: synonym and multi-token synonym handling, with explicit token graph semantics where needed.
- Tokens must retain at least term bytes/text, position and position increment, start/end offsets, and position length (or an extensible equivalent). Preserve position gaps for removed stop words and support phrase queries and highlighting.
- Index-time analyzers and search-time analyzers are independently configurable per field, with compatible versioned definitions. Analyzer changes must not silently reinterpret already-indexed segments; document reindexing and backward compatibility.
- Prefer composable Rust `Tokenizer`, `TokenFilter`, `Analyzer`, and `Normalizer` contracts. Finalize ownership, streaming, fallibility, UTF-8 offsets, allocation behavior, and thread safety in a subsequent design/implementation PR.
- Multi-fields allow the same source value to be indexed as analyzed text, normalized keyword, and non-stemmed wildcard-searchable terms. Stemming must **not** automatically apply to glob patterns.

### Implemented analyzer API (PR 4)

The following are implemented in `crates/quervant-core/src/analysis` and must be treated as the current contract (approved by `docs/decisions/PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md`):

- **Token model (`Token`).** UTF-8 term (`Box<str>`), `value_index`, absolute `position`, `position_increment`, `position_length`, and original-source UTF-8 byte offsets `[start_offset, end_offset)` **within the source value**. Stop-word removal preserves position holes; offsets always reference the original input even when a filter changes term length. Positions/gaps/offsets use checked arithmetic and fail typed rather than wrapping or saturating.
- **Pipelines (`Pipeline`).** `TokenizerKind` (`Keyword`, `Whitespace`, `UnicodeWord` via UAX #29 `unicode-segmentation`) plus ordered token filters `Normalize` (default NFC; `None`/NFD/NFKC/NFKD supported), `CaseFold` (full Unicode folding via `icu_casemap` 2.0.1, opt-in), `AsciiFold`, `Stopwords` (pinned Snowball English list), and `Stem` (Snowball English, `rust-stemmers` 1.2.0, opt-in). **Length-changing character filters are rejected at configuration time** (`UnsupportedCharacterFilter`) because no approved original-offset correction map exists.
- **Multi-value semantics.** Each token carries its `value_index` and value-relative offsets; the first token of a subsequent value is placed at least `POSITION_GAP = 100` positions after the previous value's last token, including when an intervening value is empty or stop-word-only.
- **Limits and cancellation (`AnalysisLimits`).** Enforceable ceilings: 1 MiB per source value, **100,000 emitted tokens per source value**, 4 KiB per term, and 8,000,000 deterministic work units **per call**. Callers may lower but not exceed them. The pull cursor (`AnalysisCursor`) scans lazily, charging work incrementally; the keyword and whitespace tokenizers charge per scalar, while one UAX #29 word segment scanned by `UnicodeWordIndices::next()` is **atomic** (the library API offers no intra-segment checkpoint) and is bounded by the 1 MiB per-value ceiling. `Cancellation` is polled at fixed work/checkpoint boundaries and before each word segment; exhaustion/cancellation are typed errors and never return a silently truncated stream. Opaque third-party domain calls are charged/polled around, not preempted. Terminal cursor failures are latched: after the first error, `next_token` returns the same error without further scanning; EOF is idempotent.
- **Definition/registry (`AnalyzerDefinition`, `AnalyzerRegistry`).** Each definition has a stable id, semantic version, explicit index and search pipelines, and optional `DomainConfig`. The canonical `AnalyzerFingerprint` is SHA-256 (RustCrypto `sha2`) over a version-tagged, length-delimited encoding that includes pipeline order/config, normalization form, stop-word/stemmer dataset identities, and pinned domain dataset versions. `SchemaAnalyzerBindings` resolves `FieldDefinition.analyzer` (Text) / `.normalizer` (Keyword) against the registry and **fails closed** on unknown names or version mismatch. `AnalyzerRegistry::resolve_fingerprint(name, version, fingerprint)` is the compatibility seam for persisted analyzer identity: an equal id/version with a different canonical fingerprint is a typed `AnalyzerFingerprintMismatch`, never a silent reinterpretation. `resolve_compatible` is explicitly version-only.
- **Term-query preparation (`prepare_term`, `prepare_prefix`, `prepare_glob`, `prepare_regex`).** Literal terms/prefixes are normalized but **not stemmed**; globs are parsed into `Literal`/`AnySequence`/`AnyChar` segments, normalizing only literals and preserving operators/escapes. `prepare_regex` validates the bounded subset with the parser-only `regex-syntax` AST (no compilation/execution) and normalizes **decoded literal runs** — maximal sequences of adjacent literal AST nodes with no intervening operator/group/class/anchor/quantifier — using the same ordered `Normalize`/`CaseFold`/`AsciiFold` transforms as indexed terms, re-escaping the result as literal scalars. This preserves cross-scalar NFC composition (`e`+U+0301 → `é`) and safe case expansion (`Straße` → `strasse`) without changing operator scope; a quantified scalar that would expand, a combining mark that could compose across a quantifier/operator boundary, inline flags, named captures, and classes that are not stable under the configured transforms are all rejected typed. Class ranges are proven stable over their whole (bounded ≤4096-scalar) interior, not just endpoints, so `[0-9]`/`[a-z]` remain accepted while `[A-Z]`/`[@-a]` are rejected under case folding. When the pipeline applies a **composing normalization** (`NFC`/`NFKC`), any expression that follows another expression and can begin its nonempty match with a combining scalar is rejected typed: this includes nested groups/alternations/repetitions, preceded literal runs, the `.` wildcard, Perl/Unicode classes (`\w`, `\d`, `\s`, `\p{...}`), bracketed classes proven able to match a combining scalar, and **negated bracketed or POSIX/ASCII classes** (`e[^x]`, `e[[:^digit:]]`) whose complement can include combining scalars (e.g. `e(?:\u0301)`, `e[\u0301]`, `e.`, `e\w`, `e[^x]`). The analysis is **nullable-aware**: optional/empty prefixes (`x?`, `x*`, `{0,n}`, nested nullable groups) do not hide a later mark. Self-contained runs compose internally (`(?:e\u0301)` → `(?:é)`), a leading mark with no preceding expression is preserved, and safe classes/ranges (`e[0-9]`, `e[a-z]`, `e(?:xy)`) remain accepted. Under decomposition-only or no normalization no cross-boundary composition occurs, so the same patterns are accepted. Separate from leading-combining safety, a **negated class's complement membership is not stable under full Unicode case folding** (`[^a]` matches source `A`, but the folded indexed term `a` is excluded); when a `CaseFold` filter is configured, any outer-negated bracketed class, negated POSIX/ASCII class, or nested negated bracket is rejected typed with `UnsupportedPattern`, while positive classes (`[0-9]`, `[a-z]`, `[[:digit:]]`) remain accepted and non-case-folding `NFC`/`NFD`/`NFKD`/no-transform pipelines keep the previous behavior. `prepare_prefix` and `prepare_glob` enforce the 1 MiB raw-input ceiling, a deterministic per-scalar work charge independent of configured filters, the 4 KiB per-term bound on the normalized prefix and each normalized glob literal segment, and a `max_input_bytes` ceiling on the serialized glob; a glob literal removed entirely by the configured transforms is rejected rather than silently dropped. Under composing normalization a glob literal that begins with a combining scalar and is not the first segment (e.g. `e*\u0301`, `*\u0301`) is rejected typed, because `*` may match zero scalars and expose cross-boundary composition; `*` and `?` are defined over scalars of the **indexed term**. Stop-words and stemming are never applied to patterns. Automaton/FST execution is PR 8.
- **Domain analysis (`analyze_domain`).** UTS #46 **nontransitional** canonical ASCII/Unicode identity (`idna` 1.1.0), reversed labels, PSL decomposition with explicit `PslPrivateSuffixPolicy` (`publicsuffix` 2.3.0 with the committed pinned `public_suffix_list.dat`), and a separate UTS #39 confusable `skeleton` (`unicode-security` 0.1.2). Canonical identity and skeleton are distinct; a skeleton match is never identity equality. The embedded PSL is parsed **fail-closed**: a malformed dataset is a typed `InvalidDataset` error, never an empty-list success. `domain_dataset_identity()` exposes the exact pinned dataset identities and re-verifies the embedded PSL digest. No dataset is fetched at runtime.
- **PR 5 boundary.** PR 4 defines analyzer identity/fingerprint metadata for consumers, but **no on-disk/segment format**. PR 5 owns serializing analyzer identity per field/segment; PR 6 owns commit/recovery; PR 8 owns multi-term execution. No persisted format may be frozen against these fingerprints without preserving their exact canonical encoding.

### Glob query semantics

Glob queries are first-class `GlobQuery` nodes, distinct from `TermQuery`, `PrefixQuery`, and full-text query parsing. Initial grammar:

| Syntax | Meaning |
| --- | --- |
| `*` | Zero or more Unicode scalar values |
| `?` | Exactly one Unicode scalar value |
| `\\*`, `\\?`, `\\\\` | Escaped literal wildcard or backslash |

Patterns such as `mic*soft`, `mic?osoft`, `*soft`, and `*.example.com` are valid. `*.example.com` can match multiple DNS labels (e.g. `a.b.example.com`); it does not mean exactly one label. Glob matching operates against the indexed **term** rather than raw source text. Field-specific pattern normalization must preserve operators and escaping, and must use compatible normalization with the indexed terms without applying stemming. Explicitly define case sensitivity and Unicode normalization per field.

The planned execution path is **glob parser -> finite-state automaton -> FST term-dictionary intersection -> postings -> query scoring**. Do not use an unbounded scan of all terms as the default implementation. Leading-wildcard and match-all patterns can still be expensive: impose limits on pattern length, automaton complexity, expanded terms, CPU/time and cancellation. Exceeding budgets must return an explicit error or clearly flagged partial results; never silently truncate.

### Regex queries and shared multi-term execution

`RegexQuery` is a first-class query variant alongside `TermQuery`, `PrefixQuery`, and `GlobQuery`. The supported grammar is a **documented regular-language subset**, not PCRE: character classes/ranges, grouping, alternation, `*`, `+`, `?`, bounded repetitions such as `{2,4}`, and Unicode character classes where bounded implementation cost permits. Do **not** support backreferences, lookbehind/lookahead, or arbitrary PCRE extensions. Regex query syntax and its escaping rules are distinct from glob syntax.

A regex matches the **entire indexed term**, not an arbitrary substring of raw document text. For example, `(login|signin)[0-9]*\\.example\\.com` can match `login.example.com` or `signin42.example.com` in a suitable normalized keyword field. Field normalization and case-sensitivity must be explicit and compatible with index-time normalization; do not stem regex patterns. Specify Unicode scalar-value semantics and their compilation to the UTF-8 byte transitions used by the term dictionary. Pattern normalization must not corrupt regex operators, character classes, escapes, or Unicode properties.

```text
PrefixQuery / GlobQuery / RegexQuery
                 |
        syntax-specific parser
                 |
       compatible finite automaton
                 |
        FST dictionary intersection
                 |
       bounded matching-term stream
                 |
      postings / query execution
```

Share the automaton/FST intersection and term-expansion infrastructure across prefix, glob, and regex queries, with a conceptual `MultiTermQuery` dispatch abstraction (final Rust API deferred). Prefer automata that can be intersected efficiently with the term dictionary; determinization/state explosion must be bounded and may cause explicit query rejection. Apply common limits for pattern length, automaton states/transitions, matching-term expansion, CPU/time, cancellation, and memory. A regex such as `.*` may still enumerate most terms, despite FST acceleration. No silent truncation or unbounded fallback scans. Define rewrite/scoring semantics consistently for all multi-term queries.

Later PR tests must cover regex alternation, classes, repetition, escaping, Unicode properties, full-term anchoring, case normalization, equivalence with a reference matcher, pathological state growth, leading `.*`, cancellation, and cross-segment correctness.

### Domain-oriented analysis and fuzzy search (approved optional v0.1 scope)

Domain names are identifiers, not English prose. **PR 4** delivers optional, schema-configurable DNS/IDNA canonicalization (including case, root-dot and DNS label/length policy), reversed-label representation, Public Suffix List (PSL) registered-domain decomposition, and Unicode UTS #39 confusable skeletons. Preserve the original input and the canonical exact identity separately from all derived keys. Skeleton equality is **not** domain identity or a claim of visual equivalence. Reversed labels, registered-domain keys, individual labels and confusable skeletons are independent, queryable derived representations, not replacements for canonical identity.

Specify and version IDNA profile, Unicode normalization, PSL dataset and private-suffix policy, UTS #39 confusables dataset and any derived-key encoding. Index-time and query-time interpretation must agree; mismatched versions require explicit handling (such as reindexing), never silent reinterpretation. Invalid input produces typed errors. Keep domain support optional and general-purpose; do not introduce DIGR-specific risk scoring, detection rules or brand workflows into `quervant-core`.

**PR 8** delivers general-purpose bounded fuzzy term matching plus basic optional domain-aware fuzzy matching using reusable query infrastructure. Enforce edit-distance, term-expansion, memory, time and cancellation budgets; compare canonical identity separately from similarity candidates. Advanced weighted domain similarity and specialized impersonation scoring remain **after v0.1**. Precise algorithms, query contracts and version compatibility must be finalized in PR 4/PR 8 design reviews before code or format freeze.

### Required validation in later PRs

Cover Unicode boundaries, offsets/positions and stop-word gaps, stemming behavior, multi-field selection, wildcard escaping, literal wildcard terms, leading wildcards, pattern normalization, automaton/FST equivalence against a simple reference matcher, query cancellation and resource limits, and domain identity preservation.

## Dense vector and hybrid retrieval (future scope)

**Architectural commitment, not implemented in PR 1.** Quervant will support vector search as an additional field-indexing and query capability within the standalone core, reusing document IDs, immutable segments, manifests, local `Directory`, `SegmentStore`/`SegmentCache`, and authoritative `ObjectStore`. Do not create an independent vector database or require an embedding model/provider in the core.

### Field and query contracts

- Plan a `VectorField` with fixed dimension, dense `f32` values, explicit metric (cosine similarity, dot product, or Euclidean distance), validation of dimension and non-finite values, and immutable index metadata describing encoding, metric, and version. Multiple vector fields per document may be supported.
- Plan `KnnQuery` with field, query vector, `k`, optional metadata filter, and bounded candidate/search parameters; define score direction and normalization per metric. Exact KNN is the reference implementation and correctness oracle.
- Plan `HybridQuery` combining lexical (BM25) and vector retrieval, initially through reciprocal rank fusion (RRF) of candidate ranks rather than naive combination of incompatible raw scores. Define candidate limits, deterministic tie-breaking, and missing-result behavior.
- Applications supply embeddings initially. Embedding generation/model hosting is optional integration work, not part of the initial core.

### Immutable segments, persistence, and caching

Persist vector values and optional ANN structures as versioned immutable segment files, referenced by the same committed manifest mechanism as lexical index files. Vector writes, deletes, merges, and crash recovery must preserve document identity and visibility across both index representations. HNSW is the leading approximate nearest-neighbor (ANN) candidate, **not** a committed library/format decision; segment-local graphs must account for tombstones, merge/rebuild costs, and graph versioning.

ObjectStore remains authoritative; local vector graphs and data are disposable caches. Graph traversal can require irregular random accesses: avoid per-edge remote object requests. Design bounded local materialization, memory accounting, warmup, eviction, and cold-reader recovery before enabling ANN. `Directory` supplies local index-file access; vector-aware `SegmentCache` policy may differ from postings caches without changing the durable storage model.

### Query execution, filtering, and distributed behavior

Start with exact flat KNN (baseline), then benchmark segment-local HNSW for recall/latency/memory against exact results. Metadata-filtered KNN must be correct: post-filtering a small unfiltered ANN candidate list can underfill `k` or lose recall. Plan filter-aware ANN traversal and an exact filtered fallback where appropriate; specify underfill and recall semantics explicitly.

Search Nodes run shard-local vector retrieval; the Aggregator merges globally comparable exact scores or performs rank fusion for hybrid results. For ANN, configure per-shard candidate oversampling and measure global recall against exact KNN. Apply existing deadlines, cancellation, memory and work budgets. Do not conflate approximate retrieval with exact top-K guarantees.

### Delivery order and verification

**Only after v0.2 distributed lexical search is delivered:** (1) vector field schema, immutable `f32` storage, metric validation and exact KNN; (2) HNSW prototype with reproducible recall@k, p50/p95/p99, throughput, memory, build and merge benchmarks; (3) metadata-filtered vector search with correctness fallback; (4) BM25/vector hybrid RRF; (5) optional quantization, sparse vectors, or model integrations.

Later PRs must test metric correctness, dimension mismatch, NaN/infinity rejection, deletion/merge visibility, manifest crash recovery, empty-cache ObjectStore bootstrap, memory budgets, filtered top-K correctness, deterministic hybrid fusion, and multi-shard ANN recall.

## Distributed responsibilities

**Design target for v0.2; not implemented by this documentation PR.** The complete approved distributed architecture is maintained in the [distributed design register](distributed/README.md), which is normative for distributed-specific decisions. Its specifications cover:

- [Topology, logical shard routing, roles and placement](distributed/01-TOPOLOGY-PLACEMENT.md).
- [Distributed ingestion, stable operation IDs, revisions, fencing and acknowledgment semantics](distributed/02-INGESTION.md).
- [Distributed querying: global BM25, exact analytics, snapshot vectors, pushdown, budgets, planning and future joins](distributed/03-QUERYING.md).
- [Coordinator HA, Search Node recovery, scaling, cluster metadata and lifecycle](distributed/04-AVAILABILITY-OPERATIONS.md).
- [ObjectStore publication, retention and conservative GC](distributed/05-STORAGE-GC.md).
- [FP-002/GC-002/DR-002 safety protocols and unresolved proof gates](distributed/06-SAFETY-PROTOCOLS.md).

Keep `quervant-core` independent of distributed dependencies. Coordinator controls desired placement, Query Aggregator performs direct Search Node query fan-out, Indexing Coordinator routes bounded writes, Search Nodes run shard-local core readers/writers, and Publication Authority validates fenced pointer transitions. ObjectStore is authoritative for committed generations; etcd is authoritative for control-plane metadata. Do not create two independently writable publication pointers.

**Scope reconciliation:** the previously open distributed-ingestion milestone decision has been resolved architecturally in favor of a minimal complete v0.2 distributed write path, subject to explicit release acceptance and implementation planning in [ROADMAP.md](ROADMAP.md). Distributed joins, automatic resharding, vector search and destructive remote GC without safety qualification remain excluded.

## Dispatch strategy and hot-path performance

**Design policy for v0.1 and later, not an implemented optimization.** Prefer static dispatch (concrete types or generic trait bounds) in CPU-bound inner loops where per-item indirect calls can inhibit inlining or specialization. Do **not** ban `dyn Trait` globally: choose dispatch granularity based on measured costs.

- **Static-dispatch candidates:** postings iterators, term-dictionary/FST transitions, segment decoding, BM25 scoring, Boolean/phrase execution, and high-volume token processing. Design generic/concrete interfaces so the compiler can monomorphize and optimize these paths when beneficial.
- **Runtime-variable query plans:** query trees may contain heterogeneous scorer types. Consider enum-based dispatch or query-plan specialization, ideally dispatching outside the per-document inner loop. An enum match still incurs runtime branching and is not automatically faster than a trait object.
- **Coarse-grained boundaries:** `dyn Trait` is acceptable for `Directory`, `ObjectStore`, pluggable backends, service orchestration, and similar operations where I/O, allocation, or network latency dominates. A single indirect call per batch/block is different from one per posting/document.
- **Tradeoffs:** monomorphization can increase compilation time, binary size, and instruction-cache pressure; generic and async trait APIs can also complicate ownership and ergonomics. Avoid premature generic propagation through entire call stacks.
- **Required evaluation before freezing hot-path APIs:** benchmark representative static-generic, enum-dispatch, and `dyn Trait` scorer/postings designs on identical data and hardware. Measure QPS, p50/p95/p99 latency, CPU/cycles, allocations, code size and compile-time costs. Profile real workloads, including term, conjunction, disjunction and phrase queries, before claiming a dispatch strategy is faster.

**Rule:** no *avoidable* dynamic dispatch inside performance-critical inner loops; permit it at coarse-grained boundaries or when benchmarks show it is acceptable.

## Logging, tracing, and telemetry boundaries

**Planned v0.1 policy; no telemetry runtime is implemented by PR 1.** Use the Rust `tracing` crate as Quervant's standard structured event/span **instrumentation API**. Do not introduce a custom `Tracer` trait or a generic span-wrapper layer merely to support hypothetical framework swaps. The instrumentation API and the collection/export implementation are separate decisions.

- `quervant-core` may depend on `tracing` but must **not** install a global subscriber or require `tracing-subscriber`, OpenTelemetry SDK/exporters, an OTLP Collector, Prometheus, Jaeger, Loki, or Grafana. An embedding application owns telemetry configuration; the core remains usable with no subscriber.
- Service binaries own initialization, filtering, sampling, formatting, nonblocking log writers, exporter lifecycles, and shutdown/flush. Keep `tracing-subscriber` and optional OpenTelemetry integrations behind application/service boundaries so collector and exporter implementations can change without rewriting core instrumentation.
- `tracing` versus an independent instrumentation API such as `fastrace` is **not** a transparent subscriber swap. Evaluate such a migration only if reproducible end-to-end benchmarks justify its call-site and ecosystem integration costs.
- Preferred reference observability stack (optional, not a core dependency): structured logs, OpenTelemetry/OTLP tracing and metrics, Prometheus, Jaeger, Loki, and Grafana. Select concrete metrics API/export paths in an implementation PR; avoid assuming every log route must use OTLP.

### Instrumentation placement

**Instrument at bounded operation boundaries:**
- v0.1: query request and query-plan phases; index/write batches; flushes, commits, merges, refresh and recovery; segment load/cache materialization; ObjectStore operations and retries; errors and exceptional state changes.
- v0.2: Aggregator fan-out and shard responses, Coordinator placement/leadership changes, Search Node shard activation/drain, rebalancing and failover. Propagate W3C Trace Context across service RPC boundaries.
- Use counters, gauges and histograms for aggregate per-query/per-batch statistics such as query duration, indexed documents, postings visited, expanded terms, cache hit/miss counts, merge duration and storage bytes. Record aggregated values after the operation rather than emitting an event for every item.

**Avoid instrumentation inside tight loops:** no routine span creation/enter/exit, per-document/per-posting/per-token/per-FST-transition/per-score events, or per-decoded-value logging in production execution loops. Avoid expensive diagnostic formatting, allocations, synchronous JSON formatting, I/O and exporter calls on search/indexing hot threads. If exceptional fine-grained diagnostics are needed, isolate them behind explicit opt-in diagnostic builds/configuration, with bounded output and separately measured overhead.

**Performance and safety requirements:** use level/target filtering and compile-time maximum-level filtering where appropriate; note that disabled call sites may still have nonzero costs and expensive diagnostic computations must be explicitly guarded. Apply bounded exporter queues, batching, configurable sampling and documented loss/backpressure behavior; telemetry outages must not block query processing. Use bounded-cardinality metric labels; never label metrics by document ID, raw query, term, user ID or arbitrary shard IDs without an explicitly reviewed cardinality policy. Avoid logging sensitive query contents, credentials, document bodies and raw identifiers by default.

### Verification

Before v0.1 acceptance, benchmark identical representative search and indexing workloads with no subscriber, filtered subscriber, default production instrumentation and opt-in diagnostics; include a collector-unavailable scenario. Report throughput/QPS, p50/p95/p99 latency, CPU, allocations, memory and export drops, and compare against an uninstrumented baseline. Treat any overhead budget as a measured release criterion, not a claim about a library. Reassess the instrumentation API only if material measured overhead remains after fixing instrumentation granularity and subscriber configuration.

## I/O architecture and kernel-bypass strategy

**Design intent, not implemented functionality.** Optimize measured bottlenecks without coupling indexing or query semantics to a specific operating system, NIC, or NVMe driver.

The initial data path is:

```text
ObjectStore (S3/RustFS/etc.) <-- Tokio + conventional HTTP client --> cache/workspace
                                                                  |
                                      local immutable segments: mmap / buffered reads
                                                                  |
                                      synchronous postings and scoring loops
```

The planned optimization tiers are:

1. **Portable baseline:** Tokio for remote ObjectStore requests, conventional filesystem operations for local cache and workspace, and memory mapping where suitable for immutable segment reads. Preserve a portable buffered-read fallback.
2. **Optional Linux `io_uring`:** benchmark asynchronous/batched local NVMe reads and writes, prefetch/cache fill, merge I/O, and integrity-check workflows. `io_uring` still executes through the Linux kernel; it is **not** full kernel bypass. Avoid assuming it outperforms `mmap` for hot random-access postings.
3. **Experimental SPDK / DPDK:** SPDK offers user-space NVMe access and DPDK offers user-space packet I/O for dedicated high-performance deployments. They are **not** initial requirements. SPDK cannot be treated as a drop-in replacement for ordinary filesystem-backed, `mmap`-readable segment caches; it needs a distinct block/cache backend, memory ownership and DMA model. DPDK requires a compatible networking stack and deployment constraints; it does not automatically accelerate standard TLS/HTTP/S3 clients.

**Abstraction boundaries:** keep logical segment reads, range/prefetch operations, and cache management independent of the local I/O backend. A future backend may use conventional filesystem I/O, `io_uring`, or an SPDK-specific cache. Do not promise one common `mmap` interface for SPDK. Place backend-specific code behind opt-in features, with platform and runtime capability detection and a portable fallback. Keep these boundaries independent of distributed placement and shard ownership.

**Performance evaluation:** compare cold/warm-cache latency (p50/p95/p99), QPS, CPU cycles per query, throughput, cache hit rate, I/O amplification, memory use, and cost on the **same hardware and workload**. Measure remote-object latency separately from local-NVMe behavior, including realistic query mixes and merges. Prefer an optimized backend only after reproducible benchmarks show a meaningful end-to-end benefit. Document kernel, filesystem, NVMe, NUMA, and deployment prerequisites.

## Stable-key mutation lifecycle (PR 9)

PR 9 adds stable-key revisions, tombstones, idempotency and explicit lossless compaction to the local single-writer lifecycle. Segment files remain byte-immutable; logical visibility lives in a **versioned, content-addressed mutation-state sidecar** referenced by a manifest payload version 2.

- **Admission vs. durability.** `IndexWriter::apply` admits one typed mutation into an ordered journal and returns a `MutationResponse` with the allocated revision. Acknowledgment means *admitted to volatile writer state*, not durable. Only a successful `IndexWriter::commit` is durable. `flush` never changes visibility; `refresh` publishes a new volatile immutable view; old snapshots and PIT handles keep their exact pre-mutation masks.
- **Revisions.** One accepted operation per logical key is the next revision (`previous + 1`, first operation `1`), including tombstones for deletes of absent keys. Insert fails when the key is live; insert after a tombstone succeeds. Revision allocation follows accepted operation order under the writer lock; caller timestamps are never used.
- **Idempotency.** A nonempty token is scoped to the index and maps to a deterministic SHA-256 fingerprint over intent, logical key and every field state. Exact replay returns the original revision with `replayed = true`; reuse with a different payload fails with `IdempotencyConflict`. The finite replay ledger is bounded by count and modeled bytes; a full ledger rejects new idempotency requests before admission rather than silently evicting entries. Replay-ledger retention is independent of tombstone/data retention.
- **State format.** `MutationStateV1` carries strictly ascending key rows (`key`, `revision`, `LIVE`/`DELETED`, and for live rows the winning `(segment_id, doc_id)`) and the replay ledger. It is encoded in the shared container envelope, bound to its manifest by exact length and SHA-256, and validated before publication: pointers must resolve to in-range physical documents with matching keys and no shared winner. Legacy version-1 manifests synthesize an all-live revision-1 state from physical keys and remain readable without rewriting frozen bytes.
- **Publication ordering.** New segments, then the state sidecar, then the manifest that references it, then atomic `CURRENT` last. `CURRENT` never references an absent or invalid sidecar. An indeterminate `CURRENT` write poisons the writer for reconciliation rather than retrying blind.
- **Visibility.** Each snapshot owns an immutable per-segment live mask: a physical document is live iff its segment bitmap is set and the generation state has a `LIVE` winner at exactly that `(segment_id, doc_id)`. Term, phrase, multi-term, `NOT` and every BM25 corpus statistic consume the same effective mask, so obsolete physical documents never resurrect and cannot distort document frequency or average field length.
- **Lossless compaction.** `IndexWriter::compact` merges the current committed segments by remapping decoded postings/positions, typed columns, stored records, field norms and remap — not by re-analyzing stored records. Indexed-but-not-stored fields, positions, columns/nulls and legacy norms are preserved; revisions, tombstones and the replay ledger are carried over byte-semantically while winning pointers are updated.
- **Retention.** The only retention hook is explicit: a caller-supplied key list and nonempty policy reason admitted through the normal revisioned delete path. There are no clock reads, TTL daemon or background deletes.
- **Reclamation.** PR 9 ships conservative dry-run planning only. Independent `Index` handles own independent PIT counters, there is no cross-process reader-exclusion protocol, and `Directory::list` is bounded, so no online deletion is claimed. Unreferenced objects are classified `UNKNOWN` and are never deletable. Destructive cleanup requires a future offline-maintenance protocol.

## Typed numeric/temporal retrieval and bounded analytics (PR 10)

PR 10 adds a **single snapshot-bound typed column-scan engine** over the PR 9 effective-live
view. It reuses the existing query AST, sort contracts, typed columns, canonical group keys and
time bounds unchanged; it does **not** add a segment/manifest format, a second index, a
compound lexical+typed planner, a time-sorted physical layout or approximate analytics. The
standalone `quervant-core` engine remains independent of distributed services.

- **Entry point.** `TypedSearcher::new(&ReaderSnapshot, &Schema, SearchLimits)` exposes
  `search(TypedSearchRequest, ...)` and `aggregate(AggregateRequest, ...)`. Every query, sort,
  metric and limit is validated before any segment is opened; unsupported operators fail closed
  with a typed error and never return an empty result silently.
- **Boolean typed subset.** Only `MatchAll`, columnar `Range` (`I64`/`U64`/finite `F64`/`Timestamp`),
  half-open `TimeRange`, and recursive `And`/`Or`/`Not` execute. `And([]) = true`, `Or([]) = false`,
  and `Not` complements **effective-live** documents only. Missing, explicit null and empty
  multi-values never satisfy a positive range; multivalue ranges match if any member qualifies.
  `TimeRange` is exactly `[start, end)` in signed UTC microseconds and matches any timestamp
  member.
- **Canonical ordering.** One comparator (`typed_compare`) is shared by the bounded top-K heap,
  final ordering and cursor validation. Booleans order `false < true`, keywords by unsigned UTF-8
  bytes, timestamps by signed microseconds, floats by finite total order, and IP addresses by
  `(family, bits)` (IPv4 before IPv6). Missing and explicit null are distinct; missing/null
  placement (`First`/`Last`) does not reverse under `Desc`, while scalar values do. The logical
  `DocumentKey` is always the ascending final tie-break. `Text`, `Json`, `GeoPoint` and `Cidr`
  are not typed sort/group scalars.
- **Cursors.** `TypedCursor` is opaque and non-serializable. It binds to a process-wide unique
  snapshot identity (shared by `Arc` clones), a canonical SHA-256 fingerprint of the typed query
  and sort, the full last sort tuple and the last logical key. Page size is excluded, so
  continuation may change `top_k`. A different snapshot or changed query/sort is rejected before
  I/O; cross-process/portable cursors remain future work.
- **Aggregation.** Group by zero to three typed columnar keys (plus an optional fixed-width
  `Timestamp` bucket) with exact Cartesian expansion bounded **before** materialization and
  per-document tuple deduplication. `Missing` and `Null` are distinct components; an empty
  multi-value expands to zero groups. Buckets use `origin + floor_div(ts - origin, width) * width`
  in checked `i128`. Metrics are `Count` (documents), checked `i128`/`u128` `Sum`, Neumaier
  compensated finite `F64` `Sum`/`Avg`, `Min`/`Max` (including `Timestamp`) and exact per-group
  distinct sets. Frequency top-K is computed exactly and then truncated, with descending count
  and ascending canonical value ties. A document with multiple group values contributes once to
  each distinct group, independent of metric-value multiplicity.
- **Resource bounds.** `SearchLimits` is extended additively with defaults and hard ceilings for
  typed scan documents, typed work units, aggregate groups, aggregate state bytes, per-group
  distinct/frequency cardinality, per-document expansion, frequency top-K and cursor bytes.
  Existing candidate/heap/work bounds and applicable `Budgets` remain in force; the effective
  allowance is the minimum. Checked arithmetic and preflight-before-insertion apply throughout;
  exceeding a bound is a typed error, never truncation or clamping. Cancellation is polled on
  entry, per segment and at least every 256 charged units, with no partial response.
- **Pruning.** A segment may be skipped only by persisted `TimeBounds::prunes_positive_range` for
  a positive top-level `And` `TimeRange` conjunct on the same codec field. Unknown/absent bounds
  and predicates under `Or`/`Not` always scan. PR 9 tombstones can only widen persisted bounds,
  so pruning has no false negatives; skipped segments are counted in diagnostics. A
  test-only `with_pruning_disabled` mode enables differential verification.

## Future correctness work

Document commit atomicity, object visibility, writer fencing, cross-region publication, manifest retention/GC, distributed top-K/BM25 statistics, and partial-failure behavior before production implementation.


## Advanced text retrieval (planned, not v0.1 requirements)

Quervant intends to support three separate capabilities: **substring retrieval** (term substring versus normalized full-field-value substring), **ranked autocomplete suggestions**, and **document search-as-you-type**. The normative proposed contracts, compatibility gate, and acceptance matrix are in [Advanced text retrieval](decisions/ADVANCED_TEXT_RETRIEVAL.md). This affirms product direction, **not implementation status or release delivery**.

The existing bounded glob/regex term matching is a correctness-oriented fallback, not a guarantee of efficient arbitrary substring lookup. Optional schema-configured gram/trigram postings with exact normalized-value verification are the planned acceleration path. Prefix enumeration should reuse the planned FST/automaton infrastructure; no separate trie is required by default. Search-as-you-type composes analyzed complete terms with a final incomplete-token prefix and returns ranked documents, not suggestions.

**Format gate:** PR 5's sequential dictionary wire format remains frozen. PR 8 must explicitly resolve auxiliary FST versus versioned codec extension (or measured runtime-derived FST) before changing persistent representation. No PR 5 or PR 8 implementation scope is silently expanded.
