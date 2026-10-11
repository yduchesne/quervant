# Trawler architecture (design targets)

> This document records intended architecture, not implemented features.

## Separation of concerns

- **Core**: a self-contained index writer/reader/searcher, immutable segments, postings, scoring, manifests, refresh, and recovery.
- **ObjectStore adapters**: provider-independent operations, including streamed/ranged reads, durable writes, and explicit capabilities. S3-compatible adapters should support RustFS and AWS S3; additional providers may follow.
- **Distributed**: shard identity and routing, control plane, query aggregation, and search-node hosting.

Dependency direction: `trawler-distributed -> trawler-core`. The core must never depend on the distributed crate. Storage contracts must remain usable without distributed infrastructure.

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

## Text analysis, field indexing, and glob queries

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

### Domain-oriented analysis (optional specialization)

Domain names are identifiers, not English prose. Keep canonical exact identity separate from similarity matching. A specialized analyzer may index normalized exact domain, reversed labels, individual labels, registered domain (using Public Suffix List), and n-grams. IDNA and DNS canonicalization rules must be specified, tested, and versioned. A reversed representation is an optimization, not a change to domain identity. Approximate matching (e.g. confusables and weighted substitutions) is a separate query/ranking capability. Keep domain-specific features optional so `trawler-core` remains a general-purpose search engine.

### Required validation in later PRs

Cover Unicode boundaries, offsets/positions and stop-word gaps, stemming behavior, multi-field selection, wildcard escaping, literal wildcard terms, leading wildcards, pattern normalization, automaton/FST equivalence against a simple reference matcher, query cancellation and resource limits, and domain identity preservation.

## Distributed responsibilities

- **Coordinator**: shard placement, node membership/health, activation/draining, and control-plane epochs. Multiple instances with one active leader; etcd provides initial leader election, leases, and authoritative placement state. Stale leaders must be fenced.
- **Query Aggregator**: obtains placement from the Coordinator and watches for changes, caches routing snapshots, dispatches shard-local queries directly to Search Nodes, handles retries/deadlines, and merges results. It does not route queries through the Coordinator.
- **Search Node**: opens assigned shard readers, materializes local cache as necessary, and executes shard-local queries.
- **ObjectStore**: stores all durable shard data independent of placement.

Reader-shard rebalancing: assign destination -> cold-open from ObjectStore -> report queryable -> activate routing -> drain old assignment. No peer-to-peer data migration. Writer ownership transitions are separate and require fencing.

Each logical shard is one independent core index. Distributed search must avoid counting replicas twice and define cross-shard ranking/statistics and snapshot semantics.

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
