# Quervant

Quervant is an early-stage, Rust-based information retrieval system. The design separates a reusable **single-index search engine** from an independently deployable **distributed search platform**.

> **Status:** early-stage, pre-v0.1 release. The standalone core implements lexical search (including bounded prefix/glob/regex/fuzzy matching and BM25), mutable document operations, typed numeric and temporal retrieval, native JSON-path querying, WGS84 point search, projections, bounded aggregation/batch execution, snapshot-bound pagination and opt-in remote RustFS/S3-backed persistence. These capabilities have implementation and test evidence, but **PR 14 acceptance and v0.1 release qualification remain incomplete**. Distributed coordination, native graph/ontology execution, and vector/hybrid retrieval are not implemented. Do not use for production workloads.

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
- **Planned native graph indexing and traversal:** a snapshot-consistent property graph with typed vertices and edges, immutable adjacency, bounded graph traversals and algorithms, and unified graph/search queries. Design only; not yet implemented or scheduled. See the [graph architecture register](docs/graph/README.md) and [graph roadmap](docs/graph/ROADMAP.md).
- **Planned native ontology indexing and inference:** typed classes and relationships, hierarchy traversal, declarative inference and ontology-aware query predicates, integrated with snapshot-consistent search. Deferred beyond v0.1; see [ontology specification register](docs/ontology/README.md) and [roadmap](docs/ROADMAP.md).
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

This section describes architectural goals; some foundations are implemented, while distributed services, graph/ontology execution and vector retrieval remain unimplemented. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

### Time-oriented search in v0.1 (implemented foundation; further capabilities planned)

The standalone core implements typed timestamp fields, bounded time-range predicates, segment pruning, snapshot-bound pagination and typed aggregations. **Still planned:** richer first-class time-series layouts, fixed-duration time buckets and optimizations beyond the existing typed/temporal implementation. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

### Native JSON and geospatial search in v0.1 (implemented foundation)

Implemented functionality includes native JSON ingestion and indexed paths, equality/existence/range/membership filtering, indexed JSON-path sorting, and WGS84 GeoPoint indexing with bounding-box, radius, point-in-polygon and distance ordering. These compose with other query predicates. JSON array structure is preserved in stored source; future correlated nested-array execution, recursive JSONPath, transformations and richer geometries remain **planned**, not implemented. PR 14 still requires acceptance closeout. See [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### General-purpose search primitives (implemented foundation)

Quervant's standalone core supports mutable application documents and append-oriented events: stable document keys, insert/upsert/delete and batch mutation operations, refresh/durable commit, PIT snapshots, typed values, stored projections, pagination and bounded composable lexical/JSON/temporal/geospatial queries. Merge/compaction and retention support exist; acceptance of the complete PR 14 surface is still pending. **Not implemented:** WAND/block-max WAND, facets, highlighting and autocomplete. Bounded fuzzy term matching **is implemented** (PR 8). See [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md) and [docs/TESTING.md](docs/TESTING.md).

For the planned v0.1 implementation PR sequence and acceptance gates, see [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md).

### Network and aggregation search primitives (implemented foundation)

The core implements typed IPv4/IPv6 exact/range/CIDR predicates, existence and null/missing semantics, set-membership filtering, bounded group-by aggregation, exact distinct counts and top-K frequent values. These compose with the unified search engine, subject to the outstanding PR 14 acceptance gates. **Still planned:** sliding-window/event-sequence correlation, cross-index joins and continuous streaming detection. See [docs/ROADMAP_V01.md](docs/ROADMAP_V01.md).

## Remote RustFS/S3 mode (opt-in, PR 13)

`quervant-core::remote` provides an opt-in remote-backed single-shard index. The remote ObjectStore is authoritative and holds the existing immutable codecs under one validated prefix; a private local workspace and the verified `SegmentCache` are disposable. The default build stays local-only and never compiles the S3 SDK or an async runtime. Remote durability is only acknowledged after a provider-enforced compare-and-swap of `index/CURRENT`.

The production adapter lives in `quervant-objectstore` behind the `s3` feature:

```toml
quervant-core = { path = "crates/quervant-core", features = ["s3"] }
```

**Safety rules for remote mode:**

- Capabilities are advertised only for an endpoint qualified by a real concurrent probe. An unqualified `S3ObjectStore` advertises no capabilities and fails closed; never assume atomic create-if-absent or conditional replace for an arbitrary S3-compatible service.
- Credentials are never logged, and integration tests target an explicit local RustFS endpoint. Do not point the test suite at public AWS by accident.
- `If-Match` performs a HEAD-capture-ETag, bounded GET + SHA-256 verify, then conditional PUT. An ETag is never treated as a content digest.

To run the real RustFS acceptance tests against a pinned local RustFS container:

```sh
QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
QUERVANT_RUSTFS_REGION=us-east-1 \
QUERVANT_RUSTFS_BUCKET=quervant-pr13 \
QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1

QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
QUERVANT_RUSTFS_BUCKET=quervant-pr13-core \
QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1
```

See [docs/pr-artifacts/pr-13/](docs/pr-artifacts/pr-13/) for provider qualification, validation and adversarial evidence.

## Native graph architecture (design only)

Quervant's [QGS-001–QGS-008 graph design register](docs/graph/README.md) specifies a future native property graph with immutable adjacency, bounded traversal/algorithms, combined graph/search queries, distributed extensions and optional ontology integration. **Architecture approved conceptually; functionality not implemented or scheduled.** See the [graph roadmap and safety gates](docs/graph/ROADMAP.md).

## Native ontology architecture (design only)

Quervant's [QOS ontology design register](docs/ontology/README.md) describes a future native ontology layer for typed classes and relationships, asserted facts, declarative inference, hierarchy reasoning and ontology-aware search. Approved conceptual foundations are documented in QOS-001–QOS-004; explanation/provenance, agent-oriented querying, capability reasoning and graph–ontology integration remain proposals. **Design only; functionality is not implemented or assigned to a release.** See the [ontology specifications](docs/ontology/README.md) and [cross-release roadmap](docs/ROADMAP.md).


## Development

Install a stable Rust toolchain supporting edition 2024, then:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo doc --workspace --no-deps
```

The foundation requires no async runtime or remote service for local mode; content digests use the audited RustCrypto `sha2` crate rather than project-authored cryptography. The opt-in remote S3/RustFS adapter and its real-backend acceptance tests are described above.

## Licensing

The reusable crates are licensed under **Apache License 2.0**. The distributed crate is licensed under **Elastic License 2.0 (ELv2)**, a source-available license that restricts offering the licensed software as a managed service. ELv2 is **not** an OSI-approved open-source license. See [LICENSING.md](LICENSING.md) and each crate's Cargo manifest. Licensing boundaries must remain explicit when adding shared code.

## Contributions

Please read [AGENTS.md](AGENTS.md) for repository engineering conventions. Contributions and licensing questions may be discussed through GitHub issues. No contributor licensing agreement or commercial relicensing policy has yet been adopted.
