# PR 10 Preflight — typed numeric/temporal retrieval and bounded analytics

**Status:** pre-implementation artifact. **Base:** `main` at merge commit
`2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7` (PR #28 follow-up docs).
**Working branch:** `dev/temporal-retrieval` (the plan suggested
`dev/typed-temporal-analytics`; the existing branch name is retained).
**Plan version:** 2026-10-14. Workspace `rust-version` is 1.85; stable toolchain
is installed alongside `+1.85.0`.

## 1. Working tree and baseline

- `git status`: clean.
- `git rev-parse HEAD`: `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`.
- Branch: `dev/temporal-retrieval`.
- Workspace members: `quervant-core`, `quervant-objectstore`,
  `quervant-distributed` (the last is a stub).

A fresh baseline `cargo test --workspace --all-targets` run is recorded in the
final validation report. PR 9 (merge commit `16a7771` lineage, head `b8c63f9`
per the roadmap) is already merged.

## 2. Inspected paths and reconciled contracts

| Path | Reconciled facts |
|---|---|
| `contract/query.rs` | `Query::{MatchAll,Range,TimeRange,And,Or,Not}` already exist. `Query::validate(schema,budgets)` validates shape/type/depth but **not** columnarity. `Range` accepts any numeric/Timestamp field. `TimeRange` requires `Timestamp` and rejects `start > end`; `start == end` is accepted (matches none). `Bound::{Unbounded,Included,Excluded}`. `address_cmp` orders `(family, bits)`, IPv4 (0) before IPv6 (1). |
| `contract/result.rs` | `Sort`, `SortField`, `SortDirection`, `MissingValuePosition`, `MultiValueSelector`, `TopK`, `PitId`, `Cursor`. Existing `Cursor` carries PIT + sort + **last key** + expiry, no last sort tuple → left untouched. `TopK` validates against `BudgetKind::ResultWindow`. |
| `contract/value.rs` | `Timestamp` signed micros `i64`; `FieldValue::{Text,Keyword,Bool,I64,U64,F64,Timestamp,Json,GeoPoint,Ip,Cidr}`; `FieldValue::validate` rejects non-finite `F64`. |
| `contract/schema.rs` | `Schema::primary_timestamp() -> Option<&str>` already persisted (single, indexed, `Timestamp`). **No persistent format change required.** |
| `contract/budget.rs` | `BudgetKind::{JsonDepth,QueryDepth,Fields,ArrayElements,DocumentBytes,ResultWindow,Groups,GroupKeyFields,GroupExpansions,DistinctKeys,TermExpansion,MemoryBytes,Elapsed,ResponseBytes,...}`. `checked_product` rejects overflow. |
| `contract/aggregation.rs` | Existing *contract-only* aggregation shapes. PR 10 introduces its own execution request/response types (`AggregateRequest`, etc.) and does not change this contract module. `group_expansion_count` semantics (empty key contributes 0) are mirrored. |
| `search/mod.rs` | `LexicalSearcher::search` intact. `search/*` private modules; `pub use error::{SearchError,SearchResult}; pub use limits::SearchLimits`. |
| `search/limits.rs` | `SearchLimits` is a `Copy` struct with published defaults and per-field hard ceilings; over-ceiling is a typed `SearchError::ResourceLimit`, never a clamp. Extended additively by PR 10. |
| `search/error.rs` | `SearchError::{Query,Analysis,Segment,Index,UnsupportedOperator,ResourceLimit,Cancelled,CorruptIndex,InvalidScore}`. Reused; new behavior uses existing variants. |
| `index/snapshot.rs` | `ReaderSnapshot::open_segment_reader(index) -> GuardedSegmentReader`; `effective_live_docs(index,&reader)` and `live_mask(index)` are `pub(crate)` and already intersect the segment live bitmap with the PR 9 generation mask. Arc clones of a snapshot need a stable identity for cursors. |
| `index/visibility.rs` | PR 9 effective-live masks are the mandatory liveness source. Physical bitmaps alone are never sufficient. |
| `segment/reader.rs` | `SegmentReader::{doc_count,live_docs,doc_key,column_value,time_bounds,schema}`. `column_value(field_id,doc_id)` reopens a bounded `ColumnReader` per call; no wire change. |
| `segment/column.rs` | `encode_group_key(&[GroupComponent])` canonical and collision-free; `GroupComponent::{Missing(FieldType),Null(FieldType),Value(&FieldValue)}`; `EMPTY_MULTI` expands to zero groups. |
| `segment/bounds.rs` | `TimeBounds::prunes_positive_range(start,end)` is conservative (see §4). |

## 3. Snapshot identity

`ReaderSnapshot` did not carry a process-wide unique identity. Cursors must bind
to a snapshot instance, and generation/view are not unique across handles. PR 10
adds a read-only **monotonically allocated `binding_id`** to `ReaderSnapshot`
(`static AtomicU64`), shared by `Arc` clones. This is the only snapshot change.

## 4. Conservative-pruning proof (`prunes_positive_range`)

For half-open `[start,end)` on a `Timestamp` field:

- `known == false` or `presence == PRESENCE_UNKNOWN` → `false` (scan).
- `present_count == 0` → `true`; missing/null never satisfies a positive range.
- Else prune iff `max_micros < start` (every value is below the window) or
  `min_micros >= end` (every value is at/above the exclusive upper bound).

PR 9 tombstones/upserts can only remove documents from a generation. A deleted
extreme value leaves the persisted bound *wider* than the effective live set, so
the direction of the inequality remains safe (no false negatives). The bound
`field_id` must equal the queried `TimeRange` field's codec id; a mismatch
disables pruning. **Go.**

## 5. Canonical scalar ordering (Go, newly defined here)

No shared comparator existed. PR 10 defines and tests a single canonical order
(`search/typed_compare.rs`), consistent with `contract::query::address_cmp`:

| Type | Order |
|---|---|
| `Bool` | `false < true` |
| `I64` | signed numeric |
| `U64` | unsigned numeric |
| `F64` | finite total order (non-finite rejected) |
| `Timestamp` | signed microseconds |
| `Keyword` | unsigned UTF-8 bytes (`str` byte order) |
| `IpAddress` | `(family, bits)`, IPv4 < IPv6 |

`Text`, `Json`, `GeoPoint`, `Cidr` are not sortable/groupable/metric scalars for
PR 10 and fail closed.

## 6. STOP-gate decision

| Gate | Result |
|---|---|
| Float/IP/type semantics conflict with plan §3 | No conflict. Go. |
| Persisted time bounds can false-negative | No. Go. |
| PR 9 live masks exposable read-only | Yes (`pub(crate)` accessors). Go. |
| Primary timestamp requires codec changes | No, already persisted. Go. |
| Cursor snapshot identity impossible | Solved with monotonic `binding_id`. Go. |
| Exact metrics require unbounded/approximate state | No; exact with per-group bounds. Go. |
| Existing validation/budget contract contradicts plan | No. Go. |
| Wire/CURRENT/merge/BM25 change necessary | No. Go. |
| Real boundary harness runnable | Yes (MemoryDirectory/FsDirectory). Go. |

**Decision: GO.**
