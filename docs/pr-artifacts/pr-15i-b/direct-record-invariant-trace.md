# PR 15I-B direct-record — invariant traceability

| Invariant | Meaning | Tests |
|---|---|---|
| V-01 | `record_ends` belongs only to the exact verified bytes/schema/limits | DR-U27, DR-U38, DR-I11 |
| V-02 | Certificate published atomically after all blocks + charge | DR-U14, DR-U36, DR-U37 |
| V-03 | Certified selected read inflates touched blocks and parses only selected records | DR-U09–U13, DR-U40, DR-I07/08 |
| V-04 | No certificate/zero budget uses full validation every request | DR-U28–U30, DR-F01 |
| V-05 | Selected/unselected corruption detected at first certification | DR-U25, DR-U26, DR-U41, DR-F13 |

## Paper counterexamples (pre-implementation)

(a) **Wrong `+b` indexing.** For N=129, B=2: block 1 starts at flat index
`128 + 1 = 129`; using `128` would read block 0's terminal offset as block 1's
first boundary, giving `boundaries[0] != 10` → typed `Corrupt`.
(b) **Missing terminal for 129 docs.** Flat length must be `129+2=131`; a table
of 130 entries fails `len == N+B` and the last block's `len == doc_count+1`.
(c) **Out-of-range local ID.** `doc_id >= first+doc_count` is rejected before
slice lookup; a forged offset slice cannot satisfy the count check.
(d) **Duplicate/descending IDs.** Rejected with the existing
`stored selection` typed error before certificate work or decompression.
(e) **Unselected JSON corruption with recomputed envelope digest.** The first
selected access validates all blocks; the v1 scanner returns the same typed
semantic error and no certificate is published.
(f) **Metadata cap one byte low.** `MetadataMeter::reserve` is attempted before
parsing; `LimitExceeded` → `Ok(false)` → fully validating uncached path.
(g) **Invalid compressed length.** Bounded `decompress_block` rejects before
allocation and no certificate is published.
(h) **Different verified state/bytes.** The certificate lives in
`OnceLock`/`Mutex` inside one `Arc<VerifiedSegmentState>`; a new state starts
empty and cannot observe the old pointer.
(i) **Initializer panic.** The mutex is poisoned; no certificate is published and
retry returns a typed corruption/lock error.
(j) **Accidental O(N) hot scan.** The hot path computes
`block_index = doc_id/128` and indexes `parsed.entries[block_index]`; it never
loops the directory. Counter DR-U40 fails if any block-count-scale loop or
128-record scan is observed.
