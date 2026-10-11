# Trawler

Trawler is an early-stage, Rust-based information retrieval system. The design separates a reusable **single-index search engine** from an independently deployable **distributed search platform**.

> **Status:** repository foundation only. Indexing, query execution, persistence, distributed coordination, and service APIs are not yet implemented. Do not use for production workloads.

## Workspace

| Crate | Scope | License |
| --- | --- | --- |
| `trawler-core` | Standalone single-index/single-shard indexing and searching | Apache-2.0 |
| `trawler-objectstore` | Provider-neutral object-storage adapters and test doubles | Apache-2.0 |
| `trawler-distributed` | Multi-shard placement, query aggregation, coordination, and rebalancing | Elastic-2.0 |

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

Trawler's general-purpose core will also treat event timestamps as first-class index fields: optional primary time field, efficient range pruning, chronological filtered retrieval and stable pagination, with minimal fixed-duration time buckets and count/sum/min/max/avg aggregations. Timestamp-sorted immutable segments and per-segment min/max time metadata aim to avoid fetching irrelevant remote objects. Late/out-of-order events must remain correct. This is a **planned v0.1 design requirement**, not implemented in PR 1. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Development

Install a stable Rust toolchain supporting edition 2024, then:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo doc --workspace --no-deps
```

The foundation uses no external runtime dependencies. RustFS integration tests and real S3 end-to-end tests will be added as storage features land.

## Licensing

The reusable crates are licensed under **Apache License 2.0**. The distributed crate is licensed under **Elastic License 2.0 (ELv2)**, a source-available license that restricts offering the licensed software as a managed service. ELv2 is **not** an OSI-approved open-source license. See [LICENSING.md](LICENSING.md) and each crate's Cargo manifest. Licensing boundaries must remain explicit when adding shared code.

## Contributions

Please read [AGENTS.md](AGENTS.md) for repository engineering conventions. Contributions and licensing questions may be discussed through GitHub issues. No contributor licensing agreement or commercial relicensing policy has yet been adopted.
