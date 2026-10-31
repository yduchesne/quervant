# PR 15D-B — supplemental CPU/RSS report

**Status: `BLOCKED-ATTESTATION`. No resource probe has been executed.**

`benchmarks/pr15d/harness/resource_probe.py` is implemented and covered by 29
deterministic tests using synthetic `/proc` fixtures, but a real probe requires a
completed new campaign plus a fresh human idle attestation for that window (X37/
X38). Running it without those would fabricate evidence, so it was not run.

## What will appear here after an authorized run

For each engine and corpus size (N=10 000 `rare`/K=10 and N=100 000
`medium`/K=10), from three independent probe processes:

| Engine | N | CPU ns/request (min / median / max) | peak RSS bytes (min / median / max) | status |
|---|---|---|---|---|
| quervant | 10000 | pending | pending | pending |
| quervant | 100000 | pending | pending | pending |
| tantivy | 10000 | pending | pending | pending |
| tantivy | 100000 | pending | pending | pending |
| lucene | 10000 | pending | pending | pending |
| lucene | 100000 | pending | pending | pending |

Plus: per-probe `stop_reason`, clock-tick resolution (`SC_CLK_TCK`), contention
state before/after each probe, the fixed representative lane, and the trial
manifest digests proving the performance evidence was untouched.

## Standing limitations (already binding)

- These are **process-level** observations; they are never mixed into
  `engine_ns`, latency ratios or the 20-sample series.
- Peak RSS (`VmHWM`) is not an allocation measurement. Allocations stay
  `NOT_MEASURED` and require a separate, reviewer-approved method.
- A probe that cannot reach 500 ms of CPU before a cap is reported as
  `BELOW_RESOLUTION` / `DIAGNOSTIC_RESOLUTION_LIMIT`, never as zero.
- JVM GC, virtualisation and WSL2 scheduling noise are part of the environment
  and must be disclosed with the fingerprint.

Producing this report requires the operator attestation described in
`b-methodology-fixup.md` (P6).
