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

## Known weaknesses / open risks (corrective pass)

1. **`head` uses a bounded full GET + hash.** Correct SHA-256 reporting is
   favored over cost, so reference verification re-reads uploaded objects. For
   large segments this doubles publication bandwidth; a provider-supplied
   cryptographically validated metadata digest would remove it. This traffic is
   accounted separately in stats.
2. **Plain HTTP only.** The `s3` feature has no TLS provider. AWS S3 over HTTPS
   needs an explicit TLS feature; the reference and test provider is local
   RustFS.
3. **`verify_references` cost.** Every immutable object is HEAD-verified before
   CAS; the fake is cheap but the S3 adapter's `head` performs a full GET.
4. **Deferred evidence.** Query-scoped pre-materialization pruning (V08), the
   deterministic real-RustFS HTTP fault proxy (M10/M11/T06/C09),
   separate-process crash-at-checkpoint tests (C10/C11), the independent
   typed/time/JSON/geo/PIT oracle (V02–V05) and the remote benchmark lane
   (P01–P03) are not implemented. GitHub Actions has not been observed.
5. **Resolved since the previous review.** In-memory full-segment assembly was
   replaced by cache-owned staged-file transfer with retained byte leases;
   retry backoff now uses a bounded capped exponential delay (real Tokio timer
   under `s3`, executor-neutral yield by default); and the remote writer is
   poisoned synchronously before the first await after local commit.

## Review checklist status

| Item | Status |
|---|---|
| Cache hit/follower performs zero redundant GET; one leader owns download | PASS (`m06`, `m07`) |
| No full-segment Vec or all-chunks `try_collect`; retained memory bounded | PASS (staged transfer; BytePool peak test) |
| Stage disk charged, verified, fsynced and atomically promoted by cache | PASS (`FsDirectory::open_staged`/`promote_staged`, `m13`) |
| Cancellation at checkpoints leaves no visible incomplete generation | PARTIAL (GET/write covered; real proxy crash not executed) |
| Actual bounded timed retry; no hidden SDK retries | PASS (T01–T04; SDK retries disabled) |
| CAS `CURRENT` last; stale writers rejected; ambiguous never falsely acked | PASS |
| Real RustFS interrupted HTTP and separate-process crash tests | NOT EXECUTED |
| Independent typed/time/JSON/geo/PIT/upsert/delete oracle | PARTIAL (lexical + upsert/delete/reopen) |
| Cold/warm benchmarks and raw metrics | NOT EXECUTED |
| Stable/MSRV, ≥85% coverage, real-provider integration, GitHub Actions | Local stable + MSRV + coverage PASS; CI not observed |
| V08 explicitly deferred and tracked | DEFERRED / NOT EXECUTED |
| Independent reviewer accepts implementation and correctness gates | OPEN |

## Final acceptance adversarial review

Induced-fault evidence (all through the production `S3ObjectStore` and
`RemoteIndexWriter`/`RemoteIndex`, real signed requests to pinned RustFS):

- **No false acknowledgment.** H10 (CAS applied, response dropped) reconciles
  only after re-reading the authoritative `CURRENT`; H11 (CAS never reaches
  RustFS) yields `RecoveryRequired` and a terminal writer. K04 (process killed
  after CAS) reopens the new generation from an empty cache; K03 (killed before
  CAS) reopens with no committed `CURRENT`.
- **No partial cache visibility.** H02 (truncated ranged body), H03 (206→200),
  H04 (bad `Content-Range`) and H09 (cancel during delayed GET) all fail closed;
  H09 asserts no final segment key exists.
- **Stale writers.** H12 (competing writers via proxy) and K01–K04 (crash then
  reopen) never expose a partially published generation.
- **Resource ceilings.** Ranged transfer peak retained bytes were measured at
  exactly `chunk_size × concurrency` (2,097,152 B for 256 KiB × 8); whole-GET
  retains the full object. Concurrency/byte pools remain hard-bounded.
- **No hidden retries.** H06 (2 attempts), H07 (exactly 3 = `max_retries+1`) and
  H08 (1 attempt, no retry) confirm the transfer layer owns retry policy and the
  SDK retry layer stays disabled.

Residual risks (unchanged / new):

- **V08 requires maintainer approval.** Query-scoped pruning is deferred.
- **K05, O04–O06 not executed.** Do not treat as PASS.
- **CI not observed** on the final pushed SHA.
- `S3ObjectStore::head()` still performs a bounded full GET + hash; verification
  traffic is reported separately in the benchmark.
