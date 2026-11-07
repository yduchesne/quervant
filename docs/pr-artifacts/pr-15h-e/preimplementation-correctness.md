# PR 15H-E — pre-implementation correctness contract

## Producers/consumers inspected

- Producers: `segment/build.rs::SegmentBuilder::build` and
  `index/merge.rs::build_merged_segment_with`; both emit
  `SectionKind::Dictionary` only when positional postings/dictionary fields exist.
- Consumer: `segment/reader.rs::decode_metadata` (feature support, schema, norms,
  dictionary, posting extents).
- Codec: `segment/dictionary.rs::{encode_dictionary,DictionaryReader::new_metered}`.
- Feature registry: `segment/format.rs::SUPPORTED_FEATURES`.
- `ByteReader::varint`/`ByteWriter::varint` already implement canonical unsigned
  LEB128; no new varint code is allowed.

## Frozen E contract

- Feature `FEATURE_COMPACT_DICTIONARY = 0x000C`, required `(0x000C,1)`.
- Dictionary payload v2: `u16 version=2`, `u32 field_count`, then for each
  ascending field: `u32 field_id`, `u64 term_count`, then each ascending term:
  `u16 len`, UTF-8 bytes, and canonical LEB128 `doc_freq`,
  `postings_offset`, `postings_length`.
- v1 remains `version=1` with fixed `u64` metadata; decoded `DictionaryEntry`
  values are identical for identical logical input.
- v2 preflight `MIN_TERM_BYTES = 6`; v1 stays 27. Feature/payload mismatch is a
  typed `Corrupt`; unknown required feature is `UnsupportedFeature`.
- Both producers emit v2+feature iff a dictionary is emitted; no dictionary means
  no feature. Compaction always emits v2 and reads v1 or v2 sources.

## E invariant → tests

| Invariant | Tests |
|---|---|
| E-I01 legacy v1 read | `dictionary` v1 fixture tests; E-U01 |
| E-I02 exact v2 wire | E-U02–U05 |
| E-I03 feature/payload matrix | E-U06–U10 |
| E-I04 malformed/limits | E-U11–U19 |
| E-I05 budget/retained | E-U20–U22 |
| E-I06 other sections unchanged | E-P07, E-I04 |
| E-I07 query/score/order | existing suites, E-I06–I11 |
| E-I08 producers/compaction | E-U23–U26, E-I12–I16 |
| E-I09 durability/remote | E-I17–I21, real RustFS |
| E-I10 A/E identity | campaign manifest |
| E-I11 source-lock/idle | controller tests |
| E-I12 rollback | rollback commit + diff |
| E-I13 no API/format-major | source audit |
| E-I14 D closeout | D_PREDECESSOR_LOCK (CI waived) |

## Counterexamples

- v2 body without the required feature and v1 body with it must both be typed
  corruption; no fallback to the wrong decoder.
- Noncanonical/overflow/truncated varints, zero doc_freq/length, bad UTF-8,
  duplicate/unsorted terms, trailing data, and out-of-range posting extents must
  fail before verified-state publication.
- A no-dictionary segment must not carry the compact feature.
- A v1 source compacted to v2 must preserve surviving docs/revisions/tombstones.
