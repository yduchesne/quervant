# PR 15E Phase 5 — design and decisions (as executed)

**Authorization:** maintainer-approved Phase 5 plan (selective DOC_KEYS decoding for
singleton hits), executed on existing PR #83. One optimization; no Phase 6 work.

## 1. Approved decision and implementation

| Decision | Implementation |
|---|---|
| Optimize only a segment with **exactly one** selected hit and **≥ 1,024** physical docs | Per-site predicates: `collect_mixed` uses `scored.len() == 1 && reader.doc_count() >= 1024`; `project_selected_hits` uses `indices.len() == 1 && reader.doc_count() >= 1024` |
| Consume the existing DOC_KEYS v1 section with the same validation, owning only the selected key | `segment/reader.rs::decode_doc_key_selected` mirrors the full decoder's ordered framing/count/limit/`count_min_bytes` checks, validates every key's UTF-8 and constructor rules without allocating unselected strings, owns one key, scans to `expect_end` |
| Query-local accessor that never installs the full cache | `pub(crate) doc_key_selected` clones from an existing full cache or runs the single scan; public `doc_key`/`doc_keys` byte-identical |
| No new cache, index, offset table, format, API, scorer, stats or work-meter change | none added; `score.rs`, `work.rs`, `execute.rs`, `projection.rs`, `segment/format.rs`, `segment/value.rs`, `segment/stored.rs`, index/storage, manifests and CI untouched |

## 2. Why this and not statistics caching

The Phase 4 review suggested investigating `compute_stats`, but source inspection showed a
directly demonstrated remaining allocation: `doc_key()` → `doc_keys()` decodes every physical
key in the segment on each new query-local reader, and a one-hit query can call it twice
(hit collection and projection). PR15E-A historically attributed 5.4M allocations to
`decode_doc_keys` on the 100K rare capture — motivation, not attribution. Phase 5 removes the
allocation for the singleton shape only.

## 3. Deliberate non-goals

* No fast path for 2+ hits (that would be O(N×hits) without a new index design).
* No threshold tuning beyond the fixed 1,024-document rule.
* No full-key cache, verified-state or snapshot mutation; no stats caching; no format change.
* No change to cancellation polling inside the codec (the existing contract polls at the
  query layer), and the declared `SegmentLimits` checks remain authoritative.

## 4. Recorded notes

| Item | Note |
|---|---|
| Allocation-only admissibility | The fast path avoids the full `Vec<DocumentKey>` allocation but preserves every declared `SegmentLimits` check and typed corruption validation; no published cap was relaxed |
| Test-only witnesses | `#[cfg(test)]` cache-occupancy and owned-key counters in `segment/reader.rs`; compiled out of production and benchmark builds; no production counters or logging |
| Corruption injection | Tests rebuild a checksum-valid container with a patched DOC_KEYS body so the codec (not the digest) rejects the input |
| Unit-test placement | Codec/reader tests live in the existing `segment/tests.rs` `phase5` module; the query-level key-parity test lives in `unified.rs`'s existing test module (in-crate `SelectedHit` access). Both are test-only |
