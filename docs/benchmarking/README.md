# Benchmarking Infrastructure Refactoring — Interim Documentation

**Status: historical BM-01–BM-09 design documentation.** BM-09 was **DONE — TERMINATED INCOMPLETE** ([PR #110](https://github.com/yduchesne/quervant/pull/110), closed and unmerged). The replacement **BM-10** is **PLANNED** in [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md); `v0.1-bench` remains **NOT COMPLETE**.

The documents in this directory preserve the **original, partially implemented and ultimately abandoned** benchmarking migration architecture, methods and PR sequence. Their historical approval, cryptographic-integrity, receipt/attestation, offline-replay and sequencing rules **do not govern BM-10**. The current BM-10 contract is in the roadmap; it prioritizes direct, scientifically valid measurements and useful reports. These design files do **not** assert that their target architecture shipped.

## Documents

- [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md) — human-readable target experimental process, terms, randomized blocks and slots, pruning, statistical interpretation and gate purposes.
- [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) — target software architecture, interfaces, invariants, gate orchestration, evidence and qualification contracts.
- [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md) — phased migration, compatibility, verification and rollback specification.
- [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md) — the **current** BM-09 closeout, detailed [source/artifact reuse register](BENCHMARKING_ROADMAP.md#bm-09--real-full-scale-benchmark-qualification-consolidation-and-v01-bench-closeout-historical-plan), BM-10 requirements and revised milestone exit criteria.
- [BM10_MAIN_CODE_AUDIT.md](BM10_MAIN_CODE_AUDIT.md) — audited `main` code-level deletion/refactor inventory for removing benchmark integrity checks, seals, receipts and transitive dependencies while preserving scientific and safety requirements.
- [../BENCHMARKING.md — current comparative methodology](../BENCHMARKING.md#current-comparative-methodology--recovered-from-bm-09-for-bm-10) — **recovered BM-09 scientific methodology:** within-run paired relative effects, cross-run percentage-point changes rather than absolute time comparisons, comparability classification and uncertainty. This is the canonical guidance for BM-10.

## Historical BM-01–BM-09 testing boundary

BM-01 through BM-08 were simulation-first and did not perform real timing. BM-09 was the designated first real-acquisition step; it **terminated incomplete** and did not deliver qualified results. Those restrictions are **historical, not BM-10 rules**. BM-10 may execute real benchmarks under its own correctness, comparability, readiness and statistical safeguards, without manual authorization or cryptographic evidence certification. See the [revised roadmap](BENCHMARKING_ROADMAP.md).

## Permanent artifact naming convention

The repository-wide rules for naming, dating, identifying and retaining benchmark configurations and results are maintained in the **canonical** [`docs/BENCHMARKING.md` artifact convention](../BENCHMARKING.md#benchmark-configuration-and-result-artifact-naming-permanent-convention). They apply to new benchmark work **independently of BM-10 or any particular milestone**. This historical directory and the BM-10 roadmap refer to that convention rather than define separate naming rules.

## Relationship to existing documentation

During the refactoring, the existing canonical documents directly under `docs/`, especially [../BENCHMARKING.md](../BENCHMARKING.md), continue to describe current behavior and historical methodology. A frozen historical experiment's own protocol, source identities, receipts and evidence remain authoritative for that experiment. **No design in this folder retroactively modifies historical measurements, approvals, or decisions.**

This directory is now explicitly retained for **historical design and BM-10 roadmap planning**. BM-10 must update canonical documentation under `docs/` to match the implementation it actually delivers; it must not transplant the superseded architecture wholesale or describe an unimplemented target as current behavior. Preserve older frozen experiments and verdicts.

## Version semantics

`v0.1-bench` is an **interim engineering milestone**, not a declaration that Quervant's product version has changed to v0.2. It sits between the current v0.1 codebase and the resulting v0.1 state after the benchmarking refactoring. The milestone is complete only when the **revised BM-10 and C6 criteria** in the roadmap pass. BM-09's terminated original acceptance gate is not inherited. An optional Git tag or release marker requires a separate explicit decision.

## Constraints

Documentation-only PR: no production code, tests, benchmark evidence, frozen artifacts, or current qualification claims are changed by introducing these specifications.
