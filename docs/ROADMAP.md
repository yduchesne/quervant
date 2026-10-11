# Roadmap

This is an indicative implementation sequence, not a delivery commitment. **Release boundaries are explicit:** v0.1 is a standalone single-shard lexical search engine; v0.2 introduces multi-shard distributed search using that core; vector/ANN/hybrid search is deferred until **after v0.2** (target v0.3). No vector indexing or ANN implementation is required for v0.1 or v0.2.

## v0.1 agreed planning gates

- **Deployment modes:** standalone local-only durable index and standalone remote-backed index. Neither requires distributed services; only the remote-backed mode requires ObjectStore.
- **First remote provider:** RustFS via S3-compatible API, as the reference for portable segment materialization, bounded cache eviction/reload, cold bootstrap and failure recovery. No RustFS-specific core dependencies.
- **Storage model:** immutable segments, shared versioned formats/manifests/generation visibility, one logical writer and concurrent readers; local and remote modes have separate durability/publication mechanisms.
- **Initial cache strategy:** whole-file materialization with verification; range/partial caching deferred pending evidence. Cache eviction is distinct from authoritative remote garbage collection.
- **Pre-implementation decisions:** document/schema and writer/reader/searcher APIs, refresh/delete/update semantics, precise query/analyzer feature gate, storage sync/async boundaries, manifest publication/fencing capabilities, reader retention and resource limits.
- **Acceptance evidence:** local commit/recovery; RustFS empty-cache bootstrap, cache eviction/reload, concurrent readers, network interruption/partial-download recovery and bounded resource use; reproducible correctness and Tantivy-comparison benchmarks. Format versioning starts in v0.1 without an implicit cross-version compatibility guarantee.

## v0.1 — Standalone single-shard lexical search

1. **PR 1 — Repository foundation:** workspace, crate boundaries, licensing, README/AGENTS, architecture, basic CI. No indexing implementation.
2. **Core storage contracts:** specify the local `Directory` trait (Lucene-inspired file lifecycle and read/write handles), `SegmentStore`/`SegmentCache` layering, and independent remote `ObjectStore` capabilities; define atomicity/durability and sync/async semantics; add memory adapter, deterministic fault injection, RustFS integration harness and conformance tests.
3. **Text analysis contracts:** design per-field index/search analyzers, token positions/offsets, Unicode word/whitespace/keyword tokenizers, normalizers, stop words, stemming, and multi-fields; specify first-class glob and regex grammars, whole-term regex semantics, shared automaton execution, and resource budgets before index format and query APIs are frozen.
4. **Single-index persistence:** immutable segment codecs, durable manifests, atomic commit/recovery, cold-reader bootstrap.
5. **Core lexical search:** analyzer implementations, term dictionaries/postings, Boolean/phrase/prefix/glob/regex queries with shared FST/automaton intersection and bounded expansion, BM25, top-K, deletes and merges.

**v0.1 acceptance boundary:** a consumer can index, commit, recover, and search a single independent core index without etcd, Coordinator, Aggregator, Search Nodes, or any vector functionality. Validate an empty-cache reader bootstrap from authoritative ObjectStore and the lexical query/correctness suite.

## v0.2 — Distributed multi-shard lexical search

6. **Distributed foundations:** shard identity/prefix/routing, Coordinator etcd leadership and placement watches, independently deployed Aggregator and Search Node, shard-local core queries, distributed lexical top-K merge.
7. **Dynamic rebalancing and resilience:** reader activation/drain, placement epochs, cache warming, failure injection, leader failover, writer fencing, duplicate-replica avoidance and cross-shard result correctness.

**v0.2 acceptance boundary:** multi-shard indexes reuse the v0.1 core without adding distributed dependencies to `trawler-core`; the Aggregator fans out directly to Search Nodes using Coordinator placement updates; shard rebalancing and failure recovery preserve query correctness. **No vectors, HNSW, or hybrid retrieval in v0.2.**

## v0.3 — Vector and hybrid retrieval (after v0.2)

8. **Vector search foundation:** finalize `VectorField`/`KnnQuery` and metric/encoding contracts; add immutable dense `f32` storage, cosine/dot/Euclidean scoring, exact KNN, deletes/merges, recovery and empty-cache bootstrap.
9. **Approximate and hybrid retrieval:** benchmark segment-local HNSW against exact KNN; add metadata-filter-aware ANN with exact fallback and BM25/vector RRF `HybridQuery`; define recall, candidate oversampling, distributed merging and resource budgets.

**v0.3 target:** exact and approximate vector retrieval and hybrid search across standalone and distributed deployments. Precise feature gates and acceptance criteria will be refined in subsequent PRs.

## Later / optional extensions

- **Domain search extensions:** domain normalization, n-grams and explainable approximate domain-name matching without conflating distinct names; not a v0.1/v0.2 release blocker.
- **I/O performance evaluation:** establish portable filesystem/`mmap` baseline; benchmark opt-in Linux `io_uring` and consider SPDK/DPDK only if measured bottlenecks justify specialized backends.
- **Production hardening:** observability, load/performance benchmarks, regional readers, GC, resilience and security review, staged as needed across releases.

A later PR should define a concrete testable contract for each stage before implementation.
