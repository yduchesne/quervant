# PR 5 — Segment and manifest format decisions (F01–F12)

> **Status: PROPOSED — AWAITING HUMAN APPROVAL. NOT APPROVED.**
>
> This document proposes a concrete, byte-level durable format for PR 5. It is a
> **recommendation for human decision**, authored by a coding agent as required
> by `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §2. It is **not** an approval,
> a format freeze, or authorization to implement production codec code.
>
> Per `docs/decisions/PR04_PR05_DESIGN_GATE_APPROVAL.md`, F01–F12 are approved
> *in principle* only. The unresolved binary-layout details are listed here as
> explicit choices. A human must approve this document and record the approved
> commit SHA before any production codec is written (plan §2, §8, §11).

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
dependency graph. **No custom cryptographic primitive is proposed.**

## Terminology

- **Segment**: one immutable container file, identified by an existing
  `storage::SegmentId`, described by one existing `storage::SegmentDescriptor`
  (one remote object key + `ContentDescriptor`).
- **Section**: a typed, length-delimited, digest-protected region inside the
  container.
- **Physical doc id**: dense `u32`/`u64` index `0..doc_count` in the segment's
  post-remap physical order.
- **Logical key**: PR 2 `DocumentKey`, stored byte-exact (A01).

---

## F01 — Container shape: one file vs typed component files

### Recommendation (R-F01)

**One segment = one immutable container file with typed, section-addressable
components.** `SegmentId` maps 1:1 to the container; the existing
`SegmentDescriptor.object_key` and `ContentDescriptor` describe that one file.

Layout:

```text
+--------------------------------------------------------------+
| Header (fixed 24 bytes, see F02)                             |
+--------------------------------------------------------------+
| Section[kind=SCHEMA]        (canonical order by section kind)|
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
| Footer: section directory + required/optional feature sets + |
|         content digest (see F02)                             |
+--------------------------------------------------------------+
```

Sections appear in ascending `section_kind` order; each kind appears at most
once in v1. The `COLUMNS` section contains a per-`field_id` sub-directory and
contiguous column blocks so a future reader can seek to one field's bytes.

### Alternatives

- **(A) Typed component files per segment** (Lucene-ish `.tim`/`.doc`/`.pos`/…)
  referenced by a manifest. Pros: selective materialization; smaller units;
  independent rewrite. Cons: requires a **multi-object** `SegmentDescriptor`
  (today it is one object); multi-object atomicity/verification is more complex;
  PR 13 cold bootstrap must materialize many objects.
- **(B) One file, opaque whole-segment blob.** Simplest. Cons: blocks selective
  reads and future streaming; violates F10 direction.

### Tradeoffs and compatibility

R-F01 preserves the existing one-object `SegmentDescriptor` seam (PR 3) and the
PR 13 whole-file materialization model while keeping sections seekable via
`ReadHandle::read_at`. It deliberately does **not** commit to FST/block layout or
partial caching. Multi-file remains representable later by introducing a new
`SegmentDescriptor`/manifest variant under a new major version; no current
reader promises it.

**Open human choice:** confirm one-file. If multi-file is chosen, F02, F10 and
PR 3's descriptor seam must be re-opened explicitly.

---

## F02 — Header, version, endianness, boundaries, footer, integrity, features

### Recommendation (R-F02)

All fixed-width integers are **little-endian**. Encoding/decoding goes through
explicit LE helpers; no `transmute`/`unsafe` (`trawler-core` is
`#![forbid(unsafe_code)]`).

**Header (24 bytes):**

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | `magic` = ASCII `TRWSEG01` |
| 8 | 2 | `format_major: u16` = `1` |
| 10 | 2 | `format_minor: u16` = `0` |
| 12 | 1 | `endian: u8` = `0x01` (LE); any other value fails |
| 13 | 1 | `header_len: u8` = `24` (additive growth) |
| 14 | 2 | `header_flags: u16` = `0` reserved; unknown set bits fail |
| 16 | 8 | `doc_count: u64` |

**Footer (near end of file, located by backward scan):**

```text
section_directory:
    section_count: u32
    repeat section_count times, ascending kind:
        section_kind: u16
        section_flags: u16
        aux: u64              # field_id for COLUMNS sub-blocks, else 0
        body_offset: u64
        body_length: u64
        body_digest: [u8;32]  # SHA-256 of the exact body bytes
required_feature_count: u32
    repeat: feature_id: u16, feature_version: u16
optional_feature_count: u32
    repeat: feature_id: u16, feature_version: u16
footer_magic: [8] = ASCII "TRWSEGFT"
footer_len: u32               # bytes from section_directory start to EOF
content_digest: [u8;32]       # SHA-256 over bytes [0, digest_offset)
```

`content_digest` is the final 32 bytes of the file and covers everything before
it, including the directory, feature sets and footer magic. A reader locates the
footer by reading a bounded tail window and finding `footer_magic`; the footer is
small (bounded by `MAX_SECTION_COUNT` and `MAX_FEATURE_COUNT`).

### Unknown required/optional behavior

- Unknown set bit in `header_flags`: fail closed.
- A `feature_id` present in `required_features` with an unknown id or an
  unsupported version: fail closed (`UnsupportedFeature`).
- Unknown `optional_features`: ignored.
- Unknown `section_kind`: if listed in required features → fail; if optional →
  skip; an unlisted unknown section kind fails closed.
- `format_major != 1`: fail closed (`UnsupportedFormatVersion`).
- `format_minor` greater than supported: reject **unless** every difference is
  covered by known optional features; v1 recommends rejecting any minor
  mismatch until an explicit compatibility policy is approved (F12).

### Alternatives

- CRC-32C instead of SHA-256 for per-section digests. Rejected: SHA-256 is
  already a vetted dependency, collision-resistant, and uniform with PR 3
  content digests; CRC is cheaper but weaker and adds a second integrity notion.
- Digest over the whole file including a zeroed digest field. Rejected: more
  error-prone than "digest is last and covers the prefix".
- Big-endian. Rejected: no benefit; LE matches dominant target platforms.

### Compatibility implications

Magic + major/minor + explicit feature negotiation give fail-closed behavior for
unknown required capabilities and a forward path for additive optional sections.
No cross-major compatibility is promised by this proposal (F12).

---

## F03 — Canonical field identity, descriptor, analyzer/normalizer binding

### Recommendation (R-F03)

- `field_id` is a dense `u32` assigned by **canonically sorting field names by
  raw UTF-8 byte order**. Identical schema sets therefore encode byte-identically
  regardless of declaration order (INV01). Duplicate names are rejected.
- Field descriptor version = `1`.
- Per field body (in SCHEMA section, by ascending `field_id`):
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

Cross-validated rules (must equal PR 2 `FieldDefinition::validate`):
columnar `Text`/`Json` rejected; analyzer only on `Text`; normalizer only on
`Keyword`; primary timestamp must be Timestamp+Single+indexed.

### Analyzer/normalizer resolution

The codec stores id + version + 32-byte canonical fingerprint. A consumer must
call PR 4 `AnalyzerRegistry::resolve_fingerprint(id, version, fingerprint)`; a
mismatch is a typed failure, never a silent reinterpretation (INV06). PR 5 does
not reimplement or re-derive the fingerprint.

### Alternatives

- Field name as primary key everywhere (no numeric id). Simpler but bloats every
  per-document/postings reference. Rejected.
- Declaration-order field ids. Rejected: breaks byte determinism (INV01).
- Store full analyzer config instead of fingerprint. Rejected: duplicates PR 4,
  creates a second source of truth.

### Compatibility implications

New types/options are additive enum/flag values; unknown values fail closed.
Changing the fingerprint encoding is a PR 4 concern and a major-version event.

---

## F04 — Dense doc ids, logical keys, version/live references, tombstones, merges

### Recommendation (R-F04)

- Dense physical doc ids `0..doc_count` (`doc_count` from header).
- **DOC_KEYS** section: for each physical doc id ascending,
  `key_len u16` + byte-exact `DocumentKey` (max 1024 bytes, A01). Keys are not
  required to be sorted; a sorted key→doc-id index is a reserved optional
  capability (`F_DOC_KEY_INDEX`, not implemented in v1).
- **VERSION_REFS** section: `present u8`; if present, one `revision u64` per
  physical doc id. PR 5 stores the reference value only; revision allocation is
  PR 6. `revision = 0` means "unassigned".
- **LIVE_DOCS** section: `present u8`; if present, a bitmap of
  `ceil(doc_count/8)` bytes, bit `i` = doc `i` live. Absent means all live.
  PR 5 encodes/validates the reference; delete/update execution is PR 9.
- **TOMBSTONES**: reserved optional section kind, not emitted in v1. Merge-ready
  references (segment id + doc id + revision) are reserved as an optional
  extension; merge execution is PR 9.

### Merge semantics (references only)

A future merge reads (key, revision, live) and produces a new segment with a new
dense enumeration. PR 5 defines only the stored references and the remap
mechanism (F09); it executes no merge.

### Compatibility implications

Adding tombstone/merge sections is additive under new optional features. Changing
doc-id semantics is a major-version change.

---

## F05 — Term dictionary, UTF-8 order, postings, positions, offsets, skips

### Recommendation (R-F05)

**Ordering:** terms are unique and sorted by **raw UTF-8 byte ascending order**
within their field. No normalization or collation is applied at codec level; the
analyzer already produced the indexed term bytes (PR 4).

**TERM_DICTIONARY section:** `dictionary_version u16 = 1`;
`field_count u32`; for each indexed field by ascending `field_id`:
`field_id u32`, `term_count u64`, then `term_count` entries:
`term_len u16` (≤ 4096, PR 4 `HARD_MAX_TERM_BYTES`) + term bytes;
`doc_freq u32` (> 0); `postings_offset u64` (relative to POSTINGS body);
`postings_len u64`. Duplicate terms in one field are rejected.

**POSTINGS section:** concatenated per-term blocks. Per block:
`occurrence_index u8` (`0` = doc-id-only, `1` = positional);
`doc_count u32`; then doc ids as first-absolute-then delta unsigned LEB128
varints, **strictly increasing**; then per doc `freq u32` (≥1); for positional
blocks, `freq` occurrence records:
`position_delta varint` (first occurrence absolute, subsequent deltas > 0),
`position_length varint` (≥1), `value_index varint`,
`start_offset varint`, `end_offset varint`, with `start ≤ end` and every offset
a valid UTF-8 boundary only verified against the source at a higher layer.
All arithmetic is checked; violation is a typed corruption error (INV04).

**Varint canonicality:** unsigned LEB128, little-endian groups of 7 bits,
**minimal-length encoding required**; overlong encodings and >64-bit values are
rejected before use. This removes ambiguity and hostile-length tricks.

**Optional skips:** reserved feature `F_SKIP_BLOCKS` (id `0x0008`), **not emitted
in v1** and not required by any v1 reader. If later enabled, skip metadata is a
separate `SKIP_INDEX` section; the postings block format stays unchanged.

**No FST in PR 5.** The sorted dictionary is the v1 lookup structure. FST
compilation/intersection belongs to PR 8. PR 5 must expose bounded dictionary
lookup/iteration contracts, not an FST.

### Alternatives

- Front-coded / block-compressed dictionary. Smaller, but adds decode complexity
  and is an optimization with no correctness requirement; defer until measured.
- Fixed-width `u64` postings instead of varints. Simpler and removes
  canonicalization risk; larger. **Recommended as the conservative fallback** if
  the human prefers to minimize v1 decoder risk. The format must choose one; a
  version bump can switch encodings.
- Absolute positions instead of deltas. Larger; no benefit.

### Compatibility implications

The `occurrence_index` byte reserves future posting variants. New encodings must
be advertised as requirements; unknown required variants fail closed.

---

## F06 — Stored source documents and JSON fidelity

### Recommendation (R-F06)

**Semantic preservation of the validated typed document, not byte-for-byte
request bytes.** PR 2 has no raw-JSON source capture; `Document` is already a
canonicalized typed structure. PR 5 stores it losslessly with respect to the
contract: logical key, exact field states (A04), typed values, multivalue order,
and full nested JSON.

**STORED section:** `stored_version u16 = 1`; `stored_count u64`; for each
physical doc id ascending: `key_len u16` + key; `present_field_count varint`;
for each present field by ascending `field_id`: `field_id u32`;
`state u8` (`1` explicit null, `2` empty multi, `3` single, `4` multi);
single = one value; multi = `count varint` + `count` values. **Absent fields are
not encoded** (absence is the omission of the field).

JSON value encoding (recursive, depth-bounded by A20 `JsonDepth`):
tag `0x00 Null`, `0x01 Bool`+1 byte, `0x02 I64`+8 bytes, `0x03 U64`+8 bytes,
`0x04 F64`+8 bytes (finite only), `0x05 String`+`len varint`+UTF-8,
`0x06 Array`+`count varint`+values, `0x07 Object`+`count varint`+pairs.
Array order and object member order are preserved exactly. Explicit JSON null is
`JsonValue::Null`, distinct from field `ExplicitNull` and from absence.
Non-finite floats are rejected (A03).

**Limits (before allocation):** max field count (A20 `Fields`), max array
elements (A20 `ArrayElements`), max JSON depth (A20 `JsonDepth`), max stored
value bytes, and max total section bytes (F11). Decoding preflights counts and
lengths against the remaining section bytes.

### Alternatives

- Byte-for-byte original request JSON. Requires a new PR 2 contract to retain raw
  bytes; **out of scope** and a STOP if required.
- Re-encode via a general JSON library. Rejected: adds a dependency, may reorder
  members or reformat numbers, and loses typed integer width control.

### Compatibility implications

New JSON tags are additive; unknown tags fail closed. A future
byte-for-byte contract would be a new field/option under a new major version.

---

## F07 — Typed columns, null states, multivalue, numbers, IP, geo, group keys

### Recommendation (R-F07)

One **COLUMNS** section with a per-columnar-`field_id` directory; each column
block is contiguous and independently digest-covered.

Per block: `column_version u16 = 1`; `field_id u32`; `doc_count u64`; then per
physical doc id: `state u8` (`1` explicit null, `2` empty multi, `3` single,
`4` multi); single = one value; multi = `count varint` + values in original
order. Min/Max selector selection is query-time (A15); **all** values are stored.

Value encodings (LE unless noted):

| Type | Encoding |
|---|---|
| Bool | `u8` 0/1 |
| I64 | `i64` 8 bytes two's complement |
| U64 | `u64` 8 bytes |
| F64 | IEEE-754 `f64` 8 bytes, **finite only** |
| Timestamp | `i64` microseconds UTC (A13) |
| Keyword | `len u16` + UTF-8 bytes |
| GeoPoint | `lon f64`, `lat f64` (16 bytes, bit-exact; `-0.0` preserved) |
| IpAddress | `family u8` (`0` IPv4, `1` IPv6) + 4/16 address bytes |
| IpNetwork | `family u8` + 4/16 address bytes + `prefix u8` |

Rules: IPv4 and IPv6 are family-tagged and never text-compared; IPv4-mapped IPv6
stays IPv6 (family `1`) unless an approved schema-level `normalize_ipv4_mapped`
opt-in exists (A07) — the flag, if added, must be part of the field descriptor
version. CIDR prefix ranges validated (0–32 / 0–128), host bits already rejected
by `IpNetwork` (A08). Geo rejects non-finite and out-of-range coordinates.

**Group keys:** a typed, length-delimited tuple encoding used by PR 10:
`tuple_len varint`; per component `type_tag u8`; `state u8` (`0` missing,
`1` explicit null, `2` value); then canonical value bytes (as above, with family
tags). Distinct types/families/lengths cannot collide (INV10). Canonical ordering
for deterministic group output is defined by a **decoded type-aware comparator**
(type tag, then value semantics; missing before null before values), **not** by
raw byte order, avoiding signed-integer and float bit-order pitfalls.

### Alternatives

- Column-major (whole column values contiguous) vs doc-major (per-doc states).
  Recommendation is doc-major state stream with per-doc value runs for v1
  simplicity and exact null/missing round-trip; column-major is a measurable
  optimization for later.
- Bit-packing/dictionary-encoding keywords. Deferred; correctness first.

### Compatibility implications

New column types/tags are additive under required features. Unknown required
column types fail closed. Changing a `u8` state tag meaning is a major-version
change.

---

## F08 — Conservative time/geo bounds and unprunable state

### Recommendation (R-F08)

Bounds are only used for pruning; **unknown/absent bounds must disable pruning
and never exclude matches** (INV09).

**TIME_BOUNDS:** `state u8` (`0` Unknown, `1` Known). If Known:
`min_micros i64`, `max_micros i64`, `ordered u8` (`0`/`1`). Known requires the
schema's primary timestamp to be present, Single, and non-null for **every** live
doc; otherwise `Unknown`. A Known range with `min > max` is corruption.
Optional per-block bounds are reserved (`F_BLOCK_TIME_BOUNDS`, not in v1).

**GEO_BOUNDS:** per GeoPoint columnar field: `field_id u32`; `state u8`
(`0` Unknown, `1` Known); if Known: `west f64`, `south f64`, `east f64`,
`north f64`, `crosses_antimeridian u8`. For a crossing envelope `west > east`
represents the union `[west, 180] ∪ [-180, east]` (A14). Unknown if any live doc
lacks a point. Dateline cases are explicitly tested.

**SORTED_REMAP** describes physical ordering (F09).

### Compatibility implications

Adding block-level bounds is additive/optional. A wrong-but-"known" bound is a
correctness bug; unknown is always safe.

---

## F09 — Sorted doc-id permutation, tie-breaker, total remapping

### Recommendation (R-F09)

When a sorted layout is requested (e.g., primary-timestamp ascending), the
physical order is: **primary timestamp ascending, then `DocumentKey` raw UTF-8
byte ascending** (A15 final tie-break). Absent/null timestamps sort by the
explicit missing-value policy and are disambiguated by key, so the order is total
and deterministic.

**SORTED_REMAP** section: `state u8` (`0` identity, `1` present); if present:
`physical_to_original`: `doc_count` × `u64`; `original_to_physical`:
`doc_count` × `u64`. Both arrays must be valid permutations of `0..doc_count`
(bijective, no duplicates, no out-of-range) or the segment is corrupt. Both
directions are stored so validation is cheap and unambiguous.

The remap is applied to **every** doc-addressed structure: DOC_KEYS,
VERSION_REFS, LIVE_DOCS, STORED, all COLUMNS, postings doc-id sequences, and
bounds are computed over physical order. A single encoder entry point performs
the permutation so no structure can be missed (INV08). Cross-structure agreement
is asserted by test P5-U44..U50 and P5-P04.

### Compatibility implications

A future SORTED_REMAP variant is a new `state` value under a new required
feature. Identity layout (`state = 0`) must remain readable by all v1 readers.

---

## F10 — Manifest schema and reference validation (no publication)

### Recommendation (R-F10)

The manifest is an immutable metadata container with the same header/footer
discipline as a segment (F02), magic `TRWMAN01`, and a MANIFEST section:

```text
manifest_version u16 = 1
schema: <F03 encoding>
segment_count u32
  per segment, ascending SegmentId UTF-8:
    segment_id_len u16 + bytes           # existing storage::SegmentId grammar
    object_key_len u16 + bytes           # existing ObjectKey grammar
    content_digest [u8;32]               # ContentDescriptor digest
    content_length u64
    time_bounds: <F08 encoding>          # optional pruning metadata
    required/optional feature sets (per segment)
required_features, optional_features
generation:  present u8; generation u64; parent_generation: present u8; u64
writer_epoch: present u8; u64            # reserved; never published by PR 5
content_digest [u8;32]
```

**Validation:** reject duplicate segment ids or object keys, missing content
descriptor fields, zero/oversized lengths, digest length mismatches, duplicate
schema field names, unknown required features, and any reference whose key fails
the existing `ObjectKey`/`SegmentId` grammar. All offsets/lengths checked.

**Prohibited in PR 5:** writing `CURRENT`, publishing a committed generation,
allocating generations/epochs, refresh, or recovery. The generation/epoch fields
are **reserved placeholders** that PR 6 will populate under its own protocol.
PR 5 may serialize/deserialize/validate a manifest and round-trip it through the
real `Directory`, but must not treat any file as a published generation.

### Compatibility implications

Manifest major bumps follow the segment major policy. Generation/epoch semantics
are PR 6; PR 5 must not assign meaning that binds PR 6.

---

## F11 — Explicit caps, checked arithmetic and cancellation checkpoints

### Recommendation (R-F11)

Every encoder/decoder entry point enforces declared caps and rejects **before**
allocation or unbounded reads. Proposed v1 ceilings (hard; human may adjust):

| Cap | Proposed default | Notes |
|---|---|---|
| `max_segment_bytes` | 256 MiB | whole-file materialization (PR 3/13) |
| `max_docs` | 2^32 | |
| `max_schema_fields` | 4,096 | A20 `Fields` for documents may be lower |
| `max_term_bytes` | 4,096 | matches PR 4 `HARD_MAX_TERM_BYTES` |
| `max_terms_total` | 2^32 | |
| `max_postings_per_term` | 2^32 | |
| `max_positions_per_posting` | 2^32 | |
| `max_array_elements` | A20 `ArrayElements` | reuse PR 2 |
| `max_json_depth` | A20 `JsonDepth` | reuse PR 2 |
| `max_section_decode_bytes` | 256 MiB | per section, ≤ segment cap |
| `max_stored_doc_bytes` | min(doc budget, section cap) | |
| `max_sections` | 64 | footer bound |
| `max_features` | 256 | footer bound |
| `max_read_bytes_per_call` | 1 MiB | positional read bound |
| `max_work_units` | analogous to PR 4 | decode work metering |

Rules: all offset/length/count arithmetic uses `checked_add`/`checked_mul`;
`u64 ↔ usize` conversions are checked (`try_from`); counts/lengths are validated
against the remaining declared section/segment bytes before reserving; readers
never trust footer offsets and must verify `offset + length ≤ segment_len` and
non-overlap of section ranges. Decode loops poll cancellation at fixed
checkpoints and after each decoded entry/batch; cancellation/exhaustion is a
typed error, never a partial trusted result (INV05, INV12).

### Compatibility implications

Caps are decoder policy, not wire format; raising them does not change bytes.
A wire value exceeding a cap is a typed error, never truncation.

---

## F12 — Compatibility, capabilities, golden fixtures, evolution

### Recommendation (R-F12)

- **Major**: incompatible layout/semantics. A v1 reader must fail closed on any
  unknown major. No cross-major read compatibility is promised in v0.1; a migration
  is an explicit future decision.
- **Minor**: additive, backward-compatible only when every difference is covered
  by known optional features. Until a compatibility policy is approved, v1
  readers reject unknown minor versions (conservative; can be relaxed by a
  future decision).
- **Required vs optional features**: unknown required → fail closed; unknown
  optional → ignore. The existing `contract::Capability`/`CapabilitySet` shape is
  reused for runtime negotiation where applicable; on-disk feature ids are a
  codec-internal numeric namespace mapped to capability names.
- **Golden fixtures**: bytes are **checked into the repository** under
  `crates/trawler-core/tests/fixtures/segment/` with an independently authored
  expected-content table (document key, field, term, position, offset, typed
  value, bounds, remap). Golden tests decode committed bytes; self-round-trip is
  additionally required but not a substitute. Regeneration instructions record
  the exact input fixture and deterministic seed. A fixture is only updated by an
  explicit, reviewed format decision.
- **Evolution**: new capabilities add optional sections/features; existing
  section kinds and value tags keep their v1 meaning. Removing/altering a v1
  meaning is a major-version change.
- **No cross-version compatibility claim** beyond the above until approved by a
  later decision record.

---

## Summary of decisions requiring explicit human approval

| ID | Proposed recommendation | Confidence / open point |
|---|---|---|
| F01 | One sectioned container file per segment | Confirm vs multi-file |
| F02 | `TRWSEG01`, LE, header+footer, SHA-256, required/optional features | Confirm SHA-256 vs CRC |
| F03 | Canonical name-sorted numeric `field_id`; analyzer fingerprint stored | — |
| F04 | Dense physical doc ids; byte-exact keys; revision/live refs only | — |
| F05 | Per-field UTF-8-sorted dictionary; varint delta postings; positions+offsets+value_index; skips reserved | Confirm varint vs fixed-width |
| F06 | Semantic typed stored source; nested JSON order preserved | Confirm semantic (not byte-for-byte) |
| F07 | Doc-major typed columns; family-tagged IP; tagged group keys | — |
| F08 | Known/Unknown bounds; unknown disables pruning; antimeridian envelope | — |
| F09 | Timestamp then key tie-break; stored bidirectional permutation | — |
| F10 | Manifest codec valid (no CURRENT/publication) | — |
| F11 | Explicit hard caps and cancellation checkpoints | Confirm numeric ceilings |
| F12 | Major fail-closed; optional additive evolution; checked-in goldens | Confirm conservative minor policy |

## Explicit STOP statement

No production codec will be implemented until:

1. this document is marked **APPROVED / APPROVED WITH CHANGES** by a human,
2. the approved commit SHA is recorded in the table above,
3. the invariant→test traceability in
   `docs/pr-artifacts/pr-5/correctness-matrix.md` is accepted, and
4. any requested changes are folded back into this document.
