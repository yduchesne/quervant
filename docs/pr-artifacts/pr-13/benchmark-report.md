# PR 13 — benchmark report

**Status: NOT EXECUTED.** No remote-mode benchmark was run for this change.
This file records that gap explicitly rather than fabricating measurements.

## Why

The mandatory local correctness, lint, test, coverage and real-RustFS vertical
slice gates were executed (see `validation-report.md`). The plan's benchmark lane
— fixed corpus/digest, whole-GET versus parallel-ranged cold bootstrap, warm
queries, p50/p95/p99, throughput, GET bytes/count, retries and peak
HTTP/memory/temp-disk — was **not** executed in this environment. The existing
repo benchmark harness (`benchmarks/scripts/`, `crates/quervant-core/benches/`)
targets local CPU workloads and has no remote/RustFS lane yet.

## Instrumentation available for the future lane

The implementation already exposes the counters a remote benchmark needs:

- `RemoteIndex::transfer_stats() -> Arc<TransferStats>` with `requests()`,
  `bytes()`, `retries()`, `range_requests()` and `whole_requests()`.
- `RemoteIndexWriter::transfer_stats()` for hydration/verification traffic.
- `RemoteTransferConfig` forces ranged versus whole transfer deterministically
  via `range_threshold` and `chunk_size`, so the same corpus can be measured in
  both modes.
- Real RustFS tests already cover cold recovery, ranged recovery and CAS races;
  a benchmark lane can reuse the same pinned image and env.

## Required before DONE

- Fixed corpus and digest shared between whole and ranged runs.
- Cold empty-cache bootstrap and warm query latencies (p50/p95/p99), QPS and CPU.
- GET bytes/count and retry counts for whole versus ranged.
- Peak concurrent HTTP requests, live response bytes and temporary disk.
- Comparison against the local `FsDirectory` path on identical data.
