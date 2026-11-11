# PR 15I-D1-F — preflight

Executed on the operator host before any benchmark or C2 production edit.

## Source identities

| Item | Value |
|---|---|
| Current worktree | main checkout clean at `e6b88634884c9111c5222f8055914779d5bab889` |
| Verified BASE | `a53ee021acbe5f30db2b3298a11fcd99e72c2945` |
| Historical D0 production baseline | `7237bce325834d6cc1c73735697be29bc60ef16b` |
| Historical rejected C1 | `236017289567885689b46d3d04e71d6653296124` |
| Historical D1 T0 | `c4e6f5c0c82efb40e50d4cbfaa1279263f1a5321` |
| Historical C1 rollback | `e935531fb76e90e1a74b0ef3e9ba38c63b47d300` |
| Historical D1 closeout | `e3dcfff6f69b7a53dedabe1bc50e59de4a89a364` |
| New branch | `dev/pr15i-d1-f-c2-independent` (based on BASE) |

- `git cat-file -e` succeeds for every SHA above.
- `crates/quervant-core/src/search/unified.rs` blob is
  `b2978021f9f36ae9a5cdd9fa036448a54097c948` at both `e6b8863` and BASE;
  `segment/reader.rs` is `aa69f2bebb9746f44254a702438e91cea9a9b7a5` at both.
- `git diff 7237bce BASE -- unified.rs reader.rs` is empty.
- `git diff BASE e935531 -- crates/` is empty; BASE is the production source.
- Adapter lock SHA-256 is `19953cab…` (the D0 compatibility lock). Two
  `cargo build --release --locked` runs in a pristine BASE worktree succeeded
  (22.65 s, 0.03 s), the lock checksum was unchanged, the tree stayed clean and
  `cargo metadata --locked --no-deps` passed.

## Historical C1 evidence audit (immutable)

Archives at `$HOME/.local/share/quervant/benchmark-evidence/pr15i-d1/`:

| Archive | SHA-256 | Members | Sidecar | Extraction/re-hash | D1 verifier |
|---|---|---:|---|---|---|
| `c1-base-aa-01.tar.gz` | `a741a858…` | 58 | match | 0 mismatches, 0 extra | PASS `CONTROL_QUALIFIED` |
| `c1-base-01.tar.gz` | `f6aabd32…` | 61 | match | 0 mismatches, 0 extra | PASS `CAMPAIGN_QUALIFIED` |
| `c1-base-02.tar.gz` | `94417804…` | 61 | match | 0 mismatches, 0 extra | PASS `CAMPAIGN_REJECTED` |

Extraction rejected absolute/`..` members; every member was re-hashed against the
sidecar inventory. Historical campaign binaries are still present and match the
sealed manifest hashes (A `9f9f909f…`, B `6866066c…`). The original C1 rejection
is preserved unchanged; this follow-up does not re-run C1.

## Host and toolchains

- WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, 12 CPUs, 32 GiB.
- Native `ext4`, 772 G free at preflight.
- `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`, `cargo +1.85.0`
  1.85.0, Python 3.12.3.
- Benchmark CPU pair selected at run time through `taskset -c 4,5` (controller
  on the second allowed CPU, adapters on the first); each adapter affinity is
  verified from `/proc`.
- `quervant-cleanup.timer` and `quervant-disk-monitor.timer` were active and
  enabled. Their state is recorded and they are stopped only during benchmark
  acquisition, then restored to the exact original active state.

## C2 invariant → test matrix

| Invariant | Tests |
|---|---|
| F-I02 no C1 code / allowed diff | B02 source-policy and symbol tests; verifier changed-path + symbol scan |
| F-I03 borrowed bytes equal decoded keys | K01, K03, K05 |
| F-I04 no escaped borrow | K02, K05 (compiled lifetimes; no unsafe) |
| F-I05 ownership only on admission | K06, K07 |
| F-I06 duplicate scan unchanged | K08 |
| F-I07 full response parity | K09–K12, K16 |
| F-I08 optional metadata fallback | K04, K13 |
| F-I09 budgets/snapshot/RustFS | K10, K12–K15 |
| F-I10 byte-identical indexes | B03 + campaign index digests/sentinels |
| F-I11 sealed evidence | B04–B16 |
| F-I12 postmortem evidence levels | `c1-postmortem.md` |

## Applied decisions

- FDX-01: BASE exists and matches the frozen production blobs; two locked
  builds pass → pin BASE.
- FDX-02: historical C1/T0 commits and archives exist and verify → perform the
  F1 audit without modifying them.
- FDX-19: F0 tooling defects, if any, are corrected and re-frozen **before** any
  real campaign; no after-data edits.
- FDX-26: RustFS is unavailable on this host (no service/container) and hosted
  CI/PR credentials are not assumed → `RUSTFS_PENDING`, `CI_PENDING`,
  `PR_NOT_CREATED` unless credentials actually work.

## Blockers

None for F0/F1/F2 or benchmark acquisition. RustFS and hosted CI remain
external gates.
