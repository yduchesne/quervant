# PR 15H-A — QA and CI record

## Tested state

- Branch: `dev/pr15h-a-linear-term-candidates`
- Baseline / inspected `main`: `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
- Candidate (measured): `dce8f02405e6541d478c2072a0332af192ed2945`
- Rollback (code-bearing final): `3eae252f7777b551f2eaf0289ea067957b1f7c74`
- This document and the other closeout artifacts are a documentation-only
  follow-up on the same code tree.
- Working tree: clean for tracked code; raw evidence is gitignored under
  `target/pr15h-a/`.

## Stable toolchain (`rustc 1.98.1`, `cargo 1.98.1`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,312 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,316 passed, 0 failed, 79 ignored (feature-gated RustFS suites run separately) |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.72 % line coverage** (88.11 % functions, 92.14 % regions) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo build -p quervant-core --release` | PASS (U24: no test-only witness in release) |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `python3 -m py_compile benchmarks/pr15h_a/{run.py,test_run.py}` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15h_a -p 'test_*.py'` | PASS — 21 passed |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`, workspace `rust-version = 1.85`, edition 2024)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 126 test binaries, 0 failures |

## Focused PR 15H-A suites

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib search::unified` (baseline smoke) | PASS — 46 passed |
| `cargo test -p quervant-core --lib search::execute` (baseline smoke) | PASS — 40 passed |
| `cargo test -p quervant-core --test pr15h_a_candidate_materialization` | PASS — 6 passed (candidate and post-rollback) |
| `cargo test -p quervant-core --lib search::execute::linear_term_tests` (candidate) | PASS — 8 passed |
| `cargo test -p quervant-core --lib search::unified::phase4_tests` (candidate) | PASS — 15 passed |

## Real RustFS acceptance

Pinned image `docker.io/rustfs/rustfs@sha256:1803faef…` run via local `podman`
on `127.0.0.1:9000` with the CI test credentials. All suites passed:

| Suite | Result |
|---|---|
| `quervant-objectstore --features s3 --test pr13_s3_rustfs` | PASS — 8 passed |
| `quervant-objectstore --features s3 --test pr13_proxy_rustfs` | PASS — 5 passed |
| `quervant-core --all-features --test pr13_remote` | PASS — 3 passed |
| `quervant-core --all-features --test pr13_oracle` | PASS — 1 passed |
| `quervant-core --all-features --test pr15g_a_rustfs` | PASS — 1 passed |
| `quervant-core --all-features --test pr15g_b_rustfs` | PASS — 1 passed |
| `quervant-core --all-features --test pr13_remote_proxy` | PASS — 7 passed |
| `quervant-core --all-features --test pr13_crash_rustfs k0` | PASS — 5 passed |
| `quervant-core --all-features --test pr13_crash_rustfs k05` | PASS — 10/10 repeated runs |

## Hosted CI

**PENDING (HA-D68).** No branch push or hosted workflow run was authorized or
performed. The exact-final-HEAD jobs `rust`, `msrv` and `rustfs` must still pass
in CI; the equivalent local commands (including real RustFS) passed above. This
is a deferred gate, not a green claim.

## Nonpass classification

None. There were no test, lint, coverage, documentation or real-RustFS failures.
The only open item is the hosted-CI gate above (`DEFER AND CONTINUE`); it blocks
PR acceptance but not the already-decided performance rejection/rollback.
