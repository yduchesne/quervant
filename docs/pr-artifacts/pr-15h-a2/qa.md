# PR 15H-A2 — QA record

## Tested state

- Branch: `dev/pr15h-a2-cardinality-gated-linear`
- A2 base: `7a136f7f299c2f460401b9d92dcef37d219ea98c`
- Measured candidate: `569132dace8d92c103dfdebd5d24167d65c0c0c0`
- Code-bearing final (rollback): `29f2a372fdc1b4b3316409fc7ff218fb761ba5fb`
- Documentation/test metadata is a follow-up commit on the same code tree.
- Working tree: clean; raw evidence ignored under `target/pr15h-a2/`.

## Stable toolchain (`rustc 1.98.1`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,320 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,324 passed, 0 failed, 79 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.72 % lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo build -p quervant-core --release` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `python3 -m py_compile benchmarks/pr15h_a2/{run.py,test_run.py}` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15h_a2 -p 'test*.py'` | PASS — 26 passed |
| `cargo test -p quervant-core --test pr15h_a2_dispatch` | PASS — 8 passed |
| `cargo test -p quervant-core --test pr15h_a_candidate_materialization` | PASS — 6 passed |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,324 passed |

## Real RustFS

Pinned image `docker.io/rustfs/rustfs@sha256:1803faef…` via local `podman`:

| Suite | Result |
|---|---|
| `pr13_s3_rustfs` | PASS — 8 |
| `pr13_proxy_rustfs` | PASS — 5 |
| `pr13_remote` | PASS — 3 |
| `pr13_oracle` | PASS — 1 |
| `pr15g_a_rustfs` | PASS — 1 |
| `pr15g_b_rustfs` | PASS — 1 |
| `pr13_remote_proxy` | PASS — 7 |
| `pr13_crash_rustfs k0` | PASS — 5 |
| `pr13_crash_rustfs k05` | PASS — 10/10 |

## Hosted CI

**`CI_PENDING` (A2-D71).** No branch push or hosted workflow was authorized or
performed. The exact-final-HEAD `rust`, `msrv` and `rustfs` jobs still need to
pass in CI; equivalent local commands (including real RustFS) passed.

## Failures

None. No `INTRODUCED_REGRESSION`, `FEATURE_DEFECT`, `FLAKY` or
`ENVIRONMENT_OR_HARNESS` failure occurred.
