# PR 14 — Baseline inventory

- Base commit: `7ca1b2ec59fec648602e0e4a52e8f903a596f106` (`main`, branch `dev/pagination`)
- Working tree: modified (uncommitted) at time of writing
- Toolchains: `rustc 1.98.1`, `cargo 1.98.1`, `cargo +1.85.0` (MSRV), `cargo-llvm-cov 0.9.1`
- Workspace members: `quervant-core` (Apache-2.0), `quervant-objectstore` (Apache-2.0), `quervant-distributed` (Elastic-2.0)

## Revalidated APIs at this HEAD

| Area | File | Verified contract |
|---|---|---|
| Query AST | `crates/quervant-core/src/contract/query.rs` | `Query` with lexical, `Range`/`TimeRange`, `Exists`/`Missing`/`IsNull`, `In`/`NotIn`, `Ip*`, `JsonPath*`, geo and Boolean variants. `ConcreteJsonPath`, `JsonPathExpr`, `Bound<T>`. |
| Result contracts | `contract/result.rs` | `Sort`, `SortField`, `Projection::{Source,Fields}`, `TopK`, `PitId`, `Cursor`. `Cursor` carries pit/sort/last key **without** the complete sort tuple. |
| Batch contracts | `contract/batch.rs` | `QueryRequest`, `BatchQueryRequest`, `BatchQueryResponse`, `PerQueryOutcome` — shapes/validation only, no executor. |
| Aggregation contracts | `contract/aggregation.rs` | `Aggregation`, `Aggregate`, `GroupBy`, `ExactDistinct`, `TopKFrequency`, `TimeBucket` (width only). |
| Lexical engine | `search/plan.rs`, `search/execute.rs` | Private `CompiledQuery`/`CompiledNode`, postings-based BM25 top-K, exact totals, resource ledgers. Unsupported operators fail closed. |
| Typed/analytics engine | `search/typed.rs`, `search/analytics.rs` | `TypedSearcher::{search,aggregate}`, `TypedCursor`, typed `CompiledQuery` (before PR 14: `MatchAll`, `Range`, `TimeRange`, `JsonExists`, `JsonEquals`, geo, Boolean), exact `AggregationEngine`. |
| Stored source | `segment/stored.rs` | `StoredRecord`, `encode_stored`, `decode_stored`; `SegmentReader::{stored, stored_doc, doc_keys, doc_key}`. |
| JSON paths | `segment/json_paths.rs` | Immutable indexed path/leaf-value section; concrete paths, wildcard existence, exact scalar equality; bounded DFS extraction. |
| Snapshot/PIT | `index/snapshot.rs` | `ReaderSnapshot::{binding_id, generation, view_ordinal, effective_live_docs, open_segment_reader}`. |

## Pre-PR-14 gaps confirmed

- `TypedSearcher` did not execute `Exists`, `Missing`, `IsNull`, `In`, `NotIn`, `IpExact`, `IpRange`, `IpInCidr`, `IpNotInCidr`.
- No JSON path range, scalar-array membership or indexed-path sort.
- No stored-source projection API.
- No `contract::aggregation::Aggregation` → `AggregateRequest` adapter.
- No batch executor.

## Notable pre-existing items

- `docs/TESTING.md` contains 4 stray `<<<<<<< HEAD` lines (lines 56–59) with no matching `=======`/`>>>>>>>`. Left unchanged; recorded as a pre-existing documentation defect unrelated to PR 14 code.
