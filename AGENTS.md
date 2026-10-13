# Agent and contributor instructions

These instructions apply across the Trawler repository.

## Release sequencing

- **v0.1:** deliver a standalone single-shard lexical `trawler-core` with persistence/recovery and ObjectStore cold bootstrap; no distributed services or vector support required.
- **v0.2:** introduce multi-shard distributed lexical search by composing the v0.1 core with Coordinator/etcd, separate Aggregator/Search Nodes, placement, and rebalancing; never introduce cluster dependencies into `trawler-core`.
- **After v0.2 (v0.3 target):** implement dense vectors, exact KNN, HNSW/ANN, metadata-filtered KNN and hybrid RRF. Preserve the architecture contracts but do not implement vector functionality as a v0.1/v0.2 prerequisite.
- Optional domain-specific extensions and specialized I/O backends are not release blockers unless explicitly scoped in a later plan.

## Project boundaries

- `trawler-core` is a complete standalone single-index engine, not a distributed subsystem. Do not import etcd, cluster placement, RPC, node IDs, or query aggregation into it.
- `trawler-objectstore` contains reusable provider-neutral storage adapters. Do not hard-code S3 assumptions into public core contracts.
- `trawler-distributed` owns logical shards, placement, etcd integration, Coordinator, Aggregator, and distributed search. Coordinator is **control-plane only**; Aggregator performs query fan-out and result merging. They must remain independently deployable.
- A shard is a core index scoped to a durable ObjectStore prefix. Node-local caches are disposable; the ObjectStore is authoritative.
- No source or binary code may be moved from an ELv2 component into an Apache-licensed component without verifying its provenance and rights.

## Engineering rules

- Rust 2024 edition; prefer clear types, small modules, explicit errors, and minimal dependencies.
- **No custom cryptography:** Do not implement, reimplement, or modify cryptographic algorithms or primitives in project code, including encryption/decryption, hashes (e.g. SHA-256), MACs, signatures, key derivation, random-number generation, or cryptographic protocols. Use established, actively maintained, security-reviewed libraries with appropriate licensing instead (for example RustCrypto `sha2` for SHA-256). Do not use a hand-written implementation to avoid a dependency, build-tool issue, or environment limitation. A wrapper around a vetted library is allowed if it does not implement the primitive itself. If no suitable library exists or a required dependency cannot build, **STOP**, report the blocker, and request explicit human approval for a separately reviewed exception; never silently ship custom cryptography. Tests with published vectors do not substitute for cryptographic review.
- Use Tokio for async remote I/O and orchestration when implemented; keep postings traversal and scoring synchronous and allocation-conscious.
- Index segments are immutable. Updates create new data and manifests; do not mutate committed segment files.
- A commit must be recoverable from ObjectStore alone. Never publish a manifest referencing unverified/unavailable objects.
- Separate durable commit from local reader refresh. Design writer fencing and stale-leader rejection before enabling concurrent/failover writers.
- Bound concurrency, memory, retries, and remote I/O. Avoid unbounded tasks and implicit whole-object buffering.
- Do not silently conflate DNS/domain canonicalization with similarity matching. Preserve distinct domain identities.
- Prefer descriptive tests that cover observable behavior and failure modes over implementation details.

## Dispatch and hot-path performance rules

- Prefer concrete types and generic trait bounds (static dispatch) for CPU-bound per-posting, per-document, per-term, per-token and per-decoded-value operations when they enable inlining and measurable optimization.
- Avoid **avoidable** `dyn Trait` calls inside tight scoring, postings, FST traversal, and codec loops; do not impose a blanket prohibition on trait objects.
- Heterogeneous runtime query trees may use enums or specialized execution plans. Enum matching is still runtime dispatch; move selection outside hot loops where practical and benchmark alternatives.
- Allow dynamic dispatch at coarse-grained boundaries such as `Directory`, `ObjectStore`, pluggable I/O adapters, and distributed orchestration. Do not force generics across remote/async stacks without evidence of benefit.
- Balance monomorphization against code bloat, compile time, instruction-cache effects and API complexity.
- Before finalizing scorer and postings-iterator APIs, benchmark static generics, enum dispatch and `dyn Trait` under comparable workloads; report throughput, tail latency, CPU, allocations and code size. Never assert a dispatch strategy is faster without measurement.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architectural rationale.

## Agreed v0.1 storage and lifecycle decisions

- Support **both** standalone local-only durable indexes and remote ObjectStore-backed indexes; never require remote services for local mode. Keep codecs, manifest schema, index generation/visibility, indexing and searching shared.
- RustFS is the **first reference remote ObjectStore**, reached via an S3-compatible adapter. Do not couple `trawler-core` or segment formats to RustFS-specific APIs or unverified S3 consistency/conditional-write guarantees.
- Remote committed objects/manifests are authoritative in remote-backed mode; cached local segments are disposable. Local-only mode uses a separate durable local commit/recovery protocol with equivalent logical visibility semantics.
- Initially materialize and verify complete immutable segment files into a bounded local cache; make partial/range caching and swapping optimizations evidence-driven.
- Distinguish cache eviction from remote garbage collection; remote deletion requires committed-generation retention and reader-safety rules.
- Model one logical index writer, multiple concurrent readers and generation-based visibility. Specify refresh, update/delete, merge, old-reader retention and recovery contracts before implementation.
- Version index formats from v0.1, but do not assert cross-version compatibility without an explicit policy.
- Include RustFS fault-injection and conformance tests: cold bootstrap, cache reuse/eviction/reload, interrupted/corrupt downloads, concurrent readers, publication ordering, recovery and resource bounds. Benchmark representative workloads against Tantivy on comparable hardware.

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
- Vector support is **architectural scope only until after v0.2**; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Logging and telemetry engineering rules

- Standardize on the `tracing` crate for structured events and spans. Do **not** create a custom `Tracer` trait or span abstraction solely for backend interchangeability.
- `trawler-core` may emit `tracing` events/spans but must not initialize a global subscriber or depend on `tracing-subscriber`, OpenTelemetry SDK/exporters or monitoring services. Applications embedding the core own subscriber installation.
- Service binaries own subscriber/exporter initialization, filtering, sampling, nonblocking output, lifecycle and shutdown. Treat `tracing-subscriber` as replaceable collection infrastructure, not part of core APIs. A switch to `fastrace` instrumentation is a separate API migration requiring benchmarks.
- **Do instrument:** request/query and query-plan boundaries, indexing batches, segment flush/merge/commit, reader refresh/recovery, cache fill and ObjectStore calls; in v0.2, Aggregator fan-out, Search Node shard requests, Coordinator placement/leadership and rebalancing. Propagate trace context between services.
- **Do not instrument per item in hot loops:** avoid routine per-posting, per-document, per-score, per-token, per-FST-transition and per-decoded-value spans/events. Prefer aggregated counters/histograms recorded outside the loop.
- No synchronous log formatting, blocking writes or telemetry export on search/scoring hot paths. Fine-grained diagnostics require explicit opt-in, bounded volume and benchmark evidence.
- Use appropriate runtime and compile-time filters; guard expensive field calculations explicitly. Disabled tracing is cheap but not assumed free.
- Bound sampling, queue sizes, batching and exporter resource usage; document drops/backpressure and ensure collector outages cannot stall query execution.
- Keep metric labels low-cardinality; avoid raw queries, terms, document/user identifiers and sensitive data in telemetry by default.
- Benchmark no-subscriber, filtered, default-production and verbose-diagnostic modes on representative indexing/search workloads; include exporter failure and report QPS, p50/p95/p99, CPU, allocations and dropped telemetry. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Mandatory local validation before completion

For every code-bearing task, **the coding agent must execute all applicable checks locally after its final changes and before claiming the work is DONE, ready for review, or complete**. A passing remote CI run does not replace local verification; local verification does not replace required CI or real-service acceptance. Do not use “where feasible” to waive a required gate.

Run from the workspace root (using the project's supported toolchain):

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo doc --workspace --no-deps
```

- **Toolchains:** continuous integration runs the current stable Rust toolchain (`dtolnay/rust-toolchain@stable`), while the workspace `rust-version` (MSRV) is pinned to Rust 1.85. Run Clippy, tests, and formatting with **both** `cargo +1.85.0 …` and the stable `cargo …`. A clean MSRV Clippy does **not** guarantee clean stable Clippy: newer stable lints (for example `clippy::manual_contains`) can fail CI even when 1.85 passes. Report both command sets and results; do not claim a single-toolchain pass satisfies the lint gate.

- **Unit tests:** run the complete applicable unit-test suite and add meaningful tests for new/changed behavior, edge cases, invalid inputs and failure paths. Do not add assertion-free tests or tests that merely invoke functions to inflate coverage.
- **Integration and conformance tests:** run every applicable existing integration/contract/regression suite and the real production-path tests required by the task's PR plan. As new filesystem, RustFS, or distributed integration harnesses become available, execute them when their functionality is affected. Do not substitute mocks/fakes for mandatory real-boundary tests.
- **Lint and static analysis:** run Clippy with warnings denied, plus any additional repository-configured or PR-mandated static/security analysis (for example dependency, unsafe-code, license, or secret checks) when applicable. Report exact commands and results; do not claim checks that do not exist.
- **Coverage:** measure line coverage of **all applicable production Rust workspace code**, with a hard floor of **85%**, using the exact command above. Both unit and integration tests may contribute to the combined metric; there is no invented separate numeric unit-test-only threshold. Inspect coverage output for uncovered new/changed behavior, not just the aggregate percentage. Add or improve behavior-focused tests for uncovered areas and rerun coverage until the threshold passes. Never lower the floor, omit production crates/modules, or manipulate exclusions to force a pass. Any exclusions require explicit human review and documentation.
- **Final rerun:** after the last source, test, manifest, or CI-related change, rerun every affected mandatory check, including workspace coverage for code/test changes. Do not rely on a result from before the final patch.
- **Unavailable or failing checks:** if required tools, permissions, containers, services, or other prerequisites prevent local execution, attempt reasonable setup without unsafe system changes. Report the exact blocker, commands attempted, and impact; mark the task **BLOCKED / NOT VERIFIED**, not DONE. Do not silently substitute CI results, alternate commands, or fabricated evidence. A human may explicitly authorize a documented exception; absent that approval, the completion gate remains open.
- **Documentation-only tasks:** explicitly record why code/test/coverage checks are not applicable. Run any relevant documentation/link/format validation and do not claim code tests were executed.

The final coding-agent report must include the tested commit/working-tree state; a per-command PASS/FAIL/BLOCKED/NOT APPLICABLE table; actual test counts and measured line-coverage percentage when applicable; required integration topology; unresolved failures; and any authorized exceptions. **A green CI status alone is insufficient evidence for a local-completion claim.**

## Mandatory test coverage and integration gates

- **Minimum 85% automated line coverage** for the Rust workspace's production code, measured by an explicitly documented, reproducible coverage tool and CI command (for example `cargo llvm-cov`). Coverage must be computed across all applicable production crates, not selectively reported from well-tested modules; exclude generated code and test-only code only through documented, reviewed exclusions.
- Every implementation PR must add or update **relevant unit tests and integration tests**. Unit tests alone do not satisfy acceptance when the change crosses real component, filesystem, network, or service boundaries. A PR limited to documentation or other non-executable changes may state that code tests are not applicable.
- Integration tests must exercise the actual production path appropriate to the change: local filesystem commit/restart/recovery; RustFS S3 adapter, segment materialization/cache, and cold bootstrap; analyzer→writer→commit→reader→query; or distributed service integration in v0.2. Use deterministic fixtures and fault injection, but do not substitute a fake adapter for a required real-boundary integration test.
- CI must enforce the 85% coverage floor and required integration suites. Coverage is necessary but **not sufficient**: correctness, negative/failure cases, persistence invariants, and required integration acceptance must pass independently.
- Plans must specify coverage command, scope, exclusions, test topology, integration scenarios, and exact evidence. Do not mark a PR DONE when coverage is below 85%, a mandatory integration test has not run, or a required gate fails. If required infrastructure is unavailable, report BLOCKED rather than silently omitting the gate.

- **Authoritative testing philosophy:** read [docs/TESTING.md](docs/TESTING.md). Prefer real algorithm implementations, stateful deterministic fakes at external boundaries, and `mockall` for narrow interaction assertions. Require relevant unit AND integration tests and the 85% workspace coverage gate; fake-based unit tests do not replace RustFS/filesystem production-path integration.

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
