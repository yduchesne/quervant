# PR 5 decoder budget audit (R5-I07 / C5-INV01, C5-INV09)

Every allocation or multiplication driven by untrusted bytes is listed with its
preflight rule. Guards run **before** any `with_capacity`/`reserve`; failures are
typed `SegmentError::{LimitExceeded, Truncated, Corrupt}`. `max_single_allocation`
is a conservative per-allocation bound (`count * size_of::<T>()` or explicit
bytes); `max_section_decode_bytes` is the cumulative retained-byte budget;
`max_decoded_entries` bounds entry counts.

| Decoder | Untrusted quantity | Preflight (in addition to source bounds) |
|---|---|---|
| `format::parse_container` footer | `section_count` | `max_sections`; `check_alloc::<SectionEntry>` before reserve |
| `format::read_features` | feature `count` | `max_features`; `check_alloc::<(u16,u16)>` |
| `schema::CodecSchema::decode` | `field_count` | `check_entries`; `check_alloc::<CodecField>`; `count_min_bytes(..., 13, remaining)`; cumulative `check_decoded_bytes` over retained names |
| `dictionary::DictionaryReader::new` | `field_count` | `check_entries`; `check_alloc::<(u32,Vec<DictionaryEntry>)>`; `count_min_bytes(..., 12, remaining)`; `try_reserve_exact` |
| `dictionary::DictionaryReader::new` | per-field `term_count` | running `max_terms_total`; `check_entries`; `check_decoded_bytes`; `check_alloc::<DictionaryEntry>`; `count_min_bytes(..., 27, remaining)`; cumulative retained term bytes vs `check_decoded_bytes` |
| `stored::decode_stored` | `count` | `max_docs`; `check_entries`; `check_alloc::<StoredRecord>`; `count_min_bytes(..., 3+bitmap_len, remaining)`; `try_reserve_exact` |
| `value::decode_field_values` | multi `count` | `max_array_elements`; `check_entries`; `check_alloc::<FieldValue>` |
| `value::decode_json` | array `count` | `max_array_elements`; `check_entries`; `check_alloc::<JsonValue>` |
| `value::decode_json` | object `count` | `max_array_elements`; `check_entries`; `check_alloc::<(String, JsonValue)>` |
| `value::decode_json` | string/key `len` | `check_len` vs `max_single_allocation`; each byte read bounds-checked |
| `postings::PostingsReader::new` | `posting_doc_count` | `max_postings_per_term`; `<= segment_doc_count` |
| `postings::PostingsReader::next` | per-doc `freq` | `max_decoded_entries`; `check_alloc::<Occurrence>` before `reserve` |
| `column::encode_columns` (encoder) | `docs.len()` | `check_entries` |
| `column::ColumnReader::open` | `column_count` | `check_entries`; `check_alloc::<ColumnMeta>`; `count_min_bytes(..., COLUMN_HEADER_LEN, remaining)`; `try_reserve_exact` |
| `column::ColumnReader::open` | `block_count`, `block_docs`, extents | `block_docs != 0`; `block_count == ceil(doc_count/block_docs)`; `dir_len == block_count*BLOCK_ENTRY_LEN`; every offset/extent via `checked_add`; each block bounded by its own column end; nonoverlap across columns |
| `column::ColumnReader::value` | multi `count` | `check_entries`; `check_alloc::<FieldValue>` |
| `remap::DocRemap::decode` | `doc_count` | `check_entries(2*doc_count)`; `check_alloc::<u64>`; `count_min_bytes(..., 8, remaining)` |
| `reader::decode_geo_bounds` | `count` | `check_entries`; `check_alloc::<GeoBounds>`; `count_min_bytes(..., 55, remaining)` |
| `reader::read_all` | whole-file `len` | `accepted_segment_bytes` |
| `manifest::Manifest::decode` | `schema_len` | `check_allocation_bytes` |
| `manifest::Manifest::decode` | `segment_count` | `check_entries`; `check_alloc::<ManifestSegmentRef>`; `count_min_bytes(..., MIN_SEGMENT_REF_BYTES, remaining)`; `try_reserve_exact`; cumulative `check_decoded_bytes` over ids/keys |
| `manifest::decode_features` | feature `count` | `max_features`; `count_min_bytes(..., 4, remaining)`; `check_alloc::<(u16,u16)>`; strictly-ascending/duplicate-free |
| `bounds::TimeBounds::decode` / `GeoBounds::decode` | fixed-width | fixed 39/55-byte slices; presence/count consistency checked |

## Cross-section validation performed at `SegmentReader::open`

- Container kind, version, endian, flags, required features.
- Schema decoding and field-id density.
- Remap length equals header `doc_count`; bijection validated.
- Dictionary/posting coherence: `POSTINGS` present iff dictionary present; every
  dictionary posting extent inside the `POSTINGS` body.
- Column geometry validated eagerly (one addressed block per access), and each
  column's `doc_count` equals the segment `doc_count`.
- Stored header `count` equals the segment `doc_count`.
- Time/geo bounds shapes validated.

**Lazy (not eagerly decoded):** stored records (`SegmentReader::stored`),
individual column values, and postings blocks. Dictionary `doc_freq` vs posting
`posting_doc_count` is compared when `postings()` is called.

## Residual

- The whole-file read (`read_all`) is bounded by `accepted_segment_bytes` rather
  than `max_single_allocation`; that is intentional and documented — the entire
  container must be in memory for full-envelope verification.
- `check_alloc` is a conservative upper bound, not an exact `Vec` capacity claim.
