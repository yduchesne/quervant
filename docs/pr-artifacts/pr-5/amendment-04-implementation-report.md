# PR 5 Amendment 04 implementation report — decoder budget consistency

> **Branch:** `dev/segment-codecs`
> **Pre-amendment baseline:** `dcaffb3b1dccb93f5e655713652cfb394645efe7`
> **Status:** complete; awaiting independent review. **No merge.**

## 1. Change summary

Introduced `crates/trawler-core/src/segment/decode_budget.rs` with
`DecodeBudget<'a>` (`new`, `retained`, `reserve_bytes`, `reserve_vec<T>`,
`reserve_string`, `reserve_btree_entry<K,V>`), registered privately in
`segment/mod.rs`. Failed reservations leave the budget unchanged; overflow is a
typed `LimitExceeded`.

R5-I10–R5-I13 fixes:

| Finding | Fix |
|---|---|
| R5-I10 dictionary | Outer `Vec<(u32,Vec<DictionaryEntry>)>` and per-field `Vec<DictionaryEntry>` precharged via `reserve_vec`; borrowed term bytes validated and `reserve_string`-charged before ownership; `previous_term` clone eliminated (compare `entries.last()`); one owned term copy |
| R5-I11 schema | `Vec<CodecField>` precharged; borrowed name validated and `reserve_string`-charged before `to_owned`; analyzer/normalizer binding id+version payloads charged (see deviation) |
| R5-I12 stored/JSON | One `DecodeBudget` shared across all records, fields and nested values; `Vec<StoredRecord>`, key string, `BTreeMap` entries, multi-value vectors, JSON array/object vectors, strings and object keys all precharged; public `decode_field_values`/`decode_scalar`/`decode_json` signatures preserved via fresh-budget wrappers and internal `*_budgeted` siblings |
| R5-I13 remap | Both permutation arrays charged cumulatively before either allocation; `DocRemap::from_order` is no longer called from `decode`, eliminating the third inverse vector; direct construction from validated arrays; identity path also precharges both vectors |

## 2. Files changed

Production: `segment/decode_budget.rs` (new), `segment/mod.rs`,
`segment/dictionary.rs`, `segment/schema.rs`, `segment/stored.rs`,
`segment/value.rs`, `segment/remap.rs`.
Tests: `tests/segment_corrective_pass04.rs` (new, 17 tests); module unit tests in
`decode_budget.rs` (5).

Unchanged: `limits.rs`, `format.rs`, `reader.rs`, manifest/`ManifestDecodeBudget`,
encoders, container framing, public `SegmentLimits`/`SegmentReader`/`ColumnReader`/
`DocRemap::from_order`, `trawler-objectstore`, `trawler-distributed`, Cargo
manifests/lockfile, golden fixture.

## 3. Allocation-order audit (reviewer-verifiable)

Each charged allocation is preceded by its cumulative reservation:

- **dictionary** `:110` outer `reserve_vec` → `:118` `try_reserve_exact`;
  `:157` inner `reserve_vec` → `:164` `try_reserve_exact`; `:199`
  `reserve_string` → `:201` `to_owned`.
- **schema** `:45`/`:46` `reserve_string(id/version)` → `:51`/`:52` `to_owned`;
  `:318` `reserve_vec::<CodecField>` → `:321` `try_reserve_exact`; `:338`
  `reserve_string(name)` → `:339` `to_owned`.
- **stored** `:97` `reserve_vec::<StoredRecord>` → `:110` `try_reserve_exact`;
  `:125` `reserve_string(key)` → `:126` `DocumentKey::new`; `:150`
  `reserve_btree_entry` → `:152` field decode.
- **value** `:110` `reserve_vec::<FieldValue>` → `:111` `with_capacity`; `:188`
  `:195` `reserve_string` → `:189` `:196` `to_owned`; `:374`/`:384` JSON vector
  `reserve_vec` → `:375`/`:385` `with_capacity`; `:368`/`:393` string/key
  `reserve_string` → `:369`/entry push.
- **remap** `:133`/`:134` identity and `:152`/`:153` explicit both `reserve_vec`
  before `:154`/`:158` `with_capacity`.

## 4. Deviation from the plan text (resolved, not a STOP)

The plan stated `FieldBinding` is "a fixed-size inline struct … no separately
allocated binding strings". The actual `FieldBinding` owns `id: String` and
`version: String`. Under invariant A4-01 these must be charged, so the decoder
now `reserve_string`s both payloads. This is stricter than before, requires no
public or wire change, and is the only correct reading of the ownership model.
Recorded for human review.

## 5. Residual risks

- Modeled retained-byte charge, not allocator/RSS/heap.
- `BTreeMap` node overhead is an estimate (`3 * size_of::<usize>()`).
- `ManifestDecodeBudget` is intentionally not migrated (`Manifest` keeps its own
  model); harmonizing the two is deferred.
- Each logical decode has its own budget; no whole-segment aggregate cap.
- Whole-segment buffering remains an accepted PR 5 limitation.

## 6. Validation

See `amendment-04-validation-report.md`. All mandatory gates pass; no merge.
