# Roadmap

This is an indicative implementation sequence, not a delivery commitment. **Release boundaries are explicit:** v0.1 is a standalone single-shard lexical search engine; v0.2 introduces multi-shard distributed search using that core; vector/ANN/hybrid search is deferred until **after v0.2** (target v0.3). No vector indexing or ANN implementation is required for v0.1 or v0.2.

For the numbered v0.1 implementation PR register, dependencies, acceptance criteria and progress status, see [ROADMAP_V01.md](ROADMAP_V01.md). This cross-release roadmap remains the source for release boundaries.

**Cross-subsystem sequencing:** [Distributed / Graph / Ontology integration roadmap](INTEGRATION_ROADMAP.md) coordinates shared identity, immutable storage, typed query IR, snapshots and PR ownership without changing the separate release and architecture authorities. It adopts overlapping architectural planning and staged implementation, with explicit DG-P1/DG-P2 and QOS gates.

Testing philosophy, fake/mock selection, conformance suites, fault injection and integration topology are defined in [TESTING.md](TESTING.md).

## Cross-release testing quality gates

- **At least 85% automated line coverage** across applicable production Rust workspace crates, measured reproducibly and enforced in CI. Document reviewed exclusions; do not inflate coverage by excluding difficult production paths.
- Every executable-code PR must include relevant **unit and integration tests**, with real filesystem/RustFS or service-boundary coverage where applicable. Deterministic fakes are supplemental, not a substitute for required production-path integration.
- Coverage, unit tests, integration/fault-injection acceptance, and correctness checks are independent release/PR gates. A required test that has not executed is not a pass. Documentation-only changes may declare code testing not applicable.
- Record actual commands, test environment, results, and any BLOCKED or failing gates before declaring completion. See [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md).

## Approved v0.1 optional domain-search extensions

The v0.1 implementation register in [ROADMAP_V01.md](ROADMAP_V01.md) assigns optional DNS/IDNA canonicalization, reversed-label keys, Public Suffix List registered-domain decomposition and UTS #39 confusable skeletons to **PR 4**. It assigns bounded general-purpose fuzzy term search and basic domain-aware fuzzy matching to **PR 8**. These are general-purpose schema-configurable primitives, not a separate domain-intelligence engine. Exact domain identity, derived keys and similarity matches remain distinct and versioned; advanced weighted domain similarity and domain-impersonation scoring are deferred beyond v0.1. PR 3 storage scope is unchanged.

## v0.1 agreed planning gates

- **Deployment modes:** standalone local-only durable index and standalone remote-backed index. Neither requires distributed services; only the remote-backed mode requires ObjectStore.
- **First remote provider:** RustFS via S3-compatible API, as the reference for portable segment materialization, bounded cache eviction/reload, cold bootstrap and failure recovery. No RustFS-specific core dependencies.
- **Storage model:** immutable segments, shared versioned formats/manifests/generation visibility, one logical writer and concurrent readers; local and remote modes have separate durability/publication mechanisms.
- **Initial cache strategy:** whole-file materialization with verification; range/partial caching deferred pending evidence. Cache eviction is distinct from authoritative remote garbage collection.
- **Pre-implementation decisions:** document/schema and writer/reader/searcher APIs, refresh/delete/update semantics, precise query/analyzer feature gate, storage sync/async boundaries, manifest publication/fencing capabilities, reader retention and resource limits.
- **Acceptance evidence:** local commit/recovery; RustFS empty-cache bootstrap, cache eviction/reload, concurrent readers, network interruption/partial-download recovery and bounded resource use; reproducible correctness and Tantivy-comparison benchmarks. Format versioning starts in v0.1 without an implicit cross-version compatibility guarantee.

Benchmark architecture and measurement rules are specified in [BENCHMARKING.md](BENCHMARKING.md). v0.1 includes reproducible **Quervant, Tantivy and Apache Lucene** local-engine runners, correctness-gated comparisons, and a separate RustFS remote-cache benchmark lane. Relative performance parity is not a release gate.

## Post-v0.1 native ontology architecture (design only)

Approved conceptual architecture is documented in the [versioned QOS-001–QOS-004 specification register](ontology/README.md), including mutation encoding (QOS-003A), cross-segment adjacency (QOS-003B), and inference invalidation (QOS-003C). [QOS-005](ontology/QOS-005.md) registers a **proposed, not-yet-approved** inference explanation and provenance interface, potentially useful to evidence-driven consumers such as ATI. **No ontology implementation or implementation PR planning is authorized before v0.1 completion.** Ontology has no assigned delivery milestone; these specifications are not implemented features or finalized binary formats.

## v0.1 — Standalone single-shard lexical search

1. **PR 1 — Repository foundation:** workspace, crate boundaries, licensing, README/AGENTS, architecture, basic CI. No indexing implementation.
2. **Core storage contracts:** specify the local `Directory` trait (Lucene-inspired file lifecycle and read/write handles), `SegmentStore`/`SegmentCache` layering, and independent remote `ObjectStore` capabilities; define atomicity/durability and sync/async semantics; add memory adapter, deterministic fault injection, RustFS integration harness and conformance tests.
3. **Text analysis contracts:** design per-field index/search analyzers, token positions/offsets, Unicode word/whitespace/keyword tokenizers, normalizers, stop words, stemming, and multi-fields; specify first-class glob and regex grammars, whole-term regex semantics, shared automaton execution, and resource budgets before index format and query APIs are frozen.
4. **Single-index persistence:** immutable segment codecs, durable manifests, atomic commit/recovery, cold-reader bootstrap.
5. **Core lexical search:** analyzer implementations, term dictionaries/postings, Boolean/phrase/prefix/glob/regex queries with shared FST/automaton intersection and bounded expansion, BM25, top-K, deletes and merges.

**v0.1 acceptance boundary:** a consumer can index, commit, recover, and search a single independent core index without etcd, Coordinator, Aggregator, Search Nodes, or any vector functionality. Validate an empty-cache reader bootstrap from authoritative ObjectStore and the lexical query/correctness suite.

### First-class time-series retrieval in v0.1

Temporal retrieval is **in scope for v0.1**, not deferred to distributed or vector releases. The core remains general-purpose: an optional index-level primary timestamp field with per-segment physical-layout metadata enables time-oriented indexes without imposing time ordering on all indexes.

- **Query acceptance:** UTC timestamp range filters, conjunction with lexical/exact filters, ascending/descending time ordering, deterministic top-K and cursor pagination; late/out-of-order arrivals remain correct.
- **Analytics acceptance:** fixed-duration time buckets, exact count and numeric sum/min/max/average. High-cardinality group-by, percentiles, moving averages, downsampling, rollups and SQL parsing are outside this v0.1 gate.
- **Format acceptance:** per-segment timestamp min/max and layout flag; timestamp-sorted segment option (default for time-oriented indexes), safe doc-ID remapping during sorting/merges; block bounds/skipping where the sorted-block format supports it. Prune irrelevant remote segments before materializing them.
- **Storage acceptance:** shared local/remote format and manifests, bounded whole-file cache in v0.1, future range-read-friendly layout without requiring range caching now.
- **Verification:** half-open bounds, ties/pagination, filter combinations, time buckets and numeric aggregates, missing/duplicate timestamps, late events, deletes/merges, crash recovery and RustFS cold-cache pruning. Reproducible recent-window query/aggregation benchmarks include remote bytes fetched and cache/segment touches.

In the implementation sequence, the core contract stage defines timestamp schema, temporal query and aggregation contracts; persistence defines temporal metadata, sorting and block layout; lexical query execution also implements temporal filtering/sorting and bounded aggregations. See [ARCHITECTURE.md](ARCHITECTURE.md).

### Native JSON and geospatial v0.1 acceptance

Native JSON and geospatial point search are **v0.1 scope**, sharing the typed field model, immutable segments and query IR with lexical and temporal retrieval.

- **JSON:** ingest and return structured JSON, index nested typed scalar paths, support exact/range/existence predicates, scalar-array membership, indexed-path sorting, and compile a documented RFC 9535-inspired JSONPath subset to typed query operations. Define null/missing, mixed-type and multivalue semantics and bound dynamic path discovery.
- **JSON future-proofing:** preserve nested arrays and parent/element identity in stored source; define extensible query IR, versioned structural capabilities and old-segment correctness/migration policy for later correlated nested-array predicates, recursive JSONPath and JSON transformations/projections. Do not implement those advanced operators in v0.1.
- **Geospatial:** typed WGS84 GeoPoint and GeoJSON Point input, bounding-box, radius, point-in-polygon and distance sorting; correct antimeridian handling, stable ties, exact candidate verification, and conjunction with time/JSON/lexical predicates.
- **Spatial future-proofing:** geometry type/codec and query extension points for lines/polygons/multipolygons and spatial relations, multi-valued point ancestry, segment-level conservative bounds, pluggable immutable spatial access (BKD-like or cell postings), and no spatial-index dependence on distributed infrastructure.
- **Delivery staging:** field/schema/query IR and JSON/geo semantics before format freeze; then segment codecs and typed column/spatial access; then query operators and compound planner integration; then local/RustFS acceptance and workload benchmarks. PR 11 (merged as GitHub PR #31, with DFS hardening in #32) delivers JSON path extraction, concrete-path equality and existence, but **not** JSON range predicates, scalar-array membership, indexed-path sorting or public stored-source selection. Those remain v0.1 obligations owned by PR 14 and qualified in PR 15, not post-v0.1 deferrals. PR 1 documents these requirements but adds no implementation.

**v0.1 acceptance boundary additionally includes:** JSON source round-trip and nested-array preservation, indexed-path filter/sort correctness, spatial bbox/radius/polygon correctness at boundaries and antimeridian, combined time+geo+JSON queries, sorted/merged/deleted segment consistency, and empty-cache RustFS recovery. Future-feature support is an extensibility/correctness contract, not a promise of full JSONPath or rich geometry execution in v0.1.

### General-purpose search primitive contract gate (v0.1)

Before freezing segment/manifest formats, approve and document:

- Stable logical document keys, deterministic insert/update/upsert/delete ordering, immutable-segment tombstones/live-docs, merge/GC and retention behavior.
- Refresh versus durable commit guarantees, crash recovery, snapshot/PIT readers and snapshot-bound search-after cursors.
- Typed field descriptors, positional postings, skip/block structures, DocValues-like per-document columns, missing/null/multivalue sorting, and basic stored-field selection/projection.
- Unified typed query IR, score/filter composition, deterministic sort/top-K, postings intersections, time/spatial pruning, bounded execution and explicit query-budget errors.
- Append-event and mutable-document policy profiles on the same standalone core; neither changes correctness or durability.
- Format/manifest versioning, capability flags, compatibility/reindex rules and validation fixtures.

**v0.1 functional scope:** include key-based upsert/update/delete and refresh/PIT semantics, columnar sorting/aggregation, basic projections and deterministic pagination alongside previously specified lexical, time, JSON and geo operations. Stage implementation across small follow-on PRs: (1) contracts/fixtures, (2) immutable codecs and columnar/live-doc storage, (3) mutation and snapshot lifecycle, (4) query operators/planner, (5) local/RustFS fault and performance evidence. Avoid bundling all features into one implementation PR.

**Deferred optimizations/features:** WAND/block-max WAND, cost-based planning, facets, fuzzy matching, highlighting, autocomplete, substring acceleration, advanced JSONPath, rich geometry and high-cardinality analytics. Reserve extension points, not v0.1 delivery obligations. v0.2 distributed and post-v0.2 vector/hybrid release boundaries remain unchanged.

### Network and aggregation primitives in v0.1

The v0.1 standalone core also targets **native IPv4/IPv6 exact/range/CIDR queries**, **bounded group-by aggregations** over one or more typed fields, **exact distinct counts**, **top-K frequent field values**, and universal typed `EXISTS`/`MISSING`/`IS NULL`/`IN`/`NOT IN` predicates. These capabilities serve security logs, observability, networking and application analytics without introducing SIEM-specific rule processing.

Before the segment-format freeze, PR 2 must define address-family normalization/ordering, CIDR and multivalue semantics, missing/null/negation truth tables, group-key and distinct-count semantics, stable top-K ties and resource-exhaustion behavior. PR 5 supplies typed storage/DocValues support, PR 10 aggregation operators, PR 14 query composition, and PR 15 qualification. Aggregations must honor live documents and PIT snapshots, with bounded memory and explicit errors rather than silent truncation. See [ROADMAP_V01.md](ROADMAP_V01.md).

**Still deferred:** sliding/rolling windows, event-sequence correlation, sessionization, cross-index joins/lookup enrichment, continuous queries/streaming detection, approximate distinct counts, materialized aggregation acceleration and SIEM query-language compatibility. These are not prerequisites for v0.1.

## v0.2 — Distributed multi-shard lexical search

**Approved distributed direction, with proposed cross-index scope extension; not implemented.** The normative v0.2 architecture is in [distributed design register](distributed/README.md). The proposed [D01–D15 implementation roadmap](distributed/ROADMAP.md) and [XJ-001 cross-index foundation](distributed/10-CROSS-INDEX-FOUNDATION.md) add a dependency-oriented work-package plan; these IDs are **planning labels, not GitHub PR numbers**. Implementation details and acceptance still require fresh-main PR plans and safety qualification.

### Minimum complete distributed engine

- Stable versioned logical-shard routing, Coordinator/etcd HA and placement, reader activation/drain, failure-domain-aware recovery and capacity admission.
- Separate stateless Query Aggregator with direct Search Node fan-out, strict completeness by default, generation-specific readiness, snapshot-bound retries and cursor retention.
- Distributed lexical/typed execution using shard-local `quervant-core`: globally comparable **within-index** BM25 (`GLOBAL_STATS` default), exact supported analytics and ordered scans, unified mixed predicates, predicate/projection/partial-aggregation pushdown, physical-plan capability negotiation, global work budgets.
- **Cross-index query foundation (XJ-001):** cluster index catalog and stable IndexId; index-aware document identity; typed schema reconciliation; higher-level scan/filter/project/UNION ALL/aggregate logical plans; pinned multi-index generation vectors and exact supported multi-index search, global ordering, analytics, pagination, and streaming. Incomparable per-index relevance scores must not be silently merged. See [XJ-001](distributed/10-CROSS-INDEX-FOUNDATION.md).
- **Finite distributed result streaming (C7):** compose existing core pull-based bounded batches through Search Node streaming RPCs and a backpressured Query Aggregator, preserve global sorted-order correctness, snapshot pins, cancellation, final/partial/error framing and bounded per-hop memory. Exact blocking operators cannot emit unfinalized results. **Both Axum HTTP NDJSON and native Tonic gRPC server streaming are mandatory external v0.2 interfaces**, backed by one transport-neutral SearchService, while Tonic/Prost is the internal RPC stack. See [DS-001 service and presentation architecture](distributed/09-SERVICE-PROTOCOLS.md), [distributed streaming specification](distributed/07-STREAMING.md) and [core streaming contract](STREAMING_SEARCH.md).
- Stateless Indexing Coordinator, fenced single authoritative writer per logical shard, durable idempotent mutation identities/revisions, per-shard partial outcomes and distinct `ACCEPTED`/`DURABLE`/`SEARCHABLE` semantics.
- Publication Authority with qualified ObjectStore CAS and FP-002 fencing, safe snapshot retention and GC-002 protection (destructive remote GC stays disabled until its proof gate passes), DR-002 recovery barriers and metadata reconciliation.
- Real etcd and RustFS/S3-compatible integration, deterministic concurrency/failure injection and existing workspace quality gates.

### Service and transport architecture (DS-001)

[DS-001](distributed/09-SERVICE-PROTOCOLS.md) establishes a shared service layer for search, mutation and lifecycle operations, independent of protocol DTOs; Tonic/Prost over gRPC is the sole initial internal RPC framework and the native gRPC client transport; Axum provides HTTP JSON and event-framed NDJSON finite query-result streaming. Query execution, snapshot management, global merge and mutation semantics live exclusively in shared service implementations. NDJSON completion requires a terminal event; a dropped HTTP connection is not successful completion. Conformance across protocols, slow-consumer flow control, authentication, cancellation and typed errors are required for v0.2. gRPC-Web, WebSocket, SSE and CLI pipeline syntax remain optional future adapters.

### Explicit exclusions and gates

No vectors, ANN, hybrid retrieval, general SQL, **executable** distributed joins/shuffle (including graph/ontology joins), automatic resharding, durable ingestion journal, dedicated writer-only nodes, predictive autoscaler, continuous subscriptions, CDC or live-tail query feeds. Multi-index UNION/analytics is included in the proposed v0.2 extension; a reserved Join/Exchange IR operator is **not** an implementation commitment. Join and Exchange are future physical-plan extension points only. Fixed logical shard count limits parallel shard writers.

**Mandatory preimplementation safety gates:** qualified pointer CAS and exclusive publication authorization; proof of GC publication/deletion barrier before enabling destructive remote collection; recovery-generation fencing under etcd rollback; complete distributed query snapshot/budget/merge correctness. See [safety protocols](distributed/06-SAFETY-PROTOCOLS.md). Do not infer implementation completion from approved documents.

**v0.2 acceptance boundary:** multiple logical shards are independently committed and recoverable, single-index queries merge globally comparable results without duplicate replicas or silent partiality; multi-index UNION preserves source identity, typed schema semantics and exact supported global operations under explicit index-set snapshots; finite streaming queries enforce bounded backpressure, global ordering where requested, snapshot consistency and explicit terminal outcomes, ingestion preserves idempotency/durability under writer failover, and control-plane failures cannot bypass fencing. `quervant-core` retains standalone operation without distributed dependencies.

## v0.3 — Vector and hybrid retrieval (after v0.2)

8. **Vector search foundation:** finalize `VectorField`/`KnnQuery` and metric/encoding contracts; add immutable dense `f32` storage, cosine/dot/Euclidean scoring, exact KNN, deletes/merges, recovery and empty-cache bootstrap.
9. **Approximate and hybrid retrieval:** benchmark segment-local HNSW against exact KNN; add metadata-filter-aware ANN with exact fallback and BM25/vector RRF `HybridQuery`; define recall, candidate oversampling, distributed merging and resource budgets.

**v0.3 target:** exact and approximate vector retrieval and hybrid search across standalone and distributed deployments. Precise feature gates and acceptance criteria will be refined in subsequent PRs.

## Planned native ontology indexing and inference (post-v0.1; unassigned milestone)

Quervant plans **native ontology indexing and inference** as a first-class extension of the standalone core, not merely graph traversal. The design includes index-local versioned ontologies; typed classes, multiple inheritance and disjointness; asserted directed relationships; reusable archetypes and named hierarchy families; deterministic positive-rule inference; strict atomic consistency validation; immutable-segment adjacency and snapshot-scoped execution; and universally URN-identified query operators with namespace unions and fatal ambiguity detection. Ontology-aware predicates must compose with lexical and other typed search.

**Specification references:** [Ontology specification register and design status](ontology/README.md) tracks QOS-001 (semantic model), QOS-002 (archetypes and inference), QOS-003 (physical architecture), and QOS-004 (universal operator namespaces). Detailed physical subdesigns QOS-003A (mutation encoding), QOS-003B (cross-segment adjacency), and QOS-003C (inference invalidation) are documented as approved conceptual specifications; implementation-specific API, codec and parser contracts remain future work. Proposed [graph–ontology composition](ontology/GRAPH-ONTOLOGY-INTEGRATION.md) and [QOS-009 agent-oriented discovery](ontology/QOS-009.md) add non-binding cross-layer interfaces. The register distinguishes approved conceptual decisions from design details not yet written as normative standalone specifications.

**Release boundary:** finish v0.1 first. Ontology implementation is **not** part of v0.1, does not alter its PR acceptance gates, and has no assigned implementation PR, release number, or delivery date. Do not begin ontology implementation PR planning until v0.1 is complete and the specifications are consolidated and design-closed. Distributed ontology execution is deferred separately.

## Later / optional extensions

- **Domain search extensions:** domain normalization, n-grams and explainable approximate domain-name matching without conflating distinct names; not a v0.1/v0.2 release blocker.
- **I/O performance evaluation:** establish portable filesystem/`mmap` baseline; benchmark opt-in Linux `io_uring` and consider SPDK/DPDK only if measured bottlenecks justify specialized backends.
- **Deferred lexical performance — shared decoded field norms (identified in PR 7 Amendment 05):** `SegmentReader::open` currently eagerly decodes persisted BM25 field norms, and search reconstructs segment readers for each request. Consequently, repeated searches incur O(document count × indexed scoring fields) decoding/allocation work even though immutable norms were persisted to avoid rescanning postings. Evaluate a snapshot- or immutable-segment-scoped cache of **validated decoded norms** only after profiling and representative repeat-query benchmarks demonstrate material benefit (candidate post-v0.1/v0.2 performance work; **no assigned PR or release commitment**). Design must preserve immutable segment identity and snapshot/PIT consistency, cross-thread sharing without mutable aliasing, compatibility with legacy segments, fail-closed integrity validation, explicit decoded-memory budgets and eviction/lifetime accounting, and correctness during commits, refresh, and concurrent searches. Compare cold/warm latency, allocations, RSS, and multi-reader concurrency against the uncached baseline; require identical search results and BM25 scores. Do not expand PR 7, alter its accepted on-disk format, or make this a v0.1 acceptance gate.
- **Future — Graph indexing, retrieval and traversal (unassigned milestone; related to ontology):** Explore optional native graph indexing as an extension of Quervant's general-purpose search engine, **not** a commitment to build a full graph database. Candidate capabilities include directed, typed relationships; indexed incoming/outgoing adjacency; bounded breadth-first and depth-first traversal; K-hop neighborhood expansion; and unweighted shortest-path queries. Graph operations should eventually compose with typed predicates, temporal filters and snapshot-consistent retrieval. Design evaluation must address stable vertex and edge identity distinct from segment-local document IDs, immutable-segment and merge compatibility, edge deletion/live-doc visibility, traversal fan-out/memory/time budgets, and efficient local/ObjectStore access. **Validation-first delivery:** begin with edge documents and repeated indexed neighbor lookups, measure correctness and traversal cost on representative graphs, and introduce dedicated segment-local adjacency codecs only if benchmarks justify them. **Explicit non-goals:** no graph-specific implementation, public graph APIs, adjacency codecs or graph tests in v0.1; no current commitment to distributed graph execution, PageRank, community detection, graph query languages or graph-database functionality. No release number or delivery date is assigned. Existing stable identity, versioned optional segment capabilities and extensible typed query IR should avoid unnecessarily foreclosing this future direction without adding speculative graph contracts now.
- **Production hardening:** observability, load/performance benchmarks, regional readers, GC, resilience and security review, staged as needed across releases.

A later PR should define a concrete testable contract for each stage before implementation.


### Prospective ontology research (not approved)

[QOS-008 — Capability and State-Transition Reasoning](ontology/QOS-008.md) is a **prospective, unapproved** architecture research candidate. It explores whether bounded hypothetical-state and capability-path analysis belongs in Quervant or an independent solver using Quervant's snapshot ontology queries. AWS IAM privilege-escalation analysis is an illustrative reference workload, not a committed built-in feature. No implementation or v0.1 scope change is authorized.

[**QOS-009 — Ontology Discovery and Agent-Oriented Query Planning**](ontology/QOS-009.md) is a **prospective, unapproved** architecture candidate. It would expose machine-readable ontology/operator catalogs, capability discovery, canonical typed query IR, query validation and plan diagnostics, and typed results with explicit completeness/budget status. Agent-side natural-language interpretation, task decomposition, external-tool orchestration, and answer synthesis remain outside Quervant. The design should support one-query and multi-query workflows without requiring an embedded LLM or agent runtime. **Architectural design priority:** ahead of exploratory QOS-006 confidence propagation and QOS-008 state-transition reasoning; no implementation commitment or v0.1 scope change.

### Advanced text retrieval — affirmed future capabilities

The product roadmap explicitly includes **optional accelerated substring search**, **ranked autocomplete**, and **search-as-you-type** as distinct, separately planned features. See [Advanced text retrieval contracts](decisions/ADVANCED_TEXT_RETRIEVAL.md). Term-substring matching using bounded glob/regex is distinct from efficient full-field-value substring retrieval; an optional per-field gram index with exact verification is the intended acceleration strategy. Autocomplete reuses planned FST prefix enumeration and adds bounded ranking/deduplication. Search-as-you-type combines completed-token retrieval with an incomplete final-token prefix and document ranking.

**Sequencing:** documentation/contracts first (this documentation-only change); PR 8 keeps its current multi-term scope; approve FST/PR 5 codec compatibility before persistence changes; then separately plan autocomplete, search-as-you-type, and gram-backed substring implementation. No delivery release is assigned and none of these three accelerated/UX capabilities is newly promised in v0.1.


### PR 13 remote-storage delivery status (2026-10-15)

The v0.1 remote ObjectStore/RustFS implementation (PR 13) has been merged. Remote committed state remains authoritative; local cache materialization is verified and disposable. Real RustFS acceptance includes fault-injected HTTP/CAS publication, process-crash recovery and local/remote query equivalence. Query-scoped **pre-materialization** pruning (V08) was explicitly **deferred, not implemented**, and is tracked in [issue #37](https://github.com/yduchesne/quervant/issues/37); conservative query correctness remains mandatory. See [v0.1 roadmap](ROADMAP_V01.md) and [PR 13 acceptance](pr-artifacts/pr-13/validation-report.md).


## Post-v0.1 native graph architecture (documentation only)

The [QGS-001–QGS-008 graph specification register](graph/README.md) and [graph implementation roadmap/review](graph/ROADMAP.md) describe approved conceptual native property-graph, immutable storage, traversal, algorithms, combined search/graph queries, distributed graph processing, ontology integration and temporal/weighted graph architecture. **None are implemented or assigned to a release by this documentation.** Existing v0.1/v0.2 boundaries and v0.3 vector target are unchanged. Distributed graph is post-v0.2 and requires DG-P1 cross-shard mutation and DG-P2 qualified graph-snapshot protocols before unrestricted execution. Managed assertion authority requires an explicit QOS amendment; QOS-005/QOS-008 and other proposed ontology extensions retain separate approval gates.
