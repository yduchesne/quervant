# PR 6 implementation report

> **Branch:** `dev/pr06-writer-lifecycle`
> **Baseline:** `569f4a48f98e2f97d55686c5440588889fc66233` (`main`)
> **Status:** implementation complete for the PR 6 scope; all mandatory local
> gates executed and green (see `validation-report.md`). **No merge performed.**

## 1. Scope delivered

- `quervant_core::index`: local single-writer index lifecycle.
- Create/open a local index over an existing `Directory`.
- Insert-only admission with duplicate-key rejection across pending, flushed and
  committed state (including after reopen).
- Bounded flush (staged, non-visible), non-durable refresh, durable commit,
  immutable reader snapshots and process-local pinned PIT handles.
- Strict `CURRENT` v1 codec, durable generation recovery and fail-closed
  corruption handling.
- Deterministic fault-injection and real-filesystem/separate-process tests.

Explicitly **out of scope** and not implemented: upsert/delete/tombstones/
merges/GC, lexical query execution, remote RustFS/S3 publication, distributed
coordination/failover, vector search, schema migrations, network APIs.

## 2. Files

New production module `crates/quervant-core/src/index/`:

| File | Responsibility |
|---|---|
| `mod.rs` | `Index` opener/factory, `CommittedState`, `CURRENT`-only recovery, schema/analyzer compatibility. |
| `error.rs` | Typed `IndexError` (no panic on malformed persisted input). |
| `limits.rs` | Checked pending/commit/manifest/snapshot/PIT bounds; reuses `SegmentLimits`, `AnalysisLimits`, `contract::Budgets`. |
| `current.rs` | Strict `CURRENT` v1 codec and canonical key helpers. |
| `snapshot.rs` | `ReaderSnapshot`, `SegmentSnapshot`, `SegmentMeta` (thread-safe, `Arc`-held bytes). |
| `writer.rs` | `IndexWriter`: lock, insert, apply, flush, refresh, pin, commit, reconciliation. |
| `pit.rs` | `PinCounter` and `PitHandle` (bounded, process-local). |
| `support.rs` | Bounded verified reads, `CURRENT` read, immutable install, segment build/meta. |

Additive storage change:

- `crates/quervant-core/src/storage/directory.rs`: `Directory::create_dir_all`
  (default `Unsupported`), implemented for `FsDirectory` (create + fsync
  ancestors on Unix) and `MemoryDirectory` (validated no-op).
- `crates/quervant-core/src/storage/error.rs`: `StorageOp::CreateDir`.
- `crates/quervant-core/src/storage/fs.rs`, `memory.rs`: implementations.
- `crates/quervant-core/src/lib.rs`: `pub mod index;` and module docs.

Tests:

- `crates/quervant-core/tests/pr06_lifecycle_unit.rs` (U01–U17).
- `crates/quervant-core/tests/pr06_local_integration.rs` (I01–I12, 3 child
  processes).
- `crates/quervant-core/tests/pr06_faults.rs` (F01–F16).

## 3. Protocol and design decisions

### 3.1 Durable identities

- `index/CURRENT` — sole durable generation selector.
- `index/manifests/g-<16-lowercase-hex>.manifest` — immutable encoded manifest.
- `index/segments/<64-lowercase-sha256>.seg` — immutable content-addressed segment.
- `index/WRITER_LOCK` — exclusive cooperating-writer marker.

Segment id `s-<64hex>`; object key `index/segments/<64hex>.seg`; content
algorithm `0` (existing SHA-256); length/digest recomputed from the actual
segment bytes. Manifest refs are sorted strictly by segment id.

### 3.2 `CURRENT` v1

Exactly five LF-terminated ASCII lines, ≤ 512 bytes, parsed strictly (version,
16 lowercase hex generation ≥ 1, matching manifest filename, canonical nonzero
decimal length, 64 lowercase hex digest; duplicates/unknown fields/trailing
bytes/CR/non-ASCII/leading zeros rejected). `length`/`sha256` describe the
**manifest** bytes. PR 5 fixtures are untouched.

### 3.3 Single-writer ownership

`IndexWriter::open` takes `index/WRITER_LOCK` with `create` (create-new), writes
and fsyncs a marker, then fsyncs the directory. A second cooperating writer gets
`WriterBusy`. The marker is removed only on orderly close/drop. Stale locks are
never stolen; an operator must verify no live writer and delete the marker
before reopening. This is cooperative admission, not automatic failover.

### 3.4 Insert, flush, refresh

- `insert` validates against the schema and `Budgets`, rejects duplicate keys,
  enforces pending count/byte bounds, and converts to `SegmentDocument`
  (`revision = 0`, `live = true`). `apply` rejects upsert/delete and any request
  carrying an idempotency key as `UnsupportedMutation` with no side effects.
- `flush` builds one immutable segment with the existing `SegmentBuilder` and
  stores it in the flushed set; it does not write any file or `CURRENT`.
- `refresh` builds a volatile snapshot of committed + flushed + pending
  documents, enforces the resident-snapshot byte bound, and publishes only on
  complete success. Old snapshots are unchanged.
- `Index::open_existing`/`open_committed` resolve only `CURRENT`; absence is
  `NotInitialized`; corruption/missing bytes are typed errors with no fallback.
- `Index::create` supports empty uncommitted state; the first empty commit
  creates generation 1; later no-op commits return the existing generation
  without rewriting `CURRENT`.

### 3.5 Durable commit ordering

1. Build new segments from the pending batch (flushed segments reused).
2. Install each content-addressed segment: `create` → `write_all` → file
   `sync_all` → directory `sync`. A pre-existing byte-identical file is reused;
   different bytes are a typed `ContentConflict` and are never overwritten.
3. Build the new `Manifest` from previous refs + new refs, canonical-sort,
   enforce the manifest byte bound and round-trip-validate `encode`/`decode`.
4. Install the immutable generation manifest with the same durable ordering.
5. Encode and `atomic_write` `CURRENT` **last**.
6. Acknowledge only after `atomic_write` returns success; then advance committed
   state, clear exactly the committed pending/flushed documents, and publish the
   durable snapshot.

Failure **before** `CURRENT`: the old generation remains authoritative and
pending/flushed state is retained; orphan segment/manifest files are invisible
and not garbage-collected. Failure **after** `CURRENT` replaced (or an unreadable
`CURRENT`): the writer enters `RecoveryRequired` and refuses further writes;
durability is never inferred from a read-back.

### 3.6 Snapshots and PIT

`ReaderSnapshot` holds `Arc<Vec<u8>>` segment bytes and is `Send + Sync`;
independent `SegmentReader`s are constructed per call/thread. The snapshot
exposes generation (`None` for a volatile pre-commit view), view ordinal,
segment count, document count, stored keys and stored-document membership.
`PitHandle` pins exactly one snapshot until close/drop; pins are bounded
(default 128). No GC runs in PR 6, so old readers/PITs remain valid.

### 3.7 Feature canonicalization (no PR 5 format change)

`SegmentBuilder` writes the baseline feature into a `ContainerBuilder` that
already contains it, so a segment's declared required features can contain a
duplicate `(1, 1)`. The manifest codec requires strictly ascending
duplicate-free feature sets. PR 6 canonicalizes (sort + dedup) feature
declarations when deriving `ManifestSegmentRef`s; segment bytes and PR 5 golden
fixtures are unchanged.

## 4. Residual risks

- Stale-lock recovery is manual; there is no unattended failover/fencing.
- A volatile PIT is lost on process crash and does not survive restart.
- No GC/orphan cleanup; failed attempts can leave unreferenced objects.
- The committed-key index and resident snapshot are in memory and bounded by
  limits; PR 6 does not scan all segments per insert.
- Process-crash tests are not a power-loss simulation; durability rests on the
  verified `Directory::atomic_write`/`fsync` contract.
- Remote mode and all query execution are deferred (PR 13, PR 7).
