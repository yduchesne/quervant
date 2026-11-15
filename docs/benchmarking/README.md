# Benchmarking Infrastructure Refactoring — Interim Documentation

**Status:** Interim design and migration documentation for **v0.1-bench**.

The documents in this directory describe a **transitional state** of Quervant: the planned refactoring of the benchmarking and verification infrastructure between the present v0.1 codebase and the post-refactoring v0.1 codebase. These documents are proposals and implementation contracts, **not assertions that the target architecture has already shipped**.

## Documents

- [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md) — human-readable target experimental process, terms, randomized blocks and slots, pruning, statistical interpretation and gate purposes.
- [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) — target software architecture, interfaces, invariants, gate orchestration, evidence and qualification contracts.
- [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md) — phased migration, compatibility, verification and rollback specification.
- [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md) — the v0.1-bench BM-01 onward PR series, dependencies, acceptance criteria and exit gates.

## Relationship to existing documentation

During the refactoring, the existing canonical documents directly under `docs/`, especially [../BENCHMARKING.md](../BENCHMARKING.md), continue to describe current behavior and historical methodology. A frozen historical experiment's own protocol, source identities, receipts and evidence remain authoritative for that experiment. **No design in this folder retroactively modifies historical measurements, approvals, or decisions.**

Once the refactoring is completed, **preserve this entire directory for historical purposes**. At that point, integrate the implemented content of `BENCHMARKING_ARCHITECTURE.md` and the adopted target methodology from `BENCHMARKING_METHODOLOGY.md` into the relevant *current* documentation directly under `docs/`, with all other necessary updates to those current documents (including procedures, examples, CLI instructions, references, and indexes). The historical migration and roadmap documents remain here as a record of the transition. Do not leave competing descriptions of the active architecture; clearly mark this folder as historical upon completion.

## Version semantics

`v0.1-bench` is an **interim engineering milestone**, not a declaration that Quervant's product version has changed to v0.2. It sits between the current v0.1 codebase and the resulting v0.1 state after the benchmarking refactoring. The milestone is complete only when the roadmap's exit criteria pass. An optional Git tag or release marker requires a separate explicit decision.

## Constraints

Documentation-only PR: no production code, tests, benchmark evidence, frozen artifacts, or current qualification claims are changed by introducing these specifications.
