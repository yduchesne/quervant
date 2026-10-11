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
