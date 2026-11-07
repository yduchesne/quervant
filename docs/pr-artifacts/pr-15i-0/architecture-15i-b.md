# 15I-B — Bounded Compressed Random-Access STORED Blocks (DESIGN CONTRACT)

**Status: `DESIGN_PROPOSAL_ONLY` — detailed block binary layout and validation
lifecycle approval still required; NOT IMPLEMENTED.**

PR 15I-0 changes no production code and no on-disk format. Everything below is a
fixed design direction for a future, separately authorised implementation PR.

## Owner and goal

One separate format change for the STORED section, targeting on-disk size **and**
selective-retrieval latency.

Do **not** revive the rejected PR 15G-E persistent-offset implementation
verbatim. Its observed rare-lane regression must first be explained, and a **new
cold/warm acceptance study** is mandatory before any candidate is written.

## Fixed format direction

- Retain the outer verified segment envelope, section kind `Stored`, immutable
  content identity and mandatory feature negotiation.
- Add a **new required `STORED_BLOCKS` feature** and a versioned STORED payload.
- Logically fixed-size groups of **128 consecutive physical docs** per
  independently compressed block; the last block may contain 1–127 docs.
- Within every uncompressed block preserve **the exact existing v1 record
  encoding**, including header and per-record field semantics, under a separately
  documented block framing.
- Explicit block directory sorted by first physical doc id, storing
  `first_doc_id`, `doc_count`, `compressed_offset`, `compressed_length`,
  `uncompressed_length` using checked 64-bit offsets/lengths. No overlap, no
  holes, terminal boundaries exact.
- A source-level implementation detail not specified here (for example
  directory footer placement) is **not authorised** in this contract. The later
  detailed implementation plan must resolve it explicitly before coding.

## Compression candidates and fixed evaluation order

Implement an offline **benchmark-only** encoder experiment first in the future PR
using **LZ4** and **Zstd level 1** on exactly the same uncompressed blocks,
source-locked on the same corpus.

Evaluate compactness, time to compress/decompress, and seek locality. Retain
exactly one codec by this predeclared multidimensional gate:

1. semantic correctness equal;
2. smaller STORED and total bytes;
3. no more than **10 %** median rare/medium warm-query regression;
4. no more than **10 %** reopen or cold-bootstrap regression;
5. lower combined storage + retrieval cost than the alternative.

If both qualify, choose the codec with the **lower median selected-document
retrieval time**; if within 2 % of one another, prefer the smaller compressed
bytes; if still tied, prefer LZ4. If neither qualifies, revert safely.

These are future evaluation directions. They are **not** approval to implement
anything in 15I-0.

## Validation and trust invariant

An encrypted, signed or digested block alone does not prove semantic validation.

- Before selected-block acceleration, establish a trusted immutable **validation
  certificate** tied to the *exact* content descriptor/digest, schema, limits and
  code-version contract.
- Prove that corruption of **unselected** records remains detectable at a
  contractually equivalent boundary.
- The later implementation plan must define whether expensive full semantic
  validation moves to open/first admission rather than every query, and its
  complete budget/error-precedence consequences.
- Until that is approved, **retain existing full-validation behaviour**. Do not
  return a faster-but-less-checked result.
- A certificate does not survive different bytes, different limits or a
  different schema. Any optional cache must be bounded, counted and immutable.

## Reader / writer boundaries

`segment/stored.rs`, `segment/format.rs`, `segment/reader.rs`, segment producer
`segment/build.rs`, compaction `index/merge.rs`, local open/recovery, the RustFS
whole-object cold cache, snapshot/PIT and the segment checkers.

Legacy v1 STORED remains readable and is validated on its existing path. No new
public query API. Decompression is bounded **before** allocation. Use the fixed
`128`-doc block geometry and do not secretly enlarge it based on compression
results.

## Future adversarial matrix

Empty / one / 127 / 128 / 129 / 255 / 256 docs; key/field/value null and multi
states; very large record, max-value/nesting; missing/non-monotone/overlapping
offsets; zip-bomb/declared-size mismatch; truncated compressed bytes; corruption
in selected and unselected blocks; budget exact/one-over; cache
eviction/reload; old v1 local/RustFS reopen; cancellation; two segments and
compaction; snapshot before/after refresh; remote short download; crash between
segment creation and manifest publication; repeated readers.

**Data-loss or corruption-observability regression is a HARD STOP, not a
throughput waiver.**

## Measured evidence (PR 15I-0, source `48e7d3a`, not a forecast)

STORED is the largest single segment section in the current baseline:

| Documents | STORED bytes | Share of committed index | Whole committed index |
|---:|---:|---:|---:|
| 10,000 | 966,263 | 31.2703 % | 3,090,037 |
| 100,000 | 9,662,513 | 31.2046 % | 30,965,025 |

Segment-level sections at 100K: `Stored` 9,662,513; `Postings` 3,983,573;
`Dictionary` 3,500,207; `Columns` 2,004,364; `DocKeys` 1,100,010;
`VersionRefs` 800,011; `FieldNorms` 300,074; `LiveDocs` 12,511; `Schema` 97;
segment non-section overhead 666. The mutation-state sidecar (9,600,180) is
reported **separately** and is not part of segment bytes.

These are physical sizes only. **No compression ratio is claimed or implied.**
Actual feasible reduction depends on codec, payload entropy, durability and
required metadata, and must be measured by the future PR.

## Open questions / decision required before implementation

1. Block directory footer placement and its interaction with the existing
   container envelope checks.
2. The exact validation-certificate lifetime and its error precedence relative
   to existing budget rejections.
3. Whether the first candidate keeps per-record validation eager and only
   amortises decompression (a strictly safer starting point).
