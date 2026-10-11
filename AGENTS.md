# Agent and contributor instructions

These instructions apply across the Trawler repository.

## Project boundaries

- `trawler-core` is a complete standalone single-index engine, not a distributed subsystem. Do not import etcd, cluster placement, RPC, node IDs, or query aggregation into it.
- `trawler-objectstore` contains reusable provider-neutral storage adapters. Do not hard-code S3 assumptions into public core contracts.
- `trawler-distributed` owns logical shards, placement, etcd integration, Coordinator, Aggregator, and distributed search. Coordinator is **control-plane only**; Aggregator performs query fan-out and result merging. They must remain independently deployable.
- A shard is a core index scoped to a durable ObjectStore prefix. Node-local caches are disposable; the ObjectStore is authoritative.
- No source or binary code may be moved from an ELv2 component into an Apache-licensed component without verifying its provenance and rights.

## Engineering rules

- Rust 2024 edition; prefer clear types, small modules, explicit errors, and minimal dependencies.
- Use Tokio for async remote I/O and orchestration when implemented; keep postings traversal and scoring synchronous and allocation-conscious.
- Index segments are immutable. Updates create new data and manifests; do not mutate committed segment files.
- A commit must be recoverable from ObjectStore alone. Never publish a manifest referencing unverified/unavailable objects.
- Separate durable commit from local reader refresh. Design writer fencing and stale-leader rejection before enabling concurrent/failover writers.
- Bound concurrency, memory, retries, and remote I/O. Avoid unbounded tasks and implicit whole-object buffering.
- Do not silently conflate DNS/domain canonicalization with similarity matching. Preserve distinct domain identities.
- Prefer descriptive tests that cover observable behavior and failure modes over implementation details.

## Local storage abstraction rules

- Plan a Lucene-inspired `Directory` trait for local index-file access: `open_read`, `create`, `delete`, `atomic_write`, `exists`, and `sync`. These names are illustrative, **not** a finalized Rust API.
- Keep `Directory` (local files) distinct from `ObjectStore` (authoritative remote persistence). Keep `SegmentStore` and `SegmentCache` responsibilities explicit.
- Candidate backends: `FsDirectory`, `MmapDirectory`, `MemoryDirectory`, optional `IoUringDirectory`; SPDK requires a separate block/segment-access contract if POSIX-like semantics cannot be upheld.
- Finalize error types, handles, lifetimes, path semantics, atomicity, durability, capability discovery, sync/async boundaries, and failure-injection tests in the core storage-contract PR. Never assume an atomic rename is automatically a durable commit.
- Ensure cold-reader bootstrap from ObjectStore works with any supported local backend. Do not couple search scoring or index formats to filesystem syscalls.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the proposed layering.

## I/O performance and portability rules

- Start with portable filesystem I/O and `mmap` for suitable immutable segment reads, plus Tokio-based asynchronous ObjectStore/network operations.
- Treat Linux `io_uring` as an **optional** local-NVMe optimization, not full kernel bypass. Do not require it for `trawler-core` to compile or function.
- Treat SPDK (user-space NVMe) and DPDK (user-space networking) as **experimental, opt-in** deployment-specific backends. Neither is an initial feature requirement.
- Do not force an SPDK backend into a filesystem/`mmap` contract: its block-device and memory models differ. Separate logical segment access, local cache backend, and remote object-storage transport.
- Keep backend-specific unsafe code isolated, justified, reviewed, and feature/platform gated; retain a portable fallback. Crate-level `forbid(unsafe_code)` must remain unless an explicitly reviewed implementation requires a narrowly scoped policy change.
- Benchmark before optimizing: compare baseline vs `io_uring` and, only where applicable, SPDK/DPDK using identical datasets, hardware, and cold/warm workloads. Report p50/p95/p99 latency, QPS, CPU, memory, cache behavior, and total I/O.
- Never claim kernel bypass, lower latency, or higher throughput without reproducible measurements. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Analysis and query semantics

- Implement composable per-field character filters, tokenizers, token filters, analyzers, and normalizers in the standalone core. Support independent index-time and search-time configurations.
- Preserve token positions, increments, offsets, and position lengths (or equivalent), including gaps introduced by stop-word removal. Version analyzer definitions and document reindexing implications.
- Initial analysis: Unicode word, whitespace and keyword tokenizers; lowercase, Unicode normalization, ASCII folding, stop words, and English stemming. Add n-grams and synonym support in planned stages.
- Support multi-fields for analyzed text, exact normalized keyword, and non-stemmed glob-searchable terms. Never automatically stem a glob pattern.
- Implement first-class `GlobQuery` with `*` (zero or more Unicode scalar values), `?` (one Unicode scalar value), and backslash escaping. A glob operates on indexed terms, not arbitrary raw document text.
- Implement first-class `RegexQuery` with whole-indexed-term matching and a bounded regular-language subset: character classes, alternation, grouping, quantifiers, bounded repetition, and Unicode classes where feasible; exclude lookarounds, backreferences, and PCRE extensions.
- Use a shared multi-term execution path for `PrefixQuery`, `GlobQuery`, and `RegexQuery`: syntax-specific compilation to automata, FST term-dictionary intersection, bounded term expansion, and postings. Never automatically stem regex patterns.
- Define regex case/Unicode/normalization/escaping semantics separately from glob syntax. Bound automaton construction/determinization, memory, time, term enumeration, and cancellation; explicitly reject over-budget queries.
- Plan automaton/FST dictionary intersection and explicit complexity, term-expansion, time, and cancellation budgets. Never silently return truncated results.
- Keep domain-specific normalization, reversed labels, Public Suffix List decomposition, n-grams, and confusable matching separate from general-purpose text analysis. Preserve exact domain identity.
- Document and test pattern normalization, escaping, Unicode behavior, offsets, phrase compatibility, and failure modes before shipping. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Vector and hybrid retrieval direction

- Treat dense vector search as a future `trawler-core` field/query capability sharing document IDs, immutable segments, manifests, `Directory`, `SegmentStore`/`SegmentCache`, and authoritative `ObjectStore`; do not build a separate vector persistence subsystem.
- Plan fixed-dimension dense `f32` `VectorField` and `KnnQuery` contracts with cosine, dot-product and Euclidean metrics; validate dimensions and non-finite values. Embeddings are supplied by clients initially.
- Implement exact KNN first as a correctness baseline. Evaluate segment-local HNSW only after benchmarking recall, latency, memory, build and merge costs.
- Design metadata-filtered KNN explicitly; unfiltered ANN followed by post-filtering does not guarantee adequate recall or `k` results. Provide an exact filtered fallback where appropriate.
- Plan `HybridQuery` using rank-based fusion (initially RRF) for BM25 and vector results; do not directly add incomparable raw scores.
- Require cold-cache ObjectStore recovery for vector segments; keep HNSW graph traversal local with bounded memory and cache warmup, not per-edge remote fetches.
- Distributed ANN must define candidate oversampling, cross-shard scoring/fusion, recall evaluation and cancellation. Keep all vector functionality independent of distributed services.
- Vector support is **architectural scope only** until lexical search works; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Validation

Before proposing a PR, run where feasible:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo doc --workspace --no-deps
```

Report commands not run and why. Never claim a test passed without executing it. Keep changes scoped; document new APIs, persistence formats, and compatibility implications.

## Testing direction

- Fast unit tests and deterministic in-memory ObjectStore/failure-injection tests.
- Shared ObjectStore adapter conformance suite.
- RustFS container-backed integration tests for the S3-compatible adapter.
- Mandatory cold-reader test: a fresh reader with empty cache and no writer-local state opens committed shard data from RustFS.
- Real AWS S3 end-to-end tests in controlled scheduled/release CI with least-privilege credentials, unique prefixes, and cleanup.
- Distributed tests for placement watches, rebalancing, stale epochs, leader loss, quorum loss, and result merging.

## Licensing and documentation

- `trawler-core`, `trawler-objectstore`: Apache-2.0.
- `trawler-distributed` and planned distributed services: Elastic-2.0 unless explicitly changed.
- Respect third-party dependency licenses. Do not describe ELv2 components as OSI open source.
- Update README, architecture docs, and roadmap when an implementation changes documented assumptions.
- Do not imply a planned capability is implemented.
