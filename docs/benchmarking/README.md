# Benchmarking Infrastructure Refactoring — Historical Design and Acceptance Contracts

**Status:** Historical design and migration contracts for **v0.1-bench**.

The implemented operator interface is maintained in
[../BENCHMARK_WORKFLOW.md](../BENCHMARK_WORKFLOW.md), alongside
[../BENCHMARKING.md](../BENCHMARKING.md). The real execution and closeout criteria
in this directory remain binding; archiving the design narrative does not claim
that those benchmarks or acceptance gates have been executed.

The documents in this directory record the refactoring design and acceptance
contracts between the original v0.1 codebase and the post-refactoring v0.1
codebase. Consult the current workflow for implemented behavior. The historical
plans alone do not establish that their real execution or closeout criteria pass.

## Documents

- [BENCHMARKING_METHODOLOGY.md](BENCHMARKING_METHODOLOGY.md) — human-readable target experimental process, terms, randomized blocks and slots, pruning, statistical interpretation and gate purposes.
- [BENCHMARKING_ARCHITECTURE.md](BENCHMARKING_ARCHITECTURE.md) — target software architecture, interfaces, invariants, gate orchestration, evidence and qualification contracts.
- [BENCHMARKING_MIGRATION.md](BENCHMARKING_MIGRATION.md) — phased migration, compatibility, verification and rollback specification.
- [BENCHMARKING_ROADMAP.md](BENCHMARKING_ROADMAP.md) — the v0.1-bench BM-01 onward PR series, dependencies, acceptance criteria and exit gates.

## Simulation-first implementation rule

For **BM-01 through BM-08**, the refactoring uses deterministic component/property tests, simulated end-to-end campaigns, fault injection and read-only historical replay. **No new real timed benchmarking, including abbreviated timing checks or official A/A controls, is permitted in those PRs.** The **first complete real benchmark qualification is BM-09**, subject to protocol freeze, host qualification and explicit authorization. All synthetic evidence must be visibly labeled and must not qualify as real performance evidence. See the [methodology](BENCHMARKING_METHODOLOGY.md#104-verifying-our-methodology-before-running-real-benchmarks), [migration specification](BENCHMARKING_MIGRATION.md#6-simulation-first-testing-and-ci-transition) and [BM roadmap](BENCHMARKING_ROADMAP.md).

## Relationship to existing documentation

During the refactoring, the existing canonical documents directly under `docs/`, especially [../BENCHMARKING.md](../BENCHMARKING.md), continue to describe current behavior and historical methodology. A frozen historical experiment's own protocol, source identities, receipts and evidence remain authoritative for that experiment. **No design in this folder retroactively modifies historical measurements, approvals, or decisions.**

Once the refactoring is completed, **preserve this entire directory for historical purposes**. At that point, integrate the implemented content of `BENCHMARKING_ARCHITECTURE.md` and the adopted target methodology from `BENCHMARKING_METHODOLOGY.md` into the relevant *current* documentation directly under `docs/`, with all other necessary updates to those current documents (including procedures, examples, CLI instructions, references, and indexes). The historical migration and roadmap documents remain here as a record of the transition. Do not leave competing descriptions of the active architecture; clearly mark this folder as historical upon completion.

## Version semantics

`v0.1-bench` is an **interim engineering milestone**, not a declaration that Quervant's product version has changed to v0.2. It sits between the current v0.1 codebase and the resulting v0.1 state after the benchmarking refactoring. The milestone is complete only when the roadmap's exit criteria pass. An optional Git tag or release marker requires a separate explicit decision.

## Original specification scope

The original specification PR was documentation-only. It introduced no production
code, tests, benchmark evidence, frozen-artifact changes or qualification claims.
