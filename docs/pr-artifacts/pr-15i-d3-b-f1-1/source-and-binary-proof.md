# PR 15I-D3-B-F1.1 — source and binary proof

## Source identities (unchanged)

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate production/tests | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| F1.1 T2 tooling | `63b30a0be451357a5edaf8399ad2e4d336e6c45b` |
| BASE `unified.rs` SHA-256 | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Candidate `unified.rs` SHA-256 (Git blob) | `493f93825e77581833a26c6436c5ea35aed26fc453eb2cbcec80733710ec183c` |
| `git diff 48d9abf3… HEAD -- crates/ Cargo.toml Cargo.lock` | empty |
| Historical T0 diff (`155ebafa… -- benchmarks/pr15i_d3_b`) | empty |
| Historical T1 diff (`ac45c23f… -- benchmarks/pr15i_d3_b_f1`) | empty |

No Rust source, test, Cargo file, corpus, oracle, adapter or index format was
changed. The source-policy proof in the verifier admits exactly the immutable
candidate diff and rejects the historical D1-C1/C2 design symbols.

## Canonical build method

Each campaign owns exactly one detached `<campaign>/compile-source` worktree and
builds both arms from that same absolute path into `<campaign>/build/A` and
`<campaign>/build/B` with `cargo build --release --locked`. For A/B the same
path switches from BASE to the candidate with `git switch --detach` only after
arm A is built. The pre/post proofs check detached HEAD, clean tree, exact HEAD,
the `unified.rs` Git blob and on-disk bytes, all six frozen PR15D inputs and the
adapter lock. No cross-worktree compilation, binary copying, `RUSTFLAGS`,
`--remap-path-prefix`, feature, profile or toolchain change is accepted.

## Control binaries and indexes

| Item | Arm A | Arm B |
|---|---|---|
| Source | `39dbd9f5…` | `39dbd9f5…` |
| Binary | `6469b5fa3952823f5828e59a2946bae4e166cd4c6eed97029c5712a406a2d71d` | same |
| Bytes | 4,479,272 | 4,479,272 |
| 100K index | 15,747,551 committed / 1,661,455 STORED, digest `5734ae60591f7563…` | same |

A/A byte equality is proven, and the binaries were rehashed before the first
slot and after the last slot (`pre_timing_snapshot == post_timing_snapshot`).

## Paired campaign 01 binaries

| Item | Arm A (BASE) | Arm B (candidate) |
|---|---|---|
| Source | `39dbd9f5…` | `48d9abf3…` |
| Binary | `9519a215b7fa188793d2cddd349a94b37ba4eb5da0cc291c0bf7433fdc6b942f` | `370678645eed410830294ef48d712d2646b79b51751405383adf18ad5ca2c431` |
| Bytes | 4,479,120 | 4,490,552 |
| 100K index | 15,747,551 / 1,661,455, digest `5734ae60591f7563…` | same |

Distinct source revisions, distinct binaries and byte-identical indexes confirm
attribution to the source change; the campaign itself is structurally blocked by
the drift violation (see `performance-qualification.md`).

## Historical preservation

- Original F1 blocked control: 59 sealed members, inventory SHA-256
  `d5511aec2f2d2546e83a728a08872ea6103e8c7c37db6105361eed406e86ff88`,
  rehashed unchanged before and after the rehearsal. No `verification.json` was
  written into it.
- Historical D3-B archive `d3b-base-aa-01.tar.gz` SHA-256
  `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc` remains.
- A pre-existing user modification to `disk-cleanup.sh` was present in the
  working tree and was deliberately left untouched.
