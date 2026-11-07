# PR 15H-E — correctness verification

Candidate: `72b18e249f2a83b77fd2faaf05deb6f0d60eaad6`
Pre-E baseline / tooling: `eb6ed9170308965987a35211d227431535a41ecb`

## Contract under test

- Dictionary payload v2 is `u16 version=2`, `u32 field_count`, then ascending
  `u32 field_id`/`u64 term_count` and ascending terms as `u16 len`, UTF-8 bytes,
  then canonical LEB128 `doc_freq`, `postings_offset`, `postings_length`.
- A v2 dictionary requires required feature `(0x000C, 1)`; v1 must not carry it;
  a missing dictionary must not carry it. Mismatches are typed `Corrupt`.
- Both `SegmentBuilder` and compaction emit v2+feature; the reader still accepts
  v1 and the frozen v1 golden segment.

## Test evidence

| Scope | Command | Result |
|---|---|---|
| v2 codec unit matrix (E-U01–U05, U11–U14, U16–U18) | `cargo test -p quervant-core --lib segment::dictionary::e_v2_tests` | 5 passed, 0 failed |
| Producer/feature matrix (E-U06–U09, U23, U26) | `cargo test -p quervant-core --test pr15h_e_compact_dictionary` | 3 passed, 0 failed |
| Existing v1 golden fixture | `cargo test -p quervant-core --test segment_golden` | 2 passed, 1 ignored |
| Existing format regression suite | `cargo test -p quervant-core --test pr08_integration` | 8 passed |
| Existing merge/compaction suite | `cargo test -p quervant-core --test pr09_merge` | 6 passed |
| Full workspace, all targets (stable and 1.85.0) | `cargo test --workspace --all-targets` | PASS — 2,339 passed, 0 failed, 12 ignored |
| Full workspace, all features (stable and 1.85.0) | `cargo test --workspace --all-targets --all-features` | PASS — 2,343 passed, 0 failed, 81 ignored |
| Real pinned RustFS, v2 cold bootstrap and remote lifecycle | `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | 3 passed |
| Real pinned RustFS, format-aware cold/miss/present lanes | `pr15g_{a,b,c,d}_rustfs -- --ignored` | 1 passed each |
| Real pinned RustFS, crash/recovery | `cargo test -p quervant-core --all-features --test pr13_crash_rustfs -- --ignored --test-threads=1` | 6 passed |
| Real pinned RustFS, adapter conditional/ranged/oversize | `cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1` | 8 passed |

The v2 tests cover exact hand-authored wire bytes, empty dictionaries, 1/127/128/
`u64::MAX` varint boundaries, v1/v2 logical equality, version `0`/`3`, truncated
and noncanonical varints, trailing bytes, zero `doc_freq`, empty/bad UTF-8 terms,
duplicate and unsorted terms, and the feature/payload matrix. Existing suites
cover malformed unselected data, budgets/retained bytes, query/score/order,
v1 golden reading and compaction survival counts/revisions/tombstones.

## Real RustFS topology

Pinned `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
under local podman, endpoint `http://127.0.0.1:19000`, disposable credentials,
unique bucket per run. The candidate worktree `72b18e2` built and uploaded v2
segments through the production adapter, then cold-opened them with a fresh
reader and empty cache. Crashing/restart, ranged transfer and stale-writer
rejection all passed. A separate v1-object RustFS fixture was not constructed;
v1 readability is covered by the frozen golden segment locally, and the remote
cache path is format-agnostic. This is disclosed for the rejection record, not
used to claim a keep.

## Known test-expectation update

`pr08_integration`'s known-required-feature list now includes
`FEATURE_COMPACT_DICTIONARY`. `pr09_merge` no longer asserts a fixed physical
doc order after compaction: merge output is ordered by content-addressed segment
id, so the v2 bytes legitimately change that order. The test now asserts the
surviving keys and their stored/column values, which is the semantic invariant;
logical query results and exact hit sets are unchanged. No v1 golden fixture was
edited.

## Verdict

Correctness: **PASS** for the candidate. The candidate was nevertheless rejected
on storage gates; see `decision.md`.
