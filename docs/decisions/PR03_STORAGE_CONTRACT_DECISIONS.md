# PR 3 — Storage Contract Decision Record (S01–S16)

> **Status: PROPOSED — PENDING HUMAN APPROVAL. DO NOT IMPLEMENT PUBLIC
> CONTRACTS FROM THIS DOCUMENT YET.**
>
> This register is the Phase 1 (stage 3A) deliverable of
> `TRAWLER_IMPLEMENTATION_PR03_DETAILED_PLAN.md`. It proposes the exact local
> `Directory`, provider-neutral `ObjectStore`, and segment/cache contract
> semantics that PR 3 would implement. Per that plan, a human must approve every
> row S01–S16 (or supply precise amendments) **before** any public trait, type,
> error, or dependency is added to `crates/`.
>
> This document does **not** authorize: a segment codec or manifest schema
> (PR 5), a writer/commit/CURRENT pointer, refresh or PIT retention (PR 6), a
> production S3/RustFS adapter or remote cold bootstrap (PR 13), query execution
> (PR 4/7+), distributed services (v0.2), vectors (v0.3), `mmap`, `io_uring`,
> SPDK, or DPDK. It does not resolve the pre-PR 6 gates `G-DEDUP-MIN` or
> `G-CANON`, which remain **OPEN**.

> **Approval reference:** _none yet._ Replace this line with the approved
> reference (human, date, and any amendments) before implementation begins. No
> GitHub approval URL is implied.

## How to use this record

1. Every row below states a **Decision**, a **Proposed choice**, the
   **preconditions/postconditions**, the **typed errors**, **capabilities**,
   **platform assumptions**, **alternatives considered**, and the **conformance
   fixtures** that will verify it.
2. Accepted statuses for each row: `APPROVED`, `APPROVED WITH CHANGES`,
   `REJECTED`.
3. A row may be re-opened only by an explicit recorded human decision.
4. Proposed Rust signatures are **illustrative shape only**; they are not a
   compile-checked commitment, and the exact naming may change without changing
   the approved semantics. The plan explicitly forbids implementing the
   architecture doc's sketch literally.
5. If you approve the proposed direction unchanged, sign the summary table in
   [Approval request](#approval-request) and mark each status `APPROVED`.

## Scope boundary of PR 3 (restated)

- `trawler-core::storage`: local `Directory` (memory + filesystem), plus the
  `SegmentStore`/`SegmentCache` seam and a minimal bounded verified cache.
- `trawler-objectstore`: provider-neutral async `ObjectStore` contract,
  capability descriptor, typed errors, and a deterministic stateful
  `FakeObjectStore` with fault injection.
- RustFS harness **foundation** only (documented, opt-in, version-pinned); the
  production S3 adapter remains deferred to PR 13.
- All other areas are out of scope, per the detailed plan.

## Cross-cutting invariants these decisions must not violate

1. `trawler-core` runs local-only with no remote service, Tokio runtime, etcd,
   or distributed component.
2. Committed segment bytes are immutable. PR 3 may create opaque test blobs but
   implements no segment codec.
3. A durable local replace synchronizes **file data and containing directory
   metadata** per the supported-platform contract. `rename` alone is not a
   durable commit.
4. Readers opening a named immutable file observe complete old or complete new
   bytes, never a partial replacement. Handle validity after replacement is
   platform-documented, not assumed.
5. Reject absolute paths, `..`, `.`, empty components, NUL, and symlink escape.
   Root confinement is mandatory; TOCTOU promises are limited to what safe std
   APIs can actually enforce.
6. `MemoryDirectory` never pretends to survive process restart or power loss.
7. ObjectStore capabilities are explicit. No assumed S3 conditional-write,
   listing, multipart atomicity, or strong-consistency guarantee. Unsupported
   requirements fail typed, never emulated unsafely.
8. Remote object keys and local cache keys are distinct. Cache eviction never
   invokes authoritative object deletion.
9. A cache entry becomes visible only after complete length + digest
   verification and atomic local promotion. Cancellation/failure leaves no
   readable partial entry.
10. Pinned cache entries cannot be evicted while a lease exists. Byte limits are
    enforced, not exceeded silently.
11. Bounded remote concurrency, retries, memory, and temporary disk use; no
    implicit unbounded whole-object buffering where a stream/range is required.
12. Synchronous local access is isolated from asynchronous network access; no
    blocking remote I/O on synchronous scoring paths.
13. Public errors carry operation/context but never credentials or object bytes.
14. `#![forbid(unsafe_code)]` is preserved. `mmap`, `io_uring`, SPDK are out of
    scope.
15. No commit visibility, manifest, CAS, or fencing protocol is asserted
    implemented in PR 3.

## Phase 0 reconciliation (executed 2026-10-12)

Recorded here so the approval is decision-complete and the plan's mandatory
Phase 0 is auditable. Full command evidence is in the completion report.

| Item | Finding |
|---|---|
| Base branch | `dev/storage-abstraction` at `c54cbf3e673d0ceaba44472a8ea9ab60c781910d` |
| `origin/main` | identical to base (`c54cbf3`) — PR 2 merged, clean tree |
| Workspace | `trawler-core`, `trawler-objectstore`, `trawler-distributed`; Rust 2024; MSRV 1.85 |
| Existing storage code | **None.** `trawler-objectstore` is a placeholder (`project_name` only); `trawler-core` exports only `contract`; no `Directory`/`ObjectStore`/`Segment*`/`FsDirectory`/`MemoryDirectory`/`FakeObjectStore`/RustFS code or dependency |
| `Cargo.lock` | absent (library workspace); no committed lockfile |
| `#![forbid(unsafe_code)]` | present in all three crates |
| Branch difference from plan facts | none material; no duplicate abstraction to reconcile |
| Local linker | GNU `cc`/`gcc`/`clang`/`ld` **not installed**; musl target + `rust-lld` present |
| Baseline baseline QA | `fmt` PASS; `clippy -D warnings` PASS; `doc` PASS; `git diff --check` PASS; `test` GNU **BLOCKED (class 5, missing `cc`)**; `test` musl PASS (22 tests); `llvm-cov` GNU **BLOCKED (class 5)**; `llvm-cov` musl **PASS, 96.62% lines** |

No STOP condition triggered by reconciliation: the branch matches the plan's
verified facts and contains no pre-existing storage abstraction.

## Dependency and platform evidence (verified, not remembered)

Checked with the installed toolchain (`rustc 1.99.0`, `cargo 1.99.0`) and
crates.io on 2026-10-12. Candidate dependencies all satisfy **MSRV 1.85** and
permissive licenses (no ELv2 contamination). Adding any of them remains subject
to review at implementation time.

| Crate | Latest seen | rust-version | License | Purpose |
|---|---|---|---|---|
| `sha2` | 0.11.0 | 1.85 | MIT OR Apache-2.0 | content digest (if SHA-256 approved) |
| `tempfile` | 3.27.0 | 1.63 | MIT OR Apache-2.0 | temp-dir fixtures in tests only |
| `futures` | 0.3.34 | 1.71 | MIT OR Apache-2.0 | minimal executor in tests; optional streams |
| `thiserror` | 2.0.21 | 1.77 | MIT OR Apache-2.0 | error enums (optional) |
| `tracing` | 0.1.44 | 1.65 | MIT | coarse I/O boundary instrumentation (core may depend; must not install a subscriber) |
| `tokio` | 1.53.2 | 1.71 | MIT | **not proposed for PR 3**; production async I/O is PR 13 |
| `tokio-util` | 0.7.20 | 1.85 | MIT | **not proposed** unless a token type is chosen |
| `mockall` | 0.15.0 | 1.77 | MIT OR Apache-2.0 | dev-only interaction tests, only where a stateful fake cannot assert the interaction |
| `blake3` | 1.8.7 | unknown | CC0-1.0 OR Apache-2.0 OR Apache-2.0 WITH LLVM-exception | **alternative** digest, not proposed (no declared MSRV) |

Platform API evidence (std, stable well before MSRV 1.85; to be re-verified
against the pinned toolchain source at implementation):

- `std::fs::File::sync_all` / `sync_data` — data/metadata durability.
- `std::fs::OpenOptions::create_new` — exclusive temp creation.
- `std::fs::rename` — atomic on POSIX; **fails if destination exists on
  Windows**; no std-level atomic replace-over-existing guarantee there.
- Unix directory durability requires `File::open(dir)` + `sync_all`.
- `std::os::unix::fs::OpenOptionsExt::custom_flags` is safe API; `O_NOFOLLOW`
  hardening would require a constant source (e.g. `libc`) and is **not**
  proposed by default (see S01 threat model).
- `async fn` in traits is stable since Rust 1.75; it is **not** `dyn`-compatible.

---

## S01 — Directory path grammar, root confinement, symlink policy

**Decision:** The grammar and normalization of local storage keys, root
confinement, and symlink handling.

**Proposed choice:**

- New validated type `storage::StorageKey` wrapping a `String`.
- Grammar: non-empty; **≤ 1024 bytes**; valid UTF-8; `/`-separated components;
  every component non-empty; no component equal to `.` or `..`; no NUL; no
  backslash; no leading `/` (absolute) and no trailing `/`; no Windows drive or
  UNC prefix; no control characters.
- Validation occurs **before any I/O or side effect**.
- `FsDirectory` is constructed with a canonicalized `root`; every operation
  resolves `root.join(key)` and verifies containment under the canonical root.
- Symlink policy: reject any key path in which a **component or the final name**
  is a symlink, checked with `std::fs::symlink_metadata` at operation time.
  `MemoryDirectory` has no symlinks.
- The residual TOCTOU window between the symlink check and the open is
  **documented honestly** and is outside the PR 3 threat model (PR 3 assumes a
  trusted local operator and no concurrent local attacker mutating the managed
  tree). A future hardened mode may add `O_NOFOLLOW`/`openat` with a reviewed
  dependency; it is explicitly out of scope now.

**Preconditions:** input string. **Postconditions:** rejected keys produce no
filesystem mutation; accepted keys are byte-exact (no Unicode normalization).

**Typed errors:** `InvalidKey { reason }`.

**Alternatives:** allow `..` and canonicalize; percent-decode; normalize Unicode;
allow symlinks resolved within root; `O_NOFOLLOW` from the start.

**Rejected because:** normalization merges distinct identities; `..` and
symlinks enable root escape; `O_NOFOLLOW` hardening needs a new dependency and
still does not make the whole path race-free.

**Conformance:** D-KEY01–D-KEY08 (including real symlinks for D-KEY05/06).

**Status:** PENDING HUMAN APPROVAL

---

## S02 — File read/write handle ownership, offsets, sync semantics

**Decision:** Handle types, ownership/lifetimes, positional reads, and explicit
sync operations.

**Proposed choice:**

```rust
pub trait ReadHandle: Send {
    fn len(&self) -> u64;
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, StorageError>;
}

pub trait WriteHandle: Send {
    fn write_all(&mut self, buf: &[u8]) -> Result<(), StorageError>;
    fn sync_all(&mut self) -> Result<(), StorageError>;
}

pub trait Directory: Send + Sync {
    fn create(&self, key: &StorageKey) -> Result<Box<dyn WriteHandle>, StorageError>;
    fn open_read(&self, key: &StorageKey) -> Result<Box<dyn ReadHandle>, StorageError>;
    // exists/delete/atomic_write/sync per S03/S05
}
```

- Handles are **owned** trait objects and never borrow the directory, so a
  handle cannot dangle after the backend changes.
- `read_at` is positional and immutable; reading at/after EOF returns
  `Ok(0)`; short reads return the number of bytes available; bytes past EOF are
  never invented.
- `sync_all` is the explicit durability barrier for a written file. `create`
  alone is **not** a durability acknowledgement.
- `Directory::sync` (S05) syncs root/directory metadata.

**Preconditions:** valid key; for `read_at`, `offset`/`buf` within `u64`/`usize`.
**Postconditions:** no hidden flush on read; `write_all` writes all bytes or
returns a typed error.

**Typed errors:** `NotFound`, `AlreadyExists`, `Io { operation }`, `Unsupported`.

**Alternatives:** borrowed `&File`; single `read(&mut buf)` with an internal
cursor; `BufReader` ownership.

**Rejected because:** borrowed handles complicate lifetimes and replacement
visibility; a shared internal cursor makes concurrent positional reads
error-prone.

**Conformance:** D-API01, D-API02, D-API07.

**Status:** PENDING HUMAN APPROVAL

---

## S03 — `atomic_write` contract, overwrite behavior, crash points

**Decision:** The durable replacement operation and its exact acknowledgement
boundary.

**Proposed choice:**

```rust
fn atomic_write(&self, key: &StorageKey, data: &[u8]) -> Result<(), StorageError>;
```

Ordered steps (see [crash-point matrix](#atomic_write-crash-point-matrix)):

1. Validate key and confine to root.
2. Create a **unique temp file in the same parent directory** with `create_new`.
3. Write all bytes (handling short writes).
4. `flush` + `sync_all` the temp file.
5. Atomically `rename`/replace the destination.
6. `sync_all` the parent directory.
7. Return `Ok(())` **only after step 6**.

`atomic_write` **replaces** an existing destination. On any failure before step
5, the previous destination is unchanged and the temp file is removed. If the
parent sync (step 6) fails after a successful rename, the call returns a typed
`Io` error — **indeterminate durability is never acknowledged as success**. A
fresh opener after step 6 sees the complete new bytes.

**Preconditions:** valid key; backend/platform supports the guarantee (S04).
**Postconditions:** success ⇒ complete new bytes durable and reachable; failure
before step 5 ⇒ prior destination byte-identical.

**Typed errors:** `InvalidKey`, `Io { operation: Write|Sync|Rename|DirSync }`,
`LimitExceeded`, `Unsupported`.

**Alternatives:** copy-existing-then-truncate in place; write directly then
rename without fsync; acknowledge after rename without parent sync.

**Rejected because:** in-place writes expose partial content; skipping fsyncs
breaks the durability promise; acknowledging before directory sync is a false
durability claim.

**Conformance:** D-API04, D-API05, D-API06, D-API07, F-01–F-08.

**Status:** PENDING HUMAN APPROVAL

---

## S04 — Durability platform support and portability

**Decision:** Which platforms get which durability guarantee, and how
unsupported cases behave.

**Proposed choice:**

- **Supported durable platform:** Unix-like (Linux/POSIX) where file `sync_all`
  and directory `sync_all` are available. `atomic_write` provides the full S03
  guarantee here.
- **Unsupported platforms (including Windows for replace-over-existing):**
  `atomic_write` returns `StorageError::Unsupported` rather than weaker success
  semantics. `FsDirectory` may still support `create`/`open_read`/`exists`/
  `delete` where safe, but `delete`/`atomic_write` durability is documented as
  unavailable.
- `MemoryDirectory` supports the logical contract (atomic visibility) with **no**
  disk durability. A process restart is explicitly out of its contract.
- No claim is made about universal power-loss safety: process-kill tests prove
  process-crash behavior, not hardware power loss. Filesystem-specific
  caveats (e.g. ext4 journal modes, network filesystems) are documented.

**Preconditions:** platform detection at `FsDirectory` construction.
**Postconditions:** callers can branch on `Unsupported` deterministically.

**Typed errors:** `Unsupported { operation, platform }`.

**Alternatives:** emulate durability on all platforms with no-op syncs; document
best-effort only.

**Rejected because:** silent no-op syncs are false durability claims.

**Conformance:** F-01–F-08 on Unix; `Unsupported` unit test for the non-Unix
branch (compile-gated).

**Status:** PENDING HUMAN APPROVAL

---

## S05 — Delete/list/exists visibility and sync semantics

**Decision:** Visibility of existence/deletion and whether listing is a
publication primitive.

**Proposed choice:**

```rust
fn exists(&self, key: &StorageKey) -> Result<bool, StorageError>;
fn delete(&self, key: &StorageKey) -> Result<(), StorageError>;
fn sync(&self) -> Result<(), StorageError>;
```

- `exists` reports current visibility; no caching.
- `delete` is **idempotent**: deleting an absent key returns `Ok(())` (the
  desired postcondition already holds). On Unix, delete returns `Ok` only after
  syncing the parent directory.
- `open_read` on an absent key returns `NotFound`.
- **No public `list` operation in PR 3.** Listing is not required for
  correctness and must not be used as a publication primitive. (A private
  helper may be used internally for temp cleanup.)
- `sync` syncs directory metadata for callers that create files directly via
  `create`/`sync_all` rather than `atomic_write`.

**Preconditions:** valid key. **Postconditions:** documented transitions only.

**Typed errors:** `NotFound` (reads only), `Io`, `Unsupported`.

**Alternatives:** `delete` returns `NotFound`; add `list` for cache management.

**Rejected because:** non-idempotent delete forces callers to special-case
retries; listing-based publication depends on unverified provider consistency
and is unnecessary.

**Conformance:** D-API03, D-API08.

**Status:** PENDING HUMAN APPROVAL

---

## S06 — Directory concurrency and locking

**Decision:** Concurrency guarantees of the `Directory` contract.

**Proposed choice:**

- `Directory: Send + Sync`; multiple concurrent readers are supported.
- Readers that opened a handle before a replacement continue to observe the
  complete old bytes on the supported platform; a new opener observes the
  complete new bytes.
- **A single logical writer per index is enforced at a higher layer (PR 6).**
  `Directory` provides no cross-process lock, no advisory lock, and no fencing
  token. It will not pretend to prevent two writers from racing.
- `Recovery`: PR 3 does not publish commit generations; stale temp cleanup is
  backend-local and must never delete a previously durable destination.

**Typed errors:** none new.

**Alternatives:** lock-file API; per-key mutex; flock-based writer election.

**Rejected because:** writer fencing/leadership is a PR 6 protocol; a
partial lock API would create false fencing guarantees.

**Conformance:** D-API05, F-08.

**Status:** PENDING HUMAN APPROVAL

---

## S07 — Storage error taxonomy and retry classification

**Decision:** The public error set and how operations map to it.

**Proposed choice:** one shared `storage::StorageError`, `#[non_exhaustive]`,
with optional `operation`/`key` context and a retry classification helper:

```rust
#[non_exhaustive]
pub enum StorageError {
    InvalidKey { reason: KeyError },
    NotFound { key: StorageKey },
    AlreadyExists { key: StorageKey },
    Corrupt { key: StorageKey, detail: CorruptionKind },
    IntegrityMismatch { key: StorageKey, expected: ContentDigest, actual: ContentDigest },
    LimitExceeded { limit: u64, requested: u64 },
    Conflict { key: StorageKey },
    Unsupported { operation: StorageOp, platform: &'static str },
    Io { operation: StorageOp, source: std::io::Error },
    Cancelled,
}
```

| Class | Variants | Retryable? |
|---|---|---|
| Caller error | `InvalidKey`, `LimitExceeded` | no (fix input) |
| Expected state | `NotFound`, `AlreadyExists` | no (state-dependent) |
| Integrity | `Corrupt`, `IntegrityMismatch` | re-download only |
| Capability | `Unsupported` | no (choose another path) |
| Transient | `Io` (subset) | caller policy |
| Operation | `Cancelled` | only on explicit retry |

A separate `ObjectStoreError` mirrors this with remote-specific variants
(`Timeout`, `PreconditionFailed`, `UnsupportedCapability`, `Backend`) so remote
semantics never masquerade as local filesystem semantics (S08).

**Alternatives:** per-backend error enums; `anyhow`-style opaque errors.

**Rejected because:** callers cannot classify opaque errors, and per-backend
enums force leaking provider types into core.

**Conformance:** each negative test asserts a specific variant, not a string.

**Status:** PENDING HUMAN APPROVAL

---

## S08 — ObjectStore operations and async contract

**Decision:** The provider-neutral object API shape and async/cancellation model.

**Proposed choice:** in `trawler-objectstore` (no dependency on `trawler-core`):

```rust
#[non_exhaustive]
pub struct ObjectKey(String);      // grammar per S10; distinct type from StorageKey

pub struct ContentDescriptor { pub length: u64, pub digest: ContentDigest }
pub struct ObjectMetadata { pub key: ObjectKey, pub length: u64, pub digest: ContentDigest }

pub struct ByteRange { pub offset: u64, pub length: u64 }

pub struct PutPrecondition;        // e.g. IfAbsent | IfMatch(ContentDigest)

#[non_exhaustive]
pub enum PutOutcome { Created, AlreadyPresent }

pub trait ObjectStore: Send + Sync {
    fn capabilities(&self) -> ObjectStoreCapabilities;
    async fn put(
        &self,
        key: &ObjectKey,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> Result<PutOutcome, ObjectStoreError>;
    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError>;
    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError>;
    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError>;
}

pub struct TransferLimits { pub max_bytes: u64 }
```

- Native `async fn` in traits (MSRV 1.85). The cache seam is generic over
  `S: ObjectStore`, so no dynamic dispatch is required in PR 3. A `dyn`-erasable
  adapter may be added later if a concrete consumer needs it.
- `put` is **immutable**: caller supplies the content descriptor (S10). If the
  key exists with the same digest → idempotent `AlreadyPresent`; different
  digest → typed `Conflict`; `IfAbsent`/`IfMatch` are capability-gated (S09).
- `get` is bounded by `TransferLimits`; the proposed PR 3 shape returns a
  bounded byte buffer. Streaming/range reads are explicitly capability-gated
  and may be deferred to PR 13; whole-object buffering is only allowed under an
  explicit `max_bytes` bound.
- The trait performs **no hidden retries**. Retry/idempotency is caller policy
  (S16).
- Cancellation: dropping the returned future is the cancellation mechanism.
  Operations must not leave a complete-but-unacknowledged object advertised;
  the fake models this at explicit fault stages (S14).

**Preconditions:** validated `ObjectKey`; limits set. **Postconditions:**
observed bytes equal stored bytes on success.

**Typed errors:** `ObjectStoreError::{InvalidKey, NotFound, Conflict,
PreconditionFailed, UnsupportedCapability, LimitExceeded, IntegrityMismatch,
Timeout, Cancelled, Backend}`.

**Alternatives:** `#[async_trait]` boxed futures; streaming `get` in PR 3;
`Vec<u8>` → `Bytes`; provider capability enum embedded in the trait.

**Rejected because:** `async_trait` adds a proc-macro and forced boxing at a
coarse boundary where generics suffice; streaming/range is not needed to verify
PR 3 behavior and would expand scope; provider-specific types must not reach
core contracts.

**Conformance:** O-01–O-12.

**Status:** PENDING HUMAN APPROVAL

---

## S09 — Remote capability discovery and CAS/fencing requirements

**Decision:** How capabilities are advertised and how missing requirements
behave.

**Proposed choice:**

```rust
#[non_exhaustive]
pub struct ObjectStoreCapabilities {
    pub immutable_create: bool,
    pub conditional_replace: bool, // If-Match / CAS
    pub read_after_write: bool,
    pub range_read: bool,
    pub list: bool,
}
```

- Every adapter reports its true capabilities; **no default is assumed true**.
- If a requested precondition or range read is not supported, the operation
  fails with `UnsupportedCapability` (fail closed). It is never emulated with a
  read-then-write sequence that is not atomic.
- `read_after_write` and `conditional_replace` describe provider guarantees
  used later for writer fencing; PR 3 only **records** them. No writer-failover
  protocol is implemented or implied.
- `FakeObjectStore` advertises only what it actually models.

**Alternatives:** assume S3 `If-None-Match`/`If-Match` universally available;
emulate CAS locally.

**Rejected because:** S3-compatible providers differ and RustFS behavior has
not been verified in PR 3; unsafe CAS emulation could produce conflicting
committed generations.

**Conformance:** O-09, and capability-conditional O-01–O-12.

**Status:** PENDING HUMAN APPROVAL

---

## S10 — Object identity, digest and integrity

**Decision:** Key grammar and content-integrity representation.

**Proposed choice:**

```rust
pub struct ObjectKey(String);       // S01 grammar adapted for object paths
pub struct ContentDigest { pub algorithm: DigestAlgorithm, pub bytes: [u8; 32] }
#[non_exhaustive]
pub enum DigestAlgorithm { Sha256V1 }
pub struct ContentDescriptor { pub length: u64, pub digest: ContentDigest }
```

- `ObjectKey` uses the same validated grammar as `StorageKey` but is a **distinct
  type**; object keys and cache keys are never interchangeable.
- Content identity = `(length, SHA-256)`, versioned as `Sha256V1`. Chosen for
  broad availability, stability, and clear provenance; `sha2 0.11` is
  MSRV-1.85-compatible (see evidence table).
- Integrity is verified **before** a cache entry is promoted. Provider ETags are
  not treated as content digests unless independently verified.
- `ContentDigest` equality is constant-time with respect to bytes is not
  required here (non-secret), but comparison is exact.

**Alternatives:** BLAKE3 (no declared MSRV); truncated digests; provider ETag;
no digest (length only).

**Rejected because:** BLAKE3's MSRV is undeclared; ETags are not guaranteed
content digests; length-only cannot detect corruption.

**Conformance:** O-07, C-07, C-08.

**Status:** PENDING HUMAN APPROVAL

---

## S11 — SegmentStore versus SegmentCache division

**Decision:** Ownership boundary between logical identity and local
materialization.

**Proposed choice:**

- `SegmentStore`: maps an immutable logical `SegmentId` (opaque, **test-only in
  PR 3**, explicitly not a committed on-disk format) to an authoritative
  `SegmentDescriptor { object_key: ObjectKey, content: ContentDescriptor }`.
  It performs no caching and no codec work.
- `SegmentCache`: given a descriptor, materializes, verifies, pins, and evicts
  local bytes in a `Directory`. It owns **only** local cache lifecycle; it never
  publishes a manifest and never deletes authoritative objects.
- PR 3 implements the minimal seam plus a deterministic
  `StaticSegmentCatalog`/fake and the bounded cache. It does **not** define a
  manifest, generation, CURRENT pointer, writer, or reader.

```rust
pub struct SegmentId(String); // opaque, PR 3 test identity only
pub struct SegmentDescriptor { pub object_key: ObjectKey, pub content: ContentDescriptor }
pub trait SegmentStore: Send + Sync {
    async fn describe(&self, id: &SegmentId) -> Result<SegmentDescriptor, StorageError>;
}
```

**Preconditions:** descriptor supplied by the authoritative store.
**Postconditions:** cache holds only verified local copies.

**STOP condition:** if approval makes the cache depend on a manifest/generation
format, writer lifecycle, distributed lock, or reader/PIT retention, that is a
PR 5/6/13 concern and must be deferred, not absorbed.

**Alternatives:** merge store and cache into one type; put caching in the
ObjectStore adapter.

**Rejected because:** merging conflates authoritative identity with disposable
local state; caching belongs above the provider-neutral adapter so every
provider shares it.

**Conformance:** C-01–C-14.

**Status:** PENDING HUMAN APPROVAL

---

## S12 — Cache pin/evict concurrency and accounting

**Decision:** Lease/pin semantics, eviction policy, and resource accounting.

**Proposed choice:**

- State machine: `Absent -> Filling(temp) -> Verified -> Published -> Leased`;
  failure/cancellation moves `Filling -> Absent` and removes the temp.
- `prepare` returns an RAII `PinnedSegment`; dropping it releases the lease.
  Pinned entries are never evicted.
- One materialization per key: concurrent `prepare` calls for the same
  descriptor coalesce onto a single fill; others await it.
- Deterministic **LRU** eviction among unpinned entries when adding would exceed
  `max_cache_bytes`. Byte and temp-space budgets are enforced; an object larger
  than the budget fails with `LimitExceeded` and is never partially published.
- Bounded concurrent downloads (`max_concurrent_fills`).
- Accounting (`CacheStats`: bytes, entries, hits, misses, evictions) is exposed
  for tests and coarse tracing.
- Eviction removes only local cache bytes and **must not** call
  `ObjectStore::delete`.

**API sketch:**

```rust
pub struct SegmentCache { /* ... */ }
impl SegmentCache {
    pub async fn prepare(
        &self,
        descriptor: &SegmentDescriptor,
    ) -> Result<PinnedSegment, StorageError>;
}
pub struct PinnedSegment { /* releases lease on drop */ }
impl PinnedSegment {
    pub fn directory_key(&self) -> &StorageKey;
    pub fn descriptor(&self) -> &ContentDescriptor;
}
```

**Alternatives:** no eviction in PR 3; TTL policy; reference-counted entries
without a byte budget.

**Rejected because:** the roadmap requires bounded cache behavior and
eviction/reload; unbounded caches violate invariant 10–11.

**Conformance:** C-01–C-14.

**Status:** PENDING HUMAN APPROVAL

---

## S13 — Async-to-sync materialization seam

**Decision:** How async remote preparation meets synchronous local reads.

**Proposed choice:**

- `SegmentCache::prepare(...)` is `async`; it performs all remote I/O and local
  promotion.
- After `prepare` returns a `PinnedSegment`, all reads are **synchronous**
  positional reads through the local `Directory`. No network I/O occurs on the
  synchronous read path.
- `trawler-core` async functions require no runtime dependency; an executor is
  supplied by the embedding application or by tests (`futures::executor`,
  dev-only in PR 3). Core never initializes a runtime.

**Alternatives:** expose a synchronous `prepare` that blocks on a runtime;
background prefetch threads.

**Rejected because:** blocking on a runtime inside core couples core to a
runtime and risks blocking the caller; background prefetch is out of scope.

**Conformance:** C-01, C-02, C-09.

**Status:** PENDING HUMAN APPROVAL

---

## S14 — Fake/fault-injection semantics

**Decision:** Deterministic fake behavior and failure stages.

**Proposed choice:**

- `FakeObjectStore` is stateful, thread-safe, and deterministic. It stores
  exact bytes and models only explicitly configured capabilities.
- Injected fault stages at real operation boundaries:
  `BeforeWrite`, `MidWrite`, `AfterCommitBeforeAck`, `ReadInterrupt`,
  `CorruptRead`, `Timeout`, `DeleteFailure`, `UnsupportedConditional`.
- Same key + same digest → idempotent `AlreadyPresent`; same key + different
  digest → `Conflict`, original unchanged.
- Faults are configured per key/operation, not via arbitrary sleeps/races.
- The fake claims **no** provider guarantees beyond what it models; it never
  emulates unsupported conditional operations.

**Alternatives:** mock-only tests; random fault injection.

**Rejected because:** deterministic stateful fakes exercise real cache logic;
mocks are reserved for narrow interaction assertions.

**Conformance:** O-01–O-12, C-01–C-14.

**Status:** PENDING HUMAN APPROVAL

---

## S15 — RustFS harness foundation versus production adapter

**Decision:** What PR 3 delivers for RustFS and what stays deferred.

**Proposed choice:**

- PR 3 adds an **opt-in, reproducible harness foundation**: version-pinned
  RustFS image/config, disposable credentials, isolated bucket/prefix, explicit
  endpoint environment variables, deterministic cleanup, and a documented
  integration entry point that **SKIPs** (not passes) when the production S3
  adapter is absent.
- A scaffold that does not exercise a production adapter is **not** a passing
  RustFS integration test and must be labeled as such.
- The production S3 adapter, real `put/head/get`, partial read, timeout/
  corruption checks, and remote cold bootstrap remain **deferred to PR 13**
  unless separately approved.
- If the CI runner supports containers, harness startup is a mandatory PR 3
  integration deliverable; if it cannot start, classify **BLOCKED — ENVIRONMENT**
  and do not substitute a fake.

**Human decision requested:** confirm (a) harness startup is mandatory in PR 3
CI, or (b) foundation-with-SKIP is acceptable and PR 13 owns execution.

**Conformance:** harness start/stop reproducibility, exact command + version
recorded; no S3-compatibility claim.

**Status:** PENDING HUMAN APPROVAL

---

## S16 — Cancellation/retry/idempotency

**Decision:** Cancellation, retry, and idempotency rules for immutable objects
and cache fills.

**Proposed choice:**

- **Immutable identity:** `(ObjectKey, ContentDescriptor)`; replaying a put with
  the same identity is idempotent (`AlreadyPresent`); a different digest for the
  same key is a typed `Conflict`. The original object is never overwritten.
- **Uncertain acknowledgement** (timeout after commit) is not permission to
  overwrite differing content; replay verifies identity.
- **Cancellation:** dropping the future cancels cooperatively; the fake models
  cancellation at explicit boundaries; cache fills clean up temp files.
- **Retries:** the contract performs none. Callers apply bounded retries with
  backoff; retry class is derived from S07. No "retry-after-cancellation"
  guarantee is invented.
- Cache fill retries deduplicate (S12).

**Conformance:** O-02, O-04, O-05, O-06, C-06, C-11.

**Status:** PENDING HUMAN APPROVAL

---

## `atomic_write` crash-point matrix

Distinguishes **process crash** (kill/abort) from **power loss** (hardware).
Deterministic process tests do **not** prove power-loss durability.

| Point | Injected failure | Acknowledged? | Observable-post-crash guarantee | Test |
|---|---|---|---|---|
| Before temp creation | path invalid / create fails | no | prior destination byte-identical | F-03 |
| Mid temp write | short/write error | no | prior destination byte-identical; temp not readable as destination | F-04 |
| After temp `sync_all`, before rename | sync ok, rename fails | no | prior destination byte-identical; temp removed/ignored | F-05 |
| After rename, before parent sync | parent sync fails | **no (`Io`)** | old **or** new complete bytes, never partial; durability indeterminate | F-06 |
| After parent sync | — | **yes** | new bytes durable and visible per supported-platform contract | F-07 |
| Temp cleanup/retry | error then retry | on retry | no corrupt final entry; retry succeeds | F-08 |

Power-loss honesty: F-03–F-08 are process-crash tests; they bound *program*
behavior. Hardware power-loss durability relies on the documented OS/filesystem
fsync contract and is not asserted by a deterministic test.

## Immutable object retry matrix

| Case | Expected result |
|---|---|
| Same key, same digest | idempotent `AlreadyPresent` (or documented safe success) |
| Same key, different digest | typed `Conflict`; original unchanged |
| Timeout before commit | no object; retry proceeds |
| Timeout after commit, before ack | retry detects same identity; no conflict |
| Partial transfer | no complete object advertised |
| Unsupported CAS | typed `UnsupportedCapability`; never emulated |

## Conformance test mapping (all required unless the ADR changes them)

| Family | Owning layer | Representative assertions |
|---|---|---|
| D-KEY01–08 | `StorageKey` + both directories | grammar, traversal, symlink, Unicode identity, duplicate create |
| D-API01–08 | shared `Directory` suite | bytes/length, EOF, exists/delete, replace visibility, concurrent readers, write error, sync error, repeated delete/missing read |
| F-01–08 | `FsDirectory` integration | fresh-instance reopen, subprocess restart, crash-point matrix, temp cleanup |
| O-01–12 | `trawler-objectstore` + fake | immutable round-trip, idempotent/conflict, partial/timeout/corrupt, capability refusal, bounded transfer, concurrency |
| C-01–C-14 | `SegmentCache` + fake remote + real `FsDirectory` | cold/warm, eviction/reload, pinning, interrupted/corrupt/length mismatch, dedup, limit, cancellation, no remote delete, restart |

## Approval request

A human must approve or amend every row. Proposed action: approve S01–S16 as
written, or list changes per ID.

| ID | Topic | Proposed status | Decision |
|---|---|---|---|
| S01 | Key grammar / root confinement / symlinks | PENDING | |
| S02 | Handle ownership / offsets / sync | PENDING | |
| S03 | `atomic_write` contract | PENDING | |
| S04 | Platform durability | PENDING | |
| S05 | Delete/list/exists | PENDING | |
| S06 | Concurrency / locking | PENDING | |
| S07 | Error taxonomy | PENDING | |
| S08 | ObjectStore async contract | PENDING | |
| S09 | Capabilities / CAS / fencing | PENDING | |
| S10 | Identity / digest | PENDING | |
| S11 | SegmentStore vs SegmentCache | PENDING | |
| S12 | Cache pin/evict/accounting | PENDING | |
| S13 | Async-to-sync seam | PENDING | |
| S14 | Fake / fault injection | PENDING | |
| S15 | RustFS harness vs adapter | PENDING | |
| S16 | Cancellation / retry / idempotency | PENDING | |

**Explicit human decisions additionally requested:**

1. **Digest:** confirm SHA-256 (`sha256-v1`) over BLAKE3 (S10).
2. **ObjectStore async:** confirm native `async fn` + generic cache (no
   `async_trait`, no `dyn` in PR 3) (S08).
3. **Dependencies:** approve `sha2` and optional `thiserror`; `tempfile`/
   `futures`/`mockall` as dev-only (evidence table).
4. **Cache in PR 3:** confirm the minimal bounded verified cache is in scope
   (S11/S12) or explicitly defer it.
5. **RustFS harness:** mandatory CI startup vs foundation-with-SKIP (S15).
6. **Windows:** confirm `Unsupported` for durable replace rather than weaker
   semantics (S04).

Until this register is approved, implementation of public contracts is
**BLOCKED** per the detailed plan's STOP conditions.
