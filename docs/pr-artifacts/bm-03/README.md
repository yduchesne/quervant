# BM-03 — declarative protocol and deterministic synthetic execution

**Status:** implementation complete pending independent review. This directory is
the BM-03 evidence package. It documents a **simulator**, not a benchmark result.

## Scope delivered

* a generic, frozen protocol compiler with two schedule algorithms
  (`balanced-cyclic-v1`, `explicit-v1`) and the synthetic A/A control schedule;
* one synthetic `BenchmarkAdapter` implementation that replays declared integer
  nanosecond values through the frozen BM-01 five-method seam;
* an injected logical clock, injected capability provider, injected single-use
  readiness provider and a test-only fault plan;
* one controller state machine for control **and** treatment campaigns;
* an exclusive, fsync-durable, append-only structural evidence store whose last
  artifact is `seal.json`;
* a read-only structural replayer that reconstructs the expected inventory,
  freeze, control equality and counts from the declared bundle and scenario.

Source: [`benchmarks/quervant_bench/protocol/`](../../../benchmarks/quervant_bench/protocol/),
[`benchmarks/quervant_bench/execution/`](../../../benchmarks/quervant_bench/execution/).
Fixture: [`benchmarks/experiments/synthetic-execution-smoke/`](../../../benchmarks/experiments/synthetic-execution-smoke/).
Tests: [`benchmarks/quervant_bench/tests/`](../../../benchmarks/quervant_bench/tests/).

## Exit / boundary

* **No real timed acquisition exists in BM-03.** No Criterion timing, live A/A,
  profiler, external engine comparison or real measured adapter invocation.
* `quervant-bench run` remains blocked **before any input/output/clock/process
  side effect** with `BM_ACQUISITION_PROHIBITED` (exit 77). There is no new CLI
  verb, no `simulate` verb and no secret enablement flag.
* `execute_synthetic()` is an internal, importable Python entry point used by
  tests and future BM components. It is not reachable from the CLI, HTTP or a
  subprocess.
* BM-03 issues **no** Gate A–E receipt, no source QA PASS, no attestation, no
  official freeze authorisation, no statistical decision and no performance
  winner. `seal.json` is a *structural* completion marker
  (`status = "sealed-structural"`).
* `benchmarks/quervant_bench/evidence/admission.py` and its synthetic admission
  receipt are **not** called to seal BM-03 measurements.

## Documents

| Document | Contents |
| --- | --- |
| [`design-and-contracts.md`](design-and-contracts.md) | state machine, schedule algorithm, control equality, scenario shape, no-time guarantee, publication and replay responsibilities |
| [`invariant-traceability.md`](invariant-traceability.md) | I-01…I-20 → implementation symbols, adversarial counterexamples and executed test IDs |
| [`schedule-golden.md`](schedule-golden.md) | literal two-arm golden vector, 12×8 structural properties, seed domain, digest method, budget boundaries |
| [`compatibility-matrix.md`](compatibility-matrix.md) | BM-01 / BM-02 / PR15D / D3-C interface status |
| [`verification-report.md`](verification-report.md) | base SHA, branch SHA, per-command QA table, CI status, residual risks, decision rules used |

## Related

* BM-01 contracts: [`docs/pr-artifacts/bm-01/`](../bm-01/README.md)
* BM-02 evidence layer: [`docs/pr-artifacts/bm-02/`](../bm-02/README.md)
* Benchmarking policy: [`docs/BENCHMARKING.md`](../../BENCHMARKING.md)
* Testing philosophy: [`docs/TESTING.md`](../../TESTING.md)
