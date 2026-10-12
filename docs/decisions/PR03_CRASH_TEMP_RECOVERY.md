# PR 3 — Crash-temporary recovery and fail-closed write reconciliation

> **Status: implementation note for Amendment #5.** Not a merge approval. This
> refines the A4 physical-accounting design; it does not change approved S01–S16
> or the A4-DIR-01 `Directory::list`/`file_len` extension.

## 1. Producer, grammar, confinement, ownership

`FsDirectory::atomic_write_impl` creates a same-parent regular file via
`temp_path(parent)`:

```text
.trawler-tmp-<decimal pid>-<decimal counter>
```

- **Grammar:** exactly `.trawler-tmp-` followed by a `u64` decimal PID, `-`, and
  a `u64` decimal counter, with no other characters and no path separators.
  Malformed lookalikes (`.trawler-tmp-`, `.trawler-tmp-x-1`,
  `.trawler-tmp-1-2-3`, `.trawler-tmp-1-`) are not recognized and, being
  unknown regular files, fail reconciliation closed.
- **Confinement:** the file lives in the destination's parent directory, which
  for the cache is the dedicated cache root. Symlinks are never followed.
- **Collision:** PID plus a process-local monotonic counter makes names unique
  within a process; a crashed process leaves its temp behind.
- **Ownership:** PID is **not** a staleness proof. The recovery design relies on
  the documented assumption that one cache instance exclusively owns the
  dedicated cache root; it never uses PID age to decide safety.

## 2. Cache-owned versus unknown

| Class | Example | Treatment |
|---|---|---|
| cache content key | `cache-v1-sha256-v1-<hex>-<len>` | charged as orphan; re-verified before reuse |
| legacy cache temp key | `tmp-v1-sha256-v1-<hex>-<len>` | charged, then deleted; failure keeps the charge |
| filesystem temp | `.trawler-tmp-<pid>-<counter>` | charged, then deleted; failure keeps the charge |
| unknown regular file | `index.meta`, malformed temp | **fail closed** (`Corrupt`); never charged or deleted |

`cache-v1-*` and `tmp-v1-*` are deliberately distinct classes: a `tmp-v1-*`
object is never a verified cache entry. None of these is treated as a pinned
segment.

## 3. Recovery order

Reconciliation runs on the bounded filesystem offloader before any fill is
admitted:

1. bounded `list("", limit)` of the dedicated root (fail closed on scan error,
   cap hit, or unreadable entry);
2. measure every regular file with `file_len` (fail closed on any metadata
   error) — **charge first**;
3. attempt deletion of recognized temporary artifacts only after all lengths
   are known;
4. charge a temporary whose deletion fails and mark it deletion-failed; future
   admission respects the charge with at most one bounded retry per admission;
5. unknown regular files fail closed before any deletion.

## 4. Crash points

| Point | On-disk state | Accounting |
|---|---|---|
| before temp creation | nothing | no residual |
| partial temp write | `.trawler-tmp-*` (short) | charged at measured length, deleted |
| after temp fsync, before rename | `.trawler-tmp-*` (full) | charged, deleted |
| after rename, before parent fsync | destination only | destination charged |
| after parent fsync | destination only (durable) | destination charged/published |
| failed destination probe | unknown | **indeterminate**: retain charge, re-arm reconciliation |
| failed temp cleanup | temp remains | charge retained, deletion-failed |
| restart | any of the above | charged by reconciliation before admission |

## 5. Ownership / exclusivity

The cache requires an exclusively owned dedicated cache root (already required
by A4). Reconciliation therefore does not need to prove a temp is stale: it
deletes every recognized temp in its own root. A live writer in the **same**
instance cannot race reconciliation because reconciliation completes before any
fill is admitted. Concurrent cache instances on the same root are unsupported;
enforcing that would require a public lock API (a STOP gate) and is not
implemented. This limitation is documented and tested where practical.

## 6. Accounting transitions (one count per byte)

`physical_bytes = known_bytes + reserved_bytes + uncertain_bytes <= max_cache_bytes`.

| Event | Effect |
|---|---|
| reserve write | `reserved_bytes += len` |
| publish (success) | old orphan charge replaced by new published charge; `reserved_bytes -= len` |
| failed write, dest present | dest charged (`+len`); `reserved_bytes -= len` |
| failed write, dest absent, temps present | temps charged; `reserved_bytes -= len` |
| failed write, dest absent, no temps | `reserved_bytes -= len` |
| failed write, any probe/list/file_len indeterminate | `reserved_bytes -= len; uncertain_bytes += len`; reconciliation re-armed |
| successful reconciliation | actual files charged into `known_bytes`; `uncertain_bytes = 0` |
| successful delete | charge released exactly once |
| failed delete | charge retained, `delete_failed` observable |

A file is represented by at most one ledger entry, so it is never double
counted; the uncertain reservation covers the window in which the on-disk state
cannot be established.

## 7. Overfull root

If the scanned occupancy already exceeds `max_cache_bytes`, reconciliation
charges it and admission fails closed with the existing typed
`StorageError::LimitExceeded`; the cache never claims the invariant holds while
it does not. Bounded cleanup of recognized temps happens during reconciliation,
after which admission is retried.
