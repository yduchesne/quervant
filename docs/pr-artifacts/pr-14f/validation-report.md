# PR 14F — local validation report

**Tested source:** `162cbfea509d5f03df4bedb89a09d9be4cafb75e`
(`fix(pr14f): qualify P4 benchmark harness and lock source`).

**Working tree at validation time:** documentation additions under
`docs/pr-artifacts/pr-14f/` only. Executable diff against the source-lock SHA is
**empty**:

```sh
git diff --stat 162cbfea… -- benchmarks/scripts/… crates/quervant-core/tests/pr14_bench_remote.rs
# (no output)
```

**Host:** WSL2 Linux 6.18.33.2, ext4 root, Intel i7-10750H (12 CPUs), 32 GB RAM.
**Toolchains:** stable `rustc 1.98.1`; MSRV `rustc 1.85.0`; `cargo-llvm-cov 0.9.1`.

## 1. Per-command results

| # | Command | Result | Evidence |
|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | **PASS** (0) | `/tmp/pr14f-validation/fmt_stable.log` |
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
| 14 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** (0) | 55 passed, 0 failed |
| 15 | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | **PASS** (0) | `PASS self-test` |
| 16 | `python3 benchmarks/scripts/test-pr14f-audit.py` | **PASS** (0) | 25 tests OK |
| 17 | `git diff --check` | **PASS** (0) | no whitespace errors |
| 18 | `podman pull` + inspect pinned RustFS digest | **PASS** (0) | digest `1803faef…6a3c`, image `f6b22807…1a5c4d` |
| 19 | RustFS `/health` probe | **PASS** | `{"status":"ok",…,"version":"1.0.1"}` |
| 20 | Three qualified `pr14_p4_v1` trials | **BLOCKED** | operator idle attestation absent (X15) |

Coverage detail: `quervant-objectstore/src/s3.rs` is 28.53% because real-S3
tests are `#[ignore]`; the workspace total still passes the 85% floor. No file
was excluded to force a pass.

## 2. Ignored-suite classification

The four workspace test commands report 10 ignored tests without all-features
and 73 with all-features. Classification:

| Group | Tests | Classification |
|---|---|---|
| `pr14_bench_remote::pr14_p4_benchmark` | 1 | **BLOCKED** — requires operator attestation; Stage D not run |
| Real-provider suites (`pr13_bench_remote`, `pr13_crash_rustfs`, `pr13_remote_proxy`, `pr13_proxy_rustfs`, `pr13_s3_rustfs`, `pr14_storage_faults`, real cases in `pr14_storage_vertical`, `pr13_remote`, `pr14b_json_memory`) | 60+ | **NOT EXECUTED in PR 14F** — not affected by the benchmark-harness change; already qualified in PR 14B/14D. The prequalified provider is healthy but this PR makes no new provider claim beyond digest/health |
| Other pre-existing `#[ignore]` cases (`unittests`, `m1..m5`, `pr06_*`, `pr11_json_corruption`, `pr13_oracle*`, `segment_golden`, `storage_fs_integration`) | 12 | **NOT EXECUTED** — unrelated to this harness-only PR; unchanged by it |

No ignored result is presented as a pass.

## 3. Unresolved failures

None in the executed local gates. The benchmark qualification itself is
**unresolved/blocked**, not passed.

## 4. Provider and CI identity

| Identity | State |
|---|---|
| Git executable source SHA | `162cbfea509d5f03df4bedb89a09d9be4cafb75e` |
| Evidence head SHA | `76612ded952623b1b4dffc5fdace67780d2b4b17` (first documentation evidence commit; later documentation-only commits may advance the head without changing executable inputs) |
| RustFS image digest | `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Dataset digest | `80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768` |
| Trial IDs / CSV hashes | none — no trial |
| PR head CI (`rust`, `msrv`, `rustfs`) | **NOT RUN** — no pull request created; `gh` token invalid |
| Independent review | **NOT DONE** |
| Merge / PR 14 acceptance / v0.1 release | **NOT DONE / NOT ACCEPTED / NOT RELEASED** |

## 5. Push/CI attempt

`gh auth status` reports the local GitHub token is invalid (X29). The repository
remote is SSH (`git@github.com:yduchesne/quervant.git`); a branch push is
attempted after the documentation commit. If the push succeeds, the maintainer
must create/observe the PR and CI at the exact immutable head SHA. No CI status
is claimed until observed.

## 6. Authorized exceptions

None requested and none granted. The benchmark gate remains open under X15; no
other gate was waived.
