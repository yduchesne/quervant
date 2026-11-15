# PR 15I-D3-B-F1 — design and build proof

## Canonical build design (implemented)

```text
target/pr15i-d3-b/fixup-f1/<campaign>/
  compile-source/            one detached Git worktree, one absolute path
  build/A/                   cargo target dir for arm A
  build/B/                   cargo target dir for arm B
  corpus/                    frozen PR15D corpus
  indexes/                   real index builds
```

Both arms always compile with the same shape:

```text
cargo build --release --locked
  --manifest-path <campaign>/compile-source/benchmarks/pr15d/adapters/quervant/Cargo.toml
  --target-dir <campaign>/build/<arm>
cwd = <campaign>/compile-source/benchmarks/pr15d/adapters/quervant
```

- A/A: checkout BASE once, build A, keep the checkout unchanged, build B.
- A/B: checkout BASE, build A, then `git switch --detach <candidate>` on the
  same path, build B. Never build from the external identity worktrees; never
  copy a binary; never change flags, toolchain, features, `RUSTFLAGS` or
  `--remap-path-prefix`.
- Before/after each build the controller proves detached HEAD, clean tree,
  exact HEAD, on-disk/Git-blob equality for the protected source and the frozen
  PR15D inputs.
- The `FORBIDDEN_BUILD_ENV` guard rejects `RUSTFLAGS`,
  `CARGO_ENCODED_RUSTFLAGS`, `CARGO_BUILD_RUSTFLAGS`, `RUSTC`,
  `RUSTC_WRAPPER`, `RUSTC_WORKSPACE_WRAPPER`, `CARGO_INCREMENTAL`,
  `SOURCE_DATE_EPOCH`, `CARGO_PROFILE_*` and `CARGO_TARGET_*`.

## Non-timed dry proof (`DRY_RUN_NO_TIMING`, never an A/A control)

Command (before T1, into the F1 namespace):

```sh
python3 benchmarks/pr15i_d3_b_f1/run.py dry-proof \
  --candidate-sha 48d9abf3eeefbccb480d89eac95f6e6911e078d5 \
  --out target/pr15i-d3-b/fixup-f1/dry-proof-01
# status: DRY_PROOF_PASS
```

| Experiment | Arm A binary SHA-256 | Arm B binary SHA-256 | Result |
|---|---|---|---|
| BASE/BASE (`dry-proof-01/dry-proof-aa`) | `4994d27305a6b46b946d7795fe2f672ed84d4a397a4af6e845e593e5ef962d8a` | `4994d27305a6b46b946d7795fe2f672ed84d4a397a4af6e845e593e5ef962d8a` | identical (as required) |
| BASE/candidate (`dry-proof-01/dry-proof-ab`) | `81bacb88aff1a6790ca76d34beb0ae79b6b80e919dc9570f30631dedb6d605ff` | `3b2f17fc52fb7fbead60b7e04422b41475898963a94a1b81d6351106e7296a0a` | distinct (as required) |

Both experiments used one canonical path each, two independent target
directories, real `cargo build --release --locked` executions, and recorded
pre/post source proofs. `dry-proof-summary.json` is labelled
`DRY_RUN_NO_TIMING`; it is not an A/A control and cannot be reclassified.

## Toolchain and environment

- `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1`, git 2.43.0,
  util-linux `findmnt` 2.39.3, Python 3.12.
- No forbidden build environment variable was present at any build.
- WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, Intel i7-10750H,
  native ext4; controller pinned to CPU 1, adapters to CPU 0.

## Official control build provenance (executed after T1)

`d3bf1-base-aa-01` created one canonical path
`…/fixup-f1/d3bf1-base-aa-01/compile-source` and performed two real,
independently-targeted builds.

| Field | Arm A | Arm B |
|---|---|---|
| Expected source | `39dbd9f5…` | `39dbd9f5…` |
| Pre/post checkout | `39dbd9f5…` | `39dbd9f5…` |
| Pre/post `unified.rs` SHA-256 | `bb7a1035…` (unchanged) | `bb7a1035…` (unchanged) |
| Build window (UTC) | `04:08:08`–`04:08:30` | `04:08:31`–`04:08:54` |
| Binary SHA-256 | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313` | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313` |
| Binary bytes | 4,479,080 | 4,479,080 |

The two base binaries are byte-identical, resolving the D3-B worktree-path
contradiction. `raw/build-provenance.json` SHA-256 is
`e965f1a7e94c6430e4522fad20f2ee8fc0291a91713e4a1c5ef4d5c257d0ea4e`;
`raw/host-attestation.json` SHA-256 is
`c2a4a37e23652d173d5a38f72532a98e7494bc273d0c627afb51b007390d0c2b`.

## Defects found while verifying the first official control

The canonical build design works. Two defects in the **frozen T1 tooling**
prevent the independent verifier from accepting the sealed control:

1. The verifier's inventory check walks the whole campaign directory but
   exempts only `build/`, `indexes/` and `corpus/`, not the mandated,
   never-sealed `compile-source/` worktree. Result:
   `V_INVENTORY: unlisted campaign member: compile-source/.git`.
2. The controller stores `allowed_cpus_before_pin` in the host attestation but
   its shared `host_fingerprint` reads a different key (`allowed_cpus`), so the
   sealed fingerprint silently omits the allowed CPU set. The verifier recomputes
   it from `allowed_cpus_before_pin`; the stored value
   (`45024a19…`) and the independent value (`aa136252…`) disagree. Result:
   `V_HOST: host fingerprint does not recompute` (diagnostic after applying only
   the first correction in memory).

Per plan §4 and FDX-41/44/56, post-T1 tooling defects are a HARD STOP: no hot
patch and no paired acquisition. See `decision-register.md` and
`execution-status.md`.
