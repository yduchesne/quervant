# Quervant v0.1 — historical PR 14 closeout planning record

**Status:** HISTORICAL PR 14 planning record. This is not a current PR 14 acceptance report or a PR 15 work-package specification. The PR 15A–15F series is defined **exclusively** in [ROADMAP_V01.md](ROADMAP_V01.md#pr-15--v01-qualification-diagnostics-bounded-optimization-and-benchmarks).
**Base:** current `main`; original PR 14 implementation merged as GitHub PR #41.
**Naming:** 14A–14C are historical work-package labels, not reserved GitHub pull-request numbers. Later PR 14D–14G acceptance evidence supersedes this old planning snapshot; current PR 15 labels are maintained only in the roadmap.

## Intent and boundaries

Close the remaining PR 14 acceptance obligations without rewriting functionality already present, then independently qualify v0.1 for release. M0–M5 mutation work is merged, with M5 qualification delivered by PR #55. No distributed, vector, ontology, or graph implementation is introduced. PR 15 is not a vehicle to silently finish missing PR 14 functionality.

The original PR 14 reports in `docs/pr-artifacts/pr-14/` contain historical NOT READY observations that predate later implementations. Before declaring a gap, inspect fresh `main`, relevant tests, and the final accepted contracts. Known present code includes `search/unified_cursor.rs`, `search/batch_meter.rs`, compound aggregation in `search/unified.rs`, and `tests/pr14_storage_vertical.rs`. The naked public batch entry rejects PIT/cursor requests; 14A adds the explicit `PitHandle`-backed entry point and local public-cursor integration suite. Real-provider/fault qualification remains 14B. Distinguish **implemented**, **tested locally**, **qualified on real RustFS**, **CI verified**, and **accepted**.

## Work packages

| Label | Deliverable | Acceptance / merge gate | Estimated focused effort |
|---|---|---|---|
| **14A** | Public PIT/cursor completion | **IMPLEMENTED — local qualification PASS; not accepted.** `execute_batch_pinned` uses a retained `PitHandle` as the sole snapshot authority, bridges complete private tuples into an opaque in-memory public cursor, validates expiry/query/sort/snapshot binding and accounts cursor bytes; real-`FsDirectory` oracle, mutation/compaction and exact/one-over tests pass. Real-RustFS/fault qualification remains 14B; final-SHA CI and human review pending. Evidence: [pr-artifacts/pr-14a/](pr-artifacts/pr-14a/implementation-evidence.md). | 3–5 h |
| **14B** | Integration, compatibility and fault qualification | Execute mandatory local and real-RustFS compound verticals (including ignored provider tests), cold bootstrap, mutation/PIT, faults, cancellation, resource exact-limit/one-over, old JSON segments and independent query oracles; record commands, environment and results | 2–4 h |
| **14C** | PR 14 acceptance closeout | Reconcile original acceptance matrix with merged code and 14A/14B evidence; run targeted PR 14 benchmarks; verify final-SHA CI, ≥85% measured line coverage and stable/MSRV gates; update PR 14 evidence and roadmap only when satisfied | 1–3 h |


**Historical estimates:** 14A–14C were estimated at 6–12 focused hours when this plan was proposed. No current PR 15 estimate or work-package definition is maintained here; consult the roadmap.

## Sequencing

1. **14A → 14B → 14C**: merge sequentially, each against fresh `main`. 14A requires an explicit compatibility/design decision before production changes; do not let a coding agent invent a public PIT resolver or alter serialized cursor contracts unilaterally.
2. **PR 15 sequencing:** refer exclusively to the authoritative PR 15A–15F dependency graph and gates in `docs/ROADMAP_V01.md`. This historical document does not constrain or redefine the updated series.

## Mandatory controls for every implementation PR

- Write a **separate detailed coding-agent plan** conforming to `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, including exact files/APIs, deterministic test IDs and expected assertions, fixtures/oracles, fault matrix, execution commands, evidence paths, rollback/compatibility considerations, and a preauthorized decisions/exception matrix.
- Use **AUTO-RESOLVE**, **DEFER AND CONTINUE**, and **HARD STOP** boundaries for foreseeable uncertainty; escalate architectural changes and mandatory unexecutable acceptance rather than assuming success.
- Reuse existing production interfaces and test harnesses. Prefer real engines and real RustFS for required verticals; mocks alone never satisfy real-boundary gates.
- Record SHA, toolchain, commands, environment, CI run IDs, raw benchmark artifacts, skipped/ignored tests and failures. Never classify a skipped test, unavailable provider, or unqualified benchmark as PASS.
- Require independent source review and explicit human merge approval. Documentation-only merge does not change feature or release status.

## Current release scope authority

The complete PR 15A–15F definitions, release gates, diagnostics and conditional optimization policy are maintained **only** in `docs/ROADMAP_V01.md`. `docs/BENCHMARKING.md` and `docs/TESTING.md` retain cross-cutting engineering policies; this document does not introduce parallel PR 15 definitions.

## 14C closeout outcome (2026-10-24)

PR 14C executed the local PR 14 suites, all 11 pinned real-RustFS verticals, the
F01–F10 fault matrix (10 iterations each), the PR 13 provider/objectstore
regressions, stable/MSRV gates and 91.27 % workspace production line coverage.
That evidence is negative-free but **PR 14 was not accepted**: the human
decision on `R-14A-JSON-MEM` is **`REQUIRE SEPARATE CORRECTION`**, and three
fresh qualified P4 trials plus final-SHA CI are unavailable. A separately
designed and approved correction must land before PR 14 acceptance resumes;
15A does not start before that. Evidence:
[PR 14C final acceptance](pr-artifacts/pr-14c/final-acceptance.md). PR 14
remains IN PROGRESS; PR 15 and v0.1 are not released.


## Historical status notice

The 2026-10-24 PR 14C outcome immediately above is a dated historical observation, **not** the current state of the whole PR 14 workstream. Later PR 14D–14G evidence and the 127-row PR 14G crosswalk control the final acceptance record. This document must not be used as the current PR 15 schedule or as evidence that PR 14 remains blocked.
