# PR 15H-B — QA and CI record

## Tested state

- Branch: `dev/pr15h-a-linear-term-candidates`
- Baseline: `6e47eed3f35a5fad8db6dab24c66f386567e95c0`
- Candidate: `ae7e416a7d4d8a0ce179b64a15cafc2cb104f85e`
- Working tree: clean; raw evidence ignored under `target/pr15h-b/`.

## Stable toolchain (`1.98.1`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,338 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,342 passed, 0 failed, 79 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.68 % lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo build -p quervant-core --release` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed |
| `python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py'` | PASS — 21 tests |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | PASS — 6 |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,342 passed |

## Real RustFS (pinned image, local podman)

| Suite | Result |
|---|---|
| `pr13_s3_rustfs` | PASS — 8 |
| `pr13_proxy_rustfs` | PASS — 5 |
| `pr13_remote` | PASS — 3 |
| `pr13_oracle` | PASS — 1 |
| `pr13_oracle_geo` | PASS — 1 |
| `pr15g_a_rustfs` | PASS — 1 |
| `pr15g_b_rustfs` | PASS — 1 |
| `pr15g_c_rustfs` | PASS — 1 |
| `pr15g_d_rustfs` | PASS — 1 |
| `m1_batches` | PASS — 1 |
| `m2_patches` | PASS — 1 |
| `m3_delete_by_query` | PASS — 3/3 |
| `m5_mutation_qualification` | PASS — 3/3 |
| `pr13_remote_proxy` | PASS — 7 |
| `pr13_crash_rustfs k0` | PASS — 5 |
| `pr13_crash_rustfs k05` | PASS — 10/10 |

## Hosted CI

**`CI_PENDING` (HB-D71).** The branch was not pushed and no hosted workflow was
run. Exact-final-HEAD `rust`/`msrv`/`rustfs` jobs remain required for merge
readiness; no green claim or merge is implied.

## Failures

None. The B controller's synthetic gate tests cover all absolute boundaries,
blocked-vs-accepted behavior, seal/report tamper and source-scope refusals.
