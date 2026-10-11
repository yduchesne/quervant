# Roadmap

This is an indicative implementation sequence, not a delivery commitment.

1. **PR 1 — Repository foundation:** workspace, crate boundaries, licensing, README/AGENTS, architecture, basic CI. No indexing implementation.
2. **Core storage contracts:** ObjectStore capabilities, memory adapter, deterministic fault injection, RustFS integration harness and adapter conformance tests.
3. **Single-index persistence:** immutable segment codecs, durable manifests, atomic commit/recovery, cold-reader bootstrap.
4. **Core search:** schema/analyzers, term dictionaries/postings, Boolean/phrase/wildcard queries, BM25, top-K, deletes and merges.
5. **Domain search extensions:** domain normalization, prefix/glob, and explainable approximate domain-name matching without conflating distinct names.
6. **Distributed foundations:** shard prefix/routing, Coordinator etcd leadership and placement watches, separate Aggregator/Search Node processes, distributed query merge.
7. **Dynamic rebalancing:** reader activation/drain, placement epochs, cache warming, failure injection, leader failover, writer fencing.
8. **Production hardening:** observability, load/performance benchmarks, regional readers, GC, resilience, and security review.

A later PR should define a concrete testable contract for each stage before implementation.
