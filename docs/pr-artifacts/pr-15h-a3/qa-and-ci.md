# PR 15H-A3 — QA and CI record

## Tested state

- Branch: `dev/pr15h-a3-sparse-regression-investigation`
- Base: `d398af5e2dc354f19b209ce53df62f78d12e26f8`
- Tooling commit: `7e23335ef1862d27801b198965ebc4a4804becde`
- Final HEAD: documentation follow-up on the same code tree.
- Working tree: clean; raw evidence ignored under `target/pr15h-a3/`.
- Production search: byte-identical to accepted `7a136f7`/`ddcbe778`.

## A3 controller and historical controllers

| Command | Result |
|---|---|
| `python3 -m py_compile benchmarks/pr15h_a3/{run.py,test_run.py}` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15h_a3 -p 'test_*.py'` | PASS — 28 tests |
| `python3 -m unittest discover -s benchmarks/pr15h_a2 -p 'test*.py'` | PASS — 26 tests |
| `python3 -m unittest discover -s benchmarks/pr15h_a -p 'test_*.py'` | PASS — 21 tests |
| `python3 benchmarks/pr15h_a3/run.py verify … --campaign aa-01` | PASS |

## Stable toolchain (`1.98.1`)

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
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| `cargo test -p quervant-core --test pr15h_a_candidate_materialization` | PASS — 6 |
| `cargo test -p quervant-core --test pr15h_a2_dispatch` | PASS — 8 |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,324 passed |

## Real RustFS (regression only)

Pinned image via local `podman`: s3 8, proxy 5, pr13_remote 3, pr13_oracle 1,
pr15g_a 1, pr15g_b 1, remote_proxy 7, crash k0 5, crash k05 10/10 — all PASS.
A3 changes no storage/remote code; these are regression evidence, not a new
feature-specific acceptance test.

## Profiling

`perf` is unavailable for the running WSL kernel; `perf stat` exits 2.
Recorded `PROFILE_UNAVAILABLE`; no packages were installed (A3-D44).

## Hosted CI

**`CI_PENDING` (A3-D72).** The branch was not pushed and no hosted workflow was
run. Exact-final-HEAD `rust`/`msrv`/`rustfs` jobs remain required for merge
readiness. No approval or merge is implied.

## Failures

None. There were no test, lint, coverage, documentation or RustFS failures.
Measurement status is separately `MEASUREMENT_BLOCKED_AA_CONTROL`.
