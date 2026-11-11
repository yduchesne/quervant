# PR 15I-D1-F C2 — correctness evidence

Executed on the measured F2 commit
`b328b83cdb6ea53af08b7591a0c1bd6128ba0dcf` before its performance
rejection. The final tree restores both production files byte-for-byte to BASE
and removes the C2-only test file.

## Scope of the measured diff

`git diff BASE F2 -- crates/` contains exactly:

- `crates/quervant-core/src/search/unified.rs`
- `crates/quervant-core/src/segment/reader.rs`
- `crates/quervant-core/tests/pr15i_d1_f_keys.rs` (new test file)

No `Cargo.*`, `execute.rs`, `score.rs`, `snapshot.rs`, `column.rs`, `.github/`
or public-contract change. The F2 source contains **none** of the rejected C1
symbols (`RetainedKeyFingerprintIndex`, `retained_key_exists`,
`key_fingerprint`, index maintenance helpers, test seams); the controller's
source guard and a direct source grep both returned empty.

## Reader tests (K01–K05, executed)

| Test | Requirement | Result |
|---|---|---|
| `d1f_k01_k02_k03_doc_key_view_borrows_validated_offsets` | first/middle/last view equals `doc_key`; same-snapshot readers share the offset pointer; the view never populates/replaces the query-local decoded-key cache | PASS |
| `d1f_k02_distinct_snapshots_do_not_share_offset_directories` | distinct snapshots have distinct offset directories; both views are exact | PASS |
| `d1f_k04_missing_or_zero_budget_returns_none_and_owns_via_legacy` | no/zero metadata budget ⇒ `Ok(None)`; existing `doc_key()` still returns the key | PASS |
| `d1f_k05_out_of_range_and_corrupt_doc_keys_are_typed` | out-of-range ⇒ typed `Corrupt`, never `None`; corrupted DOC_KEYS ⇒ view `None` then authoritative `doc_key()` reports `InvalidUtf8` | PASS |

## Search unit tests (K06–K09, executed)

| Test | Requirement | Result |
|---|---|---|
| `d1f_k06_k07_losing_candidates_never_own_a_key` | 1,000 hits, K=1/10/100: every candidate is borrowed (≥1,000 borrowed reads) and only the retained K+1 heap entries own a key; no legacy fallback | PASS |
| `d1f_k07_replacements_own_exactly_one_key_per_admission` | reverse physical order forces 1,000 replacements; exactly one owned key per admission (no fixed K+1 assumption) | PASS |
| `d1f_k07_borrowed_and_ineligible_owned_paths_match_exactly` | eligible borrowed path vs ineligible mixed query: identical keys, total hits, score bits and projection | PASS |
| `d1f_k07_k10_and_cursor_match_owned_reference` | K=10 and 7-hit cursor pages equal the expected order | PASS |
| `d1f_k09_candidate_key_ownership_contract` | Owned reuses; Borrowed allocates once; invalid borrowed content maps to typed `CorruptIndex` | PASS |

## Real public-path integration tests (K09–K16, executed)

`cargo test -p quervant-core --all-features --test pr15i_d1_f_keys` — 5/5 PASS
against real `FsDirectory` indexes (writer → commit → reopen → search):

- K boundaries 1/10/31/32/100/128/129 over two segments, exact keys and equal
  score bits (`d1f_k09_k13_k16...`);
- Keyword-sort equal values, missing-last, ASC/DESC and cursor pages
  (`d1f_k11...`);
- typed/mixed/relevance ineligible shapes, `ResourceLimit`, `Cancelled`
  (`d1f_k10_k12...`);
- update/delete masks, PIT generation isolation, reopen parity
  (`d1f_k13_k14...`);
- public writer rejects duplicate live keys; multi-segment unique keys do not
  trigger the retained-duplicate error (`d1f_k08...`).

`cargo test -p quervant-core --all-features` passed entirely; formatting and
Clippy (`-D warnings`) were clean at F2.

## K08 residual risk

A duplicate retained key cannot be injected through the public writer without
corrupting immutable committed bytes. The literal duplicate predicate
`heap.iter().any(|existing| existing.hit.key.as_str() == key.as_str())` is
unchanged and executes at the same position after view validation and charge;
the existing segment-corruption suites still fail closed. No synthetic
duplicate state was manufactured through a public snapshot. This residual risk
remains open for independent review.

## K15

Real RustFS suites were not run (no service/container; `RUSTFS_PENDING`).
