# PR 15I-D0 lockfix-01 — compatibility lock diff

## 1. Decision

The historical blocker was a stale standalone PR 15D Quervant adapter lockfile:
`quervant-core` declares `default = ["stored-lz4"]` and
`lz4_flex = { version = "=0.11.6", optional = true }`, but the adapter lock at
`HISTORICAL_BASE`/`PARENT_MAIN` did not contain `lz4_flex` or `twox-hash`.
`cargo build --locked` therefore refused before producing any executable.

`FX-02`/`FX-03` applied: the lock was regenerated through Cargo, the broad
probe was discarded, and only a mechanically minimal lock was committed.

## 2. Broad probe (discarded, preserved)

The permitted probe

```sh
cargo generate-lockfile \
  --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml
```

produced a broad refresh that also bumped `itoa`, `smallvec`, `syn`,
`unicode-script`, `unicode-security` and others. It was **not** committed.
The probe diff is preserved locally at
`target/pr15i-d0/lockfix-01/lock-probe-broad.diff`
(SHA-256 `6a6b23501874ebd57696833b05414593883d9a291cfb3056fecaaefe38ffbc1e`).
The working lock was restored to the exact original bytes.

A Cargo-supported minimal offline resolution was then used:

```sh
cargo build --release --offline \
  --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml
```

This is a normal Cargo resolution, not hand editing, and it changed only the
required records.

## 3. Accepted diff (16 insertions, 0 deletions, 0 changes)

The complete diff is 16 added lines:

```text
+ [[package]]
+ name = "lz4_flex"
+ version = "0.11.6"
+ source = "registry+https://github.com/rust-lang/crates.io-index"
+ checksum = "373f5eceeeab7925e0c1098212f2fbc4d416adec9d35051a6ab251e824c1854a"
+ dependencies = ["twox-hash"]
...
+ "lz4_flex"          # in the quervant-core dependency edge
...
+ [[package]]
+ name = "twox-hash"
+ version = "2.1.5"
+ source = "registry+https://github.com/rust-lang/crates.io-index"
+ checksum = "86a801b3cea342a06d468c8710662aa29e5e05e4f5c0d62f00bbb7f2ad7941c2"
```

Structured proof (`target/pr15i-d0/lockfix-01/lock-diff-proof.json`,
SHA-256 `574b5bbc216fbab67f644b62a2fa674a139c3eccad5665382b273044af9ef068`):

| Check | Result |
|---|---|
| Added packages | exactly `lz4_flex 0.11.6`, `twox-hash 2.1.5` |
| Removed packages | none |
| Changed package versions/checksums | none |
| Changed dependency edges | `quervant-core` gains only `lz4_flex` |
| Lock format version | 4 (unchanged) |
| Repository root `Cargo.lock` | unchanged `293ff40c…` |
| Changed paths in COMPAT_BASE | exactly the standalone adapter lock |

## 4. Reproducibility

| Check | Result |
|---|---|
| `cargo build --release --locked` (isolated target dir #1) | PASS |
| `cargo build --release --locked` (isolated target dir #2) | PASS |
| Lock SHA-256 after both builds | `19953cab…` (byte-identical) |
| `cargo metadata --locked --format-version 1` | PASS |
| Lockfiles mutated after build | none |
| COMPAT_BASE commit | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |

No manifest flag was changed, `stored-lz4` was not disabled, and no unrelated
package was updated to obtain a passing build.
