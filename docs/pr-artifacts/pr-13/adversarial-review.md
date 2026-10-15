# PR 13 — adversarial review

**Status:** self-review complete; **independent** acceptance review is still
required before this PR may be marked DONE. This document records the failure
modes examined and the known weaknesses.

## Publication safety

- **Immutable-before-pointer.** Segments, mutation state and the manifest are
  uploaded and then re-verified (`head` length + SHA-256) before the `CURRENT`
  CAS. `CURRENT` is the only mutable authoritative key and is written last.
- **No overwrite.** Every immutable upload uses create-if-absent. Identical
  bytes are idempotent; different bytes under the same key are a typed conflict
  and no pointer is published.
- **Stale writers.** The CAS precondition is the SHA-256 of the observed base
  `CURRENT`; the adapter maps it to the real ETag. A writer whose base changed
  loses with `PreconditionFailed`/`RemoteConflict`.
- **No false acknowledgement.** The writer is terminal after any ambiguous
  publication. `RemoteIndexWriter::commit` returns durability only after the
  CAS (or a reconciled exact-candidate read).
- **No remote cleanup.** Failure paths never delete remote objects; online GC is
  deferred.

## Concurrency

- Two writers from the same base cannot both win: the loser fails at the
  same-generation manifest collision or the `CURRENT` CAS (tested with the fake
  and real RustFS).
- Each writer gets a distinct private workspace, so there is no shared local
  lock or file aliasing between competing writers.
- Cache fills coalesce on identity; the `prepare_prefetched` seam does not
  bypass admission, reservation or atomic promotion.

## Integrity

- Segment bytes are SHA-256 verified by the cache's offload path before atomic
  promotion; ranged chunks are checked for exact length and contiguous
  coverage, and the assembled object is re-hashed by the cache.
- The manifest and mutation state are length- and digest-verified on read.
- The adapter never interprets an ETag as a content digest.

## Budgets and resource bounds

- Global request permits, aggregate live-response bytes, per-segment range
  concurrency, chunk size, retry count, request timeout and temp-disk ceilings
  are enforced and validated; inconsistent values are rejected, not clamped.
- Oversize objects are rejected before allocation.

## Known weaknesses / open risks

1. **Ranged assembly is in memory.** Chunks are assembled into one bounded
   `Vec<u8>`. Peak network memory is bounded by the aggregate response ceiling,
   but a very large object uses both the assembled buffer and in-flight chunk
   buffers. The plan's temp-file assembly would remove the second copy; this is
   a documented deviation, not a hidden one.
2. **`head` uses a bounded full GET + hash.** Correct SHA-256 reporting is
   favored over cost, so reference verification re-reads uploaded objects. For
   large segments this doubles publication bandwidth; a provider-supplied
   cryptographically validated metadata digest would remove it.
3. **Plain HTTP only.** The `s3` feature has no TLS provider. AWS S3 over HTTPS
   needs an explicit TLS feature; the reference and test provider is local
   RustFS.
4. **Retry backoff is a yield, not a timer.** Bounded and deterministic, but it
   does not implement the plan's 100 ms/200 ms wall-clock backoff. Real spacing
   is provided by the adapter request timeout.
5. **Deferred evidence.** Query-scoped pre-materialization pruning, real
   interrupted-transfer injection in front of RustFS, crash-at-checkpoint
   separate-process tests and benchmarks are not implemented.
6. **`verify_references` cost.** Every immutable object is HEAD-verified before
   CAS; the fake is cheap but the S3 adapter's `head` performs a full GET.

## Review checklist status

| Item | Status |
|---|---|
| Verified real atomic CAS | PASS (real RustFS probe) |
| Digest/ETag mapping correct | PASS |
| Immutable objects before pointer | PASS |
| Stale-writer rejection | PASS |
| Ambiguous reconciliation | PASS (fake) |
| Empty-cache cold reopen | PASS (fake + real) |
| Old PIT stability | PASS |
| Bounded HTTP/memory/temp disk | PASS (validated config + pools) |
| Real interrupted download | NOT EXECUTED |
| Cache pinning and no remote delete | PASS |
| Same local/RustFS query oracle | PARTIAL (lexical only) |
| No new format | PASS |
| Stable/MSRV/CI green | Local stable + MSRV PASS; CI not yet observed |
| All artifacts complete | This PR |
