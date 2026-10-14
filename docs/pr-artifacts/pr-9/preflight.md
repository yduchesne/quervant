# PR 9 Preflight — stable-key mutations, tombstones, merges and retention

**Status:** pre-implementation artifact. **Base:** `main` at PR #26 merge
(`17fd2b674365bb656ce5f3ea22de5a52cd4bf80f`). PRs 7/8 are merged. Branch:
`dev/stable-key-mutations`. Plan version: 2026-10-14.

## Exact format IDs selected (collision-checked against `src/segment/format.rs`)

| Item | Existing max | Selected | Notes |
|---|---|---|---|
| `SectionKind` | `0x000E` (`FieldNorms`) | `MutationState = 0x000F` | New section, never repurposes an existing id. |
| Required feature id | `0x0007` (`FEATURE_FIELD_NORMS`) | `FEATURE_MUTATION_STATE = 0x0008` | Added to `SUPPORTED_FEATURES` at version 1. |
| Container magic | `TRWSEG01`, `TRWMAN01` | `TRWMSV01` (`ContainerKind::MutationState`) | Reuses the existing container envelope; no existing magic changed. |
| Manifest payload version | `1` | `2` (optional `mutation_state` ref) | Version 1 remains byte-for-byte readable/emitted for legacy. |

The mutation-state sidecar is a dedicated immutable, content-addressed object
under `index/state/<sha256-hex>.state`, wrapped in the existing container
envelope with one `MutationState` section. It is referenced by a version-2
manifest through a validated `(object_key, length, sha256)` reference.

## Verified current APIs

- `Manifest` (`src/segment/manifest.rs`) currently has fields `schema`,
  `segments`, `required_features`, `optional_features`; payload version 1.
- `CommittedState` (`src/index/mod.rs`) currently carries `keys:
  BTreeSet<DocumentKey>` and rejects duplicate committed keys.
- `ReaderSnapshot::new` (`src/index/snapshot.rs`) takes
  `(generation, view_ordinal, segments, segment_limits, pins, reader_copy_limit)`.
- `execute_search` (`src/search/execute.rs`) derives `live` from
  `reader.live_docs()`; the effective live mask is the single injection point.
- `IndexWriter::apply` rejects upsert/delete/idempotency with
  `IndexError::UnsupportedMutation`.
- `Directory` exposes `create`, `open_read`, `exists`, `delete`,
  `atomic_write`, `sync`, `list`, `file_len`; `list` is bounded and is **not**
  used as proof of completeness.

## Invariant ↔ test mapping

| Invariant | Required tests | Implementation phase |
|---|---|---|
| P9-I01 | T01,T04,T14,T23 | 1,2,3 |
| P9-I02 | T02,T03,T05,T06 | 2 |
| P9-I03 | T07,T08,T09 | 2 |
| P9-I04 | T10,T11,T12,T30 | 2 |
| P9-I05 | T13,T14,T15,T26 | 1,2,3 |
| P9-I06 | T16,T17,T18,T19 | 1,2 |
| P9-I07 | T20,T21,T22,T23,T24 | 3 |
| P9-I08 | T27,T28,T29 | 1 |
| P9-I09 | T31,T32,T33 | 5 |
| P9-I10 | T34,T35,T36 | 2,3 |
| P9-I11 | T25,T37 | 1,3 |
| P9-I12 | T38,T39 | 4 |
| P9-I13 | T40,T41 | 2 |
| P9-I14 | T42 | 6 |

## Feasibility STOP-gate findings

1. **Lossless merge (Phase 0.4).** `SegmentBuilder` only accepts
   `SegmentDocument` values and re-analyzes indexed text; it cannot emit
   indexed-but-not-stored fields from `StoredRecord` alone. However, the segment
   reader exposes every decoded structure required for a *structural* merge:
   `doc_keys`, `remap`, `dictionary`/`postings_for_entry` (positions preserved),
   `column_value`, `stored_doc`, `field_norms`, `time_bounds`, `geo_bounds`.
   `build.rs`'s `encode_*` helpers are module-private but the low-level codec
   helpers (`encode_postings_block`, `encode_columns`, `encode_stored`,
   `encode_field_norms`, `DocRemap`, `ContainerBuilder`) are public. A new
   `merge` module can remap decoded structures without reanalysis. **No codec
   prerequisite change is required**; the merge path re-encodes decoded
   structures directly.
2. **Manifest v2 + sidecar coexist with v1 fixture (Phase 0.5).** Version 1
   manifests decode unchanged; version 2 only adds an optional trailing
   reference. New feature/section/container ids are collision-free.
3. **Cross-process reader exclusion.** None exists. Per Phase 5, PR 9 ships a
   **dry-run only** `ReclamationPlan` and no online deletion API.
