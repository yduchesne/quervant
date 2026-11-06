# PR 15H-B fixup — QA

Append-only fixup record (the original B performance report is unchanged).

## Source state

- Branch: `dev/pr15h-a-linear-term-candidates`
- Starting HEAD: `f06f8280899217a0e2df9cf54e78f4f7ebfbbd34`
- Original candidate: `ae7e416a7d4d8a0ce179b64a15cafc2cb104f85e`
- Original tooling: `79593314aa0525a1bb7d5f30c900a70e890e728a`
- Original evidence (read-only, original tooling): baseline seal
  `28996cec…` PASS, paired seal `be76e32b…` PASS, sanitized performance
  `f0d5d083…` byte-identical.

## Fixup tests

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15h_b -p 'test_*.py'` | PASS — 33 tests (21 original + 12 BF-T) |
| `cargo test -p quervant-core --lib search::unified::b_tests` | PASS — 6 (incl. BF-U01–U06) |
| `cargo test -p quervant-core --test pr15h_b_sort_materialization` | PASS — 6 |
| `cargo test -p quervant-core --lib segment::column::b_keyword_view_tests` | PASS — 4 |
| `cargo test -p quervant-core --lib search::typed_compare::b_comparator_tests` | PASS — 3 |

## Stable toolchain (`1.98.1`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,339 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,343 passed, 0 failed, 79 ignored |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.70 % lines** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo build -p quervant-core --release` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed |
| `git diff --check` | PASS |

## MSRV (`cargo 1.85.0`)

| Command | Result |
|---|---|
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,343 passed |

## Real RustFS (pinned image, local podman)

| Suite | Result |
|---|---|
| `pr13_s3_rustfs` | PASS — 8 |
| `pr13_proxy_rustfs` | PASS — 5 |
| `pr13_remote` | PASS — 3 |
| `pr13_oracle` | PASS — 1 |
| `pr13_oracle_geo` | PASS — 1 |
| `pr15g_a/b/c/d_rustfs` | PASS — 1 each |
| `m1_batches` / `m2_patches` | PASS — 1 each |
| `m3_delete_by_query` | PASS — 3/3 |
| `m5_mutation_qualification` | PASS — 3/3 |
| `pr13_remote_proxy` | PASS — 7 |
| `pr13_crash_rustfs k0` | PASS — 5 |
| `pr13_crash_rustfs k05` | PASS — 10/10 |

## Performance evidence

No new timed campaign was run. The original B performance numbers
(+6.266 ms K100, +12.213 ms K10 median paired differences) remain the accepted
historical result from the sealed `paired-01` campaign; this fixup changes no
production query code and no benchmark constants.

## Hosted CI

**`CI_PENDING`.** No push/PR/merge was performed; exact-final-HEAD hosted
`rust`/`msrv`/`rustfs` jobs remain pending.
