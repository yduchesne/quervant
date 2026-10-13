# Quervant

Quervant is an early-stage, Rust-based information retrieval system. The design separates a reusable **single-index search engine** from an independently deployable **distributed search platform**.

> **Status:** early-stage foundation. The typed document/field/query contracts, storage contracts (`Directory`, `ObjectStore`, `SegmentCache`), the text-analysis subsystem, immutable segment/manifest codecs, and the **local insert-only index lifecycle** (single cooperating writer, flush, non-durable refresh, durable commit/recovery, immutable reader snapshots and process-local PIT handles) are implemented and conformance-tested. Query execution, updates/deletes/merges/GC, remote RustFS/S3 mode and distributed coordination, vector search, and service APIs are **not yet implemented**. Do not use for production workloads.

## Workspace

| Crate | Scope | License |
| --- | --- | --- |
| `quervant-core` | Standalone single-index/single-shard indexing and searching | Apache-2.0 |
| `quervant-objectstore` | Provider-neutral object-storage adapters and test doubles | Apache-2.0 |
| `quervant-distributed` | Multi-shard placement, query aggregation, coordination, and rebalancing | Elastic-2.0 |

The crates share one Git repository but may be versioned and distributed separately. The distributed crate depends on the core, never the reverse. Service binaries (Coordinator, Aggregator, Search Node) will be added as distinct deployable targets in later PRs.

## Planned releases

- **v0.1 — Single-shard lexical core:** independent index writer/reader/searcher, configurable analysis, BM25, Boolean/phrase/prefix/glob/regex queries, immutable segments, durable commits and ObjectStore recovery. No distributed infrastructure required.
- **v0.2 — Multi-shard distributed lexical search:** Coordinator with etcd, independent Query Aggregator and Search Nodes, shard routing, distributed top-K, rebalancing and failure recovery. Reuses the v0.1 core.
- **v0.3 target — Vector and hybrid retrieval:** dense embedding fields, exact KNN, HNSW/ANN, metadata filtering and BM25/vector RRF. **Deferred until after v0.2.**

These are planned milestones, not shipped releases or committed dates. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Architecture goals

- Lucene-inspired inverted indexing: immutable segments, term dictionaries, postings, positions, BM25, Boolean/phrase/prefix/glob/regex queries, merges, and generation-based commits.
- **Configurable per-field text analysis:** character filters, Unicode/keyword tokenization, normalization, stop words, stemming, n-grams, and multi-fields; first-class `*`/`?` glob and regular-language regex queries through shared automaton/FST term-dictionary intersection with explicit query budgets (no PCRE backreferences or lookarounds).
- **Future vector and hybrid retrieval:** fixed-dimension dense embedding fields, cosine/dot/Euclidean exact KNN, later segment-local HNSW, metadata-filtered ANN, and BM25/vector rank fusion (RRF). Embeddings are client-supplied; vector segments share the existing ObjectStore-first persistence model. These features are deferred until after v0.2.
- A core engine usable without etcd, network services, shard identifiers, or cluster infrastructure.
- Provider-independent **ObjectStore** as the authoritative durable home of committed segments and manifests; disposable local caches/workspaces; Tokio for asynchronous remote I/O, synchronous hot scoring loops.
- A logical shard is an independent core index under an index-specific `shards/<shard-id>/` object prefix. Shard identities do not depend on compute-node identities.
- **Coordinator**: placement/control plane only, multiple instances, leader election and fencing through etcd.
- **Query Aggregator**: caches placement updates from Coordinator, fans out directly to search nodes, and merges distributed top-K results.
- **Search Nodes**: host assigned shard readers and disposable caches.
- Reader rebalancing changes placement; new nodes bootstrap directly from ObjectStore. No peer-to-peer shard data migration.
- A committed shard manifest is published only after its referenced objects are durable and verified. Writer failover needs fencing; cross-shard snapshot consistency requires explicit coordination.
- **Performance portability:** conventional filesystem I/O and `mmap` for local immutable segments, with optional benchmark-driven Linux `io_uring` acceleration. Full kernel-bypass technologies (SPDK for NVMe and DPDK for networking) remain experimental and require separate backend designs; neither is a prerequisite.

These are architectural intentions, **not currently shipped features**. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

### Time-oriented search in v0.1 (planned)

Quervant's general-purpose core will also treat event timestamps as first-class index fields: optional primary time field, efficient range pruning, chronological filtered retrieval and stable pagination, with minimal fixed-duration time buckets and count/sum/min/max/avg aggregations. Timestamp-sorted immutable segments and per-segment min/max time metadata aim to avoid fetching irrelevant remote objects. Late/out-of-order events must remain correct. This is a **planned v0.1 design requirement**, not implemented in PR 1. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

### Native JSON and geospatial search in v0.1 (planned)

Quervant plans native JSON ingestion and typed nested-path indexing, an efficiently indexable JSONPath subset, filtering/sorting on indexed JSON fields, and WGS84 geographic point search (bounding boxes, radius, point-in-polygon and distance ordering). These share the lexical and temporal query engine and immutable ObjectStore-compatible segment model. The v0.1 design must preserve JSON array structure and provide versioned extension points for future correlated nested-array queries, recursive JSONPath, JSON transformations/projections and richer geometries. **These are design targets, not features implemented in PR 1.** See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

### General-purpose search primitives (v0.1 design commitments)

Quervant is planned as a general-purpose standalone search core supporting both append-oriented event collections and mutable application documents. The v0.1 design includes stable logical document keys; insert, update, upsert and delete; refresh/commit and point-in-time reader semantics; typed per-document columnar values for sorting/aggregation; basic stored-field projections; deterministic snapshot-bound pagination; and bounded composable lexical, JSON, temporal and geospatial queries. Event and mutable-document profiles may tune layout, retention and caching without changing correctness or durability. More advanced optimizations such as WAND/block-max WAND, facets, fuzzy search, highlighting and autocomplete remain staged beyond the foundational implementation. These are **planned contracts and release targets, not implemented functionality in PR 1**. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/TESTING.md](docs/TESTING.md).

For the planned v0.1 implementation PR sequence and acceptance gates, see [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md).

### Network and aggregation search primitives (v0.1 planned)

The v0.1 design also includes typed IPv4/IPv6 fields with exact, range and CIDR predicates; bounded group-by aggregates; exact distinct counts; top-K frequent field values; and consistent typed existence, null/missing and set-membership filters. These are broadly useful for security logging, observability and structured application search. They must compose with lexical, JSON, temporal and geospatial predicates and respect reader snapshots and query resource budgets. Sliding-window/event-sequence correlation, cross-index joins and streaming detection are deferred. **These are planned capabilities, not implemented features.** See [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md).

## Development

Install a stable Rust toolchain supporting edition 2024, then:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo doc --workspace --no-deps
```

The foundation requires no async runtime or remote service for local mode; content digests use the audited RustCrypto `sha2` crate rather than project-authored cryptography. RustFS integration tests and real S3 end-to-end tests will be added as storage features land.

## Licensing

The reusable crates are licensed under **Apache License 2.0**. The distributed crate is licensed under **Elastic License 2.0 (ELv2)**, a source-available license that restricts offering the licensed software as a managed service. ELv2 is **not** an OSI-approved open-source license. See [LICENSING.md](LICENSING.md) and each crate's Cargo manifest. Licensing boundaries must remain explicit when adding shared code.

## Contributions

Please read [AGENTS.md](AGENTS.md) for repository engineering conventions. Contributions and licensing questions may be discussed through GitHub issues. No contributor licensing agreement or commercial relicensing policy has yet been adopted.
