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

## Distributed responsibilities

- **Coordinator**: shard placement, node membership/health, activation/draining, and control-plane epochs. Multiple instances with one active leader; etcd provides initial leader election, leases, and authoritative placement state. Stale leaders must be fenced.
- **Query Aggregator**: obtains placement from the Coordinator and watches for changes, caches routing snapshots, dispatches shard-local queries directly to Search Nodes, handles retries/deadlines, and merges results. It does not route queries through the Coordinator.
- **Search Node**: opens assigned shard readers, materializes local cache as necessary, and executes shard-local queries.
- **ObjectStore**: stores all durable shard data independent of placement.

Reader-shard rebalancing: assign destination -> cold-open from ObjectStore -> report queryable -> activate routing -> drain old assignment. No peer-to-peer data migration. Writer ownership transitions are separate and require fencing.

Each logical shard is one independent core index. Distributed search must avoid counting replicas twice and define cross-shard ranking/statistics and snapshot semantics.

## Future correctness work

Document commit atomicity, object visibility, writer fencing, cross-region publication, manifest retention/GC, distributed top-K/BM25 statistics, and partial-failure behavior before production implementation.
