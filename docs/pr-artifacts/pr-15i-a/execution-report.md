# PR 15I-A — execution report

Status: **A_CANDIDATE_ACCEPTED_PENDING_QA** — local campaign and QA gates pass;
hosted CI and independent review remain external.

## 1. Source identities

| Item | Value |
|---|---|
| Branch | `dev/pr15i-a-mutation` |
| Post-PR15I-0 baseline (A) | `888e819d85f0cde62a5040919ac5c96feca52f1f` |
| Tooling seal (first commit) | `29a61f7701217e7e81bc50a9eb550c050e85fd1d` |
| Measured candidate (B) | `db9007fb7239a5cce94e20c7c43ac7200da8047f` |
| Campaign | `target/pr15i-a/campaigns/paired-04` (unique, sealed) |
| Raw seal SHA-256 | `af7f6c1a85515dbc58c8c31a3b1b7f68dd6a9246d33747a529952b941b852b2f` |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Environment fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` |
| Host filesystem | native `ext4` (not `/mnt/c`) |

Binary SHA-256 (adapter / reopen probe / remote probe):

- A: `d6db9d9a…798a6` / `1e6acf7d…7f32` / `7f6f7c1a…39a4`
- B: `68143d7d…916f` / `072d5def…18b8` / `b6d67634…0880`

Two invalid campaign attempts are preserved and are **not** acceptance
evidence: `paired-01` (controller key type bug) and `paired-02` (stale worktree
pin), followed by a third controller-only fix (`paired-03` aborted before any
measurement on a frozen-helper type mismatch). `paired-04` is the first and only
campaign with complete sealed samples; every subsequent controller change would
have required a new campaign ID.

## 2. Scope

`git diff A..B` produced only these paths (all allowlisted): the five production
files `segment/format.rs`, `index/{mutation_state,writer,merge,mod}.rs`, the
in-test `index/amendment01.rs` publication helper, the two new test files, the
CI RustFS invocation, the four docs files, `benchmarks/pr15i_a/**`,
`benchmarks/reports/pr15i-a/**` and `docs/pr-artifacts/pr-15i-a/**`. No frozen
PR15D/PR15E/PR15F/PR15H-E/PR15I-0 script, corpus, fixture or report changed.

`amendment01.rs` is a `#[cfg(test)]` module; its manual publication helper now
writes the production V3 generation (payload + V3 feature) instead of a legacy
V1 payload under a V3 manifest. All its assertions are unchanged; the edit is
required by IA-06 and is not a production-path change.

## 3. Format

Payload version 3, required features `(0x0008,1)` and `(0x000C,1)`, plus
`(0x000B,1)` when V2 history is inherited or a batch replay record exists. V1
golden SHA-256 remains
`753094d07734fbbebf5b535d585af83107d241c917e7e731462d2af972efc469`. No segment
container, manifest wire version, digest or `CURRENT` sequencing change.

## 4. Test matrix (executed)

| Class | Result |
|---|---|
| U01–U43 codec/compatibility/budget | 43/43 pass (`index::mutation_state::pr15i_a_v3_tests`) |
| I01–I12 integration (incl. separate-process reopen) | pass |
| F01–F08 deterministic faults/recovery | pass |
| R01–R04 real RustFS (pinned image, `--ignored`) | 4/4 pass |
| Legacy V1/V2, M1–M5, PR06/PR09 mutation/replay suites | pass |
| Python controller/verifier tests | 28/28 pass |
| `benchmarks/scripts/test-scripts.sh` | 108/108 pass |

The full codec and integration evidence is in the workspace test run below; the
fault tests use the real `Directory` seam, and the reopen test spawns a fresh
process rather than calling a process-local reopen.

## 5. QA table (local, executed at the final source state)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS (0 failures) |
| `cargo test --workspace --all-targets --all-features` | PASS (0 failures) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS, **92.74% lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS (0 failures) |
| `git diff --check` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_a -p 'test_*.py'` | PASS (28) |
| Pinned RustFS: `pr15i_a_rustfs -- --ignored` | PASS (4) |
| Pinned RustFS: `m1_batches`, `pr13_remote`, `pr13_remote_proxy` | PASS |
| Pinned RustFS: `pr13_crash_rustfs k0`; `k05` 10×; M3 3×; M5 3× | PASS |

RustFS container: `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
endpoint `http://127.0.0.1:9000` (sanitized), isolated bucket `quervant-pr15ia`,
teardown after the runs.

## 6. Storage results (exact bytes)

| Arm | n | Sidecar | Segment | Manifest | `CURRENT` | Total | Payload |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 10,000 | 960,180 | 2,129,038 | 636 | 183 | 3,090,037 | 1 |
| B | 10,000 | 230,132 | 2,129,038 | 644 | 183 | 2,359,997 | 3 |
| A | 100,000 | 9,600,180 | 21,364,026 | 636 | 183 | 30,965,025 | 1 |
| B | 100,000 | 2,383,748 | 21,364,026 | 644 | 183 | 23,748,601 | 3 |

- A reproduces the PR15I0 sentinels exactly (`30,965,025` / `9,600,180`).
- B/A 100K sidecar = **0.248302** (gate `<= 0.75`, PASS).
- B/A 100K total = **0.766949** (gate `<= 0.95`, PASS).
- B/A 10K sidecar = 0.239676 and total = 0.763744 (gate `<= 1.02`, PASS).
- Segment bytes are byte-identical; the manifest grows by 8 bytes for the V3
  feature tuple; `CURRENT` is unchanged.
- Three independent builds per arm and size produced identical layouts.

## 7. Guardrail results (four balanced blocks, B/A)

| Metric | Block ratios | Median | Gate |
|---|---|---|---|
| Reopen 100K | 0.7965, 0.7912, 0.7836, 0.7999 | 0.7884 | PASS (`<=1.10`, blocks `<=1.25`) |
| Build+commit 100K | 0.9316, 0.9745, 0.9475, 0.9171 | 0.9395 | PASS (`<=1.15`, blocks `<=1.30`) |
| Build (ingest) only | 0.9743, 1.0263, 1.0020, 0.9237 | — | reported |
| Commit only | 0.9257, 0.9671, 0.9406, 0.9161 | — | reported |
| RSS reopen | 0.9997, 1.0005, 1.0006, 0.9994 | 1.0001 | PASS (absolute +5,632 B) |
| RSS build+commit | 0.9996, 1.0003, 1.0002, 1.0003 | 1.0002 | PASS (absolute +31,744 B) |
| RustFS cold bootstrap | 0.8691, 0.8565, 1.1986, 0.8698 | 0.8694 | PASS (`<=1.15`, blocks `<=1.35`) |

All nine warm lanes passed (worst block ratio 1.1319 on 10K rare; 100K worst
block ratio 1.0255). No lane or block was discarded. `A-P10`–`A-P12` pass:
every size rebuild and warm slot oracle-checked, exact payload/feature checks,
single candidate SHA, allowlisted scope and sealed evidence.

## 8. Controls

`pr15i_a_v3.rs` covers the 129-live-segment ordinal >= 128 shape (I11),
tombstone/upsert mixtures (I01/I02), replay-heavy state across restart (I10),
zero-live compaction (I12), legacy upgrade (I04/I05), no-op paths (I08) and
feature/decoding corruption. These are correctness controls; they are not used
as alternate performance targets and no size-ratio gate is applied to them.

## 9. Applied decision-matrix rules

| ID | Trigger | Action | Result |
|---|---|---|---|
| A-01 | PR15I0 ancestor, clean tree, `0x000C` free | Created branch, pinned BASE | OK |
| A-02 | `main` after PR15I0 has no relevant production change | Used fresh BASE | OK |
| A-03 | Ancestry verified | No hard stop | OK |
| A-05 | Existing canonical LEB128 reused | No new codec | OK |
| A-06 | Legacy golden tests use `encode()`/`encode_with_mode` | Kept them; added `encode_v3` | OK |
| A-07/A-08/A-09/A-10 | V3 always carries the batch block; V2 history retained; real commit upgrades; no-op does not migrate | Implemented exactly | OK |
| A-12–A-16, A-18, A-20, A-21 | Typed corruption, bounded allocation, owned clone retained, EOF, no-op, verified reads | Implemented exactly | OK |
| A-24 | Fresh A 100K size vs PR15I0 sentinel | Sentinel matched exactly; no mismatch | OK |
| A-26 | Frozen PR15I0 mutation probe cannot parse V3 | Added read-only A-specific probes under `benchmarks/pr15i_a` | OK |
| A-28/A-34 | Controller bugs found before sealed measurement | Fixed tooling in new commits, preserved invalid attempts, ran a complete new campaign (`paired-04`) | OK |
| A-40 | Candidate accepted; no rollback required | — | N/A |
| A-42 | User-authorized idle host, no contention | Ran the campaign without further authorization | OK |
| A-13/A-17 | V3 decode budget implemented with the prescribed charge-before-reserve ledger | No semantic change to V1/V2 | OK |
| A-31 | No correctness case failed | Candidate accepted | OK |

## 10. External gates

- **Hosted CI: `HOSTED_CI_PENDING`.** Not executed; local QA and the locally
  pinned real-RustFS job are not hosted-CI evidence.
- **Independent human review: `REVIEW_PENDING`.**
- **Push/PR/merge: not authorized and not performed.**

## 11. Reviewer follow-up

The single smallest open decision is maintainer approval to push the branch and
let hosted CI run; no local correctness, format or performance item is
unresolved. V3 remains a storage experiment and must not be described as
closing the broader cross-engine index/query gap.
