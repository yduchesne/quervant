# PR 10 Test Traceability

All commands were run from the workspace root on the final working tree
(`dev/temporal-retrieval` atop `2ecbbe2`). "Executed" means the command was run
locally; "PASS" means it returned success.

## Named integration suites

| Suite | Invariant(s) | Tests | Command | Result |
|---|---|---|---|---|
| `pr10_ranges` | I01 | T01–T05 (5) | `cargo test -p quervant-core --test pr10_ranges` | PASS |
| `pr10_time` | I02 | T06–T09 (4) | `cargo test -p quervant-core --test pr10_time` | PASS |
| `pr10_sort` | I04 | T13–T18 (6) | `cargo test -p quervant-core --test pr10_sort` | PASS |
| `pr10_cursor` | I05 | T19–T23 (4, T21 covers T21/T22) | `cargo test -p quervant-core --test pr10_cursor` | PASS |
| `pr10_buckets` | I06 | T24–T27 (4) | `cargo test -p quervant-core --test pr10_buckets` | PASS |
| `pr10_groups` | I07 | T28–T32 (5) | `cargo test -p quervant-core --test pr10_groups` | PASS |
| `pr10_metrics` | I08 | T33–T37 (5) | `cargo test -p quervant-core --test pr10_metrics` | PASS |
| `pr10_distinct` | I09 | T38–T42 (5) | `cargo test -p quervant-core --test pr10_distinct` | PASS |
| `pr10_frequency` | I09 | frequency top-K (6) | `cargo test -p quervant-core --test pr10_frequency` | PASS |
| `pr10_pruning` | I11 | T49–T53 (6) | `cargo test -p quervant-core --test pr10_pruning` | PASS |
| `pr10_integration` | I03, I12, I13 | T10–T12, T54–T61 (11) | `cargo test -p quervant-core --test pr10_integration` | PASS |
| `pr10_properties` | I10, I14 | T43–T48, T62–T64 (9) | `cargo test -p quervant-core --test pr10_properties` | PASS |

**Total PR 10 integration tests: 70, 0 failures.**

## Unit tests added

| File | Tests | Coverage focus |
|---|---|---|
| `search/typed_compare.rs` | 6 | canonical order, missing/null, categories, bounds, time range, canonical bytes |
| `search/analytics.rs` | 4 | bucket floor/overflow, group expansion, Neumaier sum |
| `search/typed.rs` | 4 | empty snapshot, global group, unsupported query/sort |
| `search/limits.rs` | existing + typed bounds | defaults, ceilings, builders |
| `index/snapshot.rs` | existing | binding identity (exercised by cursor tests) |

## Invariant → evidence map

| ID | Primary tests | Topology | Counterexample |
|---|---|---|---|
| I01 | `pr10_ranges::t01..t05` | real committed `MemoryDirectory` index + column codec | excluded endpoint, empty multi, `Not` over missing/null |
| I02 | `pr10_time::t06..t09` | real committed index | `start==end`, pre-epoch, multi timestamp |
| I03 | `pr10_integration::t10..t12` | real writer commit + PR 9 PIT | delete/upsert/old PIT |
| I04 | `pr10_sort::t13..t18` | real committed index | missing/null ordering under Desc, multi selector |
| I05 | `pr10_cursor::t19..t23` | real committed index | changed page size, changed query/sort, two snapshots |
| I06 | `pr10_buckets::t24..t27` | real aggregate | negative floor, shifted origin, overflow width |
| I07 | `pr10_groups::t28..t32` | real aggregate | duplicate multi, empty multi, Cartesian bound |
| I08 | `pr10_metrics::t33..t37` | real aggregate | widening, compensation, empty avg |
| I09 | `pr10_distinct::t38..t42`, `pr10_frequency::*` | multi-segment committed index | cross-segment distinct, tie order, per-doc uniqueness |
| I10 | `pr10_properties::t43..t48` | real committed index | one-over limits, entry/mid-scan/aggregation cancellation |
| I11 | `pr10_pruning::t49..t53` | multi-segment index with disjoint time bounds | boundary, unknown bounds, `And` vs `Or`/`Not`, on/off differential |
| I12 | `pr10_integration::t54..t57` | real compaction/reopen | delete before compact, late arrival, reversed insert order |
| I13 | `pr10_integration::t59..t61` | real BM25 searcher + segment bytes | unsupported operator, BM25 unchanged, deterministic bytes |
| I14 | `pr10_properties::t62,t63` | real `MemoryDirectory` and `FsDirectory` | memory/fs parity, corrupt committed segment |

## Deterministic oracle

`pr10_properties::t64_seeded_oracle` runs seeds `0`, `1`, `0x5EED`, `0xC0FFEE` with
250 upsert/delete operations each. It uses `ModelIndex` (an independent
`BTreeMap` model with revisions) and primitive `i64` comparisons — never the
production comparator, `encode_group_key` or aggregation engine. It compares the
sorted range-hit key sequence, the pruning-on/off key sequence, and exact
per-host `Count` groups.
