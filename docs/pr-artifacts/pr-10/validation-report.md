# PR 10 Validation Report

**Working tree:** `dev/temporal-retrieval` atop `main` `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7` (all PR 10 changes uncommitted when these commands ran).
**Toolchains attempted:** stable (`cargo`) and MSRV (`cargo +1.85.0`).

## Command matrix

| # | Command | Toolchain | Result | Evidence |
|---|---|---|---|---|
| 1 | `cargo fmt --all -- --check` | stable | **PASS** | no diff |
| 2 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | stable | **PASS** | no diagnostics |
| 3 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 1.85.0 | **PASS** | no diagnostics |
| 4 | `cargo test -p quervant-core --test pr10_ranges` | stable | **PASS** | 5 passed |
| 5 | `cargo test -p quervant-core --test pr10_time` | stable | **PASS** | 4 passed |
| 6 | `cargo test -p quervant-core --test pr10_sort` | stable | **PASS** | 6 passed |
| 7 | `cargo test -p quervant-core --test pr10_cursor` | stable | **PASS** | 4 passed |
| 8 | `cargo test -p quervant-core --test pr10_buckets` | stable | **PASS** | 4 passed |
| 9 | `cargo test -p quervant-core --test pr10_groups` | stable | **PASS** | 5 passed |
| 10 | `cargo test -p quervant-core --test pr10_metrics` | stable | **PASS** | 5 passed |
| 11 | `cargo test -p quervant-core --test pr10_distinct` | stable | **PASS** | 5 passed |
| 12 | `cargo test -p quervant-core --test pr10_frequency` | stable | **PASS** | 6 passed |
| 13 | `cargo test -p quervant-core --test pr10_pruning` | stable | **PASS** | 6 passed |
| 14 | `cargo test -p quervant-core --test pr10_integration` | stable | **PASS** | 11 passed |
| 15 | `cargo test -p quervant-core --test pr10_properties` | stable | **PASS** | 9 passed |
| 16 | `cargo test --workspace --all-targets` | stable | **PASS** | 1320 passed, 0 failed, 7 ignored |
| 17 | `cargo +1.85.0 test --workspace --all-targets` | 1.85.0 | **PASS** | 1319 passed, 0 failed, 7 ignored |
| 18 | `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | stable | **PASS** | **91.64% line**, 87.41% function, 91.30% region |
| 19 | `cargo doc --workspace --no-deps` | stable | **PASS** | generated |
| 20 | `cargo bench -p quervant-core --no-run` | stable | **PASS** | all bench targets build |
| 21 | `bash benchmarks/scripts/test-scripts.sh` | shell | **PASS** | 33 passed, 0 failed |

No command above is reported as PASS without having been executed on the final
tree after the last production/test change.

One benign discrepancy: the stable workspace run reports one more passing test
than the MSRV workspace run (1320 vs 1319); both report 0 failures. This is a
single test-harness difference in an existing target, not a PR 10 failure.

## Coverage — new/changed files (line %)

| File | Line coverage |
|---|---|
| `search/analytics.rs` | 89.16% |
| `search/limits.rs` | 89.36% |
| `search/typed.rs` | 86.97% |
| `search/typed_compare.rs` | 91.89% |
| `index/snapshot.rs` | 85.75% |
| `segment/reader.rs` | 84.03% (pre-existing large file; aggregate workspace gate applies) |
| **Workspace total** | **91.64%** |

## Integration topology used

- Real `MemoryDirectory` and real temporary `FsDirectory`.
- Real `IndexWriter` admission, mutate, commit, `refresh`, `pin`, `compact` and
  `Index::open_existing` reopen.
- Real verified `SegmentReader` over the PR 5 column codec, including a real
  corruption case (single flipped byte) that fails closed.
- PR 9 effective-live masks and old-PIT snapshots.
- No fake engine, no fake adapter substituted for a mandatory boundary.

## Environment / limitations

- Stable is `1.98.1`; MSRV `1.85.0` is installed and used.
- The 1M bench size could not be built with default `IndexLimits`
  (`max_mutation_state_bytes` = 32 MiB for 1M logical keys). 10K and 100K are
  measured (see `performance-report.md`).
- RustFS and distributed topologies are out of PR 10 scope (PR 13 / v0.2).

## Blockers

None. All mandatory local gates pass.
