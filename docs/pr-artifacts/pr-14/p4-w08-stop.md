# PR 14 — W08 STOP: cache eviction/reload cannot be constructed through supported public APIs

Status: **BLOCKED — architectural STOP** (per the P4 plan §18 and the W08
instruction). No production cache/search/storage change was made.

## Exact ownership/lifetime constraint

1. `crates/quervant-core/src/remote/mod.rs`
   - `struct Hydrated { pins: Vec<PinnedSegment>, .. }` materializes **every**
     manifest segment through `cache.prepare_remote(..)` and collects one pin per
     segment (`pins.push(pin)`, around line 670).
   - `pub struct RemoteIndex<S> { .., _pins: Vec<PinnedSegment>, _cache: SegmentCache<..>, .. }`
     moves the whole pin vector into the index handle (line 188).
   - The pins are private and released only by `PinnedSegment::Drop` when the
     **entire** `RemoteIndex` is dropped. There is no public method to release a
     single segment's pin, to keep one segment pinned while unpinning another, or
     to re-attach a pin lease to a snapshot.
2. The internal `SegmentCache` (`_cache`) is private. `RemoteIndex` exposes only
   `snapshot()`, `pin()`, `generation()` and `transfer_stats()` (lines 196–215);
   there is no `cache_stats()` accessor. `TransferStats` exposes HTTP
   requests/bytes/retries/ranges/peak, **not** `CacheStats::evictions`,
   `misses`, `hits` or `physical_bytes`.
3. `SegmentCache::prepare_remote` is `pub(crate)`
   (`crates/quervant-core/src/storage/cache.rs:896`), so an external integration
   test cannot drive the same cache instance that a `RemoteIndex` uses.

## Consequence

The required W08 sequence — materialize A, release **A's** pins while other
segments remain pinned, materialize B and assert LRU eviction via
`CacheStats.evictions`, then re-access A through the same cache and prove a
verified re-fetch — cannot be expressed with the supported public API. Dropping
the whole `RemoteIndex` releases all pins (not A specifically) and destroys the
cache handle; a new `RemoteIndex` creates a new cache instance with no shareable
`CacheStats`. Constructing the sequence would require either:

- a public per-segment pin/release or snapshot-scoped cache handle, or
- a public `cache_stats()` (and explicit unpin) on `RemoteIndex`, or
- exposing `prepare_remote`/`SegmentCache` ownership to tests.

All three are production API/ownership changes made solely to satisfy a
benchmark, which the W08 instruction and P4 plan forbid. Manipulating private
accounting, deleting cache files externally, or bypassing pins is also forbidden.

## Smallest decision required for architectural review

Approve one of:
1. Expose a read-only `RemoteIndex::cache_stats()` plus a documented way to
   release unpinned snapshot pins (production API addition), or
2. Accept W08 as **not applicable** for the current snapshot-lifetime pin model
   and remove it from P4 acceptance, or
3. Provide a supported multi-snapshot/cache-owner API where one reader can share
   a bounded cache with another snapshot.

Until one is approved, W08/B03 remain unqualified and **P4 is NOT ACCEPTED**.
No weaker test is substituted.

## Unaffected evidence
R01–R15 storage verticals, F01–F10 real-provider faults (10 iterations each),
and W01–W07/W09 three-trial qualification remain green and unchanged.
