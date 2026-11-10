# PR 15I-D0 lockfix-01 — diagnostic source proof

## 1. Derivative identity

The instrumented scratch tree is materialized from `COMPAT_BASE` only. It changes
exactly six paths:

```text
crates/quervant-core/Cargo.toml
crates/quervant-core/src/search/mod.rs
crates/quervant-core/src/search/d0_probe.rs     (new, scratch only)
crates/quervant-core/src/search/unified.rs
crates/quervant-core/src/search/execute.rs
benchmarks/pr15d/adapters/quervant/src/main.rs
```

| Item | Value |
|---|---|
| BASE / checkout head | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |
| Derivative fingerprint | `09d7b8cda7229223ea123d45eec12f2d5f7c8c64afeb0043fc1ac0511ee275d6` |
| Source-derivation SHA-256 | `995a6645ec8be9ae3ba29008687aa4a15ac6f195acb328d70fd364cf7f04a463` |
| Protocol SHA-256 | `b1618f40480143a4ee30239a18dfc82d5e233d07b833d9d3a65d605421968a1e` |
| Proof status | `VERIFIED` |

The fingerprint is unchanged from the historical D0 run because `COMPAT_BASE`
differs from `HISTORICAL_BASE` only in the standalone adapter lock, which is not
one of the six derivative source files. Base source hashes are unchanged:

| File | BASE SHA-256 |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| `crates/quervant-core/src/search/execute.rs` | `b49d49f7d8104f10e98bea82e7a30b80652dd87b5b78c083bf9f1384ea8edb55` |
| `crates/quervant-core/src/search/mod.rs` | `988c2b2d47d162bd58dc96e823dc6fcd9b0ca5f9d2b85264fb863cef1036cca1` |
| `crates/quervant-core/Cargo.toml` | `38d34224ff5ca87d5dbbde8f42216326a51593e31f37675d4d44a0030e2dfc1a` |
| `benchmarks/pr15d/adapters/quervant/src/main.rs` | `42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63` |
| `crates/quervant-core/src/search/d0_probe.rs` | `ABSENT` in BASE |

## 2. Independent reconstruction

`source_proof.py` does **not** import the materializer. It carries its own copy
of the closed insertion inventory, rebuilds `COMPAT_BASE + approved insertions +
rustfmt`, and requires the scratch bytes to match exactly. It then deletes only
the inserted bytes and requires the original `COMPAT_BASE` bytes back.

Accepted checks:

- byte-identical to the independent derivative;
- reverse-edit restores BASE;
- only the six derivative paths changed;
- `pr15id0-probe` is non-default and `default = ["stored-lz4"]` is unchanged;
- `pub mod d0_probe;` is feature-gated and `mod diagnostics;` keeps `#[cfg(test)]`;
- no added `#[inline]` attribute;
- no added public item other than `pub mod d0_probe;`;
- `query_probe` exists only in the adapter and exactly once.

## 3. The two authorized scratch imports

Rust resolves a sibling module as `super::d0_probe`, not `d0_probe`, inside
`search/unified.rs` and `search/execute.rs`. The fixup authorizes exactly two
additions:

```rust
use super::d0_probe;
```

at byte offsets `1565` (`unified.rs`) and `1398` (`execute.rs`). They are in the
existing import block, change no expression, query branch, scoring path,
signature or public API, and are removed by the reverse proof.

Negative tests in `test_source_proof.py` reject:

- one changed token in either import;
- a duplicated/third import;
- a moved import;
- any one-byte non-instrumented source change;
- an extra `#[inline]`, an added public item, a changed feature default;
- any seventh changed path.

## 4. Binaries

| Arm | Binary SHA-256 | Build |
|---|---|---|
| `A` | `db27f3bf36c7907f5dafb65e17147deadef380e59104e5684a46725e05ee46a9` | `cargo build --release --locked` (default features) |
| `Q`/`P` | `aab694cdb6a1f3c3012bcaebf049d0dab2f07e4cf171d735ed46a4db8e172502` | same + `--features quervant-core/pr15id0-probe` |

`A` is distinct from `Q`/`P`; `Q` and `P` are the same file and digest. The
campaign verifier re-hashes each binary and checks every slot's recorded digest.

## 5. Evidence (local)

- `target/pr15i-d0/lockfix-01/build-01.log`
- `target/pr15i-d0/lockfix-01/slice-03.log`
- `target/pr15i-d0/lockfix-01/slice-03-verify.json`
- scratch derivation:
  `target/pr15i-d0/lockfix-01/worktrees/instrumented/target/pr15i-d0/build/QP/source-derivation.json`
- source proof output:
  `target/pr15i-d0/lockfix-01/worktrees/instrumented/target/pr15i-d0/build/QP/`

Raw evidence is never committed.
