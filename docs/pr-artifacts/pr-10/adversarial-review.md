# PR 10 Adversarial Review

**Scope:** typed numeric/temporal retrieval and bounded exact analytics.
**Base:** `main` `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`.
**Branch:** `dev/temporal-retrieval`.
**Status:** implementation complete locally; PR not merged, roadmap not marked DONE.

Each invariant I01–I14 below lists adversarial counterexamples considered, the
production file that enforces the behavior, and the executed named tests.

| ID | Invariant | Adversarial cases considered | Implementation | Tests |
|---|---|---|---|---|
| I01 | Typed ranges honor type, inclusive/exclusive, any-member and missing/null | `Excluded` equal to the value; inverted `[10,5]`; unbounded sides; multi with only an out-of-range member; explicit null vs absent; empty multi | `search/typed_compare.rs::{matches_range,satisfies_lower,satisfies_upper}`; `search/typed.rs::validate_query` | `pr10_ranges::t01..t05` |
| I02 | Time filters are exact half-open signed UTC microseconds | `start==end`; `start>end` rejection; pre-epoch negatives; multi timestamp any-member; late/out-of-order ingestion | `typed_compare::matches_time_range`; `typed.rs::validate_query` | `pr10_time::t06..t09` |
| I03 | Every result/metric respects PR 9 effective-live masks and old PIT | delete then same-key search; upsert replacement; old PIT after delete; refresh vs committed | `ReaderSnapshot::effective_live_docs` consumed by `typed.rs::scan` | `pr10_integration::t10..t12`; unit `typed::empty_snapshot_returns_no_hits` |
| I04 | Sort is total across directions, ties, missing/null, multivalue | equal keys across directions; missing-first vs missing-last under `Desc`; null vs missing; min/max selector before direction; IPv4 vs IPv6 | `typed_compare::{compare_candidates,sort_value_cmp,select_sort_value,canonical_scalar_cmp}` | `pr10_sort::t13..t18`; unit `typed_compare::*` |
| I05 | Cursor binds snapshot and query/sort; no pagination gaps/duplicates | full multi-page walk; changed page size; changed query; changed sort; two snapshots at one generation | `typed.rs::{TypedCursor,fingerprint,SearchAccumulator}` | `pr10_cursor::t19,t20,t21_changed_query_or_sort_rejected,t23` |
| I06 | Buckets use signed floor division, correct boundaries and overflow | negative timestamps; shifted origin; exact boundary; zero/negative width; extreme i64 width | `analytics::bucket_start` (`i128::div_euclid`, checked `i128`) | `pr10_buckets::t24..t27`; unit `analytics::bucket_*` |
| I07 | Group expansion/dedup and null/missing/empty semantics are exact | duplicate multi values; missing/null/empty; empty multi → zero groups; Cartesian bound before allocation; two group keys | `analytics::{expand_field_values,AggregationEngine}`; canonical `encode_group_key` | `pr10_groups::t28..t32`; `pr10_distinct::t42` |
| I08 | Count/sum/min/max/avg follow exact declared arithmetic policy | count docs vs values; widening past i64/u64; compensated float sum; timestamp min/max; empty avg `None` | `analytics::{Accumulator,neumaier_add}` | `pr10_metrics::t33..t37` |
| I09 | Exact distinct and frequency top-K preserve ties and per-doc uniqueness | distinct across segments; duplicate multi; cardinality bound; canonical group order; per-doc uniqueness across groups; frequency ties | `analytics::{Accumulator::Distinct,apply_frequency,finish}` | `pr10_distinct::t38..t42`; `pr10_frequency::*` |
| I10 | Limits and cancellation fail atomically without partial output | exact vs one-over scan/groups/state; pre-cancelled entry; mid-scan cancellation; aggregation cancellation; no partial response | `search/limits.rs`; `typed.rs::ScanGuard` | `pr10_properties::t43..t48` |
| I11 | Pruning has no false negatives and measurable skipped segments | nonoverlapping times; boundary at max/end; unknown bounds; `And` vs `Or`/`Not`; pruning on/off differential | `typed.rs::{collect_positive_time,segment_pruned}` + `TimeBounds::prunes_positive_range` | `pr10_pruning::t49..t53` |
| I12 | Refresh/merge/reopen/late events preserve logical results | lossless compaction after delete; close/reopen; late earlier-timestamp arrival; seeded insertion order | unchanged PR 9 writer/merge + typed scan | `pr10_integration::t54..t57` |
| I13 | Unsupported sibling operators fail closed; lexical and codec regression green | `Term`/`Exists` rejected before I/O; BM25 term search unchanged; deterministic segment bytes | `typed.rs::{validate_query,evaluate_query,query_label}` | `pr10_integration::t59..t61`; unit `typed::unsupported_query_fails_closed` |
| I14 | MemoryDirectory/FsDirectory real-boundary results agree | same docs on both directories; corrupt committed segment | `typed.rs` + real `Directory` seam | `pr10_properties::t62,t63` |

## Adversarial counterexamples explicitly exercised

1. **Filter before cursor vs after cursor.** `total_hits` counts every matching
   live document, while the page heap excludes `<= cursor`. A paginated walk over
   10 documents asserts the exact key sequence with no gaps/duplicates.
2. **Distinct snapshot, same generation.** Two `Index::snapshot()` calls receive
   different process-wide `binding_id`s, so a cursor from one is rejected by the
   other (`CursorPitMismatch`), even though generation/view are equal.
3. **Null vs missing.** A `nullable` column with an explicit null and an absent
   document is asserted to sort as `Missing < Null` (First) and `Value < Null <
   Missing` (Last), and never to collapse.
4. **Empty multi-value.** Grouping by a field whose multi-value is empty yields
   zero groups for that document; a positive range never matches it; `Not` does.
5. **Checked arithmetic.** `i64::MAX + i64::MAX` and `u64::MAX + u64::MAX`
   produce `i128`/`u128` values, never wrapped i64/u64 values.
6. **Pruning safety.** `Or`/`Not` branches never contribute a positive conjunct;
   `segments_skipped_by_time` stays `0` for those and the unknown-bounds segment
   is scanned.
7. **Cancellation atomicity.** Entry, mid-scan and aggregation cancellation return
   `SearchError::Cancelled` with no `TypedSearchResponse`/`AggregateResponse`.
8. **Corrupt segment.** Flipping one byte of a committed `.seg` file makes
   `Index::open_existing` fail (content-descriptor digest mismatch) rather than
   return partial typed results.

## Known limitations / follow-ups (not defects)

- **1M benchmark size.** The writer's default `max_mutation_state_bytes` (32 MiB)
  is exceeded by a 1M-logical-key generation, so the `QUERVANT_PR10_BENCH_LARGE`
  1M fixture cannot be built with default `IndexLimits`. 10K/100K are measured.
- **Integer overflow error path.** A checked `i128`/`u128` sum cannot realistically
  overflow with in-memory fixtures; the tests demonstrate exact widening instead.
  The checked-arithmetic error is covered by construction and code review.
- **Cursor portability.** `TypedCursor` is deliberately in-process and
  non-serializable; cross-process/expiring cursors are PR 14 scope.
- **`dyn Cancellation` boundary.** Cancellation is a coarse-grained request-level
  trait object; it is not on the per-document hot path (checked per segment and
  every 256 charged units), matching the AGENTS dispatch guidance.
- **Per-segment column reader.** The scan opens one `ColumnReader` per segment and
  reuses it; there is no cross-segment cache and no partial/range column read.
- **Codec interruption.** Existing bounded column decodes are not interruptible
  mid-call; cancellation is observed between operations.
