# PR 5 corrective implementation report

> **Branch:** `dev/segment-codecs`
> **Pre-correction baseline:** `b47861c5f5940ac60e815921fba3f39091473bba`
> **Status:** corrective fixup complete; awaiting independent review. **No merge.**

## 1. Findings disposition (R5-I01–R5-I07)

| Finding | Severity | Resolution |
|---|---|---|
| R5-I01 dictionary memory | HIGH | `DictionaryReader::new` now preflights `field_count`/`term_count` against remaining source bytes, per-allocation budget (`check_alloc`), cumulative retained bytes (`check_decoded_bytes`), and uses `try_reserve_exact`. `max_decoded_entries` is no longer used as a memory proxy. |
| R5-I02 column geometry | HIGH | `ColumnReader::open_with_doc_count` validates the complete canonical geometry at open: schema field membership/columnar/type/layout, directory length, cross-column nonoverlap, per-block `first_doc`/`rows`, state/value extents bounded by the owning column, state-tag validity, fixed slot width, and variable offset-table monotonicity/terminal value. |
| R5-I03 manifest count allocation | HIGH | `Manifest::decode` preflights `segment_count` (`check_entries`, `check_alloc`, `count_min_bytes`, `try_reserve_exact`) and tracks retained bytes. `schema_len` is allocation-bounded. |
| R5-I04 manifest required features | HIGH | Container `ensure_supported_features()` is called before payload parse; per-segment and manifest-level `required_features` are negotiated via the shared `ensure_features_supported`; feature sets must be strictly ascending/duplicate-free. |
| R5-I05 group-key encoding | MEDIUM | Implemented the approved F07 bytes exactly (`type_tag`, then `0x00`/`0x01`/`0x02`, then value) via `GroupComponent::{Missing(FieldType), Null(FieldType), Value}`. Not persisted in segment bytes; no wire/golden change. |
| R5-I06 stored-doc scalability | MEDIUM | `decode_stored` is bounded (entries + allocation + cumulative). `stored_doc`/`stored` behavior is documented: first access materializes and caches all records via `Rc`, bounded by F11 budgets; no format index invented. |
| R5-I07 sibling budgets | MEDIUM | Audited every untrusted allocation across `value`, `stored`, `postings`, `schema`, `remap`, `bounds`, `format`, `column`, `dictionary`, `manifest`, `reader`; added conservative preflights (see `decoder-budget-audit.md`). |

## 2. Files changed

Production (`crates/trawler-core/src/segment/`): `limits.rs` (allocation/
decoded-byte helpers), `format.rs` (shared `ensure_features_supported`,
`count_min_bytes`, feature/footer preflights), `dictionary.rs`, `column.rs`,
`manifest.rs`, `schema.rs`, `stored.rs`, `value.rs`, `postings.rs`, `remap.rs`,
`reader.rs`, `mod.rs` (exports).

Tests: new `crates/trawler-core/tests/segment_corrective.rs` (24 tests);
extended `src/segment/tests.rs` and `tests/segment_codec.rs` (group-key oracle).

Untouched: `golden.seg` (SHA-256 `ebb078…dae979`), `Cargo.toml`/`Cargo.lock`,
`trawler-objectstore`, `trawler-distributed`, PR 2/3/4 APIs, roadmap status.

## 3. Approved-format compliance

- No F01–F12 persistent byte, feature id, digest domain, section order, or
  compatibility change. Golden fixture byte-identical.
- Group-key bytes now match approved F07 (they are not persisted in the golden).
- `max_single_allocation` reinterpreted as a pre-reserve conservative bound per
  approved F11 separation (wire vs safety vs operational); no wire ceiling added.

## 4. Deferred / explicitly not done

- No PR 6 writer/commit/CURRENT/recovery, PR 7 query, PR 8 automata, PR 13
  RustFS bootstrap, distributed, or vector work.
- No per-document random-access stored index (would be a format change).
- No authenticated selective range-read scheme (separate decision).
- Dictionary/postings `advance` remain sequential by approved v1 design.

## 5. Residual risks

- Coverage headroom is modest (85.16%).
- `check_alloc` is a conservative upper bound, not exact capacity accounting.
- Whole-file read is bounded by `accepted_segment_bytes`, intentionally.
- Group-key API change is a conformance correction; if a reviewer disagrees,
  the change is isolated to `column.rs` and its tests.

## 6. Validation

See `corrective-validation-report.md`. All mandatory gates pass on the final
tree; no merge was performed.
