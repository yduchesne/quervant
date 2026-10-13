# PR 5 — Segment and manifest format decisions (F01–F12)

> **Status: PROPOSED — AWAITING HUMAN APPROVAL. NOT APPROVED. AMENDMENT 01 APPLIED.**
>
> This document proposes a concrete, byte-level durable format for PR 5. It is a
> **recommendation for human decision**, authored by a coding agent as required
> by `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §2. It is **not** an approval,
> a format freeze, or authorization to implement production codec code.
>
> Per `docs/decisions/PR04_PR05_DESIGN_GATE_APPROVAL.md`, F01–F12 are approved
> *in principle* only. A human must approve this document and record the approved
> commit SHA before any production codec is written (plan §2, §8, §11).

## Amendment history

| Amendment | Scope | Baseline | Status |
|---|---|---|---|
| 01 | R5-01–R5-08 (postings seek, addressable columns, integrity/access model, fixed trailer, state vocabulary, partial bounds, limit classes, manifest integrity/lifecycle) | `98762ed` | Applied in this revision; awaiting approval |

## Approval record (to be completed by a human)

| Field | Value |
|---|---|
| Decision | ☐ APPROVED / ☐ APPROVED WITH CHANGES / ☐ REJECTED |
| Approved by | _pending_ |
| Approval date | _pending_ |
| Approved commit SHA of this file | _pending_ |
| Changes / conditions | _pending_ |

Until this table is completed and points at a committed SHA, **STOP before
production codec code**.

## Precedence and constraints

This proposal is subordinate to, and must not weaken:

- `AGENTS.md` (no custom cryptography; no scope leakage; bounded resources).
- `docs/decisions/PR02_CONTRACT_DECISIONS.md` (A01–A25, contract-only).
- `docs/decisions/PR03_STORAGE_CONTRACT_DECISIONS.md` (Directory/ObjectStore seams).
- `docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md` and the approval amendment
  (token model, `AnalyzerFingerprint`, position gap `POSITION_GAP = 100`).
- `PR04_PR05_DESIGN_GATE_APPROVAL.md` (binding F02/F05/F06/F07/F08/F09/F10/F11 constraints).
- `docs/ARCHITECTURE.md`, `docs/ROADMAP_V01.md`, `docs/TESTING.md`.

Integrity uses the vetted RustCrypto `sha2 = 0.11.0` SHA-256 already in the
dependency graph. Content identity reuses PR 3's `ContentDescriptor`
`(length, SHA-256, algorithm version)` (`trawler-objectstore::digest`). **No
custom cryptographic primitive is proposed.** No unsigned or `unsafe` reads are
used (`trawler-core` is `#![forbid(unsafe_code)]`).

## Terminology

- **Segment**: one immutable container file, identified by an existing
  `storage::SegmentId`, described by one existing `storage::SegmentDescriptor`
  (one remote object key + `ContentDescriptor`).
- **Section**: a typed, length-delimited, digest-protected region inside the
  container.
- **Physical doc id**: dense `u64` index `0..doc_count` in the segment's
  post-remap physical order.
- **Logical key**: PR 2 `DocumentKey`, stored byte-exact (A01).
- **Offsets** are absolute byte positions within their stated reference frame,
  little-endian `u64` unless stated otherwise; **lengths** are byte counts.

---

## F01 — Container shape: one file vs typed component files

### Recommendation (R-F01)

**One segment = one immutable container file with typed, section-addressable
components.** `SegmentId` maps 1:1 to the container; the existing
`SegmentDescriptor.object_key` and `ContentDescriptor` describe that one file.

Layout:

```text
+--------------------------------------------------------------+
| Header (fixed 24 bytes, F02)                                 |
+--------------------------------------------------------------+
| Section[kind=SCHEMA]        (contiguous, ascending kind)     |
| Section[kind=TERM_DICTIONARY]                                |
| Section[kind=POSTINGS]                                       |
| Section[kind=DOC_KEYS]                                       |
| Section[kind=VERSION_REFS]                                   |
| Section[kind=LIVE_DOCS]                                      |
| Section[kind=STORED]                                         |
| Section[kind=COLUMNS]                                        |
| Section[kind=TIME_BOUNDS]                                    |
| Section[kind=GEO_BOUNDS]                                     |
| Section[kind=SORTED_REMAP]                                   |
| Section[kind=SEGMENT_META]                                   |
| (optional EXTENSIONS section)                                |
+--------------------------------------------------------------+
| Footer: feature sets + section directory (variable, F02)     |
+--------------------------------------------------------------+
| Trailer (fixed 64 bytes at EOF, F02)                         |
+--------------------------------------------------------------+
```

Sections are **contiguous** (no gaps) starting at `header_len`, in ascending
`section_kind` order; each kind appears at most once in v1. Section bodies are
independently digest-covered (`body_digest`). The `COLUMNS` section is internally
block-addressable (F07).

### Selective access and trust (R5-03, summary; detail in F02.1)

Section addressability permits a reader to locate a section/block. It does **not**
by itself grant authenticated content identity: a per-section digest compared
against the same untrusted footer proves only internal consistency. Full-file
verification against an independently trusted `ContentDescriptor` is the v1 trust
anchor. See F02.1 for the exact full vs selective rules.

### Alternatives

- **(A) Typed component files per segment** (Lucene-ish) referenced by a manifest.
  Pros: selective materialization; smaller units. Cons: requires a multi-object
  `SegmentDescriptor` (today one object); multi-object atomicity/verification;
  PR 13 bootstrap must materialize many objects.
- **(B) One file, opaque whole-segment blob.** Simplest. Cons: blocks selective
  reads and streaming; contradicts F10/PR 14 direction.

### Tradeoffs and compatibility

R-F01 preserves the existing one-object `SegmentDescriptor` seam (PR 3) and the
PR 13 whole-file materialization model while reserving selective section/block
access. It does not commit to FST layout or partial caching. Multi-file remains
representable later under a new major version; no v1 reader promises it.

**Open human choice:** confirm one-file. If multi-file is chosen, F02, F10 and
PR 3's descriptor seam must be re-opened explicitly.

---

## F02 — Envelope, fixed trailer, endianness, integrity, features

### Recommendation (R-F02)

All fixed-width integers are **little-endian**, written/read via explicit LE
helpers. `endian` must be `0x01`; any other value is an unsupported-format error.

#### F02.0 Header (fixed 24 bytes at offset 0)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 8 | `magic` | ASCII `TRWSEG01` (segment) / `TRWMAN01` (manifest) |
| 8 | 2 | `format_major: u16` | `1`; other → fail closed |
| 10 | 2 | `format_minor: u16` | `0` |
| 12 | 1 | `endian: u8` | `0x01` LE; other → fail closed |
| 13 | 1 | `header_len: u8` | `24`; sections start here |
| 14 | 2 | `header_flags: u16` | `0`; unknown set bit → fail closed |
| 16 | 8 | `doc_count: u64` | manifest uses `0` here plus payload metadata |

#### F02.1 Footer location: fixed trailer, no magic scanning (R5-04)

The file ends with a **fixed 64-byte trailer**. `trailer_offset =
file_len - 64` (checked subtraction; `file_len` from `ReadHandle::len()`).
A reader never scans payload bytes for magic.

**Trailer (64 bytes at `trailer_offset`):**

| Offset from trailer | Size | Field |
|---|---|---|
| 0 | 8 | `trailer_magic` = ASCII `TRWSTR01` |
| 8 | 8 | `footer_offset: u64` — absolute offset of footer start |
| 16 | 8 | `footer_len: u64` — exact bytes from `footer_offset` to `trailer_offset` |
| 24 | 4 | `section_count: u32` |
| 28 | 2 | `trailer_version: u16` = `1` |
| 30 | 2 | `trailer_flags: u16` = `0`; unknown bit → fail closed |
| 32 | 32 | `envelope_digest: [u8;32]` — SHA-256 over `[0, trailer_offset)` |

`footer_len` **excludes** the trailer and `envelope_digest`; it is exactly the
byte span between `footer_offset` and `trailer_offset`. Because `envelope_digest`
covers `[0, trailer_offset)`, it covers the header, all section bodies **and the
entire footer**. The trailer's own offset/length/count fields are redundant
cross-checks against the (covered) footer and must agree.

Minimum file length: `MIN_FILE_LEN = 24 (header) + 14 (min footer) + 64
(trailer) = 102` bytes. Files shorter than this fail closed.

#### F02.2 Footer (variable, immediately before the trailer)

| Field | Width |
|---|---|
| `footer_version: u16` = `1` | 2 |
| `section_count: u32` (must equal trailer) | 4 |
| `required_feature_count: u32` | 4 |
| required features: `(feature_id: u16, feature_version: u16)` | 4 each |
| `optional_feature_count: u32` | 4 |
| optional features: `(feature_id: u16, feature_version: u16)` | 4 each |
| directory entries, ascending `section_kind` (below) | 60 each |

**Directory entry (60 bytes):**

| Field | Width |
|---|---|
| `section_kind: u16` | 2 |
| `section_flags: u16` | 2 |
| `aux: u64` (field id for COLUMNS sub-blocks, else `0`) | 8 |
| `body_offset: u64` (absolute, relative to file start) | 8 |
| `body_length: u64` | 8 |
| `body_digest: [u8;32]` = SHA-256 of exact body bytes | 32 |

`body_digest` is a **structural/accidental-corruption** check (see F02.3); it is
not a trust anchor by itself.

#### F02.3 Integrity and access trust model (R5-03)

Two distinct operations are defined and must never be conflated.

**A. Full verification (v1 trust anchor).**

1. Obtain the complete file bytes (PR 13 whole-file materialization / local
   `Directory` read), or stream all bytes.
2. Compute SHA-256 over `[0, trailer_offset)` and compare against an
   **independently trusted expected digest** — a PR 3 `ContentDescriptor` digest
   obtained from `SegmentStore::describe` / a manifest reference, not from the
   file itself.
3. Validate the envelope structure (trailer, footer, section directory,
   contiguity, per-section digests, feature negotiation).
4. Only after (2) and (3) may decoded data be treated as content-authenticated.

Trust origin is the PR 3 `SegmentDescriptor.content` (or a manifest segment
reference). Failure to obtain a trusted descriptor is not a pass; decoded data is
at most structurally checked.

**B. Selective/range access (reserved; not implemented in v1).**

Reading only the fixed trailer + footer + selected sections/blocks:

- Structural validation (offsets, lengths, contiguity, `body_digest`) is
  possible.
- **Content identity is NOT established** by comparing a fetched section to a
  digest stored in the same untrusted footer. A full-file prefix digest cannot
  authenticate an arbitrary subset.
- A selective reader may trust a range **only** if the containing file was
  already fully verified against a trusted descriptor (for example a verified PR 3
  `SegmentCache` entry), or if a future approved authenticated structure (for
  example a Merkle tree with a root committed in a trusted manifest) is added by a
  **separate human decision**. PR 5 does not implement either.
- Range reads are therefore labelled **structurally checked, not independently
  content-authenticated** until one of those conditions holds. No security-
  sensitive assertion may rely on an unverified range.

`ReadHandle::read_at` obtains the trailer with one bounded read of the final 64
bytes and the footer with one bounded read of `[footer_offset, trailer_offset)`.
After full verification, a reader may cache the verified container; PR 3
`SegmentCache` already verifies a `ContentDescriptor` on fill, which satisfies
condition A for cached entries.

**What SHA-256 does and does not do.** SHA-256 detects accidental corruption and,
with a trusted expected digest, detects substitution. Without a trusted
reference, SHA-256 provides no cryptographic authenticity for a maliciously
replaced file.

#### F02.4 Feature/version behavior

- `format_major != 1`: fail closed (`UnsupportedFormatVersion`).
- `format_minor` > supported: reject unless an approved compatibility policy
  allows it (F12). v1 default is conservative rejection.
- Unknown set bit in `header_flags` or `trailer_flags`: fail closed.
- A `required_features` id that is unknown or at an unsupported version: fail
  closed. Unknown `optional_features`: ignored.
- Unknown `section_kind` that is not advertised as optional: fail closed.
- Section bodies must exactly tile `[header_len, footer_offset)`; a gap or overlap
  fails closed. Trailing undeclared bytes are impossible by construction because
  the footer must end exactly at `trailer_offset`.

### Alternatives

- CRC-32C for section digests. Rejected: adds a second integrity notion; SHA-256
  is already a vetted dependency and uniform with PR 3 content digests.
- Backward magic scan for the footer. Rejected (R5-04): ambiguous when magic bytes
  appear in payload; the fixed trailer is deterministic.

---

## F03 — Canonical field identity, descriptor, analyzer/normalizer binding

### Recommendation (R-F03)

- `field_id` is a dense `u32` assigned by **canonically sorting field names by
  raw UTF-8 byte order**. Identical schema sets encode byte-identically regardless
  of declaration order (INV01). Duplicate names are rejected.
- Field descriptor version = `1`.
- Per field body (SCHEMA section, ascending `field_id`):
  `field_id u32`; `name_len u16` + UTF-8 name; `type_tag u8`; `cardinality u8`
  (`0` Single, `1` Multi); `option_flags u8` (`bit0` indexed, `bit1` stored,
  `bit2` columnar); analyzer binding; normalizer binding; `reserved u16 = 0`.
- Binding = `present u8`; if present: `id_len u16`, id bytes; `version_len u16`,
  version bytes; `fingerprint [u8;32]` (PR 4 `AnalyzerFingerprint`).
- `primary_timestamp`: `present u8`; if present `field_id u32`.
- SCHEMA section begins with `descriptor_version u16 = 1`.

`FieldType` tags (unknown tag = fail closed):

| tag | type | tag | type |
|---|---|---|---|
| 1 | Text | 7 | Timestamp |
| 2 | Keyword | 8 | Json |
| 3 | Bool | 9 | GeoPoint |
| 4 | I64 | 10 | IpAddress |
| 5 | U64 | 11 | IpNetwork |
| 6 | F64 | | |

Cross-validated rules (must equal PR 2 `FieldDefinition::validate`): columnar
`Text`/`Json` rejected; analyzer only on `Text`; normalizer only on `Keyword`;
primary timestamp must be Timestamp+Single+indexed.

### Analyzer/normalizer resolution

The codec stores id + version + 32-byte canonical fingerprint. A consumer must
call PR 4 `AnalyzerRegistry::resolve_fingerprint(id, version, fingerprint)`; a
mismatch is a typed failure, never a silent reinterpretation (INV06). PR 5 does
not reimplement or re-derive the fingerprint.

### Compatibility implications

New types/options are additive enum/flag values; unknown values fail closed.
Changing the fingerprint encoding is a PR 4 concern and a major-version event.

---

## F04 — Dense doc ids, logical keys, version/live references, tombstones, merges

### Recommendation (R-F04)

- Dense physical doc ids `0..doc_count` from the header.
- **DOC_KEYS** section: for each physical doc id ascending, `key_len u16` +
  byte-exact `DocumentKey` (≤ 1024 bytes, A01). A sorted key→doc-id index is a
  reserved optional capability (`F_DOC_KEY_INDEX`), not implemented in v1.
- **VERSION_REFS**: `present u8`; if present, one `revision u64` per physical doc
  id. PR 5 stores the reference only; revision allocation is PR 6. `0` = unassigned.
- **LIVE_DOCS**: `present u8`; if present, a bitmap of `ceil(doc_count/8)` bytes,
  bit `i` = doc `i` live. Absent means all live. PR 5 encodes/validates the
  reference; delete/update execution is PR 9.
- **TOMBSTONES / merge references**: reserved optional sections, not emitted in
  v1. Merge execution is PR 9.

### Merge semantics (references only)

A future merge reads (key, revision, live) and produces a new segment with a new
dense enumeration. PR 5 defines only stored references and the remap mechanism
(F09); it executes no merge.

---

## F05 — Term dictionary, UTF-8 order, postings, positional semantics and seek

### Recommendation (R-F05)

**Ordering:** terms are unique and sorted by **raw UTF-8 byte ascending order**
within their field. No normalization/collation at codec level.

**TERM_DICTIONARY section:** `dictionary_version u16 = 1`; `field_count u32`;
for each indexed field ascending `field_id`: `field_id u32`, `term_count u64`,
then entries:

| Field | Width | Notes |
|---|---|---|
| `term_len` | `u16` | `1..=4096` (PR 4 `HARD_MAX_TERM_BYTES`) |
| term bytes | `term_len` | UTF-8, unique within field |
| `doc_freq` | `u64` | `> 0`; must equal posting block `doc_count` |
| `postings_offset` | `u64` | relative to POSTINGS body start |
| `postings_length` | `u64` | `> 0`; exact block extent |

Duplicate terms in one field are rejected. Entries are sorted, so a bounded
reader may binary-search the dictionary.

**POSTINGS section:** concatenated blocks. Block layout:

| Field | Width | Notes |
|---|---|---|
| `occurrence_kind` | `u8` | `0` DOC_ONLY, `1` POSITIONAL |
| `doc_count` | `u64` | `> 0`; == dictionary `doc_freq` |
| `freq_total` | `u64` | sum of per-doc frequencies; `>= doc_count` |
| doc ids | varints | first absolute, then **strictly positive** deltas; strictly increasing; `< doc_count` |
| per doc `freq` | `u64` varint | `>= 1` |
| positional records | see below | only when `occurrence_kind = 1` |

For each positional record, in **strictly increasing position order per
`(term, doc)`**:

| Field | Width | Notes |
|---|---|---|
| `position` | `u64` varint | first record absolute; later records store a **positive delta** from the previous record |
| `position_length` | `u64` varint | `>= 1` |
| `value_index` | `u64` varint | **non-decreasing** across the doc's records |
| `start_offset` | `u64` varint | original-source byte offset within its value |
| `end_offset` | `u64` varint | `>= start_offset` |

A block consumes **exactly** `postings_length` bytes; truncation or trailing
bytes are rejected. `doc_freq == doc_count`, `freq_total == Σ freq`, and all byte
extents are cross-validated; zero-length blocks and out-of-bounds offsets are
rejected (INV03, INV04). Varints are unsigned LEB128, **minimal-length
canonical**; overlong and `> u64::MAX` encodings are rejected before use.

### Position semantics validated against PR 4 (R5-01)

PR 4 fixes positions as **strictly increasing per retained token**:

- `Token::new` rejects `position_increment == 0` and `position_length == 0`
  (`crates/trawler-core/src/analysis/token.rs`).
- The analyzer computes `increment = position.checked_sub(previous).filter(|i| *i > 0)`,
  so a retained token always advances position
  (`crates/trawler-core/src/analysis/analyzer.rs`).
- `POSITION_GAP = 100` separates distinct source values; offsets are per source
  value and `value_index` identifies that value.

Therefore **equal positions for the same term in the same document are
impossible**, and strict positive position deltas are correct. `position` is the
authoritative absolute coordinate; PR 4's `position_increment` is a
stream-relative quantity and is **not** stored verbatim in per-term postings
(storing it per term would be meaningless across terms). An execution layer that
needs the stream increment reconstructs it from absolute positions. `position`
and `position_increment` are explicitly **not** conflated. Source offsets are
never inferred from normalized term length; they are stored as produced by the
analyzer, and UTF-8 boundary validity against the source remains a higher-layer
check because the codec does not keep the source value in the postings block.

### Bounded reader/seek contract (R5-01)

The postings reader exposes a binding **behavioral** contract (names
illustrative):

- `next()` returns the next posting in ascending doc-id order, or EOF.
- `advance(target)` returns the first posting with `doc_id >= target`, or EOF;
  it never moves backward; `target <= current_doc_id` returns the current posting;
  calling after EOF stays EOF.
- **Without skip metadata, `advance` scans sequentially from the current cursor.**
  It is **not** guaranteed sublinear and makes no random-access promise. Work is
  charged per decoded posting.
- Decoding is lazy and bounded: maximum bytes per read, maximum postings decoded
  per batch, and cancellation checkpoints. Whole-term materialization is not a
  prerequisite for `advance`.
- An optional `SKIP_INDEX` section is **reserved** under feature `F_SKIP_BLOCKS`
  and is **not emitted in v1**; adding it later must not change v1 posting
  semantics. The absence of skips in v1 is therefore an explicit **performance
  tradeoff**, not an oversight.

### Alternatives

- Front-coded/block-compressed dictionary: deferred optimization.
- Fixed-width `u64` postings instead of varints: simpler decoder, larger format;
  the conservative fallback if the human prefers to minimize decoder risk.
- Absolute positions instead of deltas: larger, no benefit.

---

## F06 — Stored source documents and logical field states

### Recommendation (R-F06)

**Semantic preservation of the validated typed document, not byte-for-byte
request bytes.** PR 2 has no raw-JSON source capture; `Document` is already a
typed structure. PR 5 stores it losslessly with respect to the contract.

**Shared logical state vocabulary (F06 and F07 must agree exactly):**

| Tag | State | PR 2 `FieldValues` |
|---|---|---|
| `0x00` | `ABSENT` | `Absent` |
| `0x01` | `EXPLICIT_NULL` | `ExplicitNull` |
| `0x02` | `EMPTY_MULTI` | `Empty` |
| `0x03` | `SINGLE` | `Single(_)` |
| `0x04` | `MULTI` | `Multi(_)` with count `>= 1` |

Rules: `MULTI` requires count `>= 1`; count `0` is `EMPTY_MULTI`. `SINGLE` and
`MULTI(count = 1)` are **distinct** PR 2 variants and therefore have distinct
encodings; they are not two encodings of one state. `ABSENT` is never inferred
from arbitrary zero bytes.

**STORED section:** `stored_version u16 = 1`; `stored_count u64` (== `doc_count`).
Per physical doc id ascending:

- `key_len u16` + key bytes.
- **presence bitmap** of `ceil(schema_field_count/8)` bytes over `field_id`;
  bit set ⇔ field state is one of `EXPLICIT_NULL`/`EMPTY_MULTI`/`SINGLE`/`MULTI`
  (i.e. not `ABSENT`).
- For each set bit, ascending `field_id`: `field_id u32`; `state u8`
  (`0x01..=0x04`); then `SINGLE` = one value; `MULTI` = `count u64 varint`
  (`>= 1`) + values; `EMPTY_MULTI`/`EXPLICIT_NULL` = no value bytes.

The bitmap participates in validation: every set bit has exactly one entry and
every entry's bit is set; a schema field with a clear bit is exactly `ABSENT`.

JSON value encoding (recursive, depth-bounded): `0x00 Null`, `0x01 Bool`+1,
`0x02 I64`+8, `0x03 U64`+8, `0x04 F64`+8 (finite only), `0x05 String`+`len
varint`+UTF-8, `0x06 Array`+`count varint`+values, `0x07 Object`+`count
varint`+pairs. Array and object-member order are preserved exactly. Explicit JSON
null (`JsonValue::Null`) is distinct from field `EXPLICIT_NULL`.

**Limits before allocation:** A20 `Fields`, `ArrayElements`, `JsonDepth`, plus
F11. Counts/lengths are validated against remaining section bytes before
allocation.

### Alternatives

- Byte-for-byte original request JSON: requires a new PR 2 contract; **out of
  scope** and a STOP if required.
- Omit `ABSENT` entirely without a presence bitmap: rejected (R5-05) as ambiguous.

---

## F07 — Addressable typed columns and group keys

### Recommendation (R-F07)

**COLUMNS section** contains a column directory then contiguous, independently
digest-covered column blocks. Each block covers a **uniform** physical doc range
of `block_docs` docs (default `1,024`; an operational policy, F11), except the
last block. This yields bounded doc access.

**Column directory** (at section start): `column_count u32`; per columnar field
ascending `field_id`: `field_id u32`, `type_tag u8`, `layout_kind u8`
(`0x01` FIXED_SINGLE, `0x02` VARIABLE_MULTI), `doc_count u64`, `block_count u32`,
`state_bitmap_len u64` (reserved; `0` in v1), `block_dir_offset u64`,
`block_dir_len u64`.

**Block directory entry** (per block, ascending): `first_doc_id u64` (must equal
`block_index * block_docs`), `doc_count u32`, `state_offset u64`,
`values_offset u64`, `values_length u64`. Offsets are relative to the column's
block area.

`doc N` lookup: `block_index = N / block_docs` is **O(1) directory arithmetic**;
the reader touches one directory entry and **at most its containing block**. It
never scans preceding blocks. Byte/entry work is bounded by `block_docs` and F11
caps. This is a bounded local-access guarantee, **not** a promise of O(1) remote
I/O independent of ObjectStore latency.

#### Layout kinds

- `FIXED_SINGLE` (only `Cardinality::Single`; only fixed-width types Bool, I64,
  U64, F64, Timestamp, GeoPoint): per block, a **state array** of `doc_count`
  bytes (F06 tags; valid states `ABSENT`/`EXPLICIT_NULL`/`SINGLE`), followed by a
  **fixed slot array** of `doc_count × slot_width` bytes. `slot_width`: Bool 1,
  I64/U64/F64/Timestamp 8, GeoPoint 16. The slot exists for every doc; bytes are
  meaningful only when the state is `SINGLE` (otherwise arbitrary and ignored, not
  interpreted as a value).
- `VARIABLE_MULTI` (Keyword, IpAddress, IpNetwork, and any `Cardinality::Multi`):
  per block, a **state array** of `doc_count` bytes (all five tags), followed by
  an **offset table** of `(doc_count + 1) × u64` entries (relative to the value
  area), followed by the value area. `offset[i]..offset[i+1]` delimits doc `i`.
  Offsets must be non-decreasing and `offset[doc_count] == value_area_len`.
  Doc `i`'s bytes are: `SINGLE` = one value; `MULTI` = `count varint` (`>= 1`) +
  values; `EMPTY_MULTI`/`EXPLICIT_NULL`/`ABSENT` = zero bytes.

Value encodings (LE unless noted):

| Type | Encoding |
|---|---|
| Bool | `u8` 0/1 |
| I64 | `i64` two's complement, 8 bytes |
| U64 | `u64`, 8 bytes |
| F64 | IEEE-754 `f64`, 8 bytes, **finite only** |
| Timestamp | `i64` microseconds UTC (A13) |
| Keyword | `u16` length + UTF-8 bytes |
| GeoPoint | `lon f64`, `lat f64` (16 bytes, bit-exact; `-0.0` preserved) |
| IpAddress | `family u8` (`0` IPv4, `1` IPv6) + 4/16 address bytes |
| IpNetwork | `family u8` + 4/16 address bytes + `prefix u8` |

Rules: IPv4/IPv6 are family-tagged, never text-compared; IPv4-mapped IPv6 stays
IPv6 unless an approved schema-level `normalize_ipv4_mapped` opt-in exists (A07),
and that flag must become part of the field-descriptor version. CIDR prefix
ranges are validated (0–32 / 0–128); host bits were rejected by PR 2
`IpNetwork`. Geo rejects non-finite/out-of-range coordinates. `Min`/`Max`
multi-value selection remains a query-time concern (A15); all values are stored.
Multi-valued records never physically cross a block boundary; an oversized single
record is a typed encode error.

Deterministic ordering: columns/blocks are ordered by ascending `field_id` and
ascending `first_doc_id`. F09 remapping assigns physical doc ids **before**
columns are written, so every column is already in physical order.

**Group keys:** a typed, length-delimited tuple used by PR 10. `tuple_len varint`;
per component: `type_tag u8`; then a state tag `0x00 MISSING`, `0x01 NULL`,
`0x02 VALUE` + value bytes (family-tagged as above). `EMPTY_MULTI` is a
**documented non-groupable** condition: it expands to zero groups (A16/H08), so it
produces no group key. Missing and null are distinct groups. Distinct types,
families and lengths cannot collide (INV10). Canonical ordering for deterministic
group output is defined by a **decoded type-aware comparator** (type tag, then
value semantics; missing before null before values), **not** raw byte order.

### Adversarial acceptance

A test must instrument bytes read and decoded entries to prove doc-N access does
not scan preceding blocks (P5-A06); malformed/descending/overflow offsets are
rejected (P5-A07).

### Alternatives

- Column-major value storage: measurable optimization; deferred.
- Byte-per-doc state array vs 2-bit packing: v1 uses one byte per doc for exact
  simplicity; packing is a later compatible optimization.

---

## F08 — Conservative bounds with partial presence

### Recommendation (R-F08)

Bounds are used only to **prune**; metadata that cannot prove a predicate
unsatisfiable disables pruning. Bounds are over **actual valid values**.

**Presence metadata (per bounds object):**

| Field | Width | Meaning |
|---|---|---|
| `presence_state` | `u8` | `0` UNKNOWN, `1` NO_VALUES, `2` SOME_VALUES, `3` ALL_APPLICABLE_VALUES |
| `live_count` | `u64` | number of live docs |
| `present_count` | `u64` | live docs with at least one applicable value |

`NO_VALUES` = `present_count == 0`; `ALL` = `present_count == live_count`;
`SOME` = `0 < present_count < live_count`; `UNKNOWN` = presence not tracked.
`live_count == 0` is allowed and means prune everything.

**TIME_BOUNDS:** `field_id u32` (primary timestamp); `state u8` (`0` UNKNOWN,
`1` Known); presence metadata; if Known (and `present_count > 0`):
`min_micros i64`, `max_micros i64`, `ordered u8`. Known requires the primary
timestamp field to be present, Single, non-null on every doc counted by
`present_count`. A Known range with `min > max` is corruption. Per-block time
bounds are reserved (`F_BLOCK_TIME_BOUNDS`, not v1).

**GEO_BOUNDS:** per GeoPoint field; `field_id u32`; `state u8`; presence
metadata; if Known: `west f64`, `south f64`, `east f64`, `north f64`,
`crosses_antimeridian u8`. The envelope includes **all** values of **all**
present docs when the field is multi-valued. A crossing envelope uses `west >
east` for `[west, 180] ∪ [-180, east]` (A14).

**Pruning applicability truth table** (conservative; metadata must prove the
**whole** predicate unsatisfiable):

| Predicate shape | Prune only when |
|---|---|
| positive time range / geo bbox/radius | `presence_state != UNKNOWN` and (`present_count == 0` or all present values outside the predicate) |
| `IS NULL` / `MISSING` (value-less) | `presence_state == ALL_APPLICABLE_VALUES` (every live doc has a value) |
| `EXISTS(value)` / `IS NOT NULL` | `present_count == 0` |
| negation of a positive range/geo predicate | `presence_state == ALL_APPLICABLE_VALUES` and all present values inside the positive predicate |
| disjunction (`OR`) | **every** disjunct is prunable |
| conjunction (`AND`) | **any** conjunct is prunable |
| `live_count == 0` | always prune |
| `presence_state == UNKNOWN` or unlisted predicate | never prune |

Rationale: missing/absent/null values do not satisfy a positive time/geo
predicate, so positive pruning is safe under `SOME`. A negated predicate may be
satisfied by a missing value, so it needs `ALL` plus all-present-inside. Because
`ABSENT` and `EXPLICIT_NULL` are not separately counted in presence metadata,
`IS NULL` versus `MISSING` are only pruned together via `ALL`; that is
deliberately conservative. Predicate semantics are owned by PR 2/query contracts;
PR 5 only stores metadata. Any predicate not listed here must not prune.

### Adversarial acceptance

P5-A13 (partial presence positive-range) and P5-A14 (missing/null, NOT, OR) test
both positive and negative query shapes, not only envelope round-trip.

---

## F09 — Sorted doc-id permutation, tie-breaker, total remapping

### Recommendation (R-F09)

Physical order when a sorted layout is requested: **primary timestamp ascending,
then `DocumentKey` raw UTF-8 byte ascending** (A15 final tie-break). Absent/null
timestamps use the explicit missing-value policy and are disambiguated by key, so
the total order is deterministic.

**SORTED_REMAP** section: `state u8` (`0` identity, `1` present); if present:
`physical_to_original`: `doc_count × u64`; `original_to_physical`:
`doc_count × u64`. Both arrays must be valid permutations of `0..doc_count`
(bijective, no duplicates, no out-of-range) or the segment is corrupt.

The remap is applied to **every** doc-addressed structure: DOC_KEYS,
VERSION_REFS, LIVE_DOCS, STORED, all column blocks, postings doc-id sequences,
and bounds computed over physical order. A single encoder entry point performs
the permutation (INV08); cross-structure agreement is asserted by tests
P5-U44..U50, P5-A20 and P5-P04.

---

## F10 — Manifest schema, integrity and lifecycle (no publication)

### Recommendation (R-F10)

The manifest is an immutable container with the same header/footer/trailer
discipline as a segment (F02), magic `TRWMAN01`, `doc_count = 0`.

**MANIFEST payload section:**

```text
manifest_version u16 = 1
schema: <F03 encoding>
segment_count u32
  per segment, ascending SegmentId UTF-8:
    segment_id_len u16 + bytes            # existing storage::SegmentId grammar
    object_key_len u16 + bytes            # existing ObjectKey grammar
    content_digest_algorithm u8           # 0 = sha256-v1 (PR 3 DigestAlgorithm)
    content_length u64                    # PR 3 ContentDescriptor length
    content_digest [u8;32]                # PR 3 ContentDescriptor digest
    time_bounds: <F08 TIME_BOUNDS encoding>
    required_features / optional_features
required_features / optional_features
```

### Manifest integrity roles (R5-08)

Three digest roles are distinct and named:

1. **Manifest envelope digest** — the F02 `envelope_digest` in the manifest
   trailer, covering the manifest bytes `[0, trailer_offset)`. It is **not**
   repeated inside the payload; doing so is prohibited.
2. **Segment content descriptor digest** — each reference's
   `content_length`+`content_digest`+`content_digest_algorithm`, identifying the
   referenced segment's bytes exactly as PR 3 `ContentDescriptor`. This is the
   trusted expected digest used by full verification (F02.1).
3. **Future PR 6 lifecycle metadata** — not part of v1 (see below).

The manifest's own expected digest must come from an independently trusted
source (for example the index `CURRENT`/manifest reference in PR 6). Comparing a
manifest's `envelope_digest` to itself authenticates nothing.

### Lifecycle fields (R5-08; human choice)

**Recommended:** **omit** `generation`, `parent_generation`, `writer_epoch`
entirely from the v1 payload and reserve future feature ids/versions for them.
PR 5 defines no generation allocation, CURRENT pointer, atomic publication,
fencing, or recovery.

**Alternative (for human decision):** retain fixed-width fields with mandatory
zero/absent values and explicitly no publication meaning. This risks PR 6
reinterpreting them; the recommended omission avoids freezing PR 6 semantics.

### Validation (exhaustive)

Reject duplicate segment ids or object keys; missing/zero/oversized content
lengths; digest algorithm out of range; duplicate schema field names; unknown
required features; malformed reference keys; and any offset/length overflow.
Validate the envelope exactly as F02.

PR 5 may serialize/deserialize/validate a manifest and round-trip it through the
real `Directory`, but must never treat any file as a published generation.

---

## F11 — Wire representability, safety budgets and operational policy

Limits fall into three distinct classes (R5-07). Only class 1 is wire format.

### Class 1 — Wire representability (immutable in v1)

| Quantity | Wire width | Max representable |
|---|---|---|
| `field_id` | `u32` | `2^32 - 1` |
| `doc_count` / physical doc id | `u64` | `2^64 - 1` |
| section body count | derived from `section_count u32` | `2^32 - 1` |
| `term_len` | `u16` | `65,535` (further capped at 4,096, PR 4) |
| feature id | `u16` | `65,535` |
| offsets/lengths | `u64` | `2^64 - 1` |
| digest | 32 bytes | SHA-256 |

All arithmetic uses checked `u64`/`u32` operations and checked `u64 -> usize`
conversions; representability overflow and out-of-range values are typed errors.

### Class 2 — Reader/writer safety budgets (enforced regardless of file size)

Independent of any configured segment size; these protect the decoder:

| Budget | Proposed default | Enforced where |
|---|---|---|
| max single allocation | 64 MiB | every allocation preflight |
| max section decode bytes | 256 MiB | per section/block decode |
| max decoded entries per operation | 8,000,000 | postings/column/dictionary batches |
| max JSON/recursion depth | A20 `JsonDepth` | stored/column JSON |
| max read bytes per `read_at` | 1 MiB | trailer/footer/section reads |
| max footer bytes | 1 MiB | footer parse |
| max sections | 4,096 | footer parse |
| max features | 1,024 | footer parse |
| cancellation cadence | every 1,024 decoded entries | long decodes |

Every decoder preflights counts/lengths against remaining declared bytes and
these budgets before allocating.

### Class 3 — Operational policy (configurable, not a wire restriction)

| Policy | Default | Notes |
|---|---|---|
| preferred segment size (encoder target) | 256 MiB | guidance, not a reader rejection |
| accepted segment size (reader ceiling) | configurable; default 1 GiB | readers may accept larger compliant files under a different policy |
| absolute compile-time parser guard | checked against `usize`/allocation budget | prevents overflow/OOM, not a format limit |
| `block_docs` (column) | 1,024 | encoder layout policy |
| preferred column block bytes | 1 MiB | encoder target |
| docs per segment (target) | application policy | PR 6 |
| cache materialization target | PR 3/PR 13 | not PR 5 |

A 256 MiB figure is therefore a **preferred operational target**, not a
permanent format ceiling. Readers accept any structurally valid file within their
configured `accepted segment size` and class-2 budgets.

### Adversarial acceptance

P5-A16 (wire max vs operational target, larger compatible file) and P5-A17
(hostile count, 32-bit conversion, work/alloc budgets).

---

## F12 — Compatibility, capabilities, golden fixtures, evolution

### Recommendation (R-F12)

- **Major**: incompatible layout/semantics. A v1 reader fails closed on any
  unknown major. No cross-major compatibility in v0.1.
- **Minor**: additive, backward-compatible only when every difference is covered
  by known optional features. Until an explicit compatibility policy is approved,
  v1 readers **reject unknown minor versions** (conservative; relaxable later).
- **Required vs optional features**: unknown required → fail closed; unknown
  optional → ignore. On-disk numeric feature ids map to `contract::Capability`
  names for runtime negotiation.
- **Integrity**: envelope and per-section digests detect accidental corruption;
  content authentication requires an independently trusted `ContentDescriptor`
  (F02.1). Selective reads are not authenticated by an untrusted footer.
- **Golden fixtures**: committed bytes under
  `crates/trawler-core/tests/fixtures/segment/` with an **independently authored**
  expected-content table (document key, field, state, term, position, offset,
  typed value, bounds, remap). Golden tests decode committed bytes; self
  round-trip is additionally required but is not a substitute. Regeneration
  instructions record the exact inputs and deterministic seeds; updates require
  an explicit, reviewed format decision.
- **Evolution**: new capabilities add optional sections/features; existing v1
  section kinds, state tags and value tags keep their meaning. Changing a v1
  meaning is a major-version change.

---

## Summary of decisions requiring explicit human approval

| ID | Proposed recommendation | Open point |
|---|---|---|
| F01 | One sectioned container file per segment | Confirm vs multi-file |
| F02 | `TRWSEG01`, LE, fixed 64-byte trailer, SHA-256 envelope digest, required/optional features, explicit full-vs-selective trust model | Confirm trust model + SHA-256 |
| F03 | Canonical name-sorted `field_id`; PR 4 fingerprint stored | — |
| F04 | Dense physical ids; byte-exact keys; revision/live refs only | — |
| F05 | Per-field UTF-8 dictionary; varint delta postings; strict positional semantics; sequential `advance` (no v1 skips) | Confirm varint vs fixed-width |
| F06 | Shared five-state vocabulary; presence-bitmap stored source; semantic preservation | Confirm semantic (not byte-for-byte) |
| F07 | O(1)-directory block-addressable columns; fixed/variable layouts; family-tagged IP; tagged group keys | Confirm block layout |
| F08 | Presence-aware conservative bounds + pruning applicability table | Confirm applicability rules |
| F09 | Timestamp then key tie-break; stored bidirectional permutation | — |
| F10 | Manifest codec valid; three distinct digest roles; lifecycle fields omitted (or reserved-zero) | Choose omit vs reserved-zero |
| F11 | Wire vs safety vs operational limit classes; 256 MiB is policy not format | Confirm defaults |
| F12 | Major fail-closed; conservative minor rejection; committed goldens | Confirm minor policy |

## Explicit STOP statement

No production codec will be implemented until:

1. this document is marked **APPROVED / APPROVED WITH CHANGES** by a human,
2. the approved commit SHA is recorded in the table above,
3. the invariant→test traceability in
   `docs/pr-artifacts/pr-5/correctness-matrix.md` (including P5-A01–A20) is
   accepted, and
4. any requested changes are folded back into this document.
