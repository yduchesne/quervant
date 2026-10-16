# PR 14 — Benchmark report

**Status: NOT EXECUTED.**

No PR 14 benchmark was run. Per `docs/BENCHMARKING.md` and the PR 14 contract, no performance
claim is made, and no comparative (Tantivy/Lucene) threshold is asserted.

## Why

- The plan gates benchmarks on the independent oracle passing and on the 14F vertical corpus,
  which was not built in this execution.
- The new JSON sort path currently performs a per-matching-document indexed-occurrence decode;
  this has not been measured and no throughput claim is offered.
- RustFS cold/warm benchmark lanes require a real provider endpoint that was unavailable; the
  run is **BLOCKED**, not skipped-with-pass.

## Required before any claim

- Deterministic fixture with an independent correctness oracle and dataset digest.
- Local pure/mixed, JSON path sort, projection, aggregation, and RustFS cold/warm lanes
  recorded separately with p50/p95/p99, QPS, CPU/RSS/allocations, remote GET bytes/count, SHA,
  fixture digest and environment.
- Three independently qualified trials for any comparative statement.
