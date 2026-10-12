# PR 3 — Bounded filesystem offloading for async cache preparation (design note)

> Linked from `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md`. This is an
> implementation note for Amendment #3; it does not change approved S01–S16
> semantics. It is **not** a release or merge approval.

## Purpose

`Directory` is intentionally synchronous. `SegmentCache::prepare` is
asynchronous and executor-neutral. Amendment #3 removes blocking filesystem
calls from the polling/executor thread by offloading them to a small, bounded
worker pool with async completion. Search hot-path local reads (`open_read`) stay
synchronous and are excluded. Remote I/O stays async. No Tokio or runtime is
introduced into `trawler-core`.

## Call path before/after

Synchronous filesystem calls reachable from async `prepare`:

| Site | Before | After |
|---|---|---|
| stale temporary cleanup | `directory.delete(temp_key)` on poll | offloaded `delete` job |
| local promotion | `directory.atomic_write(key, &body)` on poll | offloaded `atomic_write` job |
| eviction | `directory.delete(key)` on poll | offloaded `delete` job |
| pinned read (`open_read`) | synchronous (by design) | unchanged (excluded) |

CPU-bound SHA-256 verification still runs on the polling thread and is out of
scope for this amendment.

## Dispatcher interface and bounds

A private (`pub(crate)`) `FsOffloader<D>` owns:

- an `Arc<D>` (`Directory: Send + Sync`, plus `'static`);
- a finite worker pool (default **2** workers; a small constant, never one
  thread per request);
- a bounded job queue: `max_queued_jobs = max_concurrent_fills` and
  `max_queued_bytes = max_cache_bytes` (derived from `CacheConfig`; no public
  API change);
- async admission: `acquire_capacity(bytes)` suspends the caller (waker-based,
  re-checked after every wakeup) until `queued_bytes + bytes <= max_queued_bytes`
  and `queue.len() < max_queued_jobs`.

`queued_bytes` counts payloads that are permitted, queued, or running, so the
sum of in-memory write payloads never exceeds `max_cache_bytes`; no additional
clone of the response buffer is made (the verified `Vec<u8>` moves into the
job). Admission is fair enough to avoid starvation because a completed job
wakes all waiters and the predicate is re-checked.

## Ownership across the worker boundary

- The dispatcher owns the queue and the worker threads.
- Each job owns its operation closure (`Send + 'static`) and its payload; the
  closure captures the `Directory` only as a `&D` parameter, never `D` itself.
- Completion uses a shared `CompletionInner<T>` (`std::sync::Mutex` around
  `{result, waker}` plus an `AtomicBool`). The worker holds a `Completer<T>`;
  the waiter holds a `Completion<T>` future. Registration and completion share
  one mutex, so no wakeup is lost.
- The cache never holds its accounting/fill mutexes during filesystem I/O or
  while calling a waker.

## Runtime neutrality

- Completion is waker/`Future` based; `trawler-core` has no runtime dependency.
- Workers are plain OS threads that may **block**; they are managed and joined
  only by an explicit `shutdown_and_join` (called from a non-async thread, e.g.
  tests). Cache/offloader drop signals shutdown and detaches, so an executor
  thread is never joined.

## Cancellation and job lifecycle

A job is `Queued -> Running -> Completed -> Reconciled`.

- **Cancel before enqueue:** dropping the `prepare` future while awaiting queue
  capacity drops the capacity permit; no job exists.
- **Cancel queued:** the waiter's `Completion` drop sets the job's cancellation
  flag. The worker observes the flag before running the syscall and skips the
  filesystem mutation, reconciling with `StorageError::Cancelled`.
- **Cancel running:** running syscalls are not preemptible. The waiter drop
  does **not** release the byte reservation, fill ownership, or per-key
  eviction marker. The worker completes the syscall and then reconciles
  (publish on success, typed failure otherwise) before any retry can reuse the
  key.
- A detached worker never mutates files after a new fill has reused the key:
  `FillOwnership` (reservation + fill slot) and the `evicting` marker are owned
  by the job until reconciliation.

`FillLeaderGuard` owns `FillOwnership` until the write job is enqueued; it then
`delegate`s that ownership to the job. Dropping the guard before delegation
cancels the fill; dropping after delegation is a no-op. A dropped future is
therefore safe at every point.

## Publication ordering

Remote length + SHA-256 verification complete before the `atomic_write` job is
submitted. The entry becomes published and pinnable only inside the job's
reconcile step, after a successful `atomic_write`; the reconcile constructs the
leader's `PinnedSegment` (`pinned = 1`). A cancelled or failed operation is
never reported as published. Post-publication pin ownership is unchanged: a
dropped leader releases its pin while leaving the verified entry published.

## Eviction ordering

An entry is marked `evicting` before its delete job is submitted and stays
unavailable (not pinnable, not reselectable) until the job's reconcile step
removes it. A concurrent fill for the same identity awaits
`wait_for_key_eviction`. Failed deletion is handled explicitly: accounting is
freed so admission makes progress, but a stale local file may remain
(best-effort cleanup) and is overwritten by a later fill. Cache accounting is a
logical bound; it is **not** a hard physical-disk bound while stale files can
remain. Authoritative remote objects are never deleted.

## Failure and shutdown

- Filesystem errors are converted to typed `StorageError` values; worker panic
  is caught (the job's `complete` still runs) and surfaces as a typed backend
  failure, never masking corruption or durability errors.
- Queue saturation suspends submitters asynchronously; it never blocks an
  executor thread.
- `shutdown_and_join` sets the shutdown flag, wakes workers, and waits for
  queued jobs to drain and workers to exit; it must not be called from an async
  poll. Offloader drop signals shutdown without joining.
- No lock is held during filesystem I/O or while calling a waker.
