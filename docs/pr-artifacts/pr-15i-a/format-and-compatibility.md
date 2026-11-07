# PR 15I-A — compact mutation-state payload version 3

## Wire layout (frozen)

```text
u16  payload_version = 3
u32  segment_id_count = D
D x  { u16 len; bytes[len] }            strict ascending raw UTF-8 bytes, len >= 1
u32  key_row_count = R
R x  { u16 len; bytes[len]             (DocumentKey, unchanged)
       u64 revision                    (little endian, >= 1)
       u8  status                      (0 DELETED, 1 LIVE)
       if LIVE: varint_u64 ordinal; varint_u64 physical_doc_id }
u32  replay_count
...  exact existing version 1 single-key replay serialization
u32  batch_replay_count                  always present, even when zero
...  exact existing version 2 batch-replay serialization
```

- Ordinals and physical document IDs use the existing canonical unsigned LEB128
  (`ByteWriter::varint` / `ByteReader::varint`). Ordinals are additionally
  checked with `u32::try_from` and `ordinal < D`.
- The dictionary contains exactly the segment IDs referenced by live rows,
  sorted with `&str::as_bytes()` ordering. An empty table is valid only when no
  row is live.
- Live rows must carry both pointer fields; deleted rows must carry neither.
- The batch block is always present; there is no V3-specific replay schema.

## Feature tuples

| Artifact | Required features |
|---|---|
| V3 sidecar | `(0x0008,1)` mutation state, `(0x000C,1)` compact V3, and `(0x000B,1)` when V2 history is inherited or any batch replay exists |
| New manifest | carries forward inherited features, adds `(0x0008,1)` and `(0x000C,1)`; retains `(0x000B,1)` when inherited |
| Segment containers | unchanged |
| Manifest wire version / digest / `CURRENT` | unchanged |

A V3 payload requires the sidecar's **required** V3 feature and the manifest's
V3 feature; either mismatch is typed corruption and fails before any state is
published. A reader without `0x000C` rejects the sidecar with
`UnsupportedFeature` before parsing the payload.

## Compatibility matrix

| Stored generation | Pre-V3 binary | V3-capable binary | Next real mutation/compaction |
|---|---|---|---|
| V1 sidecar + V1 manifest | reads | reads identically | writes V3, adds V3 marker |
| V2 sidecar + V2 marker | reads | reads identically | writes V3, retains V2 marker |
| V3 sidecar + V3 marker | `UnsupportedFeature` | reads | writes V3; retains V2 when inherited |
| V3 payload without required V3 marker | rejects | `Corrupt` | no write |
| Manifest requires V3 but sidecar is V1/V2 | rejects | `Corrupt` | no write |
| Unknown feature / payload version | fail closed | fail closed | no write |

No in-place migration and no "old binary reads V3" claim. A no-op commit or
no-op compaction never rewrites a legacy generation; the first accepted mutation
or non-no-op compaction publishes a new V3 generation.

## Resource accounting

V3 decoding keeps all existing per-allocation checks and adds a V3-only
cumulative charge against `max_section_decode_bytes`: dictionary references and
usage flags, table identifier bytes, row structs, logical key bytes, copied
segment strings, replay structs and token/key bytes, and batch replay
structs/token/key bytes. Every charge is checked before the corresponding
reservation or owned copy; overflow is `LimitExceeded`. V1/V2 decoding keeps its
historical budget behavior unchanged (`None` ledger).

V3 reduces **disk** bytes only. `KeyRow` still owns a `String` segment ID, so no
resident-memory reduction is claimed; the campaign measures peak RSS explicitly.
