# Testing Philosophy and Engineering Policy

This document is the authoritative Trawler testing policy for human contributors, reviewers, and coding agents. Read it alongside [ARCHITECTURE.md](ARCHITECTURE.md), [BENCHMARKING.md](BENCHMARKING.md), [ROADMAP.md](ROADMAP.md), and [../AGENTS.md](../AGENTS.md).

## Guiding principle

**Test real search-engine behavior with real implementations whenever practical. Fake external or nondeterministic boundaries, not the search algorithms or the architecture under test. Mock interactions only when the interaction itself is the behavior under test.**

The purpose of tests is to establish correct indexing, query semantics, immutable snapshot visibility, durability, recovery, and operational behavior—not merely to confirm that methods were invoked. A passing mock expectation cannot prove segment integrity, BM25 correctness, filesystem durability, or RustFS compatibility.

## Testing techniques and intended use

| Technique | Primary purpose | Trawler examples |
|---|---|---|
| **Real implementations** | Verify actual behavior and integration | Segment codecs, analyzers, FSTs, postings, BM25, filesystem operations |
| **Fakes** | Exercise real logic under deterministic conditions | `MemoryDirectory`, `FakeObjectStore`, controlled failures |
| **Mocks** | Verify interactions and protocol contracts | Expected ObjectStore calls, retries, cancellation |
| **Fault injection** | Verify failure handling and recovery | Partial writes, corrupted downloads, timeouts, commit interruptions |
| **Real-service integration** | Verify compatibility with external systems | RustFS S3 API, filesystem restart, eventually etcd |

A fake is a working, stateful test implementation of a boundary. A mock is an expectation-driven substitute used to assert calls or arguments. A stub returns canned values without necessarily maintaining state. A fault-injection wrapper can surround a real implementation or fake and fail at specified operations. Do not conflate these mechanisms in PR plans or test reports.

## Mocking standard: `mockall`

- Use **`mockall`** as Trawler's standard Rust mocking crate, as a **dev-dependency** in crates that need interaction tests. Pin the version through the workspace lockfile and verify the current compatible release before adding it. An illustrative dependency declaration is `mockall = "0.15"`; this document does not claim that dependency is already installed.
- Use mocks for narrow, coarse-grained trait-boundary interactions: expected method calls, argument predicates, call counts, retries, and cancellation-related protocol behavior.
- Do **not** mock analyzers, token streams, FST transitions, postings traversal, BM25 scoring, segment codecs, or the query executor in tests intended to establish their correctness.
- Do **not** introduce dynamic dispatch or mock-oriented abstractions into performance-critical production loops merely to make tests easier. Use static/generic dispatch where appropriate.
- Do not add a trait solely to accommodate `mockall` without an architectural justification; test through existing public contracts first.
- A mock-based unit test never substitutes for a required real-boundary integration test.

## Preferred fakes and reusable test support

Prefer a **stateful deterministic `FakeObjectStore`** implementing the same verified provider-neutral contract as the production ObjectStore adapter. It should model object identity, bytes, writes, reads, deletes, and contractually supported conditional operations—not invent consistency or CAS semantics unavailable to the production adapter.

Use `MemoryDirectory` for fast deterministic directory-contract tests; it may also be a supported in-memory backend, rather than a test-only fake. Reuse existing implementations if present. Do not introduce duplicate `Directory`/`ObjectStore` abstractions.

A proposed (not yet implemented) shared layout, justified when several crates need common fixtures:

```text
trawler-test-support/
├── storage/
│   ├── memory_directory.rs
│   ├── fake_object_store.rs
│   └── fault_injection.rs
├── fixtures/
│   ├── documents.rs
│   └── indexes.rs
└── assertions/
    ├── search_results.rs
    └── index_integrity.rs
```

Keep test-only fakes, helpers, and `mockall` out of release runtime dependencies. Production-quality `MemoryDirectory` is an intentional exception when part of the supported Directory API.

## Required test layers

1. **Unit tests:** deterministic algorithm tests, boundary/negative cases, parser and analyzer semantics, postings/FST/BM25 reference results, manifest validation, budget limits, and isolated failure handling.
2. **Contract/conformance tests:** a reusable behavior suite run against every relevant implementation of a shared interface (e.g., `MemoryDirectory`, `FsDirectory`, `MmapDirectory`; fake and real ObjectStore adapters for the contract they both claim). Tests must not assume unsupported remote guarantees.
3. **Integration tests:** actual production components and boundary adapters; local filesystem commit/restart/recovery, RustFS S3 upload/read/manifest publication, segment cache materialization/eviction/reload, and analyzer→writer→commit→reader→query. v0.2 adds real distributed service/etcd integration.
4. **Fault-injection and recovery tests:** deterministic interrupted writes, short reads, corrupted segment bytes, incomplete downloads, cache failures, commit publication failures, crash/restart, concurrent reader snapshots, and bounded retry/cancellation behavior as relevant.
5. **Benchmarks:** follow [BENCHMARKING.md](BENCHMARKING.md). Trawler local-only vs Tantivy vs Lucene requires equivalent semantics and correctness gates; RustFS cold/warm/cache tests are separate. Performance results are not substitutes for correctness tests.

For every implementation PR, require relevant **unit tests AND integration tests**. If the changed behavior is purely internal and has no meaningful new integration boundary, the plan must identify the existing integration suite that exercises it and run that suite; do not create a contrived fake integration test. Documentation-only changes may explicitly mark code-test gates not applicable.

## Canonical production-path examples

```text
Local durability:
real analyzer -> real writer -> real segments -> FsDirectory
    -> durable commit -> process/reopen boundary -> real reader -> verified query

Remote durability:
real segment codec -> real SegmentStore/SegmentCache
    -> production S3 adapter -> RustFS
    -> empty-cache reader bootstrap -> verified query

Unit fault injection:
real segment codec -> real SegmentStore/SegmentCache
    -> deterministic failing Directory/ObjectStore
    -> typed failure + no incomplete visible generation
```

A fake ObjectStore validates core failure handling; only the real RustFS integration validates S3 adapter behavior. A restart test using an in-memory Directory does not validate filesystem durability.

## Mandatory coverage and CI gates

- **At least 85% automated line coverage** across applicable production Rust workspace code. Enforce the threshold in CI using a documented, reproducible tool and command, such as `cargo llvm-cov` once configured. Do not invent an already-working command before the harness exists.
- Exclude generated or test-only code only with explicit, reviewed, documented rationale. Do not omit hard-to-test production modules or crates to inflate coverage.
- Coverage is necessary but insufficient: targeted unit tests, relevant integration tests, negative/failure cases, and correctness assertions are separate mandatory gates.
- Record coverage scope, tool/version, command, exclusions, environment and measured percentage. Required tests must actually execute and pass; merely compiling a test or adding it to the repository is not evidence.
- CI enforcement and integration harness implementation are planned work until verified present on current main.

## Deterministic fault and state cases

| ID | Scenario | Required assertion |
|---|---|---|
| S1 | Segment write interrupted | No partial segment exposed to a reader |
| S2 | Segment bytes corrupted | Integrity verification rejects the segment |
| S3 | Manifest publication fails | Previous committed generation remains visible |
| S4 | Cache evicts unpinned segment | Authoritative remote object remains intact; reload works |
| S5 | Reader holds pinned segment during eviction | Existing reader remains valid |
| S6 | Remote download interrupted | Partial cache entry never becomes readable; retry can recover |
| S7 | Cold reader with empty cache | Bootstrap succeeds from committed RustFS objects |
| S8 | Writer commits while readers are active | Readers see complete old or new generations, never mixed state |
| S9 | Retried operation after uncertain outcome | No conflicting committed generation |
| S10 | Query term expansion exceeds budget | Deterministic bounded rejection |

These are reference cases; individual PR plans select relevant cases and add exact fixtures, operation boundaries, and expected error types. Do not claim an unsupported remote conditional-write guarantee.

## Temporal retrieval acceptance matrix (v0.1)

The time-series requirement is tested against **real index codecs, writers and readers**, not mock scorers. Use fixed UTC fixtures and reference/oracle results:

| ID | Scenario | Required assertion |
|---|---|---|
| T1 | Half-open ranges, empty windows, precision and UTC normalization | Exact boundary membership and stable typed errors for invalid ranges |
| T2 | Duplicate timestamps, missing primary timestamps, deterministic pagination | No duplicates/omissions across pages, stable tie-break order |
| T3 | Time predicate + exact/Boolean/lexical predicates | Correct intersection and ascending/descending top-K |
| T4 | Late and out-of-order event-time data | All eligible records found independent of ingestion sequence |
| T5 | Fixed-duration buckets, count, sum/min/max/avg | Exact reference results including empty/null/overflow semantics defined by the contract |
| T6 | Timestamp-sorted segment creation, merging, deletion | All postings/stored-field/doc-ID references consistent after remapping |
| T7 | Segment min/max pruning and block skipping where applicable | Pruned segments/blocks not read; boundary-overlapping data not dropped |
| T8 | Local restart and RustFS empty-cache reader | Temporal queries and aggregates correct after reopen; irrelevant remote objects not materialized |
| T9 | Cache eviction, interrupted materialization and recovery | No partial or inconsistent temporal results or exposed partial generation |

Benchmark with controlled timestamp distributions (uniform, clustered, skewed, late arrivals), short versus wide windows, filter selectivity, and cold/warm caches. Report actual bytes downloaded, objects and segments touched, p50/p95/p99 latency, throughput, memory and ingestion/merge overhead. A measurable performance claim requires recorded test evidence; correctness is mandatory irrespective of improvement.

## JSON and geospatial acceptance matrix (v0.1)

Use real writers, segment codecs, readers, typed query operators and independent reference/oracle evaluations. Exercise local and RustFS-backed indexes; mocks do not establish query correctness.

| ID | Scenario | Required assertion |
|---|---|---|
| J1 | Nested JSON ingestion, source round-trip, arrays and explicit null | All types, array order, nesting and null/missing distinction retained per documented preservation contract |
| J2 | Indexed JSONPath subset: equality/range/existence/scalar-array membership | Correct matches; unsupported grammar rejected explicitly, not silently scanned |
| J3 | JSON sorting with missing/null/mixed/multivalued paths | Documented deterministic order, stable cursor pagination and type behavior |
| J4 | Same-element nested-array counterexample | Stored structure distinguishes correlated elements; no false positive from flattened postings; future capability remains representable |
| J5 | Schema limits and type changes | Deterministic bounded handling, no uncontrolled field explosion |
| G1 | GeoPoint/GeoJSON validation | WGS84 lon/lat order, finite/range checks and invalid input handling |
| G2 | Bounding boxes, including antimeridian/polar cases | Exact membership and conservative pruning without false negatives |
| G3 | Radius and distance sort | Reference geodesic results, defined tolerance, stable ties and top-K |
| G4 | Point-in-polygon including edges and holes where supported | Exact verification after candidate generation, documented boundary semantics |
| G5 | Multiple points in nested JSON events | Preserved element association for future correlated time/geo predicates |
| X1 | Compound time + JSON + geo + lexical filters | Correct Boolean intersection, sort, pagination and aggregations where supported |
| X2 | Merge/delete/reopen, remote empty cache and spatial/temporal pruning | Correct remapping, no missed documents and no irrelevant segment materialization when metadata proves exclusion |

Benchmark geo selectivity, time-window width, nested-field cardinality, dynamic-schema overhead, local and cold/warm RustFS reads; report bytes fetched, objects/segments touched, latency, memory, indexing throughput and merge cost. Future recursive JSONPath, correlated nested-array execution and transformations require later feature-specific acceptance suites; v0.1 must verify retained structure and extensible format contracts.

## Evidence, failures, and PR completion

Separate **baseline**, **regression**, and **feature-acceptance** evidence. A test existing, a test executing, and a test passing in the required topology are distinct facts. A mock-based passing unit test does not prove a real RustFS integration scenario. A green regression suite does not prove the new feature.

Classify each mandatory failure as introduced regression, feature defect, verified pre-existing deterministic failure, evidenced nondeterministic/flaky failure, or environment/harness failure. Missing infrastructure is **BLOCKED**, not PASS. Report unresolved failures explicitly; retries cannot erase a failed required stability run.

Before marking an implementation PR DONE, verify: the 85% workspace coverage gate, relevant unit tests, relevant production-path integration tests, required fault/recovery scenarios, repository QA, and documentation updates have passed. The detailed plan must name the authoritative commands/topology and acceptance evidence. Do not weaken the policy to make a PR pass.

## Instructions for coding agents

- Inspect fresh `main`, the relevant branch, and existing traits/test fixtures before writing tests.
- Choose real implementations first, then stateful fakes for controlled behavior, then `mockall` only for interaction assertions.
- Reuse contract/conformance suites across implementations rather than duplicating superficially similar tests.
- Keep fixtures small, deterministic, versioned where appropriate, and independent of uncontrolled public services.
- Never introduce mock-oriented production abstractions, duplicate storage interfaces, or synchronous test hooks into search hot loops.
- STOP and request a decision if an integration boundary cannot be exercised, the real adapter violates the assumed contract, or mandatory coverage/QA cannot be met.
- Follow [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md) for executable PR plans and explicit evidence requirements.
