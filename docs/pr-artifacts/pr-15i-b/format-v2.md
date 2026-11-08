# PR 15I-B — STORED v2 format (implemented candidate, rejected)

**Final status: REJECTED.** Both codec candidates failed the frozen rare/medium
latency gate, so production was restored exactly to the merged PR 15I-A code.
This document records the format that was implemented and measured; it is not
present in the final production tree and `FEATURE_STORED_BLOCKS` is not enabled.

## Layout

All integers little endian, offsets relative to the STORED payload start.

| Offset | Width | Field | Invariant |
|---:|---:|---|---|
| 0 | u16 | `stored_version` | `2` |
| 2 | u64 | `total_doc_count` | equals segment `doc_count` |
| 10 | u16 | `block_docs` | `128` |
| 12 | u8 | `codec_id` | `1` LZ4, `2` Zstd level 1 |
| 13 | u8 | `flags` | `0` |
| 14 | u64 | `block_count` | `ceil(total/128)` |
| 22 | 40×N | directory | increasing first-doc id |
| 22+40N | … | compressed blocks | contiguous, no gaps/padding |

Each entry: `first_doc_id` (u64, exactly `i*128`), `doc_count` (u32, 128 except
last), reserved (u32 = 0), `compressed_offset` (u64), `compressed_length` (u64>0),
`uncompressed_length` (u64 ≥ 10).

Every uncompressed block body is an ordinary STORED v1 payload
(`u16(1) + u64(local_count) + exact records`) for 128 consecutive physical docs.
No per-block checksum; the section/segment digests remain authoritative.

## Feature and compatibility

- Required: `(FEATURE_STORED,1)` and `(FEATURE_STORED_BLOCKS=0x000D,1)`.
- Legacy v1 segments (no `0x000D`) read byte-exactly and are never rewritten on
  read.
- v2 body without the required feature, v1 body with the feature, unknown codec,
  unknown flags and an unmerged loser codec id all fail closed.
- New segments and compaction emit v2; old PIT/generations remain readable.

## Validation lifecycle

First STORED access parses the directory, decompresses and semantically
validates **every** block with one segment-wide `DecodeBudget`, then publishes a
metadata-charged directory certificate in the shared verified state
(`OnceLock` + initialization mutex). Later accesses inflate only touched blocks.
Without an access budget or when the metadata reservation fails, a fully
validating uncached path runs on every request. Unselected corruption fails the
first STORED access; no partial certificate is published.

## Rejection reason

The format achieved large storage savings but the measured warm rare/medium
lanes regressed beyond the frozen `B-P06` ceiling. See
[`codec-selection.md`](codec-selection.md).
