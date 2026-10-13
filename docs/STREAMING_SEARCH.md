# Streaming search and composable result pipelines — architecture commitment

**Status:** approved design direction; not an implemented feature or a frozen public API. Applies to standalone `quervant-core` and later distributed execution. This is general-purpose search infrastructure, not a security-only feature.

## Goal and boundaries

Quervant must be capable of producing matching documents incrementally in bounded batches, without materializing the complete result set before delivering the first batch when the query plan permits streaming. This supports interactive log/event exploration, CLI exports, browser filtering and future Unix-like result pipelines (`grep`, `grep -v`, `head`, `tail`, `sort`, `uniq`, `count`, grouped analytics). Streaming transport and a pipeline-language parser are separate concerns.

Three capabilities must remain distinct:
1. **Engine result production:** a pull-based, bounded result cursor/batch interface in `quervant-core`.
2. **Transport streaming:** a server adapter maps batches to an incremental wire protocol, preserving cancellation/backpressure.
3. **Client pipelines:** a CLI/UI consumes records incrementally and may filter, display, or transform them; where possible, server-side predicate pushdown avoids shipping irrelevant records.

## Core execution contract

- Provide a conceptual `next_batch(max_results)` / cursor interface; precise Rust types, async boundary and lifetime/ownership are deferred to the owning implementation PR. Never require a distributed coordinator or a network runtime in `quervant-core`.
- Each batch and its stored-field projection must have explicit maximum rows/bytes and query-wide CPU, I/O, memory, timeout and output budgets. A consumer that stops requesting batches must stop upstream production rather than accumulate an unbounded queue.
- Support cancellation propagation through segment iteration, predicate evaluation, stored-field materialization and, later, remote I/O. No blocking executor work or unbounded prefetch.
- Bind results to a reader/PIT snapshot and respect live-doc visibility, mutations, expiry and retention. A long-lived stream must not silently switch generations.
- Distinguish a stream's **encounter order** (not a semantic sort) from an explicitly requested deterministic sort. PIT-bound pagination/search-after must use complete sort keys and stable tie-breaking; a streaming cursor is not interchangeable with a resumable pagination token.
- Errors and budget exhaustion must be explicit. If some rows were already emitted, the transport must report a terminal error/partial status, never present an incomplete stream as a successful complete answer. Counts/aggregations must not silently truncate.
- Preserve ability to push indexed predicates and projections into server-side execution. Client-side `grep` is a post-filter over received results, not a substitute for index evaluation.

## Operator semantics

| Operator | Streamability | Correctness requirement |
| --- | --- | --- |
| `grep`, `grep -v`, field predicate, projection | Streaming | Per-record bounded evaluation; preserve input order where applicable. |
| `head N` | Streaming | Return first N **in the defined input order**, cancel upstream when satisfied. Without explicit sort, not necessarily newest/top-scored. |
| `tail N` | Bounded state | Keep last N in the defined order; final result requires end of input. |
| `uniq` | Conditional | Adjacent dedup streams; global distinct requires bounded state or a sorted strategy. |
| `count`, `sum`, `min`, `max` | Incremental state | Exact final value only after input completes; progress values must be labeled provisional. |
| `sort`, exact global `top K`, global `group by` | Potentially blocking | May need full scan and/or bounded aggregation state; early results only if correctness is provable from index order/algorithm. Explicit error when budgets insufficient. |

A request such as `search level:error | head 100` is not equivalent to `search level:error | sort timestamp desc | head 100`. Do not emit a purported globally sorted/top-K answer prematurely. Streaming means bounded production, **not** guaranteed low time-to-first-result for every query.

## Segment/format implications — PR 5 gate

PR 5 must preserve segment-local bounded iteration over candidate document IDs/postings, stored-source/selected-field retrieval, and typed columnar access sufficient for incremental projection/filtering. Segment doc-ID remapping and physical timestamp ordering must remain correct; format metadata should identify ordering and conservative bounds, without assuming every segment is sorted. Avoid APIs that force whole-result or whole-source-document materialization as the only access path. Do not add wire formats, UI pipeline syntax or speculative new on-disk features solely for streaming.

## Ownership and milestones

- **PR 5:** preserve codec/read-access primitives and document these constraints before format freeze.
- **PR 6:** reader/PIT lifecycle, cancellation/lease and snapshot ownership compatible with long-lived bounded cursors.
- **PR 7–12:** segment-local incremental iteration where feasible; explicit blocking/budgeted operators for ranking, sorting and analytics.
- **PR 13:** remote I/O honors backpressure, bounded prefetch and cancellation without changing standalone core contracts.
- **PR 14:** define and implement initial bounded, pull-based result cursor/batch execution, composition and deterministic ordering semantics, subject to approved detailed plan.
- **PR 15:** qualify streaming correctness, cancellation, memory/backpressure bounds and time-to-first-batch against representative workloads.
- **Future transport/UI:** NDJSON over HTTP is a candidate initial transport, not an approved protocol requirement; WebSocket/gRPC are alternatives. UI/CLI Unix-like pipes and greps are a future product capability, not v0.1 delivery promises. Distributed query aggregation must preserve bounded flow control and global-order correctness.

## Acceptance scenarios for owning PRs

1. A selective query yields a first bounded batch before complete result enumeration; memory remains bounded under a slow consumer.
2. Early `head N` stops upstream work; cancellation releases PIT/segment/cache leases.
3. Sorted timestamp-descending `head N` returns the correct global N despite out-of-order segments and ties; no premature incorrect rows.
4. Snapshot-consistent results across refresh, deletes, merges and PIT expiration, with explicit expiration error.
5. Exact count/group-by reports terminal success only after completion; budget exhaustion produces a typed error, not a silently truncated answer.
6. Mid-stream backend failure produces an explicit terminal failure/partial status.
7. Client `grep` filters only transmitted records; equivalent indexed server predicate produces correct matches with reduced transfer when selective.
8. Local and ObjectStore-backed execution produce equivalent results, with bounded remote prefetch.

This document establishes architecture constraints; it does not assert that PR 3 implements query streaming.
