# PR 13 — remote benchmark report (P01–P04)

**Status:** measured on the real RustFS reference provider. Corpus: 20,000
documents, single segment of **3,244,788 bytes** (~3.1 MiB), corpus digest
`4e80dd39ca95a18e5859e38c7f7881a9272ce737066cfa570876deab4da9ce52`.
3 warm-ups + 20 measured trials per configuration. Raw measurements:
[`benchmarks/reports/pr13-remote-benchmark.json`](../../../benchmarks/reports/pr13-remote-benchmark.json)
(the repo convention ignores raw `*.csv`; the runner also writes a local CSV).

## Environment

- Pinned RustFS `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
  loopback `http://127.0.0.1:9000`, native Linux filesystem (not WSL).
- Production `S3ObjectStore` (AWS SDK `1.96.0`, retries disabled), `RemoteIndex`
  with a fresh empty local workspace per cold trial.
- Command:
  ```sh
  QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 QUERVANT_RUSTFS_REGION=us-east-1 \
  QUERVANT_RUSTFS_BUCKET=quervant-pr13-bench QUERVANT_RUSTFS_ACCESS_KEY=… \
  QUERVANT_RUSTFS_SECRET_KEY=… \
  cargo test -p quervant-core --all-features --test pr13_bench_remote -- --ignored --nocapture --test-threads=1
  ```
- Cache ceiling 1 GiB; whole mode `range_threshold=256 MiB`, `chunk_size=8 MiB`;
  ranged mode `range_threshold=1`, `chunk_size=256 KiB`, 8 concurrent ranges.

## Results (milliseconds)

| Mode | Cold-open p50 | p95 | p99 | Warm query p50 | p95 | p99 | GETs | Bytes | Peak retained | RSS max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Whole GET | 1564.3 | 2502.4 | 3550.4 | 641.4 | 872.1 | 946.4 | 1 | 3,244,788 | 3,244,788 | 93,248 KiB |
| Parallel ranged | 1679.3 | 2354.9 | 2574.3 | 568.2 | 816.6 | 884.7 | 13 | 3,244,788 | 2,097,152 | 108,704 KiB |

## Acceptance

| ID | Result |
|---|---|
| P01 | Whole and ranged both return the same 20,000 hits and the same object bytes; measured above | PASS |
| P02 | Warm scoring issues **zero** remote GETs (asserted per trial); measurements above | PASS |
| P03 | Ranged peak retained response bytes = 2,097,152 = `chunk_size 256 KiB × 8`, i.e. the configured ceiling; no incomplete cache visibility (each cold open asserted 20,000 hits) | PASS |
| P04 | No speedup threshold asserted; both cold modes are within noise of each other on this ~3 MiB segment | PASS |

## Limitations (honest)

- Segment size is ~3.1 MiB, not the plan's 16/64/256 MiB. Larger segments and
  the 1 GiB ceiling were **not** measured; no hard limit was raised.
- `S3ObjectStore::head()` performs a bounded full GET + hash; publication
  reference-verification traffic is separate from cold-open transfer and is not
  broken out here.
- Timings are single-host loopback; they are not a WAN or multi-tenant claim.
- RSS is process-wide `/proc/self/statm`, not allocator-attributed.
