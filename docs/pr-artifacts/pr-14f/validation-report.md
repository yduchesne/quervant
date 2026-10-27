# PR 14F — local validation report

**Tested source:** `7df492023397a512e400b03865a989020eff1430`
(`fix(pr14f): use absolute report dirs for qualified campaigns`).

**Working tree at validation time:** documentation and new tracked
`benchmarks/reports/pr14f-p4-7df492023397-t{1,2,3}.json` only. The executable
diff against the source SHA is empty.

**Host:** WSL2 Linux 6.18.33.2, ext4 root, Intel i7-10750H (12 CPUs), 32 GB RAM.
**Toolchains:** stable `rustc 1.98.1`; MSRV `rustc 1.85.0`; `cargo-llvm-cov 0.9.1`.

## 1. Per-command results

| # | Command | Result | Evidence |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | **PASS** (0) | `/tmp/pr14f-validation-final/fmt_stable.log` |
| 2 | `cargo +1.85.0 fmt --all -- --check` | **PASS** (0) | `fmt_msrv.log` |
| 3 | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** (0) | `clippy_stable.log` |
| 4 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** (0) | `clippy_stable_all.log` |
| 5 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | **PASS** (0) | `clippy_msrv.log` |
| 6 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** (0) | `clippy_msrv_all.log` |
| 7 | `cargo test --workspace --all-targets` | **PASS** (0) | 2,044 passed, 0 failed, 10 ignored |
| 8 | `cargo test --workspace --all-targets --all-features` | **PASS** (0) | 2,048 passed, 0 failed, 73 ignored |
| 9 | `cargo +1.85.0 test --workspace --all-targets` | **PASS** (0) | 2,044 passed, 0 failed, 10 ignored |
| 10 | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** (0) | 2,048 passed, 0 failed, 73 ignored |
| 11 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** (0) | **91.84% lines**, 87.36% regions, 91.29% functions |
| 12 | `cargo doc --workspace --all-features --no-deps` | **PASS** (0) | `doc.log` |
| 13 | `cargo bench --workspace --no-run` | **PASS** (0) | `bench_norun.log` |
| 14 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** (0) | 58 passed, 0 failed |
| 15 | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | **PASS** (0) | `PASS self-test` |
| 16 | `python3 benchmarks/scripts/test-pr14f-audit.py` | **PASS** (0) | 25 tests OK |
| 17 | `git diff --check` | **PASS** (0) | no whitespace errors |
| 18 | Pinned RustFS digest + health | **PASS** | digest `1803faef…6a3c`, image `f6b22807…1a5c4d`, health `1.0.1` |
| 19 | Campaign 1 (`162cbfea…`) t1 | **RUNNER PASS / CAMPAIGN FAIL** | 648.53 s; wrapper aborted on relative report path |
| 20 | Approved absolute-path fix + re-lock | **PASS** | source `7df492023397…`; 58 shell tests |
| 21 | Campaign 2 (`7df4920…`) t1/t2/t3 | **PASS** | 627.58 / 594.18 / 586.70 s; all `qualified=true`, contention `clear` |
| 22 | `validate-pr14-p4.py --w08-exemption` on 3 reports | **PASS** | `PASS: 3 qualified pr14_p4_v1 trials` |
| 23 | `audit-pr14f-trials.py` on 3 reports | **PASS** | `PASS PR14F audit` |
| 24 | Read-only percentile analysis (staged, untracked) | **PASS** | 14 pairs × 3 trials, percentiles from raw CSV |
| 25 | Raw evidence local package | **PASS** | `quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz`, SHA-256 `6cef9c71…8fe66d`, 15,491 bytes, deterministic rebuild, 21 members |
| 26 | Package/archive checksum verification | **PASS** | `PACKAGE-SHA256SUMS` OK; `original-archive/SHA256SUMS` OK; manifest hashes match |
| 27 | Durable raw archive | **PASS (operator-attested)** | Google Drive `1nt02UI8…`; declared SHA-256 matches local package; agent re-download blocked by Google auth |
| 28 | Baseline-head CI at `4c94ba8` | **PASS** | PR #67, Rust CI run 40424504536: `rust`, `msrv`, `rustfs` success |
| 29 | Archival-head CI at `bd1fed7` | **PASS** | PR #67, Rust CI run 40441448948: `rust`, `msrv`, `rustfs` success |
| 30 | Previous final-binding-head CI at `8887541` | **PASS** | PR #67, Rust CI run 40443185707: `rust`, `msrv`, `rustfs` success |
| 31 | Current binding-head CI / review / merge | **PENDING / NOT DONE / NOT AUTHORIZED** | this documentation commit advances the head |

Coverage detail: `quervant-objectstore/src/s3.rs` is 28.53% because real-S3
tests are `#[ignore]`; the workspace total still passes the 85% floor. No file
was excluded to force a pass.

### Package and hash verification (final archival pass)

- All 3 tracked reports, 3 raw CSVs, 3 contention records and 3 run logs matched
  their `qualification-manifest.json` SHA-256 values.
- The package checksum manifest (`PACKAGE-SHA256SUMS`) and the retained original
  archive manifest (`original-archive/SHA256SUMS`) both verify.
- A deterministic rebuild of the `tar.gz` is byte-identical.
- Historical `pr14-p4-t{1,2,3}.json` hashes remain unchanged.
- `git diff 7df4920..4c94ba8` contains only documentation and published reports;
  the benchmark executable/workload diff is empty.
- The package embeds the pre-archival `qualification-manifest.json` snapshot.
  The authoritative updated manifest in the repository records the package
  SHA-256; embedding that hash inside the package would create a self-reference.

## 2. Ignored-suite classification

The workspace commands report 10 ignored tests without all-features and 73 with
all-features:

| Group | Classification |
|---|---|
| `pr14_bench_remote::pr14_p4_benchmark` | **EXECUTED separately** in campaign 2 (3 consecutive qualified runs); not part of the workspace command |
| Real-provider suites (`pr13_*`, `pr14_storage_faults`, real `pr14_storage_vertical` cases, etc.) | **NOT EXECUTED in PR 14F** — not affected by the benchmark-harness change; already qualified in PR 14B/14D. The pinned provider was exercised by the benchmark |
| Other pre-existing `#[ignore]` cases | **NOT EXECUTED** — unrelated to this harness-only PR |

No ignored result is presented as a pass.

## 3. Unresolved failures

- Campaign 1 (`162cbfea…`) failed after t1 on the relative report-directory
  defect. It was stopped under X13/X32, disclosed, and resolved by the
  operator-approved absolute-path fix plus three fresh trials on the new source
  lock (X18/AD-F04).
- **RAW ARCHIVE VERIFIED; DURABLE ARCHIVE ESTABLISHED (operator-attested):** the raw CSV,
  reports, contention records and logs are packaged deterministically under
  `target/pr14-p4/package/quervant-pr14f-p4-7df492023397-raw-evidence.tar.gz`
  with a verified SHA-256 and inventory. The maintainer uploaded the package to
  Google Drive and declared the same SHA-256, establishing a durable copy
  independent of the local checkout. The agent could not independently
  re-download it without Google credentials; remote integrity is
  operator-attested. The local package remains staged.
- Baseline-head CI at `4c94ba8` (run 40424504536), archival-head CI at
  `bd1fed7` (run 40441448948) and previous final-binding-head CI at `8887541`
  (run 40443185707) are green for `rust`, `msrv` and `rustfs`. This binding
  commit advances the head; independent review and merge authorization are
  outstanding.

## 4. Provider and CI identity

| Identity | State |
|---|---|
| Git executable source SHA | `7df492023397a512e400b03865a989020eff1430` |
| Measurement evidence head SHA | `4c94ba8823dac62d6397e65239db1094ce6dbfe1` (CI-verified) |
| Archival evidence head SHA | `bd1fed714c21adc5d2aeb3936db1e0b49aea3eac` (CI-verified) |
| Previous final binding head | `888754131add34cad914596c466503aa68a11325` (CI-verified) |
| Current binding head | this commit; CI pending |
| Durable archive | Google Drive `1nt02UI8…`; operator-declared SHA-256 matches local |
| RustFS image digest | `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Dataset digest | `80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768` |
| Trial IDs | `t1`, `t2`, `t3` |
| Tracked reports | `benchmarks/reports/pr14f-p4-7df492023397-t{1,2,3}.json` |
| Validator / auditor | **PASS / PASS** |
| Baseline-head CI (`rust`, `msrv`, `rustfs`) | **PASS** at `4c94ba8`; run 40424504536 |
| Archival-head CI (`rust`, `msrv`, `rustfs`) | **PASS** at `bd1fed7`; run 40441448948 |
| Previous final-binding-head CI (`rust`, `msrv`, `rustfs`) | **PASS** at `8887541`; run 40443185707 |
| Current binding-head CI | **PENDING** |
| Independent review | **NOT DONE** |
| Merge / PR 14 acceptance / v0.1 release | **NOT DONE / NOT ACCEPTED / NOT RELEASED** |

## 5. Push and CI

PR #67 exists and is open. Local `gh` authentication remains invalid (X29),
but the public GitHub API was used to verify three immutable heads:
`4c94ba8` (run 40424504536), `bd1fed7` (run 40441448948) and `8887541`
(run 40443185707); all three passed `rust`, `msrv` and `rustfs`. This validation
report commit advances the head; checks for the current binding head are
**pending** and must not be conflated with earlier results.

## 6. Authorized exceptions

- The operator explicitly approved the minimal absolute-path wrapper fix after
  campaign 1 (X13/X18). The new source lock repeats all three trials; campaign
  1's t1 is not reused.
- The operator's idle attestation was supplied before campaign 1 and the
  corrected campaign ran under the same explicit three-trial authorization. The
  timing is disclosed; the host was independently idle and every live contention
  check was `clear`.
- No other gate was waived.
