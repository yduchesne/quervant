# Quervant v0.1 — PR execution roadmap

> **Status:** IN PROGRESS (PRs 1–6, 8 and 9 DONE; PR 7 implementation complete on `dev/lexical-postings` pending review/merge; PRs 10–15 PLANNED). This document is the authoritative **v0.1 PR-level execution tracker**. It records proposed implementation PRs, not GitHub PRs already opened. PR identifiers after PR 1 are planning labels, subject to refinement before coding. Update status only with verified implementation/merge evidence.

See [ROADMAP.md](ROADMAP.md) for cross-release boundaries, [ARCHITECTURE.md](ARCHITECTURE.md) for design targets, [TESTING.md](TESTING.md) for quality gates, [BENCHMARKING.md](BENCHMARKING.md) for reproducible measurements, and [DETAILED_PR_PLAN_AUTHORING_GUIDE.md](DETAILED_PR_PLAN_AUTHORING_GUIDE.md) for full per-PR execution plans.

## Release objective and constraints

Deliver a **standalone, general-purpose, single-index/single-shard Rust search engine** supporting mutable application documents and append-oriented structured events, with lexical, typed numeric, temporal, native JSON and geospatial point retrieval. Provide durable local storage and optional remote ObjectStore-backed committed state, validated against RustFS. No Coordinator, Aggregator, Search Node, etcd, distributed routing or vector/ANN/hybrid runtime is required in v0.1. The `quervant-core` crate must not depend on cluster management or RustFS.

**Foundation rules:** immutable versioned segments; explicit stable logical document identity; bounded memory/CPU/I/O; separate refresh and durable commit; correct snapshot-bound pagination; shared field/query contracts; segment pruning before remote materialization where safe. The exact contracts must be approved **before** freezing the on-disk format. Later correlated JSON arrays, recursive JSONPath, transformations/projections, richer geometry and WAND optimizations require forward-compatible extension points, **not** v0.1 execution.

**Quality gates:** >=85% automated production Rust line coverage, relevant real-path unit/integration tests, deterministic fault injection, local and RustFS acceptance, explicit command/result evidence, and correctness-gated Tantivy/Apache Lucene benchmark comparison. No unexecuted check may be marked passed.

## Planned PR register

| PR | Working title | Dependencies | Status |
|---|---|---|---|
| 1 | Repository foundation and architecture roadmap | None | DONE — [PR #1](https://github.com/yduchesne/trawler/pull/1) merged; [foundation CI](https://github.com/yduchesne/trawler/actions/runs/38175860017) verified (F19 status reconciled; F15 coverage separately gated) |
| 2 | Unified document, field and query contracts | 1 | DONE — [PR #6](https://github.com/yduchesne/trawler/pull/6) merged 2026-10-12 (merge `c54cbf3`); CI `rust` check verified success on head and merge commit; A01–A25 approved 2026-10-11; Implementation Amendment 01 applied (checked exactly-N batch responses, batch aggregate-budget validation, server/index/tenant budget hierarchy); runtime execution deferred to PRs 3–15 |
| 3 | Storage abstraction, durability and conformance harness | 2 | DONE — [PR #13](https://github.com/yduchesne/trawler/pull/13) merged 2026-10-12 (merge `cdbab01`); CI `rust` check verified success; `Directory`/`ObjectStore` contracts, memory/filesystem backends, bounded verified `SegmentCache` and RustFS harness foundation implemented and conformance-tested. Production S3/RustFS adapter and remote cold bootstrap remain PR 13. |
| 4 | Analyzer and term-query contracts/implementation | 2–3 | DONE — GitHub PR #16 merged 2026-10-12 (merge `9bc042d`); CI `rust` check verified success; analyzer subsystem (`quervant-core::analysis`) implemented and conformance-tested; term-query execution remains PR 8. |
| 5 | Versioned immutable segment codecs and columnar values | 2–4 | DONE — GitHub PR #19 merged 2026-10-13 (merge `c735dac`); CI `rust` check verified success; immutable segment/manifest codecs, typed columns, checked-in golden fixture and corrective passes implemented and conformance-tested. |
| 6 | Writer, commit/recovery, refresh and PIT lifecycle | 3, 5 | DONE — [PR #22](https://github.com/yduchesne/quervant/pull/22) merged 2026-10-13 (merge `56fa9c2`); local lifecycle, recovery, PIT and resource-budget parity implemented and validated; remote/RustFS scope remains PR 13 |
| 7 | Lexical postings, Boolean/phrase and ranked search | 4–6 | PLANNED |
| 8 | Advanced lexical multi-term operators and safety budgets | 7 | DONE — [PR #25](https://github.com/yduchesne/quervant/pull/25) merged 2026-10-14 (merge `7d52547`); prefix/glob/whole-term regex and bounded fuzzy execution, runtime-derived FST intersection, domain-aware canonical-term matching, and Amendment 01 resource-accounting hardening implemented and validated. |
| 9 | Stable-key mutations, tombstones, merges and retention | 6–7 | DONE — delivered on `dev/stable-key-mutations` through commit `b8c63f9` (original implementation `950583c`, roadmap follow-up `fac859f`); versioned `MutationStateV1` sidecar + manifest v2, generation-specific live masks, revisioned insert/upsert/delete with idempotency replay/conflict, volatile refresh versus durable `CURRENT` commit, lossless explicit compaction, explicit retention and dry-run reclamation implemented and validated. Amendment 01 closes the revision-overflow, ambiguous-`CURRENT` poisoning and cooperative merge-cancellation acceptance gaps. Remote/RustFS, online garbage collection and distributed/vector functionality remain outside PR 9. |
| 10 | Typed numeric/temporal retrieval and bounded analytics | 5–7, 9 | PLANNED |
| 11 | Native JSON ingestion, path indexing and query subset | 2, 5–7, 9–10 | PLANNED |
| 12 | GeoPoint indexing and spatial query execution | 2, 5–7, 10–11 | PLANNED |
| 13 | Remote ObjectStore mode, RustFS and cache/recovery | 3, 5–12 | PLANNED |
| 14 | Unified compound planner, pagination, projections and governance | 7–13 | PLANNED |
| 15 | v0.1 release qualification, compatibility and benchmarks | 1–14 | PLANNED |

Dependencies are conceptual; independently implementable sub-work may be split or parallelized after contracts are approved. PR numbers are planning identifiers, not a claim that GitHub PRs exist.

## PR summaries and acceptance boundaries

### PR 1 — Repository foundation and architecture roadmap

**Scope:** Cargo workspace (`quervant-core`, `quervant-objectstore`, `quervant-distributed`), licensing, README, agent guidance, CI, architecture/testing/benchmarking policies, cross-release roadmap and this PR register.

**Acceptance:** workspace layout and declared licenses reviewed; foundation CI verified; documentation distinguishes planned capabilities from implementation. **No engine functionality is implied by merging PR 1.**

### PR 2 — Unified document, field and query contracts

**Scope:** logical document key and version semantics; typed IPv4/IPv6 and CIDR field/query semantics; universal EXISTS/MISSING/IS NULL/IN/NOT IN truth tables; group-by, exact distinct and top-K IR with resource limits; insert/upsert/delete ordering; typed schema and field cardinality; stored/columnar/indexed options; nested JSON identity; WGS84 GeoPoint; timestamp; analyzer bindings; typed query IR; filter/rank/sort/aggregation/basic projection interfaces; cursor/PIT contracts; feature/version negotiation and resource budgets. Explicitly decide missing/null, mixed types, multi-valued sorting, JSONPath grammar and geospatial boundary semantics.

**Acceptance:** reviewed architecture decision record, compile-time Rust API contracts, executable conformance fixtures and golden examples, plus a signed-off **pre-format design gate**. Future structural/geometry operators remain representable without claiming execution.

### PR 3 — Storage abstraction, durability and conformance harness

**Scope:** local `Directory`, segment access/cache contracts, separate provider-neutral `ObjectStore` capabilities, sync/async boundaries, atomic publication/fencing requirements, memory and filesystem adapters, fault injection and RustFS test harness foundation.

**Acceptance:** real filesystem conformance tests, simulated partial writes/crashes and clear local-versus-remote durability assumptions; no cluster dependencies.

**Implementation status (`dev/storage-abstraction`):** the `Directory`/`ObjectStore` contracts, `MemoryDirectory`, `FsDirectory` durability behavior, deterministic `FakeObjectStore` fault injection, exact bounded ranged reads, the bounded verified `SegmentCache`, and the RustFS harness foundation are implemented and conformance-tested (D-*, F-*, O-*, C-*). The production S3/RustFS adapter, remote cold bootstrap and real RustFS integration remain **PR 13**. See [decisions/PR03_STORAGE_CONTRACT_DECISIONS.md](decisions/PR03_STORAGE_CONTRACT_DECISIONS.md).

### PR 4 — Analyzer and term-query contracts/implementation

**Scope:** field-specific index/search analyzers, Unicode/whitespace/keyword tokenization, normalization, positions/offsets, stopwords/stemming as agreed, and explicit multi-term grammar/automaton contracts. Include **optional, schema-configurable domain-oriented analysis**: DNS/IDNA canonical exact identity, root-dot and label validation, reversed-label representations, Public Suffix List (PSL) registered-domain decomposition, and Unicode UTS #39 confusable skeletons as separately indexed derived representations. Version normalization rules and external datasets; keep identity distinct from skeleton equivalence and similarity.

**Acceptance:** deterministic token streams, offsets/positions and analyzer version behavior across Unicode and malformed inputs; documented resource limits. Domain fixtures cover IDNA/case/root-dot equivalence, invalid labels, PSL private-suffix policy and dataset version, reversed labels, Unicode confusables, stable canonical identity, and version mismatch/reindex behavior.

**Implementation status (merged via GitHub PR #16, merge `9bc042d`):** the analyzer subsystem (`quervant-core::analysis`) is implemented with approved parameters: `Token`/offsets/positions, keyword/whitespace/Unicode-word tokenizers, NFC/case-fold/ASCII-fold/stopword/stemmer filters, bounded pull cursor + limits + cancellation, canonical SHA-256 analyzer fingerprints and schema bindings, term/prefix/glob/regex preparation (execution remains PR 8), and optional pinned UTS #46/PSL/UTS #39 domain representations. A4-01–22 and I4-01–04 execute and pass locally; fmt, Clippy, doc, coverage (94.0% lines) and the full workspace test suite pass, including on the declared Rust 1.85 MSRV after the behavior-preserving PR 2 let-chain fixup. See [pr-artifacts/pr-4/implementation-report.md](pr-artifacts/pr-4/implementation-report.md). No segment/on-disk format is introduced.

**Cross-cutting streaming requirement:** Quervant must support bounded incremental result production for suitable query plans, with pull-based backpressure, cancellation, PIT consistency, explicit ordering and typed terminal errors. See [Streaming search and composable pipelines](STREAMING_SEARCH.md). Streaming does not imply that global sorting, exact top-K or aggregation can emit final answers before sufficient input has been processed. This is a core architecture requirement, not a v0.1 UI or transport commitment.

### PR 5 — Versioned immutable segment codecs and columnar values

**Scope:** immutable segment/manifest schemas, typed field descriptors, term dictionaries, positional postings, stored source documents, DocValues-like typed columns including family-aware IPv4/IPv6 address representations and aggregation-friendly typed group keys, live-doc/version references, temporal/spatial conservative bounds and optional codec capability flags. Include sorted-layout doc-ID remapping and merge-ready references.

**Acceptance:** golden on-disk fixtures, round-trip/reopen and corruption checks, version incompatibility handling, local durability and index-structure consistency. No index-format freeze before PR 2 approval.

### PR 6 — Writer, commit/recovery, refresh and PIT lifecycle

**Scope:** single-writer indexing, flush, durable manifest publication, refresh visibility, reader generations, PIT pinning and crash recovery; local mode first.

**Acceptance:** atomic committed generations, defined acknowledgment behavior, consistent concurrent readers, snapshot retention and deterministic crash-point tests.

**Implementation status (merged via [GitHub PR #22](https://github.com/yduchesne/quervant/pull/22), merge `56fa9c2`, 2026-10-13):** the local single-writer lifecycle is implemented in `quervant_core::index`: strict `CURRENT` v1 publication, insert-only admission with duplicate rejection across all states, bounded flush, non-durable refresh, immutable `ReaderSnapshot`s, bounded process-local `PitHandle`s, durable commit ordering (segments → manifest → atomic `CURRENT` last), indeterminate-outcome reconciliation (`RecoveryRequired`), and `CURRENT`-only generation recovery. The merged implementation includes Amendment 01 lifecycle/recovery corrections and Amendment 02 commit/reopen snapshot-budget parity. Unit, real `MemoryDirectory`/`FsDirectory` integration and separate-process restart, fault-injection, and amendment regression suites were reported passing locally on Rust 1.85 and Rust 1.98.1; the Amendment 02 validation report records 874 passed, 7 ignored, 0 failed, and 92.33% line coverage on Rust 1.85 before the subsequent CI compatibility correction. The merge is verified by merge commit `56fa9c2`; this roadmap update does not independently assert a final CI result. Remote/RustFS, query, mutation/merge and distributed functionality remain outside PR 6.

### PR 7 — Lexical postings, Boolean/phrase and ranked search

**Scope:** term/postings traversal, AND/OR/NOT, phrase/position matching, BM25, top-K, postings intersections and basic segment/block skipping.

**Acceptance:** oracle-checked ranking/filtering, phrase positions, deletion-aware scoring, deterministic ties and repeatable Tantivy/Lucene lexical comparison fixtures.

**Implementation status (`dev/lexical-postings`, pending review/merge):** `quervant-core::search` implements exact `Term`, positional `Phrase`, nested `And`/`Or`/`Not`, `MatchAll`, snapshot-wide BM25 and bounded deterministic top-K with exact hit counts. Compilation fails closed on every non-PR-7 contract operator before I/O; execution is read-only over borrowed `ReaderSnapshot`s. Field lengths are read from an optional immutable per-segment `FieldNorms` section and document frequencies are retrieved for queried terms only (legacy segments use the original bounded recomputation path); `SearchLimits`, `SearchWork` and RAII reader reservations bound work, memory and cancellation. Verified locally with 1063 passing workspace tests, 0 failures, and 92.06% workspace line coverage on both Rust 1.98.1 and Rust 1.85.0. Segment/block skipping and WAND are deliberately not claimed. **Amendment 01** corrects BM25 scoring to exclude negative-only leaves (even-`Not`-parity eligibility), enforces `max_segment_candidate_entries` per segment rather than cumulatively, tracks segment+global candidate bytes atomically, enforces scanned-posting limits independently, and fixes field-length entry occupancy and top-K replacement byte checks. **Amendment 02** aligns candidate reservations with allocation lifetimes. **Amendment 03** makes candidate-ledger transitions all-or-nothing (validate budget and ledger state, then commit once), makes direct budget release atomic under mixed-validity subtraction, and bounds/charges `phrase.rs` verification scratch (candidate, occurrence-reference and chain buffers) before allocation through a scoped owner, releasing it after the buffers drop. **Amendment 04** adds a Linux/WSL2 Criterion microbenchmark and profiling system (deterministic correctness-gated fixtures with an independent oracle and dataset digest, five dev-only benchmark targets, a benchmark-only profiling entrypoint and perf/flamegraph/heaptrack wrappers, a provenance/baseline runner and a checked-in pre-optimization baseline) without changing production behavior; profiling is classified BLOCKED/UNAVAILABLE on hosts without the tools. **Amendment 04 Correction 01** adds independently generated fixture metadata (oracle hit counts; nullable for non-query microbenchmarks), a strict `quervant-bench-v2` report builder/validator, a sanitized `/proc` contention detector with fail-closed runner qualification, and corrects the dictionary throughput unit. The qualified baseline rerun is **BLOCKED** on this host by a competing `java` CPU consumer; no qualified artifact was fabricated. See [pr-artifacts/pr-7/amendment-04-correction-01-review.md](pr-artifacts/pr-7/amendment-04-correction-01-review.md). **Amendment 05** replaces the per-search all-dictionary/all-postings statistics scan with an immutable, optional per-segment `FieldNorms` section (`FEATURE_FIELD_NORMS`, v1) emitted by the builder in the same analysis pass as postings, and retrieves document frequencies for queried terms only; genuine legacy segments keep an explicit bounded fallback, malformed norms fail closed, and the PR 5 legacy golden fixture is unchanged with a new norms golden checked in separately. Performance objective is **QUALIFIED**: a three-trial same-environment pre/post comparison (clean `a8adf37` vs clean `eb28f7e`, identical fixture metadata/dataset digests, all contention checks clear) shows scored lexical search **1.68x-2.06x** faster with postings/dictionary/BM25 controls unchanged. See [pr-artifacts/pr-7/amendment-05-review.md](pr-artifacts/pr-7/amendment-05-review.md) and [benchmarks/reports/pr07-amendment05-comparison.md](../benchmarks/reports/pr07-amendment05-comparison.md). See [pr-artifacts/pr-7/implementation-report.md](pr-artifacts/pr-7/implementation-report.md), [pr-artifacts/pr-7/amendment-01-review.md](pr-artifacts/pr-7/amendment-01-review.md), [pr-artifacts/pr-7/amendment-02-review.md](pr-artifacts/pr-7/amendment-02-review.md), [pr-artifacts/pr-7/amendment-03-review.md](pr-artifacts/pr-7/amendment-03-review.md), [pr-artifacts/pr-7/amendment-04-review.md](pr-artifacts/pr-7/amendment-04-review.md) and [pr-artifacts/pr-7/validation-report.md](pr-artifacts/pr-7/validation-report.md). **Status remains PLANNED until accepted and merged.**

### PR 8 — Advanced lexical multi-term operators and safety budgets

**Scope:** prefix, glob, regex (defined whole-term semantics), FST/automaton intersection, **general-purpose bounded fuzzy term matching** and **basic optional domain-aware fuzzy matching** that reuses the same query machinery; bounded expansions, cancellation and explicit budget-exhaustion errors. Keep advanced weighted domain-similarity scoring and DIGR-specific impersonation workflows out of v0.1.

**Acceptance:** grammar edge cases, adversarial pattern tests, bounded edit distance and term expansion, deterministic edit/transposition/domain-label cases, identity-preserving results, no unbounded work, and correctness against reference evaluators.

### PR 9 — Stable-key mutations, tombstones, merges and retention

**Scope:** update/upsert/delete, version/tombstone ordering, live-doc masking, merge/compaction, retention policy hooks and snapshot-safe reclamation.

**Acceptance:** delete/reinsert races and retries, PIT-consistent old generations, safe garbage collection, merge remapping and restart recovery.

**Implementation status (delivered on `dev/stable-key-mutations`, head `b8c63f9`):** `quervant-core::index` now carries an immutable, content-addressed `MutationStateV1` sidecar referenced by a version-2 manifest (`FEATURE_MUTATION_STATE`, section `0x000F`), with legacy v1 manifests synthesized in memory. Writers admit ordered revisioned insert/upsert/delete operations with deterministic SHA-256 idempotency fingerprints, exact-replay returns and typed token conflicts; acknowledgment means admitted, and only `commit` (segments → sidecar → manifest → atomic `CURRENT` last) is durable. Each `ReaderSnapshot` owns generation-specific live masks consumed by every lexical operator and BM25 statistic, so obsolete physical documents never resurrect. `IndexWriter::compact()` performs lossless remapping of decoded postings/positions, typed columns, stored values, field norms, revisions, tombstones and the replay ledger; retention is explicit-key only and reclamation is dry-run planning, not online deletion. **Amendment 01** adds a valid near-`u64::MAX` mutation-state fixture and overflow tests, deterministic `CURRENT` write-then-error poisoning/recovery tests against real `MemoryDirectory`/`FsDirectory`, and bounded cooperative `compact_with_cancel(&AtomicBool)` cancellation with no false `Cancelled` after publication. Local stable and Rust 1.85 MSRV gates pass: fmt, Clippy `-D warnings`, 1234 workspace tests with 0 failures, 91.67% line coverage, docs, benchmark build and script suites. Remote/RustFS mode, cross-process/online GC and distributed/vector behavior remain out of scope (PR 13 and later). See [pr-artifacts/pr-9/implementation-report.md](pr-artifacts/pr-9/implementation-report.md), [pr-artifacts/pr-9/validation-report.md](pr-artifacts/pr-9/validation-report.md), [pr-artifacts/pr-9/test-traceability.md](pr-artifacts/pr-9/test-traceability.md) and [pr-artifacts/pr-9/amendment-01-validation-report.md](pr-artifacts/pr-9/amendment-01-validation-report.md).

### PR 10 — Typed numeric/temporal retrieval and bounded analytics

**Scope:** typed ranges, optional primary event timestamp, half-open UTC time filtering, ascending/descending sort, stable cursor ordering, fixed-width time buckets, bounded group-by over one or more typed keys, count/sum/min/max/avg, exact distinct counts and top-K field-value frequencies. Segment time min/max pruning and optional time-oriented physical layout.

**Acceptance:** late/out-of-order events, boundary/tie/null cases, exact aggregations and distinct counts, stable top-K ties, explicit cardinality/memory-budget errors (no silent truncation), merges/deletes, and measurable skipped segments without false negatives.

### PR 11 — Native JSON ingestion, path indexing and query subset

**Scope:** preserve structured JSON and array ancestry, selective dynamic schema with limits, nested scalar extraction, equality/range/existence, scalar-array membership, indexed JSONPath subset compilation, field sorting and source retrieval.

**Acceptance:** source structure round-trip, explicit null/missing and type rules, safe schema budgets, no false correlated matches from flattened arrays. Correlated-array execution, recursive selectors and arbitrary transformations remain deferred with extension fixtures.

### PR 12 — GeoPoint indexing and spatial query execution

**Scope:** WGS84 GeoPoint/GeoJSON Point, spatial index choice (BKD-like or hierarchical cells) based on documented tradeoffs, conservative segment bounds, bounding box, radius, point-in-polygon, geodesic distance sort, multi-valued point preservation.

**Acceptance:** antimeridian, poles, boundary/hole and coordinate-validation cases; exact candidate verification; stable distance ordering; no false-negative pruning. Rich geometries deferred.

### PR 13 — Remote ObjectStore mode, RustFS and cache/recovery

**Scope:** provider-neutral object adapter, authoritative committed manifests/segments, bounded whole-file materialization cache, integrity verification, cold-reader bootstrap, eviction/reload, retry/failure behavior and remote garbage-collection safety. Implement **bounded concurrent whole-segment downloads** and **parallel ranged GETs for large segments**, selecting between single GET and ranged transfer by configurable thresholds and verified provider capabilities. Assemble complete objects locally and verify full-object length and SHA-256 before atomic cache publication; enforce connection, request, memory, temporary-disk and cancellation budgets. PR 3 owns optional range-read contract/capability only, not the parallel transfer implementation.

**Acceptance:** real RustFS empty-cache and interrupted-download tests, concurrent reader correctness, manifest fencing/recovery and remote segment-pruning evidence. Test single GET vs parallel ranged GET, concurrent segment materialization, providers without range capability, incomplete/overlapping/missing ranges, retries and cancellation, and strict cache/in-flight resource limits. **Partial caching and predictive prefetch remain deferred**; parallel ranges still produce a fully materialized, verified segment.

### PR 14 — Unified compound planner, pagination, projections and governance

**Scope:** compose lexical, JSON, numeric, temporal, spatial and IPv4/IPv6 CIDR operators, universal typed field membership/existence predicates and bounded group-by/distinct/top-K aggregations through shared typed IR; correctness-first candidate/intersection planner; score/filter composition; deterministic PIT-bound search-after; basic stored-field selection; limits and cancellation; plan telemetry.

**Acceptance:** cross-domain compound oracle suite (including IP/CIDR plus grouped analytics), no pagination gaps/duplicates, bounded execution, deterministic plan correctness across local and RustFS. Cost-based planning and WAND/block-max WAND remain optional future work.

### PR 15 — v0.1 release qualification, compatibility and benchmarks

**Scope:** integration/fault/regression suite including security-log-style CIDR, membership, group-by, exact distinct and top-K workloads, >=85% measured coverage, version/format fixtures, both workload profiles, resource-budget evidence, local versus remote equivalence, reproducible Quervant/Tantivy/Lucene benchmarking and release documentation.

**Acceptance:** all v0.1 gates independently passed and recorded; known limitations explicit; no distributed or vector dependency; benchmark results reported without unsupported parity claims.

## Cross-cutting security-log retrieval additions (approved v0.1 scope)

These are **general-purpose primitives**, not a SIEM-specific engine. The owning PRs are PR 2 (semantics and typed IR), PR 5 (IP and aggregation columnar codecs), PR 10 (group-by/exact distinct/top-K execution), PR 14 (compound planning and typed predicate execution), and PR 15 (correctness-gated security-log benchmarks). PR 2 must approve the canonical IPv4/IPv6 and CIDR representation, multivalue matching, missing/null and NOT IN truth tables, per-document distinct semantics, group key ordering, deterministic frequency ties and budget-exhaustion errors **before** PR 5 freezes the format. The appropriate owning implementation PR must provide exact IP/CIDR query execution; it may be staged with PR 10/14 without introducing a new PR number.

**Acceptance:** CIDR /0 and /32 or /128 boundaries, IPv4-mapped IPv6 policy, exact/grouped counts across deletes and PIT snapshots, no silent truncation when high-cardinality budgets are exceeded, and equivalent results across local and RustFS. Explicitly defer sequence/temporal correlation, sliding windows, joins, streaming detection, approximate cardinality and materialized aggregate indexes.

## Scope and status discipline

- **IN PROGRESS** means implementation or review is underway; **DONE** requires merged code/documentation and verified acceptance evidence; **BLOCKED** identifies an unresolved decision or failed gate. Do not mark a planned PR complete because its architecture is documented.
- Each PR receives its own detailed implementation plan before coding: exact file/API changes, out-of-scope items, test matrix, commands, rollback/migration considerations and merge gate. Update this register when splitting/reordering work, including dependency changes.
- No full RFC 9535 JSONPath, correlated nested-array query execution, arbitrary JSON transformations, rich geometry indexing, distributed execution, vector search, SQL parser, high-cardinality analytics, WAND/block-max WAND, fuzzy search, facets, highlighting or autocomplete is promised by v0.1.
- **v0.2:** distributed multi-shard lexical query/placement and resilience. **Post-v0.2:** vector/ANN/hybrid. Preserve standalone `quervant-core` independence.


## Advanced text retrieval dependency note (documentation-only)

The [advanced text retrieval contracts](decisions/ADVANCED_TEXT_RETRIEVAL.md) affirm three **future** capabilities: optional gram-accelerated substring retrieval, ranked autocomplete suggestions, and search-as-you-type document retrieval. They are not PR 5, PR 7, or PR 8 deliverables and do not change the v0.1 exclusion of autocomplete or substring acceleration.

Dependencies: PR 4 analyzer normalization and token boundaries; PR 5 approved sequential dictionary and feature/version contracts; PR 7 lexical execution/Boolean scoring; PR 8 bounded prefix/glob/regex/FST/fuzzy machinery. An explicit FST-versus-existing-wire compatibility decision is required before persistent FST changes. Implement each capability in a separately scoped future PR with independent acceptance evidence; do not mark any as DONE based on this documentation update.
