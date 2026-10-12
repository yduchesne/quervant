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

## Domain-oriented normalization and fuzzy-search acceptance (v0.1, PR 4 / PR 8)

Domain functionality is optional and schema-configurable. The following are **feature acceptance** requirements once their owning PR is implemented; this documentation-only change does not claim that the tests or features exist today.

| ID | Owner | Scenario | Required assertion |
|---|---|---|---|
| DN01 | PR 4 | ASCII case, root dot and canonical DNS identity | Documented equivalent spellings yield the same canonical key; original value retained. |
| DN02 | PR 4 | IDNA Unicode/ASCII forms and malformed inputs | Explicit versioned IDNA profile; valid equivalents agree and invalid labels/lengths fail with typed errors. |
| DN03 | PR 4 | Reversed-label representation | Deterministic label boundaries and queryable derived key; exact identity unchanged. |
| DN04 | PR 4 | PSL multi-label and private suffixes | Registered-domain extraction follows a documented private-suffix policy and pinned dataset version. |
| DN05 | PR 4 | UTS #39 mixed-script confusables | Versioned skeletons are deterministic; collisions do not imply identical domains. |
| DN06 | PR 4 | Analyzer configuration/version change | Index/query versions agree or explicitly reject/reindex; no silent reinterpretation. |
| DN07 | PR 4 | Optional feature disabled | Ordinary keyword/text fields remain unchanged; no domain-only behavior leaks. |
| DF01 | PR 8 | Exact, substitution, insertion, deletion, transposition | Bounded fuzzy term results match an independent reference evaluator; domain-aware behavior is explicit. |
| DF02 | PR 8 | Registered-domain vs subdomain label variation | Domain-aware matching preserves label boundaries and exact identity separately from similarity. |
| DF03 | PR 8 | Adversarial dictionary/pattern and budget boundaries | Bounded edit distance, expansion, memory, timeout and cancellation; explicit error instead of truncation. |
| DF04 | PR 8 | Unicode/IDNA and skeleton interplay | No accidental equality coercion; stable versioned query/index normalization. |
| DF05 | PR 8 | Real indexed terms, local reopen and applicable RustFS path | Same logical matches and deterministic ordering across storage/reopen; fake-only tests do not satisfy integration acceptance. |

PR 4/PR 8 must include targeted unit tests, negative cases and real production-path integration tests as applicable; use the repository's workspace-wide 85% coverage gate. Dataset versions, fixture provenance and test commands must be recorded. Advanced weighted similarity and application-specific impersonation scoring are outside v0.1.

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

- **At least 85% automated line coverage** across applicable production Rust workspace code. Enforce the threshold in CI with `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` (installed via the installer action declared in the workflow and the Rust `llvm-tools-preview` component). The command measures workspace line coverage and fails when it falls below 85%.
- Exclude generated or test-only code only with explicit, reviewed, documented rationale. Do not omit hard-to-test production modules or crates to inflate coverage.
- Coverage is necessary but insufficient: targeted unit tests, relevant integration tests, negative/failure cases, and correctness assertions are separate mandatory gates.
- Record coverage scope, tool/version, command, exclusions, environment and measured percentage. Required tests must actually execute and pass; merely compiling a test or adding it to the repository is not evidence.
- The coverage gate is configured in `.github/workflows/ci.yml`; verify it actually passes in GitHub Actions before declaring enforcement operational. Real-service integration harnesses remain planned until individually implemented and verified.

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

## General-purpose primitive acceptance matrix (v0.1)

| ID | Scenario | Required assertion |
|---|---|---|
| P1 | Insert, duplicate key, update, upsert, delete, delete/reinsert | Deterministic logical key/version and visibility behavior across flush/reopen |
| P2 | Crash between refresh, segment write, manifest publication and acknowledgment | Documented refresh/durability guarantees and atomic recovery without partial committed state |
| P3 | PIT reader across update/delete/merge and retention/GC | Pinned snapshot remains consistent; obsolete objects reclaimed only when safe |
| P4 | Search-after pagination with tied scores, missing/null/multivalued sorts | No skips/duplicates within a snapshot; cursor expiry/rejection deterministic |
| P5 | DocValues-like columns across flush, merge, delete, reopen | Typed values, aggregations, basic projections and remapped doc IDs remain correct |
| P6 | Phrase/position postings and Boolean intersections | Exact positional/Boolean semantics with reference evaluator and adversarial token streams |
| P7 | Block/segment skip pruning and query budgets | No false negatives; bounded expansion, memory, bytes and explicit cancellation/errors |
| P8 | Append-event vs mutable-document profile | Same correctness and durability semantics under differing policy/layout choices |
| P9 | Retention expiry and remote object cleanup | Deterministic policy, safe PIT retention, committed-manifest reachability |
| P10 | Format versions and optional feature capabilities | Golden fixtures, incompatible-codec errors and documented upgrade/reindex behavior |
| P11 | Compound relevance + JSON + time + geo + projection | Stable scoring/filtering/sorting and source/selected-field correctness |
| P12 | Local vs RustFS cold-cache recovery and faults | Equivalent committed results, bounded cache/I/O, no stale/torn reader state |

Require deterministic fault injection around acknowledgment/commit and concurrency, production-path integration tests, >=85% automated line coverage, and benchmark reports for postings intersection, sorting, mutation/merge amplification, cold/warm ObjectStore operations, temporal/spatial pruning and both workload profiles. Compare with Tantivy/Lucene and other relevant baselines only where workload/feature semantics are equivalent; record limitations rather than claiming unmeasured wins.

## IP, typed membership and grouped analytics acceptance matrix (v0.1)

| ID | Scenario | Required assertion |
|---|---|---|
| S1 | IPv4/IPv6 exact, ordered range and CIDR membership | Correct family-aware binary matching; no text-prefix or geospatial substitution |
| S2 | CIDR /0, host prefix, invalid length, malformed address and IPv4-mapped IPv6 | Boundary correctness; explicit family/normalization policy; typed invalid-input errors |
| S3 | Multi-valued IP fields and Boolean/JSON/time conjunction | Correct any-value membership and no false matches from unrelated values |
| S4 | EXISTS, MISSING, IS NULL, IN, NOT IN across typed and JSON fields | Approved truth tables including null, absent, empty array, mismatched types and negation |
| S5 | Group by one and multiple typed keys with count/sum/min/max/avg | Exact aggregates on matching live documents, deterministic group order and numeric semantics |
| S6 | Exact distinct count, repeated multivalued values, missing/null keys | Explicit per-document distinct semantics and exact counts |
| S7 | Top-K field-value frequency with ties | Deterministic ranking and stable tie-breaker; correct frequency definitions |
| S8 | High-cardinality group/distinct budget, timeout and cancellation | Typed resource errors, no silent truncation or false exact results |
| S9 | Update/delete/merge/retention with PIT snapshot | Aggregate and network predicate results match the snapshot, before and after reopen |
| S10 | Compound IP + JSON + temporal + lexical filters and aggregation | Correct filtering before aggregation; local/RustFS equivalent results |
| S11 | Columnar codec version/merge remapping for IP and group keys | Exact round-trip, compatibility errors and no key corruption |
| S12 | Reproducible security-log-style benchmarks | Correctness-gated IP/CIDR, group-by, distinct and top-K results; record latency, memory, read amplification and cold/warm remote I/O |

Implement production-path unit and integration evidence in the owning PRs (2, 5, 10, 14 and 15). Tests here are **future acceptance requirements**, not evidence of implementation. Do not treat a fake ObjectStore as equivalent to RustFS integration.

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
