# PR 15H-B — design verification

## Borrowed view contract (`segment/column.rs`)

`ColumnKeywordView<'a>` is `Missing`, `Null`, `Value(&'a str)` or `LegacyDecode`.
`ColumnReader::keyword_sort_view`:

1. finds the column meta (absent column → `Missing`);
2. resolves the schema field and checks the type tag exactly as `value()`;
3. returns `LegacyDecode` for non-Keyword/non-Single;
4. calls `span_of` exactly once (same block counter/bounds/errors):
   `ABSENT|EMPTY_MULTI → Missing`, `EXPLICIT_NULL → Null`, `Fixed`/`MULTI`/
   unexpected → `LegacyDecode`;
5. for `STATE_SINGLE` slices `bytes[start..end]` with the existing
   `"value range out of bounds"` error, then `len_prefixed_u16("keyword")`,
   UTF-8 validation, `DecodeBudget::reserve_string`, and
   `expect_end("column value")` — the same order as `decode_scalar` + `value()`;
6. never allocates, never uses unsafe, and borrows only `&self`.

## Comparator contract (`search/typed_compare.rs`)

`compare_borrowed_keyword_to_owned` computes the same rank as `rank_of`, reverses
only the value comparison for `Desc`, compares Keyword values by raw UTF-8 bytes,
and returns `None` for `LegacyDecode`/incompatible retained values. The caller
falls back to the ordinary owned candidate path for that candidate.
`owned_keyword_sort_value` materializes the conventional `SortValue` only at
admission with a fallible exact reservation.

## Selection contract (`search/unified.rs`)

Eligibility is `single_term_postings_eligible` **and** standalone
(`batch.is_none()`) **and** no `after` **and** exactly one sort field with no
JSON/geo **and** the contract schema field is `Keyword`/`Single`/columnar.

Per qualified candidate:

1. `total_hits` checked increment;
2. logical key resolution (`doc_key_selected`/`doc_key` rule);
3. `keyword_sort_view` validation (no allocation);
4. `borrowed_keyword_candidate_charge` (same formula/order as `candidate_charge`);
5. duplicate-retained-key check over the whole heap;
6. heap not full → materialize + original admission;
7. heap full → borrowed vs worst-owned comparison, then ascending key tie;
   loser returns without a tuple; winner materializes + original admission;
8. `LegacyDecode`/incompatible → ordinary owned candidate path for that one
   candidate with the already-resolved key.

The original owned heap admission sequence is extracted into
`heap_admit_candidate` and used by both paths. `execute.rs`, BM25,
`score_segment`, codecs, `CachedGeometry`, projection and public cursors are
untouched.

## Error-order parity

Key decode → column validation → modeled charge overflow → duplicate key →
heap admission. The only new early return is a loser that has already passed all
of those checks. `LegacyDecode` never invents a new error; it runs the legacy
decoder.

## Codec/budget boundaries

`value()`, `span_of()`, the wire layout, decode limits and the verified-geometry
cache are unchanged. The new reader performs the same validators and returns the
same typed errors (`InvalidUtf8`, `LimitExceeded`, `Corrupt`,
`InvalidColumnGeometry`).
