# Quervant v0.1 — PR 14 completion and PR 15 release qualification series

**Status:** PROPOSED execution plan; no implementation or acceptance is implied by this document.
**Base:** current `main`; original PR 14 implementation merged as GitHub PR #41.
**Naming:** 14A–14C and 15A–15D are *roadmap work-package labels*, not reserved GitHub pull-request numbers. New pull requests target `main`.

## Intent and boundaries

Close the remaining PR 14 acceptance obligations without rewriting functionality already present, then independently qualify v0.1 for release. M0–M5 mutation work is merged, with M5 qualification delivered by PR #55. No distributed, vector, ontology, or graph implementation is introduced. PR 15 is not a vehicle to silently finish missing PR 14 functionality.

The original PR 14 reports in `docs/pr-artifacts/pr-14/` contain historical NOT READY observations that predate later implementations. Before declaring a gap, inspect fresh `main`, relevant tests, and the final accepted contracts. Known present code includes `search/unified_cursor.rs`, `search/batch_meter.rs`, compound aggregation in `search/unified.rs`, and `tests/pr14_storage_vertical.rs`. The naked public batch entry rejects PIT/cursor requests; 14A adds the explicit `PitHandle`-backed entry point and local public-cursor integration suite. Real-provider/fault qualification remains 14B. Distinguish **implemented**, **tested locally**, **qualified on real RustFS**, **CI verified**, and **accepted**.

## Work packages

| Label | Deliverable | Acceptance / merge gate | Estimated focused effort |
|---|---|---|---|
| **14A** | Public PIT/cursor completion | **IMPLEMENTED — local qualification PASS; not accepted.** `execute_batch_pinned` uses a retained `PitHandle` as the sole snapshot authority, bridges complete private tuples into an opaque in-memory public cursor, validates expiry/query/sort/snapshot binding and accounts cursor bytes; real-`FsDirectory` oracle, mutation/compaction and exact/one-over tests pass. Real-RustFS/fault qualification remains 14B; final-SHA CI and human review pending. Evidence: [pr-artifacts/pr-14a/](pr-artifacts/pr-14a/implementation-evidence.md). | 3–5 h |
| **14B** | Integration, compatibility and fault qualification | Execute mandatory local and real-RustFS compound verticals (including ignored provider tests), cold bootstrap, mutation/PIT, faults, cancellation, resource exact-limit/one-over, old JSON segments and independent query oracles; record commands, environment and results | 2–4 h |
| **14C** | PR 14 acceptance closeout | Reconcile original acceptance matrix with merged code and 14A/14B evidence; run targeted PR 14 benchmarks; verify final-SHA CI, ≥85% measured line coverage and stable/MSRV gates; update PR 14 evidence and roadmap only when satisfied | 1–3 h |
| **15A** | Release regression and compatibility | Independent cross-feature oracles, security-log CIDR/membership/group-by/exact-distinct/top-K, mutation/replay, durability/crash, snapshots, version/golden fixtures, local/remote equivalence, limits; both workload profiles; ≥85% coverage | 3–5 h |
| **15B** | Reproducible Quervant/Tantivy/Lucene benchmarks | Pinned corpus, versions and hardware; equivalent local lexical workloads, correctness-before-timing, indexing throughput, p50/p95/p99, QPS, index size, CPU/RSS, repeated qualified trials and raw reports; no unsupported parity claims | 4–8 h |
| **15C** | RustFS performance and resilience | Cold/warm cache, whole GET vs ranged GET, concurrent segments, representative sizes including 16/64/256 MiB and 1 GiB where feasible, interruptions/retries, verified bytes, peak memory/disk/in-flight/request budgets; raw evidence and explicit unavailable/blocked cases | 2–4 h |
| **15D** | Final v0.1 release gate | Consolidated independent acceptance matrix and known limitations; all mandatory gates passed and recorded; final-SHA CI, source review, release documentation and human sign-off; tag only after authorization | 2–4 h |

**Indicative total:** 17–33 focused hours (14A–14C: 6–12; 15A–15D: 11–21), assuming a supervised coding agent, design-closed plans, working CI/provider environments and no major correctness defects. These are nonbinding planning estimates, not test execution results or a promise of elapsed time. Benchmark environment setup, repeated measurements and unexpected fixups can extend them.

## Sequencing

1. **14A → 14B → 14C**: merge sequentially, each against fresh `main`. 14A requires an explicit compatibility/design decision before production changes; do not let a coding agent invent a public PIT resolver or alter serialized cursor contracts unilaterally.
2. **15A** begins only after PR 14 acceptance closeout. Freeze common datasets, independent oracles and correctness gates here.
3. **15B** and **15C** may be implemented in parallel after 15A's fixtures are available; merge against fresh `main` with conflict/requalification checks.
4. **15D** follows all mandatory evidence and is the sole v0.1 release sign-off milestone. Start v0.2 distributed implementation only after v0.1 acceptance.

## Mandatory controls for every implementation PR

- Write a **separate detailed coding-agent plan** conforming to `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, including exact files/APIs, deterministic test IDs and expected assertions, fixtures/oracles, fault matrix, execution commands, evidence paths, rollback/compatibility considerations, and a preauthorized decisions/exception matrix.
- Use **AUTO-RESOLVE**, **DEFER AND CONTINUE**, and **HARD STOP** boundaries for foreseeable uncertainty; escalate architectural changes and mandatory unexecutable acceptance rather than assuming success.
- Reuse existing production interfaces and test harnesses. Prefer real engines and real RustFS for required verticals; mocks alone never satisfy real-boundary gates.
- Record SHA, toolchain, commands, environment, CI run IDs, raw benchmark artifacts, skipped/ignored tests and failures. Never classify a skipped test, unavailable provider, or unqualified benchmark as PASS.
- Require independent source review and explicit human merge approval. Documentation-only merge does not change feature or release status.

## Release acceptance and non-goals

PR 15 must establish reproducible correctness and resource governance, compatibility with supported on-disk formats, crash recovery, local/remote equivalence, ≥85% measured workspace line coverage, and honest comparative benchmark evidence. **Matching or exceeding Tantivy/Lucene performance is not a release gate.** A mandatory missing feature, failed correctness oracle, unqualified real-provider gate or unsupported parity assertion blocks sign-off. Known deferred optimizations (including PR 13 V08, tracked by issue #37) must remain explicit rather than silently represented as delivered.

See `docs/ROADMAP_V01.md`, `docs/TESTING.md`, `docs/BENCHMARKING.md`, and the PR 14 historical acceptance reports for the authoritative scope and methodology. This document refines execution sequencing; it does not supersede approved architecture contracts.
