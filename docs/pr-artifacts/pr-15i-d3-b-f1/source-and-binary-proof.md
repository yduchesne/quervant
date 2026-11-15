# PR 15I-D3-B-F1 — source and binary proof

## Source identities (unchanged candidate)

| Item | Value |
|---|---|
| BASE | `39dbd9f571a58bea8cc03d5a406533298e809bfe` |
| Candidate production/tests | `48d9abf3eeefbccb480d89eac95f6e6911e078d5` |
| Branch HEAD at execution | `ac45c23fd5a8862898e4d4502a4bfc684e4dfc82` (T1) |
| BASE `unified.rs` SHA-256 | `bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433` |
| Candidate `unified.rs` SHA-256 | `493f93825e77581833a26c6436c5ea35aed26fc453eb2cbcec80733710ec183c` |
| Candidate test SHA-256 | `ff5f0feced8f65a1ef2f08f7e830eeebec657472e91d79f2a99ce42294dd84ac` |

`git diff --name-only 48d9abf3… HEAD -- crates/ Cargo.toml Cargo.lock` is empty:
F1 changed no production, test, manifest or lock file. The F1 work is a copy of
the benchmark tooling plus PR documentation only.

## Canonical build proof

- One campaign-local worktree at
  `<campaign>/compile-source`, detached at the expected revision before each
  build; tracked and untracked status clean; `rev-parse --show-toplevel` equal
  to the canonical path.
- Before and after each build: HEAD, `unified.rs` Git blob and on-disk bytes,
  all six frozen PR15D inputs and the adapter `Cargo.lock` match the frozen
  digests.
- Two independent `cargo build --release --locked` executions into
  `<campaign>/build/A` and `<campaign>/build/B`; distinct build ids, distinct
  target directories, identical toolchain and environment fingerprint, and no
  forbidden flags or `RUSTFLAGS`-style overrides.
- For A/B only: `git switch --detach <candidate>` on the same path, recorded
  with from/to SHAs and argv.

### Dry proof (non-timed, `DRY_RUN_NO_TIMING`)

| Experiment | A | B | Required |
|---|---|---|---|
| BASE/BASE | `4994d273…` | `4994d273…` | equal |
| BASE/candidate | `81bacb88…` | `3b2f17fc…` | distinct |

### Official control

| Arm | Source | Binary | Bytes |
|---|---|---|---|
| A | `39dbd9f5…` | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313` | 4,479,080 |
| B | `39dbd9f5…` | `2e28d89b19e973bacedd61aee09dae83c1af0f19c8437429cda4684a2a338313` | 4,479,080 |

The binaries were rehashed immediately before the first slot and after the last
slot; both snapshots agree. Both arms' 100K indexes are byte-identical
(15,747,551 bytes, STORED 1,661,455, digest `5734ae60591f7563…`).

## Historical isolation

- `benchmarks/pr15i_d3_b/**` is byte-identical to the old T0 commit
  `155ebafafa29fb0e6b6cbf953f89445f4880fd2f`
  (`git diff --exit-code` empty).
- The old v1 protocol SHA-256 remains
  `8c113091507528450f9dd8f406fc3ac0a390c164b9a7a603583f48d752c6d1be`.
- The old failed archive remains
  `563a5cf02674dacd71286796dcffcb0760098a0adec8db5434edbd60b3d973fc`
  with its sidecar; it was neither re-used nor re-published.

## Post-outcome state

The candidate remains committed on `dev/pr15i-d3b-retained-key-prefilter` as an
unmerged measurement branch. No production rollback was performed because the
outcome is a measurement block, not a qualified performance rejection.
