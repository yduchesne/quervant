# PR 15H-D — correctness

Executed at candidate `0f97779`; the final source is the exact `c802f96` restore.

## Plan equivalence

`d_u03_u04_u05_plan_equivalence` compiles the same query through the original
`unified_plan::compile` and through `compile_with_resolved` with pre-resolved
bindings/codec, and asserts equality of `root`, `lexical_leaves`,
`positive_lexical`, `scoring_field_ids`, `codec`, and typed-leaf count for:
MatchAll, Term, And, Or, Not, Phrase, Prefix, Glob, Regex, Fuzzy and typed
`Exists`.

## End-to-end

`d_u07_u09_u10_search_and_cursor_parity` on a real `MemoryDirectory` index
compares the new normal path to the ineligible `And([Term])` fallback for K10,
K100, total hits, key order, score bits and cursor follow-up.

`d_u01_u02_u06_u14_validation_and_empty_index` covers empty index, the original
`select_keys` compiler path and invalid-sort rejection before segment access.

## Preserved suites

- `search::unified::b_tests` — 6 (B malformed-losing UTF-8, comparator parity).
- `pr15h_b_sort_materialization` — 6 (50K FsDirectory, two segments, PIT,
  cursor, multi/typed, corrupted container).
- `segment::column::b_keyword_view_tests` — 4; comparator tests — 3.
- Full workspace at candidate: 2,342 all-targets / 2,346 all-features, 0 failed.

## Semantics preserved

Compiler validation order, cursor/fingerprint-before-compile order, error
precedence, BM25 bits, counts, ordering, projection, batch/aggregation and
resource accounting are unchanged. Production diff was limited to the two
allowed search files; no format, API, Cargo, CI or storage change. Query-only
index digests were byte-identical between arms.

The D-only tests referenced `compile_with_resolved` and were removed by the
byte-for-byte rollback of `unified.rs`; the B/C suites remain green.
