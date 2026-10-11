# Roadmap

This is an indicative implementation sequence, not a delivery commitment.

1. **PR 1 — Repository foundation:** workspace, crate boundaries, licensing, README/AGENTS, architecture, basic CI. No indexing implementation.
2. **Core storage contracts:** specify the local `Directory` trait (Lucene-inspired file lifecycle and read/write handles), `SegmentStore`/`SegmentCache` layering, and independent remote `ObjectStore` capabilities; define atomicity/durability and sync/async semantics; add memory adapter, deterministic fault injection, RustFS integration harness and conformance tests.
3. **Text analysis contracts:** design per-field index/search analyzers, token positions/offsets, Unicode word/whitespace/keyword tokenizers, normalizers, stop words, stemming, and multi-fields; specify first-class glob grammar and resource budgets before index format and query APIs are frozen.
4. **Single-index persistence:** immutable segment codecs, durable manifests, atomic commit/recovery, cold-reader bootstrap.
5. **Core search:** analyzer implementations, term dictionaries/postings, Boolean/phrase/prefix/glob queries with FST/automaton intersection and bounded expansion, BM25, top-K, deletes and merges.
6. **Domain search extensions:** domain normalization, n-grams, and explainable approximate domain-name matching without conflating distinct names.
7. **Distributed foundations:** shard prefix/routing, Coordinator etcd leadership and placement watches, separate Aggregator/Search Node processes, distributed query merge.
8. **Dynamic rebalancing:** reader activation/drain, placement epochs, cache warming, failure injection, leader failover, writer fencing.
9. **I/O performance evaluation:** establish a portable filesystem/`mmap` baseline; benchmark opt-in Linux `io_uring` on local NVMe and consider SPDK/DPDK only if measured workload bottlenecks justify specialized backends.
10. **Production hardening:** observability, load/performance benchmarks, regional readers, GC, resilience, and security review.

A later PR should define a concrete testable contract for each stage before implementation.
