# Trawler architecture (design targets)

> This document records intended architecture, not implemented features.

## Release boundaries

- **v0.1:** standalone single-index/single-shard lexical core, including analysis, BM25, Boolean/phrase/prefix/glob/regex search, immutable segments, commit/recovery, and ObjectStore cold bootstrap. No cluster runtime dependencies.
- **v0.2:** multi-shard distributed lexical search built on the unchanged standalone core, with Coordinator/etcd, separate Query Aggregator and Search Nodes, placement and rebalancing.
- **v0.3 target (post-v0.2):** vector fields, exact KNN, ANN/HNSW, metadata-filtered vector retrieval, and hybrid BM25/vector fusion. Vector support is **not a delivery requirement for v0.1 or v0.2**.

See [docs/ROADMAP.md](ROADMAP.md) for release acceptance boundaries.

## First-class temporal retrieval (v0.1 design target)

Trawler is a **general-purpose lexical search engine** with first-class timestamped-event/log retrieval, not a specialized time-series database. This requirement is part of the v0.1 architecture, although PR 1 only documents it.

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

Trawler uses **one general-purpose typed document model**, shared by lexical, numeric, temporal, JSON and geospatial retrieval. JSON is a first-class ingestion/return format, not a required representation for non-JSON clients. PR 1 records contracts only; no JSON or spatial query engine is implemented here.

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

Trawler is a **general-purpose search engine**, not an append-only log engine. Structured events and logs are important workloads, but must not constrain document mutation, relevance ranking or standalone embedded/local use. The following are design contracts for follow-on PRs; PR 1 remains documentation/foundation only.

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

### Unified query IR, execution and safety

- Use one typed query IR for lexical ranking, Boolean filters, numeric/time ranges, JSONPath-compiled predicates, geographic predicates, sorting, bounded aggregation and **basic field-selection projection**. Selecting stored fields is v0.1; arbitrary JSON restructuring/transformation remains deferred.
- Define filter-vs-score behavior, relevance score and deterministic tie rules, missing/null sort order, multi-valued field sort selectors, pagination/search-after semantics and PIT binding. Preserve consistent results across merges and storage backends.
- Support a deterministic correctness-first execution planner with index-driven candidate generation, intersection, optional time/spatial pruning and bounded top-K. Instrument plan choices and bytes/segments touched. Cost-based planning and WAND variants are future optimizations, not required to satisfy v0.1 correctness.
- Bound query execution by configurable limits (candidate count, multi-term expansion, regex automata/work, scanned bytes, memory, result window, timeout/cancellation, aggregation buckets, JSON depth and spatial complexity). Specify explicit resource-exhaustion errors and avoid unbounded full-source scans.
- Future fuzzy search, facets, highlighting, autocomplete, substring indexing, recursive JSONPath, correlated nested-array predicates and rich geometry require reserved operator/codec extension points; their full execution is not a v0.1 requirement.

### Workload policies, not separate engines

- **Append-oriented event profile:** optional primary event timestamp, late arrivals, timestamp-oriented segment layout, time-based retention, time-first pruning and ingestion-oriented flush/merge defaults.
- **Mutable document profile:** stable keys, update/upsert/delete, relevance-oriented access, PIT consistency, flexible indexing and merge defaults.
- Profiles select policies (schema discovery, indexing, layout, flush/merge, cache and retention) but **never alter query correctness, document identity or durability semantics**. Both use the same standalone `trawler-core` API, codecs and manifest lifecycle; neither depends on distributed services.
- Benchmark cost, indexing throughput, p50/p95 latency, read amplification, memory, object-store operations and recovery against relevant Tantivy/Lucene baselines and, where comparable, Quickwit. Do not assert differentiation or superior performance without measurements.

**Design gate before implementing immutable codecs:** approve stable document identity/mutation order, refresh/commit/PIT semantics, field and columnar value contracts, query IR and projection semantics, live-doc/tombstone/retention lifecycle, format compatibility, workload policy boundaries and query resource budgets. Keep v0.2 distributed and post-v0.2 vector milestones unchanged.

## Separation of concerns

- **Core**: a self-contained index writer/reader/searcher, immutable segments, postings, scoring, manifests, refresh, and recovery.
- **ObjectStore adapters**: provider-independent operations, including streamed/ranged reads, durable writes, and explicit capabilities. S3-compatible adapters should support RustFS and AWS S3; additional providers may follow.
- **Distributed**: shard identity and routing, control plane, query aggregation, and search-node hosting.

Dependency direction: `trawler-distributed -> trawler-core`. The core must never depend on the distributed crate. Storage contracts must remain usable without distributed infrastructure.

## v0.1 decisions: standalone lifecycle and release gates

**Agreed design targets (not implemented by PR 1):** v0.1 supports both **fully local durable indexes** and **remote ObjectStore-backed indexes**. They share segment codecs, manifest representation, generation semantics, reader visibility, indexing, and search execution; durability/publication mechanisms differ. A local-only index must not require a running object-storage service. A remote-backed index treats remote committed state as authoritative and local materialized segments as disposable.

Use **one logical writer per index**, concurrent readers, immutable committed segment generations, and explicit refresh/commit visibility. Define update/delete semantics, background merges, old-reader retention, and crash recovery in the v0.1 lifecycle contracts. Version on-disk/on-object formats from the outset, but do not promise cross-version compatibility until explicitly specified.

Before implementation PR decomposition, finalize document/field schema, writer/reader/searcher API and lifecycle, query/analysis feature acceptance, local and remote commit publication and recovery, cache limits, and synchronous hot-path versus asynchronous I/O boundaries. Measure correctness and performance against a reproducible baseline (including Tantivy on equivalent data and hardware), without promising performance superiority.

### RustFS-first remote validation and portability

Use **RustFS as the first remote ObjectStore reference implementation**, accessed through the **S3-compatible API**, not RustFS-specific engine hooks. The remote `ObjectStore` interface must describe capabilities and failure semantics needed by the engine; avoid relying on provider-specific atomicity, conditional writes, or listing consistency without verifying them. A portable adapter must permit future S3-compatible and other remote providers without changing index formats or search logic.

Start with **whole-file immutable segment materialization** to a bounded local cache; validate integrity before exposing cached files to readers. Eviction and re-download are cache operations, never deletion of authoritative objects. Treat remote segment garbage collection separately, subject to committed-manifest retention and reader safety. Add range reads, partial caching, prefetch or swapping refinements only after cold/warm workload measurements justify their complexity.

RustFS-backed acceptance/fault-injection scenarios must cover: empty-cache reader bootstrap; warm-cache reuse; cache eviction and re-materialization; multiple concurrent readers; committed-manifest visibility only after all referenced objects are durable; restart/recovery; network timeout, interrupted/partial download and corrupted object handling; bounded disk/memory usage; and provider portability. Remote commits must never expose incomplete generations. Define local durable commit and remote publication protocols separately while retaining shared logical generation/visibility rules. Do not assume local atomic rename is durable without synchronization, or that an S3-compatible provider offers atomic compare-and-swap without explicit verification.

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

**Planned abstraction; API signatures are illustrative and not yet implemented.** Following Lucene's directory concept, `trawler-core` will expose a local `Directory` contract to separate index-file lifecycle and access from a concrete local filesystem implementation:

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
trawler-core indexing / searching
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

## Text analysis, field indexing, and multi-term queries

**Design target only; no analyzer or query execution code exists in PR 1.** Text analysis is a core capability, not an application-side preprocessing requirement. It must be independent of distributed search and configured per field.

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

### Domain-oriented analysis (optional specialization)

Domain names are identifiers, not English prose. Keep canonical exact identity separate from similarity matching. A specialized analyzer may index normalized exact domain, reversed labels, individual labels, registered domain (using Public Suffix List), and n-grams. IDNA and DNS canonicalization rules must be specified, tested, and versioned. A reversed representation is an optimization, not a change to domain identity. Approximate matching (e.g. confusables and weighted substitutions) is a separate query/ranking capability. Keep domain-specific features optional so `trawler-core` remains a general-purpose search engine.

### Required validation in later PRs

Cover Unicode boundaries, offsets/positions and stop-word gaps, stemming behavior, multi-field selection, wildcard escaping, literal wildcard terms, leading wildcards, pattern normalization, automaton/FST equivalence against a simple reference matcher, query cancellation and resource limits, and domain identity preservation.

## Dense vector and hybrid retrieval (future scope)

**Architectural commitment, not implemented in PR 1.** Trawler will support vector search as an additional field-indexing and query capability within the standalone core, reusing document IDs, immutable segments, manifests, local `Directory`, `SegmentStore`/`SegmentCache`, and authoritative `ObjectStore`. Do not create an independent vector database or require an embedding model/provider in the core.

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

- **Coordinator**: shard placement, node membership/health, activation/draining, and control-plane epochs. Multiple instances with one active leader; etcd provides initial leader election, leases, and authoritative placement state. Stale leaders must be fenced.
- **Query Aggregator**: obtains placement from the Coordinator and watches for changes, caches routing snapshots, dispatches shard-local queries directly to Search Nodes, handles retries/deadlines, and merges results. It does not route queries through the Coordinator.
- **Search Node**: opens assigned shard readers, materializes local cache as necessary, and executes shard-local queries.
- **ObjectStore**: stores all durable shard data independent of placement.

Reader-shard rebalancing: assign destination -> cold-open from ObjectStore -> report queryable -> activate routing -> drain old assignment. No peer-to-peer data migration. Writer ownership transitions are separate and require fencing.

Each logical shard is one independent core index. Distributed search must avoid counting replicas twice and define cross-shard ranking/statistics and snapshot semantics.

## Dispatch strategy and hot-path performance

**Design policy for v0.1 and later, not an implemented optimization.** Prefer static dispatch (concrete types or generic trait bounds) in CPU-bound inner loops where per-item indirect calls can inhibit inlining or specialization. Do **not** ban `dyn Trait` globally: choose dispatch granularity based on measured costs.

- **Static-dispatch candidates:** postings iterators, term-dictionary/FST transitions, segment decoding, BM25 scoring, Boolean/phrase execution, and high-volume token processing. Design generic/concrete interfaces so the compiler can monomorphize and optimize these paths when beneficial.
- **Runtime-variable query plans:** query trees may contain heterogeneous scorer types. Consider enum-based dispatch or query-plan specialization, ideally dispatching outside the per-document inner loop. An enum match still incurs runtime branching and is not automatically faster than a trait object.
- **Coarse-grained boundaries:** `dyn Trait` is acceptable for `Directory`, `ObjectStore`, pluggable backends, service orchestration, and similar operations where I/O, allocation, or network latency dominates. A single indirect call per batch/block is different from one per posting/document.
- **Tradeoffs:** monomorphization can increase compilation time, binary size, and instruction-cache pressure; generic and async trait APIs can also complicate ownership and ergonomics. Avoid premature generic propagation through entire call stacks.
- **Required evaluation before freezing hot-path APIs:** benchmark representative static-generic, enum-dispatch, and `dyn Trait` scorer/postings designs on identical data and hardware. Measure QPS, p50/p95/p99 latency, CPU/cycles, allocations, code size and compile-time costs. Profile real workloads, including term, conjunction, disjunction and phrase queries, before claiming a dispatch strategy is faster.

**Rule:** no *avoidable* dynamic dispatch inside performance-critical inner loops; permit it at coarse-grained boundaries or when benchmarks show it is acceptable.

## Logging, tracing, and telemetry boundaries

**Planned v0.1 policy; no telemetry runtime is implemented by PR 1.** Use the Rust `tracing` crate as Trawler's standard structured event/span **instrumentation API**. Do not introduce a custom `Tracer` trait or a generic span-wrapper layer merely to support hypothetical framework swaps. The instrumentation API and the collection/export implementation are separate decisions.

- `trawler-core` may depend on `tracing` but must **not** install a global subscriber or require `tracing-subscriber`, OpenTelemetry SDK/exporters, an OTLP Collector, Prometheus, Jaeger, Loki, or Grafana. An embedding application owns telemetry configuration; the core remains usable with no subscriber.
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

## Future correctness work

Document commit atomicity, object visibility, writer fencing, cross-region publication, manifest retention/GC, distributed top-K/BM25 statistics, and partial-failure behavior before production implementation.
