# PR 10 Format Compatibility

**Conclusion: no segment, manifest, mutation-state, `CURRENT` or lexical-scoring
wire changes.** Index formats remain at their PR 5/PR 6/PR 9 versions.

## Changes and their wire impact

| Change | Wire impact |
|---|---|
| New `search/{typed,typed_compare,analytics}.rs` | None — reads existing sections only |
| `search/limits.rs` additive fields | None — in-memory configuration |
| `index/snapshot.rs` `binding_id` | None — process-local allocation, never persisted |
| `segment/reader.rs::open_columns()` | None — read-only accessor over the existing `COLUMNS` section |
| `search/mod.rs` re-exports | None |
| New benchmark and tests | None |

## Frozen surfaces respected

- `segment/format.rs`, `segment/manifest.rs`, `segment/column.rs`: untouched.
- `segment/build.rs`, `index/writer.rs`, `index/merge.rs`: untouched.
- `search/execute.rs` (lexical BM25) and `search/plan.rs`: untouched.
- `contract/*`: untouched; existing `Query`, `Sort`, `Cursor`, `Budgets` preserved.
- `quervant-objectstore`, `quervant-distributed`: untouched.
- No new Cargo dependency was added (`sha2` was already a dependency).

## Evidence

- `pr10_integration::t61_deterministic_segments` asserts two independent builds of
  the same logical documents produce byte-identical segment files.
- `pr10_integration::t60_lexical_bm25_unchanged` asserts the lexical BM25 path
  still returns the expected term hits and positive scores.
- Existing `segment_golden.rs`, `segment_codec.rs`, PR 7/8 and PR 9 codec/PIT
  suites remain green in the full workspace run (1320 passed, 0 failed).
- The PR 5 column codec round-trips through the new read-only `open_columns()`
  accessor without any byte change; `ColumnReader::open` still validates version
  `1` and the same geometry invariants.

## Explicitly deferred format work

The optional time-sorted physical layout described as *optional* by the roadmap is
**not** implemented. Adding it later would be a new, separately-versioned segment
capability and is out of PR 10 scope.
