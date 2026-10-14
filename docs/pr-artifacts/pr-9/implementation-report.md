# PR 9 implementation report

**Base:** `main` after PR #26 (`17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`).
**Branch:** `dev/stable-key-mutations`. **Working tree:** uncommitted (31 changed
or new paths) at report time. **Toolchains used:** Rust `1.98.1` (active
stable) and Rust `1.85.0` (workspace MSRV).

This report describes the implementation actually present in the tree. It is
not an assertion that PR 9 has been merged or that the roadmap status changed.

## Delivered

### 1. Versioned generation state (`src/index/mutation_state.rs`)

- `MutationStateV1` with strictly ascending `KeyRow` (`key`, `revision`,
  `LIVE`/`DELETED`, winning `segment_id`/`doc_id`) and ascending `ReplayRow`
  (`token`, SHA-256 fingerprint, key, intent, revision).
- Deterministic encode/decode in the shared container envelope
  (`ContainerKind::MutationState`, magic `TRWMSV01`, section
  `SectionKind::MutationState = 0x000F`, required feature
  `FEATURE_MUTATION_STATE = 0x0008`).
- Bounded decode with typed rejection of unknown status/intent, zero revision,
  unsorted/duplicate keys or tokens, malformed lengths and unknown features.
- Deterministic `mutation_fingerprint` over intent, logical key and every field
  state (absent / explicit null / empty multi / scalar / ordered multi).
- `IndexLimits` gains `max_mutation_state_bytes` (32 MiB default, 512 MiB
  ceiling), `max_replay_entries` (100 000 / 1 000 000) and `max_replay_bytes`
  (16 MiB / 256 MiB) with clamped setters.

### 2. Manifest v2 and generation loading

- `Manifest` gains an optional `MutationStateRef { object_key, content_length,
  content_digest }`; payload version 2 encodes it and requires
  `FEATURE_MUTATION_STATE`; version 1 is unchanged.
- `load_committed_at` reads and verifies the sidecar, decodes it, and — for a
  version-1 legacy manifest — synthesizes an in-memory all-live revision-1 state
  from physical document keys (rejecting duplicate live keys) without rewriting
  any bytes.
- `CommittedState` replaces the `keys` set with `state: Arc<MutationStateV1>`
  and validated generation masks.

### 3. Generation-specific visibility (`src/index/visibility.rs`)

- `build_masks_from_readers` validates every live pointer against the real
  segment readers (segment exists, doc id in range, physical key matches, no
  duplicate physical claim) and produces one immutable mask per segment.
- `ReaderSnapshot::new_with_masks` owns the masks and validates mask lengths.
  `effective_live_docs` intersects the segment bitmap with the mask.
- `execute_search` derives its live slice from `effective_live_docs`, so term,
  phrase, prefix/glob/regex/fuzzy, `NOT` and all BM25 statistics use the same
  effective mask.

### 4. Mutation admission and durability (`src/index/writer.rs`)

- Ordered accepted-operation journal with a key-indexed candidate status map
  and a token-indexed replay map; commit derives the candidate state by
  replaying the journal in order.
- `apply` returns `IndexResult<MutationResponse>`; `insert` delegates and keeps
  `Result<()>`. Validation/schema/conflict/budget checks happen before revision
  assignment or state mutation. `checked_add` guards revision overflow.
- `flush` builds a segment without changing visibility; `refresh` publishes a
  volatile snapshot with generation masks and leaves the prior view untouched on
  failure.
- `commit` ordering: segments → sidecar → manifest → atomic `CURRENT`.
  Delete-only commits advance the generation with no new segment. An
  indeterminate `CURRENT` write poisons the writer (`RecoveryRequired`).
- `delete_keys_for_retention` validates the whole batch (nonempty reason,
  deterministic dedup, batch bound, revision-overflow preflight) before
  admission.

### 5. Lossless compaction (`src/index/merge.rs`)

- Single `IndexWriter::compact()` entry point; rejects outstanding mutations
  with `PendingMutations`.
- Deterministic `(segment_id, old_doc_id) -> new_doc_id` mapping for live
  winners; dead physical docs are dropped.
- Re-encodes decoded postings with positions, typed columns, stored records,
  field norms (persisted or legacy-reconstructed) and recomputed time/geo
  bounds; carries revisions, tombstones and the replay ledger unchanged.
- Publishes through the same segments → sidecar → manifest → `CURRENT` order;
  an empty output publishes an empty segment list with no empty segment object.
- No-op for a single all-live segment; otherwise consolidates/reclaims.

### 6. Conservative reclamation (`src/index/reclaim.rs`)

- `Index::reclamation_plan()` classifies `CURRENT_REACHABLE`,
  `HISTORICAL_REACHABLE` and `UNKNOWN` from `CURRENT` plus a bounded inventory.
- No online deletion API; `online_deletion_supported` is always `false` and
  `has_deletable_objects()` is always `false`. Unreferenced objects are
  `UNKNOWN`.

### 7. Tests and benchmarks

- Six PR 9 integration suites plus module unit tests (see
  `test-traceability.md`).
- New `benches/merge.rs` measures `compact()` and search latency before/after
  compaction; declared in `crates/quervant-core/Cargo.toml`.

## Deliberately not implemented

- No cross-process/online GC, no background merge scheduler, no TTL daemon, no
  remote/RustFS path, no distributed or vector functionality.
- No cooperative cancellation inside merge or state decode (T35); no
  indeterminate-post-`CURRENT` fault injection (T30); no dynamic
  revision-overflow injection (T06). These are documented gaps, not claimed
  coverage.
