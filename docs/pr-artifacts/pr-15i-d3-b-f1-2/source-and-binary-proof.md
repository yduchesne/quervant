# PR 15I-D3-B-F1.2 — source and binary proof

## Source identities

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| BASE `unified.rs` | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Candidate `unified.rs` | `493f93825e77581833a26c6436c5ea35aed26fc453eb2cbcec80733710ec183c` |
| Final production source (after rollback) | `bb7a1035…`; `git diff 39dbd9f5… -- crates/quervant-core/src/search/unified.rs` empty |
| Rollback commit | `5d3bf1f7b1bb87f374d355fece579e84ad3d0ec2` (additive; no history rewrite) |

No Cargo, corpus, oracle, adapter, codec or index-format change was made at any
point. The D3-B integration test file `crates/quervant-core/tests/pr15i_d3_b.rs`
passes against BASE and was retained.

## Canonical builds (one path per campaign, two real builds)

| Campaign | Arm | Source | Binary SHA-256 | Bytes |
|---|---|---|---|---|
| `d3bf12-base-aa-01` | A | BASE | `e6363c866b2f70e22e391cd276a499de57d609b17fca63c8e71d0a82b36166b7` | 4,479,112 |
| `d3bf12-base-aa-01` | B | BASE | `e6363c866b2f70e22e391cd276a499de57d609b17fca63c8e71d0a82b36166b7` | 4,479,112 |
| `d3bf12-base-01` | A | BASE | `9f3d1afebe3f222b97f80e64b030b3e14fe8c7f8a925127e2e6c460dad86f9b0` | 4,479,072 |
| `d3bf12-base-01` | B | candidate | `c5cceb191d4ff2d333058862a6f916c77d89cd12a06a51fbdda961dcdff0fe61` | 4,490,664 |

Both campaigns used `<campaign>/compile-source` as the single canonical absolute
path, independent `build/A` and `build/B` target directories,
`cargo build --release --locked`, and a pre/post source proof (detached HEAD,
clean tree, HEAD, `unified.rs` Git blob and on-disk bytes, all six frozen PR15D
inputs and the adapter lock). A/B switched the same path with
`git switch --detach` only after arm A was built. Binaries were rehashed before
and after timed acquisition (`pre_timing_snapshot == post_timing_snapshot`).

## Indexes and oracle

Both campaigns produced byte-identical indexes across arms: 100K committed
15,747,551 bytes, STORED 1,661,455 bytes, digest
`5734ae60591f7563…`. The verifier regenerated the frozen PR15D corpus and
confirmed every lane's exact hit counts and document IDs. No sentinel differed.

## Historical preservation

- D3-B T0 (`155ebafa…`), F1 T1 (`ac45c23f…`) and F1.1 T2 (`63b30a0b…`): all
  `git diff --exit-code` empty after the complete run.
- F1.1 original control and paired evidence: inventory SHA-256 unchanged before
  and after the rehearsal (`d5511aec…`-class content); no receipt or archive was
  added to them.
- Historical D3-B and F1.1 archives retain their pinned SHA-256.
- The pre-existing uncommitted `disk-cleanup.sh` change was preserved untouched.
