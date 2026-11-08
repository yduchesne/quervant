# PR 15I-B P1 — offline LZ4 vs Zstd level-1 pre-study

**Scope:** benchmark-only codec laboratory. No production STORED code was
changed. Pinned libraries: `lz4_flex =0.11.6` (checked decode only) and
`zstd =0.13.3` (level 1, no dictionary). Both build under MSRV 1.85.

Tool: `benchmarks/pr15i_b/codec_lab` (standalone locked project, public
`quervant-core` APIs). It reads a fresh post-PR15I-A baseline index, reconstructs
each exact 128-doc STORED v1 block through `encode_stored`, and proves byte
identity: `index body = u16(1) + u64(total) + Σ block[10..]`.

## Fresh baseline (P0 production, post-15I-A)

| n | STORED section | 10K/100K total index |
|---|---:|---:|
| 10,000 | 966,263 | 2,359,997 |
| 100,000 | 9,662,513 | 23,748,601 |

## Candidate STORED section (22-byte header + 40 B/block + compressed blocks)

| n | Codec | Blocks | Compressed payload | Candidate section | Ratio to baseline |
|---|---:|---:|---:|---:|---:|
| 10K | LZ4 | 79 | 163,187 | 166,369 | 0.172 |
| 10K | Zstd1 | 79 | 59,806 | 62,988 | 0.065 |
| 100K | LZ4 | 782 | 1,630,153 | 1,661,455 | 0.172 |
| 100K | Zstd1 | 782 | 596,723 | 628,025 | 0.065 |

Both codecs pass the P1 screen: byte-identical v1 block reconstruction, lossless
round-trip, and candidate 100K STORED section `<` baseline. These are offline
codec numbers only; they are not search/reopen/RustFS acceptance results.

## Controls (v1 body bytes → LZ4 / Zstd1)

| Control | Docs | v1 bytes | LZ4 | Zstd1 |
|---|---:|---:|---:|---:|
| records-0 | 0 | 10 | 11 | 19 |
| records-1 | 1 | 107 | 90 | 90 |
| records-127 | 127 | 12,284 | 2,075 | 787 |
| records-128 | 128 | 12,381 | 2,089 | 788 |
| records-129 | 129 | 12,475 | 2,106 | 792 |
| records-255 | 255 | 24,652 | 3,943 | 1,284 |
| records-256 | 256 | 24,749 | 3,957 | 1,278 |
| five-state | 5 | 130 | 71 | 75 |
| nested-json | 1 | 63 | 61 | 72 |
| high-entropy-60KiB | 1 | 60,034 | 5,813 | 2,064 |

The high-entropy control is 60 KiB because a single stored value is bounded by
the existing `u16` length prefix; the nested-JSON control uses a synthetic
JSON-typed codec schema because the frozen PR15D index schema has no JSON field.

## Selection

Both codecs remain eligible for production candidates. Final selection is
deferred to the source-locked P3 campaign using the frozen gates and the
combined storage/retrieval criterion (`C = S * R < 1.00`). No production codec
dependency has been added yet.
