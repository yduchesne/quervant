# PR 3 — Physical cache-space accounting (Amendment #4, implemented)

> **Status: APPROVED (Decision Addendum #1, A4-DIR-01) and IMPLEMENTED** on
> `dev/storage-abstraction`. This note records the implemented design; it does
> not change any other approved S01–S16 decision.
>
> Linked from `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md`. See also
> [PR03_FS_OFFLOAD_DESIGN.md](PR03_FS_OFFLOAD_DESIGN.md).

## Guarantee

The cache enforces a hard bound on the **aggregate logical content length of
cache-owned regular files plus reserved future file growth** within its
dedicated root:

```text
known_bytes + reserved_bytes <= max_cache_bytes
```

- `known_bytes` is the sum of the logical lengths of every cache-owned regular
  file, each counted **exactly once**.
- `reserved_bytes` is the sum of admitted write growth not yet represented by an
  on-disk charge (temporary/partial bytes).

**Excluded from the guarantee:** filesystem allocation overhead, metadata,
directory entries, sparse-file allocation, compression, snapshots, unrelated
writers, and underlying device free space. It is a logical-length guarantee, not
a bound on actual device blocks (that would require a filesystem quota or
equivalent external enforcement).

## Non-overlapping file ledger

Every cache-owned regular file is represented by exactly one `FileEntry` in the
cache ledger, with the following mutually exclusive lifecycle:

| State | On-disk reality | Charge | Transitions |
|---|---|---|---|
| `Absent` | no file | 0 | `reserve` → reservation |
| reserved (not dispatched) | no file yet | `reserved_bytes` = content length | cancel → `Absent`; dispatch → temp |
| temporary (in progress) | temp file (+ existing destination) | `reserved_bytes` covers the temp growth; the existing destination is already in `known_bytes` | success → published; failure → residual charge or `Absent` |
| published (verified) | destination file | `known_bytes`, `published = true`, pinnable | evict → `evicting` |
| evicting | destination still present | `known_bytes` | delete ok → `Absent`; delete err → `delete_failed` |
| delete-failed | file still present | `known_bytes`, `delete_failed = true` | bounded retry → `evicting` or `Absent` |
| orphan (charged, unverified) | destination file with no live entry | `known_bytes`, `published = false` | verified overwrite → published; evict → `Absent` |

Because the ledger has one entry per file, a file is never double-counted.
Transitions move the charge; they do not duplicate it:

- **Reserve:** `reserved_bytes += content.length`.
- **Publish:** the destination charge moves from any prior orphan entry to the
  new published entry (`known_bytes` changes by `new_len - old_len`), then
  `reserved_bytes -= content.length`. Because a published entry is always
  created for a key that was not a live published entry, this is the only
  in-place change.
- **Failed write:** if a probe of the key shows a residual regular file, it is
  charged as an orphan (`known_bytes += residual`) before the reservation is
  released; otherwise the reservation is simply released.
- **Successful delete:** the file entry is removed and `known_bytes -= len`.
- **Failed delete:** the entry stays charged and `delete_failed` is set.

### Temp/destination overlap

`FsDirectory::atomic_write` creates a same-parent temporary file and renames it
over the destination. For a re-materialization of an existing content-addressed
key, the old destination and the new temp coexist, so the operation temporarily
holds `2 × length`. The design accounts for this without reserving twice: the
existing destination is already charged in `known_bytes`, and `reserved_bytes`
covers only the *new* temp growth. The peak is therefore `known_bytes +
reserved_bytes`, and admission requires it to stay within `max_cache_bytes`.
A4-10 verifies this on the real filesystem by parking inside the temp-created
step and measuring actual file lengths.

## Admission and eviction

- `reserve(bytes)` admits only when `known_bytes + reserved_bytes + bytes <=
  max_cache_bytes`; otherwise it evicts charged files (orphans first, then LRU
  unpinned published entries) and retries.
- Pinned entries are never evicted. If no capacity can be reclaimed, admission
  fails with the existing typed `StorageError::LimitExceeded`; it never blocks a
  worker thread or spins.
- A failed delete is **not** freed capacity. The file stays charged and
  `delete_failed`, and is observable via `CacheStats::delete_failures`. At most
  one bounded retry is attempted per admission (`reserve` clears the retry flag
  once per call), so a permanent failure cannot spin.

## Restart reconciliation

`SegmentCache` reconciliation is **lazy and offloaded**: the first `prepare`
awaits it (and returns any typed failure instead of admitting), so the
infallible `SegmentCache::new` is unchanged. Reconciliation runs on the bounded
filesystem offloader (never on an executor thread), lists the dedicated root,
measures each cache-owned regular file, and charges it as an orphan before any
fill is admitted.

- The cache root must be **dedicated** to cache-owned files. A regular file whose
  name is not `cache-v1-…`, `tmp-v1-…` or a filesystem temp fails reconciliation
  closed (`Corrupt`) rather than being charged or deleted.
- Symlinks and directories are never followed and are not charged (they are
  outside the logical-length guarantee).
- A content-addressed orphan is **never** treated as a verified hit: it carries
  no published entry, so a later `prepare` re-fetches and re-verifies, then
  overwrites it atomically. Its charge moves to the published entry.
- If enumeration/metadata is unavailable, reconciliation fails closed and no
  fill is admitted; the bound is never reported as enforced on an incomplete
  scan.

The scan is bounded by `reconcile_entry_limit` (1024..=262144 entries); exceeding
it fails closed.

### Crash-temporary recovery

`FsDirectory::atomic_write` creates same-parent temporary files named
`.trawler-tmp-<decimal pid>-<decimal counter>`. A crash bypasses `TempGuard`, so
reconciliation recognizes that **exact grammar** (lookalikes fail closed as
unknown files), measures every regular file first, charges each, and only then
deletes recognized temporaries. A temporary whose delete fails stays charged
and is marked `delete_failed` (observable via `CacheStats::delete_failures`),
retried at most once per admission. `.trawler-tmp-*` files are never treated as
verified entries or pinnable segments. PID is not used as a staleness proof;
the cache assumes an exclusively owned dedicated root (see
[PR03_CRASH_TEMP_RECOVERY.md](PR03_CRASH_TEMP_RECOVERY.md)).

### Failed-write reconciliation

When `atomic_write` fails, the worker probes the destination and re-lists the
root for internal temporaries:

- **determinate** (destination present with a known length, or verified
  `NotFound`, and a successful temp inventory): the residual files are charged
  and the reservation is released;
- **indeterminate** (any metadata/list error): the reservation is not released;
  it is retained as `uncertain_bytes` and reconciliation is re-armed, so no fill
  is admitted until a full scan succeeds and clears the uncertain charge.

A directory-sync failure after rename leaves the destination present and is
charged; it is never published as verified without a new verified write.

## API

The only public additions are the approved `Directory` capability
(A4-DIR-01): `Directory::list(&self, prefix, limit)` and
`Directory::file_len(&self, key)`, plus the additive `SegmentCache::shutdown`
from Amendment #3 and the new `CacheStats` observability fields
(`physical_bytes`, `orphan_bytes`, `delete_failures`). No public constructor
changed.

## Tests

A4-01..16 cover offloaded verification, failed-delete retention, bounded retry,
cleanup release, temp/destination overlap (real FS), restart charging,
unverified-orphan rejection, scan-failure refusal, unrelated-file/symlink safety,
bound preservation under concurrency, and real-FS restart/reopen. A3-IO and
A2-ASYNC suites are retained.
