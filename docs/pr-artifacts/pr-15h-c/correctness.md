# PR 15H-C — correctness evidence

Executed at the measured candidate `fee4edb`; the final source is the exact
`e8744d3` restore after the qualified rejection.

## C unit tests (`search::unified::c_tests`)

| Test | Coverage |
|---|---|
| `c_u01_u02_u03_zero_and_singleton_routing` | 0 hits: no borrows; 1 hit on >=1024: `doc_key_selected`, 0 borrows, 1 admission; 1 hit on <1024: 1 borrow |
| `c_u04_u05_u12_u13_large_k_bounds_and_parity` | 50K common, K10/K100: 50K borrows, 0 fallback, admission <= K+1, exact keys/score bits vs `And([Term])` |
| `c_u06_u07_u08_u18_ordering_and_cursor` | DESC/ASC, missing first/last, explicit null, non-ASCII/NUL, key tie, cursor follow-up parity |
| `c_u09_u10_u11_cached_key_boundaries` | indexes 0/N-1 valid; N, `u64::MAX`, empty slice return exact `Corrupt { context: "doc keys" }` |
| `c_u15_duplicate_retained_key_before_competitiveness` | duplicate logical key returns the existing `CorruptIndex` before discard; no admission/fallback clone |
| `c_u16_legacy_decode_fallback_owns_one_key` | non-single-valued column: `LegacyDecode`, exactly one fallback clone, legacy Min selection, heap updated |

## Preserved B/regression evidence

- `search::unified::b_tests` — 6 passed (including the B malformed-losing UTF-8
  decision test and comparator parity).
- `pr15h_b_sort_materialization` — 6 passed (50K FsDirectory, two segments,
  PIT, cursor, multi/typed fallback, corrupt container).
- `segment::column::b_keyword_view_tests` — 4 passed.
- `search::typed_compare::b_comparator_tests` — 3 passed.
- Full workspace tests at candidate: 2,345 all-targets / 2,349 all-features,
  0 failed.

## Semantics preserved

`total_hits`, physical projection, BM25 bits, sort/cursor ordering, duplicate
detection, modeled charges, cancellation and all ineligible paths were
unchanged. No index bytes, manifest, public API or storage contract changed; A/B
index digests were byte-identical.

## Final-source note

The C-only tests referenced the rejected borrowed-key helper and were removed by
the byte-for-byte restore of `unified.rs`. The rollback source is the accepted
B-fixup implementation; its B tests and integration suite remain green.
