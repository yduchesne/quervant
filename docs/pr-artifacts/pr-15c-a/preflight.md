# PR 15C-A preflight and correctness challenge

Status: S0 gate record. Written **before** any production edit.

## 1. Pinned baseline

| Item | Value |
|---|---|
| Plan source baseline SHA | `42b19445dd79a90d8701b4306e305c6e4e44cd57` (2026-10-28) |
| `git rev-parse main` | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| `git rev-parse origin/main` | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| Working branch at start | `dev/pr15c-a-immutable-segment` (identical base, zero commits ahead of `main`) |
| Working tree | clean (`git status --short` empty) |
| Toolchain | `rustc 1.98.1`, `cargo 1.98.1`, `cargo +1.85.0` = 1.85.0, `clippy 0.1.98`, `cargo-llvm-cov 0.9.1` |
| `Cargo.lock` | tracked, unmodified, sha256 `83e73c8ea63a115a428690f869356df9dc38a31c06f9fc0a792cbd91fa07b789` |

Decision-matrix rows observed at S0: **X01** (clean baseline), **X05** (existing branch with identical base and no work — reused instead of creating a new name), **X12** (pre-existing `docs/TESTING.md` conflict markers confirmed below), **X13** n/a (test target `pr15b_diagnostics` exists unchanged).

### Baseline test evidence

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib` | PASS — 771 passed, 0 failed, 1 ignored |
| `cargo test -p quervant-core --test pr15b_diagnostics` | PASS — 16 passed, 0 failed (42.17 s) |
| `cargo fmt --all -- --check` | PASS |

### Known baseline document defect (X12)

`docs/TESTING.md` lines 56–59 contain four literal `<<<<<<< HEAD` markers with no
matching `=======`/`>>>>>>>` hunks, exactly as reported by the plan. Reproduced on
the pinned base commit, therefore pre-existing (F3). It is **not** edited by this
PR (plan §X12: "Log baseline doc issue; do not edit unrelated file").

## 2. G1 field classification (17 fields)

| # | Field | Exact type | Ownership | `Send+Sync` | Disposition |
|---|---|---|---|---|---|
| 1 | `bytes` | `Vec<u8>` | heap, sole owner | yes | shared as `Arc<Vec<u8>>` (snapshot's existing `Arc`, no clone) |
| 2 | `limits` | `SegmentLimits` (`Copy`) | inline | yes | shared |
| 3 | `doc_count` | `u64` | inline | yes | shared |
| 4 | `sections` | `Vec<SectionEntry>` (`SectionEntry: Copy`) | heap | yes | shared |
| 5 | `required` | `Vec<(u16, u16)>` | heap | yes | shared |
| 6 | `optional` | `Vec<(u16, u16)>` | heap | yes | shared |
| 7 | `schema` | `CodecSchema { fields: Vec<CodecField>, primary_timestamp: Option<u32> }` | heap | yes | shared |
| 8 | `remap` | `DocRemap { Vec<u64>, Vec<u64>, bool }` | heap | yes | shared |
| 9 | `dictionary` | `Option<DictionaryReader { Vec<(u32, Vec<DictionaryEntry>)> }>` | heap, nested | yes | shared |
| 10 | `norms` | `Option<FieldNormsReader { u64, BTreeMap<u32, FieldNorms> }>` | heap, **map** | yes (`BTreeMap` is `Send+Sync`) | shared after S1 representation change to sorted `Vec` (VSR-G2-03 forbids retained map nodes) |
| 11 | `time_bounds` | `Option<TimeBounds>` (`Copy`, scalars only) | inline | yes | shared, zero heap charge |
| 12 | `geo_bounds` | `Vec<GeoBounds>` (`GeoBounds: Copy`, scalars only) | heap | yes | shared |
| 13 | `json_paths` | `Option<Rc<JsonPathDirectory { Vec<JsonDocOffset> }>>` | heap, **`Rc`** | **no** (`Rc` is neither `Send` nor `Sync`) | shared as `Option<Arc<JsonPathDirectory>>` (X07: the `Rc` is used only through the reader field, the `JsonPathsReader` constructor and `open_json_paths`) |
| 14 | `spatial` | `Option<SpatialIndex { Vec<SpatialField { Vec<SpatialNode> }> }>` | heap, nested | yes | shared |
| 15 | `stored_cache` | `RefCell<Option<Rc<Vec<StoredRecord>>>>` | heap, interior-mutable | **no** | query-local, unchanged |
| 16 | `doc_keys_cache` | `RefCell<Option<Rc<Vec<DocumentKey>>>>` | heap, interior-mutable | **no** | query-local, unchanged |
| 17 | `live_docs_cache` | `RefCell<Option<Rc<Vec<bool>>>>` | heap, interior-mutable | **no** | query-local, unchanged |

Split verified: **14 shared / 3 query-local**, exactly as `VERIFIED_SEGMENT_READER_REUSE.md` §13 G1.

## 3. Allocation-owner inventory reachable from cached state

Every heap owner below was inspected in source. Charge unit = requested usable payload
capacity (`capacity × size_of::<Element>()`, or `String::capacity()`); allocator headers,
rounding and `Vec`/`Arc` inline headers inside a parent element are excluded; the encoded
segment buffer (`Arc<Vec<u8>>`) belongs to the snapshot and is never re-charged.

| Owner | Nested heap owners | Charge |
|---|---|---|
| `VerifiedSegmentState` (one `Arc` payload) | — | `size_of::<VerifiedSegmentState>()`, once |
| `sections: Vec<SectionEntry>` | none (`SectionEntry` is `Copy`) | `capacity * size_of::<SectionEntry>()` |
| `required`, `optional: Vec<(u16,u16)>` | none | `capacity * size_of::<(u16,u16)>()` each |
| `CodecSchema.fields: Vec<CodecField>` | `CodecField.name: String`; `Option<FieldBinding>` → `FieldBinding.id: String`, `.version: String`; `fingerprint: [u8;32]` inline | vector capacity + every `String::capacity()` |
| `DocRemap` | `physical_to_original: Vec<u64>`, `original_to_physical: Vec<u64>`; `identity: bool` inline | both capacities `* size_of::<u64>()` |
| `DictionaryReader.fields: Vec<(u32, Vec<DictionaryEntry>)>` | per-field `Vec<DictionaryEntry>`; `DictionaryEntry.term: String` | outer capacity `* size_of::<(u32, Vec<DictionaryEntry>)>()` + each inner capacity `* size_of::<DictionaryEntry>()` + each `term.capacity()` |
| `FieldNormsReader.fields: Vec<(u32, FieldNorms)>` | `FieldNorms.lengths: Vec<u64>`; other fields inline | vector capacity `* size_of::<(u32, FieldNorms)>()` + each `lengths.capacity() * size_of::<u64>()` |
| `JsonPathDirectory` (`Arc` payload) | `doc_offsets: Vec<JsonDocOffset>` | `size_of::<JsonPathDirectory>()` once + `doc_offsets.capacity() * size_of::<JsonDocOffset>()` |
| `SpatialIndex.fields: Vec<SpatialField>` | per-field `nodes: Vec<SpatialNode>` | outer capacity `* size_of::<SpatialField>()` + each `nodes.capacity() * size_of::<SpatialNode>()` |
| `geo_bounds: Vec<GeoBounds>` | none (`GeoBounds` is `Copy`) | `capacity * size_of::<GeoBounds>()` |
| `time_bounds: Option<TimeBounds>` | none (`Copy`, scalars) | zero |
| `limits`, `doc_count`, scalars | none | zero |

No `Box`, no `HashMap`, no `Rc` (after S1/S2), no opaque allocator node size remains in the
retained graph. **No X09/X99 condition found.**

Query-local caches (15–17) are *not* part of cached state and are never charged.

## 4. Source call graph (verification boundaries)

```
Index::open / IndexWriter::open
  └─ support::read_current            (CURRENT pointer; no bytes trust)
      └─ load_committed_at
          ├─ support::read_verified(CURRENT manifest, descriptor, max_manifest_bytes)   [boundary A]
          ├─ Manifest::decode
          ├─ per segment: support::read_verified(segment key, descriptor, accepted_segment_bytes) [boundary B]
          └─ SegmentReader::open(bytes.clone(), limits)                                  [boundary C]
                ├─ byte-length limit check
                ├─ parse_container(bytes, limits)      -> SHA-256 envelope + per-section digests + structure
                ├─ feature/section agreement checks (norms, json paths, spatial)
                ├─ dictionary<->postings extent check
                ├─ ColumnReader::open_with_doc_count (eager geometry)
                ├─ validate_stored_header
                └─ metadata decoders (schema, remap, dictionary, norms, bounds, json, spatial)
Volatile refresh (writer)      : same boundaries on freshly built bytes
SegmentSnapshot::open_reader   : SegmentReader::open (uncached local path; merge/visibility/writer)
ReaderSnapshot::open_segment_reader
  ├─ ReaderByteBudget::try_reserve(encoded_len)                    [boundary D, unchanged]
  └─ SegmentReader::open(snapshot bytes clone)                     [boundaries C as above]
SegmentReader::verify_content_descriptor : re-verifies descriptor length+SHA-256 on demand
```

PR 15C-A adds **no** trust boundary: `read_verified` (A, B), `parse_container` (C), the
descriptor re-check and boundary D all remain exactly as-is. The cache reuses only state
that already passed A/B/C for the same snapshot-owned `Arc<Vec<u8>>`; a cache hit skips
only the *repeat* of C for that identical immutable allocation (VSR-G3).

## 5. G2 pre-allocation feasibility proof (candidate allowance)

The allowance is derived **before** any retained metadata allocation, never from a
post-decode size sum, and never from a guessed multiplier. Lengths come from the decoded
footer (`ContainerView::sections()`), whose structural validity (contiguity, tiling,
digests, bounds) has already been established by `parse_container`; counts are bounded by
the proven minimum encoded width of each element in that section.

Let `L(k)` be a section body length, `N = doc_count`, `S<T> = size_of::<T>()`, all arithmetic
checked (`u64`). `count_min_bytes(context, c, m, avail)` in the existing decoders proves
`c * m <= avail` for the corresponding `m`, so each `c <= avail / m <= L/m`.

| Class | Proven minimum encoded width | Allowance term |
|---|---|---|
| parser (`sections`) | not needed: `section_count <= limits.max_sections()` | `max_sections * S<SectionEntry>` |
| parser (`required`,`optional`) | not needed: each `count <= limits.max_features()` | `2 * max_features * S<(u16,u16)>` |
| shared state `Arc` | — | `S<VerifiedSegmentState>` |
| schema fields | `count_min_bytes(..., 13, L(Schema)-6)` | `(L(Schema)/13) * S<CodecField>` |
| schema strings | each byte is inside the section | `+ L(Schema)` |
| doc remap | both vectors are exactly `N` | `2 * N * S<u64>` |
| dictionary fields | `count_min_bytes(..., 12, ...)` | `(L(Dictionary)/12) * S<(u32,Vec<DictionaryEntry>)>` |
| dictionary terms | `count_min_bytes(..., 26, ...)` | `(L(Dictionary)/26) * S<DictionaryEntry>` |
| dictionary strings | each byte is inside the section | `+ L(Dictionary)` |
| norms fields | `20 + N` bytes per field (12 header + 8 totals + `>= N` varints) | `(L(FieldNorms)/(20+N)) * S<(u32,FieldNorms)>` |
| norms lengths | each length occupies `>= 1` byte; total elements `= fields*N` | `+ L(FieldNorms) * S<u64>` |
| json offsets | `count_min_bytes(..., 10, ...)`; `Vec::push` growth satisfies `capacity < 2*len + 4` | `(2*(L(JsonPaths)/10) + 4) * S<JsonDocOffset>` |
| json directory `Arc` | — | `+ S<JsonPathDirectory>` |
| spatial fields | `count_min_bytes(..., 20, ...)` | `(L(SpatialPoints)/20) * S<SpatialField>` |
| spatial nodes | fixed 77-byte wire node | `(L(SpatialPoints)/77) * S<SpatialNode>` |
| geo bounds | fixed 55-byte wire entry | `(L(GeoBounds)/55) * S<GeoBounds>` |
| time bounds, scalars | no heap | `0` |

Soundness: for every class the allowance is `>=` the sum of the decoder's own proven
`count * min_width <= section_len` bound times the true element size, and total string
capacities cannot exceed the section bytes that contain them. `Vec::try_reserve_exact(n)`
yields `capacity() == n`; the only amortized-growth vector (`doc_offsets`) is covered by
the `2*len+4` term. Therefore `actual_retained_charge <= allowance` holds for every
admissible segment, and is still **reconciled against measured capacities** before
publication so a violation is discarded rather than published (X41).

Conservative rejection is permitted and occurs for large dictionaries: e.g. a 100 MB
dictionary section yields a ~560 MB allowance that exceeds the 256 MiB default cap, so
that segment uses the verified uncached path. This is the specified behaviour
(VSR-G2-06 "may conservatively reject caching"), not an error.

## 6. G1 `Send + Sync` probe

Proposed composition is `Arc<Vec<u8>>`, `Copy` scalars, `Vec<Copy>` (`SectionEntry`,
`(u16,u16)`, `GeoBounds`), `CodecSchema`, `DocRemap`, `Option<DictionaryReader>`,
`Option<FieldNormsReader>` (sorted `Vec`), `Option<TimeBounds>`, `Option<Arc<JsonPathDirectory>>`,
`Option<SpatialIndex>`, plus one `Option<MetadataReservation>` holding `Arc<MetadataBudget>`
(`AtomicU64`) and `u64`. Every constituent is `Send + Sync`; no `Rc`, `RefCell`, `Cell` or
raw pointer remains. S2 lands `fn assert_send_sync<T: Send + Sync>()` compile-time probes for
`VerifiedSegmentState` and `ReaderSnapshot`.

## 7. Test-before-code invariant → oracle mapping

| Invariant | Test | Kind |
|---|---|---|
| G1-01 traits | `g1_01_verified_state_and_snapshot_are_send_sync` | unit (compile-time) |
| G1-02 local cache isolation | `g1_02_query_local_caches_are_per_reader` | unit |
| G1-03 standalone/open_directory | `g1_03_standalone_and_directory_open_unchanged` | unit + integration |
| G1-04 legacy sections | `g1_04_legacy_segment_features_unchanged` | unit |
| VSR-I01 exact bytes | `g3_01_repeated_reads_reuse_same_verified_state`, `g3_06_same_ids_different_bytes_are_never_trusted` | unit |
| VSR-I02 fail closed | `g3_02..g3_05` corruption/descriptor tests, `g4_04_failed_validation_wakes_waiters` | unit |
| VSR-I03 snapshot isolation | `g3_07` PIT/mask/refresh isolation | unit/integration |
| VSR-I04 thread safety | `g1_01`, `g4_01` (2/8/32-thread barrier, exactly one verification) | unit |
| VSR-I05 bounded memory | `g2_01..g2_11` (zero cap, exact/one-over, overflow, nested classes, last-Arc release) | unit |
| VSR-I06 no execution lock | `g4_09_no_lock_held_after_acquisition` | unit |
| VSR-I07 compatibility | `g1_03`, `g1_04`, PR15B oracles, `pr15c_a_segment_state` parity | unit + integration |
| VSR-I08 provider parity | RustFS cold/fault harness — **BLOCKED EXTERNAL if unavailable** (X31) | integration |
| VSR-I09 safe cleanup | `g2_10`, `g4_08` | unit |
| VSR-I10 fallback valid | `g2_01..g2_04`, `g3_02`, `g4_05` | unit |

## 8. Ambiguities and decision mapping

| # | Ambiguity | Resolution |
|---|---|---|
| 1 | Branch name differs from the plan's suggested `feat/pr15c-a-verified-segment-state`; an identical-base branch exists | **X05** reuse `dev/pr15c-a-immutable-segment`; no reset/force |
| 2 | `reader_copy_limit` argument currently receives `IndexLimits::max_snapshot_bytes()` at every production call site | Not reinterpretation: `MetadataBudget::limit = reader_copy_limit`, i.e. the exact constructor argument, as G2-01 prescribes. No call site and no `IndexLimits` field changes |
| 3 | Decoders are `pub` (`CodecSchema::decode`, `DocRemap::decode`, `DictionaryReader::new`, `FieldNormsReader::decode`, `SpatialIndex::decode`) — threading a meter must not change public signatures | **X07/X38-adjacent**: add `pub(crate) *_metered` variants; existing public functions keep exact signatures and delegate with no meter |
| 4 | `metadata_cap == 0` also means `reader_copy_limit == 0`, which makes boundary-D admission fail first (X28) so the zero-cap branch is unreachable through production construction | Add `#[cfg(test)]`-only `ReaderSnapshot::new_with_metadata_cap_for_test` (independent cap, production construction unchanged) — **X16/X38** |
| 5 | Poisoned slot lock: no dedicated error variant, adding one changes the public error contract | **X24**: map to the existing typed `IndexError::CorruptCommittedState { detail }` and fail closed; the RAII recovery path uses `PoisonError::into_inner` so cleanup never aborts |
| 6 | `LimitExceeded` raised during an *optional* cached build vs genuine over-limit input | **X17/X18**: during the cached build `LimitExceeded` ⇒ release allowance, reset slot, notify, run the authoritative uncached path (which re-raises the identical typed error if the input is genuinely over-limit). Digest/feature/structure/descriptor errors propagate (**X19**) |
| 7 | Section-digest corruption cannot be produced by a single flipped byte (the envelope digest covers the footer) | Tests recompute the trailer envelope digest with the existing `sha256` helper after tampering a footer section digest — same technique already used by the segment codec suites |
| 8 | Real RustFS availability | **X31** — recorded as BLOCKED EXTERNAL if the environment lacks a live instance |
| 9 | `SegmentSnapshot::open_reader` (writer/merge/visibility paths) | Untouched: it is not `ReaderSnapshot::open_segment_reader`; no caching, full validation |
