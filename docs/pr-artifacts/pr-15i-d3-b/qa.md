# PR 15I-D3-B — QA

All checks were executed locally on the candidate code state
`48d9abf3eeefbccb480d89eac95f6e6911e078d5` (production + tests) with tooling
freeze `155ebafafa29fb0e6b6cbf953f89445f4880fd2f`. No production, test,
manifest or CI-related file changed after that state; later commits are
documentation only. The table therefore reports the final code-bearing tree.

## Commands and results

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS, 0 warnings |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo test --workspace --all-targets` | PASS, 0 failed |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,496 passed, 0 failed, 0 ignored across 137 test binaries |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.85% lines** (reference: 87.79% regions, 92.17% functions) |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS, 0 warnings |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS, 0 failed |
| `cargo +1.85.0 doc --workspace --no-deps` | PASS |
| `python3 -m py_compile benchmarks/pr15i_d3_b/*.py` | PASS |
| `python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py' -v` | PASS — 61 tests (32 controller, 29 independent verifier V01–V28 + extras) |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests, 3 skipped |
| `git diff --check` | PASS |

Targeted D3-B suites (included above, run separately for evidence):
`cargo test -p quervant-core --lib d3b_tests` = 28/28 PASS;
`cargo test -p quervant-core --test pr15i_d3_b` = 10/10 PASS (I12 is ignored
without the `s3` feature and a real RustFS service).

Regression-sensitive existing suites that pass unchanged:
`c3_path_heap_exact_one_over`, `c3_path_batch_parity_and_memory_reject`, all
`b_tests` borrowed-keyword parity tests (including the malformed losing payload
test), cancellation/unwind, pagination and multi-segment tests.

## Integration boundaries

| Boundary | State |
|---|---|
| Real local `FsDirectory` commit, close, reopen, query (`i11`) | PASS |
| Real writer/commit/snapshot/PIT/delete/upsert (`i05`, `i07`) | PASS |
| Real branch, detached BASE and candidate worktrees, clean tracked trees | PASS |
| Real RustFS/S3 production adapter (I12) | **RUSTFS_PENDING** |
| Hosted CI | **CI_PENDING** (local-only session) |
| Independent human review | **REVIEW_PENDING** |

### RustFS blocker (exact)

`QUERVANT_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh` fails to start the pinned
image:

```text
Error: short-name "rustfs/rustfs@sha256:1803faef…" did not resolve to an alias
and no unqualified-search registries are defined in
"/etc/containers/registries.conf"
Error: no container with name or ID "quervant-rustfs" found: no such container
curl: (7) Failed to connect to 127.0.0.1 port 9000
```

podman-compose 1.0.6 / podman 4.9.3 cannot resolve the digest-pinned short name
and no registry is configured. Recorded as `RUSTFS_PENDING` (decision
`DBX-23`); it is not reported as a pass, and no fake or in-memory substitute is
claimed.

## Coverage detail

`cargo llvm-cov` reports 92.85% line coverage across all workspace production
crates (including `quervant-core`, `quervant-objectstore`,
`quervant-distributed`); no production module was excluded and the 85% floor was
not modified. The uncovered D3-B lines are the RustFS-gated I12 body and
defensive branches already uncovered before this change; the new filter,
duplicate-check, admission and observation code is exercised by the U/I/V
matrices and by the existing unified suites.

## Failure classification

No gate failed. Nothing was classified `INTRODUCED_REGRESSION`,
`FEATURE_DEFECT`, `DETERMINISTIC_PRE_EXISTING`, `NONDETERMINISTIC_FLAKY` or
`ENVIRONMENT_HARNESS` except the documented `RUSTFS_PENDING` environment
blocker. The A/A binary mismatch is a benchmark-environment structural blocker
(`MEASUREMENT_BLOCKED`), not a code test failure.
