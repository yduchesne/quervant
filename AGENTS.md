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
