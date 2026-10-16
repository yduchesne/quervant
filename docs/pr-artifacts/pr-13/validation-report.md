# PR 13 — validation report

**Tested working tree:** `dev/rust-fs` on top of baseline
`653b412e0e7df8efe18602479b661629427fab57`, uncommitted at the time of these
runs. **Result: all executed local gates PASS. CI has not been observed. PR is
not DONE.**

Toolchains: stable (`rustc 1.98.1` per CI pin `dtolnay/rust-toolchain@master`) and
Rust `1.85.0` (workspace MSRV). Host: Linux x86_64.

## Commands and results

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | stable | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets` | stable | PASS — 1495 passed, 0 failed, 8 ignored |
| `cargo test --workspace --all-targets --all-features` | stable | PASS — 1499 passed, 0 failed, 19 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 1.85.0 | PASS — 1499 passed, 0 failed, 19 ignored |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | PASS — **91.44%** line coverage |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS — **90.36%** line coverage |
| `cargo doc --workspace --no-deps` | stable | PASS |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS |
| `cargo bench --workspace --no-run` | stable | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | stable | PASS — 33 script tests |
| `git diff --check` | — | PASS (no whitespace errors) |

Coverage scope: all production Rust workspace crates (`quervant-core`,
`quervant-objectstore`, `quervant-distributed`), no exclusions. The all-features
figure includes the opt-in `s3` adapter, whose network paths are exercised
primarily by the ignored real-RustFS tests and are therefore lightly instrumented
(`s3.rs` 23.49% line coverage); the workspace floor still passes.

## Real RustFS acceptance

Pinned image:
`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
(podman rootless, ephemeral data volume, endpoint `http://127.0.0.1:9000`,
test-only credentials).

| Command | Result |
|---|---|
| `cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1` | PASS — 8 passed, 0 failed |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | PASS — 3 passed, 0 failed |

Environment for both:
`QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000`,
`QUERVANT_RUSTFS_REGION=us-east-1`,
`QUERVANT_RUSTFS_BUCKET=quervant-pr13[-core]`,
`QUERVANT_RUSTFS_ACCESS_KEY=quervanttest`,
`QUERVANT_RUSTFS_SECRET_KEY=quervantsecret`. Secrets are test-only and are not
logged; no public AWS endpoint is used.

## Ignored / skipped tests

- 8 ignored by default (`cargo test --workspace --all-targets`): the pre-existing
  process-restart suites plus the new real-RustFS tests.
- 19 ignored with `--all-features`: the additional real-RustFS object-store and
  core tests.

Ignored real-provider tests are executed explicitly above and are not counted as
PASS when skipped.

## Not executed

- GitHub Actions CI (no push observed).
- Real-RustFS interrupted-transfer fault proxy, crash-at-checkpoint
  separate-process tests, query-scoped pruning and benchmarks (see
  `benchmark-report.md`).

## Corrective pass rerun (supersedes the counts above)

Executed after the file-backed staging, cache-first hydration, timed retry and
terminal-writer hardening. All commands run from the workspace root.

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable | PASS |
| `cargo +1.85.0 fmt --all -- --check` | 1.85.0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | PASS |
| `cargo test --workspace --all-targets --all-features` | stable | PASS — **1506 passed, 0 failed, 19 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 1.85.0 | PASS — **1506 passed, 0 failed, 19 ignored** |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS — **90.22%** line coverage |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | PASS — **91.25%** line coverage |
| `cargo doc --workspace --all-features --no-deps` | stable | PASS |
| `cargo bench --workspace --no-run` | stable | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | stable | PASS — 33 script tests |
| `git diff --check` | — | PASS |

Real RustFS (image
`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`):

| Command | Result |
|---|---|
| `cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1` | PASS — 8 passed |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored --test-threads=1` | PASS — 3 passed |

### Still not executed

- Real deterministic HTTP fault proxy in front of RustFS (M10/M11/T06/C09).
- Separate-process crash-at-checkpoint tests (C10/C11).
- Independent typed/time/JSON/geo/PIT reference oracle (V02–V05).
- Remote cold/warm benchmark lane (P01–P03).
- GitHub Actions CI.

## Final acceptance execution (H/K/O/P)

All commands run from the workspace root on native Linux. Toolchains: stable
(`1.98.1` per CI pin) and Rust `1.85.0` (MSRV). RustFS image
`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`.

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (+1.85.0) | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (+1.85.0) | PASS |
| `cargo test --workspace --all-targets` | PASS — 1504 passed, 0 failed, 8 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — **1508 passed, 0 failed, 38 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 1508 passed, 0 failed, 38 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **90.22%** lines |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **91.24%** lines |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33 script tests |
| `git diff --check` | PASS |

### New real-provider targets (explicit, ignored tests executed separately)

| Target | Command (env `QUERVANT_RUSTFS_*`, `-- --ignored --test-threads=1`) | Result |
|---|---|---|
| `pr13_s3_rustfs` | `cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs` | 8 passed |
| `pr13_proxy_rustfs` | `cargo test -p quervant-objectstore --features s3 --test pr13_proxy_rustfs` | 5 passed |
| `pr13_remote` | `cargo test -p quervant-core --all-features --test pr13_remote` | 3 passed |
| `pr13_remote_proxy` | `cargo test -p quervant-core --all-features --test pr13_remote_proxy` | 7 passed |
| `pr13_crash_rustfs k0` | `cargo test -p quervant-core --all-features --test pr13_crash_rustfs k0` | 4 passed |
| `pr13_oracle` | `cargo test -p quervant-core --all-features --test pr13_oracle` | 1 passed |
| `pr13_bench_remote` | `cargo test -p quervant-core --all-features --test pr13_bench_remote` | PASS (150.60 s, CSV emitted) |

### 10-iteration repetition (unique prefixes per iteration, 0 failures)

- `pr13_proxy_rustfs` (H01–H04, H06): 10 × 5 passed.
- `pr13_remote_proxy` (H06–H12): 10 × 7 passed.
- `pr13_crash_rustfs k0` (K01–K04): 10 × 4 passed.

Per-iteration logs were captured under `/tmp/p13_{obj,core,crash}_*.log` during
the run; each iteration used a distinct prefix derived from the process id and a
per-run nanosecond id.

### Not executed / not observed

- K05 (crash during partial ranged download) and O04–O06 (JSON/geo oracle).
- GitHub Actions on the final pushed SHA (no push from this environment).
- V08 remains DEFERRED pending maintainer approval.

## Final candidate SHA

The final acceptance evidence above was produced on the working tree committed as
`b6343f3a677374a7e9aa56eb662636b165ba56b7` on `dev/rust-fs` (parent `ae2036c`, baseline `main`
`653b412e0e7df8efe18602479b661629427fab57`). The benchmark raw measurements are
checked in at `benchmarks/reports/pr13-remote-benchmark.json`.

## Review-fixup validation (final candidate)

Executed after the review fixups (real timer, fail-closed env, K05, O04–O06).

| Command | Toolchain | Result |
|---|---|---|
| `cargo fmt --all -- --check` | stable + 1.85 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable + 1.85 | PASS |
| `cargo test --workspace --all-targets` | stable | PASS — 1507 passed, 0 failed, 8 ignored |
| `cargo test --workspace --all-targets --all-features` | stable | PASS — **1511 passed, 0 failed, 41 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 1.85 | PASS — 1511 passed, 0 failed, 41 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | stable | PASS — **90.26%** lines |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | PASS — **91.32%** lines |
| `cargo doc`, `cargo bench --no-run`, benchmark scripts, `git diff --check` | stable | PASS |

### Real-provider targets (fail-closed, `--ignored --test-threads=1`)

| Target | Result |
|---|---|
| `pr13_s3_rustfs` | 8 passed |
| `pr13_proxy_rustfs` | 5 passed |
| `pr13_remote` | 3 passed |
| `pr13_remote_proxy` | 7 passed |
| `pr13_crash_rustfs k0` (K01–K05) | 5 passed |
| `pr13_oracle` | 1 passed |
| `pr13_oracle_geo` (O04–O06) | 1 passed |

K05 was repeated 10× with unique prefixes and deterministic checkpoints; 0
failures. H/K 10× repetitions from the previous pass remain valid regression
evidence for the unchanged cases.

### CI

`.github/workflows/ci.yml` now defines `rust` (default + all-features clippy/tests,
coverage, docs, bench, scripts), `msrv` (Rust 1.85), and `rustfs` (pinned RustFS
service, real acceptance, 10× K05) jobs. **GitHub Actions has not been observed
for the final SHA** because this environment cannot push; CI is **BLOCKED /
NOT OBSERVED**, not PASS.

### V08

Query-scoped pre-materialization pruning remains **DEFERRED — PENDING MAINTAINER
APPROVAL**. It is not marked PASS and PR 13 is not marked DONE.
