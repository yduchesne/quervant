# Verified immutable segment-state reuse architecture

**Status:** Approved architectural direction; not yet implemented on `main`. This is a permanent core-engine architecture specification, independent of implementation PR numbering.
**Authority:** This document defines the intended segment verification, snapshot caching, ownership and safety contracts. `../ARCHITECTURE.md` is the top-level architecture index. The existing production implementation remains the source of truth for current behavior until migration is accepted.
**Implementation sequencing:** PR 15C-A is the first prospective delivery vehicle; PR 15C-B separately qualifies performance. Neither owns or changes the enduring contracts recorded here.

## 1. Purpose, scope, and motivation

Quervant's immutable segments are integrity-verified containers. At the currently implemented snapshot-reader boundary, every `ReaderSnapshot::open_segment_reader(index)` reserves the complete encoded segment length against a snapshot reader-copy budget, clones a `Vec<u8>`, and calls `SegmentReader::open`. Opening parses the container, recomputes its SHA-256 envelope, checks feature/schema/section contracts, and decodes immutable structures including JSON-path directories. Repeated queries repeat these costs even for absent or one-hit predicates.

The architecture replaces redundant **per-query verification and immutable metadata decoding** with **snapshot-scoped reuse of successfully verified immutable segment state**. It does not eliminate integrity verification or authorize a cache of mutable query execution state. Performance evidence is maintained separately in `../pr-artifacts/pr-15b/bottleneck-dossier.md` and `../BENCHMARKING.md`; measured host-specific percentages are not normative requirements.

## 2. Non-negotiable invariants

- **VSR-I01 — Exact-byte trust.** Every reusable object corresponds to the exact immutable segment byte allocation verified under the required codec limits. Verification happens before publication; bytes cannot be changed while referenced.
- **VSR-I02 — Fail closed.** No failed or partially initialized validation becomes a cache hit. Every previously enforced container/section/feature/schema/descriptor check remains enforced at the appropriate trust boundary.
- **VSR-I03 — Snapshot isolation.** Each `ReaderSnapshot` owns its cache. Cache entries never carry effective live masks or cross generation/view boundaries; pinned PIT references retain their own snapshot semantics.
- **VSR-I04 — Thread safety.** Shared objects are immutable and `Send + Sync`. `Rc`/`RefCell` and lazy mutable decoded caches remain query-local unless a separate design approves their replacement.
- **VSR-I05 — Bounded memory.** Cached parsed metadata is accounted and bounded. The existing active-reader admission/budget contract remains effective independently of removing physical byte copies.
- **VSR-I06 — No execution locks.** Initialization is synchronized, but no cache lock is held during search, scoring, projection, aggregation or caller-controlled cancellation.
- **VSR-I07 — Contract compatibility.** Public query APIs, errors where relevant, document visibility, scoring/ranking, cursor/PIT rules, durability, format/version and storage provider contracts are unchanged.
- **VSR-I08 — Provider neutrality.** Local and RustFS-backed snapshots use the same verified-state boundary; provider faults, corruption and bootstrap verification must not be hidden by a cache.
- **VSR-I09 — Safe cleanup.** Cache ownership follows snapshot lifetime; active guards may keep a shared immutable object alive, without reference cycles or leaked accounting.
- **VSR-I10 — No silent downgrade.** Resource failure may use an explicitly budgeted uncached path, not bypass verification, budgets or cancellation.

## 3. Existing implementation boundary (baseline, not target)

Relevant current sources are `crates/quervant-core/src/index/snapshot.rs`, `src/segment/reader.rs`, `src/segment/format.rs`, and `src/search/unified.rs`.

`SegmentSnapshot` holds `meta`, `Arc<Vec<u8>>` and document count. `ReaderSnapshot` holds ordered segments, generation-specific masks, binding identity, reader-copy budget and pin ownership. `GuardedSegmentReader` owns a `SegmentReader` and an RAII reservation. `SegmentReader` currently owns a fresh `Vec<u8>`, immutable parsed metadata and three `RefCell<Option<Rc<...>>>` lazy caches for stored records, document keys, and live documents. Query execution and projection acquire readers through `open_segment_reader`.

These are existing semantics to preserve during migration, not evidence that verified-state caching already exists.

## 4. Component and field-ownership contract

**VSR-AD-001 — Snapshot-scoped immutable state.** A private `VerifiedSegmentState` is owned by a snapshot cache entry and shared through `Arc`. A query-local `SegmentReader` borrows or holds that immutable state and retains its existing non-thread-safe lazy caches. The public `GuardedSegmentReader::reader()` borrowing shape remains unchanged.

**VSR-AD-002 — Immutable shared fields.** Target shared state includes the exact `Arc<Vec<u8>>`, checked document count, validated section/feature lists, codec schema, document-ID remap, term dictionary, field norms, time/geo bounds, decoded JSON-path directory, and spatial metadata. Include only metadata proven immutable, safely shareable and created through the existing validation path. Readers must not cache references into temporary owned buffers.

**VSR-AD-003 — Query-local fields.** Keep `stored_cache`, `doc_keys_cache`, and `live_docs_cache` query-local initially; preserve their current lazy decoding semantics and `Rc/RefCell` representation. Effective generation masks remain solely in `ReaderSnapshot`. Query-local sorting, candidate lists, scratch buffers, aggregations, cancellation and meters are never snapshot-cached.

**Field-extraction gate (mandatory before implementation):** Record every existing `SegmentReader` field, its exact Rust type, ownership, borrowing relationships, `Send/Sync` classification, memory charge and shared/local disposition. In particular resolve the current `Rc<JsonPathDirectory>` representation in shared state without making mutable query caches global. Do not guess that all existing metadata types implement `Send + Sync`.

## 5. Construction, validation and publication

**VSR-AD-004 — Verification-once per immutable state.** Create a candidate state using the currently authoritative parser/validator (whole-container SHA-256 envelope; supported features; section extents/digests and structural checks; schema, remap, dictionary/postings consistency, column geometry, stored count, norms, JSON-path feature/section consistency, spatial metadata and bounds). Publish only after all required checks and memory admission succeed.

**VSR-AD-005 — Concurrent first access.** Synchronize initialization of a cache slot per physical segment. At most one successful state is published for that snapshot slot; concurrent callers either wait and reuse it or take a bounded independently verified fallback. Never hold initialization locks while executing queries. Poison/failure paths propagate typed errors and do not install a partially validated object.

**VSR-AD-006 — Byte identity.** Cache key is the owning snapshot instance and canonical segment index, not a segment name, object-store key or caller-provided identifier. A cache hit only references the same immutable `Arc<Vec<u8>>` protected by the snapshot. Mutation or replacement cannot overwrite that allocation. No process-global or cross-snapshot reuse in the first implementation.

**Integrity qualification gate:** Demonstrate that no existing verification performed in `SegmentReader::open` or the storage bootstrap is omitted. Define precisely when a content descriptor is verified and how cached-state reuse preserves that obligation. A checksum/cache bypass, weakened corruption error or unverified provider read is a hard stop.

## 6. Reader-budget and metadata-cache memory governance

**VSR-AD-007 — Two distinct accounts.**
1. **Active-reader admission:** Preserve the existing `ReaderByteBudget` checked-CAS limit, byte-weighted reservation *before* granting a reader and RAII release on guard drop. The encoded byte length remains the logical admission charge even when physical cloning is removed. A cache hit does not grant unlimited concurrent readers.
2. **Retained cache memory:** Maintain an independent bounded accounting of parsed, cache-retained metadata (including the shared objects' attributable retained allocations), with overflow-safe checked arithmetic and release on cache eviction/drop. Already-resident encoded segment bytes must not be falsely charged as newly allocated metadata. Shared allocations must not be double-charged to two cache entries.

**VSR-AD-008 — Admission and fallback.** Admit a successfully verified candidate only if its complete retained-metadata charge fits the cache cap. A cache-cap rejection routes to the current independently validated, bounded uncached-reader path; it must not cause a false cache hit or weaken active-reader limits. On failed decode/allocation or cancellation, release every temporary charge and reservation. Avoid hidden unbounded retention.

**Mandatory unresolved parameter gate:** Before an agent may implement memory admission, derive the cap, allocator-independent accounting formula and per-field retained-byte method from current `IndexLimits`/`SegmentLimits` and snapshot resident-memory contracts. Specify overflow behavior and exact-equal/one-byte-over tests. No arbitrary hard-coded MB cap, guessed `size_of` estimate for heap-owned data or unchecked metadata allocations may be presented as approved design. If a complete bounded accounting model is impossible with existing types, stop and request a separate design decision rather than improvise.

**VSR-AD-009 — Cache lifetime and eviction.** First version supports snapshot-lifetime retention of admitted entries and uncached fallback when no capacity remains; do not build a global LRU or cross-snapshot eviction framework. Preserve in-flight guard ownership on snapshot drop. Memory growth across concurrently retained snapshots remains subject to existing snapshot/pin limits and the new per-snapshot cache account; identify any aggregate residency bound explicitly before implementation.

## 7. Snapshot, PIT, mutation and compaction contracts

**VSR-AD-010 — Visibility remains snapshot-owned.** The canonical segment order and `masks` of the requesting `ReaderSnapshot` determine effective live documents. Verification state contains the physical segment's immutable live bitmap only as encoded data; it never captures generation-specific overlay masks. An older PIT cannot observe a later mutation, delete, update or compaction result. New snapshots instantiate their own cache slots. Existing binding IDs and cursor validation remain unchanged.

Maintain parity for insert, upsert, delete, query mutation, batch mutation, refresh, commit/reopen, point-in-time continuation, and compaction. Cache retention cannot prevent legal cleanup beyond the lifetime already dictated by snapshots, pins and query guards.

## 8. Provider and bootstrap contracts

**VSR-AD-011 — Provider-independent, post-load cache.** Cache only after the authoritative local or RustFS-backed segment bytes have been obtained and validated. It does not substitute for provider reads, content-descriptor verification, manifest/CAS publication, recovery or cold bootstrap. If initial remote read fails, no state may be published. Cache hits must not suppress new provider interactions required by an existing public operation; no new coherence semantics are introduced.

A later global cache, persisted verification evidence, range-backed reader, memory map, cross-snapshot sharing or remote consistency optimization requires a separate architecture amendment.

## 9. Observability and measurement

**VSR-AD-012 — Verifiable reuse.** Add private, deterministic validation witnesses for successful initial verification, cache reuse, fallback, failed initialization, active-reader charge and retained-cache charge. Counters must not alter query control flow or become a new public API. Performance benchmarks must run without diagnostic instrumentation in the timed hot path.

Qualify using correctness-gated, release-mode same-host before/after Criterion trials; preserve the frozen PR 15B baseline without overwriting its manifests. Report cache hit ratio and verification/decode counts separately from wall-time, cumulative allocations, peak retained heap, and contention. Do not extrapolate 10K profiles to 100K without an actual 100K measurement.

## 10. Required tests and adversarial cases

| Test family | Acceptance witness |
|---|---|
| Identity/reuse | Same snapshot and segment verifies once; different snapshot does not inherit state by name |
| Corruption | Header/trailer, section digest, feature, schema, JSON, spatial, norms and descriptor corruption still fail closed |
| Concurrency | Racing initial readers never observe partial state; no execution lock held after acquisition |
| Reservations | Existing reader-budget exact-boundary/one-over, overflow, failed-decode, cancellation and guard-drop semantics retained |
| Metadata cache | Exact cap/one-byte over, overflow, allocation failure, fallback, resident accounting and drop releases |
| Lifetime | Snapshot destroyed with outstanding guards; no leaks, stale references or reference cycles |
| Visibility | Cross-generation mutations/overlays and old PIT isolated from new snapshots |
| Compatibility | Legacy optional sections, existing segment formats, standalone `SegmentReader::open`, local/RustFS provider behavior |
| Query parity | PR 15A regression and PR 15B oracle suites; ordering/scoring/projection/geo/typed/JSON/batch equivalence |
| Performance | Verified reuse counts and ≥3 qualified baseline-versus-optimized trials, with no integrity or budget relaxations |

Unchanged on-disk format, stable public contract and full inherited CI (including real RustFS) are release gates.

## 11. Design-to-implementation status and stops

**Approved architectural direction:** VSR-I01–I10 and VSR-AD-001–012 as documented above. The split between shared immutable state and per-query mutable reader is normative.

**Implementation-blocking detailed design gates still open:** (G1) exhaustive type/field extraction and thread-safety proof; (G2) exact retained-memory accounting, cap, fallback and aggregate residency policy; (G3) verification/descriptor boundary map for all constructors and providers; (G4) deterministic concurrent init/failure policy and test matrix. Resolve and document these *here* before issuing low-reasoning coding-agent instructions. Do not reinterpret this status as authorization to invent missing choices.

**Delivery mapping:** PR 15C-A would implement verified-state reuse only; PR 15C-B would qualify measured improvements; secondary query/top-K/aggregation optimizations remain separately gated. These PR references are delivery metadata, not architectural identifiers or authorities.

## 12. Non-goals and future evolution

No public API or wire/index format changes; no engine rewrite; no segment-codec migration; no unbounded cache; no weakening hash verification; no shared mutable `Rc/RefCell` caches; no global segment cache; no redesign of typed/lexical planner, scoring, batch sharing or aggregation. Future distributed workers may employ the same trust and admission principles, but distributed caching and cross-node coherence require their own architecture.

## 13. Detailed design closure: metadata allocation and initialization

**Status:** Normative design of VSR G1–G4, approved for documentation. This section resolves design discretion; implementation must still satisfy the explicit compile-time, fault, capacity and semantic proof gates below. The cache budget is an **accounted-requested-capacity bound**, not a portable bound on allocator metadata, fragmentation or OS RSS. Never describe it as an exact RSS bound.

### G1 — Exact shared-field disposition and thread-safety contract

Existing `SegmentReader` has 17 fields. Move these **14 immutable fields** into `VerifiedSegmentState`: `bytes: Arc<Vec<u8>>`, `limits: SegmentLimits`, `doc_count: u64`, `sections: Vec<SectionEntry>`, `required: Vec<(u16,u16)>`, `optional: Vec<(u16,u16)>`, `schema: CodecSchema`, `remap: DocRemap`, `dictionary: Option<DictionaryReader>`, `norms: Option<FieldNormsReader>`, `time_bounds: Option<TimeBounds>`, `geo_bounds: Vec<GeoBounds>`, `json_paths: Option<Arc<JsonPathDirectory>>`, `spatial: Option<SpatialIndex>`.

The **three query-local fields** remain `stored_cache: RefCell<Option<Rc<Vec<StoredRecord>>>>`, `doc_keys_cache: RefCell<Option<Rc<Vec<DocumentKey>>>>`, `live_docs_cache: RefCell<Option<Rc<Vec<bool>>>>`; initialize all three empty for every acquired reader. Convert the JSON-path directory sharing handle to `Arc` in the reusable representation; its `Vec<JsonDocOffset>` data are immutable. Keep `JsonPathsReader<'_>` accessors compatible with that handle change. Never share the three mutable caches or snapshot effective-live overlays.

Prove `VerifiedSegmentState: Send + Sync` with a compile-time generic trait assertion in tests. Any existing metadata component that fails these bounds is a **STOP**, not permission to add `unsafe impl Send/Sync`. `SegmentReader` itself stays query-local and need not implement `Send + Sync`. Preserve the standalone `SegmentReader::open(Vec<u8>, SegmentLimits)` public constructor and `GuardedSegmentReader::reader()`.

### G2 — Allocator-aware, construction-time metadata reservation contract

**VSR-G2-01 — Cap and separation.** Per-snapshot retained-metadata capacity `metadata_cap = reader_copy_limit` passed to the same snapshot constructor. It is an independent `u64` checked-reservation account; it **does not** replace, combine with or change the active-reader byte-weighted budget. Each guard continues to reserve the full encoded segment byte length *before acquisition* and releases on guard drop. `metadata_cap=0` disables caching and follows the verified uncached path.

**VSR-G2-02 — What is counted.** Count only additional heap-owned metadata allocations retained by the verified state, expressed as **requested usable payload capacity**. Do not charge the already-resident `Arc<Vec<u8>>` segment byte buffer again. Include every metadata `Vec` payload, nested `Vec` payload, owned `String` payload, any separately allocated `Arc` payload, and every owned map/tree allocation. Stack/inlined fields, allocator headers/rounding and fragmentation are excluded from this *accounted capacity* definition; they must not be mislabeled exact physical consumption.

**VSR-G2-03 — Mandatory representation rule.** Cached metadata must have a closed, auditable allocation graph consisting of fixed-size structs, `Vec<T>`, `String` and `Arc<T>` with known ownership. **Do not retain `BTreeMap` nodes in cached metadata.** For `FieldNormsReader`, replace the internal `BTreeMap<u32,FieldNorms>` with a sorted `Vec<(u32,FieldNorms)>` with identical lookup/duplicate-rejection semantics (binary search); preserve public accessor behavior. Any other allocation-owning type not listed or any hidden map/box internals discovered during implementation requires stopping for an architecture amendment. Do not estimate opaque allocator node size.

**VSR-G2-04 — Reservation before allocation.** Implement a private per-build metadata allocation meter, initialized with a candidate *upper-bound allowance* under the snapshot metadata cap. For each retained allocation, calculate `requested_capacity * size_of::<Element>()` (or string byte capacity), checked for overflow; reserve this amount **before the allocating operation**, and call `try_reserve_exact` / equivalent bounded allocation. If the allocator may yield larger capacity than requested, read the actual resulting capacity and top up the charge *before publication*, otherwise discard the candidate and fall back. A failed reserve, unknown capacity or exceeded cap must not publish a state. Account for `Arc<T>` heap payload once when separately allocated; repeated `Arc` clones incur no payload charge. Prevent double counting of nested inline headers that are already within a vector's element size.

**VSR-G2-05 — Per-type charge inventory.**
- `sections`, `required`, `optional`, `geo_bounds`: `capacity * size_of::<T>()`.
- `CodecSchema`: field-vector capacity × `size_of::<CodecField>()`, plus each field-name `String.capacity()`, plus each present analyzer/normalizer binding `id.capacity() + version.capacity()`; count nested allocations only once.
- `DocRemap`: capacities of `physical_to_original` and `original_to_physical` × `size_of::<u64>()`.
- `DictionaryReader`: outer field-vector capacity × `size_of::<(u32,Vec<DictionaryEntry>)>()`, each inner entry-vector capacity × `size_of::<DictionaryEntry>()`, each `term.capacity()`.
- `FieldNormsReader`: sorted field-vector capacity × `size_of::<(u32,FieldNorms)>()`, plus each `lengths.capacity() * size_of::<u64>()`.
- `JsonPathDirectory`: `doc_offsets.capacity() * size_of::<JsonDocOffset>()`, plus separately allocated `Arc<JsonPathDirectory>` payload if not accounted as inlined shared-state bytes.
- `SpatialIndex`: `fields.capacity() * size_of::<SpatialField>()`, plus each `nodes.capacity() * size_of::<SpatialNode>()`.
- `TimeBounds`, `GeoBounds`, scalar fields, optional tags: no heap charge unless their actual definitions own allocations; if so STOP and amend this inventory.
- `VerifiedSegmentState` allocation: count one shared-state `Arc` payload once; do not count existing encoded bytes twice.

**VSR-G2-06 — Admission and temporary peak.** Before construction, reserve a conservative **candidate allowance** from the metadata budget, based on checked upper bounds for the complete metadata payload of that segment; if it cannot be shown to fit, use the old verified uncached path. Decode metadata under existing `SegmentLimits` and under this candidate allowance; every growing retained allocation must pass its per-allocation meter. On success replace the allowance reservation with the measured requested-capacity charge and return the unused allowance. On failure release it completely. The candidate cannot publish if measured charge exceeds its allowance or cap. Temporary decode allocations remain subject to the unchanged decoder budget; they are not silently treated as retained allocations. Do not simultaneously materialize a second complete segment-byte copy on the cache-hit path. On a cache miss, if existing validation requires a copy, charge and release it under the existing reader budget as before.

**VSR-G2-07 — Cache entry lifetime.** Attach the final metadata reservation directly to the immutable `Arc` state, not just to the slot. Release the charge when the final `Arc` is dropped, including when a guard outlives its snapshot. The budget counter itself is owned through an `Arc` with no cycle. Cache slots retain admitted entries for the snapshot lifetime; no LRU.

**VSR-G2-08 — Deterministic fallback.** Cache cap exceeded, zero cap, reservation rejection or allocation failure during an optional cache build => release candidate charges, then execute the original, fully validating and correctly budgeted uncached-reader construction. A genuine corruption, invalid feature/schema, inconsistent metadata or provider verification failure is **not** an optional cache failure: propagate the same typed error; never mask it by fallback. Concurrency waiting must never retain a metadata charge for a loser candidate.

**G2 implementation-stop rule.** If the chosen metadata representation cannot enforce prior reservation for all retained allocations, or if a conservative candidate preflight cannot be derived from explicit decoded structure counts/limits without guessing, **STOP** and request an amendment. No arbitrary heap multiplier, guessed B-tree node size, post-hoc-only size accounting or unlimited temporary decoded cache is authorized. Acceptance requires exact/one-over and overflow tests for every nested class, together with live budget-counter and drop-path assertions.

### G3 — Immutable-byte verification provenance

Storage materialization and segment interpretation are independent validation boundaries. For committed segments, `index/mod.rs` calls `support::read_verified()` against a manifest `ContentDescriptor` before constructing the reader; `SegmentReader::open` then calls `parse_container` (envelope SHA-256 and full structural validation). Preserve both. The shared-state constructor may skip only subsequent `parse_container` work for its identical immutable `Arc<Vec<u8>>` within the same snapshot. Never cache a state by object key or digest alone. `SegmentReader::verify_content_descriptor` and every existing explicit descriptor-check call site remain authoritative, including standalone and volatile paths. Committed load, volatile refresh, mutation, compaction, local/RustFS cold bootstrap and provider-fault paths require separate test witnesses; any missing or bypassed validation is a STOP. Preserve on-disk bytes and format.

### G4 — Synchronized per-slot initialization

Each snapshot has a segment-indexed slot with `Empty | Building | Ready(Arc<VerifiedSegmentState>)`. Use `Mutex` plus `Condvar`, never a global cache lock. Acquire the slot lock only for state transition, release before allocation/hash/decode, and reacquire for publication and `notify_all`. On ordinary failure or unwind, an RAII build guard restores `Building -> Empty` and wakes all waiters. A poisoned mutex fails closed with a deterministic internal error; no `unwrap` and no publication. A successful `Ready` is immutable until final ownership release.

`open_segment_reader(index)` has **no cancellation argument**; cache construction and waiting therefore do not introduce a new cancellation interface or invented polling interval. Existing search cancellation checks remain unchanged. Threads waiting for initialization do not hold segment bytes, metadata reservations or execution locks beyond their existing active-reader reservation. Admission rejection takes the independently verified uncached path. Racing failed initializations may retry; no negative cache is introduced. Required tests cover first-use race, failed validation and wakeup, resource fallback, poison, panic unwind, no lock across work, zero-cap and guard-outlives-snapshot.

### G1–G4 completion criteria and authority

This section settles the intended representation, cap policy, accounting units, trust boundaries, fallback and concurrency state machine. **Before implementation begins**, compile-time trait checks and allocation-inventory coverage must be shown against fresh source; the implementation agent must STOP rather than extend the architecture for any unlisted owner or unsupported preflight. These are verification gates on a fixed design, not permission to choose another design. PR 15C-A is delivery metadata only; all normative choices remain in this permanent document.
