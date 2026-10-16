# PR 13 — implementation report

**Baseline:** `653b412e0e7df8efe18602479b661629427fab57`
**Status:** implementation complete for the scoped remote mode; **not DONE** —
independent review and remaining evidence gates are open (see
`validation-report.md` and `adversarial-review.md`).

## Files added

| File | Purpose |
|---|---|
| `crates/quervant-objectstore/src/s3.rs` | Production S3-compatible `S3ObjectStore`, opt-in `s3` feature |
| `crates/quervant-objectstore/tests/pr13_s3_rustfs.rs` | Real RustFS provider probe + adapter acceptance |
| `crates/quervant-core/src/remote/config.rs` | `RemoteKeyPrefix`, `RemoteTransferConfig`, `RemoteConfig`, hard limits |
| `crates/quervant-core/src/remote/transfer.rs` | Bounded whole/ranged download scheduler, permit/byte pools, retry policy, stats |
| `crates/quervant-core/src/remote/publication.rs` | Ordered remote publication + CAS state machine and ambiguous-outcome reconciliation |
| `crates/quervant-core/src/remote/mod.rs` | `RemoteIndex`, `RemoteIndexWriter`, hydration, workspace and cache wiring |
| `crates/quervant-core/tests/pr13_remote.rs` | Fake + real RustFS vertical-slice tests |

## Files modified

| File | Change |
|---|---|
| `crates/quervant-objectstore/src/lib.rs` | `#[cfg(feature = "s3")] mod s3` and re-exports |
| `crates/quervant-objectstore/src/contract.rs` | `impl ObjectStore for Arc<S>` forwarding |
| `crates/quervant-objectstore/src/error.rs` | `ObjectStoreError::Transient` and `is_transient()` |
| `crates/quervant-objectstore/src/fake.rs` | `set_put_fault_at` for deterministic multi-object fault targeting |
| `crates/quervant-objectstore/Cargo.toml` | `s3` feature and optional AWS SDK/Tokio dependencies |
| `crates/quervant-core/src/storage/cache.rs` | private `prepare_prefetched` seam; `FillSource`; no accounting changes |
| `crates/quervant-core/src/storage/error.rs` | map `Transient` to a timed-out I/O error |
| `crates/quervant-core/src/index/mod.rs` | `support` made `pub(crate)` for the remote module |
| `crates/quervant-core/src/index/error.rs` | `InvalidConfiguration`, `RemoteConflict` variants |
| `crates/quervant-core/src/lib.rs` | `pub mod remote` |
| `crates/quervant-core/Cargo.toml` | `s3` feature, `futures` dependency, Tokio dev-dependency |

No immutable segment/manifest/`CURRENT` codec, query semantics, `quervant-distributed`,
or vector/graph code was modified. `quervant-core` gained no distributed dependency.

## Architecture and invariants

- **Naming.** One validated prefix `P`; logical `StorageKey K` maps to
  `ObjectKey(P + "/" + K)` only after both are validated. Document key, segment
  id, content digest, generation, remote key and cache key stay distinct.
- **Formats.** Unchanged: `index/CURRENT`, `index/manifests/g-<16hex>.manifest`,
  `index/segments/<digest>.seg`, `index/state/<digest>.state`.
- **Cache ownership.** The existing `SegmentCache` remains the sole owner of
  admission, coalescing, disk reservations, atomic promotion, pinning,
  reconciliation and eviction. The remote path only supplies already-fetched
  bytes through a crate-private seam (`prepare_prefetched`); the cache re-hashes
  them before promotion. No second cache, no bypass, no duplicated accounting.
- **Reader bootstrap.** Remote `CURRENT` → verified manifest → schema/analyzer
  binding and aggregate bound preflight → verified mutation state → segment
  materialization → `Index::open_with_limits` (existing codec/live-mask/PIT
  checks). Missing/corrupt `CURRENT` fails closed with no listing fallback.
- **Writer.** Private per-writer workspace; existing `IndexWriter`; the remote
  base tracked separately. Commit: local commit → upload segments → state →
  manifest (create-if-absent) → verify references → CAS `CURRENT` last. Any
  remote publication failure poisons the writer.
- **Ambiguous outcomes.** `Timeout`/`Transient` on the CAS is reconciled by
  re-reading `CURRENT`: exact candidate → reconciled success; base unchanged or
  unreadable → `RecoveryRequired`; another pointer → `RemoteConflict`.
- **Budgets.** `RemoteTransferConfig` enforces concurrency, aggregate response
  bytes, chunk size, retries, timeout and temp-disk ceilings, rejecting (never
  clamping) zero/oversized/inconsistent values. The effective cache bounds are
  the minimum of the cache, transfer and index limits.

## Deliberate deviations (documented)

1. **Plain-HTTP connector.** The `s3` feature uses the smithy plain-HTTP
   connector so the Rust 1.85 build needs no C/asm TLS toolchain. HTTPS/AWS S3
   requires a separately reviewed TLS feature; the reference provider is a local
   RustFS endpoint.
2. **Timed retry backoff.** Transient retries use a bounded capped exponential
   backoff (100 ms, 200 ms, …, capped at 2 s) through an injected `Sleeper`.
   Under the `s3` feature this is a real Tokio timer; the default local build
   uses an executor-neutral yield so it gains no runtime. This replaces the
   earlier yield-only retry.
3. **`RemoteIndex::writer()` is async.** Hydration needs remote I/O, so the
   writer is opened asynchronously. This is the minimal signature adaptation.

## Corrective pass (file-backed staging, cache-first hydration)

The corrective plan replaced the in-memory ranged assembly and the
`prepare_prefetched(Vec<u8>)` seam:

- **Cache-owned staged-file transfer.** `SegmentCache::prepare_remote` performs
  reconciliation, hit/follower/leader election and disk admission **before**
  invoking the remote fetcher. Only the elected leader fetches; a hit returns a
  pin with zero remote GETs and a follower waits on the existing fill slot.
  `FsDirectory::open_staged` creates a cache-owned `tmp-v1-*` staged file and
  `promote_staged` performs the fsync + rename + directory sync. The cache
  length-checks, streams SHA-256 (on a filesystem worker), and atomically
  promotes; no full-segment `Vec` and no all-chunk `try_collect` remains.
- **Retained byte leases.** A `FetchedChunk { bytes, lease }` keeps the
  aggregate-response byte lease until the staged write completes; the HTTP
  permit is released before the write. `buffer_unordered` is consumed
  incrementally with `while let`, bounding retained buffers to the configured
  ceiling (asserted by the BytePool high-water mark).
- **Timed retry.** Bounded capped exponential backoff through an injected
  `Sleeper`; permits/leases are released before sleeping and cancellation
  prevents later attempts. Tests use a `VirtualSleeper` recording exact delays.
- **Cancellation-safe commit.** After the local `CURRENT` advances, the remote
  writer is marked terminal **synchronously before the first await** and cleared
  only on confirmed remote publication. `insert`, `apply`, `flush`, `refresh`,
  `compact` and further `commit` reject a terminal writer.

## Deliberate deviations (documented)

1. **Plain-HTTP connector.** The `s3` feature uses the smithy plain-HTTP
   connector so the Rust 1.85 build needs no C/asm TLS toolchain. HTTPS/AWS S3
   requires a separately reviewed TLS feature; the reference provider is a local
   RustFS endpoint.

## Deferred / not implemented

- Query-scoped pre-materialization pruning (V08) requires a planner contract
  amendment; no pruning was fabricated.
- Real-RustFS deterministic HTTP fault proxy (abort/delay/corrupt-Content-Range/
  200-for-206/drop-after-CAS) and separate-process crash-at-checkpoint tests.
- Independent typed/time/JSON/geo/PIT/upsert reference oracle (only lexical
  equivalence was executed) and the remote cold/warm benchmark lane.
- `S3ObjectStore::head()` still performs a bounded full GET + hash for a true
  SHA-256; publication verification traffic is accounted separately.

## Final acceptance test infrastructure

Test-only additions (no production behavior change except instrumentation):

- `crates/quervant-objectstore/tests/support/mod.rs`: deterministic loopback
  HTTP/1.1 fault proxy that forwards exact signed bytes and supports
  `TruncateBodyAfter`, `ReplaceStatus200`, `SetContentRange`, `DelayUntil`,
  `Return503`, `ReturnStatus`, `ForwardThenDrop`, `ForwardThenCheckpoint` and
  `BlockBeforeCheckpoint`.
- `crates/quervant-objectstore/tests/pr13_proxy_rustfs.rs` (H01–H04, H06).
- `crates/quervant-core/tests/pr13_remote_proxy.rs` (H06–H12).
- `crates/quervant-core/tests/pr13_crash_rustfs.rs` (K01–K04 child-process
  crash harness with a `child_entrypoint` self re-invocation).
- `crates/quervant-core/tests/pr13_oracle.rs` (O01–O03, O07–O10).
- `crates/quervant-core/tests/pr13_bench_remote.rs` (P01–P04) and
  `benchmarks/reports/pr13-remote-benchmark.csv`.
- `TransferStats::peak_retained_bytes()` added so benchmarks can report the
  measured retained-response ceiling (instrumentation only).

No persisted format, query semantics, public `ObjectStore`/`Directory` contract
or distributed boundary changed.
