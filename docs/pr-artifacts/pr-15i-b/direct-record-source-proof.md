# PR 15I-B direct-record — source proof

- Branch: `dev/pr15i-b-stored-blocks`
- `P0_SHA`: `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb`
- Historical rejected LZ4 source: `bfdb9b0d95de171c72be1de26e4501fc701df988`
- Common direct-record source (`DIRECT_COMMON_LZ4_SHA`): `67d75b58a17e2d99bb689adccbf9bdfd304bfb55`
- `B_LZ4_DIRECT_SHA`: `7f5b1f7a337920af17299d6213ff990e2e09a482`
- `B_ZSTD_DIRECT_SHA`: `71d92f909791a2079536fe527f0c70ec14c33307`
- Rollback / final code HEAD: `7b423fc17d1c888bccf2be97749bb8de73be1556`
- Frozen protocol SHA-256: `3a63d5b8f208ed15921c3200aaa00e940e7aa30697b1805cd7ce2fa0d86d523a`

## Restoration and change scope

Only the preapproved §3.1 source paths were restored from `bfdb9b0`; two
restored `let`-chains were rewritten as nested `if let` for Rust 1.85.
The direct-record change is limited to:

- `segment/stored_blocks.rs`: flat boundary capture during full validation and
  `decode_selected_with_offsets` (touched-block-only inflation, selected-slice
  decoding, checked block-index lookup);
- `segment/reader.rs`: `record_ends` in the shared certificate, metered
  allowance/charge-before-allocate, certified dispatch;
- `segment/stored.rs`: test-only hot-block/record observation counters.

The 22-byte header, 40-byte directory entry, `block_docs=128`, feature
`(0x000D,1)`, v1 block bodies, producers, segment ids and digests are unchanged.
`git diff --name-only 67d75b5 71d92f9` is exactly `Cargo.lock` and
`crates/quervant-core/Cargo.toml` (the Zstd-only candidate switch).

After both codecs failed, the rollback restored production/Cargo/CI exactly to
P0: `git diff 0cf7dec 7b423fc -- crates/quervant-core/src
crates/quervant-core/Cargo.toml Cargo.lock .github/workflows/ci.yml` is empty.
