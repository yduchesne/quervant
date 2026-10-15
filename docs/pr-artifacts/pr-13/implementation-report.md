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
2. **Executor-neutral retry backoff.** Because the core must not require a timer
   runtime, transient retries use a bounded, deterministic executor yield rather
   than wall-clock sleeps; the adapter's request timeout spaces real attempts.
3. **Ranged assembly in memory.** Chunks are assembled into one bounded
   `Vec<u8>` (bounded by the cache's per-object response limit) rather than a
   pre-sized temp file. Peak network memory is bounded by the aggregate response
   ceiling; the cache owns the single on-disk copy.
4. **`RemoteIndex::writer()` is async.** Hydration needs remote I/O, so the
   writer is opened asynchronously. This is the minimal signature adaptation.

## Deferred / not implemented

- Query-scoped pre-materialization pruning (V08) requires a planner contract
  amendment; no pruning was fabricated.
- Real-RustFS interrupted-transfer fault proxy, crash-at-checkpoint
  separate-process tests, and remote benchmarks (see `benchmark-report.md`).
