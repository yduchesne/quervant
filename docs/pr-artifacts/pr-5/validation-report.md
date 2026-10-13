# PR 5 validation report

> Exact commands and results are recorded for the final working tree. This is a
> code-bearing PR; every applicable mandatory gate was executed locally with
> `cargo +1.85.0` (MSRV `rustc 1.85.0 (4d91de4e4 2025-02-17)`), without a merge.

## 1. Baseline vs feature evidence

- **Baseline (pre-implementation, approved HEAD `84ed70b`)**: 639 passed / 0
  failed / 1 ignored; 87.74% workspace line coverage. Recorded in
  `implementation-preflight.md`.
- **Feature acceptance (final working tree)**: 689 passed / 0 failed / 2 ignored;
  85.26% workspace line coverage. The increase is the 50 new segment-codec tests
  (unit + integration + golden).

## 2. Mandatory command results

| Gate | Exact command | Exit | Result |
|---|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | 0 | PASS |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | 0 | PASS — **689 passed / 0 failed / 2 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | 0 | PASS |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | PASS |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | 0 | PASS |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | 0 | PASS — **TOTAL 85.26% line / 89.97% function / 92.57% region** |
| Whitespace | `git diff --check` | 0 | clean |

The threshold flag was independently verified: the same command with
`--fail-under-lines 99` exits non-zero, confirming enforcement is active.

### Ignored tests (not passes)

1. `crates/trawler-objectstore` RustFS/S3 harness **SKIP** (real adapter is
   PR 13) — pre-existing.
2. `segment_golden::regenerate_golden` — deliberately `#[ignore]`d to prevent
   accidental fixture drift.

A SKIP is not a pass and no RustFS conformance is claimed.

## 3. Coverage by segment module (final)

| File | Line |
|---|---|
| `segment/error.rs` | 95.45% |
| `segment/limits.rs` | 95.83% |
| `segment/model.rs` | 100.00% |
| `segment/schema.rs` | 82.99% |
| `segment/format.rs` | 82.29% |
| `segment/build.rs` | 82.35% |
| `segment/postings.rs` | 82.14% |
| `segment/remap.rs` | 81.16% |
| `segment/dictionary.rs` | 80.00% |
| `segment/reader.rs` | 77.12% |
| `segment/bounds.rs` | 76.82% |
| `segment/stored.rs` | 76.54% |
| `segment/value.rs` | 76.23% |
| `segment/manifest.rs` | 75.98% |
| `segment/column.rs` | 75.17% |
| **Workspace TOTAL** | **85.26%** |

## 4. Adversarial evidence (executed)

| Area | Test(s) | Observable result |
|---|---|---|
| Whole-file vs envelope digest domains | `p5_a21_envelope_and_whole_file_digests_cover_different_domains` | Trailer tamper breaks the whole-file descriptor; envelope is checked separately; substitution rejected |
| Posting count vs segment count | `p5_a22_posting_doc_count_distinct_from_segment_doc_count` | 10 docs, term in docs 7/9 → `posting_doc_count = 2 < doc_count = 10`; out-of-range/duplicate/non-monotone rejected |
| Persisted column geometry | `p5_a23_columns_persisted_block_geometry_and_bounded_access` | `block_docs = 3` reopened under default 1,024; docs 0/2/3/4 accessible; `blocks_read == 12` (1/block) |
| Malformed geometry | `p5_a05_a07_column_geometry_is_rejected` | Zero `block_docs` rejected |
| `advance` monotonicity | `p5_a01_advance_semantics` | in-between/current/EOF/idempotent semantics |
| Cancellation | `postings_round_trip_and_errors` | `CancellationFlag` → `SegmentError::Cancelled` |
| Five-state fidelity | `p5_a08_five_states_round_trip`, `column_multi_value_round_trip` | absent/null/empty/single/multi distinct; `SINGLE` vs `MULTI(1)` distinct |
| Partial time presence | `p5_a13_a14_time_bounds_presence` | Positive pruning safe under `SOME`; negated range not pruned with a missing value |
| Antimeridian geo | `p5_a15_geo_antimeridian_envelope` | Crossing envelope; disjoint/interior bboxes correct |
| Remap consistency | `p5_a20_timestamp_sorted_remap`, golden | Physical order by timestamp then key; stored/postings/remap agree |
| Corruption/truncation | `p5_u01`, `p5_u02`, `format_footer_and_feature_errors`, `container_builder_and_parse_errors` | Typed errors, no panic |
| Non-canonical varints | `p5_u05_noncanonical_varint_rejected` | Overlong/invalid rejected |
| Real directories | `p5_i01_memory_directory_reopen`, `p5_i06_fs_directory_fresh_instance_reopen` | Reopen via `MemoryDirectory` and a fresh `FsDirectory` |

## 5. Golden fixture

- Path: `crates/trawler-core/tests/fixtures/segment/golden.seg`
- `sha256 = ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`
- Size: 1688 bytes
- Decoded by `p5_g02_golden_decodes_expected_table` against a hand-authored
  expected table (keys in physical order, typed values, term dictionary,
  postings, remap, time bounds, columnar read). Regeneration is an ignored test.

## 6. Failure classification

No mandatory gate failed. No introduced regression, feature defect, flaky
failure, or environment/harness failure was observed. Pre-existing items
reported but not modified:

- `docs/TESTING.md` literal conflict markers (lines 56–59) — documentation-only,
  out of PR 5 scope.
- RustFS/S3 harness SKIP — PR 13.

## 7. Limitations / residual risks

- Coverage margin is modest (85.26% vs the 85% floor).
- v1 dictionary lookup and postings `advance` are sequential by design.
- Selective range reads are not independently content-authenticated; a future
  authenticated-range scheme requires separate approval.
- Source-boundary validation of stored offsets is a higher-layer concern.
- No merge was performed; PR 5 remains subject to independent review.
