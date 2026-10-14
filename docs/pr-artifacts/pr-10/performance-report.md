# PR 10 Performance Report

**Harness:** `crates/quervant-core/benches/typed_analytics.rs` (Criterion,
`harness = false`), registered in `crates/quervant-core/Cargo.toml`.

The bench builds a real committed `MemoryDirectory` index through the public
writer, opens a real snapshot, and times one whole typed search or aggregation
per iteration. Expected results are not asserted inside the timed region; the
fixture asserts the live document count before timing.

- Environment variables: `QUERVANT_PR10_BENCH_SIZE=<n>` runs a single size;
  `QUERVANT_PR10_BENCH_LARGE=1` adds 1M to the default `[10K, 100K]` set.
- Criterion invocation used for the numbers below:
  `cargo bench -p quervant-core --bench typed_analytics -- --warm-up-time 1 --measurement-time 2 --sample-size 10`
  with `QUERVANT_PR10_BENCH_SIZE` set per row.

## Measured results (release profile)

| Workload | 10 000 docs | 100 000 docs |
|---|---:|---:|
| Range `n ∈ [100,200]`, sort by key | 16.3–17.2 ms | 166–176 ms |
| `MatchAll`, sort by `n` desc, top-10 | 18.4–20.3 ms | 185–198 ms |
| Group by `host`+`tags`, Count/Sum/Avg/ExactDistinct | 43.7–49.1 ms | 441–469 ms |

Ranges are the Criterion confidence interval bounds (`time: [low mid high]`).
Scaling from 10K to 100K is close to linear for all three workloads.

For reference, before the per-segment `ColumnAccess` change the 10K release
numbers were range ≈1.03 s, sort ≈0.99 s, aggregate ≈4.87 s; reusing one
`ColumnReader` per segment reduced those by ~49×, ~43× and ~102× respectively
(Criterion reported `p < 0.05` for each change). The improvement is attributable
to avoiding a full column-geometry re-parse for every value read.

## Not measured

- **1 000 000 docs.** The default PR 9 `IndexLimits::max_mutation_state_bytes`
  (32 MiB) is exceeded by a 1M-logical-key mutation state; `writer.insert`
  returns `ResourceLimit { limit: 33_554_432, requested: 33_600_180 }`. Raising
  that ceiling (or using smaller logical key sets) is outside PR 10 scope. The
  harness supports the size via `QUERVANT_PR10_BENCH_LARGE=1`.
- **p50/p95/p99 latency, peak RSS, skipped-segment counters under load.** Only
  Criterion wall-time confidence intervals were captured; skipped-segment
  behavior is verified functionally by `pr10_pruning::t49..t53`.
- **Pruning on/off throughput delta.** Correctness differential is tested; a
  dedicated throughput comparison was not run because the bench fixture uses a
  single time range per segment rather than a pruning-adversarial multi-segment
  layout.

## Claims discipline

No throughput, latency or memory claim is made beyond the measured Criterion
intervals above. The pre/post comparison is a same-machine Criterion change
report, not a cross-machine claim. Distributed, RustFS and vector performance
are out of scope.
