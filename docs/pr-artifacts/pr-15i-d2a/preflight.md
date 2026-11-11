# PR 15I-D2-A — preflight

## Source identity

| Item | Value |
|---|---|
| Accepted BASE | `9429dce99827f25766a92c1fbded8f78a0b168f1` |
| `origin/main` at execution | `9429dce99827f25766a92c1fbded8f78a0b168f1` |
| D1 reconciliation | PR #94 (`dev/pr15i-d1-f-c2-independent`) is merged; C2 was reverted on `051c319`; no C1 fingerprint index and no C2 `doc_key_view` remain in production source |
| Tooling freeze T0 | `747ceb2464425f2392829c5165decf4c697cf34b` |
| Protocol | `benchmarks/pr15i_d2a/protocol_v1.json`, SHA-256 `7e41e2c576baf522ad652dd66488373f07c88a3c8419677a3f42dee40f41d39e` |
| Tooling manifest | SHA-256 `92c025c90ba6344f4f5c4a7270ea9ec8131b3e1daac0c58f947d325d2a02bd04` |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |

The planning document's read-time `main` was `e6b8863` and did not contain the
D1-F closeout. The execution checkout is `9429dce`, whose tracked production
`crates/quervant-core/src` tree is byte-identical to `e6b8863`; only D1-F
tooling, documentation and the PR15D adapter lockfile changed. Audited source
blobs were re-verified:

| File | Git blob |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | `b2978021f9f36ae9a5cdd9fa036448a54097c948` |
| `crates/quervant-core/src/search/execute.rs` | `5d0ac48132de6ea1220bdd884f81ca9f260ab3ba` |
| `crates/quervant-core/src/search/score.rs` | `2921afc52ad0f343498e6c69814b38016205ea2d` |
| `crates/quervant-core/src/segment/reader.rs` | `aa69f2bebb9746f44254a702438e91cea9a9b7a5` |

## Frozen input SHA-256

| Path | SHA-256 |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| `crates/quervant-core/src/search/execute.rs` | `b49d49f7d8104f10e98bea82e7a30b80652dd87b5b78c083bf9f1384ea8edb55` |
| `crates/quervant-core/src/search/score.rs` | `f03712ec16822a343002346a1bf596f292ed7884411fc1a4b0dbe7ba911caf16` |
| `crates/quervant-core/src/search/mod.rs` | `988c2b2d47d162bd58dc96e823dc6fcd9b0ca5f9d2b85264fb863cef1036cca1` |
| `crates/quervant-core/src/segment/reader.rs` | `3f74af0e3c071a4b39275c48b15c976cf69f1cc007cd7646f5a303a68c007107` |
| `crates/quervant-core/Cargo.toml` | `38d34224ff5ca87d5dbbde8f42216326a51593e31f37675d4d44a0030e2dfc1a` |
| `benchmarks/pr15d/adapters/quervant/src/main.rs` | `42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63` |
| `benchmarks/pr15d/adapters/quervant/Cargo.lock` | `19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121` |
| `benchmarks/pr15d/corpus/oracle.py` | `4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2` |

The full 25-artifact inventory is in
`target/pr15i-d2a/preflight/preflight-final.json` (`status: PASS`).

## Build and host checks

- `cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml`: PASS on BASE.
- `cargo check --locked --workspace --all-features`: PASS on BASE.
- Native filesystem: `ext4`; not a DrvFs/9p mount.
- Host: WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, 12 allowed CPUs
  (`0-11`), Intel Core i7-10750H; no cpufreq governor readable.
- Toolchains: `rustc/cargo 1.98.1` stable and `1.85.0` MSRV available; Python
  3.12.3; `taskset`, `findmnt`, `sha256sum`, `git`, `rustfmt` present.
- Affinity: controller on the second allowed CPU, adapters on the first; the
  adapter affinity is observed with a bounded settled wait.
- Contention: every one of the 128 campaign probes reported `clear`; invalid
  attempts are preserved separately.

## Tooling-freeze history

| T0 | Change | Campaign evidence |
|---|---|---|
| `e69fb64` | initial tooling freeze | superseded before any accepted sample |
| `eb3fdbc` | control index-sentinel arm handling | superseded before any accepted sample |
| `bb3a6e5` | control source inventory excludes the scratch-only probe module | A/A qualified; superseded after the paired metadata defect |
| `2774c87` | campaign source inventory allows the new probe module | paired 01 rejected by the verifier (Q fingerprint metadata defect) |
| `747ceb2` | final: Q/P slots carry the derivative fingerprint | accepted A/A, campaign 01, campaign 02 |

All superseded campaign directories and the superseded A/A archive are retained
under `target/pr15i-d2a/superseded/` and
`$HOME/.local/share/quervant/benchmark-evidence/pr15i-d2a/superseded/`.
They are not part of the qualified series.

## A/A attempts under the final T0

1. `d2a-base-aa-01-attempt-01-T0-747ceb2` — rejected: one 10K absent block ratio
   `1.269948` was outside `[0.80, 1.25]`. Preserved; not used.
2. `d2a-base-aa-01` — qualified after documented quiescence (DA-16 retry).

No source, corpus, adapter or binary identity changed between the attempts.
